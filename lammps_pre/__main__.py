"""Run ``python -m lammps_pre`` through the same CLI as the legacy launcher.

The CLI raises SystemExit on noninteractive command failure, so this entry
point does not need to translate a returned status code.
"""
from lammps_pre.cli import main

main()
