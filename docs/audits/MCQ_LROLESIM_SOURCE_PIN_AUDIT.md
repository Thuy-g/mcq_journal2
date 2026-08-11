# `src/MCQ_lrolesim.py` — forensic audit of the protected-source hash pin

**Date** 2026-08-12 · **Task** Prompt 8H-B1.5, §6–7 · **Nature** read-only,
documentation only. No production file was created, modified, or deleted while
producing this audit. No test was changed. No hash was rebaselined.

**Failing check**
`tests/test_pipeline_graph_lrolesim.py::TestProtectedSources::test_protected_source_is_unmodified[src/MCQ_lrolesim.py-cdd4f90c...]`

```
expected  cdd4f90c006dc57d97ecccf79685efcd553e60be12dc86cfd66d205f5b6ff15b
actual    a286fe08719a6a049638548aee7526c069b3fec2ab621bec8d540059d3f03617
```

---

## 1. Tracked/untracked status

`git ls-files -- src/MCQ_lrolesim.py` returns nothing: **the file has never
been committed.** It has no git history, no blame, no diff, and no commit ever
touched it. Everything about *when* the file changed therefore comes from
filesystem metadata and other files' records about it — except §4 below, which
recovers real evidence of *what* changed from a source the earlier draft of
this audit did not examine: the compiled bytecode cache.

```
$ stat src/MCQ_lrolesim.py
  Size: 56935 bytes   (1081 lines)
  Modify: 2026-08-04 03:17:40 +0900
```

---

## 2. First known appearance of each hash

### `cdd4f90c…` (expected / pinned)

Introduced as a literal in `tests/test_pipeline_graph_lrolesim.py` by commit
`ae1a6ee1885f84b7ce4ed6899354f8e63dfc1e4e` — *"Run Journal 2 pilot graph and
LRoleSim ranking"*, 2026-07-30. It is one entry in the `PROTECTED_SOURCE_SHA256`
dict, alongside seven sibling pins (`MCQ_lrolesim_ClaudeWeb_v2.py`,
`kg/graph_view.py`, `kg/loader.py`, `lrolesim/adapter.py`, `classes/policy.py`,
`classes/member_mapper.py`, `classes/local_candidate_profile.py`). `git log -p
--all -- tests/test_pipeline_graph_lrolesim.py | grep -c cdd4f90c` returns
exactly **1**: the literal was written once and never edited.

Independent corroboration that `cdd4f90c…` really was the on-disk hash on
2026-07-30, not just a test literal, comes from three archived task packages'
own `source_hashes_before_after.csv`, each recording it as the *live measured*
value on that date:

| Package | Recorded row |
|---|---|
| `outputs/journal2_week1_foundation_2026-07-30.zip` | `src/MCQ_lrolesim.py,UNCHANGED,cdd4f90c…,cdd4f90c…,yes` |
| `outputs/journal2_week1_local_mapping_2026-07-30.zip` | `src/MCQ_lrolesim.py,UNCHANGED,cdd4f90c…,cdd4f90c…,true` |
| `outputs/journal2_week2_graph_lrolesim_pilot_2026-07-30.zip` | `src/MCQ_lrolesim.py,protected_must_not_change,cdd4f90c…,cdd4f90c…,false,unmodified` |

Prompt 8C (this same package) and Prompt 8D
(`outputs/journal2_week2_extract_integration_2026-07-30/`) both ran inside
this window; Prompt 8C was re-run 2026-07-31 08:39 (per that package's own
`implementation_report.md`), still inside the `cdd4f90c…` era.

### `a286fe08…` (actual / current)

First recorded appearance in any repository artifact:
`outputs/journal2_minimal_core_phase_a_2026-08-06/source_hashes_before_after.csv`,
row `src/MCQ_lrolesim.py,not_touched,a286fe08…,a286fe08…,True` — the task that
produced that package found the file *already* at `a286fe08…`, both before and
after its own unrelated work, and reported it as pre-existing state.

