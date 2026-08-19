############################################################################
# src/pipeline/phase_b2_any_answer_run_v3.py
#
# Prompt 8H-B2-E / B2-F orchestration helpers for the v3 runner.
#
# WHAT THIS MODULE IS FOR, AND WHAT IT REFUSES TO BE
# ---------------------------------------------------
# `src/pipeline/phase_b2_any_answer_run.py` (v2) is NOT modified and NOT
# replaced: the 329-Answer development report was produced by it and remains
# historical evidence. This module IMPORTS it and adds exactly the six things
# Prompt 8H-B2-E asks for on top:
#
#   1. a VERSIONED runner configuration (§5, §7, §9, §10, §12) whose every
#      choice is recorded in the run manifest rather than compiled in;
#   2. the candidate-validity screen (§7 type compatibility, §8 answer-name
#      containment), applied BEFORE the M1 graph so a rejected candidate never
#      consumes a LRoleSim rank or an evidence classification;
#   3. `--print-facts-only` (§15): the complete raw pinned-KG fact inventory of
#      an Answer, grouped by (predicate, direction), with NO ranking, NO
#      LRoleSim, NO evidence and NO selection;
#   4. `--lines-for-input-file START-END` (§16): 1-based inclusive source-line
#      selection over an Answers.txt, cohorts still parsed from the whole file;
#   5. a batch table whose |R*| lives in its OWN COLUMN (§17), so the
#      cardinality can never be lost to a string truncation;
#   6. the rich batch metrics of §18 and the four distinct coverage concepts of
#      §19.
#
# EVERY SCIENTIFIC DECISION STILL BELONGS SOMEWHERE ELSE and is delegated
# unchanged: identity, class ranking, member retrieval, local mapping, the M1
# graph, LRoleSim, the semantic index, evidence classification, set cover and
# the six-key objective. Nothing in this file classifies, ranks or selects.
#
# IMPORT-TIME PURITY: no network, no pickle load, no model load, no file write.
############################################################################

from __future__ import annotations

import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import mcq_core                                                     # noqa: E402
from classes.candidate_validity import (                            # noqa: E402
    DEFAULT_CANDIDATE_VALIDITY_POLICY,
    PERSON_STRICT_CANDIDATE_VALIDITY_POLICY,
    TYPE_POLICY_OBSERVE_ONLY,
    TYPE_POLICY_PERSON_STRICT,
    CandidateValidityPolicy,
    CandidateValidityVerdict,
    classify_entity_type,
    screen_candidate,
)
from classes.class_leakage import (                                 # noqa: E402
    DEFAULT_DERIVATIONAL_POLICY,
    DERIVATIONAL_POLICY_V2,
    DerivationalPolicy,
)
from pipeline import phase_b2_any_answer_run as anyb2               # noqa: E402
from selection.observed_facts import (                              # noqa: E402
    DIRECTION_LABEL,
    observed_edge_set,
)
from rationale_v3.semantic_relations import normalize_uri           # noqa: E402

__all__ = [
    "ANY_ANSWER_V3_SCHEMA_VERSION",
    "POLICY_PATHS",
    "RunnerConfigV3",
    "DEFAULT_RUNNER_CONFIG",
    "LineRangeError",
    "parse_line_range",
    "rows_in_line_range",
    "raw_fact_groups",
    "render_raw_facts",
    "screen_candidate_pool",
    "CandidateScreenResult",
    "summary_table_v3",
    "prose_summary_v3",
    "batch_metrics",
    "metrics_markdown",
    "metrics_csv_rows",
]

ANY_ANSWER_V3_SCHEMA_VERSION = "phase_b2_any_answer_v3"

#: Where the two policy generations live. Both are shipped; a run names one.
POLICY_PATHS = {
    "predicate_policy_v1": SRC_DIR / "rationale_v3" / "policies"
                           / "predicate_policy.json",
    "predicate_policy_v2": SRC_DIR / "rationale_v3" / "policies"
                           / "predicate_policy_v2.json",
    "semantic_relation_policy_v1": SRC_DIR / "rationale_v3" / "policies"
                                   / "semantic_relation_policy.json",
    "semantic_relation_policy_v2": SRC_DIR / "rationale_v3" / "policies"
                                   / "semantic_relation_policy_v2.json",
}


# ==========================================================================
# 1) The versioned runner configuration
# ==========================================================================


@dataclass(frozen=True)
class RunnerConfigV3:
    """Every VERSIONED policy choice one v3 run makes, in one recorded object.

    The point is that "which science ran" is a value a manifest can print, not
    a property of which commit happened to be checked out. Each field names a
    generation that also exists in its predecessor form, so a v3 run can
    reproduce the v2 run exactly by naming the v1 generation everywhere — which
    is what the delta audits do.
    """

    predicate_policy_path: Path
    semantic_policy_path: Path
    derivational_policy: DerivationalPolicy
    candidate_validity_policy: CandidateValidityPolicy
    rationale_objective: str

    def as_record(self) -> dict:
        return {
            "schema_version": ANY_ANSWER_V3_SCHEMA_VERSION,
            "predicate_policy_path": str(self.predicate_policy_path),
            "semantic_relation_policy_path": str(self.semantic_policy_path),
            "rationale_objective": self.rationale_objective,
            "class_leakage_policy": self.derivational_policy.as_record(),
            "candidate_validity_policy":
                self.candidate_validity_policy.as_record(),
        }


DEFAULT_RUNNER_CONFIG = RunnerConfigV3(
    predicate_policy_path=POLICY_PATHS["predicate_policy_v2"],
    semantic_policy_path=POLICY_PATHS["semantic_relation_policy_v2"],
    derivational_policy=DERIVATIONAL_POLICY_V2,
    candidate_validity_policy=DEFAULT_CANDIDATE_VALIDITY_POLICY,
    rationale_objective=mcq_core.RATIONALE_OBJECTIVE_V2,
)

