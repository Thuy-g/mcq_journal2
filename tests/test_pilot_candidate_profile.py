############################################################################
# tests/test_pilot_candidate_profile.py
#
# Contract tests for src/classes/local_candidate_profile.py, plus the
# repository-root pytest discovery fix in pytest.ini.
#
# What these tests defend:
#   * degrees count EDGES with multiplicity while neighbour counts count NODES,
#     and a self-loop adds to the former but not the latter;
#   * complete_one_hop_node_count is the closed neighbourhood size;
#   * complete_one_hop_edge_count is the INDUCED edge count, computed only inside
#     an explicit budget and reported as null (never estimated) beyond it;
#   * fits_under_default_max_nodes_alone agrees EXACTLY with what
#     src/kg/graph_view.py would decide for that candidate offered first — which
#     is what makes the profile descriptive rather than a second, divergent rule;
#   * profiling builds no graph and reorders nothing;
#   * `python -m pytest` from the repository root collects only tests/.
#
# Offline, deterministic, no network, no pinned pickle.
#
# Run:
#     python -m pytest -vv tests/test_pilot_candidate_profile.py
############################################################################

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from classes import local_candidate_profile as lcp   # noqa: E402
from kg import graph_view as gv                      # noqa: E402

ANSWER = 0


def graph(edges):
    """Build (in_neighbor, out_neighbor) from (subject, predicate, object) triples."""
    out_neighbor: dict[int, list[tuple[int, int]]] = {}
    in_neighbor: dict[int, list[tuple[int, int]]] = {}
    for subject, predicate, obj in edges:
        out_neighbor.setdefault(subject, []).append((predicate, obj))
        in_neighbor.setdefault(obj, []).append((predicate, subject))
    return in_neighbor, out_neighbor


def star(center: int, out_targets, in_sources=(), predicate: int = 0):
    return ([(center, predicate, t) for t in out_targets]
            + [(s, predicate, center) for s in in_sources])


def footprint_for(in_neighbor, out_neighbor, *, answer=ANSWER, max_nodes=1200):
    return lcp.profile_answer_footprint(
        "http://dbpedia.org/resource/A", answer, in_neighbor, out_neighbor,
        max_nodes=max_nodes)


# --- Degrees ---------------------------------------------------------------

def test_degrees_and_unique_neighbours_are_reported_separately():
    in_n, out_n = graph(star(5, out_targets=[10, 11, 12], in_sources=[20, 21]))
    fp = footprint_for(in_n, out_n)
    profile = lcp.profile_candidate(5, in_n, out_n, fp)
    assert profile.full_out_degree == 3
    assert profile.full_in_degree == 2
    assert profile.unique_out_neighbors == 3
    assert profile.unique_in_neighbors == 2
    assert profile.distinct_neighbor_count == 5
    assert profile.full_degree == 5


def test_parallel_predicates_raise_the_degree_but_not_the_neighbour_count():
    """LRoleSim normalises by neighbourhood size, the budget spends nodes."""
    in_n, out_n = graph([(5, 0, 10), (5, 1, 10), (5, 2, 10)])
    profile = lcp.profile_candidate(5, in_n, out_n, footprint_for(in_n, out_n))
    assert profile.full_out_degree == 3
    assert profile.unique_out_neighbors == 1
    assert profile.distinct_neighbor_count == 1
    assert profile.complete_one_hop_node_count == 2


def test_a_self_loop_adds_an_edge_but_no_node_and_is_reported():
    in_n, out_n = graph([(5, 0, 5), (5, 0, 10)])
    profile = lcp.profile_candidate(5, in_n, out_n, footprint_for(in_n, out_n))
    assert profile.full_out_degree == 2
    assert profile.unique_out_neighbors == 1          # 10 only; self excluded
    assert profile.has_self_loop is True
    assert profile.complete_one_hop_node_count == 2   # {5, 10}


def test_a_node_with_no_edges_profiles_as_isolated():
    in_n, out_n = graph([(100, 0, 101)])
    profile = lcp.profile_candidate(7, in_n, out_n, footprint_for(in_n, out_n))
    assert profile.full_out_degree == 0
    assert profile.full_in_degree == 0
    assert profile.distinct_neighbor_count == 0
    assert profile.complete_one_hop_node_count == 1   # itself
    assert profile.complete_one_hop_edge_count == 0
    assert profile.incident_edge_count == 0


