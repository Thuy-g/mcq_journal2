############################################################################
# src/pipeline/phase_b2_any_answer_run_v4.py
#
# Prompt 8H-B2-G orchestration helpers — the FINAL-BENCHMARK CANDIDATE runner.
#
# WHAT THIS MODULE IS, AND WHAT IT REFUSES TO BE
# -----------------------------------------------
# `src/pipeline/phase_b2_any_answer_run_v3.py` (B2-E/B2-F) is NOT modified and
# NOT replaced. It produced the published B2-E/F evidence and its defaults are
# the fingerprint of those results. This module IMPORTS it and adds the eight
# things Prompt 8H-B2-G asks for:
#
#   1.  a v4 runner configuration whose CANDIDATE defaults differ from v3 in
#       exactly three recorded places — rationale objective v3 (§7), M1
#       `max_nodes = 5000` (§8) and an audited predicate-slot alias policy (§5);
#   2.  the third candidate-validity policy `PERSON_GUARDED` (§2), offered
#       beside `OBSERVE_ONLY` and `PERSON_STRICT` and NOT declared the default;
#   3.  candidate metrics that separate DETECTION from REJECTION (§3);
#   4.  the versioned granularity-risk switch `report-only` / `require-clean`
#       (§6), applied outside the frozen kernel;
#   5.  an M1 graph stage with an explicit budget and diagnostics that can
#       EXPLAIN `GRAPH_BUDGET_INSUFFICIENT_CANDIDATES` (§8);
#   6.  class-feature rejection records wired through to the batch report, so
#       the class-leak metric stops reporting a silent zero (§10);
#   7.  a SECOND, learner-showable LRoleSim rank-retention denominator
#       `L1+ = MCQ-L1 u MCQ-L2`, beside the existing any-kernel-selection one
#       which is kept unchanged (§11);
#   8.  a batch table and metric set in which `|R*|` has its own column and no
#       scientific quantity shares a cell with truncatable free text (§12).
#
# EVERY SCIENTIFIC DECISION STILL BELONGS SOMEWHERE ELSE and is delegated
# unchanged: identity, class ranking, member retrieval, local mapping, the M1
# graph budget, LRoleSim, the semantic index, evidence classification, the exact
# minimum-cardinality set cover and the six-key objective. Nothing in this file
# classifies, ranks or selects.
#
# NOTHING HERE IS A PUBLICATION DEFAULT. Prompt 8H-B2-G exists to produce the
# EVIDENCE a human researcher needs in order to choose the final configuration.
# The word "candidate" in every name below is meant literally.
#
# IMPORT-TIME PURITY: no network, no pickle load, no model load, no file write.
############################################################################

from __future__ import annotations

import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import mcq_core                                                     # noqa: E402
from classes.candidate_validity import (                            # noqa: E402
    DEFAULT_CANDIDATE_VALIDITY_POLICY,
    PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY,
    PERSON_STRICT_CANDIDATE_VALIDITY_POLICY,
    REJECT_ANSWER_NAME_CONTAINED,
    REJECT_TYPE_NOT_PERSON,
    REJECT_TYPE_UNKNOWN,
    REJECTED_BY_NAME_RULE,
    REJECTED_BY_TYPE_RULE,
    TYPE_NOT_PERSON,
    TYPE_PERSON,
    TYPE_POLICY_OBSERVE_ONLY,
    TYPE_POLICY_PERSON_GUARDED,
    TYPE_POLICY_PERSON_STRICT,
    TYPE_UNKNOWN,
    CandidateValidityPolicy,
)
from classes.class_leakage import (                                 # noqa: E402
    DEFAULT_DERIVATIONAL_POLICY,
    DERIVATIONAL_POLICY_V2,
    DerivationalPolicy,
)
from kg.graph_view import (                                        # noqa: E402
    GRAPH_BUDGET_OK,
    collect_complete_one_hop,
)
from pipeline import phase_b2_any_answer_run_v3 as v3               # noqa: E402
from pipeline.graph_lrolesim_run import (                           # noqa: E402
    ATTEMPT_GRAPH_FEASIBLE,
    GRAPH_GATE_MIN_CANDIDATES,
    GRAPH_MAX_CANDIDATES,
    GRAPH_MAX_NODES,
    GraphStageResult,
    ScoreCache,
    SourceHashes,
    attempt_class_graph,
    rank_graph,
)
from rationale_v3.predicate_aliases import (                        # noqa: E402
    DEFAULT_ALIAS_POLICY,
    NO_ALIAS_POLICY,
    PredicateAliasPolicy,
)
from selection.granularity_clean import (                           # noqa: E402
    GRANULARITY_POLICY_REPORT_ONLY,
    GRANULARITY_POLICY_REQUIRE_CLEAN,
    REPORT_ONLY_POLICY,
    REQUIRE_CLEAN_POLICY,
    STATUS_CLEAN_SELECTION_FOUND,
    STATUS_NO_GRANULARITY_CLEAN_RATIONALE,
    GranularityRiskPolicy,
)

__all__ = [
    "ANY_ANSWER_V4_SCHEMA_VERSION",
    "V4_GRAPH_MAX_NODES",
    "RunnerConfigV4",
    "V4_CANDIDATE_RUNNER_CONFIG",
    "V3_COMPATIBLE_RUNNER_CONFIG",
    "CANDIDATE_VALIDITY_POLICIES",
    "GRAPH_BUDGET_LOST_REASONS",
    "build_graph_and_rank_v4",
    "graph_budget_diagnostics",
    "graph_row_with_effective_budget",
    "class_rejection_records",
    "class_rejection_metrics",
    "candidate_screen_metrics",
    "lrolesim_rank_retention",
    "batch_metrics_v4",
    "metrics_markdown_v4",
    "metrics_csv_rows_v4",
    "summary_table_v4",
]