#: The configuration that reproduces the Prompt 8H-B2-D run exactly.
V2_COMPATIBLE_RUNNER_CONFIG = RunnerConfigV3(
    predicate_policy_path=POLICY_PATHS["predicate_policy_v1"],
    semantic_policy_path=POLICY_PATHS["semantic_relation_policy_v1"],
    derivational_policy=DEFAULT_DERIVATIONAL_POLICY,
    candidate_validity_policy=DEFAULT_CANDIDATE_VALIDITY_POLICY,
    rationale_objective=mcq_core.RATIONALE_OBJECTIVE_V1,
)


# ==========================================================================
# 2) §16 — the input line range
# ==========================================================================


class LineRangeError(ValueError):
    """`--lines-for-input-file` was malformed or inconsistent."""


_RANGE_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


def parse_line_range(text: str) -> tuple[int, int]:
    """``"11-33"`` -> ``(11, 33)``. 1-based and INCLUSIVE at both ends.

    Every rejection is explicit rather than silently coerced, because a range
    that quietly became something else would change which Answers a published
    number was computed over:

      * anything that is not ``START-END`` is refused;
      * ``START`` below 1 is refused — the file's first line is line 1;
      * ``START > END`` is refused rather than swapped.

    A range that simply selects no Answer row is NOT an error here; it is a run
    with zero Answers, and the caller reports it as such.
    """
    match = _RANGE_RE.match(str(text))
    if not match:
        raise LineRangeError(
            f"--lines-for-input-file expects START-END with two integers, "
            f"got {text!r}")
    start, end = int(match.group(1)), int(match.group(2))
    if start < 1:
        raise LineRangeError(
            f"--lines-for-input-file START must be at least 1 (the file's first "
            f"line is line 1), got {start}")
    if start > end:
        raise LineRangeError(
            f"--lines-for-input-file requires START <= END, got {start}-{end}; "
            f"the range is not silently swapped")
    return start, end


def rows_in_line_range(parsed, line_range: Optional[tuple[int, int]]):
    """The Answer rows to EXECUTE, and the cohort each one was written under.

    The WHOLE file is always parsed, which is what §16 asks for and what makes
    the cohort of a selected line knowable: a ``#COHORT:`` marker above the
    range still governs the rows inside it. Only EXECUTION is restricted.

    Filtering rules, all of them the file grammar's own:
      * blank lines, ``#COMMENT:`` lines and any other comment are not Answer
        rows and can never be selected;
      * a ``#COHORT:`` marker is metadata and never becomes an Answer;
      * a row whose URI failed the IRI check is excluded exactly as in a full
        run, so a range cannot smuggle in a row the full run rejects;
      * duplicates collapse to their FIRST occurrence, matching the full run's
        ``unique_uris`` semantics, and the first occurrence's line number is the
        one the range is tested against.

    Returns ``[(line_number, answer_uri, cohort), ...]`` in file order.
    """
    seen: set[str] = set()
    selected: list[tuple[int, str, Optional[str]]] = []
    for row in parsed.rows:
        if not row.uri_is_valid or row.answer_uri in seen:
            continue
        seen.add(row.answer_uri)
        if line_range is not None and not (
                line_range[0] <= row.line_number <= line_range[1]):
            continue
        selected.append((row.line_number, row.answer_uri, row.cohort))
    return selected


# ==========================================================================
# 3) §15 — the raw pinned-KG fact inventory
# ==========================================================================


def raw_fact_groups(answer_local_uri: str, *, local_kg) -> dict:
    """EVERY raw one-hop fact of one Answer, grouped by (predicate, direction).

    Deliberately NOT the rationale-eligible inventory. `--print-facts-only`
    exists so a researcher can see what the snapshot actually holds BEFORE any
    policy has removed anything, so no hard reject, no object filter, no leakage
    test and no tier is consulted here.

    Enumeration is `selection.observed_facts.observed_edge_set()` and
    normalization is the frozen `normalize_uri()` — the same two helpers
    `mcq_inputs.answer_facts_from_local_kg()` uses — so the groups printed here
    and the facts the kernel reasons over are drawn from one edge set. A
    predicate or counterpart index that resolves to no URI is a non-URI-valued
    edge (a literal); the frozen enumeration skips it rather than inventing a
    URI, and this reconstruction agrees with it.

    IN and OUT are separate groups and are never merged: `(Answer, p, x)` and
    `(x, p, Answer)` are different relations with different verbalizations.

    Returns a record with the local node index, the group map and the counts.
    Raises nothing for a missing node: the caller reports that state.
    """
    from mcq_inputs import node_index_or_none          # local: avoids a cycle

    node = node_index_or_none(answer_local_uri, local_kg)
    if node is None:
        return {"answer_local_uri": answer_local_uri, "local_index": None,
                "resolved": False, "groups": {}, "fact_count": 0,
                "group_count": 0, "out_fact_count": 0, "in_fact_count": 0,
                "skipped_non_uri_edges": 0}

    grouped: dict[tuple[str, str], set[str]] = {}
    skipped = 0
    for predicate_index, direction_code, counterpart_index in observed_edge_set(
            node, local_kg, use_in=True):
        predicate = local_kg.index_url.get(predicate_index)
        counterpart = local_kg.index_url.get(counterpart_index)
        if predicate is None or counterpart is None:
            skipped += 1
            continue
        key = (normalize_uri(predicate), DIRECTION_LABEL[direction_code])
        grouped.setdefault(key, set()).add(normalize_uri(counterpart))

    groups = {key: tuple(sorted(values)) for key, values in sorted(grouped.items())}
    total = sum(len(v) for v in groups.values())
    return {
        "answer_local_uri": answer_local_uri,
        "local_index": node,
        "resolved": True,
        "groups": groups,
        "fact_count": total,
        "group_count": len(groups),
        "out_fact_count": sum(len(v) for (_, d), v in groups.items() if d == "OUT"),
        "in_fact_count": sum(len(v) for (_, d), v in groups.items() if d == "IN"),
        "skipped_non_uri_edges": skipped,
    }


