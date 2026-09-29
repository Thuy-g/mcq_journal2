# B3 ARCH-4 implementation contract — what `src/choice_evidence_v1/` must build

**Prompt** 8H-B3-ARCH-4 · **Date** 2026-09-19
**Status** CONTRACT for a FUTURE implementation task. No production code exists
or is created by ARCH-4. Every "MUST" below binds the implementer; every
section number in brackets refers to `B3_CHOICE_EVIDENCE_SPEC_ARCH4_2026-09-19.md`
("the spec"), which governs on any conflict.
**Specification version implemented** `choice_evidence_spec/ARCH-4/1.0.0`
(SHA-256 in `B3_ARCH4_FREEZE_MANIFEST_2026-09-19.json`).

---

## 1. Purpose and boundaries

The package turns one learner-facing v4 item into (a) the pre-answer clue plan
`S_pre`, (b) the post-answer explanation graph `S_post` / `G_ce`, (c) a
machine-readable record with provenance, and (d) batch metrics — exactly as the
spec defines them, with no free parameter beyond the configuration record of §4.

The package MUST NOT import `lrolesim`, MUST NOT call `mcq_core.select_distractors`,
MUST NOT construct an `AnswerCase`, MUST NOT write into any v4 artefact
directory, MUST NOT open the network, MUST NOT modify `src/mcq_core.py`,
`src/kg/graph_view.py`, the LRoleSim kernel/adapter, `src/selection/granularity_clean.py`,
`src/rationale_v3/policies/predicate_policy_v2.json`, or any v1–v4 runner.
`mcq_core` MAY be imported for its frozen dataclass types and `LEVEL_STRENGTH`.

Frozen pure functions the package MUST reuse rather than reimplement:
`mcq_inputs.candidate_objects_from_local_kg`, `normalize_uri`,
`rationale_v3.quality.assess_fact_quality`, `detect_answer_leakage`,
`leakage_tokens`, `display_label`, `kg.loader.load_local_kg` (SHA-256
verified), `pipeline.rationale_v3_run.build_semantic_index_from_pinned_kg`,
`load_semantic_index_cache`, `SemanticIndexCacheKey`, the semantic index's
`canonical()` / `classify()` / `ancestors()`, the alias policy
(`DEFAULT_ALIAS_POLICY.family_for`, `observed_objects_for_key`). The ARCH-3
audit script (`scripts/audit_b3_choice_evidence_decisions.py`) is the reference
realisation of the universe builder and the two solves; it is DEVELOPMENT code
and MUST NOT be imported by production code.

---

## 2. Package layout

```
src/choice_evidence_v1/
  __init__.py       version strings: SPEC_VERSION, PRE_KEYS_VERSION, POST_KEYS_VERSION,
                    STATUS_VERSION, GROUNDING_VERSION, RECORD_SCHEMA_VERSION, OPTION_ORDER_SCHEME
  contracts.py      vocabulary (tiers, grounding, risk, statuses, node kinds, roles), dataclasses
                    (ChoiceEvidenceConfig, TemplatePolicyRef, FactUniverse, Group, GroupSelection,
                    SolveRecord, ChoiceEvidenceGraph, ItemRecord)                         [spec §4, §10, §11]
  universe.py       build_universe(): enumeration, B3 semantic index, node identity, grouping,
                    grounding + risk, screens, tiers, attributes, canonical order          [spec §4, §5]
  grounding.py      ground_by_rule(), the Answer-owned copy rule, agreement counters     [spec §4.6]
  admissibility.py  pre_admissible(g) with reason codes (Arm C)                           [spec §6.1]
  milp.py           the Milp wrapper over scipy.optimize.milp; lexicographic_solve(); canonical fix
                                                                                           [spec §8.1–8.2]
  select_pre.py     solve_pre_node_aware(): C-PRE-1..5, keys k1..k6, witnesses, re-check  [spec §6, §8.3]
  select_post.py    solve_post(): C-POST-1..5, keys k1..k7, re-check                       [spec §7, §8.3]
  recheck.py        pure-Python feasibility + key-vector recomputation for both solves    [spec §8.3]
  oracle.py         exhaustive oracle (≤ 16 free groups)                                   [spec §8.5]
  bounding.py       the resource-guard fallback only (stratified bounding)                 [spec §5.3]
  option_order.py   BLOCK_BALANCED_4 printed-order scheme                                  [spec §9.4]
  graph.py          ChoiceEvidenceGraph from S_post (+ CLASS node), JSON + GraphML          [spec §9.3]
  clues.py          ClueGroupPlan for S_pre (group ids, letters, template ids; no prose)    [spec §9.2]
  prose.py          deterministic template rendering of clues and explanation basis       [spec §9.5]
  metrics.py        per-item and per-batch metrics                                          [spec §11]
  baselines.py      B0 rationale-only, B1 sorted-cut, B3 greedy, B2-normalised (own outputs) [spec §13]
scripts/run_phase_b3_choice_evidence_v1.py     offline runner over a v4 artefacts root
tests/test_choice_evidence_v1.py               invariants I-01 … I-24 (§9 below)
```

