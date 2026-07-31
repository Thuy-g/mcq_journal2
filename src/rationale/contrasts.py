############################################################################
# src/rationale/contrasts.py
#
# Set-aware observed contrast between one Answer and one candidate.
#
# THE DEFECT THIS MODULE REPLACES  (AUDIT_Journal2_v2_2026-07-26, EX-6 and §3.4)
#   The legacy distinguishing_facts() treated a MISSING TRIPLE as a valid
#   contrast, which is invalid under the Open World Assumption, and it compared
#   raw edge sets element-by-element with no notion of a predicate's object SET.
#   Two consequences followed:
#
#     * a predicate with several objects was handled as if it had one, so
#       "the Answer's object is not the candidate's object" was reported even when
#       the candidate also had the Answer's object among its other objects;
#     * absence and positive alternative were the same thing, so the strongest and
#       the weakest evidence the snapshot can offer were indistinguishable.
#
# WHAT REPLACES IT
#   For an entity x and key κ = (predicate_uri, direction), the OBSERVED
#   COUNTERPART SET is
#
#       O_x(κ) = { counterpart_uri : (κ, counterpart_uri) observed for x }
#
#   A predicate may connect to zero, one or many counterparts; nothing here
#   assumes single-valuedness. Each Answer fact f = (κ, o_A) is then classified
#   against O_d(κ) into exactly one of three statuses, and each KEY is classified
#   into exactly one of six set relations.
#
# DIRECTION IS PART OF THE KEY
#   IN and OUT facts are never combined. `counterpart_uri` is the OBJECT of an OUT
#   fact and the SUBJECT of an IN fact (AUDIT item EX-12), so merging the two
#   directions under one predicate would compare a node's subjects with its
#   objects and call the difference evidence.
#
# CANONICAL URI EQUALITY ONLY
#   Membership and set relations use string equality on canonical URIs. Prompt 8E
#   adds no ontology subsumption, no geographical containment, no owl:sameAs
#   resolution, no property-hierarchy reasoning and no inference. Any of those
#   would change which facts count as contrasts without changing any name in the
#   output, which is exactly the kind of silent semantic drift the audit flags.
#
# OPEN WORLD
#   Nothing here emits a negative fact. ABSENCE_ONLY_OBSERVED names an absence in
#   ONE SNAPSHOT and is never read as "the triple is false" (CLAUDE.md item 7).
#
# OFFLINE AND PURE: dictionaries, frozensets and comparisons. No I/O.
############################################################################

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

from rationale.contracts import (
    COVERING_STATUSES,
    EVIDENCE_ABSENCE_ONLY_OBSERVED,
    EVIDENCE_POSITIVE_ALTERNATIVE_OBSERVED,
    EVIDENCE_SHARED_OBSERVED,
    RELATION_ANSWER_STRICT_SUBSET,
    RELATION_CANDIDATE_KEY_ABSENT,
    RELATION_CANDIDATE_STRICT_SUBSET,
    RELATION_DISJOINT,
    RELATION_EQUAL,
    RELATION_PARTIAL_OVERLAP,
    AnswerFact,
    FactKey,
    RationaleContractError,
    sort_answer_facts,
    validate_policy,
)

#: {(predicate_uri, direction): frozenset[counterpart_uri]}
CounterpartSets = Mapping[tuple[str, str], frozenset]


# ==========================================================================
# 1) OBSERVED COUNTERPART SETS
# ==========================================================================

def build_counterpart_sets(facts: Iterable[AnswerFact]) -> dict[tuple[str, str], frozenset]:
    """O_x(κ) for every key κ observed for one entity.

    Returned keyed by the plain tuple (predicate_uri, direction) rather than by
    FactKey, because this mapping is looked up once per (fact, candidate) pair in
    the enumeration hot path and a dataclass hash there would cost more than it
    documents. FactKey remains the public spelling in every emitted record.

    An entity with no observed fact for a key simply has no entry: an empty set
    and a missing key are the same observation here, and
    `observed_counterparts()` normalises both to the empty frozenset.
    """
    grouped: dict[tuple[str, str], set] = {}
    for fact in facts:
        grouped.setdefault((fact.predicate_uri, fact.direction), set()).add(
            fact.counterpart_uri)
    return {key: frozenset(value) for key, value in grouped.items()}


