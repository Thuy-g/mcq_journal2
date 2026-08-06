"""Tests for the Phase A selection kernel, ``src/mcq_core.py``.

Four groups:

* **mathematical correctness** — the exact bitmask set cover against brute
  force on deterministic random cases, plus the mask semantics that the whole
  method rests on: NOT_COVERED never covers, the threshold ladder behaves, and
  IN and OUT are different facts;
* **the Eisaku Satō regression** — every numeric claim in
  ``docs/audits/EISAKU_SATO_SELECTION_TRACE.md`` that the kernel is responsible
  for, rebuilt from the frozen Prompt-8F-R1 evidence records;
* **the eight-pilot regression** — all eight R1 pilot selections reproduced
  exactly, with ``selected_mcqs_v3_r1.jsonl`` used ONLY as the oracle, and the
  published regression CSV checked against what the kernel actually produces;
* **determinism and safety** — byte-identical canonical output, immunity to
  the caller's candidate ordering, no network, no forbidden imports, and the
  terminology guard.

Nothing here imports ``scripts/spec_freeze_audit.py``, ``src.rationale_v3`` or
``src.rationale``. The kernel is checked on its own terms. No network, no
pinned-KG load: every input is a frozen file under ``outputs/``.
"""

from __future__ import annotations

import ast
import csv
import itertools
import json
import random
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcq_core import (  # noqa: E402
    K_DISTRACTORS,
    LEVEL_STRENGTH,
    POLICY_ORDER,
    AnswerFact,
    Candidate,
    FactQuality,
    build_case,
    canonical_record,
    case_masks,
    combination_objective_key,
    coverage_mask,
    local_pool_anonymity,
    minimum_cover_size,
    minimum_cover_size_table,
    rank_minimum_rationales,
    select_distractors,
)

CORE_SOURCE = ROOT / "src" / "mcq_core.py"
R1_DIR = ROOT / "outputs" / "journal2_week2_rationale_v3_r1_2026-08-03"
HANDOFF = (ROOT / "outputs" / "journal2_week2_extract_integration_2026-07-30"
           / "candidate_ranking_handoff.jsonl")
REGRESSION_CSV = ROOT / "docs" / "checks" / "MINIMAL_CORE_PHASE_A_REGRESSION.csv"

SATO = "http://dbpedia.org/resource/Eisaku_Satō"
ALMA_MATER = ("http://dbpedia.org/property/almaMater", "OUT",
              "http://dbpedia.org/resource/University_of_Tokyo")
BEFORE = ("http://dbpedia.org/property/before", "IN",
          "http://dbpedia.org/resource/Kiichi_Aichi")


# --------------------------------------------------------------------------
# Synthetic fixtures — small hand-built cases with no dependency on the pilot
# --------------------------------------------------------------------------


def make_fact(levels, *, predicate="http://example.org/p", direction="OUT",
              counterpart="http://example.org/o", eligible=True, soft_leak=False,
              verbalizable=True, tier=1, label_length=5, tokens=1,
              bases=None, risks=None, template="T"):
    """One already-classified Answer fact. ``levels[i]`` is the level on candidate i."""
    size = len(levels)
    quality = FactQuality(
        predicate_uri=predicate, direction=direction, counterpart_uri=counterpart,
        display_label=counterpart.rsplit("/", 1)[-1], eligible=eligible,
        soft_leak=soft_leak, verbalizable=verbalizable, pedagogical_tier=tier,
        label_length=label_length, token_count=tokens, template_id=template)
    return AnswerFact(quality=quality, levels=tuple(levels),
                      exclusion_bases=tuple(bases or ["NONE"] * size),
                      granularity_risks=tuple(risks or ["NONE"] * size))


def make_case(facts, count=None):
    """A synthetic AnswerCase with ``count`` candidates of descending score."""
    size = count if count is not None else len(facts[0].levels)
    candidates = [Candidate(rank=i + 1, score=1.0 - i / 100,
                            uri=f"http://example.org/c{i}") for i in range(size)]
    return build_case("http://example.org/A", "A", candidates, facts)


