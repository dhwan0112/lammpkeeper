"""
Terminal display helpers.

Stage 2: the implementation moved to `lammpkeeper.common.display` (it was
byte-identical in lammps_pre and lammps_post). This module is kept as a
backward-compatible re-export so existing imports
(`from lammps_post.display import C, progress_msg, print_table, print_kv, HAS_RICH`)
and the `python -m lammps_post` / `lammps-post.py` entry points keep working
unchanged. The single source of truth now lives in
lammpkeeper/common/display.py.
"""
from lammpkeeper.common.display import (  # noqa: F401
   C,
   HAS_RICH,
   print_table,
   print_kv,
   progress_msg,
)

__all__ = ['C', 'HAS_RICH', 'print_table', 'print_kv', 'progress_msg']
