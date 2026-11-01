"""GEN-2b: session routing of explicit run metadata (ADR-0005 steps 3-4).

Covers the input classification/conflict rules, explicit-over-heuristic
resolution, the unresolved-timestep contract, the generic force field,
manual `set dt` / `set forcefield` override lifetimes, load/unload
transactions, status output, the `--input` flag and Fe-O invariance.
Species labels are made up (A, B, X) with sparse type IDs so a hardcoded
element name or preset fails loudly. Fe-O pins were measured on unmodified
main (5dce7f0) with the real prep writers and the committed ACE fixture.
"""
import contextlib
import io
import itertools
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import warnings

import _util

SPARSE = {1: 'A', 5: 'B', 9: 'X'}
LOG = os.path.join(_util.REPO_ROOT, 'tests', 'fixtures', 'ace_examples',
                   'regular_MD', 'log.lammps')
FIXTURE_IN = os.path.join(_util.REPO_ROOT, 'tests', 'fixtures', 'ace_examples',
                          'regular_MD', 'run_md.lammps')


def _quiet(call):
    """Run call with stdout discarded; exceptions and warnings still escape."""
    with contextlib.redirect_stdout(io.StringIO()):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return call()


def _shell():
    """Return a real shell configured for noninteractive, history-free use."""
    from lammps_post.shell import LammpsPostShell
    shell = LammpsPostShell()
    shell.noninteractive = True
    return shell


def _load(shell, kind, path, extra=''):
    """Load one source through the actual command parser."""
    return _quiet(lambda: shell.do_load(f'{kind} {shlex.quote(str(path))}{extra}'))


def _run(shell, command):
    """Run one shell command; return captured stdout and leave status on the shell."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            shell.onecmd(command)
    return out.getvalue()


def _raises(call, *needles):
    """Require a ValueError whose text contains every needle (case-insensitive)."""
    try:
        _quiet(call)
    except ValueError as exc:
        for needle in needles:
            assert str(needle).lower() in str(exc).lower(), str(exc)
        return str(exc)
    raise AssertionError('expected ValueError')


def _warnings_of(call):
    """Return the RuntimeWarning texts a call emits (stdout discarded)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        with contextlib.redirect_stdout(io.StringIO()):
            call()
    return [str(w.message) for w in caught if issubclass(w.category, RuntimeWarning)]


def _dump(path, types=(1, 5, 9), labels=('A', 'B', 'X'), flags='pp pp pp'):
    """Write three frames with two atoms per type; atoms drift 0.1 A per frame in x."""
    text = ''
    n = 2 * len(types)
    for step in range(3):
        rows = []
        for index, tid in enumerate(t for t in types for _ in (0, 1)):
            label = labels[types.index(tid)] if labels else None
            x = 1.0 + index + 0.1 * step
            ident = f'{index + 1} {tid}' + (f' {label}' if label else '')
            rows.append(f'{ident} {x:.6f} 2 3')
        columns = 'id type element x y z' if labels else 'id type x y z'
        text += (f'ITEM: TIMESTEP\n{step * 100}\nITEM: NUMBER OF ATOMS\n{n}\n'
                 f'ITEM: BOX BOUNDS {flags}\n0 20\n0 20\n0 20\n'
                 f'ITEM: ATOMS {columns}\n' + '\n'.join(rows) + '\n')
    Path(path).write_text(text)


def _input(path, pair='eam/alloy', units='metal', timestep='0.001', atom_style='atomic',
           coeff='default', extra=''):
    """Write an input whose declarations are chosen per field; None omits a command."""
    lines = []
    if units is not None:
        lines.append(f'units {units}')
    if atom_style is not None:
        lines.append(f'atom_style {atom_style}')
    lines.append('boundary p p p')
    if pair is not None:
        lines.append(f'pair_style {pair}')
        if coeff == 'default':
            slots = ' '.join(SPARSE.get(t, 'NULL') for t in range(1, 10))
            coeff = f'pair_coeff * * pot.eam.alloy {slots}'
        if coeff:
            lines.append(coeff)
    if timestep is not None:
        lines.append(f'timestep {timestep}')
    Path(path).write_text('\n'.join(lines) + '\n' + extra)


def _session(tmp, **input_kwargs):
    """Return (shell, dump path, input path) with files written but nothing loaded."""
    shell = _shell()
    shell.state.output_dir = str(Path(tmp) / 'out')
    dump, inp = Path(tmp) / 'traj.dump', Path(tmp) / 'run.in'
    _dump(dump)
    _input(inp, **input_kwargs)
    return shell, dump, inp


