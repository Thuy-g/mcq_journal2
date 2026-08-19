############################################################################
# tests/test_class_leakage.py
#
# Tests for src/classes/class_leakage.py — the CLASS-ONLY derivational /
# eponymic leakage rule composed on top of the frozen R1 rule — and for the
# leakage-provenance repair in src/category_extractor_v6.py.
#
# EVERY TEST IS OFFLINE. No network, no model, no pinned pickle. The only file
# read is the SHA-256-pinned predicate policy, which is what the frozen rule
# already reads.
############################################################################

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import category_extractor_v6 as v6  # noqa: E402
from classes import class_leakage as cl  # noqa: E402
from rationale_v3.quality import detect_answer_leakage  # noqa: E402

RESOURCE = "http://dbpedia.org/resource/"
CATEGORY = "http://dbpedia.org/resource/Category:"


@pytest.fixture(scope="module")
def policy():
    return v6.load_r1_leakage_policy()


# ---------------------------------------------------------------------------
# 1) The bounded edit distance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("a,b,expected", [
    ("aristotle", "aristotle", 0),
    ("aristotle", "aristotel", 1),      # one ADJACENT TRANSPOSITION
    ("aristotle", "aristotl", 1),       # one deletion
    ("aristotle", "aristotles", 1),     # one insertion
    ("aristotle", "aristotla", 1),      # one substitution
    ("aristotle", "aristot", 2),        # two edits -> reported as limit + 1
    ("carbon", "boron", 2),
])
def test_bounded_damerau_levenshtein(a, b, expected):
    assert cl.bounded_damerau_levenshtein(a, b, 1) == expected


def test_the_transposition_case_is_why_plain_levenshtein_would_not_do():
    """`aristotle` -> `aristotel` is one transposition and two substitutions.

    Optimal string alignment counts it as ONE edit; plain Levenshtein counts
    two. The whole Aristotle repair depends on the transposition being admitted,
    so it is asserted explicitly rather than left implicit in a table.
    """
    assert cl.bounded_damerau_levenshtein("aristotle", "aristotel", 1) == 1
    assert cl.bounded_damerau_levenshtein("aristotle", "aristotel", 0) == 1  # > 0


# ---------------------------------------------------------------------------
# 2) The required regression: Aristotle / Aristotelian
# ---------------------------------------------------------------------------


def test_aristotelian_philosophers_is_a_hard_class_leak(policy):
    verdict = cl.classify_class_leakage_extended(
        RESOURCE + "Aristotle", RESOURCE + "Aristotelian_philosophers", policy)
    assert verdict.level == cl.LEAK_HARD
    assert verdict.source == cl.LEAK_SOURCE_DERIVATIONAL
    assert verdict.changed_by_class_rule
    assert any("CLASS_DERIVATIONAL_IAN" in e for e in verdict.derivational_evidence)


def test_the_frozen_r1_rule_still_calls_that_pair_soft(policy):
    """R1 is UNCHANGED. The class rule is composed on top, never merged in.

    If this ever starts failing, the frozen rationale rule has been modified and
    every rationale verdict in the project has moved with it.
    """
    result = detect_answer_leakage(
        RESOURCE + "Aristotle", RESOURCE + "Aristotelian_philosophers", policy)
    assert result.soft_leak is True
    assert result.hard_leak is False
    level, _, _ = cl.classify_r1_only(
        RESOURCE + "Aristotle", RESOURCE + "Aristotelian_philosophers", policy)
    assert level == cl.LEAK_SOFT


