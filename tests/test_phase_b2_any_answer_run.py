############################################################################
# tests/test_phase_b2_any_answer_run.py
#
# Tests for the generic any-Answer Phase-B runner:
#   src/pipeline/phase_b2_any_answer_run.py
#   scripts/run_phase_b2_any_answer_v2.py
#
# EVERY TEST IS OFFLINE. No network, no SBERT model, and no 1.2 GB pinned
# pickle: the SPARQL endpoint, the identity evidence source, the local KG
# lookup and the local-mapping walk are all fakes or fixtures. The three
# stages that genuinely need the pinned graph are exercised by the live smoke
# runs recorded under outputs/, not here.
############################################################################

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
SCRIPTS_DIR = REPO_ROOT / "scripts"
for path in (SRC_DIR, SCRIPTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import category_extractor_v6 as v6                          # noqa: E402
import mcq_inputs                                           # noqa: E402
import run_phase_b2_any_answer_v2 as runner                 # noqa: E402
from classes.member_mapper import make_local_lookup         # noqa: E402
from mcq_core import Candidate                              # noqa: E402
from pipeline import phase_b2_answer_run as b2              # noqa: E402
from pipeline import phase_b2_any_answer_run as anyb2       # noqa: E402

R = "http://dbpedia.org/resource/"
C = "http://dbpedia.org/resource/Category:"
S = anyb2.AnswerStatus


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeSparqlClient:
    """A v6-shaped fake endpoint, driven by `#qid:` markers.

    `asked` records every subject URI interpolated into a query, which is what
    lets a test assert WHICH of the Answer's three URIs the class queries used.
    """

    endpoint = "https://fake.example/sparql"

    def __init__(self, *, label="Fake Answer", categories=(), counts=None):
        self.label = label
        self.categories = tuple(categories)
        self.counts = dict(counts or {})
        self.asked: list[str] = []

    def run(self, query):
        qid = v6.query_id(query)
        for match in re.findall(r"<(http[^>]+)>", query):
            self.asked.append(match)
        if qid == "answer_info":
            return self._ok([{"label": {"value": self.label}}])
        if qid == "answer_categories":
            return self._ok([{"cat": {"value": c}} for c in self.categories])
        if qid == "category_counts":
            return self._ok([{"cat": {"value": c}, "c": {"value": str(n)}}
                             for c, n in self.counts.items()])
        return self._ok([])

    def _ok(self, rows):
        rows = tuple(rows)
        return v6.QueryResult(
            status=v6.QueryStatus.OK if rows else v6.QueryStatus.ZERO_RESULTS,
            rows=rows, endpoint=self.endpoint)


class FakeIdentitySource:
    def __init__(self, counts=None, forward=None, reverse=None):
        self.counts = dict(counts or {})
        self.forward = dict(forward or {})
        self.reverse = dict(reverse or {})
        self.query_count = 0

    def category_counts(self, uris):
        self.query_count += 1
        return {u: self.counts[u] for u in uris if u in self.counts}, frozenset()

    def forward_targets(self, uris):
        self.query_count += 1
        return {u: self.forward[u] for u in uris if u in self.forward}, frozenset()

    def reverse_sources(self, uris):
        self.query_count += 1
        return {u: self.reverse[u] for u in uris if u in self.reverse}, frozenset()


class FakeFetcher:
    def counters(self):
        return {"offline": True, "network_pages": 0, "cache_hits": 0,
                "pages_stored": 0, "failed_pages": 0}


def make_context(*, client, identity_source, url_index):
    """A context dict in the shape `build_context()` produces, but all fakes."""
    return {
        "local_kg": SimpleNamespace(url_index=url_index, source_sha256="fake"),
        "local_lookup": make_local_lookup(url_index),
        "retriever": object(),
        "redirects": object(),
        "fetcher": FakeFetcher(),
        "identity_source": identity_source,
        "sparql": v6.SparqlRunner(client=client),
        "universe": v6.IdfUniverse(total_entities=6_000_000, definition="TEST"),
        "encoder": None,
        "leads": None,
        "semantic_source": v6.SemanticSource.WIKIPEDIA_LEAD,
        "quality_policy": v6.load_r1_leakage_policy(),
        "semantic_policy": None,
        "base_rules": None,
    }


def make_args(**overrides):
    args = runner.build_parser().parse_args(
        ["--answer-uri", R + "X", "--offline-replay"])
    args.alpha = v6.DEFAULT_ALPHA
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


# ===========================================================================
# A) CLI contract
# ===========================================================================


def test_answer_uri_and_input_are_mutually_exclusive_and_one_is_required():
    with pytest.raises(SystemExit):
        runner.build_parser().parse_args(["--offline-replay"])
    with pytest.raises(SystemExit):
        runner.build_parser().parse_args(
            ["--answer-uri", "x", "--input", "f.txt", "--offline-replay"])


def test_alpha_defaults_to_the_pre_specified_zero_point_seven(capsys, monkeypatch):
    """Unset on the namespace, resolved to v6.DEFAULT_ALPHA inside main()."""
    args = runner.build_parser().parse_args(
        ["--answer-uri", "x", "--offline-replay"])
    assert args.alpha is None
    assert v6.DEFAULT_ALPHA == 0.7

    seen = {}

    def stop(parsed_args, local_kg):
        seen["alpha"] = parsed_args.alpha
        raise SystemExit(99)

    monkeypatch.setattr(runner, "load_local_kg", lambda *a, **k: SimpleNamespace(
        url_index={}, source_sha256="fake"))
    monkeypatch.setattr(runner, "build_context", stop)
    with pytest.raises(SystemExit):
        runner.main(["--answer-uri", R + "X", "--offline-replay"])
    assert seen["alpha"] == 0.7


def test_an_explicit_alpha_overrides_the_default(monkeypatch):
    seen = {}

    def stop(parsed_args, local_kg):
        seen["alpha"] = parsed_args.alpha
        raise SystemExit(99)

    monkeypatch.setattr(runner, "load_local_kg", lambda *a, **k: SimpleNamespace(
        url_index={}, source_sha256="fake"))
    monkeypatch.setattr(runner, "build_context", stop)
    with pytest.raises(SystemExit):
        runner.main(["--answer-uri", R + "X", "--offline-replay", "--alpha", "0.25"])
    assert seen["alpha"] == 0.25


@pytest.mark.parametrize("alpha", ["1.5", "-0.1", "nan"])
def test_an_invalid_alpha_is_rejected_before_any_work(alpha, capsys, monkeypatch):
    monkeypatch.setattr(runner, "load_local_kg", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("the pinned KG must not be loaded for a bad alpha")))
    assert runner.main(["--answer-uri", R + "X", "--offline-replay",
                        "--alpha", alpha]) == runner.EXIT_USAGE
    assert "alpha" in capsys.readouterr().out


