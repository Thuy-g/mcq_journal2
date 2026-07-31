############################################################################
# src/selection/contracts.py
#
# The ranker-facing contract shared by the proposed Journal-2 pilot path and the
# retained legacy baseline.
#
# WHY A CONTRACT AT ALL
#   Before this module, src/extract_221_and_select_distractors_ClaudeWeb_v2.py
#   owned candidate retrieval, OverlapStrict/OverlapLoose scoring, an MMR-like
#   selection step and rationale logic in one file, so "the ranker" was not a
#   thing that could be named, swapped or compared. AUDIT_Journal2_v2_2026-07-26
#   item EX-2 records the consequence: LRoleSim was absent from the distractor
#   pipeline entirely, and nothing in the code made that visible.
#
#   Making the ranker an explicit interface means the proposed method and the
#   baseline are two named implementations of one contract, so a report can never
#   quietly present one as the other.
#
# THE TWO RANKERS
#   lrolesim_m1_fixed_k3    the PROPOSED Journal-2 pilot path. Structural
#                           plausibility from LRoleSim L_ed, lrolesim_beta 0.2,
#                           exactly three iterations, over the frozen M1 graphs.
#   legacy_overlap_baseline the RETAINED baseline. OverlapStrict/OverlapLoose plus
#                           the old MMR-like step. Kept because a baseline is
#                           needed for a future comparison, never because it is
#                           the method being proposed.
#
#   A ranker name is data in every output record, so "which ranker produced this"
#   is answerable from the artefact alone.
#
# WHAT A RANKING IS NOT
#   A CandidateRanking is a STRUCTURAL PLAUSIBILITY ORDER over retained
#   candidates. It is not a distractor set: rationale feasibility has not been
#   applied, so no element of it may be called a final distractor. Every
#   provisional record therefore carries is_final_distractor = False, and the
#   handoff carries RATIONALE_SELECTION_DEFERRED_TO_PROMPT_8E.
#
# NAMING NOTE — `lrolesim_beta`, never bare `beta`
#   This project has TWO quantities called beta: the LRoleSim decay factor, and
#   OverlapLoose's weight in OverlapScore (ALPHA/BETA in the legacy extractor).
#   src/lrolesim/adapter.py actively REFUSES a keyword called `beta` for exactly
#   this reason. Since these records travel alongside legacy-overlap records, the
#   unqualified name is the one mistake this schema must not make, so the field is
#   `lrolesim_beta` throughout.
#
# Offline and pure: dataclasses, validation and sorting only. No I/O, no network,
# no KG access, no ranking mathematics.
############################################################################

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence, runtime_checkable

# --- Ranker names (frozen; they appear in every output record) --------------
RANKER_LROLESIM_M1_FIXED_K3 = "lrolesim_m1_fixed_k3"
RANKER_LEGACY_OVERLAP_BASELINE = "legacy_overlap_baseline"

#: The ranker the Journal-2 pilot proposes. Named once, here.
PROPOSED_RANKER_NAME = RANKER_LROLESIM_M1_FIXED_K3

KNOWN_RANKER_NAMES = (RANKER_LROLESIM_M1_FIXED_K3, RANKER_LEGACY_OVERLAP_BASELINE)

# --- The frozen Prompt-8C LRoleSim execution path --------------------------
# Mirrored from src/lrolesim/adapter.pilot_config(). Duplicated as CONSTANTS to
# be asserted against, never to be used as a second source of truth: this module
# checks that the frozen records say these values, it does not configure a run.
PILOT_MEASURE = "lrolesim_ed"
PILOT_LROLESIM_BETA = 0.2
PILOT_ITERATIONS = 3
PILOT_ITERATION_MODE = "fixed"

# --- Record scope -----------------------------------------------------------
SCOPE_PRIMARY = "primary"
SCOPE_DIAGNOSTIC = "diagnostic"

