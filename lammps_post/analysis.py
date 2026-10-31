"""
═══════════════════════════════════════════════════════════════
Section 3: Analysis Functions
═══════════════════════════════════════════════════════════════
Numerical analyses that take parsed data and return result dictionaries.
Most species selections accept explicit type unions; the spin analysis
deliberately retains the ACE domain mapping. Missing optional charge data
returns None, while invalid geometry or atom identity raises where checked.

Time-series results use picoseconds, assuming caller-supplied dt_fs is valid
for the represented steps. Most population analyses use absolute dump steps;
MSD and the ID-resolved penetration profile instead start at the first frame.
Spatial analyses assume Angstrom coordinates. Position-based slab metrics
use the supplied z coordinates without unwrapping or following a moving
surface unless explicitly stated. Empty-selection behavior is metric-specific.
These routines do not infer or convert units; caller/reader metadata must supply
literal Cartesian columns, valid types and the intended timestep convention.
Validation is local to each metric, not a general certification of input data.

Dependencies:
  Required : numpy
  Optional : scipy.spatial.cKDTree (loaded when finding RDF/O2 candidates)
═══════════════════════════════════════════════════════════════
"""

import itertools
import warnings

import numpy as np

from lammpkeeper.common.mapping import label_to_type
from lammpkeeper.io import Box
from lammpkeeper.core.geometry import minimum_image, to_fractional
from lammps_post import (Q_OXIDIZED_E, SURFACE_OFFSET_A, NEAR_SURFACE_A,
                         O2_BOND_CUTOFF_A)


def _type_ids(selection, name):
    """Return a nonempty immutable union of positive integer type IDs.

    Reject booleans rather than accepting their integer representation. Repeated
    IDs collapse to one member; no element or force-field inference is attempted.
    ``name`` identifies the caller's selection in validation errors.
    """
    if isinstance(selection, (int, np.integer)):
        members = [selection]
    else:
        try:
            members = list(selection)
        except TypeError:
            raise ValueError(f'{name} must be an integer or iterable of type IDs') from None
    if not members or any(isinstance(t, (bool, np.bool_))
                          or not isinstance(t, (int, np.integer)) or t <= 0
                          for t in members):
        raise ValueError(f'{name} must contain positive integer type IDs')
    return frozenset(map(int, members))


def _typed_cell(frame, analysis):
    """Validate an explicit Box and all retained compatibility geometry copies.

    Bare legacy bounds/tilt never opt into triclinic interpretation. Exact
    agreement is required: compatibility arrays describe the very same cell,
    not an independently fitted or approximately equivalent lattice. A retained
    ``triclinic`` boolean claims nonorthogonal geometry, not format provenance.
    Numerical analyses also enforce the core geometry's condition/scale limits
    and a representable inverse volume; extreme valid metadata is not permission
    to publish overflowed distances or density normalization.
    """
    if 'cell' not in frame:
        return None
    cell = frame['cell']
    context = f"{analysis} timestep {frame['timestep']}"
    if not isinstance(cell, Box):
        raise ValueError(f'{context}: cell must be a Box')
    bounds = np.asarray(cell.bounds, dtype=float)
    matrix = np.asarray(cell.matrix, dtype=float)
    if (bounds.shape != (3, 2) or matrix.shape != (3, 3)
            or not np.all(np.isfinite(bounds)) or not np.all(np.isfinite(matrix))
            or not np.isfinite(cell.volume) or cell.volume <= 0):
        raise ValueError(f'{context}: cell geometry must be finite and positive')
    if 'box' in frame:
        legacy = np.asarray(frame['box'], dtype=float)
        if legacy.shape != (3, 2) or not np.array_equal(legacy, bounds):
            raise ValueError(f'{context}: cell and compatibility box bounds disagree')
    for key in ('tilt', 'tilt_factors'):
        if key in frame:
            retained = np.asarray(frame[key], dtype=float)
            if retained.shape != (3,) or not np.array_equal(retained, cell.tilt):
                raise ValueError(f'{context}: cell and retained {key} disagree')
    for dim, key in enumerate(('xy', 'xz', 'yz')):
        if key in frame:
            retained = np.asarray(frame[key], dtype=float)
            if retained.shape != () or retained != cell.tilt[dim]:
                raise ValueError(f'{context}: cell and retained {key} disagree')
    if 'triclinic' in frame:
        marker = frame['triclinic']
        if not isinstance(marker, (bool, np.bool_)):
            raise ValueError(f'{context}: retained triclinic flag must be a boolean scalar')
        if bool(marker) != (not cell.is_orthogonal):
            raise ValueError(f'{context}: cell and retained triclinic flag disagree')
    try:
        # The empty public transform validates the whole basis without using
        # PBC, transforming atom coordinates or changing orthogonal arithmetic.
        to_fractional(np.empty((0, 3), dtype=np.float64), cell)
    except ValueError as exc:
        raise ValueError(f'{context}: unsupported numerical geometry: {exc}') from exc
    with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
        inverse_volume = np.float64(1.0) / cell.volume
    if not np.isfinite(inverse_volume):
        raise ValueError(f'{context}: geometry volume is too small for finite density normalization')
    return cell


def _cell_periodic(cell, explicit, fallback, analysis):
    """Resolve typed PBC without guessing unknown triclinic boundary flags.

    ``fallback`` is caller-owned legacy policy, used only for absent cells or
    orthogonal cells with unresolved flags. An explicit mask cannot resolve an
    unknown tilted cell here: the authoritative Box must first be updated.
    Orthogonal RDF's historical z-only override is handled by its caller.
    """
    if cell is None:
        return fallback
    if cell.pbc is None:
        if not cell.is_orthogonal:
            raise ValueError(f'{analysis}: triclinic Box PBC is unresolved')
        return fallback
    if explicit is not None and tuple(explicit) != tuple(cell.pbc):
        raise ValueError(f'{analysis}: explicit PBC and Box PBC disagree')
    return tuple(cell.pbc)


def _guard_slab_frame(frame, analysis):
    """Reject unsupported typed or retained tilted slab geometry visibly.

    Bare legacy frames without tilt retain their old coordinate-only path;
    this helper does not validate every such frame's bounds or z values.
    """
    if ('cell' in frame or frame.get('triclinic', False)
            or any(key in frame for key in ('tilt', 'tilt_factors', 'xy', 'xz', 'yz'))):
        _orthogonal_box(frame, analysis)


def _orthogonal_box(frame, analysis):
    """Return finite orthogonal bounds and their three positive side lengths.

    Check both the bounds shape and retained tilt metadata: a (3, 2) bounds
    array alone does not prove orthogonality. Tilt already discarded upstream
    cannot be recovered here. ``analysis`` supplies context for visible errors.
    """
    cell = _typed_cell(frame, analysis)
    box = np.asarray(frame['box'] if 'box' in frame else cell.bounds, dtype=float)
    tilted = any(np.any(np.asarray(frame.get(key, 0), dtype=float) != 0)
                 for key in ('tilt', 'tilt_factors', 'xy', 'xz', 'yz'))
    if (box.shape != (3, 2) or tilted or (cell is not None and not cell.is_orthogonal)
            or (cell is None and frame.get('triclinic', False))):
        raise ValueError(f"{analysis} timestep {frame['timestep']}: requires orthogonal (3, 2) "
                         'bounds; triclinic geometry is unsupported')
    lengths = box[:, 1] - box[:, 0]
    if not np.all(np.isfinite(box)) or not np.all(np.isfinite(lengths)) or np.any(lengths <= 0):
        raise ValueError(f"{analysis} timestep {frame['timestep']}: box lengths must be finite and positive")
    return box, lengths


def _require_finite_charges(charges, frame, analysis):
    """Reject nonfinite contributing charges; keep empty selections valid."""
    if not np.all(np.isfinite(charges)):
        raise ValueError(f"{analysis} timestep {frame.get('timestep', 'unknown')}: "
                         'selected charges contain nonfinite values (NaN/Inf)')


