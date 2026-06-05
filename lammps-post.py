#!/usr/bin/env python3
"""
Backwards-compatible wrapper script.
The actual code now lives in the lammps_post/ package.

Usage (all equivalent):
    python lammps-post.py                          # Interactive mode
    python -m lammps_post                          # Package mode
    python lammps-post.py --log log.lammps         # Pre-load log
    python -m lammps_post --plot thermo --theme publication  # One-shot
"""
from lammps_post.cli import main

main()
