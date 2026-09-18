# B3 — Fact selection and the choice–evidence bipartite graph: architecture

**Prompt** 8H-B3-ARCH-1 · **Date** 2026-09-18
**Branch** `journal2-b2g-final-benchmark-safety-v4-20260918`
**Status** ARCHITECTURE / DESIGN ONLY. No production code, no change to any
frozen module, no change to any v1/v2/v3/v4 output. Nothing here is a
publication-final decision; §21 lists the decisions a human must record.
**Terminology authority** `docs/context/EVIDENCE_TAXONOMY_V1.md`;
`docs/context/PHASE_B_INPUT_CONTRACT.md` for what a v4 record contains.
**Companion** `B3_CHOICE_EVIDENCE_FACT_SELECTION_ARCHITECTURE_2026-09-18.summary.json`
(machine-readable digest of this document).

---

## 0. What this document decides, and what it refuses to decide

The v4 runner ends at a frozen Phase-B selection: an Answer `A`, three
distractors `D = {d1, d2, d3}` chosen by the exact six-key objective over the
frozen LRoleSim ranking, and an exact minimum-cardinality rationale `R*` under
the `main-l1` (or, diagnostically, `diagnostic-l0`) evidence policy. The next
stage must turn that into

1. a compact **pre-answer clue set** the participant reads before answering;
2. a **post-answer choice–evidence bipartite graph** the participant sees after
   answering, with `A/B/C/D` on the left and counterpart nodes on the right;
3. a machine-readable record that says which observed facts were exposed, why,
   under which budget, and with what provenance.

This document designs that stage. It fixes the graph data model, the candidate
fact universe, the objective and constraints, compares five algorithm
families, recommends one, and specifies the interfaces, statuses, metrics,
budget-sensitivity study, baselines and threats. It does **not** choose the
final budget, the final weights, or the publication configuration of v4 —
those are human decisions and the report says so where they arise.

**Boundaries that every sentence below respects.**

* Evidence levels (`NOT_COVERED`, `L0`, `L1`, `L2`) are decided upstream by the
  frozen classifier and are read here as opaque attributes of an ordered
  `(Answer fact, candidate)` pair. Nothing in this stage may create, upgrade,
  downgrade or rescue a level. `SCOPED_EMPIRICAL` is an annotation on L1.
* `L0` is snapshot absence and is never a learner-facing reason. A missing
  triple is never drawn, verbalized or implied as a false fact.
* `IN` and `OUT` are two relation identities. They never merge, never share a
  right-node edge, never share a clue.
* LRoleSim is consumed only as the frozen ranks/scores already on the record.
  No score is recomputed, and nothing this stage decides feeds back into the
  ranking, the pool, the set cover or the objective that chose `D` and `R*`.
* `R*` is produced by the existing set-cover stage and is consumed as given.
  This stage may add context around `R*`; it may not replace it.
* The LRoleSim matching bipartite graph (Hungarian matching inside RoleSim)
  and the **choice–evidence bipartite graph** designed here are different
  objects with different names.
* `direct_identifier = True` means only local structural specificity within
  the candidate pool. It is never read as "easy for a human".

---

## 1. Position in the pipeline — current-stage data flow

```
 ┌──────────────── Phase B v4 (frozen, existing) ────────────────────────────┐
 │ identity → v6 class ranking → local-mapping walk → candidate screen       │
 │ → M1 graph (declared budget) → frozen LRoleSim ranks/scores               │
 │ → semantic index rebuild → B1.2 Answer facts + R1 quality                 │
 │ → B1.3 per-(fact, candidate) levels → mcq_core.build_case()               │
 │ → mcq_core.select_distractors()  ⇒ Selection(D, R*, masks, keys)          │
 │ → selection.granularity_clean.apply_granularity_policy() ⇒ outcome        │
 │ → canonical_record + phase_b1_provenance  (audit_record)                  │
 └──────────────────────────────┬────────────────────────────────────────────┘
                                │  consumed READ-ONLY (§12.1)
                                ▼
 ┌──────────────── B3 stage (NEW, this design) ──────────────────────────────┐
 │ (1) gate: learner-facing main-corpus item only                            │
 │ (2) universe: one-hop observed facts of A, d1, d2, d3 from the pinned KG  │
 │     + R1 quality per fact + grounding annotations + hard screens          │
 │ (3) grouping: fact edges → (κ, o) clue groups → right nodes               │
 │ (4) tiering: MANDATORY_RATIONALE / RATIONALE_ALTERNATIVE /                │
 │              OPTIONAL_CONTEXT / EXCLUDED(reason)                          │
 │ (5) pre-answer selection  (budget B_pre, exact 0-1 ILP)                   │
 │ (6) post-answer selection (budget B_post, nested ⊇ pre, exact 0-1 ILP)    │
 │ (7) records: clue plan, graph, provenance, objective components, status   │
 └──────────────────────────────┬────────────────────────────────────────────┘
                                ▼
        verbalization (templates; later)      graph rendering (post-answer; later)
```

The stage reads the pinned KG **offline** for the distractors' own observed
facts. It performs no network access, recomputes no LRoleSim score, re-runs no
evidence classification for the pairs the kernel used, and writes nothing into
any v4 artefact directory. It is a new versioned package (§12).

---

## 2. Presentation protocol and the two exposures

The participant sees, before answering, prose such as

> A, B, C, and D are all Japanese Nobel laureates. A, B, and C worked at Kyoto
> University. B, C, and D were born in Japan. C and D graduated from Kyoto
> University. A is known for induced pluripotent stem cells. Who is A?

with the four names as options, and only **after** answering the bipartite
graph and a fuller explanation of why `A` is the Answer.

Two consequences shape everything else.

**(a) Letters, not names, are the left side of the pre-answer item.** The
participant must map the letter `A` onto one of four printed names. Every clue
about *any* letter therefore helps by elimination, and "Answer leakage" here
means *a clue that lets the participant place `A` without using the intended
rationale* — not merely "the Answer string appears in the stem". The letter
assignment must be a recorded permutation with a seed, never `A = Answer` as
the legacy code did (§18).

**(b) Two exposures with different purposes and different budgets.** The clue
set exists to make the item answerable from the rationale while staying
non-trivial; the graph exists to explain. Nothing forces their budgets to be
equal, and §11 argues they should not be. What they must share is a single
candidate universe, a single scoring model and a nesting guarantee, so the
graph can never contradict the clues.

---

## 3. Graph data model — the formal representation

### 3.1 Sets

Let `C = {c_0, c_1, c_2, c_3}` be the four choices, `c_0 = A` the Answer and
`c_1..c_3 = D` in the kernel's position order (bit order of every coverage
mask on the v4 record). Let `K` be the pinned snapshot.

An **observed fact edge** is

```
f = (c, κ, o)        with κ = (p, dir), dir ∈ {OUT, IN}
```

meaning: in `K`, `(c, p, o)` is observed when `dir = OUT`, and `(o, p, c)` is
observed when `dir = IN`. `o` is the **counterpart** (object of an OUT fact,
subject of an IN fact — never called "object" unconditionally, AUDIT EX-12).

The **choice–evidence bipartite graph** is

```
G = (C ∪ O, E)
  O  = set of right nodes = { node(o) : some selected f has counterpart o }
  E  = set of selected fact edges f = (c, κ, o), one edge per (c, κ, o)
```

Each edge carries: `predicate_uri`, `direction`, `source_choice`,
`counterpart_uri`, `display_label`, `template_id`, `verbalizable`,
`pedagogical_tier`, `eligible`, `tier` (§5.3), `grounding` (§3.6),
`provenance` (pinned KG sha256 + fact schema version), and for Answer edges the
frozen per-distractor evidence levels copied from the v4 record.

### 3.2 A fact is not a right node

```
A --workedAt(OUT)-->      Kyoto_University
B --workedAt(OUT)-->      Kyoto_University
C --graduatedFrom(OUT)--> Kyoto_University
```

