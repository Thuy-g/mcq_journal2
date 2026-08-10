"""Tests for the frozen-record ``AnswerCase`` adapter, ``src/mcq_inputs.py``.

Phase B1 step 1 has exactly one acceptance gate: **all eight R1-ready pilot
Answers must be reproduced through production code**, not through the test-only
reader that has been carrying the regression so far. Everything else here exists
to make sure the adapter reached that result by *reading* frozen records rather
than by repairing, defaulting or inventing them.

Five groups:

* **the eight-pilot regression** — policy, distractor URIs, distractor ranks,
  selected rationale fact set and |R*| against ``selected_mcqs_v3_r1.jsonl``,
  which is used ONLY as an oracle and never as input;
* **adapter equivalence** — the production reader and the test-only
  ``load_pilot_cases()`` produce identical ``AnswerCase`` objects. The import
  direction is one-way: this test module may read the reference reader, and
  ``src/mcq_inputs.py`` must never import a test module;
* **the nine input invariants** of ``docs/context/PHASE_B_INPUT_CONTRACT.md`` §7,
  each with at least one failing case, including the two forbidden level/basis
  combinations and the ranker-substitution guard. No silent repair anywhere;
* **determinism and the frozen kernel** — two independent runs are byte
  identical, and ``src/mcq_core.py`` is unchanged;
* **Albert Einstein is not fabricated** — an Answer the frozen runs never
  processed produces a clear failure, never a synthetic case.

Phase B1 step 2 adds a sixth group, ``B1.2-T1`` … ``B1.2-T11`` at the end of this
file: the Answer's own one-hop facts, reconstructed from the **pinned local KG**
and given the frozen R1 quality/leakage fields.

WHY THE B1.2 GROUP LOADS THE REAL 1.2 GB GRAPH BY DEFAULT
---------------------------------------------------------
``tests/test_kg_loader.py`` gates its one real-graph test behind
``MCQ_JOURNAL2_LOAD_REAL_KG=1``, because there the load is a bonus check on a
loader whose behaviour is already covered by small synthetic fixtures. Here it is
the opposite: the acceptance gate of B1.2 *is* the measurement on the pinned
snapshot — 9 OUT, 57 IN, 66 distinct facts, 60 counterparts, 48 eligible, 17
eligible κ, 41 eligible with a template — and a synthetic graph could reproduce
none of it. A gate that skips by default is not a gate, so this group runs by
default and is skipped only when the pinned file is absent or when
``MCQ_JOURNAL2_SKIP_REAL_KG=1`` is set explicitly.

The cost is real and is paid once: the graph is loaded by a single module-scoped
fixture (about 75 s and about 12 GB RSS on the development machine), every B1.2
test reads that one object, and ``B1.2-T9`` asserts the load count is exactly 1.

Still no network and no model. Apart from that single pinned-graph read, every
input is a frozen file under ``outputs/``.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import json
import os
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from mcq_core import (  # noqa: E402
    AnswerFact,
    FactQuality,
    canonical_record,
    select_distractors,
)
from mcq_inputs import (  # noqa: E402
    ALLOWED_EVIDENCE_LEVELS,
    ALLOWED_EXCLUSION_BASES,
    ALLOWED_GRANULARITY_RISKS,
    FORBIDDEN_LEVEL_BASIS_COMBINATIONS,
    PINNED_LROLESIM_EXECUTION,
    AnswerNotFoundError,
    InputContractError,
    answer_facts_from_local_kg,
    case_from_frozen_records,
    case_from_records,
    find_evidence_records,
    find_ranking_record,
    frozen_answer_uris,
    read_jsonl,
    validate_fact_alignment,
)
# The frozen upstream implementations, imported HERE so that a few B1.2 pins can
# be stated on the rule itself (a leakage pair that is not in the pinned graph, a
# chemical display label) without the production module growing a copy of either.
from kg.loader import load_local_kg  # noqa: E402
from rationale_v3.quality import assess_fact_quality, load_quality_policy  # noqa: E402

# T2. The reference reader lives in the kernel's own test module. Importing it
# HERE is the whole point of the equivalence test; the production module must
# never import in this direction, which is asserted below by an AST scan.
from test_mcq_core import load_pilot_cases  # noqa: E402

import mcq_inputs  # noqa: E402

CORE_SOURCE = ROOT / "src" / "mcq_core.py"
INPUTS_SOURCE = ROOT / "src" / "mcq_inputs.py"
HANDOFF = (ROOT / "outputs" / "journal2_week2_extract_integration_2026-07-30"
           / "candidate_ranking_handoff.jsonl")
R1_DIR = ROOT / "outputs" / "journal2_week2_rationale_v3_r1_2026-08-03"
EVIDENCE = R1_DIR / "evidence_audit_v3_r1.jsonl"
ORACLE = R1_DIR / "selected_mcqs_v3_r1.jsonl"

# The Phase-A2 kernel this adapter feeds, frozen at this digest.
FROZEN_KERNEL_SHA256 = "ba4b378584ef1f067f81ab8ffcf2c82137293acac1915e58770f2b1b097abf63"

SATO = "http://dbpedia.org/resource/Eisaku_Satō"
# Silicon is the corruption fixture: 11 candidates and 3 facts, the smallest
# real record set, so a failing-case test reads as a single obvious edit.
SILICON = "http://dbpedia.org/resource/Silicon"
# Sulfuric acid reached Prompt 8D but no approved class was graph-feasible, so it
# has a ranking row and no evidence records at all.
SULFURIC_ACID = "http://dbpedia.org/resource/Sulfuric_acid"
# Albert Einstein was never processed by either frozen run.
EINSTEIN = "http://dbpedia.org/resource/Albert_Einstein"
CARBON = "http://dbpedia.org/resource/Carbon"

# --- B1.2: the pinned local KG and the frozen R1 quality policy -------------
PINNED_KG = ROOT / "data" / "infobox.pickle_EnglishVersion_EntityType"
# Pinned so a silent rebuild cannot pass: the graph build assigns node indices by
# iterating a Python set, so a rebuilt file renumbers every node.
PINNED_KG_SHA256 = "e230c5b95e20093631697624d9c46f30a14081b3f415d5027ffaf313bdbbea1b"
QUALITY_POLICY_PATH = (ROOT / "src" / "rationale_v3" / "policies"
                       / "predicate_policy.json")

#: The B0-audit measurements of Albert Einstein, independently taken from this
#: same pinned snapshot. They are TEST EXPECTATIONS only: the production function
#: hard-codes none of them and derives every one from the graph.
EINSTEIN_EXPECTED = {
    "one_hop_out_facts": 9,
    "one_hop_in_facts": 57,
    "distinct_one_hop_facts": 66,
    "distinct_counterpart_entities": 60,
    "eligible_after_frozen_r1_hard_filter": 48,
    "eligible_predicate_direction_keys": 17,
    "eligible_with_registered_template": 41,
}

#: The eleven FactQuality fields, which is exactly what B1.2-T5 compares against
#: the frozen R1 ``answer_fact_evidence[].quality`` records.
QUALITY_FIELDS = ("predicate_uri", "direction", "counterpart_uri",
                  "display_label", "eligible", "soft_leak", "verbalizable",
                  "pedagogical_tier", "label_length", "token_count",
                  "template_id")

#: Every pinned-graph load this module performs, appended by the fixture below.
#: B1.2-T9 requires exactly one: the graph is 1.2 GB and roughly 12 GB resident.
PINNED_KG_LOADS: list[str] = []

#: Outbound connection attempts recorded while the real Einstein extraction ran.
#: B1.2-T9 requires this to stay empty.
NETWORK_ATTEMPTS: list[str] = []

requires_pinned_kg = pytest.mark.skipif(
    not PINNED_KG.is_file() or os.environ.get("MCQ_JOURNAL2_SKIP_REAL_KG") == "1",
    reason=(f"the pinned local KG {PINNED_KG.name} is unavailable, or "
            f"MCQ_JOURNAL2_SKIP_REAL_KG=1 was set; the B1.2 acceptance gate "
            f"cannot be measured on a synthetic graph"),
)


# --------------------------------------------------------------------------
# Fixtures and helpers
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pilot_uris():
    return frozen_answer_uris(handoff_path=HANDOFF, evidence_path=EVIDENCE)


@pytest.fixture(scope="module")
def production_cases(pilot_uris):
    """Every pilot AnswerCase, built through the PRODUCTION adapter."""
    return {uri: case_from_frozen_records(uri, handoff_path=HANDOFF,
                                          evidence_path=EVIDENCE)
            for uri in pilot_uris}


@pytest.fixture(scope="module")
def production_selections(production_cases):
    return {uri: select_distractors(case) for uri, case in production_cases.items()}


@pytest.fixture(scope="module")
def oracle():
    """``selected_mcqs_v3_r1.jsonl`` is used ONLY as the regression oracle."""
    return [json.loads(line) for line in ORACLE.read_text("utf-8").splitlines()]


def oracle_identities(record):
    """The oracle's rationale, as canonical (predicate, direction, object) tuples."""
    return [(fact["predicate_uri"], fact["direction"], fact["claim_object_uri"])
            for fact in record["selected_rationale"]]


def frozen_records(answer_uri=SILICON):
    """A DEEP COPY of one Answer's frozen records, safe to corrupt in a test.

    Corrupting a copy rather than a temporary file keeps each failing-case test a
    single visible edit, and guarantees the frozen inputs on disk are never
    touched.
    """
    ranking = find_ranking_record(read_jsonl(HANDOFF), answer_uri)
    evidence = find_evidence_records(read_jsonl(EVIDENCE), answer_uri)
    return copy.deepcopy(ranking), copy.deepcopy(evidence)


def assert_refused(corrupt, fragment, answer_uri=SILICON):
    """Apply one corruption to real frozen records and require an explicit raise.

    ``fragment`` is matched against the message so that the test pins down WHICH
    invariant fired, not merely that something failed.
    """
    ranking, evidence = frozen_records(answer_uri)
    corrupt(ranking, evidence)
    with pytest.raises(InputContractError) as error:
        case_from_records(answer_uri, ranking, evidence)
    assert fragment in str(error.value), str(error.value)


def sample_quality():
    """A minimal FactQuality for the hand-built alignment tests."""
    return FactQuality(
        predicate_uri="http://dbpedia.org/property/almaMater", direction="OUT",
        counterpart_uri="http://dbpedia.org/resource/Kobe_University",
        display_label="Kobe University", eligible=True, soft_leak=False,
        verbalizable=True, pedagogical_tier=1, label_length=15, token_count=2,
        template_id="ALMA_MATER_OUT_V1")


def canonical_json(case, selection):
    return json.dumps(canonical_record(case, selection), sort_keys=True,
                      ensure_ascii=False)


def test_the_uncorrupted_fixture_builds_a_case():
    """The corruption helper starts from records that are known to be valid."""
    ranking, evidence = frozen_records()
    case = case_from_records(SILICON, ranking, evidence)
    assert len(case.candidates) == 11
    assert len(case.facts) == 3


# --------------------------------------------------------------------------
# T1. The eight-pilot regression, through the production adapter
# --------------------------------------------------------------------------


