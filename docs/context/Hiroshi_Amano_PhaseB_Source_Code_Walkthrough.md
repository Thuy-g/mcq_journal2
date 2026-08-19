# Hiroshi Amano — a line-by-line walkthrough of what the Phase-B source code
# actually does

**Answer:** `http://dbpedia.org/resource/Hiroshi_Amano`
**Run traced:** the real offline replay of `scripts/run_phase_b2_any_answer_v3.py`
(`--v2-compatible` arm), which reproduces the 329-Answer development report for
this Answer exactly — same class, same distractor triple, same |R\*|, same
rationale, same anonymity count.
**Pinned local KG:** `data/infobox.pickle_EnglishVersion_EntityType`,
SHA-256 `e230c5b95e20093631697624d9c46f30a14081b3f415d5027ffaf313bdbbea1b`.

Every number below is copied from that run's artifacts
(`answer_identity.json`, `class_ranking_complete.csv`,
`class_attempts_and_mapping.csv`, `complete_lrolesim_ranking.csv`,
`candidate_fact_evidence.csv`, `final_selection.json`). Nothing is a toy
example and nothing is recomputed by hand.

---

## The one thing to understand before anything else

> **The three distractors are NOT chosen first and then explained.**

A reader who assumes "take the LRoleSim top 3, then find a rationale" cannot
explain this Answer at all, because the selected distractors are **ranks 2, 3
and 4** — not 1, 2, 3. What actually happens is:

1. every candidate triple in the declared search scope is enumerated —
   here **all C(24, 3) = 2,024** of them;
2. each triple is tested for FULL COVERAGE under a set-cover with at most
   ρ = 3 facts — **969 of the 2,024 survive**;
3. the survivors are ordered by ONE lexicographic six-key objective, and the
   smallest key wins.

The rationale is part of the objective (key 4), not a post-hoc justification.
Rank 1, Isamu Akasaki, is excluded because **no eligible Answer fact reaches L1
against him** — he is Amano's own doctoral advisor and shares his university —
so every triple containing him fails step 2 under the `main-l1` policy.

---

## 1. CLI entry point

`scripts/run_phase_b2_any_answer_v3.py`

```
main()                              # argument parsing, the network gate
  -> runner_config_from_args()      # which VERSIONED policies this run uses
  -> load_local_kg()                # kg/loader.py, SHA-256 verified before use
  -> build_context()                # every client, constructed AFTER the gate
  -> run_one_answer()               # stages A .. L2, below
```

`main()` refuses to run without exactly one of `--allow-network` /
`--offline-replay`; under offline replay the SPARQL client is
`run_phase_b2_any_answer_v2.OfflineSparqlClient`, which has **no transport at
all** and raises on a cache miss. "This replay issued no HTTP" is therefore a
property of the object graph, not a claim about which branch ran.

---

## 2. Answer URI identity — stage [A]

`classes/answer_identity.py :: resolve_answer_identity()`

Three URIs are kept apart, because they answer three different questions:

| field | value for Amano | who consumes it |
|---|---|---|
| `original_uri` | `.../Hiroshi_Amano` | the immutable audit identity |
| `remote_query_uri` | `.../Hiroshi_Amano` | the CURRENT `dcterms:subject` query |
| `local_kg_uri` | `.../Hiroshi_Amano` | every local graph / evidence / LRoleSim stage |

```
local_index              2152906
local_resolution_method  ORIGINAL_URI_IN_LOCAL_KG
local_lookup_form        BRACKETED          # the pickle keys URIs as <http://…>
remote_redirect_status   NO_REDIRECT
```

For this Answer all three coincide. They do not always: an entity renamed since
the March-2023 dump needs the historical spelling locally and the current one
remotely, which is why the record carries three fields rather than one.

---

## 3. v6 class extraction — stage [B]/[C]

`src/category_extractor_v6.py :: extract_answer_features()` then
`rank_feasible_classes(features, alpha)`

Stage 1 applies six HARD feasibility gates in a fixed order (valid Category
URI, not administrative, member count known, ≥ 10 eligible members, ≤ 5,000
members, no HARD class-name leak). Stage 2 encodes the Wikipedia lead with
SBERT once. Stage 3 fuses two RANKS:

```
combined_score = alpha * normalized_sbert + (1 - alpha) * normalized_idf
               = 0.7  * nSBERT           + 0.3            * nIDF
```

