############################################################################
# src/selection/lrolesim_handoff.py
#
# The PROPOSED Journal-2 pilot ranker: `lrolesim_m1_fixed_k3`.
#
# WHAT THIS MODULE IS
#   An ADAPTER over the verified Prompt-8C artefacts. It reads the frozen graph
#   and LRoleSim records, checks them against the contract below, and exposes them
#   through the CandidateRanker interface so the extract entrypoint can consume a
#   ranking without knowing anything about LRoleSim.
#
# WHAT THIS MODULE IS NOT
#   * It does NOT implement LRoleSim. The mathematics lives in
#     src/MCQ_lrolesim_ClaudeWeb_v2.py and is reached only through
#     src/lrolesim/adapter.py. Journal 2 APPLIES LRoleSim as a structural
#     plausibility ranker; it does not redefine it (CLAUDE.md items 2 and 3).
#   * It does NOT build a graph. Rebuilding one here would produce a second,
#     differently-budgeted graph and silently invalidate every frozen fingerprint.
#   * It does NOT re-rank, re-score, re-sort or re-tie-break. Prompt-8C ranks are
#     reproduced, never recomputed. Every ordering assertion below is a CHECK on
#     the frozen record, not a fresh computation.
#   * It does NOT select distractors and does NOT generate rationales. LRoleSim
#     does not generate rationales (CLAUDE.md item 4); rationale set cover is
#     Prompt 8E's.
#
# THE CONTRACT CHECKED HERE  (Prompt 8D, section 5)
#   nine primary Answer summary rows; eight graph-feasible; Sulfuric acid the one
#   primary failure; 204 primary ranked candidates; every ranked candidate an
#   approved retained candidate; no context node ranked; no Answer ranking itself;
#   the selected class agreeing across every file; the graph fingerprint agreeing
#   across ranking, graph and summary records; measure lrolesim_ed; lrolesim_beta
#   0.2; exactly 3 fixed iterations; contiguous ranks; descending scores; ties
#   broken on ascending canonical candidate URI.
#
#   A violation raises ContractInconsistencyError. It is never repaired, and it is
#   never downgraded to a warning: an inconsistency between these files means the
#   frozen evidence no longer describes one run, which is a review question, not
#   something a consumer may paper over.
#
# OFFLINE
#   Reads local frozen files only. No network, no SPARQL, no class selection, no
#   spaCy, no SBERT, no abstracts. The 1.2 GB pinned pickle is needed only for
#   observed-fact serialization, which the caller supplies separately.
############################################################################

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from selection.contracts import (
    CandidateRanking,
    NO_GRAPH_FEASIBLE_APPROVED_CLASS,
    NO_MAPPING_FEASIBLE_APPROVED_CLASS,
    PILOT_ITERATIONS,
    PILOT_ITERATION_MODE,
    PILOT_LROLESIM_BETA,
    PILOT_MEASURE,
    RANKER_LROLESIM_M1_FIXED_K3,
    RATIONALE_SELECTION_DEFERRED,
    RankedCandidate,
    RationaleSelectionHandoff,
    SCOPE_DIAGNOSTIC,
    SCOPE_PRIMARY,
)

# --- Expected pilot shape (asserted, never assumed) ------------------------
EXPECTED_PRIMARY_ANSWER_COUNT = 9
EXPECTED_GRAPH_FEASIBLE_PRIMARY_COUNT = 8
EXPECTED_PRIMARY_RANKED_CANDIDATE_COUNT = 204
EXPECTED_DIAGNOSTIC_RANKED_CANDIDATE_COUNT = 6
EXPECTED_PRIMARY_FAILURE_ANSWER_URI = "http://dbpedia.org/resource/Sulfuric_acid"
DIAGNOSTIC_CLASS_URI = "http://dbpedia.org/resource/Category:Mineral_acids"

# The frozen Prompt-8C files this adapter reads.
REQUIRED_INPUT_FILES = (
    "graph_policy_summary.csv",
    "graph_class_attempts.csv",
    "graph_candidates.jsonl",
    "graph_manifests.jsonl",
    "lrolesim_rankings.csv",
    "lrolesim_scores.jsonl",
    "provisional_top3.csv",
    "sulfuric_acid_diagnostic.json",
    "run_manifest.json",
)

PROVISIONAL_TOP_N = 3


class HandoffError(Exception):
    """Base class for Prompt-8D handoff failures."""


class Prompt8CInputError(HandoffError):
    """A frozen Prompt-8C input file is missing or unreadable."""


