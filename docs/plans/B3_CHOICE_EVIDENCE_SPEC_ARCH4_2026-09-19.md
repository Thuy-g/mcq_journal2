# B3 choice–evidence architecture — normative specification (ARCH-4)

**Prompt** 8H-B3-ARCH-4 · **Date** 2026-09-19
**Branch** `journal2-b3-choice-evidence-architecture-20260918`
**Status** FROZEN SPECIFICATION — the architecture/specification freeze of the
B3 stage. It is NOT production code, NOT a publication run, NOT the adoption of
any template into the production registry, NOT the publication configuration of
the upstream v4 pipeline, and NOT the human-study preregistration manifest.
**Specification version** `choice_evidence_spec/ARCH-4/1.0.0`
**Companions** `B3_CHOICE_EVIDENCE_SPEC_ARCH4_2026-09-19.summary.json`
(machine-readable digest); `B3_ARCH4_IMPLEMENTATION_CONTRACT_2026-09-19.md`
(what the future implementation must build); `B3_ARCH4_FREEZE_MANIFEST_2026-09-19.json`
(hash of this file and of its dependencies); the decision record
`B3_HUMAN_DECISION_MEMO_2026-09-18.md` / `.json` (decisions recorded 2026-09-19).
**Basis** ARCH-1 `B3_CHOICE_EVIDENCE_FACT_SELECTION_ARCHITECTURE_2026-09-18.md`
(design), ARCH-2 `B3_CHOICE_EVIDENCE_ARCHITECTURE_ADVERSARIAL_REVIEW_2026-09-18.md`
(review), ARCH-3 `B3_DECISION_SUPPORT_MEASUREMENTS_2026-09-18.*` and ARCH-3R
`B3_PRE_FREEZE_BLOCKER_RESOLUTION_2026-09-19.*` (DEVELOPMENT measurements),
`B3_TEMPLATE_COVERAGE_EXPANSION_PLAN_2026-09-19.md`.
**Terminology authority** `docs/context/EVIDENCE_TAXONOMY_V1.md` (evidence
levels); `docs/context/PHASE_B_INPUT_CONTRACT.md` (what a v4 record contains).

---

## 0. Normative language, scope and non-scope

**0.1 Language.** MUST, MUST NOT, SHOULD and MAY are used in their normative
sense. A sentence without one of these words is explanatory. Where this
specification and an earlier ARCH document differ, this specification governs;
where this specification and `EVIDENCE_TAXONOMY_V1.md` differ on the meaning
of an evidence level, the taxonomy governs and this specification is defective.

**0.2 What is frozen here.** The formal objects of the B3 stage (§4), the
universe semantics (§5), the two exact selection problems (§6, §7), the solver
and tie-breaking protocol (§8), the presentation contract for the textual MCQ
and the post-answer choice–evidence bipartite graph (§9), the status
vocabulary (§10), the record contract (§11), the development/publication
separation and the rule for the future preregistration manifest (§12), the
baseline naming (§13), the machine-testable invariants (§14), the defaults
carried forward without a new human decision (§15), and the researcher's
recorded decisions H1–H18 (§1).

**0.3 What is not frozen here.** The production implementation
(`src/choice_evidence_v1/` does not exist yet and MUST NOT be created by the
ARCH-4 task); the upstream publication configuration (CLAUDE.md work-order step
1: candidate-validity policy, granularity-risk policy, rationale objective, M1
node budget); the production template registry version (§4.12: only the
INTERFACE and the selected direction are frozen); the benchmark Answer list and
the random seeds (§12.3: they belong to the preregistration manifest); the human
evaluation protocol text.

**0.4 Evidence status.** Every number quoted in this document is DEVELOPMENT
evidence from the 396 learner-facing development items of ARCH-3/ARCH-3R
(329 + 189 Answers, v4 offline replay). None of it is a final benchmark result
and none of it may be presented as one (§12.1).

**0.5 Standard techniques.** The 0-1 integer program, sequential (lexicographic)
optimisation, exhaustive enumeration as an oracle and minimum set cover are
standard techniques. Nothing in this specification claims to invent them.

---

## 1. Frozen decision register (researcher-approved, recorded 2026-09-19)

The researcher approved the following values through the ARCH-4 prompt. They
are recorded in `B3_HUMAN_DECISION_MEMO_2026-09-18.md` / `.json` with date
2026-09-19 and the signature field reading "researcher approved via ARCH-4
prompt; manual signature pending". No handwritten signature was forged.

| id | frozen value | where in this specification |
|---|---|---|
| H1 | the complete frozen `R*` is mandatory in the pre-answer clue set | §6.2 (C-PRE-1), §9.2 |
| H2 | separate B3 grounding vocabulary, observational only, never changes upstream evidence semantics; `ABSENCE_ONLY` never means false; `SHARED_BY_CONTAINMENT` and semantic-unavailable states explicit; `IN`/`OUT` never merge | §2, §4.6 |
| H3 | `RATIONALE_ALTERNATIVE`: OFF before answering; REQUIRED after answering wherever a showable alternative exists | §6.1, §7.2 (C-POST-3) |
| H4 | `K_A_pre = 0`, `K_A_post = 0`; no optional Answer-only fact is admitted merely to fill the graph | §6.1, §7.2 (C-POST-4) |
| H5 | T2 direction for the future production template policy; template-policy INTERFACE frozen, registry version NOT changed here | §4.12 |
| H6 | HiGHS through `scipy.optimize.milp`; exact-only publication path (`mip_rel_gap = 0`, optimal certificate required, pure-Python re-check, no greedy publication fallback) | §8 |
| H7 | N1: absolute ENTITY-node cap with node-aware pre-answer selection; `B_pre = 4`, `B_post = 7`; the pre solver reserves the immutable post-answer mandatory footprint; `B_post` counts unique right-side ENTITY nodes | §6.2 (C-PRE-4), §7.2 (C-POST-2) |
| H8a | the class/frame statement is mandatory in the textual MCQ | §9.2 |
| H8b | a `CLASS` node is retained in the post-answer graph; budget-exempt, typed, provenance-marked, not an ENTITY evidence node; affects neither `B_post`, shared information, rationale coverage nor grounding | §4.9, §9.3 |
| H9 | rarity/frequency is an annotation only; never a difficulty claim (nor is `direct_identifier`) | §4.10, §14 (I-15) |
| H10 | `A` = Answer; `B/C/D` = frozen distractor kernel position order; printed option order independently seeded, permuted and balanced across the benchmark; the post-answer graph uses the canonical A/B/C/D semantics | §4.1, §9.4 |
| H11 | a dated, hashed frozen protocol manifest before any participant data; ARCH-4 specifies when and how, and does not create it | §12.3 |
| H12 | deterministic template-based prose; optional LLM polishing is not part of the publication benchmark condition | §9.5 |
| H13 | hard constraints + strict lexicographic optimisation, every ε = 0; PRE order = ARCH-2 order; POST order = ABSENCE_ONLY incidences, risk groups, shared information, distinct keys, unique ENTITY nodes, tier cost, tokens, canonical tie-break; never a weighted sum | §6.3, §7.3 |
| H14 | grounding-clean Arm C frozen as the pre-answer admissibility rule; mandatory-only when nothing survives; template expansion is the permitted recovery, weakening open-world semantics is not | §6.1 |
| H15 | the participant protocol states that displayed facts are selected explanatory/context facts, not an exhaustive description of the four entities | §9.2, §9.3 |
| H16 | `ABSENCE_ONLY`: forbidden as a pre-answer optional clue; representable post-answer only where the explanation architecture needs it; legend/provenance-marked; never verbalized as logical falsity | §6.1, §7.1, §9.3 |
| H17 | evaluation naming distinguishes B2-literal, B2-normalised (and B2-structural if used) and every structural baseline by name; never an ambiguous "baseline" | §13 |
| H18 | `UNIVERSE_FULL` is the normal path; `N_max` bounding is not part of the default algorithm; bounding only as an explicit fallback status behind a declared resource guard, with provenance and separate reporting | §5 |

---

## 2. Two layers that MUST stay separate

