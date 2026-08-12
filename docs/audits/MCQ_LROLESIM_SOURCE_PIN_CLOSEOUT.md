# `src/MCQ_lrolesim.py` — source-pin closeout (independent stronger verification)

**Date** 2026-08-12 · **Task** Prompt 8H-B1.5-R1 · **Nature** verification and
hygiene only. No production `.py` file was created, modified, or deleted.
The only tracked changes made by this task are this document and one
comment-annotated hash literal in `tests/test_pipeline_graph_lrolesim.py`.

This document is the independent re-verification of, and closeout for, the
recommendation made in `docs/audits/MCQ_LROLESIM_SOURCE_PIN_AUDIT.md`
("B1.5"). Read B1.5 first; this document does not repeat its provenance
timeline (git history, mtime clustering, `.pyc` header dating) except where
that evidence is itself independently re-checked below.

---

## 1. Why B1.5's method needed a second pass

B1.5 recovered the pinned era's compiled bytecode from
`src/__pycache__/MCQ_lrolesim.cpython-311.pyc` via `marshal.load()` and
compared it against the current source recompiled in memory, walking 48
code objects and comparing `co_code` (the raw opcode bytes) pairwise. It
found 47/48 identical and one difference (`main()`), and recommended
rebaselining the pin on that basis.

`co_code` equality is real evidence, but it is not sufficient by itself to
prove two functions are semantically equivalent. Two code objects can have
byte-identical opcode streams while differing in the constants those
opcodes index into (`LOAD_CONST 0; RETURN_VALUE` looks the same whether
`co_consts[0]` is `0.2` or `0.3`), in the names looked up by `LOAD_GLOBAL`/
`LOAD_ATTR`, or in the function's own signature. This task therefore does
**not** repeat B1.5's own phrasing that "47/48 identical `co_code` proves
the entire scientific kernel is semantically identical" as a conclusion on
its own; it re-derives the conclusion from a strictly stronger comparison.

---

## 2. Historical `.pyc` provenance — independently re-verified

Re-checked directly in this task, before loading anything:

```
$ ls -la src/__pycache__/MCQ_lrolesim.cpython-311.pyc
-rw-r--r-- 1 thuy thuy 46795 Jul 30 02:59 ...cpython-311.pyc

magic bytes (first 4)         : a70d0d0a
this interpreter's MAGIC_NUMBER: a70d0d0a   -> MATCH (CPython 3.11, timestamp-based pyc, flags=0)
embedded source mtime (bytes 8-12)  : 2026-07-26 07:20:12
embedded source size  (bytes 12-16) : 56752 bytes
current src/MCQ_lrolesim.py size    : 56935 bytes  (183 bytes larger, matching B1.5 Sec. 2b)
current src/MCQ_lrolesim.py mtime   : 2026-08-04 03:17:40
```

All four values match B1.5's own documented header read exactly. The magic
number matching this interpreter's `importlib.util.MAGIC_NUMBER` and the
flags word having its low bit clear (hash-based-pyc bit unset) means this
is an ordinary CPython-3.11-produced, timestamp-based `.pyc` that this same
interpreter can safely `marshal.load()` without a version mismatch. The
comparator tool (`codeobject_semantic_diff.py`, Sec. 4 below) re-checks
this same magic/flags condition itself and raises rather than proceeding if
it does not hold.

Neither the `.pyc` nor `src/MCQ_lrolesim.py` was imported or executed at
any point in this task — the historical code object was obtained with
`marshal.load()` only, and the current source was obtained with
`compile()` only (see Sec. 4).

---

## 3. The stronger comparator

**Location:**
`outputs/journal2_phase_b1_source_pin_closeout_2026-08-12/codeobject_semantic_diff.py`
(a verification tool for this task, not a production module; not under
`src/`, not imported by any pipeline or test).

**What it checks, per code-object node, recursively over the whole tree**
(module → every nested function/lambda/genexpr/class/method, walked via
`co_consts`, 48 nodes total — identical node count to B1.5):

