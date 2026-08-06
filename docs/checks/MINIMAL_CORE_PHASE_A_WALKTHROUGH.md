# Minimal research core, Phase A — a walkthrough for the author

**Date** 2026-08-06 · **Branch** `journal2-minimal-core-selection-phase-a-20260806`
**Code** `src/mcq_core.py` · **Tests** `tests/test_mcq_core.py`
**Authoritative terminology** `docs/context/EVIDENCE_TAXONOMY_V1.md`

This document explains what `src/mcq_core.py` does and why, in enough detail
that you can defend it in a viva without opening Prompt 8F-R1. It is written
for you, the author of the method — not for a software engineer reviewing an
API. Where a number appears, it is a number the test suite actually checks.

---

## 1. What Phase A is, and where its boundary sits

The method has two halves that are easy to confuse, so this file separates them
once and keeps them separate.

**Classification** asks: *given this Answer fact and this candidate, what does
the pinned snapshot show?* That is where object equality, redirects, semantic
containment, empirical single-valued rules, URL and media detection, lexical
leakage detection and the verbalization registry live.

**Selection** asks: *given all of that already decided, which three candidates
and which smallest set of facts should the item use?* That is the mathematics —
an exhaustive combination search wrapped around an exact minimum-cardinality
set cover, ordered by a six-key lexicographic objective.

**Phase A implements only the second half.** It never sees a triple. It receives
records in which every evidence level, every eligibility decision and every
quality attribute has already been computed by the frozen Prompt-8F-R1
pipeline, and treats them as given.

### The input, precisely

| What arrives | Where it lives | What Phase A does with it |
|---|---|---|
| one Answer URI and label | `AnswerCase` | provenance |
| the **complete** ranked candidate pool, each with its frozen LRoleSim rank and score | `Candidate` | objective keys 1, 2, 5, 6 |
| every Answer fact's canonical identity `(predicate_uri, direction, counterpart_uri)` | `FactQuality` | fact identity; never split, never merged |
| whether each fact is eligible | `FactQuality.eligible` | a hard filter, applied before anything else |
| per-fact quality: `soft_leak`, `verbalizable`, `pedagogical_tier`, `label_length`, `token_count`, `template_id` | `FactQuality` | rationale-ranking fields 7–11 |
| per-(fact, candidate) evidence level | `AnswerFact.levels` | coverage masks, and ranking fields 1–4 |
| per-(fact, candidate) `exclusion_basis` and `granularity_risk` | `AnswerFact` | ranking fields 5–6, and provenance |

### The output

One `Selection` per Answer: the evidence policy that was used, the three chosen
candidates in position order, the chosen rationale with each fact's coverage
mask, the exact minimum rationale size, the objective values, and the local
candidate-pool anonymity diagnostics. `canonical_record()` renders it as a
deterministic dictionary with the scientific caveats attached.

### What Phase A deliberately does not do

No evidence classification from raw triples. No exact/equivalent object
testing. No parent–child semantic testing. No semantic-index traversal. No
empirical single-valued rules. No L2 proof checking. No URL or media predicate
detection. No lexical leakage detection. No template lookup. No natural-language
verbalization. No Bipartite Graph. No 100-Answer runner. Those are Phase B.

---

## 2. The four evidence levels, in one page

The authority is `docs/context/EVIDENCE_TAXONOMY_V1.md`. The kernel only needs
their **order**, which is `NOT_COVERED < L0 < L1 < L2`.

**`NOT_COVERED`** — the candidate *supports* the Answer's proposition. It has
the Answer's own object, or a trusted equivalent of it, or something lying
under it. The fact therefore tells a student nothing that separates the two
entities, so it covers nobody. In the code this is strength 0, and because
every policy threshold is at least 1, **a `NOT_COVERED` incidence can never set
a coverage bit at any threshold.** That is not an implementation detail; it is
the definition of the level made mechanical.