def _view(shell):
    """Snapshot the metadata visible to consumers, for equality checks."""
    s = shell.state
    return (s.ff, s.ff_info['unit_system'], s.ff_info['dt_fs'], dict(s.atom_types),
            dict(s.manual_overrides),
            None if s.run_metadata is None else tuple(
                (n, getattr(s.run_metadata, n).value, getattr(s.run_metadata, n).status)
                for n in s.run_metadata.FIELDS))


# ───────────── parse_input: classification and conflicts ─────────────

def _parse_text(text):
    """Parse input text through the real parser, always removing the temp file."""
    from lammps_post.parsers import parse_input
    with tempfile.NamedTemporaryFile('w', suffix='.in', delete=False) as handle:
        handle.write(text)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return parse_input(handle.name), handle.name
    finally:
        os.remove(handle.name)


def test_legacy_forcefield_key_uses_exact_token_classifier():
    """config['forcefield'] follows classify_pair_style; substrings never count."""
    cases = {'pace': 'ace', 'pace/kk': 'ace', 'reaxff NULL': 'reaxff', 'reax/c NULL': 'reaxff',
             'hdnnp 6.0 dir nnp': 'hdnnp', 'eam/alloy': 'generic', 'lj/cut 2.5': 'generic',
             'hybrid/overlay pace zbl 1.0 2.0': 'generic', 'ace': 'generic', 'n2p2': 'generic',
             'eam/alloy': 'generic'}
    for pair, expected in cases.items():
        config, _ = _parse_text(f'units metal\npair_style {pair}\n')
        assert config['forcefield'] == expected, (pair, config['forcefield'])
    trap, _ = _parse_text('units metal\npair_style eam/alloy\n'
                          'pair_coeff * * pace_reaxff_hdnnp.eam.alloy A\n')
    assert trap['forcefield'] == 'generic'
    none, _ = _parse_text('units metal\natom_style atomic\n')
    assert none['forcefield'] == 'unknown'


def test_contradictory_pair_style_and_atom_style_are_rejected():
    """Differing repeats raise with the path and both values; equal repeats pass."""
    for command, first, second in (('pair_style', 'eam/alloy', 'lj/cut 2.5'),
                                   ('atom_style', 'atomic', 'charge')):
        text = f'units metal\n{command} {first}\n{command} {second}\n'
        from lammps_post.parsers import parse_input
        with tempfile.NamedTemporaryFile('w', suffix='.in', delete=False) as handle:
            handle.write(text)
        try:
            try:
                parse_input(handle.name)
            except ValueError as exc:
                message = str(exc)
            else:
                raise AssertionError(f'{command} conflict accepted')
        finally:
            os.remove(handle.name)
        assert handle.name in message and repr(first) in message and repr(second) in message
    config, _ = _parse_text('units metal\natom_style atomic\natom_style atomic\n'
                            'pair_style eam/alloy\npair_style eam/alloy\n')
    assert config['pair_style'] == 'eam/alloy' and config['atom_style'] == 'atomic'


# ───────────── explicit metadata beats the dump heuristic ─────────────

def test_explicit_eam_and_lj_are_never_reported_as_domain_families():
    """EAM/LJ inputs stay generic in both load orders, with no preset labels or spin."""
    _util.require_numpy()
    for pair in ('eam/alloy', 'lj/cut 2.5', 'hybrid/overlay pace zbl 1.0 2.0'):
        for order in ('input_first', 'dump_first'):
            with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
                # Numeric dump with three sparse types would be guessed ACE.
                shell, dump, inp = _session(tmp, pair=pair, coeff='')
                _dump(dump, labels=None)
                steps = [('input', inp), ('dump', dump)]
                for kind, path in (steps if order == 'input_first' else steps[::-1]):
                    _load(shell, kind, path)
                s = shell.state
                assert s.ff == 'generic', (pair, order, s.ff)
                assert s.ff_info['forcefield'] == 'generic'
                assert s.run_metadata.ff_family.status == 'explicit'
                assert s.run_metadata.ff_family.value == 'generic'
                # The heuristic's Fe/O preset labels must not leak in.
                assert s.atom_types == {}, (pair, order, s.atom_types)
                assert s.dt_fs == 1.0
                out = _run(shell, 'analyze spin')
                assert shell.last_command_ok is False
                assert 'not applicable' in out.lower()


