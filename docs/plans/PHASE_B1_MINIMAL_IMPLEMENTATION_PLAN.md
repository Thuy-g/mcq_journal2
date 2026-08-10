# Phase B1 — the smallest implementation that reaches a real new Answer

**Status** PROPOSED, 2026-08-10. **No code is authorised by this document.**
**Depends on** `docs/context/PHASE_B_INPUT_CONTRACT.md` (the field contract),
`docs/audits/ALBERT_EINSTEIN_PHASE_B_READINESS.md` (the gap list),
`docs/audits/ANSWER_LEAKAGE_DESIGN_AUDIT.md` (the leakage decision)
**Consistent with** `docs/plans/MINIMAL_RESEARCH_CORE_PLAN.md` §4 and §6

---

## 1. The goal, in one sentence

**Turn real upstream frozen or local records for one Answer into a valid
`AnswerCase`, then run the already-existing Phase-A2 kernel unchanged.**

Not: a new selection algorithm, a new evidence taxonomy, a new ranker, a
verbalizer, a bipartite graph, or a batch runner.

---

## 2. Scope decision forced by the audit

The readiness audit found five gaps. Only three of them are code:

| Gap | Nature | In Phase B1? |
|---|---|---|
| GAP-1 approved class for a new Answer | human decision | **no** — a precondition, §7 |
| GAP-2 class-member roster (needs `dcterms:subject`, unavailable offline) | approved network run | **no** — a precondition, §7 |
| GAP-3 orchestration hard-wired to the nine-Answer pilot policy | code | **yes**, minimally |
| GAP-4 semantic index keyed to the pilot source-object set | code (offline rebuild), downstream of GAP-2 | **yes**, as a reused call |
| GAP-5 no production `AnswerCase` adapter | code | **yes** — this is the heart of B1 |

So Phase B1 is **the adapter plus the thin offline plumbing around it**, built
and proven on inputs that exist today, and ready to accept Albert Einstein the
moment GAP-1 and GAP-2 clear. Building it in that order is deliberate: it means
the network-dependent step, when it finally runs, feeds code that has already
passed a regression gate rather than code being written for the first time.

---

## 3. Files — two, and no more

```
src/mcq_inputs.py          the ONLY new production file
tests/test_mcq_inputs.py   the ONLY new test file
```

`src/mcq_core.py` is **not modified**. Its 243 tests must still pass byte for
byte. `src/rationale_v3/**`, `src/pipeline/**`, `src/selection/**`,
`src/lrolesim/**`, `src/kg/**`, `src/MCQ_lrolesim.py` and every category
extractor are **not modified**.

This matches `MINIMAL_RESEARCH_CORE_PLAN.md` §4's approved shape — *"two files,
one test file"*, with `mcq_core.py` readable top-to-bottom without opening the
other — and fills the slot that plan reserved for `src/mcq_run.py`. The name
`mcq_inputs.py` is preferred because the module's job is *building the input
record*, not orchestrating a run; if the author prefers `mcq_run.py`, the
content below is unchanged.

### Explicitly not created

No plugin framework. No repository or storage abstraction. No writer hierarchy or
`as_record()` per dataclass. No `Protocol`/ABC layer over the readers. No new
policy file — the frozen `predicate_policy.json` is reused as-is. No L2 rule, no
proof generator, no `EvidenceProof` construction. No verbalization. No bipartite
graph. No batch driver, no 100-Answer run.

---

## 4. What `src/mcq_inputs.py` contains

Roughly 300–400 executable lines, half of it validation. Four sections, in this
order.

### 4.1 Reading a frozen R1 Answer — the path that works today

```python
def case_from_frozen_records(
    answer_uri: str,
    *,
    handoff_path: Path,          # candidate_ranking_handoff.jsonl  (Prompt 8D)
    evidence_path: Path,         # evidence_audit_v3_r1.jsonl       (Prompt 8F-R1)
) -> AnswerCase:
    """Build an AnswerCase from records whose evidence levels are ALREADY set."""
```

