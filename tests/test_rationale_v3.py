############################################################################
# tests/test_rationale_v3.py
#
# Contract tests for the rationale V3 layer, revision R1:
#   src/rationale_v3/{contracts,semantic_relations,evidence,quality,setcover,
#                     selector}.py
#   src/pipeline/rationale_v3_run.py
#   src/extract_and_select_distractors_v3.py   (mode dispatch only)
#
# WHAT THESE TESTS DEFEND
#   * the CORRECTED taxonomy: an observed alternative object is L1 whatever the
#     predicate's cardinality, an empty object set is L0, and a supporting
#     object is NOT_COVERED before any rule runs;
#   * a scoped empirical rule ANNOTATES an L1 with SCOPED_EMPIRICAL and can
#     neither create nor destroy the level;
#   * L2 is unreachable without a machine-checkable proof, and a missing
#     qualifier blocks temporal L2 by construction;
#   * an unavailable semantic index never relabels an observed positive
#     alternative as an absence; it is reported and blocks main-corpus
#     eligibility instead;
#   * the parent-child closure is depth-bounded and cycle-safe, IN never merges
#     with OUT;
#   * the exact bitmask DP equals brute force on 1,000+ deterministic random
#     cases and still reproduces the Prompt-8E DP;
#   * canonical URI ordering decides a rationale ONLY when every scientific and
#     pedagogical key is exactly tied;
#   * dbp:url, a Web Archive object and Carbon/Carbonado are rejected, while a
#     short shared prefix and chemical Roman numerals are not touched;
#   * a 1,000-candidate ranking never enumerates its 166,167,000 triples;
#   * a fallback class is REQUESTED and never executed;
#   * Prompt 8E still passes and still reproduces byte for byte, and the
#     Prompt-8F parent commit stays recoverable.
#
# OFFLINE
#   No network. The 1.2 GB pinned pickle is NEVER loaded: the semantic index is
#   consumed from its cache and every other input is a frozen file.
#
# Run:  python -m pytest -vv tests/test_rationale_v3.py
############################################################################

from __future__ import annotations

import csv
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

FROZEN_8E_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_rationale_selection_2026-08-01")
FROZEN_8F_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_rationale_v3_2026-08-03")
SEMANTIC_CACHE = (
    REPO_ROOT / "data" / "semantic_index_v3" / "pilot_place_containment_v1.json")
POLICY_DIR = SRC_DIR / "rationale_v3" / "policies"
PROMPT8F_PARENT_COMMIT = "1b81f9a4a8d4c09b8b381e80ea090e2dab256a7f"

from pipeline import rationale_v3_run as runner                        # noqa: E402
from rationale_v3.contracts import (                                   # noqa: E402
    DIRECTION_IN,
    DIRECTION_OUT,
    EXCLUSION_BASIS_FORMAL_PROOF,
    EXCLUSION_BASIS_NONE,
    EXCLUSION_BASIS_SCOPED_EMPIRICAL,
    FORBIDDEN_NEGATIVE_CLAIM_PHRASES,
    GRANULARITY_RISK_NONE,
    GRANULARITY_RISK_PRESENT,
    GRANULARITY_RISK_UNRESOLVED,
    L0_ABSENCE_ONLY_OBSERVED,
    L1_POSITIVE_VALUE_CONTRAST,
    LEVEL_L0,
    LEVEL_L1,
    LEVEL_L2,
    LEVEL_NOT_COVERED,
    NOT_COVERED_CANONICALLY_EQUIVALENT,
    NOT_COVERED_EXACT_EQUAL,
    NOT_COVERED_SEMANTIC_ENTAILMENT,
    POLICY_DIAGNOSTIC_L0,
    POLICY_MAIN_L1,
    POLICY_STRICT_L2,
    QUALIFIER_PRESENT,
    QUALIFIER_UNAVAILABLE,
    RELATION_CANDIDATE_UNDER_CLAIM,
    RELATION_CANONICALLY_EQUIVALENT,
    RELATION_CLAIM_UNDER_CANDIDATE,
    RELATION_EXACT_EQUAL,
    RELATION_PROVEN_DISJOINT,
    RELATION_UNAVAILABLE,
    RELATION_UNRELATED_OR_UNKNOWN,
    RULE_ACTIVE,
    RULE_PROPOSED_NOT_ACTIVE,
    RULE_TYPE_EMPIRICAL_SINGLE_VALUED,
    RULE_TYPE_EXPLICIT_NEGATIVE,
    RULE_TYPE_FUNCTIONAL_PROPERTY,
    RULE_TYPE_TEMPORAL_EXCLUSIVE,
    SEARCH_FULL_EXACT,
    SEARCH_POOL_EXACT,
    SEMANTIC_CHECK_CLOSURE_RAN,
    SEMANTIC_CHECK_INDEX_UNAVAILABLE,
    SEMANTIC_CHECK_NOT_APPLICABLE,
    AnswerFact,
    RationaleProposition,
    RationaleV3ContractError,
    assert_no_negative_claim,
    covers_under_policy,
    mcq_evidence_level,
    validate_exclusion_basis,
)
from rationale_v3.evidence import (                                    # noqa: E402
    EmpiricalDerivationConfig,
    EvidenceRule,
    EvidenceRuleBook,
    ScopeKeyObservation,
    classify_fact_against_candidate,
    derive_empirical_single_valued_rules,
)
from rationale_v3.quality import (                                     # noqa: E402
    TEMPLATE_UNKNOWN,
    assess_fact_quality,
    check_object,
    check_predicate,
    detect_answer_leakage,
    display_label,
    load_quality_policy,
)
from rationale_v3.semantic_relations import (                          # noqa: E402
    AncestorEdge,
    SemanticIndexCacheKey,
    SemanticRelationPolicy,
    TraversalRule,
    build_semantic_index,
    load_semantic_index_cache,
    load_semantic_relation_policy,
    unavailable_semantic_index,
)
from rationale_v3.setcover import (                                    # noqa: E402
    CoverageFact,
    brute_force_minimum_rationale,
    enumerate_minimum_rationales,
    exact_minimum_rationale,
    minimum_cover_size,
)
from rationale_v3.selector import (                                    # noqa: E402
    AnswerInput,
    PoolPolicy,
    RankedCandidateView,
    build_candidate_pool,
    build_evidence_table,
    rank_minimum_rationales,
    search_combinations,
)

R = "http://dbpedia.org/resource/"
P = "http://dbpedia.org/property/"
SCOPE = R + "Category:Test_scope"
FINGERPRINT = "fp"


# --- FIXTURES AND SMALL BUILDERS ---------------------------------------------

@pytest.fixture(scope="session")
def quality_policy():
    return load_quality_policy(POLICY_DIR / "predicate_policy.json")


@pytest.fixture(scope="session")
def real_semantic_policy():
    return load_semantic_relation_policy(POLICY_DIR / "semantic_relation_policy.json")


@pytest.fixture(scope="session")
def v3_run():
    """The R1 pilot run, executed once for the whole session."""
    return runner.run_rationale_v3(verbose=False)


@pytest.fixture(scope="session")
def v3_outputs(v3_run, tmp_path_factory):
    return runner.write_all_outputs(
        v3_run, tmp_path_factory.mktemp("v3r1_outputs"), ("pytest",))


def synthetic_policy(*, max_depth: int = 3, equivalence=(), disjoint=()):
    """A tiny policy allowlisting one containment predicate."""
    return SemanticRelationPolicy(
        version="test/1", max_depth=max_depth,
        traversal_rules=(TraversalRule(
            rule_id="TEST_PART_OF", predicate_uri=P + "isPartOf",
            direction=DIRECTION_OUT,
            relation_kind="ADMINISTRATIVE_PLACE_CONTAINMENT",
            description="test containment"),),
        excluded_predicates={}, equivalence_source="test",
        equivalence_pairs=tuple(equivalence), disjointness_source="test",
        disjoint_pairs=tuple(disjoint), policy_sha256="test-sha", notes={})