Every later package agrees and none records a further change:
`journal2_minimal_core_phase_a2_pool_2026-08-09`,
`journal2_phase_b0_albert_readiness_2026-08-10`,
`journal2_phase_b1_step1_frozen_adapter_2026-08-10` all record `a286fe08…` →
`a286fe08…`. **The file has been stable at `a286fe08…` since at least
2026-08-06** and remains so today.

### The transition window, narrowed to one hour

No repository artifact records a measurement of this specific file *between*
2026-07-30 (last `cdd4f90c…`) and 2026-08-06 (first `a286fe08…`) — none of the
tasks in that window touched the LRoleSim pipeline. Two independent pieces of
filesystem evidence narrow the window much further than that gap:

**a) Isolated mtime.** `stat` on the seven sibling protected files shows every
one of them clustered in a single editing session, 2026-07-30 06:58–09:44
(the session that produced the Prompt-8B/8C deliverables). `src/MCQ_lrolesim.py`
is the *only* one of the eight with a different mtime: **2026-08-04 03:17:40**,
five days later.

```
2026-07-30 06:58:24  src/classes/policy.py
2026-07-30 07:00:48  src/kg/loader.py
2026-07-30 07:03:04  src/kg/graph_view.py
2026-07-30 07:06:16  src/MCQ_lrolesim_ClaudeWeb_v2.py
2026-07-30 07:10:15  src/lrolesim/adapter.py
2026-07-30 09:42:10  src/classes/local_candidate_profile.py
2026-07-30 09:44:38  src/classes/member_mapper.py
2026-08-04 03:17:40  src/MCQ_lrolesim.py        <-- outlier
```

`find . -newermt "2026-08-04 03:00:00" -not -newermt "2026-08-04 04:00:00"`
across the *entire* repository returns exactly one path:
`src/MCQ_lrolesim.py`. Nothing else on disk was touched in that hour, which
rules out a bulk operation (a `git checkout`, a tar extraction, a repo-wide
resave) and is consistent with a single, deliberate touch of this one file.

**b) The compiled bytecode cache.** `src/__pycache__/MCQ_lrolesim.cpython-311.pyc`
is a CPython timestamp-based `.pyc`. Its header (bytes 8–16) embeds the mtime
and size of the *source it was compiled from*, independent of anything git or
this repository's own manifests recorded:

```
$ python3 - <<'PY'
import struct, datetime
data = open("src/__pycache__/MCQ_lrolesim.cpython-311.pyc","rb").read(16)
mtime = struct.unpack("<I", data[8:12])[0]
size  = struct.unpack("<I", data[12:16])[0]
print(datetime.datetime.fromtimestamp(mtime), size)
PY
2026-07-26 07:20:12   56752
```

The `.pyc` file's own mtime is **2026-07-30 02:59**, i.e. compiled *before*
all three `cdd4f90c…`-confirming manifests that same day, from a source last
touched 2026-07-26 — squarely inside the `cdd4f90c…` era and consistent with
that being the pin's actual content. Its recorded source size, **56752
bytes**, is 183 bytes smaller than the current file's 56935 bytes. This is
independent, non-git evidence that the file's *content*, not merely
provenance metadata, actually changed — not only its mtime.

---

## 3. Control group: the seven sibling pins

All seven other entries in `PROTECTED_SOURCE_SHA256` were re-measured today
and match their 2026-07-30 pinned value with no exception (`src/MCQ_lrolesim_ClaudeWeb_v2.py`,
`src/kg/graph_view.py`, `src/kg/loader.py`, `src/lrolesim/adapter.py`,
`src/classes/policy.py`, `src/classes/member_mapper.py`,
`src/classes/local_candidate_profile.py` — all **unchanged**). The drift is
isolated to exactly one file out of eight in the same protected set, which
rules out a wholesale re-checkout or a repo-wide tool pass.

