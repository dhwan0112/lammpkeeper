"""REV-ANALYSIS-1: selected charges must be finite, never silently dropped.

All numeric examples are in-memory and use arbitrary type IDs. Expected values
come from explicit population arithmetic, not fixture hashes or golden outputs.
"""

import _util


COL = dict(type=0, q=1, z=2, unused=3)
SCALAR_COL = dict(type=0, q=1)


def _frame(rows, step=40, spatial=True):
    """Build numeric rows with no geometry at all for scalar-charge examples."""
    import numpy as np
    width = 4 if spatial else 2
    frame = dict(atoms=np.asarray(rows, dtype=float).reshape(-1, width),
                 timestep=step)
    if spatial:
        frame['box'] = np.asarray([(0, 10)] * 3, dtype=float)
    return frame


def _reject(call, analysis, step):
    """Require an analysis- and timestep-specific finite-charge ValueError."""
    try:
        call()
    except ValueError as exc:
        message = str(exc).lower()
        for text in (analysis.lower(), 'charge', 'finite', f'timestep {step}'):
            assert text in message, str(exc)
    else:
        raise AssertionError('selected nonfinite charge must raise ValueError')


def _check_global_rejection(function, analysis):
    """Both members of a species union reject NaN and either infinity."""
    import numpy as np
    for bad in (np.nan, np.inf, -np.inf):
        for index in (0, 1):
            frame = _frame([[4, .1], [7, .9]], spatial=False)
            frame['atoms'][index, SCALAR_COL['q']] = bad
            _reject(lambda: function([frame], SCALAR_COL, fe_type={4, 7}),
                    analysis, 40)


def test_charge_evolution_rejects_selected_nonfinite_without_geometry():
    """Scalar charge statistics cannot publish NaN/Inf or drop a bad atom."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_charge_evolution
    _check_global_rejection(analyze_charge_evolution, 'Charge evolution')


def test_or_rejects_selected_nonfinite_without_geometry():
    """The [NaN, .9] denominator repro must fail, not yield a plausible .5."""
    _util.require_numpy()
    from lammps_post.analysis import compute_or
    _check_global_rejection(compute_or, 'Oxidation rate')


def _check_region_rejection(function, analysis):
    """Inclusive slab endpoints participate in finite-charge validation."""
    import numpy as np
    for bad in (np.nan, np.inf, -np.inf):
        for z in (2, 3, 4):
            frame = _frame([[4, .9, 3, 0], [7, bad, z, 0]])
            _reject(lambda: function([frame], COL, fe_type={4, 7},
                                     z_range=(2, 4)), analysis, 40)


def test_charge_evolution_rejects_nonfinite_inside_inclusive_region():
    """Region filtering must precede validation without losing boundary atoms."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_charge_evolution
    _check_region_rejection(analyze_charge_evolution, 'Charge evolution')


def test_or_rejects_nonfinite_inside_inclusive_region():
    """No NaN/Inf inside the selected slab may alter the oxidation fraction."""
    _util.require_numpy()
    from lammps_post.analysis import compute_or
    _check_region_rejection(compute_or, 'Oxidation rate')


def test_charge_and_or_revalidate_later_frame_after_type_change():
    """An initially unrelated bad charge becomes invalid on joining the group."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_charge_evolution, compute_or
    first = _frame([[4, .9], [9, np.nan]], spatial=False)
    later = _frame([[4, .9], [7, np.nan]], step=80, spatial=False)
    for function, name in ((analyze_charge_evolution, 'Charge evolution'),
                           (compute_or, 'Oxidation rate')):
        _reject(lambda: function([first, later], SCALAR_COL, fe_type={4, 7}),
                name, 80)


def test_charge_z_rejects_selected_in_bin_nonfinite_charges():
    """Both union members and the lower/internal bin edges consume charges."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_charge_z
    for bad in (np.nan, np.inf, -np.inf):
        for atom_type in (4, 7):
            for z in (0, 2, 5, 9):
                frame = _frame([[4, .9, 2, 0], [atom_type, bad, z, 0]])
                _reject(lambda: analyze_charge_z(frame, COL, z_bins=2,
                                                 fe_type={4, 7}, o_type=9),
                        'Charge z profile', 40)


def test_charge_z_overlap_still_requires_finite_metal_charge():
    """Metal precedence must not turn an overlapping type into charge-free counts."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_charge_z
    frame = _frame([[7, np.nan, 2, 0]])
    _reject(lambda: analyze_charge_z(frame, COL, z_bins=2,
                                     fe_type={4, 7}, o_type={7, 9}),
            'Charge z profile', 40)


def test_charge_z_without_timestep_still_reports_invalid_charge():
    """A static profile needs no time metadata, including for its error report."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_charge_z
    frame = _frame([[4, float('nan'), 2, 0]])
    del frame['timestep']
    _reject(lambda: analyze_charge_z(frame, COL, fe_type=4, o_type=9),
            'Charge z profile', 'unknown')
    frame['atoms'][0, COL['q']] = .5
    result = analyze_charge_z(frame, COL, z_bins=2, fe_type=4, o_type=9)
    assert list(result['fe_charge']) == [.5, 0]