def synthetic_index(edges=(), *, max_depth: int = 3, equivalence=(), disjoint=()):
    policy = synthetic_policy(max_depth=max_depth, equivalence=equivalence,
                              disjoint=disjoint)
    return build_semantic_index(
        policy=policy,
        parent_edges=[AncestorEdge(child_uri=c, parent_uri=p,
                                   rule_id="TEST_PART_OF",
                                   predicate_uri=P + "isPartOf",
                                   relation_kind="ADMINISTRATIVE_PLACE_CONTAINMENT")
                      for c, p in edges],
        cache_key=None)


def empty_rulebook(*, require_closure: bool = True, rules=()):
    return EvidenceRuleBook(
        version="test/1", policy_sha256="test",
        derivation=EmpiricalDerivationConfig(
            enabled=True, scope_kind="TEST", scope_note="test",
            minimum_support=3, maximum_observed_canonical_cardinality=1,
            maximum_violations=0, active_directions=(DIRECTION_OUT,),
            inactive_direction_reason={
                DIRECTION_IN: "IN_DIRECTION_EMPIRICAL_CARDINALITY_NOT_TRUSTED"},
            empirical_label="EMPIRICAL_AND_SCOPED_NOT_UNIVERSAL",
            version="test/1"),
        rules=tuple(rules),
        require_semantic_closure_for_annotation=require_closure)


def single_valued_rule(predicate=P + "birthPlace", direction=DIRECTION_OUT,
                       *, status=RULE_ACTIVE, scope=SCOPE):
    return EvidenceRule(
        rule_id=f"SV_{direction}_{predicate.rsplit('/', 1)[-1]}",
        rule_type=RULE_TYPE_EMPIRICAL_SINGLE_VALUED,
        predicate_uri=predicate, direction=direction, scope=scope,
        scope_kind="TEST", required_evidence=("test",), minimum_support=3,
        observed_support=9, maximum_observed_cardinality=1,
        observed_violation_count=0, source="test", provenance="test",
        version="test/1", activation_status=status,
        empirical_label="EMPIRICAL_AND_SCOPED_NOT_UNIVERSAL")


def l2_rule(rule_type=RULE_TYPE_FUNCTIONAL_PROPERTY, predicate=P + "birthPlace",
            *, status=RULE_ACTIVE, rule_id="L2_RULE"):
    return EvidenceRule(
        rule_id=rule_id, rule_type=rule_type, predicate_uri=predicate,
        direction=DIRECTION_OUT, scope=SCOPE, scope_kind="TEST",
        required_evidence=("declaration",), minimum_support=0,
        observed_support=0, maximum_observed_cardinality=1,
        observed_violation_count=0, source="test ontology",
        provenance="synthetic fixture", version="test/1",
        activation_status=status,
        ontology_source="synthetic test ontology declaring maxCardinality 1")


def proposition(predicate=P + "birthPlace", direction=DIRECTION_OUT,
                obj=R + "Tokyo", qualifiers=(), qualifier_status=None):
    return RationaleProposition(
        predicate_uri=predicate, direction=direction, source_object_uri=obj,
        claim_object_uri=obj, qualifiers=tuple(qualifiers),
        qualifier_status=(qualifier_status if qualifier_status is not None
                          else (QUALIFIER_PRESENT if qualifiers
                                else QUALIFIER_UNAVAILABLE)))


def classify(objects, *, index=None, rulebook=None, prop=None, scope=SCOPE):
    return classify_fact_against_candidate(
        proposition=prop or proposition(), candidate_uri=R + "Candidate",
        candidate_objects=list(objects),
        semantic_index=index if index is not None else synthetic_index(),
        rulebook=rulebook or empty_rulebook(), scope=scope)


def fact(predicate, direction, counterpart):
    return AnswerFact(predicate_uri=predicate, direction=direction,
                      counterpart_uri=counterpart,
                      graph_fingerprint=FINGERPRINT)


def answer_input(answer_facts, candidate_facts, *, n=None, scores=None,
                 answer_uri=R + "Answer"):
    """A synthetic AnswerInput. Candidate rank order is the sorted URI order."""
    names = (sorted(candidate_facts) if candidate_facts
             else [f"{R}Cand{i:04d}" for i in range(n or 0)])
    if n is not None:
        assert len(names) == n, f"expected {n} candidates, built {len(names)}"
    ranked = tuple(
        RankedCandidateView(rank=i + 1, canonical_candidate_uri=uri,
                            candidate_local_index=1000 + i,
                            score=(scores[i] if scores else 1.0 - i * 0.01))
        for i, uri in enumerate(names))
    return AnswerInput(
        answer_uri=answer_uri, answer_local_index=1, display_label="Answer",
        pilot_slot=1, selected_class_uri=SCOPE, graph_fingerprint=FINGERPRINT,
        ranker_name="lrolesim_m1_fixed_k3", measure="lrolesim_ed",
        lrolesim_beta=0.2, iterations=3, iteration_mode="fixed",
        ranked_candidates=ranked, answer_facts=tuple(answer_facts),
        candidate_facts={k: tuple(v) for k, v in candidate_facts.items()})


def table_for(answer_facts, candidate_facts, *, index=None, rulebook=None,
              policy=None, n=None):
    return build_evidence_table(
        answer_input(answer_facts, candidate_facts, n=n),
        semantic_index=index if index is not None else synthetic_index(),
        rulebook=rulebook or empty_rulebook(),
        quality_policy=policy or load_quality_policy(
            POLICY_DIR / "predicate_policy.json"))


def coverage_facts(specs):
    """[(mask, tie_weight, key_suffix)] -> CoverageFacts in canonical order."""
    return tuple(
        CoverageFact(fact_index=i,
                     canonical_key=(P + "p", DIRECTION_OUT, R + suffix),
                     coverage_mask=mask, tie_weight=weight)
        for i, (mask, weight, suffix) in enumerate(specs))


# --- GROUP A — THE CORRECTED EVIDENCE TAXONOMY -------------------------------

@pytest.mark.parametrize("objects,level,reason,basis", [
    # An observed alternative object IS the L1 case, whatever the predicate's
    # cardinality. This is the whole point of the R1 correction.
    ([R + "Kyoto"], LEVEL_L1, L1_POSITIVE_VALUE_CONTRAST, EXCLUSION_BASIS_NONE),
    ([R + "Kyoto", R + "Osaka"], LEVEL_L1, L1_POSITIVE_VALUE_CONTRAST,
     EXCLUSION_BASIS_NONE),
    # No observed object at all is the only L0 case.
    ([], LEVEL_L0, L0_ABSENCE_ONLY_OBSERVED, EXCLUSION_BASIS_NONE),
    # Support, checked before any rule.
    ([R + "Tokyo"], LEVEL_NOT_COVERED, NOT_COVERED_EXACT_EQUAL,
     EXCLUSION_BASIS_NONE),
    ([R + "Tokyo", R + "Kyoto", R + "Osaka"], LEVEL_NOT_COVERED,
     NOT_COVERED_EXACT_EQUAL, EXCLUSION_BASIS_NONE),
])
def test_taxonomy_level_reason_and_basis(objects, level, reason, basis):
    result = classify(objects)
    assert (result.level, result.reason_code, result.exclusion_basis) == (
        level, reason, basis)
    assert result.proof is None
    assert result.applied_rule_id == ""


