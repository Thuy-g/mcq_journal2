############################################################################
# tests/test_pipeline_graph_lrolesim.py
#
# Contract tests for the Week-2 integration layer:
#   src/pipeline/candidate_order.py
#   src/pipeline/graph_lrolesim_run.py
#
# WHAT THESE TESTS DEFEND
#   * the graph-admission order is deterministic, seeded per (Answer, class), and
#     independent of local node index, input sequence and PYTHONHASHSEED;
#   * the MAPPING gate and the GRAPH gate stay distinct;
#   * approved-class order is preserved and the graph-stage fallback walks it;
#   * every candidate in a graph has neighbourhood coverage exactly 1.0;
#   * the node cap and the candidate cap hold;
#   * context nodes never become ranked candidates;
#   * LRoleSim runs L_ed, beta 0.2, EXACTLY three iterations, never convergence;
#   * ties break on ascending canonical URI, not on local index;
#   * a cached score is reused only on a full fingerprint match;
#   * an offline replay reproduces the scientific outputs byte-for-byte;
#   * the Sulfuric-acid diagnostic stays out of every primary metric;
#   * L_edt is REFUSED on the all-zero entity-type map, not silently run;
#   * the protected source files are unmodified.
#
# OFFLINE
#   No network. The 1.2 GB pinned pickle is never loaded: the end-to-end tests use
#   the REAL approved policy and the REAL frozen Week-1 mapping outputs against a
#   SYNTHETIC miniature KG built in tmp_path, so the real 27-pair class walk, the
#   real fallback logic, the cache and the replay are all exercised in seconds.
#
# Run:
#     python -m pytest -vv tests/test_pipeline_graph_lrolesim.py
############################################################################

from __future__ import annotations

import hashlib
import json
import pickle
import subprocess
import sys
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from kg import graph_view as gv                     # noqa: E402
from lrolesim import adapter as ad                  # noqa: E402
from pipeline import candidate_order as co          # noqa: E402
from pipeline import graph_lrolesim_run as glr      # noqa: E402

FROZEN_DIR = REPO_ROOT / "outputs" / "journal2_week1_local_mapping_2026-07-30"

# SHA-256 of every file this task is forbidden to modify, recorded at the start of
# the task. A change to any of them fails here rather than in a later review.
PROTECTED_SOURCE_SHA256 = {
    "src/MCQ_lrolesim_ClaudeWeb_v2.py":
        "b7c3678ee531a291dee874053529ac498d8c7674b892cff19e817808671ddec0",
    "src/MCQ_lrolesim.py":
        "cdd4f90c006dc57d97ecccf79685efcd553e60be12dc86cfd66d205f5b6ff15b",
    "src/kg/graph_view.py":
        "0ed2733307ef8116b4ba79c906e8e880711e06f011418b0da3104e4c99716ec4",
    "src/kg/loader.py":
        "21a28be02ef2745271e01ebf0a3f10bba62949f32d6f4fc8a0d39d342600f565",
    "src/lrolesim/adapter.py":
        "2100fd112b144a4d71d2b0be0ef3465b3c73c9f8d5d8ad78b28a587185d65f33",
    "src/classes/policy.py":
        "8b90c6c345ac0f4380193f6e0ed6be584a79a41cd6434af53439d1d9f82738ef",
    "src/classes/member_mapper.py":
        "48aa0831cd7847ab24d6c282e9f879e0cafae31b130b630fb8c328abe71ca681",
    "src/classes/local_candidate_profile.py":
        "4e92506ef2bb7fddfa5366dcf6fd97794043d8de622f39fb7ca3472da8410684",
    # RETIRED BY PROMPT 8D — src/extract_221_and_select_distractors_ClaudeWeb_v2.py
    #   Prompt 8C was forbidden to touch the extract file, so it was pinned here at
    #   d09cb686e162b115b69b898dda95d260c5bc14e93ea52ffe3c71e6140513e983.
    #   Prompt 8D's mandate is to PATCH that exact file into a mode-dispatching
    #   compatibility entrypoint, so the pin no longer describes a rule that holds.
    #   It is removed rather than re-pinned at the new digest: re-pinning would
    #   assert "this file must never change again", which is not true of an
    #   orchestration wrapper, and would fail on every later legitimate edit for a
    #   reason unrelated to Prompt 8C's guarantees.
    #   The pre-Prompt-8D digest above remains the recorded baseline, and Prompt
    #   8D's own suite (tests/test_selection_lrolesim_handoff.py) pins the five
    #   sources that DO stay frozen: candidate_order, graph_lrolesim_run,
    #   graph_view, the LRoleSim adapter and the LRoleSim kernel.
}

ANSWER = "http://dbpedia.org/resource/Shinya_Yamanaka"
CLASS = "http://dbpedia.org/resource/Category:Japanese_Nobel_laureates"
OTHER_ANSWER = "http://dbpedia.org/resource/Eisaku_Satō"


def _cand(uri: str, index: int, origin: str = co.ORIGIN_EXACT) -> co.MappedCandidate:
    return co.MappedCandidate(canonical_uri=uri, local_index=index,
                              mapping_origin=origin)


def _uris(n: int) -> list[str]:
    return [f"http://dbpedia.org/resource/Cand_{i:03d}" for i in range(n)]


# ==========================================================================
# 1) THE DETERMINISTIC SEEDED GRAPH-ADMISSION ORDER
# ==========================================================================

class TestOrderingKey:
    def test_digest_matches_the_frozen_specification(self):
        """The key is exactly SHA256(domain NUL answer NUL class NUL candidate)."""
        candidate = "http://dbpedia.org/resource/Akira_Yoshino"
        expected = hashlib.sha256(
            "\x00".join((co.GRAPH_ADMISSION_ORDER_DOMAIN, ANSWER, CLASS,
                         candidate)).encode("utf-8")
        ).hexdigest()
        assert co.graph_admission_digest(ANSWER, CLASS, candidate) == expected

    def test_domain_is_versioned(self):
        assert co.GRAPH_ADMISSION_ORDER_DOMAIN == "journal2-m1-graph-order-v1"

    def test_it_is_not_called_a_ranking(self):
        name = co.GRAPH_ADMISSION_ORDER_NAME
        assert name == "deterministic seeded graph-admission order"
        assert "random" not in name.lower()
        assert "rank" not in name.lower()

    def test_a_nul_byte_in_any_field_is_refused(self):
        with pytest.raises(co.CandidateOrderInputError):
            co.graph_admission_digest(ANSWER, CLASS, "http://x\x00y")

    def test_changing_the_domain_changes_the_digest(self):
        a = co.graph_admission_digest(ANSWER, CLASS, "http://x")
        b = co.graph_admission_digest(ANSWER, CLASS, "http://x", domain="v2")
        assert a != b


