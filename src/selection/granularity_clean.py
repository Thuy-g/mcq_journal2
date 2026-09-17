############################################################################
# src/selection/granularity_clean.py
#
# THE VERSIONED GRANULARITY-RISK POLICY — Prompt 8H-B2-G §6.
#
# WHAT THE POLICY IS FOR
# -----------------------
# `granularity_risk` is the axis that records that an APPARENT contrast may be
# an artefact of how two articles were written rather than a real difference:
#
#     Otto Hahn    dbp:field -> dbr:Radiochemistry
#     Marie Curie  dbp:field -> dbr:Chemistry , dbr:Physics
#
# Radiochemistry is a subfield of chemistry, so "Hahn worked in radiochemistry
# and Curie did not" is a statement the snapshot does not support. The evidence
# LEVEL stays what it is — an observed alternative value really was observed —
# and the doubt is recorded on its own axis, exactly as
# `docs/context/EVIDENCE_TAXONOMY_V1.md` §5 requires.
#
# Until now that record was ORDERING ONLY: a risky rationale could still be the
# selected one, and the report merely said so. §6 asks for a VERSIONED switch:
#
#     report-only    the historical behaviour. A risky rationale may still be
#                    selected; it is flagged and counted. Nothing is removed.
#     require-clean  a learner-facing MAIN rationale must carry zero
#                    granularity-risk incidences. A risky rationale is not
#                    shown as a reason; a clean alternative is preferred when
#                    one exists at the same admissible search level, and when
#                    none exists the run says so EXPLICITLY.
#
# THE FOUR THINGS require-clean MUST NOT DO, AND DOES NOT
# --------------------------------------------------------
#   1. It never converts a risky L1 into L0. Levels are decided upstream by
#      `classify_fact_against_candidate()` and nothing here touches them.
#   2. It never invents NOT_COVERED. No fact is reclassified; facts are only
#      ADMITTED or not admitted into a rationale.
#   3. It never invents a fact, a triple or a hierarchy edge.
#   4. It never silently degrades to a weaker evidence policy. When no clean
#      rationale exists at the policy the kernel reached, the result is reported
#      with an explicit diagnostic status and is NOT re-searched under a weaker
#      evidence policy, because "we could not find a safe reason" is a
#      measurement and rescuing it with absence evidence would be worse than
#      reporting it.
#
# WHY THIS LIVES OUTSIDE `mcq_core.py`
# -------------------------------------
# `src/mcq_core.py` is the frozen selection kernel and is not edited. The
# function below reproduces the kernel's own control flow by CALLING the
# kernel's public pieces — `build_candidate_pool`, `feasible_combinations`,
# `combination_prefix_key`, `rank_minimum_rationales`,
# `combination_objective_key` — and adds exactly one thing: an admissibility
# predicate over rationales, plus the prefix-tier walk that predicate makes
# necessary.
#
# THE ONE CONTROL-FLOW DIFFERENCE, AND WHY IT IS EXACT
# ------------------------------------------------------
# The kernel computes the BEST value of objective keys 1-3 over the feasible
# combinations and then only materialises rationales for the combinations that
# achieve it. That is exact, because the objective is lexicographic and a
# combination that lost on keys 1-3 can never be rescued by keys 4-6 — PROVIDED
# every best-prefix combination yields a rationale. With an admissibility
# filter that proviso can fail: every best-prefix combination may have only
# risky minimum-cardinality covers. So this function walks the DISTINCT prefix
# values in ascending order and stops at the FIRST tier that yields an
# admissible finalist. With a predicate that admits everything the walk stops at
# the first tier and the result is identical to `select_distractors()`, which is
# asserted directly by `test_b2g_final_benchmark_safety_v4.py`.
#
# IMPORT-TIME PURITY: no I/O, no network, no policy file read at import.
############################################################################

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mcq_core import (                                             # noqa: E402
    DEFAULT_POOL_POLICY,
    DEFAULT_RATIONALE_OBJECTIVE,
    POLICY_ORDER,
    AnswerCase,
    PoolPolicy,
    Rationale,
    Selection,
    build_candidate_pool,
    combination_objective_key,
    combination_prefix_key,
    feasible_combinations,
    rank_minimum_rationales,
)

