# B3 pre-freeze blocker resolution — template coverage, nested budget feasibility, extended bounding, package integrity

**Prompt** 8H-B3-ARCH-3R · **Date** 2026-09-19
**Status** DEVELOPMENT MEASUREMENTS ONLY. Not a publication run, not
production B3 code, not a signed decision. The `RECORDED DECISION` lines of
`B3_HUMAN_DECISION_MEMO_2026-09-18.md` are untouched; the §H provisional set
was used to CONSTRUCT the analysis only.
**Evidence** `outputs/journal2_b3_pre_freeze_resolution_2026-09-19/` and its
archive `outputs/journal2_b3_pre_freeze_resolution_2026-09-19.zip`
(ARCHIVE_DIGEST in the external `.zip.sha256`: `be9e9928c5919a2b808469dc5208a9fabc29680c98674d0485329231a8da7d57`); the rebuilt
ARCH-3 archive `outputs/journal2_b3_decision_support_2026-09-18.zip`
(ARCHIVE_DIGEST `8666a3361a918102bd26a4f326ec3ea083b3cd91d4cdf388c29431965800c2bd`).
**Script** `scripts/audit_b3_pre_freeze_resolution.py` (AUDIT / DECISION
SUPPORT ONLY), reusing the audited ARCH-3 module; the ARCH-3 script was
modified only in its packaging stage (§1).
**Companions** `B3_TEMPLATE_COVERAGE_EXPANSION_PLAN_2026-09-19.md` and
`B3_PRE_FREEZE_BLOCKER_RESOLUTION_2026-09-19.summary.json`.
**Terminology authority** `docs/context/EVIDENCE_TAXONOMY_V1.md`.

Measured results are marked **Measured**; the reviewer's readings are marked
**Reading** and decide nothing. Every rate carries its denominator. Nothing
upstream changed: the selected Answer, class, distractor triple, LRoleSim
ranks and scores, evidence levels and `R*` of the 396 learner-facing
development items are read from the ARCH-3 universes. No network access.

---

## 1. A — the evidence-package integrity repair (done first)

**What was wrong (Measured on the code).** The ARCH-3 package stage
enumerated the directory, digested every file and wrote `SHA256SUMS.*` while
the archive was open, then, after closing the archive, wrote
`zip_manifest.json` containing the archive's own SHA-256. On a first run that
file is simply missing from the archive; on any later run the previous run's
`zip_manifest.json` and `SHA256SUMS.*` are enumerated and archived as stale
content, and the archive digest recorded inside them can never match the
archive that contains them.

**The corrected protocol** (`build_package()` in the ARCH-3 script, reused by
this task): (1) delete every artefact of an earlier package run (previous
archive, external digest, `zip_manifest.json`, previous content-manifest
files); (2) enumerate the regular files, digest each, decide `in_zip`;
(3) write the **CONTENT_MANIFEST** (`CONTENT_MANIFEST.json`, `SHA256SUMS.txt`,
`SHA256SUMS.csv`) **before** the archive exists and never with the archive's
own digest inside; (4) build the archive in deterministic path order with no
directory entries; (5) close it, `testzip()`, compute the **ARCHIVE_DIGEST**
and write it **only** to the external `<archive>.sha256`, then re-read the
archive and verify digest and entry count. The counts are consistent by
construction: `zip_entries = regular_files_in_zip + 3 manifest files`,
`directory_entries = 0`.

**The ARCH-3 archive, rebuilt without recomputing any measurement
(Measured).** The package stage re-aggregates the rollups from the stored
per-item measurement files; the eight scientific rollup files were digested
before the rebuild and re-verified byte-identical afterwards. The
measurement-time script hash is carried forward in `run_manifest.json`
(`measurement_script_sha256`) beside the hash of the script that packaged.

| check | result |
|---|---|
| archive_digest_inside_manifest | False |
| content_manifest_inside_equals_on_disk | True |
| directory_entries_in_zip | 0 |
| excluded_regular_files | 10 |
| external_digest_matches_archive | True |
| regular_files_in_zip | 8343 |
| regular_files_total | 8353 |
| scientific_rollups_unchanged_by_repackage | True |
| stale_zip_manifest_inside_archive | False |
| stale_zip_manifest_present | False |
| testzip_first_bad | None |
| zip_entries | 8346 |
| zip_entries_equal_manifest_expected | True |
| scientific rollups re-verified byte-identical | h13_objective_sensitivity.json, h14_admissibility_arms.json, h18_bounding_stability.json, h5_verbalizability_audit.json, h6_solver_metrics.json, h7_budget_sweep.json, per_cohort_rollups.json, per_item_metrics.csv |
| external ARCHIVE_DIGEST | `8666a3361a918102bd26a4f326ec3ea083b3cd91d4cdf388c29431965800c2bd` |

**The new archive** (`465` entries, expected `465`):

| quantity | value |
|---|---|
| archive | /home/thuy/projects/mcq_journal2/outputs/journal2_b3_pre_freeze_resolution_2026-09-19.zip |
| archive_bytes | 1652861 |
| archive_sha256 | be9e9928c5919a2b808469dc5208a9fabc29680c98674d0485329231a8da7d57 |
| directory_entries_in_zip | 0 |
| entries_consistent | True |
| excluded_regular_files | 0 |
| external_digest_file | /home/thuy/projects/mcq_journal2/outputs/journal2_b3_pre_freeze_resolution_2026-09-19.zip.sha256 |
| external_digest_verified | True |
| kind | ARCHIVE_DIGEST |
| regular_files_in_zip | 462 |
| regular_files_total | 462 |
| testzip_first_bad | None |
| zip_entries | 465 |
| zip_entries_expected | 465 |

---

## 2. B — the template-candidate audit (summary; the plan has the tables)

Ninety-one predicate-direction keys were audited over the whole pinned KG:
the five ARCH-3 high-impact keys, every key of a template-less fact in a
selected `R*`, every key that would unlock arm-C pre-answer context in at
least two items, and every key with at least twenty shared unverbalizable
optional groups. Verdicts: **48 SAFE_TO_TEMPLATE, 29
NEEDS_HUMAN_REVIEW, 14 REJECT** (`template_candidates_v1.json`,
version `template_candidates/1.0.0-proposal-not-production`). All five
high-impact keys are SAFE with neutral, family-independent readings. The
production registry is not edited; no Answer-specific template exists.

---

## 3. C — counterfactual template coverage on the frozen selections (Measured)

T0 = production templates; T1 = the five high-impact keys; T2 = all
48 SAFE keys. Applied in memory to the `R*` facts and the optional
groups of every item; distractors and `R*` unchanged.