def analyze_charge_evolution(frames, col_idx, dt_fs=0.25, z_range=None, q_thr=Q_OXIDIZED_E,
                             fe_type=1):
    """
    Track the evolution of Fe atomic partial charges over time.
    Intended for ReaxFF partial charges; mechanically requires only a 'q' column.

    In ReaxFF simulations, Fe atoms gain positive charge upon oxidation.
    This function tracks:
    - Average Fe charge within each frame
    - Maximum Fe charge (most oxidized atom)
    - Count and fraction of "oxidized" Fe atoms (charge > q_thr)

    The default charge cutoff is a domain heuristic, not a formal oxidation
    state or a phase classifier; partial charges depend on the force field.
    Selection is repeated per frame, so type changes and slab entry/exit alter
    the population. Empty selections produce zero statistics and fractions.
    A requested z restriction requires a z column; otherwise ValueError is raised
    before consuming frames, even when charge data are absent.
    Slab endpoints are inclusive; charges equal to q_thr are not oxidized.
    Without a z restriction neither a Box nor orthogonality is required.
    Nonfinite charges in the selected type/slab population raise ValueError.

    Args:
        frames:  list[dict] — Parsed trajectory frames from parse_dump
        col_idx: dict       — Column name -> index mapping
        dt_fs:   float      — Timestep in femtoseconds (0.25 for ReaxFF)
        z_range: tuple or None — (zlo, zhi) to restrict analysis to a z-slab
        q_thr:   float      — Charge threshold for "oxidized" classification (e)
        fe_type: int or iterable[int] — Explicit metal species type(s).

    Returns:
        dict with keys:
            'time'         : np.array — Time in picoseconds
            'avg'          : np.array — Average Fe charge per frame
            'max'          : np.array — Maximum Fe charge per frame
            'n_oxidized'   : np.array — Count of Fe atoms with q > q_thr
            'n_total_fe'   : np.array — Total Fe atom count per frame
            'frac_oxidized': np.array — Fraction of oxidized Fe atoms
        Returns None if no charge column is found.
    """
    zi = col_idx.get('z')    # z-coordinate column index
    if z_range is not None and zi is None:
        raise ValueError("Charge evolution region z_range requires a 'z' column")
    qi = col_idx.get('q')    # Column presence, not force-field identification
    ti = col_idx['type']     # Atom type column index
    if qi is None:
        if z_range is not None:
            for fr in frames:
                _guard_slab_frame(fr, 'Charge z restriction')
        return None  # No charge data; absence alone does not identify a force field

    fe_types = _type_ids(fe_type, 'fe_type')
    time, avg, mx, n_ox, n_fe = [], [], [], [], []
    for fr in frames:
        if z_range is not None:
            _guard_slab_frame(fr, 'Charge z restriction')
        atoms = fr['atoms']
        # Select Fe atoms (type 1 in standard ReaxFF Fe-O systems)
        fe_mask = np.isin(atoms[:, ti], list(fe_types))
        # Optionally restrict to a z-slab (e.g., surface region only)
        if z_range is not None and zi is not None:
            z = atoms[:, zi]
            fe_mask &= (z >= z_range[0]) & (z <= z_range[1])
        qs = atoms[fe_mask, qi]  # Charges of selected Fe atoms
        _require_finite_charges(qs, fr, 'Charge evolution')
        n_fe_total = len(qs)
        # Convert timestep to picoseconds: step * dt_fs / 1000
        time.append(fr['timestep'] * dt_fs / 1000)
        n_fe.append(n_fe_total)
        if n_fe_total > 0:
            avg.append(np.mean(qs))
            mx.append(np.max(qs))
            n_ox.append(int(np.sum(qs > q_thr)))  # Count oxidized Fe
        else:
            avg.append(0); mx.append(0); n_ox.append(0)

    n_ox = np.array(n_ox)
    n_fe = np.array(n_fe)
    # Safe division: avoid division by zero when no Fe atoms are in the region
    frac_ox = np.divide(n_ox, n_fe, where=n_fe > 0, out=np.zeros(len(n_ox), dtype=float))

    return {'time': np.array(time), 'avg': np.array(avg),
            'max': np.array(mx), 'n_oxidized': n_ox,
            'n_total_fe': n_fe, 'frac_oxidized': frac_ox}


def analyze_charge_z(frame, col_idx, z_bins=50, fe_type=1, o_type=2):
    """
    Compute the z-direction charge distribution for a single frame.
    Intended for ReaxFF partial charges; requires the 'q' column.

    Divides the simulation box along the z-axis into bins and computes:
    - Average Fe charge in each bin (shows where oxidation is occurring)
    - O atom count in each bin (shows O penetration profile)

    Charge/count overlap can highlight candidate reaction regions, but does
    not establish bonding or an oxide phase. Coordinates are binned as supplied;
    bins exclude the upper box boundary with the digitize convention used here.
    Empty metal bins report zero mean charge, distinguished by fe_count == 0.
    If type selections overlap, the metal branch takes precedence for counts.
    Nonfinite metal charges in valid bins raise ValueError; charges of count-only
    species and atoms outside the bins do not contribute and are not validated.

    Args:
        frame:   dict — A single frame from parse_dump output
        col_idx: dict — Column name -> index mapping
        z_bins:  int  — Number of bins along z-axis (default: 50)
        fe_type, o_type: int or iterable[int] — Explicit species type(s).

    Returns:
        dict with keys:
            'z'         : np.array — Bin center positions (Angstroms)
            'fe_charge' : np.array — Average Fe charge per bin
            'fe_count'  : np.array — Number of Fe atoms per bin
            'o_count'   : np.array — Number of O atoms per bin
        Returns None if charge or z columns are missing.
    """
    zi = col_idx.get('z')
    qi = col_idx.get('q')
    ti = col_idx['type']
    _guard_slab_frame(frame, 'Charge z profile')
    if qi is None or zi is None:
        return None

    fe_types = _type_ids(fe_type, 'fe_type')
    o_types = _type_ids(o_type, 'o_type')
    atoms = frame['atoms']
    zlo, zhi = frame['box'][2]
    bins = np.linspace(zlo, zhi, z_bins + 1)
    ctr = (bins[:-1] + bins[1:]) / 2

    fe_q_sum = np.zeros(z_bins)
    fe_n = np.zeros(z_bins)
    o_n = np.zeros(z_bins)

    z_all = atoms[:, zi]
    types = atoms[:, ti].astype(int)
    charges = atoms[:, qi]
    bin_idx = np.digitize(z_all, bins) - 1
    valid = (bin_idx >= 0) & (bin_idx < z_bins)
    _require_finite_charges(charges[valid & np.isin(types, list(fe_types))],
                            frame, 'Charge z profile')

    for i in np.where(valid)[0]:
        # Average over the atoms in each occupied bin, not over the whole slab:
        # count and local mean charge convey different spatial information.
        bi = bin_idx[i]
        if types[i] in fe_types:
            fe_q_sum[bi] += charges[i]
            fe_n[bi] += 1
        elif types[i] in o_types:
            o_n[bi] += 1

    fe_q_avg = np.divide(fe_q_sum, fe_n, where=fe_n > 0, out=np.zeros(z_bins))

    return {'z': ctr, 'fe_charge': fe_q_avg, 'fe_count': fe_n, 'o_count': o_n}


def _rdf_candidate_pairs(pos_a, pos_b, box, r_max, z_pbc, same_species=False, pbc=None):
    """
    (ia, ib, weight) for every (a, b) pair whose minimum-image distance may be
    below r_max, found with an orthogonal periodic cKDTree. Return None without
    scipy or for a tilted Box; callers must then enumerate pairs themselves.

    The search radius carries a small margin, so the result is a superset of
    the pairs the brute-force loop would bin. Explicit pbc overrides the legacy
    x/y-periodic, optional-z convention. Each nonperiodic axis gets a padded
    box larger than its coordinate span, so no wrapped image enters the cutoff.
    Legacy RDF callers omitting pbc retain their original behavior.
    Callers supply finite, nonempty position arrays and validated bounds/cutoff;
    this private helper does not perform the public analyses' full validation.

    For same_species, each unordered pair is returned once with weight 2: the
    brute-force loop sees (i, j) and (j, i), whose minimum-image distances are
    bitwise equal (the displacement only changes sign).
    """
    if isinstance(box, Box):
        if not box.is_orthogonal:
            return None
        pbc = _cell_periodic(box, pbc, (True, True, z_pbc), 'RDF candidates')
        box = box.bounds
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        return None

    lo = box[:, 0]
    L = box[:, 1] - box[:, 0]
    wa = pos_a - lo
    wb = pos_b - lo
    boxsize = L.astype(float)
    periodic = (True, True, z_pbc) if pbc is None else pbc
    for dim, is_periodic in enumerate(periodic):
        if is_periodic:
            for w in (wa, wb):
                w[:, dim] %= L[dim]
                w[w[:, dim] >= L[dim], dim] = 0.0   # x % L can round up to L
        else:
            lower = min(wa[:, dim].min(), wb[:, dim].min())
            wa[:, dim] -= lower
            wb[:, dim] -= lower
            boxsize[dim] = max(wa[:, dim].max(), wb[:, dim].max()) + 2 * r_max + 1.0

    radius = r_max * (1 + 1e-6) + 1e-6
    tree_a = cKDTree(wa, boxsize=boxsize)
    if same_species:
        pairs = tree_a.query_pairs(radius, output_type='ndarray')
        return pairs[:, 0], pairs[:, 1], 2
    tree_b = cKDTree(wb, boxsize=boxsize)
    # Sparse records can include zero-distance pairs; public RDF binning rejects
    # r == 0 explicitly rather than relying on sparse storage conventions.
    near = tree_a.sparse_distance_matrix(tree_b, radius, output_type='ndarray')
    return near['i'].astype(np.intp), near['j'].astype(np.intp), 1


