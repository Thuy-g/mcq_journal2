############################################################################
# src/pipeline/__init__.py
#
# The Week-2 integration layer: frozen local candidate mappings -> deterministic
# candidate ordering -> M1 graph-budget policy -> fixed-iteration LRoleSim.
#
# This package ORCHESTRATES modules that already exist. It owns no mathematics
# and no retrieval:
#   * candidate mappings come from the frozen Week-1 outputs;
#   * the graph budget is src/kg/graph_view.py;
#   * the ranker is src/lrolesim/adapter.py over src/MCQ_lrolesim_ClaudeWeb_v2.py;
#   * the approved class list is src/classes/policy.py.
#
# Nothing here reaches the network, and nothing here selects final distractors,
# builds rationales or verbalizes an MCQ.
############################################################################

from __future__ import annotations

__all__ = ["candidate_order", "graph_lrolesim_run"]