def test_hybrid_with_pace_is_generic_and_dump_ace_guess_is_replaced():
    """A hybrid pair style replaces the ACE shape guess instead of inheriting it."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell, dump, inp = _session(tmp, pair='hybrid/overlay pace zbl 1.0 2.0',
                                    coeff='pair_coeff * * pace x.yace A NULL NULL NULL B NULL NULL NULL X')
        _load(shell, 'dump', dump)
        assert shell.state.ff == 'ace' and shell.state.run_metadata.ff_family.status == 'guessed'
        _load(shell, 'input', inp)
        assert shell.state.ff == 'generic'
        assert shell.state.run_metadata.pair_style.value.startswith('hybrid/overlay')
        _quiet(lambda: shell.do_unload('input'))
        assert shell.state.ff == 'ace'
        assert shell.state.run_metadata.ff_family.status == 'guessed'


def test_made_up_labels_and_sparse_ids_work_under_generic_family():
    """Explicit A/B/X labels on IDs 1/5/9 drive RDF and MSD with no Fe/O presets."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell, dump, inp = _session(tmp)
        _load(shell, 'input', inp)
        _load(shell, 'dump', dump)
        s = shell.state
        assert s.ff == 'generic' and s.atom_types == SPARSE
        assert s.species_map.type_sets() == {'A': frozenset({1}), 'B': frozenset({5}),
                                              'X': frozenset({9})}
        assert s.dt_fs == 1.0
        _run(shell, 'analyze rdf A-B')
        assert shell.last_command_ok, 'rdf'
        _run(shell, 'analyze msd --species A')
        assert shell.last_command_ok, 'msd'
        # Two atoms drift 0.2 A over the run: MSD 0.04 A^2 at the last frame.
        assert abs(float(s.cache['msd_A']['msd'][-1]) - 0.04) < 1e-9


def test_generic_element_only_dump_gets_no_preset_type_numbers():
    """Fe/O elements under an explicit generic style are numbered 1/2, not ACE slots 1/3."""
    _util.require_numpy()
    rows = {0: ['1 Fe 1 2 3', '2 O 5 2 3'], 1: ['1 Fe 1.1 2 3', '2 O 5.1 2 3']}
    text = ''.join(f'ITEM: TIMESTEP\n{k}\nITEM: NUMBER OF ATOMS\n2\n'
                   'ITEM: BOX BOUNDS pp pp pp\n0 20\n0 20\n0 20\nITEM: ATOMS id element x y z\n'
                   + '\n'.join(r) + '\n' for k, r in rows.items())
    results = {}
    for name, pair in (('generic', 'lj/cut 2.5'), ('legacy', None)):
        with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
            dump = Path(tmp) / 'e.dump'
            dump.write_text(text)
            shell = _shell()
            if pair:
                inp = Path(tmp) / 'run.in'
                _input(inp, pair=pair, coeff='')
                _load(shell, 'input', inp)
            _load(shell, 'dump', dump)
            frame = shell.state.dump_frames[0]
            col = shell.state.dump_col_idx['type']
            results[name] = [int(v) for v in frame['atoms'][:, col]]
    assert results['legacy'] == [1, 3], results      # unchanged ACE-slot convention
    assert results['generic'] == [1, 2], results


# ───────────── time rule and unresolved timestep ─────────────

def test_time_rule_matrix_explicit_partial_and_legacy_paths():
    """Legacy guessed dt only with no pair/units/timestep declared; partials are unresolved."""
    _util.require_numpy()
    cases = [
        # The sparse 3-type dump is guessed ACE by the legacy heuristic: dt 0.25 fs.
        ('nothing declared', dict(pair=None, units=None, timestep=None), 'guessed', 0.25),
        ('units only', dict(pair=None, units='metal', timestep=None), 'unresolved', None),
        ('timestep only', dict(pair=None, units=None, timestep='0.5'), 'unresolved', None),
        ('pair only', dict(pair='eam/alloy', units=None, timestep=None), 'unresolved', None),
        ('units+pair', dict(pair='eam/alloy', units='real', timestep=None), 'unresolved', None),
        ('metal+timestep', dict(pair=None, units='metal', timestep='0.002'), 'explicit', 2.0),
        ('real+timestep', dict(pair='eam/alloy', units='real', timestep='0.5'), 'explicit', 0.5),
    ]
    for name, kwargs, status, expected in cases:
        for order in ('input_first', 'dump_first'):
            with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
                shell, dump, inp = _session(tmp, coeff='', **kwargs)
                steps = [('input', inp), ('dump', dump)]
                for kind, path in (steps if order == 'input_first' else steps[::-1]):
                    _load(shell, kind, path)
                md = shell.state.run_metadata
                assert md.dt_fs.status == status, (name, order, md.dt_fs)
                assert shell.state.dt_fs_or_none == expected, (name, order)
                if expected is None:
                    _raises(lambda: shell.state.dt_fs, 'timestep unresolved', 'set dt')
                else:
                    assert shell.state.dt_fs == expected


