############################################################################
# src/extract_221_and_select_distractors_ClaudeWeb_v2.py
#
# COMPATIBILITY ENTRYPOINT AND ORCHESTRATION WRAPPER  (Prompt 8D)
#
# WHAT THIS FILE USED TO BE
#   A single module that retrieved candidates over SPARQL, scored them with
#   OverlapStrict/OverlapLoose, picked a set with an MMR-like step, and derived
#   "distinguishing facts" — with no reference to LRoleSim anywhere in it.
#   AUDIT_Journal2_v2_2026-07-26 item EX-2 records that absence as the single most
#   serious methodological blocker in the Journal-2 code base: the pipeline
#   diagram claimed a structural ranker the file did not contain.
#
# WHAT THIS FILE IS NOW
#   An orchestration wrapper over two NAMED rankers, and the owner of neither's
#   mathematics:
#
#     pilot-lrolesim-handoff   PROPOSED. Consumes the verified Prompt-8C graph and
#                              LRoleSim records through
#                              selection.lrolesim_handoff, checks them against the
#                              ranking contract, serializes the observed one-hop
#                              facts Prompt 8E needs, and stops.
#
#     legacy-overlap           BASELINE. Delegates to selection.legacy_overlap,
#                              which is network- and model-bearing and is imported
#                              only inside that mode.
#
#   and, since Prompt 8E, one further stage of the proposed path:
#
#     pilot-rationale-selection  PROPOSED. Consumes the frozen Prompt-8D handoff,
#                              computes the exact minimum-cardinality rationale set
#                              cover and selects distractors. Delegates entirely to
#                              pipeline.rationale_selection_run: this entrypoint
#                              owns NO set-cover and NO distractor-combination
#                              mathematics, which live in src/rationale/ (audit
#                              §9.2). Adding them here is what made the legacy file
#                              a 1,000-line module that no reviewer could bound.
#
#   Graph construction, the admission order and the LRoleSim kernel are NOT here.
#   They live in src/kg/graph_view.py, src/pipeline/candidate_order.py,
#   src/lrolesim/adapter.py and src/MCQ_lrolesim_ClaudeWeb_v2.py, all frozen.
#
# THE MODE IS MANDATORY
#   `--mode` has no default. An omitted or misspelled mode is an error, never a
#   silent fall-through to the baseline — a baseline reported as the proposed
#   method would be a false experimental claim, so the CLI is built to make that
#   impossible rather than unlikely.
#
# WHERE THIS STOPS
#   Before final distractor selection, before rationale set cover, before rarity
#   ranking and before MCQ verbalization. Every provisional record carries
#   is_final_distractor = false and
#   rationale_selection_status = RATIONALE_SELECTION_DEFERRED_TO_PROMPT_8E.
#
# OPEN WORLD
#   The facts written here are OBSERVED in the pinned local KG. No negative fact
#   is generated and no absence is reported as falsity (CLAUDE.md item 7).
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
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from selection.contracts import (                     # noqa: E402
    PILOT_ITERATION_MODE,
    RANKER_LEGACY_OVERLAP_BASELINE,
    RANKER_LROLESIM_M1_FIXED_K3,
    RATIONALE_SELECTION_DEFERRED,
    RationaleSelectionHandoff,
    SCOPE_DIAGNOSTIC,
    SCOPE_PRIMARY,
)
from selection.lrolesim_handoff import (              # noqa: E402
    EXPECTED_PRIMARY_FAILURE_ANSWER_URI,
    ContractReport,
    LRoleSimHandoffRanker,
    build_diagnostic_handoff,
    build_primary_handoffs,
    load_prompt8c_outputs,
    validate_prompt8c_contract,
)
from selection.observed_facts import (                # noqa: E402
    DEFAULT_EDGESET_CACHE,
    FACT_SCHEMA_VERSION,
    EdgeSetCache,
    OwnerFactSet,
    observed_edge_set,
    observed_facts_for_node,
    serialize_owner_fact_sets,
)

# ==========================================================================
# 0) PINNED INPUTS AND MODES
# ==========================================================================

PINNED_LOCAL_KG = REPO_ROOT / "data" / "infobox.pickle_EnglishVersion_EntityType"
PINNED_LOCAL_KG_SHA256 = (
    "e230c5b95e20093631697624d9c46f30a14081b3f415d5027ffaf313bdbbea1b"
)
FROZEN_PROMPT8C_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_graph_lrolesim_pilot_2026-07-30"
)
FROZEN_PROMPT8C_ZIP = (
    REPO_ROOT / "outputs" / "journal2_week2_graph_lrolesim_pilot_2026-07-30.zip"
)
FROZEN_PROMPT8C_ZIP_SHA256 = (
    "6306d6c6734728e8d8c470dab9ad5d2a6b728b721eab993e6c282ec3f8f8addc"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_extract_integration_2026-07-30"
)
# The frozen Prompt-8D handoff that pilot-rationale-selection consumes. Named
# here only so `--prompt8d-dir` has a default without importing the rationale
# layer at argument-parsing time; the mode itself reads the same constant from
# pipeline.rationale_selection_run, and a test asserts the two agree.
DEFAULT_PROMPT8D_DIR = DEFAULT_OUTPUT_DIR

