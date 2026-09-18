# Claude Code Instructions — MCQ Journal 2

## Project identity

- Repository root: `/home/thuy/projects/mcq_journal2`
- Primary implementation language: Python
- Primary development environment: Ubuntu WSL 2 on Windows 11

- Research topic: **A Method to Generate Choices with their Rationales for Multiple Choice Questions Using Knowledge Graphs**
- Conda environment: `mcq-journal2`
- Main knowledge source for the first complete experiment: DBpedia English infobox data
- Planned initial scale: at least 100 Answer entities, each targeting three distractors and a grounded rationale set

## Required context

Before editing code, read, in this order:

1. `docs/context/00_context_index.md` — the read-order table;
2. `docs/context/10_current_state_post_b2ef.md` — where the project actually is;
3. `docs/context/EVIDENCE_TAXONOMY_V1.md` — authoritative on evidence levels;
4. the task-specific files the index names;
5. the exact source file currently present on disk.

`docs/context/PHASE_B_INPUT_CONTRACT.md` is required before touching
`mcq_core.py` or `mcq_inputs.py`. The long handoff documents are HISTORICAL
reference: read the section you need, not the whole file.

Do not rely only on chat memory, comments at the top of files, or filenames.

## Language

- The user may communicate in Vietnamese.
- Explanations to the user may be in Vietnamese.
- Python identifiers, public APIs, docstrings, test names, CLI options, changelogs, and machine-readable output fields should be in English.
- Preserve Japanese text in source references when needed.

## Non-negotiable scientific boundaries

1. Journal 1 defined and evaluated LRoleSim.
2. Journal 2 **applies or integrates LRoleSim as a structural plausibility ranker**.
3. Do not claim that Journal 2 extends or changes the mathematical definition of LRoleSim unless the formula is deliberately changed and re-proved.
4. LRoleSim does not generate rationales.
5. Rationale optimization belongs in a separate module.
6. The LRoleSim matching bipartite graph is not the MCQ choice–evidence bipartite graph.
7. DBpedia follows an open-world setting. A missing triple is not automatically a false fact.
8. Use the term `observed_contrast` for a fact observed for the Answer but not observed for a distractor, unless an explicit negative has been independently verified.
9. Do not call a selected class globally optimal. Use `requested_class`, `recommended_class`, `top_ranked_class`, or `first_feasible_class`.
10. Do not claim that set cover, Hungarian matching, or bitmask dynamic programming is newly invented in this project.
11. The rationale ranking prefers **more** scoped-empirical incidences, not fewer:
    key field 5 is `-scoped_empirical_incidences` under objectives v1/v2 and
    field 7 under v3. Describe it that way. It is an ordering annotation that sits
    after the complete evidence-level profile and can never create, upgrade or
    rescue a level.
12. `direct_identifier = True` means only that the rationale is satisfied by the
    Answer alone within the local candidate pool. It is **local structural
    specificity**, never a claim that the item is easy for a human.

## File safety

- Never overwrite a source file whose outputs are published evidence.
- Add a NEW versioned file (v3, v4, ...) instead, and never move an old default.
- Treat Journal 1 source and regression fixtures as immutable archives.
- Do not edit unrelated modules in the same task.
- Do not commit, merge, push, reset, clean, or delete files unless the user explicitly requests it.
- Never use `git reset --hard`, `git clean -fd`, force push, or recursive deletion without explicit user approval.
- Do not modify large data files in `data/`.
- Do not silently change local KG node indices or pickle keys.

## Work order — current state (2026-09-18, after Prompt 8H-B2-G)

Steps 1-3 are COMPLETE. The category selector (v6), the frozen LRoleSim
adapter and the distractor/rationale pipeline are integrated and regression
tested, and development batches of 329 and 189 Answers have been run.

Remaining, in order:

1. Choose the publication configuration from the B2-G evidence:
   candidate-validity policy, granularity-risk policy, rationale objective,
   M1 node budget. `docs/context/11_final_benchmark_candidate_policy.md`
   states each option and what it costs. **This is a human decision.**
2. Run the final publication benchmark with that frozen configuration.
3. Verbalization, then the choice-evidence bipartite graph.
4. Human evaluation of a frozen automatic output.
5. Optimise performance only after correctness and yield are measured.

Do not start step 2 before step 1 is recorded.

## Editing workflow

Before editing:

```bash
pwd
git status
git branch --show-current
sha256sum <target-v2-file>
python -m py_compile <target-v2-file>
```

During editing:

- Prefer the smallest correct patch.
- Keep imports explicit.
- Avoid import-time network calls, model downloads, cache creation, and ranking.
- Unit tests must not require Internet.
- Mark Internet-dependent tests with `pytest.mark.integration`.
- Use deterministic sorting and tie-breaking.
- Record provenance for external queries and generated outputs.

After editing:

```bash
git status
git diff --stat
git diff
python -m py_compile <new-file>
python -m pytest -q <relevant-test-file>
```

Report:

- files created;
- files modified;
- files intentionally not touched;
- tests actually run;
- tests passed and failed;
- tests not run and why;
- deferred issues;
- exact commands for reproducing the checks.

Never write “all tests passed” unless all claimed tests were actually executed successfully.

## Network and external services

- Do not call DBpedia, download models, or perform other network operations unless the user approves.
- Unit tests should mock SPARQL and embedding services.
- Query failure, successful zero-result, and cache hit must be represented as different states.
- Do not cache network exceptions as valid empty results.

## Current module boundaries

```text
kg/               pinned-KG loading, URI mapping, the frozen M1 graph budget
classes/          class ranking, member mapping, class-leak and candidate validity
lrolesim/         the frozen Journal-1 ranker adapter (mathematics unchanged)
selection/        handoff contracts, observed facts, the granularity-risk policy
rationale_v3/     quality, evidence classification, semantic index, predicate aliases
mcq_core.py       the FROZEN selection kernel: set cover, rationale key, objective
mcq_inputs.py     the production adapter into the kernel
pipeline/         orchestration; scripts/ holds the runners
```

`mcq_core.py`, `src/kg/graph_view.py` and the LRoleSim kernel/adapter are
PROTECTED: `tests/test_pipeline_graph_lrolesim.py` pins their SHA-256. New work
is ADDITIVE and versioned — a new runner generation, never a changed default in
an old one. `v1`/`v2`/`v3` runners and their outputs are historical evidence.

Runners, newest last: `scripts/run_phase_b2_any_answer_v2.py` (B2-D),
`..._v3.py` (B2-E/F), `..._v4.py` (B2-G final-benchmark CANDIDATE).