# --------------------------------------------------------------------------
# 1. Mathematical correctness — the exact bitmask set cover
# --------------------------------------------------------------------------


def brute_force_cover(masks, k):
    """Smallest number of masks OR-ing to the full mask, by exhaustive search."""
    full = (1 << k) - 1
    distinct = sorted({m for m in masks if m})
    for size in range(len(distinct) + 1):
        for combo in itertools.combinations(distinct, size):
            covered = 0
            for mask in combo:
                covered |= mask
            if covered == full:
                return size
    return k + 1


@pytest.mark.parametrize("seed", range(120))
def test_exact_dp_equals_brute_force(seed):
    """The DP must agree with exhaustive search on every deterministic case."""
    rng = random.Random(seed)
    k = rng.choice([2, 3, 4, 5])
    masks = [rng.randrange(0, 1 << k) for _ in range(rng.randint(0, 11))]
    expected = min(brute_force_cover(masks, k), k + 1)
    assert minimum_cover_size(masks, k) == expected


def brute_force_exact_state(masks, k, state):
    """Smallest number of distinct masks whose OR is EXACTLY ``state``.

    The DP table holds one entry per reachable OR value, so the reference
    implementation must match on the OR being exactly the state, not merely a
    superset of it.
    """
    distinct = sorted({m for m in masks if m})
    best = k + 1
    for size in range(len(distinct) + 1):
        if size >= best:
            break
        for combo in itertools.combinations(distinct, size):
            covered = 0
            for mask in combo:
                covered |= mask
            if covered == state:
                best = size
                break
    return min(best, k + 1)


@pytest.mark.parametrize("seed", range(40))
def test_exact_dp_equals_brute_force_on_every_state(seed):
    """Not only the full mask: every one of the 2^k table entries is exact."""
    rng = random.Random(1000 + seed)
    k = rng.choice([2, 3, 4])
    masks = [rng.randrange(0, 1 << k) for _ in range(rng.randint(0, 8))]
    table = minimum_cover_size_table(masks, k)
    for state in range(1 << k):
        assert table[state] == brute_force_exact_state(masks, k, state)


def test_unreachable_full_mask_is_reported_as_k_plus_one():
    """No fact reaches the third distractor, so no cover exists at all."""
    assert minimum_cover_size([0b001, 0b010], 3) == 4
    assert minimum_cover_size([], 3) == 4
    # k + 1 is strictly larger than any achievable size, so one comparison
    # against rho rejects "impossible" and "too large" together.
    assert minimum_cover_size([0b001, 0b010], 3) > K_DISTRACTORS


def test_duplicate_masks_are_collapsed_without_changing_the_answer():
    """A minimum cover never contains two facts carrying the same mask."""
    assert minimum_cover_size([0b011, 0b011, 0b011, 0b100], 3) == 2
    assert minimum_cover_size_table([0b011, 0b011, 0b100], 3) == \
        minimum_cover_size_table([0b011, 0b100], 3)
    # A zero mask covers nobody and can never help.
    assert minimum_cover_size_table([0, 0, 0b111], 3) == \
        minimum_cover_size_table([0b111], 3)


def test_one_fact_rationale():
    case = make_case([make_fact(["L1", "L1", "L1"])])
    size, level, ranked = rank_minimum_rationales(case, (0, 1, 2), "main-l1")
    assert (size, level) == (1, "L1")
    assert ranked[0].coverage_mask == 0b111
    assert len(ranked[0].fact_indices) == 1


def test_two_fact_rationale():
    """The Eisaku Satō shape in miniature: two exactly complementary facts."""
    case = make_case([make_fact(["NOT_COVERED", "L1", "L1"], counterpart="http://example.org/o1"),
                      make_fact(["L1", "L0", "L0"], counterpart="http://example.org/o2")])
    size, _, ranked = rank_minimum_rationales(case, (0, 1, 2), "main-l1")
    assert size == 2
    assert sorted(ranked[0].coverage_masks) == [0b001, 0b110]
    assert ranked[0].coverage_mask == 0b111


