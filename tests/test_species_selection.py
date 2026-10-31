"""PHYS-4: explicit species unions, shell resolution, and RDF selections.

Synthetic coordinates deliberately give the two spin channels different MSDs
and RDFs. No fixtures or numerical goldens are changed. In particular these
tests compare selection paths using the current RDF normalization. The
historically named same-species equivalence check does not lock in the old
extra division by two. The enumerated cross-species case and dedicated audit
oracles independently check normalization; path agreement alone is not proof
of physical correctness.
"""
import contextlib
import io
import warnings
from unittest.mock import patch

import _util


COL = {'id': 0, 'type': 1, 'x': 2, 'y': 3, 'z': 4}
ACE = {1: 'Fe_up', 2: 'Fe_down', 3: 'O'}


def _frame(rows, step=0):
    """Build a ten-unit cubic frame directly, independent of dump serialization."""
    import numpy as np
    return {'atoms': np.asarray(rows, dtype=float),
            'box': np.asarray(((0, 10), (0, 10), (0, 10)), dtype=float),
            'timestep': step}


def _msd_frames():
    """Provide squared displacements 1, 9 and 0 to distinguish channel unions."""
    # Final squared displacements are 1, 9, 0. Fe union = 5, not 9 or 10/3.
    return [_frame([[1, 1, 1, 1, 1], [2, 2, 4, 1, 1], [3, 3, 7, 1, 1]]),
            _frame([[1, 1, 2, 1, 1], [2, 2, 7, 1, 1], [3, 3, 7, 1, 1]], 100)]


def _rdf_frames():
    """Mix periodic neighbors and changing types to exercise per-frame group masks."""
    # Includes cross-boundary neighbors, unequal type populations, and distinct
    # channel distributions. Changing types in frame 2 checks per-frame masks.
    rows = [[1, 1, 0.2, 1, 1], [2, 2, 3.2, 1, 1],
            [3, 3, 1.2, 1, 1], [4, 3, 8.2, 1, 1],
            [5, 1, 5.2, 2, 1], [6, 2, 8.2, 3, 2]]
    second = [r[:] for r in rows]
    second[0][1] = 3
    second[2][1] = 2
    second[1][2] += 0.35
    return [_frame(rows), _frame(second, 100)]


def _shell(frames=None, labels=None, ff='ace'):
    """Create only analysis state, bypassing interactive history and user files."""
    from lammps_post.shell import LammpsPostShell
    from lammps_post.state import SessionState
    # Bypass readline/history setup entirely: this suite tests resolution, not
    # interactive initialization, and must never touch the user's HOME history.
    shell = LammpsPostShell.__new__(LammpsPostShell)
    shell.state = SessionState()
    shell.state.dump_frames = frames if frames is not None else _msd_frames()
    shell.state.dump_col_idx = dict(COL)
    shell.state.ff_info.update(forcefield=ff,
                               atom_types=dict(ACE if labels is None else labels),
                               dt_fs=1.0)
    shell.state.input_config = {'boundary': ['p', 'p', 'p']}
    return shell


def _quiet(call):
    """Suppress presentation output while preserving return values and exceptions."""
    with contextlib.redirect_stdout(io.StringIO()):
        return call()


def _value_error(call, *needles):
    """Require an explanatory rejection rather than silent species substitution."""
    try:
        _quiet(call)
    except ValueError as exc:
        message = str(exc).lower()
        assert message, 'validation must explain the rejected selection'
        for needle in needles:
            assert str(needle).lower() in message, str(exc)
        return
    raise AssertionError('expected ValueError rather than a silent species fallback')


def _assert_rdf(actual, expected):
    """Compare radial grids, normalized bins and the number of contributing frames."""
    import numpy as np
    np.testing.assert_allclose(actual['r'], expected['r'], rtol=1e-14, atol=1e-14)
    np.testing.assert_allclose(actual['g'], expected['g'], rtol=1e-13, atol=1e-13)
    assert actual['n_frames'] == expected['n_frames']


def _flatten(frames, mapping):
    """Relabel copied types simultaneously to form a legacy integer-API comparator."""
    result = []
    for frame in frames:
        copied = dict(frame, atoms=frame['atoms'].copy())
        original = frame['atoms'][:, COL['type']]
        for old, new in mapping.items():
            copied['atoms'][original == old, COL['type']] = new
        result.append(copied)
    return result


