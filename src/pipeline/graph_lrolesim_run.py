############################################################################
# src/pipeline/graph_lrolesim_run.py
#
# Week-2 orchestration:
#   frozen local candidate mappings
#     -> deterministic seeded graph-admission order
#     -> M1 graph-budget policy with approved-class fallback
#     -> fixed-iteration LRoleSim L_ed ranking (beta 0.2, exactly 3 iterations)
#
# THE TWO GATES ARE DIFFERENT GATES
#   Week 1 measured a MAPPING gate: ">= 10 members of this approved class exist in
#   the pinned local KG". This task adds a GRAPH gate: ">= 10 of those candidates
#   are still retained after the node budget admitted their COMPLETE one-hop
#   neighbourhoods". Passing the first says nothing about the second: a class of 78
#   locally mapped members can still collapse below ten once each admitted
#   candidate has to bring its whole neighbourhood inside 1200 nodes. Mapping
#   feasibility is therefore never reinterpreted as graph feasibility — the two
#   are recorded as separate columns with separate statuses.
#
# WHAT THIS MODULE DOES NOT DO
#   * no network and no SPARQL — an offline guard is installed and its attempt
#     counter is published in the run manifest;
#   * no mathematics: the graph budget is src/kg/graph_view.py and the ranker is
#     src/lrolesim/adapter.py, both used unmodified;
#   * no convergence run — only adapter.run_lrolesim_fixed via rank_m1_graph;
#   * no rationale feasibility, no final distractor triple, no verbalization. The
#     top three are published strictly as `provisional_lrolesim_top3`.
#
# L_edt IS REFUSED, NOT SUBSTITUTED
#   The pinned pickle's index_type is 0 for every node. Running L_edt against an
#   all-zero type map would silently reproduce L_ed and be reported as an
#   independent ablation, so it is refused with
#   L_EDT_DEFERRED_NO_VALID_ENTITY_TYPE_MAP.
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

from classes.policy import (                        # noqa: E402
    POSITION_FALLBACK_1,
    POSITION_FALLBACK_2,
    POSITION_PREFERRED,
    AnswerClassPolicy,
    PilotClassPolicy,
    assert_policies_agree,
    load_policy_csv,
    load_policy_json,
)
from kg.graph_view import (                         # noqa: E402
    DEFAULT_MAX_NODES,
    GRAPH_BUDGET_OK,
    MAX_ACCEPTED_CANDIDATES,
    MIN_ACCEPTED_CANDIDATES,
    M1Graph,
    build_m1_graph,
)
from kg.loader import load_local_kg, sha256_file    # noqa: E402
from lrolesim import adapter as lrolesim_adapter    # noqa: E402
from pipeline.candidate_order import (              # noqa: E402
    GRAPH_ADMISSION_ORDER_DOMAIN,
    GRAPH_ADMISSION_ORDER_NAME,
    ORIGIN_EXACT,
    ORIGIN_REDIRECT,
    GraphAdmissionOrder,
    MappedCandidate,
    order_candidates_for_graph_admission,
)

# --- Pinned inputs ---------------------------------------------------------
PINNED_LOCAL_KG = REPO_ROOT / "data" / "infobox.pickle_EnglishVersion_EntityType"
PINNED_LOCAL_KG_SHA256 = (
    "e230c5b95e20093631697624d9c46f30a14081b3f415d5027ffaf313bdbbea1b"
)
FROZEN_MAPPING_DIR = (
    REPO_ROOT / "outputs" / "journal2_week1_local_mapping_2026-07-30"
)
FROZEN_MAPPING_ZIP = (
    REPO_ROOT / "outputs" / "journal2_week1_local_mapping_2026-07-30.zip"
)
FROZEN_MAPPING_ZIP_SHA256 = (
    "c4fb64b24a862651561575ebca8c684d3a4a526a0b98c6bb274467a2734f10c8"
)
POLICY_CSV = REPO_ROOT / "data" / "pilot_class_policy_v1.csv"
POLICY_JSON = REPO_ROOT / "data" / "pilot_class_policy_v1.json"

DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_graph_lrolesim_pilot_2026-07-30"
)
DEFAULT_SCORE_CACHE = (
    REPO_ROOT / "data" / "cache" / "journal2_week2_graph_lrolesim_v1.jsonl"
)

# Source files whose content changes the meaning of a cached score.
FINGERPRINTED_SOURCES = {
    "graph_builder": SRC_DIR / "kg" / "graph_view.py",
    "lrolesim_adapter": SRC_DIR / "lrolesim" / "adapter.py",
    "lrolesim_kernel": SRC_DIR / "MCQ_lrolesim_ClaudeWeb_v2.py",
    "candidate_order": SRC_DIR / "pipeline" / "candidate_order.py",
}

# --- Graph-stage gate ------------------------------------------------------
GRAPH_STAGE_MAPPING_GATE = 10           # mapped candidates required to even try
GRAPH_GATE_MIN_CANDIDATES = MIN_ACCEPTED_CANDIDATES     # 10 retained after budget
GRAPH_MAX_CANDIDATES = MAX_ACCEPTED_CANDIDATES          # 50
GRAPH_MAX_NODES = DEFAULT_MAX_NODES                     # 1200

# --- Graph-stage statuses --------------------------------------------------
GRAPH_SELECTED_PREFERRED = "GRAPH_SELECTED_PREFERRED"
GRAPH_SELECTED_FALLBACK_1 = "GRAPH_SELECTED_FALLBACK_1"
GRAPH_SELECTED_FALLBACK_2 = "GRAPH_SELECTED_FALLBACK_2"
NO_GRAPH_FEASIBLE_APPROVED_CLASS = "NO_GRAPH_FEASIBLE_APPROVED_CLASS"

_GRAPH_STATUS_FOR_POSITION = {
    POSITION_PREFERRED: GRAPH_SELECTED_PREFERRED,
    POSITION_FALLBACK_1: GRAPH_SELECTED_FALLBACK_1,
    POSITION_FALLBACK_2: GRAPH_SELECTED_FALLBACK_2,
}

# Mapping-stage status carried forward from the frozen Week-1 outputs.
NO_MAPPING_FEASIBLE_APPROVED_CLASS = "NO_MAPPING_FEASIBLE_APPROVED_CLASS"

# --- Per-class attempt outcomes -------------------------------------------
ATTEMPT_GRAPH_FEASIBLE = "GRAPH_FEASIBLE"
ATTEMPT_GRAPH_BUDGET_INSUFFICIENT = "GRAPH_BUDGET_INSUFFICIENT_CANDIDATES"
ATTEMPT_SKIPPED_MAPPING_COUNT_BELOW_GATE = "SKIPPED_MAPPING_COUNT_BELOW_GRAPH_STAGE_GATE"
ATTEMPT_SKIPPED_RETRIEVAL_INCOMPLETE = "SKIPPED_RETRIEVAL_INCOMPLETE"
ATTEMPT_NOT_ATTEMPTED_EARLIER_CLASS_SELECTED = "NOT_ATTEMPTED_EARLIER_CLASS_SELECTED"

# --- L_edt ablation --------------------------------------------------------
L_EDT_DEFERRED = "L_EDT_DEFERRED_NO_VALID_ENTITY_TYPE_MAP"

# --- Record scope ----------------------------------------------------------
SCOPE_PRIMARY = "primary"
SCOPE_DIAGNOSTIC = "diagnostic"

# --- Sulfuric acid engineering diagnostic ---------------------------------
# Explicitly separate from the primary policy: it does not change the mapping
# outcome, the nine-Answer denominator, or the primary graph-stage yield.
DIAGNOSTIC_ANSWER_URI = "http://dbpedia.org/resource/Sulfuric_acid"
DIAGNOSTIC_CLASS_URI = "http://dbpedia.org/resource/Category:Mineral_acids"
DIAGNOSTIC_EXPECTED_MAPPED_COUNT = 6
DIAGNOSTIC_MIN_CANDIDATES = 3           # enough to run LRoleSim at all

# --- Run modes -------------------------------------------------------------
MODE_RUN = "run"
MODE_REPLAY = "replay"

CACHE_SCHEMA_VERSION = "journal2-week2-graph-lrolesim-cache-v1"


class PipelineError(Exception):
    """Base class for Week-2 orchestration failures."""


class OfflineGuardTripped(PipelineError):
    """The run attempted a network connection. Every input must be local."""


class EntityTypeMapUnusableError(PipelineError):
    """The pinned pickle's entity-type map cannot support the L_edt ablation."""


class MappingInputError(PipelineError):
    """The frozen Week-1 mapping outputs are missing, altered or inconsistent."""


class CacheMissInReplayError(PipelineError):
    """Replay mode needs a cached score and the fingerprint is absent."""


class FrozenInputError(PipelineError):
    """A pinned input file does not have its expected SHA-256."""


# ==========================================================================
# 1) OFFLINE GUARD
# ==========================================================================

@dataclass
class OfflineGuard:
    """Blocks and COUNTS outbound socket connections for the whole run.

    The pilot's claim is "zero HTTP calls, zero SPARQL calls". A guard that
    actually fails the run turns that from a promise into a checked property, and
    the published counter is evidence rather than an assurance.
    """

    attempts: list[str] = field(default_factory=list)
    _installed: bool = False
    _saved: dict = field(default_factory=dict)

    def install(self) -> None:
        if self._installed:
            return
        guard = self

        def _deny(target: object) -> str:
            return f"{target!r}"

        real_connect = socket.socket.connect
        real_connect_ex = socket.socket.connect_ex
        real_create = socket.create_connection

        def blocked_connect(self, address, *a, **k):      # noqa: ANN001
            guard.attempts.append(_deny(address))
            raise OfflineGuardTripped(
                f"outbound connection to {address!r} refused: this run must read "
                f"only local frozen inputs")

        def blocked_connect_ex(self, address, *a, **k):   # noqa: ANN001
            guard.attempts.append(_deny(address))
            raise OfflineGuardTripped(
                f"outbound connection to {address!r} refused")

        def blocked_create(address, *a, **k):             # noqa: ANN001
            guard.attempts.append(_deny(address))
            raise OfflineGuardTripped(
                f"outbound connection to {address!r} refused")

        self._saved = {
            "connect": real_connect,
            "connect_ex": real_connect_ex,
            "create_connection": real_create,
        }
        socket.socket.connect = blocked_connect          # type: ignore[method-assign]
        socket.socket.connect_ex = blocked_connect_ex    # type: ignore[method-assign]
        socket.create_connection = blocked_create        # type: ignore[assignment]
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        socket.socket.connect = self._saved["connect"]          # type: ignore[method-assign]
        socket.socket.connect_ex = self._saved["connect_ex"]    # type: ignore[method-assign]
        socket.create_connection = self._saved["create_connection"]  # type: ignore[assignment]
        self._installed = False

    def as_record(self) -> dict:
        return {
            "installed": self._installed,
            "network_attempts": len(self.attempts),
            "http_calls": 0 if not self.attempts else len(self.attempts),
            "sparql_calls": 0 if not self.attempts else len(self.attempts),
            "attempted_addresses": list(self.attempts),
        }


# ==========================================================================
# 2) ENTITY-TYPE MAP VALIDATION  (the L_edt refusal)
# ==========================================================================

