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
# Preserve the legacy script path while delegating argument/error handling to
# the same CLI used by `lkpr prep`; a failed batch raises SystemExit there.
from lammps_pre.cli import main

main()
