"""AUDIT-20261027 analytic oracles; no fixture or golden rebaselining.

RDF uses an equal-weight arithmetic mean of instantaneous density-normalized
RDFs, rho_b=N_b/V. Same-species histograms count both ordered directions.
"""
from contextlib import nullcontext
from unittest.mock import patch
import warnings

import _util


COL = dict(id=0, type=1, x=2, y=3, z=4)


def _frame(rows, step=0, length=10):
    """Build a cubic frame with explicit volume for independent normalization math."""
    import numpy as np
    return dict(atoms=np.asarray(rows, float).reshape(-1, 5), timestep=step,
                box=np.asarray([(0, length)] * 3, float))


def _reject(call, needle):
    """Require an informative failure rather than a silently usable bad result."""
    try:
        call()
    except ValueError as exc:
        assert needle.lower() in str(exc).lower(), str(exc)
    else:
        raise AssertionError('expected visible ValueError')


def test_rdf_ordered_same_species_exact():
    """Two distinct atoms contribute two ordered pairs, normalized by N times rho."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf
    fr = _frame([[1, 4, 4, 5, 5], [2, 4, 5, 5, 5]])
    got = compute_rdf([fr], COL, 4, 4, r_max=2, n_bins=2, z_pbc=True)
    # The occupied bin spans radii 1 to 2: its volume is 4*pi/3*(8-1).
    # The contract uses rho=N/V, not a finite-population (N-1)/V correction.
    shell = 4 * np.pi / 3 * 7
    np.testing.assert_allclose(got['g'], [0, 2 / (2 * (2 / 1000) * shell)])


def test_rdf_variable_volume_arithmetic_ensemble_exact():
    """Average per-frame density-normalized curves, not pooled pair exposures."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf
    rows = [[1, 4, 4, 5, 5], [2, 9, 5, 5, 5]]
    frames = [_frame(rows), _frame(rows, 1, 20)]
    # Each frame has one A-B pair; inverse density makes its curve scale with V.
    expected = (1000 + 8000) / (2 * (4 * np.pi / 3 * 7))
    for order in (frames, frames[::-1]):
        got = compute_rdf(order, COL, 4, 9, r_max=2, n_bins=2, z_pbc=True)
        np.testing.assert_allclose(got['g'], [0, expected])
        assert got['n_frames'] == 2


def test_rdf_variable_population_arithmetic_ensemble_exact():
    """Doubling target atoms and bin counts together leaves the normalized RDF fixed."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf
    rows = [[1, 4, 4, 5, 5], [2, 9, 5, 5, 5]]
    frames = [_frame(rows), _frame(rows + [[3, 9, 5.5, 5, 5]], 1)]
    expected = 1000 / (4 * np.pi / 3 * 7)
    for order in (frames, frames[::-1]):
        got = compute_rdf(order, COL, 4, 9, r_max=2, n_bins=2, z_pbc=True)
        np.testing.assert_allclose(got['g'], [0, expected])


def test_rdf_seeded_ideal_gas_constant_and_variable_volume():
    """Uniform random ensembles give an approximately unit, order-invariant plateau."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf
    rng = np.random.default_rng(71426)
    n = 1200
    frames = []
    for k in range(6):
        pos = rng.uniform(0, 30, (2 * n, 3))
        rows = np.column_stack((np.arange(1, 2*n+1), np.repeat((4, 9), n), pos))
        frames.append(_frame(rows, k, 30))
    variable = frames[:3] + [dict(fr, atoms=fr['atoms'].copy(), box=fr['box'] * 2)
                             for fr in frames[3:]]
    for fr in variable[3:]:
        fr['atoms'][:, 2:] *= 2
    # Shell volume grows as the difference of cubed edges. Volume weighting
    # aggregates counts fairly; the outer bins avoid sparse near-origin noise.
    # With N/V same-species normalization, the ideal finite-N level is (N-1)/N,
    # well inside the statistical band around one used here.
    weights = np.diff(np.linspace(0, 6, 31) ** 3)
    for ensemble in (frames, variable):
        for a, b in ((4, 4), (4, 9)):
            got = compute_rdf(ensemble, COL, a, b, r_max=6, n_bins=30,
                              max_frames=6, z_pbc=True)
            reverse = compute_rdf(ensemble[::-1], COL, a, b, r_max=6,
                                  n_bins=30, max_frames=6, z_pbc=True)
            keep = got['r'] >= 3
            plateau = np.average(got['g'][keep], weights=weights[keep])
            assert .95 < plateau < 1.05, plateau
            np.testing.assert_allclose(got['g'], reverse['g'], rtol=1e-14)


