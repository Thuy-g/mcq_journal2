############################################################################
# tests/test_run_category_selector_v6.py
#
# Tests for scripts/run_category_selector_v6.py — the v6 command-line driver.
#
# NO TEST HERE TOUCHES THE NETWORK OR LOADS A MODEL. The network gate itself is
# tested by asserting that the process refuses BEFORE any live client is built.
############################################################################

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
SCRIPTS_DIR = REPO_ROOT / "scripts"
for directory in (SRC_DIR, SCRIPTS_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import category_extractor_v6 as v6  # noqa: E402
import run_category_selector_v6 as runner_module  # noqa: E402
from classes import wikipedia_lead as wl  # noqa: E402

RESOURCE = "http://dbpedia.org/resource/"
CATEGORY = RESOURCE + "Category:"


def read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))


# ---------------------------------------------------------------------------
# 1) Import purity and the network gate
# ---------------------------------------------------------------------------


def test_importing_the_runner_creates_no_file_and_issues_no_query(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import importlib
    sys.modules.pop("run_category_selector_v6", None)
    importlib.import_module("run_category_selector_v6")
    assert list(tmp_path.iterdir()) == []


def test_no_live_call_is_possible_without_allow_network(tmp_path, monkeypatch, capsys):
    """The gate must fire BEFORE any client, model or Wikipedia session exists."""
    def explode(*args, **kwargs):
        raise AssertionError("a live component was built before the network gate")

    monkeypatch.setattr(runner_module, "make_dbpedia_runner", explode)
    monkeypatch.setattr(runner_module, "SbertEncoder", explode)
    monkeypatch.setattr(runner_module, "RequestsWikipediaTransport", explode)
    monkeypatch.setattr(runner_module, "build_run_context", explode)

    code = runner_module.main(["--answer-uri", RESOURCE + "Albert_Einstein"])
    assert code == runner_module.EXIT_NETWORK_DENIED
    assert "Network access is denied by default" in capsys.readouterr().err


def test_answer_uri_and_input_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit):
        runner_module.build_parser().parse_args(
            ["--answer-uri", "x", "--input", str(tmp_path / "a.txt")])


def test_one_of_answer_uri_or_input_is_required():
    with pytest.raises(SystemExit):
        runner_module.build_parser().parse_args([])


def test_alpha_and_alphas_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        runner_module.build_parser().parse_args(
            ["--answer-uri", "x", "--alpha", "0.5", "--alphas", "0,1"])


def test_alpha_defaults_to_the_pre_specified_working_configuration():
    args = runner_module.build_parser().parse_args(["--answer-uri", "x"])
    assert args.alpha is None          # unset on the namespace...
    assert v6.DEFAULT_ALPHA == 0.7     # ...and resolved to the pre-specified 0.7
    # The help text a user reads must not contradict the value main() applies.
    help_text = runner_module.build_parser().format_help()
    assert "0.7" in help_text
    assert "neutral equal" not in help_text


def test_an_invalid_alpha_is_rejected_before_any_work(capsys, monkeypatch):
    monkeypatch.setattr(runner_module, "build_run_context", lambda a: (_ for _ in ()).throw(
        AssertionError("must not reach the run")))
    assert runner_module.main(["--answer-uri", "x", "--alpha", "1.5"]) \
        == runner_module.EXIT_USAGE
    assert "alpha" in capsys.readouterr().err


def test_parse_alpha_list_validates_every_value():
    assert runner_module.parse_alpha_list("0,0.25,0.5,0.7,0.75,1") == \
        [0.0, 0.25, 0.5, 0.7, 0.75, 1.0]
    with pytest.raises(ValueError):
        runner_module.parse_alpha_list("0,2")
    with pytest.raises(ValueError):
        runner_module.parse_alpha_list("")


# ---------------------------------------------------------------------------
# 2) Answers.txt parsing
# ---------------------------------------------------------------------------


SAMPLE = """#COHORT: Japanese_Nobel_laureates:
http://dbpedia.org/resource/Shinya_Yamanaka
http://dbpedia.org/resource/Hideki_Yukawa

#COMMENT: http://dbpedia.org/resource/Sin-Itiro_Tomonaga
# a plain comment line
#COHORT: WORLD HISTORY:
http://dbpedia.org/resource/Shinya_Yamanaka
http://dbpedia.org/resource/Julius_Caesar
"""


