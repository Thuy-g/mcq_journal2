# Albert Einstein — Phase-B readiness audit (Prompt 8H-B0)

**Date** 2026-08-10
**Repository** `/home/thuy/projects/mcq_journal2` · **Environment** `mcq-journal2` (Python 3.11.15)
**Audit branch** `journal2-phase-b0-albert-readiness-audit-20260810`, created from
`20234996e70c8e815e74534a1688958a6040a099`
**Nature** read-only. No production Python file was created or modified. No test was modified.
**Target Answer** `http://dbpedia.org/resource/Albert_Einstein`

**Verdict — §8:** `ALBERT_NOT_READY_MISSING_PHASE_B_INPUTS`

---

## 1. Preflight — verified, not assumed

| Check | Expected | Observed |
|---|---|---|
| repository path | `/home/thuy/projects/mcq_journal2` | same |
| conda environment | `mcq-journal2` | `CONDA_DEFAULT_ENV=mcq-journal2`, `/home/thuy/miniforge3/envs/mcq-journal2/bin/python` |
| Python | 3.11.x | 3.11.15 |
| branch at start | `journal2-minimal-core-selection-phase-a2-pool-20260809` | same |
| HEAD at start | `20234996e70c8e815e74534a1688958a6040a099` | same |
| A2 commit exists | yes | yes — *"Add bounded pool-exact search with evidence rescue"*, 2026-08-10 00:33:37 +0900 |
| package SHA-256 | `fc01dcfc9b8aec69e620e1e2a3bbc02f8396040cca596c840a28daadf269ba77` | **matches**, and matches the recorded `.sha256` sidecar |
| package integrity | `ZipFile.testzip()` → `None` | `None` (12 members) |
| tracked working tree | clean | **clean** — `git status --porcelain -uno` produced no output |
| untracked files | present | **155** untracked paths (excluding `:Zone.Identifier` sidecars) |
| A2 on-disk state | matches the A2 `source_hashes_before_after.csv` "after" column | **matches for every row**, including `src/mcq_core.py` = `ba4b3785…` and `src/MCQ_lrolesim.py` = `a286fe08…` |
| kernel suite (verification only) | 243 passed | **243 passed in 10.94 s** |

**The tracked tree is clean but 155 untracked files exist.** They include the
author's research sources (`src/mcq_generation.py`, `src/all_in_one.py`,
`src/build_bipartite_and_draw*.py`, `legacy/`, `docs/references/`,
`docs/context/*.md`, `notebooks/`, the Okuhara reference tree) and generated
caches. **Nothing was deleted, moved, staged, restored or modified.** No
`git add .` was used. `src/MCQ_lrolesim.py` was not opened for writing and its
SHA-256 is unchanged. Untracked research files were not cleaned.

`outputs/*` is git-ignored, so the audit package is written there and only the
four documents under `docs/` are committed.

---

## 2. Sources read

**Primary (the current contract).** `src/mcq_core.py` (1,264 lines, read in
full); `tests/test_mcq_core.py`; `docs/context/EVIDENCE_TAXONOMY_V1.md`;
`docs/checks/MINIMAL_CORE_PHASE_A2_POOL_WALKTHROUGH.md`;
`docs/checks/MINIMAL_CORE_PHASE_A2_POOL_ABLATION.md` and its CSV; the Prompt-8H-A2
`implementation_report.md`.

**Frozen R1, as an upstream oracle only.** `src/rationale_v3/contracts.py`,
`evidence.py`, `quality.py`, `semantic_relations.py`, `selector.py`, the three
policy JSON files, `src/pipeline/rationale_v3_run.py`, and the relevant parts of
`src/pipeline/graph_lrolesim_run.py` and `candidate_order.py`.

**Class selection.** `src/category_extractor_ClaudeWeb_v4.py` (current
reference), `src/category_extractor_ClaudeWeb_v2.py` (historical),
`src/category_extractor.py` (original author's semantics, consulted only where
needed).

