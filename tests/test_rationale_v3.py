############################################################################
# tests/test_rationale_v3.py
#
# Contract tests for the Prompt-8F rationale V3 layer:
#   src/rationale_v3/contracts.py
#   src/rationale_v3/semantic_relations.py
#   src/rationale_v3/evidence.py
#   src/rationale_v3/quality.py
#   src/rationale_v3/setcover.py
#   src/rationale_v3/selector.py
#   src/pipeline/rationale_v3_run.py
#   src/extract_and_select_distractors_v3.py   (mode dispatch only)
#
# WHAT THESE TESTS DEFEND
#   * a different object under an UNCONSTRAINED multi-valued predicate is L0 and
#     never L1 or L2 — the single most important scientific boundary in V3;
#   * L2 is unreachable without a machine-checkable proof, and a missing
#     qualifier blocks temporal L2 by construction;
#   * a candidate that SUPPORTS the proposition — by identity, by redirect, or by
#     lying under the claim object — is NOT_COVERED before any rule can run;
#   * the parent-child closure is depth-bounded and cycle-safe, and IN never
#     merges with OUT;
#   * the exact bitmask DP equals brute force on 1,000+ deterministic random
#     cases, and reproduces the Prompt-8E result when V3's features are off;
#   * canonical URI ordering decides a rationale ONLY when every scientific and
#     pedagogical key is exactly tied;
#   * dbp:url, a Web Archive object and Carbon/Carbonado are rejected, while a
#     short shared prefix and chemical Roman numerals are not touched;
#   * a 1,000-candidate ranking never enumerates its 166,167,000 triples;
#   * a fallback class is REQUESTED and never executed, and the Bipartite graph
#     is emitted as candidates and never selected;
#   * the Prompt-8E baseline still passes and still reproduces byte for byte.
#
# OFFLINE
#   No network. The 1.2 GB pinned pickle is NEVER loaded by these tests: the
#   semantic index is consumed from its cache, and every other input is a frozen
#   JSONL file.
#
# Run:
#     python -m pytest -vv tests/test_rationale_v3.py
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
FROZEN_8E_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_rationale_selection_2026-08-01")
SEMANTIC_CACHE = (
    REPO_ROOT / "data" / "semantic_index_v3" / "pilot_place_containment_v1.json")
POLICY_DIR = SRC_DIR / "rationale_v3" / "policies"

from pipeline import rationale_v3_run as runner                        # noqa: E402
from rationale_v3.contracts import (                                   # noqa: E402
    DIRECTION_IN,
    DIRECTION_OUT,
    FALLBACK_L0_ONLY,
    FORBIDDEN_NEGATIVE_CLAIM_PHRASES,
    L0_DIFFERENT_OBJECTS_NONEXCLUSIVE,
    L0_GRANULARITY_RISK,
    L0_KEY_ABSENT,
    L0_SEMANTIC_RELATION_UNKNOWN,
    LEVEL_L0,
    LEVEL_L1,
    LEVEL_L2,
    LEVEL_NOT_COVERED,
    NOT_COVERED_CANONICALLY_EQUIVALENT,
    NOT_COVERED_EXACT_EQUAL,
    NOT_COVERED_SEMANTIC_ENTAILMENT,
    POLICY_DIAGNOSTIC_L0,
    POLICY_MAIN_L1PLUS,
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
    RULE_TYPE_FUNCTIONAL_PROPERTY,
    RULE_TYPE_EXPLICIT_NEGATIVE,
    RULE_TYPE_TEMPORAL_EXCLUSIVE,
    SEARCH_FULL_EXACT,
    SEARCH_POOL_EXACT,
    AnswerFact,
    RationaleProposition,
    RationaleV3ContractError,
    assert_no_negative_claim,
    covers_under_policy,
)
from rationale_v3.evidence import (                                    # noqa: E402
    EmpiricalDerivationConfig,
    EvidenceRule,
    EvidenceRuleBook,
    ScopeKeyObservation,
    classify_fact_against_candidate,
    derive_empirical_single_valued_rules,
    load_evidence_rules,
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
    normalize_uri,
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
    select_for_answer,
)

R = "http://dbpedia.org/resource/"
P = "http://dbpedia.org/property/"
SCOPE = R + "Category:Test_scope"
FINGERPRINT = "fp"


# ==========================================================================
# FIXTURES AND SMALL BUILDERS
# ==========================================================================

@pytest.fixture(scope="session")
def quality_policy():
    return load_quality_policy(POLICY_DIR / "predicate_policy.json")


@pytest.fixture(scope="session")
def real_semantic_policy():
    return load_semantic_relation_policy(POLICY_DIR / "semantic_relation_policy.json")


@pytest.fixture(scope="session")
def real_semantic_index(real_semantic_policy):
    """The cached pilot index. Never loads the pinned pickle."""
    payload = json.loads(SEMANTIC_CACHE.read_text(encoding="utf-8"))
    key = SemanticIndexCacheKey(**payload["cache_key"])
    return load_semantic_index_cache(SEMANTIC_CACHE, policy=real_semantic_policy,
                                     expected_key=key)


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
            minimum_support=3, support_ablation_values=(3,),
            maximum_observed_canonical_cardinality=1, maximum_violations=0,
            active_directions=(DIRECTION_OUT,),
            inactive_direction_reason={DIRECTION_IN: "IN_DIRECTION_"
                                       "EMPIRICAL_CARDINALITY_NOT_TRUSTED"},
            empirical_label="EMPIRICAL_AND_SCOPED_NOT_UNIVERSAL",
            version="test/1"),
        rules=tuple(rules), require_semantic_closure_for_l1=require_closure)


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


def functional_rule(predicate=P + "birthPlace", *, status=RULE_ACTIVE):
    return EvidenceRule(
        rule_id="FUNC_BIRTHPLACE", rule_type=RULE_TYPE_FUNCTIONAL_PROPERTY,
        predicate_uri=predicate, direction=DIRECTION_OUT, scope=SCOPE,
        scope_kind="TEST", required_evidence=("functional declaration",),
        minimum_support=0, observed_support=0, maximum_observed_cardinality=1,
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
        proposition=prop or proposition(),
        candidate_uri=R + "Candidate",
        candidate_objects=list(objects),
        semantic_index=index if index is not None else synthetic_index(),
        rulebook=rulebook or empty_rulebook(),
        scope=scope)


def fact(predicate, direction, counterpart):
    return AnswerFact(predicate_uri=predicate, direction=direction,
                      counterpart_uri=counterpart,
                      graph_fingerprint=FINGERPRINT)


def answer_input(answer_facts, candidate_facts, *, n=None, scores=None,
                 answer_uri=R + "Answer"):
    """A synthetic AnswerInput. Candidate rank order is the sorted URI order.

    Names come from `candidate_facts` whenever it is non-empty, so a caller can
    never generate a roster that silently fails to match its own fact keys.
    """
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