class TestOrderingDeterminism:
    def test_same_inputs_give_the_same_order(self):
        cands = [_cand(u, i) for i, u in enumerate(_uris(40), start=100)]
        first = co.order_candidates_for_graph_admission(ANSWER, CLASS, cands)
        second = co.order_candidates_for_graph_admission(ANSWER, CLASS, cands)
        assert first.ordered_canonical_uris == second.ordered_canonical_uris

    def test_order_is_independent_of_input_sequence(self):
        """A reversed or shuffled input must not change the resulting order."""
        uris = _uris(40)
        forward = [_cand(u, i) for i, u in enumerate(uris, start=100)]
        backward = list(reversed(forward))
        a = co.order_candidates_for_graph_admission(ANSWER, CLASS, forward)
        b = co.order_candidates_for_graph_admission(ANSWER, CLASS, backward)
        assert a.ordered_canonical_uris == b.ordered_canonical_uris

    def test_order_is_independent_of_set_iteration_order(self):
        """Feeding the candidates out of a set must not change the order."""
        uris = _uris(40)
        listed = co.order_candidates_for_graph_admission(
            ANSWER, CLASS, [_cand(u, i) for i, u in enumerate(uris, start=100)])
        from_set = co.order_candidates_for_graph_admission(
            ANSWER, CLASS,
            [_cand(u, 100 + uris.index(u)) for u in set(uris)])
        assert listed.ordered_canonical_uris == from_set.ordered_canonical_uris

    def test_order_is_independent_of_local_node_index(self):
        """Renumbering every local index must leave the URI order untouched.

        Local indices are assigned by iterating a Python set in read_ttl, so an
        order that depended on them would depend on pickle construction.
        """
        uris = _uris(40)
        low = [_cand(u, i) for i, u in enumerate(uris, start=1)]
        high = [_cand(u, 9_000_000 - i) for i, u in enumerate(uris, start=1)]
        a = co.order_candidates_for_graph_admission(ANSWER, CLASS, low)
        b = co.order_candidates_for_graph_admission(ANSWER, CLASS, high)
        assert a.ordered_canonical_uris == b.ordered_canonical_uris

    def test_different_answers_obtain_different_orders(self):
        """The seed is per (Answer, class), so no candidate is globally favoured."""
        cands = [_cand(u, i) for i, u in enumerate(_uris(40), start=100)]
        a = co.order_candidates_for_graph_admission(ANSWER, CLASS, cands)
        b = co.order_candidates_for_graph_admission(OTHER_ANSWER, CLASS, cands)
        assert a.ordered_canonical_uris != b.ordered_canonical_uris

    def test_different_classes_obtain_different_orders(self):
        cands = [_cand(u, i) for i, u in enumerate(_uris(40), start=100)]
        a = co.order_candidates_for_graph_admission(ANSWER, CLASS, cands)
        b = co.order_candidates_for_graph_admission(
            ANSWER, "http://dbpedia.org/resource/Category:Other", cands)
        assert a.ordered_canonical_uris != b.ordered_canonical_uris

    def test_order_is_not_alphabetical(self):
        """A plain URI sort would bias admission by spelling under the cap."""
        uris = _uris(40)
        ordered = co.order_candidates_for_graph_admission(
            ANSWER, CLASS, [_cand(u, i) for i, u in enumerate(uris, start=100)])
        assert list(ordered.ordered_canonical_uris) != sorted(uris)

    def test_order_is_not_local_index_order(self):
        uris = _uris(40)
        cands = [_cand(u, i) for i, u in enumerate(uris, start=100)]
        ordered = co.order_candidates_for_graph_admission(ANSWER, CLASS, cands)
        assert list(ordered.ordered_local_indices) != sorted(
            c.local_index for c in cands)

    def test_sorted_by_digest_then_uri(self):
        cands = [_cand(u, i) for i, u in enumerate(_uris(40), start=100)]
        ordered = co.order_candidates_for_graph_admission(ANSWER, CLASS, cands)
        keys = [(c.order_digest, c.canonical_uri) for c in ordered.ordered]
        assert keys == sorted(keys)

    def test_admission_positions_are_one_based_and_dense(self):
        cands = [_cand(u, i) for i, u in enumerate(_uris(12), start=100)]
        ordered = co.order_candidates_for_graph_admission(ANSWER, CLASS, cands)
        assert [c.admission_position for c in ordered.ordered] == list(range(1, 13))

    def test_reproducible_across_processes_under_different_hash_seeds(self):
        """PYTHONHASHSEED must not reach the order. Checked in real subprocesses."""
        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "from pipeline import candidate_order as co\n"
            "uris=[f'http://dbpedia.org/resource/Cand_{i:03d}' for i in range(40)]\n"
            "cands=[co.MappedCandidate(canonical_uri=u, local_index=100+i,\n"
            "        mapping_origin='EXACT') for i,u in enumerate(uris)]\n"
            "o=co.order_candidates_for_graph_admission(%r, %r, set(cands))\n"
            "print('|'.join(o.ordered_canonical_uris))\n"
        ) % (str(SRC_DIR), ANSWER, CLASS)
        outputs = []
        for seed in ("0", "1", "12345"):
            proc = subprocess.run([sys.executable, "-c", script], check=True,
                                  capture_output=True, text=True,
                                  env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"})
            outputs.append(proc.stdout.strip())
        assert len(set(outputs)) == 1, "order changed with PYTHONHASHSEED"
        assert outputs[0].count("|") == 39


class TestOrderingInputContracts:
    def test_the_answer_may_not_be_its_own_candidate(self):
        with pytest.raises(co.CandidateOrderInputError):
            co.order_candidates_for_graph_admission(
                ANSWER, CLASS, [_cand(ANSWER, 1)])

    def test_bracketed_uri_is_refused(self):
        with pytest.raises(co.CandidateOrderInputError):
            _cand("<http://dbpedia.org/resource/X>", 1)

    def test_unknown_mapping_origin_is_refused(self):
        with pytest.raises(co.CandidateOrderInputError):
            _cand("http://dbpedia.org/resource/X", 1, origin="GUESSED")

    def test_duplicate_uri_is_dropped_and_reported(self):
        cands = [_cand("http://dbpedia.org/resource/X", 1),
                 _cand("http://dbpedia.org/resource/X", 1)]
        ordered = co.order_candidates_for_graph_admission(ANSWER, CLASS, cands)
        assert len(ordered.ordered) == 1
        assert [d.reason for d in ordered.dropped] == [co.DUPLICATE_CANONICAL_URI]

    def test_two_uris_on_one_local_node_is_dropped_and_reported(self):
        cands = [_cand("http://dbpedia.org/resource/X", 7),
                 _cand("http://dbpedia.org/resource/Y", 7)]
        ordered = co.order_candidates_for_graph_admission(ANSWER, CLASS, cands)
        assert len(ordered.ordered) == 1
        assert [d.reason for d in ordered.dropped] == [co.DUPLICATE_LOCAL_INDEX]


# ==========================================================================
# 2) SYNTHETIC MINIATURE KG
# ==========================================================================

class FakeKG:
    """The subset of kg.loader.LocalKG that the orchestration actually uses."""

    def __init__(self, index_url, out_neighbor, in_neighbor, index_type,
                 sha256="0" * 64):
        self.index_url = index_url
        self.url_index = {v: k for k, v in index_url.items()}
        self.out_neighbor = out_neighbor
        self.in_neighbor = in_neighbor
        self.index_type = index_type
        self.source_sha256 = sha256

    def uri_for_index(self, index):
        return self.index_url[index]


def build_star_kg(answer: int, candidates, neighbors_each: int = 2,
                  predicate: int = 1, sha256="0" * 64,
                  answer_uri: str = ANSWER) -> FakeKG:
    """A KG where every candidate owns `neighbors_each` PRIVATE context nodes.

    Private neighbours make the node cost of a candidate exact and predictable,
    which is what the cap tests need: admitting k candidates costs exactly
    k * (1 + neighbors_each) nodes beyond the Answer's base.

    `candidates` are MappedCandidate objects, and each node is registered under its
    OWN canonical URI. That matters: the orchestration checks the canonical
    candidate URI against the KG's index_url, so a fixture that invented a
    different spelling would be testing an inconsistent graph.
    """
    out_neighbor: dict[int, list[tuple[int, int]]] = {}
    in_neighbor: dict[int, list[tuple[int, int]]] = {}
    index_url = {answer: f"<{answer_uri}>"}
    next_context = 1_000_000

    def link(u: int, v: int) -> None:
        out_neighbor.setdefault(u, []).append((predicate, v))
        in_neighbor.setdefault(v, []).append((predicate, u))

    for candidate in candidates:
        index_url[candidate.local_index] = f"<{candidate.canonical_uri}>"
        link(answer, candidate.local_index)      # a shared edge with the Answer
        for _ in range(neighbors_each):
            context = next_context
            next_context += 1
            index_url[context] = f"<http://dbpedia.org/resource/Ctx_{context}>"
            link(candidate.local_index, context)
    index_type = {i: 0 for i in index_url}       # all zero, like the real pickle
    return FakeKG(index_url, out_neighbor, in_neighbor, index_type, sha256=sha256)


# ==========================================================================
# 3) THE MAPPING GATE IS NOT THE GRAPH GATE
# ==========================================================================

def _facts(slot, answer_uri, position, class_uri, answer_index, candidates,
           retrieval_complete=True, count=None):
    return glr.ClassMappingFacts(
        pilot_slot=slot,
        answer_uri=answer_uri,
        answer_local_index=answer_index,
        class_position=position,
        class_uri=class_uri,
        retrieval_complete=retrieval_complete,
        mapped_candidate_count_excluding_answer=(
            len(candidates) if count is None else count),
        accepted=tuple(candidates),
    )


class TestGraphStageGate:
    def test_mapping_gate_and_graph_gate_are_separate_thresholds(self):
        assert glr.GRAPH_STAGE_MAPPING_GATE == 10
        assert glr.GRAPH_GATE_MIN_CANDIDATES == 10
        assert glr.GRAPH_MAX_CANDIDATES == 50
        assert glr.GRAPH_MAX_NODES == 1200

    def test_nine_mapped_candidates_never_reaches_the_graph_builder(self):
        """Below the graph-stage gate the class is SKIPPED, not attempted."""
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(9))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands)
        kg = build_star_kg(50, cands)
        attempt, graph, order = glr.attempt_class_graph(facts, kg)
        assert attempt.attempted is False
        assert attempt.outcome == glr.ATTEMPT_SKIPPED_MAPPING_COUNT_BELOW_GATE
        assert attempt.graph_stage_eligible is False
        assert graph is None and order is None

    def test_incomplete_retrieval_is_a_distinct_skip_reason(self):
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(30))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands,
                       retrieval_complete=False)
        kg = build_star_kg(50, cands)
        attempt, graph, _ = glr.attempt_class_graph(facts, kg)
        assert attempt.outcome == glr.ATTEMPT_SKIPPED_RETRIEVAL_INCOMPLETE
        assert graph is None

    def test_passing_the_mapping_gate_can_still_fail_the_graph_gate(self):
        """The whole point: 30 mapped candidates, but only huge neighbourhoods.

        Every candidate needs 200 private context nodes, so the 1200-node budget
        admits at most five and the class is graph-infeasible despite comfortably
        passing the mapping gate.
        """
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(30))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands)
        kg = build_star_kg(50, cands, neighbors_each=200)
        attempt, graph, order = glr.attempt_class_graph(facts, kg)
        assert attempt.graph_stage_eligible is True       # mapping gate passed
        assert attempt.attempted is True
        assert attempt.outcome == glr.ATTEMPT_GRAPH_BUDGET_INSUFFICIENT
        assert attempt.accepted_candidate_count < glr.GRAPH_GATE_MIN_CANDIDATES
        assert graph is not None and graph.graph is None  # nothing rankable
        assert order is not None and len(order) == 30

    def test_a_feasible_class_reports_graph_feasible(self):
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(30))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands)
        kg = build_star_kg(50, cands, neighbors_each=2)
        attempt, graph, _ = glr.attempt_class_graph(facts, kg)
        assert attempt.outcome == glr.ATTEMPT_GRAPH_FEASIBLE
        assert attempt.accepted_candidate_count == 30
        assert graph is not None and graph.graph is not None


