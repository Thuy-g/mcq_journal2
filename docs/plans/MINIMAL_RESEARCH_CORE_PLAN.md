# Minimal research core — written plan

**Date** 2026-08-06 · **Branch** `journal2-spec-freeze-20260806`
**Status** PLAN ONLY. **No implementation begins in this task.**
**Authoritative terminology** `docs/context/EVIDENCE_TAXONOMY_V1.md`

---

## 0. Why a minimal core

Prompt 8F-R1 is a correct, well-tested, richly provenanced implementation. It is
also **4,598 non-comment code lines across 9 production files plus 1 test file**.
That is too large to remain the only implementation a single human author must
read, explain in a viva, and defend to a reviewer.

The problem is not quality. It is that the *scientific content* of the method —
class-constrained retrieval, LRoleSim ranking, evidence classification, exact
minimum-cardinality rationale selection — is distributed across nine files
alongside a large amount of framework machinery that no paper claim depends on.

**The scientific priority is clarity, correctness and author comprehensibility,
not software-framework completeness.**

The minimal core is not a rewrite for its own sake. It is a deliberate
re-scoping to *exactly the behaviour that supports the paper's main claim*, with
everything else documented and recoverable rather than deleted.

### Relationship to the existing implementations

| Artefact | Role | Development status |
|---|---|---|
| **Prompt 8E** (`src/rationale/`, `src/pipeline/rationale_selection_run.py`) | the **minimal historical algorithmic baseline** — the simplest correct version of the selection algorithm | **frozen.** Kept for regression comparison and to show the method's algorithmic core existed before the evidence taxonomy was elaborated. Not developed further. |
| **Prompt 8F-R1** (`src/rationale_v3/`, `src/pipeline/rationale_v3_run.py`) | the **feature-rich reference implementation and audit oracle** — the ground truth any future implementation must agree with | **frozen.** Kept to answer "what does the full method do on case X?", to recover deferred features, and to validate the minimal core. Not developed further. |
| **Minimal research core** (planned) | the **only forward implementation** | begins **after this plan is approved**, and not before. |

**8E and R1 must not be developed as two competing production pipelines.**
Neither receives new features. Once the minimal core exists and passes its
regression tests against both, it is the single line of development; 8E and R1
become immutable archives in the sense of `CLAUDE.md` §"File safety".

---

## 1. Essential behaviour — what the minimal core must preserve

Each item below is required because a specific paper claim or scientific
boundary depends on it.

| # | Behaviour | Why it cannot be dropped |
|---:|---|---|
| 1 | **Consume frozen LRoleSim candidate ranks and scores** from the Prompt-8D handoff; assert `measure`, `lrolesim_beta`, `iterations`, `iteration_mode`, `ranker_name` at run time; never recompute similarity | RQ1 depends on the ranking being the published LRoleSim, unmodified |
| 2 | **LRoleSim remains a structural plausibility ranker only** | `CLAUDE.md` §2, §4: Journal 2 applies LRoleSim; it does not extend it, and LRoleSim does not generate rationales |
| 3 | **`L0_ABSENCE_ONLY_OBSERVED` as a diagnostic level** | yield reporting (RQ4) and failure analysis (RQ5); must exist and must never enter a main-corpus rationale |
| 4 | **`L1_POSITIVE_ALTERNATIVE_OBSERVED`** as defined in `EVIDENCE_TAXONOMY_V1.md` §3 | the evidence level every reported rationale rests on (RQ2) |
| 5 | **Exact distractor-combination search** over the observed class sizes (pilot: 11–50 candidates → C(n,3) ≤ 18,424) | the paper claims exactness for the reported experiments; a heuristic would void it |
| 6 | **Exact minimum-cardinality bitmask set cover** over the k distractors | RQ3, the compactness half of the plausibility/compactness trade-off |
| 7 | **Hard rejection of URL / media / raw-template fields** | measured effect: it is what removes `dbp:url` → Web Archive from Eisaku Satō (`quality_off` re-selects it) |
| 8 | **Deterministic Answer-label leakage detection, including Carbon–Carbonado** | a rationale that leaks the Answer string invalidates the item; the Carbon case is a named regression |
| 9 | **Correct IN/OUT handling**, never merged | `(p, IN)` and `(p, OUT)` are different relations; 6 of 9 pilot rationale facts are IN |
| 10 | **Verbalizability registry** (template id, tier, verbalizable flag) | decides main- versus diagnostic-corpus eligibility; it is the sole blocker on Eisaku Satō |
| 11 | **Snapshot-groundedness and snapshot-local uniqueness verification** | every emitted fact must be traceable to the pinned snapshot; local anonymity must be computed and labelled as local |
| 12 | **Compact deterministic JSONL output** with provenance (input hashes, graph fingerprint, policy, per-distractor levels) | `CLAUDE.md` §"Network and external services"; reproduction protocol |
| 13 | **Regression tests against selected Prompt-8E and R1 cases** | the only proof the re-scoping preserved behaviour |