def coverage_facts(specs):
    """[(mask, tie_weight, key_suffix)] -> CoverageFacts in canonical order."""
    return tuple(
        CoverageFact(fact_index=i, canonical_key=(P + "p", DIRECTION_OUT,
                                                  R + suffix),
                     coverage_mask=mask, tie_weight=weight)
        for i, (mask, weight, suffix) in enumerate(specs))


# ==========================================================================
# GROUP A — EVIDENCE AND MULTI-VALUED PREDICATES  (§16 items 1-12)
# ==========================================================================

def test_01_different_objects_unconstrained_predicate_is_l0_only():
    """A different observed object, with no active rule, is L0. Never L1/L2."""
    result = classify([R + "Kyoto"])
    assert result.level == LEVEL_L0
    assert result.reason_code == L0_DIFFERENT_OBJECTS_NONEXCLUSIVE
    assert result.proof is None
    assert result.applied_rule_id == ""


def test_02_candidate_key_absent_is_l0():
    result = classify([])
    assert result.level == LEVEL_L0
    assert result.reason_code == L0_KEY_ABSENT
    assert result.candidate_object_uris == ()


def test_03_candidate_shares_exact_answer_object_is_not_covered():
    result = classify([R + "Tokyo"])
    assert result.level == LEVEL_NOT_COVERED
    assert result.reason_code == NOT_COVERED_EXACT_EQUAL
    for policy in (POLICY_STRICT_L2, POLICY_MAIN_L1PLUS, POLICY_DIAGNOSTIC_L0):
        assert not covers_under_policy(result.level, policy)


def test_04_candidate_has_answer_object_plus_alternatives_is_not_covered():
    """The multi-valued case Prompt 8E's set logic already got right, kept."""
    result = classify([R + "Tokyo", R + "Kyoto", R + "Osaka"])
    assert result.level == LEVEL_NOT_COVERED
    assert result.reason_code == NOT_COVERED_EXACT_EQUAL


def test_05_active_scoped_single_valued_rule_produces_l1():
    book = empty_rulebook(rules=[single_valued_rule()])
    result = classify([R + "Kyoto"], rulebook=book)
    assert result.level == LEVEL_L1
    assert result.applied_rule_type == RULE_TYPE_EMPIRICAL_SINGLE_VALUED
    assert result.proof is None
    assert covers_under_policy(result.level, POLICY_MAIN_L1PLUS)
    assert not covers_under_policy(result.level, POLICY_STRICT_L2)


def test_06_inactive_or_proposed_rule_cannot_produce_l1():
    for status in (RULE_PROPOSED_NOT_ACTIVE, "INACTIVE"):
        book = empty_rulebook(rules=[single_valued_rule(status=status)])
        result = classify([R + "Kyoto"], rulebook=book)
        assert result.level == LEVEL_L0, status
        assert result.applied_rule_id == ""


def test_07_trusted_functional_property_conflict_produces_l2():
    book = empty_rulebook(rules=[functional_rule()])
    result = classify([R + "Kyoto"], rulebook=book)
    assert result.level == LEVEL_L2
    assert result.proof is not None
    assert result.proof.ontology_source
    assert result.proof.premises
    assert result.proof.conclusion
    assert covers_under_policy(result.level, POLICY_STRICT_L2)


def test_08_distinct_objects_without_functional_proof_cannot_produce_l2():
    """Only-one-value-observed is not functionality. The rule must be declared."""
    book = empty_rulebook(rules=[single_valued_rule()])
    result = classify([R + "Kyoto"], rulebook=book)
    assert result.level == LEVEL_L1
    assert result.proof is None
    plain = classify([R + "Kyoto"])
    assert plain.level == LEVEL_L0


def test_09_explicit_negative_assertion_produces_l2():
    rule = EvidenceRule(
        rule_id="NEG_1", rule_type=RULE_TYPE_EXPLICIT_NEGATIVE,
        predicate_uri=P + "birthPlace", direction=DIRECTION_OUT, scope=SCOPE,
        scope_kind="TEST", required_evidence=("explicit negative assertion",),
        minimum_support=0, observed_support=0, maximum_observed_cardinality=0,
        observed_violation_count=0, source="test", provenance="synthetic",
        version="test/1", activation_status=RULE_ACTIVE,
        ontology_source="synthetic source carrying an explicit negative "
                        "property assertion")
    result = classify([R + "Kyoto"], rulebook=empty_rulebook(rules=[rule]))
    assert result.level == LEVEL_L2
    assert result.proof is not None
    assert result.proof.rule_type == RULE_TYPE_EXPLICIT_NEGATIVE


def test_10_missing_qualifier_blocks_temporal_l2():
    rule = EvidenceRule(
        rule_id="TEMPORAL_1", rule_type=RULE_TYPE_TEMPORAL_EXCLUSIVE,
        predicate_uri=P + "office", direction=DIRECTION_OUT, scope=SCOPE,
        scope_kind="TEST", required_evidence=("qualifiers",),
        minimum_support=0, observed_support=0, maximum_observed_cardinality=1,
        observed_violation_count=0, source="test", provenance="synthetic",
        version="test/1", activation_status=RULE_ACTIVE,
        ontology_source="synthetic temporal exclusivity source")
    prop = proposition(predicate=P + "office", obj=R + "Prime_Minister")
    assert prop.qualifier_status == QUALIFIER_UNAVAILABLE
    result = classify([R + "President"], rulebook=empty_rulebook(rules=[rule]),
                      prop=prop)
    assert result.level == LEVEL_L0
    assert result.proof is None
    assert "TEMPORAL_1" in result.blocked_rule_ids


def test_11_complete_temporal_qualified_conflict_can_produce_l2():
    rule = EvidenceRule(
        rule_id="TEMPORAL_2", rule_type=RULE_TYPE_TEMPORAL_EXCLUSIVE,
        predicate_uri=P + "office", direction=DIRECTION_OUT, scope=SCOPE,
        scope_kind="TEST", required_evidence=("qualifiers",),
        minimum_support=0, observed_support=0, maximum_observed_cardinality=1,
        observed_violation_count=0, source="test", provenance="synthetic",
        version="test/1", activation_status=RULE_ACTIVE,
        ontology_source="synthetic temporal exclusivity source")
    prop = proposition(predicate=P + "office", obj=R + "Prime_Minister",
                       qualifiers=(("startTime", "1964-11-09"),
                                   ("endTime", "1972-07-07")))
    result = classify([R + "President"], rulebook=empty_rulebook(rules=[rule]),
                      prop=prop)
    assert result.level == LEVEL_L2
    assert result.proof is not None
    assert result.proof.qualifier_context == QUALIFIER_PRESENT


def test_12_no_real_pilot_case_is_forced_to_l2_without_proof(v3_run):
    """Zero L2 on the pilot, and every L2 anywhere carries an EvidenceProof."""
    counts = v3_run.counts()["fact_candidate_level_incidences_all_facts"]
    assert counts[LEVEL_L2] == 0
    for selection in v3_run.ready_selections:
        for row in selection.table.evidence:
            for item in row:
                assert (item.level == LEVEL_L2) == (item.proof is not None)


