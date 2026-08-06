# Evidence Taxonomy V1 — authoritative terminology for Journal 2

**Status** AUTHORITATIVE, frozen 2026-08-06
**Supersedes** the evidence-level names in `docs/audits/AUDIT_Journal2_v2_2026-07-26.md`
(see `docs/audits/TAXONOMY_SUPERSESSION_20260806.md`)
**Applies to** all future Journal-2 code, prompts, audits and paper text

This file is the single authority on what an evidence level means. Code,
prompts and paper text must cite this file. They must not infer evidence
definitions from the July 26 audit, from Prompt 8E/8F/8F-R1 report prose, or
from identifier names in any implementation.

---

## 0. Setting and notation

Let `K` be a **pinned DBpedia English infobox snapshot**. Everything below is a
statement about `K` and about nothing else.

| Symbol | Meaning |
|---|---|
| `A` | the Answer entity |
| `d` | a distractor candidate |
| `p` | a predicate (a DBpedia infobox property) |
| `dir` | the direction, `OUT` (subject is the entity) or `IN` (object is the entity) |
| `κ = (p, dir)` | a **predicate-direction key**. `IN` and `OUT` are never merged. |
| `o` | the Answer's counterpart under `κ`, called the **claim object** |
| `O_d(κ)` | the set of objects observed for `d` under `κ` in `K` |
| `f = (A, κ, o)` | one **Answer fact**, the unit that may enter a rationale |

The **Answer proposition** of `f` is the assertion that the entity stands in
relation `κ` to `o`. A candidate **supports** the proposition when `K`, read
through the checked semantic index, records that the candidate also stands in
that relation.

An evidence level is always a property of the ordered pair `(f, d)` — it says
how the fact `f` distinguishes `A` from the candidate `d`. It is never a
property of `f` alone.

---

## 1. `NOT_COVERED`

**Definition.** The candidate **supports** the Answer proposition, through any
of:

1. **exact object equality** — `o ∈ O_d(κ)`;
2. **trusted canonical/redirect equivalence** — some `o′ ∈ O_d(κ)` is a
   canonical/redirect equivalent of `o` under a trusted, offline-verified
   equivalence entry;
3. **candidate-object-under-claim semantic entailment** — some `o′ ∈ O_d(κ)`
   lies under `o` in an allowlisted containment hierarchy, so asserting `o′`
   entails the Answer proposition.

**Consequence.** The fact **does not distinguish that candidate**. It covers
nobody at that position and contributes no bit to any coverage mask.

**Ordering.** `NOT_COVERED` is tested **before** `L0`, `L1` and `L2`. A fact the
candidate supports can never be re-read as absence or as contrast.

**Direction of the semantic test.** Only *candidate-object-under-claim* removes
contrast. The reverse containment (`claim object under candidate object`, e.g.
the Answer says *Tokyo* and the candidate says *Japan*) does **not** make the
fact `NOT_COVERED`, and it does **not** make it `L1` either: it is a recorded
**granularity risk**, handled on a separate axis (§5).

---

## 2. `L0_ABSENCE_ONLY_OBSERVED`

**Definition.** `O_d(κ) = ∅`. The pinned snapshot records **no object at all**
for the candidate under the same predicate and the same direction.

**What L0 is.** Snapshot **absence / non-support** only.

**What L0 is not.**

* It is **not negation**. It does not assert `¬p(d, o)`.
* It is **not real-world exclusion**. DBpedia infobox coverage is
  incomplete; a missing infobox row is a documentation gap far more often
  than it is a fact about the world.
* It is **not evidence a student may be shown as a reason.** L0 is a
  diagnostic level: it supports yield reporting and failure analysis, and it
  must not appear in a rationale presented as justification.

**Correct phrasing.** "The snapshot records no `almaMater` for `d`."
**Forbidden phrasing.** "`d` did not attend `o`." / "`d` has no alma mater."

---

## 3. `L1_POSITIVE_ALTERNATIVE_OBSERVED`

**Definition.** `O_d(κ) ≠ ∅` **and** the candidate does **not** support the
Answer proposition in the checked semantic index. That is, the candidate has at
least one **observed alternative value** under the same predicate and the same
direction, and none of its observed values is `o`, a trusted equivalent of `o`,
or an entity lying under `o`.

**Authoritative name.** `L1_POSITIVE_ALTERNATIVE_OBSERVED`.

