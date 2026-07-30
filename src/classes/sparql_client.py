############################################################################
# src/classes/sparql_client.py
#
# A NARROW DBpedia SPARQL client for one job: retrieving the members of an
# approved category class, and resolving dbo:wikiPageRedirects for members that
# do not match the pinned local KG exactly.
#
# WHY THIS IS NOT src/category_extractor_ClaudeWeb_v4.py's CLIENT
#   v4's DBpediaSparqlClient was inspected and deliberately not reused as the
#   transport. Three concrete reasons, not style preferences:
#
#   1. v4 goes through SPARQLWrapper and catches a bare `Exception`, so HTTP 429,
#      502 and a malformed JSON body all collapse into one FAILED state with a
#      repr() string. This task must record the HTTP status and must treat a
#      retryable 503 differently from a permanently malformed body.
#   2. SPARQLWrapper.setTimeout() is a single timeout. This task requires
#      explicit, separate connect and read timeouts.
#   3. v4's cache (schema `sparql_cache_v3.0`, tables `responses`/`meta`) keys one
#      row per query and has no notion of a class, a page index, a cursor, an
#      attempt count or a failure class. Retrofitting resumable page state into
#      it would mean altering a cache schema that frozen category-selector
#      artifacts depend on.
#
#   What IS reused, and only as pure functions re-derived here rather than
#   imported: v4's SPARQL-injection defence (validate an interpolated IRI against
#   the SPARQL 1.1 IRIREF grammar and refuse it rather than escape it), its
#   keyset pagination discipline (FILTER(STR(?x) > cursor) paired with
#   ORDER BY STR(?x), never OFFSET), and its bracketed-vs-bare local-key lookup.
#   v4 itself is NOT imported: it is a 3,600-line module carrying SBERT, NLTK and
#   scoring machinery, and importing it would couple this narrow layer's test
#   surface to all of it. The shared behaviours are covered by tests here.
#
# NETWORK SCOPE
#   Exactly one host is reachable: https://dbpedia.org/sparql. Any other endpoint
#   raises EndpointNotAllowedError. No model download, no Wikidata, no GitHub.
#
# NEVER
#   * cache a failed, partial or malformed response as a successful result;
#   * treat "the endpoint did not answer" as "the class has no members";
#   * follow owl:sameAs (that would substitute a different KG's entity — outside
#     the approved candidate-pool definition, CLAUDE.md boundary 6/7).
#
# IMPORT-TIME PURITY
#   No network, no sqlite connection, no filesystem write, no model load. The
#   `requests` import is lazy, inside RequestsHttpTransport.
############################################################################

from __future__ import annotations

import hashlib
import json
import random
import re
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Optional, Protocol, Sequence

# --- The single authorized endpoint ---------------------------------------
DBPEDIA_ENDPOINT = "https://dbpedia.org/sparql"
ALLOWED_ENDPOINTS = (DBPEDIA_ENDPOINT,)

DEFAULT_USER_AGENT = (
    "mcq-journal2-pilot-class-member-mapping/1.0 "
    "(academic research; DBpedia English category-member retrieval; "
    "9-Answer engineering pilot; contact via repository maintainer)"
)

# Separate connect and read budgets: a refused TCP handshake and a Virtuoso query
# that is merely slow are different problems and deserve different patience.
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_READ_TIMEOUT = 120.0

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BACKOFF_BASE_SECONDS = 1.0
DEFAULT_BACKOFF_CAP_SECONDS = 30.0
DEFAULT_JITTER_FRACTION = 0.25

# Virtuoso caps a single result set well below this, and every approved pilot
# class is small, so one page is normally enough. Pagination exists so that a
# larger class cannot be silently truncated.
DEFAULT_PAGE_SIZE = 1000
DEFAULT_MAX_PAGES = 25
DEFAULT_REDIRECT_BATCH_SIZE = 50
DEFAULT_MAX_REDIRECT_HOPS = 3

# Statuses worth another attempt: rate limiting and the Virtuoso 5xx family.
RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})

SCHEMA_VERSION = "pilot_class_member_mapping_v1"

CATEGORY_PREFIX = "http://dbpedia.org/resource/Category:"
RESOURCE_PREFIX = "http://dbpedia.org/resource/"

_PREFIXES = (
    "PREFIX dcterms: <http://purl.org/dc/terms/>\n"
    "PREFIX dbo:     <http://dbpedia.org/ontology/>"
)

