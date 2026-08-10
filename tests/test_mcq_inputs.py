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

No network, no pinned-KG load, no model. Every input is a frozen file under
``outputs/``.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
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
    case_from_frozen_records,
    case_from_records,
    find_evidence_records,
    find_ranking_record,
    frozen_answer_uris,
    read_jsonl,
    validate_fact_alignment,
)

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
    """One AST scan covers test coupling, network clients and NLP toolkits."""
    allowed = {"__future__", "json", "pathlib", "typing", "mcq_core"}
    tree = ast.parse(INPUTS_SOURCE.read_text("utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= allowed, sorted(imported - allowed)


def test_no_forbidden_module_is_named_in_the_adapter_source():
    """Explicit list, so a future edit that adds one fails loudly."""
    forbidden = ["requests", "urllib", "http.client", "socket", "SPARQLWrapper",
                 "rdflib", "spacy", "nltk", "wordnet", "gensim", "torch",
                 "transformers", "sentence_transformers", "sklearn", "openai",
                 "anthropic", "test_mcq_core", "rationale_v3", "pickle"]
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
