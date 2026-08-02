############################################################################
# src/pipeline/rationale_v3_run.py
#
# PROMPT 8F ORCHESTRATION — evidence-level rationale V3 and quality-aware
# distractor selection.
#
# WHAT THIS RUN CONSUMES
#   The FROZEN Prompt-8D handoff in
#   outputs/journal2_week2_extract_integration_2026-07-30/, the three versioned
#   V3 policy files, and one CACHED semantic index. Nothing else.
#
#   The 1.2 GB pinned pickle is NOT loaded by the run. It is read exactly once,
#   by the separate `build-semantic-index` mode, which writes a cache keyed on
#   the KG hash, the policy hash, the pilot's counterpart-URI list and the
#   traversal depth. The run verifies that key and refuses a cache built for
#   anything else, so the two can never silently diverge.
#
# WHAT THIS RUN MUST NOT TOUCH  (Prompt 8F §3)
#   No HTTP, no SPARQL, no Wikidata, no DBpedia endpoint, no DBpedia abstracts,
#   no spaCy, no SBERT, no LLM, no legacy OverlapStrict/OverlapLoose, no class
#   selection, no fallback-class graph construction, no LRoleSim recomputation.
#   The ranker stays lrolesim_m1_fixed_k3 with measure lrolesim_ed,
#   lrolesim_beta 0.2 and exactly three fixed iterations, all READ from the
#   frozen records and asserted here.
#
# WHERE THIS STOPS
#   Before natural-language verbalization, before the final Bipartite Graph
#   selection and drawing, before fallback-class execution, and before human
#   evaluation. Generation is fully automatic: no human judgement enters the
#   algorithmic selection loop, and every record says so through
#   generation_is_automatic / manual_intervention_used /
#   post_generation_human_evaluation_status.
#
# THE SULFURIC-ACID BOUNDARY
#   Sulfuric acid stays the ONE primary failure, with a primary summary row and
#   PRIMARY_NOT_READY. Its six diagnostic candidates are analysed in a separate
#   namespace and enter no primary denominator, success rate or candidate count.
#
# OPEN WORLD
#   Every emitted fact is OBSERVED in the pinned snapshot. L0 is never reported
#   as a negative fact, and no absence is reported as falsity (CLAUDE.md items 7
#   and 8).
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
from dataclasses import dataclass, field
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
    ENUMERATION_COMPLETE,
    FALLBACK_L0_ONLY,
    FALLBACK_NEXT_STAGE,
    HUMAN_EVALUATION_NOT_STARTED,
    LEGACY_ONE_FACT_SPECIAL_CASE_NOTE,
    LEVEL_DEFINITION,
    LEVEL_L0,
    LEVEL_L1,
    LEVEL_L2,
    LEVEL_NOT_COVERED,
    MULTI_VALUED_PREDICATE_NOTE,
    PARENT_CHILD_NOTE,
    POLICY_DIAGNOSTIC_L0,
    POLICY_MAIN_L1PLUS,
    POLICY_NOTE,
    POLICY_PRIORITY,
    POLICY_STRICT_L2,
    POOL_ABLATION_SIZES,
    POOL_OPTIMALITY_NOTE,
    PROMPT8E_STATUS_FOR_REASON_CODE,
    PUBLISHABLE_FINAL_NOTE,
    QUALIFIER_NOTE,
    RELATION_UNRELATED_OR_UNKNOWN,
    SEARCH_FULL_EXACT,
    SELECTION_PRIMARY_NOT_READY,
    SET_COVER_ALGORITHM,
    SET_COVER_COMPLEXITY,
    SET_COVER_PROVENANCE_NOTE,
    AnswerFact,
    RationaleV3ContractError,
    assert_no_negative_claim,
)
from rationale_v3.evidence import (                                    # noqa: E402
    EvidenceRuleBook,
    derive_empirical_single_valued_rules,
    load_evidence_rules,
    observe_scope_cardinalities,
)
from rationale_v3.quality import load_quality_policy                   # noqa: E402
from rationale_v3.selector import (                                    # noqa: E402
    AUDIT_TOP_COMBINATIONS,
    AUDIT_TOP_RATIONALES,
    AnswerInput,
    AnswerSelection,
    CandidatePool,
    PoolPolicy,
    RankedCandidateView,
    build_evidence_table,
    not_ready_selection,
    pool_size_ablation,
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
    write_semantic_index_cache,
)

# ==========================================================================
# 0) PINNED INPUTS
# ==========================================================================

FROZEN_PROMPT8D_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_extract_integration_2026-07-30")
FROZEN_PROMPT8D_ZIP_SHA256 = (
    "d2a0ff793f64767c0413c3b9f116791abecdeafdf51c4bff3eaf2ee331cae404")
FROZEN_PROMPT8E_DIR = (
    REPO_ROOT / "outputs" / "journal2_week2_rationale_selection_2026-08-01")
FROZEN_PROMPT8E_ZIP_SHA256 = (
    "9463e1045ea98a40c8ef062adf999ff0b86ee03adafd5326be855713c91921a3")

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
    REPO_ROOT / "outputs" / "journal2_week2_rationale_v3_2026-08-03")

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

# Frozen Prompt-8C, 8D and 8E sources. Prompt 8F must not change any of them, so
# their hashes are checked at run time and published, not merely promised.
PROTECTED_SOURCES = {
    "candidate_order": (
        SRC_DIR / "pipeline" / "candidate_order.py",
        "8a6e9b36f9a393de8a4f287305f4545f78e4090b34a83f0b3ebcea76cbc0e1f2"),
    "graph_lrolesim_run": (
        SRC_DIR / "pipeline" / "graph_lrolesim_run.py",
        "2c1242dbe7dfd7608a3dd09d7ff71bcd672880968b1bcdfdbd7fe45d628eb994"),
    "graph_view": (
        SRC_DIR / "kg" / "graph_view.py",
        "0ed2733307ef8116b4ba79c906e8e880711e06f011418b0da3104e4c99716ec4"),
    "lrolesim_adapter": (
        SRC_DIR / "lrolesim" / "adapter.py",
        "2100fd112b144a4d71d2b0be0ef3465b3c73c9f8d5d8ad78b28a587185d65f33"),
    "lrolesim_kernel": (
        SRC_DIR / "MCQ_lrolesim_ClaudeWeb_v2.py",
        "b7c3678ee531a291dee874053529ac498d8c7674b892cff19e817808671ddec0"),
    "selection_init": (
        SRC_DIR / "selection" / "__init__.py",
        "912a0a49867006645667d43d989fc0a87492edbf59da5c925955c1aa6c9a375a"),
    "selection_contracts": (
        SRC_DIR / "selection" / "contracts.py",
        "a271f28eaf0492604232fe3f0a2810346e3db98fee64aa9dd1236ce6219752ec"),
    "selection_observed_facts": (
        SRC_DIR / "selection" / "observed_facts.py",
        "78f0543252851177e19389626ed17a34440d0f941b18c4bb8b4e7ffdaaa8364d"),
    "selection_lrolesim_handoff": (
        SRC_DIR / "selection" / "lrolesim_handoff.py",
        "c4fc4077743f3f4874d3abda91a0ee4d13ce5256c47a691e3988c99e708ce26d"),
    "selection_legacy_overlap": (
        SRC_DIR / "selection" / "legacy_overlap.py",
        "a50dd4435f65f831b2c641219445a917f0e5851a6e35ace3aacc1f061e5f014d"),
    "prompt8e_entrypoint": (
        SRC_DIR / "extract_221_and_select_distractors_ClaudeWeb_v2.py",
        "81f9297f8084503806a28ed15f2ed1c6465c152a86616c4d12e669ac0867f6aa"),
    "prompt8e_rationale_init": (
        SRC_DIR / "rationale" / "__init__.py",
        "cedb14cac100ddb2d8291ffa52bcfd71dfff6a74554e96016b13c4b139734796"),
    "prompt8e_rationale_contracts": (
        SRC_DIR / "rationale" / "contracts.py",
        "04fadc371c7a6d32dc41b264efb27a755e781a3ced2bc49f8a3e57610d9eb7a3"),
    "prompt8e_rationale_contrasts": (
        SRC_DIR / "rationale" / "contrasts.py",
        "06e4c5c8dcd2c0fa6de95f6b68a9dc81a21680da5b6ba6a8d3cb91459c7e29a3"),
    "prompt8e_rationale_setcover": (
        SRC_DIR / "rationale" / "setcover.py",
        "bc811a1632dbb972dc1372a382b566eadf07f5af7569aef5656c8804dec4dafe"),
    "prompt8e_rationale_selector": (
        SRC_DIR / "rationale" / "selector.py",
        "14dc3684e3d516fad147a111288bbc7de33fcbdc34c05c3956930900e13c7d39"),
    "prompt8e_rationale_selection_run": (
        SRC_DIR / "pipeline" / "rationale_selection_run.py",
        "650a6e634815a71996a381300e480bd2a224b08bc6d6d4ae096c0cd1497bcec3"),
}