QID_PREFIX = "#qid:"
QID_CLASS_MEMBERS_PAGE = "class_members_page"
QID_REDIRECT_BATCH = "redirect_batch"


# --- Query kinds -----------------------------------------------------------
class QueryKind(str, Enum):
    CLASS_MEMBERS_PAGE = "class_members_page"
    REDIRECT_BATCH = "redirect_batch"


# --- Outcome vocabulary ----------------------------------------------------
class PageState(str, Enum):
    """How a SUCCESSFUL page ended. Only these are ever cached as results.

    A zero-row page is a real, citable observation ("the endpoint answered and
    there is nothing after this cursor") and is kept distinct from a failure so
    that an empty class can never be confused with an unreachable one.
    """

    PAGE_COMPLETE = "PAGE_COMPLETE"
    PAGE_COMPLETE_ZERO_ROWS = "PAGE_COMPLETE_ZERO_ROWS"


class FailureClass(str, Enum):
    """How a FAILED attempt ended. Never stored in the results table."""

    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    PERMANENT_MALFORMED_RESPONSE = "PERMANENT_MALFORMED_RESPONSE"
    PERMANENT_QUERY_REJECTED = "PERMANENT_QUERY_REJECTED"


class CacheOrigin(str, Enum):
    """Where a page's rows actually came from, recorded on every page."""

    LIVE_HTTP = "LIVE_HTTP"
    CACHE_HIT = "CACHE_HIT"
    FROZEN_EXPORT = "FROZEN_EXPORT"


# Machine-readable error kinds. Never prose, so a consumer can branch on them.
ERROR_KIND_HTTP_STATUS = "http_status"
ERROR_KIND_CONNECT_TIMEOUT = "connect_timeout"
ERROR_KIND_READ_TIMEOUT = "read_timeout"
ERROR_KIND_CONNECTION_ERROR = "connection_error"
ERROR_KIND_MALFORMED_JSON = "malformed_json"
ERROR_KIND_MALFORMED_SPARQL_RESULTS = "malformed_sparql_results"
ERROR_KIND_TRANSPORT_EXCEPTION = "transport_exception"


# --- Typed errors ----------------------------------------------------------

class SparqlClientError(Exception):
    """Base class for every failure raised by this narrow client."""


class EndpointNotAllowedError(SparqlClientError):
    """An endpoint outside ALLOWED_ENDPOINTS was requested.

    Network authorization for this task is one host. Making that a raised error
    rather than a comment means a typo or an environment variable cannot quietly
    widen the approved network scope.
    """


class OfflineNetworkAttemptError(SparqlClientError):
    """Strict offline mode tried to make an HTTP call.

    Raised by OfflineTransport. The offline replay's "zero HTTP calls" claim is
    enforced structurally: there is no socket to fall back to.
    """


class UnsafeUriError(SparqlClientError, ValueError):
    """A URI cannot be safely interpolated into a SPARQL query."""


class PageRetrievalFailed(SparqlClientError):
    """One page could not be retrieved after the bounded retry budget.

    Carries the failure record so a caller can preserve the successful cache and
    report LOCAL_CLASS_MAPPING_PARTIAL_RETRY_REQUIRED instead of crashing.
    """

    def __init__(self, message: str, failure: "PageFailure") -> None:
        super().__init__(message)
        self.failure = failure


# --- Transport-level errors (raised by a transport, mapped by the client) ---
# Defined here, not imported from `requests`, so a unit-test double can simulate
# a connect timeout without any HTTP library installed.

class TransportError(SparqlClientError):
    error_kind = ERROR_KIND_TRANSPORT_EXCEPTION


class TransportConnectTimeout(TransportError):
    error_kind = ERROR_KIND_CONNECT_TIMEOUT


class TransportReadTimeout(TransportError):
    error_kind = ERROR_KIND_READ_TIMEOUT


class TransportConnectionError(TransportError):
    error_kind = ERROR_KIND_CONNECTION_ERROR


# --- URI handling ----------------------------------------------------------
# CONTEXT A of v4's split validation: a value interpolated between < and >.
# SPARQL 1.1 grammar rule [139]: '<' ([^<>"{}|^`\] - [#x00-#x20])* '>'.
# The apostrophe is deliberately absent from the forbidden set — it terminates
# neither an IRIREF nor a double-quoted literal, and refusing it would reject
# <http://dbpedia.org/resource/Shin'ichirō_Tomonaga>, pilot slot 2.
_UNSAFE_IRIREF_CHARS = re.compile(r"""[\s<>"{}|\\^`]|[\x00-\x20\x7f-\x9f]""")

