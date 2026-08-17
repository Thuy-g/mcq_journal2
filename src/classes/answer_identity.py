############################################################################
# src/classes/answer_identity.py
#
# ONE ENTITY, THREE URIs — the Answer-identity bridge between the CURRENT public
# DBpedia endpoint and the PINNED March-2023 local infobox KG.
#
# WHY AN ENTITY NEEDS THREE URIs AND WHY THEY MUST NOT BE COLLAPSED
# ------------------------------------------------------------------
# The class selector asks the LIVE endpoint what categories an Answer has. The
# graph, evidence and LRoleSim stages read a PINNED dump taken in March 2023.
# Those are two different corpora observed three years apart, and DBpedia
# renames resources between them. Measured on this project's own corpus:
#
#     pinned March-2023 URI                      current public DBpedia URI
#     ---------------------------------------    --------------------------------
#     dbr:Akira_Suzuki_(chemist)                 dbr:Akira_Suzuki
#     dbr:Makoto_Kobayashi_(physicist)           dbr:Makoto_Kobayashi
#     dbr:Xun_Kuang                              dbr:Xunzi_(philosopher)
#     dbr:Monzaemon_Chikamatsu                   dbr:Chikamatsu_Monzaemon
#
# So three URIs, each answering a different question:
#
#   original_uri     what the researcher or the dataset actually wrote. It is the
#                    IMMUTABLE AUDIT IDENTITY. Every report keys on it, and it is
#                    never rewritten, because a batch whose input column silently
#                    changed spelling cannot be reconciled with the file it came
#                    from.
#
#   remote_query_uri the resource whose CURRENT dcterms:subject categories,
#                    label and dbo:description are queried. Using the historical
#                    spelling here yields a Wikipedia lead but zero categories,
#                    and the Answer is then reported as having no usable class
#                    when in fact it has many.
#
#   local_kg_uri     the resource that EXISTS AS A NODE in the pinned pickle.
#                    Using the current spelling here yields no node at all, and
#                    the run stops with "absent from the pinned local KG" for an
#                    entity that is plainly present under its 2023 name.
#
# Collapsing any two of them produces a run that is wrong in a way that looks
# like a data problem. Keeping them apart makes each failure name its own stage.
#
# WHY THE PINNED KG IS NOT RENAMED, MIGRATED OR REGENERATED
# ----------------------------------------------------------
# Node indices in that pickle were assigned by iterating a Python set. Rebuilding
# it renumbers every node, which invalidates every recorded local index, every
# frozen LRoleSim fingerprint and every score cache in the repository. The dump
# is a pinned experimental artefact, not a database to be kept current, and
# CLAUDE.md forbids touching it. The bridge is therefore built in code, at
# read time, and recorded per Answer.
#
# WHY A WIKIPEDIA REDIRECT AND A DBpedia RESOURCE REDIRECT ARE DIFFERENT FACTS
# -----------------------------------------------------------------------------
# `classes.wikipedia_lead` already follows redirects — MediaWiki's, over ARTICLE
# TITLES, to find the page whose lead text becomes the semantic query vector.
# That says nothing about which DBpedia RESOURCE carries the dcterms:subject
# triples: the two namespaces are maintained by different processes and are not
# guaranteed to agree at any moment. This module therefore resolves
# `dbo:wikiPageRedirects` on the DBpedia side and records that chain separately;
# `owl:sameAs` is never traversed, exactly as in `classes.member_mapper`,
# because it would substitute another KG's entity.
#
# WHY THE ANSWER MUST BE EXCLUDED BY RESOLVED LOCAL IDENTITY
# -----------------------------------------------------------
# A class roster retrieved from the current endpoint returns the CURRENT
# spelling. The Answer as supplied may be the HISTORICAL one. Comparing raw URI
# strings then finds no match, and the Answer is silently admitted as its own
# distractor — an item whose correct answer is also one of its wrong answers.
# Exclusion is therefore performed on the resolved LOCAL NODE INDEX, which is
# one integer per entity however many spellings point at it. `map_class_members`
# already does exactly this; this module's job is to give it the right Answer URI
# so that the index it compares against is the right index.
#
# THE FOUR MEASURED PAIRS ABOVE ARE REGRESSION FIXTURES, NOT PRODUCTION DATA.
# Nothing in this file branches on an entity. There is no mapping table: the
# pairs are rediscovered from `dbo:wikiPageRedirects` evidence every run, and the
# tests assert that the source contains no hard-coded resource name.
#
# IMPORT-TIME PURITY: no network, no sqlite connection, no file read at import.
############################################################################

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

