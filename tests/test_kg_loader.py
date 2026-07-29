############################################################################
# tests/test_kg_loader.py
#
# Contract tests for src/kg/loader.py — read-only access to a pinned local-KG
# pickle.
#
# What these tests defend:
#   * the loader never rebuilds a pickle and never falls back to the network;
#   * the schema is validated before the graph is used;
#   * the SHA-256 of the file actually loaded is recorded as provenance;
#   * URI<->index access is available, with typed errors for misses;
#   * zero or several plausible pickles produce LOCAL_KG_SELECTION_REQUIRED
#     rather than a silent guess.
#
# The real 1.2 GB DBpedia pickle is NOT loaded by default: it takes about a
# minute and several GB of RAM. Its inventory/resolution is checked cheaply here,
# and the full load is exercised by the opt-in test at the bottom, enabled with
#     MCQ_JOURNAL2_LOAD_REAL_KG=1
#
# Offline and deterministic. No network in any test, opt-in test included.
#
# Run:
#     python -m pytest -vv tests/test_kg_loader.py
############################################################################

from __future__ import annotations

import hashlib
import os
import pathlib
import pickle
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from kg import loader as kgl  # noqa: E402

DATA_DIR = REPO_ROOT / "data"
REAL_PICKLE = DATA_DIR / "infobox.pickle_EnglishVersion_EntityType"

# SHA-256 of the pinned local KG, measured on 2026-07-30. Recorded so a silent
# rebuild — which would renumber every node index — cannot go unnoticed.
REAL_PICKLE_SHA256 = "e230c5b95e20093631697624d9c46f30a14081b3f415d5027ffaf313bdbbea1b"


def make_kg_payload(uris=("<a>", "<b>", "<c>"), predicate="<p>"):
    """A minimal but schema-valid read_ttl 5-tuple: a --p--> b --p--> c."""
    all_uris = list(uris) + [predicate]
    url_index = {u: i for i, u in enumerate(all_uris)}
    index_url = {i: u for u, i in url_index.items()}
    p = url_index[predicate]
    a, b, c = (url_index[u] for u in uris)
    out_neighbor = {a: [(p, b)], b: [(p, c)]}
    in_neighbor = {b: [(p, a)], c: [(p, b)]}
    index_type = {a: 0, b: 0, c: 0}
    return url_index, index_url, out_neighbor, in_neighbor, index_type


def write_pickle(path: pathlib.Path, payload) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(payload, f)
    return path


# --- Inventory and resolution ---------------------------------------------

def test_inventory_is_empty_when_no_pickle_is_present(tmp_path):
    (tmp_path / "notes.txt").write_text("not a pickle", encoding="utf-8")
    assert kgl.inventory_local_kg_candidates(tmp_path) == ()


def test_inventory_finds_a_single_pickle(tmp_path):
    write_pickle(tmp_path / "infobox.pickle_EnglishVersion", make_kg_payload())
    candidates = kgl.inventory_local_kg_candidates(tmp_path)

    assert len(candidates) == 1
    assert candidates[0].path.name == "infobox.pickle_EnglishVersion"
    assert candidates[0].size_bytes > 0
    assert candidates[0].sha256 is None                  # hashing is opt-in


