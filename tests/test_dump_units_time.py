"""REV-IO-11 (AUDIT-20261104 A-1): dumps written with `dump_modify units/time yes`.

LAMMPS writes 'ITEM: UNITS' + the unit style once per opened file (repeated
in appended or concatenated output) and 'ITEM: TIME' + the elapsed time before every
'ITEM: TIMESTEP' when those dump_modify options are set. DumpReader rejected
both items as an invalid header, so such dumps could not be loaded at all.

The reader now accepts them on the streaming, indexed and lazy paths alike:
`reader.units` holds the unit style, frames carrying 'ITEM: TIME' get a
'time' key (other frames keep the exact old key set), and DumpIndex /
LazyFrames expose `times` (NaN where absent). A unit style that changes, or
first appears after the first frame, a duplicate item and a non-finite time
raise ValueError on every path. In a session the dump's unit style is explicit
evidence: it replaces guessed units, must match explicit input units, and
turns an explicit input timestep into an explicit dt.
"""

import contextlib
import io
import os
from pathlib import Path
import shlex
import tempfile
import warnings

from _util import require_numpy

ROWS = '1 1 0.1 0.2 0.3\n2 2 1.1 1.2 1.3\n'


def _frame(step, time=None, units=None, crlf=False):
    """Return one dump frame with optional UNITS/TIME items before its marker."""
    text = ''
    if units is not None:
        text += f'ITEM: UNITS\n{units}\n'
    if time is not None:
        text += f'ITEM: TIME\n{time}\n'
    text += (f'ITEM: TIMESTEP\n{step}\nITEM: NUMBER OF ATOMS\n2\n'
             'ITEM: BOX BOUNDS pp pp pp\n0 10\n0 10\n0 10\n'
             'ITEM: ATOMS id type x y z\n' + ROWS)
    return text.replace('\n', '\r\n') if crlf else text


def _write(text):
    """Write `text` to a fresh temporary dump file and return its path."""
    fd, path = tempfile.mkstemp(suffix='.dump')
    with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    return path


def _paths(path, **kwargs):
    """Return [(timestep, time or None, frame keys)] per access path."""
    from lammps_post.parsers import DumpReader, LazyFrames
    out = {}
    reader = DumpReader(path, **kwargs)
    out['stream'] = [(f['timestep'], f.get('time'), sorted(f)) for f in reader]
    reader = DumpReader(path, **kwargs)
    index = reader.index()
    out['indexed'] = [(f['timestep'], f.get('time'), sorted(f))
                      for f in (reader.read_frame(index, k) for k in range(len(index)))]
    for cache in (0, 10 ** 6):
        lazy = LazyFrames(DumpReader(path, **kwargs), cache_bytes=cache)
        out[f'lazy-{cache}'] = [(f['timestep'], f.get('time'), sorted(f)) for f in lazy]
    return out


def _all_paths_raise(path, needle):
    """Require ValueError containing `needle` from the stream and index paths."""
    from lammps_post.parsers import DumpReader
    for name, call in (('stream', lambda: list(DumpReader(path))),
                       ('index', lambda: DumpReader(path).index())):
        try:
            call()
        except ValueError as exc:
            assert needle in str(exc), (name, str(exc))
        else:
            raise AssertionError(f'{name}: expected ValueError containing {needle!r}')


def test_units_and_time_items_load_identically_on_every_path():
    """ITEM: UNITS and ITEM: TIME give the same units and times on all read paths."""
    require_numpy()
    import numpy as np
    from lammps_post.parsers import DumpReader, LazyFrames, parse_dump
    path = _write(_frame(0, 0, 'metal') + _frame(10, 0.01) + _frame(20, 0.02))
    try:
        assert DumpReader(path).units == 'metal'
        expected = [(0, 0.0), (10, 0.01), (20, 0.02)]
        for name, frames in _paths(path).items():
            assert [(s, t) for s, t, _ in frames] == expected, (name, frames)
            assert all('time' in keys for _, _, keys in frames), name
        reader = DumpReader(path)
        index = reader.index()
        assert np.array_equal(index.times, [0.0, 0.01, 0.02])
        # The atom block excludes the next frame's UNITS/TIME lines.
        assert index.block_end[0] == len(_frame(0, 0, 'metal')), index.block_end
        lazy = LazyFrames(DumpReader(path), stride=2)
        assert np.array_equal(lazy.times, [0.0, 0.02])
        frames, columns, _ = parse_dump(path)
        assert [f['time'] for f in frames] == [0.0, 0.01, 0.02]
        assert frames[1]['atoms'].shape == (2, len(columns))
    finally:
        os.unlink(path)


