#!/usr/bin/env python
############################################################################
# scripts/audit_b3_pre_freeze_resolution.py
#
#   AUDIT / DECISION SUPPORT ONLY — NOT PRODUCTION B3 CODE.
#
# Prompt 8H-B3-ARCH-3R (2026-09-19): the targeted follow-up to ARCH-3 that
# resolves the pre-freeze blockers with DEVELOPMENT measurements only:
#
#   B  template-candidate audit (corpus-wide pinned-KG census + candidate file)
#   C  counterfactual template coverage T0 / T1 / T2 on the frozen selections
#   D  H7 nested-infeasibility repair: N1 (node-aware pre, absolute cap) vs N2
#   E  H4 K_A_post = 0 vs 1 under N1
#   F  H18 extension on the hard (IN-heavy) items only
#   package  the corrected packaging protocol for the new evidence directory
#
# It REUSES the ARCH-3 audit module (`scripts/audit_b3_choice_evidence_decisions.py`)
# for the universe files, the prepared views, the exact 0-1 solver wrapper,
# the lexicographic protocol, the key vectors and the bounding rules, so every
# number here is computed by the same audited code path as ARCH-3.
#
# NOTHING UPSTREAM CHANGES: the selected Answer, class, distractor triple,
# LRoleSim ranks/scores, evidence levels and R* are read from the ARCH-3
# universes (themselves read from the replayed v4 artefacts). No production
# template registry is edited; T1/T2 are COUNTERFACTUAL template sets applied
# in memory. No network access. The pinned KG is opened read-only (census only).
############################################################################
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
SCRIPTS = REPO_ROOT / "scripts"


def _load_arch3():
    """Import the ARCH-3 audit module by path, registered in sys.modules so its
    dataclasses resolve (a bare exec_module breaks `dataclass`)."""
    name = "audit_b3_choice_evidence_decisions"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


A3 = _load_arch3()
import numpy as np                                            # noqa: E402
import scipy                                                  # noqa: E402
from rationale_v3.quality import load_quality_policy, display_label   # noqa: E402
from rationale_v3.semantic_relations import normalize_uri     # noqa: E402

TODAY = "2026-09-19"
SCRIPT_VERSION = "audit_b3_pre_freeze_resolution/1.0.0-development-only"
ARCH3_DIR = REPO_ROOT / "outputs" / "journal2_b3_decision_support_2026-09-18"
OUT_DIR_DEFAULT = REPO_ROOT / "outputs" / "journal2_b3_pre_freeze_resolution_2026-09-19"
P = "http://dbpedia.org/property/"
LETTERS = A3.LETTERS

# --- the five highest-impact keys measured by ARCH-3 (H5 histogram) ---
HIGH_IMPACT_KEYS = (("birthPlace", "IN"), ("products", "IN"), ("battles", "IN"),
                    ("deathPlace", "IN"), ("settlementType", "OUT"))

# --- analysis configuration (ARCH-3R §H provisional set; NOT signed decisions) ---
PRE_ARM = "C_no_A_excluding_support3"      # H14 safety candidate for the pre-answer solves
B_PRE_SWEEP = (2, 3, 4, 5, 6)
N1_B_POST_SWEEP = (6, 7, 8, 9, 10)
N2_K_SWEEP = (2, 3, 4, 5, 6)
DESIGNATED_B_PRE, DESIGNATED_B_POST = 4, 7
MEASURE_N_MAX = A3.MEASURE_N_MAX                 # stratified 400, as in ARCH-3
H18_EXT_N_MAX = (800, 1600, 3200)
H18_EXT_MIN_OPTIONAL = 800                       # only items with more than this many optional groups
CENSUS_EXAMPLES_PER_KEY = 8
CENSUS_TOP_VALUES = 12


def say(msg: str) -> None:
    print(msg, flush=True)


def key_str(p: str, d: str) -> str:
    return f"{p.rsplit('/', 1)[-1]}/{d}"


# ==========================================================================
# B) TEMPLATE-CANDIDATE CENSUS — corpus-wide, pinned KG read-only
# ==========================================================================

def candidate_keys_from_universes(arch3_dir: Path) -> dict:
    """Which predicate-direction keys matter, measured on the ARCH-3 universes.

    Three sources, all counted with their denominators:
      (a) keys of template-less facts inside the FROZEN selected R*;
      (b) keys of shared (support >= 2, not Answer-only) optional groups that
          have no template;
      (c) keys of optional groups that pass every arm-C rule EXCEPT the
          template rule — the groups a template would unlock as pre-answer
          context — with the number of ITEMS that would gain >= 1 such group.
    """
    rstar = Counter(); shared = Counter(); unlock_groups = Counter(); unlock_items = defaultdict(set)
    for up in sorted((arch3_dir / "universe").glob("*.json.gz")):
        u = A3.read_json(up)
        item = u["item"]["key"]; grp = u["item"]["cohort_group"]
        for f in u["rationale"]["facts"]:
            if not f["verbalizable"]:
                rstar[key_str(f["predicate_uri"], f["direction"])] += 1
        for g in u["groups"]:
            if g["tier"] != A3.T_OPT:
                continue
            a = g["attrs"]
            if a["s"] < 2 or a["a"] == 1 or a["verb"] == 1:
                continue
            for p, d in g["raw_keys"]:
                shared[key_str(p, d)] += 1
            ok, failed = A3.arm_admissible(PRE_ARM, g)
            if failed == ["UNVERBALIZABLE"]:
                for p, d in g["raw_keys"]:
                    k = key_str(p, d)
                    unlock_groups[k] += 1
                    unlock_items[k].add((item, grp))
    return {"rstar_unverbalizable_fact_keys": dict(rstar.most_common()),
            "shared_unverbalizable_optional_groups_by_key": dict(shared.most_common()),
            "unlock_groups_by_key": dict(unlock_groups.most_common()),
            "unlock_items_by_key": {k: {"items": len(v), "by_group": dict(Counter(g for _, g in v))}
                                    for k, v in unlock_items.items()}}


def select_census_keys(census_src: dict, *, min_rstar_facts: int = 1, min_unlock_items: int = 2,
                       min_shared_groups: int = 20) -> list[tuple[str, str]]:
    """The keys the corpus census looks at: every key of a template-less R*
    fact, every key that would unlock >= min_unlock_items items, and every key
    with >= min_shared_groups shared unverbalizable optional groups; plus the
    five ARCH-3 high-impact keys."""
    keys: set[tuple[str, str]] = set(HIGH_IMPACT_KEYS)
    for k, n in census_src["rstar_unverbalizable_fact_keys"].items():
        if n >= min_rstar_facts:
            keys.add(tuple(k.split("/")))
    for k, v in census_src["unlock_items_by_key"].items():
        if v["items"] >= min_unlock_items:
            keys.add(tuple(k.split("/")))
    for k, n in census_src["shared_unverbalizable_optional_groups_by_key"].items():
        if n >= min_shared_groups:
            keys.add(tuple(k.split("/")))
    return sorted(keys)


def stage_census(args, out_dir: Path) -> None:
    """Corpus-wide census of the candidate keys over the pinned KG.

    For every candidate predicate: number of edges, distinct subjects, distinct
    objects, the most frequent objects (to see whether the slot holds VALUES or
    LAYOUT LABELS), the share of object values that are resources of the
    pinned KG, and deterministic example triples (first-by-subject-index, so
    the sample is reproducible and not cherry-picked). Both directions are read
    from the same edges. Nothing is written to the KG.
    """
    src = candidate_keys_from_universes(ARCH3_DIR)
    keys = select_census_keys(src)
    A3.write_json(out_dir / "template_candidate_key_sources.json", {"sources": src, "census_keys": [list(k) for k in keys]})
    say(f"[census] {len(keys)} candidate keys: {', '.join('/'.join(k) for k in keys)}")
    from kg.loader import load_local_kg
    t0 = time.time()
    kg = load_local_kg(A3.PINNED_KG_PATH, verify_sha256=A3.PINNED_KG_SHA256)
    say(f"[census] KG loaded in {time.time() - t0:.1f}s; scanning every subject's out-edges once ...")
    import mcq_inputs as mi
    pred_index = {}
    for p, d in keys:
        idx = mi.node_index_or_none(P + p, kg)
        if idx is not None:
            pred_index[idx] = p
    stats = {p: {"edges": 0, "subjects": set(), "objects": Counter(), "examples": []} for p in {p for p, _ in keys}}
    t1 = time.time()
    for subj, edges in kg.out_neighbor.items():
        for pi, oi in edges:
            p = pred_index.get(pi)
            if p is None:
                continue
            st = stats[p]
            st["edges"] += 1
            st["subjects"].add(subj)
            st["objects"][oi] += 1
            if len(st["examples"]) < CENSUS_EXAMPLES_PER_KEY * 4:
                st["examples"].append((subj, oi))
    say(f"[census] scan done in {time.time() - t1:.1f}s")

    def plain(i: int) -> str:
        raw = kg.index_url.get(i)
        return normalize_uri(raw) if raw else f"<index {i}>"

    out = {}
    for p, st in stats.items():
        objs = st["objects"]
        top = [(plain(o), n) for o, n in objs.most_common(CENSUS_TOP_VALUES)]
        resource_share = (sum(n for o, n in objs.items() if plain(o).startswith("http://dbpedia.org/resource/"))
                          / st["edges"]) if st["edges"] else None
        # deterministic examples: the lowest subject indices, spread over distinct objects
        seen_o = set(); examples = []
        for subj, oi in sorted(st["examples"]):
            if oi in seen_o and len(examples) >= 3:
                continue
            seen_o.add(oi)
            examples.append({"subject": plain(subj), "object": plain(oi),
                             "subject_label": display_label(plain(subj)), "object_label": display_label(plain(oi))})
            if len(examples) >= CENSUS_EXAMPLES_PER_KEY:
                break
        out[p] = {"predicate_uri": P + p, "edges": st["edges"], "distinct_subjects": len(st["subjects"]),
                  "distinct_objects": len(objs), "resource_object_share": round(resource_share, 4) if resource_share is not None else None,
                  "top_objects": [{"object": o, "label": display_label(o), "count": n} for o, n in top],
                  "examples": examples}
    A3.write_json(out_dir / "template_candidate_census.json",
                  {"pinned_kg_sha256": A3.PINNED_KG_SHA256, "keys": [list(k) for k in keys], "predicates": out})
    say(f"[census] wrote {len(out)} predicate records")


# ==========================================================================
# B/C) TEMPLATE SETS — T0 (production), T1 (high-impact SAFE), T2 (all SAFE)
# ==========================================================================

def load_template_candidates(path: Path) -> dict:
    """The versioned candidate file written by hand for this task (see the
    expansion plan). It is NOT the production registry and is never written
    into `predicate_policy_v2.json`."""
    return A3.read_json(path)


