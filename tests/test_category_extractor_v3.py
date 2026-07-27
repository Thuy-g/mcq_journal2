############################################################################
# tests/test_category_extractor_v3.py
#
# Unit tests for src/category_extractor_ClaudeWeb_v3.py.
#
# Every test in this file is offline. SPARQL transport, the sentence encoder,
# the spaCy pipeline, the WordNet expander and the redirect resolver are all
# replaced by deterministic test doubles, so nothing here downloads a model or
# contacts an endpoint.
#
# Integration tests that would touch DBpedia are marked with
# ``@pytest.mark.integration`` AND gated on ``RUN_INTEGRATION=1``, so they stay
# deselected even without a pytest configuration file. They were not executed.
#
# Run:
#     python -m pytest -q tests/test_category_extractor_v3.py -m "not integration"
############################################################################

from __future__ import annotations

import hashlib
import os
import pathlib
import random
import re
import subprocess
import sys
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import category_extractor_ClaudeWeb_v3 as ce  # noqa: E402

RESOURCE = "http://dbpedia.org/resource/"
CATEGORY = ce.CATEGORY_PREFIX

ANSWER = RESOURCE + "Shinya_Yamanaka"
CAT_NOBEL = CATEGORY + "Japanese_Nobel_laureates"
CAT_BIO = CATEGORY + "Japanese_biologists"
CAT_STEM = CATEGORY + "Stem_cell_researchers"
CAT_LIVING = CATEGORY + "Living_people"

INTEGRATION = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="network integration tests run only with RUN_INTEGRATION=1",
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


_LIMIT_RE = re.compile(r"LIMIT\s+(\d+)")
_AFTER_RE = re.compile(r'FILTER\(STR\(\?x\)\s*>\s*"([^"]*)"\)')


class FakeSparqlClient:
    """Deterministic transport double, routed by the ``#qid:`` query marker.

    Member queries honour ``ORDER BY STR(?x)``, ``LIMIT`` and the keyset
    ``after`` filter exactly as an endpoint would — pages are sorted and sliced
    by the *string* form of the member URI, which is the same ordering the
    query asks for — so pagination and truncation behaviour can be tested
    offline.
    """

    def __init__(
        self,
        *,
        label=None,
        abstract=None,
        categories=(),
        member=False,
        counts=None,
        members=None,
        redirect=None,
        fail_qids=(),
        raise_qids=(),
        redirect_map=None,
    ):
        self.endpoint = "http://fake.invalid/sparql"
        self.language = "en"
        self.label = label
        self.abstract = abstract
        self.categories = tuple(categories)
        self.member = member
        self.counts = dict(counts or {})
        self.members = {k: list(v) for k, v in (members or {}).items()}
        self.redirect = redirect
        self.redirect_map = dict(redirect_map or {})
        self.fail_qids = set(fail_qids)
        self.raise_qids = set(raise_qids)
        self.calls: list[str] = []
        self.queries: list[str] = []

    @staticmethod
    def _cell(value):
        return {"value": str(value)}

    def run(self, query):
        qid = ce.query_id(query)
        self.calls.append(qid)
        self.queries.append(query)
        if qid in self.raise_qids:
            raise RuntimeError(f"simulated transport error for {qid}")
        if qid in self.fail_qids:
            return ce.QueryResult(
                status=ce.QueryStatus.FAILED,
                error=f"simulated endpoint failure for {qid}",
                endpoint=self.endpoint,
                language=self.language,
            )
        rows = self._rows(qid, query)
        return ce.QueryResult(
            status=ce.QueryStatus.OK if rows else ce.QueryStatus.ZERO_RESULTS,
            rows=tuple(rows),
            endpoint=self.endpoint,
            language=self.language,
        )

    def _rows(self, qid, query):
        if qid == "answer_info":
            row = {}
            if self.label is not None:
                row["label"] = self._cell(self.label)
            if self.abstract is not None:
                row["abs"] = self._cell(self.abstract)
            if self.member and "dct:subject <" in query:
                row["member"] = self._cell("yes")
            return [row] if row else []
        if qid == "answer_categories":
            return [{"cat": self._cell(c)} for c in self.categories]
        if qid == "category_counts":
            return [
                {"cat": self._cell(c), "c": self._cell(n)} for c, n in sorted(self.counts.items())
            ]
        if qid == "class_members":
            target = None
            for cat in self.members:
                if f"<{cat}>" in query:
                    target = cat
                    break
            page = sorted(self.members.get(target, []))
            after = _AFTER_RE.search(query)
            if after:
                page = [m for m in page if m > after.group(1)]
            limit = _LIMIT_RE.search(query)
            if limit:
                page = page[: int(limit.group(1))]
            return [{"x": self._cell(m)} for m in page]
        if qid == "class_members_batch":
            rows = []
            for cat in sorted(self.members):
                if f"<{cat}>" not in query:
                    continue
                for member in sorted(self.members[cat]):
                    rows.append({"cat": self._cell(cat), "x": self._cell(member)})
            limit = _LIMIT_RE.search(query)
            if limit:
                rows = rows[: int(limit.group(1))]
            return rows
        if qid == "redirect":
            for source, target in self.redirect_map.items():
                if f"<{source}>" in query:
                    return [{"target": self._cell(target)}]
            return [{"target": self._cell(self.redirect)}] if self.redirect else []
        raise AssertionError(f"unexpected query id: {qid!r}")


class FakeEncoder:
    """Deterministic hash-based embedder. No model, no download, no network."""

    def __init__(self, max_seq_length=256, width=16, affinities=None):
        self.name = "fake-encoder"
        self.max_seq_length = max_seq_length
        self.width = width
        self.affinities = dict(affinities or {})
        self.calls = 0
        self.encoded: list[str] = []

    def encode(self, texts):
        self.calls += 1
        self.encoded.extend(texts)
        return [self._vector(t) for t in texts]

    def _vector(self, text):
        if text in self.affinities:
            vector = [0.0] * self.width
            vector[0] = 1.0
            vector[1] = float(self.affinities[text])
            return vector
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [digest[i % len(digest)] / 255.0 for i in range(self.width)]


class _FakeToken:
    def __init__(self, text, pos):
        self.text = text
        self.pos_ = pos


class FakeNlp:
    """Tags every capitalised token as a proper noun."""

    def __call__(self, text):
        return [
            _FakeToken(word, "PROPN" if word[:1].isupper() else "NOUN")
            for word in str(text).replace("_", " ").split()
        ]


def fake_synonym_expander(word):
    """Small deterministic stand-in for the WordNet expander."""
    table = {
        "phosphoric": {"phosphoric", "phosphorus"},
        "phosphorus": {"phosphorus"},
        "oxoacids": {"oxoacid", "oxoacids", "acid"},
        "acid": {"acid"},
    }
    return table.get(word, {word})


class FakeRedirectResolver:
    def __init__(self, mapping):
        self.mapping = dict(mapping)
        self.calls: list[str] = []

    def resolve(self, uri):
        self.calls.append(uri)
        return self.mapping.get(uri)


USABLE_COUNTS = {CAT_BIO: 800, CAT_NOBEL: 30, CAT_STEM: 120}


def members_for(counts):
    """Member lists whose lengths agree with the advertised remote counts."""
    tags = {CAT_BIO: "Bio", CAT_NOBEL: "Nobel", CAT_STEM: "Stem"}
    return {
        cat: [f"{RESOURCE}{tags[cat]}{i:04d}" for i in range(n)]
        for cat, n in counts.items()
        if cat in tags
    }


def make_client(**overrides):
    """A client describing a well-formed Answer with three usable categories."""
    counts = overrides.pop("counts", {**USABLE_COUNTS, CAT_LIVING: 900_000})
    defaults = dict(
        label="Shinya Yamanaka",
        abstract=(
            "Shinya Yamanaka is a Japanese stem cell researcher. "
            "He is a Nobel Prize laureate. "
            "He works at Kyoto University."
        ),
        categories=(CAT_BIO, CAT_LIVING, CAT_NOBEL, CAT_STEM),
        counts=counts,
        members=members_for(counts),
    )
    defaults.update(overrides)
    return FakeSparqlClient(**defaults)


def local_index_for(client, extra=(ANSWER,)):
    keys = {f"<{uri}>": i for i, uri in enumerate(extra)}
    offset = len(keys)
    for members in client.members.values():
        for uri in members:
            keys.setdefault(f"<{uri}>", offset + len(keys))
    return keys


# ---------------------------------------------------------------------------
# 1) Importing the module has no side effects
# ---------------------------------------------------------------------------


