"""RDF precision contract (REV-ANALYSIS-4): float32 input positions.

Position arrays may be float32 (native parser / user frames). The RDF must
evaluate displacements, minimum image and the cutoff comparison in float64 on
the *represented* input values, so the SciPy candidate path and the row-wise
fallback agree and match an exact-rational oracle at the cutoff edge.
"""
import os
from fractions import Fraction
from unittest.mock import patch

import numpy as np

import _util  # noqa: F401
from _util import require

COL = dict(id=0, type=1, x=2, y=3, z=4)
# Arbitrary type IDs, so no hardcoded species numbering can pass by accident.
TA, TB = 4, 9


def _frame(rows, dtype, lo=-50.0, length=100.0):
    """Build a cubic-box frame whose atom array has the requested dtype."""
    box = np.array([[lo, lo + length]] * 3, dtype=float)
    return dict(atoms=np.asarray(rows, dtype=dtype), timestep=0, box=box)


def _fast_and_fallback(fr, **kw):
    """Return (SciPy-candidate g, forced row-wise-fallback g); fast is None without SciPy."""
    from lammps_post import analysis as a
    fast = None
    try:
        import scipy  # noqa: F401
        fast = a.compute_rdf([fr], COL, type_a=TA, type_b=TB, **kw)['g']
    except ImportError:
        pass
    with patch.object(a, '_rdf_candidate_pairs', return_value=None):
        slow = a.compute_rdf([fr], COL, type_a=TA, type_b=TB, **kw)['g']
    return fast, slow


def _edge_case():
    """Two float32 atoms straddling the periodic cutoff; returns frame, kwargs, exact distance."""
    fr = _frame([[1, TA, -49.95, 0, 0], [2, TB, 49.15, 0, 0]], np.float32)
    p, q = (Fraction(float(v)) for v in fr['atoms'][:, 2])
    # Fractions of the represented float32 values: exact, independent of production.
    exact = Fraction(100) - (q - p)
    cutoff = 0.8999958038330078
    assert exact > Fraction(cutoff)   # true distance is outside the cutoff
    kw = dict(r_max=cutoff, n_bins=1, pbc=(True, False, False))
    return fr, kw


def test_float32_cutoff_edge_fallback_matches_exact_oracle():
    """Row-wise fallback must reject a pair whose exact MIC distance exceeds r_max."""
    fr, kw = _edge_case()
    _, slow = _fast_and_fallback(fr, **kw)
    assert slow[0] == 0.0, slow


def test_float32_cutoff_edge_scipy_equals_fallback():
    """SciPy candidate path and forced fallback agree on the float32 edge pair."""
    require(__import__('importlib').util.find_spec('scipy') is not None,
            'scipy not installed (fast-path assertion)')
    fr, kw = _edge_case()
    fast, slow = _fast_and_fallback(fr, **kw)
    assert fast[0] == 0.0 and np.array_equal(fast, slow), (fast, slow)


def test_float32_equals_float64_cast_of_same_values():
    """float32 input gives the same g as the same represented values stored as float64."""
    fr, kw = _edge_case()
    fr64 = dict(fr, atoms=fr['atoms'].astype(np.float64))
    for f32, f64 in zip(_fast_and_fallback(fr, **kw), _fast_and_fallback(fr64, **kw)):
        if f32 is not None:
            assert np.array_equal(f32, f64), (f32, f64)


def test_float32_inside_cutoff_counts_pair():
    """A float32 pair whose exact MIC distance is inside r_max is counted by both paths."""
    fr, kw = _edge_case()
    kw = dict(kw, r_max=0.9000001)   # just above the exact 0.89999771...
    fast, slow = _fast_and_fallback(fr, **kw)
    assert slow[0] > 0.0
    if fast is not None:
        assert np.array_equal(fast, slow)


def test_float32_random_frames_scipy_equals_fallback_and_float64():
    """Random float32 frames: both paths bitwise equal to each other and to float64 cast."""
    require(__import__('importlib').util.find_spec('scipy') is not None,
            'scipy not installed (fast-path assertion)')
    rng = np.random.RandomState(7)
    n = 60
    pos = rng.uniform(-50, 50, size=(n, 3))
    types = rng.choice([TA, TB], size=n)
    rows = np.column_stack([np.arange(n), types, pos])
    fr = _frame(rows, np.float32)
    fr64 = dict(fr, atoms=fr['atoms'].astype(np.float64))
    kw = dict(r_max=9.0, n_bins=30, pbc=(True, True, False))
    fast, slow = _fast_and_fallback(fr, **kw)
    fast64, slow64 = _fast_and_fallback(fr64, **kw)
    assert np.array_equal(fast, slow)
    assert np.array_equal(fast, fast64) and np.array_equal(slow, slow64)
    assert fast.sum() > 0