from classes.sparql_client import (
    DEFAULT_MAX_REDIRECT_HOPS,
    strip_uri_brackets,
    is_safe_iri,
    validate_iri,
)

__all__ = [
    "IDENTITY_SCHEMA_VERSION",
    "DEFAULT_MAX_IDENTITY_HOPS",
    "RemoteRedirectStatus",
    "LocalResolutionMethod",
    "IdentityStatus",
    "AnswerIdentity",
    "IdentityEvidenceSource",
    "build_category_presence_query",
    "build_forward_redirect_query",
    "build_reverse_redirect_query",
    "SparqlIdentitySource",
    "resolve_remote_query_uri",
    "resolve_answer_identity",
]

IDENTITY_SCHEMA_VERSION = "answer_identity_v1"

#: Redirect chains are bounded. DBpedia redirect chains are normally one hop;
#: three is the same budget `classes.sparql_client` already declares for member
#: redirects, reused so the project has ONE redirect budget rather than two.
DEFAULT_MAX_IDENTITY_HOPS = DEFAULT_MAX_REDIRECT_HOPS

RESOURCE_PREFIX = "http://dbpedia.org/resource/"
CATEGORY_PREFIX = "http://dbpedia.org/resource/Category:"

QID_PREFIX = "#qid:"
QID_CATEGORY_PRESENCE = "identity_category_presence"
QID_FORWARD_REDIRECT = "identity_forward_redirect"
QID_REVERSE_REDIRECT = "identity_reverse_redirect"

_PREFIXES = (
    "PREFIX dcterms: <http://purl.org/dc/terms/>\n"
    "PREFIX dbo:     <http://dbpedia.org/ontology/>"
)


class RemoteRedirectStatus(str, Enum):
    """How the CURRENT-DBpedia redirect walk ended. Six outcomes, never merged.

    Each licenses a different conclusion, and collapsing any two of them would
    make a transport problem indistinguishable from a fact about the graph:

    NO_REDIRECT   the URI is not a redirect. It is the current resource.
    FOLLOWED      a chain was followed to a terminal, non-redirecting resource.
    QUERY_FAILED  the endpoint did not answer. NOTHING follows — in particular
                  not "there is no redirect".
    CYCLE         A -> B -> A. The data is inconsistent; no target is chosen.
    UNSAFE_TARGET the target could not be safely interpolated into a query, so
                  the walk stopped rather than building a query from it.
    MAX_HOPS      OUR hop budget stopped the walk. Whether a further hop would
                  have reached a terminal resource is unknown.
    """

    NO_REDIRECT = "NO_REDIRECT"
    FOLLOWED = "FOLLOWED"
    QUERY_FAILED = "QUERY_FAILED"
    CYCLE = "CYCLE"
    UNSAFE_TARGET = "UNSAFE_TARGET"
    MAX_HOPS = "MAX_HOPS"


class LocalResolutionMethod(str, Enum):
    """HOW the pinned-KG node was found. The resolution order is this list.

    ORIGINAL_URI            the supplied URI is itself a node. Nothing else is
                            attempted: the researcher's own spelling wins when it
                            works, and no query is spent.
    REMOTE_QUERY_URI        the current canonical URI is a node.
    REVERSE_REDIRECT_ALIAS  some OTHER URI redirects to the current canonical URI
                            on today's DBpedia and IS a node in the pinned dump.
                            This is the Xun_Kuang / Xunzi_(philosopher) case.
    NOT_RESOLVED            no admissible spelling is a node here. An open-world
                            absence from one dump, never a claim about existence.
    AMBIGUOUS               two or more distinct local nodes were admissible and
                            the declared rule does not choose between them.
                            Reported, never guessed.
    """

    ORIGINAL_URI = "ORIGINAL_URI_IN_LOCAL_KG"
    REMOTE_QUERY_URI = "REMOTE_QUERY_URI_IN_LOCAL_KG"
    REVERSE_REDIRECT_ALIAS = "LOCAL_ALIAS_VIA_REVERSE_REDIRECT"
    NOT_RESOLVED = "NO_LOCAL_URI_IDENTITY"
    AMBIGUOUS = "AMBIGUOUS_LOCAL_ALIAS"