def test_import_creates_no_network_cache_or_model_side_effects(tmp_path):
    probe = textwrap.dedent(
        """
        import glob, os, sqlite3, sys
        sys.path.insert(0, sys.argv[1])
        before = set(glob.glob("**", recursive=True))
        import category_extractor_ClaudeWeb_v3 as m
        after = set(glob.glob("**", recursive=True))
        created = after - before
        assert not created, f"files created at import: {sorted(created)}"
        for name in ("sentence_transformers", "SPARQLWrapper", "nltk", "spacy", "torch"):
            assert name not in sys.modules, f"{name} was imported at import time"
        conns = [k for k, v in vars(m).items() if isinstance(v, sqlite3.Connection)]
        assert not conns, f"live sqlite connections at module level: {conns}"
        print("PROBE_OK")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(SRC_DIR)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PROBE_OK" in completed.stdout


def test_module_exposes_no_uppercase_best_and_report_has_no_optimality_wording():
    source = (SRC_DIR / "category_extractor_ClaudeWeb_v3.py").read_text(encoding="utf-8")
    assert "BEST" not in source

    lines = source.splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("def choose_best_class_for_answer")
    )
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("def ")), len(lines)
    )
    for index, line in enumerate(lines):
        if "best" in line.lower():
            assert (
                "choose_best_class_for_answer" in line or start <= index < end
            ), f"'best' outside the deprecated wrapper at line {index + 1}: {line!r}"

    client = make_client()
    result = ce.select_candidate_classes(ANSWER, mode="recommended", client=client)
    report = ce.format_selection_report(result)
    assert "best" not in report.lower()
    assert "optimal" not in report.lower()


# ---------------------------------------------------------------------------
# 2-4) Manual mode
# ---------------------------------------------------------------------------


def test_manual_mode_accepts_a_valid_requested_class_without_ranking():
    client = make_client(member=True)
    index = local_index_for(client)
    result = ce.select_candidate_classes(
        ANSWER, mode="manual", requested_class="dbc:Japanese_Nobel_laureates",
        client=client, local_index=index,
    )
    assert result.selection_status is ce.SelectionStatus.OK
    assert result.selected_class == CAT_NOBEL
    assert result.local_kg_uri == f"<{ANSWER}>"
    # No ranking work: categories were never listed and nothing was scored.
    assert "answer_categories" not in client.calls
    assert result.recommended_classes[0].scored is False
    # Audit criterion C5: at most three queries when a local index is supplied.
    assert result.sparql_query_count <= 3, client.calls


def test_manual_mode_rejects_an_invalid_requested_class():
    # A plain resource URI does not denote a category.
    client = make_client(member=True)
    bad = ce.select_candidate_classes(
        ANSWER, mode="manual", requested_class=RESOURCE + "Plato", client=client
    )
    assert bad.selection_status is ce.SelectionStatus.MANUAL_CLASS_INVALID
    assert bad.selected_class is None
    assert client.calls == [], "an unusable request must not spend a query"

    # A maintenance category is rejected before any query as well.
    junk_client = make_client(member=True)
    junk = ce.select_candidate_classes(
        ANSWER, mode="manual", requested_class="dbc:Living_people", client=junk_client
    )
    assert junk.selection_status is ce.SelectionStatus.MANUAL_CLASS_INVALID
    assert junk.number_rejected_by_reason == {ce.REASON_JUNK: 1}
    assert junk_client.calls == []

    # A class the Answer belongs to but which is far too generic.
    generic_client = make_client(member=True, counts={CAT_BIO: 4_000_000})
    generic = ce.select_candidate_classes(
        ANSWER, mode="manual", requested_class=CAT_BIO, client=generic_client
    )
    assert generic.selection_status is ce.SelectionStatus.MANUAL_CLASS_INVALID
    assert generic.number_rejected_by_reason == {ce.REASON_TOO_GENERIC: 1}


def test_manual_mode_detects_that_the_answer_is_not_a_member():
    client = make_client(member=False)
    result = ce.select_candidate_classes(
        ANSWER, mode="manual", requested_class=CAT_NOBEL, client=client
    )
    assert result.selection_status is ce.SelectionStatus.MANUAL_CLASS_NOT_MEMBER
    assert result.selected_class is None
    assert client.calls == ["answer_info"], "membership must fail before the count query"


def test_manual_mode_reports_insufficient_local_candidates_separately():
    client = make_client(member=True)
    index = {f"<{ANSWER}>": 0, f"<{RESOURCE}Nobel0>": 1}
    result = ce.select_candidate_classes(
        ANSWER, mode="manual", requested_class=CAT_NOBEL, client=client,
        local_index=index, min_local_candidates=10,
    )
    assert result.selection_status is ce.SelectionStatus.INSUFFICIENT_LOCAL_CANDIDATES
    assert result.number_rejected_by_reason == {ce.REASON_LOCAL_TOO_FEW: 1}


def test_manual_mode_reports_insufficient_remote_candidates_separately():
    client = make_client(member=True, counts={CAT_NOBEL: 2})
    result = ce.select_candidate_classes(
        ANSWER, mode="manual", requested_class=CAT_NOBEL, client=client
    )
    assert result.selection_status is ce.SelectionStatus.INSUFFICIENT_REMOTE_CANDIDATES
    assert result.number_rejected_by_reason == {ce.REASON_TOO_SMALL: 1}


def test_local_uri_not_found_is_its_own_status():
    client = make_client(member=True)
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, local_index={"<http://other/X>": 0}
    )
    assert result.selection_status is ce.SelectionStatus.LOCAL_URI_NOT_FOUND
    assert result.local_kg_uri is None


# ---------------------------------------------------------------------------
# 5) Recommended mode
# ---------------------------------------------------------------------------


def test_recommended_mode_returns_top_n_with_separate_score_components():
    client = make_client()
    encoder = FakeEncoder(affinities={"Japanese Nobel laureates": 0.9})
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, encoder=encoder, top_n=2,
        local_index=local_index_for(client),
    )
    assert result.selection_status is ce.SelectionStatus.OK
    assert len(result.recommended_classes) == 2
    assert result.selected_class == result.recommended_classes[0].category_uri

    top = result.recommended_classes[0]
    for component in (
        "raw_idf", "normalized_idf", "raw_sbert", "normalized_sbert", "combined_score"
    ):
        assert component in top.to_dict()
    assert 0.0 <= top.normalized_idf <= 1.0
    assert 0.0 <= top.normalized_sbert <= 1.0
    assert top.scored is True
    assert result.encoder_metadata["available"] is True
    assert result.encoder_metadata["aggregation"] == "mean_chunks"

    # Living_people never survives the junk filter.
    assert CAT_LIVING not in [c.category_uri for c in result.recommended_classes]
    assert result.number_rejected_by_reason.get(ce.REASON_JUNK) == 1

    # Ordering is by combined score with the URI as an explicit tie-break.
    scores = [(-c.combined_score, c.category_uri) for c in result.recommended_classes]
    assert scores == sorted(scores)


def test_recommendation_score_falls_back_to_specificity_without_an_encoder():
    client = make_client()
    result = ce.select_candidate_classes(ANSWER, mode="recommended", client=client)
    assert result.selection_status is ce.SelectionStatus.OK
    assert result.encoder_metadata["available"] is False
    for candidate in result.recommended_classes:
        assert candidate.raw_sbert == 0.0
        assert candidate.normalized_sbert == 0.0
        assert candidate.combined_score == pytest.approx(candidate.normalized_idf)


def test_soft_overlap_penalty_is_applied_only_when_configured():
    client = make_client(
        label="Phosphoric acid",
        categories=(CATEGORY + "Phosphorus_oxoacids", CATEGORY + "Japanese_biologists"),
        counts={CATEGORY + "Phosphorus_oxoacids": 40, CAT_BIO: 800},
    )
    plain = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client,
        synonym_expander=fake_synonym_expander,
    )
    penalised = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=make_client(
            label="Phosphoric acid",
            categories=(CATEGORY + "Phosphorus_oxoacids", CATEGORY + "Japanese_biologists"),
            counts={CATEGORY + "Phosphorus_oxoacids": 40, CAT_BIO: 800},
        ),
        synonym_expander=fake_synonym_expander, soft_leak_penalty=0.5,
    )
    soft_plain = {c.category_uri: c for c in plain.recommended_classes}
    soft_pen = {c.category_uri: c for c in penalised.recommended_classes}
    target = CATEGORY + "Phosphorus_oxoacids"
    assert soft_plain[target].leak_level is ce.LeakLevel.SOFT
    assert soft_pen[target].combined_score < soft_plain[target].combined_score


# ---------------------------------------------------------------------------
# 6) First-feasible mode
# ---------------------------------------------------------------------------


def test_first_feasible_uses_specificity_then_uri_and_honours_priority():
    client = make_client()
    result = ce.select_candidate_classes(
        ANSWER, mode="first_feasible", client=client, local_index=local_index_for(client)
    )
    assert result.selection_status is ce.SelectionStatus.OK
    # Nobel laureates (30 members) is more specific than Stem cell researchers
    # (120) which is more specific than Japanese biologists (800).
    assert result.selected_class == CAT_NOBEL
    ordered = [c.category_uri for c in result.recommended_classes]
    assert ordered == [CAT_NOBEL, CAT_STEM, CAT_BIO]

    prioritised = ce.select_candidate_classes(
        ANSWER, mode="first_feasible", client=make_client(),
        local_index=local_index_for(client), candidate_priority=["dbc:Japanese_biologists"],
    )
    assert prioritised.selected_class == CAT_BIO


def test_first_feasible_order_breaks_ties_on_uri_only():
    tied = [
        ce.ClassCandidate(category_uri=CAT_STEM, category_short="", display_label="", raw_idf=0.5),
        ce.ClassCandidate(category_uri=CAT_BIO, category_short="", display_label="", raw_idf=0.5),
        ce.ClassCandidate(category_uri=CAT_NOBEL, category_short="", display_label="", raw_idf=0.9),
    ]
    ordered = [c.category_uri for c in ce.first_feasible_order(tied)]
    assert ordered == [CAT_NOBEL, CAT_BIO, CAT_STEM]


# ---------------------------------------------------------------------------
# 7-8, 10) Status separation and cache correctness
# ---------------------------------------------------------------------------


def test_query_failure_is_distinct_from_a_successful_zero_result():
    failed = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=make_client(fail_qids={"answer_categories"})
    )
    assert failed.selection_status is ce.SelectionStatus.QUERY_FAILED
    assert failed.query_status is ce.QueryStatus.FAILED

    zero = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=make_client(categories=())
    )
    assert zero.selection_status is ce.SelectionStatus.NO_SUBJECT_CATEGORIES
    assert zero.query_status is not ce.QueryStatus.FAILED
    assert failed.selection_status is not zero.selection_status


def test_no_categories_is_distinct_from_all_categories_rejected():
    none_at_all = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=make_client(categories=())
    )
    assert none_at_all.selection_status is ce.SelectionStatus.NO_SUBJECT_CATEGORIES
    assert none_at_all.number_of_categories == 0

    all_rejected = ce.select_candidate_classes(
        ANSWER, mode="recommended",
        client=make_client(categories=(CAT_NOBEL,), counts={CAT_NOBEL: 3}),
    )
    assert all_rejected.selection_status is ce.SelectionStatus.ALL_CATEGORIES_REJECTED
    assert all_rejected.number_of_categories == 1
    assert all_rejected.number_rejected_by_reason == {ce.REASON_TOO_SMALL: 1}


def test_no_label_and_no_categories_is_reported_as_no_label():
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=make_client(label=None, abstract=None, categories=())
    )
    assert result.selection_status is ce.SelectionStatus.NO_LABEL
    assert result.label_missing is True
    # The URI still yields a usable display label.
    assert result.display_label == "Shinya Yamanaka"


def test_transport_failure_is_never_cached_as_a_zero_result_success():
    cache = ce.InMemorySparqlCache()
    broken = FakeSparqlClient(raise_qids={"answer_info"})
    runner = ce.SparqlRunner(client=broken, cache=cache)
    result = runner.run(ce.build_answer_info_query(ANSWER))
    assert result.status is ce.QueryStatus.FAILED
    assert len(cache) == 0, "a failed query must not be stored"

    # The failure did not poison the cache: a later healthy run still works.
    healthy = ce.SparqlRunner(client=make_client(), cache=cache)
    again = healthy.run(ce.build_answer_info_query(ANSWER))
    assert again.status is ce.QueryStatus.OK
    assert len(cache) == 1


def test_successful_zero_result_is_cached_under_its_own_status():
    cache = ce.InMemorySparqlCache()
    client = make_client(categories=())
    runner = ce.SparqlRunner(client=client, cache=cache)
    first = runner.run(ce.build_answer_categories_query(ANSWER))
    assert first.status is ce.QueryStatus.ZERO_RESULTS
    assert first.cache_status is ce.CacheStatus.MISS
    assert len(cache) == 1

    second = runner.run(ce.build_answer_categories_query(ANSWER))
    assert second.status is ce.QueryStatus.ZERO_RESULTS
    assert second.cache_status is ce.CacheStatus.HIT
    assert runner.n_client_calls == 1, "the second call must be served from cache"


def test_cache_refresh_and_bypass_modes():
    cache = ce.InMemorySparqlCache()
    client = make_client()
    ce.SparqlRunner(client=client, cache=cache).run(ce.build_answer_info_query(ANSWER))
    assert len(cache) == 1

    refreshing = ce.SparqlRunner(client=client, cache=cache, refresh=True)
    refreshed = refreshing.run(ce.build_answer_info_query(ANSWER))
    assert refreshed.cache_status is ce.CacheStatus.REFRESH
    assert refreshing.n_client_calls == 1

    bypassing = ce.SparqlRunner(client=client, cache=cache, bypass=True)
    bypassed = bypassing.run(ce.build_answer_info_query(ANSWER))
    assert bypassed.cache_status is ce.CacheStatus.BYPASS
    assert bypassing.n_cache_hits == 0


def test_sqlite_cache_records_required_fields_and_refuses_a_foreign_schema(tmp_path):
    path = tmp_path / "nested" / "cache.sqlite"
    cache = ce.SqliteSparqlCache(path, endpoint="http://fake.invalid/sparql")
    runner = ce.SparqlRunner(client=make_client(), cache=cache)
    runner.run(ce.build_answer_info_query(ANSWER))

    key = ce.compute_query_hash(
        "http://fake.invalid/sparql", "en", ce.build_answer_info_query(ANSWER)
    )
    record = cache.get(key)
    assert record is not None
    for column in ("endpoint", "language", "response_json", "query_status", "retrieved_at"):
        assert column in record
    meta = cache.meta()
    assert meta["schema_version"] == ce.CACHE_SCHEMA_VERSION
    assert "created_at" in meta and "endpoint" in meta
    assert cache.clear() == 1
    cache.close()

    # A v2-style cache file must be refused, never migrated or overwritten.
    import sqlite3

    foreign = tmp_path / "v2_style.sqlite"
    conn = sqlite3.connect(foreign)
    conn.execute("CREATE TABLE cache (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
    conn.execute("INSERT INTO cache VALUES ('k', 'v', 1.0)")
    conn.commit()
    conn.close()
    before = foreign.read_bytes()
    with pytest.raises(ce.CacheSchemaMismatch):
        ce.SqliteSparqlCache(foreign).get("anything")
    assert foreign.read_bytes() == before, "the foreign cache file was modified"


# ---------------------------------------------------------------------------
# 9) Determinism
# ---------------------------------------------------------------------------


def test_selection_is_deterministic_and_independent_of_input_order():
    categories = [CAT_BIO, CAT_LIVING, CAT_NOBEL, CAT_STEM]
    baseline = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=make_client(categories=tuple(categories)),
        encoder=FakeEncoder(), local_index=local_index_for(make_client()),
    ).to_json()

    rng = random.Random(20260726)
    for _ in range(5):
        shuffled = categories[:]
        rng.shuffle(shuffled)
        candidate = ce.select_candidate_classes(
            ANSWER, mode="recommended", client=make_client(categories=tuple(shuffled)),
            encoder=FakeEncoder(), local_index=local_index_for(make_client()),
        ).to_json()
        assert candidate == baseline


def test_repeated_identical_runs_produce_identical_records():
    first = ce.select_candidate_classes(
        ANSWER, mode="first_feasible", client=make_client(), encoder=FakeEncoder()
    ).to_dict()
    second = ce.select_candidate_classes(
        ANSWER, mode="first_feasible", client=make_client(), encoder=FakeEncoder()
    ).to_dict()
    assert first == second


# ---------------------------------------------------------------------------
# 11) Query hygiene
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,query", sorted(ce.sample_queries().items()))
def test_every_query_with_a_limit_also_has_an_order_by(name, query):
    if "LIMIT" in query:
        assert "ORDER BY" in query, f"{name} applies LIMIT without deterministic ordering"
    assert ce.query_id(query) is not None


def test_truncation_at_the_category_limit_is_reported():
    many = tuple(CATEGORY + f"Cat_{i:03d}" for i in range(5))
    client = make_client(categories=many, counts={c: 50 for c in many})
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, category_limit=5
    )
    assert result.categories_truncated is True


# ---------------------------------------------------------------------------
# 12-18) Display labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "uri,label,expected",
    [
        (RESOURCE + "Makoto_Kobayashi_(physicist)", None, "Makoto Kobayashi"),
        (RESOURCE + "Akira_Suzuki_(chemist)", None, "Akira Suzuki"),
        (RESOURCE + "Phosphorus(V)", None, "Phosphorus(V)"),
        (RESOURCE + "Phosphorus(V)_oxide", None, "Phosphorus(V) oxide"),
        (RESOURCE + "Iron(III)_chloride", None, "Iron(III) chloride"),
        (RESOURCE + "Iron(II)_chloride", None, "Iron(II) chloride"),
        (RESOURCE + "Vitamin_B12_(cobalamin)", "Vitamin B12", "Vitamin B12"),
        (RESOURCE + "Vitamin_B12_(cobalamin)", None, "Vitamin B12 (cobalamin)"),
        (RESOURCE + "Kant%C5%8D_region", None, "Kantō region"),
        (RESOURCE + "Tamagawa_Station_(Tokyo)", None, "Tamagawa Station"),
        (RESOURCE + "Plato", None, "Plato"),
    ],
)
def test_format_display_label(uri, label, expected):
    assert ce.format_display_label(uri, rdfs_label=label) == expected


def test_display_label_keeps_chemistry_distinguishable_and_is_nfc():
    iron_ii = ce.format_display_label(RESOURCE + "Iron(II)_chloride")
    iron_iii = ce.format_display_label(RESOURCE + "Iron(III)_chloride")
    assert iron_ii != iron_iii

    import unicodedata

    decomposed = "Kantō region"  # 'o' + combining macron
    rendered = ce.format_display_label(RESOURCE + "X", rdfs_label=decomposed)
    assert rendered == unicodedata.normalize("NFC", decomposed)
    assert "̄" not in rendered

    # The v2 behaviour that this replaces.
    import category_extractor_ClaudeWeb_v2 as v2

    assert v2.remove_parenthetical("Iron(III)_chloride") == "Iron chloride"
    assert ce.format_display_label(RESOURCE + "Iron(III)_chloride") == "Iron(III) chloride"


def test_disambiguator_suffixes_are_configurable_not_hard_coded_per_uri():
    uri = RESOURCE + "Something_(widget)"
    assert ce.format_display_label(uri) == "Something (widget)"
    assert ce.format_display_label(uri, disambiguator_suffixes={"widget"}) == "Something"
    # Supplying a custom set replaces the default rather than extending it.
    assert (
        ce.format_display_label(
            RESOURCE + "Makoto_Kobayashi_(physicist)", disambiguator_suffixes={"widget"}
        )
        == "Makoto Kobayashi (physicist)"
    )


# ---------------------------------------------------------------------------
# 19-20) Leakage
# ---------------------------------------------------------------------------


def test_hard_leak_is_detected_and_rejects_the_class():
    verdict = ce.detect_leak("Albert Einstein", "Albert Einstein Award")
    assert verdict.level is ce.LeakLevel.HARD

    assert ce.detect_leak("Plato", "Plato").level is ce.LeakLevel.HARD
    # Token boundaries: 'Plato' must not leak through 'Platonists'.
    assert ce.detect_leak("Plato", "Platonists").level is ce.LeakLevel.NONE

    propn = ce.detect_leak(
        "Makoto Kobayashi", "Kobayashi Maskawa theory awardees", nlp=FakeNlp()
    )
    assert propn.level is ce.LeakLevel.HARD

    client = make_client(
        label="Shinya Yamanaka",
        categories=(CATEGORY + "Shinya_Yamanaka_awards", CAT_NOBEL),
        counts={CATEGORY + "Shinya_Yamanaka_awards": 25, CAT_NOBEL: 30},
    )
    result = ce.select_candidate_classes(ANSWER, mode="recommended", client=client)
    assert result.number_rejected_by_reason == {ce.REASON_HARD_LEAK: 1}
    assert [c.category_uri for c in result.recommended_classes] == [CAT_NOBEL]


def test_soft_overlap_is_flagged_but_never_hard_rejected():
    verdict = ce.detect_leak(
        "Phosphoric acid", "Phosphorus oxoacids", synonym_expander=fake_synonym_expander
    )
    assert verdict.level is ce.LeakLevel.SOFT
    assert verdict.is_hard is False

    client = make_client(
        label="Phosphoric acid",
        categories=(CATEGORY + "Phosphorus_oxoacids",),
        counts={CATEGORY + "Phosphorus_oxoacids": 40},
    )
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, synonym_expander=fake_synonym_expander
    )
    assert result.selection_status is ce.SelectionStatus.OK
    assert result.recommended_classes[0].leak_level is ce.LeakLevel.SOFT
    assert result.number_rejected_by_reason == {}


def test_wordnet_style_expansion_alone_cannot_reject_a_class():
    """A synonym expander that relates everything must not reject anything."""

    def everything_is_related(word):
        return {"universal-token", word}

    verdict = ce.detect_leak(
        "Shinya Yamanaka", "Japanese Nobel laureates", synonym_expander=everything_is_related
    )
    assert verdict.level is ce.LeakLevel.SOFT
    assert verdict.is_hard is False


# ---------------------------------------------------------------------------
# 21) Deprecated compatibility wrappers
# ---------------------------------------------------------------------------


def test_deprecated_wrapper_warns_and_matches_the_top_ranked_recommendation():
    ranked = ce.rank_classes_for_answer(ANSWER, client=make_client())
    assert ranked and isinstance(ranked[0], ce.ClassCandidate)

    with pytest.warns(DeprecationWarning, match="deprecated"):
        chosen = ce.choose_best_class_for_answer(ANSWER, client=make_client())
    assert chosen == ranked[0].category_uri

    doc = ce.choose_best_class_for_answer.__doc__ or ""
    assert "DEPRECATED" in doc
    assert "not" in doc.lower() and "optimal" in doc.lower()


def test_rank_classes_for_answer_does_not_warn():
    import warnings as _warnings

    with _warnings.catch_warnings():
        _warnings.simplefilter("error", DeprecationWarning)
        ce.rank_classes_for_answer(ANSWER, client=make_client())


# ---------------------------------------------------------------------------
# Encoder, chunking, scoring helpers
# ---------------------------------------------------------------------------


def test_chunk_text_splits_long_abstracts_and_never_drops_words():
    abstract = " ".join(f"Sentence number {i} about the entity." for i in range(40))
    chunks = ce.chunk_text(abstract, max_tokens=32)
    assert len(chunks) >= 2
    assert " ".join(chunks).split() == abstract.split()

    single_long = "word " * 200
    long_chunks = ce.chunk_text(single_long.strip(), max_tokens=32)
    assert len(long_chunks) >= 2
    assert " ".join(long_chunks).split() == single_long.split()

    assert ce.chunk_text("", max_tokens=32) == []


def test_encoder_metadata_records_chunk_count_and_disclaims_full_coverage():
    abstract = " ".join(f"Sentence number {i} about the entity." for i in range(60))
    client = make_client(abstract=abstract)
    encoder = FakeEncoder(max_seq_length=32)
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, encoder=encoder
    )
    meta = result.encoder_metadata
    assert meta["available"] is True
    assert meta["abstract_chunks"] >= 2
    assert meta["max_seq_length"] == 32
    assert meta["chunk_strategy"] == "sentence_pack"
    assert "not a claim that the full abstract was processed" in meta["note"]
    assert encoder.calls == 1, "labels and chunks must be encoded in one batch"


def test_category_specificity_and_rank_normalisation():
    assert ce.category_specificity(1) == pytest.approx(1.0)
    assert ce.category_specificity(ce.DEFAULT_TOTAL_ENTITIES) == pytest.approx(0.0)
    assert ce.category_specificity(30) > ce.category_specificity(800)
    assert ce.category_specificity(None) == 0.0

    assert ce._rank_normalize([]) == []
    assert ce._rank_normalize([0.4]) == [1.0]
    assert ce._rank_normalize([1.0, 1.0, 1.0]) == [0.5, 0.5, 0.5]
    assert ce._rank_normalize([0.1, 0.9, 0.5]) == [0.0, 1.0, 0.5]
    # Order independence: the same multiset gives the same values per element.
    assert ce._rank_normalize([0.9, 0.1, 0.5]) == [1.0, 0.0, 0.5]


def test_normalize_category_accepts_the_documented_spellings():
    assert ce.normalize_category("dbc:Japanese_Nobel_laureates") == CAT_NOBEL
    assert ce.normalize_category("Category:Japanese_Nobel_laureates") == CAT_NOBEL
    assert ce.normalize_category(CAT_NOBEL) == CAT_NOBEL
    assert ce.normalize_category(f"<{CAT_NOBEL}>") == CAT_NOBEL
    assert ce.normalize_category("Japanese Nobel laureates") == CAT_NOBEL
    assert ce.normalize_category(RESOURCE + "Plato") is None
    assert ce.normalize_category("") is None
    assert ce.normalize_category(None) is None


# ---------------------------------------------------------------------------
# Redirects (interface only; live behaviour unverified)
# ---------------------------------------------------------------------------


def test_redirects_are_disabled_by_default():
    resolver = FakeRedirectResolver({ANSWER: RESOURCE + "Yamanaka_Shinya"})
    uri, used = ce.resolve_query_uri(ANSWER, resolver=resolver)
    assert (uri, used) == (ANSWER, False)
    assert resolver.calls == []

    client = make_client(categories=(), label=None)
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, redirect_resolver=resolver
    )
    assert result.redirect_used is False
    assert resolver.calls == []


def test_single_redirect_hop_with_cycle_protection():
    resolver = FakeRedirectResolver({ANSWER: RESOURCE + "Target"})
    uri, used = ce.resolve_query_uri(ANSWER, resolver=resolver, enabled=True)
    assert (uri, used) == (RESOURCE + "Target", True)

    cyclic = FakeRedirectResolver({ANSWER: ANSWER})
    uri, used = ce.resolve_query_uri(ANSWER, resolver=cyclic, enabled=True, max_hops=5)
    assert (uri, used) == (ANSWER, False)

    two_step = FakeRedirectResolver({ANSWER: RESOURCE + "B", RESOURCE + "B": ANSWER})
    uri, used = ce.resolve_query_uri(ANSWER, resolver=two_step, enabled=True, max_hops=5)
    assert uri == RESOURCE + "B", "the cycle back to the origin must be refused"


def test_redirect_is_used_only_when_the_original_uri_yields_nothing():
    target = RESOURCE + "Yamanaka_Shinya"

    class TwoStageClient(FakeSparqlClient):
        def _rows(self, qid, query):
            if f"<{ANSWER}>" in query and qid in ("answer_info", "answer_categories"):
                return []
            return super()._rows(qid, query)

    client = TwoStageClient(
        label="Shinya Yamanaka",
        categories=(CAT_NOBEL,),
        counts={CAT_NOBEL: 30},
    )
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, resolve_redirects=True,
        redirect_resolver=FakeRedirectResolver({ANSWER: target}),
    )
    assert result.redirect_used is True
    assert result.query_uri == target
    assert result.original_uri == ANSWER, "the original URI must never be rewritten"
    assert result.selection_status is ce.SelectionStatus.OK


class LabelledRedirectClient(FakeSparqlClient):
    """A redirect resource that keeps its own label but has no categories.

    This is the shape that defeats a "no label AND no categories" trigger: the
    label lives on the redirect, the ``dct:subject`` statements live only on the
    canonical target.
    """

    def _rows(self, qid, query):
        if f"<{ANSWER}>" in query and qid == "answer_categories":
            return []  # a successful zero-result, not a query failure
        return super()._rows(qid, query)


@pytest.mark.parametrize("mode", ["recommended", "first_feasible"])
def test_redirect_is_attempted_when_a_labelled_uri_has_no_categories(mode):
    target = RESOURCE + "Yamanaka_Shinya"
    client = LabelledRedirectClient(
        label="Shinya Yamanaka",
        categories=(CAT_NOBEL,),
        counts={CAT_NOBEL: 30},
    )
    resolver = FakeRedirectResolver({ANSWER: target})
    result = ce.select_candidate_classes(
        ANSWER, mode=mode, client=client, resolve_redirects=True,
        redirect_resolver=resolver,
    )

    assert resolver.calls == [ANSWER], "zero categories alone must trigger the hop"
    assert result.redirect_used is True
    assert result.query_uri == target
    assert result.original_uri == ANSWER, "the original URI must never be rewritten"
    assert result.selection_status is ce.SelectionStatus.OK
    assert result.selected_class == CAT_NOBEL
    assert result.selection_status is not ce.SelectionStatus.NO_SUBJECT_CATEGORIES


def test_manual_mode_does_not_spend_a_redirect_query_on_a_labelled_entity():
    """Manual mode never fetches categories, so 'no categories' cannot be its trigger."""
    client = make_client(member=True)
    resolver = FakeRedirectResolver({ANSWER: RESOURCE + "Yamanaka_Shinya"})
    result = ce.select_candidate_classes(
        ANSWER, mode="manual", requested_class=CAT_NOBEL, client=client,
        resolve_redirects=True, redirect_resolver=resolver,
    )
    assert resolver.calls == [], "an ordinary labelled entity needs no redirect"
    assert result.redirect_used is False
    assert client.calls.count("redirect") == 0
    assert result.sparql_query_count <= 3, "the manual query budget must be preserved"


class UnlabelledButCategorisedClient(FakeSparqlClient):
    """The original URI has usable categories but no label.

    The redirect target is the mirror image: a label, and nothing else. Adopting
    it would trade real data for a cosmetic one.
    """

    def _rows(self, qid, query):
        if qid == "answer_info" and f"<{ANSWER}>" in query:
            return []  # no label, no abstract — a successful zero-result
        if qid == "answer_categories" and f"<{ANSWER}>" not in query:
            return []  # the redirect target carries no categories
        return super()._rows(qid, query)


@pytest.mark.parametrize("mode", ["recommended", "first_feasible"])
def test_a_missing_label_alone_does_not_trigger_a_redirect(mode):
    """Categories, not labels, are what the ranking modes need from a redirect."""
    client = UnlabelledButCategorisedClient(
        label="Yamanaka Shinya",  # served only for the redirect target
        categories=(CAT_NOBEL,),
        counts={CAT_NOBEL: 30},
    )
    resolver = FakeRedirectResolver({ANSWER: RESOURCE + "Yamanaka_Shinya"})
    result = ce.select_candidate_classes(
        ANSWER, mode=mode, client=client, resolve_redirects=True,
        redirect_resolver=resolver,
    )

    assert resolver.calls == [], "usable categories leave nothing for a redirect to fix"
    assert client.calls.count("redirect") == 0
    assert result.redirect_used is False
    assert result.original_uri == ANSWER
    assert result.query_uri == ANSWER, "the original URI must not be abandoned"
    assert result.selection_status is ce.SelectionStatus.OK
    assert result.selection_status is not ce.SelectionStatus.NO_SUBJECT_CATEGORIES
    assert result.selected_class == CAT_NOBEL
    assert result.label_missing is True, "the missing label is recorded, not repaired"


class MemberWithoutLabelClient(FakeSparqlClient):
    """The original URI is a confirmed member of the requested class, unlabelled.

    The redirect target has a label but is not a member, so adopting it would
    throw away the very fact manual mode exists to establish.
    """

    def _rows(self, qid, query):
        if qid != "answer_info":
            return super()._rows(qid, query)
        if f"<{ANSWER}>" in query:
            row = {}
            if "dct:subject <" in query:
                row["member"] = self._cell("yes")
            return [row] if row else []
        return [{"label": self._cell("Yamanaka Shinya")}]


def test_manual_mode_keeps_confirmed_membership_over_a_labelled_redirect():
    client = MemberWithoutLabelClient(
        categories=(CAT_NOBEL,),
        counts={CAT_NOBEL: 30},
    )
    resolver = FakeRedirectResolver({ANSWER: RESOURCE + "Yamanaka_Shinya"})
    result = ce.select_candidate_classes(
        ANSWER, mode="manual", requested_class=CAT_NOBEL, client=client,
        resolve_redirects=True, redirect_resolver=resolver,
    )

    assert resolver.calls == [], "confirmed membership settles the manual decision"
    assert client.calls.count("redirect") == 0
    assert result.redirect_used is False
    assert result.original_uri == ANSWER
    assert result.query_uri == ANSWER
    assert result.selection_status is not ce.SelectionStatus.MANUAL_CLASS_NOT_MEMBER
    assert result.selection_status is ce.SelectionStatus.OK
    assert result.selected_class == CAT_NOBEL
    assert result.sparql_query_count <= 3, "the manual query budget must be preserved"


def test_manual_mode_adopts_a_redirect_only_when_it_confirms_membership():
    """The hop is still available when membership is genuinely unresolved."""
    target = RESOURCE + "Yamanaka_Shinya"

    class OnlyTargetIsMemberClient(FakeSparqlClient):
        def _rows(self, qid, query):
            if qid == "answer_info" and f"<{ANSWER}>" in query:
                return []  # no label and no membership: nothing to go on
            return super()._rows(qid, query)

    client = OnlyTargetIsMemberClient(
        label="Yamanaka Shinya",
        member=True,
        categories=(CAT_NOBEL,),
        counts={CAT_NOBEL: 30},
    )
    resolver = FakeRedirectResolver({ANSWER: target})
    result = ce.select_candidate_classes(
        ANSWER, mode="manual", requested_class=CAT_NOBEL, client=client,
        resolve_redirects=True, redirect_resolver=resolver,
    )

    assert resolver.calls == [ANSWER]
    assert result.redirect_used is True
    assert result.query_uri == target
    assert result.original_uri == ANSWER, "the original URI must never be rewritten"
    assert result.selection_status is ce.SelectionStatus.OK
    assert result.selected_class == CAT_NOBEL


# ---------------------------------------------------------------------------
# Provenance of the built-in redirect query
# ---------------------------------------------------------------------------

REDIRECT_TARGET = RESOURCE + "Yamanaka_Shinya"

# The full query sequence of a selection that follows one redirect: the
# original URI's two queries, the redirect lookup, the target's two queries,
# and the category count.
REDIRECT_QIDS = [
    "answer_info", "answer_categories", "redirect",
    "answer_info", "answer_categories", "category_counts",
]


class RedirectingClient(FakeSparqlClient):
    """Original URI: a label and no categories. Target: one usable category."""

    def _rows(self, qid, query):
        if qid == "answer_categories" and f"<{ANSWER}>" in query:
            return []  # successful zero-result on the original URI
        return super()._rows(qid, query)


def redirecting_client(**overrides):
    defaults = dict(
        label="Shinya Yamanaka",
        categories=(CAT_NOBEL,),
        counts={CAT_NOBEL: 30},
        redirect_map={ANSWER: REDIRECT_TARGET},
    )
    defaults.update(overrides)
    return RedirectingClient(**defaults)


def test_the_builtin_redirect_query_is_counted_against_the_answer():
    """A resolver over the shared runner must not query around the counter view."""
    client = redirecting_client()
    shared = ce.SparqlRunner(client=client)
    resolver = ce.SparqlRedirectResolver(shared)

    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", runner=shared,
        resolve_redirects=True, redirect_resolver=resolver,
    )

    assert client.calls == REDIRECT_QIDS, client.calls
    assert result.redirect_used is True
    assert result.query_uri == REDIRECT_TARGET
    assert result.original_uri == ANSWER
    assert result.selection_status is ce.SelectionStatus.OK

    assert result.sparql_query_count == 6
    assert result.cache_stats["queries"] == 6
    assert result.sparql_query_count == result.cache_stats["queries"]
    assert shared.stats()["queries"] == 6, "no query may be double-counted"
    assert shared.stats()["client_calls"] == len(client.calls)


def test_redirect_counters_stay_per_answer_across_a_shared_cache():
    client = redirecting_client()
    cache = ce.InMemorySparqlCache()
    shared = ce.SparqlRunner(client=client, cache=cache)
    resolver = ce.SparqlRedirectResolver(shared)

    kwargs = dict(
        mode="recommended", runner=shared,
        resolve_redirects=True, redirect_resolver=resolver,
    )
    first = ce.select_candidate_classes(ANSWER, **kwargs)
    calls_after_first = len(client.calls)
    second = ce.select_candidate_classes(ANSWER, **kwargs)

    assert first.sparql_query_count == 6
    assert first.cache_stats["cache_hits"] == 0
    assert first.cache_stats["client_calls"] == 6

    assert second.sparql_query_count == 6, "the same six queries, all cached"
    assert second.cache_stats["cache_hits"] == 6, (
        "including the redirect lookup's own cache hit"
    )
    assert second.cache_stats["client_calls"] == 0
    assert len(client.calls) == calls_after_first, "the client was not called again"

    assert shared.stats()["queries"] == 12
    assert shared.stats()["cache_hits"] == 6
    assert shared.stats()["client_calls"] == 6


def test_a_failed_redirect_query_is_a_query_failure_not_a_missing_category():
    """A lookup that did not answer licenses no conclusion about the Answer."""
    client = redirecting_client(fail_qids={"redirect"})
    shared = ce.SparqlRunner(client=client)

    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", runner=shared, resolve_redirects=True,
        redirect_resolver=ce.SparqlRedirectResolver(shared),
    )

    assert result.selection_status is ce.SelectionStatus.QUERY_FAILED
    assert result.query_status is ce.QueryStatus.FAILED
    assert result.selection_status is not ce.SelectionStatus.NO_SUBJECT_CATEGORIES
    assert result.error and "simulated endpoint failure for redirect" in result.error

    assert client.calls == ["answer_info", "answer_categories", "redirect"]
    assert "answer_info" not in client.calls[3:], "no target query may be issued"
    assert result.sparql_query_count == 3, "the failed redirect query is counted"
    assert result.cache_stats["failed"] == 1
    assert shared.stats()["failed"] == 1
    assert result.original_uri == ANSWER


def test_a_successful_zero_result_redirect_is_not_a_failure():
    """The other half of the distinction: answered, and there is no redirect."""
    client = redirecting_client(redirect_map={})
    shared = ce.SparqlRunner(client=client)

    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", runner=shared, resolve_redirects=True,
        redirect_resolver=ce.SparqlRedirectResolver(shared),
    )

    assert result.selection_status is ce.SelectionStatus.NO_SUBJECT_CATEGORIES
    assert result.selection_status is not ce.SelectionStatus.QUERY_FAILED
    assert result.query_status is not ce.QueryStatus.FAILED
    assert result.redirect_used is False
    assert result.query_uri == ANSWER
    assert result.sparql_query_count == 3
    assert shared.stats()["failed"] == 0


@pytest.mark.parametrize("failing_qid", ["answer_info", "answer_categories"])
def test_a_failure_reading_the_redirect_target_is_not_discarded(failing_qid):
    """The original's zero-category answer must not stand in for a failed target."""

    class TargetFailsClient(RedirectingClient):
        def run(self, query):
            qid = ce.query_id(query)
            if qid == failing_qid and f"<{REDIRECT_TARGET}>" in query:
                self.calls.append(qid)
                return ce.QueryResult(
                    status=ce.QueryStatus.FAILED,
                    error=f"simulated failure reading the target's {qid}",
                    endpoint=self.endpoint,
                    language=self.language,
                )
            return super().run(query)

    client = TargetFailsClient(
        label="Shinya Yamanaka",
        categories=(CAT_NOBEL,),
        counts={CAT_NOBEL: 30},
        redirect_map={ANSWER: REDIRECT_TARGET},
    )
    shared = ce.SparqlRunner(client=client)

    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", runner=shared, resolve_redirects=True,
        redirect_resolver=ce.SparqlRedirectResolver(shared),
    )

    assert result.selection_status is ce.SelectionStatus.QUERY_FAILED
    assert result.query_status is ce.QueryStatus.FAILED
    assert result.selection_status is not ce.SelectionStatus.NO_SUBJECT_CATEGORIES
    assert result.error == f"simulated failure reading the target's {failing_qid}"
    assert result.original_uri == ANSWER, "the original URI is never rewritten"

    # Original URI (2) + redirect (1) + target queries up to the failure.
    expected = 4 if failing_qid == "answer_info" else 5
    assert result.sparql_query_count == expected, client.calls
    assert result.cache_stats["queries"] == expected
    assert shared.stats()["queries"] == expected
    assert result.cache_stats["failed"] == 1


