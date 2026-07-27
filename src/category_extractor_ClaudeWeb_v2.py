############################################################################
# category_extractor.py  (phiên bản viết lại — Journal 2) bởi Claude Chat trên Web
#
# Nhiệm vụ: với một Answer URI, tìm CLASS (dbc:...) tốt nhất để lấy ứng viên
# distractor.
#
# Thay đổi lớn so với bản cũ:
#   1) Số lần gọi SPARQL giảm từ (2 + N) xuống còn 2 cho mỗi Answer node.
#   2) Toàn bộ kết quả SPARQL được cache xuống đĩa (SQLite) -> chạy lần 2 gần
#      như tức thì, và cache này chính là "snapshot" để tái lập thí nghiệm.
#   3) Sửa lỗi trộn thang đo TF-IDF với SBERT trong method="combined".
#   4) Trả về DANH SÁCH XẾP HẠNG (không chỉ top-1) để pipeline có thể fallback.
#   5) Bỏ sentinel -999; dùng cơ chế loại bỏ tường minh + ghi lý do loại (audit
#      trail) để viết vào bài báo.
############################################################################

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Iterable, Optional, Sequence

from SPARQLWrapper import SPARQLWrapper, JSON

# ---------------------------------------------------------------------------
# 0) THAM SỐ CẤU HÌNH — gom về một chỗ để viết vào phần "Experimental Setup"
# ---------------------------------------------------------------------------

DBPEDIA_ENDPOINT = os.environ.get("DBPEDIA_ENDPOINT", "https://dbpedia.org/sparql")
DBPEDIA_LANG = os.environ.get("DBPEDIA_LANG", "en")          # "en" hoặc "ja"
CACHE_PATH = os.environ.get("SPARQL_CACHE", "./sparql_cache.sqlite")

SBERT_MODEL_NAME = "all-MiniLM-L6-v2"

MIN_CLASS_SIZE = 10        # class quá nhỏ -> không đủ ứng viên distractor
MAX_CLASS_SIZE = 5000      # class quá lớn (Living_people) -> không đặc trưng
TOTAL_ENTITIES = 6_000_000 # dùng cho IDF; xem ghi chú ở hàm _idf()

# Các category "hành chính"/"bảo trì" của Wikipedia: không mang nghĩa ngữ nghĩa.
# Lọc bằng regex TRƯỚC khi đếm -> tiết kiệm rất nhiều truy vấn.
JUNK_CATEGORY_PATTERNS = [
    r"^Living_people$", r"^\d{3,4}_births$", r"^\d{3,4}_deaths$",
    r"^Year_of_(birth|death)_", r"^People_from_", r"^Date_of_(birth|death)_",
    r"^(All|Articles|Pages|Wikipedia|CS1|Use_|Webarchive|Commons)",
    r"_stubs$", r"_missing$", r"_needing_", r"_with_unsourced_",
    r"^\d{1,2}(st|nd|rd|th)-century_(births|deaths)$",
]
_JUNK_RE = re.compile("|".join(JUNK_CATEGORY_PATTERNS))


# ---------------------------------------------------------------------------
# 1) CACHE SPARQL TRÊN ĐĨA
# ---------------------------------------------------------------------------

class SparqlCache:
    """Cache key=hash(endpoint+query) -> value=JSON string.

    Lý do dùng SQLite thay vì dict trong RAM: (a) sống sót qua các lần chạy
    lại; (b) chính là bằng chứng tái lập (reproducibility) nộp kèm bài báo —
    endpoint công cộng của DBpedia thay đổi theo thời gian, nên reviewer sẽ
    hỏi "làm sao tái lập?". Câu trả lời: publish file cache này.
    """

    def __init__(self, path: str = CACHE_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            " k TEXT PRIMARY KEY, v TEXT, ts REAL)"
        )
        self._conn.commit()

    @staticmethod
    def _key(endpoint: str, query: str) -> str:
        return hashlib.sha256(f"{endpoint}\n{query}".encode("utf-8")).hexdigest()

    def get(self, endpoint: str, query: str):
        k = self._key(endpoint, query)
        with self._lock:
            row = self._conn.execute("SELECT v FROM cache WHERE k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, endpoint: str, query: str, value) -> None:
        k = self._key(endpoint, query)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache VALUES (?,?,?)",
                (k, json.dumps(value), time.time()),
            )
            self._conn.commit()