def observed_counterparts(sets: CounterpartSets, key: tuple[str, str]) -> frozenset:
    """O_x(κ), empty when the entity has no observed fact for that key."""
    return sets.get(key, frozenset())


# ==========================================================================
# 2) OBJECT-SET RELATION  (Prompt 8E §5)
# ==========================================================================

def classify_object_sets(answer_set: frozenset,
                         candidate_set: frozenset) -> str:
    """Exactly one deterministic label for the relation O_A(κ) vs O_d(κ).

    The six labels are total and mutually exclusive over non-empty O_A(κ):

        CANDIDATE_KEY_ABSENT       O_d(κ) is empty
        EQUAL                      the two sets are the same set
        ANSWER_STRICT_SUBSET       O_A(κ) ⊊ O_d(κ)
        CANDIDATE_STRICT_SUBSET    O_d(κ) ⊊ O_A(κ)
        PARTIAL_OVERLAP            they meet, neither contains the other
        DISJOINT                   they are both non-empty and do not meet

    CANDIDATE_KEY_ABSENT is checked FIRST and is not merged into DISJOINT: "the
    candidate has other counterparts, none of them the Answer's" and "the pinned
    snapshot records nothing at all for this key on this candidate" are different
    observations, and only the first can ever support POSITIVE_ALTERNATIVE.
    """
    if not candidate_set:
        return RELATION_CANDIDATE_KEY_ABSENT
    if answer_set == candidate_set:
        return RELATION_EQUAL
    if answer_set < candidate_set:
        return RELATION_ANSWER_STRICT_SUBSET
    if candidate_set < answer_set:
        return RELATION_CANDIDATE_STRICT_SUBSET
    if answer_set & candidate_set:
        return RELATION_PARTIAL_OVERLAP
    return RELATION_DISJOINT


# ==========================================================================
# 3) EVIDENCE STATUS OF ONE ANSWER FACT AGAINST ONE CANDIDATE  (§5)
# ==========================================================================

def evidence_status(answer_counterpart: str,
                    candidate_set: frozenset) -> str:
    """Classify f = (κ, o_A) against O_d(κ). Exactly one of three statuses.

        SHARED_OBSERVED                 o_A ∈ O_d(κ)
        POSITIVE_ALTERNATIVE_OBSERVED   o_A ∉ O_d(κ), O_d(κ) non-empty
        ABSENCE_ONLY_OBSERVED           o_A ∉ O_d(κ), O_d(κ) empty

    A SHARED_OBSERVED fact never covers the candidate under either policy: the
    Answer and the candidate agree on it in the snapshot, so it discriminates
    nothing. That is the property the legacy code lost by comparing whole edge
    sets without grouping by key.

    Prompt 8E's §5 wording adds "and o_A is not exactly the same as O_d(κ)" to the
    positive branch; that clause is implied by o_A ∉ O_d(κ) and is therefore not
    re-tested here — if o_A were the sole element of O_d(κ) it would be a member.
    """
    if answer_counterpart in candidate_set:
        return EVIDENCE_SHARED_OBSERVED
    if candidate_set:
        return EVIDENCE_POSITIVE_ALTERNATIVE_OBSERVED
    return EVIDENCE_ABSENCE_ONLY_OBSERVED


def covers_under_policy(status: str, policy: str) -> bool:
    """Whether `status` counts as coverage under `policy`.

    The single place the two policies differ, so they cannot drift apart or be
    mixed by an intermediate call site.
    """
    return status in COVERING_STATUSES[validate_policy(policy)]