# ==========================================================================
# 4) BUDGET CONTRACTS ON REAL BUILDER OUTPUT
# ==========================================================================

class TestBudgetContracts:
    def test_candidate_cap_is_fifty(self):
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(80))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands)
        kg = build_star_kg(50, cands, neighbors_each=1)
        attempt, graph, _ = glr.attempt_class_graph(facts, kg)
        assert attempt.accepted_candidate_count == 50
        assert attempt.candidate_cap_reached is True
        assert graph.budget.accepted_count == 50

    def test_node_cap_is_never_exceeded(self):
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(60))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands)
        kg = build_star_kg(50, cands, neighbors_each=40)
        attempt, graph, _ = glr.attempt_class_graph(facts, kg)
        assert graph.graph is not None
        assert graph.graph.node_count <= glr.GRAPH_MAX_NODES
        assert attempt.node_budget_bound is True

    def test_every_accepted_candidate_has_coverage_exactly_one(self):
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(60))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands)
        kg = build_star_kg(50, cands, neighbors_each=40)
        _, graph, _ = glr.attempt_class_graph(facts, kg)
        accepted = [r for r in graph.budget.candidate_records if r.accepted]
        assert accepted
        assert all(r.neighborhood_coverage_ratio == 1.0 for r in accepted)
        # And the builder's own assertion agrees.
        gv.assert_full_neighborhood_coverage(graph.budget)

    def test_candidates_are_offered_in_admission_order(self):
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(20))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands)
        kg = build_star_kg(50, cands, neighbors_each=2)
        _, graph, order = glr.attempt_class_graph(facts, kg)
        offered = [r.candidate for r in graph.budget.candidate_records]
        assert offered == list(order.ordered_local_indices)


# ==========================================================================
# 5) APPROVED-CLASS ORDER AND GRAPH-STAGE FALLBACK
# ==========================================================================

class FakePolicyRow:
    """A minimal stand-in for classes.policy.AnswerClassPolicy."""

    def __init__(self, slot, answer_uri, classes, label="Label"):
        self.pilot_slot = slot
        self.answer_uri = answer_uri
        self.display_label = label
        self.preferred_class, self.fallback_class_1, self.fallback_class_2 = classes

    @property
    def ordered_classes(self):
        return (self.preferred_class, self.fallback_class_1, self.fallback_class_2)

    @property
    def ordered_positions(self):
        return tuple(zip(("preferred", "fallback_1", "fallback_2"),
                         self.ordered_classes))


def _fallback_fixture(sizes, neighbors):
    """Build (row, inputs, kg) for one Answer with three controllable classes."""
    classes = [f"http://dbpedia.org/resource/Category:C{i}" for i in (1, 2, 3)]
    row = FakePolicyRow(1, ANSWER, classes)
    facts = {}
    all_candidates = []
    base = 100
    for position, class_uri, size in zip(
            ("preferred", "fallback_1", "fallback_2"), classes, sizes):
        cands = [_cand(f"http://dbpedia.org/resource/{position}_{i:03d}", base + i)
                 for i in range(size)]
        base += 1000
        all_candidates.extend((c, neighbors[position]) for c in cands)
        facts[(1, class_uri)] = _facts(1, ANSWER, position, class_uri, 50, cands)

    out_neighbor: dict[int, list[tuple[int, int]]] = {}
    in_neighbor: dict[int, list[tuple[int, int]]] = {}
    index_url = {50: f"<{ANSWER}>"}
    ctx = 1_000_000

    def link(u, v):
        out_neighbor.setdefault(u, []).append((1, v))
        in_neighbor.setdefault(v, []).append((1, u))

    for candidate, count in all_candidates:
        index_url[candidate.local_index] = f"<{candidate.canonical_uri}>"
        link(50, candidate.local_index)
        for _ in range(count):
            index_url[ctx] = f"<http://dbpedia.org/resource/Ctx_{ctx}>"
            link(candidate.local_index, ctx)
            ctx += 1
    kg = FakeKG(index_url, out_neighbor, in_neighbor, {i: 0 for i in index_url})

    inputs = glr.FrozenMappingInputs(
        facts=facts,
        mapping_stage_status={1: "MAPPING_SELECTED_PREFERRED"},
        selected_mapping_class={1: classes[0]},
        answer_local_index={1: 50},
        source_hashes={},
    )
    return row, inputs, kg, classes


