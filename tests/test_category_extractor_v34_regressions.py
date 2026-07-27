############################################################################
# tests/test_category_extractor_v34_regressions.py
#
# Test-first reproduction of the two core-selector defects that block v3.4,
# as classified in docs/audits/AUDIT_category_selector_v3_smoke_2026-07-27.md:
#
#   D — a syntactically valid apostrophe-bearing http(s) IRI is rejected by the
#       shared unsafe-character class, both as a direct Answer URI and as a
#       redirect target, even though the position it occupies is an IRIREF
#       (`<...>`) where SPARQL 1.1 rule [139] permits an apostrophe.
#
#   E — a redirect target that IS returned by the endpoint but then fails
#       validation is discarded with no trace: the serialized record exposes
#       only `redirect_used`, so a found-and-rejected target is indistinguishable
#       from a lookup that found nothing.
#
# Committed at tag `category-selector-v3.4-red`, where this module ran against the
# frozen v3.3 selector (sha256 b9556d64…) and produced ONE PASS and THREE FAILURES.
# The passing control proved the fake transport and redirect fixture were sound, so
# the three failures were attributable to selector behaviour, not to the fixture.
#
# It now targets category_extractor_ClaudeWeb_v4 and must report FOUR PASSES. Only
# the import and these comments changed; not one behavioural contract was weakened.
#
# Offline and deterministic: no network, no SQLite cache, no SBERT, no local
# index, no subprocess, no monkeypatch, no xfail, no skip, no ordering or path
# dependence. The real selector code under test is exercised — v3.3 at the RED
# tag, v3.4 now; only the transport is replaced.
#
# Run:
#     python -m pytest -vv tests/test_category_extractor_v34_regressions.py --tb=short
############################################################################

from __future__ import annotations

import pathlib
import re
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import category_extractor_ClaudeWeb_v4 as ce  # noqa: E402

RESOURCE = "http://dbpedia.org/resource/"
CATEGORY = ce.CATEGORY_PREFIX

# The exact RDF terms from the live probe. The percent-encoded spelling
# (…/Shin%27ichir%C5%8D_Tomonaga) is deliberately NOT used anywhere in this
# module: the C0 probe measured it at 0 triples, so it is a different RDF term,
# not an encoding of the one below.
OLD_TOMONAGA = RESOURCE + "Sin-Itiro_Tomonaga"
RAW_CANONICAL_TOMONAGA = RESOURCE + "Shin'ichirō_Tomonaga"

KOBAYASHI_ORIGINAL = RESOURCE + "Makoto_Kobayashi_(physicist)"
KOBAYASHI_CANONICAL = RESOURCE + "Makoto_Kobayashi"

REJECTED_SOURCE = RESOURCE + "Redirect_Source_Example"
INVALID_TARGET = RESOURCE + "Invalid Redirect Target"  # a space: never a legal IRIREF

# Category names chosen to share no content token with any Answer label used
# here, so the leak filter cannot reject them for an unrelated reason.
CAT_THEORETICAL = CATEGORY + "Japanese_theoretical_physicists"
CAT_NAGOYA = CATEGORY + "Scientists_from_Nagoya"
CAT_QUANTUM = CATEGORY + "Quantum_electrodynamics"
CAT_LAUREATES = CATEGORY + "Nobel_laureates_in_Physics"

# SPARQL 1.1 grammar rule [139] IRIREF: '<' ([^<>"{}|^`\] - [#x00-#x20])* '>'.
# Used only to assert the PREMISE of regression D — that the apostrophe-bearing
# IRI really is legal inside <...>. If this premise ever failed, the test itself
# would be wrong, so it is checked explicitly rather than assumed.
IRIREF_BODY = re.compile(r"^[^<>\"{}|^`\\\x00-\x20]*$")

# The serialized redirect provenance v3.4 must expose. Alternative spellings are
# accepted so the contract is about semantics, not about one chosen attribute
# name; v3.3 exposes none of them under any spelling.
PROVENANCE_CONTRACT = {
    "redirect_attempted": ("redirect_attempted",),
    "redirect_target": ("redirect_target",),
    "redirect_resolution_status": ("redirect_resolution_status", "redirect_status"),
    "redirect_rejected_reason": ("redirect_rejected_reason", "redirect_rejection_reason"),
}


# ---------------------------------------------------------------------------
# Deterministic fake transport
# ---------------------------------------------------------------------------


