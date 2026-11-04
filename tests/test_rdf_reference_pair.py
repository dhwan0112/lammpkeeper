"""REV-PLOT-1: interactive RDF reference overlays use each curve's own pair.

`plot rdf` derived the reference pair by splitting the first selected cache
key on underscores; real keys are `rdf_Fe-O`, so every curve was compared
against Fe-O references, and all selected curves shared that one list. These
tests drive the real shell dispatch with scripted prompts; the reference
calculator and the renderer are replaced by recorders so no numeric
reference or matplotlib is needed.
"""
import contextlib
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

import _util


def _shell(shell_module, tmp, cache):
    """A shell whose RDF cache holds one two-point curve per key in `cache`."""
    shell = shell_module.LammpsPostShell()
    shell.state.output_dir = str(Path(tmp) / 'plots')
    for key, label in cache.items():
        # A string is the pair label; a dict carries extra fields such as display_label.
        fields = {'label': label} if isinstance(label, str) else dict(label)
        shell.state.cache[key] = {'r': [1.0, 2.0], 'g': [0.5, 1.0], **fields}
    return shell


def _fake_reference(phase_or_crystal, pair=('Fe', 'O'), r_max=6.0, **_):
    """Stand-in for compute_reference_rdf returning a minimal result that names
    the phase and pair; the mock in `_driven` records the calls."""
    name = phase_or_crystal if isinstance(phase_or_crystal, str) else phase_or_crystal['name']
    return {'r': [1.0], 'g': [1.0], 'label': f'{name} {pair[0]}-{pair[1]}', 'phase': name, 'pair': pair}


@contextlib.contextmanager
def _driven(shell_module, shell, answers, references):
    """Run one interactive command with scripted answers and recorders."""
    rendered = []
    output = io.StringIO()
    with patch.object(shell_module.sys, 'stdin') as stdin, \
            patch.object(shell, '_ask', side_effect=answers) as ask, \
            patch.object(references, 'compute_reference_rdf', side_effect=_fake_reference) as compute, \
            patch.object(shell_module, 'plot_rdf',
                         side_effect=lambda data, *a, ref_rdfs=None, **k: rendered.append((data['label'], ref_rdfs))), \
            contextlib.redirect_stdout(output):
        stdin.isatty.return_value = True
        yield ask, compute, rendered, output


def test_reference_pair_reads_labels_and_legacy_keys_without_a_default():
    """_rdf_reference_pair reads the pair from display_label, label or a legacy
    key, and returns None (never Fe-O) when there are not exactly two names."""
    from lammps_post import shell as shell_module
    read = shell_module.LammpsPostShell._rdf_reference_pair
    assert read('rdf_O-O', {'label': 'O-O'}) == ('O', 'O')
    # The display label carries resolved species names when the user typed type ids.
    assert read('rdf_1-2', {'label': '1-2', 'display_label': 'Fe-O'}) == ('Fe', 'O')
    assert read('rdf_1-2', {'label': '1-2'}) == ('1', '2')
    # Legacy underscore-joined keys without labels.
    assert read('rdf_X_Y', {'r': [1.0], 'g': [2.0]}) == ('X', 'Y')
    # Anything that is not exactly two names has no pair, and never becomes Fe-O.
    assert read('rdf_all', {}) is None
    assert read('rdf_Fe-O-up', {'label': 'Fe-O-up'}) is None
    assert read('rdf_-O', {'label': '-O'}) is None
    assert read('rdf_Fe-O', 'not a dict') == ('Fe', 'O')


def test_recipe_references_only_come_from_a_per_key_dict():
    """_rdf_recipe_references returns the saved list for the exact cache key and
    None for bare lists, empty lists, missing keys or missing recipes."""
    from lammps_post import shell as shell_module
    read = shell_module.LammpsPostShell._rdf_recipe_references
    ref = _fake_reference('FeO', ('O', 'O'))
    assert read({'_ref_rdfs': {'rdf_O-O': [ref]}}, 'rdf_O-O') == [ref]
    assert read({'_ref_rdfs': {'rdf_O-O': [ref]}}, 'rdf_Fe-Fe') is None
    assert read({'_ref_rdfs': {'rdf_O-O': []}}, 'rdf_O-O') is None
    assert read({'_ref_rdfs': {'rdf_O-O': None}}, 'rdf_O-O') is None
    # Pre-fix bare list, missing key, empty recipe, no recipe at all.
    assert read({'_ref_rdfs': [ref]}, 'rdf_O-O') is None
    assert read({'_output_dir': 'x'}, 'rdf_O-O') is None
    assert read({}, 'rdf_O-O') is None
    assert read(None, 'rdf_O-O') is None