**Frozen data artefacts.** The Prompt-8D handoff, the R1 evidence audit, the
Week-1 local mapping, the batch-34 class-selection outputs, the PDF-grounded
reconciliation, `data/pilot_class_policy_v1.*`, the semantic-index cache, the
class-member SQLite cache, and the pinned local KG pickle (opened read-only).

**Not read.** Okuhara source code — out of scope for this audit, as instructed.

`docs/plans/MINIMAL_RESEARCH_CORE_PLAN.md` §6 was read so that the Phase-B1 plan
does not contradict the approved sequencing.

---

## 3. The `AnswerCase` contract

Reconstructed field by field from the source actually on disk and frozen
separately as **`docs/context/PHASE_B_INPUT_CONTRACT.md`**. The headline finding
is stated there and repeated here because everything else follows from it:

> `src/mcq_core.py` does not derive a single `AnswerCase` field from a raw
> Answer URI. It imports only `__future__`, `dataclasses`, `itertools`, `math`
> and `typing`.

Summary of where the fields must come from:

| Field group | Access class | Exists for Einstein? |
|---|---|---|
| `answer_uri`, `display_label` | none | **yes** |
| `Candidate.rank`, `.score`, `.uri` | LRoleSim, over a candidate roster | **no** |
| `FactQuality.predicate_uri / direction / counterpart_uri` | local KG only | **yes** (computable) |
| `FactQuality.eligible / soft_leak / display_label / label_length / token_count` | none, beyond the policy file | **yes** (computable) |
| `FactQuality.verbalizable / template_id / pedagogical_tier` | none, beyond the policy file | **yes** (computable) |
| `AnswerFact.levels` | local KG **+ candidates** + semantic index | **no** |
| `AnswerFact.exclusion_bases` | local KG + declared scope | **no** |
| `AnswerFact.granularity_risks` | semantic index built for this source-object set | **no** |
| `eligible_fact_indices` | derived by `build_case()` | n/a |

---

## 4. Albert Einstein artefact inventory

Exhaustive search of the repository and every frozen output for
`Albert_Einstein` / `Albert Einstein`. Fifteen files match; twelve are source
files that mention the name only as a comment, a probe list or a doctest
example. The three that carry real data are analysed below.

### 4.1 What exists

| Artefact | Path | Provenance / version | Compatible with the current frozen spec? |
|---|---|---|---|
| **Answer appears in the 34-Answer input list** | `data/category_answer_nodes_v2_demo.txt`, line 32 | tracked; `sha256 d78621e4…` recorded in the batch-34 manifest | yes — it is only an input URI |
| **Class-selection result** | `outputs/category_selector_v4_batch34_2026-07-28/{B1_initial,B2_recovery,B_final_warm}/results.jsonl` | `category_selector_v3.4`, live SPARQL run 2026-07-28, `sbert_enabled: false`, `local_index_supplied: false` | **no — see §4.3** |
| **Reconciled preliminary class proposal** | `outputs/journal2_pdf_grounded_reconciliation_2026-07-30/class_decision_reconciliation.csv`, row `input_index=31`; worksheet §31 | 2026-07-30 | **no — `NEEDS_HUMAN_DECISION`, `human_approval` empty, checkboxes unticked** |
| **Answer is present in the pinned local KG** | `data/infobox.pickle_EnglishVersion_EntityType` | `sha256 e230c5b9…`, the pinned snapshot | **yes** — node index `417144`, 9 OUT + 57 IN one-hop facts, 25 distinct predicates |

### 4.2 What does **not** exist

