############################################################################
# src/pipeline/candidate_order.py
#
# The deterministic seeded graph-admission order.
#
# WHAT PROBLEM THIS SOLVES
#   src/kg/graph_view.py consumes an ALREADY ORDERED candidate list and admits
#   candidates all-or-nothing until the node budget or the candidate cap is hit.
#   So the order decides which complete neighbourhoods get considered first. A
#   finite budget therefore forces a choice, and the choice must be recorded.
#
# WHAT THIS ORDER IS NOT
#   It is NOT a ranking. No OverlapScore, no LRoleSim score, no degree, no
#   centrality and no human judgement enters it — by construction it CANNOT,
#   because it is computed before any graph exists. Calling it a ranking would
#   claim a scientific ordering this project has not established at this stage.
#
#   It is also NOT random. "Random" would mean unreproducible, and would make the
#   pilot's graphs unverifiable. It is a fixed keyed hash: the same inputs always
#   give the same order, in any process, on any machine.
#
#   The honest name, used throughout the outputs, is
#       deterministic seeded graph-admission order.
#
# WHY NOT SIMPLY URI ORDER OR LOCAL-INDEX ORDER
#   * Local-index order is an artefact of pickle construction: src/read_ttl.py
#     assigns indices while iterating a Python set, so index order encodes the
#     source TTL's layout and nothing about the entity. Preferring low indices
#     would silently prefer whatever appeared early in the dump.
#   * Plain URI order is an artefact of spelling. Under a 50-candidate cap on a
#     125-member class it would systematically admit "A..." and systematically
#     drop "W...", which is a bias correlated with alphabet and language.
#   A per-(Answer, class) keyed digest has neither property: it is stable, it is
#   uncorrelated with spelling and with dump layout, and it differs per Answer, so
#   no single candidate is globally advantaged across the pilot.
#
# THE KEY (frozen; changing it changes every graph, so it is versioned)
#   SHA256( DOMAIN + NUL + answer_uri + NUL + class_uri + NUL + candidate_uri )
#   sorted ascending by (hash_digest, canonical_candidate_uri).
#
#   The digest is the primary key; the URI is a total-order tiebreak so that two
#   candidates colliding on a digest still get one fixed order rather than an
#   order that depends on input sequence. A full SHA-256 collision here is not
#   expected to occur — the tiebreak exists to make the ordering provably total,
#   not because a collision is anticipated.
#
# CANONICAL CANDIDATE URI
#   The canonical URI of a candidate is the URI of the node ACTUALLY PRESENT in
#   the pinned local KG: the redirect target when the retrieved member redirected,
#   and the retrieved member URI otherwise. It is unbracketed. Using the retrieved
#   URI instead would give two different orders for the same graph node depending
#   on which alias was retrieved.
#
# Offline and pure: hashing and sorting only. No I/O, no network, no KG access.
############################################################################

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

# --- Frozen ordering key ---------------------------------------------------
# Versioned in the domain string itself: a future ordering policy must take a new
# domain, so an artefact's order can never be silently reinterpreted.
GRAPH_ADMISSION_ORDER_DOMAIN = "journal2-m1-graph-order-v1"
_NUL = "\x00"

# The public name for this ordering in every report and output column.
GRAPH_ADMISSION_ORDER_NAME = "deterministic seeded graph-admission order"

# Mapping origins the Week-1 mapper may attach to an accepted candidate.
ORIGIN_EXACT = "EXACT"
ORIGIN_REDIRECT = "REDIRECT"

# --- Duplicate dispositions ------------------------------------------------
DUPLICATE_CANONICAL_URI = "DUPLICATE_CANONICAL_URI"
DUPLICATE_LOCAL_INDEX = "DUPLICATE_LOCAL_INDEX"


class CandidateOrderError(Exception):
    """Base class for graph-admission-order failures."""


class CandidateOrderInputError(CandidateOrderError):
    """A candidate offered for ordering is not usable as a graph candidate."""


