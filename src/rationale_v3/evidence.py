############################################################################
# src/rationale_v3/evidence.py
#
# Evidence levels L0 / L1 / L2 for one Answer fact against one candidate.
#
# THE ONE QUESTION THIS MODULE ANSWERS
#   How strong is the evidence that Answer fact f distinguishes the Answer from
#   candidate d, in the pinned snapshot?
#
#       level(f, d) in {NOT_COVERED, L0, L1, L2}
#
#   and, always, WHICH RULE said so.
#
# WHY THE MULTI-VALUED CASE DRIVES THE DESIGN
#   For a multi-valued predicate, "the candidate has a different object" is not
#   evidence of anything much: the candidate may hold the Answer's object as well
#   and the snapshot simply not record it. Prompt 8E gave that case the same name
#   (POSITIVE_ALTERNATIVE_OBSERVED) as the case where the predicate really does
#   admit one value. V3 separates them:
#
#     * different objects, no rule           -> L0_DIFFERENT_OBJECTS_NONEXCLUSIVE
#     * different objects, ACTIVE scoped rule -> L1
#     * different objects, machine proof      -> L2 with an EvidenceProof
#
#   and it refuses to reach L1 or L2 by any other route.
#
# WHY SEMANTIC SUPPORT IS CHECKED FIRST
#   A candidate that holds the Answer's object under a redirect, or an object
#   lying UNDER the Answer's object in a containment hierarchy, SUPPORTS the
#   Answer's proposition. Such a fact discriminates nothing and must not cover
#   the candidate at any level. This check runs before any rule, so no rule can
#   promote a supporting candidate to a contrast.
#
# WHY "WE DID NOT LOOK" IS NOT "WE FOUND NOTHING"
#   `require_semantic_closure_for_l1` distinguishes two states that are easy to
#   conflate: the closure ran over the allowlisted edges and found no containment
#   path (UNRELATED_OR_UNKNOWN, L1 permitted), and no semantic index existed at
#   all (SEMANTIC_RELATION_UNAVAILABLE, level capped at L0). Treating the second
#   as the first would let a missing cache silently manufacture L1 yield.
#
# OPEN WORLD
#   L0 is an observation about one snapshot and never a negative fact. L1 is
#   valid inside a declared scope and is never universal. Only L2 claims
#   exclusion, and only with a proof object (CLAUDE.md items 7 and 8).
#
# OFFLINE AND PURE apart from reading the policy file it is given.
############################################################################

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from rationale_v3.contracts import (
    L1_REASON_FOR_RULE_TYPE,
    L1_RULE_TYPES,
    L2_REASON_FOR_RULE_TYPE,
    L2_RULE_TYPES,
    LEVEL_L0,
    LEVEL_L1,
    LEVEL_L2,
    LEVEL_NOT_COVERED,
    L0_DIFFERENT_OBJECTS_NONEXCLUSIVE,
    L0_GRANULARITY_RISK,
    L0_KEY_ABSENT,
    L0_SEMANTIC_RELATION_UNKNOWN,
    NOT_ACTIVE_CARDINALITY_VIOLATION,
    NOT_ACTIVE_IN_DIRECTION,
    NOT_ACTIVE_INSUFFICIENT_SUPPORT,
    NOT_ACTIVE_PREDICATE_REJECTED,
    NOT_COVERED_CANONICALLY_EQUIVALENT,
    NOT_COVERED_EXACT_EQUAL,
    NOT_COVERED_SEMANTIC_ENTAILMENT,
    QUALIFIER_UNAVAILABLE,
    RELATION_CANDIDATE_UNDER_CLAIM,
    RELATION_CANONICALLY_EQUIVALENT,
    RELATION_CLAIM_UNDER_CANDIDATE,
    RELATION_EXACT_EQUAL,
    RELATION_UNAVAILABLE,
    RULE_ACTIVE,
    RULE_INACTIVE,
    RULE_PROPOSED_NOT_ACTIVE,
    RULE_TYPE_EMPIRICAL_SINGLE_VALUED,
    RULE_TYPE_SCOPED_CLOSED_WORLD_SLOT,
    SEMANTIC_GRANULARITY_RISK,
    EvidenceProof,
    RationaleProposition,
    RationaleV3ContractError,
    validate_l2_assignment,
)
from rationale_v3.semantic_relations import (
    SemanticIndex,
    SemanticRelationResult,
    normalize_uri,
)

VERSION = "rationale_v3.evidence/1.0.0"


