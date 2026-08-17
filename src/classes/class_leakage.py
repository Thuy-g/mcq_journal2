############################################################################
# src/classes/class_leakage.py
#
# CLASS-ONLY leakage: is a candidate-source CLASS LABEL answer-revealing?
#
# WHY THIS MODULE EXISTS AT ALL
# -----------------------------
# `rationale_v3.quality.detect_answer_leakage` ("R1") is the frozen lexical
# leakage rule of this project and it is NOT modified here, imported only, and
# called unchanged. R1 was specified and measured for RATIONALE COUNTERPARTS —
# the object of a fact that will be shown to a learner as a reason. Its HARD
# threshold requires BOTH a shared prefix of at least `minimum_prefix_length`
# characters AND that one complete token be a prefix of the other:
#
#     Carbon      / Carbonado          hard  (shared "carbon", 6, prefix-of)
#     Carbon      / Boron_carbide      soft  (shared "carb", 4, prefix of neither)
#
# That second condition is exactly right for a counterpart URI and exactly
# insufficient for a CLASS NAME. Measured on the Prompt 8H-B2-C run:
#
#     Answer  http://dbpedia.org/resource/Aristotle
#     Class   Category:Aristotelian_philosophers        R1 verdict: SOFT
#             evidence  aristotle~aristotelian:SHORT_PREFIX
#
# "aristotle" and "aristotelian" share nine characters but neither is a prefix
# of the other ("aristotle"[7:] is "le", "aristotelian"[7:] is "elian"), so R1
# is behaving exactly as specified. Nevertheless a question whose candidate
# pool is drawn from "Aristotelian philosophers" hands the learner the Answer in
# the class name itself. A rule written for one artefact does not automatically
# transfer to a different artefact, and the honest repair is a SECOND, CLASS-ONLY
# rule rather than a quiet widening of R1 that would change every rationale
# verdict in the project at the same time.
#
# WHAT THE CLASS-ONLY RULE ADDS, AND WHAT IT DELIBERATELY CANNOT ADD
# ------------------------------------------------------------------
# It adds ONE narrow family: a DERIVATIONAL / EPONYMIC form, i.e. a token built
# by attaching a small, explicitly listed English derivational suffix to a stem
# that is (almost) the other token.
#
#   Aristotle  ->  Aristotel + -ian     "aristotel" vs "aristotle": one adjacent
#                                       transposition, so the stem was MODIFIED
#   Socrates   ->  Socrat    + -ic      "socrat" vs plural-stem("socrates")
#
# Crucially, this rule is nearly EMPTY on top of R1 by construction. Whenever a
# suffix attaches WITHOUT modifying the stem — Plato/Platonism, Japan/Japanese,
# German/Germanic, Carbon/Carbonic — the derived token literally starts with the
# Answer token, so R1's LONG_PREFIX branch has already returned HARD and this
# module changes nothing. The only verdicts it can move are the ones where the
# derivation ALTERED the stem, which is precisely the gap the Aristotle case
# exposed. `class_leakage_delta_audit.csv` reports every moved verdict.
#
# WHY THE SUFFIX LIST IS SHORT AND WHY -ate / -ide / -ine ARE ABSENT
# -------------------------------------------------------------------
# The listed suffixes form adjectives and nouns from PROPER NAMES. The absent
# ones are the workhorses of chemical nomenclature: carbonate, sulfate,
# phosphate, oxide, chloride, carbide, chlorine, sulfite. Admitting "-ate" would
# fold every salt onto its element root and reject "Carbonate minerals" for the
# Answer "Carbon" on a purely orthographic coincidence, which is the exact
# over-sensitivity AUDIT item CE-11 records as a past mistake. Two further guards
# keep the rule narrow:
#
#   * a stem shorter than MINIMUM_STEM_LENGTH characters is refused outright, so
#     sulfite -> "sulf" and nitrite -> "nitr" can never fire;
#   * the stem must be within MAXIMUM_STEM_EDIT_DISTANCE of the Answer token,
#     computed as a bounded Damerau-Levenshtein distance, so "one small spelling
#     adjustment" is the whole licence and nothing looser.
#
# NO MODELS, NO STEMMER, NO EXCEPTIONS TABLE
# -------------------------------------------
# No WordNet, no spaCy, no embeddings, no LLM, no Porter stemming, and no
# entity-specific branch: `grep -i aristotle` over this file finds only prose.
# The single stemming operation performed on the Answer side is
# `rationale_v3.quality._plural_stem`, the frozen light plural stem, imported
# rather than re-derived so that "one plural rule" stays true of the repository.
#
# IMPORT-TIME PURITY: no I/O, no network, no policy file read at import.
############################################################################

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

