############################################################################
# src/kg/graph_view.py
#
# The M1 graph-budget contract for the nine-Answer pilot.
#
# THE CONTRACT (binding; supersedes the per-seed-quota sketch in
# outputs/journal2_pdf_grounded_reconciliation_2026-07-30/implementation_handoff.md
# patch P2, which is NOT implemented here — see "GRAPH-CAP CORRECTION" below)
#
#   1. The ordered candidate list is supplied by the caller.
#   2. The Answer is always pinned.
#   3. A candidate is accepted only when the candidate AND its complete
#      URI-valued one-hop IN/OUT neighbourhood fit without exceeding max_nodes.
#   4. Once accepted, no neighbour of that candidate may be removed by the budget.
#   5. Continue through the ordered list until 50 candidates are accepted, or no
#      further candidate fits.
#   6. Fewer than 10 accepted candidates  ->  GRAPH_BUDGET_INSUFFICIENT_CANDIDATES,
#      after which the class-policy layer may try the next APPROVED fallback.
#   7. Edges are the induced edge set over the final retained nodes.
#   8. Per included candidate, record full/retained IN and OUT degree and the
#      neighbourhood coverage ratio, which must be exactly 1.0.
#
# GRAPH-CAP CORRECTION
#   The earlier handoff proposed a per-seed neighbour quota, i.e. truncating each
#   candidate's neighbourhood to an equal share of the budget. That is rejected.
#   A truncated neighbourhood changes the candidate's equivalence classes and its
#   degree, and LRoleSim normalises by max(|N(u)|,|N(v)|) — so a partially
#   expanded candidate is scored against a neighbourhood it does not have. "Equal
#   truncation for everyone" is not fairness, it is a uniformly wrong graph.
#   Instead, admission is all-or-nothing per candidate: a candidate that does not
#   fit COMPLETELY is skipped, never partially expanded. Every candidate that
#   reaches LRoleSim therefore has coverage ratio 1.0, and the cost of the budget
#   is a smaller, honestly reported candidate set rather than a silently distorted
#   graph.
#
# OUT OF SCOPE HERE
#   This module must NOT compute OverlapScore or reorder candidates. It receives
#   an already ordered list; candidate ordering belongs to the selection layer.
#
# DETERMINISM
#   No output depends on Python set or dict iteration order. Sets are used only
#   for membership tests; everything emitted is either sorted by node index or
#   kept in the caller's supplied candidate order.
############################################################################

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

# --- Frozen budget constants ----------------------------------------------
# Grounded in architecture_decision_v2.md section 1: node cap 1200, candidate
# cap 50, and the G1 >= 10 candidate gate.
DEFAULT_MAX_NODES = 1200
MAX_ACCEPTED_CANDIDATES = 50
MIN_ACCEPTED_CANDIDATES = 10

# --- Statuses --------------------------------------------------------------
GRAPH_BUDGET_OK = "GRAPH_BUDGET_OK"
GRAPH_BUDGET_INSUFFICIENT_CANDIDATES = "GRAPH_BUDGET_INSUFFICIENT_CANDIDATES"

# --- Per-candidate rejection reasons --------------------------------------
REJECTED_WOULD_EXCEED_MAX_NODES = "WOULD_EXCEED_MAX_NODES"
REJECTED_CANDIDATE_CAP_REACHED = "NOT_CONSIDERED_CANDIDATE_CAP_REACHED"
REJECTED_SAME_AS_ANSWER = "SAME_AS_ANSWER"
REJECTED_DUPLICATE = "DUPLICATE_CANDIDATE"
REJECTED_ANSWER_BASE_EXCEEDS_BUDGET = "NOT_CONSIDERED_ANSWER_BASE_EXCEEDS_BUDGET"


class GraphBudgetError(Exception):
    """Base class for graph-budget contract failures."""


class GraphBudgetContractError(GraphBudgetError):
    """An invariant of the contract above was violated — a bug, not bad input."""


class GraphBudgetConfigError(GraphBudgetError):
    """The budget parameters themselves are unusable."""