def test_a_network_mode_must_be_declared(capsys, monkeypatch):
    monkeypatch.setattr(runner, "load_local_kg", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("nothing may run before the network gate")))
    assert runner.main(["--answer-uri", R + "X"]) == runner.EXIT_USAGE
    assert "exactly one of --allow-network / --offline-replay" in \
        capsys.readouterr().out
    assert runner.main(["--answer-uri", R + "X", "--allow-network",
                        "--offline-replay"]) == runner.EXIT_USAGE


def test_the_runner_does_not_accept_a_v5_results_file():
    """The whole point of B2-D: no pre-computed ranking file is required."""
    help_text = runner.build_parser().format_help()
    assert "--v5-results" not in help_text
    with pytest.raises(SystemExit):
        runner.build_parser().parse_args(
            ["--answer-uri", "x", "--offline-replay", "--v5-results", "f.jsonl"])


def test_every_documented_cli_option_exists():
    help_text = runner.build_parser().format_help()
    for option in ("--answer-uri", "--input", "--alpha", "--allow-network",
                   "--offline-replay", "--member-cache", "--score-cache",
                   "--wikipedia-cache", "--sparql-cache",
                   "--semantic-index-root", "--max-classes", "--output-report",
                   "--artifacts-dir"):
        assert option in help_text, option


# ===========================================================================
# B) The identity contract: which of the three URIs reaches which stage
# ===========================================================================