# The frozen R1 rule and its two frozen helpers. `_plural_stem` is private to
# `quality.py` and is imported ON PURPOSE: re-deriving "strip one light plural
# suffix, never below four characters" here would create a SECOND plural rule
# that could silently drift from the one every rationale verdict already uses.
from rationale_v3.quality import (
    QualityPolicy,
    _plural_stem,
    detect_answer_leakage,
    leakage_tokens,
)

__all__ = [
    "CLASS_LEAKAGE_POLICY_VERSION",
    "LEAK_NONE",
    "LEAK_SOFT",
    "LEAK_HARD",
    "LEAK_STATUS_EVALUATED",
    "LEAK_STATUS_NOT_EVALUATED",
    "LEAK_SOURCE_R1",
    "LEAK_SOURCE_DERIVATIONAL",
    "LEAK_SOURCE_NOT_EVALUATED",
    "DERIVATIONAL_SUFFIXES",
    "MINIMUM_STEM_LENGTH",
    "MAXIMUM_STEM_EDIT_DISTANCE",
    "DerivationalPolicy",
    "DEFAULT_DERIVATIONAL_POLICY",
    "ClassLeakVerdict",
    "bounded_damerau_levenshtein",
    "derivational_matches",
    "classify_r1_only",
    "classify_class_leakage_extended",
]

CLASS_LEAKAGE_POLICY_VERSION = "class_derivational_eponymic/1.0.0"

# The three verdict levels. Spelled as the SAME strings the v6 selector's
# `LeakLevel` enum already uses, so the two vocabularies cannot drift apart and
# no translation table is needed anywhere.
LEAK_NONE = "no_leak"
LEAK_SOFT = "soft_overlap"
LEAK_HARD = "hard_leak"

# Whether a verdict was computed at all. `no_leak` must NEVER be readable as
# "leakage was not evaluated": those two support opposite conclusions, and the
# Prompt 8H-B2-C output conflated them for every size-rejected class.
LEAK_STATUS_EVALUATED = "EVALUATED"
LEAK_STATUS_NOT_EVALUATED = "NOT_EVALUATED_UNADAPTABLE_CATEGORY_URI"

LEAK_SOURCE_R1 = "rationale_v3_r1"
LEAK_SOURCE_DERIVATIONAL = "class_derivational_eponymic_v1"
LEAK_SOURCE_NOT_EVALUATED = "not_evaluated"

#: Derivational suffixes that build an adjective or a follower-noun from a
#: proper name. Ordered longest-first so that "esque" is tried before "es"
#: would ever be relevant; the tuple is data, and the whole rule is reviewable
#: by reading it. Chemical-nomenclature suffixes (-ate, -ide, -ine, -ite except
#: as guarded below, -ane, -ene, -ol) are deliberately NOT here; see the module
#: docstring.
DERIVATIONAL_SUFFIXES: tuple[str, ...] = (
    "esque",   # Kafkaesque, Rubenesque
    "ians",    # Aristotelians, Platonians  (plural of -ian)
    "ists",    # Thomists, Marxists         (plural of -ist)
    "isms",    # Platonisms                 (plural of -ism)
    "ites",    # Hussites, Shiites          (plural of -ite)
    "ian",     # Aristotelian, Newtonian, Freudian
    "ean",     # Euclidean, Archimedean
    "ese",     # Japanese, Portuguese
    "ist",     # Thomist, Marxist
    "ism",     # Platonism, Confucianism
    "ite",     # Hussite, Israelite
    "ish",     # Danish, Spanish
    "oid",     # Mongoloid
    "ic",      # Socratic, Homeric, Germanic
    "an",      # Roman, Elizabethan
)

#: A stem shorter than this is refused. Six characters, not five: a derivational
#: suffix that attaches to an UNMODIFIED stem of five or more characters is
#: already HARD under R1's LONG_PREFIX branch, so this rule only ever needs to
#: reach the longer, stem-modifying derivations. Raising the floor to six costs
#: nothing that R1 does not already cover and removes the short-root
#: coincidences ("sulf", "nitr", "graph") outright.
MINIMUM_STEM_LENGTH = 6

#: How far the derivational stem may sit from the Answer token. One bounded
#: Damerau-Levenshtein edit — one insertion, deletion, substitution, or one
#: ADJACENT TRANSPOSITION. The transposition is what "aristotle"/"aristotel"
#: needs and is why plain Levenshtein at distance 1 would not do.
MAXIMUM_STEM_EDIT_DISTANCE = 1

