# Phase-B Input Contract — what `select_distractors()` requires, field by field

**Status** FROZEN for Phase B, 2026-08-10
**Kernel under contract** `src/mcq_core.py` @ `20234996e70c8e815e74534a1688958a6040a099`
(`sha256 ba4b378584ef1f067f81ab8ffcf2c82137293acac1915e58770f2b1b097abf63`)
**Terminology authority** `docs/context/EVIDENCE_TAXONOMY_V1.md`
**Companion audit** `docs/audits/ALBERT_EINSTEIN_PHASE_B_READINESS.md`

This file is the single authority on **what an `AnswerCase` is and where each of
its fields must come from**. It was reconstructed from the source file actually
on disk, not from chat memory, report prose or identifier names.

---

## 0. The one sentence that governs everything below

`src/mcq_core.py` **does not derive a single one of these fields from a raw
Answer URI.**

The module's own docstring says so, and the code confirms it: `mcq_core.py`
imports only `__future__`, `dataclasses`, `itertools`, `math` and `typing`. It
never opens a triple store, never tests object equality, never consults a
semantic index, never detects a URL or media predicate, never detects lexical
leakage and never looks up a verbalization template. It receives `AnswerFact`
records whose `levels` tuple is **already filled in** and whose `quality` record
**already carries** `eligible`, `verbalizable`, `pedagogical_tier` and the rest,
and it consumes them as opaque, already-computed attributes.

Everything in §2 and §3 below is therefore an **upstream obligation**. Phase B is
the work of discharging it for a new Answer.

---

## 1. The entry point

```python
select_distractors(
    case: AnswerCase,
    pool_policy: PoolPolicy = DEFAULT_POOL_POLICY,
    force_pool: bool = False,
) -> Selection | None
```

`AnswerCase` must be built through `build_case(answer_uri, display_label,
candidates, facts)`, never by calling the dataclass constructor directly.
`build_case()` re-sorts candidates into the canonical order `(rank, uri)`,
permutes every fact's per-candidate tuple the same way, and derives
`eligible_fact_indices`. Two callers holding the same information in different
orders therefore produce byte-identical output. Constructing `AnswerCase`
directly bypasses that canonicalisation and is a contract violation.

---

## 2. `AnswerCase` — the five top-level fields

| # | Field | Type / shape | Scientific meaning | Produced by | Available for the pilot? | Access needed |
|---:|---|---|---|---|---|---|
| 1 | `answer_uri` | `str`, unbracketed | The Answer entity `A`. Identity only; the kernel never dereferences it. | the caller / batch input list | yes | none |
| 2 | `display_label` | `str` | Human-readable Answer label, carried onto the record. Must preserve parentheses, Roman numerals and diacritics (see §4). | class-selection stage or `quality.display_label(uri)` | yes | none |
| 3 | `candidates` | `tuple[Candidate, ...]` | **The complete ranked candidate pool** of the selected class. Not a top-k slice: the anonymity denominator and `original_candidate_count` both read it. | class selection → member retrieval → local mapping → graph → LRoleSim | yes, 8 Answers | see §3.1 |
| 4 | `facts` | `tuple[AnswerFact, ...]` | Every observed Answer fact, eligible **and** ineligible. Ineligible facts are kept so indices stay stable and a rejected fact remains inspectable. | one-hop extraction + evidence classification + quality assessment | yes, 8 Answers | see §3.2–§3.4 |
| 5 | `eligible_fact_indices` | `tuple[int, ...]` | **Derived by `build_case()`.** Never supplied by the caller. | `build_case()` | derived | none |

---

## 3. The three record types

### 3.1 `Candidate` — the frozen LRoleSim ranking

```python
@dataclass(frozen=True)
class Candidate:
    rank: int      # 1-based, contiguous, ascending by structural plausibility
    score: float   # the frozen LRoleSim score
    uri: str       # canonical candidate URI, unbracketed
```

| Field | Meaning | Upstream stage | Frozen source for the pilot | Access class |
|---|---|---|---|---|
| `rank` | Position in the **frozen** LRoleSim ranking. Objective key 5 sums it; `build_case()` sorts by it; the bounded pool's `TOP` component is literally the first *m* positions. | LRoleSim run (Prompt 8D) | `candidate_ranking_handoff.jsonl` → `ranked_candidates[].rank` | **LRoleSim** |
| `score` | The frozen LRoleSim score. Objective keys 1 and 2 maximise its sum and its minimum with full cardinal precision. | LRoleSim run (Prompt 8D) | same file → `ranked_candidates[].score` | **LRoleSim** |
| `uri` | `ranked_candidates[].canonical_candidate_uri`. The final deterministic tie-break (objective key 6). | local mapping + graph admission | same file | local KG |

