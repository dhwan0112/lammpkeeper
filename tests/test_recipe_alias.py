"""REV-UI-2: 'plot redo/edit <name>' finds recipes saved under normalized keys.

Interactive plots store recipes under normalized titles (`plot charge` saves
`charge_evolution`), but the shell advertises `plot redo <name>` with the name
the user typed. Before the fix `plot redo charge` said "No saved recipe". The
stored keys must stay unchanged, and old key names must keep working.
"""
import contextlib
import io
from pathlib import Path
import shlex
import tempfile
from unittest.mock import PropertyMock, patch

import _util

# dispatch name -> stored recipe key(s) an interactive session writes.
TABLE = {
    'charge': 'charge_evolution',
    'charge_z': 'charge_z_distribution',
    'oar': 'oxygen_absorption_rate',
    'penetration': 'o_penetration',
    'penetration_trend': 'o_penetration_trend',
    'dissociation': 'o2_dissociation',
    'spin': 'spin_evolution',
}
# Names whose stored key already equals the dispatch name.
IDENTITY = ('thermo', 'thermostat', 'pressure', 'rdf', 'penetration_profile')


def _shell():
    """A bare noninteractive shell with its handlers replaced by recorders."""
    from lammps_post.shell import LammpsPostShell
    shell = LammpsPostShell()
    shell.noninteractive = True
    shell.calls = []
    shell.state.verify_trajectory_source = lambda: None
    return shell


def _record(shell, name):
    """Replace _iplot_<name> with a recorder of (name, _batch, _edit_mode)."""
    def handler(opts, _batch=False, _edit_mode=False):
        """Record the call instead of plotting."""
        shell.calls.append((name, _batch, _edit_mode))
    setattr(shell, '_iplot_' + name, handler)


def _run(shell, command):
    """Run one command and return captured stdout."""
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        shell.onecmd(command)
    return buf.getvalue()


def test_redo_and_edit_accept_every_dispatch_name():
    """Each saved stored key is reachable by redo/edit under its dispatch name."""
    _util.require_numpy()
    for name, key in TABLE.items():
        with tempfile.TemporaryDirectory() as tmp:
            shell = _shell()
            shell.state.output_dir = tmp
            _record(shell, name)
            shell.state.plot_recipes[key] = {'normalize': True, 'lw': 2.0}
            text = _run(shell, 'plot redo %s' % name)
            assert shell.last_command_ok is True, (name, text)
            assert 'No saved recipe' not in text, (name, text)
            assert shell.calls == [(name, True, False)], (name, shell.calls)
            shell.calls.clear()
            text = _run(shell, 'plot edit %s' % name)
            assert shell.last_command_ok is True, (name, text)
            assert shell.calls == [(name, False, True)] or \
                shell.calls == [(name, True, True)], (name, shell.calls)


def test_stored_key_names_still_work():
    """The old, stored key names keep working for redo and edit."""
    _util.require_numpy()
    for name, key in TABLE.items():
        with tempfile.TemporaryDirectory() as tmp:
            shell = _shell()
            shell.state.output_dir = tmp
            _record(shell, name)
            shell.state.plot_recipes[key] = {'normalize': False}
            text = _run(shell, 'plot redo %s' % key)
            assert shell.last_command_ok is True, (key, text)
            assert shell.calls == [(name, True, False)], (key, shell.calls)
            assert key in shell.state.plot_recipes
    for name in IDENTITY:
        shell = _shell()
        _record(shell, name)
        # Dispatch guards need loaded data; the recorder never reads it.
        shell.state.log_data = {'step': []}
        shell.state.dump_frames = [{}]
        shell._analyze_rdf = lambda *a, **k: None
        shell.state.plot_recipes[name] = {'_dpi': 100}
        with tempfile.TemporaryDirectory() as tmp:
            shell.state.output_dir = tmp
            _run(shell, 'plot redo %s' % name)
        assert shell.last_command_ok is True, name
        assert shell.calls == [(name, True, False)], (name, shell.calls)


def test_missing_recipe_and_unknown_name_still_fail_visibly():
    """Without a saved recipe redo warns; it does not invent one."""
    _util.require_numpy()
    shell = _shell()
    text = _run(shell, 'plot redo charge')
    assert 'No saved recipe' in text, text
    assert shell.calls == []


def test_penetration_trend_legacy_key_still_found():
    """`penetration_trend` is also saved by the handler; both keys resolve."""
    _util.require_numpy()
    shell = _shell()
    _record(shell, 'penetration_trend')
    shell.state.plot_recipes['penetration_trend'] = {'_dpi': 100}
    with tempfile.TemporaryDirectory() as tmp:
        shell.state.output_dir = tmp
        _run(shell, 'plot redo penetration_trend')
    assert shell.calls == [('penetration_trend', True, False)], shell.calls


def test_charge_end_to_end_save_then_redo_writes_figure():
    """Real interactive `plot charge` saves a recipe; `plot redo charge` rewrites the figure."""
    _util.require_numpy()
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        _util.skip('matplotlib missing: charge figure not exercised')
        return
    from lammps_post.shell import LammpsPostShell
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dump = root / 'q.dump'
        text = ''
        for step in (0, 10):
            text += ('ITEM: TIMESTEP\n%d\nITEM: NUMBER OF ATOMS\n2\n'
                     'ITEM: BOX BOUNDS pp pp pp\n0 10\n0 10\n0 10\n'
                     'ITEM: ATOMS id type element x y z q\n'
                     '1 1 Fe 1 1 1 0.5\n2 2 O 2 2 2 -0.5\n' % step)
        dump.write_text(text)
        shell = LammpsPostShell()
        shell.noninteractive = True
        shell.state.output_dir = str(root / 'out')
        with contextlib.redirect_stdout(io.StringIO()):
            shell.onecmd('load dump %s' % shlex.quote(str(dump)))
            shell.onecmd('set types 1=Fe 2=O')
            shell.onecmd('set dt 1')
            shell.onecmd('analyze charge')
        assert shell.last_command_ok and shell.state.cache.get('charge')
        # Save the recipe the way an interactive session does: prompts answered
        # with their defaults.
        with patch.object(LammpsPostShell, '_no_prompt',
                          new_callable=PropertyMock, return_value=False):
            with patch.object(LammpsPostShell, '_ask',
                              lambda self, prompt, default=None: default):
                _run(shell, 'plot charge')
        assert shell.last_command_ok is True
        assert 'charge_evolution' in shell.state.plot_recipes
        out = root / 'out'
        for p in out.glob('*'):
            p.unlink()
        text = _run(shell, 'plot redo charge')
        assert shell.last_command_ok is True, text
        assert 'No saved recipe' not in text, text
        assert any(p.suffix == '.png' for p in out.glob('*')), (list(out.glob('*')), text)