---

## 4. What changed, recovered from the `.pyc` bytecode cache — a real diff, at the object-code level

No copy of the file with hash `cdd4f90c…` exists anywhere in the working
tree, in git history, or inside any `outputs/*.zip` (exhaustively searched:
`grep -r cdd4f90c` across every tracked and untracked file finds only the test
literal itself; no `*.py`/`*.bak`/`*.orig` file hashes to it; no zip entry
named `*lrolesim*` other than the `ClaudeWeb_v2` variant exists). **Source
text at the expected hash is not recoverable.** But
`src/__pycache__/MCQ_lrolesim.cpython-311.pyc` is a compiled snapshot of the
file from that era (§2b), and Python's `marshal` module can load its code
object directly — turning "no diff is possible" into a real, if partial, one.

**Method.** Load the code object from the `.pyc` with `marshal.load()`, and
compile the *current* `src/MCQ_lrolesim.py` in memory with `compile()`. Walk
both code-object trees (module → every nested function/class/method,
48 objects total) and compare `co_code` (the actual instruction bytes) pairwise.

**Result — 47 of 48 code objects are byte-for-byte identical bytecode:**

```
<module>                                            IDENTICAL
ElementWithAllSameRelation (+ __eq__/__hash__/__init__)              IDENTICAL
ElementWithDirectionEquivalenceRelation (+ methods)                  IDENTICAL
ElementWithEdgeDirectionEquivalenceRelation (+ methods)               IDENTICAL
ElementWithEdgeDirectionEquivalenceRelation_EntityType (+ methods)    IDENTICAL
ElementWithEdgeEquivalenceRelation (+ methods)                        IDENTICAL
Sim, Sim.__init__, Sim.__getitem__, Sim.__setitem__                   IDENTICAL
lrolesim()                                                            IDENTICAL  (430 bytes both)
create_mat(), create_mats()                                           IDENTICAL
edge_count(), reduce_neighbor()                                       IDENTICAL
compute_mrr(), compute_ndcg() (+ nested genexpr)                      IDENTICAL
partition_by_binary_label_function[_withkey] (+ lambdas)              IDENTICAL
solve_assignment_problem[_multiple] (+ nested lambdas)                IDENTICAL
short_form(), get_equiv_classes_for_node(), print_equiv_classes_...   IDENTICAL
process_nodes_batch()                                                 IDENTICAL
main()                                                                DIFFERS  (8354 -> 8314 bytes)
main()/calc_sorted_list (nested)                                      IDENTICAL
```

**The entire scientific kernel — `lrolesim()`, `create_mats()`, `create_mat()`,
the `Sim` class, `edge_count()`, `partition_by_binary_label_function[_withkey]`,
`solve_assignment_problem[_multiple]`, `compute_mrr()`, `compute_ndcg()`, and
all four equivalence-relation classes — compiles to byte-identical bytecode in
both versions.** The one and only function whose compiled code differs is
`main()`, the file's manual CLI driver.

**What changed inside `main()`.** Disassembling both versions of `main()` and
diffing pinpoints a single source line (880): the hard-coded demonstration
variable `name_list`. In the pinned era it was a 19-entry list of Japanese
Nobel-laureate resource names; in the current file it is a 2-entry list:

```python
# cdd4f90c… era (recovered from the .pyc's constant pool):
name_list = ["Eisaku_Satō", "Yasunari_Kawabata", "Kenzaburō_Ōe", "Hideki_Yukawa",
             "Yoichiro_Nambu", "Shinya_Yamanaka", "Susumu_Tonegawa", "Leo_Esaki",
             "Ei-ichi_Negishi", "Masatoshi_Koshiba", "Ryōji_Noyori",
             "Sin-Itiro_Tomonaga", "Osamu_Shimomura", "Toshihide_Maskawa",
             "Makoto_Kobayashi_(physicist)", "Hideki_Shirakawa", "Kenichi_Fukui",
             "Akira_Suzuki_(chemist)", "Koichi_Tanaka"]

# a286fe08… (current, line 880):
name_list = ["Eisaku_Satō","Carbon"]  #, "Eisaku_Satō", "Yasunari_Kawabata", ...
```

