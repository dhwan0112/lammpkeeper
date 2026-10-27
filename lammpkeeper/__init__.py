"""
LammpKeeper (lkpr) — unified entry point for the LAMMPS pre/post-processing
CLIs used in the iron-redox MLFF study.

The router delegates to the legacy-named `lammps_pre` and `lammps_post`
packages so installed commands, module entrypoints and old wrapper scripts
reach the same implementation. Shared display, mapping and hosted-shell
utilities now live in `lammpkeeper.common`; correctness changes are recorded
in CHANGELOG.md rather than being hidden behind a package reorganization.
The larger layered migration remains incremental (ADR-0001). This module
must stay dependency-light because packaging reads VERSION without needing
the optional prep/plotting stack.

Subcommands:
    lkpr prep ...   -> lammps_pre.cli.main    (structure & LAMMPS input generation)
    lkpr post ...   -> lammps_post.cli.main   (trajectory analysis & plotting)
"""

# Single source of the version: lammps_pre, lammps_post and pyproject.toml read it.
VERSION = "1.2.0"