def test_l1_covers_main_l1_but_not_strict_l2():
    result = classify([R + "Kyoto"])
    assert covers_under_policy(result.level, POLICY_MAIN_L1)
    assert covers_under_policy(result.level, POLICY_DIAGNOSTIC_L0)
    assert not covers_under_policy(result.level, POLICY_STRICT_L2)


def test_not_covered_covers_nothing():
    result = classify([R + "Tokyo"])
    for policy in (POLICY_STRICT_L2, POLICY_MAIN_L1, POLICY_DIAGNOSTIC_L0):
        assert not covers_under_policy(result.level, policy)


@pytest.mark.parametrize("status,expected_basis", [
    (RULE_ACTIVE, EXCLUSION_BASIS_SCOPED_EMPIRICAL),
    (RULE_PROPOSED_NOT_ACTIVE, EXCLUSION_BASIS_NONE),
    ("INACTIVE", EXCLUSION_BASIS_NONE),
])
def test_scoped_empirical_rule_only_annotates_an_existing_l1(status,
                                                             expected_basis):
    """The rule may set exclusion_basis. It may never decide the level."""
    result = classify([R + "Kyoto"],
                      rulebook=empty_rulebook(rules=[single_valued_rule(
                          status=status)]))
    assert result.level == LEVEL_L1
    assert result.reason_code == L1_POSITIVE_VALUE_CONTRAST
    assert result.exclusion_basis == expected_basis
    assert result.proof is None
    # Removing the rule entirely changes the annotation and nothing else.
    plain = classify([R + "Kyoto"])
    assert plain.level == result.level == LEVEL_L1


def test_annotation_rule_cannot_create_l1_from_an_absence():
    """An absence stays L0 even where a scoped rule is active for the key."""
    result = classify([], rulebook=empty_rulebook(rules=[single_valued_rule()]))
    assert result.level == LEVEL_L0
    assert result.reason_code == L0_ABSENCE_ONLY_OBSERVED
    assert result.exclusion_basis == EXCLUSION_BASIS_NONE
    assert result.semantic_check_status == SEMANTIC_CHECK_NOT_APPLICABLE


def test_annotation_is_withheld_when_the_candidate_violates_the_rule():
    """A rule derived as at-most-one may not annotate a candidate showing two."""
    result = classify([R + "Kyoto", R + "Osaka"],
                      rulebook=empty_rulebook(rules=[single_valued_rule()]))
    assert result.level == LEVEL_L1
    assert result.exclusion_basis == EXCLUSION_BASIS_NONE
    assert "SV_OUT_birthPlace" in result.blocked_rule_ids


@pytest.mark.parametrize("rule_type,rule_id", [
    (RULE_TYPE_FUNCTIONAL_PROPERTY, "FUNC_1"),
    (RULE_TYPE_EXPLICIT_NEGATIVE, "NEG_1"),
])
def test_trusted_declaration_can_produce_l2_with_a_proof(rule_type, rule_id):
    result = classify([R + "Kyoto"], rulebook=empty_rulebook(
        rules=[l2_rule(rule_type, rule_id=rule_id)]))
    assert result.level == LEVEL_L2
    assert result.exclusion_basis == EXCLUSION_BASIS_FORMAL_PROOF
    assert result.proof is not None
    assert result.proof.ontology_source and result.proof.premises
    assert result.proof.conclusion
    assert covers_under_policy(result.level, POLICY_STRICT_L2)


def test_l2_is_impossible_without_a_proof():
    """Only-one-value-observed is not functionality, and an L2 level with no
    EvidenceProof is refused by the contract itself."""
    assert classify([R + "Kyoto"],
                    rulebook=empty_rulebook(rules=[single_valued_rule()])
                    ).level == LEVEL_L1
    with pytest.raises(RationaleV3ContractError):
        validate_exclusion_basis(LEVEL_L2, EXCLUSION_BASIS_NONE)
    with pytest.raises(RationaleV3ContractError):
        validate_exclusion_basis(LEVEL_L0, EXCLUSION_BASIS_SCOPED_EMPIRICAL)


@pytest.mark.parametrize("qualifiers,expected", [
    ((), LEVEL_L1),                                        # no qualifier: no L2
    ((("startTime", "1964-11-09"), ("endTime", "1972-07-07")), LEVEL_L2),
])
def test_temporal_l2_requires_real_qualifiers(qualifiers, expected):
    rule = l2_rule(RULE_TYPE_TEMPORAL_EXCLUSIVE, predicate=P + "office",
                   rule_id="TEMPORAL_1")
    prop = proposition(predicate=P + "office", obj=R + "Prime_Minister",
                       qualifiers=qualifiers)
    result = classify([R + "President"], rulebook=empty_rulebook(rules=[rule]),
                      prop=prop)
    assert result.level == expected
    if expected == LEVEL_L1:
        assert prop.qualifier_status == QUALIFIER_UNAVAILABLE
        assert result.proof is None
        assert "TEMPORAL_1" in result.blocked_rule_ids
    else:
        assert result.proof.qualifier_context == QUALIFIER_PRESENT


def test_pilot_has_no_l2_without_proof(v3_run):
    """Zero L2 on the pilot, and every L2 anywhere carries an EvidenceProof."""
    counts = v3_run.counts()["fact_candidate_level_incidences_all_facts"]
    assert counts[LEVEL_L2] == 0
    for selection in v3_run.ready_selections:
        for row in selection.table.evidence:
            for item in row:
                assert (item.level == LEVEL_L2) == (item.proof is not None)
                assert (item.exclusion_basis == EXCLUSION_BASIS_FORMAL_PROOF) == (
                    item.proof is not None)


def test_mcq_level_is_the_weakest_per_distractor_best_level():
    assert mcq_evidence_level([LEVEL_L2, LEVEL_L2, LEVEL_L2]) == "MCQ-L2"
    assert mcq_evidence_level([LEVEL_L2, LEVEL_L1, LEVEL_L2]) == "MCQ-L1"
    assert mcq_evidence_level([LEVEL_L1, LEVEL_L0, LEVEL_L1]) == "MCQ-L0"
    assert mcq_evidence_level([]) == "MCQ-NOT_COVERED"


# --- GROUP B — SEMANTIC SAFETY -----------------------------------------------

@pytest.mark.parametrize("objects,index_kwargs,relation,reason", [
    ([R + "Tokyo"], {}, RELATION_EXACT_EQUAL, NOT_COVERED_EXACT_EQUAL),
    ([R + "Antisthenes_(Heraclitean)"],
     {"equivalence": [(R + "Antisthenes_(Heraclitean)", R + "Tokyo")]},
     RELATION_CANONICALLY_EQUIVALENT, NOT_COVERED_CANONICALLY_EQUIVALENT),
    ([R + "Bunkyo"], {"edges": [(R + "Bunkyo", R + "Tokyo")]},
     RELATION_CANDIDATE_UNDER_CLAIM, NOT_COVERED_SEMANTIC_ENTAILMENT),
])
def test_supporting_relations_make_the_fact_not_covered(objects, index_kwargs,
                                                        relation, reason):
    edges = index_kwargs.pop("edges", ())
    index = synthetic_index(edges, **index_kwargs)
    assert index.classify(R + "Tokyo", objects[0]).relation == relation
    result = classify(objects, index=index)
    assert result.level == LEVEL_NOT_COVERED
    assert result.reason_code == reason


def test_granularity_risk_is_reported_and_does_not_downgrade_the_level():
    """The claim object lies UNDER a candidate object: the candidate holds the
    more general statement. R1 records the risk and keeps the observation."""
    index = synthetic_index([(R + "Bunkyo", R + "Tokyo")])
    prop = proposition(obj=R + "Bunkyo")
    assert index.classify(R + "Bunkyo", R + "Tokyo").relation == (
        RELATION_CLAIM_UNDER_CANDIDATE)
    result = classify([R + "Tokyo"], index=index, prop=prop)
    assert result.level == LEVEL_L1
    assert result.granularity_risk_status == GRANULARITY_RISK_PRESENT
    assert result.granularity_risk is True
    assert result.semantic_check_status == SEMANTIC_CHECK_CLOSURE_RAN


