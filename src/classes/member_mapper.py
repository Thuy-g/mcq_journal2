############################################################################
# src/classes/member_mapper.py
#
#   approved DBpedia class
#     -> retrieve class members            (bounded keyset pagination, resumable)
#     -> resolve DBpedia redirects         (dbo:wikiPageRedirects, never sameAs)
#     -> map members into the pinned local KG
#     -> apply the MAPPING-STAGE gate
#
# WHAT THE GATE IS, AND IS NOT
#   MIN_MAPPED_LOCAL_CANDIDATES = 10 mapped local candidates, excluding the
#   Answer. It is a NECESSARY MAPPING condition only. It is NOT graph-budget
#   feasibility: it says nothing about whether those candidates' complete one-hop
#   neighbourhoods fit under DEFAULT_MAX_NODES, which is decided later by
#   src/kg/graph_view.py. A class that passes this gate may still fail the graph
#   budget. Nothing in this module may be described as graph feasibility.
#
# TWO PHASES, DELIBERATELY SEPARATED
#   Phase A  retrieve every unique approved class's members, then resolve every
#            redirect needed by any of them.
#   Phase B  a PURE function evaluates the frozen local counts per Answer/class.
#   The separation is required by §3.5: select_first_feasible_class() is only ever
#   handed a callback that reads already-frozen integers, so no hidden network
#   call can happen inside a feasibility walk and change the answer depending on
#   evaluation order.
#
# OPEN-WORLD DISCIPLINE (CLAUDE.md boundary 7)
#   A member that does not resolve locally is UNRESOLVED with a machine-readable
#   reason. It is never recorded as "not a member" or "does not exist"; the local
#   pickle is one snapshot of one dump, and its silence is not a negative fact.
#
# NOT DONE HERE
#   No candidate ordering policy, no build_m1_graph(), no OverlapScore, no
#   LRoleSim, no distractor choice, no rationale work, no verbalization. Members
#   are serialised in URI order purely for determinism; see the module note on
#   ordering in local_candidate_profile.py.
############################################################################

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional, Protocol, Sequence

from classes.page_cache import (
    FrozenClassMembers,
    FrozenExport,
    FrozenRedirect,
    PageCache,
)
from classes.policy import (
    AnswerClassPolicy,
    NO_FEASIBLE_APPROVED_CLASS,
    SELECTED_FALLBACK_1,
    SELECTED_FALLBACK_2,
    SELECTED_PREFERRED,
    ClassSelectionResult,
    select_first_feasible_class,
)
from classes.sparql_client import (
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_REDIRECT_HOPS,
    DEFAULT_PAGE_SIZE,
    DEFAULT_REDIRECT_BATCH_SIZE,
    CacheOrigin,
    PageFailure,
    PageResult,
    PageRetrievalFailed,
    QueryKind,
    SparqlPageClient,
    binding_value,
    build_class_members_page_query,
    build_redirect_batch_query,
    is_iri_member,
    is_safe_iri,
    local_lookup_forms,
    query_fingerprint,
    strip_uri_brackets,
)

# --- The mapping-stage gate ------------------------------------------------
MIN_MAPPED_LOCAL_CANDIDATES = 10

MAPPING_SELECTED_PREFERRED = "MAPPING_SELECTED_PREFERRED"
MAPPING_SELECTED_FALLBACK_1 = "MAPPING_SELECTED_FALLBACK_1"
MAPPING_SELECTED_FALLBACK_2 = "MAPPING_SELECTED_FALLBACK_2"
NO_MAPPING_FEASIBLE_APPROVED_CLASS = "NO_MAPPING_FEASIBLE_APPROVED_CLASS"

_MAPPING_STATUS_FOR_POLICY_STATUS = {
    SELECTED_PREFERRED: MAPPING_SELECTED_PREFERRED,
    SELECTED_FALLBACK_1: MAPPING_SELECTED_FALLBACK_1,
    SELECTED_FALLBACK_2: MAPPING_SELECTED_FALLBACK_2,
    NO_FEASIBLE_APPROVED_CLASS: NO_MAPPING_FEASIBLE_APPROVED_CLASS,
}

# --- Mapping origins (§3.3) ------------------------------------------------
MAPPING_ORIGIN_EXACT = "EXACT"
MAPPING_ORIGIN_REDIRECT = "REDIRECT"
MAPPING_ORIGIN_UNRESOLVED = "UNRESOLVED"

# --- Why a member stayed unresolved. Machine-readable, never prose. --------
UNRESOLVED_NO_REDIRECT = "NO_LOCAL_MATCH_AND_NO_REDIRECT"
UNRESOLVED_REDIRECT_TARGET_NOT_LOCAL = "REDIRECT_TARGET_NOT_IN_LOCAL_KG"
UNRESOLVED_REDIRECT_CYCLE = "REDIRECT_CYCLE_DETECTED"
UNRESOLVED_REDIRECT_UNSAFE_TARGET = "UNSAFE_OR_MALFORMED_REDIRECT_TARGET"
UNRESOLVED_REDIRECT_LOOKUP_UNAVAILABLE = "REDIRECT_LOOKUP_UNAVAILABLE"
UNRESOLVED_REDIRECT_HOP_BUDGET = "REDIRECT_HOP_BUDGET_EXHAUSTED"
UNRESOLVED_NOT_AN_IRI = "MEMBER_IS_NOT_AN_IRI"