# --- Fact direction ---------------------------------------------------------
# For an OUT fact the owner is the subject and the counterpart is the object; for
# an IN fact the owner is the object and the counterpart is the SUBJECT. The
# neutral name `counterpart_uri` is what makes both readable, and is why this
# schema has no unconditional `object` field. AUDIT item EX-12 records the bug
# that field name caused in the legacy build_choices().
DIRECTION_OUT = "OUT"
DIRECTION_IN = "IN"
DIRECTIONS = (DIRECTION_OUT, DIRECTION_IN)

# --- Handoff statuses -------------------------------------------------------
RATIONALE_SELECTION_DEFERRED = "RATIONALE_SELECTION_DEFERRED_TO_PROMPT_8E"

#: The mapping/graph statuses Sulfuric acid keeps as the one primary failure.
NO_MAPPING_FEASIBLE_APPROVED_CLASS = "NO_MAPPING_FEASIBLE_APPROVED_CLASS"
NO_GRAPH_FEASIBLE_APPROVED_CLASS = "NO_GRAPH_FEASIBLE_APPROVED_CLASS"

#: Emitted on every provisional top-3 record so the reason is in the artefact.
NOT_FINAL_REASON = (
    "rationale feasibility has not been applied yet; these are structural "
    "plausibility ranks only"
)


class SelectionContractError(Exception):
    """A ranking or handoff violates the contract in this module."""


# ==========================================================================
# 1) RANKED CANDIDATES
# ==========================================================================

@dataclass(frozen=True)
class RankedCandidate:
    """One retained candidate at one rank, as produced by a CandidateRanker.

    `rank` is 1-based and contiguous within a ranking. `score` is whatever the
    named ranker measures — it is NOT comparable across rankers, which is why the
    ranker name travels with every record rather than being implied by context.
    """

    rank: int
    canonical_candidate_uri: str
    candidate_local_index: int
    score: float
    tie_group_id: int
    tie_group_size: int
    at_beta_floor: bool = False
    candidate_origin: Optional[str] = None
    graph_admission_position: Optional[int] = None

    def __post_init__(self) -> None:
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1:
            raise SelectionContractError(f"rank must be a 1-based int, got {self.rank!r}")
        if not isinstance(self.canonical_candidate_uri, str) or not self.canonical_candidate_uri:
            raise SelectionContractError(
                f"canonical_candidate_uri must be a non-empty string, got "
                f"{self.canonical_candidate_uri!r}")
        if self.canonical_candidate_uri.startswith("<") or self.canonical_candidate_uri.endswith(">"):
            # The bracketed spelling is the pinned pickle's KEY, not the URI.
            # Accepting both would give one node two identities in one file.
            raise SelectionContractError(
                f"canonical_candidate_uri must be unbracketed, got "
                f"{self.canonical_candidate_uri!r}")
        if isinstance(self.candidate_local_index, bool) or not isinstance(
                self.candidate_local_index, int):
            raise SelectionContractError(
                f"candidate_local_index must be an int, got "
                f"{self.candidate_local_index!r}")

    def as_record(self) -> dict:
        return {
            "rank": self.rank,
            "canonical_candidate_uri": self.canonical_candidate_uri,
            "candidate_local_index": self.candidate_local_index,
            "score": self.score,
            "tie_group_id": self.tie_group_id,
            "tie_group_size": self.tie_group_size,
            "at_beta_floor": self.at_beta_floor,
            "candidate_origin": self.candidate_origin,
            "graph_admission_position": self.graph_admission_position,
            # Restated per candidate, not only per Answer: a consumer that reads
            # one record in isolation must not be able to mistake a provisional
            # rank for a selected distractor.
            "is_final_distractor": False,
            "not_final_reason": NOT_FINAL_REASON,
        }