def test_frames_without_time_keep_the_old_key_set():
    """Without ITEM: TIME, frames carry no `time` key, as before."""
    require_numpy()
    import numpy as np
    from lammps_post.parsers import DumpReader
    old = ['atoms', 'box', 'elements', 'natoms', 'timestep']
    for text, units in ((_frame(0) + _frame(10), None),
                        (_frame(0, units='real') + _frame(10), 'real')):
        path = _write(text)
        try:
            assert DumpReader(path).units == units
            for name, frames in _paths(path).items():
                assert [keys for _, _, keys in frames] == [old, old], (name, frames)
            assert np.isnan(DumpReader(path).index().times).all()
        finally:
            os.unlink(path)


def test_appended_dump_repeats_its_units_item():
    """A repeated, matching ITEM: UNITS from an appended dump is accepted."""
    # Dump::openfile resets unit_count, so each reopen writes ITEM: UNITS again.
    require_numpy()
    path = _write(_frame(0, 0.0, 'real') + _frame(10, 5.0)
                  + _frame(20, 10.0, 'real') + _frame(30, 15.0))
    try:
        for name, frames in _paths(path).items():
            assert [(s, t) for s, t, _ in frames] == [(0, 0.0), (10, 5.0), (20, 10.0),
                                                      (30, 15.0)], name
    finally:
        os.unlink(path)


def test_crlf_dump_with_units_and_time():
    """CRLF line endings do not affect UNITS/TIME parsing."""
    require_numpy()
    from lammps_post.parsers import DumpReader
    path = _write(_frame(0, 0.5, 'metal', crlf=True) + _frame(10, 1.5, crlf=True))
    try:
        assert DumpReader(path).units == 'metal'
        for name, frames in _paths(path).items():
            assert [(s, t) for s, t, _ in frames] == [(0, 0.5), (10, 1.5)], name
    finally:
        os.unlink(path)


def test_box_model_frames_carry_time_with_cell():
    """Box-model frames keep `time` next to `cell` and `tilt`."""
    require_numpy()
    path = _write(_frame(0, 0.0, 'metal') + _frame(10, 0.01))
    try:
        for name, frames in _paths(path, box_model=True).items():
            assert frames[1][1] == 0.01, name
            assert {'cell', 'tilt', 'time'} <= set(frames[1][2]), name
    finally:
        os.unlink(path)


def test_inconsistent_items_raise_on_every_path():
    """Changed units, late units and bad time values raise the same error on all paths."""
    require_numpy()
    cases = [
        (_frame(0, 0.0, 'metal') + _frame(10, 0.01, 'real'), 'ITEM: UNITS changes before frame 1'),
        (_frame(0) + _frame(10, units='metal'), 'not before the first frame'),
        (_frame(0, 'nan'), "invalid ITEM: TIME value 'nan'"),
        (_frame(0, 'abc'), "invalid ITEM: TIME value 'abc'"),
        (_frame(0, 0.0) + 'ITEM: TIME\n1\n' + _frame(10, 2.0), 'duplicate ITEM: TIME item'),
        (_frame(0, units='metal real'), 'invalid ITEM: UNITS value'),
    ]
    for text, needle in cases:
        path = _write(text)
        try:
            from lammps_post.parsers import DumpReader
            try:
                DumpReader(path)
            except ValueError as exc:
                # Frame-0 defects fail the layout preflight in the constructor,
                # which every access path (stream, index, lazy, parse_dump) runs.
                assert needle in str(exc), str(exc)
                assert needle.startswith(('invalid', 'duplicate')), needle
                continue
            _all_paths_raise(path, needle)
        finally:
            os.unlink(path)