def template_sets(cands: dict) -> dict[str, frozenset]:
    """T1 = SAFE_TO_TEMPLATE candidates among the five high-impact keys;
    T2 = every SAFE_TO_TEMPLATE candidate. Both are sets of (predicate_uri, direction)."""
    safe = {(c["predicate_uri"], c["direction"]) for c in cands["candidates"] if c["eligibility"] == "SAFE_TO_TEMPLATE"}
    high = {(P + p, d) for p, d in HIGH_IMPACT_KEYS}
    return {"T0": frozenset(), "T1": frozenset(safe & high), "T2": frozenset(safe)}


def apply_template_set(uni: dict, extra: frozenset) -> dict:
    """Return a COPY of a universe in which `attrs.verb` of every group and the
    `verbalizable` flag of every R* fact are recomputed as
    `production template exists OR key in extra`. Nothing else changes: the
    frozen levels, R*, distractors, grounding and every other attribute are
    untouched. This is the whole counterfactual: templates are the only lever."""
    u = json.loads(json.dumps(uni))
    for g in u["groups"]:
        if g["attrs"]["verb"] == 0:
            if all((p, d) in extra for p, d in (tuple(k) for k in g["raw_keys"])):
                g["attrs"]["verb"] = 1
    for f in u["rationale"]["facts"]:
        if not f["verbalizable"] and (f["predicate_uri"], f["direction"]) in extra:
            f["verbalizable"] = True
    u["rationale"]["fully_verbalizable"] = all(f["verbalizable"] for f in u["rationale"]["facts"])
    return u


def stage_coverage(args, out_dir: Path) -> None:
    """C) the primary counterfactual: T0/T1/T2 on the FROZEN selections."""
    cands = load_template_candidates(out_dir / "template_candidates_v1.json")
    sets = template_sets(cands)
    rows = []
    unresolved = {t: Counter() for t in sets}
    for up in sorted((ARCH3_DIR / "universe").glob("*.json.gz")):
        base = A3.read_json(up)
        row = {"item": base["item"]["key"], "batch": base["item"]["batch"], "cohort": base["item"]["cohort"],
               "cohort_group": base["item"]["cohort_group"], "rstar_size": len(base["rationale"]["facts"])}
        for t, extra in sets.items():
            u = apply_template_set(base, extra)
            row[f"{t}_rstar_fully_verbalizable"] = u["rationale"]["fully_verbalizable"]
            row[f"{t}_rstar_unverbalizable_facts"] = sum(1 for f in u["rationale"]["facts"] if not f["verbalizable"])
            for f in u["rationale"]["facts"]:
                if not f["verbalizable"]:
                    unresolved[t][key_str(f["predicate_uri"], f["direction"])] += 1
            opt = [g for g in u["groups"] if g["tier"] == A3.T_OPT]
            for arm in ("A_arch1_penalty", "B_arch2_hard", "C_no_A_excluding_support3"):
                adm = [g for g in opt if A3.arm_admissible(arm, g)[0]]
                short = {"A_arch1_penalty": "A", "B_arch2_hard": "B", "C_no_A_excluding_support3": "C"}[arm]
                row[f"{t}_arm{short}_admissible"] = len(adm)
                row[f"{t}_arm{short}_by_support"] = json.dumps(dict(Counter(str(g["attrs"]["s"]) for g in adm)), sort_keys=True)
        rows.append(row)
    A3.write_csv(out_dir / "template_coverage_T0_T1_T2.csv", rows)
    # rollups with denominators, pooled + per cohort group + per batch
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        for label in ("POOLED", f"GROUP:{r['cohort_group']}", f"BATCH:{r['batch']}", f"COHORT:{r['cohort']}"):
            groups[label].append(r)
    roll = {}
    for label, rs in sorted(groups.items()):
        n = len(rs)
        rec = {"items": n}
        for t in sets:
            fv = sum(1 for r in rs if r[f"{t}_rstar_fully_verbalizable"])
            rec[t] = {
                "rstar_fully_verbalizable": A3.rate(fv, n),
                "recovered_vs_T0": A3.rate(sum(1 for r in rs if r[f"{t}_rstar_fully_verbalizable"] and not r["T0_rstar_fully_verbalizable"]), n),
                "unresolved_rstar_facts": sum(r[f"{t}_rstar_unverbalizable_facts"] for r in rs),
                "items_with_unresolved_rstar_fact": A3.rate(sum(1 for r in rs if r[f"{t}_rstar_unverbalizable_facts"] > 0), n),
            }
            for short in ("A", "B", "C"):
                adm = [r[f"{t}_arm{short}_admissible"] for r in rs]
                rec[t][f"arm{short}"] = {
                    "items_ge1": A3.rate(sum(1 for a in adm if a >= 1), n),
                    "items_ge2": A3.rate(sum(1 for a in adm if a >= 2), n),
                    "items_ge3": A3.rate(sum(1 for a in adm if a >= 3), n),
                    "mandatory_only": A3.rate(sum(1 for a in adm if a == 0), n),
                    "admissible_mean": A3._mean(adm), "admissible_median": A3._median(adm),
                    "admissible_total": sum(adm),
                }
        roll[label] = rec
    A3.write_json(out_dir / "template_coverage_rollup.json",
                  {"template_sets": {t: sorted(f"{key_str(p, d)}" for p, d in v) for t, v in sets.items()},
                   "unresolved_rstar_keys_by_set": {t: dict(c.most_common()) for t, c in unresolved.items()},
                   "rollup": roll})
    say(f"[coverage] {len(rows)} items; T1 keys {len(sets['T1'])}, T2 keys {len(sets['T2'])}")


# ==========================================================================
# C-secondary) require-verbalizable re-selection under T2 (kept separate)
# ==========================================================================

def stage_coverage_secondary(args, out_dir: Path) -> None:
    """What an UPSTREAM require-verbalizable policy would do under T2, for the
    items whose frozen R* is still not fully verbalizable under T2. Uses the
    frozen kernel through the ARCH-3 counterfactual with the T2 flags patched
    into the FactQuality records (nothing else changes). Time-budgeted;
    timeouts are recorded outcomes. This is SECONDARY: the primary path never
    lets verbalizability change the frozen distractor triple."""
    cands = load_template_candidates(out_dir / "template_candidates_v1.json")
    t2 = template_sets(cands)["T2"]
    cov = list(csv.DictReader(open(out_dir / "template_coverage_T0_T1_T2.csv", encoding="utf-8")))
    todo = {r["item"] for r in cov if r["T2_rstar_fully_verbalizable"] == "False"}
    refs = [r for r in A3.list_items(ARCH3_DIR / "v4_offline_replay") if r.gate_passed and A3.item_key(r) in todo]
    say(f"[coverage-secondary] {len(refs)} items still not fully verbalizable under T2; kernel counterfactual with {args.workers} workers")
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(_h5_under_t2, ref, sorted(t2)): ref for ref in refs}
        for i, fut in enumerate(as_completed(futs), 1):
            rows.append(fut.result())
            if i % 10 == 0:
                say(f"  [coverage-secondary] {i}/{len(refs)}")
    rows.sort(key=lambda r: r["item"])
    A3.write_json(out_dir / "template_coverage_secondary_T2_reselection.json", rows)
    A3.write_csv(out_dir / "template_coverage_secondary_T2_reselection.csv",
                 [{k: (";".join(map(str, v)) if isinstance(v, list) else v) for k, v in r.items()} for r in rows])
    say(f"[coverage-secondary] outcomes: {dict(Counter(r.get('counterfactual') for r in rows))}")


def _h5_under_t2(ref, t2_keys: list) -> dict:
    """Worker: the ARCH-3 H5 audit with the T2 template set patched in."""
    import mcq_core
    from mcq_core import AnswerFact, FactQuality as KFQ, build_case
    t2 = {tuple(k) for k in t2_keys}
    qp = load_quality_policy(A3.PREDICATE_POLICY_PATH)
    try:
        case, info = A3.kernel_case_from_artifacts(ref, qp)
        facts = []
        for f in case.facts:
            q = f.quality
            verb = q.verbalizable or ((q.predicate_uri, q.direction) in t2)
            facts.append(AnswerFact(quality=KFQ(**{**q.__dict__, "verbalizable": verb}),
                                    levels=f.levels, exclusion_bases=f.exclusion_bases,
                                    granularity_risks=f.granularity_risks))
        case2 = build_case(case.answer_uri, case.display_label, case.candidates, facts)
        sel = info["selection"]
        rec = {"item": A3.item_key(ref), "cohort_group": ref.cohort_group}
        done, base = A3.with_time_budget(A3.H5_KERNEL_TIME_BUDGET_S,
                                         lambda: A3.select_distractors(case2, objective=A3.RATIONALE_OBJECTIVE_V3))
        if not done or base is None:
            rec["counterfactual"] = "KERNEL_REPLAY_NOT_COMPUTED_TIMEOUT"
            return rec
        recorded_d = tuple(d["candidate_uri"] for d in sel["distractors"])
        rec["kernel_replay_match_under_T2"] = tuple(d.uri for d in base.distractors) == recorded_d
        rec["baseline_unverbalizable_under_T2"] = base.rationale.unverbalizable_fact_count
        if base.rationale.unverbalizable_fact_count == 0:
            rec["counterfactual"] = "BASELINE_VERBALIZABLE_UNDER_T2"
            return rec
        done, alt = A3.with_time_budget(
            A3.H5_CALL_TIME_BUDGET_S,
            lambda: A3.select_with_rationale_filter(case2, objective=A3.RATIONALE_OBJECTIVE_V3,
                                                    admissible=lambda _c, _p, r: r.unverbalizable_fact_count == 0))
        if not done:
            rec["counterfactual"] = "COUNTERFACTUAL_NOT_COMPUTED_TIMEOUT"
        elif alt is None or mcq_core.LEVEL_STRENGTH[mcq_core.POLICY_THRESHOLD[alt.evidence_policy]] < \
                mcq_core.LEVEL_STRENGTH[mcq_core.POLICY_THRESHOLD[base.evidence_policy]]:
            rec["counterfactual"] = "NO_FULLY_VERBALIZABLE_MIN_CARD_SOLUTION_AT_SAME_POLICY"
        else:
            changed = tuple(d.uri for d in alt.distractors) != recorded_d
            rec["counterfactual"] = "ALTERNATIVE_DISTRACTORS_CHANGE" if changed else "ALTERNATIVE_RATIONALE_ONLY"
            rec["alt_rstar_size"] = len(alt.rationale.fact_indices)
            rec["alt_rstar_grew"] = len(alt.rationale.fact_indices) > len(base.rationale.fact_indices)
        return rec
    except Exception as exc:                                        # noqa: BLE001
        return {"item": A3.item_key(ref), "cohort_group": ref.cohort_group, "counterfactual": f"ERROR {exc!r}"}


# ==========================================================================
# D/E) N1 — node-aware pre selection under an ABSOLUTE ENTITY-node cap; N2 — relative cap
# ==========================================================================

