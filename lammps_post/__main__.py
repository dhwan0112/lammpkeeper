#!/usr/bin/env python3
"""
Execute the legacy ``python -m lammps_post`` entry point.

Keep argument parsing and exit-status ownership in cli.main so module execution
and the external script shim use the same workflow. Importing this entry-point
module intentionally launches main; it is not a reusable helper module.
"""
from lammps_post.cli import main

main()
