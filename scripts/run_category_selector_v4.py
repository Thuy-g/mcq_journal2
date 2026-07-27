#!/usr/bin/env python3
############################################################################
# scripts/run_category_selector_v4.py
#
# Deterministic, auditable batch runner for category selector v3.4
# (src/category_extractor_ClaudeWeb_v4.py).
#
# Derived from scripts/run_category_selector_v3.py at frozen hash d9787802…,
# which remains unchanged. Only what v3.4 compatibility requires moved:
# the selector import, the runner schema version, four redirect-provenance
# columns in summary.csv, and a resume-completeness rule that will not accept
# a v3.3 record as a finished v3.4 Answer.
#
# The selector decides *what* a class is; this runner decides only *how many
# Answers get asked, in what order, and where the evidence is written*. It adds
# no ranking, no thresholds and no class policy of its own.
#
# Design commitments, each of which has a test:
#
#   * Network access is denied unless --allow-network is passed. Without it the
#     process exits before a live client is constructed.
#   * Exactly one SparqlRunner serves the whole batch, and the redirect resolver
#     is built over that same runner, so every query a selection causes lands in
#     that Answer's counters and in the batch total.
#   * Answers are processed sequentially in input order. No threads, no
#     multiprocessing, no async.
#   * A normal selector outcome — query_failed, no_subject_categories,
#     all_categories_rejected — is data, not an error: it is recorded and the
#     batch continues with exit code 0.
#   * An unexpected Python exception is isolated to its Answer, recorded in a
#     clearly distinct envelope, and makes the *process* exit nonzero.
#   * Outputs are replaced with os.replace(), so a partially written file is
#     never mistaken for a finished one.
#
# This module performs no I/O at import: no file is created, no model is loaded
# and no query is issued until a function is called.
############################################################################

from __future__ import annotations

import argparse
import ast
import contextlib
import csv
import hashlib
import io
import json
import os
import pickle
import platform
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from category_extractor_ClaudeWeb_v4 import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    DEFAULT_ENDPOINT,
    DEFAULT_LANGUAGE,
    DEFAULT_SBERT_MODEL,
    DEFAULT_TOP_N,
    SCHEMA_VERSION as SELECTOR_SCHEMA_VERSION,
    MODES,
    SbertEncoder,
    SparqlRedirectResolver,
    SparqlRunner,
    is_safe_uri,
    make_dbpedia_runner,
    select_candidate_classes,
)

__all__ = [
    "RUNNER_SCHEMA_VERSION",
    "SELECTOR_SCHEMA_VERSION",
    "extract_answer_nodes_from_v2",
    "AnswerInput",
    "load_answer_input",
    "read_answer_uris",
    "write_answer_uris",
    "is_complete_result_record",
    "is_complete_exception_record",
    "load_previous_records",
    "existing_output_files",
    "build_resolver",
    "run_batch",
    "BatchOutcome",
    "build_parser",
    "main",
]

# ---------------------------------------------------------------------------
# Constants. Nothing here performs I/O.
# ---------------------------------------------------------------------------

# 1.1: summary.csv gained four redirect-provenance columns and --resume now
# requires them, so a v1.0 result set is not interchangeable with a v1.1 one.
RUNNER_SCHEMA_VERSION = "category_runner_v1.1"

RESULTS_FILENAME = "results.jsonl"
SUMMARY_FILENAME = "summary.csv"
RANKING_FILENAME = "ranking.csv"
MANIFEST_FILENAME = "run_manifest.json"

# Every JSONL line carries a discriminator, so an exception envelope can never
# be read as a selection result by a consumer that forgets to check.
RECORD_TYPE_RESULT = "class_selection_result"
RECORD_TYPE_EXCEPTION = "runner_exception"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NETWORK_DENIED = 3
EXIT_UNEXPECTED_EXCEPTIONS = 4
EXIT_OUTPUT_EXISTS = 5

OUTPUT_FILENAMES = (
    RESULTS_FILENAME,
    SUMMARY_FILENAME,
    RANKING_FILENAME,
    MANIFEST_FILENAME,
)

