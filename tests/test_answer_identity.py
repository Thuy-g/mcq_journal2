############################################################################
# tests/test_answer_identity.py
#
# Tests for src/classes/answer_identity.py — the three-URI Answer-identity
# bridge between the CURRENT public DBpedia endpoint and the PINNED March-2023
# local infobox KG.
#
# EVERY TEST IS OFFLINE. The endpoint is a fake evidence source and the pinned
# KG is a four-entry dictionary, so nothing here needs the network or the
# 1.2 GB pickle. The four historical/current URI pairs the prompt names are
# REGRESSION FIXTURES: they appear in this file and nowhere in the production
# source, which is asserted directly.
############################################################################

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from classes import answer_identity as ai  # noqa: E402
from classes.member_mapper import (  # noqa: E402
    ClassRetrieval,
    make_local_lookup,
    map_class_members,
)

R = "http://dbpedia.org/resource/"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeEvidenceSource:
    """A deterministic stand-in for the live endpoint.

    `counts` maps a URI to its number of CURRENT dcterms:subject categories.
    `forward` maps a redirect stub to its target. `reverse` maps a target to the
    stubs that redirect to it. `fail` marks URIs whose lookups are UNAVAILABLE —
    the third state, kept distinct from "queried and found nothing".
    """

    def __init__(self, counts=None, forward=None, reverse=None, fail=()):
        self.counts = dict(counts or {})
        self.forward = dict(forward or {})
        self.reverse = dict(reverse or {})
        self.fail = set(fail)
        self.query_count = 0
        self.asked = []

    def _split(self, uris):
        unavailable = {u for u in uris if u in self.fail}
        return [u for u in uris if u not in unavailable], frozenset(unavailable)

    def category_counts(self, uris):
        self.query_count += 1
        self.asked.append(("category_counts", tuple(uris)))
        ok, bad = self._split(uris)
        return {u: self.counts[u] for u in ok if u in self.counts}, bad

    def forward_targets(self, uris):
        self.query_count += 1
        self.asked.append(("forward", tuple(uris)))
        ok, bad = self._split(uris)
        return {u: self.forward[u] for u in ok if u in self.forward}, bad

    def reverse_sources(self, uris):
        self.query_count += 1
        self.asked.append(("reverse", tuple(uris)))
        ok, bad = self._split(uris)
        return {u: self.reverse[u] for u in ok if u in self.reverse}, bad


def _executable_text(file_name: str) -> str:
    """The module's source with comments and docstrings removed, lower-cased.

    Prose has to be able to name the drift the module was built for and the
    relations it refuses to traverse; executable code must not. Stripping the
    two apart is what lets both assertions be strict.
    """
    source = (SRC_DIR / "classes" / file_name).read_text("utf-8")
    code_only = []
    in_docstring = False
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.count('"""') == 1:
            in_docstring = not in_docstring
            continue
        if in_docstring or stripped.startswith("#") or stripped.startswith('"""'):
            continue
        code_only.append(line.split("#", 1)[0])
    return "\n".join(code_only).lower()


def pinned_kg(*local_names):
    """A minimal `url_index`, in the pinned pickle's own bracketed key form."""
    return make_local_lookup({f"<{R}{name}>": 1000 + index
                              for index, name in enumerate(local_names)})


#: The four measured historical/current pairs, as
#: (pinned local name, current canonical name).
URI_PAIRS = [
    ("Akira_Suzuki_(chemist)", "Akira_Suzuki"),
    ("Makoto_Kobayashi_(physicist)", "Makoto_Kobayashi"),
    ("Xun_Kuang", "Xunzi_(philosopher)"),
    ("Monzaemon_Chikamatsu", "Chikamatsu_Monzaemon"),
]


def source_for(local_name, current_name):
    """The endpoint evidence for one pair, in the shape DBpedia actually holds.

    The current resource carries the categories; the historical spelling carries
    none and redirects to it. That is exactly the drift the bridge exists for.
    """
    return FakeEvidenceSource(
        counts={R + current_name: 12},
        forward={R + local_name: R + current_name},
        reverse={R + current_name: (R + local_name,)},
    )