#: How many listed suffixes may be removed in sequence. Two, because the
#: eponymic DOCTRINE names in this corpus are two derivations deep —
#: ``Aristotelianism`` = Aristotle + -ian + -ism, ``Confucianism`` = Confucius +
#: -ian + -ism — and one strip leaves a stem three edits away from the name.
#: The stem floor applies at every step, so the extra depth cannot reach a short
#: root: "germanic" -> "german" -> "germ" is refused, and so is
#: "buddhism" -> "buddh". Measured over the 329-Answer corpus, the whole
#: class-only rule at depth 2 changes the verdict of 10 of 7,388 Answer/class
#: pairs, of which depth 2 itself contributes exactly two — Aristotelianism and
#: Confucianism. See `class_leakage_delta_audit.csv`.
MAXIMUM_DERIVATION_DEPTH = 2


@dataclass(frozen=True)
class DerivationalPolicy:
    """The complete, explicit configuration of the class-only rule.

    A dataclass rather than four module constants read directly, so a test can
    tighten or loosen ONE threshold and observe the effect without monkeypatching
    module state, and so the effective configuration can be recorded verbatim in
    a run manifest.
    """

    suffixes: tuple[str, ...] = DERIVATIONAL_SUFFIXES
    minimum_stem_length: int = MINIMUM_STEM_LENGTH
    maximum_edit_distance: int = MAXIMUM_STEM_EDIT_DISTANCE
    maximum_derivation_depth: int = MAXIMUM_DERIVATION_DEPTH
    version: str = CLASS_LEAKAGE_POLICY_VERSION

    def as_record(self) -> dict:
        return {
            "class_leakage_policy_version": self.version,
            "derivational_suffixes": list(self.suffixes),
            "minimum_stem_length": self.minimum_stem_length,
            "maximum_stem_edit_distance": self.maximum_edit_distance,
            "maximum_derivation_depth": self.maximum_derivation_depth,
        }


DEFAULT_DERIVATIONAL_POLICY = DerivationalPolicy()


@dataclass(frozen=True)
class ClassLeakVerdict:
    """One Answer/class leakage verdict, with everything an audit needs.

    `level` is the FINAL verdict, `r1_level` is what the frozen rule alone said,
    and `changed_by_class_rule` is true exactly when the class-only extension
    moved the verdict. Keeping all three means the delta audit is a projection of
    the verdict object rather than a second computation that could disagree
    with it.
    """

    level: str
    status: str = LEAK_STATUS_EVALUATED
    source: str = LEAK_SOURCE_R1
    reason: Optional[str] = None
    evidence: tuple[str, ...] = ()
    r1_level: str = LEAK_NONE
    r1_reason: Optional[str] = None
    r1_evidence: tuple[str, ...] = ()
    derivational_evidence: tuple[str, ...] = ()

    @property
    def is_hard(self) -> bool:
        return self.level == LEAK_HARD

    @property
    def evaluated(self) -> bool:
        return self.status == LEAK_STATUS_EVALUATED

    @property
    def changed_by_class_rule(self) -> bool:
        """True when the class-only extension produced a different level."""
        return self.evaluated and self.level != self.r1_level

    def as_record(self) -> dict:
        return {
            "leak_level": self.level,
            "leak_status": self.status,
            "leak_source": self.source,
            "leak_reason": self.reason,
            "leak_evidence": list(self.evidence),
            "r1_leak_level": self.r1_level,
            "r1_leak_evidence": list(self.r1_evidence),
            "class_rule_evidence": list(self.derivational_evidence),
            "changed_by_class_rule": self.changed_by_class_rule,
        }


def bounded_damerau_levenshtein(a: str, b: str, limit: int) -> int:
    """Damerau-Levenshtein distance, reported as ``limit + 1`` once exceeded.

    Bounded rather than exact because the only question ever asked is "is this
    at most one edit apart?"; computing a distance of 9 accurately would cost
    the same and mean nothing here. The length pre-check makes the common
    non-match case free.

    Optimal string alignment (the restricted edit distance): each pair of
    characters may participate in at most one transposition. That is the right
    variant for a spelling adjustment inside one word, and it is the variant a
    reader who checks "aristotle" against "aristotel" by hand will compute.
    """
    limit = max(0, int(limit))
    if a == b:
        return 0
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous_previous: list[int] = []
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current[j] = min(
                previous[j] + 1,          # deletion
                current[j - 1] + 1,       # insertion
                previous[j - 1] + cost,   # substitution
            )
            if (i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb):
                current[j] = min(current[j], previous_previous[j - 2] + 1)
        if min(current) > limit:
            return limit + 1
        previous_previous, previous = previous, current
    return previous[len(b)] if previous[len(b)] <= limit else limit + 1


