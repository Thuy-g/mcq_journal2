############################################################################
# category_extractor_ClaudeWeb_v3.py
#
# Journal 2 — Phase 1: candidate-class selection.
#
# Scope of this module
# --------------------
# Given an Answer URI, help identify candidate classes (DBpedia
# ``dcterms:subject`` categories) from which distractor candidates can later be
# retrieved. That is all. This module deliberately does NOT:
#
#   * find a globally optimal class (no such objective is defined or proved);
#   * measure the educational quality of a class;
#   * solve ontology alignment;
#   * retrieve, rank, or select distractors;
#   * generate or validate rationales.
#
# Selection is two-stage, as specified in
# ``docs/context/03_journal2_algorithm_spec.md`` §4:
#
#   1. hard feasibility checking;
#   2. recommendation ranking among feasible classes.
#
# Relationship to v2
# ------------------
# ``src/category_extractor_ClaudeWeb_v2.py`` is unchanged and remains the
# reference for the previous behaviour. This file is additive. The behavioural
# differences that matter scientifically are:
#
#   D1  No import-time side effects. v2 executes ``_CACHE = SparqlCache()`` at
#       module level, which creates an SQLite file merely by importing it.
#       Here the SPARQL client and the cache are injected by the caller.
#   D2  Query failure, successful zero-result, and cache hit are three distinct
#       observable states. v2 collapses all of them into ``[]``, which makes
#       the yield-rate experiment (docs/context/06_evaluation_plan.md §6.1)
#       impossible to measure.
#   D3  Every query containing ``LIMIT`` also contains ``ORDER BY``, and
#       truncation is reported rather than silent.
#   D4  Answer leakage is graded (hard / soft / none). v2 hard-rejects on any
#       shared WordNet lemma, which can discard usable classes. WordNet can
#       only ever produce a SOFT verdict here, never a rejection.
#   D5  Display-label formatting and leak detection are separate operations
#       with separate normalisers. v2's ``remove_parenthetical()`` deletes any
#       parenthetical, which corrupts chemical entities
#       (``Iron(III)_chloride`` -> ``Iron chloride``).
#   D6  IDF and SBERT similarity are rank-normalised within one Answer before
#       being combined, and all five score components are returned separately.
#   D7  Sequential execution only. v2's thread pool shared lazily initialised
#       SBERT/WordNet/spaCy globals across six worker threads.
#
# Terminology (docs/context/09_claims_and_terminology.md)
# ------------------------------------------------------
#   requested_class      class supplied by the question creator
#   recommended_class    class suggested by the system
#   top_ranked_class     highest scoring feasible class
#   first_feasible_class first class satisfying the hard constraints
#
# The word "optimal" is not used about any class produced here.
#
# Selection status semantics
# --------------------------
#   ok                              a class was selected
#   no_label                        query succeeded but the URI has neither a
#                                   label nor any subject category (the URI
#                                   appears to be unknown to the endpoint)
#   no_subject_categories           labelled entity with zero categories
#   all_categories_rejected         categories existed and every one of them
#                                   failed a check that ran to completion
#   no_confirmed_feasible_class     no class was confirmed feasible, but at
#                                   least one class stayed unresolved, so
#                                   rejection was NOT demonstrated
#   manual_class_invalid            requested class is malformed, is a
#                                   maintenance category, is too generic, or
#                                   hard-leaks the Answer
#   manual_class_not_member         Answer is not a member of the requested class
#   insufficient_remote_candidates  class has fewer than ``min_remote_candidates``
#   insufficient_local_candidates   the class was enumerated completely and has
#                                   fewer than ``min_local_candidates`` members
#                                   present in the local KG index
#   local_check_inconclusive        the local member count is only a lower bound
#                                   because enumeration was cut short; the class
#                                   is NOT shown to be insufficient
#   local_uri_not_found             Answer URI cannot be mapped into the local KG
#   query_failed                    a required SPARQL query failed (NOT a
#                                   successful zero-result)
#
# The local-KG check reports one of five outcomes per class (``LocalCheck``):
# not applicable, checked and feasible, checked and insufficient, inconclusive
# (incomplete enumeration), or not checked because a probe budget ran out. A
# truncated prefix of a member list is never treated as a complete count.
#
# Deferred in this phase, with interfaces provided
# ------------------------------------------------
#   * redirect resolution is implemented but disabled by default and has NOT
#     been verified against a live endpoint (see ``resolve_query_uri``);
#   * the disambiguator whitelist is a small hand-written default; deriving it
#     from the KG (audit Appendix B.2) is future work;
#   * ``total_entities`` is a documented constant, not a measured count;
#   * choice-label distinctness across the final Answer + distractor set
#     belongs to the MCQ-rendering phase, not here.
############################################################################

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
import unicodedata
import urllib.parse
import warnings
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Protocol, Sequence

__all__ = [
    "QueryStatus",
    "SelectionStatus",
    "LeakLevel",
    "CacheStatus",
    "QueryResult",
    "SparqlClient",
    "SparqlResponseCache",
    "InMemorySparqlCache",
    "SqliteSparqlCache",
    "CacheSchemaMismatch",
    "SparqlRunner",
    "PerAnswerRunner",
    "DBpediaSparqlClient",
    "make_dbpedia_runner",
    "AnswerInfo",
    "ClassCandidate",
    "ClassSelectionResult",
    "LeakVerdict",
    "RedirectResolver",
    "SparqlRedirectResolver",
    "RedirectQueryFailed",
    "resolve_query_uri",
    "format_display_label",
    "detect_leak",
    "category_specificity",
    "chunk_text",
    "split_sentences",
    "estimate_tokens",
    "AbstractEncoder",
    "SbertEncoder",
    "select_candidate_classes",
    "rank_classes_for_answer",
    "choose_best_class_for_answer",
    "sample_queries",
    "query_id",
    "is_safe_uri",
    "LocalCheck",
    "LocalMemberCount",
    "has_unresolved_classes",
]

# ---------------------------------------------------------------------------
# 0) CONFIGURATION — plain constants only. Nothing here performs I/O.
# ---------------------------------------------------------------------------

# 3.1: ``ClassCandidate`` gained ``eligible_remote_count`` and local counts
#      stopped counting the Answer as one of its own distractors.
# 3.2: ``sparql_query_count`` and ``cache_stats`` changed meaning from the
#      runner's cumulative totals to this Answer's own spend. Records written by
#      3.1 and 3.2 have identical field names but incomparable counter values
#      whenever one runner served more than one Answer, which is why the version
#      moves rather than the field names.
# 3.3: those same per-Answer counters now include the built-in redirect query.
#      A 3.2 record produced with ``resolve_redirects=True`` undercounts by one
#      query per hop, so redirect-enabled 3.2 and 3.3 counters are likewise not
#      comparable. A failed redirect lookup is also now reported as a query
#      failure rather than as an absence of categories.
# The SQLite cache table is untouched throughout, so CACHE_SCHEMA_VERSION stays
# at 3.0 — it versions the on-disk schema, not the result record.
SCHEMA_VERSION = "category_selector_v3.3"
CACHE_SCHEMA_VERSION = "sparql_cache_v3.0"

DEFAULT_ENDPOINT = os.environ.get("DBPEDIA_ENDPOINT", "https://dbpedia.org/sparql")
DEFAULT_LANGUAGE = os.environ.get("DBPEDIA_LANG", "en")

# NOTE: this path is only a default *string*. No file or directory is created
# until a cache object is explicitly constructed and used. It deliberately
# differs from v2's ``./sparql_cache.sqlite``, whose ``cache(k, v, ts)`` schema
# is incompatible and must not be migrated or overwritten.
DEFAULT_CACHE_PATH = os.environ.get(
    "CATEGORY_V3_SPARQL_CACHE", "./cache/category_v3_sparql.sqlite"
)

DEFAULT_SBERT_MODEL = "all-MiniLM-L6-v2"

DEFAULT_MIN_REMOTE_CANDIDATES = 10
DEFAULT_MAX_REMOTE_CANDIDATES = 5000
DEFAULT_MIN_LOCAL_CANDIDATES = 10

# Used by ``category_specificity``. This is a documented constant, not a
# measured value; deriving it from the snapshot is deferred (audit CE-9).
DEFAULT_TOTAL_ENTITIES = 6_000_000

DEFAULT_ALPHA = 0.7           # weight of normalised SBERT in the combined score
DEFAULT_TOP_N = 5
DEFAULT_CATEGORY_LIMIT = 200  # max dcterms:subject values fetched per Answer
DEFAULT_MEMBER_LIMIT = 2000   # max members fetched for one class
DEFAULT_MAX_MEMBER_ROWS = 20000   # global row budget for the batched member probe
DEFAULT_MAX_LOCAL_PROBES = 12     # max classes probed against the local KG
DEFAULT_MAX_MEMBER_PAGES = 5      # max pages when paginating one class's members

CATEGORY_PREFIX = "http://dbpedia.org/resource/Category:"

# Only these namespaces may denote a candidate class. Anything else — another
# host, another path, or a resource URI that merely contains "Category:" — is
# rejected rather than interpolated into a query.
ALLOWED_CATEGORY_PREFIXES = (
    CATEGORY_PREFIX,
    "https://dbpedia.org/resource/Category:",
)

# Wikipedia maintenance / administrative categories carry no semantic content.
JUNK_CATEGORY_PATTERNS = (
    r"^Living_people$",
    r"^\d{3,4}_births$",
    r"^\d{3,4}_deaths$",
    r"^Year_of_(birth|death)_",
    r"^People_from_",
    r"^Date_of_(birth|death)_",
    r"^(All|Articles|Pages|Wikipedia|CS1|Use_|Webarchive|Commons)",
    r"_stubs$",
    r"_missing$",
    r"_needing_",
    r"_with_unsourced_",
    r"^\d{1,2}(st|nd|rd|th)-century_(births|deaths)$",
)
_JUNK_RE = re.compile("|".join(JUNK_CATEGORY_PATTERNS))

# Rejection reason codes. Free-text detail is kept per candidate; these codes
# are what ``number_rejected_by_reason`` counts.
REASON_JUNK = "junk_category"
REASON_TOO_SMALL = "insufficient_remote_candidates"
REASON_TOO_GENERIC = "too_generic"
REASON_HARD_LEAK = "hard_leak"
REASON_LOCAL_TOO_FEW = "insufficient_local_candidates"
REASON_LOCAL_NOT_PROBED = "local_probe_budget_exhausted"
REASON_LOCAL_INCONCLUSIVE = "local_candidates_inconclusive"
REASON_COUNT_UNAVAILABLE = "remote_count_unavailable"
REASON_INVALID_URI = "invalid_category_uri"

# Outcome buckets. A class is only counted as *rejected* when a check ran to
# completion and failed. A class whose evaluation was cut short is unresolved,
# and reporting it as a rejection would overstate what was measured.
INCONCLUSIVE_REASON_CODES = frozenset({REASON_LOCAL_INCONCLUSIVE})
NOT_EVALUATED_REASON_CODES = frozenset(
    {REASON_LOCAL_NOT_PROBED, REASON_COUNT_UNAVAILABLE}
)
UNRESOLVED_REASON_CODES = INCONCLUSIVE_REASON_CODES | NOT_EVALUATED_REASON_CODES


# ---------------------------------------------------------------------------
# 1) STATUS VOCABULARY
#
# Enum member names follow prompts/prompt_category_v3.md §4; the serialised
# ``.value`` strings follow docs/context/09_claims_and_terminology.md §9 so
# that JSONL output matches the terminology contract.
# ---------------------------------------------------------------------------


class QueryStatus(str, Enum):
    OK = "ok"
    ZERO_RESULTS = "zero_results"
    FAILED = "query_failed"


class SelectionStatus(str, Enum):
    OK = "ok"
    NO_LABEL = "no_label"
    NO_SUBJECT_CATEGORIES = "no_subject_categories"
    ALL_CATEGORIES_REJECTED = "all_categories_rejected"
    NO_CONFIRMED_FEASIBLE_CLASS = "no_confirmed_feasible_class"
    MANUAL_CLASS_INVALID = "manual_class_invalid"
    MANUAL_CLASS_NOT_MEMBER = "manual_class_not_member"
    INSUFFICIENT_REMOTE_CANDIDATES = "insufficient_remote_candidates"
    INSUFFICIENT_LOCAL_CANDIDATES = "insufficient_local_candidates"
    LOCAL_CHECK_INCONCLUSIVE = "local_check_inconclusive"
    LOCAL_URI_NOT_FOUND = "local_uri_not_found"
    QUERY_FAILED = "query_failed"


class LeakLevel(str, Enum):
    NONE = "no_leak"
    SOFT = "soft_overlap"
    HARD = "hard_leak"


class CacheStatus(str, Enum):
    HIT = "hit"
    MISS = "miss"
    BYPASS = "bypass"
    REFRESH = "refresh"
    DISABLED = "disabled"


class LocalCheck(str, Enum):
    """Outcome of the local-KG candidate check for one class.

    ``CHECKED_INSUFFICIENT`` is the only value that asserts a class really does
    not have enough local candidates. ``INCONCLUSIVE`` and ``NOT_CHECKED_BUDGET``
    both mean the question was left open, and must never be reported as a
    demonstrated shortage.
    """

    NOT_APPLICABLE = "not_applicable"
    CHECKED_FEASIBLE = "checked_feasible"
    CHECKED_INSUFFICIENT = "checked_insufficient"
    INCONCLUSIVE = "inconclusive"
    NOT_CHECKED_BUDGET = "not_checked_budget"


MODES = ("manual", "recommended", "first_feasible")


# ---------------------------------------------------------------------------
# 2) SPARQL TRANSPORT — injectable client, injectable cache
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueryResult:
    """Outcome of one SPARQL request.

    ``rows`` uses the SPARQL-JSON binding shape, i.e. each row is a mapping
    ``{"var": {"value": "..."}}``, so that a fake client in a unit test has the
    same shape as the real endpoint.
    """

    status: QueryStatus
    rows: tuple[Mapping[str, Any], ...] = ()
    error: Optional[str] = None
    query_hash: str = ""
    endpoint: str = ""
    language: str = ""
    retrieved_at: Optional[float] = None
    cache_status: CacheStatus = CacheStatus.DISABLED

    @property
    def ok(self) -> bool:
        return self.status is QueryStatus.OK

    @property
    def failed(self) -> bool:
        return self.status is QueryStatus.FAILED


