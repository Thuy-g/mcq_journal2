############################################################################
# src/rationale_v3/contracts.py
#
# The frozen vocabulary of the Journal-2 rationale V3 layer (revision R1).
#
# WHAT R1 CORRECTS
#   Prompt 8F made an observed positive alternative object L0 unless a scoped
#   empirical single-valued rule was active, which inverted the meaning of L1
#   and let an empirical annotation decide a level. R1 restores the taxonomy:
#
#     NOT_COVERED  the candidate SUPPORTS the Answer's proposition
#     L0           absence-only: the candidate has NO object for the key
#     L1           positive observed contrast: at least one alternative object
#     L2           verified exclusion, carried by an EvidenceProof
#
#   How strong the exclusion argument is now lives on a SEPARATE axis,
#   `exclusion_basis` in {NONE, SCOPED_EMPIRICAL, FORMAL_PROOF}, so a scoped
#   rule can annotate an L1 contrast without creating or destroying it.
#
# OPEN WORLD
#   L0 records what one snapshot leaves unrecorded and is never a negative fact
#   (CLAUDE.md item 7). L1 is an OBSERVED contrast, not a proof that the
#   candidate could not also hold the Answer's object. Only L2 asserts
#   exclusion, and only with a proof object.
#
# kappa = (predicate_uri, direction). `counterpart_uri` is the OBJECT of an OUT
# fact and the SUBJECT of an IN fact (AUDIT item EX-12), so IN and OUT are never
# compared. Imports nothing from `rationale` (8E), `selection`, `kg`, `lrolesim`.
############################################################################

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

VERSION = "rationale_v3.contracts/2.0.0-r1"

DIRECTION_OUT = "OUT"
DIRECTION_IN = "IN"
DIRECTIONS = (DIRECTION_OUT, DIRECTION_IN)

# --- 1) EVIDENCE LEVELS ------------------------------------------------------

LEVEL_NOT_COVERED = "NOT_COVERED"
LEVEL_L0 = "L0"
LEVEL_L1 = "L1"
LEVEL_L2 = "L2"

EVIDENCE_LEVELS = (LEVEL_NOT_COVERED, LEVEL_L0, LEVEL_L1, LEVEL_L2)

#: The total order. Used wherever a level is compared, so "stronger than" has
#: exactly one meaning in the code base.
LEVEL_ORDER = {LEVEL_NOT_COVERED: 0, LEVEL_L0: 1, LEVEL_L1: 2, LEVEL_L2: 3}

LEVEL_DEFINITION = {
    LEVEL_NOT_COVERED: (
        "The candidate SUPPORTS the Answer's proposition in the pinned "
        "snapshot, through exact object equality, verified canonical "
        "equivalence, or a safe semantic entailment in which the candidate's "
        "object lies under the claim object. The fact discriminates nothing "
        "here, and this test runs before L0, L1 and L2."),
    LEVEL_L0: (
        "ABSENCE-ONLY OBSERVED. The Answer supports the proposition and the "
        "pinned snapshot records no object at all for the same predicate and "
        "direction on the candidate. L0 is snapshot non-support under the Open "
        "World Assumption: it carries no claim about the world beyond the "
        "snapshot and is not real-world exclusion."),
    LEVEL_L1: (
        "POSITIVE VALUE CONTRAST. The candidate has at least one OBSERVED "
        "alternative object for the same predicate and direction and does not "
        "support the Answer's proposition. The predicate may be multi-valued: "
        "L1 reports an observed contrast and does not establish that the "
        "candidate could not also hold the Answer's object."),
    LEVEL_L2: (
        "VERIFIED EXCLUSION. A machine-checkable proof exists, carried as an "
        "EvidenceProof with premises, conclusion and an ontology or schema "
        "source. Reachable only through a trusted declaration."),
}

# --- 2) REASON CODES ---------------------------------------------------------
# Every level assignment names the rule that produced it; the R1-to-8F and
# R1-to-8E comparisons are built on these codes.

