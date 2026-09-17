############################################################################
# src/pipeline/phase_b2_answer_run.py
#
# Prompt 8H-B2-B orchestration: ONE genuinely new Answer, end to end.
#
#   automatic v5 class ranking
#     -> complete class-member retrieval          (live SPARQL, cached)
#     -> mapping into the pinned local KG         (§E local-mapping gate)
#     -> M1 graph admission                       (frozen policy)
#     -> frozen Journal-2 LRoleSim                (lrolesim_m1_fixed_k3)
#     -> COMPLETE ranked candidate pool
#     -> exact enlarged semantic-index source-object set
#     -> offline semantic-index rebuild
#     -> mcq_inputs.build_and_select()            (frozen Phase-B kernel)
#
# WHY THIS MODULE EXISTS AT ALL, AND WHAT IT REFUSES TO BE
# --------------------------------------------------------
# Every scientific decision below already has exactly one owner elsewhere in
# this repository. This module owns NONE of them. It is glue: it walks the
# stages in order, carries one stage's output into the next stage's input
# shape, and records what happened at each step. Concretely it delegates
#
#   class ranking / leakage  -> category_extractor_ClaudeWeb_v5 (via its runner)
#   member retrieval         -> classes.member_mapper.ClassMemberRetriever
#   redirect resolution      -> classes.member_mapper.resolve_redirect_chains
#   local mapping            -> classes.member_mapper.map_class_members
#   graph admission order    -> pipeline.candidate_order
#   M1 graph budget          -> pipeline.graph_lrolesim_run.attempt_class_graph
#   LRoleSim ranking         -> pipeline.graph_lrolesim_run.rank_graph
#   semantic index build     -> pipeline.rationale_v3_run
#   evidence / quality / set cover / objective -> mcq_inputs + mcq_core
#
# and it reimplements not one line of any of them. The existing pilot drivers
# (`classes.mapping_run.run_mapping`, `graph_lrolesim_run.run_pilot`) are NOT
# reused as drivers, for one reason only: both are parameterised by
# `data/pilot_class_policy_v1.csv`, whose human approval covers exactly nine
# Answers and explicitly does not cover Albert Einstein. Driving them would
# require inventing a tenth approved row, i.e. a synthetic class approval. The
# pure functions underneath those drivers are shared and are what this module
# calls.
#
# WHY THE B2-A IDF-ONLY RANKING IS NOT AUTOMATICALLY THE B2 CLASS
# ---------------------------------------------------------------
# Prompt 8H-B2-A ranked Albert Einstein's 67 feasible classes and reported
# `dbc:German_relativity_theorists` as top-1. That run performed NO check
# against the pinned local KG (`local_check: "not_applicable"` on every row),
# so its top-1 is a statement about DBpedia's remote category sizes and about
# label specificity, and says nothing whatsoever about whether the class can
# produce a usable candidate roster HERE. A class of 600 remote members can map
# to three local nodes. Local mapping is therefore a SEPARATE FEASIBILITY
# STAGE, applied to the ranking in order, and the class this module selects is
# `first_locally_mapping_feasible_class` — never "the optimal class".
#
# WHY alpha=0.7 IS A CONFIGURATION AND NOT AN OPTIMALITY CLAIM
# ------------------------------------------------------------
# `combined = 0.7 * normalized_sbert + 0.3 * normalized_idf` is the
# PRE-SPECIFIED working configuration for B2, fixed before the run so that the
# class choice is not selected post hoc from several weightings. It is not
# claimed to be optimal, tuned, or better than any other alpha; a controlled
# sensitivity experiment is a separate, later task. See
# `SBERT_COMPONENT_STATUS` below for what actually happened to the SBERT half
# on this run, which is recorded rather than quietly absorbed.
#
# WHY THE COMPLETE RANKED POOL IS NOT THE BOUNDED SEARCH POOL
# ------------------------------------------------------------
# `complete_ranked_pool` is every candidate the M1 graph retained, ranked by
# LRoleSim, with contiguous ranks 1..n. It is the anonymity denominator and it
# is what `Candidate.rank` indexes. When C(n,3) exceeds the kernel's budget the
# kernel searches a BOUNDED POOL instead and reports POOL_EXACT: exact within
# that pool, carrying no optimality claim over the candidates it excluded. The
# two are different objects with different epistemic status and this module
# never conflates them — it hands the kernel the complete pool and lets the
# kernel decide and report its own scope.
#
# WHY THE SEMANTIC INDEX MUST BE REBUILT FOR A NEW ANSWER
# --------------------------------------------------------
# `SemanticIndexCacheKey` includes `source_object_list_sha256`, the digest of
# the exact set of counterpart URIs the run reasons about. Albert Einstein's
# Answer objects and his candidates' objects under the same predicate-direction
# keys are not in the pilot's set, so the pilot cache legitimately refuses to
# load for him. Reusing it would be a cache-key violation; ignoring the refusal
# would leave every L1 pair carrying UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE for
# no reason other than not having rebuilt. So the set is derived exactly, its
# digest recorded, and the index rebuilt offline from the pinned KG.
#
# WHY L0/L1/L2 CANNOT BE CHANGED TO OBTAIN YIELD
# -----------------------------------------------
# L0 is snapshot ABSENCE ONLY and is never showable to a student: under the
# open-world assumption `(d, p, o) ∉ K` does not imply `¬p(d, o)`, so "DBpedia
# does not record it" is not a reason a distractor is wrong. L1 is an OBSERVED
# ALTERNATIVE under the same key — the weakest thing that is showable, and
# still not a logical negation, because many infobox predicates are
# multi-valued. L2 requires a machine-checkable exclusion proof and the frozen
# policy activates no L2 rule, so zero L2 is the correct outcome and not a gap.
# If this Answer yields no valid selection, that is a measurement to report,
# not a threshold to lower.
############################################################################

