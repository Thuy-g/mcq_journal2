############################################################################
# src/selection/observed_facts.py
#
# Observed URI-valued one-hop facts from the pinned local KG, plus the corrected
# edge-set cache.
#
# WHAT THIS FIXES  (AUDIT_Journal2_v2_2026-07-26, items EX-4 and EX-12)
#
#   EX-4 — the cache-key defect.
#     The legacy cache in extract_221_and_select_distractors_ClaudeWeb_v2.py was
#
#         _edgeset_cache: dict[int, frozenset] = {}
#         if node_idx in _edgeset_cache: return _edgeset_cache[node_idx]
#
#     keyed by NODE INDEX ALONE. So the first call decided the answer for every
#     later call on that node: a result computed with use_in=False was returned
#     verbatim for use_in=True, silently halving the neighbourhood, and a second
#     KG loaded in the same process inherited the first KG's edges even though
#     read_ttl.py renumbers every node on each build. Audit test T2.1 confirmed
#     the use_in half of this on the real file. Both failures are silent — the
#     wrong answer is returned successfully.
#
#     The identity here is (kg_identity, node_index, use_in, fact_schema_version):
#       kg_identity          the pinned KG's SHA-256 when the object carries one,
#                            so two builds can never share an entry;
#       node_index           as before;
#       use_in               so the IN/OUT ablation cannot cross-contaminate;
#       fact_schema_version  so a future change to what a fact IS invalidates
#                            entries instead of reinterpreting them.
#
#   EX-12 — direction-dependent naming.
#     The legacy build_choices() emitted {"predicate", "direction", "object"} for
#     BOTH directions. For an IN edge the third element is the SUBJECT, so the
#     record named its subject "object" and any downstream verbalization would
#     state the relation backwards. This module emits `counterpart_uri` and never
#     an unconditional `object` — see ObservedFact in contracts.py.
#
# OPEN-WORLD DISCIPLINE
#   Everything here is OBSERVED. There is no function that emits a negative fact,
#   and absence of a triple is never recorded, returned or implied to be false.
#   DBpedia is open-world (CLAUDE.md item 7): a missing triple is missing, not
#   false. Prompt 8E may compute an `observed_contrast` between two owners' fact
#   sets; that is a statement about the pinned KG, not about the world.
#
# SCOPE
#   Reads an already-loaded KG object. Does not load, build, cache to disk, rank,
#   select distractors or touch the network.
############################################################################

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

from selection.contracts import (
    DIRECTION_IN,
    DIRECTION_OUT,
    ObservedFact,
    SCOPE_DIAGNOSTIC,
    SCOPE_PRIMARY,
    sort_observed_facts,
)

# --- Fact schema version ---------------------------------------------------
# Part of the cache identity. Bump this whenever "what counts as one fact"
# changes, so no entry computed under the old meaning is ever reused.
FACT_SCHEMA_VERSION = "journal2-prompt8d-observed-fact-v1"

# --- Direction codes -------------------------------------------------------
# Declared IN first, matching src/MCQ_lrolesim_ClaudeWeb_v2.py's `IN, OUT = 0, 1`.
# The legacy extractor declared the same VALUES in the opposite order
# (`OUT, IN = 1, 0`), which AUDIT item API-1 flagged as an easy mis-edit. The
# values are asserted below rather than merely commented.
DIRECTION_CODE_IN = 0
DIRECTION_CODE_OUT = 1

DIRECTION_LABEL = {
    DIRECTION_CODE_OUT: DIRECTION_OUT,
    DIRECTION_CODE_IN: DIRECTION_IN,
}
assert DIRECTION_CODE_IN == 0 and DIRECTION_CODE_OUT == 1, (
    "direction codes must stay (IN, OUT) == (0, 1) to match the LRoleSim kernel"
)


class ObservedFactError(Exception):
    """A fact could not be serialized from the pinned local KG."""


