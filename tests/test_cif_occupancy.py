"""REV-REF-1: reject CIF metadata that an unweighted reference cannot represent.

These synthetic inputs test the bounded reader, not arbitrary CIF compliance or
an occupancy-weighted physical model. Geometry expectations are literal and
independent of the reference RDF kernel. The shell check mocks plotting only as
a failure sentinel; real Agg artist coverage lives in test_audit_references_plots.
"""
import contextlib
import copy
import io
from pathlib import Path
import re
import tempfile
from unittest.mock import MagicMock, patch

import _util


_BASE_COLUMNS = ('_atom_site_label', '_atom_site_type_symbol',
                 '_atom_site_fract_x', '_atom_site_fract_y', '_atom_site_fract_z')
_OCCUPANCY = '_atom_site_occupancy'
_DISORDER = ('_atom_site_disorder_assembly', '_atom_site_disorder_group')


def _cif(rows, extra=(), columns=None, symmetry='_space_group_IT_number 1\n'):
    """Build an orthogonal synthetic cell without relying on production helpers."""
    columns = tuple(columns) if columns is not None else _BASE_COLUMNS + tuple(extra)
    return ('data_probe\n_chemical_name_mineral ordered_probe\n'
            '_cell_length_a 2\n_cell_length_b 4\n_cell_length_c 6\n'
            + symmetry + 'loop_\n' + '\n'.join(columns) + '\n' + rows + '\n')


def _reject(text, tag, site=None, value=None, line=None):
    """Require a contextual, visible policy error and unchanged source bytes."""
    from lammps_post.references import parse_cif

    with tempfile.TemporaryDirectory(prefix='lkpr-cif-guard-') as tmp:
        path = Path(tmp) / 'reference with spaces.cif'
        path.write_text(text, encoding='utf-8')
        original = path.read_bytes()
        try:
            parse_cif(str(path))
        except ValueError as exc:
            message = str(exc)
            assert str(path) in message, message
            assert tag.lower() in message.lower(), message
            assert any(word in message.lower() for word in
                       ('unsupported', 'not supported', 'only', 'cannot',
                        'ambiguous', 'invalid', 'malformed', 'requires')), message
            if site is not None:
                assert site in message, message
            if value is not None:
                assert value in message, message
            if line is not None:
                assert re.search(r'(?:\bline\s*[:=]?\s*' + str(line) + r'\b|:'
                                 + str(line) + r'(?::|\b))',
                                 message, re.IGNORECASE), message
        else:
            raise AssertionError('unsupported CIF accepted: ' + repr(text))
        assert path.read_bytes() == original


def _assert_geometry(crystal):
    """Use literal fractional/Cartesian sites and an analytic separation oracle."""
    import numpy as np

    assert set(crystal) == {'name', 'cell', 'atoms'}
    assert crystal['name'] == 'ordered_probe'
    np.testing.assert_allclose(crystal['cell'], [[2., 0., 0.], [0., 4., 0.],
                                               [0., 0., 6.]], atol=1e-14)
    assert [element for element, _ in crystal['atoms']] == ['X', 'Y']
    assert all(len(atom) == 2 for atom in crystal['atoms']), 'no occupancy weights'
    positions = np.array([position for _, position in crystal['atoms']])
    np.testing.assert_allclose(positions, [[.25, .5, .75], [.75, .5, .25]])
    cartesian = positions @ crystal['cell']
    np.testing.assert_allclose(cartesian, [[.5, 2., 4.5], [1.5, 2., 1.5]])
    np.testing.assert_allclose(np.linalg.norm(cartesian[1] - cartesian[0]), np.sqrt(10.))


def test_rev_ref_1_zero_occupancy_cannot_become_a_full_atom():
    """An explicitly empty CIF site must reject, not become a unit-weight atom."""
    _util.require_numpy()
    from pathlib import Path
    import tempfile
    from lammps_post.references import parse_cif

    text = ('data_probe\n_cell_length_a 2\n_cell_length_b 2\n_cell_length_c 2\n'
            '_space_group_IT_number 1\nloop_\n_atom_site_label\n'
            '_atom_site_type_symbol\n_atom_site_fract_x\n_atom_site_fract_y\n'
            '_atom_site_fract_z\n_atom_site_occupancy\nX1 X 0 0 0 0\n')
    with tempfile.TemporaryDirectory(prefix='lkpr-cif-occupancy-') as tmp:
        path = Path(tmp) / 'site.cif'
        path.write_text(text)
        try:
            parse_cif(str(path))
        except ValueError as exc:
            message = str(exc)
            assert str(path) in message and 'occupancy' in message.lower(), message
            assert 'X1' in message and '0' in message, message
        else:
            raise AssertionError('explicit zero-occupancy site was accepted as a full atom')


