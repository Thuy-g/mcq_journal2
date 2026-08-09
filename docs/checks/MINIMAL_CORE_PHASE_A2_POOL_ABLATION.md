# Pool-size ablation on the eight-Answer pilot — a diagnostic, not a validation

**Date** 2026-08-09 · **Branch** `journal2-minimal-core-selection-phase-a2-pool-20260809`
**Data** `docs/checks/MINIMAL_CORE_PHASE_A2_POOL_ABLATION.csv` (32 rows = 8 Answers × 4 pool sizes)
**Verified by** `tests/test_mcq_core.py::test_published_pool_ablation_csv_matches_the_kernel`

Every pilot Answer runs `FULL_EXACT` under the default policy, so this ablation
uses `force_pool=True` to make each Answer run `POOL_EXACT` at four pool sizes
and compares the result against its own `FULL_EXACT` reference. The four sizes
are the same policy at four scales — `top = ceil(3M/4)`, `rescue = M − top` —
so `M = 100` is exactly the inherited default 75 + 25.

---

## 1. Headline result

**All 32 forced-pool runs reproduce the `FULL_EXACT` selection exactly**: same
evidence policy, same three distractor URIs and ranks, same rationale fact set,
same `|R*|`.

| Forced `M` | top / rescue | Answers reproducing `FULL_EXACT` | Answers whose pool was actually smaller than the class |
|---:|---|---:|---:|
| 25 | 19 / 6 | **8 / 8** | 3 (Aristotle, Plato, Carbon) |
| 50 | 38 / 12 | **8 / 8** | 0 |
| 75 | 57 / 18 | **8 / 8** | 0 |
| 100 | 75 / 25 | **8 / 8** | 0 |

The fourth column is the one to read first. The pilot classes hold 11 to 49
candidates, so at `M = 50`, `M = 75` and `M = 100` **the bounded pool contains
the entire class** and "reproduces `FULL_EXACT`" is arithmetic, not evidence.
Only `M = 25` restricts anything at all, and only for three Answers.

Per-Answer detail:

| Answer | `n` | reference ranks | `M=25` pool | `M=50` pool | `M=75` pool | `M=100` pool | any change? |
|---|---:|---|---:|---:|---:|---:|:--:|
| Silicon | 11 | 1\|2\|3 | 11 | 11 | 11 | 11 | no |
| Adam Smith | 18 | 1\|2\|3 | 18 | 18 | 18 | 18 | no |
| Shinya Yamanaka | 24 | 1\|2\|3 | 24 | 24 | 24 | 24 | no |
| Shin'ichirō Tomonaga | 24 | 1\|2\|3 | 24 | 24 | 24 | 24 | no |
| **Eisaku Satō** | 24 | **1\|5\|6** | 24 | 24 | 24 | 24 | no |
| Aristotle | 27 | 1\|2\|3 | **25** | 27 | 27 | 27 | no |
| Plato | 27 | 1\|2\|3 | **25** | 27 | 27 | 27 | no |
| Carbon | 49 | 1\|2\|3 | **25** | 49 | 49 | 49 | no |

Eisaku Satō is the interesting non-event: his selection reaches down to LRoleSim
ranks 5 and 6, but 5 and 6 sit inside the top-19 cutoff even at `M = 25`, so no
pool size in this range can threaten it.

---

## 2. Which Answers differ

**None.** `same_distractor_selection`, `same_rationale` and `same_policy` are
`True` in all 32 rows.

Every forced row reports `global_optimality_claim = False` and
`pool_optimality_claim = True`, including the rows where the bounded pool
happens to contain the whole class. That is deliberate: the kernel reports the
scope it searched under, not the scope it could have claimed after the fact.
A reader who sees `POOL_EXACT` must never have to reconstruct whether the pool
was complete before trusting the claim.

---

## 3. Did evidence rescue change any forced-pool result?

**It changed pool composition in all three genuinely bounded cases, and changed
no selected item.**

At `M = 25` the rescue key pulled in candidates that a rank-only cutoff would
have dropped, and it did so for the intended reason — evidence density:

| Answer | rescued ranks | dropped ranks | evidence behind the choice |
|---|---|---|---|
| Aristotle | 20, 21, 22, 23, 24, **26** | 25, 27 | rank 26 has **157** L1 incidences; rank 25 has 1; rank 27 reaches only L0 |
| Plato | 20, 22, 23, 24, 25, **26** | 21, 27 | rank 26 has **127** L1 incidences; rank 21 has 2; rank 27 reaches only L0 |
| Carbon | 20, 21, 22, 23, **30, 31** | 24–29, 32–49 | ranks 30 and 31 have 10 L1 incidences each; ranks 24–29 have 1 |

A counterfactual run with the rescue slots removed (`top = M`, `rescue = 0`) at
each of the four sizes reproduces the same eight selections as well. So on this
pilot the mechanism is **inert with respect to the output** — every winning
triple came from the top of the ranking, and no Answer needed a rescued
candidate to form an item.

That is a statement about eight small Answers, not about the mechanism. The
adversarial synthetic case in
`tests/test_mcq_core.py::test_a_top_only_pool_loses_the_evidence_and_produces_no_item_at_all`
shows the failure the slots exist to prevent: with the rescue slots the kernel
produces a `main-l1` item, and without them it produces **nothing at all**. The
pilot simply contains no class where the top of the LRoleSim ranking is that
evidence-starved — while the pilot *does* contain the milder form of exactly
that pattern, in Eisaku Satō's ranks 2 and 3, which carry zero L1-covering
eligible facts.

---

## 4. Why this cannot validate `M = 100`, and what would

Four reasons, all of them structural:

1. **The classes are too small.** Seven of eight are under 30 candidates, and
   the largest is 49. `M = 100` never binds. An ablation in which the treatment
   is not applied measures nothing about the treatment.
2. **`FULL_EXACT` is never even left.** Every reference run here is exhaustive
   over the complete pool, because `C(49, 3) = 18,424` is a ninth of the budget.
   The regime the default policy was designed for — `n > 107` — is not
   represented by a single Answer.
3. **Eight Answers cannot estimate a tail risk.** The quantity that matters is
   *how often the winning triple contains a candidate ranked below 75*, and
   the pilot's answer to that question is a sample of eight, in which the
   deepest rank ever selected is 6.
4. **The pilot's evidence density is not the corpus's.** Fact counts here run
   from 3 (Silicon) to 218 (Aristotle) eligible facts. Rescue only bites where
   evidence is sparse at the top of the ranking, and the pilot has no such case.

What would actually settle the pool size is the 100-Answer batch, reporting per
Answer: the class size, whether `POOL_EXACT` was entered, the deepest LRoleSim
rank in the selected triple, whether any selected candidate was a rescued one,
and — on the classes small enough to afford it — a `FULL_EXACT` cross-check
against the bounded result. **That run is Phase B and is not performed here.**

Until then the default stays as inherited:

```
M = 100    top_by_lrolesim = 75    evidence_rescue = 25
MAX_EXACT_COMBINATIONS = 200_000
```

It is not being confirmed by this pilot; it is being *left alone* because the
pilot provides no evidence to move it.

---

## 5. Column reference

| Column | Meaning |
|---|---|
| `answer_uri`, `display_label` | the Answer entity |
| `reference_search_scope` | scope of the unforced reference run — `FULL_EXACT` for all eight |
| `original_candidate_count` | size of the complete ranked candidate pool |
| `forced_pool_size` | `M` |
| `top_limit`, `rescue_limit` | `ceil(3M/4)` and `M − top` |
| `actual_pool_candidate_count` | candidates the forced search actually ranged over |
| `evidence_rescue_count` | how many entered through a rescue slot |
| `reference_policy`, `pool_policy_reached` | evidence policy chosen in each run |
| `reference_distractor_ranks`, `pool_distractor_ranks` | LRoleSim ranks of the selected triple, `|`-separated |
| `reference_rationale_facts`, `pool_rationale_facts` | canonical `predicate direction -> counterpart`, `;`-separated |
| `same_distractor_selection`, `same_rationale`, `same_policy` | the three comparisons |
| `global_optimality_claim`, `pool_optimality_claim` | the claims the forced run supports — `False` / `True` throughout |

Reproduce with:

```bash
conda activate mcq-journal2
python -m pytest -q tests/test_mcq_core.py -k "ablation or forced_pool"
```
