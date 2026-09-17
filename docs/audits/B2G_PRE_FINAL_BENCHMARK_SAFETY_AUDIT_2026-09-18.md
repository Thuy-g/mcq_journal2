# Prompt 8H-B2-G — Pre-Final-Benchmark Safety Audit

**Date** 2026-09-18
**Branch** `journal2-b2g-final-benchmark-safety-v4-20260918`
**Pinned KG** `data/infobox.pickle_EnglishVersion_EntityType`, sha256 `e230c5b9…bea1b`
**Evidence package** `outputs/journal2_b2g_final_benchmark_safety_v4_2026-09-18/`

> **This task declares no publication-final policy.** It produces the evidence a
> human researcher needs in order to choose one. Every configuration named below
> is a CANDIDATE, and the final benchmark has not been run or labelled.

---

## 0. What was and was not changed

| Kind | What |
|---|---|
| **Unchanged** | `src/mcq_core.py`, `src/kg/graph_view.py`, the LRoleSim kernel and adapter, every v1/v2/v3 runner default, every published artefact, `EVIDENCE_TAXONOMY_V1.md`, `PHASE_B_INPUT_CONTRACT.md` |
| **Extended, defaults preserved** | `classes/candidate_validity.py` (a third policy, derived detection properties), `mcq_inputs.py` (an optional alias policy, default empty), `pipeline/phase_b2_answer_run.py` (an optional alias policy on the source-object set), `pipeline/graph_lrolesim_run.py` (effective-budget fields; the frozen CSV header is unchanged) |
| **New** | `rationale_v3/predicate_aliases.py`, `selection/granularity_clean.py`, `pipeline/phase_b2_any_answer_run_v4.py`, `scripts/run_phase_b2_any_answer_v4.py`, `tests/test_b2g_final_benchmark_safety_v4.py` |

`--v3-compatible` reproduces a B2-E/F run through the v4 code path, and
`test_the_v3_compatible_v4_config_reproduces_the_b2ef_generation` pins it.

---

## 1. §2 — the candidate-validity recount, and why it differs

The B2-E/F audit reported ≈7,384 candidate rows / 6,030 accepted / 1,307 UNKNOWN
rejected / 30 NOT_PERSON / 17 name-containment / 66 of 306 pools below the gate.
§2 forbids trusting those numbers, so they were recomputed from the artefacts on
disk: `evidence_script_b2g_candidate_policy_delta.py`.

### 1.1 Two parsing defects found and fixed in the audit itself

1. **The 52-character candidate-name truncation.**
   `run_phase_b2_any_answer_v2.print_lrolesim_ranking` prints
   `profile.uri.rsplit('/',1)[-1][:52]`. A truncated name does not resolve in
   the pinned KG, has an EMPTY observed-key set, and is therefore classified
   `UNKNOWN` — inflating exactly the number `PERSON_STRICT` rejects on. The
   recount repairs truncated names by **unique prefix match** against the
   pinned KG: 18 rows truncated, **18 repaired uniquely, 0 ambiguous**.
2. **A rank-1-to-9 parsing hole.** The rank is right-aligned in a four-character
   field, so a single-digit rank carries seven leading spaces. An early version
   of the audit regex bounded the indent at six and silently dropped the nine
   most plausible candidates of every pool (4,640 rows instead of 7,403).

The corrected row count **7,403** is confirmed independently: it is exactly the
sum of `complete_pool_size` over the 329 parsed rows of
`pre_repair_parsed_rows.json`.

### 1.2 The three-arm result (source: `Results_Answer.txt_v1_2026-08-18`)

307 Answers with a ranked pool; 7,403 candidate rows;
Answer types 226 PERSON / 81 UNKNOWN.

**DETECTION — policy-independent, computed under every arm**

| detector | count |
|---|---:|
| candidate type PERSON | 4,211 |
| candidate type NOT_PERSON | 79 |
| candidate type UNKNOWN | 3,113 |
| complete-Answer-name containment | **19** |

**REJECTION — what the active policy removed**

| arm | accepted | rejected | NOT_PERSON | UNKNOWN | name rule | pools below the gate of 10 |
|---|---:|---:|---:|---:|---:|---|
| `OBSERVE_ONLY` | 7,403 | 0 | 0 | 0 | 0 | **0 of 307** |
| `PERSON_GUARDED` | 7,340 | 63 | 44 | 0 | 19 | **3 of 307** |
| `PERSON_STRICT` | 6,050 | 1,353 | 44 | 1,292 | 17 | **66 of 307** |

The same audit over the newer `Results_Answer.txt_v2_2026-08-20` gives 7,431
rows, 59 / 1,341 rejections and 2 / 64 pools below the gate.

### 1.3 Differences from the B2-E/F figures, explained

| quantity | B2-E/F | recomputed | explanation |
|---|---:|---:|---|
| candidate rows | 7,384 | **7,403** | 7,403 is the independent sum of `complete_pool_size`; the 19-row difference is a parsing artefact of the earlier audit, not a policy change |
| accepted under `PERSON_STRICT` | 6,030 | **6,050** | follows from the row count |
| UNKNOWN rejected | 1,307 | **1,292** | −15: truncated names repaired to real nodes stop being UNKNOWN |
| NOT_PERSON rejected | 30 | **44** | +14: the same 18 repairs; several repaired nodes are confirmed NOT_PERSON |
| name-containment rejected | 17 | **17** | identical |
| pools below the gate | 66 / 306 | **66 / 307** | identical; the denominator was off by one |

