############################################################################
# src/classes/wikipedia_lead.py
#
# English Wikipedia LEAD TEXT retrieval and caching for category selector v6.
#
# WHY THIS MODULE EXISTS AT ALL
#   Category selector v5 scored the semantic component from ``dbo:abstract``.
#   During Prompt 8H-B2-B the locally cached Sentence-BERT model loaded
#   successfully offline, but the current public DBpedia endpoint returned no
#   usable ``dbo:abstract`` values for ANY probed entity (measured evidence:
#   ``outputs/journal2_phase_b2_einstein_e2e_2026-08-13/
#   sbert_abstract_unavailability_evidence.txt`` — Einstein has 1,166 outgoing
#   triples on that endpoint and zero abstracts in any language). The Einstein
#   ranking was therefore IDF-only while being labelled an IDF+SBERT run. v6
#   takes its semantic text from a source that is actually served today: the
#   English Wikipedia lead section, through an official MediaWiki API.
#
# WHY THE FIELD IS CALLED wikipedia_lead_text AND NEVER dbo:abstract
#   They are different objects with different provenance. ``dbo:abstract`` is a
#   literal inside a DBpedia release; a Wikipedia lead is the intro section of a
#   LIVE Wikipedia revision, identified by a revision ID that changes over time.
#   Calling the second one "abstract" would make two incomparable artifacts look
#   interchangeable in the output tables, which is exactly the confusion this
#   module is meant to remove.
#
# WHY WIKIPEDIA TEXT IS RANKING EVIDENCE AND NEVER RATIONALE-TRUTH EVIDENCE
#   The rationale layer reasons over the PINNED March-2023 DBpedia infobox
#   graph under an Open-World Assumption; every rationale claim must be
#   traceable to a triple in that snapshot. A Wikipedia lead fetched today comes
#   from a different, later, unpinned corpus. Using it to justify a rationale
#   would silently import unpinned present-day prose into a frozen-snapshot
#   argument. It is used for exactly one thing: producing a similarity score
#   that ORDERS candidate-source classes. Nothing downstream of the class
#   ranking ever reads this text.
#
# WHY AN OFFICIAL API AND NOT SCRAPED HTML
#   Rendered Wikipedia HTML has no stable contract, mixes navigation furniture
#   and infobox text into the prose, and gives no revision identity. The
#   MediaWiki Action API returns the intro section as plain text together with
#   the page ID, the canonical title after redirect resolution, and the exact
#   revision ID and timestamp — i.e. everything needed to say precisely which
#   text was scored.
#
# IMPORT-TIME PURITY
#   No network call, no file creation, no model load at import. ``requests`` is
#   imported lazily inside the live transport.
############################################################################

from __future__ import annotations

import hashlib
import json
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Protocol, Sequence

__all__ = [
    "WIKIPEDIA_API_ENDPOINT",
    "DEFAULT_USER_AGENT",
    "LeadStatus",
    "WikipediaLead",
    "WikipediaLeadCache",
    "HttpResponse",
    "WikipediaTransport",
    "RequestsWikipediaTransport",
    "WikipediaLeadClient",
    "dbpedia_uri_to_wikipedia_title",
    "build_lead_query_params",
    "parse_lead_response",
    "sha256_text",
    "iso_utc",
]

# The single English Wikipedia API host this module may contact. A different
# host is refused rather than requested: a "Wikipedia lead" from a mirror is not
# the same observation and must not enter the provenance record under this name.
WIKIPEDIA_API_ENDPOINT = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_LANGUAGE = "en"

# Wikimedia's API etiquette requires a descriptive User-Agent identifying the
# client and a contact address, so that operators can reach the researcher
# rather than blanket-blocking an anonymous crawler.
DEFAULT_USER_AGENT = (
    "mcq-journal2-category-selector-v6/1.0 "
    "(research: MCQ distractor generation from knowledge graphs; "
    "contact: redaiprojects289@gmail.com)"
)

# The MediaWiki extracts module caps a batched intro request at 20 pages.
MAX_TITLES_PER_REQUEST = 20

DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_READ_TIMEOUT = 60.0
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BACKOFF_BASE_SECONDS = 1.0
DEFAULT_BACKOFF_CAP_SECONDS = 30.0

RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})

