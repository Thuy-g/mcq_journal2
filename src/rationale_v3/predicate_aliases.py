############################################################################
# src/rationale_v3/predicate_aliases.py
#
# PREDICATE-SLOT ALIASES for evidence matching — Prompt 8H-B2-G §5.
#
# THE DEFECT THIS REPAIRS
# ------------------------
# Evidence is decided against a predicate-direction key `κ = (predicate, dir)`
# and the comparison is EXACT STRING EQUALITY of the predicate URI. DBpedia's
# infobox namespace is not a curated ontology: it contains whatever slot name an
# editor typed, so the SAME relation appears under several spellings. Measured
# on the pinned March-2023 snapshot:
#
#     Robert Boyle   dbp:fields -> dbr:Physics , dbr:Chemistry , ...
#     Joseph Black   dbp:field  -> dbr:Chemistry , dbr:Physics , ...
#
# Under exact keying `(dbp:fields, OUT)` and `(dbp:field, OUT)` are different
# keys, so Joseph Black records NOTHING under Boyle's key and the pair is
# classified `L0_ABSENCE_ONLY_OBSERVED` — "the snapshot records no field for
# Joseph Black" — when the snapshot in fact records the SAME VALUE under the
# singular spelling. That is not a weak observation, it is a FALSE one, and it
# is the single failure mode this module exists to prevent.
#
# WHAT THE REPAIR IS, EXACTLY
# ----------------------------
# For EVIDENCE LOOKUP ONLY, a candidate's observed objects are unioned across
# the members of an explicitly audited ALIAS FAMILY, within the same direction.
# Nothing else changes:
#
#   * the Answer fact keeps its own raw predicate URI and its own provenance —
#     a rationale still says `dbp:fields`, because that is what the snapshot
#     records for the Answer;
#   * the pinned KG is not rewritten, no triple is added, no triple is removed;
#   * IN and OUT stay separate keys, always;
#   * `(p, IN)` aliases only with `(q, IN)`;
#   * the union happens BEFORE `classify_fact_against_candidate()`, so an exact
#     object match under an alias reaches the `NOT_COVERED` branch — the
#     candidate SUPPORTS the proposition — and can never be re-read as L0 or L1.
#
# WHY THIS IS NOT "SINGULARISE EVERY DBPEDIA PREDICATE"
# ------------------------------------------------------
# A blanket morphological rule would be a guess about hundreds of predicates
# nobody has looked at. `dbp:children` is not `dbp:child`-with-an-s in any
# useful sense; `dbp:products` and `dbp:product` may or may not be the same
# slot; `dbp:workplaces` / `dbp:workInstitutions` / `dbp:workInstitution` LOOK
# related and their extensions have to be MEASURED before they are merged. So
# this module ships exactly ONE audited family and a hard refusal to grow by
# inference: a family enters `DEFAULT_ALIAS_POLICY` only after a corpus-wide
# census is recorded in the task's evidence package.
#
# WHY A MERGE CAN ONLY EVER WEAKEN A DISTINCTION, NEVER INVENT ONE
# ------------------------------------------------------------------
# Unioning enlarges `O_d(κ)`. Enlarging it can move a pair
# L0 -> L1 (something is now observed), L0 -> NOT_COVERED or L1 -> NOT_COVERED
# (the claim is now supported). It can NEVER move a pair towards a stronger
# discrimination, and it can never create an exclusion. So the operation is
# safe in the open-world direction: it can only remove a distinction the
# snapshot did not really support. That asymmetry is why aliasing is applied to
# the CANDIDATE's observed set and never used to add facts to the Answer.
#
# IMPORT-TIME PURITY: no I/O, no network, no policy file read at import.
############################################################################

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

__all__ = [
    "PREDICATE_ALIAS_POLICY_VERSION",
    "AliasFamily",
    "PredicateAliasPolicy",
    "NO_ALIAS_POLICY",
    "FIELD_ALIAS_FAMILY",
    "DEFAULT_ALIAS_POLICY",
    "AUDITED_CANDIDATE_FAMILIES",
    "observed_objects_for_key",
]

PREDICATE_ALIAS_POLICY_VERSION = "predicate_slot_alias/1.0.0-field-family"

P = "http://dbpedia.org/property/"


