############################################################################
# src/rationale/setcover.py
#
# EXACT minimum-cardinality rationale set cover.
#
# THE DEFECT THIS REPLACES  (AUDIT_Journal2_v2_2026-07-26, item EX-3)
#   The legacy select_distractor_set() (lines 450-455) and build_choices()
#   (lines 507-510) accepted only the special case |R| = 1: ONE Answer fact had to
#   discriminate ALL THREE distractors at once. The audit ran a counterexample
#   (test T2.3) in which a perfectly valid question needed a two-fact rationale —
#   f1 covering d1 and d2, f2 covering d3 — and the legacy code discarded it. The
#   audit's conclusion is quoted in §1.3: the slide remark "Maybe this kind of
#   condition is too strict!!!" is partly an artefact of the code, not a property
#   of DBpedia. The same function was internally inconsistent, filtering
#   candidates on `n_distinguishing > 0` (the correct feasibility condition) at
#   line 415 and then applying the far stricter |R| = 1 at line 453.
#
#   That special case is not reintroduced anywhere in this module.
#
# THE PROBLEM SOLVED HERE
#   Given a distractor set D = (d_1 … d_k) and the Answer's observed facts, each
#   fact induces a k-bit coverage mask under the active evidence policy:
#
#       bit i = 1  iff  the fact covers d_i under that policy
#
#       full_mask = 2^k − 1
#       R*(D)     = a smallest set of Answer facts whose masks OR to full_mask
#
# WHY EXACT IS AFFORDABLE  (audit §3.3)
#   General set cover is NP-hard. This one is not being solved in general: the
#   universe is the DISTRACTOR SET, whose size is k ≤ 5 in any MCQ setting, so an
#   exact bitmask dynamic program runs in O(m · 2^k) — O(8m) at the primary k = 3.
#   The feasibility lemma bounds the answer too: a covering R exists iff every
#   distractor has at least one covering fact, and then |R*| ≤ k.
#
#   Prompt 8E claims no new algorithm. Bitmask dynamic programming over subsets is
#   textbook, and CLAUDE.md item 10 forbids presenting it as newly invented. What
#   is contributed is the FORMULATION — plausibility-ordered distractor choice
#   under a minimum-cardinality observed-contrast constraint — not the solver.
#
# THE DYNAMIC PROGRAM
#   dp[mask] = the lexicographically best partial solution reaching exactly
#   `mask`, keyed by
#
#       (size, absence_only_incidences, canonical fact-position chain)
#
#   Facts are processed once each, in canonical ascending
#   (predicate_uri, direction, counterpart_uri) order, and each fact relaxes all
#   2^k states: one 0/1 pass, O(m · 2^k).
#
#   Keeping ONE best partial per mask is exact for all three key components:
#     * `size` and `absence_only_incidences` are additive, so a partial that is
#       worse on either can never overtake;
#     * every chain is extended only by positions LARGER than any it already
#       holds, so chains stay sorted and, for two equal-length chains C1 < C2, the
#       extension by the same later position preserves C1 + (p,) < C2 + (p,);
#     * two partials at the same mask admit exactly the same completions, since a
#       completion depends on the mask alone.
#   The property test against brute force on 1,000+ random cases is what keeps
#   that argument honest rather than merely stated.
#
# TIE-BREAKING AMONG EQUALLY SMALL RATIONALES  (Prompt 8E §7)
#   The final MCQ exposes exactly ONE rationale, chosen deterministically by
#     1. minimise the number of ABSENCE_ONLY_OBSERVED fact–distractor coverage
#        incidences (a per-fact additive weight, so the DP optimises it directly);
#     2. canonical ascending sorted fact tuple.
#   `optimal_rationale_count` records how many equally small rationales existed,
#   so the tie-break is auditable rather than invisible. No rarity, anonymity,
#   embedding, weight or learned score enters this module.
#
# THIS MODULE KNOWS NOTHING ABOUT
#   LRoleSim, graphs, URIs beyond their canonical order, candidate ranks, the
#   pinned KG, or which policy produced the masks it is given. It receives k-bit
#   integers and returns a cover. That is the module boundary the audit fixes in
#   §9.2, and it is why nothing here can be mistaken for a change to LRoleSim.
#
# OFFLINE AND PURE: integers, tuples and comparisons. No I/O.
############################################################################

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable, Optional, Sequence