### Non-negotiable invariants the core must enforce

* `(d, p, o) ∉ K` never implies `¬p(d, o)`. Absence is never written as falsity.
* `NOT_COVERED` is tested before `L0`/`L1`/`L2`.
* No annotation may move a fact between levels.
* Deterministic sorting and tie-breaking everywhere; two runs byte-identical.
* No import-time network calls, model downloads, cache creation or ranking.
* Unit tests require no Internet.

---

## 2. Deferred from the minimal core

Deferred means: **documented here, recoverable from R1, not implemented in the
core** unless real batch evidence proves it is needed.

| Deferred | Evidence for deferring |
|---|---|
| **Active L2 rules** | 0 L2 incidences and 0 `EvidenceProof` records in the pilot; no trustworthy offline source of functionality/disjointness/negative assertions exists for DBpedia infobox properties |
| **General `EvidenceProof` execution** | nothing to execute while L2 is deferred |
| **`SCOPED_EMPIRICAL` annotation in primary selection** | 39 annotated incidences existed; **0** reached a selected rationale; it changed no selection |
| **Semantic closure in primary selection** | the bounded closure found `EXACT_EQUAL 313` and `UNRELATED_OR_UNKNOWN 69,144`, with **zero** `CANONICALLY_EQUIVALENT`, **zero** `CANDIDATE_UNDER_CLAIM` and **zero** `CLAIM_UNDER_CANDIDATE`. It changed **no evidence level** in the pilot. Exact object equality is retained (§3); the traversal is not |
| **`POOL_EXACT`** | all eight pilot Answers ran `FULL_EXACT`; the largest class needed 18,424 combinations. Add only when a real class exceeds the exact budget |
| **Default multi-arm ablation execution** | the three R1 ablation arms answered their question once; re-running them on every batch is measurement, not method. Keep as a separately invoked mode if needed |
| **Many separate audit writers** | R1 already collapsed 11 writers to 5; the core should emit **two** files (selected MCQs, run manifest) plus one optional evidence dump |
| **WordNet, spaCy, embeddings, LLM calls** | prohibited; see §3 |
| **Bipartite Graph construction** | out of scope; see §5 |
| **Natural-language verbalization** | the registry records *whether* a fact is verbalizable (essential, item 10); *producing* the sentence is a separate module |

Recovery commands, all valid at commit `1b81f9a` and `cbb9706`:

```bash
git show 1b81f9a:src/rationale_v3/selector.py            # pool ablation, PoolAblationRow
git show 1b81f9a:src/pipeline/rationale_v3_run.py        # bipartite emission, 16 writers
git show cbb9706:src/rationale_v3/semantic_relations.py  # bounded semantic closure
git show cbb9706:src/rationale_v3/evidence.py            # scoped empirical rules, L2 scaffolding
```

---

## 3. Identity and synonym scope — documented, not implemented

The minimal identity policy for future code. **Do not implement in this task.**

### Permitted identity operations