def test_exactly_the_eight_r1_ready_answers_have_frozen_records(pilot_uris, oracle):
    """The adapter's inventory is the eight the R1 run actually published."""
    assert len(oracle) == 8
    assert pilot_uris == tuple(sorted(record["answer_uri"] for record in oracle))


def test_all_eight_pilot_selections_are_reproduced(production_selections, oracle):
    """Policy, distractor URIs, distractor ranks, rationale fact set, |R*|."""
    for record in oracle:
        selection = production_selections[record["answer_uri"]]
        assert selection is not None, record["display_label"]
        assert selection.evidence_policy == record["evidence_policy"]
        assert [d.uri for d in selection.distractors] == \
            [d["candidate_uri"] for d in record["distractors"]]
        assert [d.rank for d in selection.distractors] == \
            [d["original_lrolesim_rank"] for d in record["distractors"]]
        assert sorted(selection.rationale.fact_identities) == \
            sorted(oracle_identities(record))
        assert selection.minimum_rationale_size == record["minimum_rationale_size"]


def test_the_reported_search_sizes_are_re_derived_not_copied(production_selections,
                                                             oracle):
    """The adapter reads no result field, so these numbers come from the kernel."""
    for record in oracle:
        selection = production_selections[record["answer_uri"]]
        assert selection.candidate_count == record["original_candidate_count"]
        assert selection.enumerated_combination_count == \
            record["enumerated_combination_count"]
        assert selection.candidate_rank_sum == record["candidate_rank_sum"]
        assert selection.lrolesim_score_sum == record["lrolesim_score_sum"]
        assert selection.lrolesim_score_min == record["lrolesim_score_min"]
        assert selection.rationale.coverage_mask == record["coverage_mask"]
        assert selection.mcq_evidence_level == record["mcq_evidence_level"]
        assert selection.search_scope == record["search_scope"]


def test_the_sato_case_survives_the_round_trip(production_cases, production_selections):
    """The one pilot Answer whose selection leaves the provisional top three.

    Eisaku Satō's LRoleSim ranks 2 and 3 carry no L1-covering eligible fact, so
    the exact search replaces them with ranks 5 and 6 and needs a two-fact
    rationale. If the adapter mis-aligned a single per-candidate tuple, this is
    the Answer whose numbers would move first.
    """
    selection = production_selections[SATO]
    assert len(production_cases[SATO].candidates) == 24
    assert [d.rank for d in selection.distractors] == [1, 5, 6]
    assert selection.minimum_rationale_size == 2
    assert selection.enumerated_combination_count == 2024


def test_every_pilot_answer_reaches_mcq_l1_and_no_l2_exists(production_cases,
                                                            production_selections):
    """Zero L2 is the correct offline outcome, not a gap: no proof source exists."""
    for uri, selection in production_selections.items():
        assert selection.evidence_policy == "main-l1"
        assert selection.mcq_evidence_level == "MCQ-L1"
        for fact in production_cases[uri].facts:
            assert "L2" not in fact.levels


# --------------------------------------------------------------------------
# T2. Adapter equivalence with the test-only reference reader
# --------------------------------------------------------------------------


def test_the_production_adapter_equals_the_reference_reader(production_cases):
    """No silent drift between the promoted reader and the one it replaces."""
    reference = load_pilot_cases()
    assert set(reference) == set(production_cases)
    for uri, case in production_cases.items():
        assert case == reference[uri], uri