__all__ = [
    "GRANULARITY_RISK_POLICY_VERSION",
    "GRANULARITY_POLICY_REPORT_ONLY",
    "GRANULARITY_POLICY_REQUIRE_CLEAN",
    "GRANULARITY_POLICIES",
    "GranularityRiskPolicy",
    "REPORT_ONLY_POLICY",
    "REQUIRE_CLEAN_POLICY",
    "GranularityCleanOutcome",
    "STATUS_NO_RISK_PRESENT",
    "STATUS_CLEAN_SELECTION_FOUND",
    "STATUS_NO_GRANULARITY_CLEAN_RATIONALE",
    "select_with_rationale_filter",
    "apply_granularity_policy",
]

GRANULARITY_RISK_POLICY_VERSION = "granularity_risk_policy/1.0.0"

GRANULARITY_POLICY_REPORT_ONLY = "report-only"
GRANULARITY_POLICY_REQUIRE_CLEAN = "require-clean"
GRANULARITY_POLICIES = (GRANULARITY_POLICY_REPORT_ONLY,
                        GRANULARITY_POLICY_REQUIRE_CLEAN)

#: What `apply_granularity_policy()` concluded, as three distinct findings.
#: "there was no risk to begin with" and "a clean alternative was found" are
#: different facts and are never collapsed, because the first says the corpus is
#: safe here and the second says the policy DID something.
STATUS_NO_RISK_PRESENT = "GRANULARITY_NO_RISK_IN_THE_SELECTED_RATIONALE"
STATUS_CLEAN_SELECTION_FOUND = "GRANULARITY_CLEAN_ALTERNATIVE_SELECTED"
STATUS_NO_GRANULARITY_CLEAN_RATIONALE = "NO_GRANULARITY_CLEAN_MAIN_RATIONALE"


@dataclass(frozen=True)
class GranularityRiskPolicy:
    """The complete, versioned configuration of the §6 switch.

    ``tolerated_risk_states`` names the granularity-risk states a learner-facing
    rationale may still carry under ``require-clean``. It is EMPTY by default —
    the strictest reading of "zero unresolved granularity-risk incidences" — and
    exists so a researcher can, for example, tolerate
    ``HIERARCHY_NOT_MODELLED_FOR_THESE_OBJECTS`` (the index ran and simply has no
    model for this object pair) while refusing
    ``CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT`` (a positively observed containment
    the wrong way round). Making that a value rather than a constant is what
    lets the two readings be MEASURED instead of argued about.
    """

    mode: str = GRANULARITY_POLICY_REPORT_ONLY
    tolerated_risk_states: frozenset = frozenset()
    version: str = GRANULARITY_RISK_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.mode not in GRANULARITY_POLICIES:
            raise ValueError(
                f"unknown granularity-risk policy {self.mode!r}; expected one "
                f"of {GRANULARITY_POLICIES}")

    @property
    def requires_clean(self) -> bool:
        return self.mode == GRANULARITY_POLICY_REQUIRE_CLEAN

    def admits(self, case: AnswerCase, positions: Sequence[int],
               rationale: Rationale) -> bool:
        """May this rationale be the learner-facing one under this policy?

        Under ``report-only`` every rationale is admissible, so the whole
        mechanism is inert and the kernel's own choice stands.

        Under ``require-clean`` the test is on the risk STATES actually present
        under the selected positions, not merely on the incidence count, so a
        tolerated state does not have to be subtracted from a total.
        """
        if not self.requires_clean:
            return True
        for index in rationale.fact_indices:
            for position in positions:
                state = case.facts[index].granularity_risks[position]
                if state != "NONE" and state not in self.tolerated_risk_states:
                    return False
        return True

    def as_record(self) -> dict:
        return {
            "granularity_risk_policy_version": self.version,
            "granularity_risk_policy": self.mode,
            "tolerated_risk_states": sorted(self.tolerated_risk_states),
            "note": ("report-only is the historical behaviour: a risky "
                     "rationale may still be selected and is flagged. "
                     "require-clean refuses a risky rationale as the "
                     "learner-facing main reason; it never changes an evidence "
                     "level, never invents NOT_COVERED and never rescues an "
                     "item with a weaker evidence policy."),
        }


REPORT_ONLY_POLICY = GranularityRiskPolicy(mode=GRANULARITY_POLICY_REPORT_ONLY)
REQUIRE_CLEAN_POLICY = GranularityRiskPolicy(
    mode=GRANULARITY_POLICY_REQUIRE_CLEAN)


