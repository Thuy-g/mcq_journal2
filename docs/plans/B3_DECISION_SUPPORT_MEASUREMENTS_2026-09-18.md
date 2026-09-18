# B3 decision-support measurements — offline development batches

**Prompt** 8H-B3-ARCH-3 · **Date** 2026-09-18
**Status** DEVELOPMENT MEASUREMENTS ONLY. Not a final benchmark, not a
publication result, not production B3 code. Nothing here signs a human
decision; the `RECORDED DECISION` lines of
`B3_HUMAN_DECISION_MEMO_2026-09-18.md` are untouched.
**Evidence package** `outputs/journal2_b3_decision_support_2026-09-18/`
(ZIP: `outputs/journal2_b3_decision_support_2026-09-18.zip`, validated with
`testzip()`); machine-readable digest of this document:
`B3_DECISION_SUPPORT_MEASUREMENTS_2026-09-18.summary.json`.
**Script** `scripts/audit_b3_choice_evidence_decisions.py` — labelled
AUDIT / DECISION SUPPORT ONLY; no `src/choice_evidence_v1/` was created.
**Terminology authority** `docs/context/EVIDENCE_TAXONOMY_V1.md`.

---

## 0. What was measured, on what, and what was not touched

The two 2026-09-18 development batches (`data/Answers.txt`, 329 unique
Answers; `data/Answers_HISTORICAL_EVENTS_PLACES.txt`, 189) were replayed
**offline** through the frozen v4 runner into the evidence directory, with
private copies of the four offline caches so the originals were never opened
for writing. The replay reproduces the 2026-09-18 batch reports item by item
(§1). Every measurement then reads the replayed artefacts and the pinned KG
read-only. The selected Answer, the selected class, the selected distractors,
the frozen LRoleSim ranks and scores, the frozen evidence levels, the frozen
`R*` and every open-world rule are consumed as given and nothing is fed back.
No network access occurred: `--offline-replay` raises on any cache miss.

Six decisions of the ARCH-2 memo were given empirical support:

| decision | measurement | section |
|---|---|---|
| H14 pre-answer admissibility | arms A (ARCH-1 penalty-style) / B (ARCH-2 grounding-clean) / C (B + no A-excluding support-3), plus two informative variants | §3 |
| H5 require-verbalizable | kernel replay + counterfactual re-selection through the frozen kernel, nothing changed | §4 |
| H13 objective formulation | exact lexicographic 0-1 optimisation, adjacent-key swaps, comparators | §5 |
| H7 / H3 / H4 exposure and budgets | `B_pre` × `B_post` × `K_A_post` sweep, class as caption vs budget-exempt node | §6 |
| H18 universe bounding | modular pre-key vs stratified bounding, `N_max` ∈ {100, 200, 400, 800, FULL}, stability at doubling | §7 |
| H6 solver | HiGHS via `scipy.optimize.milp` on the actual instances, certificates, pure-Python re-check, exhaustive oracle, deterministic rerun | §8 |

**Vocabulary discipline.** A missing edge is snapshot silence, never
falsity. `ABSENCE_ONLY` is the presentation analogue of `L0` and is never
downgraded from `UNRESOLVED`. No structural quantity below is human
difficulty. Every rate carries its denominator. Measured results are marked
**Measured**; the reviewer's readings are marked **Reading** and are not
decisions.

### 0.1 The audit universe (what one item looks like to the audit)

For each learner-facing main-L1 item the audit builds, from the pinned KG,
every observed one-hop fact edge of the four choices (letters `A` = Answer,
`B/C/D` = distractors in kernel position order), assesses each edge with the
frozen quality function (same policy file; the CSV eligibility verdict is
re-verified), groups edges into clue groups `(alias-family key, canonical
counterpart)`, and annotates every non-support letter of every group with a
**grounding** value and a **risk** value:

* Answer-owned groups against a distractor: the frozen level is copied
  (`NOT_COVERED` → `SHARED_BY_CONTAINMENT` when the letter owns no edge to the
  node, `L1` → `ALTERNATIVE_OBSERVED` with the frozen risk, `L0` →
  `ABSENCE_ONLY`);
* every other pair: the ARCH-2 rule, which mirrors the frozen classifier step
  by step (nothing observed → `ABSENCE_ONLY`; index unavailable →
  `UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE`; any supporting relation →
  `SHARED_BY_CONTAINMENT`; else `ALTERNATIVE_OBSERVED` with risk
  `CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT` / `HIERARCHY_NOT_MODELLED` / `NONE`),
  over a B3 semantic index built for the counterparts of all four choices
  under its own cache key (§1.2).

The rule's agreement with the frozen classifier is itself measured on the
Answer-owned pairs (§1.2). Tiers follow ARCH-1 §5.3: `MANDATORY_RATIONALE`
(the `R*` groups), `RATIONALE_ALTERNATIVE` (a distractor's observed
alternative value under a covering `R*` key), `OPTIONAL_CONTEXT`, `EXCLUDED`
(ineligible predicate/object, Answer-label hard leak, option reference,
self-loop, class duplicate). The class frame sits outside every budget.

### 0.2 The designated audit configuration

Declared before any number was seen, not chosen from human data:
`B_pre = 4` optional clue groups, `B_post = 7` ENTITY right nodes,
`K_A_pre = 0`, `K_A_post = 1`, alternatives OFF before answering and REQUIRED
after where showable, stratified bounding at `N_max = 400` for H13/H7, the
ARCH-2 candidate key orders (pre: uncovered letters, shared information,
distinct keys, clue groups, tier sum, tokens; post: `ABSENCE_ONLY`
incidences, risk-bearing groups, shared information, distinct keys, ENTITY
nodes, tier sum, tokens), canonical order last. All of it is in
`run_manifest.json`.


---

## 1. Replay verification, gate and universe validation (Measured)

**Replay = report, item by item.** Both replayed batches reproduce the
2026-09-18 batch tables on every compared column (status, class, pool size,
distractors with ranks, `|R*|`, rationale facts, per-distractor levels, MCQ
level, risk, option-reference count): `answers` 329/329 matched, 0
mismatched, 0 missing; `hist` 189/189 matched, 0 mismatched, 0 missing
(`replay_verification.csv`).

**Gate.** Of 518 Answer rows, 396 pass the learner-facing main-L1 gate.
The 122 that do not are v4 outcomes, not B3 decisions: `NO_ARTIFACT_DIR` 4, `STATUS_AMBIGUOUS_LOCAL_ALIAS` 2, `STATUS_GRAPH_INFEASIBLE` 43, `STATUS_NO_LOCALLY_MAPPING_FEASIBLE_CLASS` 7, `STATUS_NO_LOCAL_URI_IDENTITY` 21, `STATUS_NO_MAIN_L1_SELECTION` 39, `STATUS_NO_USABLE_CLASS` 1, `STATUS_NO_VALID_FINAL_COMBINATION` 5.

**Kernel replay.** The frozen kernel, fed the `AnswerCase` rebuilt from the
artefacts (quality recomputed by the frozen pure function, levels copied),
reproduces the recorded distractor triple, rationale identities and evidence
policy for **396/396** items; the artefacts' `verbalizable` flags agree with
the kernel's rationale in 396/396; eligibility recomputation disagreed with
the CSV verdict on 0 facts.

**Universe and grounding validation.** The ARCH-2 grounding rule, computed
with the audit's own B3 index, reproduces the frozen level-derived grounding
and risk on **282,933 of 282,933** Answer-owned (group, distractor) pairs.
The Answer's one-hop enumeration equals the CSV fact inventory in 396/396
items, and the B3 index was available for 396/396 items.

| group | items | groups mean | optional mean / median / max | excluded mean | index available | Answer enumeration = CSV | grounding rule = frozen level (pairs) | risk equal | items with an (R* fact, distractor) absence incidence | alt-unshowable items | mandatory nodes mean |
|---|---:|---:|---|---:|---|---|---|---|---|---|---:|
| POOLED | 396 | 423.1389 | 360.096 / 65.5 / 4921 | 28.5354 | 396/396 (100.0%) | 396/396 (100.0%) | 282933/282933 (100.0%) | 282933/282933 (100.0%) | 55/396 (13.89%) | 32/396 (8.08%) | 1.1515 |
| GROUP:CHEMISTRY | 40 | 105.625 | 58.2 / 15.5 / 777 | 6.375 | 40/40 (100.0%) | 40/40 (100.0%) | 4574/4574 (100.0%) | 4574/4574 (100.0%) | 7/40 (17.5%) | 1/40 (2.5%) | 1.225 |
| GROUP:EVENT | 34 | 342.6471 | 280.6765 / 57.5 / 2513 | 11.3235 | 34/34 (100.0%) | 34/34 (100.0%) | 22787/22787 (100.0%) | 22787/22787 (100.0%) | 6/34 (17.65%) | 1/34 (2.94%) | 1.1765 |
| GROUP:PERSON | 240 | 135.4042 | 107.8458 / 55.0 / 1338 | 15.5083 | 240/240 (100.0%) | 240/240 (100.0%) | 38057/38057 (100.0%) | 38057/38057 (100.0%) | 35/240 (14.58%) | 26/240 (10.83%) | 1.1583 |
| GROUP:PLACE | 47 | 1641.1277 | 1491.2128 / 750 / 4921 | 81.383 | 47/47 (100.0%) | 47/47 (100.0%) | 146657/146657 (100.0%) | 146657/146657 (100.0%) | 3/47 (6.38%) | 2/47 (4.26%) | 1.0638 |
| GROUP:POLITY | 35 | 1201.6571 | 993.0571 / 401 / 4835 | 88.9429 | 35/35 (100.0%) | 35/35 (100.0%) | 70858/70858 (100.0%) | 70858/70858 (100.0%) | 4/35 (11.43%) | 2/35 (5.71%) | 1.1143 |
| BATCH:answers | 280 | 131.15 | 100.7536 / 45.0 / 1338 | 14.2036 | 280/280 (100.0%) | 280/280 (100.0%) | 42631/42631 (100.0%) | 42631/42631 (100.0%) | 42/280 (15.0%) | 27/280 (9.64%) | 1.1679 |
| BATCH:hist | 116 | 1127.9397 | 986.0948 / 266.5 / 4921 | 63.1293 | 116/116 (100.0%) | 116/116 (100.0%) | 240302/240302 (100.0%) | 240302/240302 (100.0%) | 13/116 (11.21%) | 5/116 (4.31%) | 1.1121 |