def test_cif_rejects_nonunit_unknown_nonfinite_and_malformed_occupancy():
    """Reject every unsupported nominal value, including float-rounded near-one."""
    _util.require_numpy()
    values = ('0', '-0', '0.0(2)', '.5', '0.75(3)', '-1', '1.01', '2', '.', '?',
              'NaN', 'nan', '+Inf', '-Inf', 'Infinity', '1e999999', '1e-999999',
              '.9999999999999999999999', '1.0000000000000000000001',
              '1/1', 'one', '1(abc)', '1()', '1(2)(3)', '1junk', '1_0',
              "'0.5'", '"?"')
    for value in values:
        text = _cif('X1 X .25 .5 .75 ' + value, extra=(_OCCUPANCY,))
        _reject(text, _OCCUPANCY, site='X1', value=value.strip('\'"'),
                line=len(text.splitlines()))


def test_cif_absent_occupancy_retains_literal_ordered_geometry():
    """Legacy absent metadata retains unit sites, return shape and source bytes."""
    _util.require_numpy()
    from lammps_post.references import parse_cif

    text = _cif('X1 X .25 .5 .75\nY1 Y .75 .5 .25')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'ordered.cif'
        path.write_text(text)
        original = path.read_bytes()
        _assert_geometry(parse_cif(str(path)))
        assert path.read_bytes() == original


def test_cif_exact_unit_decimal_scientific_uncertainty_and_quotes():
    """Only the exact nominal value matters; uncertainty is accepted, not modeled."""
    _util.require_numpy()
    from lammps_post.references import parse_cif

    values = ('1', '+1', '1.', '1.000', '01.000', '.1e1', '10e-1', '1E+0',
              '1.000(12)', '1.000(12)e0', "'1'", '"1.000(2)"', "'1e0'")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'unit.cif'
        for value in values:
            path.write_text(_cif('X1 X .25 .5 .75 ' + value +
                                 '\nY1 Y .75 .5 .25 ' + value, extra=(_OCCUPANCY,)))
            original = path.read_bytes()
            _assert_geometry(parse_cif(str(path)))
            assert path.read_bytes() == original