# ---------------------------------------------------------------------------
# 1) The four required identity-equivalence regressions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("local_name,current_name", URI_PAIRS)
def test_both_spellings_reach_the_same_remote_entity_and_local_node(
        local_name, current_name):
    """The core requirement: old and current spellings CONVERGE.

    Same remote query URI, same pinned local node, same local index — and the
    original spelling preserved verbatim on each record, because that is the
    audit identity the input file can be reconciled against.
    """
    lookup = pinned_kg(local_name)
    from_old = ai.resolve_answer_identity(
        R + local_name, local_lookup=lookup, source=source_for(local_name, current_name))
    from_new = ai.resolve_answer_identity(
        R + current_name, local_lookup=lookup, source=source_for(local_name, current_name))

    assert from_old.resolved and from_new.resolved
    assert from_old.remote_query_uri == from_new.remote_query_uri == R + current_name
    assert from_old.local_kg_uri == from_new.local_kg_uri == R + local_name
    assert from_old.local_index == from_new.local_index
    # The immutable audit identity differs, and only it.
    assert from_old.original_uri == R + local_name
    assert from_new.original_uri == R + current_name


@pytest.mark.parametrize("local_name,current_name", URI_PAIRS)
def test_each_spelling_records_how_it_got_there(local_name, current_name):
    lookup = pinned_kg(local_name)
    from_old = ai.resolve_answer_identity(
        R + local_name, local_lookup=lookup, source=source_for(local_name, current_name))
    from_new = ai.resolve_answer_identity(
        R + current_name, local_lookup=lookup, source=source_for(local_name, current_name))

    # Supplied the historical URI: the pinned node is the URI itself, and the
    # remote side needed a forward redirect to find today's categories.
    assert from_old.local_resolution_method == \
        ai.LocalResolutionMethod.ORIGINAL_URI.value
    assert from_old.remote_redirect_status == ai.RemoteRedirectStatus.FOLLOWED.value
    assert from_old.remote_redirect_used is True
    assert from_old.remote_redirect_chain == (R + current_name,)

    # Supplied the current URI: no forward redirect was needed, and the pinned
    # node was reached through a REVERSE redirect alias.
    assert from_new.local_resolution_method == \
        ai.LocalResolutionMethod.REVERSE_REDIRECT_ALIAS.value
    assert from_new.remote_redirect_status == ai.RemoteRedirectStatus.NO_REDIRECT.value
    assert from_new.remote_redirect_used is False
    assert R + local_name in from_new.local_alias_candidates


def test_a_uri_that_already_has_categories_is_never_abandoned():
    """§5.1. A usable subject is kept even when a redirect chain also exists.

    Following a redirect away from a resource that already answers the question
    would change which entity's categories the run scored, for no gain.
    """
    lookup = pinned_kg("Albert_Einstein")
    source = FakeEvidenceSource(
        counts={R + "Albert_Einstein": 67},
        forward={R + "Albert_Einstein": R + "Einstein"},
    )
    identity = ai.resolve_answer_identity(
        R + "Albert_Einstein", local_lookup=lookup, source=source)
    assert identity.remote_query_uri == R + "Albert_Einstein"
    assert identity.remote_redirect_status == ai.RemoteRedirectStatus.NO_REDIRECT.value
    assert identity.original_uri_has_current_categories is True
    # No forward-redirect query was ever issued: the decision was made on the
    # category probe alone.
    assert [kind for kind, _ in source.asked] == ["category_counts"]


# ---------------------------------------------------------------------------
# 2) Answer exclusion by RESOLVED LOCAL IDENTITY, not by string inequality
# ---------------------------------------------------------------------------


