############################################################################
# tests/test_b2g_final_benchmark_safety_v4.py
#
# Offline, deterministic tests for every generic rule Prompt 8H-B2-G adds.
#
# NO NETWORK, NO PINNED-KG LOAD, NO MODEL. Every case below is built from a
# handful of explicit fixture values or the frozen eight-Answer pilot records
# that already live in `outputs/`. That is deliberate: a test that needed the
# 1.2 GB pickle would be skipped on any machine without it, and a skipped test
# proves nothing.
#
# NO NAMED REGRESSION ANSWER IS HARD-CODED AS A PRODUCTION BRANCH. Muhammad,
# Robert Boyle, Otto Hahn and Augustus appear here only as TEST FIXTURES —
# `grep -i muhammad src/` finds prose, never control flow.
############################################################################

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import mcq_core                                                    # noqa: E402
from classes.candidate_validity import (                           # noqa: E402
    DEFAULT_CANDIDATE_VALIDITY_POLICY,
    PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY,
    PERSON_STRICT_CANDIDATE_VALIDITY_POLICY,
    REJECT_ANSWER_NAME_CONTAINED,
    REJECT_TYPE_NOT_PERSON,
    REJECT_TYPE_UNKNOWN,
    REJECTED_BY_NAME_RULE,
    REJECTED_BY_NOTHING,
    REJECTED_BY_TYPE_RULE,
    TYPE_NOT_PERSON,
    TYPE_PERSON,
    TYPE_POLICIES,
    TYPE_POLICY_OBSERVE_ONLY,
    TYPE_POLICY_PERSON_GUARDED,
    TYPE_POLICY_PERSON_STRICT,
    TYPE_UNKNOWN,
    CandidateValidityPolicy,
    answer_name_containment,
    classify_entity_type,
    screen_candidate,
)
from kg import graph_view                                          # noqa: E402
from mcq_core import AnswerFact, Candidate, FactQuality, build_case  # noqa: E402
from pipeline import phase_b2_any_answer_run_v3 as v3              # noqa: E402
from pipeline import phase_b2_any_answer_run_v4 as v4              # noqa: E402
from pipeline import graph_lrolesim_run as glr                     # noqa: E402
from rationale_v3.contracts import (                               # noqa: E402
    GRANULARITY_RISK_HIERARCHY_UNMODELLED,
    GRANULARITY_RISK_NONE,
    LEVEL_L0,
    LEVEL_L1,
    LEVEL_NOT_COVERED,
    RationaleProposition,
)
from rationale_v3.evidence import (                                # noqa: E402
    classify_fact_against_candidate,
    load_evidence_rules,
)
from rationale_v3.predicate_aliases import (                       # noqa: E402
    AUDITED_CANDIDATE_FAMILIES,
    DEFAULT_ALIAS_POLICY,
    FIELD_ALIAS_FAMILY,
    NO_ALIAS_POLICY,
    AliasFamily,
    PredicateAliasPolicy,
    observed_objects_for_key,
)
from rationale_v3.quality import load_quality_policy               # noqa: E402
from rationale_v3.semantic_relations import (                      # noqa: E402
    build_semantic_index,
    load_semantic_relation_policy,
)
from selection.granularity_clean import (                          # noqa: E402
    GRANULARITY_POLICIES,
    REPORT_ONLY_POLICY,
    REQUIRE_CLEAN_POLICY,
    STATUS_CLEAN_SELECTION_FOUND,
    STATUS_NO_GRANULARITY_CLEAN_RATIONALE,
    STATUS_NO_RISK_PRESENT,
    GranularityRiskPolicy,
    apply_granularity_policy,
    select_with_rationale_filter,
)

R = "http://dbpedia.org/resource/"
P = "http://dbpedia.org/property/"
POLICIES = SRC / "rationale_v3" / "policies"

FIELD_OUT = (P + "field", "OUT")
FIELDS_OUT = (P + "fields", "OUT")
FIELDS_IN = (P + "fields", "IN")


@pytest.fixture(scope="module")
def quality_v2():
    return load_quality_policy(POLICIES / "predicate_policy_v2.json")


@pytest.fixture(scope="module")
def rulebook():
    from pipeline.rationale_v3_run import EVIDENCE_RULES_PATH
    return load_evidence_rules(EVIDENCE_RULES_PATH)


@pytest.fixture(scope="module")
def semantic_index():
    policy = load_semantic_relation_policy(
        POLICIES / "semantic_relation_policy_v2.json")
    return build_semantic_index(policy=policy, parent_edges=[])


# ==========================================================================
# §2 — the THIRD candidate-validity policy, PERSON_GUARDED
# ==========================================================================
#
# The whole point of the new arm is what it does with UNKNOWN. Every test below
# pins one side of that distinction, because a policy that quietly started
# refusing UNKNOWN would read snapshot SILENCE as a contradiction — the single
# mistake the L0/L1 taxonomy exists to prevent.

PERSON_KEYS = ((P + "birthPlace", "OUT"), (P + "spouse", "OUT"))
WORK_KEYS = ((P + "author", "OUT"), (P + "publisher", "OUT"))


def _screen(answer_uri, candidate_uri, candidate_keys, policy, quality_policy,
            answer_keys=PERSON_KEYS):
    answer_type = classify_entity_type(answer_uri, answer_keys, policy=policy)
    return screen_candidate(
        answer_uri=answer_uri, candidate_uri=candidate_uri,
        observed_keys=candidate_keys, quality_policy=quality_policy,
        answer_type=answer_type, policy=policy)


def test_person_guarded_is_a_declared_policy_beside_the_other_two():
    assert TYPE_POLICIES == (TYPE_POLICY_OBSERVE_ONLY,
                             TYPE_POLICY_PERSON_GUARDED,
                             TYPE_POLICY_PERSON_STRICT)
    assert PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY.rejects_on_type is True
    assert PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY.rejects_unknown_type is False
    assert PERSON_STRICT_CANDIDATE_VALIDITY_POLICY.rejects_unknown_type is True
    assert DEFAULT_CANDIDATE_VALIDITY_POLICY.rejects_on_type is False


