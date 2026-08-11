# Phase B1 — final dependency architecture

**Date** 2026-08-12 · **Task** Prompt 8H-B1.5 §2–5 · **Nature** read-only
architecture audit. No production Python file was created, modified, or
deleted while producing this document. Classifications below are traced from
actual `import` statements and actual call sites, not inferred from directory
names.

**Decision:** `KEEP_CURRENT_MODULAR_DEPENDENCIES`. See §6 for the reasoning.

---

## 1. Classification vocabulary

| Label | Meaning |
|---|---|
| `FINAL_RUNTIME_CORE` | Directly on `mcq_inputs.build_and_select()`'s live call path, or is that path itself. |
| `FROZEN_SCIENTIFIC_DEPENDENCY` | A scientific rule/policy the runtime path calls into, owned and tested upstream; never inlined. |
| `REFERENCE_OR_REGRESSION_ONLY` | Not on the live B1.4 path; kept only so an earlier stage/comparison remains re-runnable and byte-comparable. |
| `LEGACY_NOT_ON_FINAL_RUNTIME_PATH` | Superseded; nothing live imports it for its scientific content. |
| `FUTURE_EXTENSION_POINT` | Not called today; exists for a planned future use (B2 upstream stages, future L2 rules). |

---

## 2. The B1.4 runtime path itself

### `src/mcq_core.py` — `FINAL_RUNTIME_CORE`

The frozen selection kernel. Imports only `__future__`, `dataclasses`,
`itertools`, `math`, `typing` — no rationale/selection/kg dependency of any
kind. Provides `AnswerCase`, `Candidate`, `FactQuality`, `AnswerFact`,
`PoolPolicy`, `Selection`, `build_case()`, `select_distractors()`,
`canonical_record()`. Called directly by `mcq_inputs.build_and_select()`.
243 tests in `tests/test_mcq_core.py`. Needed for final Journal-2 batch
execution: yes — it is the kernel every Answer must pass through.

### `src/mcq_inputs.py` — `FINAL_RUNTIME_CORE`

The Phase-B1 input adapter (B1.1 frozen-record reader, B1.2 answer-facts-from-KG,
B1.3 per-candidate evidence classification, B1.4 `build_and_select`
orchestration). Imports `mcq_core` plus exactly five names from two upstream
packages (§3, §4). 174 tests in `tests/test_mcq_inputs.py`. This is the file
this whole audit exists to characterize the dependencies of.

---

## 3. `rationale_v3` — the frozen scientific dependency, kept upstream

`mcq_inputs.py` imports exactly four names, no more:

```python
from rationale_v3.quality import assess_fact_quality
from rationale_v3.semantic_relations import normalize_uri
from rationale_v3.contracts import RationaleProposition
from rationale_v3.evidence import classify_fact_against_candidate
```

### `src/rationale_v3/quality.py` — `FROZEN_SCIENTIFIC_DEPENDENCY`

**Role.** `assess_fact_quality()` is the R1 hard-eligibility filter and the
deterministic Answer-leakage rule (`detect_answer_leakage()`), driven by
`predicate_policy.json`. 485 lines.
**Called by B1.4?** Yes — `mcq_inputs.py`'s B1.2
(`answer_facts_from_local_kg`) calls `assess_fact_quality()` once per observed
fact to populate every `FactQuality` field.
**Other importers.** `src/pipeline/rationale_v3_run.py`,
`src/extract_and_select_distractors_v3.py` (via the pipeline module),
`tests/test_rationale_v3.py`.
**Tests.** Covered inside `tests/test_rationale_v3.py` (85 collected tests,
shared across the `rationale_v3` package) plus the leakage measurements
recorded in `docs/audits/ANSWER_LEAKAGE_DESIGN_AUDIT.md`.
**Frozen?** Yes — `docs/audits/ALBERT_EINSTEIN_PHASE_B_READINESS.md` §6
explicitly pins the leakage thresholds and forbids reimplementing them with
WordNet/spaCy/embeddings.
**Needed for final batch execution?** Yes, directly.

### `src/rationale_v3/evidence.py` — `FROZEN_SCIENTIFIC_DEPENDENCY`