ANY_ANSWER_V4_SCHEMA_VERSION = "phase_b2_any_answer_v4"

#: Prompt 8H-B2-G §8. The v4 CANDIDATE node budget. The frozen v1/v2/v3 value
#: (`kg.graph_view.DEFAULT_MAX_NODES` = 1200) is NOT changed: every published
#: result was produced under it and its fingerprint must stay reproducible.
#: 5000 is a PARAMETER of the v4 configuration, recorded in the manifest, and
#: the 1200-vs-5000 comparison is measured rather than asserted.
V4_GRAPH_MAX_NODES = 5000

#: The three candidate-validity policies, by CLI name. All three are shipped and
#: measured; which becomes the publication default is the researcher's decision.
CANDIDATE_VALIDITY_POLICIES = {
    "observe-only": DEFAULT_CANDIDATE_VALIDITY_POLICY,
    "person-guarded": PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY,
    "person-strict": PERSON_STRICT_CANDIDATE_VALIDITY_POLICY,
}

#: The three ways the M1 node budget can refuse a candidate. Kept apart because
#: only the FIRST of them is repaired by raising `max_nodes`.
GRAPH_BUDGET_LOST_REASONS = (
    "WOULD_EXCEED_MAX_NODES",
    "NOT_CONSIDERED_ANSWER_BASE_EXCEEDS_BUDGET",
    "NOT_CONSIDERED_CANDIDATE_CAP_REACHED",
)


# ==========================================================================
# 1) The versioned v4 runner configuration
# ==========================================================================


@dataclass(frozen=True)
class RunnerConfigV4:
    """Every VERSIONED policy choice one v4 run makes, in one recorded object.

    It extends `v3.RunnerConfigV3` by composition rather than inheritance so
    that the v3 record shape stays exactly what the B2-E/F artifacts contain,
    and so that a v4 manifest can print BOTH the inherited v3 block and the four
    fields v4 adds.

    Every field is a value, never a module default that happens to be in force:
    "which science ran" must be readable from the manifest, not inferred from
    which commit was checked out.
    """

    base: v3.RunnerConfigV3
    #: §8. The M1 node budget this run declares.
    graph_max_nodes: int = V4_GRAPH_MAX_NODES
    graph_max_candidates: int = GRAPH_MAX_CANDIDATES
    #: §5. The audited predicate-slot alias families used for evidence lookup.
    alias_policy: PredicateAliasPolicy = DEFAULT_ALIAS_POLICY
    #: §6. report-only or require-clean.
    granularity_policy: GranularityRiskPolicy = REPORT_ONLY_POLICY

    @property
    def rationale_objective(self) -> str:
        return self.base.rationale_objective

    @property
    def candidate_validity_policy(self) -> CandidateValidityPolicy:
        return self.base.candidate_validity_policy

    @property
    def derivational_policy(self) -> DerivationalPolicy:
        return self.base.derivational_policy

    @property
    def predicate_policy_path(self) -> Path:
        return self.base.predicate_policy_path

    @property
    def semantic_policy_path(self) -> Path:
        return self.base.semantic_policy_path

    def as_record(self) -> dict:
        return {
            **self.base.as_record(),
            # v4 last, so the v4 schema version is the one a reader sees; the
            # inherited v3 value stays available under its own key.
            "schema_version": ANY_ANSWER_V4_SCHEMA_VERSION,
            "inherited_v3_schema_version": v3.ANY_ANSWER_V3_SCHEMA_VERSION,
            "graph_max_nodes": self.graph_max_nodes,
            "graph_max_candidates": self.graph_max_candidates,
            "graph_max_nodes_frozen_v3_value": GRAPH_MAX_NODES,
            "predicate_alias_policy": self.alias_policy.as_record(),
            "granularity_risk_policy": self.granularity_policy.as_record(),
            "publication_status": (
                "CANDIDATE CONFIGURATION FOR EVIDENCE GATHERING. Prompt "
                "8H-B2-G explicitly does not declare a publication-final "
                "policy; this record exists so the researcher can compare arms."
            ),
        }


#: The v4 CANDIDATE configuration. It differs from `v3.DEFAULT_RUNNER_CONFIG` in
#: exactly three places, each demanded by a numbered section of Prompt 8H-B2-G:
#:
#:   §7  rationale objective v3        (v3 runner defaults to objective v2)
#:   §8  M1 max_nodes = 5000           (v3 runner uses the frozen 1200)
#:   §5  the audited field/fields alias family (v3 runner uses exact keys only)
#:
#: The candidate-validity policy stays OBSERVE_ONLY and the granularity policy
#: stays report-only, because §2 and §6 both say the decision is not to be made
#: in this task.
V4_CANDIDATE_RUNNER_CONFIG = RunnerConfigV4(
    base=v3.RunnerConfigV3(
        predicate_policy_path=v3.POLICY_PATHS["predicate_policy_v2"],
        semantic_policy_path=v3.POLICY_PATHS["semantic_relation_policy_v2"],
        derivational_policy=DERIVATIONAL_POLICY_V2,
        candidate_validity_policy=DEFAULT_CANDIDATE_VALIDITY_POLICY,
        rationale_objective=mcq_core.RATIONALE_OBJECTIVE_V3,
    ),
    graph_max_nodes=V4_GRAPH_MAX_NODES,
    alias_policy=DEFAULT_ALIAS_POLICY,
    granularity_policy=REPORT_ONLY_POLICY,
)