| Required artefact | Status | Evidence |
|---|---|---|
| Human-approved class | **absent** | `data/pilot_class_policy_v1.csv` holds exactly nine rows: Yamanaka, Tomonaga, Satō, Carbon, Silicon, Sulfuric acid, Aristotle, Plato, Adam Smith. Its manifest note reads: *"Approval covers the nine-Answer engineering pilot only. The remaining 25 Answers of the 34-Answer denominator are NOT approved. Never substitute an unapproved class at run time."* |
| Complete same-class candidate list | **absent** | `data/cache/pilot_class_member_mapping_v1.sqlite` holds 32 pages for 23 classes — all of them the approved pilot classes, none Einstein-related. The batch-34 SPARQL cache stores only the Answer label, its category list and per-category member **counts**; the two cached responses mentioning Einstein contain no member list. |
| Local-KG membership information for candidates | **absent** | `mapped_candidates.jsonl` contains two "Einstein" strings, both `Einsteinium` (a Carbon/Silicon class member, `NO_LOCAL_MATCH_AND_NO_REDIRECT`). No Albert Einstein candidate was ever mapped. |
| Graph extraction / one-hop **candidate** facts | **absent** | `observed_candidate_facts.jsonl` covers the eight ready pilot Answers only. |
| One-hop **Answer** facts, serialized | **absent as a record**, **derivable offline** | `observed_answer_facts.jsonl` has 582 rows, none for Einstein. The underlying facts are in the pinned KG (§4.4). |
| Frozen LRoleSim ranking | **absent** | `candidate_ranking_handoff.jsonl` has 9 rows; Einstein is not one. There is no ranking, so `Candidate.rank` and `.score` do not exist. |
| R1-style evidence table | **absent** | `evidence_audit_v3_r1.jsonl` `answer_fact_evidence` records cover the eight ready Answers only (582 records, 14,860 incidences). |
| Semantic-index coverage | **absent for Einstein** | `data/semantic_index_v3/pilot_place_containment_v1.json` is keyed to the pilot source-object digest (§7). |
| Quality / leakage records | **absent as records**, **computable offline** | see §4.4 |
| Verbalization / template information | **available generically** | the 61-entry template registry in `predicate_policy.json` is Answer-independent |
| **A complete `AnswerCase`** | **absent** | follows from the above |

### 4.3 Why the existing class-selection output must not be reused

The batch-34 run selected `dbc:Einstein_family` as Albert Einstein's automatic
top-1 class, with `combined_score = 1.0`, `feasible = true`,
`leak_level = "no_leak"`, `eligible_remote_count = 10`.

Three independent reasons make it unusable:

1. **It is an Answer-name leak that the class-level detector missed.** Running
   the frozen R1 rule on the same pair returns HARD (`WHOLE_TOKEN einstein`).
   The mechanism of the miss is analysed in
   `docs/audits/ANSWER_LEAKAGE_DESIGN_AUDIT.md` §3. The same run correctly
   hard-rejected `dbc:Albert_Einstein`, so the detector fires only at the top of
   its range.
2. **It is not human-approved, and its successor proposal is explicitly
   pending.** The reconciliation rejected the automatic top-1 and proposed
   `dbc:German_theoretical_physicists` (fallbacks `dbc:Nobel_laureates_in_Physics`,
   `dbc:20th-century_German_physicists`) with status `NEEDS_HUMAN_DECISION`, an
   empty `human_approval` column, and every checkbox in worksheet §31 unticked.
3. **The scoring was degraded and unverified.** `sbert_enabled: false` and
   `encoder_metadata.available: false`, so the combined score was IDF-only
   (`normalized_sbert = 0.0` on every row); and `local_index_supplied: false`
   with `local_check: "not_applicable"`, so **no class was ever checked against
   the pinned local KG**. Local-KG membership is what determines whether a class
   can produce a usable candidate roster at all.

Note also the vocabulary discipline: the batch record's own field is
`recommended_classes`, and the reconciliation's is a *preliminary proposal*.
Neither is a globally optimal class, and neither may be described as one.

### 4.4 What the pinned local KG does supply for Albert Einstein

Measured 2026-08-10 by opening the pinned pickle read-only:

```
node index                417144   (lookup form '<http://dbpedia.org/resource/Albert_Einstein>')
one-hop OUT facts              9   (6 distinct predicates)
one-hop IN  facts             57   (22 distinct predicates)
distinct one-hop facts        66   (60 distinct counterpart entities)
```

Applying the frozen R1 quality layer (`assess_fact_quality` +
`predicate_policy.json`, `sha256 6c07bbe3ab…`) to those 66 facts:

```
ELIGIBLE after the hard filter      48   across 17 distinct (predicate, direction) keys
  of which with a registered template  41
REJECTED                            18
  ANSWER_LEXICAL_LEAK               15
  PREDICATE_RAW_LAYOUT_SLOT          2
  PREDICATE_EXTERNAL_URL_FIELD       2
  OBJECT_EXTERNAL_URL                1   (dbp:thesisUrl -> …/eth-30378-01.pdf)
  OBJECT_WEB_ARCHIVE_URL             1   (dbp:url -> web.archive.org/…)
```

**Reading.** The *Answer-fact* half of the contract is comfortably satisfiable
offline — 48 eligible facts is more than any pilot Answer except Aristotle, and
the two Prompt-8E motivating failures (Web-Archive URL, external URL) are caught
on a new Answer with no special-casing. The blocked half is everything that
needs **candidates**.

**Open-world reminder.** These 66 facts are what the pinned snapshot records for
Albert Einstein. Absence of any other fact is a statement about the snapshot's
coverage, never about the world.

---

## 5. The minimal upstream sequence, and where it breaks

| # | Arrow | Existing implementation | Status for Albert Einstein |
|---:|---|---|---|
| 1 | Answer URI → **class selection** | `src/category_extractor_ClaudeWeb_v4.py`, `select_class(...)`, mode `recommended` | **GAP-1 — governance.** A ranked proposal exists but is `NEEDS_HUMAN_DECISION`. Re-running is possible (SPARQL cache is warm for the category list) but produces a leaking top-1 unless the class-level leak rule is strengthened. No approved class exists. |
| 2 | class → **complete candidate pool** | Week-1 mapping stage; SPARQL `?member dcterms:subject <Category:…>` + `MappedCandidate` | **GAP-2 — network, hard.** The pinned dump is `infobox-properties` only and contains **no** `dcterms:subject` edge; probing 400,000 subject nodes found predicates exclusively under `http://dbpedia.org/property/`, and only 135 `Category:` resources among the first 2,000,000 node URIs — all of them infobox *values*. **The candidate roster cannot be derived offline.** The class-member cache covers only the 23 approved pilot classes. |
| 3 | pool → **local graph / observed facts** | `src/kg/loader.py`, `src/kg/graph_view.py`, `src/pipeline/graph_lrolesim_run.py` | **Blocked by GAP-2 for candidates.** For the *Answer alone* it already works offline: §4.4 is the proof. |
| 4 | graph → **frozen LRoleSim ranking** | `src/lrolesim/adapter.py` + `src/MCQ_lrolesim_ClaudeWeb_v2.py`, driven by `run_pilot()` | **Blocked by GAP-2.** Also **GAP-3 — orchestration**: `run_pilot()` is hard-wired to `data/pilot_class_policy_v1.csv`, whose approval is nine Answers wide, and to the frozen Week-1 mapping directory. It is not parameterised by an arbitrary Answer. |
| 5 | → **Answer facts** | one-hop extraction, `observed_answer_facts.jsonl` shape | **AVAILABLE offline.** 66 raw / 48 eligible, measured. |
| 6 | → **evidence classification** | `rationale_v3.evidence.classify_fact_against_candidate()` | **Blocked by GAP-2.** A level is a property of the ordered pair (fact, candidate); with no candidates there is nothing to classify. The classifier itself is ready and needs no change. |
| 7 | → **quality / leakage / verbalizability** | `rationale_v3.quality.assess_fact_quality()` | **AVAILABLE offline**, measured in §4.4. |
| 8 | → **semantic fields** (`granularity_risks`) | `rationale_v3.semantic_relations` + `build_semantic_index_from_pinned_kg()` | **GAP-4 — cache rebuild.** See §7. The build mode exists and is offline; the *existing cache* cannot be reused. |
| 9 | → **`AnswerCase`** | `mcq_core.build_case()`; reference reader `load_pilot_cases()` in `tests/test_mcq_core.py:370–417` | **GAP-5 — no production adapter.** The 45-line reader exists only as test code and reads only frozen records that exist for the eight pilot Answers. |
| 10 | → **`select_distractors()`** | `src/mcq_core.py` | **READY, unchanged.** 243/243 tests pass. It needs no Phase-B modification whatsoever. |