This is `load_pilot_cases()` from `tests/test_mcq_core.py:370–417` promoted to
production, generalised from "all eight" to "one named Answer", and given the
§4.4 validation. It reads exactly two files and decides nothing: `Candidate.rank`
and `.score` come from the 8D handoff, the eleven `FactQuality` fields and the
three per-candidate axes come from the R1 `answer_fact_evidence` records.

Keeping this path is what makes the regression gate (§6) possible at all.

### 4.2 Building a *new* Answer's facts from the pinned local KG

```python
def answer_facts_from_local_kg(
    answer_uri: str, *, local_kg, quality_policy,
) -> tuple[FactQualityRow, ...]:
    """Every one-hop fact of the Answer, with its eleven quality attributes.

    Reads out_neighbor (OUT) and in_neighbor (IN) for the Answer's node index and
    calls the FROZEN rationale_v3.quality.assess_fact_quality() once per fact.
    Decides no evidence level: a level is a property of an ordered
    (fact, candidate) pair and there are no candidates at this point.
    """
```

Measured feasible for Albert Einstein in the readiness audit §4.4: 66 raw facts →
48 eligible across 17 `κ` keys, 41 with a registered template, with the
Web-Archive and external-URL rejections both firing.

### 4.3 Classifying evidence against a supplied candidate roster

```python
def levels_for_candidates(
    answer_facts, candidates, *, local_kg, semantic_index, rulebook, scope,
) -> tuple[AnswerFact, ...]:
    """Per-(fact, candidate) levels, bases and granularity risks.

    Delegates every decision to the FROZEN
    rationale_v3.evidence.classify_fact_against_candidate(). This function only
    gathers O_d(kappa) — the candidate's observed objects under the same
    predicate AND the same direction — from the pinned KG and aligns the three
    output tuples to the candidate order.
    """
```

**IN and OUT are never merged when gathering `O_d(κ)`.** That is the single
easiest thing to get wrong here and the one that would silently invalidate every
level, so it gets its own test (§5, T-7).

### 4.4 Validation, then the kernel call

```python
def build_and_select(case_inputs, *, pool_policy=DEFAULT_POOL_POLICY):
    """Assert the nine input invariants, build_case(), then select_distractors()."""
```

The nine invariants are `PHASE_B_INPUT_CONTRACT.md` §7, verbatim. They live here
and **never** in `mcq_core.py`. A violation raises; it is never clamped, defaulted
or silently repaired — a clamped input produces a result that is arithmetically
valid and scientifically meaningless.

Provenance the adapter must attach to every emitted record, in addition to what
`canonical_record()` already carries: the selected class URI **and its approval
status**, the input file SHA-256s, the pinned-KG SHA-256, the policy SHA-256s,
the semantic-index cache key with its usability verdict, and the five pinned
LRoleSim parameters.

### 4.5 Leakage — reuse, do not re-derive

Per `ANSWER_LEAKAGE_DESIGN_AUDIT.md` §5: import
`rationale_v3.quality.assess_fact_quality` and let it call
`detect_answer_leakage` internally. `quality.py` imports only `hashlib`, `json`,
`unicodedata`, `dataclasses`, `pathlib`, `typing`, `urllib.parse` and
`rationale_v3.contracts` — no model, no network. Reusing it inherits the
semantics **and** the existing regression tests.

If the dependency on the `rationale_v3` package is later judged undesirable,
copy the six functions verbatim (≈90 lines with comments) and port their tests.
**Do not paraphrase the rule** — a paraphrase is a new rule that has never been
measured. WordNet, spaCy, embeddings and LLMs remain forbidden on this path.

---

## 5. `tests/test_mcq_inputs.py`