def write_sample(tmp_path: Path, text: str = SAMPLE) -> Path:
    path = tmp_path / "Answers.txt"
    path.write_text(text, encoding="utf-8")
    return path


def test_cohort_headers_set_the_cohort_of_following_rows(tmp_path):
    parsed = runner_module.parse_answers_file(write_sample(tmp_path))
    assert [r.cohort for r in parsed.rows] == [
        "Japanese_Nobel_laureates", "Japanese_Nobel_laureates",
        "WORLD HISTORY", "WORLD HISTORY"]
    assert parsed.cohort_order == ["Japanese_Nobel_laureates", "WORLD HISTORY"]


def test_comments_and_blanks_are_ignored_as_answers(tmp_path):
    parsed = runner_module.parse_answers_file(write_sample(tmp_path))
    assert parsed.answer_row_count == 4
    assert parsed.blank_lines == 1
    # A #COMMENT: line contains a URI and is still NOT an Answer.
    assert all("Tomonaga" not in r.answer_uri for r in parsed.rows)
    assert len(parsed.other_comment_lines) == 1


def test_a_malformed_row_is_reported_not_silently_dropped(tmp_path):
    path = write_sample(tmp_path, SAMPLE + "this is not a uri at all\n")
    parsed = runner_module.parse_answers_file(path)
    assert len(parsed.malformed_rows) == 1
    assert parsed.malformed_rows[0][1] == "this is not a uri at all"
    assert parsed.audit()["malformed_rows"][0]["line_number"] == 10


def test_a_row_with_the_prefix_but_an_invalid_iri_is_reported_and_excluded(tmp_path):
    """data/Answers.txt line 182 really is ``...Magnesium_oxide"``.

    It satisfies the §N grammar (it starts with the resource prefix) but is not
    a valid IRI, so it cannot be interpolated into a SPARQL query. It must be
    counted as an Answer row for the audit AND excluded from the run.
    """
    bad = RESOURCE + 'Magnesium_oxide"'
    parsed = runner_module.parse_answers_file(
        write_sample(tmp_path, SAMPLE + bad + "\n"))
    assert parsed.answer_row_count == 5
    assert len(parsed.invalid_uri_rows) == 1
    assert bad not in parsed.unique_uris
    assert parsed.audit()["runnable_unique_answer_uris"] == 3
    assert parsed.audit()["unique_answer_uris"] == 4


def test_first_occurrence_wins_but_every_duplicate_is_retained(tmp_path):
    parsed = runner_module.parse_answers_file(write_sample(tmp_path))
    yamanaka = RESOURCE + "Shinya_Yamanaka"
    assert parsed.unique_uris.count(yamanaka) == 1
    assert parsed.unique_uris[0] == yamanaka
    occurrences = [r for r in parsed.rows if r.answer_uri == yamanaka]
    assert len(occurrences) == 2
    assert [r.is_duplicate for r in occurrences] == [False, True]
    assert parsed.duplicate_row_count == 1


def test_cross_cohort_duplicate_provenance_is_preserved(tmp_path):
    parsed = runner_module.parse_answers_file(write_sample(tmp_path))
    assert parsed.cohorts_by_uri[RESOURCE + "Shinya_Yamanaka"] == \
        ["Japanese_Nobel_laureates", "WORLD HISTORY"]


def test_the_repository_answers_file_matches_the_researcher_audit():
    """Measured, not assumed: 347 Answer rows / 329 unique / 18 duplicate rows.

    RE-MEASURED 2026-08-17. The researcher edited `data/Answers.txt` after
    commit c1928a7: four Answer rows were removed and the one row that satisfied
    the grammar without being a valid IRI (`...Magnesium_oxide"`, a stray double
    quote) was corrected. The previous frozen expectation — 351 / 333 / 18 with
    one unqueryable row — therefore failed on an unmodified checkout, and the
    numbers below are what the current file actually contains.

    `data/Answers.txt` is the researcher's input dataset and is untracked in git,
    so this assertion is a CONSISTENCY CHECK between the parser and the file on
    disk, not a claim that the corpus may not change. It is written as exact
    equalities on purpose: a silently shrinking denominator makes every coverage
    percentage computed from this corpus wrong, and a failing test is how that
    change announces itself.
    """
    parsed = runner_module.parse_answers_file(REPO_ROOT / "data" / "Answers.txt")
    audit = parsed.audit()
    assert audit["answer_uri_rows"] == 347
    assert audit["unique_answer_uris"] == 329
    assert audit["duplicate_answer_rows"] == 18
    assert audit["malformed_rows"] == []
    # Every row is now a queryable IRI, so runnable == unique.
    assert audit["invalid_uri_rows"] == []
    assert audit["runnable_unique_answer_uris"] == 329
    assert audit["cohort_header_lines"] == 13


