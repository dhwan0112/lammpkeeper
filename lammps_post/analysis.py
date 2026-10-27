"""
═══════════════════════════════════════════════════════════════
Section 3: Analysis Functions
═══════════════════════════════════════════════════════════════
Pure functions that take parsed data and return analysis results
as dictionaries. All functions are force-field-aware and handle
edge cases (empty frames, missing columns) gracefully.

Each analysis function returns a dict containing:
  - Time series arrays ('time', plus result-specific keys)
  - Both raw counts AND normalized fractions for cross-simulation
    comparison (the 'normalize' toggle in the CLI selects which
    to display in plots)

Dependencies:
  Required : numpy
  Optional : scipy.spatial.cKDTree (lazy-loaded for O2 dissociation)
═══════════════════════════════════════════════════════════════
"""

import itertools
import warnings

import numpy as np

from lammpkeeper.common.mapping import label_to_type
from lammps_post import (Q_OXIDIZED_E, SURFACE_OFFSET_A, NEAR_SURFACE_A,
                         O2_BOND_CUTOFF_A)

def analyze_charge_evolution(frames, col_idx, dt_fs=0.25, z_range=None, q_thr=Q_OXIDIZED_E):
    """
    Track the evolution of Fe atomic partial charges over time.
    ReaxFF-only analysis — requires the 'q' column in dump data.

    In ReaxFF simulations, Fe atoms gain positive charge upon oxidation.
    This function tracks:
    - Average Fe charge across all frames
    - Maximum Fe charge (most oxidized atom)
    - Count and fraction of "oxidized" Fe atoms (charge > q_thr)

    An Fe atom with q > 0.3 e is considered oxidized (the threshold
    0.3 is empirically chosen to distinguish metallic Fe (~0 e) from
    oxidized Fe²⁺ (~0.8-1.2 e) and Fe³⁺ (~1.2-1.8 e)).

    Args:
        frames:  list[dict] — Parsed trajectory frames from parse_dump
        col_idx: dict       — Column name -> index mapping
        dt_fs:   float      — Timestep in femtoseconds (0.25 for ReaxFF)
        z_range: tuple or None — (zlo, zhi) to restrict analysis to a z-slab
        q_thr:   float      — Charge threshold for "oxidized" classification (e)

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
    qi = col_idx.get('q')    # Charge column index (None if not ReaxFF)
    ti = col_idx['type']     # Atom type column index
    if qi is None:
        return None  # No charge data available — not a ReaxFF dump

    time, avg, mx, n_ox, n_fe = [], [], [], [], []
    for fr in frames:
        atoms = fr['atoms']
        # Select Fe atoms (type 1 in standard ReaxFF Fe-O systems)
        fe_mask = atoms[:, ti].astype(int) == 1
        # Optionally restrict to a z-slab (e.g., surface region only)
        if z_range is not None and zi is not None:
            z = atoms[:, zi]
            fe_mask &= (z >= z_range[0]) & (z <= z_range[1])
        qs = atoms[fe_mask, qi]  # Charges of selected Fe atoms
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


def analyze_charge_z(frame, col_idx, z_bins=50):
    """
    Compute the z-direction charge distribution for a single frame.
    ReaxFF-only analysis — requires the 'q' column.

    Divides the simulation box along the z-axis into bins and computes:
    - Average Fe charge in each bin (shows where oxidation is occurring)
    - O atom count in each bin (shows O penetration profile)

    This provides a spatial view of oxidation: bins near the Fe surface
    will show higher Fe charges where O has penetrated and reacted.

    Args:
        frame:   dict — A single frame from parse_dump output
        col_idx: dict — Column name -> index mapping
        z_bins:  int  — Number of bins along z-axis (default: 50)

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
    if qi is None or zi is None:
        return None

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

    for i in np.where(valid)[0]:
        bi = bin_idx[i]
        if types[i] == 1:
            fe_q_sum[bi] += charges[i]
            fe_n[bi] += 1
        elif types[i] == 2:
            o_n[bi] += 1

    fe_q_avg = np.divide(fe_q_sum, fe_n, where=fe_n > 0, out=np.zeros(z_bins))

    return {'z': ctr, 'fe_charge': fe_q_avg, 'fe_count': fe_n, 'o_count': o_n}