#: The configuration that reproduces a Prompt 8H-B2-E/F v3 run exactly, through
#: the v4 code path. It is what every "before" arm of a delta audit names, and
#: its existence is what makes "the v4 code changed nothing by itself" testable.
V3_COMPATIBLE_RUNNER_CONFIG = RunnerConfigV4(
    base=v3.DEFAULT_RUNNER_CONFIG,
    graph_max_nodes=GRAPH_MAX_NODES,
    alias_policy=NO_ALIAS_POLICY,
    granularity_policy=REPORT_ONLY_POLICY,
)


# ==========================================================================
# 2) §8 — the M1 graph stage with an EXPLICIT budget and real diagnostics
# ==========================================================================


def build_graph_and_rank_v4(
    walk,
    local_kg,
    *,
    display_label: str,
    score_cache_path,
    max_nodes: int = V4_GRAPH_MAX_NODES,
    max_candidates: int = GRAPH_MAX_CANDIDATES,
    min_candidates: int = GRAPH_GATE_MIN_CANDIDATES,
    pilot_slot: int = 0,
    progress=None,
):
    """`phase_b2_answer_run.build_graph_and_rank()` with a DECLARED node budget.

    The historical function is not modified: it hard-codes the frozen 1200-node
    budget, which is exactly what a reproduction of the published runs needs.
    This one takes the budget as an argument and returns a sixth value, the
    budget DIAGNOSTICS, which exist even when the graph stage fails — the
    historical function drops the `M1Graph` on failure, so nothing downstream
    could say WHY `GRAPH_BUDGET_INSUFFICIENT_CANDIDATES` happened.

    Every scientific step is the frozen one, called unmodified:
    `attempt_class_graph()` for the M1 policy and `rank_graph()` for the frozen
    `lrolesim_m1_fixed_k3` / `lrolesim_ed` / beta 0.2 / 3 fixed iterations.
    LRoleSim's mathematical definition and its Journal-2 configuration are
    untouched; only how many nodes the graph may hold is a parameter.

    Returns `(attempt, graph_result, scored, fingerprint, provenance,
    diagnostics)`.
    """
    from pipeline.phase_b2_answer_run import mapping_facts_for_graph_stage

    say = progress or (lambda message: None)
    facts = mapping_facts_for_graph_stage(walk, pilot_slot=pilot_slot)
    say(f"  M1 graph: offering {len(facts.accepted)} mapped candidates "
        f"(max_candidates={max_candidates}, max_nodes={max_nodes}, "
        f"min retained={min_candidates})")
    attempt, m1_graph, order = attempt_class_graph(
        facts, local_kg, max_candidates=max_candidates, max_nodes=max_nodes,
        min_candidates=min_candidates)
    diagnostics = graph_budget_diagnostics(
        attempt, m1_graph, order, local_kg=local_kg,
        answer_index=facts.answer_local_index)
    say(f"        -> {attempt.outcome}: {attempt.accepted_candidate_count} "
        f"retained, {attempt.retained_node_count} nodes, "
        f"{attempt.retained_edge_count} edges")
    if attempt.outcome != ATTEMPT_GRAPH_FEASIBLE:
        say(f"        budget diagnostics: {diagnostics['explanation']}")
        return attempt, None, (), None, {}, diagnostics

    result = GraphStageResult(
        pilot_slot=pilot_slot,
        answer_uri=walk.answer_uri,
        display_label=display_label,
        answer_local_index=walk.answer_local_index,
        mapping_stage_status=walk.status,
        graph_stage_status=ATTEMPT_GRAPH_FEASIBLE,
        selected_class_position=facts.class_position,
        selected_class_uri=walk.selected_class_uri,
        attempts=(attempt,),
        m1_graph=m1_graph,
        order=order,
    )
    cache = ScoreCache(score_cache_path).load()
    scored, fingerprint, provenance = rank_graph(
        result, local_kg, cache, SourceHashes.collect())
    say(f"  LRoleSim: {len(scored)} ranked candidates, "
        f"score_source={provenance.get('score_source')}, "
        f"iterations_run={provenance.get('iterations_run')}")
    return attempt, result, scored, fingerprint, provenance, diagnostics