def test_the_answer_is_excluded_once_under_a_different_alias():
    """The failure this repair prevents: the Answer as its own distractor.

    The class roster comes back from the CURRENT endpoint under the CURRENT
    spelling; the Answer was supplied under the HISTORICAL one. Comparing raw
    URI strings finds no match. Comparing resolved LOCAL NODE INDICES does.
    """
    local_name, current_name = "Xun_Kuang", "Xunzi_(philosopher)"
    peers = ["Confucius", "Mencius", "Han_Fei"]
    lookup = pinned_kg(local_name, *peers)
    identity = ai.resolve_answer_identity(
        R + local_name, local_lookup=lookup,
        source=source_for(local_name, current_name))

    # The roster names the Answer by its CURRENT URI, which is NOT a node here;
    # the redirect outcome is what carries it to the pinned node, exactly as it
    # does for any other member.
    retrieval = ClassRetrieval(
        class_uri=R + "Category:Chinese_philosophers",
        member_uris=tuple(sorted([R + current_name] + [R + p for p in peers])),
        raw_member_count=4, page_count=1, page_size=1000,
        retrieval_complete=True, incomplete_reason=None)
    from classes.member_mapper import RedirectOutcome, REDIRECT_RESOLVED

    resolved = lookup(R + local_name)
    outcomes = {R + current_name: RedirectOutcome(
        source_uri=R + current_name, status=REDIRECT_RESOLVED,
        chain=(R + local_name,), resolved_uri=R + local_name,
        local_index=resolved.local_index, lookup_form=resolved.lookup_form)}

    mapping = map_class_members(
        answer_uri=identity.local_kg_uri,      # <- the RESOLVED local identity
        class_uri=R + "Category:Chinese_philosophers",
        class_position="ranked_1", retrieval=retrieval,
        local_lookup=lookup, redirect_outcomes=outcomes)

    assert mapping.answer_excluded_count == 1
    assert mapping.mapped_candidate_count == len(peers)
    assert identity.local_index not in mapping.local_candidate_indices


def test_passing_the_unresolved_uri_would_admit_the_answer_as_its_own_distractor():
    """The counter-example, asserted so the repair's necessity is measured.

    Handing `map_class_members` the CURRENT spelling — which is not a node in the
    pinned dump — leaves the Answer node unexcluded and inflates the candidate
    pool by one. This is what the identity bridge prevents, and it is checked
    here rather than argued in a comment.
    """
    local_name, current_name = "Xun_Kuang", "Xunzi_(philosopher)"
    peers = ["Confucius", "Mencius", "Han_Fei"]
    lookup = pinned_kg(local_name, *peers)
    retrieval = ClassRetrieval(
        class_uri=R + "Category:Chinese_philosophers",
        member_uris=tuple(sorted([R + current_name] + [R + p for p in peers])),
        raw_member_count=4, page_count=1, page_size=1000,
        retrieval_complete=True, incomplete_reason=None)
    from classes.member_mapper import RedirectOutcome, REDIRECT_RESOLVED

    resolved = lookup(R + local_name)
    outcomes = {R + current_name: RedirectOutcome(
        source_uri=R + current_name, status=REDIRECT_RESOLVED,
        chain=(R + local_name,), resolved_uri=R + local_name,
        local_index=resolved.local_index, lookup_form=resolved.lookup_form)}

    mapping = map_class_members(
        answer_uri=R + current_name,           # <- the UNRESOLVED remote spelling
        class_uri=R + "Category:Chinese_philosophers",
        class_position="ranked_1", retrieval=retrieval,
        local_lookup=lookup, redirect_outcomes=outcomes)

    assert mapping.answer_local_index is None
    assert mapping.answer_excluded_count == 0
    assert mapping.mapped_candidate_count == len(peers) + 1   # the Answer leaked in


# ---------------------------------------------------------------------------
# 3) The refusals: ambiguity, absence, failure, cycles, budgets
# ---------------------------------------------------------------------------