| set | `R*` fully verbalizable | recovered vs T0 | items with a template-less `R*` fact left | arm-C ≥ 1 pre-answer clue | arm-C mandatory-only |
|---|---|---|---|---|---|
| T0 | 220/396 (55.56%) | — | — | 132/396 (33.33%) | 264/396 (66.67%) |
| T1 | 316/396 (79.8%) | 96/396 (24.24%) | — | 147/396 (37.12%) | — |
| T2 | 350/396 (88.38%) | 130/396 (32.83%) | 46/396 (11.62%) | 193/396 (48.74%) | 203/396 (51.26%) |

Per cohort group, the unresolved keys under T2 and the arm-B/arm-C detail are
in the expansion plan §7 and in `template_coverage_rollup.json`. Arm B and
arm C coincide at every level: the A-excluding support-3 rule never removes
the last admissible group.

**Secondary counterfactual, kept separate (Measured).** For the items whose
frozen `R*` is still not fully verbalizable under T2, an UPSTREAM
require-verbalizable re-selection through the frozen kernel with the T2 flags
patched in gives: `NO_FULLY_VERBALIZABLE_MIN_CARD_SOLUTION_AT_SAME_POLICY` 15, `ALTERNATIVE_RATIONALE_ONLY` 14, `ALTERNATIVE_DISTRACTORS_CHANGE` 12, `BASELINE_VERBALIZABLE_UNDER_T2` 4, `COUNTERFACTUAL_NOT_COMPUTED_TIMEOUT` 1 (`BASELINE_VERBALIZABLE_UNDER_T2` means the kernel, re-run with the T2 flags,
itself orders a fully verbalizable rationale first for the same triple through key 9;
`COUNTERFACTUAL_NOT_COMPUTED_TIMEOUT` is the 120 s budget). This is what the policy would do if verbalizability
were allowed to change the frozen triple; the primary B3 path does not allow
it (§H provisional H5).

**Reading.** Generic deterministic templates repair most of the H5 loss
without touching a single selection: five templates take fully verbalizable
`R*` from 220/396 (55.56%) to 316/396 (79.8%), and the 48 SAFE keys to 350/396 (88.38%). The remainder
sits on keys that need a human call (`regent`, `after`/`before`,
`leaderName`, `titleLeader`, `wars`) or are rejected (`honorificPrefix`,
`name`, `subdivisionType`). The H14 side moves less and where it moves is
telling: places gain pre-answer context almost entirely from templates
(0/47 → 39/47 under T2), persons barely (118/240 → 125/240) because their
loss is grounding (`ABSENCE_ONLY`), which no template can or should repair.
Whether the two-thirds (T0) or half (T2) mandatory-only rate is acceptable
remains memo H14.

---

## 4. D — H7 nested budget infeasibility: N1 versus N2 (Measured)

**N1** (primary): the pre-answer solve carries the immutable post-answer
mandatory footprint as feasibility witnesses — the `R*` nodes plus, for every
distractor with a showable alternative, at least one alternative node under
`COVER_ALT` — and enforces `|ENTITY_NODES(S_pre ∪ M_post)| ≤ B_post`. The
pre-answer keys are exactly ARCH-2's; the witnesses take no part in them.
**N2** (comparison): the ARCH-3 pre solve unchanged; the post cap is relative,
`mandatory_post_core + K_post_optional`, where the core is the `R*` nodes
plus the minimum alternative footprint. Both under T0 and T2, arm C,
stratified universe at 400, `K_A_post = 0` (and 1 for N1).

**The mandatory core.** Distribution of `R*` nodes + minimum alternative
footprint over the 396 measured items: {'1': 4, '2': 41, '3': 102, '4': 217, '5': 29, '6': 3} (maximum 6).

**N1 sweep, pooled, `K_A_post = 0`:**

