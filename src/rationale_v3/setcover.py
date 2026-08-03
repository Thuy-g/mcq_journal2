############################################################################
# src/rationale_v3/setcover.py
#
# EXACT minimum-cardinality rationale set cover, plus complete enumeration of
# the equally-smallest rationales so selector.py can rank among them.
#
# UNCHANGED BY R1
#   The dynamic program is the Prompt-8E/8F solver: an exact O(m * 2^k) bitmask
#   DP that replaced the legacy |R| = 1 special case (AUDIT item EX-3, which
#   discarded valid two-fact rationales). 8E's `absence_incidences` is the
#   general `tie_weight` here, so with the extra features off this module and
#   `rationale.setcover` agree fact for fact; a test asserts that directly.
#
# WHY THE DP DOES NOT PICK THE RATIONALE
#   Several ordering keys — the rationale's minimum evidence level, redundancy
#   across the set, local candidate-pool anonymity — are properties of the WHOLE
#   SET and cannot be folded into a per-fact additive weight. The DP answers
#   only what it can answer exactly and cheaply, the minimum cardinality.
#
# WHY COMPLETE ENUMERATION IS AFFORDABLE
#   A minimum cover never contains two facts with the same coverage mask, so it
#   picks from PAIRWISE DISTINCT mask classes, of which there are at most
#   2^k - 1 = 7 at k = 3. The walk is bounded by `limit` and the result says
#   whether the bound was reached.
#
# Set cover and bitmask DP over subsets are textbook (CLAUDE.md item 10); the
# contribution is the formulation around them. OFFLINE AND PURE, no I/O.
############################################################################

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
from typing import Iterable, Optional, Sequence

from rationale_v3.contracts import (
    DEFAULT_K,
    DEFAULT_MAX_MINIMUM_RATIONALE_CANDIDATES,
    DEFAULT_RHO,
    ENUMERATION_BOUNDED,
    ENUMERATION_COMPLETE,
    SET_COVER_ALGORITHM,
    SET_COVER_COMPLEXITY,
    RationaleV3ContractError,
    coverage_status_for_count,
    validate_k,
    validate_policy,
    validate_rho,
)

VERSION = "rationale_v3.setcover/1.0.0"


# --- 1) WHAT SET COVER SEES OF A FACT ----------------------------------------

@dataclass(frozen=True)
class CoverageFact:
    """One Answer fact reduced to exactly what set cover needs.

    `fact_index`     position in the Answer's canonically sorted fact list.
    `canonical_key`  (predicate_uri, direction, counterpart_uri) — the final
                     tie-break order, carried so this module never has to know
                     what a URI is.
    `coverage_mask`  k-bit mask under ONE evidence policy.
    `tie_weight`     an additive per-fact penalty the DP minimises after size.
                     Prompt 8E used the count of absence-only coverage
                     incidences here; V3 passes the count of L0 incidences,
                     which is the same number whenever V3's extra features are
                     switched off.
    """

    fact_index: int
    canonical_key: tuple[str, str, str]
    coverage_mask: int
    tie_weight: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.coverage_mask, bool) or not isinstance(
                self.coverage_mask, int) or self.coverage_mask < 0:
            raise RationaleV3ContractError(
                f"coverage_mask must be a non-negative int, got "
                f"{self.coverage_mask!r}")
        if self.tie_weight < 0:
            raise RationaleV3ContractError(
                f"tie_weight must be non-negative, got {self.tie_weight!r}")
        if self.tie_weight > bin(self.coverage_mask).count("1"):
            raise RationaleV3ContractError(
                f"tie_weight {self.tie_weight} exceeds the "
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
            "tie_weight": self.tie_weight,
        }


# --- 2) THE RESULT -----------------------------------------------------------

@dataclass(frozen=True)
class RationaleCover:
    """The exact minimum-cardinality result for ONE distractor combination.

    Returned even when full coverage is impossible, describing the BEST
    ACHIEVABLE coverage rather than nothing: a deterministic partial diagnostic
    is more useful than discarded evidence, and `full_coverage` is the only field
    that decides whether this may become an MCQ.
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
    tie_weight_total: int
    candidate_fact_count: int

    @property
    def within_rho(self) -> bool:
        return self.minimum_rationale_size <= self.rho

    @property
    def feasible(self) -> bool:
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
            "tie_weight_total": self.tie_weight_total,
            "within_rho": self.within_rho,
            "feasible": self.feasible,
            "candidate_fact_count": self.candidate_fact_count,
            "selected_rationale": [f.as_record() for f in self.selected_rationale],
        }


# --- 3) THE SIZE-ONLY DYNAMIC PROGRAM  (the enumeration hot path) ------------

def cover_size_table(masks: Iterable[int], k: int) -> list[int]:
    """Minimum number of facts reaching each of the 2^k coverage masks.

    Unreachable masks hold k + 1, which is strictly larger than any achievable
    cover size because |R*| <= k whenever a cover exists.

    DISTINCT MASKS SUFFICE: a minimum cover never contains two facts with the
    same mask, so deduplicating first is not an approximation. That is what makes
    the per-combination question cheap while returning exactly what the full
    O(m · 2^k) program returns.
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
            raise RationaleV3ContractError(
                f"coverage mask {mask} does not fit in k={k} bits")
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


# --- 4) THE FULL DYNAMIC PROGRAM ---------------------------------------------

