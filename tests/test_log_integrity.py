"""REV-IO-1: reject malformed numeric rows without losing thermo history.

Synthetic Step-headed tables define a deliberately narrow grammar contract,
not support for every LAMMPS output mode. Literal arrays independently check
preserved valid histories; shell and subprocess cases use the real parser.
"""
from pathlib import Path
import re
import shlex
import tempfile
import warnings

import _util


def _assert_diagnostic(message, path, lineno, row, headers):
    """Require source location, the offending row, and the active table layout."""
    assert str(path) in message and f':{lineno}:' in message, message
    assert 'thermo' in message.lower() and row in message, message
    named_headers = all(header in message for header in headers.split())
    expected_width = re.search(
        r'expected\s+' + str(len(headers.split())) + r'\b', message, re.IGNORECASE)
    assert named_headers or expected_width, message


def _reject(path, text, row, headers='Step Temp PotEng'):
    """Reject the complete history and verify the actual source line number."""
    from lammps_post.parsers import parse_log
    path.write_text(text)
    lineno = text.splitlines().index(row) + 1
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        try:
            parse_log(path)
        except ValueError as exc:
            _assert_diagnostic(str(exc), path, lineno, row, headers)
        else:
            raise AssertionError('malformed thermo row accepted: ' + row)


def test_rev_io_1_short_thermo_row_must_not_disappear():
    """A numeric short row must reject the history, not silently bridge its steps."""
    _util.require_numpy()
    from pathlib import Path
    import tempfile
    from lammps_post.parsers import parse_log

    text = ('run 20\nStep Temp PotEng\n0 300 -10\n10 301\n20 302 -12\n'
            'Loop time of 1 on 1 procs\n')
    with tempfile.TemporaryDirectory(prefix='lkpr-thermo-integrity-') as tmp:
        path = Path(tmp) / 'log.lammps'
        path.write_text(text)
        try:
            parse_log(path)
        except ValueError as exc:
            message = str(exc)
            assert str(path) in message and ':4:' in message, message
            assert 'thermo' in message.lower() and '10 301' in message, message
        else:
            raise AssertionError('malformed thermo row disappeared without a diagnostic')


def test_numeric_short_and_long_rows_report_source_and_active_headers():
    """Width mismatches identify the real path and line despite diagnostic gaps."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lkpr thermo integrity ') as tmp:
        path = Path(tmp) / 'with spaces.log'
        for row in ('10 301', '10 301 -11 99'):
            text = ('LAMMPS synthetic log\nrun 20\nStep Temp PotEng\n'
                    '0 300 -10\nWARNING: synthetic diagnostic\n\n' + row +
                    '\n20 302 -12\nLoop time of 1 on 1 procs\n')
            _reject(path, text, row)


def test_bad_numeric_cells_cannot_hide_behind_stage_or_end_keywords():
    """Numeric-leading corruption is validated before keyword classification."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'corrupt.log'
        for row in ('10 broken -11', '10 minimize -11', '10 Loop time',
                    '10 cg style', '10 equilibrate -11', '10 ERROR -11',
                    '10 301 oxidation'):
            _reject(path, 'run 20\nStep Temp PotEng\n0 300 -10\n' + row +
                    '\n20 302 -12\nLoop time of 1 on 1 procs\n', row)


def test_first_last_and_eof_rows_use_float_convertible_leading_tokens():
    """No existing good row or closing summary is needed to detect corruption."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'edge.log'
        for row in ('+1e1 bad -11', '-.5 301', 'nan 301 -11 extra',
                    'inf bad -11', '-inf 301'):
            for before in ('', '0 300 -10\n'):
                for after in ('', '\nLoop time of 1 on 1 procs\n'):
                    _reject(path, 'run 10\nStep Temp PotEng\n' + before + row + after,
                            row)


def test_minimization_corruption_rejects_otherwise_valid_md_history():
    """Optimizer tables cannot conceal corruption merely because MD excludes them."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'minimize.log'
        md = ('run 10\nStep Temp PotEng\n0 300 -10\n10 301 -11\n'
              'Loop time of 1 on 1 procs\n')
        for row in ('11 301', '11 301 -12 extra', '11 minimize -12'):
            _reject(path, md + 'minimize 0 1e-8 100 1000\nStep Temp PotEng\n'
                    '10 301 -11\n' + row, row)


