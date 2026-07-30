############################################################################
# tests/test_pilot_member_mapping.py
#
# Contract tests for src/classes/page_cache.py, src/classes/member_mapper.py and
# src/classes/mapping_run.py.
#
# What these tests defend:
#   * a member maps to a local node only through explicit, labelled lookup forms
#     (bracketed / bare / percent-decoded / NFC / NFD), never a silent rewrite;
#   * apostrophe-bearing and Unicode URIs map;
#   * dbo:wikiPageRedirects is used ONLY after an exact miss; cycles, malformed
#     targets and unavailable lookups are separate reported states;
#   * two raw members reaching one local index yield ONE candidate;
#   * the Answer is excluded from its own candidate pool;
#   * pagination merges pages without duplication and resumes after interruption;
#   * a failed page is NEVER readable as a successful cache hit;
#   * both offline modes make zero HTTP calls and reproduce the scientific files
#     byte-for-byte;
#   * exactly 27 Answer/class rows and 9 Answer rows are emitted;
#   * the mapping gate boundary is 9 (fails) versus 10 (passes);
#   * an unapproved class can never reach the gate;
#   * a local-KG SHA mismatch is refused.
#
# The 1.2 GB pinned pickle is NOT loaded. A small synthetic KG in the same
# read_ttl 5-tuple shape is built per test, which is what lets the end-to-end run
# assert exact counts.
#
# Offline and deterministic. No test touches the network.
#
# Run:
#     python -m pytest -vv tests/test_pilot_member_mapping.py
############################################################################

from __future__ import annotations

import json
import pathlib
import pickle
import re
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from classes import mapping_run as mr           # noqa: E402
from classes import member_mapper as mm         # noqa: E402
from classes import page_cache as pc            # noqa: E402
from classes import policy as pol               # noqa: E402
from classes import sparql_client as sc         # noqa: E402

R = "http://dbpedia.org/resource/"
C = "http://dbpedia.org/resource/Category:"

ANSWER_TOMONAGA = R + "Shin'ichirō_Tomonaga"
ANSWER_SATO = R + "Eisaku_Satō"
ANSWER_CARBON = R + "Carbon"
CLASS_JNL = C + "Japanese_Nobel_laureates"

POLICY_CSV = REPO_ROOT / "data" / "pilot_class_policy_v1.csv"
POLICY_JSON = REPO_ROOT / "data" / "pilot_class_policy_v1.json"


# ==========================================================================
# Helpers
# ==========================================================================

def url_index_for(uris, start: int = 100) -> dict[str, int]:
    """Bracketed keys, like the pinned pickle produced by src/read_ttl.py."""
    return {f"<{u}>": start + i for i, u in enumerate(uris)}


def lookup_for(uris, start: int = 100):
    return mm.make_local_lookup(url_index_for(uris, start))


def retrieval_of(class_uri: str, members, *, complete: bool = True,
                 page_size: int = 1000, page_count: int = 1) -> mm.ClassRetrieval:
    ordered = tuple(sorted(set(members)))
    return mm.ClassRetrieval(
        class_uri=class_uri,
        member_uris=ordered,
        raw_member_count=len(list(members)),
        page_count=page_count,
        page_size=page_size,
        retrieval_complete=complete,
        incomplete_reason=None if complete else mm.RETRIEVAL_PAGE_FAILED,
    )


class DictRedirectSource:
    """Redirect answers from a dict. `None` value = confirmed no redirect."""

    def __init__(self, mapping, unavailable=()):
        self.mapping = dict(mapping)
        self.unavailable = set(unavailable)
        self.batches: list[tuple[str, ...]] = []

    def redirect_targets(self, source_uris):
        batch = tuple(sorted(set(source_uris)))
        self.batches.append(batch)
        targets = {u: self.mapping[u] for u in batch
                   if self.mapping.get(u) is not None}
        return targets, frozenset(u for u in batch if u in self.unavailable)


def members_body(uris) -> str:
    return json.dumps({
        "head": {"vars": ["member"]},
        "results": {"bindings": [{"member": {"type": "uri", "value": u}}
                                 for u in uris]},
    })


def redirect_body(pairs) -> str:
    return json.dumps({
        "head": {"vars": ["source", "target"]},
        "results": {"bindings": [
            {"source": {"type": "uri", "value": s},
             "target": {"type": "uri", "value": t}} for s, t in pairs]},
    })


_CLASS_RE = re.compile(r"dcterms:subject <([^>]+)>")
_CURSOR_RE = re.compile(r'FILTER\(STR\(\?member\) > "([^"]+)"\)')
_LIMIT_RE = re.compile(r"LIMIT (\d+)")
_VALUES_RE = re.compile(r"VALUES \?source \{ (.*?) \}", re.S)


class ScriptedTransport:
    """Answers members and redirect queries from in-memory data.

    Understands the real query text — class URI, keyset cursor and LIMIT — so
    pagination, page merging and resume are exercised end to end rather than
    stubbed at a higher level.
    """

    def __init__(self, class_members, redirects=None, page_size=None,
                 fail_plan=None):
        self.class_members = {k: tuple(sorted(v)) for k, v in class_members.items()}
        self.redirects = dict(redirects or {})
        self.page_size = page_size
        self.fail_plan = list(fail_plan or [])
        self.member_calls: list[tuple[str, str | None]] = []
        self.redirect_calls: list[tuple[str, ...]] = []
        self.call_count = 0

    def post(self, endpoint: str, query: str) -> sc.HttpResponse:
        self.call_count += 1
        if self.fail_plan:
            planned = self.fail_plan.pop(0)
            if planned is not None:
                if isinstance(planned, Exception):
                    raise planned
                return planned

        if sc.query_id(query) == sc.QID_REDIRECT_BATCH:
            raw = _VALUES_RE.search(query).group(1)
            sources = tuple(re.findall(r"<([^>]+)>", raw))
            self.redirect_calls.append(sources)
            pairs = [(s, self.redirects[s]) for s in sources
                     if self.redirects.get(s) is not None]
            return sc.HttpResponse(200, redirect_body(sorted(pairs)))

        class_uri = _CLASS_RE.search(query).group(1)
        cursor_match = _CURSOR_RE.search(query)
        cursor = cursor_match.group(1) if cursor_match else None
        limit = int(_LIMIT_RE.search(query).group(1))
        self.member_calls.append((class_uri, cursor))

        members = self.class_members.get(class_uri, ())
        if cursor is not None:
            members = tuple(m for m in members if m > cursor)
        return sc.HttpResponse(200, members_body(members[:limit]))


def make_fetcher(tmp_path, transport, **client_kwargs):
    cache = pc.PageCache(tmp_path / "cache.sqlite", endpoint=sc.DBPEDIA_ENDPOINT)
    client = sc.SparqlPageClient(
        transport=transport, sleep=lambda _s: None,
        jitter_fraction=0.0, **client_kwargs)
    fetcher = mm.CachedPageFetcher(
        cache=cache, client=client, endpoint=sc.DBPEDIA_ENDPOINT)
    return cache, client, fetcher


# --- Synthetic pilot world -------------------------------------------------
# Member counts are chosen to exercise every gate outcome and the 9/10 boundary.
#   Japanese_Nobel_laureates            9  -> fails (boundary, one short)
#   21st-century_Japanese_biologists   10  -> passes (boundary, exactly at it)
#   Japanese_theoretical_physicists     9  -> fails
#   Japanese_physicists                15  -> passes
#   20th-century_prime_ministers        3   -> fails
#   Nobel_Peace_Prize_laureates         4   -> fails   (slot 3: all three fail)
#   Reactive_nonmetals                 12 raw, but includes the Answer itself and
#                                      a duplicate, so exactly 10 candidates
#   every other class                  12  -> passes
SPECIAL_CLASS_SIZES = {
    C + "Japanese_Nobel_laureates": 9,
    C + "21st-century_Japanese_biologists": 10,
    C + "Japanese_theoretical_physicists": 9,
    C + "Japanese_physicists": 15,
    C + "20th-century_prime_ministers_of_Japan": 3,
    C + "Nobel_Peace_Prize_laureates": 4,
}
DEFAULT_CLASS_SIZE = 12

