# Bounded pool-exact search, Phase A2 — a walkthrough for the author

**Branch** `journal2-minimal-core-selection-phase-a2-pool-20260809`
**Parent** `4e3b5fd` (Phase A) · **Specification freeze** `debe7a9`
**Source** `src/mcq_core.py` · **Tests** `tests/test_mcq_core.py`
**Authority for terminology** `docs/context/EVIDENCE_TAXONOMY_V1.md`

Phase A gave the kernel one search mode: enumerate every one of the
`C(n, 3)` candidate triples and score all of them. Phase A2 adds a second mode
for classes where that is no longer affordable, and — this is the part that
matters for the paper — makes the kernel say, on every record it emits, **which
of the two it used and therefore what may be claimed about the answer**.

Nothing else changed. The coverage masks, the exact minimum-cardinality set
cover, the rationale enumeration, the fourteen-field rationale key and the
six-key candidate-combination objective are byte-for-byte the Phase A ones, and
all 201 Phase A tests still pass unmodified.

---

## 1. Why `FULL_EXACT` eventually stops being affordable

`C(n, 3) = n(n−1)(n−2)/6` grows cubically. The pilot classes are small, so the
cost has been invisible so far:

| Candidates `n` | `C(n, 3)` | measured wall clock |
|---:|---:|---|
| 11 (Silicon) | 165 | 0.6 ms |
| 24 (Eisaku Satō) | 2,024 | 67 ms |
| 27 (Aristotle) | 2,925 | 409 ms |
| 49 (Carbon) | 18,424 | 187 ms |
| 107 | 198,485 | — the last size inside the budget |
| 108 | 204,156 | — the first size outside it |
| 200 | 1,313,400 | |
| 1,000 | 166,167,000 | |

The two 27-candidate classes cost more than the 49-candidate one, which shows
that the count of triples is not the whole story: per-combination cost also
scales with the number of eligible Answer facts (Aristotle has 218, Carbon 15).
Measured, Aristotle costs ≈ 140 µs per combination. At that density:

* 108 candidates → ≈ 29 s per Answer → ≈ 48 min for a 100-Answer corpus;
* 1,000 candidates → ≈ 6.5 h **per Answer**.

DBpedia classes of a thousand members are ordinary. So the guard is needed, and
it is placed on the term that actually explodes — the combination count, not the
candidate count:

```python
MAX_EXACT_COMBINATIONS = 200_000        # C(107,3) = 198,485 fits; C(108,3) = 204,156 does not
```

Below the budget nothing changes at all. **All eight pilot Answers remain
`FULL_EXACT`**, and their selections are identical to Phase A.

---

## 2. What `POOL_EXACT` is

When `C(n, 3)` exceeds the budget, the kernel builds a **bounded candidate
pool** and enumerates *every* triple inside it:

```
POOL = TOP  ∪  RESCUE

TOP     the first 75 candidates of the frozen LRoleSim ranking
RESCUE  at most 25 further candidates, from below that cutoff, chosen by
        candidate-local evidence features
|POOL| ≤ 100    →    C(100, 3) = 161,700 triples, all of them enumerated
```

For the 1,000-candidate case that is 161,700 triples instead of 166,167,000 —
**1,028× less work** — and the measured run drops from an estimated 6.5 hours to
0.8 s on the synthetic case in the test suite.

`POOL_EXACT` is still exhaustive. There is no beam, no greedy pass, no sampling,
no early exit and no first-feasible acceptance. What shrank is the *domain*, not
the rigour of the search over it.

### The one thing that must never be blurred

| | `FULL_EXACT` | `POOL_EXACT` |
|---|---|---|
| enumerated over | the **complete** ranked candidate pool | a **bounded** pool of ≤ 100 |
| `pool_optimality_claim` | `true` | `true` |
| `global_optimality_claim` | `true` | **`false`** |
| what you may write | exact over the complete ranked candidate pool of the class | exact **within the bounded candidate pool** |

A `POOL_EXACT` result carries no claim whatsoever about the candidates that were
excluded from the pool. One of them may well have formed a better triple. The
kernel does not know, did not look, and says so.

Both fields, and a sentence spelling this out, are attached to **every**
canonical record (`search_scope`, `search_scope_note`, `global_optimality_claim`,
`pool_optimality_claim`, …). The distinction is not left in a report where it
can be separated from the numbers it qualifies.

