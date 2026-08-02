############################################################################
# src/rationale_v3/contracts.py
#
# The frozen vocabulary of the Journal-2 rationale V3 layer.
#
# WHAT V3 CHANGES, AND WHY THE VOCABULARY HAD TO CHANGE WITH IT
#   Prompt 8E classified an Answer fact against a candidate into three statuses
#   (SHARED_OBSERVED / POSITIVE_ALTERNATIVE_OBSERVED / ABSENCE_ONLY_OBSERVED) and
#   ran two policies over them. Those three statuses conflate distinctions that
#   decide whether a rationale is scientifically usable:
#
#     * "the candidate has a DIFFERENT object" is decisive when the predicate is
#       known to admit one object in the scope, and is nearly worthless when the
#       predicate is multi-valued — 8E gave both the same name;
#     * "different object" is not even a contrast when the two objects are the
#       same thing under a redirect, or when the candidate's object sits UNDER the
#       Answer's object in a containment hierarchy;
#     * a machine-checkable exclusion proof and an unexplained absence were both
#       reachable through the same policy switch.
#
#   V3 therefore reports an EVIDENCE LEVEL per (Answer fact, candidate):
#
#       NOT_COVERED < L0 < L1 < L2
#
#   with a REASON CODE naming which rule produced it, and — for L2 only — an
#   EvidenceProof carrying premises and an ontology source. Nothing may reach L1
#   without an active, scoped, versioned rule; nothing may reach L2 without a
#   proof object. That is the whole point of the file.
#
# WHAT DID NOT CHANGE
#   The Open-World boundary. L0 is an OBSERVATION about one snapshot and is never
#   a negative fact (CLAUDE.md item 7). L1 is an OPERATIONAL contrast valid inside
#   a declared scope, not a universal law. Only L2 claims exclusion, and only with
#   a proof. No status name in this file contains the word "false".
#
# DIRECTION IS PART OF THE KEY
#   κ = (predicate_uri, direction). An IN fact and an OUT fact on the same
#   predicate are never compared: `counterpart_uri` is the OBJECT of an OUT fact
#   and the SUBJECT of an IN fact (AUDIT item EX-12), so merging them would
#   compare a node's subjects against its objects and call the difference
#   evidence.
#
# INDEPENDENCE
#   This package imports nothing from `rationale` (Prompt 8E), `selection`, `kg`
#   or `lrolesim`. Prompt 8E stays an executable frozen baseline, and a change
#   here cannot reach it.
#
# OFFLINE AND PURE: constants, dataclasses and validation only.
############################################################################

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

VERSION = "rationale_v3.contracts/1.0.0"

# ==========================================================================
# 0) DIRECTION
# ==========================================================================

DIRECTION_OUT = "OUT"
DIRECTION_IN = "IN"
DIRECTIONS = (DIRECTION_OUT, DIRECTION_IN)

# ==========================================================================
# 1) EVIDENCE LEVELS  (Prompt 8F §6)
# ==========================================================================

LEVEL_NOT_COVERED = "NOT_COVERED"
LEVEL_L0 = "L0"
LEVEL_L1 = "L1"
LEVEL_L2 = "L2"

EVIDENCE_LEVELS = (LEVEL_NOT_COVERED, LEVEL_L0, LEVEL_L1, LEVEL_L2)

#: The total order. Used everywhere a level is compared, so "stronger than" has
#: exactly one meaning in the code base.
LEVEL_ORDER = {
    LEVEL_NOT_COVERED: 0,
    LEVEL_L0: 1,
    LEVEL_L1: 2,
    LEVEL_L2: 3,
}

LEVEL_DEFINITION = {
    LEVEL_NOT_COVERED: (
        "The candidate SUPPORTS the Answer's proposition in the pinned snapshot, "
        "through exact object equality, canonical equivalence, a safe semantic "
        "entailment (the candidate's object lies under the claim object), or a "
        "compatible qualified statement. The fact discriminates nothing here."),
    LEVEL_L0: (
        "OBSERVED NON-SUPPORT ONLY. The Answer supports the proposition; the "
        "pinned snapshot records no equivalent support for the candidate; no "
        "active scoped exclusivity rule applies; and no formal exclusion proof "
        "exists. L0 is a statement about one snapshot under the Open World "
        "Assumption: it records what that snapshot shows and what it leaves "
        "unrecorded, and it carries no claim about the world beyond it."),
    LEVEL_L1: (
        "SCOPED VALIDATED CONTRAST. An active, versioned rule in "
        "evidence_rules.json establishes an operationally valid contrast inside "
        "an explicitly declared scope — for example a predicate observed to be "
        "single-valued across the selected local class, with adequate support and "
        "zero observed violations. Empirical and scoped, never universal."),
    LEVEL_L2: (
        "FORMALLY ENTAILED EXCLUSION. A machine-checkable proof exists, carried "
        "as an EvidenceProof with premises, conclusion and an ontology or schema "
        "source. Reachable only through a trusted declaration; never inferred "
        "from the fact that a single value happens to be observed."),
}

