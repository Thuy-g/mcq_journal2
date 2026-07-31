############################################################################
# src/selection/legacy_overlap.py
#
# The RETAINED baseline: `legacy_overlap_baseline`.
#
# WHY THIS FILE EXISTS
#   OverlapStrict/OverlapLoose plus the old MMR-like step is the method Journal 2
#   must eventually COMPARE AGAINST. Deleting it would remove the baseline; leaving
#   it inside the extract entrypoint would leave the proposed path one accidental
#   call away from it. So it is moved here, named, and quarantined.
#
# HOW IT IS QUARANTINED
#   * Every public entry point emits a DeprecationWarning naming its replacement.
#   * Nothing here is imported by the proposed pilot path. The extract entrypoint
#     imports this module LAZILY, inside the legacy-overlap mode only.
#   * SPARQL, spaCy and sentence-transformers are imported INSIDE functions. In
#     particular `category_extractor_ClaudeWeb_v2` opens an on-disk SPARQL cache at
#     import time (its module-level `_CACHE = SparqlCache()`), so importing it at
#     module scope would create a cache file merely because this module was read —
#     which is what CLAUDE.md's "no import-time cache creation" forbids and what
#     would make the proposed path's "zero SPARQL" claim untestable.
#   * `LegacyOverlapRanker` refuses to run unless the caller passes
#     `i_understand_this_is_the_baseline_not_the_proposed_method=True`.
#
# WHAT IS FIXED HERE RELATIVE TO THE ORIGINAL
#   * the edge-set cache is keyed by (KG identity, node, use_in, schema) — AUDIT
#     item EX-4, via src/selection/observed_facts.py;
#   * IN facts are reported with `counterpart_uri`, never an unconditional
#     `object` — AUDIT item EX-12;
#   * candidate sorting has a total, deterministic tiebreak — AUDIT item EX-13.
#
# WHAT IS NOT FIXED HERE, ON PURPOSE
#   The scientific defects of the baseline are LEFT AS THEY WERE, because a
#   baseline that has been quietly improved is not the baseline anyone published:
#     EX-3   `legacy_single_fact_common_filter()` still requires a non-empty
#            intersection-free remainder rather than solving set cover;
#     EX-5   `score_norm` is still computed and still not used for ordering;
#     EX-6   `distinguishing_facts()` still reads absence as contrast, which is
#            unsound under the Open-World Assumption;
#     EX-7   the MMR step still measures diversity over EDGE sets, so it is NOT
#            rationale-aware and must never be described as such.
#   Each is marked at its definition. The corrected treatments belong to the
#   proposed path and to Prompt 8E, not to a retrofitted baseline.
############################################################################

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
import warnings
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from selection.contracts import (
    DIRECTION_IN,
    DIRECTION_OUT,
    RANKER_LEGACY_OVERLAP_BASELINE,
)
from selection.observed_facts import (
    DIRECTION_CODE_IN,
    DIRECTION_CODE_OUT,
    EdgeSetCache,
    observed_edge_set,
)

# --- Baseline parameters (unchanged from the original extract file) --------
ALPHA = 1.0            # OverlapStrict weight
BETA = 0.5             # OverlapLoose weight. NOT the LRoleSim decay factor.
THETA = 0.60           # SBERT threshold for "near-synonymous objects"
K_DISTRACTORS = 3
LAMBDA_MMR = 0.75
MAX_REDUNDANCY = 0.90
MAX_CANDIDATES = 300
ABSTRACT_BATCH = 50
SBERT_MODEL_NAME = "all-MiniLM-L6-v2"
ABSTRACT_CACHE = os.environ.get("ABSTRACT_CACHE", "./abstract_cache.sqlite")

# Direction codes, re-exported under the legacy spelling so old callers keep
# working. Declared IN-first to match the LRoleSim kernel (AUDIT item API-1).
IN, OUT = DIRECTION_CODE_IN, DIRECTION_CODE_OUT

