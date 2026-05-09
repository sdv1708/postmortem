# Experiment Tracking Through Run and Eval Metadata

The MVP will support experiment tracking by recording versioned metadata on Analysis Runs and Evaluation Runs: pipeline version, Prompt Version, model/provider, Retrieval Strategy, Chunking Strategy, verifier version, scenario id, deterministic check results, judge rubric scores, and Warning Code counts.

This is enough to compare prompts and pipeline tradeoffs without building a user-facing A/B testing platform, feature flag system, or experiment management product in the first milestone.