Five gaps. Only **GAP-2** requires network access; **GAP-1** requires a human
decision; **GAP-3**, **GAP-4** and **GAP-5** are offline engineering.

**Nothing in this task implements any of them.**

---

## 6. Answer-leakage design

Audited separately and in full in **`docs/audits/ANSWER_LEAKAGE_DESIGN_AUDIT.md`**.
Its conclusion, in one paragraph:

> Preserve `rationale_v3.quality.detect_answer_leakage()` with the frozen
> thresholds (`minimum_token_length=4`, `minimum_prefix_length=5`,
> `soft_prefix_length=4`, `strip_suffixes=["s","es"]`). Measured on the same
> 60 real Albert Einstein counterparts it returns 11 hard leaks against v4's 4
> and v2's 9, and it is the only one of the three that separates
> `Carbon`/`Carbonado` (HARD) from `Carbon`/`Boron_carbide` (soft at most) while
> preserving `Iron(II) chloride` and `Iron(III) chloride` as distinct display
> labels. Do not import `category_extractor_ClaudeWeb_v4.py` or `_v2.py` into
> `mcq_core.py`; do not introduce WordNet, spaCy, embeddings or an LLM — WordNet
> produced two demonstrable false-positive mechanisms in the measurements
> (`einstein → brainiac`, `phosphorus → lucifer`).

---

## 7. Semantic-index requirement

### What produces `UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE`

In `classify_fact_against_candidate()`, for a candidate with at least one
observed object that does not support the claim:

```python
if any(relation == CLAIM_OBJECT_UNDER_CANDIDATE_OBJECT for ...):
    granularity = GRANULARITY_RISK_PRESENT
elif not closure_ran:
    granularity = GRANULARITY_RISK_UNRESOLVED      # <-- the value in question
else:
    granularity = GRANULARITY_RISK_NONE
```

`closure_ran` is `semantic_index.available and no pair returned
SEMANTIC_RELATION_UNAVAILABLE`. So the risk value is `UNRESOLVED` exactly when
the index was not usable. `UNRESOLVED` is ordered against by objective key 6 and
blocks main-corpus eligibility, but it never relabels an observed alternative as
an absence — the observation stays intact.

**`CLOSURE_RAN` means only that the relevant semantic check executed.** It is
not a statement that a semantic relation was found; the R1 pilot recorded 116
`semantic_relation` records over 14,860 incidences.

### The existing cache is pilot-specific, by construction

`data/semantic_index_v3/pilot_place_containment_v1.json`
(`sha256 00a780b414…`) carries:

```
format                    rationale_v3.semantic_index/1
policy_version            semantic_relation_policy/1.0.0
indexed_object_count      2205
parent_edges              1192
cache_key.max_depth       4
cache_key.pinned_kg_sha256        e230c5b95e20093631697624d9c46f30a14081b3f415d5027ffaf313bdbbea1b
cache_key.policy_sha256           4336b3b003324431ac9b7304d29617d6d83e2a3d3a2c7f79ee0d9ca4d2fa078a
cache_key.source_object_list_sha256  926b274d8e47d9d70d0a0e548dd844a20cd966def7eaa07647172e1ac01bbf5d
```

