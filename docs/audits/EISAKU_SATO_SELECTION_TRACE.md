# Eisaku Satō — exact selection trace

**Date** 2026-08-06 · **Branch** `journal2-spec-freeze-20260806`
**Purpose** Reconstruct, from the frozen machine-readable evidence, why the
Prompt-8F-R1 run selected LRoleSim ranks **1, 5, 6** rather than the provisional
top three, and why the minimum rationale has cardinality **2**.

**No selection code was changed.** The numbers below are re-derived by
`scripts/spec_freeze_audit.py`, an independent re-implementation of the
objective that reads only frozen records and imports nothing from
`src/rationale_v3/`. That re-derivation reproduces **all eight** R1 pilot
selections — policy, distractor triple and rationale set — byte-for-byte
equivalent to `selected_mcqs_v3_r1.jsonl`; see
`tests/test_spec_freeze_audit.py::test_rederivation_reproduces_every_r1_selection`.
The trace is therefore derived, not copied from the R1 implementation report.

## Source records cited

| Handle | File | Selector |
|---|---|---|
| `EV[i]` | `outputs/journal2_week2_rationale_v3_r1_2026-08-03/evidence_audit_v3_r1.jsonl` | `record_type=answer_fact_evidence`, `answer_uri=…/Eisaku_Satō`, `fact_index=i` |
| `CS` | same file | `record_type=combination_search`, `answer_uri=…/Eisaku_Satō` |
| `SEL` | `outputs/journal2_week2_rationale_v3_r1_2026-08-03/selected_mcqs_v3_r1.jsonl` | `answer_uri=…/Eisaku_Satō`, `pilot_slot=3` |
| `RANK` | `outputs/journal2_week2_extract_integration_2026-07-30/candidate_ranking_handoff.jsonl` | `answer_uri=…/Eisaku_Satō` |

Input integrity, re-verified 2026-08-06:

```
f70fd0cbbfc57af78c3a608b40015aac3639cfb76f6bf75b757f2f2354404300  candidate_ranking_handoff.jsonl
36335c317997ec7de43f775ca627d2829d0d1d04c3345c95f55264230007eb3b  observed_answer_facts.jsonl
b90fd043d9633fb720d03634d8ed0549d218f662a0d868899c2b75705475f870  observed_candidate_facts.jsonl
```

All three match `SEL.input_package_sha256`.

Fixed parameters (`SEL`, `CS`): `k=3`, `ρ=3`, `search_scope=FULL_EXACT`,
`measure=lrolesim_ed`, `lrolesim_beta=0.2`, `iterations=3`,
`iteration_mode=fixed`, `ranker_name=lrolesim_m1_fixed_k3`,
`selected_class_uri=…/Category:Japanese_Nobel_laureates`.

---

## 1. The objective being optimised

Smallest wins, evaluated left to right:

| # | Field | Direction |
|---:|---|---|
| 1 | `-lrolesim_score_sum` | maximise total structural plausibility |
| 2 | `-lrolesim_score_min` | maximise the weakest distractor |
| 3 | `minimum_rationale_size` | minimise \|R*\| (exact bitmask set cover) |
| 4 | the 14-field rationale ranking key | evidence-level profile first, then quality |
| 5 | `candidate_rank_sum` | deterministic tie-break |
| 6 | `candidate_uris` | lexicographic last resort |

LRoleSim is consumed here **only** as a frozen structural plausibility ranker.
No similarity is recomputed, and LRoleSim produces no rationale.

---

## 2. All 24 ranked candidates

From `RANK.ranked_candidates`. The fourth column is derived from `EV[*]`: the
number of the 55 **eligible** Answer facts that cover the candidate at
`L1_POSITIVE_ALTERNATIVE_OBSERVED` or better.