def test_rdf_explicit_xy_nonperiodic_and_legacy_fallback():
    """Explicit nonperiodic flags override the legacy periodic-x/y convention."""
    _util.require_numpy()
    import numpy as np
    from lammps_post import analysis as a
    for axis in (0, 1):
        rows = [[1, 4, 5, 5, 5], [2, 9, 5, 5, 5]]
        rows[0][axis + 2], rows[1][axis + 2] = .1, 9.9
        fr = _frame(rows)
        for fallback in (False, True):
            with patch.object(a, '_rdf_candidate_pairs', return_value=None) if fallback else nullcontext():
                got = a.compute_rdf([fr], COL, 4, 9, r_max=1, n_bins=5,
                                    pbc=(False, False, False), z_pbc=True)
                np.testing.assert_array_equal(got['g'], np.zeros(5))
                legacy = a.compute_rdf([fr], COL, 4, 9, r_max=1, n_bins=5)
                assert legacy['g'].sum() > 0


def test_rdf_scipy_matches_fallback_all_axis_combinations():
    """Accelerated and brute-force RDFs agree for mixed axes and type unions."""
    _util.require_numpy()
    import itertools
    import numpy as np
    from lammps_post import analysis as a
    try:
        import scipy.spatial  # noqa: F401
    except ImportError:
        # A fallback-only environment cannot establish cross-backend equality.
        _util.skip('scipy unavailable: accelerated RDF equality requires scipy')
    rng = np.random.default_rng(777)
    rows = np.column_stack((np.arange(1, 81), np.repeat((4, 9), 40),
                            rng.uniform(-5, 15, (80, 3))))
    frames = [_frame(rows), _frame(rows, 1, 20)]
    for pbc in itertools.product((False, True), repeat=3):
        for pair in ((4, 4), (4, 9), ({4, 9}, {9})):
            fast = a.compute_rdf(frames, COL, *pair, r_max=3, n_bins=12, pbc=pbc)
            with patch.object(a, '_rdf_candidate_pairs', return_value=None):
                slow = a.compute_rdf(frames, COL, *pair, r_max=3, n_bins=12, pbc=pbc)
            np.testing.assert_array_equal(fast['g'], slow['g'])


def test_rdf_missing_species_frame_warns_and_reports_used_count():
    """Excluded empty selections must warn and not inflate the reported ensemble."""
    _util.require_numpy()
    from lammps_post.analysis import compute_rdf
    frames = [_frame([[1, 4, 4, 5, 5], [2, 9, 5, 5, 5]]),
              _frame([[1, 4, 4, 5, 5]], 1)]
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter('always')
        got = compute_rdf(frames, COL, 4, 9)
    assert got['n_frames'] == 1 and seen
    assert '1' in str(seen[0].message) and 'empty' in str(seen[0].message).lower()