### 1.4 What the numbers say about the three arms

* `PERSON_GUARDED` removes the candidates the snapshot **positively
  contradicts** (44) plus every name-containment leak (19), and costs **3 of
  307 pools**.
* `PERSON_STRICT` additionally removes 1,292 UNKNOWN candidates and costs
  **66 of 307 pools** — a 22× larger yield cost for candidates the snapshot is
  merely SILENT about. Reading that silence as a refusal is the same mistake as
  reading `L0` as falsity.
* `OBSERVE_ONLY` costs nothing and protects nothing.

**No recommendation is made here.** The three columns are the decision material.

### 1.5 Two structural findings the researcher must weigh

1. **The screen runs after the class walk has already committed.** When it drops
   a pool below the mapping gate the runner reports
   `NO_LOCALLY_MAPPING_FEASIBLE_CLASS` instead of walking on to the next ranked
   class. Muhammad is the named example: the pool falls 11 → 9 and the Answer is
   lost under BOTH acting policies, although sixteen feasible classes existed.
   Repairing this means re-entering the walk after screening, which is a
   structural change to `b2.walk_ranked_classes_for_local_mapping` and is
   **deferred**, not attempted here.
2. **The PERSON heuristic has false positives.** `Hud_(prophet)` is classified
   `NOT_PERSON` and removed under both acting policies. It is a person; the
   article simply fills no listed OUT person slot. The verdict carries the keys
   that produced it, so it is inspectable — but a final benchmark using an
   acting policy should expect this class of loss.

---

## 2. §3 — detection versus rejection

The v3 metric `candidate_topical_identity_leak_rejections` counted REJECTIONS
only, so an observe-only run published `0` while the detector had fired 19 times
corpus-wide. Zero rejections was true; zero detections was false; one field
carried both meanings.

`CandidateValidityVerdict` now publishes both, and
`phase_b2_any_answer_run_v4.candidate_screen_metrics()` reports them under
separate names:

```
candidate_type_person_detected_count        candidate_type_rejected_count
candidate_type_not_person_detected_count    candidate_name_containment_rejected_count
candidate_type_unknown_detected_count       rejected_by_rule {NONE, TYPE_RULE, NAME_RULE}
candidate_name_containment_detected_count
```

The v3 field names are preserved with their v3 meaning, annotated in place.

### Muhammad regression (§3)

`http://dbpedia.org/resource/Muhammad_in_Islam` is **detected** by
complete-name containment under every policy:

```
candidate name tokens ['muhammad','in','islam'] contain the complete
Answer name ['muhammad'] contiguously at position 0
```

Its observed slot profile is person-shaped (`birthPlace`, `father`, `mother`,
`office`, `predecessor`, `religion`, `title`), so its detected type is `PERSON`
and the type rule cannot touch it. Under `PERSON_GUARDED` and `PERSON_STRICT`
it is rejected with `reject_reason = CANDIDATE_NAME_CONTAINS_THE_COMPLETE_ANSWER_NAME`
and `rejected_by_rule = NAME_RULE` — **not** attributed to the type rule.

Corpus-wide the two counts differ by exactly 2: 19 detected, 17 rejected under
`PERSON_STRICT`, because for two candidates the UNKNOWN type rule fired first.
`PERSON_GUARDED` rejects all 19 by the name rule, since it does not act on
UNKNOWN. That difference is the whole point of recording the attribution.

Tests: `test_a_detector_may_fire_while_a_non_rejecting_policy_removes_nothing`,
`test_the_name_rule_rejects_under_both_acting_policies_and_says_so`,
`test_a_candidate_that_trips_both_detectors_is_attributed_to_one_rule`.

---

## 3. §4 — `dbp:honorificPrefix` census: DO NOT promote

Corpus-wide over the pinned snapshot:

| quantity | value |
|---|---|
| distinct subjects (OUT) | **31,747** |
| URI-valued occurrences (OUT) | 35,120 |
| distinct objects | 1,363 |
| current pedagogical tier | **3** (the default, i.e. weakest) |
| verbalization template | **none** — `VERBALIZABLE_UNKNOWN`, both directions |
| eligible under `predicate_policy_v2` | yes (not hard-rejected) |
| appears in a selected rationale | **yes** — Muhammad, `honorificPrefix → Islamic_prophet` |
| learner-facing under current policy | **yes** (see below) |

Most frequent objects: *The Honourable* (6,924), *The Right Honourable*
(4,964), *The Most Reverend* (1,822), *Excellency* (1,290), *Sir* (1,145),
*His Eminence* (1,131), *The Reverend* (1,130), *Saint* (618), *Dame* (289),
*Professor* (277).

**Conclusion: leave it at its current weak/default status.** The slot is a
FORM OF ADDRESS, not a fact about what the entity did. Adding a pedagogical tier
or a verbalization template to rescue one Answer would license "A is addressed as
*The Right Honourable* and B is not" as a learner-facing reason for roughly
31,747 subjects. The corpus-wide evidence argues against promotion, not for it.

`honorificPrefix → Islamic_prophet` is genuinely more contentful than the corpus
norm. That is an argument about ONE object, not about the predicate, and §4
forbids acting on it.

**A finding that must be recorded:** an unverbalizable fact IS currently
learner-facing. `PHASE_B_INPUT_CONTRACT.md` §3.2 says `verbalizable` is "only
barred from the main corpus", but in the kernel it is ordering key 9 only, and
`has_main_l1_selection` reads the evidence policy alone. Muhammad's selected
main-L1 rationale contains a fact with no template. This is a
documentation-versus-code contradiction, reported rather than silently patched.