| # | Operation | Notes |
|---:|---|---|
| 1 | **Exact URI equality** | the primary test; 313 of 313 `NOT_COVERED` incidences in the pilot were decided by it alone |
| 2 | **Canonical DBpedia redirect equality** | offline only, from the frozen Prompt-8B class-member retrieval (`record_type=redirect` rows with a resolved `target_uri`); 5 equivalence entries exist in the pilot index |
| 3 | **Trusted offline `owl:sameAs` equality** *if already available* | no live traversal, no new download; broad `owl:sameAs` traversal is explicitly deferred in `01_project_goal.md` |
| 4 | **Normalized display-label equality** | Unicode NFC, case-folded, whitespace-collapsed; used to catch the same entity surfacing under two labels |
| 5 | **Duplicate-choice rejection after canonicalization** | after 1–4, no two of {Answer, distractor₁, distractor₂, distractor₃} may be the same entity |

### Explicitly excluded

**Do not add WordNet, spaCy similarity, sentence embeddings, or any
general lexical-synonym expansion.** These are excluded on scientific grounds,
not merely for simplicity: each would introduce an unverifiable, non-deterministic
equivalence judgement into a pipeline whose central claim is that every emitted
statement is grounded in a pinned snapshot.

### Three notions that must never be conflated

| Notion | Question it answers | Status in the core |
|---|---|---|
| **Entity identity / equivalence** | *Are these two IRIs the same thing?* | **in scope.** Decidable from the snapshot: URI equality, redirects, trusted `owl:sameAs`. Truth-preserving — substituting one for the other cannot change a fact's truth value. |
| **Lexical synonymy** | *Are these two words interchangeable in language?* | **out of scope.** A property of a lexicon, not of the KG. "Author" and "writer" may be synonyms while `dbo:author` and `dbo:writer` are different predicates with different extensions. Substitution is **not** truth-preserving. |
| **Semantic relatedness** | *Are these two things associated?* | **out of scope for identity.** Graded, directionless, and already covered by LRoleSim as a *plausibility* signal. It must never be used to decide whether a candidate supports a proposition — that is precisely how an unverifiable equivalence would enter the evidence layer. |

The failure mode this separation prevents: treating "Tokyo" and "Japan" as
related (true) and therefore as equivalent (false), which would silently convert
a genuine `L1` into a spurious `NOT_COVERED`, or worse, the reverse. The R1
`granularity_risk` axis exists for exactly this hazard and its **direction**
matters — see `EVIDENCE_TAXONOMY_V1.md` §1 and §5.

---

## 4. Size, readability and structure targets

### Target for the future implementation — not for this task

| Constraint | Target |
|---|---|
| production Python files | **at most 2** |
| main test files | **at most 1** |
| non-comment code lines, total | **no more than approximately 1,500** |

Comments and docstrings **do not count** against the 1,500-line target.

### Current baseline, measured 2026-08-06

Measured with `tools/count_loc.py`, which reports the four categories separately.

| Scope | Files | Physical | Blank | Comment/docstring | **Code** |
|---|---:|---:|---:|---:|---:|
| R1 production | 9 | 6,551 | 839 | 2,004 | **3,708** |
| R1 test | 1 | 1,215 | 179 | 146 | **890** |
| **R1 total** | **10** | **7,766** | **1,018** | **2,150** | **4,598** |

Per production file:

| File | Physical | Blank | Comment | Code |
|---|---:|---:|---:|---:|
| `src/pipeline/rationale_v3_run.py` | 2,197 | 231 | 774 | 1,192 |
| `src/rationale_v3/selector.py` | 1,066 | 144 | 251 | 671 |
| `src/rationale_v3/evidence.py` | 790 | 90 | 202 | 498 |
| `src/rationale_v3/semantic_relations.py` | 660 | 94 | 189 | 377 |
| `src/rationale_v3/contracts.py` | 674 | 122 | 235 | 317 |
| `src/rationale_v3/quality.py` | 485 | 70 | 123 | 292 |
| `src/rationale_v3/setcover.py` | 470 | 64 | 129 | 277 |
| `src/extract_and_select_distractors_v3.py` | 164 | 21 | 63 | 80 |
| `src/rationale_v3/__init__.py` | 45 | 3 | 38 | 4 |

