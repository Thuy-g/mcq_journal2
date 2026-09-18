# Journal 2 Context Index

Last updated: 2026-09-18 (Prompt 8H-B2-G)

This directory contains the compact context that Claude Code should read frequently. The PDFs under `docs/references/` remain the authoritative primary sources.

**Start here:** `10_current_state_post_b2ef.md` — where the project actually is.
**Before choosing the publication configuration:** `11_final_benchmark_candidate_policy.md`.

## Read order

| Task | Required context |
|---|---|
| Any code change | `CLAUDE.md`, `10_current_state_post_b2ef.md`, latest audit under `docs/audits/` |
| Evidence levels, anything touching L0/L1/L2 | **`EVIDENCE_TAXONOMY_V1.md` (authoritative)** |
| `mcq_core.py` / `mcq_inputs.py` | **`PHASE_B_INPUT_CONTRACT.md` (frozen)**, `10_current_state_post_b2ef.md` |
| Category selector | `03_journal2_algorithm_spec.md`, `05_refactoring_requirements.md`, `09_claims_and_terminology.md` |
| LRoleSim adapter | `02_lrolesim_summary.md`, `05_refactoring_requirements.md`, Journal 1 PDF |
| Distractor pipeline | `03_journal2_algorithm_spec.md`, `06_evaluation_plan.md`, `PHASE_B_INPUT_CONTRACT.md` |
| Choosing / running the final benchmark | `11_final_benchmark_candidate_policy.md`, `06_evaluation_plan.md`, `08_data_and_reproducibility.md` |
| Related-work writing | `04_related_work_okuhara_umematsu.md`, primary PDFs |
| Git/Claude Code workflow | `07_repository_workflow.md` |

## Current-state and policy files (read in full; they are short)

* `10_current_state_post_b2ef.md` — status after Prompt 8H-B2-G, the measured
  facts to carry forward, and the known documentation/code contradictions.
* `11_final_benchmark_candidate_policy.md` — every open configuration choice,
  its measured cost, the planned benchmark cohorts (evaluation metadata only)
  and the named Failure Analysis cases.

## Frozen specifications (authoritative; do not edit without reporting a contradiction first)

* `EVIDENCE_TAXONOMY_V1.md` — the single authority on what `NOT_COVERED`, `L0`,
  `L1`, `L2`, `exclusion_basis` and `granularity_risk` mean.
* `PHASE_B_INPUT_CONTRACT.md` — what an `AnswerCase` is and where each field
  comes from.

## HISTORICAL reference — read the section you need, not the whole file

These are large handoffs kept for provenance. They are **not** mandatory full
reads for a coding task, and their "current status" sections are superseded by
`10_current_state_post_b2ef.md`.

| File | Lines | What it is good for |
|---|---:|---|
| `MCQ_Journal2_B2_B3_Context_Handoff_EN_2026-08-13.md` | 900 | the scientific rationale behind §§8-28 (evidence taxonomy, IN/OUT, set cover, the six-key objective, POOL_EXACT) |
| `MCQ_Journal2_Context_Handoff_after_Prompt8C_2026-07-30.md` | ~460 | class-selection history before v5 |
| `Hiroshi_Amano_PhaseB_Source_Code_Walkthrough.md` | ~1300 | one Answer traced line by line through the Phase-B code |
| `ClassPolicy_…_BeforePrompt8B_2026-07-30_EN.txt` | large | pre-8B class policy, superseded by the v6 selector |

## Files

1. `01_project_goal.md` — research problem, intended contribution, scope, exclusions, and completion criteria.
2. `02_lrolesim_summary.md` — Journal 1 concepts that must remain mathematically unchanged.
3. `03_journal2_algorithm_spec.md` — task definition, pipeline, interfaces, rationale formulation, and output schema.
4. `04_related_work_okuhara_umematsu.md` — positioning against Umematsu, Okuhara 2019/2025, and other relevant approaches.
5. `05_refactoring_requirements.md` — confirmed v2 blockers, module boundaries, phased migration, and acceptance criteria.
6. `06_evaluation_plan.md` — research questions, baselines, metrics, ablations, human evaluation, and statistical reporting.
7. `07_repository_workflow.md` — Git branches, Claude Code operating rules, testing, review, and commit procedure.
8. `08_data_and_reproducibility.md` — dataset snapshots, hashes, seeds, cache metadata, environment capture, and run manifests.
9. `09_claims_and_terminology.md` — reviewer-safe terminology and claims that must not be made.
10. `10_current_state_post_b2ef.md` — current state after Prompt 8H-B2-G.
11. `11_final_benchmark_candidate_policy.md` — the open configuration choices and their measured costs.

## Authoritative references

Expected under `docs/references/`:

- `Official_LRoleSim_Aug2025.pdf`
- `Explainability_of_LRoleSim.pdf`
- `MCQ2025_Slides_Seminar20250604_Thuy.pdf`
- `Umematsu_Master_final.pdf`
- `Okuhara_2019_LinkedData_MCQ.pdf`
- `JIP2025_Okuhara.pdf`
- `SIGIR2017_Knowledge_Questions_from_Knowledge_Graphs.pdf`
- `Patra_Saha_2019_Named_Entity_Distractors.pdf`
- `Kurdi_2020_AQG_Systematic_Review.pdf`
- `Alhazmi_2024_Distractor_Generation_Survey.pdf`
- `Leo_2019_Ontology_Based_Medical_MCQs.pdf`

See `docs/references/README.md` for naming guidance.