def _rdf_candidate_pairs(pos_a, pos_b, box, r_max, z_pbc, same_species=False):
    """
    (ia, ib, weight) for every (a, b) pair whose minimum-image distance may be
    below r_max, found with a periodic cKDTree; None without scipy.

    The search radius carries a small margin, so the result is a superset of
    the pairs the brute-force loop would bin. x and y are periodic; z is too
    when z_pbc, otherwise it gets a box longer than the coordinate span plus
    r_max, so no wrapped image can come within the cutoff.

    For same_species, each unordered pair is returned once with weight 2: the
    brute-force loop sees (i, j) and (j, i), whose minimum-image distances are
    bitwise equal (the displacement only changes sign).
    """
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        return None

    lo = box[:, 0]
    L = box[:, 1] - box[:, 0]
    wa = pos_a - lo
    wb = pos_b - lo
    boxsize = L.astype(float)
    periodic_dims = (0, 1, 2) if z_pbc else (0, 1)
    for dim in periodic_dims:
        for w in (wa, wb):
            w[:, dim] %= L[dim]
            w[w[:, dim] >= L[dim], dim] = 0.0   # x % L can round up to L
    if not z_pbc:
        zmin = min(wa[:, 2].min(), wb[:, 2].min())
        wa[:, 2] -= zmin
        wb[:, 2] -= zmin
        boxsize[2] = max(wa[:, 2].max(), wb[:, 2].max()) + 2 * r_max + 1.0

    radius = r_max * (1 + 1e-6) + 1e-6
    tree_a = cKDTree(wa, boxsize=boxsize)
    if same_species:
        pairs = tree_a.query_pairs(radius, output_type='ndarray')
        return pairs[:, 0], pairs[:, 1], 2
    tree_b = cKDTree(wb, boxsize=boxsize)
    # Zero-distance entries are dropped from the sparse result; the binning
    # excludes r == 0 anyway.
    near = tree_a.sparse_distance_matrix(tree_b, radius, output_type='ndarray')
    return near['i'].astype(np.intp), near['j'].astype(np.intp), 1


