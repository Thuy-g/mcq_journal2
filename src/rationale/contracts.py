############################################################################
# src/rationale/contracts.py
#
# The frozen vocabulary of the Journal-2 rationale layer.
#
# WHY A SEPARATE VOCABULARY MODULE
#   Every scientific boundary this layer must not cross is expressible as "which
#   word may be written into an output record". Putting the permitted words in one
#   module, as constants, makes the boundary checkable: a test can assert that no
#   emitted record contains a word outside this file, which is a far stronger
#   guarantee than a review convention.
#
# THE THREE DISTINCTIONS THIS FILE EXISTS TO KEEP
#
#   1) OBSERVED CONTRAST IS NOT NEGATION.
#      AUDIT_Journal2_v2_2026-07-26 §3.4 rejects the entailment spelling
#      `R ⊨ A ∧ ∀d ∈ D, R ⊭ d` outright: `⊨` is entailment, and under the Open
#      World Assumption the pinned KG not containing (d, p, o) does NOT yield
#      ¬(d, p, o). The permitted relation is the observed one,
#      `f K-contrasts (A, d) ⟺ f ∈ F_K(A) ∧ f ∉ F_K(d)`, and it is a statement
#      about the SNAPSHOT. Hence FORBIDDEN_NEGATIVE_CLAIM_PHRASES below, and hence
#      no status name in this file contains the word "false".
#
#   2) A POSITIVE ALTERNATIVE IS STRONGER EVIDENCE, STILL NOT A PROOF.
#      Observing (d, p, o′) with o′ ≠ o is much better evidence than observing
#      nothing, but for a MULTI-VALUED predicate it is not proof that (d, p, o) is
#      false — d may simply have both. Umematsu's thesis (audit §3.4) closes that
#      gap by first restricting to predicates whose object is uniquely determined;
#      Prompt 8E deliberately does NOT apply that filter, so
#      POSITIVE_ALTERNATIVE_OBSERVED is weaker than the audit's L2 and is labelled
#      as observation, never as exclusion. See PREDICATE_FUNCTIONALITY_NOTE.
#
#   3) ALGORITHM-SELECTED IS NOT PUBLISHABLE-FINAL.
#      Prompt 8E performs automatic candidate selection, not factual
#      certification. Every selected record therefore carries
#      requires_human_validation / human_validation_status / publishable_final,
#      and there is deliberately no bare `is_final_distractor = true` anywhere.
#
# DIRECTION IS PART OF THE KEY
#   `selection/contracts.py` records (AUDIT item EX-12) that the legacy
#   build_choices() emitted {"predicate", "direction", "object"} for BOTH
#   directions, so an IN edge had its SUBJECT stored under the name "object". This
#   layer inherits the corrected spelling — `counterpart_uri` — and additionally
#   makes `direction` part of the object-set key, so an IN fact and an OUT fact on
#   the same predicate can never be compared against each other.
#
# INDEPENDENCE
#   The direction spellings are redeclared here rather than imported from
#   selection.contracts, so this package has no import edge into the selection
#   layer at all (audit §9.2). src/pipeline/rationale_selection_run.py holds the
#   one cross-check that the two spellings agree, which is where a dependency
#   between the two layers legitimately belongs.
#
# OFFLINE AND PURE: constants, dataclasses and validation only.
############################################################################

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# ==========================================================================
# 0) DIRECTION  (redeclared, never imported — see the header)
# ==========================================================================

DIRECTION_OUT = "OUT"
DIRECTION_IN = "IN"
DIRECTIONS = (DIRECTION_OUT, DIRECTION_IN)

# ==========================================================================
# 1) OBJECT-SET RELATIONS  (Prompt 8E §5)
# ==========================================================================
# Computed per (Answer, candidate, key) from CANONICAL URI EQUALITY ONLY. No
# ontology subsumption, no geographical containment, no owl:sameAs, no property
# hierarchy, no inference of any kind — adding any of those would change what the
# relation means without changing its name.