is **one** right node and **three** fact edges under **two** predicate-direction
keys. Three quantities are therefore distinct and all three are needed:

| symbol | meaning | why it matters |
|---|---|---|
| `f` | fact edge `(c, κ, o)` | the unit of observation and of provenance |
| `g = (κ, o)` | **clue group**: all edges with the same key and counterpart | the unit of one clue sentence ("A, B and C worked at Kyoto University") |
| `o` | right node | the unit of graph size and of the right-side budget |

`support(g) = { c : (c, κ, o) ∈ F }` and `support(o) = ∪_{g on o} support(g)`.

### 3.3 Decision variables

The selection must therefore carry separate binaries with linking constraints:

```
z_g ∈ {0,1}   expose clue group g           (the selection unit)
y_o ∈ {0,1}   right node o present          y_o ≥ z_g   ∀ g on o
                                             y_o ≤ Σ_{g on o} z_g
x_f ∈ {0,1}   edge f drawn                  x_f = z_{g(f)}   (atomicity, §3.4)
v_κ ∈ {0,1}   key κ used                    v_κ ≤ Σ_{g with key κ} z_g
```

`x_f ≤ y_{o(f)}` from the task statement is implied by `x_f = z_g ≤ y_o`.

### 3.4 Group atomicity — the OWA safeguard inside the graph itself

If the group `(workedAt OUT, Kyoto_University)` has support `{A, B, C}` and the
stage exposed only the `A` and `B` edges, the sentence "A and B worked at Kyoto
University" and the drawn graph would both **implicate** that C did not — a
contrast the snapshot contradicts. So a group is exposed as a whole or not at
all (`x_f = z_g`). Trimming happens at the level of *groups* (choose which
`(κ, o)` to show), never at the level of *edges within a group*. This is the
single most important difference from the legacy heuristics, which exposed
individual edges.

### 3.5 IN edges without reversing their semantics

An IN fact `(x, p, c)` is stored as `f = (c, (p, IN), x)` and drawn as an arrow
**from the right node into the choice** (`x → c`, label `p`), exactly as the
legacy builder did (`direction==1 ? choice→object : object→choice`). Its clue
sentence uses the IN template of `(p, IN)` ("A was the doctoral advisor of X"
versus "X was the doctoral advisor of A"). Two groups `(p, IN, x)` and
`(p, OUT, x)` are different groups, may share the right node `x`, and are never
counted as one clue or one fact. An IN group and an OUT group never merge into
a "shared predicate".

### 3.6 Right-node identity, and the grounding annotation

* **Identity** is the frozen `normalize_uri()` form, then the semantic index's
  `canonical()` representative (redirect/equivalence) **when the index is
  available for that object**. Two objects that are `CANONICALLY_EQUIVALENT`
  are one right node with both raw URIs recorded. Objects the index does not
  cover fall back to exact normalized identity and the record says so
  (`node_identity_basis ∈ {EXACT, CANONICAL_EQUIVALENT}`). Label-based
  merging is forbidden (`Iron(II) chloride` / `Iron(III) chloride`).
* **Alias families** (`dbp:field` / `dbp:fields`) unify keys *for grouping*
  under the same declared policy the v4 run used, direction preserved; the raw
  predicate of every edge is kept and printed.
* **Containment** (`CANDIDATE_OBJECT_UNDER_CLAIM`, e.g. Tokyo under Japan) does
  **not** merge nodes: `d --birthPlace--> Tokyo` and `A --birthPlace--> Japan`
  stay two nodes. The support relation is recorded as an annotation on the
  Answer edge (`supported_by_containment: [d]`) so a renderer can dash a line,
  but no edge that is not observed is ever drawn.
* **Grounding** of a clue group against a choice `c ∉ support(g)` is an
  annotation, computed from observations only and kept apart from the frozen
  evidence vocabulary:

  ```
  grounding(g, c) = SHARED              c ∈ support(g)
                  = ALTERNATIVE_OBSERVED c ∉ support(g) and O_c(κ) ≠ ∅
                  = ABSENCE_ONLY         c ∉ support(g) and O_c(κ) = ∅
  ```

  For Answer-owned groups against a distractor this coincides with the frozen
  level (`NOT_COVERED` / `L1` / `L0`) and the frozen value is **copied, not
  recomputed**. For distractor-owned groups the same observation rule is
  applied by the new stage; the result is called *grounding*, is never written
  into `levels`, never fed to the kernel, and never used to claim exclusion.
  `ABSENCE_ONLY` is what makes a clue carry an unsupported implicature
  ("B, C and D were born in Japan" ⇒ "A was not"), so it is penalised (§6) and
  reported.

### 3.7 Kinds of right node

| kind | source | support | provenance | role |
|---|---|---|---|---|
| `ENTITY` | pinned-KG one-hop counterpart | 1–4 | `pinned_kg:<sha256>` | ordinary evidence |
| `CLASS` | the selected class `selected_class_uri` | 4 by construction | `remote_category_membership:<cache>` — **not** the pinned KG | the frame sentence "A, B, C and D are all …" |

The class node is mandatory in both exposures (§5.3) and is drawn with its own
provenance, because the pinned snapshot holds no `dcterms:subject` edges
(`PHASE_B_INPUT_CONTRACT.md` §6.1). Its label may carry a recorded
`soft_overlap` (Kingdom of Italy / Italian states); that is reported, not
repaired.

### 3.8 What the graph never contains

No negative edge, no "does not have" edge, no node manufactured from absence,
no left node outside `C` (the legacy `find_other_node_for_object` added a fifth
entity from live SPARQL — rejected, §18), no edge whose triple is not in `K`,
and no edge under an ineligible predicate/object (§5.2).

---

## 4. Formal problem definition

**Given** a learner-facing v4 item `(A, D, R*, levels, quality, class)` and the
pinned snapshot `K`, **construct** the candidate universe `F` of eligible
observed fact edges of the four choices (§5), group it into `G`, and **choose**
two nested group subsets

```
S_pre ⊆ S_post ⊆ G,   with   G_mand ⊆ S_pre
```

such that: the right-node count of `S_pre` is at most `B_pre` and of `S_post`
at most `B_post`; every hard safety constraint of §6.2 holds; and each subset
maximises the declared utility of §6.3 exactly over the (possibly bounded)
universe, with the deterministic tie-break of §13.

`G_mand` are the mandatory groups: the class group and the `R*` groups.
Exposing `R*` is what makes the item answerable from the clue set: the
rationale is the kernel's proof that the observed facts of `A` set it apart
from `d1, d2, d3` at level ≥ L1, and an item whose clues omit it would be
answerable only from outside knowledge. `R*` is therefore **mandatory even
when it is Answer-only**, while optional Answer-only groups are the leakage the
objective penalises. That asymmetry is deliberate and is stated on the record.

---

## 5. The candidate fact universe

### 5.1 Sources

| source | how obtained | already exists? |
|---|---|---|
| Answer facts `F_A` | `AnswerCase.facts` (all, eligible and ineligible), with per-distractor levels, bases, risks and R1 quality | yes, on the v4 record |
| distractor facts `F_d` | one-hop enumeration of each `d_i` from the pinned KG, same frozen enumeration and normalization as B1.2 (`observed_edge_set` + `normalize_uri`), then R1 `assess_fact_quality(answer_uri = A, …)` | the enumeration exists (`candidate_objects_from_local_kg` yields `{κ: objects}`); the *quality assessment of a distractor fact against the Answer label* is new use of an existing frozen function |
| class group | `selected_class_uri`, its label, and the retrieval provenance | yes |

Leakage is always assessed **against the Answer label** for every choice's
facts: a distractor edge whose counterpart contains "Einstein" hands the
participant the Answer as surely as an Answer edge would.

### 5.2 Hard screens (a screened fact is EXCLUDED with a reason code, never a penalty)

