############################################################################
# src/rationale/ — the Journal-2 rationale layer.
#
# INDEPENDENT OF LRoleSim BY CONSTRUCTION
#   AUDIT_Journal2_v2_2026-07-26 §9.2 fixes the boundary: "kiểm tra tồn tại
#   rationale" belongs to `rationale/setcover.py` and NOT to `lrolesim/` or
#   `selection/`, and "tuyệt đối không thêm hàm sinh rationale vào
#   MCQ_lrolesim*.py". Nothing in this package imports the LRoleSim kernel, the
#   adapter, the graph layer or the selection layer, so no reviewer can read this
#   code as a change to the LRoleSim definition (CLAUDE.md items 2-5).
#
#   LRoleSim scores enter this package only as opaque floats read from the frozen
#   Prompt-8D handoff, used for ordering and never recomputed.
#
# WHAT THIS PACKAGE DOES
#   contracts.py   the frozen vocabulary: object-set relations, evidence statuses,
#                  the two evidence policies, coverage and selection statuses.
#   contrasts.py   set-aware observed contrast — object sets per
#                  (predicate_uri, direction) key, their relation, and the
#                  per-fact evidence status against one candidate.
#   setcover.py    exact minimum-cardinality rationale set cover, O(m * 2^k).
#   selector.py    exact search over every k-candidate combination, deterministic
#                  selection, partial diagnostics and the rho ablation.
#
# OPEN-WORLD DISCIPLINE
#   Everything here describes the PINNED KG SNAPSHOT. No function in this package
#   emits a negative fact, and there is no code path that can express "the
#   candidate does not have this fact" as a claim about the world. DBpedia is
#   open-world (CLAUDE.md item 7): a triple absent from the dump is absent, not
#   false. Every selection this package makes carries requires_human_validation.
#
# OFFLINE AND PURE
#   No network, no SPARQL, no spaCy, no SBERT, no abstracts, no class selection,
#   no graph construction, no pinned-pickle load. Dataclasses, integers and
#   deterministic sorting only.
############################################################################

from __future__ import annotations

__all__ = ["contracts", "contrasts", "setcover", "selector"]
