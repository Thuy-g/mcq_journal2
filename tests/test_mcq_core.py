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
  terminology guard;
* **the bounded candidate pool** (Phase A2) — the FULL_EXACT/POOL_EXACT
  boundary, evidence rescue below the LRoleSim cutoff, exactness *inside* the
  bounded pool checked against brute force, the anonymity denominator staying
  on the COMPLETE ranked candidate pool, and the published pool ablation.

Nothing here imports ``scripts/spec_freeze_audit.py``, ``src.rationale_v3`` or
``src.rationale``. The kernel is checked on its own terms. No network, no
pinned-KG load: every input is a frozen file under ``outputs/``.
"""

from __future__ import annotations

import ast
import csv
import itertools
import json
import math
import random
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcq_core import (  # noqa: E402
    DEFAULT_POOL_POLICY,
    K_DISTRACTORS,
    LEVEL_STRENGTH,
    MAX_EXACT_COMBINATIONS,
    MAX_POOL_SIZE,
    POLICY_ORDER,
    POOL_EVIDENCE_RESCUE,
    POOL_POLICY_NAME,
    POOL_TOP_BY_LROLESIM,
    SEARCH_FULL_EXACT,
    SEARCH_POOL_EXACT,
    AnswerFact,
    Candidate,
    FactQuality,
    PoolPolicy,
    build_candidate_pool,
    build_case,
    candidate_rescue_key,
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
ABLATION_CSV = ROOT / "docs" / "checks" / "MINIMAL_CORE_PHASE_A2_POOL_ABLATION.csv"
A2_WALKTHROUGH = ROOT / "docs" / "checks" / "MINIMAL_CORE_PHASE_A2_POOL_WALKTHROUGH.md"
ABLATION_POOL_SIZES = (25, 50, 75, 100)

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
                 ROOT / "docs" / "checks" / "MINIMAL_CORE_PHASE_A_WALKTHROUGH.md",
                 A2_WALKTHROUGH):
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


# --------------------------------------------------------------------------
# 8. Phase A2 — the bounded candidate pool
# --------------------------------------------------------------------------
#
# Everything below concerns WHICH candidates the exact search ranges over. None
# of it touches how a combination is scored once chosen: the set-cover DP, the
# evidence thresholds, the fourteen-field rationale key and the six-key
# objective are the Phase A ones, tested unchanged in sections 1-7 above.


def uniform_case(levels_by_candidate, **fact_kwargs):
    """A one-fact case whose single fact carries the given per-candidate levels."""
    return make_case([make_fact(list(levels_by_candidate), **fact_kwargs)])


def shuffled_case(case, seed):
    """The same information presented in a different caller-side order."""
    order = list(range(len(case.candidates)))
    random.Random(seed).shuffle(order)
    return build_case(
        case.answer_uri, case.display_label,
        [case.candidates[i] for i in order],
        [AnswerFact(quality=fact.quality,
                    levels=tuple(fact.levels[i] for i in order),
                    exclusion_bases=tuple(fact.exclusion_bases[i] for i in order),
                    granularity_risks=tuple(fact.granularity_risks[i] for i in order))
         for fact in case.facts])


def rescue_case(n=60, evidence_positions=(57, 58, 59)):
    """The adversarial shape that justifies evidence rescue.

    Every high-ranked candidate SHARES the Answer's proposition, so it is
    NOT_COVERED and carries no usable evidence whatsoever. Only three deeply
    low-ranked candidates have an observed alternative value. A pool built from
    the LRoleSim ranking alone therefore contains no feasible triple at all.
    """
    levels = ["NOT_COVERED"] * n
    for position in evidence_positions:
        levels[position] = "L1"
    return uniform_case(levels)


# --- A. the defaults, and FULL_EXACT preservation on the pilot ---------------


def test_pool_defaults_are_the_inherited_frozen_values():
    """These are R1's numbers. A silent change here would change the method."""
    assert MAX_EXACT_COMBINATIONS == 200_000
    assert (POOL_TOP_BY_LROLESIM, POOL_EVIDENCE_RESCUE, MAX_POOL_SIZE) == (75, 25, 100)
    assert POOL_POLICY_NAME == "top_lrolesim_plus_evidence_rescue_v1"
    assert DEFAULT_POOL_POLICY == PoolPolicy()
    assert POOL_TOP_BY_LROLESIM + POOL_EVIDENCE_RESCUE == MAX_POOL_SIZE
    # A 100-candidate pool is 161,700 triples, every one of which is enumerated.
    assert math.comb(MAX_POOL_SIZE, K_DISTRACTORS) == 161_700


