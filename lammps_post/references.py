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
  B. CIF file import  — parse any .cif file (COD, ICSD, etc.)

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
occupancies/disorder, arbitrary CIF syntax and general symmetry algebra are
not modeled. Built-in cells describe ideal periodic positions without thermal
motion, defects, spin assignments or force-field-dependent relaxation.
═══════════════════════════════════════════════════════════════
"""

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

    Place a along x and b in the xy plane, choosing nonnegative c_z. alpha,
    beta and gamma are respectively the b-c, a-c and a-b angles. The square
    root clips a negative residual to zero; this is not a general validation
    of physically valid cell parameters, and degenerate cells remain unusable.
    """
    alpha_r = np.radians(alpha)
    beta_r = np.radians(beta)
    gamma_r = np.radians(gamma)

    cos_a, cos_b, cos_g = np.cos(alpha_r), np.cos(beta_r), np.cos(gamma_r)
    sin_g = np.sin(gamma_r)

    v2 = b * cos_g
    v3 = b * sin_g
    w2 = c * cos_b
    w3 = c * (cos_a - cos_b * cos_g) / sin_g
    w4 = np.sqrt(max(0, c**2 - w2**2 - w3**2))

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


def _apply_symop(symop_str, frac):
    """
    Apply a symmetry operation string (e.g., '-x, y+1/2, -z+1/2') to
    fractional coordinates. Returns new fractional position.

    Recognize signed coordinate terms and numeric/fractional translations
    through tokenization, not eval. This handles the conventional simple xyz
    expressions used by the built-ins, but is not an arbitrary expression
    parser or syntax validator. Wrapping and duplicate handling belong to
    _expand_symmetry, so the result here may lie outside the unit cell.
    """
    result = np.zeros(3)
    parts = [s.strip() for s in symop_str.split(',')]

    for i, part in enumerate(parts):
        val = 0.0
        # Parse each term in the expression
        part = part.replace(' ', '')
        # Handle fractions like 1/2, 1/4, 3/4
        tokens = re.findall(r'[+-]?(?:\d+/\d+|[xyz]|\d+\.?\d*)', part)

        for token in tokens:
            if 'x' in token:
                coeff = token.replace('x', '')
                if coeff in ('', '+'):
                    coeff = 1.0
                elif coeff == '-':
                    coeff = -1.0
                else:
                    coeff = float(coeff)
                val += coeff * frac[0]
            elif 'y' in token:
                coeff = token.replace('y', '')
                if coeff in ('', '+'):
                    coeff = 1.0
                elif coeff == '-':
                    coeff = -1.0
                else:
                    coeff = float(coeff)
                val += coeff * frac[1]
            elif 'z' in token:
                coeff = token.replace('z', '')
                if coeff in ('', '+'):
                    coeff = 1.0
                elif coeff == '-':
                    coeff = -1.0
                else:
                    coeff = float(coeff)
                val += coeff * frac[2]
            elif '/' in token:
                num, den = token.split('/')
                val += float(num) / float(den)
            elif token:
                try:
                    val += float(token)
                except ValueError:
                    pass

        result[i] = val

    return result


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
    """
    all_atoms = []
    seen = set()

    for elem, frac in asym_atoms:
        for op in symops:
            new_frac = _apply_symop(op, np.array(frac, dtype=float))
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
    ValueError when symmetry cannot be established: supply explicit symmetry
    operations, or declare P1. A named non-P1 group alone is not expanded from
    a space-group database.

    Uses the first atom-site loop with fractional coordinates, strips numeric
    parenthetical uncertainties and defaults absent/unusable angles to 90
    degrees. Atom rows are whitespace-split; occupancies, anisotropic motion,
    multiple data blocks and sophisticated multiline/quoted CIF constructs
    are not interpreted. The caller must judge the suitability of such input
    as a fully occupied ideal reference before drawing structural conclusions.
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

    # Cell parameters
    a = _strip_uncertainty(_get_value('_cell_length_a'))
    b = _strip_uncertainty(_get_value('_cell_length_b'))
    c = _strip_uncertainty(_get_value('_cell_length_c'))
    alpha = _strip_uncertainty(_get_value('_cell_angle_alpha')) or 90.0
    beta = _strip_uncertainty(_get_value('_cell_angle_beta')) or 90.0
    gamma = _strip_uncertainty(_get_value('_cell_angle_gamma')) or 90.0

    if a is None or b is None or c is None:
        print("  CIF: Missing cell parameters.")
        return None

    cell = _cell_from_params(a, b, c, alpha, beta, gamma)

    # Chemical name
    name = _get_value('_chemical_name_mineral') or _get_value('_chemical_formula_sum') or source

    # ── Parse atom_site loop ──
    # Header-driven indices allow column reordering. This lightweight reader
    # skips incomplete/unusable rows rather than validating the entire CIF.
    # Find the loop_ block containing _atom_site_fract_x
    atom_labels = []
    atom_types = []
    frac_x = []
    frac_y = []
    frac_z = []

    # Find loop block
    loop_pattern = re.compile(
        r'loop_\s*((?:_atom_site_\S+\s*)+)((?:(?!loop_|_[a-z]).*\n?)*)',
        re.MULTILINE
    )

    for m in loop_pattern.finditer(cif_text):
        header_block = m.group(1)
        data_block = m.group(2)

        if '_atom_site_fract_x' not in header_block:
            continue

        # Parse column order from header
        columns = re.findall(r'(_atom_site_\S+)', header_block)
        col_map = {c: i for i, c in enumerate(columns)}

        idx_label = col_map.get('_atom_site_label')
        idx_type = col_map.get('_atom_site_type_symbol')
        idx_fx = col_map.get('_atom_site_fract_x')
        idx_fy = col_map.get('_atom_site_fract_y')
        idx_fz = col_map.get('_atom_site_fract_z')

        if idx_fx is None or idx_fy is None or idx_fz is None:
            continue

        # Parse data rows
        for line in data_block.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('_') or line.startswith('loop'):
                continue
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
                # Extract the symmetry operation (may have a number prefix)
                # Format: "1 'x, y, z'" or "'x, y, z'" or "x, y, z"
                op = re.sub(r"^\d+\s+", '', line)  # Remove leading number
                op = op.strip("'\"")
                if ',' in op:
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

def compute_reference_rdf(phase_or_crystal, pair=('Fe', 'O'), r_max=6.0,
                          n_bins=200, supercell=(4, 4, 4)):
    """
    Compute the ideal g(r) from a crystal structure.

    Replicate row-vector unit cells, histogram directed element-A to element-B
    distances and normalize by N_A times spherical-shell volume times N_B/V.
    Thus identical-element pairs retain both directions; separations <= 0.01 Å
    (including self pairs) and >= r_max are excluded. The ideal static lattice
    has sharp bin-dependent peaks, not a thermally broadened experimental RDF.

    Periodicity is applied in all three dimensions by rounding fractional
    displacements in the supercell basis. This is componentwise fractional
    wrapping, not a general closest-lattice-vector search for arbitrarily skew
    cells. Supply a suitable cell/supercell and cutoff so intended neighbor
    shells are represented without missing repeated images. No finite-boundary
    shell correction, automatic replication-size choice or input validation
    of these geometric assumptions is performed.

    Args:
        phase_or_crystal: str (key in CRYSTAL_DB) or dict (from parse_cif)
        pair:      tuple — (element_a, element_b) for the RDF pair
        r_max:     float — Maximum radial distance (Å)
        n_bins:    int — Number of histogram bins
        supercell: tuple — (nx, ny, nz) supercell dimensions

    Returns:
        dict: {'r', 'g', 'label', 'phase'} or None if failed
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

    cell = np.array(crystal['cell'])
    atoms_list = crystal['atoms']

    nx, ny, nz = supercell
    supercell_matrix = cell * np.array([[nx], [ny], [nz]])

    # Scale each lattice-vector row independently. Dividing translated unit-cell
    # fractions by replication counts expresses positions in that larger basis.
    # Build supercell positions
    all_positions = []
    all_elements = []

    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                for elem, frac in atoms_list:
                    frac = np.array(frac, dtype=float)
                    # Shift to supercell image
                    shifted = (frac + np.array([ix, iy, iz])) / np.array([nx, ny, nz])
                    # Fractional -> Cartesian in supercell
                    cart = shifted @ supercell_matrix
                    all_positions.append(cart)
                    all_elements.append(elem)

    all_positions = np.array(all_positions)
    all_elements = np.array(all_elements)

    vol = abs(np.linalg.det(supercell_matrix))
    inv_cell = np.linalg.inv(supercell_matrix)

    # Select atom types
    elem_a, elem_b = pair
    mask_a = all_elements == elem_a
    mask_b = all_elements == elem_b
    pos_a = all_positions[mask_a]
    pos_b = all_positions[mask_b]

    if len(pos_a) == 0 or len(pos_b) == 0:
        return None

    # Compute pairwise distances with minimum image convention
    # Work in the lattice basis so the reference does not discard hexagonal or
    # other oblique cell angles. Componentwise wrapping has the skew-cell
    # limitation documented above; it is not a universal triclinic MIC solver.
    dr = r_max / n_bins
    hist = np.zeros(n_bins)

    for p in pos_a:
        d = pos_b - p
        frac_d = d @ inv_cell
        frac_d -= np.round(frac_d)
        d = frac_d @ supercell_matrix
        r = np.linalg.norm(d, axis=1)
        valid = (r > 0.01) & (r < r_max)
        bi = (r[valid] / dr).astype(int)
        bi = bi[bi < n_bins]
        np.add.at(hist, bi, 1)

    # Normalize to g(r)
    bins_edge = np.linspace(0, r_max, n_bins + 1)
    r_centers = (bins_edge[:-1] + bins_edge[1:]) / 2
    shell_vol = (4 / 3) * np.pi * (bins_edge[1:] ** 3 - bins_edge[:-1] ** 3)
    rho_b = len(pos_b) / vol
    g = hist / (len(pos_a) * shell_vol * rho_b)

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
