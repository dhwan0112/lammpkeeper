"""REV-IO-12 (AUDIT-20261104 B-R1): non-increasing dump timesteps warn.

Every time-dependent analysis builds its time axis from frame step numbers.
A concatenated or restarted dump whose steps repeat or go backwards
(0, 100, 50, 50) used to load without any message, so MSD, penetration and
charge time series silently repeated or ran backwards. The streaming and
indexed paths now issue one RuntimeWarning per pass naming the first step that
does not increase; frames are still returned in file order.
"""

import contextlib
import io
import os
import shlex
import tempfile
import warnings

from _util import require_numpy


def _frame(step):
    """Return a two-atom orthogonal frame at `step`."""
    return (f'ITEM: TIMESTEP\n{step}\nITEM: NUMBER OF ATOMS\n2\n'
            'ITEM: BOX BOUNDS pp pp pp\n0 10\n0 10\n0 10\n'
            'ITEM: ATOMS id type x y z\n1 1 0.1 0.2 0.3\n2 1 1.1 1.2 1.3\n')


def _write(steps):
    """Write one frame per step to a temporary dump and return its path."""
    fd, path = tempfile.mkstemp(suffix='.dump')
    with os.fdopen(fd, 'w') as f:
        f.write(''.join(_frame(s) for s in steps))
    return path


def _order_warnings(call):
    """Run `call`; return (result, timestep-order warning texts)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        result = call()
    return result, [str(w.message) for w in caught
                    if issubclass(w.category, RuntimeWarning)
                    and 'not strictly increasing' in str(w.message)]


def _access_paths(path):
    """Return {name: callable returning the loaded timesteps} for each access path."""
    from lammps_post.parsers import DumpReader, LazyFrames, parse_dump
    return {
        'stream': lambda: [f['timestep'] for f in DumpReader(path)],
        'strided stream': lambda: [f['timestep'] for f in DumpReader(path, stride=3)],
        'parse_dump': lambda: [f['timestep'] for f in parse_dump(path)[0]],
        'lazy': lambda: [f['timestep'] for f in LazyFrames(DumpReader(path))],
    }


def test_repeated_and_backward_steps_warn_once_on_every_path():
    require_numpy()
    path = _write([0, 100, 50, 50, 200])
    try:
        for name, call in _access_paths(path).items():
            steps, texts = _order_warnings(call)
            # Frames stay in file order; nothing is dropped or sorted.
            expected = [0, 50] if name == 'strided stream' else [0, 100, 50, 50, 200]
            assert steps == expected, (name, steps)
            assert len(texts) == 1, (name, texts)
            assert 'step 50 follows step 100 (frame 2)' in texts[0], (name, texts)
    finally:
        os.unlink(path)


def test_duplicate_restart_frame_warns():
    require_numpy()
    from lammps_post.parsers import DumpReader
    path = _write([0, 100, 100, 200])
    try:
        _, texts = _order_warnings(lambda: list(DumpReader(path)))
        assert len(texts) == 1 and 'step 100 follows step 100 (frame 2)' in texts[0], texts
        _, texts = _order_warnings(lambda: DumpReader(path).index())
        assert len(texts) == 1 and 'step 100 follows step 100 (frame 2)' in texts[0], texts
    finally:
        os.unlink(path)


def test_increasing_steps_do_not_warn():
    require_numpy()
    for steps in ([0, 10, 20], [5], [0, 1000, 1001]):
        path = _write(steps)
        try:
            for name, call in _access_paths(path).items():
                _, texts = _order_warnings(call)
                assert texts == [], (name, steps, texts)
        finally:
            os.unlink(path)


def test_shell_load_reports_the_warning():
    require_numpy()
    from lammps_post.shell import LammpsPostShell
    path = _write([0, 100, 50])
    try:
        shell = LammpsPostShell()
        shell.noninteractive = True
        with contextlib.redirect_stdout(io.StringIO()):
            _, texts = _order_warnings(lambda: shell.do_load(f'dump {shlex.quote(path)}'))
        assert len(texts) == 1 and 'step 50 follows step 100' in texts[0], texts
        assert [f['timestep'] for f in shell.state.dump_frames] == [0, 100, 50]
    finally:
        os.unlink(path)
