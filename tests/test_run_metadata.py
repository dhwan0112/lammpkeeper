"""GEN-2a: explicit run metadata model, pair-style classifier, additive parser key.

Covers ADR-0005 implementation steps 1-2. Expectations are written literally
from LAMMPS rules (metal time is ps, real time is fs; pair-style names from the
LAMMPS manual), not derived from the production tables. Legacy `parse_input`
values were captured from unmodified main (7192e64) before this change and are
pinned here so the additive `metadata` key cannot alter them.
"""
import math
import os
import tempfile
import warnings

import _util  # noqa: F401  (path bootstrap)

from lammpkeeper.io.metadata import MetadataField, RunMetadata, derive_dt_fs

from lammps_post.parsers import classify_pair_style, parse_input

INPUTS = {
    'ace': 'units metal\natom_style atomic\nboundary p p p\ntimestep 0.00025\npair_style pace\npair_coeff * * ACE_Fe-O.yace Fe Mn O\nread_data foo.data\n',
    'reaxff': 'units real\natom_style charge\nboundary p p f\npair_style reaxff NULL\npair_coeff * * ffield.reax Fe O\ntimestep 0.25\n',
    'hdnnp': 'units metal\natom_style atomic\npair_style hdnnp 6.0 dir nnp\npair_coeff * * Fe O\ntimestep 0.0005\n',
    'eam': 'units metal\natom_style atomic\npair_style eam/alloy\npair_coeff * * Fe_mm.eam.alloy Fe\ntimestep 0.002\n',
    'hybrid': 'units metal\nvariable dt equal 0.001\ntimestep ${dt}\npair_style hybrid/overlay pace zbl 1.0 2.0\npair_coeff * * pace ACE_Fe-O.yace Fe O\npair_coeff 1 1 zbl 26 26\n',
    'bare': 'units real\natom_style full\n',
    'notimestep': 'units metal\npair_style pace\npair_coeff * * x.yace Fe O\n',
    'nounits': 'timestep 0.5\npair_style pace\npair_coeff * * x.yace Fe O\n',
    'filename_trap': 'units metal\npair_style eam/alloy\npair_coeff * * pace_like_reaxff_ace.eam.alloy Fe\ntimestep 0.001\n',
}

# Values returned by main 7192e64 `parse_input` for INPUTS (legacy schema).
LEGACY = {'ace': {'atom_style': 'atomic',
         'boundary': ['p', 'p', 'p'],
         'dt_fs': 0.25,
         'element_map': {1: 'Fe', 2: 'Mn', 3: 'O'},
         'forcefield': 'ace',
         'pair_coeff': {'elements': ['Fe', 'Mn', 'O'], 'potential_file': 'ACE_Fe-O.yace'},
         'pair_style': 'pace',
         'read_data': 'foo.data',
         'timestep': 0.00025,
         'units': 'metal'},
 'bare': {'atom_style': 'full',
          'boundary': [],
          'dt_fs': None,
          'element_map': {},
          'forcefield': 'unknown',
          'pair_coeff': None,
          'pair_style': None,
          'read_data': None,
          'timestep': None,
          'units': 'real'},
 'eam': {'atom_style': 'atomic',
         'boundary': [],
         'dt_fs': 2.0,
         'element_map': {1: 'Fe'},
         'forcefield': 'unknown',
         'pair_coeff': {'elements': ['Fe'], 'potential_file': 'Fe_mm.eam.alloy'},
         'pair_style': 'eam/alloy',
         'read_data': None,
         'timestep': 0.002,
         'units': 'metal'},
 'filename_trap': {'atom_style': None,
                   'boundary': [],
                   'dt_fs': 1.0,
                   'element_map': {1: 'Fe'},
                   'forcefield': 'unknown',
                   'pair_coeff': {'elements': ['Fe'],
                                  'potential_file': 'pace_like_reaxff_ace.eam.alloy'},
                   'pair_style': 'eam/alloy',
                   'read_data': None,
                   'timestep': 0.001,
                   'units': 'metal'},
 'hdnnp': {'atom_style': 'atomic',
           'boundary': [],
           'dt_fs': 0.5,
           'element_map': {1: 'Fe', 2: 'O'},
           'forcefield': 'hdnnp',
           'pair_coeff': {'elements': ['Fe', 'O'], 'potential_file': None},
           'pair_style': 'hdnnp 6.0 dir nnp',
           'read_data': None,
           'timestep': 0.0005,
           'units': 'metal'},
 'hybrid': {'atom_style': None,
            'boundary': [],
            'dt_fs': 1.0,
            'element_map': {1: 'Fe', 2: 'O'},
            'forcefield': 'ace',
            'pair_coeff': {'elements': ['Fe', 'O'], 'potential_file': 'ACE_Fe-O.yace'},
            'pair_style': 'hybrid/overlay pace zbl 1.0 2.0',
            'read_data': None,
            'timestep': 0.001,
            'units': 'metal'},
 'notimestep': {'atom_style': None,
                'boundary': [],
                'dt_fs': None,
                'element_map': {1: 'Fe', 2: 'O'},
                'forcefield': 'ace',
                'pair_coeff': {'elements': ['Fe', 'O'], 'potential_file': 'x.yace'},
                'pair_style': 'pace',
                'read_data': None,
                'timestep': None,
                'units': 'metal'},
 'nounits': {'atom_style': None,
             'boundary': [],
             'dt_fs': None,
             'element_map': {1: 'Fe', 2: 'O'},
             'forcefield': 'ace',
             'pair_coeff': {'elements': ['Fe', 'O'], 'potential_file': 'x.yace'},
             'pair_style': 'pace',
             'read_data': None,
             'timestep': 0.5,
             'units': None},
 'reaxff': {'atom_style': 'charge',
            'boundary': ['p', 'p', 'f'],
            'dt_fs': 0.25,
            'element_map': {1: 'Fe', 2: 'O'},
            'forcefield': 'reaxff',
            'pair_coeff': {'elements': ['Fe', 'O'], 'potential_file': 'ffield.reax'},
            'pair_style': 'reaxff NULL',
            'read_data': None,
            'timestep': 0.25,
            'units': 'real'}}