def test_a_custom_resolver_error_is_still_contained():
    """Only an explicit SPARQL failure escapes; a resolver's own bug does not."""

    class ExplodingResolver:
        def resolve(self, uri):
            raise ValueError("resolver bug, not an endpoint failure")

    client = redirecting_client()
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, resolve_redirects=True,
        redirect_resolver=ExplodingResolver(),
    )
    assert result.selection_status is ce.SelectionStatus.NO_SUBJECT_CATEGORIES
    assert result.query_status is not ce.QueryStatus.FAILED

    # The typed failure, by contrast, propagates out of resolve_query_uri.
    class FailingResolver:
        def resolve(self, uri):
            raise ce.RedirectQueryFailed(uri, "endpoint refused the lookup")

    with pytest.raises(ce.RedirectQueryFailed):
        ce.resolve_query_uri(ANSWER, resolver=FailingResolver(), enabled=True)


def test_sparql_redirect_resolver_separates_its_three_outcomes():
    found = FakeSparqlClient(redirect_map={ANSWER: REDIRECT_TARGET})
    assert ce.SparqlRedirectResolver(
        ce.SparqlRunner(client=found)
    ).resolve(ANSWER) == REDIRECT_TARGET

    absent = FakeSparqlClient()
    assert ce.SparqlRedirectResolver(
        ce.SparqlRunner(client=absent)
    ).resolve(ANSWER) is None

    broken = FakeSparqlClient(fail_qids={"redirect"})
    with pytest.raises(ce.RedirectQueryFailed) as excinfo:
        ce.SparqlRedirectResolver(ce.SparqlRunner(client=broken)).resolve(ANSWER)
    assert excinfo.value.uri == ANSWER
    assert "simulated endpoint failure" in (excinfo.value.error or "")