**`L0_ABSENCE_ONLY_OBSERVED`** — the snapshot records no object at all for the
candidate under the same predicate and the same direction. This is *snapshot
absence*. It is not negation, not real-world exclusion, and not something a
student may be shown as a reason. It exists so that you can report yield and
analyse failures.

**`L1_POSITIVE_ALTERNATIVE_OBSERVED`** — the candidate has at least one
**observed alternative value** under the same predicate and the same direction,
and none of its observed values supports the Answer's proposition. This is the
weakest level you may put in front of a student, and it must always be phrased
as an observation: *"the snapshot records Tokyo Institute of Technology as
Hideki Shirakawa's `almaMater`, and does not record University of Tokyo."*

**`L2_VERIFIED_EXCLUSION`** — a machine-checkable proof exists. The kernel
accepts L2 as an input level and orders it correctly, and there is a unit test
that proves it does. But **Phase A implements no L2 rule and no proof
generator**, and the R1 pilot contains zero L2 incidences. Zero is the correct
offline outcome: DBpedia infobox properties carry no trustworthy functionality,
cardinality, disjointness or negative-assertion declarations.

`SCOPED_EMPIRICAL` is an **annotation** on an already-established L1, not a
fourth level. It sits at field 5 of the rationale key — after the entire
evidence profile — so it can order two equally strong rationales and can never
create, upgrade or rescue a level.

### The open-world limitation, stated once and carried everywhere

```
(d, p, o) ∉ K   does NOT imply   ¬p(d, o)
```

The snapshot records what has been documented, not what is true. Absence is a
statement about coverage. An observed alternative value is a statement about
what the snapshot records — never a proof of incompatibility. Many DBpedia
infobox predicates are multi-valued; `almaMater` is the worked example below,
where the rank-1 candidate carries *two* values. The constant
`OPEN_WORLD_NOTE` travels on every emitted record for exactly this reason.

---

## 3. Coverage masks — how a fact becomes three bits

Fix a combination of three candidates. Write it as `positions = (d₀, d₁, d₂)`.

**Bit *i* corresponds exactly to candidate `positions[i]`** — the *i*-th
distractor in this combination's own position order. Bit 0 is the first
distractor, bit 1 the second, bit 2 the third.

For a fact `f` and a threshold `τ`:

```
bit i = 1   iff   level(f, positions[i]) ≥ τ
```

Three consequences worth stating aloud:

* A mask is meaningless without the combination it was built against. Reorder
  the combination and the bits move.
* `NOT_COVERED` contributes no bit, because its strength is 0 and every
  threshold is at least 1.
* **IN and OUT never merge.** `dbp:influences` IN and `dbp:influences` OUT are
  different relations, with different extensions and different verbalizations.
  They are two different facts here, with two independent masks. Six of the
  nine rationale facts in the R1 pilot are IN, and Eisaku Satō's rationale
  would be destroyed if the two directions were folded together.

The three thresholds come from the three policies:

| policy | threshold | meaning |
|---|---|---|
| `strict-l2` | L2 | every distractor needs a verified exclusion |
| `main-l1` | L1 | every distractor needs an observed alternative value or better — the main-corpus policy |
| `diagnostic-l0` | L0 | snapshot absence counts; diagnostic only, never shown as a reason |

They are tried in that order, and the **first** policy with at least one
feasible full-coverage combination is selected. A weaker policy is never mixed
in to rescue a stronger one.

---

## 4. The exact minimum-cardinality set cover

Once a combination is fixed, a rationale is a set of Answer facts, and the
question is: *what is the smallest set whose masks OR to `0b111`?*

This is minimum-cardinality set cover over three elements. With only `2³ = 8`
subsets it is solved exactly by a small dynamic program.

### The table

`minimum_cover_size_table(masks)` returns eight numbers. Entry `s` is the
minimum number of facts whose masks OR to **exactly** `s`, starting from
nothing. Unreachable entries hold `k + 1 = 4`.