@dataclass(frozen=True)
class MappedCandidate:
    """One accepted Week-1 mapping, as offered to the ordering.

    `canonical_uri` is the local KG node's own URI (see the module docstring), and
    `local_index` is that node's index in the pinned pickle. `retrieved_uri` is
    kept only as provenance — it never enters the ordering key.
    """

    canonical_uri: str
    local_index: int
    mapping_origin: str
    retrieved_uri: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_uri, str) or not self.canonical_uri.strip():
            raise CandidateOrderInputError(
                f"canonical_uri must be a non-blank string, got "
                f"{self.canonical_uri!r}")
        if self.canonical_uri.startswith("<") or self.canonical_uri.endswith(">"):
            # A bracketed form is the local pickle's KEY spelling, not the URI.
            # Allowing both spellings would produce two different digests for one
            # node, so the bracketed form is refused rather than normalised.
            raise CandidateOrderInputError(
                f"canonical_uri must be unbracketed, got {self.canonical_uri!r}")
        if isinstance(self.local_index, bool) or not isinstance(self.local_index, int):
            raise CandidateOrderInputError(
                f"local_index must be an int, got {self.local_index!r}")
        if self.mapping_origin not in (ORIGIN_EXACT, ORIGIN_REDIRECT):
            raise CandidateOrderInputError(
                f"mapping_origin must be one of "
                f"{(ORIGIN_EXACT, ORIGIN_REDIRECT)}, got {self.mapping_origin!r}")


@dataclass(frozen=True)
class OrderedCandidate:
    """One candidate with its admission position and the digest that produced it."""

    admission_position: int
    canonical_uri: str
    local_index: int
    mapping_origin: str
    order_digest: str
    retrieved_uri: Optional[str] = None

    def as_record(self) -> dict:
        return {
            "admission_position": self.admission_position,
            "canonical_candidate_uri": self.canonical_uri,
            "candidate_local_index": self.local_index,
            "mapping_origin": self.mapping_origin,
            "graph_admission_order_digest": self.order_digest,
            "retrieved_member_uri": self.retrieved_uri,
        }


@dataclass(frozen=True)
class DroppedCandidate:
    """A candidate removed before ordering, with the reason it was removed."""

    canonical_uri: str
    local_index: int
    reason: str

    def as_record(self) -> dict:
        return {
            "canonical_candidate_uri": self.canonical_uri,
            "candidate_local_index": self.local_index,
            "dropped_reason": self.reason,
        }


@dataclass(frozen=True)
class GraphAdmissionOrder:
    """The complete ordered sequence for one (Answer, class) pair."""

    answer_uri: str
    class_uri: str
    domain: str
    ordered: tuple[OrderedCandidate, ...]
    dropped: tuple[DroppedCandidate, ...]

    def __len__(self) -> int:
        return len(self.ordered)

    @property
    def ordered_local_indices(self) -> tuple[int, ...]:
        """The sequence handed to the M1 graph builder, in admission order."""
        return tuple(c.local_index for c in self.ordered)

    @property
    def ordered_canonical_uris(self) -> tuple[str, ...]:
        return tuple(c.canonical_uri for c in self.ordered)

    def index_to_uri(self) -> dict[int, str]:
        return {c.local_index: c.canonical_uri for c in self.ordered}

    def position_of_index(self, local_index: int) -> int:
        for candidate in self.ordered:
            if candidate.local_index == local_index:
                return candidate.admission_position
        raise KeyError(f"local index {local_index} is not in this admission order")

    def as_record(self) -> dict:
        return {
            "answer_uri": self.answer_uri,
            "class_uri": self.class_uri,
            "graph_admission_order_domain": self.domain,
            "graph_admission_order_name": GRAPH_ADMISSION_ORDER_NAME,
            "ordered_candidate_count": len(self.ordered),
            "dropped_candidate_count": len(self.dropped),
            "ordered_candidates": [c.as_record() for c in self.ordered],
            "dropped_candidates": [d.as_record() for d in self.dropped],
        }