def test_mapping_canonical_ace_species_sets():
    """Canonical Fe resolves to both spin types while channel names stay singleton."""
    _util.require_numpy()
    from lammpkeeper.common.mapping import species_type_sets, resolve_species
    expected = {'Fe': frozenset({1, 2}), 'Fe_up': frozenset({1}),
                'Fe_down': frozenset({2}), 'O': frozenset({3})}
    actual = species_type_sets(ACE, ff='ace')
    for name, types in expected.items():
        assert actual[name] == types
        assert isinstance(actual[name], frozenset)
        assert resolve_species(name, ACE, ff='ace') == types


def test_mapping_unknown_name_lists_valid_species():
    """Unknown labels must fail with the available canonical selections listed."""
    _util.require_numpy()
    from lammpkeeper.common.mapping import resolve_species
    _value_error(lambda: resolve_species('missing', ACE, ff='ace'),
                 'missing', 'Fe', 'Fe_up', 'Fe_down', 'O')


def test_mapping_duplicate_labels_merge_without_prefix_guessing():
    """Identical labels form unions but underscore prefixes create no aliases."""
    _util.require_numpy()
    from lammpkeeper.common.mapping import species_type_sets, resolve_species
    labels = {4: 'A_spin', 7: 'A_spin', 9: 'B'}
    actual = species_type_sets(labels)
    assert actual == {'A_spin': frozenset({4, 7}), 'B': frozenset({9})}
    _value_error(lambda: resolve_species('A', labels), 'A_spin', 'B')
    _value_error(lambda: resolve_species('Fe', labels), 'A_spin', 'B')


def test_mapping_generic_unknown_forcefield_uses_supplied_labels_only():
    """Unrecognized presets cannot inject Fe/O assumptions into explicit labels."""
    _util.require_numpy()
    from lammpkeeper.common.mapping import species_type_sets, resolve_species
    labels = {4: 'A', 7: 'A', 9: 'B'}
    for ff in (None, 'unknown', 'not-a-preset'):
        assert species_type_sets(labels, ff=ff) == {
            'A': frozenset({4, 7}), 'B': frozenset({9})}
        _value_error(lambda: resolve_species('O', labels, ff=ff), 'A', 'B')


def test_mapping_custom_ace_labels_do_not_inject_preset_species():
    """User-supplied X/Y/Z labels outrank the preset's usual species vocabulary."""
    _util.require_numpy()
    from lammpkeeper.common.mapping import species_type_sets, resolve_species
    labels = {1: 'X', 2: 'Y', 3: 'Z'}
    assert species_type_sets(labels, ff='ace') == {
        'X': frozenset({1}), 'Y': frozenset({2}), 'Z': frozenset({3})}
    for name in ('Fe', 'Fe_up', 'Fe_down', 'O'):
        _value_error(lambda: resolve_species(name, labels, ff='ace'), 'X', 'Y', 'Z')


def test_mapping_explicit_groups_and_conflicting_definitions():
    """Groups may span known types but cannot redefine labels or reference unknown IDs."""
    _util.require_numpy()
    from lammpkeeper.common.mapping import species_type_sets, resolve_species
    labels = {4: 'A', 7: 'A', 9: 'B'}
    groups = {'X': {4, 9}}
    assert resolve_species('X', labels, groups=groups) == frozenset({4, 9})
    assert species_type_sets(labels, groups=groups)['A'] == frozenset({4, 7})
    _value_error(lambda: species_type_sets(labels, groups={'A': {4}}), 'A')
    _value_error(lambda: species_type_sets(labels, groups={'X': {99}}), '99')


def test_mapping_display_labels_distinguish_spin_union():
    """Presentation distinguishes all-spin Fe from each channel without hiding errors."""
    _util.require_numpy()
    from lammpkeeper.common.mapping import species_display_name
    assert species_display_name('Fe', ACE, ff='ace') == 'Fe (all spins)'
    assert species_display_name('Fe_up', ACE, ff='ace') == 'Fe↑'
    assert species_display_name('Fe_down', ACE, ff='ace') == 'Fe↓'
    assert species_display_name('O', ACE, ff='ace') == 'O'
    display = species_display_name('A', {4: 'A', 7: 'A', 9: 'B'})
    assert 'A' in display
    _value_error(lambda: species_display_name('missing', ACE, ff='ace'), 'missing')