_CACHE = SparqlCache()


def run_sparql(query: str, endpoint: str = DBPEDIA_ENDPOINT,
               retries: int = 6, timeout: int = 60):
    """Claude Code for VS Code:Chạy SPARQL với cache + retry + backoff. Trả về dict JSON hoặc None.

    HTTP 502/503/504 từ endpoint công cộng của DBpedia thường chỉ là quá tải
    TẠM THỜI (server-side), không phải lỗi truy vấn. Trước đây chỉ thử lại
    3 lần với backoff tối đa 4s -> hết hạn quá sớm khi server đang bận.
    Giờ thử lại nhiều hơn với backoff dài hơn (tối đa 60s) + jitter để tránh
    nhiều tiến trình cùng retry đúng lúc.
    """
    cached = _CACHE.get(endpoint, query)
    if cached is not None:
        return cached

    import random

    last_err = None
    for attempt in range(retries):
        try:
            sparql = SPARQLWrapper(endpoint)
            sparql.setReturnFormat(JSON)
            sparql.setTimeout(timeout)
            sparql.setQuery(query)
            result = sparql.query().convert()
            _CACHE.put(endpoint, query, result)
            return result
        except Exception as e:                      # noqa: BLE001
            last_err = e
            if attempt < retries - 1:
                wait = min(2 ** attempt, 60) + random.uniform(0, 1)
                print(f"  [SPARQL retry {attempt + 1}/{retries - 1}] {e} "
                      f"-> chờ {wait:.1f}s")
                time.sleep(wait)
    print(f"[SPARQL FAILED after {retries} tries] {last_err}\n{query[:200]}")
    return None


# ---------------------------------------------------------------------------
# 2) LẤY MỌI THỨ VỀ ANSWER NODE TRONG *MỘT* TRUY VẤN
# ---------------------------------------------------------------------------

@dataclass
class AnswerInfo:
    uri: str
    label: str = ""
    abstract: str = ""
    categories: list[str] = field(default_factory=list)   # dạng "dbc:Xxx"


def _strip_uri(uri: str) -> str:
    return uri.strip().strip("<>")


def fetch_answer_info(answer_uri: str, lang: str = DBPEDIA_LANG,
                      endpoint: str = DBPEDIA_ENDPOINT) -> AnswerInfo:
    """1 truy vấn duy nhất lấy: rdfs:label + dbo:abstract + tất cả dcterms:subject.

    Bản cũ tốn 2 truy vấn riêng (categories, abstract) và KHÔNG lấy label.
    """
    r = _strip_uri(answer_uri)
    query = f"""
PREFIX dct:  <http://purl.org/dc/terms/>
PREFIX dbo:  <http://dbpedia.org/ontology/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?cat ?label ?abs WHERE {{
  OPTIONAL {{ <{r}> rdfs:label ?label . FILTER(lang(?label) = '{lang}') }}
  OPTIONAL {{ <{r}> dbo:abstract ?abs . FILTER(lang(?abs) = '{lang}') }}
  OPTIONAL {{
    <{r}> dct:subject ?cat .
    FILTER(STRSTARTS(STR(?cat), "http://dbpedia.org/resource/Category:"))
  }}
}}
"""
    info = AnswerInfo(uri=f"<{r}>")
    res = run_sparql(query, endpoint)
    if not res:
        return info

    cats: set[str] = set()
    for b in res["results"]["bindings"]:
        if "label" in b and not info.label:
            info.label = b["label"]["value"]
        if "abs" in b and not info.abstract:
            info.abstract = b["abs"]["value"]
        if "cat" in b:
            cats.add("dbc:" + b["cat"]["value"].split("Category:")[-1])

    # Fallback label: lấy từ URI nếu DBpedia không có rdfs:label.
    if not info.label:
        info.label = _strip_uri(answer_uri).split("/")[-1].replace("_", " ")
    info.categories = sorted(cats)
    return info