def min_alternative_footprint(prep) -> int:
    """The smallest number of DISTINCT right nodes (outside the mandatory R*
    nodes) that satisfies COVER_ALT for every distractor that has a showable
    alternative — the immutable part of the post-answer mandatory core beyond
    R*. Brute force over node subsets of size 0..3 (at most three letters)."""
    letters = [L for L in LETTERS[1:] if prep.alt_by_letter.get(L)]
    if not letters:
        return 0
    nodes_by_letter = {L: {prep.groups[g]["node"] for g in prep.alt_by_letter[L]} for L in letters}
    universe = sorted(set().union(*nodes_by_letter.values()) - set(prep.mandatory_nodes))
    free_cover = {L for L in letters if nodes_by_letter[L] & set(prep.mandatory_nodes)}   # covered by an R* node already
    need = [L for L in letters if L not in free_cover]
    if not need:
        return 0
    import itertools
    for k in range(1, len(need) + 1):
        for combo in itertools.combinations(universe, k):
            if all(nodes_by_letter[L] & set(combo) for L in need):
                return k
    return len(need)


def solve_pre_node_aware(prep, admissible: Sequence[str], b_pre: int, b_post: int, key_order: Sequence[int],
                         tag: str = "n1_pre") -> dict:
    """N1: the ARCH-2 pre-answer selection with ONE extra hard constraint —

        |ENTITY_NODES(S_pre ∪ M_post)| <= B_post

    where M_post is the immutable post-answer mandatory footprint: the R* nodes
    plus, for every distractor with a showable alternative, at least one
    alternative node (COVER_ALT). The alternative groups enter the model as
    feasibility WITNESSES (binary w_g under COVER_ALT) that share the node
    variables with the pre groups but take no part in any key, so the pre keys
    are exactly ARCH-2's and a pre clue can never make the post graph infeasible.
    """
    rec: dict[str, Any] = {"b_pre": b_pre, "b_post": b_post, "key_order": list(key_order),
                           "admissible_count": len(admissible), "mode": "N1_node_aware"}
    n_mand = len(prep.mandatory_nodes)
    if n_mand + min_alternative_footprint(prep) > b_post:
        rec.update({"status": "CE_MANDATORY_CORE_TOO_LARGE", "selected": [], "key_values": None, "solver_used": False,
                    "mandatory_core_nodes": n_mand + min_alternative_footprint(prep)})
        return rec
    m = A3.Milp(tag)
    z = {gid: m.var() for gid in admissible}
    w = {gid: m.var() for gid in prep.alt_showable}
    nodes_free = sorted(({prep.groups[g]["node"] for g in admissible} | {prep.groups[g]["node"] for g in prep.alt_showable})
                        - prep.mandatory_nodes)
    y = {o: m.var() for o in nodes_free}
    letters_free = [L for L in LETTERS if L not in prep.mandatory_letters]
    u = {L: m.var() for L in letters_free}
    keys_free = sorted({tuple(prep.groups[g]["key"]) for g in admissible} - prep.mandatory_keys)
    v = {k: m.var() for k in keys_free}
    if admissible:
        m.row({z[g]: 1.0 for g in admissible}, 0, b_pre)
    for g in admissible:
        o = prep.groups[g]["node"]
        if o in y:
            m.row({y[o]: 1.0, z[g]: -1.0}, 0, math.inf)
    for g in prep.alt_showable:
        o = prep.groups[g]["node"]
        if o in y:
            m.row({y[o]: 1.0, w[g]: -1.0}, 0, math.inf)
    for L in LETTERS[1:]:
        alts = prep.alt_by_letter.get(L, [])
        if alts:
            m.row({w[g]: 1.0 for g in alts}, 1, math.inf)
    m.row({y[o]: 1.0 for o in nodes_free}, 0, b_post - n_mand)
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
    status, x, vals = A3.lexicographic_solve(m, [keys[i] for i in key_order], [z[g] for g in admissible])
    if x is None:
        rec.update({"status": f"CE_SOLVER_NOT_OPTIMAL_{status}", "selected": None, "key_values": None, "solver_used": True})
        return rec
    selected = [g for g in admissible if int(x[z[g]]) == 1]
    kv = A3.pre_key_vector(prep, selected)
    new_nodes = {prep.groups[g]["node"] for g in selected} - prep.mandatory_nodes
    rec.update({"status": "CE_SELECTED" if selected else "CE_SELECTED_MANDATORY_ONLY", "selected": selected,
                "solver_used": True, "key_values": vals, "key_values_recomputed": kv,
                "verified": (len(selected) <= b_pre and [kv[i] for i in key_order] == vals
                             and n_mand + len(new_nodes) + min_alternative_footprint(prep) <= b_post + 3),
                "pre_new_nodes": len(new_nodes), "mandatory_core_nodes": n_mand + min_alternative_footprint(prep)})
    return rec


def post_metrics(prep, post: dict) -> dict:
    """Structural metrics of one post graph (class as a budget-exempt node: +1 node, +4 edges)."""
    if post.get("selected_free") is None:
        return {"status": post["status"]}
    sel_free = post["selected_free"]
    gs = [prep.groups[g] for g in list(prep.mandatory) + sel_free]
    nodes = {g["node"] for g in gs}
    opt = [g for g in sel_free if prep.groups[g]["tier"] == A3.T_OPT]
    alt = [g for g in sel_free if prep.groups[g]["tier"] == A3.T_ALT]
    per_letter_opt = {L: sum(1 for g in opt if L in prep.groups[g]["support"]) for L in LETTERS}
    letters_with_alt = [L for L in LETTERS[1:] if prep.alt_by_letter.get(L)]
    covered = [L for L in letters_with_alt if any(L in prep.groups[g]["alt_for"] for g in alt)]
    return {"status": post["status"], "entity_nodes": len(nodes), "entity_nodes_with_class_node": len(nodes) + 1,
            "edges": sum(len(g["edges"]) for g in gs), "mandatory_nodes": len(prep.mandatory_nodes),
            "optional_groups": len(opt), "alternative_groups": len(alt),
            "shared_information": sum(prep.groups[g]["attrs"]["s"] - 1 for g in sel_free),
            "distinct_keys": len({tuple(g["key"]) for g in gs}),
            "alt_letters": len(letters_with_alt), "alt_covered": len(covered),
            "abs_exposed": sum(prep.groups[g]["attrs"]["abs"] for g in sel_free),
            "risk_groups": sum(A3.risk_flag(prep.groups[g]) for g in sel_free),
            "answer_only_optional": sum(1 for g in opt if prep.groups[g]["attrs"]["a"] == 1),
            "letters_without_optional": [L for L in LETTERS[1:] if per_letter_opt[L] == 0],
            "mandatory_only": len(opt) == 0}


def measure_budget_item(universe_path: str, out_path: str, config: dict) -> dict:
    """D/E worker: N1 and N2 sweeps for one item under T0 and T2, plus the
    adjacent-swap sensitivity under N1 at the designated configuration."""
    A3.SOLVER_CALLS.clear()
    base = A3.read_json(Path(universe_path))
    sets = {k: frozenset(tuple(x) for x in v) for k, v in config["template_sets"].items()}
    rec: dict[str, Any] = {"item": base["item"], "counts": base["counts"], "by_template_set": {}}
    pre_base = list(range(len(A3.PRE_KEYS)))
    post_base = list(range(len(A3.POST_KEYS)))
    for tname in ("T0", "T2"):
        uni = apply_template_set(base, sets[tname]) if tname != "T0" else base
        prep = A3.prepare(uni)
        bounded, binfo = A3.bound_optional(prep, MEASURE_N_MAX, "stratified")
        bset = set(bounded)
        admissible = [g["gid"] for g in uni["groups"] if g["tier"] == A3.T_OPT and g["gid"] in bset
                      and A3.arm_admissible(PRE_ARM, g)[0]]
        core = len(prep.mandatory_nodes) + min_alternative_footprint(prep)
        out: dict[str, Any] = {"measure_universe": binfo, "admissible_pre": len(admissible),
                               "mandatory_nodes": len(prep.mandatory_nodes), "mandatory_core_nodes": core,
                               "n1": {}, "n2": {}, "n1_swaps": {}}
        # --- N1: node-aware pre for every (B_pre, B_post); post at the same B_post; K_A 0/1 ---
        for bp in B_PRE_SWEEP:
            for bpost in N1_B_POST_SWEEP:
                pre = solve_pre_node_aware(prep, admissible, bp, bpost, pre_base, tag=f"n1_pre_{bp}_{bpost}")
                cell: dict[str, Any] = {"pre_status": pre["status"], "pre_selected": pre.get("selected"),
                                        "pre_new_nodes": pre.get("pre_new_nodes"), "pre_verified": pre.get("verified"),
                                        "pre_keys": pre.get("key_values_recomputed")}
                for ka in (0, 1):
                    if pre.get("selected") is None:
                        cell[f"post_ka{ka}"] = {"status": pre["status"]}
                        continue
                    post = A3.solve_post(prep, pre["selected"], bounded, bpost, ka, post_base, tag=f"n1_post_{bp}_{bpost}_{ka}")
                    pm = post_metrics(prep, post)
                    pm["verified"] = post.get("verified"); pm["selected_free"] = post.get("selected_free")
                    pm["key_values"] = post.get("key_values_recomputed")
                    cell[f"post_ka{ka}"] = pm
                out["n1"][f"{bp}|{bpost}"] = cell
        # --- N2: ARCH-3 pre (not node-aware) at B_pre; post cap = core + K; K_A = 0 ---
        for bp in B_PRE_SWEEP:
            pre = A3.solve_pre(prep, admissible, bp, pre_base, tag=f"n2_pre_{bp}")
            for k in N2_K_SWEEP:
                cap = core + k
                if pre.get("selected") is None:
                    out["n2"][f"{bp}|{k}"] = {"status": pre["status"], "cap": cap}
                    continue
                post = A3.solve_post(prep, pre["selected"], bounded, cap, 0, post_base, tag=f"n2_post_{bp}_{k}")
                pm = post_metrics(prep, post)
                pm["cap"] = cap; pm["pre_new_nodes"] = len({prep.groups[g]["node"] for g in pre["selected"]} - prep.mandatory_nodes)
                pm["verified"] = post.get("verified"); pm["selected_free"] = post.get("selected_free")
                out["n2"][f"{bp}|{k}"] = pm
        # --- sensitivity under N1 at the designated configuration (K_A = 0), adjacent swaps only ---
        if tname == "T0":
            pre0 = solve_pre_node_aware(prep, admissible, DESIGNATED_B_PRE, DESIGNATED_B_POST, pre_base, tag="n1_sens_pre")
            if pre0.get("selected") is not None:
                post0 = A3.solve_post(prep, pre0["selected"], bounded, DESIGNATED_B_POST, 0, post_base, tag="n1_sens_post")
                swaps = {}
                for name, perm in A3.adjacent_swaps(len(A3.POST_KEYS))[1:]:
                    p2 = A3.solve_post(prep, pre0["selected"], bounded, DESIGNATED_B_POST, 0, perm, tag=f"n1_sens_{name}")
                    swaps[name] = {"changed": p2.get("selected_free") != post0.get("selected_free"),
                                   "jaccard": A3.jaccard(p2.get("selected_free") or [], post0.get("selected_free") or []),
                                   "earliest_key": (A3.earliest_diff(post0.get("key_values_recomputed"), p2.get("key_values_recomputed"), A3.POST_KEYS)
                                                    if p2.get("selected_free") != post0.get("selected_free") else "")}
                pre_swaps = {}
                for name, perm in A3.adjacent_swaps(len(A3.PRE_KEYS))[1:]:
                    p3 = solve_pre_node_aware(prep, admissible, DESIGNATED_B_PRE, DESIGNATED_B_POST, perm, tag=f"n1_sens_pre_{name}")
                    pre_swaps[name] = {"changed": p3.get("selected") != pre0.get("selected"),
                                       "jaccard": A3.jaccard(p3.get("selected") or [], pre0.get("selected") or [])}
                out["n1_swaps"] = {"post": swaps, "pre": pre_swaps, "post_status": post0["status"]}
        rec["by_template_set"][tname] = out
    calls = list(A3.SOLVER_CALLS)
    rec["solver"] = {"calls": len(calls), "status_counts": dict(Counter(c["status_name"] for c in calls)),
                     "seconds_total": round(sum(c["seconds"] for c in calls), 3),
                     "seconds_max": round(max((c["seconds"] for c in calls), default=0.0), 4),
                     "n_vars_max": max((c["n_vars"] for c in calls), default=0)}
    A3.write_json(Path(out_path), rec, gz=True)
    return {"item": base["item"]["key"], "calls": len(calls), "seconds": rec["solver"]["seconds_total"]}


