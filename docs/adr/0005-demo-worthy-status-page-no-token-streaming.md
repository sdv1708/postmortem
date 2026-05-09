# Demo-Worthy Status Page Without Token Streaming

The Analysis Run status page is part of the MVP demo surface: it should make the pipeline legible while the user waits by showing human-readable Run Stages such as evidence normalization, timeline extraction, hypothesis generation, citation verification, and postmortem drafting. The MVP will not stream postmortem text token-by-token because partial prose can appear before citations are verified, which would weaken the core evidence-backed claim.
