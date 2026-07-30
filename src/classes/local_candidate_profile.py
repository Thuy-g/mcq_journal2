############################################################################
# src/classes/local_candidate_profile.py
#
# DESCRIPTIVE profiling of locally mapped candidates. Nothing is decided here.
#
# WHAT THIS MODULE DOES
#   For each mapped local candidate, read the pinned pickle and report its degree
#   and the size of its complete one-hop footprint, plus whether that footprint
#   ALONE could theoretically fit under DEFAULT_MAX_NODES = 1200 once the Answer
#   and the Answer's complete one-hop neighbourhood are reserved.
#
# WHAT THIS MODULE MUST NOT DO (§4)
#   * choose the final candidate ordering;
#   * call build_m1_graph() or fit_ordered_candidates_to_graph_budget();
#   * truncate any neighbourhood;
#   * compute OverlapScore;
#   * run LRoleSim, select distractors, do rationale set cover, or verbalize.
#
# ORDERING IS SERIALISATION, NOT SCIENCE
#   Candidates are emitted in ascending local-index order (and their URIs in
#   sorted URI order) purely so two runs produce byte-identical files. URI order
#   and index order are ARTEFACTS OF SPELLING AND OF PICKLE CONSTRUCTION — the
#   pickle's indices were assigned by iterating a Python set. Neither is the
#   pilot's candidate-prioritization policy, which belongs to the selection layer
#   and does not exist yet.
#
# "FITS ALONE" IS PER-CANDIDATE AND INDEPENDENT
#   fits_under_default_max_nodes_alone answers: "if this were the FIRST candidate
#   offered to the budget, would it be admitted?" It is NOT joint feasibility. Two
#   candidates that each fit alone need not both fit, because their footprints can
#   overlap or can jointly overrun the budget. The graph-budget outcome is decided
#   only by src/kg/graph_view.py, on an ordered list this module does not produce.
#
# Offline and pure: reads the already-loaded adjacency mappings, no network.
############################################################################

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

from kg.graph_view import DEFAULT_MAX_NODES, collect_complete_one_hop

# Computing the INDUCED edge count over a closed one-hop neighbourhood costs one
# adjacency scan per neighbour. That is trivial for an ordinary DBpedia entity and
# ruinous for a hub with a six-figure degree, so §4's "when inexpensive" is made a
# concrete, recorded threshold rather than a judgement call.
DEFAULT_ONE_HOP_EDGE_BUDGET_NODES = 5000

ONE_HOP_EDGES_COMPUTED = "COMPUTED"
ONE_HOP_EDGES_SKIPPED_TOO_LARGE = "SKIPPED_FOOTPRINT_EXCEEDS_EDGE_BUDGET"


@dataclass(frozen=True)
class AnswerFootprint:
    """The Answer's pinned base: itself plus its complete one-hop neighbourhood.

    Mirrors src/kg/graph_view.py's contract item 2 — the Answer and its complete
    neighbourhood are charged to the node budget before any candidate — so the
    remaining budget reported here is the same quantity the graph layer will use.
    """

    answer_uri: str
    local_index: int
    full_out_degree: int
    full_in_degree: int
    unique_out_neighbors: int
    unique_in_neighbors: int
    distinct_neighbor_count: int
    base_node_count: int
    max_nodes: int
    base_nodes: frozenset[int]

    @property
    def remaining_node_budget(self) -> int:
        """Nodes left for candidates. Clamped at 0, never negative."""
        return max(0, self.max_nodes - self.base_node_count)

    @property
    def base_exceeds_budget(self) -> bool:
        return self.base_node_count > self.max_nodes

    def as_record(self) -> dict:
        return {
            "answer_uri": self.answer_uri,
            "answer_local_index": self.local_index,
            "answer_full_out_degree": self.full_out_degree,
            "answer_full_in_degree": self.full_in_degree,
            "answer_unique_out_neighbors": self.unique_out_neighbors,
            "answer_unique_in_neighbors": self.unique_in_neighbors,
            "answer_distinct_neighbor_count": self.distinct_neighbor_count,
            "answer_base_node_count": self.base_node_count,
            "max_nodes": self.max_nodes,
            "remaining_node_budget": self.remaining_node_budget,
            "answer_base_exceeds_budget": self.base_exceeds_budget,
        }


