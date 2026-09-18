# B3 choice–evidence architecture — independent adversarial review

**Prompt** 8H-B3-ARCH-2 · **Date** 2026-09-18
**Branch** `journal2-b2g-final-benchmark-safety-v4-20260918`
**Object under review** `docs/plans/B3_CHOICE_EVIDENCE_FACT_SELECTION_ARCHITECTURE_2026-09-18.md`
(Prompt 8H-B3-ARCH-1, "ARCH-1" below) and its `.summary.json` companion.
**Status** REVIEW ONLY. No production code, no change to any frozen module, no
change to any v1/v2/v3/v4 output, no edit of ARCH-1, no git operation.
**Companion** `B3_HUMAN_DECISION_MEMO_2026-09-18.md` (one row per human
decision) and `B3_HUMAN_DECISION_MEMO_2026-09-18.json`.
**Terminology authority** `docs/context/EVIDENCE_TAXONOMY_V1.md`.

---

## 0. Verdict in one paragraph

**NOT_READY_FOR_SPEC_FREEZE.** The ARCH-1 skeleton is sound and should be
kept: one screened universe of observed facts, clue groups as the unit of
exposure, group atomicity, safety expressed as hard constraints, two nested
selections, an exact solver over a declared universe, an exhaustive oracle for
small instances, provenance on every edge, and no edge that is not an observed
triple. Five parts of the design must change before a specification can be
frozen, and none of them is a matter of taste: (1) the letter permutation
contradicts the professor's required item form, in which `A` **is** the
Answer by task semantics; (2) the weighted-sum utility carries thirteen free
weights, lets a weight decide an open-world safety question, and departs from
the exact lexicographic philosophy the project has defended everywhere else;
(3) a pre-answer clue whose only "contrast" against a letter is snapshot
absence must be inadmissible, not penalised; (4) the grounding rule for
distractor-owned facts is under-specified relative to the frozen `NOT_COVERED`
tests and has no unresolved state; (5) the publication path must not
substitute a greedy selection for an exact one. Section 14 lists the minimal
change set; the decision memo lists what only the human researcher may decide.

---

## 1. Scope, method and what was verified

### 1.1 What was read

In the order the prompt requires: `CLAUDE.md`;
`docs/context/00_context_index.md`; `docs/context/10_current_state_post_b2ef.md`;
`docs/context/EVIDENCE_TAXONOMY_V1.md`; `docs/context/PHASE_B_INPUT_CONTRACT.md`;
ARCH-1 in full (1,074 lines) and its summary JSON. In addition, the first 80
lines of `docs/context/11_final_benchmark_candidate_policy.md` (the open
configuration choices ARCH-1 depends on).

### 1.2 Concrete factual questions resolved outside those documents

Each question is stated first; only the smallest relevant file or lines were
read. No broad crawl was performed and the Okuhara sources were not opened.

| # | Question | Where it was resolved | Answer |
|---|---|---|---|
| Q1 | Does the project's own documentation fix `A` as the Answer in the required item form? | `docs/context/MCQ_Journal2_B2_B3_Context_Handoff_EN_2026-08-13.md` lines 22–37 (§2) and 741–760 (§26) | Yes. The professor-required form ends "Who is A?" and the graph's left side is "A/B/C/D (Answer + three distractors)". |
| Q2 | Is the frozen kernel objective a lexicographic tuple, and how many fields does the rationale key have? | `src/mcq_core.py` lines 629–700 (`ranking_key`, `ranking_key_v2`, `ranking_key_v3`) | Yes, "smallest tuple wins"; v1 has fourteen fields, v2 fifteen; v3 reorders three ordering-only fields. ARCH-1's "fourteen-field key" is accurate. |
| Q3 | Did the legacy generator fix `A = Answer`, and was that a considered choice? | `src/mcq_generation.py` lines 108–118 and 158–166 | Yes: the comment reads "random shuffle hay fix? Ở đây fix: A=answer, B=dist1, C=dist2, D=dist3", and the question line is "…choose which is A?". |
| Q4 | Which exact 0-1 solvers are already installed in `mcq-journal2`? | `conda run -n mcq-journal2 python -c "import …"` on 2026-09-18 | `scipy 1.17.1` with `scipy.optimize.milp` (HiGHS) present; `ortools`, `pulp`, `mip`, `highspy` absent; `networkx 3.6.1`, `numpy 2.4.6` present. |