# ---------------------------------------------------------------------------
# 3) End-to-end batch behaviour with a fake endpoint
# ---------------------------------------------------------------------------


class FakeClient:
    """A tiny fake endpoint: two categories per Answer, deterministic counts."""

    endpoint = "https://fake.example/sparql"

    def __init__(self):
        self.queries = []

    def run(self, query):
        qid = v6.query_id(query)
        self.queries.append(qid)
        if qid == "answer_info":
            return self._ok([{"label": {"value": "Fake Label"},
                              "description": {"value": "a short gloss"}}])
        if qid == "answer_categories":
            return self._ok([{"cat": {"value": CATEGORY + "Alpha_class"}},
                             {"cat": {"value": CATEGORY + "Beta_class"}}])
        if qid == "category_counts":
            return self._ok([
                {"cat": {"value": CATEGORY + "Alpha_class"}, "c": {"value": "40"}},
                {"cat": {"value": CATEGORY + "Beta_class"}, "c": {"value": "400"}}])
        if qid == "idf_universe_unfiltered":
            return self._ok([{"N": {"value": "6721370"}}])
        if qid == "idf_universe_category_filtered":
            return v6.QueryResult(status=v6.QueryStatus.PARTIAL,
                                  rows=({"N": {"value": "3099179"}},),
                                  endpoint=self.endpoint, sql_state="S1TAT")
        return self._ok([])

    def _ok(self, rows):
        rows = tuple(rows)
        return v6.QueryResult(
            status=v6.QueryStatus.OK if rows else v6.QueryStatus.ZERO_RESULTS,
            rows=rows, endpoint=self.endpoint)


class FakeEncoder:
    name = "fake-encoder"
    max_seq_length = 32

    def __init__(self):
        self.batches = []

    def encode(self, texts):
        self.batches.append(list(texts))
        return [[1.0 + t.lower().count("a"), 1.0 + t.lower().count("e")]
                for t in texts]


def install_fakes(monkeypatch, *, encoder=None, leads=None):
    """Replace every live component with an offline double.

    The Wikipedia client is replaced by one whose transport would raise, so a
    test that accidentally reached the network would fail loudly.
    """
    client = FakeClient()
    encoder = encoder if encoder is not None else FakeEncoder()

    def fake_context(args):
        sparql_runner = v6.SparqlRunner(client=client,
                                        cache=v6.InMemorySparqlCache())
        universe = v6.resolve_idf_universe(
            sparql_runner, explicit_total=args.total_entities)

        class FrozenLeadClient:
            def fetch_many(self, uris):
                return {u: (leads or {}).get(u, wl.WikipediaLead(
                    answer_uri=u, requested_title="T", status=wl.LeadStatus.OK,
                    canonical_title="T", page_id=1, revision_id=7,
                    revision_timestamp="2026-01-01T00:00:00Z",
                    lead_text="An example lead about a researcher.",
                    lead_sha256="deadbeef", character_length=35,
                    sentence_count=1)) for u in uris}

            def stats(self):
                return {"api_requests": 0, "cache_hits": len(uris_seen), "cache_misses": 0}

        uris_seen: list[str] = []
        return runner_module.RunContext(
            runner=sparql_runner, universe=universe, encoder=encoder,
            lead_client=FrozenLeadClient(), lead_cache=None,
            semantic_source=v6.SemanticSource(args.semantic_source),
            policy=v6.load_r1_leakage_policy())

    monkeypatch.setattr(runner_module, "build_run_context", fake_context)
    return client, encoder


def test_a_batch_run_writes_every_declared_single_alpha_artifact(tmp_path, monkeypatch):
    install_fakes(monkeypatch)
    out = tmp_path / "out"
    code = runner_module.main([
        "--input", str(write_sample(tmp_path)), "--alpha", "0.5",
        "--output-dir", str(out), "--allow-network"])
    assert code == runner_module.EXIT_OK
    for name in ("answers_parsed.csv", "duplicate_answers.csv",
                 "semantic_text_coverage.csv", "answer_summary.csv",
                 "class_rankings_all.csv", "rejected_classes.csv",
                 "run_manifest.json", "idf_universe_provenance.json",
                 "answers_input_audit.json", "malformed_rows.csv"):
        assert (out / name).is_file(), name


