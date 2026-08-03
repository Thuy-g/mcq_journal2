############################################################################
# src/rationale_v3/selector.py
#
# Evidence- and quality-aware distractor selection over the frozen Prompt-8D
# rankings, with a scalable exact / pool-exact combination search.
#
# THE THREE THINGS THIS MODULE DECIDES
#   1) WHICH EVIDENCE TIER an Answer lands in: strict-L2, then main-L1, then
#      diagnostic-L0. The tier is chosen BEFORE the combination objective, so a
#      structurally attractive triple can never pull an Answer into a weaker
#      evidence tier.
#   2) WHICH THREE CANDIDATES: maximise the LRoleSim score sum, then the minimum
#      score, then minimise the rationale cardinality, then the rationale
#      evidence/quality key, then the rank sum, and only then the canonical URI
#      tuple. Every LRoleSim score is READ from the frozen Prompt-8D handoff;
#      nothing here recomputes or re-ranks one (CLAUDE.md items 2 and 3).
#   3) WHICH RATIONALE among the equally smallest. Prompt 8E broke that tie with
#      an additive weight and then URI order, which is how a Web Archive URL and
#      a counterpart containing the Answer's own name were selected. URI order
#      is now the LAST resort.
#
# WHAT R1 CHANGED HERE
#   The middle policy is `main-l1` and covers a distractor with an L1 POSITIVE
#   OBSERVED CONTRAST. Within L1 a SCOPED_EMPIRICAL annotation is preferred over
#   NONE — after the evidence profile, never in place of it. Granularity risk
#   (present or unresolved) no longer downgrades a level; it is counted, ordered
#   against, and blocks main-corpus eligibility.
#
# WHY THE SEARCH IS AFFORDABLE
#   Coverage of a candidate by a fact does not depend on the other candidates,
#   so the evidence table is built once per Answer and each combination only
#   asks which mask CLASSES its three candidates induce. Enumerating and ranking
#   every minimum-cardinality rationale runs only for combinations still tied
#   after the first three objective keys, never for all C(n, 3).
#
# WHERE THIS STOPS
#   No class selection, candidate retrieval, mapping, graph construction or
#   LRoleSim run. An Answer with no eligible full-coverage result emits a
#   fallback REQUEST. OFFLINE AND PURE: no I/O, no network.
############################################################################

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import comb
from typing import Mapping, Optional, Sequence

from rationale_v3.contracts import (
    DEFAULT_K,
    DEFAULT_MAX_EXACT_COMBINATIONS,
    DEFAULT_MAX_MINIMUM_RATIONALE_CANDIDATES,
    DEFAULT_MAX_POOL_SIZE,
    DEFAULT_POOL_EVIDENCE_RESCUE,
    DEFAULT_POOL_TOP_BY_SCORE,
    DEFAULT_RHO,
    FALLBACK_L0_ONLY,
    FALLBACK_NO_FULL_COVERAGE,
    FALLBACK_NO_QUALITY_ELIGIBLE,
    FALLBACK_SEMANTIC_RISK,
    GRANULARITY_RISK_NONE,
    LEVEL_L0,
    LEVEL_L1,
    LEVEL_L2,
    LEVEL_NOT_COVERED,
    LEVEL_ORDER,
    MAIN_CORPUS_POLICIES,
    POLICY_DIAGNOSTIC_L0,
    POLICY_MINIMUM_LEVEL,
    POLICY_PRIORITY,
    POOL_POLICY_NAME,
    SEARCH_FULL_EXACT,
    SEARCH_POOL_EXACT,
    SELECTION_NO_FULL_COVERAGE,
    SELECTION_NO_QUALITY_ELIGIBLE,
    SELECTION_PRIMARY_NOT_READY,
    SELECTION_STATUS_FOR_POLICY,
    AnswerFact,
    RationaleProposition,
    RationaleV3ContractError,
    level_at_least,
    mcq_evidence_level,
    sort_answer_facts,
    validate_k,
    validate_policy,
    validate_rho,
)
from rationale_v3.evidence import (
    EvidenceRuleBook,
    FactCandidateEvidence,
    classify_fact_against_candidate,
)
from rationale_v3.quality import FactQuality, assess_fact_quality, fact_quality_key
from rationale_v3.semantic_relations import SemanticIndex
from rationale_v3.setcover import (
    CoverageFact,
    cover_size_table,
    enumerate_minimum_rationales,
    exact_minimum_rationale,
)

VERSION = "rationale_v3.selector/2.0.0-r1"

#: How many ranked minimum rationales an audit record keeps per Answer. The
#: exact count is published separately, so this bounds the artefact, not the
#: search.
AUDIT_TOP_RATIONALES = 10

#: Descending evidence levels a rationale's minimum level can take.
_LEVELS_STRONGEST_FIRST = (LEVEL_L2, LEVEL_L1, LEVEL_L0)


# --- 1) INPUT VIEWS ----------------------------------------------------------

@dataclass(frozen=True)
class RankedCandidateView:
    """One frozen Prompt-8D rank. Read-only; nothing here re-ranks."""

    rank: int
    canonical_candidate_uri: str
    candidate_local_index: int
    score: float