def test_cif_guarded_explicit_identity_and_body_centering_are_preserved():
    """Occupancy validation leaves explicit P1 and centering expansion unchanged."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.references import parse_cif

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'symmetry.cif'
        for operations, expected in (("'x,y,z'\n", [[0., 0., 0.]]),
                                     ("'x,y,z'\n'x+1/2,y+1/2,z+1/2'\n",
                                      [[0., 0., 0.], [.5, .5, .5]])):
            symmetry = ('loop_\n_space_group_symop_operation_xyz\n' + operations)
            path.write_text(_cif('X1 X 0 0 0 1 . .',
                                 extra=(_OCCUPANCY,) + _DISORDER, symmetry=symmetry))
            crystal = parse_cif(str(path))
            assert [element for element, _ in crystal['atoms']] == ['X'] * len(expected)
            np.testing.assert_allclose([p for _, p in crystal['atoms']], expected)


def test_cif_late_invalid_site_aborts_instead_of_returning_partial_crystal():
    """A valid prefix must not become an apparently complete reference crystal."""
    _util.require_numpy()
    from lammps_post.references import CRYSTAL_DB

    before = _util.canon(CRYSTAL_DB)
    for invalid in ('0', '.5', '?'):
        text = _cif('X1 X .25 .5 .75 1\nY_late Y .75 .5 .25 ' + invalid,
                    extra=(_OCCUPANCY,))
        _reject(text, _OCCUPANCY, site='Y_late', value=invalid,
                line=len(text.splitlines()))
    assert _util.canon(CRYSTAL_DB) == before


def test_cif_guarded_loop_prefixed_labels_cannot_hide_unsupported_sites():
    """Loop-like labels are data: validate bad sites and retain ordered unit sites."""
    _util.require_numpy()
    from lammps_post.references import parse_cif

    extra = (_OCCUPANCY,) + _DISORDER
    prefix = 'X1 X 0 0 0 1 . .\n'
    suffix = '\nZ1 Z .25 .75 .25 1 . .'
    labels = ('loopSite1', 'loop_1', 'LOOPSITE1', 'LOOP_1')
    for label in labels:
        for metadata, tag, value in (('0 . .', _OCCUPANCY, '0'),
                                     ('.5 . .', _OCCUPANCY, '.5'),
                                     ('1 A .', _DISORDER[0], 'A'),
                                     ('1 . A', _DISORDER[1], 'A')):
            text = _cif(prefix + label + ' Y .5 .5 .5 ' + metadata + suffix,
                        extra=extra)
            _reject(text, tag, site=label, value=value,
                    line=len(text.splitlines()) - 1)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'loop_labels.cif'
        for label in labels:
            path.write_text(_cif('X1 X 0 0 0 1\n' + label + ' Y .5 .5 .5 1\n'
                                 'Z1 Z .25 .75 .25 1', extra=(_OCCUPANCY,)))
            original = path.read_bytes()
            crystal = parse_cif(str(path))
            assert len(crystal['atoms']) == 3
            assert crystal['atoms'] == [('X', [0., 0., 0.]),
                                        ('Y', [.5, .5, .5]),
                                        ('Z', [.25, .75, .25])]
            assert path.read_bytes() == original


def test_cif_bad_coordinates_or_element_cannot_hide_partial_occupancy():
    """Validate metadata before filtering unusable coordinates or element fields."""
    _util.require_numpy()
    for row in ('X_bad X ? 0 0 .5', 'X_bad X bad 0 0 .5',
                'X_bad - 0 0 0 .5', 'X_bad X 0 . 0 .5'):
        text = _cif('X1 X .25 .5 .75 1\n' + row, extra=(_OCCUPANCY,))
        _reject(text, _OCCUPANCY, site='X_bad', value='.5')


def test_cif_case_insensitive_reordered_guarded_columns():
    """Mixed/uppercase tags cannot bypass validation and still map valid sites."""
    _util.require_numpy()
    from lammps_post.references import parse_cif

    columns = ('_ATOM_SITE_OCCUPANCY', '_Atom_Site_Fract_Z', '_ATOM_SITE_LABEL',
               '_atom_site_fract_y', '_ATOM_SITE_TYPE_SYMBOL', '_Atom_Site_Fract_X',
               '_ATOM_SITE_DISORDER_GROUP')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'mixed.cif'
        path.write_text(_cif('1 .75 X1 .5 X .25 .\n1 .25 Y1 .5 Y .75 .', columns=columns))
        _assert_geometry(parse_cif(str(path)))
    _reject(_cif('.5 .75 X_bad .5 X .25 .', columns=columns),
            _OCCUPANCY, site='X_bad', value='.5')
    _reject(_cif('1 .75 X_bad .5 X .25 A', columns=columns),
            _DISORDER[1], site='X_bad', value='A')


def test_cif_guarded_simple_quotes_and_inline_comments():
    """Quoted fields and comments preserve row width without treating # as a field."""
    _util.require_numpy()
    from lammps_post.references import parse_cif

    rows = ('\'X1 # first site\' \'X\' .25 .5 .75 "1.000" . . # full site\n'
            '"Y1 second site" Y .75 .5 .25 \'1e0\' . . # another site')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'quoted.cif'
        path.write_text(_cif(rows, extra=(_OCCUPANCY,) + _DISORDER))
        _assert_geometry(parse_cif(str(path)))
    _reject(_cif("'X bad label' X 0 0 0 .5 # a comment", extra=(_OCCUPANCY,)),
            _OCCUPANCY, site='X bad label', value='.5')


def test_cif_disorder_only_accepts_absent_or_unquoted_not_applicable():
    """Codes may be valid CIF but are unsupported, not proof of ordered sites."""
    _util.require_numpy()
    from lammps_post.references import parse_cif

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'ordered.cif'
        for tags in ((_DISORDER[0],), (_DISORDER[1],), _DISORDER):
            dots = ' .' * len(tags)
            path.write_text(_cif('X1 X .25 .5 .75' + dots +
                                 '\nY1 Y .75 .5 .25' + dots, extra=tags))
            _assert_geometry(parse_cif(str(path)))
    for tag in _DISORDER:
        for code in ('0', '1', 'A', '-1', '?', "'.'", '"."'):
            for occupancy in (False, True):
                extra = (tag, _OCCUPANCY) if occupancy else (tag,)
                row = 'X_disordered X 0 0 0 ' + code + (' 1' if occupancy else '')
                _reject(_cif(row, extra=extra), tag, site='X_disordered',
                        value=code.strip('\'"'))


