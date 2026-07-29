############################################################################
# src/lrolesim/ — thin adapter over the LRoleSim kernel.
#
# CLAUDE.md non-negotiable boundary 2: Journal 2 APPLIES or INTEGRATES LRoleSim
# as a structural plausibility ranker. This package therefore contains no
# mathematics of its own. It pins the published configuration
# (measure = lrolesim_ed, lrolesim_beta = 0.2, iterations = 3) and calls the
# kernel in src/MCQ_lrolesim_ClaudeWeb_v2.py.
#
# The definition of LRoleSim is unchanged, so nothing here is re-proved and no
# extension of Journal 1's mathematics is claimed.
#
# No import-time network access, no model download, no ranking at import time.
############################################################################

from __future__ import annotations

__all__ = ["adapter"]