# ==========================================================================
# 2) REASON CODES
# ==========================================================================
# Every level assignment names the rule that produced it. A reason code is the
# smallest reportable unit of "why", and the V3-to-8E comparison is built on it.

# --- NOT_COVERED ------------------------------------------------------------
NOT_COVERED_EXACT_EQUAL = "NOT_COVERED_EXACT_EQUAL"
NOT_COVERED_CANONICALLY_EQUIVALENT = "NOT_COVERED_CANONICALLY_EQUIVALENT"
NOT_COVERED_SEMANTIC_ENTAILMENT = "NOT_COVERED_CANDIDATE_OBJECT_UNDER_CLAIM_OBJECT"
NOT_COVERED_COMPATIBLE_QUALIFIED = "NOT_COVERED_COMPATIBLE_QUALIFIED_STATEMENT"

NOT_COVERED_REASON_CODES = (
    NOT_COVERED_EXACT_EQUAL,
    NOT_COVERED_CANONICALLY_EQUIVALENT,
    NOT_COVERED_SEMANTIC_ENTAILMENT,
    NOT_COVERED_COMPATIBLE_QUALIFIED,
)

# --- L0 ---------------------------------------------------------------------
#: The pinned snapshot records no fact at all for this key on this candidate.
L0_KEY_ABSENT = "L0_KEY_ABSENT"
#: The candidate has other observed objects for the key, and no active rule
#: makes the key exclusive in this scope. The 8E POSITIVE_ALTERNATIVE_OBSERVED
#: case, renamed to stop it reading as an exclusion.
L0_DIFFERENT_OBJECTS_NONEXCLUSIVE = "L0_DIFFERENT_OBJECTS_NONEXCLUSIVE"
#: Different objects, and the semantic layer could not decide how they relate,
#: so "different" may still turn out to be "the same thing" or "a special case".
L0_SEMANTIC_RELATION_UNKNOWN = "L0_SEMANTIC_RELATION_UNKNOWN"
#: The CLAIM object lies UNDER a candidate object: the candidate holds the more
#: general statement. Apparent contrast, downgraded rather than trusted (§5).
L0_GRANULARITY_RISK = "L0_GRANULARITY_RISK"

L0_REASON_CODES = (
    L0_KEY_ABSENT,
    L0_DIFFERENT_OBJECTS_NONEXCLUSIVE,
    L0_SEMANTIC_RELATION_UNKNOWN,
    L0_GRANULARITY_RISK,
)

# --- L1 ---------------------------------------------------------------------
L1_SCOPED_SINGLE_VALUED = "L1_EMPIRICALLY_SINGLE_VALUED_IN_SCOPE"
L1_CURATED_MUTUALLY_EXCLUSIVE = "L1_CURATED_MUTUALLY_EXCLUSIVE_VALUES"
L1_SCOPED_CLOSED_WORLD_SLOT = "L1_SCOPED_CLOSED_WORLD_SLOT"
L1_SOURCE_VALIDATED_POSITIVE_CONTRAST = "L1_SOURCE_VALIDATED_POSITIVE_CONTRAST"

L1_REASON_CODES = (
    L1_SCOPED_SINGLE_VALUED,
    L1_CURATED_MUTUALLY_EXCLUSIVE,
    L1_SCOPED_CLOSED_WORLD_SLOT,
    L1_SOURCE_VALIDATED_POSITIVE_CONTRAST,
)

# --- L2 ---------------------------------------------------------------------
L2_FUNCTIONAL_PROPERTY_CONFLICT = "L2_FORMAL_FUNCTIONAL_PROPERTY_CONFLICT"
L2_MAX_CARDINALITY_CONFLICT = "L2_FORMAL_MAX_CARDINALITY_CONFLICT"
L2_EXPLICIT_NEGATIVE_ASSERTION = "L2_EXPLICIT_NEGATIVE_PROPERTY_ASSERTION"
L2_DISJOINT_VALUE_CONFLICT = "L2_FORMAL_DISJOINT_VALUE_CONFLICT"
L2_TEMPORAL_EXCLUSIVE_CONFLICT = "L2_TEMPORALLY_SCOPED_EXCLUSIVE_CONFLICT"

L2_REASON_CODES = (
    L2_FUNCTIONAL_PROPERTY_CONFLICT,
    L2_MAX_CARDINALITY_CONFLICT,
    L2_EXPLICIT_NEGATIVE_ASSERTION,
    L2_DISJOINT_VALUE_CONFLICT,
    L2_TEMPORAL_EXCLUSIVE_CONFLICT,
)