# --- Why a retrieval is not complete --------------------------------------
RETRIEVAL_COMPLETE = "RETRIEVAL_COMPLETE"
RETRIEVAL_PAGE_FAILED = "RETRIEVAL_PAGE_FAILED"
RETRIEVAL_PAGE_BUDGET_EXHAUSTED = "RETRIEVAL_PAGE_BUDGET_EXHAUSTED"
RETRIEVAL_CURSOR_UNUSABLE = "RETRIEVAL_CURSOR_UNUSABLE"

# --- Why a member was dropped after mapping -------------------------------
DROPPED_DUPLICATE_LOCAL_INDEX = "DUPLICATE_LOCAL_INDEX"
DROPPED_IS_THE_ANSWER = "IS_THE_ANSWER"


class MemberMapperError(Exception):
    """Base class for member-mapping failures."""


class OfflineCacheMissError(MemberMapperError):
    """Strict offline mode needed a page that the cache/export does not hold.

    Distinct from a network error: the endpoint was never contacted. Raised
    instead of falling back to HTTP, so an offline replay cannot quietly become a
    live run.
    """


class LocalKGVerificationError(MemberMapperError):
    """The pinned local KG is not the build this pilot was measured against."""


# --- Local lookup ----------------------------------------------------------

@dataclass(frozen=True)
class LocalLookup:
    """The result of looking one URI up in the pinned pickle's url_index."""

    uri: str
    local_index: Optional[int]
    lookup_form: Optional[str]

    @property
    def found(self) -> bool:
        return self.local_index is not None


class LocalIndexLookup(Protocol):
    """Just enough of LocalKG to map URIs, so tests need no 1.2 GB pickle."""

    def __call__(self, uri: str) -> LocalLookup:  # pragma: no cover - protocol
        ...


def make_local_lookup(url_index: Mapping[str, int]) -> Callable[[str], LocalLookup]:
    """Bind a url_index into a lookup that walks the labelled spelling ladder.

    Read-only: keys are never added, rewritten or normalized in place. The form
    that matched is returned so the run can report how many mappings depended on
    a spelling other than the exact one the endpoint returned.
    """
    def lookup(uri: str) -> LocalLookup:
        bare = strip_uri_brackets(uri)
        if not bare:
            return LocalLookup(uri=bare, local_index=None, lookup_form=None)
        for form, key in local_lookup_forms(bare):
            index = url_index.get(key)
            if index is not None:
                return LocalLookup(uri=bare, local_index=int(index),
                                   lookup_form=form)
        return LocalLookup(uri=bare, local_index=None, lookup_form=None)

    return lookup


def verify_local_kg_sha256(actual: str, expected: Optional[str]) -> str:
    """Refuse to map against a different local KG build.

    Node indices in this pickle were assigned by iterating a Python set, so a
    different build renumbers every node. Mapping a member to index 4,201,337
    against the wrong build is not an approximation, it is a different entity.
    """
    if expected is not None and actual != expected:
        raise LocalKGVerificationError(
            "pinned local KG SHA-256 mismatch; refusing to map against a "
            f"different build.\n  expected: {expected}\n  found:    {actual}"
        )
    return actual


# --- Phase A: retrieval ----------------------------------------------------

@dataclass(frozen=True)
class ClassRetrieval:
    """Everything retrieved for ONE approved class."""

    class_uri: str
    member_uris: tuple[str, ...]
    raw_member_count: int
    page_count: int
    page_size: int
    retrieval_complete: bool
    incomplete_reason: Optional[str]
    pages: tuple[PageResult, ...] = ()
    failures: tuple[PageFailure, ...] = ()
    non_iri_row_count: int = 0
    duplicate_row_count: int = 0

    @property
    def unique_member_count(self) -> int:
        return len(self.member_uris)

    def as_record(self) -> dict:
        return {
            "class_uri": self.class_uri,
            "raw_member_count": self.raw_member_count,
            "unique_member_count": self.unique_member_count,
            "duplicate_row_count": self.duplicate_row_count,
            "non_iri_row_count": self.non_iri_row_count,
            "page_count": self.page_count,
            "page_size": self.page_size,
            "retrieval_complete": self.retrieval_complete,
            "incomplete_reason": self.incomplete_reason,
            "failed_page_count": len(self.failures),
            "cache_origins": sorted({p.cache_origin for p in self.pages}),
        }

    def as_frozen_record(self) -> FrozenClassMembers:
        return FrozenClassMembers(
            class_uri=self.class_uri,
            member_uris=self.member_uris,
            page_count=self.page_count,
            page_size=self.page_size,
            retrieval_complete=self.retrieval_complete,
            raw_member_count=self.raw_member_count,
            duplicate_row_count=self.duplicate_row_count,
            non_iri_row_count=self.non_iri_row_count,
            incomplete_reason=self.incomplete_reason,
        )

    @classmethod
    def from_frozen_record(cls, frozen: FrozenClassMembers) -> "ClassRetrieval":
        """Rebuild a retrieval from the frozen export. No pages, no failures.

        `pages` is empty because the export deliberately carries no per-page
        provenance: page timestamps and cache origins are what would otherwise
        make the replay's output differ byte-for-byte from the live run's. The
        scientific quantities are all carried explicitly.
        """
        return cls(
            class_uri=frozen.class_uri,
            member_uris=frozen.member_uris,
            raw_member_count=frozen.raw_member_count,
            page_count=frozen.page_count,
            page_size=frozen.page_size,
            retrieval_complete=frozen.retrieval_complete,
            incomplete_reason=frozen.incomplete_reason,
            pages=(),
            failures=(),
            non_iri_row_count=frozen.non_iri_row_count,
            duplicate_row_count=frozen.duplicate_row_count,
        )