New work is additive: a later change to any frozen value is
`src/choice_evidence_v2/`, never a changed default in v1.

---

## 3. Configuration record (`ChoiceEvidenceConfig`, frozen values)

```python
ChoiceEvidenceConfig(
    spec_version            = "choice_evidence_spec/ARCH-4/1.0.0",
    pre_keys_version        = "ce_pre_keys/ARCH-4/1.0.0",
    post_keys_version       = "ce_post_keys/ARCH-4/1.0.0",
    status_version          = "ce_status/ARCH-4/1.0.0",
    grounding_version       = "ce_grounding/ARCH-4/1.0.0",
    record_schema_version   = "choice_evidence_v1/1.0.0",
    option_order_scheme     = "ce_option_order/BLOCK_BALANCED_4/1.0.0",
    B_pre                   = 4,            # optional clue GROUPS in S_pre
    B_post                  = 7,            # unique ENTITY NODES in S_post (CLASS exempt)
    K_A_pre                 = 0,
    K_A_post                = 0,
    alternatives_pre        = "OFF",
    alternatives_post       = "REQUIRED_WHERE_SHOWABLE",
    pre_admissibility_arm   = "C_no_A_excluding_support3",
    pre_keys                = ("uncovered_letters", "neg_shared_information", "neg_distinct_keys",
                               "clue_groups", "tier_sum", "token_sum"),           # then canonical
    post_keys               = ("absence_incidences", "risk_groups", "neg_shared_information",
                               "neg_distinct_keys", "entity_nodes", "tier_sum", "token_sum"),  # then canonical
    epsilon                 = 0,            # every level; no weighted sum
    universe_scope_default  = "UNIVERSE_FULL",
    optional_groups_guard   = 20000,
    solve_time_limit_seconds= 600.0,
    fallback_bounding       = {"strata": {"node_sharing": True, "k_per_key": 2, "k_per_letter": 5},
                               "n_max": 3200},
    solver                  = {"name": "highs-scipy-milp", "mip_rel_gap": 0.0, "threads": 1,
                               "presolve": True, "canonical_block": 24},
    oracle_max_free_groups  = 16,
    class_node              = {"retained": True, "budget_exempt": True, "kind": "CLASS",
                               "provenance": "remote_category_membership"},
    mode                    = "development" | "publication",
    template_policy         = TemplatePolicyRef(registry_path, registry_version, registry_sha256,
                                                supersedes_sha256),
    benchmark_seed          = None | int,   # publication: taken from the preregistration manifest
)
```

The config record MUST be written verbatim into `run_manifest.json` and its
SHA-256 onto every item record. In `publication` mode the runner MUST refuse to
start if `benchmark_seed` is None or the registry SHA-256 does not match the
file on disk.

---

## 4. Public API (signatures; semantics in the spec)

```python
build_universe(item: V4ItemRef, *, local_kg, quality_policy, semantic_policy, alias_policy,
               template_policy: TemplatePolicyRef, index_root: Path) -> FactUniverse
pre_admissible(group: Group) -> tuple[bool, list[str]]
solve_pre_node_aware(universe: FactUniverse, cfg: ChoiceEvidenceConfig) -> GroupSelection   # returns P, W, keys, SolveRecord
solve_post(universe: FactUniverse, pre: GroupSelection, cfg: ChoiceEvidenceConfig) -> GroupSelection
recheck_pre(universe, pre, cfg) -> RecheckResult         # feasibility incl. |N_mand ∪ nodes(P) ∪ W| ≤ B_post; key vector equality
recheck_post(universe, pre, post, cfg) -> RecheckResult
oracle_pre / oracle_post(...) -> Optional[list[str]]     # None when above the threshold
assign_option_order(items: Sequence[ItemRecord], benchmark_seed: int) -> None
build_graph(universe, post: GroupSelection, class_info) -> ChoiceEvidenceGraph
render_clues(universe, pre, template_policy) -> list[ClueSentence]
render_explanation(universe, post, template_policy) -> dict[str, list[Sentence]]   # per distractor, basis(d) only
item_record(universe, pre, post, graph, statuses, cfg, provenance) -> ItemRecord
```