REASON_CODE_LEVEL = {
    **{code: LEVEL_NOT_COVERED for code in NOT_COVERED_REASON_CODES},
    **{code: LEVEL_L0 for code in L0_REASON_CODES},
    **{code: LEVEL_L1 for code in L1_REASON_CODES},
    **{code: LEVEL_L2 for code in L2_REASON_CODES},
}

#: Which Prompt-8E status each V3 reason code corresponds to. Kept so the two
#: runs can be compared row by row (Prompt 8F §6.2) without re-deriving 8E.
PROMPT8E_STATUS_FOR_REASON_CODE = {
    NOT_COVERED_EXACT_EQUAL: "SHARED_OBSERVED",
    # 8E had no notion of a redirect or of containment, so both of these were
    # POSITIVE_ALTERNATIVE_OBSERVED there and are corrections here.
    NOT_COVERED_CANONICALLY_EQUIVALENT: "POSITIVE_ALTERNATIVE_OBSERVED",
    NOT_COVERED_SEMANTIC_ENTAILMENT: "POSITIVE_ALTERNATIVE_OBSERVED",
    NOT_COVERED_COMPATIBLE_QUALIFIED: "POSITIVE_ALTERNATIVE_OBSERVED",
    L0_KEY_ABSENT: "ABSENCE_ONLY_OBSERVED",
    L0_DIFFERENT_OBJECTS_NONEXCLUSIVE: "POSITIVE_ALTERNATIVE_OBSERVED",
    L0_SEMANTIC_RELATION_UNKNOWN: "POSITIVE_ALTERNATIVE_OBSERVED",
    L0_GRANULARITY_RISK: "POSITIVE_ALTERNATIVE_OBSERVED",
    L1_SCOPED_SINGLE_VALUED: "POSITIVE_ALTERNATIVE_OBSERVED",
    L1_CURATED_MUTUALLY_EXCLUSIVE: "POSITIVE_ALTERNATIVE_OBSERVED",
    L1_SCOPED_CLOSED_WORLD_SLOT: "ABSENCE_ONLY_OBSERVED",
    L1_SOURCE_VALIDATED_POSITIVE_CONTRAST: "POSITIVE_ALTERNATIVE_OBSERVED",
    L2_FUNCTIONAL_PROPERTY_CONFLICT: "POSITIVE_ALTERNATIVE_OBSERVED",
    L2_MAX_CARDINALITY_CONFLICT: "POSITIVE_ALTERNATIVE_OBSERVED",
    L2_EXPLICIT_NEGATIVE_ASSERTION: "POSITIVE_ALTERNATIVE_OBSERVED",
    L2_DISJOINT_VALUE_CONFLICT: "POSITIVE_ALTERNATIVE_OBSERVED",
    L2_TEMPORAL_EXCLUSIVE_CONFLICT: "POSITIVE_ALTERNATIVE_OBSERVED",
}

MULTI_VALUED_PREDICATE_NOTE = (
    "L0_DIFFERENT_OBJECTS_NONEXCLUSIVE records that the candidate has a different "
    "observed counterpart for the same predicate and direction in the pinned KG "
    "snapshot, and that no active rule makes that key exclusive in this scope. "
    "For a multi-valued predicate the candidate may hold the Answer's counterpart "
    "too without this snapshot recording it, so the observation is operational "
    "evidence for candidate selection under the Open World Assumption and nothing "
    "stronger. Only an active scoped rule raises it to L1, and only a proof "
    "raises it to L2.")

# ==========================================================================
# 3) SEMANTIC RELATIONS  (§5)
# ==========================================================================

RELATION_EXACT_EQUAL = "EXACT_EQUAL"
RELATION_CANONICALLY_EQUIVALENT = "CANONICALLY_EQUIVALENT"
RELATION_CANDIDATE_UNDER_CLAIM = "CANDIDATE_OBJECT_DESCENDANT_OF_CLAIM_OBJECT"
RELATION_CLAIM_UNDER_CANDIDATE = "CLAIM_OBJECT_DESCENDANT_OF_CANDIDATE_OBJECT"
RELATION_PROVEN_DISJOINT = "PROVEN_DISJOINT"
RELATION_UNRELATED_OR_UNKNOWN = "UNRELATED_OR_UNKNOWN"
RELATION_UNAVAILABLE = "SEMANTIC_RELATION_UNAVAILABLE"

SEMANTIC_RELATIONS = (
    RELATION_EXACT_EQUAL,
    RELATION_CANONICALLY_EQUIVALENT,
    RELATION_CANDIDATE_UNDER_CLAIM,
    RELATION_CLAIM_UNDER_CANDIDATE,
    RELATION_PROVEN_DISJOINT,
    RELATION_UNRELATED_OR_UNKNOWN,
    RELATION_UNAVAILABLE,
)