# One member of Reactive_nonmetals reaches the local KG only via a redirect, and
# one is a distinct URI that redirects onto an already-mapped node.
REDIRECT_ONLY_MEMBER = R + "Carbon_element_redirect_stub"
REDIRECT_ONLY_TARGET = R + "Carbon_allotrope_target"
DUPLICATE_MEMBER = R + "Reactive_nonmetals_dup_stub"


def build_synthetic_world():
    """(class_members, local_uris, redirects) for the real nine-Answer policy."""
    policy = pol.load_policy_csv(POLICY_CSV)
    classes = sorted({c for row in policy for c in row.ordered_classes})

    class_members: dict[str, list[str]] = {}
    for class_uri in classes:
        slug = class_uri.split("Category:")[-1]
        size = SPECIAL_CLASS_SIZES.get(class_uri, DEFAULT_CLASS_SIZE)
        class_members[class_uri] = [f"{R}{slug}_member_{i:02d}" for i in range(size)]

    reactive = C + "Reactive_nonmetals"
    # 12 generated members -> drop two, add the Answer, a redirect-only member and
    # a duplicate stub, so the class still has 12 raw members but only 10
    # distinct non-Answer local candidates.
    class_members[reactive] = (
        class_members[reactive][:9]
        + [ANSWER_CARBON, REDIRECT_ONLY_MEMBER, DUPLICATE_MEMBER]
    )

    local_uris = [row.answer_uri for row in policy]
    for members in class_members.values():
        for uri in members:
            if uri in (REDIRECT_ONLY_MEMBER, DUPLICATE_MEMBER):
                continue                       # deliberately absent locally
            local_uris.append(uri)
    local_uris.append(REDIRECT_ONLY_TARGET)
    local_uris = sorted(set(local_uris))

    redirects = {
        REDIRECT_ONLY_MEMBER: REDIRECT_ONLY_TARGET,
        # Redirects onto a member of the same class that is already mapped, so the
        # duplicate-local-index path is exercised through a redirect.
        DUPLICATE_MEMBER: class_members[reactive][0],
    }
    return class_members, local_uris, redirects


def write_synthetic_pickle(path: pathlib.Path, local_uris, extra_edges=None):
    """A read_ttl-shaped 5-tuple: (url_index, index_url, out, in, index_type)."""
    url_index = {f"<{u}>": i for i, u in enumerate(sorted(local_uris))}
    index_url = {i: k for k, i in url_index.items()}
    out_neighbor: dict[int, list[tuple[int, int]]] = {}
    in_neighbor: dict[int, list[tuple[int, int]]] = {}
    predicate = 0
    for source, target in (extra_edges or ()):
        s = url_index[f"<{source}>"]
        t = url_index[f"<{target}>"]
        out_neighbor.setdefault(s, []).append((predicate, t))
        in_neighbor.setdefault(t, []).append((predicate, s))
    index_type = {i: 0 for i in index_url}
    path.write_bytes(pickle.dumps(
        (url_index, index_url, out_neighbor, in_neighbor, index_type)))
    return url_index


def build_synthetic_pilot(tmp_path: pathlib.Path):
    """A complete synthetic pilot: pickle on disk plus a scripted transport."""
    class_members, local_uris, redirects = build_synthetic_world()
    kg_path = tmp_path / "synthetic.pickle"
    # A couple of edges so degree profiling has something to report.
    edges = [(ANSWER_CARBON, REDIRECT_ONLY_TARGET),
             (REDIRECT_ONLY_TARGET, ANSWER_TOMONAGA)]
    write_synthetic_pickle(kg_path, local_uris, edges)
    transport = ScriptedTransport(class_members, redirects=redirects)
    from kg.loader import sha256_file
    return kg_path, sha256_file(kg_path), transport, class_members, redirects


def config_for(tmp_path, kg_path, kg_sha, mode, out_name, **overrides):
    return mr.RunConfig(
        mode=mode,
        output_dir=tmp_path / out_name,
        policy_csv=POLICY_CSV,
        policy_json=POLICY_JSON,
        local_kg_path=kg_path,
        expected_local_kg_sha256=kg_sha,
        cache_path=overrides.pop("cache_path", tmp_path / "run_cache.sqlite"),
        frozen_jsonl=overrides.pop("frozen_jsonl", tmp_path / "frozen.jsonl"),
        frozen_manifest=tmp_path / "frozen_manifest.json",
        page_size=overrides.pop("page_size", 5),   # small: forces real pagination
        **overrides,
    )


SCIENTIFIC_FILES = (
    "mapping_summary.csv",
    "selected_mapping_class.csv",
    "mapped_candidates.jsonl",
    "candidate_local_profiles.jsonl",
)


# ==========================================================================
# Exact local mapping and the lookup-form ladder
# ==========================================================================

def test_exact_local_mapping_uses_the_bracketed_key():
    lookup = lookup_for([ANSWER_CARBON])
    result = lookup(ANSWER_CARBON)
    assert result.found
    assert result.local_index == 100
    assert result.lookup_form == sc.LOOKUP_FORM_BRACKETED


def test_bare_key_is_found_and_reported_as_the_bare_form():
    lookup = mm.make_local_lookup({ANSWER_CARBON: 7})
    result = lookup(ANSWER_CARBON)
    assert result.local_index == 7
    assert result.lookup_form == sc.LOOKUP_FORM_BARE


def test_bracketed_wins_when_both_spellings_are_present():
    lookup = mm.make_local_lookup({f"<{ANSWER_CARBON}>": 1, ANSWER_CARBON: 2})
    assert lookup(ANSWER_CARBON).local_index == 1


def test_a_bracketed_input_uri_still_resolves():
    lookup = lookup_for([ANSWER_CARBON])
    assert lookup(f"<{ANSWER_CARBON}>").local_index == 100


def test_apostrophe_bearing_uri_maps():
    lookup = lookup_for([ANSWER_TOMONAGA])
    result = lookup(ANSWER_TOMONAGA)
    assert result.found
    assert result.lookup_form == sc.LOOKUP_FORM_BRACKETED


def test_unicode_uri_maps():
    lookup = lookup_for([ANSWER_SATO])
    assert lookup(ANSWER_SATO).found


def test_percent_encoded_member_reaches_a_raw_utf8_local_key():
    lookup = lookup_for([ANSWER_TOMONAGA])
    encoded = R + "Shin%27ichir%C5%8D_Tomonaga"
    result = lookup(encoded)
    assert result.local_index == 100
    assert result.lookup_form == sc.LOOKUP_FORM_PERCENT_DECODED_BRACKETED


def test_nfd_spelled_local_key_is_reachable_and_labelled():
    """The dump and the endpoint need not agree on Unicode composition."""
    import unicodedata
    nfd = unicodedata.normalize("NFD", ANSWER_SATO)
    lookup = mm.make_local_lookup({f"<{nfd}>": 42})
    result = lookup(ANSWER_SATO)
    assert result.local_index == 42
    assert result.lookup_form == sc.LOOKUP_FORM_NFD_BRACKETED


def test_a_missing_uri_is_data_not_an_exception():
    lookup = lookup_for([ANSWER_CARBON])
    result = lookup(R + "Nonexistent")
    assert not result.found
    assert result.local_index is None
    assert result.lookup_form is None


