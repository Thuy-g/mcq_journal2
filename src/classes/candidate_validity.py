############################################################################
# src/classes/candidate_validity.py
#
# CANDIDATE-LEVEL validity screening for Prompt 8H-B2-E, §7 and §8.
#
# TWO INDEPENDENT QUESTIONS, DELIBERATELY KEPT APART
# ---------------------------------------------------
#   §7  "is this candidate the same KIND of thing as the Answer?"
#       Mao Zedong's selected class was `Category:Maoist_China`, whose members
#       are `History_of_the_People's_Republic_of_China_(1949-1976)`,
#       `Mass_line`, `Laogai`, `Angang_Constitution` and `Anti-Rightist_
#       Campaign` - historical events, doctrines and institutions offered as
#       distractors for a PERSON.
#
#   §8  "does this candidate's NAME hand the learner the Answer?"
#       Muhammad's rank-2 distractor was `Muhammad_in_Islam`. It is a
#       person-shaped article - the pinned snapshot records birthPlace, father,
#       mother, office, predecessor, religion and title for it - so no type
#       test can reject it. Only its NAME is disqualifying.
#
# The two rules must not be merged. A type gate that also rejected topical
# derivatives would silently attribute one rejection to the other, and the
# 329-Answer delta audit could not attribute a yield change to either.
#
# WHY THE PINNED KG'S OWN `index_type` CANNOT BE USED
# ---------------------------------------------------
# Measured, not assumed: the pinned March-2023 pickle carries 6,672,610
# `index_type` entries and EVERY ONE of them is 0. `src/read_ttl.py` line 86
# initialises the map to 0 ("Others") and never updates it, and
# `treat_entity_type.entity_type_update()` - which would have filled it - needs
# live SPARQL and was never run for this dump. There is therefore no stored
# type to reuse, and this module says so rather than pretending otherwise.
#
# Nor is there an `rdf:type` triple to fall back on: the dump is
# infobox-properties only, and `rdf:type`, `dcterms:subject`, `skos:broader`,
# `gold:hypernym` and `dbo:wikiPageWikiLink` are all absent from its URI space.
#
# WHAT IS USED INSTEAD, AND WHAT IT CLAIMS
# -----------------------------------------
# The one type signal the pinned snapshot does carry is WHICH INFOBOX SLOTS an
# article fills. Human-biography templates fill kinship and life-event slots
# that essentially nothing else fills; `Mass_line` and `Laogai` fill no
# URI-valued slot at all. So the verdict is read off the observed
# (predicate, direction) KEY SET, with three states and no fourth:
#
#   PERSON      at least one STRONG person-biography key is observed;
#   NOT_PERSON  no person key, and at least one strong non-person key;
#   UNKNOWN     neither - the snapshot is silent about this entity's kind.
#
# UNKNOWN IS NOT PERSON. Under the strict policy an UNKNOWN candidate is
# refused, and the refusal is recorded as UNKNOWN rather than as NOT_PERSON,
# because "the snapshot records nothing" and "the snapshot records something
# incompatible" are different observations - the same open-world discipline the
# L0/L1 distinction rests on.
#
# NOTHING HERE IS A CLAIM ABOUT DBPEDIA OR THE WORLD. It is a claim about which
# slots one snapshot filled, and every verdict carries the keys that produced
# it so a reviewer can overrule it by inspection.
#
# NO MODELS, NO NETWORK, NO ENTITY-SPECIFIC BRANCH. Set membership and token
# comparison only; `grep -i muhammad` over this file finds prose only.
#
# WHAT PROMPT 8H-B2-G ADDED (2026-09-18), AND WHAT IT DID NOT CHANGE
# -------------------------------------------------------------------
#   * a THIRD type policy, `PERSON_GUARDED`, which refuses a confirmed
#     NOT_PERSON and the §8 name rule but KEEPS an UNKNOWN candidate;
#   * explicit DETECTION fields on every verdict, so a run can report that a
#     detector fired while the active policy removed nothing.
# `OBSERVE_ONLY` and `PERSON_STRICT` behave exactly as before, field for field;
# the two added properties are derived, not stored, and no default moved.
#
# IMPORT-TIME PURITY: no I/O, no network, no policy file read at import.
############################################################################

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