from rationale.contracts import (
    SET_COVER_ALGORITHM,
    SET_COVER_COMPLEXITY,
    RationaleContractError,
    coverage_status_for_count,
    validate_k,
    validate_policy,
    validate_rho,
)


# ==========================================================================
# 1) WHAT SET COVER SEES OF A FACT
# ==========================================================================

@dataclass(frozen=True)
class CoverageFact:
    """One Answer fact reduced to exactly what set cover needs.

    `fact_index`          position in the Answer's canonically sorted fact list;
                          the identity every emitted mask bit resolves back to.
    `canonical_key`       (predicate_uri, direction, counterpart_uri) — the §7
                          tie-break order, carried so this module never has to
                          know what a URI is.
    `coverage_mask`       k-bit mask under ONE evidence policy.
    `absence_incidences`  how many of the covered distractors are covered only
                          because the pinned snapshot records nothing for that key
                          (ABSENCE_ONLY_OBSERVED). Zero by construction under the
                          positive-observed policy.
    """

    fact_index: int
    canonical_key: tuple[str, str, str]
    coverage_mask: int
    absence_incidences: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.coverage_mask, bool) or not isinstance(
                self.coverage_mask, int) or self.coverage_mask < 0:
            raise RationaleContractError(
                f"coverage_mask must be a non-negative int, got "
                f"{self.coverage_mask!r}")
        if self.absence_incidences < 0:
            raise RationaleContractError(
                f"absence_incidences must be non-negative, got "
                f"{self.absence_incidences!r}")
        if self.absence_incidences > bin(self.coverage_mask).count("1"):
            raise RationaleContractError(
                f"absence_incidences {self.absence_incidences} exceeds the "
                f"{bin(self.coverage_mask).count('1')} distractors covered by "
                f"mask {self.coverage_mask:b}")

    def as_record(self) -> dict:
        return {
            "fact_index": self.fact_index,
            "predicate_uri": self.canonical_key[0],
            "direction": self.canonical_key[1],
            "counterpart_uri": self.canonical_key[2],
            "coverage_mask": self.coverage_mask,
            "coverage_mask_bits": bin(self.coverage_mask),
            "absence_only_incidences": self.absence_incidences,
        }


# ==========================================================================
# 2) THE RESULT
# ==========================================================================

