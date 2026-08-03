############################################################################
# src/pipeline/rationale_v3_run.py
#
# PROMPT 8F-R1 ORCHESTRATION — corrected evidence taxonomy, quality-aware
# distractor selection, compact scientific output set.
#
# WHAT THIS RUN CONSUMES
#   The FROZEN Prompt-8D handoff in
#   outputs/journal2_week2_extract_integration_2026-07-30/, the three versioned
#   policy files, and one CACHED semantic index. Nothing else. The 1.2 GB pinned
#   pickle is NOT loaded: it is read once by the separate `build-semantic-index`
#   mode, which writes a cache keyed on the KG hash, the policy hash, the
#   pilot's counterpart-URI list and the traversal depth. The run verifies that
#   key and refuses a cache built for anything else.
#
# WHAT R1 CHANGED HERE
#   * the middle policy is `main-l1`, and MCQ_level is reported explicitly;
#   * sixteen overlapping scientific files became five, with one typed evidence
#     audit instead of eight near-duplicate outputs;
#   * the support-threshold sweep, the candidate-pool ablation and the
#     Bipartite-graph fact emission were removed — the first two are purely
#     observational and the third belongs to a later task. All three are
#     recoverable from commit 1b81f9a;
#   * three ABLATION ARMS (quality off, semantic off, both off) run alongside
#     the full configuration so the four-way comparison can attribute each
#     difference to the taxonomy, the quality filter, the semantic layer or the
#     distractor search, without confounding the first two.
#
# WHAT THIS RUN MUST NOT TOUCH
#   No HTTP, SPARQL, Wikidata, DBpedia endpoint or abstracts, spaCy, SBERT, LLM,
#   legacy OverlapStrict/OverlapLoose, class selection, fallback-class graph
#   construction or LRoleSim recomputation. The ranker stays
#   lrolesim_m1_fixed_k3 with measure lrolesim_ed, lrolesim_beta 0.2 and exactly
#   three fixed iterations, all READ from the frozen records and asserted here.
#
# THE SULFURIC-ACID BOUNDARY
#   Sulfuric acid stays the ONE primary failure, with a primary summary row and
#   PRIMARY_NOT_READY. Its six diagnostic candidates are analysed in a separate
#   namespace inside run_manifest.json and enter no primary denominator, success
#   rate or candidate count.
#
# OPEN WORLD
#   Every emitted fact is OBSERVED in the pinned snapshot. L0 is absence-only
#   observation and is never a negative fact (CLAUDE.md items 7 and 8).
############################################################################

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import resource
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rationale_v3.contracts import (                                  # noqa: E402
    AUTOMATIC_GENERATION_FIELDS,
    DEFAULT_K,
    DEFAULT_MAX_EXACT_COMBINATIONS,
    DEFAULT_RHO,
    EXCLUSION_BASIS_DEFINITION,
    FALLBACK_NEXT_STAGE,
    HUMAN_EVALUATION_NOT_STARTED,
    LEGACY_ONE_FACT_SPECIAL_CASE_NOTE,
    LEVEL_DEFINITION,
    LEVEL_L0,
    LEVEL_L1,
    LEVEL_L2,
    LEVEL_NOT_COVERED,
    MCQ_LEVEL_NOTE,
    MULTI_VALUED_PREDICATE_NOTE,
    PARENT_CHILD_NOTE,
    POLICY_DIAGNOSTIC_L0,
    POLICY_MAIN_L1,
    POLICY_MINIMUM_LEVEL,
    POLICY_NOTE,
    POLICY_PRIORITY,
    POLICY_STRICT_L2,
    POOL_OPTIMALITY_NOTE,
    PROMPT8E_STATUS_FOR_REASON_CODE,
    PUBLISHABLE_FINAL_NOTE,
    QUALIFIER_NOTE,
    RELATION_UNRELATED_OR_UNKNOWN,
    SELECTION_PRIMARY_NOT_READY,
    SET_COVER_ALGORITHM,
    SET_COVER_COMPLEXITY,
    SET_COVER_PROVENANCE_NOTE,
    AnswerFact,
    assert_no_negative_claim,
    level_at_least,
)
from rationale_v3.evidence import (                                    # noqa: E402
    EvidenceRuleBook,
    derive_empirical_single_valued_rules,
    load_evidence_rules,
    observe_scope_cardinalities,
)
from rationale_v3.quality import (                                     # noqa: E402
    LeakagePolicy,
    ObjectPolicy,
    load_quality_policy,
)
from rationale_v3.selector import (                                    # noqa: E402
    AUDIT_TOP_RATIONALES,
    AnswerInput,
    AnswerSelection,
    PoolPolicy,
    RankedCandidateView,
    not_ready_selection,
    select_for_answer,
)
from rationale_v3.semantic_relations import (                          # noqa: E402
    AncestorEdge,
    SemanticIndex,
    SemanticIndexCacheKey,
    build_semantic_index,
    load_semantic_index_cache,
    load_semantic_relation_policy,
    normalize_uri,
    source_object_list_sha256,
    unavailable_semantic_index,
    write_semantic_index_cache,
)

# --- 0) PINNED INPUTS --------------------------------------------------------

FROZEN_PROMPT8D_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_extract_integration_2026-07-30")
FROZEN_PROMPT8D_ZIP_SHA256 = (
    "d2a0ff793f64767c0413c3b9f116791abecdeafdf51c4bff3eaf2ee331cae404")
FROZEN_PROMPT8E_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_rationale_selection_2026-08-01")
FROZEN_PROMPT8E_ZIP_SHA256 = (
    "9463e1045ea98a40c8ef062adf999ff0b86ee03adafd5326be855713c91921a3")
#: The Prompt-8F package this task corrects. Read as DATA for the comparison;
#: never modified, never re-executed.
FROZEN_PROMPT8F_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_rationale_v3_2026-08-03")
FROZEN_PROMPT8F_ZIP_SHA256 = (
    "3ba2803ee154074208bdc8a401ce379b8bf57e1b717d02391ee7443fa80585bf")
PROMPT8F_PARENT_COMMIT = "1b81f9a4a8d4c09b8b381e80ea090e2dab256a7f"

PINNED_LOCAL_KG = REPO_ROOT / "data" / "infobox.pickle_EnglishVersion_EntityType"
PINNED_LOCAL_KG_SHA256 = (
    "e230c5b95e20093631697624d9c46f30a14081b3f415d5027ffaf313bdbbea1b")

POLICY_DIR = SRC_DIR / "rationale_v3" / "policies"
PREDICATE_POLICY_PATH = POLICY_DIR / "predicate_policy.json"
EVIDENCE_RULES_PATH = POLICY_DIR / "evidence_rules.json"
SEMANTIC_POLICY_PATH = POLICY_DIR / "semantic_relation_policy.json"

DEFAULT_SEMANTIC_INDEX_CACHE = (
    REPO_ROOT / "data" / "semantic_index_v3" / "pilot_place_containment_v1.json")
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_rationale_v3_r1_2026-08-03")

REQUIRED_INPUT_FILES = (
    "candidate_ranking_handoff.jsonl",
    "extract_integration_summary.csv",
    "observed_answer_facts.jsonl",
    "observed_candidate_facts.jsonl",
    "observed_diagnostic_facts.jsonl",
    "provisional_top3_handoff.csv",
    "sulfuric_acid_diagnostic_handoff.json",
    "contract_validation.json",
)

# Frozen Prompt-8C, 8D and 8E sources. R1 must not change any of them, so their
# hashes are checked at run time and published, not merely promised.
PROTECTED_SOURCE_PINS = (
    ("candidate_order", "pipeline/candidate_order.py", "8a6e9b36f9a393de8a4f287305f4545f78e4090b34a83f0b3ebcea76cbc0e1f2"),
    ("graph_lrolesim_run", "pipeline/graph_lrolesim_run.py", "2c1242dbe7dfd7608a3dd09d7ff71bcd672880968b1bcdfdbd7fe45d628eb994"),
    ("graph_view", "kg/graph_view.py", "0ed2733307ef8116b4ba79c906e8e880711e06f011418b0da3104e4c99716ec4"),
    ("lrolesim_adapter", "lrolesim/adapter.py", "2100fd112b144a4d71d2b0be0ef3465b3c73c9f8d5d8ad78b28a587185d65f33"),
    ("lrolesim_kernel", "MCQ_lrolesim_ClaudeWeb_v2.py", "b7c3678ee531a291dee874053529ac498d8c7674b892cff19e817808671ddec0"),
    ("selection_init", "selection/__init__.py", "912a0a49867006645667d43d989fc0a87492edbf59da5c925955c1aa6c9a375a"),
    ("selection_contracts", "selection/contracts.py", "a271f28eaf0492604232fe3f0a2810346e3db98fee64aa9dd1236ce6219752ec"),
    ("selection_observed_facts", "selection/observed_facts.py", "78f0543252851177e19389626ed17a34440d0f941b18c4bb8b4e7ffdaaa8364d"),
    ("selection_lrolesim_handoff", "selection/lrolesim_handoff.py", "c4fc4077743f3f4874d3abda91a0ee4d13ce5256c47a691e3988c99e708ce26d"),
    ("selection_legacy_overlap", "selection/legacy_overlap.py", "a50dd4435f65f831b2c641219445a917f0e5851a6e35ace3aacc1f061e5f014d"),
    ("prompt8e_entrypoint", "extract_221_and_select_distractors_ClaudeWeb_v2.py", "81f9297f8084503806a28ed15f2ed1c6465c152a86616c4d12e669ac0867f6aa"),
    ("prompt8e_rationale_init", "rationale/__init__.py", "cedb14cac100ddb2d8291ffa52bcfd71dfff6a74554e96016b13c4b139734796"),
    ("prompt8e_rationale_contracts", "rationale/contracts.py", "04fadc371c7a6d32dc41b264efb27a755e781a3ced2bc49f8a3e57610d9eb7a3"),
    ("prompt8e_rationale_contrasts", "rationale/contrasts.py", "06e4c5c8dcd2c0fa6de95f6b68a9dc81a21680da5b6ba6a8d3cb91459c7e29a3"),
    ("prompt8e_rationale_setcover", "rationale/setcover.py", "bc811a1632dbb972dc1372a382b566eadf07f5af7569aef5656c8804dec4dafe"),
    ("prompt8e_rationale_selector", "rationale/selector.py", "14dc3684e3d516fad147a111288bbc7de33fcbdc34c05c3956930900e13c7d39"),
    ("prompt8e_rationale_selection_run", "pipeline/rationale_selection_run.py", "650a6e634815a71996a381300e480bd2a224b08bc6d6d4ae096c0cd1497bcec3"),
)

PROTECTED_SOURCES = {name: (SRC_DIR / relative, digest)
                     for name, relative, digest in PROTECTED_SOURCE_PINS}

# --- The expected Prompt-8D shape, asserted rather than assumed -------------
EXPECTED_PRIMARY_ANSWER_COUNT = 9
EXPECTED_READY_ANSWER_COUNT = 8
EXPECTED_PRIMARY_RANKED_CANDIDATE_COUNT = 204
EXPECTED_DIAGNOSTIC_RANKED_CANDIDATE_COUNT = 6
EXPECTED_PRIMARY_FAILURE_ANSWER_URI = "http://dbpedia.org/resource/Sulfuric_acid"

# --- The frozen LRoleSim execution path, asserted --------------------------
EXPECTED_RANKER_NAME = "lrolesim_m1_fixed_k3"
EXPECTED_MEASURE = "lrolesim_ed"
EXPECTED_LROLESIM_BETA = 0.2
EXPECTED_ITERATIONS = 3
EXPECTED_ITERATION_MODE = "fixed"

#: Files a strict offline replay must reproduce byte for byte. Timing, clock and
#: Git-state artefacts are excluded by construction, not by tolerance.
REPLAY_COMPARED_FILES = (
    "rationale_v3_r1_summary.csv",
    "selected_mcqs_v3_r1.jsonl",
    "evidence_audit_v3_r1.jsonl",
    "prompt8e_v3_v3r1_comparison.csv",
    "fallback_class_requests_v3_r1.jsonl",
)