| # | Test | Guards |
|---:|---|---|
| T-1 | all eight pilot Answers rebuilt through `case_from_frozen_records()` reproduce the R1 selections exactly — policy, distractor URIs and ranks, rationale fact set, \|R*\| | that the production adapter is equivalent to the test-only reader |
| T-2 | the adapter and `load_pilot_cases()` produce **identical** `AnswerCase` objects | no silent drift between the two readers |
| T-3 | each of the nine input invariants raises when violated (nine parametrised cases) | clamping instead of failing |
| T-4 | a misaligned per-candidate tuple raises rather than truncating | the worst silent corruption available |
| T-5 | `L0 + SCOPED_EMPIRICAL` and `L2 + NONE` are rejected | the two machine-checked forbidden combinations |
| T-6 | a `Candidate` sourced from a legacy Overlap ranking is rejected by an explicit provenance check | ranker substitution |
| T-7 | `O_d(κ)` gathered for `(p, IN)` never includes objects of `(p, OUT)`, on a fixture graph | the direction-merge bug |
| T-8 | the ten leakage regression cases of `ANSWER_LEAKAGE_DESIGN_AUDIT.md` §6 | leak-rule drift; display-label corruption |
| T-9 | a stale semantic-index cache yields `SEMANTIC_INDEX_UNAVAILABLE` and `UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE` on L1 pairs — **not** a relabelled L0 | absence manufactured from a missing index |
| T-10 | `CLOSURE_RAN` is asserted to mean *the check ran*, never *a relation was found* | the semantics slippage the taxonomy warns about |
| T-11 | offline guard: zero socket connections during the whole suite | network creep |
| T-12 | import guard: `nltk`, `spacy`, `sentence_transformers`, `torch`, `SPARQLWrapper` absent from `sys.modules` | model creep |
| T-13 | two consecutive runs produce byte-identical canonical records | determinism |
| T-14 | `src/mcq_core.py` SHA-256 unchanged from `ba4b3785…` | the kernel staying frozen |

Fixtures are small hand-built graphs plus the two existing frozen files. No test
loads the 1.2 GB pickle; the local-KG reader is exercised through a tiny fake
with the same 5-tuple shape.

---

## 6. Acceptance gate

Phase B1 is complete when, and only when:

1. all eight R1 pilot selections are reproduced **through the production
   adapter**, not through test-only code;
2. all 243 existing `tests/test_mcq_core.py` tests still pass, unmodified;
3. `src/mcq_core.py` is byte-identical to `ba4b378584ef1f067f81ab8ffcf2c82137293acac1915e58770f2b1b097abf63`;
4. two consecutive runs are byte-identical apart from clock and Git fields;
5. zero network attempts and zero forbidden imports, both asserted by guards;
6. every invariant of `PHASE_B_INPUT_CONTRACT.md` §7 has a failing-case test;
7. the four line-count categories are reported separately for both new files;
8. terminology conforms to `EVIDENCE_TAXONOMY_V1.md` — in particular the string
   `POSITIVE_VALUE_CONTRAST` does not appear in either new file.

Reproducing the eight pilot Answers is the whole gate. A new Answer cannot be
part of it, because no new Answer's inputs exist yet.

---

## 7. Preconditions for the Albert Einstein integration case

These are **not** Phase B1 work. They are what must happen before the first real
new Answer can be run, in this order:

1. **A human class decision.** Worksheet §31 of the PDF-grounded reconciliation
   is unticked and `human_approval` is empty. The proposal is
   `dbc:German_theoretical_physicists` (72 eligible remote members) with
   fallbacks `dbc:Nobel_laureates_in_Physics` (217) and
   `dbc:20th-century_German_physicists` (560). The automatic top-1
   `dbc:Einstein_family` **must not be used**: the frozen R1 leak rule marks it
   `WHOLE_TOKEN einstein`, and it was never approved.
2. **An approved SPARQL run** to retrieve the members of the approved class and
   map them into the pinned local KG — the Week-1 stage, which is the only way to
   obtain the roster, because the pinned dump is `infobox-properties` only and
   contains no `dcterms:subject` edge.