def graph_budget_diagnostics(attempt, m1_graph, order, *, local_kg=None,
                             answer_index=None) -> dict:
    """WHY the node budget admitted what it admitted — and what it cost.

    `GRAPH_BUDGET_INSUFFICIENT_CANDIDATES` has three entirely different causes
    and only one of them is repaired by raising `max_nodes`:

      * candidates that WOULD_EXCEED_MAX_NODES — these are the ones a larger
        budget recovers, and their count is the honest measure of what the
        budget cost this Answer;
      * candidates never considered because the ANSWER'S OWN one-hop
        neighbourhood already overran the budget — a larger candidate budget
        does nothing at all here, and no class choice can help either;
      * candidates never considered because the candidate CAP was already full —
        a larger NODE budget changes nothing.

    EVERYTHING IS READ, NOTHING IS WRITTEN. `src/pipeline/graph_lrolesim_run.py`
    and `src/kg/graph_view.py` are PROTECTED SOURCES whose SHA-256 is pinned by
    `rationale_v3_run.PROTECTED_SOURCE_PINS`; they are not modified to expose a
    field. Every number below comes from the frozen `GraphBudgetResult` the
    frozen builder already returns, and the Answer's base size is recomputed
    with the frozen helper `kg.graph_view.collect_complete_one_hop()` — the same
    function the budget itself charges with — so the two cannot drift.

    The record is produced for a SUCCESSFUL attempt too, because "the budget was
    never binding" is exactly as informative as "the budget was binding".
    """
    lost = Counter()
    budget = None if m1_graph is None else m1_graph.budget
    if budget is not None:
        for record in budget.candidate_records:
            if record.rejection_reason:
                lost[record.rejection_reason] += 1

    over = lost.get("WOULD_EXCEED_MAX_NODES", 0)
    base_blocked = lost.get("NOT_CONSIDERED_ANSWER_BASE_EXCEEDS_BUDGET", 0)
    cap_blocked = lost.get("NOT_CONSIDERED_CANDIDATE_CAP_REACHED", 0)

    effective_max_nodes = (GRAPH_MAX_NODES if budget is None
                           else budget.max_nodes)
    effective_max_candidates = (GRAPH_MAX_CANDIDATES if budget is None
                                else budget.max_candidates)
    base_exceeds = bool(budget is not None and budget.answer_base_exceeds_budget)
    base_nodes = _answer_base_node_count(answer_index, local_kg)

    if attempt.outcome == ATTEMPT_GRAPH_FEASIBLE and not attempt.node_budget_bound:
        explanation = ("the node budget was never binding: every ordered "
                       "candidate that was considered fitted completely")
    elif base_exceeds:
        explanation = (
            f"the Answer's own complete one-hop neighbourhood is {base_nodes} "
            f"nodes, which alone exceeds max_nodes={effective_max_nodes}; no "
            f"candidate could be admitted with complete coverage, and "
            f"{base_blocked} candidate(s) were therefore never considered. No "
            f"CLASS choice can repair this at this budget")
    elif over:
        explanation = (
            f"{over} candidate(s) were refused because admitting their complete "
            f"one-hop neighbourhood would exceed max_nodes="
            f"{effective_max_nodes}; the Answer base alone is {base_nodes} "
            f"nodes. These are the candidates a larger node budget would "
            f"recover")
    elif cap_blocked:
        explanation = (
            f"{cap_blocked} candidate(s) were not considered because the "
            f"{effective_max_candidates}-candidate cap was already full; a "
            f"larger NODE budget would not change this")
    else:
        explanation = ("no candidate was refused by the node budget; if the "
                       "attempt failed, the cause is upstream of the budget")

    return {
        "outcome": attempt.outcome,
        "effective_max_nodes": effective_max_nodes,
        "effective_max_candidates": effective_max_candidates,
        "frozen_v3_max_nodes": GRAPH_MAX_NODES,
        "graph_min_candidates": GRAPH_GATE_MIN_CANDIDATES,
        "candidates_offered_to_m1": attempt.ordered_candidate_count,
        "candidates_retained": attempt.accepted_candidate_count,
        "m1_node_count": attempt.retained_node_count,
        "m1_edge_count": attempt.retained_edge_count,
        "answer_base_node_count": base_nodes,
        "answer_base_exceeds_budget": base_exceeds,
        "node_budget_bound": attempt.node_budget_bound,
        "candidate_cap_reached": attempt.candidate_cap_reached,
        "lost_would_exceed_max_nodes": over,
        "lost_answer_base_exceeds_budget": base_blocked,
        "lost_candidate_cap_reached": cap_blocked,
        "lost_total": over + base_blocked + cap_blocked,
        "lost_by_reason": {reason: lost.get(reason, 0)
                           for reason in GRAPH_BUDGET_LOST_REASONS},
        "other_rejections": {reason: count for reason, count in sorted(lost.items())
                             if reason not in GRAPH_BUDGET_LOST_REASONS},
        "explanation": explanation,
    }


def _answer_base_node_count(answer_index, local_kg) -> int:
    """|{Answer} u N(Answer)| — what the Answer charges to the node budget.

    Computed with the frozen helper the budget itself uses, so the number
    reported here and the number the budget charged cannot drift. Returns 0 when
    the caller supplied no graph, which is the diagnostics-only path.
    """
    if answer_index is None or local_kg is None:
        return 0
    profile = collect_complete_one_hop(answer_index, local_kg.in_neighbor,
                                       local_kg.out_neighbor)
    return 1 + len(profile.neighbors)


def graph_row_with_effective_budget(attempt, diagnostics) -> dict:
    """`attempt.as_row()` with the two budget columns telling the truth.

    `ClassGraphAttempt.as_row()` writes the MODULE CONSTANTS into `max_nodes`
    and `max_candidates`, because it is the frozen Week-2 artifact writer and
    its file is a PROTECTED SOURCE. A v4 run that declared a different budget
    would otherwise publish a row saying 1200. Only those two values are
    replaced, and only in the copy v4 stores; no key is added or removed, so the
    row shape stays exactly what every existing reader expects.
    """
    row = dict(attempt.as_row())
    row["max_nodes"] = diagnostics["effective_max_nodes"]
    row["max_candidates"] = diagnostics["effective_max_candidates"]
    return row


# ==========================================================================
# 3) §10 — class-feature rejections, wired through so nothing reports zero
# ==========================================================================


def class_rejection_records(features) -> tuple[dict, ...]:
    """One record per REJECTED class of one Answer's v6 feature extraction.

    THE DEFECT THIS REPAIRS. The v3 batch metric computed

        hard_class_leak_rejections = sum(
            sum(1 for entry in r.class_ranking_rejections)
            for r in results if hasattr(r, "class_ranking_rejections"))

    and `AnswerRunResult` has no `class_ranking_rejections` attribute at all. The
    `hasattr` guard therefore excluded EVERY result and the metric published a
    hard zero that looked like a scientific finding. The repair is to carry the
    real records, and the test that proves it is one that FAILS if the attribute
    disappears again rather than silently reporting zero.

    A class that failed several gates keeps ONE declared primary status —
    `rejected_code`, the first gate that fired in the declared gate order — and
    every independent reason stays inspectable in `rejection_reasons`. Leakage is
    annotated independently of the size gates, so `leak_level` is the true
    verdict even for a class rejected earlier for being too small.
    """
    records = []
    for feature in getattr(features, "rejected_classes", ()):
        records.append({
            "category_uri": feature.category_uri,
            "category_label": feature.category_label,
            "primary_rejected_code": feature.rejected_code,
            "rejected_reason": feature.rejected_reason,
            "all_rejection_reasons": list(feature.rejection_reasons),
            "leak_level": getattr(feature.leak_level, "value",
                                  feature.leak_level),
            "leak_status": getattr(feature.leak_status, "value",
                                   feature.leak_status),
            "leak_source": feature.leak_source,
            "leak_reason": feature.leak_reason,
            "leak_evidence": list(feature.leak_evidence),
            "r1_leak_level": getattr(feature.r1_leak_level, "value",
                                     feature.r1_leak_level),
            "class_rule_leak_evidence": list(feature.class_rule_leak_evidence),
            "remote_count": feature.remote_count,
            "eligible_remote_count": feature.eligible_remote_count,
        })
    return tuple(records)


