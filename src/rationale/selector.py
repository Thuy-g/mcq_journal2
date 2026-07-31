############################################################################
# src/rationale/selector.py
#
# Evidence-aware exact search over EVERY k-candidate combination.
#
# WHY EXHAUSTIVE, AND WHY NOT THE PROVISIONAL TOP THREE
#   Prompt 8D published a `provisional_lrolesim_top3` for each Answer and marked
#   every row is_final_distractor = false. Those three are a STRUCTURAL diagnostic:
#   they are the three most plausible candidates, chosen with no reference to
#   whether any rationale can discriminate them. Treating them as the distractor
#   set would make rationale feasibility a filter applied after the fact — exactly
#   the mistake the legacy pipeline made, where an Answer whose top candidate
#   happened to share every observed fact simply yielded nothing.
#
#   This module searches the COMPLETE Prompt-8D ranking instead, so an uncovered
#   top-three candidate can be replaced by a lower-ranked but rationale-feasible
#   one. The largest ranking holds 49 candidates, so exact enumeration of all
#   C(49, 3) = 18,424 combinations is affordable and no heuristic is needed.
#
# WHY THE SEARCH IS AFFORDABLE
#   Coverage of a candidate by an Answer fact does not depend on which OTHER
#   candidates are in the combination, so the contrast table is built once per
#   Answer (contrasts.py) and each combination only has to ask which mask classes
#   its three candidates induce. Held as one integer per candidate with one bit per
#   Answer fact, that question is a handful of bitwise operations rather than a
#   loop over m facts, and the at most 2^k − 1 distinct mask classes it produces
#   feed the same dynamic program setcover.py exposes. `_mask_class_census` and
#   `exact_minimum_rationale` therefore agree by construction, and a test asserts
#   it on real data.
#
# WHAT IS DETERMINISTIC HERE  (Prompt 8E §8, §9)
#   Selection among full-coverage combinations, in order:
#     1. maximise the sum of the three LRoleSim scores;
#     2. maximise the minimum LRoleSim score among the three;
#     3. minimise minimum-rationale cardinality;
#     4. minimise the sum of candidate ranks;
#     5. canonical ascending tuple of candidate URIs.
#   Partial diagnostics, in order:
#     1. maximise coverage count;  2. maximise the score sum;
#     3. minimise the rationale size used for that maximum coverage;
#     4. minimise the rank sum;    5. canonical candidate URI tuple.
#   Every LRoleSim score is READ from the frozen Prompt-8D handoff. Nothing in
#   this module recomputes, rescales or re-ranks one (CLAUDE.md items 2 and 3).
#
# POLICY PRIORITY
#   positive-observed is searched first. snapshot-observed is searched only when
#   the first yields no feasible combination, and its result is labelled
#   ALGORITHM_SELECTED_SNAPSHOT_OBSERVED_REQUIRES_HUMAN_VALIDATION. The two are
#   never mixed inside one selection.
#
# WHAT THIS MODULE MUST NOT DO  (Prompt 8E §9)
#   No class selection, no member mapping, no graph construction, no LRoleSim run
#   for a fallback class. Prompt 8D holds rankings for the Prompt-8C selected class
#   ONLY, so a fallback class has no ranking to search and inventing one here would
#   silently produce numbers with no frozen provenance. An Answer with no
#   full-coverage combination is reported as REQUIRES_FALLBACK_CLASS_GRAPH_LROLESIM_RUN
#   and left for a separate task.
#
# OFFLINE AND PURE: integers, tuples and comparisons. No I/O, no network.
############################################################################

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from math import comb
from typing import Iterable, Mapping, Optional, Sequence