@dataclass(frozen=True)
class CandidateRanking:
    """The complete structural-plausibility order for ONE Answer, from ONE ranker.

    Immutable and self-describing: an instance carries the ranker that produced it,
    the measure configuration, and the graph fingerprint the order is valid for, so
    two rankings can never be merged by accident.
    """

    ranker_name: str
    answer_uri: str
    answer_local_index: int
    selected_class_uri: str
    graph_fingerprint: str
    measure: str
    lrolesim_beta: float
    iterations: int
    ranked: tuple[RankedCandidate, ...]
    primary_or_diagnostic: str = SCOPE_PRIMARY
    iteration_mode: str = PILOT_ITERATION_MODE

    def __post_init__(self) -> None:
        if self.ranker_name not in KNOWN_RANKER_NAMES:
            raise SelectionContractError(
                f"unknown ranker_name {self.ranker_name!r}; expected one of "
                f"{KNOWN_RANKER_NAMES}")
        if self.primary_or_diagnostic not in (SCOPE_PRIMARY, SCOPE_DIAGNOSTIC):
            raise SelectionContractError(
                f"primary_or_diagnostic must be {SCOPE_PRIMARY!r} or "
                f"{SCOPE_DIAGNOSTIC!r}, got {self.primary_or_diagnostic!r}")
        validate_ranking_order(self.ranked, answer_uri=self.answer_uri)

    def __len__(self) -> int:
        return len(self.ranked)

    @property
    def ranked_candidate_count(self) -> int:
        return len(self.ranked)

    @property
    def diagnostic_only(self) -> bool:
        return self.primary_or_diagnostic == SCOPE_DIAGNOSTIC

    @property
    def excluded_from_primary_policy_metrics(self) -> bool:
        return self.diagnostic_only

    def top(self, n: int = 3) -> tuple[RankedCandidate, ...]:
        """The first `n` ranks. PROVISIONAL — see is_final_distractor."""
        return self.ranked[:n]

    def candidate_uris(self) -> tuple[str, ...]:
        return tuple(c.canonical_candidate_uri for c in self.ranked)

    def as_record(self) -> dict:
        return {
            "ranker_name": self.ranker_name,
            "answer_uri": self.answer_uri,
            "answer_local_index": self.answer_local_index,
            "selected_class_uri": self.selected_class_uri,
            "graph_fingerprint": self.graph_fingerprint,
            "measure": self.measure,
            "lrolesim_beta": self.lrolesim_beta,
            "iterations": self.iterations,
            "iteration_mode": self.iteration_mode,
            "primary_or_diagnostic": self.primary_or_diagnostic,
            "diagnostic_only": self.diagnostic_only,
            "excluded_from_primary_policy_metrics":
                self.excluded_from_primary_policy_metrics,
            "ranked_candidate_count": self.ranked_candidate_count,
            "ranked_candidates": [c.as_record() for c in self.ranked],
        }


def validate_ranking_order(ranked: Sequence[RankedCandidate],
                           answer_uri: Optional[str] = None) -> None:
    """Enforce the order invariants every ranker must satisfy.

    Checked here rather than trusted per ranker, so a new ranker cannot introduce
    a non-contiguous, non-deterministic or self-including order:

      * ranks are 1..n and contiguous;
      * scores are non-increasing;
      * within one score, canonical URIs ascend (the frozen tiebreak);
      * a candidate appears at most once;
      * the Answer never ranks itself.
    """
    for position, candidate in enumerate(ranked, start=1):
        if candidate.rank != position:
            raise SelectionContractError(
                f"ranks must be contiguous from 1; position {position} carries "
                f"rank {candidate.rank}")

    seen: set[str] = set()
    for candidate in ranked:
        if candidate.canonical_candidate_uri in seen:
            raise SelectionContractError(
                f"candidate {candidate.canonical_candidate_uri!r} appears twice "
                f"in one ranking")
        seen.add(candidate.canonical_candidate_uri)
        if answer_uri is not None and candidate.canonical_candidate_uri == answer_uri:
            raise SelectionContractError(
                f"the Answer {answer_uri!r} must never rank itself")

    for earlier, later in zip(ranked, ranked[1:]):
        if later.score > earlier.score:
            raise SelectionContractError(
                f"scores must be non-increasing: rank {earlier.rank} scores "
                f"{earlier.score!r} but rank {later.rank} scores {later.score!r}")
        if (later.score == earlier.score
                and later.canonical_candidate_uri < earlier.canonical_candidate_uri):
            raise SelectionContractError(
                f"tied scores must break on ascending canonical candidate URI: "
                f"rank {earlier.rank} is {earlier.canonical_candidate_uri!r} but "
                f"rank {later.rank} is {later.canonical_candidate_uri!r}")