def _drifted_setup():
    """An entity renamed since the pinned dump, in the fakes' shapes.

    Pinned dump holds `Old_Name`; today's DBpedia serves `New_Name` and holds the
    categories there.
    """
    client = FakeSparqlClient(
        categories=[C + "Some_Feasible_Class"],
        counts={C + "Some_Feasible_Class": 400})
    identity = FakeIdentitySource(
        counts={R + "New_Name": 9},
        forward={R + "Old_Name": R + "New_Name"},
        reverse={R + "New_Name": (R + "Old_Name",)})
    url_index = {f"<{R}Old_Name>": 4242}
    return client, identity, url_index


def test_the_class_queries_use_the_remote_uri_and_the_walk_uses_the_local_one(
        monkeypatch):
    """The single most important contract in this module.

    The CURRENT endpoint is asked about the CURRENT resource, because the
    historical spelling carries no dcterms:subject triples there. The local
    mapping walk is handed the PINNED spelling, because that is the only one
    with a node — and because Answer exclusion downstream compares LOCAL NODE
    INDICES, which a current-spelling Answer would never match.
    """
    client, identity, url_index = _drifted_setup()
    captured = {}

    def fake_walk(answer_uri, ranked, **kwargs):
        captured["walk_answer_uri"] = answer_uri
        captured["ranked"] = ranked
        return SimpleNamespace(
            is_feasible=False, attempts=(), status="NO_MAPPING_FEASIBLE_RANKED_CLASS",
            selected_class_uri=None, selected_ranking_position=None,
            selected_mapping=None)

    monkeypatch.setattr(b2, "walk_ranked_classes_for_local_mapping", fake_walk)
    context = make_context(client=client, identity_source=identity,
                           url_index=url_index)
    result = runner.run_one_answer(R + "Old_Name", cohort=None, context=context,
                                   args=make_args(), out_dir=None)

    assert result.identity.original_uri == R + "Old_Name"
    assert result.identity.remote_query_uri == R + "New_Name"
    assert result.identity.local_kg_uri == R + "Old_Name"
    assert result.identity.local_index == 4242
    # Class queries went to the CURRENT resource...
    assert R + "New_Name" in client.asked
    assert R + "Old_Name" not in client.asked
    # ...and the local walk got the PINNED one.
    assert captured["walk_answer_uri"] == R + "Old_Name"
    assert result.status == S.NO_LOCALLY_MAPPING_FEASIBLE_CLASS


def test_an_answer_absent_from_the_pinned_dump_stops_with_a_named_status():
    client, identity, _ = _drifted_setup()
    context = make_context(client=client, identity_source=identity, url_index={})
    result = runner.run_one_answer(R + "Old_Name", cohort=None, context=context,
                                   args=make_args(), out_dir=None)
    assert result.status == S.NO_LOCAL_URI_IDENTITY
    assert result.selection is None


def test_an_ambiguous_local_alias_is_reported_and_never_guessed():
    client = FakeSparqlClient()
    identity = FakeIdentitySource(
        counts={R + "New_Name": 9},
        reverse={R + "New_Name": (R + "Old_A", R + "Old_B")})
    url_index = {f"<{R}Old_A>": 1, f"<{R}Old_B>": 2}
    context = make_context(client=client, identity_source=identity,
                           url_index=url_index)
    result = runner.run_one_answer(R + "New_Name", cohort=None, context=context,
                                   args=make_args(), out_dir=None)
    assert result.status == S.AMBIGUOUS_LOCAL_ALIAS


def test_a_malformed_answer_uri_is_input_invalid():
    context = make_context(client=FakeSparqlClient(),
                           identity_source=FakeIdentitySource(), url_index={})
    result = runner.run_one_answer("not a uri", cohort=None, context=context,
                                   args=make_args(), out_dir=None)
    assert result.status == S.INPUT_INVALID


def test_no_current_categories_is_its_own_status():
    client = FakeSparqlClient(categories=[])
    identity = FakeIdentitySource(counts={R + "Here": 3})
    context = make_context(client=client, identity_source=identity,
                           url_index={f"<{R}Here>": 7})
    result = runner.run_one_answer(R + "Here", cohort=None, context=context,
                                   args=make_args(), out_dir=None)
    assert result.status == S.NO_CURRENT_DBPEDIA_CATEGORIES