def test_all_eight_pilot_answers_stay_full_exact_under_the_default_policy(
        pilot_cases, pilot_selections):
    """Acceptance gate 2: the default pilot search scope does not move."""
    for uri, selection in pilot_selections.items():
        pool = selection.pool
        n = len(pilot_cases[uri].candidates)
        assert pool.scope == SEARCH_FULL_EXACT
        assert pool.global_optimality_claim is True
        assert pool.pool_optimality_claim is True
        assert pool.original_combination_count <= MAX_EXACT_COMBINATIONS
        # The complete candidate count IS the search pool count.
        assert pool.original_candidate_count == len(pool.positions) == n
        assert pool.positions == tuple(range(n))
        assert pool.enumerated_combination_count == pool.original_combination_count
        assert pool.enumerated_combination_count == math.comb(n, K_DISTRACTORS)
        # Nothing is rescued when nothing was excluded.
        assert pool.rescued_positions == ()


def test_full_exact_records_publish_every_required_provenance_field(
        pilot_cases, pilot_selections):
    """The scope block travels with the record, not with a separate report."""
    required = {
        "search_scope", "pool_policy", "original_candidate_count",
        "pool_candidate_count", "original_combination_count",
        "enumerated_combination_count", "pool_top_by_lrolesim",
        "pool_evidence_rescue_limit", "evidence_rescue_count",
        "evidence_rescued_candidate_ranks", "evidence_rescued_candidate_uris",
        "max_pool_size", "max_exact_combinations", "global_optimality_claim",
        "pool_optimality_claim",
    }
    for uri, selection in pilot_selections.items():
        record = canonical_record(pilot_cases[uri], selection)
        assert required <= set(record), sorted(required - set(record))
        assert record["search_scope"] == SEARCH_FULL_EXACT
        assert record["global_optimality_claim"] is True
        assert record["pool_optimality_claim"] is True
        assert record["evidence_rescue_count"] == 0
        assert record["evidence_rescued_candidate_ranks"] == []
        assert record["evidence_rescued_candidate_uris"] == []
        assert record["pool_candidate_count"] == record["original_candidate_count"]
        assert record["pool_policy"] == POOL_POLICY_NAME
        assert "exact over the complete ranked candidate pool" in \
            record["search_scope_note"]


def test_forcing_the_default_pool_on_the_pilot_changes_only_the_claim(pilot_cases,
                                                                      pilot_selections):
    """M = 100 covers every pilot class whole, so the science must not move.

    What DOES move is the claim: the same triple, the same rationale and the
    same objective values are now exact only within the bounded pool, so
    ``global_optimality_claim`` drops to False even though the bounded pool
    happens to contain everything. The kernel reports the scope it searched
    under, not the scope it could have got away with.
    """
    for uri, case in pilot_cases.items():
        reference = pilot_selections[uri]
        forced = select_distractors(case, pool_policy=PoolPolicy.for_pool_size(100),
                                    force_pool=True)
        assert forced.pool.scope == SEARCH_POOL_EXACT
        assert forced.pool.global_optimality_claim is False
        assert forced.pool.pool_optimality_claim is True
        assert len(forced.pool.positions) == len(case.candidates)
        assert forced.positions == reference.positions
        assert forced.evidence_policy == reference.evidence_policy
        assert forced.rationale.fact_identities == reference.rationale.fact_identities
        assert forced.minimum_rationale_size == reference.minimum_rationale_size


# --- B. the FULL_EXACT / POOL_EXACT boundary ---------------------------------


