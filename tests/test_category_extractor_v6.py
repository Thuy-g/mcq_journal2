############################################################################
# tests/test_category_extractor_v6.py
#
# Tests for src/category_extractor_v6.py — the v6 automatic candidate-source
# class selector.
#
# NO TEST HERE TOUCHES THE NETWORK OR LOADS A MODEL. Every SPARQL response,
# Wikipedia lead and embedding is supplied by a fake, so the whole file runs
# offline and deterministically.
############################################################################

from __future__ import annotations

import ast
import importlib
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import category_extractor_v6 as v6  # noqa: E402
from classes import wikipedia_lead as wl  # noqa: E402
from rationale_v3.quality import detect_answer_leakage  # noqa: E402

RESOURCE = "http://dbpedia.org/resource/"
CATEGORY = "http://dbpedia.org/resource/Category:"

ANSWER_YAMANAKA = RESOURCE + "Shinya_Yamanaka"
ANSWER_EINSTEIN = RESOURCE + "Albert_Einstein"
ANSWER_CARBON = RESOURCE + "Carbon"
ANSWER_ADAM_SMITH = RESOURCE + "Adam_Smith"
ANSWER_PLATO = RESOURCE + "Plato"
ANSWER_SILICON = RESOURCE + "Silicon"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeSparqlClient:
    """A SPARQL client driven by ``#qid:`` markers, never by substring matching."""

    endpoint = "https://fake.example/sparql"

    def __init__(self, *, label=None, description=None, categories=(), counts=None,
                 universe=None, universe_status=None, fail=(), calls=None):
        self.label = label
        self.description = description
        self.categories = tuple(categories)
        self.counts = dict(counts or {})
        self.universe = universe
        self.universe_status = universe_status
        self.fail = set(fail)
        self.calls = calls if calls is not None else []

    def run(self, query: str) -> v6.QueryResult:
        qid = v6.query_id(query)
        self.calls.append(qid)
        if qid in self.fail:
            return v6.QueryResult(status=v6.QueryStatus.FAILED,
                                  error="injected failure", endpoint=self.endpoint)
        if qid == "answer_info":
            row = {}
            if self.label is not None:
                row["label"] = {"value": self.label}
            if self.description is not None:
                row["description"] = {"value": self.description}
            return self._ok([row] if row else [])
        if qid == "answer_categories":
            return self._ok([{"cat": {"value": c}} for c in self.categories])
        if qid == "category_counts":
            rows = []
            for uri in self.categories:
                if uri in self.counts:
                    rows.append({"cat": {"value": uri},
                                 "c": {"value": str(self.counts[uri])}})
            return self._ok(rows)
        if qid in ("idf_universe_category_filtered", "idf_universe_unfiltered"):
            if self.universe_status is not None and qid == "idf_universe_category_filtered":
                return v6.QueryResult(status=self.universe_status,
                                      rows=({"N": {"value": "12345"}},),
                                      endpoint=self.endpoint, sql_state="S1TAT",
                                      error="incomplete")
            if self.universe is None:
                return v6.QueryResult(status=v6.QueryStatus.FAILED,
                                      error="no universe", endpoint=self.endpoint)
            return self._ok([{"N": {"value": str(self.universe)}}])
        return self._ok([])

    def _ok(self, rows):
        rows = tuple(rows)
        return v6.QueryResult(
            status=v6.QueryStatus.OK if rows else v6.QueryStatus.ZERO_RESULTS,
            rows=rows, endpoint=self.endpoint)


class FakeEncoder:
    """A deterministic, offline stand-in for Sentence-BERT.

    Each text is embedded as a fixed 3-vector derived from character counts, so
    similarities are stable and reproducible without any model.
    """

    name = "fake-encoder"
    max_seq_length = 32

    def __init__(self):
        self.encoded_batches = []

    def encode(self, texts):
        self.encoded_batches.append(list(texts))
        vectors = []
        for text in texts:
            lowered = text.lower()
            vectors.append([
                1.0 + lowered.count("a"),
                1.0 + lowered.count("e"),
                1.0 + lowered.count("i"),
            ])
        return vectors


def make_lead(text="Shinya Yamanaka is a Japanese stem cell researcher.",
              answer_uri=ANSWER_YAMANAKA, status=wl.LeadStatus.OK, **kwargs):
    return wl.WikipediaLead(
        answer_uri=answer_uri, requested_title="Shinya Yamanaka", status=status,
        canonical_title="Shinya Yamanaka", page_id=11, revision_id=999,
        revision_timestamp="2026-01-01T00:00:00Z",
        lead_text=text if status is wl.LeadStatus.OK else None,
        lead_sha256=wl.sha256_text(text) if status is wl.LeadStatus.OK else None,
        character_length=len(text) if status is wl.LeadStatus.OK else 0,
        sentence_count=1 if status is wl.LeadStatus.OK else 0, **kwargs)


UNIVERSE = v6.IdfUniverse(total_entities=1_000_000,
                          definition=v6.UNIVERSE_EXPLICIT)


def make_runner(**kwargs):
    client = FakeSparqlClient(**kwargs)
    return v6.SparqlRunner(client=client, cache=v6.InMemorySparqlCache()), client


# ---------------------------------------------------------------------------
# 1) Import purity
# ---------------------------------------------------------------------------