def class_rejection_metrics(results: Sequence) -> dict:
    """§10's corrected class-ranking metrics, over every Answer in the batch.

    `answers_with_rejection_records` is reported next to every count for one
    reason: it is the number that exposes a wiring regression. If the records
    stop arriving the counts go to zero, and only this denominator says whether
    that means "no class was rejected" or "nobody was asked".
    """
    counts: Counter = Counter()
    all_reasons: Counter = Counter()
    hard_leak_any_reason = 0
    discovered = feasible = rejected = 0
    answers_with_records = 0
    for result in results:
        discovered += getattr(result, "categories_discovered", 0) or 0
        feasible += getattr(result, "feasible_class_count", 0) or 0
        rejected += getattr(result, "rejected_class_count", 0) or 0
        records = getattr(result, "class_ranking_rejections", None)
        if records is None:
            continue
        answers_with_records += 1
        for record in records:
            counts[record["primary_rejected_code"] or "unrecorded"] += 1
            for reason in record["all_rejection_reasons"]:
                all_reasons[reason] += 1
            if record["leak_level"] == "hard_leak":
                hard_leak_any_reason += 1
    return {
        "answers_in_batch": len(results),
        "answers_with_rejection_records": answers_with_records,
        "total_classes_discovered": discovered,
        "feasible_classes": feasible,
        "total_rejected_classes": rejected,
        "rejection_records_collected": int(sum(counts.values())),
        "hard_class_leak_rejections":
            counts.get("hard_leak", 0),
        "hard_leaking_classes_by_any_rejection_reason": hard_leak_any_reason,
        "too_small_rejections": counts.get("insufficient_remote_candidates", 0),
        "too_generic_rejections": counts.get("too_generic", 0),
        "junk_category_rejections": counts.get("junk_category", 0),
        "invalid_uri_rejections": counts.get("invalid_category_uri", 0),
        "count_unavailable_rejections":
            counts.get("remote_count_unavailable", 0),
        "primary_rejection_codes": dict(sorted(counts.items())),
        "all_independent_rejection_reasons": dict(sorted(all_reasons.items())),
        "note": ("`hard_class_leak_rejections` counts classes whose PRIMARY "
                 "gate was the hard leakage gate. "
                 "`hard_leaking_classes_by_any_rejection_reason` counts every "
                 "rejected class that hard-leaks, including ones a size gate "
                 "refused first. The two differ by design: leakage is annotated "
                 "independently of the size gates."),
    }


# ==========================================================================
# 4) §3 — candidate metrics that separate DETECTION from REJECTION
# ==========================================================================


def candidate_screen_metrics(screens: Sequence) -> dict:
    """What the candidate detectors OBSERVED, and what the policy REMOVED.

    THE DEFECT THIS REPAIRS. v3 published

        candidate_topical_identity_leak_rejections = 0

    for a run whose name detector had fired on every `Muhammad` /
    `Muhammad_in_Islam`-shaped pair, because the metric counted rejections and
    the active policy was OBSERVE_ONLY. Zero rejections was TRUE and zero
    detections was FALSE, and one number was carrying both meanings.

    Every count below is therefore named `_detected_` or `_rejected_`, and the
    two are computed from different fields of the same verdict:
    `name_containment_detected` / `detected_entity_type` are the detectors;
    `rejected_by_rule` is the policy. The old v3 field names are preserved with
    their old meaning so an existing reader does not silently change its mind.
    """
    detected_type: Counter = Counter()
    rejected_by_rule: Counter = Counter()
    reject_reasons: Counter = Counter()
    name_detected = 0
    name_rejected = 0
    type_rejected = 0
    rows = 0
    answer_types: Counter = Counter()
    for screen in screens:
        answer_types[screen.answer_type] += 1
        for verdict in screen.verdicts:
            rows += 1
            detected_type[verdict.detected_entity_type] += 1
            if verdict.name_containment_detected:
                name_detected += 1
            rule = verdict.rejected_by_rule
            rejected_by_rule[rule] += 1
            if verdict.reject_reason:
                reject_reasons[verdict.reject_reason] += 1
            if rule == REJECTED_BY_NAME_RULE:
                name_rejected += 1
            elif rule == REJECTED_BY_TYPE_RULE:
                type_rejected += 1
    return {
        "screens": len(screens),
        "candidate_rows_screened": rows,
        "answer_entity_types": dict(sorted(answer_types.items())),

        # --- DETECTION: what the detectors observed, policy-independent ---
        "candidate_type_person_detected_count": detected_type.get(TYPE_PERSON, 0),
        "candidate_type_not_person_detected_count":
            detected_type.get(TYPE_NOT_PERSON, 0),
        "candidate_type_unknown_detected_count":
            detected_type.get(TYPE_UNKNOWN, 0),
        "candidate_name_containment_detected_count": name_detected,

        # --- REJECTION: what the ACTIVE policy actually removed -----------
        "candidate_type_rejected_count": type_rejected,
        "candidate_name_containment_rejected_count": name_rejected,
        "candidates_rejected_total": type_rejected + name_rejected,
        "candidates_accepted_total": rows - (type_rejected + name_rejected),
        "rejected_by_rule": dict(sorted(rejected_by_rule.items())),
        "reject_reasons": dict(sorted(reject_reasons.items())),

        # --- backward compatibility with the v3 metric names --------------
        "candidate_type_rejections": type_rejected,
        "candidate_type_rejections_by_reason": {
            reason: reject_reasons.get(reason, 0)
            for reason in (REJECT_TYPE_NOT_PERSON, REJECT_TYPE_UNKNOWN)
            if reject_reasons.get(reason, 0)},
        "candidate_topical_identity_leak_rejections": name_rejected,

        "note": ("DETECTED and REJECTED are different measurements. Under "
                 "OBSERVE_ONLY every `_detected_` count can be positive while "
                 "every `_rejected_` count is zero, and that is the correct "
                 "report, not a contradiction."),
    }