def test_unavailable_index_does_not_relabel_l1_as_l0():
    """The Prompt-8F behaviour this corrects: a missing cache must not turn an
    observed positive alternative into an absence."""
    missing = unavailable_semantic_index(synthetic_policy(), "no cache in test")
    assert missing.classify(R + "Tokyo", R + "Paris").relation == (
        RELATION_UNAVAILABLE)
    result = classify([R + "Paris"], index=missing,
                      rulebook=empty_rulebook(rules=[single_valued_rule()]))
    assert result.level == LEVEL_L1
    assert result.reason_code == L1_POSITIVE_VALUE_CONTRAST
    assert result.semantic_check_status == SEMANTIC_CHECK_INDEX_UNAVAILABLE
    assert result.granularity_risk_status == GRANULARITY_RISK_UNRESOLVED
    # The stronger SCOPED_EMPIRICAL reading is withheld, but the level stands.
    assert result.exclusion_basis == EXCLUSION_BASIS_NONE


def test_unresolved_granularity_risk_blocks_main_corpus_eligibility(v3_run):
    """Withholding the index keeps the MCQ level and removes eligibility."""
    arm = v3_run.comparison_arms["semantic_off"]
    assert arm, "the semantic_off ablation arm did not run"
    for answer_uri, selection in arm.items():
        full = v3_run.selection_for(answer_uri)
        assert selection.mcq_evidence_level == full.mcq_evidence_level
        assert selection.eligible_for_main_corpus is False
        assert selection.unresolved_granularity_risk is True


def test_proven_disjoint_relation_is_recorded_but_creates_no_exclusion():
    index = synthetic_index(disjoint=[(R + "Tokyo", R + "Liquid")])
    assert index.classify(R + "Tokyo", R + "Liquid").relation == (
        RELATION_PROVEN_DISJOINT)
    result = classify([R + "Liquid"], index=index)
    assert result.level == LEVEL_L1        # observed contrast, not a proof
    assert result.exclusion_basis == EXCLUSION_BASIS_NONE
    assert result.proof is None


def test_closure_is_depth_bounded_and_cycle_safe():
    chain = [(R + "A", R + "B"), (R + "B", R + "C"), (R + "C", R + "D"),
             (R + "D", R + "E")]
    shallow = synthetic_index(chain, max_depth=2)
    assert set(shallow.ancestors(R + "A")) == {R + "B", R + "C"}
    assert shallow.classify(R + "E", R + "A").relation == (
        RELATION_UNRELATED_OR_UNKNOWN)
    deep = synthetic_index(chain, max_depth=4)
    assert set(deep.ancestors(R + "A")) == {R + "B", R + "C", R + "D", R + "E"}
    assert deep.classify(R + "E", R + "A").relation == (
        RELATION_CANDIDATE_UNDER_CLAIM)
    cyclic = synthetic_index([(R + "A", R + "B"), (R + "B", R + "C"),
                              (R + "C", R + "A")], max_depth=10)
    ancestors = cyclic.ancestors(R + "A")          # must terminate
    assert set(ancestors) == {R + "B", R + "C"} and R + "A" not in ancestors


def test_in_and_out_never_merge():
    """The candidates hold the SAME counterpart in the other direction, so the
    OUT fact must see an absence and not support."""
    table = table_for(
        [fact(P + "influenced", DIRECTION_OUT, R + "X")],
        {f"{R}Cand{i}": [fact(P + "influenced", DIRECTION_IN, R + "X")]
         for i in range(3)})
    for position in range(3):
        item = table.evidence[0][position]
        assert item.level == LEVEL_L0
        assert item.reason_code == L0_ABSENCE_ONLY_OBSERVED


def test_semantic_index_cache_key_is_verified(real_semantic_policy, tmp_path):
    stale = SemanticIndexCacheKey(
        pinned_kg_sha256="0" * 64, policy_sha256="0" * 64,
        source_object_list_sha256="0" * 64, max_depth=1, creation_command="test")
    index = load_semantic_index_cache(SEMANTIC_CACHE, policy=real_semantic_policy,
                                      expected_key=stale)
    assert index.available is False
    assert "different inputs" in index.unavailable_reason
    assert load_semantic_index_cache(tmp_path / "absent.json",
                                     policy=real_semantic_policy,
                                     expected_key=stale).available is False


# --- GROUP C — SET COVER AND RATIONALE RANKING -------------------------------

def test_two_fact_counterexample_still_returns_a_rationale_of_size_two():
    """AUDIT item EX-3 / test T2.3: f1 covers d1+d2, f2 covers d3. |R*| = 2."""
    cover = exact_minimum_rationale(
        coverage_facts([(0b011, 0, "f1"), (0b100, 0, "f2")]),
        k=3, rho=3, evidence_policy=POLICY_DIAGNOSTIC_L0)
    assert cover.full_coverage is True
    assert cover.minimum_rationale_size == 2
    assert len(cover.selected_rationale) == 2
    assert minimum_cover_size([0b011, 0b100], 3) == 2


def test_exact_dp_equals_brute_force_on_random_cases():
    rng = random.Random(20260803)
    checked = 0
    for _ in range(1200):
        k = rng.randint(1, 5)
        specs = []
        for i in range(rng.randint(1, 12)):
            mask = rng.randrange(0, 1 << k)
            specs.append((mask, rng.randint(0, bin(mask).count("1")), f"f{i:03d}"))
        facts = coverage_facts(specs)
        fast = exact_minimum_rationale(facts, k=k, rho=k,
                                       evidence_policy=POLICY_DIAGNOSTIC_L0)
        slow = brute_force_minimum_rationale(facts, k=k, rho=k,
                                             evidence_policy=POLICY_DIAGNOSTIC_L0)
        for name in ("coverage_mask", "minimum_rationale_size",
                     "tie_weight_total", "full_coverage",
                     "optimal_rationale_count"):
            assert getattr(fast, name) == getattr(slow, name), name
        assert fast.selected_rationale_keys() == slow.selected_rationale_keys()
        checked += 1
    assert checked >= 1000


def test_dp_still_reproduces_the_prompt8e_dp():
    """With the extra features off, the copied DP must agree with 8E's."""
    from rationale import setcover as prompt8e_setcover
    rng = random.Random(8531)
    for _ in range(300):
        k = rng.randint(1, 4)
        specs = []
        for i in range(rng.randint(1, 9)):
            mask = rng.randrange(0, 1 << k)
            specs.append((mask, rng.randint(0, bin(mask).count("1")), f"f{i:03d}"))
        new = exact_minimum_rationale(coverage_facts(specs), k=k, rho=k,
                                      evidence_policy=POLICY_DIAGNOSTIC_L0)
        old = prompt8e_setcover.exact_minimum_rationale(
            tuple(prompt8e_setcover.CoverageFact(
                fact_index=i, canonical_key=(P + "p", DIRECTION_OUT, R + s),
                coverage_mask=mask, absence_incidences=w)
                for i, (mask, w, s) in enumerate(specs)),
            k=k, rho=k, evidence_policy="snapshot-observed")
        for name in ("minimum_rationale_size", "coverage_mask", "full_coverage",
                     "optimal_rationale_count"):
            assert getattr(new, name) == getattr(old, name), name
        assert new.selected_rationale_keys() == old.selected_rationale_keys()