class TestGraphStageFallback:
    def test_preferred_class_wins_when_it_is_feasible(self):
        row, inputs, kg, classes = _fallback_fixture(
            (30, 30, 30), {"preferred": 2, "fallback_1": 2, "fallback_2": 2})
        result = glr.select_graph_feasible_class(row, inputs, kg)
        assert result.graph_stage_status == glr.GRAPH_SELECTED_PREFERRED
        assert result.selected_class_uri == classes[0]

    def test_falls_back_to_position_one_when_preferred_fails_the_graph_gate(self):
        row, inputs, kg, classes = _fallback_fixture(
            (30, 30, 30), {"preferred": 300, "fallback_1": 2, "fallback_2": 2})
        result = glr.select_graph_feasible_class(row, inputs, kg)
        assert result.graph_stage_status == glr.GRAPH_SELECTED_FALLBACK_1
        assert result.selected_class_uri == classes[1]

    def test_falls_back_to_position_two_when_both_earlier_classes_fail(self):
        row, inputs, kg, classes = _fallback_fixture(
            (30, 30, 30), {"preferred": 300, "fallback_1": 300, "fallback_2": 2})
        result = glr.select_graph_feasible_class(row, inputs, kg)
        assert result.graph_stage_status == glr.GRAPH_SELECTED_FALLBACK_2
        assert result.selected_class_uri == classes[2]

    def test_no_graph_feasible_approved_class_when_all_three_fail(self):
        row, inputs, kg, _ = _fallback_fixture(
            (30, 30, 30), {"preferred": 300, "fallback_1": 300, "fallback_2": 300})
        result = glr.select_graph_feasible_class(row, inputs, kg)
        assert result.graph_stage_status == glr.NO_GRAPH_FEASIBLE_APPROVED_CLASS
        assert result.selected_class_uri is None
        assert result.m1_graph is None

    def test_classes_are_walked_in_approved_order(self):
        row, inputs, kg, classes = _fallback_fixture(
            (30, 30, 30), {"preferred": 300, "fallback_1": 300, "fallback_2": 300})
        result = glr.select_graph_feasible_class(row, inputs, kg)
        assert [a.class_position for a in result.attempts] == [
            "preferred", "fallback_1", "fallback_2"]
        assert [a.class_uri for a in result.attempts] == classes

    def test_every_approved_class_appears_even_after_the_walk_stops(self):
        """A class after the selected one is recorded as NOT ATTEMPTED, not omitted."""
        row, inputs, kg, _ = _fallback_fixture(
            (30, 30, 30), {"preferred": 2, "fallback_1": 2, "fallback_2": 2})
        result = glr.select_graph_feasible_class(row, inputs, kg)
        assert len(result.attempts) == 3
        assert result.attempts[0].outcome == glr.ATTEMPT_GRAPH_FEASIBLE
        for later in result.attempts[1:]:
            assert later.outcome == glr.ATTEMPT_NOT_ATTEMPTED_EARLIER_CLASS_SELECTED
            assert later.attempted is False

    def test_an_unreached_but_eligible_class_still_reports_eligible(self):
        """"not reached" must not be reported as "not eligible".

        All three classes here pass the mapping gate; the walk stops at the
        preferred one. The two later classes were never built, but they WERE
        graph-stage eligible, and graph_policy_summary.csv counts that column.
        """
        row, inputs, kg, _ = _fallback_fixture(
            (30, 30, 30), {"preferred": 2, "fallback_1": 2, "fallback_2": 2})
        result = glr.select_graph_feasible_class(row, inputs, kg)
        assert [a.graph_stage_eligible for a in result.attempts] == [True, True, True]
        assert [a.attempted for a in result.attempts] == [True, False, False]

    def test_an_unreached_and_ineligible_class_reports_ineligible(self):
        """A later class below the mapping gate is still reported ineligible."""
        row, inputs, kg, _ = _fallback_fixture(
            (30, 5, 30), {"preferred": 2, "fallback_1": 2, "fallback_2": 2})
        result = glr.select_graph_feasible_class(row, inputs, kg)
        assert [a.graph_stage_eligible for a in result.attempts] == [True, False, True]

    def test_a_class_the_policy_never_approved_is_never_consulted(self):
        row, inputs, kg, classes = _fallback_fixture(
            (30, 30, 30), {"preferred": 300, "fallback_1": 300, "fallback_2": 300})
        result = glr.select_graph_feasible_class(row, inputs, kg)
        assert {a.class_uri for a in result.attempts} == set(classes)


# ==========================================================================
# 6) LROLESIM: L_ed, BETA 0.2, EXACTLY THREE ITERATIONS
# ==========================================================================

class TestLRoleSimConfiguration:
    def test_pilot_config_is_l_ed_beta_0_2_and_three_iterations(self):
        config = ad.pilot_config()
        assert config.measure == "lrolesim_ed"
        assert config.lrolesim_beta == 0.2
        assert config.iterations == 3
        assert config.as_record()["iteration_mode"] == "fixed"

    def test_ranking_runs_exactly_three_iterations_observed(self, monkeypatch,
                                                            tmp_path):
        """The count is COUNTED by the kernel callback, not copied from config."""
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(12))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands)
        kg = build_star_kg(50, cands, neighbors_each=2)
        result = _single_class_result(facts, kg)

        seen = []
        real = ad.run_lrolesim_fixed

        def spy(*args, **kwargs):
            run = real(*args, **kwargs)
            seen.append(run.iterations_run)
            return run

        monkeypatch.setattr(ad, "run_lrolesim_fixed", spy)
        cache = glr.ScoreCache(tmp_path / "cache.jsonl")
        scored, _, prov = glr.rank_graph(
            result, kg, cache, glr.SourceHashes.collect())
        assert seen == [3]
        assert prov["iterations_run"] == 3
        assert len(scored) == 12

    def test_the_convergence_api_is_never_called(self, monkeypatch, tmp_path):
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(12))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands)
        kg = build_star_kg(50, cands, neighbors_each=2)
        result = _single_class_result(facts, kg)

        def forbidden(*args, **kwargs):
            raise AssertionError("the pilot must not use the convergence path")

        monkeypatch.setattr(ad, "run_lrolesim_until_convergence", forbidden)
        cache = glr.ScoreCache(tmp_path / "cache.jsonl")
        glr.rank_graph(result, kg, cache, glr.SourceHashes.collect())

    def test_beta_kwarg_is_still_refused_by_the_adapter(self):
        with pytest.raises(ad.LRoleSimConfigError):
            ad.rank_candidates(1, [2], [1, 2], {}, {}, beta=0.2)


def _single_class_result(facts, kg, min_candidates=None) -> glr.GraphStageResult:
    """Build a GraphStageResult for one class, bypassing the policy walk."""
    kwargs = {} if min_candidates is None else {"min_candidates": min_candidates}
    attempt, graph, order = glr.attempt_class_graph(facts, kg, **kwargs)
    assert graph is not None and graph.graph is not None
    return glr.GraphStageResult(
        pilot_slot=facts.pilot_slot,
        answer_uri=facts.answer_uri,
        display_label="Label",
        answer_local_index=facts.answer_local_index,
        mapping_stage_status="MAPPING_SELECTED_PREFERRED",
        graph_stage_status=glr.GRAPH_SELECTED_PREFERRED,
        selected_class_position=facts.class_position,
        selected_class_uri=facts.class_uri,
        attempts=(attempt,),
        m1_graph=graph,
        order=order,
    )