DBPEDIA_RESOURCE_PREFIXES = (
    "http://dbpedia.org/resource/",
    "https://dbpedia.org/resource/",
)

# Cache-file schema. Bumping this refuses an older cache rather than silently
# reinterpreting its records under new field semantics.
CACHE_SCHEMA_VERSION = "wikipedia_lead_cache_v1"


class WikipediaLeadError(Exception):
    """Base class for every failure this module raises deliberately."""


class EndpointNotAllowedError(WikipediaLeadError):
    """A host other than the English Wikipedia API was requested."""


class OfflineNetworkAttemptError(WikipediaLeadError):
    """A live request was attempted while the network gate was closed."""


class CacheSchemaMismatch(WikipediaLeadError):
    """The cache file was written by a different schema version."""


class LeadStatus(str, Enum):
    """Why a lead is or is not available. Four states, never collapsed to one.

    ``OK``                    a page was resolved and non-empty lead text was
                              returned.
    ``PAGE_MISSING``          the API answered successfully and reported that no
                              such page exists. This is DATA, not a failure.
    ``EMPTY_LEAD``            the page exists but its intro extract is empty
                              (e.g. a pure disambiguation or set-index page).
                              Also data.
    ``REQUEST_FAILED``        the API could not be reached, returned a non-2xx
                              status, or returned a body this module could not
                              parse. NOT a statement about the page.

    Keeping ``REQUEST_FAILED`` distinct from ``PAGE_MISSING``/``EMPTY_LEAD`` is
    the same discipline the SPARQL layer already enforces: a transport problem
    must never be recorded as a finding about the world, because a coverage
    census built on that confusion would understate Wikipedia coverage by
    exactly the number of requests that happened to fail.
    """

    OK = "ok"
    PAGE_MISSING = "page_missing"
    EMPTY_LEAD = "empty_lead"
    REQUEST_FAILED = "request_failed"