# Frozen Prompt-8B/8C sources. Prompt 8D must not change any of them, so their
# hashes are checked at run time and published, not merely promised.
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
}

# --- Modes ------------------------------------------------------------------
MODE_PILOT_LROLESIM_HANDOFF = "pilot-lrolesim-handoff"
MODE_PILOT_RATIONALE_SELECTION = "pilot-rationale-selection"
MODE_LEGACY_OVERLAP = "legacy-overlap"
MODES = (MODE_PILOT_LROLESIM_HANDOFF, MODE_PILOT_RATIONALE_SELECTION,
         MODE_LEGACY_OVERLAP)

RANKER_FOR_MODE = {
    MODE_PILOT_LROLESIM_HANDOFF: RANKER_LROLESIM_M1_FIXED_K3,
    # Prompt 8E consumes the same frozen ranking; the ranker does not change when
    # rationale feasibility is applied to its output.
    MODE_PILOT_RATIONALE_SELECTION: RANKER_LROLESIM_M1_FIXED_K3,
    MODE_LEGACY_OVERLAP: RANKER_LEGACY_OVERLAP_BASELINE,
}

# Files a strict offline replay must reproduce byte for byte. Timing and clock
# artefacts are excluded by construction, not by tolerance.
REPLAY_COMPARED_FILES = (
    "extract_integration_summary.csv",
    "candidate_ranking_handoff.jsonl",
    "provisional_top3_handoff.csv",
    "observed_answer_facts.jsonl",
    "observed_candidate_facts.jsonl",
    "observed_diagnostic_facts.jsonl",
    "sulfuric_acid_diagnostic_handoff.json",
    "contract_validation.json",
)


class ExtractIntegrationError(Exception):
    """Base class for Prompt-8D extract-integration failures."""


class UnknownModeError(ExtractIntegrationError):
    """A mode was requested that this entrypoint does not implement.

    Raised instead of defaulting. There is no mode whose absence means "legacy".
    """


class ProtectedSourceModifiedError(ExtractIntegrationError):
    """A frozen Prompt-8B/8C source file no longer has its expected SHA-256."""


class OfflineGuardTripped(ExtractIntegrationError):
    """The proposed path attempted an outbound connection."""


# ==========================================================================
# 1) OFFLINE GUARD
# ==========================================================================