def test_local_lookup_never_mutates_the_index():
    index = url_index_for([ANSWER_CARBON])
    before = dict(index)
    lookup = mm.make_local_lookup(index)
    lookup(R + "Nonexistent")
    lookup(ANSWER_CARBON)
    assert index == before


# ==========================================================================
# Local KG verification
# ==========================================================================

def test_local_kg_sha_mismatch_is_refused():
    with pytest.raises(mm.LocalKGVerificationError):
        mm.verify_local_kg_sha256("a" * 64, "b" * 64)


def test_matching_local_kg_sha_is_accepted():
    assert mm.verify_local_kg_sha256("a" * 64, "a" * 64) == "a" * 64
    assert mm.verify_local_kg_sha256("a" * 64, None) == "a" * 64


def test_loader_refuses_a_pickle_with_the_wrong_sha(tmp_path):
    from kg.loader import LocalKGFileError, load_local_kg
    path = tmp_path / "kg.pickle"
    write_synthetic_pickle(path, [ANSWER_CARBON, ANSWER_TOMONAGA])
    with pytest.raises(LocalKGFileError) as excinfo:
        load_local_kg(path, verify_sha256="0" * 64)
    assert "SHA-256 mismatch" in str(excinfo.value)


def test_run_refuses_a_local_kg_sha_mismatch(tmp_path):
    from kg.loader import LocalKGFileError
    kg_path, kg_sha, transport, _cm, _r = build_synthetic_pilot(tmp_path)
    config = config_for(tmp_path, kg_path, "0" * 64, mr.MODE_LIVE, "out")
    with pytest.raises(LocalKGFileError):
        mr.run_mapping(config, transport=transport)


# ==========================================================================
# Redirect resolution
# ==========================================================================

def test_redirect_maps_a_member_that_has_no_exact_match():
    stub, target = R + "Stub", R + "Target"
    lookup = lookup_for([target])
    outcomes = mm.resolve_redirect_chains(
        [stub], DictRedirectSource({stub: target}), lookup)
    outcome = outcomes[stub]
    assert outcome.status == mm.REDIRECT_RESOLVED
    assert outcome.local_index == 100
    assert outcome.chain == (target,)


def test_a_two_hop_chain_is_followed():
    a, b, c = R + "A", R + "B", R + "C"
    lookup = lookup_for([c])
    outcomes = mm.resolve_redirect_chains(
        [a], DictRedirectSource({a: b, b: c}), lookup, max_hops=3)
    assert outcomes[a].status == mm.REDIRECT_RESOLVED
    assert outcomes[a].chain == (b, c)


def test_a_redirect_cycle_is_detected_not_followed_forever():
    a, b = R + "A", R + "B"
    lookup = lookup_for([R + "Unrelated"])
    outcomes = mm.resolve_redirect_chains(
        [a], DictRedirectSource({a: b, b: a}), lookup, max_hops=5)
    assert outcomes[a].status == mm.REDIRECT_CYCLE
    assert outcomes[a].chain == (b, a)
    assert outcomes[a].local_index is None


def test_a_self_redirect_is_a_cycle():
    a = R + "A"
    outcomes = mm.resolve_redirect_chains(
        [a], DictRedirectSource({a: a}), lookup_for([R + "X"]), max_hops=3)
    assert outcomes[a].status == mm.REDIRECT_CYCLE


@pytest.mark.parametrize("bad_target", [
    R + "A B", 'http://dbpedia.org/resource/A"B', "not a uri",
])
def test_a_malformed_redirect_target_is_never_interpolated(bad_target):
    a = R + "A"
    outcomes = mm.resolve_redirect_chains(
        [a], DictRedirectSource({a: bad_target}), lookup_for([R + "X"]))
    assert outcomes[a].status == mm.REDIRECT_UNSAFE_TARGET
    assert outcomes[a].local_index is None


def test_no_redirect_found_is_distinct_from_a_failed_lookup():
    a, b = R + "A", R + "B"
    source = DictRedirectSource({a: None, b: None}, unavailable=[b])
    outcomes = mm.resolve_redirect_chains([a, b], source, lookup_for([R + "X"]))
    assert outcomes[a].status == mm.REDIRECT_NONE_FOUND
    assert outcomes[b].status == mm.REDIRECT_LOOKUP_UNAVAILABLE


def test_a_terminated_chain_whose_target_is_absent_says_so():
    a, b = R + "A", R + "B"
    outcomes = mm.resolve_redirect_chains(
        [a], DictRedirectSource({a: b, b: None}), lookup_for([R + "X"]), max_hops=3)
    assert outcomes[a].status == mm.REDIRECT_TARGET_NOT_LOCAL
    assert outcomes[a].chain == (b,)


def test_running_out_of_hops_is_reported_as_our_budget_not_as_the_data():
    a, b, c = R + "A", R + "B", R + "C"
    outcomes = mm.resolve_redirect_chains(
        [a], DictRedirectSource({a: b, b: c}), lookup_for([R + "X"]), max_hops=1)
    assert outcomes[a].status == mm.REDIRECT_HOP_BUDGET_EXHAUSTED
    assert outcomes[a].chain == (b,)


def test_zero_hops_reports_nothing_observed():
    a = R + "A"
    outcomes = mm.resolve_redirect_chains(
        [a], DictRedirectSource({a: R + "B"}), lookup_for([R + "X"]), max_hops=0)
    assert outcomes[a].status == mm.REDIRECT_LOOKUP_UNAVAILABLE
    assert outcomes[a].chain == ()


def test_redirects_are_batched_in_sorted_order():
    """The batch's query text must depend on the SET, not on discovery order."""
    uris = [R + f"M{i}" for i in range(7)]
    source = DictRedirectSource({u: None for u in uris})
    mm.resolve_redirect_chains(list(reversed(uris)), source, lookup_for([R + "X"]))
    assert source.batches[0] == tuple(sorted(uris))


def test_only_members_without_an_exact_match_need_a_redirect():
    present, absent = R + "Present", R + "Absent"
    lookup = lookup_for([present])
    unmatched = mm.collect_unmatched_members(
        {CLASS_JNL: retrieval_of(CLASS_JNL, [present, absent])}, lookup)
    assert unmatched == (absent,)


def test_unmatched_members_are_collected_once_across_classes():
    absent = R + "Absent"
    lookup = lookup_for([R + "Other"])
    retrievals = {
        CLASS_JNL: retrieval_of(CLASS_JNL, [absent]),
        C + "Second": retrieval_of(C + "Second", [absent]),
    }
    assert mm.collect_unmatched_members(retrievals, lookup) == (absent,)


# ==========================================================================
# Per-class mapping
# ==========================================================================

def test_two_raw_members_reaching_one_local_index_yield_one_candidate():
    stub, real = R + "Stub", R + "Real"
    lookup = lookup_for([real])
    retrieval = retrieval_of(CLASS_JNL, [stub, real])
    outcomes = mm.resolve_redirect_chains(
        [stub], DictRedirectSource({stub: real}), lookup)
    result = mm.map_class_members(
        ANSWER_CARBON, CLASS_JNL, "preferred", retrieval, lookup, outcomes)
    assert result.mapped_candidate_count == 1
    assert result.duplicate_dropped_count == 1
    # Both raw URIs are retained; neither is rewritten or discarded.
    assert {m.raw_member_uri for m in result.members} == {stub, real}


def test_the_answer_is_excluded_from_its_own_candidate_pool():
    other = R + "Other"
    lookup = lookup_for([ANSWER_CARBON, other])
    result = mm.map_class_members(
        ANSWER_CARBON, CLASS_JNL, "preferred",
        retrieval_of(CLASS_JNL, [ANSWER_CARBON, other]), lookup, {})
    assert result.answer_excluded_count == 1
    assert result.mapped_candidate_count == 1
    assert result.answer_local_index not in result.local_candidate_indices


