#!/usr/bin/env python
############################################################################
# scripts/run_phase_b2_any_answer_v3.py
#
# Prompt 8H-B2-E / B2-F driver: run ANY Answer — or a whole Answers.txt batch,
# or a LINE RANGE of one — end to end, from the AUTOMATIC v6 class ranking
# through the frozen Phase-B selection kernel.
#
# WHAT IS NEW IN v3, AND WHY EACH THING EXISTS
# ---------------------------------------------
#   --print-facts-only          §15. Print the COMPLETE raw pinned-KG fact
#                               inventory of an Answer and stop. No class
#                               ranking, no DBpedia class retrieval, no
#                               LRoleSim, no evidence, no selection.
#   --lines-for-input-file A-B  §16. Execute only the Answer rows whose SOURCE
#                               LINE lies in a 1-based inclusive range. The
#                               whole file is still parsed, so the cohort a
#                               selected line was written under is known.
#   versioned policy switches   §5, §7, §9, §10, §12. Which semantic policy,
#                               which predicate policy, which class-leakage
#                               policy, which candidate-validity policy and
#                               which rationale objective a run uses are
#                               ARGUMENTS, recorded in the manifest, not
#                               facts about which commit is checked out.
#   --v2-compatible             Name the v1 generation of all five at once, so
#                               a delta audit can run both arms from one script.
#   a fixed batch table         §17. |R*| lives in its own column and is never
#                               truncated.
#   rich batch metrics          §18/§19. Four distinct coverage concepts, every
#                               denominator explicit, N/A instead of a division
#                               by zero, and a machine-readable JSON + CSV.
#
# WHAT IT DELIBERATELY DOES NOT DO
#   `scripts/run_phase_b2_any_answer_v2.py` and
#   `src/pipeline/phase_b2_any_answer_run.py` are NOT modified and NOT removed.
#   They produced the published 329-Answer development report and remain the
#   historical evidence of it. This script IMPORTS the v2 driver's presentation
#   helpers rather than copying them, so the per-Answer report sections [A]-[L]
#   cannot drift between the two runners.
#
# WHAT IT STOPS BEFORE
#   Natural-language verbalization, final MCQ prose, choice-evidence bipartite
#   graph construction, the ~100-PERSON publication benchmark and human
#   evaluation. The run ends at the frozen Phase-B selection result.
#
# NETWORK
#   Exactly one of --allow-network / --offline-replay is required; neither is
#   the default. Under --offline-replay every client is constructed so that a
#   cache miss RAISES. `--print-facts-only` reads the pinned local KG only and
#   needs no network at all when the supplied URI resolves directly.
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
# The v2 driver is imported READ-ONLY, for its presentation helpers and its
# strict-offline SPARQL client. Nothing here writes to it, and `say()` shares
# its TRANSCRIPT so one report file is still literally the terminal session.
import run_phase_b2_any_answer_v2 as v2cli                      # noqa: E402
from classes.answer_identity import (                           # noqa: E402
    IdentityStatus,
    LocalResolutionMethod,
    SparqlIdentitySource,
    resolve_answer_identity,
)
from classes.candidate_validity import (                        # noqa: E402
    DEFAULT_CANDIDATE_VALIDITY_POLICY,
    TYPE_POLICY_OBSERVE_ONLY,
    TYPE_POLICY_PERSON_STRICT,
    CandidateValidityPolicy,
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
from pipeline.rationale_v3_run import (                         # noqa: E402
    EVIDENCE_RULES_PATH,
    build_semantic_index_from_pinned_kg,
)
from rationale_v3.evidence import (                             # noqa: E402
    derive_empirical_single_valued_rules,
    load_evidence_rules,
    observe_scope_cardinalities,
)
from rationale_v3.quality import load_quality_policy            # noqa: E402
from rationale_v3.semantic_relations import (                   # noqa: E402
    SemanticIndexCacheKey,
    load_semantic_index_cache,
    load_semantic_relation_policy,
    source_object_list_sha256,
)

S = anyb2.AnswerStatus

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_BLOCKED = 1

#: One shared transcript with the v2 presentation helpers, so a report file
#: written here contains every line those helpers printed.
TRANSCRIPT = v2cli.TRANSCRIPT
say = v2cli.say


# ==========================================================================
# 1) Per-Answer pipeline, v3
# ==========================================================================


def run_one_answer(original_uri, *, cohort, source_line, context, args, out_dir):
    """The complete per-Answer pipeline. Never raises for a scientific failure.

    Identical to the v2 pipeline stage for stage, with ONE stage inserted and
    three arguments made versioned:

      * inserted between §E (local mapping) and §F (the M1 graph): the
        candidate-validity screen of §7/§8, so a candidate that is the wrong
        KIND of thing, or whose name contains the complete Answer name, never
        reaches the graph and therefore never consumes a LRoleSim rank or an
        evidence classification;
      * the class-leakage policy, the predicate policy, the semantic policy, the
        candidate-validity policy and the rationale objective all come from the
        run configuration rather than from module defaults.
    """
    started = time.time()
    result = anyb2.AnswerRunResult(original_uri=original_uri, cohort=cohort,
                                   alpha=args.alpha)
    # Carried for the batch table's Line column; the base dataclass has no such
    # field, and attaching it here keeps the frozen v2 record shape untouched.
    result.source_line_number = source_line
    result.candidate_screen = None

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
        f"class-leakage policy = "
        f"{context['config'].derivational_policy.version}) ...")
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
        derivational=context["config"].derivational_policy)
    result.display_label = features.answer_label
    result.categories_discovered = features.categories_discovered
    result.feasible_class_count = len(features.feasible_classes)
    result.rejected_class_count = len(features.rejected_classes)

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

    # --- E2. §7 / §8 candidate-validity screen, BEFORE the M1 graph --------
    walk = screen_walk_candidates(walk, context, result)
    if walk is None:
        return finish(S.NO_LOCALLY_MAPPING_FEASIBLE_CLASS,
                      "the candidate-validity screen left fewer than "
                      f"{b2.LOCAL_MAPPING_GATE} candidates, so the selected "
                      "class no longer reaches the local-mapping gate")

    # --- F. the frozen M1 graph and the frozen LRoleSim --------------------
    say("[F] building the M1 graph and running the frozen Journal-2 LRoleSim ...")
    attempt, graph_result, scored, fingerprint, provenance = b2.build_graph_and_rank(
        walk, context["local_kg"], display_label=result.display_label,
        score_cache_path=args.score_cache, progress=say)
    result.graph_outcome = attempt.outcome
    result.graph_row = attempt.as_row()
    if graph_result is None:
        return finish(S.GRAPH_INFEASIBLE,
                      f"the M1 graph stage returned {attempt.outcome}")
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
    sources = b2.enlarged_source_object_uris(answer_facts, observed_by_candidate)
    key_digest = source_object_list_sha256(sources)
    result.semantic_source_count = len(sources)
    result.semantic_source_digest = key_digest
    eligible = sum(1 for f in answer_facts if f.eligible)
    say(f"    {len(answer_facts)} Answer facts ({eligible} eligible), "
        f"{len(sources)} source objects, "
        f"source_object_list_sha256={key_digest}")

    index_target = anyb2.semantic_index_path(
        args.semantic_index_root, answer_local_uri, key_digest)
    say(f"[G] rebuilding the semantic index OFFLINE from the pinned KG "
        f"(policy {context['semantic_policy'].version}) -> {index_target.name}")
    try:
        index_path = build_semantic_index_from_pinned_kg(
            policy_path=context["config"].semantic_policy_path,
            cache_path=index_target,
            source_object_uris=sources, local_kg=context["local_kg"],
            verbose=False)
        expected_key = SemanticIndexCacheKey(
            pinned_kg_sha256=b2.PINNED_LOCAL_KG_SHA256,
            policy_sha256=context["semantic_policy"].policy_sha256,
            source_object_list_sha256=key_digest,
            max_depth=context["semantic_policy"].max_depth,
            creation_command=("python scripts/run_phase_b2_any_answer_v3.py "
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
    say(f"    relation domains: "
        f"{[d.domain_id for d in context['semantic_policy'].effective_domains]}")

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
        f"(rationale objective = {context['config'].rationale_objective}) ...")
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
        objective=context["config"].rationale_objective)
    result.case = case
    result.selection = selection
    result.record = record
    result.evidence_profiles = anyb2.summarise_candidate_evidence(case)

    v2cli.print_lrolesim_ranking(result)
    if selection is None:
        return finish(S.NO_VALID_FINAL_COMBINATION,
                      "no combination of the roster reached full coverage under "
                      "any policy; a feasibility measurement, not an error")
    v2cli.print_final_selection(result)
    print_v3_additions(result)
    if not result.has_main_l1_selection:
        return finish(S.NO_MAIN_L1_SELECTION,
                      f"a selection exists only under the "
                      f"{selection.evidence_policy} policy; L0 is snapshot "
                      f"absence and is never student-showable")
    return finish(S.SUCCESS_FULL_EXACT if selection.search_scope == "FULL_EXACT"
                  else S.SUCCESS_POOL_EXACT)


