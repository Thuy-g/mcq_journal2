############################################################################
# src/pipeline/phase_b2_any_answer_run.py
#
# Prompt 8H-B2-D orchestration: ANY Answer, or a whole Answers.txt batch, end
# to end — with no per-Answer input file and no pre-computed class ranking.
#
#   AnswerIdentity  (original / remote query / pinned local URI)
#     -> automatic v6 class ranking          (Wikipedia lead + standard IDF)
#     -> complete class-member retrieval     (live SPARQL, cached)
#     -> mapping into the pinned local KG    (local-mapping gate >= 10)
#     -> M1 graph admission                  (frozen policy)
#     -> frozen Journal-2 LRoleSim           (lrolesim_ed / beta 0.2 / k=3 fixed)
#     -> COMPLETE ranked candidate pool
#     -> exact enlarged semantic-index source-object set
#     -> per-Answer semantic-index rebuild
#     -> mcq_inputs.build_and_select()       (frozen Phase-B kernel)
#
# WHAT THIS MODULE OWNS AND WHAT IT REFUSES TO OWN
# ------------------------------------------------
# It owns three things and nothing else:
#
#   1. the ADAPTER from the v6 selector's ranking to the shape the frozen
#      local-mapping walk already consumes;
#   2. the SUMMARY of an evidence matrix the kernel already produced;
#   3. a deterministic per-Answer semantic-index PATH.
#
# Every scientific decision belongs somewhere else and is delegated unchanged:
#
#   answer identity            -> classes.answer_identity
#   class ranking / leakage    -> category_extractor_v6 (+ classes.class_leakage)
#   member retrieval, redirects, local mapping
#                              -> classes.member_mapper
#   graph admission and order  -> pipeline.candidate_order, graph_lrolesim_run
#   LRoleSim ranking           -> pipeline.graph_lrolesim_run.rank_graph
#   semantic index build       -> pipeline.rationale_v3_run
#   evidence, set cover, objective
#                              -> mcq_inputs + mcq_core
#
# The §E walk itself is `phase_b2_answer_run.walk_ranked_classes_for_local_mapping`
# called unmodified. Prompt 8H-B2-B's driver script is not touched and remains
# historical evidence of that run.
#
# WHY THE ANSWER IS HANDED TO EVERY LOCAL STAGE BY ITS PINNED-KG URI
# -------------------------------------------------------------------
# `walk_ranked_classes_for_local_mapping` looks the Answer up in the pinned
# `url_index` and refuses to proceed without a node, and `map_class_members`
# excludes the Answer by comparing LOCAL INDICES. Both therefore need the
# March-2023 spelling, not the current one. Handing them the current spelling of
# an entity that has been renamed since the dump produces two failures at once:
# the walk cannot find an Answer node, and — if it could — the Answer would be
# admitted as its own distractor because its historical URI never string-matches
# the roster's current URI. The class QUERIES, by contrast, need the CURRENT
# spelling, because the historical resource carries no dcterms:subject triples
# on today's endpoint. That is why the identity record keeps three URIs and why
# this module reads a different one at each stage.
#
# WHY "BEST AVAILABLE EVIDENCE LEVEL" IS A SUMMARY AND NOT A NEW SEMANTICS
# -------------------------------------------------------------------------
# An evidence level is a property of an ORDERED PAIR (Answer fact, candidate).
# It is never a property of a candidate on its own. A candidate can be L1 under
# one fact, L0 under a second and NOT_COVERED under a third, all at once. The
# researcher's request to see "the evidence level of all distractors" is
# therefore answered with a per-candidate PROFILE — the strongest level any
# eligible fact supplies, plus the incidence counts at each level — computed by
# projecting the matrix the frozen classifier already built. Nothing here
# classifies, upgrades, downgrades or rescues anything, and the complete matrix
# is retained alongside the summary so the projection is never lossy in the
# artifacts.
#
# WHY THE SEMANTIC INDEX IS REBUILT PER ANSWER
# ---------------------------------------------
# `SemanticIndexCacheKey` includes `source_object_list_sha256`, the digest of the
# exact set of counterpart URIs the run reasons about. Two Answers have
# different sets, so one shared index file would either fail its key check for
# every Answer but one, or — if the check were bypassed — classify one Answer's
# pairs against another Answer's containment facts. The path therefore carries
# BOTH the Answer and the digest, which makes a wrong reuse impossible rather
# than merely unlikely.
#
# WHY A FAILED ANSWER STAYS IN THE DENOMINATOR
# ---------------------------------------------
# Every yield number this project reports is a fraction whose denominator is the
# Answers attempted. An Answer that produced no selection is a MEASUREMENT of
# the method's coverage, not an error to be filtered out of the table; dropping
# it would silently inflate every rate computed from the batch.
#
# IMPORT-TIME PURITY: no network, no pickle load, no model load, no file write.
############################################################################

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import category_extractor_v6 as v6                                # noqa: E402
from classes.answer_identity import (                             # noqa: E402
    AnswerIdentity,
    IdentityStatus,
)
from mcq_core import LEVEL_STRENGTH                               # noqa: E402
from pipeline import phase_b2_answer_run as b2                    # noqa: E402

