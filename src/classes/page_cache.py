############################################################################
# src/classes/page_cache.py
#
# Resumable page cache (SQLite) and the SQLite-independent frozen replay export.
#
# THE ONE STRUCTURAL RULE
#   Successes and failures live in DIFFERENT TABLES. `pages` can only ever hold a
#   completely parsed, successfully retrieved page; `failures` is append-only and
#   is never consulted by get_page(). So "a failed response is not treated as a
#   successful cache hit" is not a policy the read path has to remember — there
#   is nowhere for a failure to be read back from.
#
# WHY NOT REUSE v4's CACHE
#   v4's `sparql_cache_v3.0` keys one row per query with columns
#   (query_hash, endpoint, language, response_json, query_status, retrieved_at).
#   It cannot express a class, a page index, a keyset cursor, an attempt count or
#   a failure class, and frozen category-selector artifacts already depend on that
#   schema. A separate schema version and a separate file are used instead, and
#   v4's cache file is never opened by this module.
#
# RESUME
#   The cache key is sha256(endpoint + "\n" + exact query text). Keyset
#   pagination makes page N's query text a deterministic function of page N-1's
#   last member, so re-running an interrupted retrieval regenerates exactly the
#   same key chain and every already-stored page is a hit. Nothing needs to
#   remember "where it was": the query text IS the position.
#
# FROZEN EXPORT
#   data/pilot_class_members_v1.jsonl is a plain, sorted, timestamp-free JSONL
#   file sufficient to replay the whole mapping without SQLite and without HTTP.
#   Timestamps are deliberately kept OUT of it and put in the manifest instead,
#   so the scientific result files can be required to be byte-identical between
#   the live run and the offline replay.
#
# IMPORT-TIME PURITY: no connection is opened and no file is created at import.
############################################################################

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from classes.sparql_client import (
    SCHEMA_VERSION,
    CacheOrigin,
    PageFailure,
    PageResult,
    PageState,
    iso_utc,
    query_id,
)

CACHE_SCHEMA_VERSION = SCHEMA_VERSION
REQUIRED_TABLES = frozenset({"pages", "failures", "meta"})

# JSON serialisation used for every frozen/scientific artifact in this task.
# sort_keys makes a record's bytes independent of dict construction order;
# ensure_ascii=False keeps Shin'ichirō_Tomonaga readable rather than \u-escaped;
# the compact separators remove trailing-whitespace ambiguity.
JSON_DUMP_KWARGS = {
    "ensure_ascii": False,
    "sort_keys": True,
    "separators": (",", ":"),
}


def dumps_canonical(obj: Any) -> str:
    """One canonical JSON spelling, so byte-identity is a testable property."""
    return json.dumps(obj, **JSON_DUMP_KWARGS)


class PageCacheError(Exception):
    """Base class for page-cache failures."""


class CacheSchemaMismatch(PageCacheError):
    """The file was not written by this schema version. Refused, not migrated."""


class FrozenExportError(PageCacheError):
    """The frozen replay export is missing, malformed, or incomplete."""


# --- SQLite cache ----------------------------------------------------------