The top of Amano's 11-class feasible ranking:

| rk | class | n_c | nIDF | nSBERT | score |
|---:|---|---:|---:|---:|---:|
| 1 | `Category:Japanese_Nobel_laureates` | 28 | 0.909 | 1.000 | **0.9727** |
| 2 | `Category:21st-century_Japanese_physicists` | 15 | 1.000 | 0.909 | 0.9364 |
| 3 | `Category:Members_of_the_Japan_Academy` | 29 | 0.818 | 0.727 | 0.7545 |
| 4 | `Category:Nobel_laureates_in_Physics` | 218 | 0.182 | 0.818 | 0.6273 |
| 5 | `Category:Nagoya_University_alumni` | 63 | 0.545 | 0.636 | 0.6091 |

`raw_idf` for rank 1 is 12.3886 = `standard_idf(28, 6_721_370)`; the
`normalized_*` columns are rank-normalised within this Answer's own class set,
which is what makes the two heterogeneous features addable at all.

---

## 4. The selected class — stage [E]

`src/pipeline/phase_b2_answer_run.py :: walk_ranked_classes_for_local_mapping()`

The walk descends the ranking and stops at the FIRST class that passes the
local-mapping gate (≥ `LOCAL_MAPPING_GATE` = 10 mapped candidates, compared by
LOCAL NODE INDEX). From `class_attempts_and_mapping.csv`:

```
rank 1  Category:Japanese_Nobel_laureates   MAPPING_FEASIBLE
        28 remote members -> 24 exact + 1 redirect, 1 excluded as the Answer,
        3 unresolved  =>  24 mapped candidates excluding the Answer  >= gate 10
rank 2  Category:21st-century_Japanese_physicists   NOT_ATTEMPTED_EARLIER_CLASS_SELECTED
rank 3+ ... likewise NOT_ATTEMPTED
```

> The selected class is the **first locally mapping-feasible** class of an
> automatic ranking. It is **not** a globally optimal class: ranks 2 and below
> were never tested, and the report says so on its own line.

---

## 5. Class-member retrieval and 6. pinned local mapping

`classes/member_mapper.py`

* `ClassMemberRetriever.retrieve()` pages the class roster through a SQLite
  page cache; under offline replay a miss raises `OfflineCacheMissError`
  rather than returning an empty roster.
* `map_class_members()` is PURE and runs five steps in this order:
  normalize → exact `url_index` lookup → frozen-redirect fallback →
  deduplicate by final LOCAL INDEX → **exclude the Answer by local index**.

The last step is why the Answer's pinned spelling matters: exclusion compares
`local_index`, not URI strings, so a renamed entity cannot slip in as its own
distractor.

---

## 7. M1 graph construction — stage [F]

`src/pipeline/graph_lrolesim_run.py :: attempt_class_graph()`, budgeted by
`kg/graph_view.py :: fit_ordered_candidates_to_graph_budget()`

Frozen M1 policy: the Answer is pinned; each admitted candidate contributes its
**complete** URI-valued one-hop IN/OUT neighbourhood or is rejected outright —
never truncated; at most 50 candidates and 1,200 nodes; at least 10 retained
candidates for success.

```
offered 24 mapped candidates -> GRAPH_FEASIBLE: 24 retained
```

Context nodes (the neighbours) enter the graph so candidates have structure.
They are **never offered to the ranker** and can never become distractors.

---

## 8. The frozen LRoleSim calculation

`src/lrolesim/adapter.py` driving `src/MCQ_lrolesim_ClaudeWeb_v2.py`, called by
`graph_lrolesim_run.rank_graph()`.

```
ranker      lrolesim_m1_fixed_k3
measure     lrolesim_ed
beta        0.2
iterations  3   (FIXED — not a convergence test)
run fingerprint  b3…  (graph + policy + source digests)
```

Journal 2 **applies** LRoleSim as a structural plausibility ranker. Its formula
is Journal 1's and is not re-derived here; nothing in Phase B recomputes a
similarity, and LRoleSim produces no rationale.

---

## 9. The complete LRoleSim ranking — stage [I]

`complete_lrolesim_ranking.csv`, 24 candidates, contiguous ranks from 1. The
top eight:

| rk | candidate | score | tie group |
|---:|---|---:|---:|
| 1 | Isamu Akasaki | 0.384615384615 | 1 |
| 2 | Shuji Nakamura | 0.374668759812 | 2 |
| 3 | Ryōji Noyori | 0.350557330538 | 3 |
| 4 | Toshihide Maskawa | 0.323284963314 | 4 |
| 5 | Shinya Yamanaka | 0.301036164359 | 5 |
| 6 | Osamu Shimomura | 0.297775479423 | 6 |
| 7 | Leo Esaki | 0.266061050061 | 7 |
| 8 | Shin'ichirō Tomonaga | 0.264576677938 | 8 |

This complete pool — not a top-k slice — is also the denominator of the
anonymity count in step 25.

---

## 10. Why the provisional top-ranked candidate is NOT evidence-feasible

`src/pipeline/phase_b2_any_answer_run.py :: summarise_candidate_evidence()`
projects the frozen per-(fact, candidate) matrix:

| rk | candidate | best available level | L1 | L0 | NOT_COVERED |
|---:|---|---|---:|---:|---:|
| **1** | **Isamu Akasaki** | **L0** | **0** | 1 | 3 |
| 2 | Shuji Nakamura | L1 | 2 | 1 | 1 |
| 3 | Ryōji Noyori | L1 | 2 | 2 | 0 |
| 4 | Toshihide Maskawa | L1 | 1 | 1 | 2 |

Akasaki reaches L1 on **nothing**. Under the `main-l1` policy a combination is
feasible only if EVERY distractor is covered at ≥ L1, so **every triple
containing rank 1 is infeasible** — and the highest-scoring feasible triple is
therefore (2, 3, 4). That single fact explains the whole result.

Why is he uncoverable? Because he is the person the Answer's own facts point
at: Amano's `doctoralAdvisor` **is** Akasaki (so that fact is L0 against him —
he has no advisor recorded), and Akasaki's `almaMater`, `workplaces` and
`after` values coincide with Amano's, making those three NOT_COVERED. He is the
most structurally similar candidate **and** the least discriminable one. That
tension is exactly what the objective exists to resolve.

---

## 11. All raw Answer facts

`src/mcq_inputs.py :: answer_facts_from_local_kg()`, enumerating with
`selection/observed_facts.py :: observed_edge_set(node, kg, use_in=True)` and
normalising with the frozen `normalize_uri()`.

Amano's complete observed one-hop inventory is small:

| # | key | counterpart |
|---:|---|---|
| f0 | (`dbp:after`, **IN**) | `dbr:Peter_Higgs` |
| f1 | (`dbp:almaMater`, OUT) | `dbr:Nagoya_University` |
| f2 | (`dbp:doctoralAdvisor`, OUT) | `dbr:Isamu_Akasaki` |
| f3 | (`dbp:workplaces`, OUT) | `dbr:Nagoya_University` |

Direction is part of the identity and is never merged: `(Answer, p, x)` and
`(x, p, Answer)` are different relations with different verbalizations.
`f1` and `f3` share a counterpart and are still two facts, because their keys
differ.

*(`--print-facts-only` prints exactly this inventory, grouped by
`(predicate, direction)`, with no ranking, no LRoleSim, no evidence and no
selection — `phase_b2_any_answer_run_v3.raw_fact_groups()`.)*

---

## 12. Quality filtering

`src/rationale_v3/quality.py :: assess_fact_quality()` — three hard filters
(`check_predicate`, `check_object`, `detect_answer_leakage`) and four soft
signals (tier, template, label length, token count).

All four of Amano's facts are **eligible**. Their tiers and templates:

| fact | tier | template |
|---|---:|---|
| `almaMater` OUT | 1 | `OUT_ALMA_MATER_V1` |
| `doctoralAdvisor` OUT | 1 | `OUT_DOCTORAL_ADVISOR_V1` |
| `workplaces` OUT | 1 | `OUT_WORKPLACES_V1` |
| `after` IN | 3 (default) | none |

Verbalizability is deliberately NOT part of hard eligibility: an unverbalizable
fact stays available for diagnostics and is only barred from the main corpus.

---

## 13. Candidate observations under each (predicate, direction)