LEGACY_KEYS = ('forcefield', 'dt_fs', 'timestep', 'units', 'atom_style', 'boundary',
               'pair_style', 'pair_coeff', 'element_map', 'read_data')

# Exact first-token table. Verified against docs.lammps.org (2026-11-01):
# pace, pace/extrapolation, their /kk variants and the APIP-package variants
# (pace/apip, pace/fast/apip, pace/precise/apip); reaxff and its /kk, /omp
# variants; hdnnp. `reax/c` (+ /kk, /omp) is the historical ReaxFF name and is
# an assumed alias, not listed in the current manual.
CLASSIFY = {
    'pace': 'ace',
    'pace/extrapolation': 'ace',
    'pace/kk': 'ace',
    'pace/extrapolation/kk': 'ace',
    'pace/apip': 'ace',
    'pace/fast/apip': 'ace',
    'pace/precise/apip': 'ace',
    'pace product chunksize 4096': 'ace',
    'reaxff': 'reaxff',
    'reaxff NULL checkqeq no': 'reaxff',
    'reaxff/kk': 'reaxff',
    'reaxff/omp': 'reaxff',
    'reax/c': 'reaxff',
    'reax/c/kk': 'reaxff',
    'reax/c/omp': 'reaxff',
    'hdnnp 6.0 dir nnp': 'hdnnp',
    # Everything below is generic: no substring matching, ever.
    'pacemaker': 'generic',
    'pace_like': 'generic',
    'ace': 'generic',            # not a LAMMPS pair style name
    'n2p2': 'generic',           # n2p2 is the library; the pair style is hdnnp
    'nnp': 'generic',
    'reax': 'generic',
    'reaxffx': 'generic',
    'PACE': 'generic',           # LAMMPS command names are case-sensitive
    'eam': 'generic',
    'eam/alloy': 'generic',
    'lj/cut 8.0': 'generic',
    'lj/cut/coul/long 8.0': 'generic',
    'tersoff': 'generic',
    'hybrid pace zbl 1.0 2.0': 'generic',
    'hybrid/overlay pace reaxff': 'generic',
    'hybrid/scaled 1.0 pace 1.0 zbl 1.0 2.0': 'generic',
    'eam/alloy ACE_Fe-O.yace': 'generic',
    'eam/alloy reaxff.table': 'generic',
    '/data/pace/ACE.yace': 'generic',
}


