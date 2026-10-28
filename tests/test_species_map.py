"""GEN-1 generic model tests, independent of force-field/chemical vocabulary."""

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import _util
from lammpkeeper.core import SpeciesMap


def _reject(call, *fragments):
    """Require a visible validation error, with every relevant diagnostic detail."""
    try:
        call()
    except ValueError as exc:
        assert all(fragment in str(exc) for fragment in fragments), str(exc)
    else:
        raise AssertionError('invalid species metadata was accepted')


def test_generic_sparse_repeated_labels_and_groups():
    """Repeated names union sparse numeric IDs; explicit groups may overlap."""
    species = SpeciesMap.from_atom_types({2: 'A', 7: 'A', 9: 'B'}, groups={'X': [2, 9]})
    assert species.type_sets() == {'A': frozenset({2, 7}), 'B': frozenset({9}),
                                   'X': frozenset({2, 9})}
    assert species.resolve('A') == frozenset({2, 7})
    assert species.resolve('X') == frozenset({2, 9})
    _reject(lambda: species.resolve('missing'), 'missing', 'A', 'B', 'X')
    _reject(lambda: species.resolve([]), 'Unknown species')


def test_generic_snapshots_and_returned_views_cannot_mutate_memberships():
    """External dictionaries/lists and copied views cannot relabel a live model."""
    members = [2, 7]
    labels = {'A': members, 'B': [9]}
    species = SpeciesMap(labels)
    labels['B'].append(10)
    members.clear()
    labels['X'] = [11]
    copied = species.type_sets()
    copied['A'] = frozenset({999})
    copied.clear()
    assert species.resolve('A') == frozenset({2, 7})
    assert species.resolve('B') == frozenset({9})
    assert 'X' not in species.type_sets()
    try:
        species._label_types = {}
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError('species map permits attribute replacement')
    try:
        species._label_types['A'] = frozenset({999})
    except TypeError:
        pass
    else:
        raise AssertionError('internal selection view permits mutation')


def test_generic_factory_copies_type_and_group_maps():
    """Factories snapshot both inputs instead of retaining mutable caller state."""
    types, groups = {2: 'A', 7: 'B'}, {'X': [2, 7]}
    species = SpeciesMap.from_atom_types(types, groups=groups)
    types[2] = 'B'
    groups['X'].clear()
    assert species.resolve('A') == frozenset({2})
    assert species.resolve('X') == frozenset({2, 7})


def test_generic_empty_session_and_exact_vocabulary():
    """Unloaded maps are valid, but names and underscore prefixes are not guessed."""
    empty = SpeciesMap({})
    assert empty.type_sets() == {}
    _reject(lambda: empty.resolve('A'), 'Unknown species', 'supply explicit type labels')
    species = SpeciesMap.from_atom_types({2: 'A_spin', 7: 'B'})
    assert species.resolve('A_spin') == frozenset({2})
    _reject(lambda: species.resolve('A'), 'A_spin', 'B')
    _reject(lambda: species.resolve('a_spin'), 'Unknown species')


def test_generic_type_ids_require_positive_integral_values():
    """Boolean, fractional, text, nonfinite and nonpositive IDs cannot be rounded."""
    for bad in (True, False, 0, -1, 2.0, 2.5, '2', None, float('nan'), float('inf')):
        _reject(lambda: SpeciesMap({'A': [bad]}), 'positive integer')
        _reject(lambda: SpeciesMap.from_atom_types({bad: 'A'}), 'positive integer')
        _reject(lambda: SpeciesMap.from_atom_types({2: 'A'}, groups={'X': [bad]}),
                'positive integer')


def test_generic_group_and_label_validation():
    """Unknown references and exact-label conflicts fail rather than changing selection."""
    for bad in ('', '  ', 2, None):
        _reject(lambda: SpeciesMap({bad: [2]}), 'species name')
        _reject(lambda: SpeciesMap.from_atom_types({2: bad}), 'species name')
        _reject(lambda: SpeciesMap.from_atom_types({2: 'A'}, groups={bad: [2]}),
                'species name')
    for members in ([], (), set(), None, 2):
        _reject(lambda: SpeciesMap({'A': members}), 'Group')
    _reject(lambda: SpeciesMap.from_atom_types({2: 'A'}, groups={'X': [99]}), 'X', '99')
    _reject(lambda: SpeciesMap.from_atom_types({2: 'A', 7: 'A'}, groups={'A': [2]}),
            'Conflicting', 'A')
    assert SpeciesMap.from_atom_types({2: 'A'}, groups={'A': [2]}).resolve('A') == {2}
    for bad in (None, [], 'A'):
        _reject(lambda: SpeciesMap(bad), 'mapping')
        _reject(lambda: SpeciesMap.from_atom_types(bad), 'mapping')
    _reject(lambda: SpeciesMap.from_atom_types({2: 'A'}, groups=[]), 'mapping')


def test_generic_iterators_are_snapshotted_once():
    """Single-use membership iterators remain valid after construction."""
    species = SpeciesMap({'A': iter([2, 7, 2]), 'B': iter([9])})
    assert species.resolve('A') == frozenset({2, 7})
    assert species.resolve('A') == frozenset({2, 7})
    groups = {'X': iter([2, 9])}
    assert SpeciesMap.from_atom_types({2: 'A', 9: 'B'}, groups=groups).resolve('X') == {2, 9}


def test_generic_numpy_integral_types_do_not_add_a_numpy_dependency():
    """Optional NumPy scalar inputs obey the same integral validation as Python ints."""
    _util.require_numpy()
    import numpy as np
    species = SpeciesMap.from_atom_types({np.int64(2): 'A', np.int32(7): 'B'},
                                          groups={'X': [np.int64(2), np.int32(7)]})
    assert species.resolve('X') == frozenset({2, 7})
    _reject(lambda: SpeciesMap({'A': [np.bool_(True)]}), 'positive integer')


def test_generic_model_imports_with_stdlib_only():
    """The new public package does not import any optional scientific backend."""
    run = subprocess.run([sys.executable, '-S', '-c',
                          'from lammpkeeper.core import SpeciesMap; '
                          'assert SpeciesMap.from_atom_types({2:"A",7:"B"}).resolve("B")=={7}'],
                         cwd=_util.REPO_ROOT, capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stdout + run.stderr


def test_legacy_selection_adapter_delegates_to_generic_resolution():
    """PHYS-4 compatibility helpers actually resolve through the new model."""
    from lammpkeeper.common.mapping import make_species_map, resolve_species, species_type_sets
    calls = []
    original = SpeciesMap.resolve

    def observe(species, name):
        """Record the real generic method without substituting its result."""
        calls.append(name)
        return original(species, name)

    with patch.object(SpeciesMap, 'resolve', new=observe):
        assert resolve_species('X', {2: 'A', 7: 'B'}, groups={'X': [2, 7]}) == {2, 7}
    assert calls == ['X']
    assert isinstance(make_species_map({2: 'A', 7: 'B'}), SpeciesMap)
    assert species_type_sets({2: 'A', 7: 'A'}) == {'A': frozenset({2, 7})}


def test_generic_core_has_no_domain_species_or_forcefield_literals():
    """Domain presets must not leak back into the generic system model."""
    import lammpkeeper.core.species as module
    tree = ast.parse(Path(module.__file__).read_text())
    forbidden = {'Fe', 'O', 'Mn', 'ace', 'reaxff', 'hdnnp', 'Fe_up', 'Fe_down'}
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not forbidden & literals