---

## 4. §5 — predicate-slot aliases: `dbp:field` / `dbp:fields`

### 4.1 The defect, measured

| entity | `dbp:field` (OUT) | `dbp:fields` (OUT) |
|---|---|---|
| `Robert_Boyle` | — | Chemistry, Physics |
| `Joseph_Black` | Chemistry, Medicine, Physics | — |

Under exact keying the Answer's key is `(dbp:fields, OUT)`, `Joseph_Black`
records nothing under it, `O_d(κ) = ∅`, and the pair is classified
`L0_ABSENCE_ONLY_OBSERVED` — "the snapshot records no field for Joseph Black".
That is not a weak observation, it is a **false** one.

### 4.2 The corpus evidence for the family

| quantity | value |
|---|---|
| subjects using `dbp:field` only | 20,484 |
| subjects using `dbp:fields` only | 14,729 |
| subjects using **both** | **1** |
| distinct objects, `field` / `fields` | 4,421 / 4,706 |
| shared objects | 1,603 (Jaccard 0.213) |

The near-perfect subject disjointness is the decisive signal: an editor picks
one spelling. The shared vocabulary is unambiguously academic disciplines
(Painting, Mathematics, Physics, Botany, Chemistry, Computer science, …).

### 4.3 What the alias layer does, and what it cannot do

`rationale_v3/predicate_aliases.py` unions the CANDIDATE's observed objects
across the family, in the same direction, **before** classification:

* raw predicates and raw provenance are preserved — the rationale still prints
  `dbp:fields`, because that is what the snapshot records for the Answer;
* the pinned KG is not rewritten; no triple is added or removed;
* IN and OUT stay separate keys;
* an exact object match under an alias reaches `NOT_COVERED` — the candidate
  SUPPORTS the proposition — and can never be read as absence;
* the union can only ever REMOVE a distinction. Enlarging `O_d(κ)` can move a
  pair L0→L1 or →NOT_COVERED, never toward a stronger discrimination, and it
  can never create an exclusion.

The semantic-index source-object set is widened by the same policy, because that
set IS the cache key: an index built without the aliases would omit exactly the
objects the aliased lookup asks about.

### 4.4 The workplace family: audited, NOT admitted

| member | subjects | distinct objects |
|---|---:|---:|
| `dbp:workplaces` | 22,710 | 8,414 |
| `dbp:workInstitutions` | 4,922 | 3,337 |
| `dbp:workInstitution` | 4,175 | 2,527 |
| `dbp:workplace` | **2** | 2 |

Pairwise SUBJECT overlap is **0** for every pair; object Jaccard is 0.16–0.21;
the top objects of the three real members are the same universities. The
measurement is *compatible* with equivalence — but no DEFECT has been
demonstrated for this family, and §5 admits a family only on audited evidence of
a defect it repairs. They stay in `AUDITED_CANDIDATE_FAMILIES` as **NOT
ADMITTED**, with the numbers above, so the decision is inspectable.

### 4.5 Robert Boyle / Joseph Black regression

| arm | selected distractors | rationale | local anonymity |
|---|---|---|---|
| A (v3-compatible, no aliases) | Stoney (1), **Joseph Black (2)**, Schrödinger (3) | `influenced → Isaac_Newton; influenced ← Otto_von_Guericke` | 0 / 26 |
| B (v4 candidate, aliases on) | Stoney (1), **Joseph Black (2)**, Schrödinger (3) | same | **1 / 26** |

The selected triple and rationale are unchanged — the winning rationale never
used the field slot. What the alias policy changed is the EVIDENCE PROFILE: with
`dbp:field`/`dbp:fields` unioned, Joseph Black now supports Boyle's field
proposition, the local anonymity count rises from 0 to 1, and no fact can any
longer claim an absence that the snapshot contradicts. Tests:
`test_an_alias_match_becomes_not_covered_not_l0`,
`test_an_alias_can_only_ever_weaken_a_distinction`.

---

## 5. §6 — semantic-granularity safety

### 5.1 The versioned switch

`selection/granularity_clean.py` adds `granularity-risk-policy ∈ {report-only,
require-clean}`. It never converts a risky L1 into L0, never invents
`NOT_COVERED`, never invents a fact, never grows `|R*|` and never substitutes a
weaker evidence policy. When no clean minimum-cardinality rationale exists it
reports `NO_GRANULARITY_CLEAN_MAIN_RATIONALE` and marks the item not
learner-facing, with the item still published.

It lives OUTSIDE the frozen kernel and reproduces the kernel exactly when the
admissibility predicate admits everything — asserted on the eight frozen pilot
Answers under all three objectives
(`test_the_filtered_search_reduces_to_the_frozen_kernel`).

### 5.2 Measured delta, 11-Answer regression set

| arm | any kernel selection | student-showable | exact ranks [1,2,3] | granularity statuses |
|---|---:|---:|---:|---|
| B `report-only` | 11 | 11 | 11 | 11 × no-risk |
| C `require-clean` | 11 | 11 | **9** | 8 × no-risk, **3 × clean alternative selected** |