| rank | candidate | LRoleSim score | L1-covering eligible facts | provisional top-3 | selected |
|---:|---|---|---:|:---:|:---:|
| 1 | Ei-ichi Negishi | 0.22190222222222222 | 1 | yes | **yes** |
| 2 | Yasunari Kawabata | 0.21841777777777779 | **0** | yes | |
| 3 | Masatoshi Koshiba | 0.21333333333333335 | **0** | yes | |
| 4 | Yoshinori Ohsumi | 0.21333333333333335 | **0** | | |
| 5 | Hideki Shirakawa | 0.20836497625830960 | 1 | | **yes** |
| 6 | Isamu Akasaki | 0.20696461464461466 | 1 | | **yes** |
| 7 | Ryōji Noyori | 0.20696461464461466 | 1 | | |
| 8 | Shin'ichirō Tomonaga | 0.20696461464461466 | 1 | | |
| 9 | Shinya Yamanaka | 0.20648888888888889 | 2 | | |
| 10 | Shuji Nakamura | 0.20648888888888889 | 2 | | |
| 11 | Hiroshi Amano | 0.20615874855331065 | 1 | | |
| 12 | Osamu Shimomura | 0.20615874855331065 | 1 | | |
| 13 | Toshihide Maskawa | 0.20615874855331065 | 1 | | |
| 14 | Leo Esaki | 0.20426481567814903 | 1 | | |
| 15 | Koichi Tanaka | 0.20392102383213495 | 1 | | |
| 16 | Hideki Yukawa | 0.20386991181657849 | 1 | | |
| 17 | Kenichi Fukui | 0.20386991181657849 | 1 | | |
| 18 | Satoshi Ōmura | 0.20363304843304844 | 1 | | |
| 19 | Takaaki Kajita | 0.20359658119658119 | 1 | | |
| 20 | Kenzaburō Ōe | 0.20280888888888890 | 1 | | |
| 21 | Akira Yoshino | 0.20000000000000001 | **0** | | |
| 22 | Japan Confederation of A- and H-Bomb Sufferers Organizations | 0.20000000000000001 | **0** | | |
| 23 | Susumu Tonegawa | 0.20000000000000001 | **0** | | |
| 24 | Tasuku Honjo | 0.20000000000000001 | **0** | | |

**17 of 24** candidates have at least one L1-covering eligible fact, matching
`CS.per_policy["main-l1"].candidates_with_any_coverage = 17`. Seven — ranks
2, 3, 4, 21, 22, 23, 24 — have **none**.

**Exact score ties matter later.** Ranks 3 and 4 share a score; ranks 6, 7 and 8
share `0.20696461464461466` exactly (`RANK.tie_group_id = 5`, `tie_group_size = 3`);
ranks 9–10, 11–13, 16–17 and 21–24 likewise tie. These are exact float
equalities in the frozen handoff, not near-equalities.

### Fact eligibility

Satō has **60** observed Answer facts, of which **55** are eligible
(`CS.answer_fact_count = 60`, `CS.eligible_answer_fact_count = 55`). The five
rejected facts, from `EV[*].quality.rejection_reasons`:

| `fact_index` | predicate | dir | object | rejection reasons |
|---:|---|---|---|---|
| 6 | `dbp:caption` | IN | `First_Satō_Cabinet` | `PREDICATE_RAW_LAYOUT_SLOT`, `ANSWER_LEXICAL_LEAK` |
| 7 | `dbp:caption` | IN | `Second_Satō_Cabinet` | `PREDICATE_RAW_LAYOUT_SLOT`, `ANSWER_LEXICAL_LEAK` |
| 9 | `dbp:governmentHead` | IN | `First_Satō_Cabinet` | `ANSWER_LEXICAL_LEAK` |
| 10 | `dbp:governmentHead` | IN | `Second_Satō_Cabinet` | `ANSWER_LEXICAL_LEAK` |
| 59 | `dbp:url` | OUT | `…openlearn-live-12th-august-2015%23sato` | `PREDICATE_EXTERNAL_URL_FIELD`, `OBJECT_WEB_ARCHIVE_URL` |

These are **hard filters**, applied before any ranking. Facts 6, 7, 9 and 10
would leak the string "Satō" into the rationale; fact 59 is a raw external URL.

