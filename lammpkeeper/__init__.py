"""
LammpKeeper (lkpr) — unified entry point for the LAMMPS pre/post-processing
CLIs used in the iron-redox MLFF study.

Stage 1 (dispatcher-only integration): `lkpr` routes to the existing
`lammps_pre` (prep) and `lammps_post` (post) packages *unchanged*. Their
numeric behavior and physics are preserved exactly; only a top-level
subcommand router is added. Physical reorganization into prep/, post/,
common/ and any shared-module extraction are deferred to Stage 2, together
with regression baselines.

Subcommands:
    lkpr prep ...   -> lammps_pre.cli.main    (structure & LAMMPS input generation)
    lkpr post ...   -> lammps_post.cli.main   (trajectory analysis & plotting)
"""

VERSION = "0.1.0"
