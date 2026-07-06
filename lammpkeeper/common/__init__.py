"""
Shared modules for LammpKeeper (Stage 2 extraction target).

Modules here are the single source of truth for logic that was previously
duplicated between lammps_pre (prep) and lammps_post (post). Extraction is
incremental and behavior-preserving; each module is verified against a
before/after baseline before being committed.

Currently extracted:
    display  — terminal output helpers (was byte-identical in both packages)
"""