def test_guessed_units_never_confirm_an_explicit_timestep():
    """An explicit timestep without explicit units stays unresolved despite a guessed dump unit."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell, dump, inp = _session(tmp, pair=None, units=None, timestep='0.5', coeff='')
        _load(shell, 'dump', dump)
        _load(shell, 'input', inp)
        md = shell.state.run_metadata
        assert md.units.status == 'guessed' and md.dt_fs.status == 'unresolved'
        assert md.timestep.status == 'explicit'


def test_unresolved_dt_fails_time_analyses_but_not_structural_ones():
    """MSD/penetration/OAR fail with the actionable text; RDF and density still run."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        # An explicit O label (type 5) lets the O-based analyses reach their time axis.
        shell, dump, inp = _session(tmp, timestep=None, coeff=(
            'pair_coeff * * pot.eam.alloy A NULL NULL NULL O NULL NULL NULL X'))
        _dump(dump, labels=('A', 'O', 'X'))
        _load(shell, 'input', inp)
        _load(shell, 'dump', dump)
        assert shell.state.dt_fs_or_none is None
        _run(shell, 'set surface_z 5')   # penetration/OAR need a plane; dt is the variable here
        for command in ('analyze msd --species A', 'analyze penetration', 'analyze oar',
                        'analyze dissociation'):
            before = shell.command_failures
            out = _run(shell, command)
            assert shell.last_command_ok is False, command
            assert shell.command_failures == before + 1, command
            assert 'timestep unresolved' in out, (command, out)
            assert "set dt" in out and 'units and timestep' in out
        for command in ('analyze rdf A-O', 'analyze density'):
            _run(shell, command)
            assert shell.last_command_ok, command
        assert any(k.startswith('rdf_') for k in shell.state.cache)
        # A manual override resolves it and enables the time analysis.
        _run(shell, 'set dt 2.0')
        assert shell.last_command_ok and shell.state.dt_fs == 2.0
        _run(shell, 'analyze msd --species A')
        assert shell.last_command_ok


def test_lj_units_fail_time_consumers_and_reject_manual_dt():
    """Explicit lj units give no fs conversion; set dt cannot create one; RDF still works."""
    _util.require_numpy()
    from lammpkeeper.io.metadata import RunMetadata
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell, dump, inp = _session(tmp)
        _load(shell, 'input', inp)
        _load(shell, 'dump', dump)
        # parse_input rejects units lj, so inject the explicit record it cannot yet build.
        lj = RunMetadata.from_explicit(str(inp), pair_style='lj/cut 2.5', ff_family='generic',
                                       units='lj', timestep=0.005)
        shell.state.input_config['metadata'] = lj
        shell._publish_metadata()
        assert shell.state.run_metadata.dt_fs.status == 'unresolved'
        assert 'lj' in shell.state.run_metadata.dt_fs.note
        _raises(lambda: shell.state.dt_fs, 'timestep unresolved')
        out = _run(shell, 'analyze msd --species A')
        assert shell.last_command_ok is False and 'timestep unresolved' in out
        before = dict(shell.state.manual_overrides)
        out = _run(shell, 'set dt 1.0')
        assert shell.last_command_ok is False and 'lj' in out
        assert shell.state.manual_overrides == before == {}
        _run(shell, 'analyze rdf A-B')
        assert shell.last_command_ok


def test_manual_dt_shown_as_manual_and_warns_when_it_differs():
    """set dt is a separate manual record, visible in status, warning on disagreement."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell, dump, inp = _session(tmp)
        _load(shell, 'input', inp)
        _load(shell, 'dump', dump)
        messages = _warnings_of(lambda: shell.do_set('dt 0.5'))
        assert any('differs from resolved evidence' in m and '1.0' in m for m in messages)
        s = shell.state
        assert s.dt_fs == 0.5 and s.manual_overrides['dt']['value'] == 0.5
        # Source evidence stays untouched beneath the override.
        assert s.run_metadata.dt_fs.value == 1.0 and s.run_metadata.dt_fs.status == 'explicit'
        info = _run(shell, 'info')
        assert 'manual override dt' in info and '[manual]' in info and 'manual' in info
        assert _warnings_of(lambda: shell.do_set('dt 1.0')) == []


# ───────────── set forcefield ─────────────

def test_set_forcefield_generic_is_a_manual_override_with_no_presets():
    """generic is accepted, recorded manually, removes spin/presets and never indexes FORCE_FIELDS."""
    _util.require_numpy()
    from lammpkeeper.common.mapping import FORCE_FIELDS
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell = _shell()
        dump = Path(tmp) / 'traj.dump'
        _dump(dump, types=(1, 2, 3), labels=None)
        _load(shell, 'dump', dump)
        s = shell.state
        assert s.ff == 'ace' and s.atom_types == {1: 'Fe_up', 2: 'Fe_down', 3: 'O'}
        messages = _warnings_of(lambda: shell.do_set('forcefield generic'))
        assert any('differs from resolved evidence' in m for m in messages)
        assert s.ff == 'generic' and s.manual_overrides['forcefield']['value'] == 'generic'
        assert s.atom_types == {}, s.atom_types
        assert 'generic' not in FORCE_FIELDS
        _run(shell, 'analyze spin')
        assert shell.last_command_ok is False
        assert 'manual' in _run(shell, 'info')
        _run(shell, 'set forcefield nonsense')
        assert shell.last_command_ok is False and s.ff == 'generic'
        _run(shell, 'set forcefield ace')
        assert s.ff == 'ace' and s.atom_types == {1: 'Fe_up', 2: 'Fe_down', 3: 'O'}


def test_set_forcefield_failure_restores_previous_override_and_labels():
    """A label validation failure leaves the earlier override, labels and metadata intact."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell, dump, inp = _session(tmp)
        _load(shell, 'input', inp)
        _load(shell, 'dump', dump)
        s = shell.state
        _quiet(lambda: shell.do_set('forcefield hdnnp'))
        before = _view(shell)
        original = s._validate_species

        def failing(*args, **kwargs):
            """Simulate a species validation failure for the next rebuild."""
            raise ValueError('boom')

        s._validate_species = failing
        try:
            _raises(lambda: shell.do_set('forcefield reaxff'), 'boom')
        finally:
            s._validate_species = original
        assert _view(shell) == before


