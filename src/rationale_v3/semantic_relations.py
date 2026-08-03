############################################################################
# src/rationale_v3/semantic_relations.py
#
# Canonical equality and a BOUNDED, ALLOWLISTED, CYCLE-SAFE parent-child layer.
#
# THE DEFECT THIS ADDRESSES
#   Prompt 8E compared counterpart URIs with string equality, which makes two
#   mistakes look identical to a correct answer: `Antisthenes_(Heraclitean)` and
#   `Heraclitus` are the same entity under a DBpedia redirect, and a candidate
#   whose birthPlace is a ward of the Answer's birthPlace SUPPORTS the more
#   general claim. Both failures push a fact UP in apparent strength.
#
#   This layer can only push evidence DOWN: it removes apparent contrast by
#   making a fact NOT_COVERED, and never manufactures exclusion. In R1 it also
#   never pushes an observed positive alternative down to an absence — an
#   unavailable index is reported through `semantic_check_status` and
#   `granularity_risk`, which block main-corpus eligibility instead.
#
# NOT A REASONER
#   A breadth-first walk over an ADJACENCY MAP built from an explicit allowlist,
#   with a configured maximum depth, a visited set and a recorded rule id per
#   edge. No property-hierarchy inference, no transitive closure over arbitrary
#   predicates, no owl reasoning, no type inference.
#
# WHY THE ALLOWLIST IS SO SHORT
#   DBpedia infobox predicates are polysemous ACROSS TEMPLATES: `dbp:region` is
#   the containing region on a settlement page and the philosophical tradition
#   on a philosopher page. The default policy admits administrative-containment
#   slots only, and every excluded predicate is listed with its reason.
#
# WHERE THE EDGES COME FROM
#   A CACHED index built once by an explicit offline command. The run never
#   loads the 1.2 GB pickle: it verifies the cache key and refuses a cache built
#   for a different KG, policy, depth or object list. With no cache every
#   parent-child question answers SEMANTIC_RELATION_UNAVAILABLE, which is a
#   reportable state and not an error.
#
# No relation here is inferred from how a URI is spelled: string shape drives
# only canonical NORMALIZATION, which is not a semantic claim.
############################################################################

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from rationale_v3.contracts import (
    RELATION_CANDIDATE_UNDER_CLAIM,
    RELATION_CANONICALLY_EQUIVALENT,
    RELATION_CLAIM_UNDER_CANDIDATE,
    RELATION_EXACT_EQUAL,
    RELATION_PROVEN_DISJOINT,
    RELATION_UNAVAILABLE,
    RELATION_UNRELATED_OR_UNKNOWN,
    RationaleV3ContractError,
)

VERSION = "rationale_v3.semantic_relations/1.0.0"

DEFAULT_MAX_DEPTH = 4

#: What the closure is allowed to mean. One kind only in Prompt 8F: a walk up
#: administrative containment. A second kind may be added later by policy, but it
#: must then get its own name so a reader can tell which walk produced a relation.
RELATION_KIND_PLACE_CONTAINMENT = "ADMINISTRATIVE_PLACE_CONTAINMENT"
RELATION_KINDS = (RELATION_KIND_PLACE_CONTAINMENT,)


class SemanticPolicyError(RationaleV3ContractError):
    """The semantic-relation policy file is missing, malformed or inconsistent."""


class SemanticCacheError(RationaleV3ContractError):
    """A cached semantic index does not match the key it must have been built for."""


# --- 1) CANONICALIZATION -----------------------------------------------------

def normalize_uri(uri: str) -> str:
    """Exact URI normalization. NOT a semantic claim.

    Three deterministic string operations, each of which leaves the referent
    unchanged by construction:

      * strip the pinned pickle's `<...>` key spelling;
      * Unicode NFC, so two byte sequences for the same character compare equal;
      * drop one trailing '/' , which DBpedia uses interchangeably.

    Nothing here lowercases, decodes percent escapes, or removes parentheses:
    `Iron(III)_chloride` and `Iron(II)_chloride` are different entities, and a
    normalizer that merged them would silently destroy a chemistry question
    (AUDIT item CE-10, T2.5).
    """
    if not isinstance(uri, str):
        raise RationaleV3ContractError(f"uri must be a string, got {uri!r}")
    text = uri.strip()
    if text.startswith("<") and text.endswith(">"):
        text = text[1:-1]
    text = unicodedata.normalize("NFC", text)
    if len(text) > 1 and text.endswith("/"):
        text = text[:-1]
    return text


