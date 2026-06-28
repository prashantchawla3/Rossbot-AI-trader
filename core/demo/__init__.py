"""Demo orchestration package — wires the existing engines + Alpaca paper adapters
into a single end-to-end loop for a live demonstration (Alpaca paper trading).

This package is intentionally DEMO-SCOPED and clearly flags every simplification
versus the production spec:
  - E6 (Level-2 support gate) is BYPASSED — Alpaca has no native depth-of-book.
  - Pillar-5 catalyst is NOT verified (no licensed news/NLP feed in the demo) — the
    scanner's Tier-B catalyst gate is replaced by a hard-coded float lookup + RVOL.
  - MARKET_STATE is forced HOT for the demo so the dashboard shows action.

None of these simplifications touch the production strategy/risk modules under
``core/strategy`` or ``core/risk``; the demo path is additive and isolated.

spec: ROSSBOT_STRATEGY_SPEC.md §1 (scanner), §2 (entry), §5/§6 (risk), §3 (exits).
"""