**Reading.** The audit universe is faithful to the frozen record where the
two overlap, so the distractor-owned grounding (which has no frozen
counterpart) is computed by a rule that is empirically identical to the
classifier on every pair where both exist. Two structural facts of the
development data are visible already: places and polities have IN-heavy
universes an order of magnitude larger than persons (median optional groups
750 and 401 versus 55), and `|R*|` is 1 for 338 items, 2 for 54 and 3 for 4.
The mixed `L1`/`L0` case of ARCH-2 §4.3 (an `R*` fact at `L0` for some
distractor) occurs in **55/396 items (13.9 %)**, 145 incidences, all with
`|R*| ≥ 2` (51 with `|R*| = 2`, 4 with `|R*| = 3`): the residual is real
and now has a number.

---

## 2. Measurement A — H14 pre-answer admissibility arms (Measured)

Arms over the complete `OPTIONAL_CONTEXT` tier of every item (142,598 optional
groups; `K_A = 0` in every arm):

* **A_arch1_penalty** — the ARCH-1 screens only: eligible, verbalizable, not
  Answer-only. Singletons, `ABSENCE_ONLY`, risk, unresolved and
  distractor-label groups stay admissible (they were penalties).
* **B_arch2_hard** — the ARCH-2 rule: support ≥ 2; every non-support letter
  `ALTERNATIVE_OBSERVED`; no `SHARED_BY_CONTAINMENT`; no `UNRESOLVED`;
  granularity risk `NONE` (literally: `CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT`,
  `HIERARCHY_NOT_MODELLED` and `UNRESOLVED` all refuse); verbalizable; no
  Answer-label and no distractor-label leak.
* **B_tolerate_unmodelled** (informative) — B, but `HIERARCHY_NOT_MODELLED`
  tolerated (the `require-clean` "tolerated state" reading).
* **C_no_A_excluding_support3** — B plus no optional group with support
  exactly `{B, C, D}`.
* **C2_no_A_excluding_any** (informative) — B plus no optional group that
  excludes `A` at any support size.

| arm | optional before | admissible after | retained | mean/median per item | items ≥1 | items ≥2 | items ≥3 | mandatory-only | by support 2/3/4 | items with A-excluding s=3 survivor |
|---|---:|---:|---|---|---|---|---|---|---|---|
| A_arch1_penalty | 142598 | 9767 | 9767/142598 (6.85%) | 24.6641 / 10.0 | 326/396 (82.32%) | 299/396 (75.51%) | 286/396 (72.22%) | 70/396 (17.68%) | 931/210/110 | 28/396 (7.07%) |
| B_arch2_hard | 142598 | 724 | 724/142598 (0.51%) | 1.8283 / 0.0 | 132/396 (33.33%) | 91/396 (22.98%) | 63/396 (15.91%) | 264/396 (66.67%) | 483/135/106 | 11/396 (2.78%) |
| B_tolerate_unmodelled | 142598 | 737 | 737/142598 (0.52%) | 1.8611 / 0.0 | 137/396 (34.6%) | 95/396 (23.99%) | 64/396 (16.16%) | 259/396 (65.4%) | 492/139/106 | 11/396 (2.78%) |
| C2_no_A_excluding_any | 142598 | 533 | 533/142598 (0.37%) | 1.346 / 0.0 | 124/396 (31.31%) | 71/396 (17.93%) | 44/396 (11.11%) | 272/396 (68.69%) | 308/119/106 | 0/396 (0.0%) |
| C_no_A_excluding_support3 | 142598 | 708 | 708/142598 (0.5%) | 1.7879 / 0.0 | 132/396 (33.33%) | 90/396 (22.73%) | 61/396 (15.4%) | 264/396 (66.67%) | 483/119/106 | 0/396 (0.0%) |

| reason | groups |
|---|---:|
| `SUPPORT_BELOW_2` | 136446 |
| `UNVERBALIZABLE` | 127987 |
| `ANSWER_ONLY_K_A_0` | 82621 |
| `ABSENCE_ONLY_LETTER` | 59168 |
| `DISTRACTOR_LABEL_LEAK` | 7355 |
| `GRANULARITY_RISK_HIERARCHY_UNMODELLED` | 166 |
| `GRANULARITY_RISK_CLAIM_UNDER_CANDIDATE` | 88 |
| `SHARED_BY_CONTAINMENT_LETTER` | 44 |

| group | items | arm A | arm B | arm B-tolerate-unmodelled | arm C | arm C2 (no A-excluding at all) | arm B mandatory-only |
|---|---:|---|---|---|---|---|---|
| POOLED | 396 | 326/396 (82.32%) | 132/396 (33.33%) | 137/396 (34.6%) | 132/396 (33.33%) | 124/396 (31.31%) | 264/396 (66.67%) |
| GROUP:CHEMISTRY | 40 | 28/40 (70.0%) | 5/40 (12.5%) | 5/40 (12.5%) | 5/40 (12.5%) | 4/40 (10.0%) | 35/40 (87.5%) |
| GROUP:EVENT | 34 | 11/34 (32.35%) | 0/34 (0.0%) | 0/34 (0.0%) | 0/34 (0.0%) | 0/34 (0.0%) | 34/34 (100.0%) |
| GROUP:PERSON | 240 | 240/240 (100.0%) | 118/240 (49.17%) | 123/240 (51.25%) | 118/240 (49.17%) | 111/240 (46.25%) | 122/240 (50.83%) |
| GROUP:PLACE | 47 | 14/47 (29.79%) | 0/47 (0.0%) | 0/47 (0.0%) | 0/47 (0.0%) | 0/47 (0.0%) | 47/47 (100.0%) |
| GROUP:POLITY | 35 | 33/35 (94.29%) | 9/35 (25.71%) | 9/35 (25.71%) | 9/35 (25.71%) | 9/35 (25.71%) | 26/35 (74.29%) |
| BATCH:answers | 280 | 268/280 (95.71%) | 123/280 (43.93%) | 128/280 (45.71%) | 123/280 (43.93%) | 115/280 (41.07%) | 157/280 (56.07%) |
| BATCH:hist | 116 | 58/116 (50.0%) | 9/116 (7.76%) | 9/116 (7.76%) | 9/116 (7.76%) | 9/116 (7.76%) | 107/116 (92.24%) |

| quantity | count |
|---|---:|
| `abs` | 118085 |
| `alt` | 301019 |
| `cont` | 60 |
| `groups_A_excluding_any` | 55357 |
| `groups_A_excluding_support3` | 183 |
| `groups_answer_only` | 82621 |
| `groups_dl` | 7355 |
| `groups_singleton` | 136446 |
| `groups_unverbalizable` | 127987 |
| `groups_with_abs` | 59168 |
| `groups_with_cont` | 44 |
| `groups_with_risk` | 254 |
| `groups_with_unres` | 0 |
| `risk_present` | 123 |
| `risk_unmod` | 358 |
| `risk_unres` | 0 |
| `unres` | 0 |

**Decomposition of the arm-B cost (Measured).** The optional tier is
dominated by two properties that no arm can repair: 127,987 of 142,598
optional groups (89.8 %) have no template, and 136,446 (95.7 %) are
singletons. Items with at least one shared (support ≥ 2), verbalizable,
non-Answer-only optional group — the material that any pre-answer context
policy can work with — number **229/396**. Of those 229, arm B leaves
**97** with no admissible group; over the shared verbalizable groups of
those 97 items the first failing arm-B reason is `ABSENCE_ONLY_LETTER` for
181 groups, `HIERARCHY_NOT_MODELLED` for 6 and `DISTRACTOR_LABEL_LEAK` for 4.
Under arm B the admissible-count distribution is 0 for 264 items, 1 for 41,
2 for 28, 3 for 10, 4 for 12 and ≥ 5 for 41. Places (0/47) and events (0/34)
have no arm-B-admissible pre-answer context at all; persons keep it in
118/240.