def test_three_fact_rationale():
    case = make_case([make_fact(["L1", "L0", "L0"], counterpart="http://example.org/o1"),
                      make_fact(["L0", "L1", "L0"], counterpart="http://example.org/o2"),
                      make_fact(["L0", "L0", "L1"], counterpart="http://example.org/o3")])
    size, _, ranked = rank_minimum_rationales(case, (0, 1, 2), "main-l1")
    assert size == 3
    assert sorted(ranked[0].coverage_masks) == [0b001, 0b010, 0b100]


def test_rationale_larger_than_rho_is_infeasible():
    """rho = 3 distractors, so a fourth required fact makes the combination fail."""
    case = make_case([make_fact(["L1", "L0", "L0", "L0"], counterpart="http://example.org/o1"),
                      make_fact(["L0", "L1", "L0", "L0"], counterpart="http://example.org/o2"),
                      make_fact(["L0", "L0", "L1", "L0"], counterpart="http://example.org/o3")],
                     count=4)
    assert rank_minimum_rationales(case, (0, 1, 2), "main-l1") is not None
    assert rank_minimum_rationales(case, (1, 2, 3), "main-l1") is None


# --------------------------------------------------------------------------
# 2. Mathematical correctness — mask semantics
# --------------------------------------------------------------------------


def test_bit_i_tracks_position_i_of_the_combination():
    """The mask is meaningless without the combination it was built against."""
    fact = make_fact(["L1", "L0", "L1"])
    assert coverage_mask(fact, (0, 1, 2), "L1") == 0b101
    assert coverage_mask(fact, (1, 0, 2), "L1") == 0b110
    assert coverage_mask(fact, (2, 1, 0), "L1") == 0b101


def test_not_covered_never_sets_a_bit_at_any_threshold():
    """The candidate SUPPORTS the proposition, so the fact discriminates nothing."""
    fact = make_fact(["NOT_COVERED", "NOT_COVERED", "L1"])
    for threshold in ("L2", "L1", "L0"):
        assert coverage_mask(fact, (0, 1, 2), threshold) & 0b011 == 0
    assert coverage_mask(fact, (0, 1, 2), "L0") == 0b100
    assert LEVEL_STRENGTH["NOT_COVERED"] == 0


def test_threshold_ladder_l0_l1_l2():
    """Raising the threshold can only ever shrink a mask."""
    fact = make_fact(["L2", "L1", "L0"])
    assert coverage_mask(fact, (0, 1, 2), "L0") == 0b111
    assert coverage_mask(fact, (0, 1, 2), "L1") == 0b011
    assert coverage_mask(fact, (0, 1, 2), "L2") == 0b001


def test_l2_is_accepted_as_an_input_level_by_the_generic_kernel():
    """Phase A implements no L2 rule, but must order an L2 input correctly."""
    case = make_case([make_fact(["L2", "L2", "L2"])])
    selection = select_distractors(case)
    assert selection.evidence_policy == "strict-l2"
    assert selection.mcq_evidence_level == "MCQ-L2"


def test_strict_l2_is_skipped_when_no_l2_evidence_exists():
    """Policy order strict-l2 -> main-l1 -> diagnostic-l0, first feasible wins."""
    case = make_case([make_fact(["L1", "L1", "L1"])])
    assert select_distractors(case).evidence_policy == "main-l1"
    assert POLICY_ORDER == ("strict-l2", "main-l1", "diagnostic-l0")


def test_diagnostic_l0_is_reached_only_when_main_l1_is_infeasible():
    """Absence-only coverage is the last resort and is labelled as such."""
    case = make_case([make_fact(["L1", "L0", "L0"], counterpart="http://example.org/o1")])
    selection = select_distractors(case)
    assert selection.evidence_policy == "diagnostic-l0"
    assert selection.mcq_evidence_level == "MCQ-L0"


