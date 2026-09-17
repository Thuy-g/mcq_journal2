#!/usr/bin/env python
############################################################################
# scripts/run_phase_b2_any_answer_v4.py
#
# Prompt 8H-B2-G driver — the FINAL-BENCHMARK CANDIDATE runner.
#
# This is a NEW runner. `scripts/run_phase_b2_any_answer_v3.py` and
# `src/pipeline/phase_b2_any_answer_run_v3.py` are NOT modified and NOT removed:
# they produced the published B2-E/B2-F evidence and their defaults ARE the
# fingerprint of those results. Everything the two runners share is imported
# from the v3 driver rather than copied, so the per-Answer report sections
# [A]-[L] cannot drift between them.
#
# WHAT IS NEW IN v4, AND WHY EACH THING EXISTS
# ---------------------------------------------
#   --rationale-objective v3        §7. v3 is the v4 CANDIDATE DEFAULT. The v3
#                                   runner defaults to objective v2, which does
#                                   not repair the Augustus option-reference
#                                   conflict; objective v3 places the semantic
#                                   granularity risk and the conflict above the
#                                   SCOPED_EMPIRICAL annotation, which is the
#                                   only placement that does. Both are shipped.
#   --max-nodes 5000                §8. The v4 CANDIDATE M1 node budget. The
#                                   frozen 1200 is unchanged and remains
#                                   selectable, so the 1200-vs-5000 comparison
#                                   is a measurement and not a claim.
#   --predicate-alias-policy v1     §5. The audited `dbp:field` / `dbp:fields`
#                                   slot family, applied to the CANDIDATE's
#                                   observed objects for evidence lookup only.
#   --candidate-type-policy         §2. Now THREE arms: observe-only,
#                                   person-guarded (rejects a confirmed
#                                   NOT_PERSON, keeps UNKNOWN) and
#                                   person-strict.
#   --granularity-risk-policy       §6. report-only (historical) or
#                                   require-clean (a learner-facing main
#                                   rationale must carry zero granularity risk).
#   --v3-compatible                 Name the B2-E/F generation of everything at
#                                   once, so a delta audit runs both arms from
#                                   one script.
#   corrected batch metrics         §3 detection-vs-rejection, §10 class-leak
#                                   rejections that are no longer a silent zero,
#                                   §11 the L1+ student-showable rank-retention
#                                   denominator beside the unchanged any-kernel
#                                   one, §12 |R*| in its own column.
#
# WHAT IT STOPS BEFORE
#   Verbalization, MCQ prose, the choice-evidence bipartite graph, the ~100-item
#   publication benchmark and human evaluation. The run ends at the frozen
#   Phase-B selection result plus the §6 policy record.
#
# NOTHING HERE IS A PUBLICATION DEFAULT. Prompt 8H-B2-G produces the evidence a
# human researcher needs in order to choose one.
#
# NETWORK
#   Exactly one of --allow-network / --offline-replay is required; neither is
#   the default. Under --offline-replay every client is constructed so that a
#   cache miss RAISES.
############################################################################

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import category_extractor_v6 as v6                              # noqa: E402
import mcq_core                                                 # noqa: E402
import mcq_inputs                                               # noqa: E402
import run_category_selector_v6 as selector_cli                 # noqa: E402
# The v2 and v3 drivers are imported READ-ONLY, for their presentation helpers,
# their strict-offline SPARQL client and their argument plumbing. Nothing here
# writes to them, and `say()` shares the v2 TRANSCRIPT so one report file is
# still literally the terminal session.
import run_phase_b2_any_answer_v2 as v2cli                      # noqa: E402
import run_phase_b2_any_answer_v3 as v3cli                      # noqa: E402
from classes.answer_identity import (                           # noqa: E402
    IdentityStatus,
    LocalResolutionMethod,
    SparqlIdentitySource,
    resolve_answer_identity,
)
from classes.class_leakage import (                             # noqa: E402
    DEFAULT_DERIVATIONAL_POLICY,
    DERIVATIONAL_POLICY_V2,
)
from classes.wikipedia_lead import (                            # noqa: E402
    DEFAULT_USER_AGENT,
    RequestsWikipediaTransport,
    WikipediaLeadCache,
    WikipediaLeadClient,
)
from kg.loader import load_local_kg                             # noqa: E402
from mcq_core import Candidate                                  # noqa: E402
from pipeline import phase_b2_answer_run as b2                  # noqa: E402
from pipeline import phase_b2_any_answer_run as anyb2           # noqa: E402
from pipeline import phase_b2_any_answer_run_v3 as v3           # noqa: E402
from pipeline import phase_b2_any_answer_run_v4 as v4           # noqa: E402
from pipeline.rationale_v3_run import (                         # noqa: E402
    EVIDENCE_RULES_PATH,
    build_semantic_index_from_pinned_kg,
)
from rationale_v3.evidence import (                             # noqa: E402
    derive_empirical_single_valued_rules,
    load_evidence_rules,
    observe_scope_cardinalities,
)
from rationale_v3.predicate_aliases import (                    # noqa: E402
    DEFAULT_ALIAS_POLICY,
    NO_ALIAS_POLICY,
)
from rationale_v3.quality import load_quality_policy            # noqa: E402
from rationale_v3.semantic_relations import (                   # noqa: E402
    SemanticIndexCacheKey,
    load_semantic_index_cache,
    load_semantic_relation_policy,
    source_object_list_sha256,
)
from selection.granularity_clean import (                       # noqa: E402
    GRANULARITY_POLICY_REPORT_ONLY,
    GRANULARITY_POLICY_REQUIRE_CLEAN,
    REPORT_ONLY_POLICY,
    REQUIRE_CLEAN_POLICY,
    STATUS_NO_GRANULARITY_CLEAN_RATIONALE,
    apply_granularity_policy,
)