# ==========================================================================
# 4) THE FULL ANSWER-CANDIDATE CONTRAST
# ==========================================================================

@dataclass(frozen=True)
class FactEvidence:
    """How one Answer fact stands against one candidate in the pinned snapshot."""

    fact_index: int
    evidence_status: str
    object_set_relation: str
    answer_object_set_size: int
    candidate_object_set_size: int

    def as_record(self) -> dict:
        return {
            "fact_index": self.fact_index,
            "evidence_status": self.evidence_status,
            "object_set_relation": self.object_set_relation,
            "answer_object_set_size": self.answer_object_set_size,
            "candidate_object_set_size": self.candidate_object_set_size,
        }


@dataclass(frozen=True)
class CandidateContrast:
    """The observed contrast between one Answer and one candidate.

    `covering_fact_indices` is precomputed per policy because the combination
    search asks the same question C(n, 3) times; the per-policy sets are the only
    thing set cover needs from this module.
    """

    candidate_uri: str
    candidate_rank: int
    evidence: tuple[FactEvidence, ...]
    covering_fact_indices: Mapping[str, frozenset]

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.evidence:
            counts[item.evidence_status] = counts.get(item.evidence_status, 0) + 1
        return counts

    def relation_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.evidence:
            counts[item.object_set_relation] = (
                counts.get(item.object_set_relation, 0) + 1)
        return counts

    def has_coverage(self, policy: str) -> bool:
        """Whether ANY Answer fact covers this candidate under `policy`.

        This is the per-candidate half of the audit's feasibility lemma (§3.3): a
        rationale covering a distractor set exists iff every distractor has at
        least one covering fact. It is a NECESSARY condition and is never used as
        a sufficient one — feasibility of a triple is decided by the exact
        set-cover result, never by this predicate (Prompt 8E §8).
        """
        return bool(self.covering_fact_indices[validate_policy(policy)])


def contrast_answer_with_candidate(
    answer_facts: Sequence[AnswerFact],
    answer_sets: CounterpartSets,
    candidate_sets: CounterpartSets,
    *,
    candidate_uri: str,
    candidate_rank: int,
) -> CandidateContrast:
    """Classify every Answer fact against one candidate.

    `answer_facts` must already be in canonical ascending order; the returned
    fact indices are positions in that order and are the identity every mask bit
    and every rationale record refers to.
    """
    evidence: list[FactEvidence] = []
    covering: dict[str, set[int]] = {policy: set() for policy in COVERING_STATUSES}

    for index, fact in enumerate(answer_facts):
        key = (fact.predicate_uri, fact.direction)
        answer_set = observed_counterparts(answer_sets, key)
        candidate_set = observed_counterparts(candidate_sets, key)
        status = evidence_status(fact.counterpart_uri, candidate_set)
        relation = classify_object_sets(answer_set, candidate_set)
        evidence.append(FactEvidence(
            fact_index=index,
            evidence_status=status,
            object_set_relation=relation,
            answer_object_set_size=len(answer_set),
            candidate_object_set_size=len(candidate_set),
        ))
        for policy, statuses in COVERING_STATUSES.items():
            if status in statuses:
                covering[policy].add(index)

    return CandidateContrast(
        candidate_uri=candidate_uri,
        candidate_rank=candidate_rank,
        evidence=tuple(evidence),
        covering_fact_indices={policy: frozenset(indices)
                               for policy, indices in covering.items()},
    )


