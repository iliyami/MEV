"""Paper-2 v2 harness: multi-policy adversary on DAG-based BFT.

This package extends the paper-1 single-policy harness without modifying any
protocol core logic (see /Users/iliya/Dev/Blockchain/CLAUDE.md).

Modules:
    schema   -- v2 YAML schema + validator, backward-compatible with paper 1
    policy   -- per-slot policy-vector materialization from named archetypes
    auditor  -- Invariant Auditor (static + runtime checks)
    sweeper  -- experiment_sweeper_v2 orchestration skeleton
    baselines -- paper-1 reference numbers for contradiction detection
"""