def test_the_production_module_imports_no_test_module_and_no_client():
    """One AST scan covers test coupling, network clients and NLP toolkits.

    B1.2 widened this set by exactly two packages, both frozen and both offline:
    ``rationale_v3`` for the R1 quality/leakage assessor and the R1 URI
    normalizer, and ``selection`` for the corrected Prompt-8D one-hop edge
    enumeration. ``kg`` is deliberately still absent — the adapter receives an
    already-loaded graph and must never learn to resolve or open one itself.
    """
    allowed = {"__future__", "json", "pathlib", "typing", "mcq_core",
               "rationale_v3", "selection"}
    tree = ast.parse(INPUTS_SOURCE.read_text("utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= allowed, sorted(imported - allowed)


def test_no_forbidden_module_is_named_in_the_adapter_source():
    """Explicit list, so a future edit that adds one fails loudly.

    ``rationale_v3`` left this list in B1.2 because the adapter now legitimately
    calls the frozen R1 quality assessor; the AST test above is what keeps that
    import narrow. Every other name stays banned, and the serialization-format
    name in particular: B1.2 reads an already-loaded graph object and must never
    acquire its own reader for the pinned local-KG file.
    """
    forbidden = ["requests", "urllib", "http.client", "socket", "SPARQLWrapper",
                 "rdflib", "spacy", "nltk", "wordnet", "gensim", "torch",
                 "transformers", "sentence_transformers", "sklearn", "openai",
                 "anthropic", "test_mcq_core", "pickle"]
    text = INPUTS_SOURCE.read_text("utf-8")
    assert [name for name in forbidden if name in text] == []


def test_the_adapter_uses_the_authoritative_l1_terminology():
    """EVIDENCE_TAXONOMY_V1.md is authoritative; the superseded name is banned.

    Both banned strings are assembled from two halves on purpose, so that this
    test file does not itself contain the literal strings it forbids. The frozen
    R1 records carry the superseded name in a diagnostic ``reason_code`` field;
    the adapter never reads it, and must never propagate it.
    """
    banned_token = "POSITIVE_VALUE" + "_CONTRAST"
    banned_phrase = "positive " + "contrast"
    text = INPUTS_SOURCE.read_text("utf-8")
    assert banned_token not in text
    assert banned_phrase not in text.lower()


# --------------------------------------------------------------------------
# T3/T4. Invariant 1 — aligned per-candidate tuples, never truncated
# --------------------------------------------------------------------------


@pytest.mark.parametrize("levels,bases,risks", [
    (("L1", "L1"), ("NONE",) * 3, ("NONE",) * 3),
    (("L1",) * 3, ("NONE", "NONE"), ("NONE",) * 3),
    (("L1",) * 3, ("NONE",) * 3, ("NONE", "NONE")),
    (("L1",) * 4, ("NONE",) * 3, ("NONE",) * 3),
])
def test_invariant_1_rejects_any_misaligned_tuple(levels, bases, risks):
    """A short tuple would re-point every later level at the wrong candidate."""
    fact = AnswerFact(quality=sample_quality(), levels=levels,
                      exclusion_bases=bases, granularity_risks=risks)
    with pytest.raises(InputContractError) as error:
        validate_fact_alignment(fact, 3, "hand-built fact")
    assert "invariant 1" in str(error.value)


def test_invariant_1_rejects_a_candidate_count_disagreeing_with_the_roster():
    def corrupt(ranking, evidence):
        evidence[0]["candidate_count"] = 10

    assert_refused(corrupt, "invariant 1")


def test_a_dropped_per_candidate_row_raises_instead_of_truncating():
    """The alignment guard fires before any tuple is built; zip() is never used."""
    def corrupt(ranking, evidence):
        evidence[0]["per_candidate"].pop()

    assert_refused(corrupt, "invariant 6")


def test_an_extra_per_candidate_row_raises_instead_of_being_ignored():
    def corrupt(ranking, evidence):
        extra = copy.deepcopy(evidence[0]["per_candidate"][0])
        extra["candidate_uri"] = "http://dbpedia.org/resource/Not_In_The_Pool"
        evidence[0]["per_candidate"].append(extra)

    assert_refused(corrupt, "invariant 6")


# --------------------------------------------------------------------------
# T3/T5. Invariants 2 and 3 — vocabularies and forbidden combinations
# --------------------------------------------------------------------------


@pytest.mark.parametrize("field,value", [
    ("evidence_level", "L3"),
    ("evidence_level", "l1"),
    ("exclusion_basis", "PROBABLY"),
    ("granularity_risk", "MAYBE"),
])
def test_invariant_2_rejects_a_value_outside_the_frozen_vocabulary(field, value):
    def corrupt(ranking, evidence):
        evidence[0]["per_candidate"][0][field] = value

    assert_refused(corrupt, "invariant 2")


def test_the_frozen_vocabularies_are_the_taxonomy_v1_vocabularies():
    """The four levels, the three bases and the three risks, spelled out."""
    assert ALLOWED_EVIDENCE_LEVELS == {"NOT_COVERED", "L0", "L1", "L2"}
    assert ALLOWED_EXCLUSION_BASES == {"NONE", "SCOPED_EMPIRICAL", "FORMAL_PROOF"}
    assert ALLOWED_GRANULARITY_RISKS == {
        "NONE", "CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT",
        "UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE"}


@pytest.mark.parametrize("level,basis", [("L0", "SCOPED_EMPIRICAL"), ("L2", "NONE")])
def test_invariant_3_rejects_the_two_forbidden_combinations(level, basis):
    """L0 + SCOPED_EMPIRICAL annotates an absence; L2 + NONE is a proof with no basis."""
    assert (level, basis) in FORBIDDEN_LEVEL_BASIS_COMBINATIONS

    def corrupt(ranking, evidence):
        evidence[0]["per_candidate"][0]["evidence_level"] = level
        evidence[0]["per_candidate"][0]["exclusion_basis"] = basis

    assert_refused(corrupt, "invariant 3")


def test_a_scoped_empirical_annotation_on_an_l1_is_still_accepted():
    """SCOPED_EMPIRICAL is an annotation on an existing L1, not a fourth level."""
    ranking, evidence = frozen_records()
    row = evidence[0]["per_candidate"][0]
    row["evidence_level"] = "L1"
    row["exclusion_basis"] = "SCOPED_EMPIRICAL"
    case = case_from_records(SILICON, ranking, evidence)
    assert "SCOPED_EMPIRICAL" in case.facts[0].exclusion_bases


# --------------------------------------------------------------------------
# T3. Invariants 4 and 7 — the candidate roster
# --------------------------------------------------------------------------


def test_invariant_4_rejects_a_duplicated_rank():
    def corrupt(ranking, evidence):
        ranking["ranked_candidates"][1]["rank"] = 1

    assert_refused(corrupt, "invariant 4")


def test_invariant_4_rejects_a_ranking_that_does_not_start_at_one():
    def corrupt(ranking, evidence):
        for row in ranking["ranked_candidates"]:
            row["rank"] += 1

    assert_refused(corrupt, "invariant 4")


def test_invariant_4_rejects_a_repeated_candidate_uri():
    def corrupt(ranking, evidence):
        ranking["ranked_candidates"][1]["canonical_candidate_uri"] = \
            ranking["ranked_candidates"][0]["canonical_candidate_uri"]

    assert_refused(corrupt, "invariant 4")


def test_invariant_4_rejects_a_truncated_candidate_pool():
    """The complete ranked pool is the anonymity denominator, not a top-k slice."""
    def corrupt(ranking, evidence):
        ranking["ranked_candidates"] = ranking["ranked_candidates"][:5]

    assert_refused(corrupt, "invariant 4")


def test_invariant_7_rejects_an_answer_that_ranks_itself():
    def corrupt(ranking, evidence):
        ranking["ranked_candidates"][0]["canonical_candidate_uri"] = SILICON

    assert_refused(corrupt, "invariant 7")


# --------------------------------------------------------------------------
# T3/T6. Invariants 5 and 8 — the pinned ranker, and no Overlap substitution
# --------------------------------------------------------------------------


def test_the_five_pinned_lrolesim_parameters_are_the_frozen_ones():
    assert PINNED_LROLESIM_EXECUTION == {
        "ranker_name": "lrolesim_m1_fixed_k3",
        "measure": "lrolesim_ed",
        "lrolesim_beta": 0.2,
        "iterations": 3,
        "iteration_mode": "fixed",
    }


@pytest.mark.parametrize("field,value", [
    ("ranker_name", "lrolesim_m1_fixed_k5"),
    ("measure", "lrolesim_simrank"),
    ("lrolesim_beta", 0.8),
    ("iterations", 5),
    ("iteration_mode", "converged"),
])
def test_invariant_5_refuses_an_unpinned_execution_path(field, value):
    """A different beta or iteration mode is a different ranker, same field names."""
    def corrupt(ranking, evidence):
        ranking[field] = value

    assert_refused(corrupt, "invariant 5")


@pytest.mark.parametrize("field,value", [
    ("ranker_name", "legacy_overlap_v1"),
    ("measure", "overlap_ed"),
])
def test_invariant_8_refuses_a_legacy_overlap_ranking(field, value):
    def corrupt(ranking, evidence):
        ranking[field] = value

    assert_refused(corrupt, "invariant 8")


def test_a_legacy_overlap_ranking_never_reaches_candidate_rank_or_score(monkeypatch):
    """The refusal happens BEFORE a single Candidate is constructed."""
    def must_not_run(ranking_row):
        raise AssertionError("a Candidate was built from a rejected ranking")

    monkeypatch.setattr(mcq_inputs, "candidates_from_ranking", must_not_run)
    ranking, evidence = frozen_records()
    ranking["ranker_name"] = "legacy_overlap_v1"
    with pytest.raises(InputContractError) as error:
        case_from_records(SILICON, ranking, evidence)
    assert "invariant 8" in str(error.value)


# --------------------------------------------------------------------------
# T3. Invariant 6 — exact candidate alignment between the two frozen files
# --------------------------------------------------------------------------


def test_invariant_6_rejects_a_renamed_candidate():
    def corrupt(ranking, evidence):
        evidence[0]["per_candidate"][0]["candidate_uri"] = \
            "http://dbpedia.org/resource/Germanium_dioxide"

    assert_refused(corrupt, "invariant 6")


def test_invariant_6_rejects_a_duplicated_candidate_row():
    def corrupt(ranking, evidence):
        rows = evidence[0]["per_candidate"]
        rows[1] = copy.deepcopy(rows[0])

    assert_refused(corrupt, "invariant 6")


def test_invariant_6_rejects_evidence_that_was_ranked_differently():
    """A file re-ranked after classification would align levels to a dead pool."""
    def corrupt(ranking, evidence):
        rows = evidence[0]["per_candidate"]
        rows[0]["candidate_rank"], rows[1]["candidate_rank"] = \
            rows[1]["candidate_rank"], rows[0]["candidate_rank"]

    assert_refused(corrupt, "invariant 6")


# --------------------------------------------------------------------------
# T3. Invariant 9 — the selected class and its recorded approval position
# --------------------------------------------------------------------------


def test_invariant_9_rejects_a_missing_selected_class():
    def corrupt(ranking, evidence):
        ranking["selected_class_uri"] = ""

    assert_refused(corrupt, "invariant 9")


@pytest.mark.parametrize("field,value", [
    ("graph_stage_status", "NO_GRAPH_FEASIBLE_APPROVED_CLASS"),
    ("graph_stage_status", "GRAPH_SELECTED_UNAPPROVED_TOP1"),
    ("mapping_stage_status", "NO_MAPPING_FEASIBLE_APPROVED_CLASS"),
])
def test_invariant_9_rejects_a_pool_not_drawn_from_an_approved_class_position(
        field, value):
    """Only a named position of the human-approved class list is accepted."""
    def corrupt(ranking, evidence):
        ranking[field] = value

    assert_refused(corrupt, "invariant 9")


def test_invariant_9_rejects_an_answer_never_handed_over_for_rationale_selection():
    def corrupt(ranking, evidence):
        ranking["ready_for_rationale_selection"] = False

    assert_refused(corrupt, "invariant 9")


def test_invariant_9_rejects_evidence_classified_against_another_class():
    """The two frozen files must agree on the class the pool was drawn from."""
    def corrupt(ranking, evidence):
        evidence[0]["scope"] = "http://dbpedia.org/resource/Category:Metalloids"

    assert_refused(corrupt, "invariant 9")


def test_every_pilot_answer_records_its_class_in_both_frozen_files(pilot_uris):
    """The provenance invariant 9 CAN check, on the real records, for all eight."""
    for uri in pilot_uris:
        ranking = find_ranking_record(read_jsonl(HANDOFF), uri)
        evidence = find_evidence_records(read_jsonl(EVIDENCE), uri)
        assert ranking["selected_class_uri"]
        assert {record["scope"] for record in evidence} == \
            {ranking["selected_class_uri"]}


# --------------------------------------------------------------------------
# Malformed records that are not one of the nine, but must still not pass
# --------------------------------------------------------------------------


def test_a_missing_quality_field_is_reported_by_name():
    def corrupt(ranking, evidence):
        del evidence[0]["quality"]["pedagogical_tier"]

    assert_refused(corrupt, "pedagogical_tier")


def test_a_non_contiguous_fact_index_is_refused():
    def corrupt(ranking, evidence):
        evidence[0]["fact_index"] = 99

    assert_refused(corrupt, "fact_index")


def test_records_belonging_to_another_answer_are_refused():
    ranking, evidence = frozen_records()
    with pytest.raises(InputContractError):
        case_from_records(SATO, ranking, evidence)


# --------------------------------------------------------------------------
# T7/T8. Determinism, and the kernel staying frozen
# --------------------------------------------------------------------------


def test_two_independent_runs_are_byte_identical(pilot_uris):
    """Reconstruction and selection twice, compared as canonical JSON."""
    for uri in pilot_uris:
        first = case_from_frozen_records(uri, handoff_path=HANDOFF,
                                         evidence_path=EVIDENCE)
        second = case_from_frozen_records(uri, handoff_path=HANDOFF,
                                          evidence_path=EVIDENCE)
        assert canonical_json(first, select_distractors(first)) == \
            canonical_json(second, select_distractors(second))


def test_the_phase_a2_kernel_is_still_byte_identical():
    """B1.1 adds a caller; it changes nothing in the frozen selection kernel."""
    assert hashlib.sha256(CORE_SOURCE.read_bytes()).hexdigest() == FROZEN_KERNEL_SHA256


# --------------------------------------------------------------------------
# T9. Albert Einstein is NOT fabricated
# --------------------------------------------------------------------------


def test_albert_einstein_is_absent_from_the_frozen_inventory(pilot_uris):
    assert EINSTEIN not in pilot_uris


def test_albert_einstein_produces_a_clear_no_frozen_records_failure():
    """Never a synthetic case: no candidates, no scores, no evidence levels.

    Albert Einstein has no approved class decision and no class-member roster, so
    neither frozen run ever produced a record for him. The honest outcome is a
    failure that says exactly that.
    """
    with pytest.raises(AnswerNotFoundError) as error:
        case_from_frozen_records(EINSTEIN, handoff_path=HANDOFF,
                                 evidence_path=EVIDENCE)
    message = str(error.value)
    assert "no frozen records" in message
    assert EINSTEIN in message
    assert "will not fabricate" in message


def test_albert_einstein_has_no_evidence_records_either():
    with pytest.raises(AnswerNotFoundError):
        find_evidence_records(read_jsonl(EVIDENCE), EINSTEIN)


def test_sulfuric_acid_has_a_ranking_row_but_no_evidence_and_is_refused():
    """The ninth pilot Answer: no approved class was graph-feasible for it."""
    row = find_ranking_record(read_jsonl(HANDOFF), SULFURIC_ACID)
    assert row["ready_for_rationale_selection"] is False
    assert row["ranked_candidate_count"] == 0
    with pytest.raises(AnswerNotFoundError):
        case_from_frozen_records(SULFURIC_ACID, handoff_path=HANDOFF,
                                 evidence_path=EVIDENCE)


# ==========================================================================
# PHASE B1 STEP 2 — the Answer's own facts, read from the pinned local KG
# ==========================================================================
#
# What is NOT tested here, because B1.2 must not do it: no evidence level, no
# exclusion basis, no granularity risk, no candidate roster, no class selection,
# no member retrieval, no LRoleSim, no AnswerCase for Albert Einstein.


@contextlib.contextmanager
def no_network(recorder):
    """Refuse and record every outbound connection attempt inside the block.

    A guard that FAILS makes "zero network attempts" a checked property rather
    than an assurance, and the recorder is the published evidence.
    """
    saved = (socket.socket.connect, socket.socket.connect_ex,
             socket.create_connection)

    def blocked(address):
        recorder.append(repr(address))
        raise AssertionError(
            f"outbound connection to {address!r} refused: B1.2 reads only the "
            f"pinned local KG and frozen local policy files")

    socket.socket.connect = lambda self, address, *a, **k: blocked(address)
    socket.socket.connect_ex = lambda self, address, *a, **k: blocked(address)
    socket.create_connection = lambda address, *a, **k: blocked(address)
    try:
        yield recorder
    finally:
        (socket.socket.connect, socket.socket.connect_ex,
         socket.create_connection) = saved


@pytest.fixture(scope="module")
def pinned_kg():
    """The pinned local KG, loaded ONCE for the whole module.

    ``verify_sha256`` pins the run to one exact build rather than to whatever
    file currently has that name; a mismatch raises instead of quietly measuring
    a different graph. Loading is delegated to ``kg.loader``, which is the only
    module allowed to open the file — the adapter under test never does.
    """
    PINNED_KG_LOADS.append(str(PINNED_KG))
    return load_local_kg(PINNED_KG, verify_sha256=PINNED_KG_SHA256)


@pytest.fixture(scope="module")
def quality_policy():
    """The frozen R1 §9 policy: predicates, objects, leakage thresholds, templates."""
    return load_quality_policy(QUALITY_POLICY_PATH)


@pytest.fixture(scope="module")
def einstein_facts(pinned_kg, quality_policy):
    """Albert Einstein's complete one-hop fact inventory, extracted ONCE.

    The extraction runs inside the socket guard, so B1.2-T9 is a property of the
    real acceptance-gate run rather than of a separate toy call.
    """
    with no_network(NETWORK_ATTEMPTS):
        return answer_facts_from_local_kg(
            EINSTEIN, local_kg=pinned_kg, quality_policy=quality_policy)


def by_identity(facts):
    return {fact.identity: fact for fact in facts}


def frozen_r1_quality_by_answer():
    """{answer_uri: {(p, direction, counterpart): frozen quality record}}.

    Read from the frozen R1 evidence audit, which is the ORACLE here and never an
    input to the reconstruction being tested.
    """
    frozen: dict = {}
    for record in read_jsonl(EVIDENCE):
        if record.get("record_type") != "answer_fact_evidence":
            continue
        quality = record["quality"]
        frozen.setdefault(record["answer_uri"], {})[
            (quality["predicate_uri"], quality["direction"],
             quality["counterpart_uri"])] = quality
    return frozen


# --------------------------------------------------------------------------
# B1.2-T1. The Albert Einstein acceptance gate — all seven measured counts
# --------------------------------------------------------------------------


@requires_pinned_kg
def test_b12_t1_einstein_reproduces_every_b0_audit_count(einstein_facts):
    """The seven numbers the B0 audit measured on this same pinned snapshot.

    If the file on disk ever produces different numbers, this test fails and the
    expectations are NOT to be edited: the correct response is to report which
    fact identities differ, because the snapshot, not the arithmetic, moved.
    """
    eligible = [fact for fact in einstein_facts if fact.eligible]
    measured = {
        "one_hop_out_facts": sum(1 for f in einstein_facts if f.direction == "OUT"),
        "one_hop_in_facts": sum(1 for f in einstein_facts if f.direction == "IN"),
        "distinct_one_hop_facts": len(einstein_facts),
        "distinct_counterpart_entities": len({f.counterpart_uri
                                              for f in einstein_facts}),
        "eligible_after_frozen_r1_hard_filter": len(eligible),
        "eligible_predicate_direction_keys": len({f.predicate_direction_key
                                                  for f in eligible}),
        "eligible_with_registered_template": sum(1 for f in eligible
                                                 if f.verbalizable),
    }
    assert measured == EINSTEIN_EXPECTED


@requires_pinned_kg
def test_b12_t1_the_production_function_hard_codes_none_of_the_counts():
    """The seven numbers are test expectations, never constants in the module."""
    text = INPUTS_SOURCE.read_text("utf-8")
    tree = ast.parse(text)
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, int)
                and not isinstance(node.value, bool)}
    assert literals & set(EINSTEIN_EXPECTED.values()) == set()