# ==========================================================================
# 1) KG ACCESS  (works for both kg.loader.LocalKG and the legacy KG dataclass)
# ==========================================================================

def bare_uri(uri: str) -> str:
    """Strip the pinned pickle's `<...>` key spelling to get the plain URI."""
    if uri.startswith("<") and uri.endswith(">"):
        return uri[1:-1]
    return uri


def _uri_for_index(kg: object, index: int) -> str:
    """Resolve a node or predicate index to its unbracketed URI.

    Accepts either src/kg/loader.LocalKG (`uri_for_index`) or the legacy KG
    dataclass (`uri`), so the corrected cache can serve the legacy entrypoint
    without the legacy entrypoint importing the new loader.
    """
    getter = getattr(kg, "uri_for_index", None)
    if getter is None:
        getter = getattr(kg, "uri", None)
    if getter is None:
        raise ObservedFactError(
            f"KG object {type(kg).__name__} exposes neither uri_for_index() nor "
            f"uri(); cannot resolve index {index}")
    try:
        raw = getter(index)
    except KeyError as exc:
        raise ObservedFactError(
            f"index {index} is not present in the pinned local KG") from exc
    if raw is None:
        raise ObservedFactError(
            f"index {index} is not present in the pinned local KG")
    return bare_uri(raw)


def _neighbor_map(kg: object, attribute: str) -> Mapping[int, Sequence[tuple[int, int]]]:
    neighbor = getattr(kg, attribute, None)
    if neighbor is None:
        raise ObservedFactError(
            f"KG object {type(kg).__name__} has no {attribute} mapping")
    return neighbor


# ==========================================================================
# 2) THE CORRECTED EDGE-SET CACHE
# ==========================================================================

@dataclass(frozen=True)
class EdgeSetCacheKey:
    """The full identity of one cached edge set.

    Every component is load-bearing; dropping any one of them reproduces a real
    defect. See the EX-4 note at the top of this module.
    """

    kg_identity: str
    node_index: int
    use_in: bool
    fact_schema_version: str = FACT_SCHEMA_VERSION


class EdgeSetCache:
    """Memoises complete one-hop edge sets under the full identity above.

    A CACHE, not a store: it is process-local, it is never written to disk, and it
    holds only what can be recomputed from the pinned KG.

    On kg_identity for an object with no SHA-256: the registry below keeps a
    STRONG reference to that KG object alongside its token. That is deliberate.
    `id()` is only unique among LIVE objects, so a weak reference would let a
    collected KG's address be reused by a different KG and silently revive its
    entries — precisely the class of bug this cache exists to remove. The cost is
    that a KG registered here stays alive until `clear()`.
    """

    def __init__(self) -> None:
        self._entries: dict[EdgeSetCacheKey, frozenset[tuple[int, int, int]]] = {}
        self._registry: dict[int, tuple[object, str]] = {}
        self._token_counter = 0
        self.hits = 0
        self.misses = 0

    # --- identity ---------------------------------------------------------
    def identity_for(self, kg: object) -> str:
        """A stable identity token for one loaded KG."""
        sha = getattr(kg, "source_sha256", None)
        if isinstance(sha, str) and sha:
            return f"sha256:{sha}"
        key = id(kg)
        registered = self._registry.get(key)
        if registered is not None and registered[0] is kg:
            return registered[1]
        self._token_counter += 1
        token = f"object:{self._token_counter}:{type(kg).__name__}"
        self._registry[key] = (kg, token)
        return token

    # --- lookup -----------------------------------------------------------
    def get_or_compute(self, kg: object, node_index: int,
                       use_in: bool = True) -> frozenset[tuple[int, int, int]]:
        key = EdgeSetCacheKey(
            kg_identity=self.identity_for(kg),
            node_index=node_index,
            use_in=bool(use_in),
        )
        cached = self._entries.get(key)
        if cached is not None:
            self.hits += 1
            return cached
        self.misses += 1
        computed = _compute_edge_set(kg, node_index, use_in=use_in)
        self._entries[key] = computed
        return computed

    def clear(self) -> None:
        self._entries.clear()
        self._registry.clear()
        self.hits = 0
        self.misses = 0

    def as_record(self) -> dict:
        return {
            "fact_schema_version": FACT_SCHEMA_VERSION,
            "entry_count": len(self._entries),
            "hits": self.hits,
            "misses": self.misses,
            "distinct_kg_identities": len({k.kg_identity for k in self._entries}),
        }