**Role.** `classify_fact_against_candidate()` is, in its own module comment,
"the single place an evidence level is decided": nothing-observed → L0;
support test → NOT_COVERED; active L2 rule → L2 with `EvidenceProof`;
otherwise → L1. 790 lines.
**Called by B1.4?** Yes — `mcq_inputs.py`'s B1.3 (`levels_for_candidates`)
calls it once per (Answer fact, candidate) pair and copies its three
verdicts (level, exclusion basis, granularity risk) verbatim.
**Transitive calls.** `classify_fact_against_candidate()` itself calls
`rationale_v3.semantic_relations.normalize_uri()` (evidence.py, the
`objects = tuple(sorted({normalize_uri(uri) ...}))` step) and
`SemanticIndex.classify()` from the same module, and imports
`RationaleProposition`/`EvidenceProof`/level and exclusion-basis constants
from `rationale_v3.contracts`. So B1.3's one call transitively exercises
`quality`'s sibling modules `semantic_relations` and `contracts` — the reason
`mcq_inputs.py` also imports `normalize_uri` directly (B1.2 must agree with
B1.3 on fact identity, i.e. use the *same* normalization, not a second copy
of it).
**Other importers.** `src/pipeline/rationale_v3_run.py`.
**Tests.** `tests/test_rationale_v3.py` (85 tests, package-wide).
**Needed for final batch execution?** Yes, directly.

### `src/rationale_v3/contracts.py` — `FROZEN_SCIENTIFIC_DEPENDENCY`

**Role.** `RationaleProposition` (validates its own URIs/qualifier state on
construction), `EvidenceProof`, the level/exclusion-basis/granularity-risk
vocabularies, `validate_exclusion_basis()`, `validate_l2_assignment()`. 674
lines.
**Called by B1.4?** Yes — `mcq_inputs.py`'s B1.3 constructs a
`RationaleProposition` per Answer fact before calling
`classify_fact_against_candidate()`.
**Other importers.** `rationale_v3/evidence.py`, `rationale_v3/quality.py`
(shares the same vocabulary), `rationale_v3/selector.py`,
`rationale_v3/semantic_relations.py`.
**Tests.** `tests/test_rationale_v3.py`.
**Needed for final batch execution?** Yes, directly.

### `src/rationale_v3/semantic_relations.py` — `FROZEN_SCIENTIFIC_DEPENDENCY`

**Role.** `normalize_uri()` (exact-equal/redirect/canonicalization-aware URI
normalization), `SemanticIndex` (bounded-depth containment closure,
cache-keyed on KG hash + policy hash + source-object list + depth), and
`build`/`load` for the semantic-index cache. 660 lines.
**Called by B1.4?** Yes, directly (`normalize_uri` in B1.2) and transitively
through `evidence.classify_fact_against_candidate()` (B1.3).
**Other importers.** `rationale_v3/evidence.py`,
`src/pipeline/rationale_v3_run.py` (the only place permitted to build the
cache from the pinned 1.2 GB pickle, via
`build_semantic_index_from_pinned_kg()`).
**Tests.** `tests/test_rationale_v3.py`.
**Needed for final batch execution?** Yes for `normalize_uri`/`SemanticIndex`
directly; the cache-*build* half is a `FUTURE_EXTENSION_POINT` for any Answer
whose semantic index does not yet exist (Albert Einstein — see
`docs/plans/PHASE_B2_ALBERT_PRECONDITIONS.md` step 8).

### `src/rationale_v3/setcover.py` — `REFERENCE_OR_REGRESSION_ONLY`

**Role.** Exact minimum-cardinality set-cover search over the R1 evidence
tiers, used by the *older* R1 orchestration path. 470 lines.
**Called by B1.4?** No. `mcq_core.py` has its own independent set-cover
implementation (`coverage_mask()`, `minimum_cover_size_table()`,
`minimum_cover_size()`, `select_distractors()`) — a separate, frozen kernel
that `mcq_inputs.py` calls instead. `rationale_v3.setcover` is not imported by
`mcq_inputs.py` or `mcq_core.py` at all.
**Other importers.** `src/rationale_v3/selector.py`,
`src/pipeline/rationale_v3_run.py`, `tests/test_rationale_v3.py`.
**Tests.** `tests/test_rationale_v3.py`.
**Needed for final batch execution?** No — superseded by `mcq_core.py` on the
live path. Kept so the R1 pipeline (`extract_and_select_distractors_v3.py
--mode pilot-rationale-v3-r1`) remains executable as the comparison baseline
the commit history calls "a comparison, not a re-run" against `mcq_core`'s
kernel.
**Note on CLAUDE.md item 10.** Neither this module nor `mcq_core.py` claims
set-cover-with-bitmask-DP was invented in this project; both are
implementations of a known technique, kept separately because they serve
different, explicitly-dated pipelines.

