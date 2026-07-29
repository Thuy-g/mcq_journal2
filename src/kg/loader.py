############################################################################
# src/kg/loader.py
#
# Read-only loader for an EXISTING pinned local-KG pickle.
#
# The pickle is the 5-tuple produced by src/read_ttl.py:
#     (url_index, index_url, out_neighbor, in_neighbor, index_type)
#   url_index     {"<uri>": int}
#   index_url     {int: "<uri>"}
#   out_neighbor  {subject_index: [(predicate_index, object_index), ...]}
#   in_neighbor   {object_index:  [(predicate_index, subject_index), ...]}
#   index_type    {node_index: int}   (entity type; 0 = Others)
#
# HARD RULES FOR THIS MODULE
#   * never rebuild the pickle — read_ttl.read_ttl() assigns node indices by
#     iterating a Python set, so a rebuild silently renumbers every node and
#     invalidates any index recorded by an earlier run;
#   * never fall back to the network when a file is missing or unreadable;
#   * never choose between several plausible pickles on the caller's behalf —
#     report LOCAL_KG_SELECTION_REQUIRED and let a human pin one;
#   * record the SHA-256 of the file actually loaded, as run provenance.
#
# Errors are typed so a caller can tell "no file" from "several files" from
# "file present but not the expected schema".
############################################################################

from __future__ import annotations

import hashlib
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

# --- Resolution statuses ---------------------------------------------------
LOCAL_KG_UNIQUE = "LOCAL_KG_UNIQUE"
LOCAL_KG_SELECTION_REQUIRED = "LOCAL_KG_SELECTION_REQUIRED"

# Filename patterns searched under data/. Kept broad on purpose: it is better to
# surface two candidates and stop than to match narrowly and silently pick one.
LOCAL_KG_GLOB_PATTERNS = ("*pickle*", "*.pkl", "*.pickle")

# Files that merely mention "pickle" but are not a KG dump. Extensions only, so
# the rule stays explainable.
LOCAL_KG_EXCLUDED_SUFFIXES = (
    ".txt", ".csv", ".json", ".md", ".py", ".log", ".ttl", ".zip", ".sha256",
)

EXPECTED_TUPLE_LENGTH = 5
SCHEMA_FIELD_NAMES = (
    "url_index", "index_url", "out_neighbor", "in_neighbor", "index_type",
)


# --- Typed errors ----------------------------------------------------------

class LocalKGError(Exception):
    """Base class for every local-KG loading failure."""


class LocalKGFileError(LocalKGError):
    """The requested local-KG file is missing or cannot be read."""


class LocalKGSchemaError(LocalKGError):
    """The file unpickled but is not the expected read_ttl 5-tuple schema."""


class LocalKGSelectionRequiredError(LocalKGError):
    """Zero or several plausible local-KG pickles exist; a human must pin one."""

    def __init__(self, message: str, candidates: Sequence["LocalKGCandidate"] = ()):
        super().__init__(message)
        self.status = LOCAL_KG_SELECTION_REQUIRED
        self.candidates = tuple(candidates)


class UnknownUriError(LocalKGError, KeyError):
    """A URI was requested that the pinned local KG does not contain."""


class UnknownIndexError(LocalKGError, KeyError):
    """A node index was requested that the pinned local KG does not contain."""


# --- Inventory -------------------------------------------------------------