def test_the_doctrine_name_needs_two_derivation_steps(policy):
    """`Aristotelianism` = Aristotle + -ian + -ism, so one strip is not enough.

    A single strip leaves "aristotelian", which is three edits from "aristotle"
    and correctly refused. The second strip reaches "aristotel", one adjacent
    transposition away. Asserted together with the depth-1 refusal so the reason
    the depth exists cannot be lost.
    """
    verdict = cl.classify_class_leakage_extended(
        RESOURCE + "Aristotle", RESOURCE + "Aristotelianism", policy)
    assert verdict.level == cl.LEAK_HARD
    assert any("ISM_IAN" in e for e in verdict.derivational_evidence)

    shallow = cl.DerivationalPolicy(maximum_derivation_depth=1)
    assert cl.classify_class_leakage_extended(
        RESOURCE + "Aristotle", RESOURCE + "Aristotelianism", policy,
        derivational=shallow).level == cl.LEAK_SOFT


def test_confucianism_is_the_same_shape(policy):
    verdict = cl.classify_class_leakage_extended(
        RESOURCE + "Confucius", RESOURCE + "Confucianism", policy)
    assert verdict.level == cl.LEAK_HARD
    assert verdict.changed_by_class_rule


def test_the_stem_floor_applies_at_every_derivation_step():
    """What actually bounds the depth: no step may produce a short root.

    Checked on the stem generator directly, because that is where the bound
    lives. `germanic` may reach `german` and must never reach `germ`;
    `buddhism` may reach nothing at all.
    """
    policy = cl.DEFAULT_DERIVATIONAL_POLICY
    german = {stem for stem, _ in cl._derivational_stems("germanic", policy)}
    assert "german" in german
    assert "germ" not in german

    assert cl._derivational_stems("buddhism", policy) == ()      # "buddh" is 5
    assert cl._derivational_stems("sulfite", policy) == ()       # "sulf" is 4
    assert cl._derivational_stems("nitrite", policy) == ()       # "nitr" is 4

    platon = {stem for stem, _ in cl._derivational_stems("platonism", policy)}
    assert platon == {"platon"}                                  # cannot go deeper

    aristotle = {stem for stem, _ in
                 cl._derivational_stems("aristotelianism", policy)}
    assert "aristotelian" in aristotle and "aristotel" in aristotle


@pytest.mark.parametrize("answer,category", [
    ("Buddha", "Buddhism"),               # no admissible stem exists at all
    ("Plato", "Platonism"),               # already HARD under the frozen rule
])
def test_the_extra_depth_changes_nothing_for_these(answer, category, policy):
    verdict = cl.classify_class_leakage_extended(
        RESOURCE + answer, RESOURCE + category, policy)
    assert verdict.level == verdict.r1_level


def test_aristotle_against_itself_is_hard_under_r1_alone(policy):
    verdict = cl.classify_class_leakage_extended(
        RESOURCE + "Aristotle", RESOURCE + "Aristotle", policy)
    assert verdict.level == cl.LEAK_HARD
    assert verdict.r1_level == cl.LEAK_HARD
    assert verdict.source == cl.LEAK_SOURCE_R1
    assert verdict.changed_by_class_rule is False
    assert "aristotle~aristotle:WHOLE_TOKEN" in verdict.evidence


# ---------------------------------------------------------------------------
# 3) The false-positive protections that must survive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("answer,category", [
    ("Carbon", "Boron_carbide"),          # the frozen CE-11 protection
    ("Nitrogen", "Nitrites"),             # stem "nitr" is below the floor
    ("Sulfur", "Sulfites"),               # stem "sulf" is below the floor
    ("Carbon", "Carbide_minerals"),
])
def test_short_chemical_roots_do_not_become_hard(answer, category, policy):
    """The class rule must not turn a shared chemical root into a rejection.

    Every pair here shares a prefix with the Answer and every one of them is a
    legitimate candidate-source class. `-ate` and `-ide` are absent from the
    suffix list and the six-character stem floor removes `nitr` and `sulf`, so
    the extension contributes nothing and R1's verdict stands.
    """
    verdict = cl.classify_class_leakage_extended(
        RESOURCE + answer, RESOURCE + category, policy)
    assert verdict.level != cl.LEAK_HARD
    assert verdict.derivational_evidence == ()
    assert verdict.changed_by_class_rule is False