class EvidenceRuleError(RationaleV3ContractError):
    """The evidence-rule policy is missing, malformed or self-contradictory."""


# ==========================================================================
# 1) RULES
# ==========================================================================

@dataclass(frozen=True)
class EvidenceRule:
    """One L1 or L2 rule, with every field Prompt 8F section 6.3 requires.

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
    resolves_granularity_risk: bool = False
    ontology_source: str = ""
    exclusive_value_sets: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if self.rule_type not in L1_RULE_TYPES + L2_RULE_TYPES:
            raise EvidenceRuleError(
                f"{self.rule_id}: unknown rule_type {self.rule_type!r}")
        if self.activation_status not in (RULE_ACTIVE, RULE_PROPOSED_NOT_ACTIVE,
                                          RULE_INACTIVE):
            raise EvidenceRuleError(
                f"{self.rule_id}: unknown activation_status "
                f"{self.activation_status!r}")
        if self.rule_type in L2_RULE_TYPES and self.activation_status == RULE_ACTIVE:
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

    @property
    def key_tuple(self) -> tuple[str, str]:
        return (self.predicate_uri, self.direction)

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
            "resolves_granularity_risk": self.resolves_granularity_risk,
            "ontology_source": self.ontology_source,
            "evidence_level": LEVEL_L2 if self.is_l2 else LEVEL_L1,
        }


@dataclass(frozen=True)
class EmpiricalDerivationConfig:
    """The declared thresholds behind EMPIRICALLY_SINGLE_VALUED_IN_SCOPE."""

    enabled: bool
    scope_kind: str
    scope_note: str
    minimum_support: int
    support_ablation_values: tuple[int, ...]
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
            "scope_kind": self.scope_kind,
            "scope_note": self.scope_note,
            "minimum_support": self.minimum_support,
            "support_ablation_values": list(self.support_ablation_values),
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
    require_semantic_closure_for_l1: bool
    notes: Mapping[str, str] = field(default_factory=dict)

    def with_rules(self, extra: Iterable[EvidenceRule]) -> "EvidenceRuleBook":
        merged = list(self.rules) + list(extra)
        seen: set[str] = set()
        for rule in merged:
            if rule.rule_id in seen:
                raise EvidenceRuleError(f"duplicate rule id {rule.rule_id!r}")
            seen.add(rule.rule_id)
        return EvidenceRuleBook(
            version=self.version,
            policy_sha256=self.policy_sha256,
            derivation=self.derivation,
            rules=tuple(sorted(merged, key=lambda r: r.rule_id)),
            require_semantic_closure_for_l1=self.require_semantic_closure_for_l1,
            notes=self.notes,
        )

    def active_rules_for(self, predicate_uri: str, direction: str,
                         scope: str) -> tuple[EvidenceRule, ...]:
        """Active rules matching the key AND the scope, strongest tier first."""
        matched = [rule for rule in self.rules
                   if rule.is_active
                   and rule.predicate_uri == predicate_uri
                   and rule.direction == direction
                   and rule.scope == scope]
        # L2 before L1: the classifier must try to prove before it settles for a
        # scoped contrast, and the order here is what guarantees that.
        return tuple(sorted(matched, key=lambda r: (0 if r.is_l2 else 1,
                                                    r.rule_id)))

    def counts(self) -> dict:
        active = [r for r in self.rules if r.is_active]
        return {
            "total_rules": len(self.rules),
            "active_rules": len(active),
            "active_l1_rules": sum(1 for r in active if not r.is_l2),
            "active_l2_rules": sum(1 for r in active if r.is_l2),
            "proposed_not_active_rules": sum(
                1 for r in self.rules
                if r.activation_status == RULE_PROPOSED_NOT_ACTIVE),
            "inactive_rules": sum(1 for r in self.rules
                                  if r.activation_status == RULE_INACTIVE),
        }


def load_evidence_rules(path: str | Path,
                        *, require_semantic_closure_for_l1: bool = True
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
    derivation_raw = payload.get("empirical_single_valued_derivation", {})
    derivation = EmpiricalDerivationConfig(
        enabled=bool(derivation_raw.get("enabled", False)),
        scope_kind=str(derivation_raw.get("scope_kind", "")),
        scope_note=str(derivation_raw.get("scope_note", "")),
        minimum_support=int(derivation_raw.get("minimum_support", 5)),
        support_ablation_values=tuple(
            int(v) for v in derivation_raw.get("support_ablation_values", ())),
        maximum_observed_canonical_cardinality=int(
            derivation_raw.get("maximum_observed_canonical_cardinality", 1)),
        maximum_violations=int(derivation_raw.get("maximum_violations", 0)),
        active_directions=tuple(
            str(d) for d in derivation_raw.get("active_directions", ("OUT",))),
        inactive_direction_reason={
            str(k): str(v) for k, v
            in derivation_raw.get("inactive_direction_reason", {}).items()},
        empirical_label=str(derivation_raw.get("empirical_label", "")),
        version=version,
    )

    rules: list[EvidenceRule] = []
    for group, expected_types in (("l1_rules", L1_RULE_TYPES),
                                  ("l2_rules", L2_RULE_TYPES)):
        for entry in payload.get(group, ()):
            rule = _rule_from_record(entry, version)
            if rule.rule_type not in expected_types:
                raise EvidenceRuleError(
                    f"{path.name}: rule {rule.rule_id} appears under {group} but "
                    f"has rule_type {rule.rule_type!r}")
            rules.append(rule)

    return EvidenceRuleBook(
        version=version,
        policy_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        derivation=derivation,
        rules=tuple(sorted(rules, key=lambda r: r.rule_id)),
        require_semantic_closure_for_l1=require_semantic_closure_for_l1,
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
        resolves_granularity_risk=bool(entry.get("resolves_granularity_risk",
                                                 False)),
        ontology_source=str(entry.get("ontology_source", "")),
        exclusive_value_sets=tuple(
            tuple(normalize_uri(str(v)) for v in group)
            for group in entry.get("exclusive_value_sets", ())),
    )


# ==========================================================================
# 2) DERIVING EMPIRICAL SINGLE-VALUED RULES
# ==========================================================================

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
    over EVERY entity in the scope — the Answer and the complete ranked candidate
    pool. Cardinality is counted over CANONICAL objects, so a redirect pair is
    one value and not two; counting raw URIs would invent violations and suppress
    rules that the data does support.
    """
    cells: dict[tuple[str, str], list[int]] = {}
    for entity in sorted(observations):
        for key, objects in observations[entity].items():
            canonical = {semantic_index.canonical(uri) for uri in objects}
            if not canonical:
                continue
            cells.setdefault(key, []).append(len(canonical))

    entity_count = len(observations)
    rows = []
    for (predicate_uri, direction), cardinalities in sorted(cells.items()):
        rows.append(ScopeKeyObservation(
            scope=scope,
            predicate_uri=predicate_uri,
            direction=direction,
            support=len(cardinalities),
            maximum_cardinality=max(cardinalities),
            violation_count=sum(1 for c in cardinalities if c > 1),
            observed_entity_count=entity_count,
        ))
    return tuple(rows)