class TestRankingContracts:
    def _ranked(self, tmp_path, neighbors_each=2, n=12):
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(n))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands)
        kg = build_star_kg(50, cands,
                           neighbors_each=neighbors_each)
        result = _single_class_result(facts, kg)
        cache = glr.ScoreCache(tmp_path / "cache.jsonl")
        scored, fp, _ = glr.rank_graph(result, kg, cache,
                                       glr.SourceHashes.collect())
        return result, scored, fp

    def test_only_accepted_candidates_are_ranked(self, tmp_path):
        result, scored, _ = self._ranked(tmp_path)
        assert {s.local_index for s in scored} == set(
            result.m1_graph.accepted_candidates)

    def test_context_nodes_never_appear_in_the_ranking(self, tmp_path):
        """Graph nodes that are not approved candidates stay context-only."""
        result, scored, _ = self._ranked(tmp_path)
        graph_nodes = set(result.m1_graph.graph.nodes)
        candidates = set(result.m1_graph.accepted_candidates)
        context = graph_nodes - candidates - {result.answer_local_index}
        assert context, "fixture must actually contain context nodes"
        assert not (context & {s.local_index for s in scored})

    def test_the_answer_is_never_ranked_against_itself(self, tmp_path):
        result, scored, _ = self._ranked(tmp_path)
        assert result.answer_local_index not in {s.local_index for s in scored}

    def test_ranks_are_dense_and_one_based(self, tmp_path):
        _, scored, _ = self._ranked(tmp_path)
        assert [s.rank for s in scored] == list(range(1, len(scored) + 1))

    def test_sorted_by_descending_score_then_ascending_uri(self, tmp_path):
        _, scored, _ = self._ranked(tmp_path)
        keys = [(-s.score, s.canonical_uri) for s in scored]
        assert keys == sorted(keys)

    def test_ties_break_on_uri_not_on_local_index(self, tmp_path):
        """In this fixture every candidate is structurally identical, so the whole
        ranking is one tie group and the URI order alone decides it."""
        _, scored, _ = self._ranked(tmp_path)
        tied = [s for s in scored if s.tie_group_id == scored[0].tie_group_id]
        assert len(tied) > 1, "fixture must produce a tie"
        assert [s.canonical_uri for s in tied] == sorted(
            s.canonical_uri for s in tied)

    def test_tie_groups_are_recorded_with_their_size(self, tmp_path):
        _, scored, _ = self._ranked(tmp_path)
        by_score = {}
        for s in scored:
            by_score.setdefault(s.score, []).append(s)
        for group in by_score.values():
            assert len({s.tie_group_id for s in group}) == 1
            assert all(s.tie_group_size == len(group) for s in group)

    def test_assign_tie_groups_handles_mixed_scores(self):
        scored = [(0.9, "a"), (0.9, "b"), (0.5, "c"), (0.2, "d"), (0.2, "e")]
        assert glr.assign_tie_groups(scored) == [
            (1, 2), (1, 2), (2, 1), (3, 2), (3, 2)]

    def test_assign_tie_groups_on_empty_input(self):
        assert glr.assign_tie_groups([]) == []

    def test_beta_floor_is_flagged(self, tmp_path):
        _, scored, _ = self._ranked(tmp_path)
        for s in scored:
            assert s.at_beta_floor == (s.score == 0.2)

    def test_candidate_origin_is_carried_through(self, tmp_path):
        _, scored, _ = self._ranked(tmp_path)
        assert all(s.mapping_origin in ("EXACT", "REDIRECT") for s in scored)


class TestCanonicalUriContract:
    """The canonical candidate URI must BE the local node's URI in the pinned KG."""

    def test_a_consistent_fixture_passes(self, tmp_path):
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(12))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands)
        kg = build_star_kg(50, cands, neighbors_each=2)
        result = _single_class_result(facts, kg)
        scored, _, _ = glr.rank_graph(result, kg, glr.ScoreCache(
            tmp_path / "c.jsonl"), glr.SourceHashes.collect())
        assert len(scored) == 12

    def test_a_mislabelled_node_is_refused(self, tmp_path):
        """A redirect recorded against the wrong target must not be scored silently."""
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(12))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands)
        kg = build_star_kg(50, cands, neighbors_each=2)
        # Rename one candidate node in the KG so its URI no longer matches.
        kg.index_url[cands[0].local_index] = "<http://dbpedia.org/resource/Wrong>"
        result = _single_class_result(facts, kg)
        with pytest.raises(glr.PipelineError, match="canonical candidate URI"):
            glr.rank_graph(result, kg, glr.ScoreCache(tmp_path / "c.jsonl"),
                           glr.SourceHashes.collect())

    def test_bare_uri_strips_the_pickle_bracket_spelling(self):
        assert glr._bare_uri("<http://x/y>") == "http://x/y"
        assert glr._bare_uri("http://x/y") == "http://x/y"


# ==========================================================================
# 7) L_edt REFUSAL
# ==========================================================================

class TestEntityTypeRefusal:
    def test_all_zero_type_map_is_reported_unusable(self):
        verdict = glr.inspect_entity_type_map({i: 0 for i in range(100)})
        assert verdict.usable is False
        assert verdict.status == glr.L_EDT_DEFERRED
        assert verdict.nonzero_count == 0

    def test_all_zero_type_map_raises_on_assert(self):
        with pytest.raises(glr.EntityTypeMapUnusableError) as exc:
            glr.assert_entity_type_map_usable({i: 0 for i in range(100)})
        assert glr.L_EDT_DEFERRED in str(exc.value)

    def test_a_populated_type_map_is_accepted(self):
        verdict = glr.assert_entity_type_map_usable({1: 0, 2: 3, 3: 7})
        assert verdict.usable is True
        assert verdict.status == "L_EDT_ELIGIBLE"
        assert verdict.nonzero_count == 2

    def test_the_deferral_token_is_the_required_string(self):
        assert glr.L_EDT_DEFERRED == "L_EDT_DEFERRED_NO_VALID_ENTITY_TYPE_MAP"

    def test_the_adapter_alone_would_not_catch_an_all_zero_map(self):
        """Why the guard above has to exist.

        The adapter refuses an EMPTY index_type; an all-zero map is non-empty, so
        it passes the adapter's check and would silently reproduce L_ed. This test
        documents that gap rather than changing the protected adapter.
        """
        all_zero = {i: 0 for i in range(5)}
        assert bool(all_zero) is True
        config = ad.ablation_config()
        assert config.requires_entity_types is True
        with pytest.raises(ad.LRoleSimConfigError):
            ad.run_lrolesim_fixed([1, 2], {}, {}, config=config, index_type={})
        # And with the all-zero map it does NOT raise — hence glr's guard.
        glr.inspect_entity_type_map(all_zero)


# ==========================================================================
# 8) FINGERPRINTS AND CACHE INVALIDATION
# ==========================================================================

def _fingerprint(**overrides):
    base = dict(
        local_kg_sha256="a" * 64,
        answer_uri=ANSWER,
        class_uri=CLASS,
        ordered_accepted_candidate_uris=["http://x/1", "http://x/2"],
        retained_node_uris=["http://x/1", "http://x/2", "http://x/ctx"],
        max_candidates=50,
        max_nodes=1200,
        measure="lrolesim_ed",
        lrolesim_beta=0.2,
        iterations=3,
        source_hashes=glr.SourceHashes(hashes={
            "graph_builder": "b" * 64,
            "lrolesim_adapter": "c" * 64,
            "lrolesim_kernel": "d" * 64,
            "candidate_order": "e" * 64,
        }),
    )
    base.update(overrides)
    return glr.build_run_fingerprint(**base)


class TestFingerprint:
    def test_identical_inputs_give_the_same_fingerprint(self):
        assert _fingerprint().run_fingerprint == _fingerprint().run_fingerprint

    @pytest.mark.parametrize("field,value", [
        ("local_kg_sha256", "f" * 64),
        ("answer_uri", "http://dbpedia.org/resource/Other"),
        ("class_uri", "http://dbpedia.org/resource/Category:Other"),
        ("ordered_accepted_candidate_uris", ["http://x/2", "http://x/1"]),
        ("retained_node_uris", ["http://x/1"]),
        ("max_candidates", 40),
        ("max_nodes", 900),
        ("measure", "lrolesim_edt"),
        ("lrolesim_beta", 0.3),
        ("iterations", 4),
    ])
    def test_every_field_changes_the_fingerprint(self, field, value):
        assert _fingerprint().run_fingerprint != _fingerprint(**{field: value}).run_fingerprint

    @pytest.mark.parametrize("source", [
        "graph_builder", "lrolesim_adapter", "lrolesim_kernel", "candidate_order"])
    def test_every_source_hash_changes_the_fingerprint(self, source):
        hashes = dict(_fingerprint().payload["run"])  # not used directly
        changed = {
            "graph_builder": "b" * 64, "lrolesim_adapter": "c" * 64,
            "lrolesim_kernel": "d" * 64, "candidate_order": "e" * 64,
        }
        changed[source] = "9" * 64
        other = _fingerprint(source_hashes=glr.SourceHashes(hashes=changed))
        assert _fingerprint().run_fingerprint != other.run_fingerprint
        assert hashes  # the baseline payload really has run fields

    def test_candidate_order_changes_the_graph_fingerprint_too(self):
        a = _fingerprint()
        b = _fingerprint(ordered_accepted_candidate_uris=["http://x/2", "http://x/1"])
        assert a.graph_fingerprint != b.graph_fingerprint

    def test_ranker_config_does_not_change_the_graph_fingerprint(self):
        """The graph is the same graph whatever measure is run over it."""
        a = _fingerprint()
        b = _fingerprint(iterations=4)
        assert a.graph_fingerprint == b.graph_fingerprint
        assert a.run_fingerprint != b.run_fingerprint

    def test_fingerprint_records_every_required_field(self):
        payload = _fingerprint().payload
        graph, run = payload["graph"], payload["run"]
        for key in ("local_kg_sha256", "answer_uri", "class_uri",
                    "ordered_accepted_candidate_uris", "retained_node_uris_sha256",
                    "retained_node_count", "max_candidates", "max_nodes",
                    "graph_builder_sha256", "candidate_order_sha256"):
            assert key in graph, key
        for key in ("measure", "lrolesim_beta", "iterations",
                    "lrolesim_adapter_sha256", "lrolesim_kernel_sha256"):
            assert key in run, key