RELATION_EQUAL = "EQUAL"
RELATION_ANSWER_STRICT_SUBSET = "ANSWER_STRICT_SUBSET"
RELATION_CANDIDATE_STRICT_SUBSET = "CANDIDATE_STRICT_SUBSET"
RELATION_PARTIAL_OVERLAP = "PARTIAL_OVERLAP"
RELATION_DISJOINT = "DISJOINT"
RELATION_CANDIDATE_KEY_ABSENT = "CANDIDATE_KEY_ABSENT"

OBJECT_SET_RELATIONS = (
    RELATION_EQUAL,
    RELATION_ANSWER_STRICT_SUBSET,
    RELATION_CANDIDATE_STRICT_SUBSET,
    RELATION_PARTIAL_OVERLAP,
    RELATION_DISJOINT,
    RELATION_CANDIDATE_KEY_ABSENT,
)

# ==========================================================================
# 2) EVIDENCE STATUS OF ONE ANSWER FACT AGAINST ONE CANDIDATE  (§5)
# ==========================================================================

#: o_A is among the candidate's observed counterparts for the same key.
#: The fact does NOT cover this candidate under any policy.
EVIDENCE_SHARED_OBSERVED = "SHARED_OBSERVED"

#: o_A is not among them, and the candidate has one or more OTHER observed
#: counterparts for the same key. The strongest evidence Prompt 8E produces.
EVIDENCE_POSITIVE_ALTERNATIVE_OBSERVED = "POSITIVE_ALTERNATIVE_OBSERVED"

#: o_A is not among them, and the candidate has NO observed counterpart for the
#: key at all. Absence in one snapshot. Never a negation.
EVIDENCE_ABSENCE_ONLY_OBSERVED = "ABSENCE_ONLY_OBSERVED"

EVIDENCE_STATUSES = (
    EVIDENCE_SHARED_OBSERVED,
    EVIDENCE_POSITIVE_ALTERNATIVE_OBSERVED,
    EVIDENCE_ABSENCE_ONLY_OBSERVED,
)

PREDICATE_FUNCTIONALITY_NOTE = (
    "POSITIVE_ALTERNATIVE_OBSERVED records that the candidate has a different "
    "observed counterpart for the same predicate and direction in the pinned KG "
    "snapshot. Prompt 8E applies no functional-predicate filter, so for a "
    "multi-valued predicate the candidate may hold the Answer's counterpart too "
    "without this snapshot recording it. The status is operational evidence for "
    "candidate selection under the Open World Assumption, never a refutation, and "
    "it requires human validation before use."
)

# NOTE ON THE PHRASE LIST BELOW
#   FORBIDDEN_NEGATIVE_CLAIM_PHRASES is a SUBSTRING check applied to whole
#   artefacts, so it cannot distinguish a claim from a disclaimer that quotes the
#   same words. That is deliberate — a checker that tried to parse intent would be
#   the thing most likely to be wrong — and it is why every note in this file is
#   worded to state the Open-World boundary without ever spelling out the claim it
#   rules out. If a future note needs rewording to pass, reword the note.

# ==========================================================================
# 3) THE TWO EVIDENCE POLICIES  (§6)
# ==========================================================================
# Never mixed silently: a policy name is a field on every record that a coverage
# decision produced, so "which policy said this" is answerable from the artefact.

POLICY_POSITIVE_OBSERVED = "positive-observed"
POLICY_SNAPSHOT_OBSERVED = "snapshot-observed"

EVIDENCE_POLICIES = (POLICY_POSITIVE_OBSERVED, POLICY_SNAPSHOT_OBSERVED)

#: Selection priority: positive-observed first, snapshot-observed only as an
#: explicitly labelled fallback. The order of this tuple IS the priority.
POLICY_PRIORITY = (POLICY_POSITIVE_OBSERVED, POLICY_SNAPSHOT_OBSERVED)

