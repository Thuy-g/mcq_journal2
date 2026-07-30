#!/usr/bin/env python
############################################################################
# src/classes/mapping_run.py
#
# Orchestration and provenance output for the class-member mapping stage:
#
#   approved DBpedia class -> retrieve members -> resolve redirects
#     -> map into the pinned local KG -> profile local candidate coverage
#
# THREE MODES, ONE MAPPING PATH
#   live            cache-first; HTTP only for pages the cache does not hold.
#   offline-cache   strict offline; reads the SQLite cache; no transport exists.
#   offline-frozen  strict offline; reads data/pilot_class_members_v1.jsonl only.
#
#   All three feed the SAME pure mapping and profiling functions, so "the offline
#   replay produces semantically identical mapping outputs" follows from the
#   structure rather than from a comparison performed afterwards. The comparison
#   is still made, as a check on that claim.
#
# BYTE-IDENTITY CONTRACT
#   The SCIENTIFIC result files carry no timestamp, no cache origin and no
#   attempt count, so they are byte-identical across modes:
#       mapping_summary.csv  selected_mapping_class.csv
#       mapped_candidates.jsonl  candidate_local_profiles.jsonl
#   Everything time-varying lives in the PROVENANCE files, which are expected to
#   differ between a live run and a replay:
#       query_log.jsonl  cache_inventory.json  run_manifest.json
#
# STOPS BEFORE GRAPH CONSTRUCTION (§4)
#   No build_m1_graph(), no candidate ordering policy, no OverlapScore, no
#   LRoleSim, no distractor selection, no rationale set cover, no verbalization.
############################################################################

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from classes.local_candidate_profile import (       # noqa: E402
    AnswerFootprint,
    CandidateLocalProfile,
    profile_answer_footprint,
    profile_candidate,
)
from classes.member_mapper import (                 # noqa: E402
    MIN_MAPPED_LOCAL_CANDIDATES,
    NO_MAPPING_FEASIBLE_APPROVED_CLASS,
    AnswerMappingOutcome,
    CachedPageFetcher,
    ClassMappingResult,
    ClassMemberRetriever,
    ClassRetrieval,
    FrozenClassMemberRetriever,
    FrozenRedirectSource,
    SparqlRedirectSource,
    collect_unmatched_members,
    frozen_redirect_records,
    make_local_lookup,
    map_class_members,
    resolve_redirect_chains,
    retrieve_all_classes,
    select_mapping_class_for_answer,
    verify_local_kg_sha256,
)
from classes.page_cache import (                    # noqa: E402
    PageCache,
    dumps_canonical,
    load_frozen_export,
    write_frozen_export,
)
from classes.policy import (                        # noqa: E402
    CLASS_POSITIONS,
    PilotClassPolicy,
    assert_policies_agree,
    load_policy_csv,
    load_policy_json,
)
from classes.sparql_client import (                 # noqa: E402
    DBPEDIA_ENDPOINT,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_REDIRECT_HOPS,
    DEFAULT_PAGE_SIZE,
    DEFAULT_REDIRECT_BATCH_SIZE,
    SCHEMA_VERSION,
    RequestsHttpTransport,
    SparqlPageClient,
    iso_utc,
    strip_uri_brackets,
)
from kg.graph_view import DEFAULT_MAX_NODES         # noqa: E402
from kg.loader import load_local_kg, sha256_file    # noqa: E402

# --- Pinned inputs ---------------------------------------------------------
DEFAULT_POLICY_CSV = REPO_ROOT / "data" / "pilot_class_policy_v1.csv"
DEFAULT_POLICY_JSON = REPO_ROOT / "data" / "pilot_class_policy_v1.json"
DEFAULT_LOCAL_KG = REPO_ROOT / "data" / "infobox.pickle_EnglishVersion_EntityType"
EXPECTED_LOCAL_KG_SHA256 = (
    "e230c5b95e20093631697624d9c46f30a14081b3f415d5027ffaf313bdbbea1b"
)
DEFAULT_CACHE_PATH = (
    REPO_ROOT / "data" / "cache" / "pilot_class_member_mapping_v1.sqlite")
DEFAULT_FROZEN_JSONL = REPO_ROOT / "data" / "pilot_class_members_v1.jsonl"
DEFAULT_FROZEN_MANIFEST = (
    REPO_ROOT / "data" / "pilot_class_members_v1_manifest.json")