@dataclass(frozen=True)
class AnswerInput:
    """Everything the search needs for ONE Answer, all frozen upstream."""

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
    answer_facts: tuple[AnswerFact, ...]
    candidate_facts: Mapping[str, tuple[AnswerFact, ...]]
    primary_or_diagnostic: str = "primary"

    def __post_init__(self) -> None:
        uris = [c.canonical_candidate_uri for c in self.ranked_candidates]
        if self.answer_uri in uris:
            raise RationaleV3ContractError(
                f"{self.answer_uri}: the Answer appears among its own candidates")
        if len(set(uris)) != len(uris):
            raise RationaleV3ContractError(
                f"{self.answer_uri}: a candidate appears twice in the ranking")
        ranks = [c.rank for c in self.ranked_candidates]
        if ranks != sorted(ranks):
            raise RationaleV3ContractError(
                f"{self.answer_uri}: ranked candidates are not in rank order")

    @property
    def candidate_count(self) -> int:
        return len(self.ranked_candidates)

    @property
    def scope(self) -> str:
        """The rule scope: the Prompt-8C selected class."""
        return self.selected_class_uri


# --- 2) THE EVIDENCE TABLE ---------------------------------------------------

@dataclass(frozen=True)
class EvidenceTable:
    """Every Answer fact against every ranked candidate, levels and quality.

    Built once per Answer and reused by the combination search and the
    diagnostics, so the two can never disagree about what the snapshot says.
    """

    answer_uri: str
    scope: str
    graph_fingerprint: str
    facts: tuple[AnswerFact, ...]
    propositions: tuple[RationaleProposition, ...]
    quality: tuple[FactQuality, ...]
    candidates: tuple[RankedCandidateView, ...]
    evidence: tuple[tuple[FactCandidateEvidence, ...], ...]
    eligible_fact_indices: tuple[int, ...]
    supporter_sets: tuple[frozenset, ...]

    @property
    def fact_count(self) -> int:
        return len(self.facts)

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    def level(self, fact_index: int, candidate_position: int) -> str:
        return self.evidence[fact_index][candidate_position].level

    def covering_bitset(self, candidate_position: int, minimum_level: str) -> int:
        """Facts reaching at least `minimum_level` against one candidate.

        One bit per fact index, so the per-combination question is a handful of
        bitwise operations rather than a loop over m facts. Only ELIGIBLE facts
        contribute: a fact removed by the predicate, object or leakage filter is
        removed from every policy, not merely deprioritised.
        """
        bits = 0
        for index in self.eligible_fact_indices:
            if level_at_least(self.level(index, candidate_position), minimum_level):
                bits |= 1 << index
        return bits

    def level_counts(self, *, eligible_only: bool = False) -> dict[str, int]:
        counts = {LEVEL_NOT_COVERED: 0, LEVEL_L0: 0, LEVEL_L1: 0, LEVEL_L2: 0}
        indices = (self.eligible_fact_indices if eligible_only
                   else range(len(self.evidence)))
        for index in indices:
            for item in self.evidence[index]:
                counts[item.level] += 1
        return counts

    def exclusion_basis_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.evidence:
            for item in row:
                counts[item.exclusion_basis] = counts.get(
                    item.exclusion_basis, 0) + 1
        return counts

    def local_anonymity(self, fact_indices: Sequence[int]) -> tuple[int, float, bool]:
        """|S_local(R)|, its ratio, and whether R identifies the Answer alone.

        S_local(R) is the set of entities in {Answer + the COMPLETE ranked
        candidate pool} that support every proposition in R. An entity supports
        a proposition exactly when the fact does not cover it, so this reuses
        the evidence table rather than recomputing support.

        This is LOCAL. It says nothing about entities of the same class absent
        from this pool, and it is named `local_candidate_pool_anonymity`
        everywhere it is written out.
        """
        pool_size = 1 + self.candidate_count          # the Answer is always in it
        if not fact_indices:
            return (pool_size, 1.0, False)
        supporters = set(range(self.candidate_count))
        for index in fact_indices:
            supporters &= self.supporter_sets[index]
            if not supporters:
                break
        count = 1 + len(supporters)                   # + the Answer itself
        return (count, count / pool_size, count == 1)


