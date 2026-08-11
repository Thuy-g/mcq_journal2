# Phase B2 — Albert Einstein preconditions (not started)

**Date** 2026-08-11/12 · **Task** Prompt 8H-B1.5 §8 · **Status** PLANNING ONLY.
No SPARQL was issued while producing this document. No class was chosen. No
class members were retrieved. No LRoleSim run was performed. `build_and_select()`
was not called for Albert Einstein. This document restates and orders
already-established conclusions; it authorizes nothing.

---

## 1. Restating the B0/B1 conclusion

Per `docs/audits/ALBERT_EINSTEIN_PHASE_B_READINESS.md` (Prompt 8H-B0,
2026-08-10) and unchanged by B1.1–B1.4:

Albert Einstein (`http://dbpedia.org/resource/Albert_Einstein`, pinned-KG node
index `417144`) currently has:

* **66 observed one-hop Answer facts** in the pinned local KG
  (`data/infobox.pickle_EnglishVersion_EntityType`, `sha256 e230c5b9…`) — 9 OUT
  across 6 predicates, 57 IN across 22 predicates, 60 distinct counterpart
  entities. Applying the frozen R1 quality layer to these 66 facts yields 48
  eligible (17 distinct predicate/direction keys, 41 with a registered
  template) and 18 rejected (15 `ANSWER_LEXICAL_LEAK`, 2
  `PREDICATE_RAW_LAYOUT_SLOT`, 2 `PREDICATE_EXTERNAL_URL_FIELD`, 1
  `OBJECT_EXTERNAL_URL`, 1 `OBJECT_WEB_ARCHIVE_URL`; two facts carry more than
  one reason). This half of the `AnswerCase` contract is offline-derivable
  today and has already been measured, not merely estimated.
* **No approved candidate roster.** No human-approved class exists for
  Albert Einstein (`data/pilot_class_policy_v1.csv` covers nine unrelated
  pilot Answers only); no class-member list exists locally or in cache for
  any Einstein-related class; the pinned dump contains no `dcterms:subject`
  edge, so a roster cannot be derived offline even if a class were approved.

Nothing in B1.1–B1.4 changes this: B1.4's `build_and_select()` was proven only
against the eight frozen pilot Answers and against the Answer-only half of a
record contract; it was never invoked, and cannot yet be invoked, on Albert
Einstein, because invariant checks in `mcq_inputs.py` require a non-empty,
ranked `candidates` tuple that does not exist for him.

---

## 2. The exact dependency order before B2 can run

Each arrow is a hard prerequisite for the next; none may be skipped, reordered,
or filled with placeholder data. This restates
`docs/plans/PHASE_B1_MINIMAL_IMPLEMENTATION_PLAN.md` §7 and
`ALBERT_EINSTEIN_PHASE_B_READINESS.md` §5, aligned to the two-file B1.1–B1.4
adapter that now exists.

```
1. human-approved class
       |  a person, not code, ticks a worksheet checkbox for a controlled
       |  class URI (see §3) — currently unticked for every Einstein proposal
       v
2. complete class-member list
       |  an approved SPARQL run over the approved class, retrieving every
       |  ?member dcterms:subject <Category:...> — the pinned infobox dump has
       |  no such edge, so this step needs live network access, not the cache
       v
3. local mapping
       |  Week-1 stage: map each remote member URI into the pinned local KG
       |  (or record it as NO_LOCAL_MATCH), producing a MappedCandidate list
       v
4. graph-feasible candidates
       |  src/pipeline/graph_lrolesim_run.py's graph-admission stage: build
       |  the M1 graph over Answer + mapped candidates, apply the node cap and
       |  the neighbourhood-coverage-1.0 requirement
       v
5. frozen LRoleSim run
       |  src/lrolesim/adapter.py driving MCQ_lrolesim_ClaudeWeb_v2.py at the
       |  five pinned parameters (ranker_name=lrolesim_m1_fixed_k3,
       |  measure=lrolesim_ed, beta=0.2, iterations=3, mode=fixed) — never a
       |  different beta or a different iteration mode
       v
6. complete ranked roster
       |  Candidate.rank / Candidate.score for every graph-feasible candidate,
       |  contiguous unique ranks, unique URIs (mcq_inputs.py invariant 4)
       v
7. enlarged semantic-index source-object set
       |  Answer facts' counterpart objects UNION every candidate's observed
       |  objects under the same predicate/direction keys — this set does not
       |  exist yet because the candidate half does not exist
       v
8. semantic-index rebuild
       |  build_semantic_index_from_pinned_kg() in
       |  src/pipeline/rationale_v3_run.py, run OFFLINE over the enlarged
       |  source-object set from step 7. The existing pilot cache
       |  (data/semantic_index_v3/pilot_place_containment_v1.json) is keyed to
       |  the pilot's own source-object digest and is REJECTED, not reused,
       |  for any input outside that pilot (SemanticIndexCacheKey.matches()) —
       |  confirmed by the B0 audit, not assumed here
       v
9. build_and_select()
       |  src/mcq_inputs.py's B1.2 (answer_facts_from_local_kg),
       |  B1.3 (levels_for_candidates), B1.4 (build_and_select) — already
       |  implemented and tested against the eight frozen pilot Answers,
       |  requiring no further code changes to accept a new Answer once
       |  steps 1-8 supply real inputs
```