| templates | B_pre | B_post | pre status | post status (K_A=0) | nested-infeasible | core-too-large | selected | mean pre optional | mean ENTITY nodes (caption / +class node) | mean optional | mean alt | shared info | distinct keys | alt coverage | items exposing ABSENCE_ONLY | mandatory-only | every distractor has optional |
|---|---:|---:|---|---|---:|---:|---|---:|---|---:|---:|---:|---:|---|---|---|---|
| T0 | 2 | 10 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.5606 | 6.4268 / 7.4268 | 3.0253 | 2.952 | 5.8056 | 3.2652 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 169/396 (42.68%) |
| T0 | 2 | 6 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.5556 | 5.0328 / 6.0328 | 1.7854 | 2.6869 | 3.7121 | 2.6566 | 1143/1143 (100.0%) | 55/396 (13.89%) | 151/396 (38.13%) | 162/396 (40.91%) |
| T0 | 2 | 7 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.5606 | 5.4419 / 6.4419 | 2.1667 | 2.7652 | 4.4091 | 2.8914 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 165/396 (41.67%) |
| T0 | 2 | 8 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.5606 | 5.8106 / 6.8106 | 2.4848 | 2.8384 | 4.9697 | 3.0303 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 167/396 (42.17%) |
| T0 | 2 | 9 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.5606 | 6.1364 / 7.1364 | 2.7677 | 2.899 | 5.4217 | 3.1641 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 169/396 (42.68%) |
| T0 | 3 | 10 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.7146 | 6.4268 / 7.4268 | 3.0328 | 2.9394 | 5.7955 | 3.2702 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 169/396 (42.68%) |
| T0 | 3 | 6 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.6566 | 5.0328 / 6.0328 | 1.803 | 2.6641 | 3.6793 | 2.6566 | 1143/1143 (100.0%) | 55/396 (13.89%) | 151/396 (38.13%) | 162/396 (40.91%) |
| T0 | 3 | 7 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.7146 | 5.4419 / 6.4419 | 2.1641 | 2.7449 | 4.3687 | 2.8712 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 166/396 (41.92%) |
| T0 | 3 | 8 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.7146 | 5.8106 / 6.8106 | 2.4949 | 2.8232 | 4.952 | 3.0278 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 167/396 (42.17%) |
| T0 | 3 | 9 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.7146 | 6.1364 / 7.1364 | 2.7778 | 2.8838 | 5.4116 | 3.1641 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 169/396 (42.68%) |
| T0 | 4 | 10 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.8434 | 6.4268 / 7.4268 | 3.0505 | 2.9217 | 5.7854 | 3.2626 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 169/396 (42.68%) |
| T0 | 4 | 6 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.6995 | 5.0328 / 6.0328 | 1.8182 | 2.654 | 3.6591 | 2.6515 | 1143/1143 (100.0%) | 55/396 (13.89%) | 151/396 (38.13%) | 162/396 (40.91%) |
| T0 | 4 | 7 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.803 | 5.4419 / 6.4419 | 2.1944 | 2.7222 | 4.3333 | 2.8763 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 165/396 (41.67%) |
| T0 | 4 | 8 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.8434 | 5.8106 / 6.8106 | 2.5051 | 2.8005 | 4.9066 | 3.0076 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 167/396 (42.17%) |
| T0 | 4 | 9 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.8434 | 6.1364 / 7.1364 | 2.798 | 2.8662 | 5.3914 | 3.154 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 169/396 (42.68%) |
| T0 | 5 | 10 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.9419 | 6.4268 / 7.4268 | 3.0631 | 2.9141 | 5.7778 | 3.2551 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 169/396 (42.68%) |
| T0 | 5 | 6 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.7071 | 5.0328 / 6.0328 | 1.8207 | 2.654 | 3.6616 | 2.649 | 1143/1143 (100.0%) | 55/396 (13.89%) | 151/396 (38.13%) | 162/396 (40.91%) |
| T0 | 5 | 7 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.8359 | 5.4419 / 6.4419 | 2.202 | 2.7197 | 4.3283 | 2.8687 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 165/396 (41.67%) |
| T0 | 5 | 8 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.9192 | 5.8106 / 6.8106 | 2.5126 | 2.7904 | 4.8838 | 2.9949 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 166/396 (41.92%) |
| T0 | 5 | 9 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.9419 | 6.1364 / 7.1364 | 2.798 | 2.8586 | 5.3712 | 3.1389 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 169/396 (42.68%) |
| T0 | 6 | 10 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.0177 | 6.4268 / 7.4268 | 3.0657 | 2.9066 | 5.7652 | 3.2449 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 169/396 (42.68%) |
| T0 | 6 | 6 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.7071 | 5.0328 / 6.0328 | 1.8207 | 2.654 | 3.6616 | 2.649 | 1143/1143 (100.0%) | 55/396 (13.89%) | 151/396 (38.13%) | 162/396 (40.91%) |
| T0 | 6 | 7 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.8434 | 5.4419 / 6.4419 | 2.2045 | 2.7197 | 4.3308 | 2.8662 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 165/396 (41.67%) |
| T0 | 6 | 8 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.947 | 5.8106 / 6.8106 | 2.5202 | 2.7879 | 4.8838 | 2.9924 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 166/396 (41.92%) |
| T0 | 6 | 9 | {'CE_SELECTED': 132, 'CE_SELECTED_MANDATORY_ONLY': 264} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.9975 | 6.1364 / 7.1364 | 2.8056 | 2.8485 | 5.346 | 3.1338 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 169/396 (42.68%) |
| T2 | 2 | 10 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.8662 | 6.4268 / 7.4268 | 3.0354 | 2.9394 | 5.7955 | 3.2601 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 172/396 (43.43%) |
| T2 | 2 | 6 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.8611 | 5.0328 / 6.0328 | 1.7576 | 2.6717 | 3.649 | 2.6313 | 1143/1143 (100.0%) | 55/396 (13.89%) | 151/396 (38.13%) | 166/396 (41.92%) |
| T2 | 2 | 7 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.8662 | 5.4419 / 6.4419 | 2.1641 | 2.75 | 4.3662 | 2.8965 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 169/396 (42.68%) |
| T2 | 2 | 8 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.8662 | 5.8106 / 6.8106 | 2.4899 | 2.8258 | 4.9318 | 3.0429 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 171/396 (43.18%) |
| T2 | 2 | 9 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 0.8662 | 6.1364 / 7.1364 | 2.7727 | 2.8864 | 5.399 | 3.1616 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 172/396 (43.43%) |
| T2 | 3 | 10 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.1414 | 6.4268 / 7.4268 | 3.048 | 2.9192 | 5.7778 | 3.2601 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 173/396 (43.69%) |
| T2 | 3 | 6 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.0 | 5.0328 / 6.0328 | 1.7753 | 2.649 | 3.6187 | 2.6313 | 1143/1143 (100.0%) | 55/396 (13.89%) | 151/396 (38.13%) | 166/396 (41.92%) |
| T2 | 3 | 7 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.1414 | 5.4419 / 6.4419 | 2.1566 | 2.7197 | 4.2778 | 2.8359 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 171/396 (43.18%) |
| T2 | 3 | 8 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.1414 | 5.8106 / 6.8106 | 2.5025 | 2.8005 | 4.8838 | 3.0404 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 172/396 (43.43%) |
| T2 | 3 | 9 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.1414 | 6.1364 / 7.1364 | 2.7828 | 2.8636 | 5.3737 | 3.1616 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 173/396 (43.69%) |
| T2 | 4 | 10 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.3838 | 6.4268 / 7.4268 | 3.0657 | 2.8939 | 5.75 | 3.2525 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 173/396 (43.69%) |
| T2 | 4 | 6 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.0657 | 5.0328 / 6.0328 | 1.7929 | 2.6389 | 3.5758 | 2.6212 | 1143/1143 (100.0%) | 55/396 (13.89%) | 151/396 (38.13%) | 165/396 (41.67%) |
| T2 | 4 | 7 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.2652 | 5.4419 / 6.4419 | 2.1843 | 2.697 | 4.2348 | 2.8359 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 170/396 (42.93%) |
| T2 | 4 | 8 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.3838 | 5.8106 / 6.8106 | 2.5076 | 2.7702 | 4.7753 | 2.9848 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 172/396 (43.43%) |
| T2 | 4 | 9 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.3838 | 6.1364 / 7.1364 | 2.8005 | 2.8384 | 5.3157 | 3.1439 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 173/396 (43.69%) |
| T2 | 5 | 10 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.5833 | 6.4268 / 7.4268 | 3.0732 | 2.8813 | 5.702 | 3.2323 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 173/396 (43.69%) |
| T2 | 5 | 6 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.0833 | 5.0328 / 6.0328 | 1.798 | 2.6389 | 3.5808 | 2.6212 | 1143/1143 (100.0%) | 55/396 (13.89%) | 151/396 (38.13%) | 165/396 (41.67%) |
| T2 | 5 | 7 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.3157 | 5.4419 / 6.4419 | 2.1944 | 2.6944 | 4.2146 | 2.8283 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 169/396 (42.68%) |
| T2 | 5 | 8 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.4874 | 5.8106 / 6.8106 | 2.5152 | 2.7601 | 4.7525 | 2.9596 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 171/396 (43.18%) |
| T2 | 5 | 9 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.5833 | 6.1364 / 7.1364 | 2.798 | 2.8232 | 5.2298 | 3.0884 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 173/396 (43.69%) |
| T2 | 6 | 10 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.7576 | 6.4268 / 7.4268 | 3.0783 | 2.8636 | 5.6288 | 3.1768 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 173/396 (43.69%) |
| T2 | 6 | 6 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.0909 | 5.0328 / 6.0328 | 1.8005 | 2.6389 | 3.5833 | 2.6212 | 1143/1143 (100.0%) | 55/396 (13.89%) | 151/396 (38.13%) | 165/396 (41.67%) |
| T2 | 6 | 7 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.3333 | 5.4419 / 6.4419 | 2.1995 | 2.6944 | 4.2197 | 2.8283 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 169/396 (42.68%) |
| T2 | 6 | 8 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.5354 | 5.8106 / 6.8106 | 2.5227 | 2.7576 | 4.7298 | 2.952 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 170/396 (42.93%) |
| T2 | 6 | 9 | {'CE_SELECTED': 193, 'CE_SELECTED_MANDATORY_ONLY': 203} | {'CE_SELECTED': 396} | 0 | 0 | 396/396 (100.0%) | 1.6692 | 6.1364 / 7.1364 | 2.798 | 2.8131 | 5.197 | 3.0631 | 1143/1143 (100.0%) | 55/396 (13.89%) | 149/396 (37.63%) | 173/396 (43.69%) |