@requires_pinned_kg
def test_b12_t1_the_complete_inventory_keeps_its_ineligible_facts(einstein_facts):
    """66 observed, 48 eligible: the other 18 are REPORTED, not dropped.

    A reviewer can only check that the hard filter removed the right facts if the
    facts it removed are still in the inventory with ``eligible`` False.
    """
    ineligible = [fact for fact in einstein_facts if not fact.eligible]
    assert len(einstein_facts) == 66
    assert len(ineligible) == 18
    assert all(fact.display_label for fact in ineligible)


@requires_pinned_kg
def test_b12_t1_external_url_and_web_archive_facts_are_ineligible(einstein_facts):
    """The Eisaku-Satō Web-Archive failure class, pinned on a second Answer."""
    facts = by_identity(einstein_facts)
    web_archive = ("http://dbpedia.org/property/url", "OUT",
                   "https://web.archive.org/web/20110811112756/"
                   "http:/www.alberteinstein.info")
    external = ("http://dbpedia.org/property/thesisUrl", "OUT",
                "http://e-collection.library.ethz.ch/eserv/eth:30378/"
                "eth-30378-01.pdf")
    assert facts[web_archive].eligible is False
    assert facts[external].eligible is False


@requires_pinned_kg
def test_b12_t1_answer_lexical_leaks_are_ineligible_and_clean_facts_are_not(
        einstein_facts):
    """"Bust of Albert Einstein" hands the learner the Answer; "Mileva Marić" does not."""
    facts = by_identity(einstein_facts)
    leaking = [
        ("http://dbpedia.org/property/subject", "IN",
         "http://dbpedia.org/resource/Bust_of_Albert_Einstein"),
        ("http://dbpedia.org/property/spouse", "IN",
         "http://dbpedia.org/resource/Elsa_Einstein"),
        ("http://dbpedia.org/property/children", "OUT",
         "http://dbpedia.org/resource/Hans_Albert_Einstein"),
    ]
    clean = [
        ("http://dbpedia.org/property/spouse", "OUT",
         "http://dbpedia.org/resource/Mileva_Marić"),
        ("http://dbpedia.org/property/doctoralAdvisor", "OUT",
         "http://dbpedia.org/resource/Alfred_Kleiner"),
        ("http://dbpedia.org/property/influences", "IN",
         "http://dbpedia.org/resource/Karl_Popper"),
    ]
    assert [facts[key].eligible for key in leaking] == [False, False, False]
    assert [facts[key].eligible for key in clean] == [True, True, True]


# --------------------------------------------------------------------------
# B1.2-T2. Direction safety — IN and OUT are never merged
# --------------------------------------------------------------------------


@requires_pinned_kg
def test_b12_t2_out_and_in_are_counted_independently(einstein_facts):
    """9 and 57, derived separately and never as one merged neighbourhood."""
    out = [fact for fact in einstein_facts if fact.direction == "OUT"]
    incoming = [fact for fact in einstein_facts if fact.direction == "IN"]
    assert len(out) == 9
    assert len(incoming) == 57
    assert len(out) + len(incoming) == len(einstein_facts) == 66
    assert {fact.direction for fact in einstein_facts} == {"IN", "OUT"}


@requires_pinned_kg
def test_b12_t2_one_predicate_in_both_directions_is_two_different_facts(
        einstein_facts):
    """``dbp:children`` reaches ``dbr:Einstein_family`` in BOTH directions.

    Same predicate, same counterpart, opposite direction: two rows, two distinct
    canonical identities, and two independently assessed quality records. A
    reconstruction that keyed on the predicate alone — or on (predicate,
    counterpart) — would report one fact here and silently lose the other.
    """
    children = "http://dbpedia.org/property/children"
    family = "http://dbpedia.org/resource/Einstein_family"
    facts = by_identity(einstein_facts)
    assert (children, "IN", family) in facts
    assert (children, "OUT", family) in facts
    # Same κ predicate, different κ: the two are never the same rationale slot.
    assert facts[(children, "IN", family)].predicate_direction_key != \
        facts[(children, "OUT", family)].predicate_direction_key
    # And the two directions genuinely carry different upstream verbalizations.
    assert facts[(children, "IN", family)].template_id != \
        facts[(children, "OUT", family)].template_id

    # A second, independent occurrence, to prove the first is not a special case.
    advisors = "http://dbpedia.org/property/academicAdvisors"
    both = {fact.direction for fact in einstein_facts
            if fact.predicate_uri == advisors}
    assert both == {"IN", "OUT"}


@requires_pinned_kg
def test_b12_t2_a_counterpart_reached_in_both_directions_is_one_entity(
        einstein_facts):
    """66 facts over 60 counterparts: the six extra facts are re-reached entities."""
    counterparts = {fact.counterpart_uri for fact in einstein_facts}
    assert len(counterparts) == 60
    assert len(einstein_facts) - len(counterparts) == 6


# --------------------------------------------------------------------------
# B1.2-T3 and B1.2-T4. Uniqueness and deterministic order
# --------------------------------------------------------------------------


@requires_pinned_kg
def test_b12_t3_no_canonical_fact_identity_appears_twice(einstein_facts):
    """``(predicate_uri, direction, counterpart_uri)`` is unique by construction."""
    identities = [fact.identity for fact in einstein_facts]
    assert len(set(identities)) == len(identities) == 66


@requires_pinned_kg
def test_b12_t4_two_independent_extractions_are_the_same_ordered_tuple(
        pinned_kg, quality_policy):
    """Not merely the same set: the same tuple, element for element, in order."""
    first = answer_facts_from_local_kg(EINSTEIN, local_kg=pinned_kg,
                                       quality_policy=quality_policy)
    second = answer_facts_from_local_kg(EINSTEIN, local_kg=pinned_kg,
                                        quality_policy=quality_policy)
    assert first == second
    assert [fact.identity for fact in first] == [fact.identity for fact in second]


@requires_pinned_kg
def test_b12_t4_the_order_is_ascending_predicate_direction_counterpart(
        einstein_facts):
    """The canonical order is the sorted identity, with nothing else mixed in."""
    identities = [fact.identity for fact in einstein_facts]
    assert identities == sorted(identities)


# --------------------------------------------------------------------------
# B1.2-T5. Frozen R1 quality semantics, on the existing eight-Answer pilot
# --------------------------------------------------------------------------


@requires_pinned_kg
def test_b12_t5_the_pilot_quality_records_are_reproduced_exactly(pinned_kg,
                                                                 quality_policy):
    """All eight R1-ready pilot Answers, all eleven quality fields, no tolerance.

    This is what makes the Einstein numbers trustworthy: the same function, the
    same graph and the same policy reproduce 582 already-published quality
    records exactly. A difference here would be reported, never special-cased —
    the function must not learn to imitate stale output for one Answer.
    """
    frozen = frozen_r1_quality_by_answer()
    assert len(frozen) == 8

    differences: list = []
    compared = 0
    for answer_uri in sorted(frozen):
        local = by_identity(answer_facts_from_local_kg(
            answer_uri, local_kg=pinned_kg, quality_policy=quality_policy))
        expected = frozen[answer_uri]
        differences += [("only in frozen R1", answer_uri, key)
                        for key in sorted(set(expected) - set(local))]
        differences += [("only in local reconstruction", answer_uri, key)
                        for key in sorted(set(local) - set(expected))]
        for key in sorted(set(expected) & set(local)):
            fact = local[key]
            for name in QUALITY_FIELDS:
                compared += 1
                if getattr(fact, name) != expected[key][name]:
                    differences.append(
                        (answer_uri, key, name, getattr(fact, name),
                         expected[key][name]))
    assert differences == []
    assert compared == 582 * len(QUALITY_FIELDS)


@requires_pinned_kg
def test_b12_t5_the_pilot_answers_keep_their_in_out_split(pinned_kg,
                                                          quality_policy):
    """Silicon has 3 facts and Carbon 16, all IN — the R1 pilot's own shape."""
    silicon = answer_facts_from_local_kg(SILICON, local_kg=pinned_kg,
                                         quality_policy=quality_policy)
    carbon = answer_facts_from_local_kg(CARBON, local_kg=pinned_kg,
                                        quality_policy=quality_policy)
    assert len(silicon) == 3
    assert len(carbon) == 16
    assert {fact.direction for fact in carbon} == {"IN"}


@requires_pinned_kg
def test_b12_t5_an_answer_outside_the_pinned_graph_is_refused_not_emptied(
        pinned_kg, quality_policy):
    """An empty inventory must never stand in for "not in the snapshot"."""
    with pytest.raises(AnswerNotFoundError) as error:
        answer_facts_from_local_kg(
            "http://dbpedia.org/resource/Not_A_Node_In_This_Snapshot",
            local_kg=pinned_kg, quality_policy=quality_policy)
    assert "not a node of the pinned local KG" in str(error.value)


# --------------------------------------------------------------------------
# B1.2-T6. Answer leakage — the frozen R1 rule, unchanged
# --------------------------------------------------------------------------


@requires_pinned_kg
def test_b12_t6_carbon_carbonado_is_still_a_hard_leak(pinned_kg, quality_policy):
    """The original failure: "Carbonado" contains "Carbon" and gives the Answer away."""
    facts = by_identity(answer_facts_from_local_kg(
        CARBON, local_kg=pinned_kg, quality_policy=quality_policy))
    carbonado = ("http://dbpedia.org/property/formula", "IN",
                 "http://dbpedia.org/resource/Carbonado")
    assert facts[carbonado].eligible is False
    # Hard, not soft: a soft leak only orders equally small rationales.
    assert facts[carbonado].soft_leak is False