#: Modules whose presence in sys.modules would contradict the zero-network,
#: zero-model claim of the R1 path. `kg.loader` is deliberately absent: the
#: separate build-semantic-index mode is the one place allowed to open the
#: pinned pickle, and the run asserts it did NOT do so.
FORBIDDEN_MODULE_PREFIXES = (
    "spacy", "sentence_transformers", "torch", "SPARQLWrapper", "requests",
    "urllib3", "httpx", "openai", "anthropic", "nltk", "gensim",
    "classes.sparql_client", "classes.member_mapper", "classes.page_cache",
    "classes.class_selector", "category_extractor_ClaudeWeb_v2",
    "category_extractor_ClaudeWeb_v3", "category_extractor_ClaudeWeb_v4",
    "selection.legacy_overlap", "lrolesim.adapter",
    "MCQ_lrolesim_ClaudeWeb_v2", "pipeline.graph_lrolesim_run",
)


class RationaleV3Error(Exception):
    """Base class for R1 rationale failures."""


class Prompt8DInputError(RationaleV3Error):
    """A frozen Prompt-8D input file is missing, unreadable or inconsistent."""


class ProtectedSourceModifiedError(RationaleV3Error):
    """A frozen source file no longer has its expected SHA-256."""


class OfflineGuardTripped(RationaleV3Error):
    """The R1 path attempted an outbound connection."""


# --- 1) OFFLINE GUARD --------------------------------------------------------

@dataclass
class OfflineGuard:
    """Blocks and counts outbound socket connections for the whole run.

    A guard that FAILS the run makes "zero network attempts" a checked property
    rather than an assurance, and the published counter is the evidence.
    """

    attempts: list = field(default_factory=list)
    _installed: bool = False
    _saved: dict = field(default_factory=dict)

    def install(self) -> None:
        if self._installed:
            return
        guard = self

        def blocked(address):
            guard.attempts.append(repr(address))
            raise OfflineGuardTripped(
                f"outbound connection to {address!r} refused: R1 reads only "
                f"frozen local artefacts")

        self._saved = {
            "connect": socket.socket.connect,
            "connect_ex": socket.socket.connect_ex,
            "create_connection": socket.create_connection,
        }
        socket.socket.connect = (                          # type: ignore[method-assign]
            lambda self, address, *a, **k: blocked(address))
        socket.socket.connect_ex = (                       # type: ignore[method-assign]
            lambda self, address, *a, **k: blocked(address))
        socket.create_connection = (                       # type: ignore[assignment]
            lambda address, *a, **k: blocked(address))
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        socket.socket.connect = self._saved["connect"]              # type: ignore[method-assign]
        socket.socket.connect_ex = self._saved["connect_ex"]        # type: ignore[method-assign]
        socket.create_connection = self._saved["create_connection"]  # type: ignore[assignment]
        self._installed = False

    def as_record(self) -> dict:
        return {
            "installed": self._installed,
            "network_attempts": len(self.attempts),
            "http_calls": len(self.attempts),
            "sparql_calls": len(self.attempts),
            "attempted_addresses": list(self.attempts),
        }


def loaded_forbidden_modules() -> list:
    """Which forbidden modules this process imported. Expected: none."""
    return [name for name in sorted(sys.modules)
            if any(name == prefix or name.startswith(prefix + ".")
                   for prefix in FORBIDDEN_MODULE_PREFIXES)]


# --- 2) DETERMINISTIC READERS AND WRITERS ------------------------------------

def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"))


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, records: Iterable[Mapping[str, object]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        for record in records:
            f.write(_canonical_json(record) + "\n")


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=True)
        f.write("\n")


def _b(value: bool) -> str:
    return "true" if value else "false"


def _fmt_score(score: float) -> str:
    """Shortest round-tripping decimal form, matching the 8C/8D/8E writers."""
    return repr(float(score))


def _join(values: Iterable[object]) -> str:
    return "|".join(str(value) for value in values)


def sha256_file(path: str | Path, chunk_size: int = 1 << 23) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_jsonl(path: Path) -> list:
    if not path.is_file():
        raise Prompt8DInputError(f"input not found: {path}")
    records = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise Prompt8DInputError(f"{path.name} line {lineno}: {exc}") from exc
    return records