**2.1 Evidence layer (upstream, frozen, read-only).** The Answer `A`, the
distractor triple `D = (d_1, d_2, d_3)` in kernel position order, the frozen
LRoleSim ranks and scores, the evidence level of every ordered pair `(f, d)`
(`NOT_COVERED` / `L0_ABSENCE_ONLY_OBSERVED` / `L1_POSITIVE_ALTERNATIVE_OBSERVED`
/ `L2_VERIFIED_EXCLUSION`), the exclusion-basis, semantic-check and
granularity-risk axes, the minimum-cardinality rationale `R*`, the selected
class and the learner-facing gate are decided upstream. The B3 stage MUST read
them as opaque attributes of the v4 record. It MUST NOT create, upgrade,
downgrade or rescue a level, MUST NOT recompute any LRoleSim quantity, MUST NOT
change `D` or `R*`, and MUST NOT write into any v4 artefact directory. LRoleSim
is applied as the frozen structural plausibility ranker whose output the v4
record already carries; nothing here extends it, and it generates no rationale.

**2.2 Presentation/selection layer (B3, this specification).** Grounding
annotations (§4.6), tiers (§4.8), the two selections (§6, §7), the textual MCQ
and the graph (§9) decide what is SHOWN and in which order, never what is TRUE
of the pinned snapshot `K` or of the world.

**2.3 Open-world rule, restated normatively.** For every choice `c`, predicate
`p` and counterpart `o`:

```
(c, p, o) ∉ K   does NOT imply   ¬p(c, o)
```

Selection and presentation MUST NOT convert snapshot absence into falsity. In
particular: no negative edge or negative sentence exists anywhere (§9.3); an
optional pre-answer clue MUST NOT rest on absence grounding (§6.1); a
post-answer `ABSENCE_ONLY` incidence MUST be legend-marked and MUST NOT be
verbalized as "does not" / "has no" (§9.3, §9.5); the paper-facing phrase is
"observed alternative value", the term for a fact observed for `A` and not for
a distractor is `observed_contrast`, and the forbidden vocabulary column of
`EVIDENCE_TAXONOMY_V1.md` §9 applies to every B3 record, prose and figure.

---

## 3. Inputs (read-only) and provenance

| input | source | B3 use |
|---|---|---|
| `AnswerCase.facts` with per-distractor levels, exclusion bases, granularity risks, R1 quality | v4 `result.case` and the frozen `candidate_fact_evidence.csv` | Answer edges, frozen levels (copied), quality |
| `Selection` after the granularity policy: `positions`, distractors with rank/score, `rationale.fact_indices`, `coverage_masks`, `evidence_policy`, `rationale_objective`, option-reference flags, `direct_identifier_flag`, local candidate-pool anonymity | v4 `outcome.selection` | `D` in kernel order, `R*`, flags |
| the rationale's own `granularity_risk_incidences` and per-pair risks | `selection.rationale` | `risk` annotations on Answer-owned groups (§4.6); the status string of `apply_granularity_policy()` MUST NOT be used (§17) |
| `mcq_evidence_level`, `has_main_l1_selection`, `learner_facing` | v4 result | the gate (§10 `CE_SKIPPED_NOT_LEARNER_FACING`) |
| `selected_class_uri`, its label, retrieval provenance, class-leak level | v4 result / run provenance | the `CLASS` frame object (§4.9) |
| `phase_b1_provenance`: `pinned_kg_sha256`, `quality_policy_sha256`, `semantic_relation_policy_sha256`, alias policy record | v4 record | provenance; the same alias policy for grouping |
| the pinned KG, loaded through `kg.loader.load_local_kg` with SHA-256 verification | runner | one-hop observed facts of the three distractors (§4.2) |
| the template registry version in force (§4.12) and the semantic relation policy | runner configuration | verbalizability, tiers, node identity, grounding |

The stage MUST make no network access. Query failure, successful zero-result and
cache hit MUST remain three distinct states in every KG or cache access.

---

## 4. Formal objects

### 4.1 Choices and letters

`C = {A, B, C, D}` is the set of the four choices. `A` is the Answer entity
by task semantics. `B`, `C`, `D` are the three distractors in the kernel's
position order (positions 0, 1, 2 of the frozen `Selection`, the bit order of
every coverage mask on the v4 record). The letter assignment MUST NOT be
permuted, seeded or randomised (H10). Letters are bound variables of the clue
text; the printed order of the four NAMES is a separate, recorded permutation
(§9.4). `D_letters = {B, C, D}`.

### 4.2 Pinned snapshot, keys, observed fact edges

`K` is the pinned DBpedia English infobox snapshot identified by
`pinned_kg_sha256`. A predicate-direction key is `κ = (p, dir)`, `dir ∈ {OUT, IN}`;
`IN` and `OUT` are two relation identities that MUST NOT be merged, MUST NOT
share a group and MUST NOT be counted as one clue or one key (H2). An
**observed fact edge** is `f = (c, κ, o)`: `(c, p, o) ∈ K` when `dir = OUT`,
`(o, p, c) ∈ K` when `dir = IN`. `o` is the **counterpart** (object of an OUT
fact, subject of an IN fact). `O_c(κ)` is the set of counterparts observed for
`c` under `κ`, produced by the frozen enumeration
(`candidate_objects_from_local_kg` + `normalize_uri`); for `c = A` the
enumeration MUST equal the identity set of the frozen `candidate_fact_evidence.csv`
(status `CE_ANSWER_ENUMERATION_MISMATCH` otherwise).

### 4.3 The frozen rationale `R*`, explanation basis, rationale absence incidences

`R* = {f_1, …, f_ρ}` is the exact minimum-cardinality rationale of the v4
record (`rationale.fact_indices`), consumed as given (H1). For each `f ∈ R*` the
record carries the frozen level `lev(f, d)` for every `d ∈ D_letters`. Derived,
never recomputed:

* `basis(d) = { f ∈ R* : lev(f, d) ∈ {L1, L2} }` — the **explanation basis** of
  distractor `d`. Under `main-l1` it is non-empty for every `d`; the adapter
  MUST assert this and refuse the item otherwise (`CE_INPUT_CONTRACT_VIOLATION`).
* `rationale_absence_incidences = |{ (f, d) : f ∈ R*, lev(f, d) = L0 }|` — a
  first-class reported metric (ARCH-2 P4). B3 cannot reduce it and MUST NOT try.
* `verbalizable(R*)` = every `f ∈ R*` has a template for its raw key under the
  registry version in force (§4.12). If false, status
  `CE_RATIONALE_NOT_VERBALIZABLE` (§10).

### 4.4 Right-side ENTITY node identity and the B3 semantic index

The B3 stage MUST build its own semantic index over the counterparts of ALL
FOUR choices, offline, from the pinned KG under the frozen semantic relation
policy, with its own cache key (`pinned_kg_sha256`, policy SHA-256, SHA-256 of
the sorted source-object list, max depth, creation command) and its own
provenance record. The index MUST be used for node identity, grounding and
containment/risk annotation only; it MUST NOT re-decide any frozen level.

A **right-side ENTITY node** is `node(o) = canonical(normalize_uri(o))`, the
index's canonical representative (redirect/equivalence) when the index covers
`o`, else the normalized URI itself; `node_identity_basis ∈ {EXACT, CANONICAL_EQUIVALENT}`
is recorded. Label-based merging MUST NOT occur. Containment does NOT merge
nodes: `Tokyo` and `Japan` are two nodes. All raw URIs of a node are recorded;
the deterministic representative is the lexicographically smallest normalized URI.

### 4.5 Fact groups, support sets, atomicity

The **family key** of a raw key is `fam(κ) = (slot(p), dir)` where `slot(p)` is
the alias family's canonical slot under the frozen alias policy of the v4 run
(else `p` itself); direction is preserved. A **fact group** (clue group) is

```
g = (fam(κ), node(o))
edges(g) = { f = (c, κ', o') : fam(κ') = fam(κ), node(o') = node(o) }
support(g) = { c ∈ C : some edge of g belongs to c }        s_g = |support(g)| ∈ {1,2,3,4}
```

A group is the unit of one clue sentence and the unit of selection. **Atomicity**:
a group is exposed whole or not at all; every edge of a selected group MUST be
drawn and every supporting letter MUST be listed in its sentence (ARCH-1 §3.4).
Exposing a strict subset of a group's edges is forbidden because it manufactures
an exhaustivity implicature the snapshot contradicts. Two groups may share a
node; a node is the unit of graph size (§7.2).

