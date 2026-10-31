"""EXEC-1: independent arithmetic and bounded, headless execution regressions."""
import contextlib
import copy
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
import warnings

import _util


def _request(path):
    """Build the minimal complete v1 request for a caller-selected log path."""
    return {'protocol_version': 1, 'request_id': 'synthetic-A',
            'operation': 'thermo.summary', 'operation_version': 1,
            'input': {'log': str(path)}, 'parameters': {}}


def _log(path, units='metal'):
    """Write generic three-sample columns with independently known statistics."""
    path.write_text((f'units {units}\n' if units else '') +
                    'run 4\nStep Temp PotEng KinEng TotEng Press Volume\n'
                    '0 2 -6 1 -5 -2 10\n2 4 -4 3 -1 0 12\n'
                    '4 6 -2 5 3 2 14\n')


def _execute(request):
    """Require every execution envelope to round-trip through strict JSON."""
    from lammpkeeper.execution import execute_request
    response = execute_request(request)
    # A strict JSON consumer can round-trip every response, including failures.
    assert json.loads(json.dumps(response, allow_nan=False)) == response
    assert response['artifacts'] == []
    return response


def _reject(call, contains):
    """Require invalid scientific input to raise a useful ValueError."""
    try:
        call()
    except ValueError as exc:
        assert contains.lower() in str(exc).lower(), str(exc)
    else:
        raise AssertionError('invalid input accepted: ' + contains)


def test_application_independent_ordered_population_statistics():
    """Check analytic population statistics, column order and detached results."""
    _util.require_numpy()
    import numpy as np
    from lammpkeeper.application import summarize_thermo
    data = {'step': np.array([0., 2., 4.]), 'temp': np.array([2., 4., 6.]),
            'pe': np.array([-6., -4., -2.]), 'unselected': np.array([np.nan])}
    original = {k: v.copy() for k, v in data.items()}
    result = summarize_thermo(data)
    assert result['sample_count'] == 3
    assert list(result['statistics']) == ['step', 'temp', 'pe']
    for key, low, high, mean in [('step', 0, 4, 2), ('temp', 2, 6, 4),
                                 ('pe', -6, -2, -4)]:
        stats = result['statistics'][key]
        assert stats == {'min': low, 'max': high, 'mean': mean,
                         'std': math.sqrt(8 / 3)}
    for key in data:
        np.testing.assert_array_equal(data[key], original[key])
    data['temp'][0] = 100
    assert result['statistics']['temp']['min'] == 2  # numeric snapshot, not a view


def test_application_rejects_empty_shape_length_nonfinite_and_overflow():
    """Reject malformed arrays and finite inputs whose statistics overflow."""
    _util.require_numpy()
    import numpy as np
    from lammpkeeper.application import summarize_thermo
    for data, message in [(None, 'thermo'), ({}, 'step'),
                          ({'step': []}, 'step'), ({'step': [[0, 1]]}, 'step'),
                          ({'step': [0, 1], 'temp': [2]}, 'temp'),
                          ({'step': [0, 1], 'temp': [2, np.nan]}, 'temp'),
                          ({'step': [0, 1], 'temp': [2, np.inf]}, 'temp'),
                          ({'step': [0, 1], 'temp': ['bad', 2]}, 'temp'),
                          ({'step': [0, 1], 'temp': [1e308, -1e308]}, 'statistics')]:
        _reject(lambda: summarize_thermo(data), message)


def test_application_rejects_unsafe_steps_including_omitted_raw_blocks():
    """Apply the parsed-Step guard even to raw rows excluded from the summary."""
    _util.require_numpy()
    import numpy as np
    from lammpkeeper.application import summarize_thermo
    for step in (0.5, np.nan, np.inf, 2**53, -(2**53), 2**53 + 1):
        _reject(lambda: summarize_thermo({'step': [step]}), 'step')
        raw = (['Step', 'Press'], np.array([[step, 2.]]), ['init'])
        _reject(lambda: summarize_thermo({'step': [0], 'raw_blocks': [raw]}), 'step')
    assert summarize_thermo({'step': [-(2**53) + 1]})['sample_count'] == 1