def test_degrees_agree_with_graph_view_collect_complete_one_hop():
    in_n, out_n = graph(star(5, [10, 11], [20]) + [(5, 1, 10), (5, 0, 5)])
    reference = gv.collect_complete_one_hop(5, in_n, out_n)
    profile = lcp.profile_candidate(5, in_n, out_n, footprint_for(in_n, out_n))
    assert profile.full_out_degree == reference.full_out_degree
    assert profile.full_in_degree == reference.full_in_degree
    assert profile.distinct_neighbor_count == reference.distinct_neighbor_count
    assert profile.complete_one_hop_node_count == len(reference.neighbors) + 1


# --- One-hop footprint -----------------------------------------------------

def test_complete_one_hop_node_count_is_the_closed_neighbourhood():
    in_n, out_n = graph(star(5, [10, 11, 12], [10, 20]))    # 10 appears both ways
    profile = lcp.profile_candidate(5, in_n, out_n, footprint_for(in_n, out_n))
    assert profile.distinct_neighbor_count == 4              # 10, 11, 12, 20
    assert profile.complete_one_hop_node_count == 5          # plus 5 itself


def test_induced_one_hop_edge_count_includes_edges_between_neighbours():
    """The count is INDUCED, so a neighbour-to-neighbour edge belongs in it."""
    in_n, out_n = graph([(5, 0, 10), (5, 0, 11), (10, 0, 11)])
    profile = lcp.profile_candidate(5, in_n, out_n, footprint_for(in_n, out_n))
    assert profile.complete_one_hop_node_count == 3
    assert profile.complete_one_hop_edge_count == 3
    assert profile.one_hop_edge_count_state == lcp.ONE_HOP_EDGES_COMPUTED
    # The cheap incident count only sees edges touching the node itself.
    assert profile.incident_edge_count == 2


def test_induced_edge_count_excludes_edges_leaving_the_footprint():
    in_n, out_n = graph([(5, 0, 10), (10, 0, 99)])
    profile = lcp.profile_candidate(5, in_n, out_n, footprint_for(in_n, out_n))
    assert profile.complete_one_hop_node_count == 2           # {5, 10}
    assert profile.complete_one_hop_edge_count == 1           # 10->99 excluded


def test_induced_edge_count_keeps_multiplicity():
    in_n, out_n = graph([(5, 0, 10), (5, 1, 10)])
    profile = lcp.profile_candidate(5, in_n, out_n, footprint_for(in_n, out_n))
    assert profile.complete_one_hop_edge_count == 2


def test_induced_edge_count_agrees_with_build_induced_graph():
    in_n, out_n = graph([(5, 0, 10), (5, 1, 11), (10, 0, 11), (11, 0, 5),
                         (10, 0, 99)])
    profile = lcp.profile_candidate(5, in_n, out_n, footprint_for(in_n, out_n))
    closed = {5, *gv.collect_complete_one_hop(5, in_n, out_n).neighbors}
    reference = gv.build_induced_graph(closed, in_n, out_n)
    assert profile.complete_one_hop_edge_count == reference.edge_count


def test_an_oversized_footprint_reports_null_rather_than_an_estimate():
    in_n, out_n = graph(star(5, list(range(1000, 1050))))
    profile = lcp.profile_candidate(
        5, in_n, out_n, footprint_for(in_n, out_n), one_hop_edge_budget_nodes=10)
    assert profile.complete_one_hop_edge_count is None
    assert profile.one_hop_edge_count_state == lcp.ONE_HOP_EDGES_SKIPPED_TOO_LARGE
    # The cheap, exact incident count is still reported.
    assert profile.incident_edge_count == 50


# --- The Answer's reserved base --------------------------------------------

def test_the_answer_base_is_itself_plus_its_complete_one_hop():
    in_n, out_n = graph(star(ANSWER, [1, 2, 3], [4]))
    fp = footprint_for(in_n, out_n, max_nodes=1200)
    assert fp.base_node_count == 5                       # {0,1,2,3,4}
    assert fp.remaining_node_budget == 1195
    assert not fp.base_exceeds_budget
    assert fp.base_nodes == frozenset({0, 1, 2, 3, 4})