class SparqlClient(Protocol):
    """Minimal transport contract. Implementations must not raise."""

    endpoint: str
    language: str

    def run(self, query: str) -> QueryResult:  # pragma: no cover - protocol
        ...


class SparqlResponseCache(Protocol):
    """Cache contract. Implementations must never store a failed query."""

    def get(self, key: str) -> Optional[Mapping[str, Any]]:  # pragma: no cover
        ...

    def put(self, key: str, record: Mapping[str, Any]) -> bool:  # pragma: no cover
        ...


# Every table a complete v3 cache must contain. An existing file that claims
# this schema version but lacks one of them is refused, not repaired.
_REQUIRED_CACHE_TABLES = frozenset({"responses", "meta"})


class CacheSchemaMismatch(RuntimeError):
    """Raised when a cache file was not written by this schema version."""


def compute_query_hash(endpoint: str, language: str, query: str) -> str:
    payload = f"{endpoint}\n{language}\n{query}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class InMemorySparqlCache:
    """Process-local cache. Useful for tests and for a single batch run."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> Optional[Mapping[str, Any]]:
        return self._rows.get(key)

    def put(self, key: str, record: Mapping[str, Any]) -> bool:
        if record.get("query_status") == QueryStatus.FAILED.value:
            return False
        self._rows[key] = dict(record)
        return True

    def __len__(self) -> int:
        return len(self._rows)


class SqliteSparqlCache:
    """SQLite-backed response cache.

    The connection is opened on first use, never at import. A cache file whose
    tables were not written by this schema version is refused rather than
    migrated, which protects v2's ``sparql_cache.sqlite`` from being altered.

    A cache is not by itself a reproducibility mechanism
    (docs/context/08_data_and_reproducibility.md §1); the snapshot, code,
    configuration, models, and seeds are also required.
    """

    def __init__(
        self,
        path: str | os.PathLike[str] = DEFAULT_CACHE_PATH,
        *,
        schema_version: str = CACHE_SCHEMA_VERSION,
        endpoint: str = DEFAULT_ENDPOINT,
        create_parents: bool = True,
    ) -> None:
        self.path = str(path)
        self.schema_version = schema_version
        self.endpoint = endpoint
        self._create_parents = create_parents
        self._conn: Optional[sqlite3.Connection] = None

    # -- connection handling ------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        target = Path(self.path)
        if self._create_parents and str(target.parent) not in ("", "."):
            target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)

        def refuse(reason: str) -> CacheSchemaMismatch:
            conn.close()
            return CacheSchemaMismatch(f"{self.path!r} {reason}")

        try:
            existing = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        except sqlite3.DatabaseError as exc:
            raise refuse(f"is not a readable SQLite database: {exc}") from exc

        if existing:
            # An existing database is validated *completely* before anything is
            # written to it. Creating the v3 tables first and only then reading
            # meta.schema_version — as this method used to — leaves a permanent
            # mark on a file that turns out to be foreign, which is exactly what
            # the refusal is supposed to prevent.
            if "meta" not in existing:
                raise refuse(
                    f"contains tables {sorted(existing)} but no 'meta' table; "
                    "refusing to write to a cache produced by another schema"
                )
            try:
                row = conn.execute(
                    "SELECT value FROM meta WHERE key='schema_version'"
                ).fetchone()
            except sqlite3.DatabaseError as exc:
                raise refuse(f"has an unreadable 'meta' table: {exc}") from exc
            if row is None:
                raise refuse(
                    "has a 'meta' table that records no schema_version; "
                    "refusing to adopt a cache of unknown provenance"
                )
            if row[0] != self.schema_version:
                raise refuse(
                    f"has schema_version {row[0]!r}, expected {self.schema_version!r}"
                )
            missing = sorted(_REQUIRED_CACHE_TABLES - existing)
            if missing:
                raise refuse(
                    f"declares schema_version {row[0]!r} but is missing table(s) "
                    f"{missing}; refusing to repair an incomplete cache in place"
                )
            self._conn = conn
            return conn

        # Only a database with no tables at all — a new file, or one this
        # process just created by connecting — may have the v3 schema written.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS responses ("
            " query_hash TEXT PRIMARY KEY,"
            " endpoint TEXT NOT NULL,"
            " language TEXT NOT NULL,"
            " response_json TEXT NOT NULL,"
            " query_status TEXT NOT NULL,"
            " retrieved_at REAL NOT NULL,"
            " schema_version TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT OR REPLACE INTO meta VALUES (?, ?)",
            [
                ("schema_version", self.schema_version),
                ("created_at", str(time.time())),
                ("endpoint", self.endpoint),
            ],
        )
        conn.commit()
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- cache protocol -----------------------------------------------------

    def get(self, key: str) -> Optional[Mapping[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            "SELECT endpoint, language, response_json, query_status, retrieved_at"
            " FROM responses WHERE query_hash=?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return {
            "endpoint": row[0],
            "language": row[1],
            "response_json": row[2],
            "query_status": row[3],
            "retrieved_at": row[4],
        }

    def put(self, key: str, record: Mapping[str, Any]) -> bool:
        # A failed query must never be stored as if it were a valid response.
        if record.get("query_status") == QueryStatus.FAILED.value:
            return False
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO responses VALUES (?,?,?,?,?,?,?)",
            (
                key,
                record["endpoint"],
                record["language"],
                record["response_json"],
                record["query_status"],
                float(record.get("retrieved_at") or time.time()),
                self.schema_version,
            ),
        )
        conn.commit()
        return True

    def meta(self) -> dict[str, str]:
        conn = self._connect()
        return {k: v for k, v in conn.execute("SELECT key, value FROM meta")}

    def clear(self) -> int:
        """Drop every cached response. Used by a ``--refresh``-style run."""
        conn = self._connect()
        n = conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
        conn.execute("DELETE FROM responses")
        conn.commit()
        return int(n)

    def __len__(self) -> int:
        conn = self._connect()
        return int(conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0])


@dataclass
class SparqlRunner:
    """Combines a client with an optional cache and records provenance counters.

    ``refresh``  ignore any cached entry but store the fresh response.
    ``bypass``   neither read nor write the cache.
    """

    client: SparqlClient
    cache: Optional[SparqlResponseCache] = None
    refresh: bool = False
    bypass: bool = False
    n_queries: int = 0
    n_cache_hits: int = 0
    n_client_calls: int = 0
    n_failed: int = 0
    n_zero_results: int = 0

    @property
    def endpoint(self) -> str:
        return getattr(self.client, "endpoint", DEFAULT_ENDPOINT)

    @property
    def language(self) -> str:
        return getattr(self.client, "language", DEFAULT_LANGUAGE)

    def run(self, query: str) -> QueryResult:
        self.n_queries += 1
        key = compute_query_hash(self.endpoint, self.language, query)

        if self.cache is not None and not self.bypass and not self.refresh:
            record = self.cache.get(key)
            if record is not None:
                self.n_cache_hits += 1
                status = QueryStatus(record["query_status"])
                if status is QueryStatus.ZERO_RESULTS:
                    self.n_zero_results += 1
                return QueryResult(
                    status=status,
                    rows=tuple(json.loads(record["response_json"])),
                    query_hash=key,
                    endpoint=record.get("endpoint", self.endpoint),
                    language=record.get("language", self.language),
                    retrieved_at=record.get("retrieved_at"),
                    cache_status=CacheStatus.HIT,
                )

        self.n_client_calls += 1
        try:
            result = self.client.run(query)
        except Exception as exc:  # noqa: BLE001 - transport errors are data
            result = QueryResult(status=QueryStatus.FAILED, error=repr(exc))

        # A successful response with no bindings is a distinct state.
        status = result.status
        if status is QueryStatus.OK and not result.rows:
            status = QueryStatus.ZERO_RESULTS

        if status is QueryStatus.FAILED:
            self.n_failed += 1
            # Provenance must survive failure: a bypassed run did not consult
            # the cache, so calling the outcome a MISS would misreport why no
            # cached answer was used. Nothing is written either way.
            if self.cache is None:
                cache_status = CacheStatus.DISABLED
            elif self.bypass:
                cache_status = CacheStatus.BYPASS
            else:
                cache_status = CacheStatus.MISS
            return QueryResult(
                status=status,
                rows=(),
                error=result.error,
                query_hash=key,
                endpoint=self.endpoint,
                language=self.language,
                retrieved_at=time.time(),
                cache_status=cache_status,
            )

        if status is QueryStatus.ZERO_RESULTS:
            self.n_zero_results += 1

        retrieved_at = time.time()
        cache_status = CacheStatus.DISABLED
        if self.cache is not None and not self.bypass:
            self.cache.put(
                key,
                {
                    "endpoint": self.endpoint,
                    "language": self.language,
                    "response_json": json.dumps([dict(r) for r in result.rows]),
                    "query_status": status.value,
                    "retrieved_at": retrieved_at,
                },
            )
            cache_status = CacheStatus.REFRESH if self.refresh else CacheStatus.MISS
        elif self.bypass:
            cache_status = CacheStatus.BYPASS

        return QueryResult(
            status=status,
            rows=tuple(result.rows),
            query_hash=key,
            endpoint=self.endpoint,
            language=self.language,
            retrieved_at=retrieved_at,
            cache_status=cache_status,
        )

    def stats(self) -> dict[str, int]:
        """Counters accumulated by *this* runner since it was constructed."""
        return {
            "queries": self.n_queries,
            "cache_hits": self.n_cache_hits,
            "client_calls": self.n_client_calls,
            "failed": self.n_failed,
            "zero_results": self.n_zero_results,
        }


# Pairs of (stats() key, SparqlRunner attribute) — the single place the counter
# names are written down, so a new counter cannot be added to one and forgotten
# in the other.
_COUNTER_FIELDS: tuple[tuple[str, str], ...] = (
    ("queries", "n_queries"),
    ("cache_hits", "n_cache_hits"),
    ("client_calls", "n_client_calls"),
    ("failed", "n_failed"),
    ("zero_results", "n_zero_results"),
)


class PerAnswerRunner(SparqlRunner):
    """A per-invocation counter view over a shared runner.

    Every query is delegated, so caching, refresh and bypass behaviour are
    unchanged and the shared runner's counters keep accumulating across the
    whole batch. What differs is *this* object's counters, which start at zero
    and therefore describe exactly one Answer.

    This exists because a batch that reuses one runner would otherwise report
    cumulative totals on every result after the first: two Answers costing three
    queries each would be recorded as 3 and 6 rather than 3 and 3. Wrapping
    rather than threading a baseline through every return path makes the
    property structural — there is no second source of numbers for a caller to
    reach for by mistake.
    """

    def __init__(self, delegate: SparqlRunner) -> None:
        super().__init__(
            client=delegate.client,
            cache=delegate.cache,
            refresh=delegate.refresh,
            bypass=delegate.bypass,
        )
        self.delegate = delegate

    def run(self, query: str) -> QueryResult:
        before = self.delegate.stats()
        try:
            return self.delegate.run(query)
        finally:
            # Mirror whatever the delegate counted, including on the failure
            # path, so the two views can never drift apart.
            after = self.delegate.stats()
            for name, attribute in _COUNTER_FIELDS:
                setattr(
                    self,
                    attribute,
                    getattr(self, attribute) + after[name] - before[name],
                )


def _base_runner(runner: SparqlRunner) -> SparqlRunner:
    """The shared runner underneath any stack of per-Answer views."""
    seen: set[int] = set()
    while isinstance(runner, PerAnswerRunner) and id(runner) not in seen:
        seen.add(id(runner))
        runner = runner.delegate
    return runner


@dataclass
class DBpediaSparqlClient:
    """Live endpoint transport. Constructed explicitly; never at import.

    ``SPARQLWrapper`` is imported lazily inside :meth:`run` so that importing
    this module — and running the unit tests — pulls in no HTTP machinery.
    """

    endpoint: str = DEFAULT_ENDPOINT
    language: str = DEFAULT_LANGUAGE
    timeout: int = 60
    retries: int = 3
    backoff_cap: float = 60.0
    sleep: Callable[[float], None] = time.sleep

    def run(self, query: str) -> QueryResult:
        from SPARQLWrapper import JSON, SPARQLWrapper  # lazy: keeps import clean

        last_error: Optional[str] = None
        for attempt in range(max(1, self.retries)):
            try:
                sparql = SPARQLWrapper(self.endpoint)
                sparql.setReturnFormat(JSON)
                sparql.setTimeout(self.timeout)
                sparql.setQuery(query)
                payload = sparql.query().convert()
                rows = tuple(payload["results"]["bindings"])
                return QueryResult(
                    status=QueryStatus.OK if rows else QueryStatus.ZERO_RESULTS,
                    rows=rows,
                    endpoint=self.endpoint,
                    language=self.language,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = repr(exc)
                if attempt < self.retries - 1:
                    self.sleep(min(2.0**attempt, self.backoff_cap))
        return QueryResult(
            status=QueryStatus.FAILED,
            error=last_error,
            endpoint=self.endpoint,
            language=self.language,
        )


def make_dbpedia_runner(
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    language: str = DEFAULT_LANGUAGE,
    cache_path: Optional[str] = DEFAULT_CACHE_PATH,
    refresh: bool = False,
    bypass: bool = False,
) -> SparqlRunner:
    """Build a live runner. Calling this is an explicit opt-in to network use."""
    cache = (
        SqliteSparqlCache(cache_path, endpoint=endpoint) if cache_path is not None else None
    )
    client = DBpediaSparqlClient(endpoint=endpoint, language=language)
    return SparqlRunner(client=client, cache=cache, refresh=refresh, bypass=bypass)


# ---------------------------------------------------------------------------
# 3) QUERY BUILDERS — pure functions, unit-testable without a network
#
# Invariant enforced by tests: a query containing LIMIT also contains ORDER BY.
# Each query carries a ``#qid:`` marker so that provenance records and test
# doubles can identify it without brittle substring matching.
# ---------------------------------------------------------------------------

QID_PREFIX = "#qid:"

_PREFIXES = """PREFIX dct:  <http://purl.org/dc/terms/>
PREFIX dbo:  <http://dbpedia.org/ontology/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>"""


