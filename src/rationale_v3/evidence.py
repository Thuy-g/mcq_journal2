############################################################################
# src/rationale_v3/evidence.py
#
# Evidence levels NOT_COVERED / L0 / L1 / L2 for one Answer fact against one
# candidate, plus the SEPARATE exclusion-basis axis.
#
# THE R1 CORRECTION
#   The LEVEL is decided by the OBSERVATION alone:
#
#     candidate supports the claim            -> NOT_COVERED   (checked first)
#     candidate has no object for the key     -> L0
#     candidate has an alternative object     -> L1
#     a machine-checkable proof exists        -> L2 with an EvidenceProof
#
#   A scoped empirical single-valued rule NEVER decides whether a positive
#   alternative is L0 or L1. It may only annotate an established L1 with
#   exclusion_basis = SCOPED_EMPIRICAL, which selector.py may prefer among
#   equally strong rationales and which no policy may promote to L2.
#
#   For a multi-valued predicate the candidate may hold the Answer's object as
#   well without the snapshot recording it, so L1 means "positive observed
#   contrast" and never "the candidate could not hold that object". That
#   distinction lives in exclusion_basis, not in a silent downgrade.
#
# WHY SEMANTIC SUPPORT IS CHECKED FIRST
#   A candidate holding the Answer's object under a redirect, or an object lying
#   UNDER it in a containment hierarchy, SUPPORTS the proposition and must not
#   cover the candidate at any level, so the test runs before any rule.
#
# WHY "WE DID NOT LOOK" IS NOT "WE FOUND NOTHING"
#   `semantic_check_status` separates a closure that ran and found no path from
#   a missing index. An unavailable index no longer relabels an observed
#   positive alternative as an absence; it is recorded as
#   GRANULARITY_RISK_UNRESOLVED, which blocks main-corpus eligibility instead.
#
# OFFLINE AND PURE apart from the policy file it is given. The Open-World
# boundary and the level vocabulary are stated once, in contracts.py.
############################################################################

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from rationale_v3.contracts import (
    ANNOTATION_RULE_TYPES,
    EXCLUSION_BASIS_FORMAL_PROOF,
    EXCLUSION_BASIS_NONE,
    EXCLUSION_BASIS_SCOPED_EMPIRICAL,
    GRANULARITY_RISK_HIERARCHY_UNMODELLED,
    GRANULARITY_RISK_NONE,
    GRANULARITY_RISK_PRESENT,
    GRANULARITY_RISK_UNRESOLVED,
    L0_ABSENCE_ONLY_OBSERVED,
    L1_POSITIVE_VALUE_CONTRAST,
    L2_REASON_FOR_RULE_TYPE,
    L2_RULE_TYPES,
    LEVEL_L0,
    LEVEL_L1,
    LEVEL_L2,
    LEVEL_NOT_COVERED,
    NOT_ACTIVE_CARDINALITY_VIOLATION,
    NOT_ACTIVE_IN_DIRECTION,
    NOT_ACTIVE_INSUFFICIENT_SUPPORT,
    NOT_ACTIVE_PREDICATE_REJECTED,
    NOT_COVERED_CANONICALLY_EQUIVALENT,
    NOT_COVERED_EXACT_EQUAL,
    NOT_COVERED_SCOPED_VALUE_EQUIVALENT,
    NOT_COVERED_SEMANTIC_ENTAILMENT,
    QUALIFIER_UNAVAILABLE,
    RELATION_CANDIDATE_UNDER_CLAIM,
    RELATION_CANONICALLY_EQUIVALENT,
    RELATION_CLAIM_UNDER_CANDIDATE,
    RELATION_EXACT_EQUAL,
    RELATION_HIERARCHY_NOT_MODELLED,
    RELATION_SCOPED_VALUE_EQUIVALENT,
    RELATION_UNAVAILABLE,
    RULE_ACTIVE,
    RULE_INACTIVE,
    RULE_PROPOSED_NOT_ACTIVE,
    RULE_TYPE_EMPIRICAL_SINGLE_VALUED,
    SEMANTIC_CHECK_CLOSURE_RAN,
    SEMANTIC_CHECK_INDEX_UNAVAILABLE,
    SEMANTIC_CHECK_NOT_APPLICABLE,
    EvidenceProof,
    RationaleProposition,
    RationaleV3ContractError,
    validate_exclusion_basis,
    validate_l2_assignment,
)
from rationale_v3.semantic_relations import (
    SemanticIndex,
    SemanticRelationResult,
    normalize_uri,
)

