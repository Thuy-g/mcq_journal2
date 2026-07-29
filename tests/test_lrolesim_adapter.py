############################################################################
# tests/test_lrolesim_adapter.py
#
# Contract tests for src/lrolesim/adapter.py and the narrow fixed-iteration
# patch to src/MCQ_lrolesim_ClaudeWeb_v2.py.
#
# What these tests defend:
#   * the pilot runs EXACTLY three iterations, counted as observed, not assumed;
#   * the convergence path is still reachable, under its own explicit API;
#   * lrolesim_beta is 0.2 in the pilot adapter, and the OverlapLoose weight can
#     never be passed in under the name `beta`;
#   * L_ed is primary and L_edt is available as an ablation;
#   * the HanamiSpots graph and final similarities reproduce the published
#     values.
#
# PDF EVIDENCE (verified in this task, see the implementation report)
#   docs/references/Explainability_of_LRoleSim.pdf
#     sha256 2aadbc087c14ba4d0e99b37f21589c953931f6b3286be35bd8293ce9ebd58804
#     p. 1  HanamiSpots = 4 seeds + all immediate neighbours + induced edges,
#           "13 nodes, 15 edges, and 6 edge labels"
#     p. 2  Table 1 "Final similarity":
#             LRoleSim_ed            Kamagatani 1.000, Hinokinai 0.867
#             LRoleSim_ed EntityType Kamagatani 1.000, Hinokinai 0.600
#           every other node 0.200
#   docs/references/Official_LRoleSim_Aug2025.pdf
#     sha256 faaaffd6bb6cf8549a61b915b7025b5069ceaaf53e925fd921faa9cc9c89ea74
#     PDF p. 8 = printed p. 436: "We set the parameters as beta = 0.2 and k = 3."
#
# Offline: the graph comes from tests/fixtures/hanami_spots_offline.json, which
# was extracted once from the pinned local pickle. No network, no 1.2 GB load.
#
# Run:
#     python -m pytest -vv tests/test_lrolesim_adapter.py
############################################################################

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from kg import graph_view as gv          # noqa: E402
from lrolesim import adapter as ad       # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "hanami_spots_offline.json"

# Values transcribed from the PDF, independent of the kernel's own fixture, so a
# drift in either shows up as a failure rather than agreeing with itself.
PDF_FINAL_L_ED = {"Kamagatani": 1.000, "Hinokinai_River_Embankment": 0.867}
PDF_FINAL_L_EDT = {"Kamagatani": 1.000, "Hinokinai_River_Embankment": 0.600}
PDF_BETA_FLOOR = 0.200
PDF_STRUCTURE = {"nodes": 13, "edges": 15, "edge_labels": 6}
PDF_TOLERANCE = 5e-4                      # the paper rounds to 3 decimals

DBR = "http://dbpedia.org/resource/"


class HanamiFixture:
    """The offline HanamiSpots graph, indexed exactly as a read_ttl pickle is."""

    def __init__(self, payload: dict):
        self.payload = payload
        uris = sorted(set(payload["nodes"]) | {e[1] for e in payload["edges"]})
        self.url_index = {u: i for i, u in enumerate(uris)}
        self.index_url = {i: u for u, i in self.url_index.items()}

        self.out_neighbor: dict[int, list[tuple[int, int]]] = {}
        self.in_neighbor: dict[int, list[tuple[int, int]]] = {}
        for s, p, o in payload["edges"]:
            si, pi, oi = self.url_index[s], self.url_index[p], self.url_index[o]
            self.out_neighbor.setdefault(si, []).append((pi, oi))
            self.in_neighbor.setdefault(oi, []).append((pi, si))

        self.index_type = {self.url_index[u]: t
                           for u, t in payload["entity_types"].items()}
        self.nodes = sorted(self.url_index[u] for u in payload["nodes"])
        self.query = self.url_index[payload["query"]]
        self.seeds = [self.url_index[u] for u in payload["seeds"]]

    def short(self, index: int) -> str:
        """dbr-style local name, for comparing against the PDF's row labels."""
        return self.index_url[index].strip("<>").rsplit("/", 1)[-1]

    def index_of(self, local_name: str) -> int:
        return self.url_index[f"<{DBR}{local_name}>"]


