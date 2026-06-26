"""Vendor-agnostic adapter contracts — the spine of the system (plan Phase 0).

No vendor is wired in Phase 0 (OPEN client decision #1). These ABCs let the strategy/risk
core be written against a stable interface; concrete Alpaca/IBKR/Databento adapters arrive in
Phase 1+. The broker contract deliberately exposes NO native STOP order type (U13).
"""