MODE_LIVE = "live"
MODE_OFFLINE_CACHE = "offline-cache"
MODE_OFFLINE_FROZEN = "offline-frozen"
MODES = (MODE_LIVE, MODE_OFFLINE_CACHE, MODE_OFFLINE_FROZEN)

# --- Verdicts (§7) ---------------------------------------------------------
VERDICT_COMPLETE = "LOCAL_CLASS_MAPPING_COMPLETE_READY_FOR_GRAPH_POLICY"
VERDICT_PARTIAL = "LOCAL_CLASS_MAPPING_PARTIAL_RETRY_REQUIRED"

# --- Scientific file schemas ----------------------------------------------
# Explicit column lists rather than dict key order: these files must stay
# byte-identical across modes, so a field that varies with time or cache origin
# must not be able to drift in by accident.
MAPPING_SUMMARY_COLUMNS = (
    "pilot_slot",
    "answer_uri",
    "display_label",
    "answer_local_index",
    "class_position",
    "class_uri",
    "page_size",
    "page_count",
    "retrieval_complete",
    "incomplete_reason",
    "raw_member_count",
    "unique_member_count",
    "duplicate_row_count",
    "non_iri_row_count",
    "exact_local_mappings",
    "redirect_local_mappings",
    "unresolved_members",
    "duplicate_local_index_dropped",
    "answer_excluded_count",
    "mapped_candidate_count_excluding_answer",
    "mapping_gate_threshold",
    "passes_mapping_gate",
)

SELECTED_MAPPING_COLUMNS = (
    "pilot_slot",
    "answer_uri",
    "display_label",
    "answer_local_index",
    "mapping_stage_status",
    "selected_class_position",
    "selected_class_uri",
    "selected_mapped_candidate_count",
    "preferred_class_uri",
    "preferred_mapped_candidate_count",
    "preferred_passes_mapping_gate",
    "fallback_1_class_uri",
    "fallback_1_mapped_candidate_count",
    "fallback_1_passes_mapping_gate",
    "fallback_2_class_uri",
    "fallback_2_mapped_candidate_count",
    "fallback_2_passes_mapping_gate",
    "mapping_gate_threshold",
    "all_approved_classes_retrieval_complete",
)


class MappingRunError(Exception):
    """The run cannot proceed on the inputs it was given."""


# --- Small helpers ---------------------------------------------------------

def _write_csv(path: Path, columns: Sequence[str], rows: Iterable[Mapping]) -> Path:
    """Write a CSV with LF endings so the bytes do not depend on the platform."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns),
                                lineterminator="\n", extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: _csv_cell(row.get(c)) for c in columns})
    return path


def _csv_cell(value: object) -> object:
    """Render None as empty and bool as a stable lowercase token."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _write_jsonl(path: Path, records: Iterable[Mapping]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(dumps_canonical(record) + "\n")
    return path


def _write_json(path: Path, payload: Mapping) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    return path