def exact_minimum_rationale(
    facts: Sequence[CoverageFact],
    *,
    k: int = DEFAULT_K,
    rho: int = DEFAULT_RHO,
    evidence_policy: str,
) -> RationaleCover:
    """The exact minimum-cardinality rationale for one distractor combination.

    O(m · 2^k): one pass over the m candidate facts, each relaxing 2^k states.
    Exact, never greedy. The representative returned is the one the Prompt-8E
    order picks — smallest (size, tie_weight, canonical position chain) — so
    with V3's extra features disabled this function and `rationale.setcover`
    agree fact for fact.

    `rho` filters PRESENTATION, not correctness: the true minimum is computed
    first and compared to rho afterwards.
    """
    validate_k(k)
    validate_rho(rho)
    validate_policy(evidence_policy)

    full = (1 << k) - 1
    ordered = tuple(sorted(facts, key=lambda f: f.canonical_key))
    for fact in ordered:
        if fact.coverage_mask > full:
            raise RationaleV3ContractError(
                f"coverage mask {fact.coverage_mask} does not fit in k={k} bits")

    best_mask = 0
    for fact in ordered:
        best_mask |= fact.coverage_mask

    dp: dict[int, tuple[int, int, tuple[int, ...]]] = {0: (0, 0, ())}
    for position, fact in enumerate(ordered):
        mask = fact.coverage_mask
        if mask == 0:
            continue
        updates: dict[int, tuple[int, int, tuple[int, ...]]] = {}
        for covered, (size, weight, chain) in dp.items():
            if size >= k:
                continue
            merged = covered | mask
            if merged == covered:
                continue
            proposal = (size + 1, weight + fact.tie_weight, chain + (position,))
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
        selected_rationale=selected,
        optimal_rationale_count=count_minimum_rationales(
            ordered, k=k, target_mask=best_mask, size=size),
        tie_weight_total=weight,
        candidate_fact_count=len(ordered),
    )


# --- 5) COUNTING AND ENUMERATING THE EQUALLY SMALL RATIONALES ----------------

def count_minimum_rationales(facts: Sequence[CoverageFact], *, k: int,
                             target_mask: int, size: int) -> int:
    """How many distinct fact sets of `size` OR exactly to `target_mask`.

    Exact and cheap: a minimum cover has pairwise distinct masks, so the count is
    a sum over subsets of the at most 2^k − 1 distinct non-zero mask values,
    weighted by how many facts carry each value.
    """
    validate_k(k)
    if size == 0:
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


@dataclass(frozen=True)
class MinimumRationaleEnumeration:
    """Every minimum-cardinality rationale, or a bounded prefix of them."""

    size: int
    target_mask: int
    total_count: int
    enumerated: tuple[tuple[CoverageFact, ...], ...]
    scope: str
    limit: int

    @property
    def complete(self) -> bool:
        return self.scope == ENUMERATION_COMPLETE

    def as_record(self) -> dict:
        return {
            "minimum_rationale_size": self.size,
            "target_mask": self.target_mask,
            "minimum_rationale_count": self.total_count,
            "enumerated_count": len(self.enumerated),
            "enumeration_scope": self.scope,
            "enumeration_limit": self.limit,
        }


def enumerate_minimum_rationales(
    facts: Sequence[CoverageFact],
    *,
    k: int,
    size: int,
    target_mask: int,
    limit: int = DEFAULT_MAX_MINIMUM_RATIONALE_CANDIDATES,
) -> MinimumRationaleEnumeration:
    """All fact sets of exactly `size` whose masks OR to `target_mask`.

    Complete unless `limit` is reached, and the result says which. `facts` must
    already be in the caller's preferred order — selector.py sorts them by the
    per-fact quality key first, so a truncated enumeration keeps the facts most
    likely to win rather than an arbitrary prefix.

    A minimum cover has pairwise DISTINCT masks, so the walk is over subsets of
    the at most 2^k − 1 distinct mask classes; within a class subset it is the
    Cartesian product of the facts carrying each class.
    """
    validate_k(k)
    if size == 0:
        empty: tuple[tuple[CoverageFact, ...], ...] = (
            ((),) if target_mask == 0 else ())
        return MinimumRationaleEnumeration(
            size=0, target_mask=target_mask, total_count=len(empty),
            enumerated=empty, scope=ENUMERATION_COMPLETE, limit=limit)

    by_mask: dict[int, list[CoverageFact]] = {}
    for fact in facts:
        if fact.coverage_mask:
            by_mask.setdefault(fact.coverage_mask, []).append(fact)

    total = 0
    collected: list[tuple[CoverageFact, ...]] = []
    truncated = False
    for classes in combinations(sorted(by_mask), size):
        union = 0
        for mask in classes:
            union |= mask
        if union != target_mask:
            continue
        groups = [by_mask[mask] for mask in classes]
        ways = 1
        for group in groups:
            ways *= len(group)
        total += ways
        if truncated:
            continue
        for chosen in product(*groups):
            if len(collected) >= limit:
                truncated = True
                break
            collected.append(tuple(chosen))

    return MinimumRationaleEnumeration(
        size=size,
        target_mask=target_mask,
        total_count=total,
        enumerated=tuple(collected),
        scope=ENUMERATION_BOUNDED if truncated else ENUMERATION_COMPLETE,
        limit=limit,
    )


# --- 6) THE BRUTE-FORCE REFERENCE --------------------------------------------

def brute_force_minimum_rationale(
    facts: Sequence[CoverageFact],
    *,
    k: int = DEFAULT_K,
    rho: int = DEFAULT_RHO,
    evidence_policy: str,
) -> RationaleCover:
    """Enumerate every subset up to size k and take the best. TESTS ONLY.

    Deliberately the most naive correct implementation that can be written: it
    exists so `exact_minimum_rationale` is checked against something sharing no
    reasoning with it, not to be called by the pipeline.
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
                weight += ordered[position].tie_weight
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
        tie_weight_total=weight,
        candidate_fact_count=len(ordered),
    )