from rationale_v3.quality import QualityPolicy, leakage_tokens

__all__ = [
    "CANDIDATE_VALIDITY_POLICY_VERSION",
    "TYPE_PERSON",
    "TYPE_NOT_PERSON",
    "TYPE_UNKNOWN",
    "TYPE_POLICY_OBSERVE_ONLY",
    "TYPE_POLICY_PERSON_GUARDED",
    "TYPE_POLICY_PERSON_STRICT",
    "TYPE_POLICIES",
    "REJECT_NONE",
    "REJECT_TYPE_NOT_PERSON",
    "REJECT_TYPE_UNKNOWN",
    "REJECT_ANSWER_NAME_CONTAINED",
    "PERSON_EVIDENCE_KEYS",
    "NON_PERSON_EVIDENCE_KEYS",
    "CandidateValidityPolicy",
    "DEFAULT_CANDIDATE_VALIDITY_POLICY",
    "PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY",
    "PERSON_STRICT_CANDIDATE_VALIDITY_POLICY",
    "REJECTED_BY_NOTHING",
    "REJECTED_BY_TYPE_RULE",
    "REJECTED_BY_NAME_RULE",
    "EntityTypeVerdict",
    "CandidateValidityVerdict",
    "classify_entity_type",
    "answer_name_containment",
    "screen_candidate",
]

CANDIDATE_VALIDITY_POLICY_VERSION = "candidate_validity/1.0.0"

P = "http://dbpedia.org/property/"

TYPE_PERSON = "PERSON"
TYPE_NOT_PERSON = "NOT_PERSON"
TYPE_UNKNOWN = "UNKNOWN_TYPE_NOT_RECORDED_IN_PINNED_SNAPSHOT"

#: The THREE declared candidate-type policies. OBSERVE_ONLY computes and
#: publishes every verdict and rejects nothing; it is the DEFAULT, because §7.5
#: forbids applying a same-type rule to the chemistry cohorts before its effect
#: has been measured. PERSON_STRICT refuses both NOT_PERSON and UNKNOWN.
#: PERSON_GUARDED — added by Prompt 8H-B2-G §2 — sits between them.
#:
#: WHY PERSON_GUARDED EXISTS AND WHY IT KEEPS UNKNOWN
#: ---------------------------------------------------
#: `UNKNOWN` means the PINNED SNAPSHOT filled none of the listed slots for that
#: article. It does NOT mean the entity is known not to be a person. Under the
#: open-world discipline this project applies to L0 (`docs/context/
#: EVIDENCE_TAXONOMY_V1.md` §2), absence of a recorded slot is a statement about
#: coverage, not about the world — and the measured cost of reading it as a
#: refusal is large: the B2-E/B2-F simulation refused roughly one candidate row
#: in six on UNKNOWN alone and pushed dozens of candidate pools below the
#: local-mapping gate. PERSON_GUARDED therefore refuses only what the snapshot
#: POSITIVELY contradicts (a confirmed NOT_PERSON slot profile) plus the §8 name
#: rule, and leaves UNKNOWN in the pool.
#:
#: Which of the three becomes the publication default is NOT decided here. All
#: three are shipped, all three are measured, and the choice is the researcher's.
TYPE_POLICY_OBSERVE_ONLY = "OBSERVE_ONLY"
TYPE_POLICY_PERSON_GUARDED = "PERSON_GUARDED"
TYPE_POLICY_PERSON_STRICT = "PERSON_STRICT"
TYPE_POLICIES = (TYPE_POLICY_OBSERVE_ONLY, TYPE_POLICY_PERSON_GUARDED,
                 TYPE_POLICY_PERSON_STRICT)

REJECT_NONE = ""
REJECT_TYPE_NOT_PERSON = "CANDIDATE_TYPE_NOT_PERSON"
REJECT_TYPE_UNKNOWN = "CANDIDATE_TYPE_UNKNOWN_UNDER_PERSON_STRICT_POLICY"
REJECT_ANSWER_NAME_CONTAINED = "CANDIDATE_NAME_CONTAINS_THE_COMPLETE_ANSWER_NAME"

