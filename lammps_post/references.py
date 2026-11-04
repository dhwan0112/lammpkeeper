"""
═══════════════════════════════════════════════════════════════
Reference Crystal Structures for RDF Comparison
═══════════════════════════════════════════════════════════════
Computes ideal g(r) from known crystal structures of iron and
iron oxide phases. Used for overlaying reference RDFs on top of
MD-computed g(r) to compare candidate local environments. Similar peak
positions alone do not establish an oxide phase, magnetic order or purity.

Two sources of crystal data:
  A. Built-in database — hardcoded from experimental refinements
  B. CIF file import  — bounded ordered/unit-site subset from local files or COD

Built-in phases:
  - alpha-Fe   (BCC, Im-3m, a = 2.87 Å)
  - FeO        (wustite, rocksalt, Fm-3m, a = 4.326 Å)
  - Fe2O3      (hematite, corundum, R-3c, a = 5.038 Å, c = 13.772 Å)
  - Fe3O4      (magnetite, inverse spinel, Fd-3m, a = 8.396 Å)

CIF import supports:
  - Local .cif files
  - Crystallography Open Database (COD) by ID:
      e.g., parse_cif('cod:9009768') fetches Fe3O4 from COD

No external dependencies beyond numpy — CIF parsing and symmetry
expansion are implemented from scratch.
This is a lightweight CIF reader, not a complete crystallographic parser:
explicit unsupported occupancy/disorder is rejected, not weighted or resolved.
Arbitrary CIF syntax and general symmetry algebra are not modeled. Built-in
cells describe ideal periodic positions without thermal motion, defects, spin
assignments or force-field-dependent relaxation.
═══════════════════════════════════════════════════════════════
"""

from decimal import Decimal, InvalidOperation
import os
import re
import numpy as np


# ═══════════════════════════════════════════════════════════════
# Utility: Symmetry Operations & Cell Geometry
# ═══════════════════════════════════════════════════════════════

def _cubic_cell(a):
    """Return row lattice vectors for a cubic cell with side length a in Å."""
    return np.diag([a, a, a])


def _hexagonal_cell(a, c):
    """Return row vectors for a hexagonal cell, with lengths a/c in Å.

    The second in-plane vector makes 120 degrees with the first; the c vector
    is perpendicular to that plane, matching the hematite hexagonal setting.
    """
    return np.array([
        [a, 0, 0],
        [-a / 2, a * np.sqrt(3) / 2, 0],
        [0, 0, c],
    ])


def _cell_from_params(a, b, c, alpha, beta, gamma):
    """Build row lattice vectors from lengths in Å and angles in degrees.

    Place a along x and b in the xy plane, choosing positive c_z. alpha,
    beta and gamma are respectively the b-c, a-c and a-b angles. Every length
    must be a finite positive number and every angle a finite number strictly
    between 0 and 180 degrees; the three angles must also describe a cell of
    positive volume, i.e. ``1 - cos²α - cos²β - cos²γ + 2 cosα cosβ cosγ > 0``
    (each angle smaller than the sum of the other two and the three summing
    to less than 360 degrees). The residual is compared against 1e-12 rather
    than 0 so that exact boundary triples such as 120/120/120, whose residual
    rounds to about +1e-15, are rejected too. Bools, numpy bools and strings
    are not numbers here. Anything else raises ValueError naming the
    offending parameter; no value is clipped or defaulted.
    """
    params = {'a': a, 'b': b, 'c': c, 'alpha': alpha, 'beta': beta, 'gamma': gamma}
    for name, value in params.items():
        if isinstance(value, (bool, np.bool_, str, bytes)):
            raise ValueError(f'cell parameter {name} must be a number, got {value!r}')
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f'cell parameter {name} must be a number, got {value!r}') from None
        if not np.isfinite(number):
            raise ValueError(f'cell parameter {name} must be finite, got {value!r}')
        params[name] = number
    for name in ('a', 'b', 'c'):
        if params[name] <= 0.0:
            raise ValueError(f'cell length {name} must be positive, got {params[name]:g}')
    for name in ('alpha', 'beta', 'gamma'):
        if not 0.0 < params[name] < 180.0:
            raise ValueError(f'cell angle {name} must lie strictly between 0 and 180 degrees, '
                             f'got {params[name]:g}')
    a, b, c = params['a'], params['b'], params['c']
    alpha, beta, gamma = params['alpha'], params['beta'], params['gamma']

    alpha_r = np.radians(alpha)
    beta_r = np.radians(beta)
    gamma_r = np.radians(gamma)

    cos_a, cos_b, cos_g = np.cos(alpha_r), np.cos(beta_r), np.cos(gamma_r)
    sin_g = np.sin(gamma_r)

    # Squared volume of the unit parallelepiped: V = abc * sqrt(residual).
    residual = 1.0 - cos_a ** 2 - cos_b ** 2 - cos_g ** 2 + 2.0 * cos_a * cos_b * cos_g
    # The residual is dimensionless and its rounding error is ~1e-15, so a
    # strict `> 0` test would accept exact boundary triples (120/120/120
    # evaluates to +1e-15) and build a cell with c_z ~ 1e-8.
    if residual <= 1e-12:
        raise ValueError(f'cell angles alpha={alpha:g}, beta={beta:g}, gamma={gamma:g} do not '
                         f'describe a cell with positive volume; each angle must be smaller than '
                         f'the sum of the other two and the three must sum to less than 360 degrees')

    v2 = b * cos_g
    v3 = b * sin_g
    w2 = c * cos_b
    w3 = c * (cos_a - cos_b * cos_g) / sin_g
    w4 = c * np.sqrt(residual) / sin_g

    return np.array([
        [a, 0, 0],
        [v2, v3, 0],
        [w2, w3, w4],
    ])


