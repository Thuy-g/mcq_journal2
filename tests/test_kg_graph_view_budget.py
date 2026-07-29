############################################################################
# tests/test_kg_graph_view_budget.py
#
# Contract tests for src/kg/graph_view.py — the M1 graph-budget contract.
#
# The contract under test (see the module header of graph_view.py):
#   1. the ordered candidate list is supplied, never reordered here;
#   2. the Answer is always pinned;
#   3. a candidate is accepted only if it AND its complete one-hop IN/OUT
#      neighbourhood fit within max_nodes;
#   4. an accepted candidate's neighbours are never evicted afterwards;
#   5. stop at 50 accepted, or when nothing more fits;
#   6. fewer than 10 accepted -> GRAPH_BUDGET_INSUFFICIENT_CANDIDATES;
#   7. edges are the induced edge set over the retained nodes;
#   8. every included candidate has neighbourhood_coverage_ratio == 1.0.
#
# The rejected alternative is tested too: a candidate that does not fit
# COMPLETELY must be SKIPPED, never partially expanded.
#
# Offline, deterministic, synthetic graphs only. No pickle, no network.
#
# Run:
#     python -m pytest -vv tests/test_kg_graph_view_budget.py
############################################################################

from __future__ import annotations

import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from kg import graph_view as gv  # noqa: E402

# Predicate indices used by the synthetic graphs. Predicates are edge labels and
# must never be counted as nodes.
P1, P2, P3 = 9001, 9002, 9003

# The Answer's own neighbours live in their own numeric range so they cannot
# collide with any candidate's private fan.
ANSWER_NEIGHBOR_BASE = 500_000


def build_kg(triples):
    """(subject, predicate, object) triples -> (in_neighbor, out_neighbor)."""
    out_neighbor: dict[int, list[tuple[int, int]]] = {}
    in_neighbor: dict[int, list[tuple[int, int]]] = {}
    for s, p, o in triples:
        out_neighbor.setdefault(s, []).append((p, o))
        in_neighbor.setdefault(o, []).append((p, s))
    return in_neighbor, out_neighbor


def star_kg(candidate_specs, answer=100, answer_neighbors=0):
    """Build an Answer plus candidates, each with a private neighbour fan.

    candidate_specs: {candidate_index: number_of_private_out_neighbours}.
    Private neighbours are numbered from candidate*1000, and the Answer's own
    neighbours from ANSWER_NEIGHBOR_BASE, so no two fans overlap and the node
    arithmetic in the tests is exact.
    """
    triples = []
    for k in range(answer_neighbors):
        triples.append((answer, P1, ANSWER_NEIGHBOR_BASE + k))
    for candidate, fan in candidate_specs.items():
        for k in range(fan):
            triples.append((candidate, P2, candidate * 1000 + k))
    return build_kg(triples)


# --- collect_complete_one_hop ---------------------------------------------

def test_one_hop_collects_both_directions_and_excludes_predicates():
    in_n, out_n = build_kg([(1, P1, 2), (3, P2, 1), (1, P3, 4)])
    profile = gv.collect_complete_one_hop(1, in_n, out_n)

    assert profile.neighbors == (2, 3, 4)
    assert profile.full_out_degree == 2                 # 1->2, 1->4
    assert profile.full_in_degree == 1                  # 3->1
    assert profile.full_degree == 3
    assert P1 not in profile.neighbors                  # predicates are not nodes


def test_one_hop_neighbors_are_sorted_and_deduplicated():
    """Two predicates joining the same pair cost one node but two degrees."""
    in_n, out_n = build_kg([(1, P1, 5), (1, P2, 5), (1, P1, 3)])
    profile = gv.collect_complete_one_hop(1, in_n, out_n)

    assert profile.neighbors == (3, 5)
    assert profile.distinct_neighbor_count == 2
    assert profile.full_out_degree == 3


def test_one_hop_of_an_isolated_node_is_empty():
    in_n, out_n = build_kg([(1, P1, 2)])
    profile = gv.collect_complete_one_hop(999, in_n, out_n)

    assert profile.neighbors == ()
    assert profile.full_degree == 0