# --- One-hop neighbourhoods ------------------------------------------------

@dataclass(frozen=True)
class NeighborhoodProfile:
    """The complete URI-valued one-hop neighbourhood of one node.

    `neighbors` holds DISTINCT neighbour node indices (what the node budget
    spends), while the degrees count EDGES with multiplicity (what LRoleSim
    normalises by). The two differ whenever a pair of nodes is joined by more
    than one predicate, so both are recorded.
    """

    node: int
    neighbors: tuple[int, ...]
    full_out_degree: int
    full_in_degree: int

    @property
    def distinct_neighbor_count(self) -> int:
        return len(self.neighbors)

    @property
    def full_degree(self) -> int:
        return self.full_out_degree + self.full_in_degree


def collect_complete_one_hop(
    node: int,
    in_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    out_neighbor: Mapping[int, Sequence[tuple[int, int]]],
) -> NeighborhoodProfile:
    """Complete URI-valued one-hop IN and OUT neighbourhood of `node`.

    Predicates are edge labels, not nodes, so they are never collected. A
    self-loop contributes to the degree but adds no new node, so `node` itself is
    excluded from `neighbors`.
    """
    out_edges = out_neighbor.get(node, ())
    in_edges = in_neighbor.get(node, ())

    neighbors: set[int] = set()
    for _p, o in out_edges:
        if o != node:
            neighbors.add(o)
    for _p, s in in_edges:
        if s != node:
            neighbors.add(s)

    return NeighborhoodProfile(
        node=node,
        neighbors=tuple(sorted(neighbors)),      # sorted: deterministic output
        full_out_degree=len(out_edges),
        full_in_degree=len(in_edges),
    )


# --- Candidate admission ---------------------------------------------------

@dataclass(frozen=True)
class CandidateGraphRecord:
    """Per-candidate provenance required by the contract, item 8."""

    candidate: int
    accepted: bool
    rejection_reason: Optional[str]
    full_out_degree: int
    full_in_degree: int
    retained_out_degree: int
    retained_in_degree: int
    neighborhood_coverage_ratio: float
    distinct_neighbor_count: int
    retained_neighbor_count: int

    def as_record(self) -> dict:
        return {
            "candidate": self.candidate,
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
            "full_out_degree": self.full_out_degree,
            "full_in_degree": self.full_in_degree,
            "retained_out_degree": self.retained_out_degree,
            "retained_in_degree": self.retained_in_degree,
            "neighborhood_coverage_ratio": self.neighborhood_coverage_ratio,
            "distinct_neighbor_count": self.distinct_neighbor_count,
            "retained_neighbor_count": self.retained_neighbor_count,
        }


@dataclass(frozen=True)
class GraphBudgetResult:
    """Which candidates the node budget admitted, and the resulting node set."""

    status: str
    answer: int
    nodes: tuple[int, ...]
    accepted_candidates: tuple[int, ...]
    candidate_records: tuple[CandidateGraphRecord, ...]
    max_nodes: int
    max_candidates: int
    min_candidates: int
    candidate_cap_reached: bool
    node_budget_bound: bool
    answer_base_exceeds_budget: bool

    @property
    def is_sufficient(self) -> bool:
        return self.status == GRAPH_BUDGET_OK

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_candidates)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    def record_for(self, candidate: int) -> CandidateGraphRecord:
        for record in self.candidate_records:
            if record.candidate == candidate:
                return record
        raise KeyError(f"candidate {candidate} was not offered to the graph budget")

    def as_record(self) -> dict:
        return {
            "status": self.status,
            "answer": self.answer,
            "node_count": self.node_count,
            "max_nodes": self.max_nodes,
            "accepted_candidate_count": self.accepted_count,
            "accepted_candidates": list(self.accepted_candidates),
            "max_candidates": self.max_candidates,
            "min_candidates": self.min_candidates,
            "candidate_cap_reached": self.candidate_cap_reached,
            "node_budget_bound": self.node_budget_bound,
            "answer_base_exceeds_budget": self.answer_base_exceeds_budget,
            "candidates": [r.as_record() for r in self.candidate_records],
        }