@dataclass(frozen=True)
class AnswerContrastTable:
    """Every Answer fact against every ranked candidate, for one Answer.

    Built once per Answer and reused by the combination search, the rho ablation
    and the partial diagnostics, so those three never disagree about what the
    snapshot says.
    """

    answer_uri: str
    graph_fingerprint: str
    facts: tuple[AnswerFact, ...]
    contrasts: tuple[CandidateContrast, ...]

    @property
    def fact_count(self) -> int:
        return len(self.facts)

    @property
    def candidate_count(self) -> int:
        return len(self.contrasts)

    def candidate_uris(self) -> tuple[str, ...]:
        return tuple(c.candidate_uri for c in self.contrasts)

    def covering_fact_bitset(self, candidate_position: int, policy: str) -> int:
        """Facts covering one candidate, as an int with one bit per fact index.

        The combination search needs, for each of C(n, k) triples, the mask class
        of every fact. Holding the per-candidate coverage as an integer turns that
        inner question into a handful of bitwise operations on m-bit integers
        instead of an m-step Python loop, without changing a single decision: the
        bits are exactly `covering_fact_indices[policy]`.
        """
        indices = self.contrasts[candidate_position].covering_fact_indices[
            validate_policy(policy)]
        bits = 0
        for index in indices:
            bits |= 1 << index
        return bits

    def candidates_with_coverage(self, policy: str) -> tuple[int, ...]:
        """Positions of candidates having at least one covering fact.

        Diagnostic only — see CandidateContrast.has_coverage.
        """
        return tuple(position for position, contrast in enumerate(self.contrasts)
                     if contrast.has_coverage(policy))


def build_answer_contrast_table(
    *,
    answer_uri: str,
    graph_fingerprint: str,
    answer_facts: Iterable[AnswerFact],
    candidate_facts: Mapping[str, Sequence[AnswerFact]],
    candidate_order: Sequence[tuple[str, int]],
) -> AnswerContrastTable:
    """Assemble the whole contrast table for one Answer.

    `candidate_order` is the frozen Prompt-8D ranking as (candidate_uri, rank)
    pairs, in rank order. Candidate POSITION in this table is rank - 1, and every
    mask bit produced downstream is a position in this sequence, so the reported
    distractor of a bit can never drift from the ranked candidate it came from.

    A candidate with no observed fact at all is legitimate and is NOT dropped: it
    still occupies a position, and every Answer fact scores ABSENCE_ONLY_OBSERVED
    against it. Dropping it would silently shrink the search space.
    """
    facts = sort_answer_facts(answer_facts)

    canonical_keys = [fact.canonical_key for fact in facts]
    if len(set(canonical_keys)) != len(canonical_keys):
        raise RationaleContractError(
            f"{answer_uri}: two Answer facts share the canonical key "
            f"(predicate_uri, direction, counterpart_uri); the §7 tie-break "
            f"requires that order to be total")

    for fact in facts:
        if fact.graph_fingerprint != graph_fingerprint:
            raise RationaleContractError(
                f"{answer_uri}: Answer fact {fact.canonical_key} carries graph "
                f"fingerprint {fact.graph_fingerprint!r}, expected "
                f"{graph_fingerprint!r}")

    answer_sets = build_counterpart_sets(facts)

    contrasts: list[CandidateContrast] = []
    for candidate_uri, rank in candidate_order:
        if candidate_uri == answer_uri:
            raise RationaleContractError(
                f"{answer_uri}: the Answer appears in its own candidate list")
        own_facts = candidate_facts.get(candidate_uri, ())
        for fact in own_facts:
            if fact.graph_fingerprint != graph_fingerprint:
                raise RationaleContractError(
                    f"{answer_uri}: candidate {candidate_uri} carries graph "
                    f"fingerprint {fact.graph_fingerprint!r}, expected "
                    f"{graph_fingerprint!r}")
        contrasts.append(contrast_answer_with_candidate(
            facts,
            answer_sets,
            build_counterpart_sets(own_facts),
            candidate_uri=candidate_uri,
            candidate_rank=rank,
        ))

    return AnswerContrastTable(
        answer_uri=answer_uri,
        graph_fingerprint=graph_fingerprint,
        facts=facts,
        contrasts=tuple(contrasts),
    )