def test_an_unresolved_member_is_recorded_with_a_reason_not_dropped():
    absent = R + "Absent"
    lookup = lookup_for([R + "Other"])
    outcomes = mm.resolve_redirect_chains(
        [absent], DictRedirectSource({absent: None}), lookup)
    result = mm.map_class_members(
        ANSWER_CARBON, CLASS_JNL, "preferred",
        retrieval_of(CLASS_JNL, [absent]), lookup, outcomes)
    member = result.members[0]
    assert member.mapping_origin == mm.MAPPING_ORIGIN_UNRESOLVED
    assert member.unresolved_reason == mm.UNRESOLVED_NO_REDIRECT
    assert member.local_index is None
    assert result.unresolved_count == 1


def test_a_member_with_no_frozen_redirect_answer_is_unavailable_not_absent():
    """Silence in the frozen record must not become a claim about DBpedia."""
    absent = R + "Absent"
    lookup = lookup_for([R + "Other"])
    result = mm.map_class_members(
        ANSWER_CARBON, CLASS_JNL, "preferred",
        retrieval_of(CLASS_JNL, [absent]), lookup, {})
    assert (result.members[0].unresolved_reason
            == mm.UNRESOLVED_REDIRECT_LOOKUP_UNAVAILABLE)


def test_origins_are_counted_separately():
    exact, stub, target, absent = R + "E", R + "S", R + "T", R + "A"
    lookup = lookup_for([exact, target])
    outcomes = mm.resolve_redirect_chains(
        [stub, absent], DictRedirectSource({stub: target, absent: None}), lookup)
    result = mm.map_class_members(
        ANSWER_CARBON, CLASS_JNL, "preferred",
        retrieval_of(CLASS_JNL, [exact, stub, absent]), lookup, outcomes)
    assert (result.exact_mapped_count, result.redirect_mapped_count,
            result.unresolved_count) == (1, 1, 1)
    assert result.mapped_candidate_count == 2


def test_candidate_indices_are_sorted_and_deduplicated():
    uris = [R + f"M{i}" for i in range(5)]
    lookup = lookup_for(uris)
    result = mm.map_class_members(
        ANSWER_CARBON, CLASS_JNL, "preferred",
        retrieval_of(CLASS_JNL, list(reversed(uris))), lookup, {})
    indices = result.local_candidate_indices
    assert list(indices) == sorted(indices)
    assert len(set(indices)) == len(indices)


def test_mapping_is_deterministic_across_input_orders():
    uris = [R + f"M{i}" for i in range(6)]
    lookup = lookup_for(uris)
    a = mm.map_class_members(ANSWER_CARBON, CLASS_JNL, "preferred",
                             retrieval_of(CLASS_JNL, uris), lookup, {})
    b = mm.map_class_members(ANSWER_CARBON, CLASS_JNL, "preferred",
                             retrieval_of(CLASS_JNL, list(reversed(uris))),
                             lookup, {})
    assert [m.as_record() for m in a.members] == [m.as_record() for m in b.members]
    assert a.local_candidate_indices == b.local_candidate_indices


def test_a_literal_member_is_reported_as_not_an_iri():
    lookup = lookup_for([R + "X"])
    retrieval = mm.ClassRetrieval(
        class_uri=CLASS_JNL, member_uris=("just a literal",), raw_member_count=1,
        page_count=1, page_size=10, retrieval_complete=True, incomplete_reason=None)
    result = mm.map_class_members(
        ANSWER_CARBON, CLASS_JNL, "preferred", retrieval, lookup, {})
    assert result.members[0].unresolved_reason == mm.UNRESOLVED_NOT_AN_IRI


# ==========================================================================
# The mapping gate
# ==========================================================================

def _result_with(count: int, class_uri: str, position: str) -> mm.ClassMappingResult:
    uris = [R + f"{class_uri[-6:]}_{i}" for i in range(count)]
    lookup = lookup_for(uris)
    return mm.map_class_members(ANSWER_CARBON, class_uri, position,
                                retrieval_of(class_uri, uris), lookup, {})


def test_gate_boundary_nine_fails_and_ten_passes():
    assert not _result_with(9, CLASS_JNL, "preferred").passes_mapping_gate
    assert _result_with(10, CLASS_JNL, "preferred").passes_mapping_gate
    assert mm.MIN_MAPPED_LOCAL_CANDIDATES == 10


def test_gate_counts_exclude_the_answer():
    """9 candidates plus the Answer is still 9, so the gate must fail."""
    uris = [R + f"M{i}" for i in range(9)]
    lookup = lookup_for(uris + [ANSWER_CARBON])
    result = mm.map_class_members(
        ANSWER_CARBON, CLASS_JNL, "preferred",
        retrieval_of(CLASS_JNL, uris + [ANSWER_CARBON]), lookup, {})
    assert result.mapped_candidate_count == 9
    assert not result.passes_mapping_gate


@pytest.mark.parametrize("counts,expected_status,expected_position", [
    ((12, 12, 12), mm.MAPPING_SELECTED_PREFERRED, pol.POSITION_PREFERRED),
    ((9, 12, 12), mm.MAPPING_SELECTED_FALLBACK_1, pol.POSITION_FALLBACK_1),
    ((9, 9, 12), mm.MAPPING_SELECTED_FALLBACK_2, pol.POSITION_FALLBACK_2),
    ((9, 9, 9), mm.NO_MAPPING_FEASIBLE_APPROVED_CLASS, None),
    ((0, 0, 0), mm.NO_MAPPING_FEASIBLE_APPROVED_CLASS, None),
])
def test_the_walk_respects_preferred_then_fallback_order(
        counts, expected_status, expected_position):
    row = pol.load_policy_csv(POLICY_CSV).by_slot(1)
    per_class = [
        _result_with(count, class_uri, position)
        for count, (position, class_uri) in zip(counts, row.ordered_positions)
    ]
    outcome = mm.select_mapping_class_for_answer(row, per_class)
    assert outcome.status == expected_status
    assert outcome.selected_position == expected_position


def test_the_first_passing_class_wins_even_when_a_later_one_is_larger():
    row = pol.load_policy_csv(POLICY_CSV).by_slot(1)
    per_class = [
        _result_with(count, class_uri, position)
        for count, (position, class_uri) in zip((10, 500, 500),
                                                row.ordered_positions)
    ]
    outcome = mm.select_mapping_class_for_answer(row, per_class)
    assert outcome.selected_position == pol.POSITION_PREFERRED
    assert outcome.selected_class_uri == row.preferred_class


def test_all_three_classes_are_reported_even_after_one_passes():
    row = pol.load_policy_csv(POLICY_CSV).by_slot(1)
    per_class = [
        _result_with(12, class_uri, position)
        for position, class_uri in row.ordered_positions
    ]
    outcome = mm.select_mapping_class_for_answer(row, per_class)
    assert len(outcome.per_class) == 3
    assert len(outcome.as_record()["attempts"]) == 3


def test_an_unapproved_class_cannot_reach_the_gate():
    row = pol.load_policy_csv(POLICY_CSV).by_slot(1)
    per_class = [
        _result_with(12, class_uri, position)
        for position, class_uri in row.ordered_positions
    ]
    per_class[1] = _result_with(500, C + "Totally_unapproved_class",
                                pol.POSITION_FALLBACK_1)
    with pytest.raises(pol.UnapprovedClassError):
        mm.select_mapping_class_for_answer(row, per_class)


def test_the_gate_cannot_be_evaluated_before_all_three_classes_are_mapped():
    row = pol.load_policy_csv(POLICY_CSV).by_slot(1)
    per_class = [_result_with(12, row.preferred_class, pol.POSITION_PREFERRED)]
    with pytest.raises(mm.MemberMapperError):
        mm.select_mapping_class_for_answer(row, per_class)