**A-excluding support-3 groups (Measured).** They survive arm B in 11/396
items (16 groups). Forbidding them (arm C) therefore changes nothing for
385 items and removes the last admissible group in 0 items (arm C keeps
132/396 items ≥ 1, the same as arm B). Forbidding every A-excluding group
(C2) costs 8 more items (124/396).

**Reading.** The grounding-clean rule's own cost, separated from the
template gap and the singleton structure, is 97 of the 229 items that have
shared verbalizable context, almost entirely through `ABSENCE_ONLY` letters.
Whether that cost is acceptable is memo H14 and remains the researcher's;
what the measurement settles is that (i) the pre-answer context problem is
first a template-coverage problem, (ii) `HIERARCHY_NOT_MODELLED` tolerance
buys 5 items and containment/claim-under-candidate risks are rare (2 and 1
first-failing groups), and (iii) arm C is free relative to B. Nothing here
implies that arm B is publication-final because 132 items keep context; a
policy that leaves two thirds of items with clue sets of "class frame +
`R*`" is a design fact the human must weigh against the open-world argument
of the review.

---

## 3. Measurement B — H5 require-verbalizable cost (Measured)

Counterfactual audit only: the recorded `R*` is never altered; the frozen
kernel is re-run through `select_with_rationale_filter` with the predicate
"every rationale fact has a template", at the same evidence policy, with
`|R*|` fixed by the exact set cover per triple. A result at a weaker policy
is refused. The kernel calls carry a declared time budget (240 s for the
baseline replay, 120 s each for the same-triple enumeration and the
counterfactual); a timeout is a recorded outcome.

| group | items | kernel replay match | R* fully verbalizable | items LOST under require-verbalizable (no fully verbalizable min-card solution at main-l1) | rationale-only change | distractors change | same-triple verbalizable alternative exists (of not-fully-verbalizable) |
|---|---:|---|---|---|---|---|---|
| POOLED | 396 | 396/396 (100.0%) | 220/396 (55.56%) | 100/396 (25.25%) | 7/396 (1.77%) | 55/396 (13.89%) | 7/176 (3.98%) |
| GROUP:CHEMISTRY | 40 | 40/40 (100.0%) | 10/40 (25.0%) | 19/40 (47.5%) | 0/40 (0.0%) | 11/40 (27.5%) | 0/30 (0.0%) |
| GROUP:EVENT | 34 | 34/34 (100.0%) | 1/34 (2.94%) | 30/34 (88.24%) | 0/34 (0.0%) | 2/34 (5.88%) | 0/33 (0.0%) |
| GROUP:PERSON | 240 | 240/240 (100.0%) | 207/240 (86.25%) | 8/240 (3.33%) | 5/240 (2.08%) | 20/240 (8.33%) | 5/33 (15.15%) |
| GROUP:PLACE | 47 | 47/47 (100.0%) | 0/47 (0.0%) | 36/47 (76.6%) | 0/47 (0.0%) | 3/47 (6.38%) | 0/47 (0.0%) |
| GROUP:POLITY | 35 | 35/35 (100.0%) | 2/35 (5.71%) | 7/35 (20.0%) | 2/35 (5.71%) | 19/35 (54.29%) | 2/33 (6.06%) |
| BATCH:answers | 280 | 280/280 (100.0%) | 217/280 (77.5%) | 27/280 (9.64%) | 5/280 (1.79%) | 31/280 (11.07%) | 5/63 (7.94%) |
| BATCH:hist | 116 | 116/116 (100.0%) | 3/116 (2.59%) | 73/116 (62.93%) | 2/116 (1.72%) | 24/116 (20.69%) | 2/113 (1.77%) |

| predicate/direction | items |
|---|---:|
| `affiliation/IN` | 1 |
| `after/IN` | 3 |
| `after/OUT` | 2 |
| `allegiance/IN` | 1 |
| `battles/IN` | 18 |
| `before/IN` | 1 |
| `before/OUT` | 3 |
| `birthPlace/IN` | 38 |
| `builder/IN` | 1 |
| `candidate/IN` | 1 |
| `canonizedBy/OUT` | 1 |
| `combatant/IN` | 1 |
| `combatant/OUT` | 3 |
| `commander/OUT` | 1 |
| `constituency/OUT` | 1 |
| `country/IN` | 1 |
| `cultCenter/IN` | 2 |
| `deathPlace/IN` | 13 |
| `dedication/IN` | 2 |
| `deity/IN` | 1 |
| `disease/OUT` | 1 |
| `dynasty/OUT` | 1 |
| `establishedEvent/IN` | 1 |
| `event/IN` | 2 |
| `eventStart/OUT` | 1 |
| `examples/IN` | 1 |
| `father/IN` | 1 |
| `field/IN` | 1 |
| `honorificPrefix/OUT` | 2 |
| `ideology/IN` | 1 |
| `including/IN` | 1 |
| `issue/OUT` | 1 |
| `language/OUT` | 1 |
| `leader/IN` | 2 |
| `leader/OUT` | 3 |
| `leaderName/OUT` | 4 |
| `location/OUT` | 2 |
| `monarch/IN` | 2 |
| `name/IN` | 2 |
| `northeast/OUT` | 1 |
| `othernames/OUT` | 1 |
| `partof/IN` | 3 |
| `place/OUT` | 1 |
| `postalCodeType/OUT` | 1 |
| `presidentCandidate/IN` | 1 |
| `product/IN` | 1 |
| `products/IN` | 26 |
| `regent/IN` | 4 |
| `regent/OUT` | 1 |
| `school/OUT` | 2 |
| `settlementType/OUT` | 6 |
| `spouse/IN` | 1 |
| `subdivisionName/OUT` | 2 |
| `subdivisionType/OUT` | 1 |
| `timezone/OUT` | 1 |
| `titleLeader/OUT` | 3 |
| `treatment/IN` | 1 |
| `type/IN` | 1 |
| `wars/IN` | 3 |
| `with/IN` | 1 |

**Reading.** 176/396 development items (44.4 %) carry an `R*` with at least
one template-less fact, and the cost is almost entirely outside the person
cohorts (places 47/47, events 33/34, polities 33/35, chemistry 30/40 versus
persons 33/240). Under a `require-verbalizable` policy as modelled here,
100/396 items (25.3 %) would have **no** fully verbalizable
minimum-cardinality solution at `main-l1` anywhere in the search scope,
55 (13.9 %) would keep a selection with a **different distractor triple**,
7 (1.8 %) would change only the rationale, and 14 (3.5 %, all in the
historical batch) could not be decided within the time budget. `|R*|` grew
in 5 of the 62 alternatives. The same-triple check shows how rarely a
verbalizable alternative exists for the recorded distractors (7/176): the
kernel already orders unverbalizable facts down (key 9), so when it picked
one there usually was no verbalizable cover of the same cardinality for that
triple. The unverbalizable keys are concentrated: `birthPlace/IN` (38 items),
`products/IN` (26), `battles/IN` (18), `deathPlace/IN` (13),
`settlementType/OUT` (6) — five keys account for 101 of the 176 items. The
measurement therefore supports the ARCH-2 reading of H5 that template
coverage expansion should precede the policy, and quantifies what the policy
alone would cost; whether to adopt the policy, expand templates, or exclude
items is the publication-configuration decision (CLAUDE.md step 1) and
remains the researcher's.

---

## 4. Measurement C — H13 lexicographic objective stability (Measured)

Exact 0-1 optimisation (HiGHS via `scipy.optimize.milp`, `mip_rel_gap = 0`),
sequential lexicographic solves with every ε = 0, block-lexicographic
canonical tie fix, pure-Python re-check of every selection, exhaustive oracle
where the free-group count is ≤ 16. Primary arm B; designated budgets;
stratified universe at `N_max = 400`. Adjacent swaps only.

| exposure | swap | selection changed | mean Jaccard | earliest key that differs |
|---|---|---|---:|---|
| pre | swap_0_1 | 0/396 (0.0%) | 1.0 | {} |
| pre | swap_1_2 | 5/396 (1.26%) | 0.9929 | {'neg_shared_information': 5} |
| pre | swap_2_3 | 0/396 (0.0%) | 1.0 | {} |
| pre | swap_3_4 | 0/396 (0.0%) | 1.0 | {} |
| pre | swap_4_5 | 0/396 (0.0%) | 1.0 | {} |
| post | swap_0_1 | 0/372 (0.0%) | 1.0 | {} |
| post | swap_1_2 | 14/372 (3.76%) | 0.9907 | {'risk_groups': 14} |
| post | swap_2_3 | 56/372 (15.05%) | 0.9412 | {'neg_shared_information': 56} |
| post | swap_3_4 | 58/372 (15.59%) | 0.9477 | {'neg_distinct_keys': 58} |
| post | swap_4_5 | 0/372 (0.0%) | 1.0 | {} |
| post | swap_5_6 | 4/372 (1.08%) | 0.9962 | {'tier_sum': 4} |

