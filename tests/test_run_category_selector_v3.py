############################################################################
# tests/test_run_category_selector_v3.py
#
# Offline tests for scripts/run_category_selector_v3.py.
#
# Every test here uses a deterministic fake transport and a fake encoder. No
# test contacts DBpedia, downloads a model, or writes outside pytest's tmp_path.
# The frozen selector (category_extractor_ClaudeWeb_v3) is exercised for real —
# only its transport is replaced.
#
# Run:
#     python -m pytest -q tests/test_run_category_selector_v3.py
############################################################################

from __future__ import annotations

import hashlib
import json
import pathlib
import pickle
import subprocess
import sys
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(SRC_DIR), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import category_extractor_ClaudeWeb_v3 as ce  # noqa: E402
import run_category_selector_v3 as runner_mod  # noqa: E402

RESOURCE = "http://dbpedia.org/resource/"
CATEGORY = ce.CATEGORY_PREFIX

ANSWER_A = RESOURCE + "Shinya_Yamanaka"
ANSWER_B = RESOURCE + "Kenichi_Fukui"
ANSWER_C = RESOURCE + "Carbon"
CAT_NOBEL = CATEGORY + "Japanese_Nobel_laureates"
CAT_STEM = CATEGORY + "Stem_cell_researchers"

DATA_FILE = REPO_ROOT / "data" / "category_answer_nodes_v2_demo.txt"
V2_SOURCE = SRC_DIR / "category_extractor_ClaudeWeb_v2.py"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class BatchFakeClient:
    """Deterministic transport that answers every Answer URI the same way.

    ``fail_for`` makes the endpoint *fail* for one Answer, which the selector
    reports as the ordinary data outcome ``query_failed`` — not as a crash.
    """

    def __init__(
        self,
        *,
        categories=(CAT_NOBEL, CAT_STEM),
        counts=None,
        fail_for=(),
        redirect_map=None,
        no_categories_for=(),
        abstract=None,
    ):
        self.endpoint = "http://fake.invalid/sparql"
        self.language = "en"
        self.categories = tuple(categories)
        self.counts = dict(counts or {CAT_NOBEL: 30, CAT_STEM: 120})
        self.fail_for = set(fail_for)
        self.redirect_map = dict(redirect_map or {})
        self.no_categories_for = set(no_categories_for)
        self.abstract = abstract
        self.calls: list[str] = []

    @staticmethod
    def _cell(value):
        return {"value": str(value)}

    def _subject(self, query):
        for uri in (
            *self.fail_for,
            *self.no_categories_for,
            *self.redirect_map,
            *self.redirect_map.values(),
        ):
            if f"<{uri}>" in query:
                return uri
        return None

    def run(self, query):
        qid = ce.query_id(query)
        self.calls.append(qid)
        subject = self._subject(query)
        if subject in self.fail_for and qid in ("answer_info", "answer_categories"):
            return ce.QueryResult(
                status=ce.QueryStatus.FAILED,
                error=f"simulated endpoint failure for {subject}",
                endpoint=self.endpoint,
                language=self.language,
            )
        rows = self._rows(qid, query, subject)
        return ce.QueryResult(
            status=ce.QueryStatus.OK if rows else ce.QueryStatus.ZERO_RESULTS,
            rows=tuple(rows),
            endpoint=self.endpoint,
            language=self.language,
        )

    def _rows(self, qid, query, subject):
        if qid == "answer_info":
            row = {"label": self._cell("Fake Label")}
            if self.abstract:
                row["abs"] = self._cell(self.abstract)
            return [row]
        if qid == "answer_categories":
            if subject in self.no_categories_for:
                return []
            return [{"cat": self._cell(c)} for c in self.categories]
        if qid == "category_counts":
            return [
                {"cat": self._cell(c), "c": self._cell(n)}
                for c, n in sorted(self.counts.items())
                if f"<{c}>" in query
            ]
        if qid == "redirect":
            for source, target in sorted(self.redirect_map.items()):
                if f"<{source}>" in query:
                    return [{"target": self._cell(target)}]
            return []
        if qid in ("class_members", "class_members_batch"):
            return []
        raise AssertionError(f"unexpected query id: {qid!r}")


class FakeEncoder:
    """Deterministic hash-based embedder. No model, no download, no network."""

    name = "fake-encoder"
    max_seq_length = 256

    def __init__(self):
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        return [
            [b / 255.0 for b in hashlib.sha256(t.encode("utf-8")).digest()[:8]]
            for t in texts
        ]


def make_runner(client=None):
    return ce.SparqlRunner(client=client or BatchFakeClient())