def iso_utc(moment: Optional[float] = None) -> str:
    """UTC ISO-8601 timestamp with second resolution."""
    stamp = datetime.fromtimestamp(
        time.time() if moment is None else moment, tz=timezone.utc
    )
    return stamp.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    """SHA-256 of the exact UTF-8 bytes of ``text``.

    Recorded for every cached lead so that a later replay can prove it scored
    the same characters, not merely a text retrieved from the same title.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dbpedia_uri_to_wikipedia_title(answer_uri: str) -> Optional[str]:
    """Derive the REQUESTED English Wikipedia title from a DBpedia resource URI.

    DBpedia resource URIs are minted from Wikipedia article titles by replacing
    spaces with underscores and percent-encoding, so the inverse is mechanical:
    take the local name, percent-decode it, turn underscores back into spaces.

    This is deliberately only the *requested* title. Whether that title is the
    canonical one is not decided here — the API's own ``normalized`` and
    ``redirects`` reports settle it, and both are recorded (see
    :func:`parse_lead_response`). Guessing canonicality locally would hide the
    redirect that the provenance record is supposed to expose.

    Returns ``None`` for a URI that is not a DBpedia resource, rather than
    fabricating a title from an arbitrary string.
    """
    if not answer_uri:
        return None
    text = str(answer_uri).strip().strip("<>").strip()
    for prefix in DBPEDIA_RESOURCE_PREFIXES:
        if text.startswith(prefix):
            local = text[len(prefix):]
            break
    else:
        return None
    if not local or "/" in local:
        return None
    title = urllib.parse.unquote(local).replace("_", " ").strip()
    # NFC only: the API compares titles after its own normalisation, and NFC is
    # what Wikipedia stores. No case folding, no diacritic stripping — those
    # would silently request a different article.
    title = unicodedata.normalize("NFC", title)
    return title or None


@dataclass(frozen=True)
class WikipediaLead:
    """One Answer's English Wikipedia lead, with complete retrieval provenance.

    ``lead_text`` holds the FULL intro section exactly as the API returned it.
    It is never truncated before storage: chunking for the encoder's token
    window happens at encoding time only, so the cached artifact stays a
    faithful copy of what Wikipedia served (Prompt §H).
    """

    answer_uri: str
    requested_title: Optional[str]
    status: LeadStatus
    canonical_title: Optional[str] = None
    page_id: Optional[int] = None
    revision_id: Optional[int] = None
    revision_timestamp: Optional[str] = None
    normalized_from: Optional[str] = None
    redirected_from: Optional[str] = None
    lead_text: Optional[str] = None
    lead_sha256: Optional[str] = None
    character_length: int = 0
    sentence_count: int = 0
    language: str = WIKIPEDIA_LANGUAGE
    api_endpoint: str = WIKIPEDIA_API_ENDPOINT
    retrieved_at: Optional[str] = None
    error: Optional[str] = None
    cache_status: str = "miss"

    @property
    def available(self) -> bool:
        """True only when real, non-empty lead text is present.

        A caller must branch on this rather than on ``lead_text or ""``: an
        unavailable lead is not an empty lead and must not be scored as one.
        """
        return self.status is LeadStatus.OK and bool(self.lead_text)

    @property
    def redirect_used(self) -> bool:
        return self.redirected_from is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer_uri": self.answer_uri,
            "requested_title": self.requested_title,
            "status": self.status.value,
            "canonical_title": self.canonical_title,
            "page_id": self.page_id,
            "revision_id": self.revision_id,
            "revision_timestamp": self.revision_timestamp,
            "normalized_from": self.normalized_from,
            "redirected_from": self.redirected_from,
            "lead_text": self.lead_text,
            "lead_sha256": self.lead_sha256,
            "character_length": self.character_length,
            "sentence_count": self.sentence_count,
            "language": self.language,
            "api_endpoint": self.api_endpoint,
            "retrieved_at": self.retrieved_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any], *,
                  cache_status: str = "hit") -> "WikipediaLead":
        return cls(
            answer_uri=str(record["answer_uri"]),
            requested_title=record.get("requested_title"),
            status=LeadStatus(str(record["status"])),
            canonical_title=record.get("canonical_title"),
            page_id=record.get("page_id"),
            revision_id=record.get("revision_id"),
            revision_timestamp=record.get("revision_timestamp"),
            normalized_from=record.get("normalized_from"),
            redirected_from=record.get("redirected_from"),
            lead_text=record.get("lead_text"),
            lead_sha256=record.get("lead_sha256"),
            character_length=int(record.get("character_length") or 0),
            sentence_count=int(record.get("sentence_count") or 0),
            language=str(record.get("language") or WIKIPEDIA_LANGUAGE),
            api_endpoint=str(record.get("api_endpoint") or WIKIPEDIA_API_ENDPOINT),
            retrieved_at=record.get("retrieved_at"),
            error=record.get("error"),
            cache_status=cache_status,
        )


def count_sentences(text: str) -> int:
    """Cheap sentence count for the coverage census only.

    Not a linguistic claim and not used for scoring: it exists so the
    dbo:description-versus-Wikipedia-lead census can report text size in a
    second unit besides characters.
    """
    if not text or not text.strip():
        return 0
    count = 0
    for chunk in text.replace("!", ".").replace("?", ".").split("."):
        if chunk.strip():
            count += 1
    return count


# ---------------------------------------------------------------------------
# Request construction and response parsing — pure, network-free, testable
# ---------------------------------------------------------------------------


def build_lead_query_params(titles: Sequence[str]) -> dict[str, str]:
    """Parameters for one batched MediaWiki intro-extract request.

    ``exintro`` + ``explaintext`` restrict the extract to the LEAD section,
    before the first ordinary section heading, and return it as plain text
    rather than HTML or wikitext. ``redirects=1`` makes the API resolve
    redirects itself and report every hop, so redirect handling is the API's
    documented behaviour rather than a local heuristic. ``rvprop=ids|timestamp``
    pins the exact revision the text came from.
    """
    if not titles:
        raise ValueError("at least one title is required")
    if len(titles) > MAX_TITLES_PER_REQUEST:
        raise ValueError(
            f"at most {MAX_TITLES_PER_REQUEST} titles per request, got {len(titles)}"
        )
    for title in titles:
        # "|" is the API's list separator; a title containing one cannot be
        # batched unambiguously and is refused rather than silently split.
        if not title or "|" in title:
            raise ValueError(f"unusable Wikipedia title for a batched request: {title!r}")
    return {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "prop": "extracts|revisions",
        "exintro": "1",
        "explaintext": "1",
        "exlimit": str(MAX_TITLES_PER_REQUEST),
        "redirects": "1",
        "rvprop": "ids|timestamp",
        "rvslots": "main",
        "titles": "|".join(titles),
        "maxlag": "5",
    }


def _chain_requested_title(
    requested: str,
    normalized: Mapping[str, str],
    redirects: Mapping[str, str],
) -> tuple[str, Optional[str], Optional[str]]:
    """Follow ``normalized`` then ``redirects`` from a requested title.

    Returns ``(final_title, normalized_from, redirected_from)``. The API applies
    normalisation before redirect resolution and may chain several redirects, so
    the chain is followed rather than assumed to be one hop. A cycle terminates
    the walk instead of looping.
    """
    normalized_from: Optional[str] = None
    current = requested
    if current in normalized:
        normalized_from = current
        current = normalized[current]

    redirected_from: Optional[str] = None
    seen = {current}
    while current in redirects:
        nxt = redirects[current]
        if nxt in seen:
            break
        if redirected_from is None:
            redirected_from = current
        current = nxt
        seen.add(current)
    return current, normalized_from, redirected_from


def parse_lead_response(
    payload: Mapping[str, Any],
    requested_titles: Sequence[str],
    title_to_answer: Mapping[str, str],
    *,
    retrieved_at: Optional[str] = None,
) -> list[WikipediaLead]:
    """Turn one API response into one :class:`WikipediaLead` per requested title.

    Every requested title yields exactly one record, in the order requested, so
    a page the API silently omitted becomes an explicit ``REQUEST_FAILED``
    rather than a missing row that a later count would read as "not attempted".
    """
    stamp = retrieved_at or iso_utc()
    query = payload.get("query")
    if not isinstance(query, Mapping):
        raise ValueError("MediaWiki response has no 'query' object")

    normalized = {
        str(item["from"]): str(item["to"])
        for item in query.get("normalized", ())
        if isinstance(item, Mapping) and "from" in item and "to" in item
    }
    redirects = {
        str(item["from"]): str(item["to"])
        for item in query.get("redirects", ())
        if isinstance(item, Mapping) and "from" in item and "to" in item
    }
    pages_by_title: dict[str, Mapping[str, Any]] = {}
    for page in query.get("pages", ()):
        if isinstance(page, Mapping) and page.get("title") is not None:
            pages_by_title[str(page["title"])] = page

    leads: list[WikipediaLead] = []
    for requested in requested_titles:
        answer_uri = title_to_answer.get(requested, "")
        final_title, normalized_from, redirected_from = _chain_requested_title(
            requested, normalized, redirects
        )
        page = pages_by_title.get(final_title)
        if page is None:
            leads.append(WikipediaLead(
                answer_uri=answer_uri,
                requested_title=requested,
                status=LeadStatus.REQUEST_FAILED,
                canonical_title=final_title,
                normalized_from=normalized_from,
                redirected_from=redirected_from,
                retrieved_at=stamp,
                error=(
                    "the API response contained no page entry for the resolved "
                    f"title {final_title!r}"
                ),
            ))
            continue

        if page.get("missing"):
            leads.append(WikipediaLead(
                answer_uri=answer_uri,
                requested_title=requested,
                status=LeadStatus.PAGE_MISSING,
                canonical_title=str(page.get("title") or final_title),
                normalized_from=normalized_from,
                redirected_from=redirected_from,
                retrieved_at=stamp,
            ))
            continue

        revisions = page.get("revisions") or ()
        revision = revisions[0] if revisions and isinstance(revisions[0], Mapping) else {}
        text = page.get("extract") or ""
        text = text.strip()
        status = LeadStatus.OK if text else LeadStatus.EMPTY_LEAD
        leads.append(WikipediaLead(
            answer_uri=answer_uri,
            requested_title=requested,
            status=status,
            canonical_title=str(page.get("title") or final_title),
            page_id=int(page["pageid"]) if page.get("pageid") is not None else None,
            revision_id=int(revision["revid"]) if revision.get("revid") is not None else None,
            revision_timestamp=(
                str(revision["timestamp"]) if revision.get("timestamp") is not None else None
            ),
            normalized_from=normalized_from,
            redirected_from=redirected_from,
            lead_text=text or None,
            lead_sha256=sha256_text(text) if text else None,
            character_length=len(text),
            sentence_count=count_sentences(text),
            retrieved_at=stamp,
        ))
    return leads


# ---------------------------------------------------------------------------
# Cache — one JSON file, sorted by Answer URI, replayable without a network
# ---------------------------------------------------------------------------


class WikipediaLeadCache:
    """A plain JSON file mapping Answer URI -> lead record.

    WHY A JSON FILE AND NOT SQLITE
        There is at most one record per Answer and the whole corpus is a few
        hundred Answers, so a sorted, human-readable, diffable file is a better
        scientific artifact than an opaque binary: a reviewer can read exactly
        which revision of which article was scored. Nothing here is a hot path.

    WHY A FAILED REQUEST IS NEVER STORED
        Storing ``REQUEST_FAILED`` would let a transient network problem be
        replayed forever as though Wikipedia had answered. ``PAGE_MISSING`` and
        ``EMPTY_LEAD`` ARE stored: those are answers, and re-asking for them on
        every run would waste requests on pages already known not to have a
        lead.

    The file is created only when :meth:`save` is called — never at import and
    never merely by constructing the object.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._records: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def load(self) -> "WikipediaLeadCache":
        """Read the cache file if it exists. A foreign schema is refused."""
        if self._loaded:
            return self
        self._loaded = True
        if not self.path.is_file():
            return self
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        version = payload.get("schema_version")
        if version != CACHE_SCHEMA_VERSION:
            raise CacheSchemaMismatch(
                f"{self.path} declares schema_version {version!r}, "
                f"expected {CACHE_SCHEMA_VERSION!r}; refusing to reinterpret it"
            )
        for record in payload.get("leads", ()):
            self._records[str(record["answer_uri"])] = dict(record)
        return self

    def get(self, answer_uri: str) -> Optional[WikipediaLead]:
        self.load()
        record = self._records.get(answer_uri)
        if record is None:
            return None
        return WikipediaLead.from_dict(record, cache_status="hit")

    def put(self, lead: WikipediaLead) -> bool:
        """Store a lead. Returns False for a request failure, which is dropped."""
        self.load()
        if lead.status is LeadStatus.REQUEST_FAILED:
            return False
        self._records[lead.answer_uri] = lead.to_dict()
        return True

    def save(self) -> Path:
        """Write the cache atomically, sorted by Answer URI for stable bytes."""
        self.load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "api_endpoint": WIKIPEDIA_API_ENDPOINT,
            "language": WIKIPEDIA_LANGUAGE,
            "lead_count": len(self._records),
            "leads": [self._records[k] for k in sorted(self._records)],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(text + "\n", encoding="utf-8")
        temporary.replace(self.path)
        return self.path

    def __len__(self) -> int:
        self.load()
        return len(self._records)