#: WHICH RULE actually removed a candidate, kept apart from WHICH DETECTOR
#: FIRED. Prompt 8H-B2-G §3: the 329-Answer metric
#: `candidate_topical_identity_leak_rejections` reported zero under an
#: observe-only run even though the name detector had fired 17 times, because
#: the metric counted REJECTIONS and the policy rejected nothing. Detection and
#: rejection are two different measurements and every verdict now carries both.
REJECTED_BY_NOTHING = "NONE"
REJECTED_BY_TYPE_RULE = "TYPE_RULE"
REJECTED_BY_NAME_RULE = "NAME_RULE"

#: STRONG person-biography slots. Every one of them is a kinship relation, a
#: life-event place, an education/appointment relation or a scholarly-lineage
#: relation, i.e. a slot that a human-biography infobox fills and that a
#: doctrine, an event, a chemical or a publication does not. Literal-valued
#: slots such as birthDate are deliberately absent: the pinned pickle keeps only
#: URI-valued edges, so a literal slot is invisible here and listing it would
#: suggest a signal that can never fire.
PERSON_EVIDENCE_KEYS: frozenset = frozenset({
    (P + "academicAdvisors", "OUT"),
    (P + "almaMater", "OUT"),
    (P + "burialPlace", "OUT"),
    (P + "children", "OUT"),
    (P + "citizenship", "OUT"),
    (P + "deathPlace", "OUT"),
    (P + "doctoralAdvisor", "OUT"),
    (P + "doctoralStudents", "OUT"),
    (P + "education", "OUT"),
    (P + "father", "OUT"),
    (P + "mainInterests", "OUT"),
    (P + "mother", "OUT"),
    (P + "nationality", "OUT"),
    (P + "notableStudents", "OUT"),
    (P + "occupation", "OUT"),
    (P + "parents", "OUT"),
    (P + "relatives", "OUT"),
    (P + "restingPlace", "OUT"),
    (P + "schoolTradition", "OUT"),
    (P + "spouse", "OUT"),
    (P + "workInstitution", "OUT"),
    (P + "workInstitutions", "OUT"),
    (P + "workplaces", "OUT"),
    # `birthPlace` is listed last on purpose: it is the one slot below that a
    # small number of non-person articles (an organisation's founding place, a
    # fictional character) also fill. It stays in because removing it loses
    # every pre-modern ruler whose article fills nothing else, and because a
    # false PERSON here is corrected by §8's name rule and by the reviewer, not
    # silently acted on.
    (P + "birthPlace", "OUT"),
})

#: STRONG non-person slots: a subject that fills one of these is a work, a
#: product, an organisation, an event or a substance. Consulted ONLY when no
#: person key is present, so an author who is also somebody's subject is never
#: reclassified.
NON_PERSON_EVIDENCE_KEYS: frozenset = frozenset({
    (P + "author", "OUT"),
    (P + "casualties", "OUT"),
    (P + "chemicalFormula", "OUT"),
    (P + "composition", "OUT"),
    (P + "formula", "OUT"),
    (P + "founder", "OUT"),
    (P + "genre", "OUT"),
    (P + "headquarters", "OUT"),
    (P + "industry", "OUT"),
    (P + "manufacturer", "OUT"),
    (P + "perpetrators", "OUT"),
    (P + "products", "OUT"),
    (P + "publisher", "OUT"),
})


