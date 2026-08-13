#!/usr/bin/env python
############################################################################
# scripts/run_phase_b2_answer.py
#
# Prompt 8H-B2-B driver: run ONE Answer end to end, from the automatic v5
# class ranking through the frozen Phase-B selection kernel, and write the
# reproducibility evidence for every stage.
#
# WHAT THIS SCRIPT IS
#   A thin sequencer. Every scientific decision belongs to a frozen module and
#   is delegated to it; see the module docstring of
#   `src/pipeline/phase_b2_answer_run.py` for the full ownership table and for
#   why each stage exists. This file adds argument parsing, one pinned-KG load
#   shared by every stage, progress output, and artefact writing.
#
# WHAT IT DELIBERATELY STOPS BEFORE
#   Verbalization, natural-language MCQ generation, choice-evidence bipartite
#   graph construction, the 100-Answer batch, and human evaluation. The run
#   ends at the frozen Phase-B selection result.
#
# NETWORK
#   Only stage E (class-member retrieval + redirect resolution) can touch the
#   network, and only with --allow-network. --offline-replay constructs the
#   fetcher with client=None, so a cache miss raises instead of silently
#   reaching for a transport; that makes "this replay made zero HTTP calls" a
#   property of the object graph rather than a claim about which branches ran.
#   Every retrieved page is stored in the normal SQLite cache in the normal
#   format, and a query failure, a successful zero-result and a cache hit stay
#   three distinguishable states.
############################################################################

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import mcq_inputs                                             # noqa: E402
from kg.loader import load_local_kg                           # noqa: E402
from mcq_core import Candidate                                # noqa: E402
from pipeline import phase_b2_answer_run as b2                # noqa: E402
from pipeline.rationale_v3_run import (                       # noqa: E402
    EVIDENCE_RULES_PATH,
    PREDICATE_POLICY_PATH,
    SEMANTIC_POLICY_PATH,
    build_semantic_index_from_pinned_kg,
)
from rationale_v3.evidence import (                           # noqa: E402
    derive_empirical_single_valued_rules,
    load_evidence_rules,
    observe_scope_cardinalities,
)
from rationale_v3.quality import load_quality_policy          # noqa: E402
from rationale_v3.semantic_relations import (                 # noqa: E402
    SemanticIndexCacheKey,
    load_semantic_index_cache,
    load_semantic_relation_policy,
    source_object_list_sha256,
)

DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "outputs" / "journal2_phase_b2_einstein_e2e_2026-08-13")


def say(message: str) -> None:
    print(message, flush=True)


def repo_relative(path) -> str:
    """`path` relative to the repository root when it lives there, else absolute.

    Artefacts normally land under `outputs/`, and a repo-relative string is what
    makes a provenance record portable. A replay may legitimately write to a
    scratch directory outside the repository, and that must be recorded rather
    than crash the run.
    """
    path = Path(path).resolve()
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def write_answer_fact_inventory(out, answer_uri, answer_facts, quality_policy) -> None:
    """Every one-hop Answer fact with its frozen R1 eligibility verdict.

    The COMPLETE inventory, ineligible facts included with their rejection
    reasons, because the rejected ones are exactly what a reviewer needs in
    order to check that the hard filter removed the right facts. `eligible` is
    the frozen R1 hard filter and is reported, never recomputed with different
    thresholds: `assess_fact_quality` is called here for its `rejection_reasons`
    field, which `mcq_core.FactQuality` does not carry, and its verdict is
    identical to the one already used upstream.
    """
    from rationale_v3.quality import assess_fact_quality

    rows = []
    for index, fact in enumerate(answer_facts):
        assessed = assess_fact_quality(
            answer_uri=answer_uri, predicate_uri=fact.predicate_uri,
            direction=fact.direction, counterpart_uri=fact.counterpart_uri,
            policy=quality_policy)
        rows.append({
            "fact_index": index,
            "predicate_uri": fact.predicate_uri,
            "direction": fact.direction,
            "counterpart_uri": fact.counterpart_uri,
            "display_label": fact.display_label,
            "eligible": fact.eligible,
            "rejection_reasons": ";".join(assessed.rejection_reasons),
            "soft_leak": fact.soft_leak,
            "verbalizable": fact.verbalizable,
            "template_id": fact.template_id,
            "pedagogical_tier": fact.pedagogical_tier,
        })
    b2.write_csv(out / "answer_fact_inventory.csv", list(rows[0].keys()), rows)