def test_rdf_rejects_invalid_pbc_geometry_and_positions():
    """Malformed axes, retained tilt and nonfinite coordinates must fail visibly."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf
    fr = _frame([[1, 4, 4, 5, 5], [2, 9, 5, 5, 5]])
    for pbc in ((True, False), (1, 0, 1), 'ppp'):
        _reject(lambda: compute_rdf([fr], COL, 4, 9, pbc=pbc), 'pbc')
    _reject(lambda: compute_rdf([dict(fr, box=np.ones((3, 3)))], COL, 4, 9), 'triclinic')
    _reject(lambda: compute_rdf([dict(fr, tilt=(1, 0, 0))], COL, 4, 9), 'triclinic')
    broken = dict(fr, atoms=fr['atoms'].copy())
    broken['atoms'][0, 2] = np.nan
    _reject(lambda: compute_rdf([broken], COL, 4, 9), 'finite')


def _profile_frames():
    """Keep one submerged ID while replacing an above-surface atom by a new ID."""
    f0 = _frame([[1, 4, 0, 0, 10], [10, 9, 0, 0, 12], [20, 9, 0, 0, 8]])
    f1 = _frame([[1, 4, 0, 0, 10], [20, 9, 0, 0, 8], [30, 9, 0, 0, 12]], 1)
    return [f0, f1]


def test_profile_replacement_tracks_id_union_without_false_crossing():
    """An ID union with NaN absences prevents row replacement becoming a crossing."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_penetration_profile
    got = analyze_penetration_profile(_profile_frames(), COL, o_type=9)
    np.testing.assert_array_equal(got['o_ids'], [10, 20, 30])
    np.testing.assert_allclose(got['o_z_traj'], [[12, 8, np.nan], [np.nan, 8, 12]])
    np.testing.assert_array_equal(got['cross_times'], [0])
    assert got['n_o'] == 3 and got['n_initial_o'] == 2


def test_profile_population_changes_and_empty_frames_are_retained():
    """An empty middle sample remains a time-aligned NaN gap, not a skipped frame."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_penetration_profile
    f0, f1 = _profile_frames()
    middle = _frame([[1, 4, 0, 0, 10]], 1)
    got = analyze_penetration_profile([f0, middle, dict(f1, timestep=2)], COL, o_type=9)
    np.testing.assert_allclose(got['time'], [0, .001, .002])
    assert np.isnan(got['o_z_traj'][1]).all() and np.isnan(got['min_o_z'][1])
    np.testing.assert_array_equal(got['n_present_o'], [2, 0, 2])
    np.testing.assert_array_equal(got['cross_times'], [0])


def test_profile_can_start_empty_then_track_new_ids():
    """Late submerged arrivals have events but never join the initial cohort."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_penetration_profile
    frames = [_frame([[1, 4, 0, 0, 10]]),
              _frame([[1, 4, 0, 0, 10], [20, 9, 0, 0, 8]], 1)]
    got = analyze_penetration_profile(frames, COL, o_type=9)
    np.testing.assert_allclose(got['o_z_traj'], [[np.nan], [8]])
    assert got['n_initial_o'] == 0
    np.testing.assert_array_equal(got['cross_times'], [.001])
    assert got['initial_cross_times'].size == 0


def test_profile_requires_valid_unique_ids():
    """Persistent penetration trajectories require explicit, unambiguous identities."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_penetration_profile
    frames = _profile_frames()
    _reject(lambda: analyze_penetration_profile(frames, {k: v for k, v in COL.items() if k != 'id'}, o_type=9), 'id')
    for value in (1, -1, 2.5, float('nan')):
        broken = [dict(fr, atoms=fr['atoms'].copy()) for fr in frames]
        broken[1]['atoms'][1, 0] = value
        _reject(lambda: analyze_penetration_profile(broken, COL, o_type=9), 'id')


def test_profile_consumes_percentile_and_explicit_surface_species_union():
    """Surface percentiles use only the configured type union and interpolation."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_penetration_profile
    rows = [[k+1, 4 if k % 2 else 7, 0, 0, z]
            for k, z in enumerate(list(range(10)) + [100])]
    rows += [[100, 9, 0, 0, 60], [101, 12, 0, 0, 60], [102, 99, 0, 0, 1000]]
    frames = [_frame(rows, length=1200), _frame(rows, 1, 1200)]
    # Eleven surface heights put the 95th percentile halfway between 9 and
    # 100; the unrelated type at 1000 must not influence that interpolation.
    for pct, expected in ((50, 5), (90, 9), (95, 54.5)):
        got = analyze_penetration_profile(frames, COL, o_type={9, 12},
                                          fe_type={4, 7}, surface_percentile=pct)
        np.testing.assert_allclose(got['surface_z'], expected)
        assert got['cross_times'].size == 0 and got['n_o'] == 2