# --- 2) THE POLICY -----------------------------------------------------------

@dataclass(frozen=True)
class TraversalRule:
    """One allowlisted edge type the closure may walk."""

    rule_id: str
    predicate_uri: str
    direction: str
    relation_kind: str
    description: str

    def as_record(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "predicate_uri": self.predicate_uri,
            "direction": self.direction,
            "relation_kind": self.relation_kind,
            "description": self.description,
        }


@dataclass(frozen=True)
class SemanticRelationPolicy:
    """The versioned §5 policy: what may be walked, how far, and what may not."""

    version: str
    max_depth: int
    traversal_rules: tuple[TraversalRule, ...]
    excluded_predicates: Mapping[str, str]
    equivalence_source: str
    equivalence_pairs: tuple[tuple[str, str], ...]
    disjointness_source: str
    disjoint_pairs: tuple[tuple[str, str], ...]
    policy_sha256: str
    notes: Mapping[str, str] = field(default_factory=dict)

    @property
    def allowlisted_predicates(self) -> tuple[str, ...]:
        return tuple(sorted({rule.predicate_uri for rule in self.traversal_rules}))

    def rule_for(self, predicate_uri: str,
                 direction: Optional[str] = None) -> Optional[TraversalRule]:
        """The first rule allowlisting this predicate, optionally in one
        direction. Rules are stored sorted by rule_id, so "first" is stable."""
        for rule in self.traversal_rules:
            if rule.predicate_uri != predicate_uri:
                continue
            if direction is not None and rule.direction != direction:
                continue
            return rule
        return None

    def as_record(self) -> dict:
        return {
            "version": self.version,
            "policy_sha256": self.policy_sha256,
            "max_depth": self.max_depth,
            "traversal_rules": [rule.as_record() for rule in self.traversal_rules],
            "allowlisted_predicates": list(self.allowlisted_predicates),
            "excluded_predicates": dict(sorted(self.excluded_predicates.items())),
            "equivalence_source": self.equivalence_source,
            "equivalence_pair_count": len(self.equivalence_pairs),
            "disjointness_source": self.disjointness_source,
            "disjoint_pair_count": len(self.disjoint_pairs),
            "notes": dict(sorted(self.notes.items())),
        }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_semantic_relation_policy(path: str | Path) -> SemanticRelationPolicy:
    """Read and validate the versioned policy file."""
    path = Path(path)
    if not path.is_file():
        raise SemanticPolicyError(f"semantic relation policy not found: {path}")
    raw_text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise SemanticPolicyError(f"{path.name}: {exc}") from exc

    rules: list[TraversalRule] = []
    seen_ids: set[str] = set()
    for entry in payload.get("traversal_rules", ()):
        rule = TraversalRule(
            rule_id=str(entry["rule_id"]),
            predicate_uri=normalize_uri(str(entry["predicate_uri"])),
            direction=str(entry["direction"]),
            relation_kind=str(entry["relation_kind"]),
            description=str(entry.get("description", "")),
        )
        if rule.relation_kind not in RELATION_KINDS:
            raise SemanticPolicyError(
                f"{path.name}: rule {rule.rule_id} declares unknown relation_kind "
                f"{rule.relation_kind!r}; expected one of {RELATION_KINDS}")
        if rule.direction not in ("OUT", "IN"):
            raise SemanticPolicyError(
                f"{path.name}: rule {rule.rule_id} declares direction "
                f"{rule.direction!r}")
        if rule.rule_id in seen_ids:
            raise SemanticPolicyError(
                f"{path.name}: duplicate traversal rule id {rule.rule_id!r}")
        seen_ids.add(rule.rule_id)
        rules.append(rule)

    max_depth = int(payload.get("max_depth", DEFAULT_MAX_DEPTH))
    if max_depth < 1:
        raise SemanticPolicyError(
            f"{path.name}: max_depth must be at least 1, got {max_depth}")

    equivalence = tuple(
        (normalize_uri(str(pair[0])), normalize_uri(str(pair[1])))
        for pair in payload.get("equivalence_pairs", ()))
    disjoint = tuple(
        (normalize_uri(str(pair[0])), normalize_uri(str(pair[1])))
        for pair in payload.get("disjoint_pairs", ()))

    return SemanticRelationPolicy(
        version=str(payload.get("version", "unversioned")),
        max_depth=max_depth,
        traversal_rules=tuple(sorted(rules, key=lambda r: r.rule_id)),
        excluded_predicates={normalize_uri(str(k)): str(v) for k, v
                             in payload.get("excluded_predicates", {}).items()},
        equivalence_source=str(payload.get("equivalence_source", "")),
        equivalence_pairs=equivalence,
        disjointness_source=str(payload.get("disjointness_source", "")),
        disjoint_pairs=disjoint,
        policy_sha256=_sha256_text(raw_text),
        notes={str(k): str(v) for k, v in payload.get("notes", {}).items()},
    )