Every function MUST be deterministic and side-effect free except for the
semantic-index cache under `index_root` (own cache key; a corrupted or missing
cache is rebuilt, never silently treated as "unavailable").

---

## 5. Item record schema (`choice_evidence_v1/1.0.0`)

```json
{
  "schema_version": "choice_evidence_v1/1.0.0",
  "spec_version": "choice_evidence_spec/ARCH-4/1.0.0",
  "config_sha256": "…",
  "item": {"key": "…", "answer_uri": "…", "display_label": "…", "batch": "…", "cohort": "…",
           "evidence_policy": "main-l1", "mcq_evidence_level": "MCQ-L1", "learner_facing": true,
           "rationale_objective": "…", "direct_identifier_flag": true,
           "direct_identifier_note": "local structural specificity only; not a difficulty claim",
           "granularity_risk_incidences": 0, "option_reference_conflict_count": 0},
  "letters": {"A": "<answer_uri>", "B": "<d1>", "C": "<d2>", "D": "<d3>",
              "distractor_positions": [0, 1, 2], "lrolesim_ranks": [1, 2, 3]},
  "printed_options": {"scheme": "ce_option_order/BLOCK_BALANCED_4/1.0.0", "benchmark_seed": 0,
                      "block_index": 0, "option_order": ["<uri>", "<uri>", "<uri>", "<uri>"],
                      "answer_printed_position": 3},
  "class": {"uri": "…", "label": "…", "provenance": "remote_category_membership:<cache>",
            "class_leak_level": "no_leak|soft_overlap", "class_selection_term": "first_feasible_class"},
  "universe": {"scope": "UNIVERSE_FULL", "edge_count": 0, "group_count": 0, "node_count": 0,
               "optional_groups": 0, "excluded_by_reason": {}, "node_identity_basis_counts": {},
               "semantic_index": {"available": true, "cache_key": "…", "source_object_list_sha256": "…",
                                  "policy_sha256": "…"},
               "guard_fired": false, "bounding": null},
  "rationale": {"facts": [{"fact_index": 17, "predicate_uri": "…", "direction": "OUT",
                            "counterpart_uri": "…", "family_key": ["…", "OUT"], "node": "…",
                            "verbalizable": true, "template_id": "…", "pedagogical_tier": 1,
                            "levels": {"B": "L1", "C": "L0", "D": "L1"}, "risks": {"B": "NONE", "C": "NONE", "D": "NONE"}}],
                "explanation_basis": {"B": [17], "C": [23], "D": [17]},
                "absence_incidences": 1, "fully_verbalizable": true},
  "groups": [{"gid": "g00000", "key": ["<slot>", "OUT"], "raw_keys": [["<p>", "OUT"]], "node": "…",
              "node_label": "…", "node_raw_uris": ["…"], "node_identity_basis": "CANONICAL_EQUIVALENT",
              "support": "ABC", "tier": "OPTIONAL_CONTEXT", "alt_for": "",
              "grounding": {"D": {"state": "ALTERNATIVE_OBSERVED", "risk": "NONE", "method": "setlogic"}},
              "attrs": {"s": 3, "a": 0, "n": 0, "excl_answer": 0, "t": 1, "verb": 1, "tok": 2, "len": 16,
                        "abs": 0, "alt": 1, "cont": 0, "unres": 0, "risk_present": 0, "risk_unmod": 0,
                        "risk_unres": 0, "soft": 0, "dl": 0, "rare": 12},
              "excluded_reasons": [], "pre_screens": [], "pre_admissible": true, "pre_inadmissible_reasons": [],
              "template_id": "…", "edges": ["f00011", "f00012", "f00019"]}],
  "edges": [{"edge_id": "f00011", "letter": "A", "predicate_uri": "…", "direction": "OUT",
             "counterpart_uri": "…", "group_id": "g00000", "fact_index": 17, "eligible": true,
             "frozen_levels": {"B": "L1", "C": "L0", "D": "L1"},
             "provenance": {"pinned_kg_sha256": "…", "fact_schema_version": "journal2-prompt8d-observed-fact-v1"}}],
  "pre_answer": {"B_pre": 4, "K_A_pre": 0, "arm": "C_no_A_excluding_support3", "admissible_count": 3,
                 "selected_groups": ["g00007"], "key_values": [0, -2, -1, 1, 1, 2],
                 "n1": {"mandatory_nodes": 3, "min_footprint": 2, "witness_nodes": ["…"], "core_ok": true},
                 "solver": {"name": "highs-scipy-milp", "scipy": "1.17.1", "levels": 6,
                            "statuses": ["OPTIMAL", "OPTIMAL", "OPTIMAL", "OPTIMAL", "OPTIMAL", "OPTIMAL"],
                            "canonical_blocks": 1, "seconds": 0.02},
                 "verified": true, "oracle_agreed": true, "status": "CE_SELECTED"},
  "post_answer": {"B_post": 7, "K_A_post": 0, "free_count": 40, "selected_groups": ["g00007", "g00009", "g00010"],
                  "key_values": [0, 0, -3, -2, 2, 3, 5], "entity_nodes": ["…"], "entity_node_count": 5,
                  "cover_alt": {"B": true, "C": true, "D": true}, "unshowable_letters": [],
                  "abs_incidences_exposed": 0, "risk_groups_exposed": 0, "unverbalizable_groups_exposed": 0,
                  "solver": {"…": "…"}, "verified": true, "oracle_agreed": null, "status": "CE_SELECTED"},
  "graph": {"left": ["A", "B", "C", "D"],
            "right": [{"node_id": "…", "kind": "ENTITY|CLASS", "uris": ["…"], "label": "…", "provenance": "…"}],
            "edges": [{"edge_id": "f00011", "from": "A", "to": "<node>", "orientation": "choice_to_node|node_to_choice",
                       "predicate_uri": "…", "direction": "OUT", "relation_label": "…|<raw predicate identifier>",
                       "role": "MANDATORY_RATIONALE|RATIONALE_ALTERNATIVE|OPTIONAL_CONTEXT|CLASS_FRAME"}],
            "node_annotations": [{"kind": "CONTAINMENT", "from": "<node>", "to": "<node>"}],
            "legend_note": "an edge is a fact recorded in the pinned snapshot; a missing edge means the snapshot records nothing, not that the fact is false"},
  "prose": {"frame": "…", "clues": ["…"], "question": "Who is A?",
            "explanation": {"B": ["…"], "C": ["…"], "D": ["…"]}, "non_exhaustivity_instruction_id": "H15/1.0.0"},
  "flags": {"rationale_option_reference_conflict": false, "rationale_unverbalizable_fact_count": 0,
            "rationale_granularity_risk_incidences": 0, "class_label_leak_level": "no_leak"},
  "provenance": {"template_policy": {"registry_path": "…", "registry_version": "…", "registry_sha256": "…",
                                     "supersedes_sha256": null},
                 "pinned_kg_sha256": "…", "quality_policy_sha256": "…", "semantic_relation_policy_sha256": "…",
                 "alias_policy": "…", "git_commit": "…", "python": "…", "scipy": "…"},
  "statuses": ["CE_SELECTED"]
}
```