@dataclass(frozen=True)
class CandidateValidityPolicy:
    """The complete, explicit configuration of both screens.

    A dataclass rather than module constants read directly, so a test can move
    ONE knob without monkeypatching module state and so a run manifest can
    record the effective configuration verbatim (§7.6).
    """

    type_policy: str = TYPE_POLICY_OBSERVE_ONLY
    person_evidence_keys: frozenset = PERSON_EVIDENCE_KEYS
    non_person_evidence_keys: frozenset = NON_PERSON_EVIDENCE_KEYS
    #: §8. Off by default until its corpus-wide delta has been reviewed.
    reject_answer_name_containment: bool = False
    version: str = CANDIDATE_VALIDITY_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.type_policy not in TYPE_POLICIES:
            raise ValueError(
                f"unknown candidate type policy {self.type_policy!r}; "
                f"expected one of {TYPE_POLICIES}")

    @property
    def rejects_on_type(self) -> bool:
        """True when the type axis may remove a candidate at all.

        Both PERSON_GUARDED and PERSON_STRICT act on the type axis; they differ
        only in what they do with UNKNOWN (see `rejects_unknown_type`).
        """
        return self.type_policy in (TYPE_POLICY_PERSON_GUARDED,
                                    TYPE_POLICY_PERSON_STRICT)

    @property
    def rejects_unknown_type(self) -> bool:
        """True ONLY under PERSON_STRICT.

        PERSON_GUARDED deliberately retains an UNKNOWN candidate: the snapshot
        recording no person slot is an observation about coverage, not evidence
        that the entity is not a person. Refusing it would read absence as
        falsity — the single mistake the whole L0/L1 taxonomy exists to prevent.
        """
        return self.type_policy == TYPE_POLICY_PERSON_STRICT

    def as_record(self) -> dict:
        return {
            "candidate_validity_policy_version": self.version,
            "candidate_type_policy": self.type_policy,
            "candidate_type_policy_rejects": self.rejects_on_type,
            "candidate_type_policy_rejects_unknown": self.rejects_unknown_type,
            "person_evidence_key_count": len(self.person_evidence_keys),
            "non_person_evidence_key_count": len(self.non_person_evidence_keys),
            "reject_answer_name_containment": self.reject_answer_name_containment,
            "type_source": ("OBSERVED_INFOBOX_SLOT_PROFILE_IN_PINNED_SNAPSHOT "
                            "(the pinned pickle's index_type map is uniformly 0 "
                            "and carries no type information)"),
        }


DEFAULT_CANDIDATE_VALIDITY_POLICY = CandidateValidityPolicy()

#: Prompt 8H-B2-G §2. Refuses a CONFIRMED NOT_PERSON and the §8 name rule, and
#: keeps UNKNOWN. Offered and measured; NOT declared the publication default.
PERSON_GUARDED_CANDIDATE_VALIDITY_POLICY = CandidateValidityPolicy(
    type_policy=TYPE_POLICY_PERSON_GUARDED,
    reject_answer_name_containment=True,
)

#: The strictest configuration a PERSON main benchmark could declare.
PERSON_STRICT_CANDIDATE_VALIDITY_POLICY = CandidateValidityPolicy(
    type_policy=TYPE_POLICY_PERSON_STRICT,
    reject_answer_name_containment=True,
)


@dataclass(frozen=True)
class EntityTypeVerdict:
    """One entity's observed-slot type verdict, with the slots behind it."""

    entity_uri: str
    entity_type: str
    person_evidence_keys: tuple[str, ...]
    non_person_evidence_keys: tuple[str, ...]
    observed_key_count: int
    policy_version: str

    @property
    def is_person(self) -> bool:
        return self.entity_type == TYPE_PERSON

    def as_record(self) -> dict:
        return {
            "entity_uri": self.entity_uri,
            "entity_type": self.entity_type,
            "person_evidence_keys": list(self.person_evidence_keys),
            "non_person_evidence_keys": list(self.non_person_evidence_keys),
            "observed_key_count": self.observed_key_count,
            "candidate_validity_policy_version": self.policy_version,
        }