def compute_rdf(frames, col_idx, type_a=1, type_b=2, r_max=6.0, n_bins=200,
                max_frames=20, label_a='Fe', label_b='O', z_pbc=False, pbc=None):
    """
    Compute the radial distribution function g(r) between two atom types.

    The RDF describes how atomic density varies as a function of distance
    from a reference atom. It reveals characteristic bond lengths and
    coordination shells. Approximate Fe-O first-shell comparison markers are:
        - ~1.76 A → amorphous FeO
        - ~1.95 A → Fe₂O₃ (hematite)
        - ~2.06 A → Fe₃O₄ (magnetite)
        - ~2.16 A → FeO (wustite)

    These distances are contextual guides, not unique phase fingerprints:
    temperature, strain, disorder and mixed phases can shift/overlap peaks.

    Algorithm:
    1. For each reference atom of type_a, compute distances to all type_b atoms
    2. Apply minimum image convention on explicitly periodic axes
    3. Histogram the distances into radial bins
    4. Normalize each frame by N_a * shell_vol * (N_b / V), then take the
       arithmetic mean of those instantaneous RDFs. Equal frame weighting is
       appropriate for equally sampled configurations, including changing volume
       or populations; this is not a pooled-pair/exposure-weighted estimator.
       Same-species histograms count both ordered directions, with no extra /2.
       Using rho_b=N_b/V gives the finite-N ideal-gas plateau (N_b-1)/N_b
       for identical selections. Nonperiodic boundaries use the same global
       density convention, without a finite-boundary shell-volume correction.

    For orthogonal cells with scipy, a periodic cKDTree finds pairs within r_max and
    their distances are recomputed with the same minimum-image formula as the
    brute-force fallback (used without scipy), so both paths bin identically.
    Typed triclinic cells use exact nearest-lattice MIC and complete row-wise
    NumPy pairs, without a triclinic cKDTree backend. The distance is the nearest
    cell image, not a sum over repeated images. The caller must choose a cutoff
    suitable for the periodic cell;
    full spherical shells cease to be represented beyond its inscribed radius.
    Exactly coincident pairs and r == r_max are excluded in both paths.
    Empty species frames warn and do not enter the average; if none contribute,
    the returned g array is zero and n_frames is zero. Overlapping, unequal
    type unions retain directed A-to-B counting rather than the identical-set
    optimization; zero-distance self contributions are still excluded.

    Args:
        frames:     list[dict] — Trajectory frames
        col_idx:    dict       — Column index mapping
        type_a:     int or iterable[int] — Reference type(s), selected each frame.
        type_b:     int or iterable[int] — Target type(s), selected each frame.
        r_max:      float      — Maximum radial distance in Angstroms (default: 6.0)
        n_bins:     int        — Number of histogram bins (default: 200)
        max_frames: int        — Use only the last N frames for averaging (default: 20)
        label_a:    str        — Name of reference species for plot labels
        label_b:    str        — Name of target species for plot labels
        z_pbc:      bool       — Apply PBC in z-direction (default: False).
                                 Set to False for slab geometries (boundary p p f).
        pbc:        three bools or None — Explicit lattice-vector flags must
                    agree with known Box metadata. None uses resolved flags for
                    a tilted Box, but preserves (True, True, z_pbc) for ALL
                    orthogonal inputs, including typed ones. Triclinic Box
                    flags must already be resolved.

    Returns:
        dict with keys:
            'r'        : np.array — Bin center distances (Angstroms)
            'g'        : np.array — Normalized RDF values g(r)
            'label'    : str      — Pair label (e.g., 'Fe-O')
            'n_frames' : int      — Number of frames used in averaging
            'frame_window' : dict — The frames selected for averaging, before
                                    empty-species frames are dropped:
                                    'first_step'/'last_step' (dump timesteps,
                                    None when no frame is selected), 'n_frames'
                                    (selected count) and 'selection' ('last'
                                    when the trajectory was truncated to its
                                    last max_frames frames, 'all' otherwise).
                                    describe_frame_window() renders it.
    """
    types_a, types_b = _type_ids(type_a, 'type_a'), _type_ids(type_b, 'type_b')
    try:
        periodic = (True, True, z_pbc) if pbc is None else tuple(pbc)
    except TypeError:
        raise ValueError('RDF pbc must contain exactly three booleans') from None
    if len(periodic) != 3 or not all(isinstance(v, (bool, np.bool_)) for v in periodic):
        raise ValueError('RDF pbc must contain exactly three booleans')
    if not np.isfinite(r_max) or r_max <= 0:
        raise ValueError('RDF r_max must be finite and positive')
    for name, value in (('n_bins', n_bins), ('max_frames', max_frames)):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value <= 0:
            raise ValueError(f'RDF {name} must be a positive integer')
    same_species = types_a == types_b
    xi, yi, zi, ti = col_idx['x'], col_idx['y'], col_idx['z'], col_idx['type']
    dr = r_max / n_bins       # Bin width in Angstroms
    g_total = np.zeros(n_bins)
    n_frames_used = 0         # Number of frames contributing to the average
    bins_edge = np.linspace(0, r_max, n_bins + 1)
    r_centers = (bins_edge[:-1] + bins_edge[1:]) / 2
    shell_vol = (4 / 3) * np.pi * np.diff(bins_edge ** 3)

    # Restrict to the requested tail; choosing a tail does not establish that
    # it is equilibrated, and its frames receive equal (not elapsed-time) weight.
    truncated = len(frames) > max_frames
    use_frames = frames[-max_frames:] if truncated else frames
    frame_window = {
        'first_step': int(use_frames[0]['timestep']) if len(use_frames) else None,
        'last_step': int(use_frames[-1]['timestep']) if len(use_frames) else None,
        'n_frames': len(use_frames),
        'selection': 'last' if truncated else 'all',
    }

    for fr in use_frames:
        cell = _typed_cell(fr, 'RDF')
        # The legacy z_pbc switch remains authoritative for orthogonal inputs
        # when no explicit three-axis mask is supplied, including typed frames.
        frame_periodic = (periodic if cell is not None and cell.is_orthogonal and pbc is None
                          else _cell_periodic(cell, pbc, periodic, 'RDF'))
        triclinic = cell is not None and not cell.is_orthogonal
        if triclinic:
            box, L = cell.bounds, cell.lengths
        else:
            box, L = _orthogonal_box(fr, 'RDF')
        atoms = fr['atoms']
        types = atoms[:, ti].astype(int)
        # Keep singleton arithmetic unchanged while allowing explicit unions.
        mask_a = types == next(iter(types_a)) if len(types_a) == 1 else np.isin(types, list(types_a))
        mask_b = types == next(iter(types_b)) if len(types_b) == 1 else np.isin(types, list(types_b))

        # Extract xyz positions for both species
        pos_a = atoms[mask_a][:, [xi, yi, zi]]
        pos_b = atoms[mask_b][:, [xi, yi, zi]]
        if not np.all(np.isfinite(pos_a)) or not np.all(np.isfinite(pos_b)):
            raise ValueError(f"RDF timestep {fr['timestep']}: selected positions must be finite")

        if len(pos_a) == 0 or len(pos_b) == 0:
            warnings.warn(f"RDF timestep {fr['timestep']}: empty species selection; "
                          'frame excluded from RDF average', RuntimeWarning, stacklevel=2)
            continue

        pairs = (None if triclinic else
                 _rdf_candidate_pairs(pos_a, pos_b, box, r_max, z_pbc,
                                      same_species=same_species, pbc=frame_periodic))
        hist = np.zeros(n_bins)
        if pairs is not None:
            # cKDTree only nominates pairs; distances are recomputed below with
            # the brute-force formula so every r lands in the same bin as before.
            ia, ib, weight = pairs
            d = pos_b[ib] - pos_a[ia]
            for dim, wrap in enumerate(frame_periodic):
                if wrap:
                    d[:, dim] -= L[dim] * np.round(d[:, dim] / L[dim])
            r = np.linalg.norm(d, axis=1)
            valid = (r > 0) & (r < r_max)
            bi = (r[valid] / dr).astype(int)
            bi = bi[bi < n_bins]
            hist += weight * np.bincount(bi, minlength=n_bins)
        else:
            # Row-wise fallback avoids allocating a full N_a x N_b matrix.
            for p in pos_a:
                d = pos_b - p
                if triclinic:
                    d = minimum_image(d, cell)
                else:
                    for dim, wrap in enumerate(frame_periodic):
                        if wrap:
                            d[:, dim] -= L[dim] * np.round(d[:, dim] / L[dim])
                r = np.linalg.norm(d, axis=1)
                valid = (r > 0) & (r < r_max)
                bi = (r[valid] / dr).astype(int)
                bi = bi[bi < n_bins]
                np.add.at(hist, bi, 1)
        rho_b = len(pos_b) / (cell.volume if triclinic else np.prod(L))
        g_total += hist / (len(pos_a) * shell_vol * rho_b)
        n_frames_used += 1

    g = g_total / n_frames_used if n_frames_used else g_total
    return {'r': r_centers, 'g': g, 'label': f'{label_a}-{label_b}',
            'n_frames': n_frames_used, 'frame_window': frame_window}


def describe_frame_window(window):
    """Render a compute_rdf frame_window as 'last 20 frames (steps 3400–3587)'.

    'all N frames' marks an untruncated trajectory; a window with no frames
    renders as '0 frames'. This describes which frames were selected, not
    whether they are equilibrated.
    """
    n = int(window['n_frames'])
    if n == 0 or window.get('first_step') is None:
        return '0 frames'
    word = 'frame' if n == 1 else 'frames'
    return (f"{window.get('selection', 'last')} {n} {word} "
            f"(steps {window['first_step']}\u2013{window['last_step']})")