def test_a_resolver_on_a_foreign_runner_is_left_alone():
    """Rebinding must never move a query onto a different transport."""
    client = redirecting_client()
    other_client = redirecting_client()
    shared = ce.SparqlRunner(client=client)
    foreign = ce.SparqlRunner(client=other_client)
    resolver = ce.SparqlRedirectResolver(foreign)

    bound = ce._bind_redirect_resolver(resolver, ce.PerAnswerRunner(shared))
    assert bound is resolver, "a foreign transport must not be rebound"

    same = ce.SparqlRedirectResolver(shared)
    view = ce.PerAnswerRunner(shared)
    rebound = ce._bind_redirect_resolver(same, view)
    assert rebound is not same
    assert rebound.runner is view
    assert ce._base_runner(view) is shared


# ---------------------------------------------------------------------------
# Truncated member retrieval must never prove a shortage of local candidates
# ---------------------------------------------------------------------------

BIG_CAT = CATEGORY + "Big_class"


def big_class_client(size=3000, local_slice=slice(2500, 2510)):
    """A class of ``size`` members whose local-KG members appear late.

    URI-ordered page 1 (2000 rows) contains no local member at all; the local
    members only appear in page 2.
    """
    members = [f"{RESOURCE}m{i:05d}" for i in range(size)]
    client = FakeSparqlClient(
        label="Shinya Yamanaka",
        member=True,
        categories=(BIG_CAT,),
        counts={BIG_CAT: size},
        members={BIG_CAT: members},
    )
    index = {f"<{ANSWER}>": 0}
    index.update({f"<{m}>": i + 1 for i, m in enumerate(members[local_slice])})
    return client, index


