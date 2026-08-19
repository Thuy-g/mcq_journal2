############################################################################
# tests/test_b2ef_quality_semantic_v3.py
#
# Offline, deterministic tests for every rule Prompt 8H-B2-E / B2-F adds.
#
# NO NETWORK, NO PINNED-KG LOAD, NO MODEL. Every semantic index in this module
# is built from a handful of explicit fixture edges, and every local-KG
# behaviour is exercised against a tiny fake graph with the same five-mapping
# shape `kg.loader.LocalKG` exposes. That is deliberate: a test that needed the
# 1.2 GB pickle would be skipped in CI, and a skipped test proves nothing.
############################################################################

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import mcq_core                                                   # noqa: E402
from classes import class_leakage as cl                           # noqa: E402
from classes.candidate_validity import (                          # noqa: E402
    DEFAULT_CANDIDATE_VALIDITY_POLICY,
    PERSON_STRICT_CANDIDATE_VALIDITY_POLICY,
    REJECT_ANSWER_NAME_CONTAINED,
    REJECT_TYPE_NOT_PERSON,
    REJECT_TYPE_UNKNOWN,
    TYPE_NOT_PERSON,
    TYPE_PERSON,
    TYPE_UNKNOWN,
    answer_name_containment,
    classify_entity_type,
    screen_candidate,
)
from pipeline import phase_b2_any_answer_run_v3 as v3             # noqa: E402
from rationale_v3.contracts import (                              # noqa: E402
    GRANULARITY_RISK_HIERARCHY_UNMODELLED,
    GRANULARITY_RISK_NONE,
    GRANULARITY_RISK_PRESENT,
    LEVEL_L0,
    LEVEL_L1,
    LEVEL_NOT_COVERED,
    NOT_COVERED_SCOPED_VALUE_EQUIVALENT,
    RELATION_CANDIDATE_UNDER_CLAIM,
    RELATION_CLAIM_UNDER_CANDIDATE,
    RELATION_HIERARCHY_NOT_MODELLED,
    RELATION_SCOPED_VALUE_EQUIVALENT,
    RELATION_UNRELATED_OR_UNKNOWN,
    RationaleProposition,
)
from rationale_v3.evidence import (                               # noqa: E402
    classify_fact_against_candidate,
    load_evidence_rules,
)
from rationale_v3.quality import load_quality_policy              # noqa: E402
from rationale_v3.semantic_relations import (                     # noqa: E402
    AncestorEdge,
    build_semantic_index,
    load_semantic_relation_policy,
)

R = "http://dbpedia.org/resource/"
P = "http://dbpedia.org/property/"
POLICIES = SRC / "rationale_v3" / "policies"
FIELD_KEY = (P + "field", "OUT")
NATIONALITY_KEY = (P + "nationality", "OUT")
BIRTHPLACE_KEY = (P + "birthPlace", "OUT")


@pytest.fixture(scope="module")
def quality_v1():
    return load_quality_policy(POLICIES / "predicate_policy.json")


@pytest.fixture(scope="module")
def quality_v2():
    return load_quality_policy(POLICIES / "predicate_policy_v2.json")


@pytest.fixture(scope="module")
def semantic_v1():
    return load_semantic_relation_policy(POLICIES / "semantic_relation_policy.json")


@pytest.fixture(scope="module")
def semantic_v2():
    return load_semantic_relation_policy(
        POLICIES / "semantic_relation_policy_v2.json")


@pytest.fixture()
def index_v2(semantic_v2):
    """A tiny index carrying ONE edge of each new relation kind, plus a place."""
    edges = [
        AncestorEdge(R + "Oncology", R + "Medicine", "FIELD_ACTIVITY_SECTOR_V1",
                     P + "activitySector", "PROFESSIONAL_FIELD_HIERARCHY"),
        AncestorEdge(R + "Germany", R + "Germans", "NATIONALITY_DEMONYM_V1",
                     P + "demonym", "NATIONALITY_VALUE_EQUIVALENCE"),
        AncestorEdge(R + "Shibuya", R + "Tokyo", "PLACE_CONTAINMENT_CITY_V1",
                     P + "city", "ADMINISTRATIVE_PLACE_CONTAINMENT"),
    ]
    return build_semantic_index(policy=semantic_v2, parent_edges=edges)


@pytest.fixture(scope="module")
def rulebook():
    from pipeline.rationale_v3_run import EVIDENCE_RULES_PATH
    return load_evidence_rules(EVIDENCE_RULES_PATH)


# ==========================================================================
# 1) §5 — field semantic hierarchy, directionality, and the coverage state
# ==========================================================================


def test_candidate_object_under_claim_object_is_not_covered(index_v2):
    """Answer claims the BROAD field; the candidate holds a SUB-field.

    The candidate supports the broader proposition, so the fact discriminates
    nothing and must be NOT_COVERED — never L1.
    """
    relation = index_v2.classify(R + "Medicine", R + "Oncology", FIELD_KEY)
    assert relation.relation == RELATION_CANDIDATE_UNDER_CLAIM
    assert relation.depth == 1
    assert relation.path_rule_ids == ("FIELD_ACTIVITY_SECTOR_V1",)


def test_claim_object_under_candidate_object_is_a_granularity_risk(index_v2):
    """Answer claims the SUB-field; the candidate holds only the broad one.

    The raw positive contrast is retained — the observation really is different
    — but the pair is marked CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT so it is not
    main-corpus-safe.
    """
    relation = index_v2.classify(R + "Oncology", R + "Medicine", FIELD_KEY)
    assert relation.relation == RELATION_CLAIM_UNDER_CANDIDATE