def compute_rdf(frames, col_idx, type_a=1, type_b=2, r_max=6.0, n_bins=200,
                max_frames=20, label_a='Fe', label_b='O', z_pbc=False):
    """
    Compute the radial distribution function g(r) between two atom types.

    The RDF describes how atomic density varies as a function of distance
    from a reference atom. It reveals characteristic bond lengths and
    coordination shells. For Fe-O systems, the first peak position
    indicates the oxide phase:
        - ~1.76 A → amorphous FeO
        - ~1.95 A → Fe₂O₃ (hematite)
        - ~2.06 A → Fe₃O₄ (magnetite)
        - ~2.16 A → FeO (wustite)

    Algorithm:
    1. For each reference atom of type_a, compute distances to all type_b atoms
    2. Apply minimum image convention (PBC) for x and y directions
    3. Histogram the distances into radial bins
    4. Normalize by ideal gas density: g(r) = hist / (N_frames * N_a * shell_vol * rho_b)

    With scipy, a periodic cKDTree finds the candidate pairs within r_max and
    their distances are recomputed with the same minimum-image formula as the
    brute-force fallback (used without scipy), so both paths bin identically.

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

    Returns:
        dict with keys:
            'r'        : np.array — Bin center distances (Angstroms)
            'g'        : np.array — Normalized RDF values g(r)
            'label'    : str      — Pair label (e.g., 'Fe-O')
            'n_frames' : int      — Number of frames used in averaging
    """
    def type_set(selection):
        if isinstance(selection, (int, np.integer)):
            members = [selection]
        else:
            try:
                members = list(selection)
            except TypeError:
                raise ValueError('RDF selections must be integer type IDs or iterables of type IDs') from None
        if not members or any(isinstance(t, (bool, np.bool_))
                              or not isinstance(t, (int, np.integer)) or t <= 0
                              for t in members):
            raise ValueError('RDF selections must contain positive integer type IDs')
        return frozenset(map(int, members))

    types_a, types_b = type_set(type_a), type_set(type_b)
    same_species = types_a == types_b
    xi, yi, zi, ti = col_idx['x'], col_idx['y'], col_idx['z'], col_idx['type']
    dr = r_max / n_bins       # Bin width in Angstroms
    hist_total = np.zeros(n_bins)  # Accumulated distance histogram across all frames
    n_frames_used = 0         # Number of frames contributing to the average
    n_a_last = 0              # Number of type_a atoms (for normalization)
    n_b_last = 0              # Number of type_b atoms (for density calculation)
    vol_last = 0              # Box volume (for ideal gas normalization)

    # Use only the last max_frames frames to focus on equilibrated data
    use_frames = frames[-max_frames:] if len(frames) > max_frames else frames

    for fr in use_frames:
        atoms = fr['atoms']
        types = atoms[:, ti].astype(int)
        # Keep singleton arithmetic unchanged while allowing explicit unions.
        mask_a = types == next(iter(types_a)) if len(types_a) == 1 else np.isin(types, list(types_a))
        mask_b = types == next(iter(types_b)) if len(types_b) == 1 else np.isin(types, list(types_b))

        # Extract xyz positions for both species
        pos_a = atoms[mask_a][:, [xi, yi, zi]]
        pos_b = atoms[mask_b][:, [xi, yi, zi]]

        if len(pos_a) == 0 or len(pos_b) == 0:
            continue  # Skip frames with no atoms of either type

        box = fr['box']
        L = box[:, 1] - box[:, 0]  # Box lengths [Lx, Ly, Lz]
        n_a_last = len(pos_a)
        n_b_last = len(pos_b)
        vol_last = L[0] * L[1] * L[2]  # Total box volume

        pairs = _rdf_candidate_pairs(pos_a, pos_b, box, r_max, z_pbc,
                                     same_species=same_species)
        if pairs is not None:
            # cKDTree only nominates pairs; distances are recomputed below with
            # the brute-force formula so every r lands in the same bin as before.
            ia, ib, weight = pairs
            d = pos_b[ib] - pos_a[ia]
            d[:, 0] -= L[0] * np.round(d[:, 0] / L[0])
            d[:, 1] -= L[1] * np.round(d[:, 1] / L[1])
            if z_pbc:
                d[:, 2] -= L[2] * np.round(d[:, 2] / L[2])
            r = np.linalg.norm(d, axis=1)
            valid = (r > 0) & (r < r_max)
            bi = (r[valid] / dr).astype(int)
            bi = bi[bi < n_bins]
            hist_total += weight * np.bincount(bi, minlength=n_bins)
            n_frames_used += 1
            continue

        # --- Vectorized brute-force with minimum image convention ---
        # For each type_a atom, compute distances to ALL type_b atoms
        # simultaneously using NumPy broadcasting.
        for p in pos_a:
            d = pos_b - p  # Displacement vectors (N_b x 3)
            # Apply periodic boundary conditions in x and y directions
            # using the minimum image convention: d -= L * round(d/L)
            d[:, 0] -= L[0] * np.round(d[:, 0] / L[0])
            d[:, 1] -= L[1] * np.round(d[:, 1] / L[1])
            # Z-direction: apply PBC by default; set z_pbc=False for slab geometries
            if z_pbc:
                d[:, 2] -= L[2] * np.round(d[:, 2] / L[2])
            r = np.linalg.norm(d, axis=1)  # Scalar distances
            valid = (r > 0) & (r < r_max)  # Exclude self (r=0) and beyond cutoff
            bi = (r[valid] / dr).astype(int)  # Map distances to bin indices
            bi = bi[bi < n_bins]  # Guard against edge case at r_max boundary
            np.add.at(hist_total, bi, 1)  # Unbuffered increment (handles duplicates)

        n_frames_used += 1

    # Return empty RDF if no valid frames were processed
    if n_frames_used == 0 or n_a_last == 0:
        r_centers = np.linspace(dr / 2, r_max - dr / 2, n_bins)
        return {'r': r_centers, 'g': np.zeros(n_bins),
                'label': f'{label_a}-{label_b}', 'n_frames': 0}

    # --- RDF Normalization ---
    # g(r) = observed_count / expected_count_for_ideal_gas
    # expected = N_frames * N_a * shell_volume(r) * number_density_b
    bins_edge = np.linspace(0, r_max, n_bins + 1)
    r_centers = (bins_edge[:-1] + bins_edge[1:]) / 2
    # Volume of each spherical shell: V_shell = 4/3 * pi * (r_outer^3 - r_inner^3)
    shell_vol = (4 / 3) * np.pi * (bins_edge[1:] ** 3 - bins_edge[:-1] ** 3)
    rho_b = n_b_last / vol_last  # Average number density of type_b
    g = hist_total / (n_frames_used * n_a_last * shell_vol * rho_b)
    # Preserve the historical same-species normalization for both singletons
    # and equal sets. PHYS-4 changes selection only, not this convention.
    if same_species:
        g /= 2

    return {'r': r_centers, 'g': g, 'label': f'{label_a}-{label_b}',
            'n_frames': n_frames_used}