def test_a_sweep_run_writes_every_declared_sweep_artifact(tmp_path, monkeypatch):
    install_fakes(monkeypatch)
    out = tmp_path / "out"
    code = runner_module.main([
        "--input", str(write_sample(tmp_path)), "--alphas", "0,0.25,0.5,0.7,0.75,1",
        "--output-dir", str(out), "--allow-network"])
    assert code == runner_module.EXIT_OK
    for name in ("alpha_sweep_top1.csv", "alpha_sweep_topk.csv",
                 "alpha_sweep_all_rankings.csv", "alpha_rank_stability.csv",
                 "semantic_text_coverage.csv", "alpha_sweep_manifest.json"):
        assert (out / name).is_file(), name


def test_a_six_alpha_sweep_costs_the_same_traffic_as_one_alpha(tmp_path, monkeypatch):
    """The whole point of §L: the sweep must not multiply endpoint traffic."""
    single_client, single_encoder = install_fakes(monkeypatch)
    runner_module.main([
        "--input", str(write_sample(tmp_path)), "--alpha", "0.5",
        "--output-dir", str(tmp_path / "one"), "--allow-network"])
    single_queries = len(single_client.queries)
    single_encodes = len(single_encoder.batches)

    sweep_client, sweep_encoder = install_fakes(monkeypatch)
    runner_module.main([
        "--input", str(write_sample(tmp_path)), "--alphas", "0,0.25,0.5,0.7,0.75,1",
        "--output-dir", str(tmp_path / "six"), "--allow-network"])
    assert len(sweep_client.queries) == single_queries
    assert len(sweep_encoder.batches) == single_encodes


def test_the_sweep_reuses_identical_raw_features_across_alphas(tmp_path, monkeypatch):
    install_fakes(monkeypatch)
    out = tmp_path / "out"
    runner_module.main([
        "--input", str(write_sample(tmp_path)), "--alphas", "0,0.5,1",
        "--output-dir", str(out), "--allow-network"])
    rows = read_csv(out / "alpha_sweep_all_rankings.csv")
    features: dict[tuple[str, str], set[tuple[str, str, str]]] = {}
    for row in rows:
        key = (row["answer_uri"], row["category_uri"])
        features.setdefault(key, set()).add(
            (row["raw_idf"], row["raw_sbert"], row["remote_count"]))
    assert all(len(v) == 1 for v in features.values()), \
        "a raw feature changed between alphas"


def test_cohort_metadata_never_changes_the_ranking(tmp_path, monkeypatch):
    """Same Answers, different cohort labels, byte-identical rankings.

    If a cohort string could reach the ranker, the selector would stop being
    generic for an arbitrary DBpedia Answer.
    """
    body = ("http://dbpedia.org/resource/Shinya_Yamanaka\n"
            "http://dbpedia.org/resource/Hideki_Yukawa\n")
    first = tmp_path / "a.txt"
    first.write_text("#COHORT: ALPHA COHORT:\n" + body, encoding="utf-8")
    second = tmp_path / "b.txt"
    second.write_text("#COHORT: A COMPLETELY DIFFERENT LABEL:\n" + body,
                      encoding="utf-8")

    outputs = []
    for source, name in ((first, "one"), (second, "two")):
        install_fakes(monkeypatch)
        out = tmp_path / name
        runner_module.main(["--input", str(source), "--alpha", "0.5",
                            "--output-dir", str(out), "--allow-network"])
        rows = read_csv(out / "class_rankings_all.csv")
        outputs.append([{k: v for k, v in row.items() if k != "cohort"}
                        for row in rows])
    assert outputs[0] == outputs[1]


def test_rejected_classes_are_written_without_any_rank_column(tmp_path, monkeypatch):
    install_fakes(monkeypatch)
    out = tmp_path / "out"
    runner_module.main(["--input", str(write_sample(tmp_path)), "--alpha", "0.5",
                        "--output-dir", str(out), "--allow-network"])
    header = (out / "rejected_classes.csv").read_text(
        encoding="utf-8").splitlines()[0]
    assert "rank" not in header.lower()
    ranking_header = (out / "class_rankings_all.csv").read_text(
        encoding="utf-8").splitlines()[0]
    assert "feasible_rank" in ranking_header