**N2 sweep, pooled:**

| templates | B_pre | K_post_optional | mean cap | post status | nested-infeasible | selected | mean ENTITY nodes | max ENTITY nodes | mean optional | shared info | distinct keys | alt coverage |
|---|---:|---:|---:|---|---:|---|---:|---:|---:|---:|---:|---|
| T0 | 2 | 2 | 5.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 4.7803 | 7 | 1.601 | 3.2626 | 2.5429 | 1143/1143 (100.0%) |
| T0 | 2 | 3 | 6.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.2096 | 7 | 1.9874 | 4.0429 | 2.7955 | 1143/1143 (100.0%) |
| T0 | 2 | 4 | 7.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.601 | 8 | 2.3384 | 4.6591 | 2.9722 | 1143/1143 (100.0%) |
| T0 | 2 | 5 | 8.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.9495 | 9 | 2.6338 | 5.1515 | 3.1111 | 1143/1143 (100.0%) |
| T0 | 2 | 6 | 9.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 6.2601 | 10 | 2.9015 | 5.5808 | 3.2071 | 1143/1143 (100.0%) |
| T0 | 3 | 2 | 5.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 49, 'CE_SELECTED': 347} | 49 | 347/396 (87.63%) | 4.7118 | 7 | 1.4669 | 2.9251 | 2.4582 | 1005/1005 (100.0%) |
| T0 | 3 | 3 | 6.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.2096 | 7 | 1.9899 | 3.9747 | 2.7702 | 1143/1143 (100.0%) |
| T0 | 3 | 4 | 7.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.601 | 8 | 2.3535 | 4.6338 | 2.9672 | 1143/1143 (100.0%) |
| T0 | 3 | 5 | 8.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.9495 | 9 | 2.6465 | 5.1389 | 3.1086 | 1143/1143 (100.0%) |
| T0 | 3 | 6 | 9.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 6.2601 | 10 | 2.9116 | 5.5707 | 3.2121 | 1143/1143 (100.0%) |
| T0 | 4 | 2 | 5.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 59, 'CE_SELECTED': 337} | 59 | 337/396 (85.1%) | 4.6855 | 7 | 1.3412 | 2.7537 | 2.3591 | 976/976 (100.0%) |
| T0 | 4 | 3 | 6.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 40, 'CE_SELECTED': 356} | 40 | 356/396 (89.9%) | 5.0787 | 7 | 1.8006 | 3.5674 | 2.6573 | 1027/1027 (100.0%) |
| T0 | 4 | 4 | 7.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.601 | 8 | 2.3586 | 4.5682 | 2.9394 | 1143/1143 (100.0%) |
| T0 | 4 | 5 | 8.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.9495 | 9 | 2.6692 | 5.1162 | 3.096 | 1143/1143 (100.0%) |
| T0 | 4 | 6 | 9.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 6.2601 | 10 | 2.9293 | 5.5581 | 3.202 | 1143/1143 (100.0%) |
| T0 | 5 | 2 | 5.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 59, 'CE_SELECTED': 337} | 59 | 337/396 (85.1%) | 4.6855 | 7 | 1.3412 | 2.7537 | 2.3591 | 976/976 (100.0%) |
| T0 | 5 | 3 | 6.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 49, 'CE_SELECTED': 347} | 49 | 347/396 (87.63%) | 5.0375 | 7 | 1.6657 | 3.389 | 2.5533 | 1001/1001 (100.0%) |
| T0 | 5 | 4 | 7.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 25, 'CE_SELECTED': 371} | 25 | 371/396 (93.69%) | 5.4852 | 8 | 2.2022 | 4.2588 | 2.8544 | 1072/1072 (100.0%) |
| T0 | 5 | 5 | 8.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.9495 | 9 | 2.6641 | 5.0884 | 3.0707 | 1143/1143 (100.0%) |
| T0 | 5 | 6 | 9.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 6.2601 | 10 | 2.9394 | 5.5505 | 3.1894 | 1143/1143 (100.0%) |
| T0 | 6 | 2 | 5.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 59, 'CE_SELECTED': 337} | 59 | 337/396 (85.1%) | 4.6855 | 7 | 1.3412 | 2.7537 | 2.3591 | 976/976 (100.0%) |
| T0 | 6 | 3 | 6.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 49, 'CE_SELECTED': 347} | 49 | 347/396 (87.63%) | 5.0375 | 7 | 1.6657 | 3.389 | 2.5533 | 1001/1001 (100.0%) |
| T0 | 6 | 4 | 7.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 32, 'CE_SELECTED': 364} | 32 | 364/396 (91.92%) | 5.4396 | 8 | 2.0852 | 4.1209 | 2.7665 | 1052/1052 (100.0%) |
| T0 | 6 | 5 | 8.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 21, 'CE_SELECTED': 375} | 21 | 375/396 (94.7%) | 5.816 | 9 | 2.4853 | 4.7733 | 2.992 | 1084/1084 (100.0%) |
| T0 | 6 | 6 | 9.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 6.2601 | 10 | 2.9495 | 5.5303 | 3.1793 | 1143/1143 (100.0%) |
| T2 | 2 | 2 | 5.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 4.7803 | 7 | 1.5657 | 3.1869 | 2.5227 | 1143/1143 (100.0%) |
| T2 | 2 | 3 | 6.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.2096 | 7 | 1.9747 | 3.9975 | 2.8005 | 1143/1143 (100.0%) |
| T2 | 2 | 4 | 7.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.601 | 8 | 2.3409 | 4.6187 | 2.9823 | 1143/1143 (100.0%) |
| T2 | 2 | 5 | 8.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.9495 | 9 | 2.6439 | 5.1263 | 3.1136 | 1143/1143 (100.0%) |
| T2 | 2 | 6 | 9.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 6.2601 | 10 | 2.9091 | 5.5657 | 3.202 | 1143/1143 (100.0%) |
| T2 | 3 | 2 | 5.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 94, 'CE_SELECTED': 302} | 94 | 302/396 (76.26%) | 4.5762 | 7 | 1.2318 | 2.394 | 2.298 | 874/874 (100.0%) |
| T2 | 3 | 3 | 6.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.2096 | 7 | 1.9646 | 3.8788 | 2.7222 | 1143/1143 (100.0%) |
| T2 | 3 | 4 | 7.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.601 | 8 | 2.3561 | 4.5657 | 2.9697 | 1143/1143 (100.0%) |
| T2 | 3 | 5 | 8.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.9495 | 9 | 2.654 | 5.0934 | 3.1136 | 1143/1143 (100.0%) |
| T2 | 3 | 6 | 9.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 6.2601 | 10 | 2.9242 | 5.5455 | 3.2045 | 1143/1143 (100.0%) |
| T2 | 4 | 2 | 5.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 105, 'CE_SELECTED': 291} | 105 | 291/396 (73.48%) | 4.5395 | 7 | 1.079 | 2.2062 | 2.1753 | 842/842 (100.0%) |
| T2 | 4 | 3 | 6.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 83, 'CE_SELECTED': 313} | 83 | 313/396 (79.04%) | 4.8754 | 7 | 1.5112 | 2.885 | 2.4728 | 904/904 (100.0%) |
| T2 | 4 | 4 | 7.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.601 | 8 | 2.351 | 4.4318 | 2.8965 | 1143/1143 (100.0%) |
| T2 | 4 | 5 | 8.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.9495 | 9 | 2.6717 | 5.0328 | 3.0884 | 1143/1143 (100.0%) |
| T2 | 4 | 6 | 9.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 6.2601 | 10 | 2.9394 | 5.5076 | 3.1995 | 1143/1143 (100.0%) |
| T2 | 5 | 2 | 5.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 105, 'CE_SELECTED': 291} | 105 | 291/396 (73.48%) | 4.5395 | 7 | 1.079 | 2.2062 | 2.1753 | 842/842 (100.0%) |
| T2 | 5 | 3 | 6.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 93, 'CE_SELECTED': 303} | 93 | 303/396 (76.52%) | 4.8152 | 7 | 1.3399 | 2.6403 | 2.3432 | 875/875 (100.0%) |
| T2 | 5 | 4 | 7.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 64, 'CE_SELECTED': 332} | 64 | 332/396 (83.84%) | 5.238 | 8 | 1.8976 | 3.4699 | 2.6988 | 958/958 (100.0%) |
| T2 | 5 | 5 | 8.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 5.9495 | 9 | 2.6591 | 4.9419 | 3.0076 | 1143/1143 (100.0%) |
| T2 | 5 | 6 | 9.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 6.2601 | 10 | 2.9444 | 5.4596 | 3.1717 | 1143/1143 (100.0%) |
| T2 | 6 | 2 | 5.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 105, 'CE_SELECTED': 291} | 105 | 291/396 (73.48%) | 4.5395 | 7 | 1.079 | 2.2062 | 2.1753 | 842/842 (100.0%) |
| T2 | 6 | 3 | 6.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 93, 'CE_SELECTED': 303} | 93 | 303/396 (76.52%) | 4.8152 | 7 | 1.3399 | 2.6403 | 2.3432 | 875/875 (100.0%) |
| T2 | 6 | 4 | 7.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 73, 'CE_SELECTED': 323} | 73 | 323/396 (81.57%) | 5.1672 | 8 | 1.7461 | 3.226 | 2.5944 | 932/932 (100.0%) |
| T2 | 6 | 5 | 8.5934 | {'CE_NESTED_INFEASIBLE_AT_BUDGET': 58, 'CE_SELECTED': 338} | 58 | 338/396 (85.35%) | 5.5148 | 9 | 2.1213 | 3.8521 | 2.8314 | 976/976 (100.0%) |
| T2 | 6 | 6 | 9.5934 | {'CE_SELECTED': 396} | 0 | 396/396 (100.0%) | 6.2601 | 10 | 2.9394 | 5.3813 | 3.0909 | 1143/1143 (100.0%) |

