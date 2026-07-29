############################################################################
# src/kg/ — local knowledge-graph access for Journal 2.
#
# Week-1 foundation scope:
#   loader.py      read-only load of an existing pinned pickle; URI<->index;
#                  SHA-256 provenance; schema validation; typed errors.
#   graph_view.py  the M1 graph-budget contract: Answer pinned, candidates
#                  accepted only with their COMPLETE one-hop neighbourhood,
#                  induced edges over the retained nodes.
#
# Deliberately absent in Week 1: sparql_cache.py and entity_types.py. They are
# network-facing (or depend on a module that is) and are not part of this task.
#
# No import-time network access, no pickle rebuilding, no cache creation.
############################################################################

from __future__ import annotations

__all__ = ["loader", "graph_view"]