**Required reduction: 4,598 → ~1,500 code lines, about 67 %.**

### Where the reduction comes from — a budget, not a hope

R1's own report identified why its 8.4 % reduction stalled: roughly 40 % of
surviving code lines are `as_record()` methods and CSV field lists publishing
provenance, and it declined to cut output fields or tests. The minimal core
reaches 1,500 by **removing whole features**, not by compressing code.

| Source of reduction | Est. code lines removed | Basis |
|---|---:|---|
| `semantic_relations.py` deleted entirely (exact equality retained inline) | ~377 | changed no evidence level in the pilot |
| scoped-empirical rule machinery, L2 scaffolding, `EvidenceProof` in `evidence.py` | ~250 | 0 selections affected, 0 L2 incidences |
| ablation-arm orchestration, comparison writers, remaining audit writers in `rationale_v3_run.py` | ~700 | measurement, not method |
| output-writer consolidation: 5 files → 2 (+1 optional) | ~250 | field lists shrink with the schema |
| `POOL_EXACT` pool-policy machinery | ~120 | unused at pilot class sizes |
| `contracts.py` vocabulary that survives only to serve deferred features | ~180 | follows the features |
| test file re-scoped to the surviving behaviour | ~400 | fewer features to test; **regression cases are kept, not cut** |
| **Total estimated** | **~2,280** | leaves ≈ 2,300 — still above target |

The residual gap to 1,500 must come from **structural** consolidation: one
evidence/selection module and one pipeline/IO module, with a single record
schema serialized once rather than an `as_record()` per dataclass. If, when the
work is done, 1,500 is not reached, **report the actual number and the reason
rather than deleting tests, output fields or comments to hit it** — the R1
report's handling of its own miss is the correct precedent.

### Proposed structure

```
src/mcq_core.py       evidence classification, exact set cover, combination
                      search, quality filters, leakage, verbalizability registry
src/mcq_run.py        input loading, provenance, orchestration, JSONL output, CLI
tests/test_mcq_core.py
```

Two files, one test file. `src/mcq_core.py` must be readable top-to-bottom
without reference to the other.

### Comment requirements — mandatory, and not counted against the budget

**Do not reduce line count by deleting explanatory comments.** The human author
must be able to read the code and explain it. The future implementation must
carry detailed comments covering, at minimum:

1. **the mathematical objective** — every key, its direction, why it sits where
   it does in the ordering;
2. **evidence semantics** — what `NOT_COVERED` / `L0` / `L1` / `L2` mean, with a
   pointer to `EVIDENCE_TAXONOMY_V1.md`;
3. **mask construction** — which bit tracks which distractor, and why a fact's
   mask is policy-dependent;
4. **the exact set-cover DP** — why distinct masks suffice, why unreachable
   entries hold `k+1`, why the result is exact and not a greedy approximation;
5. **IN/OUT direction** — why the two directions are never merged;
6. **deterministic tie-breaking** — every tie-break, and what happens if it is
   removed (see `RANK_SUM_EFFECT_AUDIT.md`);
7. **Open-World limitations** — at every point where a level is assigned or a
   rationale is emitted.

Report line counts in all four categories separately — **physical, blank,
comment/docstring, executable code** — using `tools/count_loc.py`. Only the
last is measured against 1,500.

---

## 5. Bipartite Graph — reminder, not a task

**Do not implement Bipartite Graph generation in the minimal core, and not in
this task.**

The LRoleSim matching bipartite graph and the MCQ choice–evidence bipartite
graph are **different objects** (`CLAUDE.md` §6). Any future Bipartite Graph or
fact-selection task **must first inspect the original user-written files**,
which contain the author's own prior formulation and must not be reinvented:

```
/home/thuy/projects/mcq_journal2/src/mcq_generation.py                        (9,482 B)
/home/thuy/projects/mcq_journal2/src/build_bipartite_and_draw_ExtendedVersion.py (16,120 B)
/home/thuy/projects/mcq_journal2/src/all_in_one.py                            (17,249 B)
```