class IdentityStatus(str, Enum):
    """The overall verdict for one Answer's identity resolution."""

    RESOLVED = "IDENTITY_RESOLVED"
    NO_LOCAL_IDENTITY = "NO_LOCAL_URI_IDENTITY"
    AMBIGUOUS_LOCAL_ALIAS = "AMBIGUOUS_LOCAL_ALIAS"
    INPUT_INVALID = "INPUT_INVALID"


@dataclass(frozen=True)
class AnswerIdentity:
    """One Answer's three URIs and the complete evidence for each of them.

    A single auditable record rather than several loose variables, so that a
    caller cannot accidentally hand a remote spelling to a local stage: there is
    exactly one field for each question, each is named for the question it
    answers, and every one of them is written by this module alone.
    """

    original_uri: str
    remote_query_uri: Optional[str] = None
    local_kg_uri: Optional[str] = None
    local_index: Optional[int] = None
    local_lookup_form: Optional[str] = None
    remote_redirect_used: bool = False
    remote_redirect_status: str = RemoteRedirectStatus.NO_REDIRECT.value
    remote_redirect_chain: tuple[str, ...] = ()
    local_resolution_method: str = LocalResolutionMethod.NOT_RESOLVED.value
    local_alias_candidates: tuple[str, ...] = ()
    resolution_status: str = IdentityStatus.NO_LOCAL_IDENTITY.value
    original_uri_has_current_categories: Optional[bool] = None
    original_uri_current_category_count: Optional[int] = None
    remote_query_uri_current_category_count: Optional[int] = None
    detail: str = ""
    queries_issued: int = 0

    @property
    def resolved(self) -> bool:
        """True when BOTH a remote query URI and a pinned local node exist."""
        return (self.resolution_status == IdentityStatus.RESOLVED.value
                and self.local_index is not None
                and bool(self.remote_query_uri))

    @property
    def uris_differ(self) -> bool:
        """True when the remote and local spellings are not the same string.

        The case this whole module exists for, and the case in which Answer
        exclusion by raw string comparison silently fails.
        """
        return bool(self.remote_query_uri and self.local_kg_uri
                    and self.remote_query_uri != self.local_kg_uri)

    def as_record(self) -> dict:
        return {
            "identity_schema_version": IDENTITY_SCHEMA_VERSION,
            "original_uri": self.original_uri,
            "remote_query_uri": self.remote_query_uri,
            "local_kg_uri": self.local_kg_uri,
            "local_index": self.local_index,
            "local_lookup_form": self.local_lookup_form,
            "remote_redirect_used": self.remote_redirect_used,
            "remote_redirect_status": self.remote_redirect_status,
            "remote_redirect_chain": list(self.remote_redirect_chain),
            "local_resolution_method": self.local_resolution_method,
            "local_alias_candidates": list(self.local_alias_candidates),
            "resolution_status": self.resolution_status,
            "original_uri_has_current_categories":
                self.original_uri_has_current_categories,
            "original_uri_current_category_count":
                self.original_uri_current_category_count,
            "remote_query_uri_current_category_count":
                self.remote_query_uri_current_category_count,
            "remote_and_local_uris_differ": self.uris_differ,
            "queries_issued": self.queries_issued,
            "detail": self.detail,
            "note": (
                "original_uri is the immutable audit identity; remote_query_uri "
                "is the resource whose CURRENT dcterms:subject categories were "
                "queried; local_kg_uri is the node of the pinned March-2023 "
                "infobox dump used by every local graph, evidence and LRoleSim "
                "stage. The pinned dump is never edited, renamed or regenerated."
            ),
        }


# ---------------------------------------------------------------------------
# Query builders — pure, offline-testable, and refusing rather than escaping
# ---------------------------------------------------------------------------