Three supporting lines were also checked by `grep` only:
`docs/context/03_journal2_algorithm_spec.md` line 357 ("A simpler
lexicographic implementation is acceptable"); `docs/context/06_evaluation_plan.md`
lines 296, 335, 342 ("blinded and randomized presentation", "permutation
robustness", "randomized option order"); `docs/plans/MINIMAL_RESEARCH_CORE_PLAN.md`
lines 14 and 21 (author comprehensibility as the scientific priority).

### 1.3 What this review does not do

It does not measure anything on the development batches, does not run the
pinned KG, does not repair the two upstream issues of ARCH-1 §20, and does not
choose any of the human decisions. Where a yield cost is predicted below, it
is a prediction with its basis stated, not a measurement.

---

## 2. Findings register

Severity scale. **CRITICAL** = contradicts a stated requirement or a frozen
scientific boundary; the design cannot be frozen with it. **HIGH** = would
produce learner-facing items or paper claims a careful reviewer would reject.
**MEDIUM** = a real defect with a bounded, local fix. **LOW** = wording,
schema or consistency.

| id | sev | area | finding (one line) | fix in §14 |
|---|---|---|---|---|
| F-01 | CRITICAL | A/B/C/D | ARCH-1 permutes letters and calls fixed `A = Answer` a "positional leak"; the required form makes `A` the Answer by definition and no learner-visible leak exists. The real leak is the printed option order, which ARCH-1 does not model. | C1 |
| F-02 | HIGH | OWA | An optional pre-answer clue with `abs_g > 0` is only penalised; under ARCH-1's own candidate weights it routinely wins, so a weight decides an open-world safety question. | C3 |
| F-03 | HIGH | OWA | The mandatory `R*` case "L1 for one distractor, L0 for another" is not resolved; ARCH-1 §6.3 even says it "cannot occur". It occurs whenever `|R*| ≥ 2`. | C5 |
| F-04 | HIGH | OWA | The grounding rule for distractor-owned groups is exact-identity only; it lacks the canonical-equivalence and containment tests of `NOT_COVERED`, has no `UNRESOLVED` state when the index is unavailable, and has no granularity-risk axis. | C4 |
| F-05 | HIGH | objective | Weighted-sum utility: thirteen named weights (fifteen numbers with pre/post variants), a two-weight sweep, and a stated departure from the project's exact lexicographic philosophy. | C2 |
| F-06 | HIGH | solver | "Exact solver unavailable/timeout → greedy → publish with flag" mixes a heuristic into the exact method's published arm and makes the item set machine-speed dependent. | C6 |
| F-07 | HIGH | exposure | `RATIONALE_ALTERNATIVE` groups are "optional, preferred" before answering; they are singleton, distractor-owned discriminating clues that turn the item into an elimination puzzle, and they are the post-answer explanation the professor asked for. | C7 |
| F-08 | MEDIUM | universe | Bounding pre-key is blind to the three interaction effects (node sharing, key diversity, letter balance); no stability threshold is declared. | C9 |
| F-09 | MEDIUM | universe | `CE_COVER_ALT_RELAXED` is said to be "only possible with L2"; the alternative set can also be emptied by the eligibility, option-reference and self-loop screens. | C11 |
| F-10 | MEDIUM | class | The `CLASS` node consumes one of at most ten right-node slots, is constant (support 4), and carries a different provenance from every other node; the frame *sentence* and the graph *node* are two decisions, not one. | C8 |
| F-11 | MEDIUM | baseline | The "legacy baseline" replaces six operations of the historical code; ARCH-1 does not name the two objects apart, and one of the "unsafe" replacements (fixed `A`) was in fact correct. | C10 |
| F-12 | MEDIUM | leakage | A counterpart label that lexically contains a **distractor's** label is only a soft penalty (`W_dl = 1`); pre-answer it removes one option by elimination. | C3 |
| F-13 | MEDIUM | universe | The B3 stage needs a semantic index over the counterparts of all four choices; without it, every distractor-owned group is unresolved and the corrected admissibility rule empties the pre-answer optional tier. | C4 |
| F-14 | MEDIUM | solver | The decision matrix scores the exact solver 2/5 on "new dependency"; an exact MILP solver is already installed (HiGHS via scipy). The matrix's conclusion stands, its argument was understated. | C6 |
| F-15 | MEDIUM | process | The pre-registered budget rule of §16 depends on decisions that are still open (alternatives pre-answer, admissibility, key order); it cannot be frozen in its current wording. | C12 |
| F-16 | LOW | objective | The tier table calls alternatives "preferred" while the objective penalises them (`n_g = 1`, `s_g = 1`): an internal contradiction that disappears under C2 + C7. | C2 |
| F-17 | LOW | wording | Optional Answer-only facts are called "leakage"; under the required form they are *additional discriminating content*, which the handoff already names ("avoid additional A-only supplementary facts"). | C1 |
| F-18 | LOW | model | §3.6 allows a renderer to "dash a line" for containment support while §3.8 forbids any edge not observed in `K`; the containment relation must be a node–node annotation, never a choice–node edge. | C4 |
| F-19 | LOW | budget | An absolute `B_post` gives items with a larger `R*` systematically less context; whether the budget should be relative to the mandatory core is undecided. | C8 |
| F-20 | LOW | schema | `answer_letter`, `permutation_seed`, `CE_SOLVER_*_GREEDY_USED` and the three-valued grounding vocabulary must change with C1, C4, C6. | C11 |
| F-21 | LOW | claims | "The graph cannot imply an unsupported negative by construction" (§11.1) is true only at the level of asserted edges, not at the level of what a learner infers; the paper must not repeat it unqualified. | C3, C5 |
| F-22 | INFO | precedent | The kernel already minimises absence incidences inside a minimum-cardinality rationale (key 4, `+l0_incidences`); B3 cannot reduce the `R*` residual further without changing `R*`, which is forbidden. | — |

---

## 3. A/B/C/D semantics — the professor's form versus ARCH-1 §2(a), §13.5, §18

### 3.1 What the requirement says

The handoff (§2) records the professor-required form verbatim:

> A, B, C, and D are all Japanese Nobel laureates. A, B, and C worked at Kyoto
> University. B, C, and D were born in Japan. C and D graduated from Kyoto
> University. A is known for induced pluripotent stem cells. **Who is A?**
> Hitoshi Nozaki / Shin'ichirō Tomonaga / Toshihide Maskawa / Shinya Yamanaka

and, for the graph, "the left side has A/B/C/D (Answer + three distractors)".
The prompt for this review restates it: `A` = the Answer node; `B, C, D` =
the distractor nodes; the learner does not know which printed name is `A`.

### 3.2 Why fixed `A = Answer` is not a leak

The letters are **bound variables of the clue text**. The question "Who is
A?" *defines* `A` as the entity to be identified; the four **names** are the
options. The learner's task is the bijection between letters and names, and
the target is whichever letter the question names. Renaming the variable
(asking "Who is C?" with the same clues re-lettered) changes no information
available to the learner: every clue is invariant under a consistent
relabelling, and the question always names the target letter. A leak is a
signal that correlates with the **name** of the Answer; the identity of the
target *letter* carries none, because the letters are not the options.

I looked for a learner-visible leak under fixed `A` and found none:

* **Clue degree.** `A` appears in every `R*` clue and so tends to have the
  highest degree. The learner already knows `A` is the target; degree reveals
  nothing about which printed name `A` is.
* **Order of `B, C, D`.** If they follow the kernel's position order (the bit
  order of every coverage mask), the learner cannot see rank, score or
  position; nothing about the names follows.
* **Constancy across items.** `A` is the target letter in every item. Letters
  are not options, so there is no "always pick option A" strategy.
* **Post-answer graph.** Names are revealed there by design.

The one **real** positional leak is the one ARCH-1 does not model: the
**printed order of the four names**. The legacy code built
`map_nodes = [answer_idx] + distractors`; if the options are printed in that
list order, the Answer is always the first printed name. That is the leak the
legacy comment "random shuffle hay fix?" was worrying about, and it is fixed
by permuting the printed order, not the letters. `06_evaluation_plan.md`
already asks for "randomized option order" and "permutation robustness" —
both refer to the printed options.

### 3.3 ARCH-1 is also internally inconsistent on this point

§3.1 defines `c_0 = A` as the Answer "in the kernel's position order (bit
order of every coverage mask on the v4 record)". §2(a), §13.5 and §18 then
require a seeded letter permutation in which "the Answer is never at a fixed
letter", and the record schema (§12.3) carries `answer_letter: "C"`. Under
the permutation the kernel's 4-bit masks would have to be re-mapped for every
item; under fixed letters they are the graph's incidence masks unchanged
(handoff §26: "fact incidence can be encoded with a 4-bit A/B/C/D mask").
Fixed letters are therefore also the simpler and more traceable design.

### 3.4 Determination

* `A = Answer` **remains fixed by task semantics.** It is not a positional
  leak, and calling it one in the paper would be wrong.
* `B, C, D` = the three distractors **in the kernel's position order**,
  deterministic and recorded. Randomising them adds nothing for the learner
  and breaks mask alignment.
* The **printed option order** is an independent, recorded permutation:
  seeded per item, balanced across the benchmark so each printed position
  holds the Answer in about a quarter of the items (a Latin-square or
  block-balanced assignment is the standard remedy for position bias), and
  reused unchanged for the post-answer display so the participant is not
  confused by a re-ordering.
* The record replaces `answer_letter` and `permutation_seed` by
  `option_order` (four URIs in printed order), `answer_printed_position`, the
  balancing scheme and its seed. The "unsafe: fixed `A = Answer`" row of §18
  and the corresponding `summary.json` entry are withdrawn.
* ARCH-1 §2(a)'s observation that "every clue about any letter helps by
  elimination" remains true and is the reason §4 below matters.

Finding **F-01** (CRITICAL). The severity is about the requirement, not the
effort: the fix is small, but a frozen specification carrying the permutation
would generate items in the wrong form and a record schema that cannot
represent the right one.

---

## 4. Group atomicity under the open-world assumption — is it sufficient?

### 4.1 Three layers that must not be confused

| layer | what it is | what it licenses |
|---|---|---|
| **L-1 logical evidence semantics** | statements about the pinned snapshot `K`: `(d, p, o) ∈ K` or not; `NOT_COVERED` / `L0` / `L1` / `L2` as properties of an ordered `(Answer fact, candidate)` pair; `(d,p,o) ∉ K ⇏ ¬p(d,o)` | what may be *claimed* about `K`; never a negative about the world |
| **L-2 observed positive statements** | what an item *asserts*: every clue sentence and every drawn edge is a positive observed triple of `K` (plus the class membership with its own provenance); no negative sentence and no negative edge exists anywhere | what a reviewer can check against `K` triple by triple |
| **L-3 pragmatic implicature** | what a cooperative reader *infers* from a list of clues in a puzzle frame: (i) **exhaustivity** — a clue naming the letters that have property X is read as naming *all* of them, so unnamed letters are inferred not to have X; (ii) **uniqueness** — "Who is A?" presupposes that exactly one option satisfies A's description | nothing; implicatures are inferences the text invites, and they are cancellable by an explicit instruction |