### 4.6 Grounding state per (group, choice) and the risk axis

For every group `g` and every choice `c ∉ support(g)` the stage computes a
**grounding state** and a **granularity risk**, from observations only:

```
grounding(g, c) ∈ { SHARED, SHARED_BY_CONTAINMENT, ALTERNATIVE_OBSERVED,
                    ABSENCE_ONLY, UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE }
risk(g, c)      ∈ { NONE, CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT,
                    HIERARCHY_NOT_MODELLED, UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE }
```

**Rule** (the frozen `NOT_COVERED` tests applied to a presentation pair, in this
order): if `O_c(κ) = ∅` → `ABSENCE_ONLY`, risk `NONE`; else if the index is
unavailable → `UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE`, risk `UNRESOLVED`; else if
some recorded value of `c` is exactly or canonically equal to `node(g)` → `SHARED`
(this case cannot arise for `c ∉ support(g)` and is kept for completeness); else
if some recorded value of `c` lies UNDER `node(g)` in the allowlisted containment
hierarchy (candidate-object-under-claim) → `SHARED_BY_CONTAINMENT`, risk `NONE`;
else `ALTERNATIVE_OBSERVED`, with risk `CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT` when
`node(g)` lies under a recorded value of `c`, `HIERARCHY_NOT_MODELLED` when the
relation could not be modelled, else `NONE`. `SHARED_BY_CONTAINMENT` MUST be
represented as a node–node annotation only (§9.3), never as a choice–node edge.

**Copy rule for Answer-owned groups.** For a group with an Answer edge and
`c = d` a distractor, the frozen level of the Answer fact(s) against `d`
DECIDES and is copied, not recomputed: `NOT_COVERED` → `SHARED_BY_CONTAINMENT`
(the distractor supports without owning an edge to this node); `L1`/`L2` →
`ALTERNATIVE_OBSERVED` with the worst frozen risk; `L0` → `ABSENCE_ONLY`. The
rule of the previous paragraph is still evaluated and its agreement with the
frozen value is recorded (development evidence: 282,933/282,933 pairs agree).

**Boundary.** Grounding is written into the B3 record only. It MUST NOT be
written into `levels`, fed to the kernel, or used to claim exclusion.
`ABSENCE_ONLY` is the presentation analogue of `L0`: snapshot silence, never
falsity. An unavailable index MUST NOT relabel an observed alternative as an
absence (taxonomy §5).

### 4.7 Hard screens and the EXCLUDED tier