@dataclass
class CachedPageFetcher:
    """Cache-first page access. The single place a network call can happen.

    `client is None` means STRICT OFFLINE: a cache miss raises rather than
    reaching for a transport that does not exist. Because this is the only path
    to a page, "the offline replay made zero HTTP calls" is a property of the
    object graph, not a claim about which branches ran.
    """

    cache: Optional[PageCache]
    client: Optional[SparqlPageClient]
    endpoint: str
    network_page_count: int = 0
    cache_hit_count: int = 0
    stored_page_count: int = 0
    failed_page_count: int = 0

    @property
    def offline(self) -> bool:
        return self.client is None

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
        fingerprint = query_fingerprint(self.endpoint, query)
        if self.cache is not None:
            cached = self.cache.get_page(fingerprint)
            if cached is not None:
                self.cache_hit_count += 1
                return cached

        if self.client is None:
            raise OfflineCacheMissError(
                f"strict offline mode: no cached page for {query_kind} "
                f"page={page_index} class={class_uri!r} "
                f"(fingerprint {fingerprint[:16]}...); the live run did not "
                f"store it, so the replay cannot proceed without HTTP"
            )

        try:
            page = self.client.fetch(
                query,
                query_kind=query_kind,
                class_uri=class_uri,
                page_index=page_index,
                cursor_after=cursor_after,
                page_size=page_size,
            )
        except PageRetrievalFailed as exc:
            self.failed_page_count += 1
            if self.cache is not None:
                # Recorded in the FAILURES table, which get_page() never reads.
                self.cache.record_failure(exc.failure)
            raise

        self.network_page_count += 1
        if self.cache is not None:
            self.cache.put_page(page)
            self.stored_page_count += 1
        return page

    def counters(self) -> dict:
        return {
            "offline": self.offline,
            "network_pages": self.network_page_count,
            "cache_hits": self.cache_hit_count,
            "pages_stored": self.stored_page_count,
            "failed_pages": self.failed_page_count,
        }


@dataclass
class ClassMemberRetriever:
    """Bounded, resumable keyset pagination over one class's members.

    Resume needs no bookmark. The cache key is sha256(endpoint + query text) and
    page N's query text embeds page N-1's last member as its cursor, so re-running
    an interrupted retrieval regenerates the identical key chain and every
    already-stored page is a hit. The position IS the query.
    """

    fetcher: CachedPageFetcher
    page_size: int = DEFAULT_PAGE_SIZE
    max_pages: int = DEFAULT_MAX_PAGES

    def retrieve(self, class_uri: str) -> ClassRetrieval:
        pages: list[PageResult] = []
        failures: list[PageFailure] = []
        # dict, not set: preserves first-seen order for the duplicate tally while
        # the emitted member list is sorted independently.
        seen: dict[str, None] = {}
        raw_rows = 0
        non_iri_rows = 0
        duplicate_rows = 0
        cursor: Optional[str] = None
        complete = False
        reason: Optional[str] = None

        for page_index in range(int(self.max_pages)):
            query = build_class_members_page_query(
                class_uri, page_size=self.page_size, after=cursor)
            try:
                page = self.fetcher.fetch(
                    query,
                    query_kind=QueryKind.CLASS_MEMBERS_PAGE.value,
                    class_uri=class_uri,
                    page_index=page_index,
                    cursor_after=cursor,
                    page_size=self.page_size,
                )
            except PageRetrievalFailed as exc:
                # Preserve every page retrieved so far: a partial verdict must
                # keep its successful cache (§7).
                failures.append(exc.failure)
                reason = RETRIEVAL_PAGE_FAILED
                break

            pages.append(page)
            raw_rows += page.row_count

            last_raw: Optional[str] = None
            for row in page.rows:
                value = binding_value(row, "member")
                last_raw = value if value is not None else last_raw
                if not is_iri_member(value):
                    non_iri_rows += 1
                    continue
                bare = strip_uri_brackets(value)
                if bare in seen:
                    duplicate_rows += 1
                    continue
                seen[bare] = None

            if page.is_terminal_page:
                complete = True
                break

            if last_raw is None or not is_safe_iri(last_raw):
                # Without a usable cursor the next page cannot be requested
                # deterministically. Stopping and saying so is the only honest
                # option; guessing a cursor could skip or repeat members.
                reason = RETRIEVAL_CURSOR_UNUSABLE
                break
            cursor = strip_uri_brackets(last_raw)
        else:
            reason = RETRIEVAL_PAGE_BUDGET_EXHAUSTED

        return ClassRetrieval(
            class_uri=class_uri,
            member_uris=tuple(sorted(seen)),
            raw_member_count=raw_rows,
            page_count=len(pages),
            page_size=int(self.page_size),
            retrieval_complete=complete,
            incomplete_reason=None if complete else reason,
            pages=tuple(pages),
            failures=tuple(failures),
            non_iri_row_count=non_iri_rows,
            duplicate_row_count=duplicate_rows,
        )


