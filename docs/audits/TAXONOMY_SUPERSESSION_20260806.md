# Taxonomy supersession notice — 2026-08-06

**Purpose** Record that the evidence-level **names** used in the July 26
engineering audit are superseded, and give an exact mapping so that no future
reader silently carries the old meanings forward.

**Authoritative file** `docs/context/EVIDENCE_TAXONOMY_V1.md`

---

## 1. What is superseded and what is not

`docs/audits/AUDIT_Journal2_v2_2026-07-26.md` **remains a valid historical
engineering audit** and is **not rewritten, not corrected and not deleted**. Its
findings on the v2 code base — the blocker list, the OWA violation in
`distinguishing_facts()`, the module boundaries, the acceptance criteria —
stand as written and retain their evidentiary value as a record of what the
project knew on 2026-07-26.

What is superseded is narrower and specific:

> **The evidence-level names `L0`, `L1`, `L2` as defined in §3.4 of the July 26
> audit no longer carry those meanings.** Future code, prompts, audits and paper
> text must take evidence-level definitions from `EVIDENCE_TAXONOMY_V1.md` and
> must not infer them from the July 26 audit.

File hash of the superseded audit, unchanged by this notice:

```
docs/audits/AUDIT_Journal2_v2_2026-07-26.md.sha256   (sidecar, retained as-is)
```

---

## 2. Why the names had to move

The July 26 audit numbered its levels by **argumentative strength under OWA**,
and it placed a *functionality requirement* inside the top level:

* its **L2** was an observed alternative **plus** `p` functional on `d`;
* its **L1** was an **absence** that had been **cross-verified in a second
  knowledge graph** (Wikidata or another-language DBpedia);
* its **L0** was an unverified absence.

Two problems follow for an offline DBpedia-infobox system.

1. **The old L1 is unreachable offline and is an absence claim.** It requires a
   second KG lookup, which the project's offline, pinned-snapshot protocol
   forbids, and even when performed it strengthens an *absence*, not an
   observation. It has **no counterpart** in V1 — V1 deliberately declines to
   promote absence by corroboration, because two snapshots missing the same
   triple is still two documentation gaps, not a negation.
2. **The old L2 conflates an observation with an ontological guarantee.**
   DBpedia infobox properties carry no trustworthy functionality declarations
   offline, so the functionality half can only ever be an *empirical, local*
   observation. V1 splits the two: the observation sets the **level** (L1), and
   the local empirical single-valuedness becomes a separate, weaker
   **annotation** (`SCOPED_EMPIRICAL`) that can order but never upgrade.

The dangerous residue is the phrase **"positive contrast"**. In the July 26
audit it named the *stronger* level (alternative **+** functionality). Prompt
8F-R1 reused it, as `L1_POSITIVE_VALUE_CONTRAST`, for the *weaker* level
(alternative, no functionality). A reader who trusts the phrase would credit
V1's L1 with a guarantee it does not have. That is exactly why
`EVIDENCE_TAXONOMY_V1.md` fixes the authoritative name as
**`L1_POSITIVE_ALTERNATIVE_OBSERVED`**, with the prose wording
**"observed alternative value"**, and retires "positive contrast" entirely.

---

## 3. Mapping table

