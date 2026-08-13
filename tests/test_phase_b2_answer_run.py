############################################################################
# tests/test_phase_b2_answer_run.py
#
# Prompt 8H-B2-B: the SMALLEST tests that cover genuinely new B2 glue.
#
# WHAT IS DELIBERATELY *NOT* RETESTED HERE
#   The frozen science already has its own suites and they run unchanged:
#     tests/test_mcq_core.py            the selection kernel (243 tests)
#     tests/test_mcq_inputs.py          the nine Phase-B input invariants and
#                                       the eight-pilot build_and_select
#                                       regression (174 tests)
#     tests/test_rationale_v3.py        the R1 evidence/quality/semantic layer,
#                                       including byte-identical R1 replay
#     tests/test_category_extractor_v5.py   the v5 HARD leakage gate, including
#                                       Albert_Einstein vs Category:Einstein_family
#     tests/test_pilot_member_mapping.py    retrieval, redirects, local mapping
#     tests/test_pipeline_graph_lrolesim.py M1 budget and the frozen ranking
#   Duplicating any of them here would create a second copy of an assertion
#   that can drift from the first. What IS tested below is only the new glue:
#   reading the ranking, walking it under the local-mapping gate, deriving the
#   enlarged source-object set, and the two new keyword arguments on the
#   semantic-index build path.
############################################################################

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline import phase_b2_answer_run as b2               # noqa: E402
from pipeline.rationale_v3_run import (                      # noqa: E402
    SEMANTIC_POLICY_PATH,
    build_semantic_index_from_pinned_kg,
)
from rationale_v3.semantic_relations import (                # noqa: E402
    load_semantic_index_cache,
    load_semantic_relation_policy,
    source_object_list_sha256,
)

ANSWER = "http://dbpedia.org/resource/Albert_Einstein"
CLASS_A = "http://dbpedia.org/resource/Category:Alpha"
CLASS_B = "http://dbpedia.org/resource/Category:Beta"


# --- helpers ---------------------------------------------------------------

def _class_entry(uri, *, combined, feasible=True, remote=20, leak="no_leak"):
    return {
        "category_uri": uri,
        "category_short": "dbc:" + uri.rsplit(":", 1)[-1],
        "display_label": "Category:" + uri.rsplit(":", 1)[-1],
        "remote_count": remote,
        "eligible_remote_count": remote - 1,
        "raw_idf": 0.5, "normalized_idf": combined,
        "raw_sbert": 0.0, "normalized_sbert": 0.0,
        "combined_score": combined,
        "feasible": feasible,
        "leak_level": leak, "leak_source": "rationale_v3_r1", "leak_evidence": [],
    }


def _selection(entries):
    return {
        "original_uri": ANSWER,
        "display_label": "Albert Einstein",
        "mode": "recommended",
        "config": {"alpha": 0.7},
        "recommended_classes": entries,
    }


class FakeLookup:
    def __init__(self, index, uri=None):
        self.local_index = index
        self.found = index is not None
        self.uri = uri
        self.lookup_form = uri


def _lookup_over(mapping):
    """A `local_lookup` that resolves exactly the URIs in `mapping`."""
    def lookup(uri):
        return FakeLookup(mapping.get(uri), uri)
    return lookup


class FakeRetrieval:
    """The subset of `ClassRetrieval` the walk reads."""

    def __init__(self, class_uri, members, *, complete=True, reason=None):
        self.class_uri = class_uri
        self.member_uris = tuple(members)
        self.retrieval_complete = complete
        self.incomplete_reason = reason
        self.page_count = 1
        self.raw_member_count = len(members)
        self.non_iri_row_count = 0
        self.duplicate_row_count = 0
        self.pages = ()
        self.failures = ()

    @property
    def unique_member_count(self):
        return len(self.member_uris)

    def as_record(self):
        return {"class_uri": self.class_uri,
                "unique_member_count": self.unique_member_count}


