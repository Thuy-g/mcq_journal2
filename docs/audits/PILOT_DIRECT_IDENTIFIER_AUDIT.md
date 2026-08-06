# Pilot direct-identifier audit

**Date** 2026-08-06 · **Branch** `journal2-spec-freeze-20260806`
**Data** `docs/audits/PILOT_DIRECT_IDENTIFIER_AUDIT.csv` (8 rows, one per selected pilot MCQ)
**Derived by** `scripts/spec_freeze_audit.py`, re-computed from frozen Prompt-8F-R1 records

**This audit is descriptive. It contains no judgement about whether any question
is educationally good or bad.** No question is rejected, ranked or scored here.

---

## 1. What is measured, and what it means

### Local candidate-pool anonymity

For a rationale set `R` over Answer `A`:

```
S_local(R) = { e ∈ {A} ∪ ranked candidate pool : e supports every proposition in R }
local_candidate_pool_anonymity_count  = |S_local(R)|
local_candidate_pool_anonymity_ratio  = |S_local(R)| / (1 + |candidate pool|)
direct_identifier_flag                = ( |S_local(R)| == 1 )
```

An entity **supports** a proposition exactly when the fact does not cover it —
i.e. its evidence level is `NOT_COVERED` (see
`docs/context/EVIDENCE_TAXONOMY_V1.md` §1).

**The scope is strictly local.** The pool is the Answer plus the *complete
ranked candidate pool of the Prompt-8C selected class*, as frozen by Prompt 8D.
A count of 1 means: *within this pool*, no other entity carries the same
rationale. It says nothing about class members absent from the pool, and nothing
about DBpedia as a whole. The metric is named
`local_candidate_pool_anonymity` everywhere for exactly this reason, and it must
never be reported as "unique in DBpedia" or "globally unique".

### Risk category

Strictly derived from the count, with no other input:

| Category | Condition |
|---|---|
| `UNIQUE_IN_LOCAL_POOL` | `local_candidate_pool_anonymity_count == 1` |
| `SHARED_IN_LOCAL_POOL` | `local_candidate_pool_anonymity_count ≥ 2` |

### The diagnostic reading

Direct identification **supports local Answer uniqueness**: if only the Answer
satisfies the rationale within the pool, the rationale genuinely picks the
Answer out and does not accidentally describe a distractor as well.

The same property **may make a question easier** if the clue is famous or overly
specific — a rationale that names a strongly Answer-associated entity can be
recognised without the reasoning the item intends to test.

Both readings follow from the same number. **This is a diagnostic metric, not an
automatic rejection criterion.** Nothing in the pipeline filters on it; it enters
the rationale ranking key only as the **thirteenth of fourteen** fields, i.e.
essentially as a late tie-break, and it never removes a candidate rationale from
consideration.

---

## 2. Results

| # | Answer | pool size | rationale (predicate, dir → object) | \|R*\| | anonymity count | ratio | direct-identifier | risk category |
|---:|---|---:|---|---:|---:|---:|:---:|---|
| 1 | Shinya Yamanaka | 25 | `dbp:almaMater` OUT → Kobe University | 1 | 1 | 0.0400 | **yes** | `UNIQUE_IN_LOCAL_POOL` |
| 2 | Shin'ichirō Tomonaga | 25 | `dbp:birthPlace` OUT → Tokyo | 1 | **2** | 0.0800 | no | `SHARED_IN_LOCAL_POOL` |
| 3 | Eisaku Satō | 25 | `dbp:almaMater` OUT → University of Tokyo **+** `dbp:before` IN → Kiichi Aichi | 2 | 1 | 0.0400 | **yes** | `UNIQUE_IN_LOCAL_POOL` |
| 4 | Carbon | 50 | `dbp:formula` IN → Diamond | 1 | 1 | 0.0200 | **yes** | `UNIQUE_IN_LOCAL_POOL` |
| 5 | Silicon | 12 | `dbp:knownFor` IN → Jöns Jacob Berzelius | 1 | 1 | 0.0833 | **yes** | `UNIQUE_IN_LOCAL_POOL` |
| 6 | Aristotle | 28 | `dbp:influences` IN → Ptolemy | 1 | 1 | 0.0357 | **yes** | `UNIQUE_IN_LOCAL_POOL` |
| 7 | Plato | 28 | `dbp:influenced` IN → Gorgias | 1 | **2** | 0.0714 | no | `SHARED_IN_LOCAL_POOL` |
| 8 | Adam Smith | 19 | `dbp:influences` IN → James Watt | 1 | 1 | 0.0526 | **yes** | `UNIQUE_IN_LOCAL_POOL` |

