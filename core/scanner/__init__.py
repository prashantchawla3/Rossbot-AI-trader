"""Two-tier scanner (Phase 1): RVOL engine, float resolver, Five-Pillars gate, sub-scanners.

Pure logic over normalized snapshots (``ScanCandidate``). No vendor or DB imports — the
vendor wiring lives in ``adapters/`` and feeds these functions. Spec §1, §9, §2A.
"""