**Hard constraints, asserted upstream and re-asserted here.**

* Ranks must be contiguous from 1. `validate_prompt8d_contract()` enforces it.
* The execution path is pinned: `ranker_name = lrolesim_m1_fixed_k3`,
  `measure = lrolesim_ed`, `lrolesim_beta = 0.2`, `iterations = 3`,
  `iteration_mode = fixed`.
* **No similarity may be recomputed in Phase B.** Journal 2 *applies* LRoleSim
  as a structural plausibility ranker; it does not extend it, and LRoleSim
  produces no rationale.
* **A legacy Overlap-based ranking is not a substitute.**
  `src/selection/legacy_overlap.py` exists and is a protected frozen source; it
  must never be used to populate `rank` or `score`. Doing so would silently
  replace the paper's ranker with a different measure while keeping the same
  field names.

### 3.2 `FactQuality` — the eleven already-computed per-fact attributes

```python
@dataclass(frozen=True)
class FactQuality:
    predicate_uri: str
    direction: str            # "IN" or "OUT"
    counterpart_uri: str
    display_label: str
    eligible: bool
    soft_leak: bool
    verbalizable: bool
    pedagogical_tier: int
    label_length: int
    token_count: int
    template_id: str
```

`(predicate_uri, direction, counterpart_uri)` is the **canonical fact identity**.
`(predicate_uri, direction)` is `κ`, the predicate-direction key.

| Field | Meaning and role in the objective | Upstream producer | Access class |
|---|---|---|---|
| `predicate_uri` | The infobox property. Identity component; nothing is keyed on it alone. | one-hop extraction from the pinned local KG | local KG |
| `direction` | `"OUT"` (Answer is subject) or `"IN"` (Answer is object). **Part of the identity, deliberately.** `dbp:influences` IN and OUT are two different relations with different extensions and different verbalizations, so they are never merged, never share a dictionary key and never counted as one fact. Six of the nine R1 pilot rationale facts are IN. | one-hop extraction | local KG |
| `counterpart_uri` | Object of an OUT fact, **subject** of an IN fact. | one-hop extraction | local KG |
| `display_label` | The label a learner would see. **Must preserve parentheses, Roman numerals, digits, diacritics and case** — `Iron(II) chloride` and `Iron(III) chloride` must stay two distinct strings. Feeds objective key 10 via `label_length`. | `rationale_v3.quality.display_label()` | none |
| `eligible` | **HARD FILTER**, decided upstream: raw layout slots, external-URL and media objects, machine identifiers, and Answer-label leakage. An ineligible fact is removed from every policy and every rationale; it is never a soft penalty, and Phase A never re-derives it. | `rationale_v3.quality.assess_fact_quality()` — `predicate_ok and object_ok and not hard_leak` | none (policy file only) |
| `soft_leak` | Objective key 7: fewer soft Answer-label echoes. Ordering only; removes nothing. | `detect_answer_leakage()` | none |
| `verbalizable` | Objective key 9. True iff a template is registered for `(predicate_uri, direction)`. Deliberately **not** part of `eligible`: an unverbalizable fact stays available for diagnostics and is only barred from the main corpus. | template registry in `predicate_policy.json` | none |
| `pedagogical_tier` | Objective key 8, lower is better; default 3. An ordering aid, never a truth claim, and it never changes an evidence level. | `predicate_policy.json` → `pedagogical_tier` | none |
| `label_length` | Objective key 10: `len(display_label)`. | derived | none |
| `token_count` | Objective key 11: `len(leakage_tokens(counterpart_uri, minimum_length=1))`. | derived | none |
| `template_id` | Published on the record; `VERBALIZABLE_UNKNOWN` when no template exists. Phase B stops before generating any sentence. | template registry | none |

### 3.3 `AnswerFact` — the three per-(fact, candidate) axes

```python
@dataclass(frozen=True)
class AnswerFact:
    quality: FactQuality
    levels: tuple[str, ...]              # aligned to AnswerCase.candidates
    exclusion_bases: tuple[str, ...]     # same alignment
    granularity_risks: tuple[str, ...]   # same alignment
```