def _derivational_stems(token: str, policy: DerivationalPolicy
                        ) -> tuple[tuple[str, str], ...]:
    """Every ``(stem, suffix_path)`` obtainable by removing listed suffixes.

    Longest suffix first, duplicates removed, and any stem below
    `minimum_stem_length` dropped before it can be compared. Returning ALL
    admissible stems rather than only the first keeps the rule independent of
    the suffix tuple's order: "aristotelian" yields both ("aristotel", "ian")
    and ("aristoteli", "an"), and the caller accepts whichever matches.

    Up to `maximum_derivation_depth` suffixes are removed in sequence, because
    the eponymic doctrine names in this corpus are genuinely two derivations
    deep: ``Aristotelianism`` is Aristotle + -ian + -ism, ``Confucianism`` is
    Confucius + -ian + -ism. One strip reaches only "aristotelian", which is
    three edits from "aristotle" and correctly refused.

    The depth is safe because the length floor applies at EVERY step, not only
    at the end: "germanic" -> "german" -> "germ" is refused at the second strip,
    "platonism" -> "platon" cannot strip again, and "buddhism" -> "buddh" never
    survives the first. Depth therefore buys the -ianism family and nothing
    shorter.
    """
    depth = max(1, int(policy.maximum_derivation_depth))
    frontier: list[tuple[str, str]] = [(token, "")]
    stems: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _ in range(depth):
        nxt: list[tuple[str, str]] = []
        for current, path in frontier:
            for suffix in sorted(set(policy.suffixes), key=lambda s: (-len(s), s)):
                if not suffix or not current.endswith(suffix):
                    continue
                stem = current[: -len(suffix)]
                if len(stem) < policy.minimum_stem_length:
                    continue
                # The path reads outermost-suffix-first, so the evidence string
                # spells the derivation in the order it was applied backwards:
                # "ism_ian" means -ian was attached first, then -ism.
                extended = f"{path}_{suffix}" if path else suffix
                key = (stem, extended)
                if key in seen:
                    continue
                seen.add(key)
                stems.append(key)
                nxt.append((stem, extended))
        if not nxt:
            break
        frontier = nxt
    return tuple(stems)


def derivational_matches(
    answer_uri: str,
    counterpart_uri: str,
    policy: QualityPolicy,
    *,
    derivational: DerivationalPolicy = DEFAULT_DERIVATIONAL_POLICY,
) -> tuple[str, ...]:
    """Deterministic evidence strings for every derivational/eponymic overlap.

    Tokenisation is the frozen R1 pipeline (`leakage_tokens` with the policy's
    own `minimum_token_length`), so the two rules see exactly the same tokens
    and a disagreement between them can only come from the comparison, never
    from the input.

    Both directions are tested — a suffix stripped from the CLASS token and a
    suffix stripped from the ANSWER token — because "one name is a derivational
    form of the other" is a symmetric relation and a class named `Aristotle` for
    an Answer named `Aristotelianism` is just as revealing as the converse. The
    direction is recorded in the evidence so a reviewer never has to guess which
    side was rewritten.

    Evidence format mirrors R1's own ``answer_token~other_token:KIND`` shape so
    that a mixed evidence column stays readable, with the suffix and the measured
    edit distance carried inside KIND.
    """
    minimum = policy.leakage.minimum_token_length
    answer_tokens = leakage_tokens(answer_uri, minimum_length=minimum)
    other_tokens = leakage_tokens(counterpart_uri, minimum_length=minimum)
    limit = derivational.maximum_edit_distance
    floor = derivational.minimum_stem_length

    matches: set[str] = set()
    for a in answer_tokens:
        # The frozen light plural stem, so "socrates" and "socrat" compare equal
        # exactly as they already do everywhere else in this repository.
        a_stem = _plural_stem(a, policy.leakage.strip_suffixes)
        if len(a_stem) < floor:
            continue
        for b in other_tokens:
            b_stem = _plural_stem(b, policy.leakage.strip_suffixes)

            # Direction 1: the CLASS token is the derived form.
            for stem, suffix in _derivational_stems(b, derivational):
                distance = bounded_damerau_levenshtein(a_stem, stem, limit)
                if distance <= limit:
                    matches.add(
                        f"{a}~{b}:CLASS_DERIVATIONAL_{suffix.upper()}_D{distance}")

            # Direction 2: the ANSWER token is the derived form.
            if len(b_stem) < floor:
                continue
            for stem, suffix in _derivational_stems(a, derivational):
                distance = bounded_damerau_levenshtein(b_stem, stem, limit)
                if distance <= limit:
                    matches.add(
                        f"{a}~{b}:ANSWER_DERIVATIONAL_{suffix.upper()}_D{distance}")
    return tuple(sorted(matches))