def test_in_and_out_are_different_fact_identities():
    """(p, IN) and (p, OUT) are different relations and must never merge."""
    same_predicate = "http://example.org/influences"
    same_object = "http://example.org/x"
    case = make_case([
        make_fact(["L1", "L0", "L0"], predicate=same_predicate,
                  direction="OUT", counterpart=same_object),
        make_fact(["L0", "L1", "L1"], predicate=same_predicate,
                  direction="IN", counterpart=same_object),
    ])
    size, _, ranked = rank_minimum_rationales(case, (0, 1, 2), "main-l1")
    best = ranked[0]
    assert size == 2                                    # neither fact alone suffices
    assert len(set(best.fact_identities)) == 2          # two distinct identities
    assert {i[1] for i in best.fact_identities} == {"IN", "OUT"}
    # Different kappa, so the pair is not redundant.
    assert best.redundant_predicate_direction_pairs == 0


def test_two_facts_sharing_one_predicate_direction_key_are_redundant():
    """The positive control for the test above: same kappa, different object."""
    predicate = "http://example.org/influences"
    case = make_case([
        make_fact(["L1", "L0", "L0"], predicate=predicate, direction="IN",
                  counterpart="http://example.org/x"),
        make_fact(["L0", "L1", "L1"], predicate=predicate, direction="IN",
                  counterpart="http://example.org/y"),
    ])
    _, _, ranked = rank_minimum_rationales(case, (0, 1, 2), "main-l1")
    assert ranked[0].redundant_predicate_direction_pairs == 1


def test_ineligible_facts_are_removed_before_any_ranking():
    """Eligibility is a hard filter decided upstream, never a soft penalty."""
    case = make_case([make_fact(["L1", "L1", "L1"], eligible=False,
                                counterpart="http://example.org/o1"),
                      make_fact(["L1", "L0", "L0"], counterpart="http://example.org/o2")])
    assert case.eligible_fact_indices == (1,)
    assert rank_minimum_rationales(case, (0, 1, 2), "main-l1") is None


# --------------------------------------------------------------------------
# 3. Local candidate-pool anonymity
# --------------------------------------------------------------------------


def test_local_anonymity_counts_the_answer_plus_supporters():
    case = make_case([make_fact(["NOT_COVERED", "NOT_COVERED", "L1"])])
    count, ratio, direct = local_pool_anonymity(case, [0])
    assert (count, direct) == (3, False)
    assert ratio == pytest.approx(3 / 4)
    case = make_case([make_fact(["L1", "L1", "L1"])])
    assert local_pool_anonymity(case, [0]) == (1, 0.25, True)


def test_local_anonymity_of_a_set_intersects_supporter_sets():
    case = make_case([make_fact(["NOT_COVERED", "NOT_COVERED", "L1"],
                                counterpart="http://example.org/o1"),
                      make_fact(["NOT_COVERED", "L1", "L1"],
                                counterpart="http://example.org/o2")])
    assert local_pool_anonymity(case, [0, 1])[0] == 2     # the Answer plus candidate 0


def test_direct_identifier_flag_orders_but_never_filters():
    """It is the 13th of 14 ranking fields; it removes no rationale."""
    case = make_case([make_fact(["L1", "L1", "L1"])])
    selection = select_distractors(case)
    # The only available rationale is a direct identifier, and it is selected.
    assert selection.rationale.direct_identifier_flag is True
    assert selection.minimum_rationale_size == 1
    # It sits at field 13, after the whole evidence profile and every quality field.
    assert selection.rationale.ranking_key[12] == 1


# --------------------------------------------------------------------------
# 4. The frozen Prompt-8F-R1 pilot input
# --------------------------------------------------------------------------