VERSION = "rationale_v3.evidence/2.1.0-b2ef"


class EvidenceRuleError(RationaleV3ContractError):
    """The evidence-rule policy is missing, malformed or self-contradictory."""


# --- 1) RULES ----------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceRule:
    """One annotation rule or one L2 proof rule.

    A rule is DATA, not code: activation is a field, so an inactive rule is
    visible in the published policy audit instead of being absent from it.
    """

    rule_id: str
    rule_type: str
    predicate_uri: str
    direction: str
    scope: str
    scope_kind: str
    required_evidence: tuple[str, ...]
    minimum_support: int
    observed_support: int
    maximum_observed_cardinality: int
    observed_violation_count: int
    source: str
    provenance: str
    version: str
    activation_status: str
    inactive_reason: str = ""
    empirical_label: str = ""
    ontology_source: str = ""
    exclusive_value_sets: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if self.rule_type not in ANNOTATION_RULE_TYPES + L2_RULE_TYPES:
            raise EvidenceRuleError(
                f"{self.rule_id}: unknown rule_type {self.rule_type!r}")
        if self.activation_status not in (RULE_ACTIVE, RULE_PROPOSED_NOT_ACTIVE,
                                          RULE_INACTIVE):
            raise EvidenceRuleError(
                f"{self.rule_id}: unknown activation_status "
                f"{self.activation_status!r}")
        if self.is_l2 and self.activation_status == RULE_ACTIVE:
            if not self.ontology_source:
                raise EvidenceRuleError(
                    f"{self.rule_id}: an ACTIVE L2 rule must name an "
                    f"ontology_source; an exclusion proof with no schema behind "
                    f"it is not a proof")

    @property
    def is_l2(self) -> bool:
        return self.rule_type in L2_RULE_TYPES

    @property
    def is_active(self) -> bool:
        return self.activation_status == RULE_ACTIVE

    def as_record(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "predicate_uri": self.predicate_uri,
            "direction": self.direction,
            "scope": self.scope,
            "scope_kind": self.scope_kind,
            "required_evidence": list(self.required_evidence),
            "minimum_support": self.minimum_support,
            "observed_support": self.observed_support,
            "maximum_observed_cardinality": self.maximum_observed_cardinality,
            "observed_violation_count": self.observed_violation_count,
            "source": self.source,
            "provenance": self.provenance,
            "version": self.version,
            "activation_status": self.activation_status,
            "inactive_reason": self.inactive_reason,
            "empirical_label": self.empirical_label,
            "ontology_source": self.ontology_source,
            "role": ("L2_PROOF_RULE" if self.is_l2
                     else "L1_EXCLUSION_BASIS_ANNOTATION_ONLY"),
        }


@dataclass(frozen=True)
class EmpiricalDerivationConfig:
    """The declared thresholds behind EMPIRICALLY_SINGLE_VALUED_IN_SCOPE.

    In R1 this configuration governs an ANNOTATION only. No value of any field
    here can move a fact between L0 and L1.
    """

    enabled: bool
    scope_kind: str
    scope_note: str
    minimum_support: int
    maximum_observed_canonical_cardinality: int
    maximum_violations: int
    active_directions: tuple[str, ...]
    inactive_direction_reason: Mapping[str, str]
    empirical_label: str
    version: str

    def as_record(self) -> dict:
        return {
            "enabled": self.enabled,
            "rule_type": RULE_TYPE_EMPIRICAL_SINGLE_VALUED,
            "role": "L1_EXCLUSION_BASIS_ANNOTATION_ONLY",
            "scope_kind": self.scope_kind,
            "scope_note": self.scope_note,
            "minimum_support": self.minimum_support,
            "maximum_observed_canonical_cardinality":
                self.maximum_observed_canonical_cardinality,
            "maximum_violations": self.maximum_violations,
            "active_directions": list(self.active_directions),
            "inactive_direction_reason": dict(self.inactive_direction_reason),
            "empirical_label": self.empirical_label,
            "version": self.version,
        }


