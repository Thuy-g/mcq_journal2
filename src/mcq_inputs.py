"""Journal 2 Phase-B input adapter: frozen ``AnswerCase`` records (B1.1), the
Answer's own observed facts read from the pinned local KG (B1.2), the aligned
per-(fact, candidate) evidence axes obtained from the frozen R1 classifier
(B1.3), and the thin orchestration that connects those to the frozen Phase-A2
selection kernel (B1.4).

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

Somebody has to discharge that upstream obligation. This module discharges it in
three instalments.

**B1.1 — frozen records.** For the Answers whose levels and quality fields were
already computed and written to disk by the frozen Prompt-8D ranking run and the
frozen Prompt-8F-R1 evidence run, this module reads exactly two files, it
**decides nothing**, and it validates everything before the kernel is allowed to
see the result. That is everything down to :func:`case_from_frozen_records`.

**B1.2 — the Answer's own facts, for an Answer the frozen runs never processed.**
:func:`answer_facts_from_local_kg` reconstructs the complete one-hop observed
fact inventory of one Answer from the already-loaded pinned local KG and attaches
the frozen R1 fact-quality/Answer-leakage fields to each fact. That is a strictly
per-Answer step: it is the half of the upstream obligation that needs no
candidate roster.

**B1.3 — the other half, which needs one.** :func:`levels_for_candidates` takes
those Answer facts together with an already-ranked candidate roster, gathers each
candidate's observed objects ``O_d(κ)`` under exactly the same
predicate-direction key from the same pinned graph, and hands every
(Answer fact, candidate) pair to the frozen R1
``classify_fact_against_candidate()``. The three verdicts it returns — evidence
level, exclusion basis, granularity risk — are copied onto an ``AnswerFact`` and
aligned to the ranked candidate order. Not one of them is decided here.

**B1.4 — putting the four owners in a row.** :func:`build_and_select` validates
the supplied roster and its provenance, calls B1.2, calls B1.3, calls
``mcq_core.build_case()`` and calls ``mcq_core.select_distractors()``. It states
no scientific rule at all: every step it performs already has exactly one owner,
and the search scope, the set cover, the rationale ranking and the six-key
objective remain entirely the kernel's. See the B1.4 section comment at the
bottom of this file for why a roster needs provenance it cannot carry itself, and
why a run with no selection is a measurement rather than a failure to repair.

WHAT THIS MODULE MUST NEVER BECOME
----------------------------------
It is not the place for evidence *rules*, quality *policy*, leakage *rules*,
semantic closure, class selection or LRoleSim computation. Those stay upstream,
in their own frozen modules, and their outputs arrive here as records or as
function calls into the frozen implementation — B1.2 calls
``rationale_v3.quality.assess_fact_quality()`` and B1.3 calls
``rationale_v3.evidence.classify_fact_against_candidate()``, and neither
reimplements any part of what it calls. In particular B1.3 does **not** re-run,
re-tune or second-guess the B1.2 quality verdict: ``FactQuality.eligible`` is the
frozen R1 hard filter and is consumed as already decided.

The KG access added in B1.2 is deliberately narrow: this module never opens,
builds, repairs or caches a local-KG file. It receives an **already-loaded**
graph object and an **already-loaded** quality policy as arguments, reads one
node's one-hop edges through the frozen ``selection.observed_facts`` enumeration,
and stops there. Resolving, verifying and loading the pinned graph stays in
``kg.loader``, where the "never rebuild, never fall back to the network" rules
already live.

Equally, none of the validation below may migrate into ``mcq_core.py``: the
kernel stays the small selection kernel, and the input contract is enforced by
its caller.

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
This module **reads** evidence levels in B1.1 and **obtains** them in B1.3 by
calling the frozen R1 classifier. It never states an evidence rule of its own, and
it never rewrites a level it was given.

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
    currently activated in the frozen offline policy, and the pilot contains zero
    L2 incidences. The upstream R1 layer contains generic EvidenceProof/L2-proof
    machinery, but no trustworthy L2 proof source/rule is active for the current
    DBpedia-infobox experiment.** Zero is therefore the correct offline outcome,
    not a gap. The vocabulary accepts ``L2`` only so that a future, separately
    approved rule would not need this file changed.

``SCOPED_EMPIRICAL`` is an annotation on an existing L1, never a fourth level.
``CLOSURE_RAN`` means **only that the semantic check executed** — it is not a
statement that a semantic relation was found. It is a fourth axis,
``semantic_check_status``, which is not an ``AnswerCase`` field: this module
neither reads it from a frozen record nor copies it out of a classification, and
what it does carry from an unavailable check is the granularity risk
``UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE``, which never moves a level.

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
Imports are ``json``, ``math``, ``pathlib``, ``typing``, ``mcq_core`` and the
five frozen offline helpers this module delegates to — the R1 quality assessor,
the R1 URI normalizer and the Prompt-8D one-hop edge enumeration for B1.2, plus
the R1 proposition type and the R1 evidence classifier for B1.3. B1.4 adds no
import beyond ``math`` and three more names from the frozen kernel it already
imported. No network, no SPARQL
client, no embedding model, no NLP toolkit, no WordNet, no LLM, no file-format
parser of its own, and no import of any test module. The semantic index and the
evidence rulebook are **arguments**, never built here: constructing either one
requires the traversal policy, the cache key and the scope derivation that belong
upstream, and inventing a local substitute for either would be the single easiest
way to silently reclassify the whole pilot.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from mcq_core import (
    DEFAULT_POOL_POLICY,
    DEFAULT_RATIONALE_OBJECTIVE,
    AnswerCase,
    AnswerFact,
    Candidate,
    FactQuality,
    PoolPolicy,
    Selection,
    build_case,
    canonical_record,
    select_distractors,
)
# The three frozen upstream behaviours B1.2 reuses instead of reimplementing.
# `assess_fact_quality` IS the R1 hard eligibility filter and the R1 deterministic
# Answer-leakage rule; `normalize_uri` is the exact URI normalization R1 applied
# before assessing a fact, so the two agree on fact identity; `observed_edge_set`
# and `DIRECTION_LABEL` are the corrected Prompt-8D one-hop enumeration, whose
# cache identity already includes the graph's SHA-256 and the IN/OUT flag.
from rationale_v3.quality import assess_fact_quality
from rationale_v3.semantic_relations import normalize_uri
from selection.observed_facts import DIRECTION_LABEL, observed_edge_set
# The two frozen upstream behaviours B1.3 reuses instead of reimplementing.
# `RationaleProposition` IS the R1 proposition object — the assertion that an
# entity stands in relation κ = (predicate_uri, direction) to the claim object —
# and it validates its own URIs and qualifier state on construction.
# `classify_fact_against_candidate` IS the single place in this project where an
# evidence level is decided: it runs the R1 support test before any rule, applies
# the R1 semantic index, applies the supplied rulebook, and returns the level,
# the exclusion basis and the granularity risk together. B1.3 calls it once per
# (Answer fact, candidate) pair and copies its three verdicts; it reproduces none
# of its decision tree, because a second copy of a scientific rule is a second
# rule that can drift from the first.
from rationale_v3.contracts import RationaleProposition
from rationale_v3.evidence import classify_fact_against_candidate
# Prompt 8H-B2-G §5. An OPTIONAL, versioned predicate-slot alias layer used for
# EVIDENCE LOOKUP ONLY. The default is the empty policy, under which
# `observed_objects_for_key()` is literally `observed.get(key, ())` and every
# caller that existed before B2-G is unchanged. Under an active policy the
# CANDIDATE's observed object set is unioned across an audited alias family in
# the same direction, so `dbp:field` and `dbp:fields` stop producing a false
# absence. Raw predicates, raw provenance and the pinned KG are never rewritten.
from rationale_v3.predicate_aliases import (
    NO_ALIAS_POLICY,
    PredicateAliasPolicy,
    observed_objects_for_key,
)

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
    """The requested Answer has no frozen records, or is not in the pinned KG.

    This is the honest outcome for any Answer the frozen runs never processed —
    Albert Einstein is the worked example. It is a *failure*, deliberately, and
    never a quietly empty ``AnswerCase``: fabricating candidates, scores or
    evidence levels for an Answer that has none would produce an MCQ whose
    numbers came from nowhere.

    B1.2 raises the same error for an Answer URI that is not a node of the pinned
    local KG, for the same reason: an Answer outside the snapshot has no observed
    facts, and an empty fact inventory would be indistinguishable from an Answer
    that genuinely has none.
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


