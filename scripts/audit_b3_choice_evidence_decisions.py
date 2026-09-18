#!/usr/bin/env python
############################################################################
# scripts/audit_b3_choice_evidence_decisions.py
#
#   AUDIT / DECISION SUPPORT ONLY — NOT PRODUCTION B3 CODE.
#
# Prompt 8H-B3-ARCH-3 (2026-09-18). Offline development-batch measurements
# that give the human researcher empirical decision support for the open
# choice–evidence architecture decisions of ARCH-2:
#
#   H5   require-verbalizable cost (counterfactual audit, nothing changed)
#   H6   is the already-installed HiGHS/scipy exact route adequate?
#   H7   exposure and budget behaviour (B_pre groups, B_post ENTITY nodes)
#   H13  lexicographic objective stability (adjacent key swaps)
#   H14  pre-answer grounding-clean admissibility arms A / B / C
#   H18  universe bounding: modular pre-key versus stratified, N_max stability
#
# WHAT THIS SCRIPT IS NOT
#   * It is not `src/choice_evidence_v1/`; no production package is created.
#   * It changes nothing upstream. The selected Answer, the selected class,
#     the selected distractors, the frozen LRoleSim ranks and scores, the
#     frozen evidence levels, the frozen R* and every open-world rule are
#     READ from the v4 artefacts and never fed back.
#   * It is not a publication run. Every number it writes is a DEVELOPMENT
#     measurement on the two 2026-09-18 development batches.
#   * It performs no network access. The pinned KG is opened read-only.
#
# INPUTS
#   The per-Answer artefact trees written by an OFFLINE REPLAY of the v4
#   runner (`scripts/run_phase_b2_any_answer_v4.py --offline-replay`) for
#   `data/Answers.txt` and `data/Answers_HISTORICAL_EVENTS_PLACES.txt`, into
#   the evidence directory, with private copies of the four offline caches so
#   the originals are never touched. The replay is verified item by item
#   against the 2026-09-18 batch reports (`replay_verification.csv`).
#
# STAGES (run in this order; each is resumable and idempotent)
#   verify     compare the replay reports with the 2026-09-18 reports
#   universe   build the B3 audit universe of every learner-facing main-L1
#              item: observed fact edges of the four choices, clue groups,
#              grounding annotations, tiers, attributes (needs the pinned KG)
#   h5         kernel replay + counterfactual require-verbalizable audit
#              (needs no KG; uses the frozen kernel read-only)
#   measure    H14 arms, H13 swaps, H7 sweep, H18 bounding, H6 solver metrics
#              (exact 0-1 optimisation with scipy.optimize.milp / HiGHS)
#   rerun      deterministic re-solve of a sample and byte comparison (H6)
#   package    rollups, manifest, SHA-256 sums, ZIP with testzip()
#
# EVERY SCIENTIFIC RULE IS COMMENTED WHERE IT IS APPLIED. Search for the
# markers  [RULE]  (an open-world or evidence rule),  [ARCH-1]  (a design
# element taken from the first architecture) and  [ARCH-2]  (a change the
# review asked for) to find them.
############################################################################
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import itertools
import json
import math
import os
import platform
import re
import statistics
import signal
import subprocess
import sys
import time
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

# Single-threaded numerical libraries: HiGHS (through scipy) and any BLAS use
# must not fan out across cores inside a worker process, so the measurements
# are reproducible and the per-call timings are comparable.  [H6]
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import numpy as np                                            # noqa: E402
from scipy.optimize import milp, LinearConstraint, Bounds      # noqa: E402
from scipy.sparse import csr_matrix                           # noqa: E402
import scipy                                                  # noqa: E402

# Frozen / versioned project modules, all consumed READ-ONLY.
import mcq_core                                               # noqa: E402
from mcq_core import (Candidate, AnswerFact, FactQuality as KernelFactQuality,   # noqa: E402
                      build_case, select_distractors, rank_minimum_rationales,
                      RATIONALE_OBJECTIVE_V3)
from selection.granularity_clean import select_with_rationale_filter  # noqa: E402
from rationale_v3.quality import (load_quality_policy, assess_fact_quality,  # noqa: E402
                                  detect_answer_leakage, display_label,
                                  leakage_tokens)
from rationale_v3.predicate_aliases import DEFAULT_ALIAS_POLICY, observed_objects_for_key  # noqa: E402
from rationale_v3.semantic_relations import (normalize_uri, load_semantic_relation_policy,  # noqa: E402
                                             SemanticIndexCacheKey, source_object_list_sha256,
                                             load_semantic_index_cache)
from rationale_v3 import contracts as C                       # noqa: E402

SCRIPT_VERSION = "audit_b3_choice_evidence_decisions/1.0.0-development-only"
TODAY = "2026-09-18"
PREDICATE_POLICY_PATH = SRC / "rationale_v3" / "policies" / "predicate_policy_v2.json"
SEMANTIC_POLICY_PATH = SRC / "rationale_v3" / "policies" / "semantic_relation_policy_v2.json"
PINNED_KG_PATH = REPO_ROOT / "data" / "infobox.pickle_EnglishVersion_EntityType"
PINNED_KG_SHA256 = "e230c5b95e20093631697624d9c46f30a14081b3f415d5027ffaf313bdbbea1b"

LETTERS = ("A", "B", "C", "D")            # [RULE] A = Answer by task semantics; B/C/D = distractors in kernel position order
ANSWER_LETTER = "A"

# --- grounding vocabulary (ARCH-1 three values + the two ARCH-2 additions) ---
G_SHARED = "SHARED"                                   # letter owns an edge to this node (support)
G_ALT = "ALTERNATIVE_OBSERVED"                        # letter has an observed value under the key, none supporting the node
G_ABS = "ABSENCE_ONLY"                                # snapshot records nothing under the key for this letter
G_CONT = "SHARED_BY_CONTAINMENT"                      # letter's recorded value supports the node via equivalence/containment [ARCH-2]
G_UNRES = "UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE"     # closure could not run [ARCH-2]; never downgraded to absence

R_NONE = C.GRANULARITY_RISK_NONE
R_PRESENT = C.GRANULARITY_RISK_PRESENT                # CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT
R_UNRES = C.GRANULARITY_RISK_UNRESOLVED
R_UNMOD = C.GRANULARITY_RISK_HIERARCHY_UNMODELLED

# --- tiers (ARCH-1 §5.3) ---
T_MAND = "MANDATORY_RATIONALE"
T_ALT = "RATIONALE_ALTERNATIVE"
T_OPT = "OPTIONAL_CONTEXT"
T_EXCL = "EXCLUDED"

# --- the designated audit configuration for H13 / H18 (declared, not chosen from human data) ---
DESIGNATED_B_PRE = 4
DESIGNATED_B_POST = 7
DESIGNATED_K_A_POST = 1
B_PRE_SWEEP = (2, 3, 4, 5, 6)
B_POST_SWEEP = (4, 5, 6, 7, 8, 9, 10)
K_A_POST_SWEEP = (0, 1)
N_MAX_SWEEP = (100, 200, 400, 800)
FULL_UNIVERSE_CAP = 3000          # optional groups above this are not solved at UNIVERSE_FULL (recorded)
MEASURE_N_MAX = 400               # the bounded universe used for H13 and H7 (stratified); H18 studies bounding itself
STRATA_K_KEY = 2                  # stratified bounding: top-k per distinct predicate-direction family
STRATA_K_LETTER = 5               # stratified bounding: top-k per distractor letter
ORACLE_MAX_FREE = 16              # exhaustive oracle runs when the free-group count is at most this
CANONICAL_BLOCK = 24              # groups per block in the block-lexicographic canonical fix
MILP_TIME_LIMIT = 300.0
H5_CALL_TIME_BUDGET_S = 120        # per exact kernel call in the H5 counterfactual; a timeout is a RECORDED outcome
H5_KERNEL_TIME_BUDGET_S = 240      # for the baseline kernel replay itself (large pools); a timeout is a RECORDED outcome

# ARCH-1 §6.3 candidate weights (used ONLY for the comparator arm "ARCH-1 weighted")
ARCH1_WEIGHTS = {"W_sup": 4, "W_tier": 2, "W_verb": 2, "W_div": 3, "W_red": 2, "W_bal": 3,
                 "W_len_pre": 1, "W_len_post": 0, "W_ans_pre": 6, "W_ans_post": 3,
                 "W_single": 2, "W_abs": 3, "W_risk": 2, "W_soft": 1, "W_dl": 1}

PRE_KEYS = ("uncovered_letters", "neg_shared_information", "neg_distinct_keys",
            "clue_groups", "tier_sum", "token_sum")
POST_KEYS = ("absence_incidences", "risk_groups", "neg_shared_information",
             "neg_distinct_keys", "entity_nodes", "tier_sum", "token_sum")


def say(msg: str) -> None:
    print(msg, flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: Any, gz: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True)
    if gz:
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(text)
    else:
        path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> Any:
    if str(path).endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: Sequence[Mapping], columns: Optional[Sequence[str]] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    cols = list(columns) if columns else list(rows[0].keys())
    for row in rows:
        for k in row.keys():
            if k not in cols:
                cols.append(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in cols})


def pct(num: int, den: int) -> Optional[float]:
    return None if den == 0 else round(100.0 * num / den, 2)


def rate(num: int, den: int) -> dict:
    """Every rate carries its denominator.  [methodological safeguard §11]"""
    return {"numerator": num, "denominator": den, "percent": pct(num, den)}


def cohort_group(cohort_label: str) -> str:
    """Coarse cohort grouping — EVALUATION METADATA ONLY (never passed upstream).

    Derived from the `#COHORT:` header of the input file exactly as the v4
    runner carried it into `batch_summary.csv`. The keyword mapping is the
    whole rule and is recorded in the manifest.
    """
    up = (cohort_label or "").upper()
    if "CHEMISTRY" in up:
        return "CHEMISTRY"
    if "EVENTS" in up:
        return "EVENT"
    if "PLACES" in up:
        return "PLACE"
    if "POLITIES" in up:
        return "POLITY"
    return "PERSON"


# ==========================================================================
# 1) LOADING THE FROZEN v4 ARTEFACTS (read-only)
# ==========================================================================

@dataclass
class ItemRef:
    """One development item: where its v4 artefacts are and its gate verdict."""
    slug: str
    batch: str                 # "answers" | "hist"
    artifact_dir: Path
    answer_uri: str
    display_label: str
    cohort: str
    cohort_group: str
    status: str
    has_main_l1_selection: bool
    mcq_evidence_level: str
    learner_facing: bool
    gate_passed: bool
    gate_reason: str
    seconds_v4: float
    granularity_risk_incidences: int
    m1_node_count: int


def list_items(replay_root: Path) -> list[ItemRef]:
    """Every Answer row of both replayed batches, with the learner-facing gate.

    [RULE] Gate = a v4 SUCCESS status, `has_main_l1_selection`, MCQ level in
    {MCQ-L1, MCQ-L2} and learner-facing under the recorded granularity policy
    (report-only in the 2026-09-18 batches, so every selected item is
    learner-facing there; the incidence count is still carried).
    """
    refs: list[ItemRef] = []
    for batch in ("answers", "hist"):
        art = replay_root / batch / "artifacts"
        summary = art / "batch_summary.csv"
        if not summary.is_file():
            continue
        rows = list(csv.DictReader(open(summary, encoding="utf-8")))
        # map original_uri -> artefact dir by reading each dir's final_selection.json / answer_identity.json
        dirs = sorted(p for p in art.iterdir() if p.is_dir() and re.match(r"^\d{4}_", p.name))
        uri_to_dir: dict[str, Path] = {}
        for d in dirs:
            ident = d / "answer_identity.json"
            if ident.is_file():
                try:
                    uri_to_dir[read_json(ident)["original_uri"]] = d
                except Exception:      # noqa: BLE001
                    pass
        seen = set()
        for row in rows:
            uri = row["original_uri"]
            if uri in seen:
                continue
            seen.add(uri)
            d = uri_to_dir.get(uri)
            status = row.get("status", "")
            has_main = row.get("has_main_l1_selection", "") == "True"
            mcq = row.get("mcq_evidence_level", "")
            learner_facing = True
            gpo = d / "granularity_policy_outcome.json" if d else None
            if gpo is not None and gpo.is_file():
                try:
                    learner_facing = bool(read_json(gpo).get("learner_facing_under_policy", True))
                except Exception:      # noqa: BLE001
                    learner_facing = True
            reason = ""
            if d is None:
                reason = "NO_ARTIFACT_DIR"
            elif not status.startswith("SUCCESS"):
                reason = f"STATUS_{status}"
            elif not has_main:
                reason = "NO_MAIN_L1_SELECTION"
            elif mcq not in ("MCQ-L1", "MCQ-L2"):
                reason = f"MCQ_LEVEL_{mcq}"
            elif not learner_facing:
                reason = "NOT_LEARNER_FACING_UNDER_GRANULARITY_POLICY"
            elif not (d / "final_selection.json").is_file():
                reason = "NO_FINAL_SELECTION"
            refs.append(ItemRef(
                slug=(d.name if d else re.sub(r"[^A-Za-z0-9_]+", "_", uri.rsplit("/", 1)[-1])),
                batch=batch, artifact_dir=d if d else art,
                answer_uri=uri, display_label=row.get("display_label", ""),
                cohort=row.get("cohort", ""), cohort_group=cohort_group(row.get("cohort", "")),
                status=status, has_main_l1_selection=has_main, mcq_evidence_level=mcq,
                learner_facing=learner_facing, gate_passed=(reason == ""), gate_reason=reason,
                seconds_v4=float(row.get("seconds") or 0.0),
                granularity_risk_incidences=int(row.get("granularity_risk_incidences") or 0),
                m1_node_count=int(row.get("m1_node_count") or 0)))
    return refs


def item_key(ref: ItemRef) -> str:
    return f"{ref.batch}__{ref.slug}"


# ==========================================================================
# 2) REPLAY VERIFICATION — the replay must reproduce the 2026-09-18 reports
# ==========================================================================

TABLE_HEADER_PREFIX = "| # | Answer | Line | Status |"