def test_every_class_rejected_is_no_usable_class():
    """An answer-revealing class name and a too-small class, and nothing else."""
    client = FakeSparqlClient(
        label="Aristotle",
        categories=[C + "Aristotelian_philosophers", C + "Aristotle"],
        counts={C + "Aristotelian_philosophers": 67, C + "Aristotle": 4})
    identity = FakeIdentitySource(counts={R + "Aristotle": 60})
    context = make_context(client=client, identity_source=identity,
                           url_index={f"<{R}Aristotle>": 11})
    result = runner.run_one_answer(R + "Aristotle", cohort=None, context=context,
                                   args=make_args(), out_dir=None)
    assert result.status == S.NO_USABLE_CLASS
    assert result.feasible_class_count == 0


# ===========================================================================
# C) The v6 -> walk adapter
# ===========================================================================


def test_the_adapter_copies_the_selector_order_and_numbers_verbatim():
    feature_a = v6.ClassFeature(
        category_uri=C + "Alpha", category_label="Alpha", remote_count=100,
        eligible_remote_count=99, raw_idf=2.0, raw_sbert=0.5,
        leak_level=v6.LeakLevel.SOFT, leak_status=v6.LeakStatus.EVALUATED,
        leak_evidence=("a~b:SHORT_PREFIX",), feasible=True)
    feature_b = v6.ClassFeature(
        category_uri=C + "Beta", category_label="Beta", remote_count=200,
        eligible_remote_count=199, raw_idf=1.0, raw_sbert=0.9, feasible=True)
    features = v6.AnswerFeatures(
        answer_uri=R + "X", answer_label="X", status=v6.STATUS_OK,
        classes=(feature_a, feature_b),
        idf_universe=v6.IdfUniverse(total_entities=1000, definition="TEST"))
    ranking = v6.rank_feasible_classes(features, 0.7)
    adapted = anyb2.ranked_classes_from_v6(ranking)

    assert [r.class_uri for r in adapted] == \
        [entry.category_uri for entry in ranking.ranked]
    assert [r.rank for r in adapted] == [1, 2]
    for adapted_row, entry in zip(adapted, ranking.ranked):
        assert adapted_row.combined_score == entry.combined_score
        assert adapted_row.normalized_idf == entry.normalized_idf
        assert adapted_row.leak_level == entry.feature.leak_level.value


def test_the_adapter_carries_a_missing_semantic_feature_as_none():
    """`None` means "no semantic feature exists"; 0.0 would mean something else."""
    feature = v6.ClassFeature(
        category_uri=C + "Alpha", category_label="Alpha", remote_count=100,
        eligible_remote_count=99, raw_idf=2.0, raw_sbert=None, feasible=True)
    features = v6.AnswerFeatures(
        answer_uri=R + "X", answer_label="X", status=v6.STATUS_OK,
        classes=(feature,),
        idf_universe=v6.IdfUniverse(total_entities=1000, definition="TEST"))
    adapted = anyb2.ranked_classes_from_v6(
        v6.rank_feasible_classes(features, 0.7))
    assert adapted[0].raw_sbert is None
    assert adapted[0].normalized_sbert is None


def test_a_hard_leaking_class_never_reaches_the_adapter():
    """The selector rejects it before scoring, so it is not in the ranking."""
    features = v6.AnswerFeatures(
        answer_uri=R + "Aristotle", answer_label="Aristotle",
        status=v6.STATUS_OK,
        classes=(v6.ClassFeature(
            category_uri=C + "Aristotelian_philosophers",
            category_label="Aristotelian philosophers",
            leak_level=v6.LeakLevel.HARD, feasible=False,
            rejected_code=v6.RejectCode.HARD_LEAK.value),))
    assert anyb2.ranked_classes_from_v6(
        v6.rank_feasible_classes(features, 0.7)) == ()


# ===========================================================================
# D) The evidence PROFILE of every ranked candidate
# ===========================================================================