def load_pilot_cases():
    """Rebuild every pilot AnswerCase from the frozen, ALREADY-CLASSIFIED records.

    Phase A never decides an evidence level. This loader only copies the levels
    the R1 pipeline already wrote out, plus the per-fact quality fields and the
    frozen Prompt-8D LRoleSim rank and score. No triple is read, no semantic
    index is consulted, and no similarity is recomputed.
    """
    ranking = {}
    for line in HANDOFF.read_text("utf-8").splitlines():
        row = json.loads(line)
        ranking[row["answer_uri"]] = row

    grouped: dict[str, list[dict]] = {}
    for line in (R1_DIR / "evidence_audit_v3_r1.jsonl").read_text("utf-8").splitlines():
        record = json.loads(line)
        if record["record_type"] == "answer_fact_evidence":
            grouped.setdefault(record["answer_uri"], []).append(record)

    cases = {}
    for answer_uri, records in grouped.items():
        records.sort(key=lambda r: r["fact_index"])
        row = ranking[answer_uri]
        candidates = [Candidate(rank=c["rank"], score=c["score"],
                                uri=c["canonical_candidate_uri"])
                      for c in sorted(row["ranked_candidates"], key=lambda c: c["rank"])]
        order = [c.uri for c in candidates]
        facts = []
        for record in records:
            per = {c["candidate_uri"]: c for c in record["per_candidate"]}
            quality = record["quality"]
            facts.append(AnswerFact(
                quality=FactQuality(
                    predicate_uri=quality["predicate_uri"],
                    direction=quality["direction"],
                    counterpart_uri=quality["counterpart_uri"],
                    display_label=quality["display_label"],
                    eligible=quality["eligible"], soft_leak=quality["soft_leak"],
                    verbalizable=quality["verbalizable"],
                    pedagogical_tier=quality["pedagogical_tier"],
                    label_length=quality["label_length"],
                    token_count=quality["token_count"],
                    template_id=quality["template_id"]),
                levels=tuple(per[uri]["evidence_level"] for uri in order),
                exclusion_bases=tuple(per[uri]["exclusion_basis"] for uri in order),
                granularity_risks=tuple(per[uri]["granularity_risk"] for uri in order)))
        cases[answer_uri] = build_case(answer_uri, row["display_label"], candidates, facts)
    return cases


def load_oracle():
    """``selected_mcqs_v3_r1.jsonl`` is used ONLY as the regression oracle."""
    return [json.loads(line) for line
            in (R1_DIR / "selected_mcqs_v3_r1.jsonl").read_text("utf-8").splitlines()]


@pytest.fixture(scope="module")
def pilot_cases():
    return load_pilot_cases()


@pytest.fixture(scope="module")
def pilot_selections(pilot_cases):
    return {uri: select_distractors(case) for uri, case in pilot_cases.items()}


@pytest.fixture(scope="module")
def oracle():
    return load_oracle()


def render_facts(identities):
    """The canonical rendering used by the published regression CSV."""
    return " ; ".join(f"{p} {d} -> {o}" for p, d, o in sorted(identities))


def oracle_identities(record):
    return [(f["predicate_uri"], f["direction"], f["claim_object_uri"])
            for f in record["selected_rationale"]]


# --------------------------------------------------------------------------
# 5. The Eisaku Satō regression
# --------------------------------------------------------------------------


def test_sato_has_twenty_four_candidates(pilot_cases):
    assert len(pilot_cases[SATO].candidates) == 24


def test_sato_enumerates_2024_combinations(pilot_selections):
    """C(24, 3) = 2024, every one of them, FULL_EXACT."""
    assert pilot_selections[SATO].enumerated_combination_count == 2024


def test_sato_provisional_top_three_is_infeasible_at_main_l1(pilot_cases):
    """Ranks 2 and 3 have zero L1-covering eligible facts, so no cover exists."""
    case = pilot_cases[SATO]
    for position in (1, 2):                              # LRoleSim ranks 2 and 3
        covering = [i for i in case.eligible_fact_indices
                    if coverage_mask(case.facts[i], (position,), "L1")]
        assert covering == []
    # An empty bitset cannot be covered by any subset of facts, of any size.
    assert minimum_cover_size(case_masks(case, (0, 1, 2), "L1")) == K_DISTRACTORS + 1
    assert rank_minimum_rationales(case, (0, 1, 2), "main-l1") is None
    # The same triple IS feasible once absence is allowed to count, which is
    # exactly why the diagnostic policy may never be reported as main-corpus.
    assert rank_minimum_rationales(case, (0, 1, 2), "diagnostic-l0")[0] == 1