---

## 3. The provisional top three, and why it fails

`CS.provisional_lrolesim_top3_ranks = [1, 2, 3]`,
`CS.provisional_top3_treated_as_final = false`.

Per-candidate evidence over the 55 eligible facts, derived from `EV[*].per_candidate`:

| rank | candidate | `L1` | `L0` | `NOT_COVERED` | L1-covering facts |
|---:|---|---:|---:|---:|---|
| 1 | Ei-ichi Negishi | **1** | 53 | 1 | `EV[3]` `dbp:before` (IN) → `Kiichi_Aichi` |
| 2 | Yasunari Kawabata | **0** | 54 | 1 | — none — |
| 3 | Masatoshi Koshiba | **0** | 54 | 1 | — none — |

### Why ranks 1, 2 and 3 cannot form a full-coverage main-L1 combination

The `main-l1` policy requires **every** distractor to be covered by at least one
rationale fact at level L1 or L2. Coverage of a candidate is possible only if
some eligible fact reaches L1 for it.

**Yasunari Kawabata (rank 2) and Masatoshi Koshiba (rank 3) are covered by zero
eligible facts at L1.** Their coverage bitsets over the 55 eligible facts are
empty. No subset of facts — of any cardinality, in any combination — can cover
an empty bitset. The combination `{1, 2, 3}` is therefore **infeasible at
main-L1 by construction**, not merely expensive or unlucky.

Their sole non-L0 evidence is a `NOT_COVERED`: both share
`dbp:almaMater → University_of_Tokyo` with Satō (`EV[2]`,
`reason_code = NOT_COVERED_EXACT_EQUAL`). That is the opposite of
distinguishing evidence — the fact confirms they resemble the Answer. Every
other eligible fact yields `L0_ABSENCE_ONLY_OBSERVED`, i.e. the snapshot simply
records nothing for them under that predicate and direction. Under the Open-World
Assumption, absence is not falsity, so those 54 L0 incidences may not be used as
a reason shown to a student.

The same test decides the other five zero-coverage candidates (ranks 4, 21–24).

### The provisional triple *is* feasible at the diagnostic policy

`CS.per_policy["diagnostic-l0"]` reports `feasible_combination_count = 2024` —
every combination — with `best_partial` = ranks `[1, 2, 3]`, `coverage_mask = 7`,
`minimum_rationale_size = 1`. So the provisional top three could be "covered" by
a single fact **if absence counted as evidence**. It does not. The policy order
is `strict-l2 → main-l1 → diagnostic-l0`, and `main-l1` is feasible, so
`diagnostic-l0` is never reached.

`CS.per_policy["strict-l2"]`: `candidates_with_any_coverage = 0`,
`feasible_combination_count = 0`. There are **no L2 incidences anywhere** in the
pilot — no `EvidenceProof` source exists offline. Zero is the correct outcome,
not a gap.

---

## 4. Why the selection is ranks 1, 5, 6

### Step 1 — the feasible set

`CS.enumerated_combination_count = 2024 = C(24, 3)`, all enumerated
(`search_scope = FULL_EXACT`, `global_optimality_claim = true`, so no pool
truncation applies).

| policy | feasible (full coverage, \|R*\| ≤ 3) |
|---|---:|
| `strict-l2` | 0 |
| **`main-l1`** | **680** |
| `diagnostic-l0` | 2024 |

680 matches `CS.per_policy["main-l1"].full_coverage_combination_count`, and is
re-derived independently. `main-l1` is the first feasible policy, so it is
selected: `SEL.evidence_policy = "main-l1"`.

### Step 2 — objective keys 1 and 2 restrict to the covered candidates

A feasible combination may only use the 17 candidates with non-empty coverage.
The three largest LRoleSim scores among those 17 are ranks 1, 5 and then the
exact three-way tie at ranks 6/7/8. Hence the maximum attainable
`lrolesim_score_sum` over feasible combinations is