def write_evidence_detail(out, case, selection) -> None:
    """Per (selected rationale fact, distractor) evidence, on all three axes.

    Level, exclusion basis and granularity risk are SEPARATE AXES and are
    reported as such: an exclusion basis is not a weaker level, and a
    granularity risk is not a level at all. Every value is copied from the
    already-built `AnswerCase`, which got it from the frozen R1 classifier.
    """
    if selection is None:
        return
    positions = {d.candidate_uri if hasattr(d, "candidate_uri") else d.uri: d
                 for d in selection.distractors}
    rows = []
    for fact_index in selection.rationale.fact_indices:
        fact = case.facts[fact_index]
        for position, candidate in enumerate(case.candidates):
            if position not in selection.positions:
                continue
            rows.append({
                "fact_index": fact_index,
                "predicate_uri": fact.quality.predicate_uri,
                "direction": fact.quality.direction,
                "counterpart_uri": fact.quality.counterpart_uri,
                "counterpart_display_label": fact.quality.display_label,
                "distractor_uri": candidate.uri,
                "distractor_lrolesim_rank": candidate.rank,
                "distractor_lrolesim_score": repr(candidate.score),
                "evidence_level": fact.levels[position],
                "exclusion_basis": fact.exclusion_bases[position],
                "granularity_risk": fact.granularity_risks[position],
            })
    b2.write_csv(out / "rationale_evidence_detail.csv", list(rows[0].keys()), rows)