3. **A graph + LRoleSim run** over Answer ∪ roster, at the five pinned
   parameters, producing `Candidate.rank` and `.score`.
4. **A semantic-index rebuild** over the enlarged source-object set, offline,
   through `build_semantic_index_from_pinned_kg()`. This is downstream of step 2:
   the source-object list includes the candidates' objects.

Only then does `case_from_local_records(Albert_Einstein)` have anything to read.

**Expect `POOL_EXACT`.** Two of the three proposed classes exceed 107 candidates,
where `C(n,3)` passes the 200,000 budget. Einstein would be the first Answer to
exercise the bounded pool on real data. The result is then **exact within the
bounded candidate pool** and carries no optimality claim over excluded
candidates; the walkthrough must say so, and `global_optimality_claim` will
correctly read `false`.

---

## 8. Comment and docstring requirements

Mandatory in `src/mcq_inputs.py`, and not counted against any line budget. The
human author must be able to read the file and defend it without opening
`rationale_v3`:

1. **why the module exists** — that `mcq_core.py` derives none of these fields,
   and that this is the module that discharges the obligation;
2. **each of the nine invariants**, with what breaks scientifically if it is
   removed rather than merely what raises;
3. **IN versus OUT** at every place `O_d(κ)` is gathered — why the two directions
   are never merged, with the `dbp:influences` example;
4. **the open-world limitation** wherever a level is read or written: `L0` is
   snapshot absence and never negation; `L1` is an *observed alternative value*
   and never a proof of incompatibility; only `L2` may be phrased as exclusion,
   and no L2 rule is implemented;
5. **`CLOSURE_RAN` means the check ran**, not that a relation was found;
6. **display versus leakage tokenization** — that `display_label()` preserves
   parentheses and Roman numerals and that `leakage_tokens()` is lossy and never
   displayed, with the `Iron(II)`/`Iron(III)` example;
7. **the leakage thresholds** — the four numbers, where they live, and the
   `Carbon`/`Carbonado` versus `Carbon`/`Boron_carbide` separation they encode;
8. **provenance** — why the class approval status, the cache key and the five
   LRoleSim parameters travel on every record.

---

## 9. Sequencing

| Step | Work | Gate |
|---:|---|---|
| B1.1 | `case_from_frozen_records()` + T-1 … T-6, T-13, T-14 | eight pilot Answers reproduced through production code |
| B1.2 | `answer_facts_from_local_kg()` + T-7, T-8, T-11, T-12 | Albert Einstein's 48 eligible facts reproduced from the pinned KG, matching §4.4 of the readiness audit |
| B1.3 | `levels_for_candidates()` + T-9, T-10 | fixture-graph classification agrees with `rationale_v3.evidence` on the pilot records |
| B1.4 | `build_and_select()` + provenance | package, walkthrough, review |
| — | **stop** | preconditions §7 are outside B1 |
| B2 | the Albert Einstein integration case, after §7 clears | one real new Answer end to end |
| B3 | the 100-Answer batch | not before B2 is reviewed |

Performance is optimised only after correctness and yield measurements exist, per
`CLAUDE.md` "Required work order" item 5.

---

## 10. What this plan does not authorise

Modifying `src/mcq_core.py`, `src/MCQ_lrolesim.py`, `src/rationale_v3/**`,
`src/pipeline/**` or any category extractor; changing the evidence taxonomy, the
fourteen-field rationale key, the six-key objective, or the position of
`candidate_rank_sum` at key 5; implementing L2; implementing verbalization or any
natural-language generation; implementing the choice–evidence bipartite graph
(which is a different object from the LRoleSim matching bipartite graph, and
whose future task must first read the author's own
`src/mcq_generation.py`, `src/build_bipartite_and_draw_ExtendedVersion.py` and
`src/all_in_one.py`); adding WordNet, spaCy, embeddings or an LLM anywhere on the
run path; running the 100-Answer batch; and reusing the unapproved
`dbc:Einstein_family` class for any purpose.