#: Which evidence statuses count as COVERAGE under each policy.
COVERING_STATUSES = {
    POLICY_POSITIVE_OBSERVED: frozenset({EVIDENCE_POSITIVE_ALTERNATIVE_OBSERVED}),
    POLICY_SNAPSHOT_OBSERVED: frozenset({EVIDENCE_POSITIVE_ALTERNATIVE_OBSERVED,
                                         EVIDENCE_ABSENCE_ONLY_OBSERVED}),
}

POLICY_NOTE = {
    POLICY_POSITIVE_OBSERVED: (
        "An Answer fact covers a candidate only when the candidate has a "
        "DIFFERENT observed counterpart for the same predicate and direction in "
        "the pinned KG snapshot."),
    POLICY_SNAPSHOT_OBSERVED: (
        "An Answer fact covers a candidate when the candidate has a different "
        "observed counterpart OR no observed counterpart at all for that key in "
        "the pinned KG snapshot. This is NOT an Open-World-safe proof: absence in "
        "one snapshot is not negation, so a snapshot-observed result is a "
        "human-validation fallback and must not be reported as OWA-safe."),
}

# ==========================================================================
# 4) COVERAGE AND SELECTION STATUSES  (§8, §9)
# ==========================================================================

COVERAGE_FULL = "FULL_COVERAGE"
COVERAGE_PARTIAL_2_OF_3 = "PARTIAL_2_OF_3"
COVERAGE_PARTIAL_1_OF_3 = "PARTIAL_1_OF_3"
COVERAGE_ZERO = "ZERO_COVERAGE"

SELECTION_POSITIVE_OBSERVED = "ALGORITHM_SELECTED_POSITIVE_OBSERVED"
SELECTION_SNAPSHOT_OBSERVED = (
    "ALGORITHM_SELECTED_SNAPSHOT_OBSERVED_REQUIRES_HUMAN_VALIDATION")
SELECTION_NO_FULL_COVERAGE = "NO_FULL_COVERAGE_IN_SELECTED_CLASS"
SELECTION_PRIMARY_NOT_READY = "PRIMARY_NOT_READY"

SELECTION_STATUSES = (
    SELECTION_POSITIVE_OBSERVED,
    SELECTION_SNAPSHOT_OBSERVED,
    SELECTION_NO_FULL_COVERAGE,
    SELECTION_PRIMARY_NOT_READY,
)

SELECTION_STATUS_FOR_POLICY = {
    POLICY_POSITIVE_OBSERVED: SELECTION_POSITIVE_OBSERVED,
    POLICY_SNAPSHOT_OBSERVED: SELECTION_SNAPSHOT_OBSERVED,
}

#: Emitted when no three-candidate combination reaches full coverage inside the
#: Prompt-8C selected class. Prompt 8E must NOT run class selection, mapping,
#: graph construction or LRoleSim for a fallback class: Prompt 8D holds rankings
#: for the selected class only, so a fallback class has no ranking to search.
REQUIRES_FALLBACK_CLASS = "REQUIRES_FALLBACK_CLASS_GRAPH_LROLESIM_RUN"

# ==========================================================================
# 5) HUMAN-VALIDATION FIELDS  (§5, §8)
# ==========================================================================

HUMAN_VALIDATION_NOT_CHECKED = "NOT_CHECKED"

#: Attached to every algorithm-selected MCQ, under BOTH policies. Even
#: ALGORITHM_SELECTED_POSITIVE_OBSERVED still requires human validation.
HUMAN_VALIDATION_FIELDS = {
    "requires_human_validation": True,
    "human_validation_status": HUMAN_VALIDATION_NOT_CHECKED,
    "publishable_final": False,
}

#: The provenance stamp on every rationale fact. A rationale fact is always an
#: observation read from the pinned local KG through the frozen Prompt-8D
#: serialization; nothing here derives, infers or invents one.
FACT_SOURCE_PINNED_LOCAL_KG = "pinned_local_kg_observed_fact"