def test_cif_unbound_scalar_or_other_loop_guard_metadata_is_rejected():
    """Relevant metadata cannot silently float outside the selected atom header."""
    _util.require_numpy()
    ordered = _cif('X1 X .25 .5 .75')
    for tag in (_OCCUPANCY,) + _DISORDER:
        for value in ('1', '.5', '.'):
            fragments = (tag + ' ' + value + '\n',
                         tag + '\n' + value + '\n',
                         'loop_\n' + tag + '\n' + value + '\n',
                         'loop_\n_atom_site_label\n' + tag + '\nX1 ' + value + '\n')
            for fragment in fragments:
                _reject(ordered + fragment, tag)
                _reject(ordered.replace('loop_\n', fragment + 'loop_\n', 1), tag)
        second = _cif('Y1 Y 0 0 0 .5', extra=(tag,)).split('loop_\n', 1)[1]
        _reject(ordered + 'loop_\n' + second, tag)


def test_cif_packed_unbound_constraint_aliases_cannot_escape_association():
    """Reject declarations after another scalar value, not just line-leading tags."""
    _util.require_numpy()
    ordered = _cif('X1 X 0 0 0')
    for canonical in (_OCCUPANCY,) + _DISORDER:
        alias = canonical.replace('_atom_site_', '_atom_site.')
        for tag in (canonical, canonical.swapcase(), canonical.title(),
                    alias, alias.swapcase(), alias.title()):
            for value in (('0', '.5', '1') if canonical == _OCCUPANCY else ('A', '.')):
                # The lower-case occupancy/zero suffix is the actual packed-scalar repro.
                row = "_chemical_name_mineral 'Probe' " + tag + ' ' + value
                for text in (ordered + row + '\n',
                             ordered.replace('loop_\n', row + '\nloop_\n', 1)):
                    line = text.splitlines().index(row) + 1
                    _reject(text, tag, value=row, line=line)


def test_cif_packed_supported_guard_headers_keep_unit_sites_and_reject_bad_sites():
    """Packed underscore headers work without claiming general dot-category parsing."""
    _util.require_numpy()
    from lammps_post.references import parse_cif

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'packed_headers.cif'
        for tag in (_OCCUPANCY,) + _DISORDER:
            for header_tag in (tag, tag.swapcase(), tag.title()):
                columns = (' '.join(_BASE_COLUMNS + (header_tag,)),)
                value = '1' if tag == _OCCUPANCY else '.'
                path.write_text(_cif('X1 X .25 .5 .75 ' + value +
                                     '\nY1 Y .75 .5 .25 ' + value, columns=columns))
                original = path.read_bytes()
                _assert_geometry(parse_cif(str(path)))
                assert path.read_bytes() == original
                invalid = '.5' if tag == _OCCUPANCY else 'A'
                text = _cif('X1 X .25 .5 .75 ' + value +
                            '\nY_bad Y .75 .5 .25 ' + invalid, columns=columns)
                _reject(text, tag, site='Y_bad', value=invalid,
                        line=len(text.splitlines()))