`require-clean` changed three items: **Otto Hahn** (distractor 3 moved from
John Gofman, rank 3, to Irène Joliot-Curie, rank 4) and **Niels Bohr**
(Aage Bohr, rank 3 → Per Bak, rank 4) changed their DISTRACTOR TRIPLE;
**Richard Kuhn** changed only its rationale. Yield did not fall on this set;
rank retention did (11 → 9 exact [1,2,3]). No Answer hit
`NO_GRANULARITY_CLEAN_MAIN_RATIONALE` here — but Otto Hahn and Niels Bohr each
had **zero** clean covers for their original triple, so on a corpus where no
alternative triple exists that status is reachable.

The cost is visible per case. Richard Kuhn has 4 minimum-cardinality covers, 3
of them clean; the risky winner `birthPlace → Vienna; field → Chemistry` wins on
ranking field 3 (`-l1`, −4 vs −3), so the clean alternative
`birthPlace → Vienna; knownFor ← Goethe_Prize` carries **one fewer L1
incidence**. `require-clean` buys granularity safety with evidence-profile
strength inside the same `|R*|` and the same minimum level.

### 5.3 Otto Hahn — why one verified edge would not be enough

Pinned snapshot: `Otto_Hahn dbp:field → {Nuclear_chemistry, Radiochemistry}`;
`Marie_Curie dbp:field → {Chemistry, Physics}`.

Even a verified `Radiochemistry —broader→ Chemistry` edge would **not**
establish `Marie_Curie dbp:field Radiochemistry`. Containment runs one way: an
entity recorded under the SUB-field entails the broader claim, so
*candidate-object-under-claim* removes contrast. The reverse — the Answer claims
the narrow field and the candidate records the broad one — entails nothing.
"Curie worked in chemistry" does not place her in every chemical subfield, and
asserting it would be inventing a fact from a hierarchy edge.

The snapshot models nothing here: the nodes Chemistry, Radiochemistry,
Biochemistry, Nuclear_chemistry, Physics have **zero outgoing edges of any
predicate**. The run therefore reports
`HIERARCHY_NOT_MODELLED_FOR_THESE_OBJECTS`, which is the true state of the
evidence. **Otto Hahn remains a named Failure Analysis case**, and no
per-Answer live-web fact was added.

Covers: `field → Radiochemistry` is one of **2** minimum-cardinality covers for
the selected triple, and **0 of the 2 are clean**, which is why `require-clean`
had to change the triple rather than the rationale.

### 5.4 Niels Bohr — the 36 covers, audited

Under the **v3-compatible** configuration (the one the 36 figure came from):

* `|R*| = 3`, evidence policy `main-l1`, **36 minimum-cardinality covers**;
* **0 of the 36 are granularity-risk free**;
* the winner `influences ← Jane_Dewey; doctoralAdvisor ← Hans_Kramers;
  field → Theoretical_physics` is separated from the runner-up at ranking
  **field 10, `label_length_sum` (41 vs 42)** — a cosmetic tie-break, reached
  because every earlier field ties across all 36.

So the answer to §6's question is explicit: **there is no zero-granularity-risk
alternative of the same minimum cardinality for that triple.** The risk is not a
preference the ranking made; it is a property of every minimum cover.

Under the **v4 candidate** configuration `|R*|` falls to 2 and the cover count
to 6 (the field alias union lets one fact cover more candidates), and **0 of the
6 are clean**. `require-clean` therefore changes the triple.

### 5.5 Socrates — and the detector's silence

Pinned snapshot:

| entity | `dbp:schoolTradition` |
|---|---|
| Socrates | Classical_Greek_philosophy |
| Plato | Platonism |
| Epicurus | Epicureanism |
| Plotinus | Neoplatonism |
| Aristotle | *(none)* |

Corpus census: **2,707 subjects, 1,114 distinct objects**. The vocabulary mixes
eras with doctrines; the most frequent values are specific schools (Analytic
philosophy 514, Continental philosophy 377, Neoplatonism 25, Aristotelianism 24,
Thomism 24). `Classical_Greek_philosophy` is used by exactly **2 subjects in the
entire snapshot** — Socrates and Diotima of Mantinea.

Nothing here is fabricated: the snapshot asserts no relation between
`Classical_Greek_philosophy` and `Platonism`, `Epicureanism` or `Neoplatonism`,
and none is asserted by this audit.

**The critical finding: `require-clean` does NOT protect Socrates.** No relation
domain in `semantic_relation_policy_v2.json` governs `dbp:schoolTradition`, so
the granularity detector never fires, the selected rationale carries
`granularity_risk = 0`, and the policy sees nothing to repair. The broad-vs-
specific risk is real and undetected.

**Socrates remains a Failure Analysis case** until a frozen, versioned and
defensible philosophical-tradition relation source exists. A cheap partial
mitigation the researcher may consider — NOT implemented here — is to declare a
`schoolTradition` relation domain with `REPORT_UNMODELLED_OBJECTS`, which would
at least surface the risk as `HIERARCHY_NOT_MODELLED` rather than silence.

### 5.6 Richard Kuhn

`dbp:field → Chemistry` (the broad value), distractors Cori, Kapeller-Adler,
Tuppy in an `Austrian biochemists` class. Granularity risk 2
(`HIERARCHY_NOT_MODELLED`) in arms A and B; `require-clean` substitutes the
clean `birthPlace → Vienna; knownFor ← Goethe_Prize` at the cost of one L1
incidence. Broad/narrow Chemistry–Biochemistry remains unmodelled in the
snapshot.

---

## 6. §7 — rationale objective v3 as the v4 candidate default