NOT_COVERED_EXACT_EQUAL = "NOT_COVERED_EXACT_EQUAL"
NOT_COVERED_CANONICALLY_EQUIVALENT = "NOT_COVERED_CANONICALLY_EQUIVALENT"
NOT_COVERED_SEMANTIC_ENTAILMENT = "NOT_COVERED_CANDIDATE_OBJECT_UNDER_CLAIM_OBJECT"
NOT_COVERED_COMPATIBLE_QUALIFIED = "NOT_COVERED_COMPATIBLE_QUALIFIED_STATEMENT"
#: Prompt 8H-B2-E: the candidate's object denotes the same value of THIS
#: predicate slot under a declared, predicate-scoped equivalence rule. Kept
#: apart from NOT_COVERED_CANONICALLY_EQUIVALENT, which is a claim about entity
#: identity and would be false for a country/demonym pair.
NOT_COVERED_SCOPED_VALUE_EQUIVALENT = "NOT_COVERED_PREDICATE_SCOPED_VALUE_EQUIVALENT"

NOT_COVERED_REASON_CODES = (
    NOT_COVERED_EXACT_EQUAL,
    NOT_COVERED_CANONICALLY_EQUIVALENT,
    NOT_COVERED_SEMANTIC_ENTAILMENT,
    NOT_COVERED_COMPATIBLE_QUALIFIED,
    NOT_COVERED_SCOPED_VALUE_EQUIVALENT,
)

#: The ONE L0 code in R1. Prompt 8F's L0_DIFFERENT_OBJECTS_NONEXCLUSIVE,
#: L0_SEMANTIC_RELATION_UNKNOWN and L0_GRANULARITY_RISK are gone: all three
#: described a candidate with an observed positive alternative, which is L1.
L0_ABSENCE_ONLY_OBSERVED = "L0_ABSENCE_ONLY_OBSERVED"
L0_REASON_CODES = (L0_ABSENCE_ONLY_OBSERVED,)

#: The ONE L1 code in R1. The level comes from the observation; any active
#: scoped rule only annotates it through `exclusion_basis`.
L1_POSITIVE_VALUE_CONTRAST = "L1_POSITIVE_VALUE_CONTRAST"
L1_REASON_CODES = (L1_POSITIVE_VALUE_CONTRAST,)

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


#: Which Prompt-8E status each R1 reason code corresponds to, kept so the runs
#: can be compared row by row without re-deriving 8E. 8E had no notion of a
#: redirect or of containment, so the three semantic NOT_COVERED codes were
#: POSITIVE_ALTERNATIVE_OBSERVED there and are corrections here.
ALL_REASON_CODES = (NOT_COVERED_REASON_CODES + L0_REASON_CODES
                    + L1_REASON_CODES + L2_REASON_CODES)

PROMPT8E_STATUS_FOR_REASON_CODE = {
    NOT_COVERED_EXACT_EQUAL: "SHARED_OBSERVED",
    NOT_COVERED_CANONICALLY_EQUIVALENT: "POSITIVE_ALTERNATIVE_OBSERVED",
    NOT_COVERED_SEMANTIC_ENTAILMENT: "POSITIVE_ALTERNATIVE_OBSERVED",
    NOT_COVERED_COMPATIBLE_QUALIFIED: "POSITIVE_ALTERNATIVE_OBSERVED",
    NOT_COVERED_SCOPED_VALUE_EQUIVALENT: "SHARED_OBSERVED",
    L0_ABSENCE_ONLY_OBSERVED: "ABSENCE_ONLY_OBSERVED",
    L1_POSITIVE_VALUE_CONTRAST: "POSITIVE_ALTERNATIVE_OBSERVED",
    **{code: "POSITIVE_ALTERNATIVE_OBSERVED" for code in L2_REASON_CODES},
}

MULTI_VALUED_PREDICATE_NOTE = (
    "L1 records that the candidate has a DIFFERENT observed counterpart for the "
    "same predicate and direction in the pinned KG snapshot. For a multi-valued "
    "predicate the candidate may hold the Answer's counterpart as well without "
    "this snapshot recording it, so L1 is an observed positive contrast and "
    "nothing stronger. Only an EvidenceProof reaches L2.")