from rationale.contracts import (
    DEFAULT_K,
    DEFAULT_RHO,
    EVIDENCE_ABSENCE_ONLY_OBSERVED,
    FACT_SOURCE_PINNED_LOCAL_KG,
    POLICY_POSITIVE_OBSERVED,
    POLICY_PRIORITY,
    POLICY_SNAPSHOT_OBSERVED,
    REQUIRES_FALLBACK_CLASS,
    RHO_ABLATION_VALUES,
    SELECTION_NO_FULL_COVERAGE,
    SELECTION_PRIMARY_NOT_READY,
    SELECTION_STATUS_FOR_POLICY,
    HUMAN_VALIDATION_NOT_CHECKED,
    RationaleContractError,
    coverage_status_for_count,
    validate_k,
    validate_policy,
    validate_rho,
)
from rationale.contrasts import AnswerContrastTable
from rationale.setcover import (
    CoverageFact,
    RationaleCover,
    cover_size_table,
    exact_minimum_rationale,
)

#: How many feasible combinations per policy the audit record keeps. The full
#: enumeration is exact but 18,424 rows for one Answer would bloat the evidence
#: package without adding evidence: the counts below are exact, and the ordering
#: is reproducible from the frozen inputs.
AUDIT_TOP_COMBINATIONS = 20


# ==========================================================================
# 1) INPUT VIEWS
# ==========================================================================

@dataclass(frozen=True)
class RankedCandidateView:
    """One frozen Prompt-8D rank. Read-only; nothing here re-ranks."""

    rank: int
    canonical_candidate_uri: str
    candidate_local_index: int
    score: float


@dataclass(frozen=True)
class AnswerSelectionInput:
    """Everything the search needs for ONE Answer, all of it frozen upstream."""

    answer_uri: str
    answer_local_index: int
    display_label: str
    pilot_slot: int
    selected_class_uri: str
    graph_fingerprint: str
    ranker_name: str
    measure: str
    lrolesim_beta: float
    iterations: int
    iteration_mode: str
    ranked_candidates: tuple[RankedCandidateView, ...]
    table: AnswerContrastTable
    primary_or_diagnostic: str = "primary"

    def __post_init__(self) -> None:
        if self.table.answer_uri != self.answer_uri:
            raise RationaleContractError(
                f"contrast table is for {self.table.answer_uri!r}, not "
                f"{self.answer_uri!r}")
        if self.table.graph_fingerprint != self.graph_fingerprint:
            raise RationaleContractError(
                f"{self.answer_uri}: contrast table fingerprint "
                f"{self.table.graph_fingerprint!r} != handoff fingerprint "
                f"{self.graph_fingerprint!r}")
        ranked = tuple(c.canonical_candidate_uri for c in self.ranked_candidates)
        if ranked != self.table.candidate_uris():
            raise RationaleContractError(
                f"{self.answer_uri}: the contrast table's candidate order differs "
                f"from the frozen ranking order")
        if self.answer_uri in ranked:
            raise RationaleContractError(
                f"{self.answer_uri}: the Answer appears among its own candidates")
        if len(set(ranked)) != len(ranked):
            raise RationaleContractError(
                f"{self.answer_uri}: a candidate appears twice in the ranking")

    @property
    def candidate_count(self) -> int:
        return len(self.ranked_candidates)


# ==========================================================================
# 2) ONE COMBINATION
# ==========================================================================