`SemanticIndexCacheKey.matches()` compares four fields, `source_object_list_sha256`
among them. That digest is produced by `pilot_object_uris()`, whose own docstring
states: *"This IS the semantic index's source-object list, and its digest is part
of the cache key: an index built for a different pilot must not be reused."*

**Therefore the answer to the question is unambiguous: the existing cache is
pilot-specific and cannot safely cover Albert Einstein or his candidate
objects.** Adding his counterpart URIs changes the source-object set, changes the
digest, and `load_semantic_index_cache()` returns
`unavailable_semantic_index("semantic index cache was built for different inputs
(source_object_list_sha256); it is not reused")`. Every L1 pair then carries
`UNRESOLVED_SEMANTIC_INDEX_UNAVAILABLE`.

Merely reading the existing cache is **not** sufficient, so no rebuild was
attempted in this task.

### What a rebuild would need

| Ingredient | Source | Status |
|---|---|---|
| the pinned KG | `data/infobox.pickle_EnglishVersion_EntityType`, `sha256 e230c5b9…` | present, verified |
| the traversal policy | `src/rationale_v3/policies/semantic_relation_policy.json`, `sha256 4336b3b0…`, `max_depth = 4` | present, unchanged |
| the **enlarged** source-object list | every counterpart URI the enlarged run reasons about = Answer facts **∪ candidate facts** | **the candidate half does not exist** (GAP-2) |
| the build mode | `build_semantic_index_from_pinned_kg()` in `src/pipeline/rationale_v3_run.py` — the one place permitted to open the pickle | present, offline |

The dependency is worth stating plainly: **the semantic index cannot be rebuilt
for Albert Einstein until his candidate roster exists**, because the source-object
list includes the candidates' objects. GAP-4 is downstream of GAP-2, not
parallel to it.

---

## 8. Verdict

### `ALBERT_NOT_READY_MISSING_PHASE_B_INPUTS`

Albert Einstein **cannot** be run today, and no rearrangement of existing frozen
artefacts changes that. The missing inputs, stated as `AnswerCase` fields:

| Missing field | Why it is missing | Blocking gap |
|---|---|---|
| `candidates` — the entire tuple | no class-member list exists for any Einstein-related class, locally or in cache, and the pinned dump has no membership edge | GAP-2 (network), GAP-1 (approval) |
| `Candidate.rank`, `Candidate.score` | no LRoleSim run exists; there is no graph because there are no candidates | GAP-2, GAP-3 |
| `AnswerFact.levels` (all pairs) | an evidence level is a property of the ordered pair (fact, candidate) | GAP-2 |
| `AnswerFact.exclusion_bases` | derived over a scope defined by the candidate pool | GAP-2 |
| `AnswerFact.granularity_risks` | needs a semantic index keyed to the enlarged source-object set | GAP-4, downstream of GAP-2 |

**Fields that are *not* missing:** `answer_uri`, `display_label`, and every one
of the eleven `FactQuality` attributes for all 66 one-hop facts — measured, not
assumed (§4.4).

### What was deliberately not done

No dummy values were written. No hand-authored candidate list, no invented rank
or score, no assumed evidence level, no reuse of the unapproved
`dbc:Einstein_family` class, no substitution of a legacy Overlap ranking for the
frozen LRoleSim ranking, and no synthetic case dressed up as Albert Einstein.
The 243 synthetic and pilot tests in `tests/test_mcq_core.py` demonstrate that
the kernel is correct; they are **not** a substitute for the real Albert Einstein
input, and no claim to the contrary is made here.

### The narrowest true statement about what *is* ready

`src/mcq_core.py` is ready and needs no change. The Answer-side half of the
input contract is offline-derivable today for Albert Einstein. The candidate-side
half is not derivable from the pinned snapshot at all, and its first step
requires a human class decision followed by approved network access.