def stage_budget(args, out_dir: Path) -> None:
    cands = load_template_candidates(out_dir / "template_candidates_v1.json")
    sets = template_sets(cands)
    config = {"template_sets": {k: sorted([list(x) for x in v]) for k, v in sets.items()}}
    todo = []
    for up in sorted((ARCH3_DIR / "universe").glob("*.json.gz")):
        mp = out_dir / "budget" / up.name
        if not mp.is_file():
            todo.append((str(up), str(mp)))
    (out_dir / "budget").mkdir(parents=True, exist_ok=True)
    say(f"[budget] {len(todo)} items with {args.workers} workers (N1 B_pre×B_post×K_A, N2 B_pre×K; T0 and T2)")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(measure_budget_item, up, mp, config): up for up, mp in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                r = fut.result()
                if i % 25 == 0:
                    say(f"  [budget] {i}/{len(todo)} ({time.time() - t0:.0f}s) last: {r['item']} {r['calls']} solves")
            except Exception as exc:                                # noqa: BLE001
                say(f"  [budget] FAILED {futs[fut]}: {exc!r}")
    say(f"[budget] done in {time.time() - t0:.0f}s")


# ==========================================================================
# F) H18 EXTENSION — stratified bounding at 800 / 1600 / 3200 / FULL on the hard items
# ==========================================================================

def measure_bounding_item(universe_path: str, out_path: str) -> dict:
    """One hard item: N1 pre at (4, 7, K_A = 0), arm C, T0, stratified bounding at
    800, 1600, 3200 and the FULL optional universe (attempted; a failed or
    non-optimal solve is recorded, never hidden). Runtime and peak model size
    are recorded per level."""
    A3.SOLVER_CALLS.clear()
    uni = A3.read_json(Path(universe_path))
    prep = A3.prepare(uni)
    pre_base = list(range(len(A3.PRE_KEYS))); post_base = list(range(len(A3.POST_KEYS)))
    levels = [(str(n), n) for n in H18_EXT_N_MAX] + [("FULL", None)]
    runs = {}
    for label, n in levels:
        t0 = time.time()
        calls_before = len(A3.SOLVER_CALLS)
        b, info = A3.bound_optional(prep, n, "stratified")
        bset = set(b)
        adm = [g["gid"] for g in uni["groups"] if g["tier"] == A3.T_OPT and g["gid"] in bset and A3.arm_admissible(PRE_ARM, g)[0]]
        try:
            pre = solve_pre_node_aware(prep, adm, DESIGNATED_B_PRE, DESIGNATED_B_POST, pre_base, tag=f"h18x_pre_{label}")
            post = (A3.solve_post(prep, pre["selected"], b, DESIGNATED_B_POST, 0, post_base, tag=f"h18x_post_{label}")
                    if pre.get("selected") is not None else {"status": pre["status"]})
            err = ""
        except Exception as exc:                                    # noqa: BLE001
            pre, post, err = {"status": "ERROR", "selected": None}, {"status": "ERROR"}, repr(exc)
        calls = A3.SOLVER_CALLS[calls_before:]
        runs[label] = {"info": info, "pre": pre.get("selected"), "pre_keys": pre.get("key_values_recomputed"),
                       "pre_status": pre["status"], "post": post.get("selected_free"),
                       "post_keys": post.get("key_values_recomputed"), "post_status": post["status"],
                       "post_verified": post.get("verified"), "error": err,
                       "seconds": round(time.time() - t0, 2), "solves": len(calls),
                       "n_vars_max": max((c["n_vars"] for c in calls), default=0),
                       "n_rows_max": max((c["n_rows"] for c in calls), default=0),
                       "statuses": dict(Counter(c["status_name"] for c in calls))}
    comps = {}
    seq = [l for l, _ in levels]
    for a, bl in zip(seq, seq[1:]):
        ra, rb = runs[a], runs[bl]
        ok = ra["post_status"] == "CE_SELECTED" and rb["post_status"] == "CE_SELECTED"
        comps[f"{a}->{bl}"] = {
            "actually_bounded_at_a": ra["info"]["scope"] == "UNIVERSE_BOUNDED", "both_solved": ok,
            "pre_equal": ra["pre"] == rb["pre"], "post_equal": ra["post"] == rb["post"],
            "pre_jaccard": A3.jaccard(ra["pre"] or [], rb["pre"] or []),
            "post_jaccard": A3.jaccard(ra["post"] or [], rb["post"] or []),
            "earliest_key": ("" if (ra["pre"] == rb["pre"] and ra["post"] == rb["post"]) else
                             ("pre:" + A3.earliest_diff(ra["pre_keys"], rb["pre_keys"], A3.PRE_KEYS) if ra["pre"] != rb["pre"]
                              else "post:" + A3.earliest_diff(ra["post_keys"], rb["post_keys"], A3.POST_KEYS)))}
    rec = {"item": uni["item"], "optional_total": len(prep.optional), "runs": runs, "comparisons": comps}
    A3.write_json(Path(out_path), rec, gz=True)
    return {"item": uni["item"]["key"], "optional": len(prep.optional),
            "full_status": runs["FULL"]["post_status"], "full_seconds": runs["FULL"]["seconds"]}


def stage_bounding(args, out_dir: Path) -> None:
    todo = []
    for up in sorted((ARCH3_DIR / "universe").glob("*.json.gz")):
        u = A3.read_json(up)
        if u["counts"].get("tier_OPTIONAL_CONTEXT", 0) > H18_EXT_MIN_OPTIONAL:
            mp = out_dir / "bounding" / up.name
            if not mp.is_file():
                todo.append((str(up), str(mp)))
    (out_dir / "bounding").mkdir(parents=True, exist_ok=True)
    say(f"[bounding] {len(todo)} hard items (> {H18_EXT_MIN_OPTIONAL} optional groups) with {args.workers} workers")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(measure_bounding_item, up, mp): up for up, mp in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                r = fut.result()
                say(f"  [bounding] {i}/{len(todo)} {r['item']} optional={r['optional']} FULL={r['full_status']} ({r['full_seconds']}s)")
            except Exception as exc:                                # noqa: BLE001
                say(f"  [bounding] FAILED {futs[fut]}: {exc!r}")
    say(f"[bounding] done in {time.time() - t0:.0f}s")


# ==========================================================================
# B) THE TEMPLATE-CANDIDATE FILE — verdicts written from the census, one per key
# ==========================================================================
#
# Each verdict was assigned by READING the corpus census (frequencies, the most
# frequent objects and deterministic example triples). The rules applied:
#
#   SAFE_TO_TEMPLATE    a fixed English template renders EVERY observed triple of
#                       the key faithfully; the slot holds VALUES of one kind and
#                       the reading does not depend on the subject's infobox
#                       family. "Neutral" readings ("the location of X is Y")
#                       are used where the exact relation wording would vary.
#   NEEDS_HUMAN_REVIEW  the slot is polysemous across infobox families, mixes
#                       values with list pages or placeholders, or the reading
#                       would be wrong for a material share of triples.
#   REJECT              layout metadata, alias/name slots, navigation slots,
#                       external references, or a slot the B2-G audit already
#                       refused (honorificPrefix).
# No template exists to rescue one Answer: every verdict is about the KEY over
# the whole pinned KG. The production registry is NOT edited.

def _c(pred: str, direction: str, reading: str, semantic: str, verdict: str, reason: str,
       pattern: Optional[str] = None, risks: str = "", roles_reverse: Optional[bool] = None) -> dict:
    triple = pattern or (f"(<answer>, dbp:{pred}, <object>)" if direction == "OUT" else f"(<subject>, dbp:{pred}, <answer>)")
    return {"predicate_uri": P + pred, "raw_predicate": f"dbp:{pred}", "direction": direction, "triple_pattern": triple,
            "intended_semantic_reading": semantic, "proposed_template": reading,
            "template_id": f"{direction}_{''.join(ch if ch.isalnum() else '_' for ch in pred).upper()}_CANDIDATE_V1",
            "subject_object_roles_reverse_for_IN": (direction == "IN") if roles_reverse is None else roles_reverse,
            "ambiguity_risks": risks, "eligibility": verdict, "scientific_reason": reason}