def compute_oar(frames, col_idx, z_surf, dt_fs=0.25, o_type=2):
    """
    Compute the Oxygen Absorption Rate (OAR) over time.

    OAR is defined as the fraction of O atoms that have penetrated below
    the Fe surface z-coordinate. An OAR of 0.5 means 50% of O atoms are
    below the surface. This metric quantifies the progress of oxidation —
    a rising OAR indicates ongoing O absorption into the Fe slab.

    Args:
        frames:  list[dict] — Trajectory frames
        col_idx: dict       — Column index mapping
        z_surf:  float      — z-coordinate of the Fe surface (Angstroms)
        dt_fs:   float      — Timestep in femtoseconds
        o_type:  int        — Atom type number for oxygen

    Returns:
        dict with keys:
            'time'       : np.array — Time in picoseconds
            'oar'        : np.array — Oxygen absorption rate (0 to 1)
            'n_absorbed' : np.array — Count of O atoms below surface
            'n_total'    : np.array — Total O atom count per frame
    """
    ti = col_idx['type']
    zi = col_idx['z']

    time, oar, n_abs, n_total = [], [], [], []
    for fr in frames:
        atoms = fr['atoms']
        types = atoms[:, ti].astype(int)
        o_mask = types == o_type
        o_z = atoms[o_mask, zi]
        n_o = len(o_z)
        n_below = int(np.sum(o_z < z_surf))

        time.append(fr['timestep'] * dt_fs / 1000)
        n_abs.append(n_below)
        n_total.append(n_o)
        oar.append(n_below / n_o if n_o > 0 else 0)

    return {'time': np.array(time), 'oar': np.array(oar),
            'n_absorbed': np.array(n_abs), 'n_total': np.array(n_total)}