A screened group is EXCLUDED with a reason code, never penalised:
`EXCLUDED_INELIGIBLE_<R1 reason>` (predicate/object ineligible under the quality
policy, including the hard Answer-label leak assessed against the Answer label
for EVERY choice's edges), `EXCLUDED_OPTION_REFERENCE` (node is one of the four
frozen option URIs), `EXCLUDED_SELF_LOOP`, `EXCLUDED_DUPLICATES_CLASS_NODE`.
Two pre-answer-only screens are recorded on the group and enforced by §6.1:
`PRE_EXCLUDED_UNVERBALIZABLE`, `PRE_EXCLUDED_DISTRACTOR_LABEL_LEAK` (the node
label or any raw counterpart label lexically leaks a distractor's label). A
screen MUST NOT remove an `R*` group: an `R*` group that trips a screen is
flagged (§10), never altered.

### 4.8 Tiers

Evaluated in this order for every group:

| tier | definition |
|---|---|
| `MANDATORY_RATIONALE` | some Answer edge of `g` is a fact of `R*` (identity `(p, dir, o)`); the group carries its FULL support |
| `EXCLUDED` | a §4.7 screen fired (and the group is not mandatory) |
| `RATIONALE_ALTERNATIVE` | `alt_for(g) = { d ∈ support(g) ∩ D_letters : some f ∈ R* with fam(κ_f) = fam(g) has lev(f, d) ∈ {L1, L2} } ≠ ∅` — the distractor's OBSERVED alternative value under a covering rationale key. `ALT(d) = { g : d ∈ alt_for(g) }`. A distractor `d` with `basis(d) ≠ ∅` and `ALT(d) = ∅` is an **unshowable-alternative letter** (§10 `CE_COVER_ALT_UNSHOWABLE`) |
| `OPTIONAL_CONTEXT` | every other group |

`M_R = { g : tier(g) = MANDATORY_RATIONALE }`, `N_mand = { node(g) : g ∈ M_R }`,
`K_mand = { fam(g) : g ∈ M_R }`, `L_mand = ∪_{g ∈ M_R} support(g)` (always ∋ A).
A `RATIONALE_ALTERNATIVE` group MAY have `A ∈ support(g)` (multi-valued key);
it is still drawn with its full support.

### 4.9 The CLASS-frame object

`CLASS = (selected_class_uri, class_label, provenance = remote_category_membership:<cache>, class_leak_level)`.
It is a frame object with support `C` by construction. It is NOT a fact group,
NOT an ENTITY node, has no `κ`, no grounding, no attributes and no decision
variable. It MUST appear as the frame sentence of the textual MCQ (H8a) and as
a typed, provenance-marked right node of the post-answer graph (H8b) that is
outside every budget and every key. Its label MAY carry a recorded `soft_overlap`;
B3 reports and never repairs it. The class is a `first_feasible_class` /
`requested_class`; it MUST NOT be described as optimal.

### 4.10 Group attributes (computed once, all recorded)

```
s_g     = |support(g)|                     a_g = [support(g) = {A}]      n_g = [s_g = 1]
excl_g  = [A ∉ support(g)]
t_g     = min over raw keys of g of the pedagogical tier (1 best … 3 default) in the registry version in force
verb_g  = [every raw key of g has a template in the registry version in force]
tok_g   = number of leakage tokens (minimum length 1) of the node's display label
len_g   = character length of the node's display label
abs_g   = |{c ∉ support(g) : grounding(g,c) = ABSENCE_ONLY}|
cont_g  = |{…= SHARED_BY_CONTAINMENT}|     unres_g = |{…= UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE}|
alt_g   = |{…= ALTERNATIVE_OBSERVED}|
riskP_g = |{c ∉ support(g) : risk(g,c) = CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT}|
riskU_g = |{… = HIERARCHY_NOT_MODELLED}|   riskR_g = |{… = UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE}|
risk_g  = [riskP_g + riskU_g + riskR_g > 0]
soft_g  = [R1 soft-leak flag on any edge]  dl_g = [distractor-label leak, §4.7]
rare_g  = offline pinned-KG count of other subjects/objects sharing (p, node) — ANNOTATION ONLY (H9)
```

`rare_g`, `direct_identifier_flag` and every other structural quantity MUST NOT
be described, recorded or reported as human difficulty. `direct_identifier =
True` means only local structural specificity within the candidate pool.

### 4.11 Canonical order of groups

A total order, used for variable creation, tie-breaking and record ordering:

```
( tier_rank(g), -s_g, t_g, 1 - verb_g, abs_g, a_g, n_g, tok_g, len_g,
  slot(p), dir, node(g) )        tier_rank: MANDATORY_RATIONALE 0, RATIONALE_ALTERNATIVE 1,
                                             OPTIONAL_CONTEXT 2, EXCLUDED 3
```

Group ids `g00000, g00001, …` are assigned in this order. The order is a pure
function of the universe and MUST be byte-stable across runs.

### 4.12 Verbalizability and the template-policy interface (H5)

**Interface (frozen).** The stage reads ONE template registry version, given by
`TemplatePolicyRef = (registry_path, registry_version, registry_sha256, supersedes_sha256 | null)`,
and records it on every item and in the run manifest. `verbalizable(g)`,
`t_g`, `verbalizable(R*)`, the pre-answer admissibility (§6.1) and every
rendered sentence (§9.5) are functions of that version. A template is keyed by
`(predicate, direction)` over the whole pinned KG; a template keyed by, or
added to rescue, a particular Answer, distractor or item MUST NOT exist
(I-16). An unrestricted predicate-label verbalizer (a sentence generated for a
key without a registered template) MUST NOT exist.

**Selected direction (frozen).** The future production policy follows T2 of
the template plan: the five high-impact generic templates (`battles/IN`,
`birthPlace/IN`, `deathPlace/IN`, `products/IN`, `settlementType/OUT`) are
included (Phase 1); the remaining 43 candidates currently classified
`SAFE_TO_TEMPLATE` in `template_candidates_v1.json`
(`template_candidates/1.0.0-proposal-not-production`) are the Phase-2 target;
none of the 29 `NEEDS_HUMAN_REVIEW` keys and none of the 14 `REJECT` keys is
admitted automatically.

**What is NOT claimed.** The production registry in force today is
`src/rationale_v3/policies/predicate_policy_v2.json` (73 templates, SHA-256 in
the freeze manifest). It contains none of the 48 candidates. Adoption MUST
happen in a NEW versioned registry file (`predicate_policy_v3.json` or later)
that names the version it supersedes and its SHA-256; v2 MUST NOT be edited.
Once the registry version changes, every upstream or downstream measurement
that depends on verbalizability (ARCH-3 H5/H14 audits, ARCH-3R coverage and
budget sweeps, the upstream `require-verbalizable` cost, and every B3 selection)
MUST be rerun on the new version before publication. A registry change MUST
NOT rewrite any frozen development Answer, distractor, level or `R*` result:
frozen artefacts stay as they are and a new run is a new, versioned artefact.

---

## 5. Universe semantics

**5.1 Construction.** `F` = all observed fact edges of the four choices after
the frozen enumeration; `G` = its groups (§4.5) with grounding, screens, tiers
and attributes; `G_opt = { g : tier(g) = OPTIONAL_CONTEXT }`. The construction
is deterministic, offline and fully recorded (edge, group and node counts;
excluded-by-reason counts; node-identity basis counts; index availability).

**5.2 `UNIVERSE_FULL` (normal path, H18).** Both selections MUST be solved
over the complete `G_opt`. `universe_scope = UNIVERSE_FULL` on the record.
Development evidence: every hard item (43 items with more than 800 optional
groups, up to 4,921 optional groups and 9,759 variables) solved at FULL with
an optimality certificate, median 3.6 s, maximum 73.4 s.

**5.3 Resource-guard fallback (explicit, never default).** A run configuration
MUST declare `optional_groups_guard` (frozen default 20,000 groups) and
`solve_time_limit_seconds` (frozen default 600 s per solve). Only if an item
exceeds the guard MAY the stage bound `G_opt` by stratified bounding (keep
every optional group on a node already carried by a mandatory or showable
alternative group; the top 2 per distinct family key; the top 5 per distractor
letter; then fill to `N_max = 3200` by the pre-key `(-s_g, t_g, 1-verb_g, rare_g
rarer first, len_g, canonical identity)`), with status `CE_UNIVERSE_BOUNDED_FALLBACK`,
`universe_scope = UNIVERSE_BOUNDED`, the strata and `N_max` recorded, and the
item reported separately from `UNIVERSE_FULL` items in every table. Bounding
touches `OPTIONAL_CONTEXT` only; it MUST NOT change answerability (`R*` is
complete), the alternatives, or any grounding. A solve that hits the time limit
is `CE_SOLVER_NOT_OPTIMAL` (§8.4), never a bounded re-solve of the same item.

---

## 6. Pre-answer selection `S_pre`

`S_pre = M_R ∪ P` where `P ⊆ G_opt` is the set of selected optional clue groups.
The frame sentence (§4.9) accompanies `S_pre` and is outside it.

### 6.1 Admissibility of optional groups before answering (Arm C, H14) — HARD

`g ∈ G_opt` is **pre-admissible**, `g ∈ Adm_pre`, iff ALL of the following hold
(each failing condition is recorded by its reason code):

| condition | reason code when violated |
|---|---|
| `verb_g = 1` | `UNVERBALIZABLE` |
| `a_g = 0` (`K_A_pre = 0`, H4) | `ANSWER_ONLY_K_A_0` |
| `s_g ≥ 2` | `SUPPORT_BELOW_2` |
| `abs_g = 0` (H16: no pre-answer clue rests on snapshot absence) | `ABSENCE_ONLY_LETTER` |
| `cont_g = 0` | `SHARED_BY_CONTAINMENT_LETTER` |
| `unres_g = 0` | `UNRESOLVED_INDEX_LETTER` |
| `riskP_g = 0` | `GRANULARITY_RISK_CLAIM_UNDER_CANDIDATE` |
| `riskR_g = 0` | `GRANULARITY_RISK_UNRESOLVED` |
| `riskU_g = 0` | `GRANULARITY_RISK_HIERARCHY_UNMODELLED` |
| `dl_g = 0` (no distractor-label leak; the Answer-label leak is already an EXCLUDED screen) | `DISTRACTOR_LABEL_LEAK` |
| NOT (`s_g = 3` and `A ∉ support(g)`) — no optional group with support exactly `{B, C, D}` | `A_EXCLUDING_SUPPORT_3` |

Equivalently: every non-support letter of an admissible group is
`ALTERNATIVE_OBSERVED` with risk `NONE`. `RATIONALE_ALTERNATIVE` groups are
never in `Adm_pre` (H3: OFF before answering). `EXCLUDED` groups are never in
`Adm_pre`. There is no soft version of any row: admissibility MUST be a hard
constraint, never a penalty or a key. If `Adm_pre = ∅` the item is
`CE_SELECTED_MANDATORY_ONLY` and MUST be kept as such; an inadmissible clue
MUST NOT be inserted to fill the set. Development evidence: mandatory-only
264/396 (66.7 %) under the current registry, 203/396 (51.3 %) under T2; Arm C
costs nothing beyond Arm B on this data.

### 6.2 Hard constraints

Decision variables: `z_g ∈ {0,1}` for `g ∈ Adm_pre`; `u_L ∈ {0,1}` for
`L ∈ C \ L_mand` (letters not covered by any mandatory group); `v_k ∈ {0,1}` for
`k ∈ K_free = { fam(g) : g ∈ Adm_pre } \ K_mand`; and the N1 objects
`w_h ∈ {0,1}` for `h ∈ ALT_show = ∪_d ALT(d)`, `y_o ∈ {0,1}` for
`o ∈ N_free = ({node(g) : g ∈ Adm_pre} ∪ {node(h) : h ∈ ALT_show}) \ N_mand`.

```
(C-PRE-1)  every g ∈ M_R is selected (fixed outside the model; full support; H1)
(C-PRE-2)  Σ_g z_g ≤ B_pre                                  B_pre = 4 optional clue groups
(C-PRE-3)  u_L + Σ_{g ∋ L} z_g ≥ 1        ∀ L ∈ C \ L_mand   (u_L = 1 marks an uncovered letter)
           v_k ≤ Σ_{g : fam(g) = k} z_g   ∀ k ∈ K_free       (v_k = 1 only if key k is used)
(C-PRE-4)  N1 node-aware feasibility (H7):
           y_o ≥ z_g   ∀ g ∈ Adm_pre on o;   y_o ≥ w_h   ∀ h ∈ ALT_show on o
           Σ_{h ∈ ALT(d)} w_h ≥ 1            ∀ d with ALT(d) ≠ ∅        (COVER_ALT witnesses)
           |N_mand| + Σ_{o ∈ N_free} y_o ≤ B_post                        B_post = 7
(C-PRE-5)  K_A_pre = 0: already inside §6.1 (a_g = 1 is inadmissible)
```

**Mandatory post footprint.** `M_post = N_mand ∪ W` where `W` is a node set of a
COVER_ALT witness assignment. `min_footprint(N) = min |W \ N|` over witness
assignments given already-paid nodes `N`. Pre-check: if
`|N_mand| + min_footprint(N_mand) > B_post` the item is
`CE_MANDATORY_CORE_TOO_LARGE` (development evidence: the core is at most 6
nodes over 396 items, so this cannot occur at `B_post = 7`). The witnesses
`w_h` take no part in any key: they exist so that no pre-answer clue can make
the post-answer graph nested-infeasible.

### 6.3 Exact PRE objective (H13) — strict lexicographic, every ε = 0

Minimise, in this order, then apply the canonical tie-break of §8.2:

```
k1  Σ_{L ∈ C \ L_mand} u_L                       fewer distractor letters with no admissible optional clue
k2  − Σ_g z_g · (s_g − 1)                        more shared information
k3  − Σ_{k ∈ K_free} v_k                         more distinct predicate-direction keys
k4  Σ_g z_g                                      fewer clue sentences
k5  Σ_g z_g · t_g                                lower pedagogical-tier cost
k6  Σ_g z_g · tok_g                              fewer tokens
k7  canonical tie-break (§8.2)
```

Objective version `ce_pre_keys/ARCH-4/1.0.0`. The key vector of a selection is
`key_pre(P) = (k1, …, k6)` recomputed in pure Python from `P` alone (§8.3). A
weighted sum, a scaled sum, or any ε > 0 MUST NOT be used. Adjacent-swap
variants are ablations, each a distinct versioned objective, never the method.

### 6.4 Result

`P` (canonical order), `key_pre(P)`, the solver record (§8), the N1 witness
node set `W` actually returned, and the status (§10). `S_pre = M_R ∪ P`.

---

## 7. Post-answer selection `S_post`

### 7.1 Admissible set and nesting

`Free_post = G_opt ∪ ALT_show ∪ P` (every `OPTIONAL_CONTEXT` group of the
universe, every showable alternative, and the pre-selected optional groups).
Post-answer, `ABSENCE_ONLY`, containment, unresolved, risk-bearing,
distractor-label-leaking and template-less optional groups ARE admissible
(carried forward from ARCH-2 §7.2; ordered against by k1–k2; counted; legend-
and provenance-marked in the graph, §9.3). `EXCLUDED` groups are never
admissible. `S_post = M_R ∪ Q` with `Q ⊆ Free_post`, and nesting
`P ⊆ Q` (every pre-answer clue is an edge set of the graph).

### 7.2 Hard constraints

Variables `z_g` for `g ∈ Free_post` (fixed to 1 for `g ∈ P`), `y_o` for
`o ∈ {node(g) : g ∈ Free_post} \ N_mand`, `v_k` for
`k ∈ {fam(g)} \ K_mand`.

```
(C-POST-1)  every g ∈ M_R is drawn (fixed; full support)
(C-POST-2)  y_o ≥ z_g ∀ g on o;  y_o ≤ Σ_{g on o} z_g;   |N_mand| + Σ_o y_o ≤ B_post = 7
            — B_post counts UNIQUE right-side ENTITY nodes (mandatory nodes count;
              a node shared by several groups counts once; the CLASS node never counts)
(C-POST-3)  COVER_ALT: Σ_{h ∈ ALT(d)} z_h ≥ 1   ∀ d with ALT(d) ≠ ∅          (H3)
(C-POST-4)  Σ_{g ∈ G_opt, a_g = 1} z_g ≤ K_A_post = 0                       (H4)
(C-POST-5)  z_g = 1 ∀ g ∈ P                                                   (nesting)
            v_k ≤ Σ_{g : fam(g) = k} z_g
```

Pre-check: `|N_mand| > B_post` → `CE_MANDATORY_EXCEEDS_BUDGET` (cannot occur
when the §6.2 pre-check passed; kept as an internal assertion). Under N1 the
post problem is feasible by construction; an `INFEASIBLE` status here is the
internal error `CE_NESTED_INFEASIBLE_AT_BUDGET` and MUST fail the run (§10).

### 7.3 Exact POST objective (H13) — strict lexicographic, every ε = 0

```
k1  Σ_g z_g · abs_g                              fewer exposed ABSENCE_ONLY incidences   (H16)
k2  Σ_g z_g · risk_g                             fewer granularity-risk-bearing groups
k3  − Σ_g z_g · (s_g − 1)                        more shared information
k4  − Σ_k v_k                                    more distinct predicate-direction keys
k5  Σ_o y_o                                      fewer unique ENTITY right nodes
k6  Σ_g z_g · t_g                                lower pedagogical-tier cost
k7  Σ_g z_g · tok_g                              fewer tokens
k8  canonical tie-break (§8.2)
```

Sums run over `g ∈ Free_post` (mandatory groups are constants and contribute
nothing). Objective version `ce_post_keys/ARCH-4/1.0.0`. The recomputed vector
`key_post(Q)` uses `|{node(g) : g ∈ Q} \ N_mand|` for k5. Development
evidence on the adjacent swaps: k3↔k4 changes 54/396 and k4↔k5 58/396
selections; k1↔k2 14/396; the rest ≤ 1 %.

### 7.4 Result

`Q` (canonical order), `key_post(Q)`, `S_post`, the ENTITY node set
`N_post = N_mand ∪ {node(g) : g ∈ Q}` with `|N_post| ≤ 7`, `cover_alt[d]` per
distractor, `unshowable_letters`, and the metrics of §11.

---

## 8. Deterministic tie-breaking and the exact solver protocol (H6)

**8.1 Solver.** HiGHS through `scipy.optimize.milp`, `mip_rel_gap = 0`,
single thread (`OMP_NUM_THREADS = 1`), integrality on every variable, variables
created in canonical order, rows appended in a fixed order, `presolve`
permitted, `time_limit = solve_time_limit_seconds`. The scipy and Python
versions MUST be recorded in the run manifest (development: scipy 1.17.1,
Python 3.11.15).

**8.2 Sequential lexicographic solve and the canonical tie-break.** For keys
`k1 … kn`: minimise `k_i`; if the status is not OPTIMAL stop with
`CE_SOLVER_NOT_OPTIMAL_<status>`; append the equality row `k_i(x) = opt_i`;
continue. After the last key, among the remaining optimal selections choose the
one whose 0/1 vector over the free groups in canonical order is
lexicographically LARGEST (an earlier group is taken whenever an optimal
selection containing it exists). An implementation MAY realise this block-wise
with exactly representable powers of two (the audit used blocks of 24); any
realisation MUST yield the same selection. The selected set is therefore a pure
function of the universe and the configuration; substituting another exact
solver MUST produce byte-identical records.

**8.3 Pure-Python re-check (mandatory for every solve of every item).**
Recompute from the returned selection alone: every hard constraint of §6.2 /
§7.2 (for N1: `|N_mand ∪ nodes(P) ∪ W| ≤ B_post` with the witness set `W`
actually returned — the audit's development-only slack of `+3` MUST NOT be
carried into production), and the full key vector, which MUST equal the
sequence of per-level optimal values reported by the solver. Any mismatch is
`CE_RECHECK_FAILED`.

**8.4 Publication path is exact-only.** In publication mode every solve of
every published item MUST have status OPTIMAL at every level and pass §8.3.
Otherwise the item is NOT published, its status is counted in the run
manifest, and the runner exits non-zero. A greedy or heuristic selection MUST
NOT be substituted, flagged or otherwise; greedy is structural baseline B3
only, run separately into its own output (§13).

**8.5 Exhaustive oracle.** For every item whose free-group count is at most 16
(pre: `|Adm_pre|`; post: `|Free_post|`), an exhaustive enumeration over subsets
MUST reproduce the solver's selection (key vector and canonical choice). The
test suite MUST include such instances. Development evidence: 389/389 pre and
34/34 post oracle agreements.

**8.6 Determinism test.** Two runs on identical inputs MUST produce
byte-identical item records (timing fields excluded).

---

## 9. Presentation contract

### 9.1 Two exposures

Before answering the participant receives the textual MCQ of §9.2 and the four
NAMES as options; no graph, no names attached to letters, nothing that reveals
`A`. After answering the participant receives the bipartite graph of §9.3 and
the explanation prose of §9.5. Both are derived from the same universe and the
same nested selections, so the graph can never contradict the clues.

### 9.2 Textual MCQ (pre-answer)

1. The frame sentence (H8a): "A, B, C, and D are all <class label>." — with
   its remote provenance stated once in the protocol, not per item.
2. One sentence per group of `S_pre` in canonical order, each rendered by the
   registered template of its raw key, listing EVERY supporting letter
   (atomicity). `R*` sentences follow ARCH-2 P1: positive Answer-attribute
   phrasing from the fact's own template; no exclusivity marker ("only A",
   "unlike B, C and D"); no negative clause about any letter. A conjunctive
   rendering of several `R*` facts about `A` is permitted (P6).