@dataclass(frozen=True)
class EntityTypeMapVerdict:
    """Whether the pinned pickle's index_type can support L_edt."""

    usable: bool
    status: str
    entry_count: int
    distinct_value_count: int
    nonzero_count: int
    sample_values: tuple[int, ...]

    def as_record(self) -> dict:
        return {
            "l_edt_status": self.status,
            "entity_type_map_usable": self.usable,
            "index_type_entry_count": self.entry_count,
            "index_type_distinct_value_count": self.distinct_value_count,
            "index_type_nonzero_count": self.nonzero_count,
            "index_type_sample_values": list(self.sample_values),
        }


def inspect_entity_type_map(index_type: Mapping[int, int]) -> EntityTypeMapVerdict:
    """Measure the type map instead of assuming it is populated.

    `0` is the pickle's "Others" bucket. A map whose every value is 0 carries no
    type information at all, so L_edt's type-aware equivalence relation collapses
    to L_ed's. That is a DEFERRAL, not an equivalence claim: see the refusal in
    `assert_entity_type_map_usable`.
    """
    nonzero = 0
    distinct: set[int] = set()
    for value in index_type.values():
        distinct.add(value)
        if value != 0:
            nonzero += 1
    usable = nonzero > 0
    return EntityTypeMapVerdict(
        usable=usable,
        status="L_EDT_ELIGIBLE" if usable else L_EDT_DEFERRED,
        entry_count=len(index_type),
        distinct_value_count=len(distinct),
        nonzero_count=nonzero,
        sample_values=tuple(sorted(distinct)[:8]),
    )


def assert_entity_type_map_usable(index_type: Mapping[int, int]) -> EntityTypeMapVerdict:
    """Refuse L_edt on an all-zero type map.

    src/lrolesim/adapter.py already refuses an EMPTY index_type, but an all-zero
    map is non-empty and would pass that check while producing L_ed's numbers
    under L_edt's name. This is the missing guard, and it lives here rather than in
    the protected adapter.
    """
    verdict = inspect_entity_type_map(index_type)
    if not verdict.usable:
        raise EntityTypeMapUnusableError(
            f"{L_EDT_DEFERRED}: index_type has {verdict.entry_count} entries and "
            f"{verdict.nonzero_count} non-zero values, so every node is type 0 "
            f"('Others'). L_edt on this map would reproduce L_ed exactly and be "
            f"reported as an independent ablation. L_edt is deferred until an "
            f"independently validated entity-type source exists."
        )
    return verdict


# ==========================================================================
# 3) FINGERPRINTS AND THE RESUMABLE SCORE CACHE
# ==========================================================================

def _canonical_json(payload: object) -> str:
    """Key-sorted, separator-pinned JSON. The byte form a fingerprint hashes."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"))


def _digest_of(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceHashes:
    """SHA-256 of every source file that can change a score's meaning."""

    hashes: Mapping[str, str]

    @classmethod
    def collect(cls, paths: Mapping[str, Path] = None) -> "SourceHashes":
        paths = FINGERPRINTED_SOURCES if paths is None else paths
        return cls(hashes={name: sha256_file(path)
                           for name, path in sorted(paths.items())})

    def as_record(self) -> dict:
        return dict(self.hashes)


@dataclass(frozen=True)
class RunFingerprint:
    """The complete graph/run fingerprint that keys a cached score result.

    Every field is part of the key. A cached result is reusable only when ALL of
    them match, so changing the ordering policy, the budget, the measure, the beta,
    the iteration count, the pinned KG or ANY of the fingerprinted source files
    invalidates the entry instead of silently reusing a stale score.
    """

    payload: Mapping[str, object]

    @property
    def graph_fingerprint(self) -> str:
        """Structure only: which graph, built from what, by which builder."""
        return _digest_of(self.payload["graph"])

    @property
    def run_fingerprint(self) -> str:
        """Structure plus the ranker configuration and ranker source hashes."""
        return _digest_of({"graph": self.payload["graph"],
                           "run": self.payload["run"]})

    def as_record(self) -> dict:
        return {
            "graph_fingerprint": self.graph_fingerprint,
            "run_fingerprint": self.run_fingerprint,
            "fields": json.loads(_canonical_json(self.payload)),
        }


def build_run_fingerprint(
    *,
    local_kg_sha256: str,
    answer_uri: str,
    class_uri: str,
    ordered_accepted_candidate_uris: Sequence[str],
    retained_node_uris: Sequence[str],
    max_candidates: int,
    max_nodes: int,
    measure: str,
    lrolesim_beta: float,
    iterations: int,
    source_hashes: SourceHashes,
    order_domain: str = GRAPH_ADMISSION_ORDER_DOMAIN,
) -> RunFingerprint:
    """Assemble the fingerprint required by the task's item 8.

    Retained nodes enter as a SHA-256 over their sorted URIs rather than as raw
    local indices: indices are an artefact of pickle construction, so a URI-based
    digest keeps the key meaningful even though the pinned KG hash is also part of
    the key.
    """
    node_uris = sorted(retained_node_uris)
    graph = {
        "local_kg_sha256": local_kg_sha256,
        "answer_uri": answer_uri,
        "class_uri": class_uri,
        "graph_admission_order_domain": order_domain,
        "ordered_accepted_candidate_uris": list(ordered_accepted_candidate_uris),
        "retained_node_count": len(node_uris),
        "retained_node_uris_sha256": _digest_of(node_uris),
        "max_candidates": int(max_candidates),
        "max_nodes": int(max_nodes),
        "graph_builder_sha256": source_hashes.hashes["graph_builder"],
        "candidate_order_sha256": source_hashes.hashes["candidate_order"],
    }
    run = {
        "measure": measure,
        "lrolesim_beta": float(lrolesim_beta),
        "iterations": int(iterations),
        "iteration_mode": "fixed",
        "lrolesim_adapter_sha256": source_hashes.hashes["lrolesim_adapter"],
        "lrolesim_kernel_sha256": source_hashes.hashes["lrolesim_kernel"],
    }
    return RunFingerprint(payload={"graph": graph, "run": run})


class ScoreCache:
    """A compact, append-only JSONL cache of LRoleSim score vectors.

    Keyed by the full run fingerprint. Scores are stored against the CANONICAL
    CANDIDATE URI, not the local index, so a cache entry stays readable without
    the 1.2 GB pickle and cannot be silently misapplied to a renumbered graph.

    Deliberately not another cache framework: one file, one dict, two operations.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.entries: dict[str, dict] = {}
        self.hits = 0
        self.misses = 0
        self.writes = 0

    def load(self) -> "ScoreCache":
        if not self.path.is_file():
            return self
        with open(self.path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise PipelineError(
                        f"{self.path.name} line {lineno}: corrupt cache record: {exc}"
                    ) from exc
                if record.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
                    # A different schema is not a partial hit; skip it rather than
                    # guessing which fields still mean what.
                    continue
                key = record.get("run_fingerprint")
                if isinstance(key, str):
                    # A later record for the same fingerprint supersedes an earlier
                    # one; identical fingerprints imply identical inputs.
                    self.entries[key] = record
        return self

    def get(self, fingerprint: RunFingerprint) -> Optional[dict]:
        key = fingerprint.run_fingerprint
        record = self.entries.get(key)
        if record is None:
            self.misses += 1
            return None
        # Belt and braces: the key IS the digest of the fields, but comparing the
        # stored fields too makes a truncated or hand-edited cache fail loudly.
        if record.get("fields") != json.loads(_canonical_json(fingerprint.payload)):
            self.misses += 1
            return None
        self.hits += 1
        return record

    def put(self, fingerprint: RunFingerprint, scores: Sequence[tuple[str, float]],
            iterations_run: int, node_count: int) -> dict:
        record = {
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "run_fingerprint": fingerprint.run_fingerprint,
            "graph_fingerprint": fingerprint.graph_fingerprint,
            "fields": json.loads(_canonical_json(fingerprint.payload)),
            "node_count": int(node_count),
            "iterations_run": int(iterations_run),
            # repr-free float round-trip: json emits the shortest exact form.
            "scores": [[uri, float(score)] for uri, score in scores],
        }
        self.entries[record["run_fingerprint"]] = record
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(_canonical_json(record) + "\n")
        self.writes += 1
        return record

    def as_record(self) -> dict:
        return {
            "path": str(self.path.relative_to(REPO_ROOT))
                    if self.path.is_absolute() and REPO_ROOT in self.path.parents
                    else str(self.path),
            "schema_version": CACHE_SCHEMA_VERSION,
            "entry_count": len(self.entries),
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
        }


# ==========================================================================
# 4) FROZEN WEEK-1 MAPPING INPUTS
# ==========================================================================

@dataclass(frozen=True)
class ClassMappingFacts:
    """Week-1's mapping outcome for one (Answer, approved class) pair."""

    pilot_slot: int
    answer_uri: str
    answer_local_index: int
    class_position: str
    class_uri: str
    retrieval_complete: bool
    mapped_candidate_count_excluding_answer: int
    accepted: tuple[MappedCandidate, ...]

    @property
    def passes_graph_stage_mapping_gate(self) -> bool:
        """The GRAPH-STAGE eligibility test of task item 4 — not graph feasibility."""
        return (self.retrieval_complete
                and self.mapped_candidate_count_excluding_answer
                >= GRAPH_STAGE_MAPPING_GATE)


@dataclass(frozen=True)
class FrozenMappingInputs:
    """Everything this task reads out of the frozen Week-1 evidence package."""

    facts: Mapping[tuple[int, str], ClassMappingFacts]
    mapping_stage_status: Mapping[int, str]
    selected_mapping_class: Mapping[int, Optional[str]]
    answer_local_index: Mapping[int, int]
    source_hashes: Mapping[str, str]

    def for_pair(self, pilot_slot: int, class_uri: str) -> ClassMappingFacts:
        try:
            return self.facts[(pilot_slot, class_uri)]
        except KeyError:
            raise MappingInputError(
                f"the frozen mapping outputs contain no record for pilot slot "
                f"{pilot_slot} and class {class_uri!r}"
            ) from None


def _parse_bool(text: str, label: str) -> bool:
    lowered = (text or "").strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise MappingInputError(f"{label}: expected 'true' or 'false', got {text!r}")


def canonical_candidate_uri(record: Mapping[str, object]) -> str:
    """The URI of the local node this mapping record resolved to.

    REDIRECT records resolved through `redirect_target_uri`, so THAT is the local
    node's own URI; EXACT records resolved on the retrieved URI itself. Using
    `normalized_member_uri` for a redirect would key the ordering on an alias that
    is not the graph node.
    """
    origin = record.get("mapping_origin")
    if origin == ORIGIN_REDIRECT:
        target = record.get("redirect_target_uri")
        if not isinstance(target, str) or not target:
            raise MappingInputError(
                f"REDIRECT record without redirect_target_uri: {record!r}")
        return target
    if origin == ORIGIN_EXACT:
        normalized = record.get("normalized_member_uri")
        if not isinstance(normalized, str) or not normalized:
            raise MappingInputError(
                f"EXACT record without normalized_member_uri: {record!r}")
        return normalized
    raise MappingInputError(
        f"accepted mapping record has unusable mapping_origin {origin!r}")