def test_person_guarded_rejects_a_confirmed_non_person(quality_v2):
    verdict = _screen(R + "Some_Person", R + "Some_Book", WORK_KEYS,
                      PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY, quality_v2)
    assert verdict.detected_entity_type == TYPE_NOT_PERSON
    assert verdict.accepted is False
    assert verdict.reject_reason == REJECT_TYPE_NOT_PERSON
    assert verdict.rejected_by_rule == REJECTED_BY_TYPE_RULE


def test_person_guarded_keeps_an_unknown_candidate(quality_v2):
    """The defining difference from PERSON_STRICT, and the reason it exists."""
    verdict = _screen(R + "Some_Person", R + "Silent_Entity", (),
                      PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY, quality_v2)
    assert verdict.detected_entity_type == TYPE_UNKNOWN
    assert verdict.accepted is True
    assert verdict.rejected_by_rule == REJECTED_BY_NOTHING


def test_person_strict_still_rejects_the_same_unknown_candidate(quality_v2):
    verdict = _screen(R + "Some_Person", R + "Silent_Entity", (),
                      PERSON_STRICT_CANDIDATE_VALIDITY_POLICY, quality_v2)
    assert verdict.accepted is False
    assert verdict.reject_reason == REJECT_TYPE_UNKNOWN


def test_observe_only_removes_nothing_under_either_detector(quality_v2):
    for candidate, keys in ((R + "Some_Book", WORK_KEYS),
                            (R + "Silent_Entity", ()),
                            (R + "Some_Person_in_Context", PERSON_KEYS)):
        verdict = _screen(R + "Some_Person", candidate, keys,
                          DEFAULT_CANDIDATE_VALIDITY_POLICY, quality_v2)
        assert verdict.accepted is True
        assert verdict.rejected_by_rule == REJECTED_BY_NOTHING


def test_the_three_arms_agree_on_every_detector_output(quality_v2):
    """Detection must be policy-independent, or no delta audit is meaningful."""
    for policy in (DEFAULT_CANDIDATE_VALIDITY_POLICY,
                   PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY,
                   PERSON_STRICT_CANDIDATE_VALIDITY_POLICY):
        verdict = _screen(R + "Muhammad", R + "Muhammad_in_Islam", PERSON_KEYS,
                          policy, quality_v2)
        assert verdict.detected_entity_type == TYPE_PERSON
        assert verdict.name_containment_detected is True


# ==========================================================================
# §3 — DETECTION and REJECTION are two different measurements
# ==========================================================================


def test_a_detector_may_fire_while_a_non_rejecting_policy_removes_nothing(
        quality_v2):
    """The exact defect §3 names, pinned as an invariant.

    The 329-Answer report published
    `candidate_topical_identity_leak_rejections = 0` for a run whose name
    detector had fired seventeen times. Zero REJECTIONS was true; zero
    DETECTIONS was false, and one field carried both meanings.
    """
    verdict = _screen(R + "Muhammad", R + "Muhammad_in_Islam", PERSON_KEYS,
                      DEFAULT_CANDIDATE_VALIDITY_POLICY, quality_v2)
    assert verdict.name_containment_detected is True
    assert verdict.name_containment_evidence != ""
    assert verdict.accepted is True
    assert verdict.rejected_by_rule == REJECTED_BY_NOTHING
    record = verdict.as_record()
    assert record["name_containment_detected"] is True
    assert record["reject_reason"] == "ACCEPTED"


def test_the_name_rule_rejects_under_both_acting_policies_and_says_so(
        quality_v2):
    for policy in (PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY,
                   PERSON_STRICT_CANDIDATE_VALIDITY_POLICY):
        verdict = _screen(R + "Muhammad", R + "Muhammad_in_Islam", PERSON_KEYS,
                          policy, quality_v2)
        assert verdict.accepted is False
        assert verdict.reject_reason == REJECT_ANSWER_NAME_CONTAINED
        # NOT falsely attributed to the type rule: the candidate is a PERSON.
        assert verdict.rejected_by_rule == REJECTED_BY_NAME_RULE
        assert verdict.detected_entity_type == TYPE_PERSON


def test_a_candidate_that_trips_both_detectors_is_attributed_to_one_rule(
        quality_v2):
    """A class of case the delta audit must be able to attribute exactly.

    §7 runs before §8, so a candidate that is BOTH the wrong kind of thing and
    a name container is reported as a TYPE rejection. The name detection stays
    visible on the same record, so nothing is lost.
    """
    verdict = _screen(R + "Some_Person", R + "Some_Person_Anthology", WORK_KEYS,
                      PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY, quality_v2)
    assert verdict.name_containment_detected is True
    assert verdict.detected_entity_type == TYPE_NOT_PERSON
    assert verdict.rejected_by_rule == REJECTED_BY_TYPE_RULE
    assert verdict.reject_reason == REJECT_TYPE_NOT_PERSON


class _Screen:
    """The minimum shape `candidate_screen_metrics()` reads."""

    def __init__(self, answer_type, verdicts):
        self.answer_type = answer_type
        self.verdicts = tuple(verdicts)