def classify_entity_type(
    entity_uri: str,
    observed_keys: Iterable[tuple[str, str]],
    *,
    policy: CandidateValidityPolicy = DEFAULT_CANDIDATE_VALIDITY_POLICY,
) -> EntityTypeVerdict:
    """PERSON / NOT_PERSON / UNKNOWN from the observed predicate-direction keys.

    ``observed_keys`` is the set of ``(predicate_uri, direction)`` pairs the
    pinned snapshot records for the entity — exactly the keys of
    ``mcq_inputs.candidate_objects_from_local_kg()``, so the type verdict and the
    evidence classification read the same observation.

    Precedence is person-first and is not a preference: a person key is a
    positive biographical observation, whereas a non-person key can appear on a
    person's article through an unusual template. An entity with both is a
    PERSON whose article also fills a work slot, and saying so is more accurate
    than declaring a conflict.
    """
    keys = {(str(p), str(d)) for p, d in observed_keys}
    person = tuple(sorted(f"{p}|{d}" for p, d in keys
                          & policy.person_evidence_keys))
    other = tuple(sorted(f"{p}|{d}" for p, d in keys
                         & policy.non_person_evidence_keys))
    if person:
        entity_type = TYPE_PERSON
    elif other:
        entity_type = TYPE_NOT_PERSON
    else:
        entity_type = TYPE_UNKNOWN
    return EntityTypeVerdict(
        entity_uri=entity_uri, entity_type=entity_type,
        person_evidence_keys=person, non_person_evidence_keys=other,
        observed_key_count=len(keys), policy_version=policy.version)


def _name_tokens(uri: str, policy: QualityPolicy) -> tuple[str, ...]:
    """The ORDERED token sequence of a URI's local name.

    ``leakage_tokens`` at minimum length 1 — the full sequence, nothing dropped
    — because §8's condition is about the Answer's COMPLETE name appearing
    inside the candidate's name, and dropping a short token would let
    ``Sun_Yat-sen`` match ``Yat-sen_Memorial`` on a fragment.
    """
    return leakage_tokens(uri, minimum_length=1)


def answer_name_containment(answer_uri: str, candidate_uri: str,
                            policy: QualityPolicy) -> Optional[str]:
    """§8: does the candidate's name CONTAIN the Answer's complete name?

    The condition is deliberately the strongest one that still catches
    ``Muhammad`` / ``Muhammad_in_Islam``:

      * the candidate's ordered token sequence contains the Answer's ordered
        token sequence as a CONTIGUOUS run, and
      * the candidate has strictly more tokens, so the two names are not simply
        the same name.

    ANY-TOKEN OVERLAP IS NOT ENOUGH, and that is the whole point. ``Ashikaga
    Takauji`` and ``Ashikaga Yoshiakira`` share the family name ``ashikaga`` but
    neither contains the other's complete two-token name, so both survive — they
    are distinct historical persons and §7.7 requires them to stay eligible.
    ``Muhammad`` is a one-token name that appears complete and contiguous inside
    ``Muhammad in Islam``, so that pair is caught.

    Returns a human-readable evidence string, or ``None`` when the rule does not
    fire. It never returns a verdict on its own: the caller decides whether the
    active policy acts on it.
    """
    answer = _name_tokens(answer_uri, policy)
    candidate = _name_tokens(candidate_uri, policy)
    if not answer or len(candidate) <= len(answer):
        return None
    span = len(answer)
    for start in range(len(candidate) - span + 1):
        if tuple(candidate[start:start + span]) == tuple(answer):
            return (f"candidate name tokens {list(candidate)} contain the "
                    f"complete Answer name {list(answer)} contiguously at "
                    f"position {start}")
    return None