def _frac_to_cart(frac_coords, cell):
    """Convert fractional row coordinates via lattice vectors stored as rows.

    Both a single length-three position and an (N, 3) array use ``frac @ cell``;
    the returned length unit is the unit of the supplied cell (normally Å).
    """
    return frac_coords @ cell


_SYMOP_TERM = re.compile(r'([+-]?)(?:(\d+)\*?)?([xyz])|([+-]?)(\d+/\d+|\d*\.\d+|\d+\.?\d*)')


def _parse_symop(symop_str):
    """
    Parse one CIF xyz symmetry operator into (rotation, translation).

    The grammar is the conventional one: exactly three comma-separated
    components; each component is a sum of terms where a term is a signed
    coordinate (``x``, ``-y``, ``+z``, optionally with an integer coefficient
    such as ``2*x``) or a signed numeric translation (``1/2``, ``0.5``,
    ``.25``, ``1``). Case and whitespace are ignored; every term after the
    first must carry its own sign, and nothing else may appear. The rotation
    part must be unimodular (determinant +1 or -1), which every space-group
    operation is in lattice coordinates; a singular or scaled operator is not
    a symmetry operation and is rejected rather than applied.

    Raises ValueError naming the operator, the component and the offending
    text for anything outside that grammar. No eval is involved.
    """
    if not isinstance(symop_str, str):
        raise ValueError(f'symmetry operation must be a string, got {type(symop_str).__name__}')
    components = symop_str.lower().split(',')
    if len(components) != 3:
        raise ValueError(f'symmetry operation {symop_str!r} has {len(components)} comma-separated '
                         f'component(s); exactly three (x, y, z) are required')
    rotation = np.zeros((3, 3))
    translation = np.zeros(3)
    for i, component in enumerate(components):
        expr = re.sub(r'\s+', '', component)
        if not expr:
            raise ValueError(f'symmetry operation {symop_str!r}: component {i + 1} is empty')
        pos = 0
        while pos < len(expr):
            m = _SYMOP_TERM.match(expr, pos)
            if m is None:
                raise ValueError(f'symmetry operation {symop_str!r}: component {i + 1} '
                                 f'({component.strip()!r}) has unrecognized text {expr[pos:]!r}; '
                                 f'only signed x/y/z terms and numeric or fractional '
                                 f'translations are supported')
            sign, coeff, axis, const_sign, const = m.groups()
            if pos > 0 and not (sign or const_sign):
                raise ValueError(f'symmetry operation {symop_str!r}: component {i + 1} '
                                 f'({component.strip()!r}) has term {m.group(0)!r} without an '
                                 f'explicit sign after {expr[:pos]!r}')
            if axis:
                value = float(coeff) if coeff else 1.0
                rotation[i, 'xyz'.index(axis)] += -value if sign == '-' else value
            else:
                if '/' in const:
                    num, den = const.split('/')
                    if int(den) == 0:
                        raise ValueError(f'symmetry operation {symop_str!r}: component {i + 1} '
                                         f'has translation {const!r} with a zero denominator')
                    value = int(num) / int(den)
                else:
                    value = float(const)
                translation[i] += -value if const_sign == '-' else value
            pos = m.end()
    det = float(np.linalg.det(rotation))
    if abs(abs(det) - 1.0) > 1e-9:
        raise ValueError(f'symmetry operation {symop_str!r} has rotation determinant {det:g}; '
                         f'a space-group operation must be unimodular (determinant +1 or -1)')
    return rotation, translation


def _apply_symop(symop_str, frac):
    """
    Apply a symmetry operation string (e.g., '-x, y+1/2, -z+1/2') to
    fractional coordinates. Returns the new fractional position, which may lie
    outside the unit cell; wrapping and duplicate handling belong to
    _expand_symmetry.

    The operator is parsed by _parse_symop, so a malformed or non-unimodular
    operator raises ValueError instead of silently contributing zero.
    """
    rotation, translation = _parse_symop(symop_str)
    return rotation @ np.asarray(frac, dtype=float) + translation