**6 of 8 `UNIQUE_IN_LOCAL_POOL`, 2 of 8 `SHARED_IN_LOCAL_POOL`.**

### Distractors and ranks

| # | Answer | selected distractors (LRoleSim rank) |
|---:|---|---|
| 1 | Shinya Yamanaka | Shuji Nakamura (1), Shin'ichirō Tomonaga (2), Toshihide Maskawa (3) |
| 2 | Shin'ichirō Tomonaga | Toshihide Maskawa (1), Isamu Akasaki (2), Osamu Shimomura (3) |
| 3 | Eisaku Satō | Ei-ichi Negishi (1), Hideki Shirakawa (**5**), Isamu Akasaki (**6**) |
| 4 | Carbon | Boron (1), Antimony (2), Sodium (3) |
| 5 | Silicon | Bilayer graphene (1), Black silicon (2), Silicon carbide (3) |
| 6 | Aristotle | Plato (1), Socrates (2), Epicurus (3) |
| 7 | Plato | Aristotle (1), Socrates (2), Epicurus (3) |
| 8 | Adam Smith | Henry George (1), Frédéric Bastiat (2), James Mill (3) |

Eisaku Satō is the only Answer whose selection departs from the provisional
LRoleSim top three; see `EISAKU_SATO_SELECTION_TRACE.md`.

### Predicate, direction and verbalizability

| # | Answer | predicate | direction | verbalizable | template | tier |
|---:|---|---|---|:---:|---|---:|
| 1 | Shinya Yamanaka | `dbp:almaMater` | OUT | yes | `OUT_ALMA_MATER_V1` | 1 |
| 2 | Shin'ichirō Tomonaga | `dbp:birthPlace` | OUT | yes | `OUT_BIRTH_PLACE_V1` | 1 |
| 3 | Eisaku Satō | `dbp:almaMater` | OUT | yes | `OUT_ALMA_MATER_V1` | 1 |
| 3 | Eisaku Satō | `dbp:before` | **IN** | **no** | `VERBALIZABLE_UNKNOWN` | 3 |
| 4 | Carbon | `dbp:formula` | IN | yes | `IN_FORMULA_V1` | 1 |
| 5 | Silicon | `dbp:knownFor` | IN | yes | `IN_KNOWN_FOR_V1` | 1 |
| 6 | Aristotle | `dbp:influences` | IN | yes | `IN_INFLUENCES_V1` | 1 |
| 7 | Plato | `dbp:influenced` | IN | yes | `IN_INFLUENCED_V1` | 1 |
| 8 | Adam Smith | `dbp:influences` | IN | yes | `IN_INFLUENCES_V1` | 1 |

**Six of the nine rationale facts use the IN direction.** IN and OUT are never
merged: `dbp:influences` IN and `dbp:influences` OUT are different keys with
different templates (rows 6 and 7 use different predicates in the same
direction, and both are IN). Eight of nine facts are verbalizable at tier 1;
the single exception, Satō's `dbp:before` IN, is the reason that item is
diagnostic-corpus rather than main-corpus eligible.

### Proper-name signal on the rationale object

The CSV column `object_proper_name_signal` carries a **deliberately weak,
purely orthographic** signal, computed with no POS tagger, no lexicon and no
embedding (all excluded by task constraint):