### A small worked example

Take three facts with masks `0b110`, `0b001` and `0b010`.

Start: only the empty state costs nothing.

```
state    000  001  010  011  100  101  110  111
cost       0    4    4    4    4    4    4    4
```

Offer `0b001`. From state `000` at cost 0 we reach `001` at cost 1.

```
state    000  001  010  011  100  101  110  111
cost       0    1    4    4    4    4    4    4
```

Offer `0b010`. From `000` we reach `010` at cost 1; from `001` at cost 1 we
reach `011` at cost 2.

```
state    000  001  010  011  100  101  110  111
cost       0    1    1    2    4    4    4    4
```

Offer `0b110`. From `000` we reach `110` at cost 1; from `001` we reach `111`
at cost 2; from `010` we reach `110` at cost 2 (no improvement); from `011` we
reach `111` at cost 3 (no improvement).

```
state    000  001  010  011  100  101  110  111
cost       0    1    1    2    4    1    1    2
```

Read off `cost[111] = 2`: the smallest rationale here has **two** facts,
`0b110` together with `0b001`. Note that the greedy rule "take the fact
covering the most uncovered distractors" would also work here, but greedy is
not guaranteed optimal on set cover in general, which is why it is not used.

### Why this is exact, and why it is safe to simplify the input

**Exactness.** Each fact is offered once, in an outer loop, and every
relaxation reads a snapshot of the table taken *before* that fact was offered.
So no fact can be used twice inside its own pass — which is precisely the 0/1
semantics of "choose this set or don't". By induction over the outer loop,
after `j` facts the table holds the exact optimum over subsets of those `j`
facts. Nothing is approximated and nothing is pruned.

**Duplicate masks collapse.** The DP only ever asks *which distractors does
this fact reach*. Two facts with the same mask answer identically, and a
minimum-cardinality cover can never contain both — deleting one leaves the
union unchanged and the count smaller, contradicting minimality. So the input
may be reduced to its distinct non-zero masks. A zero mask covers nobody and
can never help.

**But the collapse is a cardinality argument only.** Two facts with the same
mask distinguish the same distractors and yet may be very different items: one
verbalizable at tier 1, the other with no template at all. That is why the
minimum size is only step one.

**Unreachable states hold `k + 1`.** That is strictly larger than any
achievable cover size, because whenever a cover exists, one fact per distractor
already gives a cover of size at most `k`. So a single comparison against
ρ = 3 rejects "too large" and "impossible together", with no special case.

---

## 5. Choosing among the smallest rationales

Knowing that |R\*| = 2 does not tell you *which* two facts. So after the DP
returns the minimum size, the kernel **enumerates every rationale of exactly
that size that reaches full coverage** and ranks them. This is what makes the
quality ranking exact rather than "whatever the DP happened to reconstruct".

There is one exact pre-filter. Raising the threshold can only shrink masks, so
the minimum cover size is monotone as the level strengthens. The kernel finds
the strongest level `t` at which a cover of the *same* minimum size still
exists, and enumerates only covers at `t`. This is not a heuristic cut: a
same-size cover that exists at the policy threshold but not at `t` has some
distractor whose best level is below `t`, so its `rationale_min_level` is
weaker and it already loses on field 1 of the key below.

### The fourteen-field rationale key — objective key 4

Smallest tuple wins. A leading minus means "maximise". Read left to right; the
**entire evidence profile is exhausted before any quality field is consulted**,
so no amount of pedagogical polish can buy a weaker evidence level.