# CONTEXT B: a value inside a double-quoted SPARQL literal (the keyset cursor).
_UNSAFE_LITERAL_CHARS = re.compile(r"""["\\]|[\x00-\x1f\x7f-\x9f]""")

_SCHEME_RE = re.compile(r"^https?://[^/]+/")


def strip_uri_brackets(uri: Optional[str]) -> str:
    """Normalize away surrounding whitespace and angle brackets.

    The pinned pickle stores keys as ``<http://...>`` while SPARQL JSON returns
    bare IRIs, so both spellings circulate. This produces the bare form and is
    the ONLY normalization applied before a URI is recorded: percent-decoding or
    Unicode re-composition would produce a DIFFERENT RDF term, so those are
    handled as explicitly labelled lookup alternatives (see
    ``local_lookup_forms``) rather than as silent rewrites.
    """
    return (uri or "").strip().strip("<>").strip()


def is_safe_iri(value: Optional[str]) -> bool:
    """True when `value` is an http(s) IRI safe to place inside ``<...>``.

    A value that passes is interpolated VERBATIM. It is never percent-encoded,
    because a percent-encoded spelling is a different RDF term, not an encoding
    of the same one.
    """
    if not value:
        return False
    text = strip_uri_brackets(str(value))
    if not text or _UNSAFE_IRIREF_CHARS.search(text):
        return False
    return bool(_SCHEME_RE.match(text))


def is_safe_literal(value: Optional[str]) -> bool:
    """True when `value` can be placed inside a double-quoted SPARQL literal."""
    if value is None:
        return False
    text = str(value)
    return bool(text) and not _UNSAFE_LITERAL_CHARS.search(text)


def validate_iri(value: Optional[str], *, what: str = "URI") -> str:
    """Return the bare safe IRI, or raise. Refuse rather than escape."""
    if not is_safe_iri(value):
        raise UnsafeUriError(f"unsafe or malformed {what}: {value!r}")
    return strip_uri_brackets(str(value))


def validate_cursor(value: Optional[str], *, what: str = "pagination cursor") -> str:
    """A keyset cursor is an IRI (context A) compared as a literal (context B).

    Both predicates are applied, composed rather than merged, so relaxing one
    character class cannot silently relax the other.
    """
    iri = validate_iri(value, what=what)
    if not is_safe_literal(iri):
        raise UnsafeUriError(f"unsafe or malformed {what}: {value!r}")
    return iri


def is_iri_member(value: Optional[str]) -> bool:
    """True for an http(s) IRI. Literals and blank nodes are not members.

    §3.2 admits IRI members only: a category cannot meaningfully have a literal
    or blank-node member, and either would have no local KG node to map to.
    """
    return is_safe_iri(value)


# Names of the local-KG lookup forms, in the order they are attempted. Recorded
# per mapped candidate so a reviewer can see how many mappings relied on a
# spelling other than the exact one the endpoint returned.
LOOKUP_FORM_BRACKETED = "BRACKETED"
LOOKUP_FORM_BARE = "BARE"
LOOKUP_FORM_PERCENT_DECODED_BRACKETED = "PERCENT_DECODED_BRACKETED"
LOOKUP_FORM_PERCENT_DECODED_BARE = "PERCENT_DECODED_BARE"
LOOKUP_FORM_NFC_BRACKETED = "NFC_BRACKETED"
LOOKUP_FORM_NFD_BRACKETED = "NFD_BRACKETED"

LOOKUP_FORM_ORDER = (
    LOOKUP_FORM_BRACKETED,
    LOOKUP_FORM_BARE,
    LOOKUP_FORM_PERCENT_DECODED_BRACKETED,
    LOOKUP_FORM_PERCENT_DECODED_BARE,
    LOOKUP_FORM_NFC_BRACKETED,
    LOOKUP_FORM_NFD_BRACKETED,
)