def _write(text):
    """Write an input script to a fresh temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix='.in')
    with os.fdopen(fd, 'w') as f:
        f.write(text)
    return path


def _parse(name):
    """Parse one named synthetic input, silencing legacy warnings."""
    path = _write(INPUTS[name])
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return parse_input(path), path
    finally:
        os.remove(path)


def _raises(fn, *needles):
    """Assert fn raises ValueError mentioning every needle; return the message."""
    try:
        fn()
    except ValueError as exc:
        for needle in needles:
            assert needle in str(exc), f"{needle!r} missing from {exc}"
        return str(exc)
    raise AssertionError('expected ValueError')


def test_classifier_exact_token_table():
    """Each pair-style text maps to its literal family; lookalikes stay generic."""
    for text, family in CLASSIFY.items():
        assert classify_pair_style(text) == family, (text, family)


def test_classifier_no_evidence_is_none():
    """Empty, blank or missing text is 'no evidence', not 'generic'."""
    for text in (None, '', '   '):
        assert classify_pair_style(text) is None, repr(text)


def test_input_metadata_key_present_and_typed():
    """parse_input adds a RunMetadata under 'metadata' for every input."""
    for name in INPUTS:
        config, _ = _parse(name)
        assert isinstance(config['metadata'], RunMetadata), name


def test_explicit_families_from_input():
    """ACE, ReaxFF and HDNNP inputs classify from the explicit pair_style."""
    for name, family in (('ace', 'ace'), ('reaxff', 'reaxff'), ('hdnnp', 'hdnnp')):
        md = _parse(name)[0]['metadata']
        assert md.ff_family.value == family and md.ff_family.status == 'explicit', name


def test_explicit_eam_is_generic_and_keeps_raw():
    """An explicit EAM style is generic; the raw pair_style text is preserved."""
    md = _parse('eam')[0]['metadata']
    assert md.ff_family.value == 'generic' and md.ff_family.status == 'explicit'
    assert md.pair_style.value == 'eam/alloy' and md.pair_style.raw == 'eam/alloy'


def test_filename_with_pace_or_reaxff_is_not_evidence():
    """A potential filename containing family words never selects that family."""
    md = _parse('filename_trap')[0]['metadata']
    assert md.ff_family.value == 'generic'


def test_hybrid_is_generic_with_raw_kept():
    """Hybrid pair styles stay generic even when a sub-style is pace."""
    md = _parse('hybrid')[0]['metadata']
    assert md.ff_family.value == 'generic'
    assert md.pair_style.raw == 'hybrid/overlay pace zbl 1.0 2.0'


def test_source_is_input_path():
    """Explicit fields name the input file; unresolved fields carry a reason."""
    config, path = _parse('ace')
    md = config['metadata']
    assert md.units.source == path and md.timestep.source == path
    assert md.atom_style.value == 'atomic'
    bare = _parse('bare')[0]['metadata']
    assert bare.pair_style.status == 'unresolved' and bare.pair_style.note
    assert bare.ff_family.value is None and bare.ff_family.status == 'unresolved'


def test_metal_and_real_conversion_exact():
    """metal timesteps are ps (x1000 -> fs); real timesteps are already fs."""
    md = _parse('ace')[0]['metadata']
    assert md.timestep.value == 0.00025
    assert md.dt_fs.value == 0.00025 * 1000.0 and md.dt_fs.status == 'explicit'
    md = _parse('reaxff')[0]['metadata']
    assert md.dt_fs.value == 0.25 and md.dt_fs.status == 'explicit'
    assert derive_dt_fs('metal', 0.001) == (1.0, None)
    assert derive_dt_fs('real', 2.5) == (2.5, None)


def test_partial_metadata_leaves_dt_unresolved_with_reason():
    """Units without timestep, or timestep without units, never yield dt_fs."""
    md = _parse('notimestep')[0]['metadata']
    assert md.units.status == 'explicit' and md.timestep.status == 'unresolved'
    assert md.dt_fs.status == 'unresolved' and md.dt_fs.value is None
    assert 'timestep' in md.dt_fs.note
    md = _parse('nounits')[0]['metadata']
    assert md.timestep.value == 0.5 and md.timestep.status == 'explicit'
    assert md.units.status == 'unresolved'
    assert md.dt_fs.status == 'unresolved' and 'units' in md.dt_fs.note
    # An explicit family does not supply a missing dt (ADR-0005, units and time).
    assert md.ff_family.value == 'ace'


def test_lj_units_record_but_do_not_convert():
    """units lj is stored as declared; dt_fs is unresolved with a stated reason."""
    md = RunMetadata.from_explicit('x.in', pair_style='lj/cut 2.5', ff_family='generic',
                                   units='lj', timestep=0.005)
    assert md.units.value == 'lj' and md.timestep.value == 0.005
    assert md.dt_fs.status == 'unresolved' and md.dt_fs.value is None
    assert 'lj' in md.dt_fs.note and 'no scale is invented' in md.dt_fs.note


def test_invalid_timestep_rejected():
    """Non-finite, non-positive or non-numeric timesteps raise ValueError."""
    for bad in (0, -1.0, float('nan'), float('inf'), '0.5', True):
        _raises(lambda b=bad: RunMetadata.from_explicit('x.in', units='metal', timestep=b),
                'timestep')


def test_unresolved_field_cannot_carry_a_value():
    """MetadataField refuses a placeholder that looks like evidence."""
    _raises(lambda: MetadataField(1.0, None, 'unresolved'), 'unresolved')
    _raises(lambda: MetadataField(None, None, 'explicit'), 'needs a value')
    _raises(lambda: MetadataField('x', None, 'sure'), 'status')


def test_metadata_is_immutable():
    """RunMetadata and MetadataField are frozen value objects."""
    md = _parse('ace')[0]['metadata']
    for fn in (lambda: setattr(md, 'units', None), lambda: setattr(md.units, 'value', 'real')):
        try:
            fn()
        except Exception as exc:  # dataclasses.FrozenInstanceError
            assert type(exc).__name__ == 'FrozenInstanceError'
        else:
            raise AssertionError('mutation was allowed')


def test_family_requires_its_pair_style():
    """A family cannot be explicit without the pair style it came from."""
    _raises(lambda: RunMetadata.from_explicit('x.in', ff_family='ace'), 'pair_style')


def test_legacy_guess_marks_populated_fields_guessed():
    """Wrapping a detect_forcefield dict never yields an 'explicit' field."""
    info = {'forcefield': 'reaxff', 'unit_system': 'real', 'dt_fs': 0.25,
            'has_charge': True, 'atom_types': {1: 'A', 2: 'B'}}
    md = RunMetadata.from_guess(info)
    for name in ('ff_family', 'units', 'dt_fs'):
        f = getattr(md, name)
        assert f.status == 'guessed' and f.source == 'detect_forcefield', name
    assert md.ff_family.value == 'reaxff' and md.units.value == 'real'
    assert md.dt_fs.value == 0.25
    # The heuristic never saw these, so they are unresolved, not invented.
    for name in ('pair_style', 'atom_style', 'timestep'):
        assert getattr(md, name).status == 'unresolved', name
    assert all(getattr(md, n).status != 'explicit' for n in RunMetadata.FIELDS)


def test_describe_lists_every_field_with_status():
    """describe() has one line per field with status and source or reason."""
    text = _parse('notimestep')[0]['metadata'].describe().splitlines()
    assert [line.split(':')[0] for line in text] == list(RunMetadata.FIELDS)
    by = {line.split(':')[0]: line for line in text}
    assert '[explicit]' in by['units'] and '.in' in by['units']
    assert '[unresolved]' in by['timestep'] and 'dt_fs' in by
    guess = RunMetadata.from_guess({'forcefield': 'ace', 'unit_system': 'metal', 'dt_fs': 0.25})
    assert '[guessed]' in guess.describe()


def test_made_up_labels_and_sparse_types_do_not_affect_classification():
    """Classification reads only the pair_style token, never labels or type IDs."""
    text = ("units metal\npair_style eam/alloy\n"
            "pair_coeff * * pot.eam.alloy A B X\ntimestep 0.001\n")
    path = _write(text)
    try:
        md = parse_input(path)['metadata']
    finally:
        os.remove(path)
    assert md.ff_family.value == 'generic'
    sparse = ("units metal\npair_style pace\n"
              "pair_coeff * * pot.yace X Q\ntimestep 0.001\n")
    path = _write(sparse)
    try:
        config = parse_input(path)
    finally:
        os.remove(path)
    assert config['metadata'].ff_family.value == 'ace'
    assert config['element_map'] == {1: 'X', 2: 'Q'}


def test_legacy_parse_input_values_unchanged():
    """Existing parse_input keys keep the exact values main produced."""
    for name, expected in LEGACY.items():
        config, _ = _parse(name)
        for key in LEGACY_KEYS:
            assert config[key] == expected[key], (name, key, config[key], expected[key])
            assert type(config[key]) is type(expected[key]), (name, key)


def test_legacy_forcefield_still_substring_based_until_gen2b():
    """The legacy 'forcefield' key is untouched; only 'metadata' is generic-aware."""
    config, _ = _parse('hybrid')
    assert config['forcefield'] == 'ace'
    assert config['metadata'].ff_family.value == 'generic'


def test_repeated_equal_timestep_allowed():
    """Repeating the same finite timestep is harmless and keeps one value."""
    path = _write("units metal\ntimestep 0.001\ntimestep 0.001\ntimestep 1.0e-3\n")
    try:
        config = parse_input(path)
    finally:
        os.remove(path)
    assert config['timestep'] == 0.001 and config['metadata'].dt_fs.value == 1.0


def test_repeated_differing_timestep_rejected_with_path_and_values():
    """A second, different timestep raises, naming the file and both values."""
    path = _write("units metal\ntimestep 0.001\nrun 10\ntimestep 0.0005\n")
    try:
        _raises(lambda: parse_input(path), path, '0.001', '0.0005', 'timestep')
    finally:
        os.remove(path)


def test_repeated_timestep_via_variables_compared_after_resolution():
    """Differently written but numerically equal timesteps are accepted."""
    path = _write("units real\nvariable a equal 0.5\ntimestep ${a}\ntimestep 0.25*2/1\n")
    try:
        config = parse_input(path)
    finally:
        os.remove(path)
    assert config['timestep'] == 0.5 and config['dt_fs'] == 0.5
    assert math.isfinite(config['metadata'].dt_fs.value)
