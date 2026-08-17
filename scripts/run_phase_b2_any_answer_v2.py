#!/usr/bin/env python
############################################################################
# scripts/run_phase_b2_any_answer_v2.py
#
# Prompt 8H-B2-D driver: run ANY Answer — or a whole Answers.txt batch — end to
# end, from the AUTOMATIC v6 class ranking through the frozen Phase-B selection
# kernel, with no `--v5-results` file and no per-Answer configuration.
#
# WHAT THIS SCRIPT IS
#   A sequencer plus a report writer. Every scientific decision belongs to a
#   frozen module and is delegated to it; see the module docstring of
#   `src/pipeline/phase_b2_any_answer_run.py` for the ownership table.
#
# WHAT IT REPLACES AND WHAT IT LEAVES ALONE
#   `scripts/run_phase_b2_answer.py` (Prompt 8H-B2-B) is NOT modified. It reads a
#   v5 `results.jsonl` and is the historical evidence of the Einstein run. This
#   script uses `category_extractor_v6` directly and needs no ranking file.
#
# WHAT IT DELIBERATELY STOPS BEFORE
#   Natural-language verbalization, final MCQ prose, choice-evidence bipartite
#   graph construction, the full ~100-Answer B3 experiment, and human
#   evaluation. The run ends at the frozen Phase-B selection result.
#
# NETWORK
#   Exactly one of --allow-network / --offline-replay is required; neither is
#   the default and no run proceeds without a choice. Under --offline-replay
#   every client is constructed so that a cache miss RAISES: the page fetcher
#   gets `client=None`, the SPARQL runner gets a transport that cannot open a
#   socket, and the Wikipedia client is built with `allow_network=False`. "This
#   replay made zero HTTP calls" is therefore a property of the object graph
#   rather than a claim about which branches happened to run.
############################################################################

from __future__ import annotations

