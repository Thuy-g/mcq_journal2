############################################################################
# tests/test_rationale_selection.py
#
# Contract tests for the Prompt-8E rationale layer:
#   src/rationale/contracts.py
#   src/rationale/contrasts.py
#   src/rationale/setcover.py
#   src/rationale/selector.py
#   src/pipeline/rationale_selection_run.py
#   src/extract_221_and_select_distractors_ClaudeWeb_v2.py  (mode dispatch only)
#
# WHAT THESE TESTS DEFEND
#   * the AUDIT counterexample (item EX-3, test T2.3): a two-fact rationale is
#     FOUND, not discarded — the legacy |R| = 1 special case is gone;
#   * the exact dynamic program equals brute force on 1,000+ deterministic random
#     cases with k <= 5 and m <= 20, including the tie-break;
#   * object SETS are compared as sets: equal, either strict subset, partial
#     overlap, disjoint and candidate-key-absent are six distinct labels;
#   * IN and OUT facts never merge, and a shared Answer counterpart never counts
#     as coverage;
#   * POSITIVE_ALTERNATIVE_OBSERVED and ABSENCE_ONLY_OBSERVED stay distinct, and
#     positive-observed selection takes priority over snapshot-observed;
#   * the exhaustive search replaces an uncovered provisional top-three candidate
#     with a lower-ranked feasible one — checked synthetically AND on the real
#     Eisaku Satō record;
#   * an Answer with no full-coverage combination yields a PARTIAL diagnostic and
#     no algorithm-selected MCQ;
#   * Sulfuric acid stays the one PRIMARY failure and its diagnostic enters no
#     primary count;
#   * nine primary records, eight ready Answers and 204 ranked candidates are
#     consumed;
#   * no context node becomes a candidate, and no negative fact is emitted;
#   * the Prompt-8E path loads no network, SPARQL, spaCy, SBERT, abstract or
#     class-selection module, and attempts zero outbound connections;
#   * the Prompt-8D mode is untouched and its eight scientific outputs are
#     byte-identical to the frozen package;
#   * the Prompt-8E outputs reproduce byte-for-byte in a fresh offline replay;
#   * every protected Prompt-8C/8D source is byte-identical to its pin.
#
# OFFLINE
#   No network. The 1.2 GB pinned pickle is NEVER loaded: Prompt 8E consumes the
#   observed facts Prompt 8D already serialized from it, so the whole suite runs
#   from the frozen JSONL files in a fraction of a second.
#
# Run:
#     python -m pytest -vv tests/test_rationale_selection.py
############################################################################

from __future__ import annotations

import csv
import json
import random
import subprocess
import sys
from itertools import combinations
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

FROZEN_8D_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_extract_integration_2026-07-30")

import extract_221_and_select_distractors_ClaudeWeb_v2 as extract      # noqa: E402
from pipeline import rationale_selection_run as runner                 # noqa: E402
from rationale.contracts import (                                      # noqa: E402
    DIRECTION_IN,
    DIRECTION_OUT,
    EVIDENCE_ABSENCE_ONLY_OBSERVED,
    EVIDENCE_POSITIVE_ALTERNATIVE_OBSERVED,
    EVIDENCE_SHARED_OBSERVED,
    FORBIDDEN_NEGATIVE_CLAIM_PHRASES,
    HUMAN_VALIDATION_NOT_CHECKED,
    POLICY_POSITIVE_OBSERVED,
    POLICY_SNAPSHOT_OBSERVED,
    RELATION_ANSWER_STRICT_SUBSET,
    RELATION_CANDIDATE_KEY_ABSENT,
    RELATION_CANDIDATE_STRICT_SUBSET,
    RELATION_DISJOINT,
    RELATION_EQUAL,
    RELATION_PARTIAL_OVERLAP,
    REQUIRES_FALLBACK_CLASS,
    SELECTION_NO_FULL_COVERAGE,
    SELECTION_POSITIVE_OBSERVED,
    SELECTION_PRIMARY_NOT_READY,
    SELECTION_SNAPSHOT_OBSERVED,
    AnswerFact,
    RationaleContractError,
    assert_no_negative_claim,
    validate_k,
)
from rationale.contrasts import (                                      # noqa: E402
    build_answer_contrast_table,
    build_counterpart_sets,
    classify_object_sets,
    evidence_status,
)
from rationale.selector import (                                       # noqa: E402
    AnswerSelectionInput,
    RankedCandidateView,
    rationale_cover_for,
    search_all_combinations,
    select_for_answer,
)
from rationale.setcover import (                                       # noqa: E402
    CoverageFact,
    brute_force_minimum_rationale,
    count_minimum_rationales,
    cover_size_table,
    exact_minimum_rationale,
    minimum_cover_size,
)

FINGERPRINT = "f" * 64
ANSWER = "http://dbpedia.org/resource/Test_Answer"
PRED = "http://dbpedia.org/property/p"
PRED2 = "http://dbpedia.org/property/q"


# ==========================================================================
# HELPERS
# ==========================================================================

def fact(predicate: str, direction: str, counterpart: str,
         owner: str = ANSWER) -> AnswerFact:
    return AnswerFact(predicate_uri=predicate, direction=direction,
                      counterpart_uri=counterpart, graph_fingerprint=FINGERPRINT,
                      owner_uri=owner)


def coverage_fact(index: int, mask: int, absence: int = 0,
                  key: tuple[str, str, str] | None = None) -> CoverageFact:
    return CoverageFact(
        fact_index=index,
        canonical_key=key or (PRED, DIRECTION_OUT, f"o{index:03d}"),
        coverage_mask=mask,
        absence_incidences=absence,
    )


def make_selection_input(answer_triples, candidate_triples, *, scores=None,
                         answer_uri: str = ANSWER) -> AnswerSelectionInput:
    """Build one AnswerSelectionInput from plain (predicate, direction, o) tuples.

    `candidate_triples` maps candidate URI -> list of triples, in RANK order.
    Scores default to a strictly descending sequence so the frozen ranking
    invariants hold without every test having to state them.
    """
    uris = list(candidate_triples)
    if scores is None:
        scores = [1.0 - 0.01 * index for index in range(len(uris))]
    ranked = tuple(
        RankedCandidateView(rank=index + 1, canonical_candidate_uri=uri,
                            candidate_local_index=100 + index,
                            score=float(scores[index]))
        for index, uri in enumerate(uris))
    table = build_answer_contrast_table(
        answer_uri=answer_uri,
        graph_fingerprint=FINGERPRINT,
        answer_facts=[fact(*triple, owner=answer_uri)
                      for triple in answer_triples],
        candidate_facts={uri: [fact(*triple, owner=uri)
                               for triple in triples]
                         for uri, triples in candidate_triples.items()},
        candidate_order=tuple((c.canonical_candidate_uri, c.rank)
                              for c in ranked),
    )
    return AnswerSelectionInput(
        answer_uri=answer_uri,
        answer_local_index=1,
        display_label="Test Answer",
        pilot_slot=1,
        selected_class_uri="http://dbpedia.org/resource/Category:Test",
        graph_fingerprint=FINGERPRINT,
        ranker_name="lrolesim_m1_fixed_k3",
        measure="lrolesim_ed",
        lrolesim_beta=0.2,
        iterations=3,
        iteration_mode="fixed",
        ranked_candidates=ranked,
        table=table,
    )


