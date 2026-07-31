############################################################################
# tests/test_selection_lrolesim_handoff.py
#
# Contract tests for the Prompt-8D extract integration:
#   src/selection/contracts.py
#   src/selection/observed_facts.py
#   src/selection/lrolesim_handoff.py
#   src/selection/legacy_overlap.py
#   src/extract_221_and_select_distractors_ClaudeWeb_v2.py
#
# WHAT THESE TESTS DEFEND
#   * every one of the 204 primary Prompt-8C ranks is REPRODUCED, not recomputed;
#   * the 27 provisional top-3 rows (24 primary + 3 diagnostic) come back
#     unchanged, and none of them is ever called a final distractor;
#   * the six Sulfuric-acid diagnostic ranks stay out of every primary count;
#   * nine primary summary rows, with Sulfuric acid still the one primary failure;
#   * class and graph fingerprint agree across every frozen file;
#   * context nodes never become candidate distractors, and no Answer ranks itself;
#   * ranks are contiguous and ties break on ascending canonical URI;
#   * the proposed mode makes zero HTTP/SPARQL calls and never imports spaCy,
#     sentence-transformers, the SPARQL layer, the class-selection layer or the
#     legacy overlap baseline;
#   * the legacy mode is explicit — an omitted or misspelled mode is an error;
#   * extended_edgeset()'s cache respects KG identity AND use_in (AUDIT EX-4);
#   * IN facts name their counterpart correctly (AUDIT EX-12);
#   * observed-fact serialization is deterministic and fabricates no negative fact;
#   * the frozen Prompt-8B/8C sources are byte-identical.
#
# OFFLINE
#   No network. The 1.2 GB pinned pickle is never loaded: the end-to-end tests run
#   the REAL frozen Prompt-8C records against a SYNTHETIC miniature KG built in
#   tmp_path that carries exactly the local indices those records name.
#
# Run:
#     python -m pytest -vv tests/test_selection_lrolesim_handoff.py
############################################################################

from __future__ import annotations

import csv
import json
import pickle
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

FROZEN_DIR = REPO_ROOT / "outputs" / "journal2_week2_graph_lrolesim_pilot_2026-07-30"

import extract_221_and_select_distractors_ClaudeWeb_v2 as extract   # noqa: E402
from selection.contracts import (                                    # noqa: E402
    DIRECTION_IN,
    DIRECTION_OUT,
    PILOT_ITERATIONS,
    PILOT_LROLESIM_BETA,
    PILOT_MEASURE,
    RANKER_LEGACY_OVERLAP_BASELINE,
    RANKER_LROLESIM_M1_FIXED_K3,
    ObservedFact,
    RankedCandidate,
    SelectionContractError,
    sort_observed_facts,
)
from selection.lrolesim_handoff import (                             # noqa: E402
    ContractInconsistencyError,
    HandoffError,
    LRoleSimHandoffRanker,
    build_diagnostic_handoff,
    build_primary_handoffs,
    load_prompt8c_outputs,
    validate_prompt8c_contract,
)
from selection.observed_facts import (                               # noqa: E402
    DIRECTION_CODE_IN,
    DIRECTION_CODE_OUT,
    EdgeSetCache,
    observed_edge_set,
    observed_facts_for_node,
    serialize_owner_fact_sets,
)

pytestmark = pytest.mark.skipif(
    not FROZEN_DIR.is_dir(),
    reason=f"frozen Prompt-8C outputs not present at {FROZEN_DIR}",
)


# ==========================================================================
# FIXTURES
# ==========================================================================

@pytest.fixture(scope="module")
def frozen_inputs():
    return load_prompt8c_outputs(FROZEN_DIR)


@pytest.fixture(scope="module")
def ranker(frozen_inputs):
    return LRoleSimHandoffRanker(frozen_inputs)