# ==========================================================================
# 5) §11 — LRoleSim rank retention, with TWO explicit denominators
# ==========================================================================


def _describe(values: Sequence[float]) -> dict:
    """n / mean / median / min / max, or an explicit empty description."""
    if not values:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    ordered = sorted(values)
    return {"n": len(ordered),
            "mean": round(statistics.fmean(ordered), 4),
            "median": statistics.median(ordered),
            "min": ordered[0], "max": ordered[-1]}


def _retention_block(results: Sequence, denominator_name: str) -> dict:
    ranks = [[d.rank for d in r.selection.distractors] for r in results]
    exact = [row for row in ranks if row == [1, 2, 3]]
    flat = [rank for row in ranks for rank in row]
    slots = {i: [row[i] for row in ranks if len(row) > i] for i in range(3)}
    return {
        "denominator_name": denominator_name,
        "denominator": len(results),
        "exact_ranks_1_2_3": len(exact),
        "exact_ranks_1_2_3_pct": v3._pct(len(exact), len(results)),
        "all_selected_ranks": _describe(flat),
        "slot_1": _describe(slots[0]),
        "slot_2": _describe(slots[1]),
        "slot_3": _describe(slots[2]),
        "candidate_rank_sum": _describe([sum(row) for row in ranks]),
    }


def lrolesim_rank_retention(results: Sequence) -> dict:
    """§11. The existing any-kernel denominator PLUS a learner-showable one.

    TWO DENOMINATORS, NEVER ONE.

      any kernel selection   every Answer for which the kernel returned a
                             distractor triple and a rationale, INCLUDING the
                             diagnostic-L0 items. This is the v3 metric and it
                             is reported unchanged, because every published
                             number so far used it.

      L1+ = MCQ-L1 u MCQ-L2  the items a learner may actually be shown. L0 is
                             snapshot ABSENCE and is never student-showable
                             (EVIDENCE_TAXONOMY_V1 §2), so a rank-retention
                             figure quoted for "the questions we would publish"
                             must not include L0-only items.

    The two answer different questions and their percentages are not
    interchangeable. Nothing is hard-coded: both are recomputed from the
    supplied results every time.
    """
    any_selection = [r for r in results if r.selection is not None]
    l1_plus = [r for r in any_selection
               if r.mcq_evidence_level in ("MCQ-L1", "MCQ-L2")]
    return {
        "any_kernel_selection": _retention_block(
            any_selection, "any kernel selection (includes diagnostic L0)"),
        "l1_plus_student_showable": _retention_block(
            l1_plus, "L1+ = MCQ-L1 u MCQ-L2 (student-showable only)"),
        "n_L1_plus": len(l1_plus),
        "note": ("The L1+ block is the learner-showable denominator. The "
                 "any-kernel block is retained UNCHANGED so every earlier "
                 "number stays comparable. Neither is a claim that a "
                 "rank-1/2/3 triple is easy or hard for a human."),
    }


# ==========================================================================
# 6) The v4 batch metrics
# ==========================================================================


def batch_metrics_v4(results: Sequence, *,
                     config: Optional[RunnerConfigV4] = None,
                     screens: Sequence = ()) -> dict:
    """The v3 metric set, with §3, §6, §10 and §11 repaired or added.

    The v3 metrics are computed by `v3.batch_metrics()` and are NOT
    reimplemented: every existing definition, denominator and note stays
    literally the same object, so a v3-vs-v4 comparison is a comparison of the
    same quantities. v4 then REPLACES exactly the blocks that were wrong or
    missing and records what it replaced.
    """
    base = v3.batch_metrics(results, config=None, screens=())
    base["schema_version"] = ANY_ANSWER_V4_SCHEMA_VERSION
    base["runner_config"] = None if config is None else config.as_record()

    # §3 — detection vs rejection. The v3 block's own names are preserved
    # inside `candidate_screen`, so nothing that read them changes meaning.
    base["candidate_screen"] = candidate_screen_metrics(screens)

    # §10 — class-feature rejections, which v3 could only report as zero.
    base["class_rejections"] = class_rejection_metrics(results)

    # §11 — two rank-retention denominators. The v3 block is kept under its
    # original key so every earlier figure stays readable side by side.
    base["lrolesim_rank_retention_v4"] = lrolesim_rank_retention(results)

    # §6 — what the granularity policy did, if anything.
    base["granularity_policy"] = granularity_policy_metrics(results)

    # §12 — the |R*| column is structural, and this states the invariant the
    # batch table must satisfy so a truncation can never lose it again.
    any_selection = [r for r in results if r.selection is not None]
    base["rationale_cardinality_integrity"] = {
        "answers_with_selection": len(any_selection),
        "answers_with_recorded_cardinality": sum(
            1 for r in any_selection
            if r.selection.minimum_rationale_size is not None),
        "distribution": dict(sorted(Counter(
            r.selection.minimum_rationale_size for r in any_selection).items())),
        "note": ("|R*| lives in its own column of the batch table and in its "
                 "own metric field. It never shares a cell with free text, so "
                 "no display truncation can remove it. The v2 report's '57 of "
                 "329 rows show no |R*|' was a PRESENTATION defect in a "
                 "46-character cell, never 57 Answers failing to produce a "
                 "rationale."),
    }

    # The v3 pedagogical block's two candidate fields were the §3 defect. They
    # are kept (so nothing silently changes shape) and annotated in place.
    diagnostics = base.get("pedagogical_diagnostics", {})
    diagnostics["candidate_metric_superseded_note"] = (
        "candidate_type_rejections and candidate_topical_identity_leak_"
        "rejections count REJECTIONS ONLY and are zero under an observe-only "
        "run however often a detector fired. Use the `candidate_screen` block "
        "for the detection counts.")
    diagnostics["hard_class_leak_rejections"] = (
        base["class_rejections"]["hard_class_leak_rejections"])
    diagnostics["hard_class_leak_rejections_note"] = (
        "repaired in v4: the v3 expression was guarded by hasattr() on an "
        "attribute AnswerRunResult never had, so it always summed to zero")
    return base


