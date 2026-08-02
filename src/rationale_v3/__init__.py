############################################################################
# src/rationale_v3/__init__.py
#
# Journal-2 rationale layer, VERSION 3.
#
# WHAT THIS PACKAGE IS FOR
#   Turning the frozen Prompt-8D observations into a rationale that is
#   scientifically defensible and pedagogically usable:
#
#     contracts.py           the frozen vocabulary — evidence levels, reason
#                            codes, policies, proof and proposition types
#     semantic_relations.py  canonical equality plus a bounded, allowlisted,
#                            cycle-safe parent-child closure
#     evidence.py            L0 / L1 / L2 assignment, scoped rules, L2 proofs
#     quality.py             hard predicate/object filters, lexical Answer
#                            leakage, display labels, pedagogical ordering
#     setcover.py            exact minimum-cardinality bitmask DP and complete
#                            enumeration of the equally smallest rationales
#     selector.py            evidence tiers, the combination objective, the
#                            scalable exact / pool-exact search
#     policies/              versioned JSON: predicates, evidence rules,
#                            semantic relations
#
# RELATIONSHIP TO PROMPT 8E
#   `src/rationale/` is NOT modified and NOT imported from here. Prompt 8E stays
#   an executable frozen baseline that can be re-run and byte-compared, which is
#   what makes the V3-versus-8E comparison meaningful.
#
# WHAT THIS PACKAGE NEVER DOES
#   No HTTP, no SPARQL, no Wikidata, no DBpedia endpoint or abstracts, no spaCy,
#   no SBERT, no LLM, no class selection, no graph construction, no LRoleSim
#   computation. LRoleSim scores are READ from the frozen Prompt-8D handoff;
#   Journal 2 applies LRoleSim as a structural plausibility ranker and does not
#   change its definition (CLAUDE.md items 2 and 3).
#
# OPEN WORLD
#   L0 is an observation about one snapshot, never a negative fact. L1 is valid
#   inside a declared scope, never universal. Only L2 asserts exclusion, and only
#   with a proof object (CLAUDE.md items 7 and 8).
############################################################################

from __future__ import annotations

VERSION = "rationale_v3/1.0.0"

__all__ = [
    "VERSION",
    "contracts",
    "semantic_relations",
    "evidence",
    "quality",
    "setcover",
    "selector",
]
