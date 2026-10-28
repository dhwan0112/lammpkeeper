"""Independent small-system RDF/MSD oracles for the accepted GEN-3 scope.

Literal Cartesian lattice rows and bounded exhaustive image enumeration define
the expectations; production Box transforms and MIC never generate the oracle.
These synthetic tests establish algorithm behavior, not material dynamics.
"""
import itertools
from unittest.mock import patch
import warnings

import _util


COL = dict(id=0, type=1, x=2, y=3, z=4, q=5)


def _frame(positions, types=None, step=0, lo=(2, -3, 4),
           lengths=(3, 4, 5), tilt=(1.1, -.8, .7), pbc=(True, True, True)):
    """Construct a typed frame and separate literal Cartesian basis oracle."""
    import numpy as np
    from lammpkeeper.io import Box
    pos = np.asarray(positions, float).reshape(-1, 3)
    n = len(pos)
    if types is None:
        types = [4] * n
    cell = Box(lo, np.asarray(lo) + lengths, tilt=tilt, pbc=pbc)
    rows = np.column_stack((np.arange(1, n + 1), types, pos, np.zeros(n)))
    h = np.array([[lengths[0], 0, 0], [tilt[0], lengths[1], 0],
                  [tilt[1], tilt[2], lengths[2]]], float)
    return dict(atoms=rows, cell=cell, box=cell.bounds, tilt=tilt, timestep=step), h


def _image(delta, h, pbc):
    """Find an image by exhaustive Cartesian enumeration for these tiny cells.

    The finite [-8, 8] coefficient range is specific to the literal positions
    and tilts below, not a general MIC guarantee. Norm comparisons are ordinary
    float64; core geometry tests, not this oracle, cover exact near-tie ordering.
    """
    import numpy as np
    shifts = itertools.product(*(range(-8, 9) if flag else (0,) for flag in pbc))
    candidates = np.asarray(delta) - np.asarray(list(shifts)) @ h
    norms = np.sum(candidates * candidates, axis=1)
    return candidates[np.argmin(norms)]


def _wrap(pos, lo, h, pbc):
    """Wrap prescribed walks using explicit restricted-cell coordinate algebra."""
    import numpy as np
    shifted = np.asarray(pos) - lo
    sz = shifted[:, 2] / h[2, 2]
    sy = (shifted[:, 1] - sz * h[2, 1]) / h[1, 1]
    sx = (shifted[:, 0] - sy * h[1, 0] - sz * h[2, 0]) / h[0, 0]
    frac = np.column_stack((sx, sy, sz))
    for dim, flag in enumerate(pbc):
        if flag:
            frac[:, dim] -= np.floor(frac[:, dim])
    return np.asarray(lo) + frac @ h


def _reject(call, needle):
    """Require a visible, informative geometry error."""
    try:
        call()
    except ValueError as exc:
        assert needle.lower() in str(exc).lower(), str(exc)
    else:
        raise AssertionError('expected ValueError')


def _rdf_oracle(frame, h, a, b, r_max, n_bins):
    """Count directed pairs independently and normalize by literal determinant."""
    import numpy as np
    atoms = frame['atoms']
    left = atoms[np.isin(atoms[:, 1], list(a)), 2:5]
    right = atoms[np.isin(atoms[:, 1], list(b)), 2:5]
    hist = np.zeros(n_bins)
    for p in left:
        for q in right:
            d = _image(q - p, h, frame['cell'].pbc)
            radius = np.sqrt(np.dot(d, d))
            if 0 < radius < r_max:
                index = int(radius / (r_max / n_bins))
                if index < n_bins:
                    hist[index] += 1
    edges = np.linspace(0, r_max, n_bins + 1)
    shell = 4 * np.pi / 3 * np.diff(edges ** 3)
    volume = h[0, 0] * h[1, 1] * h[2, 2]
    return hist / (len(left) * shell * (len(right) / volume))