| # | Field | Direction | Why here |
|---:|---|---|---|
| 1 | strongest minimum evidence level | maximise | prefer the rationale whose *weakest* distractor is best supported |
| 2 | L2 incidence count | maximise | more verified exclusions |
| 3 | L1 incidence count | maximise | more observed alternative values |
| 4 | L0 incidence count | minimise | fewer absence-only incidences; reached only under `diagnostic-l0` |
| 5 | scoped-empirical annotation count | maximise | annotation, ordering only — after the whole level profile, so it can never create or rescue a level |
| 6 | granularity-risk incidence count | minimise | fewer apparent contrasts that may be granularity mismatches |
| 7 | soft-leak count | minimise | fewer soft echoes of the Answer string |
| 8 | pedagogical-tier sum | minimise | lower tier number is better |
| 9 | unverbalizable-fact count | minimise | fewer facts with no template |
| 10 | label-length sum | minimise | shorter surface form |
| 11 | token-count sum | minimise | fewer tokens |
| 12 | redundant predicate-direction pairs | minimise | fewer repeats of one `κ = (p, dir)` |
| 13 | direct-identifier flag | minimise | a diagnostic tie-break, **never a filter** |
| 14 | canonical fact tuple | ascending | deterministic last resort |

These are R1's fields, preserved unchanged. The eight-Answer pilot reaches only
the first few of them — seven of the eight Answers never get past objective key
3 at all. That is **not** a reason to delete the rest: a pilot of eight is far
too small to prove a field is dead. Whether any field can be dropped is a
question for the 100-Answer batch, measured, not guessed.

### Local candidate-pool anonymity — field 13, and why its name is long

For a rationale `R`:

```
S_local(R) = { e ∈ {Answer} ∪ complete ranked candidate pool : e supports every proposition in R }
local_candidate_pool_anonymity_count = |S_local(R)|
local_candidate_pool_anonymity_ratio = |S_local(R)| / (1 + |pool|)
direct_identifier_flag               = ( |S_local(R)| == 1 )
```

An entity *supports* a proposition exactly when the fact does not cover it —
i.e. its level is `NOT_COVERED`.

**The scope is strictly local.** The pool is the Answer plus the complete
ranked candidate pool of the selected class. A count of 1 means only that
*within this pool* no other entity carries the same rationale. It says nothing
about class members absent from the pool and nothing about DBpedia as a whole.
Never write "unique in DBpedia" or "globally unique" — hence the long name, and
hence the note that travels on every record.

The flag is a **diagnostic and ranking** field. It removes no rationale from
consideration. Whether it should ever become a filter needs human-evaluation
evidence the pilot does not provide.

---

## 6. The combination objective

For each Answer the kernel enumerates **every** `C(n, 3)` combination —
`FULL_EXACT`. No bounded pool, no evidence-rescue pool, no beam, no greedy
pass, no sampling, and no accepting the first feasible combination it finds.
That exhaustiveness is the only reason the search can look *past* the
provisional LRoleSim top three when the top three cannot be justified.

Smallest tuple wins, evaluated left to right:

| # | Key | Direction |
|---:|---|---|
| 1 | `lrolesim_score_sum` | maximise total structural plausibility |
| 2 | `lrolesim_score_min` | maximise the weakest distractor |
| 3 | `minimum_rationale_size` | minimise the exact \|R\*\| |
| 4 | the fourteen-field rationale key | maximise evidence profile, then quality |
| 5 | `candidate_rank_sum` | minimise |
| 6 | `candidate_uris` | ascending, final unresolved tie-break |

**LRoleSim's role.** Keys 1 and 2 are the only place LRoleSim enters, and they
consume *frozen* ranks and scores. Journal 2 **applies** LRoleSim as a
structural plausibility ranker; it does not extend it, does not touch its
formula, and LRoleSim generates no rationale. Rationale construction is the set
cover, a completely separate mechanism.

**Key 3's direction is a real choice.** Placing plausibility above compactness
means a more plausible triple is preferred even when it needs a larger
rationale. That is the plausibility/compactness trade-off the paper reports.

