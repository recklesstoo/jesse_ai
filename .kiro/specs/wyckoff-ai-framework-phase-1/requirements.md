# Wyckoff AI Framework - Phase 1 Requirements

## Goal
Deliver the first Wyckoff + AI signal pipeline on top of the Phase 0 data flow.

## Functional Requirements
1. Detect Wyckoff market phases (accumulation, markup, distribution, markdown).
2. Generate basic Wyckoff signals (spring, upthrust, sign of strength/weakness).
3. Expose signals via backend endpoint and surface them in the dashboard.
4. Allow manual review and optional auto-order routing for AI signals.

## Non-Functional Requirements
1. Signal latency under 200ms after new bar ingestion.
2. Traceability: every signal must reference the bar(s) that triggered it.
3. Configurable thresholds for volume/price deltas.

## Out of Scope (Phase 1)
- Full ML models and hyperparameter optimization.
- Multi-asset portfolio allocation.