def test_candidate_screen_metrics_reports_detections_under_observe_only(
        quality_v2):
    verdicts = [
        _screen(R + "Muhammad", R + "Muhammad_in_Islam", PERSON_KEYS,
                DEFAULT_CANDIDATE_VALIDITY_POLICY, quality_v2),
        _screen(R + "Muhammad", R + "Some_Book", WORK_KEYS,
                DEFAULT_CANDIDATE_VALIDITY_POLICY, quality_v2),
        _screen(R + "Muhammad", R + "Silent_Entity", (),
                DEFAULT_CANDIDATE_VALIDITY_POLICY, quality_v2),
    ]
    metrics = v4.candidate_screen_metrics([_Screen(TYPE_PERSON, verdicts)])
    assert metrics["candidate_name_containment_detected_count"] == 1
    assert metrics["candidate_type_not_person_detected_count"] == 1
    assert metrics["candidate_type_unknown_detected_count"] == 1
    assert metrics["candidate_type_person_detected_count"] == 1
    # ... and nothing was removed.
    assert metrics["candidate_name_containment_rejected_count"] == 0
    assert metrics["candidate_type_rejected_count"] == 0
    assert metrics["candidates_rejected_total"] == 0
    # the v3 field names keep their v3 meaning
    assert metrics["candidate_topical_identity_leak_rejections"] == 0


def test_candidate_screen_metrics_separates_the_two_under_person_guarded(
        quality_v2):
    verdicts = [
        _screen(R + "Muhammad", R + "Muhammad_in_Islam", PERSON_KEYS,
                PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY, quality_v2),
        _screen(R + "Muhammad", R + "Some_Book", WORK_KEYS,
                PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY, quality_v2),
        _screen(R + "Muhammad", R + "Silent_Entity", (),
                PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY, quality_v2),
    ]
    metrics = v4.candidate_screen_metrics([_Screen(TYPE_PERSON, verdicts)])
    assert metrics["candidate_name_containment_detected_count"] == 1
    assert metrics["candidate_name_containment_rejected_count"] == 1
    assert metrics["candidate_type_rejected_count"] == 1      # the book
    assert metrics["candidate_type_unknown_detected_count"] == 1
    # PERSON_GUARDED keeps the UNKNOWN candidate, so only two were removed.
    assert metrics["candidates_rejected_total"] == 2
    assert metrics["candidates_accepted_total"] == 1


# ==========================================================================
# §5 — the versioned predicate-slot alias layer
# ==========================================================================


def test_the_empty_alias_policy_is_exact_key_lookup():
    observed = {FIELD_OUT: (R + "Chemistry",), FIELDS_OUT: (R + "Physics",)}
    assert observed_objects_for_key(observed, FIELD_OUT,
                                    policy=NO_ALIAS_POLICY) == (R + "Chemistry",)
    assert NO_ALIAS_POLICY.enabled is False
    assert NO_ALIAS_POLICY.keys_for(FIELD_OUT) == (FIELD_OUT,)


def test_the_audited_family_unions_the_two_spellings():
    observed = {FIELD_OUT: (R + "Chemistry",), FIELDS_OUT: (R + "Physics",)}
    merged = observed_objects_for_key(observed, FIELDS_OUT,
                                      policy=DEFAULT_ALIAS_POLICY)
    assert merged == (R + "Chemistry", R + "Physics")


def test_in_and_out_are_never_merged_by_an_alias():
    observed = {FIELDS_IN: (R + "Chemistry",)}
    assert observed_objects_for_key(observed, FIELD_OUT,
                                    policy=DEFAULT_ALIAS_POLICY) == ()
    keys = DEFAULT_ALIAS_POLICY.keys_for(FIELDS_IN)
    assert all(direction == "IN" for _, direction in keys)


def test_an_unlisted_predicate_is_untouched_by_the_alias_policy():
    observed = {(P + "spouse", "OUT"): (R + "Somebody",),
                (P + "spouses", "OUT"): (R + "Somebody_Else",)}
    assert observed_objects_for_key(observed, (P + "spouse", "OUT"),
                                    policy=DEFAULT_ALIAS_POLICY) == (
        R + "Somebody",)


def test_a_family_needs_two_members_and_recorded_evidence():
    with pytest.raises(ValueError):
        AliasFamily(canonical_slot="lonely", members=frozenset({P + "field"}),
                    evidence="x")
    with pytest.raises(ValueError):
        AliasFamily(canonical_slot="nameless",
                    members=frozenset({P + "field", P + "fields"}), evidence="  ")


def test_a_predicate_may_belong_to_at_most_one_family():
    other = AliasFamily(canonical_slot="duplicate",
                        members=frozenset({P + "field", P + "domain"}),
                        evidence="a deliberately conflicting test family")
    with pytest.raises(ValueError):
        PredicateAliasPolicy(families=(FIELD_ALIAS_FAMILY, other))


def test_the_workplace_family_is_recorded_as_NOT_admitted():
    """§5 forbids assuming equivalence from string similarity."""
    assert "workplace_family" in AUDITED_CANDIDATE_FAMILIES
    assert "NOT ADMITTED" in AUDITED_CANDIDATE_FAMILIES["workplace_family"]
    members = {m for f in DEFAULT_ALIAS_POLICY.families for m in f.members}
    for name in ("workplaces", "workplace", "workInstitution",
                 "workInstitutions"):
        assert P + name not in members


def test_an_alias_match_becomes_not_covered_not_l0(semantic_index, rulebook):
    """The Robert Boyle / Joseph Black shape, as an evidence-level invariant.

    The Answer records the discipline under the PLURAL spelling and the
    candidate records the SAME object under the SINGULAR spelling. Under exact
    keying the candidate's object set for the Answer's key is empty, and an
    empty set is `L0` — a statement that the snapshot records no field for the
    candidate, which is FALSE. Under the audited family the sets are unioned
    first, the object matches exactly, and the pair is `NOT_COVERED`: the
    candidate SUPPORTS the proposition and the fact discriminates nothing.
    """
    observed = {FIELD_OUT: (R + "Chemistry",)}
    proposition = RationaleProposition(
        predicate_uri=P + "fields", direction="OUT",
        source_object_uri=R + "Chemistry", claim_object_uri=R + "Chemistry")

    exact = classify_fact_against_candidate(
        proposition=proposition, candidate_uri=R + "Joseph_Black",
        candidate_objects=observed_objects_for_key(
            observed, FIELDS_OUT, policy=NO_ALIAS_POLICY),
        semantic_index=semantic_index, rulebook=rulebook, scope="test")
    assert exact.level == LEVEL_L0

    aliased = classify_fact_against_candidate(
        proposition=proposition, candidate_uri=R + "Joseph_Black",
        candidate_objects=observed_objects_for_key(
            observed, FIELDS_OUT, policy=DEFAULT_ALIAS_POLICY),
        semantic_index=semantic_index, rulebook=rulebook, scope="test")
    assert aliased.level == LEVEL_NOT_COVERED


