"""PHYS-5: globally shortest-first geometric pairing, not bond order.

The heuristic is deliberately NOT maximum-cardinality matching. Reference
counts enumerate periodic images independently of the production helper.
"""
import itertools
from contextlib import nullcontext
from unittest.mock import patch

import _util


COL = {'id': 0, 'type': 1, 'x': 2, 'y': 3, 'z': 4}
BOX = ((0, 40),) * 3
CHAIN = [[1, 2, 5, 5, 5], [2, 2, 6., 5, 5],
         [3, 2, 6.5, 5, 5], [4, 2, 7.5, 5, 5]]


def _frame(rows, box=BOX, step=0):
    import numpy as np
    return {'atoms': np.asarray(rows, float).reshape((-1, 5)),
            'box': np.asarray(box, float), 'timestep': step}


def _far(n=17):
    return [[10 + k, 2, 20 + (k % 4) * 4, 20 + (k // 4) * 4, 30]
            for k in range(n)]


def _assert_counts(result, pairs, totals):
    import numpy as np
    pairs, totals = np.asarray(pairs), np.asarray(totals)
    dissociated = totals - 2 * pairs
    np.testing.assert_array_equal(result['n_o2'], pairs)
    np.testing.assert_array_equal(result['n_total_o'], totals)
    np.testing.assert_array_equal(result['n_dissociated'], dissociated)
    np.testing.assert_array_equal(2 * result['n_o2'] + result['n_dissociated'], totals)
    for key, numerator in (('frac_in_o2', 2 * pairs),
                           ('frac_dissociated', dissociated)):
        expected = np.divide(numerator, totals, out=np.zeros(len(totals)), where=totals > 0)
        np.testing.assert_allclose(result[key], expected, rtol=0, atol=1e-15)
        assert np.all(np.isfinite(result[key]))


def _reference(frame, pbc, cutoff, types=(4, 7), with_ids=True):
    """Enumerate 27 (or fewer) images, then sort every candidate globally."""
    import numpy as np
    rows = frame['atoms'][np.isin(frame['atoms'][:, 1], list(types))]
    lengths = frame['box'][:, 1] - frame['box'][:, 0]
    pos = rows[:, 2:5].copy()
    for axis, periodic in enumerate(pbc):
        if periodic:
            pos[:, axis] = ((pos[:, axis] - frame['box'][axis, 0])
                            % lengths[axis] + frame['box'][axis, 0])
    images = list(itertools.product(*[(-1, 0, 1) if periodic else (0,)
                                     for periodic in pbc]))
    candidates = []
    for i, j in itertools.combinations(range(len(rows)), 2):
        distance = min(float(np.linalg.norm(pos[j] + np.asarray(image) * lengths - pos[i]))
                       for image in images)
        if distance < cutoff:
            keys = (int(rows[i, 0]), int(rows[j, 0])) if with_ids else (
                tuple(pos[i]), tuple(pos[j]))
            low, high = sorted(keys)
            candidates.append((distance, low, high, i, j))
    used, count = set(), 0
    for _, _, _, i, j in sorted(candidates):
        if i not in used and j not in used:
            used.update((i, j))
            count += 1
    return count, len(rows)


def test_o2_count_independent_of_total_o_count():
    _util.require_numpy()
    from lammps_post.analysis import detect_o2_dissociation
    # Original pending PHYS-5 repro, unchanged physical expectation.
    a = detect_o2_dissociation([_frame(CHAIN)], COL,
                               bond_cutoff=1.5, o_type=2)['n_o2'][0]
    b = detect_o2_dissociation([_frame(CHAIN + _far())], COL,
                               bond_cutoff=1.5, o_type=2)['n_o2'][0]
    assert a == b, f'pairing depends on code path: {a} (n=4) vs {b} (n=21)'


def test_o2_global_shortest_first_is_not_maximum_cardinality():
    _util.require_numpy()
    from lammps_post import analysis
    for extra in ([], _far()):
        for fallback in (False, True):
            with patch.object(analysis, '_rdf_candidate_pairs', return_value=None) if fallback else nullcontext():
                result = analysis.detect_o2_dissociation(
                    [_frame(CHAIN + extra)], COL, bond_cutoff=1.5, o_type=2)
            # Middle gap 0.5 wins; the remaining ends are 2.5 apart. A maximum
            # matching could use the two outer 1.0 gaps, but that is not this API.
            _assert_counts(result, [1], [4 + len(extra)])


def test_o2_row_permutations_do_not_change_unique_distance_pairing():
    _util.require_numpy()
    from lammps_post.analysis import detect_o2_dissociation
    for rows in itertools.permutations(CHAIN):
        for extra in ([], _far()):
            result = detect_o2_dissociation([_frame(list(rows) + extra)], COL,
                                            bond_cutoff=1.5, o_type=2)
            _assert_counts(result, [1], [4 + len(extra)])


def test_o2_exact_distance_ties_use_atom_ids_not_row_order():
    _util.require_numpy()
    from lammps_post import analysis
    # All nearest gaps are exactly 1. Center IDs (1,2) must win in the first
    # assignment; outer IDs (1,2) must win in the second. Counts distinguish them.
    for ids, expected in (((3, 1, 2, 4), 1), ((1, 2, 3, 4), 2)):
        rows = [[atom_id, 2, 5 + k, 5, 5] for k, atom_id in enumerate(ids)]
        for perm in itertools.permutations(rows):
            for extra in ([], _far()):
                for fallback in (False, True):
                    with patch.object(analysis, '_rdf_candidate_pairs', return_value=None) if fallback else nullcontext():
                        result = analysis.detect_o2_dissociation(
                            [_frame(list(perm) + extra)], COL, bond_cutoff=1.1, o_type=2)
                    _assert_counts(result, [expected], [4 + len(extra)])


def test_o2_without_id_column_uses_stable_coordinate_ties():
    _util.require_numpy()
    from lammps_post import analysis
    columns = {name: index for name, index in COL.items() if name != 'id'}
    rows = [[0, 2, 5 + k, 5, 5] for k in range(4)]
    # IDs are deliberately unusable, but are not part of the supplied schema.
    for perm in itertools.permutations(rows):
        for extra in ([], _far()):
            for fallback in (False, True):
                with patch.object(analysis, '_rdf_candidate_pairs', return_value=None) if fallback else nullcontext():
                    result = analysis.detect_o2_dissociation(
                        [_frame(list(perm) + extra)], columns, bond_cutoff=1.1, o_type=2)
                _assert_counts(result, [2], [4 + len(extra)])


def test_o2_without_ids_uses_canonical_ties_for_shifted_periodic_images():
    _util.require_numpy()
    from lammps_post import analysis
    columns = {name: index for name, index in COL.items() if name != 'id'}
    # Canonical x=5,6,7,8 has equal nearest gaps; shifting individual atoms by
    # whole boxes must not replace the deterministic coordinate tie order.
    rows = [[0, 2, 5 + k + image * 40, 5, 5]
            for k, image in enumerate((1, -2, 3, -1))]
    for extra in ([], _far()):
        for perm in itertools.permutations(rows):
            frame = _frame(list(perm) + extra)
            expected, total = _reference(frame, (True,) * 3, 1.1,
                                          types=(2,), with_ids=False)
            assert expected == 2
            for fallback in (False, True):
                with patch.object(analysis, '_rdf_candidate_pairs', return_value=None) if fallback else nullcontext():
                    result = analysis.detect_o2_dissociation(
                        [frame], columns, bond_cutoff=1.1, o_type=2, pbc=(True,) * 3)
                _assert_counts(result, [expected], [total])


def test_o2_random_frames_match_independent_image_greedy_reference():
    _util.require_numpy()
    import numpy as np
    from lammps_post import analysis
    rng = np.random.default_rng(305)
    box = np.asarray(((-3, 4), (8, 14), (-11, -3)), float)
    lengths = box[:, 1] - box[:, 0]
    for pbc in itertools.product((False, True), repeat=3):
        for n in (7, 33):
            pos = box[:, 0] + rng.random((n, 3)) * lengths
            for axis, periodic in enumerate(pbc):
                if periodic:
                    pos[:, axis] += rng.integers(-3, 4, n) * lengths[axis]
            rows = np.column_stack((rng.permutation(np.arange(1, n + 1)),
                                    rng.choice((4, 7), n), pos))
            frame = _frame(rows, box)
            expected, total = _reference(frame, pbc, 1.8)
            regular = analysis.detect_o2_dissociation(
                [frame], COL, o_type={4, 7}, pbc=pbc)
            with patch.object(analysis, '_rdf_candidate_pairs', return_value=None) as helper:
                fallback = analysis.detect_o2_dissociation(
                    [frame], COL, o_type={4, 7}, pbc=pbc)
            if n > 20:
                assert helper.call_count > 0, 'fallback must disable actual candidate search'
            _assert_counts(regular, [expected], [total])
            _assert_counts(fallback, [expected], [total])
            for key in regular:
                np.testing.assert_array_equal(regular[key], fallback[key])


def test_o2_tree_and_forced_fallback_agree_with_scipy_available():
    _util.require_numpy()
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        _util.skip('scipy not installed: accelerated/fallback equality')
    from lammps_post import analysis
    with patch('scipy.spatial.cKDTree', wraps=cKDTree) as tree:
        accelerated = analysis.detect_o2_dissociation(
            [_frame(CHAIN + _far())], COL, bond_cutoff=1.5, o_type=2)
    assert tree.call_count > 0
    with patch.object(analysis, '_rdf_candidate_pairs', return_value=None) as helper:
        fallback = analysis.detect_o2_dissociation(
            [_frame(CHAIN + _far())], COL, bond_cutoff=1.5, o_type=2)
    assert helper.call_count > 0
    _assert_counts(accelerated, [1], [21])
    _assert_counts(fallback, [1], [21])


def test_o2_empty_singleton_and_multiframe_populations_are_preserved():
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import detect_o2_dissociation
    frames = [_frame([], step=0),
              _frame([[8, 4, 1, 1, 1]], step=50),
              _frame([[8, 4, 1, 1, 1], [9, 7, 2, 1, 1],
                      [10, 4, 8, 8, 8]], step=100),
              _frame([[8, 9, 1, 1, 1]], step=150)]
    result = detect_o2_dissociation(frames, COL, o_type={4, 7}, dt_fs=2)
    _assert_counts(result, [0, 0, 1, 0], [0, 1, 3, 0])
    np.testing.assert_allclose(result['time'], [0, 0.1, 0.2, 0.3])


def test_o2_cutoff_is_strict_including_tree_radius_margin():
    _util.require_numpy()
    import numpy as np
    from lammps_post import analysis
    for distance, expected in ((0., 1), (np.nextafter(1.5, 0), 1),
                               (1.5, 0), (np.nextafter(1.5, 2), 0)):
        for extra in ([], _far()):
            rows = [[1, 2, 0, 5, 5], [2, 2, distance, 5, 5]] + extra
            for fallback in (False, True):
                with patch.object(analysis, '_rdf_candidate_pairs', return_value=None) if fallback else nullcontext():
                    result = analysis.detect_o2_dissociation(
                        [_frame(rows)], COL, bond_cutoff=1.5, o_type=2)
                _assert_counts(result, [expected], [2 + len(extra)])


def test_o2_numeric_type_groups_accept_iterables_and_numpy_integer():
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import detect_o2_dissociation
    rows = [[1, 4, 1, 1, 1], [2, 7, 2, 1, 1],
            [3, 9, 8, 8, 8], [4, 4, 20, 20, 20]]
    for selector in ({4, 7}, [4, 7], (4, 7), iter((4, 7)), np.array([4, 7])):
        result = detect_o2_dissociation([_frame(rows), _frame(rows, step=10)],
                                        COL, o_type=selector)
        _assert_counts(result, [1, 1], [3, 3])
    for selector in (4, np.int64(4), {4}, iter((4,))):
        result = detect_o2_dissociation([_frame(rows)], COL, o_type=selector)
        _assert_counts(result, [0], [2])


def test_o2_instantaneous_counts_allow_types_and_id_population_to_change():
    _util.require_numpy()
    from lammps_post.analysis import detect_o2_dissociation
    frames = [_frame([[1, 4, 1, 1, 1], [2, 7, 2, 1, 1]]),
              _frame([[1, 9, 1, 1, 1], [8, 4, 2, 1, 1]], step=10),
              _frame([[9, 7, 1, 1, 1], [8, 4, 2, 1, 1]], step=20)]
    _assert_counts(detect_o2_dissociation(frames, COL, o_type={4, 7}),
                   [1, 0, 1], [2, 1, 2])


def test_o2_does_not_modify_input_atoms_or_boxes():
    _util.require_numpy()
    import numpy as np
    from lammps_post import analysis
    frame = _frame(CHAIN + _far())
    frame['atoms'][0, 2] += 3 * 40
    atoms, box = frame['atoms'].copy(), frame['box'].copy()
    frame['atoms'].flags.writeable = False
    frame['box'].flags.writeable = False
    for fallback in (False, True):
        with patch.object(analysis, '_rdf_candidate_pairs', return_value=None) if fallback else nullcontext():
            result = analysis.detect_o2_dissociation(
                [frame], COL, bond_cutoff=1.5, o_type=2)
        _assert_counts(result, [1], [21])
        np.testing.assert_array_equal(frame['atoms'], atoms)
        np.testing.assert_array_equal(frame['box'], box)