__all__ = [
    "ANY_ANSWER_SCHEMA_VERSION",
    "AnswerStatus",
    "MAIN_CORPUS_POLICIES",
    "CandidateEvidenceProfile",
    "AnswerRunResult",
    "ranked_classes_from_v6",
    "summarise_candidate_evidence",
    "candidate_fact_evidence_rows",
    "answer_slug",
    "semantic_index_path",
    "class_approval_status",
    "summary_table",
    "prose_summary",
]

ANY_ANSWER_SCHEMA_VERSION = "phase_b2_any_answer_v2"

#: The evidence policies whose rationale may be SHOWN TO A STUDENT. `diagnostic-l0`
#: is deliberately absent: L0 is snapshot ABSENCE, and under the open-world
#: assumption "DBpedia does not record it" is not a reason a distractor is wrong.
MAIN_CORPUS_POLICIES = frozenset({"strict-l2", "main-l1"})

#: The complete per-Answer status vocabulary. Every batch row carries exactly one
#: of these, and every one of them keeps the Answer in the denominator.
class AnswerStatus:
    SUCCESS_FULL_EXACT = "SUCCESS_FULL_EXACT"
    SUCCESS_POOL_EXACT = "SUCCESS_POOL_EXACT"
    NO_CURRENT_DBPEDIA_CATEGORIES = "NO_CURRENT_DBPEDIA_CATEGORIES"
    NO_USABLE_CLASS = "NO_USABLE_CLASS"
    NO_LOCAL_URI_IDENTITY = "NO_LOCAL_URI_IDENTITY"
    AMBIGUOUS_LOCAL_ALIAS = "AMBIGUOUS_LOCAL_ALIAS"
    NO_LOCALLY_MAPPING_FEASIBLE_CLASS = "NO_LOCALLY_MAPPING_FEASIBLE_CLASS"
    GRAPH_INFEASIBLE = "GRAPH_INFEASIBLE"
    SEMANTIC_INDEX_UNAVAILABLE = "SEMANTIC_INDEX_UNAVAILABLE"
    NO_MAIN_L1_SELECTION = "NO_MAIN_L1_SELECTION"
    NO_VALID_FINAL_COMBINATION = "NO_VALID_FINAL_COMBINATION"
    QUERY_FAILED = "QUERY_FAILED"
    INPUT_INVALID = "INPUT_INVALID"
    IDF_UNIVERSE_UNAVAILABLE = "IDF_UNIVERSE_UNAVAILABLE"

    #: Statuses that mean a distractor triple and a rationale exist.
    SUCCEEDED = frozenset({SUCCESS_FULL_EXACT, SUCCESS_POOL_EXACT})