def test_mapping_legacy_tables_remain_unchanged():
    """Group support must not alter legacy scalar mappings or ACE's Mn proxy slot."""
    _util.require_numpy()
    from lammpkeeper.common.mapping import (FORCE_FIELDS, type_to_label,
                                            label_to_type, element_to_type,
                                            element_order)
    assert FORCE_FIELDS['ace'] == {1: ('Fe', 'Fe_up'), 2: ('Mn', 'Fe_down'),
                                   3: ('O', 'O')}
    assert type_to_label('ace') == ACE
    assert label_to_type('ace') == {'Fe_up': 1, 'Fe_down': 2, 'O': 3}
    assert element_to_type('ace') == {'Fe': 1, 'Mn': 2, 'O': 3}
    assert element_order('ace') == ['Fe', 'Mn', 'O']


def test_shell_msd_fe_selects_both_spin_channels():
    """The Fe mean is (1 + 9)/2 = 5, excluding oxygen and neither spin channel."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    shell = _shell()
    _quiet(lambda: shell._analyze_msd(['--species', 'Fe'], _batch=True))
    expected = analyze_msd(shell.state.dump_frames, COL, species_type={1, 2},
                           dt_fs=1.0, pbc=(True, True, True))
    np.testing.assert_allclose(expected['msd'], [0, 5])
    np.testing.assert_allclose(shell.state.cache['msd_Fe']['msd'], expected['msd'])


def test_shell_msd_explicit_channels_and_oxygen_match_integer_api():
    """Each named singleton retains the scalar API's displacement and time arrays."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_msd
    for name, type_id in (('Fe_up', 1), ('Fe_down', 2), ('O', 3)):
        shell = _shell()
        _quiet(lambda: shell._analyze_msd(['--species', name], _batch=True))
        expected = analyze_msd(shell.state.dump_frames, COL, species_type=type_id,
                               dt_fs=1.0, pbc=(True, True, True))
        actual = shell.state.cache['msd_' + name]
        np.testing.assert_array_equal(actual['msd'], expected['msd'])
        np.testing.assert_array_equal(actual['time'], expected['time'])


def test_shell_msd_metadata_preserves_raw_cache_key():
    """Display-only spin formatting must not rename raw MSD cache identifiers."""
    _util.require_numpy()
    for name, display in (('Fe', 'Fe (all spins)'), ('Fe_up', 'Fe↑'),
                          ('Fe_down', 'Fe↓'), ('O', 'O')):
        shell = _shell()
        _quiet(lambda: shell._analyze_msd(['--species', name], _batch=True))
        assert set(shell.state.cache) == {'msd_' + name}
        result = shell.state.cache['msd_' + name]
        assert result['label'] == name
        assert result['display_label'] == display


def test_shell_msd_unknown_species_rejects_and_invalidates_only_target():
    """Invalid selection removes its stale result without disturbing unrelated caches."""
    _util.require_numpy()
    shell = _shell()
    other = object()
    shell.state.cache.update(msd_missing={'msd': 'stale'}, msd_O=other, rdf_Fe_O=other)
    _value_error(lambda: shell._analyze_msd(['--species', 'missing'], _batch=True),
                 'missing', 'Fe', 'O')
    assert 'msd_missing' not in shell.state.cache
    assert shell.state.cache['msd_O'] is other
    assert shell.state.cache['rdf_Fe_O'] is other


def test_shell_msd_missing_species_value_rejects_and_clears_default_target():
    """A valueless species option invalidates the default Fe target, not oxygen."""
    _util.require_numpy()
    shell = _shell()
    other = object()
    shell.state.cache.update(msd_Fe={'msd': 'stale'}, msd_O=other)
    _value_error(lambda: shell._analyze_msd(['--species'], _batch=True), 'species')
    assert 'msd_Fe' not in shell.state.cache
    assert shell.state.cache['msd_O'] is other