def _compute_edge_set(kg: object, node_index: int,
                      use_in: bool = True) -> frozenset[tuple[int, int, int]]:
    """{(predicate_index, direction_code, counterpart_index)} for one node.

    Both directions are collected when `use_in` is true, matching LRoleSim's
    N'(v) = I'(v) union O'(v). Self-loops are kept: they are observed edges, and
    dropping them here would make this set disagree with the degrees the graph
    layer records.
    """
    out_neighbor = _neighbor_map(kg, "out_neighbor")
    edges = {(p, DIRECTION_CODE_OUT, o) for p, o in out_neighbor.get(node_index, ())}
    if use_in:
        in_neighbor = _neighbor_map(kg, "in_neighbor")
        edges |= {(p, DIRECTION_CODE_IN, s) for p, s in in_neighbor.get(node_index, ())}
    return frozenset(edges)


#: The process-wide cache used by the legacy entrypoint's extended_edgeset().
DEFAULT_EDGESET_CACHE = EdgeSetCache()


def observed_edge_set(node_index: int, kg: object, use_in: bool = True,
                      cache: Optional[EdgeSetCache] = None
                      ) -> frozenset[tuple[int, int, int]]:
    """Cached complete one-hop edge set of `node_index` in `kg`."""
    cache = DEFAULT_EDGESET_CACHE if cache is None else cache
    return cache.get_or_compute(kg, node_index, use_in=use_in)


def group_by_predicate_direction(
    edge_set: Iterable[tuple[int, int, int]]
) -> dict[tuple[int, int], tuple[int, ...]]:
    """{(predicate, direction): sorted counterpart indices}.

    Counterparts are returned SORTED rather than as a set, so any consumer that
    iterates them is deterministic. The legacy group_by_key() returned raw sets,
    which made downstream matching order depend on set iteration.
    """
    grouped: dict[tuple[int, int], set[int]] = {}
    for predicate, direction, counterpart in edge_set:
        grouped.setdefault((predicate, direction), set()).add(counterpart)
    return {key: tuple(sorted(value)) for key, value in sorted(grouped.items())}


# ==========================================================================
# 3) SERIALIZING OBSERVED FACTS
# ==========================================================================

@dataclass(frozen=True)
class OwnerFactSet:
    """Every observed one-hop fact of one owner node, with its provenance."""

    owner_uri: str
    owner_local_index: int
    graph_fingerprint: str
    primary_or_diagnostic: str
    facts: tuple[ObservedFact, ...]
    owner_role: str = "candidate"
    answer_uri: Optional[str] = None
    unresolved_counterpart_count: int = 0

    @property
    def fact_count(self) -> int:
        return len(self.facts)

    @property
    def out_fact_count(self) -> int:
        return sum(1 for f in self.facts if f.direction == DIRECTION_OUT)

    @property
    def in_fact_count(self) -> int:
        return sum(1 for f in self.facts if f.direction == DIRECTION_IN)

    def as_records(self) -> list[dict]:
        records = []
        for fact in self.facts:
            record = fact.as_record()
            record["owner_role"] = self.owner_role
            record["answer_uri"] = self.answer_uri
            records.append(record)
        return records