def _read_csv(path: Path) -> list:
    if not path.is_file():
        raise Prompt8DInputError(f"input not found: {path}")
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise Prompt8DInputError(f"input not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def verify_protected_sources() -> dict:
    """Confirm every frozen source is byte-identical to its pin."""
    observed = {}
    drift = []
    for name, (path, expected) in sorted(PROTECTED_SOURCES.items()):
        digest = sha256_file(path)
        observed[name] = {
            "path": str(path.relative_to(REPO_ROOT)),
            "expected_sha256": expected,
            "observed_sha256": digest,
            "unmodified": digest == expected,
        }
        if digest != expected:
            drift.append(name)
    if drift:
        raise ProtectedSourceModifiedError(
            f"frozen Prompt-8C/8D/8E sources changed: {drift}. R1 must not "
            f"modify the graph, ordering, LRoleSim, selection or Prompt-8E "
            f"rationale layers.")
    return observed


# --- 3) READING THE FROZEN PROMPT-8D HANDOFF ---------------------------------

@dataclass(frozen=True)
class Prompt8DInputs:
    """The frozen Prompt-8D artefacts, read and shape-checked."""

    source_dir: Path
    handoffs: tuple
    summary: tuple
    answer_facts: tuple
    candidate_facts: tuple
    diagnostic_facts: tuple
    diagnostic_handoff: Mapping[str, object]
    input_sha256: Mapping[str, str]
    contract_checks: tuple = ()

    def ready_handoffs(self) -> list:
        return [h for h in self.handoffs if h["ready_for_rationale_selection"]]

    def with_checks(self, checks: Sequence) -> "Prompt8DInputs":
        return Prompt8DInputs(**{**vars(self), "contract_checks": tuple(checks)})


def load_prompt8d_handoff(source_dir: str | Path) -> Prompt8DInputs:
    """Read the frozen Prompt-8D handoff and assert its input contract."""
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise Prompt8DInputError(
            f"frozen Prompt-8D output directory not found: {source_dir}")
    missing = [name for name in REQUIRED_INPUT_FILES
               if not (source_dir / name).is_file()]
    if missing:
        raise Prompt8DInputError(
            f"{source_dir}: missing frozen Prompt-8D inputs {missing}")

    inputs = Prompt8DInputs(
        source_dir=source_dir,
        handoffs=tuple(_read_jsonl(source_dir / "candidate_ranking_handoff.jsonl")),
        summary=tuple(_read_csv(source_dir / "extract_integration_summary.csv")),
        answer_facts=tuple(_read_jsonl(source_dir / "observed_answer_facts.jsonl")),
        candidate_facts=tuple(
            _read_jsonl(source_dir / "observed_candidate_facts.jsonl")),
        diagnostic_facts=tuple(
            _read_jsonl(source_dir / "observed_diagnostic_facts.jsonl")),
        diagnostic_handoff=_read_json(
            source_dir / "sulfuric_acid_diagnostic_handoff.json"),
        input_sha256={name: sha256_file(source_dir / name)
                      for name in sorted(REQUIRED_INPUT_FILES)},
    )
    return inputs.with_checks(validate_prompt8d_contract(inputs))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Prompt8DInputError(message)


def validate_prompt8d_contract(inputs: Prompt8DInputs) -> list:
    """Assert the input contract against the frozen records.

    Every number R1 reports downstream is a consequence of these, so they are
    checked once, here, and never re-derived from a different file later.
    """
    checks: list = []

    _require(len(inputs.handoffs) == EXPECTED_PRIMARY_ANSWER_COUNT
             and len(inputs.summary) == EXPECTED_PRIMARY_ANSWER_COUNT,
             f"expected {EXPECTED_PRIMARY_ANSWER_COUNT} primary handoff records "
             f"and summary rows, found {len(inputs.handoffs)} and "
             f"{len(inputs.summary)}")
    checks.append(("nine_primary_records",
                   f"{len(inputs.handoffs)} handoffs, {len(inputs.summary)} "
                   f"summary rows"))

    ready = inputs.ready_handoffs()
    _require(len(ready) == EXPECTED_READY_ANSWER_COUNT,
             f"expected {EXPECTED_READY_ANSWER_COUNT} ready Answers, found "
             f"{len(ready)}")
    checks.append(("eight_ready_answers", f"{len(ready)} ready"))

    not_ready = [h for h in inputs.handoffs
                 if not h["ready_for_rationale_selection"]]
    _require(len(not_ready) == 1
             and not_ready[0]["answer_uri"] == EXPECTED_PRIMARY_FAILURE_ANSWER_URI
             and not_ready[0]["ranked_candidate_count"] == 0,
             f"the one primary failure must be "
             f"{EXPECTED_PRIMARY_FAILURE_ANSWER_URI} with no ranked candidate")
    checks.append(("sulfuric_acid_primary_failure_preserved",
                   f"{not_ready[0]['mapping_stage_status']} / "
                   f"{not_ready[0]['graph_stage_status']}"))

    ranked_total = sum(h["ranked_candidate_count"] for h in inputs.handoffs)
    _require(ranked_total == EXPECTED_PRIMARY_RANKED_CANDIDATE_COUNT,
             f"expected {EXPECTED_PRIMARY_RANKED_CANDIDATE_COUNT} primary "
             f"ranked candidates, found {ranked_total}")
    checks.append(("primary_ranked_candidate_count", f"{ranked_total} ranks"))

    diagnostic_ranked = inputs.diagnostic_handoff["diagnostic_handoff"][
        "ranked_candidate_count"]
    _require(diagnostic_ranked == EXPECTED_DIAGNOSTIC_RANKED_CANDIDATE_COUNT
             and bool(inputs.diagnostic_handoff["diagnostic_only"]),
             f"expected {EXPECTED_DIAGNOSTIC_RANKED_CANDIDATE_COUNT} diagnostic "
             f"ranked candidates flagged diagnostic_only, found "
             f"{diagnostic_ranked}")
    checks.append(("diagnostic_ranks_isolated",
                   f"{diagnostic_ranked} diagnostic ranks, held separately"))

    for handoff in ready:
        label = handoff["answer_uri"]
        _require(handoff["ranker_name"] == EXPECTED_RANKER_NAME,
                 f"{label}: ranker_name must be {EXPECTED_RANKER_NAME}")
        _require(handoff["measure"] == EXPECTED_MEASURE,
                 f"{label}: measure must be {EXPECTED_MEASURE}")
        _require(float(handoff["lrolesim_beta"]) == EXPECTED_LROLESIM_BETA,
                 f"{label}: lrolesim_beta must be {EXPECTED_LROLESIM_BETA}")
        _require(int(handoff["iterations"]) == EXPECTED_ITERATIONS,
                 f"{label}: iterations must be exactly {EXPECTED_ITERATIONS}")
        _require(handoff["iteration_mode"] == EXPECTED_ITERATION_MODE,
                 f"{label}: iteration_mode must be {EXPECTED_ITERATION_MODE}")
        ranks = [c["rank"] for c in handoff["ranked_candidates"]]
        _require(ranks == list(range(1, len(ranks) + 1)),
                 f"{label}: ranks must be contiguous from 1")
        for candidate in handoff["ranked_candidates"]:
            _require(not candidate["is_final_distractor"],
                     f"{label}: a frozen ranking row claims to be final")
    checks.append(("frozen_lrolesim_execution_path",
                   f"measure={EXPECTED_MEASURE}, "
                   f"lrolesim_beta={EXPECTED_LROLESIM_BETA}, "
                   f"iterations={EXPECTED_ITERATIONS} "
                   f"({EXPECTED_ITERATION_MODE})"))
    return checks


# --- 4) BUILDING THE R1 INPUTS -----------------------------------------------

def _answer_fact(record: Mapping[str, object]) -> AnswerFact:
    return AnswerFact(
        predicate_uri=normalize_uri(str(record["predicate_uri"])),
        direction=str(record["direction"]),
        counterpart_uri=normalize_uri(str(record["counterpart_uri"])),
        graph_fingerprint=str(record["graph_fingerprint"]),
        owner_uri=normalize_uri(str(record["owner_uri"])))


def _ranked_candidates(handoff: Mapping[str, object]) -> tuple:
    return tuple(
        RankedCandidateView(
            rank=int(c["rank"]),
            canonical_candidate_uri=normalize_uri(
                str(c["canonical_candidate_uri"])),
            candidate_local_index=int(c["candidate_local_index"]),
            score=float(c["score"]))
        for c in sorted(handoff["ranked_candidates"], key=lambda c: int(c["rank"])))


def build_answer_inputs(inputs: Prompt8DInputs) -> tuple:
    """One AnswerInput per READY primary Answer, in pilot-slot order."""
    answer_facts: dict = {}
    for record in inputs.answer_facts:
        answer_facts.setdefault(str(record["answer_uri"]), []).append(
            _answer_fact(record))

    candidate_facts: dict = {}
    for record in inputs.candidate_facts:
        bucket = candidate_facts.setdefault(str(record["answer_uri"]), {})
        bucket.setdefault(normalize_uri(str(record["owner_uri"])), []).append(
            _answer_fact(record))

    built = []
    for handoff in sorted(inputs.ready_handoffs(),
                          key=lambda h: int(h["pilot_slot"])):
        answer_uri = str(handoff["answer_uri"])
        built.append(AnswerInput(
            answer_uri=answer_uri,
            answer_local_index=int(handoff["answer_local_index"]),
            display_label=str(handoff["display_label"]),
            pilot_slot=int(handoff["pilot_slot"]),
            selected_class_uri=str(handoff["selected_class_uri"]),
            graph_fingerprint=str(handoff["graph_fingerprint"]),
            ranker_name=str(handoff["ranker_name"]),
            measure=str(handoff["measure"]),
            lrolesim_beta=float(handoff["lrolesim_beta"]),
            iterations=int(handoff["iterations"]),
            iteration_mode=str(handoff["iteration_mode"]),
            ranked_candidates=_ranked_candidates(handoff),
            answer_facts=tuple(answer_facts.get(answer_uri, ())),
            candidate_facts={k: tuple(v) for k, v
                             in candidate_facts.get(answer_uri, {}).items()}))
    return tuple(built)


def build_diagnostic_input(inputs: Prompt8DInputs) -> Optional[AnswerInput]:
    """The Sulfuric-acid DIAGNOSTIC input, in its own namespace.

    Engineering evidence only. Nothing built here enters a primary denominator,
    success rate or candidate count, and the primary Sulfuric-acid row stays
    PRIMARY_NOT_READY regardless of what this analysis finds.
    """
    handoff = inputs.diagnostic_handoff["diagnostic_handoff"]
    answer_facts = []
    candidate_facts: dict = {}
    for record in inputs.diagnostic_facts:
        fact = _answer_fact(record)
        if record["owner_role"] == "answer":
            answer_facts.append(fact)
        else:
            candidate_facts.setdefault(fact.owner_uri, []).append(fact)

    ranked = _ranked_candidates(handoff)
    if not ranked:
        return None
    return AnswerInput(
        answer_uri=normalize_uri(str(handoff["answer_uri"])),
        answer_local_index=int(handoff["answer_local_index"]),
        display_label=str(handoff["display_label"]),
        pilot_slot=int(handoff["pilot_slot"]),
        selected_class_uri=str(handoff["selected_class_uri"]),
        graph_fingerprint=str(handoff["graph_fingerprint"]),
        ranker_name=str(handoff["ranker_name"]),
        measure=str(handoff["measure"]),
        lrolesim_beta=float(handoff["lrolesim_beta"]),
        iterations=int(handoff["iterations"]),
        iteration_mode=str(handoff["iteration_mode"]),
        ranked_candidates=ranked, answer_facts=tuple(answer_facts),
        candidate_facts={k: tuple(v) for k, v in candidate_facts.items()},
        primary_or_diagnostic="diagnostic")


def pilot_object_uris(inputs: Prompt8DInputs) -> tuple:
    """Every counterpart URI the pilot reasons about, sorted and deduplicated.

    This IS the semantic index's source-object list, and its digest is part of
    the cache key: an index built for a different pilot must not be reused.
    """
    uris = set()
    for group in (inputs.answer_facts, inputs.candidate_facts,
                  inputs.diagnostic_facts):
        for record in group:
            uris.add(normalize_uri(str(record["counterpart_uri"])))
    return tuple(sorted(uris))


# --- 5) THE SEMANTIC INDEX (built once, cached, verified) --------------------

SEMANTIC_INDEX_BUILD_COMMAND = (
    "python src/extract_and_select_distractors_v3.py "
    "--mode build-semantic-index")


def build_semantic_index_from_pinned_kg(
    *, prompt8d_dir: str | Path = FROZEN_PROMPT8D_DIR,
    local_kg_path: str | Path = PINNED_LOCAL_KG,
    policy_path: str | Path = SEMANTIC_POLICY_PATH,
    cache_path: str | Path = DEFAULT_SEMANTIC_INDEX_CACHE,
    verbose: bool = True,
) -> Path:
    """Read the pinned KG ONCE and write the bounded semantic index cache.

    The ONLY function in this path permitted to open the 1.2 GB pickle, and it
    is a separate CLI mode so the scientific run never pays for it and never
    depends on it being loadable. `kg.loader` is imported inside the function so
    that merely importing this module does not pull the loader in. Only
    counterpart URIs from the pilot, and the ancestors reachable from them
    within the policy's depth, are indexed; nothing writes to the KG.
    """
    from kg.loader import load_local_kg           # local: build-mode only

    policy = load_semantic_relation_policy(policy_path)
    inputs = load_prompt8d_handoff(prompt8d_dir)
    sources = pilot_object_uris(inputs)
    if verbose:
        print(f"  semantic index: {len(sources)} pilot counterpart URIs, "
              f"{len(policy.traversal_rules)} allowlisted traversal rules, "
              f"max depth {policy.max_depth}")

    kg = load_local_kg(local_kg_path)
    allow = {rule.predicate_uri: rule for rule in policy.traversal_rules}

    def plain(index: int) -> Optional[str]:
        raw = kg.index_url.get(index)
        if raw is None:
            return None
        return raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw

    edges: list = []
    seen_nodes: set = set()
    frontier = list(sources)
    for depth in range(policy.max_depth):
        nxt: list = []
        for uri in frontier:
            if uri in seen_nodes:
                continue
            seen_nodes.add(uri)
            # The pinned pickle keys URIs with angle brackets (see
            # selection/observed_facts.bare_uri); the handoff stores them plain.
            node = kg.index_for_uri_or_none("<" + uri + ">")
            if node is None:
                continue
            for predicate_index, object_index in kg.out_neighbor.get(node, ()):
                predicate = plain(predicate_index)
                rule = allow.get(predicate) if predicate else None
                if rule is None:
                    continue
                parent = plain(object_index)
                if not parent or parent == uri:
                    continue
                edges.append(AncestorEdge(
                    child_uri=uri, parent_uri=parent, rule_id=rule.rule_id,
                    predicate_uri=rule.predicate_uri,
                    relation_kind=rule.relation_kind))
                nxt.append(parent)
        frontier = nxt
        if verbose:
            print(f"    depth {depth + 1}: {len(edges)} allowlisted edges, "
                  f"{len(seen_nodes)} nodes visited")
        if not frontier:
            break

    key = SemanticIndexCacheKey(
        pinned_kg_sha256=PINNED_LOCAL_KG_SHA256,
        policy_sha256=policy.policy_sha256,
        source_object_list_sha256=source_object_list_sha256(sources),
        max_depth=policy.max_depth,
        creation_command=SEMANTIC_INDEX_BUILD_COMMAND)
    index = build_semantic_index(policy=policy, parent_edges=edges,
                                 cache_key=key, indexed_object_count=len(sources))
    written = write_semantic_index_cache(cache_path, index)
    if verbose:
        print(f"  semantic index cache -> {written} "
              f"({sum(len(v) for v in index.parents.values())} edges, "
              f"{len(index.parents)} nodes with a parent)")
    return written


def load_pilot_semantic_index(inputs: Prompt8DInputs, *,
                              policy_path: str | Path = SEMANTIC_POLICY_PATH,
                              cache_path: str | Path = DEFAULT_SEMANTIC_INDEX_CACHE
                              ) -> SemanticIndex:
    """Load the cached index for THIS pilot, or an UNAVAILABLE one saying why."""
    policy = load_semantic_relation_policy(policy_path)
    key = SemanticIndexCacheKey(
        pinned_kg_sha256=PINNED_LOCAL_KG_SHA256,
        policy_sha256=policy.policy_sha256,
        source_object_list_sha256=source_object_list_sha256(
            pilot_object_uris(inputs)),
        max_depth=policy.max_depth,
        creation_command=SEMANTIC_INDEX_BUILD_COMMAND)
    return load_semantic_index_cache(cache_path, policy=policy, expected_key=key)


# --- 6) DERIVING THE SCOPED EMPIRICAL ANNOTATION RULES -----------------------

def scope_observations(answers: Sequence[AnswerInput]) -> dict:
    """{scope: {entity: {key: [object]}}} over the Answer AND candidate pools.

    Facts are keyed per Answer graph in the Prompt-8D handoff and one class is
    shared by several Answers, so the same candidate fact can appear more than
    once. Building a per-entity SET here is what stops a shared candidate from
    being counted as a cardinality violation against itself.
    """
    scopes: dict = {}
    for answer in answers:
        bucket = scopes.setdefault(answer.scope, {})
        entity = bucket.setdefault(answer.answer_uri, {})
        for fact in answer.answer_facts:
            entity.setdefault(fact.key_tuple, set()).add(fact.counterpart_uri)
        for uri, facts in answer.candidate_facts.items():
            entity = bucket.setdefault(uri, {})
            for fact in facts:
                entity.setdefault(fact.key_tuple, set()).add(fact.counterpart_uri)
    return {scope: {entity: {key: sorted(objects)
                             for key, objects in keys.items()}
                    for entity, keys in entities.items()}
            for scope, entities in scopes.items()}


def derive_rulebook(
    answers: Sequence[AnswerInput],
    *,
    base: EvidenceRuleBook,
    semantic_index: SemanticIndex,
    rejected_predicates: Mapping[str, str],
    minimum_support_override: Optional[int] = None,
) -> tuple[EvidenceRuleBook, dict]:
    """Derive every scoped empirical annotation-rule candidate and merge them."""
    observations = scope_observations(answers)
    per_scope: dict = {}
    derived: list = []
    for scope in sorted(observations):
        rows = observe_scope_cardinalities(
            scope=scope, observations=observations[scope],
            semantic_index=semantic_index)
        per_scope[scope] = rows
        derived.extend(derive_empirical_single_valued_rules(
            rows, config=base.derivation,
            rejected_predicates=rejected_predicates,
            minimum_support_override=minimum_support_override))
    return (base.with_rules(derived), per_scope)


# --- 7) THE ABLATION ARMS (for the four-way comparison) ----------------------
# Three extra selections per Answer, so each reported effect is MEASURED rather
# than asserted, and the quality and semantic factors are not confounded:
#
#   quality_off   hard predicate/object/leakage filters off, semantic index on
#   semantic_off  filters on, semantic index withheld
#   reduced       both off — the arm the four-way comparison displays
#
# Each is observational: none of them can move the primary selection, which
# always stays at the full configuration.

ARM_QUALITY_OFF = "quality_off"
ARM_SEMANTIC_OFF = "semantic_off"
ARM_REDUCED = "reduced"
COMPARISON_ARMS = (ARM_QUALITY_OFF, ARM_SEMANTIC_OFF, ARM_REDUCED)


def permissive_quality_policy(policy):
    """The same policy with every HARD filter switched off.

    Soft signals (tier, template, label length) are left alone: they order
    rationales and never remove one, so disabling them would confound the
    measurement.
    """
    objects = policy.objects
    return replace(
        policy,
        hard_reject_predicates={},
        objects=ObjectPolicy(
            resource_namespace_prefixes=(),
            web_archive_hosts=(),
            media_file_suffixes=(),
            maximum_object_label_length=10 ** 9,
            minimum_object_label_length=0,
            machine_identifier_minimum_digit_ratio=2.0,
            educational_allowlist=objects.educational_allowlist,
            reject_reason_codes=objects.reject_reason_codes),
        leakage=LeakagePolicy(
            minimum_token_length=10 ** 6,   # no token survives, so no leak fires
            minimum_prefix_length=policy.leakage.minimum_prefix_length,
            soft_prefix_length=policy.leakage.soft_prefix_length,
            strip_suffixes=policy.leakage.strip_suffixes,
            hard_reason_code=policy.leakage.hard_reason_code,
            soft_reason_code=policy.leakage.soft_reason_code))


def run_ablation_arm(arm: str, answers: Sequence[AnswerInput], *,
                     base_rules: EvidenceRuleBook, semantic_index: SemanticIndex,
                     quality_policy, k: int, rho: int,
                     pool_policy: PoolPolicy) -> dict:
    """Re-select every Answer with one or both safety layers switched off."""
    index = (unavailable_semantic_index(
                 semantic_index.policy,
                 f"withheld for the {arm} comparison arm")
             if arm in (ARM_SEMANTIC_OFF, ARM_REDUCED) else semantic_index)
    policy = (permissive_quality_policy(quality_policy)
              if arm in (ARM_QUALITY_OFF, ARM_REDUCED) else quality_policy)
    rejected = ({} if arm in (ARM_QUALITY_OFF, ARM_REDUCED)
                else quality_policy.hard_reject_predicates)
    book, _ = derive_rulebook(answers, base=base_rules, semantic_index=index,
                              rejected_predicates=rejected)
    return {answer.answer_uri: select_for_answer(
                answer, semantic_index=index, rulebook=book,
                quality_policy=policy, k=k, rho=rho, pool_policy=pool_policy)
            for answer in answers}


# --- 8) THE RUN --------------------------------------------------------------

@dataclass
class StageTiming:
    stage: str
    wall_seconds: float
    peak_rss_kb: int
    detail: str = ""

    def as_row(self) -> dict:
        return {"stage": self.stage,
                "wall_seconds": f"{self.wall_seconds:.3f}",
                "process_peak_rss_kb": self.peak_rss_kb,
                "detail": self.detail}


@dataclass
class RationaleV3Run:
    """Everything one R1 run produced."""

    mode: str
    ranker_name: str
    k: int
    rho: int
    inputs: Prompt8DInputs
    contract_checks: tuple
    answers: tuple
    selections: tuple
    primary_order: tuple
    comparison_arms: Mapping[str, Mapping[str, AnswerSelection]]
    diagnostic_input: Optional[AnswerInput]
    diagnostic_selection: Optional[AnswerSelection]
    semantic_index: SemanticIndex
    rulebook: EvidenceRuleBook
    base_rulebook: EvidenceRuleBook
    quality_policy: object
    scope_observations: Mapping[str, tuple]
    protected_sources: dict
    guard_record: dict
    forbidden_modules: tuple
    timings: tuple
    pool_policy: PoolPolicy

    def selection_for(self, answer_uri: str) -> AnswerSelection:
        for selection in self.selections:
            if selection.answer_uri == answer_uri:
                return selection
        raise KeyError(answer_uri)

    def answer_for(self, answer_uri: str) -> AnswerInput:
        for item in self.answers:
            if item.answer_uri == answer_uri:
                return item
        raise KeyError(answer_uri)

    @property
    def ready_selections(self) -> tuple:
        return tuple(s for s in self.selections if s.ready)

    def counts(self) -> dict:
        by_policy = {policy: 0 for policy in POLICY_PRIORITY}
        for selection in self.selections:
            if selection.evidence_policy:
                by_policy[selection.evidence_policy] += 1
        levels = {LEVEL_NOT_COVERED: 0, LEVEL_L0: 0, LEVEL_L1: 0, LEVEL_L2: 0}
        eligible_levels = dict(levels)
        bases: dict = {}
        for selection in self.ready_selections:
            if selection.table is None:
                continue
            for level, count in selection.table.level_counts().items():
                levels[level] += count
            for level, count in selection.table.level_counts(
                    eligible_only=True).items():
                eligible_levels[level] += count
            for basis, count in selection.table.exclusion_basis_counts().items():
                bases[basis] = bases.get(basis, 0) + count
        mcq_levels: dict = {}
        for selection in self.ready_selections:
            if selection.algorithm_selected:
                key = selection.mcq_evidence_level
                mcq_levels[key] = mcq_levels.get(key, 0) + 1
        return {
            "primary_answer_denominator": len(self.selections),
            "primary_ready_for_rationale_selection": len(self.ready_selections),
            "primary_ranked_candidate_total": sum(
                a.candidate_count for a in self.answers),
            "algorithm_selected_strict_l2": by_policy[POLICY_STRICT_L2],
            "algorithm_selected_main_l1": by_policy[POLICY_MAIN_L1],
            "algorithm_selected_diagnostic_l0_only": by_policy[
                POLICY_DIAGNOSTIC_L0],
            "mcq_evidence_level_counts": dict(sorted(mcq_levels.items())),
            "eligible_for_main_corpus": sum(
                1 for s in self.selections if s.eligible_for_main_corpus),
            "eligible_for_diagnostic_corpus": sum(
                1 for s in self.selections if s.eligible_for_diagnostic_corpus),
            "fallback_class_requests": sum(
                1 for s in self.selections if s.requires_fallback_class),
            "primary_not_ready": sum(
                1 for s in self.selections
                if s.status == SELECTION_PRIMARY_NOT_READY),
            "fact_candidate_level_incidences_all_facts": levels,
            "fact_candidate_level_incidences_eligible_facts": eligible_levels,
            "exclusion_basis_incidences_all_facts": dict(sorted(bases.items())),
            "publishable_final_mcqs": 0,
            "manual_interventions": 0,
        }


def run_rationale_v3(
    *,
    prompt8d_dir: str | Path = FROZEN_PROMPT8D_DIR,
    predicate_policy_path: str | Path = PREDICATE_POLICY_PATH,
    evidence_rules_path: str | Path = EVIDENCE_RULES_PATH,
    semantic_policy_path: str | Path = SEMANTIC_POLICY_PATH,
    semantic_cache_path: str | Path = DEFAULT_SEMANTIC_INDEX_CACHE,
    k: int = DEFAULT_K,
    rho: int = DEFAULT_RHO,
    pool_policy: PoolPolicy = PoolPolicy(),
    run_reduced_arm: bool = True,
    verbose: bool = True,
) -> RationaleV3Run:
    """Consume the frozen Prompt-8D handoff and select distractors under R1.

    Strictly offline. Makes no HTTP or SPARQL call, loads no spaCy or SBERT
    model, retrieves no DBpedia abstract, runs no class selection, rebuilds no
    graph, recomputes no LRoleSim score, and does not open the pinned pickle.
    """
    guard = OfflineGuard()
    guard.install()
    timings: list = []

    def stage(name: str, started: float, detail: str = "") -> None:
        elapsed = time.perf_counter() - started
        timings.append(StageTiming(name, elapsed,
                                   int(resource.getrusage(
                                       resource.RUSAGE_SELF).ru_maxrss), detail))
        if verbose:
            print(f"  [{name}] {elapsed:.3f}s  {detail}")

    try:
        t0 = time.perf_counter()
        protected = verify_protected_sources()
        stage("verify_protected_sources", t0,
              f"{len(protected)} frozen sources byte-identical")

        t0 = time.perf_counter()
        inputs = load_prompt8d_handoff(prompt8d_dir)
        stage("load_prompt8d_handoff", t0,
              f"{len(inputs.handoffs)} primary handoffs, "
              f"{len(inputs.answer_facts)} Answer facts, "
              f"{len(inputs.candidate_facts)} candidate facts")

        t0 = time.perf_counter()
        quality_policy = load_quality_policy(predicate_policy_path)
        base_rules = load_evidence_rules(evidence_rules_path)
        semantic_index = load_pilot_semantic_index(
            inputs, policy_path=semantic_policy_path,
            cache_path=semantic_cache_path)
        stage("load_policies", t0,
              f"{len(quality_policy.hard_reject_predicates)} rejected "
              f"predicates, semantic index available={semantic_index.available}")

        t0 = time.perf_counter()
        answers = build_answer_inputs(inputs)
        rulebook, observations = derive_rulebook(
            answers, base=base_rules, semantic_index=semantic_index,
            rejected_predicates=quality_policy.hard_reject_predicates)
        counts = rulebook.counts()
        stage("derive_annotation_rules", t0,
              f"{counts['total_rules']} rule candidates, "
              f"{counts['active_annotation_rules']} active annotations, "
              f"{counts['active_l2_rules']} active L2")

        t0 = time.perf_counter()
        selections: list = []
        primary_order: list = []
        by_uri = {a.answer_uri: a for a in answers}
        for handoff in sorted(inputs.handoffs, key=lambda h: int(h["pilot_slot"])):
            answer_uri = str(handoff["answer_uri"])
            primary_order.append(answer_uri)
            if answer_uri in by_uri:
                selections.append(select_for_answer(
                    by_uri[answer_uri], semantic_index=semantic_index,
                    rulebook=rulebook, quality_policy=quality_policy,
                    k=k, rho=rho, pool_policy=pool_policy))
            else:
                selections.append(not_ready_selection(answer_uri, k=k, rho=rho))
        stage("evidence_and_combination_search", t0,
              f"{sum(a.candidate_count for a in answers)} candidates, "
              f"{sum(len(a.answer_facts) for a in answers)} Answer facts")

        t0 = time.perf_counter()
        arms: dict = {}
        if run_reduced_arm:
            for arm in COMPARISON_ARMS:
                arms[arm] = run_ablation_arm(
                    arm, answers, base_rules=base_rules,
                    semantic_index=semantic_index, quality_policy=quality_policy,
                    k=k, rho=rho, pool_policy=pool_policy)
        stage("ablation_arms", t0,
              f"{len(arms)} arms x {len(answers)} Answers re-selected "
              f"({', '.join(COMPARISON_ARMS)})")

        t0 = time.perf_counter()
        diagnostic_input = build_diagnostic_input(inputs)
        diagnostic_selection = (
            select_for_answer(diagnostic_input, semantic_index=semantic_index,
                              rulebook=rulebook, quality_policy=quality_policy,
                              k=k, rho=rho, pool_policy=pool_policy)
            if diagnostic_input is not None else None)
        stage("diagnostic_namespace", t0,
              f"{diagnostic_input.candidate_count if diagnostic_input else 0} "
              f"diagnostic candidates, held separately")

        return RationaleV3Run(
            mode="pilot-rationale-v3-r1", ranker_name=EXPECTED_RANKER_NAME,
            k=k, rho=rho, inputs=inputs,
            contract_checks=tuple(inputs.contract_checks), answers=answers,
            selections=tuple(selections), primary_order=tuple(primary_order),
            comparison_arms=arms, diagnostic_input=diagnostic_input,
            diagnostic_selection=diagnostic_selection,
            semantic_index=semantic_index, rulebook=rulebook,
            base_rulebook=base_rules, quality_policy=quality_policy,
            scope_observations=observations, protected_sources=protected,
            guard_record=guard.as_record(),
            forbidden_modules=tuple(loaded_forbidden_modules()),
            timings=tuple(timings), pool_policy=pool_policy)
    finally:
        guard.uninstall()


# --- 9) OUTPUT 1 — THE PRIMARY SUMMARY ---------------------------------------

SUMMARY_FIELDS = (
    "pilot_slot", "answer_uri", "display_label", "primary_or_diagnostic",
    "diagnostic_only", "excluded_from_primary_policy_metrics",
    "selected_class_uri", "graph_fingerprint", "ranker_name", "measure",
    "lrolesim_beta", "iterations", "iteration_mode", "k", "rho",
    "ready_for_rationale_selection", "ranked_candidate_count",
    "answer_fact_count", "eligible_answer_fact_count",
    "search_scope", "pool_candidate_count", "original_combination_count",
    "enumerated_combination_count", "global_optimality_claim",
    "strict_l2_feasible_count", "main_l1_feasible_count",
    "diagnostic_l0_feasible_count",
    "selection_status", "evidence_policy", "mcq_evidence_level",
    "distractor_1_uri", "distractor_2_uri", "distractor_3_uri",
    "distractor_ranks", "distractor_lrolesim_scores",
    "per_distractor_evidence_level",
    "minimum_rationale_size", "minimum_rationale_count_before_quality_ranking",
    "rationale_predicates", "rationale_directions", "rationale_counterparts",
    "L2_coverage_incidence_count", "L1_coverage_incidence_count",
    "L0_coverage_incidence_count", "scoped_empirical_incidence_count",
    "exclusion_basis", "semantic_check_status",
    "semantic_granularity_risk_incidences", "hard_leakage_in_rationale",
    "local_candidate_pool_anonymity_count", "direct_identifier_flag",
    "generation_is_automatic", "manual_intervention_used",
    "post_generation_human_evaluation_status",
    "eligible_for_main_corpus", "eligible_for_diagnostic_corpus",
    "eligible_for_human_study", "publishable_final", "fallback_status",
)


def _selected_rationale_facts(selection: AnswerSelection) -> tuple:
    """The canonical keys of the ONE selected rationale, or ()."""
    best = selection.ranking.best if selection.ranking else None
    if best is None or selection.table is None:
        return ()
    return tuple(selection.table.facts[i].canonical_key
                 for i in best.fact_indices)


def _rationale_exclusion_bases(selection: AnswerSelection) -> tuple:
    """The exclusion bases and semantic statuses of the COVERING incidences.

    Only the (rationale fact, distractor) pairs that actually cover under the
    selected policy are summarised: a pair the fact does not cover carries no
    exclusion argument, and listing its basis would describe evidence the
    rationale never used.
    """
    best = selection.ranking.best if selection.ranking else None
    if best is None or selection.table is None or selection.selected is None:
        return ((), ())
    threshold = POLICY_MINIMUM_LEVEL[selection.evidence_policy]
    bases, statuses = set(), set()
    for index in best.fact_indices:
        for position in selection.selected.positions:
            item = selection.table.evidence[index][position]
            if level_at_least(item.level, threshold):
                bases.add(item.exclusion_basis)
                statuses.add(item.semantic_check_status)
    return (tuple(sorted(bases)), tuple(sorted(statuses)))


def _summary_row(run: RationaleV3Run, answer_uri: str) -> dict:
    selection = run.selection_for(answer_uri)
    handoff = next(h for h in run.inputs.handoffs if h["answer_uri"] == answer_uri)
    row = {name: "" for name in SUMMARY_FIELDS}
    row.update({
        "pilot_slot": handoff["pilot_slot"],
        "answer_uri": answer_uri,
        "display_label": handoff["display_label"],
        "primary_or_diagnostic": "primary",
        "diagnostic_only": _b(False),
        "excluded_from_primary_policy_metrics": _b(False),
        "selected_class_uri": handoff["selected_class_uri"] or "",
        "graph_fingerprint": handoff["graph_fingerprint"] or "",
        "ranker_name": handoff["ranker_name"],
        "measure": handoff["measure"] or "",
        "lrolesim_beta": ("" if handoff["lrolesim_beta"] is None
                          else repr(float(handoff["lrolesim_beta"]))),
        "iterations": ("" if handoff["iterations"] is None
                       else handoff["iterations"]),
        "iteration_mode": handoff["iteration_mode"] or "",
        "k": run.k,
        "rho": run.rho,
        "ready_for_rationale_selection": _b(selection.ready),
        "ranked_candidate_count": handoff["ranked_candidate_count"],
        "answer_fact_count": 0,
        "eligible_answer_fact_count": 0,
        "selection_status": selection.status,
        "evidence_policy": selection.evidence_policy or "",
        "generation_is_automatic": _b(True),
        "manual_intervention_used": _b(False),
        "post_generation_human_evaluation_status": HUMAN_EVALUATION_NOT_STARTED,
        "eligible_for_main_corpus": _b(selection.eligible_for_main_corpus),
        "eligible_for_diagnostic_corpus": _b(
            selection.eligible_for_diagnostic_corpus),
        "eligible_for_human_study": _b(selection.eligible_for_human_study),
        "publishable_final": _b(False),
        "fallback_status": selection.fallback_status,
    })
    if not selection.ready or selection.table is None or selection.pool is None:
        return row

    table = selection.table
    row["answer_fact_count"] = table.fact_count
    row["eligible_answer_fact_count"] = len(table.eligible_fact_indices)
    row["search_scope"] = selection.pool.scope
    row["pool_candidate_count"] = len(selection.pool.positions)
    row["original_combination_count"] = selection.pool.original_combination_count
    row["enumerated_combination_count"] = (
        selection.pool.enumerated_combination_count)
    row["global_optimality_claim"] = _b(selection.pool.global_optimality_claim)
    for policy, column in ((POLICY_STRICT_L2, "strict_l2_feasible_count"),
                           (POLICY_MAIN_L1, "main_l1_feasible_count"),
                           (POLICY_DIAGNOSTIC_L0, "diagnostic_l0_feasible_count")):
        search = selection.searches.get(policy)
        row[column] = 0 if search is None else len(search.feasible(run.rho))

    if selection.selected is not None and selection.ranking is not None:
        best = selection.ranking.best
        for index, uri in enumerate(selection.selected.candidate_uris, start=1):
            row[f"distractor_{index}_uri"] = uri
        row["distractor_ranks"] = _join(selection.selected.ranks)
        row["distractor_lrolesim_scores"] = _join(
            _fmt_score(s) for s in selection.selected.scores)
        row["minimum_rationale_size"] = selection.ranking.size
        row["minimum_rationale_count_before_quality_ranking"] = (
            selection.ranking.minimum_rationale_count)
        row["mcq_evidence_level"] = selection.ranking.mcq_evidence_level
        keys = _selected_rationale_facts(selection)
        row["rationale_predicates"] = _join(k[0] for k in keys)
        row["rationale_directions"] = _join(k[1] for k in keys)
        row["rationale_counterparts"] = _join(k[2] for k in keys)
        bases, statuses = _rationale_exclusion_bases(selection)
        row["exclusion_basis"] = _join(bases)
        row["semantic_check_status"] = _join(statuses)
        if best is not None:
            row["per_distractor_evidence_level"] = _join(
                best.per_candidate_best_level)
            row["L2_coverage_incidence_count"] = best.l2_incidences
            row["L1_coverage_incidence_count"] = best.l1_incidences
            row["L0_coverage_incidence_count"] = best.l0_incidences
            row["scoped_empirical_incidence_count"] = (
                best.scoped_empirical_incidences)
            row["semantic_granularity_risk_incidences"] = (
                best.granularity_risk_incidences)
            row["hard_leakage_in_rationale"] = _b(any(
                table.quality[i].leakage.hard_leak for i in best.fact_indices))
            row["local_candidate_pool_anonymity_count"] = best.local_anonymity_count
            row["direct_identifier_flag"] = _b(best.direct_identifier_flag)
    return row


def write_summary(run: RationaleV3Run, out_dir: Path) -> None:
    """Exactly nine primary Answer rows. Sulfuric acid stays a primary failure."""
    rows = [_summary_row(run, uri) for uri in run.primary_order]
    if len(rows) != EXPECTED_PRIMARY_ANSWER_COUNT:
        raise RationaleV3Error(
            f"the primary summary must hold exactly "
            f"{EXPECTED_PRIMARY_ANSWER_COUNT} rows, built {len(rows)}")
    _write_csv(out_dir / "rationale_v3_r1_summary.csv", SUMMARY_FIELDS, rows)


# --- 10) OUTPUT 2 — THE SELECTED MCQs ----------------------------------------

def _selected_mcq_record(run: RationaleV3Run, selection: AnswerSelection) -> dict:
    """One self-contained record per selected MCQ.

    Everything a reader needs about this question lives here: choices, ranks and
    frozen scores, the selected rationale with per-distractor evidence,
    observational and exclusion bases, semantic safety, quality, eligibility and
    provenance. No other output repeats it.
    """
    answer = run.answer_for(selection.answer_uri)
    combination = selection.selected
    ranking = selection.ranking
    table = selection.table
    pool = selection.pool
    assert (combination is not None and ranking is not None
            and table is not None and pool is not None)
    best = ranking.best
    assert best is not None
    policy = selection.evidence_policy
    assert policy is not None

    rationale = []
    for index in best.fact_indices:
        quality = table.quality[index]
        per_distractor = []
        for bit, position in enumerate(combination.positions):
            item = table.evidence[index][position]
            per_distractor.append({
                "candidate_uri": combination.candidate_uris[bit],
                "evidence_level": item.level,
                "reason_code": item.reason_code,
                "exclusion_basis": item.exclusion_basis,
                "semantic_check_status": item.semantic_check_status,
                "granularity_risk": item.granularity_risk_status,
                "candidate_object_uris": list(item.candidate_object_uris),
                "applied_rule_id": item.applied_rule_id,
                "evidence_proof": (None if item.proof is None
                                   else item.proof.as_record()),
                "prompt8e_equivalent_status":
                    PROMPT8E_STATUS_FOR_REASON_CODE.get(item.reason_code, ""),
            })
        count, ratio, direct = table.local_anonymity((index,))
        rationale.append({
            **table.propositions[index].as_record(),
            "display_label": quality.display_label,
            "per_distractor_evidence": per_distractor,
            "predicate_policy_result": ("ACCEPTED" if quality.predicate_ok
                                        else quality.predicate_reason),
            "object_policy_result": ("ACCEPTED" if quality.object_ok
                                     else quality.object_reason),
            "leakage_result": quality.leakage.reason_code,
            "template_id": quality.template_id,
            "verbalizable": quality.verbalizable,
            "pedagogical_tier": quality.pedagogical_tier,
            "local_candidate_pool_anonymity_count": count,
            "local_candidate_pool_anonymity_ratio": round(ratio, 6),
            "direct_identifier_flag": direct,
        })

    return {
        "answer_uri": selection.answer_uri,
        "display_label": answer.display_label,
        "pilot_slot": answer.pilot_slot,
        "primary_or_diagnostic": answer.primary_or_diagnostic,
        "selected_class_uri": answer.selected_class_uri,
        "graph_fingerprint": answer.graph_fingerprint,
        "ranker_name": answer.ranker_name,
        "measure": answer.measure,
        "lrolesim_beta": answer.lrolesim_beta,
        "iterations": answer.iterations,
        "iteration_mode": answer.iteration_mode,
        "k": selection.k,
        "rho": selection.rho,
        "evidence_policy": policy,
        "evidence_policy_note": POLICY_NOTE[policy],
        "mcq_evidence_level": ranking.mcq_evidence_level,
        "mcq_evidence_level_note": MCQ_LEVEL_NOTE,
        "rationale_min_level": ranking.achieved_min_level,
        "set_cover_algorithm": SET_COVER_ALGORITHM,
        "set_cover_complexity": SET_COVER_COMPLEXITY,
        "distractors": [
            {
                "position": position,
                "candidate_uri": uri,
                "original_lrolesim_rank": rank,
                "original_lrolesim_score": score,
                "candidate_local_index": next(
                    c.candidate_local_index for c in answer.ranked_candidates
                    if c.canonical_candidate_uri == uri),
                "in_provisional_lrolesim_top3": rank <= 3,
                "best_evidence_level": best.per_candidate_best_level[position],
            }
            for position, (uri, rank, score) in enumerate(
                zip(combination.candidate_uris, combination.ranks,
                    combination.scores))
        ],
        "lrolesim_score_sum": combination.score_sum,
        "lrolesim_score_min": combination.score_min,
        "candidate_rank_sum": combination.rank_sum,
        "replaced_provisional_top3": sorted(combination.ranks) != [1, 2, 3],
        **pool.as_record(),
        "pool_optimality_note": POOL_OPTIMALITY_NOTE,
        "selected_rationale": rationale,
        "selected_rationale_summary": best.as_record(),
        "selected_rationale_quality_key": [repr(part)
                                           for part in best.ranking_key()],
        "minimum_rationale_size": ranking.size,
        "minimum_rationale_count_before_quality_ranking":
            ranking.minimum_rationale_count,
        "minimum_rationale_count_enumerated": ranking.enumerated_count,
        "minimum_rationale_enumeration_scope": ranking.enumeration_scope,
        "coverage_mask": combination.coverage_mask,
        "coverage_count": combination.coverage_count,
        "full_coverage": combination.full_coverage,
        "selection_status": selection.status,
        "eligible_for_main_corpus": selection.eligible_for_main_corpus,
        "eligible_for_diagnostic_corpus": selection.eligible_for_diagnostic_corpus,
        "eligible_for_human_study": selection.eligible_for_human_study,
        "fallback_status": selection.fallback_status,
        "algorithm_selected_distractor": True,
        **AUTOMATIC_GENERATION_FIELDS,
        "publishable_final_note": PUBLISHABLE_FINAL_NOTE,
        "open_world_note": MULTI_VALUED_PREDICATE_NOTE,
        "local_candidate_pool_anonymity_note": (
            "computed over the Answer plus the COMPLETE ranked candidate pool "
            "of the selected class; it is not a statement about every entity of "
            "that class in remote DBpedia"),
        "input_package_sha256": dict(run.inputs.input_sha256),
        "input_package_zip_sha256": FROZEN_PROMPT8D_ZIP_SHA256,
        "pinned_local_kg_sha256": PINNED_LOCAL_KG_SHA256,
    }


def write_selected_mcqs(run: RationaleV3Run, out_dir: Path) -> None:
    _write_jsonl(out_dir / "selected_mcqs_v3_r1.jsonl",
                 [_selected_mcq_record(run, s) for s in run.selections
                  if s.algorithm_selected])


# --- 11) OUTPUT 3 — THE TYPED EVIDENCE AUDIT ---------------------------------
# One file, one `record_type` discriminator. Prompt 8F wrote the same evidence
# into per_candidate_evidence, evidence_proofs, semantic_relation_audit,
# quality_filter_audit, predicate_policy_audit, empirical_rule_candidates,
# all_minimum_rationale_candidates and combination_search_audit; this replaces
# all eight without dropping a field that carries scientific weight.

def _answer_fact_evidence_records(run: RationaleV3Run) -> list:
    records: list = []
    for selection in run.selections:
        table = selection.table
        if table is None:
            continue
        for index, fact in enumerate(table.facts):
            quality = table.quality[index]
            level_counts: dict = {}
            basis_counts: dict = {}
            per_candidate: list = []
            for position, candidate in enumerate(table.candidates):
                item = table.evidence[index][position]
                level_counts[item.level] = level_counts.get(item.level, 0) + 1
                basis_counts[item.exclusion_basis] = basis_counts.get(
                    item.exclusion_basis, 0) + 1
                per_candidate.append({
                    "candidate_rank": candidate.rank,
                    "candidate_uri": candidate.canonical_candidate_uri,
                    "evidence_level": item.level,
                    "reason_code": item.reason_code,
                    "exclusion_basis": item.exclusion_basis,
                    "semantic_check_status": item.semantic_check_status,
                    "granularity_risk": item.granularity_risk_status,
                    "applied_rule_id": item.applied_rule_id,
                    "candidate_object_count": len(item.candidate_object_uris),
                    "prompt8e_equivalent_status":
                        PROMPT8E_STATUS_FOR_REASON_CODE.get(item.reason_code, ""),
                })
            records.append({
                "record_type": "answer_fact_evidence",
                "answer_uri": selection.answer_uri,
                "graph_fingerprint": table.graph_fingerprint,
                "scope": table.scope,
                "fact_index": index,
                "predicate_uri": fact.predicate_uri,
                "direction": fact.direction,
                "counterpart_uri": fact.counterpart_uri,
                "candidate_count": table.candidate_count,
                "evidence_level_counts": level_counts,
                "exclusion_basis_counts": basis_counts,
                "quality": quality.as_record(),
                "per_candidate": per_candidate,
            })
    return records


def _evidence_proof_records(run: RationaleV3Run) -> list:
    """Every EvidenceProof the run built. Empty when no L2 case was proved."""
    records: list = []
    for selection in run.selections:
        table = selection.table
        if table is None:
            continue
        for index, row in enumerate(table.evidence):
            for position, item in enumerate(row):
                if item.proof is not None:
                    records.append({
                        "record_type": "evidence_proof",
                        "answer_uri": selection.answer_uri,
                        "fact_index": index,
                        "candidate_uri":
                            table.candidates[position].canonical_candidate_uri,
                        "evidence_level": item.level,
                        "reason_code": item.reason_code,
                        **item.proof.as_record(),
                    })
    return records


def _semantic_relation_records(run: RationaleV3Run) -> list:
    """A summary header, then every pair whose relation is not
    UNRELATED_OR_UNKNOWN. Emitting the millions of "no path found" pairs would
    bury the findings; the header carries their count."""
    counts: dict = {}
    found: dict = {}
    for selection in run.selections:
        table = selection.table
        if table is None:
            continue
        for index, row in enumerate(table.evidence):
            for position, item in enumerate(row):
                for relation in item.relations:
                    name = relation.relation.relation
                    counts[name] = counts.get(name, 0) + 1
                    if name == RELATION_UNRELATED_OR_UNKNOWN:
                        continue
                    key = (relation.relation.claim_object_uri,
                           relation.candidate_object_uri, name)
                    found.setdefault(key, {
                        "record_type": "semantic_relation",
                        "answer_uri": selection.answer_uri,
                        "predicate_uri": table.facts[index].predicate_uri,
                        "direction": table.facts[index].direction,
                        "candidate_uri":
                            table.candidates[position].canonical_candidate_uri,
                        **relation.as_record(),
                    })
    header = {
        "record_type": "semantic_relation_summary",
        "relation_counts": dict(sorted(counts.items())),
        "distinct_non_trivial_pairs": len(found),
        "parent_child_note": PARENT_CHILD_NOTE,
        **run.semantic_index.as_record(),
    }
    return [header] + [found[key] for key in sorted(found)]


def _annotation_rule_records(run: RationaleV3Run) -> list:
    """Every derived scoped-empirical rule candidate with its activation
    status. In R1 an active rule only sets exclusion_basis=SCOPED_EMPIRICAL."""
    return [{"record_type": "scoped_empirical_rule", **rule.as_record()}
            for rule in run.rulebook.rules]


def _combination_search_records(run: RationaleV3Run) -> list:
    records: list = []
    for selection in run.ready_selections:
        if selection.pool is None or selection.table is None:
            continue
        answer = run.answer_for(selection.answer_uri)
        records.append({
            "record_type": "combination_search",
            "answer_uri": selection.answer_uri,
            "display_label": answer.display_label,
            "graph_fingerprint": answer.graph_fingerprint,
            "selected_class_uri": answer.selected_class_uri,
            "k": selection.k,
            "rho": selection.rho,
            "candidate_count": answer.candidate_count,
            "answer_fact_count": selection.table.fact_count,
            "eligible_answer_fact_count": len(
                selection.table.eligible_fact_indices),
            **selection.pool.as_record(),
            "pool_optimality_note": POOL_OPTIMALITY_NOTE,
            "provisional_lrolesim_top3_ranks": [1, 2, 3],
            "provisional_top3_treated_as_final": False,
            "per_policy": {
                policy: {
                    "full_coverage_combination_count": len(
                        search.full_coverage_outcomes),
                    "feasible_combination_count": len(
                        search.feasible(selection.rho)),
                    "candidates_with_any_coverage":
                        search.candidates_with_any_coverage,
                    "best_partial": (None if search.best_partial is None
                                     else search.best_partial.as_record()),
                }
                for policy, search in sorted(selection.searches.items())},
            "selected_evidence_policy": selection.evidence_policy or "",
            "selected_objective_key": (
                None if selection.selected is None else {
                    "negated_lrolesim_score_sum":
                        repr(-selection.selected.score_sum),
                    "negated_lrolesim_score_min":
                        repr(-selection.selected.score_min),
                    "minimum_rationale_size":
                        selection.selected.minimum_rationale_size,
                    "candidate_rank_sum": selection.selected.rank_sum,
                    "candidate_uris": list(selection.selected.candidate_uris),
                }),
            "candidate_roster_source": (
                "the frozen Prompt-8D candidate_ranking_handoff.jsonl; it is "
                "not copied here"),
            "alternative_minimum_rationales": [
                {"quality_rank": position + 1, "is_selected": position == 0,
                 **choice.as_record()}
                for position, choice in enumerate(
                    selection.ranking.ranked[:AUDIT_TOP_RATIONALES])
            ] if selection.ranking else [],
            "note": ("Feasibility is the exact set-cover result under the "
                     "active evidence policy, never the weaker condition that "
                     "each candidate merely has some fact the Answer's fact set "
                     "does not match."),
        })
    return records


def write_evidence_audit(run: RationaleV3Run, out_dir: Path) -> None:
    _write_jsonl(out_dir / "evidence_audit_v3_r1.jsonl", [
        *_semantic_relation_records(run),
        *_annotation_rule_records(run),
        *_answer_fact_evidence_records(run),
        *_evidence_proof_records(run),
        *_combination_search_records(run),
    ])


# --- 12) OUTPUT 4 — THE FOUR-WAY COMPARISON ----------------------------------

COMPARISON_FIELDS = (
    "answer_uri", "display_label",
    "prompt8e_status", "prompt8f_status", "r1_reduced_status", "r1_status",
    "prompt8e_evidence_policy", "prompt8f_evidence_policy",
    "r1_reduced_evidence_policy", "r1_evidence_policy",
    "prompt8f_evidence_level", "r1_reduced_mcq_level", "r1_mcq_level",
    "prompt8e_distractors", "prompt8f_distractors", "r1_reduced_distractors",
    "r1_distractors",
    "distractor_set_identical_8e_vs_r1", "distractor_set_identical_8f_vs_r1",
    "distractor_set_identical_reduced_vs_r1",
    "prompt8e_rationale", "prompt8f_rationale", "r1_reduced_rationale",
    "r1_rationale",
    "rationale_identical_8e_vs_r1", "rationale_identical_8f_vs_r1",
    "rationale_identical_reduced_vs_r1",
    "prompt8e_minimum_rationale_size", "prompt8f_minimum_rationale_size",
    "r1_minimum_rationale_size",
    "r1_quality_off_rationale", "r1_quality_off_distractors",
    "r1_semantic_off_mcq_level", "r1_semantic_off_eligible_for_main_corpus",
    "taxonomy_effect", "quality_filter_effect", "semantic_safety_effect",
    "distractor_search_effect",
    "r1_rejected_the_prompt8e_rationale", "r1_rejection_reasons",
    "r1_eligible_for_main_corpus", "r1_fallback_status",
)


def _previous_rationale_keys(records: Sequence[Mapping[str, object]]) -> tuple:
    """Canonical keys from a frozen package.

    Prompt 8E wrote `counterpart_uri`; Prompt 8F wrote the proposition, whose
    object is `source_object_uri`. Both spellings name the same fact, so both
    are accepted rather than one package being silently read as empty.
    """
    keys = []
    for record in records:
        counterpart = record.get("counterpart_uri") or record.get(
            "source_object_uri") or record.get("claim_object_uri")
        keys.append((str(record["predicate_uri"]), str(record["direction"]),
                     str(counterpart)))
    return tuple(sorted(keys))


def _load_previous_package(directory: Path, summary_name: str,
                           rationale_name: str) -> tuple[dict, dict]:
    """Read a frozen package as DATA. Never re-executed, never modified."""
    summary: dict = {}
    path = directory / summary_name
    if path.is_file():
        for row in _read_csv(path):
            summary[row["answer_uri"]] = row
    rationales: dict = {}
    path = directory / rationale_name
    if path.is_file():
        for record in _read_jsonl(path):
            rationales.setdefault(str(record["answer_uri"]), []).append(record)
    return (summary, rationales)


def _format_keys(keys: Sequence[Sequence[str]]) -> str:
    return _join(f"{k[0]} ({k[1]}) -> {k[2]}" for k in keys)


def write_comparison(run: RationaleV3Run, out_dir: Path,
                     prompt8e_dir: str | Path = FROZEN_PROMPT8E_DIR,
                     prompt8f_dir: str | Path = FROZEN_PROMPT8F_DIR) -> None:
    """Prompt 8E, Prompt 8F, R1-reduced and R1-full, row by row.

    Prompt 8E and Prompt 8F are read as DATA; neither is re-executed or
    modified. Each effect is measured against the arm that isolates it, so the
    quality and semantic factors are never confounded:

      taxonomy_effect          8F and R1 disagree on the evidence tier or the
                               achieved level, with the same quality and
                               semantic layers active in both;
      quality_filter_effect    the quality_off arm chose a different rationale
                               or distractor set from the full run;
      semantic_safety_effect   the semantic_off arm reached a different MCQ
                               level, main-corpus eligibility or rationale;
      distractor_search_effect the selected candidate triple changed between 8F
                               and R1 after re-running the exact search.
    """
    old8e, old8e_facts = _load_previous_package(
        Path(prompt8e_dir), "rationale_selection_summary.csv",
        "selected_rationales.jsonl")
    old8f, old8f_facts = _load_previous_package(
        Path(prompt8f_dir), "rationale_v3_summary.csv",
        "selected_rationales_v3.jsonl")

    rows: list = []
    for answer_uri in run.primary_order:
        selection = run.selection_for(answer_uri)
        arms = {name: run.comparison_arms.get(name, {}).get(answer_uri)
                for name in COMPARISON_ARMS}
        reduced = arms[ARM_REDUCED]
        quality_off = arms[ARM_QUALITY_OFF]
        semantic_off = arms[ARM_SEMANTIC_OFF]
        row8e = old8e.get(answer_uri, {})
        row8f = old8f.get(answer_uri, {})

        keys8e = _previous_rationale_keys(old8e_facts.get(answer_uri, []))
        keys8f = _previous_rationale_keys(old8f_facts.get(answer_uri, []))
        keys_r1 = tuple(sorted(_selected_rationale_facts(selection)))
        keys_reduced = (tuple(sorted(_selected_rationale_facts(reduced)))
                        if reduced else ())
        keys_quality_off = (tuple(sorted(_selected_rationale_facts(quality_off)))
                            if quality_off else ())

        d8e = tuple(u for u in (row8e.get(f"distractor_{i}_uri", "")
                                for i in (1, 2, 3)) if u)
        d8f = tuple(u for u in (row8f.get(f"distractor_{i}_uri", "")
                                for i in (1, 2, 3)) if u)
        d_r1 = (selection.selected.candidate_uris if selection.selected else ())
        d_reduced = (reduced.selected.candidate_uris
                     if reduced and reduced.selected else ())
        d_quality_off = (quality_off.selected.candidate_uris
                         if quality_off and quality_off.selected else ())

        # Which Prompt-8E rationale facts R1's hard filters remove.
        reasons: list = []
        rejected = ""
        if old8e_facts.get(answer_uri) and selection.table is not None:
            index_by_key = {f.canonical_key: i
                            for i, f in enumerate(selection.table.facts)}
            for key in keys8e:
                index = index_by_key.get(tuple(key))
                if index is None:
                    reasons.append("FACT_NOT_PRESENT_IN_R1_TABLE")
                    continue
                quality = selection.table.quality[index]
                if not quality.eligible:
                    reasons.extend(quality.rejection_reasons)
            rejected = _b(bool(reasons))

        policy8f = row8f.get("evidence_policy", "")
        level8f = row8f.get("evidence_level", "")
        taxonomy = bool(row8f) and (
            (policy8f or "") != (selection.evidence_policy or "")
            or (level8f or "") != (selection.ranking.achieved_min_level
                                   if selection.ranking else ""))
        quality_effect = bool(quality_off) and (
            keys_quality_off != keys_r1 or set(d_quality_off) != set(d_r1))
        semantic_effect = bool(semantic_off) and (
            semantic_off.mcq_evidence_level != selection.mcq_evidence_level
            or semantic_off.eligible_for_main_corpus
            != selection.eligible_for_main_corpus
            or tuple(sorted(_selected_rationale_facts(semantic_off))) != keys_r1)
        search_effect = bool(d8f) and bool(d_r1) and set(d8f) != set(d_r1)

        rows.append({
            "answer_uri": answer_uri,
            "display_label": row8f.get("display_label",
                                       row8e.get("display_label", "")),
            "prompt8e_status": row8e.get("selection_status", ""),
            "prompt8f_status": row8f.get("selection_status", ""),
            "r1_reduced_status": reduced.status if reduced else "",
            "r1_status": selection.status,
            "prompt8e_evidence_policy": row8e.get("evidence_policy", ""),
            "prompt8f_evidence_policy": policy8f,
            "r1_reduced_evidence_policy": (reduced.evidence_policy or ""
                                           if reduced else ""),
            "r1_evidence_policy": selection.evidence_policy or "",
            "prompt8f_evidence_level": level8f,
            "r1_reduced_mcq_level": (reduced.mcq_evidence_level if reduced
                                     and reduced.algorithm_selected else ""),
            "r1_mcq_level": (selection.mcq_evidence_level
                             if selection.algorithm_selected else ""),
            "prompt8e_distractors": _join(d8e),
            "prompt8f_distractors": _join(d8f),
            "r1_reduced_distractors": _join(d_reduced),
            "r1_distractors": _join(d_r1),
            "distractor_set_identical_8e_vs_r1": _b(
                bool(d8e) and bool(d_r1) and set(d8e) == set(d_r1)),
            "distractor_set_identical_8f_vs_r1": _b(
                bool(d8f) and bool(d_r1) and set(d8f) == set(d_r1)),
            "distractor_set_identical_reduced_vs_r1": _b(
                bool(d_reduced) and bool(d_r1) and set(d_reduced) == set(d_r1)),
            "prompt8e_rationale": _format_keys(keys8e),
            "prompt8f_rationale": _format_keys(keys8f),
            "r1_reduced_rationale": _format_keys(keys_reduced),
            "r1_rationale": _format_keys(keys_r1),
            "rationale_identical_8e_vs_r1": _b(bool(keys8e)
                                               and keys8e == keys_r1),
            "rationale_identical_8f_vs_r1": _b(bool(keys8f)
                                               and keys8f == keys_r1),
            "rationale_identical_reduced_vs_r1": _b(bool(keys_reduced)
                                                    and keys_reduced == keys_r1),
            "prompt8e_minimum_rationale_size": row8e.get(
                "minimum_rationale_size", ""),
            "prompt8f_minimum_rationale_size": row8f.get(
                "minimum_rationale_size", ""),
            "r1_minimum_rationale_size": (selection.ranking.size
                                          if selection.ranking else ""),
            "r1_quality_off_rationale": _format_keys(keys_quality_off),
            "r1_quality_off_distractors": _join(d_quality_off),
            "r1_semantic_off_mcq_level": (
                semantic_off.mcq_evidence_level
                if semantic_off and semantic_off.algorithm_selected else ""),
            "r1_semantic_off_eligible_for_main_corpus": (
                _b(semantic_off.eligible_for_main_corpus)
                if semantic_off else ""),
            "taxonomy_effect": _b(taxonomy),
            "quality_filter_effect": _b(quality_effect),
            "semantic_safety_effect": _b(semantic_effect),
            "distractor_search_effect": _b(search_effect),
            "r1_rejected_the_prompt8e_rationale": rejected,
            "r1_rejection_reasons": _join(sorted(set(reasons))),
            "r1_eligible_for_main_corpus": _b(selection.eligible_for_main_corpus),
            "r1_fallback_status": selection.fallback_status,
        })
    _write_csv(out_dir / "prompt8e_v3_v3r1_comparison.csv",
               COMPARISON_FIELDS, rows)


# --- 13) OUTPUT 5 — FALLBACK CLASS REQUESTS ----------------------------------

def write_fallback_class_requests(run: RationaleV3Run, out_dir: Path) -> None:
    """Emitted and stopped at: no fallback class is executed in this task."""
    records: list = []
    for selection in run.selections:
        if not selection.requires_fallback_class:
            continue
        answer = run.answer_for(selection.answer_uri)
        best_diagnostic = None
        if selection.selected is not None and selection.ranking is not None:
            best_diagnostic = {
                "evidence_policy": selection.evidence_policy,
                "mcq_evidence_level": selection.ranking.mcq_evidence_level,
                "distractor_uris": list(selection.selected.candidate_uris),
                "distractor_ranks": list(selection.selected.ranks),
                "minimum_rationale_size": selection.ranking.size,
            }
        else:
            for policy in POLICY_PRIORITY:
                search = selection.searches.get(policy)
                if search is not None and search.best_partial is not None:
                    best_diagnostic = {"evidence_policy": policy,
                                       **search.best_partial.as_record()}
                    break
        records.append({
            "answer_uri": selection.answer_uri,
            "display_label": answer.display_label,
            "failed_selected_class_uri": answer.selected_class_uri,
            "failure_reason": selection.fallback_status,
            "best_diagnostic_result": best_diagnostic,
            "current_graph_fingerprint": answer.graph_fingerprint,
            "candidate_count": answer.candidate_count,
            "requested_next_stage": FALLBACK_NEXT_STAGE,
            "fallback_class_executed_in_this_task": False,
            "note": ("R1 runs no class selection, candidate retrieval, "
                     "mapping, graph construction or LRoleSim for a fallback "
                     "class: Prompt 8D holds rankings for the Prompt-8C "
                     "selected class only. Exact enumeration over that class "
                     "has already performed evidence-aware candidate "
                     "replacement inside it."),
        })
    _write_jsonl(out_dir / "fallback_class_requests_v3_r1.jsonl", records)


# --- 14) MANIFESTS -----------------------------------------------------------

def _git_state() -> dict:
    def _run(args: Sequence[str]) -> str:
        try:
            return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True,
                                  capture_output=True, text=True).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""
    return {
        "branch": _run(["branch", "--show-current"]),
        "head_commit": _run(["rev-parse", "HEAD"]),
        "head_subject": _run(["log", "-1", "--format=%s"]),
        "tracked_working_tree_clean": _run(
            ["status", "--porcelain", "--untracked-files=no"]) == "",
    }