**N1 at the designated cell by cohort group and template set:**

| group | items | templates | core nodes dist | B_pre 4 / B_post 6: core-too-large | B_post 7 | B_post 8 | selected at (4,7) | mean nodes (4,7) | mean optional (4,7) | shared info (4,7) | alt coverage (4,7) |
|---|---:|---|---|---:|---:|---:|---|---:|---:|---:|---|
| POOLED | 396 | T0 | {'1': 4, '2': 41, '3': 102, '4': 217, '5': 29, '6': 3} | 0 | 0 | 0 | 396/396 (100.0%) | 5.4419 | 2.1944 | 4.3333 | 1143/1143 (100.0%) |
| POOLED | 396 | T2 | {'1': 4, '2': 41, '3': 102, '4': 217, '5': 29, '6': 3} | 0 | 0 | 0 | 396/396 (100.0%) | 5.4419 | 2.1843 | 4.2348 | 1143/1143 (100.0%) |
| GROUP:CHEMISTRY | 40 | T0 | {'2': 4, '3': 12, '4': 20, '5': 3, '6': 1} | 0 | 0 | 0 | 40/40 (100.0%) | 4.65 | 0.45 | 3.025 | 119/119 (100.0%) |
| GROUP:CHEMISTRY | 40 | T2 | {'2': 4, '3': 12, '4': 20, '5': 3, '6': 1} | 0 | 0 | 0 | 40/40 (100.0%) | 4.65 | 0.525 | 2.85 | 119/119 (100.0%) |
| GROUP:EVENT | 34 | T0 | {'2': 3, '3': 14, '4': 13, '5': 4} | 0 | 0 | 0 | 34/34 (100.0%) | 4.4706 | 0.2353 | 2.0 | 101/101 (100.0%) |
| GROUP:EVENT | 34 | T2 | {'2': 3, '3': 14, '4': 13, '5': 4} | 0 | 0 | 0 | 34/34 (100.0%) | 4.4706 | 0.2941 | 2.0 | 101/101 (100.0%) |
| GROUP:PERSON | 240 | T0 | {'1': 4, '2': 26, '3': 69, '4': 119, '5': 20, '6': 2} | 0 | 0 | 0 | 240/240 (100.0%) | 5.4208 | 2.4458 | 4.3417 | 682/682 (100.0%) |
| GROUP:PERSON | 240 | T2 | {'1': 4, '2': 26, '3': 69, '4': 119, '5': 20, '6': 2} | 0 | 0 | 0 | 240/240 (100.0%) | 5.4208 | 2.4375 | 4.3417 | 682/682 (100.0%) |
| GROUP:PLACE | 47 | T0 | {'2': 7, '3': 3, '4': 37} | 0 | 0 | 0 | 47/47 (100.0%) | 6.4468 | 3.4255 | 7.7872 | 138/138 (100.0%) |
| GROUP:PLACE | 47 | T2 | {'2': 7, '3': 3, '4': 37} | 0 | 0 | 0 | 47/47 (100.0%) | 6.4468 | 3.2979 | 7.234 | 138/138 (100.0%) |
| GROUP:POLITY | 35 | T0 | {'2': 1, '3': 4, '4': 28, '5': 2} | 0 | 0 | 0 | 35/35 (100.0%) | 6.0857 | 2.7143 | 3.4 | 103/103 (100.0%) |
| GROUP:POLITY | 35 | T2 | {'2': 1, '3': 4, '4': 28, '5': 2} | 0 | 0 | 0 | 35/35 (100.0%) | 6.0857 | 2.6857 | 3.2286 | 103/103 (100.0%) |