@dataclass(frozen=True)
class CandidateLocalProfile:
    """Descriptive local profile of ONE mapped candidate. No decision implied."""

    local_index: int
    local_uri: Optional[str]
    full_out_degree: int
    full_in_degree: int
    unique_out_neighbors: int
    unique_in_neighbors: int
    distinct_neighbor_count: int
    complete_one_hop_node_count: int
    complete_one_hop_edge_count: Optional[int]
    one_hop_edge_count_state: str
    incident_edge_count: int
    has_self_loop: bool
    new_nodes_beyond_answer_base: int
    fits_under_default_max_nodes_alone: bool
    max_nodes: int
    remaining_node_budget: int

    @property
    def full_degree(self) -> int:
        return self.full_out_degree + self.full_in_degree

    def as_record(self) -> dict:
        return {
            "local_index": self.local_index,
            "local_uri": self.local_uri,
            "full_out_degree": self.full_out_degree,
            "full_in_degree": self.full_in_degree,
            "full_degree": self.full_degree,
            "unique_out_neighbors": self.unique_out_neighbors,
            "unique_in_neighbors": self.unique_in_neighbors,
            "distinct_neighbor_count": self.distinct_neighbor_count,
            "complete_one_hop_node_count": self.complete_one_hop_node_count,
            "complete_one_hop_edge_count": self.complete_one_hop_edge_count,
            "one_hop_edge_count_state": self.one_hop_edge_count_state,
            "incident_edge_count": self.incident_edge_count,
            "has_self_loop": self.has_self_loop,
            "new_nodes_beyond_answer_base": self.new_nodes_beyond_answer_base,
            "fits_under_default_max_nodes_alone":
                self.fits_under_default_max_nodes_alone,
            "max_nodes": self.max_nodes,
            "remaining_node_budget": self.remaining_node_budget,
        }


def _unique_endpoints(edges: Sequence[tuple[int, int]], node: int) -> tuple[int, bool]:
    """(distinct neighbour count excluding `node`, whether a self-loop exists).

    Self is excluded to match src/kg/graph_view.py's collect_complete_one_hop: a
    self-loop adds an EDGE but no new NODE, so it must not inflate a node-budget
    figure. Because the exclusion is invisible in the count alone, the self-loop is
    reported separately instead of being silently dropped.
    """
    others: set[int] = set()
    self_loop = False
    for _predicate, other in edges:
        if other == node:
            self_loop = True
        else:
            others.add(other)
    return len(others), self_loop


