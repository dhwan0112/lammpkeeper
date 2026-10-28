"""Synthetic MSD contracts: fixed initial IDs, per-axis PBC, and validation.

Expected values are analytic squared displacements, not trajectory goldens.
No element, force-field, parser, or optional pytest dependency is involved.
"""
import warnings

import _util  # path bootstrap for pytest and tests/run.py


COL = {'id': 0, 'type': 1, 'x': 2, 'y': 3, 'z': 4}
BOX = ((0, 10), (0, 10), (0, 30))


def _frame(rows, step=0, dtype='float64', box=BOX):
    """Build ID-bearing synthetic frames without parser or force-field inference."""
    import numpy as np
    return {'atoms': np.asarray(rows, dtype=dtype).reshape((-1, 5)),
            'box': np.asarray(box, dtype=dtype), 'timestep': step}


def _assert_msd(result, expected, times=None):
    """Compare analytic curves and reject the legacy frame-skipping result schema.

    Tolerances accommodate input coordinates already quantized to float32,
    especially cancellation near box boundaries; they are not sampling errors.
    """
    import numpy as np
    assert result is not None
    assert 'n_skipped' not in result, result
    np.testing.assert_allclose(result['msd'], expected, rtol=2e-5, atol=2e-6)
    if times is not None:
        np.testing.assert_allclose(result['time'], times, rtol=1e-6, atol=1e-9)


def _value_error(call, *needles):
    """Require a visible validation failure with enough context to locate bad input."""
    try:
        call()
    except ValueError as exc:
        message = str(exc).lower()
        assert message, 'validation error must explain the problem'
        for needle in needles:
            assert str(needle).lower() in message, str(exc)
    else:
        raise AssertionError('expected a ValueError, not a silent MSD result')


def test_msd_tracks_ids_through_type_swap():
    """Changing type labels on stationary IDs must yield zero displacement."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    # Static atoms exchanging types must not create fictitious diffusion.
    for dtype in (np.float32, np.float64):
        frames = [_frame([[1, 1, 1, 1, 1], [2, 2, 5, 1, 1]], dtype=dtype),
                  _frame([[1, 2, 1, 1, 1], [2, 1, 5, 1, 1]], 100, dtype)]
        _assert_msd(analyze_msd(frames, COL, species_type=1), [0, 0])


def test_msd_type_population_change_does_not_skip_frames():
    """Follow the initial ID through type loss and recovery, retaining all times."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    for dtype in (np.float32, np.float64):
        frames = [_frame([[1, 1, 1, 1, 1], [2, 2, 7, 1, 1]], dtype=dtype),
                  _frame([[1, 2, 2, 1, 1], [2, 2, 7, 1, 1]], 100, dtype),
                  _frame([[1, 1, 3, 1, 1], [2, 1, 7, 1, 1]], 200, dtype)]
        # ID 1 moves one length unit per sample; 100 * 2 fs is 0.2 ps.
        _assert_msd(analyze_msd(frames, COL, species_type=1, dt_fs=2),
                    [0, 1, 4], [0, 0.2, 0.4])


def test_msd_shuffled_rows_keep_atom_identity():
    """Row permutations must not replace ID-matched squared displacements."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    for dtype in (np.float32, np.float64):
        frames = [_frame([[9, 1, 1, 1, 1], [2, 1, 5, 1, 1]], dtype=dtype),
                  _frame([[2, 1, 7, 1, 1], [9, 1, 2, 1, 1]], 100, dtype),
                  _frame([[9, 1, 3, 1, 1], [2, 1, 9, 1, 1]], 200, dtype)]
        # Displacements (1, 2), then (2, 4): mean squares 2.5 and 10.
        _assert_msd(analyze_msd(frames, COL, species_type=1), [0, 2.5, 10])


def test_msd_type_group_locks_initial_cohort():
    """Every iterable selector fixes the same two initial IDs despite later swaps."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    for dtype in (np.float32, np.float64):
        frames = [_frame([[1, 1, 1, 1, 1], [2, 2, 5, 1, 1],
                          [3, 3, 8, 1, 1]], dtype=dtype),
                  _frame([[3, 1, 9, 1, 1], [2, 1, 7, 1, 1],
                          [1, 3, 2, 1, 1]], 100, dtype)]
        for types in ({1, 2}, [1, 2], (1, 2), iter((1, 2))):
            _assert_msd(analyze_msd(frames, COL, species_type=types), [0, 2.5])