Fields MUST NOT be renamed; additions are a new schema minor version.

---

## 6. Solver protocol details

* `Milp` wrapper: deterministic variable order (canonical), deterministic row
  order, `integrality = 1` everywhere, `mip_rel_gap = 0.0`, `disp = False`,
  `time_limit = cfg.solve_time_limit_seconds`; every call appends
  `(tag, n_vars, n_rows, status, seconds)` to the solve log.
* `lexicographic_solve(model, keys, canonical_vars)`: as spec §8.2. Any
  non-zero scipy status at any level aborts with that status name.
* The canonical fix MAY use blocks of 24 with coefficients `-2^(23-j)`; the
  block size is recorded.
* **N1 witnesses**: the returned witness set `W` (one node per satisfied
  COVER_ALT row, as chosen by the solver) MUST be recorded and used by
  `recheck_pre` — the development-only tolerance `<= b_post + 3` of the audit
  MUST NOT be reproduced.
* `y_o` linking in the post model MUST be two-sided (`y_o ≥ z_g`, `y_o ≤ Σ z_g`)
  so k5 is exactly the unique-node count.
* `recheck_*` MUST be written without numpy/scipy (plain Python sets and sums).
* Publication mode: any item with a status in {`CE_SOLVER_NOT_OPTIMAL_*`,
  `CE_RECHECK_FAILED`, `CE_NESTED_INFEASIBLE_AT_BUDGET`, `CE_NESTING_VIOLATED`,
  `CE_ANSWER_ENUMERATION_MISMATCH`, `CE_INPUT_CONTRACT_VIOLATION`} is excluded,
  counted in `run_manifest.json["excluded_by_status"]`, and the runner exits 2.

