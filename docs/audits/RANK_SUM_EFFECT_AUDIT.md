# Rank-sum effect audit

**Date** 2026-08-06 · **Branch** `journal2-spec-freeze-20260806`
**Data** `docs/audits/RANK_SUM_EFFECT_AUDIT.csv` (8 rows, one per selected pilot MCQ)
**Derived by** `scripts/spec_freeze_audit.py`

**The Prompt-8F-R1 selector was not modified.** The counterfactual is computed
by an independent re-implementation of the objective that first proves it
reproduces all eight R1 selections exactly, then re-runs the ordering with
objective key 5 removed.

---

## 1. Where `candidate_rank_sum` sits in the objective

Smallest wins, evaluated left to right
(`src/rationale_v3/selector.py:769-775`, `:908-923`):

| # | Field | Role |
|---:|---|---|
| 1 | `-lrolesim_score_sum` | scientific objective — total structural plausibility |
| 2 | `-lrolesim_score_min` | scientific objective — the weakest distractor |
| 3 | `minimum_rationale_size` | scientific objective — rationale compactness |
| 4 | 14-field rationale ranking key | scientific objective — evidence profile, then quality |
| 5 | **`candidate_rank_sum`** | **the field audited here** |
| 6 | `candidate_uris` | lexicographic last resort |

Key 5 is reached **only** by combinations that have already tied on keys 1–4.
Removing it promotes key 6 — lexicographic URI order — into the deciding
position. The counterfactual therefore compares *one deterministic tie-break
against another*, not "tie-break versus no tie-break".

---

## 2. Results

| # | Answer | feasible combos | tied after key 4 | key 5 reached | distinct `rank_sum` among tied | key 5 decided | ranks with key 5 | ranks without key 5 | selection changed |
|---:|---|---:|---:|:---:|---:|:---:|---|---|:---:|
| 1 | Shinya Yamanaka | 1330 | 1 | no | 1 | no | 1\|2\|3 | 1\|2\|3 | **no** |
| 2 | Shin'ichirō Tomonaga | 1540 | 1 | no | 1 | no | 1\|2\|3 | 1\|2\|3 | **no** |
| 3 | **Eisaku Satō** | 680 | **3** | **yes** | **3** | **yes** | **1\|5\|6** | **1\|5\|6** | **no** |
| 4 | Carbon | 4960 | 1 | no | 1 | no | 1\|2\|3 | 1\|2\|3 | **no** |
| 5 | Silicon | 4 | 1 | no | 1 | no | 1\|2\|3 | 1\|2\|3 | **no** |
| 6 | Aristotle | 2600 | 1 | no | 1 | no | 1\|2\|3 | 1\|2\|3 | **no** |
| 7 | Plato | 2600 | 1 | no | 1 | no | 1\|2\|3 | 1\|2\|3 | **no** |
| 8 | Adam Smith | 816 | 1 | no | 1 | no | 1\|2\|3 | 1\|2\|3 | **no** |

### The three headline numbers

* **How many Answers reach the rank-sum tie-break? 1 of 8** — Eisaku Satō.
* **How many selected combinations change when `rank_sum` is removed? 0 of 8.**
* **Which Answers change? None.**

### Why 7 of 8 never reach key 5

For those seven, exactly one feasible combination survives objective keys 1–3.
LRoleSim scores are real-valued and largely distinct, so `-score_sum` alone
almost always singles out one combination; keys 4, 5 and 6 are then never
consulted. In each of the seven, that unique survivor is the LRoleSim top three
`1|2|3` — i.e. rationale feasibility did not force a departure from the ranking.

### Why Eisaku Satō does reach key 5, and what happens there

Satō's candidates 6, 7 and 8 form an **exact** LRoleSim tie group
(`tie_group_id = 5`, `tie_group_size = 3`, score `0.20696461464461466` for all
three). The three combinations `{1,5,6}`, `{1,5,7}`, `{1,5,8}` therefore tie on:

* key 1, `score_sum = 0.6372318131251465` — identical;
* key 2, `score_min = 0.20696461464461466` — identical;
* key 3, `|R*| = 2` — identical;
* key 4, the full 14-field rationale key — identical, because all three use the
  *same* two rationale facts (`dbp:almaMater` OUT → University of Tokyo and
  `dbp:before` IN → Kiichi Aichi) with the same evidence profile.

Key 5 separates them: `rank_sum` 12 < 13 < 14, selecting `{1,5,6}` =
Ei-ichi Negishi, Hideki Shirakawa, **Isamu Akasaki**. So **`rank_sum` is
genuinely decisive for this Answer.**

**But removing it changes nothing**, because key 6 then decides and reaches the
same result by coincidence: sorting the URI triples lexicographically,

```
…/Isamu_Akasaki   <   …/Ryōji_Noyori   <   …/Shin'ichirō_Tomonaga
```

`I` < `R` < `S`, so alphabetical order happens to agree with rank order here.