def test_two_aliases_reaching_two_different_nodes_is_refused():
    lookup = pinned_kg("Old_Name_A", "Old_Name_B")
    source = FakeEvidenceSource(
        counts={R + "Current_Name": 5},
        reverse={R + "Current_Name": (R + "Old_Name_A", R + "Old_Name_B")})
    identity = ai.resolve_answer_identity(
        R + "Current_Name", local_lookup=lookup, source=source)
    assert identity.resolution_status == ai.IdentityStatus.AMBIGUOUS_LOCAL_ALIAS.value
    assert identity.local_resolution_method == ai.LocalResolutionMethod.AMBIGUOUS.value
    assert identity.local_kg_uri is None
    assert identity.resolved is False


def test_several_aliases_reaching_one_node_is_not_ambiguity():
    """Two spellings of the SAME entity resolve normally and deterministically."""
    lookup = make_local_lookup({f"<{R}Old_Name_A>": 7,
                                f"<{R}Old_Name_B>": 7})   # one node, two keys
    source = FakeEvidenceSource(
        counts={R + "Current_Name": 5},
        reverse={R + "Current_Name": (R + "Old_Name_B", R + "Old_Name_A")})
    identity = ai.resolve_answer_identity(
        R + "Current_Name", local_lookup=lookup, source=source)
    assert identity.resolved
    assert identity.local_index == 7
    # Lexicographically smallest alias, so the recorded URI is stable across runs.
    assert identity.local_kg_uri == R + "Old_Name_A"


def test_no_local_identity_is_reported_not_guessed():
    lookup = pinned_kg("Somebody_Else")
    source = FakeEvidenceSource(counts={R + "Current_Name": 5},
                                reverse={R + "Current_Name": (R + "Another_Alias",)})
    identity = ai.resolve_answer_identity(
        R + "Current_Name", local_lookup=lookup, source=source)
    assert identity.resolution_status == ai.IdentityStatus.NO_LOCAL_IDENTITY.value
    assert identity.local_kg_uri is None
    assert identity.remote_query_uri == R + "Current_Name"   # the remote half worked


def test_a_failed_reverse_lookup_is_unknown_and_not_an_absence():
    lookup = pinned_kg("Somebody_Else")
    source = FakeEvidenceSource(counts={R + "Current_Name": 5},
                                fail=[R + "Current_Name"])
    # The category probe fails first, so the remote half already reports failure.
    identity = ai.resolve_answer_identity(
        R + "Current_Name", local_lookup=lookup, source=source)
    assert identity.remote_redirect_status == ai.RemoteRedirectStatus.QUERY_FAILED.value
    assert identity.original_uri_has_current_categories is None
    assert "did not complete" in identity.detail


def test_a_redirect_cycle_keeps_the_original_uri():
    lookup = pinned_kg("Nothing_Here")
    source = FakeEvidenceSource(
        counts={},
        forward={R + "A": R + "B", R + "B": R + "A"},
        reverse={})
    identity = ai.resolve_answer_identity(R + "A", local_lookup=lookup, source=source)
    assert identity.remote_redirect_status == ai.RemoteRedirectStatus.CYCLE.value
    assert identity.remote_query_uri == R + "A"


def test_the_hop_budget_is_reported_as_our_limit_not_as_the_data():
    lookup = pinned_kg("Nothing_Here")
    source = FakeEvidenceSource(
        counts={},
        forward={R + "A": R + "B", R + "B": R + "C", R + "C": R + "D",
                 R + "D": R + "E"})
    resolution = ai.resolve_remote_query_uri(R + "A", source, max_hops=2)
    assert resolution.status == ai.RemoteRedirectStatus.MAX_HOPS
    assert resolution.uri == R + "A"   # a broken chain's midpoint is never queried


def test_an_unsafe_redirect_target_stops_the_walk():
    lookup = pinned_kg("Nothing_Here")
    source = FakeEvidenceSource(counts={}, forward={R + "A": "not a uri at all"})
    identity = ai.resolve_answer_identity(R + "A", local_lookup=lookup, source=source)
    assert identity.remote_redirect_status == ai.RemoteRedirectStatus.UNSAFE_TARGET.value
    assert identity.remote_query_uri == R + "A"