def get_category_counts(categories: Sequence[str],
                        endpoint: str = DBPEDIA_ENDPOINT) -> dict[str, int]:
    """Đếm số entity của NHIỀU category bằng MỘT truy vấn (VALUES + GROUP BY).

    Bản cũ: N truy vấn nối tiếp (N = số category, thường 15-40)
            -> ~30 round-trip * ~0.5s = ~15s cho MỖI Answer node.
    Bản này: 1 truy vấn -> ~0.5-2s. Với 100 câu hỏi: tiết kiệm ~25 phút.
    """
    if not categories:
        return {}
    values = " ".join(
        f"<{c.replace('dbc:', 'http://dbpedia.org/resource/Category:')}>"
        for c in categories
    )
    query = f"""
PREFIX dct: <http://purl.org/dc/terms/>
SELECT ?cat (COUNT(DISTINCT ?x) AS ?c) WHERE {{
  VALUES ?cat {{ {values} }}
  ?x dct:subject ?cat .
}} GROUP BY ?cat
"""
    res = run_sparql(query, endpoint)
    counts = {c: 0 for c in categories}
    if not res:
        return counts
    for b in res["results"]["bindings"]:
        short = "dbc:" + b["cat"]["value"].split("Category:")[-1]
        counts[short] = int(b["c"]["value"])
    return counts


def get_nodes_in_class(category: str, limit: int = 2000,
                       endpoint: str = DBPEDIA_ENDPOINT) -> list[str]:
    """Lấy các entity thuộc một category (dùng ở Step 2 của pipeline)."""
    cat_uri = category.replace("dbc:", "http://dbpedia.org/resource/Category:")
    query = f"""
PREFIX dct: <http://purl.org/dc/terms/>
SELECT DISTINCT ?x WHERE {{ ?x dct:subject <{cat_uri}> . }} LIMIT {limit}
"""
    res = run_sparql(query, endpoint)
    if not res:
        return []
    return [f"<{b['x']['value']}>" for b in res["results"]["bindings"]]


# ---------------------------------------------------------------------------
# 3) KIỂM TRA RÒ RỈ ĐÁP ÁN (thay cho morphological_penalty cũ)
# ---------------------------------------------------------------------------

_lemmatizer = None
_wordnet = None


def _init_wordnet():
    """Nạp WordNet một lần duy nhất, và không làm sập chương trình nếu thiếu."""
    global _lemmatizer, _wordnet
    if _lemmatizer is not None:
        return
    try:
        from nltk.stem import WordNetLemmatizer
        from nltk.corpus import wordnet as wn
        wn.synsets("test")                      # ép nạp corpus để bắt lỗi sớm
        _lemmatizer, _wordnet = WordNetLemmatizer(), wn
    except Exception as e:                       # noqa: BLE001
        print(f"[WARN] WordNet unavailable ({e}); leak check dùng lemma rỗng.")
        _lemmatizer, _wordnet = False, False


def expand_token(word: str) -> set[str]:
    """{lemma(word)} ∪ {lemma của các từ đồng nghĩa}."""
    w = word.lower()
    _init_wordnet()
    if not _lemmatizer:
        return {w}
    out = {_lemmatizer.lemmatize(w)}
    for syn in _wordnet.synsets(w):
        for lem in syn.lemmas():
            out.add(lem.name().lower().replace("_", " "))
    return out


def remove_parenthetical(text: str) -> str:
    """'Makoto_Kobayashi_(physicist)' -> 'Makoto Kobayashi'."""
    text = text.replace("_", " ")
    return re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", "", text)).strip()