def class_approval_status(alpha: float) -> str:
    """What `class_approval_status` carries into `mcq_inputs.build_and_select()`.

    `validate_run_provenance` requires a non-empty string and deliberately does
    not constrain its VALUE, so that a later frozen class-selection procedure can
    report its own status. This one says exactly what happened and claims nothing
    more: the class came from the AUTOMATIC v6 ranking at a declared alpha and
    then passed the declared local-mapping gate. It is NOT `HUMAN_APPROVED` —
    no human worksheet decision exists for an arbitrary Answer, and inventing one
    would be a synthetic class approval.
    """
    alpha_token = f"{float(alpha):g}".replace(".", "P")
    return (f"AUTOMATIC_V6_RANKING_ALPHA_{alpha_token}"
            "_FIRST_LOCAL_MAPPING_FEASIBLE_NOT_HUMAN_APPROVED")


# ==========================================================================
# 1) The adapter: a v6 ranking in the frozen walk's own input shape
# ==========================================================================


def ranked_classes_from_v6(ranking: v6.AnswerRanking) -> tuple[b2.RankedClass, ...]:
    """Express a v6 `AnswerRanking` as the `RankedClass` tuple the walk consumes.

    A pure re-labelling. Every number is COPIED from the selector's output: no
    IDF, no SBERT similarity, no combined score and no leakage verdict is
    recomputed here, because a second implementation of the class-selection
    science could drift from the first.

    The ORDER is the selector's own — descending `combined_score`, then ascending
    `category_uri` — and is preserved exactly. Re-sorting on a float that has
    been serialised and re-parsed can reorder a tie differently from the run that
    produced it.

    HARD-leaking classes never appear: the selector rejected them before scoring,
    so they are not in the feasible ranking at all. That is the point of the
    leakage gate, and this module relies on it rather than re-testing leakage.

    `raw_sbert` / `normalized_sbert` may be `None` when no semantic text or
    encoder was available. The frozen dataclass annotates them as `float`, which
    Python does not enforce; carrying `None` through is deliberate, because
    substituting 0.0 would make "no semantic feature exists" indistinguishable
    from "the encoder measured no similarity".
    """
    ranked: list[b2.RankedClass] = []
    for entry in ranking.ranked:
        feature = entry.feature
        short = feature.category_uri.rsplit("/", 1)[-1]
        ranked.append(b2.RankedClass(
            rank=entry.feasible_rank,
            class_uri=feature.category_uri,
            class_short=short,
            display_label=feature.category_label,
            remote_count=int(feature.remote_count or 0),
            eligible_remote_count=int(feature.eligible_remote_count or 0),
            raw_idf=float(feature.raw_idf or 0.0),
            normalized_idf=float(entry.normalized_idf),
            raw_sbert=feature.raw_sbert,                     # may be None
            normalized_sbert=entry.normalized_sbert,         # may be None
            combined_score=float(entry.combined_score),
            leak_level=feature.leak_level.value,
            leak_source=feature.leak_source,
            leak_evidence=";".join(feature.leak_evidence),
        ))
    return tuple(ranked)


# ==========================================================================
# 2) The evidence PROFILE of every ranked candidate
# ==========================================================================


