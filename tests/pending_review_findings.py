"""Staging area for known-failing BACKLOG reproductions (not collected).

The original 2026-10-20 repros have been moved into registered test modules:
- PHYS-2/PHYS-1: tests/test_msd.py (initial IDs and explicit per-axis PBC).
- PHYS-3: tests/test_o2_periodicity.py (periodic candidate search).
- PHYS-5: tests/test_o2_pairing.py (backend-independent global pairing).

Run tests/run.py to execute them. An empty staging area is not evidence that
all physics is correct: remaining limitations are recorded in BACKLOG.md.
New findings may be staged here, then moved into a collected test_*.py module
registered in tests/run.py when fixed. Keep fixtures and goldens unchanged
unless their separate human gates are satisfied.
"""