def _retained_degrees(
    node: int,
    retained: frozenset[int],
    in_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    out_neighbor: Mapping[int, Sequence[tuple[int, int]]],
) -> tuple[int, int, int]:
    """(retained_out_degree, retained_in_degree, retained distinct neighbours)."""
    retained_out = 0
    retained_neighbors: set[int] = set()
    for _p, o in out_neighbor.get(node, ()):
        if o in retained:
            retained_out += 1
            if o != node:
                retained_neighbors.add(o)
    retained_in = 0
    for _p, s in in_neighbor.get(node, ()):
        if s in retained:
            retained_in += 1
            if s != node:
                retained_neighbors.add(s)
    return retained_out, retained_in, len(retained_neighbors)


def _coverage_ratio(profile: NeighborhoodProfile, retained_neighbor_count: int) -> float:
    """|N1(c) inter V| / |N1(c)|, with an isolated node defined as fully covered.

    A node with no URI-valued neighbours has nothing that could be truncated, so
    treating it as 1.0 keeps the contract's "every included candidate is 1.0"
    check meaningful instead of dividing by zero.
    """
    if profile.distinct_neighbor_count == 0:
        return 1.0
    return retained_neighbor_count / profile.distinct_neighbor_count


def fit_ordered_candidates_to_graph_budget(
    answer: int,
    ordered_candidates: Iterable[int],
    in_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    out_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    max_nodes: int = DEFAULT_MAX_NODES,
    max_candidates: int = MAX_ACCEPTED_CANDIDATES,
    min_candidates: int = MIN_ACCEPTED_CANDIDATES,
) -> GraphBudgetResult:
    """Admit candidates from `ordered_candidates` under the node budget.

    Walks the supplied order and never reorders it. Admission is all-or-nothing:
    a candidate whose complete one-hop neighbourhood does not fit is SKIPPED, and
    the walk continues to the next candidate — a later, smaller candidate can
    still be admitted after a larger one was skipped.
    """
    if max_nodes < 1:
        raise GraphBudgetConfigError(f"max_nodes must be >= 1, got {max_nodes}")
    if max_candidates < 1:
        raise GraphBudgetConfigError(
            f"max_candidates must be >= 1, got {max_candidates}")
    if min_candidates < 0:
        raise GraphBudgetConfigError(
            f"min_candidates must be >= 0, got {min_candidates}")

    # Contract item 2: the Answer and its complete neighbourhood are the pinned
    # base of the graph and are charged to the budget first.
    answer_profile = collect_complete_one_hop(answer, in_neighbor, out_neighbor)
    base_nodes = {answer, *answer_profile.neighbors}
    answer_base_exceeds_budget = len(base_nodes) > max_nodes

    retained: set[int]
    if answer_base_exceeds_budget:
        # The Answer alone already overruns the budget, so no candidate can be
        # admitted with complete coverage. Keeping only the Answer node makes the
        # failure visible rather than emitting an over-budget graph.
        retained = {answer}
    else:
        retained = set(base_nodes)

    # Deduplicate while preserving the supplied order (contract item 1).
    seen: set[int] = set()
    accepted: list[int] = []
    pending: list[tuple[int, Optional[str], Optional[NeighborhoodProfile]]] = []
    node_budget_bound = False

    for candidate in ordered_candidates:
        if candidate == answer:
            pending.append((candidate, REJECTED_SAME_AS_ANSWER, None))
            continue
        if candidate in seen:
            pending.append((candidate, REJECTED_DUPLICATE, None))
            continue
        seen.add(candidate)

        if answer_base_exceeds_budget:
            pending.append((candidate, REJECTED_ANSWER_BASE_EXCEEDS_BUDGET, None))
            continue
        # Contract item 5: stop considering candidates once the cap is reached.
        if len(accepted) >= max_candidates:
            pending.append((candidate, REJECTED_CANDIDATE_CAP_REACHED, None))
            continue

        profile = collect_complete_one_hop(candidate, in_neighbor, out_neighbor)
        addition = ({candidate, *profile.neighbors}) - retained
        if len(retained) + len(addition) > max_nodes:
            # Contract item 3: all-or-nothing. Skip, do not partially expand.
            node_budget_bound = True
            pending.append((candidate, REJECTED_WOULD_EXCEED_MAX_NODES, profile))
            continue

        # Contract item 4: nodes are only ever added, never evicted.
        retained |= addition
        accepted.append(candidate)
        pending.append((candidate, None, profile))

    nodes = tuple(sorted(retained))
    frozen_retained = frozenset(retained)

    records: list[CandidateGraphRecord] = []
    for candidate, reason, profile in pending:
        if profile is None:
            profile = collect_complete_one_hop(candidate, in_neighbor, out_neighbor)
        is_accepted = reason is None
        if is_accepted:
            retained_out, retained_in, retained_neighbors = _retained_degrees(
                candidate, frozen_retained, in_neighbor, out_neighbor)
            coverage = _coverage_ratio(profile, retained_neighbors)
        else:
            # A rejected candidate is not in the graph at all; reporting zero
            # retained degree and zero coverage keeps "0.0 means absent" and
            # "1.0 means complete" unambiguous in the provenance record.
            retained_out = retained_in = retained_neighbors = 0
            coverage = 0.0
        records.append(CandidateGraphRecord(
            candidate=candidate,
            accepted=is_accepted,
            rejection_reason=reason,
            full_out_degree=profile.full_out_degree,
            full_in_degree=profile.full_in_degree,
            retained_out_degree=retained_out,
            retained_in_degree=retained_in,
            neighborhood_coverage_ratio=coverage,
            distinct_neighbor_count=profile.distinct_neighbor_count,
            retained_neighbor_count=retained_neighbors,
        ))

    if len(nodes) > max_nodes and not answer_base_exceeds_budget:
        raise GraphBudgetContractError(
            f"graph budget exceeded: {len(nodes)} nodes > max_nodes {max_nodes}"
        )

    status = (GRAPH_BUDGET_OK if len(accepted) >= min_candidates
              else GRAPH_BUDGET_INSUFFICIENT_CANDIDATES)

    return GraphBudgetResult(
        status=status,
        answer=answer,
        nodes=nodes,
        accepted_candidates=tuple(accepted),
        candidate_records=tuple(records),
        max_nodes=max_nodes,
        max_candidates=max_candidates,
        min_candidates=min_candidates,
        candidate_cap_reached=len(accepted) >= max_candidates,
        node_budget_bound=node_budget_bound,
        answer_base_exceeds_budget=answer_base_exceeds_budget,
    )