def _values_block(uris: Sequence[str], *, what: str) -> str:
    if not uris:
        raise ValueError(f"at least one {what} is required")
    return " ".join(f"<{validate_iri(u, what=what)}>" for u in uris)


def build_category_presence_query(uris: Sequence[str]) -> str:
    """How many CURRENT ``dcterms:subject`` Category memberships each URI has.

    The question this answers is "is the supplied spelling still usable as the
    category-query subject?", so it counts memberships rather than listing them:
    a count is one small row per URI and is all the decision needs. A URI absent
    from the result has zero — but only when the query SUCCEEDED, which is why
    the source reports query failure separately and never as a count of zero.
    """
    values = _values_block(uris, what="identity subject URI")
    return f"""{QID_PREFIX} {QID_CATEGORY_PRESENCE}
{_PREFIXES}
SELECT ?e (COUNT(DISTINCT ?c) AS ?n) WHERE {{
  VALUES ?e {{ {values} }}
  ?e dcterms:subject ?c .
  FILTER(STRSTARTS(STR(?c), "{CATEGORY_PREFIX}"))
}} GROUP BY ?e ORDER BY STR(?e)
"""


def build_forward_redirect_query(uris: Sequence[str]) -> str:
    """``?source dbo:wikiPageRedirects ?target`` — the source is the stub.

    Identical in shape and direction to
    ``classes.sparql_client.build_redirect_batch_query``, which resolves member
    redirects. It is spelled again here rather than imported because this module
    asks the question about ANSWERS and needs its own ``#qid:`` marker, so a
    cache hit and a provenance row can say which stage issued the query.
    ``owl:sameAs`` is not used and must never be added.
    """
    values = _values_block(uris, what="redirect source URI")
    return f"""{QID_PREFIX} {QID_FORWARD_REDIRECT}
{_PREFIXES}
SELECT DISTINCT ?source ?target WHERE {{
  VALUES ?source {{ {values} }}
  ?source dbo:wikiPageRedirects ?target .
  FILTER(isIRI(?target))
}} ORDER BY STR(?source) STR(?target)
"""


def build_reverse_redirect_query(uris: Sequence[str]) -> str:
    """``?source dbo:wikiPageRedirects ?target`` with the TARGET bound.

    The direction that has no counterpart anywhere else in the repository, and
    the one the pinned-KG bridge actually needs: given the CURRENT canonical
    resource, which OTHER spellings redirect to it? One of those aliases may be
    the March-2023 name — ``dbr:Xun_Kuang`` for today's
    ``dbr:Xunzi_(philosopher)`` — and it is the only way to reach the pinned node
    without inventing a rename rule.

    ``FILTER(!STRSTARTS(...Category:))`` keeps category redirects out of a
    resource-identity answer; a category is never an Answer node.
    """
    values = _values_block(uris, what="redirect target URI")
    return f"""{QID_PREFIX} {QID_REVERSE_REDIRECT}
{_PREFIXES}
SELECT DISTINCT ?target ?source WHERE {{
  VALUES ?target {{ {values} }}
  ?source dbo:wikiPageRedirects ?target .
  FILTER(isIRI(?source))
  FILTER(STRSTARTS(STR(?source), "{RESOURCE_PREFIX}"))
  FILTER(!STRSTARTS(STR(?source), "{CATEGORY_PREFIX}"))
}} ORDER BY STR(?target) STR(?source)
"""


# ---------------------------------------------------------------------------
# The evidence source
# ---------------------------------------------------------------------------


class IdentityEvidenceSource(Protocol):
    """The three questions the identity bridge asks about the live endpoint.

    Every method returns ``(answers, unavailable)``. A URI that was queried
    successfully and simply has no answer is absent from BOTH — the third state a
    bare ``None`` would collapse, and the one that separates "DBpedia says this
    is not a redirect" from "we never found out".
    """

    def category_counts(self, uris: Sequence[str]
                        ) -> tuple[Mapping[str, int], frozenset[str]]:
        ...  # pragma: no cover - protocol

    def forward_targets(self, uris: Sequence[str]
                        ) -> tuple[Mapping[str, str], frozenset[str]]:
        ...  # pragma: no cover - protocol

    def reverse_sources(self, uris: Sequence[str]
                        ) -> tuple[Mapping[str, tuple[str, ...]], frozenset[str]]:
        ...  # pragma: no cover - protocol