@pytest.mark.parametrize("answer,category", [
    ("Albert_Einstein", "German_relativity_theorists"),
    ("Shinya_Yamanaka", "Japanese_Nobel_laureates"),
    ("Aristotle", "Ancient_Greek_philosophers"),
    ("Silicon", "Metalloids"),
])
def test_unrelated_class_names_stay_clean(answer, category, policy):
    verdict = cl.classify_class_leakage_extended(
        RESOURCE + answer, RESOURCE + category, policy)
    assert verdict.level == cl.LEAK_NONE
    assert verdict.status == cl.LEAK_STATUS_EVALUATED


def test_einstein_family_remains_hard(policy):
    verdict = cl.classify_class_leakage_extended(
        RESOURCE + "Albert_Einstein", RESOURCE + "Einstein_family", policy)
    assert verdict.level == cl.LEAK_HARD
    assert verdict.r1_level == cl.LEAK_HARD


def test_the_extension_can_only_raise_a_verdict(policy):
    """Composition is monotone: HARD stays HARD, and nothing is ever cleared.

    Swept over a spread of Answer/class pairs so the property is checked as a
    property rather than asserted case by case.
    """
    strengths = {cl.LEAK_NONE: 0, cl.LEAK_SOFT: 1, cl.LEAK_HARD: 2}
    answers = ["Aristotle", "Carbon", "Silicon", "Sulfuric_acid", "Plato",
               "Albert_Einstein", "Socrates", "Tokugawa_Ieyasu", "Xun_Kuang"]
    classes = ["Aristotelian_philosophers", "Aristotle", "Boron_carbide",
               "Carbonate_minerals", "Silicon_compounds", "Mineral_acids",
               "Platonists", "Einstein_family", "Socratic_dialogues",
               "Japanese_Nobel_laureates", "Ancient_Greek_philosophers"]
    for answer in answers:
        for category in classes:
            verdict = cl.classify_class_leakage_extended(
                RESOURCE + answer, RESOURCE + category, policy)
            assert strengths[verdict.level] >= strengths[verdict.r1_level], (
                answer, category)


# ---------------------------------------------------------------------------
# 4) The rule is generic — no entity-specific branch in the executable source
# ---------------------------------------------------------------------------


def test_the_source_contains_no_entity_specific_branch():
    """`grep -i aristotle` over the executable lines must find nothing.

    The prompt's scientific safety condition: a rule that special-cases the one
    example it was written for is not a rule. Comments and docstrings are
    stripped before the search, because explaining WHY the rule exists requires
    naming the case that exposed the gap.
    """
    source = (SRC_DIR / "classes" / "class_leakage.py").read_text("utf-8")
    code_only = []
    in_docstring = False
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.count('"""') == 1:
            in_docstring = not in_docstring
            continue
        if in_docstring or stripped.startswith("#") or stripped.startswith('"""'):
            continue
        code_only.append(line.split("#", 1)[0])
    text = "\n".join(code_only).lower()
    for name in ("aristotle", "aristotelian", "socrates", "einstein", "carbon",
                 "plato", "xun_kuang", "akira"):
        assert name not in text, f"entity-specific branch on {name!r}"


def test_no_model_library_is_imported():
    """Structural guarantee, not a promise: WordNet, spaCy, transformers and any
    LLM client are absent from the import graph of the leakage rule."""
    source = (SRC_DIR / "classes" / "class_leakage.py").read_text("utf-8")
    for banned in ("nltk", "wordnet", "spacy", "sentence_transformers", "torch",
                   "openai", "anthropic", "transformers"):
        assert not re.search(rf"^\s*(import|from)\s+{banned}\b", source,
                             re.MULTILINE), banned


def test_the_suffix_list_excludes_the_chemical_nomenclature_suffixes():
    """`-ate`, `-ide`, `-ine`, `-ane`, `-ene`, `-ol` must never be admitted.

    Admitting any of them folds every salt, oxide and halide onto its element
    root and rejects legitimate chemistry classes wholesale.
    """
    for banned in ("ate", "ide", "ine", "ane", "ene", "ol", "yl"):
        assert banned not in cl.DERIVATIONAL_SUFFIXES