CANDIDATE_VERDICTS: list[dict] = [
    # ---- the five ARCH-3 high-impact keys ----
    _c("birthPlace", "IN", "<subject> was born in <answer>.", "the subject person's birthplace is the Answer place",
       "SAFE_TO_TEMPLATE", "956,439 edges; objects are places at any granularity (country/state/city); one reading fits all.",
       risks="mixed granularity of the place value (country vs city) is a grounding matter, not a template matter"),
    _c("deathPlace", "IN", "<subject> died in <answer>.", "the subject person's death place is the Answer place",
       "SAFE_TO_TEMPLATE", "258,812 edges; same value kind as birthPlace; one reading fits all."),
    _c("battles", "IN", "<subject> took part in <answer>.", "the subject (person or military unit) fought in the Answer battle/war",
       "SAFE_TO_TEMPLATE", "115,410 edges; subjects are persons and units, objects are wars/battles; 'took part in' is faithful for both.",
       risks="a ship or unit as subject reads naturally with 'took part in'; 'fought in' would not"),
    _c("products", "IN", "<subject> lists <answer> among its products.", "the Answer is a product of the subject organisation",
       "SAFE_TO_TEMPLATE", "27,213 edges; subjects are companies/mines/organisations, objects are product categories or substances; neutral wording avoids over-claiming manufacture.",
       risks="a few subjects are advertisements or labels (2.13.61 -> Record company); the neutral wording stays faithful"),
    _c("settlementType", "OUT", "<answer> has the settlement type <object>.", "the Answer place's settlement type as recorded in its infobox",
       "SAFE_TO_TEMPLATE", "145,055 edges; values are settlement types (Unincorporated area, City, Town, Obec...); the neutral wording stays faithful where the value is a list page (Districts of Peru).",
       risks="some values are list pages rather than type names; the reading remains true of the record"),
    # ---- other keys of template-less R* facts ----
    _c("regent", "IN", "<answer> is recorded as regent for <subject>.", "regency relation between two persons", "NEEDS_HUMAN_REVIEW",
       "3,298 edges; the slot mixes monarch-regent pairs with deputy lists on politician infoboxes (Abdul Ghani Baradar -> five deputies); direction of the relation is not uniform."),
    _c("regent", "OUT", "<object> is recorded as regent for <answer>.", "regency relation", "NEEDS_HUMAN_REVIEW", "same slot as regent/IN; same polysemy."),
    _c("leaderName", "OUT", "<object> is recorded as a leader of <answer>.", "the Answer polity/organisation's leader", "NEEDS_HUMAN_REVIEW",
       "25,097 edges; 1.5% non-resource values and frequent council/body values (Edmonton City Council 324, Indonesia) mixed with persons."),
    _c("after", "IN", "<subject> was followed by <answer>.", "succession box: the Answer came after the subject", "NEEDS_HUMAN_REVIEW",
       "183,863 edges across offices, buildings and expeditions; 'followed by' is faithful, but the placeholder value 'Incumbent' (262 edges) would render as a person; needs an object-level exclusion first."),
    _c("after", "OUT", "<answer> was followed by <object>.", "succession box", "NEEDS_HUMAN_REVIEW", "as after/IN (Incumbent placeholder)."),
    _c("before", "IN", "<subject> was preceded by <answer>.", "succession box: the Answer came before the subject", "NEEDS_HUMAN_REVIEW",
       "182,601 edges; same placeholder risk as after (Incumbent 19); otherwise faithful."),
    _c("before", "OUT", "<answer> was preceded by <object>.", "succession box", "NEEDS_HUMAN_REVIEW", "as before/IN."),
    _c("combatant", "OUT", "<object> was a combatant in <answer>.", "the Answer conflict's combatant", "SAFE_TO_TEMPLATE",
       "8,786 edges; subjects are conflicts, objects are polities/forces; one reading."),
    _c("combatant", "IN", "<answer> was a combatant in <subject>.", "the Answer polity fought in the subject conflict", "SAFE_TO_TEMPLATE", "as combatant/OUT."),
    _c("partof", "IN", "<subject> was part of <answer>.", "the subject event/site is part of the Answer larger event/structure", "SAFE_TO_TEMPLATE",
       "10,434 edges; values are larger events or structures; 'was part of' is faithful for both."),
    _c("wars", "IN", "<subject> is associated with <answer>.", "a weapon/unit page listing the wars it appears in", "NEEDS_HUMAN_REVIEW",
       "7,665 edges; subjects are cartridges and units (.45-70 -> Indian Wars); 'took part in' is wrong for an object, and the neutral wording is weak."),
    _c("titleLeader", "OUT", "The leader of <answer> held the title <object>.", "title of the polity's head", "NEEDS_HUMAN_REVIEW",
       "1,847 edges; values mix titles (Sultan, King) with list pages (List of Governors of Alabama, Monarchy of Greece)."),
    _c("leader", "OUT", "<object> is recorded as a leader of <answer>.", "the Answer polity/body's leader", "SAFE_TO_TEMPLATE",
       "38,273 edges; subjects are legislatures/parties/polities, objects are persons; neutral wording covers head-of-state and party-leader uses."),
    _c("leader", "IN", "<answer> is recorded as a leader of <subject>.", "the Answer person led the subject body", "SAFE_TO_TEMPLATE", "as leader/OUT."),
    _c("school", "OUT", "<answer> is associated with the school <object>.", "school attended or school of thought", "NEEDS_HUMAN_REVIEW",
       "13,684 edges; polysemous: Buddhist schools (Theravada 141), high schools, and draft-pick schools on team-season pages."),
    _c("dedication", "IN", "<subject> is dedicated to <answer>.", "a church/temple dedicated to the Answer saint/figure", "SAFE_TO_TEMPLATE",
       "4,933 edges; identical semantics to the existing dedicatedTo/IN template."),
    _c("honorificPrefix", "OUT", "", "form of address", "REJECT", "Prompt 8H-B2-G §4 decision: a form of address, not a fact; no template and no tier."),
    _c("name", "IN", "", "a subject's name slot pointing at the Answer resource", "REJECT",
       "811,971 edges with 35,028 subjects: squad lists, award lists and other layout uses of the `name` slot; no relation semantics."),
    _c("monarch", "IN", "<answer> was the reigning monarch for <subject>.", "the monarch during the subject's term/session", "SAFE_TO_TEMPLATE",
       "13,249 edges; subjects are parliaments, legislatures and year pages; the neutral wording is faithful for all of them."),
    _c("event", "IN", "<subject> belongs to the event <answer>.", "edition of a competition or an athlete's discipline", "NEEDS_HUMAN_REVIEW",
       "18,462 edges; mixes competition editions (1911 FA Charity Shield -> FA Community Shield) with athletes' disciplines (Marathon 644)."),
    _c("subdivisionName", "OUT", "<answer> is part of <object>.", "administrative containment of the Answer place", "SAFE_TO_TEMPLATE",
       "1,155,813 edges; the containing unit at any level; the same slot the semantic policy already uses for place containment."),
    _c("subdivisionName", "IN", "<subject> is part of <answer>.", "the subject place lies in the Answer unit", "SAFE_TO_TEMPLATE", "as subdivisionName/OUT."),
    _c("location", "OUT", "The location of <answer> is <object>.", "place of the Answer site/event", "SAFE_TO_TEMPLATE",
       "739,763 edges over sites, buildings and events; the neutral wording is true for every family (a building is located in, an event took place in)."),
    _c("location", "IN", "The location of <subject> is <answer>.", "the subject site/event is located in the Answer place", "SAFE_TO_TEMPLATE", "as location/OUT."),
    _c("cultCenter", "IN", "<answer> was a cult centre of <subject>.", "ancient deity's cult centre", "SAFE_TO_TEMPLATE",
       "299 edges; deities -> cities; unambiguous."),
    _c("field", "IN", "<subject> worked in the field of <answer>.", "academic discipline (as the existing fields/IN template)", "NEEDS_HUMAN_REVIEW",
       "31,049 edges; mostly disciplines (Painting 2,864, Mathematics 850) but the same slot is the BALLPARK on baseball-season pages (2019 Tohoku Rakuten Golden Eagles season -> Rakuten Seimei Park); the fields/IN reading would be wrong there. The alias family admits the pair for evidence lookup; a template needs the same polysemy audit."),
    _c("treatment", "IN", "<subject> is treated with <answer>.", "disease treated with the Answer substance/therapy", "SAFE_TO_TEMPLATE",
       "637 edges; diseases -> treatments; unambiguous."),
    _c("product", "IN", "<subject> lists <answer> among its products.", "singular spelling of products", "NEEDS_HUMAN_REVIEW",
       "170 edges only; subjects include advertisements and processes (Alberta Taciuk process -> Shale oil); too small and mixed to admit blind."),
    _c("examples", "IN", "", "examples list of a concept page", "REJECT", "21 edges; a list slot without relation semantics."),
    _c("othernames", "OUT", "", "alias slot", "REJECT", "98 edges; an alias/name slot; rendering it would print another name of the Answer."),
    _c("deity", "IN", "<subject> is dedicated to the deity <answer>.", "temple dedicated to the Answer deity", "SAFE_TO_TEMPLATE",
       "1,933 edges; temples -> deities; unambiguous."),
    _c("candidate", "IN", "<answer> was a candidate in <subject>.", "election candidate", "SAFE_TO_TEMPLATE",
       "170,019 edges; elections -> candidates; 'None of the above' is a genuine ballot option, not a placeholder."),
    _c("issue", "OUT", "<object> was a child of <answer>.", "royalty infobox issue = children", "SAFE_TO_TEMPLATE",
       "17,689 edges; royalty/nobility children; one reading."),
    _c("dynasty", "OUT", "<answer> belonged to the dynasty <object>.", "ruler's dynasty", "SAFE_TO_TEMPLATE",
       "3,119 edges; values are dynasties (Abbadid, Umayyad, Timurid); the neutral wording tolerates the rare polity value (Kingdom of Jimma)."),
    _c("canonizedBy", "OUT", "<answer> was canonized by <object>.", "saint canonized by a pope/church", "SAFE_TO_TEMPLATE", "765 edges; unambiguous."),
    _c("before", "OUT", "<answer> was preceded by <object>.", "succession box", "NEEDS_HUMAN_REVIEW", "duplicate guard; see before/OUT above.") if False else None,
    _c("with", "IN", "", "co-member slot of parliamentary seats", "REJECT", "16,074 edges; 'with' = fellow member of a multi-member seat; no expressible relation."),
    _c("constituency", "OUT", "<answer> represented the constituency <object>.", "politician's constituency", "NEEDS_HUMAN_REVIEW",
       "29,954 edges; subjects include elections whose `constituency` lists ALL constituencies (1999 National Assembly for Wales election -> 40 values); wrong for those."),
    _c("presidentCandidate", "IN", "<answer> was a presidential candidate in <subject>.", "US election-year page candidate", "SAFE_TO_TEMPLATE", "113 edges; unambiguous."),
    _c("father", "IN", "<answer> was the father of <subject>.", "parent relation", "SAFE_TO_TEMPLATE", "25,442 edges; mirrors the existing father/OUT template."),
    _c("spouse", "IN", "<subject> was married to <answer>.", "marriage", "SAFE_TO_TEMPLATE", "57,650 edges; mirrors the existing spouse/OUT template."),
    _c("disease", "OUT", "<answer> was an outbreak of <object>.", "epidemic's disease", "SAFE_TO_TEMPLATE", "593 edges; epidemics -> diseases; unambiguous."),
    _c("language", "OUT", "The language of <answer> is <object>.", "language of a work or polity", "NEEDS_HUMAN_REVIEW",
       "74,024 edges; 'Silent film' (3,248) is used as a language value on film pages; needs an exclusion before a template."),
    _c("commonLanguages", "OUT", "<object> was a common language of <answer>.", "polity's common languages", "SAFE_TO_TEMPLATE", "4,523 edges; polities -> languages; unambiguous."),
    _c("place", "OUT", "<answer> took place in <object>.", "event location", "SAFE_TO_TEMPLATE",
       "49,999 edges; events, protests, plays -> places/theatres; 'took place in' is faithful."),
    _c("place", "IN", "<subject> took place in <answer>.", "the subject event took place in the Answer place", "SAFE_TO_TEMPLATE", "as place/OUT."),
    _c("northeast", "OUT", "", "map-adjacency navigation slot", "REJECT", "14,513 edges; a compass-navigation slot of the settlement infobox, not a fact about the entity."),
    _c("postalCodeType", "OUT", "", "layout metadata", "REJECT", "88,309 edges; the LABEL of the postal-code slot (ZIP code, Postal Index Number); layout metadata."),
    _c("subdivisionType", "OUT", "", "layout metadata", "REJECT",
       "1,316,726 edges; the LABEL of the subdivisionName slot (List of sovereign states, U.S. state, Voivodeships of Poland); renders as nonsense ('A's subdivision type is List of sovereign states'). Candidate for an upstream layout-slot rejection, outside this task."),
    _c("eventStart", "OUT", "<answer> began with <object>.", "founding event of a polity", "NEEDS_HUMAN_REVIEW", "792 edges; the placeholder 'Wikt:establishment' (21) would render as an event."),
    _c("builder", "IN", "<subject> was built by <answer>.", "builder of a locomotive/building", "SAFE_TO_TEMPLATE", "9,413 edges; unambiguous."),
    _c("establishedEvent", "IN", "<subject> was established through <answer>.", "founding event of an organisation/polity", "NEEDS_HUMAN_REVIEW",
       "964 edges; values mix events, documents and polities (Albania -> Principality of Albania); the reading is not uniform."),
    _c("including", "IN", "", "list slot", "REJECT", "104 edges; a vague 'including' list of a period page."),
    _c("ideology", "IN", "<answer> is an ideology of <subject>.", "party ideology", "SAFE_TO_TEMPLATE", "29,171 edges; parties/movements -> ideologies; unambiguous."),
    _c("type", "IN", "", "generic type slot", "REJECT", "227,969 edges of a generic classification slot (Album, Public company); no relation between two entities."),
    _c("affiliation", "IN", "<subject> is affiliated with <answer>.", "organisational affiliation", "SAFE_TO_TEMPLATE", "13,445 edges; one reading."),
    _c("allegiance", "IN", "The allegiance of <subject> was to <answer>.", "military allegiance of a person/unit to a nation", "SAFE_TO_TEMPLATE", "17,016 edges; units/persons -> nations; one reading."),
    _c("areaServed", "IN", "<subject> serves <answer>.", "service area of an organisation", "NEEDS_HUMAN_REVIEW",
       "13,394 edges; subjects include postcode districts (01527 -> Catshill) where 'serves' is wrong."),
    _c("venue", "IN", "<subject> was held in <answer>.", "event venue or host city/country", "SAFE_TO_TEMPLATE",
       "88,531 edges; values mix venues, cities and countries; 'held in' is faithful for all three."),
    _c("cities", "IN", "<answer> is listed among the cities of <subject>.", "host cities of a summit or member cities of an area", "SAFE_TO_TEMPLATE",
       "11,635 edges; the neutral wording is true for summits (host city) and areas (member city)."),
    _c("city", "IN", "<subject> is based in <answer>.", "city of an organisation/station/building", "NEEDS_HUMAN_REVIEW",
       "142,299 edges; values include countries and states (United States, Ontario) and subjects include songs; the slot is used loosely."),
    _c("country", "IN", "The country recorded for <subject> is <answer>.", "country slot of any infobox", "SAFE_TO_TEMPLATE",
       "142,785 edges over works, buildings, events and organisations; only the neutral wording is faithful across families (a film's country of production, a building's country)."),
    _c("popplace", "IN", "<subject> has a significant population in <answer>.", "ethnic group's populated places", "SAFE_TO_TEMPLATE",
       "5,236 edges; the ethnic-group infobox slot means exactly this."),
    _c("observedby", "IN", "<subject> is observed by <answer>.", "holiday observed by a group/country", "NEEDS_HUMAN_REVIEW",
       "876 edges; values mix countries, religions and 'UN Members'; 'observed by' misreads a country value."),
    _c("officeholder", "IN", "<answer> is recorded as an office holder of <subject>.", "commanders/holders listed on an office or unit page", "NEEDS_HUMAN_REVIEW",
       "13,133 edges from 943 subjects (army pages listing commanders); the relation is 'commanded' for armies and 'held' for offices."),
    _c("premier", "IN", "<answer> was the premier for <subject>.", "premier during a cabinet/term", "NEEDS_HUMAN_REVIEW",
       "3,696 edges; cabinets and lieutenant-governors as subjects; the wording differs by family."),
    _c("primeminister", "IN", "<answer> was prime minister during the term of <subject>.", "the PM in office during the subject's term", "SAFE_TO_TEMPLATE",
       "26,863 edges; subjects are ministers, presidents and other office holders; the neutral wording is faithful for all (Kalam -> Vajpayee)."),
    _c("president", "IN", "<answer> was president during <subject>.", "president during a term or a club season", "NEEDS_HUMAN_REVIEW",
       "34,831 edges; national presidents on officeholder pages and CLUB presidents on team-season pages (1883 Brooklyn Grays season -> Charlie Byrne); the neutral wording holds but the pedagogical content differs sharply."),
    _c("nominee", "IN", "<answer> was a nominee in <subject>.", "election nominee", "SAFE_TO_TEMPLATE", "11,835 edges; elections -> nominees; unambiguous."),
    _c("nominator", "IN", "<subject> was nominated by <answer>.", "nominating authority", "NEEDS_HUMAN_REVIEW",
       "3,113 edges; elections list institutions as nominators (Local government in the Republic of Ireland); mixed."),
    _c("succession", "OUT", "<answer> held the title <object>.", "royalty succession title", "NEEDS_HUMAN_REVIEW",
       "9,635 edges; values mix titles (Emperor of Japan, Queen consort, Regent) with list pages (List of Burmese monarchs) and places (Lesotho)."),
    _c("house", "OUT", "<answer> belonged to the house <object>.", "royal house", "NEEDS_HUMAN_REVIEW",
       "11,767 edges; royal houses on person pages but LEGISLATIVE houses on election pages (1896 Queensland colonial election -> Legislative Assembly); polysemous."),
    _c("royalHouse", "OUT", "<answer> belonged to the royal house <object>.", "royal house", "SAFE_TO_TEMPLATE", "1,234 edges; unambiguous."),
    _c("today", "OUT", "The territory of <answer> is today part of <object>.", "former polity -> present country", "SAFE_TO_TEMPLATE", "4,434 edges; unambiguous."),
    _c("governmentType", "OUT", "<answer> has the form of government <object>.", "form of government", "SAFE_TO_TEMPLATE",
       "19,453 edges; values are government forms (Panchayati raj, Mayor–council, Monarchy); neutral wording."),
    _c("epochs", "IN", "<subject> is dated to the epoch <answer>.", "archaeological site period", "SAFE_TO_TEMPLATE",
       "2,122 edges; sites -> periods; neutral wording also covers a polity used as a period value (Roman Empire 81)."),
    _c("material", "IN", "<subject> is made of <answer>.", "monument/bridge material", "SAFE_TO_TEMPLATE", "2,992 edges; unambiguous."),
    _c("source", "OUT", "", "external reference slot", "REJECT", "23,394 edges; 49.6% non-resource values (URLs, book ids); an external-reference slot."),
    _c("ground", "IN", "<answer> is the home ground of <subject>.", "club's home ground", "NEEDS_HUMAN_REVIEW",
       "30,948 edges; values include countries (Italy 435, Brazil 360) where 'home ground' is wrong."),
    _c("blankNameSec", "OUT", "", "layout metadata", "REJECT", "12,552 edges; a blank-section label slot (Human Development Index, Köppen climate classification)."),
    _c("capital", "IN", "<answer> was the capital of <subject>.", "capital city of a polity", "SAFE_TO_TEMPLATE", "6,304 edges; unambiguous."),
    _c("capital", "OUT", "<object> was the capital of <answer>.", "capital of the Answer polity", "SAFE_TO_TEMPLATE", "as capital/IN."),
    _c("commander", "OUT", "<object> commanded <answer>.", "commander of a unit or in a battle", "NEEDS_HUMAN_REVIEW",
       "22,230 edges; values include rank labels (Admiral 66, General 36, Major General 32) that would render as persons."),
    _c("timezone", "OUT", "<answer> is in the <object> time zone.", "time zone of a place", "SAFE_TO_TEMPLATE",
       "314,303 edges; values are time zones; a non-discriminating context fact (support 4 is typical)."),
    _c("timezoneDst", "OUT", "", "daylight-saving variant of timezone", "REJECT", "130,738 edges; a technical duplicate of timezone with no additional learner content."),
    _c("posthumousName", "OUT", "", "layout placeholder", "REJECT", "129 edges of which 128 point at the page 'Posthumous name' itself: a placeholder, not a value."),
    _c("stadium", "IN", "<answer> appears as a match venue of <subject>.", "venue list of club-season / competition pages", "NEEDS_HUMAN_REVIEW",
       "577,960 edges from 90,432 season/competition subjects; values mix stadiums (Croke Park) and cities (Dublin 1,649); the subject is a season article, so the learner-facing content ('a match of the 2010–11 season was played in A') is weak; needs the human's pedagogical call."),
]
CANDIDATE_VERDICTS = [c for c in CANDIDATE_VERDICTS if c is not None]


