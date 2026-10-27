"""AUDIT-20261027 synthetic parser integrity regressions (NumPy only)."""
from pathlib import Path
import tempfile
import threading
import warnings

import _util  # noqa: F401
import numpy as np
from lammps_post import parsers as p


def _frame(step=0, rows=('1 1 1 2 3',), columns='id type x y z',
           flags='pp pp ff', bounds=('0 10', '0 10', '0 10')):
    return '\n'.join(['ITEM: TIMESTEP', str(step), 'ITEM: NUMBER OF ATOMS',
                      str(len(rows)), 'ITEM: BOX BOUNDS ' + flags, *bounds,
                      'ITEM: ATOMS ' + columns, *rows]) + '\n'


def _error(fn, text=None, cls=ValueError):
    try:
        fn()
    except cls as exc:
        if text:
            assert text.lower() in str(exc).lower(), str(exc)
    else:
        raise AssertionError('expected ' + cls.__name__)


def _paths(path, native, mode, **kwargs):
    reader = p.DumpReader(path, **kwargs)
    if not native:
        reader._native = None
    if mode == 'stream':
        return list(reader)
    if mode == 'index':
        index = reader.index()
        return [reader.read_frame(index, k) for k in range(len(index))]
    return list(p.LazyFrames(reader, cache_bytes=10**6 if mode == 'cached' else 0))


def test_audit_dump_geometry_every_backend_and_access():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'trajectory.dump'
        for text, needle in (
            (_frame(flags='xy xz yz pp pp ff', bounds=('0 12 2', '0 10 0', '0 10 0')), 'triclinic'),
            (_frame(flags='abc origin pp pp ff', bounds=('10 0 0 0', '0 10 0 0', '0 0 10 0')), 'triclinic'),
            (_frame() + _frame(1, flags='pp pp pp'), 'boundary'),
            (_frame().replace('ITEM: NUMBER OF ATOMS', 'INVALID HEADER'), 'header'),
            (_frame().replace('0 10\n', '0 10 2\n', 1), 'triclinic'),
        ):
            path.write_text(text)
            for native in (False, True):
                for mode in ('stream', 'index', 'cached', 'uncached'):
                    _error(lambda: _paths(path, native, mode), needle)


def test_audit_dump_labels_precision_limits_and_counts():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'trajectory.dump'
        label = 'CustomSpeciesLabelLong'
        path.write_text(_frame(rows=('1 ' + label + ' 1 2 3',), columns='id element x y z'))
        for native in (False, True):
            for mode in ('stream', 'index', 'cached', 'uncached'):
                assert _paths(path, native, mode)[0]['elements'].tolist() == [label]
        path.write_text(_frame(rows=('16777216 1 1 2 3', '16777217 1 4 5 6')))
        for native in (False, True):
            for mode in ('stream', 'index', 'cached', 'uncached'):
                _error(lambda: _paths(path, native, mode, dtype=np.float32), 'precision')
        _error(lambda: p.DumpReader(path, max_frames=-1), 'max_frames')
        _error(lambda: p.LazyFrames(p.DumpReader(path), max_frames=-1), 'max_frames')
        path.write_text(_frame().replace('ITEM: NUMBER OF ATOMS\n1', 'ITEM: NUMBER OF ATOMS\n-1'))
        _error(lambda: list(p.DumpReader(path)), 'atom')
        path.write_text(_frame() + '2 1 4 5 6\n')
        for mode in ('stream', 'index', 'cached', 'uncached'):
            _error(lambda: _paths(path, False, mode), 'atom')


def test_audit_log_warning_reset_and_minimization():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'log.lammps'
        block = 'Step Temp PotEng\n0 300 -10\nWARNING: neighbor warning\n10 301 -11\nLoop time of 1 on 1 procs\n'
        path.write_text(block)
        assert p.parse_log(path)['step'].tolist() == [0, 10]
        path.write_text(block + 'reset_timestep 0\n' + block.replace('-10', '-20').replace('-11', '-21'))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            log = p.parse_log(path)
        assert log['pe'].tolist() == [-10, -11, -20, -21]
        assert log['timeline_valid'] is False and caught
        assert [len(b[1]) for b in log['raw_blocks']] == [2, 2]
        path.write_text('run 10\nStep Temp PotEng\n0 300 -10\n10 301 -11\nLoop time of 1 on 1 procs\n'
                        'minimize 0 1e-8 100 1000\nStep Temp PotEng\n10 301 -11\n11 301 -15\n12 301 -18\nLoop time of 1 on 1 procs\n'
                        'run 10\nStep Temp PotEng\n12 302 -18\n22 303 -17\nLoop time of 1 on 1 procs\n')
        log = p.parse_log(path)
        assert log['step'].tolist() == [0, 10, 12, 22]
        assert log['elapsed_md_steps'].tolist() == [0, 10, 10, 20]
        assert log['block_kinds'] == ['md', 'minimize', 'md']
        assert log['stages'][-1] != 'minimize'
        assert log['timeline_valid'] is False
        path.write_text('Step Press Volume\n0 1 1000\n10 2 1000\nLoop time of 1 on 1 procs\n')
        assert p.parse_log(path)['press'].tolist() == [1, 2]
        path.write_text('units si\nStep Temp\n0 300\n')
        _error(lambda: p.parse_log(path), 'units')


