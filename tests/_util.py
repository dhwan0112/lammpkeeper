"""Shared helpers for the LammpKeeper regression suite.

Works both under pytest (`pytest tests/`) and with the dependency-free runner
(`python tests/run.py`). Importing this module puts the repo root on sys.path
so `lammpkeeper`, `lammps_pre`, `lammps_post` import cleanly.
"""
import io
import os
import sys
import json
import hashlib
import contextlib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
   sys.path.insert(0, REPO_ROOT)

# Git-tracked ACE example trajectory (element column: Fe/Mn/O, bulk pp pp pp).
# Shipped under tests/fixtures/ from the ACE Fe-O potential's own examples.
FIXTURE = os.path.join(
   REPO_ROOT, 'tests', 'fixtures', 'ace_examples', 'regular_MD', 'traj.dump')


def have_numpy():
   try:
      import numpy  # noqa: F401
      return True
   except ImportError:
      return False


@contextlib.contextmanager
def noninteractive():
   """Silence stdout and make stdin look empty.

   `LammpsPostShell.do_load` calls `_suggest_output_dir`, which prompts via
   `input()`. `_ask` treats EOF as "use the default", so an empty stdin keeps
   the shell on its default path. pytest replaces sys.stdin with an object that
   raises OSError instead of EOFError, so the tests must supply their own.
   """
   saved = sys.stdin
   sys.stdin = io.StringIO('')
   try:
      with contextlib.redirect_stdout(io.StringIO()):
         yield
   finally:
      sys.stdin = saved


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