| group | pre swap_0_1 | pre swap_1_2 | pre swap_2_3 | pre swap_3_4 | pre swap_4_5 | post swap_0_1 | post swap_1_2 | post swap_2_3 | post swap_3_4 | post swap_4_5 | post swap_5_6 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| POOLED | 0/396 (0.0%) | 5/396 (1.26%) | 0/396 (0.0%) | 0/396 (0.0%) | 0/396 (0.0%) | 0/372 (0.0%) | 14/372 (3.76%) | 56/372 (15.05%) | 58/372 (15.59%) | 0/372 (0.0%) | 4/372 (1.08%) |
| GROUP:CHEMISTRY | 0/40 (0.0%) | 0/40 (0.0%) | 0/40 (0.0%) | 0/40 (0.0%) | 0/40 (0.0%) | 0/40 (0.0%) | 0/40 (0.0%) | 1/40 (2.5%) | 0/40 (0.0%) | 0/40 (0.0%) | 0/40 (0.0%) |
| GROUP:EVENT | 0/34 (0.0%) | 0/34 (0.0%) | 0/34 (0.0%) | 0/34 (0.0%) | 0/34 (0.0%) | 0/34 (0.0%) | 0/34 (0.0%) | 2/34 (5.88%) | 4/34 (11.76%) | 0/34 (0.0%) | 1/34 (2.94%) |
| GROUP:PERSON | 0/240 (0.0%) | 5/240 (2.08%) | 0/240 (0.0%) | 0/240 (0.0%) | 0/240 (0.0%) | 0/218 (0.0%) | 14/218 (6.42%) | 27/218 (12.39%) | 38/218 (17.43%) | 0/218 (0.0%) | 0/218 (0.0%) |
| GROUP:PLACE | 0/47 (0.0%) | 0/47 (0.0%) | 0/47 (0.0%) | 0/47 (0.0%) | 0/47 (0.0%) | 0/47 (0.0%) | 0/47 (0.0%) | 21/47 (44.68%) | 3/47 (6.38%) | 0/47 (0.0%) | 1/47 (2.13%) |
| GROUP:POLITY | 0/35 (0.0%) | 0/35 (0.0%) | 0/35 (0.0%) | 0/35 (0.0%) | 0/35 (0.0%) | 0/33 (0.0%) | 0/33 (0.0%) | 5/33 (15.15%) | 13/33 (39.39%) | 0/33 (0.0%) | 2/33 (6.06%) |

| comparison | value |
|---|---|
| `arch1_weighted_pre_absence_incidences_total` | 675 |
| `arch1_weighted_pre_items_exposing_absence` | 249/396 (62.88%) |
| `arch1_weighted_pre_items_exposing_singletons` | 178/396 (44.95%) |
| `arch1_weighted_vs_arm_A_lex_pre_identical` | 159/396 (40.15%) |
| `arch1_weighted_vs_arm_A_lex_pre_jaccard_mean` | 0.6446 |
| `arch1_weighted_vs_primary_post_jaccard_mean` | 0.5661 |
| `arch1_weighted_vs_primary_pre_identical` | 125/396 (31.57%) |
| `arch1_weighted_vs_primary_pre_jaccard_mean` | 0.4251 |
| `arm_A_lex_vs_primary_post_jaccard_mean` | 0.5303 |
| `arm_A_lex_vs_primary_pre_identical` | 92/396 (23.23%) |
| `arm_A_lex_vs_primary_pre_jaccard_mean` | 0.3313 |
| oracle | pre ran 389, agree 389; post ran 34, agree 34 |

**Reading.** Before answering, the candidate order is almost insensitive to
adjacent swaps: only the shared-information ↔ distinct-keys swap changes
anything (5/396). After answering, two swaps matter — shared information ↔
distinct keys (56/372, 15 %) and distinct keys ↔ ENTITY nodes (58/372,
15.6 %) — and they matter most for places (45 % for the first) and polities
(39 % for the second), where the IN-heavy universe offers many equally
shared groups under one key. The order among {`ABSENCE_ONLY`, risk} and
among {tier, tokens} is irrelevant on this data. The comparators quantify
the review's F-02 and F-05 findings on the same items: the ARCH-1 weighted
objective on the ARCH-1 admissibility exposes an `ABSENCE_ONLY` implicature
in the pre-answer clue set of **249/396 items (62.9 %)**, 675 incidences,
and a singleton clue in 178/396; its selections coincide with the
lexicographic selection on the same admissibility in only 159/396 items.
The lexicographic form is stable at the top of the key list; the two
post-answer swaps that move selections are exactly the pedagogical
trade-offs the memo's H13 asks the researcher to order. The exhaustive
oracle agreed with the solver on all 389 pre and all 34 post instances it
could enumerate.

---

## 5. Measurement D — H7 / H3 / H4 exposure and budget behaviour (Measured)

Method configuration held fixed: full `R*` mandatory before answering,
alternatives OFF before answering (main arm), REQUIRED after answering where
showable, `K_A_pre = 0`, `K_A_post ∈ {0, 1}`, class frame outside every
budget. Structural only; the class-as-node arm is the caption arm plus one
node and four edges.

| B_pre | mean selected | budget fully used | mandatory-only | every distractor has ≥1 optional clue | mean distinct keys (incl. R*) | mean tokens | mean new nodes |
|---:|---:|---|---|---|---:|---:|---:|
| 2 | 0.5631 | 91/396 (22.98%) | 264/396 (66.67%) | 95/396 (23.99%) | 1.6187 | 1.4167 | 0.5505 |
| 3 | 0.7222 | 63/396 (15.91%) | 264/396 (66.67%) | 96/396 (24.24%) | 1.6843 | 1.851 | 0.6995 |
| 4 | 0.8561 | 53/396 (13.38%) | 264/396 (66.67%) | 96/396 (24.24%) | 1.7222 | 2.1742 | 0.8258 |
| 5 | 0.9596 | 41/396 (10.35%) | 264/396 (66.67%) | 96/396 (24.24%) | 1.7449 | 2.4495 | 0.9217 |
| 6 | 1.0379 | 31/396 (7.83%) | 264/396 (66.67%) | 96/396 (24.24%) | 1.7525 | 2.6616 | 0.9975 |