class FakeEndpoint:
    """Subject-aware fake SPARQL transport for the real selector under test.

    Routes on the ``#qid:`` marker the query builders emit and on which
    ``<uri>`` appears in the query text, so it answers exactly as an endpoint
    would for the entities it knows about and returns a successful zero-result
    for everything else.

    ``redirects`` values are returned verbatim as the ``?target`` binding, which
    is how an endpoint hands back a redirect target the selector must then
    validate. Nothing here raises: a query for an unknown subject is a
    zero-result, never an error, so no test can fail on an unexpected transport
    exception.
    """

    def __init__(self, *, resources=None, categories=None, redirects=None):
        self.endpoint = "http://fake.invalid/sparql"
        self.language = "en"
        # uri -> {"label": str|None, "categories": tuple[str, ...]}
        self.resources = dict(resources or {})
        # category uri -> remote member count
        self.categories = dict(categories or {})
        # source uri -> target string returned verbatim
        self.redirects = dict(redirects or {})
        self.queries: list[str] = []
        self.calls: list[str] = []

    @staticmethod
    def _cell(value):
        return {"value": str(value)}

    def _subject(self, query):
        """Which known resource this query is about, matched on the full <uri>."""
        for uri in self.resources:
            if f"<{uri}>" in query:
                return uri
        for uri in self.redirects:
            if f"<{uri}>" in query:
                return uri
        return None

    def run(self, query):
        qid = ce.query_id(query)
        self.queries.append(query)
        self.calls.append(qid)
        rows = self._rows(qid, query)
        return ce.QueryResult(
            status=ce.QueryStatus.OK if rows else ce.QueryStatus.ZERO_RESULTS,
            rows=tuple(rows),
            endpoint=self.endpoint,
            language=self.language,
        )

    def _rows(self, qid, query):
        subject = self._subject(query)

        if qid == "answer_info":
            entry = self.resources.get(subject)
            if entry is None:
                return []
            # A real endpoint answering an OPTIONAL-only SELECT returns exactly
            # one row, with no bindings when the entity has no label. The v3.3
            # builder emits such a SELECT, so the fake mirrors that shape.
            label = entry.get("label")
            return [{"label": self._cell(label)}] if label else [{}]

        if qid == "answer_categories":
            entry = self.resources.get(subject)
            if entry is None:
                return []
            return [{"cat": self._cell(c)} for c in entry.get("categories", ())]

        if qid == "category_counts":
            return [
                {"cat": self._cell(cat), "c": self._cell(count)}
                for cat, count in sorted(self.categories.items())
                if f"<{cat}>" in query
            ]

        if qid == "redirect":
            target = self.redirects.get(subject)
            return [{"target": self._cell(target)}] if target else []

        if qid in ("class_members", "class_members_batch"):
            return []

        raise AssertionError(f"fixture does not model query id {qid!r}")

    # -- helpers used by assertions ----------------------------------------

    def queries_mentioning(self, uri):
        """Every query that placed ``uri`` in an IRIREF position."""
        return [q for q in self.queries if f"<{uri}>" in q]


def run_selection(client, answer_uri):
    """Drive the real v3.3 selector over ``client`` with redirects enabled.

    One shared runner, and the built-in resolver constructed over that same
    runner — the arrangement the batch runner uses in production.
    """
    runner = ce.SparqlRunner(client=client)
    resolver = ce.SparqlRedirectResolver(runner)
    assert resolver.runner is runner
    result = ce.select_candidate_classes(
        answer_uri,
        mode="recommended",
        runner=runner,
        resolve_redirects=True,
        redirect_resolver=resolver,
        top_n=5,
    )
    return result, runner


def provenance(record):
    """Extract the redirect provenance v3.4 must serialize.

    Returns ``(values, missing)``: a mapping of canonical field name to the value
    found under any accepted spelling, and the list of canonical names absent
    under every spelling.
    """
    values, missing = {}, []
    for canonical, spellings in PROVENANCE_CONTRACT.items():
        for key in spellings:
            if key in record:
                values[canonical] = record[key]
                break
        else:
            missing.append(canonical)
    return values, missing


# ---------------------------------------------------------------------------
# CONTROL — proves the fixture and the redirect path work on v3.3
# ---------------------------------------------------------------------------


def test_control_ordinary_redirect_is_followed_and_selects_a_class():
    """An ordinary redirect target with no apostrophe must still work on v3.3.

    This is the fixture's proof of correctness. If this test ever fails, the
    three regressions below say nothing about selector behaviour, because the
    transport or the redirect fixture would be at fault.
    """
    client = FakeEndpoint(
        resources={
            KOBAYASHI_ORIGINAL: {"label": None, "categories": ()},
            KOBAYASHI_CANONICAL: {
                "label": "Makoto Kobayashi",
                "categories": (CAT_THEORETICAL, CAT_NAGOYA),
            },
        },
        categories={CAT_THEORETICAL: 19, CAT_NAGOYA: 19},
        redirects={KOBAYASHI_ORIGINAL: KOBAYASHI_CANONICAL},
    )

    result, _ = run_selection(client, KOBAYASHI_ORIGINAL)

    assert result.original_uri == KOBAYASHI_ORIGINAL, "the original URI is never rewritten"
    assert result.query_uri == KOBAYASHI_CANONICAL
    assert result.redirect_used is True
    assert result.selection_status is ce.SelectionStatus.OK
    assert result.selected_class is not None
    assert result.selected_class in [
        c.category_uri for c in result.recommended_classes
    ]
    assert "redirect" in client.calls, "the redirect lookup must actually be issued"