# What a previously written record must contain before --resume may treat the
# Answer as finished. Anything less is evidence of an interrupted or foreign
# run, not of a completed one.
RESUMABLE_RESULT_FIELDS = frozenset(
    {
        "original_uri",
        "schema_version",
        "query_status",
        "selection_status",
        "sparql_query_count",
        "cache_stats",
        "recommended_classes",
        "evaluated_classes",
        # v3.4 provenance. A record lacking any of these was written by an older
        # selector, or by an interrupted write, and is not a finished v3.4 Answer.
        "redirect_used",
        "redirect_attempted",
        "redirect_target",
        "redirect_resolution_status",
        "redirect_rejected_reason",
    }
)
EXCEPTION_ENVELOPE_FIELDS = frozenset(
    {
        "original_uri",
        "runner_exception_type",
        "runner_exception_message",
        "traceback",
        "queries_spent",
    }
)

# Manifest keys that legitimately differ between two otherwise identical runs.
# Declared in the manifest itself so a consumer comparing two runs knows what to
# exclude without having to guess.
NONDETERMINISTIC_MANIFEST_FIELDS = (
    "duration_seconds",
    "finished_at_utc",
    "git_commit",
    "git_describe",
    "platform",
    "python_version",
    "started_at_utc",
)

V2_SOURCE = SRC_DIR / "category_extractor_ClaudeWeb_v2.py"
DEFAULT_INPUT = REPO_ROOT / "data" / "category_answer_nodes_v2_demo.txt"

SUMMARY_COLUMNS = [
    "input_index",
    "original_uri",
    "query_uri",
    "display_label",
    "query_status",
    "selection_status",
    "mode",
    "selected_class",
    "redirect_used",
    "redirect_attempted",
    "redirect_target",
    "redirect_resolution_status",
    "redirect_rejected_reason",
    "number_of_categories",
    "categories_truncated",
    "sparql_query_count",
    "cache_queries",
    "cache_hits",
    "client_calls",
    "failed_queries",
    "zero_result_queries",
    "recommended_class_count",
    "runner_exception_type",
    "runner_exception_message",
]

RANKING_COLUMNS = [
    "input_index",
    "original_uri",
    "selection_status",
    "category_uri",
    "category_short",
    "display_label",
    "recommended_rank",
    "feasible",
    "rejected_code",
    "rejected_reason",
    "remote_count",
    "eligible_remote_count",
    "local_count",
    "local_check",
    "raw_idf",
    "normalized_idf",
    "raw_sbert",
    "normalized_sbert",
    "combined_score",
    "scored",
    "leak_level",
]


class RunnerInputError(ValueError):
    """A problem with the caller's input that must stop the batch before it starts."""


# ---------------------------------------------------------------------------
# 1) Input dataset
# ---------------------------------------------------------------------------


def extract_answer_nodes_from_v2(
    source_path: str | os.PathLike[str] = V2_SOURCE,
) -> list[str]:
    """Read the demo ``nodes`` list out of the v2 source by parsing, not running.

    v2's ``__main__`` block performs network calls and loads spaCy, so the list
    is recovered with :mod:`ast` and the module is never imported or executed.

    Angle brackets are stripped, duplicates are dropped keeping the first
    occurrence, and the surviving order is exactly the order written in v2. A
    value that is not an http(s) IRI is a defect in the input, not something to
    skip quietly, so it raises.
    """
    path = Path(source_path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    candidates: list[ast.List] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.List):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "nodes":
                candidates.append(node.value)

    if len(candidates) != 1:
        raise RunnerInputError(
            f"expected exactly one 'nodes = [...]' assignment in {path}, "
            f"found {len(candidates)}"
        )

    raw: list[str] = []
    for element in candidates[0].elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            raise RunnerInputError(
                f"non-string entry in the 'nodes' list of {path} at line "
                f"{getattr(element, 'lineno', '?')}"
            )
        raw.append(element.value)

    return _normalize_uri_sequence(raw, origin=str(path))