S = anyb2.AnswerStatus

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_BLOCKED = 1

#: A v4-only failure status. It is NOT a new evidence level and NOT a new
#: failure of the kernel: the kernel produced a selection and the §6 policy
#: refused to call it learner-facing. It is reported separately so the yield
#: table can never confuse "no rationale exists" with "no SAFE rationale
#: exists".
STATUS_NO_GRANULARITY_CLEAN = STATUS_NO_GRANULARITY_CLEAN_RATIONALE

TRANSCRIPT = v2cli.TRANSCRIPT
say = v2cli.say


# ==========================================================================
# 1) Per-Answer pipeline, v4
# ==========================================================================


def run_one_answer(original_uri, *, cohort, source_line, context, args, out_dir):
    """The complete per-Answer pipeline. Never raises for a scientific failure.

    Identical to the v3 pipeline stage for stage, with four versioned changes:

      * §8 the M1 graph is built under the DECLARED node budget and its budget
        diagnostics are kept even when the stage fails;
      * §5 the audited predicate-slot alias policy reaches BOTH the
        semantic-index source-object set and the evidence classification, which
        it must, because the source set is the cache key;
      * §7 the rationale objective comes from the configuration and defaults to
        v3;
      * §6 the granularity-risk policy is applied to the kernel's selection.
      * §10 the class-feature rejection records are carried onto the result.
    """
    started = time.time()
    config = context["config"]
    result = anyb2.AnswerRunResult(original_uri=original_uri, cohort=cohort,
                                   alpha=args.alpha)
    result.source_line_number = source_line
    result.candidate_screen = None
    # §10. The batch metric reads THIS attribute. It is initialised to an empty
    # tuple rather than left absent, so "no class was rejected" and "the wiring
    # broke" are different observations downstream.
    result.class_ranking_rejections = ()
    result.graph_budget_diagnostics = None
    result.granularity_outcome = None

    def finish(status: str, detail: str = "") -> anyb2.AnswerRunResult:
        result.status = status
        result.detail = detail
        result.seconds = time.time() - started
        result.sparql_stats = dict(context["sparql"].stats())
        result.fetcher_stats = dict(context["fetcher"].counters())
        return result

    # --- A. AnswerIdentity -------------------------------------------------
    say(f"[A] resolving the Answer identity for {original_uri} ...")
    identity = resolve_answer_identity(
        original_uri, local_lookup=context["local_lookup"],
        source=context["identity_source"])
    result.identity = identity
    say(f"    original URI      : {identity.original_uri}")
    say(f"    remote query URI  : {identity.remote_query_uri}")
    say(f"    pinned local URI  : {identity.local_kg_uri}  "
        f"(local index {identity.local_index})")
    say(f"    local resolution  : {identity.local_resolution_method}")
    say(f"    remote redirect   : {identity.remote_redirect_status}"
        + (f"  chain {' -> '.join(identity.remote_redirect_chain)}"
           if identity.remote_redirect_chain else ""))
    if identity.resolution_status == IdentityStatus.INPUT_INVALID.value:
        return finish(S.INPUT_INVALID, identity.detail)
    if identity.local_resolution_method == LocalResolutionMethod.AMBIGUOUS.value:
        return finish(S.AMBIGUOUS_LOCAL_ALIAS, identity.detail)
    if not identity.resolved:
        return finish(S.NO_LOCAL_URI_IDENTITY, identity.detail)

    answer_local_uri = identity.local_kg_uri
    answer_remote_uri = identity.remote_query_uri

    # --- B/C. the automatic v6 class ranking -------------------------------
    say(f"[B] extracting v6 class features (alpha={args.alpha}, "
        f"semantic source = {context['semantic_source'].value}, "
        f"class-leakage policy = {config.derivational_policy.version}) ...")
    lead = None
    if context["leads"] is not None:
        lead = context["leads"].fetch_many([answer_remote_uri]).get(answer_remote_uri)
    features = v6.extract_answer_features(
        answer_remote_uri,
        runner=context["sparql"], idf_universe=context["universe"],
        semantic_source=context["semantic_source"], wikipedia_lead=lead,
        encoder=context["encoder"], quality_policy=context["quality_policy"],
        max_remote_candidates=args.max_remote_candidates,
        min_remote_candidates=args.min_remote_candidates,
        derivational=config.derivational_policy)
    result.display_label = features.answer_label
    result.categories_discovered = features.categories_discovered
    result.feasible_class_count = len(features.feasible_classes)
    result.rejected_class_count = len(features.rejected_classes)
    # §10: the records the v3 batch metric silently could not find.
    result.class_ranking_rejections = v4.class_rejection_records(features)

    semantic = features.semantic
    say(f"    Wikipedia title   : "
        f"{semantic.wikipedia_title if semantic else None}")
    say(f"    revision ID       : "
        f"{semantic.wikipedia_revision_id if semantic else None}")
    say(f"    lead SHA-256      : {semantic.text_sha256 if semantic else None}")
    say(f"    semantic status   : {semantic.status.value if semantic else None}")
    say(f"    categories found  : {features.categories_discovered}  "
        f"({result.feasible_class_count} feasible, "
        f"{result.rejected_class_count} rejected)  status={features.status}")
    if result.class_ranking_rejections:
        say(f"    class rejections  : "
            f"{_reject_code_counts(result.class_ranking_rejections)}")
        for record in result.class_ranking_rejections:
            if record["leak_level"] == "hard_leak":
                say(f"       HARD LEAK {record['category_uri']}  "
                    f"primary={record['primary_rejected_code']}  "
                    f"reasons={record['all_rejection_reasons']}  "
                    f"evidence={record['leak_evidence']}")

    if features.status == v6.STATUS_QUERY_FAILED:
        return finish(S.QUERY_FAILED, features.error or "a SPARQL query failed")
    if features.status == v6.STATUS_IDF_UNAVAILABLE:
        return finish(S.IDF_UNIVERSE_UNAVAILABLE, features.error or "")
    if features.status == v6.STATUS_NO_CATEGORIES:
        return finish(S.NO_CURRENT_DBPEDIA_CATEGORIES,
                      "the current endpoint returned no dcterms:subject "
                      "categories for the remote query URI")

    ranking = v6.rank_feasible_classes(features, args.alpha)
    result.scoring_mode = ranking.scoring_mode.value
    ranked = anyb2.ranked_classes_from_v6(ranking)
    result.class_ranking = ranked
    v2cli.print_class_ranking(ranking, context["universe"], args.alpha)
    if not ranked:
        return finish(S.NO_USABLE_CLASS,
                      "every discovered category was rejected by the feasibility "
                      "gates (size, administrative, or answer-revealing name)")

    # --- E. the local-mapping walk -----------------------------------------
    say(f"[E] walking the ranking for local-mapping feasibility "
        f"(gate: >= {b2.LOCAL_MAPPING_GATE} mapped candidates excluding the "
        f"Answer, compared by LOCAL NODE INDEX) ...")
    walk = b2.walk_ranked_classes_for_local_mapping(
        answer_local_uri, ranked,
        retriever=context["retriever"], redirect_source=context["redirects"],
        local_lookup=context["local_lookup"], max_classes=args.max_classes,
        progress=say)
    result.class_attempts = walk.attempts
    if not walk.is_feasible:
        return finish(S.NO_LOCALLY_MAPPING_FEASIBLE_CLASS,
                      f"{sum(1 for a in walk.attempts if a.attempted)} class(es) "
                      f"were retrieved and none reached the local-mapping gate")
    result.selected_class_uri = walk.selected_class_uri
    result.selected_class_rank = walk.selected_ranking_position
    result.mapped_candidate_count = walk.selected_mapping.mapped_candidate_count
    say(f"    SELECTED: rank {walk.selected_ranking_position} of {len(ranked)} "
        f"feasible classes -> {walk.selected_class_uri}")
    say(f"    NOT a globally optimal class: it is the FIRST class of the "
        f"automatic ranking that passed the declared local-mapping gate; the "
        f"classes below it were never tested.")

    # --- E2. §7 / §8 of B2-E: the candidate-validity screen ----------------
    walk = v3cli.screen_walk_candidates(walk, context, result)
    if walk is None:
        return finish(S.NO_LOCALLY_MAPPING_FEASIBLE_CLASS,
                      "the candidate-validity screen left fewer than "
                      f"{b2.LOCAL_MAPPING_GATE} candidates, so the selected "
                      "class no longer reaches the local-mapping gate")

    # --- F. the M1 graph under the DECLARED budget, and frozen LRoleSim ----
    say(f"[F] building the M1 graph (max_nodes={config.graph_max_nodes}) and "
        f"running the frozen Journal-2 LRoleSim ...")
    (attempt, graph_result, scored, fingerprint, provenance,
     diagnostics) = v4.build_graph_and_rank_v4(
        walk, context["local_kg"], display_label=result.display_label,
        score_cache_path=args.score_cache,
        max_nodes=config.graph_max_nodes,
        max_candidates=config.graph_max_candidates,
        progress=say)
    result.graph_outcome = attempt.outcome
    # The frozen row writer stamps the MODULE CONSTANT into `max_nodes`; v4 may
    # have declared another budget, so the two budget columns are corrected in
    # the copy this run stores. No key is added or removed.
    result.graph_row = v4.graph_row_with_effective_budget(attempt, diagnostics)
    result.graph_budget_diagnostics = diagnostics
    if graph_result is None:
        return finish(S.GRAPH_INFEASIBLE,
                      f"the M1 graph stage returned {attempt.outcome}; "
                      f"{diagnostics['explanation']}")
    result.lrolesim_provenance = dict(provenance)
    result.run_fingerprint = fingerprint.run_fingerprint
    result.scored = tuple(scored)
    result.complete_pool_size = len(scored)

    candidates = tuple(Candidate(rank=c.rank, score=c.score, uri=c.canonical_uri)
                       for c in scored)

    # --- G. the semantic-index source set, then the rebuild ---------------
    say("[G] deriving the exact enlarged semantic-index source-object set ...")
    answer_facts = mcq_inputs.answer_facts_from_local_kg(
        answer_local_uri, local_kg=context["local_kg"],
        quality_policy=context["quality_policy"])
    observed_by_candidate = {
        candidate.uri: mcq_inputs.candidate_objects_from_local_kg(
            candidate.uri, local_kg=context["local_kg"])
        for candidate in candidates}
    # The alias policy MUST reach the source set too: the set is the cache key,
    # so an index built without the aliases would omit exactly the objects the
    # aliased lookup then asks about.
    sources = b2.enlarged_source_object_uris(
        answer_facts, observed_by_candidate,
        alias_policy=config.alias_policy)
    key_digest = source_object_list_sha256(sources)
    result.semantic_source_count = len(sources)
    result.semantic_source_digest = key_digest
    eligible = sum(1 for f in answer_facts if f.eligible)
    say(f"    {len(answer_facts)} Answer facts ({eligible} eligible), "
        f"{len(sources)} source objects, "
        f"source_object_list_sha256={key_digest}")
    say(f"    predicate alias policy: {config.alias_policy.version} "
        f"(enabled={config.alias_policy.enabled})")

    index_target = anyb2.semantic_index_path(
        args.semantic_index_root, answer_local_uri, key_digest)
    say(f"[G] rebuilding the semantic index OFFLINE from the pinned KG "
        f"(policy {context['semantic_policy'].version}) -> {index_target.name}")
    try:
        index_path = build_semantic_index_from_pinned_kg(
            policy_path=config.semantic_policy_path,
            cache_path=index_target,
            source_object_uris=sources, local_kg=context["local_kg"],
            verbose=False)
        expected_key = SemanticIndexCacheKey(
            pinned_kg_sha256=b2.PINNED_LOCAL_KG_SHA256,
            policy_sha256=context["semantic_policy"].policy_sha256,
            source_object_list_sha256=key_digest,
            max_depth=context["semantic_policy"].max_depth,
            creation_command=("python scripts/run_phase_b2_any_answer_v4.py "
                              "(build_semantic_index_from_pinned_kg)"))
        semantic_index = load_semantic_index_cache(
            index_path, policy=context["semantic_policy"],
            expected_key=expected_key)
    except Exception as exc:                                    # noqa: BLE001
        return finish(S.SEMANTIC_INDEX_UNAVAILABLE,
                      f"the semantic index could not be built or loaded: {exc!r}")
    result.semantic_index_path = str(index_path)
    result.semantic_index_available = semantic_index.available
    result.semantic_index_unavailable_reason = semantic_index.unavailable_reason
    say(f"    semantic index available={semantic_index.available} "
        f"reason={semantic_index.unavailable_reason!r}")

    # --- the rulebook: frozen base + the scoped-empirical derivation -------
    scope = walk.selected_class_uri
    observations: dict[str, dict] = {answer_local_uri: {}}
    for fact in answer_facts:
        observations[answer_local_uri].setdefault(
            fact.predicate_direction_key, set()).add(fact.counterpart_uri)
    for uri, observed in observed_by_candidate.items():
        observations[uri] = {key: set(objects) for key, objects in observed.items()}
    rows = observe_scope_cardinalities(
        scope=scope,
        observations={entity: {key: sorted(values) for key, values in keys.items()}
                      for entity, keys in observations.items()},
        semantic_index=semantic_index)
    derived = derive_empirical_single_valued_rules(
        rows, config=context["base_rules"].derivation,
        rejected_predicates=context["quality_policy"].hard_reject_predicates)
    rulebook = context["base_rules"].with_rules(derived)

    # --- H. the frozen Phase-B selection kernel ----------------------------
    say(f"[H] calling mcq_inputs.build_and_select() "
        f"(rationale objective = {config.rationale_objective}) ...")
    roster_path = (str(out_dir / "complete_lrolesim_ranking.csv") if out_dir
                   else f"in-memory:complete_lrolesim_ranking:"
                        f"{anyb2.answer_slug(answer_local_uri)}")
    run_provenance = {
        "candidate_roster_source": str(roster_path),
        "candidate_roster_sha256": b2.candidate_roster_digest(scored),
        "candidate_roster_is_complete_admitted_pool": True,
        "selected_class_uri": scope,
        "class_approval_status": anyb2.class_approval_status(args.alpha),
        **mcq_inputs.PINNED_LROLESIM_EXECUTION,
    }
    case, selection, record = mcq_inputs.build_and_select(
        answer_local_uri, result.display_label, candidates,
        local_kg=context["local_kg"], quality_policy=context["quality_policy"],
        semantic_index=semantic_index, rulebook=rulebook, scope=scope,
        provenance=run_provenance,
        objective=config.rationale_objective,
        alias_policy=config.alias_policy)
    result.case = case
    result.selection = selection
    result.record = record
    result.evidence_profiles = anyb2.summarise_candidate_evidence(case)

    v2cli.print_lrolesim_ranking(result)
    if selection is None:
        return finish(S.NO_VALID_FINAL_COMBINATION,
                      "no combination of the roster reached full coverage under "
                      "any policy; a feasibility measurement, not an error")

    # --- H2. §6 the versioned granularity-risk policy ----------------------
    outcome = apply_granularity_policy(
        case, selection, policy=config.granularity_policy,
        objective=config.rationale_objective)
    result.granularity_outcome = outcome
    if outcome.selection is not None and outcome.selection is not selection:
        say(f"[H2] granularity policy {config.granularity_policy.mode}: "
            f"{outcome.status} — {outcome.detail}")
        result.selection = outcome.selection
        selection = outcome.selection
    else:
        say(f"[H2] granularity policy {config.granularity_policy.mode}: "
            f"{outcome.status}")

    v2cli.print_final_selection(result)
    v3cli.print_v3_additions(result)
    print_v4_additions(result)

    if not result.has_main_l1_selection:
        return finish(S.NO_MAIN_L1_SELECTION,
                      f"a selection exists only under the "
                      f"{selection.evidence_policy} policy; L0 is snapshot "
                      f"absence and is never student-showable")
    if not outcome.learner_facing:
        return finish(STATUS_NO_GRANULARITY_CLEAN, outcome.detail)
    return finish(S.SUCCESS_FULL_EXACT if selection.search_scope == "FULL_EXACT"
                  else S.SUCCESS_POOL_EXACT)