| July 26 audit (§3.4) | Condition as written then | Prompt 8E status | Prompt 8F / 8F-R1 reason code | **Authoritative V1** | Relationship |
|---|---|---|---|---|---|
| **L2 — "positive contrast"** | `∃o′ ≠ o : (d,p,o′) ∈ K` **and** `p` functional on `d` | `POSITIVE_ALTERNATIVE_OBSERVED` (functionality never checked) | `L1_POSITIVE_VALUE_CONTRAST` | **`L1_POSITIVE_ALTERNATIVE_OBSERVED`** + optional `exclusion_basis=SCOPED_EMPIRICAL` | **Split.** The observation became the level; the functionality half became a weaker *local empirical annotation*, never a guarantee. **The V1 level is strictly weaker than the old L2.** |
| **L1 — "verified absent"** | `(d,p,o) ∉ K` **and** absence cross-verified in a second KG | — (never implemented) | — (never implemented) | **no counterpart** | **Dropped.** Requires a live second-KG lookup, forbidden by the offline protocol; and corroborated absence is still absence, not negation. **Not to be confused with V1's L1.** |
| **L0 — "unverified absent"** | `(d,p,o) ∉ K` only | `ABSENCE_ONLY_OBSERVED` | `L0_ABSENCE_ONLY_OBSERVED` | **`L0_ABSENCE_ONLY_OBSERVED`** | **Preserved.** Same meaning, same name, diagnostic only. |
| *(not in the audit)* | candidate also holds `o` | `SHARED_OBSERVED` | `NOT_COVERED_EXACT_EQUAL` and siblings | **`NOT_COVERED`** | **Added.** Tested before all levels; the fact discriminates nothing. |
| *(not in the audit)* | machine-checkable proof of exclusion | — | `L2_*` (defined, never fired) | **`L2_VERIFIED_EXCLUSION`** | **Redefined and deferred.** Now demands an explicit `EvidenceProof`; **0 incidences** in the R1 pilot. |
| *(not in the audit)* | `κ` empirically single-valued in a named local scope | — | `exclusion_basis` axis | **`SCOPED_EMPIRICAL` annotation** | **Added as an annotation, not a level.** |

### The collision, stated plainly

| Symbol | July 26 meaning | V1 meaning | Same? |
|---|---|---|---|
| `L0` | unverified absence | absence-only observed | **yes** |
| `L1` | absence cross-verified in a second KG | observed alternative value | **NO — unrelated** |
| `L2` | observed alternative + functional predicate | proof-backed verified exclusion | **NO — V1's L2 is stronger; the old L2 maps to V1's L1** |

Only `L0` survives with its meaning intact. `L1` and `L2` must be re-read
against `EVIDENCE_TAXONOMY_V1.md` on every occurrence.

---

## 4. Consequences for existing statements

* Any historical claim of the form *"100 questions should use only L2"*
  (July 26 audit §3.4 recommendation, and success criterion S5) was written in
  the **old** vocabulary. In V1 vocabulary the reachable target is
  **MCQ-L1 with `exclusion_basis` reported**, because V1's L2 requires proofs
  that no offline DBpedia source supplies. This is a change of naming and of
  what is provable offline, not a lowering of the evidential bar that was
  actually met: the eight ready pilot Answers are all **MCQ-L1**, i.e. every
  distractor is covered by a positively observed alternative value, never by
  absence alone.
* The July 26 criterion *"0 of the final 100 questions may carry L0"* remains
  meaningful and is **unchanged in force**: in V1 vocabulary it reads "no
  main-corpus rationale may rest on `L0_ABSENCE_ONLY_OBSERVED`", which the
  `main-l1` policy enforces by construction.
* Prompt 8E's three statuses (`SHARED_OBSERVED`,
  `POSITIVE_ALTERNATIVE_OBSERVED`, `ABSENCE_ONLY_OBSERVED`) are **compatible
  with V1** and map one-to-one onto `NOT_COVERED`, `L1`, `L0`. Prompt 8E's
  wording `POSITIVE_ALTERNATIVE_OBSERVED` is in fact the wording V1 adopts.
* Prompt 8F's rule that *"a different observed object alone is never L1"* is
  **withdrawn**. It let an empirical annotation decide a level. R1 corrected it,
  and V1 fixes the correction as authoritative.

---

## 5. Rule for future work

1. Cite `docs/context/EVIDENCE_TAXONOMY_V1.md` for every evidence-level
   definition.
2. Never copy an evidence-level definition out of the July 26 audit, out of any
   implementation report, or out of an identifier name.
3. Never write "positive contrast" or `POSITIVE_VALUE_CONTRAST`. Write
   **`L1_POSITIVE_ALTERNATIVE_OBSERVED`** / **"observed alternative value"**.
4. When quoting the July 26 audit in the paper or in future prompts, quote it
   as a **2026-07-26 engineering audit** and translate its level names through
   §3 of this notice before reasoning with them.