def test_an_alias_can_only_ever_weaken_a_distinction(semantic_index, rulebook):
    """An alias union enlarges O_d(k), so it can never create an exclusion.

    A candidate observed under the alias with a DIFFERENT object stays L1: the
    union added an observation, it did not add support.
    """
    observed = {FIELD_OUT: (R + "Physics",)}
    proposition = RationaleProposition(
        predicate_uri=P + "fields", direction="OUT",
        source_object_uri=R + "Chemistry", claim_object_uri=R + "Chemistry")
    aliased = classify_fact_against_candidate(
        proposition=proposition, candidate_uri=R + "Somebody",
        candidate_objects=observed_objects_for_key(
            observed, FIELDS_OUT, policy=DEFAULT_ALIAS_POLICY),
        semantic_index=semantic_index, rulebook=rulebook, scope="test")
    assert aliased.level == LEVEL_L1


def test_the_semantic_source_set_widens_with_the_alias_policy():
    """The source-object set IS the semantic-index cache key.

    An index built without the aliases would omit exactly the objects the
    aliased lookup then asks about, and every one of those pairs would come back
    UNRESOLVED for no reason.
    """
    from pipeline.phase_b2_answer_run import enlarged_source_object_uris

    class _Fact:
        def __init__(self, predicate, direction, counterpart):
            self.predicate_direction_key = (predicate, direction)
            self.counterpart_uri = counterpart

    facts = [_Fact(P + "fields", "OUT", R + "Chemistry")]
    observed = {R + "Joseph_Black": {FIELD_OUT: (R + "Physics",)}}
    without = enlarged_source_object_uris(facts, observed)
    with_alias = enlarged_source_object_uris(facts, observed,
                                             alias_policy=DEFAULT_ALIAS_POLICY)
    assert R + "Physics" not in without
    assert R + "Physics" in with_alias
    assert R + "Chemistry" in without and R + "Chemistry" in with_alias


# ==========================================================================
# §6 — the versioned granularity-risk policy
# ==========================================================================


def _quality(predicate, counterpart, tier=1, label=None):
    label = label or counterpart.rsplit("/", 1)[-1]
    return FactQuality(
        predicate_uri=predicate, direction="OUT", counterpart_uri=counterpart,
        display_label=label, eligible=True, soft_leak=False, verbalizable=True,
        pedagogical_tier=tier, label_length=len(label),
        token_count=1, template_id="T")


def _case(*, risky_first: bool):
    """A four-candidate case with TWO single-fact covers of the same triple.

    Both facts cover all three distractors at L1, so |R*| = 1 either way and
    the ranking key decides. One of them carries a granularity risk and the
    other does not, which is exactly the situation `require-clean` exists for.
    """
    candidates = [Candidate(rank=i + 1, score=1.0 - i / 10, uri=f"{R}C{i + 1}")
                  for i in range(3)]
    risky = AnswerFact(
        quality=_quality(P + "field", R + "Radiochemistry", tier=1),
        levels=("L1", "L1", "L1"),
        exclusion_bases=("NONE", "NONE", "NONE"),
        granularity_risks=(GRANULARITY_RISK_HIERARCHY_UNMODELLED,) * 3)
    clean = AnswerFact(
        quality=_quality(P + "birthPlace", R + "Somewhere", tier=1),
        levels=("L1", "L1", "L1"),
        exclusion_bases=("NONE", "NONE", "NONE"),
        granularity_risks=("NONE", "NONE", "NONE"))
    facts = (risky, clean) if risky_first else (clean, risky)
    return build_case(R + "TheAnswer", "The Answer", candidates, facts)


def _all_risky_case():
    candidates = [Candidate(rank=i + 1, score=1.0 - i / 10, uri=f"{R}C{i + 1}")
                  for i in range(3)]
    risky = AnswerFact(
        quality=_quality(P + "field", R + "Radiochemistry"),
        levels=("L1", "L1", "L1"),
        exclusion_bases=("NONE", "NONE", "NONE"),
        granularity_risks=(GRANULARITY_RISK_HIERARCHY_UNMODELLED,) * 3)
    return build_case(R + "TheAnswer", "The Answer", candidates, (risky,))


def test_the_granularity_policy_names_exactly_two_modes():
    assert GRANULARITY_POLICIES == ("report-only", "require-clean")
    with pytest.raises(ValueError):
        GranularityRiskPolicy(mode="whatever")


def test_report_only_changes_nothing():
    case = _case(risky_first=True)
    baseline = mcq_core.select_distractors(
        case, objective=mcq_core.RATIONALE_OBJECTIVE_V3)
    outcome = apply_granularity_policy(
        case, baseline, policy=REPORT_ONLY_POLICY,
        objective=mcq_core.RATIONALE_OBJECTIVE_V3)
    assert outcome.selection is baseline
    assert outcome.learner_facing is True
    assert outcome.distractors_changed is False
    assert outcome.rationale_changed is False


def test_require_clean_prefers_a_clean_rationale_when_one_exists():
    case = _case(risky_first=True)
    baseline = mcq_core.select_distractors(
        case, objective=mcq_core.RATIONALE_OBJECTIVE_V3)
    outcome = apply_granularity_policy(
        case, baseline, policy=REQUIRE_CLEAN_POLICY,
        objective=mcq_core.RATIONALE_OBJECTIVE_V3)
    assert outcome.selection is not None
    assert outcome.selection.rationale.granularity_risk_incidences == 0
    assert outcome.learner_facing is True
    # |R*| is NEVER grown to buy pedagogical safety.
    assert (outcome.selection.minimum_rationale_size
            == baseline.minimum_rationale_size)