@dataclass(frozen=True)
class EvidenceRuleBook:
    """Every rule the classifier may consult, curated plus derived."""

    version: str
    policy_sha256: str
    derivation: EmpiricalDerivationConfig
    rules: tuple[EvidenceRule, ...]
    require_semantic_closure_for_annotation: bool
    notes: Mapping[str, str] = field(default_factory=dict)

    def with_rules(self, extra: Iterable[EvidenceRule]) -> "EvidenceRuleBook":
        merged = list(self.rules) + list(extra)
        seen: set[str] = set()
        for rule in merged:
            if rule.rule_id in seen:
                raise EvidenceRuleError(f"duplicate rule id {rule.rule_id!r}")
            seen.add(rule.rule_id)
        return EvidenceRuleBook(
            version=self.version, policy_sha256=self.policy_sha256,
            derivation=self.derivation,
            rules=tuple(sorted(merged, key=lambda r: r.rule_id)),
            require_semantic_closure_for_annotation=(
                self.require_semantic_closure_for_annotation),
            notes=self.notes)

    def active_rules_for(self, predicate_uri: str, direction: str,
                         scope: str) -> tuple[EvidenceRule, ...]:
        """Active rules matching the key AND the scope, L2 first.

        L2 before annotation: the classifier must try to prove exclusion before
        it settles for an annotated observation.
        """
        matched = [rule for rule in self.rules
                   if rule.is_active and rule.predicate_uri == predicate_uri
                   and rule.direction == direction and rule.scope == scope]
        return tuple(sorted(matched, key=lambda r: (0 if r.is_l2 else 1,
                                                    r.rule_id)))

    def counts(self) -> dict:
        active = [r for r in self.rules if r.is_active]
        return {
            "total_rules": len(self.rules),
            "active_rules": len(active),
            "active_annotation_rules": sum(1 for r in active if not r.is_l2),
            "active_l2_rules": sum(1 for r in active if r.is_l2),
            "proposed_not_active_rules": sum(
                1 for r in self.rules
                if r.activation_status == RULE_PROPOSED_NOT_ACTIVE),
            "inactive_rules": sum(1 for r in self.rules
                                  if r.activation_status == RULE_INACTIVE),
        }


def load_evidence_rules(path: str | Path, *,
                        require_semantic_closure_for_annotation: bool = True
                        ) -> EvidenceRuleBook:
    """Read and validate the versioned evidence-rule policy."""
    path = Path(path)
    if not path.is_file():
        raise EvidenceRuleError(f"evidence rule policy not found: {path}")
    raw_text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise EvidenceRuleError(f"{path.name}: {exc}") from exc

    version = str(payload.get("version", "unversioned"))
    raw = payload.get("empirical_single_valued_derivation", {})
    derivation = EmpiricalDerivationConfig(
        enabled=bool(raw.get("enabled", False)),
        scope_kind=str(raw.get("scope_kind", "")),
        scope_note=str(raw.get("scope_note", "")),
        minimum_support=int(raw.get("minimum_support", 5)),
        maximum_observed_canonical_cardinality=int(
            raw.get("maximum_observed_canonical_cardinality", 1)),
        maximum_violations=int(raw.get("maximum_violations", 0)),
        active_directions=tuple(
            str(d) for d in raw.get("active_directions", ("OUT",))),
        inactive_direction_reason={
            str(k): str(v)
            for k, v in raw.get("inactive_direction_reason", {}).items()},
        empirical_label=str(raw.get("empirical_label", "")),
        version=version,
    )

    rules: list[EvidenceRule] = []
    for group, expected in (("annotation_rules", ANNOTATION_RULE_TYPES),
                            ("l2_rules", L2_RULE_TYPES)):
        for entry in payload.get(group, ()):
            rule = _rule_from_record(entry, version)
            if rule.rule_type not in expected:
                raise EvidenceRuleError(
                    f"{path.name}: rule {rule.rule_id} appears under {group} "
                    f"but has rule_type {rule.rule_type!r}")
            rules.append(rule)

    return EvidenceRuleBook(
        version=version,
        policy_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        derivation=derivation,
        rules=tuple(sorted(rules, key=lambda r: r.rule_id)),
        require_semantic_closure_for_annotation=(
            require_semantic_closure_for_annotation),
        notes={str(k): str(v) for k, v in payload.get("notes", {}).items()},
    )