**Reading.** N1 removes nested infeasibility entirely: at every
`(B_pre, B_post)` cell the nested-infeasible count is 0 and no item has a
mandatory core larger than any `B_post ≥ 6`, because the core never exceeds
6 nodes (|R*| ≤ 3 plus at most three alternative nodes). The
smallest absolute `B_post` in the sweep at which N1 has no infeasibility of
either kind is therefore **6**; at `B_post = 5` the {'1': 4, '2': 41, '3': 102, '4': 217, '5': 29, '6': 3} distribution
implies 3 core-too-large items (core 6) and at `B_post = 4` 32 (cores 5 and 6). The price of node
awareness is small and explicit: at (4, 7) the mean pre-answer optional
selection is 0.803 groups under T0 against 0.8561 in ARCH-3's
non-node-aware solve at the same `B_pre` (1.2652 under T2); the low
count comes from admissibility (only 132 of the items have any arm-C
group at T0), the small remaining difference from the solver refusing pre
clues whose nodes would crowd out the alternatives. N2 does not remove infeasibility until `K ≥ 4`
(`K = 2`: 59 nested-infeasible under T0, 105 under T2; `K = 3`:
40 / 83), and at `K = 4` its graphs range up to 8
ENTITY nodes (mean 5.601) — a variable cap that no longer "limits the
number of right-side nodes", which the research requirement asks for. The
absolute cap with node-aware pre selection is the repair that keeps that
requirement; raising the cap alone is not, and N2 is reported as the
comparison arm only. Among the absolute values, 6 is the feasibility floor,
7 gives 5.4419 mean ENTITY nodes (2.1944 optional groups,
shared-information 4.3333) and 8 gives 5.8106 (2.5051,
4.9066); the choice among them is the researcher's (memo H7).

---

## 5. E — `K_A_post` 0 versus 1 under N1 (Measured)

| templates | group | items where K_A_post=0 and 1 select different post sets | mean Answer-only optional at K_A=1 | mean optional K_A=0 / 1 | shared info K_A=0 / 1 | items exposing ABSENCE_ONLY K_A=0 / 1 |
|---|---|---|---:|---|---|---|
| T0 | POOLED | 15/396 (3.79%) | 0.0379 | 2.1944 / 2.2146 | 4.3333 / 4.3333 | 55/396 (13.89%) / 55/396 (13.89%) |
| T0 | GROUP:CHEMISTRY | 0/40 (0.0%) | 0.0 | 0.45 / 0.45 | 3.025 / 3.025 | 7/40 (17.5%) / 7/40 (17.5%) |
| T0 | GROUP:EVENT | 0/34 (0.0%) | 0.0 | 0.2353 / 0.2353 | 2.0 / 2.0 | 6/34 (17.65%) / 6/34 (17.65%) |
| T0 | GROUP:PERSON | 10/240 (4.17%) | 0.0417 | 2.4458 / 2.4708 | 4.3417 / 4.3417 | 35/240 (14.58%) / 35/240 (14.58%) |
| T0 | GROUP:PLACE | 3/47 (6.38%) | 0.0638 | 3.4255 / 3.4681 | 7.7872 / 7.7872 | 3/47 (6.38%) / 3/47 (6.38%) |
| T0 | GROUP:POLITY | 2/35 (5.71%) | 0.0571 | 2.7143 / 2.7143 | 3.4 / 3.4 | 4/35 (11.43%) / 4/35 (11.43%) |
| T2 | POOLED | 15/396 (3.79%) | 0.0379 | 2.1843 / 2.2045 | 4.2348 / 4.2348 | 55/396 (13.89%) / 55/396 (13.89%) |
| T2 | GROUP:CHEMISTRY | 0/40 (0.0%) | 0.0 | 0.525 / 0.525 | 2.85 / 2.85 | 7/40 (17.5%) / 7/40 (17.5%) |
| T2 | GROUP:EVENT | 0/34 (0.0%) | 0.0 | 0.2941 / 0.2941 | 2.0 / 2.0 | 6/34 (17.65%) / 6/34 (17.65%) |
| T2 | GROUP:PERSON | 9/240 (3.75%) | 0.0375 | 2.4375 / 2.4583 | 4.3417 / 4.3417 | 35/240 (14.58%) / 35/240 (14.58%) |
| T2 | GROUP:PLACE | 4/47 (8.51%) | 0.0851 | 3.2979 / 3.3617 | 7.234 / 7.234 | 3/47 (6.38%) / 3/47 (6.38%) |
| T2 | GROUP:POLITY | 2/35 (5.71%) | 0.0571 | 2.6857 / 2.6857 | 3.2286 / 3.2286 | 4/35 (11.43%) / 4/35 (11.43%) |

**Reading.** At the designated N1 cell the two settings select different
post sets in 15/396 (3.79%) items (T0; 15/396 (3.79%) under T2), the mean number of
Answer-only optional groups admitted at `K_A_post = 1` is 0.0379, and
shared information and `ABSENCE_ONLY` exposure are identical. There is no
measurable context benefit to buy with the extra rule; `K_A_post = 0`, the
simplicity candidate, is supported. Still memo H4.

---

## 6. F — H18 extension on the hard items (Measured)

Items with more than 800 optional groups (43 items; all places,
polities, events and persons above that size, including the 15 that ARCH-3
never solved at FULL). N1 pre at (4, 7, `K_A_post` 0), arm C, T0, stratified
bounding at 800, 1600, 3200 and the FULL optional universe.