def read_jsonl(path):
    return [
        json.loads(line)
        for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_csv_rows(path):
    import csv

    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ---------------------------------------------------------------------------
# 1) Input dataset
# ---------------------------------------------------------------------------


def test_v2_extraction_yields_exactly_34_unique_uris_in_first_occurrence_order():
    uris = runner_mod.extract_answer_nodes_from_v2(V2_SOURCE)

    assert len(uris) == 34
    assert len(set(uris)) == 34, "the returned list must already be deduplicated"
    assert uris[0] == RESOURCE + "Eisaku_Satō", "the first entry must not move"
    assert uris[-1] == RESOURCE + "Phosphoric_acid", "the last entry must not move"
    assert all(u.startswith("http://dbpedia.org/resource/") for u in uris)
    assert all("<" not in u and ">" not in u for u in uris)


def test_adam_smith_is_deduplicated_to_its_first_occurrence():
    """v2 lists Adam_Smith twice; the second must vanish, not the first."""
    source = V2_SOURCE.read_text(encoding="utf-8")
    assert source.count("resource/Adam_Smith>") == 2, "the fixture assumption"

    uris = runner_mod.extract_answer_nodes_from_v2(V2_SOURCE)
    assert uris.count(RESOURCE + "Adam_Smith") == 1
    # First occurrence sits between Aristotle and Immanuel_Kant, where v2 wrote it.
    assert uris.index(RESOURCE + "Adam_Smith") == uris.index(RESOURCE + "Aristotle") + 1
    assert uris[uris.index(RESOURCE + "Adam_Smith") + 1] == RESOURCE + "Immanuel_Kant"


def test_the_committed_dataset_matches_the_extraction_exactly():
    expected = runner_mod.extract_answer_nodes_from_v2(V2_SOURCE)
    on_disk = DATA_FILE.read_text(encoding="utf-8").splitlines()
    assert on_disk == expected, "data file and v2 source have diverged"
    assert DATA_FILE.read_text(encoding="utf-8").endswith("\n")
    assert runner_mod.read_answer_uris(DATA_FILE) == expected


def test_reading_the_dataset_preserves_order_and_drops_repeats(tmp_path):
    path = tmp_path / "answers.txt"
    path.write_text(
        "\n".join(
            [
                "# a comment line",
                ANSWER_C,
                "",
                ANSWER_A,
                ANSWER_C,  # duplicate, later
                ANSWER_B,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert runner_mod.read_answer_uris(path) == [ANSWER_C, ANSWER_A, ANSWER_B]


@pytest.mark.parametrize(
    "bad",
    [
        "ftp://dbpedia.org/resource/X",
        "not-a-uri",
        "javascript:alert(1)",
        "http://dbpedia.org/resource/A B",
        'http://dbpedia.org/resource/X"} INSERT DATA {',
    ],
)
def test_malformed_uris_are_rejected_rather_than_skipped(tmp_path, bad):
    path = tmp_path / "answers.txt"
    path.write_text(f"{ANSWER_A}\n{bad}\n", encoding="utf-8")
    with pytest.raises(runner_mod.RunnerInputError):
        runner_mod.read_answer_uris(path)


def test_extraction_rejects_a_malformed_entry_in_the_source(tmp_path):
    fake = tmp_path / "fake_v2.py"
    fake.write_text(
        textwrap.dedent(
            '''
            if __name__ == "__main__":
                nodes = [
                    "<http://dbpedia.org/resource/Plato>",
                    "<ftp://dbpedia.org/resource/Broken>",
                ]
            '''
        ),
        encoding="utf-8",
    )
    with pytest.raises(runner_mod.RunnerInputError, match="not a usable http"):
        runner_mod.extract_answer_nodes_from_v2(fake)


def test_extraction_refuses_an_ambiguous_source(tmp_path):
    fake = tmp_path / "two_lists.py"
    fake.write_text(
        'nodes = ["<http://dbpedia.org/resource/A>"]\n'
        'nodes = ["<http://dbpedia.org/resource/B>"]\n',
        encoding="utf-8",
    )
    with pytest.raises(runner_mod.RunnerInputError, match="exactly one"):
        runner_mod.extract_answer_nodes_from_v2(fake)


# ---------------------------------------------------------------------------
# 2) Runner architecture
# ---------------------------------------------------------------------------


def test_one_shared_runner_and_one_resolver_over_it():
    runner = make_runner()
    resolver = runner_mod.build_resolver(runner, enabled=True)
    assert isinstance(resolver, ce.SparqlRedirectResolver)
    assert resolver.runner is runner, "the resolver must not own a second runner"
    assert runner_mod.build_resolver(runner, enabled=False) is None


def test_redirect_queries_contribute_to_the_answers_own_counters(tmp_path):
    target = RESOURCE + "Yamanaka_Shinya"
    client = BatchFakeClient(
        redirect_map={ANSWER_A: target}, no_categories_for={ANSWER_A}
    )
    runner = make_runner(client)

    outcome = runner_mod.run_batch(
        answer_uris=[ANSWER_A],
        output_dir=tmp_path,
        runner=runner,
        resolve_redirects=True,
    )
    record = outcome.records[0]

    assert record["redirect_used"] is True
    assert record["query_uri"] == target
    assert record["original_uri"] == ANSWER_A
    assert "redirect" in client.calls
    # answer_info, answer_categories, redirect, answer_info, answer_categories,
    # category_counts — all six belong to this one Answer.
    assert record["sparql_query_count"] == 6
    assert record["cache_stats"]["queries"] == 6
    assert runner.stats()["queries"] == 6


def test_global_runner_total_equals_the_sum_of_per_answer_counts(tmp_path):
    client = BatchFakeClient(fail_for={ANSWER_B})
    runner = make_runner(client)

    outcome = runner_mod.run_batch(
        answer_uris=[ANSWER_A, ANSWER_B, ANSWER_C],
        output_dir=tmp_path,
        runner=runner,
    )
    per_answer = sum(
        record.get("sparql_query_count", record.get("queries_spent", 0))
        for record in outcome.records
    )
    assert per_answer == runner.stats()["queries"]
    assert runner.stats()["client_calls"] == len(client.calls)
    assert outcome.manifest["shared_runner_final_stats"] == runner.stats()


# ---------------------------------------------------------------------------
# 3) CLI
# ---------------------------------------------------------------------------


def _cli(tmp_path, *extra, uris=(ANSWER_A,)):
    source = tmp_path / "answers.txt"
    source.write_text("".join(f"{u}\n" for u in uris), encoding="utf-8")
    return [
        "--input", str(source),
        "--output-dir", str(tmp_path / "out"),
        *extra,
    ]


def test_network_is_denied_without_allow_network(tmp_path, capsys, monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("a live runner was constructed without --allow-network")

    monkeypatch.setattr(runner_mod, "make_dbpedia_runner", explode)
    monkeypatch.setattr(runner_mod, "SbertEncoder", explode)

    code = runner_mod.main(_cli(tmp_path))

    assert code == runner_mod.EXIT_NETWORK_DENIED
    assert code != 0
    message = capsys.readouterr().err
    assert "refusing to run" in message
    assert "--allow-network" in message
    assert not (tmp_path / "out").exists(), "no output may be written on refusal"


def test_use_sbert_alone_does_not_reach_the_gate(tmp_path, monkeypatch):
    """--use-sbert must not become a back door to a model download."""

    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("SBERT was constructed without --allow-network")

    monkeypatch.setattr(runner_mod, "SbertEncoder", explode)
    monkeypatch.setattr(runner_mod, "make_dbpedia_runner", explode)
    assert runner_mod.main(_cli(tmp_path, "--use-sbert")) == runner_mod.EXIT_NETWORK_DENIED


def test_refresh_and_bypass_are_mutually_exclusive(tmp_path, capsys):
    code = runner_mod.main(_cli(tmp_path, "--refresh", "--bypass"))
    assert code == runner_mod.EXIT_USAGE
    assert "mutually exclusive" in capsys.readouterr().err


def test_manual_mode_requires_a_requested_class(tmp_path, capsys):
    code = runner_mod.main(_cli(tmp_path, "--mode", "manual"))
    assert code == runner_mod.EXIT_USAGE
    assert "--requested-class is required" in capsys.readouterr().err

    # With the class supplied, the run proceeds as far as the network gate.
    code = runner_mod.main(
        _cli(tmp_path, "--mode", "manual", "--requested-class", CAT_NOBEL)
    )
    assert code == runner_mod.EXIT_NETWORK_DENIED


def test_an_unreadable_local_index_fails_before_any_client_is_built(tmp_path, monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("a client was constructed despite a bad local index")

    monkeypatch.setattr(runner_mod, "make_dbpedia_runner", explode)

    broken = tmp_path / "broken.pickle"
    broken.write_bytes(b"this is not a pickle")
    code = runner_mod.main(
        _cli(tmp_path, "--allow-network", "--local-index-pickle", str(broken))
    )
    assert code == runner_mod.EXIT_USAGE


def test_an_incompatible_local_index_is_rejected(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        runner_mod, "make_dbpedia_runner",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("client built")),
    )
    wrong_type = tmp_path / "list.pickle"
    wrong_type.write_bytes(pickle.dumps(["not", "a", "mapping"]))
    assert runner_mod.main(
        _cli(tmp_path, "--allow-network", "--local-index-pickle", str(wrong_type))
    ) == runner_mod.EXIT_USAGE
    assert "expected a mapping" in capsys.readouterr().err

    empty = tmp_path / "empty.pickle"
    empty.write_bytes(pickle.dumps({}))
    assert runner_mod.main(
        _cli(tmp_path, "--allow-network", "--local-index-pickle", str(empty))
    ) == runner_mod.EXIT_USAGE


def test_a_malformed_input_file_is_reported_as_usage(tmp_path, capsys):
    source = tmp_path / "bad.txt"
    source.write_text("not-a-uri\n", encoding="utf-8")
    code = runner_mod.main(
        ["--input", str(source), "--output-dir", str(tmp_path / "out")]
    )
    assert code == runner_mod.EXIT_USAGE
    assert "not a usable http(s) IRI" in capsys.readouterr().err


def test_the_parser_exposes_every_documented_flag():
    actions = {a.dest for a in runner_mod.build_parser()._actions}
    for dest in (
        "input", "output_dir", "cache_path", "mode", "requested_class", "top_n",
        "endpoint", "language", "allow_network", "resolve_redirects", "use_sbert",
        "sbert_model", "local_index_pickle", "refresh", "bypass", "resume",
    ):
        assert dest in actions, f"missing CLI flag: {dest}"


# ---------------------------------------------------------------------------
# 4) Batch execution
# ---------------------------------------------------------------------------


def test_input_order_is_preserved_and_every_answer_gets_one_record(tmp_path):
    uris = [ANSWER_C, ANSWER_A, ANSWER_B]
    outcome = runner_mod.run_batch(
        answer_uris=uris, output_dir=tmp_path, runner=make_runner()
    )
    assert [r["original_uri"] for r in outcome.records] == uris

    rows = read_csv_rows(tmp_path / "summary.csv")
    assert [r["original_uri"] for r in rows] == uris
    assert [int(r["input_index"]) for r in rows] == [0, 1, 2]


def test_ordinary_selector_outcomes_do_not_stop_the_batch(tmp_path):
    """query_failed and no_subject_categories are data, not crashes."""
    client = BatchFakeClient(fail_for={ANSWER_A}, no_categories_for={ANSWER_B})
    outcome = runner_mod.run_batch(
        answer_uris=[ANSWER_A, ANSWER_B, ANSWER_C],
        output_dir=tmp_path,
        runner=make_runner(client),
    )
    statuses = [r["selection_status"] for r in outcome.records]
    assert statuses == ["query_failed", "no_subject_categories", "ok"]
    assert outcome.unexpected_exception_count == 0
    assert outcome.normal_result_count == 3
    assert outcome.exit_code == 0, "a data outcome must not fail the process"


def test_one_unexpected_exception_is_isolated_and_the_batch_continues(tmp_path):
    # An unusable URI makes the selector raise ValueError before any query.
    uris = [ANSWER_A, "not-a-uri", ANSWER_C]
    outcome = runner_mod.run_batch(
        answer_uris=uris, output_dir=tmp_path, runner=make_runner()
    )

    assert outcome.normal_result_count == 2
    assert outcome.unexpected_exception_count == 1
    assert outcome.exit_code == runner_mod.EXIT_UNEXPECTED_EXCEPTIONS
    assert outcome.exit_code != 0

    envelope = outcome.records[1]
    assert envelope["record_type"] == runner_mod.RECORD_TYPE_EXCEPTION
    assert envelope["record_type"] != runner_mod.RECORD_TYPE_RESULT
    assert envelope["original_uri"] == "not-a-uri"
    assert envelope["runner_exception_type"] == "ValueError"
    assert envelope["runner_exception_message"]
    assert "Traceback" in envelope["traceback"]
    # It must not masquerade as a ClassSelectionResult.
    for absent in ("selection_status", "query_status", "recommended_classes"):
        assert absent not in envelope

    # The Answer after the failure still ran.
    assert outcome.records[2]["record_type"] == runner_mod.RECORD_TYPE_RESULT
    assert outcome.records[2]["selection_status"] == "ok"


def test_an_exception_after_some_queries_still_records_what_it_spent(tmp_path, monkeypatch):
    real = runner_mod.select_candidate_classes
    calls = {"n": 0}

    def flaky(uri, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            kwargs["runner"].run(ce.build_answer_info_query(uri))
            raise RuntimeError("simulated runner defect")
        return real(uri, **kwargs)

    monkeypatch.setattr(runner_mod, "select_candidate_classes", flaky)
    runner = make_runner()
    outcome = runner_mod.run_batch(
        answer_uris=[ANSWER_A, ANSWER_B, ANSWER_C],
        output_dir=tmp_path,
        runner=runner,
    )
    envelope = outcome.records[1]
    assert envelope["runner_exception_type"] == "RuntimeError"
    assert envelope["queries_spent"] == 1
    total = sum(
        r.get("sparql_query_count", r.get("queries_spent", 0)) for r in outcome.records
    )
    assert total == runner.stats()["queries"]


def test_summary_reports_the_exception_columns(tmp_path):
    runner_mod.run_batch(
        answer_uris=[ANSWER_A, "not-a-uri"],
        output_dir=tmp_path,
        runner=make_runner(),
    )
    rows = read_csv_rows(tmp_path / "summary.csv")
    assert rows[0]["runner_exception_type"] == ""
    assert rows[0]["selection_status"] == "ok"
    assert rows[1]["runner_exception_type"] == "ValueError"
    assert rows[1]["selection_status"] == ""
    assert rows[1]["original_uri"] == "not-a-uri"


# ---------------------------------------------------------------------------
# 5) Outputs
# ---------------------------------------------------------------------------


def test_all_four_outputs_are_written(tmp_path):
    outcome = runner_mod.run_batch(
        answer_uris=[ANSWER_A], output_dir=tmp_path, runner=make_runner()
    )
    for name in ("results.jsonl", "summary.csv", "ranking.csv", "run_manifest.json"):
        assert (tmp_path / name).is_file(), name
    assert set(outcome.output_paths) == {"results", "summary", "ranking", "manifest"}


def test_csv_and_jsonl_row_counts_agree(tmp_path):
    uris = [ANSWER_A, ANSWER_B, ANSWER_C]
    runner_mod.run_batch(
        answer_uris=uris, output_dir=tmp_path, runner=make_runner()
    )
    records = read_jsonl(tmp_path / "results.jsonl")
    summary = read_csv_rows(tmp_path / "summary.csv")
    ranking = read_csv_rows(tmp_path / "ranking.csv")

    assert len(records) == len(summary) == len(uris)
    expected_ranking = sum(len(r.get("evaluated_classes", ())) for r in records)
    assert len(ranking) == expected_ranking
    assert expected_ranking > 0, "the fixture must evaluate at least one class"


def test_ranking_rank_is_blank_for_classes_that_were_not_recommended(tmp_path):
    # Japanese_Nobel_laureates survives; a junk category is rejected outright.
    client = BatchFakeClient(
        categories=(CAT_NOBEL, CATEGORY + "Living_people"),
        counts={CAT_NOBEL: 30, CATEGORY + "Living_people": 900_000},
    )
    runner_mod.run_batch(
        answer_uris=[ANSWER_A], output_dir=tmp_path, runner=make_runner(client)
    )
    rows = {r["category_uri"]: r for r in read_csv_rows(tmp_path / "ranking.csv")}

    assert rows[CAT_NOBEL]["recommended_rank"] == "1"
    assert rows[CAT_NOBEL]["feasible"] == "true"
    rejected = rows[CATEGORY + "Living_people"]
    assert rejected["recommended_rank"] == "", "absence of a rank is not rank zero"
    assert rejected["feasible"] == "false"
    assert rejected["rejected_code"]
    for column in runner_mod.RANKING_COLUMNS:
        assert column in rejected


def test_manifest_records_the_frozen_selector_version_and_no_addresses(tmp_path):
    runner = make_runner()
    outcome = runner_mod.run_batch(
        answer_uris=[ANSWER_A, ANSWER_B],
        output_dir=tmp_path,
        runner=runner,
        selector_options={"mode": "recommended", "top_n": 5, "language": "en"},
        manifest_context={"input_path": "fixture", "input_row_count": 2},
    )
    manifest = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))

    assert manifest["selector_schema_version"] == "category_selector_v3.3"
    assert manifest["selector_schema_version"] == ce.SCHEMA_VERSION
    assert manifest["runner_schema_version"] == runner_mod.RUNNER_SCHEMA_VERSION
    for key in (
        "runner_schema_version", "selector_schema_version", "started_at_utc",
        "finished_at_utc", "duration_seconds", "command_arguments", "input_path",
        "input_sha256", "input_row_count", "unique_answer_count",
        "output_file_sha256", "git_commit", "git_describe", "python_version",
        "platform", "endpoint", "language", "cache_path", "cache_mode",
        "redirects_enabled", "sbert_enabled", "sbert_model",
        "local_index_supplied", "selector_configuration",
        "shared_runner_final_stats", "normal_result_count",
        "unexpected_exception_count", "selection_status_counts",
        "query_status_counts",
    ):
        assert key in manifest, f"missing manifest key: {key}"

    assert manifest["unique_answer_count"] == 2
    assert manifest["normal_result_count"] == 2
    assert manifest["unexpected_exception_count"] == 0
    assert manifest["selection_status_counts"] == {"ok": 2}
    assert manifest["sbert_enabled"] is False
    assert manifest["local_index_supplied"] is False
    assert manifest["output_file_sha256"]["results.jsonl"] == hashlib.sha256(
        (tmp_path / "results.jsonl").read_bytes()
    ).hexdigest()

    # No memory addresses anywhere in the serialised manifest.
    import re

    assert not re.search(r"0x[0-9a-f]{6,}", json.dumps(manifest)), manifest
    assert manifest == dict(outcome.manifest)


def test_outputs_are_replaced_atomically_leaving_no_temporary_files(tmp_path):
    stale = tmp_path / "results.jsonl"
    tmp_path.mkdir(parents=True, exist_ok=True)
    stale.write_text('{"stale": true}\n', encoding="utf-8")

    runner_mod.run_batch(
        answer_uris=[ANSWER_A], output_dir=tmp_path, runner=make_runner()
    )

    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], f"temporary files survived: {leftovers}"
    records = read_jsonl(stale)
    assert len(records) == 1 and "stale" not in records[0]


def test_a_failed_write_leaves_the_previous_file_intact(tmp_path, monkeypatch):
    """os.replace is the only thing that publishes a result."""
    target = tmp_path / "atomic.txt"
    runner_mod._atomic_write_text(target, "first\n")

    def boom(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(runner_mod.os, "replace", boom)
    with pytest.raises(OSError):
        runner_mod._atomic_write_text(target, "second\n")

    assert target.read_text(encoding="utf-8") == "first\n"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


# ---------------------------------------------------------------------------
# 6) Resume
# ---------------------------------------------------------------------------


def test_resume_skips_completed_answers_without_duplicating_records(tmp_path):
    first_client = BatchFakeClient()
    runner_mod.run_batch(
        answer_uris=[ANSWER_A, ANSWER_B],
        output_dir=tmp_path,
        runner=make_runner(first_client),
    )
    calls_after_first = len(first_client.calls)
    assert calls_after_first > 0

    second_client = BatchFakeClient()
    outcome = runner_mod.run_batch(
        answer_uris=[ANSWER_A, ANSWER_B, ANSWER_C],
        output_dir=tmp_path,
        runner=make_runner(second_client),
        resume=True,
    )

    uris = [r["original_uri"] for r in outcome.records]
    assert uris == [ANSWER_A, ANSWER_B, ANSWER_C], "input order must survive resume"
    assert len(uris) == len(set(uris)), "resume must not duplicate a record"
    assert outcome.resumed_count == 2
    assert outcome.new_normal_result_count == 1, "only the new Answer was run"
    assert outcome.normal_result_count == 3, "but the final output holds all three"
    assert outcome.final_record_count == 3

    records = read_jsonl(tmp_path / "results.jsonl")
    assert len(records) == 3
    assert len(read_csv_rows(tmp_path / "summary.csv")) == 3


def test_resume_ignores_a_truncated_final_line(tmp_path):
    results = tmp_path / "results.jsonl"
    tmp_path.mkdir(parents=True, exist_ok=True)
    results.write_text(
        json.dumps(_complete_normal_record(ANSWER_A))
        + "\n"
        + '{"original_uri": "' + ANSWER_B + '", "record_ty',  # truncated write
        encoding="utf-8",
    )
    preserved = runner_mod.load_previous_records(results)
    assert set(preserved) == {ANSWER_A}, "an incomplete line is not a finished Answer"

    outcome = runner_mod.run_batch(
        answer_uris=[ANSWER_A, ANSWER_B],
        output_dir=tmp_path,
        runner=make_runner(),
        resume=True,
    )
    assert outcome.resumed_count == 1
    assert outcome.new_normal_result_count == 1, "the truncated Answer was rerun"
    assert outcome.normal_result_count == 2, "the final output holds both"
    assert [r["original_uri"] for r in outcome.records] == [ANSWER_A, ANSWER_B]


def test_without_resume_a_previous_run_is_replaced_not_appended(tmp_path):
    for _ in range(2):
        runner_mod.run_batch(
            answer_uris=[ANSWER_A], output_dir=tmp_path, runner=make_runner()
        )
    assert len(read_jsonl(tmp_path / "results.jsonl")) == 1


# ---------------------------------------------------------------------------
# 7) Determinism
# ---------------------------------------------------------------------------


def test_two_equivalent_offline_runs_produce_identical_outputs(tmp_path):
    uris = [ANSWER_A, ANSWER_B, ANSWER_C]

    def run(directory):
        runner_mod.run_batch(
            answer_uris=uris,
            output_dir=directory,
            runner=make_runner(BatchFakeClient()),
            selector_options={"mode": "recommended", "top_n": 5, "language": "en"},
        )
        return {
            name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in ("results.jsonl", "summary.csv", "ranking.csv")
        }

    first = run(tmp_path / "run_a")
    second = run(tmp_path / "run_b")
    assert first == second, "equivalent offline runs must be byte-identical"


def test_the_encoder_is_used_when_supplied_and_absent_otherwise(tmp_path):
    encoder = FakeEncoder()
    client = BatchFakeClient(abstract="A deterministic abstract about chemistry.")
    outcome = runner_mod.run_batch(
        answer_uris=[ANSWER_A],
        output_dir=tmp_path,
        runner=make_runner(client),
        encoder=encoder,
    )
    assert encoder.calls > 0, "the supplied encoder must actually be used"
    assert outcome.manifest["sbert_enabled"] is True
    assert outcome.records[0]["encoder_metadata"]["available"] is True


# ---------------------------------------------------------------------------
# 8) Import hygiene
# ---------------------------------------------------------------------------


def test_importing_the_runner_creates_no_file_loads_no_model_and_opens_no_socket(tmp_path):
    """Checked in a clean interpreter, since this session already imported it."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        textwrap.dedent(
            f"""
            import json, pathlib, socket, sys
            workdir = pathlib.Path({str(tmp_path)!r})
            before = {{p.name for p in workdir.iterdir()}}

            def blocked(*a, **k):
                raise RuntimeError("import-time network access")

            socket.socket = blocked
            socket.create_connection = blocked

            sys.path.insert(0, {str(SCRIPTS_DIR)!r})
            seen = set(sys.modules)
            import run_category_selector_v3 as mod
            new = set(sys.modules) - seen

            heavy = sorted(
                m for m in new
                if m.split(".")[0] in {{
                    "SPARQLWrapper", "sentence_transformers", "torch",
                    "transformers", "spacy", "nltk", "requests", "urllib3",
                }}
            )
            after = {{p.name for p in workdir.iterdir()}}
            print(json.dumps({{
                "created": sorted(after - before),
                "heavy": heavy,
                "selector_schema": mod.SELECTOR_SCHEMA_VERSION,
                "cache_exists": pathlib.Path(mod.DEFAULT_INPUT).parent.joinpath(
                    "no-such-cache.sqlite").exists(),
            }}))
            """
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(probe)],
        capture_output=True, text=True, timeout=120, cwd=str(tmp_path),
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout.strip().splitlines()[-1])
    assert report["created"] == [], f"import created files: {report['created']}"
    assert report["heavy"] == [], f"import pulled in heavy modules: {report['heavy']}"
    assert report["selector_schema"] == "category_selector_v3.3"


# ---------------------------------------------------------------------------
# 9) Audit A: only a complete, current-schema result may be resumed
# ---------------------------------------------------------------------------


def _complete_normal_record(uri=ANSWER_A, **overrides):
    record = {
        "record_type": runner_mod.RECORD_TYPE_RESULT,
        "original_uri": uri,
        "schema_version": ce.SCHEMA_VERSION,
        "query_status": "ok",
        "selection_status": "ok",
        "sparql_query_count": 3,
        "cache_stats": {
            "queries": 3, "cache_hits": 0, "client_calls": 3,
            "failed": 0, "zero_results": 0,
        },
        "recommended_classes": [],
        "evaluated_classes": [],
    }
    record.update(overrides)
    return record


def _complete_envelope(uri=ANSWER_A, **overrides):
    record = {
        "record_type": runner_mod.RECORD_TYPE_EXCEPTION,
        "original_uri": uri,
        "runner_exception_type": "RuntimeError",
        "runner_exception_message": "simulated",
        "traceback": "Traceback (most recent call last):\n  ...\n",
        "queries_spent": 0,
    }
    record.update(overrides)
    return record


@pytest.mark.parametrize(
    "case, record, resumable",
    [
        # 1) A bare URI proves nothing about whether the Answer finished.
        ("only_original_uri", {"original_uri": ANSWER_A}, False),
        # 2) A discriminator without any of the payload is equally uninformative.
        (
            "record_type_only",
            {"original_uri": ANSWER_A, "record_type": runner_mod.RECORD_TYPE_RESULT},
            False,
        ),
        # 3) A record written by an older selector is not comparable evidence.
        (
            "wrong_selector_schema",
            _complete_normal_record(schema_version="category_selector_v3.2"),
            False,
        ),
        # 4) An exception envelope records a failure, not a finished Answer.
        ("runner_exception_envelope", _complete_envelope(), False),
        # 5) Only this one may be skipped.
        ("complete_normal_record", _complete_normal_record(), True),
    ],
)
def test_only_a_complete_current_schema_result_is_resumable(tmp_path, case, record, resumable):
    (tmp_path / "results.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )
    preserved = runner_mod.load_previous_records(tmp_path / "results.jsonl")
    assert (ANSWER_A in preserved) is resumable, case


@pytest.mark.parametrize(
    "missing",
    [
        "query_status", "selection_status", "sparql_query_count",
        "cache_stats", "recommended_classes", "evaluated_classes",
        "schema_version",
    ],
)
def test_a_normal_record_missing_any_required_field_is_not_resumable(tmp_path, missing):
    record = _complete_normal_record()
    record.pop(missing)
    (tmp_path / "results.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )
    assert runner_mod.load_previous_records(tmp_path / "results.jsonl") == {}


@pytest.mark.parametrize(
    "missing",
    ["runner_exception_type", "runner_exception_message", "traceback", "queries_spent"],
)
def test_an_incomplete_envelope_is_not_even_a_valid_envelope(tmp_path, missing):
    record = _complete_envelope()
    record.pop(missing)
    (tmp_path / "results.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )
    # Incomplete either way, so it cannot be resumed — the Answer is rerun.
    assert runner_mod.load_previous_records(tmp_path / "results.jsonl") == {}


def test_resume_replaces_a_previous_exception_envelope_with_a_fresh_result(tmp_path, monkeypatch):
    """A failed Answer is retried, not preserved as though it had succeeded."""
    real = runner_mod.select_candidate_classes

    def flaky(uri, **kwargs):
        if uri == ANSWER_B:
            raise RuntimeError("simulated first-run defect")
        return real(uri, **kwargs)

    monkeypatch.setattr(runner_mod, "select_candidate_classes", flaky)
    first = runner_mod.run_batch(
        answer_uris=[ANSWER_A, ANSWER_B], output_dir=tmp_path, runner=make_runner()
    )
    assert first.unexpected_exception_count == 1
    assert first.exit_code != 0

    monkeypatch.setattr(runner_mod, "select_candidate_classes", real)
    second = runner_mod.run_batch(
        answer_uris=[ANSWER_A, ANSWER_B],
        output_dir=tmp_path,
        runner=make_runner(),
        resume=True,
    )
    assert second.resumed_count == 1, "only the successful Answer may be skipped"
    assert second.new_normal_result_count == 1, "the failed Answer must be rerun"
    assert second.records[1]["record_type"] == runner_mod.RECORD_TYPE_RESULT
    assert second.unexpected_exception_count == 0
    assert second.exit_code == 0
    assert len(read_jsonl(tmp_path / "results.jsonl")) == 2


# ---------------------------------------------------------------------------
# 10) Audit B: the CLI never silently overwrites an existing result set
# ---------------------------------------------------------------------------


def _explode(*args, **kwargs):  # pragma: no cover - must never run
    raise AssertionError("a live runner was constructed when it must not be")


def _offline_runner(monkeypatch, client=None):
    """Let main() run end to end with a fake transport instead of DBpedia."""
    fake = ce.SparqlRunner(client=client or BatchFakeClient())
    monkeypatch.setattr(runner_mod, "make_dbpedia_runner", lambda **kwargs: fake)
    return fake


@pytest.mark.parametrize(
    "existing", ["results.jsonl", "summary.csv", "ranking.csv", "run_manifest.json"]
)
def test_the_cli_refuses_to_overwrite_an_existing_output(tmp_path, capsys, monkeypatch, existing):
    monkeypatch.setattr(runner_mod, "make_dbpedia_runner", _explode)
    out = tmp_path / "out"
    out.mkdir()
    (out / existing).write_text("previous experiment\n", encoding="utf-8")

    code = runner_mod.main(
        _cli(tmp_path, "--allow-network") [:2] + ["--output-dir", str(out), "--allow-network"]
    )

    assert code == runner_mod.EXIT_OUTPUT_EXISTS
    assert code != 0
    message = capsys.readouterr().err
    assert str(out / existing) in message, "the exact existing path must be named"
    assert "--resume" in message
    assert (out / existing).read_text(encoding="utf-8") == "previous experiment\n"


def test_the_overwrite_refusal_names_every_existing_output(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(runner_mod, "make_dbpedia_runner", _explode)
    out = tmp_path / "out"
    out.mkdir()
    for name in ("results.jsonl", "ranking.csv"):
        (out / name).write_text("x\n", encoding="utf-8")

    code = runner_mod.main(
        _cli(tmp_path)[:2] + ["--output-dir", str(out), "--allow-network"]
    )
    message = capsys.readouterr().err
    assert code == runner_mod.EXIT_OUTPUT_EXISTS
    assert str(out / "results.jsonl") in message
    assert str(out / "ranking.csv") in message
    assert str(out / "summary.csv") not in message, "only existing paths are listed"


def test_unrelated_files_in_the_output_directory_do_not_cause_refusal(tmp_path, monkeypatch):
    fake = _offline_runner(monkeypatch)
    out = tmp_path / "out"
    out.mkdir()
    (out / "notes.md").write_text("nothing to do with the run\n", encoding="utf-8")

    code = runner_mod.main(
        _cli(tmp_path)[:2] + ["--output-dir", str(out), "--allow-network"]
    )
    assert code == runner_mod.EXIT_OK
    assert (out / "results.jsonl").is_file()
    assert (out / "notes.md").is_file(), "an unrelated file must survive untouched"
    assert fake.stats()["queries"] > 0


def test_resume_permits_reusing_an_existing_output_directory(tmp_path, monkeypatch):
    out = tmp_path / "out"
    _offline_runner(monkeypatch)
    argv = _cli(tmp_path)[:2] + ["--output-dir", str(out), "--allow-network"]
    assert runner_mod.main(argv) == runner_mod.EXIT_OK

    _offline_runner(monkeypatch)
    assert runner_mod.main(argv + ["--resume"]) == runner_mod.EXIT_OK
    assert len(read_jsonl(out / "results.jsonl")) == 1


# ---------------------------------------------------------------------------
# 11) Audit C: raw rows and unique Answers are different provenance
# ---------------------------------------------------------------------------


def test_input_row_count_and_unique_answer_count_are_reported_separately(tmp_path):
    source = tmp_path / "answers.txt"
    source.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                ANSWER_A,
                ANSWER_B,
                "   ",
                ANSWER_C,
                ANSWER_A,  # duplicate row
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    loaded = runner_mod.load_answer_input(source)
    assert loaded.row_count == 4, "four usable rows before deduplication"
    assert len(loaded.uris) == 3
    assert list(loaded.uris) == [ANSWER_A, ANSWER_B, ANSWER_C]


def test_the_demo_dataset_reports_34_rows_and_34_unique():
    loaded = runner_mod.load_answer_input(DATA_FILE)
    assert loaded.row_count == 34
    assert len(loaded.uris) == 34


def test_an_invalid_row_refuses_rather_than_being_silently_excluded(tmp_path):
    source = tmp_path / "answers.txt"
    source.write_text(f"{ANSWER_A}\nnot-a-uri\n{ANSWER_B}\n", encoding="utf-8")
    with pytest.raises(runner_mod.RunnerInputError):
        runner_mod.load_answer_input(source)


def test_the_manifest_records_both_input_counts(tmp_path, monkeypatch):
    _offline_runner(monkeypatch)
    source = tmp_path / "answers.txt"
    source.write_text(
        f"# header\n\n{ANSWER_A}\n{ANSWER_B}\n{ANSWER_C}\n{ANSWER_A}\n", encoding="utf-8"
    )
    out = tmp_path / "out"
    code = runner_mod.main(
        ["--input", str(source), "--output-dir", str(out), "--allow-network"]
    )
    assert code == runner_mod.EXIT_OK
    manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["input_row_count"] == 4
    assert manifest["unique_answer_count"] == 3
    assert manifest["input_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 12) Audit D: manifest counts describe the final output, not just this run
# ---------------------------------------------------------------------------


def test_manifest_counts_describe_the_whole_final_output_under_resume(tmp_path):
    runner_mod.run_batch(
        answer_uris=[ANSWER_A, ANSWER_B], output_dir=tmp_path, runner=make_runner()
    )
    outcome = runner_mod.run_batch(
        answer_uris=[ANSWER_A, ANSWER_B, ANSWER_C],
        output_dir=tmp_path,
        runner=make_runner(),
        resume=True,
    )
    manifest = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    records = read_jsonl(tmp_path / "results.jsonl")

    assert manifest["final_record_count"] == len(records) == 3
    assert manifest["normal_result_count"] == 3, "resumed records count too"
    assert manifest["unexpected_exception_count"] == 0
    assert (
        manifest["final_record_count"]
        == manifest["normal_result_count"] + manifest["unexpected_exception_count"]
    )
    assert manifest["new_normal_result_count"] == 1
    assert manifest["new_unexpected_exception_count"] == 0
    assert manifest["resumed_record_count"] == 2
    assert sum(manifest["selection_status_counts"].values()) == 3
    assert sum(manifest["query_status_counts"].values()) == 3
    assert outcome.final_record_count == 3


def test_the_process_exits_nonzero_while_any_envelope_remains(tmp_path, monkeypatch):
    real = runner_mod.select_candidate_classes

    def always_broken(uri, **kwargs):
        if uri == ANSWER_B:
            raise RuntimeError("permanently broken Answer")
        return real(uri, **kwargs)

    monkeypatch.setattr(runner_mod, "select_candidate_classes", always_broken)
    first = runner_mod.run_batch(
        answer_uris=[ANSWER_A, ANSWER_B], output_dir=tmp_path, runner=make_runner()
    )
    assert first.exit_code == runner_mod.EXIT_UNEXPECTED_EXCEPTIONS

    second = runner_mod.run_batch(
        answer_uris=[ANSWER_A, ANSWER_B],
        output_dir=tmp_path,
        runner=make_runner(),
        resume=True,
    )
    manifest = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["unexpected_exception_count"] == 1
    assert manifest["final_record_count"] == 2
    assert second.exit_code != 0, "an unresolved envelope must keep the run failing"


def test_the_manifest_names_its_own_nondeterministic_fields(tmp_path):
    outcome = runner_mod.run_batch(
        answer_uris=[ANSWER_A], output_dir=tmp_path, runner=make_runner()
    )
    manifest = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    declared = set(manifest["nondeterministic_fields"])
    assert {"started_at_utc", "finished_at_utc", "duration_seconds"} <= declared
    for name in declared:
        assert name in manifest, f"declared field {name} is not in the manifest"
    assert "output_file_sha256" not in declared, "the data hashes must be stable"
    assert outcome.manifest["nondeterministic_fields"] == manifest["nondeterministic_fields"]


# ---------------------------------------------------------------------------
# 13) Audit: defensive input and CSV handling
# ---------------------------------------------------------------------------


def test_run_batch_refuses_duplicate_answer_uris(tmp_path):
    """Deduplication happens once, at input; a duplicate here is a caller bug."""
    with pytest.raises(runner_mod.RunnerInputError, match="duplicate"):
        runner_mod.run_batch(
            answer_uris=[ANSWER_A, ANSWER_B, ANSWER_A],
            output_dir=tmp_path,
            runner=make_runner(),
        )


def test_csv_quoting_survives_commas_quotes_and_newlines(tmp_path, monkeypatch):
    nasty = 'a message with, a comma; a "quote"; and\na newline'

    def raiser(uri, **kwargs):
        raise RuntimeError(nasty)

    monkeypatch.setattr(runner_mod, "select_candidate_classes", raiser)
    runner_mod.run_batch(
        answer_uris=[ANSWER_A], output_dir=tmp_path, runner=make_runner()
    )
    rows = read_csv_rows(tmp_path / "summary.csv")
    assert len(rows) == 1, "an embedded newline must not become a second row"
    assert rows[0]["runner_exception_message"] == nasty
    raw = (tmp_path / "summary.csv").read_bytes()
    assert b"\r\n" not in raw, "line endings must not be platform-dependent"


def test_the_frozen_selector_files_are_untouched():
    recorded = (
        REPO_ROOT / "docs" / "checksums" / "category_extractor_ClaudeWeb_v2.py.sha256"
    ).read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(V2_SOURCE.read_bytes()).hexdigest()
    assert actual == recorded, "the v2 source file must not be modified"
    assert ce.SCHEMA_VERSION == "category_selector_v3.3", "the selector is frozen at v3.3"