def test_sato_selects_ranks_one_five_six(pilot_selections):
    selection = pilot_selections[SATO]
    assert selection.evidence_policy == "main-l1"
    assert [d.rank for d in selection.distractors] == [1, 5, 6]
    assert [d.uri for d in selection.distractors] == [
        "http://dbpedia.org/resource/Ei-ichi_Negishi",
        "http://dbpedia.org/resource/Hideki_Shirakawa",
        "http://dbpedia.org/resource/Isamu_Akasaki",
    ]
    assert selection.feasible_combination_count == 680


def test_sato_rationale_fact_masks_and_their_union(pilot_cases, pilot_selections):
    """almaMater OUT -> 0b110, before IN -> 0b001, OR = 0b111.

    The two facts are exactly complementary: almaMater cannot reach Ei-ichi
    Negishi because he shares the Answer's value (NOT_COVERED), and before
    cannot reach Shirakawa or Akasaki because the snapshot records nothing for
    them under that key (L0). Neither alone suffices; together they suffice
    with nothing to spare. Note that ``before`` is an IN fact and ``almaMater``
    an OUT fact — merging the directions would destroy this rationale.
    """
    case, selection = pilot_cases[SATO], pilot_selections[SATO]
    masks = {case.facts[index].quality.identity: mask
             for index, mask in zip(selection.rationale.fact_indices,
                                    selection.rationale.coverage_masks)}
    assert masks[ALMA_MATER] == 0b110
    assert masks[BEFORE] == 0b001
    assert masks[ALMA_MATER] | masks[BEFORE] == 0b111
    assert selection.rationale.coverage_mask == 0b111


def test_sato_has_no_one_fact_main_l1_rationale(pilot_cases, pilot_selections):
    """Exhaustive over all 55 eligible facts, not a heuristic or a cut-off."""
    case, selection = pilot_cases[SATO], pilot_selections[SATO]
    assert len(case.eligible_fact_indices) == 55
    achievable = {coverage_mask(case.facts[i], selection.positions, "L1")
                  for i in case.eligible_fact_indices}
    assert 0b111 not in achievable
    assert achievable - {0} == {0b001, 0b110}


def test_sato_minimum_rationale_size_is_exactly_two(pilot_selections):
    selection = pilot_selections[SATO]
    assert selection.minimum_rationale_size == 2
    assert sorted(selection.rationale.fact_identities) == sorted([ALMA_MATER, BEFORE])


def test_sato_three_combinations_tie_through_objective_key_four(pilot_cases):
    """Ranks 1/5/6, 1/5/7 and 1/5/8 are identical on keys 1-4; key 5 decides."""
    case = pilot_cases[SATO]
    keys = []
    for third in (5, 6, 7):                     # positions of ranks 6, 7 and 8
        positions = (0, 4, third)
        size, _, ranked = rank_minimum_rationales(case, positions, "main-l1")
        keys.append(combination_objective_key(case, positions, size, ranked[0]))
    assert len({key[:4] for key in keys}) == 1               # keys 1-4 identical
    assert [key[4] for key in keys] == [12, 13, 14]          # key 5 separates them
    assert min(keys) == keys[0]                              # rank sum 12 wins


def test_sato_rank_sum_tiebreak_is_reached_and_decisive(pilot_selections):
    selection = pilot_selections[SATO]
    assert selection.combinations_tied_after_objective_key_4 == 3
    assert selection.candidate_rank_sum == 12


def test_sato_is_the_only_pilot_answer_reaching_key_five(pilot_selections):
    reached = {s.display_label for s in pilot_selections.values()
               if s.combinations_tied_after_objective_key_4 > 1}
    assert reached == {"Eisaku Satō"}


