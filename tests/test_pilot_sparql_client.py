############################################################################
# tests/test_pilot_sparql_client.py
#
# Contract tests for src/classes/sparql_client.py.
#
# What these tests defend:
#   * only https://dbpedia.org/sparql is reachable;
#   * a URI is REFUSED rather than escaped, and apostrophes/Unicode survive;
#   * keyset pagination queries pair FILTER(STR(?x) > c) with ORDER BY STR(?x);
#   * owl:sameAs never appears in any query;
#   * HTTP 429/500/502/503/504, connect timeout, read timeout, connection error
#     are retried; 4xx and malformed bodies are NOT;
#   * a 200 with an unparseable body never becomes "zero results";
#   * Retry-After is honoured but capped;
#   * strict offline mode has no socket at all.
#
# Every test is offline and deterministic: the transport is a test double, sleep
# and the clock are injected, and the jitter RNG is seeded.
#
# Run:
#     python -m pytest -vv tests/test_pilot_sparql_client.py
############################################################################

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from classes import sparql_client as sc  # noqa: E402

ANSWER_TOMONAGA = "http://dbpedia.org/resource/Shin'ichirō_Tomonaga"
ANSWER_SATO = "http://dbpedia.org/resource/Eisaku_Satō"
CLASS_JNL = "http://dbpedia.org/resource/Category:Japanese_Nobel_laureates"


# --- Test doubles ----------------------------------------------------------