# ---------------------------------------------------------------------------
# 5) The selector-level provenance repair
# ---------------------------------------------------------------------------


class _CategoryClient:
    """A fake endpoint that serves one Answer's categories and their sizes."""

    endpoint = "https://fake.example/sparql"

    def __init__(self, label, categories, counts):
        self.label = label
        self.categories = tuple(categories)
        self.counts = dict(counts)

    def run(self, query):
        qid = v6.query_id(query)
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


def _aristotle_features(policy):
    categories = [CATEGORY + "Aristotle",
                  CATEGORY + "Aristotelian_philosophers",
                  CATEGORY + "Ancient_Greek_philosophers",
                  CATEGORY + "Living_people"]
    counts = {CATEGORY + "Aristotle": 4,                     # too small
              CATEGORY + "Aristotelian_philosophers": 120,   # large enough
              CATEGORY + "Ancient_Greek_philosophers": 400,
              CATEGORY + "Living_people": 900_000}
    runner = v6.SparqlRunner(
        client=_CategoryClient("Aristotle", categories, counts))
    universe = v6.IdfUniverse(total_entities=6_000_000, definition="TEST")
    return v6.extract_answer_features(
        RESOURCE + "Aristotle", runner=runner, idf_universe=universe,
        quality_policy=policy)


def _by_uri(features, local_name):
    return next(c for c in features.classes
                if c.category_uri == CATEGORY + local_name)


def test_a_size_rejected_class_still_reports_its_true_leakage(policy):
    """THE AUDIT BUG. `Category:Aristotle` is too small AND hard-leaking.

    Before this repair it was published as `leak_level = no_leak` because the
    size gate removed it before the leakage test ran — a scientifically false
    annotation on the one class a reviewer is most likely to check by hand.
    """
    feature = _by_uri(_aristotle_features(policy), "Aristotle")
    assert feature.rejected_code == v6.RejectCode.TOO_SMALL.value
    assert feature.leak_level is v6.LeakLevel.HARD
    assert feature.leak_status is v6.LeakStatus.EVALUATED
    assert "aristotle~aristotle:WHOLE_TOKEN" in feature.leak_evidence
    # Both independent reasons survive; neither displaces the other.
    assert set(feature.rejection_reasons) == {
        v6.RejectCode.TOO_SMALL.value, v6.RejectCode.HARD_LEAK.value}
    assert feature.primary_rejected_code == v6.RejectCode.TOO_SMALL.value


def test_the_eponymic_class_is_not_feasible(policy):
    feature = _by_uri(_aristotle_features(policy), "Aristotelian_philosophers")
    assert feature.feasible is False
    assert feature.rejected_code == v6.RejectCode.HARD_LEAK.value
    assert feature.leak_level is v6.LeakLevel.HARD
    assert feature.r1_leak_level is v6.LeakLevel.SOFT   # what R1 alone said
    assert feature.leak_changed_by_class_rule is True
    assert feature.leak_source == cl.LEAK_SOURCE_DERIVATIONAL


def test_the_clean_class_survives_and_is_ranked(policy):
    features = _aristotle_features(policy)
    feasible = [c.category_uri for c in features.feasible_classes]
    assert feasible == [CATEGORY + "Ancient_Greek_philosophers"]
    ranking = v6.rank_feasible_classes(features, v6.DEFAULT_ALPHA)
    assert ranking.top_ranked_class == CATEGORY + "Ancient_Greek_philosophers"


def test_every_class_with_an_adaptable_uri_is_evaluated(policy):
    """Including administrative ones. `no_leak` never means "not evaluated"."""
    features = _aristotle_features(policy)
    for feature in features.classes:
        assert feature.leak_status is v6.LeakStatus.EVALUATED, feature.category_uri