def _git_head() -> Optional[str]:
    """The commit the run was executed at, or None outside a checkout."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _source_file_hashes() -> dict[str, str]:
    """SHA-256 of every source file this stage depends on.

    Recorded alongside the commit because the run happens BEFORE the commit: the
    commit alone would describe the previous state of the tree.
    """
    tracked = (
        "src/classes/sparql_client.py",
        "src/classes/page_cache.py",
        "src/classes/member_mapper.py",
        "src/classes/local_candidate_profile.py",
        "src/classes/mapping_run.py",
        "src/classes/policy.py",
        "src/kg/loader.py",
        "src/kg/graph_view.py",
        "pytest.ini",
    )
    hashes: dict[str, str] = {}
    for relative in tracked:
        path = REPO_ROOT / relative
        if path.is_file():
            hashes[relative] = sha256_file(path)
    return hashes


# --- Run configuration -----------------------------------------------------

@dataclass(frozen=True)
class RunConfig:
    mode: str
    output_dir: Path
    policy_csv: Path = DEFAULT_POLICY_CSV
    policy_json: Path = DEFAULT_POLICY_JSON
    local_kg_path: Path = DEFAULT_LOCAL_KG
    expected_local_kg_sha256: Optional[str] = EXPECTED_LOCAL_KG_SHA256
    cache_path: Path = DEFAULT_CACHE_PATH
    frozen_jsonl: Path = DEFAULT_FROZEN_JSONL
    frozen_manifest: Path = DEFAULT_FROZEN_MANIFEST
    endpoint: str = DBPEDIA_ENDPOINT
    page_size: int = DEFAULT_PAGE_SIZE
    max_pages: int = DEFAULT_MAX_PAGES
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    redirect_batch_size: int = DEFAULT_REDIRECT_BATCH_SIZE
    max_redirect_hops: int = DEFAULT_MAX_REDIRECT_HOPS
    max_nodes: int = DEFAULT_MAX_NODES
    write_frozen: bool = True

    @property
    def offline(self) -> bool:
        return self.mode in (MODE_OFFLINE_CACHE, MODE_OFFLINE_FROZEN)


@dataclass
class RunResult:
    """Everything a caller needs to report the verdict and write the evidence."""

    config: RunConfig
    verdict: str
    policy: PilotClassPolicy
    retrievals: dict[str, ClassRetrieval]
    outcomes: tuple[AnswerMappingOutcome, ...]
    manifest: dict
    written_files: tuple[Path, ...]
    network_page_count: int
    cache_hit_count: int
    failed_page_count: int


# --- The run ---------------------------------------------------------------

def run_mapping(config: RunConfig, *, transport: object = None) -> RunResult:
    """Execute one complete mapping run in the configured mode.

    `transport` is a seam, not a switch: production passes None and gets
    RequestsHttpTransport. A test passes a scripted transport so the whole live
    path — pagination, retry, caching, mapping, profiling and every output file —
    is exercised without a socket. It is ignored in both offline modes, which have
    no transport by construction.
    """
    if config.mode not in MODES:
        raise MappingRunError(f"unknown mode {config.mode!r}; expected {list(MODES)}")

    started = time.time()

    # --- inputs: both approved policy forms must agree ---------------------
    csv_policy = load_policy_csv(config.policy_csv)
    json_policy = load_policy_json(config.policy_json)
    assert_policies_agree(csv_policy, json_policy)
    policy = csv_policy

    # --- inputs: the pinned local KG, SHA-verified ------------------------
    local_kg = load_local_kg(config.local_kg_path,
                             verify_sha256=config.expected_local_kg_sha256)
    verify_local_kg_sha256(local_kg.source_sha256, config.expected_local_kg_sha256)
    local_lookup = make_local_lookup(local_kg.url_index)

    unique_classes = tuple(sorted({
        strip_uri_brackets(class_uri)
        for row in policy
        for class_uri in row.ordered_classes
    }))

    # --- Phase A: retrieval -----------------------------------------------
    cache: Optional[PageCache] = None
    fetcher: Optional[CachedPageFetcher] = None
    redirect_source: object
    query_log: list[dict] = []

    if config.mode == MODE_OFFLINE_FROZEN:
        export = load_frozen_export(config.frozen_jsonl)
        retriever: object = FrozenClassMemberRetriever(export=export)
        redirect_source = FrozenRedirectSource(export=export)
    else:
        cache = PageCache(config.cache_path, endpoint=config.endpoint)
        client: Optional[SparqlPageClient] = None
        if config.mode == MODE_LIVE:
            client = SparqlPageClient(
                transport=transport if transport is not None
                else RequestsHttpTransport(),
                endpoint=config.endpoint,
                max_attempts=config.max_attempts,
            )
        fetcher = CachedPageFetcher(
            cache=cache, client=client, endpoint=config.endpoint)
        retriever = ClassMemberRetriever(
            fetcher=fetcher, page_size=config.page_size, max_pages=config.max_pages)
        redirect_source = SparqlRedirectSource(
            fetcher=fetcher, batch_size=config.redirect_batch_size)

    retrievals = retrieve_all_classes(unique_classes, retriever)  # type: ignore[arg-type]

    # --- Phase A: redirects for every member with no exact local match ----
    unmatched = collect_unmatched_members(retrievals, local_lookup)
    redirect_outcomes = resolve_redirect_chains(
        unmatched, redirect_source, local_lookup,  # type: ignore[arg-type]
        max_hops=config.max_redirect_hops)

    # Retrieval is finished before ANY gate is evaluated (§3.5).
    for retrieval in retrievals.values():
        for page in retrieval.pages:
            query_log.append(page.as_log_record())
        for failure in retrieval.failures:
            query_log.append({"outcome": "FAILED", **failure.as_record()})
    if isinstance(redirect_source, SparqlRedirectSource):
        for page in redirect_source.pages:
            query_log.append(page.as_log_record())
        for failure in redirect_source.failures:
            query_log.append({"outcome": "FAILED", **failure.as_record()})

    # --- Phase B: pure mapping, then the frozen-count gate walk -----------
    outcomes: list[AnswerMappingOutcome] = []
    for row in policy:
        per_class: list[ClassMappingResult] = []
        for position, class_uri in row.ordered_positions:
            bare = strip_uri_brackets(class_uri)
            per_class.append(map_class_members(
                answer_uri=row.answer_uri,
                class_uri=bare,
                class_position=position,
                retrieval=retrievals[bare],
                local_lookup=local_lookup,
                redirect_outcomes=redirect_outcomes,
            ))
        outcomes.append(select_mapping_class_for_answer(row, per_class))

    # --- §4: descriptive local profiles, no graph construction ------------
    footprints: dict[str, AnswerFootprint] = {}
    profile_rows: list[dict] = []
    memo: dict[tuple[int, int], CandidateLocalProfile] = {}
    for outcome in outcomes:
        answer_lookup = local_lookup(outcome.answer_uri)
        if answer_lookup.local_index is None:
            raise MappingRunError(
                f"Answer {outcome.answer_uri!r} is absent from the pinned local KG; "
                f"the Week-1 inventory recorded all nine as present")
        footprint = profile_answer_footprint(
            outcome.answer_uri, answer_lookup.local_index,
            local_kg.in_neighbor, local_kg.out_neighbor,
            max_nodes=config.max_nodes)
        footprints[outcome.answer_uri] = footprint

        for result in outcome.per_class:
            for index in result.local_candidate_indices:
                key = (footprint.local_index, index)
                profile = memo.get(key)
                if profile is None:
                    profile = profile_candidate(
                        index, local_kg.in_neighbor, local_kg.out_neighbor,
                        footprint, index_url=local_kg.index_url)
                    memo[key] = profile
                profile_rows.append({
                    "pilot_slot": outcome.pilot_slot,
                    "answer_uri": outcome.answer_uri,
                    "class_position": result.class_position,
                    "class_uri": result.class_uri,
                    **footprint.as_record(),
                    **profile.as_record(),
                    "ordering_note": (
                        "emitted in ascending local_index order for deterministic "
                        "serialisation; local_index and URI order are NOT the "
                        "pilot's candidate-prioritization policy"),
                })

    # --- verdict ----------------------------------------------------------
    incomplete = tuple(sorted(
        r.class_uri for r in retrievals.values() if not r.retrieval_complete))
    verdict = VERDICT_COMPLETE if not incomplete else VERDICT_PARTIAL

    # --- outputs ----------------------------------------------------------
    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    summary_rows = [
        {
            "pilot_slot": outcome.pilot_slot,
            "answer_uri": outcome.answer_uri,
            "display_label": outcome.display_label,
            "answer_local_index": result.answer_local_index,
            "class_position": result.class_position,
            "class_uri": result.class_uri,
            "page_size": result.retrieval.page_size,
            "page_count": result.retrieval.page_count,
            "retrieval_complete": result.retrieval.retrieval_complete,
            "incomplete_reason": result.retrieval.incomplete_reason,
            "raw_member_count": result.retrieval.raw_member_count,
            "unique_member_count": result.retrieval.unique_member_count,
            "duplicate_row_count": result.retrieval.duplicate_row_count,
            "non_iri_row_count": result.retrieval.non_iri_row_count,
            "exact_local_mappings": result.exact_mapped_count,
            "redirect_local_mappings": result.redirect_mapped_count,
            "unresolved_members": result.unresolved_count,
            "duplicate_local_index_dropped": result.duplicate_dropped_count,
            "answer_excluded_count": result.answer_excluded_count,
            "mapped_candidate_count_excluding_answer": result.mapped_candidate_count,
            "mapping_gate_threshold": MIN_MAPPED_LOCAL_CANDIDATES,
            "passes_mapping_gate": result.passes_mapping_gate,
        }
        for outcome in outcomes
        for result in outcome.per_class
    ]
    written.append(_write_csv(
        out_dir / "mapping_summary.csv", MAPPING_SUMMARY_COLUMNS, summary_rows))

    selected_rows = []
    for outcome in outcomes:
        by_position = {r.class_position: r for r in outcome.per_class}
        row = {
            "pilot_slot": outcome.pilot_slot,
            "answer_uri": outcome.answer_uri,
            "display_label": outcome.display_label,
            "answer_local_index": outcome.per_class[0].answer_local_index,
            "mapping_stage_status": outcome.status,
            "selected_class_position": outcome.selected_position,
            "selected_class_uri": outcome.selected_class_uri,
            "selected_mapped_candidate_count": (
                None if outcome.selected_result is None
                else outcome.selected_result.mapped_candidate_count),
            "mapping_gate_threshold": MIN_MAPPED_LOCAL_CANDIDATES,
            "all_approved_classes_retrieval_complete": all(
                r.retrieval.retrieval_complete for r in outcome.per_class),
        }
        for position in CLASS_POSITIONS:
            result = by_position[position]
            row[f"{position}_class_uri"] = result.class_uri
            row[f"{position}_mapped_candidate_count"] = result.mapped_candidate_count
            row[f"{position}_passes_mapping_gate"] = result.passes_mapping_gate
        selected_rows.append(row)
    written.append(_write_csv(
        out_dir / "selected_mapping_class.csv", SELECTED_MAPPING_COLUMNS,
        selected_rows))

    written.append(_write_jsonl(out_dir / "mapped_candidates.jsonl", [
        {
            "pilot_slot": outcome.pilot_slot,
            "answer_uri": outcome.answer_uri,
            "answer_local_index": result.answer_local_index,
            "class_position": result.class_position,
            "class_uri": result.class_uri,
            **member.as_record(),
        }
        for outcome in outcomes
        for result in outcome.per_class
        for member in result.members
    ]))

    written.append(_write_jsonl(
        out_dir / "candidate_local_profiles.jsonl", profile_rows))

    # Provenance files: expected to differ between a live run and a replay.
    written.append(_write_jsonl(out_dir / "query_log.jsonl", query_log))

    cache_inventory = {
        "mode": config.mode,
        "endpoint": config.endpoint,
        "sqlite_cache": None if cache is None else cache.inventory(),
        "frozen_export": {
            "path": str(config.frozen_jsonl),
            "exists": config.frozen_jsonl.is_file(),
            "sha256": (sha256_file(config.frozen_jsonl)
                       if config.frozen_jsonl.is_file() else None),
            "size_bytes": (config.frozen_jsonl.stat().st_size
                           if config.frozen_jsonl.is_file() else None),
        },
        "fetcher_counters": None if fetcher is None else fetcher.counters(),
    }
    written.append(_write_json(out_dir / "cache_inventory.json", cache_inventory))

    # --- frozen replay export --------------------------------------------
    frozen_written = False
    if config.write_frozen and config.mode == MODE_LIVE and verdict == VERDICT_COMPLETE:
        write_frozen_export(
            config.frozen_jsonl,
            [r.as_frozen_record() for r in retrievals.values()],
            frozen_redirect_records(redirect_outcomes),
        )
        frozen_written = True

    finished = time.time()
    manifest = _build_manifest(
        config=config,
        policy=policy,
        local_kg_sha256=local_kg.source_sha256,
        local_kg_size=local_kg.source_size_bytes,
        unique_classes=unique_classes,
        retrievals=retrievals,
        outcomes=outcomes,
        redirect_outcomes=redirect_outcomes,
        fetcher=fetcher,
        redirect_source=redirect_source,
        query_log=query_log,
        verdict=verdict,
        incomplete=incomplete,
        started=started,
        finished=finished,
        profile_row_count=len(profile_rows),
        frozen_written=frozen_written,
    )
    written.append(_write_json(out_dir / "run_manifest.json", manifest))

    if frozen_written:
        frozen_manifest = dict(manifest)
        frozen_manifest["frozen_export"] = {
            "jsonl_path": str(config.frozen_jsonl),
            "jsonl_sha256": sha256_file(config.frozen_jsonl),
            "jsonl_size_bytes": config.frozen_jsonl.stat().st_size,
        }
        _write_json(config.frozen_manifest, frozen_manifest)

    return RunResult(
        config=config,
        verdict=verdict,
        policy=policy,
        retrievals=retrievals,
        outcomes=tuple(outcomes),
        manifest=manifest,
        written_files=tuple(written),
        network_page_count=0 if fetcher is None else fetcher.network_page_count,
        cache_hit_count=0 if fetcher is None else fetcher.cache_hit_count,
        failed_page_count=0 if fetcher is None else fetcher.failed_page_count,
    )


def _build_manifest(
    *,
    config: RunConfig,
    policy: PilotClassPolicy,
    local_kg_sha256: str,
    local_kg_size: int,
    unique_classes: Sequence[str],
    retrievals: Mapping[str, ClassRetrieval],
    outcomes: Sequence[AnswerMappingOutcome],
    redirect_outcomes: Mapping[str, object],
    fetcher: Optional[CachedPageFetcher],
    redirect_source: object,
    query_log: Sequence[Mapping],
    verdict: str,
    incomplete: Sequence[str],
    started: float,
    finished: float,
    profile_row_count: int,
    frozen_written: bool,
) -> dict:
    """The §5 manifest: every field required to reproduce and audit the run."""
    raw_members = sum(r.raw_member_count for r in retrievals.values())
    unique_members = sum(r.unique_member_count for r in retrievals.values())
    page_total = sum(r.page_count for r in retrievals.values())
    failed_pages = sum(len(r.failures) for r in retrievals.values())
    redirect_pages = len(getattr(redirect_source, "pages", ()))
    redirect_failed = len(getattr(redirect_source, "failures", ()))

    exact = sum(r.exact_mapped_count for o in outcomes for r in o.per_class)
    redirected = sum(r.redirect_mapped_count for o in outcomes for r in o.per_class)
    unresolved = sum(r.unresolved_count for o in outcomes for r in o.per_class)

    return {
        "task": "journal2_week1_local_mapping",
        "stage": ("approved class -> members -> redirects -> local mapping -> "
                  "local candidate profiling"),
        "schema_version": SCHEMA_VERSION,
        "mode": config.mode,
        "verdict": verdict,
        "endpoint": config.endpoint,
        "retrieval_started_at_iso_utc": iso_utc(started),
        "retrieval_finished_at_iso_utc": iso_utc(finished),
        "retrieval_timezone": "UTC (+00:00, explicit offset in every ISO field)",
        "wall_clock_seconds": round(finished - started, 3),
        "local_timezone_name": time.tzname[0] if time.tzname else None,
        "inputs": {
            "policy_csv_path": str(config.policy_csv),
            "policy_csv_sha256": sha256_file(config.policy_csv),
            "policy_json_path": str(config.policy_json),
            "policy_json_sha256": sha256_file(config.policy_json),
            "policy_forms_agree": True,
            "local_kg_path": str(config.local_kg_path),
            "local_kg_sha256": local_kg_sha256,
            "local_kg_size_bytes": local_kg_size,
            "expected_local_kg_sha256": config.expected_local_kg_sha256,
            "local_kg_sha256_verified": (
                local_kg_sha256 == config.expected_local_kg_sha256),
        },
        "parameters": {
            "page_size": config.page_size,
            "max_pages_per_class": config.max_pages,
            "max_http_attempts_per_page": config.max_attempts,
            "redirect_batch_size": config.redirect_batch_size,
            "max_redirect_hops": config.max_redirect_hops,
            "membership_relation": "?member dcterms:subject <CLASS_URI>",
            "redirect_relation": "dbo:wikiPageRedirects",
            "owl_sameAs_used": False,
            "mapping_gate_threshold": MIN_MAPPED_LOCAL_CANDIDATES,
            "max_nodes_for_profiling": config.max_nodes,
        },
        "counts": {
            "pilot_answer_count": len(policy),
            "answer_class_row_count": len(policy) * len(CLASS_POSITIONS),
            "unique_approved_class_count": len(unique_classes),
            "query_page_count": page_total + redirect_pages,
            "class_member_page_count": page_total,
            "redirect_batch_page_count": redirect_pages,
            "successful_page_count": page_total + redirect_pages,
            "failed_page_count": failed_pages + redirect_failed,
            "query_log_record_count": len(query_log),
            "raw_member_count": raw_members,
            "unique_member_count": unique_members,
            "redirect_lookups_attempted": len(redirect_outcomes),
            "exact_local_mappings": exact,
            "redirect_local_mappings": redirected,
            "unresolved_count": unresolved,
            "candidate_profile_row_count": profile_row_count,
        },
        "network": {
            "http_calls": 0 if fetcher is None else fetcher.network_page_count,
            "cache_hits": 0 if fetcher is None else fetcher.cache_hit_count,
            "strict_offline": config.offline,
            "transport_present": bool(
                fetcher is not None and fetcher.client is not None),
        },
        "retrieval_completeness": {
            "all_classes_complete": not incomplete,
            "incomplete_classes": list(incomplete),
        },
        "mapping_stage_outcomes": [o.as_record() for o in outcomes],
        "no_mapping_feasible_approved_class": [
            o.answer_uri for o in outcomes
            if o.status == NO_MAPPING_FEASIBLE_APPROVED_CLASS
        ],
        "frozen_export_written": frozen_written,
        "source_code_commit_at_run": _git_head(),
        "source_file_sha256": _source_file_hashes(),
        "python_version": sys.version.split()[0],
        "boundaries": [
            "the mapping gate is a NECESSARY MAPPING condition only; it is not "
            "graph-budget feasibility",
            "no graph was built, no OverlapScore computed, no LRoleSim run, no "
            "distractor selected, no rationale produced",
            "URI and local-index order are deterministic serialisation only, not "
            "the pilot's candidate-prioritization policy",
            "an unresolved member is an open-world absence in this dump, never a "
            "claim that the entity does not exist",
        ],
    }


# --- CLI -------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Retrieve approved DBpedia class members, resolve redirects, "
                     "map them into the pinned local KG and profile local "
                     "candidate coverage. Builds no graph and runs no LRoleSim."))
    parser.add_argument("--mode", choices=MODES, default=MODE_OFFLINE_CACHE,
                        help="live performs HTTP for uncached pages; both offline "
                             "modes have no transport at all (default: %(default)s)")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--frozen-jsonl", type=Path, default=DEFAULT_FROZEN_JSONL)
    parser.add_argument("--frozen-manifest", type=Path,
                        default=DEFAULT_FROZEN_MANIFEST)
    parser.add_argument("--policy-csv", type=Path, default=DEFAULT_POLICY_CSV)
    parser.add_argument("--policy-json", type=Path, default=DEFAULT_POLICY_JSON)
    parser.add_argument("--local-kg", type=Path, default=DEFAULT_LOCAL_KG)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--redirect-batch-size", type=int,
                        default=DEFAULT_REDIRECT_BATCH_SIZE)
    parser.add_argument("--max-redirect-hops", type=int,
                        default=DEFAULT_MAX_REDIRECT_HOPS)
    parser.add_argument("--no-frozen-export", action="store_true",
                        help="do not (re)write the frozen replay export")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = RunConfig(
        mode=args.mode,
        output_dir=args.output_dir,
        policy_csv=args.policy_csv,
        policy_json=args.policy_json,
        local_kg_path=args.local_kg,
        cache_path=args.cache,
        frozen_jsonl=args.frozen_jsonl,
        frozen_manifest=args.frozen_manifest,
        page_size=args.page_size,
        max_pages=args.max_pages,
        max_attempts=args.max_attempts,
        redirect_batch_size=args.redirect_batch_size,
        max_redirect_hops=args.max_redirect_hops,
        write_frozen=not args.no_frozen_export,
    )
    result = run_mapping(config)

    print(f"mode={result.config.mode}  verdict={result.verdict}")
    print(f"http_calls={result.network_page_count}  "
          f"cache_hits={result.cache_hit_count}  "
          f"failed_pages={result.failed_page_count}")
    print(f"unique approved classes: "
          f"{result.manifest['counts']['unique_approved_class_count']}")
    print(f"raw members={result.manifest['counts']['raw_member_count']}  "
          f"unique={result.manifest['counts']['unique_member_count']}")
    print(f"exact={result.manifest['counts']['exact_local_mappings']}  "
          f"redirect={result.manifest['counts']['redirect_local_mappings']}  "
          f"unresolved={result.manifest['counts']['unresolved_count']}")
    for outcome in result.outcomes:
        counts = [r.mapped_candidate_count for r in outcome.per_class]
        print(f"  slot {outcome.pilot_slot} {outcome.display_label:<22} "
              f"{outcome.status:<34} counts={counts}")
    for path in result.written_files:
        print(f"  wrote {path}")
    return 0 if result.verdict == VERDICT_COMPLETE else 2


if __name__ == "__main__":
    raise SystemExit(main())