def _case_with_levels(level_matrix):
    """A minimal `AnswerCase` shape: one row of levels per fact."""
    from mcq_core import AnswerFact, FactQuality, build_case

    candidates = [Candidate(rank=i + 1, score=1.0 - i / 10, uri=f"{R}C{i}")
                  for i in range(len(level_matrix[0]))]
    facts = []
    for index, levels in enumerate(level_matrix):
        quality = FactQuality(
            predicate_uri=f"http://dbpedia.org/property/p{index}",
            direction="OUT", counterpart_uri=f"{R}O{index}",
            display_label=f"O{index}", eligible=index != 1,   # fact 1 ineligible
            soft_leak=False, verbalizable=True, pedagogical_tier=1,
            label_length=2, token_count=1, template_id="T")
        facts.append(AnswerFact(
            quality=quality, levels=tuple(levels),
            exclusion_bases=("NONE",) * len(levels),
            granularity_risks=("NONE",) * len(levels)))
    return build_case(R + "A", "A", candidates, facts)


def test_the_profile_summarises_only_the_eligible_facts():
    case = _case_with_levels([
        ["L1", "L0", "NOT_COVERED"],     # eligible
        ["L2", "L2", "L2"],              # INELIGIBLE — must not appear
        ["L0", "L1", "L0"],              # eligible
    ])
    profiles = anyb2.summarise_candidate_evidence(case)
    assert [p.best_available_evidence_level for p in profiles] == \
        ["L1", "L1", "L0"]
    assert [p.eligible_fact_count for p in profiles] == [2, 2, 2]
    assert [p.l2_incidences for p in profiles] == [0, 0, 0]
    # The all-facts view still sees the ineligible L2, which is what makes the
    # hard filter's effect inspectable rather than invisible.
    assert [p.best_level_over_all_facts for p in profiles] == ["L2", "L2", "L2"]
    assert [p.all_facts_l2 for p in profiles] == [1, 1, 1]


def test_student_showable_counts_l1_and_l2_only():
    case = _case_with_levels([["L1", "L0", "NOT_COVERED"]])
    profiles = anyb2.summarise_candidate_evidence(case)
    assert [p.student_showable_fact_count for p in profiles] == [1, 0, 0]


def test_a_candidate_with_no_eligible_fact_is_not_covered():
    case = _case_with_levels([["L2", "L2"]])   # the only fact is ineligible? no:
    # fact index 0 IS eligible in the helper, so build an all-ineligible case.
    from mcq_core import AnswerFact, FactQuality, build_case

    quality = FactQuality(
        predicate_uri="http://dbpedia.org/property/p", direction="OUT",
        counterpart_uri=R + "O", display_label="O", eligible=False,
        soft_leak=False, verbalizable=True, pedagogical_tier=1, label_length=1,
        token_count=1, template_id="T")
    case = build_case(
        R + "A", "A", [Candidate(rank=1, score=1.0, uri=R + "C0")],
        [AnswerFact(quality=quality, levels=("L2",),
                    exclusion_bases=("NONE",), granularity_risks=("NONE",))])
    profiles = anyb2.summarise_candidate_evidence(case)
    assert profiles[0].best_available_evidence_level == "NOT_COVERED"
    assert profiles[0].eligible_fact_count == 0
    assert profiles[0].best_level_over_all_facts == "L2"


def test_the_complete_matrix_is_retained_alongside_the_summary():
    case = _case_with_levels([["L1", "L0"], ["L2", "L2"]])
    rows = anyb2.candidate_fact_evidence_rows(case)
    assert len(rows) == 2 * 2                     # facts x candidates
    assert {row["fact_eligible"] for row in rows} == {True, False}


# ===========================================================================
# E) The per-Answer semantic index path
# ===========================================================================


def test_the_semantic_index_path_is_per_answer_and_content_derived(tmp_path):
    a = anyb2.semantic_index_path(tmp_path, R + "Albert_Einstein", "a" * 64)
    b = anyb2.semantic_index_path(tmp_path, R + "Shinya_Yamanaka", "a" * 64)
    c = anyb2.semantic_index_path(tmp_path, R + "Albert_Einstein", "b" * 64)
    assert a != b, "two Answers must not share one index file"
    assert a != c, "one Answer with a different source-object set must not reuse"
    assert "Albert_Einstein" in a.name and a.name.endswith(".json")
    assert anyb2.semantic_index_path(tmp_path, R + "Albert_Einstein", "a" * 64) == a


def test_the_path_survives_a_parenthesised_or_accented_uri(tmp_path):
    path = anyb2.semantic_index_path(
        tmp_path, R + "Akira_Suzuki_(chemist)", "f" * 64)
    assert "/" not in path.name and "(" not in path.name