def _expand_symmetry(asym_atoms, symops):
    """
    Expand asymmetric unit atoms using symmetry operations.
    Remove duplicate element/position keys after rounding each wrapped
    fractional component to three decimal places. This is quantized equality,
    not a Cartesian-distance tolerance or a nearest-image neighbor test.
    Returns list of (element, [fx, fy, fz]) with coordinates wrapped to [0, 1).

    Keep elements in the key so coincident sites of different species are not
    merged. Preserve the first generated representative in traversal order;
    site occupancies and disorder alternatives are not resolved here.
    Rounding occurs after modulo wrapping: values close to 1 and 0 can still
    have distinct keys across the periodic seam, while nearby interior sites
    may collapse into one key. Neither behavior measures site separation in Å.
    """
    # Parse every operator before generating any site, so a malformed
    # operation rejects the whole expansion instead of a partial cell.
    parsed = [_parse_symop(op) for op in symops]
    all_atoms = []
    seen = set()

    for elem, frac in asym_atoms:
        frac = np.asarray(frac, dtype=float)
        for rotation, translation in parsed:
            new_frac = rotation @ frac + translation
            # Wrap to [0, 1)
            new_frac = new_frac % 1.0
            # Round for duplicate detection
            key = (elem, round(new_frac[0], 3), round(new_frac[1], 3), round(new_frac[2], 3))
            if key not in seen:
                seen.add(key)
                all_atoms.append((elem, new_frac.tolist()))

    return all_atoms


# ═══════════════════════════════════════════════════════════════
# Built-in Crystal Database
# ═══════════════════════════════════════════════════════════════

CRYSTAL_DB = {}

# ── alpha-Fe (BCC, Im-3m) ──
CRYSTAL_DB['alpha-Fe'] = {
    'name': 'α-Fe (BCC)',
    'cell': _cubic_cell(2.8665),
    'atoms': [
        ('Fe', [0.0, 0.0, 0.0]),
        ('Fe', [0.5, 0.5, 0.5]),
    ],
}

# ── FeO wustite (rocksalt, Fm-3m) ──
# Translate both basis sites through the same face-centering vectors to build
# the conventional cell, rather than confusing its motif with a primitive cell.
_fcc_trans = [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]]
_feo_atoms = []
for t in _fcc_trans:
    _feo_atoms.append(('Fe', [(0.0 + t[0]) % 1, (0.0 + t[1]) % 1, (0.0 + t[2]) % 1]))
    _feo_atoms.append(('O',  [(0.5 + t[0]) % 1, (0.5 + t[1]) % 1, (0.5 + t[2]) % 1]))
CRYSTAL_DB['FeO'] = {
    'name': 'FeO (wüstite)',
    'cell': _cubic_cell(4.326),
    'atoms': _feo_atoms,
}

# ── Fe2O3 hematite (R-3c, hexagonal setting) ──
# Asymmetric unit: Fe at (0, 0, 0.3553), O at (0.3059, 0, 0.25)
# Include centering translations in the operation list: point rotations alone
# would leave an incomplete conventional hexagonal reference cell.
_hematite_symops = [
    'x, y, z', '-y, x-y, z', '-x+y, -x, z',
    'x-y, -y, -z+1/2', '-x, -x+y, -z+1/2', 'y, x, -z+1/2',
    '-x, -y, -z', 'y, -x+y, -z', 'x-y, x, -z',
    '-x+y, y, z+1/2', 'x, x-y, z+1/2', '-y, -x, z+1/2',
    # + rhombohedral centering: (2/3, 1/3, 1/3) and (1/3, 2/3, 2/3)
    'x+2/3, y+1/3, z+1/3', '-y+2/3, x-y+1/3, z+1/3',
    '-x+y+2/3, -x+1/3, z+1/3', 'x-y+2/3, -y+1/3, -z+1/2+1/3',
    '-x+2/3, -x+y+1/3, -z+1/2+1/3', 'y+2/3, x+1/3, -z+1/2+1/3',
    '-x+2/3, -y+1/3, -z+1/3', 'y+2/3, -x+y+1/3, -z+1/3',
    'x-y+2/3, x+1/3, -z+1/3', '-x+y+2/3, y+1/3, z+1/2+1/3',
    'x+2/3, x-y+1/3, z+1/2+1/3', '-y+2/3, -x+1/3, z+1/2+1/3',
    'x+1/3, y+2/3, z+2/3', '-y+1/3, x-y+2/3, z+2/3',
    '-x+y+1/3, -x+2/3, z+2/3', 'x-y+1/3, -y+2/3, -z+1/2+2/3',
    '-x+1/3, -x+y+2/3, -z+1/2+2/3', 'y+1/3, x+2/3, -z+1/2+2/3',
    '-x+1/3, -y+2/3, -z+2/3', 'y+1/3, -x+y+2/3, -z+2/3',
    'x-y+1/3, x+2/3, -z+2/3', '-x+y+1/3, y+2/3, z+1/2+2/3',
    'x+1/3, x-y+2/3, z+1/2+2/3', '-y+1/3, -x+2/3, z+1/2+2/3',
]
_hematite_asym = [('Fe', [0.0, 0.0, 0.3553]), ('O', [0.3059, 0.0, 0.25])]
CRYSTAL_DB['Fe2O3'] = {
    'name': 'α-Fe₂O₃ (hematite)',
    'cell': _hexagonal_cell(5.038, 13.772),
    'atoms': _expand_symmetry(_hematite_asym, _hematite_symops),
}