# ==========================================================================
# 2) THE RANKER INTERFACE
# ==========================================================================

@runtime_checkable
class CandidateRanker(Protocol):
    """What the selection layer requires of any candidate ranker.

    Deliberately minimal. A ranker answers "for this Answer, in what structural
    order do the retained candidates stand" and nothing else: it does not retrieve
    candidates, does not choose a class, does not build a graph and does not judge
    rationale feasibility. Those belong to the mapping, class-policy, graph and
    rationale layers respectively.
    """

    name: str

    def ranking_for_answer(self, answer_uri: str) -> CandidateRanking:
        """The complete ranking for one Answer.

        Raises rather than returning an empty ranking when the Answer has no
        feasible graph: "no ranking exists" and "the ranking is empty" are
        different states and must not be collapsed.
        """
        ...


# ==========================================================================
# 3) OBSERVED FACTS  (open-world safe)
# ==========================================================================

@dataclass(frozen=True)
class ObservedFact:
    """One URI-valued one-hop fact OBSERVED in the pinned local KG.

    OPEN-WORLD DISCIPLINE — the whole point of this dataclass
      An instance asserts only that the triple was SEEN in the pinned KG. There is
      no field for a negative fact, and there is no constructor that can express
      one, because DBpedia is open-world: a triple absent from the dump is not a
      false triple. The rationale layer may compute an `observed_contrast` between
      two owners' fact sets, but it may never read absence as falsity.

    DIRECTION SEMANTICS
      direction == OUT   the triple is (owner_uri, predicate_uri, counterpart_uri)
      direction == IN    the triple is (counterpart_uri, predicate_uri, owner_uri)

      So `counterpart_uri` is the object of an OUT fact and the SUBJECT of an IN
      fact. It is never called `object`.
    """

    owner_uri: str
    owner_local_index: int
    predicate_uri: str
    direction: str
    counterpart_uri: str
    counterpart_local_index: int
    graph_fingerprint: str
    primary_or_diagnostic: str = SCOPE_PRIMARY

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise SelectionContractError(
                f"direction must be one of {DIRECTIONS}, got {self.direction!r}")
        if self.primary_or_diagnostic not in (SCOPE_PRIMARY, SCOPE_DIAGNOSTIC):
            raise SelectionContractError(
                f"primary_or_diagnostic must be {SCOPE_PRIMARY!r} or "
                f"{SCOPE_DIAGNOSTIC!r}, got {self.primary_or_diagnostic!r}")
        for name in ("owner_uri", "predicate_uri", "counterpart_uri"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise SelectionContractError(
                    f"{name} must be a non-empty string, got {value!r}")
            if value.startswith("<") or value.endswith(">"):
                raise SelectionContractError(
                    f"{name} must be unbracketed, got {value!r}")

    @property
    def subject_uri(self) -> str:
        """The triple's subject, resolved from the direction."""
        return self.owner_uri if self.direction == DIRECTION_OUT else self.counterpart_uri

    @property
    def object_uri(self) -> str:
        """The triple's object, resolved from the direction."""
        return self.counterpart_uri if self.direction == DIRECTION_OUT else self.owner_uri

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        """The frozen serialization order: owner, direction, predicate, counterpart."""
        return (self.owner_uri, self.direction, self.predicate_uri,
                self.counterpart_uri)

    @property
    def contrast_key(self) -> tuple[str, str, str]:
        """The owner-independent identity of a fact.

        Two owners "share" a fact when this key matches. Prompt 8E compares these
        keys to compute an observed_contrast; nothing here interprets a missing key
        as a negative fact.
        """
        return (self.direction, self.predicate_uri, self.counterpart_uri)

    def as_record(self) -> dict:
        return {
            "owner_uri": self.owner_uri,
            "owner_local_index": self.owner_local_index,
            "predicate_uri": self.predicate_uri,
            "direction": self.direction,
            "counterpart_uri": self.counterpart_uri,
            "counterpart_local_index": self.counterpart_local_index,
            "graph_fingerprint": self.graph_fingerprint,
            "primary_or_diagnostic": self.primary_or_diagnostic,
        }


def sort_observed_facts(facts: Sequence[ObservedFact]) -> tuple[ObservedFact, ...]:
    """Deduplicate and sort by (owner_uri, direction, predicate_uri, counterpart_uri).

    Deduplication is by the full sort key, so a triple repeated in the source dump
    is serialized once. Sorting is total, so the output byte stream does not depend
    on set or dict iteration order anywhere upstream.
    """
    unique: dict[tuple[str, str, str, str], ObservedFact] = {}
    for fact in facts:
        unique.setdefault(fact.sort_key, fact)
    return tuple(unique[key] for key in sorted(unique))


# ==========================================================================
# 4) THE RATIONALE-SELECTION HANDOFF
# ==========================================================================

@dataclass(frozen=True)
class RationaleSelectionHandoff:
    """Everything Prompt 8E needs for ONE Answer, and nothing it must not assume.

    This is deliberately an INPUT to rationale selection, not an output of it. It
    carries the complete ranked candidate list and a provisional top-3, all marked
    is_final_distractor = False, plus the frozen provenance that binds them to one
    graph.
    """

    answer_uri: str
    answer_local_index: int
    selected_class_uri: Optional[str]
    mapping_stage_status: str
    graph_stage_status: str
    graph_fingerprint: Optional[str]
    ranker_name: str
    measure: Optional[str]
    lrolesim_beta: Optional[float]
    iterations: Optional[int]
    ranked_candidate_count: int
    ranked_candidates: tuple[RankedCandidate, ...] = ()
    provisional_lrolesim_top3: tuple[RankedCandidate, ...] = ()
    rationale_selection_status: str = RATIONALE_SELECTION_DEFERRED
    primary_or_diagnostic: str = SCOPE_PRIMARY
    pilot_slot: Optional[int] = None
    display_label: Optional[str] = None
    ready_for_rationale_selection: bool = True
    observed_fact_counts: dict = field(default_factory=dict)

    @property
    def diagnostic_only(self) -> bool:
        return self.primary_or_diagnostic == SCOPE_DIAGNOSTIC

    def as_record(self) -> dict:
        return {
            "answer_uri": self.answer_uri,
            "answer_local_index": self.answer_local_index,
            "display_label": self.display_label,
            "pilot_slot": self.pilot_slot,
            "primary_or_diagnostic": self.primary_or_diagnostic,
            "diagnostic_only": self.diagnostic_only,
            "excluded_from_primary_policy_metrics": self.diagnostic_only,
            "selected_class_uri": self.selected_class_uri,
            "mapping_stage_status": self.mapping_stage_status,
            "graph_stage_status": self.graph_stage_status,
            "graph_fingerprint": self.graph_fingerprint,
            "ranker_name": self.ranker_name,
            "measure": self.measure,
            "lrolesim_beta": self.lrolesim_beta,
            "iterations": self.iterations,
            "iteration_mode": PILOT_ITERATION_MODE if self.measure else None,
            "ranked_candidate_count": self.ranked_candidate_count,
            "ranked_candidates": [c.as_record() for c in self.ranked_candidates],
            "provisional_lrolesim_top3": [
                c.as_record() for c in self.provisional_lrolesim_top3],
            "ready_for_rationale_selection": self.ready_for_rationale_selection,
            "rationale_selection_status": self.rationale_selection_status,
            "observed_fact_counts": dict(self.observed_fact_counts),
        }