**This agreement is a coincidence of this pilot and must not be reported as a
property of the method.** Had the tie group been, say, `Akira`, `Isamu`,
`Zenji` at ranks 8, 7, 6, the two tie-breaks would have disagreed and the
selected distractor would have differed.

---

## 3. Rank sum as a tie-break versus as a quality objective

The two readings must be kept apart, because the pilot supports one and refutes
the other.

### As a deterministic tie-break — supported

Placed at key 5, `rank_sum` answers a well-posed question: *given two candidate
triples that the objective cannot otherwise distinguish, which should be
preferred?* Its answer — prefer the triple whose members sit higher in the
LRoleSim ranking — is:

* **deterministic and reproducible**, with no dependence on iteration order;
* **aligned with the ranker the method is built on**. When LRoleSim scores tie
  *exactly*, rank is the ranker's own residual ordering (its tie-group
  numbering), so preferring a lower rank sum stays inside the LRoleSim
  framework rather than importing an outside criterion;
* **strictly more defensible than the alternative it displaces**. Without it,
  ties are resolved by alphabetical URI order, which is arbitrary, is
  correlated with nothing scientific, and would be awkward to justify to a
  reviewer asking why `Isamu Akasaki` beat `Ryōji Noyori`.

### As a scientifically meaningful quality objective — not supported

`rank_sum` is **not** evidence that a distractor set is better. Rank is an
*ordinal* transform of the LRoleSim score, and the objective already maximises
the score itself (keys 1 and 2) with full cardinal precision. Promoting
`rank_sum` above keys 1–4 would mean preferring a triple with a *lower* total
similarity because its ordinal positions summed smaller — replacing a cardinal
measurement with a coarser ordinal proxy for it. The pilot gives no evidence
that `rank_sum` carries information about plausibility, rationale quality or
item difficulty beyond what the scores already carry.

Its correct description in the paper is therefore
**"a deterministic tie-break aligned with the LRoleSim ranking"**, never
"a plausibility objective" and never a component of `Φ(D)`.

---

## 4. Recommendation for the future minimal core

**Keep `candidate_rank_sum`, at objective key 5, unchanged.**

The task anticipated a possible recommendation to remove it if it changed zero
pilot selections. It does change zero pilot selections — but removal is still
the wrong call, for three reasons:

1. **It is reached and is decisive.** In 1 of 8 pilot Answers, three
   combinations survive to key 5 and `rank_sum` picks one. The tie-break is
   live, not dead code. That it agrees with key 6 here is luck, and the audit
   says so explicitly.
2. **Removing it does not remove the tie-break, only replaces it.** The
   combinations still have to be ordered; deleting key 5 hands the decision to
   alphabetical URI order. That is a *worse* rule, not a simpler one — the
   scientific justification gets harder, not easier.
3. **The cost is negligible.** `sum(ranks)` is one integer per combination,
   roughly two lines of code, and it is already computed for provenance
   reporting (`SEL.candidate_rank_sum`). It contributes nothing to the
   ~1,500-line budget worth reclaiming.

**Conditions attached to keeping it.**

* Keep it at key 5. It must never be promoted above keys 1–4.
* Keep documenting it as a tie-break, not as a quality objective.
* Re-run this audit on the 100-Answer batch. Exact LRoleSim score ties are the
  trigger, and the pilot shows they do occur (Satō has tie groups of size 2 and
  3; the class contains a four-way tie at rank 21–24). If the batch shows key 5
  is reached often, its behaviour becomes worth reporting in the paper; if the
  batch shows it is reached never, the recommendation should be revisited with
  that larger evidence base.

---

## 5. Column reference for the CSV

| Column | Meaning |
|---|---|
| `feasible_combination_count` | full-coverage combinations with \|R*\| ≤ ρ under the selected policy |
| `combinations_tied_after_objective_key_4` | how many survive keys 1–4, i.e. how many key 5 must decide among |
| `rank_sum_tiebreak_reached` | `combinations_tied_after_objective_key_4 > 1` |
| `distinct_rank_sums_among_tied` | whether `rank_sum` can separate them at all |
| `rank_sum_decided_the_tie` | reached **and** able to separate |
| `selected_ranks_with_rank_sum` | the R1 selection (verified against `selected_mcqs_v3_r1.jsonl`) |
| `selected_ranks_without_rank_sum` | the counterfactual with key 5 deleted, keys 1–4 and 6 unchanged |
| `selection_changed_when_rank_sum_removed` | the headline result |

---

## 6. Reproduction

```bash
python scripts/spec_freeze_audit.py \
    --rank-sum-csv docs/audits/RANK_SUM_EFFECT_AUDIT.csv
python -m pytest -q tests/test_spec_freeze_audit.py
```

Relevant assertions:
`test_sato_is_the_only_answer_reaching_the_rank_sum_tiebreak`,
`test_removing_rank_sum_changes_no_pilot_selection`.