def test_blank_lines_between_items_agree_on_every_path():
    """Blank lines between preamble items parse the same on all paths."""
    require_numpy()
    second = _frame(10, 1.5, 'metal').replace('ITEM: TIME', '\nITEM: TIME').replace(
        '1.5\nITEM: TIMESTEP', '1.5\n\nITEM: TIMESTEP')
    path = _write(_frame(0, 0.5, 'metal') + second)
    try:
        for name, frames in _paths(path).items():
            assert [(s, t) for s, t, _ in frames] == [(0, 0.5), (10, 1.5)], name
    finally:
        os.unlink(path)
    # The skipped blank lines still feed the unit check on the index path.
    path = _write(_frame(0, 0.5, 'metal') + second.replace('metal', 'real'))
    try:
        _all_paths_raise(path, 'ITEM: UNITS changes before frame 1')
    finally:
        os.unlink(path)


def test_repeated_and_trailing_items_raise_on_every_path():
    """Duplicate items and items dangling at end of file raise on all paths."""
    require_numpy()
    cases = [
        (_frame(0, 0.0, 'metal') + 'ITEM: UNITS\nmetal\n' + _frame(10, 1.0, 'metal'),
         'duplicate ITEM: UNITS item before frame 1'),
        (_frame(0, 0.0, 'metal') + 'ITEM: UNITS\nmetal\n', 'end of file'),
        (_frame(0, 0.0) + 'ITEM: TIME\n1.0\n\n', 'end of file'),
    ]
    for text, needle in cases:
        path = _write(text)
        try:
            _all_paths_raise(path, needle)
        finally:
            os.unlink(path)


def test_units_item_without_timestep_is_still_invalid():
    """ITEM: UNITS alone does not make a header without ITEM: TIMESTEP valid."""
    require_numpy()
    from lammps_post.parsers import DumpReader
    path = _write('ITEM: UNITS\nmetal\nITEM: ATOMS id type x y z\n' + ROWS)
    try:
        try:
            DumpReader(path)
        except ValueError as exc:
            assert 'invalid dump header: ITEM: ATOMS' in str(exc), str(exc)
        else:
            raise AssertionError('expected ValueError')
    finally:
        os.unlink(path)


# --- session integration ---------------------------------------------------

def _shell():
    """Return a noninteractive shell."""
    from lammps_post.shell import LammpsPostShell
    shell = LammpsPostShell()
    shell.noninteractive = True
    return shell