def validate_pinned_lrolesim_execution(source: Mapping) -> None:
    """Invariants 5 and 8 on ANY mapping that claims to record an LRoleSim run.

    Split out of :func:`validate_lrolesim_provenance` in B1.4 so that the two
    callers share one implementation of the same scientific check. B1.1 applies
    it to a frozen Prompt-8D handoff record; B1.4 applies it to the provenance a
    live caller supplies alongside an already-ranked roster. A second copy of
    this check would be a second definition of "which ranker the paper used".
    """
    # Invariant 8 is tested BEFORE invariant 5, even though a legacy ranker name
    # would also fail the pinned-path equality below. A substituted ranker is a
    # scientifically distinct failure from a mistyped beta, and the reviewer must
    # be told which one happened rather than reading "expected lrolesim_m1…".
    for name in ("ranker_name", "measure"):
        text = str(source[name]).casefold()
        for token in LEGACY_RANKER_TOKENS:
            if token in text:
                raise InputContractError(
                    f"invariant 8 (no legacy Overlap ranking): {name}="
                    f"{source[name]!r} names a legacy overlap measure; a "
                    f"legacy Overlap ranking must never populate Candidate.rank "
                    f"or Candidate.score")
    observed = {name: source[name] for name in PINNED_LROLESIM_EXECUTION}
    if observed != PINNED_LROLESIM_EXECUTION:
        raise InputContractError(
            f"invariant 5 (pinned LRoleSim execution path): expected "
            f"{PINNED_LROLESIM_EXECUTION}, found {observed}")


def validate_lrolesim_provenance(ranking_row: Mapping) -> None:
    """Invariants 5 and 8: the pinned execution path, and no Overlap ranking.

    No similarity is recomputed anywhere in Phase B — Journal 2 applies LRoleSim
    as a frozen structural plausibility ranker and LRoleSim produces no
    rationale — so the only defence against a substituted ranking is to require
    the recorded execution path to be exactly the pinned one.
    """
    require_fields(ranking_row, RANKING_RECORD_FIELDS, "Prompt-8D ranking record")
    validate_pinned_lrolesim_execution(ranking_row)


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