def test_an_answer_base_over_budget_is_flagged_and_the_budget_clamps_at_zero():
    in_n, out_n = graph(star(ANSWER, list(range(1, 20))))
    fp = footprint_for(in_n, out_n, max_nodes=5)
    assert fp.base_exceeds_budget
    assert fp.remaining_node_budget == 0


def test_no_candidate_fits_when_the_answer_base_already_overruns():
    in_n, out_n = graph(star(ANSWER, list(range(1, 20))) + [(50, 0, 51)])
    fp = footprint_for(in_n, out_n, max_nodes=5)
    profile = lcp.profile_candidate(50, in_n, out_n, fp)
    assert profile.fits_under_default_max_nodes_alone is False


def test_default_max_nodes_is_the_graph_view_constant():
    assert lcp.DEFAULT_MAX_NODES == 1200
    assert gv.DEFAULT_MAX_NODES == 1200


# --- "Fits alone" ----------------------------------------------------------

def test_nodes_shared_with_the_answer_base_are_already_paid_for():
    in_n, out_n = graph(star(ANSWER, [1, 2, 3]) + star(9, [1, 2, 3]))
    fp = footprint_for(in_n, out_n)
    profile = lcp.profile_candidate(9, in_n, out_n, fp)
    assert profile.complete_one_hop_node_count == 4          # {9,1,2,3}
    assert profile.new_nodes_beyond_answer_base == 1         # only 9 is new
    assert profile.fits_under_default_max_nodes_alone


@pytest.mark.parametrize("max_nodes,expected", [
    (4, True),      # base {0,1} = 2, candidate adds {9,10} = 2 -> 4 fits
    (3, False),     # 2 + 2 = 4 > 3
])
def test_the_fits_alone_boundary(max_nodes, expected):
    in_n, out_n = graph([(ANSWER, 0, 1), (9, 0, 10)])
    fp = footprint_for(in_n, out_n, max_nodes=max_nodes)
    profile = lcp.profile_candidate(9, in_n, out_n, fp)
    assert profile.fits_under_default_max_nodes_alone is expected


@pytest.mark.parametrize("max_nodes", [2, 3, 4, 5, 8, 20, 1200])
def test_fits_alone_matches_what_the_graph_budget_would_decide(max_nodes):
    """The profile must not become a second, subtly different rule.

    Cross-checked against src/kg/graph_view.py rather than restated, so a change
    to the admission contract cannot leave the profiling silently disagreeing.
    """
    in_n, out_n = graph(
        star(ANSWER, [1, 2]) + star(9, [10, 11, 2]) + [(10, 0, 11)])
    fp = footprint_for(in_n, out_n, max_nodes=max_nodes)
    profile = lcp.profile_candidate(9, in_n, out_n, fp)

    budget = gv.fit_ordered_candidates_to_graph_budget(
        answer=ANSWER, ordered_candidates=[9], in_neighbor=in_n,
        out_neighbor=out_n, max_nodes=max_nodes, min_candidates=0)
    admitted = 9 in budget.accepted_candidates
    assert profile.fits_under_default_max_nodes_alone is admitted


def test_fits_alone_is_per_candidate_not_joint():
    """Two candidates that each fit alone need not both fit together."""
    in_n, out_n = graph([(ANSWER, 0, 1), (8, 0, 80), (9, 0, 90)])
    fp = footprint_for(in_n, out_n, max_nodes=4)
    for candidate in (8, 9):
        assert lcp.profile_candidate(
            candidate, in_n, out_n, fp).fits_under_default_max_nodes_alone

    joint = gv.fit_ordered_candidates_to_graph_budget(
        answer=ANSWER, ordered_candidates=[8, 9], in_neighbor=in_n,
        out_neighbor=out_n, max_nodes=4, min_candidates=0)
    assert joint.accepted_candidates == (8,)      # the second no longer fits


# --- Determinism and scope -------------------------------------------------