#: Relations under which the candidate SUPPORTS the Answer's proposition, so the
#: fact cannot cover it under any policy (§5 "safety semantics").
SUPPORTING_RELATIONS = frozenset({
    RELATION_EXACT_EQUAL,
    RELATION_CANONICALLY_EQUIVALENT,
    RELATION_CANDIDATE_UNDER_CLAIM,
})

SEMANTIC_GRANULARITY_RISK = "SEMANTIC_GRANULARITY_RISK"

PARENT_CHILD_NOTE = (
    "Parent-child relatedness REMOVES or DOWNGRADES apparent contrast. It never "
    "creates exclusion evidence: that a candidate's object is unrelated to the "
    "claim object in the traversed hierarchy is a statement about the traversed "
    "edges, not about the world.")

# ==========================================================================
# 4) EVIDENCE POLICIES  (§7)
# ==========================================================================

POLICY_STRICT_L2 = "strict-l2"
POLICY_MAIN_L1PLUS = "main-l1plus"
POLICY_DIAGNOSTIC_L0 = "diagnostic-l0"

EVIDENCE_POLICIES = (POLICY_STRICT_L2, POLICY_MAIN_L1PLUS, POLICY_DIAGNOSTIC_L0)

#: The tier order of §7 and §11. The order of this tuple IS the priority.
POLICY_PRIORITY = (POLICY_STRICT_L2, POLICY_MAIN_L1PLUS, POLICY_DIAGNOSTIC_L0)

#: The weakest level that counts as coverage under each policy.
POLICY_MINIMUM_LEVEL = {
    POLICY_STRICT_L2: LEVEL_L2,
    POLICY_MAIN_L1PLUS: LEVEL_L1,
    POLICY_DIAGNOSTIC_L0: LEVEL_L0,
}

COVERING_LEVELS = {
    POLICY_STRICT_L2: frozenset({LEVEL_L2}),
    POLICY_MAIN_L1PLUS: frozenset({LEVEL_L1, LEVEL_L2}),
    POLICY_DIAGNOSTIC_L0: frozenset({LEVEL_L0, LEVEL_L1, LEVEL_L2}),
}

#: Which policies may produce a MAIN-corpus item. diagnostic-l0 may not (§7).
MAIN_CORPUS_POLICIES = frozenset({POLICY_STRICT_L2, POLICY_MAIN_L1PLUS})

POLICY_NOTE = {
    POLICY_STRICT_L2: (
        "Only a formally entailed exclusion, carried by an EvidenceProof, covers "
        "a candidate."),
    POLICY_MAIN_L1PLUS: (
        "A scoped validated contrast (L1) or a formally entailed exclusion (L2) "
        "covers a candidate. The main-corpus policy."),
    POLICY_DIAGNOSTIC_L0: (
        "Observed non-support (L0) also covers a candidate. DIAGNOSTIC ONLY: an "
        "L0-only result is an observation about one snapshot and is not eligible "
        "for the main corpus."),
}

# ==========================================================================
# 5) RULE TYPES, SCOPES AND ACTIVATION  (§6.3, §6.4)
# ==========================================================================

RULE_TYPE_EMPIRICAL_SINGLE_VALUED = "EMPIRICALLY_SINGLE_VALUED_IN_SCOPE"
RULE_TYPE_CURATED_MUTUALLY_EXCLUSIVE = "CURATED_MUTUALLY_EXCLUSIVE_VALUES"
RULE_TYPE_SCOPED_CLOSED_WORLD_SLOT = "SCOPED_CLOSED_WORLD_SLOT"
RULE_TYPE_SOURCE_VALIDATED_CONTRAST = "SOURCE_VALIDATED_POSITIVE_CONTRAST"

L1_RULE_TYPES = (
    RULE_TYPE_EMPIRICAL_SINGLE_VALUED,
    RULE_TYPE_CURATED_MUTUALLY_EXCLUSIVE,
    RULE_TYPE_SCOPED_CLOSED_WORLD_SLOT,
    RULE_TYPE_SOURCE_VALIDATED_CONTRAST,
)

RULE_TYPE_FUNCTIONAL_PROPERTY = "FORMAL_FUNCTIONAL_PROPERTY_CONFLICT"
RULE_TYPE_MAX_CARDINALITY = "FORMAL_MAX_CARDINALITY_CONFLICT"
RULE_TYPE_EXPLICIT_NEGATIVE = "EXPLICIT_NEGATIVE_PROPERTY_ASSERTION"
RULE_TYPE_DISJOINT_VALUE = "FORMAL_DISJOINT_VALUE_CONFLICT"
RULE_TYPE_TEMPORAL_EXCLUSIVE = "TEMPORALLY_SCOPED_EXCLUSIVE_CONFLICT"

