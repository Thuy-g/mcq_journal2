############################################################################
# src/selection/
#
# The candidate-ranking and rationale-handoff layer for Journal 2.
#
#   contracts.py         the CandidateRanker interface, the ranking and observed
#                        fact schemas, and the rationale-selection handoff
#   observed_facts.py    the corrected edge-set cache and open-world-safe
#                        serialization of observed one-hop facts
#   lrolesim_handoff.py  the PROPOSED path: `lrolesim_m1_fixed_k3`, an adapter
#                        over the verified Prompt-8C LRoleSim rankings
#   legacy_overlap.py    the RETAINED baseline: `legacy_overlap_baseline`
#
# Nothing is re-exported here. A caller must name the module it depends on, so
# `from selection import ...` can never quietly pull the baseline into the
# proposed path — and importing this package never imports the baseline, which is
# what keeps the proposed path free of SPARQL, spaCy and sentence-transformers.
############################################################################
