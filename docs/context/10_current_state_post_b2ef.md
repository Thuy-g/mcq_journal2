# Current state — after Prompt 8H-B2-G

**Status marker** `PRE_FINAL_BENCHMARK_EVIDENCE_COMPLETE`
**Date** 2026-09-18
**Supersedes, as a STATUS statement only**, §33 of
`MCQ_Journal2_B2_B3_Context_Handoff_EN_2026-08-13.md`. That file's science is
unchanged and still authoritative where it speaks; only "where the project is"
has moved.

This file is the compact answer to "where are we?". It is meant to be read in
full. The long handoff documents are historical reference: read the section you
need, not the whole file.

---

## 1. What is finished

| Stage | State |
|---|---|
| Phase B1 — frozen kernel + production adapter | complete, regression-tested |
| LRoleSim archive source pin | closed (`26a72f1`) |
| Class selector | v6, automatic, Wikipedia-lead semantic scoring |
| Any-Answer end-to-end runner | v2 (B2-D), v3 (B2-E/F), v4 (B2-G candidate) |
| Development batches | 329 Answers (`Answers.txt`), 189 (`Answers_HISTORICAL_EVENTS_PLACES.txt`) |
| Pre-final-benchmark safety audit | Prompt 8H-B2-G, this task |

## 2. What has NOT started

Verbalization, the choice–evidence bipartite graph, the publication benchmark
and human evaluation. The B2-G run is an EVIDENCE run and declares no
publication-final policy.

## 3. The frozen things, restated once

* pinned KG `data/infobox.pickle_EnglishVersion_EntityType`,
  sha256 `e230c5b9…bea1b`; 6,685,753 nodes, 3,936,389 subjects with out-edges;
* LRoleSim execution `lrolesim_m1_fixed_k3` / `lrolesim_ed` / beta 0.2 /
  3 fixed iterations — applied, never extended, and it produces no rationale;
* the evidence taxonomy of `EVIDENCE_TAXONOMY_V1.md`: `NOT_COVERED`, `L0`,
  `L1`, `L2`, with `exclusion_basis` and `granularity_risk` on separate axes;
* exact minimum-cardinality set cover with ρ = 3;
* PROTECTED sources with pinned SHA-256: `src/mcq_core.py`,
  `src/kg/graph_view.py`, the LRoleSim kernel and adapter.

## 4. What Prompt 8H-B2-G added (all ADDITIVE and versioned)

| § | Addition | Where |
|---|---|---|
| 2 | third candidate policy `PERSON_GUARDED` (keeps UNKNOWN) | `classes/candidate_validity.py` |
| 3 | DETECTED-vs-REJECTED candidate metrics | `pipeline/phase_b2_any_answer_run_v4.py` |
| 5 | audited predicate-slot alias family `dbp:field`/`dbp:fields` | `rationale_v3/predicate_aliases.py` |
| 6 | granularity policy `report-only` / `require-clean` | `selection/granularity_clean.py` |
| 7 | rationale objective **v3** as the v4 candidate default | `pipeline/…_v4.py` |
| 8 | M1 `max_nodes` a declared parameter + budget diagnostics | `pipeline/…_v4.py` |
| 10 | class-feature rejection records wired through | `pipeline/…_v4.py` |
| 11 | second rank-retention denominator `L1+ = MCQ-L1 ∪ MCQ-L2` | `pipeline/…_v4.py` |

`scripts/run_phase_b2_any_answer_v4.py` is the runner. Nothing in v1/v2/v3
changed: a v3 run reproduces its published fingerprint byte for byte, and
`--v3-compatible` reproduces it through the v4 code path.

## 5. The measured facts a reader should carry forward

* **Candidate policies, 307 pools / 7,403 candidate rows** (recomputed):
  `OBSERVE_ONLY` removes 0 and leaves 0 pools below the mapping gate;
  `PERSON_GUARDED` removes 63 (44 NOT_PERSON + 19 name) and leaves **3**;
  `PERSON_STRICT` removes 1,353 (adding 1,292 UNKNOWN) and leaves **66**.
* **Detection ≠ rejection.** The name detector fires 19 times corpus-wide and
  the v3 metric reported `…leak_rejections = 0`, which was true and useless.
* **The `dbp:field` / `dbp:fields` split is real**: 20,485 subjects use the
  singular, 14,730 the plural, and exactly **one** uses both. Under exact
  keying that made `Joseph_Black` look like an absence for `Robert_Boyle`.
* **`max_nodes` failures have two different causes.** George Washington lost 6
  candidates to a 1,200-node budget (Answer base 247). Kingdom of Italy's own
  one-hop neighbourhood is **3,026 nodes**, so at 1,200 no class could rescue
  it and no candidate was ever considered.
* **Objective v3 repairs Augustus.** Of 42 minimum-cardinality covers, v1/v2
  chose `successor → Tiberius` on ranking field 5 (`-scoped_empirical`), with
  Tiberius a printed option; v3 chooses `deathPlace → Nola`.
* **The granularity detector is silent for `dbp:schoolTradition`.** Socrates'
  broad-vs-specific risk is real and is NOT flagged, so `require-clean` does
  not protect it. Socrates stays a Failure Analysis case.
* **The v2 table's missing `|R*|` was formatting.** 329 rows = 257 showing a
  cardinality + 47 that lost it to a 46-character truncation + 25 Answers with
  no selection at all. Rationale generation failed for none of the 47.

## 6. Terminology this project gets wrong easily

* The rationale ranking prefers **more** scoped-empirical incidences
  (`-scoped_empirical_incidences`), not fewer. It is an ordering annotation
  after the complete evidence-level profile and can never change a level.
* `direct_identifier = True` is **local structural specificity**, never
  "easy for a human".
* `L0` is snapshot absence, never falsity; `L1` is an observed alternative
  value, never exclusion.
* The selected class is `first_feasible_class`, never "globally optimal".

## 7. Known contradictions between documentation and code

Reported, not silently edited (see
`outputs/journal2_b2g_final_benchmark_safety_v4_2026-09-18/b2g_documentation_audit.md`):

1. `PHASE_B_INPUT_CONTRACT.md` §3.2 says an unverbalizable fact is "barred from
   the main corpus". In the current kernel `verbalizable` is **ordering key 9
   only**; `has_main_l1_selection` reads the evidence policy alone. An
   unverbalizable fact can and does appear in a selected main-L1 rationale.
2. The B2-E/F candidate-validity figures (7,384 / 6,030 / 1,307 / 30 / 17 /
   66-of-306) are close but not equal to the recomputation above; the
   differences are explained in the B2-G audit and come from report parsing and
   from 52-character name truncation, not from a policy change.

## 8. What happens next

`11_final_benchmark_candidate_policy.md` lists each open configuration choice
with its measured cost. Choosing them is a human decision and is step 1 of the
work order in `CLAUDE.md`.
