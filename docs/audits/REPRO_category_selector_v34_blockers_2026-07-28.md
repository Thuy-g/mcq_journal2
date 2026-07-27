# Reproduction — the two core-selector defects blocking v3.4

**Date:** 2026-07-28
**Type:** test-first, offline. No network, no implementation change, no staging, commit, tag or push.
**Purpose:** turn audit findings D and E into deterministic failing regression tests against the frozen v3.3 selector, before any v3.4 implementation exists.

**Conclusion: `V3_4_REGRESSION_REPRODUCTION_CONFIRMED`**

---

## 1. Frozen baseline

| Revision | Value |
|---|---|
| `HEAD` | `e516a06029c5fa9e4c612954bbc64f3d1a474898` |
| `category-selector-v3.3-runner` | `e516a06029c5fa9e4c612954bbc64f3d1a474898` |
| `category-selector-v3.3-offline` | `ce740e1665778e0aa65896ac73324bfa0c41d244` |

`git diff` and `git diff --cached` were both empty before and after this turn.

| File | SHA-256 (verified before and after) |
|---|---|
| `src/category_extractor_ClaudeWeb_v2.py` | `cc594ef1fc637c9df402276d84e95dc39bb60487286f64dd12f2966acb1604bd` |
| `src/category_extractor_ClaudeWeb_v3.py` | `b9556d64f02ffdf6a6f393773a89b8d1204c00228b2f27ef882cd5c286ce1ac4` |
| `tests/test_category_extractor_v3.py` | `7f5b0461b1390116304e2256e840ed49c024e55061c01de4dd59cea4d7a987f2` |
| `scripts/run_category_selector_v3.py` | `d9787802339036aefc6fd5b976890655a3ab16b40a37bb97a97f184c58442693` |
| `tests/test_run_category_selector_v3.py` | `142acee98550aa40ee6f93bf50ade19dd60de94559e22b070b14219f4810eac3` |
| `data/category_answer_nodes_v2_demo.txt` | `d78621e4e9dc0a3709155f9f8ebdd98796bb06a3a264a374307e8e059b0dc51a` |
| `docs/audits/AUDIT_category_selector_v3_smoke_2026-07-27.md` | `38dff462d691539888c7f526c2a2be1c101261ec903a3c153734eccb8e8c1853` |

---

## 2. Baseline test results, before the new file existed

```
python -m py_compile (v3, runner, both existing test modules)          OK
pytest -q tests/test_category_extractor_v3.py -m "not integration"     171 passed, 2 deselected
pytest -q tests/test_run_category_selector_v3.py                        73 passed
pytest -q tests/ -m "not integration"                                  244 passed, 2 deselected
```

Both authorised output paths were verified absent before creation.

---

## 3. The new test module

`tests/test_category_extractor_v34_regressions.py` — 473 lines,
sha256 `9dbce965bec77e5c7a4fba731aea57da465c7cdeb4683d12423a1f38ac91b0a9`.

Four behavioural tests, exactly as specified:

| # | Test name | Role |
|---|---|---|
| 1 | `test_control_ordinary_redirect_is_followed_and_selects_a_class` | control — must pass on v3.3 |
| 2 | `test_d1_apostrophe_iri_is_accepted_and_embedded_raw_in_iriref_position` | regression D1 |
| 3 | `test_d2_apostrophe_redirect_target_is_followed_with_success_provenance` | regression D2 |
| 4 | `test_e_found_but_invalid_redirect_target_is_explicitly_reported` | regression E |

The module exercises the **real v3.3 selector**: `select_candidate_classes`,
`SparqlRunner`, `SparqlRedirectResolver`, `build_answer_info_query`,
`build_answer_categories_query`, `build_redirect_query`, `is_safe_uri`,
`ClassSelectionResult.to_dict`. No selector logic is duplicated into the test file.

### Fake transport design

`FakeEndpoint` is a subject-aware SPARQL double:

* routes on the `#qid:` marker the builders emit (`answer_info`,
  `answer_categories`, `category_counts`, `redirect`, `class_members*`) via the
  module's own `ce.query_id`;