---

## 3. Why 75 slots go to LRoleSim

LRoleSim is Journal 1's structural plausibility ranker, and Journal 2 *applies*
it unchanged. Its ranking is the only principled evidence available, before any
search, about which candidates make a distractor a student could believe. The
top of that ranking is therefore where the answer will usually be, and three
quarters of the pool is reserved for it.

No similarity is recomputed while building the pool. No new measure is invented.
No embedding is consulted. The candidates in an `AnswerCase` are already stored
in canonical rank order, so `TOP` is literally the first 75 positions.

---

## 4. Why the other 25 slots exist

**Structural plausibility and evidence availability are different properties,
and on the hardest Answers they point in opposite directions.**

The most LRoleSim-similar candidates are frequently similar *because they share
the Answer's propositions* — same alma mater, same field, same country. A
candidate that shares a proposition is `NOT_COVERED` on that fact: it supports
the Answer's claim, so the fact separates nobody, and it contributes no
coverage. The pilot already contains this pattern in its sharpest form: for
Eisaku Satō, **LRoleSim ranks 2 and 3 have zero L1-covering eligible facts**, and
the exact search had to reach down to ranks 5 and 6 to build an item at all.

Now bound the pool by rank alone and the failure mode is obvious: the search
loses exactly the low-ranked candidates that carry the only usable evidence, and
it then reports an infeasibility that the complete search does not have. Not a
slightly worse item — **no item**.

The rescue quarter is the cheapest available insurance against that. It is a
*coverage* argument, not a quality one: it does not try to find better
distractors, only to keep evidence-bearing ones from being invisible.

---

## 5. How the rescue key works

`candidate_rescue_key(case, position)` returns a tuple; **smallest wins**. It is
computed once per candidate outside `TOP`, the candidates are sorted by it, and
the first 25 are taken.

| # | Component | Direction | What it protects |
|---:|---|---|---|
| 1 | strength of the best level any eligible Answer fact reaches against this candidate | maximise | an `L1_POSITIVE_ALTERNATIVE_OBSERVED` or L2 candidate always outranks an otherwise comparable L0-only one; a candidate that only ever supports the Answer's propositions sorts last |
| 2 | L2 incidences | maximise | more verified exclusions |
| 3 | L1 incidences | maximise | more observed alternative values |
| 4 | best pedagogical tier among the facts that reach L1/L2 **against this candidate** | minimise | prefer a candidate whose evidence is teachable |
| 5 | soft-leak signals among those same discriminating facts | minimise | fewer Answer-label echoes |
| 6 | granularity-risk incidences for this candidate | minimise | fewer risky apparent contrasts |
| 7 | frozen LRoleSim rank | minimise | among equals, the ranker's own ordering decides |
| 8 | canonical candidate URI | ascending | the final deterministic tie-break |

Three points that are easy to get wrong:

* **Only eligible Answer facts are read.** Ineligible facts were removed by the
  upstream hard filter and take no part here either.
* **`NOT_COVERED` provides no rescue coverage.** It is strength 0 in component 1
  and is counted in neither component 2 nor component 3 — exactly as it can
  never set a coverage bit in the search itself.