# ==========================================================================
# 6) SET-COVER PARAMETERS  (§7)
# ==========================================================================

#: The MCQ setting: three distractors, presentation budget three facts.
DEFAULT_K = 3
DEFAULT_RHO = 3

#: The implementation is generic over 1 <= k <= 5. The bound is what keeps exact
#: minimum-cardinality set cover cheap: general set cover is NP-hard, but for
#: k <= 5 the exact solution is O(m * 2^k) (audit §3.3). Prompt 8E claims no new
#: algorithm — set cover and bitmask DP are textbook (CLAUDE.md item 10).
MIN_K = 1
MAX_K = 5

#: The rho values the ablation sweeps (§10). rho never changes the primary
#: selection, which is fixed at DEFAULT_RHO under positive-observed first.
RHO_ABLATION_VALUES = (1, 2, 3)

SET_COVER_COMPLEXITY = "O(m * 2^k)"

SET_COVER_ALGORITHM = "exact_minimum_cardinality_bitmask_dp"

#: AUDIT items EX-3 and §3.2: the legacy select_distractor_set()/build_choices()
#: accepted only |R| = 1 — ONE Answer fact distinguishing all three distractors.
#: Valid two-fact and three-fact rationales were discarded, depressing yield for a
#: reason that was a property of the code and not of DBpedia. This layer solves
#: the general minimum-cardinality problem and must never reintroduce that case.
LEGACY_ONE_FACT_SPECIAL_CASE_NOTE = (
    "The legacy |R| = 1 feasibility condition (AUDIT item EX-3) is not applied. "
    "Feasibility is established by the exact minimum-cardinality set-cover result "
    "and by nothing else.")

# ==========================================================================
# 7) LANGUAGE THAT MAY NEVER BE EMITTED
# ==========================================================================
# Checked by tests against every produced artefact. These are the spellings that
# would turn an observation about one snapshot into a claim about the world.

FORBIDDEN_NEGATIVE_CLAIM_PHRASES = (
    "does not have",
    "doesn't have",
    "is false",
    "are false",
    "negative fact",
    "verified false",
    "proven false",
    "proved false",
    "logically excluded",
    "known to be false",
    "false fact",
    "definitely not",
)


class RationaleContractError(Exception):
    """A rationale record or parameter violates the contract in this module."""


def assert_no_negative_claim(text: str, where: str = "") -> None:
    """Refuse any spelling that reads absence, or contrast, as falsity."""
    lowered = text.lower()
    for phrase in FORBIDDEN_NEGATIVE_CLAIM_PHRASES:
        if phrase in lowered:
            raise RationaleContractError(
                f"{where or 'text'} contains the forbidden negative claim "
                f"{phrase!r}. Prompt 8E reports observed contrast in the pinned KG "
                f"snapshot and never asserts that a triple is false.")


def validate_k(k: int) -> int:
    if isinstance(k, bool) or not isinstance(k, int):
        raise RationaleContractError(f"k must be an int, got {k!r}")
    if not (MIN_K <= k <= MAX_K):
        raise RationaleContractError(
            f"k must satisfy {MIN_K} <= k <= {MAX_K}, got {k}")
    return k


def validate_rho(rho: int) -> int:
    """rho is a PRESENTATION budget, not a correctness parameter.

    Audit §3.5 is explicit: by the feasibility lemma |R*| <= k, so setting
    rho = k makes the constraint vacuous — every full-coverage combination
    satisfies it. rho is therefore never compared against k here. It is swept
    (1, 2, 3) in the ablation precisely because it trades yield against how long a
    rationale a learner has to read.
    """
    if isinstance(rho, bool) or not isinstance(rho, int):
        raise RationaleContractError(f"rho must be an int, got {rho!r}")
    if rho < 1:
        raise RationaleContractError(f"rho must be at least 1, got {rho}")
    return rho