---

## 9. Phase-B implementation plan

Held separately in **`docs/plans/PHASE_B1_MINIMAL_IMPLEMENTATION_PLAN.md`**.
Not started in this task.

---

## 10. Reproducing every check in this document

```bash
conda activate mcq-journal2
cd /home/thuy/projects/mcq_journal2

# --- 1) preflight -------------------------------------------------------
git rev-parse HEAD
git cat-file -t 20234996e70c8e815e74534a1688958a6040a099
sha256sum outputs/journal2_minimal_core_phase_a2_pool_2026-08-09.zip
python -c "import zipfile;print(zipfile.ZipFile('outputs/journal2_minimal_core_phase_a2_pool_2026-08-09.zip').testzip())"
git status --porcelain --untracked-files=no          # empty => tracked tree clean
git status --porcelain --untracked-files=all | grep -c '^??'
python -m pytest -q tests/test_mcq_core.py           # 243 passed

# --- 2) the class-selection artefact that exists, and why it is unusable
python - <<'PY'
import json
p = "outputs/category_selector_v4_batch34_2026-07-28/B_final_warm/results.jsonl"
for line in open(p, encoding="utf-8"):
    r = json.loads(line)
    if r.get("original_uri", "").endswith("Albert_Einstein"):
        print("selected_class      :", r["selected_class"])
        print("selection_status    :", r["selection_status"])
        print("sbert available     :", r["encoder_metadata"]["available"])
        print("local_check on top1 :", r["recommended_classes"][0]["local_check"])
        print("rejected_by_reason  :", r["number_rejected_by_reason"])
PY
grep -n "^31,http://dbpedia.org/resource/Albert_Einstein" \
     outputs/journal2_pdf_grounded_reconciliation_2026-07-30/class_decision_reconciliation.csv
sed -n '727,752p' outputs/journal2_pdf_grounded_reconciliation_2026-07-30/human_approval_worksheet.md

# --- 3) approved classes are nine Answers wide, Einstein is not among them
cut -d, -f3 data/pilot_class_policy_v1.csv
python - <<'PY'
import sqlite3
con = sqlite3.connect('file:data/cache/pilot_class_member_mapping_v1.sqlite?mode=ro', uri=True)
rows = sorted({r[0] for r in con.execute("select class_uri from pages") if r[0]})
print(len(rows), "cached classes; Einstein-related:",
      [c for c in rows if "instein" in c])
PY

# --- 4) no frozen Einstein records downstream
grep -c "Albert_Einstein" \
  outputs/journal2_week2_extract_integration_2026-07-30/candidate_ranking_handoff.jsonl \
  outputs/journal2_week2_extract_integration_2026-07-30/observed_answer_facts.jsonl \
  outputs/journal2_week2_rationale_v3_r1_2026-08-03/evidence_audit_v3_r1.jsonl || true

# --- 5) the semantic-index cache key
python -c "import json;print(json.load(open('data/semantic_index_v3/pilot_place_containment_v1.json'))['cache_key'])"

# --- 6) the pinned-KG measurements of §4.4  (loads the 1.2 GB pickle, ~2 min)
PYTHONPATH=src python - <<'PY'
import pickle
from collections import Counter
from rationale_v3.quality import assess_fact_quality, load_quality_policy

KG = "data/infobox.pickle_EnglishVersion_EntityType"
A  = "http://dbpedia.org/resource/Albert_Einstein"
plain = lambda u: u[1:-1] if u.startswith("<") else u

policy = load_quality_policy("src/rationale_v3/policies/predicate_policy.json")
with open(KG, "rb") as f:
    url_index, index_url, out_n, in_n, _ = pickle.load(f)

idx = url_index["<%s>" % A]
facts = sorted({(plain(index_url[p]), "OUT", plain(index_url[o])) for p, o in out_n.get(idx, [])}
             | {(plain(index_url[p]), "IN",  plain(index_url[s])) for p, s in in_n.get(idx, [])})
print("node index", idx, "| OUT", len(out_n.get(idx, [])), "| IN", len(in_n.get(idx, [])),
      "| distinct facts", len(facts))

reasons = Counter(); eligible = 0
for pred, d, c in facts:
    q = assess_fact_quality(answer_uri=A, predicate_uri=pred, direction=d,
                            counterpart_uri=c, policy=policy)
    eligible += q.eligible
    for r in q.rejection_reasons:
        reasons[r] += 1
print("eligible", eligible, "rejected", len(facts) - eligible, dict(reasons))
PY
```