ARCH-1 is correct at L-1 and L-2 and says so precisely (§3.8, §11.1). Its
claim that the graph "cannot imply an unsupported negative *by construction*"
holds only at L-2. Open-world safety for a **learner** is judged at L-3,
because the learner uses exhaustivity to eliminate options. ARCH-1 concedes
this ("residual implicature risk … measured (`abs_g`) and handled by the
legend text") but then handles it with a weight. Finding **F-21** (LOW) is
the wording; the substance is F-02.

Atomicity (§3.4) is **necessary**: exposing two of three edges of a group
manufactures a false exhaustivity implicature against the third letter, and
it is right that this is the single most important difference from the legacy
code. It is **not sufficient**, because a *complete* group with
`support(g) = {A, B, C}` still invites "D does not have X" at L-3, and whether
that inference is backed by anything depends on the grounding of `D`.

### 4.2 The case `support(g) = {A, B, C}`, `grounding(g, D) = ABSENCE_ONLY`

* If `grounding(g, D) = ALTERNATIVE_OBSERVED`, the implicature "D does not
  have X" is backed by an observed alternative value of `D` under the same
  key. That is exactly the evidential status of an `L1` incidence for a
  rationale fact: an **observed contrast**, phrased as an observation about
  `K`, with the multi-valued-predicate caveat of the taxonomy (§3). It is the
  kind of statement the whole pipeline is built on and is admissible.
* If `grounding(g, D) = ABSENCE_ONLY`, the implicature is backed by
  **nothing**. The snapshot is silent. Functionally, the clue presents an
  `L0` pair to the learner *as a contrast*. The taxonomy says `L0` "must not
  appear in a rationale presented as justification" and "is not evidence a
  student may be shown as a reason". A pre-answer clue is not formally a
  rationale, but the learner uses it exactly as a reason: to eliminate.
* The worst sub-case is the absent letter being `A`: "B, C and D were born in
  Japan" with no recorded birthplace for `A` says, at L-3, "A was not born in
  Japan", which is a statement about the **target** and actively misdirects a
  learner who knows that the Answer's name was born in Japan. The
  professor's own illustrative item contains this clue shape (its `A`,
  Shinya Yamanaka, was born in Higashiōsaka, Japan); the example is a format
  illustration, not an evidence policy, and it is precisely what an evidence
  discipline has to catch. Whether the pinned snapshot records his birthplace
  as a Japanese city (a containment case, §4.4) or not at all (an absence
  case) was not queried for this review; the structural point is the same.