def parse_report_table(report_path: Path) -> dict[str, dict]:
    """Parse the final per-Answer batch table of a v4 report into {Answer: cells}.

    Cells are split on ' | ' (space-pipe-space) because the "Per-distractor"
    cell contains unescaped bare pipes (`L1|L1|L1`).
    """
    rows: dict[str, dict] = {}
    if not report_path.is_file():
        return rows
    header: Optional[list[str]] = None
    with open(report_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith(TABLE_HEADER_PREFIX):
                header = [c.strip() for c in line.strip().strip("|").split(" | ")]
                continue
            if header is None:
                continue
            if not line.startswith("| "):
                if line.strip() == "" or line.startswith("|---"):
                    continue
                header = None
                continue
            cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
            if len(cells) < 8 or not cells[0].isdigit():
                continue
            rec = dict(zip(header, cells))
            rows[rec.get("Answer", cells[1])] = rec
    return rows


COMPARE_COLUMNS = ("Status", "Class", "Cands", "Distractors (rank)", "\\|R*\\|",
                   "Rationale facts", "Per-distractor", "MCQ", "Risk", "OptRef")


def verify_replay(replay_root: Path, original_reports: Mapping[str, Path], out_dir: Path) -> dict:
    """Item-by-item equality of the replay against the 2026-09-18 batch reports."""
    rows = []
    summary = {}
    for batch, original in original_reports.items():
        replay_report = replay_root / batch / "report.md"
        a = parse_report_table(original)
        b = parse_report_table(replay_report)
        matched = mismatched = missing = 0
        for name, rec in a.items():
            other = b.get(name)
            if other is None:
                missing += 1
                rows.append({"batch": batch, "answer": name, "verdict": "MISSING_IN_REPLAY"})
                continue
            diffs = [c for c in COMPARE_COLUMNS if rec.get(c, "") != other.get(c, "")]
            if diffs:
                mismatched += 1
                rows.append({"batch": batch, "answer": name, "verdict": "MISMATCH",
                             "columns": ";".join(diffs),
                             "original": " || ".join(rec.get(c, "") for c in diffs),
                             "replay": " || ".join(other.get(c, "") for c in diffs)})
            else:
                matched += 1
                rows.append({"batch": batch, "answer": name, "verdict": "MATCH"})
        summary[batch] = {"original_rows": len(a), "replay_rows": len(b), "matched": matched,
                          "mismatched": mismatched, "missing_in_replay": missing,
                          "original_report": str(original), "replay_report": str(replay_report)}
    write_csv(out_dir / "replay_verification.csv", rows,
              ["batch", "answer", "verdict", "columns", "original", "replay"])
    write_json(out_dir / "replay_verification.json", summary)
    return summary


# ==========================================================================
# 3) THE B3 AUDIT UNIVERSE — observed facts of A, B, C, D; groups; grounding
# ==========================================================================

SUPPORTING_RELATIONS = frozenset({C.RELATION_EXACT_EQUAL, C.RELATION_CANONICALLY_EQUIVALENT,
                                  C.RELATION_CANDIDATE_UNDER_CLAIM, C.RELATION_SCOPED_VALUE_EQUIVALENT})
IDENTITY_RELATIONS = frozenset({C.RELATION_EXACT_EQUAL, C.RELATION_CANONICALLY_EQUIVALENT})
RISK_ORDER = {R_NONE: 0, R_UNMOD: 1, R_UNRES: 2, R_PRESENT: 3}


def load_item_selection(ref: ItemRef) -> dict:
    """The frozen selection of one item: A, D (position order), R*, levels."""
    fs = read_json(ref.artifact_dir / "final_selection.json")
    detail = list(csv.DictReader(open(ref.artifact_dir / "rationale_evidence_detail.csv", encoding="utf-8")))
    distractors = sorted(fs["distractors"], key=lambda d: d["position"])
    # R* facts with their per-distractor frozen levels, keyed by fact_index
    rstar: dict[int, dict] = {}
    for row in detail:
        fi = int(row["fact_index"])
        rec = rstar.setdefault(fi, {
            "fact_index": fi, "predicate_uri": normalize_uri(row["predicate_uri"]),
            "direction": row["direction"], "counterpart_uri": normalize_uri(row["counterpart_uri"]),
            "levels": {}, "bases": {}, "risks": {}})
        rec["levels"][row["distractor_uri"]] = row["evidence_level"]
        rec["bases"][row["distractor_uri"]] = row["exclusion_basis"]
        rec["risks"][row["distractor_uri"]] = row["granularity_risk"]
    quality_by_identity = {(normalize_uri(f["predicate_uri"]), f["direction"], normalize_uri(f["counterpart_uri"])): f
                           for f in fs["rationale"]}
    for rec in rstar.values():
        q = quality_by_identity.get((rec["predicate_uri"], rec["direction"], rec["counterpart_uri"]), {})
        rec["verbalizable"] = bool(q.get("verbalizable", False))
        rec["template_id"] = q.get("template_id", "")
        rec["pedagogical_tier"] = q.get("pedagogical_tier")
        rec["coverage_mask"] = q.get("coverage_mask")
    prov = fs.get("phase_b1_provenance", {})
    return {
        "answer_uri": fs["answer_uri"], "display_label": fs["display_label"],
        "evidence_policy": fs["evidence_policy"], "mcq_evidence_level": fs.get("mcq_evidence_level"),
        "distractors": distractors, "rstar": rstar,
        "selected_class_uri": prov.get("selected_class_uri", ""),
        "search_scope": fs.get("search_scope"), "minimum_rationale_size": fs.get("minimum_rationale_size"),
        "direct_identifier_flag": fs.get("direct_identifier_flag"),
        "option_reference_conflict_count": fs.get("option_reference_conflict_count"),
        "rationale_objective": fs.get("rationale_objective"),
        "pinned_kg_sha256": prov.get("pinned_kg_sha256"),
        "quality_policy_sha256": prov.get("quality_policy_sha256"),
        "semantic_relation_policy_sha256": prov.get("semantic_relation_policy_sha256"),
    }


def load_answer_fact_rows(ref: ItemRef) -> dict[int, dict]:
    """All Answer facts × all candidates from `candidate_fact_evidence.csv`.

    The FROZEN levels live here. They are copied, never recomputed.  [RULE]
    """
    facts: dict[int, dict] = {}
    with open(ref.artifact_dir / "candidate_fact_evidence.csv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            fi = int(row["fact_index"])
            rec = facts.setdefault(fi, {
                "fact_index": fi, "eligible": row["fact_eligible"] == "True",
                "predicate_uri": normalize_uri(row["predicate_uri"]), "direction": row["direction"],
                "counterpart_uri": normalize_uri(row["counterpart_uri"]), "per_candidate": {}})
            rec["per_candidate"][row["candidate_uri"]] = (row["evidence_level"], row["exclusion_basis"],
                                                          row["granularity_risk"])
    return facts


def load_ranking(ref: ItemRef) -> list[Candidate]:
    rows = list(csv.DictReader(open(ref.artifact_dir / "complete_lrolesim_ranking.csv", encoding="utf-8")))
    return [Candidate(rank=int(r["rank"]), score=float(r["score"]), uri=r["canonical_candidate_uri"]) for r in rows]


class UniverseBuilder:
    """Builds the B3 audit universe for one item from the pinned KG + v4 artefacts.

    Holds the loaded KG, the quality policy, the semantic policy and per-run
    caches. One instance per process; `build(ref)` per item.
    """

    def __init__(self, evidence_dir: Path, *, local_kg, quality_policy, semantic_policy):
        self.evidence_dir = evidence_dir
        self.kg = local_kg
        self.qp = quality_policy
        self.sp = semantic_policy
        self.index_root = evidence_dir / "b3_semantic_index"
        self.index_root.mkdir(parents=True, exist_ok=True)
        import mcq_inputs as _mi
        from pipeline.rationale_v3_run import build_semantic_index_from_pinned_kg as _bsi
        self._mi = _mi
        self._build_index = _bsi
        self._quality_cache: dict[tuple, Any] = {}
        self._place_rules: Optional[frozenset] = None

    # --- semantic index over the counterparts of all four choices ---------------
    def semantic_index_for(self, slug: str, sources: Sequence[str]) -> tuple[Any, dict]:
        """[RULE] The B3 index has ITS OWN cache key (its own source-object set) and
        provenance. It is used for grounding, node identity and containment/risk
        annotation only. It never re-decides a frozen level, never changes R*,
        never touches the distractor selection or LRoleSim."""
        sources = tuple(sorted({normalize_uri(u) for u in sources}))
        digest = source_object_list_sha256(sources)
        path = self.index_root / f"{slug}__{digest[:16]}.json"
        key = SemanticIndexCacheKey(
            pinned_kg_sha256=PINNED_KG_SHA256, policy_sha256=self.sp.policy_sha256,
            source_object_list_sha256=digest, max_depth=self.sp.max_depth,
            creation_command="python scripts/audit_b3_choice_evidence_decisions.py universe "
                             "(build_semantic_index_from_pinned_kg; B3 audit index, own cache key)")
        built = False
        index = load_semantic_index_cache(path, policy=self.sp, expected_key=key) if path.is_file() else None
        if index is None or not index.available:
            self._build_index(policy_path=SEMANTIC_POLICY_PATH, cache_path=path,
                              source_object_uris=sources, local_kg=self.kg, verbose=False)
            built = True
            index = load_semantic_index_cache(path, policy=self.sp, expected_key=key)
        return index, {"available": index.available, "unavailable_reason": index.unavailable_reason,
                       "source_object_count": len(sources), "source_object_list_sha256": digest,
                       "cache_path": str(path.relative_to(self.evidence_dir)), "built_now": built,
                       "policy_version": self.sp.version, "policy_sha256": self.sp.policy_sha256,
                       "max_depth": self.sp.max_depth}

    def place_rules(self, index) -> Optional[frozenset]:
        """Rule ids of the GLOBAL hierarchy domain(s) — what the walk may follow
        for a key that no declared domain governs."""
        global_domains = [d for d in self.sp.effective_domains if d.scope == "GLOBAL_ALL_PREDICATE_KEYS"
                          and not d.symmetric_equivalence]
        return index._rules_for(global_domains) if global_domains else frozenset()

    # --- quality (frozen pure function) ---------------------------------------
    def quality(self, answer_uri: str, p: str, d: str, o: str):
        key = (answer_uri, p, d, o)
        q = self._quality_cache.get(key)
        if q is None:
            q = assess_fact_quality(answer_uri=answer_uri, predicate_uri=p, direction=d,
                                    counterpart_uri=o, policy=self.qp)
            self._quality_cache[key] = q
        return q

    # --- rarity (offline pinned-KG count) ---------------------------------------
    def rarity(self, node_uri: str, raw_keys: Sequence[tuple[str, str]]) -> Optional[int]:
        """How many OTHER subjects/objects share (p, node) in the pinned KG.
        OUT group: subjects s with (s, p, node) = in-degree of node under p.
        IN group: objects x with (node, p, x) = out-degree of node under p.
        Ordering annotation only [ARCH-1 §18]; never a difficulty claim."""
        n = self._mi.node_index_or_none(node_uri, self.kg)
        if n is None:
            return None
        total = 0
        for p, d in raw_keys:
            pi = self._mi.node_index_or_none(p, self.kg)
            if pi is None:
                continue
            neigh = self.kg.in_neighbor.get(n, ()) if d == "OUT" else self.kg.out_neighbor.get(n, ())
            total += sum(1 for (pp, _x) in neigh if pp == pi)
        return total

    # --- the build ----------------------------------------------------------------
    def build(self, ref: ItemRef) -> dict:
        sel = load_item_selection(ref)
        answer_uri = sel["answer_uri"]
        answer_norm = normalize_uri(answer_uri)
        distractor_uris = [d["candidate_uri"] for d in sel["distractors"]]
        choices = [{"letter": "A", "uri": answer_uri, "norm": answer_norm, "position": None,
                    "rank": None, "score": None, "display": sel["display_label"]}]
        for i, d in enumerate(sel["distractors"]):
            choices.append({"letter": LETTERS[i + 1], "uri": d["candidate_uri"],
                            "norm": normalize_uri(d["candidate_uri"]), "position": d["position"],
                            "rank": d["lrolesim_rank"], "score": d["lrolesim_score"],
                            "display": display_label(d["candidate_uri"])})
        letter_of_uri = {c["uri"]: c["letter"] for c in choices}

        # 3.1 observed objects per choice per raw key (the frozen enumeration)
        observed: dict[str, dict] = {}
        for c in choices:
            observed[c["letter"]] = self._mi.candidate_objects_from_local_kg(c["uri"], local_kg=self.kg)

        # 3.2 the Answer's facts come from the frozen CSV (fact_index + levels)
        answer_rows = load_answer_fact_rows(ref)
        csv_identities = {(r["predicate_uri"], r["direction"], r["counterpart_uri"]) for r in answer_rows.values()}
        enum_identities = {(p, d, o) for (p, d), objs in observed["A"].items() for o in objs}
        enumeration_matches = (csv_identities == enum_identities)

        # 3.3 semantic index over every counterpart of the four choices
        sources = [o for letter in observed for objs in observed[letter].values() for o in objs]
        index, index_info = self.semantic_index_for(ref.slug, sources)
        canon = index.canonical
        option_canon = {canon(c["norm"]) for c in choices}
        class_norm = normalize_uri(sel["selected_class_uri"]) if sel["selected_class_uri"] else ""
        place_rules = self.place_rules(index)

        # per-(letter, family key) alias-unified observed objects, canonical
        fam_objects: dict[tuple[str, tuple[str, str]], tuple[str, ...]] = {}

        def objects_for(letter: str, raw_key: tuple[str, str]) -> tuple[str, ...]:
            k = (letter, raw_key)
            if k not in fam_objects:
                fam_objects[k] = observed_objects_for_key(observed[letter], raw_key, policy=DEFAULT_ALIAS_POLICY)
            return fam_objects[k]

        anc_cache: dict[str, frozenset] = {}

        def ancestors_of(uri: str) -> frozenset:
            a = anc_cache.get(uri)
            if a is None:
                a = frozenset(index.ancestors(uri, place_rules).keys()) if index.available else frozenset()
                anc_cache[uri] = a
            return a

        union_cache: dict[tuple[str, tuple[str, str]], tuple[frozenset, frozenset]] = {}

        def canon_and_ancestor_union(letter: str, raw_key: tuple[str, str]) -> tuple[frozenset, frozenset]:
            k = (letter, raw_key)
            v = union_cache.get(k)
            if v is None:
                objs = objects_for(letter, raw_key)
                canon_set = frozenset(canon(o) for o in objs)
                anc_union: set[str] = set()
                for o in canon_set:
                    anc_union |= ancestors_of(o)
                v = (canon_set, frozenset(anc_union))
                union_cache[k] = v
            return v

        def ground_by_rule(node: str, raw_key: tuple[str, str], letter: str) -> tuple[str, str, str]:
            """The ARCH-2 grounding rule = the frozen NOT_COVERED tests applied to a
            presentation pair, with the UNRESOLVED state and the risk axis.
            Mirrors `classify_fact_against_candidate` step by step:
              nothing observed        -> ABSENCE_ONLY          [RULE] L0 analogue, never falsity
              index unavailable       -> UNRESOLVED            [RULE] never downgraded to absence
              any supporting relation -> SHARED_BY_CONTAINMENT (exact/canonical -> SHARED)
              else                    -> ALTERNATIVE_OBSERVED with risk PRESENT / UNMODELLED / NONE
            Returns (grounding, risk, method)."""
            objs = objects_for(letter, raw_key)
            if not objs:
                return (G_ABS, R_NONE, "rule")
            if not index.available:
                return (G_UNRES, R_UNRES, "rule")
            declared = [d for d in self.sp.domains_for((normalize_uri(raw_key[0]), raw_key[1]))
                        if d.scope != "GLOBAL_ALL_PREDICATE_KEYS"]
            if declared:
                # declared, predicate-scoped domain: small object sets; call the frozen classifier per pair
                rels = [index.classify(node, o, raw_key).relation for o in objs]
                if any(r in IDENTITY_RELATIONS for r in rels):
                    return (G_SHARED, R_NONE, "classify")
                if any(r in SUPPORTING_RELATIONS for r in rels):
                    return (G_CONT, R_NONE, "classify")
                if any(r == C.RELATION_UNAVAILABLE for r in rels):
                    return (G_UNRES, R_UNRES, "classify")
                if any(r == C.RELATION_CLAIM_UNDER_CANDIDATE for r in rels):
                    return (G_ALT, R_PRESENT, "classify")
                if any(r == C.RELATION_HIERARCHY_NOT_MODELLED for r in rels):
                    return (G_ALT, R_UNMOD, "classify")
                return (G_ALT, R_NONE, "classify")
            canon_set, anc_union = canon_and_ancestor_union(letter, raw_key)
            if node in canon_set:
                return (G_SHARED, R_NONE, "setlogic")
            if node in anc_union:                      # some recorded value lies UNDER the node
                return (G_CONT, R_NONE, "setlogic")
            if ancestors_of(node) & canon_set:         # the node lies UNDER a recorded value
                return (G_ALT, R_PRESENT, "setlogic")
            return (G_ALT, R_NONE, "setlogic")

        # 3.4 edges
        edges: list[dict] = []
        answer_fact_by_identity = {(r["predicate_uri"], r["direction"], r["counterpart_uri"]): r
                                   for r in answer_rows.values()}
        eligible_mismatch = 0
        dl_cache: dict[str, bool] = {}

        def distractor_label_leak(o: str) -> bool:
            v = dl_cache.get(o)
            if v is None:
                v = any(detect_answer_leakage(du, o, self.qp).hard_leak for du in distractor_uris)
                dl_cache[o] = v
            return v

        for c in choices:
            letter = c["letter"]
            for (p, d), objs in observed[letter].items():
                for o in objs:
                    q = self.quality(answer_uri, p, d, o)
                    reasons = list(q.rejection_reasons)
                    fi = None
                    if letter == "A":
                        r = answer_fact_by_identity.get((p, d, o))
                        if r is not None:
                            fi = r["fact_index"]
                            if r["eligible"] != q.eligible:
                                eligible_mismatch += 1
                    edges.append({"letter": letter, "p": p, "d": d, "o": o, "fact_index": fi,
                                  "eligible": q.eligible, "reasons": reasons,
                                  "soft_leak": q.leakage.soft_leak,
                                  "verbalizable": q.verbalizable, "template_id": q.template_id,
                                  "tier": q.pedagogical_tier})

        # 3.5 grouping by (alias family, direction) and canonical node
        def family_key(p: str, d: str) -> tuple[str, str]:
            fam = DEFAULT_ALIAS_POLICY.family_for(p)
            return ((fam.canonical_slot if fam else p), d)

        groups: dict[tuple[tuple[str, str], str], dict] = {}
        for e in edges:
            k = (family_key(e["p"], e["d"]), canon(e["o"]))
            g = groups.setdefault(k, {"key": k[0], "node": k[1], "edges": [], "raw_keys": set(),
                                      "raw_counterparts": set(), "letters": set()})
            g["edges"].append(e)
            g["raw_keys"].add((e["p"], e["d"]))
            g["raw_counterparts"].add(e["o"])
            g["letters"].add(e["letter"])

        # R* bookkeeping
        rstar = sel["rstar"]
        rstar_identities = {(r["predicate_uri"], r["direction"], r["counterpart_uri"]) for r in rstar.values()}
        rstar_family_keys = {family_key(r["predicate_uri"], r["direction"]) for r in rstar.values()}
        # ALT(d): distractor letters that an R* fact covers at L1, per family key
        alt_letters_by_key: dict[tuple[str, str], set[str]] = defaultdict(set)
        absence_incidences = 0
        explanation_basis: dict[str, list[int]] = {L: [] for L in LETTERS[1:]}
        for r in rstar.values():
            fk = family_key(r["predicate_uri"], r["direction"])
            for du, lv in r["levels"].items():
                L = letter_of_uri[du]
                if lv == "L1" or lv == "L2":
                    alt_letters_by_key[fk].add(L)
                    explanation_basis[L].append(r["fact_index"])
                elif lv == "L0":
                    absence_incidences += 1

        agree = Counter()
        out_groups: list[dict] = []
        for (fk, node), g in groups.items():
            letters = g["letters"]
            support = "".join(L for L in LETTERS if L in letters)
            raw_keys = sorted(g["raw_keys"])
            answer_edges = [e for e in g["edges"] if e["letter"] == "A"]
            is_mand = any(((e["p"], e["d"], e["o"]) in rstar_identities) for e in answer_edges)
            # --- grounding of every non-support letter ------------------------------
            grounding: dict[str, list] = {}
            for L in LETTERS:
                if L in letters:
                    continue
                rule_g = ground_by_rule(node, raw_keys[0], L)
                if answer_edges and L != "A":
                    # [RULE] Answer-owned group vs a distractor: the FROZEN level decides; copied, not recomputed.
                    du = next(c["uri"] for c in choices if c["letter"] == L)
                    levels = []
                    for e in answer_edges:
                        r = answer_rows.get(e["fact_index"]) if e["fact_index"] is not None else None
                        if r is not None and du in r["per_candidate"]:
                            levels.append(r["per_candidate"][du])
                    if levels:
                        lv = max(levels, key=lambda t: mcq_core.LEVEL_STRENGTH[t[0]] if t[0] != "NOT_COVERED" else 9)
                        if any(t[0] == "NOT_COVERED" for t in levels):
                            frozen = (G_CONT, R_NONE)          # supports without owning an edge to this node
                        elif any(t[0] in ("L1", "L2") for t in levels):
                            worst = max((t[2] for t in levels if t[0] in ("L1", "L2")),
                                        key=lambda s: RISK_ORDER.get(s, 0))
                            frozen = (G_ALT, worst)
                        else:
                            frozen = (G_ABS, R_NONE)
                        agree["pairs"] += 1
                        agree["grounding_equal"] += int(frozen[0] == rule_g[0])
                        agree["risk_equal"] += int(frozen[1] == rule_g[1])
                        grounding[L] = [frozen[0], frozen[1], "frozen_level", rule_g[0], rule_g[1]]
                        continue
                grounding[L] = [rule_g[0], rule_g[1], rule_g[2], rule_g[0], rule_g[1]]
            # --- screens (group level) -----------------------------------------------
            reasons: set[str] = set()
            for e in g["edges"]:
                for rr in e["reasons"]:
                    reasons.add(f"EXCLUDED_INELIGIBLE_{rr}")
                if canon(e["o"]) == canon(next(c["norm"] for c in choices if c["letter"] == e["letter"])):
                    reasons.add("EXCLUDED_SELF_LOOP")
            if node in option_canon:
                reasons.add("EXCLUDED_OPTION_REFERENCE")
            if class_norm and node == canon(class_norm):
                reasons.add("EXCLUDED_DUPLICATES_CLASS_NODE")
            verbalizable = all(self.qp.template_for(p, d) is not None for (p, d) in raw_keys)
            dl = distractor_label_leak(node) or any(distractor_label_leak(o) for o in g["raw_counterparts"])
            pre_screens = []
            if not verbalizable:
                pre_screens.append("PRE_EXCLUDED_UNVERBALIZABLE")
            if dl:
                pre_screens.append("PRE_EXCLUDED_DISTRACTOR_LABEL_LEAK")
            # --- tier ---------------------------------------------------------------------
            alt_for = "".join(L for L in LETTERS[1:] if L in letters and L in alt_letters_by_key.get(fk, set()))
            if is_mand:
                tier = T_MAND
            elif reasons:
                tier = T_EXCL
            elif alt_for:
                tier = T_ALT
            else:
                tier = T_OPT
            # --- attributes ------------------------------------------------------------------
            s = len(letters)
            gvals = [v[0] for v in grounding.values()]
            rvals = [v[1] for v in grounding.values()]
            attrs = {
                "s": s, "a": int(letters == {"A"}), "n": int(s == 1),
                "t": min(self.qp.tier_for(p, d) for (p, d) in raw_keys),
                "verb": int(verbalizable), "len": len(display_label(node)),
                "tok": len(leakage_tokens(node, minimum_length=1)),
                "abs": gvals.count(G_ABS), "alt": gvals.count(G_ALT), "cont": gvals.count(G_CONT),
                "unres": gvals.count(G_UNRES), "shared_ident": gvals.count(G_SHARED),
                "risk_present": rvals.count(R_PRESENT), "risk_unmod": rvals.count(R_UNMOD),
                "risk_unres": rvals.count(R_UNRES),
                "soft": int(any(e["soft_leak"] for e in g["edges"])), "dl": int(dl),
                "rare": self.rarity(node, raw_keys), "excl_answer": int("A" not in letters),
            }
            out_groups.append({
                "key": list(fk), "raw_keys": [list(k) for k in raw_keys], "node": node,
                "node_label": display_label(node), "support": support, "tier": tier,
                "alt_for": alt_for, "alt_shared_with_answer": int(bool(alt_for) and "A" in letters),
                "excluded_reasons": sorted(reasons), "pre_screens": pre_screens,
                "grounding": grounding, "attrs": attrs,
                "answer_fact_indices": sorted(e["fact_index"] for e in answer_edges if e["fact_index"] is not None),
                "is_rstar": int(is_mand),
                "edges": [[e["letter"], e["p"], e["d"], e["o"]] for e in g["edges"]],
            })

        # 3.6 canonical order [ARCH-1 §13.1] and group ids
        tier_rank = {T_MAND: 0, T_ALT: 1, T_OPT: 2, T_EXCL: 3}
        out_groups.sort(key=lambda g: (tier_rank[g["tier"]], -g["attrs"]["s"], g["attrs"]["t"],
                                       1 - g["attrs"]["verb"], g["attrs"]["abs"], g["attrs"]["a"],
                                       g["attrs"]["n"], g["attrs"]["tok"], g["attrs"]["len"],
                                       g["key"][0], g["key"][1], g["node"]))
        for i, g in enumerate(out_groups):
            g["gid"] = f"g{i:05d}"

        counts = Counter(g["tier"] for g in out_groups)
        rstar_out = []
        for r in sorted(rstar.values(), key=lambda r: r["fact_index"]):
            rstar_out.append({
                "fact_index": r["fact_index"], "predicate_uri": r["predicate_uri"], "direction": r["direction"],
                "counterpart_uri": r["counterpart_uri"], "family_key": list(family_key(r["predicate_uri"], r["direction"])),
                "node": canon(r["counterpart_uri"]), "verbalizable": r["verbalizable"],
                "template_id": r["template_id"], "pedagogical_tier": r["pedagogical_tier"],
                "levels": {letter_of_uri[du]: lv for du, lv in r["levels"].items()},
                "risks": {letter_of_uri[du]: rk for du, rk in r["risks"].items()},
            })
        return {
            "schema_version": "b3_audit_universe/1.0.0-development-only",
            "item": {"key": item_key(ref), "slug": ref.slug, "batch": ref.batch, "answer_uri": answer_uri,
                     "display_label": sel["display_label"], "cohort": ref.cohort,
                     "cohort_group": ref.cohort_group, "evidence_policy": sel["evidence_policy"],
                     "mcq_evidence_level": sel["mcq_evidence_level"], "search_scope": sel["search_scope"],
                     "minimum_rationale_size": sel["minimum_rationale_size"],
                     "direct_identifier_flag": sel["direct_identifier_flag"],
                     "option_reference_conflict_count": sel["option_reference_conflict_count"],
                     "rationale_objective": sel["rationale_objective"],
                     "granularity_risk_incidences": ref.granularity_risk_incidences,
                     "m1_node_count": ref.m1_node_count},
            "choices": choices,
            "class": {"uri": sel["selected_class_uri"],
                      "label": display_label(sel["selected_class_uri"]).replace("Category:", "") if sel["selected_class_uri"] else ""},
            "rationale": {"facts": rstar_out, "absence_incidences": absence_incidences,
                          "explanation_basis": explanation_basis,
                          "fully_verbalizable": all(r["verbalizable"] for r in rstar.values()),
                          "family_keys": [list(k) for k in sorted(rstar_family_keys)]},
            "index": index_info,
            "groups": out_groups,
            "validation": {"answer_enumeration_matches_csv": enumeration_matches,
                           "eligible_mismatch_count": eligible_mismatch,
                           "frozen_vs_rule": dict(agree)},
            "counts": {"edges": len(edges), "groups": len(out_groups), **{f"tier_{k}": v for k, v in counts.items()},
                       "nodes": len({g["node"] for g in out_groups})},
        }


def stage_universe(args, refs: list[ItemRef], out_dir: Path) -> None:
    from kg.loader import load_local_kg
    gated = [r for r in refs if r.gate_passed]
    todo = [r for r in gated if not (out_dir / "universe" / f"{item_key(r)}.json.gz").is_file()]
    say(f"[universe] {len(gated)} gated items, {len(todo)} to build")
    if not todo:
        return
    say("[universe] loading the pinned KG (SHA-256 verified) ...")
    t0 = time.time()
    kg = load_local_kg(PINNED_KG_PATH, verify_sha256=PINNED_KG_SHA256)
    say(f"[universe] KG loaded in {time.time() - t0:.1f}s")
    qp = load_quality_policy(PREDICATE_POLICY_PATH)
    sp = load_semantic_relation_policy(SEMANTIC_POLICY_PATH)
    builder = UniverseBuilder(out_dir, local_kg=kg, quality_policy=qp, semantic_policy=sp)
    for i, ref in enumerate(todo, 1):
        t1 = time.time()
        try:
            uni = builder.build(ref)
            write_json(out_dir / "universe" / f"{item_key(ref)}.json.gz", uni, gz=True)
            say(f"  [{i}/{len(todo)}] {ref.slug}: {uni['counts']['groups']} groups, "
                f"{uni['counts'].get('tier_OPTIONAL_CONTEXT', 0)} optional, {time.time() - t1:.1f}s")
        except Exception as exc:                                    # noqa: BLE001
            write_json(out_dir / "universe" / f"{item_key(ref)}.FAILED.json",
                       {"item": item_key(ref), "error": repr(exc)})
            say(f"  [{i}/{len(todo)}] {ref.slug}: FAILED {exc!r}")


# ==========================================================================
# 4) H5 — kernel replay and the counterfactual require-verbalizable audit
# ==========================================================================

class CallTimeout(Exception):
    """Raised when one exact kernel call exceeds its declared time budget."""


def with_time_budget(seconds: int, fn: Callable[[], Any]) -> tuple[bool, Any]:
    """Run `fn()` under a SIGALRM budget. Returns (completed, result_or_None).

    The H5 counterfactual calls the frozen kernel's exact rationale enumeration
    over every feasible triple; for a polity with hundreds of eligible facts and
    |R*| = 3 that enumeration is combinatorially out of reach. A budget makes
    the audit finish and turns "not computable here" into a recorded outcome,
    never into a silent approximation.
    """
    def _handler(signum, frame):
        raise CallTimeout()
    previous = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        return True, fn()
    except CallTimeout:
        return False, None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def kernel_case_from_artifacts(ref: ItemRef, qp) -> tuple[Any, dict]:
    """Rebuild the AnswerCase from the frozen artefacts through `build_case()`.

    Quality is recomputed by the frozen pure function (same policy file; verified
    against the CSV's eligibility verdict); levels/bases/risks are COPIED from
    the CSV. Nothing is re-decided.  [RULE]
    """
    sel = load_item_selection(ref)
    rows = load_answer_fact_rows(ref)
    roster = load_ranking(ref)
    facts = []
    mismatch = 0
    incomplete = 0
    for fi in sorted(rows):
        r = rows[fi]
        q = assess_fact_quality(answer_uri=sel["answer_uri"], predicate_uri=r["predicate_uri"],
                                direction=r["direction"], counterpart_uri=r["counterpart_uri"], policy=qp)
        if q.eligible != r["eligible"]:
            mismatch += 1
        levels, bases, risks = [], [], []
        for cand in roster:
            t = r["per_candidate"].get(cand.uri)
            if t is None:
                incomplete += 1
                t = ("L0", "NONE", "NONE")
            levels.append(t[0]); bases.append(t[1]); risks.append(t[2])
        facts.append(AnswerFact(
            quality=KernelFactQuality(
                predicate_uri=q.predicate_uri, direction=q.direction, counterpart_uri=q.counterpart_uri,
                display_label=q.display_label, eligible=r["eligible"], soft_leak=q.leakage.soft_leak,
                verbalizable=q.verbalizable, pedagogical_tier=q.pedagogical_tier,
                label_length=q.label_length, token_count=q.token_count, template_id=q.template_id),
            levels=tuple(levels), exclusion_bases=tuple(bases), granularity_risks=tuple(risks)))
    case = build_case(sel["answer_uri"], sel["display_label"], roster, facts)
    return case, {"selection": sel, "eligible_mismatch": mismatch, "incomplete_pairs": incomplete}


def h5_audit_item(ref: ItemRef, qp) -> dict:
    case, info = kernel_case_from_artifacts(ref, qp)
    sel = info["selection"]
    rec: dict[str, Any] = {"item": item_key(ref), "slug": ref.slug, "batch": ref.batch, "cohort": ref.cohort,
                           "cohort_group": ref.cohort_group, "answer_uri": sel["answer_uri"],
                           "eligible_mismatch": info["eligible_mismatch"],
                           "incomplete_pairs": info["incomplete_pairs"]}
    # --- (i) the primary yield numbers come straight from the frozen artefacts ---------
    # (no kernel call is needed to know whether the recorded R* has a template for every fact)
    recorded_d = tuple(d["candidate_uri"] for d in sel["distractors"])
    recorded_r = tuple(sorted((r["predicate_uri"], r["direction"], r["counterpart_uri"]) for r in sel["rstar"].values()))
    art_unverb = sorted({(r["predicate_uri"], r["direction"]) for r in sel["rstar"].values() if not r["verbalizable"]})
    rec.update({
        "rstar_size": len(sel["rstar"]), "evidence_policy": sel["evidence_policy"],
        "rstar_fully_verbalizable": all(r["verbalizable"] for r in sel["rstar"].values()),
        "rstar_unverbalizable_count": sum(1 for r in sel["rstar"].values() if not r["verbalizable"]),
        "unverbalizable_keys": ";".join(f"{p.rsplit('/', 1)[-1]}/{d}" for p, d in art_unverb),
        "unverbalizable_keys_full": [list(k) for k in art_unverb],
        "distractor_ranks": ";".join(str(d["lrolesim_rank"]) for d in sel["distractors"]),
    })
    # --- (ii) kernel replay, BUDGETED: the frozen kernel must reproduce the recorded selection ---
    done, base = with_time_budget(H5_KERNEL_TIME_BUDGET_S,
                                  lambda: select_distractors(case, objective=RATIONALE_OBJECTIVE_V3))
    if not done:
        rec.update({"kernel_replay_match": None,
                    "kernel_replay_note": f"KERNEL_REPLAY_NOT_COMPUTED_TIMEOUT_{H5_KERNEL_TIME_BUDGET_S}S",
                    "same_triple_min_rationales": None, "same_triple_fully_verbalizable_rationales": None,
                    "same_triple_note": "NOT_COMPUTED_KERNEL_TIMEOUT",
                    "counterfactual": ("BASELINE_ALREADY_VERBALIZABLE" if rec["rstar_fully_verbalizable"]
                                       else f"COUNTERFACTUAL_NOT_COMPUTED_KERNEL_TIMEOUT_{H5_KERNEL_TIME_BUDGET_S}S")})
        return rec
    if base is None:
        rec.update({"kernel_replay_match": False, "kernel_replay_note": "kernel returned None"})
        return rec
    replay_d = tuple(d.uri for d in base.distractors)
    replay_r = tuple(sorted(base.rationale.fact_identities))
    rec["kernel_replay_match"] = (replay_d == recorded_d and replay_r == recorded_r
                                  and base.evidence_policy == sel["evidence_policy"])
    rec["kernel_replay_note"] = "" if rec["kernel_replay_match"] else \
        f"distractors {replay_d != recorded_d} rationale {replay_r != recorded_r} policy {base.evidence_policy}"
    # --- the selected R* as the kernel sees it (cross-check of the artefact flags) ---
    r_quals = [case.facts[i].quality for i in base.rationale.fact_indices]
    rec["kernel_rstar_fully_verbalizable"] = base.rationale.unverbalizable_fact_count == 0
    rec["artefact_vs_kernel_verbalizable_agree"] = (rec["kernel_rstar_fully_verbalizable"] == rec["rstar_fully_verbalizable"])
    # --- (ii) another min-cardinality rationale for the SAME triple? ---
    done, ranked = with_time_budget(
        H5_CALL_TIME_BUDGET_S,
        lambda: rank_minimum_rationales(case, base.positions, base.evidence_policy, RATIONALE_OBJECTIVE_V3))
    if not done:
        rec.update({"same_triple_min_rationales": None, "same_triple_fully_verbalizable_rationales": None,
                    "same_triple_note": f"TIMEOUT_{H5_CALL_TIME_BUDGET_S}S"})
    else:
        n_min = len(ranked[2]) if ranked else 0
        n_verb = sum(1 for r in ranked[2] if r.unverbalizable_fact_count == 0) if ranked else 0
        rec.update({"same_triple_min_rationales": n_min, "same_triple_fully_verbalizable_rationales": n_verb,
                    "same_triple_note": ""})
    # --- (iii) the counterfactual policy over the whole search scope ---
    # [RULE] select_with_rationale_filter never grows |R*| for a triple (cardinality is
    # fixed by the exact set cover before key 4 is read). It walks the evidence policies
    # in order; a result at a WEAKER policy than the baseline is NOT accepted here.
    if rec["rstar_fully_verbalizable"]:
        rec.update({"counterfactual": "BASELINE_ALREADY_VERBALIZABLE", "alt_distractors_changed": False,
                    "alt_rationale_changed": False, "alt_rstar_size": len(r_quals), "alt_rstar_grew": False,
                    "alt_evidence_policy": base.evidence_policy, "alt_distractor_ranks": rec["distractor_ranks"]})
        return rec
    done, alt = with_time_budget(
        H5_CALL_TIME_BUDGET_S,
        lambda: select_with_rationale_filter(
            case, objective=RATIONALE_OBJECTIVE_V3,
            admissible=lambda _c, _p, r: r.unverbalizable_fact_count == 0))
    if not done:
        rec.update({"counterfactual": f"COUNTERFACTUAL_NOT_COMPUTED_TIMEOUT_{H5_CALL_TIME_BUDGET_S}S",
                    "alt_distractors_changed": None, "alt_rationale_changed": None, "alt_rstar_size": None,
                    "alt_rstar_grew": None, "alt_evidence_policy": None, "alt_distractor_ranks": ""})
        return rec
    if alt is None or mcq_core.LEVEL_STRENGTH[mcq_core.POLICY_THRESHOLD[alt.evidence_policy]] < \
            mcq_core.LEVEL_STRENGTH[mcq_core.POLICY_THRESHOLD[base.evidence_policy]]:
        rec.update({"counterfactual": "NO_FULLY_VERBALIZABLE_MIN_CARD_SOLUTION_AT_SAME_POLICY",
                    "alt_distractors_changed": None, "alt_rationale_changed": None, "alt_rstar_size": None,
                    "alt_rstar_grew": None,
                    "alt_evidence_policy": (alt.evidence_policy if alt is not None else None),
                    "alt_distractor_ranks": ""})
        return rec
    d_changed = tuple(d.uri for d in alt.distractors) != replay_d
    rec.update({
        "counterfactual": "ALTERNATIVE_DISTRACTORS_CHANGE" if d_changed else "ALTERNATIVE_RATIONALE_ONLY",
        "alt_distractors_changed": d_changed,
        "alt_rationale_changed": tuple(sorted(alt.rationale.fact_identities)) != replay_r,
        "alt_rstar_size": len(alt.rationale.fact_indices),
        "alt_rstar_grew": len(alt.rationale.fact_indices) > len(r_quals),
        "alt_evidence_policy": alt.evidence_policy,
        "alt_distractor_ranks": ";".join(str(d.rank) for d in alt.distractors),
        "alt_rank_sum_delta": alt.candidate_rank_sum - base.candidate_rank_sum,
        "alt_l1_incidences_delta": alt.rationale.l1_incidences - base.rationale.l1_incidences,
        "alt_granularity_risk_incidences": alt.rationale.granularity_risk_incidences,
    })
    return rec


def h5_audit_item_safe(ref: ItemRef) -> dict:
    """Worker entry: loads the (cheap) quality policy itself; never raises."""
    try:
        return h5_audit_item(ref, load_quality_policy(PREDICATE_POLICY_PATH))
    except Exception as exc:                                        # noqa: BLE001
        return {"item": item_key(ref), "slug": ref.slug, "batch": ref.batch, "cohort": ref.cohort,
                "cohort_group": ref.cohort_group, "kernel_replay_match": False,
                "kernel_replay_note": f"ERROR {exc!r}"}


def stage_h5(args, refs: list[ItemRef], out_dir: Path) -> None:
    gated = [r for r in refs if r.gate_passed]
    rows = []
    say(f"[h5] auditing {len(gated)} gated items (kernel replay + counterfactual) with {args.workers} workers")
    t0 = time.time()
    if args.workers <= 1:
        for i, ref in enumerate(gated, 1):
            rows.append(h5_audit_item_safe(ref))
            if i % 25 == 0:
                say(f"  [h5] {i}/{len(gated)}")
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(h5_audit_item_safe, ref): ref for ref in gated}
            for i, fut in enumerate(as_completed(futures), 1):
                rows.append(fut.result())
                if i % 25 == 0:
                    say(f"  [h5] {i}/{len(gated)} ({time.time() - t0:.0f}s)")
    rows.sort(key=lambda r: r["item"])
    write_json(out_dir / "h5_verbalizability_audit.json", rows)
    flat = [{k: (";".join(map(str, v)) if isinstance(v, list) else v) for k, v in r.items()} for r in rows]
    write_csv(out_dir / "h5_verbalizability_audit.csv", flat)
    say(f"[h5] wrote {len(rows)} rows")


# ==========================================================================
# 5) THE EXACT 0-1 MODEL — scipy.optimize.milp (HiGHS), lexicographic, verified
# ==========================================================================

SOLVER_CALLS: list[dict] = []          # per-process instrumentation for H6


class Milp:
    """A tiny 0-1 model wrapper over scipy.optimize.milp (HiGHS).

    Variables are created in a DETERMINISTIC order (the caller's canonical
    group order first), rows are appended in a deterministic order, and every
    solve records (n_vars, n_rows, status, seconds) for the H6 evidence. The
    relative MIP gap is 0 so a returned status 0 is an optimality certificate
    within HiGHS's floating-point tolerances; the pure-Python re-check below is
    what turns that into an exact integer statement.
    """

    STATUS = {0: "OPTIMAL", 1: "ITERATION_OR_TIME_LIMIT", 2: "INFEASIBLE", 3: "UNBOUNDED", 4: "OTHER"}

    def __init__(self, tag: str):
        self.tag = tag
        self.lb: list[float] = []
        self.ub: list[float] = []
        self.rows: list[tuple[dict[int, float], float, float]] = []

    def var(self, lo: float = 0.0, hi: float = 1.0) -> int:
        self.lb.append(lo)
        self.ub.append(hi)
        return len(self.lb) - 1

    def fix(self, v: int, value: float) -> None:
        self.lb[v] = value
        self.ub[v] = value

    def row(self, coefs: Mapping[int, float], lo: float, hi: float) -> None:
        if coefs:
            self.rows.append((dict(coefs), lo, hi))

    def solve(self, objective: Mapping[int, float]) -> tuple[int, Optional[np.ndarray], Optional[float]]:
        n = len(self.lb)
        c = np.zeros(n)
        for v, coef in objective.items():
            c[v] = coef
        constraints = []
        if self.rows:
            data, ri, ci, lo, hi = [], [], [], [], []
            for r, (coefs, l, h) in enumerate(self.rows):
                for v, coef in coefs.items():
                    data.append(coef); ri.append(r); ci.append(v)
                lo.append(l); hi.append(h)
            A = csr_matrix((data, (ri, ci)), shape=(len(self.rows), n))
            constraints.append(LinearConstraint(A, np.array(lo), np.array(hi)))
        t0 = time.perf_counter()
        res = milp(c, constraints=constraints, integrality=np.ones(n), bounds=Bounds(np.array(self.lb), np.array(self.ub)),
                   options={"mip_rel_gap": 0.0, "disp": False, "presolve": True, "time_limit": MILP_TIME_LIMIT})
        dt = time.perf_counter() - t0
        SOLVER_CALLS.append({"tag": self.tag, "n_vars": n, "n_rows": len(self.rows), "status": int(res.status),
                             "status_name": self.STATUS.get(int(res.status), "?"), "seconds": dt})
        if res.status != 0 or res.x is None:
            return int(res.status), None, None
        x = np.rint(res.x)
        return 0, x, float(res.fun)


def lexicographic_solve(model: Milp, keys: Sequence[Mapping[int, float]], canonical_vars: Sequence[int]
                        ) -> tuple[str, Optional[np.ndarray], list[int]]:
    """Minimise key 1; fix it; minimise key 2; ...; then the canonical tie fix.

    [ARCH-2 §5] ε-lexicographic with every ε = 0. Each level appends one
    equality row `key_i(x) == opt_i`. After the last key the remaining ties are
    broken by the canonical group order: the lexicographically LARGEST 0/1
    vector over `canonical_vars` (a group earlier in canonical order is taken
    whenever an optimal selection containing it exists — ARCH-1 §13.3), solved
    block-wise with exactly representable powers of two so each block needs
    one solve instead of one solve per variable.
    """
    values: list[int] = []
    x = None
    for coefs in keys:
        status, x, fun = model.solve(coefs)
        if status != 0:
            return (Milp.STATUS.get(status, "?"), None, values)
        val = int(round(fun))
        values.append(val)
        model.row(coefs, val, val)
    for start in range(0, len(canonical_vars), CANONICAL_BLOCK):
        block = list(canonical_vars[start:start + CANONICAL_BLOCK])
        obj = {v: -float(2 ** (len(block) - 1 - j)) for j, v in enumerate(block)}
        status, x, _ = model.solve(obj)
        if status != 0:
            return (Milp.STATUS.get(status, "?"), None, values)
        for v in block:
            model.fix(v, float(int(x[v])))
    if x is None:                                     # no keys and no canonical vars
        status, x, _ = model.solve({})
        if status != 0:
            return (Milp.STATUS.get(status, "?"), None, values)
    return ("OPTIMAL", x, values)


# ==========================================================================
# 6) UNIVERSE VIEWS: arms, bounding, the two selection problems
# ==========================================================================

@dataclass
class Prepared:
    """One item's universe re-indexed for the selection problems."""
    uni: dict
    groups: dict[str, dict]
    mandatory: list[str]
    mandatory_nodes: frozenset
    mandatory_keys: frozenset
    mandatory_letters: frozenset
    alt_showable: list[str]
    alt_by_letter: dict[str, list[str]]
    alt_unshowable_letters: list[str]
    optional: list[str]                      # tier OPTIONAL_CONTEXT, canonical order


def prepare(uni: dict) -> Prepared:
    groups = {g["gid"]: g for g in uni["groups"]}
    mandatory = [g["gid"] for g in uni["groups"] if g["tier"] == T_MAND]
    alt_showable = [g["gid"] for g in uni["groups"] if g["tier"] == T_ALT]
    alt_by_letter: dict[str, list[str]] = {L: [] for L in LETTERS[1:]}
    for gid in alt_showable:
        for L in groups[gid]["alt_for"]:
            alt_by_letter[L].append(gid)
    # letters that an R* fact covers at L1 but whose observed alternatives were all screened out
    needed = set()
    for f in uni["rationale"]["facts"]:
        for L, lv in f["levels"].items():
            if lv in ("L1", "L2"):
                needed.add(L)
    unshowable = sorted(L for L in needed if not alt_by_letter.get(L))
    return Prepared(
        uni=uni, groups=groups, mandatory=mandatory,
        mandatory_nodes=frozenset(groups[g]["node"] for g in mandatory),
        mandatory_keys=frozenset(tuple(groups[g]["key"]) for g in mandatory),
        mandatory_letters=frozenset(L for g in mandatory for L in groups[g]["support"]),
        alt_showable=alt_showable, alt_by_letter=alt_by_letter, alt_unshowable_letters=unshowable,
        optional=[g["gid"] for g in uni["groups"] if g["tier"] == T_OPT])


ARMS = ("A_arch1_penalty", "B_arch2_hard", "B_tolerate_unmodelled", "C_no_A_excluding_support3", "C2_no_A_excluding_any")


def arm_admissible(arm: str, g: dict) -> tuple[bool, list[str]]:
    """Pre-answer admissibility of one OPTIONAL group under an arm.

    Returns (admissible, reasons_failed). Reasons are evaluated in a fixed order
    and ALL failing reasons are returned so exclusion causes can be counted.
    [ARCH-1] Arm A: penalty-style — only the ARCH-1 screens (eligible, verbalizable, K_A = 0).
    [ARCH-2] Arm B: grounding-clean hard rule (review C3 / memo H14).
    Arm C: B plus "no A-excluding support-3 group" (memo H14 stricter option).
    """
    a = g["attrs"]
    failed: list[str] = []
    if a["verb"] == 0:
        failed.append("UNVERBALIZABLE")
    if a["a"] == 1:
        failed.append("ANSWER_ONLY_K_A_0")
    if arm == "A_arch1_penalty":
        return (not failed, failed)
    if a["s"] < 2:
        failed.append("SUPPORT_BELOW_2")
    if a["abs"] > 0:
        failed.append("ABSENCE_ONLY_LETTER")
    if a["cont"] > 0:
        failed.append("SHARED_BY_CONTAINMENT_LETTER")
    if a["unres"] > 0:
        failed.append("UNRESOLVED_INDEX_LETTER")
    if a["risk_present"] > 0:
        failed.append("GRANULARITY_RISK_CLAIM_UNDER_CANDIDATE")
    if a["risk_unres"] > 0:
        failed.append("GRANULARITY_RISK_UNRESOLVED")
    if a["risk_unmod"] > 0 and arm != "B_tolerate_unmodelled":
        failed.append("GRANULARITY_RISK_HIERARCHY_UNMODELLED")
    if a["dl"] == 1:
        failed.append("DISTRACTOR_LABEL_LEAK")
    if arm == "C_no_A_excluding_support3" and a["s"] == 3 and a["excl_answer"] == 1:
        failed.append("A_EXCLUDING_SUPPORT_3")
    if arm == "C2_no_A_excluding_any" and a["excl_answer"] == 1:
        failed.append("A_EXCLUDING_ANY_SUPPORT")
    return (not failed, failed)


def prekey(g: dict) -> tuple:
    """[ARCH-1 §5.4] the modular bounding pre-key: (-support, tier, unverbalizable,
    rarity (rarer first; None last), label length, canonical identity)."""
    a = g["attrs"]
    rare = a["rare"] if a["rare"] is not None else 10 ** 9
    return (-a["s"], a["t"], 1 - a["verb"], rare, a["len"], g["key"][0], g["key"][1], g["node"])


def bound_optional(prep: Prepared, n_max: Optional[int], method: str) -> tuple[list[str], dict]:
    """Bound the OPTIONAL_CONTEXT tier to about n_max groups.

    method = "modular":    the ARCH-1 pre-key, truncated.
    method = "stratified": [ARCH-2 §9.3] first KEEP (i) every optional group whose
             right node is already used by a mandatory or showable alternative
             group (it costs no extra node), (ii) the top STRATA_K_KEY groups of
             every distinct predicate-direction family, (iii) the top
             STRATA_K_LETTER groups containing each distractor letter; then fill
             by the pre-key up to n_max. The kept strata are never cut, so the
             bounded size may exceed n_max; the record says so.
    Bounding touches OPTIONAL_CONTEXT only: mandatory and alternative tiers are
    always complete, so answerability and grounding never depend on it.
    """
    opt = sorted(prep.optional, key=lambda gid: prekey(prep.groups[gid]))
    info = {"method": method, "n_max": n_max, "optional_total": len(opt)}
    if n_max is None or len(opt) <= n_max:
        info.update({"scope": "UNIVERSE_FULL", "bounded_size": len(opt), "kept_strata": 0})
        return opt, info
    if method == "modular":
        kept = opt[:n_max]
        info.update({"scope": "UNIVERSE_BOUNDED", "bounded_size": len(kept), "kept_strata": 0})
        return kept, info
    used_nodes = set(prep.mandatory_nodes) | {prep.groups[g]["node"] for g in prep.alt_showable}
    keep: list[str] = []
    seen = set()

    def add(gid: str) -> None:
        if gid not in seen:
            seen.add(gid); keep.append(gid)

    for gid in opt:
        if prep.groups[gid]["node"] in used_nodes:
            add(gid)
    per_key: dict[tuple, int] = Counter()
    for gid in opt:
        k = tuple(prep.groups[gid]["key"])
        if per_key[k] < STRATA_K_KEY:
            per_key[k] += 1; add(gid)
    per_letter: dict[str, int] = Counter()
    for gid in opt:
        for L in prep.groups[gid]["support"]:
            if L != "A" and per_letter[L] < STRATA_K_LETTER:
                per_letter[L] += 1; add(gid)
    strata = len(keep)
    for gid in opt:
        if len(keep) >= n_max:
            break
        add(gid)
    kept_sorted = [gid for gid in opt if gid in seen]
    info.update({"scope": "UNIVERSE_BOUNDED", "bounded_size": len(kept_sorted), "kept_strata": strata})
    return kept_sorted, info


# --- key vectors in pure Python (used for verification and the oracle) ------------------

def pre_key_vector(prep: Prepared, selected: Sequence[str]) -> list[int]:
    gs = [prep.groups[g] for g in selected]
    covered = set(prep.mandatory_letters)
    for g in gs:
        covered.update(g["support"])
    keys = {tuple(g["key"]) for g in gs} - prep.mandatory_keys
    return [len([L for L in LETTERS if L not in covered]),
            -sum(g["attrs"]["s"] - 1 for g in gs),
            -len(keys),
            len(gs),
            sum(g["attrs"]["t"] for g in gs),
            sum(g["attrs"]["tok"] for g in gs)]


def risk_flag(g: dict) -> int:
    a = g["attrs"]
    return int(a["risk_present"] + a["risk_unmod"] + a["risk_unres"] > 0)


def post_key_vector(prep: Prepared, selected_free: Sequence[str]) -> list[int]:
    gs = [prep.groups[g] for g in selected_free]
    keys = {tuple(g["key"]) for g in gs} - prep.mandatory_keys
    nodes = {g["node"] for g in gs} - prep.mandatory_nodes
    return [sum(g["attrs"]["abs"] for g in gs),
            sum(risk_flag(g) for g in gs),
            -sum(g["attrs"]["s"] - 1 for g in gs),
            -len(keys),
            len(nodes),
            sum(g["attrs"]["t"] for g in gs),
            sum(g["attrs"]["tok"] for g in gs)]


def canonical_max(cands: list[list[str]], order: Sequence[str]) -> list[str]:
    """Among tied selections, the canonical-order-maximal one (lexicographically
    largest 0/1 vector over `order`)."""
    pos = {g: i for i, g in enumerate(order)}
    best = None
    best_vec = None
    for s in cands:
        vec = [0] * len(order)
        for g in s:
            vec[pos[g]] = 1
        if best_vec is None or vec > best_vec:
            best, best_vec = s, vec
    return best


# --- the PRE-answer problem --------------------------------------------------------------

def solve_pre(prep: Prepared, admissible: Sequence[str], b_pre: int, key_order: Sequence[int],
              objective: str = "lexicographic", tag: str = "pre") -> dict:
    """Choose optional clue groups before answering.

    `admissible` = the arm's admissible optional groups (canonical order).
    Hard: at most b_pre optional groups; K_A = 0 is already inside admissibility.
    Keys (default order = ARCH-2 candidate; `key_order` permutes them):
      0 uncovered letters, 1 -shared information, 2 -distinct keys, 3 clue groups,
      4 tier sum, 5 token sum; then the canonical fix.
    objective = "arch1_weighted": the ARCH-1 §6.3 weighted utility instead (comparator).
    """
    rec: dict[str, Any] = {"b_pre": b_pre, "objective": objective, "key_order": list(key_order),
                           "admissible_count": len(admissible)}
    if not admissible:
        rec.update({"status": "CE_SELECTED_MANDATORY_ONLY", "selected": [], "key_values": pre_key_vector(prep, []),
                    "solver_used": False})
        return rec
    m = Milp(tag)
    z = {gid: m.var() for gid in admissible}
    letters_free = [L for L in LETTERS if L not in prep.mandatory_letters]
    u = {L: m.var() for L in letters_free}
    keys_free = sorted({tuple(prep.groups[g]["key"]) for g in admissible} - prep.mandatory_keys)
    v = {k: m.var() for k in keys_free}
    m.row({z[g]: 1.0 for g in admissible}, 0, b_pre)
    for L in letters_free:
        m.row({u[L]: 1.0, **{z[g]: 1.0 for g in admissible if L in prep.groups[g]["support"]}}, 1, math.inf)
    for k in keys_free:
        m.row({v[k]: 1.0, **{z[g]: -1.0 for g in admissible if tuple(prep.groups[g]["key"]) == k}}, -math.inf, 0)
    A = {g: prep.groups[g]["attrs"] for g in admissible}
    keys = [
        {u[L]: 1.0 for L in letters_free},
        {z[g]: -float(A[g]["s"] - 1) for g in admissible},
        {v[k]: -1.0 for k in keys_free},
        {z[g]: 1.0 for g in admissible},
        {z[g]: float(A[g]["t"]) for g in admissible},
        {z[g]: float(A[g]["tok"]) for g in admissible},
    ]
    if objective == "arch1_weighted":
        W = ARCH1_WEIGHTS
        obj: dict[int, float] = {}
        for g in admissible:
            a = A[g]
            u_g = (W["W_sup"] * (a["s"] - 1) + W["W_tier"] * (3 - a["t"]) + W["W_verb"] * a["verb"]
                   - W["W_ans_pre"] * a["a"] - W["W_single"] * a["n"] - W["W_abs"] * a["abs"]
                   - W["W_risk"] * risk_flag(prep.groups[g]) - W["W_soft"] * a["soft"] - W["W_dl"] * a["dl"])
            obj[z[g]] = -float(u_g) + W["W_red"] + W["W_len_pre"] * a["tok"]
        for k in keys_free:
            obj[v[k]] = -float(W["W_div"] + W["W_red"])
        for L in letters_free:
            obj[u[L]] = float(W["W_bal"])
        status, x, vals = lexicographic_solve(m, [obj], [z[g] for g in admissible])
    else:
        ordered = [keys[i] for i in key_order]
        status, x, vals = lexicographic_solve(m, ordered, [z[g] for g in admissible])
    if x is None:
        rec.update({"status": f"CE_SOLVER_NOT_OPTIMAL_{status}", "selected": None, "key_values": None,
                    "solver_used": True})
        return rec
    selected = [g for g in admissible if int(x[z[g]]) == 1]
    rec.update({"status": "CE_SELECTED" if selected else "CE_SELECTED_MANDATORY_ONLY",
                "selected": selected, "solver_used": True,
                "key_values": (vals if objective != "arch1_weighted" else pre_key_vector(prep, selected)),
                "weighted_objective": (-vals[0] if objective == "arch1_weighted" and vals else None)})
    # --- pure-Python re-check ---------------------------------------------------------------
    kv = pre_key_vector(prep, selected)
    ok = len(selected) <= b_pre and all(g in admissible for g in selected)
    if objective != "arch1_weighted":
        ok = ok and [kv[i] for i in key_order] == vals
    rec["verified"] = ok
    rec["key_values_recomputed"] = kv
    return rec


def solve_post(prep: Prepared, pre_selected: Sequence[str], optional_post: Sequence[str], b_post: int,
               k_a_post: int, key_order: Sequence[int], objective: str = "lexicographic",
               tag: str = "post", require_alt: bool = True) -> dict:
    """Choose the post-answer explanation graph, nested over the pre selection.

    Free variables: every post-admissible optional group (`optional_post`, the
    bounded OPTIONAL tier; ABSENCE_ONLY / risk / unverbalizable / distractor-label
    groups admissible here and ordered against) and every SHOWABLE alternative
    group. Fixed at 1: the pre-selected optional groups (nesting) and, outside
    the model, the mandatory groups. Hard: ENTITY-node budget b_post over all
    ENTITY nodes (mandatory nodes count; the class node never does [ARCH-2 C8]);
    COVER_ALT for every distractor that has a showable alternative; at most
    k_a_post optional Answer-only groups.
    Keys (default order): 0 ABSENCE_ONLY incidences, 1 risk-bearing groups,
    2 -shared information, 3 -distinct keys, 4 ENTITY nodes, 5 tier sum,
    6 token sum; then the canonical fix.
    """
    rec: dict[str, Any] = {"b_post": b_post, "k_a_post": k_a_post, "objective": objective,
                           "key_order": list(key_order), "pre_selected": list(pre_selected)}
    n_mand = len(prep.mandatory_nodes)
    if n_mand > b_post:
        rec.update({"status": "CE_MANDATORY_EXCEEDS_BUDGET", "selected_free": None, "key_values": None,
                    "solver_used": False, "mandatory_nodes": n_mand})
        return rec
    free = list(dict.fromkeys(list(optional_post) + list(pre_selected) + list(prep.alt_showable)))
    free = list(free)                                             # canonical order restored below
    order = {g["gid"]: i for i, g in enumerate(prep.uni["groups"])}
    free.sort(key=lambda gid: order[gid])
    m = Milp(tag)
    z = {gid: m.var() for gid in free}
    for gid in pre_selected:
        m.fix(z[gid], 1.0)
    nodes_free = sorted({prep.groups[g]["node"] for g in free} - prep.mandatory_nodes)
    y = {o: m.var() for o in nodes_free}
    keys_free = sorted({tuple(prep.groups[g]["key"]) for g in free} - prep.mandatory_keys)
    v = {k: m.var() for k in keys_free}
    letters_free = [L for L in LETTERS if L not in prep.mandatory_letters]
    u = {L: m.var() for L in letters_free}
    m.row({y[o]: 1.0 for o in nodes_free}, 0, b_post - n_mand)
    for g in free:
        o = prep.groups[g]["node"]
        if o in y:
            m.row({y[o]: 1.0, z[g]: -1.0}, 0, math.inf)
    if require_alt:
        for L in LETTERS[1:]:
            alts = [g for g in prep.alt_by_letter.get(L, []) if g in z]
            if alts:
                m.row({z[g]: 1.0 for g in alts}, 1, math.inf)
    ans_only = [g for g in free if prep.groups[g]["tier"] == T_OPT and prep.groups[g]["attrs"]["a"] == 1]
    if ans_only:
        m.row({z[g]: 1.0 for g in ans_only}, 0, k_a_post)
    for k in keys_free:
        m.row({v[k]: 1.0, **{z[g]: -1.0 for g in free if tuple(prep.groups[g]["key"]) == k}}, -math.inf, 0)
    for L in letters_free:
        m.row({u[L]: 1.0, **{z[g]: 1.0 for g in free if L in prep.groups[g]["support"]}}, 1, math.inf)
    A = {g: prep.groups[g]["attrs"] for g in free}
    keys = [
        {z[g]: float(A[g]["abs"]) for g in free},
        {z[g]: float(risk_flag(prep.groups[g])) for g in free},
        {z[g]: -float(A[g]["s"] - 1) for g in free},
        {v[k]: -1.0 for k in keys_free},
        {y[o]: 1.0 for o in nodes_free},
        {z[g]: float(A[g]["t"]) for g in free},
        {z[g]: float(A[g]["tok"]) for g in free},
    ]
    if objective == "arch1_weighted":
        W = ARCH1_WEIGHTS
        obj: dict[int, float] = {}
        for g in free:
            a = A[g]
            mand_like = 0
            u_g = (W["W_sup"] * (a["s"] - 1) + W["W_tier"] * (3 - a["t"]) + W["W_verb"] * a["verb"]
                   - W["W_ans_post"] * a["a"] * (1 - mand_like) - W["W_single"] * a["n"]
                   - W["W_abs"] * a["abs"] - W["W_risk"] * risk_flag(prep.groups[g])
                   - W["W_soft"] * a["soft"] - W["W_dl"] * a["dl"])
            obj[z[g]] = -float(u_g) + W["W_red"] + W["W_len_post"] * a["tok"]
        for k in keys_free:
            obj[v[k]] = -float(W["W_div"] + W["W_red"])
        for L in letters_free:
            obj[u[L]] = float(W["W_bal"])
        status, x, vals = lexicographic_solve(m, [obj], [z[g] for g in free])
    else:
        status, x, vals = lexicographic_solve(m, [keys[i] for i in key_order], [z[g] for g in free])
    if x is None:
        rec.update({"status": ("CE_NESTED_INFEASIBLE_AT_BUDGET" if status == "INFEASIBLE"
                               else f"CE_SOLVER_NOT_OPTIMAL_{status}"),
                    "selected_free": None, "key_values": None, "solver_used": True, "mandatory_nodes": n_mand})
        return rec
    selected = [g for g in free if int(x[z[g]]) == 1]
    kv = post_key_vector(prep, selected)
    nodes = prep.mandatory_nodes | {prep.groups[g]["node"] for g in selected}
    ok = (len(nodes) <= b_post and all(g in selected for g in pre_selected)
          and sum(1 for g in selected if g in ans_only) <= k_a_post)
    if require_alt:
        for L in LETTERS[1:]:
            alts = [g for g in prep.alt_by_letter.get(L, []) if g in z]
            if alts and not any(g in selected for g in alts):
                ok = False
    if objective != "arch1_weighted":
        ok = ok and [kv[i] for i in key_order] == vals
    rec.update({"status": "CE_SELECTED", "selected_free": selected, "solver_used": True,
                "key_values": (vals if objective != "arch1_weighted" else kv),
                "key_values_recomputed": kv, "verified": ok, "mandatory_nodes": n_mand,
                "entity_nodes": len(nodes),
                "weighted_objective": (-vals[0] if objective == "arch1_weighted" and vals else None)})
    return rec


# --- exhaustive oracle on small instances -------------------------------------------------

def oracle_pre(prep: Prepared, admissible: Sequence[str], b_pre: int, key_order: Sequence[int]) -> Optional[list[str]]:
    if len(admissible) > ORACLE_MAX_FREE:
        return None
    best_key = None
    ties: list[list[str]] = []
    for r in range(0, min(b_pre, len(admissible)) + 1):
        for combo in itertools.combinations(admissible, r):
            kv = pre_key_vector(prep, combo)
            k = [kv[i] for i in key_order]
            if best_key is None or k < best_key:
                best_key, ties = k, [list(combo)]
            elif k == best_key:
                ties.append(list(combo))
    return canonical_max(ties, admissible)


def oracle_post(prep: Prepared, pre_selected: Sequence[str], optional_post: Sequence[str], b_post: int,
                k_a_post: int, key_order: Sequence[int]) -> Optional[list[str]]:
    order = {g["gid"]: i for i, g in enumerate(prep.uni["groups"])}
    free = sorted(set(optional_post) | set(pre_selected) | set(prep.alt_showable), key=lambda g: order[g])
    movable = [g for g in free if g not in set(pre_selected)]
    if len(movable) > ORACLE_MAX_FREE:
        return None
    n_mand = len(prep.mandatory_nodes)
    if n_mand > b_post:
        return None
    best_key = None
    ties: list[list[str]] = []
    for r in range(0, len(movable) + 1):
        for combo in itertools.combinations(movable, r):
            sel = sorted(set(pre_selected) | set(combo), key=lambda g: order[g])
            nodes = prep.mandatory_nodes | {prep.groups[g]["node"] for g in sel}
            if len(nodes) > b_post:
                continue
            if sum(1 for g in sel if prep.groups[g]["tier"] == T_OPT and prep.groups[g]["attrs"]["a"] == 1) > k_a_post:
                continue
            feasible = True
            for L in LETTERS[1:]:
                alts = [g for g in prep.alt_by_letter.get(L, []) if g in set(free)]
                if alts and not any(g in sel for g in alts):
                    feasible = False
                    break
            if not feasible:
                continue
            kv = post_key_vector(prep, sel)
            k = [kv[i] for i in key_order]
            if best_key is None or k < best_key:
                best_key, ties = k, [sel]
            elif k == best_key:
                ties.append(sel)
    if not ties:
        return []
    return canonical_max(ties, free)


# ==========================================================================
# 7) PER-ITEM MEASUREMENT (worker)
# ==========================================================================

def adjacent_swaps(n: int) -> list[tuple[str, list[int]]]:
    base = list(range(n))
    out = [("baseline", base)]
    for i in range(n - 1):
        p = list(base)
        p[i], p[i + 1] = p[i + 1], p[i]
        out.append((f"swap_{i}_{i + 1}", p))
    return out


def jaccard(a: Sequence[str], b: Sequence[str]) -> Optional[float]:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return round(len(sa & sb) / len(sa | sb), 4)


def earliest_diff(k1: Optional[Sequence[int]], k2: Optional[Sequence[int]], names: Sequence[str]) -> str:
    if k1 is None or k2 is None:
        return "NO_KEY_VECTOR"
    for i, (x, y) in enumerate(zip(k1, k2)):
        if x != y:
            return names[i]
    return "CANONICAL_TIE_BREAK"


def post_structure(prep: Prepared, post: dict, pre_selected: Sequence[str]) -> dict:
    """Structural metrics of one post-answer graph (class as caption; the
    class-as-node arm is +1 node and +4 edges, reported in aggregation)."""
    if post.get("selected_free") is None:
        return {"status": post["status"]}
    sel = list(prep.mandatory) + list(post["selected_free"])
    gs = [prep.groups[g] for g in sel]
    nodes = {g["node"] for g in gs}
    edges = sum(len(g["edges"]) for g in gs)
    per_letter_degree = {L: sum(1 for g in gs for e in g["edges"] if e[0] == L) for L in LETTERS}
    opt_sel = [g for g in post["selected_free"] if prep.groups[g]["tier"] == T_OPT]
    alt_sel = [g for g in post["selected_free"] if prep.groups[g]["tier"] == T_ALT]
    per_letter_optional = {L: sum(1 for g in opt_sel if L in prep.groups[g]["support"]) for L in LETTERS}
    support_dist = Counter(str(prep.groups[g]["attrs"]["s"]) for g in opt_sel)
    covered = {L: any(L in prep.groups[g]["alt_for"] for g in alt_sel) for L in LETTERS[1:]}
    return {
        "status": post["status"], "entity_nodes": len(nodes), "edges": edges,
        "mandatory_nodes": len(prep.mandatory_nodes),
        "mandatory_share": round(len(prep.mandatory_nodes) / len(nodes), 4) if nodes else None,
        "optional_groups": len(opt_sel), "alternative_groups": len(alt_sel),
        "pre_groups_in_post": len(pre_selected),
        "per_letter_degree": per_letter_degree, "per_letter_optional": per_letter_optional,
        "min_max_degree_ratio": (round(min(per_letter_degree.values()) / max(per_letter_degree.values()), 4)
                                 if max(per_letter_degree.values()) else None),
        "letters_without_optional": [L for L in LETTERS[1:] if per_letter_optional[L] == 0],
        "support_distribution": dict(support_dist),
        "distinct_keys": len({tuple(g["key"]) for g in gs}),
        "abs_incidences_exposed": sum(prep.groups[g]["attrs"]["abs"] for g in post["selected_free"]),
        "risk_groups_exposed": sum(risk_flag(prep.groups[g]) for g in post["selected_free"]),
        "cover_alt": covered, "alt_unshowable_letters": prep.alt_unshowable_letters,
        "mandatory_only": len(opt_sel) == 0,
        "answer_only_optional": sum(1 for g in opt_sel if prep.groups[g]["attrs"]["a"] == 1),
        "unverbalizable_groups_exposed": sum(1 for g in post["selected_free"] if prep.groups[g]["attrs"]["verb"] == 0),
    }


def measure_item(universe_path: str, out_path: str, config: dict) -> dict:
    """Everything the audit measures for ONE item (runs in a worker process)."""
    SOLVER_CALLS.clear()
    uni = read_json(Path(universe_path))
    prep = prepare(uni)
    rec: dict[str, Any] = {"item": uni["item"], "counts": uni["counts"],
                           "rationale": {"absence_incidences": uni["rationale"]["absence_incidences"],
                                         "fully_verbalizable": uni["rationale"]["fully_verbalizable"],
                                         "size": len(uni["rationale"]["facts"])},
                           "index": uni["index"], "validation": uni["validation"],
                           "mandatory": {"groups": len(prep.mandatory), "nodes": len(prep.mandatory_nodes),
                                         "keys": len(prep.mandatory_keys)},
                           "alternatives": {"showable": len(prep.alt_showable),
                                            "by_letter": {L: len(v) for L, v in prep.alt_by_letter.items()},
                                            "unshowable_letters": prep.alt_unshowable_letters,
                                            "shared_with_answer": sum(prep.groups[g]["alt_shared_with_answer"]
                                                                      for g in prep.alt_showable)}}

    # --- H14: admissibility arms over the FULL optional tier -----------------------------
    arms: dict[str, Any] = {}
    optional_groups = [prep.groups[g] for g in prep.optional]
    incid = Counter()
    for g in optional_groups:
        a = g["attrs"]
        incid["abs"] += a["abs"]; incid["alt"] += a["alt"]; incid["cont"] += a["cont"]; incid["unres"] += a["unres"]
        incid["risk_present"] += a["risk_present"]; incid["risk_unmod"] += a["risk_unmod"]; incid["risk_unres"] += a["risk_unres"]
        incid["groups_with_abs"] += int(a["abs"] > 0); incid["groups_with_cont"] += int(a["cont"] > 0)
        incid["groups_with_unres"] += int(a["unres"] > 0); incid["groups_with_risk"] += risk_flag(g)
        incid["groups_unverbalizable"] += int(a["verb"] == 0); incid["groups_dl"] += a["dl"]
        incid["groups_answer_only"] += a["a"]; incid["groups_singleton"] += a["n"]
        incid["groups_A_excluding_support3"] += int(a["s"] == 3 and a["excl_answer"] == 1)
        incid["groups_A_excluding_any"] += int(a["excl_answer"] == 1)
    rec["optional_incidences"] = dict(incid)
    for arm in ARMS:
        adm, reasons = [], Counter()
        multi = Counter()
        by_support = Counter()
        for g in optional_groups:
            ok, failed = arm_admissible(arm, g)
            if ok:
                adm.append(g["gid"]); by_support[str(g["attrs"]["s"])] += 1
            else:
                reasons[failed[0]] += 1
                for f in failed:
                    multi[f] += 1
        arms[arm] = {"admissible": adm, "admissible_count": len(adm), "optional_total": len(optional_groups),
                     "by_support": dict(by_support), "first_failing_reason": dict(reasons),
                     "all_failing_reasons": dict(multi),
                     "ge1": int(len(adm) >= 1), "ge2": int(len(adm) >= 2), "ge3": int(len(adm) >= 3),
                     "mandatory_only": int(len(adm) == 0),
                     "A_excluding_support3_survivors": sum(1 for g in adm if prep.groups[g]["attrs"]["s"] == 3
                                                           and prep.groups[g]["attrs"]["excl_answer"] == 1)}
    rec["h14"] = arms

    # --- the measurement universe for H13 / H7: stratified bounding at MEASURE_N_MAX --------------
    bounded, binfo = bound_optional(prep, config["measure_n_max"], "stratified")
    rec["measure_universe"] = binfo
    bset = set(bounded)
    adm_by_arm = {arm: [g for g in arms[arm]["admissible"] if g in bset] for arm in ARMS}
    B_PRE, B_POST, K_A = config["b_pre"], config["b_post"], config["k_a_post"]
    pre_base = list(range(len(PRE_KEYS)))
    post_base = list(range(len(POST_KEYS)))

    # --- H13: objective stability (primary arm B; comparators on arm A) -----------------------
    h13: dict[str, Any] = {}
    prim = adm_by_arm["B_arch2_hard"]
    pre_runs = {}
    for name, perm in adjacent_swaps(len(PRE_KEYS)):
        pre_runs[name] = solve_pre(prep, prim, B_PRE, perm, tag=f"h13_pre_{name}")
    base_pre = pre_runs["baseline"]
    h13["pre"] = {"baseline": base_pre, "swaps": {}}
    for name, r in pre_runs.items():
        if name == "baseline":
            continue
        h13["pre"]["swaps"][name] = {
            "status": r["status"], "selected": r["selected"],
            "changed": (r["selected"] != base_pre["selected"]),
            "jaccard": jaccard(r["selected"] or [], base_pre["selected"] or []),
            "earliest_key": earliest_diff(base_pre.get("key_values_recomputed"), r.get("key_values_recomputed"), PRE_KEYS)
            if r["selected"] != base_pre["selected"] else "",
        }
    pre_sel = base_pre["selected"] or []
    post_runs = {}
    for name, perm in adjacent_swaps(len(POST_KEYS)):
        post_runs[name] = solve_post(prep, pre_sel, bounded, B_POST, K_A, perm, tag=f"h13_post_{name}")
    base_post = post_runs["baseline"]
    h13["post"] = {"baseline": base_post, "swaps": {}}
    for name, r in post_runs.items():
        if name == "baseline":
            continue
        h13["post"]["swaps"][name] = {
            "status": r["status"], "selected_free": r["selected_free"],
            "changed": (r["selected_free"] != base_post["selected_free"]),
            "jaccard": jaccard(r["selected_free"] or [], base_post["selected_free"] or []),
            "earliest_key": earliest_diff(base_post.get("key_values_recomputed"), r.get("key_values_recomputed"), POST_KEYS)
            if r["selected_free"] != base_post["selected_free"] else "",
        }
    # comparators: lexicographic on arm A; ARCH-1 weighted on arm A
    armA = adm_by_arm["A_arch1_penalty"]
    lexA_pre = solve_pre(prep, armA, B_PRE, pre_base, tag="cmp_lexA_pre")
    lexA_post = solve_post(prep, lexA_pre["selected"] or [], bounded, B_POST, K_A, post_base, tag="cmp_lexA_post")
    wA_pre = solve_pre(prep, armA, B_PRE, pre_base, objective="arch1_weighted", tag="cmp_wA_pre")
    wA_post = solve_post(prep, wA_pre["selected"] or [], bounded, B_POST, K_A, post_base,
                         objective="arch1_weighted", tag="cmp_wA_post")
    h13["comparators"] = {
        "arm_A_lexicographic": {"pre": lexA_pre, "post": lexA_post,
                                "pre_jaccard_vs_primary": jaccard(lexA_pre["selected"] or [], pre_sel),
                                "post_jaccard_vs_primary": jaccard(lexA_post.get("selected_free") or [],
                                                                   base_post.get("selected_free") or [])},
        "arm_A_arch1_weighted": {"pre": wA_pre, "post": wA_post,
                                 "pre_jaccard_vs_primary": jaccard(wA_pre["selected"] or [], pre_sel),
                                 "post_jaccard_vs_primary": jaccard(wA_post.get("selected_free") or [],
                                                                    base_post.get("selected_free") or []),
                                 "pre_jaccard_vs_armA_lex": jaccard(wA_pre["selected"] or [], lexA_pre["selected"] or []),
                                 "post_jaccard_vs_armA_lex": jaccard(wA_post.get("selected_free") or [],
                                                                     lexA_post.get("selected_free") or []),
                                 "pre_abs_exposed": sum(prep.groups[g]["attrs"]["abs"] for g in (wA_pre["selected"] or [])),
                                 "pre_singletons_exposed": sum(prep.groups[g]["attrs"]["n"] for g in (wA_pre["selected"] or []))},
    }
    # oracle on small instances (baseline orders)
    oracle: dict[str, Any] = {"pre": None, "post": None}
    o_pre = oracle_pre(prep, prim, B_PRE, pre_base)
    if o_pre is not None:
        oracle["pre"] = {"ran": True, "agrees": (o_pre == (base_pre["selected"] or [])), "oracle": o_pre}
    o_post = oracle_post(prep, pre_sel, bounded, B_POST, K_A, post_base)
    if o_post is not None and base_post.get("selected_free") is not None:
        oracle["post"] = {"ran": True, "agrees": (o_post == base_post["selected_free"]), "oracle": o_post}
    rec["h13"] = h13
    rec["oracle"] = oracle

    # --- H7: exposure and budget sweep (arm B primary) ------------------------------------------
    h7: dict[str, Any] = {"pre": {}, "post": {}}
    pre_by_budget = {}
    for bp in B_PRE_SWEEP:
        r = solve_pre(prep, prim, bp, pre_base, tag=f"h7_pre_{bp}")
        pre_by_budget[bp] = r
        h7["pre"][str(bp)] = {"status": r["status"], "selected": r["selected"], "key_values": r.get("key_values_recomputed"),
                              "verified": r.get("verified"), "n_selected": len(r["selected"] or []),
                              "letters_without_optional": [L for L in LETTERS[1:] if not any(
                                  L in prep.groups[g]["support"] for g in (r["selected"] or []))],
                              "support_distribution": dict(Counter(str(prep.groups[g]["attrs"]["s"]) for g in (r["selected"] or []))),
                              "distinct_keys": len({tuple(prep.groups[g]["key"]) for g in (r["selected"] or [])} | prep.mandatory_keys),
                              "token_sum": sum(prep.groups[g]["attrs"]["tok"] for g in (r["selected"] or [])),
                              "pre_nodes_new": len({prep.groups[g]["node"] for g in (r["selected"] or [])} - prep.mandatory_nodes)}
        for bpost in B_POST_SWEEP:
            for ka in K_A_POST_SWEEP:
                p = solve_post(prep, r["selected"] or [], bounded, bpost, ka, post_base, tag=f"h7_post_{bp}_{bpost}_{ka}")
                cell = post_structure(prep, p, r["selected"] or [])
                cell["verified"] = p.get("verified")
                cell["key_values"] = p.get("key_values_recomputed")
                h7["post"][f"{bp}|{bpost}|{ka}"] = cell
    rec["h7"] = h7

    # --- H18: bounding stability at the designated configuration ----------------------------------
    h18: dict[str, Any] = {"optional_total": len(prep.optional), "studied": len(prep.optional) > min(N_MAX_SWEEP)}
    if h18["studied"]:
        runs: dict[str, dict] = {}
        levels = [(str(n), n) for n in N_MAX_SWEEP]
        if len(prep.optional) <= FULL_UNIVERSE_CAP:
            levels.append(("FULL", None))
        else:
            h18["full_not_computed_reason"] = f"optional universe {len(prep.optional)} exceeds cap {FULL_UNIVERSE_CAP}"
        for method in ("modular", "stratified"):
            for label, n in levels:
                if label == "FULL" and method == "stratified" and "modular|FULL" in runs:
                    runs[f"{method}|FULL"] = runs["modular|FULL"]      # FULL is method-independent
                    continue
                b, info = bound_optional(prep, n, method)
                adm = [g for g in arms["B_arch2_hard"]["admissible"] if g in set(b)]
                pr = solve_pre(prep, adm, B_PRE, pre_base, tag=f"h18_pre_{method}_{label}")
                po = solve_post(prep, pr["selected"] or [], b, B_POST, K_A, post_base, tag=f"h18_post_{method}_{label}")
                runs[f"{method}|{label}"] = {"info": info, "pre": pr["selected"], "pre_keys": pr.get("key_values_recomputed"),
                                             "pre_status": pr["status"], "post": po.get("selected_free"),
                                             "post_keys": po.get("key_values_recomputed"), "post_status": po["status"]}
        h18["runs"] = runs
        comps = {}
        seq = [str(n) for n in N_MAX_SWEEP] + (["FULL"] if any(k.endswith("|FULL") for k in runs) else [])
        for method in ("modular", "stratified"):
            for a_label, b_label in zip(seq, seq[1:]):
                ra, rb = runs.get(f"{method}|{a_label}"), runs.get(f"{method}|{b_label}")
                if ra is None or rb is None:
                    continue
                actually_bounded = (ra["info"]["scope"] == "UNIVERSE_BOUNDED")
                comps[f"{method}|{a_label}->{b_label}"] = {
                    "actually_bounded_at_a": actually_bounded,
                    "pre_equal": ra["pre"] == rb["pre"], "post_equal": ra["post"] == rb["post"],
                    "pre_jaccard": jaccard(ra["pre"] or [], rb["pre"] or []),
                    "post_jaccard": jaccard(ra["post"] or [], rb["post"] or []),
                    "earliest_key": ("" if (ra["pre"] == rb["pre"] and ra["post"] == rb["post"]) else
                                     ("pre:" + earliest_diff(ra["pre_keys"], rb["pre_keys"], PRE_KEYS)
                                      if ra["pre"] != rb["pre"] else
                                      "post:" + earliest_diff(ra["post_keys"], rb["post_keys"], POST_KEYS))),
                }
        h18["comparisons"] = comps
    rec["h18"] = h18

    # --- H6: solver instrumentation for this item ----------------------------------------------
    calls = list(SOLVER_CALLS)
    rec["solver"] = {"calls": len(calls), "status_counts": dict(Counter(c["status_name"] for c in calls)),
                     "seconds_total": round(sum(c["seconds"] for c in calls), 4),
                     "seconds_max": round(max((c["seconds"] for c in calls), default=0.0), 4),
                     "n_vars_max": max((c["n_vars"] for c in calls), default=0),
                     "n_rows_max": max((c["n_rows"] for c in calls), default=0),
                     "call_seconds": [round(c["seconds"], 5) for c in calls],
                     "call_vars": [c["n_vars"] for c in calls], "call_rows": [c["n_rows"] for c in calls]}
    verified_flags = [r.get("verified") for r in pre_runs.values()] + [r.get("verified") for r in post_runs.values()]
    verified_flags += [h7["pre"][k]["verified"] for k in h7["pre"]] + [h7["post"][k].get("verified") for k in h7["post"]]
    rec["verification"] = {"checked": sum(1 for f in verified_flags if f is not None),
                           "failed": sum(1 for f in verified_flags if f is False)}
    write_json(Path(out_path), rec, gz=True)
    return {"item": uni["item"]["key"], "calls": len(calls), "seconds": rec["solver"]["seconds_total"],
            "verification_failed": rec["verification"]["failed"]}


# ==========================================================================
# 8) STAGES: measure (multiprocess), rerun (determinism), rollups, package
# ==========================================================================

def measured_items(out_dir: Path) -> list[Path]:
    return sorted((out_dir / "measure").glob("*.json.gz"))


def stage_measure(args, refs: list[ItemRef], out_dir: Path) -> None:
    config = {"b_pre": DESIGNATED_B_PRE, "b_post": DESIGNATED_B_POST, "k_a_post": DESIGNATED_K_A_POST,
              "measure_n_max": MEASURE_N_MAX}
    todo = []
    for ref in refs:
        if not ref.gate_passed:
            continue
        up = out_dir / "universe" / f"{item_key(ref)}.json.gz"
        mp = out_dir / "measure" / f"{item_key(ref)}.json.gz"
        if up.is_file() and not mp.is_file():
            todo.append((str(up), str(mp)))
    (out_dir / "measure").mkdir(parents=True, exist_ok=True)
    say(f"[measure] {len(todo)} items to measure with {args.workers} workers "
        f"(designated B_pre={config['b_pre']}, B_post={config['b_post']}, K_A_post={config['k_a_post']}, "
        f"stratified N_max={config['measure_n_max']})")
    if not todo:
        return
    t0 = time.time()
    done = 0
    if args.workers <= 1:
        for up, mp in todo:
            r = measure_item(up, mp, config)
            done += 1
            say(f"  [{done}/{len(todo)}] {r['item']}: {r['calls']} solves, {r['seconds']:.2f}s solver time")
        return
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(measure_item, up, mp, config): (up, mp) for up, mp in todo}
        for fut in as_completed(futures):
            up, mp = futures[fut]
            done += 1
            try:
                r = fut.result()
                say(f"  [{done}/{len(todo)}] {r['item']}: {r['calls']} solves, {r['seconds']:.2f}s solver time"
                    + (" VERIFICATION FAILED" if r["verification_failed"] else ""))
            except Exception as exc:                                    # noqa: BLE001
                say(f"  [{done}/{len(todo)}] {Path(up).name}: FAILED {exc!r}")
                write_json(Path(mp).with_suffix("").with_suffix(".FAILED.json"), {"universe": up, "error": repr(exc)})
    say(f"[measure] finished in {time.time() - t0:.1f}s")