# ---------------------------------------------------------------------------
# REGRESSION D1 — a valid apostrophe-bearing IRI is usable as an Answer URI
# ---------------------------------------------------------------------------


def test_d1_apostrophe_iri_is_accepted_and_embedded_raw_in_iriref_position():
    """Audit finding D, at the query-builder boundary.

    Contract for v3.4: a syntactically valid http(s) IRI containing an
    apostrophe is accepted, and every builder that places it inside ``<...>``
    embeds it verbatim — never percent-encoded, because the percent-encoded
    spelling is a different RDF term.

    Fails on v3.3: one shared unsafe-character class guards both IRIREF
    positions and the one quoted-literal position, and it lists ``'``.
    """
    uri = RAW_CANONICAL_TOMONAGA

    # Premise: the IRI really is legal inside <...>. Asserted, not assumed.
    assert IRIREF_BODY.match(uri), (
        "fixture premise broken: the test URI is not a legal SPARQL IRIREF body"
    )

    violations = []
    if not ce.is_safe_uri(uri):
        violations.append(
            "is_safe_uri() rejects a syntactically valid IRIREF; "
            "offending character: "
            f"{(ce._UNSAFE_URI_CHARS.search(uri) or [None]) and ce._UNSAFE_URI_CHARS.search(uri).group(0)!r}"
        )

    builders = (
        ("build_answer_info_query", lambda u: ce.build_answer_info_query(u)),
        ("build_answer_categories_query", lambda u: ce.build_answer_categories_query(u)),
        ("build_redirect_query", lambda u: ce.build_redirect_query(u)),
    )
    for name, build in builders:
        try:
            query = build(uri)
        except Exception as exc:  # noqa: BLE001 - the rejection IS the finding
            violations.append(f"{name}() raised {type(exc).__name__}: {exc}")
            continue
        if f"<{uri}>" not in query:
            violations.append(f"{name}() did not embed the raw IRI inside <...>")
        if "%27" in query or "%C5%8D" in query:
            violations.append(
                f"{name}() percent-encoded the IRI; %27 denotes a different RDF term"
            )

    assert not violations, (
        "v3.4 contract D1 — a valid apostrophe-bearing IRI must be usable as an "
        "Answer URI in IRIREF position. Violations:\n  - " + "\n  - ".join(violations)
    )


# ---------------------------------------------------------------------------
# REGRESSION D2 — an apostrophe-bearing redirect target is followed
# ---------------------------------------------------------------------------


def test_d2_apostrophe_redirect_target_is_followed_with_success_provenance():
    """Audit finding D, at the selector level, plus the success half of E.

    Contract for v3.4: when the endpoint returns an apostrophe-bearing canonical
    target, the selector follows it and records that it did so explicitly.

    Fails on v3.3 for two compounding reasons: the target is rejected by the
    shared validator, so the hop is abandoned; and the serialized record carries
    no provenance that would reveal it.
    """
    client = FakeEndpoint(
        resources={
            OLD_TOMONAGA: {"label": None, "categories": ()},
            RAW_CANONICAL_TOMONAGA: {
                "label": "Shin'ichirō Tomonaga",
                "categories": (CAT_QUANTUM, CAT_LAUREATES),
            },
        },
        categories={CAT_QUANTUM: 40, CAT_LAUREATES: 120},
        redirects={OLD_TOMONAGA: RAW_CANONICAL_TOMONAGA},
    )

    result, _ = run_selection(client, OLD_TOMONAGA)
    record = result.to_dict()
    values, missing = provenance(record)

    violations = []
    if result.original_uri != OLD_TOMONAGA:
        violations.append(f"original_uri was rewritten to {result.original_uri!r}")
    if result.query_uri != RAW_CANONICAL_TOMONAGA:
        violations.append(
            f"query_uri is {result.query_uri!r}, expected the raw canonical URI "
            f"{RAW_CANONICAL_TOMONAGA!r} (the redirect target was not followed)"
        )
    if result.redirect_used is not True:
        violations.append(f"redirect_used is {result.redirect_used!r}, expected True")
    if result.selection_status is not ce.SelectionStatus.OK:
        violations.append(
            f"selection_status is {result.selection_status.value!r}, expected 'ok'"
        )
    if result.selected_class is None:
        violations.append("selected_class is None, expected a class from the target")

    if missing:
        violations.append(
            "serialized record exposes no successful-redirect provenance; missing "
            f"{missing} (required: redirect_attempted == True, redirect_target == "
            f"{RAW_CANONICAL_TOMONAGA!r}, redirect_resolution_status == 'followed', "
            "redirect_rejected_reason is None)"
        )
    else:
        if values.get("redirect_attempted") is not True:
            violations.append(f"redirect_attempted is {values['redirect_attempted']!r}")
        if values.get("redirect_target") != RAW_CANONICAL_TOMONAGA:
            violations.append(f"redirect_target is {values['redirect_target']!r}")
        if values.get("redirect_resolution_status") != "followed":
            violations.append(
                f"redirect_resolution_status is {values['redirect_resolution_status']!r}"
            )
        if values.get("redirect_rejected_reason") is not None:
            violations.append(
                f"redirect_rejected_reason is {values['redirect_rejected_reason']!r}, "
                "expected None on a followed hop"
            )

    # The target must never be silently rewritten into the percent-encoded term.
    assert "%27" not in result.query_uri, "query_uri was percent-encoded"

    assert not violations, (
        "v3.4 contract D2 — an apostrophe-bearing redirect target must be followed "
        "and the success recorded. Violations:\n  - " + "\n  - ".join(violations)
    )