`--rationale-objective` defaults to **v3** in the v4 runner. v1, v2 and v3 are
all still selectable; the v3 runner still defaults to v2 and `mcq_core`'s module
default is still v1. The choice is recorded in the run manifest.

### Augustus, old-v2 versus new-v3, side by side

Selected triple in BOTH arms: `Tiberius (1)`, `Trajan (2)`, `Domitian (3)` —
scientifically comparable, unchanged.

| | arm A — objective v2 | arm B — objective v3 |
|---|---|---|
| `|R*|` | 1 | 1 |
| minimum-cardinality covers | 42 | 42 |
| covers free of granularity risk | 42 | 42 |
| **selected rationale** | `successor → Tiberius` | **`deathPlace → Nola`** |
| `option_reference_conflict` | **1** | **0** |
| exclusion basis | `SCOPED_EMPIRICAL` | `NONE` |
| deciding ranking field | 5 `-scoped_empirical` (−3 vs 0) | 9 `pedagogical_tier_sum` (1 vs 2) |

Under v1/v2, `successor → Tiberius` is the ONLY cover reaching
`scoped_empirical_incidences = 3`, and field 5 maximises that annotation — so an
annotation that no evidence LEVEL depends on decided the rationale, and the
winning clue printed one of the four choices. v3 places the granularity risk and
the option-reference conflict ABOVE the annotation; the complete evidence-LEVEL
profile (fields 1–4) is untouched, so v3 can no more buy a weaker level than v2.

`dbp:successor` was **not** blacklisted, no evidence level changed, and `|R*|`
did not grow.

---

## 7. §8 — the M1 node budget

`max_nodes` is now a declared CLI/config parameter recorded in the manifest.
The frozen value 1200 is unchanged in `kg/graph_view.py` and in every v1/v2/v3
path; the v4 candidate value is **5000**.

### Controlled comparison

| Answer | budget | class | offered | retained | nodes | edges | lost to budget | Answer base | status |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| George Washington | 1200 | `Presidents_of_the_United_States` | 11 | 5 | 1,128 | 0 | **6** (`WOULD_EXCEED_MAX_NODES`) | 247 | `GRAPH_INFEASIBLE` |
| George Washington | 2000 | same | 11 | **11** | 1,711 | 8,210 | 0 | 247 | `SUCCESS_FULL_EXACT` |
| George Washington | 5000 | same | 11 | **11** | 1,711 | 8,210 | 0 | 247 | `SUCCESS_FULL_EXACT` |
| Kingdom of Italy | 1200 | `Italian_states` | 71 | 0 | — | — | **71** (`ANSWER_BASE_EXCEEDS_BUDGET`) | **3,026** | `GRAPH_INFEASIBLE` |
| Kingdom of Italy | 5000 | `Italian_states` | 71 | **49** | 4,999 | 13,064 | **22** (`WOULD_EXCEED_MAX_NODES`) | 3,026 | `SUCCESS_FULL_EXACT` |

The 2000-node arm is included because it bounds the answer: George Washington
needs 1,711 nodes and nothing more, so 5000 is not the minimum that repairs him
— it is the value that also clears Kingdom of Italy's 3,026-node base. Runtime
for the whole 11-Answer regression batch was ≈4 minutes wall clock at either
budget, dominated by the one-off pinned-KG load (~40 s) rather than by the graph
stage; peak process RSS was not instrumented and is reported as not measured.

*(George Washington's arms ran offline; both Kingdom-of-Italy arms required the
live retrieval recorded in §15 of this report.)*

**The two failures have different causes and only one is a "budget" failure.**
George Washington lost six candidates whose neighbourhoods did not fit — exactly
what a larger budget recovers. Kingdom of Italy's OWN one-hop neighbourhood is
3,026 nodes, so at 1200 the graph could not even be started and **no candidate
was ever considered**; no class choice could have rescued it at that budget.

At 5000 the budget is still binding for Kingdom of Italy (4,999 of 5,000 nodes
used, 22 candidates refused). Raising the constant did not make the problem go
away; it moved the threshold past this Answer's base. That is why the
diagnostics, not the constant, are the deliverable:

```
lost_would_exceed_max_nodes / lost_answer_base_exceeds_budget /
lost_candidate_cap_reached / answer_base_node_count /
answer_base_exceeds_budget / node_budget_bound / candidate_cap_reached
```

plus a one-sentence `explanation` naming which of the three is responsible.

### Selected distractors and rationale (5000 arm)

| Answer | distractors (rank) | \|R*\| | rationale | MCQ | pool | covers |
|---|---|---:|---|---|---:|---:|
| George Washington | Thomas Jefferson (1), Andrew Jackson (2), James Madison (3) | 1 | `party → Independent_politician` | MCQ-L1 | 11 | — |
| Kingdom of Italy | Republic of Venice (1), Kingdom of Naples (2), Grand Duchy of Tuscany (3) | 1 | `birthPlace ← Totò` | MCQ-L1 | 49 | 2,611 |

The Kingdom-of-Italy rationale is worth a researcher's eye: it is logically
sound (an IN-direction `birthPlace` fact that the three other polities do not
record) and pedagogically thin, and it was chosen from **2,611**
minimum-cardinality covers. Rank retention is exact — the selected triple is
LRoleSim ranks 1, 2, 3 — and the distractors are the historically right kind of
entity. This is a verbalization and fact-selection question for a later phase,
not an evidence defect, and nothing was changed to improve it.

---

## 8. §9 — `Kingdom_of_Italy → Category:Italian_states`

