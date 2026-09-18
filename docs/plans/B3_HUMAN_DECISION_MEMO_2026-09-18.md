# B3 human decision memo — the choices only the researcher can make

**Prompt** 8H-B3-ARCH-2 · **Date** 2026-09-18
**Branch** `journal2-b2g-final-benchmark-safety-v4-20260918`
**Basis** `docs/plans/B3_CHOICE_EVIDENCE_ARCHITECTURE_ADVERSARIAL_REVIEW_2026-09-18.md`
("the review"), reviewing `docs/plans/B3_CHOICE_EVIDENCE_FACT_SELECTION_ARCHITECTURE_2026-09-18.md`
("ARCH-1", §21 lists H1–H12).
**Machine-readable companion** `B3_HUMAN_DECISION_MEMO_2026-09-18.json`.
**Status** DECISION MATERIAL. Nothing here is decided. Every row ends with an
empty `RECORDED DECISION` line for the researcher to fill in, date and sign.
Recording the decisions is what turns the review's verdict from
`NOT_READY_FOR_SPEC_FREEZE` into a specification that can be frozen.

---

## How to read this memo

* **Restated decision** — the question in one sentence, independent of how
  ARCH-1 phrased it.
* **ARCH-1 default** — what the first design assumed. It is *not* preserved
  automatically.
* **Evidence from the project** — documents, measured facts or source lines
  that bear on the choice; nothing here is a new measurement.
* **Alternatives and their risks** — every option the reviewer could
  defend, with what each one costs.
* **Recommended candidate** — the reviewer's proposal and the scientific
  reason. A candidate, not a decision.
* **Confidence** — HIGH / MEDIUM / LOW in the recommendation itself.
* **Human approval** — MUST (the researcher must decide; the reviewer has no
  standing), SHOULD (the researcher should confirm; a default exists),
  DELEGABLE (a default can be applied and reported; sign-off afterwards).

H1–H12 are ARCH-1's. H13–H18 were surfaced by the review and are marked NEW.

## Summary table

| id | decision | ARCH-1 default | recommended candidate | confidence | approval |
|---|---|---|---|---|---|
| H1 | `R*` in the pre-answer clues | always | always | HIGH | MUST |
| H2 | grounding vocabulary | separate, never upstream | separate in code, one rule in prose, two added values | HIGH | SHOULD |
| H3 | alternatives before answering | optional-preferred | off; post-answer required; pre-answer as ablation | MEDIUM-HIGH | MUST |
| H4 | `K_A` before / after | 0 / 1 | 0 / ≤ 1 | HIGH / MEDIUM | MUST (post) |
| H5 | `require-verbalizable` upstream | not assumed | yes, versioned, new runner generation; measure cost | MEDIUM | MUST |
| H6 | exact solver | CP-SAT, greedy fallback | HiGHS via scipy, exact-only, re-check; CP-SAT alternative | MEDIUM-HIGH | MUST |
| H7 | budget units | groups pre / nodes post | same; `ENTITY` nodes only; absolute budget | HIGH / LOW | SHOULD |
| H8a | class frame sentence | mandatory | mandatory (required by the form) | HIGH | confirm |
| H8b | `CLASS` graph node | mandatory node in budget | caption, or budget-exempt node | MEDIUM | MUST |
| H9 | rarity | ordering only | late key or annotation only | HIGH | DELEGABLE |
| H10 | letters | seeded permutation | `A` fixed; `B/C/D` kernel order; printed order permuted, balanced | HIGH | MUST |
| H11 | pre-registration | author, before the study | dated, frozen file, re-derived rule | HIGH | MUST |
| H12 | explanation prose | template-only | template-only for the benchmark | HIGH | MUST |
| H13 NEW | objective formulation and key order | weighted sum | constraints + lexicographic, `ε = 0`; order of review §5.3 | HIGH / MEDIUM | MUST |
| H14 NEW | pre-answer admissibility rule | `abs_g` penalty | hard grounding-clean rule; yield measured first | MEDIUM | MUST |
| H15 NEW | non-exhaustivity instruction | none | one sentence in the protocol | MEDIUM | MUST |
| H16 NEW | `ABSENCE_ONLY` after answering | penalty + legend | admissible, ordered against, counted, legend | MEDIUM | SHOULD |
| H17 NEW | legacy baseline naming | "legacy heuristic, offline" | B2-literal versus B2-normalised (+ B2-structural) | HIGH | SHOULD |
| H18 NEW | `N_max`, strata, stability threshold | 200, pre-key | stratified; threshold after the sweep | MEDIUM | DELEGABLE |

