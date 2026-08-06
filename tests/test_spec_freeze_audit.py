"""Tests for the Prompt-8G audit derivation script.

Two kinds of test live here:

  * unit tests on the exact combinatorial core (bitmask set cover, coverage
    masks, local anonymity) against brute force on synthetic tables, so the
    core is checked without depending on the pilot data;
  * oracle tests asserting that the independent re-derivation reproduces the
    frozen Prompt-8F-R1 selections, and that the specific numeric claims made
    in EISAKU_SATO_SELECTION_TRACE.md, PILOT_DIRECT_IDENTIFIER_AUDIT.md and
    RANK_SUM_EFFECT_AUDIT.md are the ones the data actually supports.

No network, no pinned-KG load. Every input is a frozen file under outputs/.
"""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from spec_freeze_audit import (  # noqa: E402
    AnswerTable, cover_size_table, derive, load, proper_name_signal,
)

R1_DIR = ROOT / "outputs" / "journal2_week2_rationale_v3_r1_2026-08-03"
HANDOFF = (ROOT / "outputs" / "journal2_week2_extract_integration_2026-07-30"
           / "candidate_ranking_handoff.jsonl")
SATO = "http://dbpedia.org/resource/Eisaku_Satō"


# --- the exact combinatorial core, against brute force ------------------------

def brute_force_cover(masks, k):
    """Smallest number of masks OR-ing to the full mask, by exhaustive search."""
    full = (1 << k) - 1
    distinct = sorted({m for m in masks if m})
    for size in range(0, len(distinct) + 1):
        for combo in itertools.combinations(distinct, size):
            covered = 0
            for mask in combo:
                covered |= mask
            if covered == full:
                return size
    return k + 1


@pytest.mark.parametrize("seed", range(60))
def test_cover_size_table_equals_brute_force(seed):
    rng = random.Random(seed)
    k = rng.choice([2, 3, 4])
    masks = [rng.randrange(0, 1 << k) for _ in range(rng.randint(0, 9))]
    full = (1 << k) - 1
    expected = brute_force_cover(masks, k)
    got = cover_size_table(masks, k)[full]
    assert got == min(expected, k + 1)


def test_cover_size_table_marks_unreachable_masks():
    # Two facts that never touch the third distractor cannot cover it.
    assert cover_size_table([0b001, 0b010], 3)[0b111] == 4
    assert cover_size_table([0b011, 0b100], 3)[0b111] == 2
    assert cover_size_table([0b111], 3)[0b111] == 1


def synthetic_table(levels_per_fact):
    """A minimal AnswerTable: levels_per_fact[f][c] is the level of fact f on c."""
    facts = []
    for index, levels in enumerate(levels_per_fact):
        facts.append({
            "levels": list(levels),
            "basis": ["NONE"] * len(levels),
            "risk": ["NONE"] * len(levels),
            "quality": {"eligible": True, "soft_leak": False,
                        "pedagogical_tier": 1, "verbalizable": True,
                        "label_length": 5, "token_count": 1,
                        "display_label": f"Object {index}",
                        "predicate_uri": f"p{index}", "direction": "OUT",
                        "counterpart_uri": f"o{index}", "template_id": "T"}})
    candidates = [{"rank": i + 1, "score": 1.0 - i / 100, "uri": f"c{i}"}
                  for i in range(len(levels_per_fact[0]))]
    return AnswerTable("a", "A", facts, candidates)


def test_fact_mask_bits_follow_the_combination_order():
    table = synthetic_table([["L1", "L0", "L1"]])
    # Bit i tracks positions[i], so reordering the combination reorders the bits.
    assert table.fact_mask(0, (0, 1, 2), "L1") == 0b101
    assert table.fact_mask(0, (2, 1, 0), "L1") == 0b101
    assert table.fact_mask(0, (1, 0, 2), "L1") == 0b110
    # At the diagnostic-L0 threshold the same fact covers everybody.
    assert table.fact_mask(0, (0, 1, 2), "L0") == 0b111


def test_not_covered_never_covers_at_any_threshold():
    table = synthetic_table([["NOT_COVERED", "NOT_COVERED", "L1"]])
    assert table.fact_mask(0, (0, 1, 2), "L0") == 0b100


def test_ineligible_facts_are_filtered_before_ranking():
    table = synthetic_table([["L1", "L1", "L1"], ["L1", "L1", "L1"]])
    table.facts[0]["quality"]["eligible"] = False
    table.eligible = [i for i, f in enumerate(table.facts)
                      if f["quality"]["eligible"]]
    assert table.eligible == [1]


def test_local_anonymity_counts_the_answer_plus_supporters():
    # Two candidates SUPPORT the proposition (NOT_COVERED), so |S_local| = 3.
    table = synthetic_table([["NOT_COVERED", "NOT_COVERED", "L1"]])
    count, ratio, direct = table.local_anonymity([0])
    assert (count, direct) == (3, False)
    assert ratio == pytest.approx(3 / 4)
    # A fact no candidate supports leaves the Answer alone in the local pool.
    table = synthetic_table([["L1", "L1", "L1"]])
    assert table.local_anonymity([0]) == (1, 0.25, True)