def test_triclinic_rdf_directed_species_unions_and_dynamic_cells():
    """Same, cross and overlapping unions match independent instantaneous curves."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf
    positions = [[2.1, -2.8, 4.1], [4.9, -2.8, 4.1], [3.3, .7, 4.2],
                 [2.8, -1, 8.7], [2.1, -2.8, 4.1]]
    frames_h = [_frame(positions, [4, 4, 9, 9, 9]),
                _frame(positions, [4, 4, 9, 9, 9], step=1,
                       lengths=(4, 5, 6), tilt=(-1.2, .6, -1.3))]
    # Some bins exceed the periodic inscribed radius. This tests the documented
    # nearest-image/global-density estimator, not complete spherical sampling.
    for a, b in (({4}, {4}), ({4}, {9}), ({4, 9}, {9})):
        expected = sum(_rdf_oracle(fr, h, a, b, 2.7, 9) for fr, h in frames_h) / 2
        for ordered in (frames_h, frames_h[::-1]):
            # Triclinic calculations must never use the orthogonal tree backend.
            with patch('lammps_post.analysis._rdf_candidate_pairs',
                       side_effect=AssertionError('orthogonal candidate backend used')):
                got = compute_rdf([fr for fr, _ in ordered], COL, a, b,
                                  r_max=2.7, n_bins=9, label_a='A', label_b='B')
            np.testing.assert_allclose(got['g'], expected, rtol=2e-15, atol=0)
            assert got['n_frames'] == 2 and got['label'] == 'A-B'


def test_triclinic_rdf_fractional_rounding_counterexample():
    """A modest tilt makes fractional rounding select the wrong radial bin."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf, _rdf_candidate_pairs
    fr, h = _frame([[0, 0, 0], [.686, .49, 0]], [4, 9], lo=(0, 0, 0),
                   lengths=(1, 1, 1), tilt=(.4, 0, 0))
    shortest = np.sqrt(.314 ** 2 + .49 ** 2)
    assert .5 < shortest < .6
    got = compute_rdf([fr], COL, 4, 9, r_max=1, n_bins=10)
    expected = _rdf_oracle(fr, h, {4}, {9}, 1, 10)
    np.testing.assert_allclose(got['g'], expected)
    assert np.flatnonzero(got['g']).tolist() == [5]
    assert _rdf_candidate_pairs(fr['atoms'][:1, 2:5], fr['atoms'][1:, 2:5],
                                fr['cell'], 1, True) is None


def test_triclinic_rdf_mixed_periodic_vectors_and_strong_tilt():
    """Boundary masks select lattice rows, not uncoupled Cartesian components."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf
    for flags in itertools.product((False, True), repeat=3):
        fr, h = _frame([[0, 0, 0], [2.7, .49, .2], [5.7, 1.1, .9]],
                       [4, 9, 9], lo=(0, 0, 0), lengths=(1, 1, 1),
                       tilt=(5.8, -.7, .4), pbc=flags)
        expected = _rdf_oracle(fr, h, {4}, {9}, 1.2, 12)
        got = compute_rdf([fr], COL, 4, 9, r_max=1.2, n_bins=12, pbc=flags)
        np.testing.assert_allclose(got['g'], expected)


def test_triclinic_rdf_cutoff_edges_volume_and_empty_selection():
    """Exclude zero/cutoff pairs and retain analytic shell/volume normalization."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf
    fr, _ = _frame([[0, 0, 0], [0, 0, 0], [1, 0, 0], [2, 0, 0]],
                   [4, 9, 9, 9], lo=(0, 0, 0), lengths=(10, 10, 10),
                   tilt=(2, 1, 3), pbc=(False, False, False))
    got = compute_rdf([fr], COL, 4, 9, r_max=2, n_bins=2)
    shell = 4 * np.pi / 3 * 7
    np.testing.assert_allclose(got['g'], [0, 1000 / (3 * shell)])
    empty, _ = _frame([], step=1)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        combined = compute_rdf([fr, empty], COL, 4, 9, r_max=2, n_bins=2)
    assert any('empty species selection' in str(w.message) for w in caught)
    np.testing.assert_array_equal(combined['g'], got['g'])
    assert combined['n_frames'] == 1