def test_singleton_direct_units_and_alias_collisions():
    """Check singleton statistics, explicit unit policy and ambiguous headers."""
    _util.require_numpy()
    import numpy as np
    from lammpkeeper.application import summarize_thermo
    for style in ('metal', 'real', None):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            result = summarize_thermo({'step': [5], 'temp': [1e308],
                                       'unit_system': style})
        assert result['sample_count'] == 1
        assert result['statistics']['temp'] == {'min': 1e308, 'max': 1e308,
                                                 'mean': 1e308, 'std': 0}
        assert bool(caught) == (style is None)
        assert result['units']['temp'] == ('K' if style else None)
    for style in ('lj', 'si', '', 1, ['metal']):
        _reject(lambda: summarize_thermo({'step': [0], 'unit_system': style}), 'unit')
    pairs = [('Step', 'Step'), ('Temp', 'Temperature'), ('Temp', 'c_temp_mobile'),
             ('PotEng', 'pe'), ('KinEng', 'ke'), ('TotEng', 'etotal'),
             ('Press', 'Pressure'), ('Volume', 'vol')]
    for first, second in pairs:
        headers = [first, second] if first == 'Step' else ['Step', first, second]
        _reject(lambda: summarize_thermo({'step': [0], 'headers': headers}), 'collision')
        raw = (headers, np.zeros((1, len(headers))), ['init'])
        _reject(lambda: summarize_thermo({'step': [0], 'raw_blocks': [raw]}), 'collision')