from __future__ import annotations

import csv
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from classes.member_mapper import (                             # noqa: E402
    MIN_MAPPED_LOCAL_CANDIDATES,
    CachedPageFetcher,
    ClassMappingResult,
    ClassMemberRetriever,
    ClassRetrieval,
    SparqlRedirectSource,
    collect_unmatched_members,
    make_local_lookup,
    resolve_redirect_chains,
)
from classes.page_cache import PageCache                        # noqa: E402
from classes.sparql_client import (                             # noqa: E402
    DBPEDIA_ENDPOINT,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_REDIRECT_HOPS,
    DEFAULT_PAGE_SIZE,
    DEFAULT_REDIRECT_BATCH_SIZE,
    RequestsHttpTransport,
    SparqlPageClient,
    strip_uri_brackets,
)
from pipeline.candidate_order import (                          # noqa: E402
    ORIGIN_EXACT,
    ORIGIN_REDIRECT,
    MappedCandidate,
)
from pipeline.graph_lrolesim_run import (                       # noqa: E402
    ATTEMPT_GRAPH_FEASIBLE,
    GRAPH_MAX_CANDIDATES,
    GRAPH_MAX_NODES,
    GRAPH_GATE_MIN_CANDIDATES,
    GRAPH_STAGE_MAPPING_GATE,
    ClassMappingFacts,
    GraphStageResult,
    ScoreCache,
    SourceHashes,
    attempt_class_graph,
    canonical_candidate_uri,
    rank_graph,
)

# --- Pinned inputs, restated so a drift is an error rather than a surprise --
PINNED_LOCAL_KG = REPO_ROOT / "data" / "infobox.pickle_EnglishVersion_EntityType"
PINNED_LOCAL_KG_SHA256 = (
    "e230c5b95e20093631697624d9c46f30a14081b3f415d5027ffaf313bdbbea1b"
)

#: The Answer this task completes. It is a PARAMETER of every function below —
#: the constant exists only so the driver script has a default, and no function
#: in this module branches on its value. See the B2 test that greps this
#: module's own source for an Einstein-specific control-flow string.
DEFAULT_ANSWER_URI = "http://dbpedia.org/resource/Albert_Einstein"

#: §D.2 — the pre-specified B2 class-ranking configuration. Recorded, never
#: claimed optimal, and never re-derived here: the v5 selector computes the
#: score and this module only reads its output.
B2_RANKING_MODE = "recommended"
B2_RANKING_ALPHA = 0.7

#: §E — the local-mapping feasibility gate. Identical in value to the Week-1
#: mapping gate and to the graph stage's own entry test, and deliberately so:
#: this is the same declared rule, applied to a new Answer, not a new threshold.
LOCAL_MAPPING_GATE = MIN_MAPPED_LOCAL_CANDIDATES

#: Class-attempt outcomes for the §E walk. Distinct from the graph stage's
#: outcomes, because a class can pass local mapping and still fail the graph
#: budget, and the report must be able to say which happened.
ATTEMPT_MAPPING_FEASIBLE = "MAPPING_FEASIBLE"
ATTEMPT_MAPPING_BELOW_GATE = "MAPPING_COUNT_BELOW_GATE"
ATTEMPT_RETRIEVAL_INCOMPLETE = "RETRIEVAL_INCOMPLETE"
ATTEMPT_NOT_ATTEMPTED_EARLIER_CLASS_SELECTED = "NOT_ATTEMPTED_EARLIER_CLASS_SELECTED"

#: §E outcome for the Answer as a whole.
MAPPING_SELECTED_FIRST_FEASIBLE = "MAPPING_SELECTED_FIRST_LOCALLY_FEASIBLE_RANKED_CLASS"
NO_MAPPING_FEASIBLE_RANKED_CLASS = "NO_MAPPING_FEASIBLE_RANKED_CLASS"