### `src/rationale_v3/selector.py` — `REFERENCE_OR_REGRESSION_ONLY`

**Role.** Evidence-tier-then-combination-objective distractor selection over
the frozen Prompt-8D rankings — the R1 orchestration layer's own selector,
predating `mcq_core.build_case()`/`select_distractors()`. 1066 lines.
**Called by B1.4?** No.
**Other importers.** `src/extract_and_select_distractors_v3.py` (imports
`PoolPolicy` from it), `src/pipeline/rationale_v3_run.py`,
`tests/test_rationale_v3.py`.
**Tests.** `tests/test_rationale_v3.py`.
**Needed for final batch execution?** No — role fully absorbed by
`mcq_core.py` for the frozen kernel path. Kept as the R1 executable baseline.

---

## 4. `selection.observed_facts` — kept where it is

`mcq_inputs.py` imports:

```python
from selection.observed_facts import DIRECTION_LABEL, observed_edge_set
```

### `src/selection/observed_facts.py` — `FINAL_RUNTIME_CORE`

**Role.** Owns graph-*observation* semantics — pinned graph → corrected
one-hop observation → IN/OUT labelling — as distinguished in its own module
docstring from `rationale_v3`'s evidence/reasoning semantics (observed facts
→ quality → semantic relation → evidence level). 399 lines.

**Called by B1.4?** Yes — `mcq_inputs.py`'s B1.2
(`answer_facts_from_local_kg`) calls `observed_edge_set()` to enumerate an
Answer's complete one-hop edges from an already-loaded KG object, and reads
`DIRECTION_LABEL` to attach `"IN"`/`"OUT"` to each fact.

**Dependency closure of `observed_edge_set()`.** Traced fully:

* Imports only `selection.contracts` (`DIRECTION_IN`, `DIRECTION_OUT`,
  `ObservedFact`, `SCOPE_DIAGNOSTIC`, `SCOPE_PRIMARY`, `sort_observed_facts`)
  — itself stdlib-only (`dataclasses`, `typing`), 474 lines. No import of
  `kg.loader` or `kg.graph_view` anywhere in the file.
* `observed_edge_set()` → `EdgeSetCache.get_or_compute()` → `_compute_edge_set()`,
  which reads `kg.out_neighbor` / `kg.in_neighbor` via duck typing (works for
  both `kg.loader.LocalKG` and the legacy KG dataclass, without importing
  either) — it accepts an **already-loaded** graph object and never opens,
  builds or caches a KG file itself, matching its own module docstring
  ("Reads an already-loaded KG object... never touches the network").
* The `EdgeSetCache` class (identity-keyed on `kg_identity` + `node_index` +
  `use_in` + `fact_schema_version`) exists specifically to fix two documented
  historical defects (its header, EX-4 and EX-12): a legacy cache keyed on
  node index alone that silently returned a wrong-direction result for a
  reused index, and a legacy record that mislabelled an IN edge's subject as
  `"object"`.

**Is keeping the import safer/smaller than copying the body?** Copying
`observed_edge_set()` into `mcq_inputs.py` would require also copying
`EdgeSetCache` (~70 lines, including the identity/lifetime logic that fixes
EX-4), `_uri_for_index`/`_neighbor_map` (duck-typing helpers), the
`DIRECTION_LABEL`/`DIRECTION_CODE_*` constants and their load-bearing
`assert`, **and** `selection.contracts` (`ObservedFact`,
`sort_observed_facts`, the direction constants) as a second, separate
dependency — i.e. copying would not remove a dependency, it would relocate
~150 lines of already-tested cache-correctness logic into an adapter module
whose own docstring says it "must never become" the place evidence/quality
rules live, and would create a second copy of the EX-4 fix that could drift
from the first. **Keeping the import is smaller (net new code: zero) and
safer (one fix, one place) than copying.**

