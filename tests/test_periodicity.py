"""Guard: periodicity from the dump's BOX BOUNDS flags.

- parse_boundary_flags / pbc_from_boundary read orthogonal and triclinic
  headers, and return None for a header without flags.
- DumpReader exposes the first frame's flags as `boundary`.
- analyze_msd unwraps only the axes `pbc` marks periodic, and reports frames
  it skips because their atom count changed.
- The shell's _periodicity prefers the dump flags over the input file and the
  surface_z heuristic, and 'analyze msd' / 'analyze rdf' follow it.

Skips cleanly without numpy.
"""
import os
import tempfile

import _util  # noqa: F401  (path bootstrap)
from _util import have_numpy, noninteractive


def _frame(step, rows, bounds='pp pp ff', box=((0, 10), (0, 10), (0, 20))):
    head = [
       'ITEM: TIMESTEP', str(step),
       'ITEM: NUMBER OF ATOMS', str(len(rows)),
       f'ITEM: BOX BOUNDS {bounds}'.rstrip(),
    ] + [f'{lo} {hi}' for lo, hi in box] + ['ITEM: ATOMS id type x y z']
    return '\n'.join(head + [' '.join(str(v) for v in r) for r in rows]) + '\n'


def _write(text):
    fd, path = tempfile.mkstemp(suffix='.dump')
    with os.fdopen(fd, 'w') as f:
        f.write(text)
    return path


def test_boundary_flags_from_header():
    from lammps_post.parsers import parse_boundary_flags, pbc_from_boundary
    assert parse_boundary_flags('ITEM: BOX BOUNDS pp pp ff\n') == ('pp', 'pp', 'ff')
    assert parse_boundary_flags('ITEM: BOX BOUNDS xy xz yz pp pp pp') == ('pp', 'pp', 'pp')
    assert parse_boundary_flags('ITEM: BOX BOUNDS pp pp fs') == ('pp', 'pp', 'fs')
    assert parse_boundary_flags('ITEM: BOX BOUNDS') is None
    assert parse_boundary_flags('ITEM: BOX BOUNDS xy xz yz') is None
    assert pbc_from_boundary(('pp', 'pp', 'ff')) == (True, True, False)
    assert pbc_from_boundary(('pp', 'pp', 'pp')) == (True, True, True)
    assert pbc_from_boundary(('pp', 'fm', 'pp')) == (True, False, True)
    assert pbc_from_boundary(None) is None


def test_dump_reader_exposes_boundary():
    if not have_numpy():
        return
    from lammps_post.parsers import DumpReader
    rows = [(1, 1, 1.0, 2.0, 3.0)]
    for bounds, expected in (('pp pp ff', ('pp', 'pp', 'ff')),
                             ('pp pp pp', ('pp', 'pp', 'pp')),
                             ('', None)):
        path = _write(_frame(0, rows, bounds))
        try:
            assert DumpReader(path).boundary == expected, bounds
        finally:
            os.remove(path)


def _z_crossing_frames():
    """One atom moving +1 A in z per frame across the z boundary of a 10 A cube."""
    import numpy as np
    col_idx = {'id': 0, 'type': 1, 'x': 2, 'y': 3, 'z': 4}
    box = np.array([[0.0, 10.0]] * 3)
    frames = []
    for k, z in enumerate((8.5, 9.5, 0.5, 1.5)):
        atoms = np.array([[1.0, 1.0, 5.0, 5.0, z]])
        frames.append({'timestep': k, 'box': box, 'atoms': atoms})
    return frames, col_idx


def test_msd_unwraps_z_only_when_periodic():
    if not have_numpy():
        return
    import numpy as np
    from lammps_post.analysis import analyze_msd
    frames, col_idx = _z_crossing_frames()
    bulk = analyze_msd(frames, col_idx, pbc=(True, True, True))
    assert np.allclose(bulk['msd'], [0.0, 1.0, 4.0, 9.0])
    # Slab default leaves z alone, so the boundary crossing shows as a jump.
    slab = analyze_msd(frames, col_idx)
    assert np.allclose(slab['msd'], [0.0, 1.0, 64.0, 49.0])