| B_pre | B_post | selected | nested-infeasible | mand.>budget | mean nodes (caption / node arm) | mean edges (caption / node arm) | mand. share | mean optional | mean alt | COVER_ALT satisfied | every distractor has optional | items exposing ABSENCE_ONLY | mean abs | mean risk groups | min/max degree ratio |
|---:|---:|---|---|---|---|---|---:|---:|---:|---|---|---|---:|---:|---:|
| 2 | 10 | 396/396 (100.0%) | 0 | 0 | 6.4343 / 7.4343 | 13.0076 / 17.0076 | 0.2184 | 3.0556 | 2.952 | 1143/1143 (100.0%) | 169/396 (42.68%) | 55/396 (13.89%) | 0.4293 | 0.0253 | 0.5673 |
| 2 | 4 | 272/396 (68.69%) | 124 | 0 | 3.8346 / 4.8346 | 6.1985 / 10.1985 | 0.2868 | 0.7831 | 2.4044 | 779/1143 (68.15%) | 44/272 (16.18%) | 20/272 (7.35%) | 0.1654 | 0.0257 | 0.6732 |
| 2 | 5 | 346/396 (87.37%) | 50 | 0 | 4.4769 / 5.4769 | 7.896 / 11.896 | 0.2618 | 1.3064 | 2.552 | 993/1143 (86.88%) | 112/346 (32.37%) | 44/346 (12.72%) | 0.3757 | 0.0231 | 0.5991 |
| 2 | 6 | 394/396 (99.49%) | 2 | 0 | 5.0279 / 6.0279 | 9.4061 / 13.4061 | 0.2428 | 1.8147 | 2.6853 | 1137/1143 (99.48%) | 162/394 (41.12%) | 53/394 (13.45%) | 0.4188 | 0.0254 | 0.5943 |
| 2 | 7 | 396/396 (100.0%) | 0 | 0 | 5.4394 / 6.4394 | 10.5581 / 14.5581 | 0.2331 | 2.1869 | 2.7652 | 1143/1143 (100.0%) | 165/396 (41.67%) | 55/396 (13.89%) | 0.4293 | 0.0253 | 0.5854 |
| 2 | 8 | 396/396 (100.0%) | 0 | 0 | 5.8106 / 6.8106 | 11.5126 / 15.5126 | 0.2263 | 2.5076 | 2.8384 | 1143/1143 (100.0%) | 166/396 (41.92%) | 55/396 (13.89%) | 0.4293 | 0.0253 | 0.5775 |
| 2 | 9 | 396/396 (100.0%) | 0 | 0 | 6.1414 / 7.1414 | 12.3081 / 16.3081 | 0.2217 | 2.7929 | 2.899 | 1143/1143 (100.0%) | 169/396 (42.68%) | 55/396 (13.89%) | 0.4293 | 0.0253 | 0.5724 |
| 3 | 10 | 396/396 (100.0%) | 0 | 0 | 6.4343 / 7.4343 | 12.9949 / 16.9949 | 0.2184 | 3.0657 | 2.9394 | 1143/1143 (100.0%) | 169/396 (42.68%) | 55/396 (13.89%) | 0.4293 | 0.0253 | 0.5671 |
| 3 | 4 | 258/396 (65.15%) | 138 | 0 | 3.8256 / 4.8256 | 5.938 / 9.938 | 0.2888 | 0.686 | 2.469 | 744/1143 (65.09%) | 32/258 (12.4%) | 20/258 (7.75%) | 0.1744 | 0.0271 | 0.6826 |
| 3 | 5 | 334/396 (84.34%) | 62 | 0 | 4.4581 / 5.4581 | 7.6916 / 11.6916 | 0.2641 | 1.2575 | 2.5479 | 957/1143 (83.73%) | 101/334 (30.24%) | 44/334 (13.17%) | 0.3892 | 0.024 | 0.5974 |
| 3 | 6 | 365/396 (92.17%) | 31 | 0 | 4.9507 / 5.9507 | 9.1562 / 13.1562 | 0.2489 | 1.7342 | 2.6356 | 1050/1143 (91.86%) | 136/365 (37.26%) | 53/365 (14.52%) | 0.4521 | 0.0274 | 0.5918 |
| 3 | 7 | 396/396 (100.0%) | 0 | 0 | 5.4394 / 6.4394 | 10.5 / 14.5 | 0.2331 | 2.1894 | 2.7449 | 1143/1143 (100.0%) | 166/396 (41.92%) | 55/396 (13.89%) | 0.4293 | 0.0253 | 0.585 |
| 3 | 8 | 396/396 (100.0%) | 0 | 0 | 5.8106 / 6.8106 | 11.4848 / 15.4848 | 0.2263 | 2.5177 | 2.8232 | 1143/1143 (100.0%) | 166/396 (41.92%) | 55/396 (13.89%) | 0.4293 | 0.0253 | 0.5771 |
| 3 | 9 | 396/396 (100.0%) | 0 | 0 | 6.1414 / 7.1414 | 12.2955 / 16.2955 | 0.2217 | 2.8056 | 2.8838 | 1143/1143 (100.0%) | 169/396 (42.68%) | 55/396 (13.89%) | 0.4293 | 0.0253 | 0.5729 |
| 4 | 10 | 396/396 (100.0%) | 0 | 0 | 6.4343 / 7.4343 | 12.9899 / 16.9899 | 0.2184 | 3.0859 | 2.9217 | 1143/1143 (100.0%) | 169/396 (42.68%) | 55/396 (13.89%) | 0.4293 | 0.0253 | 0.5673 |
| 4 | 4 | 257/396 (64.9%) | 139 | 0 | 3.8249 / 4.8249 | 5.9027 / 9.9027 | 0.2889 | 0.6732 | 2.4786 | 744/1143 (65.09%) | 31/257 (12.06%) | 20/257 (7.78%) | 0.1751 | 0.0272 | 0.6824 |
| 4 | 5 | 322/396 (81.31%) | 74 | 0 | 4.4379 / 5.4379 | 7.4503 / 11.4503 | 0.2665 | 1.1739 | 2.587 | 923/1143 (80.75%) | 90/322 (27.95%) | 44/322 (13.66%) | 0.4037 | 0.0248 | 0.6018 |
| 4 | 6 | 352/396 (88.89%) | 44 | 0 | 4.9119 / 5.9119 | 8.8892 / 12.8892 | 0.2519 | 1.6562 | 2.6364 | 1011/1143 (88.45%) | 124/352 (35.23%) | 53/352 (15.06%) | 0.4688 | 0.0284 | 0.5898 |
| 4 | 7 | 372/396 (93.94%) | 24 | 0 | 5.3387 / 6.3387 | 10.172 / 14.172 | 0.2389 | 2.086 | 2.7043 | 1071/1143 (93.7%) | 142/372 (38.17%) | 55/372 (14.78%) | 0.457 | 0.0269 | 0.581 |
| 4 | 8 | 396/396 (100.0%) | 0 | 0 | 5.8106 / 6.8106 | 11.4369 / 15.4369 | 0.2263 | 2.5303 | 2.8005 | 1143/1143 (100.0%) | 166/396 (41.92%) | 55/396 (13.89%) | 0.4293 | 0.0253 | 0.5759 |
| 4 | 9 | 396/396 (100.0%) | 0 | 0 | 6.1414 / 7.1414 | 12.2803 / 16.2803 | 0.2217 | 2.8258 | 2.8662 | 1143/1143 (100.0%) | 169/396 (42.68%) | 55/396 (13.89%) | 0.4293 | 0.0253 | 0.5721 |
| 5 | 10 | 396/396 (100.0%) | 0 | 0 | 6.4343 / 7.4343 | 12.9848 / 16.9848 | 0.2184 | 3.096 | 2.9141 | 1143/1143 (100.0%) | 169/396 (42.68%) | 55/396 (13.89%) | 0.4293 | 0.0253 | 0.5676 |
| 5 | 4 | 257/396 (64.9%) | 139 | 0 | 3.8249 / 4.8249 | 5.9027 / 9.9027 | 0.2889 | 0.6732 | 2.4786 | 744/1143 (65.09%) | 31/257 (12.06%) | 20/257 (7.78%) | 0.1751 | 0.0272 | 0.6824 |
| 5 | 5 | 321/396 (81.06%) | 75 | 0 | 4.4361 / 5.4361 | 7.4143 / 11.4143 | 0.2667 | 1.162 | 2.595 | 923/1143 (80.75%) | 89/321 (27.73%) | 44/321 (13.71%) | 0.405 | 0.0249 | 0.6012 |
| 5 | 6 | 344/396 (86.87%) | 52 | 0 | 4.8866 / 5.8866 | 8.6657 / 12.6657 | 0.2539 | 1.564 | 2.657 | 989/1143 (86.53%) | 116/344 (33.72%) | 53/344 (15.41%) | 0.4797 | 0.0291 | 0.5928 |
| 5 | 7 | 360/396 (90.91%) | 36 | 0 | 5.2833 / 6.2833 | 9.8806 / 13.8806 | 0.2421 | 1.9722 | 2.7111 | 1035/1143 (90.55%) | 131/360 (36.39%) | 55/360 (15.28%) | 0.4722 | 0.0278 | 0.5828 |
| 5 | 8 | 381/396 (96.21%) | 15 | 0 | 5.7244 / 6.7244 | 11.1627 / 15.1627 | 0.2303 | 2.4304 | 2.7822 | 1098/1143 (96.06%) | 151/381 (39.63%) | 55/381 (14.44%) | 0.4462 | 0.0262 | 0.5761 |
| 5 | 9 | 396/396 (100.0%) | 0 | 0 | 6.1414 / 7.1414 | 12.25 / 16.25 | 0.2217 | 2.8258 | 2.8586 | 1143/1143 (100.0%) | 169/396 (42.68%) | 55/396 (13.89%) | 0.4293 | 0.0253 | 0.5718 |
| 6 | 10 | 396/396 (100.0%) | 0 | 0 | 6.4343 / 7.4343 | 12.9697 / 16.9697 | 0.2184 | 3.0985 | 2.9066 | 1143/1143 (100.0%) | 169/396 (42.68%) | 55/396 (13.89%) | 0.4293 | 0.0253 | 0.568 |
| 6 | 4 | 257/396 (64.9%) | 139 | 0 | 3.8249 / 4.8249 | 5.9027 / 9.9027 | 0.2889 | 0.6732 | 2.4786 | 744/1143 (65.09%) | 31/257 (12.06%) | 20/257 (7.78%) | 0.1751 | 0.0272 | 0.6824 |
| 6 | 5 | 321/396 (81.06%) | 75 | 0 | 4.4361 / 5.4361 | 7.4143 / 11.4143 | 0.2667 | 1.162 | 2.595 | 923/1143 (80.75%) | 89/321 (27.73%) | 44/321 (13.71%) | 0.405 | 0.0249 | 0.6012 |
| 6 | 6 | 343/396 (86.62%) | 53 | 0 | 4.8834 / 5.8834 | 8.6239 / 12.6239 | 0.2541 | 1.551 | 2.6647 | 989/1143 (86.53%) | 115/343 (33.53%) | 53/343 (15.45%) | 0.481 | 0.0292 | 0.5921 |
| 6 | 7 | 354/396 (89.39%) | 42 | 0 | 5.2542 / 6.2542 | 9.6836 / 13.6836 | 0.2438 | 1.8842 | 2.7288 | 1019/1143 (89.15%) | 125/354 (35.31%) | 55/354 (15.54%) | 0.4802 | 0.0282 | 0.5835 |
| 6 | 8 | 371/396 (93.69%) | 25 | 0 | 5.6631 / 6.6631 | 10.9057 / 14.9057 | 0.2332 | 2.3181 | 2.7817 | 1068/1143 (93.44%) | 142/371 (38.27%) | 55/371 (14.82%) | 0.4582 | 0.027 | 0.5762 |
| 6 | 9 | 384/396 (96.97%) | 12 | 0 | 6.0521 / 7.0521 | 11.9844 / 15.9844 | 0.2251 | 2.737 | 2.8438 | 1107/1143 (96.85%) | 157/384 (40.89%) | 55/384 (14.32%) | 0.4427 | 0.026 | 0.5733 |

| K_A_post | selected | mean nodes | mean optional | mean Answer-only optional | mean abs | items exposing ABSENCE_ONLY |
|---:|---|---:|---:|---:|---:|---|
| 0 | 372/396 (93.94%) | 5.3414 | 2.0726 | 0.0 | 0.457 | 55/372 (14.78%) |
| 1 | 372/396 (93.94%) | 5.3387 | 2.086 | 0.0323 | 0.457 | 55/372 (14.78%) |