@dataclass(frozen=True)
class CombinationOutcome:
    """One three-candidate combination under ONE evidence policy.

    Carries only what selection and the audit need; the tie-broken rationale is
    materialised lazily by `rationale_cover_for`, because computing it for all
    31,327 combinations would produce evidence nobody reads.
    """

    positions: tuple[int, ...]
    candidate_uris: tuple[str, ...]
    ranks: tuple[int, ...]
    scores: tuple[float, ...]
    score_sum: float
    score_min: float
    rank_sum: int
    coverage_mask: int
    coverage_count: int
    minimum_rationale_size: int
    full_coverage: bool

    @property
    def coverage_status(self) -> str:
        return coverage_status_for_count(self.coverage_count,
                                         len(self.positions))

    @property
    def uncovered_positions(self) -> tuple[int, ...]:
        return tuple(bit for bit in range(len(self.positions))
                     if not (self.coverage_mask >> bit) & 1)

    def uncovered_candidate_uris(self) -> tuple[str, ...]:
        return tuple(self.candidate_uris[bit] for bit in self.uncovered_positions)

    def selection_key(self) -> tuple:
        """Prompt 8E §8, as one comparable tuple. Smallest wins.

        Maximisation is expressed as negation, which is exact for IEEE doubles, so
        the order does not depend on any epsilon.
        """
        return (-self.score_sum, -self.score_min, self.minimum_rationale_size,
                self.rank_sum, self.candidate_uris)

    def partial_key(self) -> tuple:
        """Prompt 8E §9, as one comparable tuple. Smallest wins."""
        return (-self.coverage_count, -self.score_sum,
                self.minimum_rationale_size, self.rank_sum, self.candidate_uris)

    def as_record(self) -> dict:
        return {
            "candidate_positions": list(self.positions),
            "candidate_uris": list(self.candidate_uris),
            "candidate_ranks": list(self.ranks),
            "lrolesim_scores": [repr(score) for score in self.scores],
            "lrolesim_score_sum": repr(self.score_sum),
            "lrolesim_score_min": repr(self.score_min),
            "candidate_rank_sum": self.rank_sum,
            "coverage_mask": self.coverage_mask,
            "coverage_mask_bits": bin(self.coverage_mask),
            "coverage_count": self.coverage_count,
            "coverage_status": self.coverage_status,
            "minimum_rationale_size": self.minimum_rationale_size,
            "full_coverage": self.full_coverage,
        }


# ==========================================================================
# 3) THE MASK CENSUS
# ==========================================================================

def _mask_class_census(bitsets: Sequence[int], fact_count: int,
                       k: int) -> tuple[int, ...]:
    """The distinct non-zero coverage-mask classes induced by k candidates.

    `bitsets[i]` holds one bit per Answer fact, set when that fact covers
    candidate i under the active policy. For mask value v, the facts whose class is
    exactly v are those covering every candidate in v and no candidate outside it,
    so class v is present iff

        (⋂_{i ∈ v} bitsets[i]) ∩ (⋂_{i ∉ v} ¬bitsets[i])  ≠  ∅

    This returns exactly the set of masks a per-fact loop would produce, and is
    used only because the same question is asked C(n, k) times.
    """
    universe = (1 << fact_count) - 1
    present: list[int] = []
    for value in range(1, 1 << k):
        selected = universe
        for index, bits in enumerate(bitsets):
            selected &= bits if (value >> index) & 1 else (universe ^ bits)
            if not selected:
                break
        if selected:
            present.append(value)
    return tuple(present)


def _coverage_facts_for_combination(
    table: AnswerContrastTable,
    positions: Sequence[int],
    policy: str,
) -> tuple[CoverageFact, ...]:
    """The per-fact CoverageFacts for one combination, for the exact DP.

    Built only for combinations that are actually reported. `absence_incidences`
    counts the fact–distractor coverage incidences that rest on absence alone; it
    is zero for every fact under positive-observed, because that policy does not
    treat absence as coverage at all.
    """
    validate_policy(policy)
    facts: list[CoverageFact] = []
    contrasts = [table.contrasts[position] for position in positions]
    for index, fact in enumerate(table.facts):
        mask = 0
        absence = 0
        for bit, contrast in enumerate(contrasts):
            if index not in contrast.covering_fact_indices[policy]:
                continue
            mask |= 1 << bit
            if (contrast.evidence[index].evidence_status
                    == EVIDENCE_ABSENCE_ONLY_OBSERVED):
                absence += 1
        if mask:
            facts.append(CoverageFact(
                fact_index=index,
                canonical_key=fact.canonical_key,
                coverage_mask=mask,
                absence_incidences=absence,
            ))
    return tuple(facts)


def rationale_cover_for(
    table: AnswerContrastTable,
    positions: Sequence[int],
    *,
    policy: str,
    k: int = DEFAULT_K,
    rho: int = DEFAULT_RHO,
) -> RationaleCover:
    """The exact, tie-broken minimum rationale for one reported combination."""
    return exact_minimum_rationale(
        _coverage_facts_for_combination(table, positions, policy),
        k=k, rho=rho, evidence_policy=policy)