import argparse
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
import mcq_inputs                                               # noqa: E402
import run_category_selector_v6 as selector_cli                 # noqa: E402
from classes.answer_identity import (                           # noqa: E402
    IdentityStatus,
    LocalResolutionMethod,
    SparqlIdentitySource,
    resolve_answer_identity,
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
from pipeline.graph_lrolesim_run import ATTEMPT_GRAPH_FEASIBLE  # noqa: E402
from pipeline.rationale_v3_run import (                         # noqa: E402
    EVIDENCE_RULES_PATH,
    PREDICATE_POLICY_PATH,
    SEMANTIC_POLICY_PATH,
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


#: Everything printed by this script, in order. `say()` writes here AND to
#: stdout, so the optional --output-report file is literally the terminal
#: session and cannot drift from it. No information required by the report
#: specification can end up in one and not the other.
TRANSCRIPT: list[str] = []


def say(message: str = "") -> None:
    TRANSCRIPT.append(message)
    print(message, flush=True)


# ==========================================================================
# Offline-mode clients: a cache miss must RAISE, never reach for a socket
# ==========================================================================


class OfflineSparqlClient:
    """A SPARQL client with no transport. Used by --offline-replay.

    `SparqlRunner` consults its cache first and calls the client only on a miss,
    so raising here makes "the replay issued no query" structural. A returned
    FAILED result would be indistinguishable from a real endpoint failure and
    would let a replay quietly report zero categories for an Answer that simply
    was not cached.
    """

    endpoint = v6.DEFAULT_ENDPOINT

    def run(self, query: str) -> v6.QueryResult:
        raise RuntimeError(
            f"strict offline mode: no cached SPARQL response for query "
            f"{v6.query_id(query)!r}; the replay cannot proceed without HTTP")


# ==========================================================================
# Per-Answer pipeline
# ==========================================================================


def run_one_answer(original_uri, *, cohort, context, args, out_dir):
    """The complete per-Answer pipeline, A through N. Never raises for science.

    A scientifically valid failure — no current categories, no locally mapping
    class, an infeasible graph, no valid final combination — returns a populated
    result with a status. Only a genuine programming error escapes, and even that
    is caught by the batch loop and recorded rather than allowed to abort a run
    that has already completed other Answers.
    """
    started = time.time()
    result = anyb2.AnswerRunResult(original_uri=original_uri, cohort=cohort,
                                   alpha=args.alpha)

    def finish(status: str, detail: str = "") -> anyb2.AnswerRunResult:
        result.status = status
        result.detail = detail
        result.seconds = time.time() - started
        result.sparql_stats = dict(context["sparql"].stats())
        result.fetcher_stats = dict(context["fetcher"].counters())
        return result

    # --- A. AnswerIdentity: original / remote query / pinned local URI ------
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

    # --- B. the automatic v6 class ranking ---------------------------------
    say(f"[B] extracting v6 class features (alpha={args.alpha}, "
        f"semantic source = {context['semantic_source'].value}) ...")
    lead = None
    if context["leads"] is not None:
        lead = context["leads"].fetch_many([answer_remote_uri]).get(answer_remote_uri)
    features = v6.extract_answer_features(
        answer_remote_uri,
        runner=context["sparql"], idf_universe=context["universe"],
        semantic_source=context["semantic_source"], wikipedia_lead=lead,
        encoder=context["encoder"], quality_policy=context["quality_policy"],
        max_remote_candidates=args.max_remote_candidates,
        min_remote_candidates=args.min_remote_candidates)
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
    print_class_ranking(ranking, context["universe"], args.alpha)
    if not ranked:
        return finish(S.NO_USABLE_CLASS,
                      "every discovered category was rejected by the feasibility "
                      "gates (size, administrative, or answer-revealing name)")

    # --- D/E. walk the ranking for LOCAL-MAPPING feasibility ---------------
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

    # --- G/H. the frozen M1 graph and the frozen LRoleSim ------------------
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

    # --- J/K. the exact enlarged source-object set, then the rebuild -------
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
    say(f"[G] rebuilding the semantic index OFFLINE from the pinned KG -> "
        f"{index_target.name}")
    try:
        index_path = build_semantic_index_from_pinned_kg(
            policy_path=SEMANTIC_POLICY_PATH, cache_path=index_target,
            source_object_uris=sources, local_kg=context["local_kg"],
            verbose=False)
        expected_key = SemanticIndexCacheKey(
            pinned_kg_sha256=b2.PINNED_LOCAL_KG_SHA256,
            policy_sha256=context["semantic_policy"].policy_sha256,
            source_object_list_sha256=key_digest,
            max_depth=context["semantic_policy"].max_depth,
            creation_command=("python scripts/run_phase_b2_any_answer_v2.py "
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

    # --- the rulebook: frozen base + R1's scoped-empirical derivation -------
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

    # --- M. the frozen Phase-B selection kernel ----------------------------
    say("[H] calling mcq_inputs.build_and_select() ...")
    # The roster identity the kernel records. When no artifacts directory was
    # requested the roster still exists — it is the in-memory complete ranked
    # pool — and its DIGEST is what actually identifies it, so a synthetic
    # location string is honest here and a fabricated file path would not be.
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
        provenance=run_provenance)
    result.case = case
    result.selection = selection
    result.record = record
    result.evidence_profiles = anyb2.summarise_candidate_evidence(case)

    print_lrolesim_ranking(result)
    if selection is None:
        return finish(S.NO_VALID_FINAL_COMBINATION,
                      "no combination of the roster reached full coverage under "
                      "any policy; a feasibility measurement, not an error")
    print_final_selection(result)
    if not result.has_main_l1_selection:
        return finish(S.NO_MAIN_L1_SELECTION,
                      f"a selection exists only under the "
                      f"{selection.evidence_policy} policy; L0 is snapshot "
                      f"absence and is never student-showable")
    return finish(S.SUCCESS_FULL_EXACT if selection.search_scope == "FULL_EXACT"
                  else S.SUCCESS_POOL_EXACT)


# ==========================================================================
# Human-readable per-Answer output. Nothing required here lives only in JSON.
# ==========================================================================


def print_class_ranking(ranking, universe, alpha) -> None:
    features = ranking.features
    say("")
    say(f"[C] COMPLETE FEASIBLE CLASS RANKING ({len(ranking.ranked)} classes) "
        f"— alpha={alpha}, scoring mode={ranking.scoring_mode.value}")
    say(f"    IDF universe N = {universe.total_entities} "
        f"[{universe.definition}]")
    say(f"    {'rk':>3}  {'class label':<44} {'n_c':>7} {'nIDF':>6} "
        f"{'nSBERT':>7} {'score':>7}  leakage")
    for entry in ranking.ranked:
        feature = entry.feature
        n_sb = ("    n/a" if entry.normalized_sbert is None
                else f"{entry.normalized_sbert:7.3f}")
        say(f"    {entry.feasible_rank:>3}  {feature.category_label[:44]:<44} "
            f"{feature.remote_count:>7} {entry.normalized_idf:6.3f} {n_sb} "
            f"{entry.combined_score:7.4f}  {feature.leak_level.value}"
            + (f" [{';'.join(feature.leak_evidence)}]"
               if feature.leak_evidence else ""))
        say(f"         {feature.category_uri}")
    rejected = features.rejected_classes
    if rejected:
        say(f"    REJECTED CLASSES ({len(rejected)}) — no feasible rank is "
            f"assigned; leakage is annotated INDEPENDENTLY of the size gates")
        for feature in sorted(rejected,
                              key=lambda c: (c.rejected_code or "", c.category_uri)):
            say(f"      [{feature.rejected_code}] {feature.category_uri}")
            say(f"          leakage={feature.leak_level.value} "
                f"[{feature.leak_status.value}] via {feature.leak_source}"
                + (f"  evidence: {', '.join(feature.leak_evidence)}"
                   if feature.leak_evidence else "")
                + (f"  all reasons: {', '.join(feature.rejection_reasons)}"
                   if len(feature.rejection_reasons) > 1 else ""))
    say("")
    say("    NOTE: this is an automatic recommendation ranking of FEASIBLE "
        "candidate-source classes.")
    say("          The top-ranked class is not claimed to be globally optimal "
        "or educationally best.")
    say("")


def print_lrolesim_ranking(result) -> None:
    execution = mcq_inputs.PINNED_LROLESIM_EXECUTION
    say("")
    say(f"[I] COMPLETE LRoleSim CANDIDATE RANKING ({result.complete_pool_size} "
        f"candidates) — this is the anonymity denominator's pool")
    say(f"    ranker={execution['ranker_name']} measure={execution['measure']} "
        f"beta={execution['lrolesim_beta']} iterations={execution['iterations']} "
        f"({execution['iteration_mode']})")
    say(f"    run fingerprint = {result.run_fingerprint}")
    say(f"    {'rk':>4}  {'candidate':<52} {'score':>12}  best  "
        f"{'L2':>3} {'L1':>3} {'L0':>3} {'NC':>4}  elig  L1+")
    for profile in result.evidence_profiles:
        say(f"    {profile.rank:>4}  {profile.uri.rsplit('/', 1)[-1][:52]:<52} "
            f"{profile.score:12.9f}  {profile.best_available_evidence_level:<11} "
            f"{profile.l2_incidences:>3} {profile.l1_incidences:>3} "
            f"{profile.l0_incidences:>3} {profile.not_covered_incidences:>4}  "
            f"{profile.eligible_fact_count:>4}  {profile.student_showable_fact_count:>3}")
    say("    best = the strongest level any ELIGIBLE Answer fact supplies for "
        "that candidate.")
    say("    An evidence level is a property of an ordered (fact, candidate) "
        "pair, never of a candidate alone.")
    say("")


def print_final_selection(result) -> None:
    selection, case, record = result.selection, result.case, result.record
    rationale = selection.rationale
    say(f"[J] FINAL SELECTED DISTRACTORS")
    for position, distractor in enumerate(selection.distractors):
        profile = next(p for p in result.evidence_profiles
                       if p.uri == distractor.uri)
        say(f"    {position + 1}. {distractor.uri}")
        say(f"       LRoleSim rank {distractor.rank} of "
            f"{result.complete_pool_size}, score {distractor.score!r}")
        say(f"       best level under the SELECTED rationale : "
            f"{rationale.per_candidate_best_level[position]}")
        say(f"       best level over ALL eligible facts      : "
            f"{profile.best_available_evidence_level}")

    say("")
    say(f"[K] MINIMUM RATIONALE  |R*| = {selection.minimum_rationale_size}  "
        f"(minimum level {selection.minimum_rationale_level}, "
        f"{selection.minimum_rationale_count_enumerated} minimum-cardinality "
        f"cover(s) enumerated)")
    for index in selection.rationale.fact_indices:
        fact = case.facts[index]
        say(f"    predicate : {fact.quality.predicate_uri}")
        say(f"    direction : {fact.quality.direction}")
        say(f"    object    : {fact.quality.counterpart_uri} "
            f"({fact.quality.display_label})")
        for position, distractor in enumerate(selection.distractors):
            slot = selection.positions[position]
            say(f"      {distractor.uri.rsplit('/', 1)[-1][:44]:<44} "
                f"level={fact.levels[slot]:<11} "
                f"basis={fact.exclusion_bases[slot]:<18} "
                f"granularity_risk={fact.granularity_risks[slot]}")

    say("")
    say(f"[L] OVERALL")
    say(f"    MCQ evidence level    : {selection.mcq_evidence_level}")
    say(f"    evidence policy       : {selection.evidence_policy}")
    say(f"    search scope          : {selection.search_scope}")
    say(f"    global optimality     : {record['global_optimality_claim']}")
    say(f"    pool optimality       : {record['pool_optimality_claim']}")
    say(f"    complete ranked pool  : {record['original_candidate_count']}")
    say(f"    bounded pool searched : {record['pool_candidate_count']} "
        f"({record['enumerated_combination_count']} combinations enumerated)")
    say(f"    anonymity count       : "
        f"{rationale.local_candidate_pool_anonymity_count} of "
        f"{result.complete_pool_size + 1} (Answer + COMPLETE ranked pool)")
    say(f"    anonymity ratio       : "
        f"{rationale.local_candidate_pool_anonymity_ratio!r}")
    say(f"    direct_identifier_flag: {rationale.direct_identifier_flag}")
    say(f"    granularity risk      : {rationale.granularity_risk_incidences}")
    say(f"    scoped empirical      : {rationale.scoped_empirical_incidences} "
        f"(an exclusion BASIS, not a fourth evidence level)")
    say(f"    > {record['search_scope_note']}")
    say("")


# ==========================================================================
# Artifacts
# ==========================================================================


def write_answer_artifacts(out_dir: Path, result) -> None:
    """The machine-readable per-Answer tree. Never a substitute for the report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    b2.write_json(out_dir / "answer_identity.json", result.identity.as_record())

    if result.class_ranking:
        b2.write_csv(out_dir / "class_ranking_complete.csv",
                     list(result.class_ranking[0].as_record().keys()),
                     [r.as_record() for r in result.class_ranking])
    if result.class_attempts:
        b2.write_csv(out_dir / "class_attempts_and_mapping.csv",
                     list(result.class_attempts[0].as_record().keys()),
                     [a.as_record() for a in result.class_attempts])
    if result.scored:
        b2.write_csv(
            out_dir / "complete_lrolesim_ranking.csv",
            ["rank", "canonical_candidate_uri", "score", "tie_group_id",
             "tie_group_size", "at_beta_floor", "mapping_origin",
             "admission_position"],
            [{"rank": c.rank, "canonical_candidate_uri": c.canonical_uri,
              "score": repr(c.score), "tie_group_id": c.tie_group_id,
              "tie_group_size": c.tie_group_size, "at_beta_floor": c.at_beta_floor,
              "mapping_origin": c.mapping_origin,
              "admission_position": c.admission_position} for c in result.scored])
    if result.evidence_profiles:
        b2.write_csv(out_dir / "complete_candidate_evidence_summary.csv",
                     list(result.evidence_profiles[0].as_record().keys()),
                     [p.as_record() for p in result.evidence_profiles])
    if result.case is not None:
        rows = anyb2.candidate_fact_evidence_rows(result.case)
        if rows:
            b2.write_csv(out_dir / "candidate_fact_evidence.csv",
                         list(rows[0].keys()), rows)
    if result.record:
        b2.write_json(out_dir / "final_selection.json", dict(result.record))
    if result.selection is not None and result.case is not None:
        rows = []
        for index in result.selection.rationale.fact_indices:
            fact = result.case.facts[index]
            for position, distractor in enumerate(result.selection.distractors):
                slot = result.selection.positions[position]
                rows.append({
                    "fact_index": index,
                    "predicate_uri": fact.quality.predicate_uri,
                    "direction": fact.quality.direction,
                    "counterpart_uri": fact.quality.counterpart_uri,
                    "counterpart_display_label": fact.quality.display_label,
                    "distractor_uri": distractor.uri,
                    "distractor_lrolesim_rank": distractor.rank,
                    "distractor_lrolesim_score": repr(distractor.score),
                    "evidence_level": fact.levels[slot],
                    "exclusion_basis": fact.exclusion_bases[slot],
                    "granularity_risk": fact.granularity_risks[slot],
                })
        b2.write_csv(out_dir / "rationale_evidence_detail.csv",
                     list(rows[0].keys()), rows)
    b2.write_json(out_dir / "run_manifest.json", {
        "schema_version": anyb2.ANY_ANSWER_SCHEMA_VERSION,
        "status": result.status,
        "detail": result.detail,
        "summary": result.summary_record(),
        "graph": dict(result.graph_row),
        "lrolesim_provenance": dict(result.lrolesim_provenance),
        "lrolesim_execution": dict(mcq_inputs.PINNED_LROLESIM_EXECUTION),
        "semantic_index_path": result.semantic_index_path,
        "semantic_source_object_count": result.semantic_source_count,
        "semantic_source_object_list_sha256": result.semantic_source_digest,
        "sparql_stats": dict(result.sparql_stats),
        "page_fetcher_stats": dict(result.fetcher_stats),
    })


# ==========================================================================
# Command line
# ==========================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_phase_b2_any_answer_v2.py",
        description=("Run ANY Answer (or an Answers.txt batch) end to end: "
                     "identity bridge -> automatic v6 class ranking -> local "
                     "mapping -> M1 graph -> frozen LRoleSim -> semantic-index "
                     "rebuild -> frozen Phase-B selection."),
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

    parser.add_argument("--allow-network", action="store_true",
                        help="opt in to contacting DBpedia and Wikipedia")
    parser.add_argument("--offline-replay", action="store_true",
                        help="strict offline: every cache miss raises")

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
        default=REPO_ROOT / "data" / "semantic_index_v3" / "phase_b2_any_answer_v2",
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
                        help="process only the first N unique Answers of a batch")
    return parser


def build_context(args, local_kg):
    """Every client one run needs, constructed AFTER the network gate."""
    from classes.member_mapper import make_local_lookup

    if args.allow_network:
        retriever, redirects, fetcher, _ = b2.open_live_retrieval(
            cache_path=args.member_cache)
        sparql = v6.make_dbpedia_runner(cache_path=str(args.sparql_cache))
    else:
        retriever, redirects, fetcher, _ = b2.open_offline_retrieval(
            cache_path=args.member_cache)
        sparql = v6.SparqlRunner(
            client=OfflineSparqlClient(),
            cache=v6.SqliteSparqlCache(str(args.sparql_cache)))

    universe = v6.resolve_idf_universe(sparql, explicit_total=args.total_entities)
    encoder = None if args.no_sbert else v6.SbertEncoder(name=args.sbert_model)
    leads = WikipediaLeadClient(
        transport=RequestsWikipediaTransport(user_agent=DEFAULT_USER_AGENT),
        cache=WikipediaLeadCache(args.wikipedia_cache),
        allow_network=bool(args.allow_network))
    return {
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
        "quality_policy": load_quality_policy(PREDICATE_POLICY_PATH),
        "semantic_policy": load_semantic_relation_policy(SEMANTIC_POLICY_PATH),
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

    # --- the input -------------------------------------------------------
    parsed = None
    cohorts: dict[str, Optional[str]] = {}
    if args.input is not None:
        if not Path(args.input).is_file():
            say(f"ERROR: input file not found: {args.input}")
            return EXIT_USAGE
        parsed = selector_cli.parse_answers_file(args.input)
        answers = list(parsed.unique_uris)
        cohorts = {uri: (parsed.cohorts_by_uri.get(uri) or [None])[0]
                   for uri in answers}
        say(f"Parsed {args.input}: {parsed.answer_row_count} Answer rows, "
            f"{len({r.answer_uri for r in parsed.rows})} unique URIs, "
            f"{parsed.duplicate_row_count} duplicate rows, "
            f"{len(parsed.cohort_order)} cohorts; {len(answers)} unique URIs are "
            f"runnable.")
        for number, text in parsed.malformed_rows:
            say(f"  INPUT PROBLEM line {number}: malformed row {text!r}")
        for number, text in parsed.invalid_uri_rows:
            say(f"  INPUT PROBLEM line {number}: not a valid IRI {text!r} "
                f"(EXCLUDED from the run)")
        if args.limit is not None:
            answers = answers[: max(0, args.limit)]
        if not answers:
            say(f"ERROR: {args.input} contains no usable Answer URIs.")
            return EXIT_USAGE
    else:
        answers = [str(args.answer_uri).strip()]

    say("Cohort labels are EVALUATION METADATA ONLY. They are carried into the "
        "output rows and are never passed to the class ranker, the graph, the "
        "LRoleSim ranker or the selection kernel.")

    started = time.time()
    say("")
    say("[0] loading the pinned local KG (SHA-256 verified before use) ...")
    local_kg = load_local_kg(b2.PINNED_LOCAL_KG,
                             verify_sha256=b2.PINNED_LOCAL_KG_SHA256)
    say(f"    pinned KG sha256 = {local_kg.source_sha256}")
    context = build_context(args, local_kg)
    say(f"    IDF universe N   = {context['universe'].total_entities} "
        f"[{context['universe'].definition}]")
    if not context["universe"].available:
        say("ERROR: no IDF universe N could be measured and none was supplied. "
            "No value was invented. Re-run with --total-entities N.")
        return EXIT_BLOCKED

    artifacts_root = (Path(args.artifacts_dir).resolve()
                      if args.artifacts_dir else None)
    results = []

    for number, uri in enumerate(answers, start=1):
        say("")
        say("=" * 100)
        say(f"ANSWER {number}/{len(answers)}: {uri}"
            + (f"   [cohort: {cohorts.get(uri)}]" if cohorts.get(uri) else ""))
        say("=" * 100)
        out_dir = (artifacts_root / f"{number:04d}_{anyb2.answer_slug(uri)}"
                   if artifacts_root else None)
        try:
            result = run_one_answer(uri, cohort=cohorts.get(uri),
                                    context=context, args=args, out_dir=out_dir)
        except Exception as exc:                                # noqa: BLE001
            # A failure is DATA. One Answer's crash must not discard the Answers
            # already completed, and must not vanish from the denominator either.
            result = anyb2.AnswerRunResult(
                original_uri=uri, cohort=cohorts.get(uri), alpha=args.alpha,
                status=S.QUERY_FAILED, detail=f"{type(exc).__name__}: {exc}")
            say(f"    FAILED: {type(exc).__name__}: {exc}")
            say(traceback.format_exc())
        say(f"    STATUS: {result.status}"
            + (f" — {result.detail}" if result.detail else ""))
        results.append(result)
        if out_dir is not None:
            write_answer_artifacts(out_dir, result)
            say(f"    artifacts -> {out_dir}")

    # --- the batch summary, ALWAYS printed to stdout ----------------------
    say("")
    say("=" * 100)
    say("BATCH SUMMARY")
    say("=" * 100)
    say("")
    say(anyb2.summary_table(results))
    say("")
    say(anyb2.prose_summary(results))
    say("")

    if args.output_report is not None:
        target = Path(args.output_report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(TRANSCRIPT) + "\n", encoding="utf-8")
        print(f"Full human-readable report written to {target}", flush=True)
    else:
        # No default filename is invented. The complete report has already gone
        # to stdout, so nothing is lost by not writing a file.
        print("No output report file was created because --output-report was "
              "not specified.", flush=True)

    if artifacts_root is not None:
        rows = [r.summary_record() for r in results]
        b2.write_csv(artifacts_root / "batch_summary.csv",
                     list(rows[0].keys()), rows)
        b2.write_csv(
            artifacts_root / "failure_summary.csv",
            ["original_uri", "cohort", "status", "detail"],
            [{"original_uri": r.original_uri, "cohort": r.cohort,
              "status": r.status, "detail": r.detail}
             for r in results if not r.succeeded])
        b2.write_json(artifacts_root / "batch_manifest.json", {
            "schema_version": anyb2.ANY_ANSWER_SCHEMA_VERSION,
            "command_arguments": sys.argv[1:],
            "mode": "live" if args.allow_network else "offline-replay",
            "alpha": args.alpha,
            "alpha_note": ("the pre-specified main working configuration "
                           "selected after the development sensitivity "
                           "analysis; not claimed to be an optimum"),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "pinned_kg_sha256": local_kg.source_sha256,
            "idf_universe": context["universe"].to_dict(),
            "lrolesim_execution": dict(mcq_inputs.PINNED_LROLESIM_EXECUTION),
            "class_leakage_policy":
                v6.DEFAULT_DERIVATIONAL_POLICY.as_record(),
            "answers_attempted": len(results),
            "answers_succeeded": sum(1 for r in results if r.succeeded),
            "input_audit": parsed.audit() if parsed is not None else None,
            "duration_seconds": round(time.time() - started, 3),
        })
        print(f"Batch artifacts -> {artifacts_root}", flush=True)

    return EXIT_OK if any(r.succeeded for r in results) else EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