def _load(shell, kind, path):
    """Load through the command parser; return captured stdout."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), warnings.catch_warnings():
        warnings.simplefilter('ignore')
        shell.do_load(f'{kind} {shlex.quote(str(path))}')
    return out.getvalue()


def _input(path, units=None, timestep=None):
    """Write an input declaring only the given units/timestep."""
    lines = ['atom_style atomic', 'boundary p p p']
    if units:
        lines.insert(0, f'units {units}')
    if timestep:
        lines.append(f'timestep {timestep}')
    Path(path).write_text('\n'.join(lines) + '\n')


def _write_input(tmp, units=None, timestep=None, name='in.run'):
    """Write an input under `tmp` and return its path."""
    path = os.path.join(tmp, name)
    _input(path, units, timestep)
    return path


def test_session_takes_dump_units_as_explicit_evidence():
    """Dump ITEM: UNITS becomes explicit session units, converts the input timestep and clears on unload."""
    require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        dump = os.path.join(tmp, 'run.dump')
        Path(dump).write_text(_frame(0, 0.0, 'real') + _frame(10, 2.5))
        shell = _shell()
        text = _load(shell, 'dump', dump)
        md = shell.state.run_metadata
        assert md.units.value == 'real' and md.units.status == 'explicit', md.units
        assert md.units.source == dump, md.units
        assert shell.state.ff_info['unit_system'] == 'real'
        assert 'real units [explicit]' in text, text
        _load(shell, 'input', _write_input(tmp, timestep='0.5'))
        md = shell.state.run_metadata
        assert md.dt_fs.value == 0.5 and md.dt_fs.status == 'explicit', md.dt_fs
        shell.do_unload('dump')
        assert shell.state._dump_units is None
        assert shell.state.run_metadata.units.status != 'explicit'


def test_dump_units_conflicting_with_input_units_roll_back():
    """Dump units that contradict input units fail the load and roll it back, in either order."""
    require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        dump = os.path.join(tmp, 'run.dump')
        Path(dump).write_text(_frame(0, units='real') + _frame(10))
        # Input first, then the dump.
        shell = _shell()
        _load(shell, 'input', _write_input(tmp, units='metal', timestep='0.001'))
        try:
            _load(shell, 'dump', dump)
        except ValueError as exc:
            assert 'Conflicting explicit units' in str(exc) and 'ITEM: UNITS' in str(exc), exc
        else:
            raise AssertionError('expected ValueError')
        assert shell.state.dump_path is None and shell.state._dump_units is None
        assert shell.state.run_metadata.units.value == 'metal'
        # Dump first, then the input.
        shell = _shell()
        _load(shell, 'dump', dump)
        try:
            _load(shell, 'input', _write_input(tmp, units='metal', name='in.other'))
        except ValueError as exc:
            assert 'Conflicting explicit units' in str(exc), exc
        else:
            raise AssertionError('expected ValueError')
        assert shell.state.input_path is None
        assert shell.state.run_metadata.units.value == 'real'


def test_guessed_dt_is_dropped_when_dump_units_contradict_the_guess():
    """A heuristic dt guess is dropped when dump units say otherwise."""
    require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        for units in ('metal', 'real', 'lj'):
            dump = os.path.join(tmp, f'{units}.dump')
            Path(dump).write_text(_frame(0, units=units) + _frame(10))
            shell = _shell()
            _load(shell, 'dump', dump)
            state = shell.state
            guess = state._dump_ff_info['unit_system']
            md = state.run_metadata
            assert md.units.value == units and md.units.status == 'explicit'
            if guess == units:
                assert md.dt_fs.status == 'guessed', (units, md.dt_fs)
            else:
                assert md.dt_fs.value is None and md.dt_fs.status == 'unresolved', md.dt_fs
                assert 'heuristic guessed' in md.dt_fs.note, md.dt_fs.note
                assert state.ff_info['dt_fs'] is None


def test_dump_units_without_fs_conversion_leave_dt_unresolved():
    """Units with no fs conversion (lj) leave dt unresolved instead of guessing."""
    require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        dump = os.path.join(tmp, 'run.dump')
        Path(dump).write_text(_frame(0, units='lj') + _frame(10))
        shell = _shell()
        _load(shell, 'dump', dump)
        _load(shell, 'input', _write_input(tmp, timestep='0.005'))
        md = shell.state.run_metadata
        assert md.units.value == 'lj' and md.units.status == 'explicit'
        assert md.dt_fs.value is None and md.dt_fs.status == 'unresolved', md.dt_fs
        assert 'no supported femtosecond conversion' in md.dt_fs.note, md.dt_fs.note


def test_blank_line_between_item_and_value_raises_on_both_paths():
    """A blank line after ITEM: UNITS/TIME is rejected by the index path too.

    The streaming path reads the blank line as the value. The index path used
    to stop its walk-back there, leaving the lines inside the previous frame's
    atom block, so the error surfaced only when that frame was read.
    """
    require_numpy()
    for item, value in (('UNITS', 'real'), ('TIME', '1.5')):
        bad = f'ITEM: {item}\n\n{value}\n'
        text = _frame(0, units='real' if item == 'UNITS' else None) + bad + _frame(100)
        path = _write(text)
        try:
            _all_paths_raise(path, f'ITEM: {item}')
        finally:
            os.unlink(path)