@dataclass
class FrozenClassMemberRetriever:
    """Replay one class's members from the frozen export. No SQLite, no HTTP.

    Exposes the same `retrieve(class_uri)` shape as ClassMemberRetriever, so
    retrieve_all_classes() and every downstream mapping function are identical in
    both modes. That is what makes "semantically identical mapping outputs" a
    consequence of the structure rather than a coincidence to be checked.
    """

    export: FrozenExport

    def retrieve(self, class_uri: str) -> ClassRetrieval:
        return ClassRetrieval.from_frozen_record(
            self.export.members_for(strip_uri_brackets(class_uri)))


class ClassMemberRetrieverLike(Protocol):
    def retrieve(self, class_uri: str) -> ClassRetrieval:  # pragma: no cover
        ...


def retrieve_all_classes(
    class_uris: Sequence[str],
    retriever: ClassMemberRetrieverLike,
) -> dict[str, ClassRetrieval]:
    """Retrieve every UNIQUE approved class exactly once, in sorted URI order.

    §3.2 requires every unique approved class, not only the first feasible one, so
    the pilot can report what each fallback would have yielded. Deduplication
    matters here: Category:Japanese_Nobel_laureates is the preferred class of
    three different Answers and must cost one retrieval, not three.
    """
    unique = tuple(sorted({strip_uri_brackets(c) for c in class_uris}))
    return {uri: retriever.retrieve(uri) for uri in unique}


# --- Phase A: redirect resolution ------------------------------------------

REDIRECT_RESOLVED = "REDIRECT_RESOLVED"
REDIRECT_NONE_FOUND = "NO_REDIRECT_FOUND"
REDIRECT_TARGET_NOT_LOCAL = "REDIRECT_TARGET_NOT_IN_LOCAL_KG"
REDIRECT_CYCLE = "REDIRECT_CYCLE_DETECTED"
REDIRECT_UNSAFE_TARGET = "UNSAFE_OR_MALFORMED_REDIRECT_TARGET"
REDIRECT_LOOKUP_UNAVAILABLE = "REDIRECT_LOOKUP_UNAVAILABLE"
REDIRECT_HOP_BUDGET_EXHAUSTED = "REDIRECT_HOP_BUDGET_EXHAUSTED"

_REDIRECT_STATUS_TO_UNRESOLVED_REASON = {
    REDIRECT_NONE_FOUND: UNRESOLVED_NO_REDIRECT,
    REDIRECT_TARGET_NOT_LOCAL: UNRESOLVED_REDIRECT_TARGET_NOT_LOCAL,
    REDIRECT_CYCLE: UNRESOLVED_REDIRECT_CYCLE,
    REDIRECT_UNSAFE_TARGET: UNRESOLVED_REDIRECT_UNSAFE_TARGET,
    REDIRECT_LOOKUP_UNAVAILABLE: UNRESOLVED_REDIRECT_LOOKUP_UNAVAILABLE,
    REDIRECT_HOP_BUDGET_EXHAUSTED: UNRESOLVED_REDIRECT_HOP_BUDGET,
}


@dataclass(frozen=True)
class RedirectOutcome:
    """How redirect resolution ended for ONE member that had no exact match."""

    source_uri: str
    status: str
    chain: tuple[str, ...]
    resolved_uri: Optional[str]
    local_index: Optional[int]
    lookup_form: Optional[str]

    @property
    def resolved(self) -> bool:
        return self.status == REDIRECT_RESOLVED

    def as_record(self) -> dict:
        return {
            "source_uri": self.source_uri,
            "redirect_status": self.status,
            "redirect_chain": list(self.chain),
            "redirect_target_uri": self.resolved_uri,
            "local_index": self.local_index,
            "local_lookup_form": self.lookup_form,
        }


class RedirectSource(Protocol):
    """Answers "what does this URI redirect to", one batch at a time."""

    def redirect_targets(self, source_uris: Sequence[str]
                         ) -> tuple[Mapping[str, str], frozenset[str]]:
        """(source -> target for hits, sources whose lookup was UNAVAILABLE).

        A source that was queried successfully and has no redirect is absent from
        the mapping AND absent from the unavailable set — the third state that a
        bare None would collapse.
        """
        ...  # pragma: no cover - protocol