def test_shell_msd_generic_duplicate_labels_select_union():
    """Generic repeated A labels yield the same analytic mean 5 without ACE aliases."""
    _util.require_numpy()
    import numpy as np
    frames = _flatten(_msd_frames(), {1: 4, 2: 7, 3: 9})
    shell = _shell(frames, {4: 'A', 7: 'A', 9: 'B'}, ff='unknown')
    _quiet(lambda: shell._analyze_msd(['--species', 'A'], _batch=True))
    np.testing.assert_allclose(shell.state.cache['msd_A']['msd'], [0, 5])
    _value_error(lambda: shell._analyze_msd(['--species', 'Fe'], _batch=True), 'A', 'B')


def test_shell_msd_does_not_invent_underscore_prefix_alias():
    """X_up and X_down alone do not authorize an inferred X selection."""
    _util.require_numpy()
    shell = _shell(labels={1: 'X_up', 2: 'X_down', 3: 'Y'}, ff='unknown')
    _value_error(lambda: shell._analyze_msd(['--species', 'X'], _batch=True),
                 'X_up', 'X_down', 'Y')


def test_rdf_singleton_sets_are_numerically_identical_to_integer_types():
    """Accepted singleton containers preserve exact scalar RDF grids and values."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf
    for a, b in ((1, 3), (1, 1), (2, 3)):
        kwargs = dict(r_max=4.5, n_bins=30, z_pbc=True)
        expected = compute_rdf(_rdf_frames(), COL, type_a=a, type_b=b, **kwargs)
        for selected_a, selected_b in (({a}, {b}), ([a], [b]), ((a,), (b,))):
            actual = compute_rdf(_rdf_frames(), COL, type_a=selected_a,
                                 type_b=selected_b, **kwargs)
            _assert_rdf(actual, expected)
            np.testing.assert_array_equal(actual['r'], expected['r'])
            np.testing.assert_array_equal(actual['g'], expected['g'])


def test_rdf_group_union_matches_flattened_type_labels_per_frame():
    """Selecting two types equals independently relabeling both into one scalar type."""
    _util.require_numpy()
    from lammps_post.analysis import compute_rdf
    frames = _rdf_frames()
    kwargs = dict(r_max=4.5, n_bins=30, z_pbc=True)
    expected = compute_rdf(_flatten(frames, {1: 4, 2: 4}), COL,
                           # Relabeling is an equivalence check, not an independent RDF oracle.
                           type_a=4, type_b=3, **kwargs)
    assert expected['n_frames'] == 2
    actual = compute_rdf(frames, COL, type_a={1, 2}, type_b={3}, **kwargs)
    _assert_rdf(actual, expected)


def test_rdf_same_group_preserves_legacy_same_species_normalization():
    """Equivalent group orderings retain the scalar same-species normalization."""
    _util.require_numpy()
    from lammps_post.analysis import compute_rdf
    frames = _rdf_frames()
    kwargs = dict(r_max=4.5, n_bins=30, z_pbc=True)
    # The historical test name denotes scalar/group parity, not permission to
    # restore a former normalization bug; both calls use the current algorithm.
    expected = compute_rdf(_flatten(frames, {1: 4, 2: 4}), COL,
                           type_a=4, type_b=4, **kwargs)
    actual = compute_rdf(frames, COL, type_a={1, 2}, type_b={2, 1}, **kwargs)
    _assert_rdf(actual, expected)


def test_rdf_group_union_has_analytic_cross_species_normalization():
    """Four enumerated pair distances and shell volumes independently fix g(r)."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf
    # Four A/B pairs at distances 1, 3, 2, 4. N_A=N_B=2, volume=1000.
    frames = [_frame([[1, 4, 1, 1, 1], [2, 7, 4, 1, 1],
                      [3, 9, 2, 1, 1], [4, 9, 8, 1, 1]])]
    result = compute_rdf(frames, COL, type_a={4, 7}, type_b={9},
                         r_max=4.5, n_bins=9, z_pbc=True)
    # Distances from x=4 to x=8 and from x=1 to x=8 are 4 and 3;
    # from x=1/4 to x=2 are 1 and 2, respectively.
    edges = np.linspace(0, 4.5, 10)
    counts, _ = np.histogram([1, 3, 2, 4], bins=edges)
    shell_vol = 4 * np.pi / 3 * (edges[1:] ** 3 - edges[:-1] ** 3)
    np.testing.assert_allclose(result['g'], counts / (2 * shell_vol * (2 / 1000)))
    assert result['n_frames'] == 1