def local_lookup_forms(uri: str) -> tuple[tuple[str, str], ...]:
    """((form_name, key), ...) to try against the pinned pickle's url_index.

    The pinned pickle was built by src/read_ttl.py from the English infobox TTL
    and stores keys in the angle-bracketed form ``<http://...>`` — all nine
    approved Answer URIs resolve that way and none resolves bare
    (outputs/journal2_week1_foundation_2026-07-30/local_kg_inventory.json). So
    BRACKETED is tried first and is expected to be the only form that ever hits.

    The remaining forms exist because the endpoint and the dump need not spell an
    IRI identically:
      * a member may come back percent-encoded while the dump stored raw UTF-8;
      * ``ō`` is U+014D precomposed (NFC) or ``o``+U+0304 (NFD), and the two are
        distinct RDF terms even though they render alike.
    Each alternative is a SEPARATE, LABELLED attempt rather than a rewrite of the
    raw URI, so no mapping can be attributed to the exact form when it actually
    depended on an equivalent spelling. Duplicate keys are dropped while the
    first-seen order is preserved, so a pure-ASCII URI yields exactly two forms.
    """
    bare = strip_uri_brackets(uri)
    percent_decoded = urllib.parse.unquote(bare)
    nfc = unicodedata.normalize("NFC", bare)
    nfd = unicodedata.normalize("NFD", bare)

    ordered = (
        (LOOKUP_FORM_BRACKETED, f"<{bare}>"),
        (LOOKUP_FORM_BARE, bare),
        (LOOKUP_FORM_PERCENT_DECODED_BRACKETED, f"<{percent_decoded}>"),
        (LOOKUP_FORM_PERCENT_DECODED_BARE, percent_decoded),
        (LOOKUP_FORM_NFC_BRACKETED, f"<{nfc}>"),
        (LOOKUP_FORM_NFD_BRACKETED, f"<{nfd}>"),
    )
    seen: set[str] = set()
    forms: list[tuple[str, str]] = []
    for name, key in ordered:
        if key in seen:
            continue
        seen.add(key)
        forms.append((name, key))
    return tuple(forms)


# --- Query builders (pure) -------------------------------------------------

def build_class_members_page_query(
    class_uri: str,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    after: Optional[str] = None,
) -> str:
    """One deterministic page of ``?member dcterms:subject <CLASS_URI>``.

    Pagination is KEYSET, not OFFSET. The filter and the sort use the same
    expression — ``FILTER(STR(?member) > "cursor")`` with
    ``ORDER BY STR(?member)`` — because IRI ordering and lexical string ordering
    are not required to agree, and a page boundary computed under one order
    cannot be trusted under the other. OFFSET is avoided entirely: Virtuoso does
    not guarantee a stable order across two OFFSET queries, so pages could
    overlap or skip members.

    ``FILTER(isIRI(?member))`` enforces the IRI-only rule at the endpoint, and
    ``SELECT DISTINCT`` means a member with several dcterms:subject statements
    for the same class is returned once.
    """
    if int(page_size) < 1:
        raise ValueError(f"page_size must be >= 1, got {page_size!r}")
    category = validate_iri(class_uri, what="class URI")
    keyset = ""
    if after:
        keyset = f'\n  FILTER(STR(?member) > "{validate_cursor(after)}")'
    return f"""{QID_PREFIX} {QID_CLASS_MEMBERS_PAGE}
{_PREFIXES}
SELECT DISTINCT ?member WHERE {{
  ?member dcterms:subject <{category}> .
  FILTER(isIRI(?member)){keyset}
}} ORDER BY STR(?member) LIMIT {int(page_size)}
"""


def build_redirect_batch_query(member_uris: Sequence[str]) -> str:
    """One batched single-hop ``dbo:wikiPageRedirects`` lookup.

    ``owl:sameAs`` is NOT used and must never be added here: substituting a
    Wikidata or other cross-KG entity would silently change the approved
    candidate pool (§3.3).

    Batched via VALUES so that N unresolved members cost ceil(N/batch) requests
    instead of N. The VALUES list is sorted by the caller, which makes the query
    text — and therefore its cache key — a deterministic function of the member
    set rather than of arrival order.
    """
    if not member_uris:
        raise ValueError("redirect batch must contain at least one member URI")
    values = " ".join(
        f"<{validate_iri(u, what='redirect source URI')}>" for u in member_uris
    )
    return f"""{QID_PREFIX} {QID_REDIRECT_BATCH}
{_PREFIXES}
SELECT DISTINCT ?source ?target WHERE {{
  VALUES ?source {{ {values} }}
  ?source dbo:wikiPageRedirects ?target .
  FILTER(isIRI(?target))
}} ORDER BY STR(?source) STR(?target)
"""