def screen_walk_candidates(walk, context, result):
    """Apply the §7/§8 screen to the walk's accepted candidates.

    Returns a walk whose selected mapping carries only the accepted candidates,
    or ``None`` when the screen drops the pool below the local-mapping gate —
    which is a scientific outcome (this class is no longer usable for this
    Answer), not an error.

    Under the default OBSERVE_ONLY policy nothing is removed and the walk is
    returned unchanged, so the pool handed to the graph is byte-identical to the
    v2 pool.
    """
    import dataclasses

    from classes.member_mapper import MappedMember

    mapping = walk.selected_mapping
    accepted_indices = list(mapping.local_candidate_indices)
    uris = [context["local_kg"].index_url[index] for index in accepted_indices]
    plain = [u[1:-1] if u.startswith("<") and u.endswith(">") else u for u in uris]

    screen = v3.screen_candidate_pool(
        answer_local_uri=walk.answer_uri, candidate_uris=plain,
        local_kg=context["local_kg"],
        quality_policy=context["quality_policy"],
        policy=context["config"].candidate_validity_policy)
    result.candidate_screen = screen

    policy = context["config"].candidate_validity_policy
    say(f"[E2] candidate-validity screen "
        f"({policy.version}, type policy = {policy.type_policy}, "
        f"answer type = {screen.answer_type}) ...")
    say(f"     offered {screen.offered}, accepted {len(screen.accepted_uris)}, "
        f"rejected {len(screen.rejected)}  {screen.reject_counts() or '{}'}")
    for verdict in screen.rejected:
        say(f"       REJECT {verdict.candidate_uri}  "
            f"[{verdict.reject_reason}] type={verdict.type_verdict.entity_type}"
            + (f"  {verdict.name_containment_evidence}"
               if verdict.name_containment_evidence else ""))
    if not policy.rejects_on_type and not policy.reject_answer_name_containment:
        say("     policy is OBSERVE_ONLY on both axes: every verdict above is "
            "published and NOTHING was removed from the pool.")
        return walk

    keep = set(screen.accepted_uris)
    kept_indices = [index for index, uri in zip(accepted_indices, plain)
                    if uri in keep]
    if len(kept_indices) < b2.LOCAL_MAPPING_GATE:
        say(f"     the screened pool holds {len(kept_indices)} candidates, "
            f"below the local-mapping gate of {b2.LOCAL_MAPPING_GATE}")
        return None

    dropped = set(accepted_indices) - set(kept_indices)
    members = tuple(
        dataclasses.replace(
            member,
            dropped_reason=(member.dropped_reason
                            or "DROPPED_CANDIDATE_VALIDITY_SCREEN"))
        if member.local_index in dropped else member
        for member in mapping.members)
    new_mapping = dataclasses.replace(
        mapping, members=members,
        local_candidate_indices=tuple(sorted(kept_indices)))
    say(f"     pool after screening: {len(kept_indices)} candidates "
        f"(ranks are assigned over the SCREENED pool, so a rejected candidate "
        f"consumes neither a rank nor any evidence work)")
    return dataclasses.replace(walk, selected_mapping=new_mapping)