**Other importers.** `src/extract_221_and_select_distractors_ClaudeWeb_v2.py`,
`src/selection/legacy_overlap.py`, `tests/test_selection_lrolesim_handoff.py`
— i.e. it already serves more than one production consumer, which is
additional evidence of a stable, shared contract rather than an
adapter-specific helper.
**Tests.** No dedicated `test_observed_facts.py`; exercised via
`tests/test_selection_lrolesim_handoff.py` (45 tests) and
`tests/test_rationale_selection.py` (77 tests), plus `tests/test_mcq_inputs.py`
(174 tests, B1.2/B1.3 coverage).
**Needed for final batch execution?** Yes, directly.

### `src/selection/contracts.py` — `FINAL_RUNTIME_CORE`

Stdlib-only (`dataclasses`, `typing`). Defines `ObservedFact`,
`sort_observed_facts`, the direction/scope constants that
`observed_facts.py` depends on. Also imported by
`selection/lrolesim_handoff.py`, `selection/legacy_overlap.py`,
`rationale/contracts.py`, `extract_221_and_select_distractors_ClaudeWeb_v2.py`.
Not imported directly by `mcq_inputs.py`, but on the live path transitively
through `observed_facts.py`.

---

## 5. Everything else named in the prompt

### `src/pipeline/rationale_v3_run.py` — `REFERENCE_OR_REGRESSION_ONLY` / `FUTURE_EXTENSION_POINT`

**Role.** Orchestration for the R1 pipeline: reads the frozen Prompt-8D
handoff, drives `rationale_v3.selector`/`setcover` end to end, and owns
`build_semantic_index_from_pinned_kg()` — the one place in the repository
permitted to open the 1.2 GB pinned pickle to build the semantic-index cache.
2197 lines.
**Called by B1.4?** No — not imported by `mcq_inputs.py` or `mcq_core.py`.
**Not on the live path for selection**, since `mcq_core`/`mcq_inputs` replaced
the R1 selection orchestration. **Is still the designated tool for rebuilding
the semantic-index cache**, which `docs/plans/PHASE_B2_ALBERT_PRECONDITIONS.md`
step 8 identifies as a hard prerequisite before Albert Einstein (or any
Answer outside the nine-Answer pilot) can run — so its selection-orchestration
role is `REFERENCE_OR_REGRESSION_ONLY` and its semantic-index-build role is a
`FUTURE_EXTENSION_POINT` the B2 chain will actually need to call.
**Other importers.** `src/extract_and_select_distractors_v3.py`.
**Tests.** `tests/test_rationale_v3.py`.

### `src/extract_and_select_distractors_v3.py` — `REFERENCE_OR_REGRESSION_ONLY` / `FUTURE_EXTENSION_POINT`

**Role.** Argument parsing and mode dispatch only, for two modes:
`pilot-rationale-v3-r1` (the R1 selection pipeline, superseded on the live
path by `mcq_core`) and `build-semantic-index` (still needed for B2). 164
lines.
**Called by B1.4?** No.
**Needed for final batch execution?** Its `build-semantic-index` mode is a
`FUTURE_EXTENSION_POINT` on the B2 dependency chain; its
`pilot-rationale-v3-r1` mode is `REFERENCE_OR_REGRESSION_ONLY`, kept so the R1
pipeline stays a re-runnable, byte-comparable baseline against `mcq_core`.

### `src/rationale/` (the older, pre-`rationale_v3` package) — `LEGACY_NOT_ON_FINAL_RUNTIME_PATH`