def test_the_gate_verdict_is_never_described_as_graph_feasibility():
    row = pol.load_policy_csv(POLICY_CSV).by_slot(1)
    per_class = [
        _result_with(12, class_uri, position)
        for position, class_uri in row.ordered_positions
    ]
    note = mm.select_mapping_class_for_answer(row, per_class).as_record()["note"]
    assert "not graph-budget feasibility" in note


# ==========================================================================
# Pagination, resume and the cache
# ==========================================================================

def test_pages_are_merged_without_duplicates(tmp_path):
    members = [R + f"M{i:03d}" for i in range(12)]
    transport = ScriptedTransport({CLASS_JNL: members})
    _cache, _client, fetcher = make_fetcher(tmp_path, transport)
    retrieval = mm.ClassMemberRetriever(
        fetcher=fetcher, page_size=5, max_pages=10).retrieve(CLASS_JNL)
    assert retrieval.retrieval_complete
    assert retrieval.page_count == 3                # 5 + 5 + 2
    assert retrieval.member_uris == tuple(sorted(members))
    assert retrieval.unique_member_count == 12
    assert retrieval.raw_member_count == 12
    assert len(set(retrieval.member_uris)) == 12


def test_the_cursor_chain_is_the_last_member_of_each_page(tmp_path):
    members = [R + f"M{i:03d}" for i in range(7)]
    transport = ScriptedTransport({CLASS_JNL: members})
    _c, _cl, fetcher = make_fetcher(tmp_path, transport)
    mm.ClassMemberRetriever(fetcher=fetcher, page_size=3).retrieve(CLASS_JNL)
    cursors = [cursor for _class_uri, cursor in transport.member_calls]
    assert cursors == [None, sorted(members)[2], sorted(members)[5]]


def test_an_exactly_full_final_page_triggers_one_more_zero_row_page(tmp_path):
    """Guessing that a full page is the last one could silently drop members."""
    members = [R + f"M{i}" for i in range(4)]
    transport = ScriptedTransport({CLASS_JNL: members})
    _c, _cl, fetcher = make_fetcher(tmp_path, transport)
    retrieval = mm.ClassMemberRetriever(
        fetcher=fetcher, page_size=2).retrieve(CLASS_JNL)
    assert retrieval.page_count == 3
    assert retrieval.pages[-1].row_count == 0
    assert (retrieval.pages[-1].page_state
            == sc.PageState.PAGE_COMPLETE_ZERO_ROWS.value)
    assert retrieval.retrieval_complete
    assert retrieval.unique_member_count == 4


def test_an_empty_class_is_a_complete_retrieval_of_zero_members(tmp_path):
    transport = ScriptedTransport({CLASS_JNL: []})
    _c, _cl, fetcher = make_fetcher(tmp_path, transport)
    retrieval = mm.ClassMemberRetriever(
        fetcher=fetcher, page_size=5).retrieve(CLASS_JNL)
    assert retrieval.retrieval_complete
    assert retrieval.unique_member_count == 0
    assert retrieval.incomplete_reason is None


def test_the_page_budget_is_reported_rather_than_silently_truncating(tmp_path):
    members = [R + f"M{i:03d}" for i in range(50)]
    transport = ScriptedTransport({CLASS_JNL: members})
    _c, _cl, fetcher = make_fetcher(tmp_path, transport)
    retrieval = mm.ClassMemberRetriever(
        fetcher=fetcher, page_size=5, max_pages=2).retrieve(CLASS_JNL)
    assert not retrieval.retrieval_complete
    assert retrieval.incomplete_reason == mm.RETRIEVAL_PAGE_BUDGET_EXHAUSTED
    assert retrieval.unique_member_count == 10


def test_retryable_statuses_recover_inside_the_pagination_loop(tmp_path):
    members = [R + f"M{i}" for i in range(3)]
    transport = ScriptedTransport(
        {CLASS_JNL: members},
        fail_plan=[sc.HttpResponse(429, "slow"), sc.HttpResponse(502, "bad"),
                   sc.HttpResponse(503, "down"), None])
    _c, _cl, fetcher = make_fetcher(tmp_path, transport, max_attempts=4)
    retrieval = mm.ClassMemberRetriever(
        fetcher=fetcher, page_size=5).retrieve(CLASS_JNL)
    assert retrieval.retrieval_complete
    assert retrieval.unique_member_count == 3
    assert transport.call_count == 4


def test_a_timeout_ends_the_retrieval_as_incomplete_and_keeps_earlier_pages(tmp_path):
    members = [R + f"M{i:03d}" for i in range(10)]
    transport = ScriptedTransport(
        {CLASS_JNL: members},
        fail_plan=[None, sc.TransportReadTimeout("t"), sc.TransportReadTimeout("t"),
                   sc.TransportReadTimeout("t")])
    cache, _cl, fetcher = make_fetcher(tmp_path, transport, max_attempts=3)
    retrieval = mm.ClassMemberRetriever(
        fetcher=fetcher, page_size=5).retrieve(CLASS_JNL)
    assert not retrieval.retrieval_complete
    assert retrieval.incomplete_reason == mm.RETRIEVAL_PAGE_FAILED
    assert retrieval.page_count == 1                 # the first page survived
    assert retrieval.unique_member_count == 5
    assert cache.page_count() == 1                   # and was cached
    assert cache.stored_failure_count() == 1


def test_malformed_json_ends_the_retrieval_and_is_not_cached_as_a_result(tmp_path):
    transport = ScriptedTransport(
        {CLASS_JNL: [R + "M1"]},
        fail_plan=[sc.HttpResponse(200, "<html>nope</html>")])
    cache, _cl, fetcher = make_fetcher(tmp_path, transport, max_attempts=3)
    retrieval = mm.ClassMemberRetriever(
        fetcher=fetcher, page_size=5).retrieve(CLASS_JNL)
    assert not retrieval.retrieval_complete
    assert retrieval.unique_member_count == 0
    assert cache.page_count() == 0                   # nothing stored
    assert cache.stored_failure_count() == 1
    assert (retrieval.failures[0].failure_class
            == sc.FailureClass.PERMANENT_MALFORMED_RESPONSE.value)


def test_a_failed_page_is_not_readable_as_a_cache_hit(tmp_path):
    """The whole point of separate `pages` and `failures` tables."""
    transport = ScriptedTransport(
        {CLASS_JNL: [R + "M1"]}, fail_plan=[sc.HttpResponse(400, "bad")])
    cache, _cl, fetcher = make_fetcher(tmp_path, transport, max_attempts=1)
    mm.ClassMemberRetriever(fetcher=fetcher, page_size=5).retrieve(CLASS_JNL)
    query = sc.build_class_members_page_query(CLASS_JNL, page_size=5)
    fingerprint = sc.query_fingerprint(sc.DBPEDIA_ENDPOINT, query)
    assert cache.get_page(fingerprint) is None
    assert cache.stored_failure_count() == 1