def _rdf_paths(a, b):
    """Compare candidate-tree and forced fallback results, reporting absent SciPy."""
    import lammps_post.analysis as analysis
    frames = _rdf_frames()
    kwargs = dict(type_a=a, type_b=b, r_max=4.5, n_bins=30, z_pbc=True)
    real = analysis._rdf_candidate_pairs
    used_tree = []

    def observe(*args, **kwargs):
        """Record actual candidate availability without modifying the pair results."""
        result = real(*args, **kwargs)
        used_tree.append(result is not None)
        return result

    with patch.object(analysis, '_rdf_candidate_pairs', observe):
        fast = analysis.compute_rdf(frames, COL, **kwargs)
    with patch.object(analysis, '_rdf_candidate_pairs', lambda *a, **k: None):
        slow = analysis.compute_rdf(frames, COL, **kwargs)
    assert fast['n_frames'] == slow['n_frames'] == 2, 'species unions must select atoms'
    _assert_rdf(fast, slow)
    if not any(used_tree):
        # Fallback agreement alone does not establish accelerated-path coverage.
        _util.skip('scipy tree path unavailable; fallback equality was checked')


def test_rdf_disjoint_group_tree_matches_fallback():
    """Disjoint group acceleration must reproduce fallback pair counting."""
    _util.require_numpy()
    _rdf_paths({1, 2}, {3})


def test_rdf_equal_group_tree_matches_fallback():
    """Equal group acceleration must retain same-species pair handling."""
    _util.require_numpy()
    _rdf_paths({1, 2}, {2, 1})


def test_rdf_partial_overlap_tree_matches_fallback():
    """Overlapping selections must count pairs identically on both execution paths."""
    _util.require_numpy()
    _rdf_paths({1, 2}, {2, 3})


def test_rdf_invalid_type_selections_raise():
    """Empty, nonpositive and nonintegral selections fail on either side of a pair."""
    _util.require_numpy()
    from lammps_post.analysis import compute_rdf
    invalid = (set(), [], 0, -1, 1.5, 'Fe', {0}, {-1}, {1.5})
    for selection in invalid:
        _value_error(lambda: compute_rdf(_rdf_frames(), COL,
                                         type_a=selection, type_b=3))
        _value_error(lambda: compute_rdf(_rdf_frames(), COL,
                                         type_a=1, type_b=selection))


def test_shell_rdf_fe_oxygen_union_matches_flattened_integer_api():
    """Shell Fe-O selection combines both spins like the relabeled scalar comparator."""
    _util.require_numpy()
    from lammps_post.analysis import compute_rdf
    frames = _rdf_frames()
    shell = _shell(frames)
    _quiet(lambda: shell._analyze_rdf(['Fe-O', '--frames', '2'], _batch=True))
    expected = compute_rdf(_flatten(frames, {1: 4, 2: 4}), COL,
                           type_a=4, type_b=3, max_frames=2,
                           label_a='Fe', label_b='O', z_pbc=True)
    _assert_rdf(shell.state.cache['rdf_Fe-O'], expected)


def test_shell_rdf_explicit_channels_and_oxygen_match_integer_api():
    """Named channel and oxygen pairs preserve scalar RDF arithmetic."""
    _util.require_numpy()
    from lammps_post.analysis import compute_rdf
    for a, b, type_a, type_b in (('Fe_up', 'O', 1, 3),
                                 ('Fe_down', 'O', 2, 3), ('O', 'O', 3, 3)):
        shell = _shell(_rdf_frames())
        pair = a + '-' + b
        _quiet(lambda: shell._analyze_rdf([pair, '--frames', '2'], _batch=True))
        expected = compute_rdf(shell.state.dump_frames, COL, type_a=type_a,
                               type_b=type_b, max_frames=2, label_a=a,
                               label_b=b, z_pbc=True)
        _assert_rdf(shell.state.cache['rdf_' + pair], expected)