def query_id(query: str) -> Optional[str]:
    """Return the ``#qid:`` marker of a query, or None."""
    for line in query.splitlines():
        stripped = line.strip()
        if stripped.startswith(QID_PREFIX):
            return stripped[len(QID_PREFIX) :].strip()
    return None


def _strip_uri(uri: str) -> str:
    return (uri or "").strip().strip("<>").strip()


# Characters that would terminate an IRI reference or a string literal inside a
# SPARQL query, plus C0/C1 control characters. A value containing any of them is
# refused outright rather than escaped, because a candidate class URI has no
# legitimate reason to contain one.
_UNSAFE_URI_CHARS = re.compile(r"""[\s<>"'{}|\\^`]|[\x00-\x1f\x7f-\x9f]""")
_SCHEME_RE = re.compile(r"^https?://[^/]+/")
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$")


def is_safe_uri(value: Optional[str]) -> bool:
    """True when ``value`` is an http(s) IRI safe to place inside ``<...>``."""
    if not value:
        return False
    text = _strip_uri(str(value))
    if not text or _UNSAFE_URI_CHARS.search(text):
        return False
    return bool(_SCHEME_RE.match(text))


def _validate_iri(value: Optional[str], *, what: str = "URI") -> str:
    """Return a safe IRI or raise ``ValueError``.

    Every query builder passes caller-supplied and endpoint-supplied URIs
    through this function before interpolating them, so no unvalidated value
    ever reaches a query string.
    """
    if not is_safe_uri(value):
        raise ValueError(f"unsafe or malformed {what}: {value!r}")
    return _strip_uri(str(value))


def _validate_language(value: Optional[str], *, what: str = "language tag") -> str:
    text = (value or "").strip()
    if not _LANGUAGE_RE.match(text):
        raise ValueError(f"unsafe or malformed {what}: {value!r}")
    return text


def build_answer_info_query(
    answer_uri: str, *, language: str = DEFAULT_LANGUAGE, membership_class: Optional[str] = None
) -> str:
    """Label + abstract, optionally plus a membership flag for one class.

    The subject-category OPTIONAL is deliberately *not* included here. In v2 all
    three OPTIONALs share one SELECT, so the result is a Cartesian product of
    label x abstract x category (audit CE-12).
    """
    subject = _validate_iri(answer_uri, what="answer URI")
    lang = _validate_language(language)
    membership = ""
    if membership_class:
        member_uri = _validate_iri(membership_class, what="membership class URI")
        membership = (
            f"\n  OPTIONAL {{ <{subject}> dct:subject <{member_uri}> ."
            ' BIND("yes" AS ?member) }'
        )
    return f"""{QID_PREFIX} answer_info
{_PREFIXES}
SELECT ?label ?abs ?member WHERE {{
  OPTIONAL {{ <{subject}> rdfs:label ?label . FILTER(lang(?label) = '{lang}') }}
  OPTIONAL {{ <{subject}> dbo:abstract ?abs . FILTER(lang(?abs) = '{lang}') }}{membership}
}}
"""


def build_answer_categories_query(answer_uri: str, *, limit: int = DEFAULT_CATEGORY_LIMIT) -> str:
    subject = _validate_iri(answer_uri, what="answer URI")
    return f"""{QID_PREFIX} answer_categories
{_PREFIXES}
SELECT DISTINCT ?cat WHERE {{
  <{subject}> dct:subject ?cat .
  FILTER(STRSTARTS(STR(?cat), "{CATEGORY_PREFIX}"))
}} ORDER BY ?cat LIMIT {int(limit)}
"""


def build_category_counts_query(category_uris: Sequence[str]) -> str:
    values = " ".join(
        f"<{_validate_iri(c, what='category URI')}>" for c in category_uris
    )
    return f"""{QID_PREFIX} category_counts
{_PREFIXES}
SELECT ?cat (COUNT(DISTINCT ?x) AS ?c) WHERE {{
  VALUES ?cat {{ {values} }}
  ?x dct:subject ?cat .
}} GROUP BY ?cat ORDER BY ?cat
"""


def build_class_members_query(
    category_uri: str,
    *,
    limit: int = DEFAULT_MEMBER_LIMIT,
    after: Optional[str] = None,
) -> str:
    """One deterministic page of a class's members.

    Pagination is keyset based, and the filter and the sort use the *same*
    expression: ``FILTER(STR(?x) > "cursor")`` is paired with
    ``ORDER BY STR(?x)``. Pairing the string comparison with a plain
    ``ORDER BY ?x`` would be unsound, because IRI ordering and lexical string
    ordering are not required to agree, and a page boundary computed under one
    order cannot then be trusted under the other. ``after`` must itself be a
    valid IRI.
    """
    category = _validate_iri(category_uri, what="category URI")
    keyset = ""
    if after:
        keyset = f'\n  FILTER(STR(?x) > "{_validate_iri(after, what="pagination cursor")}")'
    return f"""{QID_PREFIX} class_members
{_PREFIXES}
SELECT DISTINCT ?x WHERE {{
  ?x dct:subject <{category}> .{keyset}
}} ORDER BY STR(?x) LIMIT {int(limit)}
"""


def build_class_members_batch_query(
    category_uris: Sequence[str], *, limit: int = DEFAULT_MAX_MEMBER_ROWS
) -> str:
    values = " ".join(
        f"<{_validate_iri(c, what='category URI')}>" for c in category_uris
    )
    return f"""{QID_PREFIX} class_members_batch
{_PREFIXES}
SELECT DISTINCT ?cat ?x WHERE {{
  VALUES ?cat {{ {values} }}
  ?x dct:subject ?cat .
}} ORDER BY ?cat ?x LIMIT {int(limit)}
"""


def build_redirect_query(answer_uri: str) -> str:
    """Single-hop ``dbo:wikiPageRedirects`` lookup. ``owl:sameAs`` is not used."""
    subject = _validate_iri(answer_uri, what="answer URI")
    return f"""{QID_PREFIX} redirect
{_PREFIXES}
SELECT ?target WHERE {{
  <{subject}> dbo:wikiPageRedirects ?target .
}} ORDER BY ?target LIMIT 1
"""


def sample_queries() -> dict[str, str]:
    """One representative query per builder, for invariant tests and docs."""
    uri = "http://dbpedia.org/resource/Shinya_Yamanaka"
    cat = CATEGORY_PREFIX + "Japanese_Nobel_laureates"
    cat2 = CATEGORY_PREFIX + "Japanese_biologists"
    return {
        "answer_info": build_answer_info_query(uri),
        "answer_info_with_membership": build_answer_info_query(uri, membership_class=cat),
        "answer_categories": build_answer_categories_query(uri),
        "category_counts": build_category_counts_query([cat, cat2]),
        "class_members": build_class_members_query(cat),
        "class_members_batch": build_class_members_batch_query([cat, cat2]),
        "redirect": build_redirect_query(uri),
    }


def _binding(row: Mapping[str, Any], key: str) -> Optional[str]:
    cell = row.get(key)
    if isinstance(cell, Mapping):
        value = cell.get("value")
        return None if value is None else str(value)
    return None if cell is None else str(cell)


# ---------------------------------------------------------------------------
# 4) DISPLAY LABELS
#
# Display formatting is a presentation concern only. It never touches a URI
# used for querying or for local-KG lookup, and it is a different function from
# the normaliser used by leak detection (§5).
#
# Rules, applied in order, stopping at the first match
# (docs/context/03_journal2_algorithm_spec.md §3; audit Appendix B.2):
#   R0  prefer rdfs:label, else the URI local name; unquote; NFC; '_' -> ' '
#   R1  no '(' at all                                 -> keep
#   R2  parenthetical not terminal                    -> keep
#   R3  no separator before '('                       -> keep  (Phosphorus(V))
#   R4  content is a Roman numeral or numeric         -> keep  ((III), (1,2))
#   R5  content is a known disambiguator              -> drop  ((physicist))
#   R6  anything else                                 -> keep  (uncertain)
# ---------------------------------------------------------------------------

# A small, explicitly configurable default. Audit Appendix B.2 proposes
# deriving this list from the KG with a single grouped query and publishing it
# alongside the paper; that derivation is deferred, and callers may inject
# their own set through ``disambiguator_suffixes``.
DEFAULT_DISAMBIGUATOR_SUFFIXES = frozenset(
    {
        "actor", "actress", "album", "band", "biologist", "book", "chemist",
        "city", "company", "disambiguation", "film", "footballer", "given name",
        "japan", "journalist", "mathematician", "mountain", "movie", "musician",
        "name", "novel", "park", "philosopher", "physicist", "poet", "politician",
        "river", "singer", "song", "station", "surname", "tokyo", "town",
        "tv series", "video game", "village", "writer",
    }
)

_ROMAN_RE = re.compile(r"^[IVXLCDM]+$")
_NUMERIC_RE = re.compile(r"^[0-9±+\-.,/ ]+$")
_TERMINAL_PAREN_RE = re.compile(r"^(?P<head>.*\S)[ _]\((?P<inside>[^()]*)\)$")


def _uri_local_name(uri: str) -> str:
    bare = _strip_uri(uri)
    tail = bare.rsplit("/", 1)[-1]
    if "#" in tail:
        tail = tail.rsplit("#", 1)[-1]
    return tail


def format_display_label(
    uri: str,
    *,
    rdfs_label: Optional[str] = None,
    language: str = "en",
    disambiguator_suffixes: Optional[Iterable[str]] = None,
) -> str:
    """Human-readable label for an entity or category URI.

    ``language`` is accepted for interface symmetry with the caller's language
    configuration; the formatting rules below are language independent, so it
    does not change the output. The original URI is never modified.

    Distinctness across a rendered choice set (audit invariant INV-2, e.g. not
    letting ``Iron(II) chloride`` and ``Iron(III) chloride`` collapse to the
    same string) is deliberately *not* handled here — it belongs to the
    MCQ-rendering phase. The rules above preserve oxidation states, so the
    inputs that make that invariant necessary are not created by this function.
    """
    suffixes = (
        DEFAULT_DISAMBIGUATOR_SUFFIXES
        if disambiguator_suffixes is None
        else frozenset(s.strip().casefold() for s in disambiguator_suffixes)
    )

    # R0 -------------------------------------------------------------------
    if rdfs_label and str(rdfs_label).strip():
        base = str(rdfs_label)
    else:
        base = urllib.parse.unquote(_uri_local_name(uri))
    base = unicodedata.normalize("NFC", base)
    base = base.replace("_", " ")
    base = re.sub(r"\s+", " ", base).strip()
    if not base:
        return ""

    match = _TERMINAL_PAREN_RE.match(base)
    if match is None:
        return base  # R1, R2, R3

    inside = match.group("inside").strip()
    if not inside:
        return base
    if _ROMAN_RE.match(inside) or _NUMERIC_RE.match(inside):
        return base  # R4
    if inside.casefold() in suffixes:
        return match.group("head").strip()  # R5
    return base  # R6


# ---------------------------------------------------------------------------
# 5) LEAKAGE DETECTION — graded, never WordNet-only
#
# hard leak      the class name gives the Answer away -> reject the class
# soft overlap   a family/domain relationship -> audit flag, optional penalty
# no leak        -> nothing
#
# WordNet expansion can only ever produce SOFT. It is never a rejection and
# never the sole decision source, which is what
# prompts/prompt_category_v3.md §7 requires and what v2 violates.
# ---------------------------------------------------------------------------

_LEAK_STOPWORDS = frozenset(
    {
        "a", "an", "and", "by", "for", "from", "in", "list", "lists", "of", "on",
        "or", "people", "person", "persons", "the", "to", "with", "category",
        "categories", "member", "members",
    }
)


@dataclass(frozen=True)
class LeakVerdict:
    level: LeakLevel
    reason: Optional[str] = None
    evidence: tuple[str, ...] = ()

    @property
    def is_hard(self) -> bool:
        return self.level is LeakLevel.HARD

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "reason": self.reason,
            "evidence": list(self.evidence),
        }


def _normalize_for_matching(text: Optional[str]) -> str:
    """Aggressive normaliser used ONLY for leak comparison.

    This is intentionally separate from :func:`format_display_label`. It may
    discard information (including parentheticals) because its output is never
    shown to anybody.
    """
    value = unicodedata.normalize("NFKC", text or "")
    value = value.replace("_", " ")
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    return value.casefold()


def _contains_phrase(haystack: str, needle: str) -> bool:
    """Token-boundary containment, so 'plato' does not match 'platonists'."""
    if not haystack or not needle:
        return False
    return f" {needle} " in f" {haystack} "


def _content_tokens(normalized: str, *, min_length: int, stopwords: frozenset[str]) -> set[str]:
    return {
        token
        for token in normalized.split()
        if len(token) >= min_length and token not in stopwords
    }


def _proper_nouns(nlp: Any, text: str, *, min_length: int) -> set[str]:
    try:
        doc = nlp(text)
        return {
            token.text.casefold()
            for token in doc
            if getattr(token, "pos_", "") == "PROPN" and len(token.text) >= min_length
        }
    except Exception:  # noqa: BLE001 - an optional NLP layer must not break selection
        return set()