---

## H1 — Is `R*` always exposed in the pre-answer clue set?

**Restated decision.** Must every item be answerable from its own clues,
which requires exposing every fact of the frozen rationale `R*` before the
participant answers, or may some items rely on outside knowledge that the
clues do not state?

**ARCH-1 default.** Always exposed, "mandatory even when Answer-only" (§4).

**Evidence from the project.** The required form ends with an `A`-only
identifying clue ("A is known for induced pluripotent stem cells. Who is
A?"), and the handoff says the format "intentionally allows a final A-only
identifying clue" (§20) and "the rationale/final clue may be A-only by
design" (§26). `R*` is a minimum-cardinality cover, so every fact in it is
the only cover of some distractor; dropping any fact leaves a distractor
undistinguished under `K`.

**Alternatives and their risks.** *Expose only part of `R*`*: some distractor
is then not distinguished by the clues, so the item's uniqueness rests on
knowledge the item does not state and the kernel's guarantee no longer
applies to what the learner sees. *Rely on outside knowledge for some items*:
the item's correctness becomes unverifiable against `K`, which is the
paper's only ground truth.

**Recommended candidate.** Always exposed, with the presentation policy
P1–P6 of the review §4.3 (Answer-attribute phrasing, no exclusivity marker,
full support listed, per-distractor explanation restricted to `≥ L1` facts,
`rationale_absence_incidences` reported). This is less a preference than a
consequence of the form; it is listed because it fixes the semantics of
every item.

**Confidence.** HIGH. **Human approval.** MUST.

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H2 — One observation rule, two vocabularies?

**Restated decision.** Should the stage keep a separate `grounding`
vocabulary for distractor-owned facts (never written into `levels`, never
fed to the kernel), and how should the paper describe the relation between
grounding and the frozen evidence levels?

**ARCH-1 default.** Separate vocabulary (`SHARED` / `ALTERNATIVE_OBSERVED` /
`ABSENCE_ONLY`), never upstream; the paper wording left open.

**Evidence from the project.** The taxonomy defines levels as properties of
an ordered `(Answer fact, candidate)` pair and forbids any downstream stage
from creating or rescuing a level. The frozen `NOT_COVERED` test has three
clauses (exact, canonical equivalence, containment); ARCH-1's grounding
formula has one. The taxonomy §5 requires an `UNRESOLVED` state when the
semantic index is unavailable.

**Alternatives and their risks.** *One vocabulary (write grounding as
levels)*: a reviewer reads a distractor-owned "L1" as a kernel-level claim,
and the protected boundary between the kernel's inputs and the presentation
stage blurs. *Separate vocabulary but the one-clause rule*: containment cases
are misclassified as observed alternatives and the pre-answer clue then
implicates a contrast that `K` contradicts (review §4.4).

**Recommended candidate.** Separate names in code, with the three frozen
tests and two added values (`SHARED_BY_CONTAINMENT`,
`UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE`) plus a granularity-risk annotation
on every group. In the paper: **one observation rule** (support / observed
alternative / absence, read through the same semantic index), applied in two
roles — as evidence levels on Answer facts, which drive coverage, and as
grounding on any exposed clue, which drives presentation safety and nothing
upstream. The author owns the sentence.

**Confidence.** HIGH. **Human approval.** SHOULD (the paper wording).

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H3 — Are the distractors' observed alternative values shown before answering?

**Restated decision.** Should `RATIONALE_ALTERNATIVE` groups (for each
distractor, its observed alternative value under a rationale key) appear in
the pre-answer clue set, or only in the post-answer explanation graph?

**ARCH-1 default.** "Optional, preferred" before; required after.

**Evidence from the project.** The professor's stated purpose for the graph
is that participants understand the answer *after* responding (handoff §2).
The alternatives are exactly the per-distractor explanation ("B is not A
because B's recorded birthplace is Osaka"). They are singleton,
distractor-owned groups, which ARCH-1's own objective penalises (`n_g = 1`,
`s_g = 1`), contradicting "preferred". The taxonomy's multi-valued caveat
means stating an alternative does not remove the exclusivity reading for
keys such as `almaMater`.

**Alternatives and their risks.** *Show before answering*: the item becomes
a matching puzzle over four singleton facts; a learner can find `A` by
knowing any three names' values, so the item measures something other than
knowledge of the rationale; the discriminating key is exposed four times.
*Show only after answering*: the pre-answer clue "A was born in Kyoto"
carries the exhaustivity implicature against the distractors; it is backed
at `≥ L1` for each of them by some `R*` fact (review §4.3), and the
implicature is cancelled after answering by the explanation. *Show before
answering as an ablation arm only*: measures the effect without making it
the method.

**Recommended candidate.** Post-answer required (`COVER_ALT`), pre-answer
off by default, "alternatives before answering" a declared ablation arm.

**Confidence.** MEDIUM-HIGH. **Human approval.** MUST (a pedagogical
decision about what the item tests).

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H4 — How many optional Answer-only groups may appear?

**Restated decision.** The cap `K_A` on optional (non-`R*`) groups whose
support is `{A}` alone, before and after answering.

**ARCH-1 default.** 0 before, 1 after.

**Evidence from the project.** Handoff §20 and §26: "avoid additional A-only
supplementary facts; the explicit final rationale may be A-only." Under the
required form an optional Answer-only clue is not a leak of the name; it is
an additional discriminating fact that gives the learner a second route to
`A` and makes the item test something other than `R*` (review §4.5).

**Alternatives and their risks.** *`K_A > 0` before answering*: the item's
discriminating content is no longer exactly `R*`, so the human study cannot
attribute answerability to the rationale. *`K_A = 0` after answering*: the
cleanest explanation graph ("`R*` + alternatives + shared context"), at the
cost of one enriching fact about `A`. *`K_A = 1` after*: one extra fact about
`A` for context, harmless once the answer is known.

**Recommended candidate.** 0 before answering (the author's own prior
guidance); at most 1 after answering, with 0 as an acceptable stricter
choice.

**Confidence.** HIGH for the pre-answer value; MEDIUM for the post-answer
value. **Human approval.** MUST for the post-answer value.

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H5 — Should a `require-verbalizable` policy exist upstream?

**Restated decision.** How to resolve, for the publication run, the
documented contradiction that an unverbalizable fact is "barred from the main
corpus" by the contract but is only ordering key 9 in the kernel, so that a
selected `main-l1` rationale can contain a fact without a template.

**ARCH-1 default.** Not assumed; flagged per item as
`CE_RATIONALE_NOT_VERBALIZABLE` (graph produced, clue text blocked).

**Evidence from the project.** `10_current_state_post_b2ef.md` §7.1 records
the contradiction; ARCH-1 §20 names Muhammad's selected rationale as a case.
The v4 runner already has the precedent of a versioned, additive policy that
selects among minimum-cardinality covers without weakening a level
(`require-clean`, `11_final_benchmark_candidate_policy.md` §1.2, which
changed three of eleven regression selections and made none unusable).

**Alternatives and their risks.** *(i) A versioned `require-verbalizable`
policy upstream*, in a new runner generation, choosing among
minimum-cardinality covers those whose facts all have templates, else
marking the item not learner-facing: restores the contract's promise; costs
yield that is unmeasured; must never grow `|R*|` or weaken a level (the
`require-clean` discipline). *(ii) Expand the template registry* for the
predicates that occur in selected rationales: reduces the problem at the
data level; a policy is still needed for what remains. *(iii) Leave the
flag and exclude affected items from the clue-bearing benchmark*: honest but
the contract text must then be corrected, and the exclusion is a yield loss
reported after the fact rather than a policy chosen before. *(iv) Verbalise
without a template*: forbidden (`03_journal2_algorithm_spec.md` §12: the
verbalizer must not invent).

**Recommended candidate.** (i) plus (ii): a versioned policy, additive, in a
new runner generation (never a changed default in v4), with its cost measured
on the development batches and reported next to the `require-clean` cost;
template coverage expanded first so the policy bites rarely.

**Confidence.** MEDIUM (the cost is unmeasured). **Human approval.** MUST
(it is part of the publication configuration, CLAUDE.md work-order step 1).

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H6 — Which exact solver, and what happens when it does not certify?

**Restated decision.** The exact 0-1 solver dependency, and the policy for
an item whose solve returns no optimality certificate.

**ARCH-1 default.** CP-SAT (OR-Tools) or CBC via PuLP; on
unavailability or timeout, greedy, published with a flag.

**Evidence from the project.** `scipy 1.17.1` with `scipy.optimize.milp`
(HiGHS) is installed in `mcq-journal2`; `ortools`, `pulp`, `mip` and
`highspy` are not (checked 2026-09-18). `MINIMAL_RESEARCH_CORE_PLAN.md`
makes author comprehensibility and few dependencies the scientific
priority. The kernel never substitutes a heuristic for its exact set cover;
it declares scope instead.

**Alternatives and their risks.** *HiGHS via scipy*: no new dependency;
floating-point solver, so set the gap to zero and re-check every selection in
pure Python; matrix-form API. *CP-SAT*: integer-exact certificate, readable
model, a large new binary dependency. *CBC via PuLP*: a small new dependency,
floating point. *Pure-Python branch-and-bound as production solver*: a
second exact solver to prove correct with the same worst case as enumeration;
right as the small-instance oracle only. *Greedy fallback in publication*:
mixes a baseline into the method arm, makes the item set machine-dependent,
hides a bounding defect (review §6.3).

**Recommended candidate.** HiGHS via `scipy.optimize.milp`, single thread,
`mip_rel_gap = 0`, scipy version pinned; pure-Python re-check of every
constraint and of the lexicographic key vector for every published
selection; exhaustive oracle on small instances. Publication mode requires a
certificate for every solve of every published item; otherwise
`CE_SOLVER_NOT_OPTIMAL`, item not published, count in the manifest, non-zero
exit. Greedy is baseline B3 only. CP-SAT is the alternative if the author
prefers an integer-exact proof and accepts the dependency.

**Confidence.** MEDIUM-HIGH. **Human approval.** MUST (dependency policy and
the publication rule).

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H7 — Budget units, and absolute versus relative budgets

**Restated decision.** Whether the pre-answer budget is counted in clue
groups (sentences) and the post-answer budget in right nodes; and whether
the post-answer budget is absolute or relative to the mandatory core.

**ARCH-1 default.** Groups before, nodes after; absolute.

**Evidence from the project.** A group is one sentence, so groups are the
reading-load unit; a node is the visual unit of the drawing. `|R*|` varies
across items (up to `ρ = 3` facts), so under an absolute node budget items
with a larger rationale get less optional context. Handoff §26: "avoid
excessive right-side nodes".

**Alternatives and their risks.** *Nodes for both*: a sentence can name one
node and several letters, so node counts under-measure reading load.
*Relative budget ("mandatory core + k optional nodes")*: uniform context,
non-uniform graph size, which complicates the human study's comparability.
*Absolute budget*: uniform graph size, variable context; the mandatory share
must then be reported per item.

**Recommended candidate.** Groups before, `ENTITY` nodes after (the class
node exempt, H8b), absolute post-answer budget with the mandatory share
reported per item and per cohort; revisit only if the sweep shows many
`CE_SELECTED_MANDATORY_ONLY` items.

**Confidence.** HIGH for the units; LOW for absolute-versus-relative.
**Human approval.** SHOULD.

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H8a — Must the pre-answer question state the shared class?

**Restated decision.** Whether the frame sentence "A, B, C and D are all
<class>" is mandatory in every item.

**ARCH-1 default.** Mandatory, provenance-labelled (folded into H8).

**Evidence from the project.** The required form opens with it; the
candidate pool was drawn from that class; the sentence has support 4 and
discriminates nothing. Its provenance is remote category membership at
retrieval time (`PHASE_B_INPUT_CONTRACT.md` §6.1), which the paper states
once. A class label with a recorded `soft_overlap` against the Answer label
is a class-leak matter of the v6 selector and the publication policy, not of
B3.

**Alternatives and their risks.** *Omit it*: the item no longer has the
required form and the learner loses the only non-discriminating anchor.

**Recommended candidate.** Mandatory. **Confidence.** HIGH.
**Human approval.** Confirm (it follows from the form).

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H8b — Must the post-answer graph contain a `CLASS` right node?

**Restated decision.** Whether the class appears in the bipartite graph as a
right-side node with four "is a" edges, consuming one right-node budget
slot, or as a caption outside the budget.

**ARCH-1 default.** A mandatory `CLASS` node inside the budget.

**Evidence from the project.** The author's original drawing had the node
(ARCH-1 §18). It is constant (support 4), explains nothing about why `A` is
the answer, is the only node whose provenance is not the pinned snapshot
(ARCH-1 threat 2), and takes one of at most ten slots. The professor's
requirement for the graph names only the four left nodes.

**Alternatives and their risks.** *Node inside the budget*: 10–25 % of the
explanation budget spent on a constant; two provenances in one picture;
comparability with baselines depends on whether they draw it. *Node,
budget-exempt, provenance-marked*: keeps the author's picture; the budget
sweep counts `ENTITY` nodes only. *Caption with a provenance line*: cleanest
separation of sources; the graph shows only pinned-snapshot evidence; the
frame is still stated because the participant has read it.

**Recommended candidate.** Caption, budget-exempt; if the author wants the
node, budget-exempt and provenance-marked. In both cases `B_post` counts
`ENTITY` nodes only.

**Confidence.** MEDIUM. **Human approval.** MUST (it is the author's
graph design).

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H9 — What role does offline rarity play?

**Restated decision.** Whether the pinned-KG rarity of a counterpart under
its key (`rare_g`) is an ordering annotation only, a late lexicographic key,
or a utility term as in the legacy design.

**ARCH-1 default.** Ordering annotation only.

**Evidence from the project.** The legacy code chose the "unique" fact by
live-SPARQL rarity (`1/popularity`), cached failures as `999999`, and used
it as a difficulty proxy. CLAUDE.md §12 and the current-state file forbid
reading structural quantities as human difficulty. Nothing in the project
validates rarity against any human measure.

**Alternatives and their risks.** *Utility term or early key*: rarity then
shapes which context is shown on the strength of an unvalidated difficulty
proxy, and the paper cannot defend the weight. *Late key or annotation*:
breaks ties among otherwise equal selections and is recorded for the failure
analysis; makes no claim.

**Recommended candidate.** A late lexicographic key at most (after tier and
tokens), or an annotation only; reported, never described as difficulty.

**Confidence.** HIGH. **Human approval.** DELEGABLE with sign-off.

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H10 — Letter semantics and the printed option order

**Restated decision.** Whether `A` is fixed as the Answer letter and `B/C/D`
as the distractor letters (in what order), and how the printed order of the
four names is chosen and recorded.

**ARCH-1 default.** A seeded per-item permutation of the letters; "the
Answer is never at a fixed letter"; the record carries `answer_letter`.

**Evidence from the project.** The professor-required form (handoff §2)
asks "Who is A?" and defines the graph's left side as "A/B/C/D (Answer +
three distractors)". The legacy code fixed `A = answer` deliberately
(`src/mcq_generation.py` lines 111–118: "random shuffle hay fix? Ở đây fix").
`06_evaluation_plan.md` asks for "randomized option order" and "permutation
robustness", both about the printed options. The kernel's coverage masks are
in position order, which handoff §26 wants to reuse as the graph's 4-bit
incidence masks. The review §3 could demonstrate no learner-visible leak from
a fixed `A`, and identifies the printed option order as the only positional
leak (the legacy list order put the Answer first).