---

## 7. Runner

`scripts/run_phase_b3_choice_evidence_v1.py --artifacts-root <v4 run> --out <dir>
--mode development|publication --template-registry <path> --benchmark-seed <int>
[--workers N] [--baselines B0,B1,B3,B2-normalised]`

Outputs: `choice_evidence_items.jsonl`, `choice_evidence_metrics.json`,
`choice_evidence_summary.csv`, `solver_calls.jsonl`, `run_manifest.json`
(config verbatim, `TemplatePolicyRef`, KG digest, artefacts-root SHA256SUMS
digest, git commit, versions, status counts, excluded_by_status), and one
`baselines/<name>/` directory per requested baseline. Exit codes: 0 all items
processed; 2 publication-mode exclusion occurred; 3 input contract violation.
Environment: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1`; no
network; no cache creation at import time.

---

## 8. Template registry versioning (spec §4.12)

* A new registry is a NEW file `src/rationale_v3/policies/predicate_policy_v3.json`
  (or later) with fields `version`, `supersedes: {"path": …, "sha256": …}`,
  `templates: [{"predicate_uri", "direction", "template_id", "template", "pedagogical_tier", "notes"}]`.
  `predicate_policy_v2.json` MUST NOT be edited.
* Phase 1 adds the five high-impact keys; Phase 2 the remaining 43
  `SAFE_TO_TEMPLATE` keys; each `NEEDS_HUMAN_REVIEW` key is admitted only by an
  explicit researcher decision recorded in the registry notes; `REJECT` keys
  never. One unit test per template renders the deterministic census examples.
* `TemplatePolicyRef` is read once per run and recorded. Any run on a new
  registry version is a new, separately reported run; frozen development
  artefacts are never rewritten (spec §4.12).

---

## 9. Test plan (invariant → test)

| invariant | test (all offline, no network, fixtures from ARCH-3R universes) |
|---|---|
| I-01 | `test_upstream_fields_copied_verbatim`, `test_v4_artifacts_unchanged_after_run`, protected-hash test extended |
| I-02 | `test_in_out_never_merge` |
| I-03, I-04 | `test_letters_fixed_by_role` |
| I-05, I-20 | `test_rstar_groups_mandatory_and_atomic` |
| I-06, I-07 | `test_pre_admissibility_arm_c` |
| I-08 | `test_alternatives_post_only_and_cover_alt` |
| I-09 | `test_k_a_zero_both_exposures` |
| I-10 | `test_n1_reserves_post_footprint`, `test_post_never_infeasible_under_n1` |
| I-11, I-12 | `test_entity_node_budget_and_class_exempt` |
| I-13 | `test_nesting` |
| I-14 | `test_byte_identical_reruns`, `test_oracle_agreement_small_instances`, `test_canonical_maximality` |
| I-15 | `test_no_difficulty_vocabulary` |
| I-16 | `test_registry_has_no_entity_specific_template` |
| I-17 | `test_provenance_fields_present` |
| I-18 | `test_publication_mode_exact_only_exit_code` (time limit forced to 0) |
| I-19 | `test_every_edge_observed_in_pinned_kg` |
| I-21, I-22 | `test_prose_forbidden_phrases_absent`, `test_explanation_cites_basis_only` |
| I-23 | `test_option_order_block_balanced` |
| I-24 | `test_universe_full_unless_guard` |

Fixtures: at least six ARCH-3R universes (two persons, one chemistry, one
event, one place, one polity) copied under `tests/fixtures/choice_evidence_v1/`
with their SHA-256 pinned; one synthetic universe for I-02 and I-12; one
instance with ≤ 16 free groups for the oracle.

---

## 10. Blockers before implementation starts, and definition of done

Before: the recorded decisions (done 2026-09-19; manual signature pending); the
researcher's answer to "B3 may be implemented before the final benchmark run:
YES / NO"; this contract and the spec unchanged (freeze manifest hash).

Done when: every test of §9 passes offline; a development batch run on the
ARCH-3R item set reproduces the ARCH-3R designated-cell selections
(`B_pre = 4, B_post = 7, K_A_post = 0, Arm C, T0`) for every item at
`UNIVERSE_FULL`, with differences (if any) explained by the tightened N1
re-check and recorded; `python -m py_compile` on every module; the protected
hashes unchanged; no v4 artefact modified; the report lists tests run, passed,
failed and not run, exactly.