def _sulfuric_acid_diagnostic(run: RationaleV3Run) -> dict:
    """The diagnostic analysis, in its own namespace inside the manifest."""
    primary = run.selection_for(EXPECTED_PRIMARY_FAILURE_ANSWER_URI)
    payload: dict = {
        "diagnostic_only": True,
        "excluded_from_primary_policy_metrics": True,
        "answer_uri": EXPECTED_PRIMARY_FAILURE_ANSWER_URI,
        "primary_record": {
            "selection_status": primary.status,
            "ready_for_rationale_selection": primary.ready,
            "algorithm_selected_distractor": primary.algorithm_selected,
            "ranked_candidate_count": 0,
            "note": ("Sulfuric acid remains the one PRIMARY failure. The "
                     "diagnostic below is engineering evidence only and enters "
                     "no primary denominator, success rate or candidate count."),
        },
        "boundaries": {
            "counted_in_nine_answer_denominator": False,
            "counted_in_eight_ready_answer_numerator": False,
            "counted_in_primary_ranked_candidate_total": False,
            "counted_in_primary_selection_counts": False,
            "primary_failure_downgraded": False,
            "answer_replaced": False,
            "new_class_added": False,
            "publishable_final": False,
        },
        **AUTOMATIC_GENERATION_FIELDS,
    }
    diagnostic = run.diagnostic_selection
    if run.diagnostic_input is None or diagnostic is None:
        payload["diagnostic_analysis"] = None
        return payload

    best = diagnostic.ranking.best if diagnostic.ranking else None
    payload["diagnostic_analysis"] = {
        "diagnostic_class_uri": run.diagnostic_input.selected_class_uri,
        "graph_fingerprint": run.diagnostic_input.graph_fingerprint,
        "candidate_count": run.diagnostic_input.candidate_count,
        "answer_fact_count": (diagnostic.table.fact_count
                              if diagnostic.table else 0),
        "eligible_answer_fact_count": (len(diagnostic.table.eligible_fact_indices)
                                       if diagnostic.table else 0),
        "k": diagnostic.k,
        "rho": diagnostic.rho,
        "search": (diagnostic.pool.as_record() if diagnostic.pool else None),
        "per_policy_feasible_counts": {
            policy: len(search.feasible(diagnostic.rho))
            for policy, search in sorted(diagnostic.searches.items())},
        "selection_status": diagnostic.status,
        "evidence_policy": diagnostic.evidence_policy or "",
        "mcq_evidence_level": diagnostic.mcq_evidence_level,
        "selected_distractor_uris": (list(diagnostic.selected.candidate_uris)
                                     if diagnostic.selected else []),
        "selected_distractor_ranks": (list(diagnostic.selected.ranks)
                                      if diagnostic.selected else []),
        "minimum_rationale_size": (diagnostic.ranking.size
                                   if diagnostic.ranking else None),
        "selected_rationale": (best.as_record() if best else None),
        "algorithm_selected_distractor": diagnostic.algorithm_selected,
        "eligible_for_main_corpus": False,
        "eligible_for_diagnostic_corpus": diagnostic.algorithm_selected,
        "fallback_status": diagnostic.fallback_status,
        **AUTOMATIC_GENERATION_FIELDS,
    }
    return payload