def _reject_code_counts(records) -> dict:
    counts: dict = {}
    for record in records:
        code = record["primary_rejected_code"] or "unrecorded"
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def print_v4_additions(result) -> None:
    """The report fields v4 adds after the v3 [L2] block."""
    say("[L3] PROMPT 8H-B2-G ADDITIONS")
    diagnostics = getattr(result, "graph_budget_diagnostics", None)
    if diagnostics is not None:
        say(f"    M1 budget                  : max_nodes="
            f"{diagnostics['effective_max_nodes']}, nodes="
            f"{diagnostics['m1_node_count']}, edges="
            f"{diagnostics['m1_edge_count']}, offered="
            f"{diagnostics['candidates_offered_to_m1']}, retained="
            f"{diagnostics['candidates_retained']}")
        say(f"    candidates lost to budget  : "
            f"{diagnostics['lost_total']} {diagnostics['lost_by_reason']}")
        say(f"      > {diagnostics['explanation']}")
    outcome = getattr(result, "granularity_outcome", None)
    if outcome is not None:
        say(f"    granularity policy         : {outcome.policy.mode} -> "
            f"{outcome.status}")
        say(f"      learner-facing under policy: {outcome.learner_facing}; "
            f"distractors changed: {outcome.distractors_changed}; "
            f"rationale changed: {outcome.rationale_changed}")
    rejections = getattr(result, "class_ranking_rejections", ())
    say(f"    class rejections recorded  : {len(rejections)} "
        f"{_reject_code_counts(rejections)}")
    say("")