def test_incompatible_table_corruption_is_not_ignored_by_block_selection():
    """All active layouts are checked, even when a longer MD table wins selection."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'incompatible.log'
        md = ('run 20\nStep Temp PotEng\n0 300 -10\n10 301 -11\n20 302 -12\n'
              'Loop time of 1 on 1 procs\n')
        for row in ('30', '30 2 extra', '30 broken'):
            _reject(path, md + 'run 10\nStep Press\n20 1\n' + row,
                    row, headers='Step Press')


def test_valid_numeric_formats_warnings_blanks_and_eof_are_preserved():
    """Signed/scientific and nonfinite floats retain their existing numeric meaning."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.parsers import parse_log
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'valid.log'
        path.write_text('units real\ntimestep 2\nrun 20\nStep Temp PotEng\n'
                        '+0.0 3e2 -1.0e1\n\nWARNING: minimize diagnostic only\n'
                        '+1e1 +3.01e2 NaN\n\t\n2.0E1 inf -inf')
        log = parse_log(path)
    np.testing.assert_array_equal(log['step'], [0, 10, 20])
    np.testing.assert_array_equal(log['temp'], [300, 301, np.inf])
    np.testing.assert_allclose(log['pe'], [-10, np.nan, -np.inf], equal_nan=True)
    np.testing.assert_array_equal(log['elapsed_md_steps'], [0, 10, 20])
    assert log['timeline_valid'] and log['block_kinds'] == ['md']
    assert log['stages'] == ['init', 'init', 'init']
    assert log['unit_system'] == 'real' and log['dt_fs'] == 2


def test_valid_compatible_blocks_keep_source_order_deduplication_and_metadata():
    """Repeated headers and summaries preserve source identity and common endpoints."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.parsers import parse_log
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'merge.log'
        path.write_text('units metal\ntimestep 0.002\nrun 10\nStep Temp PotEng\n'
                        '0 300 -10\n10 301 -11\nLoop time of 1 on 1 procs\n'
                        'run 10\nStep Temp PotEng\n10 301 -11\n20 302 -12\n'
                        'Step Temp PotEng\n20 302 -12\n30 303 -13\n'
                        'Loop time of 2 on 1 procs\n')
        log = parse_log(path)
    np.testing.assert_array_equal(log['step'], [0, 10, 20, 30])
    np.testing.assert_array_equal(log['pe'], [-10, -11, -12, -13])
    np.testing.assert_array_equal(log['block_ids'], [0, 0, 1, 2])
    np.testing.assert_array_equal(log['elapsed_md_steps'], [0, 10, 20, 30])
    assert [len(block[1]) for block in log['raw_blocks']] == [2, 2, 2]
    assert log['block_kinds'] == ['md', 'md', 'md'] and log['timeline_valid']
    assert log['stage_times'] == {'init': 3}
    assert log['unit_system'] == 'metal' and log['dt_fs'] == 2


def test_valid_reset_minimization_and_incompatible_blocks_keep_literal_history():
    """Reset counters and optimizer iterations remain distinct from elapsed MD steps."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.parsers import parse_log
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'reset.log'
        path.write_text('run 10\nStep Temp PotEng\n0 300 -10\n10 301 -11\n'
                        'Loop time of 1 on 1 procs\n'
                        'minimize 0 1e-8 100 1000\nStep Temp PotEng\n'
                        '10 301 -11\n12 0 -18\nLoop time of 2 on 1 procs\n'
                        'reset_timestep 0\nrun 10\nStep Temp PotEng\n'
                        '0 302 -18\n10 303 -17\nLoop time of 3 on 1 procs\n'
                        'run 5\nStep Press\n10 1\n15 2\nLoop time of 4 on 1 procs\n')
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always', RuntimeWarning)
            log = parse_log(path)
    np.testing.assert_array_equal(log['step'], [0, 10, 0, 10])
    np.testing.assert_array_equal(log['pe'], [-10, -11, -18, -17])
    np.testing.assert_array_equal(log['block_ids'], [0, 0, 2, 2])
    np.testing.assert_array_equal(log['elapsed_md_steps'], [0, 10, 10, 20])
    np.testing.assert_array_equal(log['raw_blocks'][1][1], [[10, 301, -11], [12, 0, -18]])
    np.testing.assert_array_equal(log['raw_blocks'][3][1], [[10, 1], [15, 2]])
    assert log['block_kinds'] == ['md', 'minimize', 'md', 'md']
    assert not log['timeline_valid'] and len(caught) == 2
    assert log['stages'] == ['init', 'init', 'md', 'md']