def query_id(query: str) -> Optional[str]:
    """The ``#qid:`` marker of a query, so provenance need not substring-match."""
    for line in query.splitlines():
        stripped = line.strip()
        if stripped.startswith(QID_PREFIX):
            return stripped[len(QID_PREFIX):].strip()
    return None


def query_fingerprint(endpoint: str, query: str) -> str:
    """Stable identity of (endpoint, exact query text).

    The endpoint is part of the key: the same query against a different endpoint
    is a different observation and must not read another endpoint's cached rows.
    """
    return hashlib.sha256(f"{endpoint}\n{query}".encode("utf-8")).hexdigest()


# --- SPARQL JSON parsing ---------------------------------------------------

def binding_value(row: Mapping[str, Any], key: str) -> Optional[str]:
    """Read one SPARQL-JSON binding cell, tolerating the plain-string shape."""
    cell = row.get(key)
    if isinstance(cell, Mapping):
        value = cell.get("value")
        return None if value is None else str(value)
    return None if cell is None else str(cell)


class MalformedSparqlJson(SparqlClientError):
    """The body was not a SPARQL-JSON results document."""


def parse_sparql_json(text: str) -> tuple[Mapping[str, Any], ...]:
    """Parse a SPARQL-JSON body into its binding rows, or raise.

    Distinguishes "not JSON at all" from "JSON, but not SPARQL results", because
    the first is usually an HTML error page and the second usually means the
    endpoint's contract changed. Both are permanent, not retryable.
    """
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise MalformedSparqlJson(f"{ERROR_KIND_MALFORMED_JSON}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise MalformedSparqlJson(
            f"{ERROR_KIND_MALFORMED_SPARQL_RESULTS}: top level is "
            f"{type(payload).__name__}, expected an object"
        )
    results = payload.get("results")
    if not isinstance(results, Mapping):
        raise MalformedSparqlJson(
            f"{ERROR_KIND_MALFORMED_SPARQL_RESULTS}: missing 'results' object"
        )
    bindings = results.get("bindings")
    if not isinstance(bindings, list):
        raise MalformedSparqlJson(
            f"{ERROR_KIND_MALFORMED_SPARQL_RESULTS}: 'results.bindings' is "
            f"{type(bindings).__name__}, expected a list"
        )
    for row in bindings:
        if not isinstance(row, Mapping):
            raise MalformedSparqlJson(
                f"{ERROR_KIND_MALFORMED_SPARQL_RESULTS}: a binding row is "
                f"{type(row).__name__}, expected an object"
            )
    return tuple(bindings)


# --- Transport -------------------------------------------------------------

@dataclass(frozen=True)
class HttpResponse:
    """A raw HTTP response. No parsing, so the client owns all classification."""

    status_code: int
    text: str
    retry_after: Optional[str] = None


class HttpTransport(Protocol):
    """Minimal transport contract: POST a query, return status and body.

    Implementations either return an HttpResponse or raise a TransportError
    subclass. They must not retry, sleep, parse or classify — that is the
    client's job, so retry policy is tested without any HTTP library.
    """

    def post(self, endpoint: str, query: str) -> HttpResponse:  # pragma: no cover
        ...