def build_evidence_table(
    answer: AnswerInput,
    *,
    semantic_index: SemanticIndex,
    rulebook: EvidenceRuleBook,
    quality_policy,
) -> EvidenceTable:
    """Classify every Answer fact against every candidate, once."""
    facts = sort_answer_facts(answer.answer_facts)
    canonical_keys = [f.canonical_key for f in facts]
    if len(set(canonical_keys)) != len(canonical_keys):
        raise RationaleV3ContractError(
            f"{answer.answer_uri}: two Answer facts share the canonical key "
            f"(predicate_uri, direction, counterpart_uri); the final tie-break "
            f"requires that order to be total")
    for fact in facts:
        if fact.graph_fingerprint != answer.graph_fingerprint:
            raise RationaleV3ContractError(
                f"{answer.answer_uri}: Answer fact {fact.canonical_key} carries "
                f"graph fingerprint {fact.graph_fingerprint!r}, expected "
                f"{answer.graph_fingerprint!r}")

    # O_d(kappa) for every candidate, built once.
    candidate_objects: dict[str, dict[tuple[str, str], list[str]]] = {}
    for candidate in answer.ranked_candidates:
        uri = candidate.canonical_candidate_uri
        grouped: dict[tuple[str, str], list[str]] = {}
        for fact in answer.candidate_facts.get(uri, ()):
            if fact.graph_fingerprint != answer.graph_fingerprint:
                raise RationaleV3ContractError(
                    f"{answer.answer_uri}: candidate {uri} carries graph "
                    f"fingerprint {fact.graph_fingerprint!r}, expected "
                    f"{answer.graph_fingerprint!r}")
            grouped.setdefault(fact.key_tuple, []).append(fact.counterpart_uri)
        candidate_objects[uri] = grouped

    propositions = tuple(RationaleProposition.from_answer_fact(f) for f in facts)
    quality = tuple(
        assess_fact_quality(answer_uri=answer.answer_uri,
                            predicate_uri=f.predicate_uri, direction=f.direction,
                            counterpart_uri=f.counterpart_uri,
                            policy=quality_policy)
        for f in facts)

    evidence: list[tuple[FactCandidateEvidence, ...]] = []
    supporters: list[frozenset] = []
    for proposition in propositions:
        row: list[FactCandidateEvidence] = []
        supporting: set[int] = set()
        for position, candidate in enumerate(answer.ranked_candidates):
            uri = candidate.canonical_candidate_uri
            objects = candidate_objects[uri].get(
                (proposition.predicate_uri, proposition.direction), [])
            item = classify_fact_against_candidate(
                proposition=proposition, candidate_uri=uri,
                candidate_objects=objects, semantic_index=semantic_index,
                rulebook=rulebook, scope=answer.scope)
            row.append(item)
            if item.level == LEVEL_NOT_COVERED:
                supporting.add(position)
        evidence.append(tuple(row))
        supporters.append(frozenset(supporting))

    return EvidenceTable(
        answer_uri=answer.answer_uri, scope=answer.scope,
        graph_fingerprint=answer.graph_fingerprint, facts=facts,
        propositions=propositions, quality=quality,
        candidates=answer.ranked_candidates, evidence=tuple(evidence),
        eligible_fact_indices=tuple(index for index, q in enumerate(quality)
                                    if q.eligible),
        supporter_sets=tuple(supporters))


# --- 3) RANKING AMONG EQUALLY MINIMUM-CARDINALITY RATIONALES -----------------

@dataclass(frozen=True)
class RationaleChoice:
    """One ranked rationale for one distractor combination."""

    fact_indices: tuple[int, ...]
    coverage_masks: tuple[int, ...]
    size: int
    rationale_min_level: str
    per_candidate_best_level: tuple[str, ...]
    l2_incidences: int
    l1_incidences: int
    l0_incidences: int
    scoped_empirical_incidences: int
    granularity_risk_incidences: int
    soft_leak_fact_count: int
    pedagogical_tier_sum: int
    unverbalizable_count: int
    label_length_sum: int
    token_count_sum: int
    redundant_key_pairs: int
    local_anonymity_count: int
    local_anonymity_ratio: float
    direct_identifier_flag: bool
    canonical_fact_tuple: tuple[tuple[str, str, str], ...]

    @property
    def mcq_evidence_level(self) -> str:
        return mcq_evidence_level(self.per_candidate_best_level)

    def ranking_key(self) -> tuple:
        """The ordering, as one comparable tuple. SMALLEST WINS.

        Hard quality filters are not here because they are FILTERS: an
        ineligible fact never reaches this function. Maximisation is expressed
        as negation, which is exact for integers and for IEEE doubles, so no
        epsilon appears anywhere. `scoped_empirical_incidences` sits AFTER the
        level profile: an annotation may order two equally strong rationales and
        may never substitute for evidence.
        """
        return (
            -LEVEL_ORDER[self.rationale_min_level],   # maximise the MCQ level
            -self.l2_incidences,                      # evidence profile
            -self.l1_incidences,
            self.l0_incidences,
            -self.scoped_empirical_incidences,        # annotation, within L1
            self.granularity_risk_incidences,         # semantic safety
            self.soft_leak_fact_count,                # leakage
            self.pedagogical_tier_sum,                # predicate/object quality
            self.unverbalizable_count,                # verbalizability
            self.label_length_sum,                    # textual complexity
            self.token_count_sum,
            self.redundant_key_pairs,                 # redundancy
            1 if self.direct_identifier_flag else 0,  # local pool anonymity
            self.canonical_fact_tuple,                # last resort only
        )

    def as_record(self) -> dict:
        return {
            "fact_indices": list(self.fact_indices),
            "minimum_rationale_size": self.size,
            "rationale_min_level": self.rationale_min_level,
            "mcq_evidence_level": self.mcq_evidence_level,
            "per_candidate_best_level": list(self.per_candidate_best_level),
            "L2_coverage_incidence_count": self.l2_incidences,
            "L1_coverage_incidence_count": self.l1_incidences,
            "L0_coverage_incidence_count": self.l0_incidences,
            "scoped_empirical_incidence_count": self.scoped_empirical_incidences,
            "semantic_granularity_risk_incidences":
                self.granularity_risk_incidences,
            "soft_leakage_fact_count": self.soft_leak_fact_count,
            "pedagogical_tier_sum": self.pedagogical_tier_sum,
            "unverbalizable_fact_count": self.unverbalizable_count,
            "label_length_sum": self.label_length_sum,
            "token_count_sum": self.token_count_sum,
            "redundant_predicate_key_pairs": self.redundant_key_pairs,
            "local_candidate_pool_anonymity_count": self.local_anonymity_count,
            "local_candidate_pool_anonymity_ratio":
                round(self.local_anonymity_ratio, 6),
            "direct_identifier_flag": self.direct_identifier_flag,
            "coverage_masks": list(self.coverage_masks),
            "rationale_facts": [
                {"predicate_uri": key[0], "direction": key[1],
                 "counterpart_uri": key[2]}
                for key in self.canonical_fact_tuple],
        }