def test_each_selected_curve_gets_references_for_its_own_pair():
    """'plot rdf' with two curves computes references per curve pair, tags each
    offered phase with the pairs it serves, and saves them per cache key."""
    _util.require_numpy()
    from lammps_post import references, shell as shell_module

    with tempfile.TemporaryDirectory() as tmp:
        shell = _shell(shell_module, tmp, {'rdf_O-O': 'O-O', 'rdf_Fe-Fe': 'Fe-Fe'})
        answers = [shell.state.output_dir, 'all', 'y', 'all']
        with _driven(shell_module, shell, answers, references) as (ask, compute, rendered, output):
            shell.onecmd('plot rdf')
        assert shell.last_command_ok is True, output.getvalue()
        assert ask.call_count == len(answers)

        requested = [(call.args[0], call.kwargs['pair']) for call in compute.call_args_list]
        assert requested and all(pair in (('O', 'O'), ('Fe', 'Fe')) for _, pair in requested), requested
        assert ('Fe', 'O') not in [pair for _, pair in requested]

        by_label = dict(rendered)
        assert set(by_label) == {'O-O', 'Fe-Fe'}
        assert [ref['pair'] for ref in by_label['O-O']] == [('O', 'O')] * len(by_label['O-O'])
        assert [ref['pair'] for ref in by_label['Fe-Fe']] == [('Fe', 'Fe')] * len(by_label['Fe-Fe'])
        # Each curve is served by exactly the built-in phases that contain its pair.
        assert sorted(ref['phase'] for ref in by_label['O-O']) == sorted(references.get_phases_for_pair(('O', 'O')))
        assert sorted(ref['phase'] for ref in by_label['Fe-Fe']) == sorted(references.get_phases_for_pair(('Fe', 'Fe')))
        # alpha-Fe contains no oxygen, so it is offered for Fe-Fe only and says so.
        text = output.getvalue()
        assert 'Available references for O-O, Fe-Fe' in text, text
        assert '[Fe-Fe]' in text and '[O-O, Fe-Fe]' in text, text

        saved = shell.state.plot_recipes['rdf']['_ref_rdfs']
        assert set(saved) == {'rdf_O-O', 'rdf_Fe-Fe'}
        assert saved['rdf_O-O'] == by_label['O-O'] and saved['rdf_Fe-Fe'] == by_label['Fe-Fe']


def test_redo_replays_each_curves_saved_references_and_ignores_unattributed_lists():
    """'plot redo rdf' replays the per-key saved references without prompting,
    reports curves outside the saved selection, and ignores a bare list."""
    _util.require_numpy()
    from lammps_post import references, shell as shell_module

    with tempfile.TemporaryDirectory() as tmp:
        shell = _shell(shell_module, tmp, {'rdf_O-O': 'O-O', 'rdf_Fe-Fe': 'Fe-Fe'})
        o_refs = [_fake_reference('FeO', ('O', 'O'))]
        shell.state.plot_recipes['rdf'] = {'_ref_rdfs': {'rdf_O-O': o_refs, 'rdf_Fe-Fe': None}}
        # A curve analysed after the overlay was chosen is replayed bare, and says so.
        shell.state.cache['rdf_Fe-O'] = {'r': [1.0], 'g': [1.0], 'label': 'Fe-O'}
        # Redo only re-confirms the output directory; no pair or reference prompt.
        with _driven(shell_module, shell, [shell.state.output_dir], references) as (ask, compute, rendered, output):
            shell.onecmd('plot redo rdf')
        assert shell.last_command_ok is True, output.getvalue()
        assert ask.call_count == 1 and compute.call_count == 0
        assert dict(rendered) == {'O-O': o_refs, 'Fe-Fe': None, 'Fe-O': None}
        text = output.getvalue()
        assert 'rdf_Fe-O: not part of the saved reference selection' in text, text
        assert 'rdf_Fe-Fe: not part' not in text, text
        del shell.state.cache['rdf_Fe-O']

        # A bare list (the pre-fix recipe shape) names no curve: no overlay, no Fe-O guess.
        shell.state.plot_recipes['rdf'] = {'_ref_rdfs': [_fake_reference('FeO', ('Fe', 'O'))]}
        with _driven(shell_module, shell, [shell.state.output_dir], references) as (ask, compute, rendered, output):
            shell.onecmd('plot redo rdf')
        assert shell.last_command_ok is True, output.getvalue()
        assert ask.call_count == 1 and compute.call_count == 0
        assert dict(rendered) == {'O-O': None, 'Fe-Fe': None}


