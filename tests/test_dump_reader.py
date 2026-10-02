"""Guard: DumpReader / parse_dump on synthetic dumps.

Covers the layouts the ACE fixture does not: a type+charge (ReaxFF-style) dump
with no element column, 1- and 0-atom frames, column selection, float32, and
the failure modes (truncated block, layout change) that must raise instead of
silently returning wrong data. Skips cleanly without numpy.
"""
import os
import tempfile

import _util  # noqa: F401  (path bootstrap)
from _util import have_numpy


def _frame(step, rows, cols='id type q x y z', box=((0, 10), (0, 10), (0, 20))):
   head = [
      'ITEM: TIMESTEP', str(step),
      'ITEM: NUMBER OF ATOMS', str(len(rows)),
      'ITEM: BOX BOUNDS pp pp ff',
   ] + [f'{lo} {hi}' for lo, hi in box] + [f'ITEM: ATOMS {cols}']
   return '\n'.join(head + [' '.join(str(v) for v in r) for r in rows]) + '\n'


def _write(text):
   fd, path = tempfile.mkstemp(suffix='.dump')
   with os.fdopen(fd, 'w') as f:
      f.write(text)
   return path


REAX_ROWS = [
   (1, 1, 0.12, 1.0, 2.0, 3.0),
   (2, 2, -0.55, 4.0, 5.0, 6.0),
   (3, 1, 0.40, 7.0, 8.0, 9.5),
]


def _expect_value_error(fn, needle):
   try:
      fn()
   except ValueError as e:
      assert needle in str(e), str(e)
      return
   raise AssertionError(f'expected ValueError mentioning {needle!r}')


def test_type_charge_layout_without_elements():
   if not have_numpy():
      return
   import numpy as np
   from lammps_post.parsers import parse_dump
   path = _write(_frame(0, REAX_ROWS) + _frame(100, REAX_ROWS))
   try:
      frames, columns, col_idx = parse_dump(path)
   finally:
      os.remove(path)
   assert columns == ['id', 'type', 'q', 'x', 'y', 'z']
   assert col_idx == {'id': 0, 'type': 1, 'q': 2, 'x': 3, 'y': 4, 'z': 5}
   assert [f['timestep'] for f in frames] == [0, 100]
   assert frames[0]['elements'] is None
   assert frames[0]['atoms'].dtype == np.float64
   assert np.array_equal(frames[1]['atoms'], np.array(REAX_ROWS, dtype=float))
   assert np.array_equal(frames[0]['box'], [[0, 10], [0, 10], [0, 20]])


def test_single_and_zero_atom_frames_keep_2d_shape():
   if not have_numpy():
      return
   from lammps_post.parsers import parse_dump
   path = _write(_frame(0, REAX_ROWS[:1]) + _frame(1, []))
   try:
      frames, _, _ = parse_dump(path)
   finally:
      os.remove(path)
   assert frames[0]['atoms'].shape == (1, 6)
   assert frames[1]['atoms'].shape == (0, 6)


def test_column_selection_and_float32():
   if not have_numpy():
      return
   import numpy as np
   from lammps_post.parsers import DumpReader
   rows = [(7, 'Fe', 1.5, 2.5, 3.5, 0.1), (9, 'O', 4.5, 5.5, 6.5, 0.2)]
   path = _write(_frame(0, rows, cols='id element x y z vx'))
   try:
      r = DumpReader(path, columns=('element', 'x', 'z', 'no_such_col'), dtype=np.float32)
      frames = list(r)
   finally:
      os.remove(path)
   assert r.raw_columns == ['id', 'element', 'x', 'y', 'z', 'vx']
   assert r.columns == ['x', 'z'] and r.col_idx == {'x': 0, 'z': 1}
   atoms = frames[0]['atoms']
   assert atoms.dtype == np.float32
   assert np.array_equal(atoms, np.array([[1.5, 3.5], [4.5, 6.5]], dtype=np.float32))
   assert list(frames[0]['elements']) == ['Fe', 'O']
   assert frames[0]['elements'].dtype == np.dtype('U2')


def test_stride_and_max_frames():
   if not have_numpy():
      return
   from lammps_post.parsers import DumpReader
   path = _write(''.join(_frame(s, REAX_ROWS) for s in range(10)))
   try:
      assert [f['timestep'] for f in DumpReader(path, stride=3)] == [0, 3, 6, 9]
      assert [f['timestep'] for f in DumpReader(path, stride=3, max_frames=2)] == [0, 3]
      assert len(list(DumpReader(path, max_frames=0))) == 10
   finally:
      os.remove(path)


def test_empty_file_matches_legacy_return():
   if not have_numpy():
      return
   from lammps_post.parsers import parse_dump
   path = _write('')
   try:
      assert parse_dump(path) == ([], [], None)
   finally:
      os.remove(path)


def test_truncated_final_frame_raises():
   if not have_numpy():
      return
   from lammps_post.parsers import parse_dump
   text = _frame(0, REAX_ROWS) + _frame(100, REAX_ROWS)
   path = _write(text.rsplit('\n', 2)[0] + '\n')   # drop the last atom line
   try:
      _expect_value_error(lambda: parse_dump(path), 'step 100')
   finally:
      os.remove(path)


def test_partial_last_line_raises():
   if not have_numpy():
      return
   from lammps_post.parsers import parse_dump
   path = _write((_frame(0, REAX_ROWS)).rstrip('\n')[:-4])  # cut mid-line
   try:
      _expect_value_error(lambda: parse_dump(path), 'step 0')
   finally:
      os.remove(path)


def test_layout_change_raises():
   if not have_numpy():
      return
   from lammps_post.parsers import parse_dump
   rows_xyz = [r[:2] + r[3:] for r in REAX_ROWS]
   path = _write(_frame(0, REAX_ROWS) + _frame(100, rows_xyz, cols='id type x y z'))
   try:
      _expect_value_error(lambda: parse_dump(path), 'column layout changes')
   finally:
      os.remove(path)