# ==========================================================================
# GROUP B — SEMANTIC SAFETY  (§16 items 13-21)
# ==========================================================================

def test_13_exact_equality():
    index = synthetic_index()
    assert index.classify(R + "Tokyo", R + "Tokyo").relation == RELATION_EXACT_EQUAL
    # Normalization is not a semantic claim, but it must still make the same URI
    # compare equal to itself through the pickle's bracketed spelling.
    assert index.classify(R + "Tokyo",
                          "<" + R + "Tokyo>").relation == RELATION_EXACT_EQUAL


def test_14_canonical_equivalence():
    index = synthetic_index(
        equivalence=[(R + "Antisthenes_(Heraclitean)", R + "Heraclitus")])
    result = index.classify(R + "Heraclitus", R + "Antisthenes_(Heraclitean)")
    assert result.relation == RELATION_CANONICALLY_EQUIVALENT
    covered = classify([R + "Antisthenes_(Heraclitean)"], index=index,
                       prop=proposition(obj=R + "Heraclitus"))
    assert covered.level == LEVEL_NOT_COVERED
    assert covered.reason_code == NOT_COVERED_CANONICALLY_EQUIVALENT


def test_15_candidate_child_entails_general_claim_and_is_not_covered():
    index = synthetic_index([(R + "Bunkyo", R + "Tokyo")])
    assert index.classify(R + "Tokyo", R + "Bunkyo").relation == (
        RELATION_CANDIDATE_UNDER_CLAIM)
    result = classify([R + "Bunkyo"], index=index)
    assert result.level == LEVEL_NOT_COVERED
    assert result.reason_code == NOT_COVERED_SEMANTIC_ENTAILMENT


def test_16_answer_child_versus_candidate_parent_creates_granularity_risk():
    index = synthetic_index([(R + "Bunkyo", R + "Tokyo")])
    prop = proposition(obj=R + "Bunkyo")
    assert index.classify(R + "Bunkyo", R + "Tokyo").relation == (
        RELATION_CLAIM_UNDER_CANDIDATE)
    result = classify([R + "Tokyo"], index=index, prop=prop)
    assert result.granularity_risk is True
    assert result.level == LEVEL_L0
    assert result.reason_code == L0_GRANULARITY_RISK
    # And an active L1 rule may NOT rescue it unless it says it resolves the case.
    book = empty_rulebook(rules=[single_valued_rule()])
    blocked = classify([R + "Tokyo"], index=index, prop=prop, rulebook=book)
    assert blocked.level == LEVEL_L0
    assert blocked.blocked_rule_ids


def test_17_proven_disjoint_relation_is_recorded():
    index = synthetic_index(disjoint=[(R + "Solid", R + "Liquid")])
    result = index.classify(R + "Solid", R + "Liquid")
    assert result.relation == RELATION_PROVEN_DISJOINT
    # Recorded, but it does NOT by itself create exclusion evidence.
    assessed = classify([R + "Liquid"], index=index,
                        prop=proposition(obj=R + "Solid"))
    assert assessed.level == LEVEL_L0


def test_18_unknown_semantic_relation_remains_unknown():
    index = synthetic_index([(R + "Bunkyo", R + "Tokyo")])
    assert index.classify(R + "Tokyo", R + "Paris").relation == (
        RELATION_UNRELATED_OR_UNKNOWN)
    # No index at all is a DIFFERENT state, and it caps the level at L0.
    missing = unavailable_semantic_index(synthetic_policy(), "no cache in test")
    assert missing.classify(R + "Tokyo", R + "Paris").relation == (
        RELATION_UNAVAILABLE)
    book = empty_rulebook(rules=[single_valued_rule()])
    result = classify([R + "Paris"], index=missing, rulebook=book)
    assert result.level == LEVEL_L0
    assert result.reason_code == L0_SEMANTIC_RELATION_UNKNOWN


def test_19_closure_is_depth_bounded():
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


def test_20_closure_is_cycle_safe():
    cyclic = synthetic_index(
        [(R + "A", R + "B"), (R + "B", R + "C"), (R + "C", R + "A")],
        max_depth=10)
    ancestors = cyclic.ancestors(R + "A")          # must terminate
    assert set(ancestors) == {R + "B", R + "C"}
    assert R + "A" not in ancestors


def test_21_in_and_out_never_merge():
    facts = [fact(P + "influenced", DIRECTION_OUT, R + "X")]
    candidate = {R + "Cand0": [fact(P + "influenced", DIRECTION_IN, R + "X")],
                 R + "Cand1": [fact(P + "influenced", DIRECTION_IN, R + "X")],
                 R + "Cand2": [fact(P + "influenced", DIRECTION_IN, R + "X")]}
    table = build_evidence_table(
        answer_input(facts, candidate),
        semantic_index=synthetic_index(), rulebook=empty_rulebook(),
        quality_policy=load_quality_policy(POLICY_DIR / "predicate_policy.json"))
    # The candidates hold the SAME counterpart but in the other direction, so the
    # OUT fact must not see it as support.
    for position in range(3):
        item = table.evidence[0][position]
        assert item.level == LEVEL_L0
        assert item.reason_code == L0_KEY_ABSENT


# ==========================================================================
# GROUP C — SET COVER AND RATIONALE RANKING  (§16 items 22-31)
# ==========================================================================

def test_22_prompt8e_two_fact_counterexample_remains_correct():
    """AUDIT item EX-3 / test T2.3: f1 covers d1+d2, f2 covers d3. |R*| = 2."""
    facts = coverage_facts([(0b011, 0, "f1"), (0b100, 0, "f2")])
    cover = exact_minimum_rationale(facts, k=3, rho=3,
                                    evidence_policy=POLICY_DIAGNOSTIC_L0)
    assert cover.full_coverage is True
    assert cover.minimum_rationale_size == 2
    assert len(cover.selected_rationale) == 2
    assert minimum_cover_size([0b011, 0b100], 3) == 2


def test_23_exact_dp_equals_brute_force_on_random_cases():
    rng = random.Random(20260803)
    checked = 0
    for _ in range(1200):
        k = rng.randint(1, 5)
        m = rng.randint(1, 12)
        specs = []
        for i in range(m):
            mask = rng.randrange(0, 1 << k)
            weight = rng.randint(0, bin(mask).count("1"))
            specs.append((mask, weight, f"f{i:03d}"))
        facts = coverage_facts(specs)
        fast = exact_minimum_rationale(facts, k=k, rho=k,
                                       evidence_policy=POLICY_DIAGNOSTIC_L0)
        slow = brute_force_minimum_rationale(facts, k=k, rho=k,
                                             evidence_policy=POLICY_DIAGNOSTIC_L0)
        assert fast.coverage_mask == slow.coverage_mask
        assert fast.minimum_rationale_size == slow.minimum_rationale_size
        assert fast.tie_weight_total == slow.tie_weight_total
        assert fast.full_coverage == slow.full_coverage
        assert fast.selected_rationale_keys() == slow.selected_rationale_keys()
        assert fast.optimal_rationale_count == slow.optimal_rationale_count
        checked += 1
    assert checked >= 1000