def render_raw_facts(record: Mapping, *, display_label: str = "",
                     original_uri: str = "", local_kg=None,
                     show_node_index: bool = True) -> list[str]:
    """The human-readable form of `raw_fact_groups()`. Pure formatting.

    Every counterpart is printed with BOTH its URI and a readable label, because
    the URI is the identity and the label is what a person reads. The local node
    index is printed as minimal provenance when the graph is available.
    """
    from rationale_v3.quality import display_label as label_of

    lines: list[str] = []
    add = lines.append
    add("=" * 100)
    add(f"RAW PINNED-KG FACTS — {original_uri or record['answer_local_uri']}")
    add("=" * 100)
    if original_uri and original_uri != record["answer_local_uri"]:
        add(f"    resolved pinned local URI : {record['answer_local_uri']}")
    if display_label:
        add(f"    display label             : {display_label}")
    if not record["resolved"]:
        add("    STATUS                    : NOT A NODE OF THE PINNED LOCAL KG")
        add("    No facts exist to print. This is an observation about the "
            "pinned March-2023 snapshot, not about DBpedia today.")
        return lines
    add(f"    local node index          : {record['local_index']}")
    add(f"    distinct (predicate, direction) groups : {record['group_count']}")
    add(f"    raw one-hop facts         : {record['fact_count']} "
        f"({record['out_fact_count']} OUT, {record['in_fact_count']} IN)")
    if record["skipped_non_uri_edges"]:
        add(f"    non-URI-valued edges skipped : "
            f"{record['skipped_non_uri_edges']} (literals; the frozen "
            f"enumeration emits no URI for them)")
    add("")
    add("    ALL raw facts are listed. No hard-reject predicate filter, no "
        "object filter, no leakage test and no pedagogical tier was applied, "
        "and no class ranking, LRoleSim, evidence classification, set cover or "
        "MCQ selection was run.")
    add("")
    for (predicate, direction), counterparts in record["groups"].items():
        arrow = "->" if direction == "OUT" else "<-"
        add(f"  [{direction:<3}] {predicate}   ({len(counterparts)} "
            f"counterpart{'s' if len(counterparts) != 1 else ''})")
        for counterpart in counterparts:
            index = ""
            if show_node_index and local_kg is not None:
                from mcq_inputs import node_index_or_none
                found = node_index_or_none(counterpart, local_kg)
                index = f"  [node {found}]" if found is not None else "  [node -]"
            add(f"        {arrow} {counterpart}   ({label_of(counterpart)})"
                f"{index}")
        add("")
    return lines


# ==========================================================================
# 4) §7 / §8 — screening the candidate pool BEFORE the M1 graph
# ==========================================================================


@dataclass(frozen=True)
class CandidateScreenResult:
    """What the candidate-validity screen did to one Answer's mapped pool."""

    answer_uri: str
    answer_type: str
    offered: int
    accepted_uris: tuple[str, ...]
    verdicts: tuple[CandidateValidityVerdict, ...]
    policy: CandidateValidityPolicy

    @property
    def rejected(self) -> tuple[CandidateValidityVerdict, ...]:
        return tuple(v for v in self.verdicts if not v.accepted)

    def reject_counts(self) -> dict:
        return dict(Counter(v.reject_reason for v in self.rejected))

    def as_record(self) -> dict:
        return {
            "answer_uri": self.answer_uri,
            "answer_entity_type": self.answer_type,
            "candidates_offered": self.offered,
            "candidates_accepted": len(self.accepted_uris),
            "candidates_rejected": len(self.rejected),
            "reject_counts": self.reject_counts(),
            **self.policy.as_record(),
        }


def _observed_keys(uri: str, local_kg) -> set:
    """The (predicate, direction) key set the pinned snapshot records for a URI.

    The same enumeration `mcq_inputs.candidate_objects_from_local_kg()` uses, so
    the type verdict and the evidence classification never disagree about what
    was observed. A URI absent from the graph yields an empty set, which
    `classify_entity_type` reports as UNKNOWN rather than as NOT_PERSON.
    """
    from mcq_inputs import node_index_or_none

    node = node_index_or_none(uri, local_kg)
    if node is None:
        return set()
    keys = set()
    for predicate_index, direction_code, counterpart_index in observed_edge_set(
            node, local_kg, use_in=True):
        predicate = local_kg.index_url.get(predicate_index)
        if predicate is None or local_kg.index_url.get(counterpart_index) is None:
            continue
        keys.add((normalize_uri(predicate), DIRECTION_LABEL[direction_code]))
    return keys


def screen_candidate_pool(
    *,
    answer_local_uri: str,
    candidate_uris: Sequence[str],
    local_kg,
    quality_policy,
    policy: CandidateValidityPolicy = DEFAULT_CANDIDATE_VALIDITY_POLICY,
) -> CandidateScreenResult:
    """Apply §7 and §8 to a mapped candidate list, BEFORE the M1 graph.

    Placement is the requirement, not an optimisation: §7.2 asks that an invalid
    candidate consume neither a LRoleSim rank nor evidence work, and the only
    place that holds is upstream of the graph build. The consequence is stated
    plainly rather than hidden — removing a candidate changes which nodes enter
    the M1 graph, so the LRoleSim scores of the survivors are the scores of a
    DIFFERENT graph, and ranks are contiguous over the screened pool. A run that
    screens and a run that does not are therefore two different measurements,
    which is why the screen is versioned and recorded.

    Under `OBSERVE_ONLY` — the default — every verdict is computed and published
    and NOTHING is removed, so the pool handed to the graph is byte-identical to
    the v2 pool.
    """
    answer_type = classify_entity_type(
        answer_local_uri, _observed_keys(answer_local_uri, local_kg),
        policy=policy)
    verdicts = []
    accepted = []
    for uri in candidate_uris:
        verdict = screen_candidate(
            answer_uri=answer_local_uri, candidate_uri=uri,
            observed_keys=_observed_keys(uri, local_kg),
            quality_policy=quality_policy, answer_type=answer_type,
            policy=policy)
        verdicts.append(verdict)
        if verdict.accepted:
            accepted.append(uri)
    return CandidateScreenResult(
        answer_uri=answer_local_uri, answer_type=answer_type.entity_type,
        offered=len(candidate_uris), accepted_uris=tuple(accepted),
        verdicts=tuple(verdicts), policy=policy)