def validate_display_label(display_label, answer_uri: str) -> None:
    """The label a learner sees must be a non-empty string.

    Shared by the frozen-record path and by B1.4 so that a blank label cannot
    reach ``build_case()`` from either direction. Nothing here rewrites the
    label: display tokenization preserves parentheses, Roman numerals, digits,
    diacritics and case exactly, and the lossy leakage tokenization is a separate
    pipeline that is never shown to a human.
    """
    if not isinstance(display_label, str) or not display_label:
        raise InputContractError(
            f"display_label {display_label!r} for {answer_uri} is not a non-empty "
            f"string; the label a learner sees must preserve parentheses, Roman "
            f"numerals and diacritics exactly")


def validate_candidate_roster(
    answer_uri: str, candidates: Sequence[Candidate]
) -> None:
    """Invariants 4 and 7 on a roster already expressed as ``Candidate`` objects.

    Split out of :func:`candidates_from_ranking` in B1.4, where a caller supplies
    an already-ranked roster directly instead of a frozen Prompt-8D record. Both
    callers must enforce the same four properties, and one implementation is the
    only way to be sure they do.

    A roster of FEWER THAN THREE candidates is deliberately **not** rejected
    here. Too few same-class candidates is a scientifically meaningful
    feasibility failure of that class, and the frozen kernel reports it by
    returning no selection. Refusing the roster instead would hide the failure,
    and topping it up to three would fabricate distractors.
    """
    for candidate in candidates:
        if not isinstance(candidate.uri, str) or not candidate.uri:
            raise InputContractError(
                f"invariant 4 (unique candidate URIs): candidate URI "
                f"{candidate.uri!r} is not a non-empty string")
        # Objective keys 1 and 2 maximise the score sum and the score minimum
        # with full cardinal precision, so a NaN — which compares false against
        # everything — would silently corrupt both, and an infinity would win
        # every comparison it entered.
        if (isinstance(candidate.score, bool)
                or not isinstance(candidate.score, (int, float))
                or not math.isfinite(candidate.score)):
            raise InputContractError(
                f"invariant 5 (frozen LRoleSim score): score {candidate.score!r} "
                f"of {candidate.uri} is not a finite number")
    ranks = sorted(candidate.rank for candidate in candidates)
    if ranks != list(range(1, len(candidates) + 1)):
        raise InputContractError(
            f"invariant 4 (contiguous unique ranks): ranks {ranks} are not 1..n "
            f"for n = {len(candidates)}")
    uris = [candidate.uri for candidate in candidates]
    if len(set(uris)) != len(uris):
        raise InputContractError(
            "invariant 4 (unique candidate URIs): the ranking repeats a candidate")
    if answer_uri in set(uris):
        raise InputContractError(
            f"invariant 7 (the Answer is not its own candidate): "
            f"{answer_uri} appears in its own candidate pool")


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
        candidates.append(Candidate(rank=row["rank"], score=row["score"],
                                    uri=row["canonical_candidate_uri"]))
    validate_candidate_roster(ranking_row["answer_uri"], candidates)
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
    validate_display_label(display_label, answer_uri)
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


# --------------------------------------------------------------------------
# Phase B1.2 — the Answer's own observed facts, read from the pinned local KG
# --------------------------------------------------------------------------


def node_index_or_none(uri: str, local_kg):
    """The pinned local KG's node index for ``uri``, or ``None``.

    The pinned graph keys its URIs in the angle-bracket spelling ``<http://…>``
    that the graph build wrote, while every frozen record, every policy file and
    every caller spells them plain. Both spellings are tried, bracketed first, so
    a caller never has to know which one a particular build used, and neither
    spelling is silently preferred when only one exists.

    Returning ``None`` rather than raising is deliberate: the two callers below
    report a missing node very differently — a missing Answer is
    ``AnswerNotFoundError``, a missing candidate is an input-contract failure —
    and neither may be reported as "present but with nothing observed".
    """
    for spelling in ("<" + uri + ">", uri):
        index = local_kg.index_for_uri_or_none(spelling)
        if index is not None:
            return index
    return None


def answer_node_index(answer_uri: str, local_kg) -> int:
    """The pinned local KG's node index for ``answer_uri``, or a clear failure."""
    index = node_index_or_none(answer_uri, local_kg)
    if index is not None:
        return index
    raise AnswerNotFoundError(
        f"{answer_uri} is not a node of the pinned local KG, so it has no "
        f"observed one-hop facts there; this module reports that rather than "
        f"returning an empty fact inventory that would look like an Answer with "
        f"genuinely no facts")