def test_shell_rdf_metadata_preserves_raw_pair_and_cache_key():
    """Human-friendly pair labels cannot change raw cache keys or result identifiers."""
    _util.require_numpy()
    for pair, displays in (('Fe-O', ('Fe (all spins)', 'O')),
                            ('Fe_up-O', ('Fe↑', 'O')),
                            ('Fe_down-O', ('Fe↓', 'O')),
                            ('O-O', ('O', 'O'))):
        shell = _shell(_rdf_frames())
        _quiet(lambda: shell._analyze_rdf([pair], _batch=True))
        assert set(shell.state.cache) == {'rdf_' + pair}
        result = shell.state.cache['rdf_' + pair]
        assert result['label'] == pair
        for display in displays:
            assert display in result['display_label']


def test_shell_rdf_unknown_species_rejects_and_invalidates_only_target():
    """Unknown species on either side clears only that pair's stale RDF."""
    _util.require_numpy()
    for pair in ('missing-O', 'Fe-missing'):
        shell = _shell(_rdf_frames())
        other = object()
        key = 'rdf_' + pair
        shell.state.cache.update({key: {'g': 'stale'}, 'rdf_O-O': other,
                                  'msd_Fe': other})
        _value_error(lambda: shell._analyze_rdf([pair], _batch=True), 'missing', 'Fe', 'O')
        assert key not in shell.state.cache
        assert shell.state.cache['rdf_O-O'] is other
        assert shell.state.cache['msd_Fe'] is other


def test_shell_rdf_malformed_pair_rejects_and_invalidates_only_target():
    """Malformed pair syntax must not preserve stale data or erase other pairs."""
    _util.require_numpy()
    for pair in ('Fe', 'Fe-O-O', 'Fe-', '-O', '-'):
        shell = _shell(_rdf_frames())
        other = object()
        key = 'rdf_' + pair
        shell.state.cache.update({key: {'g': 'stale'}, 'rdf_O-O': other})
        _value_error(lambda: shell._analyze_rdf([pair], _batch=True))
        assert key not in shell.state.cache
        assert shell.state.cache['rdf_O-O'] is other


def test_shell_rdf_invalid_frame_count_rejects_and_invalidates_only_target():
    """Missing, nonpositive or nonnumeric limits invalidate only the requested RDF."""
    _util.require_numpy()
    for opts in (['Fe-O', '--frames'], ['Fe-O', '--frames', '0'],
                 ['Fe-O', '--frames', '-1'], ['Fe-O', '--frames', 'bad']):
        shell = _shell(_rdf_frames())
        other = object()
        shell.state.cache.update({'rdf_Fe-O': {'g': 'stale'}, 'rdf_O-O': other})
        _value_error(lambda: shell._analyze_rdf(opts, _batch=True))
        assert 'rdf_Fe-O' not in shell.state.cache
        assert shell.state.cache['rdf_O-O'] is other


def test_shell_rdf_generic_duplicate_labels_select_union():
    """Generic A-B grouping matches explicit relabeling without borrowing Fe aliases."""
    _util.require_numpy()
    from lammps_post.analysis import compute_rdf
    frames = _flatten(_rdf_frames(), {1: 4, 2: 7, 3: 9})
    shell = _shell(frames, {4: 'A', 7: 'A', 9: 'B'}, ff='unknown')
    _quiet(lambda: shell._analyze_rdf(['A-B'], _batch=True))
    expected = compute_rdf(_flatten(frames, {4: 8, 7: 8}), COL,
                           type_a=8, type_b=9, label_a='A', label_b='B', z_pbc=True)
    _assert_rdf(shell.state.cache['rdf_A-B'], expected)
    _value_error(lambda: shell._analyze_rdf(['Fe-B'], _batch=True), 'A', 'B')


def test_shell_rdf_does_not_invent_underscore_prefix_alias():
    """Generic spin-like names do not imply an undeclared X RDF group."""
    _util.require_numpy()
    shell = _shell(_rdf_frames(), {1: 'X_up', 2: 'X_down', 3: 'Y'}, ff='unknown')
    _value_error(lambda: shell._analyze_rdf(['X-Y'], _batch=True), 'X_up', 'X_down', 'Y')