# ───────────── override lifetimes ─────────────

def _overrides(shell):
    """Set both manual overrides and return the shell for lifetime checks."""
    _quiet(lambda: shell.do_set('dt 0.75'))
    _quiet(lambda: shell.do_set('forcefield hdnnp'))
    assert set(shell.state.manual_overrides) == {'dt', 'forcefield'}
    return shell


def test_overrides_survive_log_and_manifest_loads_and_unloads():
    """Log/manifest-only changes keep manual overrides and their published values."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell, dump, inp = _session(tmp)
        _load(shell, 'input', inp)
        _load(shell, 'dump', dump)
        _overrides(shell)
        manifest = Path(tmp) / 'run.json'
        manifest.write_text(json.dumps({'schema_version': 1, 'species_groups': {'AB': [1, 5]}}))
        for action in (lambda: shell.do_load(f'log {shlex.quote(LOG)}'),
                       lambda: shell.do_load(f'manifest {shlex.quote(str(manifest))}'),
                       lambda: shell.do_unload('log'), lambda: shell.do_unload('manifest')):
            assert [m for m in _warnings_of(action) if 'Manual overrides' in m] == []
            assert set(shell.state.manual_overrides) == {'dt', 'forcefield'}
            assert shell.state.dt_fs == 0.75 and shell.state.ff == 'hdnnp'


def test_overrides_expire_visibly_on_input_data_dump_load_and_unload():
    """Successful typed-source changes clear overrides, warn, and restore evidence."""
    _util.require_numpy()
    for action in ('load input', 'load dump', 'unload input', 'unload dump', 'unload data',
                   'load data'):
        with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
            shell, dump, inp = _session(tmp)
            data = Path(tmp) / 'run.data'
            data.write_text('x\n\n1 atoms\n9 atom types\n\n0 20 xlo xhi\n0 20 ylo yhi\n0 20 zlo zhi\n'
                            '\nMasses\n\n' + '\n'.join(f'{t} 1.0' for t in range(1, 10)) +
                            '\n\nAtoms # atomic\n\n1 1 1 1 1\n')
            _load(shell, 'input', inp)
            _load(shell, 'dump', dump)
            _load(shell, 'data', data)
            _overrides(shell)
            kind = action.split()[1]
            path = {'input': inp, 'dump': dump, 'data': data}[kind]
            if action.startswith('load'):
                messages = _warnings_of(lambda: shell.do_load(f'{kind} {shlex.quote(str(path))}'))
            else:
                messages = _warnings_of(lambda: shell.do_unload(kind))
            assert any('Manual overrides' in m and "'dt'" in m and 'forcefield' in m
                       for m in messages), (action, messages)
            assert shell.state.manual_overrides == {}, action
            if kind != 'dump' or action.startswith('load'):
                # Published values return to evidence (explicit dt 1.0 from the input).
                if shell.state.input_config is not None:
                    assert shell.state.dt_fs == 1.0 and shell.state.ff == 'generic', action


def test_failed_load_restores_overrides_and_session():
    """A rejected candidate keeps overrides, metadata, caches and the old input."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell, dump, inp = _session(tmp)
        _load(shell, 'input', inp)
        _load(shell, 'dump', dump)
        _overrides(shell)
        shell.state.cache['sentinel'] = marker = object()
        before = _view(shell)
        bad = Path(tmp) / 'bad.in'
        _input(bad, extra='pair_style lj/cut 2.5\n')
        _raises(lambda: shell.do_load(f'input {shlex.quote(str(bad))}'), str(bad), 'pair_style')
        assert _view(shell) == before
        assert shell.state.input_path == str(inp) and shell.state.cache['sentinel'] is marker
        # A bad dump (missing file) likewise changes nothing.
        _raises(lambda: shell.do_load(f'dump {shlex.quote(str(Path(tmp) / "none.dump"))}'), 'not found')
        assert _view(shell) == before
        _raises(lambda: shell.do_load(f'input {shlex.quote(str(Path(tmp) / "none.in"))}'), 'not found')
        assert _view(shell) == before