# --- 3) THE SECOND AXIS: EXCLUSION BASIS -------------------------------------
# The level says WHAT WAS OBSERVED. The exclusion basis says HOW STRONG the
# argument behind it is. Keeping them apart is the whole point of R1: an
# empirical single-valued observation may strengthen the reading of an L1
# contrast, and may never decide whether the contrast exists.

EXCLUSION_BASIS_NONE = "NONE"
EXCLUSION_BASIS_SCOPED_EMPIRICAL = "SCOPED_EMPIRICAL"
EXCLUSION_BASIS_FORMAL_PROOF = "FORMAL_PROOF"

EXCLUSION_BASES = (EXCLUSION_BASIS_NONE, EXCLUSION_BASIS_SCOPED_EMPIRICAL,
                   EXCLUSION_BASIS_FORMAL_PROOF)

EXCLUSION_BASIS_DEFINITION = {
    EXCLUSION_BASIS_NONE: (
        "Positive observed contrast only, or absence only. No exclusion "
        "argument is attached."),
    EXCLUSION_BASIS_SCOPED_EMPIRICAL: (
        "An L1 positive observed contrast additionally supported by an ACTIVE, "
        "explicitly local empirical rule: the predicate was observed to carry "
        "at most one canonical object across the declared scope, with adequate "
        "support and zero observed violations. Empirical and scoped, and never "
        "described as universal functionality."),
    EXCLUSION_BASIS_FORMAL_PROOF: (
        "An L2 verified exclusion whose EvidenceProof carries premises, a "
        "conclusion and an ontology or schema source."),
}

#: Which basis each level may carry. L2 must carry a proof; L0 carries none.
ALLOWED_EXCLUSION_BASES = {
    LEVEL_NOT_COVERED: (EXCLUSION_BASIS_NONE,),
    LEVEL_L0: (EXCLUSION_BASIS_NONE,),
    LEVEL_L1: (EXCLUSION_BASIS_NONE, EXCLUSION_BASIS_SCOPED_EMPIRICAL),
    LEVEL_L2: (EXCLUSION_BASIS_FORMAL_PROOF,),
}

# --- 4) SEMANTIC RELATIONS AND SEMANTIC SAFETY REPORTING ---------------------

RELATION_EXACT_EQUAL = "EXACT_EQUAL"
RELATION_CANONICALLY_EQUIVALENT = "CANONICALLY_EQUIVALENT"
RELATION_CANDIDATE_UNDER_CLAIM = "CANDIDATE_OBJECT_DESCENDANT_OF_CLAIM_OBJECT"
RELATION_CLAIM_UNDER_CANDIDATE = "CLAIM_OBJECT_DESCENDANT_OF_CANDIDATE_OBJECT"
RELATION_PROVEN_DISJOINT = "PROVEN_DISJOINT"
RELATION_UNRELATED_OR_UNKNOWN = "UNRELATED_OR_UNKNOWN"
RELATION_UNAVAILABLE = "SEMANTIC_RELATION_UNAVAILABLE"

# --- Prompt 8H-B2-E additions: predicate-scoped relation domains -------------
#
# WHY TWO NEW RELATIONS EXIST
#   The v1 closure admits ONE relation kind, administrative place containment,
#   and applies it to EVERY predicate key. That makes two very different
#   findings indistinguishable:
#
#     "we walked this object's parents and the claim object was not among them"
#     "this object has no parents of any admitted kind, so nothing was walked"
#
#   For `dbp:birthPlace` the first reading is usually right — settlement
#   infoboxes really do carry containment. For `dbp:field` it is never right:
#   measured over the pinned March-2023 snapshot, `Chemistry`, `Radiochemistry`,
#   `Biochemistry`, `Physics`, `Biology`, `Organic_chemistry` and
#   `Physical_chemistry` have ZERO outgoing edges of ANY predicate. Reporting
#   `UNRELATED_OR_UNKNOWN` with `granularity_risk = NONE` for a
#   Radiochemistry/Chemistry pair therefore published a checked negative that
#   was never checked.
#
# WHAT THE TWO NEW RELATIONS MEAN
#   HIERARCHY_NOT_MODELLED  - a relation domain governs this predicate key, and
#                             at least one of the two objects takes part in NO
#                             edge of that domain in the pinned snapshot. It is
#                             a statement about the snapshot's coverage, never
#                             about the world, and it can only ADD a reported
#                             risk. It never moves a level.
#   SCOPED_VALUE_EQUIVALENT - two objects that denote the same value OF ONE
#                             PREDICATE SLOT without being the same entity, e.g.
#                             a country and its demonym under `dbp:nationality`.
#                             It is scoped to declared predicate keys and is
#                             never a global entity identity.
RELATION_HIERARCHY_NOT_MODELLED = "HIERARCHY_NOT_MODELLED_FOR_THESE_OBJECTS"
RELATION_SCOPED_VALUE_EQUIVALENT = "PREDICATE_SCOPED_VALUE_EQUIVALENT"

