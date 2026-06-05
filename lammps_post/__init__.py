"""
╔══════════════════════════════════════════════════════════════╗
║  LAMMPS Post-Processing Interactive CLI                      ║
║  Unified analysis for ReaxFF / ACE / HDNNP simulations       ║
╚══════════════════════════════════════════════════════════════╝

A modular, interactive command-line tool that consolidates all
post-processing tasks for LAMMPS molecular dynamics simulations of
iron oxidation systems. Supports three force field families:

  - ReaxFF  : Reactive force field with charge equilibration (QEq).
              Uses 'real' unit system (kcal/mol, Angstrom, fs).
  - ACE     : Atomic Cluster Expansion potential with magnetic spin
              tracking. Uses 'metal' unit system (eV, Angstrom, ps).
  - 4G-HDNNP: Fourth-generation High-Dimensional Neural Network
              Potential. Uses 'metal' unit system.

Package structure:
    lammps_post/
    ├── __init__.py       — Version, shared constants
    ├── __main__.py       — python -m lammps_post support
    ├── display.py        — Terminal output helpers (ANSI colors, tables)
    ├── parsers.py        — File parsers (dump, log, data)
    ├── analysis.py       — Pure analysis functions
    ├── plotting.py       — Plot generation functions
    ├── state.py          — SessionState data container
    ├── shell.py          — Interactive cmd.Cmd shell
    └── cli.py            — Entry point, argparse, flag commands

Usage:
    python -m lammps_post                          # Interactive mode
    python -m lammps_post --dump traj.lammpstrj    # Pre-load dump
    python -m lammps_post --log log.lammps --plot thermo  # One-shot
    python -m lammps_post --batch commands.txt     # Batch mode

Dependencies:
    Required : numpy, matplotlib
    Optional : rich (terminal formatting), pandas (CSV/LaTeX export),
               scipy (fast O2 dissociation via cKDTree),
               MDAnalysis (alternative MSD/RDF computation)
"""

VERSION = "1.2.0"

# ═══════════════════════════════════════════════════════════════
# ── Physical Constants & Unit Conversions ──
# Density conversion: amu/A^3 -> g/cm^3
# Factor = (1 amu in kg) * (1e3 g/kg) / (1 A^3 in cm^3)
#        = 1.660539e-27 * 1e3 / 1e-24 = 1.660539
try:
    from scipy.constants import u as _AMU_KG
    DENSITY_CONVERSION = (_AMU_KG * 1e3) / 1e-24   # amu/A^3 -> g/cm^3
except ImportError:
    DENSITY_CONVERSION = 1.660539  # fallback value

# Pressure unit conversions (from LAMMPS native units)
BAR_TO_GPA = 1e-4           # bar -> GPa (metal units)
ATM_TO_GPA = 1.01325e-4     # atm -> GPa (real units)

# ── Wong 2011 Color-Blind Friendly Palette ──
# (Nature Methods 8, 441, 2011) — recommended for publication figures.
# 8 colors distinguishable by all common forms of color vision deficiency.
WONG_PALETTE = [
    '#000000',  # black
    '#E69F00',  # orange
    '#56B4E9',  # sky blue
    '#009E73',  # bluish green
    '#F0E442',  # yellow
    '#0072B2',  # blue
    '#D55E00',  # vermillion
    '#CC79A7',  # reddish purple
]

# ── cm ↔ inch conversion for journal figure sizes ──
CM_PER_INCH = 2.54