def test_23b_v3_dp_reproduces_prompt8e_dp_with_features_disabled():
    """§8: with V3's extra features off, the copied DP must agree with 8E's."""
    from rationale import setcover as prompt8e_setcover
    rng = random.Random(8531)
    for _ in range(300):
        k = rng.randint(1, 4)
        m = rng.randint(1, 9)
        specs = []
        for i in range(m):
            mask = rng.randrange(0, 1 << k)
            weight = rng.randint(0, bin(mask).count("1"))
            specs.append((mask, weight, f"f{i:03d}"))
        v3 = exact_minimum_rationale(coverage_facts(specs), k=k, rho=k,
                                     evidence_policy=POLICY_DIAGNOSTIC_L0)
        old = prompt8e_setcover.exact_minimum_rationale(
            tuple(prompt8e_setcover.CoverageFact(
                fact_index=i, canonical_key=(P + "p", DIRECTION_OUT, R + s),
                coverage_mask=mask, absence_incidences=w)
                for i, (mask, w, s) in enumerate(specs)),
            k=k, rho=k, evidence_policy="snapshot-observed")
        assert v3.minimum_rationale_size == old.minimum_rationale_size
        assert v3.coverage_mask == old.coverage_mask
        assert v3.full_coverage == old.full_coverage
        assert v3.optimal_rationale_count == old.optimal_rationale_count
        assert v3.selected_rationale_keys() == old.selected_rationale_keys()


def test_24_policy_masks_differ_correctly():
    facts = [fact(P + "birthPlace", DIRECTION_OUT, R + "Tokyo")]
    candidates = {R + "Cand0": [fact(P + "birthPlace", DIRECTION_OUT, R + "Kyoto")],
                  R + "Cand1": [], R + "Cand2": []}
    book = empty_rulebook(rules=[single_valued_rule()])
    table = build_evidence_table(
        answer_input(facts, candidates),
        semantic_index=synthetic_index(), rulebook=book,
        quality_policy=load_quality_policy(POLICY_DIR / "predicate_policy.json"))
    assert table.level(0, 0) == LEVEL_L1
    assert table.level(0, 1) == LEVEL_L0
    assert table.covering_bitset(0, LEVEL_L2) == 0
    assert table.covering_bitset(0, LEVEL_L1) == 0b1
    assert table.covering_bitset(0, LEVEL_L0) == 0b1
    assert table.covering_bitset(1, LEVEL_L1) == 0
    assert table.covering_bitset(1, LEVEL_L0) == 0b1


def test_25_rationale_minimum_evidence_level_is_correct():
    """L_min(R) = the WEAKEST per-candidate best level over the distractors."""
    facts = [fact(P + "birthPlace", DIRECTION_OUT, R + "Tokyo"),
             fact(P + "almaMater", DIRECTION_OUT, R + "Kyoto_University")]
    candidates = {
        R + "Cand0": [fact(P + "birthPlace", DIRECTION_OUT, R + "Osaka")],
        R + "Cand1": [fact(P + "birthPlace", DIRECTION_OUT, R + "Nara")],
        R + "Cand2": [],                      # only reachable at L0
    }
    book = empty_rulebook(rules=[single_valued_rule()])
    table = build_evidence_table(
        answer_input(facts, candidates), semantic_index=synthetic_index(),
        rulebook=book,
        quality_policy=load_quality_policy(POLICY_DIR / "predicate_policy.json"))
    ranking = rank_minimum_rationales(table, (0, 1, 2),
                                      policy=POLICY_DIAGNOSTIC_L0, k=3, rho=3)
    assert ranking.full_coverage is True
    assert ranking.achieved_min_level == LEVEL_L0
    best = ranking.best
    assert sorted(best.per_candidate_best_level) == [LEVEL_L0, LEVEL_L1, LEVEL_L1]
    l1_only = rank_minimum_rationales(table, (0, 1, 2),
                                      policy=POLICY_MAIN_L1PLUS, k=3, rho=3)
    assert l1_only.full_coverage is False


def _two_way_table(second_predicate, second_object, *, rulebook=None,
                   quality_policy=None, index=None):
    """Two Answer facts, each covering ALL three distractors on its own.

    Both are minimum covers of size one, so the choice between them is decided
    purely by the §10 ranking — which is what the next four tests probe.
    """
    facts = [fact(P + "birthPlace", DIRECTION_OUT, R + "AAA_Tokyo"),
             fact(second_predicate, DIRECTION_OUT, second_object)]
    candidates = {f"{R}Cand{i}": [
        fact(P + "birthPlace", DIRECTION_OUT, R + f"Other{i}"),
        fact(second_predicate, DIRECTION_OUT, R + f"Alt{i}")] for i in range(3)}
    return build_evidence_table(
        answer_input(facts, candidates),
        semantic_index=index if index is not None else synthetic_index(),
        rulebook=rulebook or empty_rulebook(),
        quality_policy=quality_policy or load_quality_policy(
            POLICY_DIR / "predicate_policy.json"))


def test_26_evidence_strength_beats_uri_ordering():
    """`AAA_Tokyo` sorts first by URI, but only the other fact reaches L1."""
    book = empty_rulebook(rules=[single_valued_rule(predicate=P + "almaMater")])
    table = _two_way_table(P + "almaMater", R + "ZZZ_Kyoto_University",
                           rulebook=book)
    ranking = rank_minimum_rationales(table, (0, 1, 2),
                                      policy=POLICY_DIAGNOSTIC_L0, k=3, rho=3)
    assert ranking.achieved_min_level == LEVEL_L1
    chosen = table.facts[ranking.best.fact_indices[0]]
    assert chosen.predicate_uri == P + "almaMater"
    assert chosen.counterpart_uri == R + "ZZZ_Kyoto_University"


def test_27_semantic_safety_beats_uri_ordering():
    """The URI-first fact carries granularity risk, so the other one wins."""
    facts = [fact(P + "birthPlace", DIRECTION_OUT, R + "AAA_Bunkyo"),
             fact(P + "deathPlace", DIRECTION_OUT, R + "ZZZ_Nara")]
    candidates = {f"{R}Cand{i}": [
        fact(P + "birthPlace", DIRECTION_OUT, R + "Tokyo"),
        fact(P + "deathPlace", DIRECTION_OUT, R + f"Alt{i}")] for i in range(3)}
    index = synthetic_index([(R + "AAA_Bunkyo", R + "Tokyo")])
    table = build_evidence_table(
        answer_input(facts, candidates), semantic_index=index,
        rulebook=empty_rulebook(),
        quality_policy=load_quality_policy(POLICY_DIR / "predicate_policy.json"))
    assert table.evidence[0][0].granularity_risk is True
    ranking = rank_minimum_rationales(table, (0, 1, 2),
                                      policy=POLICY_DIAGNOSTIC_L0, k=3, rho=3)
    chosen = table.facts[ranking.best.fact_indices[0]]
    assert chosen.predicate_uri == P + "deathPlace"
    assert ranking.best.granularity_risk_incidences == 0