def test_numeric_lines_outside_tables_and_legacy_diagnostics_are_not_reclassified():
    """Validation starts at Step headers and leaves nonnumeric diagnostics unchanged."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.parsers import parse_log
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'diagnostics.log'
        path.write_text('10 broken\n20 1 2 3 4\n')
        assert parse_log(path) is None
        for terminator in ('Loop time of 1 on 1 procs', 'ERROR: synthetic failure',
                           'diagnostic has words'):
            path.write_text('10 broken\nStep Temp PotEng\n0 300 -10\n' +
                            terminator + '\n10 broken\n')
            log = parse_log(path)
            np.testing.assert_array_equal(log['step'], [0])
            np.testing.assert_array_equal(log['pe'], [-10])


def test_failed_shell_log_replacement_preserves_loaded_history_and_cache():
    """Real parser rejection must roll back source publication and derived cache."""
    _util.require_numpy()
    import numpy as np
    from test_audit_workflow import _load, _shell
    with tempfile.TemporaryDirectory(prefix='lkpr rollback ') as tmp:
        root = Path(tmp)
        good, bad = root / 'good.log', root / 'bad log.log'
        good.write_text('run 10\nStep Temp PotEng\n0 300 -10\n10 301 -11\n')
        bad.write_text('run 20\nStep Temp PotEng\n0 300 -10\n10 301\n20 302 -12\n')
        shell = _shell(root)
        _load(shell, 'log', good)
        old_log = shell.state.log_data
        sentinel = {'values': np.array([4., 9.])}
        shell.state.cache['integrity_sentinel'] = sentinel
        old_cache = shell.state.cache
        try:
            _load(shell, 'log', bad)
        except ValueError as exc:
            _assert_diagnostic(str(exc), bad, 4, '10 301', 'Step Temp PotEng')
        else:
            raise AssertionError('shell published malformed replacement log')
        assert shell.state.log_data is old_log
        assert shell.state.log_path == str(good)
        assert shell.state.cache is old_cache
        assert shell.state.cache['integrity_sentinel'] is sentinel
        np.testing.assert_array_equal(old_log['step'], [0, 10])
        np.testing.assert_array_equal(sentinel['values'], [4, 9])


def test_malformed_log_preload_and_batch_load_exit_nonzero_with_diagnostic():
    """Both real CLI routes surface corruption instead of reporting successful load."""
    _util.require_numpy()
    from test_audit_workflow import _cli
    with tempfile.TemporaryDirectory(prefix='lkpr cli integrity ') as tmp:
        root = Path(tmp)
        bad, batch = root / 'bad log.log', root / 'commands.txt'
        bad.write_text('run 20\nStep Temp PotEng\n0 300 -10\n10 301\n20 302 -12\n')
        batch.write_text('load log ' + shlex.quote(str(bad)) + '\nquit\n')
        for args in (['-m', 'lammps_post', '--log', str(bad), '--batch', str(batch)],
                     ['-m', 'lammpkeeper', 'post', '--batch', str(batch)]):
            proc = _cli(args)
            output = proc.stdout + proc.stderr
            assert proc.returncode != 0, output
            _assert_diagnostic(output, bad, 4, '10 301', 'Step Temp PotEng')