@dataclass
class SparqlRedirectSource:
    """Batched dbo:wikiPageRedirects lookups. owl:sameAs is never traversed.

    Batching via VALUES turns N unresolved members into ceil(N / batch_size)
    requests. The batch content is sorted before the query is built, so the query
    text — and therefore its cache key — depends only on the member SET, never on
    the order they happened to be discovered in.
    """

    fetcher: CachedPageFetcher
    batch_size: int = DEFAULT_REDIRECT_BATCH_SIZE
    pages: list[PageResult] = field(default_factory=list)
    failures: list[PageFailure] = field(default_factory=list)

    def redirect_targets(self, source_uris: Sequence[str]
                         ) -> tuple[Mapping[str, str], frozenset[str]]:
        ordered = tuple(sorted({strip_uri_brackets(u) for u in source_uris if u}))
        if not ordered:
            return {}, frozenset()

        targets: dict[str, str] = {}
        unavailable: set[str] = set()
        size = max(1, int(self.batch_size))
        for start in range(0, len(ordered), size):
            batch = ordered[start:start + size]
            query = build_redirect_batch_query(batch)
            try:
                page = self.fetcher.fetch(
                    query,
                    query_kind=QueryKind.REDIRECT_BATCH.value,
                    class_uri=None,
                    page_index=start // size,
                    cursor_after=None,
                    page_size=None,
                )
            except PageRetrievalFailed as exc:
                # The whole batch is unavailable, NOT "these members have no
                # redirect". Turning a transport failure into that finding would
                # manufacture a negative fact about DBpedia.
                self.failures.append(exc.failure)
                unavailable.update(batch)
                continue

            self.pages.append(page)
            for row in page.rows:
                source = binding_value(row, "source")
                target = binding_value(row, "target")
                if not is_safe_iri(source) or target is None:
                    continue
                bare_source = strip_uri_brackets(source)
                # First target in the query's deterministic ORDER BY wins, so a
                # page with several targets for one source resolves stably.
                targets.setdefault(bare_source, strip_uri_brackets(target))

        return targets, frozenset(unavailable)


@dataclass
class FrozenRedirectSource:
    """Redirect answers replayed from the frozen export. No SQLite, no HTTP."""

    export: FrozenExport

    def redirect_targets(self, source_uris: Sequence[str]
                         ) -> tuple[Mapping[str, str], frozenset[str]]:
        targets: dict[str, str] = {}
        unavailable: set[str] = set()
        for uri in sorted({strip_uri_brackets(u) for u in source_uris if u}):
            if uri not in self.export.queried_redirect_sources:
                # Never queried in the live run: the export cannot invent an
                # answer, and claiming "no redirect" would fabricate evidence.
                unavailable.add(uri)
                continue
            target = self.export.redirects.get(uri)
            if target is not None:
                targets[uri] = target
        return targets, frozenset(unavailable)


def resolve_redirect_chains(
    source_uris: Sequence[str],
    redirect_source: RedirectSource,
    local_lookup: Callable[[str], LocalLookup],
    *,
    max_hops: int = DEFAULT_MAX_REDIRECT_HOPS,
) -> dict[str, RedirectOutcome]:
    """Follow dbo:wikiPageRedirects, bounded and cycle-safe, for URIs with no
    exact local match.

    Direction matters: `?member dbo:wikiPageRedirects ?target` means the MEMBER is
    a redirect stub and the TARGET is the canonical article. The local infobox KG
    holds articles, not stubs, so the target is the right thing to look up.

    Chains are followed at most `max_hops` times. Each chain carries its own
    visited list, so a cycle A -> B -> A is reported as REDIRECT_CYCLE_DETECTED
    rather than looping. A target that is itself unsafe stops that chain with
    UNSAFE_OR_MALFORMED_REDIRECT_TARGET rather than being interpolated into the
    next query.

    The four ways a chain can end without a local node are kept apart, because
    they license different conclusions:
      NO_REDIRECT_FOUND            the member is not a redirect at all;
      REDIRECT_TARGET_NOT_IN_LOCAL_KG  the chain ENDED and its final target is
                                   absent from this dump — an open-world absence,
                                   not a claim the entity does not exist;
      REDIRECT_HOP_BUDGET_EXHAUSTED    OUR max_hops stopped the walk, so whether a
                                   further hop would reach a local node is unknown;
      REDIRECT_LOOKUP_UNAVAILABLE  the endpoint did not answer; nothing follows.
    """
    pending = {
        uri: [uri] for uri in sorted({strip_uri_brackets(u) for u in source_uris if u})
    }
    outcomes: dict[str, RedirectOutcome] = {}
    hop_budget = max(0, int(max_hops))

    def finish(source: str, status: str, chain: Sequence[str],
               lookup: Optional[LocalLookup] = None) -> None:
        outcomes[source] = RedirectOutcome(
            source_uri=source,
            status=status,
            chain=tuple(chain[1:]),          # hop targets only, not the source
            resolved_uri=None if lookup is None else lookup.uri,
            local_index=None if lookup is None else lookup.local_index,
            lookup_form=None if lookup is None else lookup.lookup_form,
        )

    for hop in range(hop_budget):
        if not pending:
            break
        last_hop = hop == hop_budget - 1
        frontier = sorted(chain[-1] for chain in pending.values())
        targets, unavailable = redirect_source.redirect_targets(frontier)

        still_pending: dict[str, list[str]] = {}
        for source, chain in sorted(pending.items()):
            current = chain[-1]
            if current in unavailable:
                finish(source, REDIRECT_LOOKUP_UNAVAILABLE, chain)
                continue
            target = targets.get(current)
            if target is None:
                # A chain longer than the source alone means a redirect WAS
                # followed and has now terminated; the reportable fact is that its
                # final target is not in this dump, not that no redirect exists.
                finish(source,
                       REDIRECT_TARGET_NOT_LOCAL if len(chain) > 1
                       else REDIRECT_NONE_FOUND,
                       chain)
                continue
            if not is_safe_iri(target):
                finish(source, REDIRECT_UNSAFE_TARGET, chain + [target])
                continue
            if target in chain:
                finish(source, REDIRECT_CYCLE, chain + [target])
                continue
            extended = chain + [target]
            lookup = local_lookup(target)
            if lookup.found:
                finish(source, REDIRECT_RESOLVED, extended, lookup)
            elif last_hop:
                # Our budget, not the data, ended this walk.
                finish(source, REDIRECT_HOP_BUDGET_EXHAUSTED, extended)
            else:
                still_pending[source] = extended
        pending = still_pending

    # Only reachable with max_hops == 0: nothing was attempted, so nothing was
    # observed. Reported rather than silently dropped.
    for source, chain in sorted(pending.items()):
        finish(source, REDIRECT_LOOKUP_UNAVAILABLE, chain)
    return outcomes