class PageCache:
    """SQLite-backed resumable cache of successfully retrieved pages.

    The connection is opened on first use, never at import. A database that
    already has tables is validated COMPLETELY before anything is written to it,
    so a mistargeted path (for example v4's cache) is refused rather than
    silently gaining new tables.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        schema_version: str = CACHE_SCHEMA_VERSION,
        endpoint: str = "",
        create_parents: bool = True,
    ) -> None:
        self.path = Path(path)
        self.schema_version = schema_version
        self.endpoint = endpoint
        self._create_parents = create_parents
        self._conn: Optional[sqlite3.Connection] = None
        self.hit_count = 0
        self.miss_count = 0
        self.put_count = 0
        self.failure_count = 0

    # -- connection --------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if self._create_parents and str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path))

        def refuse(reason: str) -> CacheSchemaMismatch:
            conn.close()
            return CacheSchemaMismatch(f"{str(self.path)!r} {reason}")

        try:
            existing = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")
            }
        except sqlite3.DatabaseError as exc:
            raise refuse(f"is not a readable SQLite database: {exc}") from exc

        if existing:
            if "meta" not in existing:
                raise refuse(
                    f"contains tables {sorted(existing)} but no 'meta' table; "
                    f"refusing to write into a database written by another schema")
            try:
                row = conn.execute(
                    "SELECT value FROM meta WHERE key='schema_version'").fetchone()
            except sqlite3.DatabaseError as exc:
                raise refuse(f"has an unreadable 'meta' table: {exc}") from exc
            if row is None:
                raise refuse("records no schema_version; refusing to adopt a "
                             "cache of unknown provenance")
            if row[0] != self.schema_version:
                raise refuse(f"has schema_version {row[0]!r}, expected "
                             f"{self.schema_version!r}")
            missing = sorted(REQUIRED_TABLES - existing)
            if missing:
                raise refuse(f"declares schema_version {row[0]!r} but is missing "
                             f"table(s) {missing}; refusing to repair in place")
            self._conn = conn
            return conn

        self._create_schema(conn)
        self._conn = conn
        return conn

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        import time

        conn.executescript(
            """
            CREATE TABLE pages (
                query_fingerprint TEXT PRIMARY KEY,
                query_kind        TEXT    NOT NULL,
                endpoint          TEXT    NOT NULL,
                query_text        TEXT    NOT NULL,
                class_uri         TEXT,
                page_index        INTEGER,
                cursor_after      TEXT,
                page_size         INTEGER,
                page_state        TEXT    NOT NULL,
                http_status       INTEGER,
                row_count         INTEGER NOT NULL,
                rows_json         TEXT    NOT NULL,
                attempt_count     INTEGER NOT NULL,
                retrieved_at_epoch REAL   NOT NULL,
                retrieved_at_iso  TEXT    NOT NULL,
                schema_version    TEXT    NOT NULL
            );
            CREATE INDEX pages_by_class ON pages (class_uri, page_index);

            -- Append-only. Never read by get_page(); a retryable failure and a
            -- permanently malformed response are both recorded here so a partial
            -- verdict can name exactly which pages are missing and why.
            CREATE TABLE failures (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                query_fingerprint  TEXT    NOT NULL,
                query_kind         TEXT    NOT NULL,
                endpoint           TEXT    NOT NULL,
                class_uri          TEXT,
                page_index         INTEGER,
                failure_class      TEXT    NOT NULL,
                http_status        INTEGER,
                error_kind         TEXT,
                error_detail       TEXT,
                attempt_count      INTEGER NOT NULL,
                attempts_json      TEXT    NOT NULL,
                observed_at_epoch  REAL    NOT NULL,
                observed_at_iso    TEXT    NOT NULL,
                schema_version     TEXT    NOT NULL
            );
            CREATE INDEX failures_by_fingerprint ON failures (query_fingerprint);

            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        conn.executemany(
            "INSERT OR REPLACE INTO meta VALUES (?,?)",
            [
                ("schema_version", self.schema_version),
                ("created_at_epoch", str(time.time())),
                ("created_at_iso", iso_utc(time.time())),
                ("endpoint", self.endpoint),
            ],
        )
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "PageCache":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- results -----------------------------------------------------------

    def get_page(self, fingerprint: str) -> Optional[PageResult]:
        """A previously stored SUCCESSFUL page, or None. Never returns a failure."""
        conn = self._connect()
        row = conn.execute(
            "SELECT query_kind, endpoint, query_text, class_uri, page_index,"
            " cursor_after, page_size, page_state, http_status, rows_json,"
            " attempt_count, retrieved_at_epoch, retrieved_at_iso"
            " FROM pages WHERE query_fingerprint=?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            self.miss_count += 1
            return None
        self.hit_count += 1
        return PageResult(
            query_kind=row[0],
            query_fingerprint=fingerprint,
            query_text=row[2],
            endpoint=row[1],
            class_uri=row[3],
            page_index=row[4],
            cursor_after=row[5],
            page_size=row[6],
            page_state=row[7],
            http_status=row[8],
            rows=tuple(json.loads(row[9])),
            attempt_count=row[10],
            attempts=(),          # attempt detail belongs to the run that made it
            cache_origin=CacheOrigin.CACHE_HIT.value,
            retrieved_at_epoch=row[11],
            retrieved_at_iso=row[12],
        )

    def put_page(self, page: PageResult) -> bool:
        """Store a successful page. Refuses anything that is not one.

        The guard is a raise rather than a silent False: a caller reaching here
        with a non-success has a bug, and swallowing it would let an unretrieved
        page masquerade as retrieved on the next run.
        """
        valid_states = {s.value for s in PageState}
        if page.page_state not in valid_states:
            raise PageCacheError(
                f"refusing to cache page_state {page.page_state!r}; only "
                f"{sorted(valid_states)} are successful outcomes")
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                page.query_fingerprint,
                page.query_kind,
                page.endpoint,
                page.query_text,
                page.class_uri,
                page.page_index,
                page.cursor_after,
                page.page_size,
                page.page_state,
                page.http_status,
                page.row_count,
                json.dumps([dict(r) for r in page.rows], **JSON_DUMP_KWARGS),
                page.attempt_count,
                page.retrieved_at_epoch,
                page.retrieved_at_iso,
                self.schema_version,
            ),
        )
        conn.commit()
        self.put_count += 1
        return True

    def record_failure(self, failure: PageFailure) -> None:
        """Append a failure. Goes nowhere near `pages`."""
        conn = self._connect()
        conn.execute(
            "INSERT INTO failures (query_fingerprint, query_kind, endpoint,"
            " class_uri, page_index, failure_class, http_status, error_kind,"
            " error_detail, attempt_count, attempts_json, observed_at_epoch,"
            " observed_at_iso, schema_version)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                failure.query_fingerprint,
                failure.query_kind,
                failure.endpoint,
                failure.class_uri,
                failure.page_index,
                failure.failure_class,
                failure.http_status,
                failure.error_kind,
                failure.error_detail,
                failure.attempt_count,
                json.dumps([a.as_record() for a in failure.attempts],
                           **JSON_DUMP_KWARGS),
                failure.observed_at_epoch,
                failure.observed_at_iso,
                self.schema_version,
            ),
        )
        conn.commit()
        self.failure_count += 1

    # -- reporting ---------------------------------------------------------

    def meta(self) -> dict[str, str]:
        conn = self._connect()
        return {k: v for k, v in conn.execute("SELECT key, value FROM meta")}

    def page_count(self) -> int:
        conn = self._connect()
        return int(conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0])

    def stored_failure_count(self) -> int:
        conn = self._connect()
        return int(conn.execute("SELECT COUNT(*) FROM failures").fetchone()[0])

    def inventory(self) -> dict:
        """A cache_inventory.json payload: counts and per-class page tallies."""
        conn = self._connect()
        by_state = {
            state: int(count) for state, count in conn.execute(
                "SELECT page_state, COUNT(*) FROM pages GROUP BY page_state"
                " ORDER BY page_state")
        }
        by_kind = {
            kind: int(count) for kind, count in conn.execute(
                "SELECT query_kind, COUNT(*) FROM pages GROUP BY query_kind"
                " ORDER BY query_kind")
        }
        per_class = [
            {"class_uri": class_uri, "page_count": int(pages),
             "row_total": int(rows or 0)}
            for class_uri, pages, rows in conn.execute(
                "SELECT class_uri, COUNT(*), SUM(row_count) FROM pages"
                " WHERE class_uri IS NOT NULL GROUP BY class_uri"
                " ORDER BY class_uri")
        ]
        failures = [
            {"failure_class": failure_class, "count": int(count)}
            for failure_class, count in conn.execute(
                "SELECT failure_class, COUNT(*) FROM failures"
                " GROUP BY failure_class ORDER BY failure_class")
        ]
        size = self.path.stat().st_size if self.path.is_file() else 0
        return {
            "path": str(self.path),
            "schema_version": self.schema_version,
            "size_bytes": size,
            "meta": self.meta(),
            "cached_page_count": self.page_count(),
            "cached_pages_by_state": by_state,
            "cached_pages_by_query_kind": by_kind,
            "recorded_failure_count": self.stored_failure_count(),
            "recorded_failures_by_class": failures,
            "per_class_pages": per_class,
            "session_counters": {
                "hits": self.hit_count,
                "misses": self.miss_count,
                "pages_stored": self.put_count,
                "failures_recorded": self.failure_count,
            },
        }