def test_enumeration_reports_completeness():
    facts = coverage_facts([(0b011, 0, "a"), (0b100, 0, "b"),
                            (0b110, 0, "c"), (0b001, 0, "d")])
    full = enumerate_minimum_rationales(facts, k=3, size=2, target_mask=0b111)
    # {a,b}, {a,c} and {c,d} all OR to 0b111; {b,d} reaches only 0b101.
    assert full.complete is True
    assert full.total_count == len(full.enumerated) == 3
    for choice in full.enumerated:
        union = 0
        for item in choice:
            union |= item.coverage_mask
        assert union == 0b111 and len(choice) == 2
    bounded = enumerate_minimum_rationales(facts, k=3, size=2,
                                           target_mask=0b111, limit=1)
    assert bounded.complete is False
    assert (bounded.total_count, len(bounded.enumerated)) == (3, 1)


def test_policy_masks_differ_correctly():
    table = table_for(
        [fact(P + "birthPlace", DIRECTION_OUT, R + "Tokyo")],
        {R + "Cand0": [fact(P + "birthPlace", DIRECTION_OUT, R + "Kyoto")],
         R + "Cand1": [], R + "Cand2": []})
    assert table.level(0, 0) == LEVEL_L1        # observed alternative
    assert table.level(0, 1) == LEVEL_L0        # nothing observed
    assert table.covering_bitset(0, LEVEL_L2) == 0
    assert table.covering_bitset(0, LEVEL_L1) == 0b1
    assert table.covering_bitset(0, LEVEL_L0) == 0b1
    assert table.covering_bitset(1, LEVEL_L1) == 0
    assert table.covering_bitset(1, LEVEL_L0) == 0b1


def test_rationale_minimum_evidence_level_is_the_weakest_distractor():
    table = table_for(
        [fact(P + "birthPlace", DIRECTION_OUT, R + "Tokyo"),
         fact(P + "almaMater", DIRECTION_OUT, R + "Kyoto_University")],
        {R + "Cand0": [fact(P + "birthPlace", DIRECTION_OUT, R + "Osaka")],
         R + "Cand1": [fact(P + "birthPlace", DIRECTION_OUT, R + "Nara")],
         R + "Cand2": []})                      # reachable only at L0
    ranking = rank_minimum_rationales(table, (0, 1, 2),
                                      policy=POLICY_DIAGNOSTIC_L0, k=3, rho=3)
    assert ranking.full_coverage is True
    assert ranking.achieved_min_level == LEVEL_L0
    assert ranking.mcq_evidence_level == "MCQ-L0"
    assert sorted(ranking.best.per_candidate_best_level) == [
        LEVEL_L0, LEVEL_L1, LEVEL_L1]
    assert rank_minimum_rationales(table, (0, 1, 2), policy=POLICY_MAIN_L1,
                                   k=3, rho=3).full_coverage is False


def _two_way_table(second_predicate, second_object, *, rulebook=None, index=None):
    """Two Answer facts, each covering ALL THREE distractors on its own.

    Both are minimum covers of size one, so the choice between them is decided
    purely by the ranking — which is what the next tests probe.
    """
    return table_for(
        [fact(P + "birthPlace", DIRECTION_OUT, R + "AAA_Tokyo"),
         fact(second_predicate, DIRECTION_OUT, second_object)],
        {f"{R}Cand{i}": [fact(P + "birthPlace", DIRECTION_OUT, R + f"Other{i}"),
                         fact(second_predicate, DIRECTION_OUT, R + f"Alt{i}")]
         for i in range(3)},
        rulebook=rulebook, index=index)


def test_scoped_empirical_annotation_beats_uri_ordering_within_l1():
    """`AAA_Tokyo` sorts first by URI; only the other fact is annotated."""
    table = _two_way_table(
        P + "almaMater", R + "ZZZ_Kyoto_University",
        rulebook=empty_rulebook(rules=[single_valued_rule(
            predicate=P + "almaMater")]))
    ranking = rank_minimum_rationales(table, (0, 1, 2),
                                      policy=POLICY_DIAGNOSTIC_L0, k=3, rho=3)
    assert ranking.achieved_min_level == LEVEL_L1
    chosen = table.facts[ranking.best.fact_indices[0]]
    assert chosen.predicate_uri == P + "almaMater"
    assert ranking.best.scoped_empirical_incidences == 3


def test_semantic_safety_beats_uri_ordering():
    """The URI-first fact carries granularity risk, so the other one wins."""
    table = table_for(
        [fact(P + "birthPlace", DIRECTION_OUT, R + "AAA_Bunkyo"),
         fact(P + "deathPlace", DIRECTION_OUT, R + "ZZZ_Nara")],
        {f"{R}Cand{i}": [fact(P + "birthPlace", DIRECTION_OUT, R + "Tokyo"),
                         fact(P + "deathPlace", DIRECTION_OUT, R + f"Alt{i}")]
         for i in range(3)},
        index=synthetic_index([(R + "AAA_Bunkyo", R + "Tokyo")]))
    assert table.evidence[0][0].granularity_risk_status == GRANULARITY_RISK_PRESENT
    ranking = rank_minimum_rationales(table, (0, 1, 2),
                                      policy=POLICY_DIAGNOSTIC_L0, k=3, rho=3)
    assert table.facts[ranking.best.fact_indices[0]].predicate_uri == (
        P + "deathPlace")
    assert ranking.best.granularity_risk_incidences == 0


def test_pedagogical_quality_beats_uri_ordering():
    """`dbp:chassis` sorts before `dbp:knownFor` and has no template. It loses."""
    unverbalizable = table_for(
        [fact(P + "chassis", DIRECTION_OUT, R + "AAA_Frame"),
         fact(P + "knownFor", DIRECTION_OUT, R + "ZZZ_Relativity")],
        {f"{R}Cand{i}": [fact(P + "chassis", DIRECTION_OUT, R + f"OtherFrame{i}"),
                         fact(P + "knownFor", DIRECTION_OUT, R + f"OtherIdea{i}")]
         for i in range(3)})
    assert unverbalizable.quality[0].template_id == TEMPLATE_UNKNOWN
    assert unverbalizable.quality[1].verbalizable is True
    ranking = rank_minimum_rationales(unverbalizable, (0, 1, 2),
                                      policy=POLICY_DIAGNOSTIC_L0, k=3, rho=3)
    assert unverbalizable.facts[ranking.best.fact_indices[0]].predicate_uri == (
        P + "knownFor")
    assert ranking.best.unverbalizable_count == 0


def test_canonical_uri_ordering_is_the_last_resort_only():
    """Two facts identical on every scientific and quality key: URI order wins."""
    table = table_for(
        [fact(P + "knownFor", DIRECTION_OUT, R + "Alpha"),
         fact(P + "knownFor", DIRECTION_OUT, R + "Betaa")],
        {f"{R}Cand{i}": [fact(P + "knownFor", DIRECTION_OUT, R + f"Gamma{i}")]
         for i in range(3)})
    ranking = rank_minimum_rationales(table, (0, 1, 2),
                                      policy=POLICY_DIAGNOSTIC_L0, k=3, rho=3)
    keys = [choice.ranking_key() for choice in ranking.ranked[:2]]
    assert keys[0][:-1] == keys[1][:-1], "everything but the URI key must tie"
    assert table.facts[ranking.best.fact_indices[0]].counterpart_uri == R + "Alpha"