def test_generic_or_unreadable_pairs_get_no_fe_o_fallback():
    """Raw type ids, an empty selection and an unreadable pair all plot without
    a reference and say why; none silently falls back to Fe-O."""
    _util.require_numpy()
    from lammps_post import references, shell as shell_module

    with tempfile.TemporaryDirectory() as tmp:
        # Raw type ids with no element names: no built-in phase contains them.
        shell = _shell(shell_module, tmp, {'rdf_1-2': '1-2'})
        answers = [shell.state.output_dir, 'all', 'y', 'all']
        with _driven(shell_module, shell, answers, references) as (ask, compute, rendered, output):
            shell.onecmd('plot rdf')
        assert shell.last_command_ok is True, output.getvalue()
        assert ask.call_count == len(answers)
        compute.assert_not_called()
        assert rendered == [('1-2', None)]
        text = output.getvalue()
        assert 'Available references for 1-2' in text and 'no built-in phase contains' in text, text
        assert 'rdf_1-2: no 1-2 reference among the selected sources' in text, text
        assert shell.state.plot_recipes['rdf']['_ref_rdfs'] is None

    with tempfile.TemporaryDirectory() as tmp:
        # An empty selection after answering 'y' is reported, not silently dropped.
        shell = _shell(shell_module, tmp, {'rdf_O-O': 'O-O'})
        answers = [shell.state.output_dir, 'all', 'y', '']
        with _driven(shell_module, shell, answers, references) as (ask, compute, rendered, output):
            shell.onecmd('plot rdf')
        assert shell.last_command_ok is True, output.getvalue()
        compute.assert_not_called()
        assert rendered == [('O-O', None)]
        assert 'rdf_O-O: no O-O reference among the selected sources' in output.getvalue()

    with tempfile.TemporaryDirectory() as tmp:
        # A curve whose pair cannot be read is plotted without any reference prompt.
        shell = _shell(shell_module, tmp, {'rdf_all': 'all'})
        answers = [shell.state.output_dir, 'all', 'y']
        with _driven(shell_module, shell, answers, references) as (ask, compute, rendered, output):
            shell.onecmd('plot rdf')
        assert shell.last_command_ok is True, output.getvalue()
        assert ask.call_count == len(answers)
        compute.assert_not_called()
        assert rendered == [('all', None)]
        text = output.getvalue()
        assert 'rdf_all: cannot read its atom pair' in text and 'No reference overlay' in text, text


def test_cif_reference_is_computed_for_every_selected_pair():
    """One CIF crystal yields a reference for each distinct selected pair, and
    curves that resolve to the same pair share that computation."""
    _util.require_numpy()
    from lammps_post import references, shell as shell_module

    with tempfile.TemporaryDirectory() as tmp:
        # rdf_1-2 resolves to Fe-O through its display label and shares that computation.
        shell = _shell(shell_module, tmp, {'rdf_Fe-O': 'Fe-O', 'rdf_O-O': 'O-O',
                                           'rdf_1-2': {'label': '1-2', 'display_label': 'Fe-O'}})
        crystal = {'name': 'custom-FeO', 'atoms': [('Fe', (0, 0, 0)), ('O', (0.5, 0.5, 0.5))]}
        builtin = {phase for pair in (('Fe', 'O'), ('O', 'O')) for phase in references.get_phases_for_pair(pair)}
        answers = [shell.state.output_dir, 'all', 'y', str(len(builtin) + 2), 'fake.cif']
        with patch.object(references, 'parse_cif', return_value=crystal) as parse, \
                _driven(shell_module, shell, answers, references) as (ask, compute, rendered, output):
            shell.onecmd('plot rdf')
        assert shell.last_command_ok is True, output.getvalue()
        parse.assert_called_once_with('fake.cif')
        assert sorted(call.kwargs['pair'] for call in compute.call_args_list) == [('Fe', 'O'), ('O', 'O')]
        assert all(call.args[0] is crystal for call in compute.call_args_list)
        by_label = dict(rendered)
        assert [ref['pair'] for ref in by_label['Fe-O']] == [('Fe', 'O')]
        assert [ref['pair'] for ref in by_label['O-O']] == [('O', 'O')]
        assert by_label['1-2'] == by_label['Fe-O']
        text = output.getvalue()
        assert 'Reference loaded: custom-FeO Fe-O (Fe-O)' in text and '(O-O)' in text, text
        assert text.count('Reference loaded') == 2, text


