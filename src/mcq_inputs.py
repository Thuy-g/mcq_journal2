"""Frozen-record ``AnswerCase`` adapter for Journal 2 — Phase B1, step 1.

WHY THIS MODULE EXISTS
----------------------
``src/mcq_core.py`` is the frozen mathematical selection kernel, and it derives
**none** of its input fields from a raw Answer URI. It imports only
``__future__``, ``dataclasses``, ``itertools``, ``math`` and ``typing``; it never
opens a triple store, never tests object equality, never consults a semantic
index, never derives an empirical single-valued rule, never detects a URL or
media predicate, never detects lexical leakage and never looks up a
verbalization template. It receives an ``AnswerCase`` whose per-candidate
evidence levels and per-fact quality fields are **already decided**, and consumes
them as opaque attributes.

Somebody has to discharge that upstream obligation. This module is the first and
smallest instalment: it discharges it for the Answers whose levels and quality
fields were already computed and written to disk by the frozen Prompt-8D ranking
run and the frozen Prompt-8F-R1 evidence run. It reads exactly two files, it
**decides nothing**, and it validates everything before the kernel is allowed to
see the result.

WHAT THIS MODULE MUST NEVER BECOME
----------------------------------
It is not the place for KG access, evidence classification, quality assessment,
leakage detection, semantic closure, class selection or LRoleSim computation.
Those stay upstream, in their own frozen modules, and their outputs arrive here
as records. Equally, none of the validation below may migrate into
``mcq_core.py``: the kernel stays the small selection kernel, and the input
contract is enforced by its caller.

THE NINE INVARIANTS — and what breaks scientifically without each one
---------------------------------------------------------------------
They are ``docs/context/PHASE_B_INPUT_CONTRACT.md`` §7, in order. Every one of
them raises. Nothing is clamped, defaulted, repaired or truncated, because a
clamped input produces a kernel result that is arithmetically valid and
scientifically meaningless.

1. **Aligned per-candidate tuples.** ``levels``, ``exclusion_bases`` and
   ``granularity_risks`` must each have exactly ``len(candidates)`` entries.
   A short tuple silently re-points every evidence level at the wrong candidate,
   so the published rationale would justify distractors it was never computed
   against. This is the worst silent corruption available here, which is why
   ``zip()`` is never used to pair candidates with per-candidate rows.
2. **Allowed vocabularies.** An unknown level would raise a ``KeyError`` deep
   inside the kernel's ``LEVEL_STRENGTH`` lookup, or — worse, if it ever gained a
   strength — would enter the objective as a level nobody defined.
3. **No invalid level/basis combination.** ``L0 + SCOPED_EMPIRICAL`` would attach
   a single-valued annotation to a *snapshot absence*, i.e. claim empirical
   support for something never observed; ``L2 + NONE`` would report a verified
   exclusion with no exclusion basis at all. Both are machine-checked here.
4. **Contiguous unique ranks, unique URIs.** Objective key 5 sums the ranks and
   ``build_case()`` sorts by them; a gap or a duplicate makes the bounded pool's
   "top m of the frozen ranking" no longer the top m.
5. **The pinned LRoleSim execution path.** ``ranker_name``, ``measure``,
   ``lrolesim_beta``, ``iterations`` and ``iteration_mode`` must be exactly the
   five frozen values. Journal 2 *applies* LRoleSim as a structural plausibility
   ranker; a different beta or a different iteration mode is a different ranker
   wearing the same field names.
6. **Exact candidate alignment.** The candidate URIs the evidence records were
   classified against must be exactly the candidate URIs of the roster, and each
   record's own ``candidate_rank`` must agree with the roster's rank. Otherwise
   the levels are aligned to a pool that no longer exists.
7. **The Answer is never its own candidate.** An Answer that ranks itself could
   be selected as a distractor of itself.
8. **No legacy Overlap ranking.** ``src/selection/legacy_overlap.py`` exists and
   is a protected frozen source. Populating ``Candidate.rank`` or
   ``Candidate.score`` from it would silently replace the paper's ranker with a
   different measure while keeping the same field names. The frozen records carry
   no dedicated "ranking provenance" flag, so this invariant is enforced as the
   contrapositive of invariant 5 — the pinned LRoleSim path must be recorded —
   plus an explicit rejection of any ranker or measure naming a legacy overlap
   measure.
9. **The selected class and its approval status are recorded.** See the
   PROVENANCE LIMITATION note below: the class URI and the *position within the
   human-approved class list* are both recorded in the frozen files; the literal
   approval token is not, and this module does not invent one.

PROVENANCE LIMITATION FOUND WHILE IMPLEMENTING INVARIANT 9
-----------------------------------------------------------
The two frozen input files record:

* ``selected_class_uri`` on the Prompt-8D handoff record, and the same class URI
  again as ``scope`` on every Prompt-8F-R1 evidence record (this module requires
  the two to agree);
* ``graph_stage_status`` and ``mapping_stage_status``, whose values name the
  **position in the human-approved class list** that the run actually used
  (``…_SELECTED_PREFERRED``, ``…_SELECTED_FALLBACK_1``, ``…_SELECTED_FALLBACK_2``)
  and whose failure value is literally ``NO_…_FEASIBLE_APPROVED_CLASS``.

They do **not** record the approval token itself. ``approval_status`` (the value
``HUMAN_APPROVED_FOR_ENGINEERING_PILOT``), ``approval_date`` and
``source_reconciliation_sha256`` live in ``data/pilot_class_policy_v1.csv``,
which is a third file and is therefore outside this step's two-file input
contract. So invariant 9 is enforced here as far as the frozen records allow —
the class is recorded, the two files agree on it, and the run reports that it
selected a named position of the approved list — and no approval value is
manufactured. Reading the policy file is a decision for the human author.

TERMINOLOGY — the authority is ``docs/context/EVIDENCE_TAXONOMY_V1.md``
------------------------------------------------------------------------
This module **reads** evidence levels. It never derives one, and it never
rewrites one.

``NOT_COVERED``
    The candidate *supports* the Answer proposition, so the fact distinguishes
    nobody at that position.
``L0``
    Snapshot **absence only**: the pinned snapshot records no object at all for
    the candidate under the same predicate and the same direction. It is not
    negation, not real-world exclusion, and never showable to a student as a
    reason.
``L1``
    An **observed alternative value** under the same predicate and direction. It
    does *not* establish that the predicate cannot also hold the Answer's object
    for that candidate: many DBpedia infobox properties (``almaMater``,
    ``influences``, ``knownFor``) are multi-valued, so ``o ∉ O_d(κ)`` observed
    alongside some ``o′`` is consistent with ``p(d, o)`` being true and merely
    undocumented.
``L2``
    Verified exclusion, requiring a machine-checkable proof. **No L2 rule is
    implemented anywhere in this project**, and the pilot contains zero L2
    incidences; zero is the correct offline outcome, not a gap. The vocabulary
    accepts ``L2`` only so that a future, separately approved rule would not need
    this file changed.

``SCOPED_EMPIRICAL`` is an annotation on an existing L1, never a fourth level.
``CLOSURE_RAN`` on a frozen record means **only that the semantic check
executed** — it is not a statement that a semantic relation was found — and this
module neither reads it nor acts on it.

Open-world reminder, carried through everything below::

    (d, p, o) ∉ K   does NOT imply   ¬p(d, o)

DIRECTION IS PART OF THE FACT IDENTITY
--------------------------------------
``(predicate_uri, direction, counterpart_uri)`` is the canonical fact identity
and ``(predicate_uri, direction)`` is ``κ``. ``dbp:influences`` IN and
``dbp:influences`` OUT are two different relations with different extensions and
different verbalizations, so they are never merged and never share a dictionary
key. Six of the nine R1 pilot rationale facts are IN. This module preserves the
direction it reads and never groups by predicate alone.

OFFLINE BY CONSTRUCTION
-----------------------
Imports are ``json``, ``pathlib``, ``typing`` and ``mcq_core``. No network, no
SPARQL client, no embedding model, no NLP toolkit, no pinned-KG load, and no
import of any test module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from mcq_core import AnswerCase, AnswerFact, Candidate, FactQuality, build_case

# --------------------------------------------------------------------------
# Frozen vocabularies and pinned parameters
# --------------------------------------------------------------------------

# Invariant 5. These five values are the frozen LRoleSim execution path of the
# Prompt-8D run. They are hard constants rather than configuration on purpose: a
# run that quietly used another beta or another iteration mode would not be the
# ranker the paper describes, and a configurable default is exactly how such a
# substitution goes unnoticed.
PINNED_LROLESIM_EXECUTION: dict[str, object] = {
    "ranker_name": "lrolesim_m1_fixed_k3",
    "measure": "lrolesim_ed",
    "lrolesim_beta": 0.2,
    "iterations": 3,
    "iteration_mode": "fixed",
}

# Invariant 8. No frozen field says "this ranking came from LRoleSim rather than
# from the legacy Overlap measure", so the check is the contrapositive of
# invariant 5 plus this explicit token rejection. A legacy Overlap ranking must
# never populate Candidate.rank or Candidate.score.
LEGACY_RANKER_TOKENS = ("overlap",)

# Invariant 2. The three per-candidate axes, with the vocabularies of
# EVIDENCE_TAXONOMY_V1.md. Level and exclusion basis are SEPARATE AXES: no
# annotation may move a fact between levels.
ALLOWED_EVIDENCE_LEVELS = frozenset({"NOT_COVERED", "L0", "L1", "L2"})
ALLOWED_EXCLUSION_BASES = frozenset({"NONE", "SCOPED_EMPIRICAL", "FORMAL_PROOF"})
ALLOWED_GRANULARITY_RISKS = frozenset({
    "NONE",
    "CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT",
    "UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE",
})

# Invariant 3. L0 + SCOPED_EMPIRICAL would annotate a snapshot absence with an
# empirical single-valued observation it cannot have; L2 + NONE would report a
# verified exclusion with no basis. Both stay machine-checked.
FORBIDDEN_LEVEL_BASIS_COMBINATIONS = (("L0", "SCOPED_EMPIRICAL"), ("L2", "NONE"))

# Invariant 9. The closed vocabulary of class-selection outcomes that mean "a
# named position of the human-approved class list was used". Everything else —
# including NO_GRAPH_FEASIBLE_APPROVED_CLASS, the Sulfuric acid outcome — is
# refused rather than interpreted.
APPROVED_CLASS_STAGE_STATUSES: dict[str, frozenset[str]] = {
    "graph_stage_status": frozenset({
        "GRAPH_SELECTED_PREFERRED",
        "GRAPH_SELECTED_FALLBACK_1",
        "GRAPH_SELECTED_FALLBACK_2",
    }),
    "mapping_stage_status": frozenset({
        "MAPPING_SELECTED_PREFERRED",
        "MAPPING_SELECTED_FALLBACK_1",
        "MAPPING_SELECTED_FALLBACK_2",
    }),
}

# The record shapes this adapter requires. Spelled out so that a missing field is
# reported by name instead of surfacing as a KeyError from somewhere deeper.
ANSWER_FACT_EVIDENCE = "answer_fact_evidence"
RANKING_RECORD_FIELDS = (
    "answer_uri", "display_label", "selected_class_uri", "ranked_candidates",
    "ranked_candidate_count", "ready_for_rationale_selection",
    "graph_stage_status", "mapping_stage_status",
    *PINNED_LROLESIM_EXECUTION,
)
RANKED_CANDIDATE_FIELDS = ("rank", "score", "canonical_candidate_uri")
EVIDENCE_RECORD_FIELDS = (
    "answer_uri", "fact_index", "candidate_count", "scope", "quality",
    "per_candidate",
)
PER_CANDIDATE_FIELDS = (
    "candidate_uri", "candidate_rank", "evidence_level", "exclusion_basis",
    "granularity_risk",
)
# The eleven already-computed per-fact attributes of FactQuality. This adapter
# copies all eleven and recomputes none of them.
FACT_QUALITY_FIELDS = (
    "predicate_uri", "direction", "counterpart_uri", "display_label", "eligible",
    "soft_leak", "verbalizable", "pedagogical_tier", "label_length",
    "token_count", "template_id",
)


# --------------------------------------------------------------------------
# Errors — three types, so a caller can tell the three situations apart
# --------------------------------------------------------------------------


class FrozenInputError(Exception):
    """Base class for every failure of this adapter."""


class AnswerNotFoundError(FrozenInputError):
    """No frozen records exist for the requested Answer.

    This is the honest outcome for any Answer the frozen runs never processed —
    Albert Einstein is the worked example. It is a *failure*, deliberately, and
    never a quietly empty ``AnswerCase``: fabricating candidates, scores or
    evidence levels for an Answer that has none would produce an MCQ whose
    numbers came from nowhere.
    """


class InputContractError(FrozenInputError):
    """A Phase-B input invariant was violated. Never clamped, never repaired."""


# --------------------------------------------------------------------------
# Reading the two frozen files
# --------------------------------------------------------------------------


def read_jsonl(path: Path) -> list[dict]:
    """Every JSON object in a JSONL file, in file order.

    A malformed line is an error naming the line number, not a skipped record: a
    silently dropped fact would shrink the rationale search space without
    anything in the output saying so.
    """
    rows: list[dict] = []
    for number, line in enumerate(Path(path).read_text("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise FrozenInputError(f"{path}: line {number} is not valid JSON: {error}") from error
    return rows


def require_fields(record: Mapping, fields: Iterable[str], where: str) -> None:
    """Reject a record missing any required field, naming the missing fields."""
    missing = [name for name in fields if name not in record]
    if missing:
        raise InputContractError(f"{where}: missing required field(s) {missing}")


def frozen_answer_uris(*, handoff_path: Path, evidence_path: Path) -> tuple[str, ...]:
    """The Answers that have BOTH a frozen ranking record and frozen evidence.

    A caller can use this to ask "is this Answer available?" without provoking
    ``AnswerNotFoundError``. It is an inventory of what the frozen runs produced,
    never a list of Answers this module could produce records for.
    """
    ranked = {row.get("answer_uri") for row in read_jsonl(handoff_path)}
    classified = {row.get("answer_uri") for row in read_jsonl(evidence_path)
                  if row.get("record_type") == ANSWER_FACT_EVIDENCE}
    return tuple(sorted(uri for uri in ranked & classified if uri))


def find_ranking_record(
    ranking_rows: Sequence[dict],
    answer_uri: str,
    source: str = "the frozen Prompt-8D candidate ranking handoff",
) -> dict:
    """The one Prompt-8D handoff record for this Answer, or a clear failure."""
    matches = [row for row in ranking_rows if row.get("answer_uri") == answer_uri]
    if not matches:
        raise AnswerNotFoundError(
            f"no frozen records for {answer_uri} in {source}: this adapter reads "
            f"frozen records only and will not fabricate candidates, LRoleSim "
            f"scores or evidence levels for an Answer that has none")
    if len(matches) > 1:
        raise InputContractError(
            f"{source}: {len(matches)} ranking records for {answer_uri}, expected 1")
    return matches[0]


def find_evidence_records(
    evidence_rows: Sequence[dict],
    answer_uri: str,
    source: str = "the frozen Prompt-8F-R1 evidence audit",
) -> list[dict]:
    """Every ``answer_fact_evidence`` record for this Answer, or a clear failure.

    Other record types in the same file — ``scoped_empirical_rule``,
    ``semantic_relation``, ``combination_search`` — are upstream working notes and
    are deliberately not read here.
    """
    records = [row for row in evidence_rows
               if row.get("record_type") == ANSWER_FACT_EVIDENCE
               and row.get("answer_uri") == answer_uri]
    if not records:
        raise AnswerNotFoundError(
            f"no frozen records for {answer_uri} in {source}: this adapter reads "
            f"frozen records only and will not fabricate evidence levels, "
            f"exclusion bases or granularity risks for an Answer that has none")
    return records


# --------------------------------------------------------------------------
# Validation of the frozen provenance (invariants 5, 8 and 9)
# --------------------------------------------------------------------------


def validate_lrolesim_provenance(ranking_row: Mapping) -> None:
    """Invariants 5 and 8: the pinned execution path, and no Overlap ranking.

    No similarity is recomputed anywhere in Phase B — Journal 2 applies LRoleSim
    as a frozen structural plausibility ranker and LRoleSim produces no
    rationale — so the only defence against a substituted ranking is to require
    the recorded execution path to be exactly the pinned one.
    """
    require_fields(ranking_row, RANKING_RECORD_FIELDS, "Prompt-8D ranking record")
    # Invariant 8 is tested BEFORE invariant 5, even though a legacy ranker name
    # would also fail the pinned-path equality below. A substituted ranker is a
    # scientifically distinct failure from a mistyped beta, and the reviewer must
    # be told which one happened rather than reading "expected lrolesim_m1…".
    for name in ("ranker_name", "measure"):
        text = str(ranking_row[name]).casefold()
        for token in LEGACY_RANKER_TOKENS:
            if token in text:
                raise InputContractError(
                    f"invariant 8 (no legacy Overlap ranking): {name}="
                    f"{ranking_row[name]!r} names a legacy overlap measure; a "
                    f"legacy Overlap ranking must never populate Candidate.rank "
                    f"or Candidate.score")
    observed = {name: ranking_row[name] for name in PINNED_LROLESIM_EXECUTION}
    if observed != PINNED_LROLESIM_EXECUTION:
        raise InputContractError(
            f"invariant 5 (pinned LRoleSim execution path): expected "
            f"{PINNED_LROLESIM_EXECUTION}, found {observed}")


def validate_class_provenance(
    ranking_row: Mapping, evidence_records: Sequence[Mapping]
) -> None:
    """Invariant 9: the selected class, and the approval position, are recorded.

    See the module docstring's PROVENANCE LIMITATION note. What is checkable from
    the two frozen files is checked: the class URI is present, the evidence
    records were classified against that same class, the run reports a named
    position of the human-approved class list, and the Answer was actually ready
    for rationale selection. The literal approval token lives in a third file and
    is neither read nor invented here.
    """
    class_uri = ranking_row["selected_class_uri"]
    if not isinstance(class_uri, str) or not class_uri:
        raise InputContractError(
            f"invariant 9 (selected class recorded): selected_class_uri="
            f"{class_uri!r} is not a non-empty URI")
    for name, allowed in APPROVED_CLASS_STAGE_STATUSES.items():
        if ranking_row[name] not in allowed:
            raise InputContractError(
                f"invariant 9 (approval status recorded): {name}="
                f"{ranking_row[name]!r} is not one of {sorted(allowed)}, so this "
                f"pool was not reported as drawn from a named position of the "
                f"human-approved class list")
    if ranking_row["ready_for_rationale_selection"] is not True:
        raise InputContractError(
            f"invariant 9 (approval status recorded): "
            f"ready_for_rationale_selection="
            f"{ranking_row['ready_for_rationale_selection']!r}, so this Answer was "
            f"not handed over for rationale selection")
    scopes = {record.get("scope") for record in evidence_records}
    if scopes != {class_uri}:
        raise InputContractError(
            f"invariant 9 (selected class recorded): the evidence records were "
            f"classified against scope(s) {sorted(map(str, scopes))} but the "
            f"ranking record selected {class_uri}")


# --------------------------------------------------------------------------
# The candidate roster (invariants 4 and 7)
# --------------------------------------------------------------------------


def candidates_from_ranking(ranking_row: Mapping) -> tuple[Candidate, ...]:
    """The COMPLETE ranked candidate pool, in frozen LRoleSim rank order.

    This is not a top-k slice. The kernel's anonymity denominator and its
    ``original_candidate_count`` both read the complete pool, and the bounded
    pool's ``TOP`` component is literally the first *m* positions of it.

    ``rank`` and ``score`` are copied from the frozen Prompt-8D run; nothing here
    recomputes, rescales or re-sorts a similarity.
    """
    candidates: list[Candidate] = []
    for row in ranking_row["ranked_candidates"]:
        require_fields(row, RANKED_CANDIDATE_FIELDS, "ranked_candidates entry")
        uri = row["canonical_candidate_uri"]
        score = row["score"]
        if not isinstance(uri, str) or not uri:
            raise InputContractError(
                f"invariant 4 (unique candidate URIs): candidate URI {uri!r} is "
                f"not a non-empty string")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise InputContractError(
                f"invariant 5 (frozen LRoleSim score): score {score!r} of {uri} "
                f"is not a number")
        candidates.append(Candidate(rank=row["rank"], score=score, uri=uri))

    ranks = sorted(candidate.rank for candidate in candidates)
    if ranks != list(range(1, len(candidates) + 1)):
        raise InputContractError(
            f"invariant 4 (contiguous unique ranks): ranks {ranks} are not 1..n "
            f"for n = {len(candidates)}")
    uris = [candidate.uri for candidate in candidates]
    if len(set(uris)) != len(uris):
        raise InputContractError(
            "invariant 4 (unique candidate URIs): the ranking repeats a candidate")
    if ranking_row["answer_uri"] in set(uris):
        raise InputContractError(
            f"invariant 7 (the Answer is not its own candidate): "
            f"{ranking_row['answer_uri']} appears in its own candidate pool")
    if len(candidates) != ranking_row["ranked_candidate_count"]:
        raise InputContractError(
            f"invariant 4 (complete ranked candidate pool): "
            f"{len(candidates)} ranked_candidates but ranked_candidate_count="
            f"{ranking_row['ranked_candidate_count']}")
    return tuple(sorted(candidates, key=lambda candidate: candidate.rank))


# --------------------------------------------------------------------------
# The Answer facts (invariants 1, 2, 3 and 6)
# --------------------------------------------------------------------------


def validate_fact_alignment(fact: AnswerFact, candidate_count: int, where: str) -> None:
    """Invariant 1: the three per-candidate tuples are aligned to the roster.

    Kept as its own function, and called on every fact this module builds, so the
    alignment guarantee can also be asserted directly on a fact that arrived from
    somewhere else. A tuple of the wrong length means every level after the first
    divergence describes a different candidate than the one it is read against.
    """
    lengths = (len(fact.levels), len(fact.exclusion_bases),
               len(fact.granularity_risks))
    if lengths != (candidate_count, candidate_count, candidate_count):
        raise InputContractError(
            f"invariant 1 (aligned per-candidate tuples) for {where}: "
            f"levels/exclusion_bases/granularity_risks have lengths {lengths}, "
            f"expected {candidate_count} each")


def answer_fact_from_record(
    record: Mapping, candidate_uris: Sequence[str]
) -> AnswerFact:
    """One ``AnswerFact``, rebuilt from one frozen ``answer_fact_evidence`` record.

    The three per-candidate tuples are built by **looking each candidate URI up**
    in the record's ``per_candidate`` rows, in roster order. They are never built
    by zipping two sequences together: ``zip()`` stops at the shorter one, so a
    record missing a candidate would produce a short, silently misaligned tuple
    instead of an error. Invariant 6 additionally requires each row's own
    ``candidate_rank`` to agree with the roster position, which catches a file
    that was re-ranked after classification.

    The eleven ``FactQuality`` fields are copied verbatim. ``eligible`` in
    particular is a HARD FILTER decided upstream (raw layout slots, external-URL
    and media objects, Answer-label leakage); it is never re-derived here, and it
    is never softened into a penalty.
    """
    require_fields(record, EVIDENCE_RECORD_FIELDS, "answer_fact_evidence record")
    quality = record["quality"]
    where = (f"fact_index {record['fact_index']} of {record['answer_uri']} "
             f"({quality.get('predicate_uri')} {quality.get('direction')})")
    require_fields(quality, FACT_QUALITY_FIELDS, f"quality of {where}")

    rows_by_uri: dict[str, Mapping] = {}
    for row in record["per_candidate"]:
        require_fields(row, PER_CANDIDATE_FIELDS, f"per_candidate row of {where}")
        if row["candidate_uri"] in rows_by_uri:
            raise InputContractError(
                f"invariant 6 (exact candidate alignment) for {where}: candidate "
                f"{row['candidate_uri']} appears twice in per_candidate")
        rows_by_uri[row["candidate_uri"]] = row
    if set(rows_by_uri) != set(candidate_uris):
        missing = sorted(set(candidate_uris) - set(rows_by_uri))
        extra = sorted(set(rows_by_uri) - set(candidate_uris))
        raise InputContractError(
            f"invariant 6 (exact candidate alignment) for {where}: "
            f"missing {missing}, unexpected {extra}")
    if record["candidate_count"] != len(candidate_uris):
        raise InputContractError(
            f"invariant 1 (aligned per-candidate tuples) for {where}: "
            f"candidate_count={record['candidate_count']} but the roster has "
            f"{len(candidate_uris)} candidates")

    levels: list[str] = []
    bases: list[str] = []
    risks: list[str] = []
    for position, uri in enumerate(candidate_uris):
        row = rows_by_uri[uri]
        level = row["evidence_level"]
        basis = row["exclusion_basis"]
        risk = row["granularity_risk"]
        # The three axes are checked against their own vocabulary and never
        # against each other's: an exclusion basis is not a weaker level, and a
        # granularity risk is not a level at all.
        for axis, value, allowed in (
                ("evidence_level", level, ALLOWED_EVIDENCE_LEVELS),
                ("exclusion_basis", basis, ALLOWED_EXCLUSION_BASES),
                ("granularity_risk", risk, ALLOWED_GRANULARITY_RISKS)):
            if value not in allowed:
                raise InputContractError(
                    f"invariant 2 (allowed vocabularies) for {where}: {axis}="
                    f"{value!r} of {uri} is not in {sorted(allowed)}")
        if (level, basis) in FORBIDDEN_LEVEL_BASIS_COMBINATIONS:
            raise InputContractError(
                f"invariant 3 (forbidden level/basis combination) for {where}: "
                f"{level} + {basis} for {uri} is invalid by "
                f"EVIDENCE_TAXONOMY_V1.md §4")
        if row["candidate_rank"] != position + 1:
            raise InputContractError(
                f"invariant 6 (exact candidate alignment) for {where}: {uri} is "
                f"rank {position + 1} in the roster but the evidence record "
                f"records candidate_rank={row['candidate_rank']}")
        levels.append(level)
        bases.append(basis)
        risks.append(risk)

    fact = AnswerFact(
        quality=FactQuality(
            predicate_uri=quality["predicate_uri"],
            direction=quality["direction"],
            counterpart_uri=quality["counterpart_uri"],
            display_label=quality["display_label"],
            eligible=quality["eligible"],
            soft_leak=quality["soft_leak"],
            verbalizable=quality["verbalizable"],
            pedagogical_tier=quality["pedagogical_tier"],
            label_length=quality["label_length"],
            token_count=quality["token_count"],
            template_id=quality["template_id"],
        ),
        levels=tuple(levels),
        exclusion_bases=tuple(bases),
        granularity_risks=tuple(risks),
    )
    validate_fact_alignment(fact, len(candidate_uris), where)
    return fact


# --------------------------------------------------------------------------
# The public entry points
# --------------------------------------------------------------------------


def case_from_records(
    answer_uri: str,
    ranking_row: Mapping,
    evidence_records: Sequence[Mapping],
) -> AnswerCase:
    """Build one ``AnswerCase`` from records already read into memory.

    Split out from :func:`case_from_frozen_records` so that the nine invariants
    can be exercised on a deliberately corrupted copy of a real record without
    writing a temporary file. The file-reading entry point below adds nothing but
    the two reads.

    The ``AnswerCase`` is always built through ``mcq_core.build_case()``, never by
    calling the dataclass constructor: ``build_case()`` re-sorts candidates into
    the canonical ``(rank, uri)`` order, permutes every fact's per-candidate
    tuples the same way and derives ``eligible_fact_indices``, so two callers
    holding the same information in different orders produce byte-identical
    output. Constructing ``AnswerCase`` directly would bypass that
    canonicalisation and is a contract violation.
    """
    if ranking_row.get("answer_uri") != answer_uri:
        raise InputContractError(
            f"ranking record is for {ranking_row.get('answer_uri')!r}, not {answer_uri!r}")
    for record in evidence_records:
        require_fields(record, EVIDENCE_RECORD_FIELDS, "answer_fact_evidence record")
        if record["answer_uri"] != answer_uri:
            raise InputContractError(
                f"evidence record is for {record['answer_uri']!r}, not {answer_uri!r}")
    # Fact order is the frozen fact_index order, so a rebuilt rationale reports
    # the same fact indices as the R1 run it is being regressed against.
    ordered = sorted(evidence_records, key=lambda record: record["fact_index"])
    if [record["fact_index"] for record in ordered] != list(range(len(ordered))):
        raise InputContractError(
            f"fact_index values for {answer_uri} are not unique and contiguous "
            f"from 0: {[record['fact_index'] for record in ordered]}")

    validate_lrolesim_provenance(ranking_row)
    validate_class_provenance(ranking_row, ordered)
    candidates = candidates_from_ranking(ranking_row)
    candidate_uris = tuple(candidate.uri for candidate in candidates)
    facts = tuple(answer_fact_from_record(record, candidate_uris) for record in ordered)

    display_label = ranking_row["display_label"]
    if not isinstance(display_label, str) or not display_label:
        raise InputContractError(
            f"display_label {display_label!r} for {answer_uri} is not a non-empty "
            f"string; the label a learner sees must preserve parentheses, Roman "
            f"numerals and diacritics exactly")
    return build_case(answer_uri, display_label, candidates, facts)


def case_from_frozen_records(
    answer_uri: str,
    *,
    handoff_path: Path,
    evidence_path: Path,
) -> AnswerCase:
    """Build one AnswerCase from frozen records whose candidate ranking,
    evidence levels and fact-quality fields have already been computed.

    ``handoff_path`` is the Prompt-8D ``candidate_ranking_handoff.jsonl``: it
    supplies ``display_label`` and the complete ranked candidate pool with its
    frozen LRoleSim ``rank`` and ``score``.

    ``evidence_path`` is the Prompt-8F-R1 ``evidence_audit_v3_r1.jsonl``: its
    ``answer_fact_evidence`` records supply the eleven ``FactQuality`` fields and,
    per candidate, the already-decided ``evidence_level``, ``exclusion_basis`` and
    ``granularity_risk``.

    Nothing is recomputed: not LRoleSim, not evidence levels, not quality fields,
    not leakage, not semantic relations, not the set cover, not the class
    selection. The nine input invariants are asserted, and then
    ``mcq_core.build_case()`` is called.

    Raises ``AnswerNotFoundError`` when the frozen runs never processed this
    Answer, and ``InputContractError`` when they did but the records violate the
    input contract.
    """
    ranking_row = find_ranking_record(read_jsonl(handoff_path), answer_uri, str(handoff_path))
    evidence_records = find_evidence_records(read_jsonl(evidence_path), answer_uri,
                                             str(evidence_path))
    return case_from_records(answer_uri, ranking_row, evidence_records)