L2_RULE_TYPES = (
    RULE_TYPE_FUNCTIONAL_PROPERTY,
    RULE_TYPE_MAX_CARDINALITY,
    RULE_TYPE_EXPLICIT_NEGATIVE,
    RULE_TYPE_DISJOINT_VALUE,
    RULE_TYPE_TEMPORAL_EXCLUSIVE,
)

L1_REASON_FOR_RULE_TYPE = {
    RULE_TYPE_EMPIRICAL_SINGLE_VALUED: L1_SCOPED_SINGLE_VALUED,
    RULE_TYPE_CURATED_MUTUALLY_EXCLUSIVE: L1_CURATED_MUTUALLY_EXCLUSIVE,
    RULE_TYPE_SCOPED_CLOSED_WORLD_SLOT: L1_SCOPED_CLOSED_WORLD_SLOT,
    RULE_TYPE_SOURCE_VALIDATED_CONTRAST: L1_SOURCE_VALIDATED_POSITIVE_CONTRAST,
}

L2_REASON_FOR_RULE_TYPE = {
    RULE_TYPE_FUNCTIONAL_PROPERTY: L2_FUNCTIONAL_PROPERTY_CONFLICT,
    RULE_TYPE_MAX_CARDINALITY: L2_MAX_CARDINALITY_CONFLICT,
    RULE_TYPE_EXPLICIT_NEGATIVE: L2_EXPLICIT_NEGATIVE_ASSERTION,
    RULE_TYPE_DISJOINT_VALUE: L2_DISJOINT_VALUE_CONFLICT,
    RULE_TYPE_TEMPORAL_EXCLUSIVE: L2_TEMPORAL_EXCLUSIVE_CONFLICT,
}

RULE_ACTIVE = "ACTIVE"
RULE_PROPOSED_NOT_ACTIVE = "PROPOSED_NOT_ACTIVE"
RULE_INACTIVE = "INACTIVE"
RULE_ACTIVATION_STATUSES = (RULE_ACTIVE, RULE_PROPOSED_NOT_ACTIVE, RULE_INACTIVE)

#: Reasons a derived empirical rule is recorded but NOT activated. Each is a
#: scientific position, so each is named rather than left implicit.
NOT_ACTIVE_INSUFFICIENT_SUPPORT = "INSUFFICIENT_OBSERVED_SUPPORT_IN_SCOPE"
NOT_ACTIVE_CARDINALITY_VIOLATION = "OBSERVED_CARDINALITY_VIOLATION_IN_SCOPE"
NOT_ACTIVE_IN_DIRECTION = "IN_DIRECTION_EMPIRICAL_CARDINALITY_NOT_TRUSTED"
NOT_ACTIVE_PREDICATE_REJECTED = "PREDICATE_REJECTED_BY_PREDICATE_POLICY"

# ==========================================================================
# 6) QUALIFIERS  (§4)
# ==========================================================================

QUALIFIER_UNAVAILABLE = "UNAVAILABLE_IN_SOURCE"
QUALIFIER_PRESENT = "PRESENT"

QUALIFIER_NOTE = (
    "DBpedia infobox facts carry no statement-level qualifier structure, so the "
    "pilot records qualifier_status = UNAVAILABLE_IN_SOURCE and creates no "
    "temporal or location-qualified L2 evidence. The RationaleProposition type "
    "carries a qualifiers field so a future qualified source can be added without "
    "changing the object model; nothing fabricates one.")

# ==========================================================================
# 7) AUTOMATIC GENERATION VERSUS LATER HUMAN EVALUATION  (§13)
# ==========================================================================

HUMAN_EVALUATION_NOT_STARTED = "NOT_STARTED"

#: Attached to every generated record. `publishable_final = false` means the
#: 100-question corpus and its human evaluation have not been completed yet. It
#: does NOT mean a human selected, edited or approved this item: generation is
#: fully automatic and `manual_intervention_used` is false everywhere.
AUTOMATIC_GENERATION_FIELDS = {
    "generation_is_automatic": True,
    "manual_intervention_used": False,
    "post_generation_human_evaluation_status": HUMAN_EVALUATION_NOT_STARTED,
    "publishable_final": False,
}

PUBLISHABLE_FINAL_NOTE = (
    "publishable_final = false records only that the larger batch and its "
    "post-generation human evaluation have not been completed. Generation is "
    "fully automatic: no human judgement entered the algorithmic selection loop.")

# ==========================================================================
# 8) SELECTION AND FALLBACK STATUSES  (§7, §14)
# ==========================================================================

SELECTION_STRICT_L2 = "ALGORITHM_SELECTED_STRICT_L2"
SELECTION_MAIN_L1PLUS = "ALGORITHM_SELECTED_MAIN_L1PLUS"
SELECTION_DIAGNOSTIC_L0 = "ALGORITHM_SELECTED_DIAGNOSTIC_L0_ONLY"
SELECTION_NO_FULL_COVERAGE = "NO_FULL_COVERAGE_IN_SELECTED_CLASS"
SELECTION_NO_QUALITY_ELIGIBLE = "NO_QUALITY_ELIGIBLE_RATIONALE_IN_SELECTED_CLASS"
SELECTION_PRIMARY_NOT_READY = "PRIMARY_NOT_READY"