def test_the_scope_boundary_sits_exactly_where_the_combination_budget_runs_out():
    """Derived from C(n, 3), not hard-coded: the last n that fits, and the next.

    C(107, 3) = 198,485 <= 200,000 < 204,156 = C(108, 3), so 107 candidates is
    the largest class the kernel still searches exhaustively over the complete
    ranked pool.
    """
    limit = DEFAULT_POOL_POLICY.max_exact_combinations
    last_fitting = max(n for n in range(K_DISTRACTORS, 500)
                       if math.comb(n, K_DISTRACTORS) <= limit)
    assert (last_fitting, math.comb(last_fitting, K_DISTRACTORS)) == (107, 198_485)
    assert math.comb(last_fitting + 1, K_DISTRACTORS) == 204_156 > limit

    at_limit = build_candidate_pool(uniform_case(["L1"] * last_fitting))
    over_limit = build_candidate_pool(uniform_case(["L1"] * (last_fitting + 1)))
    assert at_limit.scope == SEARCH_FULL_EXACT
    assert at_limit.enumerated_combination_count == 198_485
    assert over_limit.scope == SEARCH_POOL_EXACT
    assert over_limit.original_combination_count == 204_156
    assert len(over_limit.positions) <= MAX_POOL_SIZE


def test_a_case_smaller_than_k_yields_no_selection():
    """Two candidates cannot make a triple, in either scope."""
    tiny = uniform_case(["L1", "L1"])
    assert build_candidate_pool(tiny).original_combination_count == 0
    assert select_distractors(tiny) is None


# --- C. a large synthetic class ----------------------------------------------


def thousand_candidate_case(n=1000, facts=4):
    """A deterministic already-classified case with ``n`` candidates.

    Candidate i supports the Answer's proposition number ``i % facts`` and has
    an observed alternative value for the rest, so coverage is non-uniform and
    no single fact covers everybody.
    """
    return make_case([
        make_fact(["NOT_COVERED" if i % facts == f else "L1" for i in range(n)],
                  counterpart=f"http://example.org/o{f}")
        for f in range(facts)])


def test_a_thousand_candidates_switch_to_pool_exact_automatically():
    """Acceptance gates 3, 5 and 6, on a class no exhaustive search could take."""
    case = thousand_candidate_case()
    selection = select_distractors(case)
    pool = selection.pool

    assert pool.original_candidate_count == 1000
    assert pool.original_combination_count == math.comb(1000, 3) == 166_167_000
    assert pool.scope == SEARCH_POOL_EXACT
    assert len(pool.positions) <= MAX_POOL_SIZE
    assert pool.enumerated_combination_count <= math.comb(MAX_POOL_SIZE, 3)
    assert pool.global_optimality_claim is False
    assert pool.pool_optimality_claim is True
    # Every triple inside the pool was enumerated, and only those.
    assert pool.enumerated_combination_count == \
        math.comb(len(pool.positions), K_DISTRACTORS)
    assert selection.feasible_combination_count <= pool.enumerated_combination_count
    # Three orders of magnitude fewer combinations than the complete space.
    assert pool.enumerated_combination_count < pool.original_combination_count / 1000
    assert selection.candidate_count == 1000        # the COMPLETE pool, reported


def test_the_pool_record_says_plainly_that_it_is_not_a_global_optimum():
    """Acceptance gate 6, in the words that reach the paper.

    The three phrases the specification forbids for a POOL_EXACT result may
    appear only inside an explicit negation, so the guard checks the negation
    rather than the absence of the phrase.
    """
    case = thousand_candidate_case()
    record = canonical_record(case, select_distractors(case))
    note = record["search_scope_note"]
    assert record["global_optimality_claim"] is False
    assert record["pool_optimality_claim"] is True
    assert "exact within the bounded candidate pool" in note
    assert "No optimality claim is made over candidates excluded from the pool" in note
    for phrase in ("globally optimal", "global optimum", "exact over all candidates"):
        for start in range(len(note)):
            if note.startswith(phrase, start):
                assert "NOT" in note[max(0, start - 10):start], phrase
    assert "pool-construction heuristic" in record["evidence_rescue_note"]
    assert "no part of the six-key" in record["evidence_rescue_note"]


# --- D. evidence rescue below the LRoleSim cutoff ----------------------------