def test_manual_mode_paginates_instead_of_trusting_a_truncated_prefix():
    client, index = big_class_client()
    result = ce.select_candidate_classes(
        ANSWER, mode="manual", requested_class=BIG_CAT, client=client,
        local_index=index, member_limit=2000, min_local_candidates=10,
    )
    assert result.selection_status is not ce.SelectionStatus.INSUFFICIENT_LOCAL_CANDIDATES
    assert result.selection_status is ce.SelectionStatus.OK
    assert result.selected_class == BIG_CAT

    candidate = result.recommended_classes[0]
    assert candidate.local_check is ce.LocalCheck.CHECKED_FEASIBLE
    assert candidate.local_count >= 10
    assert candidate.local_count_is_lower_bound is True
    assert client.calls.count("class_members") == 2, "the second page must be fetched"


def test_recommended_mode_paginates_a_class_too_large_for_the_batch():
    client, index = big_class_client()
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, local_index=index,
        member_limit=2000, max_member_rows=2000, min_local_candidates=10,
    )
    assert result.selection_status is ce.SelectionStatus.OK
    assert ce.REASON_LOCAL_TOO_FEW not in result.number_rejected_by_reason
    candidate = result.recommended_classes[0]
    assert candidate.category_uri == BIG_CAT
    assert candidate.local_check is ce.LocalCheck.CHECKED_FEASIBLE


@pytest.mark.parametrize("mode", ["manual", "recommended"])
def test_exhausted_page_budget_is_inconclusive_not_insufficient(mode):
    client, index = big_class_client()
    kwargs = dict(
        client=client, local_index=index, member_limit=2000,
        max_member_rows=2000, max_member_pages=1, min_local_candidates=10,
    )
    if mode == "manual":
        kwargs["requested_class"] = BIG_CAT
    result = ce.select_candidate_classes(ANSWER, mode=mode, **kwargs)

    assert result.selection_status is not ce.SelectionStatus.INSUFFICIENT_LOCAL_CANDIDATES
    # An unresolved class is never summarised as a demonstrated rejection.
    assert result.number_rejected_by_reason == {}
    assert result.number_inconclusive_by_reason == {ce.REASON_LOCAL_INCONCLUSIVE: 1}

    candidate = result.evaluated_classes[0]
    assert candidate.local_check is ce.LocalCheck.INCONCLUSIVE
    assert candidate.local_count_is_lower_bound is True
    assert "lower bound" in candidate.rejected_reason

    if mode == "manual":
        assert result.selection_status is ce.SelectionStatus.LOCAL_CHECK_INCONCLUSIVE
    else:
        assert result.selection_status is ce.SelectionStatus.NO_CONFIRMED_FEASIBLE_CLASS


def test_local_check_distinguishes_feasible_insufficient_and_unchecked():
    client = make_client()
    # Every Nobel member is local; no Stem member is; Japanese_biologists is
    # pushed outside the probe budget.
    index = {f"<{ANSWER}>": 0}
    index.update({f"<{m}>": i + 1 for i, m in enumerate(client.members[CAT_NOBEL])})

    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, local_index=index,
        max_local_probes=2, min_local_candidates=10,
    )
    by_uri = {c.category_uri: c for c in result.evaluated_classes}

    assert by_uri[CAT_NOBEL].local_check is ce.LocalCheck.CHECKED_FEASIBLE
    assert by_uri[CAT_NOBEL].feasible is True

    assert by_uri[CAT_STEM].local_check is ce.LocalCheck.CHECKED_INSUFFICIENT
    assert by_uri[CAT_STEM].rejected_code == ce.REASON_LOCAL_TOO_FEW
    assert by_uri[CAT_STEM].local_count_is_lower_bound is False

    assert by_uri[CAT_BIO].local_check is ce.LocalCheck.NOT_CHECKED_BUDGET
    assert by_uri[CAT_BIO].rejected_code == ce.REASON_LOCAL_NOT_PROBED
    assert by_uri[CAT_BIO].local_count is None
    assert "not shown to be infeasible" in by_uri[CAT_BIO].rejected_reason

    assert result.selection_status is ce.SelectionStatus.OK
    assert result.selected_class == CAT_NOBEL


class StalledPaginationClient(FakeSparqlClient):
    """An endpoint that ignores the keyset cursor and replays the same page."""

    def _rows(self, qid, query):
        if qid != "class_members":
            return super()._rows(qid, query)
        target = next((cat for cat in self.members if f"<{cat}>" in query), None)
        page = sorted(self.members.get(target, []))
        limit = _LIMIT_RE.search(query)
        if limit:
            page = page[: int(limit.group(1))]  # never advances past page 1
        self.stalled_pages = getattr(self, "stalled_pages", 0) + 1
        return [{"x": self._cell(m)} for m in page]


@pytest.mark.parametrize("mode", ["manual", "recommended"])
def test_stalled_pagination_is_inconclusive_not_complete(mode):
    """A cursor that stops advancing proves nothing about the whole class."""
    members = [f"{RESOURCE}m{i:05d}" for i in range(3000)]
    client = StalledPaginationClient(
        label="Shinya Yamanaka",
        member=True,
        categories=(BIG_CAT,),
        counts={BIG_CAT: 3000},
        members={BIG_CAT: members},
    )
    index = {f"<{ANSWER}>": 0}
    index.update({f"<{m}>": i + 1 for i, m in enumerate(members[2500:2510])})

    kwargs = dict(
        client=client, local_index=index, member_limit=2000,
        max_member_rows=2000, min_local_candidates=10,
    )
    if mode == "manual":
        kwargs["requested_class"] = BIG_CAT
    result = ce.select_candidate_classes(ANSWER, mode=mode, **kwargs)

    assert result.selection_status is not ce.SelectionStatus.INSUFFICIENT_LOCAL_CANDIDATES
    assert result.selection_status is not ce.SelectionStatus.ALL_CATEGORIES_REJECTED
    assert result.number_rejected_by_reason == {}
    assert result.number_inconclusive_by_reason == {ce.REASON_LOCAL_INCONCLUSIVE: 1}

    candidate = result.evaluated_classes[0]
    assert candidate.local_check is ce.LocalCheck.INCONCLUSIVE
    assert candidate.local_check is not ce.LocalCheck.CHECKED_INSUFFICIENT
    assert candidate.local_count_is_lower_bound is True
    assert client.stalled_pages >= 2, "the stall must be observed, not assumed"


def test_stalled_cursor_never_reports_complete_enumeration():
    """The unit-level guarantee behind the test above."""
    members = [f"{RESOURCE}m{i:05d}" for i in range(3000)]
    client = StalledPaginationClient(
        categories=(BIG_CAT,), counts={BIG_CAT: 3000}, members={BIG_CAT: members}
    )
    runner = ce.SparqlRunner(client=client)
    counted, failed = ce._count_local_members(
        runner, BIG_CAT, {}, min_local_candidates=10, member_limit=2000, max_pages=5
    )
    assert failed is False
    assert counted.complete is False
    assert counted.is_lower_bound is True
    assert counted.verdict(10) is ce.LocalCheck.INCONCLUSIVE


# ---------------------------------------------------------------------------
# Members are counted once each, however often the endpoint repeats them
# ---------------------------------------------------------------------------

DUP_CAT = CATEGORY + "Duplicated_class"


class DuplicatePageClient(FakeSparqlClient):
    """Replays one full page forever, so every page after the first is duplication."""

    def _rows(self, qid, query):
        if qid != "class_members":
            return super()._rows(qid, query)
        target = next((cat for cat in self.members if f"<{cat}>" in query), None)
        page = sorted(self.members.get(target, []))
        self.pages_served = getattr(self, "pages_served", 0) + 1
        return [{"x": self._cell(m)} for m in page]


def duplicate_page_client(*, page_size=8, local=6):
    """A full page of ``page_size`` members, exactly ``local`` of them in the KG."""
    members = [f"{RESOURCE}dup{i:04d}" for i in range(page_size)]
    client = DuplicatePageClient(
        label="Shinya Yamanaka",
        member=True,
        categories=(DUP_CAT,),
        counts={DUP_CAT: 3000},  # far larger than the page: never batchable
        members={DUP_CAT: members},
    )
    index = {f"<{ANSWER}>": 0}
    index.update({f"<{m}>": i + 1 for i, m in enumerate(members[:local])})
    return client, index


def test_count_local_members_counts_unique_uris_not_rows():
    client, index = duplicate_page_client()
    runner = ce.SparqlRunner(client=client)
    counted, failed = ce._count_local_members(
        runner, DUP_CAT, index,
        min_local_candidates=10, member_limit=8, max_pages=5,
    )
    assert failed is False
    assert counted.count == 6, "a member repeated across pages must be counted once"
    assert counted.complete is False
    assert counted.verdict(10) is ce.LocalCheck.INCONCLUSIVE
    assert counted.verdict(10) is not ce.LocalCheck.CHECKED_FEASIBLE
    assert counted.verdict(10) is not ce.LocalCheck.CHECKED_INSUFFICIENT
    assert client.pages_served >= 2, "the repetition must be observed, not assumed"