def test_28_pedagogical_and_verbalizability_quality_beats_uri_ordering():
    """`dbp:chassis` sorts before `dbp:knownFor` and has no template. It loses."""
    facts = [fact(P + "chassis", DIRECTION_OUT, R + "AAA_Frame"),
             fact(P + "knownFor", DIRECTION_OUT, R + "ZZZ_Relativity")]
    candidates = {f"{R}Cand{i}": [
        fact(P + "chassis", DIRECTION_OUT, R + f"OtherFrame{i}"),
        fact(P + "knownFor", DIRECTION_OUT, R + f"OtherIdea{i}")]
        for i in range(3)}
    policy = load_quality_policy(POLICY_DIR / "predicate_policy.json")
    table = build_evidence_table(
        answer_input(facts, candidates), semantic_index=synthetic_index(),
        rulebook=empty_rulebook(), quality_policy=policy)
    assert table.quality[0].template_id == TEMPLATE_UNKNOWN
    assert table.quality[1].verbalizable is True
    ranking = rank_minimum_rationales(table, (0, 1, 2),
                                      policy=POLICY_DIAGNOSTIC_L0, k=3, rho=3)
    chosen = table.facts[ranking.best.fact_indices[0]]
    assert chosen.predicate_uri == P + "knownFor"
    assert ranking.best.unverbalizable_count == 0


def test_29_canonical_uri_ordering_is_the_last_resort_only():
    """Two facts identical on every scientific and quality key: URI order wins."""
    facts = [fact(P + "knownFor", DIRECTION_OUT, R + "Alpha"),
             fact(P + "knownFor", DIRECTION_OUT, R + "Betaa")]
    candidates = {f"{R}Cand{i}": [
        fact(P + "knownFor", DIRECTION_OUT, R + f"Gamma{i}")] for i in range(3)}
    table = build_evidence_table(
        answer_input(facts, candidates), semantic_index=synthetic_index(),
        rulebook=empty_rulebook(),
        quality_policy=load_quality_policy(POLICY_DIR / "predicate_policy.json"))
    ranking = rank_minimum_rationales(table, (0, 1, 2),
                                      policy=POLICY_DIAGNOSTIC_L0, k=3, rho=3)
    keys = [choice.ranking_key() for choice in ranking.ranked[:2]]
    assert keys[0][:-1] == keys[1][:-1], "everything but the URI key must tie"
    chosen = table.facts[ranking.best.fact_indices[0]]
    assert chosen.counterpart_uri == R + "Alpha"


def test_30_local_anonymity_is_computed_over_the_complete_local_pool():
    facts = [fact(P + "knownFor", DIRECTION_OUT, R + "Shared")]
    candidates = {
        R + "Cand0": [fact(P + "knownFor", DIRECTION_OUT, R + "Other")],
        R + "Cand1": [fact(P + "knownFor", DIRECTION_OUT, R + "Other")],
        R + "Cand2": [fact(P + "knownFor", DIRECTION_OUT, R + "Other")],
        R + "Cand3": [fact(P + "knownFor", DIRECTION_OUT, R + "Shared")],
        R + "Cand4": [fact(P + "knownFor", DIRECTION_OUT, R + "Shared")],
    }
    table = build_evidence_table(
        answer_input(facts, candidates), semantic_index=synthetic_index(),
        rulebook=empty_rulebook(),
        quality_policy=load_quality_policy(POLICY_DIR / "predicate_policy.json"))
    count, ratio, direct = table.local_anonymity((0,))
    # Answer + Cand3 + Cand4 support it; the pool is Answer + 5 candidates.
    assert count == 3
    assert ratio == pytest.approx(3 / 6)
    assert direct is False
    lone = build_evidence_table(
        answer_input(facts, {k: v for k, v in candidates.items()
                             if k in (R + "Cand0", R + "Cand1", R + "Cand2")}),
        semantic_index=synthetic_index(), rulebook=empty_rulebook(),
        quality_policy=load_quality_policy(POLICY_DIR / "predicate_policy.json"))
    assert lone.local_anonymity((0,)) == (1, pytest.approx(0.25), True)


def test_31_local_anonymity_is_not_labelled_global_class_anonymity(v3_outputs):
    text = (v3_outputs / "selected_rationales_v3.jsonl").read_text(
        encoding="utf-8")
    assert "local_candidate_pool_anonymity_count" in text
    assert "global_class_anonymity" not in text
    assert "class_anonymity" not in text.replace(
        "local_candidate_pool_anonymity", "")
    record = json.loads(text.splitlines()[0])
    assert "COMPLETE ranked candidate" in record[
        "local_candidate_pool_anonymity_note"]


# ==========================================================================
# GROUP D — QUALITY  (§16 items 32-38)
# ==========================================================================

def test_32_dbp_url_is_rejected(quality_policy):
    ok, reason = check_predicate(P + "url", quality_policy)
    assert ok is False
    assert reason == "PREDICATE_EXTERNAL_URL_FIELD"
    assert reason in quality_policy.reject_reason_codes


def test_33_web_archive_object_is_rejected(quality_policy):
    url = ("https://web.archive.org/web/20160307233845/http:/www.open.edu/"
           "openlearn/whats-on/events/openlearn-live-12th-august-2015%23sato")
    ok, reason = check_object(url, quality_policy)
    assert ok is False
    assert reason == "OBJECT_WEB_ARCHIVE_URL"
    assert check_object("http://example.org/page", quality_policy) == (
        False, "OBJECT_EXTERNAL_URL")
    assert check_object(R + "Tokyo", quality_policy)[0] is True


def test_34_carbon_versus_carbonado_is_rejected_as_lexical_leakage(quality_policy):
    result = detect_answer_leakage(R + "Carbon", R + "Carbonado", quality_policy)
    assert result.hard_leak is True
    assert result.reason_code == "ANSWER_LEXICAL_LEAK"
    quality = assess_fact_quality(
        answer_uri=R + "Carbon", predicate_uri=P + "formula",
        direction=DIRECTION_IN, counterpart_uri=R + "Carbonado",
        policy=quality_policy)
    assert quality.eligible is False
    assert "ANSWER_LEXICAL_LEAK" in quality.rejection_reasons


def test_35_short_unrelated_substring_does_not_trigger_leakage(quality_policy):
    for answer, other in ((R + "Carbon", R + "Boron_carbide"),
                          (R + "Carbon", R + "Carl_Wilhelm_Scheele"),
                          (R + "Carbon", R + "Antimony"),
                          (R + "Plato", R + "Gorgias"),
                          (R + "Silicon", R + "J%C3%B6ns_Jacob_Berzelius"),
                          (R + "Adam_Smith", R + "The_Wealth_of_Nations")):
        result = detect_answer_leakage(answer, other, quality_policy)
        assert result.hard_leak is False, (answer, other, result.matches)