# --- Induced graph ---------------------------------------------------------

@dataclass(frozen=True)
class InducedGraph:
    """The edge-induced subgraph over a fixed node set.

    `in_neighbor`/`out_neighbor` are plain dicts keyed by every node in `nodes`,
    ready to hand to the LRoleSim kernel. Edge order inside each list follows the
    source KG, so the structure is reproducible from the same pinned pickle.
    """

    nodes: tuple[int, ...]
    in_neighbor: dict[int, list[tuple[int, int]]]
    out_neighbor: dict[int, list[tuple[int, int]]]
    edge_count: int
    distinct_edge_count: int
    edge_labels: tuple[int, ...]

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_label_count(self) -> int:
        return len(self.edge_labels)

    def as_record(self) -> dict:
        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "distinct_edge_count": self.distinct_edge_count,
            "edge_label_count": self.edge_label_count,
        }


def build_induced_graph(
    nodes: Iterable[int],
    in_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    out_neighbor: Mapping[int, Sequence[tuple[int, int]]],
) -> InducedGraph:
    """Keep exactly the edges whose BOTH endpoints are in `nodes` (contract item 7).

    `edge_count` counts retained OUT edges with multiplicity, which is the edge
    multiset LRoleSim actually consumes; `distinct_edge_count` counts distinct
    (subject, predicate, object) triples. They differ only if the source dump
    repeats a triple.
    """
    node_tuple = tuple(sorted(set(nodes)))
    node_set = frozenset(node_tuple)

    reduced_out: dict[int, list[tuple[int, int]]] = {}
    reduced_in: dict[int, list[tuple[int, int]]] = {}
    edge_count = 0
    distinct: set[tuple[int, int, int]] = set()
    labels: set[int] = set()

    for u in node_tuple:
        kept_out = [(p, o) for p, o in out_neighbor.get(u, ()) if o in node_set]
        reduced_out[u] = kept_out
        edge_count += len(kept_out)
        for p, o in kept_out:
            distinct.add((u, p, o))
            labels.add(p)
        reduced_in[u] = [(p, s) for p, s in in_neighbor.get(u, ()) if s in node_set]

    return InducedGraph(
        nodes=node_tuple,
        in_neighbor=reduced_in,
        out_neighbor=reduced_out,
        edge_count=edge_count,
        distinct_edge_count=len(distinct),
        edge_labels=tuple(sorted(labels)),      # sorted: deterministic output
    )