| group | items | optional max | FULL solved | FULL seconds median / max | FULL max variables | 800→1600 both equal | 1600→3200 | 3200→FULL | equal to FULL at 800 | at 1600 | at 3200 |
|---|---:|---:|---|---|---:|---|---|---|---|---|---|
| POOLED | 43 | 4921 | 43/43 (100.0%) | 3.6 / 73.36 | 9759 | 41/43 (95.35%) | 26/29 (89.66%) | 11/14 (78.57%) | 36/43 (83.72%) | 24/29 (82.76%) | 11/14 (78.57%) |
| GROUP:EVENT | 4 | 2513 | 4/4 (100.0%) | 1.84 / 8.49 | 5148 | 4/4 (100.0%) | 3/3 (100.0%) | 0/0 (None%) | 4/4 (100.0%) | 3/3 (100.0%) | 0/0 (None%) |
| GROUP:PERSON | 5 | 1338 | 5/5 (100.0%) | 0.7 / 0.81 | 2252 | 5/5 (100.0%) | 0/0 (None%) | 0/0 (None%) | 5/5 (100.0%) | 0/0 (None%) | 0/0 (None%) |
| GROUP:PLACE | 23 | 4921 | 23/23 (100.0%) | 6.53 / 18.84 | 9759 | 22/23 (95.65%) | 17/18 (94.44%) | 9/10 (90.0%) | 20/23 (86.96%) | 16/18 (88.89%) | 9/10 (90.0%) |
| GROUP:POLITY | 11 | 4835 | 11/11 (100.0%) | 5.13 / 73.36 | 9443 | 10/11 (90.91%) | 6/8 (75.0%) | 2/4 (50.0%) | 7/11 (63.64%) | 5/8 (62.5%) | 2/4 (50.0%) |

| group | step | items bounded & solved | S_pre equal | S_post equal | mean post Jaccard | earliest differing key |
|---|---|---:|---|---|---:|---|
| POOLED | 1600->3200 | 29 | 29/29 (100.0%) | 26/29 (89.66%) | 0.9557 | {'post:neg_distinct_keys': 1, 'post:token_sum': 2} |
| POOLED | 3200->FULL | 14 | 14/14 (100.0%) | 11/14 (78.57%) | 0.9454 | {'post:CANONICAL_TIE_BREAK': 1, 'post:neg_distinct_keys': 1, 'post:token_sum': 1} |
| POOLED | 800->1600 | 43 | 43/43 (100.0%) | 41/43 (95.35%) | 0.9809 | {'post:neg_distinct_keys': 1, 'post:token_sum': 1} |
| GROUP:EVENT | 1600->3200 | 3 | 3/3 (100.0%) | 3/3 (100.0%) | 1.0 | {} |
| GROUP:EVENT | 3200->FULL | 0 | 0/0 (None%) | 0/0 (None%) | None | {} |
| GROUP:EVENT | 800->1600 | 4 | 4/4 (100.0%) | 4/4 (100.0%) | 1.0 | {} |
| GROUP:PERSON | 1600->3200 | 0 | 0/0 (None%) | 0/0 (None%) | None | {} |
| GROUP:PERSON | 3200->FULL | 0 | 0/0 (None%) | 0/0 (None%) | None | {} |
| GROUP:PERSON | 800->1600 | 5 | 5/5 (100.0%) | 5/5 (100.0%) | 1.0 | {} |
| GROUP:PLACE | 1600->3200 | 18 | 18/18 (100.0%) | 17/18 (94.44%) | 0.9815 | {'post:neg_distinct_keys': 1} |
| GROUP:PLACE | 3200->FULL | 10 | 10/10 (100.0%) | 9/10 (90.0%) | 0.975 | {'post:neg_distinct_keys': 1} |
| GROUP:PLACE | 800->1600 | 23 | 23/23 (100.0%) | 22/23 (95.65%) | 0.9837 | {'post:neg_distinct_keys': 1} |
| GROUP:POLITY | 1600->3200 | 8 | 8/8 (100.0%) | 6/8 (75.0%) | 0.881 | {'post:token_sum': 2} |
| GROUP:POLITY | 3200->FULL | 4 | 4/4 (100.0%) | 2/4 (50.0%) | 0.8712 | {'post:CANONICAL_TIE_BREAK': 1, 'post:token_sum': 1} |
| GROUP:POLITY | 800->1600 | 11 | 11/11 (100.0%) | 10/11 (90.91%) | 0.9596 | {'post:token_sum': 1} |

FULL solve failures: []

**Reading.** The full optional universe is computationally feasible for every
hard item: 43/43 (100.0%) solved at FULL, median 3.6 s, maximum
73.36 s, at most 9759 variables. Stability at doubling improves
with the bound (41/43 (95.35%) at 800→1600, 26/29 (89.66%) at 1600→3200, 11/14 (78.57%) at
3200→FULL) but the largest items keep changing at every level, always at
the late keys (distinct keys, tokens, canonical ties) and never before
answering: no global stratified `N_max` in the sweep reproduces the FULL
selection in at least 95 % of the bounded items (equal to FULL: 36/43 (83.72%)
at 800, 24/29 (82.76%) at 1600, 11/14 (78.57%) at 3200; polities 7/11 (63.64%) at 800,
places 20/23 (86.96%)). Comparing the three options the prompt names: a single
global bound is not defensible at 95 % for polities; a declared bounded scope
for the few unstable polities is defensible but adds a scope flag to the
paper; cohort-dependent bounds are the least simple. The measurement makes a
fourth option the simplest of all: **no bound — `UNIVERSE_FULL` for every
item**, which is exact by definition and costs at most about a minute per
item on the largest polity with the installed solver. Bounding then survives
only as a declared fallback for a size no development item reached. This is
a recommendation for memo H18, not a decision.

---

## 7. G — sensitivity under N1 (Measured; no permutation search)

| exposure | swap | selection changed | mean Jaccard | earliest differing key |
|---|---|---|---:|---|
| post | swap_0_1 | 0/396 (0.0%) | 1.0 | {} |
| post | swap_1_2 | 14/396 (3.54%) | 0.9913 | {'risk_groups': 14} |
| post | swap_2_3 | 54/396 (13.64%) | 0.9463 | {'neg_shared_information': 54} |
| post | swap_3_4 | 58/396 (14.65%) | 0.9502 | {'neg_distinct_keys': 58} |
| post | swap_4_5 | 0/396 (0.0%) | 1.0 | {} |
| post | swap_5_6 | 3/396 (0.76%) | 0.9972 | {'tier_sum': 3} |
| pre | swap_0_1 | 1/396 (0.25%) | — | — |
| pre | swap_1_2 | 4/396 (1.01%) | — | — |
| pre | swap_2_3 | 1/396 (0.25%) | — | — |
| pre | swap_3_4 | 0/396 (0.0%) | — | — |
| pre | swap_4_5 | 0/396 (0.0%) | — | — |