def test_importing_the_module_performs_no_io_and_loads_no_model(tmp_path, monkeypatch):
    """Importing must not open a socket, create a file, or load a model.

    A module that touches the network at import cannot be unit tested offline,
    and a module that creates a cache file at import silently writes to the
    researcher's disk merely because a tool auto-imported it.
    """
    monkeypatch.chdir(tmp_path)
    for name in ("category_extractor_v6", "classes.wikipedia_lead"):
        sys.modules.pop(name, None)
    banned = {"sentence_transformers", "torch", "SPARQLWrapper", "nltk", "spacy"}
    already = {n for n in banned if n in sys.modules}
    importlib.import_module("category_extractor_v6")
    newly_imported = {n for n in banned if n in sys.modules} - already
    assert not newly_imported, f"import pulled in {newly_imported}"
    assert list(tmp_path.iterdir()) == []


def _executable_source(path: Path) -> str:
    """The module's EXECUTABLE text: no comments and no docstrings.

    Both source-inspection tests below must look at what the code DOES, not at
    the prose explaining why it does it — this file's module docstring
    deliberately discusses WordNet, spaCy and the Einstein regression at length.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", ())
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0]))
    kept = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and id(node) in docstrings:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            kept.append(node.value)
        elif isinstance(node, ast.Name):
            kept.append(node.id)
        elif isinstance(node, ast.Attribute):
            kept.append(node.attr)
        elif isinstance(node, ast.arg):
            kept.append(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kept.append(node.name)
        elif isinstance(node, ast.alias):
            kept.append(node.name + " " + (node.asname or ""))
        elif isinstance(node, ast.ImportFrom):
            kept.append(node.module or "")
    # A docstring's own Constant is still reachable through ast.walk, so drop
    # the ones registered above by value comparison.
    docstring_values = {
        body[0].value.value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef))
        for body in [getattr(node, "body", ())]
        if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str))}
    return "\n".join(k for k in kept if k not in docstring_values).lower()


def test_no_model_or_nlp_library_is_imported_by_the_module():
    """WordNet, spaCy, embeddings and LLM clients are not imported by this
    module at all, which makes 'no model participates in a HARD rejection'
    structural rather than a convention someone must remember."""
    tree = ast.parse((SRC_DIR / "category_extractor_v6.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("nltk", "spacy", "gensim", "openai", "anthropic", "transformers"):
        assert banned not in imported, f"{banned} must never be imported here"

    # sentence_transformers and requests may appear ONLY as lazy imports inside a
    # function body, never at module level: a top-level import would load HTTP
    # machinery (and possibly a model) merely because something imported this
    # module, which is what breaks offline unit testing.
    top_level: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level.add(node.module.split(".")[0])
    assert "sentence_transformers" not in top_level
    assert "requests" not in top_level


def test_the_hard_leakage_path_calls_only_the_frozen_r1_function():
    """The only leakage authority reachable from the selection path is R1."""
    executable = _executable_source(SRC_DIR / "category_extractor_v6.py")
    assert "detect_answer_leakage" in executable
    for banned in ("wordnet", "synonym_expander", "detect_leak"):
        assert banned not in executable, banned


# ---------------------------------------------------------------------------
# 2) Standard IDF
# ---------------------------------------------------------------------------


def test_standard_idf_is_the_conventional_log_n_over_nc():
    assert v6.standard_idf(100, 1000) == pytest.approx(math.log(10.0))
    assert v6.standard_idf(1, 1000) == pytest.approx(math.log(1000.0))
    assert v6.standard_idf(1000, 1000) == pytest.approx(0.0)


def test_standard_idf_refuses_a_non_positive_count_or_universe():
    """A silently defaulted N is exactly the failure v6 exists to remove."""
    with pytest.raises(ValueError):
        v6.standard_idf(0, 1000)
    with pytest.raises(ValueError):
        v6.standard_idf(10, 0)


def test_standard_idf_and_the_v5_scaled_idf_induce_the_same_ordering():
    """v5's log(N/n_c)/log(N) is this quantity divided by a positive constant.

    For a fixed N the two are strictly monotonic transformations of one another,
    so they order classes identically — which is why no ablation between them is
    run: an ablation could only ever measure floating-point noise.
    """
    n = 6_721_370
    counts = [1, 2, 7, 28, 240, 5000, 100_000, 1_000_000]
    standard = [v6.standard_idf(c, n) for c in counts]
    v5_scaled = [math.log(n / c) / math.log(n) for c in counts]
    assert sorted(range(len(counts)), key=lambda i: standard[i]) == \
        sorted(range(len(counts)), key=lambda i: v5_scaled[i])
    # And identical after the within-Answer rank normalisation both apply.
    assert v6.rank_normalize(standard) == pytest.approx(v6.rank_normalize(v5_scaled))


def test_idf_ordering_is_invariant_to_which_admissible_n_is_used():
    """With N fixed across a run, class ORDER depends only on n_c."""
    counts = [5, 50, 500, 5000]
    for n in (1_000_000, 6_000_000, 6_685_753, 6_721_370):
        values = [v6.standard_idf(c, n) for c in counts]
        assert values == sorted(values, reverse=True)
        assert v6.rank_normalize(values) == pytest.approx([1.0, 2 / 3, 1 / 3, 0.0])


# ---------------------------------------------------------------------------
# 3) Rank normalisation and alpha
# ---------------------------------------------------------------------------


def test_rank_normalize_is_deterministic_and_order_independent():
    values = [3.0, 1.0, 2.0, 2.0]
    assert v6.rank_normalize(values) == [1.0, 0.0, 0.5, 0.5]
    # Ties get the same value, so a permuted input yields a permuted output and
    # never a different mapping from value to normalised score.
    permuted = [2.0, 2.0, 3.0, 1.0]
    assert v6.rank_normalize(permuted) == [0.5, 0.5, 1.0, 0.0]
    assert v6.rank_normalize([]) == []
    assert v6.rank_normalize([7.0]) == [1.0]


@pytest.mark.parametrize("alpha", [-0.0001, 1.0001, 2, -1, float("nan")])
def test_invalid_alpha_is_rejected(alpha):
    with pytest.raises(ValueError):
        v6.validate_alpha(alpha)


@pytest.mark.parametrize("alpha", [0.0, 0.25, 0.5, 0.7, 0.75, 1.0])
def test_valid_alpha_is_accepted(alpha):
    assert v6.validate_alpha(alpha) == alpha


def test_default_alpha_is_a_neutral_one_half():
    assert v6.DEFAULT_ALPHA == 0.5


def test_sweep_alphas_are_exactly_the_requested_grid():
    assert v6.SWEEP_ALPHAS == (0.0, 0.25, 0.5, 0.7, 0.75, 1.0)


def test_combine_alpha_endpoints():
    assert v6.combine_alpha(0.9, 0.1, 0.0) == pytest.approx(0.1)
    assert v6.combine_alpha(0.9, 0.1, 1.0) == pytest.approx(0.9)
    assert v6.combine_alpha(0.9, 0.1, 0.5) == pytest.approx(0.5)


def test_combine_alpha_falls_back_to_idf_when_the_semantic_feature_is_absent():
    """None means 'no feature', and the caller must stamp the fallback mode."""
    assert v6.combine_alpha(None, 0.42, 1.0) == pytest.approx(0.42)
    assert v6.combine_alpha(None, 0.42, 0.0) == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# 4) The frozen R1 hard-leakage gate
# ---------------------------------------------------------------------------

R1_HARD_CASES = [
    pytest.param(ANSWER_EINSTEIN, CATEGORY + "Einstein_family", "WHOLE_TOKEN",
                 id="albert_einstein-einstein_family"),
    pytest.param(ANSWER_CARBON, CATEGORY + "Carbonado", "LONG_PREFIX",
                 id="carbon-carbonado"),
    pytest.param(ANSWER_ADAM_SMITH, CATEGORY + "Smithsonian_Institution",
                 "LONG_PREFIX", id="adam_smith-smithsonian_institution"),
    pytest.param(ANSWER_PLATO, CATEGORY + "Platonists", "LONG_PREFIX",
                 id="plato-platonists"),
]

R1_NOT_HARD_CASES = [
    pytest.param(ANSWER_CARBON, CATEGORY + "Boron_carbide", id="carbon-boron_carbide"),
    pytest.param(ANSWER_EINSTEIN, CATEGORY + "Mileva_Mari%C4%87",
                 id="einstein-mileva_maric"),
    pytest.param(ANSWER_SILICON, CATEGORY + "Boron", id="silicon-boron"),
]


@pytest.mark.parametrize("answer_uri, category_uri, expected_kind", R1_HARD_CASES)
def test_v5_named_leakage_regressions_remain_hard_in_v6(answer_uri, category_uri,
                                                        expected_kind):
    verdict = v6.classify_class_leakage(answer_uri, category_uri,
                                        policy=v6.load_r1_leakage_policy())
    assert verdict.level is v6.LeakLevel.HARD
    assert any(expected_kind in e for e in verdict.evidence), verdict.evidence


@pytest.mark.parametrize("answer_uri, category_uri", R1_NOT_HARD_CASES)
def test_v5_named_non_leakage_regressions_remain_non_hard_in_v6(answer_uri,
                                                                category_uri):
    verdict = v6.classify_class_leakage(answer_uri, category_uri,
                                        policy=v6.load_r1_leakage_policy())
    assert verdict.level is not v6.LeakLevel.HARD


@pytest.mark.parametrize(
    "answer_uri, category_uri",
    [(c.values[0], c.values[1]) for c in R1_HARD_CASES]
    + [(c.values[0], c.values[1]) for c in R1_NOT_HARD_CASES])
def test_v6_leakage_matches_the_direct_frozen_r1_function(answer_uri, category_uri):
    """Proves v6 REUSES R1 rather than reimplementing an equivalent rule."""
    policy = v6.load_r1_leakage_policy()
    adapted = v6.category_uri_to_resource_uri(category_uri)
    assert adapted is not None
    direct = detect_answer_leakage(answer_uri, adapted, policy)
    via_v6 = v6.classify_class_leakage(answer_uri, category_uri, policy=policy)
    expected = (v6.LeakLevel.HARD if direct.hard_leak
                else v6.LeakLevel.SOFT if direct.soft_leak else v6.LeakLevel.NONE)
    assert via_v6.level is expected
    assert via_v6.reason == direct.reason_code
    assert via_v6.source == v6.LEAKAGE_SOURCE_R1


def test_category_uri_adapter_drops_only_the_category_marker():
    assert (v6.category_uri_to_resource_uri(CATEGORY + "Einstein_family")
            == RESOURCE + "Einstein_family")
    assert (v6.category_uri_to_resource_uri("dbc:Einstein_family")
            == RESOURCE + "Einstein_family")
    assert (v6.category_uri_to_resource_uri("Category:Einstein_family")
            == RESOURCE + "Einstein_family")
    # A colon inside the local name is legitimate and survives.
    assert (v6.category_uri_to_resource_uri(CATEGORY + "Star_Trek:_Voyager_episodes")
            == RESOURCE + "Star_Trek:_Voyager_episodes")
    # Percent-encoding is copied byte-for-byte, never decoded or re-encoded.
    assert (v6.category_uri_to_resource_uri(CATEGORY + "Mileva_Mari%C4%87")
            == RESOURCE + "Mileva_Mari%C4%87")
    assert v6.category_uri_to_resource_uri("https://evil.example/resource/Category:X") is None
    assert v6.category_uri_to_resource_uri(None) is None


def test_classify_class_leakage_is_total_for_an_unadaptable_category():
    verdict = v6.classify_class_leakage(ANSWER_EINSTEIN, "not a uri",
                                        policy=v6.load_r1_leakage_policy())
    assert verdict.level is v6.LeakLevel.NONE


def test_einstein_family_is_hard_rejected_end_to_end():
    """The B2-A regression, now through the whole v6 feasibility pipeline."""
    cat_family = CATEGORY + "Einstein_family"
    cat_physicists = CATEGORY + "20th-century_German_physicists"
    runner, _ = make_runner(
        label="Albert Einstein", categories=(cat_family, cat_physicists),
        counts={cat_family: 40, cat_physicists: 300})
    features = v6.extract_answer_features(
        ANSWER_EINSTEIN, runner=runner, idf_universe=UNIVERSE)
    feasible = {c.category_uri for c in features.feasible_classes}
    rejected = {c.category_uri: c for c in features.rejected_classes}
    assert cat_family not in feasible
    assert rejected[cat_family].rejected_code == v6.RejectCode.HARD_LEAK.value
    assert rejected[cat_family].leak_source == v6.LEAKAGE_SOURCE_R1
    assert "einstein~einstein:WHOLE_TOKEN" in rejected[cat_family].leak_evidence
    assert cat_physicists in feasible


def test_executable_source_never_special_cases_the_einstein_string():
    """The gate must be a RULE, not a hard-coded exception for one Answer.

    Comments and docstrings are excluded from this check on purpose: the module
    docstring explains the Einstein regression at length, and that prose is the
    audit trail, not behaviour.
    """
    assert "einstein" not in _executable_source(SRC_DIR / "category_extractor_v6.py")


def test_soft_leakage_annotates_but_never_rejects():
    cat = CATEGORY + "Boron_carbide"
    runner, _ = make_runner(label="Carbon", categories=(cat,), counts={cat: 50})
    features = v6.extract_answer_features(ANSWER_CARBON, runner=runner,
                                          idf_universe=UNIVERSE)
    [candidate] = features.feasible_classes
    assert candidate.leak_level is v6.LeakLevel.SOFT
    assert candidate.feasible is True


# ---------------------------------------------------------------------------
# 5) The IDF universe
# ---------------------------------------------------------------------------


def test_explicit_total_entities_wins_and_issues_no_query():
    runner, client = make_runner(universe=42)
    universe = v6.resolve_idf_universe(runner, explicit_total=7_000_000)
    assert universe.total_entities == 7_000_000
    assert universe.definition == v6.UNIVERSE_EXPLICIT
    assert client.calls == [], "an explicit N must cost no query at all"


def test_a_partial_universe_count_is_never_accepted_as_a_measurement():
    """Virtuoso's incomplete COUNT must not become N.

    The measured behaviour on the live endpoint is exactly this: HTTP 206 /
    X-SQL-State S1TAT with a plausible-looking but truncated number.
    """
    runner, client = make_runner(universe=6_721_370,
                                 universe_status=v6.QueryStatus.PARTIAL)
    universe = v6.resolve_idf_universe(runner)
    assert universe.total_entities == 6_721_370
    assert universe.definition == v6.UNIVERSE_UNFILTERED_UPPER_BOUND
    filtered_attempt = universe.attempts[0]
    assert filtered_attempt["query_status"] == v6.QueryStatus.PARTIAL.value
    assert filtered_attempt["value"] is None
    assert client.calls == ["idf_universe_category_filtered",
                            "idf_universe_unfiltered"]


def test_no_n_is_invented_when_every_attempt_fails():
    """Neither 6,000,000 (v5's constant) nor 6,685,753 (the pinned local KG
    node count) may be substituted for a measurement that did not happen."""
    runner, _ = make_runner(universe=None)
    universe = v6.resolve_idf_universe(runner)
    assert universe.total_entities is None
    assert universe.definition == v6.UNIVERSE_UNAVAILABLE
    assert not universe.available
    assert "6000000" not in str(universe.to_dict())
    assert "6685753" not in str(universe.to_dict())


def test_scoring_refuses_when_no_idf_universe_is_available():
    cat = CATEGORY + "Japanese_Nobel_laureates"
    runner, _ = make_runner(label="Shinya Yamanaka", categories=(cat,),
                            counts={cat: 30})
    features = v6.extract_answer_features(
        ANSWER_YAMANAKA, runner=runner,
        idf_universe=v6.IdfUniverse(total_entities=None,
                                    definition=v6.UNIVERSE_UNAVAILABLE))
    assert features.status == v6.STATUS_IDF_UNAVAILABLE
    assert features.classes == ()


def test_the_universe_is_resolved_once_per_run_not_once_per_answer():
    """N is a property of the graph, not of an Answer.

    Resolving it per Answer would multiply a ~30-second query by the corpus size
    AND let N drift mid-run, making two Answers' IDF values incomparable.
    """
    cat = CATEGORY + "Japanese_Nobel_laureates"
    runner, client = make_runner(label="X", categories=(cat,), counts={cat: 30},
                                 universe=1_000_000)
    universe = v6.resolve_idf_universe(runner)
    calls_after_universe = list(client.calls)
    for uri in (ANSWER_YAMANAKA, ANSWER_EINSTEIN, ANSWER_CARBON):
        v6.extract_answer_features(uri, runner=runner, idf_universe=universe)
    per_answer_calls = client.calls[len(calls_after_universe):]
    assert not any(c.startswith("idf_universe") for c in per_answer_calls)


# ---------------------------------------------------------------------------
# 6) Semantic text: unavailability is not a cosine of zero
# ---------------------------------------------------------------------------


def test_missing_semantic_text_is_not_encoded_as_a_real_cosine_zero():
    cat = CATEGORY + "Japanese_Nobel_laureates"
    runner, _ = make_runner(label="Shinya Yamanaka", categories=(cat,),
                            counts={cat: 30})
    features = v6.extract_answer_features(
        ANSWER_YAMANAKA, runner=runner, idf_universe=UNIVERSE,
        wikipedia_lead=make_lead(status=wl.LeadStatus.PAGE_MISSING),
        encoder=FakeEncoder())
    [candidate] = features.feasible_classes
    assert candidate.raw_sbert is None, "must be absent, never 0.0"
    assert features.semantic.status is v6.SemanticStatus.UNAVAILABLE
    ranking = v6.rank_feasible_classes(features, alpha=0.7)
    assert ranking.ranked[0].normalized_sbert is None
    assert ranking.scoring_mode is v6.ScoringMode.IDF_ONLY_SEMANTIC_UNAVAILABLE


def test_a_genuine_zero_similarity_is_distinguishable_from_unavailability():
    """A real 0.0 is a measurement; None is the absence of one."""
    class OrthogonalEncoder(FakeEncoder):
        def encode(self, texts):
            return [[1.0, 0.0] if i == 0 else [0.0, 1.0]
                    for i, _ in enumerate(texts)]

    cat = CATEGORY + "Japanese_Nobel_laureates"
    runner, _ = make_runner(label="Shinya Yamanaka", categories=(cat,),
                            counts={cat: 30})
    features = v6.extract_answer_features(
        ANSWER_YAMANAKA, runner=runner, idf_universe=UNIVERSE,
        wikipedia_lead=make_lead(), encoder=OrthogonalEncoder())
    [candidate] = features.feasible_classes
    assert candidate.raw_sbert == pytest.approx(0.0)
    assert candidate.raw_sbert is not None
    ranking = v6.rank_feasible_classes(features, alpha=0.7)
    assert ranking.scoring_mode is v6.ScoringMode.RANK_FUSION


def test_no_encoder_is_reported_as_encoder_unavailable_not_as_zero():
    semantic = v6.SemanticText(source=v6.SemanticSource.WIKIPEDIA_LEAD,
                               status=v6.SemanticStatus.AVAILABLE, text="hello")
    similarities, metadata = v6.encode_semantic_similarity(None, semantic, ["a"])
    assert similarities is None
    assert metadata["reason"] == v6.SemanticStatus.ENCODER_UNAVAILABLE.value


def test_the_semantic_text_is_encoded_once_and_labels_once():
    cats = [CATEGORY + f"Class_{i}" for i in range(4)]
    runner, _ = make_runner(label="X", categories=tuple(cats),
                            counts={c: 30 + i for i, c in enumerate(cats)})
    encoder = FakeEncoder()
    v6.extract_answer_features(ANSWER_YAMANAKA, runner=runner,
                               idf_universe=UNIVERSE,
                               wikipedia_lead=make_lead(), encoder=encoder)
    assert len(encoder.encoded_batches) == 1, "one batched encode pass per Answer"


def test_chunking_keeps_every_sentence_and_never_truncates_the_cache():
    text = " ".join(f"Sentence number {i} about physics." for i in range(40))
    chunks = v6.chunk_text(text, max_tokens=20)
    assert len(chunks) > 1
    rejoined = " ".join(chunks)
    for i in range(40):
        assert f"Sentence number {i} about physics." in rejoined


def test_dbpedia_description_and_wikipedia_lead_are_never_mixed_in_one_run():
    cat = CATEGORY + "Japanese_Nobel_laureates"
    runner, _ = make_runner(label="Shinya Yamanaka",
                            description="Japanese stem cell researcher",
                            categories=(cat,), counts={cat: 30})
    lead = make_lead("A much longer Wikipedia lead paragraph about the Answer.")
    with_description = v6.extract_answer_features(
        ANSWER_YAMANAKA, runner=runner, idf_universe=UNIVERSE,
        semantic_source=v6.SemanticSource.DBPEDIA_DESCRIPTION,
        wikipedia_lead=lead, encoder=FakeEncoder())
    assert with_description.semantic.source is v6.SemanticSource.DBPEDIA_DESCRIPTION
    assert with_description.semantic.text == "Japanese stem cell researcher"
    # The Wikipedia lead was supplied and deliberately not used.
    assert with_description.semantic.wikipedia_title is None


# ---------------------------------------------------------------------------
# 7) Hard feasibility gates
# ---------------------------------------------------------------------------


def test_junk_categories_are_rejected_and_never_ranked():
    junk = CATEGORY + "Living_people"
    births = CATEGORY + "1962_births"
    good = CATEGORY + "Japanese_Nobel_laureates"
    runner, _ = make_runner(label="X", categories=(junk, births, good),
                            counts={junk: 900000, births: 4000, good: 30})
    features = v6.extract_answer_features(ANSWER_YAMANAKA, runner=runner,
                                          idf_universe=UNIVERSE)
    codes = {c.category_uri: c.rejected_code for c in features.rejected_classes}
    assert codes[junk] == v6.RejectCode.JUNK.value
    assert codes[births] == v6.RejectCode.JUNK.value
    assert [c.category_uri for c in features.feasible_classes] == [good]


def test_size_gates_use_eligible_count_below_and_full_count_above():
    """The Answer cannot be its own distractor, so the minimum applies to
    ``remote_count - 1``; the broad-category maximum applies to the full size."""
    tiny = CATEGORY + "Tiny_class"
    edge = CATEGORY + "Edge_class"
    huge = CATEGORY + "Huge_class"
    runner, _ = make_runner(label="X", categories=(tiny, edge, huge),
                            counts={tiny: 10, edge: 11, huge: 5001})
    features = v6.extract_answer_features(
        ANSWER_YAMANAKA, runner=runner, idf_universe=UNIVERSE,
        min_remote_candidates=10, max_remote_candidates=5000)
    codes = {c.category_uri: c.rejected_code for c in features.rejected_classes}
    assert codes[tiny] == v6.RejectCode.TOO_SMALL.value      # 10 - 1 = 9 < 10
    assert codes[huge] == v6.RejectCode.TOO_GENERIC.value    # 5001 > 5000
    assert [c.category_uri for c in features.feasible_classes] == [edge]


def test_a_failed_count_query_is_not_read_as_a_class_having_no_members():
    runner, _ = make_runner(label="X", categories=(CATEGORY + "A",),
                            counts={}, fail={"category_counts"})
    features = v6.extract_answer_features(ANSWER_YAMANAKA, runner=runner,
                                          idf_universe=UNIVERSE)
    assert features.status == v6.STATUS_QUERY_FAILED
    assert features.feasible_classes == ()


def test_an_answer_with_no_feasible_class_is_not_reported_as_missing_semantics():
    """Zero feasible classes and absent semantic text are opposite causes.

    Merging them would report a semantic-coverage gap that does not exist.
    """
    junk = CATEGORY + "Living_people"
    runner, _ = make_runner(label="X", categories=(junk,), counts={junk: 900000})
    features = v6.extract_answer_features(
        ANSWER_YAMANAKA, runner=runner, idf_universe=UNIVERSE,
        wikipedia_lead=make_lead(), encoder=FakeEncoder())
    assert features.status == v6.STATUS_ALL_REJECTED
    assert features.semantic.status is v6.SemanticStatus.AVAILABLE
    ranking = v6.rank_feasible_classes(features, alpha=0.5)
    assert ranking.ranked == ()
    assert ranking.scoring_mode is v6.ScoringMode.NO_FEASIBLE_CLASS


def test_a_missing_count_row_rejects_the_measurement_not_the_class():
    known = CATEGORY + "Known"
    unknown = CATEGORY + "Unknown"
    runner, _ = make_runner(label="X", categories=(known, unknown),
                            counts={known: 30})
    features = v6.extract_answer_features(ANSWER_YAMANAKA, runner=runner,
                                          idf_universe=UNIVERSE)
    codes = {c.category_uri: c.rejected_code for c in features.rejected_classes}
    assert codes[unknown] == v6.RejectCode.COUNT_UNAVAILABLE.value


def test_an_answer_with_no_categories_is_reported_not_crashed():
    runner, _ = make_runner(label="X", categories=())
    features = v6.extract_answer_features(ANSWER_YAMANAKA, runner=runner,
                                          idf_universe=UNIVERSE)
    assert features.status == v6.STATUS_NO_CATEGORIES


def test_partial_results_are_never_cached():
    cache = v6.InMemorySparqlCache()
    assert cache.put("k", {"query_status": v6.QueryStatus.PARTIAL.value}) is False
    assert cache.put("k", {"query_status": v6.QueryStatus.FAILED.value}) is False
    assert cache.put("k", {"query_status": v6.QueryStatus.OK.value,
                           "endpoint": "e", "response_json": "[]"}) is True


# ---------------------------------------------------------------------------
# 8) Ranking
# ---------------------------------------------------------------------------


def _three_class_features(encoder=None, lead=None):
    """Three classes whose IDF order and SBERT order deliberately disagree."""
    cats = [CATEGORY + "Aaaa_eee", CATEGORY + "Bbbb", CATEGORY + "Ciii"]
    runner, _ = make_runner(label="Shinya Yamanaka", categories=tuple(cats),
                            counts={cats[0]: 400, cats[1]: 40, cats[2]: 200})
    return v6.extract_answer_features(
        ANSWER_YAMANAKA, runner=runner, idf_universe=UNIVERSE,
        wikipedia_lead=lead, encoder=encoder)


def test_alpha_zero_reproduces_the_pure_idf_ranking():
    features = _three_class_features(encoder=FakeEncoder(), lead=make_lead())
    ranking = v6.rank_feasible_classes(features, alpha=0.0)
    by_idf = sorted(features.feasible_classes, key=lambda c: -c.raw_idf)
    assert [r.category_uri for r in ranking.ranked] == \
        [c.category_uri for c in by_idf]
    assert ranking.scoring_mode is v6.ScoringMode.IDF_ONLY_BY_ALPHA


def test_alpha_one_reproduces_the_pure_semantic_ranking():
    features = _three_class_features(encoder=FakeEncoder(), lead=make_lead())
    ranking = v6.rank_feasible_classes(features, alpha=1.0)
    by_sbert = sorted(features.feasible_classes, key=lambda c: -c.raw_sbert)
    assert [r.category_uri for r in ranking.ranked] == \
        [c.category_uri for c in by_sbert]
    assert ranking.scoring_mode is v6.ScoringMode.RANK_FUSION


def test_a_six_alpha_sweep_reuses_identical_raw_features():
    """Six rankings of the SAME observations, not six experiments."""
    features = _three_class_features(encoder=FakeEncoder(), lead=make_lead())
    frozen = {c.category_uri: (c.raw_idf, c.raw_sbert, c.remote_count)
              for c in features.feasible_classes}
    rankings = [v6.rank_feasible_classes(features, a) for a in v6.SWEEP_ALPHAS]
    for ranking in rankings:
        for entry in ranking.ranked:
            assert (entry.feature.raw_idf, entry.feature.raw_sbert,
                    entry.feature.remote_count) == frozen[entry.category_uri]
    assert {r.alpha for r in rankings} == set(v6.SWEEP_ALPHAS)


def test_ranking_performs_no_query_and_no_encoding():
    encoder = FakeEncoder()
    features = _three_class_features(encoder=encoder, lead=make_lead())
    batches_after_extraction = len(encoder.encoded_batches)
    for alpha in v6.SWEEP_ALPHAS:
        v6.rank_feasible_classes(features, alpha)
    assert len(encoder.encoded_batches) == batches_after_extraction


def test_ranking_is_independent_of_the_order_the_endpoint_returned_categories():
    cats = [CATEGORY + "Aaaa_eee", CATEGORY + "Bbbb", CATEGORY + "Ciii"]
    counts = {cats[0]: 400, cats[1]: 40, cats[2]: 200}
    orders = [tuple(cats), tuple(reversed(cats)), (cats[1], cats[2], cats[0])]
    results = []
    for order in orders:
        runner, _ = make_runner(label="Shinya Yamanaka", categories=order,
                                counts=counts)
        features = v6.extract_answer_features(
            ANSWER_YAMANAKA, runner=runner, idf_universe=UNIVERSE,
            wikipedia_lead=make_lead(), encoder=FakeEncoder())
        ranking = v6.rank_feasible_classes(features, alpha=0.5)
        results.append([(r.category_uri, round(r.combined_score, 12))
                        for r in ranking.ranked])
    assert results[0] == results[1] == results[2]


def test_exactly_tied_scores_break_by_category_uri():
    cats = [CATEGORY + "Zzz", CATEGORY + "Aaa"]
    runner, _ = make_runner(label="X", categories=tuple(cats),
                            counts={cats[0]: 100, cats[1]: 100})
    features = v6.extract_answer_features(ANSWER_YAMANAKA, runner=runner,
                                          idf_universe=UNIVERSE)
    ranking = v6.rank_feasible_classes(features, alpha=0.0)
    assert [r.category_uri for r in ranking.ranked] == [cats[1], cats[0]]


def test_rejected_classes_never_receive_a_feasible_rank():
    junk = CATEGORY + "Living_people"
    good = CATEGORY + "Japanese_Nobel_laureates"
    runner, _ = make_runner(label="X", categories=(junk, good),
                            counts={junk: 900000, good: 30})
    features = v6.extract_answer_features(ANSWER_YAMANAKA, runner=runner,
                                          idf_universe=UNIVERSE)
    ranking = v6.rank_feasible_classes(features, alpha=0.5)
    ranked_uris = {r.category_uri for r in ranking.ranked}
    assert junk not in ranked_uris
    assert all(r.feasible_rank >= 1 for r in ranking.ranked)
    assert [r.feasible_rank for r in ranking.ranked] == \
        list(range(1, len(ranking.ranked) + 1))


def test_ranks_are_contiguous_from_one():
    features = _three_class_features(encoder=FakeEncoder(), lead=make_lead())
    ranking = v6.rank_feasible_classes(features, alpha=0.5)
    assert [r.feasible_rank for r in ranking.ranked] == [1, 2, 3]


# ---------------------------------------------------------------------------
# 9) Query builders
# ---------------------------------------------------------------------------


def test_every_query_with_a_limit_also_has_an_order_by():
    queries = [
        v6.build_answer_info_query(ANSWER_YAMANAKA),
        v6.build_answer_categories_query(ANSWER_YAMANAKA),
        v6.build_category_counts_query([CATEGORY + "A"]),
        v6.build_idf_universe_query(),
        v6.build_idf_universe_query_unfiltered(),
    ]
    for query in queries:
        if "LIMIT" in query:
            assert "ORDER BY" in query, query
        assert v6.query_id(query), query


def test_unsafe_uris_are_refused_rather_than_escaped():
    for bad in ["http://x.example/a b", 'http://x.example/a"b',
                "http://x.example/a<b", "not-a-uri", ""]:
        with pytest.raises(ValueError):
            v6.build_answer_categories_query(bad)


def test_an_apostrophe_in_a_resource_uri_is_accepted():
    query = v6.build_answer_categories_query(RESOURCE + "Shin'ichirō_Tomonaga")
    assert "Shin'ichirō_Tomonaga" in query


def test_category_display_label_preserves_distinguishing_material():
    assert (v6.category_display_label(CATEGORY + "Iron(III)_compounds")
            == "Iron(III) compounds")
    assert (v6.category_display_label(CATEGORY + "Iron(II)_compounds")
            != v6.category_display_label(CATEGORY + "Iron(III)_compounds"))
    assert (v6.category_display_label(CATEGORY + "Mileva_Mari%C4%87")
            == "Mileva Marić")


# ---------------------------------------------------------------------------
# 10) The Wikipedia lead helper
# ---------------------------------------------------------------------------


def test_dbpedia_uri_to_wikipedia_title():
    assert wl.dbpedia_uri_to_wikipedia_title(ANSWER_EINSTEIN) == "Albert Einstein"
    assert (wl.dbpedia_uri_to_wikipedia_title(RESOURCE + "Shin%27ichir%C5%8D_Tomonaga")
            == "Shin'ichirō Tomonaga")
    assert wl.dbpedia_uri_to_wikipedia_title("http://example.com/x") is None
    assert wl.dbpedia_uri_to_wikipedia_title("") is None


def test_wikipedia_redirect_and_normalisation_are_resolved_and_recorded():
    payload = {"query": {
        "normalized": [{"from": "Sin-Itiro_Tomonaga", "to": "Sin-Itiro Tomonaga"}],
        "redirects": [{"from": "Sin-Itiro Tomonaga", "to": "Shin'ichirō Tomonaga"}],
        "pages": [{"pageid": 287410, "title": "Shin'ichirō Tomonaga",
                   "extract": "Shinichiro Tomonaga was a Japanese physicist.",
                   "revisions": [{"revid": 1366963671,
                                  "timestamp": "2026-07-31T02:42:35Z"}]}]}}
    [lead] = wl.parse_lead_response(payload, ["Sin-Itiro_Tomonaga"],
                                    {"Sin-Itiro_Tomonaga": "uri"})
    assert lead.status is wl.LeadStatus.OK
    assert lead.canonical_title == "Shin'ichirō Tomonaga"
    assert lead.normalized_from == "Sin-Itiro_Tomonaga"
    assert lead.redirected_from == "Sin-Itiro Tomonaga"
    assert lead.redirect_used is True
    assert lead.revision_id == 1366963671
    assert lead.page_id == 287410
    assert lead.lead_sha256 == wl.sha256_text(lead.lead_text)


def test_a_missing_page_is_data_and_a_failed_request_is_not():
    payload = {"query": {"pages": [{"title": "Nope", "missing": True}]}}
    [lead] = wl.parse_lead_response(payload, ["Nope"], {"Nope": "uri"})
    assert lead.status is wl.LeadStatus.PAGE_MISSING
    assert lead.available is False
    # A title the API omitted entirely is a REQUEST failure, not a finding.
    [other] = wl.parse_lead_response({"query": {"pages": []}}, ["Gone"],
                                     {"Gone": "uri"})
    assert other.status is wl.LeadStatus.REQUEST_FAILED


def test_an_empty_extract_is_empty_lead_not_ok():
    payload = {"query": {"pages": [{"pageid": 1, "title": "T", "extract": "   "}]}}
    [lead] = wl.parse_lead_response(payload, ["T"], {"T": "uri"})
    assert lead.status is wl.LeadStatus.EMPTY_LEAD
    assert lead.available is False


def test_the_lead_cache_preserves_revision_text_and_hash(tmp_path):
    cache = wl.WikipediaLeadCache(tmp_path / "leads.json")
    lead = make_lead()
    assert cache.put(lead) is True
    cache.save()
    reloaded = wl.WikipediaLeadCache(tmp_path / "leads.json").get(ANSWER_YAMANAKA)
    assert reloaded is not None
    assert reloaded.lead_text == lead.lead_text
    assert reloaded.lead_sha256 == lead.lead_sha256
    assert reloaded.revision_id == lead.revision_id
    assert reloaded.revision_timestamp == lead.revision_timestamp
    assert reloaded.canonical_title == lead.canonical_title
    assert reloaded.cache_status == "hit"


def test_a_failed_wikipedia_request_is_never_cached(tmp_path):
    cache = wl.WikipediaLeadCache(tmp_path / "leads.json")
    failed = wl.WikipediaLead(answer_uri="u", requested_title="t",
                              status=wl.LeadStatus.REQUEST_FAILED, error="boom")
    assert cache.put(failed) is False
    assert len(cache) == 0


def test_the_lead_client_makes_no_request_without_the_network_gate():
    class ExplodingTransport:
        def get(self, endpoint, params):
            raise AssertionError("no request may be made with the gate closed")

    client = wl.WikipediaLeadClient(transport=ExplodingTransport(),
                                    allow_network=False)
    results = client.fetch_many([ANSWER_EINSTEIN])
    assert results[ANSWER_EINSTEIN].status is wl.LeadStatus.REQUEST_FAILED
    assert "network access is not enabled" in results[ANSWER_EINSTEIN].error


def test_the_lead_client_serves_cached_answers_without_any_request(tmp_path):
    cache = wl.WikipediaLeadCache(tmp_path / "leads.json")
    cache.put(make_lead())

    class CountingTransport:
        def __init__(self):
            self.calls = 0

        def get(self, endpoint, params):
            self.calls += 1
            raise AssertionError("cached Answers must cost no request")

    transport = CountingTransport()
    client = wl.WikipediaLeadClient(transport=transport, cache=cache,
                                    allow_network=True)
    results = client.fetch_many([ANSWER_YAMANAKA])
    assert results[ANSWER_YAMANAKA].available
    assert transport.calls == 0
    assert client.stats()["cache_hits"] == 1