# ==========================================================================
# 4) THE EXHAUSTIVE SEARCH
# ==========================================================================

@dataclass(frozen=True)
class PolicySearch:
    """Every combination for one Answer under one evidence policy."""

    evidence_policy: str
    k: int
    candidate_count: int
    combination_count: int
    full_coverage_outcomes: tuple[CombinationOutcome, ...]
    best_partial: Optional[CombinationOutcome]
    candidates_with_any_coverage: int

    def feasible(self, rho: int) -> tuple[CombinationOutcome, ...]:
        """Full coverage AND minimum rationale within the presentation budget."""
        return tuple(outcome for outcome in self.full_coverage_outcomes
                     if outcome.minimum_rationale_size <= rho)

    def best(self, rho: int) -> Optional[CombinationOutcome]:
        feasible = self.feasible(rho)
        if not feasible:
            return None
        return min(feasible, key=lambda outcome: outcome.selection_key())

    def top(self, rho: int, limit: int = AUDIT_TOP_COMBINATIONS
            ) -> tuple[CombinationOutcome, ...]:
        return tuple(sorted(self.feasible(rho),
                            key=lambda outcome: outcome.selection_key())[:limit])


def search_all_combinations(
    selection_input: AnswerSelectionInput,
    *,
    policy: str,
    k: int = DEFAULT_K,
) -> PolicySearch:
    """Enumerate every k-candidate combination of the COMPLETE ranking.

    Exact: no pruning by rank, no beam, no early exit on the first feasible
    combination. A lower-ranked candidate replaces an uncovered higher-ranked one
    whenever the objective says so, which is the whole point of searching the full
    list rather than the provisional top three.
    """
    validate_k(k)
    validate_policy(policy)
    table = selection_input.table
    n = selection_input.candidate_count
    fact_count = table.fact_count

    bitsets = [table.covering_fact_bitset(position, policy) for position in range(n)]
    scores = [candidate.score for candidate in selection_input.ranked_candidates]
    ranks = [candidate.rank for candidate in selection_input.ranked_candidates]
    uris = [candidate.canonical_candidate_uri
            for candidate in selection_input.ranked_candidates]

    full_mask = (1 << k) - 1
    # There are at most 2^(2^k − 1) distinct censuses, so the dynamic program runs
    # a bounded number of times however many combinations there are.
    dp_cache: dict[tuple[int, ...], tuple[int, int, bool]] = {}

    full_outcomes: list[CombinationOutcome] = []
    best_partial: Optional[CombinationOutcome] = None
    best_partial_key: Optional[tuple] = None

    for positions in combinations(range(n), k):
        census = _mask_class_census([bitsets[p] for p in positions], fact_count, k)
        resolved = dp_cache.get(census)
        if resolved is None:
            best_mask = 0
            for value in census:
                best_mask |= value
            sizes = cover_size_table(census, k)
            resolved = (best_mask, sizes[best_mask], best_mask == full_mask)
            dp_cache[census] = resolved
        best_mask, minimum_size, is_full = resolved

        combo_scores = tuple(scores[p] for p in positions)
        outcome = CombinationOutcome(
            positions=positions,
            candidate_uris=tuple(uris[p] for p in positions),
            ranks=tuple(ranks[p] for p in positions),
            scores=combo_scores,
            score_sum=sum(combo_scores),
            score_min=min(combo_scores),
            rank_sum=sum(ranks[p] for p in positions),
            coverage_mask=best_mask,
            coverage_count=bin(best_mask).count("1"),
            minimum_rationale_size=minimum_size,
            full_coverage=is_full,
        )
        if is_full:
            full_outcomes.append(outcome)
        key = outcome.partial_key()
        if best_partial_key is None or key < best_partial_key:
            best_partial_key = key
            best_partial = outcome

    return PolicySearch(
        evidence_policy=policy,
        k=k,
        candidate_count=n,
        combination_count=comb(n, k) if n >= k else 0,
        full_coverage_outcomes=tuple(full_outcomes),
        best_partial=best_partial,
        candidates_with_any_coverage=len(table.candidates_with_coverage(policy)),
    )