**Why a penalty is the wrong instrument.** Under the candidate weights of
ARCH-1 §6.3 a support-3 group with one `ABSENCE_ONLY` letter scores
`W_sup·(3−1) − W_abs·1 = 8 − 3 = 5`, while a clean support-2 group scores
`W_sup·(2−1) = 4`. The default configuration therefore **prefers** the
implicature-bearing clue whenever it has one more supporter. ARCH-1's own
principle (§6.3: "the evidence semantics remain untradeable because they are
constraints and tiers, not weights") is violated by the one term that carries
open-world meaning. Whether a learner is invited to read absence as falsity
should never depend on the value of `W_abs`.

**Determination.** For the **pre-answer** clue set, an optional group with
`abs_g > 0` is **hard-inadmissible** (a constraint, not a weight). For the
**post-answer** graph, such a group is admissible: the answer is known, so no
misdirection can occur; the graph's purpose is explanation and shared
structure serves it; the missing edge is covered by the legend; and the count
of exposed `ABSENCE_ONLY` incidences is a reported metric and an early
lexicographic key (fewer is better). The human may choose the stricter
"banned in both exposures" arm (memo H16). The yield cost of the pre-answer
rule is unmeasured; it may be substantial because absence incidences
outnumber observed-alternative incidences in the pilot (8,485 `L0` versus
6,062 `L1` over all `(fact, candidate)` pairs, taxonomy §8), although that
ratio is over the whole candidate pool rather than over the three selected
distractors. It must be measured on the development batches before the rule
is frozen (memo H14). Finding **F-02** (HIGH).

**A cancellation the protocol can add.** Exhaustivity is a cancellable
implicature. A one-line participant instruction — "each clue lists the
letters for which the knowledge source records the fact; a letter that is not
listed may also have the property, the source may simply not record it" —
cancels it explicitly. It weakens elimination, which is honest, and it is a
protocol decision that belongs to the human study (memo H15). It complements
the admissibility rule; it does not replace it, because participants do not
reliably apply such instructions.

### 4.3 The mandatory `R*` case: L1 for one distractor, L0 for another

Let `R* = {f1, f2}`, with `f1` covering `d1` and `d3` at `L1` and `d2` at `L0`,
and `f2` covering `d2` at `L1`. This is the ordinary shape of a two-fact
minimum cover: a minimum-cardinality cover contains no redundant fact, so
each fact is the *only* cover of some distractor, and the other facts are
typically `L0` or `NOT_COVERED` for that distractor. ARCH-1 §6.3's remark
that "an `R*` fact with `abs_g > 0` … cannot occur" is wrong; in the pilot,
`L0` is the most frequent incidence.

The pre-answer clue "A is known for X" (from `f1`) invites, at L-3, "d2 is not
known for X". `K` does not support that: `d2` is `L0` under `κ_f1`. `R*` is
mandatory (§3.4 of ARCH-1 and memo H1), so this residual **cannot be removed
by selection**. It also cannot be reduced by B3: the kernel already prefers,
among minimum-cardinality covers with the same level profile, more `L1` and
fewer `L0` incidences (`ranking_key` fields 3–4), and B3 may not alter `R*`
(**F-22**). What B3 controls is the *presentation*. The OWA-safe policy is:

* **P1 — Answer-attribute phrasing, no exclusivity marker.** Every `R*` fact
  is verbalised as a positive statement about `A` from its own template
  ("A is known for X"), never "only A …", never "unlike B, C and D …", and
  never with a negative clause about any letter. If the `R*` group has
  supporters besides `A` (a `NOT_COVERED` distractor), atomicity requires them
  to be listed ("A and C are known for X"); omitting them would manufacture a
  false implicature, exactly the §3.4 argument.
* **P2 — Per-distractor explanation cites only observed alternatives.** After
  answering, the explanation for distractor `d` uses exactly the `R*` fact(s)
  that cover `d` at `≥ L1`, together with `d`'s observed alternative value
  under that key (the `COVER_ALT` group). It never cites an `R*` fact for
  which `d` is `L0`, and it never says "the snapshot records no X for d" to a
  learner; that sentence is diagnostic vocabulary (taxonomy §2). The record
  carries `explanation_basis[d] = {rationale_fact_index, level, alternative
  counterpart}` so the prose generator has no freedom here.
* **P3 — The graph draws every `R*` group with its full support.** A
  distractor with `L0` under an `R*` key simply has no edge to that node. The
  legend states what a missing edge means. The distractor's own observed
  alternative under that key is drawn when it exists (`COVER_ALT`), so the
  learner sees a positive recorded value, not a negative.
* **P4 — The residual is counted, not hidden.** `rationale_absence_incidences`
  = the number of `(f ∈ R*, d)` pairs at `L0`, per item and per cohort, is a
  first-class metric of the B3 output and a sentence in the paper's threats
  section.
* **P5 — Adapter invariant.** Under `main-l1`, every distractor has at least
  one `R*` fact at `≥ L1`; P2 therefore always has a basis. The B3 adapter
  asserts this and refuses an item where it fails (it cannot fail for a v4
  `main-l1` selection; the assertion documents the dependency).
* **P6 — Verbalization note (later task).** Rendering `R*` as one conjunctive
  clue about `A` ("A is known for X and died in Y") makes the *conjunction*
  the discriminating claim, which is what the kernel's coverage guarantee
  actually supports, and reduces the per-fact exhaustivity reading. This is
  a recommendation to the verbalization task, not an architecture change.

Nothing in P1–P6 converts `L0` into falsity, creates or upgrades a level, or
alters `R*`. Finding **F-03** (HIGH).

### 4.4 The grounding rule is under-specified relative to the frozen tests

ARCH-1 §3.6 defines, for distractor-owned groups,
`ALTERNATIVE_OBSERVED ⇔ c ∉ support(g) and O_c(κ) ≠ ∅`. That is exact
identity (or canonical identity, when grouping used it). The frozen
`NOT_COVERED` test has **three** clauses (taxonomy §1): exact equality,
trusted canonical/redirect equivalence, and *candidate-object-under-claim*
containment. Without the third clause, "A, B and C were born in Japan" with
`D` recorded as born in Higashiōsaka is classified `ALTERNATIVE_OBSERVED`,
and the clue implicates that `D` was not born in Japan — a contrast that `K`
itself, read through the allowlisted containment hierarchy, contradicts.

Three consequences.

1. The grounding vocabulary needs two further values:
   `SHARED_BY_CONTAINMENT` (the letter's recorded value lies under the group's
   counterpart; the letter supports the clue without owning an edge to that
   node) and `UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE` (the closure could not
   run). The taxonomy's §5 rule — an unavailable index must never relabel an
   observed alternative as anything else — applies verbatim.
2. A group with a `SHARED_BY_CONTAINMENT` or `UNRESOLVED` letter is
   **inadmissible pre-answer**: it cannot list the letter (no observed edge)
   and cannot omit it (false implicature). Post-answer it may be drawn with
   the containment relation shown as a **node–node** annotation
   (Higashiōsaka ⊂ Japan). ARCH-1 §3.6's "a renderer can dash a line" would
   draw a choice–node edge that is not in `K`, which §3.8 forbids
   (**F-18**, LOW).
3. The reverse direction — the letter's recorded value is *coarser* than the
   group's counterpart (`D` born in "Japan", group counterpart Higashiōsaka)
   — is the `CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT` granularity risk of the
   taxonomy. ARCH-1 copies that risk for Answer-owned groups (`risk_g`) but
   computes nothing for distractor-owned ones. The new stage must compute the
   same risk annotation on every group and treat a risk-bearing letter as
   inadmissible pre-answer, consistently with whatever granularity policy the
   publication run adopts (`11_final_benchmark_candidate_policy.md` §1.2).

All of this needs a semantic index that covers the counterparts of **all four
choices**. The v4 index covers the Answer's source-object set only
(`PHASE_B_INPUT_CONTRACT.md` §6.2); ARCH-1 §19.4 notes the gap and accepts
exact-identity fallback. Under the corrected admissibility rule that fallback
would mark every distractor-owned group unresolved and empty the pre-answer
optional tier, so for a publication run the B3 stage must build its own index
over the enlarged object set, offline, under its own cache key, used for
grounding and node identity only and never to re-decide a level (ARCH-1
already states the last clause). Findings **F-04** (HIGH) and **F-13**
(MEDIUM).

### 4.5 Discrimination is not the same axis as pedagogy

ARCH-1 rewards support size as pure pedagogy (`W_sup`) and penalises
Answer-only groups as "leakage" (`W_ans`). Under the required form every
optional group with `support(g) ≠ C` is **discriminating**: it partitions the
letters and gives the learner an elimination route beyond `R*`. A support-3
group that excludes `A` is, by exhaustivity, informationally the statement
"A lacks X" — as discriminating as an Answer-only clue, but negative and
resting on grounding. The clean formulation is to make the **discrimination
pattern** of a group explicit — `(support set, grounding of each non-support
letter)` — and to let the human declare which patterns are admissible before
answering. The handoff already gives the author's intent: "supplementary
facts should generally have degree ≥ 2 across A/B/C/D; avoid additional
A-only supplementary facts; the explicit final rationale may be A-only"
(§20, §26). "Leakage" is the wrong word for Answer-only optional facts; the
handoff's "additional A-only supplementary facts" is right (**F-17**, LOW).
The pattern question is memo H14; the distractor-label leak of **F-12**
(MEDIUM) belongs to the same rule: a counterpart label containing a
distractor's name removes one option by elimination and must be a hard
pre-answer screen, mirroring the hard Answer-label screen, while post-answer
it is harmless because the names are revealed.

---

## 5. The objective: weighted sum versus lexicographic versus hierarchical

### 5.1 What ARCH-1 proposes and what it admits

§6.3 maximises an integer-weighted utility with thirteen named weights
(`W_sup, W_tier, W_verb, W_div, W_red, W_bal, W_len, W_ans, W_single, W_abs,
W_risk, W_soft, W_dl`), two of which take different values before and after
answering, so fifteen numbers in all. §16 sweeps two of them (`W_ans`,
`W_abs`) at three values each; the other eleven are asserted. §9.1 names
"a weighted objective invites weight tuning on the evaluation data" as the
recommendation's weakest point and answers it procedurally. The reason given
for weights over a lexicographic key (§6.3) is that "here every term is
pedagogical and trades are the point". That premise is not true of `W_abs`,
`W_risk`, `W_soft`, `W_dl` and `W_ans`, which are safety- or
discrimination-flavoured, and §4 above shows one of them deciding an
open-world question.

### 5.2 The four formulations, compared on the criteria the prompt names

| criterion | weighted-sum 0-1 | lexicographic 0-1 (sequential solves) | ε-constraint / hierarchical | hybrid: hard safety + lexicographic primary + weights for polish |
|---|---|---|---|---|
| free hyperparameters | 13–15 real numbers | 0 numbers; one **order** of `k` keys | `k−1` tolerances `ε_i`, each in the key's own unit; `ε = 0` recovers lexicographic | the polish weights only (2–4 numbers) plus the order |
| reviewer defensibility | "why 4 and not 5?" for every weight; the sweep covers two | "we prefer X, then Y, then Z"; the same form the kernel uses and the paper already defends | as lexicographic, plus one sentence per non-zero `ε` | good if the polish tier is genuinely secondary; a reviewer will still ask why polish needs weights when the kernel used keys 8–11 for the same quantities |
| sensitivity-analysis burden | a 13-dimensional space; a 3-level factorial is `3^13 ≈ 1.6·10^6` cells; in practice a two-weight slice | adjacent-key swaps, `k−1` named variants, each a versioned objective (the exact precedent of rationale objective v1/v2/v3 and the Augustus finding) | key swaps plus a one-dimensional sweep per non-zero `ε` | key swaps plus a small weight sweep |
| interpretability of a chosen set | "it scored 41" | "it has the most shared edges among balanced sets; among those, the most distinct keys; …" — every step is a sentence | as lexicographic with "within one shared edge of the best" | mixed |
| consistency with the project's exact lexicographic philosophy | low; a new philosophy for one stage | high; the kernel's `ranking_key` and the six-key combination objective are exactly this, and `03_journal2_algorithm_spec.md` §11 says a lexicographic implementation is acceptable | high | medium |
| encodes "safety first, mandatory `R*`, compactness, shared information, controlled discrimination, diversity" | only implicitly, and inversions are possible (§4.2 example) | exactly, by placing hard rules first and keys in that order | exactly, with declared slack | mostly |
| degenerate trade-offs | a large pile of small terms can outweigh one important one | one unit of a higher key beats any amount of a lower key; mitigated by coarse top keys and by putting count-like keys where a unit is meaningful | tunable | tunable |
| solver cost | one solve | `k` solves with one equality added per level; trivial at this instance size (hundreds of binaries) | `k` solves | `k` solves |
| determinism of the selected set | needs the canonical fix (ARCH-1 §13.3) | the canonical fix is the last key; the selection is a pure function of the input and does not depend on which optimum a solver returns | same | same |

Two technical remarks. (i) A lexicographic objective **is** a weighted sum
with sufficiently separated integer weights (each weight larger than the
range of everything below it), so nothing in ARCH-1's ILP machinery changes;
sequential solves are simply the numerically clean way to realise it.
(ii) ARCH-1 §10 and §13.3 already perform a *sequential lexicographic fix*
among optimal solutions. Generalising that protocol from "tie-break" to "the
whole objective" is an extension of ARCH-1's own mechanism, not a new design.

### 5.3 Mathematical recommendation

**Constraints + ε-lexicographic 0-1 optimisation with every `ε_i = 0` by
default.** Safety and mandatory preservation are hard constraints
(admissibility of §4, `G_mand` fixed, budget, nesting, `COVER_ALT`, `K_A`).
Everything else is an ordered list of integer keys solved sequentially; the
canonical group order of ARCH-1 §13.1 is the last key. Candidate orders, to
be **recorded by the human** (memo H13), in the kernel's pattern "safety
signals, then evidence-flavoured quantities, then quality":

*Pre-answer* (admissible optional groups only; `K_A = 0` hard):
1. fewer distractor letters with no admissible optional clue (balance);
2. more shared information, `Σ z_g (s_g − 1)`;
3. more distinct predicate-direction keys (diversity);
4. fewer clue sentences, `Σ z_g` (compactness under the hard cap);
5. lower tier sum; 6. fewer tokens; 7. canonical order.

*Post-answer* (`S_pre` fixed, `COVER_ALT` hard, `K_A ≤ 1` hard):
1. fewer exposed `ABSENCE_ONLY` incidences; 2. fewer granularity-risk-bearing
groups; 3. more shared information; 4. more distinct keys; 5. fewer right
nodes used; 6. lower tier sum; 7. fewer tokens; 8. canonical order.

Rarity (`rare_g`) is at most a late key (memo H9). If the human wants a graded
trade-off anywhere — for instance "one fewer shared edge is acceptable for
two more distinct keys" — that is one `ε_i > 0`, declared in the key's own
unit, and it is the only number the paper then has to defend.

### 5.4 What remains a human publication decision

The mathematics above says which formulation has the fewest free parameters,
the clearest sentences and the best fit with the kernel. It does **not**
decide (a) whether the author accepts that a lexicographic objective never
trades a higher key for a lower one, (b) the key order, (c) whether any
`ε_i` is opened. Those three are memo H13 and are the author's. Finding
**F-05** (HIGH); **F-16** (LOW) is resolved as a side effect because
alternatives stop being both "preferred" and penalised.

---

## 6. Solver strategy and the fallback

### 6.1 Terminology

* **CP-SAT** (OR-Tools) is a constraint-programming solver built on a SAT
  core with linear-programming relaxations. It requires integer coefficients
  and bounded integer variables; it is not a general MILP solver (no native
  continuous variables). A pure 0-1 program with integer keys is its native
  domain, and its `OPTIMAL` status is a proof of optimality in exact integer
  arithmetic.
* **CBC via PuLP** (or `python-mip`) is a mixed-integer linear-programming
  route: branch-and-cut in floating point, "optimal" within a relative gap
  tolerance that must be set to zero and then verified.
* **HiGHS via `scipy.optimize.milp`** is a second MILP route, also floating
  point, exposed by scipy since 1.9. It is **already installed** in
  `mcq-journal2` (scipy 1.17.1, verified 2026-09-18); OR-Tools and PuLP are
  not.

All three model ARCH-1's program and the lexicographic sequence of §5
without modification.

### 6.2 Which is preferable here

| criterion | CP-SAT | CBC/PuLP | HiGHS/scipy |
|---|---|---|---|
| new dependency | yes (large binary wheel) | yes (small) | **no** |
| optimality certificate | exact integer | floating, gap → 0, verify | floating, gap → 0, verify |
| API for ten constraint families | expressive, readable | readable | matrix form (`A_ub`, `b_ub`, integrality), a little more code, fully explicit |
| single-thread determinism | yes, with seed and one worker | yes | yes (HiGHS is designed to be deterministic) |
| fit with `MINIMAL_RESEARCH_CORE_PLAN.md` (author-comprehensible, few dependencies) | weakest | medium | **best** |

ARCH-1's decision matrix (§8) scored the exact route 2/5 on "new dependency /
engineering risk". With HiGHS present that cost is zero; the matrix's
conclusion was right and its argument understated (**F-14**, MEDIUM).

**Recommendation.** HiGHS through `scipy.optimize.milp` as the production
solver, `mip_rel_gap = 0`, single thread, scipy version pinned in the
manifest; CP-SAT as the alternative if the human prefers an integer-exact
certificate and accepts the dependency (memo H6). Whatever the solver, two
verification steps are required and are solver-independent:

1. **Independent re-check of every published selection** in pure Python:
   recompute each hard constraint and the full lexicographic key vector of
   the returned set and compare with the solver's reported values. This
   catches tolerance artefacts and is the "author can explain it in a viva"
   layer.
2. **Exhaustive oracle** on every small instance of the test set (ARCH-1 §7.2
   already proposes it), extended to the sequential protocol.

Because the canonical fix makes the selected set a pure function of the
input, substituting one exact solver for another must produce byte-identical
records; that equality is itself a cheap cross-solver test if a second solver
is ever installed.

### 6.3 The fallback must leave the publication path

ARCH-1 §9, §10 and §14: on solver unavailability or timeout, run greedy and
publish the item flagged `CE_SOLVER_*_GREEDY_USED`, "excluded from the exact
denominator". This should not survive into the specification, for four
reasons.

1. **It contaminates the method arm.** The paper's proposed method is
   "exact selection over a declared universe". An item selected by greedy is
   a baseline-B3 item; publishing it inside the method's benchmark, however
   flagged, means the human study evaluates a mixture, and the flag will not
   travel into every table.
2. **It makes the benchmark machine-dependent.** A timeout is a property of
   the machine and the load, not of the item. Two runs of the same frozen
   configuration could publish different item sets.
3. **It hides a signal.** At a few hundred binaries and `B ≤ 10` a timeout
   is implausible; if one occurs it indicates a universe that the bounding
   step failed to control, which is a defect to fix, not to route around.
4. **It contradicts the project's own kernel discipline**, which never
   substitutes a heuristic for the exact set cover and instead declares the
   scope (`FULL_EXACT` / `POOL_EXACT`).

**Determination.** In publication mode every solve of every published item
must return an optimality certificate (`OPTIMAL` / scipy `status == 0`) and
pass the pure-Python re-check; any other outcome is `CE_SOLVER_NOT_OPTIMAL`,
the item is **not** published, the count is reported in the manifest, and
the runner exits non-zero so the condition is impossible to miss. Greedy
remains baseline **B3**, run separately and written to its own output, and
may additionally be run in development mode for the ILP–greedy agreement
metric of §15 — never as the selection. Finding **F-06** (HIGH).

---

## 7. Pre-answer versus post-answer exposure

### 7.1 `RATIONALE_ALTERNATIVE` groups before answering

ARCH-1 §5.3 makes the distractors' observed alternative values
"optional, preferred" before answering (H3 default) and required after.
Consider what a pre-answer alternative does. The clue set becomes

> A was born in Kyoto. B was born in Osaka. C was born in Tokyo. D was born
> in Nagoya.

Three consequences.

* **It changes what the item measures.** With `R*` alone, the learner must
  know which name has the discriminating property (or eliminate). With the
  alternatives, the learner can identify `A` by knowing the birthplace of
  *any three* names — or of any one name that then goes to a specific
  distractor letter. The item becomes a matching puzzle over four singleton
  facts rather than a test of the rationale.
* **It exposes the discriminating key three more times**, which makes the
  intended contrast structure obvious and makes the item easier; not "too
  obvious" in the sense of naming `A`, but in the sense of multiplying
  routes to it.
* **The OWA argument for showing them early is weaker than it looks.**
  Stating "B was born in Osaka" does replace an exhaustivity implicature by an
  observed statement, but for multi-valued keys the exclusivity reading
  survives anyway (the taxonomy's `almaMater` example), so alternatives do
  not buy the clean semantics they seem to.

Against that, the professor's stated purpose of the post-answer graph is that
participants **understand the answer after responding**. The alternatives
are exactly that explanation: "B is not A because B's recorded birthplace is
Osaka". They are singleton, distractor-owned groups; under ARCH-1's own
objective they are penalised (`n_g = 1`, `s_g = 1`), which contradicts the
"preferred" label (**F-16**).

**Determination.** Alternatives are **post-answer, required** (`COVER_ALT`)
and **pre-answer off by default**; "alternatives shown before answering" is
a declared ablation arm, not the method. Human decision H3, with the stated
pedagogical reasons. Finding **F-07** (HIGH).

### 7.2 Context facts and rationale facts need different policies

| fact class | pre-answer | post-answer |
|---|---|---|
| class frame | mandatory sentence (required by the form; §8) | caption or budget-exempt node (§8) |
| `MANDATORY_RATIONALE` (`R*`) | mandatory, full support, Answer-attribute phrasing, no exclusivity marker (P1) | mandatory; per-distractor explanation basis = the `L1` fact(s) covering that distractor (P2) |
| `RATIONALE_ALTERNATIVE` | off by default (ablation arm) | required, one per distractor where an eligible alternative exists |
| `OPTIONAL_CONTEXT` | admissible only if: support ≥ 2; every non-support letter is `ALTERNATIVE_OBSERVED` with granularity risk `NONE`; verbalizable; no Answer-label or distractor-label leak; `K_A = 0` | admissible; `ABSENCE_ONLY` and risk-bearing letters allowed but ordered against and counted; `K_A ≤ 1`; legend |
| `EXCLUDED` | never | never |

ARCH-1's "one universe, one scoring model, two nested selections" (§11.1)
survives intact; only the admissibility sets and the key lists differ
between the two solves, which its parameterised `SOLVE` already supports.

---

## 8. Class frame sentence versus `CLASS` graph node — two decisions

**A. Must the pre-answer question state the shared class?** Yes. The
required form opens with "A, B, C, and D are all …", the candidate pool was
built from that class, and the sentence is non-discriminating (support 4).
Its provenance is remote category membership at retrieval time, cached and
recorded — not the pinned snapshot — and the paper must say so once
(ARCH-1 §3.7 and §19.2 already do). Two caveats are upstream, not B3's: the
class is a `first_feasible_class`, never described as optimal (CLAUDE.md §9),
and a class label with a recorded `soft_overlap` against the Answer label is
a class-leak decision of the v6 selector and the publication policy. B3 only
prints the level. Confidence HIGH.

**B. Must the post-answer graph contain a `CLASS` right node?** Not
necessarily, and ARCH-1 should not have folded the two questions into one
(H8). The node is constant (support 4), explains nothing about *why* `A` is
the answer, carries the one provenance that differs from every other node
(ARCH-1 threat 2), and consumes one of at most ten right-node slots — ten to
twenty-five percent of the explanation budget. The frame sentence has already
been read. In favour of the node: the author's original drawing had it, it
anchors the picture visually, and text and graph then say the same thing.

**Determination.** Render the class as a **caption** of the graph ("all four
are Japanese Nobel laureates", with its own provenance line) and keep it
outside the right-node budget; if the human prefers the node, keep it
**budget-exempt** and visually marked by provenance. Either way `B_post`
counts `ENTITY` nodes only, so the budget sweep and the baseline comparison
are not distorted by a constant. Finding **F-10** (MEDIUM); memo H8a/H8b.
The related question of an absolute versus mandatory-relative budget
(**F-19**, LOW) is memo H7.

---

## 9. Exactness over a bounded universe

### 9.1 Is `UNIVERSE_FULL` / `UNIVERSE_BOUNDED` defensible?

Yes, on three conditions that ARCH-1 mostly meets: the universe construction
is deterministic and fully recorded (screens, tiers, `N_max`, pre-key,
scope flag on every record); "exact" is claimed **only** over the declared
universe (§5.4, §9 reason 2, §19.7 all say so); and the two objects with a
scientific claim attached — answerability and open-world safety — do not
depend on the bounding, because bounding touches `OPTIONAL_CONTEXT` only
while the mandatory and alternative tiers are always complete. That last
sentence is the one the paper must state explicitly: **bounding can change
which context is shown, never whether the item is answerable from its clues
or whether an exposed contrast is grounded.**

### 9.2 Can a deterministic `N_max = 200` pre-key bias the optimum?

Yes, in a specific and characterisable way. The pre-key
`(−|support|, tier, unverbalizable, rarity rank, label length, identity)`
ranks groups by the *modular* attributes the objective rewards, so the
truncation keeps what the objective likes group by group and is
"bias-aligned" for those terms. It is **blind to the three interaction
effects**:

* **node sharing** — a low-support group on a node that a mandatory or
  alternative group already pays for costs zero extra budget and can be the
  best context available, yet it ranks low and is cut;
* **key diversity** — under a common key (places: `birthPlace IN`) the top
  200 can all share one key, starving the diversity term;
* **letter balance** — the only groups covering a particular distractor may
  sit below the cut.

With a lexicographic objective the bias is easier to state: the bounded
optimum equals the full optimum whenever every group of the full optimum
survives the cut; otherwise the difference appears first at the earliest
key that depends on a cut group. Finding **F-08** (MEDIUM).

### 9.3 Minimum required sensitivity analysis and a safer bounding

1. **Stratified bounding** before `N_max`: always keep (i) every optional
   group on a node already carried by a mandatory or alternative group,
   (ii) the top `k` groups per distinct key, (iii) the top `k` groups per
   distractor letter, then fill to `N_max` by the pre-key. Record the strata.
2. **Stability at doubling.** For every bounded item of the development
   batches re-solve at `2·N_max`, `4·N_max`, and `UNIVERSE_FULL` when
   `|G| ≤ 2,000`; report the share of items whose `S_pre` and `S_post` are
   unchanged and the earliest key at which they differ.
3. **Declared threshold.** Choose the smallest `N_max` at which at least a
   declared share (a human number; 99 % is the natural candidate) of bounded
   items is stable at doubling; the threshold is written into the
   pre-registration document (memo H11, H18).
4. **Report by cohort** (persons versus places/polities), because the
   IN-heavy neighbourhoods that trigger bounding are concentrated there.

---

## 10. The "legacy baseline" — what may be called legacy

ARCH-1 §7.5 and §18 reimplement the author's heuristic offline while
replacing: `next(iter(set))` picks (canonical order), live-SPARQL popularity
(pinned-KG counts), `get_diff_fact` absence-as-contrast (frozen levels),
fixed `A = Answer` (permutation), fabricated fallback prose (none), hard-coded
`MERGE_MAP` / `SYNONYM_MAP` (declared equivalence), a fifth left node from
SPARQL (rejected), synthetic relation labels (none). After eight
replacements the object is not the historical implementation, and a reviewer
who reads "legacy baseline" will assume it is.

**Determination.** Two named objects, never conflated:

* **B2-literal** — the historical implementation as it stands: network
  dependent, non-deterministic, open-world unsafe. It **cannot be re-run
  reproducibly** and is reported as such; any outputs the author has kept
  may be shown qualitatively with their date.
* **B2-normalised** — the offline, deterministic reimplementation
  "in the spirit of" the author's prior design, with a table of every
  replacement and its reason. The "fixed `A = Answer`" row is **withdrawn**
  from that table (§3: it was correct); the printed option order is
  permuted as for every other method. Two sub-variants are useful:
  **B2-structural** keeps `get_diff_fact` (absence as contrast) and is run
  for structural metrics only, never shown to a human, to count how often the
  legacy logic would expose an `L0` pair as a contrast — a number the paper
  can use; **B2-safe** uses the frozen levels and is the variant a human may
  see.

The paper must say that B2-normalised is a reimplementation and list the
replacements; it must not imply identity with the historical code. Finding
**F-11** (MEDIUM); memo H17.

---

## 11. Upstream issues — do they block B3 implementation or only publication?

| issue | blocks B3 implementation? | blocks the final publication run? | note |
|---|---|---|---|
| `granularity_clean.apply_granularity_policy()` returns `STATUS_NO_RISK_PRESENT` under `report-only` with a non-zero incidence count | **No.** B3 reads the rationale's own incidence count and per-pair risks, never the status string (ARCH-1 §20 already requires this). | **Yes, if** the publication configuration is `report-only` and the status string is published on the record; the branch is not taken under `require-clean`. | Fix in a separate task before the publication run; not touched here. |
| An unverbalizable fact can sit in a selected `main-l1` rationale (contract §3.2 versus kernel key 9) | **No.** B3 emits `CE_RATIONALE_NOT_VERBALIZABLE`, produces the graph, blocks the clue text; development runs proceed. | **Yes.** Affected items have no clue text; the publication configuration must record H5 (a versioned `require-verbalizable` policy upstream, template coverage expansion, or exclusion with a reported yield). | Part of CLAUDE.md work-order step 1. |
| Open v4 publication choices (candidate validity, granularity policy, objective version, `max_nodes`) | **No.** B3 must be configuration-agnostic and consume whatever frozen configuration is recorded. | **Yes**, by construction of the work order: step 2 waits for step 1. The B3 budget sweep and the `N_max` stability analysis must be (re-)run on the frozen configuration before pre-registration, because a configuration change changes the development-batch outputs the sweep reads. | Cheap and offline. |

One process note. CLAUDE.md orders the remaining work as: record the
configuration; run the publication benchmark; verbalization and the
bipartite graph; human evaluation. Implementing B3 against the development
batches produces no publication output and is additive, but the human should
confirm explicitly that building B3 before the final benchmark is acceptable
under that order (memo, closing note).

---

## 12. For and against the current preferred architecture

### 12.1 What ARCH-1 gets right and must be kept

* **The unit of exposure is the clue group `(κ, o)`, not the edge**, and a
  group is exposed whole or not at all. This is the correct open-world
  safeguard at the level of asserted content and the correct sentence unit.
* **`IN` and `OUT` never merge**; the direction is part of identity, drawing
  and verbalization.
* **Nothing upstream is touched.** Levels are copied, `R*` is consumed as
  given, LRoleSim is read as frozen ranks and scores, no similarity is
  recomputed, no `AnswerCase` is constructed, no v4 artefact is written.
* **Safety is expressed as hard constraints and tiers** wherever ARCH-1 did
  so (mandatory groups, budget, nesting, `COVER_ALT`, the `K_A` cap, the
  hard screens). §4 asks that the remaining safety property (`abs_g`,
  containment, risk) join them.
* **One universe, one model, two nested selections**, so the graph can
  never omit a clue and every clue is an observed triple.
* **Exact selection over a declared universe**, scope stated on every
  record, an exhaustive oracle for small instances, a deterministic canonical
  fix so the chosen optimum is a pure function of the input.
* **Every edge carries provenance**; the class node carries a different
  provenance and says so.
* **The status taxonomy** distinguishes skipped, flagged, relaxed and failed
  items, and ARCH-1 does not repair upstream defects in passing.
* **The evaluation plan**: budget sweep on development data, a
  pre-registered choice rule, the human test set never used for tuning,
  method-agreement metrics, five baselines and five one-switch ablations.

### 12.2 Where it must change

Summarised from §§3–10: the letter permutation (F-01); the weighted
objective (F-05, F-16); absence-grounded and containment-grounded clues
before answering (F-02, F-04, F-12, F-13); the unresolved mandatory-`R*`
presentation policy (F-03, F-21); the greedy fallback in the publication path
(F-06, F-14); alternatives before answering (F-07); the class node inside the
budget (F-10, F-19); interaction-blind bounding without a stability threshold
(F-08); incomplete `COVER_ALT` relaxation reasons (F-09); the naming of the
legacy baseline (F-11); the wording "leakage" for Answer-only context (F-17);
the containment "dashed line" (F-18); the schema and status changes that
follow (F-20); and a pre-registration rule written before the decisions it
depends on (F-15).

---

## 13. Minimal architecture changes required before implementation

Each change is small; together they are the difference between a design that
would generate the professor's item form safely and one that would not. They
should be recorded in a **new** file (ARCH-2 revision), not by editing
ARCH-1, which stays as the record of the first design.

| id | change | resolves | needs human decision? |
|---|---|---|---|
| C1 | Letters fixed by role: `A` = Answer, `B/C/D` = distractors in kernel position order. The printed option order is an independent, recorded, benchmark-balanced permutation reused for the post-answer display. Replace `answer_letter` / `permutation_seed` with `option_order`, `answer_printed_position`, scheme and seed. Withdraw the "positional leak" rows in §18 and the summary JSON. Rename optional Answer-only context to "additional A-only supplementary facts". | F-01, F-17 | H10 (confirm; it follows from the required form) |
| C2 | Replace the weighted utility with hard constraints plus an ordered list of integer keys solved sequentially, `ε_i = 0` by default, canonical order last. Record the key order as a versioned objective (`ce_objective/…`) and define the adjacent-swap ablation set. | F-05, F-16 | H13 (formulation and order) |
| C3 | Pre-answer admissibility as a hard rule on optional groups: support ≥ 2; every non-support letter `ALTERNATIVE_OBSERVED` with granularity risk `NONE`; verbalizable; no Answer-label and no distractor-label lexical leak; `K_A = 0`. Post-answer: `ABSENCE_ONLY` and risk-bearing letters admissible, ordered against, counted, legend. Measure the pre-answer yield cost on the development batches before freezing. | F-02, F-12 | H14, H16 |
| C4 | Grounding rule with the three `NOT_COVERED` tests (exact, canonical equivalence, containment), two further values (`SHARED_BY_CONTAINMENT`, `UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE`), and a granularity-risk annotation on every group. Containment drawn as a node–node annotation only. A B3 semantic index over the counterparts of all four choices, offline, own cache key, never used to re-decide a level. | F-04, F-13, F-18 | H2 (vocabulary only) |
| C5 | The `R*` presentation policy P1–P6: Answer-attribute phrasing, per-distractor explanation basis restricted to `≥ L1` facts with their observed alternative, full-support drawing, `rationale_absence_incidences` as a metric, adapter invariant, conjunctive verbalization note. Correct the §6.3 remark that the case cannot occur. | F-03, F-21, F-22 | H1 (confirm) |
| C6 | Publication mode: exact optimum with certificate and pure-Python re-check for every solve of every published item; otherwise `CE_SOLVER_NOT_OPTIMAL`, item not published, count in manifest, non-zero exit. Greedy is baseline B3 only, in its own output. Solver: HiGHS via scipy (present) or CP-SAT (new dependency); version pinned. Drop `CE_SOLVER_*_GREEDY_USED` from the publication path. | F-06, F-14 | H6 |
| C7 | `RATIONALE_ALTERNATIVE`: post-answer required, pre-answer off by default, "pre-answer alternatives" as a declared ablation arm. Exposure-policy table of §7.2 in the specification. | F-07 | H3 |
| C8 | Class frame sentence mandatory (form); class rendered as caption or budget-exempt node; `B_post` counts `ENTITY` nodes only. Decide absolute versus mandatory-relative budget. | F-10, F-19 | H8a, H8b, H7 |
| C9 | Stratified bounding (node-sharing, per-key, per-letter strata) before `N_max`; stability-at-doubling analysis with a declared threshold; per-cohort reporting; the explicit sentence that bounding never affects answerability or grounding. | F-08 | H18 (threshold) |
| C10 | Two named legacy objects: B2-literal (not reproducible, reported as such) and B2-normalised (with the replacement table; the fixed-`A` row withdrawn), optionally B2-structural for the absence-as-contrast count. | F-11 | H17 |
| C11 | `COVER_ALT` relaxation reasons: `L2`, all alternatives screened (with the screen), none in the pinned KG; status `CE_COVER_ALT_UNSHOWABLE` with reason; human decides publishability. Schema: grounding vocabulary, statuses, `explanation_basis`, `option_order`, objective record as a key vector. | F-09, F-20 | — |
| C12 | Re-derive the §16 choice rule after H3/H13/H14 are recorded; write the pre-registration document (rule, thresholds, budgets, key order, `N_max`, solver, scipy version) as a dated file before any human data. | F-15 | H11 |

---

## 14. Conclusion

**NOT_READY_FOR_SPEC_FREEZE.**

The design would become ready when (a) the human researcher has recorded the
decisions in the memo that are marked as requiring approval — at minimum
H1, H3, H5, H6, H8b, H10, H13, H14 — and (b) an ARCH-2 revision incorporates
C1–C12 in a new file with an updated summary JSON. Nothing in this review
requires touching a frozen module, a v1–v4 output or `R*`; every change is
in the new stage's specification, its record schema and its evaluation
protocol.

The most important sentence for the paper that follows from this review:
**the item and the graph assert only observed facts; what a learner infers
from an unlisted letter is controlled by admissibility before answering, by
the legend and the explanation basis after answering, and is measured, not
assumed away.**

---

## 15. Cross-reference to the human decisions

The memo gives, for each of H1–H12 and the six decisions this review adds
(H13–H18), the restated decision, the project evidence, the alternatives and
their risks, a recommended candidate, a confidence level and whether human
approval is mandatory. Summary:

| id | recommended candidate | confidence | human approval |
|---|---|---|---|
| H1 | `R*` always in the pre-answer clues | HIGH | MUST (it defines the item) |
| H2 | separate grounding vocabulary in code, one observation rule in the paper, plus `SHARED_BY_CONTAINMENT` and `UNRESOLVED` | HIGH | SHOULD (paper wording) |
| H3 | alternatives post-answer only; pre-answer as an ablation arm | MEDIUM-HIGH | MUST |
| H4 | `K_A` = 0 before, ≤ 1 after | HIGH / MEDIUM | MUST (post value) |
| H5 | a versioned `require-verbalizable` policy in a new runner generation, plus template-coverage expansion; cost measured | MEDIUM | MUST (publication configuration) |
| H6 | HiGHS via scipy, exact-only, re-check; CP-SAT as alternative | MEDIUM-HIGH | MUST (dependency and policy) |
| H7 | groups before, `ENTITY` nodes after; absolute budget with mandatory share reported | HIGH / LOW | SHOULD |
| H8a | frame sentence mandatory | HIGH | confirm |
| H8b | class as caption or budget-exempt node | MEDIUM | MUST |
| H9 | rarity as a late key or annotation only | HIGH | delegate with sign-off |
| H10 | `A` fixed; `B/C/D` kernel order; printed option order permuted and balanced | HIGH | MUST (confirms the form) |
| H11 | dated, frozen pre-registration file signed by the author before human data | HIGH | MUST |
| H12 | template-only explanation prose for the benchmark | HIGH | MUST |
| H13 | constraints + lexicographic keys, `ε = 0`; key order as proposed in §5.3 | HIGH (form) / MEDIUM (order) | MUST |
| H14 | pre-answer admissibility rule of C3, after measuring yield | MEDIUM | MUST |
| H15 | non-exhaustivity instruction in the participant protocol | MEDIUM | MUST |
| H16 | `ABSENCE_ONLY` admissible post-answer with legend and key | MEDIUM | SHOULD |
| H17 | B2-literal versus B2-normalised naming | HIGH | SHOULD |
| H18 | `N_max`, strata and the stability threshold | MEDIUM | delegate after the sweep; threshold is the author's |

---

## 16. Files read, verified, created and not touched; checks run

**Read in full**: `CLAUDE.md`; `docs/context/00_context_index.md`;
`docs/context/10_current_state_post_b2ef.md`; `docs/context/EVIDENCE_TAXONOMY_V1.md`;
`docs/context/PHASE_B_INPUT_CONTRACT.md`;
`docs/plans/B3_CHOICE_EVIDENCE_FACT_SELECTION_ARCHITECTURE_2026-09-18.md`;
`docs/plans/B3_CHOICE_EVIDENCE_FACT_SELECTION_ARCHITECTURE_2026-09-18.summary.json`.
**Read in part**: `docs/context/11_final_benchmark_candidate_policy.md`
(lines 1–80); `docs/context/MCQ_Journal2_B2_B3_Context_Handoff_EN_2026-08-13.md`
(lines 22–40, 620–640, 741–760); `src/mcq_core.py` (lines 625–700);
`src/mcq_generation.py` (lines 108–122, 158–170); `grep` hits only in
`03_journal2_algorithm_spec.md`, `06_evaluation_plan.md`,
`09_claims_and_terminology.md`, `01_project_goal.md`,
`MINIMAL_RESEARCH_CORE_PLAN.md`, `build_bipartite_and_draw_ExtendedVersion.py`,
`all_in_one.py`. The Okuhara sources were not opened.

**Created**: this file; `docs/plans/B3_HUMAN_DECISION_MEMO_2026-09-18.md`;
`docs/plans/B3_HUMAN_DECISION_MEMO_2026-09-18.json`.
**Modified**: nothing. **Not touched, deliberately**: ARCH-1 and its summary
JSON; every frozen module; every v1–v4 output; every test; every context
file; `granularity_clean.py`; the kernel; git state.

**Checks run**: `python -c "json.load(...)"` on the memo JSON; `grep` of the
three new files for the vocabulary the taxonomy forbids (the "do not use"
column of `EVIDENCE_TAXONOMY_V1.md` §9); `git status --short`
and `git diff --stat` to confirm that only the three new files appeared.
No test suite was run: no Python source was created or changed.