def _rule_from_record(entry: Mapping[str, object], version: str) -> EvidenceRule:
    return EvidenceRule(
        rule_id=str(entry["rule_id"]),
        rule_type=str(entry["rule_type"]),
        predicate_uri=normalize_uri(str(entry["predicate_uri"])),
        direction=str(entry["direction"]),
        scope=str(entry.get("scope", "")),
        scope_kind=str(entry.get("scope_kind", "")),
        required_evidence=tuple(str(v) for v in entry.get("required_evidence", ())),
        minimum_support=int(entry.get("minimum_support", 0)),
        observed_support=int(entry.get("observed_support", 0)),
        maximum_observed_cardinality=int(
            entry.get("maximum_observed_cardinality", 0)),
        observed_violation_count=int(entry.get("observed_violation_count", 0)),
        source=str(entry.get("source", "")),
        provenance=str(entry.get("provenance", "")),
        version=str(entry.get("version", version)),
        activation_status=str(entry.get("activation_status", RULE_INACTIVE)),
        inactive_reason=str(entry.get("inactive_reason", "")),
        empirical_label=str(entry.get("empirical_label", "")),
        ontology_source=str(entry.get("ontology_source", "")),
        exclusive_value_sets=tuple(
            tuple(normalize_uri(str(v)) for v in group)
            for group in entry.get("exclusive_value_sets", ())),
    )


# --- 2) DERIVING THE SCOPED EMPIRICAL ANNOTATION RULES -----------------------

@dataclass(frozen=True)
class ScopeKeyObservation:
    """What the pinned snapshot shows about one (scope, key) cell."""

    scope: str
    predicate_uri: str
    direction: str
    support: int
    maximum_cardinality: int
    violation_count: int
    observed_entity_count: int

    def as_record(self) -> dict:
        return {
            "scope": self.scope,
            "predicate_uri": self.predicate_uri,
            "direction": self.direction,
            "observed_support": self.support,
            "maximum_observed_cardinality": self.maximum_cardinality,
            "observed_violation_count": self.violation_count,
            "scope_entity_count": self.observed_entity_count,
        }


def observe_scope_cardinalities(
    *,
    scope: str,
    observations: Mapping[str, Mapping[tuple[str, str], Sequence[str]]],
    semantic_index: SemanticIndex,
) -> tuple[ScopeKeyObservation, ...]:
    """Support, maximum cardinality and violations for every key in one scope.

    `observations` is {entity_uri: {(predicate_uri, direction): [object_uri]}}
    over EVERY entity in the scope. Cardinality is counted over CANONICAL
    objects, so a redirect pair is one value and not two.
    """
    cells: dict[tuple[str, str], list[int]] = {}
    for entity in sorted(observations):
        for key, objects in observations[entity].items():
            canonical = {semantic_index.canonical(uri) for uri in objects}
            if canonical:
                cells.setdefault(key, []).append(len(canonical))

    entity_count = len(observations)
    return tuple(
        ScopeKeyObservation(
            scope=scope, predicate_uri=predicate_uri, direction=direction,
            support=len(cardinalities), maximum_cardinality=max(cardinalities),
            violation_count=sum(1 for c in cardinalities if c > 1),
            observed_entity_count=entity_count)
        for (predicate_uri, direction), cardinalities in sorted(cells.items()))