def validate_policy(policy: str) -> str:
    if policy not in EVIDENCE_POLICIES:
        raise RationaleContractError(
            f"unknown evidence policy {policy!r}; expected one of "
            f"{EVIDENCE_POLICIES}")
    return policy


# ==========================================================================
# 8) THE FACT VALUE TYPES
# ==========================================================================

@dataclass(frozen=True)
class FactKey:
    """κ = (predicate_uri, direction).

    Direction is part of the key, not a decoration on it. Merging an IN fact with
    an OUT fact on the same predicate would compare a node's subjects against its
    objects and call the result a contrast.
    """

    predicate_uri: str
    direction: str

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise RationaleContractError(
                f"direction must be one of {DIRECTIONS}, got {self.direction!r}")
        if not isinstance(self.predicate_uri, str) or not self.predicate_uri:
            raise RationaleContractError(
                f"predicate_uri must be a non-empty string, got "
                f"{self.predicate_uri!r}")
        if self.predicate_uri.startswith("<") or self.predicate_uri.endswith(">"):
            raise RationaleContractError(
                f"predicate_uri must be unbracketed, got {self.predicate_uri!r}")

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.predicate_uri, self.direction)

    def as_record(self) -> dict:
        return {"predicate_uri": self.predicate_uri, "direction": self.direction}


@dataclass(frozen=True)
class AnswerFact:
    """One observed Answer fact f = (κ, o_A), as read from the Prompt-8D handoff.

    This is a VIEW over a frozen observation. Nothing in this package creates an
    AnswerFact that was not serialized by Prompt 8D from the pinned local KG, and
    `source` says so on every emitted record.
    """

    predicate_uri: str
    direction: str
    counterpart_uri: str
    graph_fingerprint: str
    owner_uri: str = ""

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise RationaleContractError(
                f"direction must be one of {DIRECTIONS}, got {self.direction!r}")
        for name in ("predicate_uri", "counterpart_uri"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise RationaleContractError(
                    f"{name} must be a non-empty string, got {value!r}")
            if value.startswith("<") or value.endswith(">"):
                raise RationaleContractError(
                    f"{name} must be unbracketed, got {value!r}")

    @property
    def key(self) -> FactKey:
        return FactKey(self.predicate_uri, self.direction)

    @property
    def canonical_key(self) -> tuple[str, str, str]:
        """The §7 tie-break order: (predicate_uri, direction, counterpart_uri).

        Total within one Answer, because Prompt 8D deduplicates observed facts on
        exactly (owner, direction, predicate, counterpart).
        """
        return (self.predicate_uri, self.direction, self.counterpart_uri)

    def as_record(self) -> dict:
        return {
            "predicate_uri": self.predicate_uri,
            "direction": self.direction,
            "counterpart_uri": self.counterpart_uri,
            "graph_fingerprint": self.graph_fingerprint,
            "source": FACT_SOURCE_PINNED_LOCAL_KG,
        }


def sort_answer_facts(facts: Iterable[AnswerFact]) -> tuple[AnswerFact, ...]:
    """Canonical ascending order on (predicate_uri, direction, counterpart_uri).

    Every downstream tie-break assumes this order, so it is applied once, here,
    rather than re-derived at each call site.
    """
    return tuple(sorted(facts, key=lambda f: f.canonical_key))


def coverage_status_for_count(covered_count: int, k: int) -> str:
    """FULL / PARTIAL_n_OF_k / ZERO, from the number of covered distractors."""
    if covered_count == k:
        return COVERAGE_FULL
    if covered_count == 0:
        return COVERAGE_ZERO
    if k == DEFAULT_K and covered_count == 2:
        return COVERAGE_PARTIAL_2_OF_3
    if k == DEFAULT_K and covered_count == 1:
        return COVERAGE_PARTIAL_1_OF_3
    return f"PARTIAL_{covered_count}_OF_{k}"