```
0.22190222222222222  (rank 1, Ei-ichi Negishi)
0.20836497625830960  (rank 5, Hideki Shirakawa)
0.20696461464461466  (rank 6 = rank 7 = rank 8)
-------------------
0.63723181312514650  = SEL.lrolesim_score_sum
```

with `score_min = 0.20696461464461466 = SEL.lrolesim_score_min`. Ranks 2, 3 and
4 carry higher scores but are unusable, which is precisely the cost the search
pays to obtain grounded evidence.

### Step 3 — key 3 gives |R*| = 2

For the three surviving combinations `{1,5,6}`, `{1,5,7}`, `{1,5,8}` the exact
bitmask set cover returns `minimum_rationale_size = 2`
(`SEL.minimum_rationale_size = 2`). §5 proves this is optimal, not merely
achieved.

### Step 4 — keys 1–4 tie three ways; key 5 decides

The three combinations are tied on keys 1, 2 and 3 (identical score sum,
identical score min, identical \|R*\|) **and** on key 4: each yields the same
14-field rationale ranking key

```
(-2, 0, -3, 0, 0, 0, 0, 4, 1, 31, 5, 0, 1,
 (('…/property/almaMater', 'OUT', '…/resource/University_of_Tokyo'),
  ('…/property/before',    'IN',  '…/resource/Kiichi_Aichi')))
```

reading: rationale min level L1 (`-2`); 0 L2 incidences; 3 L1 coverage
incidences (`-3`); 0 L0; 0 scoped-empirical; 0 granularity risk; 0 soft leaks;
pedagogical tier sum 4; 1 unverbalizable fact; label length sum 31; token count
sum 5; 0 redundant predicate-key pairs; direct-identifier flag set.

Objective key 5, `candidate_rank_sum`, then separates them:

| combination | ranks | `rank_sum` | outcome |
|---|---|---:|---|
| Ei-ichi Negishi, Hideki Shirakawa, **Isamu Akasaki** | 1, 5, 6 | **12** | **selected** |
| Ei-ichi Negishi, Hideki Shirakawa, Ryōji Noyori | 1, 5, 7 | 13 | rejected |
| Ei-ichi Negishi, Hideki Shirakawa, Shin'ichirō Tomonaga | 1, 5, 8 | 14 | rejected |

`SEL.candidate_rank_sum = 12`, `SEL.replaced_provisional_top3 = true`,
`SEL.distractors` = Ei-ichi Negishi (rank 1, `in_provisional_lrolesim_top3=true`),
Hideki Shirakawa (rank 5, `false`), Isamu Akasaki (rank 6, `false`).

Eisaku Satō is the **only** one of the eight pilot Answers whose selection
reaches objective key 5 at all; see `RANK_SUM_EFFECT_AUDIT.md`.

---

## 5. The per-fact masks under the selected candidate order

Candidate order is the selected combination's position order, so bit *i* tracks
the *i*-th distractor:

```
bit 0 = Ei-ichi Negishi    (rank 1)
bit 1 = Hideki Shirakawa   (rank 5)
bit 2 = Isamu Akasaki      (rank 6)
```

### Fact `EV[2]` — `dbp:almaMater` (OUT) → `University_of_Tokyo`

| bit | candidate | observed objects `O_d(κ)` | level | reason |
|---:|---|---|---|---|
| 0 | Ei-ichi Negishi | `University_of_Pennsylvania`, **`University_of_Tokyo`** | `NOT_COVERED` | `NOT_COVERED_EXACT_EQUAL` — he *also* attended it |
| 1 | Hideki Shirakawa | `Tokyo_Institute_of_Technology` | **`L1`** | observed alternative value |
| 2 | Isamu Akasaki | `Kyoto_University`, `Nagoya_University` | **`L1`** | observed alternative value |

```
mask(EV[2]) = 0b110 = 6
```

### Fact `EV[3]` — `dbp:before` (IN) → `Kiichi_Aichi`