@pytest.fixture(scope="module")
def hanami() -> HanamiFixture:
    return HanamiFixture(json.loads(FIXTURE.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def kernel():
    return ad.load_kernel()


# --- Fixture integrity ----------------------------------------------------

def test_fixture_records_its_provenance(hanami):
    prov = hanami.payload["provenance"]
    assert prov["network_used"] is False
    assert prov["source_pickle_sha256"] == (
        "e230c5b95e20093631697624d9c46f30a14081b3f415d5027ffaf313bdbbea1b")
    assert prov["pdf_sha256"] == (
        "2aadbc087c14ba4d0e99b37f21589c953931f6b3286be35bd8293ce9ebd58804")


def test_fixture_has_the_published_structure(hanami):
    assert len(hanami.payload["nodes"]) == PDF_STRUCTURE["nodes"]
    assert len(hanami.payload["edges"]) == PDF_STRUCTURE["edges"]
    assert len(hanami.payload["edge_labels"]) == PDF_STRUCTURE["edge_labels"]


# --- HanamiSpots structure, rebuilt through the M1 graph builder -----------

def test_m1_builder_reproduces_thirteen_nodes_fifteen_edges_six_labels(hanami):
    """The PDF p. 1 gate, run through the module the pilot actually uses.

    min_candidates is 3 here because HanamiSpots has only three non-query seeds.
    This is the published structure check, not a pilot yield gate.
    """
    answer = hanami.index_of("Kamagatani")
    candidates = [c for c in hanami.seeds if c != answer]
    assert len(candidates) == 3

    m1 = gv.build_m1_graph(
        answer=answer, ordered_candidates=candidates,
        in_neighbor=hanami.in_neighbor, out_neighbor=hanami.out_neighbor,
        max_nodes=gv.DEFAULT_MAX_NODES, min_candidates=3)

    assert m1.is_ready
    assert m1.graph.node_count == PDF_STRUCTURE["nodes"]
    assert m1.graph.edge_count == PDF_STRUCTURE["edges"]
    assert m1.graph.edge_label_count == PDF_STRUCTURE["edge_labels"]
    assert tuple(m1.graph.nodes) == tuple(hanami.nodes)

    for record in m1.budget.candidate_records:
        assert record.accepted
        assert record.neighborhood_coverage_ratio == 1.0


# --- Fixed iteration count is exactly three -------------------------------

def test_kernel_fixed_path_runs_exactly_three_iterations(hanami, kernel):
    observed: list[int] = []
    kernel.lrolesim_fixed_iterations(
        0.2, hanami.nodes, hanami.in_neighbor, hanami.out_neighbor,
        measure="lrolesim_ed", iterations=3,
        on_iteration=lambda k, _: observed.append(k))

    assert observed == [1, 2, 3]


def test_adapter_reports_three_observed_iterations(hanami):
    run = ad.run_lrolesim_fixed(
        nodes=hanami.nodes, in_neighbor=hanami.in_neighbor,
        out_neighbor=hanami.out_neighbor, config=ad.pilot_config())

    assert run.iterations_run == 3
    assert run.iteration_mode == "fixed"
    assert run.config.iterations == 3
    assert run.as_record()["iterations_run"] == 3


def test_fixed_path_honours_a_different_iteration_count(hanami, kernel):
    """The count is a real parameter, not a constant that happens to be 3."""
    for n in (1, 2, 5):
        observed: list[int] = []
        kernel.lrolesim_fixed_iterations(
            0.2, hanami.nodes, hanami.in_neighbor, hanami.out_neighbor,
            measure="lrolesim_ed", iterations=n,
            on_iteration=lambda k, _: observed.append(k))
        assert observed == list(range(1, n + 1))


def test_fixed_path_never_stops_early_even_after_convergence(hanami, kernel):
    """L_ed on HanamiSpots is already stable at k = 2; k = 3 must still run 3."""
    observed: list[int] = []
    kernel.lrolesim_fixed_iterations(
        0.2, hanami.nodes, hanami.in_neighbor, hanami.out_neighbor,
        measure="lrolesim_ed", iterations=3,
        on_iteration=lambda k, _: observed.append(k))

    assert len(observed) == 3


def test_fixed_path_rejects_a_non_positive_or_non_integer_count(hanami, kernel):
    for bad in (0, -1):
        with pytest.raises(ValueError):
            kernel.lrolesim_fixed_iterations(
                0.2, hanami.nodes, hanami.in_neighbor, hanami.out_neighbor,
                iterations=bad)
    for bad in (3.0, True, "3"):
        with pytest.raises(TypeError):
            kernel.lrolesim_fixed_iterations(
                0.2, hanami.nodes, hanami.in_neighbor, hanami.out_neighbor,
                iterations=bad)


def test_adapter_rejects_an_invalid_iteration_count():
    with pytest.raises(ad.LRoleSimConfigError):
        ad.LRoleSimConfig(iterations=0)
    with pytest.raises(ad.LRoleSimConfigError):
        ad.LRoleSimConfig(iterations=2.5)


# --- The convergence path remains separately reachable ---------------------

def test_kernel_exposes_the_convergence_path_under_its_own_name(kernel):
    assert callable(kernel.lrolesim_until_convergence)
    assert callable(kernel.lrolesim_fixed_iterations)
    assert kernel.lrolesim_until_convergence is not kernel.lrolesim_fixed_iterations


def test_convergence_path_still_runs_and_stops_on_tolerance(hanami, kernel):
    sim = kernel.lrolesim_until_convergence(
        0.2, hanami.nodes, hanami.in_neighbor, hanami.out_neighbor,
        measure="lrolesim_ed", max_iter=20, tol=1e-4, verbose=False)

    q = hanami.index_of("Kamagatani")
    hino = hanami.index_of("Hinokinai_River_Embankment")
    # Reflexivity and the beta floor still hold on the converged matrix.
    assert sim[q, q] == pytest.approx(1.0, abs=PDF_TOLERANCE)
    assert PDF_BETA_FLOOR <= sim[q, hino] <= 1.0


def test_convergence_does_not_reproduce_the_published_value(hanami, kernel):
    """This is WHY the pilot pins k = 3 instead of running to a tolerance.

    Running L_ed to tol = 1e-4 on HanamiSpots keeps contracting past k = 3 and
    lands near 0.846, while the published "Final similarity" for Hinokinai River
    Embankment is 0.867. The two execution paths are therefore not
    interchangeable, and only the fixed-k path is comparable with the paper.
    """
    q = hanami.index_of("Kamagatani")
    hino = hanami.index_of("Hinokinai_River_Embankment")

    fixed = kernel.lrolesim_fixed_iterations(
        0.2, hanami.nodes, hanami.in_neighbor, hanami.out_neighbor,
        measure="lrolesim_ed", iterations=3)
    converged = kernel.lrolesim_until_convergence(
        0.2, hanami.nodes, hanami.in_neighbor, hanami.out_neighbor,
        measure="lrolesim_ed", max_iter=20, tol=1e-4, verbose=False)

    assert fixed[q, hino] == pytest.approx(0.867, abs=PDF_TOLERANCE)
    assert abs(converged[q, hino] - fixed[q, hino]) > PDF_TOLERANCE


def test_backward_compatible_lrolesim_delegates_to_convergence(hanami, kernel):
    """Existing callers of lrolesim() keep their old behaviour."""
    old = kernel.lrolesim(
        0.2, hanami.nodes, hanami.in_neighbor, hanami.out_neighbor,
        measure="lrolesim_ed", verbose=False)
    converged = kernel.lrolesim_until_convergence(
        0.2, hanami.nodes, hanami.in_neighbor, hanami.out_neighbor,
        measure="lrolesim_ed", verbose=False)

    assert old.dict == converged.dict


def test_adapter_convergence_ablation_is_a_separate_function(hanami):
    run = ad.run_lrolesim_until_convergence(
        nodes=hanami.nodes, in_neighbor=hanami.in_neighbor,
        out_neighbor=hanami.out_neighbor)

    assert run.iteration_mode == "convergence"
    assert run.iterations_run == -1                # not an observed fixed count


def test_pilot_config_is_not_the_convergence_path():
    assert ad.pilot_config().as_record()["iteration_mode"] == "fixed"


# --- beta = 0.2, and the two betas stay apart -----------------------------

def test_pilot_adapter_beta_is_zero_point_two():
    config = ad.pilot_config()
    assert config.lrolesim_beta == 0.2
    assert ad.PILOT_LROLESIM_BETA == 0.2
    assert config.as_record()["lrolesim_beta"] == 0.2


def test_pilot_config_matches_the_published_configuration():
    config = ad.pilot_config()
    assert config.measure == "lrolesim_ed"
    assert config.lrolesim_beta == 0.2
    assert config.iterations == 3
    assert config.is_pilot_primary is True


def test_config_does_not_expose_a_field_called_beta():
    config = ad.pilot_config()
    assert not hasattr(config, "beta")
    assert "beta" not in config.as_record()
    assert "lrolesim_beta" in config.as_record()


def test_passing_beta_as_a_keyword_is_refused(hanami):
    """The OverlapLoose weight must not be able to arrive as the decay factor."""
    for fn in (ad.run_lrolesim_fixed, ad.run_lrolesim_until_convergence):
        with pytest.raises(ad.LRoleSimConfigError, match="ambiguous"):
            fn(nodes=hanami.nodes, in_neighbor=hanami.in_neighbor,
               out_neighbor=hanami.out_neighbor, beta=0.9)

    with pytest.raises(ad.LRoleSimConfigError, match="ambiguous"):
        ad.rank_candidates(
            answer=hanami.query, candidates=[], nodes=hanami.nodes,
            in_neighbor=hanami.in_neighbor, out_neighbor=hanami.out_neighbor,
            beta=0.9)


def test_out_of_range_beta_is_rejected():
    for bad in (-0.1, 1.5):
        with pytest.raises(ad.LRoleSimConfigError, match="must lie in"):
            ad.LRoleSimConfig(lrolesim_beta=bad)


# --- L_ed primary, L_edt ablation -----------------------------------------

def test_l_ed_is_primary_and_l_edt_is_the_ablation():
    assert ad.PILOT_MEASURE == "lrolesim_ed"
    assert ad.ABLATION_MEASURE == "lrolesim_edt"
    assert ad.pilot_config().measure == "lrolesim_ed"
    assert ad.ablation_config().measure == "lrolesim_edt"
    assert ad.ablation_config().is_pilot_primary is False


def test_both_measures_exist_in_the_kernel_registry(kernel):
    assert "lrolesim_ed" in kernel.MEASURES
    assert "lrolesim_edt" in kernel.MEASURES


def test_unknown_measure_is_rejected():
    with pytest.raises(ad.LRoleSimConfigError, match="unknown measure"):
        ad.LRoleSimConfig(measure="lrolesim_nonexistent")


def test_ablation_requires_entity_types(hanami):
    """Without a type map, L_edt silently becomes L_ed — refuse instead."""
    with pytest.raises(ad.LRoleSimConfigError, match="entity-type map"):
        ad.run_lrolesim_fixed(
            nodes=hanami.nodes, in_neighbor=hanami.in_neighbor,
            out_neighbor=hanami.out_neighbor, config=ad.ablation_config())


def test_ablation_runs_when_entity_types_are_supplied(hanami):
    run = ad.run_lrolesim_fixed(
        nodes=hanami.nodes, in_neighbor=hanami.in_neighbor,
        out_neighbor=hanami.out_neighbor, config=ad.ablation_config(),
        index_type=hanami.index_type)

    assert run.iterations_run == 3
    assert run.config.measure == "lrolesim_edt"


# --- HanamiSpots regression against the PDF -------------------------------

def _final_scores(hanami, config, index_type=None):
    run = ad.run_lrolesim_fixed(
        nodes=hanami.nodes, in_neighbor=hanami.in_neighbor,
        out_neighbor=hanami.out_neighbor, config=config, index_type=index_type)
    q = hanami.index_of("Kamagatani")
    return {hanami.short(j): run.score(q, j) for j in hanami.nodes}


def test_l_ed_final_similarities_match_the_pdf(hanami):
    scores = _final_scores(hanami, ad.pilot_config())

    assert len(scores) == PDF_STRUCTURE["nodes"]
    for name, score in scores.items():
        expected = PDF_FINAL_L_ED.get(name, PDF_BETA_FLOOR)
        assert score == pytest.approx(expected, abs=PDF_TOLERANCE), name


def test_l_edt_final_similarities_match_the_pdf(hanami):
    scores = _final_scores(hanami, ad.ablation_config(),
                           index_type=hanami.index_type)

    assert len(scores) == PDF_STRUCTURE["nodes"]
    for name, score in scores.items():
        expected = PDF_FINAL_L_EDT.get(name, PDF_BETA_FLOOR)
        assert score == pytest.approx(expected, abs=PDF_TOLERANCE), name


def test_l_ed_and_l_edt_differ_on_hinokinai(hanami):
    """The ablation must actually be a different measurement, not a relabelling."""
    ed = _final_scores(hanami, ad.pilot_config())
    edt = _final_scores(hanami, ad.ablation_config(), index_type=hanami.index_type)

    assert ed["Hinokinai_River_Embankment"] == pytest.approx(0.867, abs=PDF_TOLERANCE)
    assert edt["Hinokinai_River_Embankment"] == pytest.approx(0.600, abs=PDF_TOLERANCE)


def test_kernel_expected_fixture_agrees_with_the_pdf(kernel):
    """The kernel's committed HANAMI_EXPECTED_FINAL must not drift from the PDF."""
    ed = kernel.HANAMI_EXPECTED_FINAL["lrolesim_ed"]
    assert ed["dbr:Kamagatani"] == pytest.approx(1.000, abs=PDF_TOLERANCE)
    assert ed["dbr:Hinokinai_River_Embankment"] == pytest.approx(
        0.867, abs=PDF_TOLERANCE)

    edt = kernel.HANAMI_EXPECTED_FINAL["lrolesim_edt"]
    assert edt["dbr:Kamagatani"] == pytest.approx(1.000, abs=PDF_TOLERANCE)
    assert edt["dbr:Hinokinai_River_Embankment"] == pytest.approx(
        0.600, abs=PDF_TOLERANCE)


# --- Ranking ---------------------------------------------------------------

def test_ranking_orders_hinokinai_first_and_flags_the_beta_floor(hanami):
    answer = hanami.index_of("Kamagatani")
    candidates = [c for c in hanami.seeds if c != answer]

    result = ad.rank_candidates(
        answer=answer, candidates=candidates, nodes=hanami.nodes,
        in_neighbor=hanami.in_neighbor, out_neighbor=hanami.out_neighbor,
        index_url=hanami.index_url)

    assert hanami.short(result.ordered_candidates[0]) == "Hinokinai_River_Embankment"
    assert result.scores[0].score == pytest.approx(0.867, abs=PDF_TOLERANCE)
    assert result.scores[0].at_beta_floor is False
    # The other two seeds sit exactly on the beta floor, as in the published table.
    assert result.beta_floor_count == 2
    assert [s.rank for s in result.scores] == [1, 2, 3]


def test_ranking_excludes_the_answer_itself(hanami):
    answer = hanami.index_of("Kamagatani")
    result = ad.rank_candidates(
        answer=answer, candidates=[answer] + hanami.seeds, nodes=hanami.nodes,
        in_neighbor=hanami.in_neighbor, out_neighbor=hanami.out_neighbor,
        index_url=hanami.index_url)

    assert answer not in result.ordered_candidates


def test_tie_breaking_is_by_uri_and_is_deterministic(hanami):
    answer = hanami.index_of("Kamagatani")
    candidates = [c for c in hanami.nodes if c != answer]

    runs = [
        ad.rank_candidates(
            answer=answer, candidates=list(reversed(candidates)) if flip
            else candidates,
            nodes=hanami.nodes, in_neighbor=hanami.in_neighbor,
            out_neighbor=hanami.out_neighbor, index_url=hanami.index_url)
        for flip in (False, True)
    ]
    assert runs[0].ordered_candidates == runs[1].ordered_candidates

    # Among the floor-tied candidates the order is ascending URI.
    tied = [hanami.index_url[s.candidate] for s in runs[0].scores if s.at_beta_floor]
    assert tied == sorted(tied)


def test_rank_m1_graph_refuses_an_insufficient_graph(hanami):
    answer = hanami.index_of("Kamagatani")
    candidates = [c for c in hanami.seeds if c != answer]

    m1 = gv.build_m1_graph(
        answer=answer, ordered_candidates=candidates,
        in_neighbor=hanami.in_neighbor, out_neighbor=hanami.out_neighbor)

    assert m1.status == gv.GRAPH_BUDGET_INSUFFICIENT_CANDIDATES   # only 3 < 10
    with pytest.raises(ad.LRoleSimConfigError, match="not rankable"):
        ad.rank_m1_graph(m1)


def test_rank_m1_graph_ranks_a_ready_graph(hanami):
    answer = hanami.index_of("Kamagatani")
    candidates = [c for c in hanami.seeds if c != answer]

    m1 = gv.build_m1_graph(
        answer=answer, ordered_candidates=candidates,
        in_neighbor=hanami.in_neighbor, out_neighbor=hanami.out_neighbor,
        min_candidates=3)
    result = ad.rank_m1_graph(m1, index_url=hanami.index_url)

    assert result.run.iterations_run == 3
    assert result.run.node_count == PDF_STRUCTURE["nodes"]
    assert hanami.short(result.ordered_candidates[0]) == "Hinokinai_River_Embankment"


def test_ranking_record_is_serialisable(hanami):
    answer = hanami.index_of("Kamagatani")
    candidates = [c for c in hanami.seeds if c != answer]
    result = ad.rank_candidates(
        answer=answer, candidates=candidates, nodes=hanami.nodes,
        in_neighbor=hanami.in_neighbor, out_neighbor=hanami.out_neighbor,
        index_url=hanami.index_url)

    record = result.as_record()
    assert json.loads(json.dumps(record))["run"]["iterations_run"] == 3
    assert record["run"]["measure"] == "lrolesim_ed"
    assert record["run"]["lrolesim_beta"] == 0.2


# --- The archived Journal 1 source is untouched ----------------------------

def test_journal1_archive_has_no_fixed_iteration_api():
    """The patch went to the v2 file only; Journal 1's source stays immutable."""
    archived = (SRC_DIR / "MCQ_lrolesim.py").read_text(encoding="utf-8")
    assert "lrolesim_fixed_iterations" not in archived
    assert "lrolesim_until_convergence" not in archived


def test_adapter_binds_to_the_v2_kernel(kernel):
    assert pathlib.Path(kernel.__file__).name == "MCQ_lrolesim_ClaudeWeb_v2.py"