# --- Phase B: local mapping (pure) ----------------------------------------

@dataclass(frozen=True)
class MappedMember:
    """One retrieved member and how it did or did not reach a local node.

    `raw_member_uri` is preserved verbatim: §3.3 forbids rewriting or discarding
    it, because it is the only link back to what the endpoint actually returned.
    """

    raw_member_uri: str
    normalized_member_uri: str
    redirect_target_uri: Optional[str]
    mapping_origin: str
    local_index: Optional[int]
    local_lookup_form: Optional[str]
    unresolved_reason: Optional[str]
    dropped_reason: Optional[str]
    redirect_chain: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        """A mapped local candidate that survived dedup and Answer exclusion."""
        return self.local_index is not None and self.dropped_reason is None

    def as_record(self) -> dict:
        return {
            "raw_member_uri": self.raw_member_uri,
            "normalized_member_uri": self.normalized_member_uri,
            "redirect_target_uri": self.redirect_target_uri,
            "redirect_chain": list(self.redirect_chain),
            "mapping_origin": self.mapping_origin,
            "local_index": self.local_index,
            "local_lookup_form": self.local_lookup_form,
            "unresolved_reason": self.unresolved_reason,
            "dropped_reason": self.dropped_reason,
            "accepted": self.accepted,
        }


@dataclass(frozen=True)
class ClassMappingResult:
    """The mapping outcome for one Answer/class pair. No graph work involved."""

    answer_uri: str
    answer_local_index: Optional[int]
    class_uri: str
    class_position: str
    members: tuple[MappedMember, ...]
    local_candidate_indices: tuple[int, ...]
    retrieval: ClassRetrieval

    @property
    def exact_mapped_count(self) -> int:
        return sum(1 for m in self.members
                   if m.mapping_origin == MAPPING_ORIGIN_EXACT)

    @property
    def redirect_mapped_count(self) -> int:
        return sum(1 for m in self.members
                   if m.mapping_origin == MAPPING_ORIGIN_REDIRECT)

    @property
    def unresolved_count(self) -> int:
        return sum(1 for m in self.members
                   if m.mapping_origin == MAPPING_ORIGIN_UNRESOLVED)

    @property
    def duplicate_dropped_count(self) -> int:
        return sum(1 for m in self.members
                   if m.dropped_reason == DROPPED_DUPLICATE_LOCAL_INDEX)

    @property
    def answer_excluded_count(self) -> int:
        return sum(1 for m in self.members
                   if m.dropped_reason == DROPPED_IS_THE_ANSWER)

    @property
    def mapped_candidate_count(self) -> int:
        """Distinct local candidates, Answer excluded. The gate's input."""
        return len(self.local_candidate_indices)

    @property
    def passes_mapping_gate(self) -> bool:
        """MAPPING-stage gate only. NOT graph-budget feasibility."""
        return self.mapped_candidate_count >= MIN_MAPPED_LOCAL_CANDIDATES

    def as_summary_record(self) -> dict:
        record = {
            "answer_uri": self.answer_uri,
            "answer_local_index": self.answer_local_index,
            "class_uri": self.class_uri,
            "class_position": self.class_position,
            "exact_local_mappings": self.exact_mapped_count,
            "redirect_local_mappings": self.redirect_mapped_count,
            "unresolved_members": self.unresolved_count,
            "duplicate_local_index_dropped": self.duplicate_dropped_count,
            "answer_excluded_count": self.answer_excluded_count,
            "mapped_candidate_count_excluding_answer": self.mapped_candidate_count,
            "mapping_gate_threshold": MIN_MAPPED_LOCAL_CANDIDATES,
            "passes_mapping_gate": self.passes_mapping_gate,
        }
        record.update(self.retrieval.as_record())
        return record