def stage_candidates(args, out_dir: Path) -> None:
    """Write the versioned template-candidate file from the verdict table plus
    the census evidence (frequencies, examples) for every key. Every census key
    must have a verdict; a missing one is written as NEEDS_HUMAN_REVIEW with an
    explicit 'not individually audited' reason so nothing is silently admitted."""
    census = A3.read_json(out_dir / "template_candidate_census.json")
    sources = A3.read_json(out_dir / "template_candidate_key_sources.json")["sources"]
    by_key = {(c["predicate_uri"], c["direction"]): c for c in CANDIDATE_VERDICTS}
    dup = Counter((c["predicate_uri"], c["direction"]) for c in CANDIDATE_VERDICTS)
    assert not [k for k, n in dup.items() if n > 1], [k for k, n in dup.items() if n > 1]
    out = []
    for p, d in (tuple(k) for k in census["keys"]):
        rec = by_key.get((P + p, d))
        if rec is None:
            rec = _c(p, d, "", "not individually audited", "NEEDS_HUMAN_REVIEW",
                     "census key without an individual verdict in this task; nothing is admitted by default")
        ce = census["predicates"].get(p, {})
        ks = key_str(P + p, d)
        rec = dict(rec)
        rec["pinned_kg_census"] = {"edges": ce.get("edges"), "distinct_subjects": ce.get("distinct_subjects"),
                                   "distinct_objects": ce.get("distinct_objects"),
                                   "resource_object_share": ce.get("resource_object_share"),
                                   "top_objects": ce.get("top_objects", [])[:8]}
        rec["pinned_kg_examples"] = ce.get("examples", [])[:8]
        rec["development_impact"] = {
            "rstar_unverbalizable_facts": sources["rstar_unverbalizable_fact_keys"].get(ks, 0),
            "shared_unverbalizable_optional_groups": sources["shared_unverbalizable_optional_groups_by_key"].get(ks, 0),
            "armC_unlock": sources["unlock_items_by_key"].get(ks, {"items": 0, "by_group": {}}),
        }
        rec["high_impact_five"] = (p, d) in HIGH_IMPACT_KEYS
        out.append(rec)
    verdict_counts = Counter(c["eligibility"] for c in out)
    payload = {"version": "template_candidates/1.0.0-proposal-not-production", "date": TODAY,
               "note": ("CANDIDATE templates for human review. The production registry "
                        "src/rationale_v3/policies/predicate_policy_v2.json is NOT modified. No Answer-specific "
                        "template exists; every verdict is about the key over the whole pinned KG."),
               "pinned_kg_sha256": A3.PINNED_KG_SHA256, "verdict_counts": dict(verdict_counts),
               "T1_definition": "SAFE_TO_TEMPLATE candidates among the five ARCH-3 high-impact keys",
               "T2_definition": "every SAFE_TO_TEMPLATE candidate",
               "candidates": sorted(out, key=lambda c: (c["eligibility"], -c["development_impact"]["rstar_unverbalizable_facts"],
                                                        c["raw_predicate"], c["direction"]))}
    A3.write_json(out_dir / "template_candidates_v1.json", payload)
    rows = [{"key": key_str(c["predicate_uri"], c["direction"]), "eligibility": c["eligibility"],
             "high_impact_five": c["high_impact_five"], "template": c["proposed_template"],
             "edges": c["pinned_kg_census"]["edges"], "rstar_facts": c["development_impact"]["rstar_unverbalizable_facts"],
             "shared_groups": c["development_impact"]["shared_unverbalizable_optional_groups"],
             "armC_unlock_items": c["development_impact"]["armC_unlock"]["items"], "reason": c["scientific_reason"]} for c in payload["candidates"]]
    A3.write_csv(out_dir / "template_candidates_v1.csv", rows)
    say(f"[candidates] {len(out)} keys: {dict(verdict_counts)}")