@pytest.mark.parametrize("mode", ["manual", "recommended"])
def test_repeated_pages_never_inflate_the_local_candidate_count(mode):
    """Six unique local members can never satisfy a threshold of ten."""
    client, index = duplicate_page_client()
    kwargs = dict(
        client=client, local_index=index, member_limit=8,
        max_member_rows=2000, min_local_candidates=10,
    )
    if mode == "manual":
        kwargs["requested_class"] = DUP_CAT
    result = ce.select_candidate_classes(ANSWER, mode=mode, **kwargs)

    assert result.selection_status is not ce.SelectionStatus.OK
    assert result.selection_status is not ce.SelectionStatus.INSUFFICIENT_LOCAL_CANDIDATES
    assert result.selection_status is not ce.SelectionStatus.ALL_CATEGORIES_REJECTED
    assert result.recommended_classes == ()

    candidate = result.evaluated_classes[0]
    assert candidate.local_count == 6, "the reported count stays at six unique members"
    assert candidate.local_count != 12
    assert candidate.local_check is ce.LocalCheck.INCONCLUSIVE
    assert candidate.local_check is not ce.LocalCheck.CHECKED_FEASIBLE
    assert candidate.local_count_is_lower_bound is True
    assert result.number_inconclusive_by_reason == {ce.REASON_LOCAL_INCONCLUSIVE: 1}
    assert result.number_rejected_by_reason == {}


# ---------------------------------------------------------------------------
# Cursor advancement
# ---------------------------------------------------------------------------


class ScriptedPageClient(FakeSparqlClient):
    """Serves a fixed script of member pages, ignoring the keyset filter.

    This lets a page sequence that no correct endpoint would produce — an
    identical page, or one that moves backwards — be replayed deterministically.
    """

    def __init__(self, *, pages, **kwargs):
        super().__init__(**kwargs)
        self.pages = [list(p) for p in pages]
        self.served = 0

    def _rows(self, qid, query):
        if qid != "class_members":
            return super()._rows(qid, query)
        page = self.pages[min(self.served, len(self.pages) - 1)]
        self.served += 1
        return [{"x": self._cell(m)} for m in page]


def _scripted(letter, indices):
    return [f"{RESOURCE}{letter}{i}" for i in indices]


@pytest.mark.parametrize(
    "case, pages, expect_complete, expect_count, expect_pages",
    [
        # A cursor that strictly advances, ending on a short page: exhaustive.
        ("advancing", [_scripted("a", range(4)), _scripted("b", range(2))],
         True, 6, 2),
        # The same page twice: the cursor cannot advance, so nothing is proven.
        ("identical", [_scripted("a", range(4)), _scripted("a", range(4))],
         False, 4, 2),
        # A page whose maximum URI is below the previous cursor: also stalled.
        ("backwards", [_scripted("b", range(4)), _scripted("a", range(4))],
         False, 8, 2),
        # Overlapping pages still make progress, so enumeration may complete.
        ("overlapping",
         [_scripted("a", range(4)), _scripted("a", range(2, 6)), _scripted("a", [6])],
         True, 7, 3),
    ],
)
def test_cursor_advancement_decides_whether_enumeration_is_complete(
    case, pages, expect_complete, expect_count, expect_pages
):
    members = sorted({m for page in pages for m in page})
    client = ScriptedPageClient(
        pages=pages,
        categories=(DUP_CAT,),
        counts={DUP_CAT: 3000},
        members={DUP_CAT: members},
    )
    index = {f"<{m}>": i for i, m in enumerate(members)}
    runner = ce.SparqlRunner(client=client)
    counted, failed = ce._count_local_members(
        runner, DUP_CAT, index,
        min_local_candidates=20,  # high enough that early stopping never fires
        member_limit=4,
        max_pages=5,
    )
    assert failed is False
    assert counted.complete is expect_complete, case
    assert counted.count == expect_count, case
    assert counted.pages == expect_pages, case
    if not expect_complete:
        assert counted.verdict(20) is ce.LocalCheck.INCONCLUSIVE, case


def test_local_member_count_verdicts():
    feasible = ce.LocalMemberCount(count=12, complete=False, pages=2)
    assert feasible.verdict(10) is ce.LocalCheck.CHECKED_FEASIBLE
    assert feasible.is_lower_bound is True

    insufficient = ce.LocalMemberCount(count=4, complete=True, pages=1)
    assert insufficient.verdict(10) is ce.LocalCheck.CHECKED_INSUFFICIENT
    assert insufficient.is_lower_bound is False

    unknown = ce.LocalMemberCount(count=4, complete=False, pages=1)
    assert unknown.verdict(10) is ce.LocalCheck.INCONCLUSIVE


# ---------------------------------------------------------------------------
# The Answer is never one of its own distractors
# ---------------------------------------------------------------------------

EXCL_CAT = CATEGORY + "Answer_plus_nine"


def answer_plus_nine_client(*, extra_members=()):
    """A class holding the Answer and exactly nine other unique local members."""
    others = [f"{RESOURCE}peer{i:02d}" for i in range(9)]
    members = [ANSWER, *extra_members, *others]
    client = FakeSparqlClient(
        label="Shinya Yamanaka",
        member=True,
        categories=(EXCL_CAT,),
        counts={EXCL_CAT: len(members)},
        members={EXCL_CAT: members},
    )
    index = {f"<{uri}>": i for i, uri in enumerate(members)}
    return client, index


@pytest.mark.parametrize("mode", ["manual", "recommended", "first_feasible"])
def test_the_answer_does_not_count_as_its_own_distractor(mode):
    client, index = answer_plus_nine_client()
    kwargs = dict(
        client=client, local_index=index,
        min_remote_candidates=5, min_local_candidates=10,
    )
    if mode == "manual":
        kwargs["requested_class"] = EXCL_CAT
    result = ce.select_candidate_classes(ANSWER, mode=mode, **kwargs)

    candidate = result.evaluated_classes[0]
    assert candidate.remote_count == 10, "class size keeps counting the answer"
    assert candidate.eligible_remote_count == 9, "one of the ten is the answer"
    assert candidate.local_count == 9, "nine eligible local distractor candidates"
    assert candidate.local_check is ce.LocalCheck.CHECKED_INSUFFICIENT
    assert candidate.rejected_code == ce.REASON_LOCAL_TOO_FEW
    assert result.selection_status is not ce.SelectionStatus.OK
    assert result.selected_class is None

    if mode == "manual":
        assert result.selection_status is ce.SelectionStatus.INSUFFICIENT_LOCAL_CANDIDATES
    else:
        assert result.selection_status is ce.SelectionStatus.ALL_CATEGORIES_REJECTED


def test_min_remote_candidates_applies_to_the_eligible_count():
    """A class of exactly ``min_remote_candidates`` members supplies one too few."""
    client, _ = answer_plus_nine_client()
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client,
        min_remote_candidates=10, max_remote_candidates=5000,
    )
    candidate = result.evaluated_classes[0]
    assert candidate.remote_count == 10
    assert candidate.eligible_remote_count == 9
    assert candidate.rejected_code == ce.REASON_TOO_SMALL
    assert "excluding the answer" in candidate.rejected_reason


def test_max_remote_candidates_and_specificity_still_use_the_full_class_size():
    """The generic-class ceiling and the IDF are properties of the whole class."""
    size = 4_000_000
    client = make_client(counts={CAT_BIO: size})
    result = ce.select_candidate_classes(ANSWER, mode="recommended", client=client)
    candidate = next(
        c for c in result.evaluated_classes if c.category_uri == CAT_BIO
    )
    assert candidate.remote_count == size
    assert candidate.eligible_remote_count == size - 1
    assert candidate.rejected_code == ce.REASON_TOO_GENERIC
    assert candidate.raw_idf == pytest.approx(
        ce.category_specificity(size, total_entities=ce.DEFAULT_TOTAL_ENTITIES)
    ), "specificity is computed from the complete class size"


def test_neither_the_original_nor_the_canonical_uri_counts_as_a_distractor():
    """After a redirect, both spellings of the Answer are excluded exactly once."""
    target = RESOURCE + "Yamanaka_Shinya"
    client, index = answer_plus_nine_client(extra_members=(target,))

    class RedirectedClient(LabelledRedirectClient):
        pass

    redirected = RedirectedClient(
        label="Shinya Yamanaka",
        categories=(EXCL_CAT,),
        counts=client.counts,
        members=client.members,
    )
    resolver = FakeRedirectResolver({ANSWER: target})
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=redirected, local_index=index,
        resolve_redirects=True, redirect_resolver=resolver,
        min_remote_candidates=5, min_local_candidates=10,
    )

    assert result.redirect_used is True
    assert result.query_uri == target
    assert result.original_uri == ANSWER

    candidate = result.evaluated_classes[0]
    assert candidate.remote_count == 11
    assert candidate.local_count == 9, "both spellings of the answer are excluded"
    assert candidate.local_check is ce.LocalCheck.CHECKED_INSUFFICIENT


def test_excluding_the_same_uri_twice_has_no_effect():
    client, index = answer_plus_nine_client()
    runner = ce.SparqlRunner(client=client)
    kwargs = dict(min_local_candidates=99, member_limit=100, max_pages=2)
    once, _ = ce._count_local_members(
        runner, EXCL_CAT, index, exclude_uris=(ANSWER,), **kwargs
    )
    twice, _ = ce._count_local_members(
        runner, EXCL_CAT, index, exclude_uris=(ANSWER, ANSWER), **kwargs
    )
    none, _ = ce._count_local_members(runner, EXCL_CAT, index, **kwargs)
    assert once.count == twice.count == 9
    assert none.count == 10, "without an exclusion list the answer is still counted"


def test_the_answer_is_excluded_on_the_paginated_path_too():
    """The batched and paginated probes must agree about the Answer."""
    client, index = answer_plus_nine_client()
    client.counts[EXCL_CAT] = 3000  # too large for the batch: force pagination
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, local_index=index,
        member_limit=100, max_member_rows=100, min_remote_candidates=5,
        min_local_candidates=10,
    )
    assert client.calls.count("class_members") >= 1, "the paginated path must be used"
    candidate = result.evaluated_classes[0]
    assert candidate.local_count == 9
    assert candidate.local_check is ce.LocalCheck.CHECKED_INSUFFICIENT


# ---------------------------------------------------------------------------
# min_local_candidates == 0 asks for no local guarantee
# ---------------------------------------------------------------------------


MEMBER_QIDS = ("class_members", "class_members_batch")


@pytest.mark.parametrize("mode", ["manual", "recommended", "first_feasible"])
@pytest.mark.parametrize("index_has_answer", [True, False])
def test_zero_min_local_candidates_skips_the_local_check(mode, index_has_answer):
    """Vacuously satisfied: no member query, no probe budget, no rejection."""
    client = make_client(member=True)
    index = local_index_for(client) if index_has_answer else {"<%s>" % OTHER_ANSWER: 0}

    kwargs = dict(
        client=client, local_index=index,
        min_local_candidates=0, max_local_probes=0,
    )
    if mode == "manual":
        kwargs["requested_class"] = CAT_NOBEL
    result = ce.select_candidate_classes(ANSWER, mode=mode, **kwargs)

    assert result.selection_status is ce.SelectionStatus.OK
    assert result.selected_class is not None
    assert not any(qid in MEMBER_QIDS for qid in client.calls), (
        f"no member query may be issued: {client.calls}"
    )
    for candidate in result.evaluated_classes:
        assert candidate.local_check is ce.LocalCheck.NOT_APPLICABLE
        assert candidate.local_count is None
        assert candidate.rejected_code != ce.REASON_LOCAL_NOT_PROBED
        assert candidate.rejected_code != ce.REASON_LOCAL_TOO_FEW
        assert candidate.rejected_code != ce.REASON_LOCAL_INCONCLUSIVE
    assert result.selection_status is not ce.SelectionStatus.LOCAL_URI_NOT_FOUND


def test_zero_min_local_candidates_still_applies_remote_checks():
    """Skipping the local check must not weaken remote feasibility."""
    client = make_client(counts={CAT_BIO: 2, CAT_NOBEL: 3, CAT_STEM: 4})
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client,
        local_index=local_index_for(client),
        min_local_candidates=0, max_local_probes=0,
    )
    assert result.selection_status is ce.SelectionStatus.ALL_CATEGORIES_REJECTED
    assert ce.REASON_TOO_SMALL in result.number_rejected_by_reason
    assert not any(qid in MEMBER_QIDS for qid in client.calls)


def test_a_missing_local_uri_still_fails_when_a_local_guarantee_is_requested():
    """The default of 10 is untouched: the index requirement still bites."""
    client = make_client(member=True)
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client,
        local_index={"<%s>" % OTHER_ANSWER: 0},
    )
    assert ce.DEFAULT_MIN_LOCAL_CANDIDATES == 10
    assert result.selection_status is ce.SelectionStatus.LOCAL_URI_NOT_FOUND


# ---------------------------------------------------------------------------
# An incompatible cache file is refused without being touched
# ---------------------------------------------------------------------------


def _tables(path):
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()