#: Did the bounded closure actually run for this (fact, candidate) pair?
SEMANTIC_CHECK_CLOSURE_RAN = "CLOSURE_RAN"
SEMANTIC_CHECK_INDEX_UNAVAILABLE = "SEMANTIC_INDEX_UNAVAILABLE"
SEMANTIC_CHECK_NOT_APPLICABLE = "NOT_APPLICABLE_NO_OBSERVED_OBJECT"

#: Granularity risk is REPORTED, never used to move a level. PRESENT means the
#: claim object lies under a candidate object, so the candidate holds the more
#: general statement; UNRESOLVED means the closure could not run and the
#: question was never examined. Both block main-corpus eligibility; neither
#: turns an observed positive contrast back into an absence.
GRANULARITY_RISK_NONE = "NONE"
GRANULARITY_RISK_PRESENT = "CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT"
GRANULARITY_RISK_UNRESOLVED = "UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE"

#: A fourth reported state, added by Prompt 8H-B2-E. The closure RAN, the index
#: was available, and a relation domain governs this predicate key — but the
#: pinned snapshot records no hierarchy edge whatsoever for one or both of the
#: objects, so "no path" carries no information. Like the other two non-NONE
#: states it is REPORTED and blocks main-corpus safety; it never changes a
#: level, never relabels L1 as L0, and never creates L1 or L2.
GRANULARITY_RISK_HIERARCHY_UNMODELLED = "HIERARCHY_NOT_MODELLED_FOR_THESE_OBJECTS"

PARENT_CHILD_NOTE = (
    "Parent-child relatedness REMOVES apparent contrast by making a fact "
    "NOT_COVERED. It never manufactures L1 or L2 exclusion, and an unavailable "
    "semantic index never relabels an observed positive alternative as an "
    "absence: that a candidate's object is unrelated to the claim object in the "
    "traversed hierarchy is a statement about the traversed edges.")

# --- 5) EVIDENCE POLICIES AND MCQ-LEVEL EVIDENCE -----------------------------

POLICY_STRICT_L2 = "strict-l2"
POLICY_MAIN_L1 = "main-l1"
POLICY_DIAGNOSTIC_L0 = "diagnostic-l0"

EVIDENCE_POLICIES = (POLICY_STRICT_L2, POLICY_MAIN_L1, POLICY_DIAGNOSTIC_L0)

#: The tier order. The order of this tuple IS the priority.
POLICY_PRIORITY = (POLICY_STRICT_L2, POLICY_MAIN_L1, POLICY_DIAGNOSTIC_L0)

#: The weakest level that counts as coverage under each policy.
POLICY_MINIMUM_LEVEL = {
    POLICY_STRICT_L2: LEVEL_L2,
    POLICY_MAIN_L1: LEVEL_L1,
    POLICY_DIAGNOSTIC_L0: LEVEL_L0,
}

COVERING_LEVELS = {
    POLICY_STRICT_L2: frozenset({LEVEL_L2}),
    POLICY_MAIN_L1: frozenset({LEVEL_L1, LEVEL_L2}),
    POLICY_DIAGNOSTIC_L0: frozenset({LEVEL_L0, LEVEL_L1, LEVEL_L2}),
}

#: Which policies may produce a MAIN-corpus item. diagnostic-l0 may not.
MAIN_CORPUS_POLICIES = frozenset({POLICY_STRICT_L2, POLICY_MAIN_L1})

