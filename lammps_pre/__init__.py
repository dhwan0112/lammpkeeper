"""
LAMMPS-PRE: Pre-Processing Interactive CLI
Unified simulation setup for ReaxFF / ACE iron oxidation systems.

Package structure:
    lammps_pre/
    ├── __init__.py       — Version, physical constants
    ├── __main__.py       — python -m lammps_pre support
    ├── display.py        — Terminal output helpers (shared with lammps_post)
    ├── state.py          — PreState data container & FF_PRESETS
    ├── builders.py       — Fe slab, O2 placement, region computation
    ├── writers.py        — LAMMPS data/regions.inc file writers
    ├── templates.py      — Force-field-specific input script renderers
    ├── shell.py          — Interactive cmd.Cmd shell
    └── cli.py            — Entry point, argparse
"""

from lammpkeeper import VERSION  # noqa: F401

# ── Physical Constants ──
A_FE_BCC = 2.87          # BCC Fe lattice constant (Angstrom)
O2_BOND_LENGTH = 1.21    # O-O equilibrium bond length (Angstrom)
MASS_FE = 55.845         # Fe atomic mass (amu)
MASS_O = 15.999          # O atomic mass (amu)