def test_audit_data_sections_styles_and_corruption():
    base = ('Test\n\n1 atoms\n1 atom types\n\n0 10 xlo xhi\n0 10 ylo yhi\n0 10 zlo zhi\n\n'
            'Masses\n\n1 12.0 # X\n\nPair Coeffs # lj/cut\n\n1 0.01 2.0\n\n')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'system.data'
        for header, row in [('Atoms', '1 1 2 3 4 0 0 0'), ('Atoms # atomic', '1 1 2 3 4'),
                            ('Atoms # charge', '1 1 -.4 2 3 4'), ('Atoms # full', '1 7 1 -.4 2 3 4'),
                            ('Atoms # molecular', '1 7 1 2 3 4')]:
            path.write_text(base + header + '\n\n' + row + '\n\nVelocities\n\n1 0 0 0\n')
            atoms, box, masses = p.parse_data_file(path)
            assert masses == {1: 12.0}
            assert atoms.tolist() == [[1, 1, 2, 3, 4]]
            assert box.shape == (3, 2)
        for tail, needle in [('Atoms # atomic\n1 1 bad 3 4\n', 'atom'),
                             ('Atoms # atomic\n', 'count'),
                             ('Atoms # mystery\n1 1 2 3 4\n', 'style'),
                             ('2 0 0 xy xz yz\nAtoms # atomic\n1 1 2 3 4\n', 'triclinic')]:
            path.write_text(base + tail)
            _error(lambda: p.parse_data_file(path), needle)


def test_audit_input_lexing_includes_variables_mapping_units():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'nested').mkdir()
        (root / 'nested' / 'second.inc').write_text('timestep ${dt}\n')
        (root / 'nested' / 'first.inc').write_text("include 'second.inc' # nested\n")
        path = root / 'run.in'
        path.write_text('units metal\nvariable dt equal 0.001\nvariable dt equal 0.002*2\n'
                        'include "nested/first.inc" # comment\nvariable A string X\nvariable B string Y\n'
                        'pair_style hybrid pace lj/cut 2.5\npair_coeff * * pace "potential #1.yace" ${A} ${B} Z\n'
                        'pair_coeff * * pace other.yace ${A} ${B} NULL\n')
        config = p.parse_input(path)
        assert config['dt_fs'] == 4
        assert config['element_map'] == {1: 'X', 2: 'Y'}
        assert config['pair_coeff']['potential_file'] == 'other.yace'
        for text, cls, needle in [('include absent.inc\n', OSError, None),
                                  ('include run.in\n', ValueError, 'include'),
                                  ('print "bad quote\n', ValueError, 'quote'),
                                  ('units si\ntimestep 1e-15\n', ValueError, 'units'),
                                  ('variable dt equal sqrt(2)\ntimestep ${dt}\n', ValueError, 'resolve'),
                                  ('variable dt equal 0.001\nvariable dt delete\ntimestep ${dt}\n', ValueError, 'resolve'),
                                  ("variable dt equal __import__('os')\ntimestep ${dt}\n", ValueError, 'resolve')]:
            path.write_text(text)
            _error(lambda: p.parse_input(path), needle, cls)
        path.write_text('units real\npair_style lj/cut 2.5\npair_coeff * * 0.1 2.0\ntimestep 0.25\n')
        assert p.parse_input(path)['dt_fs'] == 0.25
        path.write_text('units metal\nvariable base equal 0.001\nvariable dt equal v_base*4\n'
                        'timestep ${dt}\nvariable species string "A#label"\nprint "quoted # remains"\n')
        assert p.parse_input(path)['dt_fs'] == 4
        path.write_text('units metal\nvariable dt equal 0.001\nvariable dt equal ${dt}*2\ntimestep ${dt}\n')
        assert p.parse_input(path)['dt_fs'] == 2
        path.write_text('units metal\nvariable base equal 0.001\nvariable dt equal v_base*4\n'
                        'variable base equal 0.002\ntimestep ${dt}\n')
        config = p.parse_input(path)
        assert config['dt_fs'] == 8 and config['z_variables']['dt'] == 0.008