### 8.1 What the current rule says

`Category:Italian_states` is annotated **`soft_overlap`** with evidence
`italy~italian:SHORT_PREFIX`. It is NOT a hard leak, and it was selected as the
first locally mapping-feasible class.

The three existing levels already ARE the reason codes §9 asks for:

| code | meaning | corpus count (518 Answers, 6,770 pairs) |
|---|---|---:|
| `hard_leak` | answer-identifying derivation/eponymy | 19 |
| `soft_overlap` | topical/adjectival overlap, kept | 105 |
| `no_leak` | clean class membership | 6,646 |

### 8.2 False-positive measurement of a candidate HARD rule

A candidate adjectival/demonym rule was applied corpus-wide (stem floor 4
instead of the frozen 6; suffixes -ian/-ish/-ese/-ic/-an/-n; stem must equal the
Answer token or the Answer token minus its final vowel):

| quantity | value |
|---|---:|
| (Answer, class) pairs examined | 6,770 |
| pairs where the candidate rule fires | 5 |
| pairs whose verdict it would change | **3** |
| selected classes it would remove | **2** |

The three pairs it would newly mark HARD:

| Answer | class | selected? |
|---|---|---|
| `Russo-Japanese_War` | `Category:1905_in_the_Russian_Empire` | **yes** |
| `Russo-Japanese_War` | `Category:Wars_involving_the_Russian_Empire` | no |
| `Kingdom_of_Italy` | `Category:Italian_states` | **yes** |

**All three are false positives by inspection.** "1905 in the Russian Empire"
and "Wars involving the Russian Empire" are broad topical classes containing
many events; "Italian states" legitimately describes every choice of a
Kingdom-of-Italy item. None of the three hands the learner the Answer.

**Recommendation: do not introduce a HARD adjectival rule.** Retain
`Italian_states` and report the soft topical overlap, which is what the system
already does. No code change is proposed for §9.

### 8.3 Does the class choice change the budget outcome independently?

Measured by rerunning the same Answer under the IDF-only class ranking
(`--no-sbert`), which selects a DIFFERENT first feasible class, at both budgets:

| class | offered to M1 | budget | retained | nodes | lost | status |
|---|---:|---:|---:|---:|---:|---|
| `Italian_states` (85 members) | 71 | 5000 | **49** | 4,999 | 22 `WOULD_EXCEED` | `SUCCESS_FULL_EXACT`, budget BINDING |
| `Italian_states` | 71 | 1200 | 0 | — | 71 `ANSWER_BASE_EXCEEDS` | `GRAPH_INFEASIBLE` |
| `…established_in_1861` (16 members) | 10 | 5000 | 7 | 3,521 | 3 `WOULD_EXCEED` | `GRAPH_INFEASIBLE` (gate needs 10) |
| `…established_in_1861` | 10 | 1200 | 0 | — | 10 `ANSWER_BASE_EXCEEDS` | `GRAPH_INFEASIBLE` |

**Answer, in two parts.**

*At 1200 the class is irrelevant.* The Answer's own 3,026-node neighbourhood
exceeds the budget, so no candidate is ever considered and every class fails
identically. No class-leak decision could rescue this Answer at that budget.

*At 5000 the class decides the outcome, but not in the direction one might
expect.* The 3,026-node base leaves roughly 1,974 nodes for candidates, so the
class must OFFER enough of them that at least ten still fit.
`Italian_states` offers 71 and keeps 49; the smaller
`…established_in_1861` offers 10, loses 3 to the budget and falls below the
gate. **Rejecting `Italian_states` would therefore lose the Answer entirely** —
which is an additional, independent reason not to promote the adjectival overlap
to a HARD leak on the strength of three false positives.

The two effects are separable and were separated: the budget change alone
explains 1200 → 5000, and the class change alone explains the difference between
the two 5000-node rows.

*(An earlier run of the same `--no-sbert` command, made before the live
retrieval had populated the class-member cache, walked past two classes whose
member pages were missing and selected `…disestablished_in_1946` instead; that
class offered 38 candidates, retained all 38 in 4,728 nodes and succeeded. The
observation is consistent with the reading above — more offered candidates
survive the base — and is recorded here because the selected class of a
`--no-sbert` run depends on which member pages the cache holds.)*

---

## 9. §10 — class-leak rejection metrics

The v3 batch metric was

```python
"hard_class_leak_rejections": sum(
    sum(1 for entry in r.class_ranking_rejections)
    for r in results if hasattr(r, "class_ranking_rejections"))
```

and `AnswerRunResult` has no such attribute, so the `hasattr` guard excluded
every result and the metric published a hard zero that read like a finding.

v4 carries `class_rejection_records(features)` onto every result and reports:

```
answers_in_batch / answers_with_rejection_records / total_classes_discovered /
feasible_classes / total_rejected_classes / rejection_records_collected /
hard_class_leak_rejections / hard_leaking_classes_by_any_rejection_reason /
too_small_rejections / too_generic_rejections / junk_category_rejections /
invalid_uri_rejections / count_unavailable_rejections /
primary_rejection_codes / all_independent_rejection_reasons
```

`answers_with_rejection_records` is printed beside every count precisely so that
a future zero can be told apart from a wiring failure.

On the 11-Answer regression set the corrected metric reports **373 classes
discovered, 279 feasible, 94 rejected, 94 rejection records collected, 20 HARD
class-leak rejections as the primary gate and 31 rejected classes that hard-leak
under any gate**, where v3 reported **0** for every one of the leak figures. A
class that failed several gates
keeps one declared PRIMARY status and every independent reason stays
inspectable, so `hard_leaking_classes_by_any_rejection_reason` can exceed
`hard_class_leak_rejections` by design.