def derive_empirical_single_valued_rules(
    observations: Iterable[ScopeKeyObservation],
    *,
    config: EmpiricalDerivationConfig,
    rejected_predicates: Mapping[str, str] = {},
    minimum_support_override: Optional[int] = None,
) -> tuple[EvidenceRule, ...]:
    """One annotation-rule candidate per (scope, key), ACTIVE only when every
    gate passes.

    Every candidate is returned, including the ones that fail: an inactive rule
    with its reason is evidence about the data, and dropping it would leave the
    published support threshold unexaminable.
    """
    if not config.enabled:
        return ()
    minimum_support = (config.minimum_support if minimum_support_override is None
                       else minimum_support_override)

    derived: list[EvidenceRule] = []
    for row in sorted(observations,
                      key=lambda r: (r.scope, r.predicate_uri, r.direction)):
        local = row.predicate_uri.rsplit("/", 1)[-1]
        rule_id = (f"EMP_SV_{_scope_slug(row.scope)}_{row.direction}_{local}"
                   f"_MS{minimum_support}_V1")

        status, reason = RULE_ACTIVE, ""
        if row.predicate_uri in rejected_predicates:
            status, reason = RULE_INACTIVE, NOT_ACTIVE_PREDICATE_REJECTED
        elif row.direction not in config.active_directions:
            status = RULE_PROPOSED_NOT_ACTIVE
            reason = config.inactive_direction_reason.get(
                row.direction, NOT_ACTIVE_IN_DIRECTION)
        elif (row.maximum_cardinality
                > config.maximum_observed_canonical_cardinality
                or row.violation_count > config.maximum_violations):
            status, reason = RULE_INACTIVE, NOT_ACTIVE_CARDINALITY_VIOLATION
        elif row.support < minimum_support:
            status, reason = RULE_PROPOSED_NOT_ACTIVE, NOT_ACTIVE_INSUFFICIENT_SUPPORT

        derived.append(EvidenceRule(
            rule_id=rule_id,
            rule_type=RULE_TYPE_EMPIRICAL_SINGLE_VALUED,
            predicate_uri=row.predicate_uri, direction=row.direction,
            scope=row.scope, scope_kind=config.scope_kind,
            required_evidence=(
                f"observed_support >= {minimum_support}",
                (f"maximum_observed_canonical_cardinality <= "
                 f"{config.maximum_observed_canonical_cardinality}"),
                f"observed_violation_count <= {config.maximum_violations}",
                f"direction in {list(config.active_directions)}",
                "predicate not rejected by predicate_policy",
            ),
            minimum_support=minimum_support, observed_support=row.support,
            maximum_observed_cardinality=row.maximum_cardinality,
            observed_violation_count=row.violation_count,
            source=("derived from the frozen Prompt-8D observed facts for the "
                    "selected local class candidate pool"),
            provenance=config.scope_note, version=config.version,
            activation_status=status, inactive_reason=reason,
            empirical_label=config.empirical_label))
    return tuple(derived)


def _scope_slug(scope: str) -> str:
    """A short, stable, filesystem-safe fragment of a scope URI, for rule ids."""
    tail = scope.rsplit("Category:", 1)[-1].rsplit("/", 1)[-1]
    return "".join(c if c.isalnum() else "_" for c in tail) or "GLOBAL"


# --- 3) THE CLASSIFIER -------------------------------------------------------

@dataclass(frozen=True)
class CandidateObjectRelation:
    """How one candidate object stands against the claim object."""

    candidate_object_uri: str
    relation: SemanticRelationResult

    def as_record(self) -> dict:
        return {"candidate_object_uri": self.candidate_object_uri,
                **self.relation.as_record()}


@dataclass(frozen=True)
class FactCandidateEvidence:
    """level(f, d) and exclusion_basis(f, d), with everything behind both."""

    level: str
    reason_code: str
    exclusion_basis: str
    semantic_check_status: str
    granularity_risk_status: str
    proposition: RationaleProposition
    candidate_uri: str
    candidate_object_uris: tuple[str, ...]
    relations: tuple[CandidateObjectRelation, ...]
    applied_rule_id: str = ""
    applied_rule_type: str = ""
    proof: Optional[EvidenceProof] = None
    blocked_rule_ids: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        where = f"{self.candidate_uri}/{self.reason_code}"
        validate_l2_assignment(self.level, self.proof, where=where)
        validate_exclusion_basis(self.level, self.exclusion_basis, where=where)

    @property
    def granularity_risk(self) -> bool:
        """Any unresolved or present granularity risk. Reported, never used to
        move a level."""
        return self.granularity_risk_status != GRANULARITY_RISK_NONE

    @property
    def scoped_empirical(self) -> bool:
        return self.exclusion_basis == EXCLUSION_BASIS_SCOPED_EMPIRICAL

    def as_record(self) -> dict:
        return {
            "candidate_uri": self.candidate_uri,
            "evidence_level": self.level,
            "reason_code": self.reason_code,
            "exclusion_basis": self.exclusion_basis,
            "semantic_check_status": self.semantic_check_status,
            "granularity_risk": self.granularity_risk_status,
            "applied_rule_id": self.applied_rule_id,
            "applied_rule_type": self.applied_rule_type,
            "candidate_object_uris": list(self.candidate_object_uris),
            "candidate_object_count": len(self.candidate_object_uris),
            "semantic_relations": [r.as_record() for r in self.relations],
            "blocked_rule_ids": list(self.blocked_rule_ids),
            "evidence_proof": (None if self.proof is None
                               else self.proof.as_record()),
            "note": self.note,
            **self.proposition.as_record(),
        }