class ContractInconsistencyError(HandoffError):
    """The frozen Prompt-8C records disagree with each other or with the contract.

    This is the EXTRACT_LROLESIM_INTEGRATION_REQUIRES_CONTRACT_REVIEW condition.
    """


# ==========================================================================
# 1) READING THE FROZEN PROMPT-8C OUTPUTS
# ==========================================================================

def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise Prompt8CInputError(f"frozen Prompt-8C input not found: {path}")
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise Prompt8CInputError(f"frozen Prompt-8C input not found: {path}")
    records = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise Prompt8CInputError(
                    f"{path.name} line {lineno}: {exc}") from exc
    return records


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise Prompt8CInputError(f"frozen Prompt-8C input not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _as_bool(value: object, label: str) -> bool:
    """Parse the CSV spelling of a boolean without guessing.

    An unexpected spelling raises: silently treating anything non-"true" as false
    would turn a corrupted flag into a confident negative.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value == "true":
            return True
        if value == "false":
            return False
    raise ContractInconsistencyError(
        f"{label}: expected 'true' or 'false', got {value!r}")


def _as_int(value: object, label: str) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise ContractInconsistencyError(
            f"{label}: expected an integer, got {value!r}") from exc


def _as_float(value: object, label: str) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError) as exc:
        raise ContractInconsistencyError(
            f"{label}: expected a float, got {value!r}") from exc


@dataclass(frozen=True)
class Prompt8CInputs:
    """The frozen Prompt-8C artefacts, read but not yet validated."""

    source_dir: Path
    policy_summary: tuple[dict, ...]
    class_attempts: tuple[dict, ...]
    candidates: tuple[dict, ...]
    manifests: tuple[dict, ...]
    rankings: tuple[dict, ...]
    scores: tuple[dict, ...]
    provisional_top3: tuple[dict, ...]
    diagnostic: Mapping[str, object]
    run_manifest: Mapping[str, object]

    def primary_summary_rows(self) -> list[dict]:
        return [r for r in self.policy_summary
                if r["primary_or_diagnostic"] == SCOPE_PRIMARY]

    def primary_rankings(self) -> list[dict]:
        return [r for r in self.rankings
                if r["primary_or_diagnostic"] == SCOPE_PRIMARY]

    def diagnostic_rankings(self) -> list[dict]:
        return [r for r in self.rankings
                if r["primary_or_diagnostic"] == SCOPE_DIAGNOSTIC]

    def manifest_for(self, answer_uri: str, scope: str) -> Optional[dict]:
        for manifest in self.manifests:
            if (manifest["answer_uri"] == answer_uri
                    and manifest["primary_or_diagnostic"] == scope):
                return manifest
        return None


def load_prompt8c_outputs(source_dir: str | Path) -> Prompt8CInputs:
    """Read every frozen Prompt-8C file this adapter depends on."""
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise Prompt8CInputError(
            f"frozen Prompt-8C output directory not found: {source_dir}")
    missing = [name for name in REQUIRED_INPUT_FILES
               if not (source_dir / name).is_file()]
    if missing:
        raise Prompt8CInputError(
            f"{source_dir}: missing frozen Prompt-8C inputs {missing}")

    return Prompt8CInputs(
        source_dir=source_dir,
        policy_summary=tuple(_read_csv(source_dir / "graph_policy_summary.csv")),
        class_attempts=tuple(_read_csv(source_dir / "graph_class_attempts.csv")),
        candidates=tuple(_read_jsonl(source_dir / "graph_candidates.jsonl")),
        manifests=tuple(_read_jsonl(source_dir / "graph_manifests.jsonl")),
        rankings=tuple(_read_csv(source_dir / "lrolesim_rankings.csv")),
        scores=tuple(_read_jsonl(source_dir / "lrolesim_scores.jsonl")),
        provisional_top3=tuple(_read_csv(source_dir / "provisional_top3.csv")),
        diagnostic=_read_json(source_dir / "sulfuric_acid_diagnostic.json"),
        run_manifest=_read_json(source_dir / "run_manifest.json"),
    )


# ==========================================================================
# 2) CONTRACT VALIDATION
# ==========================================================================

@dataclass(frozen=True)
class ContractReport:
    """What the validation actually observed, so a report can quote numbers."""

    primary_answer_count: int
    graph_feasible_primary_count: int
    primary_failure_answer_uris: tuple[str, ...]
    primary_ranked_candidate_count: int
    diagnostic_ranked_candidate_count: int
    checks: tuple[tuple[str, bool, str], ...]

    @property
    def all_passed(self) -> bool:
        return all(passed for _name, passed, _detail in self.checks)

    def as_record(self) -> dict:
        return {
            "primary_answer_count": self.primary_answer_count,
            "graph_feasible_primary_count": self.graph_feasible_primary_count,
            "primary_failure_answer_uris": list(self.primary_failure_answer_uris),
            "primary_ranked_candidate_count": self.primary_ranked_candidate_count,
            "diagnostic_ranked_candidate_count":
                self.diagnostic_ranked_candidate_count,
            "all_checks_passed": self.all_passed,
            "checks": [{"check": name, "passed": passed, "detail": detail}
                       for name, passed, detail in self.checks],
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractInconsistencyError(message)


def validate_prompt8c_contract(inputs: Prompt8CInputs) -> ContractReport:
    """Check every Prompt-8D section-5 invariant against the frozen records.

    Raises ContractInconsistencyError on the first violation. Returns a report of
    what was observed when all invariants hold.
    """
    checks: list[tuple[str, bool, str]] = []

    def record(name: str, detail: str) -> None:
        checks.append((name, True, detail))

    # --- shape of the primary policy summary -----------------------------
    primary_rows = inputs.primary_summary_rows()
    _require(
        len(primary_rows) == EXPECTED_PRIMARY_ANSWER_COUNT,
        f"graph_policy_summary.csv must hold exactly "
        f"{EXPECTED_PRIMARY_ANSWER_COUNT} primary Answer rows, found "
        f"{len(primary_rows)}")
    record("nine_primary_summary_rows", f"{len(primary_rows)} primary rows")

    _require(
        len(inputs.policy_summary) == len(primary_rows),
        f"graph_policy_summary.csv must contain primary rows only; found "
        f"{len(inputs.policy_summary) - len(primary_rows)} non-primary rows")
    record("summary_is_primary_only",
           "no diagnostic row is mixed into the primary summary")

    feasible = [r for r in primary_rows
                if r["graph_stage_status"] != NO_GRAPH_FEASIBLE_APPROVED_CLASS]
    infeasible = [r for r in primary_rows
                  if r["graph_stage_status"] == NO_GRAPH_FEASIBLE_APPROVED_CLASS]
    _require(
        len(feasible) == EXPECTED_GRAPH_FEASIBLE_PRIMARY_COUNT,
        f"expected {EXPECTED_GRAPH_FEASIBLE_PRIMARY_COUNT} graph-feasible primary "
        f"Answers, found {len(feasible)}")
    record("eight_graph_feasible_primary_answers",
           f"{len(feasible)} feasible, {len(infeasible)} infeasible")

    # --- Sulfuric acid stays the one primary failure ----------------------
    failure_uris = tuple(sorted(r["answer_uri"] for r in infeasible))
    _require(
        failure_uris == (EXPECTED_PRIMARY_FAILURE_ANSWER_URI,),
        f"the one primary failure must be {EXPECTED_PRIMARY_FAILURE_ANSWER_URI}, "
        f"found {list(failure_uris)}")
    sulfuric = infeasible[0]
    _require(
        sulfuric["mapping_stage_status"] == NO_MAPPING_FEASIBLE_APPROVED_CLASS,
        f"Sulfuric acid must keep mapping status "
        f"{NO_MAPPING_FEASIBLE_APPROVED_CLASS}, found "
        f"{sulfuric['mapping_stage_status']!r}")
    _require(
        not sulfuric["graph_selected_class_uri"],
        "Sulfuric acid must not carry a selected class in the primary summary")
    record("sulfuric_acid_primary_failure_preserved",
           f"{NO_MAPPING_FEASIBLE_APPROVED_CLASS} / "
           f"{NO_GRAPH_FEASIBLE_APPROVED_CLASS}")

    # --- ranked candidate counts ------------------------------------------
    primary_rankings = inputs.primary_rankings()
    diagnostic_rankings = inputs.diagnostic_rankings()
    _require(
        len(primary_rankings) == EXPECTED_PRIMARY_RANKED_CANDIDATE_COUNT,
        f"expected {EXPECTED_PRIMARY_RANKED_CANDIDATE_COUNT} primary ranked "
        f"candidates, found {len(primary_rankings)}")
    _require(
        len(diagnostic_rankings) == EXPECTED_DIAGNOSTIC_RANKED_CANDIDATE_COUNT,
        f"expected {EXPECTED_DIAGNOSTIC_RANKED_CANDIDATE_COUNT} diagnostic ranked "
        f"candidates, found {len(diagnostic_rankings)}")
    record("primary_ranked_candidate_count",
           f"{len(primary_rankings)} primary ranks")
    record("diagnostic_ranks_isolated",
           f"{len(diagnostic_rankings)} diagnostic ranks, held separately")

    # The per-Answer counts in the summary must add up to the ranking file.
    summed = sum(_as_int(r["ranked_candidate_count"],
                         f"summary[{r['answer_uri']}].ranked_candidate_count")
                 for r in primary_rows)
    _require(
        summed == len(primary_rankings),
        f"summary ranked_candidate_count sums to {summed} but "
        f"lrolesim_rankings.csv holds {len(primary_rankings)} primary rows")
    record("summary_counts_agree_with_rankings",
           f"summed ranked_candidate_count == {summed}")

    # --- accepted-candidate and context-node discipline -------------------
    accepted_by_key: dict[tuple[str, str], set[str]] = {}
    ranked_flag_by_key: dict[tuple[str, str], set[str]] = {}
    for candidate in inputs.candidates:
        key = (candidate["answer_uri"], candidate["primary_or_diagnostic"])
        if candidate["accepted_into_graph"]:
            accepted_by_key.setdefault(key, set()).add(
                candidate["canonical_candidate_uri"])
        if candidate.get("is_ranked_candidate"):
            ranked_flag_by_key.setdefault(key, set()).add(
                candidate["canonical_candidate_uri"])
        _require(
            not candidate.get("is_context_node_only"),
            f"graph_candidates.jsonl offers context-only node "
            f"{candidate['canonical_candidate_uri']} as a candidate for "
            f"{candidate['answer_uri']}")
        _require(
            not (candidate.get("is_context_node_only")
                 and candidate.get("is_ranked_candidate")),
            f"a context node was ranked for {candidate['answer_uri']}")
    record("no_context_node_offered_as_candidate",
           f"{len(inputs.candidates)} candidate records, none context-only")

    # Node arithmetic: node_count == Answer + accepted candidates + context nodes.
    # This is what makes "no context node is ranked" a checked property rather
    # than a naming convention: the context nodes are exactly the graph nodes that
    # are neither the Answer nor an accepted candidate.
    for manifest in inputs.manifests:
        node_count = _as_int(manifest["node_count"], "manifest.node_count")
        accepted = _as_int(manifest["accepted_candidate_count"],
                           "manifest.accepted_candidate_count")
        context = _as_int(manifest["context_node_count"],
                          "manifest.context_node_count")
        _require(
            node_count == 1 + accepted + context,
            f"{manifest['answer_uri']}: node_count {node_count} != 1 + "
            f"{accepted} accepted + {context} context")
        _require(
            len(manifest["accepted_candidate_uris"]) == accepted,
            f"{manifest['answer_uri']}: accepted_candidate_uris has "
            f"{len(manifest['accepted_candidate_uris'])} entries but "
            f"accepted_candidate_count is {accepted}")
        _require(
            manifest["answer_uri"] not in manifest["accepted_candidate_uris"],
            f"{manifest['answer_uri']} appears among its own accepted candidates")
    record("graph_node_arithmetic",
           "node_count == answer + accepted candidates + context nodes, "
           "for every manifest")

    # --- per-Answer ranking invariants ------------------------------------
    by_answer: dict[tuple[str, str], list[dict]] = {}
    for row in inputs.rankings:
        by_answer.setdefault(
            (row["answer_uri"], row["primary_or_diagnostic"]), []).append(row)

    for (answer_uri, scope), rows in sorted(by_answer.items()):
        label = f"{answer_uri} [{scope}]"
        rows_sorted = sorted(rows, key=lambda r: _as_int(r["rank"], label))

        # measure / lrolesim_beta / iterations are frozen
        for row in rows_sorted:
            _require(row["measure"] == PILOT_MEASURE,
                     f"{label}: measure must be {PILOT_MEASURE}, got "
                     f"{row['measure']!r}")
            _require(_as_float(row["lrolesim_beta"], label) == PILOT_LROLESIM_BETA,
                     f"{label}: lrolesim_beta must be {PILOT_LROLESIM_BETA}, got "
                     f"{row['lrolesim_beta']!r}")
            _require(_as_int(row["iterations"], label) == PILOT_ITERATIONS,
                     f"{label}: iterations must be exactly {PILOT_ITERATIONS}, got "
                     f"{row['iterations']!r}")
            _require(row["iteration_mode"] == PILOT_ITERATION_MODE,
                     f"{label}: iteration_mode must be {PILOT_ITERATION_MODE}, got "
                     f"{row['iteration_mode']!r}")

        # ranks contiguous from 1
        ranks = [_as_int(r["rank"], label) for r in rows_sorted]
        _require(ranks == list(range(1, len(rows_sorted) + 1)),
                 f"{label}: ranks must be contiguous from 1, got {ranks}")

        # descending score, ascending canonical URI on ties, no self-ranking
        previous: Optional[tuple[float, str]] = None
        for row in rows_sorted:
            score = _as_float(row["lrolesim_score"], label)
            uri = row["candidate_uri"]
            _require(uri != answer_uri,
                     f"{label}: the Answer ranks itself at rank {row['rank']}")
            if previous is not None:
                prev_score, prev_uri = previous
                _require(score <= prev_score,
                         f"{label}: score ascends at rank {row['rank']} "
                         f"({prev_score} -> {score})")
                if score == prev_score:
                    _require(prev_uri < uri,
                             f"{label}: tied scores must break on ascending "
                             f"canonical candidate URI, got {prev_uri!r} then "
                             f"{uri!r}")
            previous = (score, uri)

        # every ranked candidate is an approved retained candidate
        accepted = accepted_by_key.get((answer_uri, scope), set())
        ranked_uris = {r["candidate_uri"] for r in rows_sorted}
        stray = sorted(ranked_uris - accepted)
        _require(not stray,
                 f"{label}: ranked candidates that were never accepted into the "
                 f"graph: {stray[:3]}")
        flagged = ranked_flag_by_key.get((answer_uri, scope), set())
        _require(ranked_uris == flagged,
                 f"{label}: lrolesim_rankings.csv and graph_candidates.jsonl "
                 f"disagree on which candidates are ranked")

        manifest = inputs.manifest_for(answer_uri, scope)
        _require(manifest is not None,
                 f"{label}: no graph manifest for a ranked Answer")
        assert manifest is not None
        manifest_accepted = set(manifest["accepted_candidate_uris"])
        _require(ranked_uris == manifest_accepted,
                 f"{label}: ranked candidates differ from the manifest's accepted "
                 f"candidates")

        # class agreement across ranking, manifest and (for primary) summary
        class_uris = {r["selected_class_uri"] for r in rows_sorted}
        _require(len(class_uris) == 1,
                 f"{label}: rankings disagree on the selected class: "
                 f"{sorted(class_uris)}")
        ranking_class = class_uris.pop()
        _require(manifest["class_uri"] == ranking_class,
                 f"{label}: manifest class {manifest['class_uri']!r} != ranking "
                 f"class {ranking_class!r}")

        # graph fingerprint agreement across ranking, manifest and candidates
        fingerprints = {r["graph_fingerprint"] for r in rows_sorted}
        _require(len(fingerprints) == 1,
                 f"{label}: rankings disagree on the graph fingerprint")
        fingerprint = fingerprints.pop()
        _require(manifest["graph_fingerprint"] == fingerprint,
                 f"{label}: manifest graph fingerprint differs from the ranking's")
        candidate_fingerprints = {
            c["graph_fingerprint"] for c in inputs.candidates
            if c["answer_uri"] == answer_uri
            and c["primary_or_diagnostic"] == scope}
        _require(candidate_fingerprints == {fingerprint},
                 f"{label}: graph_candidates.jsonl fingerprints "
                 f"{sorted(candidate_fingerprints)} != {fingerprint}")

        if scope == SCOPE_PRIMARY:
            summary = next((r for r in primary_rows
                            if r["answer_uri"] == answer_uri), None)
            _require(summary is not None,
                     f"{label}: ranked Answer has no primary summary row")
            assert summary is not None
            _require(summary["graph_selected_class_uri"] == ranking_class,
                     f"{label}: summary class "
                     f"{summary['graph_selected_class_uri']!r} != ranking class "
                     f"{ranking_class!r}")
            _require(summary["mapping_selected_class_uri"] == ranking_class,
                     f"{label}: mapping class "
                     f"{summary['mapping_selected_class_uri']!r} != graph class "
                     f"{ranking_class!r}")
            _require(summary["graph_fingerprint"] == fingerprint,
                     f"{label}: summary graph fingerprint differs from the "
                     f"ranking's")
            _require(_as_int(summary["ranked_candidate_count"], label)
                     == len(rows_sorted),
                     f"{label}: summary ranked_candidate_count != number of "
                     f"ranking rows")

    record("selected_class_agrees_across_files",
           "summary, manifest and ranking agree per Answer")
    record("graph_fingerprint_agrees_across_files",
           "summary, manifest, candidates and ranking agree per Answer")
    record("ranks_contiguous_scores_descending_ties_by_uri",
           "checked for every ranked Answer")
    record("answer_never_ranks_itself", "checked for every ranked Answer")
    record("every_ranked_candidate_is_approved_and_retained",
           "ranked set == accepted set, per Answer")
    record("frozen_lrolesim_execution_path",
           f"measure={PILOT_MEASURE}, lrolesim_beta={PILOT_LROLESIM_BETA}, "
           f"iterations={PILOT_ITERATIONS} ({PILOT_ITERATION_MODE})")

    # --- the diagnostic stays outside the primary namespace ---------------
    diagnostic = inputs.diagnostic
    _require(bool(diagnostic.get("diagnostic_only")),
             "sulfuric_acid_diagnostic.json must set diagnostic_only = true")
    _require(bool(diagnostic.get("excluded_from_primary_policy_metrics")),
             "sulfuric_acid_diagnostic.json must set "
             "excluded_from_primary_policy_metrics = true")
    _require(diagnostic.get("answer_uri") == EXPECTED_PRIMARY_FAILURE_ANSWER_URI,
             "the diagnostic must be about Sulfuric acid")
    _require(diagnostic.get("diagnostic_class_uri") == DIAGNOSTIC_CLASS_URI,
             f"the diagnostic class must be {DIAGNOSTIC_CLASS_URI}")
    for row in inputs.rankings:
        if row["primary_or_diagnostic"] == SCOPE_DIAGNOSTIC:
            _require(_as_bool(row["diagnostic_only"], "ranking.diagnostic_only"),
                     "a diagnostic ranking row is not flagged diagnostic_only")
            _require(_as_bool(row["excluded_from_primary_policy_metrics"],
                              "ranking.excluded_from_primary_policy_metrics"),
                     "a diagnostic ranking row is not excluded from primary "
                     "policy metrics")
    record("diagnostic_excluded_from_primary_metrics",
           "diagnostic_only and excluded_from_primary_policy_metrics both set")

    # --- provisional top-3 rows are never final ---------------------------
    for row in inputs.provisional_top3:
        _require(not _as_bool(row["is_final_distractor"],
                              "provisional_top3.is_final_distractor"),
                 "a provisional top-3 row claims to be a final distractor")
    record("provisional_top3_never_final",
           f"{len(inputs.provisional_top3)} rows, all is_final_distractor=false")

    return ContractReport(
        primary_answer_count=len(primary_rows),
        graph_feasible_primary_count=len(feasible),
        primary_failure_answer_uris=failure_uris,
        primary_ranked_candidate_count=len(primary_rankings),
        diagnostic_ranked_candidate_count=len(diagnostic_rankings),
        checks=tuple(checks),
    )


# ==========================================================================
# 3) THE RANKER
# ==========================================================================

def _ranked_candidate_from_row(row: Mapping[str, object]) -> RankedCandidate:
    """Reproduce one Prompt-8C rank verbatim. Nothing is recomputed."""
    label = f"lrolesim_rankings.csv[{row.get('answer_uri')}]"
    return RankedCandidate(
        rank=_as_int(row["rank"], label),
        canonical_candidate_uri=str(row["candidate_uri"]),
        candidate_local_index=_as_int(row["candidate_local_index"], label),
        score=_as_float(row["lrolesim_score"], label),
        tie_group_id=_as_int(row["tie_group_id"], label),
        tie_group_size=_as_int(row["tie_group_size"], label),
        at_beta_floor=_as_bool(row["at_beta_floor"], label),
        candidate_origin=str(row["candidate_origin"]),
        graph_admission_position=_as_int(row["graph_admission_position"], label),
    )


class LRoleSimHandoffRanker:
    """CandidateRanker over the verified Prompt-8C LRoleSim rankings.

    Implements the proposed pilot path `lrolesim_m1_fixed_k3` by REPRODUCING the
    frozen ranks. It holds no graph, no kernel and no scoring code, so there is no
    way for it to disagree with Prompt-8C's numbers.
    """

    name = RANKER_LROLESIM_M1_FIXED_K3

    def __init__(self, inputs: Prompt8CInputs, report: Optional[ContractReport] = None):
        self._inputs = inputs
        self._report = report if report is not None else validate_prompt8c_contract(inputs)
        self._rankings: dict[tuple[str, str], CandidateRanking] = {}
        self._build()

    # --- construction -----------------------------------------------------
    def _build(self) -> None:
        grouped: dict[tuple[str, str], list[dict]] = {}
        for row in self._inputs.rankings:
            grouped.setdefault(
                (row["answer_uri"], row["primary_or_diagnostic"]), []).append(row)

        summary_by_uri = {r["answer_uri"]: r
                          for r in self._inputs.primary_summary_rows()}

        for (answer_uri, scope), rows in grouped.items():
            rows_sorted = sorted(rows, key=lambda r: _as_int(r["rank"], answer_uri))
            manifest = self._inputs.manifest_for(answer_uri, scope)
            assert manifest is not None      # guaranteed by validation
            first = rows_sorted[0]
            summary = summary_by_uri.get(answer_uri)
            answer_local_index = _as_int(
                manifest["answer_local_index"], f"manifest[{answer_uri}]")
            if scope == SCOPE_PRIMARY and summary is not None:
                answer_local_index = _as_int(
                    summary["answer_local_index"], f"summary[{answer_uri}]")

            self._rankings[(answer_uri, scope)] = CandidateRanking(
                ranker_name=self.name,
                answer_uri=answer_uri,
                answer_local_index=answer_local_index,
                selected_class_uri=str(first["selected_class_uri"]),
                graph_fingerprint=str(first["graph_fingerprint"]),
                measure=str(first["measure"]),
                lrolesim_beta=_as_float(first["lrolesim_beta"], answer_uri),
                iterations=_as_int(first["iterations"], answer_uri),
                iteration_mode=str(first["iteration_mode"]),
                primary_or_diagnostic=scope,
                ranked=tuple(_ranked_candidate_from_row(r) for r in rows_sorted),
            )

    # --- CandidateRanker --------------------------------------------------
    def ranking_for_answer(self, answer_uri: str) -> CandidateRanking:
        """The primary ranking for one Answer.

        Raises for a graph-infeasible Answer instead of returning an empty
        ranking: "Sulfuric acid has no feasible approved class" and "Sulfuric acid
        has zero plausible candidates" are different findings.
        """
        ranking = self._rankings.get((answer_uri, SCOPE_PRIMARY))
        if ranking is None:
            raise HandoffError(
                f"no primary LRoleSim ranking for {answer_uri!r}; a graph-"
                f"infeasible Answer has no ranking, and this must not be read as "
                f"an empty one")
        return ranking

    def diagnostic_ranking_for_answer(self, answer_uri: str) -> CandidateRanking:
        """The DIAGNOSTIC ranking, kept behind a separate method on purpose."""
        ranking = self._rankings.get((answer_uri, SCOPE_DIAGNOSTIC))
        if ranking is None:
            raise HandoffError(f"no diagnostic ranking for {answer_uri!r}")
        return ranking

    # --- accessors --------------------------------------------------------
    @property
    def report(self) -> ContractReport:
        return self._report

    @property
    def inputs(self) -> Prompt8CInputs:
        return self._inputs

    def primary_answer_uris(self) -> tuple[str, ...]:
        """All nine primary Answers, in pilot-slot order."""
        rows = sorted(self._inputs.primary_summary_rows(),
                      key=lambda r: _as_int(r["pilot_slot"], "summary.pilot_slot"))
        return tuple(r["answer_uri"] for r in rows)

    def graph_feasible_primary_answer_uris(self) -> tuple[str, ...]:
        return tuple(uri for uri in self.primary_answer_uris()
                     if (uri, SCOPE_PRIMARY) in self._rankings)

    def has_primary_ranking(self, answer_uri: str) -> bool:
        return (answer_uri, SCOPE_PRIMARY) in self._rankings


# ==========================================================================
# 4) BUILDING THE RATIONALE-SELECTION HANDOFF
# ==========================================================================

def build_handoff_for_answer(ranker: LRoleSimHandoffRanker,
                             answer_uri: str) -> RationaleSelectionHandoff:
    """One primary handoff record, feasible or not.

    A graph-infeasible Answer still gets a record: the pilot's denominator is nine
    Answers, and dropping the failure would inflate every rate computed from this
    file.
    """
    summary = next((r for r in ranker.inputs.primary_summary_rows()
                    if r["answer_uri"] == answer_uri), None)
    if summary is None:
        raise HandoffError(f"{answer_uri!r} is not a primary pilot Answer")

    pilot_slot = _as_int(summary["pilot_slot"], "summary.pilot_slot")
    answer_local_index = _as_int(summary["answer_local_index"],
                                 "summary.answer_local_index")

    if not ranker.has_primary_ranking(answer_uri):
        # The Sulfuric-acid case. No class, no graph, no fingerprint, no measure —
        # every one of those is genuinely absent, so none is invented.
        return RationaleSelectionHandoff(
            answer_uri=answer_uri,
            answer_local_index=answer_local_index,
            selected_class_uri=None,
            mapping_stage_status=summary["mapping_stage_status"],
            graph_stage_status=summary["graph_stage_status"],
            graph_fingerprint=None,
            ranker_name=RANKER_LROLESIM_M1_FIXED_K3,
            measure=None,
            lrolesim_beta=None,
            iterations=None,
            ranked_candidate_count=0,
            ranked_candidates=(),
            provisional_lrolesim_top3=(),
            rationale_selection_status=RATIONALE_SELECTION_DEFERRED,
            primary_or_diagnostic=SCOPE_PRIMARY,
            pilot_slot=pilot_slot,
            display_label=summary["display_label"],
            ready_for_rationale_selection=False,
        )

    ranking = ranker.ranking_for_answer(answer_uri)
    return RationaleSelectionHandoff(
        answer_uri=answer_uri,
        answer_local_index=answer_local_index,
        selected_class_uri=ranking.selected_class_uri,
        mapping_stage_status=summary["mapping_stage_status"],
        graph_stage_status=summary["graph_stage_status"],
        graph_fingerprint=ranking.graph_fingerprint,
        ranker_name=ranking.ranker_name,
        measure=ranking.measure,
        lrolesim_beta=ranking.lrolesim_beta,
        iterations=ranking.iterations,
        ranked_candidate_count=ranking.ranked_candidate_count,
        ranked_candidates=ranking.ranked,
        provisional_lrolesim_top3=ranking.top(PROVISIONAL_TOP_N),
        rationale_selection_status=RATIONALE_SELECTION_DEFERRED,
        primary_or_diagnostic=SCOPE_PRIMARY,
        pilot_slot=pilot_slot,
        display_label=summary["display_label"],
        ready_for_rationale_selection=True,
    )


def build_primary_handoffs(ranker: LRoleSimHandoffRanker
                           ) -> tuple[RationaleSelectionHandoff, ...]:
    """All nine primary handoffs, in pilot-slot order."""
    return tuple(build_handoff_for_answer(ranker, uri)
                 for uri in ranker.primary_answer_uris())


def build_diagnostic_handoff(ranker: LRoleSimHandoffRanker
                             ) -> RationaleSelectionHandoff:
    """The Sulfuric-acid diagnostic handoff, in its own namespace."""
    answer_uri = EXPECTED_PRIMARY_FAILURE_ANSWER_URI
    ranking = ranker.diagnostic_ranking_for_answer(answer_uri)
    manifest = ranker.inputs.manifest_for(answer_uri, SCOPE_DIAGNOSTIC)
    assert manifest is not None
    diagnostic = ranker.inputs.diagnostic
    return RationaleSelectionHandoff(
        answer_uri=answer_uri,
        answer_local_index=_as_int(manifest["answer_local_index"],
                                   "diagnostic manifest.answer_local_index"),
        selected_class_uri=ranking.selected_class_uri,
        mapping_stage_status=str(diagnostic.get("diagnostic_mapping_status",
                                                "DIAGNOSTIC_MAPPING_FEASIBLE")),
        graph_stage_status=str(diagnostic.get("diagnostic_graph_status", "")),
        graph_fingerprint=ranking.graph_fingerprint,
        ranker_name=ranking.ranker_name,
        measure=ranking.measure,
        lrolesim_beta=ranking.lrolesim_beta,
        iterations=ranking.iterations,
        ranked_candidate_count=ranking.ranked_candidate_count,
        ranked_candidates=ranking.ranked,
        provisional_lrolesim_top3=ranking.top(PROVISIONAL_TOP_N),
        rationale_selection_status=RATIONALE_SELECTION_DEFERRED,
        primary_or_diagnostic=SCOPE_DIAGNOSTIC,
        pilot_slot=_as_int(manifest["pilot_slot"], "diagnostic manifest.pilot_slot"),
        display_label="Sulfuric acid",
        ready_for_rationale_selection=False,
    )