Output in JSON (`batch_metrics.json`), CSV (`--metrics-csv`) and the
Markdown section **J. Class-ranking rejections**.

Tests: `test_class_rejection_metrics_count_every_gate`,
`test_a_missing_attribute_is_visible_instead_of_silently_zero`,
`test_the_v3_expression_would_have_reported_zero`.

---

## 10. §11 — L1+ LRoleSim rank-retention metrics

The existing any-kernel-selection block is reported **unchanged**, so every
earlier figure stays comparable. A parallel block adds the student-showable
denominator `L1+ = MCQ-L1 ∪ MCQ-L2`, with `n_L1_plus`, the exact-[1,2,3] count
and percentage, and n/mean/median/min/max for all selected ranks, slot 1, slot 2,
slot 3 and the candidate rank sum. Nothing is hard-coded — 245/278 does not
appear anywhere in the code or the metrics.

Also reported, unchanged: `SCOPED_EMPIRICAL` rate among L1, direct-identifier
rate, local anonymity distribution, granularity-risk count/rate by state and
option-reference-conflict count/rate.

`direct_identifier = True` is described as **local structural specificity only**
in the metric note, in `CLAUDE.md` §12 and in `10_current_state_post_b2ef.md`.
It is never described as "easy for humans".

---

## 11. §12 — the "57 of 329 lost |R*|" wording

Measured over `Results_Answer.txt_v1_2026-08-18`:

| quantity | value |
|---|---:|
| batch-table rows | 329 |
| rows with a selection | 304 |
| rows showing a cardinality | 257 |
| rows whose cell was truncated | 49 |
| **rows that LOST the cardinality to truncation** | **47** |
| rows with no selection at all | 25 |

`257 + 47 + 25 = 329`. Cross-check against the machine-readable record: 304 of
329 Answers carry a `rationale_size` (259 × |R*|=1, 40 × |R*|=2, 5 × |R*|=3);
the 25 without one are the 25 Answers that produced **no selection**, a genuine
feasibility outcome.

**Conclusion.** The defect was presentation: the v2 cell was
`"; ".join(facts) + " (|R*|=N)"` truncated to 46 characters, so the cardinality,
written last, was the first field removed. **Rationale generation failed for
none of the 47.** The correct figure is **47**, not 57; whichever count produced
"57", it matches neither the truncation count nor the no-selection count, and
the scientific point is unchanged.

The repair is structural: `|R*|` has its own column in the v3 and v4 tables and
its own metric field, so no display limit can remove it. Tests:
`test_the_v2_truncation_defect_is_reproducible`,
`test_the_v3_and_v4_tables_keep_the_cardinality_in_its_own_column`.

---

## 12. §15 — the named regression matrix

Arms, all over the same 11-Answer input file
(`regression_answers_b2g.txt`), offline replay:

| arm | configuration |
|---|---|
| **A** | v3-compatible — objective v2, `max_nodes` 1200, no aliases, report-only |
| **B** | v4 candidate — objective v3, `max_nodes` 5000, field alias, report-only |
| **C** | B + `require-clean` |
| **D** | B + `person-guarded` |
| **E** | B + `person-strict` |

### 12.1 Arm roll-up

| arm | any kernel selection | student-showable | no selection | L1+ exact [1,2,3] | candidate name det/rej | candidate type rej | granularity statuses |
|---|---:|---:|---:|---:|---|---:|---|
| A | 9 | 9 | 2 | 9 / 9 (100%) | 3 / 0 | 0 | 9 × no-risk |
| B | **11** | **11** | 0 | 11 / 11 (100%) | 3 / 0 | 0 | 11 × no-risk |
| C | 11 | 11 | 0 | **9** / 11 (81.8%) | 3 / 0 | 0 | 8 × no-risk, **3 × clean alternative selected** |
| D | 10 | 10 | 1 | 10 / 10 (100%) | **3 / 3** | 1 | 10 × no-risk |
| E | 9 | 9 | 2 | 9 / 9 (100%) | **3 / 3** | **25** | 9 × no-risk |

Over all five arms the candidate screen saw 217 candidate rows and detected
119 PERSON, 1 NOT_PERSON, 97 UNKNOWN and 3 complete-name containments — the same
numbers in every arm, because DETECTION is policy-independent.

Class ranking, identical in every arm: **373 classes discovered, 279 feasible,
94 rejected, 94 rejection records collected, 20 HARD class-leak rejections as
the primary gate and 31 rejected classes that hard-leak under any gate.** Under
the v3 metric all of these read as **0**.

### 12.2 Case by case