def verify_frozen_mapping_zip(
    zip_path: str | Path = FROZEN_MAPPING_ZIP,
    expected_sha256: str = FROZEN_MAPPING_ZIP_SHA256,
) -> dict:
    """Pin this run to the exact Week-1 evidence package.

    The unpacked directory is what the run reads, but the ZIP is what was frozen
    and reported, so its hash is the thing worth checking: a mismatch means the
    inputs are no longer the ones the previous task certified.
    """
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise FrozenInputError(f"frozen Week-1 evidence package not found: {zip_path}")
    digest = sha256_file(zip_path)
    if digest != expected_sha256:
        raise FrozenInputError(
            f"{zip_path.name}: SHA-256 mismatch.\n"
            f"  expected: {expected_sha256}\n"
            f"  found:    {digest}")
    return {"path": str(zip_path.relative_to(REPO_ROOT)),
            "sha256": digest,
            "size_bytes": zip_path.stat().st_size}


def load_frozen_mapping_inputs(
    mapping_dir: str | Path = FROZEN_MAPPING_DIR,
) -> FrozenMappingInputs:
    """Read mapping_summary.csv, selected_mapping_class.csv, mapped_candidates.jsonl.

    Read-only. The frozen package is evidence from a completed task and is never
    rewritten here — including its two documented provenance errors, which are
    corrected in this task's report instead.
    """
    mapping_dir = Path(mapping_dir)
    summary_path = mapping_dir / "mapping_summary.csv"
    selected_path = mapping_dir / "selected_mapping_class.csv"
    candidates_path = mapping_dir / "mapped_candidates.jsonl"
    for path in (summary_path, selected_path, candidates_path):
        if not path.is_file():
            raise MappingInputError(f"frozen mapping output not found: {path}")

    # --- accepted candidates, grouped by (slot, class) --------------------
    grouped: dict[tuple[int, str], list[MappedCandidate]] = {}
    with open(candidates_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if not record.get("accepted"):
                continue
            local_index = record.get("local_index")
            if not isinstance(local_index, int) or isinstance(local_index, bool):
                raise MappingInputError(
                    f"{candidates_path.name} line {lineno}: accepted record "
                    f"without an integer local_index")
            key = (int(record["pilot_slot"]), str(record["class_uri"]))
            grouped.setdefault(key, []).append(MappedCandidate(
                canonical_uri=canonical_candidate_uri(record),
                local_index=local_index,
                mapping_origin=str(record["mapping_origin"]),
                retrieved_uri=str(record["normalized_member_uri"]),
            ))

    # --- per-(Answer, class) mapping facts --------------------------------
    facts: dict[tuple[int, str], ClassMappingFacts] = {}
    answer_index: dict[int, int] = {}
    with open(summary_path, encoding="utf-8", newline="") as f:
        for lineno, row in enumerate(csv.DictReader(f), start=2):
            label = f"{summary_path.name} line {lineno}"
            slot = int(row["pilot_slot"])
            class_uri = row["class_uri"]
            key = (slot, class_uri)
            count = int(row["mapped_candidate_count_excluding_answer"])
            accepted = tuple(grouped.get(key, ()))
            if len(accepted) != count:
                # The summary count and the per-candidate records must agree, or
                # the graph gate would be applied to a different candidate set than
                # the one actually offered to the builder.
                raise MappingInputError(
                    f"{label}: mapping_summary reports {count} mapped candidates "
                    f"but mapped_candidates.jsonl holds {len(accepted)} accepted "
                    f"records for slot {slot} / {class_uri}")
            answer_index[slot] = int(row["answer_local_index"])
            facts[key] = ClassMappingFacts(
                pilot_slot=slot,
                answer_uri=row["answer_uri"],
                answer_local_index=int(row["answer_local_index"]),
                class_position=row["class_position"],
                class_uri=class_uri,
                retrieval_complete=_parse_bool(row["retrieval_complete"],
                                               f"{label} retrieval_complete"),
                mapped_candidate_count_excluding_answer=count,
                accepted=accepted,
            )

    # --- mapping-stage outcome per Answer ---------------------------------
    mapping_status: dict[int, str] = {}
    selected_class: dict[int, Optional[str]] = {}
    with open(selected_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            slot = int(row["pilot_slot"])
            mapping_status[slot] = row["mapping_stage_status"]
            selected_class[slot] = row["selected_class_uri"] or None

    return FrozenMappingInputs(
        facts=facts,
        mapping_stage_status=mapping_status,
        selected_mapping_class=selected_class,
        answer_local_index=answer_index,
        source_hashes={
            "mapping_summary.csv": sha256_file(summary_path),
            "selected_mapping_class.csv": sha256_file(selected_path),
            "mapped_candidates.jsonl": sha256_file(candidates_path),
        },
    )


# ==========================================================================
# 5) GRAPH-STAGE ATTEMPTS AND RANKINGS
# ==========================================================================

@dataclass(frozen=True)
class ClassGraphAttempt:
    """One approved class considered at the graph stage, and its outcome."""

    pilot_slot: int
    answer_uri: str
    class_position: str
    class_uri: str
    attempted: bool
    outcome: str
    retrieval_complete: bool
    mapped_candidate_count: int
    graph_stage_eligible: bool
    ordered_candidate_count: int
    accepted_candidate_count: int
    retained_node_count: int
    retained_edge_count: int
    candidate_cap_reached: bool
    node_budget_bound: bool
    rejected_would_exceed_max_nodes: int
    detail: str

    def as_row(self) -> dict:
        return {
            "pilot_slot": self.pilot_slot,
            "answer_uri": self.answer_uri,
            "class_position": self.class_position,
            "class_uri": self.class_uri,
            "attempted": _b(self.attempted),
            "outcome": self.outcome,
            "retrieval_complete": _b(self.retrieval_complete),
            "mapped_candidate_count_excluding_answer": self.mapped_candidate_count,
            "graph_stage_mapping_gate": GRAPH_STAGE_MAPPING_GATE,
            "graph_stage_eligible": _b(self.graph_stage_eligible),
            "ordered_candidate_count": self.ordered_candidate_count,
            "graph_min_candidates": GRAPH_GATE_MIN_CANDIDATES,
            "accepted_candidate_count": self.accepted_candidate_count,
            "retained_node_count": self.retained_node_count,
            "retained_edge_count": self.retained_edge_count,
            "max_candidates": GRAPH_MAX_CANDIDATES,
            "max_nodes": GRAPH_MAX_NODES,
            "candidate_cap_reached": _b(self.candidate_cap_reached),
            "node_budget_bound": _b(self.node_budget_bound),
            "rejected_would_exceed_max_nodes": self.rejected_would_exceed_max_nodes,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class GraphStageResult:
    """The graph-stage outcome for one Answer, plus every class it considered."""

    pilot_slot: int
    answer_uri: str
    display_label: str
    answer_local_index: Optional[int]
    mapping_stage_status: str
    graph_stage_status: str
    selected_class_position: Optional[str]
    selected_class_uri: Optional[str]
    attempts: tuple[ClassGraphAttempt, ...]
    m1_graph: Optional[M1Graph]
    order: Optional[GraphAdmissionOrder]
    scope: str = SCOPE_PRIMARY

    @property
    def is_graph_feasible(self) -> bool:
        return self.graph_stage_status != NO_GRAPH_FEASIBLE_APPROVED_CLASS


@dataclass(frozen=True)
class ScoredCandidate:
    """One ranked candidate with its tie group and provenance."""

    rank: int
    canonical_uri: str
    local_index: int
    score: float
    tie_group_id: int
    tie_group_size: int
    at_beta_floor: bool
    mapping_origin: str
    admission_position: int


def _b(value: bool) -> str:
    """CSV boolean spelling, matched to the Week-1 outputs ('true'/'false')."""
    return "true" if value else "false"


def _count_rejections(m1_graph: M1Graph, reason: str) -> int:
    return sum(1 for r in m1_graph.budget.candidate_records
               if r.rejection_reason == reason)


def attempt_class_graph(
    facts: ClassMappingFacts,
    local_kg,
    *,
    max_candidates: int = GRAPH_MAX_CANDIDATES,
    max_nodes: int = GRAPH_MAX_NODES,
    min_candidates: int = GRAPH_GATE_MIN_CANDIDATES,
) -> tuple[ClassGraphAttempt, Optional[M1Graph], Optional[GraphAdmissionOrder]]:
    """Try to build a usable M1 graph for exactly one (Answer, class) pair.

    Applies the graph-stage eligibility test first, then the deterministic seeded
    graph-admission order, then the unmodified M1 graph builder. Returns the
    attempt record even when nothing was built, so every considered class appears
    in the provenance.
    """
    if not facts.retrieval_complete:
        return (_skipped_attempt(facts, ATTEMPT_SKIPPED_RETRIEVAL_INCOMPLETE,
                                 "class member retrieval was incomplete, so the "
                                 "candidate set is not known to be the whole class"),
                None, None)
    if facts.mapped_candidate_count_excluding_answer < GRAPH_STAGE_MAPPING_GATE:
        return (_skipped_attempt(
            facts, ATTEMPT_SKIPPED_MAPPING_COUNT_BELOW_GATE,
            f"{facts.mapped_candidate_count_excluding_answer} mapped candidates "
            f"< graph-stage gate {GRAPH_STAGE_MAPPING_GATE}"), None, None)

    order = order_candidates_for_graph_admission(
        answer_uri=facts.answer_uri,
        class_uri=facts.class_uri,
        candidates=facts.accepted,
    )
    m1_graph = build_m1_graph(
        answer=facts.answer_local_index,
        ordered_candidates=order.ordered_local_indices,
        in_neighbor=local_kg.in_neighbor,
        out_neighbor=local_kg.out_neighbor,
        max_nodes=max_nodes,
        max_candidates=max_candidates,
        min_candidates=min_candidates,
    )
    feasible = m1_graph.status == GRAPH_BUDGET_OK
    graph = m1_graph.graph
    over_budget = _count_rejections(m1_graph, "WOULD_EXCEED_MAX_NODES")
    attempt = ClassGraphAttempt(
        pilot_slot=facts.pilot_slot,
        answer_uri=facts.answer_uri,
        class_position=facts.class_position,
        class_uri=facts.class_uri,
        attempted=True,
        outcome=(ATTEMPT_GRAPH_FEASIBLE if feasible
                 else ATTEMPT_GRAPH_BUDGET_INSUFFICIENT),
        retrieval_complete=facts.retrieval_complete,
        mapped_candidate_count=facts.mapped_candidate_count_excluding_answer,
        graph_stage_eligible=True,
        ordered_candidate_count=len(order),
        accepted_candidate_count=m1_graph.budget.accepted_count,
        retained_node_count=len(m1_graph.budget.nodes),
        retained_edge_count=0 if graph is None else graph.edge_count,
        candidate_cap_reached=m1_graph.budget.candidate_cap_reached,
        node_budget_bound=m1_graph.budget.node_budget_bound,
        rejected_would_exceed_max_nodes=over_budget,
        detail=(f"{m1_graph.budget.accepted_count} candidates retained with "
                f"complete one-hop coverage under {max_nodes} nodes"
                if feasible else
                f"only {m1_graph.budget.accepted_count} of {len(order)} ordered "
                f"candidates fitted completely; graph gate needs "
                f"{min_candidates}"),
    )
    return attempt, m1_graph, order


def _skipped_attempt(facts: ClassMappingFacts, outcome: str, detail: str,
                     graph_stage_eligible: Optional[bool] = None) -> ClassGraphAttempt:
    """A class that was not built, with its eligibility reported honestly.

    `graph_stage_eligible` is a property of the class's MAPPING facts, so it stays
    true for a class that would have been eligible but was never reached because an
    earlier approved class already succeeded. Forcing it to false there would
    conflate "ineligible" with "not reached" and undercount the eligible classes in
    graph_policy_summary.csv. Callers pass False explicitly only when eligibility is
    genuinely not the reason the class was skipped — the diagnostic, which never
    passed the mapping gate at all.
    """
    eligible = (facts.passes_graph_stage_mapping_gate
                if graph_stage_eligible is None else graph_stage_eligible)
    return ClassGraphAttempt(
        pilot_slot=facts.pilot_slot,
        answer_uri=facts.answer_uri,
        class_position=facts.class_position,
        class_uri=facts.class_uri,
        attempted=False,
        outcome=outcome,
        retrieval_complete=facts.retrieval_complete,
        mapped_candidate_count=facts.mapped_candidate_count_excluding_answer,
        graph_stage_eligible=eligible,
        ordered_candidate_count=0,
        accepted_candidate_count=0,
        retained_node_count=0,
        retained_edge_count=0,
        candidate_cap_reached=False,
        node_budget_bound=False,
        rejected_would_exceed_max_nodes=0,
        detail=detail,
    )


def select_graph_feasible_class(
    row: AnswerClassPolicy,
    inputs: FrozenMappingInputs,
    local_kg,
    *,
    max_candidates: int = GRAPH_MAX_CANDIDATES,
    max_nodes: int = GRAPH_MAX_NODES,
    min_candidates: int = GRAPH_GATE_MIN_CANDIDATES,
) -> GraphStageResult:
    """Walk one Answer's three approved classes IN POLICY ORDER at the graph stage.

    Stops at the first class that retains `min_candidates` candidates after graph
    budgeting. Classes after the selected one are recorded as NOT ATTEMPTED rather
    than omitted, so the provenance shows the whole approved list and why the walk
    stopped where it did.
    """
    slot = row.pilot_slot
    mapping_status = inputs.mapping_stage_status.get(slot, "")
    attempts: list[ClassGraphAttempt] = []
    chosen: Optional[tuple[str, str, M1Graph, GraphAdmissionOrder]] = None

    for position, class_uri in row.ordered_positions:
        facts = inputs.for_pair(slot, class_uri)
        if facts.class_position != position:
            raise MappingInputError(
                f"approved class order disagreement for slot {slot}: policy says "
                f"{class_uri!r} is {position!r} but the frozen mapping output "
                f"recorded it as {facts.class_position!r}")
        if chosen is not None:
            attempts.append(_skipped_attempt(
                facts, ATTEMPT_NOT_ATTEMPTED_EARLIER_CLASS_SELECTED,
                f"an earlier approved class ({chosen[0]}) was already graph "
                f"feasible, so the walk stopped before this position"))
            continue
        attempt, m1_graph, order = attempt_class_graph(
            facts, local_kg, max_candidates=max_candidates,
            max_nodes=max_nodes, min_candidates=min_candidates)
        attempts.append(attempt)
        if attempt.outcome == ATTEMPT_GRAPH_FEASIBLE:
            assert m1_graph is not None and order is not None
            chosen = (position, class_uri, m1_graph, order)

    if chosen is None:
        return GraphStageResult(
            pilot_slot=slot,
            answer_uri=row.answer_uri,
            display_label=row.display_label,
            answer_local_index=inputs.answer_local_index.get(slot),
            mapping_stage_status=mapping_status,
            graph_stage_status=NO_GRAPH_FEASIBLE_APPROVED_CLASS,
            selected_class_position=None,
            selected_class_uri=None,
            attempts=tuple(attempts),
            m1_graph=None,
            order=None,
        )

    position, class_uri, m1_graph, order = chosen
    return GraphStageResult(
        pilot_slot=slot,
        answer_uri=row.answer_uri,
        display_label=row.display_label,
        answer_local_index=inputs.answer_local_index.get(slot),
        mapping_stage_status=mapping_status,
        graph_stage_status=_GRAPH_STATUS_FOR_POSITION[position],
        selected_class_position=position,
        selected_class_uri=class_uri,
        attempts=tuple(attempts),
        m1_graph=m1_graph,
        order=order,
    )


def assign_tie_groups(scored: Sequence[tuple[float, str]]) -> list[tuple[int, int]]:
    """(tie_group_id, tie_group_size) per position, for an already sorted list.

    Ties are the normal case here, not an edge case: every candidate sharing no
    equivalence class with the Answer lands exactly on the beta floor. Publishing
    the group makes "rank 2 vs rank 3" readable as "same score, URI tiebreak"
    instead of an apparent difference in structural plausibility.
    """
    groups: list[tuple[int, int]] = []
    group_id = 0
    position = 0
    while position < len(scored):
        end = position + 1
        while end < len(scored) and scored[end][0] == scored[position][0]:
            end += 1
        group_id += 1
        size = end - position
        groups.extend([(group_id, size)] * size)
        position = end
    return groups


def rank_graph(
    result: GraphStageResult,
    local_kg,
    cache: ScoreCache,
    source_hashes: SourceHashes,
    *,
    mode: str = MODE_RUN,
    max_candidates: int = GRAPH_MAX_CANDIDATES,
    max_nodes: int = GRAPH_MAX_NODES,
) -> tuple[tuple[ScoredCandidate, ...], RunFingerprint, dict]:
    """Rank one feasible graph's accepted candidates with fixed-k=3 L_ed.

    Only the candidates the graph builder RETAINED are ranked. Context nodes — the
    neighbourhood nodes that entered the graph to give the candidates their
    complete structure — are never offered to the ranker, so they cannot appear as
    distractor candidates.
    """
    if result.m1_graph is None or result.order is None:
        raise PipelineError(
            f"slot {result.pilot_slot}: cannot rank a graph-infeasible Answer")
    graph = result.m1_graph.graph
    assert graph is not None

    accepted_indices = result.m1_graph.accepted_candidates
    index_to_uri = result.order.index_to_uri()
    position_of = {c.local_index: c.admission_position for c in result.order.ordered}
    origin_of = {c.local_index: c.mapping_origin for c in result.order.ordered}

    unknown = [i for i in accepted_indices if i not in index_to_uri]
    if unknown:
        raise PipelineError(
            f"slot {result.pilot_slot}: the graph builder accepted node(s) "
            f"{unknown} that were never offered as candidates")

    # The whole ordering rests on "the canonical candidate URI IS the local node's
    # own URI". That is checked against the pinned KG rather than assumed, because a
    # redirect whose target was recorded wrongly would silently key the admission
    # order on an alias that is not the node being scored.
    mismatched = [
        (i, index_to_uri[i], _bare_uri(local_kg.uri_for_index(i)))
        for i in accepted_indices
        if _bare_uri(local_kg.uri_for_index(i)) != index_to_uri[i]
    ]
    if mismatched:
        raise PipelineError(
            f"slot {result.pilot_slot}: canonical candidate URI disagrees with the "
            f"pinned local KG for (index, canonical, kg) {mismatched[:3]}")

    config = lrolesim_adapter.pilot_config()
    fingerprint = build_run_fingerprint(
        local_kg_sha256=local_kg.source_sha256,
        answer_uri=result.answer_uri,
        class_uri=result.selected_class_uri or "",
        ordered_accepted_candidate_uris=[index_to_uri[i] for i in accepted_indices],
        retained_node_uris=[_bare_uri(local_kg.uri_for_index(n))
                            for n in graph.nodes],
        max_candidates=max_candidates,
        max_nodes=max_nodes,
        measure=config.measure,
        lrolesim_beta=config.lrolesim_beta,
        iterations=config.iterations,
        source_hashes=source_hashes,
    )

    cached = cache.get(fingerprint)
    if cached is not None:
        score_by_uri = {uri: float(score) for uri, score in cached["scores"]}
        missing = [index_to_uri[i] for i in accepted_indices
                   if index_to_uri[i] not in score_by_uri]
        if missing:
            raise PipelineError(
                f"slot {result.pilot_slot}: cache hit is missing scores for "
                f"{missing[:3]}")
        iterations_run = int(cached["iterations_run"])
        provenance = {"score_source": "cache",
                      "iterations_run": iterations_run,
                      "wall_seconds": 0.0}
    else:
        if mode == MODE_REPLAY:
            raise CacheMissInReplayError(
                f"replay mode requires a cached LRoleSim result for slot "
                f"{result.pilot_slot} ({result.answer_uri}); run fingerprint "
                f"{fingerprint.run_fingerprint} is not in "
                f"{cache.path}. A replay must not recompute scores."
            )
        started = time.perf_counter()
        ranking = lrolesim_adapter.rank_m1_graph(
            result.m1_graph,
            config=config,
            index_url={i: index_to_uri[i] for i in accepted_indices},
        )
        elapsed = time.perf_counter() - started
        if ranking.run.iterations_run != config.iterations:
            raise PipelineError(
                f"slot {result.pilot_slot}: expected {config.iterations} "
                f"iterations, adapter observed {ranking.run.iterations_run}")
        score_by_uri = {index_to_uri[s.candidate]: float(s.score)
                        for s in ranking.scores}
        iterations_run = ranking.run.iterations_run
        cache.put(fingerprint,
                  scores=sorted(score_by_uri.items()),
                  iterations_run=iterations_run,
                  node_count=len(graph.nodes))
        provenance = {"score_source": "computed",
                      "iterations_run": iterations_run,
                      "wall_seconds": elapsed}

    # Task item 6: descending score, then ascending canonical candidate URI. The
    # URI is the tiebreak because local-index order is an artefact of the pickle.
    ordered = sorted(
        ((score_by_uri[index_to_uri[i]], index_to_uri[i], i)
         for i in accepted_indices),
        key=lambda t: (-t[0], t[1]),
    )
    tie_groups = assign_tie_groups([(score, uri) for score, uri, _ in ordered])
    beta = float(config.lrolesim_beta)
    scored = tuple(
        ScoredCandidate(
            rank=rank,
            canonical_uri=uri,
            local_index=index,
            score=score,
            tie_group_id=tie_groups[rank - 1][0],
            tie_group_size=tie_groups[rank - 1][1],
            at_beta_floor=(score == beta),
            mapping_origin=origin_of[index],
            admission_position=position_of[index],
        )
        for rank, (score, uri, index) in enumerate(ordered, start=1)
    )
    return scored, fingerprint, provenance


def _bare_uri(uri: str) -> str:
    """Strip the pickle's `<...>` key spelling to get the plain URI."""
    if uri.startswith("<") and uri.endswith(">"):
        return uri[1:-1]
    return uri


# ==========================================================================
# 6) ORCHESTRATION
# ==========================================================================

@dataclass
class StageTiming:
    """Wall time and observed peak RSS for one named stage."""

    stage: str
    wall_seconds: float
    peak_rss_kb: int
    detail: str = ""

    def as_row(self) -> dict:
        return {
            "stage": self.stage,
            "wall_seconds": f"{self.wall_seconds:.3f}",
            "process_peak_rss_kb": self.peak_rss_kb,
            "process_peak_rss_mib": f"{self.peak_rss_kb / 1024.0:.1f}",
            "detail": self.detail,
        }


def _peak_rss_kb() -> int:
    """Process peak resident set size in kB (Linux ru_maxrss unit).

    Measured rather than estimated, and reported as PROCESS peak: the 1.2 GB
    pinned pickle dominates it, so a per-stage delta would be misleading.
    """
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


@dataclass
class PilotRun:
    """Everything one orchestration produced, ready to be written out."""

    mode: str
    primary: list[GraphStageResult] = field(default_factory=list)
    diagnostic: Optional[GraphStageResult] = None
    rankings: dict[int, tuple[ScoredCandidate, ...]] = field(default_factory=dict)
    fingerprints: dict[int, RunFingerprint] = field(default_factory=dict)
    ranking_provenance: dict[int, dict] = field(default_factory=dict)
    diagnostic_ranking: tuple[ScoredCandidate, ...] = ()
    diagnostic_fingerprint: Optional[RunFingerprint] = None
    diagnostic_provenance: dict = field(default_factory=dict)
    timings: list[StageTiming] = field(default_factory=list)
    entity_type_verdict: Optional[EntityTypeMapVerdict] = None
    l_edt_refusal_message: str = ""
    local_kg_record: dict = field(default_factory=dict)
    cache_record: dict = field(default_factory=dict)
    guard_record: dict = field(default_factory=dict)
    policy_record: dict = field(default_factory=dict)
    mapping_input_hashes: dict = field(default_factory=dict)
    frozen_zip_record: dict = field(default_factory=dict)
    source_hashes: dict = field(default_factory=dict)

    # `-1` is the diagnostic's slot key: it keeps diagnostic records out of every
    # dict keyed by a real pilot slot (1..9) without a parallel data structure.
    DIAGNOSTIC_SLOT = -1

    @property
    def graph_feasible_primary(self) -> list[GraphStageResult]:
        return [r for r in self.primary if r.is_graph_feasible]

    @property
    def primary_denominator(self) -> int:
        return len(self.primary)


def run_pilot(
    *,
    mode: str = MODE_RUN,
    local_kg_path: str | Path = PINNED_LOCAL_KG,
    local_kg_sha256: Optional[str] = PINNED_LOCAL_KG_SHA256,
    mapping_dir: str | Path = FROZEN_MAPPING_DIR,
    cache_path: str | Path = DEFAULT_SCORE_CACHE,
    policy_csv: str | Path = POLICY_CSV,
    policy_json: str | Path = POLICY_JSON,
    guard: Optional[OfflineGuard] = None,
    verbose: bool = True,
) -> PilotRun:
    """The whole Week-2 orchestration for the nine approved Answers.

    Order of business, deliberately fixed:
      1. install the offline guard, so any later network attempt fails the run;
      2. load and cross-check both approved-policy forms;
      3. read the frozen Week-1 mapping outputs;
      4. load the pinned local KG and record the L_edt refusal;
      5. walk each Answer's approved classes at the graph stage;
      6. rank every feasible graph with fixed-k=3 L_ed;
      7. run the Sulfuric-acid diagnostic separately, last, so it cannot influence
         any primary decision.
    """
    if mode not in (MODE_RUN, MODE_REPLAY):
        raise PipelineError(f"unknown mode {mode!r}; expected {MODE_RUN!r} or {MODE_REPLAY!r}")

    run = PilotRun(mode=mode)
    guard = guard or OfflineGuard()
    guard.install()

    def _say(message: str) -> None:
        if verbose:
            print(message, flush=True)

    try:
        # --- 2. approved policy ------------------------------------------
        t0 = time.perf_counter()
        csv_policy = load_policy_csv(policy_csv)
        json_policy = load_policy_json(policy_json)
        assert_policies_agree(csv_policy, json_policy)
        policy: PilotClassPolicy = csv_policy
        run.policy_record = {
            "answer_count": len(policy),
            "policy_csv_sha256": csv_policy.source_sha256,
            "policy_json_sha256": json_policy.source_sha256,
            "csv_and_json_agree": True,
        }
        run.timings.append(StageTiming(
            "load_approved_policy", time.perf_counter() - t0, _peak_rss_kb(),
            f"{len(policy)} approved Answers, CSV and JSON agree"))
        _say(f"[policy] {len(policy)} approved Answers; CSV and JSON agree")

        # --- 3. frozen mapping inputs ------------------------------------
        t0 = time.perf_counter()
        run.frozen_zip_record = verify_frozen_mapping_zip()
        inputs = load_frozen_mapping_inputs(mapping_dir)
        run.mapping_input_hashes = dict(inputs.source_hashes)
        run.timings.append(StageTiming(
            "load_frozen_mapping_outputs", time.perf_counter() - t0, _peak_rss_kb(),
            f"{len(inputs.facts)} (Answer, class) mapping records"))
        _say(f"[mapping] {len(inputs.facts)} frozen (Answer, class) records")

        # --- 4. pinned local KG ------------------------------------------
        t0 = time.perf_counter()
        local_kg = load_local_kg(local_kg_path, verify_sha256=local_kg_sha256)
        load_seconds = time.perf_counter() - t0
        run.local_kg_record = local_kg.as_record(REPO_ROOT)
        run.timings.append(StageTiming(
            "load_pinned_local_kg", load_seconds, _peak_rss_kb(),
            f"sha256 {local_kg.source_sha256[:16]}..., "
            f"{local_kg.uri_count} URIs, {local_kg.edge_count} edges"))
        _say(f"[kg] loaded in {load_seconds:.1f}s — {local_kg.uri_count} URIs, "
             f"{local_kg.edge_count} edges")

        # L_edt is refused here, once, against the map actually loaded.
        run.entity_type_verdict = inspect_entity_type_map(local_kg.index_type)
        try:
            assert_entity_type_map_usable(local_kg.index_type)
        except EntityTypeMapUnusableError as exc:
            run.l_edt_refusal_message = str(exc)
            _say(f"[ablation] {L_EDT_DEFERRED}")

        source_hashes = SourceHashes.collect()
        run.source_hashes = source_hashes.as_record()
        cache = ScoreCache(cache_path).load()

        # --- 5 + 6. graph stage and ranking, per Answer ------------------
        for row in policy:
            t0 = time.perf_counter()
            result = select_graph_feasible_class(row, inputs, local_kg)
            graph_seconds = time.perf_counter() - t0
            run.primary.append(result)
            run.timings.append(StageTiming(
                f"graph_stage_slot_{row.pilot_slot}", graph_seconds, _peak_rss_kb(),
                f"{row.display_label}: {result.graph_stage_status}"))

            if not result.is_graph_feasible:
                _say(f"[graph] slot {row.pilot_slot} {row.display_label}: "
                     f"{result.graph_stage_status}")
                continue

            t0 = time.perf_counter()
            scored, fingerprint, provenance = rank_graph(
                result, local_kg, cache, source_hashes, mode=mode)
            rank_seconds = time.perf_counter() - t0
            run.rankings[row.pilot_slot] = scored
            run.fingerprints[row.pilot_slot] = fingerprint
            run.ranking_provenance[row.pilot_slot] = provenance
            run.timings.append(StageTiming(
                f"lrolesim_slot_{row.pilot_slot}", rank_seconds, _peak_rss_kb(),
                f"{row.display_label}: {len(scored)} candidates ranked "
                f"({provenance['score_source']})"))
            assert result.m1_graph is not None and result.m1_graph.graph is not None
            _say(f"[rank]  slot {row.pilot_slot} {row.display_label}: "
                 f"{result.graph_stage_status} "
                 f"{len(scored)} candidates / "
                 f"{result.m1_graph.graph.node_count} nodes "
                 f"in {rank_seconds:.1f}s ({provenance['score_source']})")

        # --- 7. Sulfuric-acid engineering diagnostic ---------------------
        t0 = time.perf_counter()
        run.diagnostic = build_sulfuric_diagnostic(policy, inputs, local_kg)
        diag_graph_seconds = time.perf_counter() - t0
        run.timings.append(StageTiming(
            "diagnostic_graph_stage", diag_graph_seconds, _peak_rss_kb(),
            f"Sulfuric acid / Mineral acids: {run.diagnostic.graph_stage_status}"))
        if run.diagnostic.is_graph_feasible:
            t0 = time.perf_counter()
            scored, fingerprint, provenance = rank_graph(
                run.diagnostic, local_kg, cache, source_hashes, mode=mode)
            diag_rank_seconds = time.perf_counter() - t0
            run.diagnostic_ranking = scored
            run.diagnostic_fingerprint = fingerprint
            run.diagnostic_provenance = provenance
            run.timings.append(StageTiming(
                "diagnostic_lrolesim", diag_rank_seconds, _peak_rss_kb(),
                f"{len(scored)} diagnostic candidates ranked "
                f"({provenance['score_source']})"))
            _say(f"[diag]  Sulfuric acid diagnostic: {len(scored)} candidates "
                 f"ranked in {diag_rank_seconds:.1f}s")
        else:
            _say(f"[diag]  Sulfuric acid diagnostic: "
                 f"{run.diagnostic.graph_stage_status}")

        run.cache_record = cache.as_record()
    finally:
        run.guard_record = guard.as_record()
        guard.uninstall()

    return run


# --- The Sulfuric-acid diagnostic -----------------------------------------

DIAGNOSTIC_GRAPH_FEASIBLE = "DIAGNOSTIC_GRAPH_FEASIBLE"
DIAGNOSTIC_GRAPH_INSUFFICIENT = "DIAGNOSTIC_GRAPH_INSUFFICIENT_CANDIDATES"


def build_sulfuric_diagnostic(
    policy: PilotClassPolicy,
    inputs: FrozenMappingInputs,
    local_kg,
) -> GraphStageResult:
    """One explicitly separate engineering diagnostic. NOT a primary outcome.

    Sulfuric acid's primary mapping outcome stays NO_MAPPING_FEASIBLE_APPROVED_CLASS
    — nothing here lowers the mapping threshold, adds a class, replaces the Answer
    or converts it to a pass. The question this answers is narrow and technical:
    "given only six mapped candidates, would the graph and ranking machinery run at
    all?" Its statuses are separate tokens and every record it produces carries
    diagnostic_only = true.
    """
    row = policy.by_answer_uri(DIAGNOSTIC_ANSWER_URI)
    facts = inputs.for_pair(row.pilot_slot, DIAGNOSTIC_CLASS_URI)
    if facts.mapped_candidate_count_excluding_answer != DIAGNOSTIC_EXPECTED_MAPPED_COUNT:
        raise MappingInputError(
            f"the diagnostic expects {DIAGNOSTIC_EXPECTED_MAPPED_COUNT} mapped "
            f"candidates for {DIAGNOSTIC_CLASS_URI}, the frozen outputs report "
            f"{facts.mapped_candidate_count_excluding_answer}")
    mapping_status = inputs.mapping_stage_status.get(row.pilot_slot, "")
    if mapping_status != NO_MAPPING_FEASIBLE_APPROVED_CLASS:
        raise MappingInputError(
            f"the diagnostic requires Sulfuric acid's primary mapping outcome to "
            f"remain {NO_MAPPING_FEASIBLE_APPROVED_CLASS}, found {mapping_status!r}")

    order = order_candidates_for_graph_admission(
        answer_uri=facts.answer_uri,
        class_uri=facts.class_uri,
        candidates=facts.accepted,
    )
    m1_graph = build_m1_graph(
        answer=facts.answer_local_index,
        ordered_candidates=order.ordered_local_indices,
        in_neighbor=local_kg.in_neighbor,
        out_neighbor=local_kg.out_neighbor,
        max_nodes=GRAPH_MAX_NODES,
        max_candidates=GRAPH_MAX_CANDIDATES,
        # The ONLY relaxation, and it is a diagnostic threshold, not the pilot
        # gate: three candidates is the minimum that makes a ranking meaningful.
        min_candidates=DIAGNOSTIC_MIN_CANDIDATES,
    )
    feasible = m1_graph.status == GRAPH_BUDGET_OK
    graph = m1_graph.graph
    attempt = ClassGraphAttempt(
        pilot_slot=row.pilot_slot,
        answer_uri=facts.answer_uri,
        class_position=facts.class_position,
        class_uri=facts.class_uri,
        attempted=True,
        outcome=(ATTEMPT_GRAPH_FEASIBLE if feasible
                 else ATTEMPT_GRAPH_BUDGET_INSUFFICIENT),
        retrieval_complete=facts.retrieval_complete,
        mapped_candidate_count=facts.mapped_candidate_count_excluding_answer,
        graph_stage_eligible=False,      # it never passed the mapping gate
        ordered_candidate_count=len(order),
        accepted_candidate_count=m1_graph.budget.accepted_count,
        retained_node_count=len(m1_graph.budget.nodes),
        retained_edge_count=0 if graph is None else graph.edge_count,
        candidate_cap_reached=m1_graph.budget.candidate_cap_reached,
        node_budget_bound=m1_graph.budget.node_budget_bound,
        rejected_would_exceed_max_nodes=_count_rejections(
            m1_graph, "WOULD_EXCEED_MAX_NODES"),
        detail=(f"diagnostic only: {m1_graph.budget.accepted_count} of "
                f"{len(order)} candidates retained, diagnostic minimum "
                f"{DIAGNOSTIC_MIN_CANDIDATES}"),
    )
    return GraphStageResult(
        pilot_slot=row.pilot_slot,
        answer_uri=facts.answer_uri,
        display_label=row.display_label,
        answer_local_index=facts.answer_local_index,
        mapping_stage_status=mapping_status,
        graph_stage_status=(DIAGNOSTIC_GRAPH_FEASIBLE if feasible
                            else DIAGNOSTIC_GRAPH_INSUFFICIENT),
        selected_class_position=facts.class_position,
        selected_class_uri=facts.class_uri,
        attempts=(attempt,),
        m1_graph=m1_graph if feasible else None,
        order=order if feasible else None,
        scope=SCOPE_DIAGNOSTIC,
    )


# ==========================================================================
# 7) OUTPUT WRITERS
# ==========================================================================
#
# Every writer below is TIMESTAMP-FREE and deterministically ordered, because the
# offline replay has to reproduce these files byte-for-byte. Anything that varies
# between two runs of the same inputs (wall time, peak RSS, the run clock) lives in
# performance_summary.csv and run_manifest.json, which are explicitly excluded from
# the byte-identity check.

# The scientific outputs a replay must reproduce byte-for-byte.
REPLAY_COMPARED_FILES = (
    "graph_policy_summary.csv",
    "graph_class_attempts.csv",
    "graph_candidates.jsonl",
    "graph_manifests.jsonl",
    "lrolesim_scores.jsonl",
    "lrolesim_rankings.csv",
    "provisional_top3.csv",
    "sulfuric_acid_diagnostic.json",
)

PROVISIONAL_TOP3_LABEL = "provisional_lrolesim_top3"


def _fmt_score(score: float) -> str:
    """Shortest round-tripping decimal form of a float.

    `repr` guarantees eval(repr(x)) == x in Python 3, so a CSV score can be read
    back without loss and two runs of identical inputs emit identical bytes. A
    fixed number of decimals would silently truncate.
    """
    return repr(float(score))


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[dict]) -> None:
    """UTF-8, LF-only CSV. `newline=""` plus lineterminator pins the bytes."""
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


GRAPH_POLICY_SUMMARY_FIELDS = (
    "pilot_slot", "answer_uri", "display_label", "answer_local_index",
    "primary_or_diagnostic",
    "mapping_stage_status", "mapping_selected_class_uri",
    "graph_stage_status", "graph_selected_class_position", "graph_selected_class_uri",
    "graph_stage_eligible_class_count", "classes_attempted_count",
    "ordered_candidate_count", "accepted_candidate_count",
    "graph_node_count", "graph_edge_count", "graph_edge_label_count",
    "context_node_count", "min_neighborhood_coverage_ratio",
    "max_candidates", "max_nodes", "graph_min_candidates",
    "candidate_cap_reached", "node_budget_bound",
    "measure", "lrolesim_beta", "iterations", "iteration_mode",
    "ranked_candidate_count", "beta_floor_count", "tie_group_count",
    "top_score", "graph_fingerprint", "run_fingerprint",
    "l_edt_status",
)


def _coverage_min(m1_graph: Optional[M1Graph]) -> str:
    if m1_graph is None:
        return ""
    accepted = [r.neighborhood_coverage_ratio
                for r in m1_graph.budget.candidate_records if r.accepted]
    return repr(min(accepted)) if accepted else ""


def _summary_row(run: PilotRun, result: GraphStageResult,
                 mapping_selected: Optional[str]) -> dict:
    slot = result.pilot_slot
    is_diag = result.scope == SCOPE_DIAGNOSTIC
    scored = (run.diagnostic_ranking if is_diag else run.rankings.get(slot, ()))
    fingerprint = (run.diagnostic_fingerprint if is_diag
                   else run.fingerprints.get(slot))
    m1_graph = result.m1_graph
    graph = None if m1_graph is None else m1_graph.graph
    config = lrolesim_adapter.pilot_config()
    accepted = 0 if m1_graph is None else m1_graph.budget.accepted_count
    node_count = 0 if graph is None else graph.node_count
    # A context node is a node that entered the graph to complete a
    # neighbourhood: everything that is neither the Answer nor an accepted
    # candidate. Published so "candidates" and "graph nodes" can never be
    # conflated in a downstream reading.
    context = max(0, node_count - accepted - (1 if node_count else 0))
    return {
        "pilot_slot": slot,
        "answer_uri": result.answer_uri,
        "display_label": result.display_label,
        "answer_local_index": ("" if result.answer_local_index is None
                               else result.answer_local_index),
        "primary_or_diagnostic": result.scope,
        "mapping_stage_status": result.mapping_stage_status,
        "mapping_selected_class_uri": mapping_selected or "",
        "graph_stage_status": result.graph_stage_status,
        "graph_selected_class_position": result.selected_class_position or "",
        "graph_selected_class_uri": result.selected_class_uri or "",
        "graph_stage_eligible_class_count": sum(
            1 for a in result.attempts if a.graph_stage_eligible),
        "classes_attempted_count": sum(1 for a in result.attempts if a.attempted),
        "ordered_candidate_count": 0 if result.order is None else len(result.order),
        "accepted_candidate_count": accepted,
        "graph_node_count": node_count,
        "graph_edge_count": 0 if graph is None else graph.edge_count,
        "graph_edge_label_count": 0 if graph is None else graph.edge_label_count,
        "context_node_count": context,
        "min_neighborhood_coverage_ratio": _coverage_min(m1_graph),
        "max_candidates": GRAPH_MAX_CANDIDATES,
        "max_nodes": GRAPH_MAX_NODES,
        "graph_min_candidates": (DIAGNOSTIC_MIN_CANDIDATES if is_diag
                                 else GRAPH_GATE_MIN_CANDIDATES),
        "candidate_cap_reached": _b(
            False if m1_graph is None else m1_graph.budget.candidate_cap_reached),
        "node_budget_bound": _b(
            False if m1_graph is None else m1_graph.budget.node_budget_bound),
        "measure": config.measure if scored else "",
        "lrolesim_beta": repr(float(config.lrolesim_beta)) if scored else "",
        "iterations": config.iterations if scored else "",
        "iteration_mode": "fixed" if scored else "",
        "ranked_candidate_count": len(scored),
        "beta_floor_count": sum(1 for s in scored if s.at_beta_floor),
        "tie_group_count": (max((s.tie_group_id for s in scored), default=0)),
        "top_score": _fmt_score(scored[0].score) if scored else "",
        "graph_fingerprint": "" if fingerprint is None else fingerprint.graph_fingerprint,
        "run_fingerprint": "" if fingerprint is None else fingerprint.run_fingerprint,
        "l_edt_status": (run.entity_type_verdict.status
                         if run.entity_type_verdict else ""),
    }


def write_graph_policy_summary(run: PilotRun, out_dir: Path,
                              selected_mapping: Mapping[int, Optional[str]]) -> None:
    """Exactly nine primary Answer rows, in pilot-slot order. No diagnostic row.

    The diagnostic is deliberately absent from this file: it has its own
    sulfuric_acid_diagnostic.json, and a tenth row here would contaminate the
    nine-Answer denominator that every yield figure is computed against.
    """
    rows = [_summary_row(run, r, selected_mapping.get(r.pilot_slot))
            for r in sorted(run.primary, key=lambda r: r.pilot_slot)]
    if len(rows) != 9:
        raise PipelineError(
            f"graph_policy_summary.csv must have exactly nine primary rows, "
            f"built {len(rows)}")
    _write_csv(out_dir / "graph_policy_summary.csv",
               GRAPH_POLICY_SUMMARY_FIELDS, rows)


GRAPH_CLASS_ATTEMPT_FIELDS = (
    "pilot_slot", "answer_uri", "primary_or_diagnostic", "class_position",
    "class_uri", "attempted", "outcome", "retrieval_complete",
    "mapped_candidate_count_excluding_answer", "graph_stage_mapping_gate",
    "graph_stage_eligible", "ordered_candidate_count", "graph_min_candidates",
    "accepted_candidate_count", "retained_node_count", "retained_edge_count",
    "max_candidates", "max_nodes", "candidate_cap_reached", "node_budget_bound",
    "rejected_would_exceed_max_nodes", "diagnostic_only",
    "excluded_from_primary_policy_metrics", "detail",
)


def write_graph_class_attempts(run: PilotRun, out_dir: Path) -> None:
    """Every approved class considered, primary and diagnostic, with its verdict."""
    rows: list[dict] = []
    for result in sorted(run.primary, key=lambda r: r.pilot_slot):
        for attempt in result.attempts:
            row = attempt.as_row()
            row.update({"primary_or_diagnostic": SCOPE_PRIMARY,
                        "diagnostic_only": _b(False),
                        "excluded_from_primary_policy_metrics": _b(False)})
            rows.append(row)
    if run.diagnostic is not None:
        for attempt in run.diagnostic.attempts:
            row = attempt.as_row()
            row.update({"primary_or_diagnostic": SCOPE_DIAGNOSTIC,
                        "diagnostic_only": _b(True),
                        "excluded_from_primary_policy_metrics": _b(True),
                        "graph_min_candidates": DIAGNOSTIC_MIN_CANDIDATES})
            rows.append(row)
    _write_csv(out_dir / "graph_class_attempts.csv",
               GRAPH_CLASS_ATTEMPT_FIELDS, rows)


def _candidate_records(run: PilotRun, result: GraphStageResult) -> list[dict]:
    if result.m1_graph is None or result.order is None:
        return []
    is_diag = result.scope == SCOPE_DIAGNOSTIC
    order_by_index = {c.local_index: c for c in result.order.ordered}
    scored = (run.diagnostic_ranking if is_diag else run.rankings.get(result.pilot_slot, ()))
    rank_by_index = {s.local_index: s for s in scored}
    fingerprint = (run.diagnostic_fingerprint if is_diag
                   else run.fingerprints.get(result.pilot_slot))
    records: list[dict] = []
    for record in result.m1_graph.budget.candidate_records:
        ordered = order_by_index.get(record.candidate)
        ranked = rank_by_index.get(record.candidate)
        records.append({
            "pilot_slot": result.pilot_slot,
            "answer_uri": result.answer_uri,
            "class_uri": result.selected_class_uri,
            "primary_or_diagnostic": result.scope,
            "diagnostic_only": is_diag,
            "excluded_from_primary_policy_metrics": is_diag,
            "candidate_local_index": record.candidate,
            "canonical_candidate_uri": (
                None if ordered is None else ordered.canonical_uri),
            "candidate_origin": None if ordered is None else ordered.mapping_origin,
            "retrieved_member_uri": None if ordered is None else ordered.retrieved_uri,
            "graph_admission_position": (
                None if ordered is None else ordered.admission_position),
            "graph_admission_order_digest": (
                None if ordered is None else ordered.order_digest),
            "accepted_into_graph": record.accepted,
            "rejection_reason": record.rejection_reason,
            "is_ranked_candidate": ranked is not None,
            "is_context_node_only": False,
            "full_out_degree": record.full_out_degree,
            "full_in_degree": record.full_in_degree,
            "retained_out_degree": record.retained_out_degree,
            "retained_in_degree": record.retained_in_degree,
            "distinct_neighbor_count": record.distinct_neighbor_count,
            "retained_neighbor_count": record.retained_neighbor_count,
            "neighborhood_coverage_ratio": record.neighborhood_coverage_ratio,
            "lrolesim_score": None if ranked is None else ranked.score,
            "lrolesim_rank": None if ranked is None else ranked.rank,
            "graph_fingerprint": (
                None if fingerprint is None else fingerprint.graph_fingerprint),
        })
    records.sort(key=lambda r: (r["pilot_slot"], r["graph_admission_position"] or 0,
                                r["candidate_local_index"]))
    return records


def write_graph_candidates(run: PilotRun, out_dir: Path) -> None:
    """Every candidate OFFERED to each selected graph, accepted or rejected."""
    records: list[dict] = []
    for result in sorted(run.primary, key=lambda r: r.pilot_slot):
        records.extend(_candidate_records(run, result))
    if run.diagnostic is not None:
        records.extend(_candidate_records(run, run.diagnostic))
    _write_jsonl(out_dir / "graph_candidates.jsonl", records)


def write_graph_manifests(run: PilotRun, out_dir: Path) -> None:
    """One manifest per built graph: structure, fingerprint and admission order."""
    records: list[dict] = []
    results = list(sorted(run.primary, key=lambda r: r.pilot_slot))
    if run.diagnostic is not None:
        results.append(run.diagnostic)
    for result in results:
        if result.m1_graph is None or result.order is None:
            continue
        is_diag = result.scope == SCOPE_DIAGNOSTIC
        fingerprint = (run.diagnostic_fingerprint if is_diag
                       else run.fingerprints.get(result.pilot_slot))
        graph = result.m1_graph.graph
        assert graph is not None
        accepted = result.m1_graph.accepted_candidates
        index_to_uri = result.order.index_to_uri()
        records.append({
            "pilot_slot": result.pilot_slot,
            "answer_uri": result.answer_uri,
            "class_uri": result.selected_class_uri,
            "class_position": result.selected_class_position,
            "primary_or_diagnostic": result.scope,
            "diagnostic_only": is_diag,
            "excluded_from_primary_policy_metrics": is_diag,
            "graph_stage_status": result.graph_stage_status,
            "answer_local_index": result.answer_local_index,
            "graph_admission_order_name": GRAPH_ADMISSION_ORDER_NAME,
            "graph_admission_order_domain": result.order.domain,
            "ordered_candidate_count": len(result.order),
            "ordered_candidate_uris": list(result.order.ordered_canonical_uris),
            "accepted_candidate_count": len(accepted),
            "accepted_candidate_uris": [index_to_uri[i] for i in accepted],
            "accepted_candidate_local_indices": list(accepted),
            "node_count": graph.node_count,
            "edge_count": graph.edge_count,
            "distinct_edge_count": graph.distinct_edge_count,
            "edge_label_count": graph.edge_label_count,
            "context_node_count": graph.node_count - len(accepted) - 1,
            "max_candidates": GRAPH_MAX_CANDIDATES,
            "max_nodes": GRAPH_MAX_NODES,
            "min_candidates": (DIAGNOSTIC_MIN_CANDIDATES if is_diag
                               else GRAPH_GATE_MIN_CANDIDATES),
            "candidate_cap_reached": result.m1_graph.budget.candidate_cap_reached,
            "node_budget_bound": result.m1_graph.budget.node_budget_bound,
            "all_accepted_coverage_is_one": all(
                r.neighborhood_coverage_ratio == 1.0
                for r in result.m1_graph.budget.candidate_records if r.accepted),
            "graph_fingerprint": (
                None if fingerprint is None else fingerprint.graph_fingerprint),
            "run_fingerprint": (
                None if fingerprint is None else fingerprint.run_fingerprint),
            "fingerprint_fields": (
                None if fingerprint is None
                else json.loads(_canonical_json(fingerprint.payload))),
        })
    _write_jsonl(out_dir / "graph_manifests.jsonl", records)


def _score_records(run: PilotRun, result: GraphStageResult) -> list[dict]:
    is_diag = result.scope == SCOPE_DIAGNOSTIC
    scored = (run.diagnostic_ranking if is_diag
              else run.rankings.get(result.pilot_slot, ()))
    if not scored:
        return []
    fingerprint = (run.diagnostic_fingerprint if is_diag
                   else run.fingerprints.get(result.pilot_slot))
    config = lrolesim_adapter.pilot_config()
    return [{
        "answer_uri": result.answer_uri,
        "pilot_slot": result.pilot_slot,
        "selected_class_uri": result.selected_class_uri,
        "selected_class_position": result.selected_class_position,
        "graph_stage_status": result.graph_stage_status,
        "candidate_uri": s.canonical_uri,
        "candidate_local_index": s.local_index,
        "lrolesim_score": s.score,
        "rank": s.rank,
        "tie_group_id": s.tie_group_id,
        "tie_group_size": s.tie_group_size,
        "at_beta_floor": s.at_beta_floor,
        "graph_fingerprint": (
            None if fingerprint is None else fingerprint.graph_fingerprint),
        "run_fingerprint": (
            None if fingerprint is None else fingerprint.run_fingerprint),
        "measure": config.measure,
        "lrolesim_beta": float(config.lrolesim_beta),
        "iterations": config.iterations,
        "iteration_mode": "fixed",
        "candidate_origin": s.mapping_origin,
        "graph_admission_position": s.admission_position,
        "primary_or_diagnostic": result.scope,
        "diagnostic_only": is_diag,
        "excluded_from_primary_policy_metrics": is_diag,
        "l_edt_status": (run.entity_type_verdict.status
                         if run.entity_type_verdict else None),
    } for s in scored]


def write_lrolesim_scores(run: PilotRun, out_dir: Path) -> None:
    """The full per-candidate score record required by task item 6."""
    records: list[dict] = []
    for result in sorted(run.primary, key=lambda r: r.pilot_slot):
        records.extend(_score_records(run, result))
    if run.diagnostic is not None:
        records.extend(_score_records(run, run.diagnostic))
    _write_jsonl(out_dir / "lrolesim_scores.jsonl", records)


LROLESIM_RANKING_FIELDS = (
    "primary_or_diagnostic", "diagnostic_only",
    "excluded_from_primary_policy_metrics",
    "pilot_slot", "answer_uri", "selected_class_position", "selected_class_uri",
    "rank", "candidate_uri", "candidate_local_index", "lrolesim_score",
    "tie_group_id", "tie_group_size", "at_beta_floor", "candidate_origin",
    "graph_admission_position", "measure", "lrolesim_beta", "iterations",
    "iteration_mode", "graph_fingerprint", "run_fingerprint", "l_edt_status",
)


def write_lrolesim_rankings(run: PilotRun, out_dir: Path) -> None:
    """Flat ranking table. Primary and diagnostic rows are explicitly labelled."""
    rows: list[dict] = []
    for record in _all_score_records(run):
        rows.append({
            "primary_or_diagnostic": record["primary_or_diagnostic"],
            "diagnostic_only": _b(record["diagnostic_only"]),
            "excluded_from_primary_policy_metrics": _b(
                record["excluded_from_primary_policy_metrics"]),
            "pilot_slot": record["pilot_slot"],
            "answer_uri": record["answer_uri"],
            "selected_class_position": record["selected_class_position"],
            "selected_class_uri": record["selected_class_uri"],
            "rank": record["rank"],
            "candidate_uri": record["candidate_uri"],
            "candidate_local_index": record["candidate_local_index"],
            "lrolesim_score": _fmt_score(record["lrolesim_score"]),
            "tie_group_id": record["tie_group_id"],
            "tie_group_size": record["tie_group_size"],
            "at_beta_floor": _b(record["at_beta_floor"]),
            "candidate_origin": record["candidate_origin"],
            "graph_admission_position": record["graph_admission_position"],
            "measure": record["measure"],
            "lrolesim_beta": repr(record["lrolesim_beta"]),
            "iterations": record["iterations"],
            "iteration_mode": record["iteration_mode"],
            "graph_fingerprint": record["graph_fingerprint"],
            "run_fingerprint": record["run_fingerprint"],
            "l_edt_status": record["l_edt_status"],
        })
    _write_csv(out_dir / "lrolesim_rankings.csv", LROLESIM_RANKING_FIELDS, rows)


def _all_score_records(run: PilotRun) -> list[dict]:
    records: list[dict] = []
    for result in sorted(run.primary, key=lambda r: r.pilot_slot):
        records.extend(_score_records(run, result))
    if run.diagnostic is not None:
        records.extend(_score_records(run, run.diagnostic))
    return records


PROVISIONAL_TOP3_FIELDS = (
    "primary_or_diagnostic", "diagnostic_only",
    "excluded_from_primary_policy_metrics",
    "pilot_slot", "answer_uri", "display_label", "selected_class_uri",
    "result_label", "rank", "candidate_uri", "candidate_local_index",
    "lrolesim_score", "tie_group_id", "tie_group_size", "at_beta_floor",
    "is_final_distractor", "not_final_reason",
    "measure", "lrolesim_beta", "iterations", "graph_fingerprint",
)

NOT_FINAL_REASON = (
    "rationale feasibility has not been applied yet; these are structural "
    "plausibility ranks only"
)


def write_provisional_top3(run: PilotRun, out_dir: Path) -> None:
    """The top three per graph, labelled `provisional_lrolesim_top3`.

    They are NOT the final distractors. Rationale feasibility has not been
    computed, so a candidate here can still be discarded later; the file says so on
    every row rather than in a footnote.
    """
    rows: list[dict] = []
    results = list(sorted(run.primary, key=lambda r: r.pilot_slot))
    if run.diagnostic is not None:
        results.append(run.diagnostic)
    for result in results:
        is_diag = result.scope == SCOPE_DIAGNOSTIC
        scored = (run.diagnostic_ranking if is_diag
                  else run.rankings.get(result.pilot_slot, ()))
        fingerprint = (run.diagnostic_fingerprint if is_diag
                       else run.fingerprints.get(result.pilot_slot))
        config = lrolesim_adapter.pilot_config()
        for s in scored[:3]:
            rows.append({
                "primary_or_diagnostic": result.scope,
                "diagnostic_only": _b(is_diag),
                "excluded_from_primary_policy_metrics": _b(is_diag),
                "pilot_slot": result.pilot_slot,
                "answer_uri": result.answer_uri,
                "display_label": result.display_label,
                "selected_class_uri": result.selected_class_uri or "",
                "result_label": PROVISIONAL_TOP3_LABEL,
                "rank": s.rank,
                "candidate_uri": s.canonical_uri,
                "candidate_local_index": s.local_index,
                "lrolesim_score": _fmt_score(s.score),
                "tie_group_id": s.tie_group_id,
                "tie_group_size": s.tie_group_size,
                "at_beta_floor": _b(s.at_beta_floor),
                "is_final_distractor": _b(False),
                "not_final_reason": NOT_FINAL_REASON,
                "measure": config.measure,
                "lrolesim_beta": repr(float(config.lrolesim_beta)),
                "iterations": config.iterations,
                "graph_fingerprint": ("" if fingerprint is None
                                      else fingerprint.graph_fingerprint),
            })
    _write_csv(out_dir / "provisional_top3.csv", PROVISIONAL_TOP3_FIELDS, rows)


def write_sulfuric_acid_diagnostic(run: PilotRun, out_dir: Path) -> None:
    """The diagnostic, in its own file, with its boundaries stated in the data."""
    result = run.diagnostic
    if result is None:
        raise PipelineError("the Sulfuric-acid diagnostic was not attempted")
    graph = None if result.m1_graph is None else result.m1_graph.graph
    fingerprint = run.diagnostic_fingerprint
    config = lrolesim_adapter.pilot_config()
    payload = {
        "diagnostic_only": True,
        "excluded_from_primary_policy_metrics": True,
        "answer_uri": result.answer_uri,
        "pilot_slot": result.pilot_slot,
        "diagnostic_class_uri": result.selected_class_uri,
        "diagnostic_class_position": result.selected_class_position,
        "mapped_candidate_count": DIAGNOSTIC_EXPECTED_MAPPED_COUNT,
        "diagnostic_min_candidates": DIAGNOSTIC_MIN_CANDIDATES,
        "primary_mapping_stage_status_preserved": result.mapping_stage_status,
        "primary_mapping_stage_status_expected": NO_MAPPING_FEASIBLE_APPROVED_CLASS,
        "primary_outcome_unchanged": (
            result.mapping_stage_status == NO_MAPPING_FEASIBLE_APPROVED_CLASS),
        "diagnostic_graph_status": result.graph_stage_status,
        "boundaries": {
            "selected_mapping_class_csv_modified": False,
            "mapping_stage_statuses_modified": False,
            "counted_in_primary_graph_stage_yield": False,
            "counted_in_nine_answer_denominator": False,
            "global_mapping_threshold_lowered": False,
            "new_class_added": False,
            "answer_replaced": False,
            "marked_as_primary_pass": False,
        },
        "graph": None if graph is None else {
            "node_count": graph.node_count,
            "edge_count": graph.edge_count,
            "distinct_edge_count": graph.distinct_edge_count,
            "edge_label_count": graph.edge_label_count,
            "accepted_candidate_count": result.m1_graph.budget.accepted_count,
            "context_node_count": (
                graph.node_count - result.m1_graph.budget.accepted_count - 1),
            "all_accepted_coverage_is_one": all(
                r.neighborhood_coverage_ratio == 1.0
                for r in result.m1_graph.budget.candidate_records if r.accepted),
        },
        "graph_admission_order": (
            None if result.order is None else result.order.as_record()),
        "lrolesim": None if not run.diagnostic_ranking else {
            "measure": config.measure,
            "lrolesim_beta": float(config.lrolesim_beta),
            "iterations": config.iterations,
            "iteration_mode": "fixed",
            "ranked_candidate_count": len(run.diagnostic_ranking),
            "beta_floor_count": sum(1 for s in run.diagnostic_ranking
                                    if s.at_beta_floor),
            "graph_fingerprint": (None if fingerprint is None
                                  else fingerprint.graph_fingerprint),
            "run_fingerprint": (None if fingerprint is None
                                else fingerprint.run_fingerprint),
            "ranking": [{
                "rank": s.rank,
                "candidate_uri": s.canonical_uri,
                "candidate_local_index": s.local_index,
                "lrolesim_score": s.score,
                "tie_group_id": s.tie_group_id,
                "tie_group_size": s.tie_group_size,
                "at_beta_floor": s.at_beta_floor,
                "candidate_origin": s.mapping_origin,
            } for s in run.diagnostic_ranking],
            "provisional_lrolesim_top3": [
                s.canonical_uri for s in run.diagnostic_ranking[:3]],
        },
        "l_edt_status": (run.entity_type_verdict.status
                         if run.entity_type_verdict else None),
    }
    _write_json(out_dir / "sulfuric_acid_diagnostic.json", payload)


PERFORMANCE_FIELDS = ("stage", "wall_seconds", "process_peak_rss_kb",
                      "process_peak_rss_mib", "detail")


def write_performance_summary(run: PilotRun, out_dir: Path) -> None:
    """Timing and peak RSS. Excluded from the byte-identity check by design."""
    _write_csv(out_dir / "performance_summary.csv", PERFORMANCE_FIELDS,
               [t.as_row() for t in run.timings])


def write_offline_replay_manifest(run: PilotRun, out_dir: Path) -> None:
    """What a replay must reproduce, and the proof that nothing went out to a network."""
    compared = {}
    for name in REPLAY_COMPARED_FILES:
        path = out_dir / name
        compared[name] = {
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    payload = {
        "mode": run.mode,
        "replay_command": (
            "python -m pipeline.graph_lrolesim_run --mode replay "
            "--output-dir <fresh directory>"),
        "byte_identical_files": list(REPLAY_COMPARED_FILES),
        "excluded_from_byte_identity": [
            "performance_summary.csv (wall time and peak RSS vary by run)",
            "run_manifest.json (records the run clock and the git state)",
            "offline_replay_manifest.json (contains the hashes it verifies)",
        ],
        "file_hashes": compared,
        "network": run.guard_record,
        "http_calls": 0,
        "sparql_calls": 0,
        "score_cache": run.cache_record,
        "pinned_local_kg": run.local_kg_record,
        "frozen_mapping_zip": run.frozen_zip_record,
        "frozen_mapping_input_sha256": run.mapping_input_hashes,
        "fingerprinted_source_sha256": run.source_hashes,
        "l_edt": (None if run.entity_type_verdict is None
                  else run.entity_type_verdict.as_record()),
    }
    _write_json(out_dir / "offline_replay_manifest.json", payload)


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


def write_run_manifest(run: PilotRun, out_dir: Path,
                       raw_command: Sequence[str]) -> None:
    """Full run provenance. Not part of the byte-identity check."""
    primary_feasible = run.graph_feasible_primary
    payload = {
        "task": "Prompt 8C — real M1 pilot graphs and fixed-iteration LRoleSim",
        "mode": run.mode,
        "raw_command": list(raw_command),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "conda_env": os.environ.get("CONDA_DEFAULT_ENV", ""),
        "git": _git_state(),
        "approved_policy": run.policy_record,
        "pinned_local_kg": run.local_kg_record,
        "pinned_local_kg_expected_sha256": PINNED_LOCAL_KG_SHA256,
        "frozen_mapping_zip": run.frozen_zip_record,
        "frozen_mapping_zip_expected_sha256": FROZEN_MAPPING_ZIP_SHA256,
        "frozen_mapping_input_sha256": run.mapping_input_hashes,
        "fingerprinted_source_sha256": run.source_hashes,
        "graph_budget": {
            "max_candidates": GRAPH_MAX_CANDIDATES,
            "max_nodes": GRAPH_MAX_NODES,
            "graph_stage_mapping_gate": GRAPH_STAGE_MAPPING_GATE,
            "graph_gate_min_candidates": GRAPH_GATE_MIN_CANDIDATES,
        },
        "graph_admission_order": {
            "name": GRAPH_ADMISSION_ORDER_NAME,
            "domain": GRAPH_ADMISSION_ORDER_DOMAIN,
            "is_ranking": False,
            "is_random": False,
        },
        "lrolesim": lrolesim_adapter.pilot_config().as_record(),
        "l_edt": (None if run.entity_type_verdict is None
                  else run.entity_type_verdict.as_record()),
        "l_edt_refusal_message": run.l_edt_refusal_message,
        "counts": {
            "primary_answer_denominator": run.primary_denominator,
            "primary_graph_feasible": len(primary_feasible),
            "primary_graph_infeasible": (
                run.primary_denominator - len(primary_feasible)),
            "primary_ranked_candidate_total": sum(
                len(v) for v in run.rankings.values()),
            "diagnostic_ranked_candidate_total": len(run.diagnostic_ranking),
        },
        "graph_stage_status_by_slot": {
            str(r.pilot_slot): r.graph_stage_status
            for r in sorted(run.primary, key=lambda r: r.pilot_slot)},
        "network": run.guard_record,
        "score_cache": run.cache_record,
        "stage_timings": [t.as_row() for t in run.timings],
        "scope_note": (
            "Stops after graph construction and LRoleSim ranking. No final "
            "rationale-constrained distractor triples, no extract-file patch, no "
            "MCQ verbalization."),
    }
    _write_json(out_dir / "run_manifest.json", payload)


def write_all_outputs(run: PilotRun, out_dir: str | Path,
                      selected_mapping: Mapping[int, Optional[str]],
                      raw_command: Sequence[str] = ()) -> Path:
    """Write every required output into `out_dir`, creating it if needed."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_graph_policy_summary(run, out_dir, selected_mapping)
    write_graph_class_attempts(run, out_dir)
    write_graph_candidates(run, out_dir)
    write_graph_manifests(run, out_dir)
    write_lrolesim_scores(run, out_dir)
    write_lrolesim_rankings(run, out_dir)
    write_provisional_top3(run, out_dir)
    write_sulfuric_acid_diagnostic(run, out_dir)
    write_performance_summary(run, out_dir)
    write_offline_replay_manifest(run, out_dir)
    write_run_manifest(run, out_dir, raw_command)
    return out_dir


# ==========================================================================
# 8) CLI
# ==========================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.graph_lrolesim_run",
        description=("Build the real M1 pilot graphs and run fixed-iteration "
                     "LRoleSim L_ed rankings. Offline only."),
    )
    parser.add_argument("--mode", choices=(MODE_RUN, MODE_REPLAY), default=MODE_RUN,
                        help=("run: compute missing scores and cache them. "
                              "replay: refuse to compute, require a cache hit for "
                              "every graph."))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--local-kg", default=str(PINNED_LOCAL_KG))
    parser.add_argument("--mapping-dir", default=str(FROZEN_MAPPING_DIR))
    parser.add_argument("--cache", default=str(DEFAULT_SCORE_CACHE))
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(argv)
    raw_command = ["python", "-m", "pipeline.graph_lrolesim_run", *argv]

    run = run_pilot(
        mode=args.mode,
        local_kg_path=args.local_kg,
        mapping_dir=args.mapping_dir,
        cache_path=args.cache,
        verbose=not args.quiet,
    )
    inputs = load_frozen_mapping_inputs(args.mapping_dir)
    out_dir = write_all_outputs(
        run, args.output_dir,
        selected_mapping=inputs.selected_mapping_class,
        raw_command=raw_command,
    )

    feasible = len(run.graph_feasible_primary)
    print(f"\n[done] mode={run.mode}  outputs -> {out_dir}")
    print(f"       primary graph-feasible: {feasible}/{run.primary_denominator}")
    print(f"       network attempts: {run.guard_record['network_attempts']} "
          f"(http 0, sparql 0)")
    print(f"       score cache: {run.cache_record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