def _normalize_uri_sequence(values: Sequence[str], *, origin: str) -> list[str]:
    """Strip angle brackets, validate, and drop repeats keeping first occurrence."""
    seen: set[str] = set()
    ordered: list[str] = []
    for position, value in enumerate(values):
        uri = str(value).strip()
        if uri.startswith("<") and uri.endswith(">"):
            uri = uri[1:-1].strip()
        if not is_safe_uri(uri):
            raise RunnerInputError(
                f"{origin}: entry {position} is not a usable http(s) IRI: {value!r}"
            )
        if uri in seen:
            continue  # first occurrence wins; order is never rearranged
        seen.add(uri)
        ordered.append(uri)
    return ordered


@dataclass(frozen=True)
class AnswerInput:
    """The input dataset, with both counts that matter for provenance.

    ``row_count`` is how many usable rows the file held; ``uris`` is what
    survived first-occurrence deduplication. Reporting only one of them would
    make a file with repeats indistinguishable from one without.
    """

    uris: tuple[str, ...]
    row_count: int


def load_answer_input(path: str | os.PathLike[str]) -> AnswerInput:
    """One URI per line. Blank lines and ``#`` comments are ignored.

    A row that is not a usable http(s) IRI raises rather than being dropped: a
    silently shortened Answer list would corrupt a yield-rate denominator.
    """
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise RunnerInputError(f"cannot read input file {target}: {exc}") from exc
    rows = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return AnswerInput(
        uris=tuple(_normalize_uri_sequence(rows, origin=str(target))),
        row_count=len(rows),
    )


def read_answer_uris(path: str | os.PathLike[str]) -> list[str]:
    """The deduplicated Answer URIs from ``path``, in first-occurrence order."""
    return list(load_answer_input(path).uris)


def write_answer_uris(path: str | os.PathLike[str], uris: Sequence[str]) -> None:
    """Write the input dataset, one bare URI per line, atomically."""
    _atomic_write_text(Path(path), "".join(f"{uri}\n" for uri in uris))


# ---------------------------------------------------------------------------
# 2) Small deterministic helpers
# ---------------------------------------------------------------------------


def _atomic_write_text(path: Path, text: str) -> None:
    """Write via a temporary file in the same directory, then ``os.replace``.

    A reader therefore sees either the previous complete file or the new
    complete one, never a truncated write mistaken for a finished run.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> Optional[str]:
    target = Path(path)
    if not target.is_file():
        return None
    return hashlib.sha256(target.read_bytes()).hexdigest()


def _git(*args: str) -> Optional[str]:
    """A read-only git query. Returns None when git or the repo is unavailable."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _csv_bool(value: Any) -> str:
    if value is None:
        return ""
    return "true" if bool(value) else "false"


def _csv_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return _csv_bool(value)
    return str(value)


def _jsonl(records: Sequence[Mapping[str, Any]]) -> str:
    return "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
    )