# ==========================================================================
# 5) SELECTION FOR ONE ANSWER
# ==========================================================================

@dataclass(frozen=True)
class RhoAblationRow:
    """One (Answer, policy, rho) cell of the §10 ablation.

    The ablation OBSERVES the primary search; it never re-runs it with different
    parameters, so it cannot silently move the primary selection, which stays at
    rho = 3 under positive-observed first.
    """

    answer_uri: str
    evidence_policy: str
    rho: int
    full_coverage_exists: bool
    feasible_triple_count: int
    best_candidate_uris: tuple[str, ...]
    best_candidate_ranks: tuple[int, ...]
    best_rationale_size: Optional[int]
    selection_policy_note: str


@dataclass(frozen=True)
class AnswerSelection:
    """The Prompt-8E result for ONE primary Answer."""

    answer_uri: str
    ready: bool
    status: str
    evidence_policy: Optional[str]
    selected: Optional[CombinationOutcome]
    cover: Optional[RationaleCover]
    searches: Mapping[str, PolicySearch]
    ablation: tuple[RhoAblationRow, ...]
    partial_covers: Mapping[str, Optional[RationaleCover]]
    rho: int = DEFAULT_RHO
    k: int = DEFAULT_K

    @property
    def algorithm_selected(self) -> bool:
        return self.selected is not None

    @property
    def requires_fallback_class(self) -> bool:
        return self.status == SELECTION_NO_FULL_COVERAGE

    @property
    def full_coverage_exists_but_exceeds_rho(self) -> bool:
        """Full coverage exists, but no minimum rationale fits the budget.

        Unreachable at the primary configuration: the feasibility lemma gives
        |R*| <= k, and the primary run sets rho = k = 3, so a full-coverage
        combination always fits. The flag exists because this layer is generic over
        1 <= k <= 5 and rho is a free presentation parameter, and because "no
        combination covers all three" and "a covering rationale exists but is too
        long to present" are different findings that must not be collapsed into one
        status.
        """
        if self.selected is not None:
            return False
        return any(bool(search.full_coverage_outcomes)
                   for search in self.searches.values())


def select_for_answer(
    selection_input: AnswerSelectionInput,
    *,
    k: int = DEFAULT_K,
    rho: int = DEFAULT_RHO,
    rho_values: Sequence[int] = RHO_ABLATION_VALUES,
) -> AnswerSelection:
    """Search, select and ablate for one ready primary Answer.

    Priority (Prompt 8E §6): full coverage under positive-observed; otherwise full
    coverage under snapshot-observed, explicitly marked as requiring human
    validation; otherwise no full-coverage algorithm-selected MCQ and a
    deterministic partial diagnostic instead.
    """
    validate_k(k)
    validate_rho(rho)

    searches = {policy: search_all_combinations(selection_input, policy=policy, k=k)
                for policy in POLICY_PRIORITY}

    chosen_policy: Optional[str] = None
    chosen: Optional[CombinationOutcome] = None
    for policy in POLICY_PRIORITY:
        best = searches[policy].best(rho)
        if best is not None:
            chosen_policy = policy
            chosen = best
            break

    cover: Optional[RationaleCover] = None
    if chosen is not None and chosen_policy is not None:
        cover = rationale_cover_for(selection_input.table, chosen.positions,
                                    policy=chosen_policy, k=k, rho=rho)
        if not cover.feasible:
            raise RationaleContractError(
                f"{selection_input.answer_uri}: the selected combination is not "
                f"feasible under the exact set cover; the enumeration and the "
                f"dynamic program disagree")
        status = SELECTION_STATUS_FOR_POLICY[chosen_policy]
    else:
        status = SELECTION_NO_FULL_COVERAGE

    # Partial diagnostics are computed for BOTH policies whenever no full-coverage
    # MCQ was selected: discarding the evidence would leave the fallback decision
    # with nothing to stand on (Prompt 8E §9).
    partial_covers: dict[str, Optional[RationaleCover]] = {}
    if chosen is None:
        for policy, search in searches.items():
            if search.best_partial is None:
                partial_covers[policy] = None
                continue
            partial_covers[policy] = rationale_cover_for(
                selection_input.table, search.best_partial.positions,
                policy=policy, k=k, rho=rho)

    ablation: list[RhoAblationRow] = []
    for policy in POLICY_PRIORITY:
        search = searches[policy]
        for ablation_rho in rho_values:
            best = search.best(ablation_rho)
            ablation.append(RhoAblationRow(
                answer_uri=selection_input.answer_uri,
                evidence_policy=policy,
                rho=ablation_rho,
                full_coverage_exists=bool(search.full_coverage_outcomes),
                feasible_triple_count=len(search.feasible(ablation_rho)),
                best_candidate_uris=best.candidate_uris if best else (),
                best_candidate_ranks=best.ranks if best else (),
                best_rationale_size=(best.minimum_rationale_size if best else None),
                selection_policy_note=(
                    "maximise score sum, then minimum score, then minimise "
                    "rationale size, rank sum, candidate URI tuple"),
            ))

    return AnswerSelection(
        answer_uri=selection_input.answer_uri,
        ready=True,
        status=status,
        evidence_policy=chosen_policy,
        selected=chosen,
        cover=cover,
        searches=searches,
        ablation=tuple(ablation),
        partial_covers=partial_covers,
        rho=rho,
        k=k,
    )