def test_the_two_field_directions_are_not_symmetric(index_v2):
    forward = index_v2.classify(R + "Medicine", R + "Oncology", FIELD_KEY)
    backward = index_v2.classify(R + "Oncology", R + "Medicine", FIELD_KEY)
    assert forward.relation != backward.relation


def test_an_unmodelled_field_pair_is_reported_not_called_unrelated(index_v2):
    """The Otto Hahn / Richard Kuhn repair, stated as a property.

    Neither Radiochemistry nor Chemistry takes part in any edge of the field
    domain in the pinned snapshot, so 'no path' carries no information and the
    pair must NOT come back as a clean UNRELATED_OR_UNKNOWN.
    """
    relation = index_v2.classify(R + "Radiochemistry", R + "Chemistry", FIELD_KEY)
    assert relation.relation == RELATION_HIERARCHY_NOT_MODELLED
    assert relation.unmodelled_domain_ids == ("PROFESSIONAL_FIELD_HIERARCHY_V1",)


def test_the_coverage_report_needs_only_one_unmodelled_object(index_v2):
    relation = index_v2.classify(R + "Medicine", R + "Chemistry", FIELD_KEY)
    assert relation.relation == RELATION_HIERARCHY_NOT_MODELLED


def test_a_predicate_the_field_domain_does_not_govern_is_untouched(index_v2):
    """Scope is the whole safety argument: the flag may not leak to other keys."""
    relation = index_v2.classify(R + "Radiochemistry", R + "Chemistry",
                                 BIRTHPLACE_KEY)
    assert relation.relation == RELATION_UNRELATED_OR_UNKNOWN
    assert relation.unmodelled_domain_ids == ()


def test_a_caller_that_passes_no_key_gets_the_v1_answer(index_v2):
    relation = index_v2.classify(R + "Radiochemistry", R + "Chemistry")
    assert relation.relation == RELATION_UNRELATED_OR_UNKNOWN


def test_the_v1_policy_still_classifies_exactly_as_before(semantic_v1):
    index = build_semantic_index(policy=semantic_v1, parent_edges=[
        AncestorEdge(R + "Shibuya", R + "Tokyo", "PLACE_CONTAINMENT_CITY_V1",
                     P + "city", "ADMINISTRATIVE_PLACE_CONTAINMENT")])
    assert index.classify(R + "Tokyo", R + "Shibuya", FIELD_KEY).relation == (
        RELATION_CANDIDATE_UNDER_CLAIM)
    assert index.classify(R + "Chemistry", R + "Radiochemistry",
                          FIELD_KEY).relation == RELATION_UNRELATED_OR_UNKNOWN


def test_the_place_domain_is_still_global_and_still_silent(index_v2):
    """v1 place behaviour is preserved under v2 for every predicate key."""
    assert index_v2.classify(R + "Tokyo", R + "Shibuya",
                             BIRTHPLACE_KEY).relation == (
        RELATION_CANDIDATE_UNDER_CLAIM)
    assert index_v2.classify(R + "Osaka", R + "Kyoto",
                             BIRTHPLACE_KEY).relation == (
        RELATION_UNRELATED_OR_UNKNOWN)


# ==========================================================================
# 2) §5 — the level is never moved, and L1 is never relabelled L0
# ==========================================================================


def _classify(claim, objects, index, rulebook, predicate=P + "field"):
    return classify_fact_against_candidate(
        proposition=RationaleProposition(
            predicate_uri=predicate, direction="OUT",
            source_object_uri=claim, claim_object_uri=claim),
        candidate_uri=R + "SomeCandidate", candidate_objects=objects,
        semantic_index=index, rulebook=rulebook, scope="test-scope")


def test_an_unmodelled_hierarchy_never_relabels_l1_as_l0(index_v2, rulebook):
    """The single most important invariant of the whole §5 repair."""
    evidence = _classify(R + "Radiochemistry", [R + "Chemistry"], index_v2,
                         rulebook)
    assert evidence.level == LEVEL_L1
    assert evidence.granularity_risk_status == GRANULARITY_RISK_HIERARCHY_UNMODELLED


def test_an_unmodelled_hierarchy_never_manufactures_l1_from_absence(
        index_v2, rulebook):
    evidence = _classify(R + "Radiochemistry", [], index_v2, rulebook)
    assert evidence.level == LEVEL_L0
    assert evidence.granularity_risk_status == GRANULARITY_RISK_NONE


def test_a_candidate_subfield_makes_the_fact_not_covered(index_v2, rulebook):
    evidence = _classify(R + "Medicine", [R + "Oncology"], index_v2, rulebook)
    assert evidence.level == LEVEL_NOT_COVERED


def test_a_broader_candidate_object_is_l1_with_a_granularity_risk(
        index_v2, rulebook):
    evidence = _classify(R + "Oncology", [R + "Medicine"], index_v2, rulebook)
    assert evidence.level == LEVEL_L1
    assert evidence.granularity_risk_status == GRANULARITY_RISK_PRESENT


def test_a_governed_key_with_a_modelled_pair_keeps_risk_none(index_v2, rulebook):
    """Both objects take part in the domain, so 'no path' IS informative."""
    index = build_semantic_index(policy=index_v2.policy, parent_edges=[
        AncestorEdge(R + "Oncology", R + "Medicine", "FIELD_ACTIVITY_SECTOR_V1",
                     P + "activitySector", "PROFESSIONAL_FIELD_HIERARCHY"),
        AncestorEdge(R + "Cardiology", R + "Surgery", "FIELD_ACTIVITY_SECTOR_V1",
                     P + "activitySector", "PROFESSIONAL_FIELD_HIERARCHY")])
    evidence = _classify(R + "Oncology", [R + "Cardiology"], index, rulebook)
    assert evidence.level == LEVEL_L1
    assert evidence.granularity_risk_status == GRANULARITY_RISK_NONE