| Value | Rule | Rationale objects |
|---|---|---|
| `MULTI_TOKEN_PROPER_NAME` | ≥ 2 tokens, ≥ 2 capitalised | Kobe University; University of Tokyo; Kiichi Aichi; Jöns Jacob Berzelius; James Watt |
| `SINGLE_TOKEN_CAPITALIZED_AMBIGUOUS` | one token | Tokyo; Diamond; Ptolemy; Gorgias |

**Why the single-token class stays explicitly ambiguous.** DBpedia capitalises
*every* resource label by convention, so capitalisation alone carries no
information. Orthographically, `Diamond` (a material — a common noun) is
indistinguishable from `Ptolemy` and `Gorgias` (named individuals) and from
`Tokyo` (a place). Carbon's rationale object `Diamond` is the concrete case
where a naive "capitalised ⇒ proper name" rule would be **wrong**. Resolving
this properly would require entity-type data from the pinned KG, which this
audit does not load. The ambiguity is reported rather than guessed.

Under the stated rule, **5 of 9** rationale objects carry a strong proper-name
signal; the remaining 4 are unresolved.

### Per-fact versus per-set anonymity

`per_fact_anonymity_count` in the CSV gives the count each fact would produce on
its own. Only Eisaku Satō has a multi-fact rationale, and there the two numbers
differ informatively:

| fact | own count | reading |
|---|---:|---|
| `dbp:almaMater` OUT → University of Tokyo | 5 | the Answer plus 4 pool members |
| `dbp:before` IN → Kiichi Aichi | 1 | the Answer alone |
| **both together** | **1** | intersection of the two supporter sets |

`almaMater → University of Tokyo` alone identifies 5 of 25 pool entities — it is
a weak identifier, and indeed it is exactly the fact that *fails* to cover
Ei-ichi Negishi, who shares it. The set as a whole is a direct identifier.

---

## 3. Observations, stated without evaluative claims

1. **Direct identification is the common case in this pilot (6 of 8).** With
   pools of 12–50 entities and rationales of cardinality 1, this is expected:
   the `main-l1` policy demands a fact that distinguishes the Answer from all
   three distractors, and such facts tend to be specific.
2. **The two shared cases are both size-1 rationales that leave exactly one
   other pool entity satisfied**, and in both cases that entity is **not** one
   of the three selected distractors:

   | Answer | rationale | also satisfied by | selected distractors |
   |---|---|---|---|
   | Shin'ichirō Tomonaga | `birthPlace` OUT → Tokyo | Hideki Yukawa (rank 11) | Maskawa (1), Akasaki (2), Shimomura (3) |
   | Plato | `influenced` IN → Gorgias | Antisthenes (rank 8) | Aristotle (1), Socrates (2), Epicurus (3) |

   This is guaranteed by construction: the `main-l1` policy requires the
   rationale to cover all three selected distractors, so a supporting entity
   can only ever be a non-selected pool member. Both rationales are valid;
   sharing with a candidate that was not chosen is not a defect.
3. **Anonymity ratio is dominated by pool size, not by clue strength.** Carbon
   has the lowest ratio (0.0200) purely because its pool has 50 entities. Ratios
   are comparable within a class, not across classes.
4. **Famous-clue difficulty is not measured here.** Whether
   `knownFor IN → Jöns Jacob Berzelius` makes the Silicon item easy for a
   student who recognises Berzelius is an empirical question for the planned
   human evaluation. This audit records only that the clue is locally unique.
5. **The metric is not currently used to filter.** No pilot MCQ was accepted or
   rejected on the basis of `direct_identifier_flag`. If a future batch shows
   that direct identifiers correlate with poor human-rated item quality, the
   flag is already computed and recorded and could be promoted to a filter —
   that decision requires evidence this pilot does not provide.

---

## 4. Reproduction

```bash
python scripts/spec_freeze_audit.py \
    --direct-identifier-csv docs/audits/PILOT_DIRECT_IDENTIFIER_AUDIT.csv
python -m pytest -q tests/test_spec_freeze_audit.py
```

The script refuses to emit any audit unless its independent re-derivation
reproduces all eight R1 selections first.