def test_unload_all_clears_overrides_and_returns_to_legacy_defaults():
    """unload all leaves no manual record and no stale explicit classification."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell, dump, inp = _session(tmp)
        _load(shell, 'log', LOG)
        _load(shell, 'input', inp)
        _load(shell, 'dump', dump)
        _overrides(shell)
        _quiet(lambda: shell.do_unload('all'))
        s = shell.state
        assert s.manual_overrides == {} and s.ff == 'unknown'
        assert s.run_metadata.ff_family.status == 'unresolved'
        assert s.input_config is None and s.dump_frames is None


def test_effective_metadata_changes_invalidate_caches():
    """Input/override changes drop cached numbers that depended on the old metadata."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell, dump, inp = _session(tmp)
        _load(shell, 'dump', dump)
        for action in (lambda: shell.do_load(f'input {shlex.quote(str(inp))}'),
                       lambda: shell.do_set('dt 3.0'), lambda: shell.do_set('forcefield generic'),
                       lambda: shell.do_unload('input')):
            shell.state.cache['sentinel'] = object()
            _quiet(action)
            assert 'sentinel' not in shell.state.cache


# ───────────── load/unload order permutations ─────────────

def test_load_order_permutations_and_unload_match_a_fresh_session():
    """Any input/dump/log order gives the same metadata; unloads equal never loading."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        base, dump, inp = _session(tmp)
        sources = {'input': inp, 'dump': dump, 'log': LOG}

        def build(kinds):
            """Return a fresh shell with the named sources loaded in order."""
            shell = _shell()
            for kind in kinds:
                _load(shell, kind, sources[kind])
            return shell

        reference = _view(build(('input', 'dump', 'log')))
        for order in itertools.permutations(sources):
            assert _view(build(order)) == reference, order
        for removed in sources:
            remaining = [k for k in ('input', 'dump', 'log') if k != removed]
            shell = build(('input', 'dump', 'log'))
            _quiet(lambda: shell.do_unload(removed))
            assert _view(shell) == _view(build(remaining)), removed
        # Replacement with a different explicit pair style takes over completely.
        other = Path(tmp) / 'other.in'
        _input(other, pair='lj/cut 2.5', timestep='0.002', coeff='')
        shell = build(('input', 'dump'))
        _load(shell, 'input', other)
        assert shell.state.ff == 'generic' and shell.state.dt_fs == 2.0
        assert shell.state.run_metadata.pair_style.value == 'lj/cut 2.5'


def test_log_input_disagreement_is_diagnosed_in_both_load_orders():
    """Combined thermo metadata names both sources and values whichever file loaded last."""
    _util.require_numpy()
    cases = [dict(units='real', timestep='0.5'),            # unit disagreement
             dict(units='metal', timestep='0.0005')]        # timestep disagreement (0.5 vs 1 fs)
    for kwargs in cases:
        for order in (('log', 'input'), ('input', 'log')):
            with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
                shell, dump, inp = _session(tmp, coeff='', **kwargs)
                for kind in order:
                    _load(shell, kind, {'log': LOG, 'input': inp}[kind])
                what = 'units' if kwargs['units'] == 'real' else 'timesteps'
                text = _raises(shell._thermo_plot_metadata, 'conflicting explicit ' + what,
                               'log ' + LOG, 'input ' + str(inp))
                assert ("'metal'" in text and "'real'" in text) or ('1.0' in text and '0.5' in text)
    # Agreement is accepted and an input-only dt is used.
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell, dump, inp = _session(tmp, coeff='', units='metal', timestep='0.001')
        _load(shell, 'log', LOG)
        _load(shell, 'input', inp)
        assert _quiet(shell._thermo_plot_metadata) == ('metal', 1.0)


# ───────────── status output ─────────────

def test_info_reports_each_field_with_status_and_source():
    """info lists explicit, guessed and unresolved fields with their sources."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell, dump, inp = _session(tmp, timestep=None)
        _load(shell, 'dump', dump)
        guessed = _run(shell, 'info')
        assert '[guessed]' in guessed and 'dump heuristic' in guessed and 'ff_family' in guessed
        _load(shell, 'input', inp)
        text = _run(shell, 'info')
        for field in ('pair_style', 'ff_family', 'atom_style', 'units', 'timestep', 'dt_fs'):
            assert field + ':' in text, field
        assert "'eam/alloy' [explicit]" in text and str(inp) in text
        assert 'dt_fs: - [unresolved]' in text and 'Timestep' in text and 'unresolved' in text
        assert "'metal' [explicit]" in text