def test_msd_none_selects_all_initial_ids_despite_type_changes():
    """An unrestricted selection follows initial atoms rather than their type labels."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    for dtype in (np.float32, np.float64):
        frames = [_frame([[1, 1, 1, 1, 1], [2, 2, 5, 1, 1]], dtype=dtype),
                  _frame([[2, 8, 7, 1, 1], [1, 9, 2, 1, 1]], 100, dtype)]
        _assert_msd(analyze_msd(frames, COL, species_type=None), [0, 2.5])


def test_msd_added_ids_warn_and_do_not_change_denominator():
    """New IDs warn but cannot dilute the two-atom initial-cohort mean."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    for dtype in (np.float32, np.float64):
        frames = [_frame([[1, 1, 1, 1, 1], [2, 1, 5, 1, 1]], dtype=dtype),
                  _frame([[3, 1, 8, 1, 1], [2, 1, 7, 1, 1],
                          [1, 1, 2, 1, 1]], 100, dtype),
                  _frame([[2, 1, 9, 1, 1], [1, 1, 3, 1, 1],
                          [3, 1, 9, 1, 1]], 200, dtype)]
        for species in (None, 1):
            with warnings.catch_warnings(record=True) as seen:
                warnings.simplefilter('always')
                result = analyze_msd(frames, COL, species_type=species)
            assert any(issubclass(w.category, RuntimeWarning)
                       and 'id' in str(w.message).lower()
                       and any(word in str(w.message).lower() for word in ('new', 'added'))
                       for w in seen), [str(w.message) for w in seen]
            _assert_msd(result, [0, 2.5, 10], [0, 0.1, 0.2])


def test_msd_missing_selected_id_raises_with_id_and_timestep():
    """A lost cohort atom must identify its ID and failing sample, not be skipped."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    frames = [_frame([[7, 1, 1, 1, 1], [8, 2, 5, 1, 1]]),
              _frame([[8, 2, 5, 1, 1]], 250)]
    _value_error(lambda: analyze_msd(frames, COL, species_type=1), 'id', '7', '250')


def test_msd_missing_all_species_id_raises():
    """Selecting all species still requires every initially present ID later on."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    frames = [_frame([[7, 1, 1, 1, 1], [8, 2, 5, 1, 1]]),
              _frame([[8, 2, 5, 1, 1]], 250)]
    _value_error(lambda: analyze_msd(frames, COL), 'id', '7', '250')


def test_msd_replacement_id_cannot_hide_missing_selected_atom():
    """Equal type counts cannot conceal replacement of a tracked physical atom."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    frames = [_frame([[7, 1, 1, 1, 1], [8, 2, 5, 1, 1]]),
              _frame([[9, 1, 2, 1, 1], [8, 2, 5, 1, 1]], 250)]
    # Same population is not enough: ID 9 cannot stand in for missing ID 7.
    _value_error(lambda: analyze_msd(frames, COL, species_type=1), 'id', '7', '250')


def test_msd_removing_unselected_atom_is_allowed():
    """Atoms outside the initial cohort may disappear without invalidating its MSD."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    for dtype in (np.float32, np.float64):
        frames = [_frame([[7, 1, 1, 1, 1], [8, 2, 5, 1, 1]], dtype=dtype),
                  _frame([[7, 1, 2, 1, 1]], 100, dtype)]
        _assert_msd(analyze_msd(frames, COL, species_type=1), [0, 1])


def test_msd_rejects_duplicate_initial_ids():
    """Ambiguous initial IDs are invalid even outside the selected cohort."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    frames = [_frame([[7, 1, 1, 1, 1], [7, 2, 5, 1, 1]]),
              _frame([[7, 1, 2, 1, 1], [8, 2, 5, 1, 1]], 100)]
    # Duplicates anywhere make the ID map ambiguous, not only in the cohort.
    _value_error(lambda: analyze_msd(frames, COL, species_type=1), 'id')


def test_msd_rejects_duplicate_later_ids():
    """Later duplicate IDs must fail before an ambiguous identity map is used."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    frames = [_frame([[7, 1, 1, 1, 1], [8, 2, 5, 1, 1]]),
              _frame([[7, 1, 2, 1, 1], [8, 2, 5, 1, 1],
                      [8, 2, 6, 1, 1]], 100)]
    _value_error(lambda: analyze_msd(frames, COL, species_type=1), 'id')