@dataclass
class OfflineGuard:
    """Blocks and counts outbound socket connections for the whole run.

    The proposed mode claims zero HTTP and zero SPARQL calls. A guard that fails
    the run makes that a checked property; the published counter is evidence
    rather than an assurance.
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
                f"outbound connection to {address!r} refused: the "
                f"{MODE_PILOT_LROLESIM_HANDOFF} mode reads only local frozen "
                f"inputs")

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


# ==========================================================================
# 2) LOCAL KG  (compatibility surface, retained)
# ==========================================================================

@dataclass
class KG:
    """The legacy in-memory view of the pinned pickle.

    Retained for old callers. New code uses src/kg/loader.LocalKG, which records
    the loaded file's SHA-256 — the identity this module's edge-set cache keys on.
    """

    url_index: dict
    index_url: dict                 # AUDIT item EX-16: a dict, not a list
    out_neighbor: dict
    in_neighbor: dict
    index_type: object = None

    def uri(self, idx: int) -> str:
        return self.index_url[idx]

    def idx(self, uri: str) -> Optional[int]:
        return self.url_index.get(uri)


def load_kg(pickle_path) -> KG:
    """Load a read_ttl pickle into the legacy KG view. No network."""
    from read_ttl import load_obj
    p = Path(pickle_path)
    if not p.is_absolute():
        for candidate in (p, REPO_ROOT / p, REPO_ROOT / "data" / p.name):
            if candidate.exists():
                p = candidate
                break
    if not p.exists():
        raise FileNotFoundError(
            f"{pickle_path} not found (tried {p}). Run read_ttl.py to build the "
            f"pickle from TTL first.")
    url_index, index_url, out_neighbor, in_neighbor, index_type = load_obj(str(p))
    return KG(url_index, index_url, out_neighbor, in_neighbor, index_type)


def extended_edgeset(node_idx: int, kg, use_in: bool = True) -> frozenset:
    """{(predicate, direction, counterpart)} for one node, correctly cached.

    THE FIX (AUDIT item EX-4, confirmed by audit test T2.1).
      The original memo was `dict[int, frozenset]` keyed by NODE INDEX ALONE:

          if node_idx in _edgeset_cache: return _edgeset_cache[node_idx]

      so the first call for a node fixed the answer for every later call. A result
      computed with use_in=False was returned unchanged for use_in=True, silently
      discarding every IN edge, and a second KG loaded in the same process
      inherited the first KG's edges even though read_ttl.py renumbers all nodes
      on every build. Both failures return successfully with the wrong answer.

      The identity is now (KG identity or SHA-256, node index, use_in, fact-schema
      version). See src/selection/observed_facts.py.
    """
    return observed_edge_set(node_idx, kg, use_in=use_in,
                             cache=DEFAULT_EDGESET_CACHE)


# ==========================================================================
# 3) DETERMINISTIC WRITERS
# ==========================================================================

def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"))


def _fmt_score(score: float) -> str:
    """Shortest round-tripping decimal form, matching Prompt-8C's writer.

    `repr` guarantees eval(repr(x)) == x in Python 3, so a score written here is
    byte-identical to the same score written by Prompt 8C.
    """
    return repr(float(score))


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


def sha256_file(path: str | Path, chunk_size: int = 1 << 23) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_protected_sources() -> dict:
    """Confirm every frozen Prompt-8B/8C source is byte-identical to its pin."""
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
            f"frozen Prompt-8B/8C sources changed: {drift}. Prompt 8D must not "
            f"modify the graph, ordering or LRoleSim layers.")
    return observed


# ==========================================================================
# 4) THE PROPOSED PATH:  pilot-lrolesim-handoff
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
class HandoffRun:
    """Everything one pilot-lrolesim-handoff run produced."""

    mode: str
    ranker_name: str
    contract_report: ContractReport
    primary_handoffs: tuple[RationaleSelectionHandoff, ...]
    diagnostic_handoff: RationaleSelectionHandoff
    answer_fact_sets: tuple[OwnerFactSet, ...]
    candidate_fact_sets: tuple[OwnerFactSet, ...]
    diagnostic_fact_sets: tuple[OwnerFactSet, ...]
    local_kg_record: dict
    protected_sources: dict
    guard_record: dict
    edgeset_cache_record: dict
    prompt8c_input_hashes: dict
    timings: tuple[StageTiming, ...]

    @property
    def ready_handoffs(self) -> tuple[RationaleSelectionHandoff, ...]:
        return tuple(h for h in self.primary_handoffs
                     if h.ready_for_rationale_selection)

    @property
    def primary_ranked_total(self) -> int:
        return sum(h.ranked_candidate_count for h in self.primary_handoffs)


def run_pilot_lrolesim_handoff(
    *,
    prompt8c_dir: str | Path = FROZEN_PROMPT8C_DIR,
    local_kg_path: str | Path = PINNED_LOCAL_KG,
    verify_local_kg_sha256: Optional[str] = PINNED_LOCAL_KG_SHA256,
    verbose: bool = True,
) -> HandoffRun:
    """Consume the verified Prompt-8C rankings and prepare the Prompt-8E input.

    Strictly offline. Makes no HTTP or SPARQL call, loads no spaCy model, no SBERT
    model and no DBpedia abstract, constructs no AbstractStore, and calls no class
    selection: the selected class of every Answer is READ from the frozen
    Prompt-8C records, never recomputed.
    """
    from kg.loader import load_local_kg           # local: keeps import cost in-mode

    guard = OfflineGuard()
    guard.install()
    timings: list[StageTiming] = []

    def stage(name: str, started: float, detail: str = "") -> None:
        timings.append(StageTiming(name, time.perf_counter() - started,
                                   _peak_rss_kb(), detail))
        if verbose:
            print(f"  [{name}] {time.perf_counter() - started:.3f}s  {detail}")

    try:
        # --- frozen sources ------------------------------------------------
        t0 = time.perf_counter()
        protected = verify_protected_sources()
        stage("verify_protected_sources", t0,
              f"{len(protected)} frozen sources byte-identical")

        # --- frozen Prompt-8C records ---------------------------------------
        t0 = time.perf_counter()
        inputs = load_prompt8c_outputs(prompt8c_dir)
        input_hashes = {
            name: sha256_file(Path(prompt8c_dir) / name)
            for name in sorted(
                p.name for p in Path(prompt8c_dir).iterdir()
                if p.is_file() and p.suffix in (".csv", ".jsonl", ".json"))
        }
        stage("load_prompt8c_outputs", t0,
              f"{len(inputs.rankings)} ranking rows, {len(inputs.manifests)} "
              f"graph manifests")

        # --- contract validation --------------------------------------------
        t0 = time.perf_counter()
        report = validate_prompt8c_contract(inputs)
        stage("validate_prompt8c_contract", t0,
              f"{len(report.checks)} checks passed, "
              f"{report.primary_ranked_candidate_count} primary ranks")

        # --- the proposed ranker ---------------------------------------------
        t0 = time.perf_counter()
        ranker = LRoleSimHandoffRanker(inputs, report=report)
        primary_handoffs = build_primary_handoffs(ranker)
        diagnostic_handoff = build_diagnostic_handoff(ranker)
        stage("build_handoffs", t0,
              f"{len(primary_handoffs)} primary handoffs, "
              f"{len(ranker.graph_feasible_primary_answer_uris())} ready")

        # --- pinned local KG --------------------------------------------------
        t0 = time.perf_counter()
        local_kg = load_local_kg(local_kg_path,
                                 verify_sha256=verify_local_kg_sha256)
        stage("load_pinned_local_kg", t0,
              f"sha256 {local_kg.source_sha256[:16]}..., "
              f"{local_kg.uri_count} URIs, {local_kg.edge_count} edges")

        # --- observed one-hop facts -------------------------------------------
        # A cache per run, keyed by (KG identity, node, use_in, schema). Answers
        # and candidates of different Answers legitimately share nodes, so the
        # memo is worth having; the corrected identity is what makes sharing safe.
        t0 = time.perf_counter()
        cache = EdgeSetCache()
        answer_fact_sets: list[OwnerFactSet] = []
        candidate_fact_sets: list[OwnerFactSet] = []

        for handoff in primary_handoffs:
            if not handoff.ready_for_rationale_selection:
                continue
            assert handoff.graph_fingerprint is not None
            answer_fact_sets.append(observed_facts_for_node(
                handoff.answer_local_index, local_kg,
                graph_fingerprint=handoff.graph_fingerprint,
                primary_or_diagnostic=SCOPE_PRIMARY,
                owner_role="answer",
                answer_uri=handoff.answer_uri,
                cache=cache))
            for candidate in handoff.ranked_candidates:
                candidate_fact_sets.append(observed_facts_for_node(
                    candidate.candidate_local_index, local_kg,
                    graph_fingerprint=handoff.graph_fingerprint,
                    primary_or_diagnostic=SCOPE_PRIMARY,
                    owner_role="candidate",
                    answer_uri=handoff.answer_uri,
                    cache=cache))
        stage("observed_primary_facts", t0,
              f"{len(answer_fact_sets)} Answers, "
              f"{len(candidate_fact_sets)} ranked candidates")

        # --- the diagnostic namespace, kept separate --------------------------
        t0 = time.perf_counter()
        diagnostic_fact_sets: list[OwnerFactSet] = []
        assert diagnostic_handoff.graph_fingerprint is not None
        diagnostic_fact_sets.append(observed_facts_for_node(
            diagnostic_handoff.answer_local_index, local_kg,
            graph_fingerprint=diagnostic_handoff.graph_fingerprint,
            primary_or_diagnostic=SCOPE_DIAGNOSTIC,
            owner_role="answer",
            answer_uri=diagnostic_handoff.answer_uri,
            cache=cache))
        for candidate in diagnostic_handoff.ranked_candidates:
            diagnostic_fact_sets.append(observed_facts_for_node(
                candidate.candidate_local_index, local_kg,
                graph_fingerprint=diagnostic_handoff.graph_fingerprint,
                primary_or_diagnostic=SCOPE_DIAGNOSTIC,
                owner_role="candidate",
                answer_uri=diagnostic_handoff.answer_uri,
                cache=cache))
        stage("observed_diagnostic_facts", t0,
              f"{len(diagnostic_fact_sets)} diagnostic owners")

        # Attach counts to each handoff so the summary needs no second pass.
        counts_by_answer: dict[str, dict[str, int]] = {}
        for fs in answer_fact_sets:
            counts_by_answer.setdefault(fs.answer_uri or "", {})["answer_facts"] = (
                fs.fact_count)
        for fs in candidate_fact_sets:
            bucket = counts_by_answer.setdefault(fs.answer_uri or "", {})
            bucket["candidate_facts"] = bucket.get("candidate_facts", 0) + fs.fact_count

        primary_handoffs = tuple(
            RationaleSelectionHandoff(
                **{**vars(h),
                   "observed_fact_counts": counts_by_answer.get(h.answer_uri, {})})
            for h in primary_handoffs
        )
        diagnostic_counts = {
            "answer_facts": diagnostic_fact_sets[0].fact_count,
            "candidate_facts": sum(fs.fact_count
                                   for fs in diagnostic_fact_sets[1:]),
        }
        diagnostic_handoff = RationaleSelectionHandoff(
            **{**vars(diagnostic_handoff),
               "observed_fact_counts": diagnostic_counts})

        return HandoffRun(
            mode=MODE_PILOT_LROLESIM_HANDOFF,
            ranker_name=RANKER_LROLESIM_M1_FIXED_K3,
            contract_report=report,
            primary_handoffs=primary_handoffs,
            diagnostic_handoff=diagnostic_handoff,
            answer_fact_sets=tuple(answer_fact_sets),
            candidate_fact_sets=tuple(candidate_fact_sets),
            diagnostic_fact_sets=tuple(diagnostic_fact_sets),
            local_kg_record=local_kg.as_record(REPO_ROOT),
            protected_sources=protected,
            guard_record=guard.as_record(),
            edgeset_cache_record=cache.as_record(),
            prompt8c_input_hashes=input_hashes,
            timings=tuple(timings),
        )
    finally:
        guard.uninstall()


# ==========================================================================
# 5) OUTPUT WRITERS
# ==========================================================================

EXTRACT_INTEGRATION_SUMMARY_FIELDS = (
    "pilot_slot", "answer_uri", "display_label", "answer_local_index",
    "primary_or_diagnostic", "diagnostic_only",
    "excluded_from_primary_policy_metrics",
    "mapping_stage_status", "graph_stage_status", "selected_class_uri",
    "graph_fingerprint", "ranker_name", "measure", "lrolesim_beta", "iterations",
    "iteration_mode", "ranked_candidate_count", "provisional_top3_count",
    "observed_answer_fact_count", "observed_candidate_fact_count",
    "ready_for_rationale_selection", "rationale_selection_status",
    "any_final_distractor_selected",
)


def _summary_row(handoff: RationaleSelectionHandoff) -> dict:
    counts = handoff.observed_fact_counts
    return {
        "pilot_slot": handoff.pilot_slot,
        "answer_uri": handoff.answer_uri,
        "display_label": handoff.display_label,
        "answer_local_index": handoff.answer_local_index,
        "primary_or_diagnostic": handoff.primary_or_diagnostic,
        "diagnostic_only": _b(handoff.diagnostic_only),
        "excluded_from_primary_policy_metrics": _b(handoff.diagnostic_only),
        "mapping_stage_status": handoff.mapping_stage_status,
        "graph_stage_status": handoff.graph_stage_status,
        "selected_class_uri": handoff.selected_class_uri or "",
        "graph_fingerprint": handoff.graph_fingerprint or "",
        "ranker_name": handoff.ranker_name,
        "measure": handoff.measure or "",
        "lrolesim_beta": ("" if handoff.lrolesim_beta is None
                          else repr(handoff.lrolesim_beta)),
        "iterations": ("" if handoff.iterations is None else handoff.iterations),
        "iteration_mode": (PILOT_ITERATION_MODE if handoff.measure else ""),
        "ranked_candidate_count": handoff.ranked_candidate_count,
        "provisional_top3_count": len(handoff.provisional_lrolesim_top3),
        "observed_answer_fact_count": counts.get("answer_facts", 0),
        "observed_candidate_fact_count": counts.get("candidate_facts", 0),
        "ready_for_rationale_selection": _b(handoff.ready_for_rationale_selection),
        "rationale_selection_status": handoff.rationale_selection_status,
        # Restated per row: Prompt 8D selects no distractor at all.
        "any_final_distractor_selected": _b(False),
    }


def write_extract_integration_summary(run: HandoffRun, out_dir: Path) -> None:
    """Exactly nine primary Answer rows. The diagnostic is NOT among them."""
    _write_csv(out_dir / "extract_integration_summary.csv",
               EXTRACT_INTEGRATION_SUMMARY_FIELDS,
               [_summary_row(h) for h in run.primary_handoffs])


def write_candidate_ranking_handoff(run: HandoffRun, out_dir: Path) -> None:
    """One record per primary Answer, carrying the COMPLETE ranked list."""
    _write_jsonl(out_dir / "candidate_ranking_handoff.jsonl",
                 [h.as_record() for h in run.primary_handoffs])


PROVISIONAL_TOP3_FIELDS = (
    "primary_or_diagnostic", "diagnostic_only",
    "excluded_from_primary_policy_metrics", "pilot_slot", "answer_uri",
    "display_label", "selected_class_uri", "ranker_name", "rank", "candidate_uri",
    "candidate_local_index", "lrolesim_score", "tie_group_id", "tie_group_size",
    "at_beta_floor", "is_final_distractor", "not_final_reason", "measure",
    "lrolesim_beta", "iterations", "graph_fingerprint",
    "rationale_selection_status",
)


def _top3_rows(handoff: RationaleSelectionHandoff) -> list[dict]:
    rows = []
    for candidate in handoff.provisional_lrolesim_top3:
        record = candidate.as_record()
        rows.append({
            "primary_or_diagnostic": handoff.primary_or_diagnostic,
            "diagnostic_only": _b(handoff.diagnostic_only),
            "excluded_from_primary_policy_metrics": _b(handoff.diagnostic_only),
            "pilot_slot": handoff.pilot_slot,
            "answer_uri": handoff.answer_uri,
            "display_label": handoff.display_label,
            "selected_class_uri": handoff.selected_class_uri or "",
            "ranker_name": handoff.ranker_name,
            "rank": candidate.rank,
            "candidate_uri": candidate.canonical_candidate_uri,
            "candidate_local_index": candidate.candidate_local_index,
            "lrolesim_score": _fmt_score(candidate.score),
            "tie_group_id": candidate.tie_group_id,
            "tie_group_size": candidate.tie_group_size,
            "at_beta_floor": _b(candidate.at_beta_floor),
            # Never a final distractor. Prompt 8D does not select distractors.
            "is_final_distractor": _b(False),
            "not_final_reason": record["not_final_reason"],
            "measure": handoff.measure or "",
            "lrolesim_beta": ("" if handoff.lrolesim_beta is None
                              else repr(handoff.lrolesim_beta)),
            "iterations": ("" if handoff.iterations is None
                           else handoff.iterations),
            "graph_fingerprint": handoff.graph_fingerprint or "",
            "rationale_selection_status": handoff.rationale_selection_status,
        })
    return rows


def write_provisional_top3_handoff(run: HandoffRun, out_dir: Path) -> None:
    """Primary provisional top-3 rows, then the diagnostic's, clearly flagged."""
    rows: list[dict] = []
    for handoff in run.primary_handoffs:
        rows.extend(_top3_rows(handoff))
    rows.extend(_top3_rows(run.diagnostic_handoff))
    _write_csv(out_dir / "provisional_top3_handoff.csv",
               PROVISIONAL_TOP3_FIELDS, rows)