def test_interruption_then_resume_refetches_only_the_missing_page(tmp_path):
    """Resume needs no bookmark: the query text IS the position."""
    members = [R + f"M{i:03d}" for i in range(10)]
    cache_path = tmp_path / "resume.sqlite"

    interrupted = ScriptedTransport(
        {CLASS_JNL: members},
        fail_plan=[None, sc.TransportReadTimeout("t")])
    cache = pc.PageCache(cache_path, endpoint=sc.DBPEDIA_ENDPOINT)
    fetcher = mm.CachedPageFetcher(
        cache=cache,
        client=sc.SparqlPageClient(transport=interrupted, sleep=lambda _s: None,
                                   max_attempts=1),
        endpoint=sc.DBPEDIA_ENDPOINT)
    first = mm.ClassMemberRetriever(fetcher=fetcher, page_size=5).retrieve(CLASS_JNL)
    assert not first.retrieval_complete
    assert interrupted.call_count == 2
    cache.close()

    resumed = ScriptedTransport({CLASS_JNL: members})
    cache2 = pc.PageCache(cache_path, endpoint=sc.DBPEDIA_ENDPOINT)
    fetcher2 = mm.CachedPageFetcher(
        cache=cache2,
        client=sc.SparqlPageClient(transport=resumed, sleep=lambda _s: None),
        endpoint=sc.DBPEDIA_ENDPOINT)
    second = mm.ClassMemberRetriever(fetcher=fetcher2, page_size=5).retrieve(CLASS_JNL)

    assert second.retrieval_complete
    assert second.member_uris == tuple(sorted(members))
    assert fetcher2.cache_hit_count == 1             # page 0 came from the cache
    assert resumed.call_count == 2                   # only pages 1 and 2 refetched
    assert second.pages[0].cache_origin == sc.CacheOrigin.CACHE_HIT.value
    cache2.close()


def test_a_second_identical_run_makes_no_network_call_at_all(tmp_path):
    members = [R + f"M{i:03d}" for i in range(7)]
    cache_path = tmp_path / "warm.sqlite"
    for expected_network in (3, 0):
        transport = ScriptedTransport({CLASS_JNL: members})
        cache = pc.PageCache(cache_path, endpoint=sc.DBPEDIA_ENDPOINT)
        fetcher = mm.CachedPageFetcher(
            cache=cache,
            client=sc.SparqlPageClient(transport=transport, sleep=lambda _s: None),
            endpoint=sc.DBPEDIA_ENDPOINT)
        mm.ClassMemberRetriever(fetcher=fetcher, page_size=3).retrieve(CLASS_JNL)
        assert fetcher.network_page_count == expected_network
        cache.close()


def test_strict_offline_raises_on_a_cache_miss_instead_of_calling_out(tmp_path):
    cache = pc.PageCache(tmp_path / "empty.sqlite", endpoint=sc.DBPEDIA_ENDPOINT)
    fetcher = mm.CachedPageFetcher(
        cache=cache, client=None, endpoint=sc.DBPEDIA_ENDPOINT)
    assert fetcher.offline
    with pytest.raises(mm.OfflineCacheMissError):
        mm.ClassMemberRetriever(fetcher=fetcher).retrieve(CLASS_JNL)
    assert fetcher.network_page_count == 0


def test_the_cache_refuses_to_store_a_non_success_state(tmp_path):
    cache = pc.PageCache(tmp_path / "c.sqlite", endpoint=sc.DBPEDIA_ENDPOINT)
    page = sc.PageResult(
        query_kind="k", query_fingerprint="f", query_text="q",
        endpoint=sc.DBPEDIA_ENDPOINT, class_uri=None, page_index=0,
        cursor_after=None, page_size=5, page_state="RETRYABLE_FAILURE",
        http_status=503, rows=(), attempt_count=1, attempts=(),
        cache_origin=sc.CacheOrigin.LIVE_HTTP.value,
        retrieved_at_epoch=0.0, retrieved_at_iso="1970-01-01T00:00:00+00:00")
    with pytest.raises(pc.PageCacheError):
        cache.put_page(page)