def test_msd_requires_explicit_id_column():
    """A multi-frame trajectory cannot infer persistent identity from row order."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    frames = [_frame([[1, 1, 1, 1, 1]]), _frame([[1, 1, 2, 1, 1]], 100)]
    columns = {key: value for key, value in COL.items() if key != 'id'}
    _value_error(lambda: analyze_msd(frames, columns), 'id')


def test_msd_rejects_invalid_initial_ids():
    """Initial IDs must be finite positive integers, including unselected rows."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    for bad in (float('nan'), float('inf'), -float('inf'), 1.5, 0, -3):
        frames = [_frame([[7, 1, 1, 1, 1], [bad, 2, 5, 1, 1]]),
                  _frame([[7, 1, 2, 1, 1], [8, 2, 5, 1, 1]], 100)]
        _value_error(lambda: analyze_msd(frames, COL, species_type=1), 'id')


def test_msd_rejects_invalid_later_ids():
    """Identity validation applies to subsequent frames, not just initialization."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    for bad in (float('nan'), float('inf'), -float('inf'), 1.5, 0, -3):
        frames = [_frame([[7, 1, 1, 1, 1], [8, 2, 5, 1, 1]]),
                  _frame([[7, 1, 2, 1, 1], [bad, 2, 5, 1, 1]], 100)]
        _value_error(lambda: analyze_msd(frames, COL, species_type=1), 'id')


def test_msd_bulk_z_crossing_and_explicit_slab():
    """A z crossing is 0.2 under bulk MIC but 29.8 for nonperiodic slab z."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    for dtype in (np.float32, np.float64):
        frames = [_frame([[1, 1, 5, 5, 0.1]], dtype=dtype),
                  _frame([[1, 1, 5, 5, 29.9]], 100, dtype)]
        _assert_msd(analyze_msd(frames, COL, pbc=(True, True, True)), [0, 0.04])
        _assert_msd(analyze_msd(frames, COL, pbc=(True, True, False)), [0, 29.8 ** 2])
        _assert_msd(analyze_msd(frames, COL), [0, 29.8 ** 2])


def test_msd_nonperiodic_x_and_periodic_y():
    """Mixed axes add the raw x square and minimum-image y square independently."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    for dtype in (np.float32, np.float64):
        frames = [_frame([[1, 1, 0.1, 0.1, 1]], dtype=dtype),
                  _frame([[1, 1, 9.9, 9.9, 1]], 100, dtype)]
        _assert_msd(analyze_msd(frames, COL, pbc=(False, True, False)),
                    [0, 9.8 ** 2 + 0.2 ** 2])


def test_msd_all_nonperiodic_axes():
    """With no PBC, use all three raw coordinate differences without wrapping."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    for dtype in (np.float32, np.float64):
        frames = [_frame([[1, 1, 0.1, 0.1, 0.1]], dtype=dtype),
                  _frame([[1, 1, 9.9, 9.9, 29.9]], 100, dtype)]
        _assert_msd(analyze_msd(frames, COL, pbc=[False, False, False]),
                    [0, 2 * 9.8 ** 2 + 29.8 ** 2])


def test_msd_multiframe_unwrapping_accumulates_displacement():
    """Successive unit steps across a boundary accumulate to squares 0, 1, 4, 9."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    for dtype in (np.float32, np.float64):
        frames = [_frame([[1, 1, x, 1, 1]], 50 * k, dtype)
                  for k, x in enumerate((8.5, 9.5, 0.5, 1.5))]
        _assert_msd(analyze_msd(frames, COL), [0, 1, 4, 9], [0, 0.05, 0.1, 0.15])


def test_msd_static_crystal_analytic_vibration():
    """Known orthogonal vibrations average by ID and return exactly to the origin."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    for dtype in (np.float32, np.float64):
        initial = [[1, 1, 2, 2, 2], [2, 1, 5, 5, 5], [3, 1, 8, 8, 8]]
        # Independent displacements (0.25,0,0), (0,0.5,0), (0,0,0.75).
        displaced = [[3, 1, 8, 8, 8.75], [1, 1, 2.25, 2, 2],
                     [2, 1, 5, 5.5, 5]]
        frames = [_frame(initial, dtype=dtype), _frame(displaced, 100, dtype),
                  _frame(initial, 200, dtype)]
        expected = (0.25 ** 2 + 0.5 ** 2 + 0.75 ** 2) / 3
        _assert_msd(analyze_msd(frames, COL), [0, expected, 0])


def test_msd_rejects_malformed_pbc():
    """Require three booleans rather than silently coercing flags or truthy values."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    frames = [_frame([[1, 1, 1, 1, 1]]), _frame([[1, 1, 2, 1, 1]], 100)]
    for pbc in (None, True, (), (True, False), (True, True, False, True),
                (1, 1, 0), ('p', 'p', 'f'), 'ppf', (True, None, False)):
        _value_error(lambda: analyze_msd(frames, COL, pbc=pbc), 'pbc')


def test_msd_rejects_malformed_box_shape():
    """Reject non-bounds matrices in either frame instead of discarding tilt data."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    for index in (0, 1):
        frames = [_frame([[1, 1, 1, 1, 1]]), _frame([[1, 1, 2, 1, 1]], 100)]
        # An arbitrary 3x3 matrix is not an orthogonal (lo, hi) bounds array.
        frames[index] = _frame([[1, 1, 1, 1, 1]], index * 100,
                               box=((0, 10, 1), (0, 10, 2), (0, 30, 3)))
        _value_error(lambda: analyze_msd(frames, COL))