@dataclass(frozen=True)
class RationaleRanking:
    """Every minimum-cardinality rationale for one combination, ranked."""

    evidence_policy: str
    size: int
    full_coverage: bool
    coverage_mask: int
    minimum_rationale_count: int
    enumerated_count: int
    enumeration_scope: str
    achieved_min_level: str
    ranked: tuple[RationaleChoice, ...]

    @property
    def best(self) -> Optional[RationaleChoice]:
        return self.ranked[0] if self.ranked else None

    @property
    def mcq_evidence_level(self) -> str:
        best = self.best
        return (best.mcq_evidence_level if best is not None
                else mcq_evidence_level(()))

    def as_record(self) -> dict:
        return {
            "evidence_policy": self.evidence_policy,
            "minimum_rationale_size": self.size,
            "full_coverage": self.full_coverage,
            "coverage_mask": self.coverage_mask,
            "minimum_rationale_count_before_quality_ranking":
                self.minimum_rationale_count,
            "minimum_rationale_count_enumerated": self.enumerated_count,
            "enumeration_scope": self.enumeration_scope,
            "rationale_min_level": self.achieved_min_level,
            "mcq_evidence_level": self.mcq_evidence_level,
        }


def _coverage_facts(table: EvidenceTable, positions: Sequence[int],
                    minimum_level: str) -> tuple[CoverageFact, ...]:
    """CoverageFacts for one combination at one level threshold.

    `tie_weight` counts the L0 coverage incidences, which is the same number
    Prompt 8E called `absence_incidences` whenever the extra features are off.
    """
    facts: list[CoverageFact] = []
    for index in table.eligible_fact_indices:
        mask = 0
        weight = 0
        for bit, position in enumerate(positions):
            level = table.level(index, position)
            if not level_at_least(level, minimum_level):
                continue
            mask |= 1 << bit
            if level == LEVEL_L0:
                weight += 1
        if mask:
            facts.append(CoverageFact(
                fact_index=index, canonical_key=table.facts[index].canonical_key,
                coverage_mask=mask, tie_weight=weight))
    return tuple(facts)


def rank_minimum_rationales(
    table: EvidenceTable,
    positions: Sequence[int],
    *,
    policy: str,
    k: int = DEFAULT_K,
    rho: int = DEFAULT_RHO,
    limit: int = DEFAULT_MAX_MINIMUM_RATIONALE_CANDIDATES,
) -> RationaleRanking:
    """Exact minimum cardinality, then the ranking among all rationales of that
    size.

    Two exact steps, in this order:

      * the DP gives the minimum cardinality s under the POLICY threshold;
      * the strongest level t at which a cover of the SAME size s still exists
        is found by re-running the cheap size-only DP at each level. That t IS
        `max rationale_min_level` over minimum-cardinality rationales: a size-s
        cover reaching level t+1 would make the minimum size at t+1 equal to s,
        so no stronger t was missed.

    Enumeration then walks exactly the size-s covers at level t, and the
    remaining keys order them.
    """
    validate_k(k)
    validate_rho(rho)
    validate_policy(policy)
    threshold = POLICY_MINIMUM_LEVEL[policy]
    full_mask = (1 << k) - 1

    base = exact_minimum_rationale(
        _coverage_facts(table, positions, threshold),
        k=k, rho=rho, evidence_policy=policy)
    size = base.minimum_rationale_size
    target = base.coverage_mask
    full = base.full_coverage

    achieved_level = threshold
    if full and size > 0:
        for level in _LEVELS_STRONGEST_FIRST:
            if not level_at_least(level, threshold):
                break
            facts = _coverage_facts(table, positions, level)
            if cover_size_table((f.coverage_mask for f in facts), k)[full_mask] == size:
                achieved_level = level
                break

    # Pre-sorted by the per-fact quality key so a bounded enumeration keeps the
    # facts most likely to win rather than an arbitrary prefix.
    ordered = tuple(sorted(
        _coverage_facts(table, positions, achieved_level),
        key=lambda f: fact_quality_key(table.quality[f.fact_index])))
    enumeration = enumerate_minimum_rationales(
        ordered, k=k, size=size, target_mask=full_mask if full else target,
        limit=limit)

    ranked = tuple(sorted(
        (_score_rationale(table, positions, choice, policy)
         for choice in enumeration.enumerated),
        key=lambda choice: choice.ranking_key()))

    return RationaleRanking(
        evidence_policy=policy, size=size, full_coverage=full,
        coverage_mask=target, minimum_rationale_count=enumeration.total_count,
        enumerated_count=len(enumeration.enumerated),
        enumeration_scope=enumeration.scope,
        achieved_min_level=achieved_level if full else LEVEL_NOT_COVERED,
        ranked=ranked)