def test_triclinic_msd_prescribed_walk_all_periodic_subsets():
    """Independent wrapping preserves Cartesian motion, shuffled IDs and swaps."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    origin = np.array([2, -3, 4])
    start = np.array([[4.9, .8, 8.9], [2.2, -2.8, 4.2]])
    velocity = np.array([[.24, .31, .37], [-.21, -.27, -.33]])
    for flags in itertools.product((False, True), repeat=3):
        _, h = _frame(start, pbc=flags)
        frames = []
        for step in range(17):
            wrapped = _wrap(start + step * velocity, origin, h, flags)
            fr, _ = _frame(wrapped, [4, 9] if step == 0 else [9, 4],
                           step=100 + 10 * step, pbc=flags)
            if step % 2:
                fr['atoms'] = fr['atoms'][::-1].copy()
            frames.append(fr)
        for species, expected_speed in ((4, np.dot(velocity[0], velocity[0])),
                                        (None, np.mean(np.sum(velocity ** 2, axis=1)))):
            got = analyze_msd(frames, COL, species_type=species, dt_fs=2, pbc=flags)
            np.testing.assert_allclose(got['msd'], np.arange(17) ** 2 * expected_speed,
                                       rtol=2e-14, atol=1e-14)
            np.testing.assert_allclose(got['time'], np.arange(17) * .02)


def test_triclinic_msd_uses_voronoi_not_fractional_rounding():
    """The accumulated increment is the exact nearest Cartesian lattice image.

    Interpreting the result as physical motion assumes the shorter enumerated
    increment; wrapped endpoints alone cannot prove whether a real trajectory
    instead took a longer aliased path. This asserts reconstruction convention.
    """
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    first, h = _frame([[0, 0, 0]], lo=(0, 0, 0), lengths=(1, 1, 1), tilt=(.4, 0, 0))
    second = dict(first, atoms=first['atoms'].copy(), timestep=1)
    second['atoms'][0, 2:5] = [.686, .49, 0]
    got = analyze_msd([first, second], COL, pbc=(True, True, True))
    expected = _image(np.array([.686, .49, 0]), h, (True, True, True))
    np.testing.assert_allclose(got['msd'], [0, np.dot(expected, expected)])


def test_typed_analysis_rejects_metadata_and_pbc_disagreement():
    """Authoritative cells cannot conceal contradictory compatibility copies."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf, analyze_msd, _orthogonal_box
    fr, _ = _frame([[2, -3, 4], [2.1, -3, 4]], [4, 9])
    bad = [dict(fr, box=fr['box'] + .01), dict(fr, tilt=(0, 0, 0)),
           dict(fr, xy=0), dict(fr, xz=np.nan), dict(fr, yz=[.7]),
           dict(fr, tilt_factors=(1.1, -.8, .8))]
    for broken in bad:
        _reject(lambda: compute_rdf([broken], COL, 4, 9), 'disagree')
        _reject(lambda: _orthogonal_box(broken, 'test'), 'disagree')
    _reject(lambda: compute_rdf([dict(fr, cell=object())], COL, 4, 9), 'Box')
    _reject(lambda: compute_rdf([fr], COL, 4, 9, pbc=(True, True, False)), 'PBC')
    _reject(lambda: analyze_msd([fr, fr], COL), 'PBC')
    unknown = dict(fr, cell=fr['cell'].with_pbc(None))
    for flags in (None, (True, True, True)):
        _reject(lambda: compute_rdf([unknown], COL, 4, 9, pbc=flags), 'unresolved')
    _reject(lambda: analyze_msd([unknown, unknown], COL, pbc=(True, True, True)), 'unresolved')


def test_triclinic_msd_rejects_cell_changes_even_empty_cohort():
    """No deformation, changing origin, flip or mixed geometry is approximated."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd
    first, _ = _frame([[2, -3, 4]], [4])
    changes = [dict(lo=(2.1, -3, 4)), dict(lengths=(3.1, 4, 5)),
               dict(tilt=(1.2, -.8, .7)), dict(tilt=(0, 0, 0)),
               dict(pbc=(True, True, False))]
    for change in changes:
        other, _ = _frame([[2, -3, 4]], [4], step=1, **change)
        for species in (None, 99):
            _reject(lambda: analyze_msd([first, other], COL, species_type=species,
                                       pbc=(True, True, True)),
                    'PBC' if 'pbc' in change else 'constant')
    legacy = {k: v for k, v in first.items() if k not in ('cell', 'tilt')}
    _reject(lambda: analyze_msd([first, legacy], COL, pbc=(True, True, True)), 'mix')


def test_triclinic_msd_preserves_identity_and_position_errors():
    """The supported cell branch never weakens existing atom tracking checks."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    first, _ = _frame([[2, -3, 4], [3, -2, 5]], [4, 9])
    flags = dict(pbc=(True, True, True), species_type=4)
    missing = dict(first, atoms=first['atoms'][1:].copy(), timestep=10)
    _reject(lambda: analyze_msd([first, missing], COL, **flags), 'missing')
    duplicate = dict(first, atoms=first['atoms'].copy(), timestep=10)
    duplicate['atoms'][1, 0] = 1
    _reject(lambda: analyze_msd([first, duplicate], COL, **flags), 'duplicate')
    invalid = dict(first, atoms=first['atoms'].copy(), timestep=10)
    invalid['atoms'][0, 2] = np.nan
    _reject(lambda: analyze_msd([first, invalid], COL, **flags), 'finite')
    no_id = {k: v for k, v in COL.items() if k != 'id'}
    _reject(lambda: analyze_msd([first, first], no_id, **flags), 'ID')