def detect_leak(
    answer_label: Optional[str],
    category_label: Optional[str],
    *,
    nlp: Any = None,
    synonym_expander: Optional[Callable[[str], Iterable[str]]] = None,
    min_token_length: int = 3,
    stopwords: frozenset[str] = _LEAK_STOPWORDS,
) -> LeakVerdict:
    """Grade the leakage risk of using ``category_label`` for ``answer_label``.

    HARD when the class name identifies the Answer:
      * the class label equals the Answer label;
      * the complete Answer name occurs inside the class name (or vice versa);
      * a distinctive proper name of the Answer occurs in the class name
        (requires ``nlp``; skipped silently when unavailable).

    SOFT when only a lemma/synonym family relationship is found, e.g.
    ``Phosphoric acid`` vs ``Phosphorus oxoacids``. SOFT never rejects.
    """
    answer_norm = _normalize_for_matching(answer_label)
    category_norm = _normalize_for_matching(category_label)
    if not answer_norm or not category_norm:
        return LeakVerdict(LeakLevel.NONE, "empty label")

    if answer_norm == category_norm:
        return LeakVerdict(
            LeakLevel.HARD,
            "class label is identical to the answer label",
            (answer_norm,),
        )

    if _contains_phrase(category_norm, answer_norm):
        return LeakVerdict(
            LeakLevel.HARD,
            "complete answer name occurs in the class name",
            (answer_norm,),
        )
    if _contains_phrase(answer_norm, category_norm):
        return LeakVerdict(
            LeakLevel.HARD,
            "complete class name occurs in the answer name",
            (category_norm,),
        )

    answer_propn: set[str] = set()
    if nlp is not None:
        answer_propn = _proper_nouns(nlp, str(answer_label or ""), min_length=min_token_length)
        category_propn = _proper_nouns(
            nlp, str(category_label or ""), min_length=min_token_length
        )
        shared_propn = {t for t in (answer_propn & category_propn) if t not in stopwords}
        if shared_propn:
            return LeakVerdict(
                LeakLevel.HARD,
                "distinctive proper name shared with the class name",
                tuple(sorted(shared_propn)),
            )

    if synonym_expander is not None:
        answer_tokens = _content_tokens(
            answer_norm, min_length=min_token_length, stopwords=stopwords
        )
        category_tokens = _content_tokens(
            category_norm, min_length=min_token_length, stopwords=stopwords
        )
        # Proper nouns are excluded from synonym expansion: WordNet senses of a
        # personal or chemical name are not evidence of a semantic family.
        answer_tokens -= answer_propn
        expanded_answer: set[str] = set()
        for token in sorted(answer_tokens):
            expanded_answer.update(t.casefold() for t in synonym_expander(token))
        expanded_category: set[str] = set()
        for token in sorted(category_tokens):
            expanded_category.update(t.casefold() for t in synonym_expander(token))
        shared = {t for t in (expanded_answer & expanded_category) if t not in stopwords}
        if shared:
            return LeakVerdict(
                LeakLevel.SOFT,
                "lemma or synonym family overlap",
                tuple(sorted(shared)[:5]),
            )

    return LeakVerdict(LeakLevel.NONE)


def make_wordnet_expander() -> Optional[Callable[[str], Iterable[str]]]:
    """Build a WordNet-backed synonym expander, or None when NLTK is missing.

    Loading happens when this factory is called, never at import.
    """
    try:
        from nltk.corpus import wordnet as wn
        from nltk.stem import WordNetLemmatizer

        wn.synsets("test")  # force corpus load so failures surface here
        lemmatizer = WordNetLemmatizer()
    except Exception:  # noqa: BLE001
        return None

    def expand(word: str) -> set[str]:
        base = word.casefold()
        out = {lemmatizer.lemmatize(base)}
        for synset in wn.synsets(base):
            for lemma in synset.lemmas():
                out.add(lemma.name().casefold().replace("_", " "))
        return out

    return expand


# ---------------------------------------------------------------------------
# 6) SCORING
#
# TF is 1 for every category-membership relation under consideration, so the
# lexical component is IDF, not TF-IDF. The API says so.
# ---------------------------------------------------------------------------


def category_specificity(
    member_count: Optional[int], *, total_entities: int = DEFAULT_TOTAL_ENTITIES
) -> float:
    """Inverse-document-frequency style specificity, scaled to [0, 1].

    1.0 for a singleton class, 0.0 for a class containing every entity.
    ``total_entities`` is a documented constant; measuring it from the snapshot
    is deferred (audit CE-9).
    """
    if member_count is None:
        return 0.0
    count = max(int(member_count), 1)
    total = max(int(total_entities), count, 2)
    return math.log(total / count) / math.log(total)


def _rank_normalize(values: Sequence[float]) -> list[float]:
    """Average-rank normalisation onto [0, 1].

    Rank normalisation is used rather than raw values because IDF is spread
    almost uniformly over [0, 1] while SBERT cosine similarity is concentrated
    in a narrow band, so adding the raw quantities lets IDF dominate regardless
    of alpha (audit §2.2, CE-9). Ties receive the same normalised value, which
    keeps the result independent of input order.
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    order = sorted(range(n), key=lambda i: (values[i], i))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return [r / (n - 1) for r in ranks]


# ---------------------------------------------------------------------------
# 7) ABSTRACT ENCODING — injectable, lazy, chunked
# ---------------------------------------------------------------------------


class AbstractEncoder(Protocol):
    name: str
    max_seq_length: int

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:  # pragma: no cover
        ...


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Regex sentence splitter. No NLTK punkt download is required."""
    if not text:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(text.strip()) if part.strip()]


def estimate_tokens(text: str) -> int:
    """Rough word-piece estimate: whitespace tokens x 1.3, floor 1.

    This is an *estimate*, not the model tokenizer. A chunk may still exceed the
    model limit and be truncated by the model itself; see ``encode_abstract``.
    """
    return max(1, int(round(len(text.split()) * 1.3)))


def chunk_text(
    text: str,
    *,
    max_tokens: int,
    safety_ratio: float = 0.8,
    token_estimator: Callable[[str], int] = estimate_tokens,
) -> list[str]:
    """Pack sentences into chunks that should fit the encoder's token limit.

    A sentence longer than the budget is split on word boundaries rather than
    dropped, so no part of the abstract is discarded. This replaces v2's
    character slicing, which threw text away before it reached the cache.
    """
    if not text or not text.strip():
        return []
    budget = max(1, int(max(1, int(max_tokens)) * safety_ratio))
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current, current_tokens
        if current:
            chunks.append(" ".join(current))
            current = []
            current_tokens = 0

    for sentence in split_sentences(text):
        size = token_estimator(sentence)
        if size > budget:
            flush()
            words = sentence.split()
            # Words-per-chunk derived from the same estimator ratio.
            per_chunk = max(1, int(budget * len(words) / max(1, size)))
            for start in range(0, len(words), per_chunk):
                chunks.append(" ".join(words[start : start + per_chunk]))
            continue
        if current_tokens + size > budget:
            flush()
        current.append(sentence)
        current_tokens += size
    flush()
    return chunks


@dataclass
class SbertEncoder:
    """Lazy sentence-transformers wrapper.

    The model is loaded on the first call to :meth:`encode` or the first read of
    :attr:`max_seq_length`, never at import and never during module discovery.
    """

    name: str = DEFAULT_SBERT_MODEL
    device: Optional[str] = None
    _model: Any = field(default=None, init=False, repr=False)

    @property
    def model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # lazy

            self._model = SentenceTransformer(self.name, device=self.device)
        return self._model

    @property
    def max_seq_length(self) -> int:
        return int(getattr(self.model, "max_seq_length", 256) or 256)

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        vectors = self.model.encode(list(texts), batch_size=64, convert_to_numpy=True)
        return [list(map(float, v)) for v in vectors]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _aggregate(vectors: Sequence[Sequence[float]], strategy: str) -> list[float]:
    if not vectors:
        return []
    if strategy == "first_chunk":
        return list(vectors[0])
    if strategy != "mean_chunks":
        raise ValueError(f"unknown aggregation strategy: {strategy!r}")
    width = len(vectors[0])
    return [sum(v[i] for v in vectors) / len(vectors) for i in range(width)]


def score_abstract_similarity(
    encoder: Optional[AbstractEncoder],
    abstract: Optional[str],
    labels: Sequence[str],
    *,
    aggregation: str = "mean_chunks",
) -> tuple[list[float], dict[str, Any]]:
    """Cosine similarity between a chunk-aggregated abstract and class labels.

    Returns ``(similarities, metadata)``. When no encoder or no abstract is
    available the similarities are all 0.0 and ``metadata["available"]`` is
    False; the caller must then not pretend a semantic score was computed.
    """
    metadata: dict[str, Any] = {
        "available": False,
        "encoder": getattr(encoder, "name", None) if encoder is not None else None,
        "max_seq_length": None,
        "chunk_strategy": "sentence_pack",
        "aggregation": aggregation,
        "abstract_chunks": 0,
        "note": (
            "Chunking removes character-level truncation of the abstract. Each "
            "chunk is still subject to the model's own token limit, so this is "
            "not a claim that the full abstract was processed losslessly."
        ),
    }
    if encoder is None or not abstract or not labels:
        return [0.0] * len(labels), metadata

    max_tokens = int(getattr(encoder, "max_seq_length", 256) or 256)
    metadata["max_seq_length"] = max_tokens
    chunks = chunk_text(abstract, max_tokens=max_tokens)
    if not chunks:
        return [0.0] * len(labels), metadata
    metadata["abstract_chunks"] = len(chunks)

    vectors = list(encoder.encode(list(chunks) + list(labels)))
    if len(vectors) != len(chunks) + len(labels):
        return [0.0] * len(labels), metadata
    abstract_vector = _aggregate(vectors[: len(chunks)], aggregation)
    metadata["available"] = True
    return [cosine(abstract_vector, v) for v in vectors[len(chunks) :]], metadata


# ---------------------------------------------------------------------------
# 8) IDENTITY, LOCAL KG MAPPING, REDIRECTS
# ---------------------------------------------------------------------------


def normalize_category(value: Optional[str]) -> Optional[str]:
    """Accept ``dbc:X`` / ``Category:X`` / a full category URI / a bare name.

    Returns the canonical full category URI, or None when the value cannot
    denote a DBpedia category. Validation is deliberately strict, because the
    result is interpolated into a SPARQL query:

      * the URI must begin with one of ``ALLOWED_CATEGORY_PREFIXES`` exactly, so
        another host (``https://evil.example/resource/Category:X``) and a
        resource URI that merely contains the substring
        (``.../resource/FooCategory:Bar``) are both rejected;
      * a local name may not contain ``/``, which would leave the category
        namespace;
      * anything containing whitespace, a control character, or a character
        that would terminate an IRI or a string literal (``<>"'{}|\\^`` `` ` ``)
        is rejected rather than escaped.

    A ``:`` inside the local name is legitimate and is preserved, so
    ``Category:Star_Trek:_Voyager_episodes`` is accepted. Only the *leading*
    ``dbc:`` or ``Category:`` token is treated as a prefix.
    """
    if value is None:
        return None
    raw = _strip_uri(str(value))
    if not raw:
        return None

    if "://" in raw or raw.lower().startswith(("http:", "https:", "ftp:", "file:")):
        if _UNSAFE_URI_CHARS.search(raw):
            return None
        for prefix in ALLOWED_CATEGORY_PREFIXES:
            if raw.startswith(prefix):
                local = raw[len(prefix) :]
                break
        else:
            return None
    else:
        if raw.startswith("dbc:"):
            local = raw[4:]
        elif raw.startswith("Category:"):
            local = raw[len("Category:") :]
        else:
            local = raw
        local = local.strip().replace(" ", "_")

    if not local or _UNSAFE_URI_CHARS.search(local):
        return None
    if "/" in local:
        return None
    candidate = CATEGORY_PREFIX + local
    return candidate if is_safe_uri(candidate) else None


def short_category(category_uri: str) -> str:
    bare = _strip_uri(category_uri)
    return "dbc:" + bare.split("Category:")[-1] if "Category:" in bare else bare


def category_local_name(category_uri: str) -> str:
    bare = _strip_uri(category_uri)
    return bare.split("Category:")[-1] if "Category:" in bare else _uri_local_name(bare)


def local_kg_key(local_index: Optional[Mapping[str, Any]], uri: str) -> Optional[str]:
    """Find the key under which ``uri`` appears in the local KG index.

    Both the angle-bracketed form used by the pickle and the bare form are
    tried. The index is only read; keys are never rewritten.
    """
    if local_index is None:
        return None
    bare = _strip_uri(uri)
    for key in (f"<{bare}>", bare):
        if key in local_index:
            return key
    return None


class RedirectQueryFailed(RuntimeError):
    """The redirect lookup itself failed, so nothing follows from it.

    This is the third state that a bare ``None`` used to swallow. "The endpoint
    answered and there is no redirect" licenses continuing with the original
    URI; "the endpoint did not answer" licenses nothing at all, and reporting it
    as an absence of categories would turn a transport failure into a data
    finding about the Answer.
    """

    def __init__(self, uri: str, error: Optional[str] = None) -> None:
        super().__init__(f"redirect query failed for {uri}: {error}")
        self.uri = uri
        self.error = error


class RedirectResolver(Protocol):
    def resolve(self, uri: str) -> Optional[str]:  # pragma: no cover - protocol
        ...


@dataclass
class SparqlRedirectResolver:
    """``dbo:wikiPageRedirects`` resolver. Never traverses ``owl:sameAs``.

    Returns ``None`` for a successful lookup that found no redirect, and raises
    :class:`RedirectQueryFailed` when the lookup could not be performed.
    """

    runner: SparqlRunner

    def resolve(self, uri: str) -> Optional[str]:
        result = self.runner.run(build_redirect_query(uri))
        if result.failed:
            raise RedirectQueryFailed(uri, result.error)
        if not result.rows:
            return None  # answered, and there is no redirect
        return _binding(result.rows[0], "target")


def _bind_redirect_resolver(
    resolver: Optional[RedirectResolver], runner: SparqlRunner
) -> Optional[RedirectResolver]:
    """Route the built-in resolver's query through this Answer's counter view.

    A resolver constructed over the caller's shared runner would otherwise query
    around the per-invocation wrapper, so its query would land in the batch total
    but not in the result that caused it.

    Rebinding is a counting concern only, so it happens exactly when it cannot
    change where the query goes: either ``runner`` already delegates to the
    resolver's own runner, or the two share the same client and cache objects. A
    custom resolver is never touched — it may hold state or a transport this
    module knows nothing about.
    """
    if not isinstance(resolver, SparqlRedirectResolver):
        return resolver
    existing = resolver.runner
    same_transport = _base_runner(existing) is _base_runner(runner) or (
        existing.client is runner.client and existing.cache is runner.cache
    )
    if not same_transport:
        return resolver
    return SparqlRedirectResolver(runner)