The leakage measurements have their own reproduction block in
`docs/audits/ANSWER_LEAKAGE_DESIGN_AUDIT.md` §7.

---

## 11. Deferred issues and uncertainties

1. **The class-level leak rule is weaker than the rationale-level one.** v4
   accepted `dbc:Einstein_family`. Fixing it changes class selection, a
   different stage with its own approval path; recorded here, not authorised.
2. **The batch-34 run had no SBERT and no local index.** Every recorded
   `combined_score` is IDF-only and no `local_check` was performed. Any future
   class decision for Albert Einstein should be re-derived under a configuration
   that at least checks local-KG membership, since a class whose members are
   absent from the pinned dump cannot produce a candidate roster.
3. **Class size versus the search budget.** The proposed classes have 72, 217
   and 560 eligible remote members. `C(n,3) > 200,000` at *n* = 108, so
   `Nobel_laureates_in_Physics` and `20th-century_German_physicists` would leave
   `FULL_EXACT` and land in `POOL_EXACT`, whose result is **exact within the
   bounded candidate pool** and carries no optimality claim over excluded
   candidates. Einstein would be the first Answer ever to exercise
   `POOL_EXACT` on real data — scientifically interesting, and a reason to
   report the search scope prominently rather than a reason to avoid the class.
4. **Cost.** At Aristotle's fact density (≈140 µs per combination) a 100-candidate
   bounded pool costs ≈ 23 s per Answer. Einstein has 48 eligible facts against
   Aristotle's 218, so the real cost is likely far lower, but it has not been
   measured.
5. **`dbp:influences` IN carries 18 of the 48 eligible facts**, so the redundant-κ
   component of the rationale key (objective key 12) may finally do real work.
   Untested; noted for the Phase-B1 walkthrough.
6. **Whether Einstein should enter the main corpus at all** is a separate
   question this audit does not answer. He is an unusually leak-prone Answer, and
   even after the 15 leak rejections, several surviving counterparts
   (`The_Meaning_of_Relativity`, `Introducing_Relativity`, `Subtle_is_the_Lord`)
   are books *about* him. That is a rationale-quality judgement for human
   evaluation, not a filter this audit proposes to add.

---

## 12. Files

**Created (documentation only)**

| Path |
|---|
| `docs/audits/ALBERT_EINSTEIN_PHASE_B_READINESS.md` (this file) |
| `docs/context/PHASE_B_INPUT_CONTRACT.md` |
| `docs/audits/ANSWER_LEAKAGE_DESIGN_AUDIT.md` |
| `docs/plans/PHASE_B1_MINIMAL_IMPLEMENTATION_PLAN.md` |

**Modified** — none.

**Intentionally not touched** — `src/mcq_core.py`, `tests/test_mcq_core.py`,
`src/MCQ_lrolesim.py`, `src/rationale_v3/**`, `src/rationale/**`,
`src/pipeline/**`, `src/selection/**`, `src/lrolesim/**`, `src/kg/**`, every
category extractor, `docs/context/EVIDENCE_TAXONOMY_V1.md`,
`docs/plans/MINIMAL_RESEARCH_CORE_PLAN.md`, `docs/checks/**`, everything under
`data/`, and all 155 untracked research files.
