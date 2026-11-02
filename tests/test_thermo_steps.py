"""REV-IO-5: thermo Step counters must stay exact or be rejected.

LAMMPS steps are signed 64-bit integers, but parse_log stores thermo rows as
float64. From 2**53 on, adjacent counters become the same float: measured on
unmodified code, steps 9007199254740992 and 9007199254740993 both parsed as
9007199254740992.0 with zero elapsed steps and timeline_valid=True. parse_log
now applies the execution layer's rule (application._steps) to every thermo
row: Step must be finite, integral and abs(Step) < 2**53, or the log is
rejected with the file, line and token.
"""
import os
import tempfile
import warnings

import _util


def _log(rows, header='Step Temp'):
    """Write a minimal metal-units log with one thermo block; return its path."""
    fd, path = tempfile.mkstemp(suffix='.lammps')
    with os.fdopen(fd, 'w') as f:
        f.write('units metal\n' + header + '\n' + '\n'.join(rows) +
                '\nLoop time of 1 on 1 procs for 1 steps with 1 atoms\n')
    return path


def _parse(rows, header='Step Temp'):
    """parse_log of the rows, warnings silenced; removes the file."""
    from lammps_post.parsers import parse_log
    path = _log(rows, header)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return parse_log(path), path
    finally:
        os.remove(path)


def _rejects(rows, *needles):
    """parse_log raises ValueError naming the file and every needle."""
    from lammps_post.parsers import parse_log
    path = _log(rows)
    try:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                parse_log(path)
        except ValueError as exc:
            for needle in (path,) + needles:
                assert needle in str(exc), f'{needle!r} missing from {exc}'
            return
        raise AssertionError(f'accepted {rows!r}')
    finally:
        os.remove(path)


def test_counters_at_or_beyond_two_to_the_53_are_rejected():
    """2**53 and 2**53+1 would collapse to one float; the log is rejected instead."""
    _util.require_numpy()
    _rejects(['9007199254740992 300', '9007199254740993 301'], '9007199254740992', '2**53')
    _rejects(['0 300', '9007199254740993 301'], '9007199254740993')
    _rejects(['-9007199254740992 300'], '-9007199254740992')
    _rejects(['1e300 300'], '1e300')


def test_nonintegral_or_nonfinite_steps_are_rejected():
    """A Step must be a whole counter; 10.5, nan and inf are not counters."""
    _util.require_numpy()
    for token in ('10.5', 'nan', 'inf', '-inf'):
        _rejects(['0 300', f'{token} 301'], token)


def test_largest_exact_counters_keep_exact_elapsed_steps():
    """Counters just below 2**53 stay exact; elapsed steps are 0, 1, 2."""
    _util.require_numpy()
    import numpy as np
    top = 2 ** 53 - 1
    data, _ = _parse([f'{top - 2} 300', f'{top - 1} 301', f'{top} 302'])
    assert data['step'].tolist() == [top - 2, top - 1, top]
    assert np.array_equal(data['elapsed_md_steps'], [0, 1, 2])
    assert data['timeline_valid'] is True


def test_ordinary_logs_are_unchanged():
    """Normal counters, negative-free and integral, parse exactly as before."""
    _util.require_numpy()
    data, _ = _parse(['0 300', '10 301', '20 302'])
    assert data['step'].tolist() == [0.0, 10.0, 20.0]
    assert data['elapsed_md_steps'].tolist() == [0.0, 10.0, 20.0]
    assert data['timeline_valid'] is True
    # Exponent notation for an exact integral counter is still accepted.
    data, _ = _parse(['0 300', '1e3 301'])
    assert data['step'].tolist() == [0.0, 1000.0]