def leaks_answer(answer_label: str, category_label: str, nlp=None) -> Optional[str]:
    """Trả về LÝ DO nếu tên class làm lộ đáp án; None nếu an toàn.

    Ba tầng kiểm tra, từ rẻ đến đắt:
      (a) khớp chuỗi con  -> 'Albert Einstein' vs 'Albert Einstein Award'
      (b) trùng token danh từ riêng -> 'Einstein' xuất hiện ở cả hai
      (c) trùng lemma/synonym       -> 'Phosphoric acid' vs 'Phosphorus compounds'
    Khác bản cũ: chạy spaCy MỘT LẦN trên cả chuỗi (có ngữ cảnh) thay vì gọi
    nlp() cho từng token rời rạc — vừa nhanh hơn ~10 lần, vừa chính xác hơn.
    """
    a = remove_parenthetical(answer_label).lower()
    c = remove_parenthetical(category_label).lower()
    if not a or not c:
        return None

    if a in c or c in a:                                   # (a)
        return f"substring overlap ('{a}' vs '{c}')"

    a_proper, c_proper = set(), set()
    if nlp is not None:                                    # (b)
        for tok in nlp(remove_parenthetical(answer_label)):
            if tok.pos_ == "PROPN" and len(tok.text) >= 3:
                a_proper.add(tok.text.lower())
        for tok in nlp(remove_parenthetical(category_label)):
            if tok.pos_ == "PROPN" and len(tok.text) >= 3:
                c_proper.add(tok.text.lower())
        shared = a_proper & c_proper
        if shared:
            return f"shared proper noun {sorted(shared)}"

    a_exp: set[str] = set()                                # (c)
    for tok in a.split():
        if len(tok) >= 3:
            a_exp |= expand_token(tok)
    c_exp: set[str] = set()
    for tok in c.split():
        if len(tok) >= 3:
            c_exp |= expand_token(tok)
    shared_lemma = a_exp & c_exp
    if shared_lemma:
        return f"shared lemma/synonym {sorted(shared_lemma)[:3]}"
    return None


# ---------------------------------------------------------------------------
# 4) XẾP HẠNG CLASS
# ---------------------------------------------------------------------------

_sbert = None


def _get_sbert():
    """Nạp SBERT lazily: nếu chỉ chạy method='tfidf' thì không tốn 90MB RAM."""
    global _sbert
    if _sbert is None:
        try:
            from sentence_transformers import SentenceTransformer
            _sbert = SentenceTransformer(SBERT_MODEL_NAME)
        except Exception as e:                   # noqa: BLE001
            print(f"[WARN] sentence-transformers unavailable: {e}")
            _sbert = False
    return _sbert or None


def _idf(count: int, total: int = TOTAL_ENTITIES) -> float:
    """IDF chuẩn hoá về [0,1] để cộng được với cosine của SBERT."""
    count = max(count, 1)
    return math.log(total / count) / math.log(total)


@dataclass
class ClassCandidate:
    category: str
    count: int = 0
    sbert_sim: float = 0.0
    idf: float = 0.0
    score: float = 0.0
    n_local: Optional[int] = None      # số ứng viên thực có trong pickle cục bộ
    rejected: Optional[str] = None     # None = được giữ lại