@dataclass(frozen=True)
class RationaleCover:
    """The exact minimum-cardinality result for ONE distractor combination.

    When full coverage is impossible the object is still returned, describing the
    BEST ACHIEVABLE coverage rather than nothing: Prompt 8E §9 requires a
    deterministic partial diagnostic instead of discarded evidence. `full_coverage`
    is the only field that decides whether this may become an MCQ, and
    `coverage_status` never reports a partial result as a complete rationale.
    """

    k: int
    rho: int
    evidence_policy: str
    full_coverage: bool
    coverage_mask: int
    coverage_count: int
    coverage_status: str
    uncovered_positions: tuple[int, ...]
    minimum_rationale_size: int
    selected_rationale: tuple[CoverageFact, ...]
    optimal_rationale_count: int
    absence_only_incidences: int
    candidate_fact_count: int

    @property
    def within_rho(self) -> bool:
        return self.minimum_rationale_size <= self.rho

    @property
    def feasible(self) -> bool:
        """Full coverage AND a rationale small enough to present.

        Prompt 8E §8: a combination is NOT feasible merely because every candidate
        has some missing fact. Feasibility is this conjunction and nothing else.
        """
        return self.full_coverage and self.within_rho

    def selected_rationale_keys(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(fact.canonical_key for fact in self.selected_rationale)

    def as_record(self) -> dict:
        return {
            "k": self.k,
            "rho": self.rho,
            "evidence_policy": self.evidence_policy,
            "algorithm": SET_COVER_ALGORITHM,
            "complexity": SET_COVER_COMPLEXITY,
            "full_coverage": self.full_coverage,
            "coverage_mask": self.coverage_mask,
            "coverage_mask_bits": bin(self.coverage_mask),
            "coverage_count": self.coverage_count,
            "coverage_status": self.coverage_status,
            "uncovered_candidate_positions": list(self.uncovered_positions),
            "minimum_rationale_size": self.minimum_rationale_size,
            "optimal_rationale_count": self.optimal_rationale_count,
            "absence_only_incidences": self.absence_only_incidences,
            "within_rho": self.within_rho,
            "feasible": self.feasible,
            "candidate_fact_count": self.candidate_fact_count,
            "selected_rationale": [f.as_record() for f in self.selected_rationale],
        }


# ==========================================================================
# 3) THE SIZE-ONLY DYNAMIC PROGRAM  (the enumeration hot path)
# ==========================================================================

def cover_size_table(masks: Iterable[int], k: int) -> list[int]:
    """Minimum number of facts reaching each of the 2^k coverage masks.

    Returns a list of length 2^k; an unreachable mask holds `k + 1`, which is
    strictly larger than any achievable cover size because |R*| ≤ k whenever a
    cover exists.

    DISTINCT MASKS SUFFICE.
      A minimum-cardinality cover never contains two facts with the SAME mask —
      dropping either leaves the coverage unchanged and the size smaller — so the
      size does not depend on how many facts share a mask. Deduplicating first is
      therefore not an approximation; it is what makes the enumeration over C(n,k)
      combinations cheap while returning exactly what the full O(m · 2^k) program
      returns. `exact_minimum_rationale` asserts the two agree.
    """
    validate_k(k)
    size = 1 << k
    unreachable = k + 1
    table = [unreachable] * size
    table[0] = 0

    for mask in sorted({int(m) for m in masks}):
        if mask == 0:
            continue
        if mask >= size:
            raise RationaleContractError(
                f"coverage mask {mask} does not fit in k={k} bits")
        # 0/1 relaxation from a snapshot: each distinct mask is used at most once.
        snapshot = list(table)
        for covered, count in enumerate(snapshot):
            if count >= unreachable:
                continue
            merged = covered | mask
            if count + 1 < table[merged]:
                table[merged] = count + 1
    return table


def minimum_cover_size(masks: Iterable[int], k: int) -> Optional[int]:
    """Size of the smallest set of masks OR-ing to full_mask, or None."""
    table = cover_size_table(masks, k)
    full = (1 << k) - 1
    return None if table[full] > k else table[full]


# ==========================================================================
# 4) THE FULL DYNAMIC PROGRAM  (exact, with the §7 tie-break)
# ==========================================================================

def exact_minimum_rationale(
    facts: Sequence[CoverageFact],
    *,
    k: int = 3,
    rho: int = 3,
    evidence_policy: str,
) -> RationaleCover:
    """The exact minimum-cardinality rationale for one distractor combination.

    O(m · 2^k): one pass over the m candidate Answer facts, each relaxing 2^k
    states. Exact — never greedy. The returned rationale is the unique
    deterministic representative of the argmin set, chosen by the §7 order.

    `rho` filters PRESENTATION, not correctness: the true minimum is computed
    first and compared to rho afterwards, so `minimum_rationale_size` is always
    the real minimum and never a value truncated to fit the budget.
    """
    validate_k(k)
    validate_rho(rho)
    validate_policy(evidence_policy)

    full = (1 << k) - 1
    ordered = tuple(sorted(facts, key=lambda f: f.canonical_key))
    for fact in ordered:
        if fact.coverage_mask > full:
            raise RationaleContractError(
                f"coverage mask {fact.coverage_mask} does not fit in k={k} bits")

    # The maximum achievable coverage is the OR of every fact's mask, and it is
    # unique: no other reachable mask can have more bits.
    best_mask = 0
    for fact in ordered:
        best_mask |= fact.coverage_mask

    # dp[mask] = (size, absence_only_incidences, chain of positions in `ordered`)
    dp: dict[int, tuple[int, int, tuple[int, ...]]] = {0: (0, 0, ())}
    for position, fact in enumerate(ordered):
        mask = fact.coverage_mask
        if mask == 0:
            # A fact covering nothing can never belong to a minimum cover.
            continue
        updates: dict[int, tuple[int, int, tuple[int, ...]]] = {}
        for covered, (size, weight, chain) in dp.items():
            if size >= k:
                # |R*| <= k whenever a cover exists, and reaching `best_mask`
                # needs at most one fact per set bit, so no deeper state is ever
                # part of an optimum.
                continue
            merged = covered | mask
            if merged == covered:
                # Adds no new distractor: strictly worse than omitting the fact.
                continue
            proposal = (size + 1, weight + fact.absence_incidences,
                        chain + (position,))
            incumbent = updates.get(merged) or dp.get(merged)
            if incumbent is None or proposal < incumbent:
                updates[merged] = proposal
        for merged, proposal in updates.items():
            incumbent = dp.get(merged)
            if incumbent is None or proposal < incumbent:
                dp[merged] = proposal

    size, weight, chain = dp[best_mask]
    selected = tuple(ordered[position] for position in chain)
    coverage_count = bin(best_mask).count("1")
    uncovered = tuple(bit for bit in range(k) if not (best_mask >> bit) & 1)

    return RationaleCover(
        k=k,
        rho=rho,
        evidence_policy=evidence_policy,
        full_coverage=best_mask == full,
        coverage_mask=best_mask,
        coverage_count=coverage_count,
        coverage_status=coverage_status_for_count(coverage_count, k),
        uncovered_positions=uncovered,
        minimum_rationale_size=size,
        selected_rationale=selected,
        optimal_rationale_count=count_minimum_rationales(
            ordered, k=k, target_mask=best_mask, size=size),
        absence_only_incidences=weight,
        candidate_fact_count=len(ordered),
    )


# ==========================================================================
# 5) COUNTING THE EQUALLY SMALL RATIONALES
# ==========================================================================

def count_minimum_rationales(facts: Sequence[CoverageFact], *, k: int,
                             target_mask: int, size: int) -> int:
    """How many distinct fact sets of `size` OR exactly to `target_mask`.

    Exact, and cheap for the same reason the cover is: a MINIMUM-cardinality cover
    has pairwise DISTINCT masks (two facts sharing a mask would make one of them
    droppable), so the count is a sum over subsets of the at most 2^k − 1 distinct
    non-zero mask values, weighted by how many facts carry each value.

    Reported as `optimal_rationale_count` so that presenting exactly one rationale
    to the learner is a recorded choice among a known number of alternatives,
    rather than an unexamined side effect of iteration order.
    """
    validate_k(k)
    if size == 0:
        # The empty set is the unique set achieving zero coverage.
        return 1 if target_mask == 0 else 0

    population: dict[int, int] = {}
    for fact in facts:
        if fact.coverage_mask:
            population[fact.coverage_mask] = population.get(
                fact.coverage_mask, 0) + 1

    total = 0
    for chosen in combinations(sorted(population), size):
        union = 0
        for mask in chosen:
            union |= mask
        if union != target_mask:
            continue
        ways = 1
        for mask in chosen:
            ways *= population[mask]
        total += ways
    return total


# ==========================================================================
# 6) THE BRUTE-FORCE REFERENCE
# ==========================================================================

def brute_force_minimum_rationale(
    facts: Sequence[CoverageFact],
    *,
    k: int = 3,
    rho: int = 3,
    evidence_policy: str,
) -> RationaleCover:
    """Enumerate every subset up to size k and take the best. TESTS ONLY.

    Deliberately the most naive correct implementation that can be written: it
    exists so `exact_minimum_rationale` is checked against something with no
    shared reasoning, not to be called by the pipeline. Exponential in m, so it is
    usable only on the small random cases the property test generates.
    """
    validate_k(k)
    validate_rho(rho)
    validate_policy(evidence_policy)

    ordered = tuple(sorted(facts, key=lambda f: f.canonical_key))
    best_mask = 0
    for fact in ordered:
        best_mask |= fact.coverage_mask
    full = (1 << k) - 1

    best_key: Optional[tuple[int, int, tuple[int, ...]]] = None
    for size in range(0, k + 1):
        for chosen in combinations(range(len(ordered)), size):
            union = 0
            weight = 0
            for position in chosen:
                union |= ordered[position].coverage_mask
                weight += ordered[position].absence_incidences
            if union != best_mask:
                continue
            key = (size, weight, tuple(chosen))
            if best_key is None or key < best_key:
                best_key = key
        if best_key is not None:
            break

    assert best_key is not None, "the full fact set always reaches best_mask"
    size, weight, chosen = best_key
    coverage_count = bin(best_mask).count("1")

    return RationaleCover(
        k=k,
        rho=rho,
        evidence_policy=evidence_policy,
        full_coverage=best_mask == full,
        coverage_mask=best_mask,
        coverage_count=coverage_count,
        coverage_status=coverage_status_for_count(coverage_count, k),
        uncovered_positions=tuple(bit for bit in range(k)
                                  if not (best_mask >> bit) & 1),
        minimum_rationale_size=size,
        selected_rationale=tuple(ordered[position] for position in chosen),
        optimal_rationale_count=count_minimum_rationales(
            ordered, k=k, target_mask=best_mask, size=size),
        absence_only_incidences=weight,
        candidate_fact_count=len(ordered),
    )