# --- 3) THE CACHE KEY --------------------------------------------------------

@dataclass(frozen=True)
class SemanticIndexCacheKey:
    """Everything that must match for a cached index to be usable (§5)."""

    pinned_kg_sha256: str
    policy_sha256: str
    source_object_list_sha256: str
    max_depth: int
    creation_command: str

    def as_record(self) -> dict:
        return {
            "pinned_kg_sha256": self.pinned_kg_sha256,
            "policy_sha256": self.policy_sha256,
            "source_object_list_sha256": self.source_object_list_sha256,
            "max_depth": self.max_depth,
            "creation_command": self.creation_command,
        }

    def matches(self, other: "SemanticIndexCacheKey") -> tuple[bool, list[str]]:
        """(usable, list of mismatching fields). `creation_command` is
        provenance, not identity, so it is recorded and not compared."""
        mismatched = [
            name for name in ("pinned_kg_sha256", "policy_sha256",
                              "source_object_list_sha256", "max_depth")
            if getattr(self, name) != getattr(other, name)]
        return (not mismatched, mismatched)


def source_object_list_sha256(uris: Iterable[str]) -> str:
    """A stable digest of the pilot's counterpart-URI set.

    Sorted and newline-joined, so the digest depends on the SET and not on the
    order a caller happened to collect it in.
    """
    payload = "\n".join(sorted({normalize_uri(u) for u in uris}))
    return _sha256_text(payload)


# --- 4) THE INDEX ------------------------------------------------------------

@dataclass(frozen=True)
class AncestorEdge:
    """One traversed edge, kept so a relation can be explained edge by edge."""

    child_uri: str
    parent_uri: str
    rule_id: str
    predicate_uri: str
    relation_kind: str

    def as_record(self) -> dict:
        return {
            "child_uri": self.child_uri,
            "parent_uri": self.parent_uri,
            "rule_id": self.rule_id,
            "predicate_uri": self.predicate_uri,
            "relation_kind": self.relation_kind,
        }


@dataclass(frozen=True)
class SemanticRelationResult:
    """One classified pair, with the evidence that produced it."""

    relation: str
    claim_object_uri: str
    candidate_object_uri: str
    depth: int
    path_rule_ids: tuple[str, ...]
    path_edges: tuple[AncestorEdge, ...]
    available: bool
    note: str = ""

    def as_record(self) -> dict:
        return {
            "relation": self.relation,
            "claim_object_uri": self.claim_object_uri,
            "candidate_object_uri": self.candidate_object_uri,
            "depth": self.depth,
            "path_rule_ids": list(self.path_rule_ids),
            "path_edges": [edge.as_record() for edge in self.path_edges],
            "semantic_relation_available": self.available,
            "note": self.note,
        }