# ---------------------------------------------------------------------------
# REGRESSION E — a found-but-rejected target is reported, not hidden
# ---------------------------------------------------------------------------


def test_e_found_but_invalid_redirect_target_is_explicitly_reported():
    """Audit finding E, independent of the apostrophe defect.

    The target here contains a space, which SPARQL 1.1 rule [139] forbids inside
    ``<...>``. It is therefore correctly rejected both today and after D is
    fixed — so this test keeps testing provenance, not character-class policy.

    Contract for v3.4: the record must say a redirect was attempted, name the
    target that came back, and give a machine-readable reason for rejecting it.
    v3.3 records only ``redirect_used = False``, which is exactly what a lookup
    that found nothing also produces.
    """
    client = FakeEndpoint(
        resources={REJECTED_SOURCE: {"label": None, "categories": ()}},
        redirects={REJECTED_SOURCE: INVALID_TARGET},
    )

    result, _ = run_selection(client, REJECTED_SOURCE)
    record = result.to_dict()
    values, missing = provenance(record)

    violations = []
    # These two hold on v3.3 already and must keep holding on v3.4.
    if result.redirect_used is not False:
        violations.append(
            f"redirect_used is {result.redirect_used!r}; an invalid target must not "
            "be treated as followed"
        )
    if result.query_uri != REJECTED_SOURCE:
        violations.append(
            f"query_uri is {result.query_uri!r}; it must stay at the original URI"
        )

    if missing:
        violations.append(
            "serialized record exposes no redirect provenance; missing "
            f"{missing} (required: redirect_attempted == True, redirect_target == "
            f"{INVALID_TARGET!r}, redirect_resolution_status == 'rejected', "
            "redirect_rejected_reason nonempty and machine-readable). Without these, "
            "a found-and-rejected target is indistinguishable from a lookup that "
            "returned no target at all."
        )
    else:
        if values.get("redirect_attempted") is not True:
            violations.append(f"redirect_attempted is {values['redirect_attempted']!r}")
        if values.get("redirect_target") != INVALID_TARGET:
            violations.append(
                f"redirect_target is {values['redirect_target']!r}, expected the exact "
                f"returned target {INVALID_TARGET!r}"
            )
        if values.get("redirect_resolution_status") != "rejected":
            violations.append(
                f"redirect_resolution_status is {values['redirect_resolution_status']!r}, "
                "expected 'rejected'"
            )
        reason = values.get("redirect_rejected_reason")
        if not isinstance(reason, str) or not reason.strip():
            violations.append(
                f"redirect_rejected_reason is {reason!r}, expected a nonempty "
                "machine-readable string"
            )

    # Independent of provenance: the rejected target must never be queried.
    leaked = client.queries_mentioning(INVALID_TARGET)
    assert not leaked, (
        f"{len(leaked)} query/queries were issued against the rejected redirect "
        "target; a target that failed validation must never reach the endpoint"
    )
    assert "redirect" in client.calls, "the redirect lookup must actually be issued"

    assert not violations, (
        "v3.4 contract E — a found-but-rejected redirect target must be reported "
        "explicitly. Violations:\n  - " + "\n  - ".join(violations)
    )