**Reading.** Unchanged from ARCH-3: before answering the candidate order is
insensitive to every adjacent swap (≤ 1 %); after answering only shared
information ↔ distinct keys (54/396 (13.64%)) and distinct keys ↔ ENTITY nodes
(58/396 (14.65%)) move selections, with `ABSENCE_ONLY` ↔ risk at 14/396 (3.54%). The
candidate post order (absence, risk, shared information, diversity,
compactness, tier, tokens, canonical) stays as declared; the two swaps that
matter are the pedagogical trade-off memo H13 asks the researcher to order.

**Solver evidence for this task (H6).** Budget stage: {'calls': 1019586, 'n_vars_max': 3959, 'seconds_total': 5882.6, 'status_counts': {'INFEASIBLE': 1315, 'OPTIMAL': 1018271}}; bounding
stage: every FULL solve certified optimal, at most 9759 variables.
Every recorded infeasible status is an N2 nested-infeasible cell.

---

## 8. Required final verdict

**H decisions now strongly supported by measurement** (still to be
recorded by the researcher, not signed here):

* **H6** — the installed HiGHS/scipy exact route: more than a million
  certified optimal solves across ARCH-3 and this task, zero re-check
  failures, oracle agreement, deterministic reruns, FULL universes of up to
  9759 variables in about a minute.
* **H7** — N1 (absolute ENTITY-node cap with node-aware pre selection)
  removes nested infeasibility at every cell; `B_post = 6` is the measured
  feasibility floor; the value among 6/7/8 is the remaining choice.
* **H4** — `K_A_post = 0`: no measurable benefit from 1.
* **H13** — hard constraints + strict lexicographic keys, ε = 0: stable
  before answering; the two post-answer swaps that matter are known.
* **H18** — `UNIVERSE_FULL` is feasible everywhere; no global `N_max` is
  needed; if a bound is kept it is a declared fallback.
* **H14 arm C** — costs nothing beyond arm B on this data.
* **H2** — the grounding rule reproduces the frozen classifier on
  282,933/282,933 pairs (ARCH-3).
* **H1, H8a, H10, H12** — unchanged from ARCH-2, untouched by any measurement.

**Genuine human scientific choices that remain:**

* **H5** — adopt Phase 1 (five templates), Phases 1–2 (48), and decide the
  29 review keys; whether neutral readings are acceptable prose.
* **H14** — accept a mandatory-only pre-answer rate of 264/396 (66.67%) (T0) or
  203/396 (51.26%) (T2) as the price of grounding-clean clues.
* **H7** — the absolute `B_post` among 6, 7, 8 (and `B_pre`).
* **H3, H8b, H11, H15, H16, H17** — pedagogical and protocol choices no
  measurement decides.

**Does template expansion remove enough of the H5/H14 bottleneck?** For H5,
yes: 130/396 (32.83%) of the 396 items recover a fully verbalizable `R*` under
T2 and only 46/396 (11.62%) remain, on keys that need a human. For H14, partly:
pre-answer context rises from 132/396 (33.33%) to 193/396 (48.74%) items, concentrated in the
place and polity cohorts; the person-cohort loss is grounding, not templates.

**Does N1 fix nested infeasibility and what `B_post` is supported?** Yes,
completely, by construction and by measurement; `B_post = 6` is the floor at
which no development item is infeasible, and 7 keeps the ARCH-3 designated
value with 5.4419 mean ENTITY nodes.

**Is a global stratified `N_max` defensible?** Not at 95 % for polities; but
it is unnecessary, because FULL is feasible for every item.

**Verdict: READY_FOR_ARCH4_SPEC_FREEZE.** No measured technical blocker
remains: the packaging protocol is repaired and verified on both archives,
the nested-budget defect has an exact repair with measured behaviour, the
universe bound can be dropped, and template coverage has a versioned,
measured expansion plan whose adoption is independent of the mathematical
specification (the specification must state that pre-answer admissibility
reads the template registry version in force). What the freeze must carry
explicitly, because no measurement decides it: the researcher's recorded
choices for H3, H4, H5, H7 (`B_post`), H8b, H11, H13 (order), H14, H15, H16,
H17; the two upstream issues that still block the **publication run** but not
the specification (the `granularity_clean` report-only status defect and the
main-L1/unverbalizable contradiction, both ARCH-1 §20); and the rule that
every sweep here is re-run if the frozen upstream publication configuration
or the template registry version changes.

---

## 9. Files, checks and reproduction

**Created**: `scripts/audit_b3_pre_freeze_resolution.py`; this report, its
`.summary.json`, `B3_TEMPLATE_COVERAGE_EXPANSION_PLAN_2026-09-19.md`;
`outputs/journal2_b3_pre_freeze_resolution_2026-09-19/` (census, key
sources, candidate file, `template_coverage_T0_T1_T2.csv`,
`template_coverage_rollup.json`, `template_coverage_secondary_T2_reselection.*`,
`n1_n2_budget_repair.csv` and rollup, `h18_extension.csv` and rollup,
`package_integrity/` (pre-repackage digests and the ARCH-3 archive check),
`budget/`, `bounding/`, `logs/`, `run_manifest.json`, `REPRODUCE.md`,
`CONTENT_MANIFEST.json`, `SHA256SUMS.*`) and its archive with the external
`.zip.sha256` and `.ARCHIVE_DIGEST.json`.
**Modified**: `scripts/audit_b3_choice_evidence_decisions.py` (packaging
stage only: `build_package()`, `measurement_script_sha256`); the ARCH-3
evidence directory's manifest and content-manifest files and its rebuilt
archive (scientific rollups verified byte-identical). Nothing tracked by git
was modified; no frozen module, no v1–v4 output, no cache, no memo line, no
production registry.
**Checks run**: `py_compile` on both scripts; `json.load` on every JSON
deliverable; `testzip()` and external-digest verification on both archives;
CONTENT_MANIFEST inside == on disk for both; stale `zip_manifest.json`
absent; ARCH-3 rollups byte-identical; `git status --short` (tracked changes:
none). No pytest suite: no production source changed.

```bash
cd /home/thuy/projects/mcq_journal2
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
python scripts/audit_b3_choice_evidence_decisions.py --stage package        # rebuilds the ARCH-3 archive
python scripts/audit_b3_pre_freeze_resolution.py --stage census
python scripts/audit_b3_pre_freeze_resolution.py --stage candidates
python scripts/audit_b3_pre_freeze_resolution.py --stage coverage
python scripts/audit_b3_pre_freeze_resolution.py --stage coverage-secondary --workers 12
python scripts/audit_b3_pre_freeze_resolution.py --stage budget --workers 12
python scripts/audit_b3_pre_freeze_resolution.py --stage bounding --workers 12
python scripts/audit_b3_pre_freeze_resolution.py --stage rollup
python scripts/audit_b3_pre_freeze_resolution.py --stage package
```