**Preferred prose wording.** **observed alternative value**.

> **Do not** use `POSITIVE_VALUE_CONTRAST`, and do not use the bare phrase
> "positive contrast", as the authoritative L1 name. The July 26 audit used
> "positive contrast" for a **different and strictly stronger** level: an
> observed alternative **plus** a functionality requirement on the predicate.
> Reusing that phrase for V1's L1 would silently claim the functionality
> guarantee that V1's L1 does not have. See
> `docs/audits/TAXONOMY_SUPERSESSION_20260806.md`.

**What L1 establishes.** That the snapshot records a *different, positively
observed* value for the candidate under the same key. This is a genuine
observation about `K`, not an inference from absence, and it is the weakest
level that may be shown to a student as a reason.

**What L1 does not establish.** L1 does **not** establish that the predicate
cannot also hold the Answer's object for that candidate. Many DBpedia infobox
properties are **multi-valued** (`almaMater`, `influences`, `knownFor` all are).
For such a key, `o ∉ O_d(κ)` observed alongside some `o′` is consistent with
`p(d, o)` being true in the world and merely unrecorded.

**Correct phrasing.** "The snapshot records `Tokyo Institute of Technology` as
Hideki Shirakawa's `almaMater`, and does not record `University of Tokyo`."
**Forbidden phrasing.** "Shirakawa did not attend the University of Tokyo."

**Level and strength are separate axes.** The *level* is decided by the
observation alone. How strong an exclusion argument the observation licenses is
recorded independently as `exclusion_basis ∈ {NONE, SCOPED_EMPIRICAL,
FORMAL_PROOF}`. No annotation may move a fact between L0 and L1, and no
annotation may substitute for evidence.

---

## 4. `SCOPED_EMPIRICAL` — an annotation, not a level

**`SCOPED_EMPIRICAL` is not a fourth evidence level.** There are exactly three
reported levels plus `NOT_COVERED`.

**Definition.** An optional annotation attached to an **existing L1**, recording
that the predicate-direction key `κ` was empirically observed to be
**single-valued within an explicitly named local scope**, with:

* `observed_support ≥` a declared minimum;
* `maximum_observed_canonical_cardinality ≤ 1`;
* `observed_violation_count = 0`;
* an explicitly recorded scope identifier and scope kind.

**Scope.** In the R1 pilot the scope is *the Answer plus the complete ranked
candidate pool of the Prompt-8C selected class* — a local, empirical scope. The
annotation says nothing about the predicate outside that pool, and nothing about
DBpedia as a whole.

**It is not universal functionality.** DBpedia infobox properties carry no
`owl:FunctionalProperty`, maximum-cardinality, disjointness or negative-assertion
declarations that could be trusted offline. An empirical single-valued
observation over a few dozen entities is a *description of the sample*, never an
ontological guarantee. It must never be written up as "the predicate is
functional".

**Permitted role.** Ordering only. In R1 the annotation count enters the
rationale ranking key **after** the whole evidence-level profile, so it may
order two equally strong rationales and can never create, upgrade or rescue a
level.

**Permitted combinations.** `L0 + SCOPED_EMPIRICAL` is invalid.
`L2 + NONE` is invalid. These must stay machine-checked.

---

## 5. Separate axes that are not levels

These are recorded alongside the level and must never be folded into it.

| Axis | Values | Meaning |
|---|---|---|
| `exclusion_basis` | `NONE` / `SCOPED_EMPIRICAL` / `FORMAL_PROOF` | how strong the exclusion argument is, given the level |
| `semantic_check_status` | `CLOSURE_RAN` / `SEMANTIC_INDEX_UNAVAILABLE` / `NOT_APPLICABLE_NO_OBSERVED_OBJECT` | whether the semantic index was consulted |
| `granularity_risk` | `NONE` / `CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT` / `UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE` | whether an apparent contrast may be a granularity mismatch |

**Rule.** An unavailable semantic index must **not** relabel an observed
alternative value as an absence. It records `UNRESOLVED`, which is ordered
against and may block main-corpus eligibility, while leaving the observation
itself intact.

---

## 6. `L2_VERIFIED_EXCLUSION` — formally defined, deferred

**Definition.** `L2` holds for `(f, d)` only when a **machine-checkable
`EvidenceProof`** exists deriving that the candidate cannot stand in relation
`κ` to `o`. A proof record must carry, at minimum:

* explicit **premises**, each traceable to a cited, trusted source;
* the **conclusion** in the same `(d, κ, o)` vocabulary;
* an **ontology source** identifier for every axiom used;
* the **rule** applied, from a closed, versioned rule set.

Admissible premise classes, when and only when a trustworthy source supplies
them: declared functionality or maximum cardinality on `κ`; declared class
disjointness; an explicit negative assertion; a verified temporal
incompatibility carrying real qualifiers.

**Status in this project.** **Deferred.** No new L2 rule is implemented or
activated. The R1 pilot contains **0 L2 incidences and 0 `EvidenceProof`
records**, and `l2_rules` is empty by design: no trustworthy functional,
cardinality, disjointness or negative-assertion declarations for DBpedia infobox
properties are available offline. **Zero is the correct outcome, not a gap.**

Any future activation of L2 requires a written specification of the rule, its
source, its proof checker, and its tests, approved before implementation.

---

## 7. Open-World Assumption

State this explicitly wherever evidence levels are reported:

```
(d, p, o) ∉ K   does NOT imply   ¬p(d, o)
```

DBpedia is an **open-world** knowledge graph. `K` records what has been
documented, not what is true. Therefore:

* absence (`L0`) is a statement about the snapshot's coverage;
* an observed alternative (`L1`) is a statement about what the snapshot
  records, not a proof of incompatibility;
* only an explicit, sourced proof (`L2`) may be phrased as exclusion.

**The paper may remain open-world-aware even though the main experiments contain
only L0 and L1**, provided that absence is never interpreted as falsity, that
L1 is never written up as exclusion, and that every reported rationale is
phrased as an observation about the pinned snapshot.

**Paper-facing phrase.** Describe the framework as an
**open-world-aware observational evidence model**.

**Terminology reminder (`CLAUDE.md` §8).** Use `observed_contrast` for a fact
observed for the Answer but not observed for a distractor, unless an explicit
negative has been independently verified.

---

## 8. Reference table

| Level | Condition on `O_d(κ)` | Distinguishes? | Showable as a reason? | Reported in R1 pilot |
|---|---|---|---|---|
| `NOT_COVERED` | candidate supports the proposition | no | n/a | 313 incidences |
| `L0_ABSENCE_ONLY_OBSERVED` | `O_d(κ) = ∅` | diagnostic only | **no** | 8,485 incidences |
| `L1_POSITIVE_ALTERNATIVE_OBSERVED` | `O_d(κ) ≠ ∅`, no support | yes | yes, phrased as observation | 6,062 incidences |
| `L2_VERIFIED_EXCLUSION` | proof exists | yes | yes, as exclusion | **0** (deferred) |

Totals are the 14,860 `(fact, candidate)` incidences in
`outputs/journal2_week2_rationale_v3_r1_2026-08-03/evidence_audit_v3_r1.jsonl`,
`record_type=answer_fact_evidence`, re-counted for this document. `SCOPED_EMPIRICAL`
annotates 39 of the 6,062 L1 incidences; it selected nothing in the pilot.

**MCQ-level evidence.** `MCQ_level = min over distractors of the best level any
rationale fact supplies for that distractor`. MCQ-L2 requires every distractor
covered by L2; MCQ-L1 requires every distractor to reach at least L1 while at
least one lacks L2; MCQ-L0 means at least one distractor is covered only by L0.
All eight ready pilot Answers are **MCQ-L1**.

---

## 9. Vocabulary discipline

| Use | Do not use |
|---|---|
| observed alternative value | positive contrast, positive value contrast |
| snapshot absence, absence-only observed | missing fact, `d` lacks `p`, `d` has no `p` |
| open-world-aware observational evidence model | verified contrast model |
| scoped empirical single-valued annotation | functional predicate, functionality |
| requested / recommended / top-ranked / first-feasible class | globally optimal class |
| applies / uses / integrates LRoleSim | extends LRoleSim, LRoleSim generates rationales |
| local candidate-pool anonymity | uniqueness, global uniqueness |

Related terminology constraints live in `docs/context/09_claims_and_terminology.md`
and `CLAUDE.md` §"Non-negotiable scientific boundaries". Where those and this
file both speak, this file is authoritative on evidence levels only.
