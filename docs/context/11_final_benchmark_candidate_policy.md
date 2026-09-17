# Final-benchmark CANDIDATE policy — the open choices and what each costs

**Date** 2026-09-18
**Status** DECISION MATERIAL. Nothing here is a publication default.
**Evidence** `docs/audits/B2G_PRE_FINAL_BENCHMARK_SAFETY_AUDIT_2026-09-18.md`
and `outputs/journal2_b2g_final_benchmark_safety_v4_2026-09-18/`

Prompt 8H-B2-G deliberately stopped before choosing. This file lists every
switch the v4 runner exposes, what it does, and the measured cost of each
setting, so the choice can be made once and recorded.

---

## 1. The four open choices

### 1.1 Candidate-validity policy — `--candidate-type-policy`

| arm | removes | candidate rows removed (of 7,403) | pools below the gate (of 307) |
|---|---|---:|---:|
| `observe-only` *(v4 default)* | nothing | 0 | **0** |
| `person-guarded` | confirmed NOT_PERSON + complete-Answer-name containment | 63 | **3** |
| `person-strict` | the above **+ UNKNOWN** | 1,353 | **66** |

`UNKNOWN` means the pinned snapshot filled no listed person slot. It is
snapshot SILENCE, not a contradiction, and the same open-world discipline that
forbids reading `L0` as falsity argues against refusing it. `person-guarded`
buys almost all of the protection for ~4% of the yield cost.

**Two caveats before choosing an acting policy.**

1. When the screen drops a pool below the local-mapping gate, the runner
   reports `NO_LOCALLY_MAPPING_FEASIBLE_CLASS` rather than walking on to the
   next ranked class. In the regression set Muhammad is lost this way under both
   acting policies although sixteen feasible classes existed. Re-entering the
   walk after screening is a structural change and is **not implemented**.
2. The PERSON heuristic has false positives (`Hud_(prophet)` → `NOT_PERSON`).
   Every verdict carries the slots that produced it and is reviewable.

### 1.2 Granularity-risk policy — `--granularity-risk-policy`

| arm | behaviour | measured effect on the 11-Answer regression set |
|---|---|---|
| `report-only` *(v4 default)* | a risky rationale may be selected; it is flagged and counted | 11 of 11 selections unchanged |
| `require-clean` | a learner-facing main rationale must carry zero granularity-risk incidences | 3 items changed: 2 changed DISTRACTOR TRIPLE, 1 changed rationale; exact ranks [1,2,3] fell 11 → 9; 0 items became unusable |

`require-clean` never converts a risky L1 to L0, never invents `NOT_COVERED`,
never grows `|R*|` and never falls back to a weaker evidence policy. When no
clean minimum-cardinality rationale exists it reports
`NO_GRANULARITY_CLEAN_MAIN_RATIONALE` and marks the item not learner-facing.

**What it cannot do.** It protects only risks the DETECTOR reports. The detector
is governed by `semantic_relation_policy_v2.json`, which declares domains for
place containment, `dbp:field`/`dbp:fields` and `dbp:nationality`/`citizenship`
only. `dbp:schoolTradition` is ungoverned, so **Socrates is not protected**. It
can also cost evidence strength: Richard Kuhn's clean alternative carries one
fewer L1 incidence than the risky winner.

### 1.3 Rationale objective — `--rationale-objective`

| version | key 4 ordering after fields 1-4 | Augustus outcome |
|---|---|---|
| `v1` | `-scoped_empirical`, `granularity_risk` | `successor → Tiberius`, conflict 1 |
| `v2` | `-scoped_empirical`, `granularity_risk`, `conflict` | `successor → Tiberius`, conflict 1 |
| `v3` *(v4 default)* | `granularity_risk`, `conflict`, `-scoped_empirical` | **`deathPlace → Nola`, conflict 0** |

The complete evidence-LEVEL profile (fields 1-4) is identical in all three, so
no version can buy a weaker level, and `|R*|` is fixed before key 4 is read so
none can grow a rationale. v3 is the only placement that repairs Augustus.

### 1.4 M1 node budget — `--max-nodes`

| value | George Washington | Kingdom of Italy |
|---|---|---|
| 1200 *(frozen v1/v2/v3)* | infeasible, 6 candidates over budget | infeasible, Answer base 3,026 > 1200 |
| 2000 | feasible, 11 retained, 1,711 nodes | infeasible, Answer base 3,026 |
| 5000 *(v4 candidate)* | feasible, 11 retained, 1,711 nodes | feasible, 49 of 71 retained, 4,999 nodes |

Raising the budget is not free and is not a fix in itself. At 5000 the budget is
still binding for Kingdom of Italy. The diagnostics
(`lost_would_exceed_max_nodes` / `lost_answer_base_exceeds_budget` /
`lost_candidate_cap_reached` / `answer_base_node_count`) are what make a budget
failure interpretable, and they should be read for every failed Answer of the
final run.

### 1.5 Predicate-slot aliases — `--predicate-alias-policy`

`v1` *(v4 candidate default)* applies the ONE audited family
`dbp:field` / `dbp:fields` to the candidate's observed objects, for evidence
lookup only. `none` reproduces exact-key lookup. The workplace family
(`workplaces` / `workplace` / `workInstitution` / `workInstitutions`) is audited
and **NOT admitted**; the numbers are in the audit.

---

## 2. Planned benchmark design — EVALUATION METADATA ONLY

Cohort labels are carried on output rows and are **never** passed to the class
ranker, the M1 graph, LRoleSim, the evidence classifier or the selection kernel.

**Core**

| cohort | target size |
|---|---:|
| Japanese Nobel laureates / scientists | 15 |
| worldwide scientists | 15 |
| — of which worldwide theoretical physicists | ~10 |
| — of which worldwide theoretical chemists | ~5 |
| Ethics / Classics persons | 15 |
| World History persons | 15 |
| Japanese History persons | 15 |
| World History historical events | 15 |
| Japanese History historical events | 15 |

**Optional extensions, only if time permits**

former states / empires / kingdoms (~15); historical places and former capitals
(~15); East Asian dynastic states (~15); chemistry entities (~15).

**This is not the final publication benchmark and must not be labelled as one
until §1's choices are recorded.**

---

## 3. Named Failure Analysis cases to carry into the paper

| case | why it fails, and what would be needed |
|---|---|
| **Otto Hahn** | `field → Radiochemistry` against Marie Curie's `Chemistry`. The pinned snapshot holds no edge between any two field nodes, so the risk is real and unmodelled. A verified `Radiochemistry ⊂ Chemistry` edge would still NOT license `Curie field Radiochemistry`: containment removes contrast only in the candidate-under-claim direction. |
| **Socrates** | `schoolTradition → Classical_Greek_philosophy` (2 subjects in the whole snapshot) against Platonism / Epicureanism / Neoplatonism. Broad-vs-specific, and the detector is silent because no relation domain governs the predicate. Needs a frozen, versioned philosophical-tradition relation source. |
| **Richard Kuhn** | broad `Chemistry` against an `Austrian biochemists` pool; the Chemistry/Biochemistry relation is unmodelled. |
| **Niels Bohr** | every one of the minimum-cardinality covers carries granularity risk, and the winner among 36 (v3 config) is separated only at ranking field 10, `label_length_sum`. |
| **Muhammad** | the class that survives the leak screen falls below the local-mapping gate, and the walk does not resume. |
| **Kingdom of Italy** | 3,026-node one-hop neighbourhood; infeasible at any budget below that, and still budget-bound at 5000. |