def test_require_clean_reports_a_diagnostic_when_no_clean_rationale_exists():
    case = _all_risky_case()
    baseline = mcq_core.select_distractors(
        case, objective=mcq_core.RATIONALE_OBJECTIVE_V3)
    assert baseline is not None
    outcome = apply_granularity_policy(
        case, baseline, policy=REQUIRE_CLEAN_POLICY,
        objective=mcq_core.RATIONALE_OBJECTIVE_V3)
    assert outcome.status == STATUS_NO_GRANULARITY_CLEAN_RATIONALE
    assert outcome.learner_facing is False
    # The item is still REPORTED, with its evidence levels untouched.
    assert outcome.selection is baseline
    assert baseline.rationale.rationale_min_level == "L1"
    assert outcome.selection.mcq_evidence_level == "MCQ-L1"


def test_require_clean_never_converts_a_risky_l1_into_l0():
    case = _all_risky_case()
    baseline = mcq_core.select_distractors(
        case, objective=mcq_core.RATIONALE_OBJECTIVE_V3)
    before = [tuple(f.levels) for f in case.facts]
    apply_granularity_policy(case, baseline, policy=REQUIRE_CLEAN_POLICY,
                             objective=mcq_core.RATIONALE_OBJECTIVE_V3)
    assert [tuple(f.levels) for f in case.facts] == before
    assert all(level == "L1" for levels in before for level in levels)


def test_a_tolerated_risk_state_is_admissible():
    """The two readings of 'zero risk' are a VALUE, so they can be measured."""
    case = _all_risky_case()
    baseline = mcq_core.select_distractors(
        case, objective=mcq_core.RATIONALE_OBJECTIVE_V3)
    lenient = GranularityRiskPolicy(
        mode="require-clean",
        tolerated_risk_states=frozenset({GRANULARITY_RISK_HIERARCHY_UNMODELLED}))
    outcome = apply_granularity_policy(
        case, baseline, policy=lenient,
        objective=mcq_core.RATIONALE_OBJECTIVE_V3)
    assert outcome.status == STATUS_NO_RISK_PRESENT
    assert outcome.learner_facing is True


@pytest.mark.parametrize("objective", [
    mcq_core.RATIONALE_OBJECTIVE_V1,
    mcq_core.RATIONALE_OBJECTIVE_V2,
    mcq_core.RATIONALE_OBJECTIVE_V3,
])
def test_the_filtered_search_reduces_to_the_frozen_kernel(objective):
    """The equivalence that makes the §6 re-search safe to ship.

    `select_with_rationale_filter(admissible=None)` must BE
    `mcq_core.select_distractors()`. It is checked on the eight frozen pilot
    Answers, whose selections are the project's regression oracle, and on the
    synthetic cases above.
    """
    from test_mcq_core import load_pilot_cases

    cases = list(load_pilot_cases().values()) + [
        _case(risky_first=True), _case(risky_first=False), _all_risky_case()]
    for case in cases:
        assert (select_with_rationale_filter(case, objective=objective,
                                             admissible=None)
                == mcq_core.select_distractors(case, objective=objective))


# ==========================================================================
# §7 — objective v3 is the v4 CANDIDATE default and the v3 default did not move
# ==========================================================================


def test_objective_v3_is_the_v4_candidate_default():
    assert (v4.V4_CANDIDATE_RUNNER_CONFIG.rationale_objective
            == mcq_core.RATIONALE_OBJECTIVE_V3)


def test_the_historical_v3_runner_default_is_unchanged():
    assert (v3.DEFAULT_RUNNER_CONFIG.rationale_objective
            == mcq_core.RATIONALE_OBJECTIVE_V2)
    assert (v3.V2_COMPATIBLE_RUNNER_CONFIG.rationale_objective
            == mcq_core.RATIONALE_OBJECTIVE_V1)
    assert mcq_core.DEFAULT_RATIONALE_OBJECTIVE == mcq_core.RATIONALE_OBJECTIVE_V1


def test_the_v3_compatible_v4_config_reproduces_the_b2ef_generation():
    config = v4.V3_COMPATIBLE_RUNNER_CONFIG
    assert config.rationale_objective == mcq_core.RATIONALE_OBJECTIVE_V2
    assert config.graph_max_nodes == graph_view.DEFAULT_MAX_NODES
    assert config.alias_policy.enabled is False
    assert config.granularity_policy.mode == "report-only"


def test_objective_v3_demotes_only_the_annotation():
    """Fields 1-4 — the complete evidence LEVEL profile — must be untouched."""
    rationale = mcq_core.Rationale(
        fact_indices=(0,), fact_identities=(("p", "OUT", "o"),),
        coverage_masks=(7,), coverage_mask=7,
        per_candidate_best_level=("L1", "L1", "L1"), rationale_min_level="L1",
        l2_incidences=0, l1_incidences=3, l0_incidences=0,
        scoped_empirical_incidences=3, granularity_risk_incidences=1,
        soft_leak_fact_count=0, pedagogical_tier_sum=1,
        unverbalizable_fact_count=0, label_length_sum=4, token_count_sum=1,
        redundant_predicate_direction_pairs=0,
        local_candidate_pool_anonymity_count=1,
        local_candidate_pool_anonymity_ratio=0.1, direct_identifier_flag=True,
        option_reference_conflict_count=1)
    assert rationale.ranking_key_v3[:4] == rationale.ranking_key[:4]
    # v3 reads the risk and the conflict BEFORE the annotation.
    assert rationale.ranking_key_v3[4:7] == (1, 1, -3)
    assert rationale.ranking_key[4:6] == (-3, 1)


# ==========================================================================
# §8 — the graph budget is a declared parameter with real diagnostics
# ==========================================================================