def test_sato_objective_values_match_the_trace(pilot_selections):
    selection = pilot_selections[SATO]
    assert selection.lrolesim_score_sum == 0.6372318131251465
    assert selection.lrolesim_score_min == 0.20696461464461466
    assert selection.rationale.ranking_key[:13] == (
        -2, 0, -3, 0, 0, 0, 0, 4, 1, 31, 5, 0, 1)


# --------------------------------------------------------------------------
# 6. The eight-pilot regression
# --------------------------------------------------------------------------


def test_all_eight_pilot_selections_are_reproduced(pilot_selections, oracle):
    """Policy, distractor URIs, distractor ranks, rationale set, |R*|."""
    assert len(oracle) == 8
    for record in oracle:
        selection = pilot_selections[record["answer_uri"]]
        assert selection is not None, record["display_label"]
        assert selection.evidence_policy == record["evidence_policy"]
        assert [d.uri for d in selection.distractors] == \
            [d["candidate_uri"] for d in record["distractors"]]
        assert [d.rank for d in selection.distractors] == \
            [d["original_lrolesim_rank"] for d in record["distractors"]]
        assert sorted(selection.rationale.fact_identities) == \
            sorted(oracle_identities(record))
        assert selection.minimum_rationale_size == record["minimum_rationale_size"]


def test_pilot_search_provenance_matches_the_oracle(pilot_selections, oracle):
    """The reported search sizes are re-derived, not copied."""
    for record in oracle:
        selection = pilot_selections[record["answer_uri"]]
        assert selection.enumerated_combination_count == \
            record["enumerated_combination_count"]
        assert selection.candidate_rank_sum == record["candidate_rank_sum"]
        assert selection.lrolesim_score_sum == record["lrolesim_score_sum"]
        assert selection.lrolesim_score_min == record["lrolesim_score_min"]
        assert selection.rationale.coverage_mask == record["coverage_mask"]
        assert selection.mcq_evidence_level == record["mcq_evidence_level"]
        assert selection.minimum_rationale_count_enumerated == \
            record["minimum_rationale_count_enumerated"]


def test_every_pilot_answer_reaches_mcq_l1(pilot_selections):
    for selection in pilot_selections.values():
        assert selection.evidence_policy == "main-l1"
        assert selection.rationale.rationale_min_level == "L1"


def test_no_l2_evidence_exists_anywhere_in_the_pilot(pilot_cases):
    """Zero is the correct offline outcome, not a gap: no proof source exists."""
    for case in pilot_cases.values():
        for fact in case.facts:
            assert "L2" not in fact.levels


def test_published_regression_csv_matches_the_kernel(pilot_selections, oracle):
    """The published CSV is verified against what the kernel actually produces."""
    rows = list(csv.DictReader(REGRESSION_CSV.read_text("utf-8").splitlines()))
    assert len(rows) == 8
    by_uri = {record["answer_uri"]: record for record in oracle}
    for row in rows:
        record = by_uri[row["answer_uri"]]
        selection = pilot_selections[row["answer_uri"]]
        assert row["display_label"] == record["display_label"]
        assert row["expected_policy"] == record["evidence_policy"]
        assert row["reproduced_policy"] == selection.evidence_policy
        assert row["expected_distractor_ranks"] == \
            "|".join(str(d["original_lrolesim_rank"]) for d in record["distractors"])
        assert row["reproduced_distractor_ranks"] == \
            "|".join(str(d.rank) for d in selection.distractors)
        assert row["expected_distractor_uris"] == \
            "|".join(d["candidate_uri"] for d in record["distractors"])
        assert row["reproduced_distractor_uris"] == \
            "|".join(d.uri for d in selection.distractors)
        assert row["expected_rationale_facts"] == render_facts(oracle_identities(record))
        assert row["reproduced_rationale_facts"] == \
            render_facts(selection.rationale.fact_identities)
        assert row["expected_minimum_rationale_size"] == \
            str(record["minimum_rationale_size"])
        assert row["reproduced_minimum_rationale_size"] == \
            str(selection.minimum_rationale_size)
        assert row["exact_match"] == "True"