| group | selected | nested-infeasible | mean nodes | mean edges | mand. share | mean optional | COVER_ALT satisfied | every distractor has optional | items exposing ABSENCE_ONLY |
|---|---|---|---:|---:|---:|---:|---|---|---|
| POOLED | 372/396 (93.94%) | 24 | 5.3387 | 10.172 | 0.2389 | 2.086 | 1071/1143 (93.7%) | 142/372 (38.17%) | 55/372 (14.78%) |
| GROUP:CHEMISTRY | 40/40 (100.0%) | 0 | 4.65 | 7.825 | 0.2768 | 0.45 | 119/119 (100.0%) | 5/40 (12.5%) | 7/40 (17.5%) |
| GROUP:EVENT | 34/34 (100.0%) | 0 | 4.4706 | 6.4706 | 0.2884 | 0.2353 | 101/101 (100.0%) | 0/34 (0.0%) | 6/34 (17.65%) |
| GROUP:PERSON | 218/240 (90.83%) | 22 | 5.2569 | 10.1835 | 0.2426 | 2.2936 | 616/682 (90.32%) | 89/218 (40.83%) | 35/218 (16.06%) |
| GROUP:PLACE | 47/47 (100.0%) | 0 | 6.4468 | 14.9149 | 0.1795 | 3.4681 | 138/138 (100.0%) | 35/47 (74.47%) | 3/47 (6.38%) |
| GROUP:POLITY | 33/35 (94.29%) | 2 | 6.0303 | 10.0 | 0.2015 | 2.6364 | 97/103 (94.17%) | 13/33 (39.39%) | 4/33 (12.12%) |

**A structural finding the sweep exposes (Measured).** The nested design
`S_pre ⊆ S_post` with `COVER_ALT` makes the post budget infeasible whenever
`mandatory nodes + new pre-answer nodes + distractors with a showable
alternative > B_post`. At `B_pre = 4`, `B_post = 7` this hits 24/396 items
(all with 1 mandatory node, 4 new pre nodes and 3 alternatives); at
`B_post = 4` it hits 124–139 items. The smallest feasible `B_post` at
`B_pre = 4` is 4 for 257 items, 5 for 65, 6 for 30, 7 for 20 and 8 for 24.
`COVER_ALT` is satisfiable for every letter that has a showable alternative
from `B_post = 7` upwards (1,143/1,143); 32/396 items have at least one
distractor whose every observed alternative was screened out
(`alt-unshowable`), which is the `CE_COVER_ALT_UNSHOWABLE` case of review
C11.

**Reading.** (i) `K_A_post = 1` versus 0 changes almost nothing on this data
(mean Answer-only optional groups 0.03; identical `ABSENCE_ONLY` exposure),
so H4's post value is a low-stakes choice. (ii) Under arm B the pre-answer
budget is rarely binding: the mean number of selected optional clues is 0.56
at `B_pre = 2` and 1.04 at `B_pre = 6`, and 264/396 items select nothing
because nothing is admissible; the budget question before answering is
therefore secondary to H14. (iii) After answering, the graph grows smoothly
with `B_post` (5.4 nodes / 10.5 edges at 7; 6.4 / 13.0 at 10, caption arm)
and the mandatory share falls from 0.29 to 0.22; roughly 14–15 % of items
expose at least one `ABSENCE_ONLY` incidence after answering under the
candidate key order, which is what memo H16 must weigh. (iv) The
nested-infeasibility rule above is a specification defect to repair before
freeze: either `B_post` must be defined relative to the pre selection
(`≥ mandatory + pre_new + |ALT letters|`), or the pre-answer solve must be
node-aware. That is a design change for ARCH-2's C8/H7, not a human
preference. (v) Whether the class is a caption or a budget-exempt node
changes graph size by exactly one node and four edges and nothing else
measured here; the choice (H8b) is the author's.

---

## 6. Measurement E — H18 universe bounding (Measured)

Bounding touches the `OPTIONAL_CONTEXT` tier only. Modular = the ARCH-1
pre-key truncated; stratified = keep every optional group on a node already
used by a mandatory or alternative group, the top 2 per distinct family key
and the top 5 per distractor letter, then fill by the pre-key. `N_max ∈
{100, 200, 400, 800}` and `UNIVERSE_FULL` where the optional tier has at
most 3,000 groups (15 items above that were not solved at FULL). Stability at
doubling is measured on the items actually bounded at the smaller `N_max`.