def test_self_loop_adds_degree_but_no_node():
    in_n, out_n = build_kg([(1, P1, 1)])
    profile = gv.collect_complete_one_hop(1, in_n, out_n)

    assert profile.neighbors == ()
    assert profile.full_out_degree == 1
    assert profile.full_in_degree == 1


# --- Answer and candidates pinned -----------------------------------------

def test_answer_and_accepted_candidates_are_all_pinned():
    candidates = list(range(1, 13))
    in_n, out_n = star_kg({c: 2 for c in candidates}, answer_neighbors=3)

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=candidates,
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=1200)

    assert result.status == gv.GRAPH_BUDGET_OK
    assert 100 in result.nodes
    for c in candidates:
        assert c in result.nodes
    assert result.accepted_candidates == tuple(candidates)


def test_answer_complete_neighbourhood_is_part_of_the_pinned_base():
    in_n, out_n = star_kg({c: 1 for c in range(1, 11)}, answer_neighbors=4)

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=list(range(1, 11)),
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=1200)

    for k in range(4):
        assert ANSWER_NEIGHBOR_BASE + k in result.nodes


def test_supplied_candidate_order_is_preserved_not_reordered():
    """The builder must not rank; a high-degree candidate keeps its position."""
    order = [5, 1, 9, 3, 7, 2, 8, 4, 10, 6]
    in_n, out_n = star_kg({c: c for c in order})

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=order,
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=1200)

    assert result.accepted_candidates == tuple(order)
    assert [r.candidate for r in result.candidate_records] == order


# --- Complete neighbourhood for every included candidate ------------------

def test_every_accepted_candidate_has_its_complete_one_hop_neighbourhood():
    candidates = list(range(1, 15))
    in_n, out_n = star_kg({c: 3 for c in candidates}, answer_neighbors=2)

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=candidates,
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=1200)

    node_set = set(result.nodes)
    for c in result.accepted_candidates:
        profile = gv.collect_complete_one_hop(c, in_n, out_n)
        assert set(profile.neighbors) <= node_set


def test_every_included_candidate_has_coverage_ratio_exactly_one():
    candidates = list(range(1, 21))
    in_n, out_n = star_kg({c: (c % 5) + 1 for c in candidates}, answer_neighbors=3)

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=candidates,
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=1200)

    accepted = [r for r in result.candidate_records if r.accepted]
    assert len(accepted) == 20
    for r in accepted:
        assert r.neighborhood_coverage_ratio == 1.0
        assert r.retained_out_degree == r.full_out_degree
        assert r.retained_in_degree == r.full_in_degree
        assert r.retained_neighbor_count == r.distinct_neighbor_count

    gv.assert_full_neighborhood_coverage(result)           # must not raise


def test_isolated_candidate_counts_as_fully_covered():
    """A candidate with no URI-valued neighbour has nothing to truncate."""
    candidates = list(range(1, 11))
    in_n, out_n = star_kg({c: 0 for c in candidates})

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=candidates,
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=50)

    assert result.status == gv.GRAPH_BUDGET_OK
    for r in result.candidate_records:
        assert r.accepted
        assert r.distinct_neighbor_count == 0
        assert r.neighborhood_coverage_ratio == 1.0


def test_full_and_retained_degrees_are_reported_per_candidate():
    in_n, out_n = build_kg([
        (100, P1, 200),                                    # Answer -> 200
        (1, P1, 200), (1, P2, 201), (300, P3, 1),          # candidate 1
    ] + [(c, P1, c * 1000) for c in range(2, 11)])

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=list(range(1, 11)),
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=1200)

    r1 = result.record_for(1)
    assert r1.accepted
    assert (r1.full_out_degree, r1.full_in_degree) == (2, 1)
    assert (r1.retained_out_degree, r1.retained_in_degree) == (2, 1)
    assert r1.neighborhood_coverage_ratio == 1.0


# --- The cap is never exceeded --------------------------------------------

def test_graph_cap_is_never_exceeded():
    candidates = list(range(1, 41))
    in_n, out_n = star_kg({c: 10 for c in candidates}, answer_neighbors=5)

    for max_nodes in (20, 50, 100, 137, 400, 1200):
        result = gv.fit_ordered_candidates_to_graph_budget(
            answer=100, ordered_candidates=candidates,
            in_neighbor=in_n, out_neighbor=out_n, max_nodes=max_nodes)
        assert result.node_count <= max_nodes, max_nodes