POLICY_NOTE = {
    POLICY_STRICT_L2: (
        "Only a verified exclusion, carried by an EvidenceProof, covers a "
        "distractor."),
    POLICY_MAIN_L1: (
        "A positive observed contrast (L1) or a verified exclusion (L2) covers "
        "a distractor. The main-corpus policy."),
    POLICY_DIAGNOSTIC_L0: (
        "Absence-only observation (L0) also covers a distractor. DIAGNOSTIC "
        "ONLY: an L0-only result is an observation about one snapshot and is "
        "not eligible for the main corpus."),
}

#: The MCQ-level evidence of §7: the WEAKEST per-distractor best evidence.
MCQ_LEVEL_FOR_LEVEL = {
    LEVEL_L2: "MCQ-L2",
    LEVEL_L1: "MCQ-L1",
    LEVEL_L0: "MCQ-L0",
    LEVEL_NOT_COVERED: "MCQ-NOT_COVERED",
}

MCQ_LEVEL_NOTE = (
    "MCQ_level = min over distractors of the best evidence level any rationale "
    "fact supplies for that distractor. MCQ-L2 requires every distractor to be "
    "covered by L2 evidence; MCQ-L1 requires every distractor to reach at least "
    "L1 while at least one lacks L2; MCQ-L0 means at least one distractor is "
    "covered only by L0.")

# --- 6) RULE TYPES, SCOPES AND ACTIVATION ------------------------------------
# One annotation rule type and five proof rule types. R1 removed the Prompt-8F
# rule types that CREATED an L1 level (CURATED_MUTUALLY_EXCLUSIVE,
# SCOPED_CLOSED_WORLD_SLOT, SOURCE_VALIDATED_POSITIVE_CONTRAST): under the
# corrected taxonomy the observation decides the level and a rule may only
# annotate it. They are recoverable from commit 1b81f9a if a later task needs a
# curated scoped rule.

RULE_TYPE_EMPIRICAL_SINGLE_VALUED = "EMPIRICALLY_SINGLE_VALUED_IN_SCOPE"
ANNOTATION_RULE_TYPES = (RULE_TYPE_EMPIRICAL_SINGLE_VALUED,)

RULE_TYPE_FUNCTIONAL_PROPERTY = "FORMAL_FUNCTIONAL_PROPERTY_CONFLICT"
RULE_TYPE_MAX_CARDINALITY = "FORMAL_MAX_CARDINALITY_CONFLICT"
RULE_TYPE_EXPLICIT_NEGATIVE = "EXPLICIT_NEGATIVE_PROPERTY_ASSERTION"
RULE_TYPE_DISJOINT_VALUE = "FORMAL_DISJOINT_VALUE_CONFLICT"
RULE_TYPE_TEMPORAL_EXCLUSIVE = "TEMPORALLY_SCOPED_EXCLUSIVE_CONFLICT"

L2_RULE_TYPES = (
    RULE_TYPE_FUNCTIONAL_PROPERTY, RULE_TYPE_MAX_CARDINALITY,
    RULE_TYPE_EXPLICIT_NEGATIVE, RULE_TYPE_DISJOINT_VALUE,
    RULE_TYPE_TEMPORAL_EXCLUSIVE,
)

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

#: Reasons a derived empirical rule is recorded but NOT activated. Each is a
#: scientific position, so each is named rather than left implicit.
NOT_ACTIVE_INSUFFICIENT_SUPPORT = "INSUFFICIENT_OBSERVED_SUPPORT_IN_SCOPE"
NOT_ACTIVE_CARDINALITY_VIOLATION = "OBSERVED_CARDINALITY_VIOLATION_IN_SCOPE"
NOT_ACTIVE_IN_DIRECTION = "IN_DIRECTION_EMPIRICAL_CARDINALITY_NOT_TRUSTED"
NOT_ACTIVE_PREDICATE_REJECTED = "PREDICATE_REJECTED_BY_PREDICATE_POLICY"

# --- 7) QUALIFIERS -----------------------------------------------------------

QUALIFIER_UNAVAILABLE = "UNAVAILABLE_IN_SOURCE"
QUALIFIER_PRESENT = "PRESENT"