**Alternatives and their risks.** *Permute the letters* (ARCH-1): items no
longer have the required form ("Who is C?"), the masks must be re-mapped per
item, the record schema cannot express the form, and nothing is gained
because letters are not options. *Fix `A`, randomise `B/C/D`*: no learner
benefit (the letters are anonymous), loses mask alignment. *Fix all letters,
permute the printed names per item with a seed*: correct; position bias
across the benchmark is then left to chance. *Fix all letters, permute the
printed names with benchmark-level balancing* (Latin square or block
balance so the Answer sits in each printed position in about a quarter of
items), recorded seed and scheme: correct and standard for MCQ studies.

**Recommended candidate.** `A` = Answer; `B/C/D` = distractors in kernel
position order; printed option order an independent, seeded,
benchmark-balanced permutation, recorded on the item (`option_order`,
`answer_printed_position`, scheme, seed) and reused unchanged for the
post-answer display. Withdraw the "positional leak" rows of ARCH-1 §18 and
the summary JSON.

**Confidence.** HIGH. **Human approval.** MUST — it confirms the item form
the professor requires and fixes the record schema.

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H11 — What counts as pre-registration, and who signs?

**Restated decision.** Whether the development-batch sweep and the knee rule
of ARCH-1 §16 constitute pre-registration for the paper, in what form, and
who freezes the budgets, weights or keys, `N_max` and solver before human
data are collected.