# ---------------------------------------------------------------------------
# Transport and client
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HttpResponse:
    """A raw HTTP response. Classification belongs to the client, not here."""

    status_code: int
    text: str
    retry_after: Optional[str] = None


class WikipediaTransport(Protocol):
    """Minimal transport contract: GET the API, return status and body.

    An implementation neither retries nor parses; the client owns both, so
    retry policy is testable with no HTTP library present.
    """

    def get(self, endpoint: str,
            params: Mapping[str, str]) -> HttpResponse:  # pragma: no cover
        ...


@dataclass
class RequestsWikipediaTransport:
    """Live transport over ``requests``, with explicit connect/read timeouts.

    ``requests`` is imported lazily inside :meth:`get`, so importing this module
    pulls in no HTTP machinery and the unit tests need none.
    """

    user_agent: str = DEFAULT_USER_AGENT
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    read_timeout: float = DEFAULT_READ_TIMEOUT
    _session: Any = field(default=None, repr=False, compare=False)

    def get(self, endpoint: str, params: Mapping[str, str]) -> HttpResponse:
        import requests  # lazy: keeps module import network-free

        if endpoint != WIKIPEDIA_API_ENDPOINT:
            raise EndpointNotAllowedError(
                f"{endpoint!r} is not the allowed English Wikipedia API endpoint "
                f"{WIKIPEDIA_API_ENDPOINT!r}"
            )
        if self._session is None:
            self._session = requests.Session()
        response = self._session.get(
            endpoint,
            params=dict(params),
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            timeout=(self.connect_timeout, self.read_timeout),
        )
        return HttpResponse(
            status_code=int(response.status_code),
            text=response.text,
            retry_after=response.headers.get("Retry-After"),
        )