def compute_oar(frames, col_idx, z_surf, dt_fs=0.25, o_type=2):
    """
    Compute the Oxygen Absorption Rate (OAR) over time.

    OAR is defined as the fraction of O atoms that have penetrated below
    the Fe surface z-coordinate. An OAR of 0.5 means 50% of O atoms are
    below the surface. Despite the historical name "rate", this is an
    instantaneous population fraction, not a time derivative or reaction flux.
    The fixed surface and instantaneous selected population define the metric;
    an empty population returns zero. No boundary wrapping or bond test is used.

    Args:
        frames:  list[dict] — Trajectory frames
        col_idx: dict       — Column index mapping
        z_surf:  float      — z-coordinate of the Fe surface (Angstroms)
        dt_fs:   float      — Timestep in femtoseconds
        o_type:  int or iterable[int] — Oxygen species type(s).

    Returns:
        dict with keys:
            'time'       : np.array — Time in picoseconds
            'oar'        : np.array — Oxygen absorption rate (0 to 1)
            'n_absorbed' : np.array — Count of O atoms below surface
            'n_total'    : np.array — Total O atom count per frame
    """
    ti = col_idx['type']
    zi = col_idx['z']

    o_types = _type_ids(o_type, 'o_type')
    time, oar, n_abs, n_total = [], [], [], []
    for fr in frames:
        _guard_slab_frame(fr, 'OAR')
        atoms = fr['atoms']
        types = atoms[:, ti].astype(int)
        o_mask = np.isin(types, list(o_types))
        o_z = atoms[o_mask, zi]
        n_o = len(o_z)
        n_below = int(np.sum(o_z < z_surf))

        time.append(fr['timestep'] * dt_fs / 1000)
        n_abs.append(n_below)
        n_total.append(n_o)
        oar.append(n_below / n_o if n_o > 0 else 0)

    return {'time': np.array(time), 'oar': np.array(oar),
            'n_absorbed': np.array(n_abs), 'n_total': np.array(n_total)}


def compute_or(frames, col_idx, dt_fs=0.25, q_thr=Q_OXIDIZED_E, z_range=None,
               fe_type=1):
    """
    Compute the Oxidation Rate (OR) partial-charge proxy, intended for ReaxFF.

    OR is the fraction of Fe atoms whose partial charge exceeds q_thr.
    Unlike OAR (which counts O positions), OR uses a partial-charge threshold.
    It is a force-field-dependent oxidation proxy, not proof of a formal charge,
    chemical bond or oxide phase, and is not a time derivative. Selection and
    its denominator are recomputed per frame; empty selections return zero.
    As in charge evolution, a requested z restriction requires a z column;
    otherwise ValueError is raised before consuming frames, even without charge
    data. Slab endpoints are inclusive; the charge threshold is strict.
    Without that restriction this is a pure scalar-charge population fraction,
    independent of box shape; only the z-restricted variant requires a slab.
    Nonfinite charges in the selected type/slab population raise ValueError.

    Args:
        frames:  list[dict] — Trajectory frames
        col_idx: dict       — Column index mapping
        dt_fs:   float      — Timestep in femtoseconds
        q_thr:   float      — Charge threshold for oxidized Fe (default: 0.3 e)
        z_range: tuple or None — Optional (zlo, zhi) to restrict analysis
        fe_type: int or iterable[int] — Explicit metal species type(s).

    Returns:
        dict with keys:
            'time' : np.array — Time in picoseconds
            'or'   : np.array — Oxidation rate (0 to 1) per frame
        Returns None if no charge column is available.
    """
    zi = col_idx.get('z')
    if z_range is not None and zi is None:
        raise ValueError("Oxidation rate region z_range requires a 'z' column")
    ti = col_idx['type']
    qi = col_idx.get('q')
    if qi is None:
        if z_range is not None:
            for fr in frames:
                _guard_slab_frame(fr, 'Oxidation rate z restriction')
        return None

    fe_types = _type_ids(fe_type, 'fe_type')
    time, vals = [], []
    for fr in frames:
        if z_range is not None:
            _guard_slab_frame(fr, 'Oxidation rate z restriction')
        atoms = fr['atoms']
        fe_mask = np.isin(atoms[:, ti], list(fe_types))
        if z_range is not None and zi is not None:
            z = atoms[:, zi]
            fe_mask &= (z >= z_range[0]) & (z <= z_range[1])
        qs = atoms[fe_mask, qi]
        _require_finite_charges(qs, fr, 'Oxidation rate')
        time.append(fr['timestep'] * dt_fs / 1000)
        vals.append(np.sum(qs > q_thr) / len(qs) if len(qs) > 0 else 0)

    return {'time': np.array(time), 'or': np.array(vals)}


def analyze_penetration(frames, col_idx, surface_z, dt_fs=1.0, o_type=2):
    """
    Track oxygen atom penetration depth into the Fe slab over time.

    Monitors three quantities:
    1. Maximum penetration depth: (surface_z - min_O_z), measuring how
       deep the deepest O atom has reached into the Fe bulk.
    2. Adsorbed O count: O atoms more than NEAR_SURFACE_A (3.0 A) below
       the surface z-coordinate.
    3. Near-surface O count: O atoms within NEAR_SURFACE_A of the surface
       (in the reaction zone but not yet fully absorbed).

    The surface is fixed, and positions are not unwrapped. The function returns
    min_O_z rather than a derived depth; consumers subtract it from surface_z.
    An empty selection gives NaN for that position but zero counts/fractions.
    The adsorbed and near-surface bands are disjoint, with all other atoms
    remaining in the total-population denominator.
    The shared lower band edge belongs to near-surface, while its upper edge
    is excluded. A minimum z above the surface is retained, not clipped.

    Args:
        frames:    list[dict] — Trajectory frames
        col_idx:   dict       — Column index mapping
        surface_z: float      — z-coordinate of the Fe surface (Angstroms)
        dt_fs:     float      — Timestep in femtoseconds
        o_type:    int or iterable[int] — Oxygen species type(s).

    Returns:
        dict with keys:
            'time'              : np.array — Time in picoseconds
            'o_min_z'           : np.array — Minimum O z-coordinate per frame
            'n_adsorbed'        : np.array — O atoms below surface_z - NEAR_SURFACE_A
            'n_near_surface'    : np.array — O atoms within 3 A of surface
            'n_total_o'         : np.array — Total O atom count
            'frac_adsorbed'     : np.array — Fraction below surface_z - NEAR_SURFACE_A
            'frac_near_surface' : np.array — Fraction of O near surface
            'surface_z'         : float    — The surface z used
    """
    ti = col_idx['type']
    zi = col_idx['z']

    o_types = _type_ids(o_type, 'o_type')
    time, o_min_z, n_ads, n_near, n_total = [], [], [], [], []
    for fr in frames:
        _guard_slab_frame(fr, 'Penetration')
        atoms = fr['atoms']
        o_mask = np.isin(atoms[:, ti], list(o_types))
        o_z = atoms[o_mask, zi]

        if len(o_z) == 0:
            time.append(fr['timestep'] * dt_fs / 1000)
            o_min_z.append(np.nan)
            n_ads.append(0)
            n_near.append(0)
            n_total.append(0)
            continue

        time.append(fr['timestep'] * dt_fs / 1000)
        o_min_z.append(np.min(o_z))
        n_ads.append(int(np.sum(o_z < (surface_z - NEAR_SURFACE_A))))
        n_near.append(int(np.sum((o_z >= (surface_z - NEAR_SURFACE_A))
                                 & (o_z < (surface_z + NEAR_SURFACE_A)))))
        n_total.append(len(o_z))

    n_ads = np.array(n_ads)
    n_near = np.array(n_near)
    n_total = np.array(n_total)
    frac_ads = np.divide(n_ads, n_total, where=n_total > 0,
                         out=np.zeros(len(n_ads), dtype=float))
    frac_near = np.divide(n_near, n_total, where=n_total > 0,
                          out=np.zeros(len(n_near), dtype=float))

    return {'time': np.array(time), 'o_min_z': np.array(o_min_z),
            'n_adsorbed': n_ads, 'n_near_surface': n_near,
            'n_total_o': n_total, 'frac_adsorbed': frac_ads,
            'frac_near_surface': frac_near, 'surface_z': surface_z}