`src/mcq_inputs.py :: candidate_objects_from_local_kg()` builds `O_d(κ)` once
per candidate and reuses it across every Answer fact. A candidate that is not a
node of the pinned KG raises an input error rather than returning `{}` — because
"absent from the graph" and "present but recording nothing under this key" are
different observations and only the second one is L0.

---

## 14. The semantic-index source-object set — stage [G]

`phase_b2_answer_run.enlarged_source_object_uris()` collects every counterpart
the run will reason about (the Answer's objects plus every candidate's objects
under the same keys); `source_object_list_sha256()` digests the SET, so the
digest cannot depend on collection order.

`phase_b2_any_answer_run.semantic_index_path()` then writes the index to
`<answer-slug>__<source-set-digest>.json`. **Both** components are load-bearing:
the slug keeps two Answers apart, and the digest makes a wrong reuse impossible
even between two runs of the SAME Answer whose candidate pools differ.

---

## 15. Evidence classification for every fact/candidate pair

`src/rationale_v3/evidence.py :: classify_fact_against_candidate()`. The order
IS the specification:

```
1. no object observed for the key            -> L0   (absence only)
2. any observed object SUPPORTS the claim    -> NOT_COVERED  (before any rule)
3. an ACTIVE L2 rule proves exclusion        -> L2 + EvidenceProof
4. otherwise                                 -> L1 positive observed contrast
```

The complete matrix for Amano's four facts against the first four candidates:

| rk | candidate | f0 `after`IN | f1 `almaMater` | f2 `doctoralAdvisor` | f3 `workplaces` |
|---:|---|---|---|---|---|
| 1 | Isamu Akasaki | NOT_COVERED | NOT_COVERED | L0 | NOT_COVERED |
| 2 | Shuji Nakamura | NOT_COVERED | **L1** | L0 | **L1** |
| 3 | Ryōji Noyori | L0 | **L1** | **L1** | L0 |
| 4 | Toshihide Maskawa | L0 | NOT_COVERED | **L1** | NOT_COVERED |

L1 here means "a different object is observed in this snapshot", never "the
candidate could not hold that object". DBpedia is open-world and the exclusion
strength lives on the separate `exclusion_basis` axis.

---

## 16. Coverage masks

`src/mcq_core.py :: coverage_mask(fact, positions, threshold)` sets bit *i* when
distractor *i* reaches the policy threshold. For the selected triple
(ranks 2, 3, 4) at threshold L1:

```
f0  after           levels [NOT_COVERED, L0, L0]      -> 000 = 0
f1  almaMater       levels [L1, L1, NOT_COVERED]      -> 011 = 3
f2  doctoralAdvisor levels [L0, L1, L1]               -> 110 = 6
f3  workplaces      levels [L1, L0, NOT_COVERED]      -> 001 = 1
```

Full coverage is `111` = 7.

---

## 17. FULL_EXACT enumeration

`mcq_core.build_candidate_pool()` chooses the scope. C(24, 3) = 2,024 is below
`MAX_EXACT_COMBINATIONS`, so the pool is the COMPLETE ranked pool and the scope
is `FULL_EXACT`: `global_optimality_claim = True`, meaning exact **over this
class's complete ranked pool** — never a claim about DBpedia.

`mcq_core.feasible_combinations()` enumerates all 2,024 with no pruning, no
beam, no sampling and no early exit. **969 survive.**

---

## 18. The minimum-cover DP

`mcq_core.minimum_cover_size_table()` — a bitmask DP over the DISTINCT non-zero
masks, memoised on the mask SET because different triples often induce the same
one. For the selected triple:

```
single facts:  3, 6, 1        -> none equals 7
pairs:         3|6 = 7  ✓      6|1 = 7  ✓      3|1 = 3  ✗
```

so **|R\*| = 2**, and exactly **two** minimum-cardinality covers exist —
`{f1, f2}` and `{f2, f3}` — which is what
`minimum_rationale_count_enumerated: 2` records.

`strongest_level_holding_the_minimum()` then checks whether a size-2 cover
still exists at L2 (it does not, since there are no L2 rules at all) and
reports L1 as `minimum_rationale_level`.

---

## 19. The six-key candidate-combination objective

`mcq_core.combination_objective_key()`. Smallest tuple wins:

| key | meaning | Amano's winning triple |
|---:|---|---|
| 1 | `-lrolesim_score_sum` | −1.048511053664346 |
| 2 | `-lrolesim_score_min` | −0.323284963314407 |
| 3 | `minimum_rationale_size` | 2 |
| 4 | `rationale.ranking_key` | see step 22 |
| 5 | `candidate_rank_sum` | 9 |
| 6 | `candidate_uris` | the canonical tuple |

Key 5 is a **deterministic tie-break aligned with the LRoleSim ranking** and
nothing more; it must never be promoted above keys 1–4 and must never be
described as a plausibility or quality metric.

Keys 1–3 are cheap and are computed for every one of the 969 survivors; key 4
is materialised only for those still tied on 1–3. That is exact, not a
shortcut: the objective is lexicographic, so a triple already beaten on keys
1–3 can never be rescued by 4–6.

---

## 20. Why the final ranks are 2, 3, 4

* Ranks (1, 2, 3) would score `0.3846 + 0.3747 + 0.3506 = 1.1099` on key 1 —
  **higher than the winner** — but the triple is **not feasible**: rank 1
  reaches L1 on no fact, so no set of ≤ 3 facts covers it and
  `feasible_combinations()` drops every triple containing it.
* Among the 969 feasible triples the largest score sum is
  `0.3747 + 0.3506 + 0.3233 = 1.048511053664346` — ranks (2, 3, 4).
* `combinations_tied_after_objective_key_4 = 1`: nothing was still tied when
  key 5 was reached, so the rank sum decided nothing here.

This is the concrete form of the general statement at the top: the search
ranges over triples, and plausibility is maximised **subject to** the evidence
being constructible.

---

## 21. All minimum-cardinality rationales for the selected triple

`mcq_core.rank_minimum_rationales()` enumerates every combination of `size`
usable facts and keeps the ones that cover everybody. For (2, 3, 4):

| # | rationale | union of masks |
|---:|---|---|
| A | `almaMater -> Nagoya_University` + `doctoralAdvisor -> Isamu_Akasaki` | 3 \| 6 = 7 |
| B | `doctoralAdvisor -> Isamu_Akasaki` + `workplaces -> Nagoya_University` | 6 \| 1 = 7 |

---

## 22. The rationale ranking key

`mcq_core.Rationale.ranking_key` — fourteen fields, evidence exhausted before
any quality field. The winner's recorded key:

```
[-2, 0, -4, 0, -2, 0, 0, 2, 0, 30, 4, 0, 1, <canonical fact tuple>]
```

| # | field | value | reading |
|---:|---|---:|---|
| 1 | `-strength(rationale_min_level)` | −2 | weakest distractor still reaches L1 |
| 2 | `-l2_incidences` | 0 | no L2 exists in this pilot |
| 3 | `-l1_incidences` | −4 | **four** (fact, distractor) pairs at L1 |
| 4 | `+l0_incidences` | 0 | none counted (below the L1 threshold) |
| 5 | `-scoped_empirical_incidences` | −2 | two annotated pairs |
| 6 | `+granularity_risk_incidences` | 0 | no risky apparent contrast |
| 7 | `+soft_leak_fact_count` | 0 | no soft Answer-label echo |
| 8 | `+pedagogical_tier_sum` | 2 | tier 1 + tier 1 |
| 9 | `+unverbalizable_fact_count` | 0 | both facts have templates |
| 10 | `+label_length_sum` | 30 | "Nagoya University" 17 + "Isamu Akasaki" 13 |
| 11 | `+token_count_sum` | 4 | 2 + 2 |
| 12 | `+redundant_predicate_direction_pairs` | 0 | the two κ differ |
| 13 | `+direct_identifier_flag` | 1 | see step 25 |
| 14 | canonical fact tuple | — | the deterministic last resort |

---

## 23. Why rationale A won

Both rationales tie on fields 1 and 2. Field 3 decides:

```
A = {almaMater, doctoralAdvisor}
    almaMater       L1 at positions 0,1   -> 2 incidences
    doctoralAdvisor L1 at positions 1,2   -> 2 incidences      total 4

B = {doctoralAdvisor, workplaces}
    doctoralAdvisor L1 at positions 1,2   -> 2 incidences
    workplaces      L1 at position 0      -> 1 incidence       total 3
```

`-l1_incidences` is −4 for A and −3 for B, so **A wins on field 3** and fields
4–14 are never consulted. In plain words: A gives the learner two distractors
that are wrong for *two* independently observed reasons, B gives that to only
one.