* identifies the subject by matching the full `<uri>` form — including angle
  brackets — so `…/Makoto_Kobayashi` cannot be mistaken for
  `…/Makoto_Kobayashi_(physicist)`;
* mirrors the real endpoint's shape for an OPTIONAL-only `SELECT`: an entity with
  no label yields exactly one row with no bindings, not zero rows;
* returns redirect targets **verbatim** as the `?target` binding, which is how a
  real endpoint hands back a value the selector must then validate;
* never raises for an unmodelled subject — that is a successful zero-result — so
  no test can fail on an unexpected transport error. The only `AssertionError`
  it can raise is for a query id the fixture does not model at all, which none of
  the four tests reaches.

Each selection runs through one shared `SparqlRunner` with
`SparqlRedirectResolver(runner)` built over that same runner, asserted with
`resolver.runner is runner` — the production arrangement.

### Why the control proves the fixture works

`test_control_…` uses the same `FakeEndpoint`, the same `run_selection` helper and
the same redirect path as D2 and E, differing only in that its redirect target
(`…/Makoto_Kobayashi`) contains no apostrophe. It **passes on v3.3**, asserting
`query_uri == target`, `redirect_used is True`, `selection_status == "ok"`,
`selected_class` non-null and present in `recommended_classes`, and that a
`redirect` query was genuinely issued.

That pass establishes that the transport, the redirect fixture, the category
counts, the leak filter and the threshold configuration are all sound. The three
failures below therefore attach to selector behaviour, not to a defective fixture.

---

## 4. Result against frozen v3.3

```
python -m py_compile tests/test_category_extractor_v34_regressions.py       OK
python -m pytest -vv tests/test_category_extractor_v34_regressions.py --tb=short
```

```
test_control_ordinary_redirect_is_followed_and_selects_a_class          PASSED
test_d1_apostrophe_iri_is_accepted_and_embedded_raw_in_iriref_position  FAILED
test_d2_apostrophe_redirect_target_is_followed_with_success_provenance  FAILED
test_e_found_but_invalid_redirect_target_is_explicitly_reported         FAILED

3 failed, 1 passed in 0.04s
```

Full suite:

```
python -m pytest -q tests/ -m "not integration"
3 failed, 245 passed, 2 deselected
```

245 = the original 244 + the new control. Re-running the two pre-existing modules
alone still gives `244 passed, 2 deselected`, so no existing test changed behaviour.

---

## 5. Failure excerpts and mapping to audit findings

### D1 → audit finding **D** (validator over-rejection, builder boundary)

```
AssertionError: v3.4 contract D1 — a valid apostrophe-bearing IRI must be usable
as an Answer URI in IRIREF position. Violations:
  - is_safe_uri() rejects a syntactically valid IRIREF; offending character: "'"
  - build_answer_info_query() raised ValueError: unsafe or malformed answer URI:
    "http://dbpedia.org/resource/Shin'ichirō_Tomonaga"
  - build_answer_categories_query() raised ValueError: unsafe or malformed answer URI: …
  - build_redirect_query() raised ValueError: unsafe or malformed answer URI: …
```

The test first asserts its own premise — that the URI is a legal SPARQL 1.1
`IRIREF` body under rule [139] — so a failure cannot mean the test is asking for
something invalid. All three builders that place an Answer URI inside `<...>`
reject it, and the named offending character is the apostrophe.

### D2 → audit finding **D** (selector level) plus the success half of **E**

```
AssertionError: v3.4 contract D2 — an apostrophe-bearing redirect target must be
followed and the success recorded. Violations:
  - query_uri is 'http://dbpedia.org/resource/Sin-Itiro_Tomonaga', expected the raw
    canonical URI "http://dbpedia.org/resource/Shin'ichirō_Tomonaga"
    (the redirect target was not followed)
  - redirect_used is False, expected True
  - selection_status is 'no_label', expected 'ok'
  - selected_class is None, expected a class from the target
  - serialized record exposes no successful-redirect provenance; missing
    ['redirect_attempted', 'redirect_target', 'redirect_resolution_status',
     'redirect_rejected_reason']
```