# Non-entity pages that must never become distractors.
_NON_ENTITY_RE = re.compile(
    r"/(List_of_|Lists_of_|Category:|Template:|Portal:|File:|Index_of_)"
    r"|\(disambiguation\)$"
)

BASELINE_NAME = RANKER_LEGACY_OVERLAP_BASELINE


class LegacyBaselineMisuseError(Exception):
    """The baseline was invoked as though it were the proposed method."""


def _deprecated(what: str, instead: str) -> None:
    warnings.warn(
        f"{what} belongs to the retained baseline {BASELINE_NAME!r} and is not "
        f"part of the proposed Journal-2 path. Use {instead} instead.",
        DeprecationWarning,
        stacklevel=3,
    )


# ==========================================================================
# 1) EDGE SETS  (corrected cache identity; see AUDIT item EX-4)
# ==========================================================================

#: Baseline-local cache, separate from the proposed path's, so a baseline run can
#: never populate or perturb the proposed path's memoisation.
LEGACY_EDGESET_CACHE = EdgeSetCache()


def extended_edgeset(node_idx: int, kg, use_in: bool = True) -> frozenset:
    """{(predicate, direction, counterpart)} for one node.

    Behaviour is unchanged; the CACHE IDENTITY is fixed. The original keyed this
    memo by node index alone, so the first `use_in` seen for a node decided every
    later call, and a second KG in the same process inherited the first KG's
    edges (AUDIT item EX-4, test T2.1).
    """
    return observed_edge_set(node_idx, kg, use_in=use_in,
                             cache=LEGACY_EDGESET_CACHE)


def group_by_key(edgeset: frozenset) -> dict[tuple, tuple]:
    """{(predicate, direction): sorted counterparts}.

    Counterparts are returned sorted rather than as a set: the original returned
    raw sets, so the matching matrix below was built in set-iteration order.
    """
    grouped: dict[tuple, set] = {}
    for predicate, direction, counterpart in edgeset:
        grouped.setdefault((predicate, direction), set()).add(counterpart)
    return {key: tuple(sorted(value)) for key, value in sorted(grouped.items())}


# ==========================================================================
# 2) ABSTRACT + EMBEDDING STORE  (network and model; baseline only)
# ==========================================================================