All three are present on disk and untracked as of 2026-08-06. They also exist in
`MyOriginalCode_MCQ2026_Backup.zip`, located at
`/mnt/d/MSI_MCQ_2026/Code Journal2_Backup/MyOriginalCode_MCQ2026_Backup.zip`.

R1 previously emitted `bipartite_fact_candidates.jsonl` via
`write_bipartite_fact_candidates`; that was removed in the R1 simplification and
is recoverable from `git show 1b81f9a:src/pipeline/rationale_v3_run.py`.

**Likely future implementation boundary: one focused source file plus one test
file — not another multi-module framework.**

---

## 6. Sequencing and acceptance

### Order of work — after this plan is approved

1. **Approve this plan.** No code before approval.
2. Write `src/mcq_core.py` against `EVIDENCE_TAXONOMY_V1.md`, with the mandatory
   comments.
3. Write `tests/test_mcq_core.py`, including:
   * exact set cover versus brute force on randomized cases with a fixed seed;
   * the Carbon–Carbonado leakage regression;
   * `dbp:url` / Web Archive rejection;
   * IN and OUT never merging;
   * the two-fact counterexample yielding \|R*\| = 2 (Eisaku Satō);
   * absence never relabelled as contrast, and vice versa.
4. Write `src/mcq_run.py`; assert the frozen LRoleSim parameters; emit
   deterministic JSONL.
5. **Regression gate:** reproduce the eight R1 pilot selections exactly —
   policy, distractor triple, rationale set — and the selected Prompt-8E cases.
   `scripts/spec_freeze_audit.py` already demonstrates this gate is achievable
   from the frozen records alone.
6. Only then run the 100-Answer batch.
7. Optimize performance only after correctness and yield measurements exist.

### Acceptance criteria

| # | Criterion |
|---:|---|
| 1 | ≤ 2 production files, ≤ 1 main test file |
| 2 | ≈ 1,500 non-comment code lines, with all four line categories reported separately |
| 3 | all eight R1 pilot selections reproduced exactly |
| 4 | selected Prompt-8E cases reproduced exactly |
| 5 | two consecutive runs byte-identical (excluding clock/Git fields) |
| 6 | zero network attempts, asserted by a guard |
| 7 | no forbidden imports (WordNet, spaCy, embeddings, LLM clients) on the run path |
| 8 | every mandatory comment topic from §4 present |
| 9 | terminology conforms to `EVIDENCE_TAXONOMY_V1.md`; the string `POSITIVE_VALUE_CONTRAST` does not appear |

### Open questions to resolve before implementation

1. **Rationale ranking key width.** R1 uses 14 fields. `RANK_SUM_EFFECT_AUDIT.md`
   shows 7 of 8 Answers never reach even key 4. A batch-scale measurement of
   which of the 14 fields are ever *reached* should precede any decision to trim
   them — the pilot is too small to justify removing any of them now.
2. **`rank_sum`.** Keep at objective key 5. See
   `RANK_SUM_EFFECT_AUDIT.md` §4 for the reasoning and the re-audit condition.
3. **`direct_identifier_flag`.** Currently the 13th of 14 ranking fields and not
   a filter. Whether it should ever become a filter needs human-evaluation
   evidence the pilot does not provide (`PILOT_DIRECT_IDENTIFIER_AUDIT.md` §3).
4. **Verbalization templates.** Eisaku Satō is the only pilot item blocked from
   the main corpus, solely by a missing `dbp:before` IN template. Whether to
   extend the registry or accept the loss is a scope decision for the batch.

---

## 7. What this plan does not authorize

No implementation begins in this task. Specifically not authorized here:
running the 100-Answer batch; implementing the minimal core; modifying R1
selection behaviour; implementing L2; adding WordNet or spaCy; adding embeddings
or LLM calls; accessing live DBpedia or Wikidata; implementing verbalization;
implementing Bipartite Graph generation; creating a general-purpose framework.