@requires_pinned_kg
def test_b12_t6_the_clean_carbon_negative_controls_are_untouched(pinned_kg,
                                                                 quality_policy):
    """Fifteen of Carbon's sixteen facts stay eligible; only Carbonado is removed."""
    facts = answer_facts_from_local_kg(CARBON, local_kg=pinned_kg,
                                       quality_policy=quality_policy)
    ineligible = [fact for fact in facts if not fact.eligible]
    assert len(ineligible) == 1
    assert ineligible[0].counterpart_uri.endswith("/Carbonado")
    for name in ("Diamond", "Graphite", "Blue_diamond", "Coal"):
        assert any(fact.counterpart_uri.endswith("/" + name) and fact.eligible
                   for fact in facts), name


def test_b12_t6_carbon_boron_carbide_is_not_hard_rejected(quality_policy):
    """The other half of the calibration, stated on the rule itself.

    ``dbr:Boron_carbide`` is not in Carbon's one-hop neighbourhood in this
    snapshot, so it cannot be pinned through an extraction. It is pinned here on
    the frozen assessor the adapter delegates to, because the two thresholds that
    separate ``Carbon``/``Carbonado`` (shared prefix "carbon", six characters,
    HARD) from ``Carbon``/``Boron_carbide`` (shared prefix "carb", four
    characters, at most SOFT) are exactly what an over-eager stemmer would
    destroy — and B1.2 must not introduce one.
    """
    assessed = assess_fact_quality(
        answer_uri=CARBON,
        predicate_uri="http://dbpedia.org/property/formula",
        direction="IN",
        counterpart_uri="http://dbpedia.org/resource/Boron_carbide",
        policy=quality_policy)
    assert assessed.leakage.hard_leak is False
    assert assessed.eligible is True


# --------------------------------------------------------------------------
# B1.2-T7. Display safety — parentheses and Roman numerals survive
# --------------------------------------------------------------------------


@requires_pinned_kg
def test_b12_t7_parentheticals_survive_the_whole_b12_path(einstein_facts):
    """Disambiguating parentheses are part of the entity's name, not noise.

    Both an eligible and an ineligible fact are checked: an ineligible fact still
    has to carry a correct label, because it is what a reviewer reads when
    checking why the hard filter removed it.
    """
    facts = by_identity(einstein_facts)
    young = facts[("http://dbpedia.org/property/influenced", "IN",
                   "http://dbpedia.org/resource/Thomas_Young_(scientist)")]
    crater = facts[("http://dbpedia.org/property/eponym", "IN",
                    "http://dbpedia.org/resource/Einstein_(crater)")]
    assert young.display_label == "Thomas Young (scientist)"
    assert young.eligible is True
    assert crater.display_label == "Einstein (crater)"
    assert crater.eligible is False


@requires_pinned_kg
def test_b12_t7_diacritics_survive_and_underscores_become_spaces(einstein_facts):
    facts = by_identity(einstein_facts)
    assert facts[("http://dbpedia.org/property/spouse", "OUT",
                  "http://dbpedia.org/resource/Mileva_Marić")
                 ].display_label == "Mileva Marić"


@pytest.mark.parametrize("uri,expected", [
    ("http://dbpedia.org/resource/Iron(III)_chloride", "Iron(III) chloride"),
    ("http://dbpedia.org/resource/Iron(II)_chloride", "Iron(II) chloride"),
    ("http://dbpedia.org/resource/Chromium(VI)_oxide", "Chromium(VI) oxide"),
])
def test_b12_t7_chemical_roman_numerals_are_preserved(uri, expected,
                                                      quality_policy):
    """Iron(III) chloride and Iron(II) chloride are DIFFERENT compounds.

    The legacy ``remove_parenthetical()`` turned both into "Iron chloride",
    misnaming the entity and collapsing two choices onto one label. These three
    are not in the pilot Answers' neighbourhoods, so they are pinned on the same
    frozen assessor B1.2 calls — the display path is shared, so this is the same
    label the adapter would emit for them.
    """
    assessed = assess_fact_quality(
        answer_uri="http://dbpedia.org/resource/Sulfuric_acid",
        predicate_uri="http://dbpedia.org/property/formula",
        direction="IN", counterpart_uri=uri, policy=quality_policy)
    assert assessed.display_label == expected


# --------------------------------------------------------------------------
# B1.2-T8. B1.2 performs NO evidence classification
# --------------------------------------------------------------------------


def b12_function_nodes():
    """The AST of the two functions B1.2 added, and nothing else."""
    tree = ast.parse(INPUTS_SOURCE.read_text("utf-8"))
    wanted = {"answer_facts_from_local_kg", "answer_node_index"}
    found = [node for node in ast.walk(tree)
             if isinstance(node, ast.FunctionDef) and node.name in wanted]
    assert {node.name for node in found} == wanted
    return found