# --- Frozen replay export --------------------------------------------------

RECORD_TYPE_CLASS_MEMBERS = "class_members"
RECORD_TYPE_REDIRECT = "redirect"


@dataclass(frozen=True)
class FrozenClassMembers:
    """The complete retrieved member set of one approved class.

    Carries the raw row tallies as well as the deduplicated member list, so a
    replay reproduces `raw_member_count` exactly instead of re-deriving a number
    it cannot see. Without them, the retrieval columns of the scientific result
    files could not be byte-identical between the live run and the replay.
    """

    class_uri: str
    member_uris: tuple[str, ...]
    page_count: int
    page_size: int
    retrieval_complete: bool
    raw_member_count: int = 0
    duplicate_row_count: int = 0
    non_iri_row_count: int = 0
    incomplete_reason: Optional[str] = None

    def as_record(self) -> dict:
        return {
            "record_type": RECORD_TYPE_CLASS_MEMBERS,
            "class_uri": self.class_uri,
            "member_uris": list(self.member_uris),
            "unique_member_count": len(self.member_uris),
            "raw_member_count": self.raw_member_count,
            "duplicate_row_count": self.duplicate_row_count,
            "non_iri_row_count": self.non_iri_row_count,
            "page_count": self.page_count,
            "page_size": self.page_size,
            "retrieval_complete": self.retrieval_complete,
            "incomplete_reason": self.incomplete_reason,
        }