@dataclass
class SparqlIdentitySource:
    """The live/cached implementation, over the frozen ``CachedPageFetcher``.

    Reuses the existing transport, retry policy, SQLite page cache and strict
    offline mode unchanged. Nothing about caching, retrying or failure
    classification is re-implemented: a cache miss in strict offline mode raises
    from the fetcher exactly as it does for a class-member page, and a failed
    page is recorded in the failures table and reported as UNAVAILABLE here —
    never as an empty answer.
    """

    fetcher: Any
    batch_size: int = 50
    query_count: int = 0
    failures: list = field(default_factory=list)

    def _run(self, query: str, kind: str, batch: Sequence[str]
             ) -> tuple[tuple[Mapping[str, Any], ...], bool]:
        from classes.sparql_client import PageRetrievalFailed

        self.query_count += 1
        try:
            page = self.fetcher.fetch(query, query_kind=kind, class_uri=None,
                                      page_index=0, cursor_after=None,
                                      page_size=None)
        except PageRetrievalFailed as exc:
            # The whole batch is UNAVAILABLE. Turning a transport failure into
            # "these URIs have no redirect / no categories" would manufacture a
            # negative fact about DBpedia out of a network problem.
            self.failures.append(exc.failure)
            return (), True
        return tuple(page.rows), False

    def _batches(self, uris: Sequence[str]) -> list[tuple[str, ...]]:
        ordered = tuple(sorted({strip_uri_brackets(u) for u in uris if u}))
        size = max(1, int(self.batch_size))
        return [ordered[i:i + size] for i in range(0, len(ordered), size)]

    def category_counts(self, uris: Sequence[str]
                        ) -> tuple[Mapping[str, int], frozenset[str]]:
        from classes.sparql_client import binding_value

        counts: dict[str, int] = {}
        unavailable: set[str] = set()
        for batch in self._batches(uris):
            rows, failed = self._run(build_category_presence_query(batch),
                                     QID_CATEGORY_PRESENCE, batch)
            if failed:
                unavailable.update(batch)
                continue
            for row in rows:
                subject = binding_value(row, "e")
                raw = binding_value(row, "n")
                if subject is None or raw is None:
                    continue
                try:
                    counts[strip_uri_brackets(subject)] = int(raw)
                except (TypeError, ValueError):
                    continue
        return counts, frozenset(unavailable)

    def forward_targets(self, uris: Sequence[str]
                        ) -> tuple[Mapping[str, str], frozenset[str]]:
        from classes.sparql_client import binding_value

        targets: dict[str, str] = {}
        unavailable: set[str] = set()
        for batch in self._batches(uris):
            rows, failed = self._run(build_forward_redirect_query(batch),
                                     QID_FORWARD_REDIRECT, batch)
            if failed:
                unavailable.update(batch)
                continue
            for row in rows:
                source = binding_value(row, "source")
                target = binding_value(row, "target")
                if not is_safe_iri(source) or target is None:
                    continue
                # First target in the query's deterministic ORDER BY wins, so a
                # source with several targets resolves the same way every run.
                targets.setdefault(strip_uri_brackets(source),
                                   strip_uri_brackets(target))
        return targets, frozenset(unavailable)

    def reverse_sources(self, uris: Sequence[str]
                        ) -> tuple[Mapping[str, tuple[str, ...]], frozenset[str]]:
        from classes.sparql_client import binding_value

        aliases: dict[str, list[str]] = {}
        unavailable: set[str] = set()
        for batch in self._batches(uris):
            rows, failed = self._run(build_reverse_redirect_query(batch),
                                     QID_REVERSE_REDIRECT, batch)
            if failed:
                unavailable.update(batch)
                continue
            for row in rows:
                target = binding_value(row, "target")
                source = binding_value(row, "source")
                if target is None or not is_safe_iri(source):
                    continue
                aliases.setdefault(strip_uri_brackets(target), []).append(
                    strip_uri_brackets(source))
        return ({k: tuple(sorted(set(v))) for k, v in aliases.items()},
                frozenset(unavailable))


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RemoteResolution:
    uri: str
    status: RemoteRedirectStatus
    chain: tuple[str, ...]
    followed: bool
    original_category_count: Optional[int]
    resolved_category_count: Optional[int]
    detail: str