def test_a_batch_replayed_from_cache_is_byte_identical(tmp_path, monkeypatch):
    """Two runs over identical frozen observations must produce identical
    scientific bytes; only the manifest carries a timestamp."""
    outputs = []
    for name in ("first", "second"):
        install_fakes(monkeypatch)
        out = tmp_path / name
        runner_module.main([
            "--input", str(write_sample(tmp_path)), "--alphas", "0,0.5,1",
            "--output-dir", str(out), "--allow-network"])
        outputs.append(out)
    scientific = ["alpha_sweep_all_rankings.csv", "alpha_sweep_top1.csv",
                  "alpha_sweep_topk.csv", "alpha_rank_stability.csv",
                  "answer_summary.csv", "rejected_classes.csv",
                  "semantic_text_coverage.csv", "answers_parsed.csv",
                  "duplicate_answers.csv", "idf_universe_provenance.json"]
    for name in scientific:
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes(), \
            f"{name} is not reproducible"


def test_the_manifest_records_the_idf_universe_and_the_r1_policy(tmp_path, monkeypatch):
    install_fakes(monkeypatch)
    out = tmp_path / "out"
    runner_module.main(["--input", str(write_sample(tmp_path)), "--alpha", "0.5",
                        "--output-dir", str(out), "--allow-network"])
    manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["idf_universe"]["total_entities"] == 6721370
    assert manifest["idf_universe"]["universe_definition"] == \
        v6.UNIVERSE_UNFILTERED_UPPER_BOUND
    assert len(manifest["r1_policy_sha256"]) == 64
    assert manifest["alphas"] == [0.5]
    assert manifest["input_audit"]["answer_uri_rows"] == 4


def test_an_explicit_total_entities_override_is_used_and_costs_no_query(
        tmp_path, monkeypatch):
    client, _ = install_fakes(monkeypatch)
    out = tmp_path / "out"
    runner_module.main(["--input", str(write_sample(tmp_path)), "--alpha", "0.5",
                        "--output-dir", str(out), "--total-entities", "6000000",
                        "--allow-network"])
    manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["idf_universe"]["total_entities"] == 6000000
    assert manifest["idf_universe"]["universe_definition"] == v6.UNIVERSE_EXPLICIT
    assert not any(q and q.startswith("idf_universe") for q in client.queries)


def test_the_idf_universe_is_queried_once_for_a_whole_batch(tmp_path, monkeypatch):
    client, _ = install_fakes(monkeypatch)
    runner_module.main(["--input", str(write_sample(tmp_path)), "--alpha", "0.5",
                        "--output-dir", str(tmp_path / "out"), "--allow-network"])
    universe_queries = [q for q in client.queries
                        if q and q.startswith("idf_universe")]
    # Exactly one filtered attempt plus one unfiltered fallback, for the RUN,
    # not per Answer.
    assert universe_queries == ["idf_universe_category_filtered",
                                "idf_universe_unfiltered"]


def test_a_run_refuses_to_score_when_no_idf_universe_exists(tmp_path, monkeypatch, capsys):
    class NoUniverseClient(FakeClient):
        def run(self, query):
            if v6.query_id(query) in ("idf_universe_unfiltered",
                                      "idf_universe_category_filtered"):
                self.queries.append(v6.query_id(query))
                return v6.QueryResult(status=v6.QueryStatus.FAILED,
                                      error="down", endpoint=self.endpoint)
            return super().run(query)

    def fake_context(args):
        sparql_runner = v6.SparqlRunner(client=NoUniverseClient(),
                                        cache=v6.InMemorySparqlCache())
        return runner_module.RunContext(
            runner=sparql_runner,
            universe=v6.resolve_idf_universe(sparql_runner,
                                             explicit_total=args.total_entities),
            encoder=None, lead_client=None, lead_cache=None,
            semantic_source=v6.SemanticSource(args.semantic_source),
            policy=v6.load_r1_leakage_policy())

    monkeypatch.setattr(runner_module, "build_run_context", fake_context)
    code = runner_module.main(["--input", str(write_sample(tmp_path)),
                               "--output-dir", str(tmp_path / "out"),
                               "--allow-network"])
    assert code == runner_module.EXIT_NO_IDF_UNIVERSE
    error = capsys.readouterr().err
    assert "No value was invented" in error
    assert "6000000" not in error and "6685753" not in error