def derive_empirical_single_valued_rules(
    observations: Iterable[ScopeKeyObservation],
    *,
    config: EmpiricalDerivationConfig,
    rejected_predicates: Mapping[str, str] = {},
    minimum_support_override: Optional[int] = None,
) -> tuple[EvidenceRule, ...]:
    """One rule candidate per (scope, key), ACTIVE only when every gate passes.

    Every candidate is returned, including the ones that fail: an inactive rule
    with its reason is evidence about the data, and dropping it would leave the
    published support threshold unexaminable.
    """
    if not config.enabled:
        return ()
    minimum_support = (config.minimum_support if minimum_support_override is None
                       else minimum_support_override)

    derived: list[EvidenceRule] = []
    for row in sorted(observations, key=lambda r: (r.scope, r.predicate_uri,
                                                   r.direction)):
        local = row.predicate_uri.rsplit("/", 1)[-1]
        rule_id = (f"EMP_SV_{_scope_slug(row.scope)}_{row.direction}_{local}"
                   f"_MS{minimum_support}_V1")

        status = RULE_ACTIVE
        reason = ""
        if row.predicate_uri in rejected_predicates:
            status = RULE_INACTIVE
            reason = NOT_ACTIVE_PREDICATE_REJECTED
        elif row.direction not in config.active_directions:
            status = RULE_PROPOSED_NOT_ACTIVE
            reason = config.inactive_direction_reason.get(
                row.direction, NOT_ACTIVE_IN_DIRECTION)
        elif (row.maximum_cardinality
              > config.maximum_observed_canonical_cardinality
              or row.violation_count > config.maximum_violations):
            status = RULE_INACTIVE
            reason = NOT_ACTIVE_CARDINALITY_VIOLATION
        elif row.support < minimum_support:
            status = RULE_PROPOSED_NOT_ACTIVE
            reason = NOT_ACTIVE_INSUFFICIENT_SUPPORT

        derived.append(EvidenceRule(
            rule_id=rule_id,
            rule_type=RULE_TYPE_EMPIRICAL_SINGLE_VALUED,
            predicate_uri=row.predicate_uri,
            direction=row.direction,
            scope=row.scope,
            scope_kind=config.scope_kind,
            required_evidence=(
                f"observed_support >= {minimum_support}",
                (f"maximum_observed_canonical_cardinality <= "
                 f"{config.maximum_observed_canonical_cardinality}"),
                f"observed_violation_count <= {config.maximum_violations}",
                f"direction in {list(config.active_directions)}",
                "predicate not rejected by predicate_policy",
            ),
            minimum_support=minimum_support,
            observed_support=row.support,
            maximum_observed_cardinality=row.maximum_cardinality,
            observed_violation_count=row.violation_count,
            source=("derived from the frozen Prompt-8D observed facts for the "
                    "selected local class candidate pool"),
            provenance=config.scope_note,
            version=config.version,
            activation_status=status,
            inactive_reason=reason,
            empirical_label=config.empirical_label,
        ))
    return tuple(derived)


