# Implementation — category selector v3.4, offline

**Date:** 2026-07-28
**Type:** offline implementation against a committed RED specification. No network, no SBERT, no local index, no live probe, no 34-Answer batch, no push. The implementation is deliberately left **unstaged and uncommitted**.

**Conclusion: `V3_4_OFFLINE_IMPLEMENTATION_READY_FOR_AUDIT`**

This is not a claim of readiness for live use or for the 34-Answer batch. A live
Tomonaga probe and a re-run of the five-Answer redirect smoke condition are still
required first.

---

## 1. RED checkpoint

The failing specification was committed before any implementation existed.

| Item | Value |
|---|---|
| RED commit | `79000b9313add2968986f5d85839deb0512852ca` |
| Annotated tag | `category-selector-v3.4-red` → `79000b9313add2968986f5d85839deb0512852ca` |
| Contents | 2 files, 728 insertions: `tests/test_category_extractor_v34_regressions.py`, `docs/audits/REPRO_category_selector_v34_blockers_2026-07-28.md` |
| State at that commit | full suite contained 3 known failures (D1, D2, E) — intentional |

Frozen tags remain intact: `category-selector-v3.3-offline` → `ce740e1…`,
`category-selector-v3.3-runner` → `e516a06…`.

### Frozen baseline, verified before and after

```
src/category_extractor_ClaudeWeb_v2.py     cc594ef1fc637c9df402276d84e95dc39bb60487286f64dd12f2966acb1604bd
src/category_extractor_ClaudeWeb_v3.py     b9556d64f02ffdf6a6f393773a89b8d1204c00228b2f27ef882cd5c286ce1ac4
tests/test_category_extractor_v3.py        7f5b0461b1390116304e2256e840ed49c024e55061c01de4dd59cea4d7a987f2
scripts/run_category_selector_v3.py        d9787802339036aefc6fd5b976890655a3ab16b40a37bb97a97f184c58442693
tests/test_run_category_selector_v3.py     142acee98550aa40ee6f93bf50ade19dd60de94559e22b070b14219f4810eac3
data/category_answer_nodes_v2_demo.txt     d78621e4e9dc0a3709155f9f8ebdd98796bb06a3a264a374307e8e059b0dc51a
docs/audits/REPRO_…_2026-07-28.md          81d36d9eb5509437aac9259c26f54aa7fba373fe4757821c1ca5eb605447cad9
```

---

## 2. Implementation scope

v4 is a **standalone module** derived from the frozen v3.3 source by an auditable
transform: 17 exact string replacements plus 2 scoped rewrites, each asserting its
occurrence count so a silent mismatch could not produce a half-transformed file.
v4 does not import v3 and does not monkeypatch it; its complete implementation can
be frozen independently.

```
SCHEMA_VERSION       = "category_selector_v3.4"   (was category_selector_v3.3)
CACHE_SCHEMA_VERSION = "sparql_cache_v3.0"        (unchanged — see §8)
```

---

## 3. The validation split

### Before (v3.3) — one character class, two contexts

```python
_UNSAFE_URI_CHARS = re.compile(r"""[\s<>"'{}|\\^`]|[\x00-\x1f\x7f-\x9f]""")
```

`_validate_iri` guarded nine call sites: **eight IRIREF positions** (`<{uri}>`) and
**one quoted-literal position** (the pagination cursor, `FILTER(STR(?x) > "{cursor}")`).
The apostrophe terminates neither, so it was over-rejected in both.

### After (v3.4) — one predicate per syntactic context

```python
# CONTEXT A — inside <...>. SPARQL 1.1 rule [139] forbids exactly
#   < > " { } | ^ ` \  and #x00-#x20 . The apostrophe is deliberately ABSENT.
_UNSAFE_IRIREF_CHARS = re.compile(r"""[\s<>"{}|\\^`]|[\x00-\x20\x7f-\x9f]""")