def test_audit_explicit_dump_labels_override_heuristic():
    frame = {'atoms': np.array([[1, 1, 0], [2, 2, 0]], float), 'elements': np.array(['A', 'B'])}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        info = p.detect_forcefield(['id', 'type', 'q'], {'id': 0, 'type': 1, 'q': 2}, [frame])
    assert info['atom_types'] == {1: 'A', 2: 'B'}
    assert info['has_element'] and caught


def test_audit_spin_aliases_require_matching_canonical_slots():
    from lammpkeeper.common.mapping import FORCE_FIELDS, type_to_label

    canonical = FORCE_FIELDS['ace']
    type_ids = sorted(canonical)
    elements = [canonical[tid][0] for tid in type_ids]
    for ids, labels, expected in (
        (type_ids, elements, type_to_label('ace')),
        (type_ids, elements[1::-1] + elements[2:], dict(zip(type_ids, elements[1::-1] + elements[2:]))),
        ([tid + 10 for tid in type_ids], elements, {tid + 10: canonical[tid][0] for tid in type_ids}),
    ):
        frame = {'atoms': np.array([[i + 1, tid] for i, tid in enumerate(ids)], float),
                 'elements': np.array(labels)}
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            info = p.detect_forcefield(['id', 'type'], {'id': 0, 'type': 1}, [frame])
        assert info['atom_types'] == expected, info


def test_audit_lazy_frames_inherit_reader_limits_and_allow_explicit_overrides():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'trajectory.dump'
        path.write_text(''.join(_frame(k) for k in range(7)))
        for native in (False, True):
            reader = p.DumpReader(path, stride=2, max_frames=2)
            if not native:
                reader._native = None
            for cache_bytes in (0, 10**6):
                for overrides, expected in (
                    ({}, [0, 2]),
                    ({'stride': 1}, [0, 1]),
                    ({'max_frames': None}, [0, 2, 4, 6]),
                    ({'max_frames': 0}, [0, 2, 4, 6]),
                    ({'stride': 3, 'max_frames': 1}, [0]),
                    ({'stride': 1, 'max_frames': None}, list(range(7))),
                ):
                    frames = p.LazyFrames(reader, cache_bytes=cache_bytes, **overrides)
                    assert frames.timesteps.tolist() == expected
                    assert [frame['timestep'] for frame in frames] == expected
                    assert frames[::-1].timesteps.tolist() == expected[::-1]
                    assert frames[-1]['timestep'] == expected[-1]
            assert p.LazyFrames(reader).timesteps.tolist() == [frame['timestep'] for frame in reader]
        for argument, values in (('stride', (0, -1, 1.5, None, '2')),
                                 ('max_frames', (-1, 1.5, float('nan'), '2'))):
            for value in values:
                _error(lambda: p.DumpReader(path, **{argument: value}), argument)
                _error(lambda: p.LazyFrames(p.DumpReader(path), **{argument: value}), argument)


def test_audit_abandoned_shared_iterator_and_changed_source():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'trajectory.dump'
        path.write_text(''.join(_frame(k) for k in range(8)))
        frames = p.LazyFrames(p.DumpReader(path), cache_bytes=0)
        seen = []
        with frames.shared_pass(depth=1):
            unused = iter(frames)
            unused.close()
            thread = threading.Thread(target=lambda: seen.extend(f['timestep'] for f in frames), daemon=True)
            thread.start()
            thread.join(timeout=2)
            assert not thread.is_alive(), 'unused iterator stalled shared producer'
        assert seen == list(range(8))
        frames = p.LazyFrames(p.DumpReader(path))
        assert frames[0]['atoms'][0, 2] == 1
        path.write_text(path.read_text().replace('1 1 1 2 3', '1 1 9 2 3'))
        _error(lambda: frames[0], 'changed')
        _error(lambda: frames.reader.read_frame(frames._store.index, 0), 'changed')


if __name__ == '__main__':
    import traceback
    failed = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_'):
            try:
                fn()
                print('PASS', name)
            except Exception:
                failed += 1
                print('FAIL', name)
                traceback.print_exc()
    raise SystemExit(bool(failed))