def test_candidate_that_does_not_fit_is_skipped_not_partially_expanded():
    """A later, smaller candidate is still admitted after a big one is skipped."""
    # Answer: 1 node. Candidate 1 needs 1 + 100 = 101 nodes -> will not fit.
    # Candidates 2..12 each need 1 + 1 = 2 nodes.
    in_n, out_n = star_kg({1: 100, **{c: 1 for c in range(2, 13)}})

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=list(range(1, 13)),
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=40)

    assert 1 not in result.accepted_candidates
    assert result.accepted_candidates == tuple(range(2, 13))

    big = result.record_for(1)
    assert big.accepted is False
    assert big.rejection_reason == gv.REJECTED_WOULD_EXCEED_MAX_NODES
    assert big.neighborhood_coverage_ratio == 0.0

    # Not one of the skipped candidate's 100 private neighbours may appear.
    assert 1 not in result.nodes
    for k in range(100):
        assert 1 * 1000 + k not in result.nodes
    assert result.node_budget_bound is True


def test_accepted_candidate_neighbours_are_never_evicted_by_a_later_candidate():
    """Contract item 4: the retained set only ever grows."""
    in_n, out_n = star_kg({1: 5, 2: 200, 3: 5, 4: 200, **{c: 1 for c in range(5, 16)}})

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=list(range(1, 16)),
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=60)

    assert 1 in result.accepted_candidates
    for k in range(5):                                     # candidate 1's fan
        assert 1 * 1000 + k in result.nodes
    for c in result.accepted_candidates:
        profile = gv.collect_complete_one_hop(c, in_n, out_n)
        assert set(profile.neighbors) <= set(result.nodes)


def test_candidate_cap_stops_admission_at_fifty():
    candidates = list(range(1, 81))
    in_n, out_n = star_kg({c: 1 for c in candidates})

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=candidates,
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=10_000)

    assert result.accepted_count == gv.MAX_ACCEPTED_CANDIDATES == 50
    assert result.accepted_candidates == tuple(range(1, 51))
    assert result.candidate_cap_reached is True
    for c in range(51, 81):
        assert result.record_for(c).rejection_reason == gv.REJECTED_CANDIDATE_CAP_REACHED


# --- Insufficient candidates ----------------------------------------------

def test_fewer_than_ten_accepted_candidates_reports_insufficient():
    # Each candidate needs 1 + 20 = 21 nodes; a 100-node budget fits 4 of them.
    candidates = list(range(1, 21))
    in_n, out_n = star_kg({c: 20 for c in candidates})

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=candidates,
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=100)

    assert result.accepted_count < gv.MIN_ACCEPTED_CANDIDATES
    assert result.status == gv.GRAPH_BUDGET_INSUFFICIENT_CANDIDATES
    assert result.is_sufficient is False


def test_exactly_ten_accepted_candidates_is_sufficient():
    candidates = list(range(1, 11))
    in_n, out_n = star_kg({c: 1 for c in candidates})

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=candidates,
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=1200)

    assert result.accepted_count == 10
    assert result.status == gv.GRAPH_BUDGET_OK


def test_nine_accepted_candidates_is_insufficient():
    candidates = list(range(1, 10))
    in_n, out_n = star_kg({c: 1 for c in candidates})

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=candidates,
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=1200)

    assert result.accepted_count == 9
    assert result.status == gv.GRAPH_BUDGET_INSUFFICIENT_CANDIDATES


def test_build_m1_graph_emits_no_graph_when_candidates_are_insufficient():
    candidates = list(range(1, 21))
    in_n, out_n = star_kg({c: 20 for c in candidates})

    m1 = gv.build_m1_graph(
        answer=100, ordered_candidates=candidates,
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=100)

    assert m1.status == gv.GRAPH_BUDGET_INSUFFICIENT_CANDIDATES
    assert m1.graph is None
    assert m1.is_ready is False