def test_unsupported_triclinic_slab_pair_and_density_consumers():
    """A typed tilted cell is rejected even when no retained tilt key exists."""
    _util.require_numpy()
    from lammps_post import analysis as a
    fr, _ = _frame([[2, -3, 4], [2.1, -3, 4]], [4, 9])
    fr.pop('tilt')
    no_charge = {k: v for k, v in COL.items() if k != 'q'}
    calls = [lambda: a.compute_oar([fr], COL, 5, o_type=9),
             lambda: a.compute_or([fr], COL, z_range=(0, 10), fe_type=4),
             lambda: a.analyze_penetration([fr], COL, 5, o_type=9),
             lambda: a.analyze_penetration_trend([fr], COL, 5, o_type=9),
             lambda: a.analyze_penetration_profile([fr, fr], COL, o_type=9, fe_type=4),
             lambda: a.analyze_penetration_profile([fr], COL, o_type=9, fe_type=4),
             lambda: a.compute_density_profile([fr], COL),
             lambda: a.compute_density_profile([fr], COL, z_range=(0, 10)),
             lambda: a.detect_o2_dissociation([fr], COL, o_type=9),
             lambda: a.analyze_charge_z(fr, COL, fe_type=4, o_type=9),
             lambda: a.analyze_charge_evolution([fr], COL, z_range=(0, 10), fe_type=4),
             lambda: a.compute_or([fr], no_charge, z_range=(0, 10), fe_type=4),
             lambda: a.analyze_charge_evolution([fr], no_charge, z_range=(0, 10), fe_type=4)]
    for call in calls:
        _reject(call, 'orthogonal')
    assert a.analyze_charge_evolution([fr], COL, fe_type=4) is not None
    assert a.analyze_spin_evolution([fr], COL) is not None


def test_triclinic_unrestricted_or_is_a_pure_charge_fraction():
    """Without a z selection, charge counting has no cell geometry dependence.

    Physical justification for correcting the new guard expectation: thresholding
    scalar charges and dividing by the selected population uses neither distances,
    volume nor a surface. Only the z-restricted variant is a slab observable.
    """
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_or
    fr, _ = _frame([[2, -3, 4], [3, -2, 5], [4, -1, 6]], [4, 4, 9])
    fr['atoms'][:, COL['q']] = [.1, .5, 1.5]
    got = compute_or([fr], COL, fe_type=4, q_thr=.3)
    np.testing.assert_array_equal(got['or'], [.5])
    no_charge = {k: v for k, v in COL.items() if k != 'q'}
    assert compute_or([fr], no_charge, fe_type=4) is None
    _reject(lambda: compute_or([fr], COL, fe_type=4, z_range=(0, 10)), 'orthogonal')


def test_typed_cell_triclinic_marker_is_a_boolean_geometry_claim():
    """Retained geometry flags must agree with the authoritative Box kind."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import _typed_cell, compute_rdf, analyze_msd
    for tilt in ((0, 0, 0), (1, 0, 0)):
        fr, _ = _frame([[0, 0, 0], [1, 0, 0]], [4, 9], lo=(0, 0, 0), tilt=tilt)
        skew = tilt != (0, 0, 0)
        for marker in (skew, np.bool_(skew)):
            matching = dict(fr, triclinic=marker)
            assert _typed_cell(matching, 'test') is fr['cell']
            compute_rdf([matching], COL, 4, 9)
            analyze_msd([matching, matching], COL, pbc=(True, True, True))
        conflicting = dict(fr, triclinic=not skew)
        _reject(lambda: _typed_cell(conflicting, 'test'), 'disagree')
        _reject(lambda: compute_rdf([conflicting], COL, 4, 9), 'disagree')
        _reject(lambda: analyze_msd([conflicting, conflicting], COL,
                                   pbc=(True, True, True)), 'disagree')
        for invalid in (0, 1, 'true', None, (), [skew], np.array(skew), np.array([skew])):
            broken = dict(fr, triclinic=invalid)
            _reject(lambda: _typed_cell(broken, 'test'), 'boolean')
            _reject(lambda: compute_rdf([broken], COL, 4, 9), 'boolean')


def test_typed_extreme_cells_reject_numerically_unsafe_analysis():
    """Valid metadata must not turn overflowed geometry into RDF/MSD/density."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf, analyze_msd, compute_density_profile
    for lengths in ((1e200, 1e200, 1e-200), (1e-160, 1e-80, 1e-80),
                    (1e-105, 1e-105, 1e-105)):
        for flags in ((False, False, False), (True, True, True)):
            fr, _ = _frame([[0, 0, 0], [1, 0, 0]], [4, 9], lo=(0, 0, 0),
                           lengths=lengths, tilt=(0, 0, 0), pbc=flags)
            assert np.isfinite(fr['cell'].volume) and fr['cell'].volume > 0
            calls = [lambda: compute_rdf([fr], COL, 4, 9, pbc=flags),
                     lambda: analyze_msd([fr, fr], COL, pbc=flags),
                     lambda: analyze_msd([fr, fr], COL, species_type=99, pbc=flags),
                     lambda: compute_density_profile([fr], COL, z_range=(0, 1)),
                     lambda: compute_density_profile([fr], COL)]
            for call in calls:
                _reject(call, 'geometry')