def test_msd_rejects_nonpositive_or_nonfinite_box_lengths():
    """Every box axis must have a finite positive length, even without PBC."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    for index in (0, 1):
        for upper in (0, -1, float('nan'), float('inf')):
            frames = [_frame([[1, 1, 1, 1, 1]]), _frame([[1, 1, 2, 1, 1]], 100)]
            # z validation is required even when z is not periodic.
            frames[index] = _frame([[1, 1, 1, 1, 1]], index * 100,
                                   box=((0, 10), (0, 10), (0, upper)))
            _value_error(lambda: analyze_msd(frames, COL, pbc=(False, False, False)))


def test_msd_short_input_returns_none_without_id_requirement():
    """Insufficient frames produce no curve before per-atom identity is needed."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    columns = {key: value for key, value in COL.items() if key != 'id'}
    assert analyze_msd([], columns) is None
    assert analyze_msd([_frame([[1, 1, 1, 1, 1]])], columns) is None


def test_msd_empty_initial_selection_returns_none():
    """No initial cohort means no MSD, even if matching types appear later."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    frames = [_frame([[1, 1, 1, 1, 1]]), _frame([[1, 2, 2, 1, 1]], 100)]
    columns = {key: value for key, value in COL.items() if key != 'id'}
    assert analyze_msd(frames, columns, species_type=9) is None
    empty = [_frame([]), _frame([], 100)]
    assert analyze_msd(empty, columns) is None


def test_msd_rejects_nonfinite_selected_positions():
    """Invalid tracked coordinates must fail rather than contaminate a curve."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    for index in (0, 1):
        for bad in (float('nan'), float('inf'), -float('inf')):
            frames = [_frame([[1, 1, 1, 1, 1]]), _frame([[1, 1, 2, 1, 1]], 100)]
            frames[index]['atoms'][0, COL['x']] = bad
            _value_error(lambda: analyze_msd(frames, COL), 'position')


def test_msd_ignores_unselected_nonfinite_positions():
    """Untracked bad coordinates must not invalidate a finite selected trajectory."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    frames = [_frame([[1, 1, 1, 1, 1], [2, 2, float('nan'), 1, 1]]),
              _frame([[1, 1, 2, 1, 1], [2, 2, float('inf'), 1, 1]], 100)]
    _assert_msd(analyze_msd(frames, COL, species_type=1), [0, 1])


def test_msd_rejects_invalid_species_type_parameters():
    """Numeric type selection excludes booleans, labels and nonpositive IDs."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    frames = [_frame([[1, 1, 1, 1, 1]]), _frame([[1, 1, 2, 1, 1]], 100)]
    for selection in (True, False, 1.5, 'A', {0}, {-1}, {1.5}, {True}):
        _value_error(lambda: analyze_msd(frames, COL, species_type=selection), 'type')


def test_shell_msd_failure_does_not_leave_stale_cached_result():
    """A failed recomputation removes only its own formerly valid cached curve."""
    _util.require_numpy()
    from lammps_post.shell import LammpsPostShell
    shell = LammpsPostShell()
    state = shell.state
    state.ff_info['atom_types'] = {1: 'A', 2: 'B'}
    state.dump_col_idx = COL
    state.dump_frames = [_frame([[7, 1, 1, 1, 1], [8, 2, 5, 1, 1]]),
                         _frame([[7, 1, 2, 1, 1], [8, 2, 5, 1, 1]], 100)]
    with _util.noninteractive():
        shell._analyze_msd(['--species', 'A'], _batch=True)
    _assert_msd(state.cache['msd_A'], [0, 1])
    state.cache['unrelated'] = 'preserve me'
    # A validation error on a later attempt must not leave the earlier curve
    # available for plotting as if it belonged to this failed computation.
    state.dump_frames[1] = _frame([[8, 2, 5, 1, 1]], 100)
    with _util.noninteractive():
        _value_error(lambda: shell._analyze_msd(['--species', 'A'], _batch=True), 'id')
    assert 'msd_A' not in state.cache, 'a failed MSD must invalidate its old curve'
    assert state.cache['unrelated'] == 'preserve me'