@dataclass(frozen=True)
class CandidateEvidenceProfile:
    """The complete evidence profile of ONE candidate, over ALL eligible facts.

    A projection of the frozen per-(fact, candidate) matrix, never a new
    classification. `best_available_evidence_level` is the strongest level any
    eligible Answer fact supplies for this candidate; it does not assert that the
    candidate is "an L1 candidate", because no such property exists.

    Both an ELIGIBLE view and an ALL-FACTS view are kept. The eligible view is
    what the kernel may build a rationale from; the all-facts view is what a
    reviewer needs in order to see whether the hard filter removed something that
    would otherwise have discriminated.
    """

    rank: int
    uri: str
    score: float
    best_available_evidence_level: str
    l2_incidences: int
    l1_incidences: int
    l0_incidences: int
    not_covered_incidences: int
    eligible_fact_count: int
    student_showable_fact_count: int          # eligible facts reaching L1 or L2
    best_level_over_all_facts: str
    all_facts_l2: int
    all_facts_l1: int
    all_facts_l0: int
    all_facts_not_covered: int

    def as_record(self) -> dict:
        return {
            "lrolesim_rank": self.rank,
            "candidate_uri": self.uri,
            "lrolesim_score": repr(self.score),
            "best_available_evidence_level": self.best_available_evidence_level,
            "l2_incidences": self.l2_incidences,
            "l1_incidences": self.l1_incidences,
            "l0_incidences": self.l0_incidences,
            "not_covered_incidences": self.not_covered_incidences,
            "eligible_rationale_fact_count": self.eligible_fact_count,
            "student_showable_l1_plus_fact_count": self.student_showable_fact_count,
            "best_level_over_all_facts": self.best_level_over_all_facts,
            "all_facts_l2_incidences": self.all_facts_l2,
            "all_facts_l1_incidences": self.all_facts_l1,
            "all_facts_l0_incidences": self.all_facts_l0,
            "all_facts_not_covered_incidences": self.all_facts_not_covered,
            "note": ("An evidence level is a property of an ordered "
                     "(Answer fact, candidate) pair. These are SUMMARIES over "
                     "that matrix, not a level the candidate holds on its own."),
        }


def _strongest(levels: Sequence[str]) -> str:
    """The strongest level in a sequence, using the kernel's own ordering.

    Empty means there were no facts to look at, which is `NOT_COVERED`: nothing
    discriminates this candidate, which is exactly what NOT_COVERED records.
    """
    if not levels:
        return "NOT_COVERED"
    return max(levels, key=lambda level: LEVEL_STRENGTH[level])


def summarise_candidate_evidence(case) -> tuple[CandidateEvidenceProfile, ...]:
    """One profile per candidate of the COMPLETE ranked pool, in pool order.

    `case.candidates` is the complete admitted pool in canonical `(rank, uri)`
    order, and every fact's `levels` tuple is aligned to that same order by
    `mcq_core.build_case`. Indexing them together is therefore the kernel's own
    alignment and not a re-derivation of it.
    """
    eligible = set(case.eligible_fact_indices)
    profiles: list[CandidateEvidenceProfile] = []
    for position, candidate in enumerate(case.candidates):
        eligible_levels = [case.facts[i].levels[position]
                           for i in range(len(case.facts)) if i in eligible]
        all_levels = [fact.levels[position] for fact in case.facts]
        profiles.append(CandidateEvidenceProfile(
            rank=candidate.rank,
            uri=candidate.uri,
            score=candidate.score,
            best_available_evidence_level=_strongest(eligible_levels),
            l2_incidences=eligible_levels.count("L2"),
            l1_incidences=eligible_levels.count("L1"),
            l0_incidences=eligible_levels.count("L0"),
            not_covered_incidences=eligible_levels.count("NOT_COVERED"),
            eligible_fact_count=len(eligible_levels),
            student_showable_fact_count=sum(
                1 for level in eligible_levels if LEVEL_STRENGTH[level]
                >= LEVEL_STRENGTH["L1"]),
            best_level_over_all_facts=_strongest(all_levels),
            all_facts_l2=all_levels.count("L2"),
            all_facts_l1=all_levels.count("L1"),
            all_facts_l0=all_levels.count("L0"),
            all_facts_not_covered=all_levels.count("NOT_COVERED"),
        ))
    return tuple(profiles)