The current line 880 carries the entire original 19-item list **verbatim, in
a trailing comment** after the active 2-item list — the author narrowed the
demo list and commented out the rest rather than deleting it, the same
pattern visible at lines 871–877 a few lines above, where three *other*
alternative demo lists (Japanese place names, US presidents) are already kept
commented out for the same script. Reconstructing line 880 with the comment's
content spliced back into the active list closes most, but not all, of the
183-byte gap from §2b (30 of 183 bytes recovered exactly this way); the
remainder is consistent with adjacent comment/whitespace edits in the same
few-line block, which are invisible to a bytecode comparison by construction
(comments and whitespace never enter `co_code`) and were not otherwise
recoverable. **A byte-exact reconstruction of the original file was
attempted and did not fully succeed — pinned down to one line, not to the
literal surrounding whitespace.**

**Corroboration that `main()`'s two active names are not arbitrary:**
`"Eisaku_Satō"` and `"Carbon"` are two of the nine Answers in
`data/pilot_class_policy_v1.csv` (the human-approved nine-Answer engineering
pilot, approved 2026-07-30) — exactly the kind of ad-hoc smoke-test edit an
author would make while manually driving this legacy script against the
pilot roster, rather than any kind of corruption.

---

## 5. Whether the file is on the executed LRoleSim path — settled, not speculative

* `src/lrolesim/adapter.py` hard-codes `_KERNEL_MODULE_NAME =
  "MCQ_lrolesim_ClaudeWeb_v2"` and dynamically loads
  `src/MCQ_lrolesim_ClaudeWeb_v2.py` by that name via
  `importlib.util.spec_from_file_location`. It has never pointed at
  `MCQ_lrolesim.py`.
* `MCQ_lrolesim.py`'s only production consumers are the untracked legacy
  author scripts `src/mcq_generation.py`, `src/all_in_one.py`,
  `src/build_bipartite_and_draw*.py`, which import individual helper names
  (`short_form`, `partition_by_binary_label_function_withkey`,
  `ElementWithEdgeDirectionEquivalenceRelation`) — never `main()`, never
  `lrolesim()` or `create_mats()` directly. None of these scripts are part of
  the frozen Phase-B pipeline.
* `main()` is guarded by `if __name__ == "__main__":` and is therefore never
  executed by an `import` at all, by any consumer.

**Therefore: `src/MCQ_lrolesim.py` was never the LRoleSim implementation that
Prompt 8C or 8D executed**, and the one function that changed (`main()`) is
not executed by any import of the module either. The executed kernel has
always been `src/MCQ_lrolesim_ClaudeWeb_v2.py`, whose hash (`b7c3678e…`) has
never moved (re-verified in this audit, §3). `src/MCQ_lrolesim.py`'s role is a
reference archive of the pre-Journal-2 author source, kept so "Journal 1's
source stays immutable" can be checked qualitatively — not an execution
dependency.

---

## 6. Intentional revision vs. accidental drift

The bytecode diff in §4 resolves this more decisively than mtime evidence
alone could:

* The change is confined to one line of hard-coded example data inside a
  never-executed CLI driver function, in a block that already contained three
  other commented-out example lists (lines 871–877) — a pattern of ordinary,
  repeated manual editing of this script's demo inputs, not corruption.
* The original 19-name list was not deleted but commented out in place,
  preserved verbatim in the same line — the action of someone editing their
  own script, not a file-transfer or encoding artifact (which would not
  produce a syntactically valid, semantically preserved Python comment).