**Key 5 is a tie-break and nothing else.** Describe it in the paper as *"a
deterministic tie-break aligned with the LRoleSim ranking"*. Never as a
plausibility metric, never as a pedagogical-quality objective, and never as a
component of the plausibility objective. The reason is simple: rank is an
*ordinal* transform of the score that keys 1 and 2 already maximise with full
cardinal precision, so promoting it would mean replacing a measurement by a
coarser proxy for the same measurement. It earns its place at key 5 because
when LRoleSim scores tie *exactly*, rank is the ranker's own residual ordering,
which keeps the resolution inside the LRoleSim framework instead of falling
through to alphabetical URI order. See `docs/audits/RANK_SUM_EFFECT_AUDIT.md`.

**Two-stage evaluation is exact, not a shortcut.** Keys 1–3 are cheap and are
computed for all `C(n, 3)` combinations; key 4 is materialised only for the
combinations still tied on keys 1–3. Because the objective is lexicographic, a
combination that has already lost on keys 1–3 can never be rescued by keys 4–6,
so materialising its rationale key would change nothing.

---

## 7. The complete Eisaku Satō calculation

This is the one pilot Answer where every interesting thing happens at once. All
numbers below are asserted by `tests/test_mcq_core.py`.

### Setup

24 ranked candidates, so `C(24, 3) = 2024` combinations, all enumerated. Satō
has 60 observed Answer facts, of which **55 are eligible** — five were removed
upstream as hard filters (two `dbp:caption` IN and two `dbp:governmentHead` IN
would have leaked the string "Satō"; one `dbp:url` OUT was a raw external Web
Archive URL). Phase A consumes those five as `eligible = False` and never
re-derives the reason.

### Why the provisional top three fails

| rank | candidate | L1-covering eligible facts |
|---:|---|---:|
| 1 | Ei-ichi Negishi | 1 |
| 2 | Yasunari Kawabata | **0** |
| 3 | Masatoshi Koshiba | **0** |

Ranks 2 and 3 are covered by **zero** eligible facts at L1. Their coverage
bitsets over the 55 eligible facts are empty, and no subset of facts — of any
cardinality, in any combination — can cover an empty bitset. So the combination
`{1, 2, 3}` is infeasible at `main-l1` **by construction**, not by bad luck or
by a search budget. The DP reports `k + 1 = 4 > ρ`.

Their only non-L0 evidence is a `NOT_COVERED`: both share
`dbp:almaMater → University of Tokyo` with Satō. That is the *opposite* of
distinguishing evidence — the fact confirms they resemble the Answer.
Everything else is L0, and under the open-world assumption absence may not be
shown to a student as a reason.

Seven of the 24 candidates (ranks 2, 3, 4, 21, 22, 23, 24) have zero L1
coverage; 17 have some. That gives **680** feasible combinations at `main-l1`,
against 0 at `strict-l2` and all 2024 at `diagnostic-l0`. `strict-l2` is
skipped, `main-l1` is feasible, so `diagnostic-l0` is never reached — which is
correct, because the provisional triple *is* feasible at `diagnostic-l0` with a
one-fact "rationale", and that rationale would be pure absence.

### Keys 1 and 2 pick the candidates

Only the 17 covered candidates may be used. The three largest LRoleSim scores
among them are rank 1, rank 5, and then an **exact three-way tie** at ranks 6,
7 and 8:

```
0.22190222222222222   rank 1, Ei-ichi Negishi
0.20836497625830960   rank 5, Hideki Shirakawa
0.20696461464461466   rank 6 = rank 7 = rank 8
--------------------
0.63723181312514650   maximum attainable score sum
```

Ranks 2, 3 and 4 carry higher scores but are unusable. That gap is precisely
the price the method pays to obtain grounded evidence, and it is worth
reporting as such.

### Key 3 gives |R\*| = 2

With `positions = (rank 1, rank 5, rank 6)`, bit 0 tracks Negishi, bit 1
Shirakawa, bit 2 Akasaki.

**`dbp:almaMater` OUT → University of Tokyo**