def _executable_text(path: Path) -> str:
    """Source with comments and docstrings removed, lower-cased.

    Prose must be free to name the earlier Einstein-only run it replaces;
    executable code must not name any entity at all.
    """
    code_only = []
    in_docstring = False
    for line in path.read_text("utf-8").splitlines():
        stripped = line.strip()
        if stripped.count('"""') == 1:
            in_docstring = not in_docstring
            continue
        if in_docstring or stripped.startswith("#") or stripped.startswith('"""'):
            continue
        code_only.append(line.split("#", 1)[0])
    return "\n".join(code_only).lower()


def test_no_answer_specific_filename_or_branch_survives_in_the_runner():
    """The B2-B driver hard-coded one Einstein index filename for every run.

    Nothing in the executable text of either new file may name an entity: the
    per-Answer index path is derived from the Answer URI and the source-object
    digest, and the pipeline branches on statuses, never on identities.
    """
    for path in (SCRIPTS_DIR / "run_phase_b2_any_answer_v2.py",
                 SRC_DIR / "pipeline" / "phase_b2_any_answer_run.py"):
        text = _executable_text(path)
        for name in ("einstein", "yamanaka", "aristotle", "tokugawa", "suzuki",
                     "kobayashi", "xun", "chikamatsu"):
            assert name not in text, f"{name!r} in the executable text of {path}"


# ===========================================================================
# F) The batch summary
# ===========================================================================


def _successful_result(uri="Shinya_Yamanaka", pool=24):
    distractors = tuple(Candidate(rank=i + 1, score=0.5 - i / 100,
                                  uri=f"{R}D{i}") for i in range(3))
    rationale = SimpleNamespace(
        fact_indices=(0,), per_candidate_best_level=("L1", "L1", "L1"),
        granularity_risk_incidences=0, scoped_empirical_incidences=0,
        local_candidate_pool_anonymity_count=1,
        local_candidate_pool_anonymity_ratio=1 / (pool + 1),
        direct_identifier_flag=True, rationale_min_level="L1")
    selection = SimpleNamespace(
        distractors=distractors, rationale=rationale, positions=(0, 1, 2),
        minimum_rationale_size=1, minimum_rationale_level="L1",
        evidence_policy="main-l1", search_scope="FULL_EXACT",
        mcq_evidence_level="MCQ-L1")
    quality = SimpleNamespace(
        predicate_uri="http://dbpedia.org/property/almaMater", direction="OUT",
        counterpart_uri=R + "Kobe_University", display_label="Kobe University")
    case = SimpleNamespace(facts=(SimpleNamespace(
        quality=quality, levels=("L1",) * 3, exclusion_bases=("NONE",) * 3,
        granularity_risks=("NONE",) * 3),))
    return anyb2.AnswerRunResult(
        original_uri=R + uri, status=S.SUCCESS_FULL_EXACT, display_label=uri,
        selected_class_uri=C + "Japanese_Nobel_laureates",
        complete_pool_size=pool, case=case, selection=selection,
        identity=SimpleNamespace(local_kg_uri=R + uri, remote_query_uri=R + uri,
                                 local_index=1, local_resolution_method="X",
                                 remote_redirect_status="NO_REDIRECT"),
        semantic_index_available=True)


def test_the_table_has_one_row_per_answer_including_failures():
    results = [_successful_result(),
               anyb2.AnswerRunResult(original_uri=R + "Broken",
                                     status=S.NO_LOCAL_URI_IDENTITY)]
    table = anyb2.summary_table(results)
    body = [line for line in table.splitlines() if line.startswith("| 1 ")
            or line.startswith("| 2 ")]
    assert len(body) == 2
    assert "NO_LOCAL_URI_IDENTITY" in table


def test_a_failure_stays_in_the_denominator():
    results = [_successful_result(),
               anyb2.AnswerRunResult(original_uri=R + "Broken",
                                     status=S.NO_LOCAL_URI_IDENTITY)]
    prose = anyb2.prose_summary(results)
    assert "Total Answers attempted            : 2" in prose
    assert "Successful (distractors selected)  : 1" in prose
    assert "NO_LOCAL_URI_IDENTITY" in prose