def _score_rationale(table: EvidenceTable, positions: Sequence[int],
                     facts: Sequence[CoverageFact], policy: str) -> RationaleChoice:
    """Every ordering signal for one candidate rationale."""
    threshold = POLICY_MINIMUM_LEVEL[policy]
    indices = tuple(f.fact_index for f in facts)

    per_candidate: list[str] = []
    l2 = l1 = l0 = scoped = granularity = 0
    for position in positions:
        best = LEVEL_NOT_COVERED
        for index in indices:
            item = table.evidence[index][position]
            if LEVEL_ORDER[item.level] > LEVEL_ORDER[best]:
                best = item.level
            if not level_at_least(item.level, threshold):
                continue
            if item.level == LEVEL_L2:
                l2 += 1
            elif item.level == LEVEL_L1:
                l1 += 1
            elif item.level == LEVEL_L0:
                l0 += 1
            if item.scoped_empirical:
                scoped += 1
            if item.granularity_risk_status != GRANULARITY_RISK_NONE:
                granularity += 1
        per_candidate.append(best)

    rationale_min = (min(per_candidate, key=lambda level: LEVEL_ORDER[level])
                     if per_candidate else LEVEL_NOT_COVERED)

    quality = [table.quality[index] for index in indices]
    # Redundancy: two rationale facts on the SAME predicate and direction teach
    # less than two on different ones, so the pair is penalised.
    keys = [(q.predicate_uri, q.direction) for q in quality]
    redundant = sum(1 for a, b in combinations(range(len(keys)), 2)
                    if keys[a] == keys[b])
    count, ratio, direct = table.local_anonymity(indices)

    return RationaleChoice(
        fact_indices=indices,
        coverage_masks=tuple(f.coverage_mask for f in facts),
        size=len(facts), rationale_min_level=rationale_min,
        per_candidate_best_level=tuple(per_candidate),
        l2_incidences=l2, l1_incidences=l1, l0_incidences=l0,
        scoped_empirical_incidences=scoped,
        granularity_risk_incidences=granularity,
        soft_leak_fact_count=sum(1 for q in quality if q.leakage.soft_leak),
        pedagogical_tier_sum=sum(q.pedagogical_tier for q in quality),
        unverbalizable_count=sum(1 for q in quality if not q.verbalizable),
        label_length_sum=sum(q.label_length for q in quality),
        token_count_sum=sum(q.token_count for q in quality),
        redundant_key_pairs=redundant, local_anonymity_count=count,
        local_anonymity_ratio=ratio, direct_identifier_flag=direct,
        canonical_fact_tuple=tuple(sorted(f.canonical_key for f in facts)))


# --- 4) THE CANDIDATE POOL ---------------------------------------------------

@dataclass(frozen=True)
class PoolPolicy:
    """How a bounded pool is built when exact enumeration is too large."""

    max_exact_combinations: int = DEFAULT_MAX_EXACT_COMBINATIONS
    top_by_score: int = DEFAULT_POOL_TOP_BY_SCORE
    evidence_rescue: int = DEFAULT_POOL_EVIDENCE_RESCUE
    max_pool_size: int = DEFAULT_MAX_POOL_SIZE
    name: str = POOL_POLICY_NAME

    def __post_init__(self) -> None:
        if self.top_by_score + self.evidence_rescue > self.max_pool_size:
            raise RationaleV3ContractError(
                f"pool policy {self.name}: top_by_score {self.top_by_score} + "
                f"evidence_rescue {self.evidence_rescue} exceeds max_pool_size "
                f"{self.max_pool_size}")

    @classmethod
    def for_pool_size(cls, size: int, *,
                      max_exact_combinations: int = DEFAULT_MAX_EXACT_COMBINATIONS
                      ) -> "PoolPolicy":
        """The default 3:1 score-to-rescue split, scaled to `size`."""
        top = (size * 3 + 3) // 4
        return cls(max_exact_combinations=max_exact_combinations,
                   top_by_score=top, evidence_rescue=size - top,
                   max_pool_size=size, name=f"{POOL_POLICY_NAME}_M{size}")

    def as_record(self) -> dict:
        return {
            "pool_policy": self.name,
            "max_exact_combinations": self.max_exact_combinations,
            "pool_top_by_lrolesim": self.top_by_score,
            "pool_evidence_rescue": self.evidence_rescue,
            "max_pool_size": self.max_pool_size,
        }


