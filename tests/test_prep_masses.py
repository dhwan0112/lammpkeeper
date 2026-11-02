"""REV-PREP-4: prep's metadata-only data inspector must read conventional Masses.

LAMMPS data files put a blank line after the `Masses` keyword and a blank line
after the entries. The inspector used to end its Masses state at the first
blank line, so the conventional layout returned an empty mass map. Blank lines
before the first entry are now skipped; a blank line after entries, a comment
line or the next section keyword ends the section. Compact layouts, inline
`# label` comments and the writer's own output must keep working. Coordinates
and presets are not read or changed by this inspector.
"""

import contextlib
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace

import _util  # noqa: F401
from _util import require_numpy

HEADER = ('# test data\n\n'
          '2 atoms\n'
          '2 atom types\n\n'
          '0.0000000000 10.0000000000 xlo xhi\n'
          '0.0000000000 10.0000000000 ylo yhi\n'
          '0.0000000000 10.0000000000 zlo zhi\n\n')


def _parse(text):
    """Write `text` to a temporary data file and run the real inspector on it."""
    from lammps_pre.shell import LammpsPreShell
    with tempfile.TemporaryDirectory(prefix='lk-prep-masses-') as tmp:
        path = Path(tmp) / 'case.data'
        path.write_text(text)
        return LammpsPreShell._parse_data_file(str(path))


def test_conventional_blank_separated_masses_are_read():
    """Blank line after the keyword and after the entries must not hide the masses."""
    info = _parse(HEADER
                  + 'Masses\n\n'
                  + '1 55.845  # Fe_up (Fe)\n'
                  + '2 15.999  # O\n\n'
                  + 'Atoms # atomic\n\n'
                  + '1 1 0.0 0.0 0.0\n2 2 5.0 5.0 5.0\n')
    assert info['masses'] == {1: 55.845, 2: 15.999}, info
    assert info['n_atoms'] == 2 and info['n_types'] == 2, info
    assert info['atom_style'] == 'atomic', info
    assert (info['xlo'], info['xhi']) == (0.0, 10.0), info


def test_several_blank_lines_after_keyword_are_skipped():
    """Every blank line before the first entry is part of the gap, not the section end."""
    info = _parse(HEADER
                  + 'Masses\n\n\n'
                  + '1 55.845\n2 15.999\n\n'
                  + 'Atoms # charge\n\n')
    assert info['masses'] == {1: 55.845, 2: 15.999}, info
    assert info['atom_style'] == 'charge', info


def test_compact_masses_without_blank_lines_still_read():
    """Compact layout (no blank line after the keyword) keeps its previous result."""
    info = _parse(HEADER
                  + 'Masses\n'
                  + '1 55.845\n2 15.999\n\n'
                  + 'Atoms # charge\n\n')
    assert info['masses'] == {1: 55.845, 2: 15.999}, info
    assert info['atom_style'] == 'charge', info


def test_masses_directly_followed_by_atoms_keep_style():
    """The next section keyword ends Masses, and its style comment is still detected."""
    info = _parse(HEADER
                  + 'Masses\n\n'
                  + '1 55.845  # Fe\n2 15.999  # O\n'
                  + 'Atoms # atomic\n\n'
                  + '1 1 0.0 0.0 0.0\n')
    assert info['masses'] == {1: 55.845, 2: 15.999}, info
    assert info['atom_style'] == 'atomic', info


def test_blank_line_after_entries_ends_masses():
    """Entries after a blank line that follows real entries are not mass entries."""
    info = _parse(HEADER
                  + 'Masses\n\n'
                  + '1 55.845  # Fe\n\n'
                  + '2 15.999  # O\n\n'
                  + 'Atoms # atomic\n\n')
    assert info['masses'] == {1: 55.845}, info


def test_inline_labels_do_not_change_masses():
    """Inline `# label` text after the mass is ignored; only type and mass are kept."""
    info = _parse(HEADER
                  + 'Masses\n\n'
                  + '1 55.845 # Fe_up (Fe) spin up\n'
                  + '2 15.999 #O\n\n'
                  + 'Atoms # atomic\n\n')
    assert info['masses'] == {1: 55.845, 2: 15.999}, info


def test_prep_writer_output_is_read_back():
    """The real data writer (ACE and ReaxFF) must round-trip its own masses and counts."""
    require_numpy()
    import numpy as np
    from lammps_pre.state import FF_PRESETS
    from lammps_pre.writers import write_data_file
    cases = [('ace', 3, 'atomic'), ('reaxff2010', 2, 'charge'),
             ('reaxff2015', 2, 'charge')]
    for ff_name, n_types, style in cases:
        ff = FF_PRESETS[ff_name]
        build = SimpleNamespace(
            fe_positions=np.array([[1.0, 1.0, 1.0], [2.0, 1.0, 1.0]]),
            o2_positions=np.array([[3.0, 1.0, 1.0]]),
            box=(0.0, 20.0, 0.0, 20.0, 0.0, 20.0),
            regions={'n_fixed_layers': 1, 'n_thermostat_layers': 1,
                     'n_nve_layers': 1})
        prep = SimpleNamespace(ff=ff, surface='100', nx=1, ny=1, nz=3)
        with tempfile.TemporaryDirectory(prefix='lk-prep-writer-') as tmp:
            path = Path(tmp) / 'generated.data'
            with contextlib.redirect_stdout(io.StringIO()):
                write_data_file(build, prep, str(path))
            info = _parse(path.read_text())
        assert info['masses'] == ff['masses'], (ff_name, info)
        assert info['n_atoms'] == 3, (ff_name, info)
        assert info['n_types'] == n_types, (ff_name, info)
        assert info['atom_style'] == style, (ff_name, info)