@dataclass
class WikipediaLeadClient:
    """Fetches leads through a transport, a cache, and an explicit network gate.

    ``allow_network=False`` (the default) means a cache miss is reported as a
    ``REQUEST_FAILED`` with an explicit reason instead of quietly contacting
    Wikipedia. Nothing about constructing this object touches the network.
    """

    transport: Optional[WikipediaTransport] = None
    cache: Optional[WikipediaLeadCache] = None
    allow_network: bool = False
    endpoint: str = WIKIPEDIA_API_ENDPOINT
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS
    backoff_cap: float = DEFAULT_BACKOFF_CAP_SECONDS
    sleep: Any = time.sleep
    request_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    def fetch_many(self, answer_uris: Sequence[str]) -> dict[str, WikipediaLead]:
        """Return one lead per Answer URI, using the cache wherever possible.

        Cached Answers cost no request at all, which is what makes the six-alpha
        sweep free of extra traffic: the sweep re-reads the same frozen lead
        text for every alpha (Prompt §L).
        """
        results: dict[str, WikipediaLead] = {}
        pending: list[str] = []
        for uri in answer_uris:
            if uri in results or uri in pending:
                continue
            cached = self.cache.get(uri) if self.cache is not None else None
            if cached is not None:
                self.cache_hits += 1
                results[uri] = cached
                continue
            self.cache_misses += 1
            pending.append(uri)

        # Titles that cannot be derived never reach the network.
        batch: list[tuple[str, str]] = []
        for uri in pending:
            title = dbpedia_uri_to_wikipedia_title(uri)
            if title is None or "|" in title:
                results[uri] = WikipediaLead(
                    answer_uri=uri,
                    requested_title=title,
                    status=LeadStatus.REQUEST_FAILED,
                    retrieved_at=iso_utc(),
                    error=(
                        "no English Wikipedia title can be derived from this URI; "
                        "it is not a batchable DBpedia resource URI"
                    ),
                    cache_status="miss",
                )
            else:
                batch.append((uri, title))

        for start in range(0, len(batch), MAX_TITLES_PER_REQUEST):
            window = batch[start:start + MAX_TITLES_PER_REQUEST]
            for lead in self._fetch_batch(window):
                results[lead.answer_uri] = lead
                if self.cache is not None:
                    self.cache.put(lead)
        return results

    def _fetch_batch(self, window: Sequence[tuple[str, str]]) -> list[WikipediaLead]:
        titles = [title for _, title in window]
        title_to_answer = {title: uri for uri, title in window}

        if not self.allow_network or self.transport is None:
            return [
                WikipediaLead(
                    answer_uri=uri,
                    requested_title=title,
                    status=LeadStatus.REQUEST_FAILED,
                    retrieved_at=iso_utc(),
                    error=(
                        "network access is not enabled and no cached lead exists "
                        "for this Answer"
                    ),
                    cache_status="miss",
                )
                for uri, title in window
            ]

        params = build_lead_query_params(titles)
        last_error: Optional[str] = None
        for attempt in range(max(1, self.max_attempts)):
            self.request_count += 1
            try:
                response = self.transport.get(self.endpoint, params)
            except Exception as exc:  # noqa: BLE001 - transport errors are data
                last_error = f"transport_exception: {exc!r}"
            else:
                if response.status_code in RETRYABLE_HTTP_STATUSES:
                    last_error = f"http_status: {response.status_code}"
                elif response.status_code != 200:
                    # A permanent status is not retried: repeating a request the
                    # server has already rejected wastes Wikimedia's capacity.
                    last_error = f"http_status: {response.status_code}"
                    break
                else:
                    try:
                        payload = json.loads(response.text)
                        return parse_lead_response(payload, titles, title_to_answer)
                    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
                        last_error = f"malformed_response: {exc!r}"
                        break
            if attempt < self.max_attempts - 1:
                self.sleep(min(self.backoff_base * (2 ** attempt), self.backoff_cap))

        stamp = iso_utc()
        return [
            WikipediaLead(
                answer_uri=uri,
                requested_title=title,
                status=LeadStatus.REQUEST_FAILED,
                retrieved_at=stamp,
                error=last_error,
                cache_status="miss",
            )
            for uri, title in window
        ]

    def stats(self) -> dict[str, int]:
        return {
            "api_requests": self.request_count,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
        }
