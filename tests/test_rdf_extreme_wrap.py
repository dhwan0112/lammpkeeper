"""RDF far-unwrapped coordinates (REV-ANALYSIS-6).

With |x|/L near 2**53 the SciPy candidate wrap lost a pair that the row-wise
fallback counted. Contract: both pair backends give identical g for coordinates
up to 2**45 box lengths from the origin and both raise the same ValueError
(naming the timestep) beyond that, the core.geometry image limit.
"""
from unittest.mock import patch

import numpy as np

import _util


def require(condition, message):
    """Assert, not skip: _util.require raises Skip, which would hide a failure."""
    assert condition, message

COL = dict(id=0, type=1, x=2, y=3, z=4)
TA, TB = 4, 9


def _frame(xa, xb, lo=0.0, length=10.0, step=7):
    """Two atoms (types TA, TB) in a cubic box; xa/xb are 3-vectors."""
    rows = [[1, TA, *xa], [2, TB, *xb]]
    box = np.array([[lo, lo + length]] * 3, dtype=float)
    return dict(atoms=np.array(rows, dtype=float), timestep=step, box=box)


def _both(fr, **kw):
    """Return (SciPy-candidate g, forced fallback g); each may be an exception."""
    from lammps_post import analysis as a

    def run():
        try:
            return a.compute_rdf([fr], COL, type_a=TA, type_b=TB, r_max=4.0,
                                 n_bins=40, **kw)['g']
        except ValueError as exc:
            return exc
    fast = run()
    with patch.object(a, '_rdf_candidate_pairs', return_value=None):
        slow = run()
    return fast, slow


def test_measured_case_rejected_identically():
    """x=0 vs 1e16+2, box [0.5, 10.5]: old SciPy g=0, fallback g>0; now both raise."""
    _util.require_numpy()
    fr = _frame([0.0, 5.0, 5.0], [1e16 + 2.0, 5.0, 5.0], lo=0.5, step=7)
    fast, slow = _both(fr, pbc=(True, False, False))
    for got in (fast, slow):
        require(isinstance(got, ValueError), f'expected ValueError, got {got!r}')
        require('timestep 7' in str(got) and '2**45' in str(got), str(got))
    require(str(fast) == str(slow), 'messages differ between backends')


def test_near_limit_matches_fallback():
    """Just inside 2**45 box lengths, with a nonzero origin, SciPy == fallback."""
    _util.require_numpy()
    length = 10.0
    far = length * 2.0 ** 44
    # Both coordinates are exactly representable here (spacing 2**-9 at 2**47).
    # Atom B sits 2 + 1/8 away from A modulo L, so the pair is inside r_max.
    fr = _frame([far, 5.0, 5.0], [0.125 + 2.0, 5.0, 5.0], lo=0.5)
    fr['atoms'][1, 2] = far + 2.125
    fast, slow = _both(fr, pbc=(True, False, False))
    require(not isinstance(fast, Exception) and not isinstance(slow, Exception),
            f'{fast!r} {slow!r}')
    require(np.array_equal(fast, slow), 'SciPy and fallback g differ near limit')


def test_far_unwrapped_matches_fallback():
    """Coordinates 1e3 box lengths out, with a nonzero origin, agree bitwise."""
    _util.require_numpy()
    rng = np.random.default_rng(6)
    n = 40
    xs = rng.uniform(0, 10, (n, 3)) + 10.0 * rng.integers(-1000, 1000, (n, 3))
    rows = np.column_stack([np.arange(n), np.where(np.arange(n) % 2, TA, TB), xs])
    fr = dict(atoms=rows, timestep=3, box=np.array([[-3.0, 7.0]] * 3))
    fast, slow = _both(fr, pbc=(True, True, True))
    require(np.array_equal(fast, slow), 'SciPy and fallback g differ at 1e3 L')
    require(slow.sum() > 0, 'test needs at least one counted pair')


def test_beyond_image_limit_rejected_identically():
    """Past 2**45 box lengths both backends raise the same error with the step."""
    _util.require_numpy()
    fr = _frame([0.0, 5.0, 5.0], [10.0 * 2.0 ** 46, 5.0, 5.0])
    fast, slow = _both(fr, pbc=(True, True, True))
    for got in (fast, slow):
        require(isinstance(got, ValueError), f'expected ValueError, got {got!r}')
        require('timestep 7' in str(got) and '2**45' in str(got), str(got))
    require(str(fast) == str(slow), 'messages differ between backends')


def test_nonperiodic_axis_is_not_limited():
    """The limit applies to periodic axes only."""
    _util.require_numpy()
    fr = _frame([0.0, 5.0, 5.0], [1.0, 5.0, 5.0 + 10.0 * 2.0 ** 50])
    fast, slow = _both(fr, pbc=(True, True, False))
    require(not isinstance(fast, Exception) and not isinstance(slow, Exception),
            f'{fast!r} {slow!r}')
    require(np.array_equal(fast, slow), 'g differ')