def test_answer_whose_own_neighbourhood_overruns_the_budget_is_insufficient():
    in_n, out_n = star_kg({c: 1 for c in range(1, 21)}, answer_neighbors=500)

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=list(range(1, 21)),
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=100)

    assert result.answer_base_exceeds_budget is True
    assert result.accepted_count == 0
    assert result.status == gv.GRAPH_BUDGET_INSUFFICIENT_CANDIDATES
    assert result.nodes == (100,)


# --- Duplicates and self-reference ----------------------------------------

def test_the_answer_appearing_in_the_candidate_list_is_rejected():
    in_n, out_n = star_kg({c: 1 for c in range(1, 12)})

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=[100] + list(range(1, 12)),
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=1200)

    assert 100 not in result.accepted_candidates
    assert result.record_for(100).rejection_reason == gv.REJECTED_SAME_AS_ANSWER


def test_a_repeated_candidate_is_accepted_once():
    in_n, out_n = star_kg({c: 1 for c in range(1, 12)})
    order = list(range(1, 12)) + [3, 5]

    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=order,
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=1200)

    assert result.accepted_candidates == tuple(range(1, 12))
    duplicates = [r for r in result.candidate_records
                  if r.rejection_reason == gv.REJECTED_DUPLICATE]
    assert [r.candidate for r in duplicates] == [3, 5]


# --- Induced edges only ---------------------------------------------------

def test_build_induced_graph_keeps_only_edges_with_both_endpoints_retained():
    in_n, out_n = build_kg([
        (1, P1, 2),          # both endpoints retained  -> kept
        (2, P2, 3),          # both endpoints retained  -> kept
        (1, P3, 99),         # 99 not retained          -> dropped
        (98, P1, 2),         # 98 not retained          -> dropped
    ])

    graph = gv.build_induced_graph([1, 2, 3], in_n, out_n)

    assert graph.nodes == (1, 2, 3)
    assert graph.edge_count == 2
    assert graph.distinct_edge_count == 2
    assert graph.edge_labels == tuple(sorted((P1, P2)))
    assert graph.out_neighbor[1] == [(P1, 2)]
    assert graph.out_neighbor[2] == [(P2, 3)]
    assert graph.in_neighbor[2] == [(P1, 1)]
    assert graph.in_neighbor[3] == [(P2, 2)]
    assert graph.out_neighbor[3] == []                     # every node is keyed


def test_induced_graph_of_the_m1_node_set_never_reaches_outside():
    candidates = list(range(1, 16))
    in_n, out_n = star_kg({c: 3 for c in candidates}, answer_neighbors=2)

    m1 = gv.build_m1_graph(
        answer=100, ordered_candidates=candidates,
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=1200)

    assert m1.is_ready
    node_set = set(m1.graph.nodes)
    for u, edges in m1.graph.out_neighbor.items():
        assert u in node_set
        for _p, o in edges:
            assert o in node_set
    for u, edges in m1.graph.in_neighbor.items():
        assert u in node_set
        for _p, s in edges:
            assert s in node_set


def test_induced_edge_count_matches_a_hand_counted_graph():
    candidates = list(range(1, 11))
    in_n, out_n = star_kg({c: 2 for c in candidates}, answer_neighbors=3)

    m1 = gv.build_m1_graph(
        answer=100, ordered_candidates=candidates,
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=1200)

    # 3 Answer edges + 10 candidates x 2 edges = 23; nodes 1 + 3 + 10 + 20 = 34.
    assert m1.graph.node_count == 34
    assert m1.graph.edge_count == 23
    assert m1.graph.edge_label_count == 2                  # P1 and P2


# --- Determinism ----------------------------------------------------------

def _reorder_kg(in_n, out_n):
    """Same graph, different dict insertion order and reversed adjacency lists."""
    new_out = {u: list(reversed(out_n[u])) for u in sorted(out_n, reverse=True)}
    new_in = {u: list(reversed(in_n[u])) for u in sorted(in_n, reverse=True)}
    return new_in, new_out


