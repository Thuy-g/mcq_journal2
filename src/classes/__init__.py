############################################################################
# src/classes/ — approved-class policy and first-feasible class selection.
#
# Journal 2 Week-1 foundation. This package owns ONE question: which class is
# a run allowed to draw distractor candidates from, for a given Answer.
#
# It never invents a class. The approved list is human-approved data
# (data/pilot_class_policy_v1.{csv,json}); the code only parses, validates and
# walks it in order. See src/classes/policy.py.
#
# No import-time network access, no ranking, no cache creation.
############################################################################

from __future__ import annotations

__all__ = ["policy"]