def test_36_chemical_roman_numerals_and_parentheses_are_preserved():
    assert display_label(R + "Iron(III)_chloride") == "Iron(III) chloride"
    assert display_label(R + "Iron(II)_chloride") == "Iron(II) chloride"
    assert display_label(R + "Phosphorus(V)_oxide") == "Phosphorus(V) oxide"
    assert display_label(R + "Vitamin_B12_(cobalamin)") == "Vitamin B12 (cobalamin)"
    assert display_label(R + "Makoto_Kobayashi_(physicist)") == (
        "Makoto Kobayashi (physicist)")
    assert display_label(R + "Kant%C5%8D_region") == "Kantō region"
    # INV-2: two chemically distinct entities never collapse to one label.
    assert display_label(R + "Iron(II)_chloride") != display_label(
        R + "Iron(III)_chloride")


def test_37_unknown_predicate_cannot_silently_beat_a_template_ready_rationale(
        quality_policy):
    unknown = assess_fact_quality(
        answer_uri=R + "Answer", predicate_uri=P + "chassis",
        direction=DIRECTION_OUT, counterpart_uri=R + "Frame",
        policy=quality_policy)
    known = assess_fact_quality(
        answer_uri=R + "Answer", predicate_uri=P + "almaMater",
        direction=DIRECTION_OUT, counterpart_uri=R + "Kobe_University",
        policy=quality_policy)
    assert unknown.template_id == TEMPLATE_UNKNOWN
    assert unknown.verbalizable is False
    assert known.verbalizable is True
    # Still ELIGIBLE — diagnostics may use it — but never main-corpus material.
    assert unknown.eligible is True


def test_38_in_template_preserves_the_correct_direction(quality_policy):
    out_author = quality_policy.template_for(P + "author", DIRECTION_OUT)
    in_author = quality_policy.template_for(P + "author", DIRECTION_IN)
    assert out_author is None, "no OUT reading is registered for dbp:author"
    assert in_author is not None
    assert in_author.template_id == "IN_AUTHOR_V1"
    assert "<subject> was written by <answer>" in in_author.reading
    in_influenced = quality_policy.template_for(P + "influenced", DIRECTION_IN)
    out_influenced = quality_policy.template_for(P + "influenced", DIRECTION_OUT)
    assert in_influenced.reading == "<subject> influenced <answer>."
    assert out_influenced.reading == "<answer> influenced <object>."
    assert in_influenced.template_id != out_influenced.template_id


# ==========================================================================
# GROUP E — SCALABILITY  (§16 items 39-45)
# ==========================================================================

def _big_table(n: int, *, facts_per_answer: int = 4):
    answer_facts = [fact(P + "knownFor", DIRECTION_OUT, R + f"Idea{i}")
                    for i in range(facts_per_answer)]
    candidates = {}
    for i in range(n):
        # Every third candidate shares Idea0, so coverage is not uniform.
        own = [fact(P + "knownFor", DIRECTION_OUT, R + f"Other{i}")]
        if i % 3 == 0:
            own.append(fact(P + "knownFor", DIRECTION_OUT, R + "Idea0"))
        candidates[f"{R}Cand{i:04d}"] = own
    return build_evidence_table(
        answer_input(answer_facts, candidates, n=n), semantic_index=
        synthetic_index(), rulebook=empty_rulebook(),
        quality_policy=load_quality_policy(POLICY_DIR / "predicate_policy.json"))


def test_39_full_exact_mode_below_the_threshold():
    table = _big_table(40)
    pool = build_candidate_pool(table, k=3, policy=PoolPolicy())
    assert pool.scope == SEARCH_FULL_EXACT
    assert pool.original_combination_count == 9880
    assert pool.enumerated_combination_count == 9880
    assert pool.global_optimality_claim is True
    assert len(pool.positions) == 40


def test_40_pool_exact_mode_above_the_threshold():
    table = _big_table(200)
    pool = build_candidate_pool(table, k=3, policy=PoolPolicy(
        max_exact_combinations=1000))
    assert pool.scope == SEARCH_POOL_EXACT
    assert pool.original_combination_count == 1313400
    assert pool.enumerated_combination_count < pool.original_combination_count
    assert pool.global_optimality_claim is False
    assert pool.pool_optimality_claim is True


def test_41_thousand_candidates_never_enumerate_every_triple():
    table = _big_table(1000)
    pool = build_candidate_pool(table, k=3, policy=PoolPolicy())
    assert pool.original_candidate_count == 1000
    assert pool.original_combination_count == 166_167_000
    assert pool.scope == SEARCH_POOL_EXACT
    assert len(pool.positions) <= 100
    assert pool.enumerated_combination_count <= 161_700
    search = search_combinations(table, policy=POLICY_DIAGNOSTIC_L0, k=3,
                                 pool=pool)
    enumerated = len(search.full_coverage_outcomes)
    assert enumerated <= pool.enumerated_combination_count
    assert pool.enumerated_combination_count < pool.original_combination_count / 1000


def test_42_pool_size_never_exceeds_the_configured_maximum():
    table = _big_table(500)
    for size in (25, 50, 75, 100):
        policy = PoolPolicy.for_pool_size(size)
        pool = build_candidate_pool(table, k=3, policy=policy, force_pool=True)
        assert len(pool.positions) <= size
        assert policy.top_by_score + policy.evidence_rescue <= size


def test_43_evidence_rescue_candidates_can_enter_below_the_cutoff():
    """A low-ranked candidate with strong evidence must be able to join the pool."""
    answer_facts = [fact(P + "birthPlace", DIRECTION_OUT, R + "Tokyo")]
    candidates = {}
    for i in range(60):
        # High-ranked candidates SHARE the Answer's object (no evidence at all);
        # the last one has a different object and an active single-valued rule.
        obj = R + "Tokyo" if i < 59 else R + "Kyoto"
        candidates[f"{R}Cand{i:04d}"] = [
            fact(P + "birthPlace", DIRECTION_OUT, obj)]
    table = build_evidence_table(
        answer_input(answer_facts, candidates, n=60),
        semantic_index=synthetic_index(),
        rulebook=empty_rulebook(rules=[single_valued_rule()]),
        quality_policy=load_quality_policy(POLICY_DIR / "predicate_policy.json"))
    policy = PoolPolicy(max_exact_combinations=10, top_by_score=20,
                        evidence_rescue=5, max_pool_size=25)
    pool = build_candidate_pool(table, k=3, policy=policy)
    assert pool.scope == SEARCH_POOL_EXACT
    assert 59 in pool.positions, "the only evidence-bearing candidate was dropped"
    assert 59 in pool.rescued_positions


def test_44_pilot_full_exact_result_is_reproducible(v3_run):
    for selection in v3_run.ready_selections:
        assert selection.pool.scope == SEARCH_FULL_EXACT
        assert selection.pool.global_optimality_claim is True
        assert (selection.pool.enumerated_combination_count
                == selection.pool.original_combination_count)