| Answer | A | B | changed by | C | D | E |
|---|---|---|---|---|---|---|
| **Robert Boyle / Joseph Black** | ok, anon 0/26 | ok, **anon 1/26** | §5 alias union | ok | ok | ok, pool 25 → 15 |
| **Muhammad / Muhammad_in_Islam** | ok, leak kept | ok, leak kept | — | **lost**: pool 11 → 9, below the gate | **lost** | same |
| **Otto Hahn / Marie Curie** | risk 3, anon 3/25 | risk 3, **anon 5/25** | §5 alias union | **triple changed**: Gofman (3) → Irène Joliot-Curie (4) | ok | ok, pool 24 → 21 |
| **Marie Curie** | ok | ok | — | ok | ok | ok, pool 13 → 11 |
| **Richard Kuhn** | risk 2 | risk 2 | — | **rationale changed** to `birthPlace → Vienna; knownFor ← Goethe_Prize` | ok | ok, pool 11 → 10 |
| **Niels Bohr** | `\|R*\|` = 3, 36 covers | **`\|R*\|` = 2**, 6 covers | §5 alias union | **triple changed**: Aage Bohr (3) → Per Bak (4) | ok | **lost**, pool below the gate |
| **Socrates / Plato / Epicurus / Plotinus** | risk 0 (undetected) | risk 0 (undetected) | — | unchanged — the detector is silent | ok | ok |
| **Augustus / Tiberius** | `successor → Tiberius`, OptRef **1** | **`deathPlace → Nola`, OptRef 0** | §7 objective v3 | ok | ok | ok, pool 13 → 12 |
| **George Washington** | `GRAPH_INFEASIBLE` (6 over budget) | **success, 11 candidates** | §8 `max_nodes` | ok | ok | ok |
| **Kingdom of Italy** | `GRAPH_INFEASIBLE` (base 3,026 > 1200) | **success, 49 candidates** | §8 `max_nodes` | ok | ok | ok |
| **Ashikaga Takauji** | ok, `direct_identifier` diagnostic only | ok | — | ok | ok | ok |

Arm A's two failures are exactly the two `max_nodes` cases; arm E's two are
Muhammad and Niels Bohr, both lost because the UNKNOWN rule drops the pool below
the local-mapping gate.

### 12.3 Ashikaga Takauji — `direct_identifier` is a diagnostic only

Selected distractors `Ashikaga Yoshiakira (1)`, `Ashikaga Yoshimitsu (2)`,
`Prince Moriyoshi (3)`; rationale
`regent ← Emperor_Go-Daigo; regent ← Emperor_Go-Murakami`; `|R*| = 2`;
MCQ-L1; anonymity 1/16 with `direct_identifier_flag = True`.

The flag rejected nothing. It is objective key 13 — a tie-break consulted only
after twelve other fields — and the item is `SUCCESS_FULL_EXACT` in all five
arms. The two same-family candidates also survive the §8 name rule, which
requires the Answer's COMPLETE token sequence contiguously:
`['ashikaga','yoshiakira']` does not contain `['ashikaga','takauji']`.

### 12.4 The name rule on a non-person Answer

Kingdom of Italy's pool contains `Kingdom_of_Italy_(Holy_Roman_Empire)` and
`Kingdom_of_Italy_(476–493)`. Both are **detected** by complete-name containment
and both are rejected by the NAME rule under `person-guarded` and
`person-strict`. Whether two genuinely different polities that share a name
prefix should be refused as distractors is a pedagogical judgement, not a
correctness question, and it is recorded here rather than decided: the
`observe-only` default keeps them, and the detection is published either way.

### 12.5 Attribution

For every changed case the generic rule responsible is named in the "changed by"
column of §12.2. No Answer-specific branch exists in any shipped module:
`test_no_named_regression_answer_is_a_production_branch` tokenizes
`candidate_validity.py`, `predicate_aliases.py`, `granularity_clean.py`,
`phase_b2_any_answer_run_v4.py` and `run_phase_b2_any_answer_v4.py`, discards
every comment and string token, and asserts that no named regression Answer
survives in executable code.

## 13. §13 — documentation audit

| Document | Action | Reason |
|---|---|---|
| `CLAUDE.md` | updated, 159 lines | work order was stale (steps 1-3 complete); required-context list rewritten; module boundaries now match the tree; two terminology rules added (§11 scoped-empirical direction, §12 direct-identifier) |
| `docs/context/00_context_index.md` | updated | new files added to the read-order table; long handoffs marked HISTORICAL |
| `docs/context/10_current_state_post_b2ef.md` | **new** | compact current state |
| `docs/context/11_final_benchmark_candidate_policy.md` | **new** | each open configuration choice with its measured cost |
| `EVIDENCE_TAXONOMY_V1.md` | **not modified** | no contradiction with current frozen semantics was found |
| `PHASE_B_INPUT_CONTRACT.md` | **not modified**, contradiction REPORTED | §3.2 says an unverbalizable fact is "barred from the main corpus"; the kernel treats `verbalizable` as ordering key 9 only and `has_main_l1_selection` reads the evidence policy alone. Muhammad's selected main-L1 rationale contains a template-less fact. Reporting first is what §13 requires |
| B2/B3 handoff (900 lines), Prompt-8C handoff, Amano walkthrough | annotated as HISTORICAL in the index | not mandatory full reads |

**Scoped-empirical wording.** The implementation ranks MORE scoped-empirical
incidences higher (`-scoped_empirical_incidences`, field 5 under v1/v2 and field
7 under v3). The existing handoff already says "more scoped-empirical
dependencies", so no correction was needed there; the statement is now also
explicit in `CLAUDE.md` and in the two new context files. No historical artefact
was rewritten.

---

## 14. §14 — planned benchmark metadata

Recorded as EVALUATION METADATA ONLY in
`docs/context/11_final_benchmark_candidate_policy.md`. Cohort labels are carried
on output rows and are never passed to the class ranker, the M1 graph, LRoleSim,
the evidence classifier or the selection kernel — asserted by the runner's own
banner and by the cohort note in every metrics block.

**This is not the final publication benchmark and is not labelled as one.**
