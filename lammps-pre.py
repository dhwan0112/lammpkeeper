#!/usr/bin/env python3
"""
Backwards-compatible wrapper script.
The actual code now lives in the lammps_pre/ package.

Usage (all equivalent):
    python lammps-pre.py                          # Interactive mode
    python -m lammps_pre                          # Package mode
    python lammps-pre.py --ff ace --preview       # One-shot
    python -m lammps_pre --ff ace --temp 500 --o2 100 --write ./output/
"""
from lammps_pre.cli import main

main()