def test_a_low_ranked_evidence_bearing_candidate_is_rescued():
    """Acceptance gate 4, and the central justification for the rescue slots.

    Ranks 1-20 all share the Answer's proposition and carry nothing usable. The
    only three candidates with an observed alternative value sit at ranks 58,
    59 and 60, far below any plausible LRoleSim cutoff.
    """
    case = rescue_case()
    policy = PoolPolicy(max_exact_combinations=10, top_by_lrolesim=20,
                        evidence_rescue=5, max_pool_size=25)
    pool = build_candidate_pool(case, policy=policy)

    assert pool.scope == SEARCH_POOL_EXACT
    for position in (57, 58, 59):
        assert position in pool.positions, "the evidence-bearing candidate was dropped"
        assert position in pool.rescued_positions
    # The rescue key put the three evidence-bearing candidates first; the two
    # remaining slots went to the best-ranked of the evidence-free remainder.
    assert pool.rescued_positions == (20, 21, 57, 58, 59)
    assert len(pool.positions) == 25 <= policy.max_pool_size


def test_a_top_only_pool_loses_the_evidence_and_produces_no_item_at_all():
    """The counterfactual: same case, same pool size, rescue slots removed.

    This is the scientific point of the mechanism. Without rescue the bounded
    search reports an infeasibility the complete search does not have — not a
    slightly worse item, no item.
    """
    case = rescue_case()
    with_rescue = PoolPolicy(max_exact_combinations=10, top_by_lrolesim=20,
                             evidence_rescue=5, max_pool_size=25)
    top_only = PoolPolicy(max_exact_combinations=10, top_by_lrolesim=25,
                          evidence_rescue=0, max_pool_size=25)

    starved = build_candidate_pool(case, policy=top_only)
    assert starved.positions == tuple(range(25))
    assert starved.rescued_positions == ()
    for position in (57, 58, 59):
        assert position not in starved.positions
    assert select_distractors(case, pool_policy=top_only, force_pool=True) is None

    rescued = select_distractors(case, pool_policy=with_rescue, force_pool=True)
    assert rescued is not None
    assert rescued.positions == (57, 58, 59)
    assert rescued.evidence_policy == "main-l1"
    assert rescued.minimum_rationale_size == 1
    # And the complete FULL_EXACT search agrees, which is what makes the
    # rescued pool the right bounded approximation here rather than a lucky one.
    assert select_distractors(case).positions == (57, 58, 59)


def test_the_rescue_key_is_candidate_local_and_orders_evidence_first():
    """It reads one candidate at a time; no pair and no triple is inspected."""
    case = rescue_case()
    with_evidence = candidate_rescue_key(case, 59)
    without = candidate_rescue_key(case, 30)
    assert with_evidence < without                      # L1 beats NOT_COVERED
    assert with_evidence[:3] == (-LEVEL_STRENGTH["L1"], 0, -1)
    assert without[0] == -LEVEL_STRENGTH["NOT_COVERED"] == 0
    # Two evidence-free candidates differ only by the rank and URI tie-breaks.
    assert candidate_rescue_key(case, 30)[:6] == candidate_rescue_key(case, 31)[:6]
    assert candidate_rescue_key(case, 30)[6:] == (31, "http://example.org/c30")


def test_l1_bearing_candidates_outrank_l0_only_candidates_for_rescue():
    """L0 may be observed, but it must never outrank an observed alternative."""
    levels = ["NOT_COVERED"] * 40
    levels[30] = "L0"
    levels[35] = "L1"
    case = uniform_case(levels)
    assert candidate_rescue_key(case, 35) < candidate_rescue_key(case, 30)
    assert candidate_rescue_key(case, 30) < candidate_rescue_key(case, 31)
    policy = PoolPolicy(max_exact_combinations=1, top_by_lrolesim=10,
                        evidence_rescue=2, max_pool_size=12)
    assert build_candidate_pool(case, policy=policy).rescued_positions == (30, 35)


def test_not_covered_gives_no_rescue_coverage_at_all():
    """A candidate that supports every Answer proposition is rescued last."""
    case = rescue_case(n=40, evidence_positions=(39,))
    keys = [candidate_rescue_key(case, p) for p in range(40)]
    assert keys[39] == min(keys)
    assert all(key[0] == 0 for p, key in enumerate(keys) if p != 39)


# --- E. determinism ----------------------------------------------------------