# ==========================================================================
# ROLLUPS for D/E/F and the package stage
# ==========================================================================

def rollup_budget(out_dir: Path) -> dict:
    recs = [A3.read_json(p) for p in sorted((out_dir / "budget").glob("*.json.gz"))]
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        for label in ("POOLED", f"GROUP:{r['item']['cohort_group']}", f"BATCH:{r['item']['batch']}"):
            groups[label].append(r)
    roll = {}
    for label, rs in sorted(groups.items()):
        n = len(rs)
        rec: dict[str, Any] = {"items": n}
        for t in ("T0", "T2"):
            tt: dict[str, Any] = {"admissible_pre_mean": A3._mean([r["by_template_set"][t]["admissible_pre"] for r in rs]),
                                  "items_ge1_admissible_pre": A3.rate(sum(1 for r in rs if r["by_template_set"][t]["admissible_pre"] >= 1), n),
                                  "mandatory_core_nodes_mean": A3._mean([r["by_template_set"][t]["mandatory_core_nodes"] for r in rs]),
                                  "mandatory_core_nodes_dist": dict(Counter(str(r["by_template_set"][t]["mandatory_core_nodes"]) for r in rs)),
                                  "n1": {}, "n2": {}}
            for bp in B_PRE_SWEEP:
                for bpost in N1_B_POST_SWEEP:
                    cells = [r["by_template_set"][t]["n1"][f"{bp}|{bpost}"] for r in rs]
                    for ka in (0, 1):
                        posts = [c[f"post_ka{ka}"] for c in cells]
                        ok = [p for p in posts if p.get("status") == "CE_SELECTED"]
                        tt["n1"][f"{bp}|{bpost}|{ka}"] = {
                            "pre_status": dict(Counter(c["pre_status"] for c in cells)),
                            "post_status": dict(Counter(p.get("status") for p in posts)),
                            "nested_infeasible": sum(1 for p in posts if p.get("status") == "CE_NESTED_INFEASIBLE_AT_BUDGET"),
                            "mandatory_core_too_large": sum(1 for c in cells if c["pre_status"] == "CE_MANDATORY_CORE_TOO_LARGE"),
                            "selected": A3.rate(len(ok), n),
                            "pre_selected_mean": A3._mean([len(c["pre_selected"] or []) for c in cells if c["pre_selected"] is not None]),
                            "pre_new_nodes_mean": A3._mean([c["pre_new_nodes"] for c in cells if c.get("pre_new_nodes") is not None]),
                            "entity_nodes_mean": A3._mean([p["entity_nodes"] for p in ok]),
                            "entity_nodes_with_class_node_mean": A3._mean([p["entity_nodes_with_class_node"] for p in ok]),
                            "edges_mean": A3._mean([p["edges"] for p in ok]),
                            "optional_groups_mean": A3._mean([p["optional_groups"] for p in ok]),
                            "alternative_groups_mean": A3._mean([p["alternative_groups"] for p in ok]),
                            "shared_information_mean": A3._mean([p["shared_information"] for p in ok]),
                            "distinct_keys_mean": A3._mean([p["distinct_keys"] for p in ok]),
                            "alt_coverage": A3.rate(sum(p["alt_covered"] for p in ok), sum(p["alt_letters"] for p in ok)),
                            "abs_exposed_mean": A3._mean([p["abs_exposed"] for p in ok]),
                            "items_exposing_absence": A3.rate(sum(1 for p in ok if p["abs_exposed"] > 0), len(ok)),
                            "answer_only_optional_mean": A3._mean([p["answer_only_optional"] for p in ok]),
                            "mandatory_only": A3.rate(sum(1 for p in ok if p["mandatory_only"]), len(ok)),
                            "every_distractor_has_optional": A3.rate(sum(1 for p in ok if not p["letters_without_optional"]), len(ok)),
                        }
            for bp in B_PRE_SWEEP:
                for k in N2_K_SWEEP:
                    posts = [r["by_template_set"][t]["n2"][f"{bp}|{k}"] for r in rs]
                    ok = [p for p in posts if p.get("status") == "CE_SELECTED"]
                    tt["n2"][f"{bp}|{k}"] = {
                        "post_status": dict(Counter(p.get("status") for p in posts)),
                        "nested_infeasible": sum(1 for p in posts if p.get("status") == "CE_NESTED_INFEASIBLE_AT_BUDGET"),
                        "cap_mean": A3._mean([p.get("cap") for p in posts if p.get("cap") is not None]),
                        "selected": A3.rate(len(ok), n),
                        "entity_nodes_mean": A3._mean([p["entity_nodes"] for p in ok]),
                        "entity_nodes_max": max((p["entity_nodes"] for p in ok), default=None),
                        "optional_groups_mean": A3._mean([p["optional_groups"] for p in ok]),
                        "shared_information_mean": A3._mean([p["shared_information"] for p in ok]),
                        "distinct_keys_mean": A3._mean([p["distinct_keys"] for p in ok]),
                        "alt_coverage": A3.rate(sum(p["alt_covered"] for p in ok), sum(p["alt_letters"] for p in ok)),
                        "abs_exposed_mean": A3._mean([p["abs_exposed"] for p in ok]),
                    }
            # K_A_post 0 vs 1 at the designated N1 cell: how often does the selection differ?
            key = f"{DESIGNATED_B_PRE}|{DESIGNATED_B_POST}"
            diff = sum(1 for r in rs if (r["by_template_set"][t]["n1"][key].get("post_ka0", {}).get("selected_free")
                                         != r["by_template_set"][t]["n1"][key].get("post_ka1", {}).get("selected_free")))
            tt["k_a_post_designated"] = {"items_where_selection_differs": A3.rate(diff, n)}
            rec[t] = tt
        sw = [r["by_template_set"]["T0"].get("n1_swaps") or {} for r in rs]
        sw = [s for s in sw if s.get("post")]
        rec["n1_sensitivity_T0"] = {
            "items": len(sw),
            "post_swaps": {name: {"changed": A3.rate(sum(1 for s in sw if s["post"][name]["changed"]), len(sw)),
                                  "jaccard_mean": A3._mean([s["post"][name]["jaccard"] for s in sw]),
                                  "earliest_key": dict(Counter(s["post"][name]["earliest_key"] for s in sw if s["post"][name]["changed"]))}
                           for name in (sw[0]["post"].keys() if sw else [])},
            "pre_swaps": {name: {"changed": A3.rate(sum(1 for s in sw if s["pre"][name]["changed"]), len(sw))}
                          for name in (sw[0]["pre"].keys() if sw else [])},
        }
        roll[label] = rec
    calls = sum(r["solver"]["calls"] for r in recs)
    status = Counter()
    for r in recs:
        status.update(r["solver"]["status_counts"])
    roll["_solver"] = {"calls": calls, "status_counts": dict(status), "seconds_total": round(sum(r["solver"]["seconds_total"] for r in recs), 1),
                       "n_vars_max": max((r["solver"]["n_vars_max"] for r in recs), default=0)}
    return roll


def rollup_bounding(out_dir: Path) -> dict:
    recs = [A3.read_json(p) for p in sorted((out_dir / "bounding").glob("*.json.gz"))]
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        for label in ("POOLED", f"GROUP:{r['item']['cohort_group']}"):
            groups[label].append(r)
    roll = {}
    steps = ["800->1600", "1600->3200", "3200->FULL"]
    for label, rs in sorted(groups.items()):
        rec: dict[str, Any] = {"items": len(rs), "optional_max": max(r["optional_total"] for r in rs),
                               "full_solved": A3.rate(sum(1 for r in rs if r["runs"]["FULL"]["post_status"] == "CE_SELECTED"), len(rs)),
                               "full_failures": [{"item": r["item"]["key"], "status": r["runs"]["FULL"]["post_status"], "error": r["runs"]["FULL"]["error"]}
                                                 for r in rs if r["runs"]["FULL"]["post_status"] != "CE_SELECTED"],
                               "full_seconds_median": A3._median([r["runs"]["FULL"]["seconds"] for r in rs]),
                               "full_seconds_max": max(r["runs"]["FULL"]["seconds"] for r in rs),
                               "full_n_vars_max": max(r["runs"]["FULL"]["n_vars_max"] for r in rs), "steps": {}}
        for st in steps:
            rows = [r["comparisons"][st] for r in rs if r["comparisons"][st]["actually_bounded_at_a"] and r["comparisons"][st]["both_solved"]]
            rec["steps"][st] = {"items_actually_bounded_and_solved": len(rows),
                                "pre_equal": A3.rate(sum(1 for x in rows if x["pre_equal"]), len(rows)),
                                "post_equal": A3.rate(sum(1 for x in rows if x["post_equal"]), len(rows)),
                                "both_equal": A3.rate(sum(1 for x in rows if x["pre_equal"] and x["post_equal"]), len(rows)),
                                "post_jaccard_mean": A3._mean([x["post_jaccard"] for x in rows]),
                                "earliest_key": dict(Counter(x["earliest_key"] for x in rows if x["earliest_key"]))}
        # every-N stability against FULL (the quantity a global N_max is judged by)
        for label_n in ("800", "1600", "3200"):
            rows = [r for r in rs if r["runs"]["FULL"]["post_status"] == "CE_SELECTED" and r["runs"][label_n]["post_status"] == "CE_SELECTED"
                    and r["runs"][label_n]["info"]["scope"] == "UNIVERSE_BOUNDED"]
            rec[f"equal_to_FULL_at_{label_n}"] = A3.rate(sum(1 for r in rows if r["runs"][label_n]["post"] == r["runs"]["FULL"]["post"]
                                                             and r["runs"][label_n]["pre"] == r["runs"]["FULL"]["pre"]), len(rows))
        roll[label] = rec
    return roll