def write_final_selection_markdown(out, *, case, selection, record, walk, ranked,
                                   scored, semantic_index, source_count,
                                   key_digest) -> None:
    """The human-readable companion to `final_selection.json`.

    Every number below is read off the record the kernel produced; nothing is
    recomputed for display. The scientific caveats travel WITH the result rather
    than in a separate document, because a search scope or an optimality claim
    read without its caveat is exactly how a local exact result gets reported as
    a global one.
    """
    lines: list[str] = []
    add = lines.append
    add(f"# Phase B2 — final selection for {case.display_label}\n")
    add(f"**Answer** `{case.answer_uri}` · **display label** {case.display_label}\n")
    add(f"**Selected class** `{walk.selected_class_uri}`  ")
    add(f"(ranking position {walk.selected_ranking_position} of "
        f"{len(ranked)} feasible classes; the FIRST that passed the "
        f"local-mapping gate of {b2.LOCAL_MAPPING_GATE} — **not** a globally "
        f"optimal class)\n")
    add(f"**Class approval status** `{b2.B2_CLASS_APPROVAL_STATUS}`\n")

    add("\n## Search scope and optimality\n")
    add(f"| field | value |\n|---|---|")
    add(f"| complete ranked candidate pool | {record['original_candidate_count']} |")
    add(f"| search scope | `{record['search_scope']}` |")
    add(f"| bounded pool size | {record['pool_candidate_count']} |")
    add(f"| combinations enumerated | {record['enumerated_combination_count']} |")
    add(f"| feasible combinations | {record['feasible_combination_count']} |")
    add(f"| global_optimality_claim | {record['global_optimality_claim']} |")
    add(f"| pool_optimality_claim | {record['pool_optimality_claim']} |")
    add(f"| evidence policy | `{record['evidence_policy']}` |")
    add(f"| MCQ evidence level | `{record['mcq_evidence_level']}` |")
    add(f"\n> {record['search_scope_note']}\n")

    add("\n## Distractors\n")
    add("| # | distractor | LRoleSim rank | LRoleSim score | best evidence level |")
    add("|---|---|---|---|---|")
    for number, d in enumerate(record["distractors"], start=1):
        add(f"| {number} | `{d['candidate_uri']}` | {d['lrolesim_rank']} | "
            f"{d['lrolesim_score']:.12f} | {d['best_evidence_level']} |")

    add("\n## Minimum rationale\n")
    add(f"Exact minimum cardinality **|R\\*| = {record['minimum_rationale_size']}**, "
        f"minimum level **{record['minimum_rationale_level']}**, "
        f"{record['minimum_rationale_count_enumerated']} minimum-cardinality "
        f"cover(s) enumerated.\n")
    add("| predicate | direction | counterpart | template | verbalizable | tier |")
    add("|---|---|---|---|---|---|")
    for fact in record["rationale"]:
        add(f"| `{fact['predicate_uri']}` | {fact['direction']} | "
            f"`{fact['counterpart_uri']}` ({fact['display_label']}) | "
            f"`{fact['template_id']}` | {fact['verbalizable']} | "
            f"{fact['pedagogical_tier']} |")

    add("\n## Six-key candidate-combination objective\n")
    add("| key | field | value |\n|---|---|---|")
    add(f"| 1 | `-lrolesim_score_sum` | {record['lrolesim_score_sum']!r} |")
    add(f"| 2 | `-lrolesim_score_min` | {record['lrolesim_score_min']!r} |")
    add(f"| 3 | `minimum_rationale_size` | {record['minimum_rationale_size']} |")
    add(f"| 4 | rationale ranking key | `{record['rationale_ranking_key']}` |")
    add(f"| 5 | `candidate_rank_sum` | {record['candidate_rank_sum']} |")
    add(f"| 6 | `candidate_uris` | "
        + ", ".join(f"`{d['candidate_uri']}`" for d in record["distractors"]) + " |")
    add(f"\n> {record['candidate_rank_sum_note']}\n")

    add("\n## Local candidate-pool anonymity\n")
    add(f"`local_candidate_pool_anonymity_count` = "
        f"{record['local_candidate_pool_anonymity_count']}, ratio "
        f"{record['local_candidate_pool_anonymity_ratio']!r}, "
        f"`direct_identifier_flag` = {record['direct_identifier_flag']}.\n")
    add(f"> {record['local_candidate_pool_anonymity_note']}\n")

    add("\n## Answer facts\n")
    eligible = len(case.eligible_fact_indices)
    add(f"{len(case.facts)} distinct one-hop observed facts, **{eligible} "
        f"eligible** after the frozen R1 hard filter, "
        f"{len(case.facts) - eligible} rejected. Per-fact rejection reasons are "
        f"in `answer_fact_inventory.csv`.\n")

    add("\n## Semantic index\n")
    add(f"Rebuilt for this Answer's exact enlarged source-object set: "
        f"{source_count} objects, "
        f"`source_object_list_sha256 = {key_digest}`, "
        f"available = {semantic_index.available}.\n")

    add("\n## Scientific caveats carried with this result\n")
    add(f"- {record['open_world_note']}")
    add(f"- {record['lrolesim_role_note']}")
    add(f"- {record['evidence_rescue_note']}")
    add("- L0 is snapshot absence only and is never shown to a student as a "
        "reason. Every rationale fact above covers all three distractors at "
        "L1 or higher.")
    (out / "final_selection.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Run one Answer end to end: v5 class ranking -> local "
                     "mapping feasibility -> M1 graph -> frozen LRoleSim -> "
                     "semantic-index rebuild -> frozen Phase-B selection."),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--answer-uri", default=b2.DEFAULT_ANSWER_URI)
    parser.add_argument(
        "--v5-results", required=True, type=Path,
        help="results.jsonl written by scripts/run_category_selector_v5.py")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--member-cache", type=Path,
        default=REPO_ROOT / "data" / "cache" / "phase_b2_class_members_v1.sqlite",
        help="SQLite page cache for class-member and redirect queries")
    parser.add_argument(
        "--score-cache", type=Path,
        default=REPO_ROOT / "data" / "cache" / "phase_b2_graph_lrolesim_v1.jsonl",
        help="LRoleSim score cache, keyed by the full run fingerprint")
    parser.add_argument(
        "--semantic-index-cache", type=Path,
        default=(REPO_ROOT / "data" / "semantic_index_v3"
                 / "phase_b2_einstein_containment_v1.json"),
        help="where the REBUILT semantic index is written; never the pilot cache")
    parser.add_argument(
        "--max-classes", type=int, default=12,
        help=("maximum ranked classes whose members may be retrieved before the "
              "walk gives up; exhausting it is reported as a walk failure, "
              "never as 'no feasible class exists'"))
    parser.add_argument(
        "--allow-network", action="store_true",
        help="opt in to contacting DBpedia for class members and redirects")
    parser.add_argument(
        "--offline-replay", action="store_true",
        help="strict offline: a cache miss raises instead of issuing HTTP")
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.allow_network and args.offline_replay:
        say("ERROR: --allow-network and --offline-replay are mutually exclusive")
        return 2
    if not args.allow_network and not args.offline_replay:
        say("ERROR: choose exactly one of --allow-network / --offline-replay; "
            "network access is denied by default")
        return 2

    # Resolved before use: every artefact path below is later reported relative
    # to the repository root, which a relative --output-dir would make
    # impossible.
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    manifest: dict = {
        "answer_uri": args.answer_uri,
        "mode": "live" if args.allow_network else "offline-replay",
        "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }

    # --- Stage 0: the pinned local KG, verified then loaded ONCE ------------
    say("[0] loading the pinned local KG (SHA-256 verified before use) ...")
    local_kg = load_local_kg(b2.PINNED_LOCAL_KG,
                             verify_sha256=b2.PINNED_LOCAL_KG_SHA256)
    say(f"    pinned KG sha256={local_kg.source_sha256}")
    manifest["pinned_kg_sha256"] = local_kg.source_sha256

    quality_policy = load_quality_policy(PREDICATE_POLICY_PATH)
    semantic_policy = load_semantic_relation_policy(SEMANTIC_POLICY_PATH)
    base_rules = load_evidence_rules(EVIDENCE_RULES_PATH)

    # --- Stage 1: the automatic v5 ranking, read and never recomputed -------
    say("[1] reading the automatic v5 class ranking ...")
    selection = b2.load_v5_selection(args.v5_results, args.answer_uri)
    display_label = selection["display_label"]
    ranked = b2.ranked_feasible_classes(selection)
    encoder = selection.get("encoder_metadata") or {}
    say(f"    {len(ranked)} feasible classes; ranking mode="
        f"{selection['mode']}, alpha={selection['config'].get('alpha')}, "
        f"sbert_available={encoder.get('available')}")
    manifest["class_ranking"] = {
        "mode": selection["mode"],
        "alpha": selection["config"].get("alpha"),
        "encoder_supplied": selection["config"].get("encoder_supplied"),
        "sbert_available": encoder.get("available"),
        "sbert_abstract_chunks": encoder.get("abstract_chunks"),
        "feasible_class_count": len(ranked),
        "evaluated_class_count": selection.get("number_of_categories"),
        "rejected_by_reason": selection.get("number_rejected_by_reason"),
        "selection_provenance": selection.get("selection_provenance"),
        "v5_top1_class_uri": selection.get("selected_class"),
        "leakage_policy_sha256": selection["config"].get("leakage_policy_sha256"),
    }
    b2.write_csv(out / "class_ranking_complete.csv",
                 list(ranked[0].as_record().keys()),
                 [r.as_record() for r in ranked])

    # --- Stage E: local-mapping feasibility ---------------------------------
    say(f"[E] walking the ranking for local-mapping feasibility "
        f"(gate: >= {b2.LOCAL_MAPPING_GATE} mapped candidates excluding the "
        f"Answer) ...")
    if args.allow_network:
        retriever, redirects, fetcher, cache = b2.open_live_retrieval(
            cache_path=args.member_cache)
    else:
        retriever, redirects, fetcher, cache = b2.open_offline_retrieval(
            cache_path=args.member_cache)
    local_lookup = b2.make_local_lookup(local_kg.url_index)

    walk = b2.walk_ranked_classes_for_local_mapping(
        args.answer_uri, ranked,
        retriever=retriever, redirect_source=redirects,
        local_lookup=local_lookup, max_classes=args.max_classes,
        progress=say)

    b2.write_csv(out / "class_attempts_and_mapping.csv",
                 list(walk.attempts[0].as_record().keys()),
                 [a.as_record() for a in walk.attempts])
    manifest["local_mapping"] = {
        "status": walk.status,
        "selected_class_uri": walk.selected_class_uri,
        "selected_ranking_position": walk.selected_ranking_position,
        "answer_local_index": walk.answer_local_index,
        "gate": b2.LOCAL_MAPPING_GATE,
        "classes_retrieved": sum(1 for a in walk.attempts if a.attempted),
        "network_pages": fetcher.network_page_count,
        "cache_hits": fetcher.cache_hit_count,
        "failed_pages": fetcher.failed_page_count,
    }
    say(f"    {walk.status}"
        + (f" -> rank {walk.selected_ranking_position} "
           f"{walk.selected_class_uri}" if walk.is_feasible else ""))
    say(f"    network pages={fetcher.network_page_count}, "
        f"cache hits={fetcher.cache_hit_count}, failed={fetcher.failed_page_count}")

    if not walk.is_feasible:
        manifest["outcome"] = "BLOCKED_NO_LOCALLY_MAPPING_FEASIBLE_CLASS"
        b2.write_json(out / "run_manifest.json", manifest)
        say("STOP: no ranked class passed the local-mapping gate. That is a "
            "feasibility measurement, not an error to repair.")
        return 1

    mapping = walk.selected_mapping
    b2.write_jsonl(out / "mapped_candidates.jsonl", [
        {"answer_uri": walk.answer_uri,
         "class_uri": walk.selected_class_uri,
         "ranking_position": walk.selected_ranking_position,
         **member.as_record()}
        for member in mapping.members])
    b2.write_json(out / "selected_class_provenance.json", {
        "answer_uri": walk.answer_uri,
        "display_label": display_label,
        "selected_class_uri": walk.selected_class_uri,
        "selected_ranking_position": walk.selected_ranking_position,
        "selection_rule": (
            "first class of the automatic v5 feasible ranking, in ranking "
            "order, that passed the declared local-mapping gate of "
            f"{b2.LOCAL_MAPPING_GATE} distinct locally mapped candidates "
            "excluding the Answer"),
        "class_approval_status": b2.B2_CLASS_APPROVAL_STATUS,
        "not_a_global_optimality_claim": (
            "This is the first locally mapping-feasible class of a ranking, "
            "not a globally optimal class. The classes ranked below it were "
            "never tested and are not claimed to be worse."),
        "v5_selection_provenance": selection.get("selection_provenance"),
        "ranking_row": next(r.as_record() for r in ranked
                            if r.class_uri == walk.selected_class_uri),
        "retrieval": mapping.retrieval.as_record(),
        "mapping_summary": mapping.as_summary_record(),
    })

    # --- Stage F: M1 graph and the frozen LRoleSim ranking ------------------
    say("[F] building the M1 graph and running the frozen LRoleSim ...")
    attempt, graph_result, scored, fingerprint, lrolesim_provenance = (
        b2.build_graph_and_rank(
            walk, local_kg, display_label=display_label,
            score_cache_path=args.score_cache, progress=say))
    b2.write_json(out / "m1_graph_manifest.json", {
        "answer_uri": walk.answer_uri,
        "selected_class_uri": walk.selected_class_uri,
        **attempt.as_row(),
        "lrolesim": ({} if fingerprint is None else fingerprint.as_record()),
        "lrolesim_provenance": lrolesim_provenance,
        "policy_note": (
            "Every admitted candidate carries its COMPLETE URI-valued one-hop "
            "IN/OUT neighbourhood; a candidate whose neighbourhood does not fit "
            "the node budget is rejected outright and never partially "
            "truncated. Context nodes are not distractor candidates."),
    })
    if graph_result is None:
        manifest["outcome"] = "BLOCKED_GRAPH_BUDGET_INSUFFICIENT"
        manifest["graph"] = attempt.as_row()
        b2.write_json(out / "run_manifest.json", manifest)
        say("STOP: the M1 graph retained too few candidates. Feasibility "
            "measurement, not an error to repair.")
        return 1

    manifest["graph"] = attempt.as_row()
    manifest["lrolesim"] = {
        "ranker_name": mcq_inputs.PINNED_LROLESIM_EXECUTION["ranker_name"],
        "measure": mcq_inputs.PINNED_LROLESIM_EXECUTION["measure"],
        "lrolesim_beta": mcq_inputs.PINNED_LROLESIM_EXECUTION["lrolesim_beta"],
        "iterations": mcq_inputs.PINNED_LROLESIM_EXECUTION["iterations"],
        "iteration_mode": mcq_inputs.PINNED_LROLESIM_EXECUTION["iteration_mode"],
        "complete_ranked_pool_size": len(scored),
        "run_fingerprint": fingerprint.run_fingerprint,
        **lrolesim_provenance,
    }

    # The COMPLETE ranked candidate pool. Contiguous ranks from 1, exact
    # scores, canonical URIs. This is the anonymity denominator and the thing
    # `Candidate.rank` indexes -- NOT the bounded search pool the kernel may
    # later choose to search, which is the kernel's own decision to make and to
    # report.
    b2.write_jsonl(out / "complete_lrolesim_ranking.jsonl", [
        {"answer_uri": walk.answer_uri,
         "selected_class_uri": walk.selected_class_uri,
         "rank": c.rank,
         "canonical_candidate_uri": c.canonical_uri,
         "score": c.score,
         "candidate_local_index": c.local_index,
         "tie_group_id": c.tie_group_id,
         "tie_group_size": c.tie_group_size,
         "at_beta_floor": c.at_beta_floor,
         "mapping_origin": c.mapping_origin,
         "admission_position": c.admission_position,
         "ranker_name": mcq_inputs.PINNED_LROLESIM_EXECUTION["ranker_name"],
         "measure": mcq_inputs.PINNED_LROLESIM_EXECUTION["measure"],
         "lrolesim_beta": mcq_inputs.PINNED_LROLESIM_EXECUTION["lrolesim_beta"],
         "iterations": mcq_inputs.PINNED_LROLESIM_EXECUTION["iterations"],
         "iteration_mode": mcq_inputs.PINNED_LROLESIM_EXECUTION["iteration_mode"],
         "graph_run_fingerprint": fingerprint.run_fingerprint}
        for c in scored])
    b2.write_csv(out / "complete_lrolesim_ranking.csv",
                 ["rank", "canonical_candidate_uri", "score", "tie_group_id",
                  "tie_group_size", "at_beta_floor", "mapping_origin",
                  "admission_position"],
                 [{"rank": c.rank, "canonical_candidate_uri": c.canonical_uri,
                   "score": repr(c.score), "tie_group_id": c.tie_group_id,
                   "tie_group_size": c.tie_group_size,
                   "at_beta_floor": c.at_beta_floor,
                   "mapping_origin": c.mapping_origin,
                   "admission_position": c.admission_position}
                  for c in scored])

    candidates = tuple(Candidate(rank=c.rank, score=c.score, uri=c.canonical_uri)
                       for c in scored)

    # --- Stage G: the exact enlarged source-object set, then the rebuild ----
    say("[G] deriving the exact enlarged semantic-index source-object set ...")
    answer_facts = mcq_inputs.answer_facts_from_local_kg(
        args.answer_uri, local_kg=local_kg, quality_policy=quality_policy)
    observed_by_candidate = {
        candidate.uri: mcq_inputs.candidate_objects_from_local_kg(
            candidate.uri, local_kg=local_kg)
        for candidate in candidates}
    sources = b2.enlarged_source_object_uris(answer_facts, observed_by_candidate)
    file_digest = b2.write_source_object_list(
        out / "semantic_source_objects.txt", sources)
    key_digest = source_object_list_sha256(sources)
    eligible = sum(1 for f in answer_facts if f.eligible)
    say(f"    {len(answer_facts)} Answer facts ({eligible} eligible), "
        f"{len({f.predicate_direction_key for f in answer_facts})} distinct "
        f"predicate-direction keys, {len(sources)} source objects")
    say(f"    source_object_list_sha256={key_digest}")

    say("[G] rebuilding the semantic index OFFLINE from the pinned KG ...")
    index_path = build_semantic_index_from_pinned_kg(
        policy_path=SEMANTIC_POLICY_PATH,
        cache_path=args.semantic_index_cache,
        source_object_uris=sources,
        local_kg=local_kg,
        verbose=True)
    expected_key = SemanticIndexCacheKey(
        pinned_kg_sha256=b2.PINNED_LOCAL_KG_SHA256,
        policy_sha256=semantic_policy.policy_sha256,
        source_object_list_sha256=key_digest,
        max_depth=semantic_policy.max_depth,
        creation_command=("python scripts/run_phase_b2_answer.py "
                          "(build_semantic_index_from_pinned_kg)"))
    semantic_index = load_semantic_index_cache(
        index_path, policy=semantic_policy, expected_key=expected_key)
    say(f"    semantic index available={semantic_index.available} "
        f"reason={semantic_index.unavailable_reason!r}")
    b2.write_json(out / "semantic_index_manifest.json", {
        "cache_path": repo_relative(index_path),
        "cache_output_sha256": b2.sha256_of_text(
            Path(index_path).read_text("utf-8")),
        "pinned_kg_sha256": b2.PINNED_LOCAL_KG_SHA256,
        "semantic_policy_sha256": semantic_policy.policy_sha256,
        "max_depth": semantic_policy.max_depth,
        "source_object_count": len(sources),
        "source_object_list_sha256_cache_key": key_digest,
        "source_object_list_file_sha256": file_digest,
        "available": semantic_index.available,
        "unavailable_reason": semantic_index.unavailable_reason,
        "cache_key": (None if semantic_index.cache_key is None
                      else semantic_index.cache_key.as_record()),
        "why_rebuilt": (
            "source_object_list_sha256 is part of the cache key, so the pilot "
            "index legitimately refuses to load for a different source-object "
            "set. Reusing it would be a cache-key violation; leaving it "
            "unavailable would leave every L1 pair carrying "
            "UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE for no reason. An "
            "unavailable index NEVER turns an observed alternative L1 into L0."),
    })

    # --- The rulebook: the frozen base, plus R1's own scoped-empirical
    # derivation over THIS Answer's scope. Derived exactly the way
    # `rationale_v3_run.derive_rulebook` derives it, over the same observation
    # shape, with the same rejected-predicate map, so SCOPED_EMPIRICAL keeps
    # its frozen meaning: an annotation on an existing L1, never a fourth
    # level, and never able to create, upgrade or rescue one.
    scope = walk.selected_class_uri
    observations: dict[str, dict] = {args.answer_uri: {}}
    for fact in answer_facts:
        observations[args.answer_uri].setdefault(
            fact.predicate_direction_key, set()).add(fact.counterpart_uri)
    for uri, observed in observed_by_candidate.items():
        observations[uri] = {key: set(objects) for key, objects in observed.items()}
    rows = observe_scope_cardinalities(
        scope=scope,
        observations={entity: {key: sorted(values) for key, values in keys.items()}
                      for entity, keys in observations.items()},
        semantic_index=semantic_index)
    derived = derive_empirical_single_valued_rules(
        rows, config=base_rules.derivation,
        rejected_predicates=quality_policy.hard_reject_predicates)
    rulebook = base_rules.with_rules(derived)
    say(f"    rulebook: {len(derived)} scoped-empirical rule candidates derived, "
        f"counts={rulebook.counts()}")
    b2.write_jsonl(out / "scoped_empirical_rules.jsonl",
                   [rule.as_record() for rule in derived])

    # --- Stage H: the frozen Phase-B selection ------------------------------
    say("[H] calling mcq_inputs.build_and_select() ...")
    provenance = {
        "candidate_roster_source": repo_relative(
            out / "complete_lrolesim_ranking.jsonl"),
        "candidate_roster_sha256": b2.candidate_roster_digest(scored),
        "candidate_roster_is_complete_admitted_pool": True,
        "selected_class_uri": walk.selected_class_uri,
        "class_approval_status": b2.B2_CLASS_APPROVAL_STATUS,
        **mcq_inputs.PINNED_LROLESIM_EXECUTION,
    }
    case, selected, record = mcq_inputs.build_and_select(
        args.answer_uri, display_label, candidates,
        local_kg=local_kg, quality_policy=quality_policy,
        semantic_index=semantic_index, rulebook=rulebook,
        scope=scope, provenance=provenance)

    b2.write_json(out / "final_selection.json", record)
    write_answer_fact_inventory(out, args.answer_uri, answer_facts, quality_policy)
    write_evidence_detail(out, case, selected)
    write_final_selection_markdown(
        out, case=case, selection=selected, record=record, walk=walk,
        ranked=ranked, scored=scored, semantic_index=semantic_index,
        source_count=len(sources), key_digest=key_digest)
    manifest["selection"] = {
        "outcome": record["phase_b1_provenance"]["selection_outcome"],
        "search_scope": record["phase_b1_provenance"]["search_scope"],
        "global_optimality_claim":
            record["phase_b1_provenance"]["global_optimality_claim"],
        "original_candidate_count": len(case.candidates),
        "eligible_fact_count": len(case.eligible_fact_indices),
        "total_fact_count": len(case.facts),
    }
    manifest["outcome"] = record["phase_b1_provenance"]["selection_outcome"]
    manifest["finished_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest["duration_seconds"] = round(time.time() - started, 3)
    b2.write_json(out / "run_manifest.json", manifest)

    say("")
    say(f"    outcome            : {manifest['outcome']}")
    say(f"    search scope       : {manifest['selection']['search_scope']}")
    say(f"    optimality claim   : {manifest['selection']['global_optimality_claim']}")
    say(f"    complete pool size : {len(case.candidates)}")
    say(f"    eligible facts     : {len(case.eligible_fact_indices)} / {len(case.facts)}")
    if selected is not None:
        say(f"    distractors        : "
            + ", ".join(d.uri for d in selected.distractors))
        rationale = selected.rationale
        say(f"    minimum rationale  : {selected.minimum_rationale_size} fact(s), "
            f"min level {selected.minimum_rationale_level}")
        # The count is over the Answer PLUS the complete ranked pool, so the
        # denominator is len(candidates) + 1. Printing the pool size alone here
        # would contradict the ratio on the very next line.
        say(f"    anonymity          : "
            f"{rationale.local_candidate_pool_anonymity_count} of "
            f"{len(case.candidates) + 1} entities (Answer + COMPLETE ranked "
            f"pool of {len(case.candidates)}) match the rationale, ratio "
            f"{rationale.local_candidate_pool_anonymity_ratio:.4f}")
        for index, identity in zip(rationale.fact_indices,
                                   rationale.fact_identities):
            say(f"      fact[{index}] {identity}")
    say("")
    say(f"    artefacts -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