def test_local_anonymity_of_a_set_intersects_supporters():
    table = synthetic_table([["NOT_COVERED", "NOT_COVERED", "L1"],
                             ["NOT_COVERED", "L1", "L1"]])
    assert table.local_anonymity([0, 1])[0] == 2   # the Answer plus candidate 0


def test_proper_name_signal_is_deliberately_weak():
    assert proper_name_signal("Kiichi Aichi") == "MULTI_TOKEN_PROPER_NAME"
    assert proper_name_signal("University of Tokyo") == "MULTI_TOKEN_PROPER_NAME"
    # DBpedia capitalises every resource, so one token can never be resolved.
    assert proper_name_signal("Diamond") == "SINGLE_TOKEN_CAPITALIZED_AMBIGUOUS"
    assert proper_name_signal("Tokyo") == "SINGLE_TOKEN_CAPITALIZED_AMBIGUOUS"


# --- oracle tests against the frozen R1 artefacts -----------------------------

@pytest.fixture(scope="module")
def rows():
    tables = load(R1_DIR / "evidence_audit_v3_r1.jsonl", HANDOFF)
    return derive(tables, R1_DIR / "selected_mcqs_v3_r1.jsonl")


def test_rederivation_reproduces_every_r1_selection(rows):
    """The audits are only trustworthy if this passes for all eight Answers."""
    assert len(rows) == 8
    failed = [r["table"].label for r in rows if not r["reproduced"]]
    assert failed == []


def test_sato_ranks_two_and_three_have_no_l1_covering_fact(rows):
    """The exact reason the provisional LRoleSim top three is not feasible."""
    row = next(r for r in rows if r["table"].answer_uri == SATO)
    table = row["table"]
    for position in (1, 2):                      # LRoleSim ranks 2 and 3
        covering = [i for i in table.eligible
                    if table.fact_mask(i, (position,), "L1")]
        assert covering == []


def test_sato_selected_combination_masks_or_to_full_coverage(rows):
    row = next(r for r in rows if r["table"].answer_uri == SATO)
    table, best = row["table"], row["best"]
    assert best["ranks"] == [1, 5, 6]
    masks = sorted(table.fact_mask(i, best["positions"], "L1")
                   for i in best["ranking"]["best"]["indices"])
    assert masks == [0b001, 0b110]
    covered = 0
    for mask in masks:
        covered |= mask
    assert covered == 0b111


def test_sato_has_no_one_fact_main_l1_rationale(rows):
    """Exhaustive over all 55 eligible facts, not a heuristic."""
    row = next(r for r in rows if r["table"].answer_uri == SATO)
    table, best = row["table"], row["best"]
    nonzero = {table.fact_mask(i, best["positions"], "L1") for i in table.eligible}
    assert 0b111 not in nonzero
    assert nonzero - {0} == {0b001, 0b110}
    assert best["ranking"]["size"] == 2


def test_sato_is_the_only_answer_reaching_the_rank_sum_tiebreak(rows):
    reached = {r["table"].label for r in rows if len(r["tied"]) > 1}
    assert reached == {"Eisaku Satō"}
    row = next(r for r in rows if r["table"].answer_uri == SATO)
    assert sorted(c["rank_sum"] for c in row["tied"]) == [12, 13, 14]


def test_removing_rank_sum_changes_no_pilot_selection(rows):
    """True in this pilot only because key 6 happens to agree. Not a guarantee."""
    changed = [r["table"].label for r in rows
               if list(r["best"]["uris"]) != list(r["without"]["uris"])]
    assert changed == []


def test_direct_identifier_split_is_six_unique_two_shared(rows):
    unique, shared = [], []
    for row in rows:
        indices = row["best"]["ranking"]["best"]["indices"]
        _, _, direct = row["table"].local_anonymity(indices)
        (unique if direct else shared).append(row["table"].label)
    assert len(unique) == 6
    assert sorted(shared) == ["Plato", "Shin'ichirō Tomonaga"]


def test_carbon_never_selects_carbonado(rows):
    """The Answer-label leakage filter must stay deterministic."""
    row = next(r for r in rows if r["table"].label == "Carbon")
    text = " ".join(row["best"]["uris"]) + " " + " ".join(
        row["table"].facts[i]["quality"]["counterpart_uri"]
        for i in row["best"]["ranking"]["best"]["indices"])
    assert "Carbonado" not in text


def test_no_selected_rationale_carries_a_url_or_web_archive_object(rows):
    for row in rows:
        for index in row["best"]["ranking"]["best"]["indices"]:
            quality = row["table"].facts[index]["quality"]
            assert quality["predicate_uri"] != "http://dbpedia.org/property/url"
            assert "web.archive" not in quality["counterpart_uri"]


def test_every_pilot_answer_reaches_mcq_l1(rows):
    for row in rows:
        assert row["policy"] == "main-l1"
        assert min(row["best"]["ranking"]["best"]["per_candidate"],
                   key=lambda level: {"NOT_COVERED": 0, "L0": 1, "L1": 2,
                                      "L2": 3}[level]) == "L1"


def test_no_l2_evidence_exists_anywhere_in_the_pilot(rows):
    """Zero is the correct outcome offline, not a gap: no proof source exists."""
    for row in rows:
        for fact in row["table"].facts:
            assert "L2" not in fact["levels"]