QUALIFIER_NOTE = (
    "DBpedia infobox facts carry no statement-level qualifier structure, so the "
    "pilot records qualifier_status = UNAVAILABLE_IN_SOURCE and creates no "
    "temporal or location-qualified L2 evidence. RationaleProposition carries a "
    "qualifiers field so a future qualified source can be added without "
    "changing the object model; nothing fabricates one.")

# --- 8) AUTOMATIC GENERATION VERSUS LATER HUMAN EVALUATION -------------------

HUMAN_EVALUATION_NOT_STARTED = "NOT_STARTED"

#: Attached to every generated record. `publishable_final = false` means the
#: 100-question corpus and its human evaluation have not been completed. It does
#: NOT mean a human selected or edited this item: generation is fully automatic.
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

# --- 9) SELECTION AND FALLBACK STATUSES --------------------------------------

SELECTION_STRICT_L2 = "ALGORITHM_SELECTED_STRICT_L2"
SELECTION_MAIN_L1 = "ALGORITHM_SELECTED_MAIN_L1"
SELECTION_DIAGNOSTIC_L0 = "ALGORITHM_SELECTED_DIAGNOSTIC_L0_ONLY"
SELECTION_NO_FULL_COVERAGE = "NO_FULL_COVERAGE_IN_SELECTED_CLASS"
SELECTION_NO_QUALITY_ELIGIBLE = "NO_QUALITY_ELIGIBLE_RATIONALE_IN_SELECTED_CLASS"
SELECTION_PRIMARY_NOT_READY = "PRIMARY_NOT_READY"

SELECTION_STATUS_FOR_POLICY = {
    POLICY_STRICT_L2: SELECTION_STRICT_L2,
    POLICY_MAIN_L1: SELECTION_MAIN_L1,
    POLICY_DIAGNOSTIC_L0: SELECTION_DIAGNOSTIC_L0,
}

FALLBACK_L0_ONLY = "FALLBACK_CLASS_REQUIRED_L0_ONLY"
FALLBACK_NO_FULL_COVERAGE = "FALLBACK_CLASS_REQUIRED_NO_FULL_COVERAGE"
FALLBACK_NO_QUALITY_ELIGIBLE = (
    "FALLBACK_CLASS_REQUIRED_NO_QUALITY_ELIGIBLE_RATIONALE")
FALLBACK_SEMANTIC_RISK = "FALLBACK_CLASS_REQUIRED_UNRESOLVED_GRANULARITY_RISK"

#: R1 emits the request and stops. No class selection, candidate retrieval,
#: mapping, graph construction or LRoleSim run happens for a fallback class.
FALLBACK_NEXT_STAGE = "FALLBACK_CLASS_GRAPH_AND_LROLESIM_RUN_IN_A_LATER_TASK"

# --- 10) COMBINATION SEARCH SCOPE --------------------------------------------

SEARCH_FULL_EXACT = "FULL_EXACT"
SEARCH_POOL_EXACT = "POOL_EXACT"

DEFAULT_MAX_EXACT_COMBINATIONS = 200_000
DEFAULT_POOL_TOP_BY_SCORE = 75
DEFAULT_POOL_EVIDENCE_RESCUE = 25
DEFAULT_MAX_POOL_SIZE = 100

POOL_POLICY_NAME = "top_lrolesim_plus_evidence_rescue_v1"

POOL_OPTIMALITY_NOTE = (
    "POOL_EXACT enumerates every k-candidate combination INSIDE a bounded pool. "
    "The result is exact for that pool only, and the run makes no optimality "
    "claim over the full ranking: read global_optimality_claim and "
    "pool_optimality_claim on the same record for the exact scope.")

# --- 11) SET-COVER PARAMETERS ------------------------------------------------

DEFAULT_K = 3
DEFAULT_RHO = 3
MIN_K = 1
MAX_K = 5

SET_COVER_ALGORITHM = "exact_minimum_cardinality_bitmask_dp"
SET_COVER_COMPLEXITY = "O(m * 2^k)"

LEGACY_ONE_FACT_SPECIAL_CASE_NOTE = (
    "The legacy |R| = 1 feasibility condition (AUDIT item EX-3) is not applied. "
    "Feasibility is established by the exact minimum-cardinality set-cover "
    "result and by nothing else.")

