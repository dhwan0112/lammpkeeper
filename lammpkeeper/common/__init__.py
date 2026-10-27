"""
Shared modules already extracted for LammpKeeper's incremental migration.

Modules here are the single source of truth for logic that was previously
duplicated between lammps_pre (prep) and lammps_post (post). Extraction is
incremental and behavior-preserving; each module is verified against a
before/after baseline before being committed.

Currently extracted:
    display  — terminal output helpers (was byte-identical in both packages)
    mapping  — canonical per-force-field type<->element convention (was
               duplicated across prep FF_PRESETS, post detect_forcefield, and
               post spin analysis)
    hosted   — child-shell navigation and bounded, opt-out readline history

Keep this initializer free of eager optional imports: importing a lightweight
mapping must not require ASE, matplotlib or Rich.
"""