@pytest.fixture(scope="module")
def real_run():
    """One real Prompt-8E run over the frozen Prompt-8D handoff. No KG load."""
    return runner.run_rationale_selection(prompt8d_dir=FROZEN_8D_DIR,
                                          verbose=False)


@pytest.fixture(scope="module")
def real_outputs(real_run, tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("prompt8e_primary")
    runner.write_all_outputs(real_run, out_dir, ["pytest"])
    return out_dir


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# ==========================================================================
# 1) THE AUDIT COUNTEREXAMPLE  (item EX-3, audit test T2.3)
# ==========================================================================

class TestAuditCounterexample:
    """The legacy |R| = 1 condition discarded this question. It must not now."""

    def test_two_fact_rationale_is_found(self):
        # f1 covers d1 and d2 (mask 0b011); f2 covers d3 (mask 0b100).
        facts = [coverage_fact(0, 0b011), coverage_fact(1, 0b100)]
        cover = exact_minimum_rationale(
            facts, k=3, rho=3, evidence_policy=POLICY_POSITIVE_OBSERVED)

        assert cover.full_coverage is True
        assert cover.minimum_rationale_size == 2
        assert len(cover.selected_rationale) == 2
        assert cover.feasible is True

    def test_no_single_fact_covers_all_three(self):
        """The exact answer is two facts precisely because no one fact suffices."""
        facts = [coverage_fact(0, 0b011), coverage_fact(1, 0b100)]
        assert all(f.coverage_mask != 0b111 for f in facts)
        assert minimum_cover_size([f.coverage_mask for f in facts], 3) == 2

    def test_legacy_one_fact_condition_would_have_rejected_it(self):
        """Documents the defect: the old feasibility test finds nothing here."""
        facts = [coverage_fact(0, 0b011), coverage_fact(1, 0b100)]
        legacy_feasible = any(f.coverage_mask == 0b111 for f in facts)
        assert legacy_feasible is False
        exact = exact_minimum_rationale(
            facts, k=3, rho=3, evidence_policy=POLICY_POSITIVE_OBSERVED)
        assert exact.full_coverage is True

    def test_rho_one_rejects_the_two_fact_rationale(self):
        """rho is a presentation budget: |R*| is still 2, feasibility is not."""
        facts = [coverage_fact(0, 0b011), coverage_fact(1, 0b100)]
        cover = exact_minimum_rationale(
            facts, k=3, rho=1, evidence_policy=POLICY_POSITIVE_OBSERVED)
        assert cover.minimum_rationale_size == 2      # the true minimum, untruncated
        assert cover.full_coverage is True
        assert cover.within_rho is False
        assert cover.feasible is False


# ==========================================================================
# 2) EXACT DP == BRUTE FORCE  (property test, 1,000+ deterministic cases)
# ==========================================================================

class TestExactAgainstBruteForce:

    @staticmethod
    def _random_case(rng: random.Random):
        k = rng.randint(1, 5)
        m = rng.randint(0, 20)
        facts = []
        for index in range(m):
            mask = rng.randrange(0, 1 << k)
            popcount = bin(mask).count("1")
            facts.append(CoverageFact(
                fact_index=index,
                # Deliberately NOT index order: the canonical order is the
                # (predicate, direction, counterpart) key, and the tie-break must
                # follow that key rather than the order facts arrived in.
                canonical_key=(PRED, rng.choice((DIRECTION_IN, DIRECTION_OUT)),
                               f"o{rng.randrange(0, 1000):04d}_{index}"),
                coverage_mask=mask,
                absence_incidences=rng.randint(0, popcount),
            ))
        return k, facts

    def test_exact_equals_brute_force_on_1000_random_cases(self):
        rng = random.Random(20260801)
        checked = 0
        for _ in range(1200):
            k, facts = self._random_case(rng)
            rho = rng.randint(1, 5)
            exact = exact_minimum_rationale(
                facts, k=k, rho=rho, evidence_policy=POLICY_SNAPSHOT_OBSERVED)
            reference = brute_force_minimum_rationale(
                facts, k=k, rho=rho, evidence_policy=POLICY_SNAPSHOT_OBSERVED)

            assert exact.full_coverage == reference.full_coverage
            assert exact.coverage_mask == reference.coverage_mask
            assert exact.coverage_count == reference.coverage_count
            assert exact.minimum_rationale_size == reference.minimum_rationale_size
            assert exact.absence_only_incidences == reference.absence_only_incidences
            # The tie-break too, not merely the cardinality.
            assert (exact.selected_rationale_keys()
                    == reference.selected_rationale_keys())
            checked += 1
        assert checked >= 1000

    def test_selected_rationale_actually_covers_what_it_claims(self):
        rng = random.Random(6180339)
        for _ in range(500):
            k, facts = self._random_case(rng)
            cover = exact_minimum_rationale(
                facts, k=k, rho=k, evidence_policy=POLICY_SNAPSHOT_OBSERVED)
            union = 0
            for chosen in cover.selected_rationale:
                union |= chosen.coverage_mask
            assert union == cover.coverage_mask
            assert len(cover.selected_rationale) == cover.minimum_rationale_size
            # A minimum cover is irredundant: dropping any fact loses coverage.
            for dropped in range(len(cover.selected_rationale)):
                partial = 0
                for position, chosen in enumerate(cover.selected_rationale):
                    if position != dropped:
                        partial |= chosen.coverage_mask
                assert partial != cover.coverage_mask

    def test_count_matches_naive_enumeration(self):
        rng = random.Random(2718281)
        for _ in range(300):
            k, facts = self._random_case(rng)
            if len(facts) > 12:
                facts = facts[:12]
            cover = exact_minimum_rationale(
                facts, k=k, rho=k, evidence_policy=POLICY_SNAPSHOT_OBSERVED)
            naive = 0
            for chosen in combinations(range(len(facts)),
                                       cover.minimum_rationale_size):
                union = 0
                for position in chosen:
                    union |= facts[position].coverage_mask
                if union == cover.coverage_mask:
                    naive += 1
            assert cover.optimal_rationale_count == naive

    def test_size_only_table_agrees_with_the_full_program(self):
        """The enumeration hot path and the reported cover cannot disagree."""
        rng = random.Random(1414213)
        for _ in range(500):
            k, facts = self._random_case(rng)
            table = cover_size_table([f.coverage_mask for f in facts], k)
            cover = exact_minimum_rationale(
                facts, k=k, rho=k, evidence_policy=POLICY_SNAPSHOT_OBSERVED)
            assert table[cover.coverage_mask] == cover.minimum_rationale_size
            full = (1 << k) - 1
            assert (table[full] <= k) == cover.full_coverage


# ==========================================================================
# 3) INFEASIBILITY AND DETERMINISM
# ==========================================================================

class TestFeasibilityAndDeterminism:

    def test_no_rationale_when_one_distractor_has_no_coverable_fact(self):
        # Nothing ever sets bit 2 (the third distractor).
        facts = [coverage_fact(0, 0b001), coverage_fact(1, 0b010),
                 coverage_fact(2, 0b011)]
        cover = exact_minimum_rationale(
            facts, k=3, rho=3, evidence_policy=POLICY_POSITIVE_OBSERVED)

        assert cover.full_coverage is False
        assert cover.feasible is False
        assert cover.coverage_mask == 0b011
        assert cover.coverage_count == 2
        assert cover.coverage_status == "PARTIAL_2_OF_3"
        assert cover.uncovered_positions == (2,)

    def test_zero_coverage_when_no_fact_covers_anything(self):
        cover = exact_minimum_rationale(
            [coverage_fact(0, 0)], k=3, rho=3,
            evidence_policy=POLICY_POSITIVE_OBSERVED)
        assert cover.coverage_status == "ZERO_COVERAGE"
        assert cover.coverage_count == 0
        assert cover.selected_rationale == ()

    def test_multiple_optimal_rationales_select_the_same_result_every_run(self):
        facts = [
            coverage_fact(0, 0b111, key=(PRED, DIRECTION_OUT, "o_zzz")),
            coverage_fact(1, 0b111, key=(PRED, DIRECTION_OUT, "o_aaa")),
            coverage_fact(2, 0b111, key=(PRED, DIRECTION_IN, "o_mmm")),
        ]
        results = set()
        for _ in range(25):
            shuffled = list(facts)
            random.Random(len(results)).shuffle(shuffled)
            cover = exact_minimum_rationale(
                shuffled, k=3, rho=3, evidence_policy=POLICY_POSITIVE_OBSERVED)
            results.add(cover.selected_rationale_keys())
            assert cover.optimal_rationale_count == 3
        assert len(results) == 1
        # Canonical ascending (predicate_uri, direction, counterpart_uri):
        # direction IN sorts before OUT, so the IN fact wins regardless of input order.
        assert results.pop() == ((PRED, DIRECTION_IN, "o_mmm"),)

    def test_absence_incidences_beat_canonical_order(self):
        """Tie-break 1 (fewest absence-only incidences) outranks tie-break 2."""
        facts = [
            coverage_fact(0, 0b111, absence=3, key=(PRED, DIRECTION_IN, "o_aaa")),
            coverage_fact(1, 0b111, absence=0, key=(PRED, DIRECTION_OUT, "o_zzz")),
        ]
        cover = exact_minimum_rationale(
            facts, k=3, rho=3, evidence_policy=POLICY_SNAPSHOT_OBSERVED)
        assert cover.selected_rationale_keys() == ((PRED, DIRECTION_OUT, "o_zzz"),)
        assert cover.absence_only_incidences == 0

    def test_k_outside_one_to_five_is_refused(self):
        for bad in (0, 6, -1):
            with pytest.raises(RationaleContractError):
                validate_k(bad)
        for good in (1, 2, 3, 4, 5):
            assert validate_k(good) == good


# ==========================================================================
# 4) OBJECT-SET SEMANTICS  (Prompt 8E §5)
# ==========================================================================

class TestObjectSetSemantics:

    @pytest.mark.parametrize("answer_set,candidate_set,expected", [
        ({"a", "b"}, {"a", "b"}, RELATION_EQUAL),
        ({"a"}, {"a", "b"}, RELATION_ANSWER_STRICT_SUBSET),
        ({"a", "b"}, {"a"}, RELATION_CANDIDATE_STRICT_SUBSET),
        ({"a", "b"}, {"b", "c"}, RELATION_PARTIAL_OVERLAP),
        ({"a"}, {"b"}, RELATION_DISJOINT),
        ({"a"}, set(), RELATION_CANDIDATE_KEY_ABSENT),
        ({"a", "b"}, set(), RELATION_CANDIDATE_KEY_ABSENT),
    ])
    def test_six_relations_are_total_and_exclusive(self, answer_set,
                                                   candidate_set, expected):
        assert classify_object_sets(frozenset(answer_set),
                                    frozenset(candidate_set)) == expected

    def test_candidate_key_absent_is_not_disjoint(self):
        """Absence and 'other counterparts, none shared' are different findings."""
        assert classify_object_sets(frozenset({"a"}), frozenset()) \
            == RELATION_CANDIDATE_KEY_ABSENT
        assert classify_object_sets(frozenset({"a"}), frozenset({"b"})) \
            == RELATION_DISJOINT

    def test_shared_object_is_never_coverage(self):
        assert evidence_status("a", frozenset({"a", "b"})) \
            == EVIDENCE_SHARED_OBSERVED
        assert evidence_status("a", frozenset({"a"})) == EVIDENCE_SHARED_OBSERVED

    def test_positive_alternative_and_absence_only_are_distinguished(self):
        assert evidence_status("a", frozenset({"b"})) \
            == EVIDENCE_POSITIVE_ALTERNATIVE_OBSERVED
        assert evidence_status("a", frozenset()) == EVIDENCE_ABSENCE_ONLY_OBSERVED

    def test_multi_valued_predicate_on_both_sides(self):
        """One predicate, several objects on the Answer AND on the candidate."""
        answer = [(PRED, DIRECTION_OUT, "a1"), (PRED, DIRECTION_OUT, "a2")]
        candidate = [(PRED, DIRECTION_OUT, "a2"), (PRED, DIRECTION_OUT, "c1"),
                     (PRED, DIRECTION_OUT, "c2")]
        selection_input = make_selection_input(
            answer, {"http://dbpedia.org/resource/d1": candidate,
                     "http://dbpedia.org/resource/d2": [],
                     "http://dbpedia.org/resource/d3": []})
        contrast = selection_input.table.contrasts[0]
        facts = selection_input.table.facts

        by_counterpart = {f.counterpart_uri: index
                          for index, f in enumerate(facts)}
        # a2 IS among the candidate's objects -> shared, never coverage.
        shared = contrast.evidence[by_counterpart["a2"]]
        assert shared.evidence_status == EVIDENCE_SHARED_OBSERVED
        # a1 is not, and the candidate has other objects -> positive alternative.
        alternative = contrast.evidence[by_counterpart["a1"]]
        assert alternative.evidence_status == EVIDENCE_POSITIVE_ALTERNATIVE_OBSERVED
        # The key relation is a set relation, computed once for both facts.
        assert shared.object_set_relation == RELATION_PARTIAL_OVERLAP
        assert alternative.object_set_relation == RELATION_PARTIAL_OVERLAP
        assert shared.answer_object_set_size == 2
        assert shared.candidate_object_set_size == 3

    def test_in_and_out_facts_never_merge(self):
        """Same predicate, same counterpart, opposite direction: separate keys."""
        answer = [(PRED, DIRECTION_OUT, "x")]
        # The candidate has the SAME predicate and counterpart, but INBOUND.
        candidate = [(PRED, DIRECTION_IN, "x")]
        selection_input = make_selection_input(
            answer, {"http://dbpedia.org/resource/d1": candidate,
                     "http://dbpedia.org/resource/d2": [],
                     "http://dbpedia.org/resource/d3": []})
        evidence = selection_input.table.contrasts[0].evidence[0]
        # Merging the directions would have made this SHARED_OBSERVED.
        assert evidence.evidence_status == EVIDENCE_ABSENCE_ONLY_OBSERVED
        assert evidence.object_set_relation == RELATION_CANDIDATE_KEY_ABSENT
        assert evidence.candidate_object_set_size == 0

        sets = build_counterpart_sets([fact(PRED, DIRECTION_OUT, "x"),
                                       fact(PRED, DIRECTION_IN, "x")])
        assert sets[(PRED, DIRECTION_OUT)] == frozenset({"x"})
        assert sets[(PRED, DIRECTION_IN)] == frozenset({"x"})
        assert len(sets) == 2

    def test_shared_answer_object_is_not_counted_as_coverage(self):
        answer = [(PRED, DIRECTION_OUT, "x")]
        selection_input = make_selection_input(
            answer, {"http://dbpedia.org/resource/d1": [(PRED, DIRECTION_OUT, "x")],
                     "http://dbpedia.org/resource/d2": [(PRED, DIRECTION_OUT, "y")],
                     "http://dbpedia.org/resource/d3": []})
        contrasts = selection_input.table.contrasts
        for policy in (POLICY_POSITIVE_OBSERVED, POLICY_SNAPSHOT_OBSERVED):
            assert contrasts[0].covering_fact_indices[policy] == frozenset()
        assert contrasts[1].covering_fact_indices[POLICY_POSITIVE_OBSERVED] \
            == frozenset({0})
        assert contrasts[2].covering_fact_indices[POLICY_POSITIVE_OBSERVED] \
            == frozenset()
        assert contrasts[2].covering_fact_indices[POLICY_SNAPSHOT_OBSERVED] \
            == frozenset({0})

    def test_fact_from_another_graph_is_refused(self):
        with pytest.raises(RationaleContractError):
            build_answer_contrast_table(
                answer_uri=ANSWER,
                graph_fingerprint=FINGERPRINT,
                answer_facts=[AnswerFact(PRED, DIRECTION_OUT, "x",
                                         graph_fingerprint="e" * 64,
                                         owner_uri=ANSWER)],
                candidate_facts={},
                candidate_order=(),
            )

    def test_answer_cannot_be_its_own_candidate(self):
        with pytest.raises(RationaleContractError):
            build_answer_contrast_table(
                answer_uri=ANSWER,
                graph_fingerprint=FINGERPRINT,
                answer_facts=[],
                candidate_facts={},
                candidate_order=((ANSWER, 1),),
            )


# ==========================================================================
# 5) POLICY PRIORITY AND CANDIDATE REPLACEMENT
# ==========================================================================

class TestPolicyAndSelection:

    def test_positive_observed_takes_priority_over_snapshot_observed(self):
        """Both policies reach full coverage; positive-observed must win."""
        answer = [(PRED, DIRECTION_OUT, "x")]
        selection_input = make_selection_input(answer, {
            "http://dbpedia.org/resource/d1": [(PRED, DIRECTION_OUT, "p1")],
            "http://dbpedia.org/resource/d2": [(PRED, DIRECTION_OUT, "p2")],
            "http://dbpedia.org/resource/d3": [(PRED, DIRECTION_OUT, "p3")],
        })
        selection = select_for_answer(selection_input)
        assert selection.status == SELECTION_POSITIVE_OBSERVED
        assert selection.evidence_policy == POLICY_POSITIVE_OBSERVED
        assert selection.cover is not None and selection.cover.full_coverage

    def test_snapshot_observed_is_the_labelled_fallback(self):
        """No positive alternative anywhere: only absence can cover."""
        answer = [(PRED, DIRECTION_OUT, "x")]
        selection_input = make_selection_input(answer, {
            "http://dbpedia.org/resource/d1": [(PRED2, DIRECTION_OUT, "z")],
            "http://dbpedia.org/resource/d2": [],
            "http://dbpedia.org/resource/d3": [],
        })
        selection = select_for_answer(selection_input)
        assert selection.status == SELECTION_SNAPSHOT_OBSERVED
        assert selection.evidence_policy == POLICY_SNAPSHOT_OBSERVED
        assert not selection.searches[POLICY_POSITIVE_OBSERVED].feasible(3)
        assert selection.searches[POLICY_SNAPSHOT_OBSERVED].feasible(3)

    def test_snapshot_observed_selection_is_marked_for_human_validation(self):
        answer = [(PRED, DIRECTION_OUT, "x")]
        selection_input = make_selection_input(answer, {
            "http://dbpedia.org/resource/d1": [],
            "http://dbpedia.org/resource/d2": [],
            "http://dbpedia.org/resource/d3": [],
        })
        selection = select_for_answer(selection_input)
        assert selection.status == SELECTION_SNAPSHOT_OBSERVED
        assert "REQUIRES_HUMAN_VALIDATION" in selection.status

    def test_search_replaces_an_uncovered_provisional_top_three_candidate(self):
        """d2 shares every Answer fact, so a lower-ranked candidate must replace it."""
        answer = [(PRED, DIRECTION_OUT, "x")]
        selection_input = make_selection_input(
            answer,
            {
                "http://dbpedia.org/resource/d1": [(PRED, DIRECTION_OUT, "p1")],
                # rank 2 shares the Answer's only fact: nothing can ever cover it.
                "http://dbpedia.org/resource/d2": [(PRED, DIRECTION_OUT, "x")],
                "http://dbpedia.org/resource/d3": [(PRED, DIRECTION_OUT, "p3")],
                "http://dbpedia.org/resource/d4": [(PRED, DIRECTION_OUT, "p4")],
            },
            scores=[0.9, 0.8, 0.7, 0.6])
        selection = select_for_answer(selection_input)

        assert selection.status == SELECTION_POSITIVE_OBSERVED
        assert selection.selected is not None
        assert selection.selected.ranks == (1, 3, 4)
        # The provisional top three would have been (1, 2, 3) and is infeasible.
        assert sorted(selection.selected.ranks) != [1, 2, 3]
        top3 = search_all_combinations(selection_input,
                                       policy=POLICY_POSITIVE_OBSERVED)
        assert all(outcome.ranks != (1, 2, 3)
                   for outcome in top3.full_coverage_outcomes)

    def test_selected_distractors_are_distinct_and_exclude_the_answer(self):
        answer = [(PRED, DIRECTION_OUT, "x")]
        selection_input = make_selection_input(answer, {
            f"http://dbpedia.org/resource/d{index}": [
                (PRED, DIRECTION_OUT, f"p{index}")]
            for index in range(1, 6)})
        selection = select_for_answer(selection_input)
        chosen = selection.selected
        assert chosen is not None
        assert len(set(chosen.candidate_uris)) == 3
        assert ANSWER not in chosen.candidate_uris

    def test_no_full_coverage_yields_only_a_partial_diagnostic(self):
        """Every candidate shares the Answer's only fact: nothing is coverable."""
        answer = [(PRED, DIRECTION_OUT, "x")]
        shared = [(PRED, DIRECTION_OUT, "x")]
        selection_input = make_selection_input(answer, {
            "http://dbpedia.org/resource/d1": shared,
            "http://dbpedia.org/resource/d2": shared,
            "http://dbpedia.org/resource/d3": shared,
        })
        selection = select_for_answer(selection_input)

        assert selection.status == SELECTION_NO_FULL_COVERAGE
        assert selection.selected is None
        assert selection.cover is None
        assert selection.requires_fallback_class is True
        assert selection.full_coverage_exists_but_exceeds_rho is False
        for policy in (POLICY_POSITIVE_OBSERVED, POLICY_SNAPSHOT_OBSERVED):
            partial = selection.partial_covers[policy]
            assert partial is not None
            assert partial.full_coverage is False
            assert partial.coverage_status == "ZERO_COVERAGE"

    def test_partial_two_of_three_is_reported_as_partial(self):
        answer = [(PRED, DIRECTION_OUT, "x")]
        selection_input = make_selection_input(answer, {
            "http://dbpedia.org/resource/d1": [(PRED, DIRECTION_OUT, "p1")],
            "http://dbpedia.org/resource/d2": [(PRED, DIRECTION_OUT, "p2")],
            "http://dbpedia.org/resource/d3": [(PRED, DIRECTION_OUT, "x")],
        })
        selection = select_for_answer(selection_input)
        assert selection.status == SELECTION_NO_FULL_COVERAGE
        partial = selection.partial_covers[POLICY_POSITIVE_OBSERVED]
        assert partial is not None
        assert partial.coverage_status == "PARTIAL_2_OF_3"
        assert partial.coverage_count == 2

    def test_feasibility_is_not_merely_each_candidate_missing_something(self):
        """Per-candidate coverage is necessary, never sufficient (Prompt 8E §8)."""
        # Each candidate is covered by SOME fact, and a full cover therefore
        # exists here; the point is that the necessary condition is checked
        # separately from the set-cover verdict and never substituted for it.
        answer = [(PRED, DIRECTION_OUT, "x"), (PRED2, DIRECTION_OUT, "y")]
        selection_input = make_selection_input(answer, {
            "http://dbpedia.org/resource/d1": [(PRED, DIRECTION_OUT, "p1")],
            "http://dbpedia.org/resource/d2": [(PRED2, DIRECTION_OUT, "p2")],
            "http://dbpedia.org/resource/d3": [(PRED, DIRECTION_OUT, "p3")],
        })
        search = search_all_combinations(selection_input,
                                         policy=POLICY_POSITIVE_OBSERVED)
        assert search.candidates_with_any_coverage == 3
        cover = rationale_cover_for(selection_input.table, (0, 1, 2),
                                    policy=POLICY_POSITIVE_OBSERVED)
        assert cover.full_coverage is True
        assert cover.minimum_rationale_size == 2       # no single fact suffices


# ==========================================================================
# 6) THE REAL PROMPT-8D INPUT CONTRACT  (§4)
# ==========================================================================

class TestRealInputContract:

    def test_nine_primary_eight_ready_two_hundred_four_candidates(self, real_run):
        counts = real_run.counts()
        assert counts["primary_answer_denominator"] == 9
        assert counts["primary_ready_for_rationale_selection"] == 8
        assert counts["primary_ranked_candidate_total"] == 204
        assert len(real_run.selections) == 9
        assert len(real_run.selection_inputs) == 8

    def test_complete_ranking_is_searched_not_the_provisional_top_three(
            self, real_run):
        for selection_input in real_run.selection_inputs:
            selection = real_run.selection_for(selection_input.answer_uri)
            search = selection.searches[POLICY_POSITIVE_OBSERVED]
            assert search.candidate_count == selection_input.candidate_count
            assert search.candidate_count > 3
            from math import comb
            assert search.combination_count == comb(search.candidate_count, 3)

    def test_frozen_lrolesim_execution_path_is_unchanged(self, real_run):
        for selection_input in real_run.selection_inputs:
            assert selection_input.ranker_name == "lrolesim_m1_fixed_k3"
            assert selection_input.measure == "lrolesim_ed"
            assert selection_input.lrolesim_beta == 0.2
            assert selection_input.iterations == 3
            assert selection_input.iteration_mode == "fixed"

    def test_context_nodes_cannot_become_candidates(self, real_run):
        """Every candidate-fact owner is a ranked candidate, never a context node."""
        ranked = {item.answer_uri: set(item.table.candidate_uris())
                  for item in real_run.selection_inputs}
        for record in real_run.inputs.candidate_facts:
            assert record["owner_uri"] in ranked[record["answer_uri"]]
            assert record["owner_uri"] != record["answer_uri"]

    def test_every_fact_belongs_to_its_answer_graph_fingerprint(self, real_run):
        for selection_input in real_run.selection_inputs:
            for observed in selection_input.table.facts:
                assert observed.graph_fingerprint \
                    == selection_input.graph_fingerprint

    def test_a_shortened_handoff_is_refused(self, tmp_path):
        """The §4 shape is asserted, not assumed."""
        broken = tmp_path / "broken"
        broken.mkdir()
        for name in runner.REQUIRED_INPUT_FILES:
            source = FROZEN_8D_DIR / name
            if name == "candidate_ranking_handoff.jsonl":
                lines = source.read_text(encoding="utf-8").splitlines()
                (broken / name).write_text("\n".join(lines[:-1]) + "\n",
                                           encoding="utf-8")
            else:
                (broken / name).write_bytes(source.read_bytes())
        with pytest.raises(runner.Prompt8DInputError):
            runner.load_prompt8d_handoff(broken)


# ==========================================================================
# 7) THE REAL SELECTION RESULT
# ==========================================================================

class TestRealSelection:

    def test_sulfuric_acid_remains_the_one_primary_failure(self, real_run):
        sulfuric = real_run.selection_for(
            "http://dbpedia.org/resource/Sulfuric_acid")
        assert sulfuric.ready is False
        assert sulfuric.status == SELECTION_PRIMARY_NOT_READY
        assert sulfuric.selected is None
        assert sulfuric.cover is None
        others = [s for s in real_run.selections
                  if s.answer_uri != "http://dbpedia.org/resource/Sulfuric_acid"]
        assert all(s.ready for s in others)

    def test_diagnostic_records_do_not_enter_primary_metrics(self, real_run):
        counts = real_run.counts()
        assert counts["primary_answer_denominator"] == 9
        assert counts["primary_ranked_candidate_total"] == 204
        # The six diagnostic candidates live in their own namespace.
        assert real_run.diagnostic_input is not None
        assert real_run.diagnostic_input.candidate_count == 6
        assert real_run.diagnostic_input.answer_uri not in {
            item.answer_uri for item in real_run.selection_inputs}
        selected = sum(1 for s in real_run.selections if s.algorithm_selected)
        assert selected + counts["no_full_coverage_total"] \
            + counts["primary_not_ready"] == 9

    def test_diagnostic_exercises_the_snapshot_observed_fallback(self, real_run):
        """Sulfuric acid's diagnostic has no positive alternative anywhere."""
        diagnostic = real_run.diagnostic_selection
        assert diagnostic is not None
        assert diagnostic.searches[POLICY_POSITIVE_OBSERVED].feasible(3) == ()
        assert diagnostic.status == SELECTION_SNAPSHOT_OBSERVED

    def test_real_candidate_replacement_for_eisaku_sato(self, real_run):
        """Ranks 3 and 4 have no positive-observed covering fact; rank 5 replaces."""
        selection = real_run.selection_for(
            "http://dbpedia.org/resource/Eisaku_Satō")
        assert selection.selected is not None
        assert selection.selected.ranks == (1, 2, 5)
        table = real_run.input_for(selection.answer_uri).table
        for position in (2, 3):                       # ranks 3 and 4
            assert table.contrasts[position].covering_fact_indices[
                POLICY_POSITIVE_OBSERVED] == frozenset()

    def test_every_selected_set_is_verified_by_the_exact_cover(self, real_run):
        for selection in real_run.selections:
            if not selection.algorithm_selected:
                continue
            assert selection.cover is not None
            assert selection.cover.full_coverage is True
            assert selection.cover.feasible is True
            assert selection.cover.minimum_rationale_size <= selection.rho
            assert len(set(selection.selected.candidate_uris)) == 3
            assert selection.answer_uri not in selection.selected.candidate_uris

    def test_rho_ablation_covers_every_policy_and_rho(self, real_run):
        for selection in real_run.ready_selections:
            cells = {(row.evidence_policy, row.rho) for row in selection.ablation}
            assert cells == {(policy, rho)
                             for policy in (POLICY_POSITIVE_OBSERVED,
                                            POLICY_SNAPSHOT_OBSERVED)
                             for rho in (1, 2, 3)}
            # Feasible counts are monotone non-decreasing in rho.
            for policy in (POLICY_POSITIVE_OBSERVED, POLICY_SNAPSHOT_OBSERVED):
                counts = [row.feasible_triple_count for row in selection.ablation
                          if row.evidence_policy == policy]
                assert counts == sorted(counts)

    def test_ablation_does_not_move_the_primary_selection(self, real_run):
        """rho = 3 under positive-observed IS the primary configuration."""
        for selection in real_run.ready_selections:
            if selection.evidence_policy != POLICY_POSITIVE_OBSERVED:
                continue
            primary = [row for row in selection.ablation
                       if row.evidence_policy == POLICY_POSITIVE_OBSERVED
                       and row.rho == 3]
            assert len(primary) == 1
            assert primary[0].best_candidate_uris \
                == selection.selected.candidate_uris


# ==========================================================================
# 8) OUTPUT ARTEFACTS
# ==========================================================================

class TestOutputs:

    def test_summary_holds_exactly_nine_primary_rows(self, real_outputs):
        rows = read_csv(real_outputs / "rationale_selection_summary.csv")
        assert len(rows) == 9
        assert all(row["primary_or_diagnostic"] == "primary" for row in rows)
        sulfuric = [row for row in rows
                    if row["answer_uri"].endswith("Sulfuric_acid")]
        assert len(sulfuric) == 1
        assert sulfuric[0]["selection_status"] == SELECTION_PRIMARY_NOT_READY
        assert sulfuric[0]["ready_for_rationale_selection"] == "false"
        assert sulfuric[0]["algorithm_selected_distractor"] == "false"

    def test_every_selected_mcq_requires_human_validation(self, real_outputs):
        records = read_jsonl(real_outputs / "algorithm_selected_distractors.jsonl")
        assert records
        for record in records:
            assert record["algorithm_selected_distractor"] is True
            assert record["requires_human_validation"] is True
            assert record["human_validated"] is False
            assert record["human_validation_status"] == HUMAN_VALIDATION_NOT_CHECKED
            assert record["publishable_final"] is False
            # No bare is_final_distractor anywhere in the schema.
            assert "is_final_distractor" not in record

    def test_positive_observed_records_still_require_validation(self, real_outputs):
        records = read_jsonl(real_outputs / "algorithm_selected_distractors.jsonl")
        positive = [r for r in records
                    if r["selection_status"] == SELECTION_POSITIVE_OBSERVED]
        assert positive
        for record in positive:
            assert record["requires_human_validation"] is True
            assert record["publishable_final"] is False

    def test_selected_rationale_facts_carry_the_required_fields(self, real_outputs):
        records = read_jsonl(real_outputs / "selected_rationales.jsonl")
        assert records
        required = {"predicate_uri", "direction", "counterpart_uri",
                    "coverage_mask", "covered_candidate_uris",
                    "per_candidate_evidence_status", "graph_fingerprint",
                    "source"}
        for record in records:
            assert required <= set(record)
            assert record["source"] == "pinned_local_kg_observed_fact"
            assert record["direction"] in (DIRECTION_IN, DIRECTION_OUT)
            assert len(record["per_candidate_evidence_status"]) == 3
            covered = set(record["covered_candidate_uris"])
            for uri, status in record["per_candidate_evidence_status"].items():
                if uri in covered:
                    assert status != EVIDENCE_SHARED_OBSERVED
                else:
                    assert status == EVIDENCE_SHARED_OBSERVED \
                        or record["evidence_policy"] == POLICY_POSITIVE_OBSERVED

    def test_selected_rationale_masks_union_to_full(self, real_outputs):
        by_answer: dict[str, int] = {}
        for record in read_jsonl(real_outputs / "selected_rationales.jsonl"):
            by_answer[record["answer_uri"]] = (
                by_answer.get(record["answer_uri"], 0) | record["coverage_mask"])
        assert by_answer
        assert all(mask == 0b111 for mask in by_answer.values())

    def test_triple_search_audit_reports_the_exhaustive_search(self, real_outputs):
        records = read_jsonl(real_outputs / "triple_search_audit.jsonl")
        assert len(records) == 8
        for record in records:
            assert record["exhaustive_search"] is True
            assert record["provisional_top3_treated_as_final"] is False
            assert record["combination_count"] > 0
            assert len(record["candidate_roster"]) == record["candidate_count"]
            for policy in (POLICY_POSITIVE_OBSERVED, POLICY_SNAPSHOT_OBSERVED):
                top = record["top_feasible_combinations"][policy]
                assert len(top) <= 20
                assert all(entry["full_coverage"] for entry in top)

    def test_fact_coverage_covers_every_answer_fact(self, real_run, real_outputs):
        records = read_jsonl(real_outputs / "fact_coverage.jsonl")
        expected = sum(item.table.fact_count
                       for item in real_run.selection_inputs)
        assert len(records) == expected == 582
        for record in records:
            assert len(record["per_candidate"]) == record["candidate_count"]
            positive = set(record["covered_candidate_ranks_positive_observed"])
            snapshot = set(record["covered_candidate_ranks_snapshot_observed"])
            # positive-observed coverage is a subset of snapshot-observed coverage.
            assert positive <= snapshot

    def test_partial_diagnostics_are_empty_when_everything_is_covered(
            self, real_outputs):
        records = read_jsonl(real_outputs / "partial_coverage_diagnostics.jsonl")
        assert records == []

    def test_partial_diagnostics_are_written_when_needed(self, tmp_path):
        """Exercised on synthetic input: the real pilot has no such Answer."""
        answer = [(PRED, DIRECTION_OUT, "x")]
        shared = [(PRED, DIRECTION_OUT, "x")]
        selection_input = make_selection_input(answer, {
            f"http://dbpedia.org/resource/d{index}": shared
            for index in range(1, 5)})
        selection = select_for_answer(selection_input)
        assert selection.status == SELECTION_NO_FULL_COVERAGE
        assert selection.requires_fallback_class
        assert REQUIRES_FALLBACK_CLASS.endswith("GRAPH_LROLESIM_RUN")

    def test_rho_ablation_csv_shape(self, real_outputs):
        rows = read_csv(real_outputs / "rho_ablation.csv")
        assert len(rows) == 8 * 2 * 3
        primary = [row for row in rows if row["is_primary_configuration"] == "true"]
        assert len(primary) == 8
        assert all(row["rho"] == "3" for row in primary)
        assert all(row["evidence_policy"] == POLICY_POSITIVE_OBSERVED
                   for row in primary)

    def test_sulfuric_acid_diagnostic_is_isolated(self, real_outputs):
        payload = json.loads(
            (real_outputs / "sulfuric_acid_diagnostic_rationale.json").read_text())
        assert payload["diagnostic_only"] is True
        assert payload["excluded_from_primary_policy_metrics"] is True
        assert payload["primary_record"]["selection_status"] \
            == SELECTION_PRIMARY_NOT_READY
        assert payload["primary_record"]["algorithm_selected_distractor"] is False
        assert all(value is False for value in payload["boundaries"].values())
        analysis = payload["diagnostic_analysis"]
        assert analysis["candidate_count"] == 6
        assert analysis["publishable_final"] is False

    def test_no_negative_fact_is_emitted_anywhere(self, real_outputs):
        for path in sorted(real_outputs.iterdir()):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            assert_no_negative_claim(text, where=path.name)
            for phrase in FORBIDDEN_NEGATIVE_CLAIM_PHRASES:
                assert phrase not in text.lower()

    def test_no_evidence_status_names_a_negation(self):
        for status in (EVIDENCE_SHARED_OBSERVED,
                       EVIDENCE_POSITIVE_ALTERNATIVE_OBSERVED,
                       EVIDENCE_ABSENCE_ONLY_OBSERVED):
            assert "FALSE" not in status
            assert "NOT" not in status
            assert status.endswith("OBSERVED")


# ==========================================================================
# 9) OFFLINE, DETERMINISM AND REGRESSION
# ==========================================================================

class TestOfflineAndRegression:

    def test_zero_network_attempts(self, real_run):
        assert real_run.guard_record["network_attempts"] == 0
        assert real_run.guard_record["http_calls"] == 0
        assert real_run.guard_record["sparql_calls"] == 0
        assert real_run.guard_record["attempted_addresses"] == []

    def test_the_run_imports_no_forbidden_module(self):
        """Measured as a DELTA over sys.modules, not as an absolute snapshot.

        `loaded_forbidden_modules()` inspects the whole process, which is exactly
        right for a standalone run and is what the run manifest publishes. Inside a
        shared pytest session it is not: tests/test_pilot_sparql_client.py and
        tests/test_lrolesim_adapter.py legitimately import the SPARQL layer and the
        LRoleSim kernel into the same interpreter, so an absolute assertion here
        would fail for a reason that has nothing to do with this code path. What
        must hold is that THIS run pulls none of them in; the subprocess test below
        settles the absolute form in a fresh interpreter.
        """
        before = set(sys.modules)
        runner.run_rationale_selection(prompt8d_dir=FROZEN_8D_DIR, verbose=False)
        added = set(sys.modules) - before
        forbidden = sorted(
            name for name in added
            if any(name == prefix or name.startswith(prefix + ".")
                   for prefix in runner.FORBIDDEN_MODULE_PREFIXES))
        assert forbidden == []

    def test_the_pinned_kg_is_never_loaded(self, real_run, real_outputs):
        """The 1.2 GB pickle is not opened: Prompt 8D already serialized it.

        In-process `sys.modules` proves nothing here, because other tests in the
        session may import the loader for their own reasons. The subprocess test
        below is the one that settles it.
        """
        manifest = json.loads((real_outputs / "run_manifest.json").read_text())
        assert manifest["pinned_local_kg_loaded"] is False
        assert manifest["pinned_local_kg_expected_sha256"] \
            == "e230c5b95e20093631697624d9c46f30a14081b3f415d5027ffaf313bdbbea1b"

    def test_subprocess_run_imports_nothing_forbidden(self, tmp_path):
        """The strongest form: a fresh interpreter, checked after the run."""
        script = (
            "import json, sys\n"
            f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
            "from pipeline import rationale_selection_run as r\n"
            f"run = r.run_rationale_selection(prompt8d_dir={str(FROZEN_8D_DIR)!r},"
            " verbose=False)\n"
            f"r.write_all_outputs(run, {str(tmp_path / 'out')!r}, ['test'])\n"
            "print(json.dumps({'forbidden': r.loaded_forbidden_modules(),\n"
            "                  'network': run.guard_record['network_attempts']}))\n"
        )
        completed = subprocess.run([sys.executable, "-c", script],
                                   cwd=REPO_ROOT, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        assert payload["forbidden"] == []
        assert payload["network"] == 0

    def test_outputs_reproduce_byte_for_byte(self, real_outputs, tmp_path):
        replay = tmp_path / "replay"
        run = runner.run_rationale_selection(prompt8d_dir=FROZEN_8D_DIR,
                                             verbose=False)
        runner.write_all_outputs(run, replay, ["pytest-replay"])
        for name in runner.REPLAY_COMPARED_FILES:
            assert (replay / name).read_bytes() == (real_outputs / name).read_bytes(), \
                f"{name} is not byte-identical across runs"

    def test_protected_sources_are_unmodified(self):
        observed = runner.verify_protected_sources()
        assert len(observed) == 10
        for name, record in observed.items():
            assert record["unmodified"] is True, name
            assert record["observed_sha256"] == record["expected_sha256"]

    def test_prompt8d_frozen_outputs_are_byte_identical(self):
        """The Prompt-8D scientific outputs this task consumes are unchanged."""
        manifest = json.loads(
            (FROZEN_8D_DIR / "offline_replay_manifest.json").read_text())
        assert len(manifest["byte_identical_files"]) == 8
        for name, recorded in manifest["file_hashes"].items():
            path = FROZEN_8D_DIR / name
            assert runner.sha256_file(path) == recorded["sha256"], name
            assert path.stat().st_size == recorded["size_bytes"], name

    def test_prompt8d_input_hashes_are_recorded(self, real_run):
        for name in runner.REQUIRED_INPUT_FILES:
            assert name in real_run.inputs.input_sha256
            assert len(real_run.inputs.input_sha256[name]) == 64


# ==========================================================================
# 10) MODE DISPATCH  (the narrow patch to the extract entrypoint)
# ==========================================================================

class TestModeDispatch:

    def test_the_new_mode_exists_and_the_old_ones_are_unchanged(self):
        assert extract.MODES == ("pilot-lrolesim-handoff",
                                 "pilot-rationale-selection",
                                 "legacy-overlap")
        assert extract.MODE_PILOT_RATIONALE_SELECTION == "pilot-rationale-selection"
        assert extract.RANKER_FOR_MODE[extract.MODE_PILOT_RATIONALE_SELECTION] \
            == "lrolesim_m1_fixed_k3"

    def test_an_omitted_mode_is_an_error(self):
        with pytest.raises(SystemExit):
            extract.build_arg_parser().parse_args([])

    def test_an_unknown_mode_is_an_error_not_a_fall_through(self):
        with pytest.raises(SystemExit):
            extract.build_arg_parser().parse_args(["--mode", "pilot-rationale"])
        args = extract.build_arg_parser().parse_args(
            ["--mode", "pilot-rationale-selection"])
        args.mode = "not-a-mode"
        with pytest.raises(extract.UnknownModeError):
            extract.dispatch("not-a-mode", args)

    def test_the_entrypoint_owns_no_set_cover_mathematics(self):
        """Prompt 8E §3: the extract entrypoint must delegate, not implement."""
        source = (SRC_DIR / "extract_221_and_select_distractors_ClaudeWeb_v2.py"
                  ).read_text(encoding="utf-8")
        for forbidden in ("coverage_mask", "full_mask", "minimum_rationale",
                          "set_cover", "combinations("):
            assert forbidden not in source, (
                f"{forbidden!r} appears in the extract entrypoint; set-cover and "
                f"combination mathematics belong in src/rationale/")

    def test_the_prompt8d_directory_default_agrees_with_the_runner(self):
        assert Path(extract.DEFAULT_PROMPT8D_DIR) \
            == runner.FROZEN_PROMPT8D_DIR

    def test_direction_spellings_agree_across_the_two_layers(self):
        from selection.contracts import DIRECTION_IN as SELECTION_IN
        from selection.contracts import DIRECTION_OUT as SELECTION_OUT
        assert DIRECTION_IN == SELECTION_IN
        assert DIRECTION_OUT == SELECTION_OUT

    def test_the_rationale_package_does_not_import_lrolesim_or_selection(self):
        """Audit §9.2: the rationale layer is independent by construction."""
        for name in ("contracts", "contrasts", "setcover", "selector"):
            source = (SRC_DIR / "rationale" / f"{name}.py").read_text(
                encoding="utf-8")
            for line in source.splitlines():
                stripped = line.strip()
                if not (stripped.startswith("import ")
                        or stripped.startswith("from ")):
                    continue
                for forbidden in ("lrolesim", "selection.", "kg.", "classes.",
                                  "pipeline."):
                    assert forbidden not in stripped, (
                        f"src/rationale/{name}.py imports {stripped!r}")