`src/rationale/__init__.py`, `contracts.py`, `contrasts.py`, `selector.py`,
`setcover.py` — the Prompt-8E rationale layer, predating `rationale_v3`.
**Imported by anything on the live B1.4 path, or by `rationale_v3` itself?**
No. `grep` for `from rationale import` / `from rationale\.` finds only
`src/pipeline/rationale_selection_run.py` (the Prompt-8E orchestration
script) and its own test, `tests/test_rationale_selection.py` (77 tests).
`rationale_v3/*.py` does not import the `rationale` package at all — the two
are parallel, independently-versioned packages, not a chain (`rationale_v3`
did not build on top of `rationale`; it replaced it, per commit `1b81f9a`:
*"Prompt 8E is not touched: `src/rationale/*`... keep their pinned hashes and
stay an executable frozen baseline, so the V3-versus-8E comparison is a
comparison and not a re-run"*).
**Needed for final batch execution?** No.
**Reasonable future extension point?** No — fully superseded by
`rationale_v3` for any forward work; kept only as the Prompt-8E frozen
baseline for historical comparison.

### `src/selection/legacy_overlap.py` — `LEGACY_NOT_ON_FINAL_RUNTIME_PATH`

**Role.** The pre-LRoleSim Overlap-measure ranking, 608 lines.
**Does `mcq_inputs.py` import it?** No. `grep -n legacy_overlap
src/mcq_inputs.py` finds exactly one hit: a **docstring sentence** (invariant
8) naming it as the thing that must never populate `Candidate.rank`/`.score`.
There is no `import` statement. Invariant 8 is enforced by rejecting ranker/
measure name tokens (`LEGACY_RANKER_TOKENS = ("overlap",)`) plus the
contrapositive of invariant 5 (the pinned LRoleSim execution-path fields must
be present) — a name-based and field-based guard, not a functional
dependency on the module.
**Does `rationale_v3` import it?** No.
**Other importers.** `src/pipeline/rationale_selection_run.py`,
`src/pipeline/rationale_v3_run.py` (diagnostic/comparison use, not the
scientific decision), `src/extract_221_and_select_distractors_ClaudeWeb_v2.py`,
`tests/test_selection_lrolesim_handoff.py`, `tests/test_mcq_inputs.py`
(regression coverage that invariant 8 actually rejects it).
**Needed for final batch execution?** No — its presence in the repository is
precisely so invariant 8 has something concrete to reject; CLAUDE.md item 3
and invariant 8 both forbid it from ever driving `Candidate.rank`/`.score`.

### `src/lrolesim/adapter.py` — `FINAL_RUNTIME_CORE` (upstream of `mcq_inputs.py`, not imported by it)

Not imported by `mcq_inputs.py`/`mcq_core.py` directly (B1.1 reads frozen,
already-ranked records; it does not re-run LRoleSim). It is, however, the
sole live entry point that produces those rankings for any Answer not yet in
the frozen record set — `_KERNEL_MODULE_NAME = "MCQ_lrolesim_ClaudeWeb_v2"`,
loaded via `importlib.util.spec_from_file_location`, never
`MCQ_lrolesim.py` (see `docs/audits/MCQ_LROLESIM_SOURCE_PIN_AUDIT.md` §5).
Required for any future Answer (including Albert Einstein, B2 step 5).

### `src/lrolesim/__init__.py` — `FINAL_RUNTIME_CORE` (package marker, no logic).

### `src/MCQ_lrolesim.py` — `REFERENCE_OR_REGRESSION_ONLY`

Not on the live path (see the LRoleSim source-pin audit, §5–6: it is an
untracked reference archive of the pre-Journal-2 author source; the executed
kernel has always been `MCQ_lrolesim_ClaudeWeb_v2.py`). Kept as a qualitative
"Journal 1 stays immutable" check, per `CLAUDE.md`'s File-safety rule and
`tests/test_lrolesim_adapter.py`'s `test_journal1_archive_has_no_fixed_iteration_api`.

### `src/MCQ_lrolesim_ClaudeWeb_v2.py` — `FINAL_RUNTIME_CORE`

The actual executed LRoleSim kernel, loaded by `lrolesim/adapter.py`. Hash
`b7c3678e…`, verified unchanged throughout this audit.

### `src/kg/loader.py`, `src/kg/graph_view.py` — `FINAL_RUNTIME_CORE` (upstream of `mcq_inputs.py`, not imported by it)

Not imported by `mcq_inputs.py` (B1.2 receives an already-loaded KG object as
an argument, per its own docstring: "this module never opens, builds,
repairs or caches a local-KG file"). They are, however, the only code
permitted to load/build the pinned KG and the M1 graph respectively, and are
therefore required upstream of any call into `mcq_inputs.build_and_select()`
for an Answer whose case is not yet frozen. Both hashes independently
verified unchanged in this audit's control group (§2 of the LRoleSim audit).

### `src/pipeline/graph_lrolesim_run.py`, `src/pipeline/candidate_order.py` — `FINAL_RUNTIME_CORE` (upstream, not imported by `mcq_inputs.py`)

Orchestration for the graph-admission stage and the LRoleSim ranking run
(Prompt 8C). Not imported by `mcq_inputs.py`. Required upstream to produce a
ranked candidate roster for any new Answer — B2 dependency-chain step 4–5.

### `src/pipeline/rationale_selection_run.py` — `LEGACY_NOT_ON_FINAL_RUNTIME_PATH`

The Prompt-8E orchestration script over the older `rationale` package.
Not imported by `mcq_inputs.py`, `mcq_core.py`, or `rationale_v3`. Kept as
the Prompt-8E frozen executable baseline.

### `src/classes/*.py` (`policy.py`, `member_mapper.py`, `local_candidate_profile.py`, `mapping_run.py`, `page_cache.py`, `sparql_client.py`) — `FINAL_RUNTIME_CORE` (upstream, not imported by `mcq_inputs.py`)

Not imported by `mcq_inputs.py`. Owns class-member SPARQL retrieval and
local-KG mapping (Week-1 stage) — required upstream, B2 dependency-chain
steps 2–3, for any Answer whose class-member roster is not already cached.

### `src/category_extractor_ClaudeWeb_v4.py` — `FINAL_RUNTIME_CORE` (upstream, not imported by `mcq_inputs.py`)

The current class-selection reference (`select_class(...)`, mode
`recommended`). Not imported by `mcq_inputs.py`. Required upstream for step 1
of the B2 chain (though, per `ANSWER_LEAKAGE_DESIGN_AUDIT.md`, its class-level
leak detector is weaker than the fact-level rule and must not be imported
*into* `mcq_core.py` — a separate, already-recorded constraint on how it may
be used, not on whether it stays in the architecture).

---

## 6. Decision: `KEEP_CURRENT_MODULAR_DEPENDENCIES`

No evidence in this audit disproves the default. Every dependency
`mcq_inputs.py` actually imports has a single, traceable owner and an
existing test contract:

| Import | Owner module | Tests |
|---|---|---|
| `assess_fact_quality` | `rationale_v3.quality` | `tests/test_rationale_v3.py` (85) |
| `normalize_uri` | `rationale_v3.semantic_relations` | `tests/test_rationale_v3.py` |
| `RationaleProposition` | `rationale_v3.contracts` | `tests/test_rationale_v3.py` |
| `classify_fact_against_candidate` | `rationale_v3.evidence` | `tests/test_rationale_v3.py` |
| `DIRECTION_LABEL`, `observed_edge_set` | `selection.observed_facts` | `tests/test_selection_lrolesim_handoff.py` (45), `tests/test_rationale_selection.py` (77), `tests/test_mcq_inputs.py` (174) |

Copying any of the five into `mcq_inputs.py` would either duplicate a
scientific rule that already has its own policy/tests/provenance
(`rationale_v3`) or duplicate a cache-correctness fix for two documented
historical defects (`observed_facts.EdgeSetCache`, EX-4/EX-12) — in both
cases creating a second copy that could drift from the first, which is
exactly the failure mode `mcq_inputs.py`'s own docstring says the module
"must never become." Line count is not the deciding factor (CLAUDE.md: "line
count alone is NOT a reason to copy a scientific helper") — ownership and
test coverage are, and both are present for every kept dependency.

`rationale_v3.setcover` and `rationale_v3.selector` are the one place this
audit found duplication in spirit — an R1 selection algorithm that
`mcq_core.py` has since reimplemented as its own frozen kernel — but this is
the opposite problem (two independent implementations of a known technique
serving two different, explicitly-dated pipelines, neither claiming to be
novel per CLAUDE.md item 10) and does not argue for consolidating
`mcq_inputs.py`'s dependencies; it argues for leaving the R1 pipeline alone as
a comparison baseline, which is already the recorded intent.

**`CONSOLIDATION_REQUIRED_BEFORE_B2` is not supported by this audit's
findings.**