def test_a_malformed_answer_uri_is_input_invalid():
    identity = ai.resolve_answer_identity(
        "not a uri", local_lookup=pinned_kg("X"), source=None)
    assert identity.resolution_status == ai.IdentityStatus.INPUT_INVALID.value
    assert identity.resolved is False


def test_without_an_evidence_source_the_local_half_still_resolves():
    """Offline: the pinned dump alone settles step 1 and reports the rest."""
    lookup = pinned_kg("Albert_Einstein")
    identity = ai.resolve_answer_identity(
        R + "Albert_Einstein", local_lookup=lookup, source=None)
    assert identity.resolved
    assert identity.remote_query_uri == R + "Albert_Einstein"
    assert identity.local_resolution_method == \
        ai.LocalResolutionMethod.ORIGINAL_URI.value

    missing = ai.resolve_answer_identity(
        R + "Someone_Else", local_lookup=lookup, source=None)
    assert missing.resolution_status == ai.IdentityStatus.NO_LOCAL_IDENTITY.value


# ---------------------------------------------------------------------------
# 4) Query builders — refuse rather than escape, and never traverse owl:sameAs
# ---------------------------------------------------------------------------


def test_query_builders_refuse_an_unsafe_iri():
    for build in (ai.build_category_presence_query,
                  ai.build_forward_redirect_query,
                  ai.build_reverse_redirect_query):
        with pytest.raises(Exception):
            build(["http://dbpedia.org/resource/A B"])   # a space is not legal
        with pytest.raises(ValueError):
            build([])


def test_the_reverse_query_binds_the_target_and_the_forward_query_the_source():
    forward = ai.build_forward_redirect_query([R + "X"])
    reverse = ai.build_reverse_redirect_query([R + "X"])
    assert "VALUES ?source" in forward
    assert "VALUES ?target" in reverse
    assert "?source dbo:wikiPageRedirects ?target" in forward
    assert "?source dbo:wikiPageRedirects ?target" in reverse
    # The two are DIFFERENT queries with different #qid markers, so a cache row
    # and a provenance line can say which direction was asked.
    assert forward != reverse


def test_owl_same_as_is_never_used():
    """Substituting another KG's entity would silently redefine the Answer.

    Checked against the EXECUTABLE text only, since the prose has to be able to
    say that sameAs is forbidden.
    """
    for query in (ai.build_category_presence_query([R + "X"]),
                  ai.build_forward_redirect_query([R + "X"]),
                  ai.build_reverse_redirect_query([R + "X"])):
        assert "sameAs" not in query
    assert "sameAs" not in _executable_text("answer_identity.py")


# ---------------------------------------------------------------------------
# 5) No hard-coded mapping table in production control flow
# ---------------------------------------------------------------------------


def test_the_four_pairs_appear_nowhere_in_the_executable_source():
    """The pairs are REGRESSION FIXTURES. Production must rediscover them.

    Comments and docstrings are stripped before the search: the module has to be
    allowed to explain which drift it was built for, and a reader needs those
    examples. What must not exist is a branch, a dict or a constant naming them.
    """
    text = _executable_text("answer_identity.py")
    for name in ("akira", "suzuki", "kobayashi", "xun", "xunzi", "chikamatsu",
                 "monzaemon", "einstein", "yamanaka", "tokugawa"):
        assert name not in text, f"hard-coded entity name {name!r} in control flow"


def test_no_model_or_heuristic_library_is_imported():
    source = (SRC_DIR / "classes" / "answer_identity.py").read_text("utf-8")
    for banned in ("nltk", "spacy", "sentence_transformers", "torch", "openai",
                   "anthropic", "transformers", "difflib", "fuzzywuzzy"):
        assert not re.search(rf"^\s*(import|from)\s+{banned}\b", source,
                             re.MULTILINE), banned