**ARCH-1 default.** The author, before the human study; the rule as
written in §16.

**Evidence from the project.** ARCH-1 §16 step 4 permits one adjustment
after a small development-only pilot "recorded". The rule's own criteria
("≥ 90 % of items have every letter in at least one optional clue") depend on
H3, H13 and H14, which are still open, so the rule cannot be frozen in its
current wording (review F-15). `08_data_and_reproducibility.md` governs run
manifests and hashes.

**Alternatives and their risks.** *Internal, dated, hashed pre-registration
file in the repository*: defensible to a reviewer as a frozen protocol; not
a public registry. *Public pre-registration (e.g. OSF)*: stronger, more
process cost; a human call. *No written pre-registration, only the manifest*:
the sweep then looks like tuning, which ARCH-1 itself names as its weakest
point.

**Recommended candidate.** A dated file under `docs/` containing the
re-derived choice rule, its thresholds, the frozen budgets, the objective
key order (or weights), `N_max` and strata, the solver and its version, the
development-batch identifiers used, and the statement that the human test
set was never read; committed (by the author, on request) before any human
data; a single recorded adjustment after the development-only pilot is
allowed if it is dated and explained. Whether to register publicly is the
author's.

**Confidence.** HIGH on the process; the thresholds are the author's.
**Human approval.** MUST.

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H12 — Post-answer explanation prose: template-only or LLM-polished?