3. The question "Who is A?" and the four names in the printed order of §9.4.
4. The protocol instruction (H15), fixed text in the preregistered protocol:
   the listed facts are selected explanatory/context facts recorded in the
   knowledge source, not an exhaustive description of the four entities; a
   letter that is not listed for a fact may also have that property.

### 9.3 Post-answer choice–evidence bipartite graph

```
G_ce = (C ∪ N_post ∪ {CLASS}, E_post)
Left column   : A, B, C, D  — A is the Answer, B/C/D the distractors, in that fixed order;
                labels "A (Name)" … after answering.
Right column  : the ENTITY nodes N_post (|N_post| ≤ 7) and the CLASS node (typed CLASS,
                provenance remote_category_membership, drawn apart from the ENTITY nodes).
Edges         : one edge per observed fact edge f = (c, κ, o) of every group in S_post,
                drawn c → node(o) when dir = OUT and node(o) → c when dir = IN, labelled with
                the raw predicate identifier and, where a template exists, its registered short
                relation label; carrying role ∈ {MANDATORY_RATIONALE, RATIONALE_ALTERNATIVE,
                OPTIONAL_CONTEXT}, provenance pinned_kg:<sha256>, and for Answer edges the
                copied frozen levels; plus one CLASS_FRAME edge c → CLASS for every c ∈ C.
```