def answer_facts_from_local_kg(
    answer_uri: str,
    *,
    local_kg,
    quality_policy,
) -> tuple[FactQuality, ...]:
    """Return every distinct one-hop observed Answer fact with frozen R1 quality.

    No evidence level is assigned here because an evidence level belongs to an
    ordered (Answer fact, candidate) pair, and no candidate roster is available
    in Phase B1.2. Nothing in this function reads, derives or stores a level, an
    exclusion basis or a granularity risk, and it never builds an ``AnswerFact``.

    WHAT IS RETURNED
        The **complete** inventory: every distinct
        ``(predicate_uri, direction, counterpart_uri)`` observed for the Answer
        in the pinned snapshot, ineligible facts included. ``eligible`` is
        reported per fact and nothing is filtered out, because the ineligible
        facts are exactly what a reviewer needs in order to check that the hard
        filter removed the right ones. Ordering is ascending
        ``(predicate_uri, direction, counterpart_uri)``, so two extractions of
        the same Answer from the same graph are identical tuples.

    DIRECTION IS PART OF THE IDENTITY, NEVER MERGED
        ``(Answer, p, x)`` is an OUT fact and ``(x, p, Answer)`` is an IN fact.
        The two are counted, keyed and returned separately even when they share a
        predicate and even when they share a counterpart, because they are
        different relations with different verbalizations. Albert Einstein has 9
        OUT and 57 IN facts, and ``dbp:children`` occurs in both directions.

    NOTHING HERE IS A NEW RULE
        Enumeration is ``selection.observed_facts.observed_edge_set()``, the
        corrected Prompt-8D one-hop edge set whose cache identity includes the
        graph's SHA-256, the node and the IN/OUT flag. Identity normalization is
        the frozen ``normalize_uri()``: strip the bracket spelling, Unicode NFC,
        drop one trailing ``/``. It is applied to the predicate and the
        counterpart because R1 applied it before assessing quality, so without it
        two DBpedia spellings of one URL would be two facts here and one fact
        there. Quality and Answer-leakage come from the frozen
        ``assess_fact_quality()`` — this module contains no leakage threshold, no
        allowlist, no template table and no tier table of its own.

    OPEN WORLD
        Every returned fact is OBSERVED in the pinned snapshot. Absence is not
        recorded, not returned, and not implied to be false.

    ``local_kg`` is an already-loaded graph object (``kg.loader.LocalKG``) and
    ``quality_policy`` an already-loaded ``rationale_v3.quality.QualityPolicy``.
    Both are arguments rather than module state so that this function opens no
    file, verifies no digest and holds no 1.2 GB object alive between calls.
    """
    node = answer_node_index(answer_uri, local_kg)

    identities: set[tuple[str, str, str]] = set()
    for predicate_index, direction_code, counterpart_index in observed_edge_set(
            node, local_kg, use_in=True):
        predicate = local_kg.index_url.get(predicate_index)
        counterpart = local_kg.index_url.get(counterpart_index)
        if predicate is None or counterpart is None:
            # Not URI-valued as far as this snapshot can tell. The frozen
            # Prompt-8D enumeration skipped such an edge rather than emitting a
            # fabricated URI, and this reconstruction must agree with it.
            continue
        identities.add((normalize_uri(predicate),
                        DIRECTION_LABEL[direction_code],
                        normalize_uri(counterpart)))

    facts: list[FactQuality] = []
    # sorted() over the identity set gives both deduplication and the canonical
    # order in one step; a set cannot hold a duplicate identity by construction.
    for predicate_uri, direction, counterpart_uri in sorted(identities):
        assessed = assess_fact_quality(
            answer_uri=answer_uri,
            predicate_uri=predicate_uri,
            direction=direction,
            counterpart_uri=counterpart_uri,
            policy=quality_policy)
        # The eleven fields of mcq_core.FactQuality, copied across from the R1
        # result. `eligible` is R1's derived hard-filter verdict (predicate OK,
        # object OK, no hard Answer leak) and `soft_leak` lives on R1's nested
        # leakage result; the other nine are attribute-for-attribute. No twelfth
        # field is invented and no field is recomputed.
        facts.append(FactQuality(
            predicate_uri=assessed.predicate_uri,
            direction=assessed.direction,
            counterpart_uri=assessed.counterpart_uri,
            display_label=assessed.display_label,
            eligible=assessed.eligible,
            soft_leak=assessed.leakage.soft_leak,
            verbalizable=assessed.verbalizable,
            pedagogical_tier=assessed.pedagogical_tier,
            label_length=assessed.label_length,
            token_count=assessed.token_count,
            template_id=assessed.template_id,
        ))
    return tuple(facts)


# --------------------------------------------------------------------------
# Phase B1.3 — per-(fact, candidate) evidence, delegated to the frozen R1
# --------------------------------------------------------------------------
#
# WHY THIS STEP EXISTS AT ALL
#   B1.2 answers "what does the pinned snapshot record about the Answer?". That
#   question has no candidate in it, so it cannot produce an evidence level: a
#   level is a property of the ORDERED PAIR (Answer fact, candidate) and says how
#   that fact distinguishes the Answer from that candidate. B1.3 supplies the
#   missing half — the candidate's own observations under the same key — and then
#   asks the frozen R1 classifier, which owns the decision.
#
# WHY B1.3 REUSES R1 RATHER THAN REWRITING IT
#   The R1 classifier is the audited implementation behind the published pilot:
#   14,860 classified incidences, an evidence policy file with its own SHA-256, a
#   semantic index with a checked cache key. Re-deriving its decision tree here
#   would create a second implementation of the same science, and the two would
#   agree only until one of them was edited. So this module gathers inputs,
#   delegates, and copies three verdicts. It contains no level rule, no support
#   test, no traversal and no threshold of its own.
#
# WHAT `O_d(κ)` MEANS
#   κ = (predicate_uri, direction) is the predicate-direction key, and `O_d(κ)`
#   is the set of objects the pinned snapshot records for candidate `d` under
#   exactly that key. It is an OBSERVATION about one snapshot, never a claim
#   about the world: DBpedia is open-world, so
#
#       (d, p, o) ∉ K   does NOT imply   ¬p(d, o)
#
# WHY IN AND OUT ARE SEPARATE KEYS
#   `(Answer, p, x)` is an OUT fact and `(x, p, Answer)` is an IN fact. They are
#   different relations with different extensions and different verbalizations —
#   `dbp:influences` OUT is "influenced" and IN is "was influenced by" — so an
#   object observed under `(p, OUT)` must never enter `(p, IN)` or the reverse.
#   Merging them would compare an Answer's out-edge against a candidate's
#   in-edge and report the resulting mismatch as evidence.