def observed_facts_for_node(
    node_index: int,
    kg: object,
    *,
    graph_fingerprint: str,
    primary_or_diagnostic: str = SCOPE_PRIMARY,
    owner_role: str = "candidate",
    answer_uri: Optional[str] = None,
    use_in: bool = True,
    cache: Optional[EdgeSetCache] = None,
) -> OwnerFactSet:
    """Serialize the observed URI-valued one-hop facts of one node.

    A counterpart or predicate whose index does not resolve to a URI in the pinned
    KG is NOT URI-valued as far as this run can tell, so it is counted and skipped
    rather than emitted with a fabricated URI. The count is reported so a silent
    drop is impossible.
    """
    if primary_or_diagnostic not in (SCOPE_PRIMARY, SCOPE_DIAGNOSTIC):
        raise ObservedFactError(
            f"primary_or_diagnostic must be {SCOPE_PRIMARY!r} or "
            f"{SCOPE_DIAGNOSTIC!r}, got {primary_or_diagnostic!r}")

    owner_uri = _uri_for_index(kg, node_index)
    edge_set = observed_edge_set(node_index, kg, use_in=use_in, cache=cache)

    facts: list[ObservedFact] = []
    unresolved = 0
    # Sorted so construction order is deterministic even before sort_observed_facts.
    for predicate_index, direction_code, counterpart_index in sorted(edge_set):
        try:
            predicate_uri = _uri_for_index(kg, predicate_index)
            counterpart_uri = _uri_for_index(kg, counterpart_index)
        except ObservedFactError:
            unresolved += 1
            continue
        facts.append(ObservedFact(
            owner_uri=owner_uri,
            owner_local_index=node_index,
            predicate_uri=predicate_uri,
            direction=DIRECTION_LABEL[direction_code],
            counterpart_uri=counterpart_uri,
            counterpart_local_index=counterpart_index,
            graph_fingerprint=graph_fingerprint,
            primary_or_diagnostic=primary_or_diagnostic,
        ))

    return OwnerFactSet(
        owner_uri=owner_uri,
        owner_local_index=node_index,
        graph_fingerprint=graph_fingerprint,
        primary_or_diagnostic=primary_or_diagnostic,
        facts=sort_observed_facts(facts),
        owner_role=owner_role,
        answer_uri=answer_uri,
        unresolved_counterpart_count=unresolved,
    )


def serialize_owner_fact_sets(owner_sets: Sequence[OwnerFactSet]) -> list[dict]:
    """Flatten owner fact sets into one deterministic record stream.

    ORDER
      (owner_uri, direction, predicate_uri, counterpart_uri) across the WHOLE
      stream, not merely within each owner, so the serialized bytes do not depend
      on the order owners were processed in. `graph_fingerprint` is appended as a
      final tiebreak to keep the order total — see below for why one owner can
      legitimately appear under two fingerprints.

    DEDUPLICATION IS PER GRAPH, NOT GLOBAL
      One node is often a ranked candidate for SEVERAL Answers: the pilot's
      Aristotle and Plato share Category:Ancient_Greek_ethicists, and the three
      Japanese laureates share Category:Japanese_Nobel_laureates, so the 204
      (Answer, candidate) pairs cover only 131 distinct candidate nodes.

      Collapsing those to one row per node would force each row to carry ONE
      graph_fingerprint chosen from several, silently dropping the link to every
      other Answer the facts also serve. Since the schema binds each row to a
      single fingerprint, the deduplication key includes it: a repeated triple in
      the source dump is still emitted once per graph, and every row remains
      provenance-linked to exactly one graph it is actually valid for.
    """
    seen: set[tuple[str, str, str, str, str]] = set()
    rows: list[tuple[tuple[str, str, str, str, str], dict]] = []
    for owner_set in owner_sets:
        for fact in owner_set.facts:
            key = (*fact.sort_key, fact.graph_fingerprint)
            if key in seen:
                continue
            seen.add(key)
            record = fact.as_record()
            record["owner_role"] = owner_set.owner_role
            record["answer_uri"] = owner_set.answer_uri
            rows.append((key, record))
    rows.sort(key=lambda item: item[0])
    return [record for _key, record in rows]