def candidate_fact_evidence_rows(case) -> list[dict]:
    """The COMPLETE per-(fact, candidate) matrix, unsummarised.

    Written whenever an artifacts directory is enabled, so that the profile above
    is a convenience and never the only surviving form of the measurement.
    """
    rows: list[dict] = []
    eligible = set(case.eligible_fact_indices)
    for fact_index, fact in enumerate(case.facts):
        for position, candidate in enumerate(case.candidates):
            rows.append({
                "fact_index": fact_index,
                "fact_eligible": fact_index in eligible,
                "predicate_uri": fact.quality.predicate_uri,
                "direction": fact.quality.direction,
                "counterpart_uri": fact.quality.counterpart_uri,
                "counterpart_display_label": fact.quality.display_label,
                "candidate_lrolesim_rank": candidate.rank,
                "candidate_uri": candidate.uri,
                "evidence_level": fact.levels[position],
                "exclusion_basis": fact.exclusion_bases[position],
                "granularity_risk": fact.granularity_risks[position],
            })
    return rows


# ==========================================================================
# 3) A deterministic per-Answer semantic-index path
# ==========================================================================

_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def answer_slug(uri: str, *, limit: int = 72) -> str:
    """A filesystem-safe, deterministic slug from a URI's local name.

    Used for artifact directory names and for the semantic-index filename. It is
    a LABEL, never an identity: two different URIs could in principle slugify
    alike, which is exactly why the semantic-index filename also carries the
    source-object-set digest.
    """
    local = str(uri).rstrip("/").rsplit("/", 1)[-1]
    slug = _SLUG_UNSAFE.sub("_", local).strip("_") or "answer"
    return slug[:limit]


#: Kept as a private alias so existing internal call sites read unchanged.
_slug = answer_slug


def semantic_index_path(root: str | Path, answer_uri: str,
                        source_object_list_sha256: str) -> Path:
    """``<root>/<answer-slug>__<source-set-digest>.json``.

    BOTH components are load-bearing. The slug makes the file readable and keeps
    two Answers apart; the digest of the exact source-object set makes a wrong
    reuse impossible even between two runs of the SAME Answer whose candidate
    pools differ — because a different pool means a different set of counterpart
    URIs, a different cache key, and therefore a different file.

    This replaces the B2-B driver's single Einstein-specific filename, which
    could only ever be correct for one Answer.
    """
    digest = str(source_object_list_sha256)[:16]
    return Path(root) / f"{_slug(answer_uri)}__{digest}.json"


def source_set_fingerprint(uris: Sequence[str]) -> str:
    """SHA-256 over the sorted URI sequence, for a manifest that must not lie."""
    payload = "\n".join(uris)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ==========================================================================
# 4) One Answer's complete result
# ==========================================================================