def test_numeric_apis_keep_existing_return_keys_without_shell_metadata():
    """Display metadata belongs to shell results, not the legacy numeric return schema."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_msd, compute_rdf
    assert set(analyze_msd(_msd_frames(), COL, species_type=1)) == {'time', 'msd'}
    # frame_window is numeric provenance (which frames were averaged), not
    # shell display metadata; display_label still must not appear here.
    assert set(compute_rdf(_rdf_frames(), COL, type_a=1, type_b=3)) == {
        'r', 'g', 'label', 'n_frames', 'frame_window'}


def test_explicit_groups_cannot_borrow_unrelated_preset_display_names():
    """A reused preset name must not advertise spin semantics its membership lacks."""
    _util.require_numpy()
    from lammpkeeper.common.mapping import species_display_name
    assert species_display_name('Fe', {3: 'O'}, ff='ace', groups={'Fe': {3}}) == 'Fe'
    assert species_display_name('Fe_up', {2: 'Fe_down'}, ff='ace',
                                groups={'Fe_up': {2}}) == 'Fe_up'
    assert species_display_name('Fe', {1: 'Fe_up'}, ff='ace', groups={'Fe': {1}}) == 'Fe'


def test_explicit_group_conflicting_with_preset_alias_is_rejected():
    """An explicit Fe subset cannot silently override the canonical all-spin alias."""
    _util.require_numpy()
    from lammpkeeper.common.mapping import species_type_sets
    _value_error(lambda: species_type_sets(ACE, ff='ace', groups={'Fe': {1}}), 'Fe')


def test_msd_malformed_option_order_invalidates_requested_not_default_target():
    """Unknown options cannot redirect stale-result invalidation from oxygen to Fe."""
    _util.require_numpy()
    for opts in (['--bad', '--species', 'O'], ['--species', 'O', '--bad']):
        shell = _shell()
        other = object()
        shell.state.cache.update(msd_O={'msd': 'stale'}, msd_Fe=other)
        _value_error(lambda: shell._analyze_msd(opts, _batch=True))
        assert 'msd_O' not in shell.state.cache
        assert shell.state.cache['msd_Fe'] is other


def test_rdf_malformed_option_order_invalidates_requested_not_default_target():
    """Pair detection for invalidation must survive option ordering and malformed limits."""
    _util.require_numpy()
    for opts in (['--bad', 'O-O'], ['O-O', '--bad'],
                 ['--frames', 'bad', 'O-O'], ['--frames', '2', '--bad', 'O-O']):
        shell = _shell(_rdf_frames())
        other = object()
        shell.state.cache.update({'rdf_O-O': {'g': 'stale'}, 'rdf_Fe-O': other})
        _value_error(lambda: shell._analyze_rdf(opts, _batch=True))
        assert 'rdf_O-O' not in shell.state.cache
        assert shell.state.cache['rdf_Fe-O'] is other


def test_ambiguous_multiple_selection_targets_raise_without_erasing_either():
    """Ambiguous requests must fail without guessing which cached result to erase."""
    _util.require_numpy()
    shell = _shell(_rdf_frames())
    cached = {'rdf_Fe-O': object(), 'rdf_O-O': object(),
              'msd_Fe': object(), 'msd_O': object()}
    shell.state.cache.update(cached)
    _value_error(lambda: shell._analyze_rdf(['Fe-O', 'O-O'], _batch=True))
    assert shell.state.cache == cached
    _value_error(lambda: shell._analyze_msd(['--species', 'Fe', '--species', 'O'], _batch=True))
    assert shell.state.cache == cached


if __name__ == '__main__':
    # Dependency-free targeted baseline, including honest exception/skip counts.
    passed = failed = skipped = 0
    for name, test in sorted(list(globals().items())):
        if name.startswith('test_') and callable(test):
            try:
                with warnings.catch_warnings(record=True):
                    warnings.simplefilter('always')
                    test()
            except _util.Skip as exc:
                skipped += 1
                print(f'SKIP {name}: {exc}')
            except Exception as exc:
                failed += 1
                print(f'FAIL {name}: {type(exc).__name__}: {exc}')
            else:
                passed += 1
                print(f'PASS {name}')
    print(f'RESULT: {passed} passed, {failed} failed, {skipped} skipped')
    raise SystemExit(bool(failed))
