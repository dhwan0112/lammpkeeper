"""REV-ANALYSIS-3: reject invalid density ranges and bin counts up front."""
import contextlib
import io
from pathlib import Path
import tempfile
import warnings

import _util

COL = {'type': 0, 'z': 1}


def _frame(rows, zlo=0.0, zhi=10.0, side=2.0):
    """Build one orthogonal frame; rows are (arbitrary type ID, z)."""
    import numpy as np
    return {'timestep': 1, 'atoms': np.array(rows, dtype=float),
            'box': np.array([[0, side], [0, side], [zlo, zhi]], dtype=float)}


def _reject(call, *words):
    """Require ValueError whose message names every given word, with no warnings."""
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        try:
            call()
        except ValueError as exc:
            text = str(exc).lower()
            for word in words:
                assert word in text, (word, str(exc))
        else:
            raise AssertionError('invalid density option was accepted')


def _density():
    """Return the function under test."""
    from lammps_post.analysis import compute_density_profile
    return compute_density_profile


def test_degenerate_reversed_and_nonfinite_ranges_reject():
    """Equal, reversed and nonfinite endpoints cannot define bins."""
    _util.require_numpy()
    f = _density()
    frames = [_frame([[7, 1.0]])]
    inf, nan = float('inf'), float('nan')
    for bad in [(1, 1), (3, 1), (nan, 4), (0, nan), (-inf, 4), (0, inf)]:
        _reject(lambda: f(frames, COL, z_range=bad, n_bins=2), 'z_range')


def test_malformed_range_container_rejects():
    """Wrong length, non-numeric and boolean endpoints are range errors."""
    _util.require_numpy()
    f = _density()
    frames = [_frame([[7, 1.0]])]
    for bad in [(1,), (0, 1, 2), 'ab', (0, 'x'), (True, 5), 5]:
        _reject(lambda: f(frames, COL, z_range=bad, n_bins=2), 'z_range')


def test_invalid_bin_counts_reject():
    """Non-integer, bool, zero, negative and nonfinite counts are rejected."""
    _util.require_numpy()
    import numpy as np
    f = _density()
    frames = [_frame([[7, 1.0]])]
    for bad in [0, -3, 2.5, True, np.bool_(True), float('nan'), float('inf'),
                '4', None, 2.0]:
        _reject(lambda: f(frames, COL, z_range=(0, 4), n_bins=bad), 'n_bins')


def test_validation_precedes_frame_iteration():
    """A generator is not consumed when options are invalid."""
    _util.require_numpy()
    f = _density()
    consumed = []

    def frames():
        """Record any attempted consumption."""
        consumed.append(True)
        yield _frame([[7, 1.0]])

    _reject(lambda: f(frames(), COL, z_range=(1, 1), n_bins=2), 'z_range')
    _reject(lambda: f(frames(), COL, z_range=(0, 1), n_bins=0), 'n_bins')
    assert consumed == []


def test_empty_trajectory_still_validates_options():
    """No frames cannot hide a bad explicit range or bin count."""
    _util.require_numpy()
    f = _density()
    _reject(lambda: f([], COL, z_range=(2, 2), n_bins=3), 'z_range')
    _reject(lambda: f([], COL, z_range=(0, 2), n_bins=-1), 'n_bins')


def test_degenerate_automatic_range_rejects():
    """A zero-thickness box is rejected by the shared box guard before binning.

    This already held before REV-ANALYSIS-3 (regression pin); the automatic-range
    check in compute_density_profile is a defensive second line.
    """
    _util.require_numpy()
    f = _density()
    _reject(lambda: f([_frame([[7, 5.0]], zlo=5, zhi=5)], COL, n_bins=2),
            'box', 'positive')


def test_empty_trajectory_without_range_rejects_clearly():
    """No frames and no range is a ValueError, not a TypeError on None."""
    _util.require_numpy()
    _reject(lambda: _density()([], COL, n_bins=2), 'z_range')


def test_valid_profiles_match_analytic_values():
    """Explicit and automatic ranges, numpy ints and types give exact densities."""
    _util.require_numpy()
    import numpy as np
    f = _density()
    # Area 4, two bins of width 5: frame 1 has 2 selected atoms in bin 0 and
    # 1 in bin 1; frame 2 has 0 and 2. Type 9 is excluded.
    frames = [_frame([[7, 1], [7, 4], [7, 6], [9, 2]]),
              _frame([[7, 6], [7, 10], [9, 1]])]
    for kwargs in ({'z_range': (0, 10)}, {}):
        r = f(frames, COL, n_bins=np.int64(2), species_type=7, **kwargs)
        assert np.allclose(r['z'], [2.5, 7.5])
        assert np.allclose(r['density'], [(2 + 0) / 2 / 20, (1 + 2) / 2 / 20])
        assert r['n_frames'] == 2
    # Negative-origin non-degenerate range still works.
    r = f([_frame([[3, -1]], zlo=-2, zhi=2)], COL, z_range=(-2, 2), n_bins=1)
    assert np.allclose(r['density'], [1 / (4 * 4)])


def test_shell_density_reports_failed_command_for_invalid_options():
    """A ValueError from the profile function fails the shell command, no cache."""
    _util.require_numpy()
    import shlex
    from unittest.mock import patch
    from lammps_post import shell as shell_module
    real = shell_module.compute_density_profile
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'slab.dump'
        path.write_text(
            'ITEM: TIMESTEP\n10\nITEM: NUMBER OF ATOMS\n1\n'
            'ITEM: BOX BOUNDS pp pp ff\n0 10\n0 10\n0 10\n'
            'ITEM: ATOMS id type element x y z\n1 1 Fe 1 1 5\n')
        shell = shell_module.LammpsPostShell()
        shell.state.output_dir = tmp
        with contextlib.redirect_stdout(io.StringIO()):
            shell.onecmd(f'load dump {shlex.quote(str(path))}')
        assert shell.last_command_ok is True
        shell.command_failures = 0

        def bad_options(*args, **kwargs):
            """Forward to the real function with an invalid bin count."""
            kwargs['n_bins'] = 0
            return real(*args, **kwargs)

        with patch.object(shell_module, 'compute_density_profile', bad_options):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                shell.onecmd('analyze density')
        assert shell.last_command_ok is False, out.getvalue()
        assert shell.command_failures == 1
        assert 'n_bins' in out.getvalue(), out.getvalue()
        assert not any(k.startswith('density_') for k in shell.state.cache)