---

## 24. The final evidence level

`Selection.mcq_evidence_level` = `MCQ-` + `rationale.rationale_min_level`, i.e.
the MINIMUM over the three distractors of the best level any selected fact
supplies:

```
distractor 1  Shuji Nakamura      best under R*  L1
distractor 2  Ryōji Noyori        best under R*  L1
distractor 3  Toshihide Maskawa   best under R*  L1
                                  -> min = L1 -> MCQ-L1
```

`evidence_policy = main-l1` and `search_scope = FULL_EXACT`, so the item is
student-showable and the exactness claim is over the complete ranked pool of
`Category:Japanese_Nobel_laureates`.

---

## 25. Anonymity and `direct_identifier_flag`

`mcq_core.local_pool_anonymity()`. `S_local(R)` is the set of entities in
`{Answer} ∪ complete ranked pool` that **support every** proposition of R — an
entity supports a proposition exactly when the fact does not cover it, i.e. its
level is `NOT_COVERED`. The Answer supports its own facts by construction, so
the count starts at 1 and the supporter set is intersected fact by fact.

```
supporters of almaMater -> Nagoya_University  : {Akasaki, Nakamura?, …}
  intersected with
supporters of doctoralAdvisor -> Isamu_Akasaki : {…}
  = {}   ->  count = 1 + 0 = 1   of  1 + 24 = 25
  ratio = 0.04 ,  direct_identifier_flag = True   (count == 1)
```

**This is a LOCAL statement.** A count of 1 means only that within this pool no
other entity carries the same rationale. It says nothing about class members
absent from the pool and nothing about DBpedia as a whole — which is why the
field is named `local_candidate_pool_anonymity_count` and why
`LOCAL_ANONYMITY_NOTE` travels with every record.

`direct_identifier_flag` is field 13 of the rationale key — a diagnostic and
ranking signal, never a hard filter. Whether it should ever become a filter
needs human-evaluation evidence this pilot does not have.

---

## Appendix — what Prompt 8H-B2-E adds, on this Answer

Running the same Answer under the v3 defaults (predicate policy v2, semantic
policy v2, class-leakage v2, rationale objective v2) changes **nothing** here:
same class, same triple, same |R\*| = 2, same rationale, same MCQ-L1. The new
report block records why:

```
[L2] PROMPT 8H-B2-E ADDITIONS
    rationale objective        : rationale_objective/2.0.0-option-reference-conflict
    option_reference_conflict  : 0
    granularity risk states    : ['NONE']
    candidate screen           : answer type PERSON, 24 of 24 candidates accepted {}
```

* **no option-reference conflict** — neither `Nagoya_University` nor
  `Isamu_Akasaki` is one of the three printed options;
* **no granularity risk** — neither fact uses a predicate key that a relation
  domain governs, so no coverage question arises;
* **the candidate screen accepts all 24** under the default OBSERVE_ONLY
  policy — Amano is typed PERSON from his `almaMater`, `doctoralAdvisor` and
  `workplaces` slots, and no verdict removes anything.

Under `--candidate-type-policy person-strict` the same Answer keeps **22 of
24**, and the two removals are worth reading carefully, because one is right
and one is the cost:

```
REJECT dbr:Japan_Confederation_of_A-_and_H-Bomb_Sufferers_Organizations
       [CANDIDATE_TYPE_NOT_PERSON]  type=NOT_PERSON
REJECT dbr:Kenzaburō_Ōe
       [CANDIDATE_TYPE_UNKNOWN_UNDER_PERSON_STRICT_POLICY]  type=UNKNOWN
```

The first is a genuine non-Person that the class `Japanese Nobel laureates`
legitimately contains — an organisation, offered as a distractor for a person.
The second is a **real person** whose pinned article happens to fill no
URI-valued biography slot at all, so the observed-slot layer cannot see that he
is one. The policy refuses him and says UNKNOWN rather than NOT_PERSON, which
is the whole point of keeping three states: the run reports "the snapshot is
silent", not "the snapshot says he is not a person". Neither removal changes
Amano's selected triple, but the second is the measured price of the strict
policy and is why it is opt-in.

An Answer that changes nothing under a repair is as much evidence about the
repair as one that changes.