def _rows_to_csv(columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(columns), lineterminator="\n", restval=""
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# 3) Record shaping
# ---------------------------------------------------------------------------


def _is_exception_record(record: Mapping[str, Any]) -> bool:
    return record.get("record_type") == RECORD_TYPE_EXCEPTION


def _summary_row(index: int, uri: str, record: Mapping[str, Any]) -> dict[str, Any]:
    if _is_exception_record(record):
        return {
            "input_index": index,
            "original_uri": uri,
            "runner_exception_type": record.get("runner_exception_type", ""),
            "runner_exception_message": record.get("runner_exception_message", ""),
        }
    stats = record.get("cache_stats") or {}
    return {
        "input_index": index,
        "original_uri": _csv_scalar(record.get("original_uri")),
        "query_uri": _csv_scalar(record.get("query_uri")),
        "display_label": _csv_scalar(record.get("display_label")),
        "query_status": _csv_scalar(record.get("query_status")),
        "selection_status": _csv_scalar(record.get("selection_status")),
        "mode": _csv_scalar(record.get("mode")),
        "selected_class": _csv_scalar(record.get("selected_class")),
        "redirect_used": _csv_bool(record.get("redirect_used")),
        "redirect_attempted": _csv_bool(record.get("redirect_attempted")),
        "redirect_target": _csv_scalar(record.get("redirect_target")),
        "redirect_resolution_status": _csv_scalar(
            record.get("redirect_resolution_status")
        ),
        "redirect_rejected_reason": _csv_scalar(
            record.get("redirect_rejected_reason")
        ),
        "number_of_categories": _csv_scalar(record.get("number_of_categories")),
        "categories_truncated": _csv_bool(record.get("categories_truncated")),
        "sparql_query_count": _csv_scalar(record.get("sparql_query_count")),
        "cache_queries": _csv_scalar(stats.get("queries")),
        "cache_hits": _csv_scalar(stats.get("cache_hits")),
        "client_calls": _csv_scalar(stats.get("client_calls")),
        "failed_queries": _csv_scalar(stats.get("failed")),
        "zero_result_queries": _csv_scalar(stats.get("zero_results")),
        "recommended_class_count": len(record.get("recommended_classes") or ()),
        "runner_exception_type": "",
        "runner_exception_message": "",
    }


def _ranking_rows(
    index: int, uri: str, record: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """One row per evaluated class. An exception envelope contributes none."""
    if _is_exception_record(record):
        return []
    ranks = {
        candidate.get("category_uri"): position
        for position, candidate in enumerate(record.get("recommended_classes") or (), 1)
    }
    rows: list[dict[str, Any]] = []
    for candidate in record.get("evaluated_classes") or ():
        category_uri = candidate.get("category_uri")
        rows.append(
            {
                "input_index": index,
                "original_uri": uri,
                "selection_status": _csv_scalar(record.get("selection_status")),
                "category_uri": _csv_scalar(category_uri),
                "category_short": _csv_scalar(candidate.get("category_short")),
                "display_label": _csv_scalar(candidate.get("display_label")),
                # Blank, not 0, for a class that is not recommended: absence of
                # a rank is not rank zero.
                "recommended_rank": _csv_scalar(ranks.get(category_uri)),
                "feasible": _csv_bool(candidate.get("feasible")),
                "rejected_code": _csv_scalar(candidate.get("rejected_code")),
                "rejected_reason": _csv_scalar(candidate.get("rejected_reason")),
                "remote_count": _csv_scalar(candidate.get("remote_count")),
                "eligible_remote_count": _csv_scalar(
                    candidate.get("eligible_remote_count")
                ),
                "local_count": _csv_scalar(candidate.get("local_count")),
                "local_check": _csv_scalar(candidate.get("local_check")),
                "raw_idf": _csv_scalar(candidate.get("raw_idf")),
                "normalized_idf": _csv_scalar(candidate.get("normalized_idf")),
                "raw_sbert": _csv_scalar(candidate.get("raw_sbert")),
                "normalized_sbert": _csv_scalar(candidate.get("normalized_sbert")),
                "combined_score": _csv_scalar(candidate.get("combined_score")),
                "scored": _csv_bool(candidate.get("scored")),
                "leak_level": _csv_scalar(candidate.get("leak_level")),
            }
        )
    return rows


def _has_answer_uri(record: Mapping[str, Any]) -> bool:
    uri = record.get("original_uri")
    return isinstance(uri, str) and bool(uri)


def is_complete_result_record(record: Mapping[str, Any]) -> bool:
    """True only for a finished selection written by *this* selector version.

    Parseable JSON is not the same as a finished Answer. A record that is
    missing its payload, or that was written by a different selector schema, is
    not evidence that the Answer completed, so resuming past it would silently
    leave a gap in the batch.
    """
    if record.get("record_type") != RECORD_TYPE_RESULT:
        return False
    # An exact match, so a v3.3 record can never be resumed as a v3.4 one and
    # --resume can never merge two selector schemas into one result set.
    if record.get("schema_version") != SELECTOR_SCHEMA_VERSION:
        return False
    if not _has_answer_uri(record):
        return False
    return all(field in record for field in RESUMABLE_RESULT_FIELDS)


def is_complete_exception_record(record: Mapping[str, Any]) -> bool:
    """True for a fully formed runner-exception envelope."""
    if record.get("record_type") != RECORD_TYPE_EXCEPTION:
        return False
    if not _has_answer_uri(record):
        return False
    return all(field in record for field in EXCEPTION_ENVELOPE_FIELDS)


def load_previous_records(path: str | os.PathLike[str]) -> dict[str, dict[str, Any]]:
    """Answer URI -> record, for every *completed* Answer already present.

    Three kinds of line are deliberately not resumable:

    * a truncated final line, the signature of an interrupted write, which
      fails to parse;
    * a parseable but incomplete record, which proves nothing finished;
    * a runner-exception envelope, which records a failure. Skipping it would
      freeze a transient defect into the result set forever, so the Answer is
      rerun and the envelope replaced by whatever the rerun produces.
    """
    target = Path(path)
    preserved: dict[str, dict[str, Any]] = {}
    if not target.is_file():
        return preserved
    for line in target.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if is_complete_result_record(record):
            preserved.setdefault(record["original_uri"], record)
    return preserved


def existing_output_files(output_dir: str | os.PathLike[str]) -> list[Path]:
    """Which of this runner's four output files already exist in ``output_dir``."""
    directory = Path(output_dir)
    return [directory / name for name in OUTPUT_FILENAMES if (directory / name).exists()]


# ---------------------------------------------------------------------------
# 4) Batch execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BatchOutcome:
    """What the batch produced.

    ``normal_result_count`` and ``unexpected_exception_count`` describe the
    *complete final output* — everything ``results.jsonl`` now holds, including
    records carried over by ``--resume``. The ``new_*`` counters describe only
    what this invocation executed. Conflating the two would make a resumed run
    look like it had done less work than the result set represents.
    """

    records: tuple[dict[str, Any], ...]
    normal_result_count: int
    unexpected_exception_count: int
    new_normal_result_count: int
    new_unexpected_exception_count: int
    resumed_count: int
    final_record_count: int
    output_paths: Mapping[str, Path]
    manifest: Mapping[str, Any]

    @property
    def exit_code(self) -> int:
        # Keyed to the final output, not to this invocation: an envelope that a
        # resumed run failed to clear must keep the batch failing.
        return EXIT_UNEXPECTED_EXCEPTIONS if self.unexpected_exception_count else EXIT_OK


def build_resolver(
    runner: SparqlRunner, *, enabled: bool
) -> Optional[SparqlRedirectResolver]:
    """The one resolver for the batch, over the one runner.

    Giving the resolver its own runner would send redirect lookups around the
    per-Answer counter view, so they would appear in no result's provenance.
    """
    if not enabled:
        return None
    resolver = SparqlRedirectResolver(runner)
    assert resolver.runner is runner, "the resolver must share the batch runner"
    return resolver


def run_batch(
    *,
    answer_uris: Sequence[str],
    output_dir: str | os.PathLike[str],
    runner: SparqlRunner,
    selector_options: Optional[Mapping[str, Any]] = None,
    resolve_redirects: bool = False,
    encoder: Any = None,
    local_index: Optional[Mapping[str, Any]] = None,
    resume: bool = False,
    manifest_context: Optional[Mapping[str, Any]] = None,
) -> BatchOutcome:
    """Run the frozen selector once per Answer and write the audit outputs.

    ``selector_options`` holds only JSON-serialisable scalars, so the manifest
    can record verbatim what was asked for. Object-valued inputs — the runner,
    the encoder, the local index — are passed separately and recorded only as
    booleans, which also keeps memory addresses out of the manifest.
    """
    options = dict(selector_options or {})
    if len(set(answer_uris)) != len(answer_uris):
        # Deduplication belongs at input. A repeat here would produce two
        # records for one Answer and break the resume contract.
        raise RunnerInputError("answer_uris contains duplicate entries")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)

    results_path = directory / RESULTS_FILENAME
    summary_path = directory / SUMMARY_FILENAME
    ranking_path = directory / RANKING_FILENAME
    manifest_path = directory / MANIFEST_FILENAME

    preserved = load_previous_records(results_path) if resume else {}
    resolver = build_resolver(runner, enabled=resolve_redirects)

    started_monotonic = time.monotonic()
    started_at = _utc_now()

    records: list[dict[str, Any]] = []
    new_normal_count = 0
    new_exception_count = 0
    resumed_count = 0

    try:
        for uri in answer_uris:
            if resume and uri in preserved:
                records.append(dict(preserved[uri]))
                resumed_count += 1
                continue

            before = runner.stats()
            try:
                result = select_candidate_classes(
                    uri,
                    runner=runner,
                    resolve_redirects=resolve_redirects,
                    redirect_resolver=resolver,
                    encoder=encoder,
                    local_index=local_index,
                    **options,
                )
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as exc:  # noqa: BLE001 - isolation is the point
                # An unexpected failure is the runner's problem, not a finding
                # about the Answer, so it is never dressed up as a result.
                after = runner.stats()
                record = {
                    "record_type": RECORD_TYPE_EXCEPTION,
                    "original_uri": uri,
                    "runner_exception_type": type(exc).__name__,
                    "runner_exception_message": str(exc),
                    "traceback": traceback.format_exc(),
                    "queries_spent": after["queries"] - before["queries"],
                }
                new_exception_count += 1
            else:
                record = dict(result.to_dict())
                record["record_type"] = RECORD_TYPE_RESULT
                new_normal_count += 1

            records.append(record)
            # Re-published after every Answer, so an interrupted batch leaves a
            # complete file that --resume can build on.
            _atomic_write_text(results_path, _jsonl(records))
    finally:
        _atomic_write_text(results_path, _jsonl(records))

    summary_rows = [
        _summary_row(index, uri, record)
        for index, (uri, record) in enumerate(zip(answer_uris, records))
    ]
    ranking_rows: list[dict[str, Any]] = []
    for index, (uri, record) in enumerate(zip(answer_uris, records)):
        ranking_rows.extend(_ranking_rows(index, uri, record))

    _atomic_write_text(summary_path, _rows_to_csv(SUMMARY_COLUMNS, summary_rows))
    _atomic_write_text(ranking_path, _rows_to_csv(RANKING_COLUMNS, ranking_rows))

    finished_at = _utc_now()
    duration = round(time.monotonic() - started_monotonic, 6)

    # Every count below describes the complete final output, so that the
    # manifest and results.jsonl can never disagree about what was produced.
    final_exception_count = sum(1 for r in records if _is_exception_record(r))
    final_normal_count = len(records) - final_exception_count

    selection_status_counts: dict[str, int] = {}
    query_status_counts: dict[str, int] = {}
    for record in records:
        if _is_exception_record(record):
            selection_status_counts["runner_exception"] = (
                selection_status_counts.get("runner_exception", 0) + 1
            )
            continue
        selection = str(record.get("selection_status"))
        query = str(record.get("query_status"))
        selection_status_counts[selection] = selection_status_counts.get(selection, 0) + 1
        query_status_counts[query] = query_status_counts.get(query, 0) + 1

    context = dict(manifest_context or {})
    manifest = {
        "runner_schema_version": RUNNER_SCHEMA_VERSION,
        "selector_schema_version": SELECTOR_SCHEMA_VERSION,
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "duration_seconds": duration,
        "command_arguments": context.get("command_arguments"),
        "input_path": context.get("input_path"),
        "input_sha256": context.get("input_sha256"),
        "input_row_count": context.get("input_row_count"),
        "unique_answer_count": len(answer_uris),
        "output_file_sha256": {
            RESULTS_FILENAME: sha256_file(results_path),
            SUMMARY_FILENAME: sha256_file(summary_path),
            RANKING_FILENAME: sha256_file(ranking_path),
        },
        "git_commit": _git("rev-parse", "HEAD"),
        "git_describe": _git("describe", "--tags", "--always", "--dirty"),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "endpoint": getattr(runner, "endpoint", None),
        "language": options.get("language", context.get("language")),
        "cache_path": context.get("cache_path"),
        "cache_mode": context.get("cache_mode", _cache_mode(runner)),
        "redirects_enabled": bool(resolve_redirects),
        "sbert_enabled": encoder is not None,
        "sbert_model": context.get("sbert_model"),
        "local_index_supplied": local_index is not None,
        "selector_configuration": dict(options),
        "shared_runner_final_stats": runner.stats(),
        # Complete final output, including anything --resume carried over.
        "normal_result_count": final_normal_count,
        "unexpected_exception_count": final_exception_count,
        "final_record_count": len(records),
        # This invocation only.
        "new_normal_result_count": new_normal_count,
        "new_unexpected_exception_count": new_exception_count,
        "resumed_record_count": resumed_count,
        "selection_status_counts": dict(sorted(selection_status_counts.items())),
        "query_status_counts": dict(sorted(query_status_counts.items())),
        "nondeterministic_fields": list(NONDETERMINISTIC_MANIFEST_FIELDS),
    }
    _atomic_write_text(
        manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )

    return BatchOutcome(
        records=tuple(records),
        normal_result_count=final_normal_count,
        unexpected_exception_count=final_exception_count,
        new_normal_result_count=new_normal_count,
        new_unexpected_exception_count=new_exception_count,
        resumed_count=resumed_count,
        final_record_count=len(records),
        output_paths={
            "results": results_path,
            "summary": summary_path,
            "ranking": ranking_path,
            "manifest": manifest_path,
        },
        manifest=manifest,
    )


def _cache_mode(runner: SparqlRunner) -> str:
    """How the batch treated the cache, read off the runner itself."""
    if getattr(runner, "cache", None) is None:
        return "disabled"
    if getattr(runner, "bypass", False):
        return "bypass"
    if getattr(runner, "refresh", False):
        return "refresh"
    return "read_write"


# ---------------------------------------------------------------------------
# 5) Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_category_selector_v4.py",
        description=(
            "Batch-run category selector v3.4 over a list of Answer "
            "URIs and write an auditable record of every decision."
        ),
        epilog=(
            "Network access is denied unless --allow-network is given. Without "
            "it the process exits before any live client is constructed, so an "
            "accidental run cannot reach DBpedia or download a model."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_INPUT,
        help="text file of Answer URIs, one per line",
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True,
        help="directory to write results.jsonl, summary.csv, ranking.csv and run_manifest.json",
    )
    parser.add_argument(
        "--cache-path", type=str, default=DEFAULT_CACHE_PATH,
        help="SQLite response cache; an incompatible file is refused, never migrated",
    )
    parser.add_argument("--mode", choices=sorted(MODES), default="recommended")
    parser.add_argument(
        "--requested-class", type=str, default=None,
        help="required in manual mode; ignored otherwise",
    )
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--endpoint", type=str, default=DEFAULT_ENDPOINT)
    parser.add_argument("--language", type=str, default=DEFAULT_LANGUAGE)
    parser.add_argument(
        "--allow-network", action="store_true",
        help="opt in to contacting the endpoint; without this the run is refused",
    )
    parser.add_argument(
        "--resolve-redirects", action="store_true",
        help="follow one dbo:wikiPageRedirects hop, using the shared runner",
    )
    parser.add_argument(
        "--use-sbert", action="store_true",
        help="score abstracts with SBERT; requires --allow-network, since the model may be downloaded",
    )
    parser.add_argument("--sbert-model", type=str, default=DEFAULT_SBERT_MODEL)
    parser.add_argument(
        "--local-index-pickle", type=Path, default=None,
        help="pickled mapping of local KG keys; validated before any query is issued",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="ignore cached entries but store fresh ones (mutually exclusive with --bypass)",
    )
    parser.add_argument(
        "--bypass", action="store_true",
        help="neither read nor write the cache (mutually exclusive with --refresh)",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="skip Answers already holding a complete record in results.jsonl",
    )
    return parser


def _load_local_index(path: Path) -> Mapping[str, Any]:
    """Load and validate the local-KG index before any query is issued.

    NOTE: this unpickles a file the caller names. Pickle executes arbitrary code
    on load, so the file must be one you produced yourself.
    """
    try:
        with open(path, "rb") as handle:
            payload = pickle.load(handle)
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError, ImportError) as exc:
        raise RunnerInputError(f"cannot read local index pickle {path}: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - any unpickling failure is an input error
        raise RunnerInputError(f"cannot read local index pickle {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise RunnerInputError(
            f"local index pickle {path} holds {type(payload).__name__}, expected a mapping"
        )
    if not payload:
        raise RunnerInputError(f"local index pickle {path} is empty")
    return payload


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.refresh and args.bypass:
        print(
            "error: --refresh and --bypass are mutually exclusive: one stores fresh "
            "responses, the other stores nothing.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if args.mode == "manual" and not args.requested_class:
        print("error: --requested-class is required in manual mode.", file=sys.stderr)
        return EXIT_USAGE
    if args.top_n < 1:
        print("error: --top-n must be at least 1.", file=sys.stderr)
        return EXIT_USAGE

    try:
        answer_input = load_answer_input(args.input)
    except RunnerInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    answer_uris = list(answer_input.uris)
    if not answer_uris:
        print(f"error: {args.input} contains no usable Answer URIs.", file=sys.stderr)
        return EXIT_USAGE

    # A previous experiment's outputs are evidence. Overwriting them because a
    # command was rerun with the wrong --output-dir destroys a result set that
    # may have cost thousands of queries, so the run is refused instead.
    if not args.resume:
        clashes = existing_output_files(args.output_dir)
        if clashes:
            listing = "\n".join(f"  {path}" for path in clashes)
            print(
                "refusing to run: these output files already exist and would be "
                f"overwritten:\n{listing}\n"
                "Choose a new --output-dir, or pass --resume to continue that "
                "result set. Nothing has been modified.",
                file=sys.stderr,
            )
            return EXIT_OUTPUT_EXISTS

    local_index = None
    if args.local_index_pickle is not None:
        try:
            local_index = _load_local_index(args.local_index_pickle)
        except RunnerInputError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE

    # ---- the network gate -------------------------------------------------
    # Everything above reads local files only. Nothing below runs without an
    # explicit opt-in, and no live client exists until after this point.
    if not args.allow_network:
        print(
            "refusing to run: this batch would query "
            f"{args.endpoint} for {len(answer_uris)} Answer(s).\n"
            "Network access is denied by default. Re-run with --allow-network "
            "if you intend to contact the endpoint.",
            file=sys.stderr,
        )
        return EXIT_NETWORK_DENIED

    runner = make_dbpedia_runner(
        endpoint=args.endpoint,
        language=args.language,
        cache_path=args.cache_path,
        refresh=args.refresh,
        bypass=args.bypass,
    )
    # Constructed only after the gate: loading a sentence-transformers model may
    # itself reach the network.
    encoder = SbertEncoder(name=args.sbert_model) if args.use_sbert else None

    selector_options: dict[str, Any] = {
        "mode": args.mode,
        "top_n": args.top_n,
        "language": args.language,
    }
    if args.mode == "manual":
        selector_options["requested_class"] = args.requested_class

    outcome = run_batch(
        answer_uris=answer_uris,
        output_dir=args.output_dir,
        runner=runner,
        selector_options=selector_options,
        resolve_redirects=args.resolve_redirects,
        encoder=encoder,
        local_index=local_index,
        resume=args.resume,
        manifest_context={
            "command_arguments": list(argv) if argv is not None else sys.argv[1:],
            "input_path": str(args.input),
            "input_sha256": sha256_file(args.input),
            "input_row_count": answer_input.row_count,
            "cache_path": args.cache_path,
            "cache_mode": "bypass" if args.bypass else ("refresh" if args.refresh else "read_write"),
            "sbert_model": args.sbert_model if args.use_sbert else None,
            "language": args.language,
        },
    )

    print(
        f"{outcome.final_record_count} record(s) in the final output: "
        f"{outcome.normal_result_count} result(s), "
        f"{outcome.unexpected_exception_count} unexpected exception(s) "
        f"({outcome.new_normal_result_count} new, "
        f"{outcome.new_unexpected_exception_count} newly failed, "
        f"{outcome.resumed_count} resumed); outputs in {args.output_dir}"
    )
    return outcome.exit_code


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