# ── Fe3O4 magnetite (Fd-3m, origin choice 2) ──
# Explicit Wyckoff motifs plus F centering, rather than an incomplete set of
# point rotations (Fd-3m also needs non-symmorphic translations). Origin 2:
# 8a = +/- (1/8,1/8,1/8) + F; 16d = four-site pyrochlore motif + F;
# 32e = (u,u,u), permutations of (u,1/4-u,1/4-u), and inversions + F.
# AUDIT-20261027: tested against independent periodic Fe-O coordination
# (8 tetrahedral / 16 octahedral) and ASE space group 227, setting 2.
_spinel_u = 0.2549
_spinel_tet = [(0.125, 0.125, 0.125), (-0.125, -0.125, -0.125)]
_spinel_oct = [(0.5, 0.5, 0.5), (0.5, 0.75, 0.75),
               (0.75, 0.5, 0.75), (0.75, 0.75, 0.5)]
_spinel_oxygen = [(_spinel_u, _spinel_u, _spinel_u),
                   (_spinel_u, 0.25 - _spinel_u, 0.25 - _spinel_u),
                   (0.25 - _spinel_u, _spinel_u, 0.25 - _spinel_u),
                   (0.25 - _spinel_u, 0.25 - _spinel_u, _spinel_u)]
_spinel_oxygen += [tuple(-v for v in p) for p in _spinel_oxygen]
_magnetite_atoms = [
    (element, ((np.asarray(position) + translation) % 1.0).tolist())
    for element, motif in [('Fe', _spinel_tet), ('Fe', _spinel_oct), ('O', _spinel_oxygen)]
    for position in motif for translation in _fcc_trans
]
CRYSTAL_DB['Fe3O4'] = {
    'name': 'Fe₃O₄ (magnetite)',
    'cell': _cubic_cell(8.396),
    'atoms': _magnetite_atoms,
}


# ═══════════════════════════════════════════════════════════════
# CIF File Parser
# ═══════════════════════════════════════════════════════════════

_CIF_SITE_CONSTRAINTS = ('_atom_site_occupancy', '_atom_site_disorder_assembly',
                         '_atom_site_disorder_group')
# One digit uncertainty may follow the mantissa or the exponent. The fullmatch
# and exact Decimal comparison reject malformed suffixes and values rounded to 1.
_CIF_OCCUPANCY_NUMBER = re.compile(
    r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)'
    r'(?:(?:\([0-9]+\))?(?:[eE][+-]?[0-9]+)?|[eE][+-]?[0-9]+\([0-9]+\))')


def _cif_site_declarations(text, source):
    """Locate unquoted site constraints anywhere in the bounded CIF token stream.

    Tags may share a physical line with other scalar items. Quoted values,
    comments and column-one semicolon text are not declarations. This lexical
    association guard does not interpret other CIF categories or validate them.
    """
    tags = set(_CIF_SITE_CONSTRAINTS)
    tags.update(tag.replace('_atom_site_', '_atom_site.') for tag in _CIF_SITE_CONSTRAINTS)
    declarations = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        start = pos
        if text[pos] == '#':
            end = text.find('\n', pos)
            pos = len(text) if end < 0 else end + 1
            continue
        if text[pos] == ';' and (pos == 0 or text[pos - 1] == '\n'):
            end = text.find('\n;', pos + 1)
            if end >= 0:
                pos = end + 2
                continue
            kind = 'unterminated semicolon text'
        elif text[pos] in ('\"', "'"):
            quote = text[pos]
            pos += 1
            closed = False
            while pos < len(text) and text[pos] not in '\r\n':
                if text[pos] == quote and (pos + 1 == len(text) or text[pos + 1].isspace()):
                    pos += 1
                    closed = True
                    break
                pos += 1
            if closed:
                continue
            kind = 'unterminated quoted value'
        else:
            while pos < len(text) and not text[pos].isspace():
                pos += 1
            token = text[start:pos]
            if token.lower() in tags:
                declarations.append((token, start))
            continue
        lineno = text.count('\n', 0, start) + 1
        tags_seen = ', '.join(dict.fromkeys(tag for tag, _ in declarations)) or 'occupancy/disorder'
        row = text.splitlines()[lineno - 1]
        raise ValueError(f'{source}:{lineno}: unsupported CIF site metadata syntax '
                         f'({tags_seen}): {kind}; row={row!r}')
    return declarations


def _cif_site_fields(line, context):
    """Tokenize one guarded site row, retaining quotes and ignoring inline comments.

    Quoted fields end only at a matching quote followed by whitespace or EOF;
    backslashes are literal, not shell escapes. This handles simple line-based
    CIF fields, not semicolon text or values split over multiple source lines.
    Retained quotes distinguish an unquoted '.' marker from a literal code.
    """
    if line.startswith(';'):
        raise ValueError(f'{context}: unsupported multiline CIF site field; row={line!r}')
    fields = []
    pos = 0
    while pos < len(line):
        while pos < len(line) and line[pos].isspace():
            pos += 1
        if pos == len(line) or line[pos] == '#':
            break
        start = pos
        if line[pos] in ('\"', "'"):
            quote = line[pos]
            pos += 1
            while pos < len(line):
                if line[pos] == quote and (pos + 1 == len(line) or line[pos + 1].isspace()):
                    pos += 1
                    break
                pos += 1
            else:
                raise ValueError(f'{context}: unsupported unterminated quoted field; row={line!r}')
        else:
            while pos < len(line) and not line[pos].isspace():
                pos += 1
        fields.append(line[start:pos])
    return fields