def test_missing_semantic_text_is_reported_and_never_scored_as_zero(
        tmp_path, monkeypatch):
    missing = {
        RESOURCE + "Shinya_Yamanaka": wl.WikipediaLead(
            answer_uri=RESOURCE + "Shinya_Yamanaka", requested_title="T",
            status=wl.LeadStatus.PAGE_MISSING)}
    install_fakes(monkeypatch, leads=missing)
    out = tmp_path / "out"
    runner_module.main(["--input", str(write_sample(tmp_path)), "--alpha", "0.7",
                        "--output-dir", str(out), "--allow-network"])
    rows = [r for r in read_csv(out / "class_rankings_all.csv")
            if r["answer_uri"].endswith("Shinya_Yamanaka")]
    assert rows
    for row in rows:
        assert row["semantic_status"] == v6.SemanticStatus.UNAVAILABLE.value
        assert row["scoring_mode"] == \
            v6.ScoringMode.IDF_ONLY_SEMANTIC_UNAVAILABLE.value
        assert row["raw_sbert"] == ""       # absent, not "0.0000000000"
        assert row["normalized_sbert"] == ""

    coverage = {r["answer_uri"]: r
                for r in read_csv(out / "semantic_text_coverage.csv")}
    yamanaka = coverage[RESOURCE + "Shinya_Yamanaka"]
    assert yamanaka["wikipedia_lead_available"] == "false"
    assert yamanaka["wikipedia_lead_status"] == wl.LeadStatus.PAGE_MISSING.value


def test_alpha_zero_and_alpha_one_produce_the_declared_endpoint_rankings(
        tmp_path, monkeypatch):
    install_fakes(monkeypatch)
    out = tmp_path / "out"
    runner_module.main(["--input", str(write_sample(tmp_path)), "--alphas", "0,1",
                        "--output-dir", str(out), "--allow-network"])
    rows = read_csv(out / "alpha_sweep_all_rankings.csv")
    by_alpha: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if row["answer_uri"].endswith("Julius_Caesar"):
            by_alpha.setdefault(row["alpha"], []).append(row)
    idf_rows = sorted(by_alpha["0.0000000000"], key=lambda r: int(r["feasible_rank"]))
    idf_values = [float(r["raw_idf"]) for r in idf_rows]
    assert idf_values == sorted(idf_values, reverse=True)
    sbert_rows = sorted(by_alpha["1.0000000000"], key=lambda r: int(r["feasible_rank"]))
    sbert_values = [float(r["raw_sbert"]) for r in sbert_rows]
    assert sbert_values == sorted(sbert_values, reverse=True)
    assert {r["scoring_mode"] for r in idf_rows} == \
        {v6.ScoringMode.IDF_ONLY_BY_ALPHA.value}


def test_the_pilot_diagnostic_is_read_only_and_leaves_the_policy_untouched(
        tmp_path, monkeypatch):
    policy_path = REPO_ROOT / "data" / "pilot_class_policy_v1.json"
    before = policy_path.read_bytes()
    install_fakes(monkeypatch)
    out = tmp_path / "out"
    runner_module.main(["--input", str(write_sample(tmp_path)), "--alphas", "0,1",
                        "--output-dir", str(out), "--allow-network"])
    assert policy_path.read_bytes() == before
    rows = read_csv(out / "pilot9_alpha_diagnostic.csv")
    # Nine pilot Answers at each of two alphas.
    assert len(rows) == 18
    assert {r["alpha"] for r in rows} == {"0.0000000000", "1.0000000000"}


def test_spearman_rho_is_none_for_a_degenerate_comparison():
    assert runner_module.spearman_rho([1], [1]) is None
    assert runner_module.spearman_rho([1, 2], [1, 2]) == pytest.approx(1.0)
    assert runner_module.spearman_rho([1, 2], [2, 1]) == pytest.approx(-1.0)
    assert runner_module.spearman_rho([1, 1], [1, 2]) is None


def test_a_single_answer_run_prints_the_complete_ranking(tmp_path, monkeypatch, capsys):
    install_fakes(monkeypatch)
    code = runner_module.main(["--answer-uri", RESOURCE + "Shinya_Yamanaka",
                               "--alpha", "0.5", "--allow-network"])
    assert code == runner_module.EXIT_OK
    out = capsys.readouterr().out
    assert "COMPLETE FEASIBLE RANKING (2 classes)" in out
    assert "Alpha class" in out and "Beta class" in out
    assert "N used for IDF" in out
    assert "not claimed to be globally optimal" in out
    assert "REJECTED CLASSES" in out