def test_the_anonymity_denominator_is_one_plus_the_complete_pool():
    table = anyb2.summary_table([_successful_result(pool=24)])
    assert "1/25" in table


def test_the_main_column_requires_a_student_showable_policy():
    showable = _successful_result()
    assert showable.has_main_l1_selection
    assert "✔" in anyb2.summary_table([showable])

    diagnostic = _successful_result()
    diagnostic.selection.evidence_policy = "diagnostic-l0"
    diagnostic.selection.mcq_evidence_level = "MCQ-L0"
    assert diagnostic.has_main_l1_selection is False
    assert "✔" not in anyb2.summary_table([diagnostic])


def test_l0_is_never_counted_as_a_student_showable_selection():
    diagnostic = _successful_result()
    diagnostic.status = S.NO_MAIN_L1_SELECTION
    diagnostic.selection.evidence_policy = "diagnostic-l0"
    diagnostic.selection.mcq_evidence_level = "MCQ-L0"
    prose = anyb2.prose_summary([diagnostic])
    assert "Diagnostic L0 only (not showable)  : 1" in prose
    assert "Successful (distractors selected)  : 0" in prose


def test_the_basis_column_does_not_present_scoped_empirical_as_a_level():
    result = _successful_result()
    result.case.facts[0].exclusion_bases = ("SCOPED_EMPIRICAL",) * 3
    table = anyb2.summary_table([result])
    assert "SCOPED_EMPIRICAL" in table
    assert "MCQ-SCOPED_EMPIRICAL" not in table


def test_the_answer_column_shows_the_original_and_the_resolved_spelling():
    result = _successful_result(uri="Akira_Suzuki")
    result.identity.local_kg_uri = R + "Akira_Suzuki_(chemist)"
    table = anyb2.summary_table([result])
    assert "Akira Suzuki → Akira Suzuki (chemist)" in table


# ===========================================================================
# G) Frozen science
# ===========================================================================


def test_the_pinned_lrolesim_execution_is_exactly_the_journal_2_configuration():
    assert mcq_inputs.PINNED_LROLESIM_EXECUTION == {
        "ranker_name": "lrolesim_m1_fixed_k3",
        "measure": "lrolesim_ed",
        "lrolesim_beta": 0.2,
        "iterations": 3,
        "iteration_mode": "fixed",
    }


def test_no_convergence_mode_ranker_can_enter_the_new_runner():
    """`src/MCQ_lrolesim.py` is the direct command-line convergence mode.

    It must not be importable from this path: the Journal-2 scoring path is the
    validated adapter driving MCQ_lrolesim_ClaudeWeb_v2 with three FIXED
    iterations.
    """
    for path in (SCRIPTS_DIR / "run_phase_b2_any_answer_v2.py",
                 SRC_DIR / "pipeline" / "phase_b2_any_answer_run.py"):
        source = path.read_text("utf-8")
        assert not re.search(r"^\s*(import|from)\s+MCQ_lrolesim\b", source,
                             re.MULTILINE), path


def test_the_kernel_entry_point_is_build_and_select():
    source = (SCRIPTS_DIR / "run_phase_b2_any_answer_v2.py").read_text("utf-8")
    assert "mcq_inputs.build_and_select(" in source
    # The kernel's own internals are never called directly from the driver.
    assert "select_distractors(" not in source
    assert "build_case(" not in source


def test_the_b2b_driver_is_not_modified_by_this_task():
    """`scripts/run_phase_b2_answer.py` remains the historical B2-B evidence."""
    import hashlib

    digest = hashlib.sha256(
        (SCRIPTS_DIR / "run_phase_b2_answer.py").read_bytes()).hexdigest()
    assert digest == (
        "d4259fc6f24a1d948f39bd58993e6877c58ee6986ac3e3718b94a3195cc3a349")


def test_the_class_approval_status_records_the_alpha_and_denies_human_approval():
    status = anyb2.class_approval_status(0.7)
    assert "0P7" in status
    assert "NOT_HUMAN_APPROVED" in status
    assert status != "HUMAN_APPROVED"


def test_the_local_mapping_gate_is_the_declared_ten():
    assert b2.LOCAL_MAPPING_GATE == 10