#: What `class_approval_status` carries into `mcq_inputs.build_and_select()`.
#: `validate_run_provenance` requires a non-empty string and deliberately does
#: not constrain its VALUE, so that a later frozen class-selection procedure can
#: report its own status. This one says exactly what happened and claims nothing
#: more: the class came from the automatic v5 policy and then passed the
#: declared local-mapping gate. It is NOT `HUMAN_APPROVED` — no human worksheet
#: decision exists for Albert Einstein, and inventing one would be a synthetic
#: class approval.
B2_CLASS_APPROVAL_STATUS = (
    "AUTOMATIC_V5_POLICY_SELECTED_LOCAL_MAPPING_FEASIBLE_NOT_HUMAN_APPROVED"
)


class PhaseB2Error(Exception):
    """The B2 run cannot proceed on the inputs it was given."""


# ==========================================================================
# 1) THE RANKED CLASS LIST (read, never recomputed)
# ==========================================================================


@dataclass(frozen=True)
class RankedClass:
    """One feasible class from the v5 ranking, in the v5 ranking's own order.

    Every field is COPIED from the selector's output. This module computes no
    IDF, no SBERT similarity, no combined score and no leakage verdict: doing so
    would create a second implementation of the class-selection science that
    could drift from the first.
    """

    rank: int
    class_uri: str
    class_short: str
    display_label: str
    remote_count: int
    eligible_remote_count: int
    raw_idf: float
    normalized_idf: float
    raw_sbert: float
    normalized_sbert: float
    combined_score: float
    leak_level: str
    leak_source: str
    leak_evidence: str

    def as_record(self) -> dict:
        return {
            "ranking_position": self.rank,
            "class_uri": self.class_uri,
            "class_short": self.class_short,
            "display_label": self.display_label,
            "remote_count": self.remote_count,
            "eligible_remote_count": self.eligible_remote_count,
            "raw_idf": self.raw_idf,
            "normalized_idf": self.normalized_idf,
            "raw_sbert": self.raw_sbert,
            "normalized_sbert": self.normalized_sbert,
            "combined_score": self.combined_score,
            "leak_level": self.leak_level,
            "leak_source": self.leak_source,
            "leak_evidence": self.leak_evidence,
        }