def test_local_anonymity_is_computed_over_the_complete_local_pool():
    shared = [fact(P + "knownFor", DIRECTION_OUT, R + "Shared")]
    candidates = {
        R + "Cand0": [fact(P + "knownFor", DIRECTION_OUT, R + "Other")],
        R + "Cand1": [fact(P + "knownFor", DIRECTION_OUT, R + "Other")],
        R + "Cand2": [fact(P + "knownFor", DIRECTION_OUT, R + "Other")],
        R + "Cand3": [fact(P + "knownFor", DIRECTION_OUT, R + "Shared")],
        R + "Cand4": [fact(P + "knownFor", DIRECTION_OUT, R + "Shared")],
    }
    # Answer + Cand3 + Cand4 support it; the pool is Answer + 5 candidates.
    count, ratio, direct = table_for(shared, candidates).local_anonymity((0,))
    assert (count, direct) == (3, False)
    assert ratio == pytest.approx(3 / 6)
    lone = table_for(shared, {k: v for k, v in candidates.items()
                              if k in (R + "Cand0", R + "Cand1", R + "Cand2")})
    assert lone.local_anonymity((0,)) == (1, pytest.approx(0.25), True)


# --- GROUP D — QUALITY -------------------------------------------------------

def test_dbp_url_and_web_archive_objects_are_rejected(quality_policy):
    ok, reason = check_predicate(P + "url", quality_policy)
    assert (ok, reason) == (False, "PREDICATE_EXTERNAL_URL_FIELD")
    assert reason in quality_policy.reject_reason_codes
    archive = ("https://web.archive.org/web/20160307233845/http:/www.open.edu/"
               "openlearn/whats-on/events/openlearn-live-12th-august-2015%23sato")
    assert check_object(archive, quality_policy) == (False,
                                                     "OBJECT_WEB_ARCHIVE_URL")
    assert check_object("http://example.org/page", quality_policy) == (
        False, "OBJECT_EXTERNAL_URL")
    assert check_object(R + "Tokyo", quality_policy)[0] is True


def test_carbon_versus_carbonado_is_rejected_as_lexical_leakage(quality_policy):
    result = detect_answer_leakage(R + "Carbon", R + "Carbonado", quality_policy)
    assert result.hard_leak is True
    assert result.reason_code == "ANSWER_LEXICAL_LEAK"
    quality = assess_fact_quality(
        answer_uri=R + "Carbon", predicate_uri=P + "formula",
        direction=DIRECTION_IN, counterpart_uri=R + "Carbonado",
        policy=quality_policy)
    assert quality.eligible is False
    assert "ANSWER_LEXICAL_LEAK" in quality.rejection_reasons


@pytest.mark.parametrize("answer,other", [
    (R + "Carbon", R + "Boron_carbide"),
    (R + "Carbon", R + "Carl_Wilhelm_Scheele"),
    (R + "Carbon", R + "Antimony"),
    (R + "Plato", R + "Gorgias"),
    (R + "Silicon", R + "J%C3%B6ns_Jacob_Berzelius"),
    (R + "Adam_Smith", R + "The_Wealth_of_Nations"),
])
def test_short_unrelated_substring_does_not_trigger_leakage(answer, other,
                                                            quality_policy):
    result = detect_answer_leakage(answer, other, quality_policy)
    assert result.hard_leak is False, (answer, other, result.matches)


@pytest.mark.parametrize("uri,expected", [
    (R + "Iron(III)_chloride", "Iron(III) chloride"),
    (R + "Iron(II)_chloride", "Iron(II) chloride"),
    (R + "Phosphorus(V)_oxide", "Phosphorus(V) oxide"),
    (R + "Vitamin_B12_(cobalamin)", "Vitamin B12 (cobalamin)"),
    (R + "Makoto_Kobayashi_(physicist)", "Makoto Kobayashi (physicist)"),
    (R + "Kant%C5%8D_region", "Kantō region"),
])
def test_display_labels_preserve_what_distinguishes_the_entity(uri, expected):
    assert display_label(uri) == expected
    # INV-2: two chemically distinct entities never collapse to one label.
    assert display_label(R + "Iron(II)_chloride") != display_label(
        R + "Iron(III)_chloride")


def test_unverbalizable_predicate_stays_eligible_but_loses(quality_policy):
    unknown = assess_fact_quality(
        answer_uri=R + "Answer", predicate_uri=P + "chassis",
        direction=DIRECTION_OUT, counterpart_uri=R + "Frame",
        policy=quality_policy)
    known = assess_fact_quality(
        answer_uri=R + "Answer", predicate_uri=P + "almaMater",
        direction=DIRECTION_OUT, counterpart_uri=R + "Kobe_University",
        policy=quality_policy)
    assert (unknown.template_id, unknown.verbalizable) == (TEMPLATE_UNKNOWN, False)
    assert known.verbalizable is True
    # Still ELIGIBLE — diagnostics may use it — but never main-corpus material.
    assert unknown.eligible is True


def test_in_and_out_templates_keep_their_own_reading(quality_policy):
    assert quality_policy.template_for(P + "author", DIRECTION_OUT) is None
    in_author = quality_policy.template_for(P + "author", DIRECTION_IN)
    assert in_author.template_id == "IN_AUTHOR_V1"
    assert "<subject> was written by <answer>" in in_author.reading
    in_influenced = quality_policy.template_for(P + "influenced", DIRECTION_IN)
    out_influenced = quality_policy.template_for(P + "influenced", DIRECTION_OUT)
    assert in_influenced.reading == "<subject> influenced <answer>."
    assert out_influenced.reading == "<answer> influenced <object>."
    assert in_influenced.template_id != out_influenced.template_id


def test_derivation_gates_are_named_and_published():
    config = empty_rulebook().derivation
    rows = [
        ScopeKeyObservation(SCOPE, P + "era", DIRECTION_OUT, 9, 1, 0, 10),
        ScopeKeyObservation(SCOPE, P + "almaMater", DIRECTION_OUT, 9, 3, 4, 10),
        ScopeKeyObservation(SCOPE, P + "eponym", DIRECTION_IN, 9, 1, 0, 10),
        ScopeKeyObservation(SCOPE, P + "region", DIRECTION_OUT, 1, 1, 0, 10),
    ]
    derived = {r.predicate_uri + r.direction: r
               for r in derive_empirical_single_valued_rules(
                   rows, config=config, rejected_predicates={})}
    assert derived[P + "era" + DIRECTION_OUT].activation_status == RULE_ACTIVE
    assert derived[P + "almaMater" + DIRECTION_OUT].inactive_reason == (
        "OBSERVED_CARDINALITY_VIOLATION_IN_SCOPE")
    assert derived[P + "eponym" + DIRECTION_IN].activation_status == (
        RULE_PROPOSED_NOT_ACTIVE)
    assert derived[P + "region" + DIRECTION_OUT].inactive_reason == (
        "INSUFFICIENT_OBSERVED_SUPPORT_IN_SCOPE")
    rejected = derive_empirical_single_valued_rules(
        rows[:1], config=config, rejected_predicates={P + "era": "TEST"})
    assert rejected[0].inactive_reason == "PREDICATE_REJECTED_BY_PREDICATE_POLICY"


# --- GROUP E — SCALABILITY ---------------------------------------------------

def _big_table(n: int, *, facts_per_answer: int = 4):
    candidates = {}
    for i in range(n):
        # Every third candidate shares Idea0, so coverage is not uniform.
        own = [fact(P + "knownFor", DIRECTION_OUT, R + f"Other{i}")]
        if i % 3 == 0:
            own.append(fact(P + "knownFor", DIRECTION_OUT, R + "Idea0"))
        candidates[f"{R}Cand{i:04d}"] = own
    return table_for([fact(P + "knownFor", DIRECTION_OUT, R + f"Idea{i}")
                      for i in range(facts_per_answer)], candidates, n=n)


def test_full_exact_mode_below_the_threshold():
    pool = build_candidate_pool(_big_table(40), k=3, policy=PoolPolicy())
    assert pool.scope == SEARCH_FULL_EXACT
    assert pool.original_combination_count == 9880
    assert pool.enumerated_combination_count == 9880
    assert pool.global_optimality_claim is True
    assert len(pool.positions) == 40