class TestScoreCache:
    def test_put_then_get_is_a_hit(self, tmp_path):
        cache = glr.ScoreCache(tmp_path / "c.jsonl")
        fp = _fingerprint()
        cache.put(fp, [("http://x/1", 0.5)], iterations_run=3, node_count=3)
        assert cache.get(fp) is not None
        assert cache.hits == 1

    def test_cache_survives_a_reload(self, tmp_path):
        path = tmp_path / "c.jsonl"
        fp = _fingerprint()
        glr.ScoreCache(path).put(fp, [("http://x/1", 0.5)], 3, 3)
        reloaded = glr.ScoreCache(path).load()
        assert reloaded.get(fp) is not None

    def test_any_fingerprint_change_invalidates_the_entry(self, tmp_path):
        path = tmp_path / "c.jsonl"
        glr.ScoreCache(path).put(_fingerprint(), [("http://x/1", 0.5)], 3, 3)
        reloaded = glr.ScoreCache(path).load()
        assert reloaded.get(_fingerprint(iterations=4)) is None
        assert reloaded.misses == 1

    def test_a_hand_edited_field_block_is_a_miss(self, tmp_path):
        """The key is the digest of the fields, so tampering must not go unnoticed."""
        path = tmp_path / "c.jsonl"
        fp = _fingerprint()
        glr.ScoreCache(path).put(fp, [("http://x/1", 0.5)], 3, 3)
        record = json.loads(path.read_text().strip())
        record["fields"]["run"]["iterations"] = 99
        path.write_text(glr._canonical_json(record) + "\n")
        assert glr.ScoreCache(path).load().get(fp) is None

    def test_an_unknown_schema_version_is_skipped(self, tmp_path):
        path = tmp_path / "c.jsonl"
        fp = _fingerprint()
        glr.ScoreCache(path).put(fp, [("http://x/1", 0.5)], 3, 3)
        record = json.loads(path.read_text().strip())
        record["cache_schema_version"] = "something-else"
        path.write_text(glr._canonical_json(record) + "\n")
        assert glr.ScoreCache(path).load().entries == {}

    def test_a_corrupt_line_fails_loudly(self, tmp_path):
        path = tmp_path / "c.jsonl"
        path.write_text("{not json\n")
        with pytest.raises(glr.PipelineError):
            glr.ScoreCache(path).load()

    def test_a_cache_hit_avoids_recomputation(self, tmp_path, monkeypatch):
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(12))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands)
        kg = build_star_kg(50, cands, neighbors_each=2)
        result = _single_class_result(facts, kg)
        hashes = glr.SourceHashes.collect()

        cache = glr.ScoreCache(tmp_path / "c.jsonl")
        first, _, prov1 = glr.rank_graph(result, kg, cache, hashes)
        assert prov1["score_source"] == "computed"

        def forbidden(*args, **kwargs):
            raise AssertionError("a cache hit must not recompute LRoleSim")

        monkeypatch.setattr(ad, "rank_m1_graph", forbidden)
        reloaded = glr.ScoreCache(tmp_path / "c.jsonl").load()
        second, _, prov2 = glr.rank_graph(result, kg, reloaded, hashes)
        assert prov2["score_source"] == "cache"
        assert [(s.rank, s.canonical_uri, s.score) for s in first] == \
               [(s.rank, s.canonical_uri, s.score) for s in second]

    def test_replay_mode_refuses_to_compute_on_a_cache_miss(self, tmp_path):
        cands = [_cand(u, 100 + i) for i, u in enumerate(_uris(12))]
        facts = _facts(1, ANSWER, "preferred", CLASS, 50, cands)
        kg = build_star_kg(50, cands, neighbors_each=2)
        result = _single_class_result(facts, kg)
        cache = glr.ScoreCache(tmp_path / "empty.jsonl")
        with pytest.raises(glr.CacheMissInReplayError):
            glr.rank_graph(result, kg, cache, glr.SourceHashes.collect(),
                           mode=glr.MODE_REPLAY)


# ==========================================================================
# 9) OFFLINE GUARD
# ==========================================================================

class TestOfflineGuard:
    def test_a_connection_attempt_is_blocked_and_counted(self):
        import socket as socket_module
        guard = glr.OfflineGuard()
        guard.install()
        try:
            with pytest.raises(glr.OfflineGuardTripped):
                socket_module.create_connection(("dbpedia.org", 80))
        finally:
            guard.uninstall()
        assert guard.as_record()["network_attempts"] == 1

    def test_uninstall_restores_the_real_socket_api(self):
        import socket as socket_module
        original = socket_module.socket.connect
        guard = glr.OfflineGuard()
        guard.install()
        assert socket_module.socket.connect is not original
        guard.uninstall()
        assert socket_module.socket.connect is original

    def test_a_clean_run_reports_zero_calls(self):
        guard = glr.OfflineGuard()
        guard.install()
        guard.uninstall()
        record = guard.as_record()
        assert record["network_attempts"] == 0
        assert record["http_calls"] == 0
        assert record["sparql_calls"] == 0


# ==========================================================================
# 10) FROZEN WEEK-1 MAPPING INPUTS
# ==========================================================================

@pytest.fixture(scope="module")
def inputs():
    """The real frozen Week-1 mapping outputs, read once for the module."""
    return glr.load_frozen_mapping_inputs(FROZEN_DIR)


class TestFrozenMappingInputs:
    def test_all_twenty_seven_answer_class_pairs_are_present(self, inputs):
        assert len(inputs.facts) == 27
        assert len({slot for slot, _ in inputs.facts}) == 9

    def test_canonical_uri_of_a_redirect_is_the_redirect_target(self):
        record = {
            "mapping_origin": "REDIRECT",
            "normalized_member_uri": "http://dbpedia.org/resource/Nihon_Hidankyo",
            "redirect_target_uri": "http://dbpedia.org/resource/Japan_Confederation",
        }
        assert glr.canonical_candidate_uri(record) == \
            "http://dbpedia.org/resource/Japan_Confederation"

    def test_canonical_uri_of_an_exact_match_is_the_member_uri(self):
        record = {"mapping_origin": "EXACT",
                  "normalized_member_uri": "http://dbpedia.org/resource/X",
                  "redirect_target_uri": None}
        assert glr.canonical_candidate_uri(record) == "http://dbpedia.org/resource/X"

    def test_an_unresolved_record_has_no_canonical_uri(self):
        with pytest.raises(glr.MappingInputError):
            glr.canonical_candidate_uri({"mapping_origin": "UNRESOLVED"})

    def test_sulfuric_acid_mapping_failure_is_carried_forward_unchanged(self, inputs):
        assert inputs.mapping_stage_status[6] == \
            glr.NO_MAPPING_FEASIBLE_APPROVED_CLASS
        assert inputs.selected_mapping_class[6] is None

    def test_the_diagnostic_class_has_exactly_six_mapped_candidates(self, inputs):
        facts = inputs.for_pair(6, glr.DIAGNOSTIC_CLASS_URI)
        assert facts.mapped_candidate_count_excluding_answer == 6
        assert len(facts.accepted) == 6
        assert facts.passes_graph_stage_mapping_gate is False

    def test_carbon_preferred_class_fails_the_mapping_gate(self, inputs):
        """Nine mapped candidates: the Week-1 fallback reason, re-checked here."""
        facts = inputs.for_pair(4, "http://dbpedia.org/resource/Category:Reactive_nonmetals")
        assert facts.mapped_candidate_count_excluding_answer == 9
        assert facts.passes_graph_stage_mapping_gate is False

    def test_the_frozen_zip_hash_is_pinned(self):
        record = glr.verify_frozen_mapping_zip()
        assert record["sha256"] == glr.FROZEN_MAPPING_ZIP_SHA256

    def test_a_wrong_expected_zip_hash_fails(self):
        with pytest.raises(glr.FrozenInputError):
            glr.verify_frozen_mapping_zip(expected_sha256="0" * 64)