Rules. (i) Every drawn edge MUST be an observed triple of `K` under its raw
key (or the CLASS_FRAME edge with its own provenance). No negative edge, no
"does not have" edge, no node manufactured from absence, no left node outside
`C`, no edge under an EXCLUDED group. (ii) Atomicity: all edges of a selected
group are drawn. (iii) A `SHARED_BY_CONTAINMENT` relation is a node–node
annotation (e.g. Higashiōsaka ⊂ Japan) and MUST NOT be drawn as a choice–node
edge. (iv) An `ABSENCE_ONLY` incidence is a MISSING edge; the legend MUST state:
"an edge is a fact recorded in the pinned snapshot; a missing edge means the
snapshot records nothing, not that the fact is false"; the exposed
`ABSENCE_ONLY` count is recorded per item (H16). (v) The `CLASS` node MUST NOT
be an ENTITY node, MUST NOT count toward `B_post`, and MUST NOT enter any key,
grounding or coverage quantity; deleting it changes no selection (H8b). (vi)
Shared nodes are preferred through k3 of §7.3, but a right node is NOT required
to connect to all four choices; `R*` nodes are typically Answer-only. (vii) A
node's raw URIs and identity basis are recorded; the deterministic representative
labels it. (viii) The graph balances compactness (k5), shared information (k3),
predicate-direction diversity (k4), educational usefulness (k6, COVER_ALT),
answer-leakage control (no optional Answer-only group, H4) and open-world
safety (k1, k2, legend) exactly in the priority order of §7.3.

### 9.4 Printed option order (H10)

Scheme `ce_option_order/BLOCK_BALANCED_4/1.0.0`. The items of a benchmark run
are sorted by their canonical `item_key`; consecutive blocks of four items are
formed; for each block `b` a permutation `π_b` of the printed positions
`{1,2,3,4}` is drawn from a deterministic generator seeded from
`(benchmark_seed, b)`; the `i`-th item of the block prints the Answer at
position `π_b[i]` (a final partial block uses the prefix of `π_b`). The three
distractors fill the remaining positions in a deterministic order drawn from a
generator seeded from `(benchmark_seed, item_key)`. Across every complete block
each printed position holds the Answer exactly once. The record MUST carry
`option_order` (four URIs in printed order), `answer_printed_position`,
`scheme`, `benchmark_seed`, `block_index`. The post-answer display MUST reuse
the same printed order for the names and MUST use the canonical letters
`A/B/C/D` for the graph. `benchmark_seed` is fixed in the preregistration
manifest (§12.3), not here.

### 9.5 Explanation prose (H12)

Deterministic and template-based: for each distractor `d` the explanation
cites exactly `basis(d)` (the `R*` facts covering `d` at ≥ L1) rendered as
positive statements about `A`, and `d`'s drawn observed alternative value under
the covering key (ARCH-2 P2), phrased as an observation about the snapshot. It
MUST NOT cite an `R*` fact for which `d` is `L0`, MUST NOT say "the snapshot
records no X for d" to a learner, and MUST NOT use any forbidden phrasing of
the taxonomy. A group without a template gets no sentence (its edge is drawn
with the raw predicate identifier). LLM polishing MUST NOT be part of the
publication benchmark condition; if ever used it is a separate later arm with
its own grounding audit.

---

## 10. Status and failure vocabulary (`ce_status/ARCH-4/1.0.0`)

| status | meaning | published in the benchmark? |
|---|---|---|
| `CE_SELECTED` | both selections found; at least one optional group in `S_pre` | yes |
| `CE_SELECTED_MANDATORY_ONLY` | `Adm_pre = ∅` or the exact pre optimum selects no optional group; graph still solved | yes (flagged, counted) |
| `CE_SKIPPED_NOT_LEARNER_FACING` | v4 item is MCQ-L0, carries no selection, or is not learner-facing | no |
| `CE_RATIONALE_NOT_VERBALIZABLE` | some `f ∈ R*` is without a template under the registry version in force; no clue text; graph MAY be produced for diagnostics | no (until the registry version or the upstream policy resolves it; §17) |
| `CE_RATIONALE_OPTION_REFERENCE_CONFLICT` | `R*` names a printed option (counted upstream); never repaired here | as the publication configuration decides; flagged |
| `CE_MANDATORY_CORE_TOO_LARGE` | `|N_mand| + min_footprint > B_post` (pre-check) | no |
| `CE_MANDATORY_EXCEEDS_BUDGET` | `|N_mand| > B_post` (post pre-check; internal assertion) | no |
| `CE_COVER_ALT_UNSHOWABLE` | some distractor has `basis(d) ≠ ∅` and `ALT(d) = ∅`, with reason per letter (`L2_NO_ALTERNATIVE`, `ALL_ALTERNATIVES_SCREENED_<screen>`, `NONE_IN_PINNED_KG`) | yes, flagged and counted; the preregistration manifest MUST state the count |
| `CE_UNIVERSE_BOUNDED_FALLBACK` | the resource guard fired; stratified bounding used (§5.3) | yes, scope recorded, reported separately |
| `CE_SEMANTIC_INDEX_UNAVAILABLE` | the B3 index could not be built/loaded; affected pairs are `UNRESOLVED` (never absence) and inadmissible pre-answer | yes, recorded |
| `CE_SOLVER_NOT_OPTIMAL_<status>` | a solve returned no optimality certificate (time limit, iteration limit, other) | no; counted in the manifest; non-zero exit |
| `CE_RECHECK_FAILED` | the pure-Python re-check of §8.3 disagreed with the solver | no; non-zero exit |
| `CE_NESTED_INFEASIBLE_AT_BUDGET` | the post solve is infeasible — impossible under N1; internal error | no; non-zero exit |
| `CE_NESTING_VIOLATED` | `P ⊄ Q` — internal error | no; non-zero exit |
| `CE_ANSWER_ENUMERATION_MISMATCH` | the frozen CSV identity set differs from the pinned-KG enumeration of `A` | no; input-contract error |
| `CE_INPUT_CONTRACT_VIOLATION` | a distractor is not in the pinned KG, `basis(d) = ∅` for a `main-l1` item, or another v4 contract breach | no; error |

`CE_SOLVER_*_GREEDY_USED` MUST NOT exist. Statuses are additive flags where
the table says "flagged"; the primary status is the first applicable row from
the top.

---

## 11. Record contract (summary; the implementation contract has the schema)

One JSON record per item, `schema_version = choice_evidence_v1/1.0.0`, carrying:
identity and gate; `letters` (A/B/C/D → URIs) and the printed-order block of
§9.4; `universe` (scope, counts, index provenance); `groups` with key, raw keys,
node, support, tier, `alt_for`, grounding per non-support letter, risk,
attributes, screens, template id; `edges` with provenance and copied frozen
levels; `rationale` (`R*` facts, `explanation_basis`, `absence_incidences`,
`fully_verbalizable`); `pre_answer` (`B_pre`, `K_A_pre`, `Adm_pre` size,
selected groups, key vector, N1 witness nodes, solver record, status);
`post_answer` (`B_post`, `K_A_post`, selected groups, key vector, ENTITY node
set, `cover_alt`, unshowable letters, solver record, status); `graph` (left,
right with kinds and provenance, edges with roles and orientation, legend
text); `flags`; `provenance` (spec version, objective versions, status
vocabulary version, `TemplatePolicyRef`, `pinned_kg_sha256`, semantic index
cache key, solver name and version, git commit); `statuses`. Batch outputs:
`choice_evidence_items.jsonl`, `choice_evidence_metrics.json`,
`choice_evidence_summary.csv`, `run_manifest.json`.