def not_ready_selection(answer_uri: str, *, k: int = DEFAULT_K,
                        rho: int = DEFAULT_RHO) -> AnswerSelection:
    """The record for a primary Answer with no Prompt-8D ranking at all.

    Sulfuric acid. It keeps a PRIMARY row so the denominator stays at nine: an
    Answer that failed earlier in the pipeline is a failure of the pipeline, and
    dropping it would inflate every rate computed from this file.
    """
    return AnswerSelection(
        answer_uri=answer_uri,
        ready=False,
        status=SELECTION_PRIMARY_NOT_READY,
        evidence_policy=None,
        selected=None,
        cover=None,
        searches={},
        ablation=(),
        partial_covers={},
        rho=rho,
        k=k,
    )


# ==========================================================================
# 6) RECORD BUILDERS
# ==========================================================================

def selected_rationale_records(selection: AnswerSelection,
                               selection_input: AnswerSelectionInput) -> list[dict]:
    """One record per fact of the ONE selected rationale (Prompt 8E §12).

    `per_candidate_evidence_status` reports the RAW status against each of the
    three distractors, including SHARED_OBSERVED where it applies, so a reader can
    see why a fact covers two distractors and not the third without re-deriving it.
    """
    if selection.cover is None or selection.selected is None:
        return []
    policy = selection.evidence_policy
    assert policy is not None
    table = selection_input.table
    positions = selection.selected.positions
    uris = selection.selected.candidate_uris

    records = []
    for fact in selection.cover.selected_rationale:
        covered = [uris[bit] for bit in range(selection.k)
                   if (fact.coverage_mask >> bit) & 1]
        statuses = {}
        for bit, position in enumerate(positions):
            statuses[uris[bit]] = (
                table.contrasts[position].evidence[fact.fact_index].evidence_status)
        records.append({
            "answer_uri": selection.answer_uri,
            "evidence_policy": policy,
            "predicate_uri": fact.canonical_key[0],
            "direction": fact.canonical_key[1],
            "counterpart_uri": fact.canonical_key[2],
            "coverage_mask": fact.coverage_mask,
            "coverage_mask_bits": bin(fact.coverage_mask),
            "covered_candidate_uris": covered,
            "per_candidate_evidence_status": statuses,
            "absence_only_incidences": fact.absence_incidences,
            "graph_fingerprint": selection_input.graph_fingerprint,
            "source": FACT_SOURCE_PINNED_LOCAL_KG,
            "requires_human_validation": True,
            "human_validation_status": HUMAN_VALIDATION_NOT_CHECKED,
            "publishable_final": False,
        })
    return records