# ==========================================================================
# 11) END TO END: REAL POLICY + REAL MAPPINGS + SYNTHETIC MINIATURE KG
# ==========================================================================

def _build_synthetic_pinned_kg(tmp_path, neighbors_each=2, big_slots=()):
    """A read_ttl-schema pickle covering exactly the nodes the real mappings use.

    Real policy, real 27-pair mapping records, tiny KG: the whole orchestration is
    exercised without loading the 1.2 GB pinned pickle. `big_slots` inflates the
    neighbourhood of a given (slot, class_position) so a graph-gate failure and the
    fallback walk can be forced deliberately.
    """
    inputs = glr.load_frozen_mapping_inputs(FROZEN_DIR)
    url_index: dict[str, int] = {}
    index_url: dict[int, str] = {}
    out_neighbor: dict[int, list[tuple[int, int]]] = {}
    in_neighbor: dict[int, list[tuple[int, int]]] = {}

    def register(index: int, uri: str) -> None:
        index_url[index] = uri
        url_index[uri] = index

    def link(u: int, v: int) -> None:
        out_neighbor.setdefault(u, []).append((7, v))
        in_neighbor.setdefault(v, []).append((7, u))

    # An Answer node is often ALSO a candidate of another Answer's class (Eisaku
    # Satō is a Japanese Nobel laureate offered to Shinya Yamanaka). A node has one
    # URI, so the Answer must be registered under its real URI, not a synthetic one.
    answer_uri_for_slot = {facts.pilot_slot: facts.answer_uri
                           for facts in inputs.facts.values()}
    for slot, answer_index in inputs.answer_local_index.items():
        register(answer_index, f"<{answer_uri_for_slot[slot]}>")
    context = 8_000_000
    for (slot, class_uri), facts in sorted(inputs.facts.items()):
        count = (400 if (slot, facts.class_position) in big_slots
                 else neighbors_each)
        for candidate in facts.accepted:
            if candidate.local_index not in index_url:
                register(candidate.local_index, f"<{candidate.canonical_uri}>")
            link(facts.answer_local_index, candidate.local_index)
            for _ in range(count):
                register(context, f"<http://dbpedia.org/resource/Ctx_{context}>")
                link(candidate.local_index, context)
                context += 1
    register(7, "<http://dbpedia.org/property/synthetic>")   # the predicate URI

    path = tmp_path / "synthetic.pickle_EnglishVersion_EntityType"
    index_type = {i: 0 for i in index_url}
    with open(path, "wb") as f:
        pickle.dump((url_index, index_url, out_neighbor, in_neighbor, index_type), f)
    return path


@pytest.fixture(scope="module")
def end_to_end(tmp_path_factory):
    """One synthetic-KG orchestration, reused by the tests below."""
    tmp_path = tmp_path_factory.mktemp("e2e")
    kg_path = _build_synthetic_pinned_kg(tmp_path)
    run = glr.run_pilot(
        mode=glr.MODE_RUN,
        local_kg_path=kg_path,
        local_kg_sha256=None,
        cache_path=tmp_path / "cache.jsonl",
        verbose=False,
    )
    inputs = glr.load_frozen_mapping_inputs(FROZEN_DIR)
    out_dir = glr.write_all_outputs(
        run, tmp_path / "out", selected_mapping=inputs.selected_mapping_class)
    return {"run": run, "out_dir": out_dir, "tmp_path": tmp_path,
            "kg_path": kg_path, "inputs": inputs}


class TestEndToEnd:
    def test_the_run_makes_zero_network_calls(self, end_to_end):
        record = end_to_end["run"].guard_record
        assert record["network_attempts"] == 0
        assert record["http_calls"] == 0
        assert record["sparql_calls"] == 0

    def test_graph_policy_summary_has_exactly_nine_primary_rows(self, end_to_end):
        import csv as csv_module
        path = end_to_end["out_dir"] / "graph_policy_summary.csv"
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv_module.DictReader(f))
        assert len(rows) == 9
        assert [int(r["pilot_slot"]) for r in rows] == list(range(1, 10))
        assert {r["primary_or_diagnostic"] for r in rows} == {"primary"}

    def test_eight_mapping_feasible_answers_reach_the_graph_stage(self, end_to_end):
        run = end_to_end["run"]
        feasible = [r for r in run.primary if r.is_graph_feasible]
        assert len(feasible) == 8
        assert {r.pilot_slot for r in feasible} == {1, 2, 3, 4, 5, 7, 8, 9}

    def test_sulfuric_acid_has_no_graph_feasible_approved_class(self, end_to_end):
        slot6 = next(r for r in end_to_end["run"].primary if r.pilot_slot == 6)
        assert slot6.graph_stage_status == glr.NO_GRAPH_FEASIBLE_APPROVED_CLASS
        assert slot6.mapping_stage_status == glr.NO_MAPPING_FEASIBLE_APPROVED_CLASS
        assert slot6.pilot_slot not in end_to_end["run"].rankings

    def test_every_feasible_answer_has_a_real_ranking(self, end_to_end):
        run = end_to_end["run"]
        for result in run.primary:
            if result.is_graph_feasible:
                scored = run.rankings[result.pilot_slot]
                assert len(scored) >= glr.GRAPH_GATE_MIN_CANDIDATES
                assert run.ranking_provenance[result.pilot_slot][
                    "iterations_run"] == 3

    def test_the_diagnostic_ran_separately_and_is_labelled(self, end_to_end):
        run = end_to_end["run"]
        assert run.diagnostic is not None
        assert run.diagnostic.scope == glr.SCOPE_DIAGNOSTIC
        assert run.diagnostic.graph_stage_status == glr.DIAGNOSTIC_GRAPH_FEASIBLE
        assert len(run.diagnostic_ranking) >= glr.DIAGNOSTIC_MIN_CANDIDATES

    def test_the_diagnostic_is_absent_from_the_primary_denominator(self, end_to_end):
        run = end_to_end["run"]
        assert run.primary_denominator == 9
        assert all(r.scope == glr.SCOPE_PRIMARY for r in run.primary)

    def test_diagnostic_rows_are_flagged_in_the_ranking_csv(self, end_to_end):
        import csv as csv_module
        path = end_to_end["out_dir"] / "lrolesim_rankings.csv"
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv_module.DictReader(f))
        primary = [r for r in rows if r["primary_or_diagnostic"] == "primary"]
        diagnostic = [r for r in rows if r["primary_or_diagnostic"] == "diagnostic"]
        assert primary and diagnostic
        assert all(r["diagnostic_only"] == "false" for r in primary)
        assert all(r["excluded_from_primary_policy_metrics"] == "false"
                   for r in primary)
        assert all(r["diagnostic_only"] == "true" for r in diagnostic)
        assert all(r["excluded_from_primary_policy_metrics"] == "true"
                   for r in diagnostic)
        assert all(int(r["pilot_slot"]) == 6 for r in diagnostic)

    def test_the_diagnostic_json_states_its_boundaries(self, end_to_end):
        payload = json.loads(
            (end_to_end["out_dir"] / "sulfuric_acid_diagnostic.json").read_text())
        assert payload["diagnostic_only"] is True
        assert payload["excluded_from_primary_policy_metrics"] is True
        assert payload["primary_outcome_unchanged"] is True
        assert payload["primary_mapping_stage_status_preserved"] == \
            glr.NO_MAPPING_FEASIBLE_APPROVED_CLASS
        assert all(value is False for value in payload["boundaries"].values())

    def test_the_frozen_mapping_outputs_were_not_rewritten(self, end_to_end):
        """The run must read the Week-1 evidence, never modify it."""
        for name, expected in end_to_end["run"].mapping_input_hashes.items():
            actual = hashlib.sha256((FROZEN_DIR / name).read_bytes()).hexdigest()
            assert actual == expected

    def test_l_edt_is_deferred_because_the_type_map_is_all_zero(self, end_to_end):
        run = end_to_end["run"]
        assert run.entity_type_verdict is not None
        assert run.entity_type_verdict.status == glr.L_EDT_DEFERRED
        assert run.entity_type_verdict.nonzero_count == 0
        assert glr.L_EDT_DEFERRED in run.l_edt_refusal_message

    def test_provisional_top3_is_never_labelled_final(self, end_to_end):
        import csv as csv_module
        path = end_to_end["out_dir"] / "provisional_top3.csv"
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv_module.DictReader(f))
        assert rows
        assert all(r["result_label"] == "provisional_lrolesim_top3" for r in rows)
        assert all(r["is_final_distractor"] == "false" for r in rows)
        assert all(int(r["rank"]) <= 3 for r in rows)

    def test_context_nodes_are_never_ranked_anywhere(self, end_to_end):
        run = end_to_end["run"]
        for result in run.primary:
            if not result.is_graph_feasible:
                continue
            graph_nodes = set(result.m1_graph.graph.nodes)
            candidates = set(result.m1_graph.accepted_candidates)
            ranked = {s.local_index for s in run.rankings[result.pilot_slot]}
            assert ranked <= candidates
            context = graph_nodes - candidates - {result.answer_local_index}
            assert not (ranked & context)

    def test_all_graphs_respect_both_caps(self, end_to_end):
        for result in end_to_end["run"].primary:
            if not result.is_graph_feasible:
                continue
            assert result.m1_graph.graph.node_count <= glr.GRAPH_MAX_NODES
            assert len(result.m1_graph.accepted_candidates) <= glr.GRAPH_MAX_CANDIDATES

    def test_all_accepted_candidates_have_complete_coverage(self, end_to_end):
        for result in end_to_end["run"].primary:
            if result.m1_graph is not None:
                gv.assert_full_neighborhood_coverage(result.m1_graph.budget)

    def test_class_attempts_cover_all_twenty_seven_primary_pairs(self, end_to_end):
        import csv as csv_module
        path = end_to_end["out_dir"] / "graph_class_attempts.csv"
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv_module.DictReader(f))
        primary = [r for r in rows if r["primary_or_diagnostic"] == "primary"]
        assert len(primary) == 27
        assert len([r for r in rows if r["primary_or_diagnostic"] == "diagnostic"]) == 1