def _cif_unquote(field):
    """Remove one balanced pair of CIF field quotes, leaving marker meaning to callers."""
    if len(field) >= 2 and field[0] in ('\"', "'") and field[-1] == field[0]:
        return field[1:-1]
    return field


def _validate_cif_site_constraints(fields, col_map, context):
    """Require a unit-weight reference site without coded disorder before expansion.

    Missing occupancy retains legacy unit-site compatibility. Explicit nominal
    occupancy must be exactly one in decimal arithmetic: no float rounding or
    tolerance may turn a partial site into a full atom. Digit uncertainties are
    accepted syntactically but are not propagated or used to fit a unit value.
    Coded/unknown disorder is unsupported, not declared physically invalid.
    """
    for tag in _CIF_SITE_CONSTRAINTS:
        if tag not in col_map:
            continue
        raw = fields[col_map[tag]]
        if tag != '_atom_site_occupancy':
            if raw != '.':
                raise ValueError(f'{context}: unsupported {tag}={raw!r}; only an unquoted '
                                 "'.' (not applicable) is supported for disorder")
            continue
        token = _cif_unquote(raw)
        nominal = None
        if _CIF_OCCUPANCY_NUMBER.fullmatch(token):
            try:
                nominal = Decimal(re.sub(r'\([0-9]+\)', '', token))
            except InvalidOperation:
                pass
        if nominal is None or not nominal.is_finite() or nominal != 1:
            raise ValueError(f'{context}: unsupported {tag}={raw!r}; only finite exact '
                             'nominal occupancy 1 is supported; no partial/unknown-site weighting')


def _symop_loop_row(line):
    """Return the operator text of one symmetry-loop row (quotes and id removed)."""
    rest = re.sub(r'^\d+\s+', '', line.strip())
    quoted = re.match(r"""^(?:'([^']*)'|"([^"]*)")""", rest)
    if quoted:
        return quoted.group(1) if quoted.group(1) is not None else quoted.group(2)
    return rest