def stage_rollup(args, out_dir: Path) -> None:
    if (out_dir / "budget").is_dir():
        A3.write_json(out_dir / "n1_n2_budget_repair_rollup.json", rollup_budget(out_dir))
        rows = []
        for p in sorted((out_dir / "budget").glob("*.json.gz")):
            r = A3.read_json(p)
            for t in ("T0", "T2"):
                for key, c in r["by_template_set"][t]["n1"].items():
                    bp, bpost = key.split("|")
                    for ka in (0, 1):
                        pm = c[f"post_ka{ka}"]
                        rows.append({"item": r["item"]["key"], "cohort_group": r["item"]["cohort_group"], "templates": t, "mode": "N1",
                                     "B_pre": bp, "B_post": bpost, "K_A_post": ka, "pre_status": c["pre_status"], "post_status": pm.get("status"),
                                     "entity_nodes": pm.get("entity_nodes"), "optional_groups": pm.get("optional_groups"),
                                     "shared_information": pm.get("shared_information"), "distinct_keys": pm.get("distinct_keys"),
                                     "alt_covered": pm.get("alt_covered"), "alt_letters": pm.get("alt_letters"), "abs_exposed": pm.get("abs_exposed")})
                for key, pm in r["by_template_set"][t]["n2"].items():
                    bp, k = key.split("|")
                    rows.append({"item": r["item"]["key"], "cohort_group": r["item"]["cohort_group"], "templates": t, "mode": "N2",
                                 "B_pre": bp, "B_post": pm.get("cap"), "K_A_post": 0, "K_post_optional": k, "post_status": pm.get("status"),
                                 "entity_nodes": pm.get("entity_nodes"), "optional_groups": pm.get("optional_groups"),
                                 "shared_information": pm.get("shared_information"), "distinct_keys": pm.get("distinct_keys"),
                                 "alt_covered": pm.get("alt_covered"), "alt_letters": pm.get("alt_letters"), "abs_exposed": pm.get("abs_exposed")})
        A3.write_csv(out_dir / "n1_n2_budget_repair.csv", rows)
    if (out_dir / "bounding").is_dir():
        A3.write_json(out_dir / "h18_extension_rollup.json", rollup_bounding(out_dir))
        rows = []
        for p in sorted((out_dir / "bounding").glob("*.json.gz")):
            r = A3.read_json(p)
            for label, run in r["runs"].items():
                rows.append({"item": r["item"]["key"], "cohort_group": r["item"]["cohort_group"], "optional_total": r["optional_total"],
                             "level": label, "scope": run["info"]["scope"], "bounded_size": run["info"]["bounded_size"],
                             "pre_status": run["pre_status"], "post_status": run["post_status"], "seconds": run["seconds"],
                             "solves": run["solves"], "n_vars_max": run["n_vars_max"], "error": run["error"]})
            for st, c in r["comparisons"].items():
                rows.append({"item": r["item"]["key"], "cohort_group": r["item"]["cohort_group"], "optional_total": r["optional_total"],
                             "level": st, "pre_equal": c["pre_equal"], "post_equal": c["post_equal"], "post_jaccard": c["post_jaccard"],
                             "earliest_key": c["earliest_key"], "actually_bounded_at_a": c["actually_bounded_at_a"]})
        A3.write_csv(out_dir / "h18_extension.csv", rows)
    say("[rollup] written")


def stage_package(args, out_dir: Path) -> None:
    """Package the new evidence directory under the corrected protocol, after
    recording the integrity checks of the rebuilt ARCH-3 archive."""
    arch3_zip = ARCH3_DIR.parent / f"{ARCH3_DIR.name}.zip"
    checks: dict[str, Any] = {"protocol": "8H-B3-ARCH-3R/A", "date": TODAY}
    with zipfile.ZipFile(arch3_zip) as zf:
        names = zf.namelist()
        inner = json.loads(zf.read([x for x in names if x.endswith("CONTENT_MANIFEST.json")][0]))
        bad = zf.testzip()
    disk = A3.read_json(ARCH3_DIR / "CONTENT_MANIFEST.json")
    ext = (ARCH3_DIR.parent / f"{ARCH3_DIR.name}.zip.sha256").read_text(encoding="utf-8").split()[0]
    before = {}
    bf = out_dir / "package_integrity" / "arch3_rollups_before_repackage.sha256"
    if bf.is_file():
        for line in bf.read_text(encoding="utf-8").splitlines():
            h, _, path = line.partition("  ")
            before[Path(path).name] = h
    rollups_unchanged = all(A3.sha256_file(ARCH3_DIR / name) == h for name, h in before.items())
    checks["arch3_archive"] = {
        "archive": str(arch3_zip), "testzip_first_bad": bad, "zip_entries": len(names),
        "content_manifest_inside_equals_on_disk": inner == disk,
        "zip_entries_equal_manifest_expected": len(names) == disk["zip_entries_expected"],
        "regular_files_total": disk["regular_files_total"], "regular_files_in_zip": disk["regular_files_in_zip"],
        "excluded_regular_files": disk["excluded_regular_files"], "directory_entries_in_zip": disk["directory_entries_in_zip"],
        "stale_zip_manifest_present": (ARCH3_DIR / "zip_manifest.json").exists(),
        "stale_zip_manifest_inside_archive": any(x.endswith("zip_manifest.json") for x in names),
        "archive_digest_inside_manifest": any("archive_sha256" in k for k in disk),
        "external_digest_matches_archive": A3.sha256_file(arch3_zip) == ext, "external_digest": ext,
        "scientific_rollups_unchanged_by_repackage": rollups_unchanged, "rollups_checked": sorted(before),
    }
    A3.write_json(out_dir / "package_integrity" / "arch3_archive_check.json", checks)
    manifest = {
        "task": "Prompt 8H-B3-ARCH-3R — pre-freeze blocker resolution (DEVELOPMENT ONLY)",
        "label": "AUDIT / DECISION SUPPORT ONLY — NOT PRODUCTION B3 CODE — NOT A PUBLICATION RUN",
        "date": TODAY, "script": str(Path(__file__).resolve().relative_to(REPO_ROOT)), "script_sha256": A3.sha256_file(Path(__file__).resolve()),
        "arch3_script_sha256": A3.sha256_file(SCRIPTS / "audit_b3_choice_evidence_decisions.py"),
        "script_version": SCRIPT_VERSION, "python": platform.python_version(), "scipy": scipy.__version__,
        "git_head": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip(),
        "git_branch": subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip(),
        "inputs": {"arch3_evidence_dir": str(ARCH3_DIR), "arch3_universes": len(list((ARCH3_DIR / "universe").glob("*.json.gz"))),
                   "pinned_kg_sha256": A3.PINNED_KG_SHA256},
        "configuration": {"pre_arm": PRE_ARM, "B_pre_sweep": list(B_PRE_SWEEP), "N1_B_post_sweep": list(N1_B_POST_SWEEP),
                          "N2_K_sweep": list(N2_K_SWEEP), "designated": {"B_pre": DESIGNATED_B_PRE, "B_post": DESIGNATED_B_POST},
                          "measure_n_max_stratified": MEASURE_N_MAX, "h18_extension_n_max": list(H18_EXT_N_MAX),
                          "h18_extension_min_optional": H18_EXT_MIN_OPTIONAL, "pre_keys": list(A3.PRE_KEYS), "post_keys": list(A3.POST_KEYS),
                          "template_sets": "T0 production; T1 SAFE among the five high-impact keys; T2 all SAFE (template_candidates_v1.json)"},
        "provisional_decision_set": "ARCH-3R §H, used for analysis only; no memo line filled",
        "network": "none; pinned KG read-only for the census",
    }
    A3.write_json(out_dir / "run_manifest.json", manifest)
    (out_dir / "REPRODUCE.md").write_text(REPRODUCE_TEXT, encoding="utf-8")
    pkg = A3.build_package(out_dir, out_dir.parent / f"{out_dir.name}.zip", zip_max_mb=args.zip_max_mb)
    say(f"[package] {pkg['archive']} entries {pkg['zip_entries']} (expected {pkg['zip_entries_expected']}) testzip {pkg['testzip_first_bad']!r} "
        f"external digest verified {pkg['external_digest_verified']}")
    # the ARCHIVE_DIGEST record of the new archive lives OUTSIDE it, next to the .sha256 file
    A3.write_json(out_dir.parent / f"{out_dir.name}.ARCHIVE_DIGEST.json", pkg)


REPRODUCE_TEXT = """# Reproduction — B3 pre-freeze blocker resolution (DEVELOPMENT ONLY)

```bash
cd /home/thuy/projects/mcq_journal2
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
# ARCH-3 evidence directory must exist (universes, H5 audit); its archive is rebuilt by
python scripts/audit_b3_choice_evidence_decisions.py --stage package
# then, in order
python scripts/audit_b3_pre_freeze_resolution.py --stage census          # pinned KG read-only
python scripts/audit_b3_pre_freeze_resolution.py --stage candidates
python scripts/audit_b3_pre_freeze_resolution.py --stage coverage
python scripts/audit_b3_pre_freeze_resolution.py --stage coverage-secondary --workers 12
python scripts/audit_b3_pre_freeze_resolution.py --stage budget --workers 12
python scripts/audit_b3_pre_freeze_resolution.py --stage bounding --workers 12
python scripts/audit_b3_pre_freeze_resolution.py --stage rollup
python scripts/audit_b3_pre_freeze_resolution.py --stage package
```
"""


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="AUDIT / DECISION SUPPORT ONLY — NOT PRODUCTION B3 CODE (ARCH-3R).")
    parser.add_argument("--stage", choices=("census", "candidates", "coverage", "coverage-secondary", "budget", "bounding",
                                            "rollup", "package"), required=True)
    parser.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--zip-max-mb", type=int, default=20)
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    {"census": stage_census, "candidates": stage_candidates, "coverage": stage_coverage,
     "coverage-secondary": stage_coverage_secondary, "budget": stage_budget, "bounding": stage_bounding,
     "rollup": stage_rollup, "package": stage_package}[args.stage](args, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