# ───────────── CLI --input ─────────────

def _cli(root, args, batch=None):
    """Run the real module entry point with an isolated HOME; return the process result."""
    home = Path(root) / 'home'
    home.mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(home), MPLBACKEND='Agg', LKPR_NO_HISTORY='1')
    command = [sys.executable, '-m', 'lammps_post'] + list(args) + ['--output', str(Path(root) / 'plots')]
    if batch is not None:
        script = Path(root) / 'commands.txt'
        script.write_text('\n'.join(batch) + '\n')
        command += ['--batch', str(script)]
    return subprocess.run(command, cwd=_util.REPO_ROOT, env=env, text=True,
                          capture_output=True, timeout=120)


def test_cli_help_documents_input_flag():
    """The flag exists with help text and the original flags remain."""
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        result = _cli(tmp, ['--help'])
        assert result.returncode == 0
        assert '--input' in result.stdout and 'input script' in result.stdout
        for flag in ('--dump', '--log', '--data', '--batch', '--analyze'):
            assert flag in result.stdout


def test_cli_input_one_shot_and_batch_exit_codes():
    """--input preloads before analyses; failures keep exit status 1, order is irrelevant."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        root = Path(tmp)
        _, dump, inp = _session(tmp)
        # One-shot success: explicit timestep from the input resolves the MSD time axis.
        for args in (['--input', str(inp), '--dump', str(dump)],
                     ['--dump', str(dump), '--input', str(inp)]):
            result = _cli(root, args + ['--analyze', 'msd --species A'])
            assert result.returncode == 0, result.stdout + result.stderr
            assert 'Final MSD' in result.stdout
        # Without the input the same one-shot uses the warned legacy guess (hdnnp) but works.
        legacy = _cli(root, ['--dump', str(dump), '--analyze', 'msd --species A'])
        assert legacy.returncode != 0 or 'Final MSD' in legacy.stdout
        # Partial explicit time metadata: time analysis fails, structure analysis succeeds.
        partial = root / 'partial.in'
        _input(partial, timestep=None)
        result = _cli(root, ['--input', str(partial), '--dump', str(dump),
                             '--analyze', 'msd --species A'])
        assert result.returncode == 1 and 'timestep unresolved' in result.stdout
        result = _cli(root, ['--input', str(partial), '--dump', str(dump), '--analyze', 'rdf A-B'])
        assert result.returncode == 0, result.stdout + result.stderr
        # A missing or contradictory input fails the preload and no analysis runs.
        result = _cli(root, ['--input', str(root / 'missing.in'), '--dump', str(dump),
                             '--analyze', 'rdf A-B'])
        assert result.returncode == 1 and 'rdf' not in result.stdout.lower().replace('rdf a-b', '')
        bad = root / 'bad.in'
        _input(bad, extra='pair_style lj/cut 2.5\n')
        result = _cli(root, ['--input', str(bad), '--dump', str(dump), '--analyze', 'rdf A-B'])
        assert result.returncode == 1 and 'pair_style' in result.stdout
        # Batch mode: --input first, then commands; a failing command still exits 1.
        ok = _cli(root, ['--input', str(inp), '--dump', str(dump)],
                  batch=['analyze rdf A-B', 'analyze msd --species A'])
        assert ok.returncode == 0, ok.stdout + ok.stderr
        failing = _cli(root, ['--input', str(partial), '--dump', str(dump)],
                       batch=['analyze rdf A-B', 'analyze msd --species A', 'analyze rdf A-B'])
        assert failing.returncode == 1 and 'timestep unresolved' in failing.stdout


# ───────────── Fe-O invariance (pins measured on main 5dce7f0) ─────────────

def test_feo_prep_style_and_fixture_sessions_match_main():
    """Prep-writer declarations and the ACE fixture give main's ff/units/dt_fs exactly."""
    _util.require_numpy()
    import contextlib as _c
    from lammps_pre.builders import build_all
    from lammps_pre.state import PreState
    from lammps_pre.writers import write_all
    fixture_dump = _util.FIXTURE
    expected = {'ace': ('ace', 'metal', 0.25), 'reaxff2010': ('reaxff', 'real', 0.25),
                'reaxff2015': ('reaxff', 'real', 0.25)}
    keep = ('units', 'atom_style', 'boundary', 'pair_style', 'pair_coeff', 'timestep', 'read_data')
    for ff, pinned in expected.items():
        with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
            state = PreState()
            state.nx, state.ny, state.nz = 4, 4, 8
            state.n_fixed_layers, state.n_thermostat_layers, state.n_o2 = 1, 2, 4
            state.set_ff(ff)
            with _c.redirect_stdout(io.StringIO()):
                build = build_all(state)
                write_all(build, state, tmp)
            written = [p for p in Path(tmp).iterdir() if p.suffix == '.in'][0]
            text = written.read_text()
            # Prep declares the step through a variable; it must resolve to an explicit value.
            assert 'variable        dt' in text and 'timestep        ${dt}' in text
            reduced = Path(tmp) / 'reduced.in'
            reduced.write_text('\n'.join(
                l for l in text.splitlines() if l.split() and (
                    l.split()[0] in keep or (l.split()[0] == 'variable' and l.split()[1] in ('dt', 'ffield')))
            ) + '\n')
            shell = _shell()
            _load(shell, 'input', reduced)
            s = shell.state
            assert (s.ff, s.ff_info['unit_system'], s.dt_fs) == pinned, ff
            assert s.run_metadata.timestep.status == 'explicit', ff
            assert s.run_metadata.dt_fs.status == 'explicit', ff
            if ff == 'ace':
                for order in (('input', 'dump'), ('dump', 'input')):
                    shell = _shell()
                    for kind in order:
                        _load(shell, kind, {'input': reduced, 'dump': fixture_dump}[kind])
                    assert (shell.state.ff, shell.state.dt_fs) == ('ace', 0.25)
                    assert shell.state.atom_types == {1: 'Fe_up', 2: 'Fe_down', 3: 'O'}
    # Committed fixture: dump alone is the warned legacy guess; its own input declares 1 fs.
    shell = _shell()
    _load(shell, 'dump', fixture_dump)
    s = shell.state
    assert (s.ff, s.ff_info['unit_system'], s.dt_fs) == ('ace', 'metal', 0.25)
    assert s.run_metadata.ff_family.status == 'guessed' and s.run_metadata.dt_fs.status == 'guessed'
    assert s.atom_types == {1: 'Fe_up', 2: 'Fe_down', 3: 'O'}
    for order in (('input', 'dump'), ('dump', 'input')):
        shell = _shell()
        for kind in order:
            _load(shell, kind, {'input': FIXTURE_IN, 'dump': fixture_dump}[kind])
        s = shell.state
        assert (s.ff, s.ff_info['unit_system'], s.dt_fs) == ('ace', 'metal', 1.0), order
        assert s.run_metadata.ff_family.status == 'explicit'


