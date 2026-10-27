"""PHYS-3: periodic candidates and explicit validation for O2 counts.

These are synthetic geometric tests, not a chemical bond-order model.
"""
import itertools
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import _util


COL = {'id': 0, 'type': 1, 'x': 2, 'y': 3, 'z': 4}
BOX = ((0, 10), (0, 10), (0, 30))


def _frame(rows, box=BOX, step=0):
    import numpy as np
    return {'atoms': np.asarray(rows, float).reshape((-1, 5)),
            'box': np.asarray(box, float), 'timestep': step}


def _value_error(call):
    try:
        call()
    except ValueError as exc:
        assert str(exc).strip(), 'validation must explain the invalid input'
    else:
        raise AssertionError('expected an informative ValueError')


def _require_scipy():
    try:
        import scipy.spatial  # noqa: F401
    except ImportError:
        _util.skip('scipy not installed: periodic tree candidate check')


def _crossing(axis, large=False):
    pos = [5., 5., 5.]
    other = pos.copy()
    pos[axis], other[axis] = 0.3, 59.7
    rows = [[1, 4] + pos, [2, 7] + other]
    if large:
        rows += [[k + 3, 4, 15 + 4 * (k % 5),
                  15 + 4 * (k // 5), 30] for k in range(19)]
    return _frame(rows, ((0, 60),) * 3)


def test_o2_detected_across_x_boundary_on_tree_path():
    _util.require_numpy()
    from lammps_post.analysis import detect_o2_dissociation
    # Original pending repro: 19 isolated atoms select the old n > 20 path.
    rows = [[1, 2, 0.3, 5, 5], [2, 2, 9.7, 5, 5]]
    for k in range(19):
        rows.append([3 + k, 2, (k % 5) * 2 + 1,
                     (k // 5) * 2 + 1, 15 + (k % 3) * 4])
    result = detect_o2_dissociation([_frame(rows)], COL,
                                    bond_cutoff=1.5, o_type=2)
    assert result['n_o2'][0] == 1, f"boundary O2 missed: {result['n_o2'][0]}"


def test_o2_each_axis_obeys_all_eight_pbc_combinations():
    _util.require_numpy()
    from lammps_post.analysis import detect_o2_dissociation
    for pbc in itertools.product((False, True), repeat=3):
        for axis in range(3):
            result = detect_o2_dissociation([_crossing(axis)], COL,
                                            o_type={4, 7}, pbc=pbc)
            assert result['n_o2'].tolist() == [int(pbc[axis])], (pbc, axis)


def test_o2_large_boundary_pairs_really_use_periodic_tree():
    _util.require_numpy()
    _require_scipy()
    from scipy.spatial import cKDTree
    from lammps_post.analysis import detect_o2_dissociation
    for axis in range(3):
        with patch('scipy.spatial.cKDTree', wraps=cKDTree) as tree:
            result = detect_o2_dissociation([_crossing(axis, large=True)], COL,
                                            o_type={4, 7}, pbc=(True,) * 3)
        assert tree.call_count > 0, 'test must exercise the SciPy tree'
        assert any(call.kwargs.get('boxsize') is not None
                   for call in tree.call_args_list), 'candidate search must be periodic'
        assert result['n_o2'].tolist() == [1], axis
        assert result['n_total_o'].tolist() == [21], axis


def test_o2_legacy_default_is_xy_periodic_z_nonperiodic():
    _util.require_numpy()
    from lammps_post.analysis import detect_o2_dissociation
    for axis in range(3):
        # Use one scalar type while retaining both atoms in this legacy call.
        frame = _crossing(axis)
        frame['atoms'][:, 1] = 4
        result = detect_o2_dissociation([frame], COL, o_type=4)
        assert result['n_o2'].tolist() == [int(axis != 2)]


def test_o2_periodic_out_of_box_positions_and_nonzero_origins():
    _util.require_numpy()
    import numpy as np
    from lammps_post import analysis
    box = np.asarray(((-17, 43), (8, 68), (-25, 35)), float)
    for axis in range(3):
        frame = _crossing(axis, large=True)
        frame['box'] = box.copy()
        frame['atoms'][:, 2:5] += box[:, 0]
        frame['atoms'][0, axis + 2] += 3 * 60
        frame['atoms'][1, axis + 2] -= 2 * 60
        pbc = tuple(dim == axis for dim in range(3))
        for force_fallback in (False, True):
            with patch.object(analysis, '_rdf_candidate_pairs', return_value=None) if force_fallback else nullcontext():
                result = analysis.detect_o2_dissociation(
                    [frame], COL, o_type={4, 7}, pbc=pbc)
            assert result['n_o2'].tolist() == [1], (axis, force_fallback)


def test_o2_candidate_helper_supports_every_periodic_axis():
    _util.require_numpy()
    _require_scipy()
    from lammps_post.analysis import _rdf_candidate_pairs
    for pbc in itertools.product((False, True), repeat=3):
        for axis in range(3):
            frame = _crossing(axis)
            pos = frame['atoms'][:, 2:5]
            candidates = _rdf_candidate_pairs(pos, pos, frame['box'], 1.5,
                                               False, same_species=True, pbc=pbc)
            assert candidates is not None
            ia, ib, weight = candidates
            assert len(ia) == len(ib) == int(pbc[axis]), (pbc, axis)
            assert weight == 2
            if pbc[axis]:
                assert {int(ia[0]), int(ib[0])} == {0, 1}


def test_o2_candidate_helper_keeps_legacy_rdf_z_pbc_semantics():
    _util.require_numpy()
    _require_scipy()
    from lammps_post.analysis import _rdf_candidate_pairs
    for z_pbc in (False, True):
        for axis in range(3):
            frame = _crossing(axis)
            pos = frame['atoms'][:, 2:5]
            ia, ib, weight = _rdf_candidate_pairs(
                pos, pos, frame['box'], 1.5, z_pbc, same_species=True)
            assert len(ia) == len(ib) == int(axis != 2 or z_pbc)
            assert weight == 2


def test_o2_rejects_malformed_pbc():
    _util.require_numpy()
    from lammps_post.analysis import detect_o2_dissociation
    for pbc in (None, True, (), (True, True), (True,) * 4,
                (1, 0, 1), ('p', 'p', 'f'), (True, None, False)):
        _value_error(lambda: detect_o2_dissociation([_crossing(0)], COL,
                                                   o_type=4, pbc=pbc))


def test_o2_rejects_invalid_cutoff():
    _util.require_numpy()
    from lammps_post.analysis import detect_o2_dissociation
    for cutoff in (0, -1, float('nan'), float('inf'), 'bad', None):
        _value_error(lambda: detect_o2_dissociation([_crossing(0)], COL,
                                                   bond_cutoff=cutoff, o_type=4))


def test_o2_rejects_invalid_or_triclinic_boxes_even_without_pairs():
    _util.require_numpy()
    from lammps_post.analysis import detect_o2_dissociation
    boxes = (((0, 0), (0, 10), (0, 10)),
             ((1, 0), (0, 10), (0, 10)),
             ((0, float('nan')), (0, 10), (0, 10)),
             ((0, 10), (0, float('inf')), (0, 10)),
             ((0, 10), (0, 10)),
             ((0, 10, 0.5), (0, 10, 0), (0, 10, 0)))
    for box in boxes:
        for rows in ([], [[1, 4, 1, 1, 1]],
                     [[1, 4, 1, 1, 1], [2, 4, 2, 1, 1]]):
            _value_error(lambda: detect_o2_dissociation([_frame(rows, box)], COL,
                                                       o_type=4))


def test_o2_rejects_nonfinite_selected_coordinates_only():
    _util.require_numpy()
    from lammps_post.analysis import detect_o2_dissociation
    for bad in (float('nan'), float('inf'), -float('inf')):
        for axis in range(3):
            row = [1, 4, 1, 1, 1]
            row[axis + 2] = bad
            _value_error(lambda: detect_o2_dissociation([_frame([row])], COL,
                                                       o_type=4))
            row[1] = 9
            result = detect_o2_dissociation(
                [_frame([row, [2, 4, 1, 1, 1], [3, 4, 2, 1, 1]])], COL,
                o_type=4)
            assert result['n_o2'].tolist() == [1]


def test_o2_rejects_invalid_type_selectors():
    _util.require_numpy()
    from lammps_post.analysis import detect_o2_dissociation
    for selector in (None, True, 0, -1, 4.5, '4', (), [], {4, 7.5},
                     [4, float('nan')], [4, True], [[4]]):
        _value_error(lambda: detect_o2_dissociation([_crossing(0)], COL,
                                                   o_type=selector))


def test_o2_rejects_invalid_selected_ids_but_ignores_unselected_ids():
    _util.require_numpy()
    from lammps_post.analysis import detect_o2_dissociation
    for bad_id in (0, -1, 1.5, float('nan'), float('inf'), 2):
        frame = _frame([[bad_id, 4, 1, 1, 1], [2, 4, 2, 1, 1]])
        _value_error(lambda: detect_o2_dissociation([frame], COL, o_type=4))
    frame = _frame([[1, 4, 1, 1, 1], [2, 4, 2, 1, 1],
                    [float('nan'), 9, 5, 5, 5], [1, 9, 7, 7, 7]])
    assert detect_o2_dissociation([frame], COL, o_type=4)['n_o2'].tolist() == [1]


def _shell(boundary, input_boundary, surface_z):
    from lammps_post.shell import LammpsPostShell

    class Frames(list):
        pass

    frames = Frames([_crossing(2)])
    frames.reader = SimpleNamespace(boundary=boundary)
    shell = LammpsPostShell.__new__(LammpsPostShell)
    shell.state = SimpleNamespace(
        dump_frames=frames, dump_col_idx=COL, dt_fs=2,
        input_config={'boundary': input_boundary} if input_boundary else None,
        surface_z=surface_z, cache={}, _guess_o_type=lambda: {4, 7})
    return shell


def test_o2_shell_routes_dump_input_and_surface_periodicity():
    _util.require_numpy()
    from lammps_post import shell as module
    cases = ((('ff', 'pp', 'pp'), ['p', 'f', 'f'], 5, (False, True, True)),
             (None, ['f', 'p', 'f'], None, (False, True, False)),
             (None, None, 5, (True, True, False)),
             (None, None, None, (True, True, True)))
    for boundary, input_boundary, surface_z, expected in cases:
        shell = _shell(boundary, input_boundary, surface_z)
        shell.state.cache = {'dissociation': 'old', 'rdf': 'keep'}

        def detect(frames, columns, **kwargs):
            assert kwargs['pbc'] == expected
            assert kwargs['o_type'] == {4, 7}
            assert kwargs['dt_fs'] == 2
            assert frames is shell.state.dump_frames and columns is COL
            assert 'dissociation' not in shell.state.cache
            return {'n_o2': [], 'n_dissociated': []}

        with patch.object(module, 'detect_o2_dissociation', side_effect=detect) as call:
            with _util.noninteractive():
                shell._analyze_dissociation([])
        assert call.call_count == 1
        assert shell.state.cache['rdf'] == 'keep'
        assert shell.state.cache['dissociation'] == {'n_o2': [], 'n_dissociated': []}


def test_o2_shell_failed_computation_invalidates_only_dissociation_cache():
    _util.require_numpy()
    from lammps_post import shell as module
    shell = _shell(('pp', 'pp', 'pp'), None, None)
    shell.state.cache = {'dissociation': 'stale', 'msd_X': 'keep'}
    with patch.object(module, 'detect_o2_dissociation',
                      side_effect=ValueError('invalid synthetic frame')):
        with _util.noninteractive():
            _value_error(lambda: shell._analyze_dissociation([]))
    assert shell.state.cache == {'msd_X': 'keep'}