def test_profile_missing_surface_is_nan_and_warns_not_zero():
    """Absent surface atoms yield a warning and unknown height, never a zero plane."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_penetration_profile
    frames = _profile_frames()
    frames[1]['atoms'] = frames[1]['atoms'][1:]
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter('always')
        got = analyze_penetration_profile(frames, COL, o_type=9, fe_type=4)
    assert np.isnan(got['surface_z'][1]) and len(seen) == 1
    np.testing.assert_array_equal(got['cross_times'], [0])
    for pct in (-1, 101, np.nan, 'bad'):
        _reject(lambda: analyze_penetration_profile(frames, COL, o_type=9,
                                                   surface_percentile=pct), 'percentile')


def test_penetration_summary_and_trend_retain_empty_samples():
    """Summary and trend preserve zero populations with undefined height metrics."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_penetration, analyze_penetration_trend
    f0, f1 = _profile_frames()
    frames = [f0, _frame([[1, 4, 0, 0, 10]], 1), dict(f1, timestep=2)]
    summary = analyze_penetration(frames, COL, 10, o_type=9)
    trend = analyze_penetration_trend(frames, COL, 10, o_type=9, window=1)
    np.testing.assert_array_equal(summary['n_total_o'], [2, 0, 2])
    np.testing.assert_allclose(trend['time'], [0, .001, .002])
    assert np.isnan(summary['o_min_z'][1]) and np.isnan(trend['mean_o_z_raw'][1])


def test_msd_o2_reject_retained_tilt_metadata():
    """Orthogonal-looking bounds cannot hide separately retained triclinic tilt."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd, detect_o2_dissociation
    frames = [dict(fr, tilt=(1, 0, 0)) for fr in _profile_frames()]
    _reject(lambda: analyze_msd(frames, COL, species_type=4), 'triclinic')
    _reject(lambda: detect_o2_dissociation(frames, COL, o_type=9), 'triclinic')


def test_domain_type_union_filters_match_flattened_species():
    """Relabeling unions to scalar species is an independent selection equivalence."""
    _util.require_numpy()
    import numpy as np
    from lammps_post import analysis as a
    rows = [[1, 4, 1, 1, 1], [2, 7, 2, 1, 4],
            [3, 9, 4, 1, 2], [4, 12, 4.5, 1, 8]]
    frames = [_frame(rows), _frame(rows, 1)]
    flat = [dict(fr, atoms=fr['atoms'].copy()) for fr in frames]
    for fr in flat:
        fr['atoms'][np.isin(fr['atoms'][:, 1], [4, 7]), 1] = 1
        fr['atoms'][np.isin(fr['atoms'][:, 1], [9, 12]), 1] = 2
    # Preserve coordinates and charges while collapsing labels only, so each
    # comparison isolates union membership rather than changing the physics.
    for func, kwargs in ((a.compute_oar, dict(z_surf=6)),
                         (a.analyze_penetration, dict(surface_z=6)),
                         (a.analyze_penetration_trend, dict(surface_z=6)),
                         (a.detect_o2_dissociation, {})):
        got, expected = func(frames, COL, o_type={9, 12}, **kwargs), func(flat, COL, **kwargs)
        for key in expected:
            np.testing.assert_allclose(got[key], expected[key])
    for fr in frames + flat:
        fr['atoms'] = np.column_stack((fr['atoms'], [.1, .7, -.2, -.6]))
    cols = dict(COL, q=5)
    for func in (a.compute_or, a.analyze_charge_evolution):
        got, expected = func(frames, cols, fe_type={4, 7}), func(flat, cols)
        for key in expected:
            np.testing.assert_allclose(got[key], expected[key])
    got = a.analyze_charge_z(frames[0], cols, fe_type={4, 7}, o_type={9, 12})
    expected = a.analyze_charge_z(flat[0], cols)
    for key in expected:
        np.testing.assert_array_equal(got[key], expected[key])
    got = a.compute_density_profile(frames, cols, species_type={9, 12})
    expected = a.compute_density_profile(flat, cols, species_type=2)
    np.testing.assert_array_equal(got['density'], expected['density'])