def _scope_slug(scope: str) -> str:
    """A short, stable, filesystem-safe fragment of a scope URI, for rule ids."""
    tail = scope.rsplit("Category:", 1)[-1].rsplit("/", 1)[-1]
    return "".join(c if c.isalnum() else "_" for c in tail) or "GLOBAL"


# ==========================================================================
# 3) THE CLASSIFIER
# ==========================================================================

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
    """level(f, d), the reason code, and everything behind both."""

    level: str
    reason_code: str
    proposition: RationaleProposition
    candidate_uri: str
    candidate_object_uris: tuple[str, ...]
    relations: tuple[CandidateObjectRelation, ...]
    granularity_risk: bool
    semantic_relation_available: bool
    applied_rule_id: str = ""
    applied_rule_type: str = ""
    proof: Optional[EvidenceProof] = None
    blocked_rule_ids: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        validate_l2_assignment(self.level, self.proof,
                               where=f"{self.candidate_uri}/{self.reason_code}")

    @property
    def covered_at_least(self) -> str:
        return self.level

    def as_record(self) -> dict:
        return {
            "candidate_uri": self.candidate_uri,
            "evidence_level": self.level,
            "reason_code": self.reason_code,
            "applied_rule_id": self.applied_rule_id,
            "applied_rule_type": self.applied_rule_type,
            "candidate_object_uris": list(self.candidate_object_uris),
            "candidate_object_count": len(self.candidate_object_uris),
            "semantic_relations": [r.as_record() for r in self.relations],
            "semantic_granularity_risk": self.granularity_risk,
            "semantic_relation_available": self.semantic_relation_available,
            "blocked_rule_ids": list(self.blocked_rule_ids),
            "evidence_proof": None if self.proof is None else self.proof.as_record(),
            "note": self.note,
            **self.proposition.as_record(),
        }