def parse_cif(source):
    """
    Parse a CIF file to extract crystal structure data.

    Supports:
      - Local file path: parse_cif('/path/to/file.cif')
      - COD ID:          parse_cif('cod:9009768')

    For COD IDs, downloads from http://www.crystallography.net/cod/<ID>.cif.

    Returns a crystal dict compatible with CRYSTAL_DB format:
        {'name': str, 'cell': 3x3 array, 'atoms': [(elem, [fx,fy,fz]), ...]}
    Returns None for a missing source, failed COD fetch, missing cell lengths
    or absent usable atom rows; local file read errors may propagate. Raises
    ValueError for an invalid cell (a present but non-numeric length or angle,
    or lengths/angles that cannot form a cell: 'CIF cell parameters are
    invalid: ...'). Raises ValueError when symmetry cannot be established:
    supply explicit symmetry operations, or declare P1. A named non-P1 group alone is not expanded from
    a space-group database. Unsupported occupancy/disorder or ambiguous guarded
    site input also raises, with source/line and site metadata where available;
    no partially filtered crystal is returned.

    Uses the first atom-site loop with fractional coordinates. Missing occupancy
    retains legacy unit-site compatibility; explicit finite nominal occupancy
    must equal one exactly, including optional digit uncertainty syntax. No
    uncertainty or partial-site weights are propagated. Disorder fields accept
    only the unquoted '.' not-applicable marker, not coded/unknown alternatives.
    Relevant metadata outside the imported loop is rejected rather than ignored.

    Atom-site headers are case-insensitive. Guarded rows require complete simple
    line-based fields (including quotes and inline comments); unguarded rows keep
    the legacy whitespace subset. Numeric coordinate uncertainties are stripped;
    absent angles default to 90 degrees, while a present but non-numeric angle
    raises ValueError. Anisotropic motion, multiple data blocks and
    sophisticated multiline CIF constructs are not interpreted. Symmetry-loop
    matching retains its legacy subset; every symmetry-loop row found is
    validated as an operator (an invalid row raises ValueError), but the
    declared space group is not checked against the operators. Cell lengths
    and angles are validated; fractional coordinates are not range- or
    finiteness-checked here.
    """
    # ── Fetch CIF content ──
    if source.lower().startswith('cod:'):
        cod_id = source.split(':')[1].strip()
        try:
            import urllib.request
            url = f'http://www.crystallography.net/cod/{cod_id}.cif'
            with urllib.request.urlopen(url, timeout=15) as resp:
                cif_text = resp.read().decode('utf-8', errors='replace')
        except Exception as e:
            print(f"  Failed to download COD {cod_id}: {e}")
            return None
    elif os.path.isfile(source):
        with open(source, 'r', errors='replace') as f:
            cif_text = f.read()
    else:
        print(f"  CIF source not found: {source}")
        return None

    # ── Parse CIF fields ──
    def _get_value(tag):
        """Read the first scalar tag value, accepting simple quoted tokens.

        Matching is case-insensitive and line-based; a missing tag yields None.
        This helper does not decode CIF semicolon-delimited multiline fields.
        """
        pattern = rf'''^\s*{re.escape(tag)}\s+('([^']*)'|"([^"]*)"|([^\s#]+))'''
        m = re.search(pattern, cif_text, re.MULTILINE | re.IGNORECASE)
        return next((v for v in m.groups()[1:] if v is not None), None) if m else None

    def _strip_uncertainty(val_str):
        """Convert a CIF number without its parenthetical uncertainty suffix.

        Missing/unparseable values (including CIF '.' and '?') return None,
        leaving callers to distinguish required fields from optional defaults.
        """
        if val_str is None:
            return None
        val_str = re.sub(r'\([^)]*\)', '', val_str)
        try:
            return float(val_str)
        except ValueError:
            return None

    # Cell parameters. An absent length is reported as missing (None result,
    # as before); an absent angle takes the conventional 90 degrees. A tag
    # that is present but not a number (including the CIF unknown markers
    # '.' and '?') and any geometrically invalid value raise ValueError, so a
    # wrong cell is never built silently.
    def _cell_param(tag, default=None):
        """Return the CIF cell tag as a float with any uncertainty stripped, or
        ``default`` when the tag is absent; raise ValueError when the tag is
        present but not a number."""
        raw = _get_value(tag)
        if raw is None:
            return default
        value = _strip_uncertainty(raw)
        if value is None:
            raise ValueError(f'CIF {tag} value {raw!r} is not a number')
        return value

    a = _cell_param('_cell_length_a')
    b = _cell_param('_cell_length_b')
    c = _cell_param('_cell_length_c')
    alpha = _cell_param('_cell_angle_alpha', 90.0)
    beta = _cell_param('_cell_angle_beta', 90.0)
    gamma = _cell_param('_cell_angle_gamma', 90.0)

    if a is None or b is None or c is None:
        print("  CIF: Missing cell parameters.")
        return None

    try:
        cell = _cell_from_params(a, b, c, alpha, beta, gamma)
    except ValueError as exc:
        raise ValueError(f'CIF cell parameters are invalid: {exc}') from None

    # Chemical name
    name = _get_value('_chemical_name_mineral') or _get_value('_chemical_formula_sum') or source

    # ── Parse atom_site loop ──
    # Bind explicit site constraints to the imported loop. A scalar, orphan or
    # second-loop declaration has no established association with these atoms;
    # refusing it is safer than silently assuming every imported site is full.
    site_constraints = _cif_site_declarations(cif_text, source)
    # Header-driven indices allow column reordering. Legacy unguarded rows retain
    # their whitespace subset; constrained rows must not disappear on a skip.
    # Find the loop_ block containing _atom_site_fract_x
    atom_labels = []
    atom_types = []
    frac_x = []
    frac_y = []
    frac_z = []

    # Find loop block
    loop_pattern = re.compile(
        r'^[ \t]*loop_\s+((?:_atom_site_\S+\s*)+)'
        r'((?:(?![ \t]*(?:loop_(?=\s|$)|_[a-z])).*\n?)*)',
        re.MULTILINE | re.IGNORECASE
    )

    for m in loop_pattern.finditer(cif_text):
        header_block = m.group(1)
        data_block = m.group(2)

        if '_atom_site_fract_x' not in header_block.lower():
            continue

        # Normalize tag names before discovering constraints: mixed-case metadata
        # must not become an ignored extra column beside lowercase coordinates.
        columns = [tag.lower() for tag in re.findall(
            r'(_atom_site_\S+)', header_block, re.IGNORECASE)]
        col_map = {tag: i for i, tag in enumerate(columns)}

        idx_label = col_map.get('_atom_site_label')
        idx_type = col_map.get('_atom_site_type_symbol')
        idx_fx = col_map.get('_atom_site_fract_x')
        idx_fy = col_map.get('_atom_site_fract_y')
        idx_fz = col_map.get('_atom_site_fract_z')

        if idx_fx is None or idx_fy is None or idx_fz is None:
            continue

        for tag, position in site_constraints:
            if not m.start(1) <= position < m.end(1):
                lineno = cif_text.count('\n', 0, position) + 1
                row = cif_text.splitlines()[lineno - 1]
                raise ValueError(f'{source}:{lineno}: unsupported CIF {tag} placement; '
                                 'occupancy/disorder metadata must belong to the first '
                                 f'imported fractional atom-site loop; row={row!r}')
        guarded = any(tag in col_map for tag in _CIF_SITE_CONSTRAINTS)
        if guarded and len(columns) != len(col_map):
            lineno = cif_text.count('\n', 0, m.start(1)) + 1
            duplicates = sorted({tag for tag in columns if columns.count(tag) > 1})
            raise ValueError(f'{source}:{lineno}: ambiguous CIF occupancy/disorder '
                             f'atom-site header: duplicate columns {duplicates!r}')

        # Validate constraints before element/coordinate filtering or expansion.
        # An otherwise unusable row must not conceal a partial or unknown site.
        first_line = cif_text.count('\n', 0, m.start(2)) + 1
        for lineno, line in enumerate(data_block.splitlines(), first_line):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if guarded:
                tag = next(tag for tag in _CIF_SITE_CONSTRAINTS if tag in col_map)
                context = f'{source}:{lineno}: CIF site row with {tag}'
                fields = _cif_site_fields(line, context)
                if len(fields) != len(columns):
                    raise ValueError(f'{context}: malformed guarded row; expected '
                                     f'{len(columns)} fields, got {len(fields)}; row={line!r}')
                parts = [_cif_unquote(field) for field in fields]
                idx_site = idx_label if idx_label is not None else idx_type
                site = parts[idx_site] if idx_site is not None else '<unlabelled>'
                _validate_cif_site_constraints(fields, col_map,
                                              f'{source}:{lineno}: CIF site {site!r}')
            else:
                if line.startswith('_') or line.startswith('loop'):
                    continue  # Preserve the legacy unguarded whitespace subset.
                parts = line.split()
                if len(parts) < len(columns):
                    continue

            # Element symbol: prefer type_symbol, fall back to label
            if idx_type is not None:
                elem = re.sub(r'[^A-Za-z]', '', parts[idx_type])
            elif idx_label is not None:
                elem = re.sub(r'[^A-Za-z]', '', parts[idx_label])
            else:
                continue

            # Capitalize properly
            elem = elem[0].upper() + elem[1:].lower() if len(elem) > 1 else elem.upper()

            fx = _strip_uncertainty(parts[idx_fx])
            fy = _strip_uncertainty(parts[idx_fy])
            fz = _strip_uncertainty(parts[idx_fz])

            if fx is not None and fy is not None and fz is not None:
                atom_labels.append(elem)
                frac_x.append(fx)
                frac_y.append(fy)
                frac_z.append(fz)

        break  # Use first matching loop

    if not atom_labels:
        print("  CIF: No atom positions found.")
        return None

    # ── Parse symmetry operations ──
    symops = []
    # Try _symmetry_equiv_pos_as_xyz or _space_group_symop_operation_xyz
    for tag in ['_symmetry_equiv_pos_as_xyz', '_space_group_symop_operation_xyz']:
        symop_pattern = re.compile(
            rf'loop_\s*(?:_\S+\s*)*{re.escape(tag)}\s*((?:(?!loop_|_[a-z]).*\n?)*)',
            re.MULTILINE
        )
        m = symop_pattern.search(cif_text)
        if m:
            data = m.group(1)
            for line in data.strip().split('\n'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Row formats: "1 'x, y, z'", "'x, y, z'", "x, y, z". A quoted
                # operator may be followed by further loop columns; an
                # unquoted one is the rest of the row. Every row must be a
                # valid operator: nothing is skipped silently.
                op = _symop_loop_row(line)
                try:
                    _parse_symop(op)
                except ValueError as exc:
                    raise ValueError(f'CIF symmetry loop ({tag}) row {line!r} is not a '
                                     f'valid operator: {exc}') from None
                symops.append(op)
            break

    if not symops:
        # Coordinates in a CIF normally describe an asymmetric unit. Missing
        # operations are NOT evidence of identity symmetry/full-cell positions.
        numbers = [_get_value(tag) for tag in
                   ('_space_group_IT_number', '_symmetry_Int_Tables_number')]
        names = [_get_value(tag) for tag in
                 ('_space_group_name_H-M_alt', '_symmetry_space_group_name_H-M',
                  '_space_group_name_Hall')]
        declared = [v for v in numbers + names if v not in (None, '?', '.')]
        p1 = ([v.strip() == '1' for v in numbers if v not in (None, '?', '.')]
              + [re.sub(r'\s+', '', v).lower() == 'p1'
                 for v in names if v not in (None, '?', '.')])
        if not declared or not all(p1):
            raise ValueError('CIF symmetry is missing: explicit symmetry operations '
                             'are required unless the declared space group is P1; '
                             'cannot treat an asymmetric unit as a full cell.')
        symops = ['x, y, z']

    # Build asymmetric unit atom list
    asym_atoms = [(elem, [fx, fy, fz])
                  for elem, fx, fy, fz in zip(atom_labels, frac_x, frac_y, frac_z)]

    # Only explicit operations (or the P1 identity established above) define
    # full-cell positions; an asymmetric unit must not masquerade as a full cell.
    expanded = _expand_symmetry(asym_atoms, symops)

    return {
        'name': name.strip("'\""),
        'cell': cell,
        'atoms': expanded,
    }


# ═══════════════════════════════════════════════════════════════
# Reference RDF Computation
# ═══════════════════════════════════════════════════════════════

def _lattice_image_offsets(cell, r_max):
    """Integer lattice translations that can bring a site pair within r_max.

    The displacement between two sites is ``(f + n) @ cell`` with the
    fractional difference ``f`` wrapped to [-0.5, 0.5] and ``n`` an integer
    vector. Its component along the normal of the plane spanned by the other
    two lattice vectors is ``(f_i + n_i) * w_i``, where ``w_i = V / |a_j x a_k|``
    is the perpendicular width of the cell along lattice direction i. A
    distance below r_max therefore needs ``|n_i| < r_max / w_i + 1/2`` on every
    axis, so the box ``|n_i| <= ceil(r_max / w_i + 1/2)`` contains every image
    that can contribute, for any cell shape. Raises ValueError for a cell that
    is not a finite 3x3 matrix, for a singular cell (whose widths are
    undefined) and for a non-positive or non-finite r_max.
    """
    cell = np.asarray(cell, dtype=float)
    if cell.shape != (3, 3) or not np.all(np.isfinite(cell)):
        raise ValueError('reference cell must be a finite 3x3 matrix of lattice-vector rows')
    volume = abs(float(np.linalg.det(cell)))
    if volume <= 0.0:
        raise ValueError('reference cell is singular (zero volume); periodic images cannot be enumerated')
    if not np.isfinite(r_max) or r_max <= 0.0:
        raise ValueError(f'r_max must be a positive distance, got {r_max!r}')
    widths = np.array([volume / np.linalg.norm(np.cross(cell[(i + 1) % 3], cell[(i + 2) % 3]))
                       for i in range(3)])
    bounds = np.ceil(r_max / widths + 0.5).astype(int)
    grids = np.meshgrid(*[np.arange(-m, m + 1) for m in bounds], indexing='ij')
    return np.stack([g.ravel() for g in grids], axis=1)


def compute_reference_rdf(phase_or_crystal, pair=('Fe', 'O'), r_max=6.0, n_bins=200):
    """
    Compute the ideal g(r) from a crystal structure.

    Every element-A site of the unit cell is paired with every periodic image
    of every element-B site closer than r_max. The images are enumerated
    exactly from the cell's perpendicular widths (``_lattice_image_offsets``),
    so every neighbour shell inside the cutoff is complete for any cutoff and
    any cell shape, including hexagonal and triclinic cells. No supercell,
    minimum-image convention or half-cell restriction is involved, and the
    unit cell is used as is: a cutoff larger than the cell simply enumerates
    more images. A singular cell raises ValueError.

    Directed element-A to element-B distances are histogrammed and normalized
    by N_A times spherical-shell volume times N_B/V. Thus identical-element
    pairs retain both directions; separations <= 0.01 Å (including self pairs)
    and >= r_max are excluded. The ideal static lattice has sharp bin-dependent
    peaks, not a thermally broadened experimental RDF. All pairs use N_B/V,
    not (N_B-1)/V for identical elements.

    Args:
        phase_or_crystal: str (key in CRYSTAL_DB) or dict (from parse_cif)
        pair:      tuple — (element_a, element_b) for the RDF pair
        r_max:     float — Maximum radial distance (Å)
        n_bins:    int — Number of histogram bins

    Returns:
        dict: {'r', 'g', 'label', 'phase'} or None if the phase name is
        unknown, the argument is neither a str nor a dict, or either element
        of the pair is absent
    """
    if isinstance(phase_or_crystal, str):
        if phase_or_crystal not in CRYSTAL_DB:
            return None
        crystal = CRYSTAL_DB[phase_or_crystal]
        phase_key = phase_or_crystal
    elif isinstance(phase_or_crystal, dict):
        crystal = phase_or_crystal
        phase_key = crystal.get('name', 'custom')
    else:
        return None

    cell = np.asarray(crystal['cell'], dtype=float)
    atoms_list = crystal['atoms']
    elements = np.array([elem for elem, _ in atoms_list], dtype=object)
    frac_all = np.array([frac for _, frac in atoms_list], dtype=float).reshape(-1, 3)

    elem_a, elem_b = pair
    frac_a = frac_all[elements == elem_a]
    frac_b = frac_all[elements == elem_b]
    if len(frac_a) == 0 or len(frac_b) == 0:
        return None

    offsets = _lattice_image_offsets(cell, r_max)
    vol = abs(float(np.linalg.det(cell)))

    dr = r_max / n_bins
    hist = np.zeros(n_bins)

    for fa in frac_a:
        # Wrap the fractional difference to [-0.5, 0.5]; the enumerated
        # integer offsets then cover every image inside the cutoff.
        frac_d = frac_b - fa
        frac_d -= np.round(frac_d)
        d = (frac_d[:, None, :] + offsets[None, :, :]) @ cell
        r = np.linalg.norm(d, axis=2).ravel()
        valid = (r > 0.01) & (r < r_max)
        bi = (r[valid] / dr).astype(int)
        bi = bi[bi < n_bins]
        np.add.at(hist, bi, 1)

    # Normalize to g(r)
    bins_edge = np.linspace(0, r_max, n_bins + 1)
    r_centers = (bins_edge[:-1] + bins_edge[1:]) / 2
    shell_vol = (4 / 3) * np.pi * (bins_edge[1:] ** 3 - bins_edge[:-1] ** 3)
    rho_b = len(frac_b) / vol
    g = hist / (len(frac_a) * shell_vol * rho_b)

    return {
        'r': r_centers,
        'g': g,
        'label': crystal['name'],
        'phase': phase_key,
    }


def get_available_phases():
    """Return built-in (lookup key, display name) pairs in database order.

    CIF structures are caller-owned dictionaries and do not enter this registry.
    """
    return [(k, v['name']) for k, v in CRYSTAL_DB.items()]


def get_phases_for_pair(pair=('Fe', 'O')):
    """List built-in keys containing both exact element labels in pair.

    This filters compositional eligibility only; it does not score an RDF match
    or establish a phase assignment. Identical-element pairs need that one
    element present, and no matching entries yields an empty list.
    """
    result = []
    elem_a, elem_b = pair
    for key, crystal in CRYSTAL_DB.items():
        elements_in_crystal = set(e for e, _ in crystal['atoms'])
        if elem_a in elements_in_crystal and elem_b in elements_in_crystal:
            result.append(key)
    return result