def resolve_query_uri(
    original_uri: str,
    *,
    resolver: Optional[RedirectResolver] = None,
    enabled: bool = False,
    max_hops: int = 1,
) -> tuple[str, bool]:
    """Return ``(query_uri, redirect_used)``.

    Disabled by default, at most ``max_hops`` hop, cycle protected, and it never
    touches ``owl:sameAs`` or any key of the local pickle.

    Raises :class:`RedirectQueryFailed` when the lookup could not be performed.
    Any other resolver exception is treated as "no redirect available" and
    contained here, because a custom resolver's internal errors say nothing
    about the endpoint.

    NOT VERIFIED AGAINST A LIVE ENDPOINT. This turn exercised it only against a
    test double; treat live behaviour as unverified until an integration run
    reports otherwise.
    """
    current = _strip_uri(original_uri)
    if not enabled or resolver is None or max_hops < 1:
        return current, False
    seen = {current}
    used = False
    for _ in range(max_hops):
        try:
            target = resolver.resolve(current)
        except RedirectQueryFailed:
            raise  # a transport failure is not evidence that no redirect exists
        except Exception:  # noqa: BLE001
            break
        if not target:
            break
        target = _strip_uri(target)
        if not is_safe_uri(target):
            break  # never follow a redirect into an unusable IRI
        if target in seen:
            break  # cycle protection
        seen.add(target)
        current = target
        used = True
    return current, used


# ---------------------------------------------------------------------------
# 9) RESULT STRUCTURES
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnswerInfo:
    original_uri: str
    query_uri: str
    label: Optional[str] = None
    abstract: Optional[str] = None
    categories: tuple[str, ...] = ()
    categories_truncated: bool = False
    member_of_requested_class: Optional[bool] = None
    query_status: QueryStatus = QueryStatus.OK
    error: Optional[str] = None
    redirect_used: bool = False


@dataclass(frozen=True)
class ClassCandidate:
    """One candidate class with its full audit trail.

    Two sizes are recorded and they mean different things:

    ``remote_count``
        the complete DBpedia size of the class, *including* the Answer. This is
        the value the class's information content is computed from, and the
        value the maximum-generic-class threshold is applied to.
    ``eligible_remote_count``
        how many remote entities could actually serve as distractors, i.e.
        ``remote_count`` minus the Answer itself. The minimum-candidate
        threshold is applied to this value, because a class whose only member
        is the Answer supplies no distractors at all.

    ``local_count`` follows the same convention as ``eligible_remote_count``:
    it never includes the Answer.
    """

    category_uri: str
    category_short: str
    display_label: str
    remote_count: Optional[int] = None
    eligible_remote_count: Optional[int] = None
    local_count: Optional[int] = None
    local_count_is_lower_bound: bool = False
    local_check: LocalCheck = LocalCheck.NOT_APPLICABLE
    members_truncated: bool = False
    raw_idf: float = 0.0
    normalized_idf: float = 0.0
    raw_sbert: float = 0.0
    normalized_sbert: float = 0.0
    combined_score: float = 0.0
    scored: bool = False
    leak_level: LeakLevel = LeakLevel.NONE
    leak_reason: Optional[str] = None
    feasible: bool = False
    rejected_reason: Optional[str] = None
    rejected_code: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category_uri": self.category_uri,
            "category_short": self.category_short,
            "display_label": self.display_label,
            "remote_count": self.remote_count,
            "eligible_remote_count": self.eligible_remote_count,
            "local_count": self.local_count,
            "local_count_is_lower_bound": self.local_count_is_lower_bound,
            "local_check": self.local_check.value,
            "members_truncated": self.members_truncated,
            "raw_idf": self.raw_idf,
            "normalized_idf": self.normalized_idf,
            "raw_sbert": self.raw_sbert,
            "normalized_sbert": self.normalized_sbert,
            "combined_score": self.combined_score,
            "scored": self.scored,
            "leak_level": self.leak_level.value,
            "leak_reason": self.leak_reason,
            "feasible": self.feasible,
            "rejected_reason": self.rejected_reason,
            "rejected_code": self.rejected_code,
        }


@dataclass(frozen=True)
class ClassSelectionResult:
    """Audit record for one Answer.

    ``recommended_classes`` holds only feasible classes, already ordered by the
    mode's policy and truncated to ``top_n``. ``evaluated_classes`` holds every
    candidate considered, including rejections, so that failure reasons can be
    counted for the yield-rate table.

    ``sparql_query_count`` and ``cache_stats`` describe **this Answer only**,
    even when one :class:`SparqlRunner` serves a whole batch; they are not the
    runner's running totals. ``sparql_query_count`` always equals
    ``cache_stats["queries"]``. For the batch total, read ``stats()`` on the
    runner that was passed in. This changed in schema version 3.2 — see
    :data:`SCHEMA_VERSION`.
    """

    original_uri: str
    query_uri: str
    local_kg_uri: Optional[str]
    display_label: str
    query_status: QueryStatus
    selection_status: SelectionStatus
    mode: str
    number_of_categories: int
    number_rejected_by_reason: Mapping[str, int]
    recommended_classes: tuple[ClassCandidate, ...]
    selected_class: Optional[str]
    redirect_used: bool
    number_inconclusive_by_reason: Mapping[str, int] = field(default_factory=dict)
    number_not_evaluated_by_reason: Mapping[str, int] = field(default_factory=dict)
    requested_class: Optional[str] = None
    categories_truncated: bool = False
    label_missing: bool = False
    sparql_query_count: int = 0
    cache_stats: Mapping[str, int] = field(default_factory=dict)
    encoder_metadata: Mapping[str, Any] = field(default_factory=dict)
    config: Mapping[str, Any] = field(default_factory=dict)
    evaluated_classes: tuple[ClassCandidate, ...] = ()
    schema_version: str = SCHEMA_VERSION
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.selection_status is SelectionStatus.OK

    @property
    def top_ranked_class(self) -> Optional[str]:
        return self.recommended_classes[0].category_uri if self.recommended_classes else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "original_uri": self.original_uri,
            "query_uri": self.query_uri,
            "local_kg_uri": self.local_kg_uri,
            "display_label": self.display_label,
            "query_status": self.query_status.value,
            "selection_status": self.selection_status.value,
            "mode": self.mode,
            "requested_class": self.requested_class,
            "number_of_categories": self.number_of_categories,
            "number_rejected_by_reason": dict(self.number_rejected_by_reason),
            "number_inconclusive_by_reason": dict(self.number_inconclusive_by_reason),
            "number_not_evaluated_by_reason": dict(self.number_not_evaluated_by_reason),
            "recommended_classes": [c.to_dict() for c in self.recommended_classes],
            "selected_class": self.selected_class,
            "redirect_used": self.redirect_used,
            "categories_truncated": self.categories_truncated,
            "label_missing": self.label_missing,
            "sparql_query_count": self.sparql_query_count,
            "cache_stats": dict(self.cache_stats),
            "encoder_metadata": dict(self.encoder_metadata),
            "config": dict(self.config),
            "evaluated_classes": [c.to_dict() for c in self.evaluated_classes],
            "error": self.error,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# 10) SELECTION
# ---------------------------------------------------------------------------


def fetch_answer_info(
    runner: SparqlRunner,
    answer_uri: str,
    *,
    original_uri: Optional[str] = None,
    language: str = DEFAULT_LANGUAGE,
    category_limit: int = DEFAULT_CATEGORY_LIMIT,
    membership_class: Optional[str] = None,
    fetch_categories: bool = True,
) -> AnswerInfo:
    """Label + abstract (one query) and, when requested, categories (one more)."""
    query_uri = _strip_uri(answer_uri)
    original = _strip_uri(original_uri or answer_uri)

    info_result = runner.run(
        build_answer_info_query(query_uri, language=language, membership_class=membership_class)
    )
    if info_result.failed:
        return AnswerInfo(
            original_uri=original,
            query_uri=query_uri,
            query_status=QueryStatus.FAILED,
            error=info_result.error,
        )

    label: Optional[str] = None
    abstract: Optional[str] = None
    member: Optional[bool] = False if membership_class else None
    for row in info_result.rows:
        label = label or _binding(row, "label")
        abstract = abstract or _binding(row, "abs")
        if membership_class and _binding(row, "member"):
            member = True

    categories: tuple[str, ...] = ()
    truncated = False
    status = info_result.status
    if fetch_categories:
        cat_result = runner.run(
            build_answer_categories_query(query_uri, limit=category_limit)
        )
        if cat_result.failed:
            return AnswerInfo(
                original_uri=original,
                query_uri=query_uri,
                label=label,
                abstract=abstract,
                member_of_requested_class=member,
                query_status=QueryStatus.FAILED,
                error=cat_result.error,
            )
        found = {
            _strip_uri(value)
            for value in (_binding(row, "cat") for row in cat_result.rows)
            if value
        }
        categories = tuple(sorted(found))
        truncated = len(cat_result.rows) >= category_limit
        if cat_result.ok:
            status = QueryStatus.OK

    return AnswerInfo(
        original_uri=original,
        query_uri=query_uri,
        label=label,
        abstract=abstract,
        categories=categories,
        categories_truncated=truncated,
        member_of_requested_class=member,
        query_status=status,
    )


def _fetch_category_counts(
    runner: SparqlRunner, category_uris: Sequence[str]
) -> tuple[dict[str, Optional[int]], bool]:
    """One grouped query for every category. Returns (counts, query_failed)."""
    counts: dict[str, Optional[int]] = {uri: None for uri in category_uris}
    if not category_uris:
        return counts, False
    result = runner.run(build_category_counts_query(category_uris))
    if result.failed:
        return counts, True
    known = {uri: 0 for uri in category_uris}
    for row in result.rows:
        cat = _strip_uri(_binding(row, "cat") or "")
        raw = _binding(row, "c")
        if cat in known and raw is not None:
            try:
                known[cat] = int(float(raw))
            except ValueError:
                known[cat] = 0
    return dict(known), False


@dataclass(frozen=True)
class LocalMemberCount:
    """How many members of one class were found in the local KG, and how sure.

    ``complete`` is True only when the class was enumerated exhaustively. When
    it is False the count is a *lower bound*: it may not be used to conclude
    that the class has too few local candidates.
    """

    count: int
    complete: bool
    pages: int

    @property
    def is_lower_bound(self) -> bool:
        return not self.complete

    def verdict(self, min_local_candidates: int) -> LocalCheck:
        if self.count >= min_local_candidates:
            return LocalCheck.CHECKED_FEASIBLE  # a lower bound already suffices
        if self.complete:
            return LocalCheck.CHECKED_INSUFFICIENT
        return LocalCheck.INCONCLUSIVE


def _excluded_local_keys(
    local_index: Mapping[str, Any], exclude_uris: Iterable[str]
) -> tuple[set[str], set[Any]]:
    """Both spellings of the entities that must not count as their own distractor.

    A URI is matched either directly or through its local-KG key, so an Answer
    reached via a redirect is excluded under both its original and its canonical
    URI even when the local index stores only one of them.
    """
    uris = {_strip_uri(u) for u in exclude_uris if u}
    keys = {
        key
        for key in (local_kg_key(local_index, uri) for uri in uris)
        if key is not None
    }
    return uris, keys


def _count_local_members(
    runner: SparqlRunner,
    category_uri: str,
    local_index: Mapping[str, Any],
    *,
    min_local_candidates: int,
    member_limit: int,
    max_pages: int,
    exclude_uris: Iterable[str] = (),
) -> tuple[LocalMemberCount, bool]:
    """Page through one class's members, stopping as soon as the answer is known.

    Deterministic keyset pagination over ``ORDER BY STR(?x)``. The loop stops
    early once ``min_local_candidates`` eligible local members have been seen
    (feasibility is then established from a lower bound), or when a short page
    proves the class was enumerated exhaustively. If the page budget runs out
    first the result is marked incomplete, never as a proven shortage.

    Two properties matter for correctness and are enforced here rather than
    assumed of the endpoint:

    * **Uniqueness.** A member repeated across pages is counted once. The
      duplicate test runs *before* the feasibility test, so a malformed endpoint
      that replays a page can never inflate the count past the threshold.
    * **Progress.** The next cursor is the maximum member URI on the page under
      the same string ordering the query uses. A cursor that is missing, or that
      does not strictly exceed its predecessor, means pagination stalled: that
      is evidence about the endpoint, not about the class, so the count remains
      a lower bound and the class stays unresolved.

    ``exclude_uris`` names entities that are not eligible distractors — in
    practice the Answer, under both its original and its query URI. Listing the
    same URI twice has no effect.

    Returns ``(count, query_failed)``.
    """
    excluded_uris, excluded_keys = _excluded_local_keys(local_index, exclude_uris)
    seen_member_uris: set[str] = set()
    count = 0
    pages = 0
    after: Optional[str] = None
    limit = max(1, int(member_limit))
    for _ in range(max(1, int(max_pages))):
        result = runner.run(
            build_class_members_query(category_uri, limit=limit, after=after)
        )
        if result.failed:
            return LocalMemberCount(count=count, complete=False, pages=pages), True
        pages += 1
        members = [_binding(row, "x") for row in result.rows]
        for member in members:
            if not member:
                continue
            uri = _strip_uri(member)
            if uri in seen_member_uris:
                continue
            seen_member_uris.add(uri)
            if uri in excluded_uris:
                continue
            key = local_kg_key(local_index, uri)
            if key is not None and key not in excluded_keys:
                count += 1
        if count >= min_local_candidates:
            return LocalMemberCount(count=count, complete=False, pages=pages), False
        if len(result.rows) < limit:
            return LocalMemberCount(count=count, complete=True, pages=pages), False
        cursor = max((_strip_uri(m) for m in members if m), default=None)
        if cursor is None or (after is not None and cursor <= after):
            return LocalMemberCount(count=count, complete=False, pages=pages), False
        after = cursor
    return LocalMemberCount(count=count, complete=False, pages=pages), False