| bit | candidate | observed objects | level |
|---:|---|---|---|
| 0 | Ei-ichi Negishi | University of Pennsylvania, **University of Tokyo** | `NOT_COVERED` — he *also* attended it |
| 1 | Hideki Shirakawa | Tokyo Institute of Technology | **L1** |
| 2 | Isamu Akasaki | Kyoto University, Nagoya University | **L1** |

→ mask `0b110`

**`dbp:before` IN → Kiichi Aichi**

| bit | candidate | observed objects | level |
|---:|---|---|---|
| 0 | Ei-ichi Negishi | Dan Shechtman | **L1** |
| 1 | Hideki Shirakawa | ∅ | `L0` |
| 2 | Isamu Akasaki | ∅ | `L0` |

→ mask `0b001`

```
  0b110   almaMater OUT   covers Shirakawa, Akasaki
  0b001   before    IN    covers Negishi
  -----   OR
  0b111                   FULL COVERAGE
```

The two facts are **exactly complementary**, and note that one is OUT and the
other IN — merging the directions would destroy this rationale.

**Proof that |R\*| = 2 exactly.** Enumerate the `main-l1` mask of every one of
the 55 eligible facts over this triple. Exactly two are non-zero: `0b110` and
`0b001`. The remaining 53 have mask `0b000`. So the achievable mask set is
`{0b000, 0b001, 0b110}`, and `0b111` is not in it — a one-fact rationale would
need a fact of mask `0b111`, and none exists. Hence |R\*| ≥ 2. Section 5
exhibits a cover of size 2, so |R\*| = 2. ∎ This is exhaustive over the whole
eligible fact set, not a search cut-off.

### Keys 1–4 tie three ways; key 5 decides

The three combinations `{1,5,6}`, `{1,5,7}` and `{1,5,8}` are identical on key
1 (same score sum), key 2 (same score min), key 3 (both |R\*| = 2) **and** key
4 — because all three use the *same* two rationale facts, so their fourteen-field
keys are literally the same tuple:

```
(-2, 0, -3, 0, 0, 0, 0, 4, 1, 31, 5, 0, 1, …)
```

reading: minimum evidence level L1 (`-2`); 0 L2 incidences; 3 L1 coverage
incidences (`-3`); 0 L0; 0 scoped-empirical; 0 granularity risk; 0 soft leaks;
pedagogical-tier sum 4; 1 unverbalizable fact; label-length sum 31; token-count
sum 5; 0 redundant predicate-direction pairs; direct-identifier flag set.

Key 5 separates them:

| combination | ranks | rank sum | outcome |
|---|---|---:|---|
| Negishi, Shirakawa, **Akasaki** | 1, 5, 6 | **12** | **selected** |
| Negishi, Shirakawa, Noyori | 1, 5, 7 | 13 | rejected |
| Negishi, Shirakawa, Tomonaga | 1, 5, 8 | 14 | rejected |

Satō is the only one of the eight pilot Answers that reaches key 5 at all.

### What the result is, and its one blocker

`main-l1`, distractors at ranks 1, 5, 6, rationale of size 2, coverage mask 7,
MCQ level `MCQ-L1`, local candidate-pool anonymity count 1 (a direct
identifier, *within this pool*).

The item is **diagnostic-corpus eligible but not main-corpus eligible**, for
one reason only: `dbp:before` IN has no verbalization template
(`template_id = VERBALIZABLE_UNKNOWN`, tier 3), and |R\*| = 2 forces that fact
into the rationale. The blocker is a missing template — not the evidence level,
not the class selection, and not the search.

---

## 8. What remains for Phase B