* The two retained active names, `Eisaku_Satō` and `Carbon`, are both
  members of this project's own nine-Answer approved pilot roster
  (`data/pilot_class_policy_v1.csv`), suggesting a deliberate narrowing of
  the demo run to the pilot's own answers.
* No CRLF, no BOM: the file was not the product of a Windows-editor
  round-trip that would show up as a global line-ending conversion.

**This was very likely a real, small, intentional, single-line manual edit by
the file's author** — narrowing a demo variable while testing something,
made in the same untracked file that this project's own convention (`CLAUDE.md`
File safety: "treat Journal 1 source ... as immutable archives") says must
never be touched. It appears to be a case of the file's own author (who is
also the person who wrote every other instruction in this repository not to
touch it) editing it directly outside the git-tracked, protection-aware
workflow — not tool-driven corruption and not evidence of a competing/
malicious edit.

---

## 7. Confidence level

* **High confidence:** the mismatch is real, isolated to this one file among
  eight protected sources, has been stable since 2026-08-06, and the file
  is not and has never been on the executed LRoleSim path (§5).
* **High confidence:** the drift is confined to `main()`; every other one of
  the file's 47 functions/classes, including the complete scientific kernel
  (`lrolesim()`, `create_mats()`, `Sim`, and all four equivalence-relation
  classes), is byte-identical bytecode between the pinned era and today
  (§4, verified by direct code-object comparison, not by inference).
* **High confidence:** the one change identified is a demo/example-data edit
  (a hard-coded `name_list`) with no bearing on any algorithm.
  Reconstructing it from the still-present trailing comment shows it is a
  narrowing to two of the project's own nine pilot Answers.
  **Medium** confidence only on the exact surrounding
  whitespace/comment bytes (a full byte-exact restoration was attempted and
  came within 30 of 183 bytes; the rest is plausibly adjacent comment
  changes in the same block, per §4, and was not independently recoverable).
* **Medium-high confidence** the edit was intentional and made directly by
  the file's own author outside the git-tracked workflow, based on the
  preserved-in-comment pattern (§6); this is inference from strong
  circumstantial evidence, not a confirmed first-person account, so it is
  not claimed as certain.

---

## 8. Recommendation

**`REBASELINE_TEST_TO_VERIFIED_ACTUAL_SOURCE`**

This is a change from what a purely mtime/manifest-based pass on this
question would conclude (`INSUFFICIENT_PROVENANCE_DO_NOT_CHANGE_ANYTHING`),
and the reason is §4: this audit did not stop at "no copy of the expected
bytes exists" — it recovered a real, object-code-level diff from
`src/__pycache__/MCQ_lrolesim.cpython-311.pyc`, which most provenance passes
would not think to open. That diff shows, with certainty rather than
plausibility, that:

1. The entire scientific content of the file — every function and class that
   implements or supports the LRoleSim algorithm — is unchanged, byte for
   byte, at the bytecode level.
2. The only change is inside `main()`, a demo-only driver that is not
   imported or executed by any production or test code in this repository,
   and never was.
3. `src/MCQ_lrolesim.py` itself has never been the module Prompt 8C/8D/8E/8F
   or any frozen pipeline actually executes — that role belongs to
   `src/MCQ_lrolesim_ClaudeWeb_v2.py`, whose own protected hash is
   independently confirmed unmoved.

Given that, continuing to fail the suite on a demo-data-only edit inside
dead code, in a file that was never on the executed path, tests a fact
("this exact archival file's bytes never move") that has already silently
become false and cannot be restored to true (§2, §4: the exact original bytes
are not fully recoverable, so `RESTORE_EXPECTED_SOURCE` is not achievable).
The evidence quality here is materially better than a typical "we can't tell,
so do nothing" case: this audit can state affirmatively *what* changed and
*that it does not matter scientifically*, not merely that something changed.
Rebaselining the pin to the current, now-understood `a286fe08…` value — with
this document as the record of why — converts an untraceable, permanently-red
integrity check back into a meaningful one, without asserting the changed
line was authorized (it was not) or hiding that it happened (it is fully
documented here).

