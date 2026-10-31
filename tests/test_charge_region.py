"""REV-ANALYSIS-2: explicit spatial selection requires a z column."""
import _util


def _functions():
    """Return both public consumers of the optional charge region."""
    from lammps_post.analysis import analyze_charge_evolution, compute_or
    return analyze_charge_evolution, compute_or


def _frame(rows):
    """Build scalar type/charge data with no box or coordinate metadata."""
    import numpy as np
    return {'timestep': 20, 'atoms': np.array(rows, dtype=float)}


def _reject(call):
    """Require an explanatory region/missing-column error, not geometry failure."""
    try:
        call()
    except ValueError as exc:
        text = str(exc).lower()
        assert 'z' in text and 'column' in text and 'region' in text, str(exc)
    else:
        raise AssertionError('explicit region without z must not become global')


def test_region_without_z_rejects_instead_of_global_result():
    """A valid box cannot supply the missing per-atom z coordinate."""
    _util.require_numpy()
    import numpy as np
    frame = _frame([[4, .1], [4, .9]])
    frame['box'] = np.array([[0, 10]] * 3, dtype=float)
    for function in _functions():
        _reject(lambda: function([frame], {'type': 0, 'q': 1},
                                 fe_type=4, z_range=(2, 4)))


def test_region_without_z_rejects_before_geometry_or_iteration():
    """Column-contract failures do not consume a generator or need a box."""
    _util.require_numpy()
    for function in _functions():
        consumed = []

        def frames():
            """Record attempted consumption to detect late validation."""
            consumed.append(True)
            yield _frame([[4, .9]])

        _reject(lambda: function(frames(), {'type': 0, 'q': 1},
                                 fe_type=4, z_range=(2, 4)))
        assert consumed == []


def test_empty_region_request_without_z_still_rejects():
    """An empty trajectory must not conceal an unsupported requested selection."""
    _util.require_numpy()
    for function in _functions():
        _reject(lambda: function([], {'type': 0, 'q': 1}, z_range=(0, 1)))


def test_missing_z_error_precedes_unrelated_missing_type_and_geometry():
    """Region metadata fails before type lookup or unsupported frame geometry."""
    _util.require_numpy()
    frame = _frame([[4, .9]])
    frame['triclinic'] = True
    for function in _functions():
        _reject(lambda: function([frame], {}, z_range=(0, 1)))
        _reject(lambda: function([frame], {'type': 0, 'q': 1}, z_range=(0, 1)))


def test_missing_charge_does_not_hide_missing_requested_z():
    """Explicit region validation precedes the optional charge-data shortcut."""
    _util.require_numpy()
    for function in _functions():
        _reject(lambda: function([], {'type': 0}, z_range=(0, 1)))
        assert function([], {'type': 0}) is None
        assert function([], {'type': 0, 'z': 1}, z_range=(0, 1)) is None


def test_unrestricted_scalar_results_need_neither_z_nor_box():
    """Unrestricted type unions retain independent finite population arithmetic."""
    _util.require_numpy()
    import numpy as np
    frame = _frame([[4, .1], [7, .5], [7, .9], [9, -1]])
    evolution, rate = _functions()
    kwargs = dict(fe_type={4, 7}, q_thr=.5, dt_fs=2)
    got = evolution([frame], {'type': 0, 'q': 1}, **kwargs)
    np.testing.assert_allclose(got['avg'], [.5])
    np.testing.assert_array_equal(got['n_total_fe'], [3])
    np.testing.assert_array_equal(got['n_oxidized'], [1])
    np.testing.assert_allclose(got['frac_oxidized'], [1 / 3])
    np.testing.assert_allclose(got['time'], [.04])
    np.testing.assert_allclose(rate([frame], {'type': 0, 'q': 1}, **kwargs)['or'], [1 / 3])


def test_region_with_z_uses_inclusive_bounds_and_species_union():
    """Real spatial selection differs from global selection without changing units."""
    _util.require_numpy()
    import numpy as np
    frame = _frame([[4, .1, 2], [7, .5, 3], [7, .9, 4],
                    [4, 2, 5], [9, 4, 3]])
    frame['box'] = np.array([[0, 10]] * 3, dtype=float)
    columns = {'type': 0, 'q': 1, 'z': 2}
    evolution, rate = _functions()
    kwargs = dict(fe_type={4, 7}, q_thr=.5, z_range=(2, 4))
    got = evolution([frame], columns, **kwargs)
    np.testing.assert_allclose(got['avg'], [.5])
    np.testing.assert_array_equal(got['n_total_fe'], [3])
    np.testing.assert_array_equal(got['n_oxidized'], [1])
    np.testing.assert_allclose(rate([frame], columns, **kwargs)['or'], [1 / 3])
    assert rate([frame], columns, fe_type={4, 7}, q_thr=.5)['or'][0] == .5


def test_valid_region_empty_population_keeps_zero_results():
    """A representable but empty selection remains valid and preserves its zeros."""
    _util.require_numpy()
    import numpy as np
    frame = _frame([[4, .9, 5]])
    frame['box'] = np.array([[0, 10]] * 3, dtype=float)
    columns = {'type': 0, 'q': 1, 'z': 2}
    evolution, rate = _functions()
    kwargs = dict(fe_type=4, z_range=(0, 1))
    got = evolution([frame], columns, **kwargs)
    for key in ('avg', 'max', 'n_oxidized', 'n_total_fe', 'frac_oxidized'):
        np.testing.assert_array_equal(got[key], [0])
    np.testing.assert_array_equal(rate([frame], columns, **kwargs)['or'], [0])