def write_offline_replay_manifest(run: RationaleV3Run, out_dir: Path) -> None:
    compared = {}
    for name in REPLAY_COMPARED_FILES:
        path = out_dir / name
        compared[name] = {"sha256": sha256_file(path),
                          "size_bytes": path.stat().st_size}
    _write_json(out_dir / "offline_replay_manifest.json", {
        "mode": run.mode,
        "replay_command": (
            "python src/extract_and_select_distractors_v3.py "
            "--mode pilot-rationale-v3-r1 --output-dir <fresh directory>"),
        "byte_identical_files": list(REPLAY_COMPARED_FILES),
        "excluded_from_byte_identity": [
            "run_manifest.json (records the run clock, timings and git state)",
            "offline_replay_manifest.json (contains the hashes it verifies)",
            "implementation_report.md (narrative)",
            "loc_before_after.csv (measured outside the run)",
        ],
        "file_hashes": compared,
        "network": run.guard_record,
        "http_calls": 0,
        "sparql_calls": 0,
        "forbidden_modules_loaded_in_process": list(run.forbidden_modules),
        "forbidden_modules_note": (
            "A PROCESS-WIDE snapshot of sys.modules taken after the run. Exact "
            "for a standalone invocation, which is how this package is "
            "produced. Inside a shared pytest session the same list also "
            "reports modules other test files imported, so the test suite "
            "asserts the delta introduced by this code path instead."),
        "prompt8d_input_sha256": dict(run.inputs.input_sha256),
        "prompt8d_zip_expected_sha256": FROZEN_PROMPT8D_ZIP_SHA256,
        "prompt8e_zip_expected_sha256": FROZEN_PROMPT8E_ZIP_SHA256,
        "prompt8f_zip_expected_sha256": FROZEN_PROMPT8F_ZIP_SHA256,
        "prompt8f_parent_commit": PROMPT8F_PARENT_COMMIT,
        "pinned_local_kg_expected_sha256": PINNED_LOCAL_KG_SHA256,
        "pinned_local_kg_loaded": False,
        "semantic_index": run.semantic_index.as_record(),
        "protected_sources": run.protected_sources,
    })