def select_with_rationale_filter(
    case: AnswerCase,
    pool_policy: PoolPolicy = DEFAULT_POOL_POLICY,
    force_pool: bool = False,
    objective: str = DEFAULT_RATIONALE_OBJECTIVE,
    admissible: Optional[Callable[[AnswerCase, Sequence[int], Rationale], bool]] = None,
) -> Optional[Selection]:
    """`mcq_core.select_distractors()` restricted to ADMISSIBLE rationales.

    With ``admissible=None`` this is `select_distractors()` — same pool, same
    policy order, same prefix optimisation, same six-key objective, same
    `Selection` — and the equivalence is a test, not a claim.

    With a predicate supplied, a combination survives only if at least one of
    its MINIMUM-CARDINALITY rationales is admissible; the best admissible one
    represents it in objective key 4. |R*| is NEVER grown to find a clean
    rationale: the cardinality is fixed by the exact set cover before key 4 is
    consulted, and a policy that could enlarge it would be buying pedagogical
    safety with a longer explanation, which §6 does not ask for.

    Returns ``None`` when no combination under any evidence policy has an
    admissible minimum-cardinality rationale.
    """
    pool = build_candidate_pool(case, policy=pool_policy, force_pool=force_pool)
    for policy in POLICY_ORDER:
        survivors = feasible_combinations(case, policy, pool)
        if not survivors:
            continue

        # Keys 1-3 of the six-key objective, grouped into TIERS. The kernel
        # takes the single best tier; with a filter we may have to look at the
        # next one, and never at more than we must.
        tiers: dict[tuple, list[tuple[tuple[int, ...], int]]] = {}
        for positions, size in survivors:
            tiers.setdefault(
                combination_prefix_key(case, positions, size), []
            ).append((positions, size))

        selection = None
        for prefix in sorted(tiers):
            finalists = []
            for positions, size in tiers[prefix]:
                ranked = rank_minimum_rationales(case, positions, policy,
                                                 objective)
                if ranked is None:
                    continue
                exact_size, level, rationales = ranked
                if admissible is not None:
                    rationales = [r for r in rationales
                                  if admissible(case, positions, r)]
                    if not rationales:
                        continue
                key = combination_objective_key(case, positions, exact_size,
                                                rationales[0], objective)
                finalists.append((key, positions, exact_size, level, rationales))
            if not finalists:
                continue
            finalists.sort(key=lambda item: item[0])
            key, positions, size, level, rationales = finalists[0]
            tied = sum(1 for item in finalists if item[0][3] == key[3])
            scores = [case.candidates[p].score for p in positions]
            selection = Selection(
                answer_uri=case.answer_uri,
                display_label=case.display_label,
                evidence_policy=policy,
                positions=positions,
                distractors=tuple(case.candidates[p] for p in positions),
                rationale=rationales[0],
                minimum_rationale_size=size,
                minimum_rationale_level=level,
                minimum_rationale_count_enumerated=len(rationales),
                lrolesim_score_sum=sum(scores),
                lrolesim_score_min=min(scores),
                candidate_rank_sum=sum(case.candidates[p].rank
                                       for p in positions),
                pool=pool,
                feasible_combination_count=len(survivors),
                combinations_tied_after_objective_key_4=tied,
                rationale_objective=objective,
            )
            break
        if selection is not None:
            return selection
    return None


@dataclass(frozen=True)
class GranularityCleanOutcome:
    """What the §6 policy did to one Answer, and what it could not do.

    ``selection`` is what the run should report. Under ``report-only`` it is
    always the kernel's own selection, unchanged. Under ``require-clean`` it is
    the clean selection when one exists, and otherwise it is STILL the kernel's
    selection — reported, flagged, and marked NOT learner-facing by
    ``learner_facing``. Hiding the item would destroy the measurement §6 asks
    for; publishing it as a reason would be the error §6 forbids.
    """

    status: str
    policy: GranularityRiskPolicy
    selection: Optional[Selection]
    baseline_selection: Optional[Selection]
    learner_facing: bool
    distractors_changed: bool
    rationale_changed: bool
    baseline_risk_incidences: int
    clean_risk_incidences: Optional[int]
    detail: str

    def as_record(self) -> dict:
        def facts(selection):
            if selection is None:
                return []
            return [f"{i}" for i in selection.rationale.fact_indices]

        return {
            "granularity_policy_status": self.status,
            **self.policy.as_record(),
            "learner_facing_under_policy": self.learner_facing,
            "distractors_changed": self.distractors_changed,
            "rationale_changed": self.rationale_changed,
            "baseline_granularity_risk_incidences":
                self.baseline_risk_incidences,
            "selected_granularity_risk_incidences": self.clean_risk_incidences,
            "baseline_rationale_fact_indices": facts(self.baseline_selection),
            "selected_rationale_fact_indices": facts(self.selection),
            "detail": self.detail,
        }