def map_class_members(
    answer_uri: str,
    class_uri: str,
    class_position: str,
    retrieval: ClassRetrieval,
    local_lookup: Callable[[str], LocalLookup],
    redirect_outcomes: Mapping[str, RedirectOutcome],
) -> ClassMappingResult:
    """Map one class's retrieved members onto local node indices. PURE.

    No network, no cache, no SQLite: every redirect answer was frozen in Phase A.
    That is what makes the mapping-gate walk in
    select_mapping_class_for_answer() free of hidden network calls (§3.5).

    Steps, in order (§3.4): normalize -> exact lookup -> redirect fallback ->
    deduplicate by final local index -> exclude the Answer node.
    """
    answer_lookup = local_lookup(answer_uri)
    answer_index = answer_lookup.local_index

    members: list[MappedMember] = []
    accepted_indices: list[int] = []
    claimed: set[int] = set()

    # Sorted iteration: determinism, and it also fixes WHICH duplicate wins when
    # two distinct member URIs map to the same local node — the first in URI
    # order is kept and the rest are recorded as dropped.
    for raw in retrieval.member_uris:
        normalized = strip_uri_brackets(raw)

        if not is_iri_member(normalized):
            members.append(MappedMember(
                raw_member_uri=raw, normalized_member_uri=normalized,
                redirect_target_uri=None,
                mapping_origin=MAPPING_ORIGIN_UNRESOLVED,
                local_index=None, local_lookup_form=None,
                unresolved_reason=UNRESOLVED_NOT_AN_IRI, dropped_reason=None,
            ))
            continue

        lookup = local_lookup(normalized)
        if lookup.found:
            origin = MAPPING_ORIGIN_EXACT
            index = lookup.local_index
            form = lookup.lookup_form
            redirect_target = None
            chain: tuple[str, ...] = ()
            unresolved_reason = None
        else:
            outcome = redirect_outcomes.get(normalized)
            if outcome is None:
                # No redirect answer was frozen for this member. Reporting it as
                # unavailable is honest; asserting "no redirect" would invent an
                # observation that was never made.
                origin = MAPPING_ORIGIN_UNRESOLVED
                index = None
                form = None
                redirect_target = None
                chain = ()
                unresolved_reason = UNRESOLVED_REDIRECT_LOOKUP_UNAVAILABLE
            elif outcome.resolved:
                origin = MAPPING_ORIGIN_REDIRECT
                index = outcome.local_index
                form = outcome.lookup_form
                redirect_target = outcome.resolved_uri
                chain = outcome.chain
                unresolved_reason = None
            else:
                origin = MAPPING_ORIGIN_UNRESOLVED
                index = None
                form = None
                redirect_target = outcome.chain[-1] if outcome.chain else None
                chain = outcome.chain
                unresolved_reason = _REDIRECT_STATUS_TO_UNRESOLVED_REASON.get(
                    outcome.status, UNRESOLVED_NO_REDIRECT)

        dropped: Optional[str] = None
        if index is not None:
            if answer_index is not None and index == answer_index:
                dropped = DROPPED_IS_THE_ANSWER      # §3.4 step 5
            elif index in claimed:
                dropped = DROPPED_DUPLICATE_LOCAL_INDEX   # §3.4 step 4
            else:
                claimed.add(index)
                accepted_indices.append(index)

        members.append(MappedMember(
            raw_member_uri=raw,
            normalized_member_uri=normalized,
            redirect_target_uri=redirect_target,
            mapping_origin=origin,
            local_index=index,
            local_lookup_form=form,
            unresolved_reason=unresolved_reason,
            dropped_reason=dropped,
            redirect_chain=chain,
        ))

    return ClassMappingResult(
        answer_uri=strip_uri_brackets(answer_uri),
        answer_local_index=answer_index,
        class_uri=strip_uri_brackets(class_uri),
        class_position=class_position,
        members=tuple(members),
        # Sorted by local index: a deterministic serialisation order, NOT a
        # scientific candidate priority. See local_candidate_profile.py.
        local_candidate_indices=tuple(sorted(accepted_indices)),
        retrieval=retrieval,
    )


# --- Phase B: the mapping-stage gate --------------------------------------