class FakeTransport:
    """Returns queued HttpResponses or raises queued TransportErrors."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[tuple[str, str]] = []

    def post(self, endpoint: str, query: str) -> sc.HttpResponse:
        self.calls.append((endpoint, query))
        if not self.script:
            raise AssertionError("transport called more times than scripted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def ok_body(*member_uris: str) -> str:
    return json.dumps({
        "head": {"vars": ["member"]},
        "results": {"bindings": [
            {"member": {"type": "uri", "value": u}} for u in member_uris]},
    })


def ok_response(*member_uris: str) -> sc.HttpResponse:
    return sc.HttpResponse(status_code=200, text=ok_body(*member_uris))


def make_client(script, **kwargs) -> tuple[sc.SparqlPageClient, list[float]]:
    """A client whose sleeps are recorded instead of performed."""
    slept: list[float] = []
    ticks = iter(range(1, 10_000))
    client = sc.SparqlPageClient(
        transport=FakeTransport(script),
        sleep=slept.append,
        clock=lambda: float(next(ticks)),
        **kwargs,
    )
    return client, slept


def fetch(client: sc.SparqlPageClient, query: str = "#qid: t\nSELECT 1", **kwargs):
    return client.fetch(query, query_kind=sc.QueryKind.CLASS_MEMBERS_PAGE.value,
                        **kwargs)


# --- Endpoint scope --------------------------------------------------------

def test_only_dbpedia_endpoint_is_authorized():
    assert sc.ALLOWED_ENDPOINTS == ("https://dbpedia.org/sparql",)
    assert sc.require_allowed_endpoint(sc.DBPEDIA_ENDPOINT) == sc.DBPEDIA_ENDPOINT


@pytest.mark.parametrize("endpoint", [
    "https://query.wikidata.org/sparql",
    "http://dbpedia.org/sparql",             # scheme differs
    "https://dbpedia.org/sparql/",           # trailing slash differs
    "https://evil.example/sparql",
])
def test_other_endpoints_are_refused(endpoint):
    with pytest.raises(sc.EndpointNotAllowedError):
        sc.require_allowed_endpoint(endpoint)


def test_client_construction_refuses_an_unapproved_endpoint():
    with pytest.raises(sc.EndpointNotAllowedError):
        sc.SparqlPageClient(transport=FakeTransport([]),
                            endpoint="https://query.wikidata.org/sparql")


# --- URI handling ----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("<http://dbpedia.org/resource/Carbon>", "http://dbpedia.org/resource/Carbon"),
    ("  http://dbpedia.org/resource/Carbon  ", "http://dbpedia.org/resource/Carbon"),
    ("<" + ANSWER_TOMONAGA + ">", ANSWER_TOMONAGA),
    ("", ""),
    (None, ""),
])
def test_strip_uri_brackets(raw, expected):
    assert sc.strip_uri_brackets(raw) == expected


def test_apostrophe_and_unicode_uris_are_safe():
    """v3.3 rejected these; the IRIREF character class must not.

    An apostrophe terminates neither an IRIREF nor a double-quoted literal, and
    Shin'ichirō Tomonaga is pilot slot 2 — refusing it would drop an approved
    Answer.
    """
    assert sc.is_safe_iri(ANSWER_TOMONAGA)
    assert sc.is_safe_iri(ANSWER_SATO)
    assert sc.validate_iri(ANSWER_TOMONAGA) == ANSWER_TOMONAGA


@pytest.mark.parametrize("bad", [
    "http://dbpedia.org/resource/A B",          # space
    'http://dbpedia.org/resource/A"B',          # double quote
    "http://dbpedia.org/resource/A<B",
    "http://dbpedia.org/resource/A>B",
    "http://dbpedia.org/resource/A{B}",
    "http://dbpedia.org/resource/A|B",
    "http://dbpedia.org/resource/A\\B",
    "http://dbpedia.org/resource/A^B",
    "http://dbpedia.org/resource/A`B",
    "http://dbpedia.org/resource/A\nB",
    "http://dbpedia.org/resource/A\x7fB",
    "ftp://dbpedia.org/resource/A",             # wrong scheme
    "not a uri",
    "",
    None,
])
def test_unsafe_iris_are_refused_not_escaped(bad):
    assert not sc.is_safe_iri(bad)
    with pytest.raises(sc.UnsafeUriError):
        sc.validate_iri(bad)


def test_cursor_must_satisfy_both_contexts():
    """A cursor is an IRI compared inside a quoted literal, so both apply."""
    assert sc.validate_cursor(ANSWER_TOMONAGA) == ANSWER_TOMONAGA
    with pytest.raises(sc.UnsafeUriError):
        sc.validate_cursor("Carbon")                    # not an IRI
    with pytest.raises(sc.UnsafeUriError):
        sc.validate_cursor('http://dbpedia.org/resource/A"B')


def test_literals_and_blank_nodes_are_not_iri_members():
    assert sc.is_iri_member("http://dbpedia.org/resource/Carbon")
    assert not sc.is_iri_member("Carbon")
    assert not sc.is_iri_member("_:b0")
    assert not sc.is_iri_member(None)


# --- Local-KG lookup ladder ------------------------------------------------

def test_ascii_uri_yields_exactly_bracketed_then_bare():
    forms = sc.local_lookup_forms("http://dbpedia.org/resource/Carbon")
    assert forms == (
        (sc.LOOKUP_FORM_BRACKETED, "<http://dbpedia.org/resource/Carbon>"),
        (sc.LOOKUP_FORM_BARE, "http://dbpedia.org/resource/Carbon"),
    )


def test_bracketed_form_is_tried_first():
    """The pinned pickle stores <uri>; that must be the first key attempted."""
    forms = sc.local_lookup_forms(ANSWER_TOMONAGA)
    assert forms[0] == (sc.LOOKUP_FORM_BRACKETED, f"<{ANSWER_TOMONAGA}>")


def test_unicode_uri_adds_an_nfd_alternative():
    forms = dict(sc.local_lookup_forms(ANSWER_TOMONAGA))
    assert sc.LOOKUP_FORM_NFD_BRACKETED in forms
    import unicodedata
    assert forms[sc.LOOKUP_FORM_NFD_BRACKETED] == (
        "<" + unicodedata.normalize("NFD", ANSWER_TOMONAGA) + ">")


def test_percent_encoded_uri_offers_a_decoded_alternative():
    encoded = "http://dbpedia.org/resource/Shin%27ichir%C5%8D_Tomonaga"
    forms = dict(sc.local_lookup_forms(encoded))
    assert forms[sc.LOOKUP_FORM_PERCENT_DECODED_BRACKETED] == f"<{ANSWER_TOMONAGA}>"


def test_lookup_forms_are_deduplicated_and_order_preserved():
    forms = sc.local_lookup_forms("http://dbpedia.org/resource/Carbon")
    keys = [k for _n, k in forms]
    assert len(keys) == len(set(keys))
    assert [n for n, _k in forms] == [n for n in sc.LOOKUP_FORM_ORDER
                                     if n in {x for x, _ in forms}]


def test_brackets_on_input_do_not_double_wrap():
    a = sc.local_lookup_forms("<http://dbpedia.org/resource/Carbon>")
    b = sc.local_lookup_forms("http://dbpedia.org/resource/Carbon")
    assert a == b


# --- Query builders --------------------------------------------------------

def test_members_query_uses_dcterms_subject_and_is_distinct():
    query = sc.build_class_members_page_query(CLASS_JNL)
    assert "dcterms:subject" in query
    assert "SELECT DISTINCT" in query
    assert f"<{CLASS_JNL}>" in query
    assert "isIRI(?member)" in query
    assert sc.query_id(query) == sc.QID_CLASS_MEMBERS_PAGE


def test_members_query_pairs_the_keyset_filter_with_the_same_sort_expression():
    """A LIMIT without a matching ORDER BY expression makes paging unsound."""
    query = sc.build_class_members_page_query(
        CLASS_JNL, page_size=500, after=ANSWER_TOMONAGA)
    assert f'FILTER(STR(?member) > "{ANSWER_TOMONAGA}")' in query
    assert "ORDER BY STR(?member)" in query
    assert "LIMIT 500" in query
    assert "OFFSET" not in query


def test_every_limited_query_has_an_order_by():
    for query in (sc.build_class_members_page_query(CLASS_JNL),
                  sc.build_class_members_page_query(CLASS_JNL, after=ANSWER_SATO)):
        if "LIMIT" in query:
            assert "ORDER BY" in query


def test_members_query_rejects_a_bad_page_size():
    with pytest.raises(ValueError):
        sc.build_class_members_page_query(CLASS_JNL, page_size=0)


def test_redirect_query_uses_wikiPageRedirects_and_never_sameAs():
    query = sc.build_redirect_batch_query([ANSWER_TOMONAGA, ANSWER_SATO])
    assert "dbo:wikiPageRedirects" in query
    assert "sameAs" not in query
    assert "owl:" not in query
    assert sc.query_id(query) == sc.QID_REDIRECT_BATCH


def test_no_query_builder_emits_owl_sameAs():
    """Cross-KG sameAs substitution would silently change the candidate pool."""
    queries = [
        sc.build_class_members_page_query(CLASS_JNL),
        sc.build_class_members_page_query(CLASS_JNL, after=ANSWER_SATO),
        sc.build_redirect_batch_query([ANSWER_SATO]),
    ]
    for query in queries:
        assert "sameAs" not in query


def test_redirect_query_refuses_an_empty_batch():
    with pytest.raises(ValueError):
        sc.build_redirect_batch_query([])


def test_query_fingerprint_includes_the_endpoint():
    query = sc.build_class_members_page_query(CLASS_JNL)
    a = sc.query_fingerprint(sc.DBPEDIA_ENDPOINT, query)
    b = sc.query_fingerprint("https://other.example/sparql", query)
    assert a != b
    assert a == sc.query_fingerprint(sc.DBPEDIA_ENDPOINT, query)


def test_different_cursors_produce_different_fingerprints():
    """Resume depends on this: page N's key must encode page N-1's last member."""
    first = sc.build_class_members_page_query(CLASS_JNL)
    second = sc.build_class_members_page_query(CLASS_JNL, after=ANSWER_SATO)
    assert (sc.query_fingerprint(sc.DBPEDIA_ENDPOINT, first)
            != sc.query_fingerprint(sc.DBPEDIA_ENDPOINT, second))


# --- SPARQL JSON parsing ---------------------------------------------------

def test_parse_sparql_json_reads_bindings():
    rows = sc.parse_sparql_json(ok_body("http://dbpedia.org/resource/Carbon"))
    assert sc.binding_value(rows[0], "member") == "http://dbpedia.org/resource/Carbon"


def test_parse_sparql_json_accepts_zero_bindings():
    rows = sc.parse_sparql_json(json.dumps({"results": {"bindings": []}}))
    assert rows == ()


@pytest.mark.parametrize("body", [
    "<html>503 Service Unavailable</html>",
    "",
    "{",
    "[1, 2, 3]",
    json.dumps({"head": {}}),
    json.dumps({"results": {}}),
    json.dumps({"results": {"bindings": "nope"}}),
    json.dumps({"results": {"bindings": [1]}}),
])
def test_malformed_bodies_raise_rather_than_parse_as_empty(body):
    with pytest.raises(sc.MalformedSparqlJson):
        sc.parse_sparql_json(body)


# --- HTTP status classification -------------------------------------------

@pytest.mark.parametrize("status", [200, 204, 299])
def test_success_statuses_classify_as_success(status):
    assert sc.classify_http_status(status) is None


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_required_statuses_are_retryable(status):
    assert sc.classify_http_status(status) == sc.FailureClass.RETRYABLE_FAILURE.value


@pytest.mark.parametrize("status", [400, 401, 403, 404, 414])
def test_other_4xx_is_permanent(status):
    assert (sc.classify_http_status(status)
            == sc.FailureClass.PERMANENT_QUERY_REJECTED.value)


# --- Retry-After -----------------------------------------------------------

def test_retry_after_delta_seconds():
    assert sc.parse_retry_after("7") == 7.0


def test_retry_after_http_date_in_the_past_is_zero_not_negative():
    assert sc.parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


@pytest.mark.parametrize("value", [None, "", "soon", "-"])
def test_unusable_retry_after_is_ignored(value):
    assert sc.parse_retry_after(value) is None


def test_retry_after_is_capped_by_backoff_cap():
    """A hostile or mistaken header must not be able to stall the run."""
    client, slept = make_client(
        [sc.HttpResponse(429, "slow down", retry_after="86400"),
         ok_response("http://dbpedia.org/resource/Carbon")],
        max_attempts=2, backoff_cap=5.0, jitter_fraction=0.0)
    fetch(client)
    assert slept == [5.0]


# --- Backoff ---------------------------------------------------------------

def test_backoff_grows_exponentially_and_is_capped():
    delays = [sc.backoff_delay(a, base=1.0, cap=8.0, jitter_fraction=0.0)
              for a in range(1, 7)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 8.0, 8.0]


def test_backoff_jitter_stays_inside_its_bound_and_is_seedable():
    import random
    values = [sc.backoff_delay(3, base=1.0, cap=100.0, jitter_fraction=0.25,
                               rng=random.Random(7)) for _ in range(5)]
    assert all(3.0 <= v <= 5.0 for v in values)
    assert len(set(values)) == 1          # same seed -> same delay


# --- Retry behaviour -------------------------------------------------------

@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_status_recovers_on_a_later_attempt(status):
    client, slept = make_client(
        [sc.HttpResponse(status, "transient"),
         ok_response("http://dbpedia.org/resource/Carbon")],
        max_attempts=3, jitter_fraction=0.0)
    page = fetch(client)
    assert page.page_state == sc.PageState.PAGE_COMPLETE.value
    assert page.row_count == 1
    assert page.attempt_count == 2
    assert page.http_status == 200
    assert slept == [1.0]
    assert page.attempts[0].failure_class == sc.FailureClass.RETRYABLE_FAILURE.value
    assert page.attempts[0].http_status == status


def test_503_then_429_then_success_records_every_attempt():
    client, slept = make_client(
        [sc.HttpResponse(503, "a"), sc.HttpResponse(429, "b"),
         ok_response("http://dbpedia.org/resource/Carbon")],
        max_attempts=4, jitter_fraction=0.0)
    page = fetch(client)
    assert [a.http_status for a in page.attempts] == [503, 429, 200]
    assert slept == [1.0, 2.0]


@pytest.mark.parametrize("error,kind", [
    (sc.TransportConnectTimeout("c"), sc.ERROR_KIND_CONNECT_TIMEOUT),
    (sc.TransportReadTimeout("r"), sc.ERROR_KIND_READ_TIMEOUT),
    (sc.TransportConnectionError("x"), sc.ERROR_KIND_CONNECTION_ERROR),
])
def test_transport_errors_are_retryable_and_named(error, kind):
    client, _slept = make_client(
        [error, ok_response("http://dbpedia.org/resource/Carbon")],
        max_attempts=2, jitter_fraction=0.0)
    page = fetch(client)
    assert page.attempts[0].error_kind == kind
    assert page.attempts[0].failure_class == sc.FailureClass.RETRYABLE_FAILURE.value


def test_repeated_timeouts_exhaust_the_budget_and_raise_with_provenance():
    client, slept = make_client(
        [sc.TransportReadTimeout("t1"), sc.TransportReadTimeout("t2"),
         sc.TransportReadTimeout("t3")],
        max_attempts=3, jitter_fraction=0.0)
    with pytest.raises(sc.PageRetrievalFailed) as excinfo:
        fetch(client, class_uri=CLASS_JNL, page_index=0)
    failure = excinfo.value.failure
    assert failure.attempt_count == 3
    assert failure.failure_class == sc.FailureClass.RETRYABLE_FAILURE.value
    assert failure.error_kind == sc.ERROR_KIND_READ_TIMEOUT
    assert failure.class_uri == CLASS_JNL
    assert len(failure.attempts) == 3
    assert slept == [1.0, 2.0]            # no sleep after the final attempt


def test_permanent_4xx_is_not_retried():
    client, slept = make_client([sc.HttpResponse(400, "bad query")], max_attempts=5)
    with pytest.raises(sc.PageRetrievalFailed) as excinfo:
        fetch(client)
    assert excinfo.value.failure.attempt_count == 1
    assert (excinfo.value.failure.failure_class
            == sc.FailureClass.PERMANENT_QUERY_REJECTED.value)
    assert slept == []


def test_malformed_json_on_http_200_is_permanent_and_never_zero_results():
    """The core "do not cache a failure as a valid empty result" case."""
    client, slept = make_client(
        [sc.HttpResponse(200, "<html>oops</html>")], max_attempts=5)
    with pytest.raises(sc.PageRetrievalFailed) as excinfo:
        fetch(client)
    failure = excinfo.value.failure
    assert (failure.failure_class
            == sc.FailureClass.PERMANENT_MALFORMED_RESPONSE.value)
    assert failure.attempt_count == 1
    assert failure.http_status == 200
    assert slept == []


def test_a_genuine_zero_row_page_is_a_success_with_its_own_state():
    client, _ = make_client([sc.HttpResponse(200, ok_body())])
    page = fetch(client, page_size=100)
    assert page.page_state == sc.PageState.PAGE_COMPLETE_ZERO_ROWS.value
    assert page.row_count == 0
    assert page.is_terminal_page
    assert page.cache_origin == sc.CacheOrigin.LIVE_HTTP.value


def test_a_full_page_is_not_terminal_but_a_short_one_is():
    client, _ = make_client([ok_response("http://a/1", "http://a/2")])
    full = fetch(client, page_size=2)
    assert not full.is_terminal_page

    client2, _ = make_client([ok_response("http://a/1")])
    short = fetch(client2, page_size=2)
    assert short.is_terminal_page


def test_http_call_count_tracks_every_attempt():
    client, _ = make_client(
        [sc.HttpResponse(503, "a"), sc.HttpResponse(503, "b"),
         ok_response("http://a/1")], max_attempts=3, jitter_fraction=0.0)
    fetch(client)
    assert client.http_call_count == 3


def test_max_attempts_must_be_at_least_one():
    with pytest.raises(ValueError):
        sc.SparqlPageClient(transport=FakeTransport([]), max_attempts=0)


# --- Strict offline transport ----------------------------------------------

def test_offline_transport_refuses_every_call():
    transport = sc.OfflineTransport()
    with pytest.raises(sc.OfflineNetworkAttemptError):
        transport.post(sc.DBPEDIA_ENDPOINT, "#qid: t\nSELECT 1")
    assert transport.attempt_count == 1


# --- Timestamp discipline --------------------------------------------------

def test_iso_utc_carries_an_explicit_offset():
    assert sc.iso_utc(0.0) == "1970-01-01T00:00:00+00:00"


def test_user_agent_is_descriptive():
    assert "mcq-journal2" in sc.DEFAULT_USER_AGENT
    assert len(sc.DEFAULT_USER_AGENT) > 40


def test_connect_and_read_timeouts_are_separate():
    transport = sc.RequestsHttpTransport()
    assert transport.connect_timeout != transport.read_timeout
    assert transport.connect_timeout > 0 and transport.read_timeout > 0
