"""REV-IO-8: parser edge cases must be rejected or handled visibly.

Covers three audit findings: thermo headers that normalize to one key,
density profiles on cell-only frames or empty trajectories, and dump frame
detection that must agree between streaming and the index path.
"""

from pathlib import Path
import tempfile
import warnings

import _util  # noqa: F401
from _util import require_numpy


def require(cond, msg=''):
    """Fail the test (never skip) when cond is false."""
    assert cond, msg

LOG_TMPL = """units metal
timestep 0.001
run 100
{header}
{row0}
{row1}
Loop time of 1.0 on 1 procs for 10 steps with 4 atoms
"""


def _write_log(tmp, header, ncols):
    """Write a two-row single-block log with the given thermo header."""
    path = Path(tmp) / 'log.lammps'
    path.write_text(LOG_TMPL.format(
        header=header, row0=' '.join(str(i) for i in range(ncols)),
        row1=' '.join(str(i + 10) for i in range(ncols))))
    return path


def test_log_colliding_headers_are_rejected():
    """Pairs normalizing to one key raise, naming file, block and both headers."""
    require_numpy()
    from lammps_post.parsers import parse_log
    cases = ['Step Temp c_temp_mobile', 'Step Press Pressure', 'Step Vol Volume',
             'Step Temp Temp', 'Step PotEng pe']
    for header in cases:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_log(tmp, header, 3)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    parse_log(str(path))
            except ValueError as exc:
                msg = str(exc)
                a, b = header.split()[1:]
                require(str(path) in msg and repr(a) in msg and repr(b) in msg
                        and 'block' in msg, f'{header}: {msg}')
            else:
                raise AssertionError(f'{header}: collision was accepted')


def test_log_distinct_headers_keep_their_keys():
    """Non-colliding aliases keep the legacy keys and values."""
    require_numpy()
    from lammps_post.parsers import parse_log
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_log(tmp, 'Step c_temp_mobile Pressure Volume PotEng', 5)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            r = parse_log(str(path))
    require(list(r['temp']) == [1, 11] and list(r['press']) == [2, 12]
            and list(r['vol']) == [3, 13] and list(r['pe']) == [4, 14], 'keys changed')


def _density():
    """Import the function under test."""
    from lammps_post.analysis import compute_density_profile
    return compute_density_profile


def _cell_frames():
    """Return (frame with box, same frame carrying only a 'cell' Box)."""
    import numpy as np
    from lammpkeeper.io import Box
    bounds = np.array([[0, 2.0], [0, 3.0], [0, 10.0]])
    atoms = np.array([[1, 1.0], [1, 4.0], [1, 6.0]])
    with_box = {'timestep': 1, 'atoms': atoms, 'box': bounds}
    cell = Box(bounds[:, 0], bounds[:, 1])
    return with_box, {'timestep': 1, 'atoms': atoms, 'cell': cell}


def test_density_cell_only_frame_equals_box_frame():
    """A frame with a 'cell' and no 'box' key gives the same profile, auto and explicit range."""
    require_numpy()
    import numpy as np
    col = {'type': 0, 'z': 1}
    with_box, cell_only = _cell_frames()
    for kwargs in ({}, {'z_range': (0, 10)}):
        a = _density()([with_box], col, n_bins=4, **kwargs)
        b = _density()([cell_only], col, n_bins=4, **kwargs)
        require(np.array_equal(a['density'], b['density'])
                and np.array_equal(a['z'], b['z']) and a['n_frames'] == b['n_frames'], str(kwargs))


def test_density_empty_trajectory_with_range_warns():
    """Zero frames with an explicit range warns visibly and keeps n_frames=0."""
    require_numpy()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        r = _density()([], {'type': 0, 'z': 1}, z_range=(0, 10), n_bins=2)
    require(r['n_frames'] == 0, 'n_frames')
    require(any('no frames' in str(w.message) for w in caught), 'no warning')


def _dump_text(rows_by_frame):
    """Serialize frames of 'id type element x y z' rows with raw row strings."""
    out = []
    for step, rows in enumerate(rows_by_frame):
        out += ['ITEM: TIMESTEP', str(step), 'ITEM: NUMBER OF ATOMS', str(len(rows)),
                'ITEM: BOX BOUNDS pp pp pp', '0 10', '0 10', '0 10',
                'ITEM: ATOMS id type element x y z', *rows]
    return '\n'.join(out) + '\n'


def _read_all(text, force_numpy):
    """Return ('ok', frames) or ('error', ...) for streaming and index paths."""
    from lammps_post import parsers
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'd.dump'
        path.write_text(text)
        results = {}
        for mode in ('stream', 'index'):
            reader = parsers.DumpReader(path)
            if force_numpy:
                reader._native = None
            try:
                if mode == 'stream':
                    frames = list(reader)
                else:
                    try:
                        idx = reader.index()
                    except ValueError:
                        # Indexing validates headers only; a failure here means
                        # frame boundaries were misdetected.
                        results[mode] = ('index-error', None)
                        continue
                    frames = [reader.read_frame(idx, k) for k in range(len(idx.timesteps))]
                results[mode] = ('ok', [(f['timestep'], f['atoms'].tolist()) for f in frames])
            except ValueError:
                results[mode] = ('error', None)
        return results


def _backends():
    """Yield (name, force_numpy); native only when loaded, else a visible note."""
    from lammps_post import parsers
    yield 'numpy', True
    if parsers._native is not None:
        yield 'native', False
    else:
        print('NOTE: native dump parser unavailable; native half skipped')


def test_dump_index_and_stream_agree_on_marker_text_in_rows():
    """Marker text inside an atom row must not split a frame in the index path."""
    require_numpy()
    good = ['1 1 Fe 1 2 3', '2 2 O 4 5 6']
    texts = {
        'valid': _dump_text([good, good]),
        'mid-line': _dump_text([['1 1 ITEM: TIMESTEP 1 2 3', '2 2 O 4 5 6'], good]),
        'line-start prefix': _dump_text([['ITEM: TIMESTEPX 1 2 3', '2 2 O 4 5 6'], good]),
    }
    for name, text in texts.items():
        outcomes = {}
        for backend, force in _backends():
            res = _read_all(text, force)
            require(res['stream'] == res['index'], f'{name}/{backend}: {res}')
            outcomes[backend] = res['stream']
        require(len(set(map(repr, outcomes.values()))) == 1, f'{name}: backends differ')
        if name == 'valid':
            require(outcomes['numpy'][0] == 'ok' and len(outcomes['numpy'][1]) == 2, 'valid')
        else:
            require(outcomes['numpy'][0] == 'error', f'{name}: malformed row accepted')