@dataclass(frozen=True)
class AnswerMappingOutcome:
    """One Answer's mapping-stage verdict, with all three classes reported."""

    answer_uri: str
    pilot_slot: int
    display_label: str
    status: str
    selected_class_uri: Optional[str]
    selected_position: Optional[str]
    per_class: tuple[ClassMappingResult, ...]
    selection: ClassSelectionResult

    @property
    def has_mapping_feasible_class(self) -> bool:
        return self.status != NO_MAPPING_FEASIBLE_APPROVED_CLASS

    def result_for_position(self, position: str) -> ClassMappingResult:
        for result in self.per_class:
            if result.class_position == position:
                return result
        raise KeyError(f"no mapping result at class position {position!r}")

    @property
    def selected_result(self) -> Optional[ClassMappingResult]:
        if self.selected_position is None:
            return None
        return self.result_for_position(self.selected_position)

    def as_record(self) -> dict:
        selected = self.selected_result
        return {
            "pilot_slot": self.pilot_slot,
            "answer_uri": self.answer_uri,
            "display_label": self.display_label,
            "mapping_stage_status": self.status,
            "selected_class_position": self.selected_position,
            "selected_class_uri": self.selected_class_uri,
            "selected_mapped_candidate_count": (
                None if selected is None else selected.mapped_candidate_count),
            "mapping_gate_threshold": MIN_MAPPED_LOCAL_CANDIDATES,
            "attempts": [
                {
                    "class_position": r.class_position,
                    "class_uri": r.class_uri,
                    "mapped_candidate_count_excluding_answer":
                        r.mapped_candidate_count,
                    "passes_mapping_gate": r.passes_mapping_gate,
                    "retrieval_complete": r.retrieval.retrieval_complete,
                }
                for r in self.per_class
            ],
            "note": (
                "passes_mapping_gate is a NECESSARY MAPPING condition only; it is "
                "not graph-budget feasibility and does not imply that these "
                "candidates fit under DEFAULT_MAX_NODES"
            ),
        }


def select_mapping_class_for_answer(
    row: AnswerClassPolicy,
    per_class: Sequence[ClassMappingResult],
) -> AnswerMappingOutcome:
    """Walk the approved classes in order; report the first passing the gate.

    All three classes are already mapped before this runs, and the callback below
    reads nothing but a frozen integer per class — no network, no cache, no
    lazy retrieval. §3.5 requires exactly that.
    """
    by_position = {r.class_position: r for r in per_class}
    missing = [p for p, _ in row.ordered_positions if p not in by_position]
    if missing:
        raise MemberMapperError(
            f"Answer {row.answer_uri!r}: no mapping result for class position(s) "
            f"{missing}; all three approved classes must be mapped before the "
            f"gate is evaluated"
        )
    for result in per_class:
        # Chokepoint: an unapproved class can never reach the gate.
        row.require_approved_class(result.class_uri)

    frozen_counts = {
        by_position[position].class_uri: by_position[position].mapped_candidate_count
        for position, _ in row.ordered_positions
    }

    def is_feasible(class_uri: str) -> object:
        count = frozen_counts[class_uri]

        class Verdict:
            detail = (f"{count} mapped local candidate(s) excluding the Answer; "
                      f"mapping gate >= {MIN_MAPPED_LOCAL_CANDIDATES}")

            def __bool__(self) -> bool:
                return count >= MIN_MAPPED_LOCAL_CANDIDATES

        return Verdict()

    selection = select_first_feasible_class(row, is_feasible)
    return AnswerMappingOutcome(
        answer_uri=row.answer_uri,
        pilot_slot=row.pilot_slot,
        display_label=row.display_label,
        status=_MAPPING_STATUS_FOR_POLICY_STATUS[selection.status],
        selected_class_uri=selection.first_feasible_class,
        selected_position=selection.selected_position,
        per_class=tuple(by_position[p] for p, _ in row.ordered_positions),
        selection=selection,
    )


def collect_unmatched_members(
    retrievals: Mapping[str, ClassRetrieval],
    local_lookup: Callable[[str], LocalLookup],
) -> tuple[str, ...]:
    """Every retrieved member with no exact local match, deduplicated and sorted.

    Redirects are resolved for this union once, rather than per class, so a member
    shared by two approved classes costs one lookup.
    """
    unmatched: set[str] = set()
    for retrieval in retrievals.values():
        for raw in retrieval.member_uris:
            normalized = strip_uri_brackets(raw)
            if not is_iri_member(normalized):
                continue
            if not local_lookup(normalized).found:
                unmatched.add(normalized)
    return tuple(sorted(unmatched))


def frozen_redirect_records(
    outcomes: Mapping[str, RedirectOutcome],
) -> tuple[FrozenRedirect, ...]:
    """Flatten resolved chains into per-hop records for the frozen export.

    Every hop is exported, not only the first, so a replay can reconstruct the
    same chain — including a cycle — without re-querying. A confirmed absence is
    exported as target_uri = null; a source that was never queried is simply not
    exported, which keeps the three states distinguishable on reload.
    """
    records: dict[str, Optional[str]] = {}
    for outcome in sorted(outcomes.values(), key=lambda o: o.source_uri):
        hops = (outcome.source_uri,) + outcome.chain
        if outcome.status == REDIRECT_LOOKUP_UNAVAILABLE:
            # Nothing was observed; exporting a null would fabricate an answer.
            continue
        for position, current in enumerate(hops[:-1]):
            records.setdefault(current, hops[position + 1])
        if outcome.status in (REDIRECT_NONE_FOUND, REDIRECT_TARGET_NOT_LOCAL):
            records.setdefault(hops[-1], None)
    return tuple(
        FrozenRedirect(source_uri=source, target_uri=target)
        for source, target in sorted(records.items())
    )