| screen | rule | reason code |
|---|---|---|
| predicate/object eligibility | R1 `eligible == False` (raw layout slots, external/web-archive URLs, media, machine identifiers, hard Answer-label leak) | `EXCLUDED_INELIGIBLE_<R1 reason>` |
| option reference | counterpart URI ∈ `{A, d1, d2, d3}` (exact frozen URI, as `mcq_core.option_reference_conflicts` does) | `EXCLUDED_OPTION_REFERENCE` |
| self loop | counterpart == source choice | `EXCLUDED_SELF_LOOP` |
| class-label duplicate | counterpart is the selected class itself (already the CLASS node) | `EXCLUDED_DUPLICATES_CLASS_NODE` |
| pre-answer only: unverbalizable | no template for `κ` — the group cannot be rendered as a clue; it stays available for the graph | `PRE_EXCLUDED_UNVERBALIZABLE` |

A screen never removes an `R*` fact: if `R*` itself trips the option-reference
screen or is unverbalizable, the item is **flagged**, not silently altered
(§14: `CE_RATIONALE_OPTION_REFERENCE_CONFLICT`, `CE_RATIONALE_NOT_VERBALIZABLE`).

### 5.3 Tiers

| tier | definition | pre-answer | post-answer |
|---|---|---|---|
| `MANDATORY_CLASS` | the class group | required | required |
| `MANDATORY_RATIONALE` | the groups `(κ_f, o_f)` of every `f ∈ R*`, with their full support (a `NOT_COVERED` distractor shares the node and its edge is drawn — atomicity) | required | required |
| `RATIONALE_ALTERNATIVE` | for each `f ∈ R*` and each distractor `d` that `f` covers at L1, the groups `(κ_f, o′)` for `o′ ∈ O_d(κ_f)`: the **observed alternative values** that make the contrast an observation about `K` rather than an implicature | optional, preferred (human decision H3) | at least one per distractor required (`COVER_ALT` constraint, §6.2) |
| `OPTIONAL_CONTEXT` | every other eligible group | optional | optional |
| `EXCLUDED` | screened out, with reason | — | — |

Only `RATIONALE_ALTERNATIVE` groups can be guaranteed to exist for every
distractor of a main-corpus item: `main-l1` requires every distractor to reach
L1 through some `R*` fact, and L1 means `O_d(κ) ≠ ∅` under that key. For an
`L2` incidence (none exist today) the alternative may be empty and the
constraint is relaxed with a recorded reason.

A distractor-only shared group (support `{B, C, D}`, `A ∉ support`) is
`OPTIONAL_CONTEXT`. It is never described as evidence *against* `A`; its
grounding against `A` is `ALTERNATIVE_OBSERVED` or `ABSENCE_ONLY` and the
record says which.

### 5.4 Bounding the universe

Place and polity Answers have IN-heavy neighbourhoods (Kingdom of Italy: 3,026
nodes). The universe is bounded **only after** the hard screens and only for
`OPTIONAL_CONTEXT`, by a declared deterministic pre-key
`(-|support(g)|, tier(g), unverbalizable, |O_c(κ)|-based rarity rank, label
length, canonical identity)` truncated to `N_max` groups (candidate default
200, recorded). The record states `universe_scope ∈ {UNIVERSE_FULL,
UNIVERSE_BOUNDED}` in the same spirit as `FULL_EXACT` / `POOL_EXACT`, and the
exactness claim of §9 is always "exact over the declared universe".

---

## 6. Objective and constraints

### 6.1 Per-group attributes (all computed once, all recorded)

```
s_g   = |support(g)| ∈ {1,2,3,4}
a_g   = 1 if support(g) = {A}                       (Answer-only)
n_g   = 1 if s_g = 1                                (singleton, any letter)
t_g   = pedagogical tier of κ (1 best … 3 default)  from the frozen policy
verb_g= 1 if a template exists for κ
len_g = display-label length of o ;  tok_g = token count
abs_g = |{ c ∉ support(g) : grounding(g,c) = ABSENCE_ONLY }|   (implicature risk)
alt_g = |{ c ∉ support(g) : grounding(g,c) = ALTERNATIVE_OBSERVED }|
risk_g= 1 if g is an Answer group carrying a non-NONE granularity risk
        against any distractor (copied from the v4 record)
soft_g= 1 if the R1 soft leak flag is set on any edge of g
dl_g  = 1 if the counterpart label lexically leaks a DISTRACTOR label
rare_g= offline rarity rank of o under κ in the pinned KG (ordering only, §18)
```

### 6.2 Hard constraints (both exposures unless marked)

```
(H1) z_g = 1                              ∀ g ∈ G_mand
(H2) Σ_o y_o ≤ B                          right-node budget (B_pre / B_post)
(H3) y_o ≥ z_g, y_o ≤ Σ z_g               node/group linking
(H4) x_f = z_g(f)                          atomicity (§3.4)
(H5) z_g = 0                               ∀ g EXCLUDED
(H6) z_g^pre ≤ z_g^post                    nesting (post solve only)
(H7) COVER_ALT (post): ∀ d ∈ D: Σ_{g ∈ ALT(d)} z_g ≥ 1  when ALT(d) ≠ ∅
(H8) Σ_{g: a_g=1, g ∉ G_mand} z_g ≤ K_A    optional Answer-only cap
                                            (pre default 0; post default 1; H4)
(H9) Σ_g z_g ≤ B_groups                    optional clue-sentence cap (pre)
(H10) balance: ∀ c ∈ C: Σ_{g ∋ c, g ∉ class} z_g ≥ 1  — soft in practice,
      encoded with slack variables and a penalty (see W_bal), because a
      distractor with no eligible shared context must not make the item fail
```

### 6.3 Utility (maximise), integer-scaled

```
U(z) =  Σ_g z_g · u_g
      + W_div · Σ_κ v_κ                                  key diversity
      − W_red · ( Σ_g z_g − Σ_κ v_κ )                    repeated keys
      − W_bal · Σ_c slack_c                              unbalanced letters
      − W_len · Σ_g z_g · tok_g                          cognitive burden

u_g  =  W_sup · (s_g − 1)                                multi-choice support
      + W_tier · (3 − t_g)                               pedagogical tier
      + W_verb · verb_g
      − W_ans · a_g · [g ∉ G_mand]                       optional Answer-only
      − W_single · n_g · [g ∉ G_mand]                    singleton (any letter)
      − W_abs · abs_g                                    implicature risk
      − W_risk · risk_g − W_soft · soft_g − W_dl · dl_g
```

The mandatory groups contribute their `u_g` but are fixed by (H1), so they
cannot buy or lose anything; their attributes are still recorded (an `R*`
fact with `abs_g > 0` against a `NOT_COVERED`… cannot occur; with a soft leak
it is reported).