def write_observed_facts(run: HandoffRun, out_dir: Path) -> None:
    """Observed one-hop facts, sorted and deduplicated, in three namespaces."""
    _write_jsonl(out_dir / "observed_answer_facts.jsonl",
                 serialize_owner_fact_sets(run.answer_fact_sets))
    _write_jsonl(out_dir / "observed_candidate_facts.jsonl",
                 serialize_owner_fact_sets(run.candidate_fact_sets))
    _write_jsonl(out_dir / "observed_diagnostic_facts.jsonl",
                 serialize_owner_fact_sets(run.diagnostic_fact_sets))


def write_sulfuric_acid_diagnostic_handoff(run: HandoffRun, out_dir: Path) -> None:
    """The diagnostic handoff, in its own file and its own namespace."""
    handoff = run.diagnostic_handoff
    primary_row = next(h for h in run.primary_handoffs
                       if h.answer_uri == EXPECTED_PRIMARY_FAILURE_ANSWER_URI)
    payload = {
        "diagnostic_only": True,
        "excluded_from_primary_policy_metrics": True,
        "answer_uri": handoff.answer_uri,
        "primary_record": {
            "mapping_stage_status": primary_row.mapping_stage_status,
            "graph_stage_status": primary_row.graph_stage_status,
            "ranked_candidate_count": primary_row.ranked_candidate_count,
            "ready_for_rationale_selection":
                primary_row.ready_for_rationale_selection,
            "note": ("Sulfuric acid remains the one PRIMARY failure. The "
                     "diagnostic below is engineering evidence only and enters "
                     "no primary count."),
        },
        "diagnostic_handoff": handoff.as_record(),
        "observed_fact_namespace": "observed_diagnostic_facts.jsonl",
        "observed_fact_owner_count": len(run.diagnostic_fact_sets),
        "observed_fact_total": sum(fs.fact_count for fs in run.diagnostic_fact_sets),
        "boundaries": {
            "counted_in_nine_answer_denominator": False,
            "counted_in_primary_graph_stage_yield": False,
            "counted_in_primary_ranked_candidate_total": False,
            "primary_failure_downgraded": False,
            "answer_replaced": False,
            "new_class_added": False,
            "any_final_distractor_selected": False,
        },
    }
    _write_json(out_dir / "sulfuric_acid_diagnostic_handoff.json", payload)