| Deferred to Phase B | Note |
|---|---|
| evidence classification from raw triples | exact object equality, trusted redirect equivalence, candidate-object-under-claim entailment |
| semantic closure and the granularity-risk direction test | the R1 closure changed no evidence level in the pilot; the axis and its direction still matter |
| quality-rule derivation | URL/media/raw-layout predicate rejection, lexical leakage detection, the verbalizability registry |
| empirical single-valued (`SCOPED_EMPIRICAL`) rule derivation | 39 annotated incidences existed in the pilot; **0** reached a selected rationale |
| any L2 rule or proof generator | requires a written specification, a source, a proof checker and tests, approved first |
| natural-language verbalization | Phase A consumes *whether* a fact is verbalizable; producing the sentence is separate |
| `src/mcq_run.py` — input loading, provenance, JSONL output, CLI | the second and last production file |
| the 100-Answer batch | only after correctness and yield are measured |
| Bipartite Graph generation | out of scope; and the author's three original files must be read first |

`POOL_EXACT` remains deferred: all eight pilot Answers ran `FULL_EXACT` and the
largest class needed 18,424 combinations. Add it only when a real class exceeds
the exact budget, and report `global_optimality_claim = false` when it is used.

---

## 9. Which claims Phase A supports, and which it does not

### Supported now

* **The distractor search is exhaustive and the reported selections are exact
  for the pilot.** Every `C(n, 3)` combination is enumerated under `FULL_EXACT`,
  with no pruning, no beam and no sampling.
* **The minimum rationale cardinality is exact, not a greedy approximation.**
  The bitmask DP is verified against brute force on 160 deterministic random
  cases, and on every one of the `2^k` table entries, not only the full mask.
* **Among minimum-cardinality rationales, the choice is exact too**, because
  all of them are enumerated before ranking.
* **The eight R1 pilot selections are reproduced exactly** — policy, distractor
  URIs, distractor ranks, rationale fact set and |R\*| — by an implementation
  that imports nothing from R1 and reads only its already-classified records.
* **LRoleSim is applied, not extended.** Ranks and scores are consumed frozen.
* **Rationale selection is independent of LRoleSim.** It is a set cover over
  evidence, and the two mechanisms meet only inside the lexicographic ordering.
* **Every reported level is an observation about a pinned snapshot**, and the
  open-world caveat is attached to every emitted record.

### Not supported, and must not be claimed

* **Nothing about exclusion or falsity.** L1 says the snapshot records an
  observed alternative value. It does **not** say the candidate could not also
  hold the Answer's object, and L0 says even less. Only L2 could support an
  exclusion claim, and there are zero L2 incidences.
* **Nothing global about the rationale.** `local_candidate_pool_anonymity` is
  local to the Answer plus the ranked candidate pool. It is not uniqueness in
  DBpedia.
* **No claim that the selected class is globally optimal.** Use *requested*,
  *recommended*, *top-ranked* or *first-feasible*.
* **No novelty claim for the mathematics.** Set cover, bitmask dynamic
  programming and Hungarian matching are textbook. The contribution is the
  method that combines a structural plausibility ranker with an exact,
  evidence-grounded rationale selection — not the DP.
* **No claim that `candidate_rank_sum` measures plausibility or item quality.**
  It is a deterministic tie-break aligned with the LRoleSim ranking.
* **No pedagogical or difficulty claim of any kind.** Nothing here has been
  evaluated by a human. Whether a locally unique clue makes an item easy is an
  empirical question for the planned human evaluation.
* **No yield claim.** Eight Answers is a pilot. The 100-Answer batch has not
  been run.
* **No claim that Phase A verbalizes anything.** Eisaku Satō is blocked from
  the main corpus by a missing template, and Phase A neither supplies nor
  invents one.

---

## 10. How to re-run the checks

```bash
conda activate mcq-journal2
python -m pytest -q tests/test_mcq_core.py
python tools/count_loc.py src/mcq_core.py tests/test_mcq_core.py
```

The regression table is `docs/checks/MINIMAL_CORE_PHASE_A_REGRESSION.csv`, one
row per pilot Answer with expected and reproduced values side by side. It is
not merely published — `test_published_regression_csv_matches_the_kernel`
re-derives every cell from the kernel and from the frozen oracle and fails if
any of them drifts.