**Why weights rather than a pure lexicographic key.** The kernel's fourteen-field
key works because evidence *levels* dominate everything and must never be
traded. Here every term is pedagogical and trades are the point ("one more
shared node versus one fewer singleton"). A weighted objective with declared
integer weights, a recorded weight vector version, and an ablation over the
weights (§17) is the honest form. The evidence semantics remain untradeable
because they are constraints and tiers, not weights.

**Candidate default weight vector** (`ce_weights/1.0.0-candidate`, to be
measured, not asserted): `W_sup=4, W_tier=2, W_verb=2, W_div=3, W_red=2,
W_bal=3, W_len=0 (per token, pre only 1), W_ans=6, W_single=2, W_abs=3,
W_risk=2, W_soft=1, W_dl=1`. Pre-answer and post-answer use the same vector
except `W_ans` (post: 3) and `W_len` (post: 0). These numbers are placeholders
for the sensitivity study; the paper reports the swept range, not one value.

### 6.4 The three fact classes the objective must never confuse

| class | handled by | may it be Answer-only? |
|---|---|---|
| facts needed to explain `R*` | (H1), (H7) | yes, by design |
| optional educational/contextual facts | `u_g`, (H8) | penalised, capped |
| facts unsafe or misleading under OWA | §5.2 screens, `W_abs`, `W_risk`, never a negative edge | excluded or penalised, never rescued |

---

## 7. Algorithm design space

Sizes after screening, from the development batches: `|G|` from ~10 (small
persons) to several hundred (places/polities, before bounding); `|O| ≈ |G|`;
`|κ|` tens; `B ≤ 10`; four left nodes always.

### 7.1 Exact 0-1 ILP / CP-SAT

Variables `z_g, y_o, v_κ, slack_c` (a few hundred binaries), constraints
(H1)–(H10) all linear, objective integer. CP-SAT (OR-Tools) or CBC via PuLP
solves this in milliseconds to seconds. Enforces every constraint exactly;
optimal over the declared universe; supports the nesting constraint and the
sequential lexicographic tie-break (§13) by re-solving with the objective
fixed. Determinism requires: integer coefficients, one worker, fixed seed,
fixed variable order, and the tie-break protocol — CP-SAT alone returns *an*
optimum. Cost: a new binary dependency (OR-Tools ≈ 60 MB, or CBC); the
"explain it in a viva" burden of an ILP formulation is low because the model is
ten lines.

### 7.2 Exact enumeration / branch-and-bound / DP

Groups with identical attribute signature `(support set, κ, t, verb, abs, …)`
are interchangeable up to the deterministic representative; collapse to
classes (`|G′| ≤ 15 support masks × |κ| × few attribute values`). Exhaustive
subsets of size ≤ B over `G′` are `Σ_{b≤B} C(|G′|, b)`: fine at `|G′| ≤ 25,
B ≤ 6` (≈ 245k), hopeless at `|G′| = 100, B = 8` (≈ 2·10^11). A DP over
"support-mask profile" cannot absorb the diversity and balance terms exactly
without a state space of `2^|κ|`. Branch-and-bound with a utility upper bound
per remaining budget works and is pure Python, but it is a second exact solver
to prove correct, and its worst case is the same enumeration. Verdict: the
right **test oracle** for small instances, wrong production solver.

### 7.3 Greedy weighted maximum coverage / submodular selection

Iteratively add the group with the largest marginal `ΔU` per node consumed,
until the budget binds; then the mandatory groups first. `O(B · |G|)`,
deterministic with the §13 order, trivially explainable. The support and
diversity terms are monotone submodular in `z`, but the penalties are modular
negatives, the node budget is a submodular *cost* (groups sharing a node cost
nothing extra), and (H7)/(H10) are covering constraints — so the classic
`(1 − 1/e)` guarantee does not apply to the whole objective, and greedy can be
strictly suboptimal (e.g. two groups on one already-paid node beat one group on
a new node, which greedy-by-marginal-per-node sees only if evaluated after the
first). Verdict: the natural **baseline and fallback**, not the headline.

### 7.4 Beam search / bounded combinatorial search

Width-`W` beam over group additions, scoring partial selections with `U`,
`O(B · W · |G|)`. Better than greedy, still heuristic, adds a width parameter
with no clear scientific meaning and makes reproducibility depend on tie order
inside the beam. Verdict: dominated — it costs more than greedy and proves
less than the ILP.

### 7.5 The legacy heuristic (author's original files)

One shared-by-all fact, one pairwise-shared fact, one "unique" Answer fact
chosen by live-SPARQL rarity (§18). Deterministic only after replacing the
`next(iter(set))` picks and the network popularity by pinned-KG counts; ignores
IN/OUT pairing across choices in one place, reads absence as contrast, exposes
edges rather than groups, fixes `A = Answer`. Verdict: **must be kept as a
named baseline** (it is the author's prior design and the reviewer will ask),
reimplemented offline with its unsafe steps replaced and every replacement
recorded; not a candidate for the proposed method.

### 7.6 Complexity summary

| method | time | memory | exact? | constraint handling |
|---|---|---|---|---|
| ILP / CP-SAT | practically ms–s; worst-case exponential | small | yes (declared universe) | all, exactly |
| exhaustive / B&B | `Σ C(|G′|,b)` | small | yes | all, exactly |
| greedy | `O(B·|G|)` | small | no | budget yes; (H7)/(H10) by repair steps |
| beam | `O(B·W·|G|)` | `O(W·B)` | no | as greedy |
| legacy | `O(|F|)` | small | no | almost none |

Universe construction itself is `O(Σ_c deg(c))` reads of the pinned KG plus
`O(|F|)` quality assessments and is identical for every method, so the
comparison is fair by construction.

---

## 8. Decision matrix

Scores 1 (poor) – 5 (best); the rightmost column is the reason the score is
not higher.

| criterion | ILP/CP-SAT | exact enum/B&B | greedy | beam | legacy | main caveat |
|---|:-:|:-:|:-:|:-:|:-:|---|
| optimises the declared objective | 5 | 5 | 2 | 3 | 1 | greedy/beam optimise a proxy |
| enforces (H1)–(H10) exactly | 5 | 5 | 3 | 3 | 1 | greedy needs repair passes |
| nesting pre ⊆ post | 5 | 4 | 4 | 3 | 1 | — |
| determinism | 4 | 5 | 5 | 3 | 2 | ILP needs the §13 protocol; beam ties |
| scalability at 100–105 MCQs | 5 | 2 | 5 | 4 | 5 | enumeration explodes on places |
| explainability in the paper | 4 | 4 | 5 | 3 | 3 | "a small 0-1 program" is one paragraph |
| reproducibility | 4 | 5 | 5 | 4 | 2 | solver version must be pinned |
| ease of ablation | 5 | 3 | 4 | 3 | 2 | weights and constraints are switches |
| new dependency / engineering risk | 2 | 4 | 5 | 4 | 5 | OR-Tools or CBC is a real dependency |
| risk of over-engineering | 3 | 3 | 5 | 2 | 4 | the ILP is small; beam adds a knob |
| matches the paper's exactness narrative (`FULL_EXACT`) | 5 | 5 | 2 | 2 | 1 | — |

---

## 9. Preferred architecture and the reasons

**Preferred: exact 0-1 ILP (CP-SAT or CBC) over the declared universe, solved
twice (pre-answer, then nested post-answer), with the greedy selector as the
recorded fallback and baseline, exhaustive enumeration as the test oracle, and
the offline legacy heuristic as a named baseline.**

Reasons, in order of weight:

1. **The instance is tiny and structured.** Four left nodes, a one-hop
   universe that is screened, grouped and bounded, a budget under ten. The
   whole model is ten constraint families over a few hundred binaries. This is
   precisely the regime where an exact solver costs nothing and a heuristic
   costs a claim.
2. **Exactness is the project's narrative.** The kernel enumerates every
   combination and every minimum rationale and labels the scope of the claim
   (`FULL_EXACT` / `POOL_EXACT`). A downstream stage that "greedily picked some
   context" would be the weakest link in the chain a reviewer follows.
   `UNIVERSE_FULL` / `UNIVERSE_BOUNDED` gives the same honest scoping.
3. **Constraints are the safety story.** Atomicity (H4), the Answer-only cap
   (H8), `COVER_ALT` (H7) and nesting (H6) are what keep the graph OWA-safe and
   consistent with the clues. A solver enforces them; a greedy pass would need
   repair heuristics whose interaction with the objective is hard to state.
4. **Ablation is a switch.** Every weight and constraint of §6 can be turned
   off in the same solver, so "which component matters" is answered by one code
   path, not five.
5. **Weights are honest here.** Unlike evidence levels, the quantities traded
   here are all pedagogical; a declared weight vector with a sensitivity sweep
   is the transparent way to say so.

### 9.1 Skeptical self-review — where this recommendation is weakest

* **A weighted objective invites weight tuning on the evaluation data.** The
  mitigation is procedural (§16): weights and budgets are chosen on the
  development batches by pre-registered automatic criteria plus a small pilot
  on a *disjoint* sample; the human test set is never used to select them.
  Reported: the swept range and the stability of the selected set across
  neighbouring weights.
* **The ILP's "optimality" is over a universe this stage constructed.** The
  screens and the bounding pre-key are policy, and a different `N_max` or
  pre-key yields a different optimum. Mitigation: `universe_scope` on every
  record, `N_max` in the manifest, and a budget-sensitivity arm that raises
  `N_max` until the selection stops changing on the development batches.
* **A new solver dependency versus a viva-defensible pure-Python core.** The
  minimal-research-core plan (`docs/plans/MINIMAL_RESEARCH_CORE_PLAN.md`)
  argues for author-comprehensible code. An OR-Tools model is short, but it is
  a black box at run time. Mitigation: the exhaustive oracle test on every
  small instance of the pilot set, a pinned solver version in the manifest,
  and the greedy fallback that records `CE_SOLVER_UNAVAILABLE_GREEDY_USED`
  rather than failing. **This is human decision H6.**
* **The pre-answer format changes what "leakage" means, and the objective
  encodes one reading of it** (Answer-only groups and singletons leak; shared
  groups do not). A shared group can still leak if the participant knows the
  fact for exactly one name. That cannot be measured offline; it is exactly
  what the human study measures (§15), and `direct_identifier` must not be
  quoted as a difficulty proxy.
* **The grounding annotation reuses the observation rule on distractor-owned
  facts.** It is deliberately named differently from the evidence levels and
  is never fed to the kernel, but a reviewer may ask why the same rule yields
  two vocabularies. Answer: the level is a property of an *Answer* fact
  against a candidate and drives coverage; grounding is a *presentation-safety*
  annotation on any clue against any choice and drives nothing upstream.
  **Human decision H2** is whether to keep the two names or to state the
  classifier generically in the paper.
* **The class node depends on a live category source.** It is provenance-
  labelled, but the paper must say the frame sentence rests on DBpedia
  category membership at retrieval time, not on the pinned snapshot.
* **Greedy might be "good enough".** If the sensitivity study shows greedy and
  ILP select identical sets on > 95 % of items, the paper should say so and
  keep the ILP only for the guarantee. That is a finding, not a threat.

---

## 10. Pseudocode (design only)

```
procedure SELECT_CHOICE_EVIDENCE(item, kg, policies, budgets, weights):
    # item: AnswerCase + Selection + GranularityCleanOutcome + class + provenance
    assert item.mcq_evidence_level in {MCQ-L1, MCQ-L2} and item.learner_facing
    letters := deterministic_permutation(item.answer_uri, seed)      # A/B/C/D
    F := answer_edges(item.case)                                       # frozen
         ∪ { distractor_edges(d, kg, policies.quality, answer=item.answer_uri)
             for d in item.distractors }
    for f in F: f.screen := hard_screens(f, item)                       # §5.2
    G := group_by((alias_key(f.κ), canonical(f.o)))                    # §3.6
    for g in G: g.support, g.grounding[c], g.attributes := ...          # §6.1
    tier(G) := MANDATORY_CLASS | MANDATORY_RATIONALE | RATIONALE_ALTERNATIVE
             | OPTIONAL_CONTEXT | EXCLUDED                              # §5.3
    G := bound_optional(G, N_max, prekey)  ; scope := FULL|BOUNDED      # §5.4

    S_pre  := SOLVE(G, budget=B_pre,  weights=w_pre,
                    hard={H1..H5, H8(K_A=0), H9, H10}, fixed=∅)
    S_post := SOLVE(G, budget=B_post, weights=w_post,
                    hard={H1..H5, H6(S_pre), H7, H8(K_A=1), H10}, fixed=S_pre)
    assert S_pre ⊆ S_post
    return records(S_pre, S_post, G, statuses, objective_components, tiebreak)

procedure SOLVE(G, budget, weights, hard, fixed):
    model := 0-1 program with z_g, y_o, v_κ, slack_c and constraints `hard`
    U* := maximise U(z)                          # integer objective, 1 worker, seed 0
    # deterministic tie-break among optima (§13):
    add constraint U(z) = U*
    for g in canonical_order(G):                 # sequential lexicographic
        if feasible(model ∧ z_g = 1): fix z_g = 1 else fix z_g = 0
    return { g : z_g = 1 }
    on solver unavailable/timeout: S := GREEDY(G, budget, weights, hard);
        status := CE_SOLVER_UNAVAILABLE_GREEDY_USED  (never silent)

procedure GREEDY(G, budget, weights, hard):      # baseline and fallback
    S := mandatory(G); repair(H7, H10)
    while nodes(S) ≤ budget:
        g* := argmax over admissible g ∉ S of (ΔU(S ∪ {g}) / Δnodes)
              broken by canonical_order
        if ΔU ≤ 0: break
        S := S ∪ {g*}
    return S
```

---

## 11. Pre-answer versus post-answer — the design and its alternatives

### 11.1 Preferred: one universe, one scoring model, two nested selections

* `QuestionClueSelector` chooses `S_pre` with budget `B_pre` (groups, since a
  group is a sentence) and `K_A = 0` optional Answer-only groups; every group
  must be verbalizable; `W_len > 0` because prose length is cognitive load.
* `PostAnswerExplanationGraphSelector` chooses `S_post ⊇ S_pre` with budget
  `B_post` (right nodes), `COVER_ALT` required so every distractor's observed
  alternative value under a covering rationale key is drawn, `K_A = 1` so one
  additional Answer fact may enrich the explanation, unverbalizable groups
  admissible (the graph prints predicate labels).
* Both are the same ILP with different parameters; the record carries both
  parameter sets.

**Consistency guarantees.** Every clue is an edge of the graph (nesting); every
edge is an observed triple of `K` (universe); no group is partially exposed
(atomicity); no negative edge exists (§3.8). The graph therefore cannot
contradict the clues and cannot imply an unsupported negative *by construction*
— the residual implicature risk (a node with support `{B, C, D}`) is measured
(`abs_g`) and handled by the legend text: "an edge is a fact recorded in the
snapshot; a missing edge means the snapshot records nothing, not that the fact
is false."

### 11.2 Alternatives considered

| alternative | why not preferred |
|---|---|
| one selection used for both exposures | forces one budget on two purposes; either the clue set is too long or the graph too thin; loses the `K_A` asymmetry |
| two independent selections | can omit a clue from the graph or show alternative values in the clues without control; consistency becomes a post-hoc check |
| post first, then pre as a sub-selection | makes the question a by-product of the explanation; the item's answerability and leakage are the primary quantities, so the clue set is solved first |
| a single richer selection plus a "reveal order" | attractive for UI, but the human protocol shows the graph only after answering, so a static two-set record is enough |

---

## 12. Module and API boundaries

### 12.1 What the stage consumes from v4 (read-only)

| input | source on the v4 side | used for |
|---|---|---|
| `AnswerCase` (facts with `levels`, `exclusion_bases`, `granularity_risks`, `FactQuality`) | `result.case` | Answer edges, frozen levels, quality |
| `Selection` (`positions`, `distractors` with rank/score, `rationale.fact_indices`, `coverage_masks`, `evidence_policy`, `rationale_objective`, `option_reference_conflict_*`, `direct_identifier_flag`, local anonymity) | `result.selection` after the granularity policy (`outcome.selection`) | mandatory tier, flags |
| `GranularityCleanOutcome.learner_facing`, `.status`, and **the rationale's own** `granularity_risk_incidences` | `result.granularity_outcome`, `selection.rationale` | the gate; `risk_g` — see §20 on why the status string must not be used for the count |
| `mcq_evidence_level`, `has_main_l1_selection` | `result` | the gate |
| `selected_class_uri`, class label, `class_approval_status`, retrieval provenance | `result`, run provenance | the CLASS node |
| `phase_b1_provenance` (`pinned_kg_sha256`, `quality_policy_sha256`, `semantic_relation_policy_sha256`, `semantic_index_cache_key`, `alias policy record`) | `record["phase_b1_provenance"]`, `config.as_record()` | provenance, and the same alias policy for grouping |
| the pinned KG, loaded through `kg.loader.load_local_kg` with SHA-256 verification | runner | distractor one-hop facts |
| the quality policy (`predicate_policy_v2.json`) and the semantic index for this item (if available) | runner context | eligibility/templates for distractor facts; node identity |

The stage never imports `lrolesim`, never calls `select_distractors`, never
constructs `AnswerCase`, and never writes into a v4 artefact directory.
`mcq_core` is imported only for its frozen dataclass types.

### 12.2 Proposed package

```
src/choice_evidence_v1/
  contracts.py    vocabulary: tiers, grounding, statuses, node kinds, record types
  universe.py     build F and G from AnswerCase + pinned KG; screens; grouping; bounding
  grounding.py    grounding(g, c) annotation; option-reference and leakage screens
  objective.py    attributes u_g, the weight vector record, U(z) as data
  select_exact.py the 0-1 program (CP-SAT/CBC), tie-break protocol, solver manifest
  select_greedy.py the baseline/fallback
  select_legacy.py the offline reimplementation of the author's heuristic (§18)
  graph.py        ChoiceEvidenceGraph record from a selection; JSON + GraphML
  clues.py        the pre-answer ClueGroupPlan (no sentences — templates are a later task)
  metrics.py      §15 metrics for one item and for a batch
scripts/run_phase_b3_choice_evidence_v1.py   offline runner over a v4 artefacts root
tests/test_choice_evidence_v1.py             oracle equality, atomicity, OWA, nesting, determinism
```

Public API (design):

```
build_universe(case, selection, class_info, *, local_kg, quality_policy,
               alias_policy, semantic_index, n_max) -> FactUniverse
select_clue_groups(universe, *, budget, weights, constraints) -> GroupSelection
select_explanation_graph(universe, clue_selection, *, budget, weights,
                         constraints) -> GroupSelection
build_graph(universe, selection, letters) -> ChoiceEvidenceGraph
item_record(universe, pre, post, graph, statuses, manifest) -> dict
```

### 12.3 Output schemas (machine-readable, one JSON record per item)

```json
{
  "schema_version": "choice_evidence_v1/1.0.0",
  "answer_uri": "...", "display_label": "...",
  "letters": {"A": "<uri>", "B": "<uri>", "C": "<uri>", "D": "<uri>",
              "permutation_seed": 0, "answer_letter": "C"},
  "gate": {"mcq_evidence_level": "MCQ-L1", "learner_facing": true,
           "evidence_policy": "main-l1"},
  "universe": {"scope": "UNIVERSE_FULL|UNIVERSE_BOUNDED", "n_max": 200,
               "edge_count": 0, "group_count": 0, "node_count": 0,
               "excluded_by_reason": {"EXCLUDED_OPTION_REFERENCE": 0},
               "node_identity_basis_counts": {"EXACT": 0, "CANONICAL_EQUIVALENT": 0},
               "semantic_index_available": true},
  "groups": [ { "group_id": "g0007", "predicate_uri": "...", "direction": "OUT",
                "counterpart_uri": "...", "node_id": "o0003", "display_label": "...",
                "tier": "OPTIONAL_CONTEXT", "support": ["A","B","C"],
                "grounding": {"D": "ALTERNATIVE_OBSERVED"},
                "attributes": {"s": 3, "a": 0, "n": 0, "t": 1, "verb": 1, "abs": 0,
                               "alt": 1, "risk": 0, "soft": 0, "dl": 0, "tok": 2,
                               "rare_rank": 12},
                "template_id": "...", "edges": ["f0011","f0012","f0019"] } ],
  "edges":  [ { "edge_id": "f0011", "source_choice": "A", "predicate_uri": "...",
                "direction": "OUT", "counterpart_uri": "...", "group_id": "g0007",
                "eligible": true, "screen": "NONE",
                "frozen_levels": {"B": "NOT_COVERED", "C": "NOT_COVERED", "D": "L1"},
                "provenance": {"pinned_kg_sha256": "...",
                               "fact_schema_version": "journal2-prompt8d-observed-fact-v1"} } ],
  "mandatory": {"class_group": "g0001",
                "rationale_groups": [{"group_id": "g0004", "rationale_fact_index": 17,
                                      "coverage_mask": 7}],
                "rationale_alternative_groups": {"B": ["g0009"], "C": ["g0010"], "D": []}},
  "pre_answer": {"budget_groups": 4, "budget_nodes": null, "k_answer_only": 0,
                 "selected_groups": ["g0001","g0004","g0007","g0012"],
                 "selected_nodes": ["o0001","o0002","o0003","o0006"],
                 "objective_value": 41, "objective_components": {"support": 20, "...": 0},
                 "weights_version": "ce_weights/1.0.0-candidate",
                 "solver": {"name": "cp-sat", "version": "...", "workers": 1, "seed": 0,
                            "status": "OPTIMAL", "tiebreak_solves": 6},
                 "status": "CE_SELECTED"},
  "post_answer": { "budget_nodes": 7, "k_answer_only": 1, "nested_over_pre": true,
                   "cover_alt_satisfied": {"B": true, "C": true, "D": false},
                   "selected_groups": [], "selected_nodes": [], "...": 0,
                   "status": "CE_SELECTED" },
  "graph": {"left": ["A","B","C","D"],
            "right": [{"node_id": "o0001", "kind": "CLASS|ENTITY", "uris": ["..."],
                       "label": "...", "provenance": "..."}],
            "edges": [{"edge_id": "f0011", "from": "A", "to": "o0003",
                       "orientation": "choice_to_node|node_to_choice",
                       "predicate_uri": "...", "direction": "OUT",
                       "role": "MANDATORY_RATIONALE|RATIONALE_ALTERNATIVE|OPTIONAL_CONTEXT|CLASS"}],
            "legend_note": "an edge is a fact recorded in the pinned snapshot; a missing edge means the snapshot records nothing, not that the fact is false"},
  "flags": {"rationale_option_reference_conflict": false,
            "rationale_unverbalizable_fact_count": 0,
            "rationale_granularity_risk_incidences": 0,
            "direct_identifier_flag": true,
            "direct_identifier_note": "local structural specificity only; not a difficulty claim",
            "class_label_leak_level": "no_leak|soft_overlap"},
  "statuses": ["CE_SELECTED"],
  "notes": {"open_world": "...", "lrolesim_role": "...", "not_publication_final": true}
}
```

Batch outputs: `choice_evidence_items.jsonl`, `choice_evidence_metrics.json`,
`choice_evidence_summary.csv`, `run_manifest.json` (weights version, budgets,
`N_max`, solver name/version, pinned KG sha256, policy sha256s, v4 artefacts
root sha256 list).

---

## 13. Deterministic tie-breaking

1. **Canonical order of groups**: `(tier rank, -s_g, t_g, 1-verb_g, abs_g,
   a_g, n_g, tok_g, len_g, predicate_uri, direction, canonical counterpart
   uri)` — a total order because the identity triple is unique after grouping.
2. **Deterministic representative** of equivalent raw URIs inside one node:
   lexicographically smallest normalized URI, all members recorded.
3. **Solver**: integer objective; one worker; fixed seed; variables created in
   canonical order; after the optimum, the **sequential lexicographic fix**
   (§10) makes the chosen optimum the canonical-order-maximal one. Two runs on
   identical input therefore produce byte-identical records, which is a test.
4. **Greedy**: ties on marginal utility broken by canonical order.
5. **Letters**: a permutation drawn from a seeded generator keyed on the Answer
   URI; recorded on the record; the Answer is never at a fixed letter.

---

## 14. Failure and status taxonomy

| status | meaning | item published? |
|---|---|---|
| `CE_SELECTED` | both selections found with at least one optional group | yes |
| `CE_SELECTED_MANDATORY_ONLY` | budget or universe allowed nothing beyond the mandatory tiers | yes, flagged |
| `CE_SKIPPED_NOT_LEARNER_FACING` | v4 item is MCQ-L0, has no selection, or is not learner-facing under the granularity policy | no |
| `CE_RATIONALE_NOT_VERBALIZABLE` | an `R*` fact has no template; graph produced, clue text blocked | graph yes, clues no |
| `CE_RATIONALE_OPTION_REFERENCE_CONFLICT` | `R*` names a printed option (already counted upstream); flagged, never repaired here | yes, flagged |
| `CE_MANDATORY_EXCEEDS_BUDGET` | the mandatory right nodes alone exceed `B` | no (budget is the wrong one) |
| `CE_COVER_ALT_RELAXED` | some distractor has no observed alternative under any covering key (only possible with L2) | yes, recorded |
| `CE_UNIVERSE_BOUNDED` | `N_max` truncated the optional universe | yes, scope recorded |
| `CE_SEMANTIC_INDEX_UNAVAILABLE_EXACT_IDENTITY` | node identity fell back to exact URIs for some objects | yes, recorded |
| `CE_SOLVER_UNAVAILABLE_GREEDY_USED` / `CE_SOLVER_TIMEOUT_GREEDY_USED` | fallback path taken | yes, flagged; excluded from the "exact" denominator |
| `CE_DISTRACTOR_NOT_IN_PINNED_KG` | input contract violation (cannot happen for a v4 selection) | error |
| `CE_NESTING_VIOLATED` | internal assertion | error |

Query failure, empty result and cache hit remain three different states in
every KG or cache access the stage makes; the stage makes no network access.

---

## 15. Evaluation metrics

Per item and aggregated per cohort; every rate carries its denominator.

**Structure.** `|O_pre|`, `|O_post|`, `|S_pre|` (clue sentences), `|E_post|`
(edges), edges per choice, mandatory share of the budget.
**Support and balance.** mean `s_g` over optional groups; share of nodes with
support ≥ 2, ≥ 3, = 4; per-letter degree; min/max degree ratio; letters with
zero optional context.
**Leakage proxies.** optional Answer-only groups (should be 0 pre); singleton
groups per letter; distractor-label leaks; class-label leak level;
`direct_identifier_flag` rate (reported as specificity, never difficulty).
**OWA safety.** `abs_g` incidences exposed (implicature risk), share of exposed
contrasts that are `ALTERNATIVE_OBSERVED`, `COVER_ALT` satisfaction, count of
granularity-risk-bearing groups exposed.
**Diversity/redundancy.** distinct keys, repeated-key groups, IN/OUT ratio,
distinct support masks.
**Verbalizability/burden.** verbalizable fraction of exposed groups, tokens per
clue, total clue tokens.
**Pedagogy.** tier distribution of exposed groups; share of tier-1.
**Method agreement.** Jaccard between ILP and greedy/legacy selections;
objective gap of greedy versus ILP.
**Human (later, on the frozen configuration).** accuracy, time, perceived
informativeness of clues, perceived usefulness and clarity of the graph,
perceived answer leakage, unique-correctness judgement, with the agreement
statistics of `06_evaluation_plan.md` §7.

---

## 16. Budget sensitivity — how to choose `B` without overfitting

1. **Sweep** `B_pre ∈ {2,3,4,5,6}` optional groups and `B_post ∈ {4,…,10}`
   right nodes, and `N_max ∈ {100, 200, 400}`, on the two development batches
   (329 + 189 Answers, v4 outputs, offline). Also sweep the two weights the
   self-review flagged as fragile (`W_ans`, `W_abs`) over three values each.
2. **Report** for every cell the §15 structural metrics, the share of items
   hitting `CE_SELECTED_MANDATORY_ONLY`, the marginal objective gain per added
   node, and the selection stability (Jaccard against the neighbouring cell).
3. **Pre-registered choice rule** (before any human data): the smallest
   `B_post` at which the median marginal gain per node falls below a declared
   fraction of the first node's gain (a knee rule), subject to `COVER_ALT`
   feasibility ≥ 95 %; `B_pre` the smallest value at which ≥ 90 % of items
   have every letter appearing in at least one optional clue.
4. **Pilot** the rule's output on a small *development-only* sample with two
   raters for readability and overload; adjust once, record the change.
5. **Freeze** budgets and weights in the manifest **before** the human study;
   the human test set is never used to move them. Report the sweep in the
   paper as a figure, not a single number.

---

## 17. Baselines and the minimal ablation set

| id | method | what it isolates |
|---|---|---|
| B0 | rationale-only (class + `R*` + `COVER_ALT`) | the value of any context at all |
| B1 | all eligible shared groups (support ≥ 2), ordered by `(-s, t, canonical)`, cut at `B` | whether optimisation beats a sorted cut |
| B2 | legacy heuristic, offline reimplementation (§18) | the author's prior design |
| B3 | greedy maximum-utility | whether exactness matters |
| M | exact ILP (proposed) | — |

Minimal ablations of M, each a single switch: (i) `W_ans = 0` (no Answer-only
penalty), (ii) no atomicity (edge-level exposure, to count the implicature
incidents it creates), (iii) `W_div = W_red = 0`, (iv) `W_abs = 0`, (v) budget
sweep of §16. Five methods × one budget column plus five one-switch ablations
is the whole table.

---

## 18. Legacy sources — reusable versus unsafe ideas

Historical evidence only; none of it is current semantics.

### `src/mcq_generation.py`

| idea | verdict | note |
|---|---|---|
| `gather_equiv_classes`: `(p, dir) → {objects}` per node | reusable, already reimplemented | `candidate_objects_from_local_kg` is the frozen form |
| `get_shared_facts`: intersection of `(κ, o)` over a node subset | reusable | becomes `support(g)` |
| `get_diff_fact`: "distractor lacks the key ⇒ pick it" | **unsafe** | reads absence as contrast (L0 as evidence); replaced by the frozen levels and `R*` |
| `next(iter(set))` picks | unsafe | non-deterministic; replaced by canonical order |
| fixed `A = Answer`, `B..D = distractors` | **unsafe** | positional leak; replaced by a seeded recorded permutation |
| fallback prose "are all top scientists" | **unsafe** | fabricated fact; no fallback text is ever generated |
| "All … / A and B both … / If A has p = o, which is A?" three-line skeleton | reusable as the *shape* of the clue plan | class group, shared groups, mandatory rationale |

### `src/build_bipartite_and_draw_ExtendedVersion.py`

| idea | verdict | note |
|---|---|---|
| `STOP_PREDICATES` | reusable idea, superseded | the versioned quality policy is its audited successor |
| `MERGE_MAP` (`Kyoto_Imperial_University → Kyoto_University`, `Empire_of_Japan → Japan`) | **unsafe** | hard-coded, unaudited equivalence; node identity uses the semantic index's declared equivalence source only |
| live-SPARQL `get_popularity` and `rarity = 1/popularity` | idea reusable, mechanism **unsafe** | network, non-reproducible, cached failures as `999999`; replaced by an offline pinned-KG count of subjects under `(κ, o)`, used as an ordering annotation `rare_g` only |
| class node with "is a" edges to all four | reusable | the `CLASS` node, with explicit remote provenance |
| right nodes = objects with ≥ 2 owners | reusable | the support ≥ 2 preference; now a weight, not a filter, because `R*` may be support 1 |
| `find_unique_predicates`: key present in all four with pairwise disjoint object sets | partially reusable | it is a stricter, all-observed form of L1 for every distractor and inspires `COVER_ALT`; it is not the evidence definition (a key absent on a distractor is L0, not "unique") |
| `(unique)` edge highlight | reusable | the `MANDATORY_RATIONALE` role on an edge |
| direction-aware drawing (`node→object` vs `object→node`) | reusable, correct | §3.5 |
| `A (Name)` labels and the plum Answer colour | post-answer only | pre-answer shows letters only |
| networkx/matplotlib two-column layout | reusable for rendering | rendering is a later task |

### `src/all_in_one.py`

| idea | verdict | note |
|---|---|---|
| `SYNONYM_MAP` | **unsafe** | same as `MERGE_MAP` |
| `find_shared_objects`, `build_bipartite_graph_1` | reusable structure | our `G` construction |
| `pick_best_unique_predicate`: Answer object not in *any* distractor object set regardless of predicate | **unsafe** | mixes keys; contrast is defined per `κ` |
| `sparql_count_inlinks` rarity | as above | offline replacement |
| `find_other_node_for_object` / `add_other_node_to_graph` (fifth left node from SPARQL) | **rejected** | adds an entity outside the candidate pool from the network; the left side is exactly `C` |
| G2 with `Node1..Node4` and hidden names | reusable idea | the pre-answer anonymisation, but with a seeded permutation rather than fixed positions |
| "also knownFor" synthetic relation label | unsafe | a relation label that is not a predicate of `K` |

---

## 19. Threats to validity

1. **Implicature under OWA.** Any clue with `abs_g > 0` invites the participant
   to infer a false negative. The penalty and the legend reduce but cannot
   remove the risk; the human study must ask whether participants drew such
   inferences.
2. **Two data sources on one graph.** The class node rests on live category
   membership; every other node on the pinned snapshot. Provenance is
   labelled, but a reader of the picture sees one graph.
3. **Snapshot skew.** IN-heavy neighbourhoods (places, polities) make the
   optional universe dominated by "X born here" style facts; the tier and
   diversity terms mitigate, the bounding pre-key decides what survives, and
   the cohort-level metrics must be reported separately for persons versus
   places.
4. **Semantic index coverage.** The index is built for the Answer's
   source-object set; distractor-only counterparts fall back to exact identity,
   so two spellings of one place can appear as two nodes. Recorded per node;
   a rebuild over the enlarged set is possible offline but changes the cache
   key and must never be used to re-decide levels.
5. **Weight and budget selection.** Addressed procedurally (§16); the residual
   risk is that the development batches and the benchmark cohorts differ in
   composition.
6. **Verbalization coverage.** An unverbalizable `R*` blocks the clue text; the
   share of such items is a yield figure the paper must report, and the
   upstream contradiction (§20) must be resolved by a human.
7. **"Exact" is over a constructed universe.** Stated on every record.
8. **Difficulty is not modelled.** Nothing here predicts human difficulty;
   `direct_identifier` and singleton counts are structural proxies only.
9. **Solver reproducibility across versions.** Pinned in the manifest; the
   oracle test guards small instances only.

---

## 20. Known issues noted, deliberately not repaired here

* **Granularity reporting defect** in `src/selection/granularity_clean.py`,
  `apply_granularity_policy()`: under `report-only` the branch
  `if not policy.requires_clean or policy.admits(...)` returns
  `STATUS_NO_RISK_PRESENT` (`GRANULARITY_NO_RISK_IN_THE_SELECTED_RATIONALE`)
  even when `baseline.rationale.granularity_risk_incidences > 0`; the count is
  still recorded on the outcome (`baseline_granularity_risk_incidences`). This
  stage therefore reads `risk_g` from the rationale's own incidence count and
  per-pair risks, **never** from the status string. The fix belongs to a
  separate task.
* **Verbalizability contradiction**: `PHASE_B_INPUT_CONTRACT.md` §3.2 says an
  unverbalizable fact is barred from the main corpus; the kernel orders on it
  only (key 9) and `has_main_l1_selection` does not read it. Muhammad's
  selected rationale contains a template-less fact. This stage reports
  `CE_RATIONALE_NOT_VERBALIZABLE` and does not change `R*`. Whether a
  versioned `require-verbalizable` policy should exist upstream is human
  decision H5.
* **Open v4 publication choices** (`11_final_benchmark_candidate_policy.md`)
  are inputs to this stage, not affected by it; the stage must run on whatever
  frozen configuration is recorded.

---

## 21. Open questions that require a HUMAN research decision

| id | decision | default assumed in this design |
|---|---|---|
| H1 | Is `R*` always exposed in the pre-answer clue set (the item is answerable from the clues), or may some items rely on outside knowledge? | always exposed |
| H2 | Reuse the observation rule on distractor-owned facts under a separate `grounding` vocabulary, or state one generic classifier in the paper with two roles? | separate vocabulary, never fed upstream |
| H3 | Are `RATIONALE_ALTERNATIVE` groups (the distractors' observed alternative values) shown **before** answering, or only after? | optional-preferred before, required after |
| H4 | `K_A`: how many optional Answer-only groups may appear (pre / post)? | 0 / 1 |
| H5 | Should a `require-verbalizable` policy exist upstream, mirroring `require-clean`? | not assumed; flagged per item |
| H6 | Exact solver dependency: OR-Tools CP-SAT, CBC via PuLP, or a pure-Python branch-and-bound? | CP-SAT with greedy fallback |
| H7 | Budget definitions: pre-answer budget in clue groups (sentences) and post-answer in right nodes, or nodes for both? | groups pre, nodes post |
| H8 | Is the class frame sentence mandatory, given its remote provenance and possible soft overlap? | mandatory, provenance-labelled |
| H9 | Offline rarity (`rare_g`): ordering annotation only, or a weighted utility term as in the legacy design? | ordering only |
| H10 | Letter permutation: uniformly random per item with a recorded seed, or Latin-square balanced across the benchmark? | seeded per item |
| H11 | Do the sweep and knee rule of §16 count as pre-registration for the paper, and who signs the frozen budget? | the author, before the human study |
| H12 | Post-answer explanation prose: template-only, or LLM-polished under the grounding constraints of `03_journal2_algorithm_spec.md` §12? | template-only in the first version |

---

## 22. Files inspected for this design (read-only), and files touched

**Inspected**: `CLAUDE.md`; `docs/context/00_context_index.md`,
`10_current_state_post_b2ef.md`, `11_final_benchmark_candidate_policy.md`,
`EVIDENCE_TAXONOMY_V1.md`, `PHASE_B_INPUT_CONTRACT.md`,
`03_journal2_algorithm_spec.md`, `06_evaluation_plan.md`,
`09_claims_and_terminology.md`, `01_project_goal.md`, the bipartite-related
sections (§§26 and 37–46 by grep) of `MCQ_Journal2_B2_B3_Context_Handoff_EN_2026-08-13.md`;
`docs/audits/B2G_PRE_FINAL_BENCHMARK_SAFETY_AUDIT_2026-09-18.md`,
`docs/audits/ANSWER_LEAKAGE_DESIGN_AUDIT.md` (first 200 lines),
`docs/plans/MINIMAL_RESEARCH_CORE_PLAN.md` (first 60 lines);
`src/mcq_core.py`, `src/mcq_inputs.py`,
`src/pipeline/phase_b2_any_answer_run_v4.py`,
`scripts/run_phase_b2_any_answer_v4.py`,
`src/rationale_v3/{contracts,evidence,quality,selector,setcover,predicate_aliases,semantic_relations}.py`
and the policy file listing under `src/rationale_v3/policies/`,
`src/selection/{contracts,granularity_clean,observed_facts,lrolesim_handoff}.py`,
and the three legacy sources `src/mcq_generation.py`,
`src/build_bipartite_and_draw_ExtendedVersion.py`, `src/all_in_one.py`;
the listing of `outputs/` and of
`outputs/journal2_b2g_final_benchmark_safety_v4_2026-09-18/`.
The Okuhara sources were not read.

**Created**: this file and its `.summary.json` companion.
**Modified**: nothing. No frozen module, no runner, no output, no test, no
context file was changed; no git operation was performed.