# --- The M1 graph ----------------------------------------------------------

@dataclass(frozen=True)
class M1Graph:
    """A pilot-ready M1 graph: budget outcome plus the induced subgraph."""

    status: str
    answer: int
    budget: GraphBudgetResult
    graph: Optional[InducedGraph]

    @property
    def is_ready(self) -> bool:
        """True only when the graph may be sent to LRoleSim."""
        return self.status == GRAPH_BUDGET_OK and self.graph is not None

    @property
    def accepted_candidates(self) -> tuple[int, ...]:
        return self.budget.accepted_candidates

    def as_record(self) -> dict:
        return {
            "status": self.status,
            "answer": self.answer,
            "budget": self.budget.as_record(),
            "graph": None if self.graph is None else self.graph.as_record(),
        }


def assert_full_neighborhood_coverage(budget: GraphBudgetResult) -> None:
    """Every ACCEPTED candidate must have coverage ratio exactly 1.0.

    The primary M1 pilot forbids sending a partially expanded candidate to
    LRoleSim, so this is checked rather than assumed.
    """
    offenders = [
        (r.candidate, r.neighborhood_coverage_ratio)
        for r in budget.candidate_records
        if r.accepted and r.neighborhood_coverage_ratio != 1.0
    ]
    if offenders:
        raise GraphBudgetContractError(
            "accepted candidates must have neighbourhood coverage ratio 1.0; "
            f"offenders (candidate, ratio): {offenders}"
        )


def build_m1_graph(
    answer: int,
    ordered_candidates: Iterable[int],
    in_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    out_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    max_nodes: int = DEFAULT_MAX_NODES,
    max_candidates: int = MAX_ACCEPTED_CANDIDATES,
    min_candidates: int = MIN_ACCEPTED_CANDIDATES,
) -> M1Graph:
    """Build the M1 graph for one Answer from an ALREADY ORDERED candidate list.

    Returns an M1Graph whose status is GRAPH_BUDGET_INSUFFICIENT_CANDIDATES when
    fewer than `min_candidates` fit; in that case `graph` is None and the class
    policy layer may try the next APPROVED fallback class. No graph is emitted
    for a state the pilot is not allowed to rank.
    """
    budget = fit_ordered_candidates_to_graph_budget(
        answer=answer,
        ordered_candidates=ordered_candidates,
        in_neighbor=in_neighbor,
        out_neighbor=out_neighbor,
        max_nodes=max_nodes,
        max_candidates=max_candidates,
        min_candidates=min_candidates,
    )
    assert_full_neighborhood_coverage(budget)

    if budget.status != GRAPH_BUDGET_OK:
        return M1Graph(status=budget.status, answer=answer, budget=budget, graph=None)

    graph = build_induced_graph(budget.nodes, in_neighbor, out_neighbor)
    return M1Graph(status=GRAPH_BUDGET_OK, answer=answer, budget=budget, graph=graph)