def graph_admission_digest(answer_uri: str, class_uri: str,
                           canonical_candidate_uri: str,
                           domain: str = GRAPH_ADMISSION_ORDER_DOMAIN) -> str:
    """The frozen ordering key, as a lowercase hex SHA-256 digest.

    NUL is the field separator because it cannot occur inside an IRI, so no two
    distinct field triples can produce the same byte string — the digest is
    unambiguous rather than merely unlikely to clash.
    """
    for name, value in (("answer_uri", answer_uri), ("class_uri", class_uri),
                        ("canonical_candidate_uri", canonical_candidate_uri),
                        ("domain", domain)):
        if not isinstance(value, str) or not value:
            raise CandidateOrderInputError(
                f"{name} must be a non-empty string, got {value!r}")
        if _NUL in value:
            raise CandidateOrderInputError(
                f"{name} must not contain a NUL byte: {value!r}")
    payload = _NUL.join((domain, answer_uri, class_uri, canonical_candidate_uri))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def order_candidates_for_graph_admission(
    answer_uri: str,
    class_uri: str,
    candidates: Iterable[MappedCandidate],
    domain: str = GRAPH_ADMISSION_ORDER_DOMAIN,
) -> GraphAdmissionOrder:
    """Order the accepted candidates of one (Answer, class) pair.

    The result depends only on the three URIs per candidate — never on the input
    sequence, never on a set or dict iteration order, and never on a local node
    index. Duplicates are dropped explicitly and reported rather than silently
    collapsed, because a duplicate would otherwise inflate the candidate count the
    graph gate is compared against.
    """
    if not isinstance(answer_uri, str) or not answer_uri:
        raise CandidateOrderInputError(f"answer_uri must be non-empty, got {answer_uri!r}")
    if not isinstance(class_uri, str) or not class_uri:
        raise CandidateOrderInputError(f"class_uri must be non-empty, got {class_uri!r}")

    seen_uris: set[str] = set()
    seen_indices: dict[int, str] = {}
    dropped: list[DroppedCandidate] = []
    keyed: list[tuple[str, str, MappedCandidate]] = []

    for candidate in candidates:
        if not isinstance(candidate, MappedCandidate):
            raise CandidateOrderInputError(
                f"expected MappedCandidate, got {type(candidate).__name__}")
        if candidate.canonical_uri == answer_uri:
            # The Answer is the pinned centre of the graph, never its own
            # distractor candidate. graph_view rejects it as well; refusing it
            # here keeps the ordered count equal to the real candidate count.
            raise CandidateOrderInputError(
                f"the Answer {answer_uri!r} must not be offered as its own "
                f"candidate")
        if candidate.canonical_uri in seen_uris:
            dropped.append(DroppedCandidate(
                canonical_uri=candidate.canonical_uri,
                local_index=candidate.local_index,
                reason=DUPLICATE_CANONICAL_URI))
            continue
        if candidate.local_index in seen_indices:
            # Two distinct canonical URIs resolving to one local node would be one
            # graph node offered twice. The second is dropped, and the collision is
            # reported so it cannot be mistaken for two independent candidates.
            dropped.append(DroppedCandidate(
                canonical_uri=candidate.canonical_uri,
                local_index=candidate.local_index,
                reason=DUPLICATE_LOCAL_INDEX))
            continue
        seen_uris.add(candidate.canonical_uri)
        seen_indices[candidate.local_index] = candidate.canonical_uri
        digest = graph_admission_digest(
            answer_uri, class_uri, candidate.canonical_uri, domain=domain)
        keyed.append((digest, candidate.canonical_uri, candidate))

    # (digest, canonical_uri) is a total order over distinct URIs, so the sort is
    # stable regardless of how `candidates` was iterated.
    keyed.sort(key=lambda t: (t[0], t[1]))

    ordered = tuple(
        OrderedCandidate(
            admission_position=position,
            canonical_uri=candidate.canonical_uri,
            local_index=candidate.local_index,
            mapping_origin=candidate.mapping_origin,
            order_digest=digest,
            retrieved_uri=candidate.retrieved_uri,
        )
        for position, (digest, _uri, candidate) in enumerate(keyed, start=1)
    )
    # Sorting by canonical URI keeps the dropped list deterministic too.
    dropped.sort(key=lambda d: (d.reason, d.canonical_uri))

    return GraphAdmissionOrder(
        answer_uri=answer_uri,
        class_uri=class_uri,
        domain=domain,
        ordered=ordered,
        dropped=tuple(dropped),
    )


def ordered_candidate_uri_sequence(order: GraphAdmissionOrder) -> Sequence[str]:
    """The ordered canonical URIs — the sequence recorded in a run fingerprint."""
    return order.ordered_canonical_uris