SELECTION_STATUSES = (
    SELECTION_STRICT_L2,
    SELECTION_MAIN_L1PLUS,
    SELECTION_DIAGNOSTIC_L0,
    SELECTION_NO_FULL_COVERAGE,
    SELECTION_NO_QUALITY_ELIGIBLE,
    SELECTION_PRIMARY_NOT_READY,
)

SELECTION_STATUS_FOR_POLICY = {
    POLICY_STRICT_L2: SELECTION_STRICT_L2,
    POLICY_MAIN_L1PLUS: SELECTION_MAIN_L1PLUS,
    POLICY_DIAGNOSTIC_L0: SELECTION_DIAGNOSTIC_L0,
}

FALLBACK_L0_ONLY = "FALLBACK_CLASS_REQUIRED_L0_ONLY"
FALLBACK_NO_FULL_COVERAGE = "FALLBACK_CLASS_REQUIRED_NO_FULL_COVERAGE"
FALLBACK_NO_QUALITY_ELIGIBLE = (
    "FALLBACK_CLASS_REQUIRED_NO_QUALITY_ELIGIBLE_RATIONALE")

FALLBACK_STATUSES = (FALLBACK_L0_ONLY, FALLBACK_NO_FULL_COVERAGE,
                     FALLBACK_NO_QUALITY_ELIGIBLE)

#: Prompt 8F emits the request and stops. No class selection, no candidate
#: retrieval, no mapping, no graph construction and no LRoleSim run happens for a
#: fallback class in this task.
FALLBACK_NEXT_STAGE = "FALLBACK_CLASS_GRAPH_AND_LROLESIM_RUN_IN_A_LATER_TASK"

# ==========================================================================
# 9) COMBINATION SEARCH SCOPE  (§12)
# ==========================================================================

SEARCH_FULL_EXACT = "FULL_EXACT"
SEARCH_POOL_EXACT = "POOL_EXACT"
SEARCH_SCOPES = (SEARCH_FULL_EXACT, SEARCH_POOL_EXACT)

DEFAULT_MAX_EXACT_COMBINATIONS = 200_000
DEFAULT_POOL_TOP_BY_SCORE = 75
DEFAULT_POOL_EVIDENCE_RESCUE = 25
DEFAULT_MAX_POOL_SIZE = 100

POOL_POLICY_NAME = "top_lrolesim_plus_evidence_rescue_v1"

POOL_ABLATION_SIZES = (25, 50, 75, 100)

POOL_OPTIMALITY_NOTE = (
    "POOL_EXACT enumerates every k-candidate combination INSIDE a bounded pool. "
    "The result is exact for that pool only, and the run makes no optimality "
    "claim over the full ranking: read global_optimality_claim and "
    "pool_optimality_claim on the same record for the exact scope.")

# ==========================================================================
# 10) SET-COVER PARAMETERS  (§8)
# ==========================================================================

DEFAULT_K = 3
DEFAULT_RHO = 3
MIN_K = 1
MAX_K = 5

SET_COVER_ALGORITHM = "exact_minimum_cardinality_bitmask_dp"
SET_COVER_COMPLEXITY = "O(m * 2^k)"

LEGACY_ONE_FACT_SPECIAL_CASE_NOTE = (
    "The legacy |R| = 1 feasibility condition (AUDIT item EX-3) is not applied. "
    "Feasibility is established by the exact minimum-cardinality set-cover result "
    "and by nothing else.")

SET_COVER_PROVENANCE_NOTE = (
    "Set cover, bitmask dynamic programming and Hungarian matching are textbook. "
    "Nothing in this package is presented as a newly invented algorithm; the "
    "contribution is the formulation and the evidence model around it.")

#: How many equally-minimum-cardinality rationales the ranking may enumerate
#: before it reports itself bounded. The pilot is expected to stay COMPLETE.
DEFAULT_MAX_MINIMUM_RATIONALE_CANDIDATES = 200_000
ENUMERATION_COMPLETE = "COMPLETE"
ENUMERATION_BOUNDED = "BOUNDED"

# ==========================================================================
# 11) LANGUAGE THAT MAY NEVER BE EMITTED
# ==========================================================================
# Checked by tests against every produced artefact. A substring check applied to
# whole files, so it cannot tell a claim from a disclaimer quoting the same
# words — deliberately, since a checker that parsed intent would be the thing
# most likely to be wrong. Every note in this file is worded to state the
# Open-World boundary without spelling out the claim it rules out.

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
    "globally optimal",
    "human-approved",
    "human approved",
)


