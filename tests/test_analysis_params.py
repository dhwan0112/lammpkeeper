"""REV-ANALYSIS-8: invalid analysis parameters must raise before any frame is read.

Each public analysis function that takes a physical parameter (timestep, surface
plane, charge threshold, z range, bin count, smoothing window) rejects NaN, inf,
reversed ranges, bools and non-integer counts with a ValueError that names the
parameter. The check runs first: the frame container used for rejection raises
AssertionError if it is iterated, indexed or measured. Valid calls are pinned to
hand calculations on a two-frame system with arbitrary type IDs.
"""

import _util

COL = dict(id=0, type=1, q=2, x=3, y=4, z=5)
NAN, INF = float('nan'), float('inf')


class _Unread(list):
    """Frame container that fails the test if any frame access is attempted."""

    def __iter__(self):
        """Fail: iteration means a frame was read before validation."""
        raise AssertionError('a frame was read before parameter validation')

    def __len__(self):
        """Fail: len() means the frames were measured before validation."""
        raise AssertionError('frames were measured before parameter validation')

    def __getitem__(self, item):
        """Fail: indexing means a frame was read before validation."""
        raise AssertionError('a frame was read before parameter validation')


def _frames():
    """Two identical orthogonal frames at steps 0 and 400 (10 A cube).

    Rows are [id, type, q, x, y, z]: type 1 metal with q 0.5 at z 2 and q 0.1 at
    z 8; type 2 gas at z 1 and z 9 (x 1.0 and 2.2, a 1.2 A pair).
    """
    import numpy as np
    atoms = np.array([[1, 1, 0.5, 5.0, 5.0, 2.0],
                      [2, 1, 0.1, 6.0, 5.0, 8.0],
                      [3, 2, 0.0, 1.0, 1.0, 1.0],
                      [4, 2, 0.0, 2.2, 1.0, 9.0]])
    box = np.array([(0.0, 10.0)] * 3)
    return [dict(timestep=s, atoms=atoms.copy(), box=box.copy()) for s in (0, 400)]


def _spin_frames():
    """Two frames with types 1, 2, 3 (ACE spin labels): 2 up, 1 down, 1 O."""
    import numpy as np
    atoms = np.array([[1, 1, 0, 0, 0, 1.0], [2, 1, 0, 1, 0, 2.0],
                      [3, 2, 0, 2, 0, 3.0], [4, 3, 0, 3, 0, 4.0]])
    box = np.array([(0.0, 10.0)] * 3)
    return [dict(timestep=s, atoms=atoms.copy(), box=box.copy()) for s in (0, 1000)]


def _msd_frames():
    """Two frames, atom 1 moves 1.5 A in x between them, atom 2 stays."""
    import numpy as np
    box = np.array([(0.0, 10.0)] * 3)
    out = []
    for step, dx in ((0, 0.0), (500, 1.5)):
        atoms = np.array([[1, 1, 0, 2.0 + dx, 5, 5.0], [2, 1, 0, 7.0, 5, 5.0]])
        out.append(dict(timestep=step, atoms=atoms, box=box.copy()))
    return out


def _fns():
    """Map a label to (callable taking the frames and keyword overrides)."""
    import lammps_post.analysis as an
    return {
        'charge_evolution': lambda fr, **k: an.analyze_charge_evolution(fr, COL, **k),
        'or': lambda fr, **k: an.compute_or(fr, COL, **k),
        'oar': lambda fr, **k: an.compute_oar(fr, COL, **{'z_surf': 5.0, **k}),
        'penetration': lambda fr, **k: an.analyze_penetration(
            fr, COL, **{'surface_z': 5.0, **k}),
        'trend': lambda fr, **k: an.analyze_penetration_trend(
            fr, COL, **{'surface_z': 5.0, **k}),
        'o2': lambda fr, **k: an.detect_o2_dissociation(fr, COL, o_type=2, **k),
        'spin': lambda fr, **k: an.analyze_spin_evolution(fr, COL, **k),
        'msd': lambda fr, **k: an.analyze_msd(fr, COL, **k),
        'profile': lambda fr, **k: an.analyze_penetration_profile(fr, COL, **k),
        'charge_z': lambda fr, **k: an.analyze_charge_z(fr, COL, **k),
    }


def _reject(call, name):
    """Require a ValueError that names the parameter."""
    try:
        call()
    except ValueError as exc:
        assert name in str(exc), str(exc)
    else:
        raise AssertionError(f'invalid {name} was accepted')


def test_dt_fs_rejected_by_every_time_producing_analysis():
    """NaN, inf, zero, negative, bool and text dt_fs raise in all nine APIs."""
    _util.require_numpy()
    fns = _fns()
    for label in ('charge_evolution', 'or', 'oar', 'penetration', 'trend', 'o2',
                  'spin', 'msd', 'profile'):
        for bad in (NAN, INF, -INF, 0, 0.0, -0.25, True, '0.25', None):
            _reject(lambda: fns[label](_Unread(), dt_fs=bad), 'dt_fs')


def test_surface_plane_nan_and_non_numbers_rejected():
    """NaN/inf surface_z or z_surf would silently count zero O below the plane."""
    _util.require_numpy()
    fns = _fns()
    for label, key in (('oar', 'z_surf'), ('penetration', 'surface_z'),
                       ('trend', 'surface_z')):
        for bad in (NAN, INF, -INF, True, 'x', None):
            _reject(lambda: fns[label](_Unread(), **{key: bad}), key)


def test_q_thr_must_be_finite():
    """q_thr is a signed charge cutoff; only nonfinite or non-numbers are invalid."""
    _util.require_numpy()
    fns = _fns()
    for label in ('charge_evolution', 'or'):
        for bad in (NAN, INF, -INF, True, 'x', None):
            _reject(lambda: fns[label](_Unread(), q_thr=bad), 'q_thr')