@dataclass(frozen=True)
class SemanticIndex:
    """A bounded parent-child index plus a canonical-equivalence map.

    `parents` maps a normalized URI to the allowlisted edges leaving it toward a
    more general entity. It is the ONLY adjacency this class will walk; a URI
    absent from it simply has no known parent, which is different from having
    none in the world.
    """

    policy: SemanticRelationPolicy
    parents: Mapping[str, tuple[AncestorEdge, ...]]
    equivalence: Mapping[str, str]
    disjoint: frozenset
    cache_key: Optional[SemanticIndexCacheKey]
    available: bool
    unavailable_reason: str = ""
    indexed_object_count: int = 0

    # --- canonical identity ------------------------------------------------
    def canonical(self, uri: str) -> str:
        """Normalized URI, then the local redirect/equivalence representative.

        The equivalence map is a MAPPING to a representative, applied once — not
        a closure. A chain a -> b -> c must be flattened when the map is built,
        which `build_semantic_index` does, so a lookup here cannot loop.
        """
        normalized = normalize_uri(uri)
        return self.equivalence.get(normalized, normalized)

    # --- bounded, cycle-safe ancestor walk ---------------------------------
    def ancestors(self, uri: str) -> dict[str, tuple[int, tuple[AncestorEdge, ...]]]:
        """{ancestor: (depth, path)} within `policy.max_depth`, cycle-safe.

        Breadth-first, so the FIRST time an ancestor is reached is at its minimum
        depth and the recorded path is a shortest one. The `visited` set makes a
        cyclic containment loop terminate rather than recurse: DBpedia infobox
        data is user-edited and does contain place cycles.
        """
        start = self.canonical(uri)
        seen: dict[str, tuple[int, tuple[AncestorEdge, ...]]] = {}
        visited = {start}
        queue: deque = deque([(start, 0, ())])
        while queue:
            node, depth, path = queue.popleft()
            if depth >= self.policy.max_depth:
                continue
            for edge in self.parents.get(node, ()):  # already canonical
                parent = edge.parent_uri
                if parent in visited:
                    continue
                visited.add(parent)
                extended = path + (edge,)
                seen[parent] = (depth + 1, extended)
                queue.append((parent, depth + 1, extended))
        return seen

    def is_descendant_of(self, child_uri: str, ancestor_uri: str
                         ) -> tuple[bool, int, tuple[AncestorEdge, ...]]:
        target = self.canonical(ancestor_uri)
        found = self.ancestors(child_uri).get(target)
        if found is None:
            return (False, 0, ())
        return (True, found[0], found[1])

    # --- the classification -------------------------------------------------
    def classify(self, claim_object_uri: str, candidate_object_uri: str
                 ) -> SemanticRelationResult:
        """Exactly one of the seven §5 relations, with its evidence.

        Order matters and is the order of §5: identity first, then equivalence,
        then the two directed containment relations, then proven disjointness,
        then the two ways of not knowing. EXACT_EQUAL is checked on the
        NORMALIZED URI and CANONICALLY_EQUIVALENT on the representative, so the
        two are never reported as the same finding.
        """
        claim_n = normalize_uri(claim_object_uri)
        cand_n = normalize_uri(candidate_object_uri)
        if claim_n == cand_n:
            return SemanticRelationResult(
                relation=RELATION_EXACT_EQUAL, claim_object_uri=claim_n,
                candidate_object_uri=cand_n, depth=0, path_rule_ids=(),
                path_edges=(), available=True)

        claim_c = self.canonical(claim_n)
        cand_c = self.canonical(cand_n)
        if claim_c == cand_c:
            return SemanticRelationResult(
                relation=RELATION_CANONICALLY_EQUIVALENT,
                claim_object_uri=claim_n, candidate_object_uri=cand_n, depth=0,
                path_rule_ids=(), path_edges=(), available=True,
                note=f"local equivalence source: {self.policy.equivalence_source}")

        if not self.available:
            return SemanticRelationResult(
                relation=RELATION_UNAVAILABLE, claim_object_uri=claim_n,
                candidate_object_uri=cand_n, depth=0, path_rule_ids=(),
                path_edges=(), available=False,
                note=self.unavailable_reason)

        under, depth, path = self.is_descendant_of(cand_c, claim_c)
        if under:
            return SemanticRelationResult(
                relation=RELATION_CANDIDATE_UNDER_CLAIM,
                claim_object_uri=claim_n, candidate_object_uri=cand_n,
                depth=depth, path_rule_ids=tuple(e.rule_id for e in path),
                path_edges=path, available=True)

        over, depth, path = self.is_descendant_of(claim_c, cand_c)
        if over:
            return SemanticRelationResult(
                relation=RELATION_CLAIM_UNDER_CANDIDATE,
                claim_object_uri=claim_n, candidate_object_uri=cand_n,
                depth=depth, path_rule_ids=tuple(e.rule_id for e in path),
                path_edges=path, available=True)

        pair = tuple(sorted((claim_c, cand_c)))
        if pair in self.disjoint:
            return SemanticRelationResult(
                relation=RELATION_PROVEN_DISJOINT, claim_object_uri=claim_n,
                candidate_object_uri=cand_n, depth=0, path_rule_ids=(),
                path_edges=(), available=True,
                note=f"disjointness source: {self.policy.disjointness_source}")

        return SemanticRelationResult(
            relation=RELATION_UNRELATED_OR_UNKNOWN, claim_object_uri=claim_n,
            candidate_object_uri=cand_n, depth=0, path_rule_ids=(),
            path_edges=(), available=True,
            note=("no allowlisted containment path within depth "
                  f"{self.policy.max_depth}; this is a statement about the "
                  "traversed edges, not about the world"))

    def as_record(self) -> dict:
        return {
            "semantic_index_available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "indexed_object_count": self.indexed_object_count,
            "parent_edge_count": sum(len(v) for v in self.parents.values()),
            "nodes_with_parents": len(self.parents),
            "equivalence_entry_count": len(self.equivalence),
            "disjoint_pair_count": len(self.disjoint),
            "cache_key": (None if self.cache_key is None
                          else self.cache_key.as_record()),
            "policy": self.policy.as_record(),
        }