# ==========================================================================
# 3) §6 — nationality value equivalence, and what it must NOT use
# ==========================================================================


def test_demonym_makes_a_country_and_its_people_not_covered(index_v2, rulebook):
    evidence = _classify(R + "Germans", [R + "Germany"], index_v2, rulebook,
                         predicate=P + "nationality")
    assert evidence.level == LEVEL_NOT_COVERED
    assert evidence.reason_code == NOT_COVERED_SCOPED_VALUE_EQUIVALENT


def test_the_nationality_equivalence_is_symmetric(index_v2):
    forward = index_v2.classify(R + "Germans", R + "Germany", NATIONALITY_KEY)
    backward = index_v2.classify(R + "Germany", R + "Germans", NATIONALITY_KEY)
    assert forward.relation == backward.relation == RELATION_SCOPED_VALUE_EQUIVALENT


def test_the_nationality_equivalence_is_not_a_global_entity_identity(index_v2):
    """Under birthPlace, Germany and Germans are NOT interchangeable."""
    relation = index_v2.classify(R + "Germans", R + "Germany", BIRTHPLACE_KEY)
    assert relation.relation != RELATION_SCOPED_VALUE_EQUIVALENT


def test_an_unrepairable_nationality_mismatch_is_reported_not_hidden(index_v2):
    """France carries no dbp:demonym edge in the pinned snapshot, so the
    Rouelle pair cannot be repaired — and must not look clean either."""
    relation = index_v2.classify(R + "French_people", R + "France",
                                 NATIONALITY_KEY)
    assert relation.relation == RELATION_HIERARCHY_NOT_MODELLED


def test_no_wiki_link_predicate_is_admitted_anywhere(semantic_v2):
    """wikiPageWikiLink / wikiPageDisambiguates prove neither identity nor
    subsumption and must never appear as a traversal rule."""
    admitted = set(semantic_v2.allowlisted_predicates)
    for banned in ("wikiPageWikiLink", "wikiPageDisambiguates",
                   "wikiPageRedirects"):
        assert not any(banned in predicate for predicate in admitted), banned


def test_region_stays_excluded_with_its_reason(semantic_v2):
    assert P + "region" in semantic_v2.excluded_predicates


# ==========================================================================
# 4) §7 — the candidate TYPE gate
# ==========================================================================


PERSON_KEYS = {(P + "birthPlace", "OUT"), (P + "spouse", "OUT")}
WORK_KEYS = {(P + "author", "OUT"), (P + "publisher", "OUT")}


def test_a_biography_slot_profile_is_a_person():
    verdict = classify_entity_type(R + "Somebody", PERSON_KEYS)
    assert verdict.entity_type == TYPE_PERSON
    assert verdict.person_evidence_keys


def test_a_work_slot_profile_is_not_a_person():
    assert classify_entity_type(R + "SomeBook", WORK_KEYS).entity_type == (
        TYPE_NOT_PERSON)


def test_an_entity_with_no_urivalued_slot_is_unknown_not_person():
    """`Mass_line` and `Laogai` fill nothing; UNKNOWN is not PERSON."""
    assert classify_entity_type(R + "Mass_line", set()).entity_type == TYPE_UNKNOWN


def test_person_evidence_outranks_a_work_slot_on_the_same_article():
    verdict = classify_entity_type(R + "Somebody", PERSON_KEYS | WORK_KEYS)
    assert verdict.entity_type == TYPE_PERSON
    assert verdict.non_person_evidence_keys


def test_the_type_gate_stands_down_when_the_answer_is_not_reliably_a_person():
    """A gate whose premise is missing must not fire (§7.1)."""
    answer_type = classify_entity_type(R + "Silicon", set())
    verdict = screen_candidate(
        answer_uri=R + "Silicon", candidate_uri=R + "Germanium",
        observed_keys=set(), quality_policy=load_quality_policy(
            POLICIES / "predicate_policy.json"),
        answer_type=answer_type, policy=PERSON_STRICT_CANDIDATE_VALIDITY_POLICY)
    assert verdict.accepted


def test_person_strict_rejects_an_unknown_candidate_and_says_so(quality_v1):
    answer_type = classify_entity_type(R + "Mao_Zedong", PERSON_KEYS)
    verdict = screen_candidate(
        answer_uri=R + "Mao_Zedong", candidate_uri=R + "Mass_line",
        observed_keys=set(), quality_policy=quality_v1,
        answer_type=answer_type, policy=PERSON_STRICT_CANDIDATE_VALIDITY_POLICY)
    assert not verdict.accepted
    assert verdict.reject_reason == REJECT_TYPE_UNKNOWN
    assert verdict.type_verdict.entity_type == TYPE_UNKNOWN


def test_person_strict_rejects_a_typed_non_person(quality_v1):
    answer_type = classify_entity_type(R + "Mao_Zedong", PERSON_KEYS)
    verdict = screen_candidate(
        answer_uri=R + "Mao_Zedong", candidate_uri=R + "Chinese_Shadows",
        observed_keys=WORK_KEYS, quality_policy=quality_v1,
        answer_type=answer_type, policy=PERSON_STRICT_CANDIDATE_VALIDITY_POLICY)
    assert verdict.reject_reason == REJECT_TYPE_NOT_PERSON


def test_the_default_policy_removes_nothing(quality_v1):
    answer_type = classify_entity_type(R + "Mao_Zedong", PERSON_KEYS)
    verdict = screen_candidate(
        answer_uri=R + "Mao_Zedong", candidate_uri=R + "Mass_line",
        observed_keys=set(), quality_policy=quality_v1,
        answer_type=answer_type, policy=DEFAULT_CANDIDATE_VALIDITY_POLICY)
    assert verdict.accepted
    assert verdict.type_verdict.entity_type == TYPE_UNKNOWN