def write_contract_validation(run: HandoffRun, out_dir: Path) -> None:
    """What the section-5 contract check actually observed."""
    _write_json(out_dir / "contract_validation.json", {
        "ranker_name": run.ranker_name,
        "prompt8c_source": str(FROZEN_PROMPT8C_DIR.relative_to(REPO_ROOT)),
        "prompt8c_input_sha256": run.prompt8c_input_hashes,
        "protected_sources": run.protected_sources,
        "contract": run.contract_report.as_record(),
    })


def write_offline_replay_manifest(run: HandoffRun, out_dir: Path) -> None:
    compared = {}
    for name in REPLAY_COMPARED_FILES:
        path = out_dir / name
        compared[name] = {"sha256": sha256_file(path),
                          "size_bytes": path.stat().st_size}
    _write_json(out_dir / "offline_replay_manifest.json", {
        "mode": run.mode,
        "replay_command": (
            "python src/extract_221_and_select_distractors_ClaudeWeb_v2.py "
            "--mode pilot-lrolesim-handoff --output-dir <fresh directory>"),
        "byte_identical_files": list(REPLAY_COMPARED_FILES),
        "excluded_from_byte_identity": [
            "run_manifest.json (records the run clock, timings and git state)",
            "offline_replay_manifest.json (contains the hashes it verifies)",
        ],
        "file_hashes": compared,
        "network": run.guard_record,
        "http_calls": 0,
        "sparql_calls": 0,
        "pinned_local_kg": run.local_kg_record,
        "prompt8c_input_sha256": run.prompt8c_input_hashes,
        "protected_sources": run.protected_sources,
        "edgeset_cache": run.edgeset_cache_record,
    })


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


