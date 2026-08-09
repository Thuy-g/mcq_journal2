"""Exact distractor-and-rationale selection kernel for Journal 2 — Phase A.

WHAT THIS MODULE IS
-------------------
This is the mathematical research core of the method, and nothing else. Given

  * one Answer entity,
  * the complete ranked candidate pool with its frozen LRoleSim rank and score,
  * the Answer's facts, each already marked eligible or ineligible, and
  * for every (fact, candidate) pair, the evidence level already decided
    upstream,

it chooses exactly ``k = 3`` distractors and the smallest rationale that
distinguishes the Answer from all three, under an exact lexicographic
objective. It is meant to be read top to bottom by the human author and
explained in a viva without opening any other file.

WHAT THIS MODULE IS NOT
-----------------------
Phase A does **not** decide evidence levels. It never sees a raw triple, never
tests object equality or parent–child containment, never consults a semantic
index, never derives an empirical single-valued rule, never checks an L2 proof,
never detects a URL/media predicate, never detects lexical leakage, and never
looks up a verbalization template. Every one of those is a *classification*
question answered by the frozen Prompt-8F-R1 pipeline, whose records are the
oracle input here. They belong to Phase B.

Concretely: this module receives ``AnswerFact`` records whose ``levels`` tuple
is already filled in, and whose ``quality`` record already carries
``eligible``, ``verbalizable``, ``pedagogical_tier`` and the rest. It consumes
those fields as opaque, already-computed attributes. It attaches no linguistic
or semantic meaning to them beyond their position in the ordering.

TERMINOLOGY — the authority is ``docs/context/EVIDENCE_TAXONOMY_V1.md``
-----------------------------------------------------------------------
Four values may appear in ``AnswerFact.levels``, ordered by strength:

``NOT_COVERED``
    The candidate **supports** the Answer proposition. The fact does not
    distinguish that candidate; it covers nobody at that position. Tested
    before L0/L1/L2 upstream, so it can never be re-read as absence or as
    contrast.
``L0_ABSENCE_ONLY_OBSERVED`` (written ``L0``)
    The pinned snapshot records no object at all for the candidate under the
    same predicate and the same direction. **Snapshot absence only.** It is not
    negation, not real-world exclusion, and not evidence a student may be shown
    as a reason. It exists here for yield reporting and failure analysis.
``L1_POSITIVE_ALTERNATIVE_OBSERVED`` (written ``L1``)
    The candidate has at least one **observed alternative value** under the
    same predicate and the same direction, and none of its observed values
    supports the Answer proposition. This is the weakest level that may be
    shown to a student, phrased as an observation about the snapshot.
``L2_VERIFIED_EXCLUSION`` (written ``L2``)
    A machine-checkable proof exists that the candidate cannot stand in that
    relation to that object. The generic kernel below **accepts L2 as an input
    level** and orders it correctly, but Phase A implements no L2 rule and no
    proof generator. The R1 pilot contains zero L2 incidences; zero is the
    correct offline outcome, not a gap.

``SCOPED_EMPIRICAL`` is an **annotation** on an existing L1, recorded in
``AnswerFact.exclusion_bases``. It is not a fourth level. It may order two
equally strong rationales and can never create, upgrade or rescue a level.

OPEN-WORLD LIMITATION — carried through every number this module produces
-------------------------------------------------------------------------
DBpedia is an open-world knowledge graph::

    (d, p, o) ∉ K   does NOT imply   ¬p(d, o)

The pinned snapshot ``K`` records what has been documented, not what is true.
Therefore absence (L0) is a statement about the snapshot's coverage; an
observed alternative (L1) is a statement about what the snapshot records and
never a proof of incompatibility; only an explicit sourced proof (L2) may be
phrased as exclusion. Nothing in this file may be written up as "the candidate
did not do X". Many DBpedia infobox predicates are multi-valued — ``almaMater``
is the worked example in the Eisaku Satō trace — so the caveat is not
hypothetical.

LROLESIM'S ROLE
---------------
LRoleSim is consumed here **only** as a frozen structural plausibility ranker.
Ranks and scores arrive pre-computed in ``Candidate``; no similarity is
recomputed, no LRoleSim formula is touched, and LRoleSim produces no rationale.
Journal 2 *applies* LRoleSim; it does not extend it. Rationale construction is
a separate mechanism entirely — the set cover below — and the two never mix.

THE COMPLETE OBJECTIVE, smallest tuple wins, evaluated left to right
--------------------------------------------------------------------
1. ``-lrolesim_score_sum``        maximise total structural plausibility
2. ``-lrolesim_score_min``        maximise the weakest distractor
3. ``minimum_rationale_size``     minimise |R*|, by exact bitmask set cover
4. the 14-field rationale ranking key  evidence profile first, then quality
5. ``candidate_rank_sum``         a deterministic tie-break aligned with the
                                  LRoleSim ranking
6. ``candidate_uris``             lexicographic last resort

Key 5 is **only** a tie-break. It is not a plausibility metric and not a
pedagogical-quality objective: rank is an ordinal transform of the score that
keys 1 and 2 already maximise with full cardinal precision, so promoting it
would replace a measurement by a coarser proxy for the same measurement. It
earns its place because when LRoleSim scores tie *exactly*, rank is the
ranker's own residual ordering, which keeps the resolution inside the LRoleSim
framework instead of falling through to alphabetical URI order. See
``docs/audits/RANK_SUM_EFFECT_AUDIT.md``.

SEARCH SCOPE — two exhaustive modes, and the claim each one supports
---------------------------------------------------------------------
There is no beam, no greedy pass, no random sampling, and no early acceptance
of the first feasible combination, in either mode. What changes between the two
modes is *what the exhaustive search is exhaustive over*, and that is a
scientific claim rather than an implementation detail:

``FULL_EXACT``
    Every one of the C(n, 3) combinations over the **complete ranked candidate
    pool** is enumerated and scored. The result is exact over the complete
    ranked candidate pool: ``global_optimality_claim`` is true.
``POOL_EXACT``
    Chosen automatically when C(n, 3) exceeds ``MAX_EXACT_COMBINATIONS``. A
    bounded pool is built — the top candidates by frozen LRoleSim rank, plus a
    few evidence-rescue candidates the rank cutoff would otherwise drop — and
    **every** combination inside that pool is enumerated and scored. The result
    is exact *within the bounded candidate pool* and nothing more:
    ``global_optimality_claim`` is false, and no optimality claim is made over
    candidates excluded from the pool.

Both modes run the identical coverage masks, the identical minimum-cardinality
bitmask DP, the identical rationale enumeration, the identical fourteen-field
rationale ranking and the identical six-key candidate-combination objective.
The only difference is the set of candidate positions the combinations are
drawn from. Evidence rescue decides which candidates the exact search may see;
it is no part of the objective and it changes no evidence level.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable, Sequence

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

# Evidence strength. NOT_COVERED sits at 0 because the candidate SUPPORTS the
# Answer proposition, so the fact discriminates nothing. Every policy threshold
# below is at least 1, which is exactly why a NOT_COVERED incidence can never
# set a coverage bit at any threshold — see coverage_mask().
LEVEL_STRENGTH = {"NOT_COVERED": 0, "L0": 1, "L1": 2, "L2": 3}

# Policies are tried in this order and the FIRST one with at least one feasible
# full-coverage combination is selected. strict-l2 demands a verified exclusion
# for every distractor; main-l1 is the main-corpus policy and demands an
# observed alternative value or better; diagnostic-l0 admits snapshot absence
# and exists only for yield reporting and failure analysis. A diagnostic-l0
# rationale must never be presented to a student as a reason.
POLICY_ORDER = ("strict-l2", "main-l1", "diagnostic-l0")
POLICY_THRESHOLD = {"strict-l2": "L2", "main-l1": "L1", "diagnostic-l0": "L0"}

K_DISTRACTORS = 3          # exactly three distractors per item
RHO_MAX_RATIONALE_SIZE = 3  # a rationale larger than this is not usable

# The two search scopes. Both enumerate exhaustively; they differ in what they
# enumerate over, and therefore in what may be claimed about the result.
SEARCH_FULL_EXACT = "FULL_EXACT"
SEARCH_POOL_EXACT = "POOL_EXACT"

# Bounded-pool defaults, INHERITED UNCHANGED from the frozen R1 policy and kept
# configurable only through PoolPolicy. C(107, 3) = 198,485 fits the budget and
# C(108, 3) = 204,156 does not, so a class needs more than 107 candidates
# before the kernel leaves FULL_EXACT at all. Three quarters of the pool is
# reserved for LRoleSim plausibility and one quarter for evidence rescue.
MAX_EXACT_COMBINATIONS = 200_000
POOL_TOP_BY_LROLESIM = 75
POOL_EVIDENCE_RESCUE = 25
MAX_POOL_SIZE = 100
POOL_POLICY_NAME = "top_lrolesim_plus_evidence_rescue_v1"

OPEN_WORLD_NOTE = (
    "Absence in the pinned snapshot is not falsity. L0 records that the "
    "snapshot has no object for the candidate under the same predicate and "
    "direction; L1 records an observed alternative value. Neither asserts that "
    "the candidate could not also hold the Answer's object, because DBpedia "
    "infobox predicates are open-world and frequently multi-valued."
)
LROLESIM_ROLE_NOTE = (
    "LRoleSim is applied as a frozen structural plausibility ranker only. No "
    "similarity is recomputed here and LRoleSim generates no rationale."
)
LOCAL_ANONYMITY_NOTE = (
    "Computed over the Answer plus the COMPLETE ranked candidate pool of the "
    "selected class. This is local candidate-pool anonymity, not uniqueness in "
    "DBpedia and not global uniqueness."
)
RANK_SUM_NOTE = (
    "candidate_rank_sum is objective key 5: a deterministic tie-break aligned "
    "with the LRoleSim ranking. It is not a plausibility metric and not a "
    "pedagogical-quality objective."
)
# The scope of the exactness claim, in words, travelling with every record so
# that a record read on its own cannot be mistaken for the stronger claim.
SEARCH_SCOPE_NOTE = {
    SEARCH_FULL_EXACT: (
        "Every combination over the COMPLETE ranked candidate pool was "
        "enumerated and scored. The selection is exact over the complete "
        "ranked candidate pool of the selected class. This is still a local "
        "claim about that pool, never a claim about DBpedia as a whole."
    ),
    SEARCH_POOL_EXACT: (
        "Every combination inside the BOUNDED candidate pool was enumerated "
        "and scored, so the selection is exact within the bounded candidate "
        "pool. No optimality claim is made over candidates excluded from the "
        "pool: this result is NOT globally optimal, is NOT a global optimum, "
        "and is NOT exact over all candidates."
    ),
}
EVIDENCE_RESCUE_NOTE = (
    "Evidence rescue is a pool-construction heuristic that decides which "
    "candidates the exact search may see. It is no part of the six-key "
    "candidate-combination objective, it creates no evidence level, and it "
    "reinterprets no absence as falsity."
)


# --------------------------------------------------------------------------
# Immutable input records
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FactQuality:
    """Per-fact fields ALREADY COMPUTED upstream, consumed here as attributes.

    ``(predicate_uri, direction, counterpart_uri)`` is the **canonical fact
    identity**. ``direction`` is ``"IN"`` or ``"OUT"`` and is part of that
    identity: ``dbp:influences`` IN and ``dbp:influences`` OUT are two different
    relations with different extensions and different verbalizations, so this
    module must never merge them, never key a dictionary on the predicate
    alone, and never count them as one fact. Six of the nine rationale facts in
    the R1 pilot are IN.

    ``eligible`` is a HARD FILTER decided upstream (raw layout slots, external
    URL fields, Answer-label leakage). An ineligible fact is removed before any
    ranking; it is never a soft penalty. Phase A does not re-derive it.
    """

    predicate_uri: str
    direction: str
    counterpart_uri: str
    display_label: str
    eligible: bool
    soft_leak: bool
    verbalizable: bool
    pedagogical_tier: int
    label_length: int
    token_count: int
    template_id: str

    @property
    def identity(self) -> tuple[str, str, str]:
        """The canonical fact tuple. Direction is inside it, deliberately."""
        return (self.predicate_uri, self.direction, self.counterpart_uri)

    @property
    def predicate_direction_key(self) -> tuple[str, str]:
        """``κ = (p, dir)``. Two facts sharing κ are redundant in a rationale."""
        return (self.predicate_uri, self.direction)


@dataclass(frozen=True)
class AnswerFact:
    """One Answer fact plus its already-classified evidence, per candidate.

    ``levels[i]``, ``exclusion_bases[i]`` and ``granularity_risks[i]`` describe
    the ordered pair (this fact, candidate ``i``) where ``i`` indexes the
    Answer's canonical candidate order. An evidence level is always a property
    of that pair; it is never a property of the fact alone.

    ``exclusion_bases`` holds NONE / SCOPED_EMPIRICAL / FORMAL_PROOF and
    ``granularity_risks`` holds NONE / CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT /
    UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE. Both are separate axes: they enter
    the rationale ranking as ordering and provenance data, and neither may move
    a fact between levels.
    """

    quality: FactQuality
    levels: tuple[str, ...]
    exclusion_bases: tuple[str, ...]
    granularity_risks: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    """One ranked candidate, with its FROZEN LRoleSim rank and score."""

    rank: int
    score: float
    uri: str


@dataclass(frozen=True)
class AnswerCase:
    """Everything the kernel needs about one Answer. Build with build_case()."""

    answer_uri: str
    display_label: str
    candidates: tuple[Candidate, ...]
    facts: tuple[AnswerFact, ...]
    eligible_fact_indices: tuple[int, ...]


def build_case(
    answer_uri: str,
    display_label: str,
    candidates: Sequence[Candidate],
    facts: Sequence[AnswerFact],
) -> AnswerCase:
    """Canonicalise a case so the caller's input ordering cannot leak into it.

    Candidates arrive in whatever order the caller happened to have, and each
    fact's per-candidate tuples are aligned to *that* order. Here they are
    re-sorted into the canonical order ``(rank, uri)`` and every fact's tuples
    are permuted the same way. Two callers holding the same information in
    different orders therefore produce the same ``AnswerCase`` and, downstream,
    byte-identical output.

    Ineligible facts are dropped from ``eligible_fact_indices`` — the hard
    filter — but are kept in ``facts`` so that indices stay stable and a
    rejected fact remains inspectable for failure analysis.
    """
    order = sorted(range(len(candidates)), key=lambda i: (candidates[i].rank, candidates[i].uri))
    ordered_candidates = tuple(candidates[i] for i in order)
    ordered_facts = tuple(
        AnswerFact(
            quality=fact.quality,
            levels=tuple(fact.levels[i] for i in order),
            exclusion_bases=tuple(fact.exclusion_bases[i] for i in order),
            granularity_risks=tuple(fact.granularity_risks[i] for i in order),
        )
        for fact in facts
    )
    eligible = tuple(i for i, fact in enumerate(ordered_facts) if fact.quality.eligible)
    return AnswerCase(answer_uri, display_label, ordered_candidates, ordered_facts, eligible)


# --------------------------------------------------------------------------
# Coverage masks
# --------------------------------------------------------------------------


def coverage_mask(fact: AnswerFact, positions: Sequence[int], threshold: str) -> int:
    """The k-bit coverage mask of ONE fact over ONE candidate combination.

    ``positions`` is the combination, as indices into ``AnswerCase.candidates``.
    **Bit i corresponds exactly to ``positions[i]``** — the i-th distractor of
    this combination, in the combination's own position order. Bit 0 is the
    first distractor, bit 1 the second, bit 2 the third. Reordering the
    combination reorders the bits; the mask is meaningless without the
    combination it was built against.

    Bit i is set iff this fact reaches ``threshold`` or better for that
    candidate::

        bit i = 1  iff  LEVEL_STRENGTH[levels[positions[i]]] >= LEVEL_STRENGTH[threshold]

    ``NOT_COVERED`` has strength 0 and every threshold has strength >= 1, so a
    NOT_COVERED incidence **can never set a bit at any threshold**. That is the
    whole point of the level: the candidate supports the Answer's proposition,
    so the fact tells a student nothing that separates them, and it must
    contribute no coverage. This is checked directly by a unit test.

    IN and OUT are never merged: two facts differing only in direction are two
    different ``AnswerFact`` objects with two independent masks, because
    direction is part of the canonical fact identity.
    """
    mask = 0
    for bit, position in enumerate(positions):
        if LEVEL_STRENGTH[fact.levels[position]] >= LEVEL_STRENGTH[threshold]:
            mask |= 1 << bit
    return mask


def case_masks(case: AnswerCase, positions: Sequence[int], threshold: str) -> list[int]:
    """Masks of every ELIGIBLE Answer fact over one combination."""
    return [coverage_mask(case.facts[i], positions, threshold) for i in case.eligible_fact_indices]


# --------------------------------------------------------------------------
# Exact minimum-cardinality bitmask set cover
# --------------------------------------------------------------------------


def minimum_cover_size_table(masks: Iterable[int], k: int = K_DISTRACTORS) -> list[int]:
    """Minimum number of facts needed to reach each of the 2^k coverage states.

    This is the exact minimum-cardinality set cover over the k distractors,
    solved by a 0/1 dynamic program on the 2^k subsets. Bitmask DP and set
    cover are textbook; nothing here is claimed as new.

    WHY IT IS EXACT, not a greedy approximation
        ``table[s]`` is the true minimum over *all* subsets of facts whose
        masks OR to a superset of ``s``. Each fact is offered once, in an outer
        loop, and every relaxation reads ``previous`` — a snapshot taken before
        that fact was offered. So no fact can be used twice inside its own
        pass, which is exactly the 0/1 semantics of choosing a set at most
        once. Induction on the outer loop: after processing the first ``j``
        facts, ``table`` holds the exact optimum over subsets of those ``j``.
        The greedy alternative (repeatedly take the fact covering the most
        uncovered distractors) can be worse than optimal on set cover, and is
        not used anywhere in this module.

    WHY DUPLICATE MASKS CAN BE COLLAPSED
        The DP only ever asks "which distractors does this fact reach". Two
        facts with the same mask are interchangeable for that question, and a
        minimum-cardinality cover never contains both — dropping one leaves the
        union unchanged and the cardinality smaller, contradicting minimality.
        So ``sorted({m for m in masks if m})`` loses nothing, and the empty
        mask is dropped because a fact covering nobody can never help. This
        collapse is a *cardinality* argument only; see
        ``rank_minimum_rationales`` for why the identity of the facts must be
        recovered afterwards.

    UNREACHABLE STATES
        hold ``k + 1``, which is strictly larger than any achievable cover
        size, because whenever a cover exists one fact per distractor already
        gives a cover of size <= k. So a single comparison against
        ``RHO_MAX_RATIONALE_SIZE`` (<= k) rejects both "too large" and
        "impossible" without a special case.
    """
    unreachable = k + 1
    table = [unreachable] * (1 << k)
    table[0] = 0
    for mask in sorted({m for m in masks if m}):
        previous = list(table)
        for covered, size in enumerate(previous):
            if size < unreachable and size + 1 < table[covered | mask]:
                table[covered | mask] = size + 1
    return table


def minimum_cover_size(masks: Iterable[int], k: int = K_DISTRACTORS) -> int:
    """Exact |R*| for FULL coverage of all k distractors; k + 1 if impossible."""
    return minimum_cover_size_table(masks, k)[(1 << k) - 1]


# --------------------------------------------------------------------------
# Local candidate-pool anonymity
# --------------------------------------------------------------------------


def local_pool_anonymity(
    case: AnswerCase, fact_indices: Sequence[int]
) -> tuple[int, float, bool]:
    """``|S_local(R)|``, its ratio, and whether R identifies the Answer alone.

    ``S_local(R)`` is the set of entities in ``{Answer} ∪ complete ranked
    candidate pool`` that **support every proposition in R**. An entity
    supports a proposition exactly when the fact does not cover it, i.e. its
    level is ``NOT_COVERED``. The Answer supports its own facts by
    construction, so the count starts at 1 and the supporter set is intersected
    fact by fact.

    THE SCOPE IS STRICTLY LOCAL. The pool is the Answer plus the complete
    ranked candidate pool of the selected class. A count of 1 means only that
    *within this pool* no other entity carries the same rationale. It says
    nothing about class members absent from the pool and nothing about DBpedia
    as a whole. Never report it as uniqueness or global uniqueness — hence the
    name, and hence LOCAL_ANONYMITY_NOTE travelling with every record.

    ``direct_identifier_flag`` is a DIAGNOSTIC and RANKING field, never a hard
    filter. It enters the rationale ranking as the thirteenth of fourteen
    fields and removes no rationale from consideration. Whether it should ever
    become a filter needs human-evaluation evidence the pilot does not provide.
    """
    supporters = set(range(len(case.candidates)))
    for index in fact_indices:
        levels = case.facts[index].levels
        supporters = {p for p in supporters if levels[p] == "NOT_COVERED"}
    count = 1 + len(supporters)
    return count, count / (1 + len(case.candidates)), count == 1


# --------------------------------------------------------------------------
# Rationale ranking — objective key 4
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Rationale:
    """One minimum-cardinality rationale, with every component of its key.

    The fields below are exactly the fourteen components of objective key 4,
    kept as named attributes so the ranking key can be read as a sentence
    rather than decoded from a tuple. ``ranking_key`` assembles them.
    """

    fact_indices: tuple[int, ...]
    fact_identities: tuple[tuple[str, str, str], ...]  # canonical, sorted
    coverage_masks: tuple[int, ...]                    # aligned to fact_indices
    coverage_mask: int                                 # the OR of the above
    per_candidate_best_level: tuple[str, ...]          # bit order = position order
    rationale_min_level: str
    l2_incidences: int
    l1_incidences: int
    l0_incidences: int
    scoped_empirical_incidences: int
    granularity_risk_incidences: int
    soft_leak_fact_count: int
    pedagogical_tier_sum: int
    unverbalizable_fact_count: int
    label_length_sum: int
    token_count_sum: int
    redundant_predicate_direction_pairs: int
    local_candidate_pool_anonymity_count: int
    local_candidate_pool_anonymity_ratio: float
    direct_identifier_flag: bool

    @property
    def ranking_key(self) -> tuple:
        """Objective key 4. Smallest tuple wins; a leading minus means maximise.

        Read left to right — the whole EVIDENCE profile is exhausted before any
        quality field is consulted, so no amount of pedagogical polish can buy
        a weaker evidence level:

         1  -strength(rationale_min_level)  strongest minimum evidence level
                                            over the three distractors, i.e.
                                            prefer the rationale whose WEAKEST
                                            distractor is best supported
         2  -l2_incidences                  more verified exclusions
         3  -l1_incidences                  more observed alternative values
         4  +l0_incidences                  fewer absence-only incidences;
                                            reached only under diagnostic-l0
         5  -scoped_empirical_incidences    annotation, ordering only; it sits
                                            AFTER the complete level profile so
                                            it can never create or rescue a
                                            level
         6  +granularity_risk_incidences    fewer risky apparent contrasts
         7  +soft_leak_fact_count           fewer soft Answer-label echoes
         8  +pedagogical_tier_sum           lower tier number is better
         9  +unverbalizable_fact_count      fewer facts with no template
        10  +label_length_sum               shorter surface form
        11  +token_count_sum                fewer tokens
        12  +redundant_predicate_direction_pairs   fewer repeats of one κ
        13  +direct_identifier_flag         diagnostic tie-break, not a filter
        14  canonical fact tuple            deterministic last resort

        These fields are R1's, preserved unchanged for Phase A. The eight-Answer
        pilot reaches only the first few of them, but the pilot is far too small
        to justify deleting any of the rest; that decision needs a batch-scale
        measurement of which fields are ever reached.
        """
        return (
            -LEVEL_STRENGTH[self.rationale_min_level],
            -self.l2_incidences,
            -self.l1_incidences,
            self.l0_incidences,
            -self.scoped_empirical_incidences,
            self.granularity_risk_incidences,
            self.soft_leak_fact_count,
            self.pedagogical_tier_sum,
            self.unverbalizable_fact_count,
            self.label_length_sum,
            self.token_count_sum,
            self.redundant_predicate_direction_pairs,
            1 if self.direct_identifier_flag else 0,
            self.fact_identities,
        )


def fact_ordering_key(quality: FactQuality) -> tuple:
    """Per-fact order, smallest wins. Only single-fact components belong here.

    Used to put the usable facts into a deterministic sequence before the
    minimum-cardinality rationales are enumerated. Because the enumeration is
    complete and the final sort is stable, this ordering can only decide
    between rationales whose full fourteen-field keys are already identical.
    """
    return (
        1 if quality.soft_leak else 0,
        quality.pedagogical_tier,
        0 if quality.verbalizable else 1,
        quality.label_length,
        quality.token_count,
        quality.identity,
    )


def build_rationale(
    case: AnswerCase,
    positions: Sequence[int],
    fact_indices: Sequence[int],
    threshold: str,
) -> Rationale:
    """Materialise one rationale and every component of its ranking key.

    Two loops, deliberately kept separate:

    * the per-(candidate, fact) loop, which reads the evidence axes. A level is
      a property of the ordered pair, so the incidence counts are counted over
      pairs, not over facts. Only incidences reaching the POLICY threshold are
      counted — a fact that fails the threshold for a candidate contributes no
      coverage and no incidence — but ``per_candidate_best_level`` tracks the
      best level seen regardless, because it reports what evidence the
      distractor actually received;
    * the per-fact loop, which sums the already-computed quality attributes.
    """
    per_candidate_best: list[str] = []
    counts = {"L0": 0, "L1": 0, "L2": 0}
    scoped = 0
    risk = 0
    for position in positions:
        best = "NOT_COVERED"
        for index in fact_indices:
            fact = case.facts[index]
            level = fact.levels[position]
            if LEVEL_STRENGTH[level] > LEVEL_STRENGTH[best]:
                best = level
            if LEVEL_STRENGTH[level] < LEVEL_STRENGTH[threshold]:
                continue
            counts[level] += 1
            if fact.exclusion_bases[position] == "SCOPED_EMPIRICAL":
                scoped += 1
            if fact.granularity_risks[position] != "NONE":
                risk += 1
        per_candidate_best.append(best)

    qualities = [case.facts[i].quality for i in fact_indices]
    keys = [q.predicate_direction_key for q in qualities]
    redundant = sum(1 for a, b in combinations(range(len(keys)), 2) if keys[a] == keys[b])
    anonymity_count, anonymity_ratio, direct = local_pool_anonymity(case, fact_indices)
    masks = tuple(coverage_mask(case.facts[i], positions, threshold) for i in fact_indices)
    union = 0
    for mask in masks:
        union |= mask

    return Rationale(
        fact_indices=tuple(fact_indices),
        fact_identities=tuple(sorted(q.identity for q in qualities)),
        coverage_masks=masks,
        coverage_mask=union,
        per_candidate_best_level=tuple(per_candidate_best),
        rationale_min_level=min(per_candidate_best, key=lambda lv: LEVEL_STRENGTH[lv]),
        l2_incidences=counts["L2"],
        l1_incidences=counts["L1"],
        l0_incidences=counts["L0"],
        scoped_empirical_incidences=scoped,
        granularity_risk_incidences=risk,
        soft_leak_fact_count=sum(1 for q in qualities if q.soft_leak),
        pedagogical_tier_sum=sum(q.pedagogical_tier for q in qualities),
        unverbalizable_fact_count=sum(1 for q in qualities if not q.verbalizable),
        label_length_sum=sum(q.label_length for q in qualities),
        token_count_sum=sum(q.token_count for q in qualities),
        redundant_predicate_direction_pairs=redundant,
        local_candidate_pool_anonymity_count=anonymity_count,
        local_candidate_pool_anonymity_ratio=anonymity_ratio,
        direct_identifier_flag=direct,
    )


def strongest_level_holding_the_minimum(
    case: AnswerCase, positions: Sequence[int], threshold: str, size: int
) -> str:
    """The strongest level at which a cover of the SAME minimum size still exists.

    Raising the level can only shrink each fact's mask, so the minimum cover
    size is monotone non-decreasing as the level strengthens. If a size-``size``
    cover exists at level ``t >= threshold`` then the minimum at ``t`` equals
    ``size``, and conversely. So the first ``t`` scanned from L2 downwards whose
    minimum equals ``size`` is the strongest level any minimum-cardinality
    rationale can reach — which is precisely the maximum of ranking-key field 1
    over all of them.

    Restricting the enumeration below to covers at that level is therefore an
    EXACT pre-filter, not a heuristic cut: a size-``size`` cover that exists at
    ``threshold`` but not at ``t`` has some distractor whose best level is under
    ``t``, so its ``rationale_min_level`` is weaker and it already loses on
    field 1 of the fourteen-field key.
    """
    for level in ("L2", "L1", "L0"):
        if LEVEL_STRENGTH[level] < LEVEL_STRENGTH[threshold]:
            break
        if minimum_cover_size(case_masks(case, positions, level), len(positions)) == size:
            return level
    return threshold


def rank_minimum_rationales(
    case: AnswerCase, positions: Sequence[int], policy: str
) -> tuple[int, str, list[Rationale]] | None:
    """Exact |R*|, then EVERY rationale of that cardinality, ranked by key 4.

    Two exact steps, in this order and for this reason:

    1. The bitmask DP gives the minimum cardinality. It works on *distinct*
       masks, which is sound for cardinality but throws away which fact
       produced which mask — and the ranking needs the facts, not the masks.
    2. So once the minimum cardinality ``size`` is known, every combination of
       ``size`` usable facts is enumerated and kept if it covers everybody. That
       makes the quality ranking exact rather than "whichever minimum-size cover
       the DP happened to reconstruct": two rationales of equal cardinality can
       differ sharply in evidence profile, verbalizability and tier, and key 4
       is there to choose between them.

    Returns ``None`` when the combination is infeasible under this policy —
    either no cover exists (the DP reports k + 1) or the smallest one is larger
    than ρ.
    """
    threshold = POLICY_THRESHOLD[policy]
    full = (1 << len(positions)) - 1
    size = minimum_cover_size(case_masks(case, positions, threshold), len(positions))
    if size > RHO_MAX_RATIONALE_SIZE:
        return None

    level = strongest_level_holding_the_minimum(case, positions, threshold, size)
    usable = sorted(
        (i for i in case.eligible_fact_indices if coverage_mask(case.facts[i], positions, level)),
        key=lambda i: fact_ordering_key(case.facts[i].quality),
    )
    ranked: list[Rationale] = []
    for candidate_facts in combinations(usable, size):
        covered = 0
        for index in candidate_facts:
            covered |= coverage_mask(case.facts[index], positions, level)
        if covered == full:
            ranked.append(build_rationale(case, positions, candidate_facts, threshold))
    if not ranked:
        return None
    ranked.sort(key=lambda rationale: rationale.ranking_key)
    return size, level, ranked


# --------------------------------------------------------------------------
# The bounded candidate pool — FULL_EXACT and POOL_EXACT
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PoolPolicy:
    """How the searchable candidate pool is bounded, and by how much.

    C(n, 3) grows cubically: 107 candidates cost 198,485 combinations, 200
    candidates cost 1,313,400, and 1,000 candidates cost 166,167,000. A DBpedia
    class large enough to matter therefore makes exhaustive enumeration over the
    complete pool impractical long before the pool itself becomes hard to build.
    This record is the ONLY place where that budget is expressed, so a reviewer
    can see the whole scalability guard as five numbers.

    The defaults are inherited from the frozen R1 policy and are not to be
    changed silently. ``for_pool_size`` scales them for ablation and nothing
    else.
    """

    max_exact_combinations: int = MAX_EXACT_COMBINATIONS
    top_by_lrolesim: int = POOL_TOP_BY_LROLESIM
    evidence_rescue: int = POOL_EVIDENCE_RESCUE
    max_pool_size: int = MAX_POOL_SIZE
    name: str = POOL_POLICY_NAME

    def __post_init__(self) -> None:
        """Reject a policy that cannot mean what it says, at construction time.

        A silently truncated pool would make the published
        ``pool_top_by_lrolesim`` and ``pool_evidence_rescue_limit`` fields
        describe a search that never happened, so an inconsistent policy is an
        error rather than something to clamp.
        """
        if min(self.max_exact_combinations, self.top_by_lrolesim,
               self.evidence_rescue, self.max_pool_size) < 0:
            raise ValueError(f"pool policy {self.name}: no limit may be negative")
        if self.max_pool_size < K_DISTRACTORS:
            raise ValueError(
                f"pool policy {self.name}: max_pool_size {self.max_pool_size} is "
                f"below k = {K_DISTRACTORS}, so no combination could be formed")
        if self.top_by_lrolesim + self.evidence_rescue > self.max_pool_size:
            raise ValueError(
                f"pool policy {self.name}: top_by_lrolesim {self.top_by_lrolesim} "
                f"+ evidence_rescue {self.evidence_rescue} exceeds max_pool_size "
                f"{self.max_pool_size}")

    @classmethod
    def for_pool_size(cls, size: int) -> "PoolPolicy":
        """The inherited 3:1 LRoleSim-to-rescue split, scaled to ``size``.

        ``top = ceil(3M/4)``, ``rescue = M - top``. M = 100 reproduces the
        default 75 + 25 exactly, which is the point: the ablation sizes are the
        same policy at four scales, not four different policies.
        """
        top = math.ceil(3 * size / 4)
        return cls(top_by_lrolesim=top, evidence_rescue=size - top,
                   max_pool_size=size, name=f"{POOL_POLICY_NAME}_M{size}")


def candidate_rescue_key(case: AnswerCase, position: int) -> tuple:
    """Pool-construction ordering for ONE candidate. Smallest tuple wins.

    WHY THIS IS DELIBERATELY CANDIDATE-LOCAL
        Every component below is read off the single candidate at ``position``,
        from evidence and quality fields that were already classified upstream.
        Nothing here inspects a pair, a triple, or which other candidates might
        join it. A rescue rule that scored combinations would need the very
        C(n, 3) enumeration the bounded pool exists to avoid, so it would be
        self-defeating: the pool must be cheap to build, or it buys nothing.

    THE ORDER, and what each component protects
        1  ``-strength(best level)``  the strongest level any eligible Answer
           fact reaches against this candidate. An L1- or L2-bearing candidate
           therefore always ranks ahead of an otherwise comparable L0-only
           candidate, and a candidate that only ever SUPPORTS the Answer's
           propositions ranks last — NOT_COVERED provides no rescue coverage,
           exactly as it provides no combination coverage.
        2  ``-l2_incidences``   more verified exclusions
        3  ``-l1_incidences``   more observed alternative values
        4  ``best_tier``        the best pedagogical tier among the facts that
           actually reach L1/L2 against this candidate; the sentinel keeps a
           candidate with no such fact behind every candidate that has one
        5  ``soft_leak``        counted only over facts that discriminate this
           candidate, since a soft leak on a fact that covers nobody here would
           be the same constant for every candidate and could order nothing
        6  ``granularity_risk`` fewer risky apparent contrasts
        7  ``rank``             the frozen LRoleSim rank, so that among equals
           the ranker's own ordering decides
        8  ``uri``             canonical last resort, so two runs on identical
           input can never disagree

    This is a POOL-CONSTRUCTION heuristic and is used nowhere else. It never
    appears in the six-key candidate-combination objective, it cannot change an
    evidence level, and being rescued confers no advantage inside the search:
    a rescued candidate is scored by exactly the same objective as any other.
    """
    best = "NOT_COVERED"
    l2 = l1 = soft = risk = 0
    best_tier = 1 + max(
        (case.facts[i].quality.pedagogical_tier for i in case.eligible_fact_indices),
        default=0)                       # sentinel: worse than any real tier
    for index in case.eligible_fact_indices:
        fact = case.facts[index]
        level = fact.levels[position]
        if LEVEL_STRENGTH[level] > LEVEL_STRENGTH[best]:
            best = level
        if level == "L2":
            l2 += 1
        elif level == "L1":
            l1 += 1
        if LEVEL_STRENGTH[level] >= LEVEL_STRENGTH["L1"]:
            best_tier = min(best_tier, fact.quality.pedagogical_tier)
            soft += 1 if fact.quality.soft_leak else 0
        if fact.granularity_risks[position] != "NONE":
            risk += 1
    candidate = case.candidates[position]
    return (-LEVEL_STRENGTH[best], -l2, -l1, best_tier, soft, risk,
            candidate.rank, candidate.uri)


@dataclass(frozen=True)
class CandidatePool:
    """The candidate positions the combination search will enumerate over.

    ``positions`` is ascending, so combinations drawn from it keep the same
    position order as a full enumeration and every coverage mask keeps the same
    bit order. Under FULL_EXACT it is simply ``range(n)``.
    """

    scope: str
    positions: tuple[int, ...]
    policy: PoolPolicy
    original_candidate_count: int
    original_combination_count: int
    enumerated_combination_count: int
    rescued_positions: tuple[int, ...]

    @property
    def global_optimality_claim(self) -> bool:
        """True ONLY under FULL_EXACT: exact over the complete ranked pool."""
        return self.scope == SEARCH_FULL_EXACT

    @property
    def pool_optimality_claim(self) -> bool:
        """Always true: both scopes enumerate their own pool exhaustively."""
        return True

    def provenance(self, case: AnswerCase) -> dict:
        """The compact scope record that must travel with every selection.

        Rescued candidates are published by rank and URI rather than by
        position, because a position is meaningless outside this run. No
        per-candidate rescue-key debug rows are emitted: the pool is
        reproducible from the policy and the frozen input, so publishing one
        row per candidate would bloat the output without adding evidence.
        """
        rescued = [case.candidates[p] for p in self.rescued_positions]
        return {
            "search_scope": self.scope,
            "search_scope_note": SEARCH_SCOPE_NOTE[self.scope],
            "global_optimality_claim": self.global_optimality_claim,
            "pool_optimality_claim": self.pool_optimality_claim,
            "pool_policy": self.policy.name,
            "original_candidate_count": self.original_candidate_count,
            "pool_candidate_count": len(self.positions),
            "original_combination_count": self.original_combination_count,
            "enumerated_combination_count": self.enumerated_combination_count,
            "pool_top_by_lrolesim": self.policy.top_by_lrolesim,
            "pool_evidence_rescue_limit": self.policy.evidence_rescue,
            "max_pool_size": self.policy.max_pool_size,
            "max_exact_combinations": self.policy.max_exact_combinations,
            "evidence_rescue_count": len(self.rescued_positions),
            "evidence_rescued_candidate_ranks": [c.rank for c in rescued],
            "evidence_rescued_candidate_uris": [c.uri for c in rescued],
            "evidence_rescue_note": EVIDENCE_RESCUE_NOTE,
        }


DEFAULT_POOL_POLICY = PoolPolicy()


def build_candidate_pool(
    case: AnswerCase,
    policy: PoolPolicy = DEFAULT_POOL_POLICY,
    force_pool: bool = False,
) -> CandidatePool:
    """FULL_EXACT under the combination budget, POOL_EXACT above it.

    The bounded pool is the top ``top_by_lrolesim`` candidates of the FROZEN
    LRoleSim ranking — no similarity is recomputed, no new measure is invented,
    no embedding is consulted — plus up to ``evidence_rescue`` candidates from
    below that cutoff, ordered by ``candidate_rescue_key``.

    WHY THE RESCUE SLOTS EXIST
        Structural plausibility and evidence availability are different
        properties. The most LRoleSim-similar candidates are frequently the ones
        that SHARE the Answer's propositions, which is precisely the case in
        which they carry no usable evidence at all — the Eisaku Satō pattern,
        where ranks 2 and 3 have zero L1-covering eligible facts. A pure
        top-of-ranking pool would systematically discard the low-ranked
        candidates that are the only ones a strong rationale can discriminate,
        and the bounded search would then report infeasibility that the complete
        search does not have. The rescue quarter is the cheapest available
        insurance against that failure mode.

    ``force_pool`` is an evaluation and debugging option: it makes POOL_EXACT
    testable and ablatable on classes small enough to verify by brute force. It
    is never the production default.
    """
    n = len(case.candidates)
    original = math.comb(n, K_DISTRACTORS) if n >= K_DISTRACTORS else 0
    if not force_pool and original <= policy.max_exact_combinations:
        return CandidatePool(
            scope=SEARCH_FULL_EXACT, positions=tuple(range(n)), policy=policy,
            original_candidate_count=n, original_combination_count=original,
            enumerated_combination_count=original, rescued_positions=())

    # Positions are canonical rank order, so the first m positions ARE the top
    # m of the frozen LRoleSim ranking; no re-sorting by score is needed.
    top = min(policy.top_by_lrolesim, n)
    room = max(min(policy.evidence_rescue, policy.max_pool_size - top), 0)
    rescued = tuple(sorted(
        sorted(range(top, n), key=lambda p: candidate_rescue_key(case, p))[:room]))
    positions = tuple(range(top)) + rescued
    return CandidatePool(
        scope=SEARCH_POOL_EXACT, positions=positions, policy=policy,
        original_candidate_count=n, original_combination_count=original,
        enumerated_combination_count=(math.comb(len(positions), K_DISTRACTORS)
                                      if len(positions) >= K_DISTRACTORS else 0),
        rescued_positions=rescued)


# --------------------------------------------------------------------------
# Candidate-combination search — the full objective
# --------------------------------------------------------------------------


def combination_prefix_key(
    case: AnswerCase, positions: Sequence[int], minimum_rationale_size: int
) -> tuple[float, float, int]:
    """Objective keys 1-3: the part that is cheap for every combination.

    Key 1 ``-lrolesim_score_sum`` maximises total structural plausibility and
    key 2 ``-lrolesim_score_min`` maximises the weakest distractor, both from
    the FROZEN LRoleSim scores. Key 3 minimises the exact |R*|, so a more
    plausible triple is preferred even when it needs a larger rationale — that
    is the plausibility/compactness trade-off the paper reports, and its
    direction is a deliberate choice recorded here.

    The scores are summed in ``positions`` order, which is ascending candidate
    order, so the floating-point result is reproducible run to run.
    """
    scores = [case.candidates[p].score for p in positions]
    return (-sum(scores), -min(scores), minimum_rationale_size)


def combination_objective_key(
    case: AnswerCase,
    positions: Sequence[int],
    minimum_rationale_size: int,
    rationale: Rationale,
) -> tuple:
    """The COMPLETE lexicographic objective, keys 1-6. Smallest tuple wins.

    1  -lrolesim_score_sum        maximise total LRoleSim score
    2  -lrolesim_score_min        maximise the minimum LRoleSim score
    3  minimum_rationale_size     minimise the exact minimum-rationale cardinality
    4  rationale.ranking_key      maximise the selected rationale's evidence
                                  and quality ordering (see Rationale.ranking_key)
    5  candidate_rank_sum         minimise the rank sum — a DETERMINISTIC
                                  TIE-BREAK ALIGNED WITH THE LROLESIM RANKING.
                                  Nothing more. It must never be promoted above
                                  keys 1-4, and must never be described as a
                                  plausibility or pedagogical-quality metric.
    6  candidate_uris             canonical URI tuple, the final unresolved
                                  tie-break, so that two runs on identical input
                                  can never disagree
    """
    return (
        *combination_prefix_key(case, positions, minimum_rationale_size),
        rationale.ranking_key,
        sum(case.candidates[p].rank for p in positions),
        tuple(case.candidates[p].uri for p in positions),
    )


def feasible_combinations(
    case: AnswerCase, policy: str, pool: CandidatePool
) -> list[tuple[tuple[int, ...], int]]:
    """Every combination IN THE POOL that is fully coverable under one policy.

    The loop below enumerates every combination of ``pool.positions`` and
    applies no pruning by rank, no beam, no sampling and no early exit. Under
    FULL_EXACT the pool is the complete ranked candidate pool, so this is all
    C(n, 3) combinations; under POOL_EXACT it is all C(|pool|, 3) combinations
    of the bounded pool. Exhaustiveness within the pool is what lets the search
    look past the provisional LRoleSim top three at all — a lower-ranked
    candidate replaces an uncovered higher-ranked one whenever the objective
    says so, which is exactly what happens to Eisaku Satō, whose ranks 2 and 3
    have zero L1-covering eligible facts.

    Returns ``(positions, minimum_rationale_size)`` for the combinations that
    survive. "Fully coverable" and "|R*| <= ρ" collapse into one test because
    an unreachable full mask is reported as k + 1 > ρ.

    The ``cache`` keys on the SET of distinct non-zero masks, which is all the
    cardinality DP reads. Different combinations frequently induce the same
    mask set, and the DP result then cannot differ.
    """
    threshold = POLICY_THRESHOLD[policy]
    cache: dict[frozenset, int] = {}
    survivors: list[tuple[tuple[int, ...], int]] = []
    for positions in combinations(pool.positions, K_DISTRACTORS):
        masks = frozenset(m for m in case_masks(case, positions, threshold) if m)
        if masks not in cache:
            cache[masks] = minimum_cover_size(masks, K_DISTRACTORS)
        if cache[masks] <= RHO_MAX_RATIONALE_SIZE:
            survivors.append((positions, cache[masks]))
    return survivors


@dataclass(frozen=True)
class Selection:
    """The chosen distractor triple, its rationale, and the search provenance."""

    answer_uri: str
    display_label: str
    evidence_policy: str
    positions: tuple[int, ...]
    distractors: tuple[Candidate, ...]
    rationale: Rationale
    minimum_rationale_size: int
    minimum_rationale_level: str
    minimum_rationale_count_enumerated: int
    lrolesim_score_sum: float
    lrolesim_score_min: float
    candidate_rank_sum: int
    pool: CandidatePool
    feasible_combination_count: int
    combinations_tied_after_objective_key_4: int

    @property
    def search_scope(self) -> str:
        """FULL_EXACT or POOL_EXACT — the scope of the exactness claim."""
        return self.pool.scope

    @property
    def candidate_count(self) -> int:
        """The COMPLETE ranked candidate pool, never the bounded search pool."""
        return self.pool.original_candidate_count

    @property
    def enumerated_combination_count(self) -> int:
        """How many combinations were actually scored, in whichever scope."""
        return self.pool.enumerated_combination_count

    @property
    def mcq_evidence_level(self) -> str:
        """MCQ level = min over distractors of the best level any fact supplies.

        MCQ-L2 requires every distractor covered by L2; MCQ-L1 requires every
        distractor to reach at least L1 while at least one lacks L2; MCQ-L0
        means at least one distractor is covered only by snapshot absence and
        the item is diagnostic, never main-corpus.
        """
        return f"MCQ-{self.rationale.rationale_min_level}"


def select_distractors(
    case: AnswerCase,
    pool_policy: PoolPolicy = DEFAULT_POOL_POLICY,
    force_pool: bool = False,
) -> Selection | None:
    """Choose k = 3 distractors and their rationale, exactly within the pool.

    The pool is built first and decides the search scope. Under FULL_EXACT the
    pool is the complete ranked candidate pool and the result is exact over it;
    under POOL_EXACT the pool is bounded and the result is exact only within
    that bounded pool. Everything after that line is identical in both scopes —
    same coverage masks, same set-cover DP, same rationale enumeration and
    ranking, same six-key objective — so no scientific behaviour depends on
    which scope was taken, only the set of candidates it ranged over.

    Policy order is ``strict-l2 -> main-l1 -> diagnostic-l0`` and the FIRST
    policy with at least one feasible full-coverage combination is selected. A
    weaker policy is never mixed in to rescue a stronger one, and a
    diagnostic-l0 result is never silently reported as if it were main-corpus
    evidence.

    Within a policy the objective is evaluated in two stages, which is exact:

    * keys 1-3 are cheap and are computed for every feasible combination;
    * key 4 — the fourteen-field rationale key — is materialised only for the
      combinations still tied on keys 1-3.

    That is not a shortcut. The objective is lexicographic, so a combination
    that has already lost on keys 1-3 can never be rescued by keys 4-6, and its
    rationale key would change nothing. Every surviving combination is then
    ordered by the complete six-key tuple.
    """
    pool = build_candidate_pool(case, policy=pool_policy, force_pool=force_pool)
    for policy in POLICY_ORDER:
        survivors = feasible_combinations(case, policy, pool)
        if not survivors:
            continue

        best_prefix = min(
            combination_prefix_key(case, positions, size) for positions, size in survivors
        )
        finalists: list[tuple[tuple, tuple[int, ...], int, str, list[Rationale]]] = []
        for positions, size in survivors:
            if combination_prefix_key(case, positions, size) != best_prefix:
                continue
            ranked = rank_minimum_rationales(case, positions, policy)
            if ranked is None:
                continue
            exact_size, level, rationales = ranked
            key = combination_objective_key(case, positions, exact_size, rationales[0])
            finalists.append((key, positions, exact_size, level, rationales))
        if not finalists:
            continue

        finalists.sort(key=lambda item: item[0])
        key, positions, size, level, rationales = finalists[0]
        # Combinations still tied after key 4 are exactly the ones key 5 decides.
        tied = sum(1 for item in finalists if item[0][3] == key[3])
        scores = [case.candidates[p].score for p in positions]
        return Selection(
            answer_uri=case.answer_uri,
            display_label=case.display_label,
            evidence_policy=policy,
            positions=positions,
            distractors=tuple(case.candidates[p] for p in positions),
            rationale=rationales[0],
            minimum_rationale_size=size,
            minimum_rationale_level=level,
            minimum_rationale_count_enumerated=len(rationales),
            lrolesim_score_sum=sum(scores),
            lrolesim_score_min=min(scores),
            candidate_rank_sum=sum(case.candidates[p].rank for p in positions),
            pool=pool,
            feasible_combination_count=len(survivors),
            combinations_tied_after_objective_key_4=tied,
        )
    return None


# --------------------------------------------------------------------------
# Canonical output record
# --------------------------------------------------------------------------


def canonical_record(case: AnswerCase, selection: Selection) -> dict:
    """A deterministic, JSON-serialisable view of one selection.

    Every collection is emitted in a canonical order — distractors in position
    order, which is the bit order of every mask on the record, and rationale
    facts sorted by canonical identity — so that two runs on the same input
    produce byte-identical JSON. The scientific caveats travel WITH the record
    rather than living only in a report, because a record read on its own must
    not be mistakable for a claim about the world.

    Each rationale fact carries its own coverage mask, so a reader can verify
    by eye that the masks OR to full coverage, and that IN and OUT facts of the
    same predicate are listed and masked separately.
    """
    rationale = selection.rationale
    facts = sorted(
        (
            {
                "predicate_uri": case.facts[index].quality.predicate_uri,
                "direction": case.facts[index].quality.direction,
                "counterpart_uri": case.facts[index].quality.counterpart_uri,
                "display_label": case.facts[index].quality.display_label,
                "template_id": case.facts[index].quality.template_id,
                "verbalizable": case.facts[index].quality.verbalizable,
                "pedagogical_tier": case.facts[index].quality.pedagogical_tier,
                "coverage_mask": mask,
            }
            for index, mask in zip(rationale.fact_indices, rationale.coverage_masks)
        ),
        key=lambda row: (row["predicate_uri"], row["direction"], row["counterpart_uri"]),
    )
    return {
        "answer_uri": selection.answer_uri,
        "display_label": selection.display_label,
        "evidence_policy": selection.evidence_policy,
        "k": K_DISTRACTORS,
        "rho": RHO_MAX_RATIONALE_SIZE,
        # Search scope, pool policy, pool sizes, the rescued candidates and BOTH
        # optimality claims. This block travels with every record precisely so
        # that the difference between "exact over the complete ranked candidate
        # pool" and "exact within the bounded candidate pool" can never be lost
        # between the kernel and the paper.
        **selection.pool.provenance(case),
        "feasible_combination_count": selection.feasible_combination_count,
        "combinations_tied_after_objective_key_4":
            selection.combinations_tied_after_objective_key_4,
        "distractors": [
            {
                "position": position,
                "candidate_uri": candidate.uri,
                "lrolesim_rank": candidate.rank,
                "lrolesim_score": candidate.score,
                "best_evidence_level": rationale.per_candidate_best_level[position],
            }
            for position, candidate in enumerate(selection.distractors)
        ],
        "lrolesim_score_sum": selection.lrolesim_score_sum,
        "lrolesim_score_min": selection.lrolesim_score_min,
        "candidate_rank_sum": selection.candidate_rank_sum,
        "minimum_rationale_size": selection.minimum_rationale_size,
        "minimum_rationale_level": selection.minimum_rationale_level,
        "minimum_rationale_count_enumerated": selection.minimum_rationale_count_enumerated,
        "rationale": facts,
        "rationale_ranking_key": rationale.ranking_key,
        "rationale_min_level": rationale.rationale_min_level,
        "mcq_evidence_level": selection.mcq_evidence_level,
        "coverage_mask": rationale.coverage_mask,
        "full_coverage": rationale.coverage_mask == (1 << K_DISTRACTORS) - 1,
        "local_candidate_pool_anonymity_count":
            rationale.local_candidate_pool_anonymity_count,
        "local_candidate_pool_anonymity_ratio":
            rationale.local_candidate_pool_anonymity_ratio,
        "direct_identifier_flag": rationale.direct_identifier_flag,
        "local_candidate_pool_anonymity_note": LOCAL_ANONYMITY_NOTE,
        "candidate_rank_sum_note": RANK_SUM_NOTE,
        "lrolesim_role_note": LROLESIM_ROLE_NOTE,
        "open_world_note": OPEN_WORLD_NOTE,
    }