def test_msd_reports_skipped_frames():
    if not have_numpy():
        return
    import numpy as np
    from lammps_post.analysis import analyze_msd
    frames, col_idx = _z_crossing_frames()
    frames[2] = dict(frames[2], atoms=np.vstack([frames[2]['atoms']] * 2))
    result = analyze_msd(frames, col_idx, pbc=(True, True, True))
    # Frame 3 is measured against frame 1: -8 A wraps to +2 A, so z = 3 A.
    assert np.allclose(result['msd'], [0.0, 1.0, 9.0])
    assert result['n_skipped'] == 1
    # No key when nothing was skipped, so existing result hashes are unchanged.
    assert 'n_skipped' not in analyze_msd(_z_crossing_frames()[0], col_idx)


def test_shell_periodicity_prefers_dump_flags():
    if not have_numpy():
        return
    from lammps_post.shell import LammpsPostShell
    rows = [(1, 1, 1.0, 2.0, 3.0), (2, 2, 4.0, 5.0, 6.0)]
    path = _write(_frame(0, rows, 'pp pp pp') + _frame(1, rows, 'pp pp pp'))
    try:
        sh = LammpsPostShell()
        sh.state.output_dir = tempfile.mkdtemp(prefix='lkpr_test_')
        with noninteractive():
            sh.do_load(f'dump {path}')
        s = sh.state
        # The dump says p p p; an input file saying p p f does not override it.
        s.input_config = {'boundary': ['p', 'p', 'f']}
        assert sh._periodicity() == ((True, True, True), 'dump')
        # Without dump flags: input file, then surface_z.
        s.dump_frames.reader.boundary = None
        assert sh._periodicity() == ((True, True, False), 'input')
        s.input_config = None
        s.surface_z = 5.0
        assert sh._periodicity() == ((True, True, False), 'surface_z')
        s.surface_z = None
        assert sh._periodicity() == ((True, True, True), 'surface_z')
    finally:
        os.remove(path)


def _crossing_dump(bounds):
    """Fe (type 1) fixed at z = 1 A; O (type 2) crossing z of a 10 A cube."""
    box = ((0, 10), (0, 10), (0, 10))
    text = ''
    for k, z in enumerate((8.5, 9.5, 0.5, 1.5)):
        rows = [(1, 1, 5.0, 5.0, 1.0), (2, 2, 5.0, 5.0, z)]
        text += _frame(k, rows, bounds, box)
    return _write(text)


def test_shell_msd_and_rdf_follow_dump_flags():
    if not have_numpy():
        return
    import numpy as np
    from lammps_post.shell import LammpsPostShell
    for bounds, msd_o, z_pbc in (('pp pp pp', [0.0, 1.0, 4.0, 9.0], True),
                                 ('pp pp ff', [0.0, 1.0, 64.0, 49.0], False)):
        path = _crossing_dump(bounds)
        try:
            sh = LammpsPostShell()
            sh.state.output_dir = tempfile.mkdtemp(prefix='lkpr_test_')
            with noninteractive():
                sh.do_load(f'dump {path}')
                sh.do_set('types 1=Fe 2=O')
                sh._analyze_msd(['--species', 'O'], _batch=True)
                sh._analyze_rdf(['Fe-O', '--frames', '4'], _batch=True)
            s = sh.state
            assert np.allclose(s.cache['msd_O']['msd'], msd_o), (bounds, s.cache['msd_O'])
            # Fe-O z separations are 7.5, 8.5, 0.5, 0.5 A; across a periodic
            # z they are 2.5 and 1.5 A for the first two frames, so the two
            # z_pbc settings give different g(r).
            from lammps_post.analysis import compute_rdf

            def ref(flag):
                return compute_rdf(s.dump_frames, s.dump_col_idx, 1, 2, max_frames=4,
                                   label_a='Fe', label_b='O', z_pbc=flag)['g']
            got = s.cache['rdf_Fe-O']['g']
            assert np.array_equal(got, ref(z_pbc)), bounds
            assert not np.array_equal(got, ref(not z_pbc)), bounds
        finally:
            os.remove(path)