| bit | candidate | observed objects `O_d(κ)` | level | reason |
|---:|---|---|---|---|
| 0 | Ei-ichi Negishi | `Dan_Shechtman` | **`L1`** | observed alternative value |
| 1 | Hideki Shirakawa | ∅ | `L0` | `L0_ABSENCE_ONLY_OBSERVED` |
| 2 | Isamu Akasaki | ∅ | `L0` | `L0_ABSENCE_ONLY_OBSERVED` |

```
mask(EV[3]) = 0b001 = 1
```

### The bitwise OR

```
  mask(EV[2])  =  0b110   (6)    covers Shirakawa, Akasaki
  mask(EV[3])  =  0b001   (1)    covers Negishi
  ---------------------------- OR
  coverage     =  0b111   (7)    FULL COVERAGE
```

`SEL.coverage_mask = 7`, `SEL.coverage_count = 3`, `SEL.full_coverage = true`,
matching `CS.alternative_minimum_rationales[0].coverage_masks = [1, 6]`.

The two facts are **exactly complementary**: `almaMater` cannot reach Negishi
because he shares the Answer's value, and `before` cannot reach Shirakawa or
Akasaki because the snapshot records nothing for them under that key. Neither
fact alone suffices, and together they suffice with nothing to spare.

---

## 6. Proof that no one-fact main-L1 rationale exists for this combination

**Claim.** For the combination `{Ei-ichi Negishi, Hideki Shirakawa, Isamu
Akasaki}`, no single eligible Answer fact covers all three at main-L1.

**Proof.** Enumerate the main-L1 coverage mask of **every one of the 55 eligible
facts** over this combination. Exactly two are non-zero:

| `fact_index` | predicate | dir | object | mask |
|---:|---|---|---|---|
| 2 | `dbp:almaMater` | OUT | `University_of_Tokyo` | `0b110` |
| 3 | `dbp:before` | IN | `Kiichi_Aichi` | `0b001` |

The remaining 53 eligible facts have mask `0b000`: they reach L1 for none of the
three. The full set of achievable masks is therefore `{0b000, 0b001, 0b110}`,
and `0b111 ∉ {0b000, 0b001, 0b110}`. A one-fact rationale would require a fact
of mask `0b111`. None exists, so `|R*| ≥ 2`. Section 5 exhibits a cover of size
2, so **`|R*| = 2` exactly**. ∎

This is exhaustive over the whole eligible fact set, not a heuristic or a
search cut-off. The bitmask DP returns the same value:
`cover_size_table({1, 6})[0b111] = 2`.

Verified by
`tests/test_spec_freeze_audit.py::test_sato_has_no_one_fact_main_l1_rationale`
and `::test_sato_selected_combination_masks_or_to_full_coverage`.

**Consequence for corpus eligibility.** `EV[3]`
(`dbp:before` IN → `Kiichi_Aichi`) has `template_id = VERBALIZABLE_UNKNOWN`,
`verbalizable = false`, `pedagogical_tier = 3`. Because \|R*\| = 2 forces that
fact into the rationale, `SEL.eligible_for_main_corpus = false` while
`SEL.eligible_for_diagnostic_corpus = true` and
`SEL.mcq_evidence_level = "MCQ-L1"`. The blocker is a **missing verbalization
template**, not the evidence level and not the class selection — which is why R1
raised no fallback-class request here.

---

## 7. Combinations enumerated, and the objective values

| Quantity | Value | Source |
|---|---:|---|
| candidates | 24 | `CS.candidate_count` |
| combinations enumerated | **2024** = C(24,3) | `CS.enumerated_combination_count` |
| combinations feasible at `strict-l2` | 0 | `CS.per_policy` |
| combinations feasible at **`main-l1`** | **680** | `CS.per_policy` |
| combinations feasible at `diagnostic-l0` | 2024 | `CS.per_policy` |
| minimum-cardinality rationales enumerated for the winner | 1 | `SEL.minimum_rationale_count_enumerated`, scope `COMPLETE` |