def test_profiles_are_emitted_in_ascending_local_index_order():
    in_n, out_n = graph([(ANSWER, 0, 1)] + [(i, 0, i + 100) for i in (7, 3, 9, 5)])
    fp = footprint_for(in_n, out_n)
    profiles = lcp.profile_candidates([9, 3, 7, 5], in_n, out_n, fp)
    assert [p.local_index for p in profiles] == [3, 5, 7, 9]


def test_duplicate_indices_are_profiled_once():
    in_n, out_n = graph([(ANSWER, 0, 1), (9, 0, 10)])
    fp = footprint_for(in_n, out_n)
    assert len(lcp.profile_candidates([9, 9, 9], in_n, out_n, fp)) == 1


def test_profiling_is_repeatable():
    in_n, out_n = graph(star(ANSWER, [1, 2]) + star(9, [10, 11]))
    fp = footprint_for(in_n, out_n)
    a = lcp.profile_candidates([9], in_n, out_n, fp)[0].as_record()
    b = lcp.profile_candidates([9], in_n, out_n, fp)[0].as_record()
    assert a == b


def test_the_local_uri_is_reported_when_the_index_map_is_supplied():
    in_n, out_n = graph([(ANSWER, 0, 1), (9, 0, 10)])
    fp = footprint_for(in_n, out_n)
    profile = lcp.profile_candidate(
        9, in_n, out_n, fp, index_url={9: "<http://dbpedia.org/resource/X>"})
    assert profile.local_uri == "<http://dbpedia.org/resource/X>"


def test_the_profile_record_has_no_ranking_or_score_field():
    """§4 forbids ordering, OverlapScore and LRoleSim in this stage."""
    in_n, out_n = graph([(ANSWER, 0, 1), (9, 0, 10)])
    record = lcp.profile_candidate(
        9, in_n, out_n, footprint_for(in_n, out_n)).as_record()
    forbidden = ("rank", "score", "overlap", "lrolesim", "similarity",
                 "priority", "distractor", "rationale")
    for key in record:
        assert not any(token in key.lower() for token in forbidden), key


def test_profiling_does_not_mutate_the_adjacency_it_reads():
    in_n, out_n = graph(star(ANSWER, [1, 2]) + star(9, [10, 11]))
    before_in = {k: list(v) for k, v in in_n.items()}
    before_out = {k: list(v) for k, v in out_n.items()}
    lcp.profile_candidates([9], in_n, out_n, footprint_for(in_n, out_n))
    assert in_n == before_in
    assert out_n == before_out


# --- Repository-root pytest discovery -------------------------------------

def test_pytest_ini_exists_and_pins_discovery():
    import configparser
    path = REPO_ROOT / "pytest.ini"
    assert path.is_file()
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    section = parser["pytest"]
    assert section["testpaths"].split() == ["tests"]
    assert set(section["norecursedirs"].split()) >= {"outputs", "legacy", "notebooks"}
    assert "integration" in section["markers"]


def test_the_archived_colliding_test_file_still_exists_untouched():
    """The fix must not have been "rename or delete the archive"."""
    archived = (REPO_ROOT / "outputs" / "checkpoints"
                / "category_selector_v3_before_final_core_patch"
                / "test_category_extractor_v3.py")
    assert archived.is_file()
    assert (REPO_ROOT / "tests" / "test_category_extractor_v3.py").is_file()


def test_root_collection_only_reaches_the_tests_tree():
    """A bare `python -m pytest` used to fail on the basename collision."""
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stdout[-3000:] + completed.stderr[-2000:]
    collected = [line for line in completed.stdout.splitlines() if "::" in line]
    assert collected, completed.stdout[-2000:]
    assert all(line.startswith("tests/") for line in collected), [
        line for line in collected if not line.startswith("tests/")][:5]
    # The archived copy under outputs/checkpoints/ must not be collected at all.
    assert "outputs/checkpoints" not in completed.stdout
    # Check the SUMMARY line, not the whole output: several legitimate test names
    # contain the word "error".
    summary = [line for line in completed.stdout.splitlines() if line.strip()][-1]
    assert "collected" in summary, summary
    assert "error" not in summary.lower(), summary


def test_the_integration_marker_is_registered():
    """CLAUDE.md requires the marker; registering it removes the warning."""
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--markers", "-p", "no:cacheprovider"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0
    assert "@pytest.mark.integration" in completed.stdout