# --- The expected Prompt-8D shape, asserted rather than assumed -------------
EXPECTED_PRIMARY_ANSWER_COUNT = 9
EXPECTED_READY_ANSWER_COUNT = 8
EXPECTED_PRIMARY_RANKED_CANDIDATE_COUNT = 204
EXPECTED_DIAGNOSTIC_RANKED_CANDIDATE_COUNT = 6
EXPECTED_PRIMARY_FAILURE_ANSWER_URI = "http://dbpedia.org/resource/Sulfuric_acid"

# --- The frozen LRoleSim execution path, asserted (§3) ----------------------
EXPECTED_RANKER_NAME = "lrolesim_m1_fixed_k3"
EXPECTED_MEASURE = "lrolesim_ed"
EXPECTED_LROLESIM_BETA = 0.2
EXPECTED_ITERATIONS = 3
EXPECTED_ITERATION_MODE = "fixed"

#: Files a strict offline replay must reproduce byte for byte. Timing, clock and
#: Git-state artefacts are excluded by construction, not by tolerance.
REPLAY_COMPARED_FILES = (
    "rationale_v3_summary.csv",
    "algorithm_selected_distractors_v3.jsonl",
    "selected_rationales_v3.jsonl",
    "all_minimum_rationale_candidates_v3.jsonl",
    "per_candidate_evidence_v3.jsonl",
    "evidence_proofs_v3.jsonl",
    "semantic_relation_audit_v3.jsonl",
    "quality_filter_audit_v3.jsonl",
    "predicate_policy_audit_v3.csv",
    "empirical_rule_candidates_v3.csv",
    "combination_search_audit_v3.jsonl",
    "candidate_pool_ablation_v3.csv",
    "fallback_class_requests_v3.jsonl",
    "bipartite_fact_candidates.jsonl",
    "sulfuric_acid_diagnostic_v3.json",
    "prompt8e_comparison.csv",
)

#: Modules whose presence in sys.modules would contradict the zero-network,
#: zero-model claim of the V3 path. `kg.loader` is deliberately absent: the
#: separate build-semantic-index mode is the one place allowed to open the
#: pinned pickle, and the run asserts it did NOT do so through
#: `pinned_local_kg_loaded`.
FORBIDDEN_MODULE_PREFIXES = (
    "spacy",
    "sentence_transformers",
    "torch",
    "SPARQLWrapper",
    "requests",
    "urllib3",
    "httpx",
    "openai",
    "anthropic",
    "classes.sparql_client",
    "classes.member_mapper",
    "classes.page_cache",
    "classes.class_selector",
    "category_extractor_ClaudeWeb_v2",
    "category_extractor_ClaudeWeb_v3",
    "category_extractor_ClaudeWeb_v4",
    "selection.legacy_overlap",
    "lrolesim.adapter",
    "MCQ_lrolesim_ClaudeWeb_v2",
    "pipeline.graph_lrolesim_run",
)


class RationaleV3Error(Exception):
    """Base class for Prompt-8F rationale-V3 failures."""


class Prompt8DInputError(RationaleV3Error):
    """A frozen Prompt-8D input file is missing, unreadable or inconsistent."""


class ProtectedSourceModifiedError(RationaleV3Error):
    """A frozen source file no longer has its expected SHA-256."""


class OfflineGuardTripped(RationaleV3Error):
    """The V3 path attempted an outbound connection."""


# ==========================================================================
# 1) OFFLINE GUARD
# ==========================================================================

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

        def blocked_connect(self, address, *a, **k):          # noqa: ANN001
            guard.attempts.append(repr(address))
            raise OfflineGuardTripped(
                f"outbound connection to {address!r} refused: Prompt 8F reads "
                f"only frozen local artefacts")

        def blocked_connect_ex(self, address, *a, **k):        # noqa: ANN001
            guard.attempts.append(repr(address))
            raise OfflineGuardTripped(
                f"outbound connection to {address!r} refused")

        def blocked_create(address, *a, **k):                  # noqa: ANN001
            guard.attempts.append(repr(address))
            raise OfflineGuardTripped(
                f"outbound connection to {address!r} refused")

        self._saved = {
            "connect": socket.socket.connect,
            "connect_ex": socket.socket.connect_ex,
            "create_connection": socket.create_connection,
        }
        socket.socket.connect = blocked_connect            # type: ignore[method-assign]
        socket.socket.connect_ex = blocked_connect_ex      # type: ignore[method-assign]
        socket.create_connection = blocked_create          # type: ignore[assignment]
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
    loaded = []
    for name in sorted(sys.modules):
        for prefix in FORBIDDEN_MODULE_PREFIXES:
            if name == prefix or name.startswith(prefix + "."):
                loaded.append(name)
                break
    return loaded


# ==========================================================================
# 2) DETERMINISTIC WRITERS
# ==========================================================================

def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"))


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


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


def sha256_file(path: str | Path, chunk_size: int = 1 << 23) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


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
            f"frozen Prompt-8C/8D/8E sources changed: {drift}. Prompt 8F must "
            f"not modify the graph, ordering, LRoleSim, selection or Prompt-8E "
            f"rationale layers.")
    return observed


# ==========================================================================
# 3) READING THE FROZEN PROMPT-8D HANDOFF
# ==========================================================================