Objective values of the selected combination:

| Key | Field | Value |
|---:|---|---|
| 1 | `lrolesim_score_sum` | `0.6372318131251465` |
| 2 | `lrolesim_score_min` | `0.20696461464461466` |
| 3 | `minimum_rationale_size` | `2` |
| 4 | rationale ranking key | `(-2, 0, -3, 0, 0, 0, 0, 4, 1, 31, 5, 0, 1, …)` |
| 5 | `candidate_rank_sum` | `12` |
| 6 | `candidate_uris` | `(Ei-ichi_Negishi, Hideki_Shirakawa, Isamu_Akasaki)` |

Reported alongside: `mcq_evidence_level = MCQ-L1`, per-distractor levels
`L1 | L1 | L1`, `exclusion_basis = NONE`, `semantic_check_status = CLOSURE_RAN`,
`granularity_risk` incidences `0`, `local_candidate_pool_anonymity_count = 1`,
`direct_identifier_flag = true`.

---

## 8. Nearest competing feasible combinations

All 680 feasible `main-l1` combinations were re-ranked under the full objective.
For each competitor, the **first** objective field on which it loses:

| # | ranks | `rank_sum` | \|R*\| | first losing field | winner vs competitor |
|---:|---|---:|---:|---|---|
| 1 | 1, 5, 7 | 13 | 2 | **key 5 `candidate_rank_sum`** | `12` vs `13` |
| 2 | 1, 5, 8 | 14 | 2 | **key 5 `candidate_rank_sum`** | `12` vs `14` |
| 3 | 1, 5, 9 | 15 | 2 | key 1 `-lrolesim_score_sum` | `-0.6372318131251465` vs `-0.6367560873694207` |
| 4 | 1, 5, 10 | 16 | 2 | key 1 `-lrolesim_score_sum` | `-0.6372318131251465` vs `-0.6367560873694207` |
| 5 | 1, 5, 11 | 17 | 2 | key 1 `-lrolesim_score_sum` | `-0.6372318131251465` vs `-0.6364259470338425` |
| 6 | 1, 5, 12 | 18 | 2 | key 1 `-lrolesim_score_sum` | `-0.6372318131251465` vs `-0.6364259470338425` |

Only competitors 1 and 2 survive as far as key 5; every other feasible
combination is already eliminated at key 1. The winner's margin over competitor
3 is `4.757e-4` in score sum — small in magnitude, but an exact float
inequality, so the ordering is deterministic and reproducible.

Note that competitors 1 and 2 are **equally good on every scientific criterion**
the objective encodes: same LRoleSim score sum and minimum, same rationale
cardinality, same evidence profile, same rationale facts. The choice among them
is genuinely arbitrary from an evidence standpoint, and `rank_sum` supplies a
deterministic, ranking-aligned resolution rather than an alphabetical one.

---

## 9. Summary

1. The provisional LRoleSim top three fails because ranks 2 and 3 have **zero**
   L1-covering eligible facts — their only non-absence evidence is that they
   *share* `University_of_Tokyo` with the Answer.
2. Ranks 1, 5, 6 is the highest-scoring feasible combination, tied exactly with
   ranks 1, 5, 7 and 1, 5, 8 because ranks 6, 7 and 8 form an exact LRoleSim tie
   group; `candidate_rank_sum` breaks that tie at 12.
3. \|R*\| = 2 is provably minimal: only two of 55 eligible facts have any
   main-L1 coverage of this triple, with masks `0b110` and `0b001`, OR-ing to
   `0b111`.
4. The item is diagnostic-corpus eligible but not main-corpus eligible, solely
   because `dbp:before` has no verbalization template.
5. Every level in this trace is an **observation about the pinned snapshot**.
   L1 records an observed alternative value; it does not assert that Shirakawa
   or Akasaki could not also have attended the University of Tokyo. `almaMater`
   is multi-valued — Negishi's own record carries two values — so the
   open-world caveat is not hypothetical here.