def _probe_local_counts(
    runner: SparqlRunner,
    ordered_uris: Sequence[str],
    remote_counts: Mapping[str, Optional[int]],
    local_index: Mapping[str, Any],
    *,
    min_local_candidates: int,
    member_limit: int,
    max_member_rows: int,
    max_local_probes: int,
    max_member_pages: int,
    exclude_uris: Iterable[str] = (),
) -> tuple[dict[str, LocalMemberCount], bool]:
    """Determine the local candidate count for as many classes as the budget allows.

    Fast path: one batched query covering every class whose *entire* member list
    provably fits inside ``max_member_rows``, so a batched count is exact.
    Classes the batch cannot settle — because they did not fit, or because the
    returned rows do not account for the class's full remote size — fall back to
    per-class keyset pagination with early stopping.

    Classes beyond ``max_local_probes`` are simply absent from the returned
    mapping: the caller must report them as unchecked, not as infeasible.

    ``exclude_uris`` is forwarded to both paths so the Answer never counts as
    one of its own distractors, however the class happened to be probed.

    Returns ``(outcomes, query_failed)``.
    """
    attempt = list(ordered_uris)[: max(0, int(max_local_probes))]
    if not attempt:
        return {}, False
    excluded_uris, excluded_keys = _excluded_local_keys(local_index, exclude_uris)

    batch: list[str] = []
    budget_rows = 0
    for uri in attempt:
        expected = remote_counts.get(uri)
        if expected is None:
            continue
        if budget_rows + expected > max_member_rows:
            continue
        batch.append(uri)
        budget_rows += expected

    outcomes: dict[str, LocalMemberCount] = {}
    if batch:
        result = runner.run(build_class_members_batch_query(batch, limit=max_member_rows))
        if result.failed:
            return {}, True
        rows_seen = {uri: 0 for uri in batch}
        local_seen = {uri: 0 for uri in batch}
        seen_pairs: set[tuple[str, str]] = set()
        for row in result.rows:
            cat = _strip_uri(_binding(row, "cat") or "")
            member = _binding(row, "x")
            if cat not in rows_seen or not member:
                continue
            uri = _strip_uri(member)
            if (cat, uri) in seen_pairs:
                continue
            seen_pairs.add((cat, uri))
            # ``rows_seen`` is compared against the class's full remote size,
            # which includes the Answer, so the Answer's own row is counted
            # here. It is excluded only from the eligible distractor count.
            rows_seen[cat] += 1
            if uri in excluded_uris:
                continue
            key = local_kg_key(local_index, uri)
            if key is not None and key not in excluded_keys:
                local_seen[cat] += 1
        for uri in batch:
            expected = remote_counts.get(uri) or 0
            outcomes[uri] = LocalMemberCount(
                count=local_seen[uri],
                complete=rows_seen[uri] >= expected,
                pages=1,
            )

    for uri in attempt:
        settled = outcomes.get(uri)
        if settled is not None and settled.verdict(min_local_candidates) is not (
            LocalCheck.INCONCLUSIVE
        ):
            continue
        counted, failed = _count_local_members(
            runner,
            uri,
            local_index,
            min_local_candidates=min_local_candidates,
            member_limit=member_limit,
            max_pages=max_member_pages,
            exclude_uris=exclude_uris,
        )
        if failed:
            return {}, True
        outcomes[uri] = counted
    return outcomes, False


def _make_candidate(
    category_uri: str,
    *,
    remote_count: Optional[int] = None,
    total_entities: int = DEFAULT_TOTAL_ENTITIES,
    disambiguator_suffixes: Optional[Iterable[str]] = None,
) -> ClassCandidate:
    return ClassCandidate(
        category_uri=category_uri,
        category_short=short_category(category_uri),
        display_label=format_display_label(
            category_uri, disambiguator_suffixes=disambiguator_suffixes
        ),
        remote_count=remote_count,
        raw_idf=category_specificity(remote_count, total_entities=total_entities),
    )


def _reject(candidate: ClassCandidate, code: str, reason: str) -> ClassCandidate:
    return ClassCandidate(
        **{
            **candidate.__dict__,
            "feasible": False,
            "rejected_code": code,
            "rejected_reason": reason,
        }
    )


def _accept(candidate: ClassCandidate, **updates: Any) -> ClassCandidate:
    return ClassCandidate(**{**candidate.__dict__, **updates})