def candidate_objects_from_local_kg(candidate_uri: str, *, local_kg) -> dict:
    """``{κ: (object_uri, …)}`` — every ``O_d(κ)`` of one candidate.

    Built once per candidate and reused across every Answer fact, because the
    enumeration is the expensive half and κ is what the classifier looks up.

    WHY A MISSING CANDIDATE NODE RAISES INSTEAD OF BECOMING L0
        "the candidate is absent from the graph" and "the candidate is present
        but records nothing under this key" are two different observations, and
        only the second is `L0`. Returning an empty mapping for an unknown URI
        would silently turn a roster/graph mismatch — a candidate that the local
        mapping stage never admitted — into a page of absence-only evidence
        against every single Answer fact, which is the strongest L0 profile the
        model can produce and would be entirely fabricated. So it is an input
        error, reported with the URI that could not be resolved.

    Enumeration, direction labelling and URI normalization are the same frozen
    helpers B1.2 uses, so the objects gathered here are drawn from exactly the
    same one-hop edge set, under exactly the same identity, as the Answer's own
    facts. A predicate or counterpart index that does not resolve to a URI is not
    URI-valued as far as this snapshot can tell; the frozen Prompt-8D enumeration
    skipped such an edge rather than emitting a fabricated URI, and this
    reconstruction agrees with it.
    """
    node = node_index_or_none(candidate_uri, local_kg)
    if node is None:
        raise InputContractError(
            f"candidate {candidate_uri} is not a node of the pinned local KG, so "
            f"O_d(kappa) cannot be observed for it; this is an input error and "
            f"NOT an empty observed object set, because 'absent from the graph' "
            f"is a different observation from 'present with nothing recorded "
            f"under this key', and only the second one is L0")

    grouped: dict[tuple[str, str], set[str]] = {}
    for predicate_index, direction_code, counterpart_index in observed_edge_set(
            node, local_kg, use_in=True):
        predicate = local_kg.index_url.get(predicate_index)
        counterpart = local_kg.index_url.get(counterpart_index)
        if predicate is None or counterpart is None:
            continue
        # The direction is part of the key, never a field beside it: an OUT
        # object and an IN subject never share a bucket.
        key = (normalize_uri(predicate), DIRECTION_LABEL[direction_code])
        grouped.setdefault(key, set()).add(normalize_uri(counterpart))
    return {key: tuple(sorted(objects)) for key, objects in sorted(grouped.items())}