@dataclass(frozen=True)
class AliasFamily:
    """One audited group of predicate URIs that denote the SAME infobox slot.

    ``canonical_slot`` is a NAME for the group, used in reports and manifests.
    It is deliberately not itself a predicate URI that gets written anywhere:
    no triple is ever rewritten to it, and no rationale ever prints it.

    ``members`` is the complete set of raw predicate URIs in the family. A
    family of fewer than two members would be a no-op and is refused, because a
    one-member "family" in a policy file is almost always a typo.

    ``evidence`` records WHY the family was declared — the corpus measurement
    that justified it. It is required: an alias family without a recorded
    measurement is exactly the unaudited guess this module forbids.
    """

    canonical_slot: str
    members: frozenset
    evidence: str

    def __post_init__(self) -> None:
        if len(self.members) < 2:
            raise ValueError(
                f"alias family {self.canonical_slot!r} has "
                f"{len(self.members)} member(s); a family must group at least "
                f"two distinct predicate URIs or it changes nothing")
        if not str(self.evidence).strip():
            raise ValueError(
                f"alias family {self.canonical_slot!r} carries no evidence "
                f"string; an unaudited alias family is not admissible")

    def as_record(self) -> dict:
        return {
            "canonical_slot": self.canonical_slot,
            "members": sorted(self.members),
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class PredicateAliasPolicy:
    """The complete, versioned set of alias families a run applies.

    An EMPTY policy is the historical behaviour: exact key lookup, nothing
    unioned. It is the default everywhere, so no existing caller changes.
    """

    families: tuple[AliasFamily, ...] = ()
    version: str = PREDICATE_ALIAS_POLICY_VERSION

    def __post_init__(self) -> None:
        seen: dict[str, str] = {}
        for family in self.families:
            for member in family.members:
                if member in seen and seen[member] != family.canonical_slot:
                    raise ValueError(
                        f"predicate {member} appears in two alias families "
                        f"({seen[member]!r} and {family.canonical_slot!r}); "
                        f"a predicate belongs to at most one slot")
                seen[member] = family.canonical_slot

    @property
    def enabled(self) -> bool:
        return bool(self.families)

    def family_for(self, predicate_uri: str) -> Optional[AliasFamily]:
        """The family this predicate belongs to, or None. Exact URI match only."""
        for family in self.families:
            if predicate_uri in family.members:
                return family
        return None

    def keys_for(self, key: tuple[str, str]) -> tuple[tuple[str, str], ...]:
        """Every (predicate, direction) key that feeds this key's object set.

        The supplied key is ALWAYS first, so a caller that only reads the head
        of the tuple still sees the raw key. The direction is carried unchanged
        onto every alias: `(dbp:field, IN)` never contributes to
        `(dbp:fields, OUT)`, because IN and OUT are different relations with
        different extensions and different verbalizations.
        """
        predicate, direction = key
        family = self.family_for(predicate)
        if family is None:
            return (key,)
        others = sorted(m for m in family.members if m != predicate)
        return (key,) + tuple((member, direction) for member in others)

    def as_record(self) -> dict:
        return {
            "predicate_alias_policy_version": self.version,
            "enabled": self.enabled,
            "family_count": len(self.families),
            "families": [f.as_record() for f in self.families],
            "note": ("Aliases are applied to the CANDIDATE's observed object "
                     "set for evidence lookup only. Raw predicates, raw "
                     "provenance and the pinned KG are unchanged, and IN/OUT "
                     "are never merged."),
        }


#: The empty policy: exact key lookup, byte-identical to every run before
#: Prompt 8H-B2-G. It is the DEFAULT of every function that takes a policy.
NO_ALIAS_POLICY = PredicateAliasPolicy(
    families=(), version="predicate_slot_alias/0-exact-keys-only")


#: The ONE audited family. `dbp:field` and `dbp:fields` are the singular and
#: plural spellings of the academic-discipline slot of the scientist/academic
#: infobox; the census in the task's evidence package records how many subjects
#: use each spelling, how many use both, and the object-vocabulary overlap
#: between them.
FIELD_ALIAS_FAMILY = AliasFamily(
    canonical_slot="academic_field",
    members=frozenset({P + "field", P + "fields"}),
    evidence=("pinned-KG census, Prompt 8H-B2-G §5: dbp:field and dbp:fields "
              "are the singular/plural spellings of the same academic-"
              "discipline infobox slot; their OUT object vocabularies are "
              "drawn from the same discipline entities and the pair "
              "Robert_Boyle(fields) / Joseph_Black(field) records the SAME "
              "objects under the two spellings. See "
              "outputs/.../predicate_alias_audit.md"),
)

#: The policy the Prompt 8H-B2-G v4 candidate configuration declares.
DEFAULT_ALIAS_POLICY = PredicateAliasPolicy(families=(FIELD_ALIAS_FAMILY,))

#: Families that were LOOKED AT and are NOT admitted. Kept in the source so the
#: refusal is inspectable and so a future task does not re-guess them. Each must
#: be measured corpus-wide before it may move into `DEFAULT_ALIAS_POLICY`; the
#: string is the reason it is still out.
AUDITED_CANDIDATE_FAMILIES: Mapping[str, str] = {
    "workplace_family": (
        "dbp:workplaces / dbp:workInstitution / dbp:workInstitutions / "
        "dbp:workplace — NOT ADMITTED. Prompt 8H-B2-G §5 explicitly refuses to "
        "assume equivalence from string similarity. The census in this task's "
        "evidence package reports their subject counts and object overlap; "
        "admitting them is a separate, measured decision."),
}


def observed_objects_for_key(
    observed: Mapping[tuple[str, str], Sequence[str]],
    key: tuple[str, str],
    *,
    policy: PredicateAliasPolicy = NO_ALIAS_POLICY,
) -> tuple[str, ...]:
    """``O_d(κ)`` for one candidate, unioned over the key's audited alias family.

    ``observed`` is the RAW per-candidate map produced by
    ``mcq_inputs.candidate_objects_from_local_kg()`` — raw predicate URIs, raw
    directions, nothing rewritten. This function reads it; it never mutates it.

    With ``NO_ALIAS_POLICY`` the result is exactly ``observed.get(key, ())``,
    which is what every caller before Prompt 8H-B2-G did, so the default path is
    unchanged down to the tuple identity of the common case.

    The returned objects are sorted and deduplicated so that the classifier sees
    a deterministic set regardless of which alias contributed which object.
    """
    keys = policy.keys_for(key)
    if len(keys) == 1:
        # The overwhelmingly common path. Returned unchanged, not re-sorted:
        # `candidate_objects_from_local_kg()` already sorts, and re-sorting here
        # would hide a caller that passed something else.
        return tuple(observed.get(key, ()))
    merged: set[str] = set()
    for alias_key in keys:
        merged.update(observed.get(alias_key, ()))
    return tuple(sorted(merged))