_SUPPORTING_REASON = {
    RELATION_EXACT_EQUAL: NOT_COVERED_EXACT_EQUAL,
    RELATION_CANONICALLY_EQUIVALENT: NOT_COVERED_CANONICALLY_EQUIVALENT,
    RELATION_CANDIDATE_UNDER_CLAIM: NOT_COVERED_SEMANTIC_ENTAILMENT,
    # Prompt 8H-B2-E: a predicate-scoped VALUE equivalence also supports the
    # proposition — under `dbp:nationality` a candidate recorded as `Germany`
    # answers the same question as an Answer recorded as `Germans`. It gets its
    # own reason code because it is not a claim about entity identity.
    RELATION_SCOPED_VALUE_EQUIVALENT: NOT_COVERED_SCOPED_VALUE_EQUIVALENT,
}


def classify_fact_against_candidate(
    *,
    proposition: RationaleProposition,
    candidate_uri: str,
    candidate_objects: Sequence[str],
    semantic_index: SemanticIndex,
    rulebook: EvidenceRuleBook,
    scope: str,
) -> FactCandidateEvidence:
    """The single place an evidence level is decided.

    The order below is the whole specification:

      1. nothing observed for the key       -> L0, absence only;
      2. any object SUPPORTS the claim      -> NOT_COVERED, before any rule;
      3. an active L2 rule proves exclusion -> L2 with an EvidenceProof;
      4. otherwise                          -> L1 positive value contrast,
                                               annotated NONE or SCOPED_EMPIRICAL.

    Step 1 precedes step 2 only because an empty object set cannot support
    anything; no rule runs before the support test.
    """
    claim = proposition.claim_object_uri
    objects = tuple(sorted({normalize_uri(uri) for uri in candidate_objects}))

    # --- 1) nothing observed for this key on this candidate -----------------
    if not objects:
        return FactCandidateEvidence(
            level=LEVEL_L0, reason_code=L0_ABSENCE_ONLY_OBSERVED,
            exclusion_basis=EXCLUSION_BASIS_NONE,
            semantic_check_status=SEMANTIC_CHECK_NOT_APPLICABLE,
            granularity_risk_status=GRANULARITY_RISK_NONE,
            proposition=proposition, candidate_uri=candidate_uri,
            candidate_object_uris=(), relations=(),
            note=("the pinned snapshot records no value for this key on this "
                  "candidate; absence in one snapshot is an observation"))

    # --- 2) does any observed object SUPPORT the claim? ---------------------
    # The predicate KEY is passed so a predicate-scoped relation domain can
    # govern this pair. Callers before Prompt 8H-B2-E passed no key and got the
    # global domains only; a v1 policy declares exactly one global domain, so
    # the classification is unchanged wherever the v1 policy is in force.
    predicate_key = (proposition.predicate_uri, proposition.direction)
    relations = tuple(
        CandidateObjectRelation(
            uri, semantic_index.classify(claim, uri, predicate_key))
        for uri in objects)
    unavailable = any(item.relation.relation == RELATION_UNAVAILABLE
                      for item in relations)
    closure_ran = semantic_index.available and not unavailable
    semantic_status = (SEMANTIC_CHECK_CLOSURE_RAN if closure_ran
                       else SEMANTIC_CHECK_INDEX_UNAVAILABLE)

    for item in relations:
        reason = _SUPPORTING_REASON.get(item.relation.relation)
        if reason is not None:
            return FactCandidateEvidence(
                level=LEVEL_NOT_COVERED, reason_code=reason,
                exclusion_basis=EXCLUSION_BASIS_NONE,
                semantic_check_status=semantic_status,
                granularity_risk_status=GRANULARITY_RISK_NONE,
                proposition=proposition, candidate_uri=candidate_uri,
                candidate_object_uris=objects, relations=relations,
                note=("the candidate supports this proposition, so the fact "
                      "discriminates nothing here"))

    # Granularity precedence, strongest statement first. A CLAIM_UNDER_CANDIDATE
    # finding is a positive observation and outranks every "we could not look"
    # state; an unavailable index outranks an unmodelled domain because it means
    # nothing at all was checked, not merely this domain.
    if any(item.relation.relation == RELATION_CLAIM_UNDER_CANDIDATE
           for item in relations):
        granularity = GRANULARITY_RISK_PRESENT
    elif not closure_ran:
        granularity = GRANULARITY_RISK_UNRESOLVED
    elif any(item.relation.relation == RELATION_HIERARCHY_NOT_MODELLED
             for item in relations):
        granularity = GRANULARITY_RISK_HIERARCHY_UNMODELLED
    else:
        granularity = GRANULARITY_RISK_NONE

    # --- 3) an L2 rule may prove exclusion ----------------------------------
    blocked: list[str] = []
    annotation: Optional[EvidenceRule] = None
    for rule in rulebook.active_rules_for(proposition.predicate_uri,
                                          proposition.direction, scope):
        if not rule.is_l2:
            if _annotation_applies(
                    rule, objects, closure_ran=closure_ran,
                    require_closure=rulebook.require_semantic_closure_for_annotation):
                annotation = annotation or rule
            else:
                blocked.append(rule.rule_id)
            continue
        proof = build_l2_proof(rule=rule, proposition=proposition,
                               candidate_uri=candidate_uri,
                               candidate_objects=objects, relations=relations,
                               closure_ran=closure_ran)
        if proof is None:
            blocked.append(rule.rule_id)
            continue
        return FactCandidateEvidence(
            level=LEVEL_L2, reason_code=L2_REASON_FOR_RULE_TYPE[rule.rule_type],
            exclusion_basis=EXCLUSION_BASIS_FORMAL_PROOF,
            semantic_check_status=semantic_status,
            granularity_risk_status=granularity,
            proposition=proposition, candidate_uri=candidate_uri,
            candidate_object_uris=objects, relations=relations,
            applied_rule_id=rule.rule_id, applied_rule_type=rule.rule_type,
            proof=proof, blocked_rule_ids=tuple(blocked))

    # --- 4) L1: an observed positive alternative ----------------------------
    if annotation is None:
        basis, note = EXCLUSION_BASIS_NONE, (
            "the candidate has a different observed object for this key; a "
            "positive observed contrast in the pinned snapshot")
    else:
        basis = EXCLUSION_BASIS_SCOPED_EMPIRICAL
        note = (f"positive observed contrast, additionally annotated by "
                f"{annotation.rule_id} inside {annotation.scope}; "
                f"{annotation.empirical_label or 'scoped, not universal'}")
    return FactCandidateEvidence(
        level=LEVEL_L1, reason_code=L1_POSITIVE_VALUE_CONTRAST,
        exclusion_basis=basis, semantic_check_status=semantic_status,
        granularity_risk_status=granularity, proposition=proposition,
        candidate_uri=candidate_uri, candidate_object_uris=objects,
        relations=relations,
        applied_rule_id=(annotation.rule_id if annotation else ""),
        applied_rule_type=(annotation.rule_type if annotation else ""),
        blocked_rule_ids=tuple(blocked), note=note)


