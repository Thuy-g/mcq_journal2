############################################################################
# src/pipeline/rationale_selection_run.py
#
# PROMPT 8E ORCHESTRATION — exact rationale set cover and evidence-aware final
# distractor selection.
#
# WHAT THIS RUN CONSUMES
#   The FROZEN Prompt-8D handoff in
#   outputs/journal2_week2_extract_integration_2026-07-30/, and nothing else:
#
#       candidate_ranking_handoff.jsonl   9 primary Answers, 204 ranked candidates
#       observed_answer_facts.jsonl       582 observed Answer facts
#       observed_candidate_facts.jsonl    3,785 observed candidate facts
#       observed_diagnostic_facts.jsonl   18 Sulfuric-acid diagnostic facts
#       extract_integration_summary.csv   the nine-row primary denominator
#       provisional_top3_handoff.csv      structural diagnostics, never final
#       sulfuric_acid_diagnostic_handoff.json
#       contract_validation.json
#
#   The pinned 1.2 GB pickle is NOT loaded. Every fact this run reasons about was
#   already serialized from it by Prompt 8D, so re-reading the KG could only
#   introduce a second, unverified source of truth for the same observations.
#
# WHAT THIS RUN MUST NOT TOUCH  (Prompt 8E §2)
#   No HTTP, no SPARQL, no spaCy, no SBERT, no DBpedia abstracts, no class
#   selection, no M1 graph rebuild, no LRoleSim recomputation, no
#   OverlapStrict/OverlapLoose, no lrolesim_edt. The ranker stays
#   lrolesim_m1_fixed_k3 with measure lrolesim_ed, lrolesim_beta 0.2 and exactly
#   three fixed iterations, all READ from the frozen records and asserted here.
#
# WHERE THIS STOPS
#   Before natural-language verbalization and before external human factual
#   validation. Every algorithm-selected record carries
#   requires_human_validation = true, human_validation_status = NOT_CHECKED and
#   publishable_final = false, under BOTH evidence policies.
#
# THE SULFURIC-ACID BOUNDARY
#   Sulfuric acid stays the ONE primary failure, with a primary summary row and
#   PRIMARY_NOT_READY. Its six diagnostic candidates are analysed in a separate
#   namespace and enter no primary denominator, success rate or candidate count.
#
# OPEN WORLD
#   Every emitted fact is OBSERVED in the pinned snapshot. No negative fact is
#   generated, and no absence is reported as falsity (CLAUDE.md items 7 and 8).
############################################################################

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import resource
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rationale.contracts import (                                    # noqa: E402
    DEFAULT_K,
    DEFAULT_RHO,
    DIRECTION_IN,
    DIRECTION_OUT,
    EVIDENCE_ABSENCE_ONLY_OBSERVED,
    EVIDENCE_POSITIVE_ALTERNATIVE_OBSERVED,
    EVIDENCE_SHARED_OBSERVED,
    FACT_SOURCE_PINNED_LOCAL_KG,
    HUMAN_VALIDATION_NOT_CHECKED,
    LEGACY_ONE_FACT_SPECIAL_CASE_NOTE,
    POLICY_NOTE,
    POLICY_POSITIVE_OBSERVED,
    POLICY_PRIORITY,
    POLICY_SNAPSHOT_OBSERVED,
    PREDICATE_FUNCTIONALITY_NOTE,
    REQUIRES_FALLBACK_CLASS,
    RHO_ABLATION_VALUES,
    SELECTION_NO_FULL_COVERAGE,
    SELECTION_POSITIVE_OBSERVED,
    SELECTION_PRIMARY_NOT_READY,
    SELECTION_SNAPSHOT_OBSERVED,
    SET_COVER_ALGORITHM,
    SET_COVER_COMPLEXITY,
    AnswerFact,
    RationaleContractError,
    assert_no_negative_claim,
)
from rationale.contrasts import build_answer_contrast_table              # noqa: E402
from rationale.selector import (                                         # noqa: E402
    AUDIT_TOP_COMBINATIONS,
    AnswerSelection,
    AnswerSelectionInput,
    RankedCandidateView,
    not_ready_selection,
    rationale_cover_for,
    select_for_answer,
    selected_rationale_records,
)

# ==========================================================================
# 0) PINNED INPUTS
# ==========================================================================

FROZEN_PROMPT8D_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_extract_integration_2026-07-30")
FROZEN_PROMPT8D_ZIP = (
    REPO_ROOT / "outputs" / "journal2_week2_extract_integration_2026-07-30.zip")
FROZEN_PROMPT8D_ZIP_SHA256 = (
    "d2a0ff793f64767c0413c3b9f116791abecdeafdf51c4bff3eaf2ee331cae404")
PINNED_LOCAL_KG_SHA256 = (
    "e230c5b95e20093631697624d9c46f30a14081b3f415d5027ffaf313bdbbea1b")

DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_rationale_selection_2026-08-01")

REQUIRED_INPUT_FILES = (
    "candidate_ranking_handoff.jsonl",
    "extract_integration_summary.csv",
    "observed_answer_facts.jsonl",
    "observed_candidate_facts.jsonl",
    "observed_diagnostic_facts.jsonl",
    "provisional_top3_handoff.csv",
    "sulfuric_acid_diagnostic_handoff.json",
    "contract_validation.json",
)

# Frozen Prompt-8C and Prompt-8D sources. Prompt 8E must not change any of them,
# so their hashes are checked at run time and published, not merely promised.
#
# src/extract_221_and_select_distractors_ClaudeWeb_v2.py is DELIBERATELY ABSENT:
# Prompt 8E narrowly patches that entrypoint to expose the new mode, and listing a
# file here that this task is authorised to change would make the check a
# formality. Its before/after hashes are published in
# source_hashes_before_after.csv instead.
PROTECTED_SOURCES = {
    "candidate_order": (
        SRC_DIR / "pipeline" / "candidate_order.py",
        "8a6e9b36f9a393de8a4f287305f4545f78e4090b34a83f0b3ebcea76cbc0e1f2"),
    "graph_lrolesim_run": (
        SRC_DIR / "pipeline" / "graph_lrolesim_run.py",
        "2c1242dbe7dfd7608a3dd09d7ff71bcd672880968b1bcdfdbd7fe45d628eb994"),
    "graph_view": (
        SRC_DIR / "kg" / "graph_view.py",
        "0ed2733307ef8116b4ba79c906e8e880711e06f011418b0da3104e4c99716ec4"),
    "lrolesim_adapter": (
        SRC_DIR / "lrolesim" / "adapter.py",
        "2100fd112b144a4d71d2b0be0ef3465b3c73c9f8d5d8ad78b28a587185d65f33"),
    "lrolesim_kernel": (
        SRC_DIR / "MCQ_lrolesim_ClaudeWeb_v2.py",
        "b7c3678ee531a291dee874053529ac498d8c7674b892cff19e817808671ddec0"),
    "selection_init": (
        SRC_DIR / "selection" / "__init__.py",
        "912a0a49867006645667d43d989fc0a87492edbf59da5c925955c1aa6c9a375a"),
    "selection_contracts": (
        SRC_DIR / "selection" / "contracts.py",
        "a271f28eaf0492604232fe3f0a2810346e3db98fee64aa9dd1236ce6219752ec"),
    "selection_observed_facts": (
        SRC_DIR / "selection" / "observed_facts.py",
        "78f0543252851177e19389626ed17a34440d0f941b18c4bb8b4e7ffdaaa8364d"),
    "selection_lrolesim_handoff": (
        SRC_DIR / "selection" / "lrolesim_handoff.py",
        "c4fc4077743f3f4874d3abda91a0ee4d13ce5256c47a691e3988c99e708ce26d"),
    "selection_legacy_overlap": (
        SRC_DIR / "selection" / "legacy_overlap.py",
        "a50dd4435f65f831b2c641219445a917f0e5851a6e35ace3aacc1f061e5f014d"),
}

# --- The expected Prompt-8D shape, asserted rather than assumed (§4) --------
EXPECTED_PRIMARY_ANSWER_COUNT = 9
EXPECTED_READY_ANSWER_COUNT = 8
EXPECTED_PRIMARY_RANKED_CANDIDATE_COUNT = 204
EXPECTED_DIAGNOSTIC_RANKED_CANDIDATE_COUNT = 6
EXPECTED_PRIMARY_FAILURE_ANSWER_URI = "http://dbpedia.org/resource/Sulfuric_acid"