def test_file_alias_collisions_in_selected_and_omitted_tables_fail():
    """Prevent parser alias overwrites from hiding ambiguous source columns."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'aliases.log'
        for header, row in [('Step Step Temp', '0 1 300'),
                            ('Step Temp Temperature', '0 300 301'),
                            ('Step PotEng pe', '0 -2 -3')]:
            for prefix in ('', 'run 2\nStep Temp\n0 1\n1 2\n2 3\n'
                           'Loop time of 1\nminimize 0 0 1 1\n'):
                path.write_text(prefix + header + '\n' + row + '\n')
                response = _execute(_request(path))
                assert response['error']['code'] == 'invalid_input', response
                assert 'collision' in response['error']['message'], response


def test_warning_retention_and_diagnostic_bounds_on_failure():
    """Keep bounded parser diagnostics and known unit provenance on failure."""
    _util.require_numpy()
    from lammpkeeper.execution import MAX_DIAGNOSTIC, MAX_WARNINGS
    from lammps_post.parsers import parse_log
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'warn.log'
        _log(path)
        def warned(source):
            """Produce excessive diagnostics before returning an invalid snapshot."""
            result = parse_log(source)
            for _ in range(MAX_WARNINGS + 5):
                warnings.warn('sentinel ' + 'x' * (MAX_DIAGNOSTIC + 20), RuntimeWarning)
            result['temp'][0] = float('nan')
            return result
        with patch('lammps_post.parsers.parse_log', side_effect=warned):
            response = _execute(_request(path))
        assert response['status'] == 'failed'
        assert response['provenance']['unit_source'] == 'log.unit_system'
        assert len(response['warnings']) == MAX_WARNINGS
        assert 'sentinel' in response['warnings'][0]
        assert all(len(item) <= MAX_DIAGNOSTIC for item in response['warnings'])
        with patch('lammps_post.parsers.parse_log', side_effect=ValueError('x' * 10000)):
            response = _execute(_request(path))
        assert len(response['error']['message']) == MAX_DIAGNOSTIC


def test_execution_synthetic_units_and_provenance():
    """Verify native unit labels and explicitly stat-based runtime provenance."""
    _util.require_numpy()
    import numpy as np
    from lammpkeeper import VERSION
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'input.log'
        for style, energy, pressure in [('metal', 'eV', 'bar'),
                                         ('real', 'kcal/mol', 'atm'),
                                         (None, None, None)]:
            _log(path, style)
            # An odd integer beyond the JS exact-number range must survive intact.
            mtime_ns = 2**53 + 1
            os.utime(path, ns=(mtime_ns, mtime_ns))
            assert path.stat().st_mtime_ns == mtime_ns
            response = _execute(_request(path))
            assert response['status'] == 'succeeded', response
            assert response['error'] is None
            result = response['result']
            assert result['sample_count'] == 3 and result['unit_system'] == style
            assert result['units']['pe'] == energy and result['units']['press'] == pressure
            assert result['statistics']['temp']['mean'] == 4
            assert list(result['statistics']) == ['step', 'temp', 'pe', 'ke',
                                                  'etotal', 'press', 'vol']
            assert bool(response['warnings']) == (style is None)
            prov = response['provenance']
            assert prov['package_version'] == VERSION
            assert prov['numpy_version'] == np.__version__
            assert prov['python_version'] and prov['python_executable'] == sys.executable
            assert prov['unit_source'] == ('log.unit_system' if style else 'unresolved')
            identity = prov['input_fingerprint']
            assert identity['method'] == 'stat' and 'hash' not in identity
            assert identity['resolved_path'] == str(path.resolve())
            assert identity['size'] == path.stat().st_size
            assert identity['mtime_ns'] == str(mtime_ns)
            assert str(int(float(mtime_ns))) != identity['mtime_ns']
            assert identity['inode'] == str(path.stat().st_ino)
            assert identity['device'] == str(path.stat().st_dev)
            assert prov['parser_selection_policy']


def test_committed_feo_parser_application_execution_and_legacy_format_parity():
    """Preserve committed-reference arithmetic and the legacy formatted table."""
    _util.require_numpy()
    from lammpkeeper.application import summarize_thermo
    from lammps_post.parsers import parse_log
    from lammps_post.shell import LammpsPostShell
    from lammpkeeper.common.display import print_table
    fixture = Path(_util.FIXTURE).with_name('log.lammps')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        data = parse_log(fixture)
    summary = summarize_thermo(data)
    response = _execute(_request(fixture))
    assert response['status'] == 'succeeded', response
    assert response['result']['statistics'] == summary['statistics']
    # Independent legacy arithmetic and formatting, not a second app invocation.
    rows = []
    for key in ['step', 'temp', 'pe', 'ke', 'etotal', 'press', 'vol']:
        if key in data:
            v = data[key]
            expected = {'min': float(v.min()), 'max': float(v.max()),
                        'mean': float(v.mean()), 'std': float(v.std())}
            assert summary['statistics'][key] == expected
            rows.append([key] + [f'{expected[k]:.4g}' for k in ['min', 'max', 'mean', 'std']])
    before, after = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(before):
        print_table(['Column', 'Min', 'Max', 'Mean', 'Std'], rows, 'Thermo Summary')
    shell = LammpsPostShell()
    shell.state.log_data = data
    with contextlib.redirect_stdout(after):
        shell.do_show('thermo')
    assert after.getvalue() == before.getvalue()
    shell.state.log_data = {'step': [0], 'temp': [float('nan')]}
    _reject(lambda: shell.do_show('thermo'), 'temp')


def test_loaded_application_snapshot_is_not_a_fresh_file_read():
    """Distinguish stable loaded snapshots from fresh structured file execution."""
    _util.require_numpy()
    from lammps_post.parsers import parse_log
    from lammpkeeper.application import summarize_thermo
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'snapshot.log'
        _log(path)
        loaded = parse_log(path)
        before = summarize_thermo(loaded)
        path.write_text('units real\nStep Temp\n0 100\n1 200\n')
        assert summarize_thermo(loaded) == before
        fresh = _execute(_request(path))
        assert fresh['result']['statistics']['temp']['mean'] == 150
        assert fresh['result']['unit_system'] == 'real'


def test_selected_row_policy_optimizer_fallback_and_compatible_boundaries():
    """Expose parser selection and float64 precision limits without repairing them."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'selection.log'
        path.write_text('units real\nminimize 0 0 1 1\nStep Temp\n0 2\n1 4\n')
        response = _execute(_request(path))
        assert response['status'] == 'succeeded', response
        assert response['result']['sample_count'] == 2
        assert response['result']['statistics']['temp']['mean'] == 3
        assert any('non-MD' in w for w in response['warnings'])
        path.write_text('units metal\nrun 1\nStep Temp\n0 2\n1 4\n'
                        'Loop time of 1\nrun 1\nStep Temp\n1 4\n2 6\n'
                        'Loop time of 1\nrun 1\nStep Press\n3 100\n'
                        'Loop time of 1\n')
        response = _execute(_request(path))
        assert response['status'] == 'succeeded', response
        assert response['result']['sample_count'] == 3  # identical boundary coalesced
        assert response['result']['statistics']['temp']['mean'] == 4
        assert list(response['result']['statistics']) == ['step', 'temp']
        assert any('excluded 1' in w for w in response['warnings'])
        # Deliberately disclose (not repair) original-token float64 precision loss.
        path.write_text('units metal\nStep Temp\n1.0000000000000001 2\n')
        response = _execute(_request(path))
        assert response['status'] == 'succeeded', response
        assert 'not exact original-token' in response['provenance']['step_precision_policy']