def resolve_remote_query_uri(
    original_uri: str,
    source: IdentityEvidenceSource,
    *,
    max_hops: int = DEFAULT_MAX_IDENTITY_HOPS,
) -> _RemoteResolution:
    """Decide WHICH resource the current endpoint should be asked about.

    The rule, in order:

    1. If the supplied URI already has at least one CURRENT ``dcterms:subject``
       Category membership, it is kept. §5.1: a usable subject is not abandoned
       because some other, cosmetic field is missing — the categories are the
       thing the selector needs, and a redirect hop that changed nothing would
       only make the provenance harder to read.
    2. Otherwise ``dbo:wikiPageRedirects`` is followed, bounded and cycle-safe,
       to a terminal non-redirecting resource, and THAT resource's category
       count is measured too.
    3. If no chain exists, the original URI is kept and reported as
       NO_REDIRECT with a zero (or unknown) category count. That is a
       measurement about the endpoint, not an error: an Answer can legitimately
       have no categories today.

    A failed lookup at any point yields QUERY_FAILED and keeps the original URI,
    because a transport problem must never be recorded as "this entity has no
    categories" or as "this entity is not a redirect".
    """
    origin = strip_uri_brackets(original_uri)
    counts, unavailable = source.category_counts([origin])
    if origin in unavailable:
        return _RemoteResolution(
            uri=origin, status=RemoteRedirectStatus.QUERY_FAILED, chain=(),
            followed=False, original_category_count=None,
            resolved_category_count=None,
            detail=("the current-category probe for the supplied URI did not "
                    "complete; no redirect was attempted and nothing may be "
                    "concluded about this URI's categories"))
    original_count = int(counts.get(origin, 0))
    if original_count > 0:
        return _RemoteResolution(
            uri=origin, status=RemoteRedirectStatus.NO_REDIRECT, chain=(),
            followed=False, original_category_count=original_count,
            resolved_category_count=original_count,
            detail=(f"the supplied URI already has {original_count} current "
                    f"dcterms:subject categories, so no redirect was followed"))

    chain: list[str] = [origin]
    status = RemoteRedirectStatus.NO_REDIRECT
    budget = max(0, int(max_hops))
    for hop in range(budget):
        current = chain[-1]
        targets, failed = source.forward_targets([current])
        if current in failed:
            status = RemoteRedirectStatus.QUERY_FAILED
            break
        target = targets.get(current)
        if target is None:
            status = (RemoteRedirectStatus.FOLLOWED if len(chain) > 1
                      else RemoteRedirectStatus.NO_REDIRECT)
            break
        if not is_safe_iri(target):
            status = RemoteRedirectStatus.UNSAFE_TARGET
            break
        if target in chain:
            chain.append(target)
            status = RemoteRedirectStatus.CYCLE
            break
        chain.append(target)
        if hop == budget - 1:
            # OUR budget ended the walk, not the data.
            status = RemoteRedirectStatus.MAX_HOPS
    else:
        if budget == 0:
            status = RemoteRedirectStatus.MAX_HOPS

    # A chain is usable only when it terminated cleanly. A cycle, an unsafe
    # target or an exhausted budget leaves the ORIGINAL URI in place: guessing a
    # midpoint of a broken chain would query an entity nobody chose.
    usable = status in (RemoteRedirectStatus.FOLLOWED,
                        RemoteRedirectStatus.NO_REDIRECT)
    resolved = chain[-1] if (usable and len(chain) > 1) else origin
    resolved_count: Optional[int] = original_count
    if resolved != origin:
        counts2, unavailable2 = source.category_counts([resolved])
        resolved_count = (None if resolved in unavailable2
                          else int(counts2.get(resolved, 0)))
    detail = {
        RemoteRedirectStatus.NO_REDIRECT: (
            "the supplied URI is not a dbo:wikiPageRedirects source, so it is "
            "the current resource; it currently has no Category membership"),
        RemoteRedirectStatus.FOLLOWED: (
            "the supplied URI had no current Category membership and a "
            "dbo:wikiPageRedirects chain resolved it to the current resource"),
        RemoteRedirectStatus.QUERY_FAILED: (
            "a redirect lookup did not complete; the supplied URI is kept and "
            "no conclusion is drawn about a redirect"),
        RemoteRedirectStatus.CYCLE: (
            "the redirect chain revisits a URI it already contains; no target "
            "was chosen and the supplied URI is kept"),
        RemoteRedirectStatus.UNSAFE_TARGET: (
            "a redirect target could not be safely interpolated into a query, "
            "so the walk stopped and the supplied URI is kept"),
        RemoteRedirectStatus.MAX_HOPS: (
            f"the hop budget of {budget} ended the walk; whether a further hop "
            f"would reach a terminal resource is unknown"),
    }[status]
    return _RemoteResolution(
        uri=resolved, status=status, chain=tuple(chain[1:]),
        followed=resolved != origin, original_category_count=original_count,
        resolved_category_count=resolved_count, detail=detail)