| group | method | step | items bounded | S_pre equal | S_post equal | both equal | mean Jaccard pre / post | earliest differing key |
|---|---|---|---:|---|---|---|---|---|
| POOLED | modular | 100->200 | 160 | 160/160 (100.0%) | 135/160 (84.38%) | 135/160 (84.38%) | 1.0 / 0.9488 | {'post:entity_nodes': 1, 'post:neg_distinct_keys': 16, 'post:neg_shared_information': 3, 'post:token_sum': 5} |
| POOLED | modular | 200->400 | 93 | 93/93 (100.0%) | 80/93 (86.02%) | 80/93 (86.02%) | 1.0 / 0.9423 | {'post:CANONICAL_TIE_BREAK': 6, 'post:neg_distinct_keys': 5, 'post:neg_shared_information': 1, 'post:token_sum': 1} |
| POOLED | modular | 400->800 | 59 | 59/59 (100.0%) | 47/59 (79.66%) | 47/59 (79.66%) | 1.0 / 0.921 | {'post:CANONICAL_TIE_BREAK': 4, 'post:entity_nodes': 1, 'post:neg_distinct_keys': 6, 'post:token_sum': 1} |
| POOLED | modular | 800->FULL | 28 | 28/28 (100.0%) | 24/28 (85.71%) | 24/28 (85.71%) | 1.0 / 0.9454 | {'post:neg_distinct_keys': 4} |
| POOLED | stratified | 100->200 | 160 | 159/160 (99.38%) | 145/160 (90.62%) | 145/160 (90.62%) | 0.9984 / 0.9586 | {'post:CANONICAL_TIE_BREAK': 2, 'post:entity_nodes': 1, 'post:neg_distinct_keys': 3, 'post:neg_shared_information': 4, 'post:token_sum': 4, 'pre:neg_shared_information': 1} |
| POOLED | stratified | 200->400 | 93 | 93/93 (100.0%) | 81/93 (87.1%) | 81/93 (87.1%) | 1.0 / 0.9485 | {'post:CANONICAL_TIE_BREAK': 2, 'post:neg_distinct_keys': 1, 'post:neg_shared_information': 5, 'post:token_sum': 4} |
| POOLED | stratified | 400->800 | 59 | 59/59 (100.0%) | 56/59 (94.92%) | 56/59 (94.92%) | 1.0 / 0.9724 | {'post:neg_distinct_keys': 2, 'post:neg_shared_information': 1} |
| POOLED | stratified | 800->FULL | 28 | 28/28 (100.0%) | 26/28 (92.86%) | 26/28 (92.86%) | 1.0 / 0.9764 | {'post:neg_distinct_keys': 1, 'post:token_sum': 1} |
| GROUP:CHEMISTRY | modular | 100->200 | 6 | 6/6 (100.0%) | 6/6 (100.0%) | 6/6 (100.0%) | 1.0 / 1.0 | {} |
| GROUP:CHEMISTRY | modular | 200->400 | 3 | 3/3 (100.0%) | 3/3 (100.0%) | 3/3 (100.0%) | 1.0 / 1.0 | {} |
| GROUP:CHEMISTRY | modular | 400->800 | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) | 1.0 / 1.0 | {} |
| GROUP:CHEMISTRY | stratified | 100->200 | 6 | 6/6 (100.0%) | 6/6 (100.0%) | 6/6 (100.0%) | 1.0 / 1.0 | {} |
| GROUP:CHEMISTRY | stratified | 200->400 | 3 | 3/3 (100.0%) | 3/3 (100.0%) | 3/3 (100.0%) | 1.0 / 1.0 | {} |
| GROUP:CHEMISTRY | stratified | 400->800 | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) | 1.0 / 1.0 | {} |
| GROUP:EVENT | modular | 100->200 | 10 | 10/10 (100.0%) | 9/10 (90.0%) | 9/10 (90.0%) | 1.0 / 0.9667 | {'post:token_sum': 1} |
| GROUP:EVENT | modular | 200->400 | 7 | 7/7 (100.0%) | 6/7 (85.71%) | 6/7 (85.71%) | 1.0 / 0.9524 | {'post:CANONICAL_TIE_BREAK': 1} |
| GROUP:EVENT | modular | 400->800 | 5 | 5/5 (100.0%) | 5/5 (100.0%) | 5/5 (100.0%) | 1.0 / 1.0 | {} |
| GROUP:EVENT | modular | 800->FULL | 4 | 4/4 (100.0%) | 4/4 (100.0%) | 4/4 (100.0%) | 1.0 / 1.0 | {} |
| GROUP:EVENT | stratified | 100->200 | 10 | 10/10 (100.0%) | 9/10 (90.0%) | 9/10 (90.0%) | 1.0 / 0.9667 | {'post:token_sum': 1} |
| GROUP:EVENT | stratified | 200->400 | 7 | 7/7 (100.0%) | 6/7 (85.71%) | 6/7 (85.71%) | 1.0 / 0.9524 | {'post:CANONICAL_TIE_BREAK': 1} |
| GROUP:EVENT | stratified | 400->800 | 5 | 5/5 (100.0%) | 5/5 (100.0%) | 5/5 (100.0%) | 1.0 / 1.0 | {} |
| GROUP:EVENT | stratified | 800->FULL | 4 | 4/4 (100.0%) | 4/4 (100.0%) | 4/4 (100.0%) | 1.0 / 1.0 | {} |
| GROUP:PERSON | modular | 100->200 | 77 | 77/77 (100.0%) | 64/77 (83.12%) | 64/77 (83.12%) | 1.0 / 0.9519 | {'post:entity_nodes': 1, 'post:neg_distinct_keys': 11, 'post:token_sum': 1} |
| GROUP:PERSON | modular | 200->400 | 27 | 27/27 (100.0%) | 25/27 (92.59%) | 25/27 (92.59%) | 1.0 / 0.9764 | {'post:CANONICAL_TIE_BREAK': 1, 'post:neg_distinct_keys': 1} |
| GROUP:PERSON | modular | 400->800 | 9 | 9/9 (100.0%) | 7/9 (77.78%) | 7/9 (77.78%) | 1.0 / 0.9693 | {'post:neg_distinct_keys': 2} |
| GROUP:PERSON | modular | 800->FULL | 5 | 5/5 (100.0%) | 5/5 (100.0%) | 5/5 (100.0%) | 1.0 / 1.0 | {} |
| GROUP:PERSON | stratified | 100->200 | 77 | 77/77 (100.0%) | 71/77 (92.21%) | 71/77 (92.21%) | 1.0 / 0.9737 | {'post:entity_nodes': 1, 'post:neg_distinct_keys': 3, 'post:neg_shared_information': 1, 'post:token_sum': 1} |
| GROUP:PERSON | stratified | 200->400 | 27 | 27/27 (100.0%) | 25/27 (92.59%) | 25/27 (92.59%) | 1.0 / 0.9655 | {'post:neg_distinct_keys': 1, 'post:token_sum': 1} |
| GROUP:PERSON | stratified | 400->800 | 9 | 9/9 (100.0%) | 8/9 (88.89%) | 8/9 (88.89%) | 1.0 / 0.9524 | {'post:neg_distinct_keys': 1} |
| GROUP:PERSON | stratified | 800->FULL | 5 | 5/5 (100.0%) | 5/5 (100.0%) | 5/5 (100.0%) | 1.0 / 1.0 | {} |
| GROUP:PLACE | modular | 100->200 | 36 | 36/36 (100.0%) | 32/36 (88.89%) | 32/36 (88.89%) | 1.0 / 0.9417 | {'post:neg_distinct_keys': 1, 'post:neg_shared_information': 3} |
| GROUP:PLACE | modular | 200->400 | 30 | 30/30 (100.0%) | 24/30 (80.0%) | 24/30 (80.0%) | 1.0 / 0.9084 | {'post:neg_distinct_keys': 4, 'post:neg_shared_information': 1, 'post:token_sum': 1} |
| GROUP:PLACE | modular | 400->800 | 26 | 26/26 (100.0%) | 21/26 (80.77%) | 21/26 (80.77%) | 1.0 / 0.9298 | {'post:CANONICAL_TIE_BREAK': 3, 'post:neg_distinct_keys': 2} |
| GROUP:PLACE | modular | 800->FULL | 12 | 12/12 (100.0%) | 9/12 (75.0%) | 9/12 (75.0%) | 1.0 / 0.9201 | {'post:neg_distinct_keys': 3} |
| GROUP:PLACE | stratified | 100->200 | 36 | 36/36 (100.0%) | 33/36 (91.67%) | 33/36 (91.67%) | 1.0 / 0.9647 | {'post:CANONICAL_TIE_BREAK': 2, 'post:neg_shared_information': 1} |
| GROUP:PLACE | stratified | 200->400 | 30 | 30/30 (100.0%) | 25/30 (83.33%) | 25/30 (83.33%) | 1.0 / 0.926 | {'post:neg_shared_information': 4, 'post:token_sum': 1} |
| GROUP:PLACE | stratified | 400->800 | 26 | 26/26 (100.0%) | 25/26 (96.15%) | 25/26 (96.15%) | 1.0 / 0.9753 | {'post:neg_shared_information': 1} |
| GROUP:PLACE | stratified | 800->FULL | 12 | 12/12 (100.0%) | 11/12 (91.67%) | 11/12 (91.67%) | 1.0 / 0.9688 | {'post:neg_distinct_keys': 1} |
| GROUP:POLITY | modular | 100->200 | 31 | 31/31 (100.0%) | 24/31 (77.42%) | 24/31 (77.42%) | 1.0 / 0.9337 | {'post:neg_distinct_keys': 4, 'post:token_sum': 3} |
| GROUP:POLITY | modular | 200->400 | 26 | 26/26 (100.0%) | 22/26 (84.62%) | 22/26 (84.62%) | 1.0 / 0.9365 | {'post:CANONICAL_TIE_BREAK': 4} |
| GROUP:POLITY | modular | 400->800 | 18 | 18/18 (100.0%) | 13/18 (72.22%) | 13/18 (72.22%) | 1.0 / 0.8578 | {'post:CANONICAL_TIE_BREAK': 1, 'post:entity_nodes': 1, 'post:neg_distinct_keys': 2, 'post:token_sum': 1} |
| GROUP:POLITY | modular | 800->FULL | 7 | 7/7 (100.0%) | 6/7 (85.71%) | 6/7 (85.71%) | 1.0 / 0.9184 | {'post:neg_distinct_keys': 1} |
| GROUP:POLITY | stratified | 100->200 | 31 | 30/31 (96.77%) | 26/31 (83.87%) | 26/31 (83.87%) | 0.9919 / 0.9032 | {'post:neg_shared_information': 2, 'post:token_sum': 2, 'pre:neg_shared_information': 1} |
| GROUP:POLITY | stratified | 200->400 | 26 | 26/26 (100.0%) | 22/26 (84.62%) | 22/26 (84.62%) | 1.0 / 0.9497 | {'post:CANONICAL_TIE_BREAK': 1, 'post:neg_shared_information': 1, 'post:token_sum': 2} |
| GROUP:POLITY | stratified | 400->800 | 18 | 18/18 (100.0%) | 17/18 (94.44%) | 17/18 (94.44%) | 1.0 / 0.9691 | {'post:neg_distinct_keys': 1} |
| GROUP:POLITY | stratified | 800->FULL | 7 | 7/7 (100.0%) | 6/7 (85.71%) | 6/7 (85.71%) | 1.0 / 0.9592 | {'post:token_sum': 1} |

| group | items studied (>100 optional) | FULL not computed (>3000) | modular ≥95% | modular ≥99% | stratified ≥95% | stratified ≥99% |
|---|---|---:|---|---|---|---|
| POOLED | 160/396 (40.4%) | 15 | None | None | None | None |
| GROUP:CHEMISTRY | 6/40 (15.0%) | 0 | 100 | 100 | 100 | 100 |
| GROUP:EVENT | 10/34 (29.41%) | 0 | 400 | 400 | 400 | 400 |
| GROUP:PERSON | 77/240 (32.08%) | 0 | 800 | 800 | 800 | 800 |
| GROUP:PLACE | 36/47 (76.6%) | 11 | None | None | 400 | None |
| GROUP:POLITY | 31/35 (88.57%) | 4 | None | None | None | None |

**Reading.** The pre-answer selection is stable under bounding almost
everywhere (S_pre equal in 100 % of modular steps and 99.4–100 % of
stratified steps): the admissible pre-answer groups are shared, verbalizable
and few, and every bounding keeps them. What bounding changes is the
**post-answer** graph, through the distinct-keys and shared-information keys
and, at `N_max ≥ 200`, through canonical ties among equally scored groups.
Stratified bounding is more stable than the modular pre-key at every pooled
step (90.6 % vs 84.4 % at 100→200; 87.1 % vs 86.0 % at 200→400; 94.9 % vs
79.7 % at 400→800; 92.9 % vs 85.7 % at 800→FULL). No `N_max` in the sweep
reaches 95 % pooled stability of both selections; per cohort, persons reach
it at 800, events at 400, chemistry at 100, places only under stratified
bounding at 400 (96.2 %), polities not at all within the sweep (94.4 % at
400→800). The threshold and the `N_max` remain the researcher's (memo H18);
the measurement says that a single pooled `N_max` cannot meet 95 % for the
IN-heavy cohorts, that stratification is the better of the two rules, and
that the paper's statement "bounding never affects answerability or
grounding" is confirmed: only the optional post-answer context moved.

---

## 7. Measurement F — H6 solver evidence (Measured)