def write_answer_artifacts_v3(out_dir: Path, result) -> None:
    """The v2 artifact tree, plus the v3 records, and safe for a crashed Answer.

    The v2 writer assumes `result.identity` exists, which is true for every
    Answer that reached stage A. It is NOT true for an Answer whose stage raised
    — the batch loop then builds a bare result with `identity=None` — and the
    v2 writer would raise while REPORTING a failure, aborting a batch that had
    already completed other Answers. v3 writes what exists and records what does
    not, because a failure is data.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if result.identity is not None:
        v2cli.write_answer_artifacts(out_dir, result)
    else:
        b2.write_json(out_dir / "run_manifest.json", {
            "schema_version": v3.ANY_ANSWER_V3_SCHEMA_VERSION,
            "status": result.status,
            "detail": result.detail,
            "identity": None,
            "note": ("this Answer raised before its identity was resolved, so "
                     "no per-stage artifact exists; the failure is recorded "
                     "here and the Answer stays in the batch denominator"),
        })
    screen = getattr(result, "candidate_screen", None)
    if screen is not None and screen.verdicts:
        b2.write_csv(out_dir / "candidate_validity_screen.csv",
                     list(screen.verdicts[0].as_record().keys()),
                     [v.as_record() for v in screen.verdicts])
        b2.write_json(out_dir / "candidate_validity_summary.json",
                      screen.as_record())


def print_v3_additions(result) -> None:
    """The report fields v3 adds after the frozen [L] block."""
    selection = result.selection
    rationale = selection.rationale
    say("[L2] PROMPT 8H-B2-E ADDITIONS")
    say(f"    rationale objective        : {selection.rationale_objective}")
    say(f"    option_reference_conflict  : "
        f"{rationale.option_reference_conflict_count}"
        + (f"  {list(rationale.option_reference_conflict_evidence)}"
           if rationale.option_reference_conflict_evidence else ""))
    if rationale.option_reference_conflict:
        say("      > a selected rationale fact names one of the selected "
            "options. Logically sound, pedagogically awkward; reported, never "
            "repaired by growing |R*|.")
    states = set()
    for index in rationale.fact_indices:
        for position in selection.positions:
            state = result.case.facts[index].granularity_risks[position]
            if state != "NONE":
                states.add(state)
    say(f"    granularity risk states    : {sorted(states) or ['NONE']}")
    screen = getattr(result, "candidate_screen", None)
    if screen is not None:
        say(f"    candidate screen           : answer type "
            f"{screen.answer_type}, {len(screen.accepted_uris)} of "
            f"{screen.offered} candidates accepted {screen.reject_counts()}")
    say("")


# ==========================================================================
# 2) §15 — --print-facts-only
# ==========================================================================


def run_facts_only(uris_with_lines, *, local_kg, context, args) -> int:
    """Print the COMPLETE raw pinned-KG fact inventory of each Answer, and stop.

    The mode's whole contract is what it does NOT do: no class ranking, no
    DBpedia class retrieval, no LRoleSim, no candidate evidence, no rationale
    and no MCQ selection. It answers exactly one question — "what does the
    pinned March-2023 snapshot record about this entity?" — and it answers it
    with EVERY fact, not only the rationale-eligible ones.

    RESOLUTION. A URI that is already a node of the pinned KG is used directly
    and needs no network. Only when it is not does the identity bridge run, and
    under --offline-replay that lookup consults the cache and raises on a miss
    rather than reaching for a socket.
    """
    say("PRINT-FACTS-ONLY MODE")
    say("  This mode loads facts ONLY from the pinned local KG. No class "
        "ranking, no DBpedia class retrieval, no LRoleSim, no evidence "
        "classification, no rationale selection and no MCQ selection is run.")
    say(f"  pinned KG sha256 = {local_kg.source_sha256}")
    say("")

    printed = 0
    for line_number, uri, cohort in uris_with_lines:
        local_uri = uri
        note = "supplied URI resolves directly in the pinned local KG"
        if mcq_inputs.node_index_or_none(uri, local_kg) is None:
            # Only now is the identity bridge needed at all.
            identity = resolve_answer_identity(
                uri, local_lookup=context["local_lookup"],
                source=context["identity_source"])
            local_uri = identity.local_kg_uri or uri
            note = (f"resolved through the identity bridge: "
                    f"{identity.local_resolution_method}")
        record = v3.raw_fact_groups(local_uri, local_kg=local_kg)
        say("")
        if line_number is not None:
            say(f"(input line {line_number}"
                + (f", cohort {cohort}" if cohort else "")
                + f")   [{note}]")
        else:
            say(f"[{note}]")
        for text in v3.render_raw_facts(
                record, original_uri=uri, local_kg=local_kg,
                show_node_index=True):
            say(text)
        printed += 1

    say("=" * 100)
    say(f"PRINT-FACTS-ONLY: {printed} Answer(s) printed. Nothing was ranked, "
        f"scored, classified or selected.")
    if args.output_report is not None:
        target = Path(args.output_report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(TRANSCRIPT) + "\n", encoding="utf-8")
        print(f"Facts report written to {target}", flush=True)
    return EXIT_OK if printed else EXIT_BLOCKED


# ==========================================================================
# 3) Command line
# ==========================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_phase_b2_any_answer_v3.py",
        description=("Run ANY Answer (or an Answers.txt batch, or a line range "
                     "of one) end to end: identity bridge -> automatic v6 class "
                     "ranking -> local mapping -> candidate-validity screen -> "
                     "M1 graph -> frozen LRoleSim -> semantic-index rebuild -> "
                     "frozen Phase-B selection. Or print raw pinned-KG facts "
                     "only."),
        epilog=("Exactly one of --allow-network / --offline-replay is required. "
                "The selected class is the FIRST locally mapping-feasible class "
                "of an automatic ranking, never a globally optimal class."),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--answer-uri", type=str, default=None,
                        help="run ONE Answer and print its complete report")
    source.add_argument("--input", type=Path, default=None,
                        help="Answers.txt-format file to run as a batch")

    parser.add_argument(
        "--alpha", type=float, default=None,
        help=(f"semantic weight for the v6 class ranking, 0 <= alpha <= 1 "
              f"(default {v6.DEFAULT_ALPHA}, the pre-specified main working "
              f"configuration; NOT a claim of optimality)"))
    parser.add_argument(
        "--output-report", type=Path, default=None,
        help=("write the full human-readable report to EXACTLY this path. When "
              "omitted no report file is created and no default name is "
              "invented"))
    parser.add_argument(
        "--artifacts-dir", type=Path, default=None,
        help=("write the machine-readable per-Answer artifact tree under this "
              "directory. When omitted no artifact tree is created"))
    parser.add_argument(
        "--metrics-json", type=Path, default=None,
        help="write the §18 batch metrics to EXACTLY this JSON path")
    parser.add_argument(
        "--metrics-csv", type=Path, default=None,
        help="write the §18 batch metrics to EXACTLY this CSV path")

    parser.add_argument("--allow-network", action="store_true",
                        help="opt in to contacting DBpedia and Wikipedia")
    parser.add_argument("--offline-replay", action="store_true",
                        help="strict offline: every cache miss raises")

    # --- §15 / §16 -------------------------------------------------------
    parser.add_argument(
        "--print-facts-only", action="store_true",
        help=("print EVERY raw pinned-KG fact of the selected Answer(s), "
              "grouped by (predicate, direction), and stop. No class ranking, "
              "no LRoleSim, no evidence, no selection"))
    parser.add_argument(
        "--lines-for-input-file", type=str, default=None, metavar="START-END",
        help=("execute only the Answer rows whose SOURCE LINE in --input lies "
              "in this 1-based INCLUSIVE range, e.g. 11-33. The whole file is "
              "still parsed so the active cohort is known. Valid only with "
              "--input"))

    # --- versioned policy switches (§5, §7, §9, §10, §12) ----------------
    parser.add_argument(
        "--predicate-policy", choices=("v1", "v2"), default="v2",
        help="which predicate/quality policy generation to load")
    parser.add_argument(
        "--semantic-policy", choices=("v1", "v2"), default="v2",
        help="which semantic-relation policy generation to load")
    parser.add_argument(
        "--class-leakage-policy", choices=("v1", "v2"), default="v2",
        help="which class-only leakage policy generation the v6 selector uses")
    parser.add_argument(
        "--rationale-objective", choices=("v1", "v2", "v3"), default="v2",
        help=("which VERSIONED rationale ordering key 4 uses. v1 is the frozen "
              "fourteen-field key. v2 inserts option_reference_conflict after "
              "the complete evidence profile. v3 additionally places the "
              "semantic granularity risk and the conflict ABOVE the "
              "SCOPED_EMPIRICAL annotation, which is the only placement that "
              "repairs the Augustus case; it is offered, measured and NOT made "
              "the default"))
    parser.add_argument(
        "--candidate-type-policy",
        choices=("observe-only", "person-strict"), default="observe-only",
        help=("observe-only publishes every candidate-type verdict and removes "
              "nothing; person-strict removes a non-Person or unknown-type "
              "candidate when the Answer itself is reliably a Person"))
    parser.add_argument(
        "--reject-answer-name-containment", action="store_true",
        help=("remove a candidate whose name CONTAINS the Answer's complete "
              "name contiguously (Muhammad / Muhammad_in_Islam). Off by "
              "default; implied by --candidate-type-policy person-strict"))
    parser.add_argument(
        "--v2-compatible", action="store_true",
        help=("name the v1 generation of every policy above at once, "
              "reproducing the Prompt 8H-B2-D run exactly"))

    parser.add_argument(
        "--member-cache", type=Path,
        default=REPO_ROOT / "data" / "cache" / "phase_b2_class_members_v1.sqlite",
        help="SQLite page cache for class members, redirects and identity probes")
    parser.add_argument(
        "--score-cache", type=Path,
        default=REPO_ROOT / "data" / "cache" / "phase_b2_graph_lrolesim_v1.jsonl",
        help="LRoleSim score cache, keyed by the full run fingerprint")
    parser.add_argument(
        "--sparql-cache", type=Path,
        default=REPO_ROOT / "cache" / "category_v6_sparql.sqlite",
        help="SQLite response cache for the v6 class-selection queries")
    parser.add_argument(
        "--wikipedia-cache", type=Path,
        default=REPO_ROOT / "cache" / "category_v6_wikipedia_leads.json",
        help="JSON cache of Wikipedia lead sections")
    parser.add_argument(
        "--semantic-index-root", type=Path,
        default=REPO_ROOT / "data" / "semantic_index_v3" / "phase_b2_any_answer_v3",
        help=("directory under which each Answer's semantic index is written as "
              "<answer-slug>__<source-object-set-digest>.json; one shared file "
              "for every Answer would be a cache-key violation"))
    parser.add_argument(
        "--max-classes", type=int, default=12,
        help=("maximum ranked classes whose members may be retrieved before the "
              "walk gives up; exhausting it is reported as a walk failure, never "
              "as 'no feasible class exists'"))
    parser.add_argument("--min-remote-candidates", type=int, default=10)
    parser.add_argument("--max-remote-candidates", type=int, default=5000)
    parser.add_argument(
        "--total-entities", type=int, default=None,
        help=("explicit IDF universe N; overrides the run-level global-count "
              "query and makes an offline replay reproduce a live run exactly"))
    parser.add_argument("--sbert-model", type=str, default=v6.DEFAULT_SBERT_MODEL)
    parser.add_argument("--no-sbert", action="store_true",
                        help="skip semantic scoring; every class row is then "
                             "stamped idf_only_semantic_unavailable")
    parser.add_argument("--semantic-source",
                        choices=[s.value for s in v6.SemanticSource],
                        default=v6.SemanticSource.WIKIPEDIA_LEAD.value,
                        help="ONE source per run; the two are never mixed")
    parser.add_argument("--limit", type=int, default=None,
                        help="process only the first N selected Answers")
    return parser


def runner_config_from_args(args) -> v3.RunnerConfigV3:
    """Turn the policy switches into ONE recorded configuration object."""
    if args.v2_compatible:
        return v3.V2_COMPATIBLE_RUNNER_CONFIG
    validity = CandidateValidityPolicy(
        type_policy=(TYPE_POLICY_PERSON_STRICT
                     if args.candidate_type_policy == "person-strict"
                     else TYPE_POLICY_OBSERVE_ONLY),
        reject_answer_name_containment=bool(
            args.reject_answer_name_containment
            or args.candidate_type_policy == "person-strict"),
    )
    return v3.RunnerConfigV3(
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


def build_context(args, local_kg, config: v3.RunnerConfigV3):
    """Every client and policy one run needs, constructed AFTER the network gate."""
    from classes.member_mapper import make_local_lookup

    if args.allow_network:
        retriever, redirects, fetcher, _ = b2.open_live_retrieval(
            cache_path=args.member_cache)
        sparql = v6.make_dbpedia_runner(cache_path=str(args.sparql_cache))
    else:
        retriever, redirects, fetcher, _ = b2.open_offline_retrieval(
            cache_path=args.member_cache)
        sparql = v6.SparqlRunner(
            client=v2cli.OfflineSparqlClient(),
            cache=v6.SqliteSparqlCache(str(args.sparql_cache)))

    universe = v6.resolve_idf_universe(sparql, explicit_total=args.total_entities)
    encoder = None if args.no_sbert else v6.SbertEncoder(name=args.sbert_model)
    leads = WikipediaLeadClient(
        transport=RequestsWikipediaTransport(user_agent=DEFAULT_USER_AGENT),
        cache=WikipediaLeadCache(args.wikipedia_cache),
        allow_network=bool(args.allow_network))
    return {
        "config": config,
        "local_kg": local_kg,
        "local_lookup": make_local_lookup(local_kg.url_index),
        "retriever": retriever,
        "redirects": redirects,
        "fetcher": fetcher,
        "identity_source": SparqlIdentitySource(fetcher=fetcher),
        "sparql": sparql,
        "universe": universe,
        "encoder": encoder,
        "leads": leads,
        "semantic_source": v6.SemanticSource(args.semantic_source),
        "quality_policy": load_quality_policy(config.predicate_policy_path),
        "semantic_policy": load_semantic_relation_policy(
            config.semantic_policy_path),
        "base_rules": load_evidence_rules(EVIDENCE_RULES_PATH),
    }


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
    if args.alpha is None:
        args.alpha = v6.DEFAULT_ALPHA
    try:
        args.alpha = v6.validate_alpha(args.alpha)
    except ValueError as exc:
        say(f"ERROR: {exc}")
        return EXIT_USAGE

    # --- §16: the line range --------------------------------------------
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

    # --- the input -------------------------------------------------------
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
                f"rows. Blank lines, #COMMENT: rows, #COHORT: markers and other "
                f"comments are never Answer rows and can never be selected; the "
                f"WHOLE file was parsed so the cohort of each selected line is "
                f"known, and the cohort remains metadata only.")
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

    # --- §15: facts-only mode -------------------------------------------
    if args.print_facts_only:
        return run_facts_only(selected, local_kg=local_kg, context=context,
                              args=args)

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
            say(f"    FAILED: {type(exc).__name__}: {exc}")
            say(traceback.format_exc())
        say(f"    STATUS: {result.status}"
            + (f" — {result.detail}" if result.detail else ""))
        results.append(result)
        if getattr(result, "candidate_screen", None) is not None:
            screens.append(result.candidate_screen)
        if out_dir is not None:
            write_answer_artifacts_v3(out_dir, result)
            say(f"    artifacts -> {out_dir}")

    # --- the batch summary ----------------------------------------------
    metrics = v3.batch_metrics(results, config=config, screens=screens)
    say("")
    say("=" * 100)
    say("BATCH SUMMARY")
    say("=" * 100)
    say("")
    say(v3.summary_table_v3(results))
    say("")
    say(v3.prose_summary_v3(results, metrics))
    say("")
    say("=" * 100)
    say("BATCH METRICS")
    say("=" * 100)
    say("")
    say(v3.metrics_markdown(metrics))

    if args.output_report is not None:
        target = Path(args.output_report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(TRANSCRIPT) + "\n", encoding="utf-8")
        print(f"Full human-readable report written to {target}", flush=True)
    else:
        print("No output report file was created because --output-report was "
              "not specified.", flush=True)

    metrics["run_manifest"] = {
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
        "input_audit": parsed.audit() if parsed is not None else None,
        "line_range": list(line_range) if line_range else None,
        "duration_seconds": round(time.time() - started, 3),
    }
    if args.metrics_json is not None:
        Path(args.metrics_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.metrics_json).write_text(
            json.dumps(metrics, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print(f"Batch metrics -> {args.metrics_json}", flush=True)
    if args.metrics_csv is not None:
        rows = v3.metrics_csv_rows(metrics)
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
            row["rationale_objective"] = (
                None if selection is None else selection.rationale_objective)
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