def levels_for_candidates(
    answer_facts: Sequence[FactQuality],
    candidates: Sequence[Candidate],
    *,
    local_kg,
    semantic_index,
    rulebook,
    scope: str,
    alias_policy: PredicateAliasPolicy = NO_ALIAS_POLICY,
) -> tuple[AnswerFact, ...]:
    """Build aligned ``AnswerFact`` records for one Answer against one roster.

    For each Answer fact and each candidate:

    1. gather the candidate's OBSERVED objects under exactly the same
       ``(predicate_uri, direction)`` key;
    2. call the frozen R1 classifier;
    3. copy its evidence level, exclusion basis and granularity risk;
    4. align the three tuples to the ranked candidate order.

    ``answer_facts`` are the ``FactQuality`` records B1.2 produced: their
    ``eligible`` verdict is the frozen R1 hard filter and is consumed here as
    ALREADY DECIDED. B1.3 re-runs no quality rule, no leakage rule and no
    blacklist, and it filters nothing out — an ineligible fact keeps its position
    so that fact indices stay stable and a rejected fact remains inspectable.

    ``semantic_index`` and ``rulebook`` are already built and already keyed;
    ``scope`` is the class the candidate pool was drawn from, and the rulebook is
    consulted per scope, so passing a scope the rules were not derived for simply
    matches no rule rather than silently matching another class's.

    THE FOUR OUTCOMES, AND WHO DECIDES THEM
        The classifier decides all of them. Restated here only so a reader of
        this module knows what it is delegating, with the authority being
        ``docs/context/EVIDENCE_TAXONOMY_V1.md``:

        ``NOT_COVERED``
            The candidate SUPPORTS the Answer proposition — through exact object
            equality, through a trusted canonical/redirect equivalence, or
            because an observed candidate object lies UNDER the claim object in
            the allowlisted containment hierarchy, so asserting it entails the
            Answer's more general claim. Semantic support produces NOT_COVERED
            rather than a weak level because the fact then distinguishes nobody
            at that position: it sets no coverage bit at any threshold. This test
            runs before every rule, so a supported fact can never be re-read as
            absence or as an observed alternative.
        ``L0``
            ``O_d(κ) = ∅``, and nothing else, ever. Snapshot absence only.
        ``L1``
            ``O_d(κ) ≠ ∅`` with no support. An observed alternative value.
        ``L2``
            Requires a machine-checkable proof. The frozen policy activates no L2
            rule (``l2_rules`` is empty), so zero L2 is the correct offline
            outcome here, not a gap.

    WHY CLAIM-UNDER-CANDIDATE IS A RISK AND NOT AN EXCLUSION
        The reverse containment — the Answer says *Tokyo* and the candidate says
        *Japan* — does NOT mean the candidate supports the proposition, and it
        does NOT mean the candidate contradicts it either. The two statements are
        recorded at different granularities, so the apparent contrast may be an
        artefact of how the two articles were written. The classifier keeps the
        observational level it already decided and records
        ``CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT`` on the separate granularity axis,
        where it orders against the fact and blocks main-corpus eligibility
        without pretending to be evidence either way.

    WHY AN UNAVAILABLE SEMANTIC INDEX STILL LEAVES L1 AS L1
        "we did not look" is not "we found nothing". When the index cannot run,
        the candidate's observed alternative value is still observed; only the
        question of whether it stands in a containment relation to the claim
        object is unanswered. Downgrading to L0 would relabel a positive
        observation as an absence — a strictly false statement about the
        snapshot — so the level is preserved and the doubt is recorded as
        ``UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE``.

    ``SCOPED_EMPIRICAL`` is likewise an annotation on an existing L1 and never a
    fourth level: it is derived upstream, arrives inside ``rulebook``, and can
    neither create, upgrade nor rescue a level.
    """
    # O_d(κ) once per candidate, in roster order. Positional, never zipped: a
    # zip() against a short sequence would stop early and silently align every
    # later evidence level to the wrong candidate.
    observed_by_position = [candidate_objects_from_local_kg(
        candidate.uri, local_kg=local_kg) for candidate in candidates]

    facts: list[AnswerFact] = []
    for quality in answer_facts:
        # The R1 proposition: this entity stands in relation κ to the claim
        # object. claim_object_uri == source_object_uri in R1 — no object is
        # generalised to an ancestor for verbalization — and nothing here invents
        # a qualifier the infobox source does not carry.
        proposition = RationaleProposition(
            predicate_uri=quality.predicate_uri,
            direction=quality.direction,
            source_object_uri=quality.counterpart_uri,
            claim_object_uri=quality.counterpart_uri)
        levels: list[str] = []
        bases: list[str] = []
        risks: list[str] = []
        for position, candidate in enumerate(candidates):
            # `.get(key, ())` is the ONLY place an empty object set is produced,
            # and it means exactly one thing: this candidate node is in the graph
            # and records nothing under this κ. A candidate that is not in the
            # graph never reaches here — it raised above.
            classified = classify_fact_against_candidate(
                proposition=proposition,
                candidate_uri=candidate.uri,
                # `observed_objects_for_key` is `.get(key, ())` under the
                # default empty alias policy. Under an ACTIVE policy it unions
                # the candidate's objects across the audited alias family in the
                # SAME direction, so `dbp:field` and `dbp:fields` stop being two
                # unrelated keys. The union happens here, BEFORE the classifier,
                # which is the only placement under which an exact object match
                # across an alias reaches the NOT_COVERED branch instead of
                # being read as absence. Nothing is written back: the Answer
                # fact keeps its own raw predicate and the pinned KG is
                # untouched.
                candidate_objects=observed_objects_for_key(
                    observed_by_position[position],
                    quality.predicate_direction_key,
                    policy=alias_policy),
                semantic_index=semantic_index,
                rulebook=rulebook,
                scope=scope)
            levels.append(classified.level)
            bases.append(classified.exclusion_basis)
            risks.append(classified.granularity_risk_status)
        fact = AnswerFact(quality=quality, levels=tuple(levels),
                          exclusion_bases=tuple(bases),
                          granularity_risks=tuple(risks))
        validate_fact_alignment(fact, len(candidates),
                                f"{quality.identity} against the ranked roster")
        facts.append(fact)
    return tuple(facts)


# --------------------------------------------------------------------------
# Phase B1.4 — the thin build-and-select orchestration
# --------------------------------------------------------------------------
#
# WHY THIS STEP CONTAINS NO SCIENCE OF ITS OWN
#   B1.2 decides what the pinned snapshot records about the Answer, and its
#   quality/leakage verdict is FINAL — B1.4 neither re-runs nor revisits it.
#   B1.3 decides every per-(fact, candidate) evidence level, by delegating to the
#   frozen R1 classifier. `mcq_core` decides the candidate pool, the search
#   scope, the set cover, the rationale ranking and the six-key objective. That
#   leaves B1.4 with exactly one job: check that the inputs are what they claim
#   to be, then call those four things in order. Every scientific rule it might
#   have restated already has exactly one owner, and a second statement of any of
#   them would be a second rule that can drift from the first.
#
# WHY A ROSTER NEEDS PROVENANCE THAT THE ROSTER ITSELF CANNOT CARRY
#   `Candidate(rank, score, uri)` is three opaque numbers and a string. Nothing
#   in it records WHICH ranker produced the ordering, WHICH class the pool was
#   drawn from, whether a human approved that class, or whether the sequence is
#   the complete admitted pool rather than somebody's top ten. All four change
#   what the published result means while changing none of the arithmetic:
#
#     * a legacy Overlap ranking would replace the paper's ranker and still fill
#       `rank` and `score` perfectly, so `provenance` must name the execution
#       path and it is checked against the pinned five values;
#     * a truncated roster would shrink the anonymity denominator and turn the
#       bounded pool's "top m of the frozen ranking" into the top m of a slice,
#       so the caller must declare the roster COMPLETE rather than merely supply
#       one that happens to be contiguous from rank 1.
#
# WHY CLASS APPROVAL IS PROVENANCE AND NOT AN EVIDENCE LEVEL
#   Approval says a human agreed that this class is a legitimate source of
#   same-class candidates. It is a statement about the experimental procedure,
#   not about any (fact, candidate) pair, and it must never be able to create,
#   upgrade or rescue a level: an approved class with weak evidence still yields
#   weak evidence. So it is required, recorded, and kept off every evidence axis.
#   No approval token is invented here, and no single approved status string is
#   hard-coded either — a later frozen class-selection procedure may report a
#   different status, and this generic path must not silently reject it.
#
# WHY NO SELECTION IS A VALID OUTCOME AND NOT SOMETHING TO REPAIR
#   `select_distractors()` returns None when no combination of the roster reaches
#   full coverage under any policy. That is a measurement — this class, at this
#   size, cannot support an item — and it is exactly the kind of feasibility
#   failure the yield experiment exists to count. B1.4 returns it unchanged,
#   still with its provenance record. It never widens the pool, weakens a
#   threshold, or fabricates a candidate to reach three.