@dataclass
class AnswerRunResult:
    """Everything one Answer produced, successful or not.

    A FAILED Answer gets a fully populated record too: `status` says what
    happened and `detail` says why, and both stay in the batch table. That is
    what keeps the denominator honest.
    """

    original_uri: str
    cohort: Optional[str] = None
    status: str = AnswerStatus.INPUT_INVALID
    detail: str = ""
    identity: Optional[AnswerIdentity] = None
    display_label: str = ""

    # class selection
    alpha: Optional[float] = None
    scoring_mode: Optional[str] = None
    categories_discovered: int = 0
    feasible_class_count: int = 0
    rejected_class_count: int = 0
    class_ranking: tuple = ()
    class_attempts: tuple = ()
    selected_class_uri: Optional[str] = None
    selected_class_rank: Optional[int] = None
    mapped_candidate_count: Optional[int] = None

    # graph + LRoleSim
    graph_outcome: Optional[str] = None
    graph_row: Mapping[str, Any] = field(default_factory=dict)
    lrolesim_provenance: Mapping[str, Any] = field(default_factory=dict)
    run_fingerprint: Optional[str] = None
    complete_pool_size: int = 0
    scored: tuple = ()

    # semantic index
    semantic_source_count: int = 0
    semantic_source_digest: Optional[str] = None
    semantic_index_path: Optional[str] = None
    semantic_index_available: Optional[bool] = None
    semantic_index_unavailable_reason: Optional[str] = None

    # selection
    case: Any = None
    selection: Any = None
    record: Mapping[str, Any] = field(default_factory=dict)
    evidence_profiles: tuple[CandidateEvidenceProfile, ...] = ()

    # provenance
    sparql_stats: Mapping[str, Any] = field(default_factory=dict)
    fetcher_stats: Mapping[str, Any] = field(default_factory=dict)
    seconds: float = 0.0

    @property
    def succeeded(self) -> bool:
        return self.status in AnswerStatus.SUCCEEDED

    @property
    def evidence_policy(self) -> Optional[str]:
        return None if self.selection is None else self.selection.evidence_policy

    @property
    def has_main_l1_selection(self) -> bool:
        """A student-showable selection under the frozen policy order.

        True only for `strict-l2` or `main-l1`. A `diagnostic-l0` selection is a
        real, reportable result and is NOT student-showable, because L0 is
        snapshot absence and absence is not falsity.
        """
        return self.evidence_policy in MAIN_CORPUS_POLICIES

    @property
    def mcq_evidence_level(self) -> Optional[str]:
        return None if self.selection is None else self.selection.mcq_evidence_level

    @property
    def search_scope(self) -> Optional[str]:
        return None if self.selection is None else self.selection.search_scope

    def summary_record(self) -> dict:
        selection = self.selection
        rationale = None if selection is None else selection.rationale
        identity = self.identity
        return {
            "original_uri": self.original_uri,
            "cohort": self.cohort,
            "display_label": self.display_label,
            "status": self.status,
            "detail": self.detail,
            "remote_query_uri": None if identity is None else identity.remote_query_uri,
            "local_kg_uri": None if identity is None else identity.local_kg_uri,
            "local_index": None if identity is None else identity.local_index,
            "local_resolution_method": (None if identity is None
                                        else identity.local_resolution_method),
            "remote_redirect_status": (None if identity is None
                                       else identity.remote_redirect_status),
            "alpha": self.alpha,
            "categories_discovered": self.categories_discovered,
            "feasible_class_count": self.feasible_class_count,
            "selected_class_uri": self.selected_class_uri,
            "selected_class_rank": self.selected_class_rank,
            "mapped_candidate_count": self.mapped_candidate_count,
            "graph_outcome": self.graph_outcome,
            "complete_ranked_pool_size": self.complete_pool_size,
            "semantic_index_available": self.semantic_index_available,
            "evidence_policy": self.evidence_policy,
            "mcq_evidence_level": self.mcq_evidence_level,
            "search_scope": self.search_scope,
            "minimum_rationale_size": (None if selection is None
                                       else selection.minimum_rationale_size),
            "minimum_rationale_level": (None if selection is None
                                        else selection.minimum_rationale_level),
            "granularity_risk_incidences": (None if rationale is None
                                            else rationale.granularity_risk_incidences),
            "scoped_empirical_incidences": (None if rationale is None
                                            else rationale.scoped_empirical_incidences),
            "local_candidate_pool_anonymity_count":
                (None if rationale is None
                 else rationale.local_candidate_pool_anonymity_count),
            "local_candidate_pool_anonymity_denominator":
                (None if selection is None else self.complete_pool_size + 1),
            "local_candidate_pool_anonymity_ratio":
                (None if rationale is None
                 else rationale.local_candidate_pool_anonymity_ratio),
            "direct_identifier_flag": (None if rationale is None
                                       else rationale.direct_identifier_flag),
            "has_main_l1_selection": self.has_main_l1_selection,
            "distractor_uris": ("" if selection is None else
                                ";".join(d.uri for d in selection.distractors)),
            "distractor_ranks": ("" if selection is None else
                                 ";".join(str(d.rank) for d in selection.distractors)),
            "seconds": round(self.seconds, 3),
        }


# ==========================================================================
# 5) The batch summary table
# ==========================================================================


def _short(uri: Optional[str], limit: int = 34) -> str:
    if not uri:
        return "-"
    local = str(uri).rstrip("/").rsplit("/", 1)[-1]
    local = local.split("Category:")[-1].replace("_", " ")
    return local if len(local) <= limit else local[: limit - 1] + "…"