@dataclass(frozen=True)
class CandidateValidityVerdict:
    """One candidate's complete screening result, accepted or not.

    DETECTION AND REJECTION ARE TWO DIFFERENT FACTS (Prompt 8H-B2-G §3).

    * `type_verdict.entity_type` and `name_containment_evidence` are what the
      DETECTORS observed. They are computed for every candidate under EVERY
      policy, including OBSERVE_ONLY, and never depend on what the policy does.
    * `reject_reason` and `rejected_by_rule` are what the ACTIVE POLICY did.
      Under OBSERVE_ONLY they are always "nothing", however loudly a detector
      fired.

    A metric that reads only the second pair reports zero detections under an
    observe-only run, which is how the 329-Answer report came to publish
    `candidate_topical_identity_leak_rejections = 0` while the name detector had
    in fact fired seventeen times.
    """

    candidate_uri: str
    answer_uri: str
    accepted: bool
    reject_reason: str
    type_verdict: EntityTypeVerdict
    name_containment_evidence: str
    policy_version: str
    type_policy: str

    @property
    def name_containment_detected(self) -> bool:
        """Did the §8 detector fire? Independent of whether anything acted."""
        return bool(self.name_containment_evidence)

    @property
    def detected_entity_type(self) -> str:
        """PERSON / NOT_PERSON / UNKNOWN — the observation, not a decision."""
        return self.type_verdict.entity_type

    @property
    def rejected_by_rule(self) -> str:
        """WHICH rule removed this candidate: NONE, TYPE_RULE or NAME_RULE.

        Attribution is exact rather than inferred from the detectors: a
        candidate may be both a NOT_PERSON and a name-containment case, and the
        delta audit must be able to say which gate actually removed it.
        """
        if not self.reject_reason:
            return REJECTED_BY_NOTHING
        if self.reject_reason == REJECT_ANSWER_NAME_CONTAINED:
            return REJECTED_BY_NAME_RULE
        return REJECTED_BY_TYPE_RULE

    def as_record(self) -> dict:
        return {
            "candidate_uri": self.candidate_uri,
            "answer_uri": self.answer_uri,
            "accepted": self.accepted,
            "reject_reason": self.reject_reason or "ACCEPTED",
            "rejected_by_rule": self.rejected_by_rule,
            "name_containment_detected": self.name_containment_detected,
            "name_containment_evidence": self.name_containment_evidence,
            "candidate_type_policy": self.type_policy,
            **self.type_verdict.as_record(),
        }


def screen_candidate(
    *,
    answer_uri: str,
    candidate_uri: str,
    observed_keys: Iterable[tuple[str, str]],
    quality_policy: QualityPolicy,
    answer_type: Optional[EntityTypeVerdict] = None,
    policy: CandidateValidityPolicy = DEFAULT_CANDIDATE_VALIDITY_POLICY,
) -> CandidateValidityVerdict:
    """Both screens for one candidate, in a fixed, reportable order.

    §7 first, then §8, because a candidate rejected for being the wrong kind of
    thing should say so rather than reporting a name coincidence. Both verdicts
    are computed either way, so the delta audit can attribute every rejection.

    ``answer_type`` is the Answer's own verdict. The type gate applies only when
    the Answer itself is RELIABLY typed a person (§7.1): refusing candidates for
    not matching a type the Answer does not demonstrably have would be a gate
    with no premise. When the Answer is UNKNOWN the type screen stands down and
    every candidate is accepted on that axis, which is recorded in the verdict.

    THE THREE POLICIES, on the type axis only:

        OBSERVE_ONLY     nothing is removed; both verdicts are still published.
        PERSON_GUARDED   a CONFIRMED NOT_PERSON is removed; UNKNOWN is kept.
        PERSON_STRICT    NOT_PERSON and UNKNOWN are both removed.

    All three compute exactly the same detector output, so a delta audit can
    compare them row by row.
    """
    type_verdict = classify_entity_type(candidate_uri, observed_keys,
                                        policy=policy)
    containment = answer_name_containment(answer_uri, candidate_uri,
                                          quality_policy) or ""

    reason = REJECT_NONE
    answer_is_person = answer_type is not None and answer_type.is_person
    if policy.rejects_on_type and answer_is_person:
        if type_verdict.entity_type == TYPE_NOT_PERSON:
            reason = REJECT_TYPE_NOT_PERSON
        elif (type_verdict.entity_type == TYPE_UNKNOWN
                and policy.rejects_unknown_type):
            # PERSON_GUARDED stops here on purpose: an UNKNOWN candidate is one
            # the snapshot is SILENT about, and silence is not a contradiction.
            reason = REJECT_TYPE_UNKNOWN
    if not reason and policy.reject_answer_name_containment and containment:
        reason = REJECT_ANSWER_NAME_CONTAINED

    return CandidateValidityVerdict(
        candidate_uri=candidate_uri, answer_uri=answer_uri,
        accepted=not reason, reject_reason=reason, type_verdict=type_verdict,
        name_containment_evidence=containment, policy_version=policy.version,
        type_policy=policy.type_policy)
