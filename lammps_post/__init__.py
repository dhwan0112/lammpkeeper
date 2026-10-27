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
    Required : numpy
    Optional : matplotlib (plots), rich (terminal formatting), pandas (CSV/LaTeX export),
               scipy (fast O2 dissociation via cKDTree),
                MDAnalysis (alternative MSD/RDF computation)

This legacy namespace remains the constants/import surface for post-processing.
The values below are unit conversions or Fe-O analysis defaults, not metadata
inferred from a particular run. Callers must still supply that run's native
units, timestep and species mapping.
"""

# Re-export the canonical version so legacy entry points agree with lkpr.
from lammpkeeper import VERSION  # noqa: F401

# ═══════════════════════════════════════════════════════════════
# ── Physical Constants & Unit Conversions ──
# Density conversion: amu/A^3 -> g/cm^3
# Factor = (1 amu in kg) * (1e3 g/kg) / (1 A^3 in cm^3)
#        = 1.660539e-27 * 1e3 / 1e-24 = 1.660539
_AMU_KG = 1.66053906660e-27                    # CODATA 2018 atomic mass constant
DENSITY_CONVERSION = (_AMU_KG * 1e3) / 1e-24   # amu/A^3 -> g/cm^3

# Pressure unit conversions (from LAMMPS native units)
BAR_TO_GPA = 1e-4           # bar -> GPa (metal units)
ATM_TO_GPA = 1.01325e-4     # atm -> GPa (real units)

# ── Analysis thresholds (Fe-O oxidation) ──
# Suffixes encode dimensions: _E is elementary charge and _A is Angstrom.
# These empirical domain thresholds must not be treated as universal criteria
# for other chemistries or as integer oxidation-state assignments.
# Partial charge above which an Fe atom counts as oxidized: metallic Fe sits
# near 0 e, Fe2+ at ~0.8-1.2 e and Fe3+ at ~1.2-1.8 e (ReaxFF QEq charges).
Q_OXIDIZED_E = 0.3
# Surface plane = topmost Fe z minus about half the BCC Fe lattice constant
# (2.87 A / 2), i.e. between the top Fe layer and the gas phase.
SURFACE_OFFSET_A = 1.4
# Half-width of the near-surface reaction zone; O deeper than this below
# the surface counts as absorbed.
NEAR_SURFACE_A = 3.0
# O-O distance below which two O atoms count as bonded (O2 bond ~1.21 A).
O2_BOND_CUTOFF_A = 1.8

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