def test_output_is_independent_of_dict_and_adjacency_order():
    candidates = list(range(1, 31))
    in_n, out_n = star_kg({c: (c % 7) + 1 for c in candidates}, answer_neighbors=4)
    alt_in, alt_out = _reorder_kg(in_n, out_n)

    a = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=candidates,
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=120)
    b = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=candidates,
        in_neighbor=alt_in, out_neighbor=alt_out, max_nodes=120)

    assert a.nodes == b.nodes
    assert a.accepted_candidates == b.accepted_candidates
    assert a.status == b.status
    assert [r.as_record() for r in a.candidate_records] == \
           [r.as_record() for r in b.candidate_records]


def test_repeated_runs_produce_identical_records():
    candidates = list(range(1, 26))
    in_n, out_n = star_kg({c: (c % 4) + 1 for c in candidates}, answer_neighbors=3)

    runs = [
        gv.build_m1_graph(answer=100, ordered_candidates=candidates,
                          in_neighbor=in_n, out_neighbor=out_n,
                          max_nodes=200).as_record()
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2]


def test_induced_graph_node_and_label_order_is_sorted():
    in_n, out_n = build_kg([(5, P3, 1), (1, P1, 5), (5, P2, 9)])
    graph = gv.build_induced_graph([9, 1, 5], in_n, out_n)

    assert graph.nodes == (1, 5, 9)
    assert list(graph.edge_labels) == sorted(graph.edge_labels)


# --- Configuration errors -------------------------------------------------

def test_invalid_budget_parameters_are_rejected():
    in_n, out_n = star_kg({1: 1})
    for kwargs in ({"max_nodes": 0}, {"max_candidates": 0}, {"min_candidates": -1}):
        with pytest.raises(gv.GraphBudgetConfigError):
            gv.fit_ordered_candidates_to_graph_budget(
                answer=100, ordered_candidates=[1],
                in_neighbor=in_n, out_neighbor=out_n, **kwargs)


def test_record_for_an_unoffered_candidate_raises():
    in_n, out_n = star_kg({c: 1 for c in range(1, 11)})
    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=list(range(1, 11)),
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=1200)

    with pytest.raises(KeyError):
        result.record_for(4242)


def test_coverage_assertion_catches_a_partially_covered_accepted_candidate():
    """The guard must actually fire, not merely exist."""
    in_n, out_n = star_kg({c: 1 for c in range(1, 11)})
    result = gv.fit_ordered_candidates_to_graph_budget(
        answer=100, ordered_candidates=list(range(1, 11)),
        in_neighbor=in_n, out_neighbor=out_n, max_nodes=1200)

    tampered_records = list(result.candidate_records)
    first = tampered_records[0]
    tampered_records[0] = gv.CandidateGraphRecord(
        candidate=first.candidate, accepted=True, rejection_reason=None,
        full_out_degree=first.full_out_degree, full_in_degree=first.full_in_degree,
        retained_out_degree=0, retained_in_degree=0,
        neighborhood_coverage_ratio=0.5,
        distinct_neighbor_count=first.distinct_neighbor_count,
        retained_neighbor_count=0)
    tampered = gv.GraphBudgetResult(
        status=result.status, answer=result.answer, nodes=result.nodes,
        accepted_candidates=result.accepted_candidates,
        candidate_records=tuple(tampered_records),
        max_nodes=result.max_nodes, max_candidates=result.max_candidates,
        min_candidates=result.min_candidates,
        candidate_cap_reached=result.candidate_cap_reached,
        node_budget_bound=result.node_budget_bound,
        answer_base_exceeds_budget=result.answer_base_exceeds_budget)

    with pytest.raises(gv.GraphBudgetContractError, match="coverage ratio 1.0"):
        gv.assert_full_neighborhood_coverage(tampered)


def test_frozen_budget_constants_match_the_architecture_decision():
    assert gv.DEFAULT_MAX_NODES == 1200
    assert gv.MAX_ACCEPTED_CANDIDATES == 50
    assert gv.MIN_ACCEPTED_CANDIDATES == 10


def test_graph_view_does_not_compute_overlap_score():
    """Candidate ordering belongs to the selection layer, not to this module."""
    source = (SRC_DIR / "kg" / "graph_view.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "overlapscore" not in lowered.replace("overlapscore or reorder", "")
    assert not hasattr(gv, "rank_candidates")
    assert not hasattr(gv, "overlap_score")