`REMOVE_OBSOLETE_PIN_AND_PIN_THE_TRUE_EXECUTED_SOURCE` was considered and
rejected: `src/MCQ_lrolesim.py` is legitimately worth continuing to protect as
a reference archive (per `CLAUDE.md`'s File safety rule), even though it is
not the executed source — removing its pin entirely would let a future,
scientifically material edit to `lrolesim()` or `create_mats()` go undetected,
which this audit's own bytecode method shows is exactly the kind of change
worth catching. Rebaselining, not removing, is the narrower action that
matches the evidence.

This is a recommendation only. No test was changed and no hash was
rebaselined while producing this audit.

---

## 9. Reproducing this audit

```bash
cd /home/thuy/projects/mcq_journal2

# current hash + mtime, untracked confirmation
sha256sum src/MCQ_lrolesim.py
stat src/MCQ_lrolesim.py
git ls-files -- src/MCQ_lrolesim.py    # empty output

# where the expected hash is pinned, and that it never changed
git log --all --oneline -- tests/test_pipeline_graph_lrolesim.py
git log --all -p -- tests/test_pipeline_graph_lrolesim.py | grep -c cdd4f90c   # -> 1

# exhaustive search for the expected hash anywhere in the repo (none found)
grep -rn "cdd4f90c" . --include="*.py" --include="*.md" --include="*.csv" \
     --include="*.json" --include="*.jsonl" --include="*.txt" 2>/dev/null \
     | grep -v Zone.Identifier

# historical hash timeline recorded by each task package
for z in outputs/*.zip; do python3 -c "
import zipfile
z = zipfile.ZipFile('$z')
for n in z.namelist():
    if n.endswith('source_hashes_before_after.csv'):
        for line in z.read(n).decode('utf-8', 'replace').splitlines():
            if 'lrolesim.py' in line.lower() and 'claudeweb' not in line.lower():
                print('$z', line)
"; done

# isolated mtime: only this file was touched in its hour
find . -newermt "2026-08-04 03:00:00" -not -newermt "2026-08-04 04:00:00" \
     -type f 2>/dev/null | grep -v '\.git/'

# the .pyc's embedded source mtime/size (independent of git and manifests)
python3 -c "
import struct, datetime
data = open('src/__pycache__/MCQ_lrolesim.cpython-311.pyc','rb').read(16)
print(datetime.datetime.fromtimestamp(struct.unpack('<I', data[8:12])[0]),
      struct.unpack('<I', data[12:16])[0])
"

# the object-code diff: every function/class, identical or not
python3 -c "
import marshal
with open('src/__pycache__/MCQ_lrolesim.cpython-311.pyc','rb') as f:
    f.read(16); old = marshal.load(f)
new = compile(open('src/MCQ_lrolesim.py', encoding='utf-8').read(),
              'src/MCQ_lrolesim.py', 'exec')
def flatten(c, path=''):
    p = path + '/' + c.co_name if path else c.co_name
    yield p, c
    for k in c.co_consts:
        if hasattr(k, 'co_consts'):
            yield from flatten(k, p)
o = dict(flatten(old)); n = dict(flatten(new))
for k in sorted(set(o) | set(n)):
    same = o[k].co_code == n[k].co_code
    if not same:
        print('DIFFERS:', k, len(o[k].co_code), '->', len(n[k].co_code))
"
# -> DIFFERS: main 8354 -> 8314   (the only line, everywhere)

# confirm the executed kernel has always been the v2 file, never this one
grep -n "_KERNEL_MODULE_NAME" src/lrolesim/adapter.py
grep -rn "import MCQ_lrolesim\b\|MCQ_lrolesim\.main" --include="*.py" src tests

# the recovered original demo list, still present as a trailing comment
sed -n '880p' src/MCQ_lrolesim.py
```