@dataclass
class RequestsHttpTransport:
    """Live transport over `requests`, with explicit connect/read timeouts.

    POST with a form-encoded body rather than GET: a batched redirect query with
    50 VALUES entries is long enough to bump against URL-length limits, and a
    truncated URL would silently query a different member set.

    `requests` is imported lazily inside post(), so importing this module pulls
    in no HTTP machinery and the unit tests stay dependency-free.
    """

    user_agent: str = DEFAULT_USER_AGENT
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    read_timeout: float = DEFAULT_READ_TIMEOUT
    _session: Any = field(default=None, repr=False, compare=False)

    def post(self, endpoint: str, query: str) -> HttpResponse:
        import requests  # lazy: keeps module import network-free

        require_allowed_endpoint(endpoint)
        if self._session is None:
            self._session = requests.Session()
        try:
            response = self._session.post(
                endpoint,
                data={"query": query, "format": "application/sparql-results+json"},
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/sparql-results+json",
                },
                timeout=(self.connect_timeout, self.read_timeout),
            )
        except requests.exceptions.ConnectTimeout as exc:
            raise TransportConnectTimeout(
                f"connect timeout after {self.connect_timeout}s: {exc}") from exc
        except requests.exceptions.ReadTimeout as exc:
            raise TransportReadTimeout(
                f"read timeout after {self.read_timeout}s: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            # An unspecific Timeout is treated as a read timeout: the connection
            # phase has its own dedicated exception above, so anything left here
            # got at least as far as sending the request.
            raise TransportReadTimeout(f"request timeout: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise TransportConnectionError(f"connection error: {exc}") from exc

        return HttpResponse(
            status_code=int(response.status_code),
            text=response.text,
            retry_after=response.headers.get("Retry-After"),
        )


class OfflineTransport:
    """A transport that cannot reach the network. Used by strict offline replay.

    Strict offline mode is enforced structurally rather than by discipline: the
    replay holds an object with no socket, so "zero HTTP calls" is not a claim
    about the code path taken but a property of the object graph.
    """

    def __init__(self) -> None:
        self.attempt_count = 0

    def post(self, endpoint: str, query: str) -> HttpResponse:
        self.attempt_count += 1
        raise OfflineNetworkAttemptError(
            f"strict offline mode: refusing an HTTP call to {endpoint} for query "
            f"{query_id(query)!r}; the cache or frozen export must already hold "
            f"this page"
        )


def require_allowed_endpoint(endpoint: str) -> str:
    """Guard: only https://dbpedia.org/sparql is authorized for this task."""
    if endpoint not in ALLOWED_ENDPOINTS:
        raise EndpointNotAllowedError(
            f"endpoint {endpoint!r} is not authorized for this task; "
            f"allowed: {list(ALLOWED_ENDPOINTS)}"
        )
    return endpoint


# --- Attempt and page records ---------------------------------------------

@dataclass(frozen=True)
class AttemptRecord:
    """One HTTP attempt: what was asked, what came back, how long it waited."""

    attempt: int
    http_status: Optional[int]
    error_kind: Optional[str]
    error_detail: Optional[str]
    failure_class: Optional[str]
    slept_seconds: float
    started_at_epoch: float

    def as_record(self) -> dict:
        return {
            "attempt": self.attempt,
            "http_status": self.http_status,
            "error_kind": self.error_kind,
            "error_detail": self.error_detail,
            "failure_class": self.failure_class,
            "slept_seconds": round(self.slept_seconds, 6),
            "started_at_epoch": self.started_at_epoch,
        }


@dataclass(frozen=True)
class PageFailure:
    """A page that could not be retrieved. NEVER written to the results table."""

    query_kind: str
    query_fingerprint: str
    query_text: str
    endpoint: str
    class_uri: Optional[str]
    page_index: Optional[int]
    failure_class: str
    http_status: Optional[int]
    error_kind: Optional[str]
    error_detail: Optional[str]
    attempt_count: int
    attempts: tuple[AttemptRecord, ...]
    observed_at_epoch: float
    observed_at_iso: str

    def as_record(self) -> dict:
        return {
            "query_kind": self.query_kind,
            "query_fingerprint": self.query_fingerprint,
            "endpoint": self.endpoint,
            "class_uri": self.class_uri,
            "page_index": self.page_index,
            "failure_class": self.failure_class,
            "http_status": self.http_status,
            "error_kind": self.error_kind,
            "error_detail": self.error_detail,
            "attempt_count": self.attempt_count,
            "attempts": [a.as_record() for a in self.attempts],
            "observed_at_epoch": self.observed_at_epoch,
            "observed_at_iso": self.observed_at_iso,
        }


@dataclass(frozen=True)
class PageResult:
    """One SUCCESSFULLY retrieved page. This is the only cacheable outcome."""

    query_kind: str
    query_fingerprint: str
    query_text: str
    endpoint: str
    class_uri: Optional[str]
    page_index: Optional[int]
    cursor_after: Optional[str]
    page_size: Optional[int]
    page_state: str
    http_status: Optional[int]
    rows: tuple[Mapping[str, Any], ...]
    attempt_count: int
    attempts: tuple[AttemptRecord, ...]
    cache_origin: str
    retrieved_at_epoch: float
    retrieved_at_iso: str

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def is_terminal_page(self) -> bool:
        """True when no further page can exist after this one.

        A short page ends the walk. A full page might be the exact last page, in
        which case the next request legitimately returns zero rows — that next
        request is still made, because guessing here would risk dropping members.
        """
        if self.page_size is None:
            return True
        return self.row_count < int(self.page_size)

    def as_log_record(self) -> dict:
        """The query_log.jsonl shape: full provenance, rows omitted."""
        return {
            "query_kind": self.query_kind,
            "query_id": query_id(self.query_text),
            "query_fingerprint": self.query_fingerprint,
            "query_text": self.query_text,
            "endpoint": self.endpoint,
            "class_uri": self.class_uri,
            "page_index": self.page_index,
            "cursor_after": self.cursor_after,
            "page_size": self.page_size,
            "page_state": self.page_state,
            "http_status": self.http_status,
            "row_count": self.row_count,
            "is_terminal_page": self.is_terminal_page,
            "attempt_count": self.attempt_count,
            "attempts": [a.as_record() for a in self.attempts],
            "cache_origin": self.cache_origin,
            "retrieved_at_epoch": self.retrieved_at_epoch,
            "retrieved_at_iso": self.retrieved_at_iso,
        }


def iso_utc(epoch: float) -> str:
    """UTC ISO-8601 with an explicit offset. Timezone is never left implicit."""
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def classify_http_status(status: int) -> Optional[str]:
    """None when the status is a success; otherwise its FailureClass value.

    429 and the Virtuoso 5xx family are retryable. Everything else in 4xx is the
    endpoint rejecting THIS query — a malformed IRI, an unsupported feature — and
    retrying it unchanged would just repeat the rejection, so it is permanent.
    """
    if 200 <= status < 300:
        return None
    if status in RETRYABLE_HTTP_STATUSES:
        return FailureClass.RETRYABLE_FAILURE.value
    if 400 <= status < 500:
        return FailureClass.PERMANENT_QUERY_REJECTED.value
    return FailureClass.RETRYABLE_FAILURE.value


def parse_retry_after(value: Optional[str], *, now: Optional[float] = None
                      ) -> Optional[float]:
    """Seconds to wait per a Retry-After header, or None if unusable.

    Accepts both RFC 9110 forms: delta-seconds and an HTTP-date. A value in the
    past yields 0.0, never a negative sleep.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return max(0.0, float(int(text)))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        from datetime import timezone

        when = when.replace(tzinfo=timezone.utc)
    reference = time.time() if now is None else now
    return max(0.0, when.timestamp() - reference)


def backoff_delay(
    attempt: int,
    *,
    base: float = DEFAULT_BACKOFF_BASE_SECONDS,
    cap: float = DEFAULT_BACKOFF_CAP_SECONDS,
    jitter_fraction: float = DEFAULT_JITTER_FRACTION,
    rng: Optional[random.Random] = None,
) -> float:
    """Exponential backoff with bounded multiplicative jitter.

    `attempt` is 1-based, so the first retry waits about `base` seconds. Jitter
    spreads retries so that several classes failing at the same moment do not
    re-request in lockstep; it is bounded (not full jitter) so the delay still
    grows monotonically in expectation. The RNG is injectable, which is what
    makes the retry schedule assertable in a unit test.
    """
    exponential = min(float(cap), float(base) * (2.0 ** max(0, attempt - 1)))
    if jitter_fraction <= 0.0:
        return exponential
    generator = rng if rng is not None else random.Random()
    factor = 1.0 + generator.uniform(-float(jitter_fraction), float(jitter_fraction))
    return max(0.0, min(float(cap), exponential * factor))


# --- The client ------------------------------------------------------------

@dataclass
class SparqlPageClient:
    """Retry, classify and time-stamp one page request. No caching, no paging.

    Deliberately does ONE thing: turn a query string into either a PageResult or
    a PageFailure, having applied the bounded retry policy. Pagination lives in
    member_mapper, and caching lives in PageCache, so each can be tested alone.
    """

    transport: HttpTransport
    endpoint: str = DBPEDIA_ENDPOINT
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS
    backoff_cap: float = DEFAULT_BACKOFF_CAP_SECONDS
    jitter_fraction: float = DEFAULT_JITTER_FRACTION
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.time
    rng: random.Random = field(default_factory=lambda: random.Random(20260730))
    respect_retry_after: bool = True
    http_call_count: int = 0

    def __post_init__(self) -> None:
        require_allowed_endpoint(self.endpoint)
        if int(self.max_attempts) < 1:
            raise ValueError(f"max_attempts must be >= 1, got {self.max_attempts!r}")

    def fetch(
        self,
        query: str,
        *,
        query_kind: str,
        class_uri: Optional[str] = None,
        page_index: Optional[int] = None,
        cursor_after: Optional[str] = None,
        page_size: Optional[int] = None,
    ) -> PageResult:
        """Retrieve one page, or raise PageRetrievalFailed with its provenance."""
        fingerprint = query_fingerprint(self.endpoint, query)
        attempts: list[AttemptRecord] = []
        pending_sleep = 0.0

        for attempt in range(1, int(self.max_attempts) + 1):
            if pending_sleep > 0.0:
                self.sleep(pending_sleep)
            slept, pending_sleep = pending_sleep, 0.0
            started = self.clock()

            status: Optional[int] = None
            error_kind: Optional[str] = None
            error_detail: Optional[str] = None
            failure_class: Optional[str] = None
            rows: Optional[tuple[Mapping[str, Any], ...]] = None
            retry_after_seconds: Optional[float] = None

            self.http_call_count += 1
            try:
                response = self.transport.post(self.endpoint, query)
            except TransportError as exc:
                error_kind = getattr(exc, "error_kind", ERROR_KIND_TRANSPORT_EXCEPTION)
                error_detail = f"{type(exc).__name__}: {exc}"
                failure_class = FailureClass.RETRYABLE_FAILURE.value
            else:
                status = response.status_code
                status_failure = classify_http_status(status)
                if status_failure is not None:
                    failure_class = status_failure
                    error_kind = ERROR_KIND_HTTP_STATUS
                    error_detail = f"HTTP {status}: {response.text[:400]}"
                    if self.respect_retry_after:
                        retry_after_seconds = parse_retry_after(
                            response.retry_after, now=started)
                else:
                    try:
                        rows = parse_sparql_json(response.text)
                    except MalformedSparqlJson as exc:
                        # A 200 with an unparseable body is NOT retryable and is
                        # certainly not an empty result set: caching it as zero
                        # rows would turn a broken response into the finding
                        # "this class has no members".
                        failure_class = (
                            FailureClass.PERMANENT_MALFORMED_RESPONSE.value)
                        error_kind = str(exc).split(":", 1)[0]
                        error_detail = str(exc)[:400]

            attempts.append(AttemptRecord(
                attempt=attempt,
                http_status=status,
                error_kind=error_kind,
                error_detail=error_detail,
                failure_class=failure_class,
                slept_seconds=slept,
                started_at_epoch=started,
            ))

            if rows is not None:
                finished = self.clock()
                state = (PageState.PAGE_COMPLETE_ZERO_ROWS if not rows
                         else PageState.PAGE_COMPLETE)
                return PageResult(
                    query_kind=query_kind,
                    query_fingerprint=fingerprint,
                    query_text=query,
                    endpoint=self.endpoint,
                    class_uri=class_uri,
                    page_index=page_index,
                    cursor_after=cursor_after,
                    page_size=page_size,
                    page_state=state.value,
                    http_status=status,
                    rows=rows,
                    attempt_count=attempt,
                    attempts=tuple(attempts),
                    cache_origin=CacheOrigin.LIVE_HTTP.value,
                    retrieved_at_epoch=finished,
                    retrieved_at_iso=iso_utc(finished),
                )

            if failure_class != FailureClass.RETRYABLE_FAILURE.value:
                break                      # permanent: another attempt is waste
            if attempt < int(self.max_attempts):
                delay = backoff_delay(
                    attempt,
                    base=self.backoff_base,
                    cap=self.backoff_cap,
                    jitter_fraction=self.jitter_fraction,
                    rng=self.rng,
                )
                # A server-supplied Retry-After outranks our own schedule, but is
                # still capped so a hostile or mistaken header cannot stall a run.
                if retry_after_seconds is not None:
                    delay = min(float(self.backoff_cap),
                                max(delay, retry_after_seconds))
                pending_sleep = delay

        last = attempts[-1]
        observed = self.clock()
        failure = PageFailure(
            query_kind=query_kind,
            query_fingerprint=fingerprint,
            query_text=query,
            endpoint=self.endpoint,
            class_uri=class_uri,
            page_index=page_index,
            failure_class=last.failure_class or FailureClass.RETRYABLE_FAILURE.value,
            http_status=last.http_status,
            error_kind=last.error_kind,
            error_detail=last.error_detail,
            attempt_count=len(attempts),
            attempts=tuple(attempts),
            observed_at_epoch=observed,
            observed_at_iso=iso_utc(observed),
        )
        raise PageRetrievalFailed(
            f"{query_kind} page {page_index} for {class_uri or '(no class)'} failed "
            f"after {len(attempts)} attempt(s): {last.error_kind} {last.error_detail}",
            failure,
        )