| Field | Meaning |
|---|---|
| `co_code_equal` | raw opcode bytes, exactly as B1.5 checked |
| `constants_equal` | every **non-code** value in `co_consts`, recursively normalized with an explicit type tag (see below), **excluding** the docstring slot (reported separately) |
| `names_equal` | `co_names` |
| `signature_fields_equal` | `co_argcount`, `co_posonlyargcount`, `co_kwonlyargcount`, `co_nlocals`, `co_flags`, `co_varnames`, `co_freevars`, `co_cellvars` |
| `exception_table_equal` | `co_exceptiontable` (Python 3.11+) |
| `metadata_only_differences` | `docstring`, `co_filename`, `co_firstlineno`, `co_linetable`, reported but **not** folded into `semantic_difference` |
| `semantic_difference` | `True` iff any of the five equality fields above is `False` for *this* node (child differences are attributed to the child's own path, not double-counted at the parent) |

**Type-tagged constant normalization.** Comparing `co_consts` entries with
plain `==` would silently equate `1 == 1.0 == True` (Python's own
semantics), hiding a real type change. `_normalize_const()` wraps every
constant with a type tag (`("int", 1)` vs `("float", "1.0")` vs
`("bool", True)`) before comparing, recursing into tuples/frozensets and
replacing nested code objects with a path marker (they are already being
compared as separate nodes in the same walk, so they are not compared a
second time by value/identity here).

**Docstring-slot handling verified empirically, not assumed** (see the
module's own docstring and the self-tests): function/lambda/genexpr code
objects unconditionally reserve `co_consts[0]` as a docstring slot (a
`str`, or `None` if absent), with no explicit store bytecode — confirmed by
disassembly. Module and class-body code objects instead compile an
*explicit* `LOAD_CONST <docstring>; STORE_NAME __doc__` instruction pair
**only when a real docstring is present**; the comparator locates that
exact instruction pair via `dis.get_instructions()` rather than guessing
from position, specifically so that an ordinary string constant that
happens to be a class/module's first real value (e.g. `class C: x =
'hello'`) is never misclassified as a docstring. This was caught and fixed
during self-testing (Sec. 5, `test_class_body_first_slot_qualname_is_not_
misread_as_docstring`).

**Module-level defaults.** Default argument values (e.g. `beta=0.2`,
`iterations=3`) are not stored in the child function's own code object at
all — CPython's compiler builds them via `LOAD_CONST`/`BUILD_TUPLE`/
`KW_NAMES` instructions in the *enclosing* code object (module or class
body) and passes the result to `MAKE_FUNCTION`. Because this comparator
walks and compares every enclosing code object's own `co_code`/`co_consts`
too, a changed default value is caught at the enclosing object's path
(`<module>` for a module-level `def`), not at the child's. Proven directly
by `test_module_level_default_change_detected_beta`,
`test_module_level_default_change_detected_iterations`, and
`test_kwonly_default_change_via_kwdefaults_dict_detected` (Sec. 5).

**A tool bug found and fixed while building this comparator.** The first
run against the real file reported semantic differences on **47 of 48**
nodes — the opposite of what a stronger, correct comparator should show
given B1.5's `co_code`-level agreement. Investigating one flagged node
(`lrolesim()` itself, which B1.5 found `co_code`-identical) showed
`co_flags` differing by exactly bit `0x1000000`, which decodes to
`CO_FUTURE_ANNOTATIONS`. The cause: `compile()`'s default behavior inherits
any `from __future__ import ...` statement **in effect in the calling
module** into the code it compiles (`dont_inherit` defaults to `False`),
and the comparator's own driver script has `from __future__ import
annotations` at its top for its own type hints. That future statement was
leaking into every freshly-compiled node of `MCQ_lrolesim.py`, which itself
has no future import at all (confirmed: `grep -n "from __future__"
src/MCQ_lrolesim.py` returns nothing). Fixed by calling
`compile(source, filename, "exec", flags=0, dont_inherit=True)`. Reproduced
the leak and the fix in isolation before and after the change; re-ran the
full comparison and self-test suite afterward. This is disclosed here
because it is exactly the kind of tool-level artifact this task exists to
guard against — a naive stronger check can introduce its own false
positives, and those must be run down and understood, not shrugged off as
"probably fine."

---

## 4. Synthetic self-tests (constant-only counterexample)

`outputs/journal2_phase_b1_source_pin_closeout_2026-08-12/comparator_self_tests.py`,
11 tests, all against `compile()`-only synthetic code (nothing executed;
`MCQ_lrolesim.py`/its `.pyc` are not touched by this file at all). Full
output captured in `comparator_self_tests.txt`. Highlights:

* **The required counterexample.** `return 0.2` vs `return 0.3` compiles to
  byte-identical `co_code` (`LOAD_CONST 0; RETURN_VALUE` both times) —
  verified as a precondition inside the test itself — yet the comparator
  reports `constants_equal=False` and `semantic_difference=True`. This is
  the exact case B1.5's `co_code`-only method could not have caught.
* **Type confusion guard.** `return 1` vs `return 1.0`: caught as different
  despite `1 == 1.0` in Python.
* **Module-level defaults.** `beta=0.2 -> beta=0.3` and `iterations=3 ->
  iterations=5`, both positional-default and keyword-only-default forms:
  the child function's own code object is provably byte-identical
  (asserted directly in the test) while the change is correctly detected
  at `<module>`.
* **Docstring vs. semantic.** A pure docstring edit (function and class
  forms) is reported under `metadata_only_differences` and explicitly
  **not** as `semantic_difference=True`.
* **False-positive guard for class bodies.** A class with *no* docstring
  whose first real statement assigns a string literal to an attribute
  (`class C: x = 'hello'`) is not misread as having a docstring, and the
  real change to that attribute's value is still caught as a genuine
  constants difference.
* **Renamed callee.** Renaming a called global function can leave `co_code`
  byte-identical (same opcode/oparg shape, different `co_names` entry it
  indexes) — caught via `names_equal=False`.
* Identical sources produce zero semantic differences and zero added/
  removed paths (negative control).

All 11 pass (`ALL SELF-TESTS PASSED (11 tests)`, `comparator_self_tests.txt`).

---

## 5. Result against the real file

Run: `outputs/journal2_phase_b1_source_pin_closeout_2026-08-12/run_comparison.py`.
Loads the historical code object from
`src/__pycache__/MCQ_lrolesim.cpython-311.pyc` via `marshal.load()` only
(never imports/executes it); compiles the current
`src/MCQ_lrolesim.py` in memory via `compile(..., dont_inherit=True)` only
(never imports/executes it either). Full machine-readable output:
`lrolesim_codeobject_semantic_diff.json`.

```
Common code-object nodes compared: 48
Added paths (new only):   []
Removed paths (old only): []
Semantic differences OUTSIDE main(): []
Semantic differences INSIDE main():  ['<module>/main']
```

* **`semantic_differences_outside_main == 0`.** Every one of the 46
  non-`main`-family nodes — the complete scientific kernel B1.5 named
  (`lrolesim()`, `create_mat()`, `create_mats()`, the `Sim` class and its
  `__init__`/`__getitem__`/`__setitem__`, `edge_count()`,
  `reduce_neighbor()`, `partition_by_binary_label_function[_withkey]`
  (incl. nested lambdas), `solve_assignment_problem[_multiple]` (incl.
  nested lambdas), `compute_mrr()`, `compute_ndcg()` (incl. nested
  genexpr), `short_form()`, `get_equiv_classes_for_node()` (incl. nested
  listcomp), `print_equiv_classes_for_single_node()`,
  `process_nodes_batch()`, and all four equivalence-relation classes with
  their `__init__`/`__eq__`/`__hash__` — has `semantic_difference: false`
  under every one of `co_code_equal`, `constants_equal`, `names_equal`,
  `signature_fields_equal`, `exception_table_equal`.
* **The only semantic difference is inside `main()`** —
  `<module>/main` (`co_code_equal=false`, `constants_equal=false`,
  `co_code` length 8354→8314 bytes, matching B1.5's own byte counts
  exactly). `<module>/main/calc_sorted_list` (the one function nested
  inside `main()`) is fully identical — also matching B1.5. Inspecting
  `detail.constants_old_rest_repr` for the `main()` node shows the same
  demo-data string pool B1.5 already identified (file/CSV names, class
  labels, the `jikken*` experiment tags) — consistent with, not
  contradicting, B1.5's finding that the one change is the `name_list`
  demo variable at source line 880.
* **`<module>` itself** (the module top-level code, distinct from
  `main()`) has `semantic_difference: false` — no import changes, no
  module-level constant or default-argument changes anywhere in the file
  outside `main()`.
* Both `<module>` and `<module>/main` show `co_linetable` under
  `metadata_only_differences` (line numbers shifted because of edits
  inside `main()`'s source lines) — expected, reported, and correctly
  excluded from `semantic_difference`, consistent with the rule in Sec. 3.
* No `added_paths`/`removed_paths`: the historical and current trees have
  exactly the same 48 code-object paths, one-to-one — no function or
  method was added or removed anywhere in the file.

**Acceptance condition met:** `semantic_differences_outside_main == 0`, and
every scientific LRoleSim function/class named in the B1.5 audit is present
among the compared nodes with `semantic_difference: false`.

---

## 6. What this does and does not prove

This audit states only: **the recoverable Python-3.11 compiled semantics of
`src/MCQ_lrolesim.py` outside the demo `main()` are equivalent, under every
field this stronger comparator checks (opcode stream, non-docstring
constants, names, full call signature, exception table), to the
`cdd4f90c…`-era compiled semantics recovered from the `.pyc` cache.**

It does **not** claim:
* that the two source files are byte-identical — the pinned era's exact
  source text is not recoverable (B1.5 Sec. 4; this task did not attempt
  to recover it further);
* that comments or whitespace are identical between the two versions —
  comments/whitespace never enter compiled bytecode and are invisible to
  this method by construction, in both B1.5's and this task's comparator;
* that `main()` is unchanged — it is known to differ, in both `co_code`
  and constants, confined to the demo `name_list` per B1.5's own
  reconstruction (not re-attempted here).

## 7. Was the test pin changed?

**Yes.** `semantic_differences_outside_main == 0` held, so the conditional
rebaseline authorized by this task's instructions was applied:
`tests/test_pipeline_graph_lrolesim.py`'s `PROTECTED_SOURCE_SHA256["src/
MCQ_lrolesim.py"]` was updated from `cdd4f90c006dc57d97ecccf79685efcd
553e60be12dc86cfd66d205f5b6ff15b` to `a286fe08719a6a049638548aee7526c069
b3fec2ab621bec8d540059d3f03617` (the file's current, independently
re-verified `sha256sum`), with an inline comment pointing back to both this
document and `MCQ_LROLESIM_SOURCE_PIN_AUDIT.md`, stating explicitly that
the file is reference/archive-only, is not the executed Journal-2
LRoleSim kernel, that the executed kernel remains
`src/MCQ_lrolesim_ClaudeWeb_v2.py`, and that the rebaseline records
verified current bytes without authorizing future modification. No other
pin in that dictionary was touched, added, or removed. The
`src/MCQ_lrolesim_ClaudeWeb_v2.py` pin (`b7c3678e…`) was re-verified
unchanged (`sha256sum`) and left untouched.

## 8. Why `MCQ_lrolesim.py` stays in `src/` rather than moving to `legacy/`

`CLAUDE.md`'s File Safety rule requires treating Journal-1 source as an
immutable archive, not deleting or relocating it out from under whatever
external tooling, documentation, or manual workflows still reference it by
its current path. B1.5 already established (Sec. 5 of that audit,
re-confirmed here by the fact that this task's own comparison needed no
different method) that the file has never been on the executed Journal-2
path — its only production consumers are untracked legacy author scripts
(`mcq_generation.py`, `all_in_one.py`, `build_bipartite_and_draw*.py`) that
are themselves outside the frozen Phase-B pipeline, and its `main()` is
guarded by `if __name__ == "__main__":` so no import ever runs it. Moving
it would be a structural repository change with no basis in this task's
mandate ("do NOT modify src/MCQ_lrolesim.py; do NOT move either file") and
no evidentiary benefit: keeping the file where it is, with its hash pinned
and its non-executed status now documented twice, is the narrower action.

## 9. Why Journal-2 execution must continue through the frozen adapter path

`src/lrolesim/adapter.py` hard-codes `_KERNEL_MODULE_NAME =
"MCQ_lrolesim_ClaudeWeb_v2"` and loads `src/MCQ_lrolesim_ClaudeWeb_v2.py`
by that name via `importlib.util.spec_from_file_location` — re-confirmed by
direct inspection in this task (`grep -n _KERNEL_MODULE_NAME
src/lrolesim/adapter.py`). It has never pointed at `MCQ_lrolesim.py`, and
this task did not change that. Final Journal-2 experiments must keep
running through this adapter, not through any direct import of either
kernel file, because the adapter — not either raw kernel module — is the
one place the frozen `PROTECTED_SOURCE_SHA256` pins, the fixed-iteration
contract, and the cache/replay guarantees in
`tests/test_pipeline_graph_lrolesim.py` are actually enforced.

---

## 10. API distinction inside `src/MCQ_lrolesim_ClaudeWeb_v2.py` (documentation only — file NOT edited)

Confirmed by direct read of the current file (not the historical `.pyc`;
this section is about the v2 kernel, which this task was never authorized
to touch and did not touch):

* **`lrolesim_fixed_iterations(...)`** (line 270) is the explicit
  fixed-iteration API. Its own docstring states in Vietnamese: *"ĐÂY LÀ
  ĐƯỜNG CHẠY CHÍNH THỨC CỦA JOURNAL 2"* ("this is the official run path for
  Journal 2"), runs exactly `iterations` rounds with no convergence check,
  and cites the LRoleSim paper's published parameters (β = 0.2, k = 3) as
  the reason the iteration count must be an explicit fixed constant rather
  than a threshold-derived value. `src/lrolesim/adapter.py` calls this
  function (line 231) for the frozen Journal-2 run path.
* **`lrolesim_until_convergence(...)`** (line 310) is the convergence API,
  kept under its own explicit name for running a "convergence vs. k=3"
  ablation — not the Journal-2 default. The adapter also exposes this
  separately as `run_lrolesim_until_convergence()` (line 269) for that
  ablation use, distinct from the frozen default path.
* **`lrolesim(...)`** (line 340) is a backward-compatible wrapper that
  delegates to `lrolesim_until_convergence()` with the same signature and
  behavior as before this API split, kept so legacy untracked scripts
  (`all_in_one.py`, `mcq_generation.py`) do not break.
* **Consequence:** because all three names live in the same module, a
  future task must not substitute a direct call to `lrolesim()` (or to
  `lrolesim_until_convergence()`) for `lrolesim_fixed_iterations()` merely
  because it is convenient to call the same module — doing so would
  silently switch Journal-2 experiments from the fixed-`k=3` official run
  path to the convergence ablation path. Final Journal-2 experiments must
  go through the already-frozen adapter functions
  (`run_lrolesim_fixed_iterations` / equivalent), which pin the correct
  one. `rank_by_similarity()` was read only to locate these definitions
  and was not analyzed or changed further, per this task's scope.

---

## 11. Reproducing this closeout

```bash
cd /home/thuy/projects/mcq_journal2
git checkout journal2-phase-b1-source-pin-closeout-20260812   # or re-derive from e7427f3

# re-verify inputs
sha256sum src/MCQ_lrolesim.py                    # expect a286fe08...03617
sha256sum src/MCQ_lrolesim_ClaudeWeb_v2.py        # expect b7c3678e...ddc0 (unchanged)
python3 -c "
import struct
d = open('src/__pycache__/MCQ_lrolesim.cpython-311.pyc','rb').read(16)
print(d[:4].hex(), struct.unpack('<I', d[4:8])[0],
      struct.unpack('<I', d[8:12])[0], struct.unpack('<I', d[12:16])[0])
"   # expect a70d0d0a 0 1785018012 56752

cd outputs/journal2_phase_b1_source_pin_closeout_2026-08-12
python3 comparator_self_tests.py     # expect: ALL SELF-TESTS PASSED (11 tests)
python3 run_comparison.py            # expect: Semantic differences OUTSIDE main(): []
```

---

## 12. Final verdict

`LROLESIM_ARCHIVE_PIN_VERIFIED_AND_CLOSED`