class RationaleV3ContractError(Exception):
    """A V3 record or parameter violates the contract in this module."""


def assert_no_negative_claim(text: str, where: str = "") -> None:
    """Refuse any spelling that reads absence, or contrast, as falsity."""
    lowered = text.lower()
    for phrase in FORBIDDEN_NEGATIVE_CLAIM_PHRASES:
        if phrase in lowered:
            raise RationaleV3ContractError(
                f"{where or 'text'} contains the forbidden phrase {phrase!r}. "
                f"Prompt 8F reports evidence levels over the pinned KG snapshot "
                f"and never asserts that a triple is refuted, that a pool result "
                f"is a global optimum, or that an item has been evaluated.")


def validate_k(k: int) -> int:
    if isinstance(k, bool) or not isinstance(k, int):
        raise RationaleV3ContractError(f"k must be an int, got {k!r}")
    if not (MIN_K <= k <= MAX_K):
        raise RationaleV3ContractError(
            f"k must satisfy {MIN_K} <= k <= {MAX_K}, got {k}")
    return k


def validate_rho(rho: int) -> int:
    """rho is a PRESENTATION budget, not a correctness parameter (audit §3.5)."""
    if isinstance(rho, bool) or not isinstance(rho, int):
        raise RationaleV3ContractError(f"rho must be an int, got {rho!r}")
    if rho < 1:
        raise RationaleV3ContractError(f"rho must be at least 1, got {rho}")
    return rho


def validate_policy(policy: str) -> str:
    if policy not in EVIDENCE_POLICIES:
        raise RationaleV3ContractError(
            f"unknown evidence policy {policy!r}; expected one of "
            f"{EVIDENCE_POLICIES}")
    return policy


def validate_level(level: str) -> str:
    if level not in LEVEL_ORDER:
        raise RationaleV3ContractError(
            f"unknown evidence level {level!r}; expected one of {EVIDENCE_LEVELS}")
    return level


def level_at_least(level: str, minimum: str) -> bool:
    """Whether `level` is at least as strong as `minimum` in the total order."""
    return LEVEL_ORDER[validate_level(level)] >= LEVEL_ORDER[validate_level(minimum)]


def covers_under_policy(level: str, policy: str) -> bool:
    """The ONE place a level is turned into a coverage decision."""
    return validate_level(level) in COVERING_LEVELS[validate_policy(policy)]


def weakest_level(levels: Iterable[str]) -> str:
    """min over the total order. Empty input is NOT_COVERED."""
    ordered = [validate_level(level) for level in levels]
    if not ordered:
        return LEVEL_NOT_COVERED
    return min(ordered, key=lambda level: LEVEL_ORDER[level])


def strongest_level(levels: Iterable[str]) -> str:
    """max over the total order. Empty input is NOT_COVERED."""
    ordered = [validate_level(level) for level in levels]
    if not ordered:
        return LEVEL_NOT_COVERED
    return max(ordered, key=lambda level: LEVEL_ORDER[level])


# ==========================================================================
# 12) THE VALUE TYPES
# ==========================================================================