def test_a_mismatched_schema_version_is_refused_before_any_table_is_created(tmp_path):
    """The old order created 'responses' first, marking a file it then refused."""
    import sqlite3

    path = tmp_path / "v999.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES ('schema_version', 'sparql_cache_v999')")
    conn.commit()
    conn.close()

    assert _tables(path) == {"meta"}, "the fixture must have no 'responses' table"
    before_bytes = path.read_bytes()
    before_digest = hashlib.sha256(before_bytes).hexdigest()

    with pytest.raises(ce.CacheSchemaMismatch):
        ce.SqliteSparqlCache(path).get("anything")

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before_digest
    assert path.read_bytes() == before_bytes, "the incompatible file was modified"
    assert "responses" not in _tables(path), "a table was created in a refused file"
    assert _tables(path) == {"meta"}


def test_a_meta_table_without_a_schema_version_is_refused(tmp_path):
    import sqlite3

    path = tmp_path / "no_version.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES ('endpoint', 'http://fake.invalid/sparql')")
    conn.commit()
    conn.close()
    before = path.read_bytes()

    with pytest.raises(ce.CacheSchemaMismatch):
        ce.SqliteSparqlCache(path).get("anything")
    assert path.read_bytes() == before
    assert "responses" not in _tables(path)


def test_a_matching_version_with_a_missing_table_is_refused_not_repaired(tmp_path):
    import sqlite3

    path = tmp_path / "incomplete.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        "INSERT INTO meta VALUES ('schema_version', ?)", (ce.CACHE_SCHEMA_VERSION,)
    )
    conn.commit()
    conn.close()
    before = path.read_bytes()

    with pytest.raises(ce.CacheSchemaMismatch):
        ce.SqliteSparqlCache(path).get("anything")
    assert path.read_bytes() == before, "an incomplete cache must not be repaired"
    assert "responses" not in _tables(path)


def test_a_new_database_is_still_created_normally(tmp_path):
    path = tmp_path / "fresh" / "cache.sqlite"
    cache = ce.SqliteSparqlCache(path, endpoint="http://fake.invalid/sparql")
    cache.put("k", {
        "endpoint": "http://fake.invalid/sparql", "language": "en",
        "response_json": "[]", "query_status": "ok", "retrieved_at": 1.0,
    })
    assert _tables(path) == {"responses", "meta"}
    assert cache.meta()["schema_version"] == ce.CACHE_SCHEMA_VERSION
    assert cache.get("k") is not None
    cache.close()

    # Reopening a complete, matching database succeeds.
    again = ce.SqliteSparqlCache(path, endpoint="http://fake.invalid/sparql")
    assert again.get("k") is not None
    again.close()


# ---------------------------------------------------------------------------
# Bypass provenance survives failure
# ---------------------------------------------------------------------------


def test_a_bypassed_failure_is_reported_as_bypass_not_miss():
    cache = ce.InMemorySparqlCache()
    broken = FakeSparqlClient(raise_qids={"answer_info"})
    runner = ce.SparqlRunner(client=broken, cache=cache, bypass=True)

    result = runner.run(ce.build_answer_info_query(ANSWER))

    assert result.status is ce.QueryStatus.FAILED
    assert result.cache_status is ce.CacheStatus.BYPASS
    assert result.cache_status is not ce.CacheStatus.MISS
    assert len(cache) == 0, "a bypassed run must write nothing"
    assert runner.n_failed == 1


def test_failure_cache_status_still_distinguishes_disabled_and_miss():
    """The other two failure provenances are unchanged."""
    disabled = ce.SparqlRunner(client=FakeSparqlClient(raise_qids={"answer_info"}))
    assert disabled.run(
        ce.build_answer_info_query(ANSWER)
    ).cache_status is ce.CacheStatus.DISABLED

    cache = ce.InMemorySparqlCache()
    missing = ce.SparqlRunner(
        client=FakeSparqlClient(raise_qids={"answer_info"}), cache=cache
    )
    assert missing.run(
        ce.build_answer_info_query(ANSWER)
    ).cache_status is ce.CacheStatus.MISS
    assert len(cache) == 0


# ---------------------------------------------------------------------------
# Result schema version
# ---------------------------------------------------------------------------


def test_result_schema_version_is_bumped_and_the_cache_schema_is_not():
    # 3.2: sparql_query_count and cache_stats became per-Answer rather than
    # cumulative, so records from 3.1 and 3.2 are not counter-comparable.
    # 3.3: those counters now include the built-in redirect query, so
    # redirect-enabled 3.2 and 3.3 records are not comparable either.
    assert ce.SCHEMA_VERSION == "category_selector_v3.3"
    assert ce.CACHE_SCHEMA_VERSION == "sparql_cache_v3.0", (
        "the SQLite table schema has not changed, so its version must not move"
    )


def test_serialised_results_carry_the_new_schema_version():
    import json

    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=make_client()
    )
    assert result.schema_version == "category_selector_v3.3"
    assert result.to_dict()["schema_version"] == "category_selector_v3.3"
    assert json.loads(result.to_json())["schema_version"] == "category_selector_v3.3"


# ---------------------------------------------------------------------------
# Result counters describe one Answer, not the runner's running total
# ---------------------------------------------------------------------------


OTHER_ANSWER = RESOURCE + "Kenichi_Fukui"


def test_a_reused_runner_reports_each_answer_separately():
    """Two Answers on one runner must not inherit each other's counters."""
    client = make_client()
    runner = ce.SparqlRunner(client=client)

    first = ce.select_candidate_classes(ANSWER, mode="recommended", runner=runner)
    second = ce.select_candidate_classes(OTHER_ANSWER, mode="recommended", runner=runner)

    assert first.sparql_query_count > 0
    assert second.sparql_query_count > 0
    assert second.sparql_query_count == first.sparql_query_count, (
        "the same work must cost the same, whichever Answer ran first"
    )
    # The bug this guards: the second result reporting first + second.
    assert second.sparql_query_count != (
        first.sparql_query_count + second.sparql_query_count
    )
    # The runner keeps the batch total.
    assert runner.stats()["queries"] == (
        first.sparql_query_count + second.sparql_query_count
    )
    assert runner.n_queries == len(client.calls)

    for result in (first, second):
        assert result.sparql_query_count == result.cache_stats["queries"]
        assert set(result.cache_stats) == {
            "queries", "cache_hits", "client_calls", "failed", "zero_results"
        }


def test_cache_hits_are_scoped_to_the_answer_that_incurred_them():
    client = make_client()
    cache = ce.InMemorySparqlCache()
    runner = ce.SparqlRunner(client=client, cache=cache)

    first = ce.select_candidate_classes(ANSWER, mode="recommended", runner=runner)
    calls_after_first = len(client.calls)
    second = ce.select_candidate_classes(ANSWER, mode="recommended", runner=runner)

    assert first.cache_stats["cache_hits"] == 0, "nothing was cached yet"
    assert first.cache_stats["client_calls"] == first.sparql_query_count

    assert second.cache_stats["cache_hits"] == second.sparql_query_count, (
        "every query of the repeat run was served from cache"
    )
    assert second.cache_stats["client_calls"] == 0
    assert len(client.calls) == calls_after_first, "the client was not called again"

    # Cumulative view is unchanged and is the sum of the two.
    assert runner.stats()["queries"] == (
        first.sparql_query_count + second.sparql_query_count
    )
    assert runner.stats()["cache_hits"] == second.cache_stats["cache_hits"]
    assert runner.stats()["client_calls"] == calls_after_first


def test_an_early_return_reports_zero_not_the_runners_history():
    """A result produced before any query must not inherit earlier counters."""
    client = make_client()
    runner = ce.SparqlRunner(client=client)

    warmup = ce.select_candidate_classes(ANSWER, mode="recommended", runner=runner)
    assert runner.n_queries > 0, "the runner must carry a nonzero history"

    # A foreign host can never denote a DBpedia category, so manual mode
    # refuses it before spending a query.
    rejected = ce.select_candidate_classes(
        ANSWER, mode="manual",
        requested_class="http://evil.example/resource/Category:X",
        runner=runner,
    )
    assert rejected.selection_status is ce.SelectionStatus.MANUAL_CLASS_INVALID
    assert rejected.sparql_query_count == 0
    assert rejected.cache_stats == {
        "queries": 0, "cache_hits": 0, "client_calls": 0,
        "failed": 0, "zero_results": 0,
    }
    assert runner.stats()["queries"] == warmup.sparql_query_count, (
        "the rejected request must not have spent a query either"
    )


def test_failure_counters_are_also_per_answer():
    client = make_client(fail_qids={"answer_info"})
    runner = ce.SparqlRunner(client=client)

    first = ce.select_candidate_classes(ANSWER, mode="recommended", runner=runner)
    second = ce.select_candidate_classes(OTHER_ANSWER, mode="recommended", runner=runner)

    assert first.query_status is ce.QueryStatus.FAILED
    assert first.cache_stats["failed"] == 1
    assert second.cache_stats["failed"] == 1, "not 2"
    assert runner.stats()["failed"] == 2


def test_per_answer_runner_delegates_without_disturbing_the_shared_runner():
    """The wrapper is a counter view: caching and transport are the delegate's."""
    client = make_client()
    cache = ce.InMemorySparqlCache()
    shared = ce.SparqlRunner(client=client, cache=cache)
    view = ce.PerAnswerRunner(shared)

    query = ce.build_answer_info_query(ANSWER)
    first = view.run(query)
    assert first.cache_status is ce.CacheStatus.MISS
    assert view.stats() == shared.stats()

    second = view.run(query)
    assert second.cache_status is ce.CacheStatus.HIT
    assert view.stats()["cache_hits"] == 1

    # A fresh view over the same runner starts at zero; the runner does not.
    fresh = ce.PerAnswerRunner(shared)
    assert fresh.stats() == {
        "queries": 0, "cache_hits": 0, "client_calls": 0,
        "failed": 0, "zero_results": 0,
    }
    assert shared.stats()["queries"] == 2
    assert fresh.endpoint == shared.endpoint and fresh.language == shared.language


def test_eligible_remote_count_is_serialised_and_reported():
    import json

    client, _ = answer_plus_nine_client()
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, min_remote_candidates=5
    )
    record = json.loads(result.to_json())
    candidate = record["evaluated_classes"][0]
    assert candidate["eligible_remote_count"] == 9
    assert candidate["remote_count"] == 10
    assert "eligible=9" in ce.format_selection_report(result)


def test_no_feasible_class_distinguishes_rejection_from_incomplete_evaluation():
    """The four aggregate outcomes a run can end in when nothing is selected."""
    # (a) every class genuinely rejected: all three are too small.
    all_rejected = ce.select_candidate_classes(
        ANSWER, mode="recommended",
        client=make_client(counts={CAT_BIO: 2, CAT_NOBEL: 3, CAT_STEM: 4}),
    )
    assert all_rejected.selection_status is ce.SelectionStatus.ALL_CATEGORIES_REJECTED
    assert all_rejected.number_rejected_by_reason == {
        ce.REASON_JUNK: 1, ce.REASON_TOO_SMALL: 3
    }
    assert all_rejected.number_inconclusive_by_reason == {}
    assert all_rejected.number_not_evaluated_by_reason == {}

    # (b) one inconclusive class, none feasible.
    client, index = big_class_client()
    inconclusive = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, local_index=index,
        member_limit=2000, max_member_rows=2000, max_member_pages=1,
        min_local_candidates=10,
    )
    assert inconclusive.selection_status is ce.SelectionStatus.NO_CONFIRMED_FEASIBLE_CLASS
    assert inconclusive.number_rejected_by_reason == {}
    assert inconclusive.number_inconclusive_by_reason == {ce.REASON_LOCAL_INCONCLUSIVE: 1}

    # (c) one unprobed class, none feasible: only the Answer is in the local KG,
    #     and the probe budget stops after the first class.
    unprobed_client = make_client()
    unprobed = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=unprobed_client,
        local_index={f"<{ANSWER}>": 0}, max_local_probes=1, min_local_candidates=10,
    )
    assert unprobed.selection_status is ce.SelectionStatus.NO_CONFIRMED_FEASIBLE_CLASS
    assert unprobed.number_not_evaluated_by_reason == {ce.REASON_LOCAL_NOT_PROBED: 2}
    assert unprobed.number_rejected_by_reason == {
        ce.REASON_JUNK: 1, ce.REASON_LOCAL_TOO_FEW: 1
    }
    assert unprobed.number_inconclusive_by_reason == {}

    # (d) a mixture containing one feasible class still succeeds.
    mixed_client = make_client()
    mixed_index = {f"<{ANSWER}>": 0}
    mixed_index.update(
        {f"<{m}>": i + 1 for i, m in enumerate(mixed_client.members[CAT_NOBEL])}
    )
    mixed = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=mixed_client, local_index=mixed_index,
        max_local_probes=2, min_local_candidates=10,
    )
    assert mixed.selection_status is ce.SelectionStatus.OK
    assert mixed.selected_class == CAT_NOBEL
    assert mixed.number_rejected_by_reason == {
        ce.REASON_JUNK: 1, ce.REASON_LOCAL_TOO_FEW: 1
    }
    assert mixed.number_not_evaluated_by_reason == {ce.REASON_LOCAL_NOT_PROBED: 1}