class AbstractStore:
    """Batched DBpedia abstract retrieval plus SBERT encoding, cached on disk.

    NETWORK AND MODEL BEARING. Constructing this opens an SQLite cache; using it
    issues SPARQL and may download an SBERT model. The proposed pilot path never
    constructs one, which is asserted by the Prompt-8D test suite.
    """

    def __init__(self, path: str = ABSTRACT_CACHE, lang: Optional[str] = None):
        _deprecated("AbstractStore",
                    "the proposed path, which uses no abstracts and no SBERT")
        if lang is None:
            from category_extractor_ClaudeWeb_v2 import DBPEDIA_LANG
            lang = DBPEDIA_LANG
        self.lang = lang
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS abs (uri TEXT PRIMARY KEY, txt TEXT)")
        self._conn.commit()
        self._vec: dict[str, object] = {}
        self._model = None

    # ---- text layer ------------------------------------------------------
    def _read_cache(self, uris: Sequence[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        with self._lock:
            for i in range(0, len(uris), 400):
                chunk = uris[i:i + 400]
                q = "SELECT uri, txt FROM abs WHERE uri IN ({})".format(
                    ",".join("?" * len(chunk)))
                for u, t in self._conn.execute(q, chunk):
                    out[u] = t
        return out

    def _write_cache(self, pairs: dict[str, str]) -> None:
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO abs VALUES (?,?)", list(pairs.items()))
            self._conn.commit()

    def fetch_abstracts(self, uris: Iterable[str]) -> dict[str, str]:
        """One VALUES query per 50 URIs. NETWORK."""
        from category_extractor_ClaudeWeb_v2 import run_sparql

        uris = list(dict.fromkeys(uris))
        have = self._read_cache(uris)
        missing = [u for u in uris if u not in have]

        for i in range(0, len(missing), ABSTRACT_BATCH):
            chunk = missing[i:i + ABSTRACT_BATCH]
            values = " ".join(f"<{u.strip('<>')}>" for u in chunk)
            query = f"""
PREFIX dbo: <http://dbpedia.org/ontology/>
SELECT ?s ?abs WHERE {{
  VALUES ?s {{ {values} }}
  ?s dbo:abstract ?abs .
  FILTER(lang(?abs) = '{self.lang}')
}}
"""
            res = run_sparql(query)
            if res is None:
                # A FAILED query must not be cached as "no abstract": that would
                # make a transient 502 permanent. Distinct from a successful
                # zero-result, which IS cached below.
                print(f"  [WARN] skipping {len(chunk)} URIs after SPARQL failure "
                      f"(will retry on a later run)")
                continue
            found: dict[str, str] = {}
            for b in res["results"]["bindings"]:
                found[f"<{b['s']['value']}>"] = b["abs"]["value"][:1000]
            for u in chunk:
                found.setdefault(u, "")
            self._write_cache(found)
            have.update(found)
        return have

    # ---- vector layer ----------------------------------------------------
    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(SBERT_MODEL_NAME)
            except Exception as e:                      # noqa: BLE001
                print(f"[WARN] sentence-transformers unavailable: {e}")
                self._model = False
        return self._model or None

    def prepare(self, uris: Iterable[str]) -> None:
        uris = [u for u in dict.fromkeys(uris) if u not in self._vec]
        if not uris:
            return
        texts = self.fetch_abstracts(uris)
        model = self._get_model()
        if model is None:
            return
        todo = [u for u in uris if texts.get(u)]
        if not todo:
            return
        embs = model.encode([texts[u] for u in todo], convert_to_tensor=True,
                            batch_size=64, show_progress_bar=False)
        for u, e in zip(todo, embs):
            self._vec[u] = e

    def sim(self, uri_a: str, uri_b: str) -> float:
        if uri_a == uri_b:
            return 1.0
        va, vb = self._vec.get(uri_a), self._vec.get(uri_b)
        if va is None or vb is None:
            # AUDIT item EX-10: this conflates "no data" with "not similar".
            # Left as-is — it is baseline behaviour.
            return 0.0
        from sentence_transformers import util
        return float(util.cos_sim(va, vb)[0][0])


# ==========================================================================
# 3) OVERLAP STRICT / LOOSE
# ==========================================================================

def overlap_strict(a_edges: frozenset, d_edges: frozenset) -> int:
    """Count of exactly matching (predicate, direction, counterpart) triples."""
    return len(a_edges & d_edges)


def _max_matching(weights: list[list[float]]) -> float:
    """Total weight of a maximum matching. scipy -> munkres -> greedy.

    AUDIT item EX-11: the greedy third branch is NOT optimal, so a machine without
    scipy and without munkres produces different numbers. Retained unchanged as
    baseline behaviour; the solver actually used is not recorded here either.
    """
    if not weights or not weights[0]:
        return 0.0
    try:
        import numpy as np
        from scipy.optimize import linear_sum_assignment
        w = np.array(weights)
        r, c = linear_sum_assignment(-w)
        return float(w[r, c].sum())
    except Exception:                                   # noqa: BLE001
        pass
    try:
        from munkres import Munkres
        m = Munkres()
        neg = [[-x for x in row] for row in weights]
        return float(sum(weights[r][c] for r, c in m.compute(neg)))
    except Exception:                                   # noqa: BLE001
        pass
    used_r: set[int] = set()
    used_c: set[int] = set()
    total = 0.0
    cells = sorted(
        ((weights[i][j], i, j)
         for i in range(len(weights)) for j in range(len(weights[0]))),
        key=lambda t: (-t[0], t[1], t[2]),
    )
    for v, i, j in cells:
        if i not in used_r and j not in used_c:
            used_r.add(i)
            used_c.add(j)
            total += v
    return total


def overlap_loose(a_edges: frozenset, d_edges: frozenset, kg,
                  store: AbstractStore, theta: float = THETA) -> float:
    """Loose similarity: same (predicate, direction), near-synonymous counterparts."""
    a_only, d_only = a_edges - d_edges, d_edges - a_edges
    ga, gd = group_by_key(a_only), group_by_key(d_only)

    total = 0.0
    for key in sorted(set(ga) & set(gd)):
        la = [_uri(kg, o) for o in ga[key]]
        ld = [_uri(kg, o) for o in gd[key]]
        w = [[(s if (s := store.sim(x, y)) >= theta else 0.0) for y in ld]
             for x in la]
        total += _max_matching(w)
    return total


def _uri(kg, index: int) -> str:
    getter = getattr(kg, "uri", None) or getattr(kg, "uri_for_index")
    return getter(index)


# ==========================================================================
# 4) CANDIDATE SCORING
# ==========================================================================

@dataclass
class CandidateScore:
    idx: int
    uri: str
    strict: int = 0
    loose: float = 0.0
    score: float = 0.0
    score_norm: float = 0.0
    n_distinguishing: int = 0
    rejected: Optional[str] = None


def rank_candidates(answer_idx: int, cand_idx: Sequence[int], kg,
                    store: AbstractStore, alpha: float = ALPHA,
                    beta: float = BETA, theta: float = THETA,
                    use_in: bool = True) -> list[CandidateScore]:
    """Score every candidate by OverlapScore. BASELINE ONLY.

    `beta` here is OverlapLoose's weight, NOT the LRoleSim decay factor. The two
    are different quantities that share a name in this project, which is why
    src/lrolesim/adapter.py refuses a keyword called `beta` outright.

    AUDIT item EX-5 is deliberately preserved: `score_norm` is computed and then
    never used for ordering, so high-degree entities still win on raw `score`.
    """
    _deprecated("rank_candidates()",
                "selection.lrolesim_handoff.LRoleSimHandoffRanker")
    a_edges = extended_edgeset(answer_idx, kg, use_in)

    need = {_uri(kg, o) for _, _, o in a_edges}
    for d in cand_idx:
        need |= {_uri(kg, o) for _, _, o in extended_edgeset(d, kg, use_in)}
    t0 = time.time()
    store.prepare(need)
    print(f"  [prepare] {len(need)} objects, {time.time() - t0:.1f}s")

    out: list[CandidateScore] = []
    for d in cand_idx:
        if d == answer_idx:
            continue
        d_edges = extended_edgeset(d, kg, use_in)
        cs = CandidateScore(idx=d, uri=_uri(kg, d))
        if not d_edges:
            cs.rejected = "no edges in local KG"
            out.append(cs)
            continue
        cs.strict = overlap_strict(a_edges, d_edges)
        cs.loose = overlap_loose(a_edges, d_edges, kg, store, theta)
        cs.score = alpha * cs.strict + beta * cs.loose
        denom = max(len(a_edges), len(d_edges)) or 1
        cs.score_norm = cs.score / denom
        cs.n_distinguishing = len(distinguishing_facts(a_edges, d_edges))
        out.append(cs)

    # AUDIT item EX-13: the original sort had no tiebreak, so equal scores came
    # out in SPARQL result order. The URI tiebreak makes the order total.
    out.sort(key=lambda c: (c.rejected is not None, -c.score, c.uri))
    return out


# ==========================================================================
# 5) FEASIBILITY AND SET SELECTION
# ==========================================================================

def distinguishing_facts(a_edges: frozenset, d_edges: frozenset) -> set:
    """Facts the Answer HAS that the distractor does not.

    OPEN-WORLD WARNING (AUDIT item EX-6). This is a set difference over the pinned
    KG, so it treats a MISSING triple as a contrast. Under DBpedia's open-world
    assumption that is unsound: absence is not falsity. Retained unchanged as
    baseline behaviour. The proposed path calls this `observed_contrast` and
    Prompt 8E must classify evidence levels before anything is shown to a learner.
    """
    return a_edges - d_edges


def legacy_single_fact_common_filter(answer_idx: int,
                                     chosen: Sequence[CandidateScore],
                                     kg, use_in: bool = True) -> frozenset:
    """The original `common = a_edges - each distractor's edges` filter.

    DEPRECATED AND NOT CALLED BY THE PROPOSED PATH.

    AUDIT item EX-3: this keeps a question only when ONE fact distinguishes the
    Answer from EVERY chosen distractor simultaneously. That is strictly stronger
    than what a rationale needs — a rationale SET may use a different fact per
    distractor — so it discards valid questions and depresses the yield rate.

    The correct treatment is exact set cover, which is Prompt 8E's task. It is
    deliberately NOT implemented here: replacing the baseline's filter with set
    cover would destroy the baseline.
    """
    _deprecated("legacy_single_fact_common_filter()",
                "the Prompt-8E exact rationale set cover")
    common = extended_edgeset(answer_idx, kg, use_in)
    for candidate in chosen:
        common = common - extended_edgeset(candidate.idx, kg, use_in)
    return common


def select_distractor_set(answer_idx: int, ranked: Sequence[CandidateScore],
                          kg, k: int = K_DISTRACTORS, lam: float = LAMBDA_MMR,
                          use_in: bool = True) -> list[CandidateScore]:
    """Greedy MMR-like selection under a redundancy cap. BASELINE ONLY.

    NOT RATIONALE-AWARE (AUDIT item EX-7). `red` measures overlap between EDGE
    sets, not between rationale signatures, so this does not deliver "each
    distractor is excluded for a different reason" — describing it that way would
    be a claim the code does not support.
    """
    _deprecated("select_distractor_set()",
                "the Prompt-8E rationale-feasible selection")
    pool = [c for c in ranked
            if c.rejected is None and c.n_distinguishing > 0][:MAX_CANDIDATES]
    if not pool:
        return []

    max_score = max(c.score for c in pool) or 1.0
    chosen: list[CandidateScore] = []
    chosen_edges: list[frozenset] = []

    while pool and len(chosen) < k:
        best, best_val = None, -1e9
        for c in pool:
            rel = c.score / max_score
            if chosen_edges:
                e = extended_edgeset(c.idx, kg, use_in)
                red = max(len(e & ce) / (max(len(e), len(ce)) or 1)
                          for ce in chosen_edges)
            else:
                red = 0.0
            if red >= MAX_REDUNDANCY:
                continue
            val = lam * rel - (1 - lam) * red
            # Deterministic tiebreak: the original kept whichever candidate the
            # pool happened to list first.
            if best is None or val > best_val or (val == best_val and c.uri < best.uri):
                best, best_val = c, val
        if best is None:
            break
        chosen.append(best)
        chosen_edges.append(extended_edgeset(best.idx, kg, use_in))
        pool.remove(best)

    common = legacy_single_fact_common_filter(answer_idx, chosen, kg, use_in)
    if not common:
        print("  [WARN] no single fact separates the Answer from the whole set "
              "-> baseline discards this question")
        return []
    return chosen


# ==========================================================================
# 6) END TO END  (baseline)
# ==========================================================================

def get_candidates_for_class(category: str, kg,
                             limit: int = MAX_CANDIDATES) -> list[int]:
    """Class members from DBpedia, filtered and mapped to local indices. NETWORK."""
    _deprecated("get_candidates_for_class()",
                "the frozen Week-1 mapping outputs")
    from category_extractor_ClaudeWeb_v2 import get_nodes_in_class

    members = get_nodes_in_class(category)
    out: list[int] = []
    seen: set[int] = set()
    idx = getattr(kg, "idx", None) or getattr(kg, "index_for_uri_or_none")
    for uri in members:
        if _NON_ENTITY_RE.search(uri):
            continue
        i = idx(uri)
        if i is not None and i not in seen:
            seen.add(i)
            out.append(i)
        if len(out) >= limit:
            break
    return out


def observed_fact_records(edges: Iterable[tuple[int, int, int]], kg) -> list[dict]:
    """Serialize edges with DIRECTION-CORRECT naming (AUDIT item EX-12).

    The original emitted `{"predicate", "direction", "object"}` for both
    directions. For an IN edge the third element is the SUBJECT, so calling it
    `object` produced records a verbalizer would state backwards.
    """
    records = []
    for predicate, direction, counterpart in sorted(edges):
        label = DIRECTION_OUT if direction == DIRECTION_CODE_OUT else DIRECTION_IN
        records.append({
            "predicate_uri": _uri(kg, predicate),
            "direction": label,
            "counterpart_uri": _uri(kg, counterpart),
        })
    return records


def build_choices(answer_uri: str, kg, store: AbstractStore, nlp=None,
                  k: int = K_DISTRACTORS, method: str = "combined") -> Optional[dict]:
    """The baseline's full Answer -> distractor-set path. NETWORK AND MODEL."""
    _deprecated("build_choices()",
                "the pilot-lrolesim-handoff mode of the extract entrypoint")
    from category_extractor_ClaudeWeb_v2 import rank_classes_for_answer

    idx = getattr(kg, "idx", None) or getattr(kg, "index_for_uri_or_none")
    a_idx = idx(answer_uri)
    if a_idx is None:
        print(f"[SKIP] {answer_uri} is not in the local KG")
        return None

    for cls in rank_classes_for_answer(answer_uri, method=method, nlp=nlp,
                                       verbose=False):
        cand = [c for c in get_candidates_for_class(cls.category, kg) if c != a_idx]
        if len(cand) < k + 2:
            print(f"  [class {cls.category}] only {len(cand)} candidates -> next class")
            continue

        ranked = rank_candidates(a_idx, cand, kg, store)
        chosen = select_distractor_set(a_idx, ranked, kg, k=k)
        if len(chosen) < k:
            print(f"  [class {cls.category}] only {len(chosen)}/{k} chosen -> next class")
            continue

        common = legacy_single_fact_common_filter(a_idx, chosen, kg)
        return {
            "ranker_name": BASELINE_NAME,
            "answer": answer_uri,
            "answer_idx": a_idx,
            "class": cls.category,
            "class_size": cls.count,
            "n_candidates": len(cand),
            "distractors": [vars(c) for c in chosen],
            # Named `observed_contrast_facts`, not `distinguishing_facts`: under
            # the Open-World Assumption these are facts observed for the Answer
            # and not observed for the distractors (CLAUDE.md item 8).
            "observed_contrast_facts": observed_fact_records(common, kg),
        }
    print(f"[FAIL] {answer_uri}: no class yielded enough distractors")
    return None


# ==========================================================================
# 7) THE BASELINE AS A NAMED RANKER
# ==========================================================================

class LegacyOverlapRanker:
    """CandidateRanker wrapper around OverlapStrict/OverlapLoose.

    Exists so the baseline is addressable by name and so a comparison table can be
    generated later. It is NOT wired into the Prompt-8D pilot path, it requires an
    explicit acknowledgement to construct, and running it needs the network.
    """

    name = RANKER_LEGACY_OVERLAP_BASELINE

    def __init__(self, kg, store: Optional[AbstractStore] = None, *,
                 i_understand_this_is_the_baseline_not_the_proposed_method: bool = False):
        if not i_understand_this_is_the_baseline_not_the_proposed_method:
            raise LegacyBaselineMisuseError(
                f"{self.name!r} is the RETAINED BASELINE, not the proposed "
                f"Journal-2 method. Construct it only with "
                f"i_understand_this_is_the_baseline_not_the_proposed_method=True, "
                f"and never report its output as proposed output."
            )
        _deprecated("LegacyOverlapRanker",
                    "selection.lrolesim_handoff.LRoleSimHandoffRanker")
        self._kg = kg
        self._store = store

    def ranking_for_answer(self, answer_uri: str):
        raise NotImplementedError(
            f"{self.name!r} scoring requires DBpedia abstracts and SBERT, which "
            f"Prompt 8D forbids. The baseline comparison run is a separate, "
            f"explicitly network-enabled task."
        )