def write_answer_artifacts_v4(out_dir: Path, result) -> None:
    """The v3 artifact tree plus the three v4 records."""
    v3cli.write_answer_artifacts_v3(out_dir, result)
    rejections = getattr(result, "class_ranking_rejections", ())
    if rejections:
        b2.write_csv(out_dir / "class_ranking_rejections.csv",
                     list(rejections[0].keys()),
                     [{k: (json.dumps(v, ensure_ascii=False)
                           if isinstance(v, list) else v)
                       for k, v in row.items()} for row in rejections])
    diagnostics = getattr(result, "graph_budget_diagnostics", None)
    if diagnostics is not None:
        b2.write_json(out_dir / "graph_budget_diagnostics.json", diagnostics)
    outcome = getattr(result, "granularity_outcome", None)
    if outcome is not None:
        b2.write_json(out_dir / "granularity_policy_outcome.json",
                      outcome.as_record())


# ==========================================================================
# 2) Command line
# ==========================================================================


def build_parser() -> argparse.ArgumentParser:
    """The v3 parser, with the v4 switches replacing or adding to it.

    Built by MUTATING a fresh v3 parser rather than by copying 120 lines of
    argument definitions, so the two runners cannot drift on the arguments they
    share — the cache paths, the network gate, the line range, the facts-only
    mode and the class-selection knobs are one definition, not two.
    """
    parser = v3cli.build_parser()
    parser.prog = "run_phase_b2_any_answer_v4.py"
    parser.description = (
        "Prompt 8H-B2-G FINAL-BENCHMARK CANDIDATE runner. Identity bridge -> "
        "automatic v6 class ranking -> local mapping -> candidate-validity "
        "screen -> M1 graph under a DECLARED node budget -> frozen LRoleSim -> "
        "semantic-index rebuild -> frozen Phase-B selection -> versioned "
        "granularity-risk policy. Every policy choice is a recorded value.")
    parser.epilog = (
        "Exactly one of --allow-network / --offline-replay is required. The "
        "selected class is the FIRST locally mapping-feasible class of an "
        "automatic ranking, never a globally optimal class. No configuration "
        "offered here is a publication default.")

    # --- §7: objective v3 becomes the v4 CANDIDATE default ---------------
    _set_default(parser, "rationale_objective", "v3")
    # --- §2: a third candidate-type arm ----------------------------------
    _replace_choices(parser, "candidate_type_policy",
                     ("observe-only", "person-guarded", "person-strict"))

    group = parser.add_argument_group("Prompt 8H-B2-G (v4) switches")
    group.add_argument(
        "--max-nodes", type=int, default=v4.V4_GRAPH_MAX_NODES,
        help=("§8. The M1 graph node budget this run declares. The frozen "
              "v1/v2/v3 value is 1200 and is still selectable; 5000 is the v4 "
              "CANDIDATE value and is recorded in the manifest, never compiled "
              "in"))
    group.add_argument(
        "--max-graph-candidates", type=int, default=None,
        help=("§8. The M1 candidate cap. Defaults to the frozen 50. A larger "
              "NODE budget does not raise this cap, and the budget diagnostics "
              "report the two refusals separately"))
    group.add_argument(
        "--predicate-alias-policy", choices=("none", "v1"), default="v1",
        help=("§5. `v1` applies the AUDITED dbp:field / dbp:fields slot family "
              "to the CANDIDATE's observed objects for evidence lookup only. "
              "`none` is exact-key lookup, the pre-B2-G behaviour. No "
              "unaudited family is ever applied and no predicate is "
              "singularised by rule"))
    group.add_argument(
        "--granularity-risk-policy",
        choices=(GRANULARITY_POLICY_REPORT_ONLY,
                 GRANULARITY_POLICY_REQUIRE_CLEAN),
        default=GRANULARITY_POLICY_REPORT_ONLY,
        help=("§6. `report-only` is the historical behaviour: a risky apparent "
              "contrast may remain selected and is flagged. `require-clean` "
              "refuses a risky rationale as the learner-facing main reason, "
              "prefers a clean alternative at the same admissible search level, "
              "and reports an explicit diagnostic when none exists. It never "
              "converts a risky L1 into L0 and never invents NOT_COVERED"))
    group.add_argument(
        "--v3-compatible", action="store_true",
        help=("reproduce a Prompt 8H-B2-E/F v3 run exactly through the v4 code "
              "path: objective v2, max_nodes 1200, no predicate aliases, "
              "granularity report-only"))
    return parser