def _read_jsonl(path: Path) -> list:
    if not path.is_file():
        raise Prompt8DInputError(f"frozen Prompt-8D input not found: {path}")
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
        raise Prompt8DInputError(f"frozen Prompt-8D input not found: {path}")
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise Prompt8DInputError(f"frozen Prompt-8D input not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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

    Every number Prompt 8F reports downstream is a consequence of these, so they
    are checked once, here, and never re-derived from a different file later.
    """
    checks: list = []

    _require(len(inputs.handoffs) == EXPECTED_PRIMARY_ANSWER_COUNT,
             f"expected {EXPECTED_PRIMARY_ANSWER_COUNT} primary handoff records, "
             f"found {len(inputs.handoffs)}")
    _require(len(inputs.summary) == EXPECTED_PRIMARY_ANSWER_COUNT,
             f"expected {EXPECTED_PRIMARY_ANSWER_COUNT} primary summary rows, "
             f"found {len(inputs.summary)}")
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
             and not_ready[0]["answer_uri"] == EXPECTED_PRIMARY_FAILURE_ANSWER_URI,
             f"the one primary failure must be "
             f"{EXPECTED_PRIMARY_FAILURE_ANSWER_URI}")
    _require(not_ready[0]["ranked_candidate_count"] == 0,
             "the primary failure must carry no ranked candidate")
    checks.append(("sulfuric_acid_primary_failure_preserved",
                   f"{not_ready[0]['mapping_stage_status']} / "
                   f"{not_ready[0]['graph_stage_status']}"))

    ranked_total = sum(h["ranked_candidate_count"] for h in inputs.handoffs)
    _require(ranked_total == EXPECTED_PRIMARY_RANKED_CANDIDATE_COUNT,
             f"expected {EXPECTED_PRIMARY_RANKED_CANDIDATE_COUNT} primary ranked "
             f"candidates, found {ranked_total}")
    checks.append(("primary_ranked_candidate_count", f"{ranked_total} ranks"))

    diagnostic_ranked = inputs.diagnostic_handoff["diagnostic_handoff"][
        "ranked_candidate_count"]
    _require(diagnostic_ranked == EXPECTED_DIAGNOSTIC_RANKED_CANDIDATE_COUNT,
             f"expected {EXPECTED_DIAGNOSTIC_RANKED_CANDIDATE_COUNT} diagnostic "
             f"ranked candidates, found {diagnostic_ranked}")
    _require(bool(inputs.diagnostic_handoff["diagnostic_only"]),
             "the Sulfuric-acid diagnostic must be flagged diagnostic_only")
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


# ==========================================================================
# 4) BUILDING THE V3 INPUTS
# ==========================================================================

def _answer_fact(record: Mapping[str, object]) -> AnswerFact:
    return AnswerFact(
        predicate_uri=normalize_uri(str(record["predicate_uri"])),
        direction=str(record["direction"]),
        counterpart_uri=normalize_uri(str(record["counterpart_uri"])),
        graph_fingerprint=str(record["graph_fingerprint"]),
        owner_uri=normalize_uri(str(record["owner_uri"])),
    )


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
        ranked = tuple(
            RankedCandidateView(
                rank=int(c["rank"]),
                canonical_candidate_uri=normalize_uri(
                    str(c["canonical_candidate_uri"])),
                candidate_local_index=int(c["candidate_local_index"]),
                score=float(c["score"]),
            )
            for c in sorted(handoff["ranked_candidates"],
                            key=lambda c: int(c["rank"])))
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
            ranked_candidates=ranked,
            answer_facts=tuple(answer_facts.get(answer_uri, ())),
            candidate_facts={k: tuple(v) for k, v
                             in candidate_facts.get(answer_uri, {}).items()},
        ))
    return tuple(built)


def build_diagnostic_input(inputs: Prompt8DInputs) -> Optional[AnswerInput]:
    """The Sulfuric-acid DIAGNOSTIC input, in its own namespace.

    Engineering evidence only. Nothing built here enters a primary denominator,
    success rate or candidate count, and the primary Sulfuric-acid row stays
    PRIMARY_NOT_READY regardless of what this analysis finds.
    """
    handoff = inputs.diagnostic_handoff["diagnostic_handoff"]
    answer_uri = normalize_uri(str(handoff["answer_uri"]))

    answer_facts = []
    candidate_facts: dict = {}
    for record in inputs.diagnostic_facts:
        fact = _answer_fact(record)
        if record["owner_role"] == "answer":
            answer_facts.append(fact)
        else:
            candidate_facts.setdefault(fact.owner_uri, []).append(fact)

    ranked = tuple(
        RankedCandidateView(
            rank=int(c["rank"]),
            canonical_candidate_uri=normalize_uri(
                str(c["canonical_candidate_uri"])),
            candidate_local_index=int(c["candidate_local_index"]),
            score=float(c["score"]),
        )
        for c in sorted(handoff["ranked_candidates"], key=lambda c: int(c["rank"])))
    if not ranked:
        return None

    return AnswerInput(
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
        ranked_candidates=ranked,
        answer_facts=tuple(answer_facts),
        candidate_facts={k: tuple(v) for k, v in candidate_facts.items()},
        primary_or_diagnostic="diagnostic",
    )


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


# ==========================================================================
# 5) THE SEMANTIC INDEX (built once, cached, verified)
# ==========================================================================

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

    The ONLY function in the V3 path permitted to open the 1.2 GB pickle, and it
    is a separate CLI mode so that the scientific run never pays for it and never
    depends on it being loadable. `kg.loader` is imported inside the function so
    that merely importing this module does not pull the loader in.

    Only counterpart URIs from the pilot, and the ancestors reachable from them
    within the policy's depth, are indexed. Nothing rebuilds the KG and nothing
    writes to it (CLAUDE.md file-safety rules).
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

    def index_of(uri: str) -> Optional[int]:
        # The pinned pickle keys URIs with angle brackets (see
        # selection/observed_facts.bare_uri); the handoff stores them plain.
        return kg.index_for_uri_or_none("<" + uri + ">")

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
            node = index_of(uri)
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
        creation_command=SEMANTIC_INDEX_BUILD_COMMAND,
    )
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
        creation_command=SEMANTIC_INDEX_BUILD_COMMAND,
    )
    return load_semantic_index_cache(cache_path, policy=policy, expected_key=key)


# ==========================================================================
# 6) DERIVING THE SCOPED EMPIRICAL RULES
# ==========================================================================

def scope_observations(answers: Sequence[AnswerInput]) -> dict:
    """{scope: {entity: {key: [object]}}} over the Answer AND candidate pools.

    Facts are keyed per Answer graph in the Prompt-8D handoff, and one class is
    shared by several Answers, so the same candidate fact can appear more than
    once. Building a per-entity SET here is what stops a shared candidate from
    being counted as a cardinality violation against itself.
    """
    scopes: dict = {}
    for answer in answers:
        scope = answer.scope
        bucket = scopes.setdefault(scope, {})
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
    """Derive every scoped empirical rule candidate and merge the active ones."""
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


# ==========================================================================
# 7) THE RUN
# ==========================================================================

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


def _peak_rss_kb() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


@dataclass
class RationaleV3Run:
    """Everything one Prompt-8F run produced."""

    mode: str
    ranker_name: str
    k: int
    rho: int
    inputs: Prompt8DInputs
    contract_checks: tuple
    answers: tuple
    selections: tuple
    primary_order: tuple
    diagnostic_input: Optional[AnswerInput]
    diagnostic_selection: Optional[AnswerSelection]
    semantic_index: SemanticIndex
    rulebook: EvidenceRuleBook
    base_rulebook: EvidenceRuleBook
    quality_policy: object
    scope_observations: Mapping[str, tuple]
    support_ablation: Mapping[int, dict]
    pool_ablation: tuple
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
        for selection in self.ready_selections:
            if selection.table is None:
                continue
            for level, count in selection.table.level_counts().items():
                levels[level] += count
            for level, count in selection.table.eligible_level_counts().items():
                eligible_levels[level] += count
        return {
            "primary_answer_denominator": len(self.selections),
            "primary_ready_for_rationale_selection": len(self.ready_selections),
            "primary_ranked_candidate_total": sum(
                a.candidate_count for a in self.answers),
            "algorithm_selected_strict_l2": by_policy[POLICY_STRICT_L2],
            "algorithm_selected_main_l1plus": by_policy[POLICY_MAIN_L1PLUS],
            "algorithm_selected_diagnostic_l0_only": by_policy[
                POLICY_DIAGNOSTIC_L0],
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
    run_pool_ablation: bool = True,
    verbose: bool = True,
) -> RationaleV3Run:
    """Consume the frozen Prompt-8D handoff and select distractors with V3.

    Strictly offline. Makes no HTTP or SPARQL call, loads no spaCy or SBERT
    model, retrieves no DBpedia abstract, runs no class selection, rebuilds no
    graph, recomputes no LRoleSim score, and does not open the pinned pickle.
    """
    guard = OfflineGuard()
    guard.install()
    timings: list = []

    def stage(name: str, started: float, detail: str = "") -> None:
        elapsed = time.perf_counter() - started
        timings.append(StageTiming(name, elapsed, _peak_rss_kb(), detail))
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
              f"predicates, semantic index available="
              f"{semantic_index.available}")

        t0 = time.perf_counter()
        answers = build_answer_inputs(inputs)
        rulebook, observations = derive_rulebook(
            answers, base=base_rules, semantic_index=semantic_index,
            rejected_predicates=quality_policy.hard_reject_predicates)
        counts = rulebook.counts()
        stage("derive_evidence_rules", t0,
              f"{counts['total_rules']} rule candidates, "
              f"{counts['active_l1_rules']} active L1, "
              f"{counts['active_l2_rules']} active L2")

        t0 = time.perf_counter()
        support_ablation: dict = {}
        for threshold in base_rules.derivation.support_ablation_values:
            book, _ = derive_rulebook(
                answers, base=base_rules, semantic_index=semantic_index,
                rejected_predicates=quality_policy.hard_reject_predicates,
                minimum_support_override=threshold)
            support_ablation[threshold] = book.counts()
        stage("support_threshold_ablation", t0,
              f"{len(support_ablation)} thresholds swept")

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
        ablation_rows: list = []
        if run_pool_ablation:
            for answer in answers:
                selection = next(s for s in selections
                                 if s.answer_uri == answer.answer_uri)
                ablation_rows.extend(pool_size_ablation(
                    answer, selection, semantic_index=semantic_index,
                    rulebook=rulebook, quality_policy=quality_policy,
                    sizes=POOL_ABLATION_SIZES, k=k, rho=rho,
                    max_exact_combinations=pool_policy.max_exact_combinations))
        stage("candidate_pool_ablation", t0, f"{len(ablation_rows)} cells")

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
            mode="pilot-rationale-v3",
            ranker_name=EXPECTED_RANKER_NAME,
            k=k, rho=rho,
            inputs=inputs,
            contract_checks=tuple(inputs.contract_checks),
            answers=answers,
            selections=tuple(selections),
            primary_order=tuple(primary_order),
            diagnostic_input=diagnostic_input,
            diagnostic_selection=diagnostic_selection,
            semantic_index=semantic_index,
            rulebook=rulebook,
            base_rulebook=base_rules,
            quality_policy=quality_policy,
            scope_observations=observations,
            support_ablation=support_ablation,
            pool_ablation=tuple(ablation_rows),
            protected_sources=protected,
            guard_record=guard.as_record(),
            forbidden_modules=tuple(loaded_forbidden_modules()),
            timings=tuple(timings),
            pool_policy=pool_policy,
        )
    finally:
        guard.uninstall()


# ==========================================================================
# 8) OUTPUT WRITERS
# ==========================================================================

SUMMARY_FIELDS = (
    "pilot_slot", "answer_uri", "display_label", "primary_or_diagnostic",
    "diagnostic_only", "excluded_from_primary_policy_metrics",
    "selected_class_uri", "graph_fingerprint", "ranker_name", "measure",
    "lrolesim_beta", "iterations", "iteration_mode", "k", "rho",
    "ready_for_rationale_selection", "ranked_candidate_count",
    "answer_fact_count", "eligible_answer_fact_count",
    "search_scope", "pool_candidate_count", "original_combination_count",
    "enumerated_combination_count", "global_optimality_claim",
    "strict_l2_feasible_count", "main_l1plus_feasible_count",
    "diagnostic_l0_feasible_count",
    "selection_status", "evidence_policy", "evidence_level",
    "distractor_1_uri", "distractor_2_uri", "distractor_3_uri",
    "distractor_ranks", "distractor_lrolesim_scores",
    "minimum_rationale_size", "minimum_rationale_count_before_quality_ranking",
    "rationale_min_level", "L2_coverage_incidence_count",
    "L1_coverage_incidence_count", "L0_coverage_incidence_count",
    "local_candidate_pool_anonymity_count", "direct_identifier_flag",
    "generation_is_automatic", "manual_intervention_used",
    "post_generation_human_evaluation_status",
    "eligible_for_main_corpus", "eligible_for_diagnostic_corpus",
    "eligible_for_human_study", "publishable_final",
    "fallback_status",
)


def _summary_row(run: RationaleV3Run, answer_uri: str) -> dict:
    selection = run.selection_for(answer_uri)
    handoff = next(h for h in run.inputs.handoffs
                   if h["answer_uri"] == answer_uri)
    row = {
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
        "search_scope": "",
        "pool_candidate_count": "",
        "original_combination_count": "",
        "enumerated_combination_count": "",
        "global_optimality_claim": "",
        "strict_l2_feasible_count": "",
        "main_l1plus_feasible_count": "",
        "diagnostic_l0_feasible_count": "",
        "selection_status": selection.status,
        "evidence_policy": selection.evidence_policy or "",
        "evidence_level": "",
        "distractor_1_uri": "", "distractor_2_uri": "", "distractor_3_uri": "",
        "distractor_ranks": "", "distractor_lrolesim_scores": "",
        "minimum_rationale_size": "",
        "minimum_rationale_count_before_quality_ranking": "",
        "rationale_min_level": "",
        "L2_coverage_incidence_count": "",
        "L1_coverage_incidence_count": "",
        "L0_coverage_incidence_count": "",
        "local_candidate_pool_anonymity_count": "",
        "direct_identifier_flag": "",
        "generation_is_automatic": _b(True),
        "manual_intervention_used": _b(False),
        "post_generation_human_evaluation_status": HUMAN_EVALUATION_NOT_STARTED,
        "eligible_for_main_corpus": _b(selection.eligible_for_main_corpus),
        "eligible_for_diagnostic_corpus": _b(
            selection.eligible_for_diagnostic_corpus),
        "eligible_for_human_study": _b(selection.eligible_for_human_study),
        "publishable_final": _b(False),
        "fallback_status": selection.fallback_status,
    }
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
                           (POLICY_MAIN_L1PLUS, "main_l1plus_feasible_count"),
                           (POLICY_DIAGNOSTIC_L0, "diagnostic_l0_feasible_count")):
        search = selection.searches.get(policy)
        row[column] = 0 if search is None else len(search.feasible(run.rho))

    if selection.selected is not None and selection.ranking is not None:
        best = selection.ranking.best
        for index, uri in enumerate(selection.selected.candidate_uris, start=1):
            row[f"distractor_{index}_uri"] = uri
        row["distractor_ranks"] = "|".join(
            str(r) for r in selection.selected.ranks)
        row["distractor_lrolesim_scores"] = "|".join(
            _fmt_score(s) for s in selection.selected.scores)
        row["minimum_rationale_size"] = selection.ranking.size
        row["minimum_rationale_count_before_quality_ranking"] = (
            selection.ranking.minimum_rationale_count)
        row["rationale_min_level"] = selection.ranking.achieved_min_level
        row["evidence_level"] = selection.ranking.achieved_min_level
        if best is not None:
            row["L2_coverage_incidence_count"] = best.l2_incidences
            row["L1_coverage_incidence_count"] = best.l1_incidences
            row["L0_coverage_incidence_count"] = best.l0_incidences
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
    _write_csv(out_dir / "rationale_v3_summary.csv", SUMMARY_FIELDS, rows)


def _rationale_fact_records(run: RationaleV3Run,
                            selection: AnswerSelection) -> list:
    """One record per fact of the ONE selected rationale, with every §17 field."""
    if (selection.selected is None or selection.ranking is None
            or selection.table is None):
        return []
    best = selection.ranking.best
    if best is None:
        return []
    answer = run.answer_for(selection.answer_uri)
    table = selection.table
    positions = selection.selected.positions
    uris = selection.selected.candidate_uris
    policy = selection.evidence_policy
    assert policy is not None

    records = []
    for index in best.fact_indices:
        quality = table.quality[index]
        proposition = table.propositions[index]
        per_level: dict = {}
        per_reason: dict = {}
        proof_refs: list = []
        relation_refs: list = []
        masks = {p: 0 for p in POLICY_PRIORITY}
        for bit, position in enumerate(positions):
            item = table.evidence[index][position]
            per_level[uris[bit]] = item.level
            per_reason[uris[bit]] = item.reason_code
            if item.proof is not None:
                proof_refs.append(item.proof.rule_id)
            for relation in item.relations:
                if relation.relation.relation != RELATION_UNRELATED_OR_UNKNOWN:
                    relation_refs.append({
                        "candidate_uri": uris[bit],
                        "candidate_object_uri": relation.candidate_object_uri,
                        "relation": relation.relation.relation,
                        "path_rule_ids": list(relation.relation.path_rule_ids),
                    })
            for candidate_policy in POLICY_PRIORITY:
                from rationale_v3.contracts import covers_under_policy as _covers
                if _covers(item.level, candidate_policy):
                    masks[candidate_policy] |= 1 << bit
        count, ratio, direct = table.local_anonymity((index,))
        records.append({
            "answer_uri": selection.answer_uri,
            "display_label": answer.display_label,
            "selected_class_uri": answer.selected_class_uri,
            "evidence_policy": policy,
            **proposition.as_record(),
            "per_candidate_level": per_level,
            "per_candidate_reason_code": per_reason,
            "rationale_min_level": selection.ranking.achieved_min_level,
            "evidence_proof_references": sorted(set(proof_refs)),
            "semantic_relation_references": relation_refs,
            "coverage_mask_strict_l2": masks[POLICY_STRICT_L2],
            "coverage_mask_main_l1plus": masks[POLICY_MAIN_L1PLUS],
            "coverage_mask_diagnostic_l0": masks[POLICY_DIAGNOSTIC_L0],
            "predicate_policy_result": ("ACCEPTED" if quality.predicate_ok
                                        else quality.predicate_reason),
            "object_policy_result": ("ACCEPTED" if quality.object_ok
                                     else quality.object_reason),
            "leakage_result": quality.leakage.reason_code,
            "local_candidate_pool_anonymity_count": count,
            "local_candidate_pool_anonymity_ratio": round(ratio, 6),
            "local_candidate_pool_anonymity_note": (
                "computed over the Answer plus the COMPLETE ranked candidate "
                "pool of the selected class; it is not a statement about every "
                "entity of that class in remote DBpedia"),
            "direct_identifier_flag": direct,
            "template_id": quality.template_id,
            "verbalizable": quality.verbalizable,
            "pedagogical_tier": quality.pedagogical_tier,
            "graph_fingerprint": answer.graph_fingerprint,
            "source_snapshot": {
                "pinned_local_kg_sha256": PINNED_LOCAL_KG_SHA256,
                "prompt8d_zip_sha256": FROZEN_PROMPT8D_ZIP_SHA256,
                "prompt8d_input_sha256": dict(run.inputs.input_sha256),
            },
            **AUTOMATIC_GENERATION_FIELDS,
        })
    return records


def write_selected_rationales(run: RationaleV3Run, out_dir: Path) -> None:
    records: list = []
    for selection in run.selections:
        records.extend(_rationale_fact_records(run, selection))
    _write_jsonl(out_dir / "selected_rationales_v3.jsonl", records)


def _selected_mcq_record(run: RationaleV3Run, selection: AnswerSelection) -> dict:
    answer = run.answer_for(selection.answer_uri)
    combination = selection.selected
    ranking = selection.ranking
    assert combination is not None and ranking is not None
    best = ranking.best
    assert best is not None
    policy = selection.evidence_policy
    assert policy is not None
    pool = selection.pool
    assert pool is not None

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
        "set_cover_algorithm": SET_COVER_ALGORITHM,
        "set_cover_complexity": SET_COVER_COMPLEXITY,
        "distractors": [
            {
                "position": position,
                "candidate_uri": uri,
                "original_rank": rank,
                "lrolesim_score": score,
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
        "distractor_uris": list(combination.candidate_uris),
        "distractor_ranks": list(combination.ranks),
        "distractor_lrolesim_scores": list(combination.scores),
        "lrolesim_score_sum": combination.score_sum,
        "lrolesim_score_min": combination.score_min,
        "candidate_rank_sum": combination.rank_sum,
        **pool.as_record(),
        "pool_optimality_note": POOL_OPTIMALITY_NOTE,
        "replaced_provisional_top3": sorted(combination.ranks) != [1, 2, 3],
        "selected_rationale": best.as_record(),
        "minimum_rationale_size": ranking.size,
        "minimum_rationale_count_before_quality_ranking":
            ranking.minimum_rationale_count,
        "minimum_rationale_count_enumerated": ranking.enumerated_count,
        "minimum_rationale_enumeration_scope": ranking.enumeration_scope,
        "selected_rationale_quality_key": [
            repr(part) for part in best.ranking_key()],
        "rationale_min_level": ranking.achieved_min_level,
        "coverage_mask": combination.coverage_mask,
        "coverage_count": combination.coverage_count,
        "full_coverage": combination.full_coverage,
        "selection_status": selection.status,
        "evidence_level": ranking.achieved_min_level,
        "eligible_for_main_corpus": selection.eligible_for_main_corpus,
        "eligible_for_diagnostic_corpus": selection.eligible_for_diagnostic_corpus,
        "eligible_for_human_study": selection.eligible_for_human_study,
        "fallback_status": selection.fallback_status,
        "algorithm_selected_distractor": True,
        **AUTOMATIC_GENERATION_FIELDS,
        "publishable_final_note": PUBLISHABLE_FINAL_NOTE,
        "open_world_note": MULTI_VALUED_PREDICATE_NOTE,
        "input_package_sha256": dict(run.inputs.input_sha256),
        "input_package_zip_sha256": FROZEN_PROMPT8D_ZIP_SHA256,
        "pinned_local_kg_sha256": PINNED_LOCAL_KG_SHA256,
    }


def write_algorithm_selected_distractors(run: RationaleV3Run,
                                         out_dir: Path) -> None:
    records = [_selected_mcq_record(run, s) for s in run.selections
               if s.algorithm_selected]
    _write_jsonl(out_dir / "algorithm_selected_distractors_v3.jsonl", records)


def write_all_minimum_rationale_candidates(run: RationaleV3Run,
                                           out_dir: Path) -> None:
    """The ranked minimum-cardinality rationales for each selected combination.

    Bounded to AUDIT_TOP_RATIONALES rows per Answer; the exact count before any
    quality ranking is published alongside, so the bound trims the artefact and
    never the search.
    """
    records: list = []
    for selection in run.selections:
        if selection.ranking is None or selection.table is None:
            continue
        for position, choice in enumerate(
                selection.ranking.ranked[:AUDIT_TOP_RATIONALES]):
            records.append({
                "answer_uri": selection.answer_uri,
                "evidence_policy": selection.evidence_policy,
                "quality_rank": position + 1,
                "is_selected": position == 0,
                "minimum_rationale_count_before_quality_ranking":
                    selection.ranking.minimum_rationale_count,
                "minimum_rationale_count_enumerated":
                    selection.ranking.enumerated_count,
                "enumeration_scope": selection.ranking.enumeration_scope,
                "ranking_key": [repr(part) for part in choice.ranking_key()],
                **choice.as_record(),
            })
    _write_jsonl(out_dir / "all_minimum_rationale_candidates_v3.jsonl", records)


def write_per_candidate_evidence(run: RationaleV3Run, out_dir: Path) -> None:
    """One record per (Answer, observed Answer fact), with per-candidate levels.

    The complete evidence table, before any combination is considered: it is what
    makes every later coverage claim checkable from the package alone.
    """
    records: list = []
    for selection in run.selections:
        table = selection.table
        if table is None:
            continue
        for index, fact in enumerate(table.facts):
            quality = table.quality[index]
            level_counts: dict = {}
            reason_counts: dict = {}
            per_candidate: list = []
            for position, candidate in enumerate(table.candidates):
                item = table.evidence[index][position]
                level_counts[item.level] = level_counts.get(item.level, 0) + 1
                reason_counts[item.reason_code] = (
                    reason_counts.get(item.reason_code, 0) + 1)
                per_candidate.append({
                    "candidate_rank": candidate.rank,
                    "candidate_uri": candidate.canonical_candidate_uri,
                    "evidence_level": item.level,
                    "reason_code": item.reason_code,
                    "prompt8e_equivalent_status":
                        PROMPT8E_STATUS_FOR_REASON_CODE.get(item.reason_code, ""),
                    "applied_rule_id": item.applied_rule_id,
                    "candidate_object_count": len(item.candidate_object_uris),
                    "semantic_granularity_risk": item.granularity_risk,
                    "semantic_relation_available":
                        item.semantic_relation_available,
                })
            records.append({
                "answer_uri": selection.answer_uri,
                "graph_fingerprint": table.graph_fingerprint,
                "scope": table.scope,
                "fact_index": index,
                "predicate_uri": fact.predicate_uri,
                "direction": fact.direction,
                "counterpart_uri": fact.counterpart_uri,
                "eligible": quality.eligible,
                "rejection_reasons": list(quality.rejection_reasons),
                "candidate_count": table.candidate_count,
                "evidence_level_counts": level_counts,
                "reason_code_counts": reason_counts,
                "per_candidate": per_candidate,
            })
    _write_jsonl(out_dir / "per_candidate_evidence_v3.jsonl", records)


def write_evidence_proofs(run: RationaleV3Run, out_dir: Path) -> None:
    """Every EvidenceProof the run built. Empty when no L2 case was proved."""
    records: list = []
    for selection in run.selections:
        table = selection.table
        if table is None:
            continue
        for index, row in enumerate(table.evidence):
            for position, item in enumerate(row):
                if item.proof is None:
                    continue
                records.append({
                    "answer_uri": selection.answer_uri,
                    "fact_index": index,
                    "candidate_uri": table.candidates[position]
                        .canonical_candidate_uri,
                    "evidence_level": item.level,
                    "reason_code": item.reason_code,
                    **item.proof.as_record(),
                })
    _write_jsonl(out_dir / "evidence_proofs_v3.jsonl", records)


def write_semantic_relation_audit(run: RationaleV3Run, out_dir: Path) -> None:
    """The semantic layer's own record: what it could see, and what it found.

    A summary header, then every pair whose relation is NOT
    UNRELATED_OR_UNKNOWN. Emitting the millions of "no path found" pairs would
    bury the findings; the header carries their count.
    """
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
                    if key in found:
                        continue
                    found[key] = {
                        "answer_uri": selection.answer_uri,
                        "predicate_uri": table.facts[index].predicate_uri,
                        "direction": table.facts[index].direction,
                        "candidate_uri": table.candidates[position]
                            .canonical_candidate_uri,
                        **relation.as_record(),
                    }
    header = {
        "record_type": "semantic_relation_summary",
        "relation_counts": dict(sorted(counts.items())),
        "distinct_non_trivial_pairs": len(found),
        "parent_child_note": PARENT_CHILD_NOTE,
        **run.semantic_index.as_record(),
    }
    rows = [found[key] for key in sorted(found)]
    for row in rows:
        row["record_type"] = "semantic_relation"
    _write_jsonl(out_dir / "semantic_relation_audit_v3.jsonl", [header, *rows])


def write_quality_filter_audit(run: RationaleV3Run, out_dir: Path) -> None:
    """Every Answer fact with its hard-filter verdict and soft quality signals."""
    records: list = []
    for selection in run.selections:
        table = selection.table
        if table is None:
            continue
        for index, quality in enumerate(table.quality):
            records.append({
                "answer_uri": selection.answer_uri,
                "fact_index": index,
                **quality.as_record(),
            })
    _write_jsonl(out_dir / "quality_filter_audit_v3.jsonl", records)


PREDICATE_AUDIT_FIELDS = (
    "predicate_uri", "direction", "policy_result", "reason_code",
    "pedagogical_tier", "template_id", "verbalizable",
    "answer_fact_count", "answers_affected", "removed_answer_fact_count",
    "removed_by_predicate_policy", "removed_by_object_policy",
    "removed_by_lexical_leakage",
)


def write_predicate_policy_audit(run: RationaleV3Run, out_dir: Path) -> None:
    """Per (predicate, direction) observed on the Answer side: verdict + counts."""
    cells: dict = {}
    for selection in run.selections:
        table = selection.table
        if table is None:
            continue
        for index, fact in enumerate(table.facts):
            quality = table.quality[index]
            key = (fact.predicate_uri, fact.direction)
            cell = cells.setdefault(key, {
                "predicate_uri": fact.predicate_uri,
                "direction": fact.direction,
                "policy_result": ("ACCEPTED" if quality.predicate_ok
                                  else "REJECTED"),
                "reason_code": quality.predicate_reason,
                "pedagogical_tier": quality.pedagogical_tier,
                "template_id": quality.template_id,
                "verbalizable": _b(quality.verbalizable),
                "answer_fact_count": 0,
                "_answers": set(),
                "removed_answer_fact_count": 0,
                "removed_by_predicate_policy": 0,
                "removed_by_object_policy": 0,
                "removed_by_lexical_leakage": 0,
            })
            cell["answer_fact_count"] += 1
            cell["_answers"].add(selection.answer_uri)
            if not quality.eligible:
                cell["removed_answer_fact_count"] += 1
            if not quality.predicate_ok:
                cell["removed_by_predicate_policy"] += 1
            if not quality.object_ok:
                cell["removed_by_object_policy"] += 1
            if quality.leakage.hard_leak:
                cell["removed_by_lexical_leakage"] += 1
    rows = []
    for key in sorted(cells):
        cell = dict(cells[key])
        cell["answers_affected"] = len(cell.pop("_answers"))
        rows.append({name: cell[name] for name in PREDICATE_AUDIT_FIELDS})
    _write_csv(out_dir / "predicate_policy_audit_v3.csv",
               PREDICATE_AUDIT_FIELDS, rows)


EMPIRICAL_RULE_FIELDS = (
    "rule_id", "rule_type", "scope", "scope_kind", "predicate_uri", "direction",
    "minimum_support", "observed_support", "maximum_observed_cardinality",
    "observed_violation_count", "activation_status", "inactive_reason",
    "empirical_label", "version", "is_primary_configuration",
)


def write_empirical_rule_candidates(run: RationaleV3Run, out_dir: Path) -> None:
    """Every derived rule candidate, at the primary threshold and each ablation
    threshold, with its activation status and the evidence behind it."""
    rows: list = []
    thresholds = sorted(set(
        [run.rulebook.derivation.minimum_support]
        + list(run.rulebook.derivation.support_ablation_values)))
    quality = run.quality_policy
    for threshold in thresholds:
        book, _ = derive_rulebook(
            run.answers, base=run.base_rulebook,
            semantic_index=run.semantic_index,
            rejected_predicates=quality.hard_reject_predicates,   # type: ignore[attr-defined]
            minimum_support_override=threshold)
        for rule in book.rules:
            if rule.minimum_support != threshold:
                continue
            rows.append({
                "rule_id": rule.rule_id,
                "rule_type": rule.rule_type,
                "scope": rule.scope,
                "scope_kind": rule.scope_kind,
                "predicate_uri": rule.predicate_uri,
                "direction": rule.direction,
                "minimum_support": rule.minimum_support,
                "observed_support": rule.observed_support,
                "maximum_observed_cardinality": rule.maximum_observed_cardinality,
                "observed_violation_count": rule.observed_violation_count,
                "activation_status": rule.activation_status,
                "inactive_reason": rule.inactive_reason,
                "empirical_label": rule.empirical_label,
                "version": rule.version,
                "is_primary_configuration": _b(
                    threshold == run.rulebook.derivation.minimum_support),
            })
    rows.sort(key=lambda r: (r["minimum_support"], r["scope"],
                             r["predicate_uri"], r["direction"]))
    _write_csv(out_dir / "empirical_rule_candidates_v3.csv",
               EMPIRICAL_RULE_FIELDS, rows)


def write_combination_search_audit(run: RationaleV3Run, out_dir: Path) -> None:
    """One record per ready Answer: what the search actually enumerated."""
    records: list = []
    for selection in run.ready_selections:
        if selection.pool is None or selection.table is None:
            continue
        answer = run.answer_for(selection.answer_uri)
        records.append({
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
                    "top_feasible_combinations": [
                        outcome.as_record() for outcome in sorted(
                            search.feasible(selection.rho),
                            key=lambda o: (o.objective_prefix(),
                                           o.objective_suffix())
                        )[:AUDIT_TOP_COMBINATIONS]],
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
            "candidate_roster": [
                {"rank": c.rank, "candidate_uri": c.canonical_candidate_uri,
                 "candidate_local_index": c.candidate_local_index,
                 "lrolesim_score": c.score}
                for c in answer.ranked_candidates],
            "note": ("Feasibility is the exact set-cover result under the active "
                     "evidence policy, never the weaker condition that each "
                     "candidate merely has some fact the Answer's fact set does "
                     "not match."),
        })
    _write_jsonl(out_dir / "combination_search_audit_v3.jsonl", records)


POOL_ABLATION_FIELDS = (
    "answer_uri", "pool_size", "search_scope", "pool_candidate_count",
    "enumerated_combination_count", "evidence_policy",
    "selected_candidate_uris", "lrolesim_score_sum", "minimum_rationale_size",
    "rationale_min_level", "selection_agreement", "lrolesim_objective_regret",
    "rationale_level_agreement", "rationale_cardinality_agreement",
    "reference_search_scope", "reference_is_full_exact",
)


def write_pool_ablation(run: RationaleV3Run, out_dir: Path) -> None:
    rows: list = []
    for row in run.pool_ablation:
        selection = run.selection_for(row.answer_uri)
        reference_scope = (selection.pool.scope if selection.pool else "")
        rows.append({
            "answer_uri": row.answer_uri,
            "pool_size": row.pool_size,
            "search_scope": row.search_scope,
            "pool_candidate_count": row.pool_candidate_count,
            "enumerated_combination_count": row.enumerated_combination_count,
            "evidence_policy": row.evidence_policy,
            "selected_candidate_uris": "|".join(row.selected_candidate_uris),
            "lrolesim_score_sum": _fmt_score(row.lrolesim_score_sum),
            "minimum_rationale_size": ("" if row.minimum_rationale_size is None
                                       else row.minimum_rationale_size),
            "rationale_min_level": row.rationale_min_level,
            "selection_agreement": _b(row.selection_agreement),
            "lrolesim_objective_regret": _fmt_score(
                row.lrolesim_objective_regret),
            "rationale_level_agreement": _b(row.rationale_level_agreement),
            "rationale_cardinality_agreement": _b(
                row.rationale_cardinality_agreement),
            "reference_search_scope": reference_scope,
            "reference_is_full_exact": _b(reference_scope == SEARCH_FULL_EXACT),
        })
    _write_csv(out_dir / "candidate_pool_ablation_v3.csv",
               POOL_ABLATION_FIELDS, rows)


def write_fallback_class_requests(run: RationaleV3Run, out_dir: Path) -> None:
    """The §14 requests. Emitted and stopped at: no fallback class is executed."""
    records: list = []
    for selection in run.selections:
        if not selection.requires_fallback_class:
            continue
        answer = run.answer_for(selection.answer_uri)
        best_diagnostic = None
        if selection.selected is not None and selection.ranking is not None:
            best_diagnostic = {
                "evidence_policy": selection.evidence_policy,
                "rationale_min_level": selection.ranking.achieved_min_level,
                "distractor_uris": list(selection.selected.candidate_uris),
                "distractor_ranks": list(selection.selected.ranks),
                "minimum_rationale_size": selection.ranking.size,
            }
        else:
            partial = None
            for policy in POLICY_PRIORITY:
                search = selection.searches.get(policy)
                if search is not None and search.best_partial is not None:
                    partial = {"evidence_policy": policy,
                               **search.best_partial.as_record()}
                    break
            best_diagnostic = partial
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
            "note": ("Prompt 8F runs no class selection, candidate retrieval, "
                     "mapping, graph construction or LRoleSim for a fallback "
                     "class: Prompt 8D holds rankings for the Prompt-8C selected "
                     "class only. Exact enumeration over that class has already "
                     "performed evidence-aware candidate replacement inside it."),
        })
    _write_jsonl(out_dir / "fallback_class_requests_v3.jsonl", records)


def write_bipartite_fact_candidates(run: RationaleV3Run, out_dir: Path) -> None:
    """The §15 choice-evidence bipartite CANDIDATES. No subset is chosen here.

    Left side: the four choices (Answer = bit 0, distractors = bits 1..3). One
    record per (proposition, four-bit incidence mask) over every fact observed
    for any of the four. Selection of a budgeted subset, and drawing, belong to a
    later task.

    This is NOT the LRoleSim matching bipartite graph (CLAUDE.md item 6).
    """
    records: list = []
    for selection in run.selections:
        if (selection.selected is None or selection.table is None
                or selection.ranking is None):
            continue
        answer = run.answer_for(selection.answer_uri)
        table = selection.table
        positions = selection.selected.positions
        choices = (answer.answer_uri, *selection.selected.candidate_uris)
        selected_keys = set()
        best = selection.ranking.best
        if best is not None:
            selected_keys = {table.facts[i].canonical_key
                             for i in best.fact_indices}

        # O_x(κ) for each of the four choices, from the frozen observations.
        owned: dict = {answer.answer_uri: {}}
        for fact in answer.answer_facts:
            owned[answer.answer_uri].setdefault(fact.key_tuple, set()).add(
                fact.counterpart_uri)
        for uri in selection.selected.candidate_uris:
            bucket: dict = {}
            for fact in answer.candidate_facts.get(uri, ()):
                bucket.setdefault(fact.key_tuple, set()).add(fact.counterpart_uri)
            owned[uri] = bucket

        propositions: dict = {}
        for choice_uri in choices:
            for key, objects in owned[choice_uri].items():
                for obj in objects:
                    propositions.setdefault((key[0], key[1], obj), 0)
        for (predicate_uri, direction, obj) in sorted(propositions):
            mask = 0
            for bit, choice_uri in enumerate(choices):
                if obj in owned[choice_uri].get((predicate_uri, direction), ()):
                    mask |= 1 << bit
            propositions[(predicate_uri, direction, obj)] = mask

        answer_fact_index = {f.canonical_key: i
                             for i, f in enumerate(table.facts)}
        for (predicate_uri, direction, obj), mask in sorted(propositions.items()):
            key = (predicate_uri, direction, obj)
            index = answer_fact_index.get(key)
            quality = table.quality[index] if index is not None else None
            evidence_status = "NOT_AN_ANSWER_FACT"
            if index is not None:
                levels = [table.evidence[index][p].level for p in positions]
                evidence_status = "|".join(levels)
            degree = bin(mask).count("1")
            records.append({
                "answer_uri": answer.answer_uri,
                "distractor_uris": list(selection.selected.candidate_uris),
                "predicate_uri": predicate_uri,
                "direction": direction,
                "counterpart_uri": obj,
                "incidence_mask_abcd": mask,
                "incidence_mask_bits": format(mask, "04b"),
                "incident_choice_uris": [choices[bit] for bit in range(4)
                                         if (mask >> bit) & 1],
                "left_side_degree": degree,
                "shared_by_at_least_two_choices": degree >= 2,
                "is_answer_fact": index is not None,
                "evidence_status": evidence_status,
                "semantic_relation_status": (
                    "AVAILABLE" if run.semantic_index.available
                    else "SEMANTIC_RELATION_UNAVAILABLE"),
                "leakage_status": (quality.leakage.reason_code if quality
                                   else "NOT_ASSESSED"),
                "predicate_quality": (quality.pedagogical_tier if quality
                                      else None),
                "verbalizable": (quality.verbalizable if quality else None),
                "template_id": (quality.template_id if quality else None),
                "is_selected_rationale": key in selected_keys,
                "is_class_node": obj == answer.selected_class_uri,
                "final_bipartite_subset_selected": False,
            })
    _write_jsonl(out_dir / "bipartite_fact_candidates.jsonl", records)


def write_sulfuric_acid_diagnostic(run: RationaleV3Run, out_dir: Path) -> None:
    """The diagnostic rationale analysis, in its own file and namespace."""
    primary = run.selection_for(EXPECTED_PRIMARY_FAILURE_ANSWER_URI)
    diagnostic_input = run.diagnostic_input
    diagnostic = run.diagnostic_selection

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

    if diagnostic_input is None or diagnostic is None:
        payload["diagnostic_analysis"] = None
        _write_json(out_dir / "sulfuric_acid_diagnostic_v3.json", payload)
        return

    best = diagnostic.ranking.best if diagnostic.ranking else None
    payload["diagnostic_analysis"] = {
        "diagnostic_class_uri": diagnostic_input.selected_class_uri,
        "graph_fingerprint": diagnostic_input.graph_fingerprint,
        "candidate_count": diagnostic_input.candidate_count,
        "answer_fact_count": (diagnostic.table.fact_count
                              if diagnostic.table else 0),
        "eligible_answer_fact_count": (
            len(diagnostic.table.eligible_fact_indices)
            if diagnostic.table else 0),
        "k": diagnostic.k,
        "rho": diagnostic.rho,
        "search": (diagnostic.pool.as_record() if diagnostic.pool else None),
        "per_policy_feasible_counts": {
            policy: len(search.feasible(diagnostic.rho))
            for policy, search in sorted(diagnostic.searches.items())},
        "selection_status": diagnostic.status,
        "evidence_policy": diagnostic.evidence_policy or "",
        "rationale_min_level": (diagnostic.ranking.achieved_min_level
                                if diagnostic.ranking else LEVEL_NOT_COVERED),
        "selected_distractor_uris": (list(diagnostic.selected.candidate_uris)
                                     if diagnostic.selected else []),
        "selected_distractor_ranks": (list(diagnostic.selected.ranks)
                                      if diagnostic.selected else []),
        "minimum_rationale_size": (diagnostic.ranking.size
                                   if diagnostic.ranking else None),
        "minimum_rationale_count_before_quality_ranking": (
            diagnostic.ranking.minimum_rationale_count
            if diagnostic.ranking else None),
        "selected_rationale": (best.as_record() if best else None),
        "algorithm_selected_distractor": diagnostic.algorithm_selected,
        "eligible_for_main_corpus": False,
        "eligible_for_diagnostic_corpus": diagnostic.algorithm_selected,
        "fallback_status": diagnostic.fallback_status,
        **AUTOMATIC_GENERATION_FIELDS,
    }
    _write_json(out_dir / "sulfuric_acid_diagnostic_v3.json", payload)


PROMPT8E_COMPARISON_FIELDS = (
    "answer_uri", "display_label",
    "prompt8e_selection_status", "v3_selection_status",
    "prompt8e_evidence_policy", "v3_evidence_policy", "v3_evidence_level",
    "prompt8e_distractors", "v3_distractors", "distractor_set_identical",
    "prompt8e_minimum_rationale_size", "v3_minimum_rationale_size",
    "prompt8e_optimal_rationale_count",
    "v3_minimum_rationale_count_before_quality_ranking",
    "prompt8e_rationale_predicate", "prompt8e_rationale_direction",
    "prompt8e_rationale_counterpart",
    "v3_rationale_predicate", "v3_rationale_direction", "v3_rationale_counterpart",
    "rationale_identical", "v3_rejected_the_prompt8e_rationale",
    "v3_rejection_reasons", "pedagogical_ranking_changed_the_choice",
    "v3_eligible_for_main_corpus", "v3_fallback_status",
)


def write_prompt8e_comparison(run: RationaleV3Run, out_dir: Path,
                              prompt8e_dir: str | Path = FROZEN_PROMPT8E_DIR
                              ) -> None:
    """Row-by-row V3 versus the frozen Prompt-8E result.

    Reads the Prompt-8E artefacts as DATA. Prompt 8E is not re-executed and not
    modified; the comparison exists so every difference is attributable to a
    named V3 rule rather than to a re-run.
    """
    prompt8e_dir = Path(prompt8e_dir)
    previous: dict = {}
    summary_path = prompt8e_dir / "rationale_selection_summary.csv"
    if summary_path.is_file():
        for row in _read_csv(summary_path):
            previous[row["answer_uri"]] = row
    rationales: dict = {}
    rationale_path = prompt8e_dir / "selected_rationales.jsonl"
    if rationale_path.is_file():
        for record in _read_jsonl(rationale_path):
            rationales.setdefault(record["answer_uri"], []).append(record)

    rows: list = []
    for answer_uri in run.primary_order:
        selection = run.selection_for(answer_uri)
        old = previous.get(answer_uri, {})
        old_facts = rationales.get(answer_uri, [])
        old_distractors = tuple(
            old.get(f"distractor_{i}_uri", "") for i in (1, 2, 3))
        old_distractors = tuple(u for u in old_distractors if u)

        new_distractors: tuple = ()
        new_size = ""
        new_count = ""
        new_facts: list = []
        if selection.selected is not None and selection.ranking is not None:
            new_distractors = selection.selected.candidate_uris
            new_size = selection.ranking.size
            new_count = selection.ranking.minimum_rationale_count
            best = selection.ranking.best
            if best is not None and selection.table is not None:
                new_facts = [selection.table.facts[i] for i in best.fact_indices]

        rejected = ""
        reasons: list = []
        if old_facts and selection.table is not None:
            index_by_key = {f.canonical_key: i
                            for i, f in enumerate(selection.table.facts)}
            for record in old_facts:
                key = (record["predicate_uri"], record["direction"],
                       record["counterpart_uri"])
                index = index_by_key.get(key)
                if index is None:
                    reasons.append("FACT_NOT_PRESENT_IN_V3_TABLE")
                    continue
                quality = selection.table.quality[index]
                if not quality.eligible:
                    reasons.extend(quality.rejection_reasons)
            rejected = _b(bool(reasons))

        old_keys = tuple(sorted((r["predicate_uri"], r["direction"],
                                 r["counterpart_uri"]) for r in old_facts))
        new_keys = tuple(sorted(f.canonical_key for f in new_facts))
        rows.append({
            "answer_uri": answer_uri,
            "display_label": old.get("display_label", ""),
            "prompt8e_selection_status": old.get("selection_status", ""),
            "v3_selection_status": selection.status,
            "prompt8e_evidence_policy": old.get("evidence_policy", ""),
            "v3_evidence_policy": selection.evidence_policy or "",
            "v3_evidence_level": (selection.ranking.achieved_min_level
                                  if selection.ranking else ""),
            "prompt8e_distractors": "|".join(old_distractors),
            "v3_distractors": "|".join(new_distractors),
            "distractor_set_identical": _b(
                bool(old_distractors) and bool(new_distractors)
                and set(old_distractors) == set(new_distractors)),
            "prompt8e_minimum_rationale_size": old.get(
                "minimum_rationale_size", ""),
            "v3_minimum_rationale_size": new_size,
            "prompt8e_optimal_rationale_count": old.get(
                "optimal_rationale_count", ""),
            "v3_minimum_rationale_count_before_quality_ranking": new_count,
            "prompt8e_rationale_predicate": "|".join(k[0] for k in old_keys),
            "prompt8e_rationale_direction": "|".join(k[1] for k in old_keys),
            "prompt8e_rationale_counterpart": "|".join(k[2] for k in old_keys),
            "v3_rationale_predicate": "|".join(k[0] for k in new_keys),
            "v3_rationale_direction": "|".join(k[1] for k in new_keys),
            "v3_rationale_counterpart": "|".join(k[2] for k in new_keys),
            "rationale_identical": _b(bool(old_keys) and old_keys == new_keys),
            "v3_rejected_the_prompt8e_rationale": rejected,
            "v3_rejection_reasons": "|".join(sorted(set(reasons))),
            "pedagogical_ranking_changed_the_choice": _b(
                bool(old_keys) and bool(new_keys) and old_keys != new_keys),
            "v3_eligible_for_main_corpus": _b(selection.eligible_for_main_corpus),
            "v3_fallback_status": selection.fallback_status,
        })
    _write_csv(out_dir / "prompt8e_comparison.csv",
               PROMPT8E_COMPARISON_FIELDS, rows)


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
            "--mode pilot-rationale-v3 --output-dir <fresh directory>"),
        "byte_identical_files": list(REPLAY_COMPARED_FILES),
        "excluded_from_byte_identity": [
            "run_manifest.json (records the run clock, timings and git state)",
            "offline_replay_manifest.json (contains the hashes it verifies)",
            "implementation_report.md (narrative)",
        ],
        "file_hashes": compared,
        "network": run.guard_record,
        "http_calls": 0,
        "sparql_calls": 0,
        "forbidden_modules_loaded_in_process": list(run.forbidden_modules),
        "forbidden_modules_note": (
            "A PROCESS-WIDE snapshot of sys.modules taken after the run. Exact "
            "for a standalone invocation, which is how this package is produced. "
            "Inside a shared pytest session the same list also reports modules "
            "other test files imported, so the test suite asserts the delta "
            "introduced by this code path instead."),
        "prompt8d_input_sha256": dict(run.inputs.input_sha256),
        "prompt8d_zip_expected_sha256": FROZEN_PROMPT8D_ZIP_SHA256,
        "prompt8e_zip_expected_sha256": FROZEN_PROMPT8E_ZIP_SHA256,
        "pinned_local_kg_expected_sha256": PINNED_LOCAL_KG_SHA256,
        "pinned_local_kg_loaded": False,
        "semantic_index": run.semantic_index.as_record(),
        "protected_sources": run.protected_sources,
    })


def write_run_manifest(run: RationaleV3Run, out_dir: Path,
                       raw_command: Sequence[str] = ()) -> None:
    quality = run.quality_policy
    _write_json(out_dir / "run_manifest.json", {
        "task": ("Prompt 8F - evidence-level rationale V3, semantic-safety "
                 "checks, pedagogical quality and scalable distractor search"),
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
        "prompt8d_input_sha256": dict(run.inputs.input_sha256),
        "protected_sources": run.protected_sources,
        "pinned_local_kg_expected_sha256": PINNED_LOCAL_KG_SHA256,
        "pinned_local_kg_loaded": False,
        "lrolesim_execution_path": {
            "ranker_name": EXPECTED_RANKER_NAME,
            "measure": EXPECTED_MEASURE,
            "lrolesim_beta": EXPECTED_LROLESIM_BETA,
            "iterations": EXPECTED_ITERATIONS,
            "iteration_mode": EXPECTED_ITERATION_MODE,
            "note": ("frozen and consumed, not recomputed: Prompt 8F reads the "
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
            "legacy_one_fact_special_case": LEGACY_ONE_FACT_SPECIAL_CASE_NOTE,
            "provenance": SET_COVER_PROVENANCE_NOTE,
        },
        "evidence_model": {
            "levels": list(LEVEL_DEFINITION),
            "level_definitions": dict(LEVEL_DEFINITION),
            "policy_priority": list(POLICY_PRIORITY),
            "policy_notes": dict(POLICY_NOTE),
            "multi_valued_predicate_note": MULTI_VALUED_PREDICATE_NOTE,
            "qualifier_note": QUALIFIER_NOTE,
            "parent_child_note": PARENT_CHILD_NOTE,
            "rule_counts": run.rulebook.counts(),
            "empirical_derivation": run.rulebook.derivation.as_record(),
            "support_threshold_ablation": {
                str(threshold): counts
                for threshold, counts in sorted(run.support_ablation.items())},
            "require_semantic_closure_for_l1":
                run.rulebook.require_semantic_closure_for_l1,
        },
        "semantic_index": run.semantic_index.as_record(),
        "quality_policy": quality.as_record(),           # type: ignore[attr-defined]
        "combination_search": {
            **run.pool_policy.as_record(),
            "pool_ablation_sizes": list(POOL_ABLATION_SIZES),
            "pool_optimality_note": POOL_OPTIMALITY_NOTE,
        },
        "input_contract_checks": [
            {"check": name, "detail": detail}
            for name, detail in run.contract_checks],
        "counts": run.counts(),
        "network": run.guard_record,
        "forbidden_modules_loaded_in_process": list(run.forbidden_modules),
        "stage_timings": [timing.as_row() for timing in run.timings],
        "automatic_generation": {
            **AUTOMATIC_GENERATION_FIELDS,
            "note": PUBLISHABLE_FINAL_NOTE,
        },
        "open_world_note": (
            "Every fact in this package is OBSERVED in the pinned local KG "
            "snapshot. L0 records observed non-support in one snapshot; L1 is a "
            "scoped operational contrast; only L2 asserts exclusion, and only "
            "with an EvidenceProof. An absent triple is simply absent."),
        "scope_note": (
            "Stops before natural-language verbalization, before final Bipartite "
            "Graph selection and drawing, before fallback-class execution, and "
            "before human evaluation."),
    })


def write_all_outputs(run: RationaleV3Run, out_dir: str | Path,
                      raw_command: Sequence[str] = (),
                      prompt8e_dir: str | Path = FROZEN_PROMPT8E_DIR) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_summary(run, out_dir)
    write_algorithm_selected_distractors(run, out_dir)
    write_selected_rationales(run, out_dir)
    write_all_minimum_rationale_candidates(run, out_dir)
    write_per_candidate_evidence(run, out_dir)
    write_evidence_proofs(run, out_dir)
    write_semantic_relation_audit(run, out_dir)
    write_quality_filter_audit(run, out_dir)
    write_predicate_policy_audit(run, out_dir)
    write_empirical_rule_candidates(run, out_dir)
    write_combination_search_audit(run, out_dir)
    write_pool_ablation(run, out_dir)
    write_fallback_class_requests(run, out_dir)
    write_bipartite_fact_candidates(run, out_dir)
    write_sulfuric_acid_diagnostic(run, out_dir)
    write_prompt8e_comparison(run, out_dir, prompt8e_dir)
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


# ==========================================================================
# 9) CLI
# ==========================================================================

MODE_RATIONALE_V3 = "pilot-rationale-v3"
MODE_BUILD_SEMANTIC_INDEX = "build-semantic-index"
MODES = (MODE_RATIONALE_V3, MODE_BUILD_SEMANTIC_INDEX)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python src/pipeline/rationale_v3_run.py",
        description=("Prompt 8F - evidence-level rationale V3 over the frozen "
                     "Prompt-8D handoff. Strictly offline."))
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--prompt8d-dir", default=str(FROZEN_PROMPT8D_DIR))
    parser.add_argument("--prompt8e-dir", default=str(FROZEN_PROMPT8E_DIR))
    parser.add_argument("--semantic-index-cache",
                        default=str(DEFAULT_SEMANTIC_INDEX_CACHE))
    parser.add_argument("--local-kg", default=str(PINNED_LOCAL_KG))
    parser.add_argument("-k", type=int, default=DEFAULT_K)
    parser.add_argument("--rho", type=int, default=DEFAULT_RHO)
    parser.add_argument("--max-exact-combinations", type=int,
                        default=DEFAULT_MAX_EXACT_COMBINATIONS)
    parser.add_argument("--skip-pool-ablation", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


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
        run_pool_ablation=not args.skip_pool_ablation,
        verbose=not args.quiet)
    out_dir = write_all_outputs(run, args.output_dir, raw_command,
                                args.prompt8e_dir)
    counts = run.counts()
    print(f"\n[done] mode={run.mode}  ranker={run.ranker_name}  "
          f"k={run.k} rho={run.rho}")
    print(f"       outputs -> {out_dir}")
    print(f"       primary Answers: {counts['primary_answer_denominator']} "
          f"({counts['primary_ready_for_rationale_selection']} ready)")
    print(f"       strict-L2: {counts['algorithm_selected_strict_l2']}  "
          f"main-L1plus: {counts['algorithm_selected_main_l1plus']}  "
          f"diagnostic-L0 only: "
          f"{counts['algorithm_selected_diagnostic_l0_only']}")
    print(f"       eligible for main corpus: "
          f"{counts['eligible_for_main_corpus']}")
    print(f"       fallback class requests: {counts['fallback_class_requests']}")
    print(f"       network attempts: "
          f"{run.guard_record['network_attempts']} (http 0, sparql 0)")
    print("       every record: generation_is_automatic=true, "
          "manual_intervention_used=false, publishable_final=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