_SUPPORTING_REASON = {
    RELATION_EXACT_EQUAL: NOT_COVERED_EXACT_EQUAL,
    RELATION_CANONICALLY_EQUIVALENT: NOT_COVERED_CANONICALLY_EQUIVALENT,
    RELATION_CANDIDATE_UNDER_CLAIM: NOT_COVERED_SEMANTIC_ENTAILMENT,
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

      1. no observed object for the key   -> a closed-world-slot rule, or L0;
      2. any object SUPPORTS the claim    -> NOT_COVERED, before any rule runs;
      3. an active L2 rule proves exclusion -> L2 with an EvidenceProof;
      4. an active L1 rule applies        -> L1;
      5. otherwise                        -> L0, with the reason that applies.

    Granularity risk and semantic unavailability are collected in step 2 and
    consulted in steps 3-5, so a rule can never be applied to a case the semantic
    layer flagged without the rule saying it resolves that case.
    """
    claim = proposition.claim_object_uri
    objects = tuple(sorted({normalize_uri(uri) for uri in candidate_objects}))

    # --- 1) nothing observed for this key on this candidate -----------------
    if not objects:
        for rule in rulebook.active_rules_for(proposition.predicate_uri,
                                              proposition.direction, scope):
            if rule.rule_type == RULE_TYPE_SCOPED_CLOSED_WORLD_SLOT:
                return FactCandidateEvidence(
                    level=LEVEL_L1,
                    reason_code=L1_REASON_FOR_RULE_TYPE[rule.rule_type],
                    proposition=proposition, candidate_uri=candidate_uri,
                    candidate_object_uris=(), relations=(),
                    granularity_risk=False,
                    semantic_relation_available=semantic_index.available,
                    applied_rule_id=rule.rule_id, applied_rule_type=rule.rule_type,
                    note=("the scope is declared complete for this slot, so an "
                          "absent value is informative inside it"))
        return FactCandidateEvidence(
            level=LEVEL_L0, reason_code=L0_KEY_ABSENT, proposition=proposition,
            candidate_uri=candidate_uri, candidate_object_uris=(), relations=(),
            granularity_risk=False,
            semantic_relation_available=semantic_index.available,
            note=("the pinned snapshot records no value for this key on this "
                  "candidate; absence in one snapshot is an observation"))

    # --- 2) does any observed object SUPPORT the claim? ---------------------
    relations = tuple(
        CandidateObjectRelation(uri, semantic_index.classify(claim, uri))
        for uri in objects)

    for item in relations:
        reason = _SUPPORTING_REASON.get(item.relation.relation)
        if reason is not None:
            return FactCandidateEvidence(
                level=LEVEL_NOT_COVERED, reason_code=reason,
                proposition=proposition, candidate_uri=candidate_uri,
                candidate_object_uris=objects, relations=relations,
                granularity_risk=False,
                semantic_relation_available=semantic_index.available,
                note=("the candidate supports this proposition, so the fact "
                      "discriminates nothing here"))

    granularity_risk = any(
        item.relation.relation == RELATION_CLAIM_UNDER_CANDIDATE
        for item in relations)
    unavailable = any(item.relation.relation == RELATION_UNAVAILABLE
                      for item in relations)
    closure_ran = semantic_index.available and not unavailable

    # --- 3) and 4) rules ----------------------------------------------------
    blocked: list[str] = []
    for rule in rulebook.active_rules_for(proposition.predicate_uri,
                                          proposition.direction, scope):
        if rule.rule_type == RULE_TYPE_SCOPED_CLOSED_WORLD_SLOT:
            continue  # only meaningful when nothing is observed
        if granularity_risk and not rule.resolves_granularity_risk:
            blocked.append(rule.rule_id)
            continue
        if not rule.is_l2:
            if rulebook.require_semantic_closure_for_l1 and not closure_ran:
                blocked.append(rule.rule_id)
                continue
            if not _empirical_rule_holds(rule, objects):
                blocked.append(rule.rule_id)
                continue
            return FactCandidateEvidence(
                level=LEVEL_L1,
                reason_code=L1_REASON_FOR_RULE_TYPE[rule.rule_type],
                proposition=proposition, candidate_uri=candidate_uri,
                candidate_object_uris=objects, relations=relations,
                granularity_risk=granularity_risk,
                semantic_relation_available=closure_ran,
                applied_rule_id=rule.rule_id, applied_rule_type=rule.rule_type,
                note=(f"scoped contrast valid inside {rule.scope}; "
                      f"{rule.empirical_label or 'scoped, not universal'}"))
        proof = build_l2_proof(rule=rule, proposition=proposition,
                               candidate_uri=candidate_uri,
                               candidate_objects=objects, relations=relations,
                               closure_ran=closure_ran)
        if proof is None:
            blocked.append(rule.rule_id)
            continue
        return FactCandidateEvidence(
            level=LEVEL_L2, reason_code=L2_REASON_FOR_RULE_TYPE[rule.rule_type],
            proposition=proposition, candidate_uri=candidate_uri,
            candidate_object_uris=objects, relations=relations,
            granularity_risk=granularity_risk,
            semantic_relation_available=closure_ran,
            applied_rule_id=rule.rule_id, applied_rule_type=rule.rule_type,
            proof=proof, blocked_rule_ids=tuple(blocked))

    # --- 5) L0, with the reason that actually applies -----------------------
    if granularity_risk:
        reason = L0_GRANULARITY_RISK
        note = ("the claim object lies under a candidate object in the "
                "allowlisted hierarchy, so the candidate holds the more general "
                "statement and the apparent contrast is downgraded")
    elif not closure_ran:
        reason = L0_SEMANTIC_RELATION_UNKNOWN
        note = ("no semantic index was available for these objects, so a "
                "containment relation between them was never examined")
    else:
        reason = L0_DIFFERENT_OBJECTS_NONEXCLUSIVE
        note = ("the candidate has different observed objects for this key and "
                "no active rule makes the key exclusive in this scope")

    return FactCandidateEvidence(
        level=LEVEL_L0, reason_code=reason, proposition=proposition,
        candidate_uri=candidate_uri, candidate_object_uris=objects,
        relations=relations, granularity_risk=granularity_risk,
        semantic_relation_available=closure_ran,
        blocked_rule_ids=tuple(blocked), note=note)


def _empirical_rule_holds(rule: EvidenceRule, objects: Sequence[str]) -> bool:
    """Whether the candidate is consistent with the rule it is about to invoke.

    A rule derived as "at most one canonical object in this scope" may only be
    applied to a candidate that actually shows at most one. If the candidate
    shows two, the scope assumption has failed for this very entity and the rule
    must not be used on it — checking here rather than trusting the derivation
    keeps the two independent.
    """
    if rule.rule_type == RULE_TYPE_EMPIRICAL_SINGLE_VALUED:
        return len(set(objects)) <= rule.maximum_observed_cardinality
    return True


# ==========================================================================
# 4) L2 PROOFS
# ==========================================================================

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
    through to L1 or L0. Every premise is written into the proof, so a reader can
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
        if not candidate_objects:
            return None
        if not closure_ran:
            # Without the closure, "no parent-child support relation" is an
            # unchecked premise, and an exclusion proof may not rest on one.
            return None
        for item in relations:
            if item.relation.relation in (RELATION_EXACT_EQUAL,
                                          RELATION_CANONICALLY_EQUIVALENT,
                                          RELATION_CANDIDATE_UNDER_CLAIM,
                                          RELATION_CLAIM_UNDER_CANDIDATE):
                return None
        premises.append(
            f"the candidate {candidate_uri} is observed with "
            f"{sorted(candidate_objects)} for the same key")
        premises.append(
            "every observed candidate object is canonically distinct from the "
            "claim object and stands in no parent-child relation to it")
        conclusion = (
            f"under the declared cardinality constraint the candidate cannot "
            f"additionally hold {proposition.claim_object_uri} for this key")

    elif rule.rule_type == "EXPLICIT_NEGATIVE_PROPERTY_ASSERTION":
        premises.append(
            f"the source declares an explicit negative property assertion for "
            f"{candidate_uri} on this key and object")
        conclusion = (
            f"the source excludes {proposition.claim_object_uri} for "
            f"{candidate_uri} on this key")

    elif rule.rule_type == "FORMAL_DISJOINT_VALUE_CONFLICT":
        disjoint_hit = None
        for group in rule.exclusive_value_sets:
            members = set(group)
            if proposition.claim_object_uri in members:
                for obj in candidate_objects:
                    if obj in members and obj != proposition.claim_object_uri:
                        disjoint_hit = (proposition.claim_object_uri, obj)
                        break
            if disjoint_hit:
                break
        if disjoint_hit is None:
            return None
        premises.append(
            f"{disjoint_hit[0]} and {disjoint_hit[1]} are declared mutually "
            f"exclusive values for this key")
        conclusion = (
            f"the candidate's observed value {disjoint_hit[1]} excludes "
            f"{disjoint_hit[0]} for this key")

    elif rule.rule_type == "TEMPORALLY_SCOPED_EXCLUSIVE_CONFLICT":
        if proposition.qualifier_status == QUALIFIER_UNAVAILABLE:
            # No qualifiers in the source: temporal L2 is unreachable, by
            # construction and not by accident.
            return None
        if not proposition.qualifiers:
            return None
        premises.append(
            f"both statements carry normalized temporal qualifiers "
            f"{sorted(proposition.qualifiers)} over an overlapping interval")
        conclusion = (
            f"within the overlapping interval the candidate cannot hold "
            f"{proposition.claim_object_uri} for this key")
    else:
        return None

    return EvidenceProof(
        rule_id=rule.rule_id,
        rule_type=rule.rule_type,
        premises=tuple(premises),
        conclusion=conclusion,
        predicate_uri=proposition.predicate_uri,
        direction=proposition.direction,
        answer_object_uri=proposition.claim_object_uri,
        candidate_object_uris=tuple(sorted(candidate_objects)),
        qualifier_context=proposition.qualifier_status,
        ontology_source=rule.ontology_source,
        provenance=rule.provenance or rule.source,
    )
