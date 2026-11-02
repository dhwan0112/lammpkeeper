"""REV-ANALYSIS-9: compute_rdf(pbc=None) must not override a typed Box's PBC.

Before this fix, the legacy `z_pbc` switch (default False) decided z
periodicity for every orthogonal frame when `pbc=None`, even when the frame's
Box declared resolved flags such as `pp pp pp`. MSD and pair detection already
raise on such disagreement. The maintainer chose (2026-11-01) to raise for RDF
as well. Matching values, unresolved Box flags and legacy frames without a
Box keep the previous behavior.
"""
from unittest.mock import patch
import warnings

import _util

COL = dict(id=0, type=1, x=2, y=3, z=4)
# Two atoms 1.0 Å apart across the periodic z face of a 10 Å box.
POSITIONS = [[5.0, 5.0, 0.5], [5.0, 5.0, 9.5]]


def _frame(pbc):
    """One orthogonal frame; a typed Box with `pbc` flags, or bare bounds if pbc is 'legacy'."""
    import numpy as np
    rows = np.column_stack(([1, 2], [1, 2], np.asarray(POSITIONS, float)))
    frame = dict(atoms=rows, box=np.array([[0, 10.0], [0, 10.0], [0, 10.0]]), timestep=7)
    if pbc != 'legacy':
        from lammpkeeper.io import Box
        frame['cell'] = Box((0, 0, 0), (10, 10, 10), pbc=pbc)
    return [frame]


def _rdf(frames, **kwargs):
    """compute_rdf of the pair with warnings silenced (cutoff warnings are not under test)."""
    from lammps_post.analysis import compute_rdf
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return compute_rdf(frames, COL, 1, 2, r_max=3.0, n_bins=6, **kwargs)


def _raises(call, *needles):
    """Assert ValueError naming every needle."""
    try:
        call()
    except ValueError as exc:
        for needle in needles:
            assert needle in str(exc), f'{needle!r} missing from {exc}'
        return
    raise AssertionError('expected ValueError')


def test_legacy_z_pbc_disagreeing_with_box_pbc_raises():
    """pp pp pp Box with the default z_pbc=False raises and names the fix."""
    _util.require_numpy()
    _raises(lambda: _rdf(_frame((True, True, True))),
            'RDF timestep 7', 'z_pbc=False', '(True, True, True)', 'pbc=')
    _raises(lambda: _rdf(_frame((True, True, False)), z_pbc=True), 'z_pbc=True')
    # x/y non-periodic in the Box also disagrees with the legacy (True, True, ...).
    _raises(lambda: _rdf(_frame((False, True, True)), z_pbc=True), '(False, True, True)')


def test_both_pair_backends_raise():
    """The cKDTree path and the row-wise fallback reject the same disagreement."""
    _util.require_numpy()
    with patch('lammps_post.analysis._rdf_candidate_pairs', return_value=None):
        _raises(lambda: _rdf(_frame((True, True, True))), 'z_pbc=False')


def test_matching_unresolved_and_legacy_frames_keep_previous_results():
    """Agreement, unresolved Box flags and bare bounds behave exactly as before."""
    _util.require_numpy()
    import numpy as np
    periodic = _rdf(_frame((True, True, True)), pbc=(True, True, True))
    open_z = _rdf(_frame((True, True, False)), pbc=(True, True, False))
    # The pair is 1 Å apart only through the z face.
    assert np.count_nonzero(periodic['g']) == 1 and np.count_nonzero(open_z['g']) == 0
    np.testing.assert_array_equal(_rdf(_frame((True, True, True)), z_pbc=True)['g'], periodic['g'])
    np.testing.assert_array_equal(_rdf(_frame((True, True, False)))['g'], open_z['g'])
    np.testing.assert_array_equal(_rdf(_frame(None))['g'], open_z['g'])
    np.testing.assert_array_equal(_rdf(_frame(None), z_pbc=True)['g'], periodic['g'])
    np.testing.assert_array_equal(_rdf(_frame('legacy'))['g'], open_z['g'])
    np.testing.assert_array_equal(_rdf(_frame('legacy'), z_pbc=True)['g'], periodic['g'])
    # An explicit mask that disagrees with the Box was already an error.
    _raises(lambda: _rdf(_frame((True, True, True)), pbc=(True, True, False)), 'disagree')