def test_z_range_rejects_nan_reversed_and_malformed():
    """A NaN, equal or reversed slab selects nothing and would report zeros."""
    _util.require_numpy()
    fns = _fns()
    bad_ranges = [(NAN, 5), (0, NAN), (-INF, 5), (0, INF), (5, 0), (3, 3),
                  (1,), (1, 2, 3), 4.0, 'ab', (True, 5), ('0', '5')]
    for label in ('charge_evolution', 'or'):
        for bad in bad_ranges:
            _reject(lambda: fns[label](_Unread(), z_range=bad), 'z_range')


def test_z_bins_must_be_positive_integer():
    """Zero, negative, float, bool and text bin counts raise; no frame is needed."""
    _util.require_numpy()
    fns = _fns()
    frame = _Unread()
    for bad in (0, -3, 2.5, 4.0, True, '5', None, NAN):
        _reject(lambda: fns['charge_z'](frame, z_bins=bad), 'z_bins')


def test_window_must_be_positive_integer_or_none():
    """window 0, negative, float, bool and text raise; None keeps the automatic window."""
    _util.require_numpy()
    fns = _fns()
    for bad in (0, -1, 2.5, 3.0, True, '3', NAN):
        _reject(lambda: fns['trend'](_Unread(), window=bad), 'window')


def test_valid_oxidation_and_charge_results_unchanged():
    """Hand values: mean q 0.3, max 0.5, one of two above 0.3; slab (0, 5) keeps one."""
    _util.require_numpy()
    import numpy as np
    fns = _fns()
    r = fns['charge_evolution'](_frames(), dt_fs=0.5)
    assert np.allclose(r['time'], [0.0, 0.2])
    assert np.allclose(r['avg'], 0.3) and np.allclose(r['max'], 0.5)
    assert list(r['n_oxidized']) == [1, 1] and list(r['n_total_fe']) == [2, 2]
    assert np.allclose(r['frac_oxidized'], 0.5)
    s = fns['charge_evolution'](_frames(), dt_fs=0.5, z_range=(0, 5), q_thr=-1.0)
    assert list(s['n_total_fe']) == [1, 1] and list(s['n_oxidized']) == [1, 1]
    neg = fns['or'](_frames(), q_thr=-1.0)
    assert np.allclose(neg['or'], 1.0)
    o = fns['or'](_frames(), dt_fs=0.5, z_range=(0, 10))
    assert np.allclose(o['or'], 0.5) and np.allclose(o['time'], [0.0, 0.2])


def test_valid_surface_results_unchanged():
    """Hand values with the plane at z 5: one of two O below, time 400 * 0.5 / 1000."""
    _util.require_numpy()
    import numpy as np
    fns = _fns()
    r = fns['oar'](_frames(), dt_fs=0.5)
    assert np.allclose(r['time'], [0.0, 0.2]) and np.allclose(r['oar'], 0.5)
    assert list(r['n_absorbed']) == [1, 1] and list(r['n_total']) == [2, 2]
    p = fns['penetration'](_frames(), dt_fs=0.5)
    assert np.allclose(p['time'], [0.0, 0.2]) and p['surface_z'] == 5.0
    assert np.allclose(p['o_min_z'], 1.0)
    below = fns['oar'](_frames(), z_surf=-2.0)
    assert list(below['n_absorbed']) == [0, 0]
    t = fns['trend'](_frames(), dt_fs=0.5, window=2)
    assert np.allclose(t['adsorption_ratio_raw'], 0.5)
    assert np.allclose(t['mean_o_z_raw'], 5.0) and np.allclose(t['max_depth_raw'], 4.0)
    assert t['window'] == 2 and np.allclose(t['time'], [0.0, 0.2])


def test_window_longer_than_series_still_clamped_visibly():
    """Existing behaviour kept: window > series length is clamped and reported."""
    _util.require_numpy()
    t = _fns()['trend'](_frames(), window=50)
    assert t['window'] == 2
    auto = _fns()['trend'](_frames())
    assert auto['window'] == 2


def test_valid_charge_z_unchanged():
    """Two 5 A bins: metal q 0.5 / 0.1, one metal and one gas atom per bin."""
    _util.require_numpy()
    import numpy as np
    r = _fns()['charge_z'](_frames()[0], z_bins=2)
    assert np.allclose(r['z'], [2.5, 7.5]) and np.allclose(r['fe_charge'], [0.5, 0.1])
    assert list(r['fe_count']) == [1, 1] and list(r['o_count']) == [1, 1]


def test_valid_pair_spin_msd_profile_unchanged():
    """Hand values for O2 pairing, spin counts, MSD and profile time axes."""
    _util.require_numpy()
    import numpy as np
    fns = _fns()
    o2 = fns['o2'](_frames(), dt_fs=0.5, pbc=(True, True, True))
    assert np.allclose(o2['time'], [0.0, 0.2])
    assert list(o2['n_total_o']) == [2, 2]
    sp = fns['spin'](_spin_frames(), dt_fs=2.0)
    assert np.allclose(sp['time'], [0.0, 2.0])
    assert list(sp['n_up']) == [2, 2] and list(sp['n_down']) == [1, 1]
    assert list(sp['n_o']) == [1, 1]
    m = fns['msd'](_msd_frames(), species_type=1, dt_fs=2.0)
    assert np.allclose(m['time'], [0.0, 1.0])
    assert np.allclose(m['msd'], [0.0, 1.5 ** 2 / 2])
    pr = fns['profile'](_frames(), dt_fs=0.5)
    assert np.allclose(pr['time'], [0.0, 0.2]) and np.allclose(pr['min_o_z'], 1.0)