# --- The frozen LRoleSim execution path, asserted (§2) ----------------------
EXPECTED_RANKER_NAME = "lrolesim_m1_fixed_k3"
EXPECTED_MEASURE = "lrolesim_ed"
EXPECTED_LROLESIM_BETA = 0.2
EXPECTED_ITERATIONS = 3
EXPECTED_ITERATION_MODE = "fixed"

#: Files a strict offline replay must reproduce byte for byte. Timing, clock and
#: Git-state artefacts are excluded by construction, not by tolerance.
REPLAY_COMPARED_FILES = (
    "rationale_selection_summary.csv",
    "algorithm_selected_distractors.jsonl",
    "selected_rationales.jsonl",
    "fact_coverage.jsonl",
    "triple_search_audit.jsonl",
    "partial_coverage_diagnostics.jsonl",
    "rho_ablation.csv",
    "sulfuric_acid_diagnostic_rationale.json",
)

#: Modules whose presence in sys.modules would contradict the zero-network,
#: zero-model claim. Checked after the run, and published in the manifest.
FORBIDDEN_MODULE_PREFIXES = (
    "spacy",
    "sentence_transformers",
    "torch",
    "SPARQLWrapper",
    "requests",
    "urllib3",
    "httpx",
    "classes.sparql_client",
    "classes.member_mapper",
    "classes.page_cache",
    "category_extractor_ClaudeWeb_v2",
    "category_extractor_ClaudeWeb_v3",
    "category_extractor_ClaudeWeb_v4",
    "selection.legacy_overlap",
    "kg.loader",
    "kg.graph_view",
    "lrolesim.adapter",
    "MCQ_lrolesim_ClaudeWeb_v2",
    "pipeline.graph_lrolesim_run",
)


class RationaleSelectionError(Exception):
    """Base class for Prompt-8E rationale-selection failures."""


class Prompt8DInputError(RationaleSelectionError):
    """A frozen Prompt-8D input file is missing, unreadable or inconsistent."""


class ProtectedSourceModifiedError(RationaleSelectionError):
    """A frozen Prompt-8C/8D source file no longer has its expected SHA-256."""


class OfflineGuardTripped(RationaleSelectionError):
    """The rationale-selection path attempted an outbound connection."""


# ==========================================================================
# 1) OFFLINE GUARD
# ==========================================================================

@dataclass
class OfflineGuard:
    """Blocks and counts outbound socket connections for the whole run.

    Prompt 8E claims zero HTTP and zero SPARQL calls. A guard that FAILS the run
    makes that a checked property rather than an assurance, and the published
    counter is the evidence.
    """

    attempts: list[str] = field(default_factory=list)
    _installed: bool = False
    _saved: dict = field(default_factory=dict)

    def install(self) -> None:
        if self._installed:
            return
        guard = self

        def blocked_connect(self, address, *a, **k):          # noqa: ANN001
            guard.attempts.append(repr(address))
            raise OfflineGuardTripped(
                f"outbound connection to {address!r} refused: Prompt 8E reads "
                f"only the frozen Prompt-8D handoff")

        def blocked_connect_ex(self, address, *a, **k):        # noqa: ANN001
            guard.attempts.append(repr(address))
            raise OfflineGuardTripped(
                f"outbound connection to {address!r} refused")

        def blocked_create(address, *a, **k):                  # noqa: ANN001
            guard.attempts.append(repr(address))
            raise OfflineGuardTripped(
                f"outbound connection to {address!r} refused")

        self._saved = {
            "connect": socket.socket.connect,
            "connect_ex": socket.socket.connect_ex,
            "create_connection": socket.create_connection,
        }
        socket.socket.connect = blocked_connect            # type: ignore[method-assign]
        socket.socket.connect_ex = blocked_connect_ex      # type: ignore[method-assign]
        socket.create_connection = blocked_create          # type: ignore[assignment]
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        socket.socket.connect = self._saved["connect"]              # type: ignore[method-assign]
        socket.socket.connect_ex = self._saved["connect_ex"]        # type: ignore[method-assign]
        socket.create_connection = self._saved["create_connection"]  # type: ignore[assignment]
        self._installed = False

    def as_record(self) -> dict:
        return {
            "installed": self._installed,
            "network_attempts": len(self.attempts),
            "http_calls": len(self.attempts),
            "sparql_calls": len(self.attempts),
            "attempted_addresses": list(self.attempts),
        }


def loaded_forbidden_modules() -> list[str]:
    """Which forbidden modules this process imported. Expected: none."""
    loaded = []
    for name in sorted(sys.modules):
        for prefix in FORBIDDEN_MODULE_PREFIXES:
            if name == prefix or name.startswith(prefix + "."):
                loaded.append(name)
                break
    return loaded


# ==========================================================================
# 2) DETERMINISTIC WRITERS
# ==========================================================================