def _annotation_applies(rule: EvidenceRule, objects: Sequence[str], *,
                        closure_ran: bool, require_closure: bool) -> bool:
    """Whether a scoped empirical rule may ANNOTATE this candidate.

    A rule derived as "at most one canonical object in this scope" may only
    annotate a candidate that actually shows at most one: if the candidate shows
    two, the scope assumption failed for this very entity. Checking here rather
    than trusting the derivation keeps the two independent.

    When the closure could not run, the stronger SCOPED_EMPIRICAL reading is
    withheld — but the L1 level itself is unaffected, which is the R1 fix.
    """
    if require_closure and not closure_ran:
        return False
    if rule.rule_type == RULE_TYPE_EMPIRICAL_SINGLE_VALUED:
        return len(set(objects)) <= rule.maximum_observed_cardinality
    return True


# --- 4) L2 PROOFS ------------------------------------------------------------

def build_l2_proof(
    *,
    rule: EvidenceRule,
    proposition: RationaleProposition,
    candidate_uri: str,
    candidate_objects: Sequence[str],
    relations: Sequence[CandidateObjectRelation],
    closure_ran: bool,
) -> Optional[EvidenceProof]:
    """Assemble an EvidenceProof, or return None when a premise is missing.

    Returning None is the normal outcome and is not an error: an L2 rule whose
    premises are not all present simply does not fire, and the classifier falls
    through to L1. Every premise is written into the proof, so a reader can
    check the inference rather than trust it.
    """
    if not rule.is_active or not rule.is_l2:
        return None

    premises: list[str] = [
        f"rule {rule.rule_id} of type {rule.rule_type} is ACTIVE",
        f"ontology source: {rule.ontology_source}",
        (f"the Answer is observed with {proposition.predicate_uri} "
         f"({proposition.direction}) -> {proposition.claim_object_uri}"),
    ]

    if rule.rule_type in ("FORMAL_FUNCTIONAL_PROPERTY_CONFLICT",
                          "FORMAL_MAX_CARDINALITY_CONFLICT"):
        if not candidate_objects or not closure_ran:
            # Without the closure, "no parent-child support relation" is an
            # unchecked premise, and an exclusion proof may not rest on one.
            return None
        for item in relations:
            if item.relation.relation in (RELATION_EXACT_EQUAL,
                                          RELATION_CANONICALLY_EQUIVALENT,
                                          RELATION_CANDIDATE_UNDER_CLAIM,
                                          RELATION_CLAIM_UNDER_CANDIDATE,
                                          RELATION_SCOPED_VALUE_EQUIVALENT,
                                          RELATION_HIERARCHY_NOT_MODELLED):
                # The last two are Prompt 8H-B2-E additions and BOTH block a
                # proof: a scoped value equivalence means the objects agree, and
                # an unmodelled hierarchy means "no parent-child support
                # relation" was never actually established.
                return None
        premises.append(f"the candidate {candidate_uri} is observed with "
                        f"{sorted(candidate_objects)} for the same key")
        premises.append(
            "every observed candidate object is canonically distinct from the "
            "claim object and stands in no parent-child relation to it")
        conclusion = (f"under the declared cardinality constraint the candidate "
                      f"cannot additionally hold {proposition.claim_object_uri} "
                      f"for this key")

    elif rule.rule_type == "EXPLICIT_NEGATIVE_PROPERTY_ASSERTION":
        premises.append(
            f"the source declares an explicit negative property assertion for "
            f"{candidate_uri} on this key and object")
        conclusion = (f"the source excludes {proposition.claim_object_uri} for "
                      f"{candidate_uri} on this key")

    elif rule.rule_type == "FORMAL_DISJOINT_VALUE_CONFLICT":
        hit = None
        for group in rule.exclusive_value_sets:
            members = set(group)
            if proposition.claim_object_uri in members:
                for obj in candidate_objects:
                    if obj in members and obj != proposition.claim_object_uri:
                        hit = (proposition.claim_object_uri, obj)
                        break
            if hit:
                break
        if hit is None:
            return None
        premises.append(f"{hit[0]} and {hit[1]} are declared mutually exclusive "
                        f"values for this key")
        conclusion = (f"the candidate's observed value {hit[1]} excludes "
                      f"{hit[0]} for this key")

    elif rule.rule_type == "TEMPORALLY_SCOPED_EXCLUSIVE_CONFLICT":
        # No qualifiers in the source: temporal L2 is unreachable, by
        # construction and not by accident.
        if (proposition.qualifier_status == QUALIFIER_UNAVAILABLE
                or not proposition.qualifiers):
            return None
        premises.append(f"both statements carry normalized temporal qualifiers "
                        f"{sorted(proposition.qualifiers)} over an overlapping "
                        f"interval")
        conclusion = (f"within the overlapping interval the candidate cannot "
                      f"hold {proposition.claim_object_uri} for this key")
    else:
        return None

    return EvidenceProof(
        rule_id=rule.rule_id, rule_type=rule.rule_type,
        premises=tuple(premises), conclusion=conclusion,
        predicate_uri=proposition.predicate_uri,
        direction=proposition.direction,
        answer_object_uri=proposition.claim_object_uri,
        candidate_object_uris=tuple(sorted(candidate_objects)),
        qualifier_context=proposition.qualifier_status,
        ontology_source=rule.ontology_source,
        provenance=rule.provenance or rule.source)