@pytest.fixture(scope="module")
def frozen_ranking_rows():
    with open(FROZEN_DIR / "lrolesim_rankings.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def frozen_top3_rows():
    with open(FROZEN_DIR / "provisional_top3.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _synthetic_kg_path(tmp_path: Path) -> Path:
    """A miniature pickle carrying exactly the local indices the frozen records name.

    Every Answer and every ranked candidate gets a small, DISTINCT one-hop
    neighbourhood, so observed-fact serialization is exercised for real without
    the 1.2 GB dump. Node indices are the REAL ones, because the handoff reads
    them straight out of the frozen records.
    """
    inputs = load_prompt8c_outputs(FROZEN_DIR)

    index_url: dict[int, str] = {}
    for row in inputs.policy_summary:
        index_url[int(row["answer_local_index"])] = f"<{row['answer_uri']}>"
    for manifest in inputs.manifests:
        index_url[int(manifest["answer_local_index"])] = f"<{manifest['answer_uri']}>"
    for row in inputs.rankings:
        index_url[int(row["candidate_local_index"])] = f"<{row['candidate_uri']}>"

    # Synthetic predicates and counterpart nodes, in an index range the real
    # records never use.
    base = max(index_url) + 1
    predicates = [base + i for i in range(3)]
    for offset, p in enumerate(predicates):
        index_url[p] = f"<http://dbpedia.org/property/synthetic{offset}>"
    counterparts = [base + 10 + i for i in range(5)]
    for offset, c in enumerate(counterparts):
        index_url[c] = f"<http://dbpedia.org/resource/Synthetic_object_{offset}>"

    out_neighbor: dict[int, list[tuple[int, int]]] = {}
    in_neighbor: dict[int, list[tuple[int, int]]] = {}
    entities = sorted(n for n in index_url
                      if n not in predicates and n not in counterparts)
    for position, node in enumerate(entities):
        out_edges = [(predicates[position % 3], counterparts[position % 5]),
                     (predicates[(position + 1) % 3], counterparts[(position + 2) % 5])]
        in_edges = [(predicates[(position + 2) % 3], counterparts[(position + 1) % 5])]
        out_neighbor[node] = out_edges
        in_neighbor[node] = in_edges
        for p, o in out_edges:
            in_neighbor.setdefault(o, []).append((p, node))
        for p, s in in_edges:
            out_neighbor.setdefault(s, []).append((p, node))

    url_index = {uri: idx for idx, uri in index_url.items()}
    index_type = {idx: 0 for idx in index_url}

    path = tmp_path / "synthetic_local_kg.pickle_EnglishVersion_EntityType"
    with open(path, "wb") as f:
        pickle.dump((url_index, index_url, out_neighbor, in_neighbor, index_type), f)
    return path


@pytest.fixture(scope="module")
def synthetic_kg(tmp_path_factory):
    return _synthetic_kg_path(tmp_path_factory.mktemp("synthetic_kg"))


@pytest.fixture(scope="module")
def pilot_run(synthetic_kg):
    return extract.run_pilot_lrolesim_handoff(
        prompt8c_dir=FROZEN_DIR,
        local_kg_path=synthetic_kg,
        verify_local_kg_sha256=None,
        verbose=False,
    )


@pytest.fixture(scope="module")
def written_outputs(pilot_run, tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("prompt8d_outputs")
    extract.write_all_outputs(pilot_run, out_dir, raw_command=["pytest"])
    return out_dir


class _TinyKG:
    """A minimal duck-typed KG for the cache and direction tests."""

    def __init__(self, index_url, out_neighbor, in_neighbor, sha256=None):
        self.index_url = index_url
        self.url_index = {v: k for k, v in index_url.items()}
        self.out_neighbor = out_neighbor
        self.in_neighbor = in_neighbor
        if sha256 is not None:
            self.source_sha256 = sha256

    def uri(self, index):
        return self.index_url[index]


# ==========================================================================
# 1) EXACT REPRODUCTION OF THE PROMPT-8C RANKS
# ==========================================================================

def test_all_204_primary_ranks_are_reproduced_exactly(ranker, frozen_ranking_rows):
    """Every primary rank, score, tie group and origin comes back unchanged."""
    frozen_primary = [r for r in frozen_ranking_rows
                      if r["primary_or_diagnostic"] == "primary"]
    assert len(frozen_primary) == 204

    reproduced = 0
    for answer_uri in ranker.graph_feasible_primary_answer_uris():
        ranking = ranker.ranking_for_answer(answer_uri)
        expected = sorted(
            (r for r in frozen_primary if r["answer_uri"] == answer_uri),
            key=lambda r: int(r["rank"]))
        assert len(expected) == ranking.ranked_candidate_count
        for row, candidate in zip(expected, ranking.ranked):
            assert candidate.rank == int(row["rank"])
            assert candidate.canonical_candidate_uri == row["candidate_uri"]
            assert candidate.candidate_local_index == int(row["candidate_local_index"])
            # repr equality, not a tolerance: the score must round-trip exactly.
            assert repr(candidate.score) == repr(float(row["lrolesim_score"]))
            assert candidate.tie_group_id == int(row["tie_group_id"])
            assert candidate.tie_group_size == int(row["tie_group_size"])
            assert candidate.at_beta_floor == (row["at_beta_floor"] == "true")
            assert candidate.candidate_origin == row["candidate_origin"]
            assert candidate.graph_admission_position == int(
                row["graph_admission_position"])
            reproduced += 1
    assert reproduced == 204


def test_six_sulfuric_diagnostic_ranks_are_isolated(ranker, frozen_ranking_rows):
    """The diagnostic ranks exist, reproduce, and enter no primary total."""
    frozen_diagnostic = [r for r in frozen_ranking_rows
                         if r["primary_or_diagnostic"] == "diagnostic"]
    assert len(frozen_diagnostic) == 6

    diagnostic = ranker.diagnostic_ranking_for_answer(
        "http://dbpedia.org/resource/Sulfuric_acid")
    assert diagnostic.ranked_candidate_count == 6
    assert diagnostic.diagnostic_only is True
    assert diagnostic.excluded_from_primary_policy_metrics is True

    for row, candidate in zip(sorted(frozen_diagnostic, key=lambda r: int(r["rank"])),
                              diagnostic.ranked):
        assert candidate.canonical_candidate_uri == row["candidate_uri"]
        assert repr(candidate.score) == repr(float(row["lrolesim_score"]))

    # The primary path must not see it at all.
    with pytest.raises(HandoffError):
        ranker.ranking_for_answer("http://dbpedia.org/resource/Sulfuric_acid")

    primary_total = sum(
        ranker.ranking_for_answer(uri).ranked_candidate_count
        for uri in ranker.graph_feasible_primary_answer_uris())
    assert primary_total == 204


def test_all_27_provisional_top3_rows_are_reproduced(written_outputs, frozen_top3_rows):
    """24 primary + 3 diagnostic rows, in the same order and with the same values.

    NOTE ON THE COUNT. Prompt 8D's section 10 says "27 provisional primary top-3
    rows". The frozen file holds 27 rows in total: 24 PRIMARY (eight graph-feasible
    Answers times three) plus 3 DIAGNOSTIC. This test pins both the total and the
    split, so the diagnostic three can never be silently counted as primary.
    """
    assert len(frozen_top3_rows) == 27
    assert sum(1 for r in frozen_top3_rows
               if r["primary_or_diagnostic"] == "primary") == 24
    assert sum(1 for r in frozen_top3_rows
               if r["primary_or_diagnostic"] == "diagnostic") == 3

    with open(written_outputs / "provisional_top3_handoff.csv",
              encoding="utf-8", newline="") as f:
        produced = list(csv.DictReader(f))
    assert len(produced) == 27

    shared = ("primary_or_diagnostic", "pilot_slot", "answer_uri",
              "selected_class_uri", "rank", "candidate_uri",
              "candidate_local_index", "lrolesim_score", "tie_group_id",
              "tie_group_size", "at_beta_floor", "is_final_distractor",
              "measure", "lrolesim_beta", "iterations", "graph_fingerprint")
    for expected, actual in zip(frozen_top3_rows, produced):
        for field in shared:
            assert actual[field] == expected[field], field


def test_no_provisional_record_claims_to_be_a_final_distractor(written_outputs):
    with open(written_outputs / "provisional_top3_handoff.csv",
              encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            assert row["is_final_distractor"] == "false"
            assert row["rationale_selection_status"] == (
                "RATIONALE_SELECTION_DEFERRED_TO_PROMPT_8E")

    with open(written_outputs / "candidate_ranking_handoff.jsonl",
              encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            assert record["rationale_selection_status"] == (
                "RATIONALE_SELECTION_DEFERRED_TO_PROMPT_8E")
            for candidate in record["ranked_candidates"]:
                assert candidate["is_final_distractor"] is False
            for candidate in record["provisional_lrolesim_top3"]:
                assert candidate["is_final_distractor"] is False


# ==========================================================================
# 2) POLICY SHAPE AND THE SULFURIC-ACID FAILURE
# ==========================================================================

def test_nine_primary_summary_rows_eight_ready(written_outputs):
    with open(written_outputs / "extract_integration_summary.csv",
              encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 9
    assert all(r["primary_or_diagnostic"] == "primary" for r in rows)
    assert sum(1 for r in rows if r["ready_for_rationale_selection"] == "true") == 8
    assert sum(int(r["ranked_candidate_count"]) for r in rows) == 204
    assert all(r["any_final_distractor_selected"] == "false" for r in rows)
    assert all(r["ranker_name"] == RANKER_LROLESIM_M1_FIXED_K3 for r in rows)


def test_sulfuric_acid_remains_the_one_primary_failure(written_outputs):
    with open(written_outputs / "extract_integration_summary.csv",
              encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    failures = [r for r in rows if r["ready_for_rationale_selection"] == "false"]
    assert len(failures) == 1
    sulfuric = failures[0]
    assert sulfuric["answer_uri"] == "http://dbpedia.org/resource/Sulfuric_acid"
    assert sulfuric["mapping_stage_status"] == "NO_MAPPING_FEASIBLE_APPROVED_CLASS"
    assert sulfuric["graph_stage_status"] == "NO_GRAPH_FEASIBLE_APPROVED_CLASS"
    assert sulfuric["ranked_candidate_count"] == "0"
    assert sulfuric["selected_class_uri"] == ""
    assert sulfuric["graph_fingerprint"] == ""


def test_diagnostic_is_not_mixed_into_primary_counts(written_outputs):
    payload = json.loads(
        (written_outputs / "sulfuric_acid_diagnostic_handoff.json").read_text())
    assert payload["diagnostic_only"] is True
    assert payload["excluded_from_primary_policy_metrics"] is True
    assert payload["diagnostic_handoff"]["ranked_candidate_count"] == 6
    assert payload["diagnostic_handoff"]["primary_or_diagnostic"] == "diagnostic"
    assert payload["primary_record"]["graph_stage_status"] == (
        "NO_GRAPH_FEASIBLE_APPROVED_CLASS")
    for key, value in payload["boundaries"].items():
        assert value is False, key

    # The diagnostic facts live in their own namespace file.
    with open(written_outputs / "observed_candidate_facts.jsonl", encoding="utf-8") as f:
        for line in f:
            assert json.loads(line)["primary_or_diagnostic"] == "primary"
    with open(written_outputs / "observed_diagnostic_facts.jsonl", encoding="utf-8") as f:
        diagnostic_facts = [json.loads(line) for line in f]
    assert diagnostic_facts
    assert all(r["primary_or_diagnostic"] == "diagnostic" for r in diagnostic_facts)


# ==========================================================================
# 3) CROSS-FILE AGREEMENT AND ORDER INVARIANTS
# ==========================================================================

def test_class_and_fingerprint_agree_across_every_frozen_file(frozen_inputs):
    report = validate_prompt8c_contract(frozen_inputs)
    assert report.all_passed
    names = {name for name, _passed, _detail in report.checks}
    assert "selected_class_agrees_across_files" in names
    assert "graph_fingerprint_agrees_across_files" in names
    assert report.primary_answer_count == 9
    assert report.graph_feasible_primary_count == 8
    assert report.primary_ranked_candidate_count == 204
    assert report.diagnostic_ranked_candidate_count == 6


def test_measure_beta_and_iterations_are_the_frozen_pilot_path(ranker):
    for answer_uri in ranker.graph_feasible_primary_answer_uris():
        ranking = ranker.ranking_for_answer(answer_uri)
        assert ranking.measure == PILOT_MEASURE == "lrolesim_ed"
        assert ranking.lrolesim_beta == PILOT_LROLESIM_BETA == 0.2
        assert ranking.iterations == PILOT_ITERATIONS == 3
        assert ranking.iteration_mode == "fixed"


def test_context_nodes_never_become_candidate_distractors(frozen_inputs, ranker):
    """A ranked candidate is always an accepted candidate, never a context node."""
    for manifest in frozen_inputs.manifests:
        accepted = set(manifest["accepted_candidate_uris"])
        # Context nodes are, by definition, the graph nodes that are neither the
        # Answer nor an accepted candidate.
        assert manifest["node_count"] == (
            1 + manifest["accepted_candidate_count"] + manifest["context_node_count"])
        assert manifest["context_node_count"] > 0
        scope = manifest["primary_or_diagnostic"]
        ranked = {r["candidate_uri"] for r in frozen_inputs.rankings
                  if r["answer_uri"] == manifest["answer_uri"]
                  and r["primary_or_diagnostic"] == scope}
        assert ranked == accepted
        assert manifest["answer_uri"] not in ranked

    for candidate in frozen_inputs.candidates:
        assert candidate["is_context_node_only"] is False


def test_answer_never_ranks_itself(ranker):
    for answer_uri in ranker.graph_feasible_primary_answer_uris():
        ranking = ranker.ranking_for_answer(answer_uri)
        assert answer_uri not in ranking.candidate_uris()


def test_ranks_are_contiguous(ranker):
    for answer_uri in ranker.graph_feasible_primary_answer_uris():
        ranking = ranker.ranking_for_answer(answer_uri)
        assert [c.rank for c in ranking.ranked] == list(
            range(1, ranking.ranked_candidate_count + 1))


def test_ties_break_on_ascending_canonical_uri(ranker):
    """Where scores tie, URIs ascend — and the pilot really does contain ties."""
    tied_groups_seen = 0
    for answer_uri in ranker.graph_feasible_primary_answer_uris():
        ranking = ranker.ranking_for_answer(answer_uri)
        for earlier, later in zip(ranking.ranked, ranking.ranked[1:]):
            assert later.score <= earlier.score
            if later.score == earlier.score:
                tied_groups_seen += 1
                assert earlier.canonical_candidate_uri < later.canonical_candidate_uri
                assert earlier.tie_group_id == later.tie_group_id
    assert tied_groups_seen > 0, "the pilot is expected to contain tied scores"


def test_contract_violation_raises_rather_than_being_repaired(frozen_inputs):
    """A ranking that ascends must be refused, not silently reordered."""
    broken = list(frozen_inputs.rankings)
    for position, row in enumerate(broken):
        if row["primary_or_diagnostic"] == "primary" and row["rank"] == "2":
            mutated = dict(row)
            mutated["lrolesim_score"] = "9.0"
            broken[position] = mutated
            break
    mutated_inputs = type(frozen_inputs)(
        **{**vars(frozen_inputs), "rankings": tuple(broken)})
    with pytest.raises(ContractInconsistencyError):
        validate_prompt8c_contract(mutated_inputs)


def test_ranked_candidate_rejects_a_bracketed_uri():
    with pytest.raises(SelectionContractError):
        RankedCandidate(rank=1, canonical_candidate_uri="<http://x/A>",
                        candidate_local_index=1, score=0.5, tie_group_id=1,
                        tie_group_size=1)


# ==========================================================================
# 4) MODE DISCIPLINE
# ==========================================================================

def test_mode_is_mandatory_and_never_silently_legacy():
    parser = extract.build_arg_parser()
    with pytest.raises(SystemExit):        # argparse: --mode is required
        parser.parse_args([])
    with pytest.raises(SystemExit):        # argparse: not a valid choice
        parser.parse_args(["--mode", "legacy_overlap"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--mode", "pilot"])

    assert parser.parse_args(["--mode", extract.MODE_PILOT_LROLESIM_HANDOFF]).mode == (
        extract.MODE_PILOT_LROLESIM_HANDOFF)
    assert parser.parse_args(["--mode", extract.MODE_LEGACY_OVERLAP]).mode == (
        extract.MODE_LEGACY_OVERLAP)


def test_dispatch_refuses_an_unknown_mode():
    args = extract.build_arg_parser().parse_args(
        ["--mode", extract.MODE_PILOT_LROLESIM_HANDOFF])
    with pytest.raises(extract.UnknownModeError):
        extract.dispatch("legacy", args)
    with pytest.raises(extract.UnknownModeError):
        extract.dispatch("", args)


def test_cli_rejects_an_omitted_mode_at_the_process_level():
    result = subprocess.run(
        [sys.executable, str(SRC_DIR / "extract_221_and_select_distractors_ClaudeWeb_v2.py")],
        capture_output=True, text=True, cwd=REPO_ROOT)
    assert result.returncode != 0
    assert "--mode" in result.stderr
    assert RANKER_LEGACY_OVERLAP_BASELINE not in result.stdout


def test_the_two_rankers_are_distinct_named_implementations():
    from selection import legacy_overlap

    assert extract.RANKER_FOR_MODE[extract.MODE_PILOT_LROLESIM_HANDOFF] == (
        "lrolesim_m1_fixed_k3")
    assert extract.RANKER_FOR_MODE[extract.MODE_LEGACY_OVERLAP] == (
        "legacy_overlap_baseline")
    assert LRoleSimHandoffRanker.name != legacy_overlap.LegacyOverlapRanker.name


def test_legacy_ranker_refuses_to_be_constructed_as_the_proposed_method():
    from selection import legacy_overlap

    with pytest.raises(legacy_overlap.LegacyBaselineMisuseError):
        legacy_overlap.LegacyOverlapRanker(kg=None)


def test_legacy_entry_points_warn_when_reached_from_new_code():
    from selection import legacy_overlap

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(legacy_overlap.LegacyBaselineMisuseError):
            legacy_overlap.LegacyOverlapRanker(kg=None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _ = extract.distinguishing_facts
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


# ==========================================================================
# 5) THE PROPOSED MODE TOUCHES NOTHING IT MUST NOT
# ==========================================================================

_PURITY_PROBE = r"""
import json, sys
sys.path.insert(0, {src!r})
import extract_221_and_select_distractors_ClaudeWeb_v2 as extract
run = extract.run_pilot_lrolesim_handoff(
    prompt8c_dir={frozen!r}, local_kg_path={kg!r},
    verify_local_kg_sha256=None, verbose=False)
extract.write_all_outputs(run, {out!r})
print("PROBE" + json.dumps({{
    "modules": sorted(sys.modules),
    "guard": run.guard_record,
    "primary": len(run.primary_handoffs),
    "ranked_total": run.primary_ranked_total,
}}))
"""


@pytest.fixture(scope="module")
def purity_probe(synthetic_kg, tmp_path_factory):
    """Run the proposed mode in a FRESH interpreter and report what it imported.

    A subprocess is the only honest way to ask this: this test module itself
    imports the baseline for other tests, so an in-process sys.modules check would
    be measuring the test suite rather than the proposed path.
    """
    out_dir = tmp_path_factory.mktemp("purity")
    script = _PURITY_PROBE.format(
        src=str(SRC_DIR), frozen=str(FROZEN_DIR), kg=str(synthetic_kg),
        out=str(out_dir / "outputs"))
    result = subprocess.run([sys.executable, "-c", script],
                            capture_output=True, text=True, cwd=REPO_ROOT)
    assert result.returncode == 0, result.stderr
    line = next(l for l in result.stdout.splitlines() if l.startswith("PROBE"))
    return json.loads(line[len("PROBE"):])


def test_proposed_mode_performs_zero_http_and_sparql_calls(purity_probe):
    guard = purity_probe["guard"]
    assert guard["network_attempts"] == 0
    assert guard["http_calls"] == 0
    assert guard["sparql_calls"] == 0
    assert guard["attempted_addresses"] == []
    assert "SPARQLWrapper" not in purity_probe["modules"]
    assert "category_extractor_ClaudeWeb_v2" not in purity_probe["modules"]


def test_proposed_mode_does_not_initialize_spacy_sbert_or_abstractstore(purity_probe):
    modules = purity_probe["modules"]
    assert "spacy" not in modules
    assert "sentence_transformers" not in modules
    # AbstractStore lives in selection.legacy_overlap; not importing the module is
    # a strictly stronger statement than not constructing the class.
    assert "selection.legacy_overlap" not in modules


def test_proposed_mode_does_not_call_class_selection(purity_probe):
    """The class-selection layer is never even imported.

    The selected class of every Answer is READ from the frozen Prompt-8C records.
    Re-running selection here could pick a different class and invalidate every
    frozen graph fingerprint.
    """
    assert "classes.policy" not in purity_probe["modules"]
    assert "classes.member_mapper" not in purity_probe["modules"]
    assert "classes.sparql_client" not in purity_probe["modules"]


def test_proposed_mode_never_calls_legacy_overlap_or_the_one_fact_filter(
        synthetic_kg, tmp_path):
    """Sentinels on every legacy entry point stay untriggered through a full run."""
    from selection import legacy_overlap

    calls: list[str] = []

    def sentinel(name):
        def _fail(*args, **kwargs):
            calls.append(name)
            raise AssertionError(
                f"the proposed path called the legacy baseline function {name}")
        return _fail

    originals = {}
    for name in ("rank_candidates", "select_distractor_set",
                 "legacy_single_fact_common_filter", "overlap_strict",
                 "overlap_loose", "build_choices", "get_candidates_for_class"):
        originals[name] = getattr(legacy_overlap, name)
        setattr(legacy_overlap, name, sentinel(name))
    try:
        run = extract.run_pilot_lrolesim_handoff(
            prompt8c_dir=FROZEN_DIR, local_kg_path=synthetic_kg,
            verify_local_kg_sha256=None, verbose=False)
        extract.write_all_outputs(run, tmp_path / "out")
    finally:
        for name, original in originals.items():
            setattr(legacy_overlap, name, original)

    assert calls == []
    assert run.ranker_name == RANKER_LROLESIM_M1_FIXED_K3
    assert run.primary_ranked_total == 204


def test_probe_reproduces_the_pilot_shape(purity_probe):
    assert purity_probe["primary"] == 9
    assert purity_probe["ranked_total"] == 204


# ==========================================================================
# 6) THE CORRECTED EDGE-SET CACHE  (AUDIT item EX-4)
# ==========================================================================

def _tiny_kg(sha256=None):
    index_url = {1: "<http://x/A>", 2: "<http://x/B>", 3: "<http://x/p>"}
    out_neighbor = {1: [(3, 2)]}
    in_neighbor = {2: [(3, 1)], 1: [(3, 2)]}
    return _TinyKG(index_url, out_neighbor, in_neighbor, sha256=sha256)


def test_edgeset_cache_distinguishes_use_in_true_from_false():
    """AUDIT test T2.1: the two ablations must not share a cache entry."""
    kg = _tiny_kg(sha256="a" * 64)
    cache = EdgeSetCache()

    without_in = observed_edge_set(1, kg, use_in=False, cache=cache)
    with_in = observed_edge_set(1, kg, use_in=True, cache=cache)

    assert without_in == frozenset({(3, DIRECTION_CODE_OUT, 2)})
    assert with_in == frozenset({(3, DIRECTION_CODE_OUT, 2),
                                 (3, DIRECTION_CODE_IN, 2)})
    assert without_in != with_in

    # Order must not matter either: recompute in the opposite order.
    reverse_cache = EdgeSetCache()
    assert observed_edge_set(1, kg, use_in=True, cache=reverse_cache) == with_in
    assert observed_edge_set(1, kg, use_in=False, cache=reverse_cache) == without_in


def test_edgeset_cache_distinguishes_two_kgs_in_one_process():
    """A second KG must not inherit the first KG's edges for the same index."""
    first = _tiny_kg(sha256="a" * 64)
    second = _TinyKG(
        index_url={1: "<http://x/A>", 9: "<http://x/Z>", 3: "<http://x/p>"},
        out_neighbor={1: [(3, 9)]}, in_neighbor={}, sha256="b" * 64)
    cache = EdgeSetCache()

    assert observed_edge_set(1, first, use_in=False, cache=cache) == frozenset(
        {(3, DIRECTION_CODE_OUT, 2)})
    assert observed_edge_set(1, second, use_in=False, cache=cache) == frozenset(
        {(3, DIRECTION_CODE_OUT, 9)})


def test_edgeset_cache_separates_kgs_without_a_sha256():
    """The object-identity fallback is still a separation, not a collision."""
    first = _tiny_kg()
    second = _TinyKG(index_url={1: "<http://x/A>", 9: "<http://x/Z>",
                               3: "<http://x/p>"},
                     out_neighbor={1: [(3, 9)]}, in_neighbor={})
    cache = EdgeSetCache()
    assert cache.identity_for(first) != cache.identity_for(second)
    assert observed_edge_set(1, first, use_in=False, cache=cache) != (
        observed_edge_set(1, second, use_in=False, cache=cache))


def test_cache_key_includes_kg_identity_node_use_in_and_schema_version():
    from selection.observed_facts import FACT_SCHEMA_VERSION, EdgeSetCacheKey

    key = EdgeSetCacheKey(kg_identity="sha256:x", node_index=7, use_in=True)
    assert key.fact_schema_version == FACT_SCHEMA_VERSION
    assert key != EdgeSetCacheKey(kg_identity="sha256:x", node_index=7, use_in=False)
    assert key != EdgeSetCacheKey(kg_identity="sha256:y", node_index=7, use_in=True)
    assert key != EdgeSetCacheKey(kg_identity="sha256:x", node_index=8, use_in=True)


def test_extract_extended_edgeset_uses_the_corrected_cache():
    kg = _tiny_kg(sha256="c" * 64)
    without_in = extract.extended_edgeset(1, kg, use_in=False)
    with_in = extract.extended_edgeset(1, kg, use_in=True)
    assert without_in != with_in
    assert len(with_in) == 2


# ==========================================================================
# 7) DIRECTION SEMANTICS  (AUDIT item EX-12)
# ==========================================================================

def test_in_and_out_facts_name_their_counterpart_correctly():
    kg = _tiny_kg(sha256="d" * 64)
    facts = observed_facts_for_node(1, kg, graph_fingerprint="fp",
                                    cache=EdgeSetCache()).facts
    by_direction = {f.direction: f for f in facts}
    assert set(by_direction) == {DIRECTION_OUT, DIRECTION_IN}

    out_fact = by_direction[DIRECTION_OUT]
    assert out_fact.owner_uri == "http://x/A"
    assert out_fact.counterpart_uri == "http://x/B"
    assert out_fact.subject_uri == "http://x/A"
    assert out_fact.object_uri == "http://x/B"

    in_fact = by_direction[DIRECTION_IN]
    # The owner is the OBJECT of an IN triple; the counterpart is the SUBJECT.
    assert in_fact.owner_uri == "http://x/A"
    assert in_fact.counterpart_uri == "http://x/B"
    assert in_fact.subject_uri == "http://x/B"
    assert in_fact.object_uri == "http://x/A"

    for fact in facts:
        assert "object" not in fact.as_record()
        assert "counterpart_uri" in fact.as_record()


def test_observed_fact_records_never_carry_an_unconditional_object_field(
        written_outputs):
    for name in ("observed_answer_facts.jsonl", "observed_candidate_facts.jsonl",
                 "observed_diagnostic_facts.jsonl"):
        with open(written_outputs / name, encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                assert "object" not in record
                assert "subject" not in record
                assert record["direction"] in (DIRECTION_OUT, DIRECTION_IN)
                assert record["counterpart_uri"]


def test_legacy_serializer_also_uses_counterpart_naming():
    from selection import legacy_overlap

    kg = _tiny_kg(sha256="e" * 64)
    records = legacy_overlap.observed_fact_records(
        [(3, DIRECTION_CODE_IN, 2), (3, DIRECTION_CODE_OUT, 2)], kg)
    assert {r["direction"] for r in records} == {DIRECTION_IN, DIRECTION_OUT}
    assert all("object" not in r for r in records)
    assert all(r["counterpart_uri"] == "<http://x/B>" for r in records)


# ==========================================================================
# 8) OBSERVED FACTS: DETERMINISM, PROVENANCE, NO NEGATIVES
# ==========================================================================

def test_observed_fact_serialization_is_deterministic_and_sorted(written_outputs):
    for name in ("observed_answer_facts.jsonl", "observed_candidate_facts.jsonl",
                 "observed_diagnostic_facts.jsonl"):
        with open(written_outputs / name, encoding="utf-8") as f:
            records = [json.loads(line) for line in f]
        keys = [(r["owner_uri"], r["direction"], r["predicate_uri"],
                 r["counterpart_uri"], r["graph_fingerprint"]) for r in records]
        assert keys == sorted(keys), f"{name} is not sorted by the frozen key"
        assert len(keys) == len(set(keys)), f"{name} contains duplicate facts"


def test_a_shared_candidate_keeps_one_row_per_graph_it_serves(written_outputs):
    """131 distinct nodes cover 204 (Answer, candidate) pairs; none loses provenance.

    Aristotle and Plato share a class, as do the three Japanese laureates, so a
    candidate can legitimately serve several Answers. Each of those links must
    survive with its own graph fingerprint rather than collapsing onto one.
    """
    with open(written_outputs / "observed_candidate_facts.jsonl", encoding="utf-8") as f:
        records = [json.loads(line) for line in f]

    fingerprints_by_owner: dict[str, set] = {}
    for record in records:
        fingerprints_by_owner.setdefault(record["owner_uri"], set()).add(
            record["graph_fingerprint"])
    shared = {owner: fps for owner, fps in fingerprints_by_owner.items()
              if len(fps) > 1}
    assert shared, "the pilot is expected to contain candidates shared by Answers"

    # For a shared owner, every fingerprint carries the SAME observed facts: the
    # facts are a property of the node in the pinned KG, not of the graph.
    for owner, fingerprints in shared.items():
        per_fingerprint = {}
        for fingerprint in fingerprints:
            per_fingerprint[fingerprint] = {
                (r["direction"], r["predicate_uri"], r["counterpart_uri"])
                for r in records
                if r["owner_uri"] == owner and r["graph_fingerprint"] == fingerprint}
        assert len(set(map(frozenset, per_fingerprint.values()))) == 1, owner


def test_observed_facts_are_provenance_linked_to_graph_fingerprints(
        written_outputs, ranker):
    fingerprints = {
        ranker.ranking_for_answer(uri).graph_fingerprint
        for uri in ranker.graph_feasible_primary_answer_uris()}
    for name in ("observed_answer_facts.jsonl", "observed_candidate_facts.jsonl"):
        with open(written_outputs / name, encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                assert record["graph_fingerprint"] in fingerprints
                assert record["primary_or_diagnostic"] == "primary"


def test_every_serialized_fact_is_observed_in_the_kg_and_none_is_negative(
        pilot_run, synthetic_kg):
    """No fabricated fact and no negative fact.

    Each record is matched back to a real edge in the pinned KG, and the schema is
    checked to have no field that could express falsity. Absence is never recorded.
    """
    with open(synthetic_kg, "rb") as f:
        url_index, index_url, out_neighbor, in_neighbor, _ = pickle.load(f)

    forbidden = {"absent", "negative", "not_present", "is_false", "missing",
                 "does_not_have", "negated"}
    checked = 0
    for fact_set in (*pilot_run.answer_fact_sets, *pilot_run.candidate_fact_sets,
                     *pilot_run.diagnostic_fact_sets):
        for fact in fact_set.facts:
            record = fact.as_record()
            assert not (set(record) & forbidden)
            assert all(value is not None for value in record.values())
            if fact.direction == DIRECTION_OUT:
                assert (fact.counterpart_local_index in
                        [o for _p, o in out_neighbor.get(fact.owner_local_index, ())])
            else:
                assert (fact.counterpart_local_index in
                        [s for _p, s in in_neighbor.get(fact.owner_local_index, ())])
            checked += 1
    assert checked > 0


def test_observed_facts_cover_every_answer_and_ranked_candidate(pilot_run):
    assert len(pilot_run.answer_fact_sets) == 8
    assert len(pilot_run.candidate_fact_sets) == 204
    # The Sulfuric-acid Answer plus its six diagnostic candidates.
    assert len(pilot_run.diagnostic_fact_sets) == 7
    assert all(fs.owner_role == "answer" for fs in pilot_run.answer_fact_sets)
    assert all(fs.owner_role == "candidate" for fs in pilot_run.candidate_fact_sets)
    assert all(fs.unresolved_counterpart_count == 0
               for fs in pilot_run.answer_fact_sets)


def test_sort_observed_facts_deduplicates_and_totally_orders():
    def fact(owner, direction, predicate, counterpart):
        return ObservedFact(owner_uri=owner, owner_local_index=1,
                            predicate_uri=predicate, direction=direction,
                            counterpart_uri=counterpart, counterpart_local_index=2,
                            graph_fingerprint="fp")

    a = fact("http://x/A", DIRECTION_OUT, "http://x/p", "http://x/B")
    duplicate = fact("http://x/A", DIRECTION_OUT, "http://x/p", "http://x/B")
    b = fact("http://x/A", DIRECTION_IN, "http://x/p", "http://x/B")
    ordered = sort_observed_facts([a, b, duplicate])
    assert len(ordered) == 2
    # "IN" sorts before "OUT" on the frozen key.
    assert [f.direction for f in ordered] == [DIRECTION_IN, DIRECTION_OUT]


def test_observed_fact_rejects_an_unknown_direction():
    with pytest.raises(SelectionContractError):
        ObservedFact(owner_uri="http://x/A", owner_local_index=1,
                     predicate_uri="http://x/p", direction="BOTH",
                     counterpart_uri="http://x/B", counterpart_local_index=2,
                     graph_fingerprint="fp")


# ==========================================================================
# 9) FROZEN SOURCES AND STRICT OFFLINE REPLAY
# ==========================================================================

def test_protected_prompt8c_sources_are_byte_identical():
    observed = extract.verify_protected_sources()
    assert set(observed) == {"candidate_order", "graph_lrolesim_run", "graph_view",
                             "lrolesim_adapter", "lrolesim_kernel"}
    for name, record in observed.items():
        assert record["unmodified"] is True, name
        assert record["observed_sha256"] == record["expected_sha256"], name


def test_a_second_run_reproduces_every_output_byte_for_byte(
        synthetic_kg, tmp_path, written_outputs):
    """Strict offline replay: same inputs, same bytes."""
    replay = extract.run_pilot_lrolesim_handoff(
        prompt8c_dir=FROZEN_DIR, local_kg_path=synthetic_kg,
        verify_local_kg_sha256=None, verbose=False)
    replay_dir = tmp_path / "replay"
    extract.write_all_outputs(replay, replay_dir)

    for name in extract.REPLAY_COMPARED_FILES:
        original = (written_outputs / name).read_bytes()
        reproduced = (replay_dir / name).read_bytes()
        assert original == reproduced, f"{name} is not byte-identical on replay"


def test_offline_replay_manifest_records_zero_network(written_outputs):
    payload = json.loads(
        (written_outputs / "offline_replay_manifest.json").read_text())
    assert payload["http_calls"] == 0
    assert payload["sparql_calls"] == 0
    assert payload["network"]["network_attempts"] == 0
    assert set(payload["byte_identical_files"]) == set(extract.REPLAY_COMPARED_FILES)
    for name, record in payload["protected_sources"].items():
        assert record["unmodified"] is True, name


def test_run_manifest_states_the_scope_and_makes_no_final_claim(written_outputs):
    payload = json.loads((written_outputs / "run_manifest.json").read_text())
    assert payload["ranker_name"] == RANKER_LROLESIM_M1_FIXED_K3
    assert payload["counts"]["final_distractors_selected"] == 0
    assert payload["counts"]["rationales_generated"] == 0
    assert payload["counts"]["primary_answer_denominator"] == 9
    assert payload["counts"]["primary_ready_for_rationale_selection"] == 8
    assert payload["counts"]["primary_ranked_candidate_total"] == 204
    assert payload["counts"]["diagnostic_ranked_candidate_total"] == 6
    assert "RATIONALE_SELECTION_DEFERRED_TO_PROMPT_8E" in payload["scope_note"]
    assert "never recorded as evidence that the triple is false" in (
        payload["open_world_note"])