def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"))


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_jsonl(path: Path, records: Iterable[Mapping[str, object]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        for record in records:
            f.write(_canonical_json(record) + "\n")


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=True)
        f.write("\n")


def _b(value: bool) -> str:
    return "true" if value else "false"


def _fmt_score(score: float) -> str:
    """Shortest round-tripping decimal form, matching the Prompt-8C/8D writers."""
    return repr(float(score))


def sha256_file(path: str | Path, chunk_size: int = 1 << 23) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_protected_sources() -> dict:
    """Confirm every frozen Prompt-8C/8D source is byte-identical to its pin."""
    observed = {}
    drift = []
    for name, (path, expected) in sorted(PROTECTED_SOURCES.items()):
        digest = sha256_file(path)
        observed[name] = {
            "path": str(path.relative_to(REPO_ROOT)),
            "expected_sha256": expected,
            "observed_sha256": digest,
            "unmodified": digest == expected,
        }
        if digest != expected:
            drift.append(name)
    if drift:
        raise ProtectedSourceModifiedError(
            f"frozen Prompt-8C/8D sources changed: {drift}. Prompt 8E must not "
            f"modify the graph, ordering, LRoleSim or selection layers.")
    return observed


# ==========================================================================
# 3) READING THE FROZEN PROMPT-8D HANDOFF
# ==========================================================================

def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise Prompt8DInputError(f"frozen Prompt-8D input not found: {path}")
    records = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise Prompt8DInputError(f"{path.name} line {lineno}: {exc}") from exc
    return records


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise Prompt8DInputError(f"frozen Prompt-8D input not found: {path}")
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise Prompt8DInputError(f"frozen Prompt-8D input not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@dataclass(frozen=True)
class Prompt8DInputs:
    """The frozen Prompt-8D artefacts, read and shape-checked."""

    source_dir: Path
    handoffs: tuple[dict, ...]
    summary: tuple[dict, ...]
    answer_facts: tuple[dict, ...]
    candidate_facts: tuple[dict, ...]
    diagnostic_facts: tuple[dict, ...]
    provisional_top3: tuple[dict, ...]
    diagnostic_handoff: Mapping[str, object]
    contract_validation: Mapping[str, object]
    input_sha256: Mapping[str, str]
    contract_checks: tuple[tuple[str, str], ...] = ()

    def ready_handoffs(self) -> list[dict]:
        return [h for h in self.handoffs if h["ready_for_rationale_selection"]]

    def with_checks(self, checks: Sequence[tuple[str, str]]) -> "Prompt8DInputs":
        return Prompt8DInputs(**{**vars(self), "contract_checks": tuple(checks)})


def load_prompt8d_handoff(source_dir: str | Path) -> Prompt8DInputs:
    """Read the frozen Prompt-8D handoff and assert the §4 input contract."""
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise Prompt8DInputError(
            f"frozen Prompt-8D output directory not found: {source_dir}")
    missing = [name for name in REQUIRED_INPUT_FILES
               if not (source_dir / name).is_file()]
    if missing:
        raise Prompt8DInputError(
            f"{source_dir}: missing frozen Prompt-8D inputs {missing}")

    inputs = Prompt8DInputs(
        source_dir=source_dir,
        handoffs=tuple(_read_jsonl(source_dir / "candidate_ranking_handoff.jsonl")),
        summary=tuple(_read_csv(source_dir / "extract_integration_summary.csv")),
        answer_facts=tuple(_read_jsonl(source_dir / "observed_answer_facts.jsonl")),
        candidate_facts=tuple(
            _read_jsonl(source_dir / "observed_candidate_facts.jsonl")),
        diagnostic_facts=tuple(
            _read_jsonl(source_dir / "observed_diagnostic_facts.jsonl")),
        provisional_top3=tuple(
            _read_csv(source_dir / "provisional_top3_handoff.csv")),
        diagnostic_handoff=_read_json(
            source_dir / "sulfuric_acid_diagnostic_handoff.json"),
        contract_validation=_read_json(source_dir / "contract_validation.json"),
        input_sha256={name: sha256_file(source_dir / name)
                      for name in sorted(REQUIRED_INPUT_FILES)},
    )
    # Validated HERE rather than by the caller, so there is no way to obtain a
    # Prompt8DInputs whose §4 contract was never checked. The observed checks are
    # carried on the object so the run does not repeat the work to report them.
    return inputs.with_checks(validate_prompt8d_contract(inputs))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Prompt8DInputError(message)


def validate_prompt8d_contract(inputs: Prompt8DInputs) -> list[tuple[str, str]]:
    """Assert the §4 input contract against the frozen records.

    Every number Prompt 8E reports downstream is a consequence of these, so they
    are checked once, here, and never re-derived from a different file later.
    """
    checks: list[tuple[str, str]] = []

    _require(len(inputs.handoffs) == EXPECTED_PRIMARY_ANSWER_COUNT,
             f"expected {EXPECTED_PRIMARY_ANSWER_COUNT} primary handoff records, "
             f"found {len(inputs.handoffs)}")
    _require(len(inputs.summary) == EXPECTED_PRIMARY_ANSWER_COUNT,
             f"expected {EXPECTED_PRIMARY_ANSWER_COUNT} primary summary rows, "
             f"found {len(inputs.summary)}")
    checks.append(("nine_primary_records",
                   f"{len(inputs.handoffs)} handoffs, {len(inputs.summary)} "
                   f"summary rows"))

    ready = inputs.ready_handoffs()
    _require(len(ready) == EXPECTED_READY_ANSWER_COUNT,
             f"expected {EXPECTED_READY_ANSWER_COUNT} Answers ready for rationale "
             f"selection, found {len(ready)}")
    checks.append(("eight_ready_answers", f"{len(ready)} ready"))

    not_ready = [h for h in inputs.handoffs
                 if not h["ready_for_rationale_selection"]]
    _require(len(not_ready) == 1
             and not_ready[0]["answer_uri"] == EXPECTED_PRIMARY_FAILURE_ANSWER_URI,
             f"the one primary failure must be "
             f"{EXPECTED_PRIMARY_FAILURE_ANSWER_URI}, found "
             f"{[h['answer_uri'] for h in not_ready]}")
    _require(not_ready[0]["ranked_candidate_count"] == 0,
             "the primary failure must carry no ranked candidate")
    checks.append(("sulfuric_acid_primary_failure_preserved",
                   f"{not_ready[0]['mapping_stage_status']} / "
                   f"{not_ready[0]['graph_stage_status']}"))

    ranked_total = sum(h["ranked_candidate_count"] for h in inputs.handoffs)
    _require(ranked_total == EXPECTED_PRIMARY_RANKED_CANDIDATE_COUNT,
             f"expected {EXPECTED_PRIMARY_RANKED_CANDIDATE_COUNT} primary ranked "
             f"candidates, found {ranked_total}")
    checks.append(("primary_ranked_candidate_count", f"{ranked_total} ranks"))

    diagnostic_ranked = inputs.diagnostic_handoff["diagnostic_handoff"][
        "ranked_candidate_count"]
    _require(diagnostic_ranked == EXPECTED_DIAGNOSTIC_RANKED_CANDIDATE_COUNT,
             f"expected {EXPECTED_DIAGNOSTIC_RANKED_CANDIDATE_COUNT} diagnostic "
             f"ranked candidates, found {diagnostic_ranked}")
    _require(bool(inputs.diagnostic_handoff["diagnostic_only"]),
             "the Sulfuric-acid diagnostic must be flagged diagnostic_only")
    _require(bool(inputs.diagnostic_handoff[
        "excluded_from_primary_policy_metrics"]),
             "the Sulfuric-acid diagnostic must be excluded from primary metrics")
    checks.append(("diagnostic_ranks_isolated",
                   f"{diagnostic_ranked} diagnostic ranks, held separately"))

    # The frozen LRoleSim execution path. Read, asserted, never reconfigured.
    for handoff in ready:
        label = handoff["answer_uri"]
        _require(handoff["ranker_name"] == EXPECTED_RANKER_NAME,
                 f"{label}: ranker_name must be {EXPECTED_RANKER_NAME}")
        _require(handoff["measure"] == EXPECTED_MEASURE,
                 f"{label}: measure must be {EXPECTED_MEASURE}")
        _require(float(handoff["lrolesim_beta"]) == EXPECTED_LROLESIM_BETA,
                 f"{label}: lrolesim_beta must be {EXPECTED_LROLESIM_BETA}")
        _require(int(handoff["iterations"]) == EXPECTED_ITERATIONS,
                 f"{label}: iterations must be exactly {EXPECTED_ITERATIONS}")
        _require(handoff["iteration_mode"] == EXPECTED_ITERATION_MODE,
                 f"{label}: iteration_mode must be {EXPECTED_ITERATION_MODE}")
        _require(len(handoff["ranked_candidates"])
                 == handoff["ranked_candidate_count"],
                 f"{label}: ranked_candidates length disagrees with the count")
        ranks = [c["rank"] for c in handoff["ranked_candidates"]]
        _require(ranks == list(range(1, len(ranks) + 1)),
                 f"{label}: ranks must be contiguous from 1")
        for candidate in handoff["ranked_candidates"]:
            _require(not candidate["is_final_distractor"],
                     f"{label}: a frozen ranking row claims to be a final "
                     f"distractor")
    checks.append(("frozen_lrolesim_execution_path",
                   f"measure={EXPECTED_MEASURE}, "
                   f"lrolesim_beta={EXPECTED_LROLESIM_BETA}, "
                   f"iterations={EXPECTED_ITERATIONS} "
                   f"({EXPECTED_ITERATION_MODE})"))

    # The provisional top three are structural diagnostics only.
    for row in inputs.provisional_top3:
        _require(row["is_final_distractor"] == "false",
                 "a provisional top-3 row claims to be a final distractor")
    checks.append(("provisional_top3_never_final",
                   f"{len(inputs.provisional_top3)} rows, all "
                   f"is_final_distractor=false"))

    # Fact provenance: every fact belongs to the Answer graph it names.
    fingerprint_by_answer = {h["answer_uri"]: h["graph_fingerprint"]
                             for h in ready}
    for record in inputs.answer_facts:
        expected = fingerprint_by_answer.get(record["answer_uri"])
        _require(expected is not None and record["graph_fingerprint"] == expected,
                 f"observed Answer fact for {record['answer_uri']} carries graph "
                 f"fingerprint {record['graph_fingerprint']!r}")
        _require(record["owner_uri"] == record["answer_uri"],
                 "an observed Answer fact is not owned by its Answer")
    ranked_uris_by_answer = {
        h["answer_uri"]: {c["canonical_candidate_uri"]
                          for c in h["ranked_candidates"]}
        for h in ready}
    for record in inputs.candidate_facts:
        answer_uri = record["answer_uri"]
        expected = fingerprint_by_answer.get(answer_uri)
        _require(expected is not None and record["graph_fingerprint"] == expected,
                 f"observed candidate fact for {answer_uri} carries graph "
                 f"fingerprint {record['graph_fingerprint']!r}")
        _require(record["owner_uri"] in ranked_uris_by_answer[answer_uri],
                 f"{answer_uri}: observed facts exist for "
                 f"{record['owner_uri']}, which is not a ranked candidate. A "
                 f"context node must never become a candidate.")
        _require(record["owner_uri"] != answer_uri,
                 f"{answer_uri}: a candidate fact is owned by the Answer itself")
    checks.append(("every_fact_belongs_to_its_answer_graph",
                   f"{len(inputs.answer_facts)} Answer facts, "
                   f"{len(inputs.candidate_facts)} candidate facts"))
    checks.append(("no_context_node_became_a_candidate",
                   "every candidate fact owner is a ranked candidate"))

    return checks


# ==========================================================================
# 4) BUILDING THE SELECTION INPUTS
# ==========================================================================

def _answer_fact_from_record(record: Mapping[str, object]) -> AnswerFact:
    return AnswerFact(
        predicate_uri=str(record["predicate_uri"]),
        direction=str(record["direction"]),
        counterpart_uri=str(record["counterpart_uri"]),
        graph_fingerprint=str(record["graph_fingerprint"]),
        owner_uri=str(record["owner_uri"]),
    )


def build_selection_inputs(inputs: Prompt8DInputs
                           ) -> tuple[AnswerSelectionInput, ...]:
    """One AnswerSelectionInput per READY primary Answer, in pilot-slot order.

    The COMPLETE ranked candidate list is used, never
    `provisional_lrolesim_top3`: those three are structural diagnostics, and
    restricting the search to them would make rationale feasibility a filter
    applied after the choice rather than a constraint on it (Prompt 8E §4).
    """
    answer_facts_by_uri: dict[str, list[AnswerFact]] = {}
    for record in inputs.answer_facts:
        answer_facts_by_uri.setdefault(str(record["answer_uri"]), []).append(
            _answer_fact_from_record(record))

    candidate_facts_by_answer: dict[str, dict[str, list[AnswerFact]]] = {}
    for record in inputs.candidate_facts:
        bucket = candidate_facts_by_answer.setdefault(
            str(record["answer_uri"]), {})
        bucket.setdefault(str(record["owner_uri"]), []).append(
            _answer_fact_from_record(record))

    built: list[AnswerSelectionInput] = []
    for handoff in sorted(inputs.ready_handoffs(),
                          key=lambda h: int(h["pilot_slot"])):
        answer_uri = str(handoff["answer_uri"])
        fingerprint = str(handoff["graph_fingerprint"])
        ranked = tuple(
            RankedCandidateView(
                rank=int(candidate["rank"]),
                canonical_candidate_uri=str(candidate["canonical_candidate_uri"]),
                candidate_local_index=int(candidate["candidate_local_index"]),
                score=float(candidate["score"]),
            )
            for candidate in sorted(handoff["ranked_candidates"],
                                    key=lambda c: int(c["rank"])))
        table = build_answer_contrast_table(
            answer_uri=answer_uri,
            graph_fingerprint=fingerprint,
            answer_facts=answer_facts_by_uri.get(answer_uri, []),
            candidate_facts=candidate_facts_by_answer.get(answer_uri, {}),
            candidate_order=tuple(
                (candidate.canonical_candidate_uri, candidate.rank)
                for candidate in ranked),
        )
        built.append(AnswerSelectionInput(
            answer_uri=answer_uri,
            answer_local_index=int(handoff["answer_local_index"]),
            display_label=str(handoff["display_label"]),
            pilot_slot=int(handoff["pilot_slot"]),
            selected_class_uri=str(handoff["selected_class_uri"]),
            graph_fingerprint=fingerprint,
            ranker_name=str(handoff["ranker_name"]),
            measure=str(handoff["measure"]),
            lrolesim_beta=float(handoff["lrolesim_beta"]),
            iterations=int(handoff["iterations"]),
            iteration_mode=str(handoff["iteration_mode"]),
            ranked_candidates=ranked,
            table=table,
        ))
    return tuple(built)


def build_diagnostic_input(inputs: Prompt8DInputs
                           ) -> Optional[AnswerSelectionInput]:
    """The Sulfuric-acid DIAGNOSTIC input, in its own namespace.

    Engineering evidence only. Nothing built here enters a primary denominator,
    success rate or candidate count, and the primary Sulfuric-acid row stays
    PRIMARY_NOT_READY regardless of what this analysis finds.
    """
    handoff = inputs.diagnostic_handoff["diagnostic_handoff"]
    fingerprint = str(handoff["graph_fingerprint"])
    answer_uri = str(handoff["answer_uri"])

    answer_facts: list[AnswerFact] = []
    candidate_facts: dict[str, list[AnswerFact]] = {}
    for record in inputs.diagnostic_facts:
        fact = _answer_fact_from_record(record)
        if record["owner_role"] == "answer":
            answer_facts.append(fact)
        else:
            candidate_facts.setdefault(str(record["owner_uri"]), []).append(fact)

    ranked = tuple(
        RankedCandidateView(
            rank=int(candidate["rank"]),
            canonical_candidate_uri=str(candidate["canonical_candidate_uri"]),
            candidate_local_index=int(candidate["candidate_local_index"]),
            score=float(candidate["score"]),
        )
        for candidate in sorted(handoff["ranked_candidates"],
                                key=lambda c: int(c["rank"])))
    if not ranked:
        return None

    table = build_answer_contrast_table(
        answer_uri=answer_uri,
        graph_fingerprint=fingerprint,
        answer_facts=answer_facts,
        candidate_facts=candidate_facts,
        candidate_order=tuple((c.canonical_candidate_uri, c.rank) for c in ranked),
    )
    return AnswerSelectionInput(
        answer_uri=answer_uri,
        answer_local_index=int(handoff["answer_local_index"]),
        display_label=str(handoff["display_label"]),
        pilot_slot=int(handoff["pilot_slot"]),
        selected_class_uri=str(handoff["selected_class_uri"]),
        graph_fingerprint=fingerprint,
        ranker_name=str(handoff["ranker_name"]),
        measure=str(handoff["measure"]),
        lrolesim_beta=float(handoff["lrolesim_beta"]),
        iterations=int(handoff["iterations"]),
        iteration_mode=str(handoff["iteration_mode"]),
        ranked_candidates=ranked,
        table=table,
        primary_or_diagnostic="diagnostic",
    )


# ==========================================================================
# 5) THE RUN
# ==========================================================================

@dataclass
class StageTiming:
    stage: str
    wall_seconds: float
    peak_rss_kb: int
    detail: str = ""

    def as_row(self) -> dict:
        return {
            "stage": self.stage,
            "wall_seconds": f"{self.wall_seconds:.3f}",
            "process_peak_rss_kb": self.peak_rss_kb,
            "detail": self.detail,
        }


def _peak_rss_kb() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


@dataclass
class RationaleSelectionRun:
    """Everything one pilot-rationale-selection run produced."""

    mode: str
    ranker_name: str
    k: int
    rho: int
    inputs: Prompt8DInputs
    contract_checks: tuple[tuple[str, str], ...]
    selection_inputs: tuple[AnswerSelectionInput, ...]
    selections: tuple[AnswerSelection, ...]
    primary_order: tuple[str, ...]
    diagnostic_input: Optional[AnswerSelectionInput]
    diagnostic_selection: Optional[AnswerSelection]
    protected_sources: dict
    guard_record: dict
    forbidden_modules: tuple[str, ...]
    timings: tuple[StageTiming, ...]

    def selection_for(self, answer_uri: str) -> AnswerSelection:
        for selection in self.selections:
            if selection.answer_uri == answer_uri:
                return selection
        raise KeyError(answer_uri)

    def input_for(self, answer_uri: str) -> AnswerSelectionInput:
        for item in self.selection_inputs:
            if item.answer_uri == answer_uri:
                return item
        raise KeyError(answer_uri)

    @property
    def ready_selections(self) -> tuple[AnswerSelection, ...]:
        return tuple(s for s in self.selections if s.ready)

    def counts(self) -> dict:
        positive = sum(1 for s in self.selections
                       if s.status == SELECTION_POSITIVE_OBSERVED)
        snapshot = sum(1 for s in self.selections
                       if s.status == SELECTION_SNAPSHOT_OBSERVED)
        none_full = sum(1 for s in self.selections
                        if s.status == SELECTION_NO_FULL_COVERAGE)
        not_ready = sum(1 for s in self.selections
                        if s.status == SELECTION_PRIMARY_NOT_READY)
        partial_only = 0
        zero_coverage = 0
        for selection in self.selections:
            if selection.status != SELECTION_NO_FULL_COVERAGE:
                continue
            best = max(
                (search.best_partial.coverage_count
                 for search in selection.searches.values()
                 if search.best_partial is not None),
                default=0)
            if best > 0:
                partial_only += 1
            else:
                zero_coverage += 1
        return {
            "primary_answer_denominator": len(self.selections),
            "primary_ready_for_rationale_selection": len(self.ready_selections),
            "primary_ranked_candidate_total": sum(
                item.candidate_count for item in self.selection_inputs),
            "algorithm_selected_positive_observed": positive,
            "algorithm_selected_snapshot_observed_only": snapshot,
            "no_full_coverage_partial_only": partial_only,
            "no_full_coverage_zero_coverage": zero_coverage,
            "no_full_coverage_total": none_full,
            "primary_not_ready": not_ready,
            "combinations_searched_per_policy": sum(
                search.combination_count
                for selection in self.ready_selections
                for search in list(selection.searches.values())[:1]),
            "human_validated_distractor_sets": 0,
            "publishable_final_mcqs": 0,
        }


def run_rationale_selection(
    *,
    prompt8d_dir: str | Path = FROZEN_PROMPT8D_DIR,
    k: int = DEFAULT_K,
    rho: int = DEFAULT_RHO,
    verbose: bool = True,
) -> RationaleSelectionRun:
    """Consume the frozen Prompt-8D handoff and select distractors exactly.

    Strictly offline. Makes no HTTP or SPARQL call, loads no spaCy model, no SBERT
    model and no DBpedia abstract, runs no class selection, rebuilds no M1 graph,
    recomputes no LRoleSim score and never invokes OverlapStrict/OverlapLoose.
    """
    guard = OfflineGuard()
    guard.install()
    timings: list[StageTiming] = []

    def stage(name: str, started: float, detail: str = "") -> None:
        elapsed = time.perf_counter() - started
        timings.append(StageTiming(name, elapsed, _peak_rss_kb(), detail))
        if verbose:
            print(f"  [{name}] {elapsed:.3f}s  {detail}")

    try:
        t0 = time.perf_counter()
        protected = verify_protected_sources()
        stage("verify_protected_sources", t0,
              f"{len(protected)} frozen sources byte-identical")

        t0 = time.perf_counter()
        inputs = load_prompt8d_handoff(prompt8d_dir)
        checks = inputs.contract_checks
        stage("load_prompt8d_handoff", t0,
              f"{len(inputs.handoffs)} primary handoffs, "
              f"{len(inputs.answer_facts)} Answer facts, "
              f"{len(inputs.candidate_facts)} candidate facts")

        t0 = time.perf_counter()
        selection_inputs = build_selection_inputs(inputs)
        stage("build_contrast_tables", t0,
              f"{len(selection_inputs)} ready Answers, "
              f"{sum(i.candidate_count for i in selection_inputs)} candidates")

        t0 = time.perf_counter()
        selections: list[AnswerSelection] = []
        primary_order: list[str] = []
        by_uri = {item.answer_uri: item for item in selection_inputs}
        for handoff in sorted(inputs.handoffs, key=lambda h: int(h["pilot_slot"])):
            answer_uri = str(handoff["answer_uri"])
            primary_order.append(answer_uri)
            if answer_uri in by_uri:
                selections.append(select_for_answer(by_uri[answer_uri],
                                                    k=k, rho=rho))
            else:
                selections.append(not_ready_selection(answer_uri, k=k, rho=rho))
        stage("exact_combination_search", t0,
              f"{sum(sum(s.combination_count for s in sel.searches.values()) for sel in selections)} "
              f"(combination, policy) evaluations")

        t0 = time.perf_counter()
        diagnostic_input = build_diagnostic_input(inputs)
        diagnostic_selection = (
            select_for_answer(diagnostic_input, k=k, rho=rho)
            if diagnostic_input is not None else None)
        stage("diagnostic_namespace", t0,
              f"{diagnostic_input.candidate_count if diagnostic_input else 0} "
              f"diagnostic candidates, held separately")

        return RationaleSelectionRun(
            mode="pilot-rationale-selection",
            ranker_name=EXPECTED_RANKER_NAME,
            k=k,
            rho=rho,
            inputs=inputs,
            contract_checks=tuple(checks),
            selection_inputs=selection_inputs,
            selections=tuple(selections),
            primary_order=tuple(primary_order),
            diagnostic_input=diagnostic_input,
            diagnostic_selection=diagnostic_selection,
            protected_sources=protected,
            guard_record=guard.as_record(),
            forbidden_modules=tuple(loaded_forbidden_modules()),
            timings=tuple(timings),
        )
    finally:
        guard.uninstall()


# ==========================================================================
# 6) OUTPUT WRITERS
# ==========================================================================

SUMMARY_FIELDS = (
    "pilot_slot", "answer_uri", "display_label", "primary_or_diagnostic",
    "diagnostic_only", "excluded_from_primary_policy_metrics",
    "selected_class_uri", "graph_fingerprint", "ranker_name", "measure",
    "lrolesim_beta", "iterations", "iteration_mode", "k", "rho",
    "ready_for_rationale_selection", "ranked_candidate_count",
    "answer_fact_count", "combination_count",
    "positive_observed_feasible_count", "snapshot_observed_feasible_count",
    "coverage_status", "selection_status", "evidence_policy",
    "distractor_1_uri", "distractor_2_uri", "distractor_3_uri",
    "distractor_ranks", "distractor_lrolesim_scores",
    "minimum_rationale_size", "optimal_rationale_count",
    "absence_only_incidences",
    "algorithm_selected_distractor", "requires_human_validation",
    "human_validated", "human_validation_status", "publishable_final",
    "requires_fallback_class_run",
)


def _summary_row(run: RationaleSelectionRun, answer_uri: str) -> dict:
    selection = run.selection_for(answer_uri)
    handoff = next(h for h in run.inputs.handoffs
                   if h["answer_uri"] == answer_uri)

    row = {
        "pilot_slot": handoff["pilot_slot"],
        "answer_uri": answer_uri,
        "display_label": handoff["display_label"],
        "primary_or_diagnostic": "primary",
        "diagnostic_only": _b(False),
        "excluded_from_primary_policy_metrics": _b(False),
        "selected_class_uri": handoff["selected_class_uri"] or "",
        "graph_fingerprint": handoff["graph_fingerprint"] or "",
        "ranker_name": handoff["ranker_name"],
        "measure": handoff["measure"] or "",
        "lrolesim_beta": ("" if handoff["lrolesim_beta"] is None
                          else repr(float(handoff["lrolesim_beta"]))),
        "iterations": ("" if handoff["iterations"] is None
                       else handoff["iterations"]),
        "iteration_mode": handoff["iteration_mode"] or "",
        "k": run.k,
        "rho": run.rho,
        "ready_for_rationale_selection": _b(selection.ready),
        "ranked_candidate_count": handoff["ranked_candidate_count"],
        "answer_fact_count": 0,
        "combination_count": 0,
        "positive_observed_feasible_count": 0,
        "snapshot_observed_feasible_count": 0,
        "coverage_status": "",
        "selection_status": selection.status,
        "evidence_policy": selection.evidence_policy or "",
        "distractor_1_uri": "",
        "distractor_2_uri": "",
        "distractor_3_uri": "",
        "distractor_ranks": "",
        "distractor_lrolesim_scores": "",
        "minimum_rationale_size": "",
        "optimal_rationale_count": "",
        "absence_only_incidences": "",
        # Never a bare is_final_distractor: an algorithm-selected distractor is
        # not a validated one, and the two must not share a field name.
        "algorithm_selected_distractor": _b(selection.algorithm_selected),
        "requires_human_validation": _b(True),
        "human_validated": _b(False),
        "human_validation_status": HUMAN_VALIDATION_NOT_CHECKED,
        "publishable_final": _b(False),
        "requires_fallback_class_run": (
            REQUIRES_FALLBACK_CLASS if selection.requires_fallback_class else ""),
    }

    if not selection.ready:
        return row

    selection_input = run.input_for(answer_uri)
    row["answer_fact_count"] = selection_input.table.fact_count
    positive = selection.searches[POLICY_POSITIVE_OBSERVED]
    snapshot = selection.searches[POLICY_SNAPSHOT_OBSERVED]
    row["combination_count"] = positive.combination_count
    row["positive_observed_feasible_count"] = len(positive.feasible(run.rho))
    row["snapshot_observed_feasible_count"] = len(snapshot.feasible(run.rho))

    if selection.selected is not None and selection.cover is not None:
        row["coverage_status"] = selection.cover.coverage_status
        for index, uri in enumerate(selection.selected.candidate_uris, start=1):
            row[f"distractor_{index}_uri"] = uri
        row["distractor_ranks"] = "|".join(str(r) for r in selection.selected.ranks)
        row["distractor_lrolesim_scores"] = "|".join(
            _fmt_score(s) for s in selection.selected.scores)
        row["minimum_rationale_size"] = selection.cover.minimum_rationale_size
        row["optimal_rationale_count"] = selection.cover.optimal_rationale_count
        row["absence_only_incidences"] = selection.cover.absence_only_incidences
    else:
        best_partial_status = ""
        for policy in POLICY_PRIORITY:
            partial = selection.partial_covers.get(policy)
            if partial is not None:
                best_partial_status = partial.coverage_status
                break
        row["coverage_status"] = best_partial_status
    return row


def write_summary(run: RationaleSelectionRun, out_dir: Path) -> None:
    """Exactly nine primary Answer rows. Sulfuric acid stays a primary failure."""
    rows = [_summary_row(run, answer_uri) for answer_uri in run.primary_order]
    if len(rows) != EXPECTED_PRIMARY_ANSWER_COUNT:
        raise RationaleSelectionError(
            f"the primary summary must hold exactly "
            f"{EXPECTED_PRIMARY_ANSWER_COUNT} rows, built {len(rows)}")
    _write_csv(out_dir / "rationale_selection_summary.csv", SUMMARY_FIELDS, rows)


def _selected_mcq_record(run: RationaleSelectionRun,
                         selection: AnswerSelection) -> dict:
    selection_input = run.input_for(selection.answer_uri)
    combination = selection.selected
    cover = selection.cover
    assert combination is not None and cover is not None
    policy = selection.evidence_policy
    assert policy is not None

    return {
        "answer_uri": selection.answer_uri,
        "display_label": selection_input.display_label,
        "pilot_slot": selection_input.pilot_slot,
        "primary_or_diagnostic": selection_input.primary_or_diagnostic,
        "selected_class_uri": selection_input.selected_class_uri,
        "graph_fingerprint": selection_input.graph_fingerprint,
        "ranker_name": selection_input.ranker_name,
        "measure": selection_input.measure,
        "lrolesim_beta": selection_input.lrolesim_beta,
        "iterations": selection_input.iterations,
        "iteration_mode": selection_input.iteration_mode,
        "k": selection.k,
        "rho": selection.rho,
        "evidence_policy": policy,
        "evidence_policy_note": POLICY_NOTE[policy],
        "set_cover_algorithm": SET_COVER_ALGORITHM,
        "set_cover_complexity": SET_COVER_COMPLEXITY,
        "distractors": [
            {
                "position": position,
                "candidate_uri": uri,
                "original_rank": rank,
                "lrolesim_score": score,
                "candidate_local_index": next(
                    c.candidate_local_index
                    for c in selection_input.ranked_candidates
                    if c.canonical_candidate_uri == uri),
                "in_provisional_lrolesim_top3": rank <= 3,
            }
            for position, (uri, rank, score) in enumerate(
                zip(combination.candidate_uris, combination.ranks,
                    combination.scores))
        ],
        "distractor_uris": list(combination.candidate_uris),
        "distractor_ranks": list(combination.ranks),
        "distractor_lrolesim_scores": list(combination.scores),
        "lrolesim_score_sum": combination.score_sum,
        "lrolesim_score_min": combination.score_min,
        "candidate_rank_sum": combination.rank_sum,
        "searched_complete_ranking": True,
        "searched_candidate_count": selection_input.candidate_count,
        "searched_combination_count": (
            selection.searches[policy].combination_count),
        "replaced_provisional_top3": sorted(combination.ranks) != [1, 2, 3],
        "selected_rationale": [
            {
                "predicate_uri": fact.canonical_key[0],
                "direction": fact.canonical_key[1],
                "counterpart_uri": fact.canonical_key[2],
                "coverage_mask": fact.coverage_mask,
                "covered_candidate_uris": [
                    combination.candidate_uris[bit]
                    for bit in range(selection.k)
                    if (fact.coverage_mask >> bit) & 1],
                "absence_only_incidences": fact.absence_incidences,
                "source": FACT_SOURCE_PINNED_LOCAL_KG,
            }
            for fact in cover.selected_rationale
        ],
        "minimum_rationale_size": cover.minimum_rationale_size,
        "optimal_rationale_count": cover.optimal_rationale_count,
        "absence_only_incidences": cover.absence_only_incidences,
        "coverage_mask": cover.coverage_mask,
        "coverage_count": cover.coverage_count,
        "coverage_status": cover.coverage_status,
        "full_coverage": cover.full_coverage,
        "selection_status": selection.status,
        "algorithm_selected_distractor": True,
        "human_validated": False,
        "requires_human_validation": True,
        "human_validation_status": HUMAN_VALIDATION_NOT_CHECKED,
        "publishable_final": False,
        "open_world_note": PREDICATE_FUNCTIONALITY_NOTE,
        "input_package_sha256": dict(run.inputs.input_sha256),
        "input_package_zip_sha256": FROZEN_PROMPT8D_ZIP_SHA256,
        "pinned_local_kg_sha256": PINNED_LOCAL_KG_SHA256,
    }


def write_algorithm_selected_distractors(run: RationaleSelectionRun,
                                         out_dir: Path) -> None:
    records = [_selected_mcq_record(run, selection)
               for selection in run.selections if selection.algorithm_selected]
    _write_jsonl(out_dir / "algorithm_selected_distractors.jsonl", records)


def write_selected_rationales(run: RationaleSelectionRun, out_dir: Path) -> None:
    records: list[dict] = []
    for selection in run.selections:
        if not selection.algorithm_selected:
            continue
        records.extend(selected_rationale_records(
            selection, run.input_for(selection.answer_uri)))
    _write_jsonl(out_dir / "selected_rationales.jsonl", records)


def write_fact_coverage(run: RationaleSelectionRun, out_dir: Path) -> None:
    """One record per (Answer, observed Answer fact), with per-candidate evidence.

    This is the complete set-aware observed contrast, before any combination is
    considered: it is what makes every later coverage claim checkable from the
    package alone. Candidate ranks are used inside `per_candidate` and the roster
    lives in triple_search_audit.jsonl, so the file stays proportionate.
    """
    records: list[dict] = []
    for selection_input in run.selection_inputs:
        table = selection_input.table
        for index, fact in enumerate(table.facts):
            per_candidate = []
            covered = {POLICY_POSITIVE_OBSERVED: [], POLICY_SNAPSHOT_OBSERVED: []}
            status_counts: dict[str, int] = {}
            relation_counts: dict[str, int] = {}
            for contrast in table.contrasts:
                evidence = contrast.evidence[index]
                per_candidate.append({
                    "candidate_rank": contrast.candidate_rank,
                    "candidate_uri": contrast.candidate_uri,
                    "evidence_status": evidence.evidence_status,
                    "object_set_relation": evidence.object_set_relation,
                    "answer_object_set_size": evidence.answer_object_set_size,
                    "candidate_object_set_size": evidence.candidate_object_set_size,
                })
                status_counts[evidence.evidence_status] = (
                    status_counts.get(evidence.evidence_status, 0) + 1)
                relation_counts[evidence.object_set_relation] = (
                    relation_counts.get(evidence.object_set_relation, 0) + 1)
                for policy in POLICY_PRIORITY:
                    if index in contrast.covering_fact_indices[policy]:
                        covered[policy].append(contrast.candidate_rank)
            records.append({
                "answer_uri": selection_input.answer_uri,
                "graph_fingerprint": selection_input.graph_fingerprint,
                "fact_index": index,
                "predicate_uri": fact.predicate_uri,
                "direction": fact.direction,
                "counterpart_uri": fact.counterpart_uri,
                "source": FACT_SOURCE_PINNED_LOCAL_KG,
                "candidate_count": table.candidate_count,
                "evidence_status_counts": status_counts,
                "object_set_relation_counts": relation_counts,
                "covered_candidate_ranks_positive_observed":
                    covered[POLICY_POSITIVE_OBSERVED],
                "covered_candidate_ranks_snapshot_observed":
                    covered[POLICY_SNAPSHOT_OBSERVED],
                "per_candidate": per_candidate,
            })
    _write_jsonl(out_dir / "fact_coverage.jsonl", records)


def write_triple_search_audit(run: RationaleSelectionRun, out_dir: Path) -> None:
    """One record per ready Answer: what the exhaustive search actually saw."""
    records: list[dict] = []
    for selection in run.ready_selections:
        selection_input = run.input_for(selection.answer_uri)
        positive = selection.searches[POLICY_POSITIVE_OBSERVED]
        snapshot = selection.searches[POLICY_SNAPSHOT_OBSERVED]
        records.append({
            "answer_uri": selection.answer_uri,
            "display_label": selection_input.display_label,
            "graph_fingerprint": selection_input.graph_fingerprint,
            "selected_class_uri": selection_input.selected_class_uri,
            "k": selection.k,
            "rho": selection.rho,
            "candidate_count": selection_input.candidate_count,
            "answer_fact_count": selection_input.table.fact_count,
            "combination_count": positive.combination_count,
            "exhaustive_search": True,
            "provisional_lrolesim_top3_ranks": [1, 2, 3],
            "provisional_top3_treated_as_final": False,
            "positive_observed_feasible_count": len(positive.feasible(selection.rho)),
            "snapshot_observed_feasible_count": len(snapshot.feasible(selection.rho)),
            "positive_observed_candidates_with_any_coverage":
                positive.candidates_with_any_coverage,
            "snapshot_observed_candidates_with_any_coverage":
                snapshot.candidates_with_any_coverage,
            "selected_evidence_policy": selection.evidence_policy or "",
            "selected_objective_key": (
                {
                    "negated_lrolesim_score_sum": repr(-selection.selected.score_sum),
                    "negated_lrolesim_score_min": repr(-selection.selected.score_min),
                    "minimum_rationale_size":
                        selection.selected.minimum_rationale_size,
                    "candidate_rank_sum": selection.selected.rank_sum,
                    "candidate_uris": list(selection.selected.candidate_uris),
                }
                if selection.selected is not None else None),
            "candidate_roster": [
                {
                    "rank": candidate.rank,
                    "candidate_uri": candidate.canonical_candidate_uri,
                    "candidate_local_index": candidate.candidate_local_index,
                    "lrolesim_score": candidate.score,
                }
                for candidate in selection_input.ranked_candidates],
            "top_feasible_combinations": {
                policy: [outcome.as_record()
                         for outcome in selection.searches[policy].top(
                             selection.rho, AUDIT_TOP_COMBINATIONS)]
                for policy in POLICY_PRIORITY},
            "top_feasible_combinations_limit": AUDIT_TOP_COMBINATIONS,
            "note": ("Feasibility is the exact set-cover result, never the weaker "
                     "condition that each candidate merely has some fact the "
                     "Answer's fact set does not match."),
        })
    _write_jsonl(out_dir / "triple_search_audit.jsonl", records)


def write_partial_coverage_diagnostics(run: RationaleSelectionRun,
                                       out_dir: Path) -> None:
    """Deterministic best partial results, for Answers with no full coverage.

    Written for BOTH policies. Evidence is not discarded when no MCQ can be
    selected: the fallback decision has to stand on something, and a partial
    result is never reported as a complete rationale.
    """
    records: list[dict] = []
    for selection in run.selections:
        if selection.status != SELECTION_NO_FULL_COVERAGE:
            continue
        selection_input = run.input_for(selection.answer_uri)
        for policy in POLICY_PRIORITY:
            search = selection.searches.get(policy)
            partial = selection.partial_covers.get(policy)
            if search is None or search.best_partial is None or partial is None:
                continue
            outcome = search.best_partial
            records.append({
                "answer_uri": selection.answer_uri,
                "display_label": selection_input.display_label,
                "graph_fingerprint": selection_input.graph_fingerprint,
                "selected_class_uri": selection_input.selected_class_uri,
                "evidence_policy": policy,
                "k": selection.k,
                "rho": selection.rho,
                "coverage_status": partial.coverage_status,
                "coverage_count": partial.coverage_count,
                "coverage_mask": partial.coverage_mask,
                "candidate_uris": list(outcome.candidate_uris),
                "candidate_ranks": list(outcome.ranks),
                "lrolesim_scores": list(outcome.scores),
                "uncovered_candidate_positions":
                    list(partial.uncovered_positions),
                "uncovered_candidate_uris": [
                    outcome.candidate_uris[bit]
                    for bit in partial.uncovered_positions],
                "rationale_size_for_this_coverage":
                    partial.minimum_rationale_size,
                "partial_rationale_facts": [
                    fact.as_record() for fact in partial.selected_rationale],
                "full_coverage": False,
                "full_coverage_exists_but_exceeds_rho":
                    selection.full_coverage_exists_but_exceeds_rho,
                "algorithm_selected_distractor": False,
                "is_complete_rationale": False,
                "requires_human_validation": True,
                "human_validation_status": HUMAN_VALIDATION_NOT_CHECKED,
                "publishable_final": False,
                "next_step": REQUIRES_FALLBACK_CLASS,
                "next_step_note": (
                    "Prompt 8E runs no class selection, mapping, graph "
                    "construction or LRoleSim for a fallback class: Prompt 8D "
                    "holds rankings for the Prompt-8C selected class only. Exact "
                    "enumeration over the complete ranking has already performed "
                    "evidence-aware candidate replacement inside that class."),
            })
    _write_jsonl(out_dir / "partial_coverage_diagnostics.jsonl", records)


RHO_ABLATION_FIELDS = (
    "answer_uri", "display_label", "evidence_policy", "rho", "k",
    "full_coverage_exists", "feasible_triple_count",
    "best_candidate_uris", "best_candidate_ranks", "best_rationale_size",
    "is_primary_configuration", "selection_policy_note",
)


def write_rho_ablation(run: RationaleSelectionRun, out_dir: Path) -> None:
    """The §10 sweep. Observational: it never moves the primary selection."""
    rows: list[dict] = []
    for selection in run.ready_selections:
        selection_input = run.input_for(selection.answer_uri)
        for entry in selection.ablation:
            rows.append({
                "answer_uri": entry.answer_uri,
                "display_label": selection_input.display_label,
                "evidence_policy": entry.evidence_policy,
                "rho": entry.rho,
                "k": selection.k,
                "full_coverage_exists": _b(entry.full_coverage_exists),
                "feasible_triple_count": entry.feasible_triple_count,
                "best_candidate_uris": "|".join(entry.best_candidate_uris),
                "best_candidate_ranks": "|".join(
                    str(rank) for rank in entry.best_candidate_ranks),
                "best_rationale_size": ("" if entry.best_rationale_size is None
                                        else entry.best_rationale_size),
                "is_primary_configuration": _b(
                    entry.rho == run.rho
                    and entry.evidence_policy == POLICY_POSITIVE_OBSERVED),
                "selection_policy_note": entry.selection_policy_note,
            })
    _write_csv(out_dir / "rho_ablation.csv", RHO_ABLATION_FIELDS, rows)


def write_sulfuric_acid_diagnostic(run: RationaleSelectionRun,
                                   out_dir: Path) -> None:
    """The diagnostic rationale analysis, in its own file and namespace."""
    primary = run.selection_for(EXPECTED_PRIMARY_FAILURE_ANSWER_URI)
    diagnostic_input = run.diagnostic_input
    diagnostic = run.diagnostic_selection

    payload: dict = {
        "diagnostic_only": True,
        "excluded_from_primary_policy_metrics": True,
        "answer_uri": EXPECTED_PRIMARY_FAILURE_ANSWER_URI,
        "primary_record": {
            "selection_status": primary.status,
            "ready_for_rationale_selection": primary.ready,
            "algorithm_selected_distractor": primary.algorithm_selected,
            "ranked_candidate_count": 0,
            "note": ("Sulfuric acid remains the one PRIMARY failure. The "
                     "diagnostic below is engineering evidence only and enters no "
                     "primary denominator, success rate or candidate count."),
        },
        "boundaries": {
            "counted_in_nine_answer_denominator": False,
            "counted_in_eight_ready_answer_numerator": False,
            "counted_in_primary_ranked_candidate_total": False,
            "counted_in_primary_selection_counts": False,
            "primary_failure_downgraded": False,
            "answer_replaced": False,
            "new_class_added": False,
            "publishable_final": False,
        },
    }

    if diagnostic_input is None or diagnostic is None:
        payload["diagnostic_analysis"] = None
        _write_json(out_dir / "sulfuric_acid_diagnostic_rationale.json", payload)
        return

    positive = diagnostic.searches[POLICY_POSITIVE_OBSERVED]
    snapshot = diagnostic.searches[POLICY_SNAPSHOT_OBSERVED]
    payload["diagnostic_analysis"] = {
        "diagnostic_class_uri": diagnostic_input.selected_class_uri,
        "graph_fingerprint": diagnostic_input.graph_fingerprint,
        "candidate_count": diagnostic_input.candidate_count,
        "answer_fact_count": diagnostic_input.table.fact_count,
        "combination_count": positive.combination_count,
        "k": diagnostic.k,
        "rho": diagnostic.rho,
        "positive_observed_feasible_count": len(positive.feasible(diagnostic.rho)),
        "snapshot_observed_feasible_count": len(snapshot.feasible(diagnostic.rho)),
        "selection_status": diagnostic.status,
        "evidence_policy": diagnostic.evidence_policy or "",
        "selected_distractor_uris": (list(diagnostic.selected.candidate_uris)
                                     if diagnostic.selected else []),
        "selected_distractor_ranks": (list(diagnostic.selected.ranks)
                                      if diagnostic.selected else []),
        "minimum_rationale_size": (diagnostic.cover.minimum_rationale_size
                                   if diagnostic.cover else None),
        "optimal_rationale_count": (diagnostic.cover.optimal_rationale_count
                                    if diagnostic.cover else None),
        "selected_rationale": [
            fact.as_record()
            for fact in (diagnostic.cover.selected_rationale
                         if diagnostic.cover else ())],
        "algorithm_selected_distractor": diagnostic.algorithm_selected,
        "requires_human_validation": True,
        "human_validation_status": HUMAN_VALIDATION_NOT_CHECKED,
        "publishable_final": False,
    }
    _write_json(out_dir / "sulfuric_acid_diagnostic_rationale.json", payload)


def _git_state() -> dict:
    def _run(args: Sequence[str]) -> str:
        try:
            return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True,
                                  capture_output=True, text=True).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""
    return {
        "branch": _run(["branch", "--show-current"]),
        "head_commit": _run(["rev-parse", "HEAD"]),
        "head_subject": _run(["log", "-1", "--format=%s"]),
        "tracked_working_tree_clean": _run(
            ["status", "--porcelain", "--untracked-files=no"]) == "",
    }


def write_offline_replay_manifest(run: RationaleSelectionRun,
                                  out_dir: Path) -> None:
    compared = {}
    for name in REPLAY_COMPARED_FILES:
        path = out_dir / name
        compared[name] = {"sha256": sha256_file(path),
                          "size_bytes": path.stat().st_size}
    _write_json(out_dir / "offline_replay_manifest.json", {
        "mode": run.mode,
        "replay_command": (
            "python src/extract_221_and_select_distractors_ClaudeWeb_v2.py "
            "--mode pilot-rationale-selection --output-dir <fresh directory>"),
        "byte_identical_files": list(REPLAY_COMPARED_FILES),
        "excluded_from_byte_identity": [
            "run_manifest.json (records the run clock, timings and git state)",
            "offline_replay_manifest.json (contains the hashes it verifies)",
        ],
        "file_hashes": compared,
        "network": run.guard_record,
        "http_calls": 0,
        "sparql_calls": 0,
        "forbidden_modules_loaded_in_process": list(run.forbidden_modules),
        "forbidden_modules_note": (
            "A PROCESS-WIDE snapshot of sys.modules taken after the run. Exact "
            "for a standalone invocation, which is how this package is produced. "
            "Inside a shared pytest session the same list also reports modules "
            "other test files imported, so the test suite asserts the delta "
            "introduced by this code path instead."),
        "prompt8d_input_sha256": dict(run.inputs.input_sha256),
        "prompt8d_zip_expected_sha256": FROZEN_PROMPT8D_ZIP_SHA256,
        "pinned_local_kg_expected_sha256": PINNED_LOCAL_KG_SHA256,
        "pinned_local_kg_loaded": False,
        "protected_sources": run.protected_sources,
    })


def write_run_manifest(run: RationaleSelectionRun, out_dir: Path,
                       raw_command: Sequence[str] = ()) -> None:
    _write_json(out_dir / "run_manifest.json", {
        "task": ("Prompt 8E — exact rationale set cover and evidence-aware final "
                 "distractor selection"),
        "mode": run.mode,
        "ranker_name": run.ranker_name,
        "raw_command": list(raw_command),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "conda_env": os.environ.get("CONDA_DEFAULT_ENV", ""),
        "git": _git_state(),
        "frozen_prompt8d_dir": str(FROZEN_PROMPT8D_DIR.relative_to(REPO_ROOT)),
        "frozen_prompt8d_zip_expected_sha256": FROZEN_PROMPT8D_ZIP_SHA256,
        "prompt8d_input_sha256": dict(run.inputs.input_sha256),
        "protected_sources": run.protected_sources,
        "pinned_local_kg_expected_sha256": PINNED_LOCAL_KG_SHA256,
        "pinned_local_kg_loaded": False,
        "lrolesim_execution_path": {
            "ranker_name": EXPECTED_RANKER_NAME,
            "measure": EXPECTED_MEASURE,
            "lrolesim_beta": EXPECTED_LROLESIM_BETA,
            "iterations": EXPECTED_ITERATIONS,
            "iteration_mode": EXPECTED_ITERATION_MODE,
            "note": ("frozen and consumed, not recomputed: Prompt 8E reads the "
                     "Prompt-8D ranks and never re-runs the kernel. lrolesim_edt "
                     "is not run."),
        },
        "set_cover": {
            "algorithm": SET_COVER_ALGORITHM,
            "complexity": SET_COVER_COMPLEXITY,
            "k": run.k,
            "rho": run.rho,
            "rho_ablation_values": list(RHO_ABLATION_VALUES),
            "exact": True,
            "greedy": False,
            "legacy_one_fact_special_case":
                LEGACY_ONE_FACT_SPECIAL_CASE_NOTE,
        },
        "evidence_policies": {
            "priority": list(POLICY_PRIORITY),
            "notes": dict(POLICY_NOTE),
            "predicate_functionality_note": PREDICATE_FUNCTIONALITY_NOTE,
        },
        "input_contract_checks": [
            {"check": name, "detail": detail}
            for name, detail in run.contract_checks],
        "counts": run.counts(),
        "network": run.guard_record,
        "forbidden_modules_loaded_in_process": list(run.forbidden_modules),
        "forbidden_modules_note": (
            "A PROCESS-WIDE snapshot of sys.modules taken after the run. Exact "
            "for a standalone invocation, which is how this package is produced. "
            "Inside a shared pytest session the same list also reports modules "
            "other test files imported, so the test suite asserts the delta "
            "introduced by this code path instead."),
        "stage_timings": [timing.as_row() for timing in run.timings],
        "open_world_note": (
            "Every fact in this package is OBSERVED in the pinned local KG "
            "snapshot. No schema in this package has a field that can express a "
            "refutation, and an absent triple is simply absent, so no "
            "algorithm-selected distractor is claimed to have been ruled out in "
            "the real world."),
        "scope_note": (
            "Stops before natural-language verbalization and before external "
            "human factual validation. Every algorithm-selected record carries "
            "requires_human_validation = true, human_validation_status = "
            "NOT_CHECKED and publishable_final = false."),
    })


def write_all_outputs(run: RationaleSelectionRun, out_dir: str | Path,
                      raw_command: Sequence[str] = ()) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_summary(run, out_dir)
    write_algorithm_selected_distractors(run, out_dir)
    write_selected_rationales(run, out_dir)
    write_fact_coverage(run, out_dir)
    write_triple_search_audit(run, out_dir)
    write_partial_coverage_diagnostics(run, out_dir)
    write_rho_ablation(run, out_dir)
    write_sulfuric_acid_diagnostic(run, out_dir)
    write_offline_replay_manifest(run, out_dir)
    write_run_manifest(run, out_dir, raw_command)

    # Every written file is re-read and checked for language that would turn an
    # observation into a claim about the world — the manifests included, since a
    # note is exactly where such a sentence would appear. Cheap, and it makes the
    # Open-World boundary a property of the ARTEFACT rather than of the code that
    # wrote it.
    for name in (*REPLAY_COMPARED_FILES, "run_manifest.json",
                 "offline_replay_manifest.json"):
        assert_no_negative_claim((out_dir / name).read_text(encoding="utf-8"),
                                 where=name)
    return out_dir


# ==========================================================================
# 7) CLI
# ==========================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python src/pipeline/rationale_selection_run.py",
        description=("Prompt 8E — exact minimum-cardinality rationale set cover "
                     "and evidence-aware distractor selection over the frozen "
                     "Prompt-8D handoff. Strictly offline."))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--prompt8d-dir", default=str(FROZEN_PROMPT8D_DIR))
    parser.add_argument("-k", type=int, default=DEFAULT_K,
                        help="distractors per question (1 <= k <= 5)")
    parser.add_argument("--rho", type=int, default=DEFAULT_RHO,
                        help="maximum rationale size that may be presented")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(argv)
    raw_command = ["python", "src/pipeline/rationale_selection_run.py", *argv]
    run = run_rationale_selection(prompt8d_dir=args.prompt8d_dir, k=args.k,
                                  rho=args.rho, verbose=not args.quiet)
    out_dir = write_all_outputs(run, args.output_dir, raw_command)
    counts = run.counts()
    print(f"\n[done] mode={run.mode}  ranker={run.ranker_name}  "
          f"k={run.k} rho={run.rho}")
    print(f"       outputs -> {out_dir}")
    print(f"       primary Answers: {counts['primary_answer_denominator']} "
          f"({counts['primary_ready_for_rationale_selection']} ready)")
    print(f"       positive-observed full coverage: "
          f"{counts['algorithm_selected_positive_observed']}")
    print(f"       snapshot-observed full coverage only: "
          f"{counts['algorithm_selected_snapshot_observed_only']}")
    print(f"       no full coverage: {counts['no_full_coverage_total']}")
    print(f"       network attempts: "
          f"{run.guard_record['network_attempts']} (http 0, sparql 0)")
    print(f"       every selected MCQ: requires_human_validation=true, "
          f"publishable_final=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