def load_v5_selection(results_jsonl: str | Path, answer_uri: str) -> dict:
    """The one v5 `results.jsonl` record for this Answer.

    Read-only. A missing or duplicated record is an error rather than a default,
    because a B2 run driven by the wrong Answer's ranking would be silently
    meaningless.
    """
    matches = []
    for number, line in enumerate(
            Path(results_jsonl).read_text("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise PhaseB2Error(
                f"{results_jsonl}: line {number} is not valid JSON: {error}") from error
        if record.get("original_uri") == answer_uri:
            matches.append(record)
    if not matches:
        raise PhaseB2Error(f"{results_jsonl}: no v5 record for {answer_uri}")
    if len(matches) > 1:
        raise PhaseB2Error(
            f"{results_jsonl}: {len(matches)} v5 records for {answer_uri}, expected 1")
    return matches[0]


def ranked_feasible_classes(selection: Mapping) -> tuple[RankedClass, ...]:
    """The COMPLETE feasible ranking, in the v5 selector's deterministic order.

    The order is the selector's own — descending `combined_score`, then ascending
    `category_uri` — and is preserved exactly as `recommended_classes` presents
    it. Nothing is re-sorted here, because re-sorting on a float that was
    serialised and re-parsed can reorder a tie differently from the run that
    produced it.

    HARD-leaking classes never appear: the selector rejected them before scoring,
    so they are not in `recommended_classes` at all. That is the point of the §D.4
    gate, and this module relies on it rather than re-testing leakage itself.
    """
    ranked: list[RankedClass] = []
    for position, entry in enumerate(selection.get("recommended_classes") or (), start=1):
        if not entry.get("feasible"):
            continue
        ranked.append(RankedClass(
            rank=position,
            class_uri=entry["category_uri"],
            class_short=entry["category_short"],
            display_label=entry["display_label"],
            remote_count=int(entry["remote_count"]),
            eligible_remote_count=int(entry["eligible_remote_count"]),
            raw_idf=float(entry["raw_idf"]),
            normalized_idf=float(entry["normalized_idf"]),
            raw_sbert=float(entry["raw_sbert"]),
            normalized_sbert=float(entry["normalized_sbert"]),
            combined_score=float(entry["combined_score"]),
            leak_level=str(entry["leak_level"]),
            leak_source=str(entry.get("leak_source") or ""),
            leak_evidence=";".join(entry.get("leak_evidence") or ()),
        ))
    if not ranked:
        raise PhaseB2Error(
            "the v5 selection record contains no feasible recommended class, so "
            "there is nothing for the local-mapping stage to walk")
    return tuple(ranked)


# ==========================================================================
# 2) §E — LOCAL-MAPPING FEASIBILITY, A SEPARATE STAGE FROM RANKING
# ==========================================================================


@dataclass(frozen=True)
class ClassMappingAttempt:
    """One ranked class considered at the local-mapping stage, and its outcome.

    Recorded for EVERY class the walk touched, including the ones it never
    reached, so the provenance shows the whole ranking and exactly where the walk
    stopped. A class that was never attempted is not evidence that it would have
    failed.
    """

    ranking_position: int
    class_uri: str
    attempted: bool
    outcome: str
    remote_count: int
    retrieval_complete: bool
    incomplete_reason: Optional[str]
    unique_member_count: int
    page_count: int
    exact_mapped_count: int
    redirect_mapped_count: int
    unresolved_count: int
    duplicate_dropped_count: int
    answer_excluded_count: int
    mapped_candidate_count_excluding_answer: int
    passes_local_mapping_gate: bool
    detail: str

    def as_record(self) -> dict:
        return {
            "ranking_position": self.ranking_position,
            "class_uri": self.class_uri,
            "attempted": self.attempted,
            "outcome": self.outcome,
            "remote_member_count": self.remote_count,
            "retrieval_complete": self.retrieval_complete,
            "incomplete_reason": self.incomplete_reason,
            "unique_member_count": self.unique_member_count,
            "page_count": self.page_count,
            "mapped_exact_count": self.exact_mapped_count,
            "mapped_redirect_count": self.redirect_mapped_count,
            "unresolved_count": self.unresolved_count,
            "duplicate_local_index_dropped": self.duplicate_dropped_count,
            "answer_excluded_count": self.answer_excluded_count,
            "mapped_candidates_excluding_answer":
                self.mapped_candidate_count_excluding_answer,
            "local_mapping_gate": LOCAL_MAPPING_GATE,
            "passes_local_mapping_gate": self.passes_local_mapping_gate,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class LocalMappingWalk:
    """The §E outcome: every attempt, and the first feasible class if any."""

    answer_uri: str
    answer_local_index: Optional[int]
    status: str
    selected_class_uri: Optional[str]
    selected_ranking_position: Optional[int]
    attempts: tuple[ClassMappingAttempt, ...]
    selected_mapping: Optional[ClassMappingResult]
    retrievals: Mapping[str, ClassRetrieval]

    @property
    def is_feasible(self) -> bool:
        return self.status == MAPPING_SELECTED_FIRST_FEASIBLE


def _attempt_from_mapping(
    ranked: RankedClass, mapping: ClassMappingResult
) -> ClassMappingAttempt:
    """Turn one completed mapping into its attempt record.

    The gate is applied to `mapped_candidate_count`, which
    `ClassMappingResult` defines as DISTINCT local candidates with the Answer
    already excluded — the two exclusions §E requires, both performed upstream by
    the frozen mapper rather than recomputed here.
    """
    retrieval = mapping.retrieval
    complete = retrieval.retrieval_complete
    count = mapping.mapped_candidate_count
    passes = complete and count >= LOCAL_MAPPING_GATE
    if not complete:
        outcome = ATTEMPT_RETRIEVAL_INCOMPLETE
        detail = (f"member enumeration did not complete "
                  f"({retrieval.incomplete_reason}); a class selected from a "
                  f"partial member list would not be the whole class")
    elif passes:
        outcome = ATTEMPT_MAPPING_FEASIBLE
        detail = (f"{count} distinct local candidates excluding the Answer "
                  f">= gate {LOCAL_MAPPING_GATE}")
    else:
        outcome = ATTEMPT_MAPPING_BELOW_GATE
        detail = (f"{count} distinct local candidates excluding the Answer "
                  f"< gate {LOCAL_MAPPING_GATE}")
    return ClassMappingAttempt(
        ranking_position=ranked.rank,
        class_uri=ranked.class_uri,
        attempted=True,
        outcome=outcome,
        remote_count=ranked.remote_count,
        retrieval_complete=complete,
        incomplete_reason=retrieval.incomplete_reason,
        unique_member_count=retrieval.unique_member_count,
        page_count=retrieval.page_count,
        exact_mapped_count=mapping.exact_mapped_count,
        redirect_mapped_count=mapping.redirect_mapped_count,
        unresolved_count=mapping.unresolved_count,
        duplicate_dropped_count=mapping.duplicate_dropped_count,
        answer_excluded_count=mapping.answer_excluded_count,
        mapped_candidate_count_excluding_answer=count,
        passes_local_mapping_gate=passes,
        detail=detail,
    )


def walk_ranked_classes_for_local_mapping(
    answer_uri: str,
    ranked: Sequence[RankedClass],
    *,
    retriever: ClassMemberRetriever,
    redirect_source: object,
    local_lookup: Callable[[str], object],
    max_redirect_hops: int = DEFAULT_MAX_REDIRECT_HOPS,
    max_classes: Optional[int] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> LocalMappingWalk:
    """Walk the ranking IN ORDER and stop at the first locally feasible class.

    This is §E's declared rule and it is generic: the only inputs are the
    ranking, the retrieved member sets and the pinned graph. There is no
    per-Answer fallback list, no hard-coded class, and no branch on the Answer's
    identity — swapping in a different Answer's ranking runs the identical code.

    RETRIEVAL IS COMPLETED BEFORE ITS CLASS IS JUDGED. `ClassRetrieval` reports
    `retrieval_complete` separately from its member list, and a class whose
    enumeration stopped early is refused rather than gated on a partial list: a
    partial list can only understate the mapped count, so passing the gate on one
    would be luck and failing it would be uninformative.

    STOPPING EARLY IS NOT A JUDGEMENT ON THE CLASSES BELOW. Classes after the
    selected one are recorded as NOT ATTEMPTED. Retrieving all 67 would cost
    tens of thousands of member rows to answer a question the walk does not ask.

    `max_classes` bounds how many classes may be RETRIEVED, so a pathological
    ranking cannot turn one Answer into an unbounded crawl. Exhausting it is
    reported as a failure of the walk, never as "no feasible class exists".
    """
    say = progress or (lambda message: None)
    answer_lookup = local_lookup(answer_uri)
    answer_index = getattr(answer_lookup, "local_index", None)
    if answer_index is None:
        raise PhaseB2Error(
            f"{answer_uri} is absent from the pinned local KG; without an Answer "
            f"node there is no one-hop neighbourhood to pin the M1 graph to")

    attempts: list[ClassMappingAttempt] = []
    retrievals: dict[str, ClassRetrieval] = {}
    selected: Optional[tuple[RankedClass, ClassMappingResult]] = None
    budget = len(ranked) if max_classes is None else int(max_classes)
    retrieved = 0

    for ranked_class in ranked:
        if selected is not None:
            attempts.append(ClassMappingAttempt(
                ranking_position=ranked_class.rank,
                class_uri=ranked_class.class_uri,
                attempted=False,
                outcome=ATTEMPT_NOT_ATTEMPTED_EARLIER_CLASS_SELECTED,
                remote_count=ranked_class.remote_count,
                retrieval_complete=False,
                incomplete_reason=None,
                unique_member_count=0, page_count=0,
                exact_mapped_count=0, redirect_mapped_count=0,
                unresolved_count=0, duplicate_dropped_count=0,
                answer_excluded_count=0,
                mapped_candidate_count_excluding_answer=0,
                passes_local_mapping_gate=False,
                detail=(f"rank {selected[0].rank} ({selected[0].class_uri}) was "
                        f"already locally feasible, so the walk stopped before "
                        f"this position; this class was NOT tested and NOT "
                        f"rejected"),
            ))
            continue
        if retrieved >= budget:
            attempts.append(ClassMappingAttempt(
                ranking_position=ranked_class.rank,
                class_uri=ranked_class.class_uri,
                attempted=False,
                outcome="NOT_ATTEMPTED_RETRIEVAL_BUDGET_EXHAUSTED",
                remote_count=ranked_class.remote_count,
                retrieval_complete=False, incomplete_reason=None,
                unique_member_count=0, page_count=0,
                exact_mapped_count=0, redirect_mapped_count=0,
                unresolved_count=0, duplicate_dropped_count=0,
                answer_excluded_count=0,
                mapped_candidate_count_excluding_answer=0,
                passes_local_mapping_gate=False,
                detail=f"retrieval budget {budget} classes exhausted",
            ))
            continue

        bare = strip_uri_brackets(ranked_class.class_uri)
        say(f"  [{ranked_class.rank:>3}] retrieving members of {bare} "
            f"(remote_count={ranked_class.remote_count}) ...")
        retrieval = retriever.retrieve(bare)
        retrievals[bare] = retrieval
        retrieved += 1

        # Redirects are resolved for THIS class's unmatched members only. The
        # pilot resolved the union across all approved classes at once because it
        # knew the whole set in advance; the walk does not, and resolving per
        # class keeps a class that is never reached from costing any query.
        unmatched = collect_unmatched_members({bare: retrieval}, local_lookup)
        redirects = resolve_redirect_chains(
            unmatched, redirect_source, local_lookup, max_hops=max_redirect_hops)

        mapping = map_class_members_for_ranked_class(
            answer_uri=answer_uri, ranked=ranked_class,
            retrieval=retrieval, local_lookup=local_lookup,
            redirect_outcomes=redirects)
        attempt = _attempt_from_mapping(ranked_class, mapping)
        attempts.append(attempt)
        say(f"        -> {attempt.outcome}: "
            f"{attempt.unique_member_count} members, "
            f"{attempt.exact_mapped_count} exact + "
            f"{attempt.redirect_mapped_count} redirect, "
            f"{attempt.mapped_candidate_count_excluding_answer} mapped "
            f"candidates excluding Answer")
        if attempt.passes_local_mapping_gate:
            selected = (ranked_class, mapping)

    if selected is None:
        return LocalMappingWalk(
            answer_uri=answer_uri, answer_local_index=answer_index,
            status=NO_MAPPING_FEASIBLE_RANKED_CLASS,
            selected_class_uri=None, selected_ranking_position=None,
            attempts=tuple(attempts), selected_mapping=None,
            retrievals=retrievals)
    ranked_class, mapping = selected
    return LocalMappingWalk(
        answer_uri=answer_uri, answer_local_index=answer_index,
        status=MAPPING_SELECTED_FIRST_FEASIBLE,
        selected_class_uri=ranked_class.class_uri,
        selected_ranking_position=ranked_class.rank,
        attempts=tuple(attempts), selected_mapping=mapping,
        retrievals=retrievals)


def map_class_members_for_ranked_class(
    *,
    answer_uri: str,
    ranked: RankedClass,
    retrieval: ClassRetrieval,
    local_lookup: Callable[[str], object],
    redirect_outcomes: Mapping[str, object],
) -> ClassMappingResult:
    """Delegate to the frozen mapper, labelling the class by its ranking position.

    `class_position` is a required field of `ClassMappingResult` and its frozen
    vocabulary (`preferred` / `fallback_1` / `fallback_2`) describes a
    three-slot human-approved policy that does not exist for this Answer.
    Reusing one of those three tokens would misreport an automatic ranking
    position as an approved policy slot, so the position is spelled explicitly as
    `ranked_<n>` instead. Nothing downstream in the B2 path parses it — the graph
    stage receives the position this module hands it — and `mcq_inputs` records
    class approval on its own separate `class_approval_status` field.
    """
    from classes.member_mapper import map_class_members   # local: keeps the

    # import graph of this module's readers small and mirrors the frozen
    # modules' own lazy-import discipline for heavy siblings.
    return map_class_members(
        answer_uri=answer_uri,
        class_uri=strip_uri_brackets(ranked.class_uri),
        class_position=f"ranked_{ranked.rank}",
        retrieval=retrieval,
        local_lookup=local_lookup,
        redirect_outcomes=redirect_outcomes,
    )


def mapped_candidates_from_result(mapping: ClassMappingResult) -> tuple[MappedCandidate, ...]:
    """The accepted local candidates, in the shape the graph stage expects.

    `canonical_candidate_uri()` is the frozen rule for which URI names the local
    node: a REDIRECT member resolved through its target, so the TARGET is the
    node's own URI, while an EXACT member resolved on the retrieved URI itself.
    Keying a redirect on the retrieved alias would order the admission on a URI
    that is not the node being scored.
    """
    candidates: list[MappedCandidate] = []
    for member in mapping.members:
        if not member.accepted:
            continue
        record = member.as_record()
        candidates.append(MappedCandidate(
            canonical_uri=canonical_candidate_uri(record),
            local_index=member.local_index,
            mapping_origin=(ORIGIN_REDIRECT
                            if member.mapping_origin == ORIGIN_REDIRECT
                            else ORIGIN_EXACT),
            retrieved_uri=member.normalized_member_uri,
        ))
    return tuple(candidates)


# ==========================================================================
# 3) §F — M1 GRAPH AND THE FROZEN LRoleSim RANKING
# ==========================================================================


def mapping_facts_for_graph_stage(
    walk: LocalMappingWalk, *, pilot_slot: int = 0
) -> ClassMappingFacts:
    """Express the §E result in the frozen graph stage's own input shape.

    `attempt_class_graph()` consumes `ClassMappingFacts` and applies its own
    entry test (`retrieval_complete` and `>= GRAPH_STAGE_MAPPING_GATE` mapped
    candidates) before building anything. Those are the same two conditions §E
    already enforced, and they are deliberately left in place rather than
    bypassed: the graph stage re-checking its own preconditions is what makes it
    safe to call from a new driver.

    `pilot_slot` is a bookkeeping integer in the frozen record shape, not a
    scientific quantity. Zero marks "not a member of the nine-Answer pilot",
    which is exactly what this Answer is.
    """
    if walk.selected_mapping is None or walk.selected_class_uri is None:
        raise PhaseB2Error(
            "no locally mapping-feasible class was selected, so there is no "
            "candidate set to build an M1 graph from")
    mapping = walk.selected_mapping
    return ClassMappingFacts(
        pilot_slot=pilot_slot,
        answer_uri=walk.answer_uri,
        answer_local_index=walk.answer_local_index,
        class_position=mapping.class_position,
        class_uri=walk.selected_class_uri,
        retrieval_complete=mapping.retrieval.retrieval_complete,
        mapped_candidate_count_excluding_answer=mapping.mapped_candidate_count,
        accepted=mapped_candidates_from_result(mapping),
    )


def build_graph_and_rank(
    walk: LocalMappingWalk,
    local_kg,
    *,
    display_label: str,
    score_cache_path: str | Path,
    pilot_slot: int = 0,
    progress: Optional[Callable[[str], None]] = None,
):
    """Build the M1 graph and produce the COMPLETE ranked candidate pool.

    Both halves are the frozen implementations, called unmodified:

    * `attempt_class_graph()` applies the frozen M1 policy — Answer pinned, each
      admitted candidate's COMPLETE URI-valued one-hop IN/OUT neighbourhood
      admitted or the candidate rejected outright (never partially truncated),
      at most 50 candidates, at most 1,200 nodes, at least 10 retained
      candidates for success. Context nodes enter the graph to give candidates
      their structure and are NEVER offered to the ranker, so they cannot become
      distractors.
    * `rank_graph()` runs the frozen Journal-2 configuration
      `lrolesim_m1_fixed_k3` / `lrolesim_ed` / beta 0.2 / exactly 3 fixed
      iterations, through `lrolesim.adapter` driving
      `MCQ_lrolesim_ClaudeWeb_v2`. `src/MCQ_lrolesim.py` is not imported and no
      legacy Overlap ranking is involved.

    Returns `(attempt, graph_result, scored, fingerprint, provenance)`. `scored`
    is the COMPLETE ranked pool over every RETAINED candidate, with contiguous
    ranks from 1 — not a top-k slice, and not the bounded search pool the kernel
    may later choose to search.
    """
    say = progress or (lambda message: None)
    facts = mapping_facts_for_graph_stage(walk, pilot_slot=pilot_slot)
    say(f"  M1 graph: offering {len(facts.accepted)} mapped candidates "
        f"(max_candidates={GRAPH_MAX_CANDIDATES}, max_nodes={GRAPH_MAX_NODES}, "
        f"min retained={GRAPH_GATE_MIN_CANDIDATES})")
    attempt, m1_graph, order = attempt_class_graph(facts, local_kg)
    say(f"        -> {attempt.outcome}: {attempt.accepted_candidate_count} "
        f"retained, {attempt.retained_node_count} nodes, "
        f"{attempt.retained_edge_count} edges")
    if attempt.outcome != ATTEMPT_GRAPH_FEASIBLE:
        return attempt, None, (), None, {}

    result = GraphStageResult(
        pilot_slot=pilot_slot,
        answer_uri=walk.answer_uri,
        display_label=display_label,
        answer_local_index=walk.answer_local_index,
        mapping_stage_status=walk.status,
        graph_stage_status=ATTEMPT_GRAPH_FEASIBLE,
        selected_class_position=facts.class_position,
        selected_class_uri=walk.selected_class_uri,
        attempts=(attempt,),
        m1_graph=m1_graph,
        order=order,
    )
    cache = ScoreCache(score_cache_path).load()
    scored, fingerprint, provenance = rank_graph(
        result, local_kg, cache, SourceHashes.collect())
    say(f"  LRoleSim: {len(scored)} ranked candidates, "
        f"score_source={provenance.get('score_source')}, "
        f"iterations_run={provenance.get('iterations_run')}")
    return attempt, result, scored, fingerprint, provenance


# ==========================================================================
# 4) §G — THE EXACT ENLARGED SEMANTIC-INDEX SOURCE-OBJECT SET
# ==========================================================================


def enlarged_source_object_uris(
    answer_facts, candidate_objects_by_uri: Mapping[str, Mapping],
    *, alias_policy=None,
) -> tuple[str, ...]:
    """Every counterpart URI this run reasons about, sorted and deduplicated.

    THIS SET IS THE CACHE KEY, so it must be exactly the set the classifier will
    see and nothing else. It is the union of

      * every object of an Answer fact — including the INELIGIBLE ones, because
        `levels_for_candidates()` classifies every fact it is given and only the
        kernel filters on `eligible`; an index that omitted them would leave
        those pairs unresolved for no reason; and
      * every object each candidate records under a predicate-direction key the
        Answer also uses — `O_d(κ)` for the κ that actually get classified.

    Candidate objects under keys the Answer never uses are deliberately EXCLUDED:
    the classifier only ever looks up `O_d(κ)` for the Answer's own κ, so
    indexing the rest would enlarge the digest without changing a single verdict,
    and would make the cache key depend on facts the run never consults.

    IN and OUT are never merged. κ is `(predicate_uri, direction)` throughout, so
    an object observed under `(p, OUT)` cannot leak into `(p, IN)`.

    ``alias_policy`` (Prompt 8H-B2-G §5) widens the key set to the audited
    predicate-slot alias families, and ONLY to those. It must be the SAME policy
    the classifier will run under: the digest is the cache key, so an index
    built without the aliases would omit exactly the objects the aliased lookup
    then asks about, and every one of those pairs would come back
    `UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE` for no reason. Passing ``None`` — the
    default — reproduces the pre-B2-G key set byte for byte.
    """
    keys = {fact.predicate_direction_key for fact in answer_facts}
    if alias_policy is not None and getattr(alias_policy, "enabled", False):
        keys = {alias
                for key in tuple(keys)
                for alias in alias_policy.keys_for(key)}
    uris = {fact.counterpart_uri for fact in answer_facts}
    for observed in candidate_objects_by_uri.values():
        for key, objects in observed.items():
            if key in keys:
                uris.update(objects)
    return tuple(sorted(uris))


def write_source_object_list(path: str | Path, uris: Sequence[str]) -> str:
    """Write the deterministic sorted source-object list and return its SHA-256.

    The digest returned is of the FILE. It is a reproducibility artefact for a
    human reader and is deliberately NOT the cache key's
    `source_object_list_sha256`, which `semantic_relations.source_object_list_sha256()`
    computes over the URI sequence itself. Both are recorded so neither has to be
    trusted on its word.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(uri + "\n" for uri in uris)
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ==========================================================================
# 5) SMALL SHARED HELPERS
# ==========================================================================


def sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def candidate_roster_digest(scored) -> str:
    """A digest of the COMPLETE ranked pool, for `candidate_roster_sha256`.

    Covers rank, canonical URI and score together, so a re-ranked or re-scored
    roster gets a different digest even when it holds the same URIs. `repr` of
    the float is deliberate: it round-trips exactly, where a formatted score
    would collapse two genuinely different scores into one digest.
    """
    payload = "\n".join(f"{c.rank}\t{c.canonical_uri}\t{repr(c.score)}"
                        for c in scored)
    return sha256_of_text(payload)


def open_live_retrieval(
    *,
    cache_path: str | Path,
    endpoint: str = DBPEDIA_ENDPOINT,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    redirect_batch_size: int = DEFAULT_REDIRECT_BATCH_SIZE,
    transport: object = None,
) -> tuple[ClassMemberRetriever, SparqlRedirectSource, CachedPageFetcher, PageCache]:
    """Cache-first live retrieval, using the frozen client and cache unchanged.

    `transport` is a seam for tests, exactly as `classes.mapping_run` uses it:
    production passes None and gets `RequestsHttpTransport`. Every page that
    comes back is stored in the normal SQLite cache in the normal format, so the
    run is replayable offline afterwards and a query failure, a successful
    zero-result and a cache hit remain three distinguishable states.
    """
    cache = PageCache(cache_path, endpoint=endpoint)
    client = SparqlPageClient(
        transport=transport if transport is not None else RequestsHttpTransport(),
        endpoint=endpoint,
        max_attempts=max_attempts,
    )
    fetcher = CachedPageFetcher(cache=cache, client=client, endpoint=endpoint)
    retriever = ClassMemberRetriever(
        fetcher=fetcher, page_size=page_size, max_pages=max_pages)
    redirects = SparqlRedirectSource(fetcher=fetcher, batch_size=redirect_batch_size)
    return retriever, redirects, fetcher, cache


def open_offline_retrieval(
    *, cache_path: str | Path, endpoint: str = DBPEDIA_ENDPOINT,
    page_size: int = DEFAULT_PAGE_SIZE, max_pages: int = DEFAULT_MAX_PAGES,
    redirect_batch_size: int = DEFAULT_REDIRECT_BATCH_SIZE,
) -> tuple[ClassMemberRetriever, SparqlRedirectSource, CachedPageFetcher, PageCache]:
    """Strict-offline replay: `client=None`, so a cache miss RAISES.

    Because `CachedPageFetcher` is the only path to a page, "this replay made
    zero HTTP calls" is a property of the object graph rather than a claim about
    which branches happened to run.
    """
    cache = PageCache(cache_path, endpoint=endpoint)
    fetcher = CachedPageFetcher(cache=cache, client=None, endpoint=endpoint)
    retriever = ClassMemberRetriever(
        fetcher=fetcher, page_size=page_size, max_pages=max_pages)
    redirects = SparqlRedirectSource(fetcher=fetcher, batch_size=redirect_batch_size)
    return retriever, redirects, fetcher, cache


def write_csv(path: str | Path, columns: Sequence[str], rows) -> Path:
    """LF-terminated CSV, so the bytes do not depend on the platform."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns),
                                lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in columns})
    return path


def write_json(path: str | Path, payload) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_jsonl(path: str | Path, records) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
    return path