def candidate_rescue_key(table: EvidenceTable, position: int) -> tuple:
    """Pre-combination evidence features for one candidate. SMALLEST WINS.

    Deliberately uses NOTHING that depends on which other candidates might join
    it: a rescue score that looked at combinations would need the very
    enumeration the pool exists to avoid.
    """
    best = LEVEL_NOT_COVERED
    l2 = l1 = soft = granularity = 0
    best_tier = 99
    for index in table.eligible_fact_indices:
        item = table.evidence[index][position]
        if LEVEL_ORDER[item.level] > LEVEL_ORDER[best]:
            best = item.level
        if item.level == LEVEL_L2:
            l2 += 1
        elif item.level == LEVEL_L1:
            l1 += 1
        if item.level in (LEVEL_L1, LEVEL_L2):
            best_tier = min(best_tier, table.quality[index].pedagogical_tier)
        if table.quality[index].leakage.soft_leak:
            soft += 1
        if item.granularity_risk_status != GRANULARITY_RISK_NONE:
            granularity += 1
    return (-LEVEL_ORDER[best], -l2, -l1, best_tier, soft, granularity,
            table.candidates[position].rank)


@dataclass(frozen=True)
class CandidatePool:
    """The positions the combination search will actually enumerate over."""

    scope: str
    positions: tuple[int, ...]
    original_candidate_count: int
    original_combination_count: int
    enumerated_combination_count: int
    policy: PoolPolicy
    rescued_positions: tuple[int, ...]

    @property
    def global_optimality_claim(self) -> bool:
        return self.scope == SEARCH_FULL_EXACT

    @property
    def pool_optimality_claim(self) -> bool:
        return True

    def as_record(self) -> dict:
        return {
            "search_scope": self.scope,
            "original_candidate_count": self.original_candidate_count,
            "pool_candidate_count": len(self.positions),
            "original_combination_count": self.original_combination_count,
            "enumerated_combination_count": self.enumerated_combination_count,
            "evidence_rescue_count": len(self.rescued_positions),
            "evidence_rescued_candidate_positions": list(self.rescued_positions),
            "global_optimality_claim": self.global_optimality_claim,
            "pool_optimality_claim": self.pool_optimality_claim,
            **self.policy.as_record(),
        }


def build_candidate_pool(table: EvidenceTable, *, k: int = DEFAULT_K,
                         policy: PoolPolicy = PoolPolicy(),
                         force_pool: bool = False) -> CandidatePool:
    """FULL_EXACT below the combination bound, POOL_EXACT above it.

    The pool is the top `top_by_score` candidates by frozen LRoleSim rank, plus
    up to `evidence_rescue` candidates that the rank order would have dropped
    but that carry the strongest available evidence. Without the rescue slots a
    bounded search would systematically lose the low-ranked candidates that are
    the only ones a strong rationale can discriminate.
    """
    validate_k(k)
    n = table.candidate_count
    original = comb(n, k) if n >= k else 0

    if not force_pool and original <= policy.max_exact_combinations:
        return CandidatePool(
            scope=SEARCH_FULL_EXACT, positions=tuple(range(n)),
            original_candidate_count=n, original_combination_count=original,
            enumerated_combination_count=original, policy=policy,
            rescued_positions=())

    # Positions are rank order, so the first `top_by_score` ARE the top by score.
    top = tuple(range(min(policy.top_by_score, n)))
    remaining = [p for p in range(n) if p not in set(top)]
    room = max(min(policy.evidence_rescue, policy.max_pool_size - len(top)), 0)
    rescued = tuple(sorted(
        sorted(remaining, key=lambda p: candidate_rescue_key(table, p))[:room]))
    positions = tuple(sorted(set(top) | set(rescued)))
    if len(positions) > policy.max_pool_size:
        positions = positions[:policy.max_pool_size]
        rescued = tuple(p for p in rescued if p in set(positions))

    return CandidatePool(
        scope=SEARCH_POOL_EXACT, positions=positions,
        original_candidate_count=n, original_combination_count=original,
        enumerated_combination_count=(comb(len(positions), k)
                                      if len(positions) >= k else 0),
        policy=policy, rescued_positions=rescued)


# --- 5) THE COMBINATION SEARCH -----------------------------------------------

@dataclass(frozen=True)
class CombinationOutcome:
    """One k-candidate combination under ONE evidence policy."""

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

    def objective_prefix(self) -> tuple:
        """Objective keys 1-3, which every combination can answer cheaply."""
        return (-self.score_sum, -self.score_min, self.minimum_rationale_size)

    def objective_suffix(self) -> tuple:
        """Objective keys 5-6, applied after the rationale quality key."""
        return (self.rank_sum, self.candidate_uris)

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
            "coverage_count": self.coverage_count,
            "minimum_rationale_size": self.minimum_rationale_size,
            "full_coverage": self.full_coverage,
        }