def _require_plain_uri(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RationaleV3ContractError(
            f"{name} must be a non-empty string, got {value!r}")
    if value.startswith("<") or value.endswith(">"):
        raise RationaleV3ContractError(
            f"{name} must be unbracketed, got {value!r}")
    return value


@dataclass(frozen=True)
class FactKey:
    """κ = (predicate_uri, direction). Direction is part of the key, not a
    decoration on it."""

    predicate_uri: str
    direction: str

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise RationaleV3ContractError(
                f"direction must be one of {DIRECTIONS}, got {self.direction!r}")
        _require_plain_uri(self.predicate_uri, "predicate_uri")

    @property
    def as_tuple(self) -> tuple[str, str]:
        return (self.predicate_uri, self.direction)

    def as_record(self) -> dict:
        return {"predicate_uri": self.predicate_uri, "direction": self.direction}


@dataclass(frozen=True)
class AnswerFact:
    """One observed Answer fact f = (κ, o_A), read from the frozen Prompt-8D
    serialization of the pinned local KG. Nothing here invents one."""

    predicate_uri: str
    direction: str
    counterpart_uri: str
    graph_fingerprint: str
    owner_uri: str = ""

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise RationaleV3ContractError(
                f"direction must be one of {DIRECTIONS}, got {self.direction!r}")
        _require_plain_uri(self.predicate_uri, "predicate_uri")
        _require_plain_uri(self.counterpart_uri, "counterpart_uri")

    @property
    def key(self) -> FactKey:
        return FactKey(self.predicate_uri, self.direction)

    @property
    def key_tuple(self) -> tuple[str, str]:
        return (self.predicate_uri, self.direction)

    @property
    def canonical_key(self) -> tuple[str, str, str]:
        """The final unresolved tie-break order (§10 item 11)."""
        return (self.predicate_uri, self.direction, self.counterpart_uri)


@dataclass(frozen=True)
class RationaleProposition:
    """The §4 proposition object.

    `claim_object_uri` equals `source_object_uri` for Prompt 8F: no source object
    is generalised to an ancestor for verbalization in this task. The two fields
    are kept distinct so a later task can generalise without changing the schema.
    """

    predicate_uri: str
    direction: str
    source_object_uri: str
    claim_object_uri: str
    qualifiers: tuple[tuple[str, str], ...] = ()
    qualifier_status: str = QUALIFIER_UNAVAILABLE

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise RationaleV3ContractError(
                f"direction must be one of {DIRECTIONS}, got {self.direction!r}")
        _require_plain_uri(self.predicate_uri, "predicate_uri")
        _require_plain_uri(self.source_object_uri, "source_object_uri")
        _require_plain_uri(self.claim_object_uri, "claim_object_uri")
        if self.qualifiers and self.qualifier_status != QUALIFIER_PRESENT:
            raise RationaleV3ContractError(
                "qualifiers were supplied but qualifier_status is not PRESENT; "
                "a qualifier must never be recorded without saying so")
        if not self.qualifiers and self.qualifier_status == QUALIFIER_PRESENT:
            raise RationaleV3ContractError(
                "qualifier_status is PRESENT but no qualifier was supplied; "
                "nothing may fabricate a qualifier")

    @classmethod
    def from_answer_fact(cls, fact: AnswerFact) -> "RationaleProposition":
        return cls(
            predicate_uri=fact.predicate_uri,
            direction=fact.direction,
            source_object_uri=fact.counterpart_uri,
            claim_object_uri=fact.counterpart_uri,
        )

    def as_record(self) -> dict:
        return {
            "predicate_uri": self.predicate_uri,
            "direction": self.direction,
            "source_object_uri": self.source_object_uri,
            "claim_object_uri": self.claim_object_uri,
            "qualifiers": [list(pair) for pair in self.qualifiers],
            "qualifier_status": self.qualifier_status,
        }


@dataclass(frozen=True)
class EvidenceProof:
    """The §6.4 proof object. Required for EVERY L2 assignment.

    An L2 level with no proof is a contradiction in terms, so `evidence.py`
    refuses to build one and `validate_l2_assignment` below is the checkable
    statement of that rule.
    """

    rule_id: str
    rule_type: str
    premises: tuple[str, ...]
    conclusion: str
    predicate_uri: str
    direction: str
    answer_object_uri: str
    candidate_object_uris: tuple[str, ...]
    qualifier_context: str
    ontology_source: str
    provenance: str

    def __post_init__(self) -> None:
        if self.rule_type not in L2_RULE_TYPES:
            raise RationaleV3ContractError(
                f"rule_type must be one of {L2_RULE_TYPES}, got "
                f"{self.rule_type!r}")
        if not self.premises:
            raise RationaleV3ContractError(
                f"{self.rule_id}: an EvidenceProof must carry at least one "
                f"premise")
        for name in ("rule_id", "conclusion", "ontology_source", "provenance"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise RationaleV3ContractError(
                    f"{name} must be a non-empty string, got {value!r}")

    def as_record(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "premises": list(self.premises),
            "conclusion": self.conclusion,
            "predicate_uri": self.predicate_uri,
            "direction": self.direction,
            "answer_object_uri": self.answer_object_uri,
            "candidate_object_uris": list(self.candidate_object_uris),
            "qualifier_context": self.qualifier_context,
            "ontology_source": self.ontology_source,
            "provenance": self.provenance,
        }


def validate_l2_assignment(level: str, proof: Optional[EvidenceProof],
                           where: str = "") -> None:
    """L2 without a proof, or a proof without L2, is a contract violation."""
    if level == LEVEL_L2 and proof is None:
        raise RationaleV3ContractError(
            f"{where or 'assignment'}: level L2 requires an EvidenceProof")
    if level != LEVEL_L2 and proof is not None:
        raise RationaleV3ContractError(
            f"{where or 'assignment'}: an EvidenceProof was supplied for level "
            f"{level}, but only L2 may carry one")


def sort_answer_facts(facts: Iterable[AnswerFact]) -> tuple[AnswerFact, ...]:
    """Canonical ascending order on (predicate_uri, direction, counterpart_uri)."""
    return tuple(sorted(facts, key=lambda f: f.canonical_key))


def coverage_status_for_count(covered_count: int, k: int) -> str:
    """FULL / PARTIAL_n_OF_k / ZERO, from the number of covered distractors."""
    if covered_count == k:
        return "FULL_COVERAGE"
    if covered_count == 0:
        return "ZERO_COVERAGE"
    return f"PARTIAL_{covered_count}_OF_{k}"