# ───────────── parent review follow-ups (2026-11-01) ─────────────

def test_undeclared_units_stay_unresolved_and_never_become_metal():
    """An input with pair_style/timestep but no units leaves units unresolved.

    Found by the GEN-2b review: with no trajectory loaded, units used to fall
    back to 'metal' silently. Status now shows 'unresolved' and a thermo plot
    without log units fails instead of assuming metal. With a dump loaded the
    heuristic unit is used but labelled guessed, never explicit.
    """
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell, dump, inp = _session(tmp, units=None)
        _load(shell, 'input', inp)
        s = shell.state
        assert s.ff_info['unit_system'] is None
        assert s.run_metadata.units.status == 'unresolved'
        info = _run(shell, 'info')
        assert any('Units' in line and 'unresolved' in line for line in info.splitlines()), info
        log = Path(tmp) / 'log.lammps'
        log.write_text('Step Temp\n0 300\n10 301\nLoop time of 1 on 1 procs for 10 steps with 6 atoms\n')
        _load(shell, 'log', log)
        _raises(shell._thermo_plot_metadata, 'units')
        _load(shell, 'dump', dump)
        assert s.run_metadata.units.status == 'guessed' and s.ff_info['unit_system'] == 'metal'


def test_failed_manual_dt_publication_leaves_no_override():
    """If publishing a manual dt fails, the override and published values roll back."""
    _util.require_numpy()
    from unittest.mock import patch
    with tempfile.TemporaryDirectory(prefix='lk-g2b-') as tmp:
        shell, dump, inp = _session(tmp)
        _load(shell, 'input', inp)
        _load(shell, 'dump', dump)
        before = _view(shell)
        with patch.object(type(shell), '_publish_metadata', side_effect=RuntimeError('boom')):
            try:
                _quiet(lambda: shell.do_set('dt 0.5'))
            except RuntimeError:
                pass
            else:
                raise AssertionError('publication failure was swallowed')
        assert _view(shell) == before
        assert 'dt' not in shell.state.manual_overrides