def write_run_manifest(run: HandoffRun, out_dir: Path,
                       raw_command: Sequence[str] = ()) -> None:
    report = run.contract_report
    _write_json(out_dir / "run_manifest.json", {
        "task": ("Prompt 8D — integrate the verified Prompt-8C LRoleSim rankings "
                 "into the Journal-2 extract pipeline"),
        "mode": run.mode,
        "ranker_name": run.ranker_name,
        "raw_command": list(raw_command),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "conda_env": os.environ.get("CONDA_DEFAULT_ENV", ""),
        "git": _git_state(),
        "frozen_prompt8c_dir": str(FROZEN_PROMPT8C_DIR.relative_to(REPO_ROOT)),
        "frozen_prompt8c_zip_expected_sha256": FROZEN_PROMPT8C_ZIP_SHA256,
        "prompt8c_input_sha256": run.prompt8c_input_hashes,
        "protected_sources": run.protected_sources,
        "pinned_local_kg": run.local_kg_record,
        "pinned_local_kg_expected_sha256": PINNED_LOCAL_KG_SHA256,
        "lrolesim_execution_path": {
            "measure": report.checks and "lrolesim_ed",
            "note": ("frozen and consumed, not recomputed: Prompt 8D reproduces "
                     "Prompt-8C ranks and never re-runs the kernel"),
        },
        "fact_schema_version": FACT_SCHEMA_VERSION,
        "edgeset_cache": run.edgeset_cache_record,
        "contract": report.as_record(),
        "counts": {
            "primary_answer_denominator": len(run.primary_handoffs),
            "primary_ready_for_rationale_selection": len(run.ready_handoffs),
            "primary_ranked_candidate_total": run.primary_ranked_total,
            "diagnostic_ranked_candidate_total":
                run.diagnostic_handoff.ranked_candidate_count,
            "observed_answer_fact_total":
                sum(fs.fact_count for fs in run.answer_fact_sets),
            "observed_candidate_fact_total":
                sum(fs.fact_count for fs in run.candidate_fact_sets),
            "observed_diagnostic_fact_total":
                sum(fs.fact_count for fs in run.diagnostic_fact_sets),
            "final_distractors_selected": 0,
            "rationales_generated": 0,
        },
        "network": run.guard_record,
        "stage_timings": [t.as_row() for t in run.timings],
        "open_world_note": (
            "Every serialized fact is OBSERVED in the pinned local KG. No "
            "negative fact is generated, and the absence of a triple is never "
            "recorded as evidence that the triple is false."),
        "scope_note": (
            "Stops before final distractor selection, exact rationale set cover, "
            "rarity ranking and MCQ verbalization. Every provisional record "
            "carries is_final_distractor = false and "
            "rationale_selection_status = " + RATIONALE_SELECTION_DEFERRED + "."),
    })