def resolve_answer_identity(
    original_uri: str,
    *,
    local_lookup: Callable[[str], Any],
    source: Optional[IdentityEvidenceSource] = None,
    max_hops: int = DEFAULT_MAX_IDENTITY_HOPS,
) -> AnswerIdentity:
    """Produce the complete three-URI identity record for one Answer.

    ``local_lookup`` is ``classes.member_mapper.make_local_lookup(url_index)``:
    the same read-only spelling ladder every mapped candidate goes through, so
    the Answer node is found by exactly the rule its candidates are found by.

    ``source`` may be ``None``, which means "no endpoint evidence is available".
    The function then still resolves whatever the pinned dump alone can settle —
    step 1 below — and reports the rest as unresolved rather than failing. That
    is what lets an offline unit test and an offline replay exercise the same
    code path.

    LOCAL RESOLUTION ORDER (principled, not a lookup table):

    1. the ORIGINAL URI, if it is a node here. The researcher's own spelling wins
       when it works, and this costs no query at all.
    2. the REMOTE QUERY URI, if it is a node here.
    3. a REVERSE-REDIRECT ALIAS of the remote query URI that is a node here.
       Ambiguity is refused: if two aliases reach two DIFFERENT local nodes, the
       declared rule does not choose, and AMBIGUOUS_LOCAL_ALIAS is reported
       instead of a guess. Several aliases reaching the SAME node is not
       ambiguity — it is the same entity spelled several ways — and resolves
       normally, choosing the lexicographically smallest alias purely so the
       recorded URI is deterministic.
    """
    origin = strip_uri_brackets(original_uri)
    if not is_safe_iri(origin):
        return AnswerIdentity(
            original_uri=str(original_uri),
            resolution_status=IdentityStatus.INPUT_INVALID.value,
            local_resolution_method=LocalResolutionMethod.NOT_RESOLVED.value,
            detail="the supplied Answer URI is not a safe http(s) IRI")

    def finish(identity: AnswerIdentity) -> AnswerIdentity:
        return identity

    # --- the remote half ----------------------------------------------------
    if source is None:
        remote = _RemoteResolution(
            uri=origin, status=RemoteRedirectStatus.NO_REDIRECT, chain=(),
            followed=False, original_category_count=None,
            resolved_category_count=None,
            detail=("no endpoint evidence source was supplied, so the supplied "
                    "URI is used as the remote query URI unchanged"))
    else:
        remote = resolve_remote_query_uri(origin, source, max_hops=max_hops)

    queries = getattr(source, "query_count", 0) if source is not None else 0

    def record(local_uri: Optional[str], lookup: Optional[Any], method: str,
               status: IdentityStatus, aliases: Sequence[str] = (),
               extra: str = "") -> AnswerIdentity:
        return AnswerIdentity(
            original_uri=origin,
            remote_query_uri=remote.uri,
            local_kg_uri=local_uri,
            local_index=(None if lookup is None
                         else getattr(lookup, "local_index", None)),
            local_lookup_form=(None if lookup is None
                               else getattr(lookup, "lookup_form", None)),
            remote_redirect_used=remote.followed,
            remote_redirect_status=remote.status.value,
            remote_redirect_chain=remote.chain,
            local_resolution_method=method,
            local_alias_candidates=tuple(aliases),
            resolution_status=status.value,
            original_uri_has_current_categories=(
                None if remote.original_category_count is None
                else remote.original_category_count > 0),
            original_uri_current_category_count=remote.original_category_count,
            remote_query_uri_current_category_count=remote.resolved_category_count,
            detail=" | ".join(p for p in (remote.detail, extra) if p),
            queries_issued=(getattr(source, "query_count", 0)
                            if source is not None else 0),
        )

    # --- step 1: the original URI -------------------------------------------
    original_lookup = local_lookup(origin)
    if getattr(original_lookup, "found", False):
        return finish(record(
            origin, original_lookup, LocalResolutionMethod.ORIGINAL_URI.value,
            IdentityStatus.RESOLVED,
            extra="the supplied URI is itself a node of the pinned local KG"))

    # --- step 2: the remote query URI ---------------------------------------
    if remote.uri != origin:
        remote_lookup = local_lookup(remote.uri)
        if getattr(remote_lookup, "found", False):
            return finish(record(
                remote.uri, remote_lookup,
                LocalResolutionMethod.REMOTE_QUERY_URI.value,
                IdentityStatus.RESOLVED,
                extra=("the current canonical URI is a node of the pinned "
                       "local KG")))

    # --- step 3: reverse-redirect aliases of the remote query URI -----------
    if source is None:
        return finish(record(
            None, None, LocalResolutionMethod.NOT_RESOLVED.value,
            IdentityStatus.NO_LOCAL_IDENTITY,
            extra=("neither the supplied nor the remote URI is a node here and "
                   "no endpoint evidence source was supplied, so no alias could "
                   "be looked for")))

    alias_map, alias_unavailable = source.reverse_sources([remote.uri])
    if remote.uri in alias_unavailable:
        return finish(record(
            None, None, LocalResolutionMethod.NOT_RESOLVED.value,
            IdentityStatus.NO_LOCAL_IDENTITY,
            extra=("the reverse-redirect lookup did not complete, so whether a "
                   "pinned-KG alias exists is UNKNOWN; this is not evidence "
                   "that none exists")))

    aliases = tuple(alias_map.get(remote.uri, ()))
    hits: dict[int, list[tuple[str, Any]]] = {}
    for alias in aliases:
        lookup = local_lookup(alias)
        index = getattr(lookup, "local_index", None)
        if index is None:
            continue
        hits.setdefault(int(index), []).append((alias, lookup))

    if not hits:
        return finish(record(
            None, None, LocalResolutionMethod.NOT_RESOLVED.value,
            IdentityStatus.NO_LOCAL_IDENTITY, aliases=aliases,
            extra=(f"{len(aliases)} DBpedia alias(es) redirect to the remote "
                   f"query URI and none of them is a node of the pinned local "
                   f"KG; an absence from one dump, not a claim of "
                   f"non-existence")))
    if len(hits) > 1:
        # Two aliases, two DIFFERENT nodes. The rule does not choose, because
        # choosing would silently pick one entity's neighbourhood to reason over.
        return finish(record(
            None, None, LocalResolutionMethod.AMBIGUOUS.value,
            IdentityStatus.AMBIGUOUS_LOCAL_ALIAS, aliases=aliases,
            extra=(f"{len(hits)} DISTINCT pinned-KG nodes are reachable through "
                   f"redirect aliases of the remote query URI "
                   f"(local indices {sorted(hits)}); the declared rule refuses "
                   f"to choose between them")))

    (index, matched), = hits.items()
    alias, lookup = sorted(matched, key=lambda pair: pair[0])[0]
    return finish(record(
        alias, lookup, LocalResolutionMethod.REVERSE_REDIRECT_ALIAS.value,
        IdentityStatus.RESOLVED, aliases=aliases,
        extra=(f"the pinned local KG holds this entity under the historical "
               f"spelling {alias}, reached from the current canonical URI "
               f"through dbo:wikiPageRedirects")))