#: What a caller must record about a roster it supplies. `require_fields` reports
#: any missing key by name, so a caller learns which provenance it omitted rather
#: than watching the run proceed on an undocumented ranking.
REQUIRED_RUN_PROVENANCE = (
    "candidate_roster_source",
    "candidate_roster_sha256",
    "candidate_roster_is_complete_admitted_pool",
    "selected_class_uri",
    "class_approval_status",
    *PINNED_LROLESIM_EXECUTION,
)


def validate_run_provenance(provenance: Mapping, *, scope: str) -> None:
    """Invariants 5, 8 and 9 on the provenance supplied with a live roster.

    The LRoleSim half is the same check B1.1 runs on a frozen Prompt-8D record,
    called through the same function. The class half is what the frozen records
    could only partly support (see the module docstring's PROVENANCE LIMITATION
    note): here the caller must state the class, its approval status and the
    roster artefact, and the class must agree with the classification scope,
    because a roster drawn from one class and evidence classified against another
    would produce levels aligned to a pool that never existed.
    """
    require_fields(provenance, REQUIRED_RUN_PROVENANCE, "the supplied run provenance")
    validate_pinned_lrolesim_execution(provenance)

    class_uri = provenance["selected_class_uri"]
    if not isinstance(class_uri, str) or not class_uri:
        raise InputContractError(
            f"invariant 9 (selected class recorded): selected_class_uri="
            f"{class_uri!r} is not a non-empty URI")
    if class_uri != scope:
        raise InputContractError(
            f"invariant 9 (selected class recorded): the roster was drawn from "
            f"{class_uri} but evidence is being classified against scope {scope}")
    # Present and non-empty, and nothing more. The VALUE is deliberately not
    # constrained: pinning one literal approval string here would refuse any
    # later frozen class-selection procedure that reports its own status.
    status = provenance["class_approval_status"]
    if not isinstance(status, str) or not status.strip():
        raise InputContractError(
            f"invariant 9 (approval status recorded): class_approval_status="
            f"{status!r} is empty, so nothing records that {class_uri} was "
            f"approved as a source of same-class candidates")
    for name in ("candidate_roster_source", "candidate_roster_sha256"):
        if not isinstance(provenance[name], str) or not provenance[name]:
            raise InputContractError(
                f"invariant 9 (candidate roster identity recorded): {name}="
                f"{provenance[name]!r} is not a non-empty string, so the roster "
                f"this selection ranged over cannot be identified again")
    # `is not True` rather than a truth test: the point is an explicit declaration,
    # and a truthy placeholder is not one.
    if provenance["candidate_roster_is_complete_admitted_pool"] is not True:
        raise InputContractError(
            "invariant 4 (complete ranked candidate pool): the caller did not "
            "record candidate_roster_is_complete_admitted_pool=True; an "
            "undocumented top-k truncation would shrink the anonymity "
            "denominator and redefine the bounded pool's TOP component")