* **Components 4 and 5 are restricted to facts that actually reach L1/L2 against
  this candidate.** A tier or a soft leak on a fact that discriminates nobody
  here would be the same constant for every candidate and could order nothing.
  (The frozen R1 key counted soft leaks over all eligible facts; the restriction
  is the intended reading of "where candidate-discriminative" and is the one
  documented deviation from R1's key.)

No evidence level is created, changed or upgraded anywhere in this function.
Absence is never reinterpreted as falsity. The key only *reads* levels that the
frozen upstream classification already wrote.

### Why it must not look at combinations

Every component above is read off **one candidate at a time**. Nothing inspects
a pair, a triple, or which other candidates might join it.

This is not a simplification, it is the whole point. A rescue rule that scored
combinations would need the very `C(n, 3)` enumeration the bounded pool exists
to avoid — building the pool would cost what the pool was meant to save. Pool
construction is `O(n × facts)`; the search is `O(|POOL|³ × facts)`. Keeping the
first term linear is what makes the guard worth having.

### Why it is a heuristic, and where it is *not* used

Evidence rescue decides **which candidates the exact search may see**. That is
all. It is:

* **not** part of the six-key candidate-combination objective;
* **not** a seventh key, a bonus, or a tie-break inside the search;
* **not** any advantage to the candidate that received it — a rescued candidate
  is scored by exactly the same objective as a top-ranked one, and loses to it
  whenever the objective says so.

So the honest description for the paper is: *a pool-construction heuristic that
bounds the search domain, followed by an exact search over that domain.* The
heuristic can cost you the global optimum. It cannot corrupt the objective.

---

## 6. A worked example — the rescue that saves the item

This is the synthetic case in
`tests/test_mcq_core.py::test_a_top_only_pool_loses_the_evidence_and_produces_no_item_at_all`,
reduced to its bones. Sixty candidates, one eligible Answer fact, and a policy
bounded to 25 (`top_by_lrolesim = 20`, `evidence_rescue = 5`) so the example
fits on a page.

```
Answer fact F:  (p, OUT, o)

candidate ranks  1 … 57   level(F) = NOT_COVERED   (they share the Answer's object)
candidate ranks 58, 59, 60  level(F) = L1          (observed alternative value)
```

**Pool by rank alone** (`top_by_lrolesim = 25`, `evidence_rescue = 0`):

```
POOL = ranks 1…25
every candidate in POOL is NOT_COVERED on F
→ no triple is coverable at strict-l2, at main-l1 or even at diagnostic-l0
→ select_distractors() returns None.  No MCQ is produced.
```

**Pool with rescue** (`top_by_lrolesim = 20`, `evidence_rescue = 5`):

```
TOP    = ranks 1…20
rescue keys over ranks 21…60, smallest first:
    rank 58 → (−2, 0, −1, 1, 0, 0, 58, …)   L1 → component 1 = −strength(L1) = −2
    rank 59 → (−2, 0, −1, 1, 0, 0, 59, …)
    rank 60 → (−2, 0, −1, 1, 0, 0, 60, …)
    rank 21 → ( 0, 0,  0, 2, 0, 0, 21, …)   NOT_COVERED → component 1 = 0
    rank 22 → ( 0, 0,  0, 2, 0, 0, 22, …)
    …
RESCUE = ranks 58, 59, 60  (evidence first)  +  ranks 21, 22  (two slots left,
                                                best rank among the rest)
POOL   = 25 candidates
→ exactly one coverable triple: ranks 58, 59, 60
→ main-l1, |R*| = 1, and the item exists.
```

The complete `FULL_EXACT` search over all sixty candidates picks the same triple,
which is what makes the bounded pool the right approximation here rather than a
lucky one. That agreement is asserted in the test.

### The same mechanism on real pilot data

Forcing `M = 25` on the three pilot classes larger than 25 candidates
(`docs/checks/MINIMAL_CORE_PHASE_A2_POOL_ABLATION.csv`) shows the key doing real
work on real evidence:

| Answer | `n` | rescued ranks | dropped ranks | why |
|---|---:|---|---|---|
| Aristotle | 27 | 20, 21, 22, 23, 24, **26** | 25, 27 | rank 26 carries **157** L1 incidences, rank 25 carries 1 |
| Plato | 27 | 20, 22, 23, 24, 25, **26** | 21, 27 | rank 26 carries **127** L1 incidences, rank 21 carries 2 |
| Carbon | 49 | 20, 21, 22, 23, **30, 31** | 24–29, 32–49 | ranks 30 and 31 carry 10 L1 incidences each, ranks 24–29 carry 1 |

In all three, rescue changed *which candidates entered the pool*. In none of the
three did it change the selected item, because the winning triple was ranks
1|2|3 all along. Eight small Answers cannot exercise the mechanism the way a
1,000-member class will; see the ablation note.

---

## 7. Why local candidate-pool anonymity still uses the COMPLETE pool

`local_candidate_pool_anonymity_count` is `|S_local(R)|`: how many entities in
`{Answer} ∪ complete ranked candidate pool` support **every** proposition in the
selected rationale. A count of 1 means the rationale singles the Answer out
inside that pool.

The denominator is `1 + n`, where `n` is the **complete** ranked candidate pool
— never the bounded search pool. Phase A2 did not touch this, and there is now a
regression test pinning it.

The reason is a claim, not a convenience. Anonymity answers *"could a student
point at another entity in this class and give the same reason?"*. Search scope
answers *"how many triples did we score?"*. If the denominator followed the
search pool, then on a 1,000-candidate class we would divide by 101 instead of
1,001 and quietly report that a rationale distinguishes the Answer from
everything — while 900 unexamined class members had never been checked. That
would be a fabricated uniqueness claim produced by an efficiency measure.

So:

```
search scope   ⊂  the pool the OBJECTIVE ranged over
anonymity scope =  the COMPLETE ranked candidate pool, always
```

The test `test_anonymity_still_counts_candidates_outside_the_bounded_search_pool`
constructs a case where two supporting candidates sit outside the bounded pool
and asserts they are still counted, and that the ratio denominator is 13, not 7.

The name remains deliberately long. Even at the complete pool it is a **local**
statement about one class's ranked candidates: not uniqueness in DBpedia, not
global uniqueness.

---

## 8. Language that is safe for the paper

When the reported run is `FULL_EXACT`:

> For each Answer we enumerate all `C(n, 3)` candidate triples and select the
> optimum of the lexicographic objective. The selection is exact over the
> complete ranked candidate pool of the selected class.

When the reported run is `POOL_EXACT`:

> For classes whose triple count exceeds the configured budget of 200,000, the
> search is restricted to a bounded candidate pool of at most 100 candidates —
> the 75 highest-ranked by LRoleSim plus up to 25 evidence-rescue candidates —
> and every triple inside that pool is enumerated. **The selection is exact
> within the bounded candidate pool; no optimality claim is made over candidates
> excluded from the pool.**

Safe: *exact within the bounded candidate pool*; *pool-exact*; *no optimality
claim is made over candidates excluded from the pool*; *exhaustive over the
constructed pool*.

Forbidden for a `POOL_EXACT` result: *globally optimal*, *global optimum*, *exact
over all candidates*, *the best possible distractor set*, *optimal distractors* —
unless the sentence explicitly negates the claim, as
`SEARCH_SCOPE_NOTE[POOL_EXACT]` does. A guard test scans the emitted note for
each forbidden phrase and requires a `NOT` immediately before it.

Two further phrasings to keep out of the paper, inherited from Phase A and
unaffected by A2:

* nothing here may be written as *"the candidate did not do X"* — the open-world
  limitation is unchanged, `L0` is snapshot absence and `L1` is an **observed
  alternative value**, neither being a proof of incompatibility;
* the rescue mechanism must not be described as improving distractor quality. It
  changes what the search can see, and nothing else.

---

## 9. What A2 added, in code

| Piece | Role |
|---|---|
| `PoolPolicy` | the five numbers of the budget, validated at construction; `for_pool_size(M)` scales the inherited 3:1 split for ablation |
| `candidate_rescue_key(case, position)` | the candidate-local ordering of §5 |
| `CandidatePool` | which positions the search ranges over, plus `global_optimality_claim` / `pool_optimality_claim` and the compact provenance block |
| `build_candidate_pool(case, policy, force_pool)` | `FULL_EXACT` under the budget, `POOL_EXACT` above it; `force_pool=True` is an evaluation/debug option only |
| `feasible_combinations(case, policy, pool)` | one added argument: enumerate over `pool.positions` instead of `range(n)` |
| `select_distractors(case, pool_policy, force_pool)` | builds the pool first, then runs the unchanged Phase A search |

`Selection` now carries the `CandidatePool` and exposes `search_scope`,
`candidate_count` (still the complete pool) and `enumerated_combination_count`.
The canonical record gained the fifteen required provenance fields plus the two
notes. No new module, no new production file, no new dependency: `mcq_core.py`
still imports only `__future__`, `dataclasses`, `itertools`, `math` and `typing`.

---

## 10. How to re-run the checks

```bash
conda activate mcq-journal2
cd /home/thuy/projects/mcq_journal2

python -m py_compile src/mcq_core.py tests/test_mcq_core.py
python -m pytest -q tests/test_mcq_core.py
python tools/count_loc.py src/mcq_core.py tests/test_mcq_core.py
```

The pool tests are the section headed `8. Phase A2 — the bounded candidate pool`
in `tests/test_mcq_core.py`. The published ablation CSV is re-derived and
compared row by row by `test_published_pool_ablation_csv_matches_the_kernel`, so
it cannot drift away from the kernel without the suite failing.