def test_45_pool_size_ablation_is_deterministic(v3_outputs):
    rows = list(csv.DictReader(
        (v3_outputs / "candidate_pool_ablation_v3.csv").open(encoding="utf-8")))
    assert rows, "the ablation produced no rows"
    sizes = sorted({int(r["pool_size"]) for r in rows})
    assert sizes == [25, 50, 75, 100]
    for row in rows:
        assert row["search_scope"] == SEARCH_POOL_EXACT
        assert int(row["pool_candidate_count"]) <= int(row["pool_size"])
        assert row["reference_is_full_exact"] == "true"
    # Determinism: a second identical ablation over the same frozen inputs must
    # produce the same rows. Re-derived here from the packaged file's own copy.
    again = list(csv.DictReader(
        (v3_outputs / "candidate_pool_ablation_v3.csv").open(encoding="utf-8")))
    assert again == rows


# ==========================================================================
# GROUP F — BOUNDARIES AND REGRESSION  (§16 items 46-53)
# ==========================================================================

def test_46_fallback_is_requested_but_never_executed(v3_run, v3_outputs):
    """The request carries everything the next stage needs, and nothing ran.

    "No fallback class was executed" is asserted from the ARTEFACTS rather than
    from sys.modules: a shared pytest session imports other suites' dependencies
    into the same process, so a process-wide module check here would be testing
    the session and not this code path. test_49 makes that check in a standalone
    process, which is the only place it means anything.
    """
    records = [json.loads(l) for l in
               (v3_outputs / "fallback_class_requests_v3.jsonl")
               .read_text(encoding="utf-8").splitlines()]
    assert records, "the pilot must emit at least one fallback request"
    frozen = {h["answer_uri"]: h for h in v3_run.inputs.handoffs}
    for record in records:
        assert record["failure_reason"].startswith("FALLBACK_CLASS_REQUIRED_")
        assert record["fallback_class_executed_in_this_task"] is False
        assert record["failed_selected_class_uri"]
        assert record["current_graph_fingerprint"]
        assert record["requested_next_stage"]
        # The failed class and the candidate count are the FROZEN Prompt-8D
        # ones: nothing selected a new class, retrieved members, built a graph
        # or ranked anything.
        handoff = frozen[record["answer_uri"]]
        assert record["failed_selected_class_uri"] == handoff["selected_class_uri"]
        assert record["candidate_count"] == handoff["ranked_candidate_count"]
        assert record["current_graph_fingerprint"] == handoff["graph_fingerprint"]
    assert {r["failure_reason"] for r in records} == {FALLBACK_L0_ONLY}
    # And every ready Answer still searched exactly its frozen candidate roster.
    for selection in v3_run.ready_selections:
        handoff = frozen[selection.answer_uri]
        assert (selection.table.candidate_count
                == handoff["ranked_candidate_count"])


def test_47_bipartite_fact_candidates_emitted_without_selecting_a_graph(v3_outputs):
    lines = (v3_outputs / "bipartite_fact_candidates.jsonl").read_text(
        encoding="utf-8").splitlines()
    assert lines
    shared = 0
    for line in lines:
        record = json.loads(line)
        assert record["final_bipartite_subset_selected"] is False
        assert 0 <= record["incidence_mask_abcd"] <= 0b1111
        assert record["left_side_degree"] == bin(
            record["incidence_mask_abcd"]).count("1")
        assert len(record["distractor_uris"]) == 3
        assert record["shared_by_at_least_two_choices"] == (
            record["left_side_degree"] >= 2)
        shared += int(record["shared_by_at_least_two_choices"])
    assert shared > 0, "no supplementary (shared) fact candidate was identified"


def test_48_zero_network_attempts(v3_run):
    assert v3_run.guard_record["network_attempts"] == 0
    assert v3_run.guard_record["http_calls"] == 0
    assert v3_run.guard_record["sparql_calls"] == 0
    assert v3_run.guard_record["attempted_addresses"] == []


def test_49_no_forbidden_imports_on_the_v3_path():
    """A STANDALONE process: a shared pytest session imports other suites' deps."""
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "from pipeline import rationale_v3_run as r\n"
        "run = r.run_rationale_v3(verbose=False, run_pool_ablation=False)\n"
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


def test_50_prompt8e_tests_still_pass():
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q",
         "tests/test_rationale_selection.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=3600)
    assert completed.returncode == 0, completed.stdout[-4000:]


def test_51_prompt8e_scientific_outputs_are_byte_identical_under_replay(tmp_path):
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