def strip_timing(rec: Any) -> Any:
    """Remove solver timing fields so two runs can be compared for equality."""
    if isinstance(rec, dict):
        return {k: strip_timing(v) for k, v in rec.items() if k not in ("solver",)}
    if isinstance(rec, list):
        return [strip_timing(v) for v in rec]
    return rec


def stage_rerun(args, refs: list[ItemRef], out_dir: Path) -> None:
    """Deterministic re-measurement of a sample in a fresh process (H6)."""
    config = {"b_pre": DESIGNATED_B_PRE, "b_post": DESIGNATED_B_POST, "k_a_post": DESIGNATED_K_A_POST,
              "measure_n_max": MEASURE_N_MAX}
    stored = measured_items(out_dir)
    if not stored:
        say("[rerun] nothing measured yet")
        return
    step = max(1, len(stored) // args.rerun_sample)
    sample = stored[::step][:args.rerun_sample]
    rerun_dir = out_dir / "rerun"
    rerun_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    say(f"[rerun] re-measuring {len(sample)} of {len(stored)} items in a fresh process")
    for mp in sample:
        key = mp.name.replace(".json.gz", "")
        up = out_dir / "universe" / mp.name
        rp = rerun_dir / mp.name
        measure_item(str(up), str(rp), config)
        a = strip_timing(read_json(mp))
        b = strip_timing(read_json(rp))
        diffs = [k for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
        rows.append({"item": key, "identical_excluding_timing": not diffs, "differing_sections": ";".join(diffs)})
        say(f"  {key}: {'IDENTICAL' if not diffs else 'DIFFERS ' + ','.join(diffs)}")
    write_csv(out_dir / "h6_deterministic_rerun.csv", rows)
    write_json(out_dir / "h6_deterministic_rerun.json",
               {"sample_size": len(rows), "identical": sum(1 for r in rows if r["identical_excluding_timing"]),
                "rows": rows})


# --- rollups -------------------------------------------------------------------------------

def _mean(xs: Sequence[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 4) if xs else None


def _median(xs: Sequence[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 4) if xs else None


def _pctl(xs: Sequence[float], q: float) -> Optional[float]:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return round(xs[int(k)], 6)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 6)


def rollup_group(recs: list[dict], h5rows: list[dict]) -> dict:
    """Every rate carries its denominator; nothing here is a claim about humans."""
    n = len(recs)
    out: dict[str, Any] = {"items": n}
    if n == 0:
        return out
    # H14 arms
    arms: dict[str, Any] = {}
    for arm in ARMS:
        adm = [r["h14"][arm]["admissible_count"] for r in recs]
        tot = [r["h14"][arm]["optional_total"] for r in recs]
        first = Counter(); allr = Counter(); bys = Counter()
        for r in recs:
            first.update(r["h14"][arm]["first_failing_reason"]); allr.update(r["h14"][arm]["all_failing_reasons"])
            bys.update({k: v for k, v in r["h14"][arm]["by_support"].items()})
        arms[arm] = {
            "optional_groups_before": sum(tot), "admissible_after": sum(adm),
            "retained": rate(sum(adm), sum(tot)),
            "admissible_per_item_mean": _mean(adm), "admissible_per_item_median": _median(adm),
            "items_ge1": rate(sum(r["h14"][arm]["ge1"] for r in recs), n),
            "items_ge2": rate(sum(r["h14"][arm]["ge2"] for r in recs), n),
            "items_ge3": rate(sum(r["h14"][arm]["ge3"] for r in recs), n),
            "mandatory_only_items": rate(sum(r["h14"][arm]["mandatory_only"] for r in recs), n),
            "admissible_by_support": dict(bys),
            "first_failing_reason_totals": dict(first), "all_failing_reason_totals": dict(allr),
            "items_with_A_excluding_support3_survivor": rate(
                sum(1 for r in recs if r["h14"][arm]["A_excluding_support3_survivors"] > 0), n),
            "A_excluding_support3_survivors_total": sum(r["h14"][arm]["A_excluding_support3_survivors"] for r in recs),
        }
    inc = Counter()
    for r in recs:
        inc.update(r["optional_incidences"])
    out["h14"] = {"arms": arms, "optional_incidence_totals": dict(inc),
                  "optional_groups_total": sum(r["counts"].get("tier_OPTIONAL_CONTEXT", 0) for r in recs)}
    # universe / grounding validation
    agree_pairs = sum(r["validation"]["frozen_vs_rule"].get("pairs", 0) for r in recs)
    out["universe"] = {
        "groups_mean": _mean([r["counts"]["groups"] for r in recs]),
        "optional_mean": _mean([r["counts"].get("tier_OPTIONAL_CONTEXT", 0) for r in recs]),
        "optional_median": _median([r["counts"].get("tier_OPTIONAL_CONTEXT", 0) for r in recs]),
        "optional_max": max(r["counts"].get("tier_OPTIONAL_CONTEXT", 0) for r in recs),
        "excluded_mean": _mean([r["counts"].get("tier_EXCLUDED", 0) for r in recs]),
        "index_available": rate(sum(1 for r in recs if r["index"]["available"]), n),
        "answer_enumeration_matches_csv": rate(sum(1 for r in recs if r["validation"]["answer_enumeration_matches_csv"]), n),
        "eligible_mismatch_items": sum(1 for r in recs if r["validation"]["eligible_mismatch_count"] > 0),
        "grounding_rule_vs_frozen_level": {
            "pairs": agree_pairs,
            "grounding_equal": rate(sum(r["validation"]["frozen_vs_rule"].get("grounding_equal", 0) for r in recs), agree_pairs),
            "risk_equal": rate(sum(r["validation"]["frozen_vs_rule"].get("risk_equal", 0) for r in recs), agree_pairs)},
        "rationale_absence_incidences_total": sum(r["rationale"]["absence_incidences"] for r in recs),
        "items_with_rationale_absence_incidence": rate(sum(1 for r in recs if r["rationale"]["absence_incidences"] > 0), n),
        "alt_unshowable_items": rate(sum(1 for r in recs if r["alternatives"]["unshowable_letters"]), n),
        "alt_shared_with_answer_groups": sum(r["alternatives"]["shared_with_answer"] for r in recs),
        "mandatory_nodes_mean": _mean([r["mandatory"]["nodes"] for r in recs]),
    }
    # H5
    if h5rows:
        m = len(h5rows)
        cf = Counter(r.get("counterfactual", "NOT_AUDITED") for r in h5rows)
        keys = Counter()
        for r in h5rows:
            for k in (r.get("unverbalizable_keys") or "").split(";"):
                if k:
                    keys[k] += 1
        out["h5"] = {
            "items": m,
            "kernel_replay_match": rate(sum(1 for r in h5rows if r.get("kernel_replay_match")), m),
            "kernel_replay_not_computed_timeout": rate(sum(1 for r in h5rows if r.get("kernel_replay_match") is None), m),
            "artefact_vs_kernel_verbalizable_agree": rate(
                sum(1 for r in h5rows if r.get("artefact_vs_kernel_verbalizable_agree")),
                sum(1 for r in h5rows if r.get("artefact_vs_kernel_verbalizable_agree") is not None)),
            "rstar_fully_verbalizable": rate(sum(1 for r in h5rows if r.get("rstar_fully_verbalizable")), m),
            "rstar_not_fully_verbalizable": rate(sum(1 for r in h5rows if r.get("rstar_fully_verbalizable") is False), m),
            "counterfactual_outcomes": dict(cf),
            "items_lost_under_require_verbalizable": rate(cf.get("NO_FULLY_VERBALIZABLE_MIN_CARD_SOLUTION_AT_SAME_POLICY", 0), m),
            "items_counterfactual_not_computed_timeout": rate(
                sum(v for k, v in cf.items() if k.startswith("COUNTERFACTUAL_NOT_COMPUTED")), m),
            "same_triple_enumeration_timeouts": sum(1 for r in h5rows if (r.get("same_triple_note") or "").startswith("TIMEOUT")),
            "items_rationale_only_change": rate(cf.get("ALTERNATIVE_RATIONALE_ONLY", 0), m),
            "items_distractors_change": rate(cf.get("ALTERNATIVE_DISTRACTORS_CHANGE", 0), m),
            "items_alt_rstar_grew": sum(1 for r in h5rows if r.get("alt_rstar_grew")),
            "unverbalizable_key_histogram": dict(keys.most_common()),
            "same_triple_fully_verbalizable_exists": rate(
                sum(1 for r in h5rows if (r.get("same_triple_fully_verbalizable_rationales") or 0) > 0
                    and r.get("rstar_fully_verbalizable") is False),
                sum(1 for r in h5rows if r.get("rstar_fully_verbalizable") is False)),
        }
    # H13
    solvable = [r for r in recs if r["h13"]["pre"]["baseline"].get("selected") is not None]
    h13: dict[str, Any] = {"items_with_pre_solution": rate(len(solvable), n), "pre_swaps": {}, "post_swaps": {}}
    for name in [s for s, _ in adjacent_swaps(len(PRE_KEYS))][1:]:
        rows = [r["h13"]["pre"]["swaps"][name] for r in solvable if name in r["h13"]["pre"]["swaps"]]
        h13["pre_swaps"][name] = {
            "changed": rate(sum(1 for x in rows if x["changed"]), len(rows)),
            "jaccard_mean": _mean([x["jaccard"] for x in rows]),
            "earliest_key": dict(Counter(x["earliest_key"] for x in rows if x["changed"]))}
    post_ok = [r for r in recs if r["h13"]["post"]["baseline"].get("selected_free") is not None]
    h13["items_with_post_solution"] = rate(len(post_ok), n)
    h13["post_baseline_status"] = dict(Counter(r["h13"]["post"]["baseline"]["status"] for r in recs))
    for name in [s for s, _ in adjacent_swaps(len(POST_KEYS))][1:]:
        rows = [r["h13"]["post"]["swaps"][name] for r in post_ok if name in r["h13"]["post"]["swaps"]]
        h13["post_swaps"][name] = {
            "changed": rate(sum(1 for x in rows if x["changed"]), len(rows)),
            "jaccard_mean": _mean([x["jaccard"] for x in rows]),
            "earliest_key": dict(Counter(x["earliest_key"] for x in rows if x["changed"]))}
    cmpA = [r["h13"]["comparators"] for r in recs]
    h13["comparators"] = {
        "arm_A_lex_vs_primary_pre_jaccard_mean": _mean([c["arm_A_lexicographic"]["pre_jaccard_vs_primary"] for c in cmpA]),
        "arm_A_lex_vs_primary_pre_identical": rate(sum(1 for c in cmpA if c["arm_A_lexicographic"]["pre_jaccard_vs_primary"] == 1.0), n),
        "arch1_weighted_vs_primary_pre_jaccard_mean": _mean([c["arm_A_arch1_weighted"]["pre_jaccard_vs_primary"] for c in cmpA]),
        "arch1_weighted_vs_primary_pre_identical": rate(sum(1 for c in cmpA if c["arm_A_arch1_weighted"]["pre_jaccard_vs_primary"] == 1.0), n),
        "arch1_weighted_vs_arm_A_lex_pre_jaccard_mean": _mean([c["arm_A_arch1_weighted"]["pre_jaccard_vs_armA_lex"] for c in cmpA]),
        "arch1_weighted_vs_arm_A_lex_pre_identical": rate(sum(1 for c in cmpA if c["arm_A_arch1_weighted"]["pre_jaccard_vs_armA_lex"] == 1.0), n),
        "arch1_weighted_pre_items_exposing_absence": rate(sum(1 for c in cmpA if c["arm_A_arch1_weighted"]["pre_abs_exposed"] > 0), n),
        "arch1_weighted_pre_absence_incidences_total": sum(c["arm_A_arch1_weighted"]["pre_abs_exposed"] for c in cmpA),
        "arch1_weighted_pre_items_exposing_singletons": rate(sum(1 for c in cmpA if c["arm_A_arch1_weighted"]["pre_singletons_exposed"] > 0), n),
        "arch1_weighted_vs_primary_post_jaccard_mean": _mean([c["arm_A_arch1_weighted"]["post_jaccard_vs_primary"] for c in cmpA]),
        "arm_A_lex_vs_primary_post_jaccard_mean": _mean([c["arm_A_lexicographic"]["post_jaccard_vs_primary"] for c in cmpA]),
    }
    oracle_pre = [r["oracle"]["pre"] for r in recs if r["oracle"]["pre"]]
    oracle_post = [r["oracle"]["post"] for r in recs if r["oracle"]["post"]]
    h13["oracle"] = {"pre_ran": len(oracle_pre), "pre_agree": sum(1 for o in oracle_pre if o["agrees"]),
                     "post_ran": len(oracle_post), "post_agree": sum(1 for o in oracle_post if o["agrees"])}
    out["h13"] = h13
    # H7
    h7: dict[str, Any] = {"pre": {}, "post": {}}
    for bp in B_PRE_SWEEP:
        cells = [r["h7"]["pre"][str(bp)] for r in recs]
        h7["pre"][str(bp)] = {
            "n_selected_mean": _mean([c["n_selected"] for c in cells]),
            "budget_fully_used": rate(sum(1 for c in cells if c["n_selected"] == bp), n),
            "mandatory_only": rate(sum(1 for c in cells if c["n_selected"] == 0), n),
            "items_every_distractor_has_optional": rate(sum(1 for c in cells if not c["letters_without_optional"]), n),
            "letters_without_optional_mean": _mean([len(c["letters_without_optional"]) for c in cells]),
            "distinct_keys_mean": _mean([c["distinct_keys"] for c in cells]),
            "token_sum_mean": _mean([c["token_sum"] for c in cells]),
            "pre_new_nodes_mean": _mean([c["pre_nodes_new"] for c in cells]),
            "support_distribution": dict(sum((Counter(c["support_distribution"]) for c in cells), Counter())),
        }
    for bp in B_PRE_SWEEP:
        for bpost in B_POST_SWEEP:
            for ka in K_A_POST_SWEEP:
                key = f"{bp}|{bpost}|{ka}"
                cells = [r["h7"]["post"][key] for r in recs]
                okc = [c for c in cells if c["status"] == "CE_SELECTED"]
                letters_with_alt = sum(1 for r in recs for L in LETTERS[1:] if r["alternatives"]["by_letter"][L] > 0)
                cover = sum(1 for c in okc for L, v in c["cover_alt"].items() if v)
                h7["post"][key] = {
                    "status": dict(Counter(c["status"] for c in cells)),
                    "selected": rate(len(okc), n),
                    "mandatory_only": rate(sum(1 for c in okc if c["mandatory_only"]), len(okc)),
                    "entity_nodes_mean": _mean([c["entity_nodes"] for c in okc]),
                    "entity_nodes_median": _median([c["entity_nodes"] for c in okc]),
                    "edges_mean": _mean([c["edges"] for c in okc]),
                    "class_as_node_nodes_mean": (_mean([c["entity_nodes"] + 1 for c in okc])),
                    "class_as_node_edges_mean": (_mean([c["edges"] + 4 for c in okc])),
                    "mandatory_share_mean": _mean([c["mandatory_share"] for c in okc]),
                    "optional_groups_mean": _mean([c["optional_groups"] for c in okc]),
                    "alternative_groups_mean": _mean([c["alternative_groups"] for c in okc]),
                    "per_letter_optional_mean": {L: _mean([c["per_letter_optional"][L] for c in okc]) for L in LETTERS},
                    "per_letter_degree_mean": {L: _mean([c["per_letter_degree"][L] for c in okc]) for L in LETTERS},
                    "min_max_degree_ratio_mean": _mean([c["min_max_degree_ratio"] for c in okc]),
                    "items_every_distractor_has_optional": rate(sum(1 for c in okc if not c["letters_without_optional"]), len(okc)),
                    "support_distribution": dict(sum((Counter(c["support_distribution"]) for c in okc), Counter())),
                    "distinct_keys_mean": _mean([c["distinct_keys"] for c in okc]),
                    "cover_alt_satisfied": rate(cover, letters_with_alt),
                    "abs_incidences_exposed_mean": _mean([c["abs_incidences_exposed"] for c in okc]),
                    "items_exposing_absence_post": rate(sum(1 for c in okc if c["abs_incidences_exposed"] > 0), len(okc)),
                    "risk_groups_exposed_mean": _mean([c["risk_groups_exposed"] for c in okc]),
                    "unverbalizable_groups_exposed_mean": _mean([c["unverbalizable_groups_exposed"] for c in okc]),
                    "answer_only_optional_mean": _mean([c["answer_only_optional"] for c in okc]),
                }
    out["h7"] = h7
    # H18
    studied = [r for r in recs if r["h18"]["studied"]]
    h18: dict[str, Any] = {"items_studied": rate(len(studied), n),
                           "full_not_computed": sum(1 for r in studied if "full_not_computed_reason" in r["h18"]),
                           "steps": {}}
    seq = [str(x) for x in N_MAX_SWEEP] + ["FULL"]
    for method in ("modular", "stratified"):
        for a_label, b_label in zip(seq, seq[1:]):
            key = f"{method}|{a_label}->{b_label}"
            rows = [r["h18"]["comparisons"][key] for r in studied if key in r["h18"].get("comparisons", {})
                    and r["h18"]["comparisons"][key]["actually_bounded_at_a"]]
            both = sum(1 for x in rows if x["pre_equal"] and x["post_equal"])
            h18["steps"][key] = {
                "items_actually_bounded": len(rows),
                "pre_equal": rate(sum(1 for x in rows if x["pre_equal"]), len(rows)),
                "post_equal": rate(sum(1 for x in rows if x["post_equal"]), len(rows)),
                "both_equal": rate(both, len(rows)),
                "pre_jaccard_mean": _mean([x["pre_jaccard"] for x in rows]),
                "post_jaccard_mean": _mean([x["post_jaccard"] for x in rows]),
                "earliest_key": dict(Counter(x["earliest_key"] for x in rows if x["earliest_key"])),
            }
        for thr in (95, 99):
            best = None
            for a_label, b_label in zip(seq, seq[1:]):
                st = h18["steps"].get(f"{method}|{a_label}->{b_label}")
                if st and st["items_actually_bounded"] > 0 and (st["both_equal"]["percent"] or 0) >= thr:
                    best = a_label
                    break
            h18[f"smallest_n_max_with_{thr}pct_stability_{method}"] = best
    out["h18"] = h18
    # H6
    calls = sum(r["solver"]["calls"] for r in recs)
    secs = [s for r in recs for s in r["solver"]["call_seconds"]]
    nv = [v for r in recs for v in r["solver"]["call_vars"]]
    nr = [v for r in recs for v in r["solver"]["call_rows"]]
    status = Counter()
    for r in recs:
        status.update(r["solver"]["status_counts"])
    out["h6"] = {
        "solver": f"HiGHS via scipy.optimize.milp (scipy {scipy.__version__})",
        "calls": calls, "status_counts": dict(status), "optimal": rate(status.get("OPTIMAL", 0), calls),
        "seconds_median": _median(secs), "seconds_p90": _pctl(secs, 0.90), "seconds_p95": _pctl(secs, 0.95),
        "seconds_max": max(secs) if secs else None, "seconds_total": round(sum(secs), 2),
        "n_vars_median": _median(nv), "n_vars_p95": _pctl(nv, 0.95), "n_vars_max": max(nv) if nv else None,
        "n_rows_median": _median(nr), "n_rows_p95": _pctl(nr, 0.95), "n_rows_max": max(nr) if nr else None,
        "verification_checked": sum(r["verification"]["checked"] for r in recs),
        "verification_failed": sum(r["verification"]["failed"] for r in recs),
        "oracle": h13["oracle"],
    }
    return out


def per_item_row(r: dict, h5: Optional[dict]) -> dict:
    it = r["item"]
    pre = r["h13"]["pre"]["baseline"]
    post = r["h13"]["post"]["baseline"]
    row = {
        "item": it["key"], "batch": it["batch"], "cohort": it["cohort"], "cohort_group": it["cohort_group"],
        "answer_uri": it["answer_uri"], "display_label": it["display_label"],
        "mcq_evidence_level": it["mcq_evidence_level"], "rstar_size": r["rationale"]["size"],
        "rstar_absence_incidences": r["rationale"]["absence_incidences"],
        "rstar_fully_verbalizable": r["rationale"]["fully_verbalizable"],
        "groups": r["counts"]["groups"], "optional_groups": r["counts"].get("tier_OPTIONAL_CONTEXT", 0),
        "excluded_groups": r["counts"].get("tier_EXCLUDED", 0), "alt_showable": r["alternatives"]["showable"],
        "alt_unshowable_letters": "".join(r["alternatives"]["unshowable_letters"]),
        "mandatory_nodes": r["mandatory"]["nodes"], "index_available": r["index"]["available"],
        "measure_scope": r["measure_universe"]["scope"], "measure_bounded_size": r["measure_universe"]["bounded_size"],
    }
    for arm in ARMS:
        row[f"adm_{arm}"] = r["h14"][arm]["admissible_count"]
    row.update({
        "pre_status": pre["status"], "pre_selected": len(pre["selected"] or []),
        "post_status": post["status"], "post_selected_free": len(post.get("selected_free") or []),
        "post_entity_nodes": post.get("entity_nodes"),
        "h13_pre_swaps_changed": sum(1 for s in r["h13"]["pre"]["swaps"].values() if s["changed"]),
        "h13_post_swaps_changed": sum(1 for s in r["h13"]["post"]["swaps"].values() if s["changed"]),
        "h18_studied": r["h18"]["studied"],
        "solver_calls": r["solver"]["calls"], "solver_seconds": r["solver"]["seconds_total"],
        "verification_failed": r["verification"]["failed"],
    })
    if h5:
        row.update({"h5_kernel_replay_match": h5.get("kernel_replay_match"),
                    "h5_counterfactual": h5.get("counterfactual"),
                    "h5_unverbalizable_keys": h5.get("unverbalizable_keys")})
    return row


def _previous_measurement_script_sha256(out_dir: Path, current: str) -> str:
    """The script hash recorded when the measurements were produced, carried forward."""
    prev = out_dir / "run_manifest.json"
    if prev.is_file():
        try:
            rec = read_json(prev)
            return str(rec.get("measurement_script_sha256") or rec.get("script_sha256") or current)
        except Exception:                                               # noqa: BLE001
            return current
    return current


def stage_package(args, refs: list[ItemRef], out_dir: Path, replay_verification: dict) -> None:
    recs = [read_json(p) for p in measured_items(out_dir)]
    h5_path = out_dir / "h5_verbalizability_audit.json"
    h5rows = read_json(h5_path) if h5_path.is_file() else []
    h5_by_item = {r["item"]: r for r in h5rows}
    say(f"[package] {len(recs)} measured items, {len(h5rows)} H5 rows")
    # rollups: pooled, per cohort group, per cohort
    groups: dict[str, list[dict]] = defaultdict(list)
    h5groups: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        it = r["item"]
        for label in ("POOLED", f"GROUP:{it['cohort_group']}", f"COHORT:{it['cohort']}", f"BATCH:{it['batch']}"):
            groups[label].append(r)
            if it["key"] in h5_by_item:
                h5groups[label].append(h5_by_item[it["key"]])
    rollups = {label: rollup_group(rs, h5groups.get(label, [])) for label, rs in sorted(groups.items())}
    write_json(out_dir / "per_cohort_rollups.json", rollups)
    write_json(out_dir / "h14_admissibility_arms.json", {k: v.get("h14") for k, v in rollups.items()})
    write_json(out_dir / "h13_objective_sensitivity.json", {k: v.get("h13") for k, v in rollups.items()})
    write_json(out_dir / "h7_budget_sweep.json", {k: v.get("h7") for k, v in rollups.items()})
    write_json(out_dir / "h18_bounding_stability.json", {k: v.get("h18") for k, v in rollups.items()})
    rerun_path = out_dir / "h6_deterministic_rerun.json"
    write_json(out_dir / "h6_solver_metrics.json",
               {"pooled": rollups.get("POOLED", {}).get("h6"), "by_group": {k: v.get("h6") for k, v in rollups.items()
                                                                            if k.startswith("GROUP:")},
                "deterministic_rerun": (read_json(rerun_path) if rerun_path.is_file() else "NOT_RUN"),
                "note": "thread count is not exposed by scipy.optimize.milp; OMP_NUM_THREADS=1 was set and "
                        "HiGHS's MIP solver is deterministic for identical input; determinism is DEMONSTRATED by "
                        "the rerun comparison, not assumed"})
    # per-item CSVs
    write_csv(out_dir / "per_item_metrics.csv", [per_item_row(r, h5_by_item.get(r["item"]["key"])) for r in recs])
    arm_rows = []
    for r in recs:
        for arm in ARMS:
            a = r["h14"][arm]
            arm_rows.append({"item": r["item"]["key"], "cohort_group": r["item"]["cohort_group"], "cohort": r["item"]["cohort"],
                             "arm": arm, "optional_total": a["optional_total"], "admissible": a["admissible_count"],
                             "support2": a["by_support"].get("2", 0), "support3": a["by_support"].get("3", 0),
                             "support4": a["by_support"].get("4", 0), "mandatory_only": a["mandatory_only"],
                             "A_excluding_support3_survivors": a["A_excluding_support3_survivors"],
                             "first_failing_reasons": json.dumps(a["first_failing_reason"], sort_keys=True)})
    write_csv(out_dir / "h14_admissibility_arms.csv", arm_rows)
    swap_rows = []
    for r in recs:
        for exp in ("pre", "post"):
            for name, s in r["h13"][exp]["swaps"].items():
                swap_rows.append({"item": r["item"]["key"], "cohort_group": r["item"]["cohort_group"], "exposure": exp,
                                  "swap": name, "changed": s["changed"], "jaccard": s["jaccard"],
                                  "earliest_key": s["earliest_key"], "status": s["status"]})
    write_csv(out_dir / "h13_objective_sensitivity.csv", swap_rows)
    sweep_rows = []
    for r in recs:
        for key, c in r["h7"]["post"].items():
            bp, bpost, ka = key.split("|")
            sweep_rows.append({"item": r["item"]["key"], "cohort_group": r["item"]["cohort_group"], "B_pre": bp,
                               "B_post": bpost, "K_A_post": ka, "status": c["status"],
                               "entity_nodes": c.get("entity_nodes"), "edges": c.get("edges"),
                               "mandatory_share": c.get("mandatory_share"), "optional_groups": c.get("optional_groups"),
                               "alternative_groups": c.get("alternative_groups"),
                               "letters_without_optional": "".join(c.get("letters_without_optional", []) or []),
                               "distinct_keys": c.get("distinct_keys"), "abs_exposed": c.get("abs_incidences_exposed"),
                               "risk_groups": c.get("risk_groups_exposed"), "mandatory_only": c.get("mandatory_only"),
                               "cover_alt": json.dumps(c.get("cover_alt", {}), sort_keys=True)})
    write_csv(out_dir / "h7_budget_sweep.csv", sweep_rows)
    bound_rows = []
    for r in recs:
        if not r["h18"]["studied"]:
            continue
        for key, c in r["h18"].get("comparisons", {}).items():
            method, step = key.split("|")
            bound_rows.append({"item": r["item"]["key"], "cohort_group": r["item"]["cohort_group"],
                               "optional_total": r["h18"]["optional_total"], "method": method, "step": step,
                               "actually_bounded_at_a": c["actually_bounded_at_a"], "pre_equal": c["pre_equal"],
                               "post_equal": c["post_equal"], "pre_jaccard": c["pre_jaccard"],
                               "post_jaccard": c["post_jaccard"], "earliest_key": c["earliest_key"]})
    write_csv(out_dir / "h18_bounding_stability.csv", bound_rows)
    # item list and gate
    write_csv(out_dir / "items.csv", [asdict(r) | {"artifact_dir": str(r.artifact_dir)} for r in refs])
    gate = Counter(r.gate_reason or "GATE_PASSED" for r in refs)
    # manifest
    script = Path(__file__).resolve()
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip()
        branch = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip()
    except Exception:                                                   # noqa: BLE001
        head, branch = "", ""
    qp = load_quality_policy(PREDICATE_POLICY_PATH)
    sp = load_semantic_relation_policy(SEMANTIC_POLICY_PATH)
    manifest = {
        "task": "Prompt 8H-B3-ARCH-3 — offline decision-support measurements (DEVELOPMENT ONLY)",
        "label": "AUDIT / DECISION SUPPORT ONLY — NOT PRODUCTION B3 CODE — NOT A PUBLICATION RUN",
        "date": TODAY, "script": str(script.relative_to(REPO_ROOT)), "script_sha256": sha256_file(script),
        # When the package stage is re-run with a later version of this script (ARCH-3R re-packaging),
        # the hash of the script that PRODUCED the measurements is preserved from the previous manifest.
        "measurement_script_sha256": _previous_measurement_script_sha256(out_dir, sha256_file(script)),
        "script_version": SCRIPT_VERSION, "git_head": head, "git_branch": branch,
        "python": platform.python_version(), "platform": platform.platform(),
        "scipy": scipy.__version__, "numpy": np.__version__,
        "pinned_kg": {"path": str(PINNED_KG_PATH.relative_to(REPO_ROOT)), "sha256": PINNED_KG_SHA256},
        "quality_policy": {"path": str(PREDICATE_POLICY_PATH.relative_to(REPO_ROOT)), "version": qp.version, "sha256": qp.policy_sha256},
        "semantic_policy": {"path": str(SEMANTIC_POLICY_PATH.relative_to(REPO_ROOT)), "version": sp.version, "sha256": sp.policy_sha256,
                            "max_depth": sp.max_depth},
        "alias_policy": DEFAULT_ALIAS_POLICY.as_record(),
        "rationale_objective": RATIONALE_OBJECTIVE_V3,
        "configuration": {
            "designated": {"B_pre_groups": DESIGNATED_B_PRE, "B_post_entity_nodes": DESIGNATED_B_POST,
                           "K_A_pre": 0, "K_A_post": DESIGNATED_K_A_POST, "measure_universe": f"stratified N_max={MEASURE_N_MAX}",
                           "alternatives_pre_answer": "OFF", "alternatives_post_answer": "REQUIRED where showable",
                           "class_frame": "outside every budget (caption arm = measured; node arm = +1 node, +4 edges)"},
            "sweeps": {"B_pre": list(B_PRE_SWEEP), "B_post": list(B_POST_SWEEP), "K_A_post": list(K_A_POST_SWEEP),
                       "N_max": list(N_MAX_SWEEP), "full_universe_cap": FULL_UNIVERSE_CAP},
            "strata": {"k_per_key": STRATA_K_KEY, "k_per_letter": STRATA_K_LETTER},
            "pre_keys": list(PRE_KEYS), "post_keys": list(POST_KEYS),
            "oracle_max_free_groups": ORACLE_MAX_FREE, "canonical_block": CANONICAL_BLOCK,
            "arch1_weights_for_comparator": ARCH1_WEIGHTS, "milp": {"mip_rel_gap": 0.0, "time_limit": MILP_TIME_LIMIT,
                                                                     "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS")},
            "arms": list(ARMS),
        },
        "cohort_group_rule": "CHEMISTRY if 'CHEMISTRY' in cohort label; EVENT if 'EVENTS'; PLACE if 'PLACES'; POLITY if 'POLITIES'; else PERSON (evaluation metadata only)",
        "items": {"total_rows": len(refs), "gate": dict(gate), "measured": len(recs), "h5_audited": len(h5rows)},
        "replay_verification": replay_verification,
        "replay_commands": [
            "python scripts/run_phase_b2_any_answer_v4.py --input data/Answers.txt --offline-replay "
            "--output-report <E>/v4_offline_replay/answers/report.md --metrics-json <E>/v4_offline_replay/answers/metrics.json "
            "--metrics-csv <E>/v4_offline_replay/answers/metrics.csv --artifacts-dir <E>/v4_offline_replay/answers/artifacts "
            "--member-cache <E>/v4_offline_replay/caches/phase_b2_class_members_v1.sqlite "
            "--score-cache <E>/v4_offline_replay/caches/phase_b2_graph_lrolesim_v1.jsonl "
            "--sparql-cache <E>/v4_offline_replay/caches/category_v6_sparql.sqlite "
            "--wikipedia-cache <E>/v4_offline_replay/caches/category_v6_wikipedia_leads.json "
            "--semantic-index-root <E>/v4_offline_replay/answers/semantic_index",
            "(same for data/Answers_HISTORICAL_EVENTS_PLACES.txt into <E>/v4_offline_replay/hist)"],
        "network": "none; --offline-replay raises on any cache miss; the pinned KG is opened read-only",
        "upstream_untouched": ["selected Answer", "selected class", "selected distractors", "frozen LRoleSim ranks/scores",
                               "frozen evidence levels", "frozen R*", "every open-world rule", "all v1-v4 outputs and caches"],
        "limitations": [
            "development measurements only; no cohort here is a benchmark cohort and no number is publication-final",
            "the B3 grounding of distractor-owned groups is computed by THIS audit's rule with THIS audit's index; "
            "its agreement with the frozen classifier is measured on Answer-owned pairs (universe.grounding_rule_vs_frozen_level)",
            "H13/H7 solve on the stratified universe bounded at N_max=400; H18 measures what bounding does",
            "structural proxies are never human difficulty; a missing edge is never falsity",
        ],
    }
    write_json(out_dir / "run_manifest.json", manifest)
    (out_dir / "REPRODUCE.md").write_text(REPRODUCE_TEXT, encoding="utf-8")
    # --- the content manifest and the archive (Prompt 8H-B3-ARCH-3R §A protocol) -----------------
    package = build_package(out_dir, out_dir.parent / f"{out_dir.name}.zip", zip_max_mb=args.zip_max_mb)
    say(f"[package] zip -> {package['archive']} ({package['archive_bytes'] / 1e6:.1f} MB), "
        f"testzip -> {package['testzip_first_bad']!r}, entries {package['zip_entries']}, "
        f"{package['excluded_regular_files']} files kept on disk only, external digest verified = "
        f"{package['external_digest_verified']}")


CONTENT_MANIFEST_NAME = "CONTENT_MANIFEST.json"
MANIFEST_FILES = (CONTENT_MANIFEST_NAME, "SHA256SUMS.txt", "SHA256SUMS.csv")
STALE_PACKAGE_FILES = ("zip_manifest.json",)          # written AFTER the archive by the ARCH-3 protocol; never again


def build_package(out_dir: Path, zip_path: Path, *, zip_max_mb: int,
                  exclude_dir_parts: Sequence[str] = ("caches",)) -> dict:
    """Package an evidence directory under the corrected protocol (ARCH-3R §A).

    ORDER OF OPERATIONS — the whole point of the repair:
      1. remove every artefact of an earlier package run that must not survive:
         the previous archive and its external digest, the stale post-archive
         manifest (`zip_manifest.json`) and the previous content-manifest files;
      2. enumerate the REGULAR files of the directory (the content manifest files
         themselves excluded), digest each, decide `in_zip` by size and by the
         excluded directory parts;
      3. write the CONTENT_MANIFEST (`CONTENT_MANIFEST.json`, `SHA256SUMS.txt`,
         `SHA256SUMS.csv`) — finalized BEFORE the archive exists, so the copy
         inside the archive is the final one. It never contains the archive's
         own digest: an archive cannot contain its own SHA-256;
      4. build the archive in deterministic path order (no directory entries);
      5. close it, run `testzip()`, compute the ARCHIVE_DIGEST and write it ONLY
         to the external `<archive>.sha256`; re-read the archive and verify the
         digest and the entry count against the manifest.
    The numbers reported are consistent by construction:
      zip_entries == regular_files_in_zip + len(MANIFEST_FILES), directory_entries == 0.
    """
    zip_path = Path(zip_path)
    digest_path = zip_path.parent / f"{zip_path.name}.sha256"
    # 1. stale artefacts
    for stale in (zip_path, digest_path):
        if stale.exists():
            stale.unlink()
    for name in STALE_PACKAGE_FILES + MANIFEST_FILES:
        f = out_dir / name
        if f.exists():
            f.unlink()
    # 2. regular files
    regular = sorted(p for p in out_dir.rglob("*") if p.is_file())
    entries, excluded = [], []
    for p in regular:
        rel = p.relative_to(out_dir)
        size = p.stat().st_size
        reasons = []
        if size > zip_max_mb * 1024 * 1024:
            reasons.append(f"size>{zip_max_mb}MB")
        if any(part in exclude_dir_parts for part in rel.parts):
            reasons.append("excluded_directory")
        entry = {"path": str(rel), "sha256": sha256_file(p), "size": size, "in_zip": not reasons,
                 "exclusion_reason": ";".join(reasons)}
        entries.append(entry)
        if reasons:
            excluded.append(entry["path"])
    in_zip = [e for e in entries if e["in_zip"]]
    # 3. the content manifest — written before the archive, never containing the archive digest
    sums_txt = "".join(f"{e['sha256']}  {e['path']}\n" for e in entries)
    (out_dir / "SHA256SUMS.txt").write_text(sums_txt, encoding="utf-8")
    write_csv(out_dir / "SHA256SUMS.csv", entries, ["path", "sha256", "size", "in_zip", "exclusion_reason"])
    manifest = {
        "kind": "CONTENT_MANIFEST",
        "note": ("Finalized before the archive was built; the archive's own SHA-256 (ARCHIVE_DIGEST) lives "
                 "ONLY in the external <archive>.sha256 file, never inside the archive."),
        "protocol": "8H-B3-ARCH-3R/A: manifest -> archive -> testzip -> external digest",
        "archive_name": zip_path.name,
        "regular_files_total": len(entries),
        "regular_files_in_zip": len(in_zip),
        "excluded_regular_files": len(excluded),
        "excluded_paths": excluded,
        "manifest_files_added_to_zip": list(MANIFEST_FILES),
        "directory_entries_in_zip": 0,
        "zip_entries_expected": len(in_zip) + len(MANIFEST_FILES),
        "sha256sums_txt_sha256": hashlib.sha256(sums_txt.encode("utf-8")).hexdigest(),
        "files": entries,
    }
    write_json(out_dir / CONTENT_MANIFEST_NAME, manifest)
    # 4. the archive, deterministic order, no directory entries
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for e in in_zip:
            zf.write(out_dir / e["path"], arcname=str(Path(out_dir.name) / e["path"]))
        for name in MANIFEST_FILES:
            zf.write(out_dir / name, arcname=str(Path(out_dir.name) / name))
    # 5. testzip, external ARCHIVE_DIGEST, verification
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        names = zf.namelist()
    archive_digest = sha256_file(zip_path)
    digest_path.write_text(f"{archive_digest}  {zip_path.name}\n", encoding="utf-8")
    verified = (digest_path.read_text(encoding="utf-8").split()[0] == sha256_file(zip_path))
    return {
        "kind": "ARCHIVE_DIGEST",
        "archive": str(zip_path), "archive_bytes": zip_path.stat().st_size, "archive_sha256": archive_digest,
        "external_digest_file": str(digest_path), "external_digest_verified": verified,
        "testzip_first_bad": bad, "zip_entries": len(names),
        "zip_entries_expected": manifest["zip_entries_expected"],
        "entries_consistent": len(names) == manifest["zip_entries_expected"],
        "regular_files_total": len(entries), "regular_files_in_zip": len(in_zip),
        "excluded_regular_files": len(excluded), "directory_entries_in_zip": 0,
        "content_manifest": str(out_dir / CONTENT_MANIFEST_NAME),
    }

REPRODUCE_TEXT = """# Reproduction — B3 decision-support measurements (DEVELOPMENT ONLY)

All commands run from the repository root inside the `mcq-journal2` conda
environment, offline (`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`).

```bash
E=outputs/journal2_b3_decision_support_2026-09-18
# 1. private copies of the four offline caches (the originals are never opened for writing)
mkdir -p $E/v4_offline_replay/caches
cp data/cache/phase_b2_class_members_v1.sqlite data/cache/phase_b2_graph_lrolesim_v1.jsonl \\
   cache/category_v6_sparql.sqlite cache/category_v6_wikipedia_leads.json $E/v4_offline_replay/caches/
# 2. offline replay of the two 2026-09-18 development batches (see run_manifest.json: replay_commands)
# 3. the audit, stage by stage
python scripts/audit_b3_choice_evidence_decisions.py --stage verify
python scripts/audit_b3_choice_evidence_decisions.py --stage universe
python scripts/audit_b3_choice_evidence_decisions.py --stage h5
python scripts/audit_b3_choice_evidence_decisions.py --stage measure --workers 12
python scripts/audit_b3_choice_evidence_decisions.py --stage rerun
python scripts/audit_b3_choice_evidence_decisions.py --stage package
```

Each stage is idempotent: it skips items whose output already exists. Delete
`universe/`, `measure/` or `rerun/` to recompute. `--limit N` and `--only TEXT`
restrict the item set for a quick check.
"""


# ==========================================================================
# 9) MAIN
# ==========================================================================

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="AUDIT / DECISION SUPPORT ONLY — NOT PRODUCTION B3 CODE. Offline development-batch "
                    "measurements for the B3 human decisions H5/H6/H7/H13/H14/H18.")
    parser.add_argument("--stage", choices=("verify", "universe", "h5", "measure", "rerun", "package", "all"), default="all")
    parser.add_argument("--evidence-dir", default=str(REPO_ROOT / "outputs" / "journal2_b3_decision_support_2026-09-18"))
    parser.add_argument("--replay-root", default=None, help="default: <evidence-dir>/v4_offline_replay")
    parser.add_argument("--original-answers-report", default=str(REPO_ROOT / "outputs" / "Results_Answers.txt_v4_2026-09-18"))
    parser.add_argument("--original-hist-report",
                        default=str(REPO_ROOT / "outputs" / "Results_Answers_HISTORICAL_EVENTS_PLACES.txt_v4_2026-09-18"))
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--limit", type=int, default=None, help="only the first N gated items (quick check)")
    parser.add_argument("--only", default=None, help="only items whose key contains this text")
    parser.add_argument("--rerun-sample", type=int, default=40)
    parser.add_argument("--zip-max-mb", type=int, default=20)
    args = parser.parse_args(argv)

    out_dir = Path(args.evidence_dir)
    replay_root = Path(args.replay_root) if args.replay_root else out_dir / "v4_offline_replay"
    out_dir.mkdir(parents=True, exist_ok=True)
    refs = list_items(replay_root)
    if args.only:
        refs = [r for r in refs if args.only in item_key(r)]
    if args.limit:
        gated = [r for r in refs if r.gate_passed][:args.limit]
        keep = {item_key(r) for r in gated}
        refs = [r for r in refs if item_key(r) in keep]
    say(f"[items] {len(refs)} rows; gated {sum(1 for r in refs if r.gate_passed)}; "
        f"gate reasons {dict(Counter(r.gate_reason for r in refs if not r.gate_passed))}")
    stages = ("verify", "universe", "h5", "measure", "rerun", "package") if args.stage == "all" else (args.stage,)
    verification = {}
    if "verify" in stages or "package" in stages:
        verification = verify_replay(replay_root, {"answers": Path(args.original_answers_report),
                                                   "hist": Path(args.original_hist_report)}, out_dir)
        say(f"[verify] {json.dumps(verification)}")
    if "universe" in stages:
        stage_universe(args, refs, out_dir)
    if "h5" in stages:
        stage_h5(args, refs, out_dir)
    if "measure" in stages:
        stage_measure(args, refs, out_dir)
    if "rerun" in stages:
        stage_rerun(args, refs, out_dir)
    if "package" in stages:
        stage_package(args, refs, out_dir, verification)
    return 0


if __name__ == "__main__":
    sys.exit(main())