def test_thousand_candidates_use_pool_exact_and_never_enumerate_every_triple():
    table = _big_table(1000)
    pool = build_candidate_pool(table, k=3, policy=PoolPolicy())
    assert pool.original_candidate_count == 1000
    assert pool.original_combination_count == 166_167_000
    assert pool.scope == SEARCH_POOL_EXACT
    assert pool.global_optimality_claim is False
    assert pool.pool_optimality_claim is True
    assert len(pool.positions) <= 100
    assert pool.enumerated_combination_count <= 161_700
    assert pool.enumerated_combination_count < pool.original_combination_count / 1000
    search = search_combinations(table, policy=POLICY_DIAGNOSTIC_L0, k=3, pool=pool)
    assert len(search.full_coverage_outcomes) <= pool.enumerated_combination_count


@pytest.mark.parametrize("size", [25, 50, 75, 100])
def test_pool_size_never_exceeds_the_configured_maximum(size):
    policy = PoolPolicy.for_pool_size(size)
    pool = build_candidate_pool(_big_table(500), k=3, policy=policy,
                                force_pool=True)
    assert len(pool.positions) <= size
    assert policy.top_by_score + policy.evidence_rescue <= size


def test_evidence_rescue_candidates_can_enter_below_the_cutoff():
    """A low-ranked candidate with the only usable evidence must reach the pool.

    High-ranked candidates SHARE the Answer's object and carry no evidence at
    all; only the last one has a different object.
    """
    candidates = {f"{R}Cand{i:04d}": [fact(P + "birthPlace", DIRECTION_OUT,
                                           R + ("Tokyo" if i < 59 else "Kyoto"))]
                  for i in range(60)}
    table = table_for([fact(P + "birthPlace", DIRECTION_OUT, R + "Tokyo")],
                      candidates, n=60,
                      rulebook=empty_rulebook(rules=[single_valued_rule()]))
    pool = build_candidate_pool(table, k=3, policy=PoolPolicy(
        max_exact_combinations=10, top_by_score=20, evidence_rescue=5,
        max_pool_size=25))
    assert pool.scope == SEARCH_POOL_EXACT
    assert 59 in pool.positions, "the only evidence-bearing candidate was dropped"
    assert 59 in pool.rescued_positions


def test_pilot_full_exact_result_is_reproducible(v3_run):
    for selection in v3_run.ready_selections:
        assert selection.pool.scope == SEARCH_FULL_EXACT
        assert selection.pool.global_optimality_claim is True
        assert (selection.pool.enumerated_combination_count
                == selection.pool.original_combination_count)


# --- GROUP F — BOUNDARIES AND REGRESSION -------------------------------------

def test_fallback_is_requested_but_never_executed(v3_run, v3_outputs):
    """Whatever fallback requests exist carry everything the next stage needs,
    and nothing ran. Asserted from the ARTEFACTS: a shared pytest session
    imports other suites' dependencies into the same process, so a process-wide
    module check here would be testing the session and not this code path."""
    text = (v3_outputs / "fallback_class_requests_v3_r1.jsonl").read_text("utf-8")
    records = [json.loads(line) for line in text.splitlines() if line.strip()]
    frozen = {h["answer_uri"]: h for h in v3_run.inputs.handoffs}
    for record in records:
        assert record["failure_reason"].startswith("FALLBACK_CLASS_REQUIRED_")
        assert record["fallback_class_executed_in_this_task"] is False
        handoff = frozen[record["answer_uri"]]
        # The failed class and the candidate count are the FROZEN Prompt-8D
        # ones: nothing selected a new class, retrieved members, built a graph
        # or ranked anything.
        assert record["failed_selected_class_uri"] == handoff["selected_class_uri"]
        assert record["candidate_count"] == handoff["ranked_candidate_count"]
        assert record["current_graph_fingerprint"] == handoff["graph_fingerprint"]
        assert record["requested_next_stage"]
    # And every ready Answer still searched exactly its frozen candidate roster.
    for selection in v3_run.ready_selections:
        assert (selection.table.candidate_count
                == frozen[selection.answer_uri]["ranked_candidate_count"])


def test_zero_network_attempts(v3_run):
    assert v3_run.guard_record["network_attempts"] == 0
    assert v3_run.guard_record["http_calls"] == 0
    assert v3_run.guard_record["sparql_calls"] == 0
    assert v3_run.guard_record["attempted_addresses"] == []


def test_no_forbidden_imports_on_the_r1_path():
    """A STANDALONE process: a shared pytest session imports other suites' deps."""
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "from pipeline import rationale_v3_run as r\n"
        "run = r.run_rationale_v3(verbose=False, run_reduced_arm=False)\n"
        "print('ATTEMPTS', run.guard_record['network_attempts'])\n"
        "print('FORBIDDEN', list(run.forbidden_modules))\n"
        "print('KG_LOADED', 'kg.loader' in sys.modules)\n"
    ) % str(SRC_DIR)
    completed = subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT,
                               capture_output=True, text=True, timeout=1800)
    assert completed.returncode == 0, completed.stderr[-3000:]
    assert "ATTEMPTS 0" in completed.stdout
    assert "FORBIDDEN []" in completed.stdout
    assert "KG_LOADED False" in completed.stdout, (
        "the scientific run must not open the pinned pickle")


def test_prompt8e_tests_still_pass():
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_rationale_selection.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=3600)
    assert completed.returncode == 0, completed.stdout[-4000:]