Steps 1 and 2 are the two gaps the B0 audit labelled GAP-1 (governance) and
GAP-2 (network, hard); step 2 is the only step in this chain that requires
network access. Steps 3–8 are offline engineering already implemented upstream
of `mcq_inputs.py` (Week-1 mapping, `graph_lrolesim_run.py`,
`lrolesim/adapter.py`, `rationale_v3_run.py`) and exercised on the nine-Answer
pilot; none of them have been run for Albert Einstein because none can start
before step 1 and step 2 clear.

---

## 3. The three existing class proposals — recorded, not approved

From `outputs/journal2_pdf_grounded_reconciliation_2026-07-30/class_decision_reconciliation.csv`
row `input_index=31` and `human_approval_worksheet.md` §31
(status `NEEDS_HUMAN_DECISION`, every checkbox unticked, `human_approval`
column empty):

| Position | Class | Basis | Eligible remote members |
|---|---|---|---|
| preferred | `dbc:German_theoretical_physicists` | `USE_EXISTING_ALTERNATIVE` (7A-R), `NEEDS_HUMAN_DECISION` (7A-F) | 72 |
| fallback 1 | `dbc:Nobel_laureates_in_Physics` | BATCH-derived | 217 |
| fallback 2 | `dbc:20th-century_German_physicists` | BATCH-derived | 560 |

None of the three is approved. This document records them for visibility only
and selects none of them; approving one is a human decision (step 1 above),
not a task this audit performs.

Note for whoever makes that decision later: the batch-34 scoring behind these
three proposals had `sbert_enabled: false` and `local_check: "not_applicable"`
(`ALBERT_EINSTEIN_PHASE_B_READINESS.md` §4.3) — every `combined_score` was
IDF-only and none of the three classes was ever checked against the pinned
local KG. Two of the three (217 and 560 members) exceed the 107-candidate
threshold at which `C(n,3)` passes the kernel's 200,000-combination budget, so
either would run under `POOL_EXACT` rather than `FULL_EXACT` and would carry
no optimality claim over excluded candidates.

### Explicitly rejected: `dbc:Einstein_family`

The batch-34 run's *automatic* top-1 for Albert Einstein was
`dbc:Einstein_family` (`combined_score=1.0`, `feasible=true`,
class-level `leak_level="no_leak"`). It is rejected here, explicitly, and must
not be used:

* It is Answer-name leakage that the class-level leak detector missed. The
  frozen R1 fact-level rule (`rationale_v3.quality.detect_answer_leakage()`),
  run on the same pair, returns **HARD** (`WHOLE_TOKEN einstein`) —
  `docs/audits/ANSWER_LEAKAGE_DESIGN_AUDIT.md` §3, row 3 of the leakage table.
* The reconciliation already rejected it in favor of the three-class proposal
  above; it is not one of the three positions under consideration.
* Even at the class-selection level (a weaker rule than the fact-level one),
  the batch-34 record's own `leak_level="no_leak"` is now known to be a
  detector miss, not a considered acceptance — see
  `ANSWER_LEAKAGE_DESIGN_AUDIT.md` §6 item 1, which records this as a known,
  unfixed weakness of the class-level rule relative to the fact-level one.

---

## 4. What this document does not do

* Does not issue SPARQL, live or cached-replay.
* Does not choose among the three recorded class proposals.
* Does not retrieve class members for any class.
* Does not run the graph-admission stage, the LRoleSim adapter, or the
  semantic-index rebuild.
* Does not call `mcq_inputs.build_and_select()` or `case_from_local_records()`
  for Albert Einstein.
* Does not modify `data/pilot_class_policy_v1.csv`, the Week-1 mapping cache,
  or the semantic-index cache.

Phase B2 begins only after a human ticks one of the worksheet checkboxes in
§31 of `human_approval_worksheet.md` (or supplies another controlled class),
making step 1 of §2 the literal next action — not code.