def test_summary_buckets_are_disjoint_and_serialised():
    client, index = big_class_client()
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, local_index=index,
        member_limit=2000, max_member_rows=2000, max_member_pages=1,
    )
    record = result.to_dict()
    for key in (
        "number_rejected_by_reason",
        "number_inconclusive_by_reason",
        "number_not_evaluated_by_reason",
    ):
        assert key in record
    codes = [
        set(record["number_rejected_by_reason"]),
        set(record["number_inconclusive_by_reason"]),
        set(record["number_not_evaluated_by_reason"]),
    ]
    assert not (codes[0] & codes[1]) and not (codes[0] & codes[2]) and not (codes[1] & codes[2])
    # Unresolved codes are never counted as demonstrated rejections.
    assert not (set(record["number_rejected_by_reason"]) & ce.UNRESOLVED_REASON_CODES)


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"alpha": -0.1},
        {"alpha": 1.5},
        {"top_n": 0},
        {"top_n": -3},
        {"min_remote_candidates": -1},
        {"max_remote_candidates": -5},
        {"min_local_candidates": -2},
        {"min_remote_candidates": 500, "max_remote_candidates": 100},
        {"member_limit": 0},
        {"max_member_rows": 0},
        {"max_local_probes": -1},
        {"max_member_pages": 0},
        {"soft_leak_penalty": -0.25},
        {"total_entities": 0},
        {"category_limit": 0},
        {"aggregation": "magic"},
    ],
)
def test_invalid_configuration_raises_before_any_query(overrides):
    client = make_client()
    with pytest.raises(ValueError, match="invalid selector configuration"):
        ce.select_candidate_classes(ANSWER, mode="recommended", client=client, **overrides)
    assert client.calls == [], "an invalid configuration must not spend a query"


def test_valid_boundary_configuration_is_accepted():
    client = make_client()
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, alpha=0.0, top_n=1,
        min_local_candidates=0, max_local_probes=0, soft_leak_penalty=0.0,
    )
    assert result.selection_status is ce.SelectionStatus.OK
    assert len(result.recommended_classes) == 1

    edge = make_client()
    assert (
        ce.select_candidate_classes(
            ANSWER, mode="recommended", client=edge, alpha=1.0
        ).selection_status
        is ce.SelectionStatus.OK
    )


# ---------------------------------------------------------------------------
# Strict URI validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.example/resource/Category:Injected",
        "http://evil.example/resource/Category:X",
        "http://dbpedia.org/resource/FooCategory:Bar",
        "http://dbpedia.org/resource/Plato",
        "ftp://dbpedia.org/resource/Category:X",
        "http://dbpedia.org/resource/Category:X> <http://evil/y",
        'http://dbpedia.org/resource/Category:X"} INSERT DATA {',
        "http://dbpedia.org/resource/Category:X\nDROP ALL",
        "http://dbpedia.org/resource/Category:X\x00",
        "dbc:X{}",
        "dbc:X'",
        "dbc:X`",
        "dbc:X|Y",
        "dbc:A/B",
        "dbc:",
        "",
        None,
    ],
)
def test_normalize_category_rejects_foreign_or_unsafe_values(value):
    assert ce.normalize_category(value) is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("dbc:Japanese_Nobel_laureates", CAT_NOBEL),
        ("Category:Japanese_Nobel_laureates", CAT_NOBEL),
        (CAT_NOBEL, CAT_NOBEL),
        (f"<{CAT_NOBEL}>", CAT_NOBEL),
        ("Japanese Nobel laureates", CAT_NOBEL),
        ("https://dbpedia.org/resource/Category:Japanese_Nobel_laureates", CAT_NOBEL),
        # A colon inside the local name is legitimate and must survive.
        (
            CATEGORY + "Star_Trek:_Voyager_episodes",
            CATEGORY + "Star_Trek:_Voyager_episodes",
        ),
        ("dbc:Star_Trek:_Voyager_episodes", CATEGORY + "Star_Trek:_Voyager_episodes"),
        (
            "Category:Star_Trek:_Voyager_episodes",
            CATEGORY + "Star_Trek:_Voyager_episodes",
        ),
    ],
)
def test_normalize_category_accepts_and_canonicalises_valid_values(value, expected):
    assert ce.normalize_category(value) == expected


def test_local_name_punctuation_is_kept_but_the_prefix_stays_exact():
    """Colons inside a local name are fine; a wrong namespace still is not."""
    good = CATEGORY + "Star_Trek:_Voyager_episodes"
    assert ce.normalize_category(good) == good
    assert ce.is_safe_uri(good) is True
    assert "Star_Trek:_Voyager_episodes" in ce.build_class_members_query(good)

    # Only the exact allowed prefix counts, so this remains rejected.
    assert ce.normalize_category(RESOURCE + "FooCategory:Bar") is None
    assert ce.normalize_category("http://dbpedia.org/resource/CategoryX:Bar") is None
    assert ce.normalize_category("http://dbpedia.org/page/Category:Bar") is None


def test_is_safe_uri():
    assert ce.is_safe_uri(RESOURCE + "Plato") is True
    assert ce.is_safe_uri(f"<{RESOURCE}Plato>") is True
    assert ce.is_safe_uri(RESOURCE + "Kant%C5%8D_region") is True
    for bad in ("", None, "Plato", "ftp://x/y", RESOURCE + "A B", RESOURCE + "A>B",
                RESOURCE + "A{B", RESOURCE + 'A"B', RESOURCE + "A\nB", "javascript:x"):
        assert ce.is_safe_uri(bad) is False, bad


def test_query_builders_refuse_unvalidated_input():
    with pytest.raises(ValueError):
        ce.build_answer_info_query(RESOURCE + "A B")
    with pytest.raises(ValueError):
        ce.build_answer_info_query(ANSWER, language="en' } #")
    with pytest.raises(ValueError):
        ce.build_answer_info_query(ANSWER, membership_class="dbc:X")  # not an IRI
    with pytest.raises(ValueError):
        ce.build_answer_categories_query("Plato")
    with pytest.raises(ValueError):
        ce.build_category_counts_query([CAT_NOBEL, "javascript:alert(1)"])
    with pytest.raises(ValueError):
        ce.build_class_members_query(CAT_NOBEL + "> } #")
    with pytest.raises(ValueError):
        ce.build_class_members_query(CAT_NOBEL, after='x") FILTER(true) #')
    with pytest.raises(ValueError):
        ce.build_class_members_batch_query([CAT_NOBEL, "http://x/Category:A B"])
    with pytest.raises(ValueError):
        ce.build_redirect_query("not-a-uri")

    # The valid forms still build, and pagination stays deterministic.
    page = ce.build_class_members_query(CAT_NOBEL, limit=10, after=RESOURCE + "Nobel0001")
    # The keyset filter and the sort must use the same expression.
    assert "ORDER BY STR(?x)" in page and "LIMIT 10" in page
    assert 'FILTER(STR(?x) > "' in page
    assert "ORDER BY ?x " not in page
    assert f'STR(?x) > "{RESOURCE}Nobel0001"' in page


def test_selector_rejects_an_unsafe_answer_uri_and_language():
    with pytest.raises(ValueError, match="answer_uri"):
        ce.select_candidate_classes(RESOURCE + "A> <B", client=make_client())
    with pytest.raises(ValueError, match="language"):
        ce.select_candidate_classes(ANSWER, client=make_client(), language="en' }")


def test_endpoint_supplied_categories_are_validated_before_use():
    hostile = "http://evil.example/resource/Category:Injected"
    client = make_client(
        categories=(CAT_NOBEL, hostile), counts={CAT_NOBEL: 30}
    )
    result = ce.select_candidate_classes(ANSWER, mode="recommended", client=client)
    assert result.number_rejected_by_reason.get(ce.REASON_INVALID_URI) == 1
    assert result.selected_class == CAT_NOBEL
    assert not any("evil.example" in q for q in client.queries)


# ---------------------------------------------------------------------------
# first_feasible must not touch the encoder
# ---------------------------------------------------------------------------


class EncoderCalled(Exception):
    """Raised by the double below if the encoder is loaded or invoked."""


class ExplodingEncoder:
    name = "must-not-be-called"

    @property
    def max_seq_length(self):
        raise EncoderCalled("max_seq_length was read")

    def encode(self, texts):
        raise EncoderCalled("encode() was called")


def test_first_feasible_and_manual_never_load_or_call_the_encoder():
    client = make_client()
    index = local_index_for(client)

    first = ce.select_candidate_classes(
        ANSWER, mode="first_feasible", client=client,
        encoder=ExplodingEncoder(), local_index=index,
    )
    assert first.selection_status is ce.SelectionStatus.OK
    assert first.selected_class == CAT_NOBEL
    assert first.encoder_metadata["available"] is False
    assert "not computed" in first.encoder_metadata["note"]
    assert all(c.scored is False for c in first.recommended_classes)
    assert all(c.combined_score == 0.0 for c in first.recommended_classes)

    manual_client = make_client(member=True)
    manual = ce.select_candidate_classes(
        ANSWER, mode="manual", requested_class=CAT_NOBEL, client=manual_client,
        encoder=ExplodingEncoder(), local_index=local_index_for(manual_client),
    )
    assert manual.selection_status is ce.SelectionStatus.OK

    # The double really does fire when scoring is genuinely requested.
    with pytest.raises(EncoderCalled):
        ce.select_candidate_classes(
            ANSWER, mode="recommended", client=make_client(), encoder=ExplodingEncoder()
        )


# ---------------------------------------------------------------------------
# Serialization and file-safety guards
# ---------------------------------------------------------------------------


def test_audit_record_contains_every_required_field_and_serialises():
    import json

    client = make_client()
    result = ce.select_candidate_classes(
        ANSWER, mode="recommended", client=client, encoder=FakeEncoder(),
        local_index=local_index_for(client),
    )
    record = json.loads(result.to_json())
    for field in (
        "original_uri", "query_uri", "local_kg_uri", "display_label", "query_status",
        "selection_status", "mode", "number_of_categories", "number_rejected_by_reason",
        "number_inconclusive_by_reason", "number_not_evaluated_by_reason",
        "recommended_classes", "selected_class", "redirect_used",
    ):
        assert field in record, f"missing audit field: {field}"
    assert record["query_status"] in {"ok", "zero_results", "query_failed"}
    assert record["sparql_query_count"] == client.calls.__len__()
    assert record["cache_stats"]["queries"] >= 1


def test_v2_source_file_is_unchanged():
    recorded = (
        REPO_ROOT / "docs" / "checksums" / "category_extractor_ClaudeWeb_v2.py.sha256"
    ).read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(
        (SRC_DIR / "category_extractor_ClaudeWeb_v2.py").read_bytes()
    ).hexdigest()
    assert actual == recorded, "the v2 source file must not be modified"


def test_selector_refuses_to_build_a_network_client_implicitly():
    with pytest.raises(ValueError, match="explicit"):
        ce.select_candidate_classes(ANSWER, mode="recommended")
    with pytest.raises(ValueError, match="mode"):
        ce.select_candidate_classes(ANSWER, mode="optimal", client=make_client())


# ---------------------------------------------------------------------------
# Integration tests — require DBpedia. NOT executed in this turn.
# ---------------------------------------------------------------------------


@pytest.mark.integration
@INTEGRATION
def test_integration_recommended_mode_against_dbpedia():
    runner = ce.make_dbpedia_runner()
    for uri in (
        RESOURCE + "Makoto_Kobayashi_(physicist)",
        RESOURCE + "Akira_Suzuki_(chemist)",
    ):
        result = ce.select_candidate_classes(uri, mode="recommended", runner=runner)
        assert result.selection_status is ce.SelectionStatus.OK
        assert result.recommended_classes


@pytest.mark.integration
@INTEGRATION
def test_integration_redirect_resolution_against_dbpedia():
    runner = ce.make_dbpedia_runner()
    resolver = ce.SparqlRedirectResolver(runner)
    uri, used = ce.resolve_query_uri(
        RESOURCE + "Yamanaka_Shinya", resolver=resolver, enabled=True
    )
    assert isinstance(uri, str) and isinstance(used, bool)