def write_all_outputs(run: HandoffRun, out_dir: str | Path,
                      raw_command: Sequence[str] = ()) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_extract_integration_summary(run, out_dir)
    write_candidate_ranking_handoff(run, out_dir)
    write_provisional_top3_handoff(run, out_dir)
    write_observed_facts(run, out_dir)
    write_sulfuric_acid_diagnostic_handoff(run, out_dir)
    write_contract_validation(run, out_dir)
    write_offline_replay_manifest(run, out_dir)
    write_run_manifest(run, out_dir, raw_command)
    return out_dir


# ==========================================================================
# 6) THE BASELINE PATH:  legacy-overlap
# ==========================================================================

def run_legacy_overlap(answer_uris: Sequence[str], *, pickle_path: str,
                       out_path: str, k: int = 3) -> int:
    """The retained OverlapStrict/OverlapLoose baseline. NETWORK AND MODEL.

    Isolated behind an explicit mode. It is imported only here, so the proposed
    path never pulls in SPARQL, spaCy or sentence-transformers, and it is never
    reached by an omitted or misspelled mode.
    """
    warnings.warn(
        f"mode {MODE_LEGACY_OVERLAP!r} runs the RETAINED BASELINE "
        f"{RANKER_LEGACY_OVERLAP_BASELINE!r}. Its output is a baseline result and "
        f"must never be reported as the proposed Journal-2 method.",
        DeprecationWarning, stacklevel=2)

    from selection import legacy_overlap             # local: network- and model-bearing

    kg = load_kg(pickle_path)
    store = legacy_overlap.AbstractStore()
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")
    except Exception:                                # noqa: BLE001
        nlp = None
        print("[WARN] spaCy unavailable; skipping the proper-noun check.")

    written = 0
    with open(out_path, "a", encoding="utf-8") as f:
        for i, uri in enumerate(answer_uris, 1):
            print(f"\n[{i}/{len(answer_uris)}] {uri}")
            record = legacy_overlap.build_choices(uri, kg, store, nlp=nlp, k=k)
            if record:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                written += 1
    print(f"\nbaseline yield: {written}/{len(answer_uris)} -> {out_path}")
    return written


# ==========================================================================
# 7) MODE DISPATCH AND CLI
# ==========================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python src/extract_221_and_select_distractors_ClaudeWeb_v2.py",
        description=("Journal-2 candidate-ranking entrypoint. The mode is "
                     "mandatory: there is no default, and an unknown mode is an "
                     "error rather than a fall-through to the baseline."),
    )
    # required=True and choices=MODES together make an omitted or misspelled mode
    # an argparse error (exit code 2). Neither can reach the baseline silently.
    parser.add_argument("--mode", choices=MODES, required=True,
                        help=(f"{MODE_PILOT_LROLESIM_HANDOFF}: proposed path, "
                              f"offline, consumes the verified Prompt-8C LRoleSim "
                              f"rankings. {MODE_PILOT_RATIONALE_SELECTION}: "
                              f"proposed path, offline, exact rationale set cover "
                              f"and distractor selection over the frozen "
                              f"Prompt-8D handoff. {MODE_LEGACY_OVERLAP}: "
                              f"retained baseline, requires the network."))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--prompt8c-dir", default=str(FROZEN_PROMPT8C_DIR))
    parser.add_argument("--local-kg", default=str(PINNED_LOCAL_KG))
    parser.add_argument("--quiet", action="store_true")
    # pilot-rationale-selection only. Defaults are resolved lazily against
    # pipeline.rationale_selection_run so that parsing arguments never imports the
    # rationale layer, and so that the two files cannot drift on what "the primary
    # configuration" means.
    parser.add_argument("--prompt8d-dir", default=str(DEFAULT_PROMPT8D_DIR))
    parser.add_argument("--rho", type=int, default=3,
                        help=("pilot-rationale-selection: the largest rationale "
                              "that may be presented. A PRESENTATION budget, not "
                              "a correctness parameter."))
    # legacy-overlap only
    parser.add_argument("--pickle", default="infobox.pickle_EnglishVersion_EntityType")
    parser.add_argument("--answers", help="legacy-overlap: file of Answer URIs")
    parser.add_argument("--answer", help="legacy-overlap: one Answer URI")
    parser.add_argument("--out", default="choices.jsonl")
    parser.add_argument("-k", type=int, default=3)
    return parser