SET_COVER_PROVENANCE_NOTE = (
    "Set cover, bitmask dynamic programming and Hungarian matching are "
    "textbook. Nothing in this package is presented as a newly invented "
    "algorithm; the contribution is the formulation and the evidence model "
    "around it.")

#: How many equally-minimum-cardinality rationales the ranking may enumerate
#: before it reports itself bounded. The pilot is expected to stay COMPLETE.
DEFAULT_MAX_MINIMUM_RATIONALE_CANDIDATES = 200_000
ENUMERATION_COMPLETE = "COMPLETE"
ENUMERATION_BOUNDED = "BOUNDED"

# --- 12) LANGUAGE THAT MAY NEVER BE EMITTED ----------------------------------
# Checked by tests against every produced artefact. A substring check applied to
# whole files, so it cannot tell a claim from a disclaimer quoting the same
# words — deliberately, since a checker that parsed intent would be the thing
# most likely to be wrong.

FORBIDDEN_NEGATIVE_CLAIM_PHRASES = (
    "does not have", "doesn't have", "is false", "are false", "negative fact",
    "verified false", "proven false", "proved false", "logically excluded",
    "known to be false", "false fact", "definitely not", "globally optimal",
    "human-approved", "human approved",
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
                f"R1 reports evidence levels over the pinned KG snapshot and "
                f"never asserts that a triple is refuted, that a pool result is "
                f"a global optimum, or that an item has been evaluated.")


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


def validate_exclusion_basis(level: str, basis: str, where: str = "") -> str:
    """The two axes must stay consistent: an L0 absence carries no exclusion
    argument, and only a proved L2 carries FORMAL_PROOF."""
    validate_level(level)
    if basis not in EXCLUSION_BASES:
        raise RationaleV3ContractError(
            f"{where or 'assignment'}: unknown exclusion_basis {basis!r}")
    if basis not in ALLOWED_EXCLUSION_BASES[level]:
        raise RationaleV3ContractError(
            f"{where or 'assignment'}: exclusion_basis {basis!r} is not "
            f"permitted at level {level}; expected one of "
            f"{ALLOWED_EXCLUSION_BASES[level]}")
    return basis


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


def mcq_evidence_level(per_distractor_best_levels: Iterable[str]) -> str:
    """MCQ_level = min_d best_level(d), reported in the MCQ-* vocabulary."""
    return MCQ_LEVEL_FOR_LEVEL[weakest_level(per_distractor_best_levels)]


# --- 13) THE VALUE TYPES -----------------------------------------------------

def _require_plain_uri(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RationaleV3ContractError(
            f"{name} must be a non-empty string, got {value!r}")
    if value.startswith("<") or value.endswith(">"):
        raise RationaleV3ContractError(
            f"{name} must be unbracketed, got {value!r}")
    return value


@dataclass(frozen=True)
class AnswerFact:
    """One observed Answer fact f = (kappa, o_A), read from the frozen Prompt-8D
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
    def key_tuple(self) -> tuple[str, str]:
        return (self.predicate_uri, self.direction)

    @property
    def canonical_key(self) -> tuple[str, str, str]:
        """The final unresolved tie-break order."""
        return (self.predicate_uri, self.direction, self.counterpart_uri)


@dataclass(frozen=True)
class RationaleProposition:
    """The proposition object.

    `claim_object_uri` equals `source_object_uri` in R1: no source object is
    generalised to an ancestor for verbalization in this task. The two fields
    stay distinct so a later task can generalise without changing the schema.
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
        for name in ("predicate_uri", "source_object_uri", "claim_object_uri"):
            _require_plain_uri(getattr(self, name), name)
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
        return cls(predicate_uri=fact.predicate_uri, direction=fact.direction,
                   source_object_uri=fact.counterpart_uri,
                   claim_object_uri=fact.counterpart_uri)

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
    """The proof object. Required for EVERY L2 assignment.

    An L2 level with no proof is a contradiction in terms, so `evidence.py`
    refuses to build one and `validate_l2_assignment` is the checkable
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
                f"{self.rule_id}: an EvidenceProof must carry a premise")
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