def rank_categories(answer: AnswerInfo, method: str = "combined",
                    nlp=None, alpha: float = 0.7,
                    local_index: Optional[dict] = None,
                    min_size: int = MIN_CLASS_SIZE,
                    max_size: int = MAX_CLASS_SIZE) -> list[ClassCandidate]:
    """Trả về TẤT CẢ ứng viên class, đã chấm điểm và đánh dấu lý do loại."""
    cands = [ClassCandidate(category=c) for c in answer.categories]

    # (i) Lọc rác bằng regex TRƯỚC — tránh đếm những category vô nghĩa.
    survivors = []
    for cd in cands:
        if _JUNK_RE.search(cd.category.replace("dbc:", "")):
            cd.rejected = "junk/maintenance category"
        else:
            survivors.append(cd)

    # (ii) Đếm kích thước bằng MỘT truy vấn gộp.
    counts = get_category_counts([cd.category for cd in survivors])
    still = []
    for cd in survivors:
        cd.count = counts.get(cd.category, 0)
        cd.idf = _idf(cd.count)
        if cd.count < min_size:
            cd.rejected = f"too small ({cd.count} < {min_size})"
        elif cd.count > max_size:
            cd.rejected = f"too generic ({cd.count} > {max_size})"
        else:
            still.append(cd)

    # (iii) Loại class làm rò rỉ đáp án.
    kept = []
    for cd in still:
        reason = leaks_answer(answer.label,
                              cd.category.replace("dbc:", ""), nlp=nlp)
        if reason:
            cd.rejected = f"answer leak: {reason}"
        else:
            kept.append(cd)

    # (iv) Nếu có pickle cục bộ: chỉ giữ class thực sự đủ ứng viên OFFLINE.
    #      Đây là lỗi thực tế của bản cũ: chọn class có 25 node trên DBpedia
    #      nhưng chỉ 14 node tồn tại trong file TTL -> distractor quá ít.
    if local_index is not None:
        kept2 = []
        for cd in kept:
            members = get_nodes_in_class(cd.category)
            cd.n_local = sum(1 for m in members if m in local_index)
            if cd.n_local < min_size:
                cd.rejected = f"only {cd.n_local} members in local KG"
            else:
                kept2.append(cd)
        kept = kept2

    # (v) Chấm điểm: SBERT theo LÔ (một lần encode cho tất cả nhãn).
    if kept and method in ("sbert", "combined") and answer.abstract:
        model = _get_sbert()
        if model is not None:
            from sentence_transformers import util
            labels = [cd.category.replace("dbc:", "").replace("_", " ")
                      for cd in kept]
            embs = model.encode([answer.abstract] + labels,
                                convert_to_tensor=True, batch_size=64)
            sims = util.cos_sim(embs[0], embs[1:])[0]
            for cd, s in zip(kept, sims):
                cd.sbert_sim = float(s)

    for cd in kept:
        if method == "tfidf":
            cd.score = cd.idf
        elif method == "sbert":
            cd.score = cd.sbert_sim
        else:                       # combined — hai thành phần cùng thang [0,1]
            cd.score = alpha * cd.sbert_sim + (1 - alpha) * cd.idf

    kept.sort(key=lambda c: c.score, reverse=True)
    rejected = [c for c in cands if c.rejected]
    return kept + rejected


def choose_best_class_for_answer(answer_uri: str, method: str = "combined",
                                 nlp=None, local_index: Optional[dict] = None,
                                 verbose: bool = True) -> Optional[str]:
    """API tương thích ngược: trả về top-1 class hoặc None."""
    ranked = rank_classes_for_answer(answer_uri, method, nlp, local_index, verbose)
    return ranked[0].category if ranked else None


def rank_classes_for_answer(answer_uri: str, method: str = "combined",
                            nlp=None, local_index: Optional[dict] = None,
                            verbose: bool = True) -> list[ClassCandidate]:
    """API mới: trả về DANH SÁCH class hợp lệ (để fallback khi top-1 hỏng)."""
    info = fetch_answer_info(answer_uri)
    if not info.categories:
        if verbose:
            print(f"[NO CATEGORY] {answer_uri}")
        return []
    ranked = rank_categories(info, method=method, nlp=nlp, local_index=local_index)
    accepted = [c for c in ranked if c.rejected is None]
    if verbose:
        print(f"\n=== {answer_uri} ({info.label}) ===")
        for c in ranked:
            tag = "OK " if c.rejected is None else "XX "
            print(f" {tag}{c.category:<55} score={c.score:.4f} "
                  f"n={c.count:<7} idf={c.idf:.3f} sbert={c.sbert_sim:.3f}"
                  f"{'' if c.rejected is None else '  <- ' + c.rejected}")
        print(f" => BEST: {accepted[0].category if accepted else None}")
    return accepted