**Restated decision.** Whether the explanation shown after answering is
produced by templates only, or by an LLM polishing pass under grounding
constraints.

**ARCH-1 default.** Template-only in the first version.

**Evidence from the project.** `03_journal2_algorithm_spec.md` §12: the
verbalizer receives grounded records and must not invent facts. The paper's
claim is grounded, reproducible rationales; every exposed sentence must map
to an observed triple or the class membership. The review §4.3 policy P2
fixes the explanation basis per distractor.

**Alternatives and their risks.** *Template-only*: stilted prose, fully
reproducible, every sentence traceable, no new dependency, no model version
to pin. *LLM-polished*: fluent; introduces a non-deterministic component,
a model version, and a grounding check that must itself be validated; a
polishing model can add an implicature ("unlike the others") that the
policy forbids; the human study then measures the polish as much as the
method.

**Recommended candidate.** Template-only for the benchmark and the human
study; LLM polishing, if ever, as a separate, later arm with its own
grounding audit and human comparison.

**Confidence.** HIGH. **Human approval.** MUST (it shapes the human-study
materials).

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H13 (NEW) — Objective formulation and key order

**Restated decision.** Whether the selection objective is an integer
weighted sum (ARCH-1 §6.3) or hard constraints plus an ordered list of keys
solved lexicographically, and, if the latter, in what order.