def granularity_policy_metrics(results: Sequence) -> dict:
    """§6. What `require-clean` changed, and what it could not repair."""
    outcomes = [getattr(r, "granularity_outcome", None) for r in results]
    present = [o for o in outcomes if o is not None]
    by_status: Counter = Counter(o.status for o in present)
    changed_distractors = sum(1 for o in present if o.distractors_changed)
    changed_rationale = sum(1 for o in present if o.rationale_changed)
    blocked = [o for o in present
               if o.status == STATUS_NO_GRANULARITY_CLEAN_RATIONALE]
    return {
        "answers_with_a_granularity_outcome": len(present),
        "statuses": dict(sorted(by_status.items())),
        "clean_alternative_selected": by_status.get(
            STATUS_CLEAN_SELECTION_FOUND, 0),
        "no_clean_rationale_exists": len(blocked),
        "distractor_triples_changed": changed_distractors,
        "rationales_changed": changed_rationale,
        "note": ("Under report-only nothing is changed and every count here is "
                 "zero by construction. Under require-clean a risky rationale "
                 "is never converted to L0 and no fact is invented: an Answer "
                 "with no clean minimum-cardinality rationale is reported with "
                 "an explicit status and marked not learner-facing."),
    }


# ==========================================================================
# 7) Rendering
# ==========================================================================


def summary_table_v4(results: Sequence) -> str:
    """The v4 batch table: the v3 table plus a granularity-policy column.

    `|R*|` keeps its own column, exactly as in v3, and nothing in this table is
    truncated to a fixed width except free-text NAMES, never a number.
    """
    table = v3.summary_table_v3(results)
    lines = table.splitlines()
    if len(lines) < 2:
        return table
    lines[0] = lines[0].rstrip("|") + " Gran. |"
    lines[1] = lines[1] + "---|"
    for index, result in enumerate(results, start=2):
        outcome = getattr(result, "granularity_outcome", None)
        if outcome is None:
            cell = "-"
        elif outcome.status == STATUS_NO_GRANULARITY_CLEAN_RATIONALE:
            cell = "NO-CLEAN"
        elif outcome.status == STATUS_CLEAN_SELECTION_FOUND:
            cell = ("CLEANED(d)" if outcome.distractors_changed
                    else "CLEANED(r)")
        else:
            cell = "ok"
        if index < len(lines):
            lines[index] = lines[index].rstrip() + f" {cell} |"
    return "\n".join(lines)