def _answer_cell(result: AnswerRunResult, limit: int = 26) -> str:
    """The Answer column: the ORIGINAL input spelling, plus the resolved one.

    The original is the immutable audit identity and is what the researcher's
    input file contains, so it leads. When the pinned local KG holds the entity
    under a different name the resolved spelling is appended after an arrow, so
    a reader can see at a glance both which row of the input this is and which
    entity was actually reasoned about.
    """
    original = _short(result.original_uri, limit)
    identity = result.identity
    if identity is None or not identity.local_kg_uri:
        return original
    resolved = _short(identity.local_kg_uri, limit)
    return original if resolved == original else f"{original} → {resolved}"


def _rationale_cell(result: AnswerRunResult, limit: int = 46) -> str:
    """The selected minimum rationale, spelled predicate -> object per fact."""
    selection = result.selection
    if selection is None or result.case is None:
        return "-"
    parts = []
    for index in selection.rationale.fact_indices:
        quality = result.case.facts[index].quality
        predicate = quality.predicate_uri.rsplit("/", 1)[-1]
        arrow = "->" if quality.direction == "OUT" else "<-"
        parts.append(f"{predicate} {arrow} {_short(quality.counterpart_uri, 22)}")
    text = "; ".join(parts) + f" (|R*|={selection.minimum_rationale_size})"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _per_distractor_cell(result: AnswerRunResult) -> str:
    """Best level reached under the SELECTED rationale, one per distractor."""
    selection = result.selection
    if selection is None:
        return "-"
    return "|".join(selection.rationale.per_candidate_best_level[position]
                    for position in range(len(selection.distractors)))


def _basis_cell(result: AnswerRunResult) -> str:
    """Exclusion bases actually present under the selected rationale.

    Summarised, never presented as a level: `SCOPED_EMPIRICAL` is an exclusion
    BASIS on a separate axis and is not a fourth evidence level.
    """
    selection, case = result.selection, result.case
    if selection is None or case is None:
        return "-"
    bases = set()
    for index in selection.rationale.fact_indices:
        for position in selection.positions:
            bases.add(case.facts[index].exclusion_bases[position])
    return "/".join(sorted(bases)) or "NONE"


def summary_table(results: Sequence[AnswerRunResult]) -> str:
    """The compact Markdown batch table. EVERY Answer gets a row.

    Column meanings, stated once so a reader never has to guess:

    * **Answer** — the ORIGINAL input spelling, followed by `→ resolved` when the
      pinned local KG holds the entity under a different name.
    * **Cands** — the size of the COMPLETE graph-feasible LRoleSim ranked pool,
      not the bounded search pool the kernel may have enumerated over.
    * **Distractors (rank)** — the three selected candidates with their ranks in
      that complete pool.
    * **Per-distractor** — the best level each distractor reaches under the
      SELECTED minimum rationale, in distractor order.
    * **MCQ** — the frozen `mcq_evidence_level` from the kernel.
    * **Basis** — exclusion bases present under the selected rationale.
    * **Sem.** — semantic-index status for this Answer's exact source-object set.
    * **Risk** — the frozen `granularity_risk_incidences` of the selected
      rationale.
    * **Anon** — `count / (1 + complete ranked pool size)`; the denominator is
      the Answer plus the COMPLETE pool.
    * **Main** — ✔ only when a student-showable L1+ selection exists.
    """
    header = ("| # | Answer | Status | Class | Cands | Distractors (rank) | "
              "Rationale (|R*|) | Per-distractor | MCQ | Basis | Sem. | Risk | "
              "Anon | Main |")
    rule = "|" + "---|" * 14
    lines = [header, rule]
    for number, result in enumerate(results, start=1):
        selection = result.selection
        distractors = ("-" if selection is None else
                       ", ".join(f"{_short(d.uri, 20)} ({d.rank})"
                                 for d in selection.distractors))
        rationale = None if selection is None else selection.rationale
        anonymity = ("-" if rationale is None else
                     f"{rationale.local_candidate_pool_anonymity_count}/"
                     f"{result.complete_pool_size + 1}")
        semantic = ("-" if result.semantic_index_available is None
                    else ("AVAILABLE" if result.semantic_index_available
                          else "UNAVAILABLE"))
        lines.append(
            f"| {number} "
            f"| {_answer_cell(result)} "
            f"| {result.status} "
            f"| {_short(result.selected_class_uri, 30)} "
            f"| {result.complete_pool_size or '-'} "
            f"| {distractors} "
            f"| {_rationale_cell(result)} "
            f"| {_per_distractor_cell(result)} "
            f"| {result.mcq_evidence_level or '-'} "
            f"| {_basis_cell(result)} "
            f"| {semantic} "
            f"| {'-' if rationale is None else rationale.granularity_risk_incidences} "
            f"| {anonymity} "
            f"| {'✔' if result.has_main_l1_selection else '-'} |")
    return "\n".join(lines)


