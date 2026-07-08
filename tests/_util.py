"""Shared helpers for the LammpKeeper regression suite.

Works both under pytest (`pytest tests/`) and with the dependency-free runner
(`python tests/run.py`). Importing this module puts the repo root on sys.path
so `lammpkeeper`, `lammps_pre`, `lammps_post` import cleanly.
"""
import os
import sys
import json
import hashlib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
   sys.path.insert(0, REPO_ROOT)

# Git-tracked ACE example trajectory (element column: Fe/Mn/O, bulk pp pp pp).
FIXTURE = os.path.join(
   REPO_ROOT, 'lammps', 'Runs', 'Archived', 'ACE', 'resources',
   'ACE_Fe-O_examples', 'examples', 'regular_MD', 'traj.dump')


def have_numpy():
   try:
      import numpy  # noqa: F401
      return True
   except ImportError:
      return False


def canon(o):
   """Canonicalize numbers / numpy arrays for a stable fingerprint."""
   import numpy as np
   if isinstance(o, dict):
      return {str(k): canon(v) for k, v in sorted(o.items(), key=lambda x: str(x[0]))}
   if isinstance(o, (list, tuple)):
      return [canon(x) for x in o]
   if isinstance(o, np.ndarray):
      return ['ndarray', list(o.shape),
              [round(float(v), 8) for v in np.asarray(o, float).ravel()]]
   if isinstance(o, (np.floating, float)):
      return round(float(o), 8)
   if isinstance(o, (np.integer, int)):
      return int(o)
   if isinstance(o, (bool, str)) or o is None:
      return o
   return repr(o)


def section_hash(obj):
   """Short sha256 of the canonical JSON of obj (matches the /tmp harness)."""
   return hashlib.sha256(json.dumps(canon(obj), sort_keys=True).encode()).hexdigest()[:16]