def test_the_bounded_pool_is_immune_to_the_callers_candidate_ordering():
    """Rescue determinism: shuffle the input, get the identical canonical pool."""
    case = rescue_case()
    policy = PoolPolicy(max_exact_combinations=10, top_by_lrolesim=20,
                        evidence_rescue=5, max_pool_size=25)
    reference = build_candidate_pool(case, policy=policy)
    for seed in range(5):
        other = shuffled_case(case, seed)
        pool = build_candidate_pool(other, policy=policy)
        assert pool.positions == reference.positions
        assert pool.rescued_positions == reference.rescued_positions
        assert [other.candidates[p].uri for p in pool.rescued_positions] == \
            [case.candidates[p].uri for p in reference.rescued_positions]


def test_equal_rescue_keys_resolve_by_original_rank_then_by_canonical_uri():
    """The last two components exist so that two runs can never disagree."""
    # Same rank, same (empty) evidence: only the canonical URI can separate them.
    candidates = [Candidate(rank=1, score=0.9, uri="http://example.org/b"),
                  Candidate(rank=1, score=0.9, uri="http://example.org/a"),
                  Candidate(rank=2, score=0.8, uri="http://example.org/c"),
                  Candidate(rank=3, score=0.7, uri="http://example.org/d")]
    case = build_case("http://example.org/A", "A", candidates,
                      [make_fact(["NOT_COVERED"] * 4)])
    assert [c.uri for c in case.candidates] == ["http://example.org/a",
                                                "http://example.org/b",
                                                "http://example.org/c",
                                                "http://example.org/d"]
    keys = [candidate_rescue_key(case, p) for p in range(4)]
    assert keys[0][:6] == keys[1][:6] and keys[0][6] == keys[1][6] == 1
    assert keys[0] < keys[1]                       # ...a before ...b, by URI
    policy = PoolPolicy(max_exact_combinations=1, top_by_lrolesim=1,
                        evidence_rescue=2, max_pool_size=3)
    assert build_candidate_pool(case, policy=policy).rescued_positions == (1, 2)


# --- F. exactness INSIDE the bounded pool ------------------------------------


def mixed_case(seed, n=12, facts=5):
    """A deterministic already-classified case with varied evidence and quality."""
    rng = random.Random(seed)
    return make_case([
        make_fact([rng.choice(["NOT_COVERED", "L0", "L1", "L1"]) for _ in range(n)],
                  counterpart=f"http://example.org/o{f}",
                  tier=rng.randint(1, 4), label_length=rng.randint(3, 30),
                  tokens=rng.randint(1, 5), soft_leak=rng.random() < 0.2)
        for f in range(facts)])


def brute_force_best_combination(case, positions):
    """The winner over ``positions``, by independent exhaustive enumeration.

    Deliberately written the slow, obvious way — first feasible policy wins,
    then the smallest six-key objective tuple over every triple — so that it
    can disagree with the kernel if the kernel ever stops being exact.
    """
    for policy in POLICY_ORDER:
        scored = []
        for triple in itertools.combinations(positions, K_DISTRACTORS):
            ranked = rank_minimum_rationales(case, triple, policy)
            if ranked is None:
                continue
            size, _, rationales = ranked
            scored.append((combination_objective_key(case, triple, size, rationales[0]),
                           triple, rationales[0]))
        if scored:
            return (policy, *min(scored, key=lambda row: row[0])[1:])
    return None


@pytest.mark.parametrize("seed", range(12))
def test_the_kernel_is_exact_inside_its_bounded_pool(seed):
    """Acceptance gate 5. This checks POOL exactness, NOT global exactness.

    The forced pool of six candidates is deliberately smaller than the twelve
    available, so the brute-force reference enumerates the SAME bounded pool.
    Whether the pool contained the globally best triple is a different question
    and is not asserted here — that is precisely the claim POOL_EXACT declines
    to make.
    """
    case = mixed_case(seed)
    policy = PoolPolicy.for_pool_size(6)
    selection = select_distractors(case, pool_policy=policy, force_pool=True)
    pool = build_candidate_pool(case, policy=policy, force_pool=True)
    assert len(pool.positions) == 6 < len(case.candidates)

    expected = brute_force_best_combination(case, pool.positions)
    if expected is None:
        assert selection is None
        return
    policy_name, positions, rationale = expected
    assert selection is not None
    assert selection.evidence_policy == policy_name
    assert selection.positions == positions
    assert selection.rationale.fact_identities == rationale.fact_identities
    assert selection.pool.enumerated_combination_count == math.comb(6, K_DISTRACTORS)
    assert selection.feasible_combination_count <= math.comb(6, K_DISTRACTORS)