---

## 12. Development versus publication

**12.1** ARCH-1 to ARCH-3R results are DEVELOPMENT evidence. They MUST NOT be
presented as final benchmark results, MUST NOT be pooled with them, and MUST be
labelled "development (329 + 189 Answers, v4 offline replay)" wherever quoted.

**12.2 Order of work (binding).** (1) Record the upstream publication
configuration (CLAUDE.md step 1). (2) Repair the two upstream publication
blockers of §17 in new versioned code. (3) Adopt the production template
registry version (§4.12) as a new file. (4) Implement `src/choice_evidence_v1/`
under the implementation contract; its tests pin this specification. (5) Rerun
the upstream pipeline on the frozen publication configuration (a new runner
generation), then B3 on its output. (6) Create the preregistration manifest
(§12.3). (7) Collect human data. No tuning of ARCH-4 objectives, budgets,
admissibility rules or templates from the final human-study responses is
allowed; any change after (6) is a new specification version and a new study.

**12.3 The frozen protocol manifest (H11).** It MUST be created after step (5)
and before step (7), as a dated, hashed file pair under `docs/protocol/`
(`B3_HUMAN_STUDY_PREREGISTRATION_<date>.json` + `.md`), and it MUST contain: the
exact code commit (git SHA) and the SHA-256 of every protected module and of
the B3 package; the pinned KG digest; the template-policy version and SHA-256
(`TemplatePolicyRef`); this specification's version and SHA-256 (from the
freeze manifest); the benchmark Answer list with its SHA-256; `benchmark_seed`
and the option-order scheme; the evaluation protocol (materials, the H15
instruction text, the legend text, measures, rater instructions, the statement
that the human test set was never read during development); the counts of every
flagged status. It MUST be signed by the researcher. A change after a
development-only pilot is permitted ONLY before this manifest exists and MUST
be recorded as a new specification version. The ARCH-4 freeze manifest is NOT
this document and MUST NOT be presented as it.

---

## 13. Baselines and naming (H17)

| name | object | may a human see it? |
|---|---|---|
| **B2-literal** | the historical implementation (`src/mcq_generation.py`, `src/build_bipartite_and_draw_ExtendedVersion.py`, `src/all_in_one.py`): live SPARQL, non-deterministic picks, absence read as contrast | reported as NOT reproducible; kept outputs shown qualitatively with their date only |
| **B2-normalised** | the offline, deterministic reimplementation with a replacement table (the fixed-`A` row withdrawn — it was correct) | yes, in its own arm |
| **B2-structural** (optional) | B2-normalised keeping absence-as-contrast, for the count of `L0` pairs the legacy logic would expose | never |
| **B0 rationale-only** | class + `R*` + COVER_ALT, nothing else | yes |
| **B1 sorted-cut** | all admissible shared groups by `(-s_g, t_g, canonical)` cut at the budget | yes |
| **B3 greedy** | greedy over the same keys; the method-agreement comparator | never as the selection of the method arm |
| **M (method)** | this specification | yes |

The word "baseline" MUST always be qualified by one of these names.

---

## 14. Machine-testable invariants and their oracles

| id | invariant | test oracle |
|---|---|---|
| I-01 | upstream immutability: copied fields (`answer_uri`, distractor URIs and positions, `R*` identities, levels, class) equal the v4 record; v4 artefact `SHA256SUMS` and the protected-module hashes are unchanged after a run | hash comparison before/after a batch run; `tests/test_pipeline_graph_lrolesim.py` extended to the B3 package |
| I-02 | IN/OUT separation: no group contains raw keys of two directions; `(p, IN, x)` and `(p, OUT, x)` are two groups | synthetic universe with both keys on one node |
| I-03 | `letters["A"] == answer_uri` for every item | schema test over a batch |
| I-04 | `letters[B,C,D]` equal the frozen selection's distractors at positions 0,1,2 | schema test over a batch |
| I-05 | full `R*` pre-answer inclusion: every `R*` fact's group ∈ `S_pre` with all its edges | record test |
| I-06 | no pre-answer `ABSENCE_ONLY` optional: `abs_g = 0` for every `g ∈ P` | record test |
| I-07 | Arm-C admissibility: every `g ∈ P` satisfies every row of §6.1 | record test recomputing the rows |
| I-08 | alternatives post-answer only: no `RATIONALE_ALTERNATIVE` group in `P`; for every `d` with `ALT(d) ≠ ∅` some `ALT(d)` group in `Q` | record test |
| I-09 | `K_A_pre = K_A_post = 0`: no optional Answer-only group in `S_pre` or `S_post` | record test |
| I-10 | N1 budget safety: `|N_mand ∪ nodes(P) ∪ W| ≤ B_post` with the returned witnesses; the post solve never returns INFEASIBLE | record test + run-level assertion |
| I-11 | `|N_post| ≤ 7` counting ENTITY nodes only | record test |
| I-12 | CLASS budget exemption: the CLASS node is not in `N_post`; no solve has a CLASS variable; deleting the node changes no key value | unit test on the model builder; record test |
| I-13 | nesting `P ⊆ Q`; every pre clue's edges are drawn | record test |
| I-14 | deterministic final tie: byte-identical reruns; oracle equality on small instances; canonical-order maximality | determinism test; §8.5 oracle test |
| I-15 | no human-difficulty inference: no record field, prose or figure text equates `rare_g`, `direct_identifier` or any structural count with difficulty; `direct_identifier_note` carries the fixed text | vocabulary grep over records, prose and paper text |
| I-16 | no Answer-specific template: every template in the registry version is keyed by `(predicate, direction)`; no template id or condition names an entity URI | registry schema test |
| I-17 | explicit registry/version provenance on every record and manifest (`TemplatePolicyRef`, spec version, objective versions, KG digest, index cache key, solver version, git commit) | schema test + manifest cross-check |
| I-18 | exact-only publication: every published item has OPTIMAL at every level and `verified = true`; a forced non-optimal solve yields a non-zero exit | run-level test with an injected time limit of 0 |
| I-19 | every drawn edge is an observed triple of `K` under its raw key (CLASS_FRAME edges excepted, with their own provenance) | pinned-KG membership test |
| I-20 | atomicity: all edges of every selected group are drawn; no group is partially exposed | record test |
| I-21 | `ABSENCE_ONLY` never verbalized as falsity; no negation template exists; forbidden phrasing absent from generated prose | registry test + prose grep |
| I-22 | explanation basis: the prose for `d` cites only `basis(d)` and `d`'s drawn alternative | prose test against the record |
| I-23 | printed option order balanced: in every complete block of four items the Answer positions are a permutation of {1,2,3,4}; the recorded seed reproduces the order | batch test |
| I-24 | `UNIVERSE_FULL` unless the declared guard fired; a bounded item carries `CE_UNIVERSE_BOUNDED_FALLBACK`, its strata and `N_max` | record test |

---

## 15. Defaults carried forward without a new human decision

These are ARCH-1/ARCH-2 defaults that ARCH-3/ARCH-3R measured and that no H
decision overrides. They are listed so the researcher sees them; changing any
of them is a new specification version.

| default | source |
|---|---|
| post-answer admissibility includes template-less, distractor-label-leaking, containment, unresolved and risk-bearing optional groups (ordered against and counted) | ARCH-1 §11.1, ARCH-2 §7.2 |
| the exclusion screens of §4.7, including the Answer-label hard leak assessed for every choice's edges | ARCH-1 §5.2 |
| alias-family grouping with direction preserved; raw predicate kept and printed | ARCH-1 §3.6 |
| canonical order of §4.11 | ARCH-1 §13.1 |
| tier evaluation order MANDATORY → EXCLUDED → ALTERNATIVE → OPTIONAL | ARCH-3 universe builder |
| `tok_g` = leakage-token count of the node label; `len_g` = label length | ARCH-3 |
| the exhaustive-oracle threshold of 16 free groups | ARCH-3 |
| stratified-bounding strata (node-sharing, top 2 per key, top 5 per letter) and `N_max = 3200` for the guard fallback only | ARCH-2 C9, ARCH-3R §6 |
| resource guards: 20,000 optional groups; 600 s per solve | this document (no development item reached either) |