def audit_record(
    case: AnswerCase,
    selection: Selection | None,
    provenance: Mapping,
    *,
    local_kg,
    quality_policy,
    semantic_index,
    rulebook,
) -> dict:
    """A deterministic, JSON-serialisable record of one build-and-select run.

    ``mcq_core.canonical_record()`` already publishes the selection itself —
    distractors, rationale, masks, search scope, both optimality claims and the
    scientific caveats — and is reused unchanged. What it cannot know is where
    its inputs came from, so exactly ONE nested mapping is added under
    ``phase_b1_provenance``. No provenance dataclass is introduced: a plain
    mapping with a fixed key order serialises deterministically and needs no
    schema migration when a later phase records one more digest.

    The four policy digests and the graph digest are read off the ALREADY-LOADED
    objects that were actually used, never re-declared by the caller and never
    recomputed from a file here. A caller-declared digest can be stale or simply
    wrong; ``rulebook.policy_sha256`` is by construction the digest of the rules
    that classified this run's evidence.

    A run with no selection still gets a full record. The provenance is what
    makes a feasibility failure reproducible and therefore countable.
    """
    cache_key = semantic_index.cache_key
    nested = {
        "answer_uri": case.answer_uri,
        "selected_class_uri": provenance["selected_class_uri"],
        "class_approval_status": provenance["class_approval_status"],
        "candidate_roster_source": provenance["candidate_roster_source"],
        "candidate_roster_sha256": provenance["candidate_roster_sha256"],
        "candidate_roster_is_complete_admitted_pool": True,
        "original_candidate_count": len(case.candidates),
        "pinned_kg_sha256": local_kg.source_sha256,
        "quality_policy_sha256": quality_policy.policy_sha256,
        "evidence_rules_sha256": rulebook.policy_sha256,
        "semantic_relation_policy_sha256": semantic_index.policy.policy_sha256,
        # Availability and identity are separate facts. An unavailable index is a
        # recorded condition of the run — it leaves every L1 carrying
        # UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE — and never a reason to downgrade.
        "semantic_index_available": semantic_index.available,
        "semantic_index_unavailable_reason": semantic_index.unavailable_reason,
        "semantic_index_cache_key": (None if cache_key is None
                                     else cache_key.as_record()),
        "lrolesim_execution": {name: provenance[name]
                               for name in PINNED_LROLESIM_EXECUTION},
        # Restated at the top level of the provenance so that a feasibility
        # failure, which has no canonical_record() to carry them, is still
        # explicit about what scope was searched and what was claimed.
        "search_scope": None if selection is None else selection.search_scope,
        "global_optimality_claim": (None if selection is None
                                    else selection.pool.global_optimality_claim),
        "selection_outcome": ("NO_FEASIBLE_SELECTION" if selection is None
                              else "SELECTED"),
    }
    if selection is None:
        return {"answer_uri": case.answer_uri,
                "display_label": case.display_label,
                "selection": None,
                "phase_b1_provenance": nested}
    return {**canonical_record(case, selection), "phase_b1_provenance": nested}


def build_and_select(
    answer_uri: str,
    display_label: str,
    candidates: Sequence[Candidate],
    *,
    local_kg,
    quality_policy,
    semantic_index,
    rulebook,
    scope: str,
    provenance: Mapping,
    pool_policy: PoolPolicy = DEFAULT_POOL_POLICY,
    force_pool: bool = False,
    objective: str = DEFAULT_RATIONALE_OBJECTIVE,
    alias_policy: PredicateAliasPolicy = NO_ALIAS_POLICY,
) -> tuple[AnswerCase, Selection | None, dict]:
    """Validate the supplied roster/provenance, reconstruct the Answer's facts,
    classify evidence, build the canonical ``AnswerCase``, and call the frozen
    Phase-A2 selector.

    Returns ``(case, selection, record)``. ``selection`` is ``None`` when no
    combination of this roster reaches full coverage under any policy, which is a
    feasibility result and not an error; ``record`` is the deterministic audit
    mapping described in :func:`audit_record`, and is produced either way.

    ``candidates`` is the COMPLETE admitted ranked candidate pool with its frozen
    LRoleSim ``rank`` and ``score`` already computed. No similarity is computed
    or recomputed anywhere in Phase B: Journal 2 applies LRoleSim as a structural
    plausibility ranker, and LRoleSim produces no rationale.

    Each of the five steps below belongs to somebody else, and this function
    contributes nothing to any of them beyond calling it:

    1. ``validate_run_provenance`` / ``validate_candidate_roster`` — the input
       contract, asserted before the kernel can produce an arithmetically valid
       but scientifically meaningless answer;
    2. ``answer_facts_from_local_kg`` (B1.2) — the Answer's complete observed
       one-hop inventory with the frozen R1 quality and leakage verdicts, which
       are consumed as already decided and are never re-run here;
    3. ``levels_for_candidates`` (B1.3) — every per-(fact, candidate) evidence
       level, exclusion basis and granularity risk, each decided by the frozen R1
       classifier;
    4. ``mcq_core.build_case`` — canonicalisation. The kernel's own contract
       forbids constructing ``AnswerCase`` directly, because ``build_case()`` is
       what re-sorts candidates into ``(rank, uri)`` order, permutes every fact's
       per-candidate tuples the same way and derives ``eligible_fact_indices``;
    5. ``mcq_core.select_distractors`` — the pool, the search scope, the set
       cover, the rationale ranking and the six-key objective. FULL_EXACT versus
       POOL_EXACT is the kernel's decision alone and is not influenced from here.
    """
    validate_run_provenance(provenance, scope=scope)
    roster = tuple(candidates)
    validate_candidate_roster(answer_uri, roster)
    validate_display_label(display_label, answer_uri)

    quality = answer_facts_from_local_kg(
        answer_uri, local_kg=local_kg, quality_policy=quality_policy)
    facts = levels_for_candidates(
        quality, roster, local_kg=local_kg, semantic_index=semantic_index,
        rulebook=rulebook, scope=scope, alias_policy=alias_policy)
    case = build_case(answer_uri, display_label, roster, facts)
    # `objective` names the VERSIONED rationale ordering (mcq_core
    # RATIONALE_OBJECTIVE_V1 / _V2). It defaults to V1, so every existing caller
    # — including the Prompt 8H-B2-D runner whose 329-Answer report is published
    # evidence — keeps the historical fourteen-field key.
    selection = select_distractors(case, pool_policy, force_pool, objective)
    return (case, selection, audit_record(
        case, selection, provenance, local_kg=local_kg,
        quality_policy=quality_policy, semantic_index=semantic_index,
        rulebook=rulebook))