class FakeRetriever:
    def __init__(self, by_class):
        self.by_class = by_class
        self.calls = []

    def retrieve(self, class_uri):
        self.calls.append(class_uri)
        return self.by_class[class_uri]


class NoRedirects:
    """A redirect source that is never consulted, because it must not be."""

    def lookup(self, *args, **kwargs):        # pragma: no cover - see below
        raise AssertionError("no redirect query should be issued in this test")


# ==========================================================================
# Reading the automatic v5 ranking
# ==========================================================================

def test_ranked_feasible_classes_preserves_the_selectors_own_order():
    """The order is the SELECTOR's, never re-sorted here.

    Re-sorting on a float that was serialised and re-parsed can order a tie
    differently from the run that produced it, which would silently change
    which class the local-mapping walk tries first.
    """
    ranked = b2.ranked_feasible_classes(_selection([
        _class_entry(CLASS_B, combined=0.9),
        _class_entry(CLASS_A, combined=0.9),
    ]))
    assert [r.class_uri for r in ranked] == [CLASS_B, CLASS_A]
    assert [r.rank for r in ranked] == [1, 2]


def test_infeasible_classes_never_enter_the_walk():
    ranked = b2.ranked_feasible_classes(_selection([
        _class_entry(CLASS_A, combined=0.9, feasible=False),
        _class_entry(CLASS_B, combined=0.8),
    ]))
    assert [r.class_uri for r in ranked] == [CLASS_B]


def test_a_ranking_with_no_feasible_class_is_an_error_not_an_empty_walk():
    with pytest.raises(b2.PhaseB2Error):
        b2.ranked_feasible_classes(_selection([
            _class_entry(CLASS_A, combined=0.9, feasible=False)]))