def test_the_frozen_node_budget_is_unchanged_and_v4_declares_its_own():
    assert graph_view.DEFAULT_MAX_NODES == 1200
    assert glr.GRAPH_MAX_NODES == 1200
    assert v4.V4_GRAPH_MAX_NODES == 5000
    assert v4.V4_CANDIDATE_RUNNER_CONFIG.graph_max_nodes == 5000


class _BudgetKG:
    """A toy graph in which the node budget is the only thing that can bind.

    The Answer has two neighbours; each candidate has `width` private
    neighbours, so `max_nodes` decides exactly how many candidates fit.
    """

    def __init__(self, candidates=6, width=10):
        self.out_neighbor = {}
        self.in_neighbor = {}
        node = 1000
        self.out_neighbor[0] = [(900, 1), (900, 2)]
        for c in range(1, candidates + 1):
            edges = []
            for _ in range(width):
                node += 1
                edges.append((900, node))
            self.out_neighbor[c] = edges
        self.url_index = {}
        self.index_url = {}
        self.index_type = {}


def _budget_facts(candidates=6):
    from pipeline.candidate_order import ORIGIN_EXACT, MappedCandidate

    return glr.ClassMappingFacts(
        pilot_slot=0, answer_uri=R + "A", answer_local_index=0,
        class_position="preferred", class_uri=R + "Category:X",
        retrieval_complete=True,
        mapped_candidate_count_excluding_answer=candidates,
        accepted=tuple(
            MappedCandidate(canonical_uri=f"{R}C{i}", local_index=i,
                            mapping_origin=ORIGIN_EXACT)
            for i in range(1, candidates + 1)),
    )


def test_the_protected_graph_sources_are_byte_identical_to_their_pins():
    """§8 is implemented WITHOUT touching a protected source.

    `pipeline/graph_lrolesim_run.py` and `kg/graph_view.py` carry pinned
    SHA-256 digests in `rationale_v3_run.PROTECTED_SOURCE_PINS`, and the R1 and
    Prompt-8E runs REFUSE TO START if either has moved. The declared node budget
    therefore had to be threaded through the EXISTING `max_nodes` parameter and
    the diagnostics computed from the frozen `GraphBudgetResult`.
    """
    import hashlib

    from pipeline.rationale_v3_run import PROTECTED_SOURCE_PINS

    pins = {name: digest for name, _, digest in PROTECTED_SOURCE_PINS}
    for name, relative in (("graph_lrolesim_run", "pipeline/graph_lrolesim_run.py"),
                           ("graph_view", "kg/graph_view.py")):
        digest = hashlib.sha256((SRC / relative).read_bytes()).hexdigest()
        assert digest == pins[name], f"{relative} is a PROTECTED SOURCE"


def test_attempt_class_graph_honours_the_declared_budget():
    kg = _BudgetKG(candidates=12, width=10)
    facts = _budget_facts(candidates=12)
    tight, tight_graph, _ = glr.attempt_class_graph(facts, kg, max_nodes=60,
                                                    min_candidates=10)
    loose, loose_graph, _ = glr.attempt_class_graph(facts, kg, max_nodes=5000,
                                                    min_candidates=10)
    assert tight_graph.budget.max_nodes == 60
    assert loose_graph.budget.max_nodes == 5000
    assert tight.accepted_candidate_count < loose.accepted_candidate_count
    assert tight.rejected_would_exceed_max_nodes > 0
    assert loose.rejected_would_exceed_max_nodes == 0


def test_the_v4_row_reports_the_effective_budget_not_the_constant():
    """The frozen writer stamps the constant; v4 corrects its own copy."""
    kg = _BudgetKG(candidates=12, width=10)
    attempt, m1, order = glr.attempt_class_graph(_budget_facts(12), kg,
                                                 max_nodes=60,
                                                 min_candidates=10)
    diagnostics = v4.graph_budget_diagnostics(attempt, m1, order, local_kg=kg,
                                              answer_index=0)
    frozen_row = attempt.as_row()
    v4_row = v4.graph_row_with_effective_budget(attempt, diagnostics)
    assert frozen_row["max_nodes"] == glr.GRAPH_MAX_NODES == 1200
    assert v4_row["max_nodes"] == 60
    # the row SHAPE is unchanged, so every existing reader keeps working
    assert set(v4_row) == set(frozen_row)


def test_graph_budget_diagnostics_explain_an_insufficient_candidate_failure():
    kg = _BudgetKG(candidates=12, width=10)
    attempt, m1, order = glr.attempt_class_graph(_budget_facts(12), kg,
                                                 max_nodes=60,
                                                 min_candidates=10)
    diagnostics = v4.graph_budget_diagnostics(attempt, m1, order, local_kg=kg,
                                              answer_index=0)
    assert diagnostics["outcome"] == glr.ATTEMPT_GRAPH_BUDGET_INSUFFICIENT
    assert diagnostics["lost_would_exceed_max_nodes"] > 0
    assert diagnostics["lost_total"] == diagnostics["lost_would_exceed_max_nodes"]
    assert "larger node budget would recover" in diagnostics["explanation"]
    assert diagnostics["effective_max_nodes"] == 60
    assert diagnostics["answer_base_node_count"] == 3   # the Answer + 2


def test_graph_budget_diagnostics_say_when_the_budget_never_bound():
    kg = _BudgetKG(candidates=12, width=10)
    attempt, m1, order = glr.attempt_class_graph(_budget_facts(12), kg,
                                                 max_nodes=5000,
                                                 min_candidates=10)
    diagnostics = v4.graph_budget_diagnostics(attempt, m1, order, local_kg=kg,
                                              answer_index=0)
    assert diagnostics["lost_total"] == 0
    assert "never binding" in diagnostics["explanation"]