def test_inventory_ignores_text_and_csv_files_that_mention_pickle(tmp_path):
    write_pickle(tmp_path / "kg.pickle", make_kg_payload())
    (tmp_path / "pickle_notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "pickle_manifest.csv").write_text("x", encoding="utf-8")
    (tmp_path / "pickle_manifest.json").write_text("{}", encoding="utf-8")

    candidates = kgl.inventory_local_kg_candidates(tmp_path)
    assert [c.path.name for c in candidates] == ["kg.pickle"]


def test_inventory_is_sorted_and_deduplicated(tmp_path):
    """A file matching two globs must be reported once, in path order."""
    for name in ("z.pickle", "a.pickle", "m.pkl"):
        write_pickle(tmp_path / name, make_kg_payload())

    candidates = kgl.inventory_local_kg_candidates(tmp_path)
    assert [c.path.name for c in candidates] == ["a.pickle", "m.pkl", "z.pickle"]


def test_inventory_can_hash_on_request(tmp_path):
    path = write_pickle(tmp_path / "kg.pickle", make_kg_payload())
    expected = hashlib.sha256(path.read_bytes()).hexdigest()

    candidates = kgl.inventory_local_kg_candidates(tmp_path, with_hashes=True)
    assert candidates[0].sha256 == expected


def test_inventory_of_a_missing_directory_raises(tmp_path):
    with pytest.raises(kgl.LocalKGFileError):
        kgl.inventory_local_kg_candidates(tmp_path / "absent")


def test_exactly_one_candidate_resolves_uniquely(tmp_path):
    write_pickle(tmp_path / "kg.pickle", make_kg_payload())
    resolution = kgl.resolve_local_kg(tmp_path)

    assert resolution.status == kgl.LOCAL_KG_UNIQUE
    assert resolution.is_unique is True
    assert resolution.selected is not None
    assert resolution.selected.path.name == "kg.pickle"


def test_no_candidate_requires_explicit_selection(tmp_path):
    resolution = kgl.resolve_local_kg(tmp_path)

    assert resolution.status == kgl.LOCAL_KG_SELECTION_REQUIRED
    assert resolution.selected is None
    assert resolution.candidates == ()
    assert "no candidate" in resolution.reason


def test_several_candidates_require_explicit_selection(tmp_path):
    write_pickle(tmp_path / "kg_a.pickle", make_kg_payload())
    write_pickle(tmp_path / "kg_b.pickle", make_kg_payload())

    resolution = kgl.resolve_local_kg(tmp_path)
    assert resolution.status == kgl.LOCAL_KG_SELECTION_REQUIRED
    assert resolution.selected is None
    assert len(resolution.candidates) == 2
    assert "a human must pin exactly one" in resolution.reason


def test_ambiguous_resolution_refuses_to_load(tmp_path):
    write_pickle(tmp_path / "kg_a.pickle", make_kg_payload())
    write_pickle(tmp_path / "kg_b.pickle", make_kg_payload())

    with pytest.raises(kgl.LocalKGSelectionRequiredError) as excinfo:
        kgl.load_pinned_local_kg(tmp_path)
    assert excinfo.value.status == kgl.LOCAL_KG_SELECTION_REQUIRED
    assert len(excinfo.value.candidates) == 2


def test_resolution_record_is_serialisable(tmp_path):
    write_pickle(tmp_path / "kg.pickle", make_kg_payload())
    record = kgl.resolve_local_kg(tmp_path).as_record()

    assert record["status"] == kgl.LOCAL_KG_UNIQUE
    assert record["candidate_count"] == 1
    assert record["selected"]["path"].endswith("kg.pickle")
    assert record["search_patterns"] == list(kgl.LOCAL_KG_GLOB_PATTERNS)


# --- Loading and provenance -----------------------------------------------

def test_load_records_the_input_file_sha256_and_size(tmp_path):
    path = write_pickle(tmp_path / "kg.pickle", make_kg_payload())
    expected = hashlib.sha256(path.read_bytes()).hexdigest()

    kg = kgl.load_local_kg(path)
    assert kg.source_sha256 == expected
    assert kg.source_size_bytes == path.stat().st_size
    assert kg.source_path == path
    assert kg.as_record()["source_sha256"] == expected


def test_verify_sha256_accepts_the_matching_digest(tmp_path):
    path = write_pickle(tmp_path / "kg.pickle", make_kg_payload())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    kg = kgl.load_local_kg(path, verify_sha256=digest)
    assert kg.source_sha256 == digest


def test_verify_sha256_rejects_a_different_build(tmp_path):
    path = write_pickle(tmp_path / "kg.pickle", make_kg_payload())
    with pytest.raises(kgl.LocalKGFileError, match="SHA-256 mismatch"):
        kgl.load_local_kg(path, verify_sha256="0" * 64)


def test_uri_and_index_access(tmp_path):
    path = write_pickle(tmp_path / "kg.pickle", make_kg_payload())
    kg = kgl.load_local_kg(path)

    idx = kg.index_for_uri("<b>")
    assert kg.uri_for_index(idx) == "<b>"
    assert kg.has_uri("<b>") is True
    assert kg.has_uri("<zz>") is False
    assert kg.index_for_uri_or_none("<zz>") is None
    assert kg.index_for_uri_or_none("<b>") == idx


def test_unknown_uri_and_index_raise_typed_errors(tmp_path):
    path = write_pickle(tmp_path / "kg.pickle", make_kg_payload())
    kg = kgl.load_local_kg(path)

    with pytest.raises(kgl.UnknownUriError):
        kg.index_for_uri("<missing>")
    with pytest.raises(kgl.UnknownIndexError):
        kg.uri_for_index(10_000)
    # Both stay catchable as KeyError for callers that treat a miss generically.
    with pytest.raises(KeyError):
        kg.index_for_uri("<missing>")


def test_indices_for_uris_separates_found_from_missing(tmp_path):
    """Local coverage of an approved class is measured, so a miss is data."""
    path = write_pickle(tmp_path / "kg.pickle", make_kg_payload())
    kg = kgl.load_local_kg(path)

    found, missing = kg.indices_for_uris(["<a>", "<nope>", "<c>", "<also_nope>"])
    assert found == (kg.index_for_uri("<a>"), kg.index_for_uri("<c>"))
    assert missing == ("<nope>", "<also_nope>")


def test_graph_sizes_are_reported(tmp_path):
    path = write_pickle(tmp_path / "kg.pickle", make_kg_payload())
    kg = kgl.load_local_kg(path)

    assert kg.uri_count == 4                             # 3 nodes + 1 predicate
    assert kg.edge_count == 2
    record = kg.as_record()
    assert record["uri_count"] == 4
    assert record["edge_count"] == 2


# --- Refusals: no rebuild, no network -------------------------------------

def test_missing_file_raises_and_says_it_will_not_rebuild(tmp_path):
    with pytest.raises(kgl.LocalKGFileError, match="never rebuilds"):
        kgl.load_local_kg(tmp_path / "absent.pickle")


def test_missing_file_is_not_created_by_the_loader(tmp_path):
    target = tmp_path / "absent.pickle"
    with pytest.raises(kgl.LocalKGFileError):
        kgl.load_local_kg(target)
    assert not target.exists()                           # nothing was built


def test_loader_module_has_no_network_imports():
    """A structural check that the loader cannot reach the network."""
    source = (SRC_DIR / "kg" / "loader.py").read_text(encoding="utf-8")
    for forbidden in ("import requests", "urllib.request", "SPARQLWrapper",
                      "http.client", "socket"):
        assert forbidden not in source


# --- Schema validation ----------------------------------------------------

def test_wrong_tuple_length_is_rejected(tmp_path):
    path = write_pickle(tmp_path / "short.pickle", ({}, {}, {}))
    with pytest.raises(kgl.LocalKGSchemaError, match="expected 5 elements"):
        kgl.load_local_kg(path)


def test_non_tuple_payload_is_rejected(tmp_path):
    path = write_pickle(tmp_path / "dict.pickle", {"url_index": {}})
    with pytest.raises(kgl.LocalKGSchemaError, match="expected a 5-tuple"):
        kgl.load_local_kg(path)


def test_non_mapping_element_is_rejected(tmp_path):
    url_index, index_url, out_n, in_n, index_type = make_kg_payload()
    path = write_pickle(tmp_path / "bad.pickle",
                        (url_index, index_url, out_n, in_n, ["not", "a", "map"]))
    with pytest.raises(kgl.LocalKGSchemaError, match="index_type.*must be a mapping"):
        kgl.load_local_kg(path)


def test_empty_url_index_is_rejected(tmp_path):
    path = write_pickle(tmp_path / "empty.pickle", ({}, {}, {}, {}, {}))
    with pytest.raises(kgl.LocalKGSchemaError, match="url_index is empty"):
        kgl.load_local_kg(path)


def test_url_index_and_index_url_size_mismatch_is_rejected(tmp_path):
    url_index, index_url, out_n, in_n, index_type = make_kg_payload()
    index_url.pop(0)
    path = write_pickle(tmp_path / "mismatch.pickle",
                        (url_index, index_url, out_n, in_n, index_type))
    with pytest.raises(kgl.LocalKGSchemaError, match="must be inverses"):
        kgl.load_local_kg(path)


def test_url_index_and_index_url_disagreement_is_rejected(tmp_path):
    url_index, index_url, out_n, in_n, index_type = make_kg_payload()
    index_url[0] = "<something_else>"
    path = write_pickle(tmp_path / "disagree.pickle",
                        (url_index, index_url, out_n, in_n, index_type))
    with pytest.raises(kgl.LocalKGSchemaError, match="disagree"):
        kgl.load_local_kg(path)


def test_malformed_adjacency_entry_is_rejected(tmp_path):
    url_index, index_url, out_n, in_n, index_type = make_kg_payload()
    out_n[0] = "not a list"
    path = write_pickle(tmp_path / "bad_adj.pickle",
                        (url_index, index_url, out_n, in_n, index_type))
    with pytest.raises(kgl.LocalKGSchemaError, match="must be a list"):
        kgl.load_local_kg(path)


def test_adjacency_entry_that_is_not_a_pair_is_rejected(tmp_path):
    url_index, index_url, out_n, in_n, index_type = make_kg_payload()
    out_n[0] = [(1, 2, 3)]
    path = write_pickle(tmp_path / "bad_pair.pickle",
                        (url_index, index_url, out_n, in_n, index_type))
    with pytest.raises(kgl.LocalKGSchemaError, match="2-tuples"):
        kgl.load_local_kg(path)


def test_unpicklable_file_is_reported_as_a_schema_error(tmp_path):
    path = tmp_path / "garbage.pickle"
    path.write_bytes(b"\x80\x04 definitely not a pickle")
    with pytest.raises(kgl.LocalKGSchemaError, match="could not unpickle"):
        kgl.load_local_kg(path)


def test_load_pinned_local_kg_end_to_end(tmp_path):
    write_pickle(tmp_path / "kg.pickle", make_kg_payload())
    kg = kgl.load_pinned_local_kg(tmp_path)
    assert kg.uri_count == 4


# --- The repository's own data/ directory ----------------------------------

def test_repository_data_dir_resolves_to_exactly_one_local_kg():
    """Cheap: stats and globs only, no gigabyte read."""
    resolution = kgl.resolve_local_kg(DATA_DIR)

    assert resolution.status == kgl.LOCAL_KG_UNIQUE, resolution.reason
    assert resolution.selected is not None
    assert resolution.selected.path == REAL_PICKLE
    assert resolution.selected.size_bytes > 1_000_000_000


@pytest.mark.skipif(
    os.environ.get("MCQ_JOURNAL2_LOAD_REAL_KG") != "1",
    reason="set MCQ_JOURNAL2_LOAD_REAL_KG=1 to load the 1.2 GB pinned pickle",
)
def test_real_pinned_local_kg_loads_and_validates():
    kg = kgl.load_pinned_local_kg(DATA_DIR, verify_sha256=REAL_PICKLE_SHA256)

    assert kg.source_path == REAL_PICKLE
    assert kg.source_sha256 == REAL_PICKLE_SHA256
    assert kg.uri_count == 6_685_753

    # The four HanamiSpots seeds must be present and round-trip through the maps.
    for uri in ("<http://dbpedia.org/resource/Kamagatani>",
                "<http://dbpedia.org/resource/Hinokinai_River_Embankment>",
                "<http://dbpedia.org/resource/Tamagawadai_Park>",
                "<http://dbpedia.org/resource/Sakurayama>"):
        idx = kg.index_for_uri(uri)
        assert kg.uri_for_index(idx) == uri
