"""REV-IO-6: dump BOX BOUNDS and input-script boundary words are validated.

Expectations are written literally from the LAMMPS rules (dump: one two-letter
token per axis; 'p' only as 'pp'; input: one or two letters per axis, 'p' only
paired with 'p'), not derived from the production regex. Invalid metadata must
raise a visible ValueError instead of publishing wrong periodicity.
"""
import os
import tempfile

import _util  # noqa: F401  (path bootstrap)
from _util import have_numpy, skip

VALID = {
    'pp pp pp': (True, True, True),
    'pp pp ff': (True, True, False),
    'pp pp fs': (True, True, False),
    'ff ss mm': (False, False, False),
    'fm sm ms': (False, False, False),
    'ff pp ss': (False, True, False),
}
INVALID = ['p p f', 'pf pp ff', 'sp pp ff', 'pm pp pp', 'pp pp', 'pp pp ff ff',
           'pp pp fx', 'pp pp ppp', 'pp pp f']


def _dump(bounds, steps=1):
    """Write a synthetic one-atom dump with literal header flags; return its path."""
    text = ''
    for s in range(steps):
        text += (f'ITEM: TIMESTEP\n{s}\nITEM: NUMBER OF ATOMS\n1\n'
                 f'ITEM: BOX BOUNDS {bounds}\n0 10\n0 10\n0 20\n'
                 'ITEM: ATOMS id type x y z\n1 1 1.0 1.0 1.0\n')
    fd, path = tempfile.mkstemp(suffix='.dump')
    with os.fdopen(fd, 'w') as f:
        f.write(text)
    return path


def _raises(fn, *needles):
    """Assert fn raises ValueError mentioning every needle; return the message."""
    try:
        fn()
    except ValueError as exc:
        msg = str(exc)
        for n in needles:
            assert n in msg, f'{n!r} missing from {msg!r}'
        return msg
    raise AssertionError('ValueError not raised')


def test_parse_boundary_flags_rejects_invalid_tokens():
    from lammps_post.parsers import parse_boundary_flags
    for bad in INVALID:
        _raises(lambda b=bad: parse_boundary_flags(f'ITEM: BOX BOUNDS {b}'))
    assert parse_boundary_flags('ITEM: BOX BOUNDS') is None
    assert parse_boundary_flags('ITEM: BOX BOUNDS xy xz yz') is None
    assert parse_boundary_flags('ITEM: BOX BOUNDS xy xz yz pp pp ff') == ('pp', 'pp', 'ff')


def test_dump_reader_rejects_invalid_flags_all_access_modes():
    if not have_numpy():
        skip('numpy unavailable')
    from lammps_post.parsers import DumpReader
    for box_model in (False, True):
        for bad in INVALID:
            path = _dump(bad)
            try:
                # The first frame is validated when the reader is constructed.
                _raises(lambda: DumpReader(path, box_model=box_model), path)
            finally:
                os.unlink(path)


def test_dump_reader_rejects_invalid_flags_in_later_frame():
    if not have_numpy():
        skip('numpy unavailable')
    from lammps_post.parsers import DumpReader
    good = _dump('pp pp ff')
    try:
        with open(good) as f:
            first = f.read()
    finally:
        os.unlink(good)
    mixed = first + first.replace('pp pp ff', 'p p f').replace('TIMESTEP\n0', 'TIMESTEP\n1')
    fd, path = tempfile.mkstemp(suffix='.dump')
    with os.fdopen(fd, 'w') as f:
        f.write(mixed)
    try:
        for box_model in (False, True):
            reader = DumpReader(path, box_model=box_model)
            _raises(lambda: list(reader), path, "'p'")
            _raises(lambda: reader.index(), path, "'p'")
    finally:
        os.unlink(path)


def test_valid_flags_publish_exact_pbc_streaming_and_indexed():
    if not have_numpy():
        skip('numpy unavailable')
    from lammps_post.parsers import DumpReader, pbc_from_boundary
    for flags, expected in VALID.items():
        path = _dump(flags, steps=2)
        try:
            for box_model in (False, True):
                reader = DumpReader(path, box_model=box_model)
                assert reader.boundary == tuple(flags.split())
                assert pbc_from_boundary(reader.boundary) == expected
                frames = list(reader)
                idx = reader.index()
                frames += [reader.read_frame(idx, k) for k in range(2)]
                assert len(frames) == 4
                if box_model:
                    for fr in frames:
                        assert tuple(fr['cell'].pbc) == expected, (flags, fr['cell'].pbc)
        finally:
            os.unlink(path)


def test_dump_without_flags_keeps_working():
    if not have_numpy():
        skip('numpy unavailable')
    from lammps_post.parsers import DumpReader
    path = _dump('')
    try:
        for box_model in (False, True):
            reader = DumpReader(path, box_model=box_model)
            assert reader.boundary is None
            assert len(list(reader)) == 1
    finally:
        os.unlink(path)


def _input(line):
    """Write a minimal input script with one boundary line; return its path."""
    fd, path = tempfile.mkstemp(suffix='.in')
    with os.fdopen(fd, 'w') as f:
        f.write(f'units metal\n{line}\n')
    return path


def test_input_boundary_valid_words_unchanged():
    from lammps_post.parsers import parse_input
    for line, words in [('boundary p p f', ['p', 'p', 'f']),
                        ('boundary pp pp fs', ['pp', 'pp', 'fs']),
                        ('boundary p p m', ['p', 'p', 'm'])]:
        path = _input(line)
        try:
            assert parse_input(path)['boundary'] == words
        finally:
            os.unlink(path)


def test_input_boundary_invalid_words_rejected_with_path():
    from lammps_post.parsers import parse_input
    for line in ['boundary pp potato f', 'boundary pf p p', 'boundary p p',
                 'boundary p p f f', 'boundary p p x', 'boundary p p sp']:
        path = _input(line)
        try:
            _raises(lambda: parse_input(path), path, 'boundary')
        finally:
            os.unlink(path)