def test_load_v5_selection_requires_exactly_one_record(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(b2.PhaseB2Error):
        b2.load_v5_selection(path, ANSWER)
    row = json.dumps({"original_uri": ANSWER})
    path.write_text(row + "\n" + row + "\n", encoding="utf-8")
    with pytest.raises(b2.PhaseB2Error):
        b2.load_v5_selection(path, ANSWER)


# ==========================================================================
# §E — the local-mapping feasibility walk
# ==========================================================================

def test_walk_stops_at_the_first_locally_feasible_class_and_marks_the_rest():
    """Classes below the selected one are NOT ATTEMPTED, not rejected.

    Recording them as failures would claim a measurement the walk never made.
    """
    members_a = [f"http://dbpedia.org/resource/A{i}" for i in range(12)]
    members_b = [f"http://dbpedia.org/resource/B{i}" for i in range(12)]
    retriever = FakeRetriever({
        CLASS_A: FakeRetrieval(CLASS_A, members_a),
        CLASS_B: FakeRetrieval(CLASS_B, members_b),
    })
    lookup = _lookup_over({ANSWER: 999, **{u: i for i, u in enumerate(members_a)}})

    walk = b2.walk_ranked_classes_for_local_mapping(
        ANSWER,
        b2.ranked_feasible_classes(_selection([
            _class_entry(CLASS_A, combined=0.9),
            _class_entry(CLASS_B, combined=0.8)])),
        retriever=retriever, redirect_source=NoRedirects(),
        local_lookup=lookup, max_redirect_hops=0)

    assert walk.is_feasible
    assert walk.selected_class_uri == CLASS_A
    assert walk.selected_ranking_position == 1
    # CLASS_B was never retrieved: stopping early must cost nothing.
    assert retriever.calls == [CLASS_A]
    outcomes = {a.class_uri: a.outcome for a in walk.attempts}
    assert outcomes[CLASS_A] == b2.ATTEMPT_MAPPING_FEASIBLE
    assert outcomes[CLASS_B] == b2.ATTEMPT_NOT_ATTEMPTED_EARLIER_CLASS_SELECTED
    assert next(a for a in walk.attempts if a.class_uri == CLASS_B).attempted is False


def test_a_class_below_the_gate_is_recorded_and_the_walk_continues():
    small = [f"http://dbpedia.org/resource/S{i}" for i in range(4)]
    big = [f"http://dbpedia.org/resource/G{i}" for i in range(12)]
    retriever = FakeRetriever({
        CLASS_A: FakeRetrieval(CLASS_A, small),
        CLASS_B: FakeRetrieval(CLASS_B, big),
    })
    resolved = {ANSWER: 999}
    resolved.update({u: 100 + i for i, u in enumerate(small)})
    resolved.update({u: 200 + i for i, u in enumerate(big)})

    walk = b2.walk_ranked_classes_for_local_mapping(
        ANSWER,
        b2.ranked_feasible_classes(_selection([
            _class_entry(CLASS_A, combined=0.9),
            _class_entry(CLASS_B, combined=0.8)])),
        retriever=retriever, redirect_source=NoRedirects(),
        local_lookup=_lookup_over(resolved), max_redirect_hops=0)

    assert walk.selected_class_uri == CLASS_B
    assert walk.selected_ranking_position == 2
    first = next(a for a in walk.attempts if a.class_uri == CLASS_A)
    assert first.outcome == b2.ATTEMPT_MAPPING_BELOW_GATE
    assert first.mapped_candidate_count_excluding_answer == 4
    assert first.passes_local_mapping_gate is False


def test_an_incomplete_enumeration_is_refused_rather_than_gated_on():
    """A partial member list can only UNDERSTATE the mapped count.

    Passing the gate on one would be luck and failing it would be
    uninformative, so the class is refused outright.
    """
    members = [f"http://dbpedia.org/resource/P{i}" for i in range(20)]
    retriever = FakeRetriever({CLASS_A: FakeRetrieval(
        CLASS_A, members, complete=False, reason="PAGE_BUDGET_EXHAUSTED")})
    lookup = _lookup_over({ANSWER: 999, **{u: i for i, u in enumerate(members)}})

    walk = b2.walk_ranked_classes_for_local_mapping(
        ANSWER, b2.ranked_feasible_classes(_selection([
            _class_entry(CLASS_A, combined=0.9)])),
        retriever=retriever, redirect_source=NoRedirects(),
        local_lookup=lookup, max_redirect_hops=0)

    assert not walk.is_feasible
    assert walk.status == b2.NO_MAPPING_FEASIBLE_RANKED_CLASS
    attempt = walk.attempts[0]
    assert attempt.outcome == b2.ATTEMPT_RETRIEVAL_INCOMPLETE
    assert attempt.passes_local_mapping_gate is False


def test_the_answer_is_excluded_from_its_own_candidate_count():
    """Invariant 7 at the mapping stage: the Answer is never its own candidate."""
    members = [ANSWER] + [f"http://dbpedia.org/resource/C{i}" for i in range(12)]
    retriever = FakeRetriever({CLASS_A: FakeRetrieval(CLASS_A, members)})
    resolved = {ANSWER: 999}
    resolved.update({u: i for i, u in enumerate(members[1:])})

    walk = b2.walk_ranked_classes_for_local_mapping(
        ANSWER, b2.ranked_feasible_classes(_selection([
            _class_entry(CLASS_A, combined=0.9)])),
        retriever=retriever, redirect_source=NoRedirects(),
        local_lookup=_lookup_over(resolved), max_redirect_hops=0)

    attempt = walk.attempts[0]
    assert attempt.answer_excluded_count == 1
    assert attempt.mapped_candidate_count_excluding_answer == 12
    assert ANSWER not in {
        c.canonical_uri for c in b2.mapped_candidates_from_result(
            walk.selected_mapping)}


def test_an_answer_absent_from_the_pinned_kg_raises():
    with pytest.raises(b2.PhaseB2Error):
        b2.walk_ranked_classes_for_local_mapping(
            ANSWER, b2.ranked_feasible_classes(_selection([
                _class_entry(CLASS_A, combined=0.9)])),
            retriever=FakeRetriever({}), redirect_source=NoRedirects(),
            local_lookup=_lookup_over({}), max_redirect_hops=0)


def test_the_retrieval_budget_is_reported_as_a_walk_failure():
    """Exhausting the budget must never be reported as 'no feasible class'."""
    small = [f"http://dbpedia.org/resource/S{i}" for i in range(2)]
    retriever = FakeRetriever({
        CLASS_A: FakeRetrieval(CLASS_A, small),
        CLASS_B: FakeRetrieval(CLASS_B, small),
    })
    resolved = {ANSWER: 999, **{u: i for i, u in enumerate(small)}}
    walk = b2.walk_ranked_classes_for_local_mapping(
        ANSWER, b2.ranked_feasible_classes(_selection([
            _class_entry(CLASS_A, combined=0.9),
            _class_entry(CLASS_B, combined=0.8)])),
        retriever=retriever, redirect_source=NoRedirects(),
        local_lookup=_lookup_over(resolved), max_classes=1, max_redirect_hops=0)

    assert retriever.calls == [CLASS_A]
    second = next(a for a in walk.attempts if a.class_uri == CLASS_B)
    assert second.outcome == "NOT_ATTEMPTED_RETRIEVAL_BUDGET_EXHAUSTED"


# ==========================================================================
# §G — the exact enlarged source-object set
# ==========================================================================

class Q:
    """The two `FactQuality` attributes `enlarged_source_object_uris` reads."""

    def __init__(self, predicate, direction, counterpart):
        self.predicate_uri = predicate
        self.direction = direction
        self.counterpart_uri = counterpart

    @property
    def predicate_direction_key(self):
        return (self.predicate_uri, self.direction)


def test_source_object_set_keeps_in_and_out_apart():
    """IN and OUT are different relations and never share a key.

    An object observed under `(p, OUT)` must not be admitted because the Answer
    happens to use `(p, IN)`.
    """
    facts = [Q("p", "OUT", "http://x/a")]
    observed = {"http://x/d": {("p", "OUT"): ("http://x/b",),
                               ("p", "IN"): ("http://x/leak",)}}
    assert b2.enlarged_source_object_uris(facts, observed) == (
        "http://x/a", "http://x/b")


def test_candidate_objects_under_unused_keys_are_excluded():
    """The classifier only ever looks up `O_d(kappa)` for the Answer's own kappa.

    Indexing more would enlarge the cache-key digest without changing a single
    verdict, and would make the key depend on facts the run never consults.
    """
    facts = [Q("p", "OUT", "http://x/a")]
    observed = {"http://x/d": {("q", "OUT"): ("http://x/unused",)}}
    assert b2.enlarged_source_object_uris(facts, observed) == ("http://x/a",)


def test_ineligible_answer_facts_still_contribute_source_objects():
    """`levels_for_candidates()` classifies EVERY fact it is given.

    Only the kernel filters on `eligible`, so an index that omitted ineligible
    facts' objects would leave those pairs unresolved for no reason.
    """
    facts = [Q("p", "OUT", "http://x/a"), Q("dbp:wikiPageUsesTemplate", "OUT",
                                            "http://x/ineligible")]
    assert "http://x/ineligible" in b2.enlarged_source_object_uris(facts, {})


def test_the_source_object_list_is_sorted_and_deduplicated(tmp_path):
    facts = [Q("p", "OUT", "http://x/b"), Q("p", "OUT", "http://x/a"),
             Q("p", "IN", "http://x/a")]
    uris = b2.enlarged_source_object_uris(facts, {})
    assert uris == ("http://x/a", "http://x/b")
    path = tmp_path / "sources.txt"
    digest = b2.write_source_object_list(path, uris)
    assert path.read_text("utf-8") == "http://x/a\nhttp://x/b\n"
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()


# ==========================================================================
# The two new keyword arguments on the semantic-index build path
# ==========================================================================

class FakeKG:
    """The four members `build_semantic_index_from_pinned_kg` touches."""

    def __init__(self, url_index, index_url, out_neighbor):
        self.url_index = url_index
        self.index_url = index_url
        self.out_neighbor = out_neighbor

    def index_for_uri_or_none(self, uri):
        return self.url_index.get(uri)


def test_an_explicit_source_object_set_produces_a_matching_cache_key(tmp_path):
    """§G: the digest in the cache key IS the digest of the supplied set.

    This is what makes the pilot index legitimately refuse to load for a
    different Answer, and what makes the rebuilt index legitimately load for
    this one.
    """
    from rationale_v3.semantic_relations import SemanticIndexCacheKey

    policy = load_semantic_relation_policy(SEMANTIC_POLICY_PATH)
    sources = ("http://dbpedia.org/resource/Zurich",
               "http://dbpedia.org/resource/Bern")
    kg = FakeKG(url_index={}, index_url={}, out_neighbor={})
    cache = tmp_path / "index.json"

    written = build_semantic_index_from_pinned_kg(
        policy_path=SEMANTIC_POLICY_PATH, cache_path=cache,
        source_object_uris=sources, local_kg=kg, verbose=False)

    expected = SemanticIndexCacheKey(
        pinned_kg_sha256=b2.PINNED_LOCAL_KG_SHA256,
        policy_sha256=policy.policy_sha256,
        source_object_list_sha256=source_object_list_sha256(tuple(sorted(sources))),
        max_depth=policy.max_depth,
        creation_command="irrelevant to matching")
    index = load_semantic_index_cache(written, policy=policy, expected_key=expected)
    assert index.available is True
    assert index.cache_key.source_object_list_sha256 == source_object_list_sha256(
        tuple(sorted(sources)))
    assert index.cache_key.pinned_kg_sha256 == b2.PINNED_LOCAL_KG_SHA256
    assert index.cache_key.policy_sha256 == policy.policy_sha256
    assert index.cache_key.max_depth == policy.max_depth


def test_the_supplied_source_set_is_normalised_before_it_is_hashed(tmp_path):
    """Order and bracket spelling must not change the digest.

    Two callers holding the same set in different spellings must key the same
    cache entry, or the index would be rebuilt for no reason and the two runs
    would report different provenance for identical inputs.
    """
    kg = FakeKG(url_index={}, index_url={}, out_neighbor={})
    plain = build_semantic_index_from_pinned_kg(
        policy_path=SEMANTIC_POLICY_PATH, cache_path=tmp_path / "a.json",
        source_object_uris=("http://x/a", "http://x/b"), local_kg=kg,
        verbose=False)
    scrambled = build_semantic_index_from_pinned_kg(
        policy_path=SEMANTIC_POLICY_PATH, cache_path=tmp_path / "b.json",
        source_object_uris=("<http://x/b>", "http://x/a", "http://x/a"),
        local_kg=kg, verbose=False)
    policy = load_semantic_relation_policy(SEMANTIC_POLICY_PATH)
    first = json.loads(Path(plain).read_text("utf-8"))["cache_key"]
    second = json.loads(Path(scrambled).read_text("utf-8"))["cache_key"]
    assert (first["source_object_list_sha256"]
            == second["source_object_list_sha256"]
            == source_object_list_sha256(("http://x/a", "http://x/b")))


def test_an_index_built_for_another_set_refuses_to_load(tmp_path):
    """The refusal is the point: reuse would be a cache-key violation."""
    from rationale_v3.semantic_relations import SemanticIndexCacheKey

    policy = load_semantic_relation_policy(SEMANTIC_POLICY_PATH)
    kg = FakeKG(url_index={}, index_url={}, out_neighbor={})
    written = build_semantic_index_from_pinned_kg(
        policy_path=SEMANTIC_POLICY_PATH, cache_path=tmp_path / "index.json",
        source_object_uris=("http://x/a",), local_kg=kg, verbose=False)

    wrong = SemanticIndexCacheKey(
        pinned_kg_sha256=b2.PINNED_LOCAL_KG_SHA256,
        policy_sha256=policy.policy_sha256,
        source_object_list_sha256=source_object_list_sha256(("http://x/other",)),
        max_depth=policy.max_depth,
        creation_command="whatever")
    index = load_semantic_index_cache(written, policy=policy, expected_key=wrong)
    assert index.available is False
    assert "source_object_list_sha256" in index.unavailable_reason
    # And the refusal must never be allowed to rewrite an observation.
    assert "L0" not in index.unavailable_reason


# ==========================================================================
# Structural guarantees about this module itself
# ==========================================================================

def _executable_strings_and_names(path):
    """Every string literal and identifier in EXECUTABLE code.

    Comments never reach the AST, and module/class/function docstrings are
    excluded explicitly. That is the distinction the test needs: prose is
    allowed to discuss which class this Answer happened to select — and the
    module docstring does, because a reader must be able to see why the B2-A
    top-1 was not treated as final — while executable code must not name it,
    because that is what would make the selection non-generic.
    """
    import ast

    tree = ast.parse(path.read_text("utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))

    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                found.append(node.value)
        elif isinstance(node, ast.Name):
            found.append(node.id)
        elif isinstance(node, ast.Attribute):
            found.append(node.attr)
    return found


def test_no_answer_specific_string_controls_the_b2_selection_path():
    """§D.5 / §E: the class must come from the generic algorithm.

    `DEFAULT_ANSWER_URI` is a documented CLI default and is allowed; what is
    forbidden is any Einstein-specific *class* string reaching executable code,
    or any branch on the Answer's identity.
    """
    forbidden = ("German_relativity_theorists", "Einstein_family",
                 "German_theoretical_physicists", "Nobel_laureates_in_Physics",
                 "20th-century_German_physicists")
    for path in (SRC_DIR / "pipeline" / "phase_b2_answer_run.py",
                 REPO_ROOT / "scripts" / "run_phase_b2_answer.py"):
        executable = _executable_strings_and_names(path)
        for token in forbidden:
            offenders = [value for value in executable if token in value]
            assert not offenders, f"{path.name} names the class {token!r}: {offenders}"
        # The Answer URI itself may appear at most once, as the CLI default.
        answer_mentions = [v for v in executable if "Albert_Einstein" in v]
        assert len(answer_mentions) <= 1, f"{path.name}: {answer_mentions}"


def test_the_local_mapping_gate_is_the_declared_shared_threshold():
    """§E's gate is the SAME declared rule as the frozen stages', not a new one."""
    from classes.member_mapper import MIN_MAPPED_LOCAL_CANDIDATES
    from pipeline.graph_lrolesim_run import GRAPH_STAGE_MAPPING_GATE

    assert b2.LOCAL_MAPPING_GATE == MIN_MAPPED_LOCAL_CANDIDATES == 10
    assert b2.LOCAL_MAPPING_GATE == GRAPH_STAGE_MAPPING_GATE


def test_the_class_approval_status_never_claims_human_approval():
    """No human worksheet decision exists for a B2 Answer, so none is claimed."""
    assert "HUMAN_APPROVED" not in b2.B2_CLASS_APPROVAL_STATUS.replace(
        "NOT_HUMAN_APPROVED", "")
    assert b2.B2_CLASS_APPROVAL_STATUS.endswith("NOT_HUMAN_APPROVED")


def test_the_candidate_roster_digest_separates_rank_score_and_uri():
    """A re-ranked or re-scored roster must not reuse another roster's digest."""
    class S:
        def __init__(self, rank, uri, score):
            self.rank, self.canonical_uri, self.score = rank, uri, score

    base = [S(1, "http://x/a", 0.5), S(2, "http://x/b", 0.4)]
    reranked = [S(1, "http://x/b", 0.4), S(2, "http://x/a", 0.5)]
    rescored = [S(1, "http://x/a", 0.5000001), S(2, "http://x/b", 0.4)]
    digests = {b2.candidate_roster_digest(r)
               for r in (base, reranked, rescored)}
    assert len(digests) == 3