@dataclass(frozen=True)
class LocalKGCandidate:
    """One plausible local-KG pickle found under data/."""

    path: Path
    size_bytes: int
    sha256: Optional[str] = None

    def as_record(self, root: Optional[Path] = None) -> dict:
        path = self.path
        if root is not None:
            try:
                path = self.path.relative_to(root)
            except ValueError:
                pass
        return {
            "path": str(path),
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class LocalKGResolution:
    """Which local KG a run may use, and the evidence behind that."""

    status: str
    data_dir: Path
    candidates: tuple[LocalKGCandidate, ...]
    selected: Optional[LocalKGCandidate] = None
    reason: str = ""

    @property
    def is_unique(self) -> bool:
        return self.status == LOCAL_KG_UNIQUE

    def as_record(self, root: Optional[Path] = None) -> dict:
        return {
            "status": self.status,
            "data_dir": str(self.data_dir if root is None
                            else self.data_dir.relative_to(root)),
            "search_patterns": list(LOCAL_KG_GLOB_PATTERNS),
            "excluded_suffixes": list(LOCAL_KG_EXCLUDED_SUFFIXES),
            "candidate_count": len(self.candidates),
            "candidates": [c.as_record(root) for c in self.candidates],
            "selected": None if self.selected is None
                        else self.selected.as_record(root),
            "reason": self.reason,
        }


def sha256_file(path: str | Path, chunk_size: int = 1 << 23) -> str:
    """SHA-256 of a file, streamed. Used for input-file provenance."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def inventory_local_kg_candidates(data_dir: str | Path,
                                  with_hashes: bool = False
                                  ) -> tuple[LocalKGCandidate, ...]:
    """List plausible local-KG pickles directly under `data_dir`, sorted by path.

    Searches only `data_dir` itself, non-recursively, because a pinned KG build
    is a top-level artifact; recursing would sweep in unrelated scratch copies.

    `with_hashes=True` hashes each candidate. That is gigabytes of I/O for a real
    DBpedia dump, so it is opt-in rather than the default.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise LocalKGFileError(f"data directory not found: {data_dir}")

    found: dict[Path, LocalKGCandidate] = {}
    for pattern in LOCAL_KG_GLOB_PATTERNS:
        for path in data_dir.glob(pattern):
            if not path.is_file():
                continue
            if path.suffix.lower() in LOCAL_KG_EXCLUDED_SUFFIXES:
                continue
            if path in found:
                continue
            found[path] = LocalKGCandidate(
                path=path,
                size_bytes=path.stat().st_size,
                sha256=sha256_file(path) if with_hashes else None,
            )
    # Sorted by path: deterministic, independent of glob and filesystem order.
    return tuple(found[p] for p in sorted(found))


def resolve_local_kg(data_dir: str | Path,
                     with_hashes: bool = False) -> LocalKGResolution:
    """Decide whether exactly one local KG can be pinned without guessing.

    Never raises on ambiguity — it returns a resolution carrying
    LOCAL_KG_SELECTION_REQUIRED so a caller can record the state and continue.
    """
    data_dir = Path(data_dir)
    candidates = inventory_local_kg_candidates(data_dir, with_hashes=with_hashes)

    if len(candidates) == 1:
        return LocalKGResolution(
            status=LOCAL_KG_UNIQUE,
            data_dir=data_dir,
            candidates=candidates,
            selected=candidates[0],
            reason=(f"exactly one candidate local-KG pickle found under "
                    f"{data_dir.name}/"),
        )
    if not candidates:
        reason = (f"no candidate local-KG pickle found under {data_dir.name}/ "
                  f"matching {list(LOCAL_KG_GLOB_PATTERNS)}")
    else:
        reason = (f"{len(candidates)} candidate local-KG pickles found under "
                  f"{data_dir.name}/; a human must pin exactly one")
    return LocalKGResolution(
        status=LOCAL_KG_SELECTION_REQUIRED,
        data_dir=data_dir,
        candidates=candidates,
        selected=None,
        reason=reason,
    )


# --- The loaded graph ------------------------------------------------------

@dataclass(frozen=True)
class LocalKG:
    """A pinned local KG, loaded read-only, with its input-file provenance."""

    url_index: Mapping[str, int]
    index_url: Mapping[int, str]
    out_neighbor: Mapping[int, Sequence[tuple[int, int]]]
    in_neighbor: Mapping[int, Sequence[tuple[int, int]]]
    index_type: Mapping[int, int]
    source_path: Path
    source_sha256: str
    source_size_bytes: int

    # --- URI <-> index ----------------------------------------------------
    def has_uri(self, uri: str) -> bool:
        return uri in self.url_index

    def index_for_uri(self, uri: str) -> int:
        try:
            return self.url_index[uri]
        except KeyError:
            raise UnknownUriError(
                f"URI not present in pinned local KG "
                f"{self.source_path.name}: {uri!r}"
            ) from None

    def uri_for_index(self, index: int) -> str:
        try:
            return self.index_url[index]
        except KeyError:
            raise UnknownIndexError(
                f"node index {index!r} not present in pinned local KG "
                f"{self.source_path.name}"
            ) from None

    def index_for_uri_or_none(self, uri: str) -> Optional[int]:
        """Lookup that treats absence as data, not as an error.

        Local coverage of an approved class is a quantity the pilot must
        MEASURE, so a miss has to be reportable without raising.
        """
        return self.url_index.get(uri)

    def indices_for_uris(self, uris: Iterable[str]
                         ) -> tuple[tuple[int, ...], tuple[str, ...]]:
        """(found indices in input order, missing URIs in input order)."""
        found: list[int] = []
        missing: list[str] = []
        for uri in uris:
            idx = self.url_index.get(uri)
            if idx is None:
                missing.append(uri)
            else:
                found.append(idx)
        return tuple(found), tuple(missing)

    # --- Sizes ------------------------------------------------------------
    @property
    def uri_count(self) -> int:
        """Number of distinct URIs, i.e. nodes AND predicates share this space."""
        return len(self.url_index)

    @property
    def edge_count(self) -> int:
        return sum(len(v) for v in self.out_neighbor.values())

    def as_record(self, root: Optional[Path] = None) -> dict:
        path = self.source_path
        if root is not None:
            try:
                path = self.source_path.relative_to(root)
            except ValueError:
                pass
        return {
            "source_path": str(path),
            "source_sha256": self.source_sha256,
            "source_size_bytes": self.source_size_bytes,
            "uri_count": self.uri_count,
            "out_neighbor_subjects": len(self.out_neighbor),
            "in_neighbor_objects": len(self.in_neighbor),
            "index_type_entries": len(self.index_type),
            "edge_count": self.edge_count,
        }


def _validate_schema(obj: object, path: Path) -> tuple:
    """Check the unpickled object is the read_ttl 5-tuple, before using it."""
    if not isinstance(obj, (tuple, list)):
        raise LocalKGSchemaError(
            f"{path.name}: expected a {EXPECTED_TUPLE_LENGTH}-tuple "
            f"{SCHEMA_FIELD_NAMES}, got {type(obj).__name__}"
        )
    if len(obj) != EXPECTED_TUPLE_LENGTH:
        raise LocalKGSchemaError(
            f"{path.name}: expected {EXPECTED_TUPLE_LENGTH} elements "
            f"{SCHEMA_FIELD_NAMES}, got {len(obj)}"
        )
    for name, value in zip(SCHEMA_FIELD_NAMES, obj):
        if not isinstance(value, Mapping):
            raise LocalKGSchemaError(
                f"{path.name}: element {name!r} must be a mapping, "
                f"got {type(value).__name__}"
            )

    url_index, index_url, out_neighbor, in_neighbor, index_type = obj

    if not url_index:
        raise LocalKGSchemaError(f"{path.name}: url_index is empty")
    if len(url_index) != len(index_url):
        raise LocalKGSchemaError(
            f"{path.name}: url_index has {len(url_index)} entries but index_url "
            f"has {len(index_url)}; the two must be inverses"
        )

    # Spot-check the inverse property on a deterministic sample rather than all
    # 6.7M entries: a full check would dominate load time, and a corrupted dump
    # fails on any sample.
    for uri in sorted(url_index)[:16]:
        idx = url_index[uri]
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise LocalKGSchemaError(
                f"{path.name}: url_index[{uri!r}] must be an int, "
                f"got {type(idx).__name__}"
            )
        if index_url.get(idx) != uri:
            raise LocalKGSchemaError(
                f"{path.name}: url_index and index_url disagree for {uri!r} "
                f"(index {idx} maps back to {index_url.get(idx)!r})"
            )

    for name, neighbor in (("out_neighbor", out_neighbor),
                           ("in_neighbor", in_neighbor)):
        for node in sorted(neighbor)[:8]:
            edges = neighbor[node]
            if not isinstance(edges, (list, tuple)):
                raise LocalKGSchemaError(
                    f"{path.name}: {name}[{node}] must be a list of "
                    f"(predicate, node) pairs, got {type(edges).__name__}"
                )
            for edge in edges[:8]:
                if not (isinstance(edge, tuple) and len(edge) == 2):
                    raise LocalKGSchemaError(
                        f"{path.name}: {name}[{node}] must contain "
                        f"(predicate, node) 2-tuples, got {edge!r}"
                    )

    return tuple(obj)


def load_local_kg(path: str | Path, verify_sha256: Optional[str] = None) -> LocalKG:
    """Load an existing pinned local-KG pickle read-only.

    Does not build, repair, migrate or write anything, and never reaches the
    network. `verify_sha256` pins the run to one exact build: a mismatch raises
    rather than continuing against a different graph.
    """
    path = Path(path)
    if not path.is_file():
        raise LocalKGFileError(
            f"pinned local KG not found: {path} — this loader never rebuilds a "
            f"pickle and never falls back to the network"
        )

    size_bytes = path.stat().st_size
    digest = sha256_file(path)
    if verify_sha256 is not None and digest != verify_sha256:
        raise LocalKGFileError(
            f"{path.name}: SHA-256 mismatch.\n"
            f"  expected: {verify_sha256}\n"
            f"  found:    {digest}"
        )

    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)
    except LocalKGError:
        raise
    except Exception as exc:                     # unpickling failure, truncation
        raise LocalKGSchemaError(
            f"{path.name}: could not unpickle local KG: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    url_index, index_url, out_neighbor, in_neighbor, index_type = _validate_schema(
        obj, path)

    return LocalKG(
        url_index=url_index,
        index_url=index_url,
        out_neighbor=out_neighbor,
        in_neighbor=in_neighbor,
        index_type=index_type,
        source_path=path,
        source_sha256=digest,
        source_size_bytes=size_bytes,
    )


def load_pinned_local_kg(data_dir: str | Path,
                         verify_sha256: Optional[str] = None) -> LocalKG:
    """Resolve then load, refusing to guess when the choice is ambiguous."""
    resolution = resolve_local_kg(data_dir)
    if not resolution.is_unique:
        raise LocalKGSelectionRequiredError(resolution.reason, resolution.candidates)
    assert resolution.selected is not None       # implied by is_unique
    return load_local_kg(resolution.selected.path, verify_sha256=verify_sha256)