# CONTEXT B — inside "...". Only " closes it, only \ starts an escape;
#   raw line breaks and controls are illegal. Values are refused, not escaped,
#   so no escaping bug can produce a query that parses differently than intended.
_UNSAFE_LITERAL_CHARS = re.compile(r"""["\\]|[\x00-\x1f\x7f-\x9f]""")

_UNSAFE_URI_CHARS = _UNSAFE_IRIREF_CHARS   # retained alias; now means CONTEXT A
```

New public predicate `is_safe_literal()` and internal `_validate_literal()`.
`build_class_members_query` routes the cursor through the literal validator; it is
no longer routed through the IRIREF validator.

**Behaviour change, precisely** (corrected — see §13): for a value in an IRIREF
position the only character whose verdict moved is `'`; everything else is
unchanged or stricter (`\x1f` → `\x20` in the IRIREF class). The initial v4 draft
*also* widened the pagination cursor, which is a separate position; §13 records
that regression and its repair.
16 parametrised cases assert that space, `<`, `>`, `"`, `{`, `}`, `|`, `^`,
`` ` ``, `\`, newline, tab, NUL, a C1 control, a bad scheme and a missing scheme
all remain rejected.

Unicode is preserved exactly: a value that passes is interpolated verbatim and is
never percent-encoded, because `…/Shin%27ichir%C5%8D_Tomonaga` was measured at
**0 triples** by the C0 probe and is therefore a different RDF term.

---

## 4. Redirect-resolution state machine

```python
class RedirectStatus(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    NO_REDIRECT   = "no_redirect"
    FOLLOWED      = "followed"
    REJECTED      = "rejected"
    QUERY_FAILED  = "query_failed"
    RESOLVER_ERROR = "resolver_error"

REDIRECT_REASON_UNSAFE_TARGET = "unsafe_or_malformed_redirect_target"
REDIRECT_REASON_CYCLE         = "redirect_cycle_detected"
REDIRECT_REASON_NOT_IMPROVING = "redirect_target_not_improving"
```

| Status | attempted | target | used | `query_uri` | reason |
|---|---|---|---|---|---|
| `not_attempted` | false | null | false | original | null |
| `no_redirect` | true | null | false | original | null |
| `followed` | true | exact raw target | true | the target | null |
| `rejected` | true | **exact returned string** | false | original | machine-readable code |
| `query_failed` | true | last seen or null | false | original | null (`error` carries the endpoint text) |
| `resolver_error` | true | last seen or null | false | original | null (`error` carries the repr) |

`REDIRECT_REASON_NOT_IMPROVING` is a third rejection code, beyond the two required.
It covers the case where a target is found and read but adopting it would not have
improved the result: v3.3 kept the original URI silently, which would have been a
second instance of exactly the invisibility defect E describes. It is recorded
explicitly instead.

**`query_failed` is never converted into `no_redirect`.** The endpoint's failure
text is preserved in `error`, and the selector still returns
`SelectionStatus.QUERY_FAILED` / `QueryStatus.FAILED` as v3.3 did.

**`resolver_error` preserves v3.3's containment** — a custom resolver's own bug
never becomes an endpoint data claim — but the state is now visible rather than
silently equated with "there is no redirect".

**A rejected target is never placed into any subsequent SPARQL query.** Asserted in
both the selector suite and the runner suite by scanning every issued query.

---

## 5. Data structures and serialization

```python
@dataclass(frozen=True)
class RedirectResolution:
    query_uri: str
    redirect_used: bool = False
    redirect_attempted: bool = False
    redirect_target: Optional[str] = None
    status: RedirectStatus = RedirectStatus.NOT_ATTEMPTED
    rejected_reason: Optional[str] = None
    error: Optional[str] = None
```

Immutable and returned by value — provenance is never carried in mutable global or
side-channel state.

`ClassSelectionResult` gained four fields, all serialized by `to_dict()`:

```
redirect_attempted            bool
redirect_target               str | None
redirect_resolution_status    str   (the closed vocabulary above)
redirect_rejected_reason      str | None
```

Preserved unchanged: `original_uri` (never rewritten), `query_uri` (moves only on a
followed hop), `redirect_used` (true only on a followed hop), `query_status`,
`selection_status`, `error`, `sparql_query_count`, `cache_stats`.

**Every result carries provenance, including every early return.** `_result()` now
takes an optional resolution and defaults to `not_attempted`, and inside
`select_candidate_classes` all ten result-construction sites go through a closure
that reads the current resolution at call time — so a return path added later
cannot forget to carry it. `_select_manual` receives the resolution as a parameter
and does the same for its three sites.

### Public API preserved

```python
resolve_query_uri_with_provenance(...) -> RedirectResolution   # used by the selector
resolve_query_uri(...) -> tuple[str, bool]                     # v3 compatibility wrapper
```

The wrapper re-raises `RedirectQueryFailed` exactly as v3.3 did, so the tuple API
and its exception contract are unchanged for existing callers.

---

## 6. Runner changes

`scripts/run_category_selector_v4.py`, derived from the committed v3 runner by
7 asserted replacements.

```
RUNNER_SCHEMA_VERSION   = "category_runner_v1.1"      (was v1.0)
SELECTOR_SCHEMA_VERSION = "category_selector_v3.4"    (from the v4 module)
```

Imports exclusively from `category_extractor_ClaudeWeb_v4`.

`summary.csv` gained four columns immediately after `redirect_used`, which is
itself preserved: `redirect_attempted`, `redirect_target`,
`redirect_resolution_status`, `redirect_rejected_reason`. `ranking.csv` is
unchanged — no consumer needs per-class redirect data.

Unchanged: network denied by default, one shared runner, sequential execution,
atomic `os.replace` writes, overwrite refusal, exception isolation, input-row
provenance, resume semantics, cache schema.

### Resume compatibility

`RESUMABLE_RESULT_FIELDS` gained all five redirect fields, and the schema check is
an exact match against `category_selector_v3.4`. Therefore:

* a complete v3.4 record is resumable;
* a v3.3 record is **not** — it is re-run, so `--resume` can never merge two
  selector schemas into one result set;
* a v3.4 record missing any single provenance field is **not** resumable.

All three are asserted, the last parametrised over each of the four fields.

---

## 7. Test results

Every command below was run; nothing was hidden with `xfail`, `skip`, deselection
changes or relaxed assertions.

| Command | Result |
|---|---|
| `py_compile` (v4 selector, regressions, v4 suite, v4 runner, v4 runner suite) | OK |
| `pytest -q tests/test_category_extractor_v3.py -m "not integration"` | **171 passed, 2 deselected** |
| `pytest -q tests/test_run_category_selector_v3.py` | **73 passed** |
| `pytest -q tests/test_category_extractor_v34_regressions.py` | **4 passed** |
| `pytest -q tests/test_category_extractor_v4.py -m "not integration"` | **216 passed, 2 deselected** |
| `pytest -q tests/test_run_category_selector_v4.py` | **94 passed** |
| `pytest -q tests/ -m "not integration"` | **558 passed, 4 deselected, 0 failed** |

### RED → GREEN

| Test | At tag `category-selector-v3.4-red` | Now |
|---|---|---|
| `test_control_ordinary_redirect_is_followed_and_selects_a_class` | PASSED | PASSED |
| `test_d1_apostrophe_iri_is_accepted_and_embedded_raw_in_iriref_position` | **FAILED** | **PASSED** |
| `test_d2_apostrophe_redirect_target_is_followed_with_success_provenance` | **FAILED** | **PASSED** |
| `test_e_found_but_invalid_redirect_target_is_explicitly_reported` | **FAILED** | **PASSED** |

**No assertion was weakened.** The only changes to that module were the import
(`…_v3` → `…_v4`) and the header comment describing which version it targets. Every
behavioural contract, every threshold and every negative assertion — including
`"%27" not in query` and "the rejected target must never be queried" — is
byte-identical to the committed RED version. This is verifiable with
`git diff category-selector-v3.4-red -- tests/test_category_extractor_v34_regressions.py`.

---

## 8. Cache-schema decision

`CACHE_SCHEMA_VERSION` stays at `sparql_cache_v3.0`. **No change is authorised or
needed**, because the patch changes neither cache serialisation nor cache-key
semantics:

* cache keys remain `sha256(endpoint, language, query_text)`;
* the stored columns are untouched;
* a previously-rejected IRI now produces a *new* key, not a redefined one.

Both existing smoke caches (12 and 21 rows) remain valid and readable. Bumping the
version would needlessly invalidate 33 correctly cached responses.

---

## 9. Offline demonstrations

All fake-transport only. No network.

**A — direct raw canonical Tomonaga input.** `is_safe_uri` → `True`; the IRI appears
verbatim inside `<...>`; no `%27` or `%C5%8D` anywhere; the runner's
`load_answer_input` accepts it as a 1-row dataset.

**B — old Tomonaga redirect.**
`original_uri = …/Sin-Itiro_Tomonaga`, `query_uri = …/Shin'ichirō_Tomonaga`,
`redirect_attempted = true`, `redirect_target = …/Shin'ichirō_Tomonaga`,
`redirect_resolution_status = "followed"`, `redirect_rejected_reason = null`,
`redirect_used = true`, `selection_status = "ok"`.

**C — invalid target.** `redirect_attempted = true`; `redirect_target` preserves the
exact string `http://dbpedia.org/resource/Bad Target`;
`redirect_resolution_status = "rejected"`;
`redirect_rejected_reason = "unsafe_or_malformed_redirect_target"`;
`redirect_used = false`; `query_uri` unchanged; **no query was issued against the
rejected target**.

**D — no redirect.** `redirect_attempted = true`, `redirect_target = null`,
`redirect_resolution_status = "no_redirect"`, `redirect_used = false`.

**E — redirect query failure.** `redirect_attempted = true`,
`redirect_resolution_status = "query_failed"` — distinct from `no_redirect`, with
the endpoint text preserved in `error`. Not converted into a data absence.

**F — offline fake batch through the v4 runner**, four Answers covering all four
outcomes:

```
exit=0  jsonl=4  summary=4  envelopes=0
manifest: selector=category_selector_v3.4  runner=category_runner_v1.1
input order preserved: True
per-Answer Σqueries=18  shared runner Σqueries=18  equal=True

Answer                     status     redirect_resolution  used   target / reason
Shinya_Yamanaka            ok         not_attempted        False  —
Plain_Redirect_Source      ok         followed             True   Plain_Redirect_Target
Sin-Itiro_Tomonaga         ok         followed             True   Shin'ichirō_Tomonaga
Bad_Redirect_Source        no_label   rejected             False  Bad Redirect Target
                                                                  unsafe_or_malformed_redirect_target

summary.csv provenance columns present : True
manifest output hashes match files     : True
rejected target never queried          : True
leftover .tmp                          : none
deterministic across two runs          : results.jsonl / summary.csv / ranking.csv all identical
```

---

## 10. Files

### Authorised implementation paths (initial draft — superseded by §13)

| File | Lines | SHA-256 |
|---|---|---|
| `src/category_extractor_ClaudeWeb_v4.py` | 3586 | `8bd3da06d0117b75975e5b9573ae131d4d82be9a5c5d4dc286df6250c7be2eab` |
| `tests/test_category_extractor_v34_regressions.py` | 476 | `d9d2e05c5f0811d3b187827f4e7d48d3feae40da87dca46a5abacea512a30253` |
| `tests/test_category_extractor_v4.py` | 2994 | `046c170e08d461d6c14a4df0a3880511ab17ed0470b95a939e945f8617fc7161` |
| `scripts/run_category_selector_v4.py` | 1059 | `b482028f52d3c4bde86e08789ef8b6b6972b95e75b75687b5d0bfe6b345016cd` |
| `tests/test_run_category_selector_v4.py` | 1525 | `6f55703350280760a304bc6f66ee116f7e810c829b0013a069fe7a76be23d6b2` |

### Protected files, re-verified after implementation

All seven hashes in §1 are unchanged. `git diff` over them is empty.

---

## 11. Remaining risks

1. **Never run against a live endpoint.** Every result above is against fake
   transports. The apostrophe IRI has not been sent over the wire by v4.
2. **The canonical Tomonaga category set is still unmeasured** — the C0 probe's
   `dct:subject` query returned HTTP 502 and was not retried. v4's ability to
   *reach* that resource is demonstrated; what it will *find* there is not known.
3. **`REDIRECT_REASON_NOT_IMPROVING` has no live precedent.** It covers a path v3.3
   handled silently; it is exercised only by construction, not by observed data.
4. **The v4 suite is derived, not independently written.** It inherits any blind
   spot the v3 suite had. The 45 tests added on top are new coverage, but the 171
   inherited ones test what v3 chose to test.
5. **Multi-hop redirects remain untested in practice.** `max_hops` defaults to 1 and
   every fixture uses one hop; the loop's multi-hop path is exercised only by the
   cycle test.
6. **Two runner schema versions now coexist.** A `category_runner_v1.0` output
   directory and a v1.1 one differ in `summary.csv` column count. Any downstream
   consumer reading by position rather than by header will break.
7. **`is_safe_uri` is now more permissive by exactly one character.** The reasoning
   is that `'` cannot terminate an IRIREF or a double-quoted literal. If a future
   query builder introduces a *single*-quoted literal context, that reasoning would
   no longer hold and a third validator would be required.

---

## 12. Next step

Per the audit's §11 sequence, items 12–14 remain:

1. a new isolated **live** Tomonaga probe — including a fresh `dct:subject` query for
   the canonical URI, the measurement the 502 cost;
2. a re-run of the five-Answer redirect smoke condition;
3. only then, authorisation of the 34-Answer batch.

The input dataset `data/category_answer_nodes_v2_demo.txt` remains byte-identical
and must not be edited: v3.4 resolves the stale URI by following its redirect, which
is the correct fix and preserves the v2-derived provenance.

**`V3_4_OFFLINE_IMPLEMENTATION_READY_FOR_AUDIT`**


---

## 13. Post-review correction pass (2026-07-28)

A review of the uncommitted draft found four defects. All four were reproduced
before being patched, and each fix is minimal — no redesign, no new redirect
status, no refactor of unrelated code.

### A — two v4 tests still targeted v3

`tests/test_category_extractor_v4.py` carried two tests inherited from the v3
suite that still named the v3 module:

* the import-hygiene subprocess probe ran `import category_extractor_ClaudeWeb_v3`;
* the source-inspection test read `SRC_DIR / "category_extractor_ClaudeWeb_v3.py"`.

Both now target v4. The probe additionally asserts
`m.SCHEMA_VERSION == "category_selector_v3.4"` inside the subprocess and prints
it, and the parent test asserts `PROBE_SCHEMA category_selector_v3.4` appears in
stdout — so the probe cannot silently import the wrong version again.

`grep ClaudeWeb_v3 tests/test_category_extractor_v4.py` now returns nothing. The
remaining v2 references are the deliberate frozen-archive checks and stay.

### B — the pagination cursor lost its URI semantics

**This is the more serious of the four, and it contradicts a claim made in §3 of
the original report.** v3.3 validated the cursor with `_validate_iri`, which
required an http(s) IRI as a side effect. The v3.4 context split routed the cursor
through `_validate_literal` alone, which checks only that the value cannot break
out of a quoted literal. Measured on the draft:

| cursor | v3.3 | v4 draft | v4 corrected |
|---|---|---|---|
| `not-a-uri` | reject | **ACCEPT** | reject |
| `abc def` | reject | **ACCEPT** | reject |
| `http://dbpedia.org/resource/A B` | reject | **ACCEPT** | reject |
| `ftp://dbpedia.org/resource/X` | reject | **ACCEPT** | reject |
| `dbpedia.org/resource/X` | reject | **ACCEPT** | reject |
| `http://dbpedia.org/resource/A"B` | reject | reject | reject |
| `http://dbpedia.org/resource/A\B` | reject | reject | reject |
| `http://dbpedia.org/resource/A\nB` | reject | reject | reject |
| `http://dbpedia.org/resource/O'Reilly_Media` | reject | ACCEPT | **ACCEPT** (intended) |

Fixed with a small composed validator, not by merging the two character classes:

```python
def _validate_cursor(value, *, what="pagination cursor"):
    if not is_safe_uri(value):          # CONTEXT A — it is a member IRI
        raise ValueError(...)
    return _validate_literal(value, what=what)   # CONTEXT B — quoted literal
```

`_UNSAFE_IRIREF_CHARS` and `_UNSAFE_LITERAL_CHARS` remain independent, so
relaxing one cannot silently relax the other. The cursor is preserved verbatim
and never percent-encoded.

**The corrected net effect across both positions is now exactly one character:**
`'` moved from rejected to accepted, in the IRIREF position and in the cursor.
Nothing else was widened anywhere.

### C — resolver-error detail was lost from the result

A custom resolver raising `ValueError("resolver bug")` produced
`redirect_resolution_status == "resolver_error"` but serialized `error: null`, so
the detail existed only inside `RedirectResolution` and never reached the record.

`_result()` now applies an explicit precedence:

```python
error = error or info.error or resolution.error
```

An explicit selector error wins, then the endpoint error on `AnswerInfo`, then the
resolver's own error. A contained resolver error is still an ordinary data outcome
— it is **not** converted into `query_failed`, which a new test asserts alongside
a second test confirming an endpoint failure still takes precedence.

### D — stale names

* the v4 source header said `category_extractor_ClaudeWeb_v3.py`; it now names v4;
* the regression module claimed "the real v3.3 selector code is exercised"; it now
  reads "v3.3 at the RED tag, v3.4 now", preserving the historical record that the
  three tests failed at `category-selector-v3.4-red`.

### Tests added

Five focused deterministic tests in the v4 selector suite: an 11-case
parametrisation pinning cursor rejection, apostrophe-cursor acceptance verbatim,
a composition test proving both predicates are applied without merging, resolver
error reaching `error`, and endpoint-error precedence. The suite grew 216 → 231.

### Final counts after the correction pass

| Suite | Result |
|---|---|
| frozen v3 selector | 171 passed, 2 deselected |
| frozen v3 runner | 73 passed |
| v3.4 blocker contracts | 4 passed |
| v4 selector | **231 passed, 2 deselected** |
| v4 runner | 94 passed |
| entire offline suite | **573 passed, 4 deselected, 0 failed** |

No `xfail`, `skip`, relaxed assertion or deselection change was used.

### Final hashes

| File | Lines | SHA-256 |
|---|---|---|
| `src/category_extractor_ClaudeWeb_v4.py` | 3607 | `921ff6d40790da0cd83a444c68aa65898b18e2bde3d92fe8739a7b7a412b0207` |
| `tests/test_category_extractor_v34_regressions.py` | 476 | `551b065a62ddc25f933f8423d87d565b7ed16067e6784179fb6bdffc6c82b414` |
| `tests/test_category_extractor_v4.py` | 3103 | `ac9ce57e984dcc98ba55c0216e04c15bd07ab368151d05a6e27a39aa1e399293` |
| `scripts/run_category_selector_v4.py` | 1059 | `b482028f52d3c4bde86e08789ef8b6b6972b95e75b75687b5d0bfe6b345016cd` |
| `tests/test_run_category_selector_v4.py` | 1525 | `6f55703350280760a304bc6f66ee116f7e810c829b0013a069fe7a76be23d6b2` |

### Residual risk added by this pass

Finding B shows that a context split can silently drop a requirement the old code
enforced as a side effect. The cursor was the only such position, but the general
lesson stands: when a merged validator is split, each resulting predicate must be
checked against what the merged one *incidentally* guaranteed, not only against
what it was documented to guarantee. The live-probe caveats in §11 are unchanged.
