"""RossBot data layer (Phase 1): bar construction + feed-integrity guards.

Pure, vendor-agnostic logic. Vendor wiring (Alpaca / Databento / EDGAR) lives in
``adapters/``; this package consumes the normalized DTOs from ``adapters.base``.
"""