---

## 16. Adversarial self-check (performed before declaring frozen)

| check | result | evidence |
|---|---|---|
| hidden weighted sums | PASS | §6.3/§7.3 are sequential exact minimisations with equality rows; the only weights are the canonical-block powers of two, which realise a lexicographic order over 0/1 vectors and enter no key |
| conflicting budgets | PASS | `B_pre` counts optional clue GROUPS (4); `B_post` counts unique ENTITY NODES (7); N1 links them in one direction only (C-PRE-4); the mandatory core (≤ 6 measured) fits |
| a route that exposes `ABSENCE_ONLY` pre-answer | PASS | §6.1 row `abs_g = 0` is hard; `R*` groups can carry an `L0` distractor but are rendered by P1 as positive Answer statements with full support and never as contrast; the H15 instruction cancels the implicature |
| a route that makes missing KG edges false | PASS | §2.3, §9.3 (iv), §9.5; no negation template (I-21); `UNRESOLVED` never downgraded to absence |
| CLASS accidentally consuming the ENTITY budget | PASS | §4.9: no variable, no node in `N_free`/`N_post`; I-12 |
| ambiguity between group count and node count | PASS | every budget and key names its unit; k5 of §7.3 is `Σ y_o` with two-sided linking; `B_post` is defined on `N_post` |
| an implementation path that can recreate nested infeasibility | PASS (after one tightening) | C-PRE-4 with COVER_ALT witnesses; the audit's re-check slack `+3` is explicitly forbidden in §8.3; `CE_NESTED_INFEASIBLE_AT_BUDGET` is an internal error, not a status an item may carry |
| verbalizability silently changing frozen upstream data | PASS | §4.12: registry change → new file, new version, rerun; frozen artefacts untouched; `CE_RATIONALE_NOT_VERBALIZABLE` never alters `R*` |
| any Answer-specific special case | PASS | no template, screen, tier or key mentions an entity; I-16 |
| mismatch between the decision memo and this specification | PASS | the memo's recorded values (2026-09-19) are the §1 register verbatim; the summary JSON and the memo JSON carry the same frozen parameters (checked by the ARCH-4 task) |

---

## 17. Blockers carried forward

**Before production implementation (`src/choice_evidence_v1/`).**
1. The researcher's manual signature on the decision memo (recorded via the
   ARCH-4 prompt; signature pending). Implementation MAY start on the recorded
   values; publication MUST NOT.
2. The decision whether B3 may be implemented before the final benchmark run
   (memo closing line) — not decided by ARCH-4.
3. The implementation contract's test plan MUST be in place before any solver
   code (I-01 … I-24 map to named tests).

**Before the final publication benchmark.**
1. **Upstream publication configuration not recorded** (CLAUDE.md step 1:
   candidate-validity policy, granularity-risk policy, rationale objective, M1
   node budget).
2. **`granularity_clean` report-only status defect** (ARCH-1 §20):
   `apply_granularity_policy()` returns `STATUS_NO_RISK_PRESENT` under
   `report-only` with a non-zero incidence count. B3 reads the count, never the
   status string; the fix belongs to a NEW versioned module/runner generation
   and MUST land before the publication run.
3. **Main-L1 / unverbalizable contradiction** (ARCH-1 §20; H5):
   `PHASE_B_INPUT_CONTRACT.md` §3.2 bars a template-less fact from the main
   corpus while the kernel only orders on it (key 9); 176/396 development items
   carried a template-less `R*` fact (46/396 would remain under T2). Resolution
   = the production registry version (§4.12) plus a versioned
   `require-verbalizable` policy in a new runner generation, or exclusion with a
   reported yield; the publication configuration MUST record which.
4. Every verbalizability-dependent measurement rerun on the frozen
   configuration and registry version (§4.12).
5. The preregistration manifest of §12.3.
6. **Pre-existing protected-source pin failure** (found by the ARCH-4 checks,
   not caused by ARCH-4): `tests/test_pipeline_graph_lrolesim.py::TestProtectedSources::test_protected_source_is_unmodified[src/MCQ_lrolesim.py-a286fe08…]`
   fails because the on-disk, git-untracked, archive-only reference file
   `src/MCQ_lrolesim.py` hashes to `5214aeb7ccaf427dc784ab78cbb26dab1f7422a82a28a66407fbbf7c8059c2d6`
   while the test pins `a286fe08719a6a049638548aee7526c069b3fec2ab621bec8d540059d3f03617`
   (rebaselined 2026-08-12, Prompt 8H-B1.5-R1). The EXECUTED LRoleSim kernel
   `src/MCQ_lrolesim_ClaudeWeb_v2.py`, `src/lrolesim/adapter.py`,
   `src/kg/graph_view.py`, `src/kg/loader.py` and the classes modules pass
   their pins (130 passed, 1 failed). ARCH-4 did not touch the file. The
   mismatch MUST be explained, and either the archive bytes restored or the
   pin re-audited in a new dated source-pin audit, before the publication
   benchmark.

Neither upstream defect, nor the archive-only pin failure, blocks this
specification freeze: none of them changes a frozen object of §4–§9.

---

## 18. Package preflight, files and checks of the ARCH-4 task

**Package preflight (measured on the LOCAL archives, 2026-09-19).**

| archive | external digest matches | entries (expected) | directory entries (`ZipInfo.is_dir`) | `testzip()` | CONTENT_MANIFEST | in-zip vs manifest |
|---|---|---|---|---|---|---|
| `outputs/journal2_b3_decision_support_2026-09-18.zip` | yes (`8666a336…c2bd`) | 8346 (8346) | 0 | None | present | 8343 in-zip regular files + 3 manifest files; 10 excluded paths declared and absent |
| `outputs/journal2_b3_pre_freeze_resolution_2026-09-19.zip` | yes (`be9e9928…da57`) | 465 (465) | 0 | None | present | 462 + 3; 0 excluded |

Both LOCAL archives pass; no package stage was rerun and no measurement was
recomputed. The transferred copy that failed elsewhere was a re-packed wrapper,
not the repository archive. Hardening applied: `build_package()` in
`scripts/audit_b3_choice_evidence_decisions.py` and `stage_package()` in
`scripts/audit_b3_pre_freeze_resolution.py` now MEASURE
`directory_entries_in_zip` from `ZipInfo.is_dir()` instead of assuming 0 or
copying the manifest value (verification code only; no measurement code
touched; both scripts compile; pre- and post-edit SHA-256 in the freeze manifest).

**Tests and checks actually run by the ARCH-4 task**:
`python -m pytest -q tests/test_pipeline_graph_lrolesim.py` → 130 passed,
1 failed (the pre-existing `src/MCQ_lrolesim.py` pin failure of §17, not
caused by this task; every other protected pin passes);
`python -m py_compile` on both patched audit scripts (pass); `json.load` on
every JSON deliverable (pass); memo-JSON versus summary-JSON frozen-parameter
equality (pass); forbidden-vocabulary scan of every created/modified document
(no hit in ARCH-4 text; the remaining hits are the unchanged 2026-09-18 memo
prose quoting the inference to be avoided); `git status` / `git diff --stat`
(only the files listed below). Tests not run: no other suite applies, because
no production source was created; no measurement stage was rerun.

**Files created**: this specification; its `.summary.json`;
`B3_ARCH4_IMPLEMENTATION_CONTRACT_2026-09-19.md`; `B3_ARCH4_FREEZE_MANIFEST_2026-09-19.json`.
**Files modified**: `B3_HUMAN_DECISION_MEMO_2026-09-18.md` / `.json` (decisions
recorded, no signature forged); the two audit scripts (verification lines only).
**Not touched**: every frozen module, every v1–v4 output, every cache, the
production template registry, the legacy sources, git state (no add/commit/push/
reset/clean/checkout/branch).