**ARCH-1 default.** Weighted sum, thirteen named weights, candidate vector
`ce_weights/1.0.0-candidate`, two weights swept.

**Evidence from the project.** The kernel's fourteen-field rationale key and
six-key combination objective are lexicographic tuples ("smallest tuple
wins", `src/mcq_core.py` lines 686–700); the rationale objective versions
v1/v2/v3 differ only in key placement, and that placement measurably changed
Augustus' rationale — the project's existing model of "sensitivity analysis"
is the key swap. `03_journal2_algorithm_spec.md` §11 states a lexicographic
implementation is acceptable. Under ARCH-1's own candidate weights a
support-3 group with one absence-grounded letter (`8 − 3 = 5`) outranks a
clean support-2 group (`4`), so a weight decides an open-world question
(review §4.2). ARCH-1 §9.1 names weight tuning as its weakest point.

**Alternatives and their risks.** *Weighted sum*: one solve; graded
trade-offs; 13–15 numbers to defend; a full sensitivity study is infeasible;
safety can be outbid. *Lexicographic, `ε = 0`*: zero numbers, one order;
every chosen set is explained by a sequence of sentences; consistent with
the kernel; never trades a higher key for a lower one, which the author must
accept. *ε-constraint*: lexicographic with one tolerance per level, each in
its own unit; parameters return only where the author opens one. *Hybrid
(weights for polish only)*: the kernel already uses keys for tier, label
length and token count, so the polish tier does not need weights.

**Recommended candidate.** Constraints + ε-lexicographic with every
`ε_i = 0` by default and the canonical order last, recorded as a versioned
objective with an adjacent-swap ablation set. Candidate orders (review
§5.3): before answering — balance, shared information, key diversity,
fewer sentences, tier, tokens, canonical; after answering — fewer
`ABSENCE_ONLY` incidences, fewer risk-bearing groups, shared information,
key diversity, fewer nodes, tier, tokens, canonical. The author may reorder
and may open one `ε_i`.

**Confidence.** HIGH on the formulation; MEDIUM on the exact order.
**Human approval.** MUST (both the acceptance of strict priority and the
order).

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H14 (NEW) — The pre-answer admissibility rule

**Restated decision.** Which optional clue groups are admissible before
answering: whether a group with an `ABSENCE_ONLY`, `SHARED_BY_CONTAINMENT`,
`UNRESOLVED` or granularity-risk-bearing non-support letter is excluded by
rule (a constraint) or merely ordered against (a weight or key), and which
discrimination patterns (support sets) are allowed.

**ARCH-1 default.** `W_abs` penalty; `W_risk` penalty on Answer groups
only; singletons penalised; Answer-only capped at 0.

**Evidence from the project.** Taxonomy §2: `L0` "must not appear in a
rationale presented as justification" and "is not evidence a student may be
shown as a reason"; §7: absence is never falsity. A pre-answer clue that
lists three letters invites the inference that the fourth lacks the
property; when that letter's grounding is absence, the inference rests on
nothing (review §4.1–4.2). The professor's own illustrative item contains a
clue of that shape ("B, C, and D were born in Japan" while `A` was born in
Japan). Handoff §20/§26: supplementary facts should have degree ≥ 2. Pilot
counts: 8,485 `L0` versus 6,062 `L1` incidences over all candidate pairs, so
the yield cost of a hard rule may be large but is unmeasured for the three
selected distractors.

**Alternatives and their risks.** *Penalty only (ARCH-1)*: absence-grounded
clues are selected routinely; a reviewer who finds one has found the paper's
open-world claim contradicted by its own items. *Hard rule (grounding-clean:
every non-support letter `ALTERNATIVE_OBSERVED` with risk `NONE`)*: no
exposed pre-answer contrast rests on absence or on a containment mismatch;
possibly many items with mandatory-only clue sets; the cost must be measured.
*Hard rule plus the non-exhaustivity instruction (H15)*: the cleanest
combination. *Restricting discrimination patterns further* (for instance,
forbidding support-3 groups that exclude `A`, which read as "A lacks X"):
stricter; reduces elimination routes; a pedagogical choice.

**Recommended candidate.** The hard rule of review C3 (support ≥ 2;
grounding-clean; verbalizable; no Answer-label or distractor-label leak;
`K_A = 0`), adopted **after** the yield cost is measured on the development
batches and reported next to the penalty-only arm; the penalty-only arm kept
as an ablation. Whether to forbid `A`-excluding support-3 groups is the
author's.

**Confidence.** MEDIUM (the cost is unmeasured). **Human approval.** MUST
(a yield-versus-safety trade-off).

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H15 (NEW) — A non-exhaustivity instruction in the participant protocol

**Restated decision.** Whether the pre-answer instructions tell participants
that a clue lists the letters for which the knowledge source records the
fact, and that an unlisted letter may also have the property.

**ARCH-1 default.** None before answering; a legend after answering.

**Evidence from the project.** Exhaustivity is a cancellable implicature;
the instruction cancels it explicitly. The taxonomy's open-world discipline
is the paper's headline. `06_evaluation_plan.md` §7 lists
"explicit instruction not to infer that DBpedia is complete" among the human
evaluation materials, so the project already intends a related instruction
for raters.

**Alternatives and their risks.** *No instruction*: participants use
elimination from non-mention, which is what the admissibility rule (H14)
makes safe only for observed alternatives. *Instruction*: honest; weakens
elimination and may lower accuracy; participants do not reliably apply such
instructions, so it complements H14 rather than replacing it. *Instruction
plus a legend after answering*: consistent across both exposures.

**Recommended candidate.** One sentence in the pre-answer instructions and
the legend after answering, both in the frozen protocol, with the human
study measuring whether participants drew absence inferences (ARCH-1 §19.1
already asks for this).

**Confidence.** MEDIUM. **Human approval.** MUST (protocol design).

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H16 (NEW) — `ABSENCE_ONLY` groups in the post-answer graph

**Restated decision.** Whether a shared group with an absence-grounded
letter may be drawn after answering.

**ARCH-1 default.** Admissible with a penalty and the legend.

**Evidence from the project.** After answering no misdirection can occur;
the graph's purpose is explanation and shared structure serves it; the
legend states what a missing edge means. Banning them removes context and
does not change what the paper may claim, because nothing negative is drawn
either way.

**Alternatives and their risks.** *Admissible, ordered against (an early
post-answer key), counted, legend*: richer graphs; the residual inference is
measured. *Banned in both exposures*: the strictest reading of the
taxonomy; thinner graphs; the simplest sentence in the paper.

**Recommended candidate.** Admissible after answering, first post-answer
key "fewer exposed `ABSENCE_ONLY` incidences", counted per item and cohort,
legend mandatory.

**Confidence.** MEDIUM. **Human approval.** SHOULD.

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H17 (NEW) — How the legacy baseline is named and run

**Restated decision.** Whether the offline, safety-normalised
reimplementation of the author's heuristic may be called the legacy
baseline, and which variants are run.

**ARCH-1 default.** "Legacy heuristic, offline reimplementation" with
unsafe steps replaced.

**Evidence from the project.** ARCH-1 §18 lists eight replacements. One of
them (fixed `A = Answer`) was not a defect (H10). The historical code depends
on live SPARQL, caches failures as `999999`, and picks from sets
non-deterministically, so it cannot be re-run reproducibly.

**Alternatives and their risks.** *One object called "legacy"*: a reviewer
assumes the historical method was evaluated; it was not. *Two named objects*
— B2-literal (historical; reported as not reproducible; any kept outputs
shown qualitatively) and B2-normalised (offline; replacement table; the
fixed-`A` row withdrawn) — with an optional B2-structural variant that keeps
absence-as-contrast for structural counting only, never shown to humans.

**Recommended candidate.** The two named objects, with B2-structural if the
author wants the "how often would the old logic have exposed an `L0` pair as
contrast" number.

**Confidence.** HIGH. **Human approval.** SHOULD.

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## H18 (NEW) — Universe bounding: strata, `N_max` and the stability threshold

**Restated decision.** How the optional tier is bounded, which strata are
always kept, and what share of bounded items must be stable at a doubled
`N_max` for the value to be frozen.

**ARCH-1 default.** `N_max = 200` by a modular pre-key; a sensitivity arm
"until the selection stops changing".

**Evidence from the project.** Kingdom of Italy's one-hop neighbourhood has
3,026 nodes; places and polities are IN-heavy. The pre-key is blind to node
sharing, key diversity and letter balance (review §9.2). Bounding touches
optional context only; answerability and grounding are unaffected.

**Alternatives and their risks.** *Pre-key only*: interaction-driven
context can be cut. *Stratified bounding* (node-sharing, per-key, per-letter
strata, then the pre-key): protects the interaction terms at a small cost in
universe size. *No bounding*: exact over the full universe but solve times on
polities become unbounded in principle.

**Recommended candidate.** Stratified bounding; stability-at-doubling
measured on the development batches; the smallest `N_max` at which at least
a declared share of bounded items (99 % is the natural candidate) is stable;
per-cohort reporting; the "bounding never affects answerability or
grounding" sentence in the paper.

**Confidence.** MEDIUM. **Human approval.** DELEGABLE after the sweep; the
threshold is the author's number.

`RECORDED DECISION: ____________________  DATE: __________  SIGNED: __________`

---

## Dependencies between decisions

* H10 fixes the record schema and must be recorded first; C1 of the review
  depends on nothing else.
* H13 (formulation) and H14 (admissibility) together define the pre-answer
  solve; H3 and H4 set two of its hard constraints; H16 sets a post-answer
  key. The §16 choice rule (H11) can only be re-derived after these five.
* H5 belongs to the publication configuration (CLAUDE.md step 1) and gates
  which items have clue text; B3 development does not wait for it.
* H6 is independent of the rest and can be recorded at once.
* H8b and H7 interact only through what `B_post` counts.
* H18 is measured after H13/H14 are fixed, because stability is defined on
  the selected sets.

## Closing note on the work order

CLAUDE.md orders the remaining work as: record the configuration (step 1);
run the publication benchmark (step 2); verbalization and the choice–evidence
graph (step 3); human evaluation (step 4). B3 implementation against the
development batches produces no publication output and is additive, but the
decision to build it before step 2 is the researcher's and should be
recorded here:

`B3 MAY BE IMPLEMENTED BEFORE THE FINAL BENCHMARK RUN: YES / NO   DATE: __________  SIGNED: __________`

## Files

**Created**: this memo and `B3_HUMAN_DECISION_MEMO_2026-09-18.json`.
**Modified**: nothing. ARCH-1, its summary JSON, every frozen module, every
v1–v4 output and every context file are untouched; no git operation was
performed.