def test_graph_budget_diagnostics_name_an_answer_base_that_eats_the_budget():
    """The Kingdom-of-Italy shape: a larger CLASS choice cannot repair it."""
    kg = _BudgetKG(candidates=12, width=5)
    # The Answer alone now charges 41 nodes to a 10-node budget. The candidate
    # count stays above the graph-stage mapping gate so the builder really runs.
    kg.out_neighbor[0] = [(900, 8000 + i) for i in range(40)]
    attempt, m1, order = glr.attempt_class_graph(_budget_facts(12), kg,
                                                 max_nodes=10,
                                                 min_candidates=10)
    diagnostics = v4.graph_budget_diagnostics(attempt, m1, order, local_kg=kg,
                                              answer_index=0)
    assert diagnostics["answer_base_exceeds_budget"] is True
    assert diagnostics["answer_base_node_count"] == 41
    assert diagnostics["lost_answer_base_exceeds_budget"] == 12
    assert diagnostics["lost_would_exceed_max_nodes"] == 0
    assert "No CLASS choice can repair this" in diagnostics["explanation"]


# ==========================================================================
# §10 — class-leak rejection metrics that are not a silent zero
# ==========================================================================


class _Result:
    """The minimum shape `class_rejection_metrics()` reads."""

    def __init__(self, *, discovered=0, feasible=0, rejected=0,
                 records=None, with_attribute=True):
        self.categories_discovered = discovered
        self.feasible_class_count = feasible
        self.rejected_class_count = rejected
        if with_attribute:
            self.class_ranking_rejections = tuple(records or ())


def _record(code, leak="no_leak", reasons=None):
    return {"category_uri": f"{R}Category:{code}", "category_label": code,
            "primary_rejected_code": code, "rejected_reason": "",
            "all_rejection_reasons": list(reasons or [code]),
            "leak_level": leak, "leak_status": "EVALUATED",
            "leak_source": "rationale_v3_r1", "leak_reason": "",
            "leak_evidence": [], "r1_leak_level": leak,
            "class_rule_leak_evidence": [], "remote_count": 100,
            "eligible_remote_count": 99}


def test_class_rejection_metrics_count_every_gate():
    results = [_Result(discovered=21, feasible=16, rejected=5, records=[
        _record("hard_leak", leak="hard_leak"),
        _record("insufficient_remote_candidates"),
        _record("insufficient_remote_candidates", leak="hard_leak",
                reasons=["insufficient_remote_candidates", "hard_leak"]),
        _record("too_generic"),
        _record("junk_category"),
    ])]
    metrics = v4.class_rejection_metrics(results)
    assert metrics["total_classes_discovered"] == 21
    assert metrics["feasible_classes"] == 16
    assert metrics["total_rejected_classes"] == 5
    assert metrics["rejection_records_collected"] == 5
    assert metrics["hard_class_leak_rejections"] == 1
    # a class refused on size FIRST still carries its true leakage verdict
    assert metrics["hard_leaking_classes_by_any_rejection_reason"] == 2
    assert metrics["too_small_rejections"] == 2
    assert metrics["too_generic_rejections"] == 1
    assert metrics["junk_category_rejections"] == 1
    assert metrics["all_independent_rejection_reasons"]["hard_leak"] == 2


def test_a_missing_attribute_is_visible_instead_of_silently_zero():
    """The exact v3 defect, pinned so it cannot come back unnoticed.

    v3 computed the metric inside `if hasattr(r, "class_ranking_rejections")`.
    `AnswerRunResult` never had that attribute, so the guard excluded every
    result and the metric published a hard zero that read like a finding.
    """
    metrics = v4.class_rejection_metrics(
        [_Result(discovered=21, feasible=16, rejected=5, with_attribute=False)])
    assert metrics["hard_class_leak_rejections"] == 0
    # ... but the denominator says nobody was asked, which is the repair.
    assert metrics["answers_in_batch"] == 1
    assert metrics["answers_with_rejection_records"] == 0
    assert metrics["total_rejected_classes"] == 5


def test_the_v3_expression_would_have_reported_zero():
    """Reproduce the old expression and show it could not have worked."""
    results = [_Result(discovered=21, feasible=16, rejected=5,
                       records=[_record("hard_leak", leak="hard_leak")],
                       with_attribute=False)]
    old = sum(sum(1 for _ in r.class_ranking_rejections)
              for r in results if hasattr(r, "class_ranking_rejections"))
    assert old == 0
    assert v4.class_rejection_metrics(results)["answers_with_rejection_records"] == 0


# ==========================================================================
# §11 — two rank-retention denominators
# ==========================================================================


class _Sel:
    def __init__(self, ranks, level):
        self.distractors = tuple(Candidate(rank=r, score=1.0, uri=f"{R}C{r}")
                                 for r in ranks)
        self._level = level

    @property
    def mcq_evidence_level(self):
        return self._level


class _RankResult:
    def __init__(self, ranks=None, level="MCQ-L1"):
        self.selection = None if ranks is None else _Sel(ranks, level)
        self.mcq_evidence_level = None if ranks is None else level


def test_l1_plus_excludes_diagnostic_l0_items():
    results = [
        _RankResult([1, 2, 3], "MCQ-L1"),
        _RankResult([1, 2, 3], "MCQ-L1"),
        _RankResult([4, 5, 6], "MCQ-L0"),
        _RankResult(None),
    ]
    block = v4.lrolesim_rank_retention(results)
    assert block["any_kernel_selection"]["denominator"] == 3
    assert block["l1_plus_student_showable"]["denominator"] == 2
    assert block["n_L1_plus"] == 2
    assert block["any_kernel_selection"]["exact_ranks_1_2_3"] == 2
    assert block["l1_plus_student_showable"]["exact_ranks_1_2_3"] == 2
    assert block["l1_plus_student_showable"]["exact_ranks_1_2_3_pct"] == 100.0
    assert block["any_kernel_selection"]["exact_ranks_1_2_3_pct"] == 66.67