def test_legacy_tilt_rejection_and_zero_tilt_orthogonal_parity():
    """Raw retained tilt stays unsupported; typed zero tilt preserves old math."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf, analyze_msd, detect_o2_dissociation
    fr, _ = _frame([[2.1, -2.8, 4.1], [4.9, -2.8, 4.1]], [4, 9],
                   tilt=(0, 0, 0), pbc=(True, True, False))
    legacy = {k: v for k, v in fr.items() if k not in ('cell', 'tilt')}
    kwargs = dict(type_a=4, type_b=9, r_max=2, n_bins=8)
    np.testing.assert_array_equal(compute_rdf([fr], COL, **kwargs)['g'],
                                  compute_rdf([legacy], COL, **kwargs)['g'])
    for key, value in (('tilt', (1, 0, 0)), ('xy', 1), ('tilt_factors', (0, 1, 0)),
                       ('box', np.zeros((3, 3))), ('tilt', (float('nan'), 0, 0))):
        broken = dict(legacy, **{key: value})
        _reject(lambda: compute_rdf([broken], COL, **kwargs), 'orthogonal')
        _reject(lambda: analyze_msd([broken, broken], COL), 'orthogonal')
    second = dict(fr, atoms=fr['atoms'].copy(), timestep=1)
    second['atoms'][:, 2] += .4
    old_second = {k: v for k, v in second.items() if k not in ('cell', 'tilt')}
    np.testing.assert_array_equal(analyze_msd([fr, second], COL)['msd'],
                                  analyze_msd([legacy, old_second], COL)['msd'])
    _reject(lambda: compute_rdf([fr], COL, **kwargs, pbc=(True, True, True)), 'PBC')
    _reject(lambda: detect_o2_dissociation([fr], COL, o_type=9,
                                          pbc=(True, True, True)), 'PBC')


def test_typed_orthogonal_rdf_keeps_legacy_z_pbc_switch():
    """Reader opt-in must not erase the old explicit orthogonal z-only override."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf
    fr, _ = _frame([[0, 0, .2], [0, 0, 9.8]], [4, 9], lo=(0, 0, 0),
                   lengths=(10, 10, 10), tilt=(0, 0, 0), pbc=(True, True, True))
    legacy = {key: value for key, value in fr.items() if key not in ('cell', 'tilt')}
    kwargs = dict(type_a=4, type_b=9, r_max=3., n_bins=6)
    curves = []
    for flag in (False, True):
        actual = compute_rdf([fr], COL, z_pbc=flag, **kwargs)['g']
        expected = compute_rdf([legacy], COL, z_pbc=flag, **kwargs)['g']
        np.testing.assert_array_equal(actual, expected)
        curves.append(actual)
    assert not np.array_equal(*curves)
    _reject(lambda: compute_rdf([fr], COL, pbc=(True, True, False), **kwargs), 'PBC')


def test_typed_orthogonal_msd_keeps_variable_lengths_and_round_ties():
    """Zero tilt retains current-length arithmetic and the historical half tie."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    frames = []
    for step, (x, length) in enumerate(((.5, 10), (3, 5), (.5, 10))):
        fr, _ = _frame([[x, 0, 0]], step=step, lo=(0, 0, 0),
                       lengths=(length, 10, 10), tilt=(0, 0, 0),
                       pbc=(True, False, False))
        frames.append(fr)
    legacy = [{k: v for k, v in fr.items() if k not in ('cell', 'tilt')}
              for fr in frames]
    got = analyze_msd(frames, COL, pbc=(True, False, False))
    old = analyze_msd(legacy, COL, pbc=(True, False, False))
    np.testing.assert_array_equal(got['msd'], [0, 6.25, 0])
    np.testing.assert_array_equal(got['msd'], old['msd'])