# --- G. the anonymity denominator stays on the COMPLETE ranked pool ----------


def test_anonymity_still_counts_candidates_outside_the_bounded_search_pool():
    """Acceptance gate 8. Search scope and anonymity scope are different things.

    Candidates 11 and 12 support the selected rationale's proposition and sit
    outside the bounded search pool. They must still be counted: shrinking the
    anonymity denominator to the search pool would make a bounded search look
    like a complete candidate class and would inflate every anonymity figure in
    the paper.
    """
    levels = ["L1"] * 10 + ["NOT_COVERED", "NOT_COVERED"]
    case = uniform_case(levels)
    policy = PoolPolicy.for_pool_size(6)
    selection = select_distractors(case, pool_policy=policy, force_pool=True)
    pool = selection.pool

    assert pool.scope == SEARCH_POOL_EXACT
    assert len(pool.positions) == 6 and len(case.candidates) == 12
    assert 10 not in pool.positions and 11 not in pool.positions

    rationale = selection.rationale
    assert rationale.local_candidate_pool_anonymity_count == 3      # Answer + 10 + 11
    assert rationale.local_candidate_pool_anonymity_ratio == pytest.approx(3 / 13)
    assert rationale.direct_identifier_flag is False
    # The denominator is 1 + the COMPLETE ranked pool, never 1 + the search pool.
    assert rationale.local_candidate_pool_anonymity_ratio != pytest.approx(3 / 7)
    # And the same numbers come out of the standalone function, over all 12.
    assert local_pool_anonymity(case, rationale.fact_indices) == \
        (3, 3 / 13, False)
    record = canonical_record(case, selection)
    assert record["local_candidate_pool_anonymity_count"] == 3
    assert record["original_candidate_count"] == 12
    assert record["pool_candidate_count"] == 6


# --- H. pool policy validation ------------------------------------------------


def test_for_pool_size_scales_the_inherited_three_to_one_split():
    for size, top, rescue in ((25, 19, 6), (50, 38, 12), (75, 57, 18), (100, 75, 25)):
        policy = PoolPolicy.for_pool_size(size)
        assert (policy.top_by_lrolesim, policy.evidence_rescue) == (top, rescue)
        assert policy.top_by_lrolesim == math.ceil(3 * size / 4)
        assert policy.top_by_lrolesim + policy.evidence_rescue == size
        assert policy.max_pool_size == size
        assert policy.name == f"{POOL_POLICY_NAME}_M{size}"
        assert policy.max_exact_combinations == MAX_EXACT_COMBINATIONS
    # M = 100 must reproduce the inherited default numbers exactly.
    default_sized = PoolPolicy.for_pool_size(MAX_POOL_SIZE)
    assert (default_sized.top_by_lrolesim, default_sized.evidence_rescue) == \
        (POOL_TOP_BY_LROLESIM, POOL_EVIDENCE_RESCUE)


@pytest.mark.parametrize("size", ABLATION_POOL_SIZES)
def test_a_bounded_pool_never_exceeds_its_configured_maximum(size):
    case = uniform_case(["L1"] * 500)
    pool = build_candidate_pool(case, policy=PoolPolicy.for_pool_size(size),
                                force_pool=True)
    assert len(pool.positions) == size
    assert len(pool.rescued_positions) <= PoolPolicy.for_pool_size(size).evidence_rescue
    assert pool.enumerated_combination_count == math.comb(size, K_DISTRACTORS)


@pytest.mark.parametrize("kwargs,message", [
    ({"top_by_lrolesim": 80, "evidence_rescue": 25, "max_pool_size": 100},
     "exceeds max_pool_size"),
    ({"top_by_lrolesim": -1}, "negative"),
    ({"evidence_rescue": -5}, "negative"),
    ({"max_pool_size": -1}, "negative"),
    ({"max_exact_combinations": -1}, "negative"),
    ({"top_by_lrolesim": 2, "evidence_rescue": 0, "max_pool_size": 2}, "below k"),
])
def test_an_incoherent_pool_policy_is_rejected_at_construction(kwargs, message):
    """A silently clamped policy would publish a search that never happened."""
    with pytest.raises(ValueError) as error:
        PoolPolicy(**kwargs)
    assert message in str(error.value)
    assert POOL_POLICY_NAME in str(error.value)