# --- 5) BUILDING AND CACHING -------------------------------------------------

def _flatten_equivalence(pairs: Sequence[tuple[str, str]]) -> dict[str, str]:
    """Resolve source -> target chains to a single representative, cycle-safe.

    A redirect chain a -> b -> c must collapse to a -> c and b -> c, or
    `canonical()` would depend on how many times it was called. A cycle is
    broken by falling back to the lexicographically smallest member, which is
    deterministic and never loops.
    """
    direct = {source: target for source, target in pairs if source != target}
    resolved: dict[str, str] = {}
    for source in sorted(direct):
        seen = [source]
        current = source
        while current in direct:
            current = direct[current]
            if current in seen:
                current = min(seen + [current])
                break
            seen.append(current)
        for member in seen:
            if member != current:
                resolved[member] = current
    return resolved


def build_semantic_index(
    *,
    policy: SemanticRelationPolicy,
    parent_edges: Iterable[AncestorEdge],
    cache_key: Optional[SemanticIndexCacheKey] = None,
    indexed_object_count: int = 0,
) -> SemanticIndex:
    """Assemble an index from already-extracted, allowlisted parent edges.

    The extraction itself lives in the pipeline layer, which is the only place
    permitted to open the pinned KG. This function stays pure so the whole
    semantic layer is testable from fixtures.
    """
    equivalence = _flatten_equivalence(policy.equivalence_pairs)

    def canonical(uri: str) -> str:
        normalized = normalize_uri(uri)
        return equivalence.get(normalized, normalized)

    grouped: dict[str, list[AncestorEdge]] = {}
    for edge in parent_edges:
        if policy.rule_for(edge.predicate_uri) is None:
            raise SemanticPolicyError(
                f"edge {edge.child_uri} -> {edge.parent_uri} uses predicate "
                f"{edge.predicate_uri!r}, which the policy does not allowlist")
        child = canonical(edge.child_uri)
        parent = canonical(edge.parent_uri)
        if child == parent:
            # A self-loop after canonicalization carries no containment.
            continue
        grouped.setdefault(child, []).append(AncestorEdge(
            child_uri=child, parent_uri=parent, rule_id=edge.rule_id,
            predicate_uri=edge.predicate_uri,
            relation_kind=edge.relation_kind))

    parents = {
        child: tuple(sorted(set(edges), key=lambda e: (e.parent_uri, e.rule_id)))
        for child, edges in sorted(grouped.items())}

    disjoint = frozenset(
        tuple(sorted((canonical(a), canonical(b))))
        for a, b in policy.disjoint_pairs)

    return SemanticIndex(
        policy=policy,
        parents=parents,
        equivalence=equivalence,
        disjoint=disjoint,
        cache_key=cache_key,
        available=True,
        unavailable_reason="",
        indexed_object_count=indexed_object_count,
    )