def classify_r1_only(answer_uri: str, counterpart_uri: str,
                     policy: QualityPolicy) -> tuple[str, Optional[str], tuple[str, ...]]:
    """``(level, reason_code, evidence)`` from the FROZEN R1 rule alone.

    Exists so the delta audit can report the R1 verdict and the extended verdict
    for the same pair without calling two different code paths that might
    tokenise differently. R1 itself is untouched: this is one call to
    `detect_answer_leakage` and a rename of its three outputs.
    """
    result = detect_answer_leakage(answer_uri, counterpart_uri, policy)
    if result.hard_leak:
        level = LEAK_HARD
    elif result.soft_leak:
        level = LEAK_SOFT
    else:
        level = LEAK_NONE
    evidence = tuple(f"{a}~{b}:{kind}" for a, b, kind in result.matches)
    return level, result.reason_code, evidence


def classify_class_leakage_extended(
    answer_uri: str,
    counterpart_uri: str,
    policy: QualityPolicy,
    *,
    derivational: DerivationalPolicy = DEFAULT_DERIVATIONAL_POLICY,
) -> ClassLeakVerdict:
    """The AUTHORITATIVE verdict for one Answer/class pair: R1, then the class rule.

    Composition is monotone and one-directional: the class-only rule can only
    RAISE a verdict to HARD. It never downgrades a HARD to SOFT, never clears a
    SOFT, and never contradicts R1 — so every class R1 already rejected stays
    rejected, and the delta over the previous behaviour is a set of additions
    that `class_leakage_delta_audit.csv` enumerates in full.

    `counterpart_uri` is the RESOURCE-STYLE adaptation of the category URI (the
    leading ``Category:`` marker removed), because that is the shape R1 was
    measured against. Producing that adaptation is the caller's job; this
    function does no URI rewriting of its own.
    """
    r1_level, r1_reason, r1_evidence = classify_r1_only(
        answer_uri, counterpart_uri, policy)
    extra = derivational_matches(answer_uri, counterpart_uri, policy,
                                 derivational=derivational)

    if r1_level == LEAK_HARD:
        # Already hard. The class rule is still recorded when it also fired, so
        # the audit can tell "R1 alone" from "both agreed", but it changes
        # nothing and the decisive source stays R1.
        return ClassLeakVerdict(
            level=LEAK_HARD, source=LEAK_SOURCE_R1, reason=r1_reason,
            evidence=r1_evidence + extra, r1_level=r1_level,
            r1_reason=r1_reason, r1_evidence=r1_evidence,
            derivational_evidence=extra)
    if extra:
        return ClassLeakVerdict(
            level=LEAK_HARD, source=LEAK_SOURCE_DERIVATIONAL,
            reason="CLASS_DERIVATIONAL_EPONYMIC_LEAK",
            evidence=r1_evidence + extra, r1_level=r1_level,
            r1_reason=r1_reason, r1_evidence=r1_evidence,
            derivational_evidence=extra)
    return ClassLeakVerdict(
        level=r1_level, source=LEAK_SOURCE_R1, reason=r1_reason,
        evidence=r1_evidence, r1_level=r1_level, r1_reason=r1_reason,
        r1_evidence=r1_evidence, derivational_evidence=())


def not_evaluated_verdict(reason: str) -> ClassLeakVerdict:
    """The verdict for a class whose URI could not be adapted for comparison.

    Deliberately NOT `no_leak`. A reader must be able to tell "the rule ran and
    found nothing" from "the rule could not run", and the previous behaviour —
    defaulting an unevaluated class to `no_leak` — is exactly the provenance
    defect this module was written to remove.
    """
    return ClassLeakVerdict(
        level=LEAK_NONE, status=LEAK_STATUS_NOT_EVALUATED,
        source=LEAK_SOURCE_NOT_EVALUATED, reason=reason,
        r1_level=LEAK_NONE)