def apply_granularity_policy(
    case: AnswerCase,
    baseline: Optional[Selection],
    *,
    policy: GranularityRiskPolicy = REPORT_ONLY_POLICY,
    pool_policy: PoolPolicy = DEFAULT_POOL_POLICY,
    force_pool: bool = False,
    objective: str = DEFAULT_RATIONALE_OBJECTIVE,
) -> GranularityCleanOutcome:
    """Apply the §6 switch to one Answer's kernel selection.

    ``baseline`` is what `mcq_inputs.build_and_select()` already produced under
    the same pool policy and the same objective. Under ``report-only`` nothing
    is recomputed and nothing is changed — the function only reports whether the
    kernel's own choice carries a risk.

    Under ``require-clean`` the search is re-run with the admissibility
    predicate. Three outcomes, kept apart:

      * the baseline was already clean — nothing to do, and no re-search is run;
      * a clean selection exists — it is reported, together with whether the
        DISTRACTORS moved or only the rationale did;
      * no clean selection exists anywhere in the search scope — the baseline is
        returned with ``learner_facing=False`` and the explicit status
        ``NO_GRANULARITY_CLEAN_MAIN_RATIONALE``. Nothing is invented and no
        weaker evidence policy is substituted.
    """
    if baseline is None:
        return GranularityCleanOutcome(
            status=STATUS_NO_RISK_PRESENT, policy=policy, selection=None,
            baseline_selection=None, learner_facing=False,
            distractors_changed=False, rationale_changed=False,
            baseline_risk_incidences=0, clean_risk_incidences=None,
            detail="no kernel selection exists, so the granularity policy has "
                   "nothing to act on")

    baseline_risk = baseline.rationale.granularity_risk_incidences
    if not policy.requires_clean or policy.admits(case, baseline.positions,
                                                  baseline.rationale):
        return GranularityCleanOutcome(
            status=STATUS_NO_RISK_PRESENT, policy=policy, selection=baseline,
            baseline_selection=baseline, learner_facing=True,
            distractors_changed=False, rationale_changed=False,
            baseline_risk_incidences=baseline_risk,
            clean_risk_incidences=baseline_risk,
            detail=("the selected rationale is already admissible under this "
                    "policy; no re-search was run"))

    clean = select_with_rationale_filter(
        case, pool_policy, force_pool, objective,
        admissible=policy.admits)
    if clean is None:
        return GranularityCleanOutcome(
            status=STATUS_NO_GRANULARITY_CLEAN_RATIONALE, policy=policy,
            selection=baseline, baseline_selection=baseline,
            learner_facing=False, distractors_changed=False,
            rationale_changed=False, baseline_risk_incidences=baseline_risk,
            clean_risk_incidences=None,
            detail=("no combination in the search scope has a "
                    "minimum-cardinality rationale free of granularity risk. "
                    "The item is reported with its risky rationale and is NOT "
                    "learner-facing under require-clean. No fact was invented, "
                    "no evidence level was changed and no weaker evidence "
                    "policy was substituted."))
    return GranularityCleanOutcome(
        status=STATUS_CLEAN_SELECTION_FOUND, policy=policy, selection=clean,
        baseline_selection=baseline, learner_facing=True,
        distractors_changed=(tuple(d.uri for d in clean.distractors)
                             != tuple(d.uri for d in baseline.distractors)),
        rationale_changed=(clean.rationale.fact_identities
                           != baseline.rationale.fact_identities),
        baseline_risk_incidences=baseline_risk,
        clean_risk_incidences=clean.rationale.granularity_risk_incidences,
        detail=("a granularity-risk-free rationale exists at the same "
                "admissible search level and was selected under the declared "
                "versioned objective"))