def compute_or(frames, col_idx, dt_fs=0.25, q_thr=Q_OXIDIZED_E, z_range=None):
    """
    Compute the Oxidation Rate (OR) over time. ReaxFF-only.

    OR is the fraction of Fe atoms whose partial charge exceeds q_thr.
    This is a direct measure of how many Fe atoms have been oxidized.
    Unlike OAR (which counts O positions), OR uses charge information
    to identify actual chemical bonding/electron transfer.

    Args:
        frames:  list[dict] — Trajectory frames
        col_idx: dict       — Column index mapping
        dt_fs:   float      — Timestep in femtoseconds
        q_thr:   float      — Charge threshold for oxidized Fe (default: 0.3 e)
        z_range: tuple or None — Optional (zlo, zhi) to restrict analysis

    Returns:
        dict with keys:
            'time' : np.array — Time in picoseconds
            'or'   : np.array — Oxidation rate (0 to 1) per frame
        Returns None if no charge column is available.
    """
    ti = col_idx['type']
    zi = col_idx.get('z')
    qi = col_idx.get('q')
    if qi is None:
        return None

    time, vals = [], []
    for fr in frames:
        atoms = fr['atoms']
        fe_mask = atoms[:, ti].astype(int) == 1
        if z_range is not None and zi is not None:
            z = atoms[:, zi]
            fe_mask &= (z >= z_range[0]) & (z <= z_range[1])
        qs = atoms[fe_mask, qi]
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

    Args:
        frames:    list[dict] — Trajectory frames
        col_idx:   dict       — Column index mapping
        surface_z: float      — z-coordinate of the Fe surface (Angstroms)
        dt_fs:     float      — Timestep in femtoseconds
        o_type:    int        — Atom type number for oxygen

    Returns:
        dict with keys:
            'time'              : np.array — Time in picoseconds
            'o_min_z'           : np.array — Minimum O z-coordinate per frame
            'n_adsorbed'        : np.array — O atoms below surface_z
            'n_near_surface'    : np.array — O atoms within 3 A of surface
            'n_total_o'         : np.array — Total O atom count
            'frac_adsorbed'     : np.array — Fraction of O below surface
            'frac_near_surface' : np.array — Fraction of O near surface
            'surface_z'         : float    — The surface z used
    """
    ti = col_idx['type']
    zi = col_idx['z']

    time, o_min_z, n_ads, n_near, n_total = [], [], [], [], []
    for fr in frames:
        atoms = fr['atoms']
        o_mask = atoms[:, ti].astype(int) == o_type
        o_z = atoms[o_mask, zi]

        if len(o_z) == 0:
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
    single-panel line graphs that clearly show oxidation progress.

    Args:
        frames:    list[dict] — Trajectory frames
        col_idx:   dict       — Column index mapping
        surface_z: float      — z-coordinate of the Fe surface (Angstroms)
        dt_fs:     float      — Timestep in femtoseconds
        o_type:    int        — Atom type number for oxygen
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
    """
    ti = col_idx['type']
    zi = col_idx['z']

    time_arr, ads_ratio, mean_z, std_z, max_depth = [], [], [], [], []

    for fr in frames:
        atoms = fr['atoms']
        o_mask = atoms[:, ti].astype(int) == o_type
        o_z = atoms[o_mask, zi]
        if len(o_z) == 0:
            continue
        time_arr.append(fr['timestep'] * dt_fs / 1000)
        ads_ratio.append(np.mean(o_z < surface_z))
        mean_z.append(np.mean(o_z))
        std_z.append(np.std(o_z))
        max_depth.append(max(0.0, surface_z - np.min(o_z)))

    if not time_arr:
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

    Args:
        frames:       list[dict] — Trajectory frames
        col_idx:      dict       — Column index mapping
        z_range:      tuple or None — (zlo, zhi) range; auto-detected if None
        n_bins:       int   — Number of z-bins (default: 200)
        species_type: int or None — Atom type to filter (None = all atoms)
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

    for fr in frames:
        atoms = fr['atoms']
        if species_type is not None:
            mask = atoms[:, ti].astype(int) == species_type
            z_coords = atoms[mask, zi]
        else:
            z_coords = atoms[:, zi]

        Lx = fr['box'][0][1] - fr['box'][0][0]
        Ly = fr['box'][1][1] - fr['box'][1][0]
        area = Lx * Ly

        h, _ = np.histogram(z_coords, bins=n_bins, range=z_range)
        density_sum += h / (area * dz)
        n_used += 1

    density_avg = density_sum / n_used if n_used > 0 else density_sum

    return {'z': z_bins, 'density': density_avg, 'species': species_name,
            'n_frames': n_used}