def _set_default(parser: argparse.ArgumentParser, dest: str, value) -> None:
    """Change one argument's DEFAULT without redefining the argument.

    Raises when the argument is missing, so a rename upstream is a loud error
    rather than a v4 run silently keeping the v3 default.
    """
    for action in parser._actions:                              # noqa: SLF001
        if action.dest == dest:
            action.default = value
            return
    raise KeyError(f"v3 parser has no argument with dest {dest!r}")


def _replace_choices(parser: argparse.ArgumentParser, dest: str,
                     choices: tuple) -> None:
    for action in parser._actions:                              # noqa: SLF001
        if action.dest == dest:
            action.choices = choices
            return
    raise KeyError(f"v3 parser has no argument with dest {dest!r}")


def runner_config_from_args(args) -> v4.RunnerConfigV4:
    """Turn the v4 switches into ONE recorded configuration object."""
    if getattr(args, "v3_compatible", False):
        return v4.V3_COMPATIBLE_RUNNER_CONFIG
    if getattr(args, "v2_compatible", False):
        return v4.RunnerConfigV4(
            base=v3.V2_COMPATIBLE_RUNNER_CONFIG,
            graph_max_nodes=v4.GRAPH_MAX_NODES,
            alias_policy=NO_ALIAS_POLICY,
            granularity_policy=REPORT_ONLY_POLICY)

    validity = v4.CANDIDATE_VALIDITY_POLICIES[args.candidate_type_policy]
    if (args.reject_answer_name_containment
            and not validity.reject_answer_name_containment):
        import dataclasses
        validity = dataclasses.replace(validity,
                                       reject_answer_name_containment=True)
    base = v3.RunnerConfigV3(
        predicate_policy_path=v3.POLICY_PATHS[
            f"predicate_policy_{args.predicate_policy}"],
        semantic_policy_path=v3.POLICY_PATHS[
            f"semantic_relation_policy_{args.semantic_policy}"],
        derivational_policy=(DERIVATIONAL_POLICY_V2
                             if args.class_leakage_policy == "v2"
                             else DEFAULT_DERIVATIONAL_POLICY),
        candidate_validity_policy=validity,
        rationale_objective={
            "v1": mcq_core.RATIONALE_OBJECTIVE_V1,
            "v2": mcq_core.RATIONALE_OBJECTIVE_V2,
            "v3": mcq_core.RATIONALE_OBJECTIVE_V3,
        }[args.rationale_objective],
    )
    return v4.RunnerConfigV4(
        base=base,
        graph_max_nodes=int(args.max_nodes),
        graph_max_candidates=(v4.GRAPH_MAX_CANDIDATES
                              if args.max_graph_candidates is None
                              else int(args.max_graph_candidates)),
        alias_policy=(DEFAULT_ALIAS_POLICY
                      if args.predicate_alias_policy == "v1"
                      else NO_ALIAS_POLICY),
        granularity_policy=(
            REQUIRE_CLEAN_POLICY
            if args.granularity_risk_policy == GRANULARITY_POLICY_REQUIRE_CLEAN
            else REPORT_ONLY_POLICY),
    )