All three tuples **must have length `len(candidates)`** and be aligned to the
caller's candidate order; `build_case()` permutes them into canonical order.

| Axis | Admissible values | Meaning | Upstream producer | Access class |
|---|---|---|---|---|
| `levels[i]` | `NOT_COVERED` / `L0` / `L1` / `L2` | The evidence level of the **ordered pair** (this fact, candidate *i*). Never a property of the fact alone. `NOT_COVERED` = the candidate *supports* the Answer proposition, has strength 0, and can never set a coverage bit at any threshold. `L0` = snapshot absence only, diagnostic, never showable to a student. `L1` = observed alternative value, the weakest showable level. `L2` = verified exclusion; the kernel orders it correctly but implements no L2 rule, and **zero L2 is the correct offline outcome, not a gap**. | `rationale_v3.evidence.classify_fact_against_candidate()` | **local KG + semantic index** |
| `exclusion_bases[i]` | `NONE` / `SCOPED_EMPIRICAL` / `FORMAL_PROOF` | How strong the exclusion argument is, **given** the level. `SCOPED_EMPIRICAL` is an annotation on an existing L1, not a fourth level; it enters the ranking *after* the whole level profile and can never create, upgrade or rescue a level. `L0 + SCOPED_EMPIRICAL` and `L2 + NONE` are invalid and machine-checked. | scoped-empirical rule derivation over the declared scope | local KG |
| `granularity_risks[i]` | `NONE` / `CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT` / `UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE` | Whether an apparent contrast may be a granularity mismatch. Objective key 6, and it blocks main-corpus eligibility. It never moves a fact between levels. | the semantic containment closure | **semantic index** |

**`semantic_check_status` is not an `AnswerCase` field**, but it decides
`granularity_risks`: when the closure could not run, an L1 pair is recorded
`UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE`. `CLOSURE_RAN` means **only that the
check executed** — it is not a statement that a semantic relation was found.

---

## 4. Display versus leakage tokenization — two pipelines, never one

This distinction is part of the contract because collapsing it silently
misnames entities.

| Purpose | Function | Behaviour | Shown to a human? |
|---|---|---|---|
| Display / identity | `rationale_v3.quality.display_label(uri)` | Underscores → spaces, percent-decode, NFC. **Parentheses, Roman numerals, digits, diacritics and case are preserved exactly.** | yes |
| Leakage comparison | `rationale_v3.quality.leakage_tokens(uri, minimum_length=n)` | NFKC, percent-decode, casefold, split on every non-alphanumeric character, drop tokens shorter than `n`. **Lossy by design.** | never |

Verified on disk, 2026-08-10:

```
Iron(II)_chloride    -> display 'Iron(II) chloride'    tokens ('iron','chloride')
Iron(III)_chloride   -> display 'Iron(III) chloride'   tokens ('iron','chloride')
Phosphorus(V)_oxide  -> display 'Phosphorus(V) oxide'  tokens ('phosphorus','oxide')
```

The display strings stay distinct; only the throw-away leakage tokens coincide.
The legacy `remove_parenthetical()` in `src/category_extractor_ClaudeWeb_v2.py`
maps **both** chloride labels to `'Iron chloride'`; it is confined to that file's
leak check and **must not be reused as a display or identity helper** in Phase B.

---

## 5. What Phase B must supply, by access class

| Access class | Fields it decides | Can it be done offline from the pinned snapshot? |
|---|---|---|
| **no external access** | `display_label`, `label_length`, `token_count`, `template_id`, `verbalizable`, `pedagogical_tier`, `soft_leak`, and the leakage half of `eligible` | yes — pure functions plus the versioned policy file |
| **local KG only** | `predicate_uri`, `direction`, `counterpart_uri`, the predicate/object half of `eligible`, observed candidate objects `O_d(κ)`, `exclusion_bases` | yes — `data/infobox.pickle_EnglishVersion_EntityType` |
| **semantic index** | `granularity_risks`, and the `NOT_COVERED` decisions that rest on canonical equivalence or candidate-object-under-claim entailment | only if a cache built for **this** source-object set exists (§6) |
| **LRoleSim** | `Candidate.rank`, `Candidate.score` | yes, given a candidate roster and a built graph |
| **class selection** | which class the candidate pool is drawn from | scoring is offline-capable, but see §6 |
| **live SPARQL / network** | the **class member list** that becomes the candidate roster | **no** — see §6 |