class TestGraphStageFallbackOnRealMappings:
    def test_a_forced_preferred_failure_falls_back_at_the_graph_stage(
            self, tmp_path):
        """Inflate slot 1's preferred class only; the walk must move to fallback_1.

        This is the graph gate doing something the mapping gate cannot: slot 1's
        preferred class passed mapping with 24 candidates and still fails here.
        """
        kg_path = _build_synthetic_pinned_kg(
            tmp_path, big_slots={(1, "preferred")})
        run = glr.run_pilot(
            mode=glr.MODE_RUN, local_kg_path=kg_path, local_kg_sha256=None,
            cache_path=tmp_path / "cache.jsonl", verbose=False)
        slot1 = next(r for r in run.primary if r.pilot_slot == 1)
        assert slot1.graph_stage_status == glr.GRAPH_SELECTED_FALLBACK_1
        assert slot1.attempts[0].outcome == glr.ATTEMPT_GRAPH_BUDGET_INSUFFICIENT
        assert slot1.attempts[0].graph_stage_eligible is True
        assert slot1.attempts[0].mapped_candidate_count == 24
        assert slot1.attempts[1].outcome == glr.ATTEMPT_GRAPH_FEASIBLE


class TestByteIdenticalOfflineReplay:
    def test_replay_reproduces_the_scientific_outputs_byte_for_byte(
            self, end_to_end):
        """A replay recomputes graphs, reuses cached scores, and must match exactly."""
        tmp_path = end_to_end["tmp_path"]
        replay = glr.run_pilot(
            mode=glr.MODE_REPLAY,
            local_kg_path=end_to_end["kg_path"],
            local_kg_sha256=None,
            cache_path=tmp_path / "cache.jsonl",
            verbose=False,
        )
        replay_dir = glr.write_all_outputs(
            replay, tmp_path / "replay",
            selected_mapping=end_to_end["inputs"].selected_mapping_class)

        assert replay.guard_record["network_attempts"] == 0
        assert replay.cache_record["writes"] == 0, "a replay must not write scores"
        assert replay.cache_record["hits"] > 0

        for name in glr.REPLAY_COMPARED_FILES:
            original = (end_to_end["out_dir"] / name).read_bytes()
            replayed = (replay_dir / name).read_bytes()
            assert replayed == original, f"{name} differs between run and replay"

    def test_the_replay_manifest_records_zero_calls_and_the_compared_files(
            self, end_to_end):
        payload = json.loads(
            (end_to_end["out_dir"] / "offline_replay_manifest.json").read_text())
        assert payload["http_calls"] == 0
        assert payload["sparql_calls"] == 0
        assert payload["network"]["network_attempts"] == 0
        assert set(payload["byte_identical_files"]) == set(glr.REPLAY_COMPARED_FILES)
        for name, entry in payload["file_hashes"].items():
            actual = hashlib.sha256(
                (end_to_end["out_dir"] / name).read_bytes()).hexdigest()
            assert actual == entry["sha256"], name

    def test_writing_twice_from_one_run_is_byte_identical(self, end_to_end):
        """Determinism of the writers themselves, independent of the cache."""
        tmp_path = end_to_end["tmp_path"]
        a = glr.write_all_outputs(
            end_to_end["run"], tmp_path / "again_a",
            selected_mapping=end_to_end["inputs"].selected_mapping_class)
        b = glr.write_all_outputs(
            end_to_end["run"], tmp_path / "again_b",
            selected_mapping=end_to_end["inputs"].selected_mapping_class)
        for name in glr.REPLAY_COMPARED_FILES:
            assert (a / name).read_bytes() == (b / name).read_bytes(), name


# ==========================================================================
# 12) PROTECTED SOURCES
# ==========================================================================

class TestProtectedSources:
    @pytest.mark.parametrize("relative,expected", sorted(PROTECTED_SOURCE_SHA256.items()))
    def test_protected_source_is_unmodified(self, relative, expected):
        path = REPO_ROOT / relative
        assert path.is_file(), relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, (
            f"{relative} was modified in a task that must not touch it")

    def test_the_pinned_local_kg_pickle_hash_is_the_expected_one(self):
        """Checked as a constant, so no test has to read 1.2 GB."""
        assert glr.PINNED_LOCAL_KG_SHA256 == (
            "e230c5b95e20093631697624d9c46f30a14081b3f415d5027ffaf313bdbbea1b")

    def test_the_pipeline_never_imports_a_sparql_client(self):
        source = (SRC_DIR / "pipeline" / "graph_lrolesim_run.py").read_text()
        for forbidden in ("sparql_client", "requests", "urllib.request",
                          "http.client", "SPARQLWrapper"):
            assert forbidden not in source, forbidden

    def test_the_pipeline_never_calls_the_convergence_api(self):
        source = (SRC_DIR / "pipeline" / "graph_lrolesim_run.py").read_text()
        assert "run_lrolesim_until_convergence" not in source
        assert "lrolesim_until_convergence" not in source