def dispatch(mode: str, args: argparse.Namespace,
             raw_command: Sequence[str] = ()) -> int:
    """Route to exactly one named mode, or refuse.

    There is deliberately no `else` that runs something: an unrecognised mode
    raises UnknownModeError.
    """
    if mode == MODE_PILOT_LROLESIM_HANDOFF:
        run = run_pilot_lrolesim_handoff(
            prompt8c_dir=args.prompt8c_dir,
            local_kg_path=args.local_kg,
            verbose=not args.quiet,
        )
        out_dir = write_all_outputs(run, args.output_dir, raw_command)
        print(f"\n[done] mode={run.mode}  ranker={run.ranker_name}")
        print(f"       outputs -> {out_dir}")
        print(f"       primary Answers: {len(run.primary_handoffs)} "
              f"({len(run.ready_handoffs)} ready for rationale selection)")
        print(f"       primary ranked candidates: {run.primary_ranked_total}")
        print(f"       network attempts: "
              f"{run.guard_record['network_attempts']} (http 0, sparql 0)")
        print(f"       rationale selection: {RATIONALE_SELECTION_DEFERRED}")
        return 0

    if mode == MODE_PILOT_RATIONALE_SELECTION:
        # Delegated in full. This entrypoint owns no set-cover mathematics, no
        # distractor-combination search and no evidence policy; it resolves the
        # mode and hands over. Imported inside the branch so that neither of the
        # other two modes pays for, or is coupled to, the rationale layer.
        from pipeline import rationale_selection_run   # local: mode-scoped

        run = rationale_selection_run.run_rationale_selection(
            prompt8d_dir=args.prompt8d_dir,
            k=args.k,
            rho=args.rho,
            verbose=not args.quiet,
        )
        out_dir = rationale_selection_run.write_all_outputs(
            run, args.output_dir, raw_command)
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
        print("       every selected MCQ: requires_human_validation=true, "
              "human_validation_status=NOT_CHECKED, publishable_final=false")
        return 0

    if mode == MODE_LEGACY_OVERLAP:
        if args.answer:
            uris = [args.answer]
        elif args.answers:
            uris = [line.strip() for line in open(args.answers) if line.strip()]
        else:
            raise ExtractIntegrationError(
                f"mode {MODE_LEGACY_OVERLAP!r} requires --answer or --answers")
        run_legacy_overlap(uris, pickle_path=args.pickle, out_path=args.out,
                           k=args.k)
        return 0

    raise UnknownModeError(
        f"unknown mode {mode!r}; expected one of {MODES}. There is no default "
        f"mode: an omitted or misspelled mode must never fall back to "
        f"{MODE_LEGACY_OVERLAP!r}.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(argv)
    raw_command = ["python", "src/extract_221_and_select_distractors_ClaudeWeb_v2.py",
                   *argv]
    return dispatch(args.mode, args, raw_command)


# ==========================================================================
# 8) BACKWARD COMPATIBILITY
# ==========================================================================

#: Legacy names that now live in selection.legacy_overlap. Resolved lazily by the
#: module __getattr__ below so that merely importing this module never imports the
#: SPARQL layer — `category_extractor_ClaudeWeb_v2` opens an SQLite cache at
#: import time, which would both create a file as a side effect of an import and
#: make the proposed path's "zero SPARQL" claim unverifiable.
_LEGACY_ATTRIBUTES = (
    "ALPHA", "BETA", "THETA", "K_DISTRACTORS", "LAMBDA_MMR", "MAX_REDUNDANCY",
    "MAX_CANDIDATES", "ABSTRACT_BATCH", "SBERT_MODEL_NAME", "ABSTRACT_CACHE",
    "IN", "OUT", "AbstractStore", "CandidateScore", "LegacyOverlapRanker",
    "build_choices", "distinguishing_facts", "get_candidates_for_class",
    "group_by_key", "legacy_single_fact_common_filter", "overlap_loose",
    "overlap_strict", "rank_candidates", "select_distractor_set",
)


def __getattr__(name: str):
    """Resolve retained baseline names on first use, with a deprecation warning."""
    if name in _LEGACY_ATTRIBUTES:
        warnings.warn(
            f"{name!r} moved to selection.legacy_overlap and belongs to the "
            f"retained baseline {RANKER_LEGACY_OVERLAP_BASELINE!r}, not to the "
            f"proposed Journal-2 path. Import it from selection.legacy_overlap "
            f"explicitly.",
            DeprecationWarning, stacklevel=2)
        from selection import legacy_overlap
        return getattr(legacy_overlap, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def select_top100(answer_idx, cand_list_idx, out_neighbor, index_url,
                  alpha=1.0, beta=0.5, threshold=0.60):
    """DEPRECATED since the v2 rewrite; never reachable from the proposed path."""
    raise NotImplementedError(
        "select_top100() was replaced by selection.legacy_overlap.rank_candidates() "
        "for the baseline, and by selection.lrolesim_handoff.LRoleSimHandoffRanker "
        "for the proposed Journal-2 path."
    )


if __name__ == "__main__":
    raise SystemExit(main())