def analyze_penetration_trend(frames, col_idx, surface_z, dt_fs=1.0,
                              o_type=2, window=None):
    """
    Compute smoothed O penetration trend metrics over time.

    Provides the same fundamental metrics as analyze_penetration() but adds
    running-average smoothing for cleaner trend visualization. Designed for
    single-panel line graphs of the selected coordinate-based observables.

    Here adsorption means strictly below surface_z, unlike the deeper offset
    band in analyze_penetration(). Depth is clipped at zero when all selected
    atoms are above the surface. Statistics describe each instantaneous
    population, not fixed atom identities. Smoothing averages frame samples,
    not physical-duration intervals, and propagates NaNs across its window.

    Args:
        frames:    list[dict] — Trajectory frames
        col_idx:   dict       — Column index mapping
        surface_z: float      — z-coordinate of the Fe surface (Angstroms)
        dt_fs:     float      — Timestep in femtoseconds
        o_type:    int or iterable[int] — Oxygen species type(s).
        window:    int or None — Smoothing window size (auto if None)

    Returns:
        dict with keys (all arrays have the same length as frames):
            'time'                : np.array — Time in ps
            'adsorption_ratio'    : np.array — Fraction of O below surface (smoothed)
            'adsorption_ratio_raw': np.array — Raw fraction (unsmoothed)
            'mean_o_z'            : np.array — Mean O z-position (smoothed)
            'mean_o_z_raw'        : np.array — Raw
            'std_o_z'             : np.array — O z-distribution width (smoothed)
            'std_o_z_raw'         : np.array — Raw
            'max_depth'           : np.array — Max penetration depth (smoothed)
            'max_depth_raw'       : np.array — Raw
            'surface_z'           : float
            'window'              : int      — Smoothing window used
        Returns None if no O atoms found.
        Frames without selected atoms retain NaN spatial/ratio measurements.
    """
    ti = col_idx['type']
    zi = col_idx['z']

    o_types = _type_ids(o_type, 'o_type')
    time_arr, ads_ratio, mean_z, std_z, max_depth = [], [], [], [], []

    for fr in frames:
        _guard_slab_frame(fr, 'Penetration trend')
        atoms = fr['atoms']
        o_mask = np.isin(atoms[:, ti], list(o_types))
        o_z = atoms[o_mask, zi]
        time_arr.append(fr['timestep'] * dt_fs / 1000)
        if len(o_z) == 0:
            ads_ratio.append(np.nan)
            mean_z.append(np.nan)
            std_z.append(np.nan)
            max_depth.append(np.nan)
            continue
        ads_ratio.append(np.mean(o_z < surface_z))
        mean_z.append(np.mean(o_z))
        std_z.append(np.std(o_z))
        max_depth.append(max(0.0, surface_z - np.min(o_z)))

    if not time_arr or np.all(np.isnan(mean_z)):
        return None

    time_arr = np.array(time_arr)
    ads_ratio = np.array(ads_ratio)
    mean_z_arr = np.array(mean_z)
    std_z_arr = np.array(std_z)
    max_depth_arr = np.array(max_depth)

    # Smoothing window: auto-select based on trajectory length
    n = len(time_arr)
    if window is None:
        window = max(5, n // 40)
    window = min(window, n)

    def _smooth(arr, w):
        """Keep sample alignment with an endpoint-padded moving average.

        Do not impute missing measurements: a NaN contaminates every window
        containing it. A series no longer than the window is returned unsmoothed.
        """
        if len(arr) <= w:
            return arr.copy()
        kernel = np.ones(w) / w
        # Pad edges to avoid shrinkage artifacts
        padded = np.concatenate([
            np.full(w // 2, arr[0]),
            arr,
            np.full(w - w // 2 - 1, arr[-1])
        ])
        return np.convolve(padded, kernel, mode='valid')[:len(arr)]

    return {
        'time': time_arr,
        'adsorption_ratio': _smooth(ads_ratio, window),
        'adsorption_ratio_raw': ads_ratio,
        'mean_o_z': _smooth(mean_z_arr, window),
        'mean_o_z_raw': mean_z_arr,
        'std_o_z': _smooth(std_z_arr, window),
        'std_o_z_raw': std_z_arr,
        'max_depth': _smooth(max_depth_arr, window),
        'max_depth_raw': max_depth_arr,
        'surface_z': surface_z,
        'window': window,
    }


def compute_density_profile(frames, col_idx, z_range=None, n_bins=200,
                            species_type=None, species_name='all'):
    """
    Compute the z-direction number density profile rho(z), averaged
    over all trajectory frames.

    The density profile reveals the layered structure of the simulation:
    - Fe slab: high density in the bulk region
    - Fe surface: density drop-off at the slab edges
    - Oxide layer: overlap of Fe and O density at the interface
    - Gas phase: low O density above the surface

    Density is computed as: rho(z) = N_atoms_in_bin / (Lx * Ly * dz)
    where Lx*Ly is the cross-sectional area and dz is the bin width.
    Units: atoms/Angstrom^3.

    All frames share fixed laboratory-z bin edges, spanning the union of box
    bounds when no range is given. Each histogram is divided by its own frame's
    cross-sectional area before arithmetic averaging: this is a mean of
    instantaneous densities, not total counts divided by a mean volume.
    Empty selected populations still contribute a zero-density frame. Coordinates
    outside the range are excluded; the last histogram bin includes its upper
    endpoint, unlike analyze_charge_z. No wrapping, comoving rescaling or boundary
    correction is performed. Only orthogonal boxes are accepted. Callers must
    supply a usable range for an empty trajectory and a positive bin count.

    Args:
        frames:       list[dict] — Trajectory frames
        col_idx:      dict       — Column index mapping
        z_range:      tuple or None — (zlo, zhi) range; auto-detected if None
        n_bins:       int   — Number of z-bins (default: 200)
        species_type: int, iterable[int] or None — Species type(s); None selects all.
        species_name: str   — Label for this species (used in plot legends)

    Returns:
        dict with keys:
            'z'        : np.array — Bin center z-coordinates (Angstroms)
            'density'  : np.array — Average number density (atoms/A^3)
            'species'  : str      — Species label
            'n_frames' : int      — Number of frames averaged over
    """
    zi = col_idx['z']
    ti = col_idx['type']

    if z_range is None and frames:
        for fr in frames:
            _orthogonal_box(fr, 'Density profile')
        boxes = getattr(frames, 'boxes', None)   # LazyFrames: from the index, no parsing
        if boxes is not None:
            zlo, zhi = float(boxes[:, 2, 0].min()), float(boxes[:, 2, 1].max())
        else:
            zlo = min(fr['box'][2][0] for fr in frames)
            zhi = max(fr['box'][2][1] for fr in frames)
        z_range = (zlo, zhi)

    dz = (z_range[1] - z_range[0]) / n_bins
    z_bins = np.linspace(z_range[0] + dz / 2, z_range[1] - dz / 2, n_bins)
    density_sum = np.zeros(n_bins)
    n_used = 0

    selected_types = None if species_type is None else _type_ids(species_type, 'species_type')
    for fr in frames:
        _orthogonal_box(fr, 'Density profile')
        atoms = fr['atoms']
        if species_type is not None:
            mask = np.isin(atoms[:, ti], list(selected_types))
            z_coords = atoms[mask, zi]
        else:
            z_coords = atoms[:, zi]

        Lx = fr['box'][0][1] - fr['box'][0][0]
        Ly = fr['box'][1][1] - fr['box'][1][0]
        area = Lx * Ly

        # Normalize before accumulating to preserve equal configuration weight
        # when a barostat changes the x/y area between frames.
        h, _ = np.histogram(z_coords, bins=n_bins, range=z_range)
        density_sum += h / (area * dz)
        n_used += 1

    density_avg = density_sum / n_used if n_used > 0 else density_sum

    return {'z': z_bins, 'density': density_avg, 'species': species_name,
            'n_frames': n_used}


def detect_o2_dissociation(frames, col_idx, bond_cutoff=O2_BOND_CUTOFF_A, dt_fs=1.0,
                           o_type=2, pbc=(True, True, False)):
    """
    Track O₂ molecule dissociation over time by detecting O-O bonds.

    This is a distance-cutoff pair heuristic, not chemical bond order or a
    maximum-cardinality matching. Eligible pairs are assigned globally by
    shortest distance; each selected atom belongs to at most one pair.
    Unassigned atoms are reported as "dissociated" for API compatibility.

    Algorithm:
    1. Extract all O atom positions for each frame
    2. Find periodic candidate pairs using scipy.cKDTree when available and
       N > 20, or a row-wise brute-force search as fallback.
    3. Recompute MIC distances on exactly the periodic axes, apply the strict
       distance < bond_cutoff criterion, and use one global shortest-first
       greedy pairing rule. Equal distances are ordered by IDs (or canonical
       coordinates without IDs), independently of input row order or backend.
    4. Unpaired O atoms are classified as "dissociated"

    These instantaneous counts do not track molecule identities or establish
    chemical reaction events without independent evidence.

    Args:
        frames:      list[dict] — Trajectory frames
        col_idx:     dict       — Column index mapping
        bond_cutoff: float      — Maximum O-O distance to consider bonded (A)
        dt_fs:       float      — Timestep in femtoseconds
        o_type:      int or iterable[int] — Types selected independently per frame.
        pbc:         three bools — Periodic axes; default retains legacy slab PBC.

    Only supplied orthogonal (3, 2) bounds without retained tilt are supported.
    Invalid settings, selected positions or selected
    IDs fail visibly. Empty selections retain a time point with zero counts.
    IDs, when present, determine tie order; counts do not follow a fixed cohort.
    Distinct IDs at coincident positions are eligible under this distance-only
    rule (unlike RDF, which drops zero distances); pairing does not certify a
    physically plausible bond length.

    Returns:
        dict with keys:
            'time'            : np.array — Time in picoseconds
            'n_o2'            : np.array — Number of O₂ molecules per frame
            'n_dissociated'   : np.array — Number of unpaired O atoms
            'n_total_o'       : np.array — Total O atom count
            'frac_in_o2'      : np.array — Fraction of O atoms in O₂ (0 to 1)
            'frac_dissociated': np.array — Fraction of dissociated O atoms
    """
    try:
        pbc = tuple(pbc)
    except TypeError:
        raise ValueError('Pair detection pbc must contain exactly three booleans') from None
    if len(pbc) != 3 or not all(isinstance(v, (bool, np.bool_)) for v in pbc):
        raise ValueError('Pair detection pbc must contain exactly three booleans')
    try:
        if isinstance(bond_cutoff, (bool, np.bool_)):
            raise ValueError
        bond_cutoff = float(bond_cutoff)
    except (TypeError, ValueError):
        raise ValueError('Bond cutoff must be finite and positive') from None
    if not np.isfinite(bond_cutoff) or bond_cutoff <= 0:
        raise ValueError('Bond cutoff must be finite and positive')
    if isinstance(o_type, (int, np.integer)):
        selected_types = [o_type]
    else:
        try:
            selected_types = list(o_type)
        except TypeError:
            raise ValueError('o_type must be an integer or iterable of type IDs') from None
    if not selected_types or any(isinstance(t, (bool, np.bool_))
                                 or not isinstance(t, (int, np.integer)) or t <= 0
                                 for t in selected_types):
        raise ValueError('o_type must contain positive integer type IDs')

    ti = col_idx['type']
    xi, yi, zi_col = col_idx['x'], col_idx['y'], col_idx['z']
    id_col = col_idx.get('id')
    periodic_dims = [dim for dim, periodic in enumerate(pbc) if periodic]
    time, n_o2_list, n_diss_list, n_total_list = [], [], [], []

    for fr in frames:
        atoms = fr['atoms']
        box, L = _orthogonal_box(fr, 'Pair detection')
        _cell_periodic(_typed_cell(fr, 'Pair detection'), pbc, pbc, 'Pair detection')
        step = fr['timestep']
        o_mask = np.isin(atoms[:, ti], selected_types)
        selected = atoms[o_mask]
        o_pos = selected[:, [xi, yi, zi_col]].astype(float, copy=True)
        n_o = len(o_pos)
        if not np.all(np.isfinite(o_pos)):
            raise ValueError(f'Timestep {step}: selected positions must be finite')
        if id_col is not None:
            ids = selected[:, id_col]
            if (not np.all(np.isfinite(ids)) or np.any(ids <= 0)
                    or np.any(ids != np.floor(ids)) or len(np.unique(ids)) != n_o):
                raise ValueError(f'Timestep {step}: selected atom IDs must be unique positive integers')
            order = np.argsort(ids)
        else:
            # Coordinate ordering is only a deterministic fallback for counts,
            # not a substitute for IDs in a per-atom time series.
            canonical_pos = o_pos.copy()
            for dim in periodic_dims:
                canonical_pos[:, dim] = (canonical_pos[:, dim] - box[dim, 0]) % L[dim]
            order = np.lexsort((canonical_pos[:, 2], canonical_pos[:, 1], canonical_pos[:, 0]))
        o_pos = o_pos[order]

        if n_o < 2:
            time.append(step * dt_fs / 1000)
            n_o2_list.append(0)
            n_diss_list.append(n_o)
            n_total_list.append(n_o)
            continue

        bonded = np.zeros(n_o, dtype=bool)  # Track which O atoms are paired
        n_o2 = 0  # Count of detected O₂ molecules

        # Periodic candidates must be found before MIC distance filtering;
        # a missing cross-boundary candidate cannot be recovered afterwards.
        candidates = (_rdf_candidate_pairs(o_pos, o_pos, box, bond_cutoff,
                                            z_pbc=pbc[2], same_species=True, pbc=pbc)
                      if n_o > 20 else None)
        if candidates is not None:
            ia, ib, _weight = candidates
        else:
            # Enumerate all close candidates, not a pairing per starting atom.
            # Keep only nearby indices, avoiding a full N x N distance matrix.
            left, right = [], []
            radius = bond_cutoff * (1 + 1e-6) + 1e-6
            for i in range(n_o - 1):
                dr = o_pos[i + 1:] - o_pos[i]
                for dim in periodic_dims:
                    dr[:, dim] -= L[dim] * np.round(dr[:, dim] / L[dim])
                near = np.flatnonzero(np.linalg.norm(dr, axis=1) <= radius)
                if len(near):
                    left.append(np.full(len(near), i, dtype=np.intp))
                    right.append(near + i + 1)
            ia = np.concatenate(left) if left else np.empty(0, dtype=np.intp)
            ib = np.concatenate(right) if right else np.empty(0, dtype=np.intp)

        # Both backends pass through exactly the same MIC, strict cutoff and
        # global greedy rule. Sorted positions make (ia, ib) a deterministic
        # tie-break by atom IDs, or by canonical coordinates when IDs are absent.
        dr = o_pos[ib] - o_pos[ia]
        for dim in periodic_dims:
            dr[:, dim] -= L[dim] * np.round(dr[:, dim] / L[dim])
        dists = np.linalg.norm(dr, axis=1)
        valid = dists < bond_cutoff
        ia, ib, dists = ia[valid], ib[valid], dists[valid]
        order = np.lexsort((ib, ia, dists))
        for idx in order:
            i, j = ia[idx], ib[idx]
            if not bonded[i] and not bonded[j]:
                bonded[i] = True
                bonded[j] = True
                n_o2 += 1

        time.append(fr['timestep'] * dt_fs / 1000)
        n_o2_list.append(n_o2)
        n_diss_list.append(int(np.sum(~bonded)))
        n_total_list.append(n_o)

    n_o2_arr = np.array(n_o2_list)
    n_diss_arr = np.array(n_diss_list)
    n_total_arr = np.array(n_total_list)
    frac_o2 = np.divide(2 * n_o2_arr, n_total_arr, where=n_total_arr > 0,
                         out=np.zeros(len(n_o2_arr), dtype=float))
    frac_diss = np.divide(n_diss_arr, n_total_arr, where=n_total_arr > 0,
                           out=np.zeros(len(n_diss_arr), dtype=float))

    return {'time': np.array(time), 'n_o2': n_o2_arr,
            'n_dissociated': n_diss_arr, 'n_total_o': n_total_arr,
            'frac_in_o2': frac_o2, 'frac_dissociated': frac_diss}


def analyze_spin_evolution(frames, col_idx, dt_fs=1.0):
    """
    Track the evolution of magnetic spin populations over time. ACE-only.

    In ACE simulations of magnetic iron oxides (e.g., Fe₃O₄ magnetite),
    Fe atoms are classified by their spin state:
      - Type 1 = Fe_up   (ACE spin-state label, not an assumed majority)
      - Type 2 = Fe_down (ACE spin-state label via the 'Mn' proxy slot)
      - Type 3 = O       (oxygen, non-magnetic)

    The convention is defined in common.mapping (Bienvenu et al., npj Comput.
    Mater. 11, 81, 2025). In the committed regular_MD fixture there are 64
    type-1 Fe slots and 128 type-2 Mn proxy slots: Fe_down is the majority and
    n_up/n_total_Fe = 64/192 = 1/3. This is a measured fixture population, not
    a general assignment of crystallographic sites to spin labels. An ideal
    8:16 antiparallel site population gives 1/3 OR 2/3 under reversed spin
    encoding. Counts alone do not establish magnetic order or an oxide phase.

    MC atom/swap moves may change these labels during a simulation; population
    histories alone cannot establish equilibration of the magnetic structure.

    This counts instantaneous labels, not persistent spin histories or spatial
    correlations. total_atoms here is the sum of the three recognized ACE
    populations, not any additional/unrecognized types. Empty denominators
    produce zero fractions; no magnetic moment magnitudes are inferred.

    Args:
        frames:  list[dict] — Trajectory frames
        col_idx: dict       — Column index mapping
        dt_fs:   float      — Timestep in femtoseconds

    Returns:
        dict with keys:
            'time'          : np.array — Time in picoseconds
            'n_up'          : np.array — Count of spin-up Fe (type 1)
            'n_down'        : np.array — Count of spin-down Fe (type 2)
            'n_o'           : np.array — Count of O atoms (type 3)
            'total_fe'      : np.array — Total Fe count (up + down)
            'total_atoms'   : np.array — Total atom count
            'up_fraction'   : np.array — n_up / total_fe (0 to 1)
            'down_fraction' : np.array — n_down / total_fe
            'o_fraction'    : np.array — n_o / total_atoms
    """
    ti = col_idx['type']
    ace = label_to_type('ace')   # {'Fe_up': 1, 'Fe_down': 2, 'O': 3}

    time, n_up, n_down, n_o = [], [], [], []
    for fr in frames:
        atoms = fr['atoms']
        types = atoms[:, ti].astype(int)
        time.append(fr['timestep'] * dt_fs / 1000)
        n_up.append(int(np.sum(types == ace['Fe_up'])))
        n_down.append(int(np.sum(types == ace['Fe_down'])))
        n_o.append(int(np.sum(types == ace['O'])))

    n_up = np.array(n_up)
    n_down = np.array(n_down)
    n_o = np.array(n_o)
    total_fe = n_up + n_down
    total_atoms = total_fe + n_o
    up_frac = np.divide(n_up, total_fe, where=total_fe > 0, out=np.zeros_like(n_up, dtype=float))
    down_frac = np.divide(n_down, total_fe, where=total_fe > 0, out=np.zeros_like(n_down, dtype=float))
    o_frac = np.divide(n_o, total_atoms, where=total_atoms > 0, out=np.zeros_like(n_o, dtype=float))

    return {'time': np.array(time), 'n_up': n_up, 'n_down': n_down,
            'n_o': n_o, 'total_fe': total_fe, 'total_atoms': total_atoms,
            'up_fraction': up_frac, 'down_fraction': down_frac, 'o_fraction': o_frac}


def analyze_msd(frames, col_idx, species_type=None, dt_fs=1.0, pbc=(True, True, False)):
    """Compute MSD of a fixed initial cohort, following atom IDs over time.

    Select types only in frame zero. Subsequent type changes or row reordering
    do not change the cohort or denominator. Newly added IDs are reported and
    ignored; missing tracked IDs raise rather than creating an unknown sampling
    gap across which periodic crossings could be lost.

    Minimum-image displacements are accumulated on the axes marked periodic.
    Orthogonal trajectories retain the historical current-frame-length
    arithmetic, including variable lengths and np.round ties. Typed triclinic
    trajectories require constant origin, matrix and resolved PBC. Each true
    step must lie strictly inside the periodic lattice Voronoi cell; fractional
    components below one-half are not sufficient. Wrapped samples cannot detect
    arbitrary aliasing. Neither image flags nor unwrapped-coordinate columns are
    interpreted, and affine cell motion is not subtracted. Bare retained tilt
    without a Box remains unsupported.
    The result averages squared Cartesian displacements over that one initial
    cohort/reference time; it is not a multiple-time-origin estimator. All
    components, including nonperiodic ones, enter the squared norm, and neither
    center-of-mass drift nor a diffusion-coefficient fit is removed/provided.

    Args:
        frames: list-like trajectory with at least two frames.
        col_idx: numeric column indices, including id, type, x, y and z.
        species_type: integer type ID, iterable of type IDs, or None for all
            atoms initially present. This is an initial-cohort MSD, not a
            time-dependent population or spin-channel MSD.
        dt_fs: timestep in femtoseconds; output time is in picoseconds.
        pbc: three booleans for lattice-vector unwrapping (Cartesian axes for
            orthogonal cells). The historical slab default
            is retained for compatibility. A bulk cell needs (True, True, True);
            the shell supplies flags from dump/input metadata.

    Returns:
        {'time': ndarray, 'msd': ndarray}, MSD in squared coordinate units
        (Angstrom² for metal/real units), or None for fewer than two frames or
        an empty initial selection. No frames are silently skipped.

    Raises:
        ValueError: IDs are absent, invalid, duplicated or missing from the
            cohort; PBC, box bounds or selected positions are malformed.
    """
    if len(frames) < 2:
        return None

    try:
        pbc = tuple(pbc)
    except TypeError:
        raise ValueError('MSD pbc must contain exactly three booleans') from None
    if len(pbc) != 3 or not all(isinstance(v, (bool, np.bool_)) for v in pbc):
        raise ValueError('MSD pbc must contain exactly three booleans')

    # Validate typed metadata even if the initial cohort will be empty. A
    # triclinic trajectory cannot silently become a legacy orthogonal series.
    reference_cell = None
    for frame in frames:
        cell = _typed_cell(frame, 'MSD')
        _cell_periodic(cell, pbc, pbc, 'MSD')
        if cell is not None and not cell.is_orthogonal:
            reference_cell = cell
            break
    if reference_cell is not None:
        for frame in frames:
            cell = _typed_cell(frame, 'MSD')
            if cell is None:
                raise ValueError('MSD triclinic trajectories cannot mix cell representations')
            _cell_periodic(cell, pbc, pbc, 'MSD')
            if (not np.array_equal(cell.bounds[:, 0], reference_cell.bounds[:, 0])
                    or not np.array_equal(cell.matrix, reference_cell.matrix)
                    or cell.pbc != reference_cell.pbc):
                raise ValueError(f"MSD timestep {frame['timestep']}: triclinic MSD requires "
                                 'constant origin, matrix and PBC; cell deformation/flips are unsupported')

    position_cols = [col_idx[k] for k in ('x', 'y', 'z')]
    first = frames[0]
    atoms0 = first['atoms']
    if species_type is None:
        mask = np.ones(len(atoms0), dtype=bool)
    else:
        if isinstance(species_type, (int, np.integer)):
            types = [species_type]
        else:
            try:
                types = list(species_type)
            except TypeError:
                raise ValueError('MSD species_type must be an integer or iterable of type IDs') from None
        if any(isinstance(t, (bool, np.bool_)) or not isinstance(t, (int, np.integer))
               or t <= 0 for t in types):
            raise ValueError('MSD species_type must contain positive integer type IDs')
        mask = np.isin(atoms0[:, col_idx['type']], types)

    if not np.any(mask):
        return None
    id_col = col_idx.get('id')
    if id_col is None:
        raise ValueError('MSD requires an explicit atom ID (id) column to track the initial cohort')

    def sorted_atoms(frame):
        """Validate every frame ID and return rows/IDs in common sorted order.

        Whole-frame uniqueness is necessary even for a smaller tracked cohort:
        searchsorted must identify one unambiguous row for every selected ID.
        """
        atoms = frame['atoms']
        ids = atoms[:, id_col]
        step = frame['timestep']
        if (not np.all(np.isfinite(ids)) or np.any(ids <= 0)
                or np.any(ids != np.floor(ids))):
            raise ValueError(f'MSD timestep {step}: atom IDs must be finite positive integers')
        order = np.argsort(ids)
        ids = ids[order]
        if np.any(ids[1:] == ids[:-1]):
            raise ValueError(f'MSD timestep {step}: duplicate atom IDs')
        return atoms[order], ids

    def box_lengths(frame):
        """Return fixed triclinic lengths or validate each legacy orthogonal cell.

        Triclinic lengths are not used for componentwise MIC: that branch calls
        the exact lattice solver after the whole series passes fixed-cell checks.
        """
        if reference_cell is not None:
            return reference_cell.lengths
        _box, lengths = _orthogonal_box(frame, 'MSD')
        return lengths

    box_lengths(first)
    ordered0, initial_ids = sorted_atoms(first)
    # Apply the selection to the same ID order as ordered0; never select again.
    selected_ids = np.sort(atoms0[mask, id_col])
    indices = np.searchsorted(initial_ids, selected_ids)
    ref_pos = ordered0[indices][:, position_cols].astype(float, copy=True)
    if not np.all(np.isfinite(ref_pos)):
        raise ValueError(f"MSD timestep {first['timestep']}: selected positions must be finite")
    prev_pos = ref_pos.copy()
    unwrapped = ref_pos.copy()
    reported_new_ids = set()

    t0 = first['timestep']
    time_arr, msd_arr = [0.0], [0.0]
    wrap_dims = [dim for dim, periodic in enumerate(pbc) if periodic]

    for fr in itertools.islice(frames, 1, None):
        lengths = box_lengths(fr)
        ordered, ids = sorted_atoms(fr)
        present = np.isin(selected_ids, ids, assume_unique=True)
        if not np.all(present):
            missing = selected_ids[~present]
            preview = ', '.join(str(int(v)) for v in missing[:8])
            raise ValueError(f"MSD timestep {fr['timestep']}: missing {len(missing)} tracked atom ID(s) "
                             f'[{preview}]; cannot unwrap across missing samples')
        added = np.setdiff1d(ids, initial_ids, assume_unique=True)
        new_ids = set(added) - reported_new_ids
        if new_ids:
            warnings.warn(f"MSD timestep {fr['timestep']}: {len(new_ids)} new atom ID(s) ignored; "
                          'tracking the fixed initial cohort', RuntimeWarning, stacklevel=2)
            reported_new_ids.update(new_ids)
        indices = np.searchsorted(ids, selected_ids)
        cur_pos = ordered[indices][:, position_cols].astype(float, copy=False)
        if not np.all(np.isfinite(cur_pos)):
            raise ValueError(f"MSD timestep {fr['timestep']}: selected positions must be finite")

        # Accumulate consecutive displacements rather than applying MIC once
        # against the initial position, so multiple resolved crossings survive.
        # This uses the current frame's lengths; it is not a subtraction of
        # affine cell motion or a general variable-cell diffusion correction.
        delta = cur_pos - prev_pos
        if reference_cell is not None:
            delta = minimum_image(delta, reference_cell)
        else:
            for dim in wrap_dims:
                delta[:, dim] -= lengths[dim] * np.round(delta[:, dim] / lengths[dim])
        unwrapped += delta
        prev_pos = cur_pos.copy()

        disp = unwrapped - ref_pos
        msd = np.mean(np.sum(disp ** 2, axis=1))
        time_arr.append((fr['timestep'] - t0) * dt_fs / 1000)
        msd_arr.append(msd)

    return {'time': np.array(time_arr), 'msd': np.array(msd_arr)}


def analyze_stage_performance(log_data):
    """
    Extract stage-wise wall-clock time breakdown from parsed log data.

    Multi-stage simulations (e.g., minimize → equilibrate → production)
    have separate 'Loop time' values for each 'run' command. This function
    returns the accumulated wall time per stage for performance analysis.

    Aggregation belongs to the parser: this accessor returns its mapping
    unchanged (not a copy), and None when the mapping is absent or empty.

    Args:
        log_data: dict or None — Output from parse_log()

    Returns:
        dict[str, float] — Stage name -> wall time in seconds.
        Returns None if no stage timing information is available.
    """
    if log_data is None or 'stage_times' not in log_data:
        return None
    st = log_data['stage_times']
    if not st:
        return None
    return st


def analyze_structure(atoms_array, z_fixed=None, z_surface=None):
    """
    Analyze the final (relaxed) structure from a LAMMPS data file.

    Computes z-resolved statistics for each atom type: count, z-range
    (min/max/mean). These are descriptive per-type extents, not automatic
    interface detection or certification of crystallographic ordering.
    Coordinates are used as stored, without periodic wrapping or species unions.
    z_fixed and z_surface are compatibility parameters and do not change these
    statistics; corresponding annotations are handled by plotting code.
    This array-only API has no geometry metadata to validate: tilted-slab
    rejection, when needed, belongs to the caller before extracting this array.

    Args:
        atoms_array: np.array shape (N, 5) — [id, type, x, y, z]
        z_fixed:     float or None — z-coordinate of the fixed layer boundary
        z_surface:   float or None — z-coordinate of the Fe surface

    Returns:
        dict[int, dict] — Type ID -> {'count', 'z_min', 'z_max', 'z_mean'}
        Returns None if atoms_array is empty.
    """
    if len(atoms_array) == 0:
        return None

    types = atoms_array[:, 1].astype(int)
    z = atoms_array[:, 4]

    result = {}
    for t in sorted(set(types)):
        t_mask = types == int(t)
        result[int(t)] = {
            'count': int(np.sum(t_mask)),
            'z_min': float(z[t_mask].min()) if np.any(t_mask) else 0,
            'z_max': float(z[t_mask].max()) if np.any(t_mask) else 0,
            'z_mean': float(z[t_mask].mean()) if np.any(t_mask) else 0,
        }

    return result


def analyze_penetration_profile(frames, col_idx, dt_fs=1.0, o_type=2,
                                 surface_percentile=95, fe_type=None):
    """
    Detailed oxygen penetration profiling: tracks per-atom O trajectories,
    z-distribution evolution, and adsorption timeline.

    Columns follow the sorted union of selected atom IDs across all frames.
    Missing atoms (or atoms outside the instantaneous species selection) are
    NaN; no frames are dropped. The surface is the requested percentile of
    selected metal z-coordinates, with NaN and a warning if none are present.
    "Crossing" times are first observed below-surface times, including atoms
    initially below it; missing samples do not imply an interpolated crossing.

    Unlike the fixed initial MSD cohort, type membership is evaluated in every
    frame and an ID may enter or leave the instantaneous selection. The percentile
    surface is a moving coordinate-based proxy, not a local interface mesh. Coordinates
    are not unwrapped, so this slab metric requires a consistent z convention.
    initial_cross_times separates initial-population observations from later
    arrivals; n_o is the union size, not a suitable initial-cohort denominator.
    A moving percentile may pass a stationary atom; therefore a first-below
    observation is not necessarily transport through a stationary material plane.

    This provides the raw data for four visualization modes:
      1. Individual O atom z-trajectories (spaghetti plot)
      2. O density kymograph (z vs time heatmap)
      3. z-distribution evolution (ridge/waterfall plot)
      4. O adsorption timeline (cumulative surface crossing)

    Args:
        frames:              list[dict] — Trajectory frames
        col_idx:             dict       — Column index mapping
        dt_fs:               float      — Timestep in femtoseconds
        o_type:              int or iterable[int] — Oxygen species type(s).
        surface_percentile:  float      — Percentile of Fe z-coords for surface (default 95)
        fe_type:             int, iterable[int] or None — Explicit surface species.
                             None retains legacy selection of all non-oxygen types.

    Returns:
        dict with keys:
            'time'       : np.array shape (N,)       — Time in ps
            'o_z_traj'   : np.array shape (N, N_o)   — ID-aligned z, NaN if absent
            'o_ids'      : np.array shape (N_o,)     — O atom IDs (for tracking)
            'surface_z'  : np.array shape (N,)       — Fe surface z per frame
            'min_o_z'    : np.array shape (N,)       — Deepest O z per frame
            'n_o'        : int                       — Number of distinct selected IDs (union)
            'n_initial_o': int                       — Initial selected population
            'n_present_o': np.array shape (N,)       — Selected population per frame
            'cross_times': np.array                  — Time (ps) each O first crossed surface
            'initial_cross_times': np.array          — First-below times for initial IDs only
        Returns None if no O atoms found or fewer than 2 frames.
    """
    ti = col_idx['type']
    zi = col_idx['z']
    idi = col_idx.get('id')
    if idi is None:
        raise ValueError('Penetration profile requires an explicit atom ID (id) column')
    o_types = _type_ids(o_type, 'o_type')
    fe_types = None if fe_type is None else _type_ids(fe_type, 'fe_type')
    if fe_types is not None and o_types & fe_types:
        raise ValueError('Penetration profile fe_type and o_type selections must not overlap')
    try:
        surface_percentile = float(surface_percentile)
    except (TypeError, ValueError):
        raise ValueError('surface_percentile must be finite and between 0 and 100') from None
    if not np.isfinite(surface_percentile) or not 0 <= surface_percentile <= 100:
        raise ValueError('surface_percentile must be finite and between 0 and 100')

    if len(frames) < 2:
        for fr in frames:
            _guard_slab_frame(fr, 'Penetration profile')
        return None

    t0 = frames[0]['timestep']

    time_arr, samples, surface_arr = [], [], []
    selected_ids = set()

    for fr in frames:
        _orthogonal_box(fr, 'Penetration profile')
        atoms = fr['atoms']
        ids = atoms[:, idi]
        if (not np.all(np.isfinite(ids)) or np.any(ids <= 0)
                or np.any(ids != np.floor(ids)) or len(np.unique(ids)) != len(ids)):
            raise ValueError(f"Penetration profile timestep {fr['timestep']}: "
                             'atom IDs must be unique finite positive integers')
        types = atoms[:, ti].astype(int)
        o_mask = np.isin(types, list(o_types))
        fe_mask = ~o_mask if fe_types is None else np.isin(types, list(fe_types))
        o_ids_frame = ids[o_mask].astype(np.int64)
        o_z = atoms[o_mask, zi]
        fe_z = atoms[fe_mask, zi]
        if not np.all(np.isfinite(o_z)) or not np.all(np.isfinite(fe_z)):
            raise ValueError(f"Penetration profile timestep {fr['timestep']}: "
                             'selected z coordinates must be finite')
        if len(fe_z):
            surface = float(np.percentile(fe_z, surface_percentile))
        else:
            warnings.warn(f"Penetration profile timestep {fr['timestep']}: no surface species; "
                          'surface is NaN', RuntimeWarning, stacklevel=2)
            surface = np.nan
        time_arr.append((fr['timestep'] - t0) * dt_fs / 1000.0)
        samples.append((o_ids_frame, o_z))
        selected_ids.update(o_ids_frame)
        surface_arr.append(surface)

    if not selected_ids:
        return None

    # Discover the complete ID union before allocating columns, allowing late
    # arrivals without changing column identity or filling absent samples with 0.
    o_ids = np.asarray(sorted(selected_ids), dtype=np.int64)
    n_o = len(o_ids)
    o_z_traj = np.full((len(samples), n_o), np.nan)
    min_o_z = np.full(len(samples), np.nan)
    n_present_o = np.asarray([len(ids) for ids, _z in samples], dtype=int)
    for i, (ids, z) in enumerate(samples):
        o_z_traj[i, np.searchsorted(o_ids, ids)] = z
        if len(z):
            min_o_z[i] = np.min(z)
    time_arr = np.array(time_arr)
    surface_arr = np.array(surface_arr)

    # NaN positions/surfaces compare false: no event is invented in a sampling
    # gap. The first observed below-surface sample is not an interpolated event
    # time, and an atom already below at the start is counted at time zero.
    cross_times, initial_cross_times = [], []
    initial_ids = set(samples[0][0])
    for j in range(n_o):
        below = o_z_traj[:, j] < surface_arr
        if np.any(below):
            first_below = time_arr[np.argmax(below)]
            cross_times.append(first_below)
            if o_ids[j] in initial_ids:
                initial_cross_times.append(first_below)
    cross_times = np.sort(cross_times) if cross_times else np.array([])

    return {
        'time': time_arr,
        'o_z_traj': o_z_traj,
        'o_ids': o_ids,
        'surface_z': surface_arr,
        'min_o_z': min_o_z,
        'n_o': n_o,
        'n_initial_o': int(n_present_o[0]),
        'n_present_o': n_present_o,
        'cross_times': cross_times,
        'initial_cross_times': np.sort(initial_cross_times),
    }