def test_finite_scalar_results_match_independent_population_arithmetic():
    """No z/box is needed; groups and populations are selected anew each frame."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_charge_evolution, compute_or
    frames = [_frame([[4, -.5], [7, .5], [7, 1.5], [9, np.nan]], spatial=False),
              _frame([[9, np.inf], [4, 1], [7, -1]], step=80, spatial=False)]
    kwargs = dict(fe_type={4, 7}, q_thr=.5, dt_fs=2)
    got = analyze_charge_evolution(frames, SCALAR_COL, **kwargs)
    expected = dict(time=[.08, .16], avg=[.5, 0], max=[1.5, 1],
                    n_oxidized=[1, 1], n_total_fe=[3, 2],
                    frac_oxidized=[1 / 3, .5])
    for key, values in expected.items():
        np.testing.assert_allclose(got[key], values)
    rate = compute_or(frames, SCALAR_COL, **kwargs)
    np.testing.assert_allclose(rate['time'], [.08, .16])
    np.testing.assert_allclose(rate['or'], [1 / 3, .5])


def test_scalar_results_ignore_unused_nonfinite_columns_and_geometry():
    """Global charge consumers must not acquire all-column or geometry guards."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_charge_evolution, compute_or
    frame = _frame([[4, .25, np.nan, np.inf], [7, .75, -np.inf, np.nan],
                    [9, np.nan, 5, 0]])
    # A scalar analysis does not consume even present, unusable slab metadata.
    frame['box'] = np.full((3, 2), np.nan)
    frame['triclinic'] = True
    charge = analyze_charge_evolution([frame], COL, fe_type={4, 7}, q_thr=.5)
    rate = compute_or([frame], COL, fe_type={4, 7}, q_thr=.5)
    np.testing.assert_allclose(charge['avg'], [.5])
    np.testing.assert_allclose(charge['max'], [.75])
    np.testing.assert_array_equal(charge['n_total_fe'], [2])
    np.testing.assert_allclose(charge['frac_oxidized'], [.5])
    np.testing.assert_allclose(rate['or'], [.5])


def test_region_results_preserve_boundaries_and_ignore_excluded_bad_charges():
    """Only the inclusive slab/type intersection supplies means and denominators."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_charge_evolution, compute_or
    frame = _frame([[4, .5, 2, np.nan], [7, 1, 3, np.inf], [7, -.5, 4, 0],
                    [4, np.nan, 1.9, 0], [7, np.inf, 4.1, 0],
                    [4, -np.inf, 5, 0], [9, np.nan, 3, 0]])
    kwargs = dict(fe_type={4, 7}, q_thr=.5, z_range=(2, 4))
    got = analyze_charge_evolution([frame], COL, **kwargs)
    np.testing.assert_allclose(got['avg'], [1 / 3])
    np.testing.assert_allclose(got['max'], [1])
    np.testing.assert_array_equal(got['n_total_fe'], [3])
    np.testing.assert_array_equal(got['n_oxidized'], [1])
    np.testing.assert_allclose(got['frac_oxidized'], [1 / 3])
    np.testing.assert_allclose(compute_or([frame], COL, **kwargs)['or'], [1 / 3])


def test_charge_z_finite_oracle_and_only_contributing_charges_are_validated():
    """Upper-edge/outside charges and count-only species do not enter means."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_charge_z
    frame = _frame([[4, .25, 0, np.nan], [7, .75, 4, np.inf], [7, -1, 5, 0],
                    [4, np.nan, 10, 0], [7, np.inf, -1, 0],
                    [7, -np.inf, 11, 0], [9, np.nan, 2, 0],
                    [12, np.inf, 7, 0], [99, np.nan, 3, 0]])
    got = analyze_charge_z(frame, COL, z_bins=2, fe_type={4, 7}, o_type={7, 9, 12})
    np.testing.assert_allclose(got['z'], [2.5, 7.5])
    np.testing.assert_allclose(got['fe_charge'], [.5, -1])
    np.testing.assert_array_equal(got['fe_count'], [2, 1])
    np.testing.assert_array_equal(got['o_count'], [1, 1])


def test_empty_selections_and_trajectories_keep_existing_zero_semantics():
    """Validation does not reject empty selections or invent a nonzero population."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_charge_evolution, analyze_charge_z, compute_or
    frames = [_frame([[9, np.nan, 3, np.inf]]), _frame([], step=80)]
    for kwargs in (dict(fe_type={4, 7}), dict(fe_type={4, 7}, z_range=(2, 4)),
                   dict(fe_type=9, z_range=(6, 7))):
        charge = analyze_charge_evolution(frames, COL, **kwargs)
        for key in ('avg', 'max', 'n_oxidized', 'n_total_fe', 'frac_oxidized'):
            np.testing.assert_array_equal(charge[key], [0, 0])
        np.testing.assert_array_equal(compute_or(frames, COL, **kwargs)['or'], [0, 0])
    for frame in frames:
        got = analyze_charge_z(frame, COL, z_bins=2, fe_type={4, 7}, o_type=12)
        for key in ('fe_charge', 'fe_count', 'o_count'):
            np.testing.assert_array_equal(got[key], [0, 0])
    for function in (analyze_charge_evolution, compute_or):
        result = function([], SCALAR_COL, fe_type={4, 7})
        assert all(values.size == 0 for values in result.values())


def test_missing_optional_columns_still_return_none():
    """Absent charge data is distinct from a present nonfinite selected charge."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_charge_evolution, analyze_charge_z, compute_or
    frame = _frame([[4, .5, 2, 0]])
    no_charge = {key: value for key, value in COL.items() if key != 'q'}
    for function in (analyze_charge_evolution, compute_or):
        assert function([frame], no_charge, fe_type=4) is None
    assert analyze_charge_z(frame, no_charge, fe_type=4, o_type=9) is None
    assert analyze_charge_z(frame, SCALAR_COL, fe_type=4, o_type=9) is None