def build_context(args, local_kg, config: v4.RunnerConfigV4):
    """Every client and policy one run needs, constructed AFTER the network gate.

    The v3 builder is reused verbatim for the shared half and is handed the v4
    configuration's INNER v3 record, so the two runners construct identical
    clients from identical policy files.
    """
    context = v3cli.build_context(args, local_kg, config.base)
    context["config"] = config
    return context


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.allow_network and args.offline_replay:
        say("ERROR: --allow-network and --offline-replay are mutually exclusive.")
        return EXIT_USAGE
    if not args.allow_network and not args.offline_replay:
        say("ERROR: choose exactly one of --allow-network / --offline-replay; "
            "network access is denied by default and no run proceeds without a "
            "declared mode.")
        return EXIT_USAGE
    if args.max_nodes < 1:
        say(f"ERROR: --max-nodes must be at least 1, got {args.max_nodes}.")
        return EXIT_USAGE
    if args.alpha is None:
        args.alpha = v6.DEFAULT_ALPHA
    try:
        args.alpha = v6.validate_alpha(args.alpha)
    except ValueError as exc:
        say(f"ERROR: {exc}")
        return EXIT_USAGE

    line_range = None
    if args.lines_for_input_file is not None:
        if args.input is None:
            say("ERROR: --lines-for-input-file is valid only with --input; a "
                "single --answer-uri has no source line to select.")
            return EXIT_USAGE
        try:
            line_range = v3.parse_line_range(args.lines_for_input_file)
        except v3.LineRangeError as exc:
            say(f"ERROR: {exc}")
            return EXIT_USAGE

    config = runner_config_from_args(args)

    parsed = None
    selected: list[tuple[Optional[int], str, Optional[str]]] = []
    if args.input is not None:
        if not Path(args.input).is_file():
            say(f"ERROR: input file not found: {args.input}")
            return EXIT_USAGE
        parsed = selector_cli.parse_answers_file(args.input)
        say(f"Parsed {args.input}: {parsed.answer_row_count} Answer rows, "
            f"{len({r.answer_uri for r in parsed.rows})} unique URIs, "
            f"{parsed.duplicate_row_count} duplicate rows, "
            f"{len(parsed.cohort_order)} cohorts.")
        for number, text in parsed.malformed_rows:
            say(f"  INPUT PROBLEM line {number}: malformed row {text!r}")
        for number, text in parsed.invalid_uri_rows:
            say(f"  INPUT PROBLEM line {number}: not a valid IRI {text!r} "
                f"(EXCLUDED from the run)")
        selected = v3.rows_in_line_range(parsed, line_range)
        if line_range is not None:
            say(f"  --lines-for-input-file {line_range[0]}-{line_range[1]}: "
                f"{len(selected)} Answer row(s) selected out of "
                f"{len(v3.rows_in_line_range(parsed, None))} runnable unique "
                f"rows.")
        if args.limit is not None:
            selected = selected[: max(0, args.limit)]
        if not selected:
            say("ERROR: no runnable Answer row was selected.")
            return EXIT_USAGE
    else:
        selected = [(None, str(args.answer_uri).strip(), None)]

    say("Cohort labels are EVALUATION METADATA ONLY. They are carried into the "
        "output rows and are never passed to the class ranker, the graph, the "
        "LRoleSim ranker or the selection kernel.")

    started = time.time()
    say("")
    say("[0] loading the pinned local KG (SHA-256 verified before use) ...")
    local_kg = load_local_kg(b2.PINNED_LOCAL_KG,
                             verify_sha256=b2.PINNED_LOCAL_KG_SHA256)
    say(f"    pinned KG sha256 = {local_kg.source_sha256}")

    context = build_context(args, local_kg, config)
    say("")
    say("RUN CONFIGURATION (every scientific choice is a recorded value):")
    for line in json.dumps(config.as_record(), indent=2,
                           sort_keys=True).splitlines():
        say("    " + line)
    say("")

    if args.print_facts_only:
        return v3cli.run_facts_only(selected, local_kg=local_kg,
                                    context=context, args=args)

    say(f"    IDF universe N   = {context['universe'].total_entities} "
        f"[{context['universe'].definition}]")
    if not context["universe"].available:
        say("ERROR: no IDF universe N could be measured and none was supplied. "
            "No value was invented. Re-run with --total-entities N.")
        return EXIT_BLOCKED

    artifacts_root = (Path(args.artifacts_dir).resolve()
                      if args.artifacts_dir else None)
    results = []
    screens = []

    for number, (line_number, uri, cohort) in enumerate(selected, start=1):
        say("")
        say("=" * 100)
        say(f"ANSWER {number}/{len(selected)}: {uri}"
            + (f"   [input line {line_number}]" if line_number else "")
            + (f"   [cohort: {cohort}]" if cohort else ""))
        say("=" * 100)
        out_dir = (artifacts_root / f"{number:04d}_{anyb2.answer_slug(uri)}"
                   if artifacts_root else None)
        try:
            result = run_one_answer(uri, cohort=cohort, source_line=line_number,
                                    context=context, args=args, out_dir=out_dir)
        except Exception as exc:                                # noqa: BLE001
            result = anyb2.AnswerRunResult(
                original_uri=uri, cohort=cohort, alpha=args.alpha,
                status=S.QUERY_FAILED, detail=f"{type(exc).__name__}: {exc}")
            result.source_line_number = line_number
            result.candidate_screen = None
            result.class_ranking_rejections = ()
            result.graph_budget_diagnostics = None
            result.granularity_outcome = None
            say(f"    FAILED: {type(exc).__name__}: {exc}")
            say(traceback.format_exc())
        say(f"    STATUS: {result.status}"
            + (f" — {result.detail}" if result.detail else ""))
        results.append(result)
        if getattr(result, "candidate_screen", None) is not None:
            screens.append(result.candidate_screen)
        if out_dir is not None:
            write_answer_artifacts_v4(out_dir, result)
            say(f"    artifacts -> {out_dir}")

    # Prompt 8H-B2-G §16: a live retrieval must be RECORDED AND CACHED. The
    # Wikipedia lead cache is written only when `save()` is called, and no
    # earlier runner called it — so a lead fetched live was replayed from
    # nothing and the next offline run silently fell back to
    # `idf_only_semantic_unavailable`, which is a DIFFERENT class ranking. Saving
    # it here is what makes a live regression replayable offline afterwards.
    # Under --offline-replay nothing was fetched, so nothing is written.
    if args.allow_network and context["leads"] is not None:
        try:
            saved = context["leads"].cache.save()
            say(f"Wikipedia lead cache saved -> {saved} "
                f"({len(context['leads'].cache)} leads); a live retrieval is "
                f"only reproducible once it is cached")
        except Exception as exc:                                # noqa: BLE001
            say(f"WARNING: the Wikipedia lead cache could not be saved: {exc!r}")

    metrics = v4.batch_metrics_v4(results, config=config, screens=screens)
    say("")
    say("=" * 100)
    say("BATCH SUMMARY")
    say("=" * 100)
    say("")
    say(v4.summary_table_v4(results))
    say("")
    say(v3.prose_summary_v3(results, metrics))
    say("")
    say("=" * 100)
    say("BATCH METRICS")
    say("=" * 100)
    say("")
    say(v4.metrics_markdown_v4(metrics))

    if args.output_report is not None:
        target = Path(args.output_report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(TRANSCRIPT) + "\n", encoding="utf-8")
        print(f"Full human-readable report written to {target}", flush=True)
    else:
        print("No output report file was created because --output-report was "
              "not specified.", flush=True)

    metrics["run_manifest"] = {
        "runner": "scripts/run_phase_b2_any_answer_v4.py",
        "schema_version": v4.ANY_ANSWER_V4_SCHEMA_VERSION,
        "command_arguments": sys.argv[1:],
        "mode": "live" if args.allow_network else "offline-replay",
        "alpha": args.alpha,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "pinned_kg_sha256": local_kg.source_sha256,
        "predicate_policy_sha256": context["quality_policy"].policy_sha256,
        "predicate_policy_version": context["quality_policy"].version,
        "semantic_policy_sha256": context["semantic_policy"].policy_sha256,
        "semantic_policy_version": context["semantic_policy"].version,
        "idf_universe": context["universe"].to_dict(),
        "lrolesim_execution": dict(mcq_inputs.PINNED_LROLESIM_EXECUTION),
        "runner_config": config.as_record(),
        "input_audit": parsed.audit() if parsed is not None else None,
        "line_range": list(line_range) if line_range else None,
        "duration_seconds": round(time.time() - started, 3),
        "publication_status": (
            "EVIDENCE RUN. Prompt 8H-B2-G is not the final publication "
            "benchmark and declares no publication-final policy."),
    }
    if args.metrics_json is not None:
        Path(args.metrics_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.metrics_json).write_text(
            json.dumps(metrics, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8")
        print(f"Batch metrics -> {args.metrics_json}", flush=True)
    if args.metrics_csv is not None:
        rows = v4.metrics_csv_rows_v4(metrics)
        Path(args.metrics_csv).parent.mkdir(parents=True, exist_ok=True)
        with open(args.metrics_csv, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["metric", "value", "denominator", "note"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"Batch metrics CSV -> {args.metrics_csv}", flush=True)

    if artifacts_root is not None:
        rows = [r.summary_record() for r in results]
        for row, result in zip(rows, results):
            row["source_line_number"] = getattr(result, "source_line_number", None)
            selection = result.selection
            row["minimum_rationale_size"] = (
                None if selection is None else selection.minimum_rationale_size)
            row["option_reference_conflict_count"] = (
                None if selection is None
                else selection.rationale.option_reference_conflict_count)
            row["granularity_risk_incidences"] = (
                None if selection is None
                else selection.rationale.granularity_risk_incidences)
            row["rationale_objective"] = (
                None if selection is None else selection.rationale_objective)
            outcome = getattr(result, "granularity_outcome", None)
            row["granularity_policy_status"] = (
                None if outcome is None else outcome.status)
            diagnostics = getattr(result, "graph_budget_diagnostics", None)
            row["m1_max_nodes"] = (
                None if diagnostics is None
                else diagnostics["effective_max_nodes"])
            row["m1_node_count"] = (
                None if diagnostics is None else diagnostics["m1_node_count"])
            row["m1_edge_count"] = (
                None if diagnostics is None else diagnostics["m1_edge_count"])
            row["candidates_lost_to_graph_budget"] = (
                None if diagnostics is None else diagnostics["lost_total"])
        b2.write_csv(artifacts_root / "batch_summary.csv",
                     list(rows[0].keys()), rows)
        b2.write_csv(
            artifacts_root / "failure_summary.csv",
            ["original_uri", "cohort", "status", "detail"],
            [{"original_uri": r.original_uri, "cohort": r.cohort,
              "status": r.status, "detail": r.detail}
             for r in results if not r.succeeded])
        if screens:
            b2.write_csv(
                artifacts_root / "candidate_validity_screen.csv",
                list(screens[0].verdicts[0].as_record().keys()),
                [v.as_record() for s in screens for v in s.verdicts])
        b2.write_json(artifacts_root / "batch_metrics.json", metrics)
        print(f"Batch artifacts -> {artifacts_root}", flush=True)

    return EXIT_OK if any(r.succeeded for r in results) else EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