def profile_answer_footprint(
    answer_uri: str,
    answer_index: int,
    in_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    out_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    *,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> AnswerFootprint:
    """Measure the Answer's reserved base under the node budget."""
    profile = collect_complete_one_hop(answer_index, in_neighbor, out_neighbor)
    out_unique, _ = _unique_endpoints(
        tuple(out_neighbor.get(answer_index, ())), answer_index)
    in_unique, _ = _unique_endpoints(
        tuple(in_neighbor.get(answer_index, ())), answer_index)
    base_nodes = frozenset({answer_index, *profile.neighbors})
    return AnswerFootprint(
        answer_uri=answer_uri,
        local_index=answer_index,
        full_out_degree=profile.full_out_degree,
        full_in_degree=profile.full_in_degree,
        unique_out_neighbors=out_unique,
        unique_in_neighbors=in_unique,
        distinct_neighbor_count=profile.distinct_neighbor_count,
        base_node_count=len(base_nodes),
        max_nodes=int(max_nodes),
        base_nodes=base_nodes,
    )


def profile_candidate(
    local_index: int,
    in_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    out_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    answer_footprint: AnswerFootprint,
    *,
    index_url: Optional[Mapping[int, str]] = None,
    one_hop_edge_budget_nodes: int = DEFAULT_ONE_HOP_EDGE_BUDGET_NODES,
) -> CandidateLocalProfile:
    """Profile one mapped candidate. Descriptive only; nothing is selected."""
    out_edges = tuple(out_neighbor.get(local_index, ()))
    in_edges = tuple(in_neighbor.get(local_index, ()))
    out_unique, out_self = _unique_endpoints(out_edges, local_index)
    in_unique, in_self = _unique_endpoints(in_edges, local_index)

    profile = collect_complete_one_hop(local_index, in_neighbor, out_neighbor)
    closed = frozenset({local_index, *profile.neighbors})
    one_hop_node_count = len(closed)

    if one_hop_node_count <= max(1, int(one_hop_edge_budget_nodes)):
        edge_count: Optional[int] = _induced_edge_count(closed, out_neighbor)
        edge_state = ONE_HOP_EDGES_COMPUTED
    else:
        # Reported as unknown rather than estimated. §4 asks for this count only
        # when it is inexpensive, and a fabricated number would be worse than a
        # null a reader can see.
        edge_count = None
        edge_state = ONE_HOP_EDGES_SKIPPED_TOO_LARGE

    # Net new nodes: what this candidate would actually charge to the budget if it
    # were offered FIRST, mirroring graph_view's `addition` computation. Nodes it
    # shares with the Answer's base are already paid for.
    new_nodes = len(closed - answer_footprint.base_nodes)
    fits_alone = (not answer_footprint.base_exceeds_budget
                  and new_nodes <= answer_footprint.remaining_node_budget)

    return CandidateLocalProfile(
        local_index=local_index,
        local_uri=None if index_url is None else index_url.get(local_index),
        full_out_degree=len(out_edges),
        full_in_degree=len(in_edges),
        unique_out_neighbors=out_unique,
        unique_in_neighbors=in_unique,
        distinct_neighbor_count=profile.distinct_neighbor_count,
        complete_one_hop_node_count=one_hop_node_count,
        complete_one_hop_edge_count=edge_count,
        one_hop_edge_count_state=edge_state,
        incident_edge_count=len(out_edges) + len(in_edges),
        has_self_loop=out_self or in_self,
        new_nodes_beyond_answer_base=new_nodes,
        fits_under_default_max_nodes_alone=fits_alone,
        max_nodes=answer_footprint.max_nodes,
        remaining_node_budget=answer_footprint.remaining_node_budget,
    )


def _induced_edge_count(
    nodes: frozenset[int],
    out_neighbor: Mapping[int, Sequence[tuple[int, int]]],
) -> int:
    """OUT edges with both endpoints inside `nodes`, counted WITH multiplicity.

    Multiplicity is kept because two nodes joined by two different predicates are
    two edges in the multiset LRoleSim consumes. Only OUT adjacency is scanned:
    every edge appears exactly once there, so scanning IN as well would
    double-count.
    """
    total = 0
    for node in nodes:
        for _predicate, other in out_neighbor.get(node, ()):
            if other in nodes:
                total += 1
    return total


def profile_candidates(
    local_indices: Iterable[int],
    in_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    out_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    answer_footprint: AnswerFootprint,
    *,
    index_url: Optional[Mapping[int, str]] = None,
    one_hop_edge_budget_nodes: int = DEFAULT_ONE_HOP_EDGE_BUDGET_NODES,
) -> tuple[CandidateLocalProfile, ...]:
    """Profile every candidate, emitted in ascending local-index order.

    The order is a SERIALISATION choice for byte-identical output. It is not a
    ranking: see the module docstring.
    """
    return tuple(
        profile_candidate(
            index, in_neighbor, out_neighbor, answer_footprint,
            index_url=index_url,
            one_hop_edge_budget_nodes=one_hop_edge_budget_nodes,
        )
        for index in sorted(set(local_indices))
    )