def test_execution_rejects_bad_parser_inputs_and_omitted_unsafe_steps():
    """Map malformed and scientifically unsafe logs to invalid_input failures."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'bad.log'
        for text in ['', 'Step Temp\n', 'Step Temp\n0 nan\n',
                     'Step Temp\n0 1e308\n1 -1e308\n',
                     'Step Temp\n0 2\n1 broken\n', 'units lj\nStep Temp\n0 1\n',
                     'Step Temp\n0.5 2\n', 'Step Temp\n9007199254740993 2\n',
                     'run 2\nStep Temp\n0 1\n1 2\n2 3\nLoop time of 1\n'
                     'minimize 0 0 1 1\nStep Temp\n9007199254740993 1\n',
                     'run 2\nStep Temp\n0 1\n1 2\n2 3\nLoop time of 1\n'
                     'run 1\nStep Press\n0.25 1\n']:
            path.write_text(text)
            response = _execute(_request(path))
            assert response['status'] == 'failed' and response['result'] is None, response
            assert response['error']['code'] == 'invalid_input', response
            assert response['error']['message']


def test_invalid_legacy_show_is_visible_and_batch_fails():
    """Make invalid legacy summaries visibly fail without a successful batch exit."""
    _util.require_numpy()
    from lammps_post.shell import LammpsPostShell
    shell = LammpsPostShell()
    shell.state.log_data = {'step': [0], 'temp': [float('inf')]}
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert shell.onecmd('show thermo') is False
    assert not shell.last_command_ok and shell.command_failures == 1
    assert 'temp' in output.getvalue() and 'finite' in output.getvalue()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path, commands = root / 'bad.log', root / 'commands.txt'
        path.write_text('units metal\nStep Temp\n0 nan\n')
        commands.write_text('show thermo\nquit\n')
        env = dict(os.environ, HOME=str(root / 'home'), TMPDIR='/tmp/opencode',
                   PYTHONPATH=_util.REPO_ROOT)
        proc = subprocess.run([sys.executable, '-m', 'lammpkeeper', 'post',
                               '--log', str(path), '--batch', str(commands)],
                              cwd=str(root), env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)
        assert proc.returncode != 0, proc.stdout + proc.stderr
        assert 'temp' in proc.stdout and 'finite' in proc.stdout


def test_strict_request_schema_versions_and_types():
    """Reject incomplete controls, unknown fields and noninteger version tokens."""
    _util.require_numpy()
    valid = _request('unused')
    cases = [None, [], True]
    for key in valid:
        missing = copy.deepcopy(valid)
        del missing[key]
        cases.append(missing)
    cases += [dict(valid, extra=1), dict(valid, request_id=''),
              dict(valid, request_id=' '), dict(valid, request_id='x' * 129),
              dict(valid, request_id=2), dict(valid, protocol_version=True),
              dict(valid, protocol_version=1.0), dict(valid, operation_version=False),
              dict(valid, operation_version='1'), dict(valid, operation='other'),
              dict(valid, operation=[]), dict(valid, input={'log': 'x', 'extra': 1}),
              dict(valid, input={'log': ''}), dict(valid, input={'log': 2}),
              dict(valid, input={'log': 'x' * 4097}),
              dict(valid, input={'log': 'x\x00y'}),
              dict(valid, input=[]), dict(valid, parameters=[]),
              dict(valid, parameters={'unknown': 1})]
    for case in cases:
        response = _execute(case)
        assert response['status'] == 'failed' and response['result'] is None, response
        assert response['error']['code'] == 'invalid_request', response
    for key in ('protocol_version', 'operation_version'):
        response = _execute(dict(valid, **{key: 2}))
        assert response['error']['code'] == 'unsupported_version', response
    assert _execute(dict(valid, request_id=[]))['request_id'] is None


def test_execution_io_errors_and_internal_errors_are_distinct():
    """Distinguish unavailable source files from unexpected backend defects."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'absent.log'
        assert _execute(_request(path))['error']['code'] == 'io_error'
        _log(path)
        with patch('lammps_post.parsers.parse_log', side_effect=RuntimeError('bug sentinel')):
            response = _execute(_request(path))
        assert response['error']['code'] == 'internal_error'
        assert response['result'] is None