def test_prompt8e_outputs_are_byte_identical_under_replay(tmp_path):
    replay = tmp_path / "prompt8e_replay"
    completed = subprocess.run(
        [sys.executable, "src/extract_221_and_select_distractors_ClaudeWeb_v2.py",
         "--mode", "pilot-rationale-selection", "--output-dir", str(replay),
         "--quiet"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=3600)
    assert completed.returncode == 0, completed.stderr[-3000:]
    compared = json.loads(
        (FROZEN_8E_DIR / "offline_replay_manifest.json").read_text("utf-8"))
    for name in compared["byte_identical_files"]:
        assert (replay / name).read_bytes() == (FROZEN_8E_DIR / name).read_bytes(), (
            f"Prompt-8E output {name} changed")


def test_r1_outputs_are_byte_identical_across_two_runs(tmp_path):
    first, second = tmp_path / "r1_a", tmp_path / "r1_b"
    for target in (first, second):
        completed = subprocess.run(
            [sys.executable, "src/extract_and_select_distractors_v3.py",
             "--mode", "pilot-rationale-v3-r1", "--output-dir", str(target),
             "--quiet"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=3600)
        assert completed.returncode == 0, completed.stderr[-3000:]
    for name in runner.REPLAY_COMPARED_FILES:
        assert (first / name).read_bytes() == (second / name).read_bytes(), (
            f"R1 output {name} is not reproducible")


def test_protected_source_hashes_are_unchanged():
    observed = runner.verify_protected_sources()
    assert len(observed) == 17
    for name, record in observed.items():
        assert record["unmodified"] is True, name


def test_prompt8f_parent_commit_stays_recoverable():
    """The Prompt-8F baseline must remain reachable in Git, so anything R1
    removed can be restored without re-deriving it."""
    for args in (["cat-file", "-e", PROMPT8F_PARENT_COMMIT],
                 ["cat-file", "-e",
                  f"{PROMPT8F_PARENT_COMMIT}:src/rationale_v3/evidence.py"],
                 ["cat-file", "-e",
                  f"{PROMPT8F_PARENT_COMMIT}:src/pipeline/rationale_v3_run.py"]):
        completed = subprocess.run(["git", *args], cwd=REPO_ROOT,
                                   capture_output=True, text=True)
        assert completed.returncode == 0, f"{args}: {completed.stderr}"
    assert FROZEN_8F_DIR.is_dir(), "the frozen Prompt-8F package was removed"


# --- GROUP G — STRUCTURAL CHECKS ON THE PILOT RUN ----------------------------

def _summary_rows(v3_outputs):
    return list(csv.DictReader(
        (v3_outputs / "rationale_v3_r1_summary.csv").open(encoding="utf-8")))


def _comparison_rows(v3_outputs):
    return {row["answer_uri"]: row for row in csv.DictReader(
        (v3_outputs / "prompt8e_v3_v3r1_comparison.csv").open(encoding="utf-8"))}


def test_summary_has_nine_primary_rows_with_sulfuric_acid_not_ready(v3_outputs):
    rows = _summary_rows(v3_outputs)
    assert len(rows) == 9
    assert all(row["primary_or_diagnostic"] == "primary" for row in rows)
    sulfuric = next(r for r in rows if r["answer_uri"].endswith("/Sulfuric_acid"))
    assert sulfuric["selection_status"] == "PRIMARY_NOT_READY"
    assert sulfuric["ready_for_rationale_selection"] == "false"
    assert sulfuric["eligible_for_main_corpus"] == "false"


def test_diagnostic_namespace_stays_out_of_the_primary_metrics(v3_run, v3_outputs):
    manifest = json.loads((v3_outputs / "run_manifest.json").read_text("utf-8"))
    diagnostic = manifest["sulfuric_acid_diagnostic"]
    assert diagnostic["diagnostic_only"] is True
    assert diagnostic["excluded_from_primary_policy_metrics"] is True
    assert all(value is False for value in diagnostic["boundaries"].values())
    counts = manifest["counts"]
    assert counts["primary_answer_denominator"] == 9
    assert counts["primary_ready_for_rationale_selection"] == 8
    assert counts["primary_ranked_candidate_total"] == 204


def test_automatic_generation_fields_replace_human_validation(v3_outputs):
    for row in _summary_rows(v3_outputs):
        assert row["generation_is_automatic"] == "true"
        assert row["manual_intervention_used"] == "false"
        assert row["post_generation_human_evaluation_status"] == "NOT_STARTED"
        assert row["publishable_final"] == "false"
    for line in (v3_outputs / "selected_mcqs_v3_r1.jsonl").read_text(
            "utf-8").splitlines():
        record = json.loads(line)
        assert record["generation_is_automatic"] is True
        assert record["manual_intervention_used"] is False
        assert record["publishable_final"] is False
        assert "requires_human_validation" not in record


def test_l0_only_results_are_never_main_corpus_eligible(v3_run):
    for selection in v3_run.selections:
        if selection.evidence_policy == POLICY_DIAGNOSTIC_L0:
            assert selection.eligible_for_main_corpus is False
            assert selection.eligible_for_diagnostic_corpus is True
            assert selection.fallback_status


def test_no_forbidden_claim_language_in_any_output(v3_outputs):
    for name in (*runner.REPLAY_COMPARED_FILES, "run_manifest.json",
                 "offline_replay_manifest.json"):
        assert_no_negative_claim((v3_outputs / name).read_text("utf-8"), where=name)
    text = (v3_outputs / "run_manifest.json").read_text("utf-8").lower()
    for phrase in FORBIDDEN_NEGATIVE_CLAIM_PHRASES:
        assert phrase not in text


def test_local_anonymity_is_not_labelled_global_class_anonymity(v3_outputs):
    text = (v3_outputs / "selected_mcqs_v3_r1.jsonl").read_text("utf-8")
    assert "local_candidate_pool_anonymity_count" in text
    assert "global_class_anonymity" not in text
    assert "class_anonymity" not in text.replace(
        "local_candidate_pool_anonymity", "")
    record = json.loads(text.splitlines()[0])
    assert "COMPLETE ranked candidate" in record[
        "local_candidate_pool_anonymity_note"]


def test_eisaku_sato_no_longer_uses_dbp_url(v3_outputs):
    row = _comparison_rows(v3_outputs)[R + "Eisaku_Satō"]
    assert P + "url" in row["prompt8e_rationale"]
    assert P + "url" not in row["r1_rationale"]
    assert row["r1_rejected_the_prompt8e_rationale"] == "true"
    reasons = set(row["r1_rejection_reasons"].split("|"))
    assert {"PREDICATE_EXTERNAL_URL_FIELD", "OBJECT_WEB_ARCHIVE_URL"} <= reasons
    # And the hard filter, not the taxonomy, is what removed it.
    assert row["quality_filter_effect"] == "true"
    assert P + "url" in row["r1_quality_off_rationale"]


def test_carbon_no_longer_uses_carbonado(v3_outputs):
    row = _comparison_rows(v3_outputs)[R + "Carbon"]
    assert R + "Carbonado" in row["prompt8e_rationale"]
    assert R + "Carbonado" not in row["r1_rationale"]
    assert row["r1_rejected_the_prompt8e_rationale"] == "true"
    assert row["r1_rejection_reasons"] == "ANSWER_LEXICAL_LEAK"


def test_every_changed_selection_is_explained_by_a_named_effect(v3_outputs):
    """No difference from Prompt 8F may be reported without a cause."""
    for answer_uri, row in _comparison_rows(v3_outputs).items():
        if not row["r1_evidence_policy"]:
            continue                                    # PRIMARY_NOT_READY
        changed_distractors = row["distractor_set_identical_8f_vs_r1"] != "true"
        changed_rationale = row["rationale_identical_8f_vs_r1"] != "true"
        if changed_distractors or changed_rationale:
            effects = [row[name] for name in
                       ("taxonomy_effect", "quality_filter_effect",
                        "semantic_safety_effect", "distractor_search_effect")]
            assert "true" in effects, f"{answer_uri}: change with no named cause"


def test_corrected_taxonomy_lifted_every_ready_answer_to_at_least_mcq_l1(v3_run):
    counts = v3_run.counts()
    assert counts["algorithm_selected_diagnostic_l0_only"] == 0
    assert counts["mcq_evidence_level_counts"] == {"MCQ-L1": 8}
    for selection in v3_run.ready_selections:
        assert selection.evidence_policy == POLICY_MAIN_L1
        assert selection.mcq_evidence_level == "MCQ-L1"


def test_entrypoint_mode_is_mandatory_and_unknown_modes_are_refused():
    import extract_and_select_distractors_v3 as entry
    with pytest.raises(SystemExit):
        entry.build_arg_parser().parse_args([])
    with pytest.raises(SystemExit):
        entry.build_arg_parser().parse_args(["--mode", "legacy-overlap"])
    assert entry.MODES == ("pilot-rationale-v3-r1", "build-semantic-index")
    # The entrypoint owns no rationale mathematics.
    source = (SRC_DIR / "extract_and_select_distractors_v3.py").read_text("utf-8")
    for banned in ("def exact_minimum_rationale", "def cover_size_table",
                   "def classify_fact_against_candidate", "itertools",
                   "def _mask_class_census", "coverage_mask"):
        assert banned not in source, banned
    assert entry.DEFAULT_PROMPT8D_DIR == str(runner.FROZEN_PROMPT8D_DIR)
    assert entry.DEFAULT_SEMANTIC_INDEX_CACHE == str(
        runner.DEFAULT_SEMANTIC_INDEX_CACHE)


def test_prompt8e_reason_code_mapping_is_total():
    from rationale_v3.contracts import (
        ALL_REASON_CODES, PROMPT8E_STATUS_FOR_REASON_CODE)
    assert set(PROMPT8E_STATUS_FOR_REASON_CODE) == set(ALL_REASON_CODES)