def unavailable_semantic_index(policy: SemanticRelationPolicy,
                               reason: str) -> SemanticIndex:
    """An index that answers SEMANTIC_RELATION_UNAVAILABLE for every walk.

    Canonical equality still works: normalization and the local equivalence map
    do not need the pinned KG, so a missing cache must not silently disable the
    redirect check as well.
    """
    return SemanticIndex(
        policy=policy,
        parents={},
        equivalence=_flatten_equivalence(policy.equivalence_pairs),
        disjoint=frozenset(
            tuple(sorted((normalize_uri(a), normalize_uri(b))))
            for a, b in policy.disjoint_pairs),
        cache_key=None,
        available=False,
        unavailable_reason=reason,
        indexed_object_count=0,
    )


def write_semantic_index_cache(path: str | Path, index: SemanticIndex) -> Path:
    """Serialize a built index, cache key included, deterministically."""
    if index.cache_key is None:
        raise SemanticCacheError(
            "refusing to cache a semantic index with no cache key: a cache "
            "without its key cannot be checked before reuse")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "rationale_v3.semantic_index/1",
        "cache_key": index.cache_key.as_record(),
        "policy_version": index.policy.version,
        "indexed_object_count": index.indexed_object_count,
        "parent_edges": [
            edge.as_record()
            for child in sorted(index.parents)
            for edge in index.parents[child]],
    }
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(payload, f, indent=1, sort_keys=True, ensure_ascii=True)
        f.write("\n")
    return path


def load_semantic_index_cache(path: str | Path, *,
                              policy: SemanticRelationPolicy,
                              expected_key: SemanticIndexCacheKey
                              ) -> SemanticIndex:
    """Load a cached index, or return an UNAVAILABLE one with the reason why.

    Never raises on a stale or missing cache: "the semantic layer had nothing to
    say here" is a result the pilot must be able to report, and turning it into
    an exception would push callers toward ignoring it.
    """
    path = Path(path)
    if not path.is_file():
        return unavailable_semantic_index(
            policy, f"no semantic index cache at {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return unavailable_semantic_index(
            policy, f"semantic index cache unreadable: {exc}")

    raw_key = payload.get("cache_key") or {}
    try:
        found_key = SemanticIndexCacheKey(
            pinned_kg_sha256=str(raw_key["pinned_kg_sha256"]),
            policy_sha256=str(raw_key["policy_sha256"]),
            source_object_list_sha256=str(raw_key["source_object_list_sha256"]),
            max_depth=int(raw_key["max_depth"]),
            creation_command=str(raw_key.get("creation_command", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return unavailable_semantic_index(
            policy, f"semantic index cache key malformed: {exc}")

    usable, mismatched = found_key.matches(expected_key)
    if not usable:
        return unavailable_semantic_index(
            policy,
            f"semantic index cache was built for different inputs "
            f"({', '.join(mismatched)}); it is not reused")

    edges = [
        AncestorEdge(
            child_uri=str(entry["child_uri"]),
            parent_uri=str(entry["parent_uri"]),
            rule_id=str(entry["rule_id"]),
            predicate_uri=str(entry["predicate_uri"]),
            relation_kind=str(entry["relation_kind"]),
        )
        for entry in payload.get("parent_edges", ())]
    return build_semantic_index(
        policy=policy, parent_edges=edges, cache_key=found_key,
        indexed_object_count=int(payload.get("indexed_object_count", 0)))