This reproduces the live Tomonaga chain exactly: the endpoint returns the raw
canonical target, the selector abandons the hop, and the record retains the old
`query_uri` with `redirect_used = False` and `no_label`.

### E → audit finding **E** (provenance only)

```
AssertionError: v3.4 contract E — a found-but-rejected redirect target must be
reported explicitly. Violations:
  - serialized record exposes no redirect provenance; missing
    ['redirect_attempted', 'redirect_target', 'redirect_resolution_status',
     'redirect_rejected_reason'] … Without these, a found-and-rejected target is
    indistinguishable from a lookup that returned no target at all.
```

Note what did **not** appear in E's violation list: `redirect_used is False` and
`query_uri == original` both **held**, and the separate assertion that no
`answer_info`, `answer_categories` or `category_counts` query was issued against
the rejected target also **passed**. E therefore fails on exactly one thing —
absent provenance — and on nothing else.

---

## 6. D2 and E are independent

| | D2 target | E target |
|---|---|---|
| URI | `…/Shin'ichirō_Tomonaga` | `…/Invalid Redirect Target` |
| Legal SPARQL `IRIREF` body (rule [139]) | **yes** | **no** (contains a space) |
| `is_safe_uri` on v3.3 | `False` | `False` |
| Still rejected after D is fixed | no — must be accepted | **yes** — permanently invalid |

E's target is forbidden by the IRIREF grammar itself, not by the project's
character-class policy. It will therefore remain a rejected target after D is
fixed, and E will keep testing provenance rather than character-class policy.
Conversely D2 will pass once D is fixed **and** provenance is added — it depends
on both, which is why the two findings are reported separately in the audit.

---

## 7. Compliance statements

* **The percent-encoded URI was not used.** `…/Shin%27ichir%C5%8D_Tomonaga`
  appears nowhere in the test module except as a negative assertion: D1 fails if a
  builder emits `%27` or `%C5%8D`, and D2 asserts `"%27" not in result.query_uri`.
  The C0 probe measured that spelling at 0 triples, so it is a distinct RDF term,
  not an encoding of the canonical one.
* **No implementation file changed.** All six protected paths retain the hashes in
  §1; `git diff` over them is empty.
* **Test-design restrictions honoured:** no `xfail`, no `skip`, no network, no
  SQLite cache, no SBERT, no local index, no subprocess, no monkeypatch, no
  assertion on `SCHEMA_VERSION`, no dependence on absolute paths, timestamps or
  execution order, no modification of an existing test, no requirement to change
  `sparql_cache_v3.0`.
* **No failure comes from a fixture error.** The control passes through the same
  fixture; the fake transport cannot raise for an unmodelled subject; and every
  failure is a deliberate `AssertionError` naming the violated contract.

---

## 8. Behavioural contract these tests pin

Restated from the audit; no implementation is proposed here.

1. A syntactically valid http(s) IRI containing `'` is accepted wherever the value
   is interpolated into an `<...>` IRIREF position, and embedded verbatim.
2. Such an IRI is never percent-encoded to make it pass validation.
3. An apostrophe-bearing redirect target is followed, with `original_uri`
   unchanged, `query_uri` moved to the target, and `redirect_used` true.
4. Every redirect outcome is serialized explicitly, with semantics equivalent to
   `redirect_attempted`, `redirect_target`, `redirect_resolution_status`,
   `redirect_rejected_reason`.
5. A found-but-rejected target is distinguishable from a lookup that returned no
   target, and is never queried against.

---

## 9. Final state

| Item | Value |
|---|---|
| `tests/test_category_extractor_v34_regressions.py` | 473 lines, sha256 `9dbce965bec77e5c7a4fba731aea57da465c7cdeb4683d12423a1f38ac91b0a9` |
| Protected source/test/data diffs | all empty |
| `git diff --cached` | clean — nothing staged |
| Suite | 245 passed, 3 failed, 2 deselected |

Nothing was staged or committed: the three failing tests are intentionally left
in the working tree as the specification for the v3.4 patch.

**`V3_4_REGRESSION_REPRODUCTION_CONFIRMED`**