def test_failed_cif_import_on_legacy_key_publishes_nothing():
    """Mirror of the matplotlib-gated CIF shell check in test_cif_occupancy (REV-REF-1),
    runnable without matplotlib: a legacy `rdf_X_Y` key still reads as the X-Y pair, the CIF
    option keeps its number with no built-in phase, and an import error stops the plot."""
    _util.require_numpy()
    from lammps_post import references, shell as shell_module

    with tempfile.TemporaryDirectory() as tmp:
        shell = _shell(shell_module, tmp, {})
        shell.state.cache['rdf_X_Y'] = {'r': [1.0], 'g': [2.0]}
        shell.state.plot_recipes['rdf'] = {'_ref_rdfs': [{'label': 'existing'}]}
        before = dict(shell.state.plot_recipes)
        assert references.get_phases_for_pair(('X', 'Y')) == []
        answers = [shell.state.output_dir, 'all', 'y', '2', 'broken.cif']
        with patch.object(references, 'parse_cif', side_effect=ValueError('broken.cif: bad site')) as parse, \
                patch.object(shell, '_save_recipe', side_effect=AssertionError('recipe publication reached')) as save, \
                _driven(shell_module, shell, answers, references) as (ask, compute, rendered, output):
            shell.onecmd('plot rdf')
        parse.assert_called_once_with('broken.cif')
        assert shell.last_command_ok is False and shell.command_failures == 1
        compute.assert_not_called()
        save.assert_not_called()
        assert rendered == []
        text = output.getvalue()
        assert 'Available references for X-Y' in text and 'no built-in phase contains' in text, text
        assert 'ValueError' in text and 'broken.cif' in text, text
        assert shell.state.plot_recipes == before


def test_numeric_selection_serves_only_the_curves_that_phase_contains():
    """Mixed selection: a type-id curve resolved through display_label, an element
    curve and an unreadable curve. Picking α-Fe (menu entry 1 in database order)
    overlays Fe-Fe only; the Fe-O curve is told it got nothing."""
    _util.require_numpy()
    from lammps_post import references, shell as shell_module

    with tempfile.TemporaryDirectory() as tmp:
        shell = _shell(shell_module, tmp, {'rdf_1-2': {'label': '1-2', 'display_label': 'Fe-O'},
                                           'rdf_Fe-Fe': 'Fe-Fe', 'rdf_all': 'all'})
        assert references.get_available_phases()[0][0] == 'alpha-Fe'
        answers = [shell.state.output_dir, 'all', 'y', '1']
        with _driven(shell_module, shell, answers, references) as (ask, compute, rendered, output):
            shell.onecmd('plot rdf')
        assert shell.last_command_ok is True, output.getvalue()
        assert ask.call_count == len(answers)
        assert [(call.args[0], call.kwargs['pair']) for call in compute.call_args_list] == [('alpha-Fe', ('Fe', 'Fe'))]
        by_label = dict(rendered)
        assert by_label['1-2'] is None and by_label['all'] is None
        assert [ref['phase'] for ref in by_label['Fe-Fe']] == ['alpha-Fe']
        text = output.getvalue()
        assert 'Available references for Fe-O, Fe-Fe' in text, text
        assert '1.' in text and 'α-Fe (BCC)  [Fe-Fe]' in text, text
        assert 'rdf_all: cannot read its atom pair' in text, text
        assert 'rdf_1-2: no Fe-O reference among the selected sources' in text, text
        assert 'rdf_Fe-Fe: no' not in text, text
        assert shell.state.plot_recipes['rdf']['_ref_rdfs'] == {
            'rdf_1-2': None, 'rdf_Fe-Fe': by_label['Fe-Fe'], 'rdf_all': None}