def write_run_manifest(run: RationaleV3Run, out_dir: Path,
                       raw_command: Sequence[str] = ()) -> None:
    quality = run.quality_policy
    _write_json(out_dir / "run_manifest.json", {
        "task": ("Prompt 8F-R1 - corrected evidence taxonomy, exclusion-basis "
                 "axis, quality-aware selection, compact output set"),
        "mode": run.mode,
        "ranker_name": run.ranker_name,
        "raw_command": list(raw_command),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "conda_env": os.environ.get("CONDA_DEFAULT_ENV", ""),
        "git": _git_state(),
        "frozen_prompt8d_dir": str(FROZEN_PROMPT8D_DIR.relative_to(REPO_ROOT)),
        "frozen_prompt8d_zip_expected_sha256": FROZEN_PROMPT8D_ZIP_SHA256,
        "frozen_prompt8e_dir": str(FROZEN_PROMPT8E_DIR.relative_to(REPO_ROOT)),
        "frozen_prompt8e_zip_expected_sha256": FROZEN_PROMPT8E_ZIP_SHA256,
        "frozen_prompt8f_dir": str(FROZEN_PROMPT8F_DIR.relative_to(REPO_ROOT)),
        "frozen_prompt8f_zip_expected_sha256": FROZEN_PROMPT8F_ZIP_SHA256,
        "prompt8f_parent_commit": PROMPT8F_PARENT_COMMIT,
        "input_and_source_hashes": (
            "published once, in offline_replay_manifest.json"),
        "pinned_local_kg_expected_sha256": PINNED_LOCAL_KG_SHA256,
        "pinned_local_kg_loaded": False,
        "lrolesim_execution_path": {
            "ranker_name": EXPECTED_RANKER_NAME,
            "measure": EXPECTED_MEASURE,
            "lrolesim_beta": EXPECTED_LROLESIM_BETA,
            "iterations": EXPECTED_ITERATIONS,
            "iteration_mode": EXPECTED_ITERATION_MODE,
            "note": ("frozen and consumed, not recomputed: R1 reads the "
                     "Prompt-8D ranks and never re-runs the kernel. Journal 2 "
                     "APPLIES LRoleSim as a structural plausibility ranker and "
                     "does not change its mathematical definition."),
        },
        "set_cover": {
            "algorithm": SET_COVER_ALGORITHM,
            "complexity": SET_COVER_COMPLEXITY,
            "k": run.k,
            "rho": run.rho,
            "exact": True,
            "greedy": False,
            "unchanged_from_prompt_8f": True,
            "legacy_one_fact_special_case": LEGACY_ONE_FACT_SPECIAL_CASE_NOTE,
            "provenance": SET_COVER_PROVENANCE_NOTE,
        },
        "evidence_model": {
            "levels": list(LEVEL_DEFINITION),
            "level_definitions": dict(LEVEL_DEFINITION),
            "exclusion_basis_definitions": dict(EXCLUSION_BASIS_DEFINITION),
            "mcq_level_note": MCQ_LEVEL_NOTE,
            "policy_priority": list(POLICY_PRIORITY),
            "policy_notes": dict(POLICY_NOTE),
            "multi_valued_predicate_note": MULTI_VALUED_PREDICATE_NOTE,
            "qualifier_note": QUALIFIER_NOTE,
            "parent_child_note": PARENT_CHILD_NOTE,
            "rule_counts": run.rulebook.counts(),
            "scoped_empirical_annotation": run.rulebook.derivation.as_record(),
            "require_semantic_closure_for_annotation":
                run.rulebook.require_semantic_closure_for_annotation,
            "correction_note": (
                "R1 restores L1 to POSITIVE VALUE CONTRAST. A scoped empirical "
                "single-valued rule can no longer decide whether an observed "
                "alternative object is L0 or L1; it only annotates an "
                "established L1 through exclusion_basis."),
        },
        "semantic_index": run.semantic_index.as_record(),
        "quality_policy": quality.as_record(),           # type: ignore[attr-defined]
        "combination_search": {
            **run.pool_policy.as_record(),
            "pool_optimality_note": POOL_OPTIMALITY_NOTE,
        },
        "input_contract_checks": [
            {"check": name, "detail": detail}
            for name, detail in run.contract_checks],
        "counts": run.counts(),
        "sulfuric_acid_diagnostic": _sulfuric_acid_diagnostic(run),
        "network": run.guard_record,
        "forbidden_modules_loaded_in_process": list(run.forbidden_modules),
        "stage_timings": [timing.as_row() for timing in run.timings],
        "automatic_generation": {**AUTOMATIC_GENERATION_FIELDS,
                                 "note": PUBLISHABLE_FINAL_NOTE},
        "open_world_note": (
            "Every fact in this package is OBSERVED in the pinned local KG "
            "snapshot. L0 records absence-only observation in one snapshot; L1 "
            "is a positive observed contrast; only L2 asserts exclusion, and "
            "only with an EvidenceProof. An absent triple is simply absent."),
        "scope_note": (
            "Stops before natural-language verbalization, before final "
            "Bipartite Graph selection and drawing, before fallback-class "
            "execution, and before human evaluation."),
    })