---

## 6. The two stages that are not offline-derivable today

### 6.1 Class member retrieval is the only true network dependency

The pinned snapshot is `infobox-properties` **only**. Probed on 2026-08-10 over
400,000 subject nodes: every predicate lives under
`http://dbpedia.org/property/`, and the strings that look category-like
(`dbp:category`, `dbp:subject`, `dbp:categories`, …) are ordinary infobox slots,
not `dcterms:subject` membership edges. Only 135 `Category:` resources appear
among the first 2,000,000 node URIs, and they are infobox *values*.

**Consequence.** `?member dcterms:subject <Category:…>` cannot be answered from
the pinned snapshot. The complete same-class candidate pool for a new Answer
requires either an approved live SPARQL run or a cached page set. The pilot's
cache, `data/cache/pilot_class_member_mapping_v1.sqlite`, holds exactly 32 pages
for **23 classes**, all of them the human-approved pilot classes.

### 6.2 The semantic index cache is pilot-bound by construction

`SemanticIndexCacheKey` is
`(pinned_kg_sha256, policy_sha256, source_object_list_sha256, max_depth)`, and
`source_object_list_sha256` digests **the exact set of counterpart URIs the run
reasons about**. `pilot_object_uris()` says so in its own docstring: *"an index
built for a different pilot must not be reused."*

Adding any new Answer changes the source-object set, changes the digest, and
makes `load_semantic_index_cache()` return `unavailable_semantic_index(...)`.
The run then reports `SEMANTIC_INDEX_UNAVAILABLE` and every L1 pair carries
`granularity_risk = UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE`.

**This is correct behaviour, not a bug.** The only sound remedy is to rebuild the
index over the enlarged source-object set from the pinned KG, offline, in the
one mode permitted to open the pickle.

---

## 7. Invariants a Phase-B adapter must assert before calling the kernel

1. `len(fact.levels) == len(fact.exclusion_bases) == len(fact.granularity_risks) == len(candidates)` for every fact.
2. Every level is in `{NOT_COVERED, L0, L1, L2}`; every basis is in `{NONE, SCOPED_EMPIRICAL, FORMAL_PROOF}`; every risk is in `{NONE, CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT, UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE}`.
3. `L0 + SCOPED_EMPIRICAL` and `L2 + NONE` never occur.
4. Ranks are contiguous from 1 and unique; URIs are unique.
5. The frozen LRoleSim execution path matches the pinned five parameters.
6. Candidate URIs in `levels` alignment are exactly the candidate URIs in `candidates`.
7. `answer_uri` does not appear among `candidates`.
8. No `Candidate` was sourced from a legacy Overlap ranking.
9. The class the pool was drawn from is recorded, with its approval status.

Violating any of these produces a kernel result that is arithmetically valid and
scientifically meaningless. They belong in the adapter, not in `mcq_core.py` —
the kernel stays the small selection kernel.

---

## 8. Frozen sources of truth for the eight pilot Answers

| Field group | File | SHA-256 |
|---|---|---|
| `Candidate.rank`, `.score`, `.uri`, `display_label` | `outputs/journal2_week2_extract_integration_2026-07-30/candidate_ranking_handoff.jsonl` | `f70fd0cbbfc57af78c3a608b40015aac3639cfb76f6bf75b757f2f2354404300` |
| `FactQuality` (all 11 fields) and the three per-candidate axes | `outputs/journal2_week2_rationale_v3_r1_2026-08-03/evidence_audit_v3_r1.jsonl`, `record_type=answer_fact_evidence` | `5a755acc669e870fc37d415086c049cff2dc4b03cbd3fa05d7d31cad6b0d0b84` |
| regression oracle only | `outputs/journal2_week2_rationale_v3_r1_2026-08-03/selected_mcqs_v3_r1.jsonl` | `5bc4ddf6e140bb56565e85f53142a02f2d9ee7928979413d8a63f04254ea6be4` |

A working reference reader for exactly these two input files already exists as
`load_pilot_cases()` in `tests/test_mcq_core.py` (lines 370–417). It is ~45
lines, reads nothing else, and is the shape a Phase-B1 production adapter should
take. **It can only read records that exist**; it is not a way to manufacture
them for a new Answer.