def test_52_v3_scientific_outputs_are_byte_identical_across_two_runs(tmp_path):
    first = tmp_path / "v3_a"
    second = tmp_path / "v3_b"
    for target in (first, second):
        completed = subprocess.run(
            [sys.executable, "src/extract_and_select_distractors_v3.py",
             "--mode", "pilot-rationale-v3", "--output-dir", str(target),
             "--quiet"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=3600)
        assert completed.returncode == 0, completed.stderr[-3000:]
    for name in runner.REPLAY_COMPARED_FILES:
        assert (first / name).read_bytes() == (second / name).read_bytes(), (
            f"V3 output {name} is not reproducible")


def test_53_protected_source_hashes_are_unchanged():
    observed = runner.verify_protected_sources()
    assert len(observed) == 17
    for name, record in observed.items():
        assert record["unmodified"] is True, name
        assert record["observed_sha256"] == record["expected_sha256"], name


# ==========================================================================
# GROUP G — STRUCTURAL CHECKS ON THE PILOT RUN
# ==========================================================================

def test_54_summary_has_exactly_nine_primary_rows_with_sulfuric_acid_not_ready(
        v3_outputs):
    rows = list(csv.DictReader(
        (v3_outputs / "rationale_v3_summary.csv").open(encoding="utf-8")))
    assert len(rows) == 9
    assert all(row["primary_or_diagnostic"] == "primary" for row in rows)
    sulfuric = next(r for r in rows
                    if r["answer_uri"].endswith("/Sulfuric_acid"))
    assert sulfuric["selection_status"] == "PRIMARY_NOT_READY"
    assert sulfuric["ready_for_rationale_selection"] == "false"
    assert sulfuric["eligible_for_main_corpus"] == "false"


def test_55_automatic_generation_fields_replace_human_validation(v3_outputs):
    rows = list(csv.DictReader(
        (v3_outputs / "rationale_v3_summary.csv").open(encoding="utf-8")))
    for row in rows:
        assert row["generation_is_automatic"] == "true"
        assert row["manual_intervention_used"] == "false"
        assert row["post_generation_human_evaluation_status"] == "NOT_STARTED"
        assert row["publishable_final"] == "false"
    for line in (v3_outputs / "algorithm_selected_distractors_v3.jsonl").read_text(
            "utf-8").splitlines():
        record = json.loads(line)
        assert record["generation_is_automatic"] is True
        assert record["manual_intervention_used"] is False
        assert record["publishable_final"] is False
        assert "requires_human_validation" not in record


def test_56_l0_only_results_are_never_main_corpus_eligible(v3_run):
    for selection in v3_run.selections:
        if selection.evidence_policy == POLICY_DIAGNOSTIC_L0:
            assert selection.eligible_for_main_corpus is False
            assert selection.eligible_for_diagnostic_corpus is True
            assert selection.fallback_status == FALLBACK_L0_ONLY


def test_57_no_forbidden_claim_language_in_any_output(v3_outputs):
    for name in (*runner.REPLAY_COMPARED_FILES, "run_manifest.json",
                 "offline_replay_manifest.json"):
        assert_no_negative_claim((v3_outputs / name).read_text("utf-8"),
                                 where=name)
    text = (v3_outputs / "run_manifest.json").read_text("utf-8")
    for phrase in FORBIDDEN_NEGATIVE_CLAIM_PHRASES:
        assert phrase not in text.lower()


def test_58_eisaku_sato_no_longer_uses_dbp_url(v3_outputs):
    """The concrete §19 item 11 check."""
    rows = {r["answer_uri"]: r for r in csv.DictReader(
        (v3_outputs / "prompt8e_comparison.csv").open(encoding="utf-8"))}
    sato = rows[R + "Eisaku_Satō"]
    assert sato["prompt8e_rationale_predicate"] == P + "url"
    assert sato["v3_rationale_predicate"] != P + "url"
    assert sato["v3_rejected_the_prompt8e_rationale"] == "true"
    reasons = set(sato["v3_rejection_reasons"].split("|"))
    assert "PREDICATE_EXTERNAL_URL_FIELD" in reasons
    assert "OBJECT_WEB_ARCHIVE_URL" in reasons


def test_59_carbon_no_longer_uses_carbonado(v3_outputs):
    """The concrete §19 item 12 check."""
    rows = {r["answer_uri"]: r for r in csv.DictReader(
        (v3_outputs / "prompt8e_comparison.csv").open(encoding="utf-8"))}
    carbon = rows[R + "Carbon"]
    assert carbon["prompt8e_rationale_counterpart"] == R + "Carbonado"
    assert carbon["v3_rationale_counterpart"] != R + "Carbonado"
    assert carbon["v3_rejected_the_prompt8e_rationale"] == "true"
    assert carbon["v3_rejection_reasons"] == "ANSWER_LEXICAL_LEAK"


def test_60_derived_rules_publish_support_and_activation(v3_outputs):
    rows = list(csv.DictReader(
        (v3_outputs / "empirical_rule_candidates_v3.csv").open(encoding="utf-8")))
    assert rows
    for row in rows:
        assert row["rule_type"] == RULE_TYPE_EMPIRICAL_SINGLE_VALUED
        assert row["activation_status"] in (
            RULE_ACTIVE, RULE_PROPOSED_NOT_ACTIVE, "INACTIVE")
        if row["activation_status"] == RULE_ACTIVE:
            assert int(row["observed_violation_count"]) == 0
            assert int(row["maximum_observed_cardinality"]) == 1
            assert int(row["observed_support"]) >= int(row["minimum_support"])
            assert row["direction"] == DIRECTION_OUT
            assert row["empirical_label"] == "EMPIRICAL_AND_SCOPED_NOT_UNIVERSAL"
        else:
            assert row["inactive_reason"]
    thresholds = sorted({int(r["minimum_support"]) for r in rows})
    assert thresholds == [3, 5, 8, 10]


def test_61_derivation_rejects_multi_valued_and_in_direction_keys():
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


def test_62_entrypoint_mode_is_mandatory_and_unknown_modes_are_refused():
    import extract_and_select_distractors_v3 as entry
    with pytest.raises(SystemExit):
        entry.build_arg_parser().parse_args([])
    with pytest.raises(SystemExit):
        entry.build_arg_parser().parse_args(["--mode", "legacy-overlap"])
    assert entry.MODES == ("pilot-rationale-v3", "build-semantic-index")
    # The entrypoint owns no rationale mathematics.
    source = (SRC_DIR / "extract_and_select_distractors_v3.py").read_text("utf-8")
    for banned in ("def exact_minimum_rationale", "def cover_size_table",
                   "def classify_fact_against_candidate", "itertools",
                   "def _mask_class_census", "coverage_mask"):
        assert banned not in source, banned
    assert entry.DEFAULT_PROMPT8D_DIR == str(runner.FROZEN_PROMPT8D_DIR)
    assert entry.DEFAULT_SEMANTIC_INDEX_CACHE == str(
        runner.DEFAULT_SEMANTIC_INDEX_CACHE)


def test_63_semantic_index_cache_key_is_verified(real_semantic_policy, tmp_path):
    stale = SemanticIndexCacheKey(
        pinned_kg_sha256="0" * 64, policy_sha256="0" * 64,
        source_object_list_sha256="0" * 64, max_depth=1,
        creation_command="test")
    index = load_semantic_index_cache(SEMANTIC_CACHE,
                                      policy=real_semantic_policy,
                                      expected_key=stale)
    assert index.available is False
    assert "different inputs" in index.unavailable_reason
    missing = load_semantic_index_cache(tmp_path / "absent.json",
                                        policy=real_semantic_policy,
                                        expected_key=stale)
    assert missing.available is False


def test_64_prompt8e_v3_reason_code_mapping_is_total():
    from rationale_v3.contracts import (
        L0_REASON_CODES, L1_REASON_CODES, L2_REASON_CODES,
        NOT_COVERED_REASON_CODES, PROMPT8E_STATUS_FOR_REASON_CODE)
    every = (NOT_COVERED_REASON_CODES + L0_REASON_CODES + L1_REASON_CODES
             + L2_REASON_CODES)
    assert set(PROMPT8E_STATUS_FOR_REASON_CODE) == set(every)


def test_65_enumeration_reports_completeness():
    facts = coverage_facts([(0b011, 0, "a"), (0b100, 0, "b"),
                            (0b110, 0, "c"), (0b001, 0, "d")])
    full = enumerate_minimum_rationales(facts, k=3, size=2, target_mask=0b111)
    assert full.complete is True
    # {a,b}, {a,c} and {c,d} all OR to 0b111; {b,d} reaches only 0b101.
    assert full.total_count == len(full.enumerated) == 3
    assert all(len(choice) == 2 for choice in full.enumerated)
    for choice in full.enumerated:
        union = 0
        for item in choice:
            union |= item.coverage_mask
        assert union == 0b111
    bounded = enumerate_minimum_rationales(facts, k=3, size=2,
                                           target_mask=0b111, limit=1)
    assert bounded.complete is False
    assert bounded.total_count == 3
    assert len(bounded.enumerated) == 1


# ==========================================================================
# SESSION FIXTURES THAT RUN THE PILOT ONCE
# ==========================================================================

@pytest.fixture(scope="session")
def v3_run():
    """The V3 pilot run, executed once for the whole session."""
    return runner.run_rationale_v3(verbose=False)


@pytest.fixture(scope="session")
def v3_outputs(v3_run, tmp_path_factory):
    out = tmp_path_factory.mktemp("v3_outputs")
    return runner.write_all_outputs(v3_run, out, ("pytest",))