def test_b12_t8_no_evidence_classification_happens_inside_the_b12_functions():
    """``classify_fact_against_candidate`` needs a candidate; B1.2 has no roster.

    B1.3 legitimately imports the classifier at module level, so this assertion
    is scoped to the two B1.2 functions rather than to the file. What it protects
    is unchanged and is the reason B1.2 and B1.3 are separate steps: the Answer's
    own fact inventory is decided without reference to any candidate, and a level
    produced inside it could only have been invented.
    """
    for function in b12_function_nodes():
        called = {node.func.id for node in ast.walk(function)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert "classify_fact_against_candidate" not in called, function.name
        assert "RationaleProposition" not in called, function.name


def test_b12_t8_the_b12_functions_build_no_answer_fact_and_no_levels():
    """No ``AnswerFact``, and none of the three per-candidate axes, anywhere in B1.2.

    An evidence level belongs to an ordered (Answer fact, candidate) pair. B1.2
    has no candidate roster, so a level produced here could only be invented.
    """
    banned_names = {"AnswerFact", "classify_fact_against_candidate",
                    "select_distractors", "build_case"}
    banned_fields = {"levels", "exclusion_bases", "granularity_risks"}
    for function in b12_function_nodes():
        for node in ast.walk(function):
            if isinstance(node, ast.Name):
                assert node.id not in banned_names, (function.name, node.id)
            if isinstance(node, ast.Attribute):
                assert node.attr not in banned_fields, (function.name, node.attr)
            if isinstance(node, ast.keyword):
                assert node.arg not in banned_fields, (function.name, node.arg)


@requires_pinned_kg
def test_b12_t8_the_returned_records_carry_no_level_attribute(einstein_facts):
    """The runtime counterpart: FactQuality has the eleven fields and no twelfth."""
    for fact in einstein_facts:
        assert not hasattr(fact, "levels")
        assert not hasattr(fact, "exclusion_bases")
        assert not hasattr(fact, "granularity_risks")
    assert set(vars(einstein_facts[0])) == set(QUALITY_FIELDS)


@requires_pinned_kg
def test_b12_t8_albert_einstein_still_has_no_answer_case(pinned_kg,
                                                         quality_policy):
    """Facts are not a case. Einstein has 66 facts and still no candidate roster.

    B1.3 is where a roster could come from, and it has not been started.
    """
    assert len(answer_facts_from_local_kg(EINSTEIN, local_kg=pinned_kg,
                                          quality_policy=quality_policy)) == 66
    with pytest.raises(AnswerNotFoundError):
        case_from_frozen_records(EINSTEIN, handoff_path=HANDOFF,
                                 evidence_path=EVIDENCE)


# --------------------------------------------------------------------------
# B1.2-T9 and B1.2-T10. Zero network, one graph load, frozen kernel
# --------------------------------------------------------------------------


@requires_pinned_kg
def test_b12_t9_the_real_einstein_extraction_attempted_no_connection(
        einstein_facts):
    """The guard was installed AROUND the acceptance-gate extraction itself."""
    assert len(einstein_facts) == 66
    assert NETWORK_ATTEMPTS == []


@requires_pinned_kg
def test_b12_t9_the_pinned_graph_was_loaded_exactly_once(einstein_facts):
    """One module-scoped load for the whole B1.2 group: 1.2 GB read one time."""
    assert PINNED_KG_LOADS == [str(PINNED_KG)]


@requires_pinned_kg
def test_b12_t9_the_loaded_graph_is_the_pinned_build(pinned_kg):
    """A rebuilt graph renumbers every node, so the digest is checked, not assumed."""
    assert pinned_kg.source_sha256 == PINNED_KG_SHA256
    assert pinned_kg.source_path == PINNED_KG


def test_b12_t10_the_frozen_kernel_is_untouched_by_b12():
    """Restated in the B1.2 group: step 2 adds a reader, not a kernel change."""
    assert hashlib.sha256(CORE_SOURCE.read_bytes()).hexdigest() == FROZEN_KERNEL_SHA256


def test_b12_the_l2_wording_is_the_scientifically_accurate_one():
    """The over-broad "no L2 rule is implemented anywhere" claim is corrected.

    The frozen R1 layer DOES contain generic EvidenceProof/L2-proof machinery.
    What is true is that no L2 rule is currently activated and the frozen l2_rules
    set is empty, so the pilot has zero L2 incidences. Saying less than that would
    misdescribe the upstream code; saying more would claim a proof source exists.
    """
    text = INPUTS_SOURCE.read_text("utf-8")
    assert "No L2 rule is\n    implemented anywhere in this project" not in text
    assert "currently activated in the frozen offline policy" in text
    assert "no trustworthy L2 proof source/rule is active" in text


# ==========================================================================
# PHASE B1 STEP 3 — per-(fact, candidate) evidence, and semantic safety
# ==========================================================================
#
# B1.3 adds exactly one capability: given Answer facts and a ranked roster,
# produce the aligned evidence level, exclusion basis and granularity risk for
# every pair, by DELEGATING every scientific decision to the frozen R1 classifier.
#
# Two kinds of test, and both are needed.
#
#   the pilot gate       All 14,860 frozen (Answer fact, candidate) incidences
#                        are reconstructed and compared axis by axis. It is the
#                        only test that can show the delegation is wired to the
#                        same inputs the published run used. It cannot show the
#                        semantic behaviour, because the pilot happens to contain
#                        no granularity risk at all: 14,860 of 14,860 incidences
#                        are NONE on that axis.
#   semantic safety      Nine synthetic pins, each a single-edge graph, for the
#                        behaviours the pilot never exercises — canonical
#                        equivalence, both containment directions, an unavailable
#                        index, IN/OUT separation, a missing candidate node, and
#                        the scoped-empirical annotation. Without these, the two
#                        most dangerous failures in this step (an unavailable
#                        index silently reading as absence, and an IN object
#                        answering an OUT question) would both pass the gate.
#
# What is NOT tested here, because B1.3 must not do it: no distractor selection,
# no set-cover execution, no candidate roster for Albert Einstein, no class
# selection, no member retrieval, no LRoleSim, no verbalization.

from dataclasses import replace  # noqa: E402

from mcq_inputs import (  # noqa: E402
    candidate_objects_from_local_kg,
    levels_for_candidates,
)
from mcq_core import Candidate  # noqa: E402
from rationale_v3.evidence import (  # noqa: E402
    EvidenceRule,
    load_evidence_rules,
)
from rationale_v3.semantic_relations import (  # noqa: E402
    AncestorEdge,
    build_semantic_index,
    load_semantic_relation_policy,
    unavailable_semantic_index,
)
# The frozen R1 orchestration, imported READ-ONLY and for the pilot fixture only.
# It supplies the same Prompt-8D roster, the same semantic-index cache key and
# the same scoped-empirical rule derivation the published run used; reproducing
# any of those here would be a second implementation of the thing under test.
from pipeline.rationale_v3_run import (  # noqa: E402
    EVIDENCE_RULES_PATH,
    FROZEN_PROMPT8D_DIR,
    build_answer_inputs,
    derive_rulebook,
    load_pilot_semantic_index,
    load_prompt8d_handoff,
)

SEMANTIC_POLICY_PATH = (ROOT / "src" / "rationale_v3" / "policies"
                        / "semantic_relation_policy.json")

#: The frozen R1 pilot totals, re-counted for EVIDENCE_TAXONOMY_V1.md §8 and
#: restated here as the acceptance gate. They are TEST EXPECTATIONS: nothing in
#: the production module knows any of them.
PILOT_INCIDENCE_COUNT = 14_860
PILOT_ALL_FACT_LEVELS = {"NOT_COVERED": 313, "L0": 8_485, "L1": 6_062, "L2": 0}
PILOT_ELIGIBLE_FACT_LEVELS = {"NOT_COVERED": 313, "L0": 7_962, "L1": 5_981,
                              "L2": 0}
PILOT_SCOPED_EMPIRICAL_COUNT = 39

# --- the synthetic vocabulary ----------------------------------------------
# Real DBpedia URIs, because normalize_uri(), the traversal allowlist and the
# frozen equivalence table all key on real spellings. No triple below is claimed
# to be in the pinned snapshot: these are one-edge fixtures, not measurements.
BORN_IN = "http://dbpedia.org/property/birthPlace"
INFLUENCED = "http://dbpedia.org/property/influenced"
IS_PART_OF = "http://dbpedia.org/property/isPartOf"
TOKYO = "http://dbpedia.org/resource/Tokyo"
SHINJUKU = "http://dbpedia.org/resource/Shinjuku"
KYOTO = "http://dbpedia.org/resource/Kyoto"
# The one frozen redirect pair used below. It is in the R1 semantic policy's
# equivalence table, which is read offline from the Prompt-8B class-member file.
HERACLITUS = "http://dbpedia.org/resource/Heraclitus"
ANTISTHENES = "http://dbpedia.org/resource/Antisthenes_(Heraclitean)"
ANSWER = "http://dbpedia.org/resource/Synthetic_Answer"
DISTRACTOR = "http://dbpedia.org/resource/Synthetic_Distractor"
SYNTHETIC_SCOPE = "http://dbpedia.org/resource/Category:Synthetic_scope"


class SyntheticKG:
    """The smallest object ``observed_edge_set()`` accepts.

    Four attributes and one method, matching what ``kg.loader.LocalKG`` exposes
    to this adapter: ``index_url`` for index → URI, ``out_neighbor`` and
    ``in_neighbor`` for the one-hop adjacency, ``source_sha256`` so the frozen
    edge-set cache keys each fixture separately, and ``index_for_uri_or_none``.

    Every instance gets its own ``source_sha256``. That is not decoration: the
    frozen cache identity is ``(kg_identity, node, use_in, schema)``, and it is
    the component that stops one fixture's edges from being served to another —
    exactly the AUDIT EX-4 defect the corrected cache exists to prevent.
    """

    def __init__(self, name, triples):
        self.source_sha256 = f"synthetic-{name}"
        uris = sorted({uri for triple in triples for uri in triple})
        self.index_url = dict(enumerate(uris))
        self._index_for = {uri: index for index, uri in self.index_url.items()}
        self.out_neighbor: dict = {}
        self.in_neighbor: dict = {}
        for subject, predicate, obj in triples:
            s, p, o = (self._index_for[subject], self._index_for[predicate],
                       self._index_for[obj])
            self.out_neighbor.setdefault(s, []).append((p, o))
            self.in_neighbor.setdefault(o, []).append((p, s))

    def index_for_uri_or_none(self, uri):
        return self._index_for.get(uri)


def synthetic_quality(predicate_uri, direction, counterpart_uri):
    """One FactQuality standing in for a B1.2 record.

    ``eligible`` is True throughout: B1.3 consumes the quality verdict and never
    re-derives it, so these tests must not depend on re-deriving it either.
    """
    return FactQuality(
        predicate_uri=predicate_uri, direction=direction,
        counterpart_uri=counterpart_uri, display_label="synthetic",
        eligible=True, soft_leak=False, verbalizable=False, pedagogical_tier=3,
        label_length=9, token_count=1, template_id="VERBALIZABLE_UNKNOWN")


def containment_index():
    """An AVAILABLE index in which Shinjuku lies under Tokyo.

    One allowlisted ``dbp:isPartOf`` edge, walked by the frozen bounded closure.
    The policy is the real frozen one, so the allowlist, the depth bound and the
    frozen redirect table are the published ones and not a local invention.
    """
    policy = load_semantic_relation_policy(SEMANTIC_POLICY_PATH)
    return build_semantic_index(policy=policy, parent_edges=[AncestorEdge(
        child_uri=SHINJUKU, parent_uri=TOKYO,
        rule_id="PLACE_CONTAINMENT_IS_PART_OF_V1", predicate_uri=IS_PART_OF,
        relation_kind="ADMINISTRATIVE_PLACE_CONTAINMENT")])


def missing_index():
    """An index that answers SEMANTIC_RELATION_UNAVAILABLE for every walk.

    Canonical equality still works — normalization and the frozen redirect table
    need no graph — which is why "index unavailable" is not "nothing is known".
    """
    return unavailable_semantic_index(
        load_semantic_relation_policy(SEMANTIC_POLICY_PATH),
        "withheld by a B1.3 semantic-safety test")


def empty_rulebook():
    """The frozen evidence policy with nothing derived: no annotation can fire."""
    return load_evidence_rules(EVIDENCE_RULES_PATH)


def classify_one(*, triples, quality, index=None, rulebook=None,
                 scope=SYNTHETIC_SCOPE, candidate_uri=DISTRACTOR, name="kg"):
    """Classify ONE fact against ONE candidate; return (level, basis, risk)."""
    facts = levels_for_candidates(
        (quality,), (Candidate(rank=1, score=0.5, uri=candidate_uri),),
        local_kg=SyntheticKG(name, triples),
        semantic_index=containment_index() if index is None else index,
        rulebook=empty_rulebook() if rulebook is None else rulebook,
        scope=scope)
    assert len(facts) == 1
    fact = facts[0]
    return (fact.levels[0], fact.exclusion_bases[0], fact.granularity_risks[0])


# --------------------------------------------------------------------------
# B1.3-T1. The pilot gate — all 14,860 incidences, three axes, no tolerance
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pilot_prompt8d_inputs():
    """The frozen Prompt-8D handoff, which is also the semantic cache's key."""
    return load_prompt8d_handoff(FROZEN_PROMPT8D_DIR)


@pytest.fixture(scope="module")
def pilot_answer_inputs(pilot_prompt8d_inputs):
    return build_answer_inputs(pilot_prompt8d_inputs)


@pytest.fixture(scope="module")
def pilot_semantic_index(pilot_prompt8d_inputs):
    """The cached pilot index, keyed on the pinned KG, the policy and the pilot.

    ``SemanticIndexCacheKey`` digests the exact counterpart-URI set the run
    reasons about, so a cache built for a different pilot is refused rather than
    reused. The reconstruction is only comparable to the frozen audit when this
    key matches, which is asserted below rather than assumed.
    """
    return load_pilot_semantic_index(pilot_prompt8d_inputs)


@pytest.fixture(scope="module")
def pilot_rulebook(pilot_answer_inputs, pilot_semantic_index, quality_policy):
    """The SAME derived rulebook the frozen R1 run used.

    Derivation is the frozen R1 code, called read-only. B1.3 production code
    derives no rule: it receives an already-prepared rulebook, because a support
    threshold invented at classification time would be a second, unpublished
    threshold.
    """
    book, _per_scope = derive_rulebook(
        pilot_answer_inputs, base=load_evidence_rules(EVIDENCE_RULES_PATH),
        semantic_index=pilot_semantic_index,
        rejected_predicates=quality_policy.hard_reject_predicates)
    return book


def frozen_r1_incidences():
    """``{(answer, fact identity, candidate): (level, basis, risk)}`` — the oracle.

    Read from the frozen R1 evidence audit, which is never an input to the
    reconstruction it grades.
    """
    frozen: dict = {}
    for record in read_jsonl(EVIDENCE):
        if record.get("record_type") != "answer_fact_evidence":
            continue
        quality = record["quality"]
        identity = (quality["predicate_uri"], quality["direction"],
                    quality["counterpart_uri"])
        for row in record["per_candidate"]:
            frozen[(record["answer_uri"], identity, row["candidate_uri"])] = (
                row["evidence_level"], row["exclusion_basis"],
                row["granularity_risk"])
    return frozen


@pytest.fixture(scope="module")
def pilot_reconstruction(pinned_kg, quality_policy, pilot_answer_inputs,
                         pilot_semantic_index, pilot_rulebook):
    """Every pilot incidence, rebuilt through the production function ONCE.

    Returns ``{(answer, fact identity, candidate): (level, basis, risk)}`` plus
    the eligibility of each fact, so the level totals can be reported both over
    all facts and over eligible facts alone without a second reconstruction.
    """
    with no_network(NETWORK_ATTEMPTS):
        rebuilt: dict = {}
        eligible: dict = {}
        for answer in pilot_answer_inputs:
            facts = answer_facts_from_local_kg(
                answer.answer_uri, local_kg=pinned_kg,
                quality_policy=quality_policy)
            candidates = tuple(
                Candidate(rank=view.rank, score=view.score,
                          uri=view.canonical_candidate_uri)
                for view in answer.ranked_candidates)
            for fact in levels_for_candidates(
                    facts, candidates, local_kg=pinned_kg,
                    semantic_index=pilot_semantic_index,
                    rulebook=pilot_rulebook, scope=answer.scope):
                identity = fact.quality.identity
                eligible[(answer.answer_uri, identity)] = fact.quality.eligible
                for position, candidate in enumerate(candidates):
                    rebuilt[(answer.answer_uri, identity, candidate.uri)] = (
                        fact.levels[position], fact.exclusion_bases[position],
                        fact.granularity_risks[position])
        return (rebuilt, eligible)


@requires_pinned_kg
def test_b13_t1_the_pilot_semantic_index_cache_key_matches(pilot_semantic_index):
    """The comparison below is meaningless if a different index was loaded."""
    assert pilot_semantic_index.available
    assert pilot_semantic_index.unavailable_reason == ""
    assert pilot_semantic_index.cache_key.pinned_kg_sha256 == PINNED_KG_SHA256


@requires_pinned_kg
def test_b13_t1_every_frozen_incidence_is_reconstructed(pilot_reconstruction):
    """14,860 incidences rebuilt, none missing, none invented."""
    rebuilt, _eligible = pilot_reconstruction
    frozen = frozen_r1_incidences()
    assert len(frozen) == PILOT_INCIDENCE_COUNT
    assert len(rebuilt) == PILOT_INCIDENCE_COUNT
    assert sorted(rebuilt) == sorted(frozen)


@requires_pinned_kg
def test_b13_t1_all_three_axes_agree_on_every_incidence(pilot_reconstruction):
    """Zero classification discrepancies. No tolerance, and no special case.

    A failure here is NOT to be silenced by exempting the offending pair: the
    reported difference names the Answer, the fact identity, the candidate and
    both verdicts, and it means the delegation is reading different inputs than
    the published run did.
    """
    rebuilt, _eligible = pilot_reconstruction
    frozen = frozen_r1_incidences()
    differences = [
        {"answer_uri": key[0], "fact_identity": key[1], "candidate_uri": key[2],
         "expected": frozen.get(key), "reconstructed": value}
        for key, value in sorted(rebuilt.items()) if frozen.get(key) != value]
    assert differences == []


@requires_pinned_kg
def test_b13_t1_the_all_fact_level_totals_are_the_published_ones(
        pilot_reconstruction):
    """313 / 8,485 / 6,062 / 0 over all facts, eligible and ineligible alike."""
    rebuilt, _eligible = pilot_reconstruction
    counts = dict.fromkeys(PILOT_ALL_FACT_LEVELS, 0)
    for level, _basis, _risk in rebuilt.values():
        counts[level] += 1
    assert counts == PILOT_ALL_FACT_LEVELS
    assert sum(counts.values()) == PILOT_INCIDENCE_COUNT


@requires_pinned_kg
def test_b13_t1_the_eligible_fact_level_totals_are_the_published_ones(
        pilot_reconstruction):
    """313 / 7,962 / 5,981 / 0 among facts the frozen hard filter kept.

    The ineligible facts are still classified and still returned. Dropping them
    would make the fact indices unstable and would hide from a reviewer which
    facts the hard filter removed.
    """
    rebuilt, eligible = pilot_reconstruction
    counts = dict.fromkeys(PILOT_ELIGIBLE_FACT_LEVELS, 0)
    for (answer_uri, identity, _candidate), (level, _b, _r) in rebuilt.items():
        if eligible[(answer_uri, identity)]:
            counts[level] += 1
    assert counts == PILOT_ELIGIBLE_FACT_LEVELS


@requires_pinned_kg
def test_b13_t1_no_l2_is_activated_anywhere_in_the_pilot(pilot_reconstruction,
                                                         pilot_rulebook):
    """Zero L2 is the CORRECT offline outcome, not a gap.

    DBpedia infobox properties carry no functional, cardinality, disjointness or
    negative-assertion declaration that could be trusted offline, so the frozen
    policy activates no L2 rule. The rulebook is checked as well as the output:
    zero L2 incidences produced by zero active L2 rules is a different statement
    from zero incidences that happened to miss.
    """
    rebuilt, _eligible = pilot_reconstruction
    assert pilot_rulebook.counts()["active_l2_rules"] == 0
    assert [key for key, value in rebuilt.items() if value[0] == "L2"] == []
    assert [key for key, value in rebuilt.items()
            if value[1] == "FORMAL_PROOF"] == []


@requires_pinned_kg
def test_b13_t1_scoped_empirical_annotates_39_l1_incidences_and_no_l0(
        pilot_reconstruction):
    """39 annotations, every one on an existing L1, none creating a level.

    ``SCOPED_EMPIRICAL`` is an annotation on the separate exclusion-basis axis,
    not a fourth level. ``L0 + SCOPED_EMPIRICAL`` would claim empirical support
    for something never observed and is invalid by EVIDENCE_TAXONOMY_V1.md §4.
    """
    rebuilt, _eligible = pilot_reconstruction
    annotated = [key for key, value in rebuilt.items()
                 if value[1] == "SCOPED_EMPIRICAL"]
    assert len(annotated) == PILOT_SCOPED_EMPIRICAL_COUNT
    assert {rebuilt[key][0] for key in annotated} == {"L1"}


@requires_pinned_kg
def test_b13_t1_the_reconstruction_attempted_no_connection(pilot_reconstruction):
    """The guard was installed AROUND the acceptance-gate reconstruction itself."""
    rebuilt, _eligible = pilot_reconstruction
    assert len(rebuilt) == PILOT_INCIDENCE_COUNT
    assert NETWORK_ATTEMPTS == []


@requires_pinned_kg
def test_b13_t1_the_pinned_graph_is_still_loaded_exactly_once(
        pilot_reconstruction):
    """B1.2 and B1.3 share one module-scoped load: 1.2 GB read one time."""
    assert PINNED_KG_LOADS == [str(PINNED_KG)]


# --------------------------------------------------------------------------
# B1.3-T2. Semantic safety — the behaviours the pilot never exercises
# --------------------------------------------------------------------------


def test_b13_t2_exact_object_equality_is_not_covered():
    """The candidate holds the very object claimed, so the fact distinguishes
    nobody at that position — and NOT_COVERED is tested before L0 and L1."""
    assert classify_one(
        name="exact", triples=[(DISTRACTOR, BORN_IN, TOKYO)],
        quality=synthetic_quality(BORN_IN, "OUT", TOKYO)) == (
            "NOT_COVERED", "NONE", "NONE")


def test_b13_t2_a_canonically_equivalent_object_is_not_covered():
    """A frozen redirect pair is ONE entity, not two.

    String equality would call this an observed alternative and publish a
    difference that does not exist. The equivalence table is read offline from
    the Prompt-8B class-member file; nothing here performs a live lookup.
    """
    assert classify_one(
        name="redirect", triples=[(DISTRACTOR, INFLUENCED, ANTISTHENES)],
        quality=synthetic_quality(INFLUENCED, "OUT", HERACLITUS)) == (
            "NOT_COVERED", "NONE", "NONE")


def test_b13_t2_a_candidate_object_under_the_claim_is_not_covered():
    """Claim *Tokyo*, candidate *Shinjuku*: asserting the ward ENTAILS the city.

    The candidate supports the Answer proposition, so the fact covers nobody
    here. This is the only containment direction that removes contrast.
    """
    assert classify_one(
        name="under-claim", triples=[(DISTRACTOR, BORN_IN, SHINJUKU)],
        quality=synthetic_quality(BORN_IN, "OUT", TOKYO)) == (
            "NOT_COVERED", "NONE", "NONE")


def test_b13_t2_a_claim_under_the_candidate_object_is_l1_plus_a_risk():
    """Claim *Shinjuku*, candidate *Tokyo*: a RISK, never an exclusion.

    The reverse containment neither supports nor contradicts the claim: the two
    articles were written at different granularities, so the apparent contrast
    may be an artefact of that. The observational level stands, and the doubt is
    recorded on the separate granularity axis, where it orders against the fact
    and blocks main-corpus eligibility without pretending to be evidence.
    """
    assert classify_one(
        name="over-claim", triples=[(DISTRACTOR, BORN_IN, TOKYO)],
        quality=synthetic_quality(BORN_IN, "OUT", SHINJUKU)) == (
            "L1", "NONE", "CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT")


def test_b13_t2_an_unavailable_index_keeps_l1_and_never_becomes_l0():
    """"We did not look" is not "we found nothing". THE R1 CORRECTION.

    With no index the observed alternative value is still observed; only the
    containment question is unanswered. Downgrading to L0 would relabel a
    positive observation as a snapshot absence — a false statement about the
    snapshot — so the level is preserved and the doubt is recorded as
    UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE.
    """
    level, basis, risk = classify_one(
        name="no-index", triples=[(DISTRACTOR, BORN_IN, KYOTO)],
        quality=synthetic_quality(BORN_IN, "OUT", TOKYO), index=missing_index())
    assert (level, basis, risk) == (
        "L1", "NONE", "UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE")
    assert level != "L0"


def test_b13_t2_canonical_equivalence_still_works_without_an_index():
    """An unavailable index must not silently disable the redirect check too.

    Normalization and the frozen equivalence table need no graph, so a missing
    cache leaves canonical identity intact. Were this to regress, a redirect pair
    would be published as a difference whenever the index was unavailable.
    """
    assert classify_one(
        name="no-index-redirect", triples=[(DISTRACTOR, INFLUENCED, ANTISTHENES)],
        quality=synthetic_quality(INFLUENCED, "OUT", HERACLITUS),
        index=missing_index()) == ("NOT_COVERED", "NONE", "NONE")


def test_b13_t2_a_candidate_with_no_object_under_the_key_is_l0():
    """``O_d(κ) = ∅`` is the ONLY thing that may produce L0.

    The candidate is in the graph and records something — under a different key.
    """
    assert classify_one(
        name="absent-key",
        triples=[(DISTRACTOR, INFLUENCED, KYOTO)],
        quality=synthetic_quality(BORN_IN, "OUT", TOKYO)) == (
            "L0", "NONE", "NONE")


def test_b13_t2_a_different_observed_object_is_l1_under_a_multi_valued_predicate():
    """An OBSERVED alternative value, and nothing stronger.

    ``dbp:influenced`` is multi-valued, so the candidate may hold the Answer's
    object as well without this snapshot recording it. L1 reports what the
    snapshot shows; it does not establish that the candidate could not also hold
    the claim object, which is why the strength lives on the exclusion-basis axis.
    """
    assert classify_one(
        name="alternative",
        triples=[(DISTRACTOR, INFLUENCED, KYOTO), (DISTRACTOR, INFLUENCED, TOKYO)],
        quality=synthetic_quality(INFLUENCED, "OUT", HERACLITUS)) == (
            "L1", "NONE", "NONE")


@pytest.mark.parametrize("direction,other", [("OUT", "IN"), ("IN", "OUT")])
def test_b13_t2_in_and_out_object_sets_never_mix(direction, other):
    """An object observed under ``(p, OUT)`` may never answer ``(p, IN)``.

    The candidate holds the claim object in the OTHER direction only. If the two
    sets merged, that would read as support and silence the fact; keeping them
    apart makes it the absence it is. ``dbp:influenced`` OUT is "influenced" and
    IN is "was influenced by" — different relations, different extensions,
    different verbalizations.
    """
    triples = ([(DISTRACTOR, INFLUENCED, TOKYO)] if other == "OUT"
               else [(TOKYO, INFLUENCED, DISTRACTOR)])
    assert classify_one(
        name=f"direction-{direction}", triples=triples,
        quality=synthetic_quality(INFLUENCED, direction, TOKYO)) == (
            "L0", "NONE", "NONE")


def test_b13_t2_the_two_directions_are_gathered_into_separate_keys():
    """The same predicate and the same counterpart, both ways, stay two keys."""
    observed = candidate_objects_from_local_kg(
        DISTRACTOR, local_kg=SyntheticKG("both-directions", [
            (DISTRACTOR, INFLUENCED, TOKYO), (KYOTO, INFLUENCED, DISTRACTOR)]))
    assert observed[(INFLUENCED, "OUT")] == (TOKYO,)
    assert observed[(INFLUENCED, "IN")] == (KYOTO,)


def test_b13_t2_a_candidate_missing_from_the_graph_raises_instead_of_l0():
    """"Absent from the graph" is NOT "present and recording nothing".

    Returning an empty object set for an unresolvable candidate would turn a
    roster/graph mismatch into the strongest L0 profile the model can produce,
    against every Answer fact at once, and every one of those levels would be
    fabricated. So it raises, naming the URI.
    """
    with pytest.raises(InputContractError) as error:
        classify_one(
            name="missing-candidate", triples=[(DISTRACTOR, BORN_IN, TOKYO)],
            quality=synthetic_quality(BORN_IN, "OUT", TOKYO),
            candidate_uri="http://dbpedia.org/resource/Not_A_Node")
    message = str(error.value)
    assert "Not_A_Node" in message
    assert "NOT an empty observed object set" in message


def test_b13_t2_scoped_empirical_annotates_an_existing_l1():
    """An ACTIVE scoped rule strengthens the READING of an L1; the level is L1.

    The rule is a local, empirical observation over one named scope — never
    universal functionality, and never described as such.
    """
    rule = EvidenceRule(
        rule_id="EMP_SV_SYNTHETIC_OUT_birthPlace_MS5_V1",
        rule_type="EMPIRICALLY_SINGLE_VALUED_IN_SCOPE",
        predicate_uri=BORN_IN, direction="OUT", scope=SYNTHETIC_SCOPE,
        scope_kind="SELECTED_LOCAL_CLASS_CANDIDATE_POOL",
        required_evidence=("observed_support >= 5",), minimum_support=5,
        observed_support=6, maximum_observed_cardinality=1,
        observed_violation_count=0, source="a B1.3 semantic-safety test",
        provenance="synthetic", version="test", activation_status="ACTIVE",
        empirical_label="EMPIRICAL_AND_SCOPED_NOT_UNIVERSAL")
    assert classify_one(
        name="annotated", triples=[(DISTRACTOR, BORN_IN, KYOTO)],
        quality=synthetic_quality(BORN_IN, "OUT", TOKYO),
        rulebook=empty_rulebook().with_rules([rule])) == (
            "L1", "SCOPED_EMPIRICAL", "NONE")


def test_b13_t2_scoped_empirical_never_creates_a_level_out_of_an_absence():
    """The SAME active rule against a candidate with nothing observed: still L0.

    An annotation may never create, upgrade or rescue a level, and
    ``L0 + SCOPED_EMPIRICAL`` is invalid by EVIDENCE_TAXONOMY_V1.md §4.
    """
    rule = EvidenceRule(
        rule_id="EMP_SV_SYNTHETIC_OUT_birthPlace_MS5_V1",
        rule_type="EMPIRICALLY_SINGLE_VALUED_IN_SCOPE",
        predicate_uri=BORN_IN, direction="OUT", scope=SYNTHETIC_SCOPE,
        scope_kind="SELECTED_LOCAL_CLASS_CANDIDATE_POOL",
        required_evidence=("observed_support >= 5",), minimum_support=5,
        observed_support=6, maximum_observed_cardinality=1,
        observed_violation_count=0, source="a B1.3 semantic-safety test",
        provenance="synthetic", version="test", activation_status="ACTIVE",
        empirical_label="EMPIRICAL_AND_SCOPED_NOT_UNIVERSAL")
    assert classify_one(
        name="annotated-absence", triples=[(DISTRACTOR, INFLUENCED, KYOTO)],
        quality=synthetic_quality(BORN_IN, "OUT", TOKYO),
        rulebook=empty_rulebook().with_rules([rule])) == ("L0", "NONE", "NONE")


def test_b13_t2_a_rule_derived_for_another_scope_does_not_fire():
    """Scope is part of the match: a rule is LOCAL to the class it was derived in.

    Its scope note says it claims nothing about the predicate outside that pool,
    so silently applying it elsewhere would publish a stronger reading than was
    ever observed.
    """
    rule = EvidenceRule(
        rule_id="EMP_SV_OTHER_OUT_birthPlace_MS5_V1",
        rule_type="EMPIRICALLY_SINGLE_VALUED_IN_SCOPE",
        predicate_uri=BORN_IN, direction="OUT",
        scope="http://dbpedia.org/resource/Category:Another_scope",
        scope_kind="SELECTED_LOCAL_CLASS_CANDIDATE_POOL",
        required_evidence=("observed_support >= 5",), minimum_support=5,
        observed_support=6, maximum_observed_cardinality=1,
        observed_violation_count=0, source="a B1.3 semantic-safety test",
        provenance="synthetic", version="test", activation_status="ACTIVE",
        empirical_label="EMPIRICAL_AND_SCOPED_NOT_UNIVERSAL")
    assert classify_one(
        name="other-scope", triples=[(DISTRACTOR, BORN_IN, KYOTO)],
        quality=synthetic_quality(BORN_IN, "OUT", TOKYO),
        rulebook=empty_rulebook().with_rules([rule])) == ("L1", "NONE", "NONE")


# --------------------------------------------------------------------------
# B1.3-T3. Alignment, delegation and the phase boundary
# --------------------------------------------------------------------------


def test_b13_t3_the_three_tuples_are_aligned_to_the_roster_order():
    """levels[i] describes candidate i, in the order the roster was given.

    Built by position, never by ``zip()``: a zip against a short sequence would
    stop early and silently re-point every later level at the wrong candidate.
    """
    graph = SyntheticKG("aligned", [
        (ANSWER, BORN_IN, TOKYO),
        ("http://dbpedia.org/resource/D1", BORN_IN, TOKYO),      # supports
        ("http://dbpedia.org/resource/D2", BORN_IN, KYOTO),      # alternative
        ("http://dbpedia.org/resource/D3", INFLUENCED, KYOTO)])  # nothing at κ
    candidates = tuple(
        Candidate(rank=rank, score=1.0 / rank,
                  uri=f"http://dbpedia.org/resource/D{rank}")
        for rank in (1, 2, 3))
    facts = levels_for_candidates(
        (synthetic_quality(BORN_IN, "OUT", TOKYO),), candidates,
        local_kg=graph, semantic_index=containment_index(),
        rulebook=empty_rulebook(), scope=SYNTHETIC_SCOPE)
    assert facts[0].levels == ("NOT_COVERED", "L1", "L0")
    assert facts[0].exclusion_bases == ("NONE", "NONE", "NONE")
    assert facts[0].granularity_risks == ("NONE", "NONE", "NONE")


def test_b13_t3_the_quality_record_is_carried_through_untouched():
    """B1.3 adds three axes and re-derives no quality field.

    ``eligible`` in particular is the frozen R1 hard filter, decided in B1.2 and
    consumed here as already decided.
    """
    quality = synthetic_quality(BORN_IN, "OUT", TOKYO)
    ineligible = replace(quality, eligible=False)
    facts = levels_for_candidates(
        (quality, ineligible),
        (Candidate(rank=1, score=0.5, uri=DISTRACTOR),),
        local_kg=SyntheticKG("carried", [(DISTRACTOR, BORN_IN, KYOTO)]),
        semantic_index=containment_index(), rulebook=empty_rulebook(),
        scope=SYNTHETIC_SCOPE)
    assert facts[0].quality is quality
    # An ineligible fact keeps its position and is still classified: dropping it
    # would move every later fact index and hide what the hard filter removed.
    assert facts[1].quality is ineligible
    assert [fact.levels for fact in facts] == [("L1",), ("L1",)]


def test_b13_t3_every_produced_value_is_inside_the_frozen_vocabulary():
    """Invariant 2 restated on the produced axes, not merely on read ones."""
    graph = SyntheticKG("vocabulary", [
        (DISTRACTOR, BORN_IN, KYOTO), (DISTRACTOR, INFLUENCED, TOKYO)])
    facts = levels_for_candidates(
        (synthetic_quality(BORN_IN, "OUT", TOKYO),
         synthetic_quality(INFLUENCED, "OUT", TOKYO)),
        (Candidate(rank=1, score=0.5, uri=DISTRACTOR),),
        local_kg=graph, semantic_index=containment_index(),
        rulebook=empty_rulebook(), scope=SYNTHETIC_SCOPE)
    for fact in facts:
        assert set(fact.levels) <= ALLOWED_EVIDENCE_LEVELS
        assert set(fact.exclusion_bases) <= ALLOWED_EXCLUSION_BASES
        assert set(fact.granularity_risks) <= ALLOWED_GRANULARITY_RISKS
        assert [pair for pair in FORBIDDEN_LEVEL_BASIS_COMBINATIONS
                if pair in set(zip(fact.levels, fact.exclusion_bases))] == []


def test_b13_t3_no_evidence_rule_is_restated_in_the_adapter_source():
    """The decision tree stays upstream. B1.3 gathers inputs and copies verdicts.

    Reason codes and proof internals are upstream audit information and are not
    part of the ``AnswerCase`` contract, so they are not copied out either.
    """
    text = INPUTS_SOURCE.read_text("utf-8")
    for banned in ("build_l2_proof", "is_descendant_of", "SemanticIndexCacheKey",
                   "build_semantic_index", "load_semantic_index_cache",
                   "derive_empirical_single_valued_rules",
                   "observe_scope_cardinalities", "reason_code",
                   "L2_REASON_FOR_RULE_TYPE", "minimum_support"):
        assert banned not in text, banned


def test_b13_t3_the_adapter_still_imports_only_frozen_offline_modules():
    """B1.3 widens the AST allowlist by nothing: ``rationale_v3`` was already in."""
    allowed = {"__future__", "json", "pathlib", "typing", "mcq_core",
               "rationale_v3", "selection"}
    tree = ast.parse(INPUTS_SOURCE.read_text("utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= allowed, sorted(imported - allowed)


def test_b13_t3_the_frozen_kernel_is_untouched_by_b13():
    """Restated in the B1.3 group: step 3 adds a caller, not a kernel change."""
    assert hashlib.sha256(CORE_SOURCE.read_bytes()).hexdigest() == FROZEN_KERNEL_SHA256


def test_b13_t3_b14_has_not_been_started():
    """No distractor selection, no set cover, no Einstein roster in this module.

    ``build_case()`` stays imported and stays used by B1.1; what B1.4 would add
    is the step AFTER it — calling the kernel — and no name from that step
    appears anywhere in the adapter.
    """
    text = INPUTS_SOURCE.read_text("utf-8")
    for banned in ("build_and_select", "select_distractors", "Selection",
                   "set_cover", "setcover", "PoolPolicy", "force_pool"):
        assert banned not in text, banned


@requires_pinned_kg
def test_b13_t3_albert_einstein_still_has_no_candidate_roster(pinned_kg,
                                                              quality_policy):
    """66 facts and still nothing to classify them against.

    A roster for Albert Einstein needs an approved class decision and a class
    member list, and the class member list is the one true network dependency in
    this project. B1.3 does not manufacture one.
    """
    facts = answer_facts_from_local_kg(EINSTEIN, local_kg=pinned_kg,
                                       quality_policy=quality_policy)
    assert len(facts) == 66
    with pytest.raises(AnswerNotFoundError):
        case_from_frozen_records(EINSTEIN, handoff_path=HANDOFF,
                                 evidence_path=EVIDENCE)
    # levels_for_candidates() with no candidates produces no evidence at all,
    # rather than a default level per fact. There is nothing to be evidence
    # against, and a level invented here would be a level from nowhere.
    built = levels_for_candidates(facts, (), local_kg=pinned_kg,
                                  semantic_index=missing_index(),
                                  rulebook=empty_rulebook(),
                                  scope="http://dbpedia.org/resource/Category:None")
    assert [fact.levels for fact in built] == [()] * len(facts)