def test_the_pinned_index_type_map_is_documented_as_unusable():
    source = (SRC / "classes" / "candidate_validity.py").read_text("utf-8")
    assert "uniformly 0" in source or "EVERY ONE of them is 0" in source


# ==========================================================================
# 5) §8 — answer-name containment
# ==========================================================================


def test_a_topical_derivative_of_the_answer_is_caught(quality_v1):
    assert answer_name_containment(R + "Muhammad", R + "Muhammad_in_Islam",
                                   quality_v1)


def test_a_shared_family_name_is_not_containment(quality_v1):
    """The §7.7 control: distinct Ashikaga persons must stay eligible."""
    for other in ("Ashikaga_Yoshiakira", "Ashikaga_Yoshimitsu",
                  "Ashikaga_Tadayoshi"):
        assert answer_name_containment(R + "Ashikaga_Takauji", R + other,
                                       quality_v1) is None


def test_an_identical_name_is_not_containment(quality_v1):
    assert answer_name_containment(R + "Muhammad", R + "Muhammad",
                                   quality_v1) is None


def test_the_rule_contains_no_entity_specific_branch():
    source = (SRC / "classes" / "candidate_validity.py").read_text("utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    for name in ("Muhammad", "Ashikaga", "Silicon", "Mao"):
        assert f'"{name}' not in code and f"'{name}" not in code, name


def test_black_silicon_is_flagged_but_never_canonicalized(quality_v1, index_v2):
    """§7.8 / §21: the option name contains the Answer name — and that is ALL
    the rule says. The two entities stay distinct everywhere else."""
    assert answer_name_containment(R + "Silicon", R + "Black_silicon", quality_v1)
    relation = index_v2.classify(R + "Silicon", R + "Black_silicon", FIELD_KEY)
    assert relation.relation != RELATION_SCOPED_VALUE_EQUIVALENT
    assert index_v2.canonical(R + "Black_silicon") != index_v2.canonical(
        R + "Silicon")


def test_person_strict_rejects_the_topical_derivative(quality_v1):
    answer_type = classify_entity_type(R + "Muhammad", PERSON_KEYS)
    verdict = screen_candidate(
        answer_uri=R + "Muhammad", candidate_uri=R + "Muhammad_in_Islam",
        observed_keys=PERSON_KEYS, quality_policy=quality_v1,
        answer_type=answer_type, policy=PERSON_STRICT_CANDIDATE_VALIDITY_POLICY)
    assert not verdict.accepted
    assert verdict.reject_reason == REJECT_ANSWER_NAME_CONTAINED
    # The type gate could not have caught it: it IS person-shaped.
    assert verdict.type_verdict.entity_type == TYPE_PERSON


# ==========================================================================
# 6) §9 — class leakage v2
# ==========================================================================


@pytest.mark.parametrize("answer,klass", [
    ("Fluorine", "Fluorinating_agents"),
    ("Mao_Zedong", "Maoist_China"),
    ("Mao_Zedong", "Maoist_theorists"),
    ("Karl_Marx", "Marxist_theorists"),
    ("Immanuel_Kant", "Kantian_philosophers"),
])
def test_v2_catches_the_eponymic_and_deverbal_class_leaks(answer, klass,
                                                          quality_v1):
    verdict = cl.classify_class_leakage_extended(
        R + answer, R + klass, quality_v1,
        derivational=cl.DERIVATIONAL_POLICY_V2)
    assert verdict.level == cl.LEAK_HARD, verdict.as_record()


@pytest.mark.parametrize("answer,klass", [
    ("Carbon", "Boron_carbide"),
    ("Carbon", "Carbide_minerals"),
    ("Nitrogen", "Nitrites"),
    ("Sulfur", "Sulfites"),
    ("Silicon", "Metalloids"),
    ("Ashikaga_Takauji", "14th-century_Japanese_people"),
    ("Albert_Einstein", "German_relativity_theorists"),
])
def test_v2_leaves_the_false_positive_controls_alone(answer, klass, quality_v1):
    verdict = cl.classify_class_leakage_extended(
        R + answer, R + klass, quality_v1,
        derivational=cl.DERIVATIONAL_POLICY_V2)
    assert verdict.level != cl.LEAK_HARD, verdict.as_record()


def test_the_v1_policy_is_unchanged_by_the_v2_additions(quality_v1):
    """Both new branches are OFF in the default policy."""
    for answer, klass in (("Fluorine", "Fluorinating_agents"),
                          ("Mao_Zedong", "Maoist_China")):
        verdict = cl.classify_class_leakage_extended(R + answer, R + klass,
                                                     quality_v1)
        assert verdict.level != cl.LEAK_HARD


def test_the_global_token_floor_was_not_lowered(quality_v1):
    """§9: the fix must NOT reduce `minimum_token_length` from 4 to 3."""
    assert quality_v1.leakage.minimum_token_length == 4
    assert cl.DERIVATIONAL_POLICY_V2.eponymic_exact_minimum_stem_length == 3


def test_the_v2_suffix_list_still_excludes_chemical_nomenclature():
    for banned in ("ate", "ide", "ine", "ane", "ene", "ol", "yl"):
        assert banned not in cl.DERIVATIONAL_SUFFIXES_V2
        assert banned not in cl.EPONYMIC_EXACT_SUFFIXES


def test_the_eponymic_branch_is_depth_one_and_exact(quality_v1):
    """'artistic' -> 'artist' must never continue to 'art'."""
    assert cl.eponymic_exact_matches(
        R + "Art_Blakey", R + "Artistic_movements", quality_v1,
        derivational=cl.DERIVATIONAL_POLICY_V2) == ()


# ==========================================================================
# 7) §10 — option_reference_conflict
# ==========================================================================


def _tiny_case(counterparts, candidate_uris, levels):
    """A minimal AnswerCase built through the kernel's own constructor."""
    from mcq_core import AnswerFact, Candidate, FactQuality, build_case

    candidates = tuple(Candidate(rank=i + 1, score=1.0 - i / 10, uri=uri)
                       for i, uri in enumerate(candidate_uris))
    facts = tuple(
        AnswerFact(
            quality=FactQuality(
                predicate_uri=P + "successor", direction="OUT",
                counterpart_uri=counterpart, display_label=counterpart,
                eligible=True, soft_leak=False, verbalizable=True,
                pedagogical_tier=2, label_length=10, token_count=1,
                template_id="T"),
            levels=tuple(levels[index]),
            exclusion_bases=("NONE",) * len(candidates),
            granularity_risks=("NONE",) * len(candidates))
        for index, counterpart in enumerate(counterparts))
    return build_case(R + "Augustus", "Augustus", candidates, facts)


def test_a_rationale_that_names_a_printed_option_is_counted():
    case = _tiny_case([R + "Tiberius"], [R + "Tiberius", R + "Trajan",
                                         R + "Domitian"],
                      [["L1", "L1", "L1"]])
    count, evidence = mcq_core.option_reference_conflicts(case, (0, 1, 2), (0,))
    assert count == 1
    assert evidence[0].endswith("Tiberius")


def test_a_rationale_that_names_no_option_is_clean():
    case = _tiny_case([R + "Livia"], [R + "Tiberius", R + "Trajan",
                                      R + "Domitian"],
                      [["L1", "L1", "L1"]])
    assert mcq_core.option_reference_conflicts(case, (0, 1, 2), (0,))[0] == 0


def test_objective_v2_prefers_the_conflict_free_rationale():
    """Two |R*|=1 rationales, identical on every evidence field."""
    case = _tiny_case(
        [R + "Tiberius", R + "Livia"],
        [R + "Tiberius", R + "Trajan", R + "Domitian"],
        [["L1", "L1", "L1"], ["L1", "L1", "L1"]])
    v1 = mcq_core.rank_minimum_rationales(case, (0, 1, 2), "main-l1",
                                          mcq_core.RATIONALE_OBJECTIVE_V1)
    v2 = mcq_core.rank_minimum_rationales(case, (0, 1, 2), "main-l1",
                                          mcq_core.RATIONALE_OBJECTIVE_V2)
    assert v2[2][0].option_reference_conflict_count == 0
    assert v1[0] == v2[0] == 1                      # |R*| is identical
    assert v2[2][0].fact_identities != v1[2][0].fact_identities or (
        v1[2][0].option_reference_conflict_count == 0)


def test_objective_v2_never_grows_the_rationale():
    """Only one |R*|=1 cover exists and it conflicts: it is KEPT and flagged."""
    case = _tiny_case([R + "Tiberius"], [R + "Tiberius", R + "Trajan",
                                         R + "Domitian"],
                      [["L1", "L1", "L1"]])
    size, _, ranked = mcq_core.rank_minimum_rationales(
        case, (0, 1, 2), "main-l1", mcq_core.RATIONALE_OBJECTIVE_V2)
    assert size == 1
    assert ranked[0].option_reference_conflict_count == 1


def test_the_new_field_sits_after_the_complete_evidence_profile():
    """v2's key is v1's first six fields, then the conflict count, then the rest."""
    case = _tiny_case([R + "Tiberius"], [R + "Tiberius", R + "Trajan",
                                         R + "Domitian"],
                      [["L1", "L1", "L1"]])
    rationale = mcq_core.build_rationale(case, (0, 1, 2), (0,), "L1")
    assert rationale.ranking_key_v2[:6] == rationale.ranking_key[:6]
    assert rationale.ranking_key_v2[6] == rationale.option_reference_conflict_count
    assert rationale.ranking_key_v2[7:] == rationale.ranking_key[6:]


def test_the_v1_objective_is_the_default_and_is_unchanged():
    assert mcq_core.DEFAULT_RATIONALE_OBJECTIVE == mcq_core.RATIONALE_OBJECTIVE_V1


# ==========================================================================
# 8) §12 — predicate policy v2, including the case-sensitivity repair
# ==========================================================================


@pytest.mark.parametrize("predicate", [
    "imagecaption", "imageCaption", "captionLeft", "headerimage",
    "signatureType", "blank", "1blankname", "opt2n", "colours", "dipstyle",
])
def test_v2_hard_rejects_every_observed_layout_spelling(predicate, quality_v2):
    from rationale_v3.quality import check_predicate
    accepted, reason = check_predicate(P + predicate, quality_v2)
    assert not accepted, predicate
    assert reason


def test_v1_missed_the_lowercase_spelling(quality_v1):
    from rationale_v3.quality import check_predicate
    assert check_predicate(P + "imageCaption", quality_v1)[0] is False
    assert check_predicate(P + "imagecaption", quality_v1)[0] is True


def test_products_and_industry_are_demoted_by_direction_not_banned(quality_v2):
    from rationale_v3.quality import check_predicate
    for predicate in ("products", "industry"):
        assert check_predicate(P + predicate, quality_v2)[0] is True
        assert quality_v2.tier_for(P + predicate, "IN") == 3


def test_a_direction_aware_tier_beats_the_predicate_only_tier(quality_v2):
    assert quality_v2.tier_for(P + "commander", "IN") == 2
    assert quality_v2.tier_for(P + "commander") == 3        # the default


def test_field_and_fields_stay_at_tier_one(quality_v2):
    for predicate in ("field", "fields"):
        assert quality_v2.tier_for(P + predicate, "OUT") == 1


def test_the_tier_scale_was_not_expanded(quality_v2):
    tiers = set(quality_v2.pedagogical_tier.values())
    tiers |= set(quality_v2.pedagogical_tier_by_key.values())
    tiers.add(quality_v2.pedagogical_tier_default)
    assert tiers <= {1, 2, 3}


def test_every_new_template_declares_its_direction(quality_v2):
    for (predicate, direction), entry in quality_v2.templates.items():
        assert direction in ("OUT", "IN")
        assert entry.reading
        marker = "<object>" if direction == "OUT" else "<subject>"
        assert marker in entry.reading, entry.template_id


def test_the_v1_policy_file_is_preserved_unchanged():
    import hashlib
    digest = hashlib.sha256(
        (POLICIES / "predicate_policy.json").read_bytes()).hexdigest()
    assert digest == (
        "6c07bbe3ab5325a027d89bf28b01e6f20794b9c11f75e09fffdf1d35dfdefa9e")


def test_the_v1_semantic_policy_file_is_preserved_unchanged():
    import hashlib
    digest = hashlib.sha256(
        (POLICIES / "semantic_relation_policy.json").read_bytes()).hexdigest()
    assert digest == (
        "4336b3b003324431ac9b7304d29617d6d83e2a3d3a2c7f79ee0d9ca4d2fa078a")


# ==========================================================================
# 9) §16 — the input line range
# ==========================================================================


@pytest.mark.parametrize("text,expected", [
    ("11-33", (11, 33)),
    (" 1 - 2 ", (1, 2)),
    ("7-7", (7, 7)),
])
def test_a_well_formed_range_parses(text, expected):
    assert v3.parse_line_range(text) == expected


@pytest.mark.parametrize("text", ["", "11", "11-", "-33", "33-11", "0-5",
                                  "a-b", "11..33", "11,33", "-1-5"])
def test_a_malformed_or_inconsistent_range_is_refused(text):
    with pytest.raises(v3.LineRangeError):
        v3.parse_line_range(text)


class _Row:
    def __init__(self, line_number, uri, cohort, valid=True):
        self.line_number = line_number
        self.answer_uri = uri
        self.cohort = cohort
        self.uri_is_valid = valid


class _Parsed:
    def __init__(self, rows):
        self.rows = rows


def test_only_answer_rows_inside_the_range_are_executed():
    parsed = _Parsed([_Row(2, R + "A", "C1"), _Row(5, R + "B", "C1"),
                      _Row(9, R + "C", "C2")])
    assert [uri for _, uri, _ in v3.rows_in_line_range(parsed, (2, 5))] == [
        R + "A", R + "B"]


def test_the_cohort_of_a_selected_line_survives_the_range():
    parsed = _Parsed([_Row(2, R + "A", "C1"), _Row(9, R + "C", "C2")])
    selected = v3.rows_in_line_range(parsed, (9, 9))
    assert selected == [(9, R + "C", "C2")]


def test_an_invalid_uri_row_is_excluded_even_inside_the_range():
    parsed = _Parsed([_Row(3, R + "Bad", "C1", valid=False)])
    assert v3.rows_in_line_range(parsed, (1, 10)) == []


def test_a_duplicate_collapses_to_its_first_occurrence():
    parsed = _Parsed([_Row(2, R + "A", "C1"), _Row(8, R + "A", "C2")])
    assert v3.rows_in_line_range(parsed, (1, 10)) == [(2, R + "A", "C1")]
    assert v3.rows_in_line_range(parsed, (8, 8)) == []


def test_no_range_means_every_runnable_row():
    parsed = _Parsed([_Row(2, R + "A", "C1"), _Row(9, R + "C", "C2")])
    assert len(v3.rows_in_line_range(parsed, None)) == 2


# ==========================================================================
# 10) §17 / §18 — the batch table and the metrics
# ==========================================================================


class _FakeRationale:
    def __init__(self, size, conflicts=0):
        self.fact_indices = ()
        self.per_candidate_best_level = ("L1", "L1", "L1")
        self.local_candidate_pool_anonymity_count = 1
        self.granularity_risk_incidences = 0
        self.option_reference_conflict_count = conflicts
        self.option_reference_conflict = conflicts > 0
        self.direct_identifier_flag = True
        self.scoped_empirical_incidences = 0


class _FakeSelection:
    def __init__(self, size, level="MCQ-L1", conflicts=0):
        self.minimum_rationale_size = size
        self.rationale = _FakeRationale(size, conflicts)
        self.distractors = ()
        self.positions = ()
        self.search_scope = "FULL_EXACT"
        self.mcq_evidence_level = level
        self.rationale_objective = mcq_core.RATIONALE_OBJECTIVE_V2


class _FakeResult:
    def __init__(self, size=None, level=None, status="SUCCESS_FULL_EXACT",
                 cohort=None):
        self.original_uri = R + "X"
        self.cohort = cohort
        self.status = status
        self.identity = None
        self.selected_class_uri = None
        self.complete_pool_size = 10
        self.semantic_index_available = True
        self.case = None
        self.source_line_number = 3
        self.selection = None if size is None else _FakeSelection(size, level)
        self.mcq_evidence_level = level
        self.has_main_l1_selection = level in ("MCQ-L1", "MCQ-L2")
        self.search_scope = None if size is None else "FULL_EXACT"


def test_the_cardinality_is_a_column_and_is_never_truncated():
    table = v3.summary_table_v3([_FakeResult(3, "MCQ-L1")])
    assert "\\|R*\\|" in table
    row = table.splitlines()[2]
    assert "| 3 |" in row


def test_the_cardinality_survives_a_long_rationale_string():
    """The v2 bug, stated as a test: |R*| lived at the END of a truncated cell."""
    v2_style = ("predicate_one -> A_very_long_counterpart_label; "
                "predicate_two -> Another_long_label (|R*|=2)")
    assert "|R*|=2" not in v2_style[:45]           # v2 truncated to 46 chars
    table = v3.summary_table_v3([_FakeResult(2, "MCQ-L1")])
    assert "| 2 |" in table.splitlines()[2]


def test_zero_denominators_print_na_and_never_divide():
    metrics = v3.batch_metrics([_FakeResult(None, None, "GRAPH_INFEASIBLE")])
    assert metrics["scoped_empirical"]["pct_of_l1_questions"] is None
    assert metrics["rationale_cardinality"]["MCQ-L1"]["denominator"] == 0
    markdown = v3.metrics_markdown(metrics)
    assert "N/A" in markdown


def test_an_empty_batch_produces_metrics_rather_than_an_exception():
    metrics = v3.batch_metrics([])
    assert metrics["coverage"]["total_answers_attempted"] == 0
    assert metrics["coverage"]["any_kernel_selection_pct"] is None
    v3.metrics_markdown(metrics)
    v3.metrics_csv_rows(metrics)


def test_the_four_coverage_concepts_are_distinct():
    results = [_FakeResult(1, "MCQ-L1"), _FakeResult(1, "MCQ-L0",
                                                     "NO_MAIN_L1_SELECTION"),
               _FakeResult(None, None, "NO_VALID_FINAL_COMBINATION")]
    metrics = v3.batch_metrics(results)
    coverage = metrics["coverage"]
    assert coverage["any_kernel_selection"] == 2
    assert coverage["student_showable_main_l1_l2"] == 1
    assert coverage["diagnostic_l0_only"] == 1
    assert coverage["no_selection"] == 1
    prose = v3.prose_summary_v3(results, metrics)
    assert "Any kernel selection" in prose
    assert "of which student-showable main L1/L2" in prose
    assert "of which diagnostic L0-only" in prose
    # The misleading v2 label must not appear as a COUNT line; it survives only
    # inside the explanatory note that says why it was abandoned.
    assert not any(line.strip().startswith("Successful")
                   for line in prose.splitlines())


def test_an_l0_only_row_is_never_reported_as_success():
    metrics = v3.batch_metrics([_FakeResult(1, "MCQ-L0",
                                            "NO_MAIN_L1_SELECTION")])
    assert metrics["coverage"]["student_showable_main_l1_l2"] == 0
    assert metrics["coverage"]["any_kernel_selection"] == 1


def test_cohort_stays_metadata_only():
    metrics = v3.batch_metrics([_FakeResult(1, "MCQ-L1", cohort="COHORT_A")])
    assert "COHORT_A" in metrics["cohorts"]
    assert "METADATA ONLY" in metrics["cohorts"]["COHORT_A"]["note"]
    source = (SRC / "pipeline" / "phase_b2_any_answer_run_v3.py").read_text("utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    # The cohort never reaches the candidate screen, which is the one v3 stage
    # that can change what the kernel sees.
    screen = code.split("def screen_candidate_pool")[1].split("\n\n\n")[0]
    assert "cohort" not in screen


# ==========================================================================
# 11) The v2 artefacts must remain intact
# ==========================================================================


def test_the_v2_runner_and_pipeline_module_are_untouched():
    import hashlib
    expected = {
        "scripts/run_phase_b2_any_answer_v2.py":
            "1f8b0f1f36b6e0c3c23427d7db9fc4d53448ee54e6d428ce7577edfd7c278384",
        "src/pipeline/phase_b2_any_answer_run.py":
            "a0f5946f290b6cd2dd7110282e0894aadedbd4f66bdbe2bb46828b856584b3a1",
    }
    for relative, digest in expected.items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert actual == digest, f"{relative} must remain historical evidence"


def test_the_v3_runner_exists_and_declares_every_new_argument():
    text = (ROOT / "scripts" / "run_phase_b2_any_answer_v3.py").read_text("utf-8")
    for argument in ("--answer-uri", "--input", "--alpha", "--allow-network",
                     "--offline-replay", "--output-report", "--artifacts-dir",
                     "--print-facts-only", "--lines-for-input-file",
                     "--member-cache", "--score-cache", "--sparql-cache",
                     "--wikipedia-cache", "--semantic-index-root"):
        assert f'"{argument}"' in text, argument


def test_the_v3_runner_keeps_alpha_at_the_declared_default():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_phase_b2_any_answer_v3.py"),
         "--help"], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0
    assert "0.7" in result.stdout


def test_facts_only_needs_no_network_argument_beyond_the_gate():
    """The mode still requires an explicit --offline-replay / --allow-network."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_phase_b2_any_answer_v3.py"),
         "--answer-uri", R + "Socrates", "--print-facts-only"],
        capture_output=True, text=True, timeout=180)
    assert result.returncode != 0
    assert "exactly one of --allow-network / --offline-replay" in result.stdout


def test_a_line_range_without_input_is_refused():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_phase_b2_any_answer_v3.py"),
         "--answer-uri", R + "Socrates", "--offline-replay",
         "--lines-for-input-file", "1-2"],
        capture_output=True, text=True, timeout=180)
    assert result.returncode != 0
    assert "valid only with --input" in result.stdout


def test_a_malformed_range_is_refused_at_the_cli():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_phase_b2_any_answer_v3.py"),
         "--input", str(ROOT / "data" / "Answers.txt"), "--offline-replay",
         "--lines-for-input-file", "33-11"],
        capture_output=True, text=True, timeout=180)
    assert result.returncode != 0
    assert "START <= END" in result.stdout


# ==========================================================================
# 12) §15 — raw fact grouping against a fake local KG
# ==========================================================================


class _FakeKG:
    """The five mappings `kg.loader.LocalKG` exposes, at toy scale."""

    def __init__(self):
        self.url_index = {
            "<" + R + "A>": 1, "<" + R + "B>": 2, "<" + R + "C>": 3,
            "<" + P + "p>": 10, "<" + P + "q>": 11,
        }
        self.index_url = {v: k for k, v in self.url_index.items()}
        # A literal object: present as an edge, absent from index_url.
        self.out_neighbor = {1: [(10, 2), (11, 3), (10, 999)]}
        self.in_neighbor = {1: [(10, 3)]}
        self.index_type = {1: 0, 2: 0, 3: 0}

    def index_for_uri_or_none(self, uri):
        return self.url_index.get(uri)


def test_raw_fact_groups_separates_in_and_out():
    record = v3.raw_fact_groups(R + "A", local_kg=_FakeKG())
    assert record["resolved"] is True
    assert (P + "p", "OUT") in record["groups"]
    assert (P + "p", "IN") in record["groups"]
    assert record["out_fact_count"] == 2
    assert record["in_fact_count"] == 1


def test_raw_fact_groups_skips_non_uri_valued_edges():
    record = v3.raw_fact_groups(R + "A", local_kg=_FakeKG())
    assert record["skipped_non_uri_edges"] == 1
    assert record["fact_count"] == 3


def test_raw_fact_groups_reports_a_missing_node_rather_than_empty_facts():
    record = v3.raw_fact_groups(R + "Nowhere", local_kg=_FakeKG())
    assert record["resolved"] is False
    assert record["local_index"] is None
    text = "\n".join(v3.render_raw_facts(record))
    assert "NOT A NODE OF THE PINNED LOCAL KG" in text


def test_render_raw_facts_states_what_it_did_not_run():
    record = v3.raw_fact_groups(R + "A", local_kg=_FakeKG())
    text = "\n".join(v3.render_raw_facts(record, local_kg=_FakeKG()))
    for phrase in ("No hard-reject predicate filter", "LRoleSim",
                   "MCQ selection"):
        assert phrase in text


# ==========================================================================
# 13) §10 — objective v3, the placement that repairs Augustus
# ==========================================================================


def test_objective_v3_keeps_the_complete_level_profile_first():
    case = _tiny_case([R + "Tiberius"], [R + "Tiberius", R + "Trajan",
                                         R + "Domitian"],
                      [["L1", "L1", "L1"]])
    rationale = mcq_core.build_rationale(case, (0, 1, 2), (0,), "L1")
    assert rationale.ranking_key_v3[:4] == rationale.ranking_key[:4]


def test_objective_v3_places_the_conflict_above_the_annotation():
    """The Augustus shape: one conflicting cover with a HIGHER annotation count
    against one clean cover with a lower one."""
    case = _tiny_case(
        [R + "Tiberius", R + "Livia"],
        [R + "Tiberius", R + "Trajan", R + "Domitian"],
        [["L1", "L1", "L1"], ["L1", "L1", "L1"]])
    # Make the conflicting fact the only one carrying the annotation.
    from dataclasses import replace
    facts = list(case.facts)
    facts[0] = replace(facts[0],
                       exclusion_bases=("SCOPED_EMPIRICAL",) * 3)
    case = replace(case, facts=tuple(facts))

    conflicting = mcq_core.build_rationale(case, (0, 1, 2), (0,), "L1")
    clean = mcq_core.build_rationale(case, (0, 1, 2), (1,), "L1")
    assert conflicting.option_reference_conflict_count == 1
    assert clean.option_reference_conflict_count == 0
    assert conflicting.scoped_empirical_incidences == 3
    assert clean.scoped_empirical_incidences == 0
    # v2 keeps the conflicting one (the annotation is consulted first);
    # v3 prefers the clean one.
    assert conflicting.ranking_key_v2 < clean.ranking_key_v2
    assert clean.ranking_key_v3 < conflicting.ranking_key_v3


def test_objective_v3_still_cannot_buy_a_weaker_evidence_level():
    case = _tiny_case(
        [R + "Tiberius", R + "Livia"],
        [R + "Tiberius", R + "Trajan", R + "Domitian"],
        [["L1", "L1", "L1"], ["L1", "L1", "L0"]])
    strong = mcq_core.build_rationale(case, (0, 1, 2), (0,), "L1")
    weak = mcq_core.build_rationale(case, (0, 1, 2), (1,), "L1")
    # The conflicting rationale covers every distractor at L1; the clean one
    # leaves distractor 3 at L0, so its weakest distractor is worse.
    assert strong.rationale_min_level == "L1"
    assert weak.rationale_min_level == "L0"
    assert strong.option_reference_conflict_count == 1
    assert weak.option_reference_conflict_count == 0
    # Field 1 is the minimum level and is decided before any conflict count,
    # under EVERY objective. The conflict-free rationale loses.
    for objective in mcq_core.RATIONALE_OBJECTIVES:
        assert strong.ranking_key_for(objective) < weak.ranking_key_for(objective)


def test_every_declared_objective_is_selectable():
    case = _tiny_case([R + "Tiberius"], [R + "Tiberius", R + "Trajan",
                                         R + "Domitian"],
                      [["L1", "L1", "L1"]])
    rationale = mcq_core.build_rationale(case, (0, 1, 2), (0,), "L1")
    for objective in mcq_core.RATIONALE_OBJECTIVES:
        assert isinstance(rationale.ranking_key_for(objective), tuple)
    with pytest.raises(ValueError):
        rationale.ranking_key_for("rationale_objective/not-a-version")