# --- I. the published pool ablation -------------------------------------------


def ablation_rows_from_the_kernel(cases, selections):
    """Recompute every row of the published ablation, from the kernel itself."""
    rows = []
    for uri in sorted(cases):
        case, reference = cases[uri], selections[uri]
        for size in ABLATION_POOL_SIZES:
            policy = PoolPolicy.for_pool_size(size)
            forced = select_distractors(case, pool_policy=policy, force_pool=True)
            pool = build_candidate_pool(case, policy=policy, force_pool=True)
            rows.append({
                "answer_uri": uri,
                "display_label": case.display_label,
                "reference_search_scope": reference.pool.scope,
                "original_candidate_count": str(len(case.candidates)),
                "forced_pool_size": str(size),
                "top_limit": str(policy.top_by_lrolesim),
                "rescue_limit": str(policy.evidence_rescue),
                "actual_pool_candidate_count": str(len(pool.positions)),
                "evidence_rescue_count": str(len(pool.rescued_positions)),
                "reference_policy": reference.evidence_policy,
                "pool_policy_reached": forced.evidence_policy,
                "reference_distractor_ranks":
                    "|".join(str(d.rank) for d in reference.distractors),
                "pool_distractor_ranks":
                    "|".join(str(d.rank) for d in forced.distractors),
                "reference_rationale_facts":
                    render_facts(reference.rationale.fact_identities),
                "pool_rationale_facts":
                    render_facts(forced.rationale.fact_identities),
                "same_distractor_selection":
                    str([d.uri for d in forced.distractors] ==
                        [d.uri for d in reference.distractors]),
                "same_rationale":
                    str(sorted(forced.rationale.fact_identities) ==
                        sorted(reference.rationale.fact_identities)),
                "same_policy":
                    str(forced.evidence_policy == reference.evidence_policy),
                "global_optimality_claim": str(forced.pool.global_optimality_claim),
                "pool_optimality_claim": str(forced.pool.pool_optimality_claim),
            })
    return rows


@pytest.fixture(scope="module")
def ablation(pilot_cases, pilot_selections):
    return ablation_rows_from_the_kernel(pilot_cases, pilot_selections)


def test_published_pool_ablation_csv_matches_the_kernel(ablation):
    """The published CSV is verified against what the kernel actually produces."""
    published = list(csv.DictReader(ABLATION_CSV.read_text("utf-8").splitlines()))
    assert len(published) == len(ablation) == 8 * len(ABLATION_POOL_SIZES)
    for row, expected in zip(published, ablation):
        assert row == expected, (row["display_label"], row["forced_pool_size"])


def test_every_forced_pool_size_reproduces_the_full_exact_pilot_selection(ablation):
    """On these eight Answers, no forced pool size changed the science.

    This is a PILOT DIAGNOSTIC on eight Answers whose classes hold 11 to 49
    candidates. It cannot validate M = 100 for the 100-Answer corpus, and the
    default is not chosen from it.
    """
    for row in ablation:
        assert row["reference_search_scope"] == SEARCH_FULL_EXACT
        assert row["same_distractor_selection"] == "True", row["display_label"]
        assert row["same_rationale"] == "True", row["display_label"]
        assert row["same_policy"] == "True", row["display_label"]
        # Every forced row is POOL_EXACT, so no forced row may claim globality.
        assert row["global_optimality_claim"] == "False"
        assert row["pool_optimality_claim"] == "True"
        assert int(row["actual_pool_candidate_count"]) <= int(row["forced_pool_size"])


def test_the_smallest_forced_pool_actually_bounds_the_larger_pilot_classes(ablation):
    """M = 25 is a real restriction for the three largest pilot classes."""
    bounded = {row["display_label"] for row in ablation
               if int(row["actual_pool_candidate_count"]) <
               int(row["original_candidate_count"])}
    assert bounded == {"Aristotle", "Plato", "Carbon"}
    for row in ablation:
        if row["display_label"] == "Carbon" and row["forced_pool_size"] == "25":
            assert (row["original_candidate_count"],
                    row["actual_pool_candidate_count"],
                    row["evidence_rescue_count"]) == ("49", "25", "6")