| quantity | value |
|---|---|
| solver | HiGHS via scipy.optimize.milp (scipy 1.17.1) |
| calls | 449469 |
| status_counts | {"INFEASIBLE": 3211, "OPTIMAL": 446258} |
| optimal | 446258/449469 (99.29%) |
| seconds_median | 0.0022 |
| seconds_p90 | 0.01104 |
| seconds_p95 | 0.02251 |
| seconds_max | 0.67078 |
| seconds_total | 2714.25 |
| n_vars_median | 370 |
| n_vars_p95 | 1783.0 |
| n_vars_max | 7269 |
| n_rows_median | 222 |
| n_rows_p95 | 1009.0 |
| n_rows_max | 3743 |
| verification_checked | 29074 |
| verification_failed | 0 |
| oracle | {"post_agree": 34, "post_ran": 34, "pre_agree": 389, "pre_ran": 389} |
| deterministic rerun | 40/40 items byte-identical (excluding timings) |

| group | solves | median s | p95 s | max s | max vars | max rows | re-check failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| GROUP:CHEMISTRY | 36357 | 0.0015 | 0.022604 | 0.05403 | 1592 | 835 | 0 |
| GROUP:EVENT | 40325 | 0.0027 | 0.02597 | 0.62837 | 5148 | 2601 | 0 |
| GROUP:PERSON | 212152 | 0.0012 | 0.00673 | 0.27142 | 2252 | 1421 | 0 |
| GROUP:PLACE | 87890 | 0.0034 | 0.02904 | 0.67078 | 6051 | 3221 | 0 |
| GROUP:POLITY | 72745 | 0.0038 | 0.106418 | 0.48564 | 7269 | 3743 | 0 |

**Reading.** On the actual audit instances the installed route is adequate:
449,469 solves, 446,258 optimal certificates and 3,211 infeasible statuses
that are all the recorded nested-infeasible cells (no time limits, no
"other" statuses); median 2.2 ms, p95 22.5 ms, maximum 0.67 s on a
7,269-variable polity instance; 29,074 selections re-checked in pure Python
with 0 failures; 389/389 pre and 34/34 post oracle agreements; 40/40
re-measured items byte-identical excluding timings in a fresh process.
Thread count is not exposed by scipy's API; `OMP_NUM_THREADS = 1` was set
and determinism was demonstrated, not assumed. Nothing here benchmarks
solver brands; it says the zero-dependency route can carry the publication
run under the exact-only policy of review C6.

---

## 8. Required conclusion — decision | measured evidence | what remains human

| decision | measured evidence (development batches, 396 gated items) | what remains human |
|---|---|---|
| **H5** require-verbalizable | 176/396 items have a template-less `R*` fact (persons 33/240; places 47/47; events 33/34; polities 33/35; chemistry 30/40). The policy alone would lose 100/396 items outright, move the distractor triple in 55, change only the rationale in 7; 14 undecidable in budget. Five IN/OUT keys explain 101 of the 176 items. | Adopt the policy, expand templates first, or exclude and report — the publication configuration (CLAUDE.md step 1), with the yield cost now known per cohort. |
| **H6** solver | HiGHS/scipy: 99.29 % optimal certificates (the rest are recorded infeasible cells), p95 22.5 ms, 0 re-check failures, 423/423 oracle agreements, 40/40 deterministic reruns. | Accept the zero-dependency route with the exact-only publication rule, or prefer CP-SAT for an integer-exact certificate at the cost of a dependency. |
| **H7** budgets | Pre budget rarely binding under arm B (mean 0.56–1.04 optional clues selected; 264/396 items select nothing). Post graph grows 3.8→6.4 nodes over `B_post` 4→10; `COVER_ALT` 100 % from `B_post` 7; nested infeasibility in 24 items at (4, 7) and up to 139 at `B_post` 4. `K_A_post` 0 vs 1 indistinguishable. Class-as-node = +1 node, +4 edges. | The budget values and units; **and a specification repair before freeze**: `B_post` relative to the pre selection or a node-aware pre solve. |
| **H13** objective | Pre-answer order insensitive to every adjacent swap (≤ 1.3 %). Post-answer: shared-information↔distinct-keys 15 % and distinct-keys↔nodes 15.6 % change selections (places 45 %, polities 39 %); other swaps ≤ 3.8 %. ARCH-1 weighted objective exposes `ABSENCE_ONLY` before answering in 62.9 % of items. Oracle 423/423. | Accept strict lexicographic priority and fix the order of the two post-answer keys that matter (shared information vs distinct keys vs nodes). |
| **H14** admissibility | Arm A: 326/396 items keep ≥ 1 optional pre clue; arm B: 132/396 (persons 118/240, polities 9/35, chemistry 5/40, places 0/47, events 0/34); 264/396 mandatory-only. Of the 229 items with any shared verbalizable context, arm B empties 97, 181 of their groups through `ABSENCE_ONLY`. Arm C costs nothing beyond B; C2 costs 8 items; tolerating unmodelled buys 5. | Whether a two-thirds mandatory-only clue-set rate is acceptable for open-world safety, whether to adopt arm C, and whether template expansion comes first. Not implied by the yield numbers. |
| **H18** bounding | S_pre stable under every bounding; S_post changes through distinct-keys / shared-information keys. Stratified beats modular at every pooled step (e.g. 94.9 % vs 79.7 % at 400→800). No pooled `N_max` reaches 95 %; per cohort 100 (chemistry), 400 (events; places stratified), 800 (persons), none (polities). 15 items above 3,000 optional groups never solved at FULL. | The stability threshold, `N_max` (possibly per cohort), and whether polities are reported as `UNIVERSE_BOUNDED` by design. |

**Decisions the measurements do not touch** (ARCH-2 confidence unchanged):
H1 (`R*` always exposed), H2 (grounding vocabulary; the 282,933/282,933
agreement supports it), H8a (frame sentence), H9 (rarity as a late key),
H10 (`A` fixed; printed order permuted), H11 (pre-registration), H12
(template-only prose), H17 (legacy naming). H3 (alternatives before
answering) was held OFF by design and not measured; H4's post value and H16
receive the numbers in §5 (0.03 Answer-only groups; 14–15 % of items expose
`ABSENCE_ONLY` after answering) but remain the researcher's.

---

## 9. Limitations (stated, not hidden)

* Development batches only; cohort groups are evaluation metadata derived
  from the input-file headers by a keyword rule recorded in the manifest.
* The grounding of distractor-owned groups is this audit's rule with this
  audit's index; its equality with the frozen classifier is demonstrated on
  Answer-owned pairs only.
* H13 and H7 solve on the stratified universe bounded at `N_max = 400`;
  H18 measures what that bounding does. 15 items with more than 3,000
  optional groups were never solved on the full universe.
* The H5 counterfactual could not be decided within its time budget for 14
  items (all historical); they are counted as undecided, not as lost.
* `HiGHS` thread count is not controllable through scipy; determinism was
  shown by rerun, not by configuration.
* The ARCH-1 weighted comparator uses the candidate weights ARCH-1 listed
  as placeholders; it demonstrates the objective's behaviour, not a tuned
  version of it.
* No structural quantity here is human difficulty; no missing edge is
  falsity.

---

## 10. Files, checks and reproduction

**Created**: `scripts/audit_b3_choice_evidence_decisions.py` (AUDIT /
DECISION SUPPORT ONLY); `docs/plans/B3_DECISION_SUPPORT_MEASUREMENTS_2026-09-18.md`
(this file) and its `.summary.json`;
`outputs/journal2_b3_decision_support_2026-09-18/` (run manifest,
`items.csv`, `replay_verification.*`, `per_item_metrics.csv`,
`per_cohort_rollups.json`, `h5_verbalizability_audit.*`,
`h14_admissibility_arms.*`, `h13_objective_sensitivity.*`,
`h7_budget_sweep.*`, `h18_bounding_stability.*`, `h6_solver_metrics.json`,
`h6_deterministic_rerun.*`, `universe/`, `measure/`, `rerun/`,
`b3_semantic_index/`, `v4_offline_replay/`, `logs/`, `SHA256SUMS.txt/.csv`,
`REPRODUCE.md`, `zip_manifest.json`) and
`outputs/journal2_b3_decision_support_2026-09-18.zip` (+ `.zip.sha256`),
validated with `testzip()` (no bad member); ten files are kept on disk only
(the four private cache copies, their digest list and five
`candidate_fact_evidence.csv` above 20 MB), listed in `zip_manifest.json`.
**Modified**: nothing tracked. No frozen module, no v1–v4 output, no cache
of `data/` or `cache/`, no memo line, no ARCH-1/ARCH-2 document.
**Not created**: `src/choice_evidence_v1/`.
**Checks run**: `python -m py_compile` on the script; `json.load` on every
JSON deliverable; `git status --short` (tracked changes: none); `testzip()`
inside the package stage; the internal checks reported above (replay
verification 518/518, kernel replay 396/396, grounding agreement
282,933/282,933, 29,074 pure-Python re-checks, 423 oracle agreements, 40
deterministic reruns). No pytest suite was run: no production source was
created or changed.

```bash
cd /home/thuy/projects/mcq_journal2
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
python scripts/audit_b3_choice_evidence_decisions.py --stage verify
python scripts/audit_b3_choice_evidence_decisions.py --stage universe     # opens the pinned KG read-only
python scripts/audit_b3_choice_evidence_decisions.py --stage h5 --workers 12
python scripts/audit_b3_choice_evidence_decisions.py --stage measure --workers 12
python scripts/audit_b3_choice_evidence_decisions.py --stage rerun
python scripts/audit_b3_choice_evidence_decisions.py --stage package
```