def test_stat_change_and_replacement_during_parse_cannot_publish_success():
    """Reject ordinary concurrent edits, replacements and removals without results."""
    _util.require_numpy()
    from lammps_post.parsers import parse_log
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'changing.log'
        for mode in ('append', 'replace', 'remove', 'parse_error'):
            _log(path)
            def changed(source):
                """Change source identity after parsing to exercise the final stat check."""
                result = parse_log(source)
                if mode == 'append':
                    with path.open('a') as stream:
                        stream.write('\n# changed\n')
                elif mode == 'replace':
                    replacement = path.with_suffix('.replacement')
                    replacement.write_text(path.read_text())
                    replacement.replace(path)
                else:
                    path.unlink()
                if mode == 'parse_error':
                    raise ValueError('parse error concurrent with removal')
                return result
            with patch('lammps_post.parsers.parse_log', side_effect=changed):
                response = _execute(_request(path))
            assert response['error']['code'] == 'input_changed', response
            assert response['result'] is None


def _cli(args, cwd, home, text=None):
    """Run the headless CLI and require one undecorated JSON line without history."""
    env = dict(os.environ, HOME=str(home), TMPDIR='/tmp/opencode',
               PYTHONPATH=_util.REPO_ROOT)
    # Do not mask history bugs with LKPR_NO_HISTORY.
    env.pop('LKPR_NO_HISTORY', None)
    options = {'input': text} if text is not None else {'stdin': subprocess.DEVNULL}
    proc = subprocess.run([sys.executable, '-m', 'lammpkeeper', 'exec'] + args,
                          cwd=str(cwd), env=env, text=True, capture_output=True,
                          timeout=30, **options)
    response = json.loads(proc.stdout, parse_constant=lambda v: (_ for _ in ()).throw(
        AssertionError('nonfinite output: ' + v)))
    assert '\x1b' not in proc.stdout and proc.stdout.count('\n') == 1, proc.stdout
    assert not any('history' in p.name.lower() for p in home.rglob('*'))
    return proc, response