@dataclass(frozen=True)
class FrozenRedirect:
    """One redirect observation.

    `target_uri is None` means the endpoint ANSWERED and there is no redirect —
    a positive observation. A source that was never queried is simply absent from
    the export, which is a third, distinguishable state.
    """

    source_uri: str
    target_uri: Optional[str]

    def as_record(self) -> dict:
        return {
            "record_type": RECORD_TYPE_REDIRECT,
            "source_uri": self.source_uri,
            "target_uri": self.target_uri,
        }


@dataclass(frozen=True)
class FrozenExport:
    """Everything the mapping stage needs, with no SQLite and no network."""

    class_members: Mapping[str, FrozenClassMembers]
    redirects: Mapping[str, Optional[str]]
    queried_redirect_sources: frozenset[str]

    @property
    def class_count(self) -> int:
        return len(self.class_members)

    def members_for(self, class_uri: str) -> FrozenClassMembers:
        try:
            return self.class_members[class_uri]
        except KeyError:
            raise FrozenExportError(
                f"frozen export has no member record for class {class_uri!r}; "
                f"it holds {len(self.class_members)} class(es)"
            ) from None


def write_frozen_export(
    path: str | Path,
    class_members: Sequence[FrozenClassMembers],
    redirects: Sequence[FrozenRedirect],
) -> Path:
    """Write the timestamp-free, deterministically ordered replay export.

    Ordering is fixed (class records by class URI, then redirect records by source
    URI) and no timestamp appears anywhere, so two runs over the same retrieved
    data produce byte-identical files.
    """
    target = Path(path)
    if str(target.parent) not in ("", "."):
        target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for record in sorted(class_members, key=lambda r: r.class_uri):
        lines.append(dumps_canonical(record.as_record()))
    for redirect in sorted(redirects, key=lambda r: r.source_uri):
        lines.append(dumps_canonical(redirect.as_record()))
    target.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return target


def load_frozen_export(path: str | Path) -> FrozenExport:
    """Load the frozen export, refusing a malformed or contradictory file."""
    source = Path(path)
    if not source.is_file():
        raise FrozenExportError(f"frozen replay export not found: {source}")

    members: dict[str, FrozenClassMembers] = {}
    redirects: dict[str, Optional[str]] = {}
    for lineno, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        text = line.strip()
        if not text:
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError as exc:
            raise FrozenExportError(f"{source.name} line {lineno}: invalid JSON: "
                                    f"{exc}") from exc
        if not isinstance(record, dict):
            raise FrozenExportError(f"{source.name} line {lineno}: not an object")
        kind = record.get("record_type")
        if kind == RECORD_TYPE_CLASS_MEMBERS:
            class_uri = record.get("class_uri")
            member_uris = record.get("member_uris")
            if not isinstance(class_uri, str) or not isinstance(member_uris, list):
                raise FrozenExportError(
                    f"{source.name} line {lineno}: malformed class_members record")
            if class_uri in members:
                raise FrozenExportError(
                    f"{source.name} line {lineno}: duplicate class_members record "
                    f"for {class_uri!r}")
            incomplete_reason = record.get("incomplete_reason")
            members[class_uri] = FrozenClassMembers(
                class_uri=class_uri,
                member_uris=tuple(str(u) for u in member_uris),
                page_count=int(record.get("page_count", 0)),
                page_size=int(record.get("page_size", 0)),
                retrieval_complete=bool(record.get("retrieval_complete", False)),
                raw_member_count=int(record.get("raw_member_count", 0)),
                duplicate_row_count=int(record.get("duplicate_row_count", 0)),
                non_iri_row_count=int(record.get("non_iri_row_count", 0)),
                incomplete_reason=(None if incomplete_reason is None
                                   else str(incomplete_reason)),
            )
        elif kind == RECORD_TYPE_REDIRECT:
            source_uri = record.get("source_uri")
            if not isinstance(source_uri, str):
                raise FrozenExportError(
                    f"{source.name} line {lineno}: malformed redirect record")
            target_uri = record.get("target_uri")
            if target_uri is not None and not isinstance(target_uri, str):
                raise FrozenExportError(
                    f"{source.name} line {lineno}: redirect target must be a "
                    f"string or null")
            if source_uri in redirects and redirects[source_uri] != target_uri:
                raise FrozenExportError(
                    f"{source.name} line {lineno}: contradictory redirect records "
                    f"for {source_uri!r}")
            redirects[source_uri] = target_uri
        else:
            raise FrozenExportError(
                f"{source.name} line {lineno}: unknown record_type {kind!r}")

    return FrozenExport(
        class_members=members,
        redirects=redirects,
        queried_redirect_sources=frozenset(redirects),
    )