def detect_o2_dissociation(frames, col_idx, bond_cutoff=O2_BOND_CUTOFF_A, dt_fs=1.0, o_type=2):
    """
    Track O₂ molecule dissociation over time by detecting O-O bonds.

    An O atom is considered part of an O₂ molecule if its nearest O neighbor
    is within bond_cutoff (default 1.8 A, compared to O₂ bond length ~1.21 A).
    Dissociated O atoms are those NOT bonded to any other O atom.

    Algorithm:
    1. Extract all O atom positions for each frame
    2. Find all O-O pairs within bond_cutoff using either:
       - scipy.cKDTree (O(N log N)) when available and N > 20
       - Brute-force pairwise distances (O(N²)) as fallback
    3. Apply greedy pairing: sort pairs by distance, assign closest first
       (each O can only belong to one O₂ molecule)
    4. Unpaired O atoms are classified as "dissociated"

    This analysis reveals the kinetics of O₂ dissociation on the Fe surface —
    a critical first step in the oxidation process.

    Args:
        frames:      list[dict] — Trajectory frames
        col_idx:     dict       — Column index mapping
        bond_cutoff: float      — Maximum O-O distance to consider bonded (A)
        dt_fs:       float      — Timestep in femtoseconds
        o_type:      int        — Atom type number for oxygen

    Returns:
        dict with keys:
            'time'            : np.array — Time in picoseconds
            'n_o2'            : np.array — Number of O₂ molecules per frame
            'n_dissociated'   : np.array — Number of unpaired O atoms
            'n_total_o'       : np.array — Total O atom count
            'frac_in_o2'      : np.array — Fraction of O atoms in O₂ (0 to 1)
            'frac_dissociated': np.array — Fraction of dissociated O atoms
    """
    ti = col_idx['type']
    xi, yi, zi_col = col_idx['x'], col_idx['y'], col_idx['z']

    time, n_o2_list, n_diss_list, n_total_list = [], [], [], []

    for fr in frames:
        atoms = fr['atoms']
        box = fr['box']
        L = box[:, 1] - box[:, 0]
        o_mask = atoms[:, ti].astype(int) == o_type
        o_pos = atoms[o_mask][:, [xi, yi, zi_col]]
        n_o = len(o_pos)

        if n_o < 2:
            if n_o > 0:
                time.append(fr['timestep'] * dt_fs / 1000)
                n_o2_list.append(0)
                n_diss_list.append(n_o)
                n_total_list.append(n_o)
            continue

        bonded = np.zeros(n_o, dtype=bool)  # Track which O atoms are paired
        n_o2 = 0  # Count of detected O₂ molecules

        # Lazy import: only load scipy when actually needed for O2 detection
        try:
            from scipy.spatial import cKDTree
            _has_scipy = True
        except ImportError:
            _has_scipy = False

        if _has_scipy and n_o > 20:
            # --- Fast path: scipy cKDTree for neighbor finding ---
            # Wrap O positions into the primary box image for consistent
            # distance queries (cKDTree doesn't handle PBC natively).
            pos_wrapped = o_pos.copy()
            box_lo = box[:, 0]  # [xlo, ylo, zlo]
            pos_wrapped[:, 0] = (pos_wrapped[:, 0] - box_lo[0]) % L[0] + box_lo[0]
            pos_wrapped[:, 1] = (pos_wrapped[:, 1] - box_lo[1]) % L[1] + box_lo[1]
            # Build KD-tree and find all pairs within bond_cutoff.
            # Note: this may miss pairs across PBC boundaries, but the
            # subsequent PBC distance recalculation catches them.
            tree = cKDTree(pos_wrapped)
            pairs = tree.query_pairs(bond_cutoff, output_type='ndarray')
            if len(pairs) > 0:
                # Recalculate distances with proper PBC (minimum image convention)
                dr = o_pos[pairs[:, 1]] - o_pos[pairs[:, 0]]
                dr[:, 0] -= L[0] * np.round(dr[:, 0] / L[0])
                dr[:, 1] -= L[1] * np.round(dr[:, 1] / L[1])
                dists = np.linalg.norm(dr, axis=1)
                valid = dists < bond_cutoff

                # Greedy pairing: assign closest pairs first to avoid
                # incorrect pairings in dense O regions. Each O atom
                # can belong to at most one O₂ molecule.
                valid_pairs = pairs[valid]
                valid_dists = dists[valid]
                order = np.argsort(valid_dists)  # Shortest distance first
                for idx in order:
                    i, j = valid_pairs[idx]
                    if not bonded[i] and not bonded[j]:
                        bonded[i] = True
                        bonded[j] = True
                        n_o2 += 1
        else:
            # --- Slow path: O(N²) brute-force pairwise distance check ---
            # Used when scipy is not available or for small O atom counts.
            for i in range(n_o):
                if bonded[i]:
                    continue  # Already paired
                best_j = -1
                best_dist = bond_cutoff
                for j in range(i + 1, n_o):
                    if bonded[j]:
                        continue
                    dr = o_pos[j] - o_pos[i]
                    # Minimum image convention for x and y
                    dr[0] -= L[0] * np.round(dr[0] / L[0])
                    dr[1] -= L[1] * np.round(dr[1] / L[1])
                    dist = np.linalg.norm(dr)
                    if dist < best_dist:
                        best_dist = dist
                        best_j = j
                if best_j >= 0:
                    bonded[i] = True
                    bonded[best_j] = True
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
      - Type 1 = Fe_up   (spin-up, majority spin in magnetite)
      - Type 2 = Fe_down (spin-down, minority spin / 'Mn' proxy)
      - Type 3 = O       (oxygen, non-magnetic)

    The spin-up fraction (n_up / n_total_Fe) reveals the magnetic ordering:
      - ~1/3 → Fe₃O₄ inverse spinel (8 tetrahedral Fe↓ : 16 octahedral Fe↑)
      - ~0.5 → Antiferromagnetic equal distribution
      - ~1.0 → Ferromagnetic (all spins aligned)

    MC atom/swap moves dynamically adjust spin states during the simulation,
    so this function tracks how the magnetic structure equilibrates.

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
    Wrapped coordinates must be sampled often enough that each periodic step is
    less than half a box length. Only orthogonal (3, 2) bounds are supported;
    this routine does not reconstruct tilt discarded by an upstream reader.
    Geometry with retained triclinic bounds is rejected, not approximated.

    Args:
        frames: list-like trajectory with at least two frames.
        col_idx: numeric column indices, including id, type, x, y and z.
        species_type: integer type ID, iterable of type IDs, or None for all
            atoms initially present. This is an initial-cohort MSD, not a
            time-dependent population or spin-channel MSD.
        dt_fs: timestep in femtoseconds; output time is in picoseconds.
        pbc: three booleans for x/y/z unwrapping. The historical slab default
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
        box = np.asarray(frame['box'], dtype=float)
        if box.shape != (3, 2):
            raise ValueError(f"MSD timestep {frame['timestep']}: requires orthogonal (3, 2) box bounds; "
                             'triclinic geometry is unsupported')
        lengths = box[:, 1] - box[:, 0]
        if (not np.all(np.isfinite(box)) or not np.all(np.isfinite(lengths))
                or np.any(lengths <= 0)):
            raise ValueError(f"MSD timestep {frame['timestep']}: box lengths must be finite and positive")
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

        delta = cur_pos - prev_pos
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
    (min/max/mean). This reveals the spatial distribution of different
    species along the z-axis — useful for identifying oxide layer
    thickness, interfacial mixing, and structural ordering.

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
                                 surface_percentile=95):
    """
    Detailed oxygen penetration profiling: tracks per-atom O trajectories,
    z-distribution evolution, and adsorption timeline.

    Collects the z-coordinate of every O atom at every frame, sorted by
    atom ID for consistent tracking. Also records the Fe surface position
    (95th percentile of Fe z-coords) per frame.

    This provides the raw data for four visualization modes:
      1. Individual O atom z-trajectories (spaghetti plot)
      2. O density kymograph (z vs time heatmap)
      3. z-distribution evolution (ridge/waterfall plot)
      4. O adsorption timeline (cumulative surface crossing)

    Args:
        frames:              list[dict] — Trajectory frames
        col_idx:             dict       — Column index mapping
        dt_fs:               float      — Timestep in femtoseconds
        o_type:              int        — Atom type number for oxygen
        surface_percentile:  float      — Percentile of Fe z-coords for surface (default 95)

    Returns:
        dict with keys:
            'time'       : np.array shape (N,)       — Time in ps
            'o_z_traj'   : np.array shape (N, N_o)   — z of each O atom per frame
            'o_ids'      : np.array shape (N_o,)     — O atom IDs (for tracking)
            'surface_z'  : np.array shape (N,)       — Fe surface z per frame
            'min_o_z'    : np.array shape (N,)       — Deepest O z per frame
            'n_o'        : int                       — Number of O atoms
            'cross_times': np.array                  — Time (ps) each O first crossed surface
        Returns None if no O atoms found or fewer than 2 frames.
    """
    ti = col_idx['type']
    zi = col_idx['z']
    idi = col_idx.get('id')

    if len(frames) < 2:
        return None

    t0 = frames[0]['timestep']

    # Determine Fe type numbers (everything that is not o_type)
    first_types = frames[0]['atoms'][:, ti].astype(int)
    fe_types = sorted(set(first_types) - {o_type})

    # First pass: check O atom count
    o_mask0 = first_types == o_type
    n_o = int(np.sum(o_mask0))
    if n_o == 0:
        return None

    # Collect trajectories
    time_arr = []
    o_z_traj = []
    surface_arr = []
    o_ids = None

    for fr in frames:
        atoms = fr['atoms']
        types = atoms[:, ti].astype(int)
        o_mask = types == o_type
        fe_mask = np.isin(types, fe_types)

        o_atoms = atoms[o_mask]
        if len(o_atoms) != n_o:
            continue  # Skip frames with different O count

        # Sort by ID for consistent tracking
        if idi is not None:
            order = np.argsort(o_atoms[:, idi])
            o_z = o_atoms[order, zi]
            if o_ids is None:
                o_ids = o_atoms[order, idi].astype(int)
        else:
            o_z = o_atoms[:, zi]

        fe_z = atoms[fe_mask, zi]
        surface = float(np.max(fe_z) - SURFACE_OFFSET_A) if len(fe_z) > 0 else 0.0

        time_arr.append((fr['timestep'] - t0) * dt_fs / 1000.0)
        o_z_traj.append(o_z)
        surface_arr.append(surface)

    if len(time_arr) < 2:
        return None

    time_arr = np.array(time_arr)
    o_z_traj = np.array(o_z_traj)  # (n_frames, n_o)
    surface_arr = np.array(surface_arr)
    min_o_z = np.min(o_z_traj, axis=1)

    if o_ids is None:
        o_ids = np.arange(n_o)

    # Compute adsorption timeline: when each O first crosses the surface
    cross_times = []
    for j in range(n_o):
        below = o_z_traj[:, j] < surface_arr
        if np.any(below):
            cross_times.append(time_arr[np.argmax(below)])
    cross_times = np.sort(cross_times) if cross_times else np.array([])

    return {
        'time': time_arr,
        'o_z_traj': o_z_traj,
        'o_ids': o_ids,
        'surface_z': surface_arr,
        'min_o_z': min_o_z,
        'n_o': n_o,
        'cross_times': cross_times,
    }