def test_cif_quoted_comment_and_semicolon_tag_mentions_are_not_declarations():
    """Lexical tag mentions in text remain text while literal ordered sites survive."""
    _util.require_numpy()
    from lammps_post.references import parse_cif

    ordered = _cif('X1 X .25 .5 .75\nY1 Y .75 .5 .25')
    annotations = (
        "_chemical_name_mineral 'Probe mentions _atom_site_occupancy 0'\n",
        '_audit_creation_method "prefix _ATOM_SITE.OCCUPANCY 0 '
        '_atom_site_disorder_group A"\n',
        "_audit_creation_method '_atom_site_occupancy'\n",
        '# _atom_site_occupancy 0 _atom_site.disorder_group A\n',
        '_audit_creation_method synthetic # _ATOM_SITE_DISORDER_ASSEMBLY A\n',
        '_audit_creation_method\n;\nText with an unmatched quote \' and '
        '_atom_site_occupancy 0\n_atom_site.disorder_group A\n'
        '_ATOM_SITE_DISORDER_ASSEMBLY A\n;\n',
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'tag_mentions.cif'
        for annotation in annotations:
            for text in (ordered + annotation,
                         ordered.replace('loop_\n', annotation + 'loop_\n', 1)):
                path.write_text(text)
                original = path.read_bytes()
                _assert_geometry(parse_cif(str(path)))
                assert path.read_bytes() == original


def test_cif_guarded_duplicate_columns_are_ambiguous():
    """Duplicate guard or coordinate columns cannot select an arbitrary value."""
    _util.require_numpy()
    for duplicate in (_OCCUPANCY, _DISORDER[0], _DISORDER[1], '_atom_site_fract_x'):
        columns = _BASE_COLUMNS + (_OCCUPANCY,) + (() if duplicate == _OCCUPANCY
                                                  else (duplicate,)) + (duplicate.upper(),)
        values = ['X1', 'X', '0', '0', '0', '1']
        if duplicate != _OCCUPANCY:
            values.append('.' if duplicate in _DISORDER else '0')
        values.append('0')
        _reject(_cif(' '.join(values), columns=columns), duplicate)


def test_cif_guarded_short_long_and_split_rows_fail_before_filtering():
    """Guarded rows must have complete unambiguous width, even with bad positions."""
    _util.require_numpy()
    for tag in (_OCCUPANCY,) + _DISORDER:
        for row in ('X_short X ? 0 0', 'X_short X ? 0',
                    'X_long X 0 0 0 1 extra', 'X_split X 0 0 0\n.5'):
            text = _cif('X1 X 0 0 0 ' + ('1' if tag == _OCCUPANCY else '.') +
                        '\n' + row, extra=(tag,))
            _reject(text, tag)


def test_cif_guarded_unmatched_quotes_and_multiline_fields_fail_clearly():
    """Unsupported lexical constructs must not erase a guarded row or site."""
    _util.require_numpy()
    for row in ("X_bad X 0 0 0 '1", 'X_bad X 0 0 0 "1',
                'X_bad X 0 0 0\n;1\n;'):
        _reject(_cif(row, extra=(_OCCUPANCY,)), _OCCUPANCY)


def test_cif_cod_download_uses_the_same_guard_without_network_access():
    """A synthetic urlopen response exercises COD parsing, not COD availability."""
    _util.require_numpy()
    from lammps_post.references import parse_cif

    response = MagicMock()
    response.__enter__.return_value.read.return_value = _cif(
        'X_cod X 0 0 0 .5', extra=(_OCCUPANCY,)).encode('utf-8')
    with patch('urllib.request.urlopen', return_value=response) as download:
        try:
            parse_cif('cod:1234567')
        except ValueError as exc:
            message = str(exc)
            assert 'cod:1234567' in message and _OCCUPANCY in message.lower(), message
            assert 'X_cod' in message and '.5' in message, message
        else:
            raise AssertionError('downloaded partial-occupancy reference accepted')
    download.assert_called_once()


def test_cif_shell_interactive_import_fails_before_compute_plot_or_publication():
    """Real shell dispatch reports failure; renderer/compute are sentinels only."""
    _util.require_numpy()
    from lammps_post import plotting, references, shell as shell_module

    _util.require(plotting.HAS_MPL, 'matplotlib not installed (interactive CIF shell check)')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'partial.cif'
        path.write_text(_cif('X1 X 0 0 0 1\nY_late Y .5 .5 .5 .5', extra=(_OCCUPANCY,)))
        original = path.read_bytes()
        shell = shell_module.LammpsPostShell()
        shell.state.output_dir = str(Path(tmp) / 'plots')
        shell.state.cache['rdf_X_Y'] = {'r': [1.], 'g': [2.]}
        shell.state.plot_recipes['rdf'] = {'_ref_rdfs': [{'label': 'existing'}]}
        before_cache = copy.deepcopy(shell.state.cache)
        before_recipes = copy.deepcopy(shell.state.plot_recipes)
        choice = str(len(references.get_phases_for_pair(('X', 'Y'))) + 2)
        answers = [shell.state.output_dir, 'all', 'y', choice, str(path)]
        output = io.StringIO()
        with patch.object(shell_module.sys, 'stdin') as stdin, \
                patch.object(shell, '_ask', side_effect=answers), \
                patch.object(references, 'compute_reference_rdf',
                             side_effect=AssertionError('reference computation reached')) as compute, \
                patch.object(shell_module, 'plot_rdf',
                             side_effect=AssertionError('rendering reached')) as render, \
                patch.object(shell, '_save_recipe',
                             side_effect=AssertionError('recipe publication reached')) as publish, \
                contextlib.redirect_stdout(output):
            stdin.isatty.return_value = True
            assert shell.onecmd('plot rdf') is False
        compute.assert_not_called()
        render.assert_not_called()
        publish.assert_not_called()
        assert shell.last_command_ok is False and shell.command_failures == 1
        message = output.getvalue()
        assert 'ValueError' in message and str(path) in message, message
        assert _OCCUPANCY in message.lower() and 'Y_late' in message, message
        assert shell.state.cache == before_cache
        assert shell.state.plot_recipes == before_recipes
        assert not list(Path(shell.state.output_dir).iterdir())
        assert path.read_bytes() == original