def test_an_unadaptable_category_uri_is_stamped_not_evaluated(policy):
    # A category URI on a FOREIGN host: it satisfies no allowed prefix, so
    # `normalize_category` refuses it and no leakage comparison is possible.
    categories = ["http://example.org/resource/Category:Aristotelian_philosophers",
                  CATEGORY + "Ancient_Greek_philosophers"]
    counts = {CATEGORY + "Ancient_Greek_philosophers": 400}
    runner = v6.SparqlRunner(
        client=_CategoryClient("Aristotle", categories, counts))
    universe = v6.IdfUniverse(total_entities=6_000_000, definition="TEST")
    features = v6.extract_answer_features(
        RESOURCE + "Aristotle", runner=runner, idf_universe=universe,
        quality_policy=policy)
    invalid = next(c for c in features.classes
                   if c.rejected_code == v6.RejectCode.INVALID_URI.value)
    assert invalid.leak_status is v6.LeakStatus.NOT_EVALUATED
    assert invalid.leak_source == cl.LEAK_SOURCE_NOT_EVALUATED
    # The level field still has to hold SOMETHING; the status is what a reader
    # must branch on, and it says the rules never ran.
    assert invalid.leak_level is v6.LeakLevel.NONE


def test_rationale_r1_leakage_rule_is_untouched():
    """The frozen rationale LEAKAGE rule must not have been edited.

    Pinned by digest rather than by inspection: the whole scientific argument
    for adding a SECOND rule instead of widening R1 is that R1's behaviour is
    unchanged, and a digest is the only form of that claim which cannot rot.

    THE DIGEST IS NOW OVER THE RULE, NOT OVER THE WHOLE FILE.
      Prompt 8H-B2-E §12 added a direction-aware pedagogical tier table to
      `rationale_v3.quality`, which changed the file digest
      (4622755938056004ff5631cb5eb1c667bac4366a2da5948e8f85065c8c74cd21 ->
      cf276fbc8419bd1c09f4d3a3f43c42f05a905c80cad5bbe7722fedbeb370ff9b) while
      touching no line of the leakage rule. A whole-file digest could no longer
      distinguish "somebody edited the leakage rule" from "somebody added a tier
      table", so the pin moved to the six functions that ARE the rule. That is a
      sharper claim than the one it replaces, not a weaker one: the file digest
      would also have passed if the tier edit had quietly changed
      `_plural_stem`, and this one would not.
    """
    import hashlib
    import inspect

    from rationale_v3 import quality

    names = ("leakage_tokens", "_plural_stem", "_shared_prefix_length",
             "detect_answer_leakage", "local_name", "display_label")
    blob = "\n".join(inspect.getsource(getattr(quality, name))
                     for name in names)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    assert digest == (
        "5d21c457daffb8aacaa64ce1767b3db7f08a48804142aef1cffb51bb978fc7c5")


def test_the_r1_leakage_verdicts_are_behaviourally_frozen(policy):
    """A behavioural companion to the digest above, on the audit's own pairs."""
    from rationale_v3.quality import detect_answer_leakage

    expected = [
        ("Carbon", "Carbonado", True, False),        # AUDIT: hard
        ("Carbon", "Boron_carbide", False, True),    # AUDIT: soft, never hard
        ("Aristotle", "Aristotelian_philosophers", False, True),
        ("Silicon", "Black_silicon", True, False),
        ("Mao_Zedong", "Maoist_China", False, False),
    ]
    for answer, other, hard, soft in expected:
        result = detect_answer_leakage(RESOURCE + answer, RESOURCE + other,
                                       policy)
        assert result.hard_leak is hard, (answer, other)
        assert result.soft_leak is soft, (answer, other)


def test_the_class_rule_never_changes_a_rationale_verdict(policy):
    """The extension is CLASS-ONLY: it is not reachable from the rationale path.

    `rationale_v3.quality` must not import it, so no rationale counterpart can
    ever be judged by it.
    """
    source = (SRC_DIR / "rationale_v3" / "quality.py").read_text("utf-8")
    assert "class_leakage" not in source