def write_all_outputs(run: RationaleV3Run, out_dir: str | Path,
                      raw_command: Sequence[str] = (),
                      prompt8e_dir: str | Path = FROZEN_PROMPT8E_DIR,
                      prompt8f_dir: str | Path = FROZEN_PROMPT8F_DIR) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_summary(run, out_dir)
    write_selected_mcqs(run, out_dir)
    write_evidence_audit(run, out_dir)
    write_comparison(run, out_dir, prompt8e_dir, prompt8f_dir)
    write_fallback_class_requests(run, out_dir)
    write_offline_replay_manifest(run, out_dir)
    write_run_manifest(run, out_dir, raw_command)

    # Every written file is re-read and checked for language that would turn an
    # observation into a claim about the world, a pool result into a global
    # optimum, or an automatically generated item into an approved one.
    for name in (*REPLAY_COMPARED_FILES, "run_manifest.json",
                 "offline_replay_manifest.json"):
        assert_no_negative_claim((out_dir / name).read_text(encoding="utf-8"),
                                 where=name)
    return out_dir


# --- 15) CLI -----------------------------------------------------------------

MODE_RATIONALE_V3_R1 = "pilot-rationale-v3-r1"
MODE_BUILD_SEMANTIC_INDEX = "build-semantic-index"
MODES = (MODE_RATIONALE_V3_R1, MODE_BUILD_SEMANTIC_INDEX)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python src/pipeline/rationale_v3_run.py",
        description=("Prompt 8F-R1 - corrected evidence taxonomy over the "
                     "frozen Prompt-8D handoff. Strictly offline."))
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--prompt8d-dir", default=str(FROZEN_PROMPT8D_DIR))
    parser.add_argument("--prompt8e-dir", default=str(FROZEN_PROMPT8E_DIR))
    parser.add_argument("--prompt8f-dir", default=str(FROZEN_PROMPT8F_DIR))
    parser.add_argument("--semantic-index-cache",
                        default=str(DEFAULT_SEMANTIC_INDEX_CACHE))
    parser.add_argument("--local-kg", default=str(PINNED_LOCAL_KG))
    parser.add_argument("-k", type=int, default=DEFAULT_K)
    parser.add_argument("--rho", type=int, default=DEFAULT_RHO)
    parser.add_argument("--max-exact-combinations", type=int,
                        default=DEFAULT_MAX_EXACT_COMBINATIONS)
    parser.add_argument("--skip-reduced-arm", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


def print_run_summary(run: RationaleV3Run, out_dir: Path) -> None:
    counts = run.counts()
    print(f"\n[done] mode={run.mode}  ranker={run.ranker_name}  "
          f"k={run.k} rho={run.rho}")
    print(f"       outputs -> {out_dir}")
    print(f"       primary Answers: {counts['primary_answer_denominator']} "
          f"({counts['primary_ready_for_rationale_selection']} ready)")
    print(f"       strict-L2: {counts['algorithm_selected_strict_l2']}  "
          f"main-L1: {counts['algorithm_selected_main_l1']}  "
          f"diagnostic-L0 only: "
          f"{counts['algorithm_selected_diagnostic_l0_only']}")
    print(f"       MCQ evidence levels: {counts['mcq_evidence_level_counts']}")
    print(f"       eligible for main corpus: {counts['eligible_for_main_corpus']}")
    print(f"       fallback class requests: {counts['fallback_class_requests']}")
    print(f"       network attempts: {run.guard_record['network_attempts']} "
          f"(http 0, sparql 0)")
    print("       every record: generation_is_automatic=true, "
          "manual_intervention_used=false, publishable_final=false")


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(argv)
    raw_command = ["python", "src/pipeline/rationale_v3_run.py", *argv]

    if args.mode == MODE_BUILD_SEMANTIC_INDEX:
        path = build_semantic_index_from_pinned_kg(
            prompt8d_dir=args.prompt8d_dir, local_kg_path=args.local_kg,
            cache_path=args.semantic_index_cache, verbose=not args.quiet)
        print(f"\n[done] semantic index cache -> {path}")
        return 0

    run = run_rationale_v3(
        prompt8d_dir=args.prompt8d_dir,
        semantic_cache_path=args.semantic_index_cache,
        k=args.k, rho=args.rho,
        pool_policy=PoolPolicy(max_exact_combinations=args.max_exact_combinations),
        run_reduced_arm=not args.skip_reduced_arm, verbose=not args.quiet)
    out_dir = write_all_outputs(run, args.output_dir, raw_command,
                                args.prompt8e_dir, args.prompt8f_dir)
    print_run_summary(run, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