def _summarize_outcomes(
    candidates: Sequence[ClassCandidate],
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Split candidate outcomes into demonstrated / inconclusive / not evaluated.

    Returns ``(rejected, inconclusive, not_evaluated)``. Only the first bucket
    holds classes that were actually shown to fail a feasibility check; the
    other two hold classes whose evaluation did not complete and about which
    nothing may be concluded.
    """
    rejected: dict[str, int] = {}
    inconclusive: dict[str, int] = {}
    not_evaluated: dict[str, int] = {}
    for candidate in candidates:
        code = candidate.rejected_code
        if not code:
            continue
        if code in INCONCLUSIVE_REASON_CODES:
            bucket = inconclusive
        elif code in NOT_EVALUATED_REASON_CODES:
            bucket = not_evaluated
        else:
            bucket = rejected
        bucket[code] = bucket.get(code, 0) + 1
    return (
        dict(sorted(rejected.items())),
        dict(sorted(inconclusive.items())),
        dict(sorted(not_evaluated.items())),
    )


def has_unresolved_classes(candidates: Sequence[ClassCandidate]) -> bool:
    """True when at least one class was left unresolved rather than rejected."""
    return any(c.rejected_code in UNRESOLVED_REASON_CODES for c in candidates)


def _validate_selector_config(
    *,
    alpha: float,
    top_n: int,
    min_remote_candidates: int,
    max_remote_candidates: int,
    min_local_candidates: int,
    total_entities: int,
    category_limit: int,
    member_limit: int,
    max_member_rows: int,
    max_local_probes: int,
    max_member_pages: int,
    soft_leak_penalty: float,
    aggregation: str,
) -> None:
    """Reject an unusable configuration before a single query is issued.

    A run configured with, say, ``min_remote_candidates > max_remote_candidates``
    can only ever reject every class. Failing fast keeps that from being
    recorded as a measured result in the yield-rate table.
    """
    problems: list[str] = []
    if not 0.0 <= float(alpha) <= 1.0:
        problems.append(f"alpha must lie in [0, 1], got {alpha!r}")
    if int(top_n) < 1:
        problems.append(f"top_n must be >= 1, got {top_n!r}")
    for name, value in (
        ("min_remote_candidates", min_remote_candidates),
        ("max_remote_candidates", max_remote_candidates),
        ("min_local_candidates", min_local_candidates),
    ):
        if int(value) < 0:
            problems.append(f"{name} must be >= 0, got {value!r}")
    if int(min_remote_candidates) > int(max_remote_candidates):
        problems.append(
            f"min_remote_candidates ({min_remote_candidates}) must not exceed "
            f"max_remote_candidates ({max_remote_candidates})"
        )
    if int(total_entities) < 1:
        problems.append(f"total_entities must be >= 1, got {total_entities!r}")
    if int(category_limit) < 1:
        problems.append(f"category_limit must be >= 1, got {category_limit!r}")
    if int(member_limit) < 1:
        problems.append(f"member_limit must be >= 1, got {member_limit!r}")
    if int(max_member_rows) < 1:
        problems.append(f"max_member_rows must be >= 1, got {max_member_rows!r}")
    if int(max_local_probes) < 0:
        problems.append(f"max_local_probes must be >= 0, got {max_local_probes!r}")
    if int(max_member_pages) < 1:
        problems.append(f"max_member_pages must be >= 1, got {max_member_pages!r}")
    if float(soft_leak_penalty) < 0.0:
        problems.append(f"soft_leak_penalty must be >= 0, got {soft_leak_penalty!r}")
    if aggregation not in ("mean_chunks", "first_chunk"):
        problems.append(f"unknown aggregation strategy: {aggregation!r}")
    if problems:
        raise ValueError("invalid selector configuration: " + "; ".join(problems))


def first_feasible_order(
    candidates: Sequence[ClassCandidate], priority: Optional[Sequence[str]] = None
) -> list[ClassCandidate]:
    """Deterministic traversal order for ``first_feasible``.

    A lightweight deterministic selection rule, not an optimality claim and not
    an educational-quality ranking:

      1. an explicitly supplied candidate priority order is preserved;
      2. remaining classes are ordered by descending ``category_specificity``,
         so a narrower class is tried before a broader one;
      3. the category URI is the final tie-breaker only.
    """
    rank: dict[str, int] = {}
    if priority:
        for index, value in enumerate(priority):
            normalized = normalize_category(value)
            if normalized is not None and normalized not in rank:
                rank[normalized] = index
    fallback = len(rank)
    return sorted(
        candidates,
        key=lambda c: (rank.get(c.category_uri, fallback), -c.raw_idf, c.category_uri),
    )


def _score_candidates(
    candidates: Sequence[ClassCandidate],
    *,
    abstract: Optional[str],
    encoder: Optional[AbstractEncoder],
    alpha: float,
    aggregation: str,
    soft_leak_penalty: float,
) -> tuple[list[ClassCandidate], dict[str, Any]]:
    """Rank-normalise IDF and SBERT within this Answer, then combine."""
    if not candidates:
        return [], {"available": False}

    labels = [c.display_label for c in candidates]
    sbert_raw, metadata = score_abstract_similarity(
        encoder, abstract, labels, aggregation=aggregation
    )
    idf_raw = [c.raw_idf for c in candidates]
    idf_norm = _rank_normalize(idf_raw)
    available = bool(metadata.get("available"))
    sbert_norm = _rank_normalize(sbert_raw) if available else [0.0] * len(candidates)

    scored: list[ClassCandidate] = []
    for candidate, sr, sn, inorm in zip(candidates, sbert_raw, sbert_norm, idf_norm):
        # Without a usable abstract or encoder the recommendation score reduces
        # to normalised specificity; alpha is not silently applied to a zero.
        combined = alpha * sn + (1.0 - alpha) * inorm if available else inorm
        if candidate.leak_level is LeakLevel.SOFT:
            combined -= soft_leak_penalty
        scored.append(
            _accept(
                candidate,
                raw_sbert=float(sr),
                normalized_sbert=float(sn),
                normalized_idf=float(inorm),
                combined_score=float(combined),
                scored=True,
            )
        )
    return scored, metadata


def _result(
    *,
    info: AnswerInfo,
    mode: str,
    status: SelectionStatus,
    runner: SparqlRunner,
    config: Mapping[str, Any],
    display_label: str,
    local_kg_uri: Optional[str] = None,
    evaluated: Sequence[ClassCandidate] = (),
    recommended: Sequence[ClassCandidate] = (),
    selected: Optional[str] = None,
    requested_class: Optional[str] = None,
    encoder_metadata: Optional[Mapping[str, Any]] = None,
    error: Optional[str] = None,
) -> ClassSelectionResult:
    rejected_by_reason, inconclusive_by_reason, not_evaluated_by_reason = (
        _summarize_outcomes(evaluated)
    )
    return ClassSelectionResult(
        original_uri=info.original_uri,
        query_uri=info.query_uri,
        local_kg_uri=local_kg_uri,
        display_label=display_label,
        query_status=info.query_status,
        selection_status=status,
        mode=mode,
        number_of_categories=len(info.categories),
        number_rejected_by_reason=rejected_by_reason,
        number_inconclusive_by_reason=inconclusive_by_reason,
        number_not_evaluated_by_reason=not_evaluated_by_reason,
        recommended_classes=tuple(recommended),
        selected_class=selected,
        redirect_used=info.redirect_used,
        requested_class=requested_class,
        categories_truncated=info.categories_truncated,
        label_missing=not bool(info.label),
        sparql_query_count=runner.n_queries,
        cache_stats=runner.stats(),
        encoder_metadata=dict(encoder_metadata or {}),
        config=dict(config),
        evaluated_classes=tuple(evaluated),
        error=error or info.error,
    )


def select_candidate_classes(
    answer_uri: str,
    *,
    mode: str = "recommended",
    requested_class: Optional[str] = None,
    top_n: int = DEFAULT_TOP_N,
    local_index: Optional[Mapping[str, Any]] = None,
    cache: Optional[SparqlResponseCache] = None,
    client: Optional[SparqlClient] = None,
    runner: Optional[SparqlRunner] = None,
    resolve_redirects: bool = False,
    redirect_resolver: Optional[RedirectResolver] = None,
    encoder: Optional[AbstractEncoder] = None,
    nlp: Any = None,
    synonym_expander: Optional[Callable[[str], Iterable[str]]] = None,
    language: str = DEFAULT_LANGUAGE,
    min_remote_candidates: int = DEFAULT_MIN_REMOTE_CANDIDATES,
    max_remote_candidates: int = DEFAULT_MAX_REMOTE_CANDIDATES,
    min_local_candidates: int = DEFAULT_MIN_LOCAL_CANDIDATES,
    total_entities: int = DEFAULT_TOTAL_ENTITIES,
    alpha: float = DEFAULT_ALPHA,
    category_limit: int = DEFAULT_CATEGORY_LIMIT,
    member_limit: int = DEFAULT_MEMBER_LIMIT,
    max_member_rows: int = DEFAULT_MAX_MEMBER_ROWS,
    max_local_probes: int = DEFAULT_MAX_LOCAL_PROBES,
    max_member_pages: int = DEFAULT_MAX_MEMBER_PAGES,
    soft_leak_penalty: float = 0.0,
    aggregation: str = "mean_chunks",
    candidate_priority: Optional[Sequence[str]] = None,
    disambiguator_suffixes: Optional[Iterable[str]] = None,
) -> ClassSelectionResult:
    """Identify candidate classes for one Answer entity.

    Modes
    -----
    ``manual``
        Validate ``requested_class`` only: membership, remote candidate count,
        local candidate count when ``local_index`` is given, and hard leakage.
        A valid class is returned immediately without any ranking, which costs
        at most three SPARQL queries.
    ``recommended``
        Return up to ``top_n`` feasible classes ordered by a recommendation
        score, with every score component and every rejection reason recorded.
        The first entry is the top-ranked recommendation, not an optimum.
    ``first_feasible``
        Return the first class passing the hard feasibility checks, using the
        deterministic order documented in :func:`first_feasible_order`.

    A transport must be supplied explicitly through ``client`` or ``runner``.
    This function never constructs a network client on its own.

    Raises ``ValueError`` for an unusable ``mode``, a missing transport, or an
    ``answer_uri`` that is not a safe http(s) IRI. A *requested_class* that
    cannot denote a category is reported as ``manual_class_invalid`` instead,
    because that is a data outcome rather than a caller error.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if runner is None:
        if client is None:
            raise ValueError(
                "select_candidate_classes requires an explicit 'client' or 'runner'; "
                "use make_dbpedia_runner() to opt in to network access"
            )
        runner = SparqlRunner(client=client, cache=cache)
    # From here on every query goes through a per-invocation counter view, so
    # the counters this call reports describe this Answer and no other. The
    # caller's runner keeps its cumulative totals for the batch as a whole.
    runner = PerAnswerRunner(runner)
    _validate_selector_config(
        alpha=alpha,
        top_n=top_n,
        min_remote_candidates=min_remote_candidates,
        max_remote_candidates=max_remote_candidates,
        min_local_candidates=min_local_candidates,
        total_entities=total_entities,
        category_limit=category_limit,
        member_limit=member_limit,
        max_member_rows=max_member_rows,
        max_local_probes=max_local_probes,
        max_member_pages=max_member_pages,
        soft_leak_penalty=soft_leak_penalty,
        aggregation=aggregation,
    )
    _validate_iri(answer_uri, what="answer_uri")
    _validate_language(language)

    config = {
        "mode": mode,
        "language": language,
        "top_n": top_n,
        "alpha": alpha,
        "min_remote_candidates": min_remote_candidates,
        "max_remote_candidates": max_remote_candidates,
        "min_local_candidates": min_local_candidates,
        "total_entities": total_entities,
        "category_limit": category_limit,
        "member_limit": member_limit,
        "max_member_rows": max_member_rows,
        "max_local_probes": max_local_probes,
        "max_member_pages": max_member_pages,
        "soft_leak_penalty": soft_leak_penalty,
        "aggregation": aggregation,
        "resolve_redirects": resolve_redirects,
        "local_index_supplied": local_index is not None,
        "encoder_supplied": encoder is not None,
        "nlp_supplied": nlp is not None,
        "synonym_expander_supplied": synonym_expander is not None,
        "endpoint": runner.endpoint,
    }

    original_uri = _strip_uri(answer_uri)
    normalized_request = normalize_category(requested_class) if mode == "manual" else None

    # ``min_local_candidates == 0`` asks for no local guarantee at all, so the
    # requirement is vacuously satisfied: no member query is issued, no probe
    # budget is spent, no class is rejected for want of local members, and the
    # Answer need not appear in the local index. Supplying an index is then a
    # way to record local identity, not a constraint to satisfy.
    local_check_required = local_index is not None and int(min_local_candidates) > 0

    # -- manual mode: reject an unusable request before spending any query ---
    if mode == "manual":
        stub = AnswerInfo(original_uri=original_uri, query_uri=original_uri)
        if normalized_request is None:
            return _result(
                info=stub,
                mode=mode,
                status=SelectionStatus.MANUAL_CLASS_INVALID,
                runner=runner,
                config=config,
                display_label=format_display_label(
                    original_uri, disambiguator_suffixes=disambiguator_suffixes
                ),
                requested_class=requested_class,
                error="requested_class does not denote a DBpedia category",
            )
        if _JUNK_RE.search(category_local_name(normalized_request)):
            candidate = _reject(
                _make_candidate(
                    normalized_request,
                    total_entities=total_entities,
                    disambiguator_suffixes=disambiguator_suffixes,
                ),
                REASON_JUNK,
                "maintenance or administrative category",
            )
            return _result(
                info=stub,
                mode=mode,
                status=SelectionStatus.MANUAL_CLASS_INVALID,
                runner=runner,
                config=config,
                display_label=format_display_label(
                    original_uri, disambiguator_suffixes=disambiguator_suffixes
                ),
                evaluated=[candidate],
                requested_class=requested_class,
            )

    # -- 1) Answer identity and basic facts ---------------------------------
    # The authoritative redirect flag lives on ``info``; this local only tracks
    # which URI the next query should use.
    query_uri = original_uri
    info = fetch_answer_info(
        runner,
        query_uri,
        original_uri=original_uri,
        language=language,
        category_limit=category_limit,
        membership_class=normalized_request,
        fetch_categories=(mode != "manual"),
    )

    # Optional single-hop redirect.
    #
    # The trigger is whatever the mode actually needs and did not get. A missing
    # label is never sufficient on its own: a label is cosmetic, it is
    # reconstructed from the URI when absent, and spending a redirect query to
    # obtain one risks abandoning a URI whose substantive data is already in
    # hand.
    #
    # Ranking modes need subject categories. A redirect resource commonly keeps
    # an rdfs:label of its own while its dct:subject statements live only on the
    # canonical target, so zero categories is the trigger — and it is the only
    # trigger, because a URI that already yielded usable categories has nothing
    # to gain.
    #
    # Manual mode never fetches categories (``fetch_categories=False``), so its
    # decision rests entirely on membership of the requested class. Confirmed
    # membership therefore ends the matter; only an unconfirmed, unlabelled URI
    # is worth a redirect query. This also preserves the documented three-query
    # budget for ordinary entities.
    if mode == "manual":
        needs_redirect = not info.label and not info.member_of_requested_class
    else:
        needs_redirect = not info.categories
    if (
        resolve_redirects
        and redirect_resolver is not None
        and info.query_status is not QueryStatus.FAILED
        and needs_redirect
    ):
        def failed_here(
            *, uri: str, error: Optional[str], redirect_used: bool
        ) -> ClassSelectionResult:
            """A transport failure during redirect handling, reported as one."""
            return _result(
                info=AnswerInfo(
                    original_uri=original_uri,
                    query_uri=uri,
                    label=info.label,
                    abstract=info.abstract,
                    categories=info.categories,
                    categories_truncated=info.categories_truncated,
                    member_of_requested_class=info.member_of_requested_class,
                    query_status=QueryStatus.FAILED,
                    error=error,
                    redirect_used=redirect_used,
                ),
                mode=mode,
                status=SelectionStatus.QUERY_FAILED,
                runner=runner,
                config=config,
                display_label=format_display_label(
                    original_uri, rdfs_label=info.label, language=language,
                    disambiguator_suffixes=disambiguator_suffixes,
                ),
                requested_class=requested_class,
                error=error,
            )

        try:
            candidate_uri, used = resolve_query_uri(
                original_uri,
                resolver=_bind_redirect_resolver(redirect_resolver, runner),
                enabled=True,
                max_hops=1,
            )
        except RedirectQueryFailed as exc:
            # The lookup did not answer. Continuing would report "no subject
            # categories" — a claim about the Answer — on the strength of a
            # failed query.
            return failed_here(uri=query_uri, error=exc.error, redirect_used=False)
        if used and candidate_uri != query_uri:
            retried = fetch_answer_info(
                runner,
                candidate_uri,
                original_uri=original_uri,
                language=language,
                category_limit=category_limit,
                membership_class=normalized_request,
                fetch_categories=(mode != "manual"),
            )
            if retried.query_status is QueryStatus.FAILED:
                # The redirect was resolved but the canonical target could not
                # be read. Falling back to the original URI's successful
                # zero-category answer would silently substitute a data finding
                # for a transport failure, and would do so precisely for the
                # entities the redirect exists to repair.
                return failed_here(
                    uri=candidate_uri, error=retried.error, redirect_used=True
                )
            # Switch only when the target supplies what the original lacked,
            # judged by the same criterion that triggered the hop. Adopting a
            # target merely because it carries a label would rewrite
            # ``query_uri`` for a cosmetic gain, and in manual mode it would
            # discard a membership result the original had already settled.
            if mode == "manual":
                improved = bool(retried.member_of_requested_class)
            else:
                improved = bool(retried.categories) or (
                    not info.label and not info.categories and bool(retried.label)
                )
            if improved:  # a failed retry already returned above
                info = AnswerInfo(
                    original_uri=original_uri,
                    query_uri=candidate_uri,
                    label=retried.label,
                    abstract=retried.abstract,
                    categories=retried.categories,
                    categories_truncated=retried.categories_truncated,
                    member_of_requested_class=retried.member_of_requested_class,
                    query_status=retried.query_status,
                    redirect_used=True,
                )
                query_uri = candidate_uri

    display_label = format_display_label(
        original_uri, rdfs_label=info.label, language=language,
        disambiguator_suffixes=disambiguator_suffixes,
    )

    if info.query_status is QueryStatus.FAILED:
        return _result(
            info=info,
            mode=mode,
            status=SelectionStatus.QUERY_FAILED,
            runner=runner,
            config=config,
            display_label=display_label,
            requested_class=requested_class,
        )

    # -- 2) Local KG identity ------------------------------------------------
    local_uri = None
    if local_index is not None:
        local_uri = local_kg_key(local_index, query_uri) or local_kg_key(
            local_index, original_uri
        )
        if local_uri is None and local_check_required:
            return _result(
                info=info,
                mode=mode,
                status=SelectionStatus.LOCAL_URI_NOT_FOUND,
                runner=runner,
                config=config,
                display_label=display_label,
                requested_class=requested_class,
            )

    if mode == "manual":
        assert normalized_request is not None  # narrowed above
        return _select_manual(
            info=info,
            runner=runner,
            config=config,
            display_label=display_label,
            local_uri=local_uri,
            local_index=local_index,
            requested_class=requested_class,
            normalized_request=normalized_request,
            min_remote_candidates=min_remote_candidates,
            max_remote_candidates=max_remote_candidates,
            min_local_candidates=min_local_candidates,
            total_entities=total_entities,
            member_limit=member_limit,
            max_member_pages=max_member_pages,
            nlp=nlp,
            synonym_expander=synonym_expander,
            disambiguator_suffixes=disambiguator_suffixes,
        )

    # -- 3) No categories at all --------------------------------------------
    if not info.categories:
        status = (
            SelectionStatus.NO_LABEL
            if not info.label
            else SelectionStatus.NO_SUBJECT_CATEGORIES
        )
        return _result(
            info=info,
            mode=mode,
            status=status,
            runner=runner,
            config=config,
            display_label=display_label,
            local_kg_uri=local_uri,
            requested_class=requested_class,
        )

    # -- 4) Hard feasibility -------------------------------------------------
    evaluated: list[ClassCandidate] = []
    survivors: list[ClassCandidate] = []
    for category_uri in info.categories:
        # Endpoint-supplied values are validated before they can reach a query.
        canonical = normalize_category(category_uri)
        if canonical is None:
            evaluated.append(
                _reject(
                    ClassCandidate(
                        category_uri=category_uri,
                        category_short=category_uri,
                        display_label="",
                    ),
                    REASON_INVALID_URI,
                    "value does not denote a usable DBpedia category URI",
                )
            )
            continue
        category_uri = canonical
        candidate = _make_candidate(
            category_uri,
            total_entities=total_entities,
            disambiguator_suffixes=disambiguator_suffixes,
        )
        if _JUNK_RE.search(category_local_name(category_uri)):
            evaluated.append(
                _reject(candidate, REASON_JUNK, "maintenance or administrative category")
            )
            continue
        survivors.append(candidate)

    counts, counts_failed = _fetch_category_counts(
        runner, [c.category_uri for c in survivors]
    )
    if counts_failed:
        evaluated.extend(survivors)
        return _result(
            info=AnswerInfo(**{**info.__dict__, "query_status": QueryStatus.FAILED}),
            mode=mode,
            status=SelectionStatus.QUERY_FAILED,
            runner=runner,
            config=config,
            display_label=display_label,
            local_kg_uri=local_uri,
            evaluated=evaluated,
            requested_class=requested_class,
        )

    sized: list[ClassCandidate] = []
    for candidate in survivors:
        count = counts.get(candidate.category_uri)
        # Every class here came from the Answer's own dct:subject list, so the
        # Answer is necessarily one of the members and cannot be a distractor.
        eligible = None if count is None else max(count - 1, 0)
        candidate = _accept(
            candidate,
            remote_count=count,
            eligible_remote_count=eligible,
            raw_idf=category_specificity(count, total_entities=total_entities),
        )
        if count is None or eligible is None:
            evaluated.append(
                _reject(candidate, REASON_COUNT_UNAVAILABLE, "remote member count unavailable")
            )
        elif eligible < min_remote_candidates:
            evaluated.append(
                _reject(
                    candidate,
                    REASON_TOO_SMALL,
                    f"only {eligible} remote distractor candidates excluding the "
                    f"answer (< {min_remote_candidates}); class size {count}",
                )
            )
        elif count > max_remote_candidates:
            evaluated.append(
                _reject(
                    candidate,
                    REASON_TOO_GENERIC,
                    f"{count} remote members (> {max_remote_candidates})",
                )
            )
        else:
            sized.append(candidate)

    unleaked: list[ClassCandidate] = []
    answer_label_for_leak = info.label or display_label
    for candidate in sized:
        verdict = detect_leak(
            answer_label_for_leak,
            category_local_name(candidate.category_uri).replace("_", " "),
            nlp=nlp,
            synonym_expander=synonym_expander,
        )
        candidate = _accept(
            candidate, leak_level=verdict.level, leak_reason=verdict.reason
        )
        if verdict.is_hard:
            evaluated.append(
                _reject(candidate, REASON_HARD_LEAK, f"hard leak: {verdict.reason}")
            )
        else:
            unleaked.append(candidate)

    # -- 5) Local feasibility ------------------------------------------------
    # Skipped entirely when no local guarantee was requested, which leaves every
    # candidate's ``local_check`` at NOT_APPLICABLE: no check was required, so
    # none is reported as having been made.
    feasible: list[ClassCandidate] = unleaked
    if local_check_required and unleaked:
        probe_order = first_feasible_order(unleaked, candidate_priority)
        outcomes, probe_failed = _probe_local_counts(
            runner,
            [c.category_uri for c in probe_order],
            counts,
            local_index,
            min_local_candidates=min_local_candidates,
            member_limit=member_limit,
            max_member_rows=max_member_rows,
            max_local_probes=max_local_probes,
            max_member_pages=max_member_pages,
            exclude_uris=(query_uri, original_uri),
        )
        if probe_failed:
            evaluated.extend(unleaked)
            return _result(
                info=AnswerInfo(**{**info.__dict__, "query_status": QueryStatus.FAILED}),
                mode=mode,
                status=SelectionStatus.QUERY_FAILED,
                runner=runner,
                config=config,
                display_label=display_label,
                local_kg_uri=local_uri,
                evaluated=evaluated,
                requested_class=requested_class,
            )
        feasible = []
        for candidate in unleaked:
            outcome = outcomes.get(candidate.category_uri)
            if outcome is None:
                evaluated.append(
                    _reject(
                        _accept(candidate, local_check=LocalCheck.NOT_CHECKED_BUDGET),
                        REASON_LOCAL_NOT_PROBED,
                        "local membership was not checked within the configured probe "
                        "budget; this class is unevaluated, not shown to be infeasible",
                    )
                )
                continue
            verdict = outcome.verdict(min_local_candidates)
            candidate = _accept(
                candidate,
                local_count=outcome.count,
                local_count_is_lower_bound=outcome.is_lower_bound,
                local_check=verdict,
                members_truncated=outcome.is_lower_bound,
            )
            if verdict is LocalCheck.CHECKED_FEASIBLE:
                feasible.append(candidate)
            elif verdict is LocalCheck.CHECKED_INSUFFICIENT:
                evaluated.append(
                    _reject(
                        candidate,
                        REASON_LOCAL_TOO_FEW,
                        f"only {outcome.count} members in the local KG "
                        f"(< {min_local_candidates}), from a complete enumeration",
                    )
                )
            else:
                evaluated.append(
                    _reject(
                        candidate,
                        REASON_LOCAL_INCONCLUSIVE,
                        f"{outcome.count} local members observed over {outcome.pages} "
                        f"page(s) of an incomplete enumeration; the count is a lower "
                        "bound, so insufficiency is not established",
                    )
                )

    # -- 6) Recommendation ranking among feasible classes -------------------
    # first_feasible orders by supplied priority, then descending specificity,
    # then URI. It needs no recommendation score, so the encoder is neither
    # loaded nor called in that mode.
    if mode == "first_feasible":
        scored = [_accept(c, feasible=True) for c in feasible]
        encoder_metadata = {
            "available": False,
            "encoder": None,
            "note": (
                "not computed: first_feasible selects by priority, category "
                "specificity and URI order, so no abstract encoding is performed"
            ),
        }
    else:
        scored, encoder_metadata = _score_candidates(
            feasible,
            abstract=info.abstract,
            encoder=encoder,
            alpha=alpha,
            aggregation=aggregation,
            soft_leak_penalty=soft_leak_penalty,
        )
        scored = [_accept(c, feasible=True) for c in scored]

    if not scored:
        evaluated_all = evaluated
        # "Every class failed a completed check" and "no class was confirmed
        # because some check did not finish" are different findings.
        no_feasible_status = (
            SelectionStatus.NO_CONFIRMED_FEASIBLE_CLASS
            if has_unresolved_classes(evaluated_all)
            else SelectionStatus.ALL_CATEGORIES_REJECTED
        )
        return _result(
            info=info,
            mode=mode,
            status=no_feasible_status,
            runner=runner,
            config=config,
            display_label=display_label,
            local_kg_uri=local_uri,
            evaluated=evaluated_all,
            encoder_metadata=encoder_metadata,
            requested_class=requested_class,
        )

    if mode == "first_feasible":
        ordered = first_feasible_order(scored, candidate_priority)
    else:
        ordered = sorted(
            scored, key=lambda c: (-c.combined_score, c.category_uri)
        )

    recommended = ordered[: max(1, int(top_n))]
    return _result(
        info=info,
        mode=mode,
        status=SelectionStatus.OK,
        runner=runner,
        config=config,
        display_label=display_label,
        local_kg_uri=local_uri,
        evaluated=list(evaluated) + list(ordered),
        recommended=recommended,
        selected=recommended[0].category_uri,
        encoder_metadata=encoder_metadata,
        requested_class=requested_class,
    )


def _select_manual(
    *,
    info: AnswerInfo,
    runner: SparqlRunner,
    config: Mapping[str, Any],
    display_label: str,
    local_uri: Optional[str],
    local_index: Optional[Mapping[str, Any]],
    requested_class: Optional[str],
    normalized_request: str,
    min_remote_candidates: int,
    max_remote_candidates: int,
    min_local_candidates: int,
    total_entities: int,
    member_limit: int,
    max_member_pages: int,
    nlp: Any,
    synonym_expander: Optional[Callable[[str], Iterable[str]]],
    disambiguator_suffixes: Optional[Iterable[str]],
) -> ClassSelectionResult:
    """Validate one requested class. No ranking is performed."""
    candidate = _make_candidate(
        normalized_request,
        total_entities=total_entities,
        disambiguator_suffixes=disambiguator_suffixes,
    )

    def finish(status: SelectionStatus, evaluated: Sequence[ClassCandidate],
               selected: Optional[str] = None,
               recommended: Sequence[ClassCandidate] = ()) -> ClassSelectionResult:
        return _result(
            info=info,
            mode="manual",
            status=status,
            runner=runner,
            config=config,
            display_label=display_label,
            local_kg_uri=local_uri,
            evaluated=evaluated,
            recommended=recommended,
            selected=selected,
            requested_class=requested_class,
        )

    if not info.member_of_requested_class:
        return finish(
            SelectionStatus.MANUAL_CLASS_NOT_MEMBER,
            [
                _reject(
                    candidate,
                    "manual_class_not_member",
                    "the answer is not a dcterms:subject member of the requested class",
                )
            ],
        )

    counts, failed = _fetch_category_counts(runner, [normalized_request])
    if failed:
        return _result(
            info=AnswerInfo(**{**info.__dict__, "query_status": QueryStatus.FAILED}),
            mode="manual",
            status=SelectionStatus.QUERY_FAILED,
            runner=runner,
            config=config,
            display_label=display_label,
            local_kg_uri=local_uri,
            evaluated=[candidate],
            requested_class=requested_class,
        )
    count = counts.get(normalized_request)
    # Membership was confirmed above, so the Answer is known to be one of the
    # members and is subtracted only now, never before membership is settled.
    eligible = None if count is None else max(count - 1, 0)
    candidate = _accept(
        candidate,
        remote_count=count,
        eligible_remote_count=eligible,
        raw_idf=category_specificity(count, total_entities=total_entities),
    )
    if count is None or eligible is None:
        # Not a demonstrated defect of the class: the size was never measured.
        return finish(
            SelectionStatus.NO_CONFIRMED_FEASIBLE_CLASS,
            [_reject(candidate, REASON_COUNT_UNAVAILABLE, "remote member count unavailable")],
        )
    if eligible < min_remote_candidates:
        return finish(
            SelectionStatus.INSUFFICIENT_REMOTE_CANDIDATES,
            [
                _reject(
                    candidate,
                    REASON_TOO_SMALL,
                    f"only {eligible} remote distractor candidates excluding the "
                    f"answer (< {min_remote_candidates}); class size {count}",
                )
            ],
        )
    if count > max_remote_candidates:
        return finish(
            SelectionStatus.MANUAL_CLASS_INVALID,
            [
                _reject(
                    candidate,
                    REASON_TOO_GENERIC,
                    f"{count} remote members (> {max_remote_candidates})",
                )
            ],
        )

    verdict = detect_leak(
        info.label or display_label,
        category_local_name(normalized_request).replace("_", " "),
        nlp=nlp,
        synonym_expander=synonym_expander,
    )
    candidate = _accept(candidate, leak_level=verdict.level, leak_reason=verdict.reason)
    if verdict.is_hard:
        return finish(
            SelectionStatus.MANUAL_CLASS_INVALID,
            [_reject(candidate, REASON_HARD_LEAK, f"hard leak: {verdict.reason}")],
        )

    if local_index is not None and int(min_local_candidates) > 0:
        outcome, failed = _count_local_members(
            runner,
            normalized_request,
            local_index,
            min_local_candidates=min_local_candidates,
            member_limit=member_limit,
            max_pages=max_member_pages,
            exclude_uris=(info.query_uri, info.original_uri),
        )
        if failed:
            return _result(
                info=AnswerInfo(**{**info.__dict__, "query_status": QueryStatus.FAILED}),
                mode="manual",
                status=SelectionStatus.QUERY_FAILED,
                runner=runner,
                config=config,
                display_label=display_label,
                local_kg_uri=local_uri,
                evaluated=[candidate],
                requested_class=requested_class,
            )
        verdict = outcome.verdict(min_local_candidates)
        candidate = _accept(
            candidate,
            local_count=outcome.count,
            local_count_is_lower_bound=outcome.is_lower_bound,
            local_check=verdict,
            members_truncated=outcome.is_lower_bound,
        )
        if verdict is LocalCheck.CHECKED_INSUFFICIENT:
            return finish(
                SelectionStatus.INSUFFICIENT_LOCAL_CANDIDATES,
                [
                    _reject(
                        candidate,
                        REASON_LOCAL_TOO_FEW,
                        f"only {outcome.count} members in the local KG "
                        f"(< {min_local_candidates}), from a complete enumeration",
                    )
                ],
            )
        if verdict is LocalCheck.INCONCLUSIVE:
            return finish(
                SelectionStatus.LOCAL_CHECK_INCONCLUSIVE,
                [
                    _reject(
                        candidate,
                        REASON_LOCAL_INCONCLUSIVE,
                        f"{outcome.count} local members observed over {outcome.pages} "
                        f"page(s) of an incomplete enumeration; the count is a lower "
                        "bound, so insufficiency is not established",
                    )
                ],
            )

    accepted = _accept(candidate, feasible=True)
    return finish(SelectionStatus.OK, [accepted], selected=normalized_request,
                  recommended=[accepted])


# ---------------------------------------------------------------------------
# 11) COMPATIBILITY API
# ---------------------------------------------------------------------------


def rank_classes_for_answer(
    answer_uri: str, **kwargs: Any
) -> list[ClassCandidate]:
    """Return the feasible classes for an Answer, highest recommendation first.

    A thin wrapper over :func:`select_candidate_classes` in ``recommended``
    mode. The order expresses a recommendation score only; it is not a claim
    about pedagogical quality or global optimality.
    """
    kwargs.pop("mode", None)
    result = select_candidate_classes(answer_uri, mode="recommended", **kwargs)
    return list(result.recommended_classes)


def choose_best_class_for_answer(answer_uri: str, **kwargs: Any) -> Optional[str]:
    """DEPRECATED compatibility wrapper. Do not use in new code.

    Returns the URI of the top-ranked *recommended* class, or None.

    The name is retained only so that pre-v3 call sites keep working. It does
    **not** imply that the returned class is globally optimal, pedagogically
    best, or unique: no such objective is defined, measured, or proved anywhere
    in this project, and the precedent literature specifies the class manually
    or picks the most specific one by a fixed rule. Use
    :func:`select_candidate_classes` and read ``recommended_classes`` or
    ``selected_class`` instead.
    """
    warnings.warn(
        "choose_best_class_for_answer() is deprecated: it names an optimum that "
        "this project does not define. Use select_candidate_classes(...) and read "
        "selected_class or recommended_classes.",
        DeprecationWarning,
        stacklevel=2,
    )
    ranked = rank_classes_for_answer(answer_uri, **kwargs)
    return ranked[0].category_uri if ranked else None


def format_selection_report(result: ClassSelectionResult) -> str:
    """Compact human-readable summary of one selection. No optimality wording."""
    lines = [
        f"=== {result.original_uri} ({result.display_label}) ===",
        f"  mode={result.mode}  query={result.query_status.value}  "
        f"selection={result.selection_status.value}  queries={result.sparql_query_count}",
    ]
    for candidate in result.evaluated_classes:
        tag = "OK" if candidate.feasible else "XX"
        detail = "" if candidate.feasible else f"  <- {candidate.rejected_reason}"
        lines.append(
            f"  {tag} {candidate.category_short:<55} score={candidate.combined_score:.4f} "
            f"n={candidate.remote_count} eligible={candidate.eligible_remote_count} "
            f"local={candidate.local_count} "
            f"idf={candidate.raw_idf:.3f} sbert={candidate.raw_sbert:.3f}{detail}"
        )
    label = {
        "manual": "requested class",
        "recommended": "top-ranked recommendation",
        "first_feasible": "first feasible class",
    }[result.mode]
    lines.append(f"  => {label}: {result.selected_class}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 12) OFFLINE SELF-CHECK
#
# Deliberately performs no network access, loads no model, and opens no cache.
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    print(f"{SCHEMA_VERSION} — offline self-check (no network, no model, no cache)\n")
    print("display labels:")
    for sample, label in [
        ("http://dbpedia.org/resource/Makoto_Kobayashi_(physicist)", None),
        ("http://dbpedia.org/resource/Akira_Suzuki_(chemist)", None),
        ("http://dbpedia.org/resource/Phosphorus(V)", None),
        ("http://dbpedia.org/resource/Phosphorus(V)_oxide", None),
        ("http://dbpedia.org/resource/Iron(III)_chloride", None),
        ("http://dbpedia.org/resource/Vitamin_B12_(cobalamin)", None),
        ("http://dbpedia.org/resource/Vitamin_B12_(cobalamin)", "Vitamin B12"),
        ("http://dbpedia.org/resource/Kant%C5%8D_region", None),
    ]:
        rendered = format_display_label(sample, rdfs_label=label)
        print(f"  {_uri_local_name(sample):<34} label={label!r:<14} -> {rendered!r}")

    print("\nleak grading:")
    for answer, category in [
        ("Albert Einstein", "Albert Einstein Award"),
        ("Shinya Yamanaka", "Japanese Nobel laureates"),
    ]:
        verdict = detect_leak(answer, category)
        print(f"  {answer:<18} vs {category:<26} -> {verdict.level.value}")

    print("\nquery invariant (every LIMIT has an ORDER BY):")
    for name, query in sample_queries().items():
        has_limit = "LIMIT" in query
        has_order = "ORDER BY" in query
        state = "ok" if (not has_limit or has_order) else "VIOLATION"
        print(f"  {name:<28} limit={has_limit!s:<5} order_by={has_order!s:<5} {state}")