def test_mcq_l2_counts_towards_l1_plus():
    results = [_RankResult([1, 2, 3], "MCQ-L2"), _RankResult([2, 3, 4], "MCQ-L0")]
    block = v4.lrolesim_rank_retention(results)
    assert block["n_L1_plus"] == 1


def test_an_empty_denominator_is_reported_as_none_not_zero():
    block = v4.lrolesim_rank_retention([_RankResult(None)])
    assert block["l1_plus_student_showable"]["denominator"] == 0
    assert block["l1_plus_student_showable"]["exact_ranks_1_2_3_pct"] is None
    assert block["l1_plus_student_showable"]["all_selected_ranks"]["mean"] is None


# ==========================================================================
# §12 — |R*| can never be lost to a truncation again
# ==========================================================================


def test_the_v2_truncation_defect_is_reproducible():
    """The old cell built the facts and then wrote the cardinality LAST.

    Truncating that string to 46 characters removed the only field that said
    how many facts a learner must be shown — which is where the '57 of 329 rows
    show no |R*|' reading came from. It was a PRESENTATION defect, not 57
    Answers failing to produce a rationale.
    """
    facts = "; ".join(f"predicate{i} -> Object_{i}" for i in range(3))
    old_cell = f"{facts} (|R*|=3)"
    assert "|R*|" in old_cell
    assert "|R*|" not in old_cell[:46]


def test_the_v3_and_v4_tables_keep_the_cardinality_in_its_own_column():
    """|R*| is a CELL of its own, not a suffix inside the facts cell.

    Splitting the header on "|" cannot work: the cardinality column's own
    label contains escaped pipes. So the test checks the structural property
    directly — the cardinality marker appears BETWEEN the two column
    separators that bound it, and the facts column is a different cell.
    """
    header = v3.summary_table_v3([]).splitlines()[0]
    assert "| \\|R*\\| |" in header
    assert "| Rationale facts |" in header
    assert header.index("\\|R*\\|") < header.index("Rationale facts")
    v4_header = v4.summary_table_v4([]).splitlines()[0]
    assert "| \\|R*\\| |" in v4_header


def test_the_integrity_block_separates_failure_from_formatting():
    metrics = v4.batch_metrics_v4([], config=None, screens=())
    integrity = metrics["rationale_cardinality_integrity"]
    assert integrity["answers_with_selection"] == 0
    assert "PRESENTATION defect" in integrity["note"]


# ==========================================================================
# The v4 configuration record, and what it promises about itself
# ==========================================================================


def test_the_v4_config_record_names_every_versioned_choice():
    record = v4.V4_CANDIDATE_RUNNER_CONFIG.as_record()
    for key in ("schema_version", "rationale_objective", "graph_max_nodes",
                "predicate_alias_policy", "granularity_risk_policy",
                "candidate_validity_policy", "class_leakage_policy",
                "predicate_policy_path", "semantic_relation_policy_path"):
        assert key in record, key
    assert record["graph_max_nodes_frozen_v3_value"] == 1200
    assert "CANDIDATE CONFIGURATION" in record["publication_status"]


def test_the_v4_config_does_not_declare_a_candidate_or_granularity_default():
    """§2 and §6 both say the decision is NOT made in this task."""
    config = v4.V4_CANDIDATE_RUNNER_CONFIG
    assert config.candidate_validity_policy.type_policy == TYPE_POLICY_OBSERVE_ONLY
    assert config.granularity_policy.mode == "report-only"


def test_batch_metrics_v4_keeps_every_v3_block():
    v3_metrics = v3.batch_metrics([], config=None, screens=())
    v4_metrics = v4.batch_metrics_v4([], config=None, screens=())
    for key in v3_metrics:
        assert key in v4_metrics, key
    for key in ("candidate_screen", "class_rejections",
                "lrolesim_rank_retention_v4", "granularity_policy",
                "rationale_cardinality_integrity"):
        assert key in v4_metrics
    # the v3 rank-retention block is retained UNCHANGED beside the v4 one
    assert v4_metrics["lrolesim_rank_retention"] == \
        v3_metrics["lrolesim_rank_retention"]


def test_no_named_regression_answer_is_a_production_branch():
    """§0: no Answer-specific production branch, no hard-coded regression name.

    The check TOKENIZES each source and discards every COMMENT and STRING
    token before searching. What survives is the executable part of the file —
    identifiers, operators, numbers — and a DBpedia URI can never be an
    identifier, so a surviving occurrence could only be control flow.

    Prose and recorded EVIDENCE strings are deliberately allowed: the audited
    alias family cites the corpus measurement that justified it by name, which
    is provenance a reviewer needs, not a branch.
    """
    import io
    import tokenize

    names = ("muhammad", "otto_hahn", "otto hahn", "augustus", "robert_boyle",
             "niels_bohr", "kingdom_of_italy", "george_washington",
             "ashikaga", "socrates", "joseph_black", "richard_kuhn",
             "marie_curie", "plato", "epicurus", "plotinus")
    sources = [SRC / "classes" / "candidate_validity.py",
               SRC / "rationale_v3" / "predicate_aliases.py",
               SRC / "selection" / "granularity_clean.py",
               SRC / "pipeline" / "phase_b2_any_answer_run_v4.py",
               ROOT / "scripts" / "run_phase_b2_any_answer_v4.py"]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        executable = []
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING,
                              tokenize.NL, tokenize.NEWLINE):
                continue
            executable.append(token.string)
        code = " ".join(executable).lower()
        for name in names:
            assert name not in code, (
                f"{path.name} names {name!r} in executable code; §0 forbids an "
                f"Answer-specific production branch")


def test_the_named_regression_answers_are_not_in_the_shipped_policies():
    """The same discipline, applied to the versioned POLICY objects."""
    record = json.dumps(v4.V4_CANDIDATE_RUNNER_CONFIG.as_record()).lower()
    for name in ("muhammad", "otto hahn", "augustus", "niels bohr",
                 "kingdom of italy", "george washington", "ashikaga"):
        assert name not in record