def batch_rank_classes(answer_uris: Iterable[str], method: str = "combined",
                       nlp=None, local_index: Optional[dict] = None,
                       max_workers: int = 6) -> dict[str, list[dict]]:
    """Chạy song song cho 100+ Answer node (I/O-bound -> dùng threads)."""
    from concurrent.futures import ThreadPoolExecutor
    out: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(rank_classes_for_answer, u, method, nlp,
                        local_index, False): u
            for u in answer_uris
        }
        for fut, uri in futures.items():
            try:
                out[uri] = [asdict(c) for c in fut.result()]
            except Exception as e:               # noqa: BLE001
                print(f"[ERROR] {uri}: {e}")
                out[uri] = []
    return out


# ---------------------------------------------------------------------------
# 5) DEMO
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        import spacy
        _nlp = spacy.load("en_core_web_sm")
    except Exception:                            # noqa: BLE001
        _nlp = None
        print("[WARN] spaCy không sẵn sàng; bỏ qua tầng kiểm tra danh từ riêng.")

    nodes = [
        "<http://dbpedia.org/resource/Eisaku_Satō>",
        "<http://dbpedia.org/resource/Yasunari_Kawabata>",
        "<http://dbpedia.org/resource/Kenzaburō_Ōe>",
        "<http://dbpedia.org/resource/Hideki_Yukawa>",
        "<http://dbpedia.org/resource/Yoichiro_Nambu>",
        "<http://dbpedia.org/resource/Shinya_Yamanaka>",
        "<http://dbpedia.org/resource/Susumu_Tonegawa>",    
        "<http://dbpedia.org/resource/Leo_Esaki>",
        "<http://dbpedia.org/resource/Ei-ichi_Negishi>",
        "<http://dbpedia.org/resource/Masatoshi_Koshiba>",
        "<http://dbpedia.org/resource/Ryōji_Noyori>",
        "<http://dbpedia.org/resource/Sin-Itiro_Tomonaga>",
        "<http://dbpedia.org/resource/Osamu_Shimomura>",
        "<http://dbpedia.org/resource/Toshihide_Maskawa>",
        "<http://dbpedia.org/resource/Makoto_Kobayashi_(physicist)>",
        "<http://dbpedia.org/resource/Hideki_Shirakawa>",
        "<http://dbpedia.org/resource/Kenichi_Fukui>",
        "<http://dbpedia.org/resource/Akira_Suzuki_(chemist)>",
        "<http://dbpedia.org/resource/Koichi_Tanaka>",

        "<http://dbpedia.org/resource/Carbon>",
        "<http://dbpedia.org/resource/Silicon>",
        "<http://dbpedia.org/resource/Vanadium>",
        "<http://dbpedia.org/resource/Neptunium>",
        "<http://dbpedia.org/resource/Sulfuric_acid>", 
        "<http://dbpedia.org/resource/Hydrochloric_acid>",

        "<http://dbpedia.org/resource/Epicurus>",
        "<http://dbpedia.org/resource/Zeno_of_Citium>",
        "<http://dbpedia.org/resource/Strato_of_Lampsacus>",

        "<http://dbpedia.org/resource/Aristotle>",
        "<http://dbpedia.org/resource/Adam_Smith>",
        "<http://dbpedia.org/resource/Immanuel_Kant>",
        "<http://dbpedia.org/resource/Adam_Smith>",
        
        "<http://dbpedia.org/resource/Albert_Einstein>",
        "<http://dbpedia.org/resource/Plato>",
        "<http://dbpedia.org/resource/Phosphoric_acid>",
    ]
    t0 = time.time()
    for nd in nodes:
        rank_classes_for_answer(nd, method="combined", nlp=_nlp)
    print(f"\nTổng thời gian: {time.time() - t0:.1f}s "
          f"(chạy lại lần 2 sẽ gần như tức thì nhờ cache)")