def test_the_cache_refuses_a_database_written_by_another_schema(tmp_path):
    import sqlite3
    path = tmp_path / "foreign.sqlite"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE responses (query_hash TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()
    with pytest.raises(pc.CacheSchemaMismatch):
        pc.PageCache(path).page_count()


def test_the_cache_refuses_a_mismatched_schema_version(tmp_path):
    path = tmp_path / "old.sqlite"
    pc.PageCache(path, schema_version="something_else").page_count()
    with pytest.raises(pc.CacheSchemaMismatch):
        pc.PageCache(path, schema_version=pc.CACHE_SCHEMA_VERSION).page_count()


def test_only_unique_classes_are_retrieved(tmp_path):
    """Japanese_Nobel_laureates is preferred for three Answers: one retrieval."""
    transport = ScriptedTransport({CLASS_JNL: [R + "M1"]})
    _c, _cl, fetcher = make_fetcher(tmp_path, transport)
    retriever = mm.ClassMemberRetriever(fetcher=fetcher, page_size=5)
    retrievals = mm.retrieve_all_classes([CLASS_JNL, CLASS_JNL, CLASS_JNL], retriever)
    assert list(retrievals) == [CLASS_JNL]
    assert transport.call_count == 1


# ==========================================================================
# Frozen export
# ==========================================================================

def test_frozen_export_round_trips(tmp_path):
    path = tmp_path / "frozen.jsonl"
    pc.write_frozen_export(
        path,
        [pc.FrozenClassMembers(class_uri=CLASS_JNL, member_uris=(R + "A", R + "B"),
                               page_count=1, page_size=5, retrieval_complete=True,
                               raw_member_count=2)],
        [pc.FrozenRedirect(source_uri=R + "S", target_uri=R + "T"),
         pc.FrozenRedirect(source_uri=R + "U", target_uri=None)])
    export = pc.load_frozen_export(path)
    assert export.members_for(CLASS_JNL).member_uris == (R + "A", R + "B")
    assert export.members_for(CLASS_JNL).raw_member_count == 2
    assert export.redirects[R + "S"] == R + "T"
    assert export.redirects[R + "U"] is None
    assert R + "U" in export.queried_redirect_sources


def test_frozen_export_is_written_in_a_deterministic_order(tmp_path):
    records = [
        pc.FrozenClassMembers(class_uri=C + "B", member_uris=(R + "1",),
                              page_count=1, page_size=5, retrieval_complete=True),
        pc.FrozenClassMembers(class_uri=C + "A", member_uris=(R + "2",),
                              page_count=1, page_size=5, retrieval_complete=True),
    ]
    redirects = [pc.FrozenRedirect(R + "Z", None), pc.FrozenRedirect(R + "A", None)]
    a = pc.write_frozen_export(tmp_path / "a.jsonl", records, redirects)
    b = pc.write_frozen_export(
        tmp_path / "b.jsonl", list(reversed(records)), list(reversed(redirects)))
    assert a.read_bytes() == b.read_bytes()


def test_frozen_export_contains_no_timestamp(tmp_path):
    path = pc.write_frozen_export(
        tmp_path / "f.jsonl",
        [pc.FrozenClassMembers(CLASS_JNL, (R + "A",), 1, 5, True)],
        [pc.FrozenRedirect(R + "S", R + "T")])
    text = path.read_text(encoding="utf-8")
    for token in ("retrieved_at", "observed_at", "timestamp", "epoch", "iso"):
        assert token not in text


def test_frozen_export_preserves_unicode_readably(tmp_path):
    path = pc.write_frozen_export(
        tmp_path / "f.jsonl",
        [pc.FrozenClassMembers(CLASS_JNL, (ANSWER_TOMONAGA, ANSWER_SATO), 1, 5, True)],
        [])
    assert "Shin'ichirō_Tomonaga" in path.read_text(encoding="utf-8")
    export = pc.load_frozen_export(path)
    assert ANSWER_TOMONAGA in export.members_for(CLASS_JNL).member_uris


@pytest.mark.parametrize("line", [
    "not json",
    json.dumps({"record_type": "unknown"}),
    json.dumps({"record_type": "class_members"}),
    json.dumps({"record_type": "redirect"}),
])
def test_a_malformed_frozen_export_is_refused(tmp_path, line):
    path = tmp_path / "bad.jsonl"
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(pc.FrozenExportError):
        pc.load_frozen_export(path)


def test_contradictory_redirect_records_are_refused(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text(
        json.dumps({"record_type": "redirect", "source_uri": R + "S",
                    "target_uri": R + "T1"}) + "\n"
        + json.dumps({"record_type": "redirect", "source_uri": R + "S",
                      "target_uri": R + "T2"}) + "\n",
        encoding="utf-8")
    with pytest.raises(pc.FrozenExportError):
        pc.load_frozen_export(path)


def test_a_missing_class_in_the_frozen_export_is_an_error(tmp_path):
    path = pc.write_frozen_export(tmp_path / "f.jsonl", [], [])
    export = pc.load_frozen_export(path)
    with pytest.raises(pc.FrozenExportError):
        export.members_for(CLASS_JNL)


def test_a_never_queried_redirect_source_replays_as_unavailable(tmp_path):
    path = pc.write_frozen_export(tmp_path / "f.jsonl", [], [])
    source = mm.FrozenRedirectSource(export=pc.load_frozen_export(path))
    targets, unavailable = source.redirect_targets([R + "S"])
    assert targets == {}
    assert unavailable == frozenset({R + "S"})


def test_a_frozen_cycle_replays_as_a_cycle(tmp_path):
    a, b = R + "A", R + "B"
    path = pc.write_frozen_export(
        tmp_path / "f.jsonl", [],
        [pc.FrozenRedirect(a, b), pc.FrozenRedirect(b, a)])
    source = mm.FrozenRedirectSource(export=pc.load_frozen_export(path))
    outcomes = mm.resolve_redirect_chains([a], source, lookup_for([R + "X"]),
                                          max_hops=5)
    assert outcomes[a].status == mm.REDIRECT_CYCLE


def test_redirect_records_export_every_hop_of_a_chain():
    a, b, c = R + "A", R + "B", R + "C"
    outcomes = mm.resolve_redirect_chains(
        [a], DictRedirectSource({a: b, b: c}), lookup_for([c]), max_hops=3)
    records = {r.source_uri: r.target_uri for r in mm.frozen_redirect_records(outcomes)}
    assert records == {a: b, b: c}


def test_an_unavailable_redirect_lookup_is_not_exported_as_an_absence():
    a = R + "A"
    outcomes = mm.resolve_redirect_chains(
        [a], DictRedirectSource({a: None}, unavailable=[a]), lookup_for([R + "X"]))
    assert mm.frozen_redirect_records(outcomes) == ()


# ==========================================================================
# Policy agreement
# ==========================================================================

def test_the_csv_and_json_approved_policies_agree():
    csv_policy = pol.load_policy_csv(POLICY_CSV)
    json_policy = pol.load_policy_json(POLICY_JSON)
    pol.assert_policies_agree(csv_policy, json_policy)
    assert len(csv_policy) == 9


def test_the_approved_policy_holds_exactly_23_unique_classes():
    policy = pol.load_policy_csv(POLICY_CSV)
    classes = {c for row in policy for c in row.ordered_classes}
    assert len(classes) == 23                     # 27 rows, 4 shared classes
    assert sum(len(row.ordered_classes) for row in policy) == 27


# ==========================================================================
# End-to-end runs
# ==========================================================================

def test_a_live_run_produces_every_required_output(tmp_path):
    kg_path, kg_sha, transport, _cm, _r = build_synthetic_pilot(tmp_path)
    result = mr.run_mapping(
        config_for(tmp_path, kg_path, kg_sha, mr.MODE_LIVE, "live"),
        transport=transport)
    assert result.verdict == mr.VERDICT_COMPLETE
    for name in SCIENTIFIC_FILES + ("query_log.jsonl", "cache_inventory.json",
                                    "run_manifest.json"):
        assert (result.config.output_dir / name).is_file(), name


def test_mapping_summary_has_exactly_27_rows_in_pilot_and_class_order(tmp_path):
    import csv as csvmod
    kg_path, kg_sha, transport, _cm, _r = build_synthetic_pilot(tmp_path)
    result = mr.run_mapping(
        config_for(tmp_path, kg_path, kg_sha, mr.MODE_LIVE, "live"),
        transport=transport)
    rows = list(csvmod.DictReader(
        (result.config.output_dir / "mapping_summary.csv").open(encoding="utf-8")))
    assert len(rows) == 27
    assert [int(r["pilot_slot"]) for r in rows] == [
        slot for slot in range(1, 10) for _ in range(3)]
    assert [r["class_position"] for r in rows] == list(pol.CLASS_POSITIONS) * 9
    policy = pol.load_policy_csv(POLICY_CSV)
    for row, (answer, position, class_uri) in zip(rows, [
            (a.answer_uri, p, c) for a in policy for p, c in a.ordered_positions]):
        assert row["answer_uri"] == answer
        assert row["class_position"] == position
        assert row["class_uri"] == class_uri


def test_selected_mapping_class_has_exactly_9_rows(tmp_path):
    import csv as csvmod
    kg_path, kg_sha, transport, _cm, _r = build_synthetic_pilot(tmp_path)
    result = mr.run_mapping(
        config_for(tmp_path, kg_path, kg_sha, mr.MODE_LIVE, "live"),
        transport=transport)
    rows = list(csvmod.DictReader(
        (result.config.output_dir / "selected_mapping_class.csv")
        .open(encoding="utf-8")))
    assert len(rows) == 9
    assert [int(r["pilot_slot"]) for r in rows] == list(range(1, 10))
    assert all(r["mapping_stage_status"] for r in rows)


def test_every_answer_gets_an_explicit_mapping_stage_outcome(tmp_path):
    kg_path, kg_sha, transport, _cm, _r = build_synthetic_pilot(tmp_path)
    result = mr.run_mapping(
        config_for(tmp_path, kg_path, kg_sha, mr.MODE_LIVE, "live"),
        transport=transport)
    statuses = {o.pilot_slot: o.status for o in result.outcomes}
    assert len(statuses) == 9
    allowed = {mm.MAPPING_SELECTED_PREFERRED, mm.MAPPING_SELECTED_FALLBACK_1,
               mm.MAPPING_SELECTED_FALLBACK_2,
               mm.NO_MAPPING_FEASIBLE_APPROVED_CLASS}
    assert set(statuses.values()) <= allowed
    # The synthetic sizes were chosen to produce one of each interesting outcome.
    assert statuses[1] == mm.MAPPING_SELECTED_FALLBACK_1     # JNL 9 -> biologists 10
    assert statuses[2] == mm.MAPPING_SELECTED_FALLBACK_2     # 9, 9 -> physicists 15
    assert statuses[3] == mm.NO_MAPPING_FEASIBLE_APPROVED_CLASS   # 9, 3, 4
    assert statuses[4] == mm.MAPPING_SELECTED_PREFERRED


def test_the_answer_and_a_duplicate_are_both_excluded_end_to_end(tmp_path):
    kg_path, kg_sha, transport, _cm, _r = build_synthetic_pilot(tmp_path)
    result = mr.run_mapping(
        config_for(tmp_path, kg_path, kg_sha, mr.MODE_LIVE, "live"),
        transport=transport)
    carbon = next(o for o in result.outcomes if o.answer_uri == ANSWER_CARBON)
    preferred = carbon.result_for_position(pol.POSITION_PREFERRED)
    assert preferred.retrieval.unique_member_count == 12
    assert preferred.answer_excluded_count == 1        # Carbon itself
    assert preferred.redirect_mapped_count == 2        # both stubs redirect
    assert preferred.duplicate_dropped_count == 1      # one lands on a mapped node
    assert preferred.mapped_candidate_count == 10      # exactly at the gate
    assert preferred.passes_mapping_gate


def test_raw_member_uris_are_preserved_verbatim(tmp_path):
    kg_path, kg_sha, transport, _cm, _r = build_synthetic_pilot(tmp_path)
    result = mr.run_mapping(
        config_for(tmp_path, kg_path, kg_sha, mr.MODE_LIVE, "live"),
        transport=transport)
    records = [json.loads(line) for line in
               (result.config.output_dir / "mapped_candidates.jsonl")
               .read_text(encoding="utf-8").splitlines()]
    stub = [r for r in records if r["raw_member_uri"] == REDIRECT_ONLY_MEMBER]
    assert stub, "the redirect-only member must appear under its RAW uri"
    assert stub[0]["mapping_origin"] == mm.MAPPING_ORIGIN_REDIRECT
    assert stub[0]["redirect_target_uri"] == REDIRECT_ONLY_TARGET


def test_the_manifest_carries_every_required_provenance_field(tmp_path):
    kg_path, kg_sha, transport, _cm, _r = build_synthetic_pilot(tmp_path)
    result = mr.run_mapping(
        config_for(tmp_path, kg_path, kg_sha, mr.MODE_LIVE, "live"),
        transport=transport)
    manifest = json.loads(
        (result.config.output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["endpoint"] == sc.DBPEDIA_ENDPOINT
    assert manifest["retrieval_started_at_iso_utc"].endswith("+00:00")
    assert manifest["inputs"]["policy_csv_sha256"]
    assert manifest["inputs"]["policy_json_sha256"]
    assert manifest["inputs"]["local_kg_sha256"] == kg_sha
    assert manifest["inputs"]["local_kg_sha256_verified"] is True
    assert manifest["counts"]["unique_approved_class_count"] == 23
    assert manifest["counts"]["answer_class_row_count"] == 27
    assert manifest["counts"]["query_page_count"] > 0
    assert manifest["counts"]["failed_page_count"] == 0
    assert manifest["counts"]["raw_member_count"] > 0
    assert manifest["counts"]["unique_member_count"] > 0
    assert manifest["counts"]["exact_local_mappings"] > 0
    assert manifest["counts"]["redirect_local_mappings"] == 2
    assert "unresolved_count" in manifest["counts"]
    assert manifest["parameters"]["owl_sameAs_used"] is False
    assert "source_code_commit_at_run" in manifest
    assert manifest["source_file_sha256"]["src/classes/member_mapper.py"]


def test_a_live_run_writes_the_frozen_export_and_its_manifest(tmp_path):
    kg_path, kg_sha, transport, _cm, _r = build_synthetic_pilot(tmp_path)
    config = config_for(tmp_path, kg_path, kg_sha, mr.MODE_LIVE, "live")
    mr.run_mapping(config, transport=transport)
    assert config.frozen_jsonl.is_file()
    assert config.frozen_manifest.is_file()
    export = pc.load_frozen_export(config.frozen_jsonl)
    assert export.class_count == 23


def test_offline_cache_replay_makes_zero_http_calls_and_matches_the_live_run(tmp_path):
    kg_path, kg_sha, transport, _cm, _r = build_synthetic_pilot(tmp_path)
    live = mr.run_mapping(
        config_for(tmp_path, kg_path, kg_sha, mr.MODE_LIVE, "live"),
        transport=transport)
    calls_after_live = transport.call_count

    replay = mr.run_mapping(config_for(
        tmp_path, kg_path, kg_sha, mr.MODE_OFFLINE_CACHE, "replay_cache"))

    assert replay.network_page_count == 0
    assert replay.manifest["network"]["http_calls"] == 0
    assert replay.manifest["network"]["transport_present"] is False
    assert transport.call_count == calls_after_live      # nothing new was requested
    for name in SCIENTIFIC_FILES:
        assert ((live.config.output_dir / name).read_bytes()
                == (replay.config.output_dir / name).read_bytes()), name


def test_offline_frozen_replay_makes_zero_http_calls_and_matches_too(tmp_path):
    kg_path, kg_sha, transport, _cm, _r = build_synthetic_pilot(tmp_path)
    live = mr.run_mapping(
        config_for(tmp_path, kg_path, kg_sha, mr.MODE_LIVE, "live"),
        transport=transport)
    calls_after_live = transport.call_count

    replay = mr.run_mapping(config_for(
        tmp_path, kg_path, kg_sha, mr.MODE_OFFLINE_FROZEN, "replay_frozen"))

    assert replay.network_page_count == 0
    assert replay.manifest["network"]["http_calls"] == 0
    assert transport.call_count == calls_after_live
    for name in SCIENTIFIC_FILES:
        assert ((live.config.output_dir / name).read_bytes()
                == (replay.config.output_dir / name).read_bytes()), name


def test_the_two_offline_modes_agree_with_each_other(tmp_path):
    kg_path, kg_sha, transport, _cm, _r = build_synthetic_pilot(tmp_path)
    mr.run_mapping(config_for(tmp_path, kg_path, kg_sha, mr.MODE_LIVE, "live"),
                   transport=transport)
    from_cache = mr.run_mapping(config_for(
        tmp_path, kg_path, kg_sha, mr.MODE_OFFLINE_CACHE, "a"))
    from_frozen = mr.run_mapping(config_for(
        tmp_path, kg_path, kg_sha, mr.MODE_OFFLINE_FROZEN, "b"))
    for name in SCIENTIFIC_FILES:
        assert ((from_cache.config.output_dir / name).read_bytes()
                == (from_frozen.config.output_dir / name).read_bytes()), name


def test_an_offline_run_without_a_cache_fails_loudly(tmp_path):
    kg_path, kg_sha, _t, _cm, _r = build_synthetic_pilot(tmp_path)
    with pytest.raises(mm.OfflineCacheMissError):
        mr.run_mapping(config_for(
            tmp_path, kg_path, kg_sha, mr.MODE_OFFLINE_CACHE, "cold"))


def test_an_unknown_mode_is_refused(tmp_path):
    kg_path, kg_sha, _t, _cm, _r = build_synthetic_pilot(tmp_path)
    with pytest.raises(mr.MappingRunError):
        mr.run_mapping(config_for(tmp_path, kg_path, kg_sha, "guess", "x"))


def test_no_unapproved_class_appears_in_any_output(tmp_path):
    import csv as csvmod
    kg_path, kg_sha, transport, _cm, _r = build_synthetic_pilot(tmp_path)
    result = mr.run_mapping(
        config_for(tmp_path, kg_path, kg_sha, mr.MODE_LIVE, "live"),
        transport=transport)
    approved = {c for row in pol.load_policy_csv(POLICY_CSV)
                for c in row.ordered_classes}
    rows = list(csvmod.DictReader(
        (result.config.output_dir / "mapping_summary.csv").open(encoding="utf-8")))
    assert {r["class_uri"] for r in rows} <= approved
    records = [json.loads(line) for line in
               (result.config.output_dir / "mapped_candidates.jsonl")
               .read_text(encoding="utf-8").splitlines()]
    assert {r["class_uri"] for r in records} <= approved


def test_a_repeated_live_run_with_a_cold_cache_is_byte_identical(tmp_path):
    """Determinism, not cache reuse: the second run re-retrieves everything."""
    kg_path, kg_sha, transport, class_members, redirects = build_synthetic_pilot(
        tmp_path)
    first = mr.run_mapping(
        config_for(tmp_path, kg_path, kg_sha, mr.MODE_LIVE, "first"),
        transport=transport)

    second_transport = ScriptedTransport(class_members, redirects=redirects)
    second = mr.run_mapping(
        config_for(tmp_path, kg_path, kg_sha, mr.MODE_LIVE, "second",
                   cache_path=tmp_path / "cold_cache.sqlite"),
        transport=second_transport)

    assert second.network_page_count == first.network_page_count > 0
    assert second.cache_hit_count == 0
    for name in SCIENTIFIC_FILES:
        assert ((first.config.output_dir / name).read_bytes()
                == (second.config.output_dir / name).read_bytes()), name