# --------------------------------------------------------------------------
# 7. Determinism and safety
# --------------------------------------------------------------------------


def canonical_json(case, selection):
    return json.dumps(canonical_record(case, selection), sort_keys=True,
                      ensure_ascii=False)


def test_same_input_gives_byte_identical_canonical_output(oracle):
    """Two independent loads of the same frozen input must not disagree."""
    first, second = load_pilot_cases(), load_pilot_cases()
    for record in oracle:
        uri = record["answer_uri"]
        assert canonical_json(first[uri], select_distractors(first[uri])) == \
            canonical_json(second[uri], select_distractors(second[uri]))


def test_candidate_input_ordering_cannot_change_the_output(pilot_cases, oracle):
    """build_case() canonicalises, so the caller's ordering never leaks through."""
    for record in oracle[:3]:
        case = pilot_cases[record["answer_uri"]]
        order = list(range(len(case.candidates)))
        random.Random(7).shuffle(order)
        shuffled = build_case(
            case.answer_uri, case.display_label,
            [case.candidates[i] for i in order],
            [AnswerFact(quality=fact.quality,
                        levels=tuple(fact.levels[i] for i in order),
                        exclusion_bases=tuple(fact.exclusion_bases[i] for i in order),
                        granularity_risks=tuple(fact.granularity_risks[i] for i in order))
             for fact in case.facts])
        assert shuffled == case
        assert canonical_json(shuffled, select_distractors(shuffled)) == \
            canonical_json(case, select_distractors(case))


def test_selection_opens_no_socket(monkeypatch, pilot_cases):
    """A behavioural guard, not just an import check."""
    def refuse(*args, **kwargs):
        raise AssertionError("the selection kernel must not touch the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    for case in pilot_cases.values():
        assert select_distractors(case) is not None


def test_the_kernel_imports_nothing_beyond_a_tiny_stdlib_allowlist():
    """Covers network clients, NLP toolkits and LLM clients in one assertion."""
    allowed = {"__future__", "dataclasses", "itertools", "math", "typing"}
    tree = ast.parse(CORE_SOURCE.read_text("utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= allowed, sorted(imported - allowed)


def test_no_forbidden_module_is_named_in_the_kernel_source():
    """Explicit list, so a future edit that adds one fails loudly."""
    forbidden = ["requests", "urllib", "http.client", "socket", "SPARQLWrapper",
                 "rdflib", "spacy", "nltk", "wordnet", "gensim", "torch",
                 "transformers", "sentence_transformers", "sklearn", "openai",
                 "anthropic", "spec_freeze_audit", "rationale_v3"]
    text = CORE_SOURCE.read_text("utf-8")
    assert [name for name in forbidden if name in text] == []


def test_terminology_uses_the_authoritative_l1_name():
    """EVIDENCE_TAXONOMY_V1.md is authoritative; the superseded name is banned."""
    for path in (CORE_SOURCE,
                 ROOT / "docs" / "checks" / "MINIMAL_CORE_PHASE_A_WALKTHROUGH.md"):
        text = path.read_text("utf-8")
        assert "POSITIVE_VALUE_CONTRAST" not in text
        assert "positive contrast" not in text.lower()
        assert "L1_POSITIVE_ALTERNATIVE_OBSERVED" in text
        assert "observed alternative value" in text


def test_open_world_and_scope_caveats_travel_with_every_record(pilot_cases,
                                                               pilot_selections):
    for uri, selection in pilot_selections.items():
        record = canonical_record(pilot_cases[uri], selection)
        assert "not falsity" in record["open_world_note"]
        assert "not global uniqueness" in record["local_candidate_pool_anonymity_note"]
        assert "tie-break" in record["candidate_rank_sum_note"]
        assert "no rationale" in record["lrolesim_role_note"]
        assert record["search_scope"] == "FULL_EXACT"