def prose_summary(results: Sequence[AnswerRunResult]) -> str:
    """The counts a reader needs to interpret the table, with the denominator.

    Failures are counted, named and kept in the total. No rate reported here is
    computed over a filtered subset.
    """
    total = len(results)
    succeeded = [r for r in results if r.succeeded]
    full_exact = [r for r in succeeded if r.status == AnswerStatus.SUCCESS_FULL_EXACT]
    pool_exact = [r for r in succeeded if r.status == AnswerStatus.SUCCESS_POOL_EXACT]
    l2 = [r for r in results if r.mcq_evidence_level == "MCQ-L2"]
    l1 = [r for r in results if r.mcq_evidence_level == "MCQ-L1"]
    l0 = [r for r in results if r.mcq_evidence_level == "MCQ-L0"]
    no_selection = [r for r in results if r.selection is None]
    identifiers = [r for r in results
                   if r.selection is not None
                   and r.selection.rationale.direct_identifier_flag]

    failures: dict[str, int] = {}
    for result in results:
        if not result.succeeded:
            failures[result.status] = failures.get(result.status, 0) + 1

    anonymity = sorted(r.selection.rationale.local_candidate_pool_anonymity_count
                       for r in results if r.selection is not None)

    def median(values):
        if not values:
            return None
        middle = len(values) // 2
        if len(values) % 2:
            return values[middle]
        return (values[middle - 1] + values[middle]) / 2

    lines = [
        f"Total Answers attempted            : {total}",
        f"Successful (distractors selected)  : {len(succeeded)}",
        f"  FULL_EXACT                       : {len(full_exact)}",
        f"  POOL_EXACT                       : {len(pool_exact)}",
        f"MCQ-L2                             : {len(l2)}",
        f"MCQ-L1                             : {len(l1)}",
        f"Diagnostic L0 only (not showable)  : {len(l0)}",
        f"No selection at any policy         : {len(no_selection)}",
        f"Direct-identifier rationales       : {len(identifiers)}",
    ]
    if anonymity:
        lines.append(
            f"Local anonymity count (of 1+pool)  : "
            f"median {median(anonymity):g}, min {anonymity[0]}, "
            f"max {anonymity[-1]}")
    else:
        lines.append("Local anonymity count              : not applicable "
                     "(no Answer produced a selection)")
    lines.append("Failure reasons (all remain in the denominator):")
    if failures:
        for status in sorted(failures):
            lines.append(f"  {status:<38} {failures[status]}")
    else:
        lines.append("  (none)")
    lines += [
        "",
        "L0 is snapshot ABSENCE and is never shown to a student as a reason: "
        "under the open-world assumption a missing triple is not a false fact.",
        "A FULL_EXACT result is exact over the COMPLETE ranked candidate pool of "
        "the selected class; a POOL_EXACT result is exact only within the bounded "
        "pool the kernel searched. Neither is a claim about DBpedia as a whole, "
        "and the selected class is the FIRST locally mapping-feasible class of an "
        "automatic ranking, never a globally optimal class.",
    ]
    return "\n".join(lines)