def metrics_markdown_v4(metrics: Mapping) -> str:
    """The human-readable v4 metric report. Pure formatting, no computation."""
    def cell(value) -> str:
        return "N/A" if value is None else str(value)

    L: list[str] = [v3.metrics_markdown(metrics)]
    A = L.append

    A("### I. Candidate screen — DETECTED versus REJECTED (§3)")
    A("")
    screen = metrics["candidate_screen"]
    A(f"- screens: **{screen['screens']}**, candidate rows screened: "
      f"**{screen['candidate_rows_screened']}**")
    A(f"- Answer entity types: `{screen['answer_entity_types']}`")
    A("")
    A("| quantity | DETECTED | REJECTED |")
    A("|---|---:|---:|")
    A(f"| candidate type PERSON | "
      f"{screen['candidate_type_person_detected_count']} | — |")
    A(f"| candidate type NOT_PERSON | "
      f"{screen['candidate_type_not_person_detected_count']} | — |")
    A(f"| candidate type UNKNOWN | "
      f"{screen['candidate_type_unknown_detected_count']} | — |")
    A(f"| candidate type (any, removed by the type rule) | — | "
      f"{screen['candidate_type_rejected_count']} |")
    A(f"| complete-Answer-name containment | "
      f"{screen['candidate_name_containment_detected_count']} | "
      f"{screen['candidate_name_containment_rejected_count']} |")
    A(f"| total | {screen['candidate_rows_screened']} | "
      f"{screen['candidates_rejected_total']} |")
    A("")
    A(f"_{screen['note']}_")
    A("")

    A("### J. Class-ranking rejections (§10)")
    A("")
    classes = metrics["class_rejections"]
    A(f"- Answers in batch: **{classes['answers_in_batch']}**, of which "
      f"**{classes['answers_with_rejection_records']}** carried rejection "
      f"records (a zero here means the wiring broke, not that no class was "
      f"rejected)")
    A("")
    A("| quantity | count |")
    A("|---|---:|")
    for label, key in (
            ("total classes discovered", "total_classes_discovered"),
            ("feasible classes", "feasible_classes"),
            ("total rejected classes", "total_rejected_classes"),
            ("rejection records collected", "rejection_records_collected"),
            ("HARD class-leak rejects (primary gate)",
             "hard_class_leak_rejections"),
            ("hard-leaking rejected classes (any gate)",
             "hard_leaking_classes_by_any_rejection_reason"),
            ("too-small rejects", "too_small_rejections"),
            ("too-generic rejects", "too_generic_rejections"),
            ("junk-category rejects", "junk_category_rejections"),
            ("invalid-URI rejects", "invalid_uri_rejections"),
            ("count-unavailable rejects", "count_unavailable_rejections")):
        A(f"| {label} | {classes[key]} |")
    A("")
    A(f"- every independent reason: "
      f"`{classes['all_independent_rejection_reasons']}`")
    A("")
    A(f"_{classes['note']}_")
    A("")

    A("### K. LRoleSim rank retention — two denominators (§11)")
    A("")
    retention = metrics["lrolesim_rank_retention_v4"]
    for key in ("any_kernel_selection", "l1_plus_student_showable"):
        block = retention[key]
        A(f"**{block['denominator_name']}** — denominator "
          f"**{block['denominator']}**, exact ranks [1,2,3]: "
          f"**{block['exact_ranks_1_2_3']}** "
          f"({cell(block['exact_ranks_1_2_3_pct'])}%)")
        A("")
        A("| series | n | mean | median | min | max |")
        A("|---|---:|---:|---:|---:|---:|")
        for label, series in (("all selected ranks", "all_selected_ranks"),
                              ("slot 1", "slot_1"), ("slot 2", "slot_2"),
                              ("slot 3", "slot_3"),
                              ("candidate rank sum", "candidate_rank_sum")):
            entry = block[series]
            A(f"| {label} | {entry['n']} | {cell(entry['mean'])} "
              f"| {cell(entry['median'])} | {cell(entry['min'])} "
              f"| {cell(entry['max'])} |")
        A("")
    A(f"_{retention['note']}_")
    A("")

    A("### L. Granularity-risk policy (§6)")
    A("")
    gran = metrics["granularity_policy"]
    A(f"- Answers with a granularity outcome: "
      f"**{gran['answers_with_a_granularity_outcome']}**")
    A(f"- statuses: `{gran['statuses']}`")
    A(f"- clean alternative selected: **{gran['clean_alternative_selected']}** "
      f"(distractor triples changed: {gran['distractor_triples_changed']}, "
      f"rationales changed: {gran['rationales_changed']})")
    A(f"- no clean rationale exists: **{gran['no_clean_rationale_exists']}**")
    A("")
    A(f"_{gran['note']}_")
    A("")

    A("### M. |R*| integrity (§12)")
    A("")
    integrity = metrics["rationale_cardinality_integrity"]
    A(f"- Answers with a selection: "
      f"**{integrity['answers_with_selection']}**")
    A(f"- Answers with a recorded |R*|: "
      f"**{integrity['answers_with_recorded_cardinality']}**")
    A(f"- |R*| distribution: `{integrity['distribution']}`")
    A("")
    A(f"_{integrity['note']}_")
    A("")
    return "\n".join(L)


def metrics_csv_rows_v4(metrics: Mapping) -> list[dict]:
    """The v3 flat CSV rows plus every v4 block, same four-column shape."""
    rows = v3.metrics_csv_rows(metrics)

    def add(metric: str, value, denominator=None, note: str = "") -> None:
        rows.append({"metric": metric,
                     "value": "" if value is None else value,
                     "denominator": "" if denominator is None else denominator,
                     "note": note})

    screen = metrics["candidate_screen"]
    for key, value in screen.items():
        if isinstance(value, (int, float, str)) or value is None:
            add(f"candidate_screen.{key}", value,
                screen["candidate_rows_screened"])
    classes = metrics["class_rejections"]
    for key, value in classes.items():
        if isinstance(value, (int, float, str)) or value is None:
            add(f"class_rejections.{key}", value, classes["answers_in_batch"])
    retention = metrics["lrolesim_rank_retention_v4"]
    for block_key in ("any_kernel_selection", "l1_plus_student_showable"):
        block = retention[block_key]
        add(f"lrolesim_v4.{block_key}.denominator", block["denominator"])
        add(f"lrolesim_v4.{block_key}.exact_ranks_1_2_3",
            block["exact_ranks_1_2_3"], block["denominator"])
        add(f"lrolesim_v4.{block_key}.exact_ranks_1_2_3_pct",
            block["exact_ranks_1_2_3_pct"], block["denominator"])
        for series in ("all_selected_ranks", "slot_1", "slot_2", "slot_3",
                       "candidate_rank_sum"):
            for stat, value in block[series].items():
                add(f"lrolesim_v4.{block_key}.{series}.{stat}", value,
                    block["denominator"])
    gran = metrics["granularity_policy"]
    for key, value in gran.items():
        if isinstance(value, (int, float, str)) or value is None:
            add(f"granularity_policy.{key}", value,
                gran["answers_with_a_granularity_outcome"])
    integrity = metrics["rationale_cardinality_integrity"]
    add("rationale_cardinality_integrity.answers_with_selection",
        integrity["answers_with_selection"])
    add("rationale_cardinality_integrity.answers_with_recorded_cardinality",
        integrity["answers_with_recorded_cardinality"],
        integrity["answers_with_selection"], integrity["note"])
    return rows