def test_subprocess_paths_spaces_closed_stdin_no_shell_or_history():
    """Exercise file/stdin transport without shells, history or optional packages."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lkpr execution spaces ') as tmp:
        root = Path(tmp)
        home = root / 'isolated home'
        home.mkdir()
        path = root / 'input with spaces.log'
        _log(path)
        request = root / 'request with spaces.json'
        request.write_text(json.dumps(_request(path.name)))
        proc, response = _cli(['--request', str(request)], root, home)
        assert proc.returncode == 0 and response['status'] == 'succeeded', proc
        proc, stdin_response = _cli(['--request', '-'], root, home, request.read_text())
        assert proc.returncode == 0 and stdin_response == response
        # Backend never imports shell/readline, even in-process.
        code = ('import sys; from lammpkeeper.execution import execute_request; '
                f'execute_request({repr(_request(path))}); '
                'assert "lammps_post.shell" not in sys.modules; '
                'assert "lammpkeeper.shell" not in sys.modules; '
                'assert "readline" not in sys.modules')
        check = subprocess.run([sys.executable, '-c', code], cwd=_util.REPO_ROOT,
                               capture_output=True, text=True, timeout=30)
        assert check.returncode == 0, check.stderr
        code = ('import sys, importlib.abc\n'
                'class NoOptional(importlib.abc.MetaPathFinder):\n'
                ' def find_spec(self, fullname, path=None, target=None):\n'
                '  if fullname.split(".")[0] in '
                '("scipy","ase","matplotlib","pandas","MDAnalysis","rich"):\n'
                '   raise ImportError("optional dependency forbidden: " + fullname)\n'
                'sys.meta_path.insert(0, NoOptional())\n'
                'from lammpkeeper.execution import execute_request\n'
                f'assert execute_request({repr(_request(path))})["status"] == "succeeded"\n')
        check = subprocess.run([sys.executable, '-c', code], cwd=_util.REPO_ROOT,
                               capture_output=True, text=True, timeout=30)
        assert check.returncode == 0, check.stderr


def test_cli_strict_json_size_options_and_capabilities():
    """Check strict decoding, inclusive size bounds and discoverable capabilities."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        home = root / 'home'
        home.mkdir()
        valid = json.dumps(_request('unused'))
        for text in [valid[:-1] + ', "request_id":"duplicate"}',
                     valid.replace('"log": "unused"', '"log":"a", "log":"b"'),
                     valid.replace('"parameters": {}', '"parameters": {"x":NaN}'),
                     valid.replace('"parameters": {}', '"parameters": {"x":Infinity}'),
                     valid.replace('"parameters": {}', '"parameters": {"x":1e999}'),
                     '{', '', ' ' * (1024 * 1024 + 1)]:
            proc, response = _cli(['--request', '-'], root, home, text)
            assert proc.returncode != 0 and response['error']['code'] == 'invalid_request'
            assert response['request_id'] is None
        oversized = root / 'oversize.json'
        oversized.write_text(' ' * (1024 * 1024 + 1))
        proc, response = _cli(['--request', str(oversized)], root, home)
        assert proc.returncode != 0 and response['error']['code'] == 'invalid_request'
        # The inclusive bound accepts valid JSON padded to exactly 1 MiB.
        proc, response = _cli(['--request', '-'], root, home,
                              valid + ' ' * (1024 * 1024 - len(valid)))
        assert response['error']['code'] == 'io_error'  # nonexistent input, not size rejection
        for args in [[], ['--unknown'], ['--request'], ['--request', '--unknown'],
                     ['--request', 'x', '--output', 'y'],
                     ['--capabilities', '--request', '-'], ['--capabilities', '--unknown']]:
            proc, response = _cli(args, root, home)
            assert proc.returncode != 0 and response['error']['code'] == 'invalid_request'
        proc, response = _cli(['--capabilities'], root, home)
        assert proc.returncode == 0 and response['status'] == 'succeeded'
        caps = response['result']
        assert caps['protocol_versions'] == [1]
        assert caps['operations']['thermo.summary']['versions'] == [1]
        assert caps['bounds']['request_bytes'] == 1024 * 1024
        assert caps['units']['supported'] == ['metal', 'real']
        assert caps['units']['conversion'] is False
        assert caps['execution'] == {'mode': 'synchronous', 'cancellation': False,
                                     'artifacts': False}
        assert set(caps['request_schema']['required']) == set(_request('x'))
        caveats = ' '.join(caps['schema_caveats'])
        assert 'integer JSON tokens' in caveats and '1.0' in caveats and 'bool' in caveats
        assert 'input.log' in caveats and 'NUL' in caveats