# ==========================================================================
# 5) §17 — the batch table, with |R*| in a column of its own
# ==========================================================================
#
# THE BUG THIS FIXES
#   v2 built one string, "fact1; fact2; ... (|R*|=2)", and then truncated it to
#   46 characters. The cardinality is written LAST, so it is the first thing a
#   truncation removes: of the 40 |R*|=2 and 5 |R*|=3 rows in the 329-Answer
#   report, every long one lost the only field that says how many facts the
#   learner must be shown. The repair is structural rather than a larger limit —
#   a scientific quantity never shares a cell with free text that may be cut.


def _short(uri: Optional[str], limit: int = 34) -> str:
    """A readable local name. Used ONLY for names, never for a number."""
    if not uri:
        return "-"
    local = str(uri).rstrip("/").rsplit("/", 1)[-1]
    local = local.split("Category:")[-1].replace("_", " ")
    return local if len(local) <= limit else local[: limit - 1] + "…"


def _rationale_facts_cell(result) -> str:
    """The rationale's facts, WITHOUT the cardinality and WITHOUT truncation.

    Every fact is spelled `predicate -> object` (or `<-` for an IN fact) and the
    cell is left at its natural length. §17 asks for no ellipses in the
    scientific batch table wherever practical, and the facts of a rationale of
    at most three facts are always short enough to print in full.
    """
    selection = result.selection
    if selection is None or result.case is None:
        return "-"
    parts = []
    for index in selection.rationale.fact_indices:
        quality = result.case.facts[index].quality
        predicate = quality.predicate_uri.rsplit("/", 1)[-1]
        arrow = "->" if quality.direction == "OUT" else "<-"
        parts.append(f"{predicate} {arrow} "
                     f"{str(quality.counterpart_uri).rsplit('/', 1)[-1]}")
    return "; ".join(parts)


def _distractor_cell(result) -> str:
    selection = result.selection
    if selection is None:
        return "-"
    return ", ".join(f"{_short(d.uri, 26)} ({d.rank})"
                     for d in selection.distractors)


def _per_distractor_cell(result) -> str:
    selection = result.selection
    if selection is None:
        return "-"
    return "|".join(selection.rationale.per_candidate_best_level[position]
                    for position in range(len(selection.distractors)))


def _basis_cell(result) -> str:
    selection, case = result.selection, result.case
    if selection is None or case is None:
        return "-"
    bases = set()
    for index in selection.rationale.fact_indices:
        for position in selection.positions:
            bases.add(case.facts[index].exclusion_bases[position])
    return "/".join(sorted(bases)) or "NONE"


def _risk_cell(result) -> str:
    """Granularity-risk incidences, and WHICH risk states produced them."""
    selection, case = result.selection, result.case
    if selection is None or case is None:
        return "-"
    states = set()
    for index in selection.rationale.fact_indices:
        for position in selection.positions:
            state = case.facts[index].granularity_risks[position]
            if state != "NONE":
                states.add(state)
    count = selection.rationale.granularity_risk_incidences
    if not states:
        return str(count)
    short = "/".join(sorted(s.split("_")[0] for s in states))
    return f"{count} ({short})"


def summary_table_v3(results: Sequence) -> str:
    """The v3 Markdown batch table. EVERY Answer gets a row.

    Columns, stated once so a reader never has to guess:

    * **Answer** — the ORIGINAL input spelling, then `-> resolved` when the
      pinned local KG holds the entity under a different name.
    * **Line** — the 1-based source line of the Answer row in the input file,
      so a `--lines-for-input-file` selection is checkable by eye.
    * **Cands** — the size of the COMPLETE graph-feasible LRoleSim ranked pool
      AFTER candidate-validity screening, not the bounded search pool.
    * **Distractors (rank)** — the three selected candidates with their ranks.
    * **|R\\*|** — the exact minimum rationale cardinality, IN ITS OWN COLUMN
      and never truncated.
    * **Rationale facts** — the facts themselves, untruncated.
    * **Per-distractor** — the best level each distractor reaches under the
      SELECTED rationale, in distractor order.
    * **MCQ** — the frozen `mcq_evidence_level`.
    * **Basis** — exclusion bases present under the selected rationale.
    * **Risk** — granularity-risk incidences and the states behind them.
    * **OptRef** — option-reference conflicts in the selected rationale.
    * **Anon** — `count / (1 + complete ranked pool size)`.
    * **Main** — only for a student-showable L1/L2 selection.
    """
    header = ("| # | Answer | Line | Status | Class | Cands | "
              "Distractors (rank) | \\|R*\\| | Rationale facts | Per-distractor "
              "| MCQ | Basis | Sem. | Risk | OptRef | Anon | Main |")
    rule = "|" + "---|" * 17
    lines = [header, rule]
    for number, result in enumerate(results, start=1):
        selection = result.selection
        rationale = None if selection is None else selection.rationale
        identity = result.identity
        answer = _short(result.original_uri, 26)
        if identity is not None and identity.local_kg_uri:
            resolved = _short(identity.local_kg_uri, 26)
            if resolved != answer:
                answer = f"{answer} → {resolved}"
        anonymity = ("-" if rationale is None else
                     f"{rationale.local_candidate_pool_anonymity_count}/"
                     f"{result.complete_pool_size + 1}")
        semantic = ("-" if result.semantic_index_available is None
                    else ("AVAILABLE" if result.semantic_index_available
                          else "UNAVAILABLE"))
        lines.append(
            f"| {number} "
            f"| {answer} "
            f"| {getattr(result, 'source_line_number', None) or '-'} "
            f"| {result.status} "
            f"| {_short(result.selected_class_uri, 30)} "
            f"| {result.complete_pool_size or '-'} "
            f"| {_distractor_cell(result)} "
            f"| {'-' if selection is None else selection.minimum_rationale_size} "
            f"| {_rationale_facts_cell(result)} "
            f"| {_per_distractor_cell(result)} "
            f"| {result.mcq_evidence_level or '-'} "
            f"| {_basis_cell(result)} "
            f"| {semantic} "
            f"| {_risk_cell(result)} "
            f"| {'-' if rationale is None else rationale.option_reference_conflict_count} "
            f"| {anonymity} "
            f"| {'✔' if result.has_main_l1_selection else '-'} |")
    return "\n".join(lines)