def _mask_class_census(bitsets: Sequence[int], fact_count: int,
                       k: int) -> tuple[int, ...]:
    """The distinct non-zero coverage-mask classes induced by k candidates.

    For mask value v, the facts whose class is exactly v are those covering
    every candidate in v and no candidate outside it, so class v is present iff

        (AND over i in v of bitsets[i]) AND (AND over i not in v of NOT bitsets[i])

    is non-empty. This returns exactly the set of masks a per-fact loop would
    produce, and is used only because the same question is asked C(n, k) times.
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


@dataclass(frozen=True)
class PolicySearch:
    """Every enumerated combination for one Answer under one evidence policy."""

    evidence_policy: str
    k: int
    pool: CandidatePool
    full_coverage_outcomes: tuple[CombinationOutcome, ...]
    best_partial: Optional[CombinationOutcome]
    candidates_with_any_coverage: int

    def feasible(self, rho: int) -> tuple[CombinationOutcome, ...]:
        return tuple(o for o in self.full_coverage_outcomes
                     if o.minimum_rationale_size <= rho)


def search_combinations(table: EvidenceTable, *, policy: str, k: int = DEFAULT_K,
                        pool: CandidatePool) -> PolicySearch:
    """Enumerate every k-candidate combination inside the pool. Exact for it.

    No pruning by rank, no beam, no early exit on the first feasible
    combination: a lower-ranked candidate replaces an uncovered higher-ranked
    one whenever the objective says so, which is why the search looks past the
    provisional top three at all.
    """
    validate_k(k)
    validate_policy(policy)
    threshold = POLICY_MINIMUM_LEVEL[policy]
    fact_count = table.fact_count
    full_mask = (1 << k) - 1

    bitsets = {p: table.covering_bitset(p, threshold) for p in pool.positions}
    dp_cache: dict[tuple[int, ...], tuple[int, int, bool]] = {}

    full_outcomes: list[CombinationOutcome] = []
    best_partial: Optional[CombinationOutcome] = None
    best_partial_key: Optional[tuple] = None

    for positions in combinations(pool.positions, k):
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

        scores = tuple(table.candidates[p].score for p in positions)
        ranks = tuple(table.candidates[p].rank for p in positions)
        outcome = CombinationOutcome(
            positions=positions,
            candidate_uris=tuple(table.candidates[p].canonical_candidate_uri
                                 for p in positions),
            ranks=ranks, scores=scores, score_sum=sum(scores),
            score_min=min(scores), rank_sum=sum(ranks), coverage_mask=best_mask,
            coverage_count=bin(best_mask).count("1"),
            minimum_rationale_size=minimum_size, full_coverage=is_full)
        if is_full:
            full_outcomes.append(outcome)
        partial_key = (-outcome.coverage_count, -outcome.score_sum,
                       outcome.minimum_rationale_size, outcome.rank_sum,
                       outcome.candidate_uris)
        if best_partial_key is None or partial_key < best_partial_key:
            best_partial_key, best_partial = partial_key, outcome

    return PolicySearch(
        evidence_policy=policy, k=k, pool=pool,
        full_coverage_outcomes=tuple(full_outcomes), best_partial=best_partial,
        candidates_with_any_coverage=sum(1 for p in pool.positions if bitsets[p]))


def select_best_combination(
    table: EvidenceTable, search: PolicySearch, *, rho: int = DEFAULT_RHO,
    limit: int = DEFAULT_MAX_MINIMUM_RATIONALE_CANDIDATES,
) -> Optional[tuple[CombinationOutcome, RationaleRanking]]:
    """The combination objective, with the rationale key materialised only where
    it can change the answer.

    Keys 1-3 are cheap and already computed for every combination. The rationale
    evidence/quality key is expensive, so it is built only for the combinations
    still TIED after keys 1-3 — which is exact, because a combination that loses
    on keys 1-3 cannot be rescued by the rationale key.
    """
    feasible = search.feasible(rho)
    if not feasible:
        return None

    best_prefix = min(o.objective_prefix() for o in feasible)
    tied = [o for o in feasible if o.objective_prefix() == best_prefix]

    scored: list[tuple[tuple, CombinationOutcome, RationaleRanking]] = []
    for outcome in tied:
        ranking = rank_minimum_rationales(
            table, outcome.positions, policy=search.evidence_policy,
            k=search.k, rho=rho, limit=limit)
        best = ranking.best
        if best is not None:
            scored.append(((best.ranking_key(), *outcome.objective_suffix()),
                           outcome, ranking))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    return (scored[0][1], scored[0][2])


# --- 6) SELECTION FOR ONE ANSWER ---------------------------------------------

@dataclass(frozen=True)
class AnswerSelection:
    """The R1 result for ONE Answer."""

    answer_uri: str
    ready: bool
    status: str
    evidence_policy: Optional[str]
    selected: Optional[CombinationOutcome]
    ranking: Optional[RationaleRanking]
    searches: Mapping[str, PolicySearch]
    pool: Optional[CandidatePool]
    table: Optional[EvidenceTable]
    fallback_status: str
    rho: int = DEFAULT_RHO
    k: int = DEFAULT_K

    @property
    def algorithm_selected(self) -> bool:
        return self.selected is not None

    @property
    def mcq_evidence_level(self) -> str:
        return (self.ranking.mcq_evidence_level if self.ranking is not None
                else mcq_evidence_level(()))

    @property
    def unresolved_granularity_risk(self) -> bool:
        best = self.ranking.best if self.ranking else None
        return best is not None and best.granularity_risk_incidences > 0

    @property
    def eligible_for_main_corpus(self) -> bool:
        """At least MCQ-L1, a verbalizable rationale, and no unresolved
        semantic granularity risk.

        Hard predicate/object filters and hard leakage are already guaranteed by
        construction — an ineligible fact never reaches a rationale — so what is
        left to check here is the tier, verbalizability and semantic safety.
        """
        if self.selected is None or self.ranking is None:
            return False
        if self.evidence_policy not in MAIN_CORPUS_POLICIES:
            return False
        best = self.ranking.best
        return (best is not None and best.unverbalizable_count == 0
                and best.granularity_risk_incidences == 0)

    @property
    def eligible_for_diagnostic_corpus(self) -> bool:
        return self.algorithm_selected

    @property
    def eligible_for_human_study(self) -> bool:
        return self.eligible_for_main_corpus

    @property
    def requires_fallback_class(self) -> bool:
        return bool(self.fallback_status)


def select_for_answer(
    answer: AnswerInput,
    *,
    semantic_index: SemanticIndex,
    rulebook: EvidenceRuleBook,
    quality_policy,
    k: int = DEFAULT_K,
    rho: int = DEFAULT_RHO,
    pool_policy: PoolPolicy = PoolPolicy(),
    limit: int = DEFAULT_MAX_MINIMUM_RATIONALE_CANDIDATES,
) -> AnswerSelection:
    """Search the three tiers in order and return the first that succeeds.

    strict-L2, then main-L1, then diagnostic-L0. The tier is chosen before the
    combination objective, so a structurally attractive triple never drags an
    Answer into a weaker evidence tier. A diagnostic-L0 result is returned with
    FALLBACK_CLASS_REQUIRED_L0_ONLY attached: it is an automatically generated
    diagnostic, not a main-corpus item.
    """
    validate_k(k)
    validate_rho(rho)

    table = build_evidence_table(answer, semantic_index=semantic_index,
                                 rulebook=rulebook, quality_policy=quality_policy)
    pool = build_candidate_pool(table, k=k, policy=pool_policy)

    searches: dict[str, PolicySearch] = {}
    chosen_policy: Optional[str] = None
    chosen: Optional[CombinationOutcome] = None
    ranking: Optional[RationaleRanking] = None

    for policy in POLICY_PRIORITY:
        search = search_combinations(table, policy=policy, k=k, pool=pool)
        searches[policy] = search
        if chosen is not None:
            continue
        found = select_best_combination(table, search, rho=rho, limit=limit)
        if found is not None:
            chosen_policy, (chosen, ranking) = policy, found

    if chosen is None:
        # Full coverage exists but no rationale survived quality ranking, or
        # none fits the presentation budget. Those are different findings and
        # must not be collapsed into "no coverage".
        if any(bool(s.full_coverage_outcomes) for s in searches.values()):
            status, fallback = (SELECTION_NO_QUALITY_ELIGIBLE,
                                FALLBACK_NO_QUALITY_ELIGIBLE)
        else:
            status, fallback = (SELECTION_NO_FULL_COVERAGE,
                                FALLBACK_NO_FULL_COVERAGE)
    else:
        status = SELECTION_STATUS_FOR_POLICY[chosen_policy]
        fallback = ""
        if chosen_policy == POLICY_DIAGNOSTIC_L0:
            fallback = FALLBACK_L0_ONLY
        elif ranking is not None and ranking.best is not None and (
                ranking.best.granularity_risk_incidences > 0):
            fallback = FALLBACK_SEMANTIC_RISK

    return AnswerSelection(
        answer_uri=answer.answer_uri, ready=True, status=status,
        evidence_policy=chosen_policy, selected=chosen, ranking=ranking,
        searches=searches, pool=pool, table=table, fallback_status=fallback,
        rho=rho, k=k)


def not_ready_selection(answer_uri: str, *, k: int = DEFAULT_K,
                        rho: int = DEFAULT_RHO) -> AnswerSelection:
    """The record for a primary Answer with no Prompt-8D ranking at all.

    Sulfuric acid. It keeps a PRIMARY row so the denominator stays at nine: an
    Answer that failed earlier is a failure of the pipeline, and dropping it
    would inflate every rate computed from this file.
    """
    return AnswerSelection(
        answer_uri=answer_uri, ready=False, status=SELECTION_PRIMARY_NOT_READY,
        evidence_policy=None, selected=None, ranking=None, searches={},
        pool=None, table=None, fallback_status="", rho=rho, k=k)