# ==========================================================================
# 6) §18 / §19 — rich batch metrics with explicit denominators
# ==========================================================================


def _pct(count: int, denominator: int) -> Optional[float]:
    """A percentage, or None when the denominator is zero.

    Never a silent 0.0: "no such Answers existed" and "none of them qualified"
    are different findings, and the Markdown renderer prints `N/A` for the
    first. Nothing here divides by zero.
    """
    if not denominator:
        return None
    return round(100.0 * count / denominator, 2)


def _describe(values: Sequence[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    ordered = sorted(values)
    return {"n": len(ordered),
            "mean": round(statistics.fmean(ordered), 4),
            "median": statistics.median(ordered),
            "min": ordered[0], "max": ordered[-1]}


def batch_metrics(results: Sequence, *, config: Optional[RunnerConfigV3] = None,
                  screens: Sequence[CandidateScreenResult] = ()) -> dict:
    """The complete §18 metric set. Machine-readable, every denominator named.

    Four coverage concepts are kept apart throughout (§19), because v2's single
    "Successful (distractors selected)" line counted 278 while 304 Answers
    actually produced a kernel selection:

      any kernel selection          a distractor triple and a rationale exist
      student-showable main L1/L2   that selection is showable to a learner
      diagnostic L0-only            a selection exists but rests on ABSENCE
      no selection                  no combination reached full coverage

    Nothing is ever removed from a denominator. Every failure status is counted
    and every rate over Answers uses the total attempted.
    """
    total = len(results)
    any_selection = [r for r in results if r.selection is not None]
    l0 = [r for r in any_selection if r.mcq_evidence_level == "MCQ-L0"]
    l1 = [r for r in any_selection if r.mcq_evidence_level == "MCQ-L1"]
    l2 = [r for r in any_selection if r.mcq_evidence_level == "MCQ-L2"]
    showable = [r for r in any_selection if r.has_main_l1_selection]
    no_selection = [r for r in results if r.selection is None]

    # --- C. SCOPED_EMPIRICAL among L1 questions --------------------------
    def scoped_incidences(result) -> int:
        selection, case = result.selection, result.case
        if selection is None or case is None:
            return 0
        return sum(
            1 for index in selection.rationale.fact_indices
            for position in selection.positions
            if case.facts[index].exclusion_bases[position] == "SCOPED_EMPIRICAL")

    scoped_l1 = [r for r in l1 if scoped_incidences(r) > 0]

    # --- D. cardinality per evidence group -------------------------------
    cardinality = {}
    for name, group in (("MCQ-L0", l0), ("MCQ-L1", l1), ("MCQ-L2", l2)):
        counter = Counter(r.selection.minimum_rationale_size for r in group)
        cardinality[name] = {
            "denominator": len(group),
            "distribution": {
                str(size): {"count": counter[size],
                            "pct_within_group": _pct(counter[size], len(group))}
                for size in sorted(counter)},
        }

    # --- E. LRoleSim rank retention --------------------------------------
    ranks = [[d.rank for d in r.selection.distractors] for r in any_selection]
    exact = [row for row in ranks if row == [1, 2, 3]]
    flat = [rank for row in ranks for rank in row]
    slots = {i: [row[i] for row in ranks if len(row) > i] for i in range(3)}

    # --- F. pedagogical diagnostics --------------------------------------
    anonymity = [r.selection.rationale.local_candidate_pool_anonymity_count
                 for r in any_selection]
    conflicts = [r.selection.rationale.option_reference_conflict_count
                 for r in any_selection]
    risky = [r for r in any_selection
             if r.selection.rationale.granularity_risk_incidences > 0]
    direct = [r for r in any_selection
              if r.selection.rationale.direct_identifier_flag]

    screen_counts: Counter = Counter()
    for screen in screens:
        screen_counts.update(screen.reject_counts())

    # --- H. cohorts -------------------------------------------------------
    by_cohort = defaultdict(list)
    for result in results:
        by_cohort[result.cohort or "(no cohort)"].append(result)
    cohorts = {}
    for cohort, group in sorted(by_cohort.items()):
        g_any = [r for r in group if r.selection is not None]
        g_show = [r for r in g_any if r.has_main_l1_selection]
        g_l0 = [r for r in g_any if r.mcq_evidence_level == "MCQ-L0"]
        g_ranks = [[d.rank for d in r.selection.distractors] for r in g_any]
        cohorts[cohort] = {
            "answers_attempted": len(group),
            "any_kernel_selection": len(g_any),
            "any_kernel_selection_pct": _pct(len(g_any), len(group)),
            "student_showable_main_l1_l2": len(g_show),
            "student_showable_pct": _pct(len(g_show), len(group)),
            "diagnostic_l0_only": len(g_l0),
            "diagnostic_l0_only_pct": _pct(len(g_l0), len(group)),
            "no_selection": len(group) - len(g_any),
            "no_selection_pct": _pct(len(group) - len(g_any), len(group)),
            "exact_ranks_1_2_3": sum(1 for row in g_ranks if row == [1, 2, 3]),
            "statuses": dict(sorted(Counter(r.status for r in group).items())),
            "note": "Cohort labels are EVALUATION METADATA ONLY. They never "
                    "reach the class ranker, the graph, LRoleSim or the kernel.",
        }

    return {
        "schema_version": ANY_ANSWER_V3_SCHEMA_VERSION,
        "runner_config": None if config is None else config.as_record(),
        "coverage": {
            "total_answers_attempted": total,
            "any_kernel_selection": len(any_selection),
            "any_kernel_selection_pct": _pct(len(any_selection), total),
            "student_showable_main_l1_l2": len(showable),
            "student_showable_main_l1_l2_pct": _pct(len(showable), total),
            "diagnostic_l0_only": len(l0),
            "diagnostic_l0_only_pct": _pct(len(l0), total),
            "no_selection": len(no_selection),
            "no_selection_pct": _pct(len(no_selection), total),
            "full_exact": sum(1 for r in any_selection
                              if r.search_scope == "FULL_EXACT"),
            "pool_exact": sum(1 for r in any_selection
                              if r.search_scope == "POOL_EXACT"),
            "denominator_note": ("every percentage in this block is over the "
                                 "Answers ATTEMPTED; no failure is removed"),
        },
        "evidence_levels": {
            "denominator": total,
            "MCQ-L0": {"count": len(l0), "pct_of_all_answers": _pct(len(l0), total)},
            "MCQ-L1": {"count": len(l1), "pct_of_all_answers": _pct(len(l1), total)},
            "MCQ-L2": {"count": len(l2), "pct_of_all_answers": _pct(len(l2), total)},
            "note": ("MCQ-L0 items are DIAGNOSTIC. L0 is snapshot absence and "
                     "is never reported as student-showable success."),
        },
        "scoped_empirical": {
            "denominator_l1_questions": len(l1),
            "l1_questions_with_at_least_one_incidence": len(scoped_l1),
            "pct_of_l1_questions": _pct(len(scoped_l1), len(l1)),
            "pct_of_all_answers": _pct(len(scoped_l1), total),
            "total_incidences_over_l1": sum(scoped_incidences(r) for r in l1),
            "note": ("SCOPED_EMPIRICAL is an exclusion BASIS on a separate "
                     "axis, never a fourth evidence level."),
        },
        "rationale_cardinality": cardinality,
        "lrolesim_rank_retention": {
            "denominator_any_kernel_selection": len(any_selection),
            "exact_ranks_1_2_3": len(exact),
            "exact_ranks_1_2_3_pct": _pct(len(exact), len(any_selection)),
            "all_selected_ranks": _describe(flat),
            "slot_1": _describe(slots[0]),
            "slot_2": _describe(slots[1]),
            "slot_3": _describe(slots[2]),
            "candidate_rank_sum": _describe([sum(row) for row in ranks]),
        },
        "pedagogical_diagnostics": {
            "denominator_any_kernel_selection": len(any_selection),
            "direct_identifier_flag_count": len(direct),
            "direct_identifier_flag_pct": _pct(len(direct), len(any_selection)),
            "anonymity_count": _describe(anonymity),
            "anonymity_distribution": dict(sorted(Counter(anonymity).items())),
            "granularity_risk_rationale_count": len(risky),
            "granularity_risk_pct": _pct(len(risky), len(any_selection)),
            "option_reference_conflict_rationale_count":
                sum(1 for value in conflicts if value),
            "option_reference_conflict_pct":
                _pct(sum(1 for value in conflicts if value), len(any_selection)),
            "option_reference_conflict_total_incidences": sum(conflicts),
            "candidate_type_rejections":
                screen_counts.get("CANDIDATE_TYPE_NOT_PERSON", 0)
                + screen_counts.get(
                    "CANDIDATE_TYPE_UNKNOWN_UNDER_PERSON_STRICT_POLICY", 0),
            "candidate_type_rejections_by_reason": {
                reason: count for reason, count in sorted(screen_counts.items())
                if reason.startswith("CANDIDATE_TYPE_")},
            "candidate_topical_identity_leak_rejections":
                screen_counts.get(
                    "CANDIDATE_NAME_CONTAINS_THE_COMPLETE_ANSWER_NAME", 0),
            "hard_class_leak_rejections": sum(
                sum(1 for entry in r.class_ranking_rejections)
                for r in results if hasattr(r, "class_ranking_rejections")),
        },
        "failure_taxonomy": dict(sorted(Counter(r.status for r in results).items())),
        "cohorts": cohorts,
    }


def metrics_markdown(metrics: Mapping) -> str:
    """The human-readable form of `batch_metrics()`. Pure formatting.

    `N/A` is printed wherever a denominator was zero. No cell is ever computed
    by dividing by zero, and no rate is silently rendered as 0%.
    """
    def cell(value) -> str:
        return "N/A" if value is None else str(value)

    L: list[str] = []
    A = L.append
    A("### A. Coverage — denominator = Answers attempted")
    A("")
    coverage = metrics["coverage"]
    total = coverage["total_answers_attempted"]
    A("| quantity | count | % of all Answers |")
    A("|---|---:|---:|")
    A(f"| Total Answers attempted | {total} | 100.0 |")
    for label, key in (
            ("Any kernel selection", "any_kernel_selection"),
            ("Student-showable main L1/L2 success", "student_showable_main_l1_l2"),
            ("Diagnostic L0-only selection", "diagnostic_l0_only"),
            ("No selection at any policy", "no_selection")):
        A(f"| {label} | {coverage[key]} | {cell(coverage[key + '_pct'])} |")
    A(f"| FULL_EXACT | {coverage['full_exact']} | "
      f"{cell(_pct(coverage['full_exact'], total))} |")
    A(f"| POOL_EXACT | {coverage['pool_exact']} | "
      f"{cell(_pct(coverage['pool_exact'], total))} |")
    A("")
    A("### B. MCQ evidence levels")
    A("")
    A("| level | count | % of all Answers |")
    A("|---|---:|---:|")
    for level in ("MCQ-L0", "MCQ-L1", "MCQ-L2"):
        entry = metrics["evidence_levels"][level]
        A(f"| {level} | {entry['count']} | {cell(entry['pct_of_all_answers'])} |")
    A("")
    A(f"_{metrics['evidence_levels']['note']}_")
    A("")
    A("### C. SCOPED_EMPIRICAL incidence among L1 questions")
    A("")
    scoped = metrics["scoped_empirical"]
    A(f"- denominator (L1 questions): **{scoped['denominator_l1_questions']}**")
    A(f"- L1 questions with >= 1 incidence: "
      f"**{scoped['l1_questions_with_at_least_one_incidence']}**")
    A(f"- % of L1 questions: **{cell(scoped['pct_of_l1_questions'])}**")
    A(f"- % of all Answers: **{cell(scoped['pct_of_all_answers'])}**")
    A(f"- total incidences over L1 selections: "
      f"{scoped['total_incidences_over_l1']}")
    A("")
    A("### D. Rationale cardinality per MCQ evidence group")
    A("")
    A("| group | denominator | \\|R*\\|=1 | \\|R*\\|=2 | \\|R*\\|=3 | other |")
    A("|---|---:|---:|---:|---:|---|")
    for level in ("MCQ-L0", "MCQ-L1", "MCQ-L2"):
        entry = metrics["rationale_cardinality"][level]
        denominator = entry["denominator"]
        cells = []
        for size in ("1", "2", "3"):
            row = entry["distribution"].get(size)
            if denominator == 0:
                cells.append("N/A")
            elif row is None:
                cells.append("0 (0.0%)")
            else:
                cells.append(f"{row['count']} ({cell(row['pct_within_group'])}%)")
        other = ", ".join(
            f"|R*|={size}: {row['count']}"
            for size, row in entry["distribution"].items()
            if size not in ("1", "2", "3")) or "-"
        A(f"| {level} | {denominator} | " + " | ".join(cells) + f" | {other} |")
    A("")
    A("### E. LRoleSim rank retention")
    A("")
    retention = metrics["lrolesim_rank_retention"]
    A(f"- denominator (any kernel selection): "
      f"**{retention['denominator_any_kernel_selection']}**")
    A(f"- selected distractors are exactly ranks 1,2,3: "
      f"**{retention['exact_ranks_1_2_3']}** "
      f"({cell(retention['exact_ranks_1_2_3_pct'])}%)")
    A("")
    A("| series | n | mean | median | min | max |")
    A("|---|---:|---:|---:|---:|---:|")
    for label, key in (("all selected ranks", "all_selected_ranks"),
                       ("slot 1", "slot_1"), ("slot 2", "slot_2"),
                       ("slot 3", "slot_3"),
                       ("candidate rank sum", "candidate_rank_sum")):
        entry = retention[key]
        A(f"| {label} | {entry['n']} | {cell(entry['mean'])} "
          f"| {cell(entry['median'])} | {cell(entry['min'])} "
          f"| {cell(entry['max'])} |")
    A("")
    A("### F. Rationale / pedagogical diagnostics")
    A("")
    diagnostics = metrics["pedagogical_diagnostics"]
    anonymity = diagnostics["anonymity_count"]
    A(f"- direct_identifier_flag: **{diagnostics['direct_identifier_flag_count']}** "
      f"({cell(diagnostics['direct_identifier_flag_pct'])}%)")
    A(f"- local anonymity count: mean {cell(anonymity['mean'])}, "
      f"median {cell(anonymity['median'])}, min {cell(anonymity['min'])}, "
      f"max {cell(anonymity['max'])}")
    A(f"- anonymity distribution: `{diagnostics['anonymity_distribution']}`")
    A(f"- granularity-risk rationales: "
      f"**{diagnostics['granularity_risk_rationale_count']}** "
      f"({cell(diagnostics['granularity_risk_pct'])}%)")
    A(f"- option-reference-conflict rationales: "
      f"**{diagnostics['option_reference_conflict_rationale_count']}** "
      f"({cell(diagnostics['option_reference_conflict_pct'])}%), "
      f"{diagnostics['option_reference_conflict_total_incidences']} incidences")
    A(f"- candidate-type rejections: "
      f"**{diagnostics['candidate_type_rejections']}** "
      f"`{diagnostics['candidate_type_rejections_by_reason']}`")
    A(f"- candidate topical/identity-leak rejections: "
      f"**{diagnostics['candidate_topical_identity_leak_rejections']}**")
    A("")
    A("### G. Failure taxonomy — every status, nothing removed")
    A("")
    A("| status | count |")
    A("|---|---:|")
    for status, count in metrics["failure_taxonomy"].items():
        A(f"| {status} | {count} |")
    A("")
    A("### H. Cohort breakdown — cohort labels are evaluation metadata only")
    A("")
    A("| cohort | Answers | any kernel sel. | student-showable | L0-only "
      "| no selection | ranks 1,2,3 |")
    A("|---|---:|---:|---:|---:|---:|---:|")
    for cohort, entry in metrics["cohorts"].items():
        A(f"| {cohort} | {entry['answers_attempted']} "
          f"| {entry['any_kernel_selection']} "
          f"({cell(entry['any_kernel_selection_pct'])}%) "
          f"| {entry['student_showable_main_l1_l2']} "
          f"({cell(entry['student_showable_pct'])}%) "
          f"| {entry['diagnostic_l0_only']} | {entry['no_selection']} "
          f"| {entry['exact_ranks_1_2_3']} |")
    A("")
    return "\n".join(L)


def metrics_csv_rows(metrics: Mapping) -> list[dict]:
    """A flat `metric,value,denominator,note` view for a CSV artifact."""
    rows: list[dict] = []

    def add(metric: str, value, denominator=None, note: str = "") -> None:
        rows.append({"metric": metric,
                     "value": "" if value is None else value,
                     "denominator": "" if denominator is None else denominator,
                     "note": note})

    total = metrics["coverage"]["total_answers_attempted"]
    for key, value in metrics["coverage"].items():
        if key == "denominator_note":
            continue
        add(f"coverage.{key}", value, total)
    for level in ("MCQ-L0", "MCQ-L1", "MCQ-L2"):
        entry = metrics["evidence_levels"][level]
        add(f"evidence_level.{level}.count", entry["count"], total)
        add(f"evidence_level.{level}.pct", entry["pct_of_all_answers"], total)
    scoped = metrics["scoped_empirical"]
    for key in ("l1_questions_with_at_least_one_incidence",
                "pct_of_l1_questions", "pct_of_all_answers",
                "total_incidences_over_l1"):
        add(f"scoped_empirical.{key}", scoped[key],
            scoped["denominator_l1_questions"], scoped["note"])
    for level, entry in metrics["rationale_cardinality"].items():
        for size, row in entry["distribution"].items():
            add(f"rationale_cardinality.{level}.size_{size}.count",
                row["count"], entry["denominator"])
            add(f"rationale_cardinality.{level}.size_{size}.pct",
                row["pct_within_group"], entry["denominator"])
    retention = metrics["lrolesim_rank_retention"]
    denominator = retention["denominator_any_kernel_selection"]
    add("lrolesim.exact_ranks_1_2_3", retention["exact_ranks_1_2_3"], denominator)
    add("lrolesim.exact_ranks_1_2_3_pct", retention["exact_ranks_1_2_3_pct"],
        denominator)
    for key in ("all_selected_ranks", "slot_1", "slot_2", "slot_3",
                "candidate_rank_sum"):
        for stat, value in retention[key].items():
            add(f"lrolesim.{key}.{stat}", value, denominator)
    for key, value in metrics["pedagogical_diagnostics"].items():
        if isinstance(value, (int, float, str)) or value is None:
            add(f"pedagogical.{key}", value, denominator)
    for status, count in metrics["failure_taxonomy"].items():
        add(f"failure.{status}", count, total)
    for cohort, entry in metrics["cohorts"].items():
        for key in ("answers_attempted", "any_kernel_selection",
                    "student_showable_main_l1_l2", "diagnostic_l0_only",
                    "no_selection", "exact_ranks_1_2_3"):
            add(f"cohort.{cohort}.{key}", entry[key],
                entry["answers_attempted"], entry["note"])
    return rows


def prose_summary_v3(results: Sequence, metrics: Mapping) -> str:
    """§19: four DISTINCT coverage concepts, never one "successful" line.

    v2 printed `Successful (distractors selected): 278`, but 304 of the 329
    Answers produced a kernel selection with three distractors — the other 26
    were diagnostic-L0 items, which have distractors and a rationale and are
    simply not showable to a learner. Calling only the L1/L2 rows "distractors
    selected" understated the kernel's reach and overstated nothing; both
    numbers matter and both are printed.
    """
    coverage = metrics["coverage"]
    total = coverage["total_answers_attempted"]

    def line(label: str, count: int, percentage) -> str:
        rendered = "N/A" if percentage is None else f"{percentage:5.1f}%"
        return f"  {label:<44} {count:>5}   {rendered}"

    L = [f"Total Answers attempted                        {total:>5}",
         "",
         "COVERAGE — four distinct concepts (percentages over all Answers):"]
    L.append(line("Any kernel selection (triple + rationale)",
                  coverage["any_kernel_selection"],
                  coverage["any_kernel_selection_pct"]))
    L.append(line("  of which student-showable main L1/L2",
                  coverage["student_showable_main_l1_l2"],
                  coverage["student_showable_main_l1_l2_pct"]))
    L.append(line("  of which diagnostic L0-only",
                  coverage["diagnostic_l0_only"],
                  coverage["diagnostic_l0_only_pct"]))
    L.append(line("No selection at any policy",
                  coverage["no_selection"], coverage["no_selection_pct"]))
    L.append("")
    L.append(f"  FULL_EXACT {coverage['full_exact']}   "
             f"POOL_EXACT {coverage['pool_exact']}")
    L.append("")
    L.append("Failure reasons (all remain in the denominator):")
    for status, count in metrics["failure_taxonomy"].items():
        L.append(f"  {status:<44} {count:>5}")
    L += [
        "",
        "A diagnostic-L0 item HAS a distractor triple and a rationale. It is "
        "not student-showable because L0 is snapshot ABSENCE, and under the "
        "open-world assumption a missing triple is not a false fact. Calling "
        "only the L1/L2 rows 'distractors selected' would mis-describe both "
        "groups, which is why this summary never uses that phrase.",
        "",
        "A FULL_EXACT result is exact over the COMPLETE ranked candidate pool "
        "of the selected class; a POOL_EXACT result is exact only within the "
        "bounded pool the kernel searched. Neither is a claim about DBpedia as "
        "a whole, and the selected class is the FIRST locally mapping-feasible "
        "class of an automatic ranking, never a globally optimal class.",
    ]
    return "\n".join(L)
