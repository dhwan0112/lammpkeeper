"""
Structure builders for lammps-pre.

Generates Fe slabs, computes region boundaries, and places O2 molecules.
Logic adapted from lammps/templates/generate_slab_o2.py.
"""

import numpy as np
from dataclasses import dataclass, field

try:
    from ase.build import bcc100, bcc110, bcc111
    HAS_ASE = True
except ImportError:
    HAS_ASE = False

from lammps_pre.display import progress_msg, C


# ═══════════════════════════════════════════════════════════════
# Build Result
# ═══════════════════════════════════════════════════════════════

@dataclass
class BuildResult:
    """Container for a completed structure build."""
    fe_positions: np.ndarray       # (N_Fe, 3)
    o2_positions: np.ndarray       # (N_O, 3)
    cell: np.ndarray               # (3, 3)
    regions: dict                  # region boundaries and counts
    box: tuple                     # (xlo, xhi, ylo, yhi, zlo, zhi)
    n_atoms: int                   # total atom count
    unique_z: list = field(default_factory=list)  # slab layer z-coords
    geometry_signature: tuple = None  # settings used for this build


# ═══════════════════════════════════════════════════════════════
# 1. Fe Slab
# ═══════════════════════════════════════════════════════════════

def build_fe_slab(state):
    """
    Build a BCC Fe slab using ASE (or manual fallback for 100).

    Returns dict with 'positions', 'cell', 'n_atoms', 'unique_z'.
    """
    miller = state.surface
    nx, ny, nz = state.nx, state.ny, state.nz
    a_fe = state.a_fe

    if any(not isinstance(n, (int, np.integer)) or isinstance(n, bool) or n < 1
           for n in (nx, ny, nz)):
        print(C.err('  Error: slab dimensions must be positive integers'))
        return None
    if not np.isfinite(a_fe) or a_fe <= 0:
        print(C.err('  Error: lattice constant must be finite and positive'))
        return None
    # The legacy writer emits a rectangular box. Even-width perfect surface
    # repeats are compatible with it; odd widths retain a real lateral tilt.
    if miller in ('110', '111') and ny % 2:
        print(C.err(f'  Error: Fe({miller}) requires even ny for the supported '
                    'orthogonal output; odd ny would lose cell tilt'))
        return None

    if HAS_ASE:
        builders = {'100': bcc100, '110': bcc110, '111': bcc111}
        if miller not in builders:
            print(C.err(f"  Unsupported Miller index: {miller}"))
            return None
        slab = builders[miller]('Fe', size=(nx, ny, nz), a=a_fe, vacuum=0)
        positions = slab.positions.copy()
        cell = slab.cell.array.copy()
    else:
        if miller != '100':
            print(C.err(f"  ASE required for Fe({miller}). Install: pip install ase"))
            return None
        # Manual BCC(100) generation
        layer_spacing = a_fe / 2.0
        positions = []
        for iz in range(nz):
            for ix in range(nx):
                for iy in range(ny):
                    z = iz * layer_spacing
                    if iz % 2 == 0:
                        x, y = ix * a_fe, iy * a_fe
                    else:
                        x, y = ix * a_fe + a_fe / 2, iy * a_fe + a_fe / 2
                    positions.append([x, y, z])
        positions = np.array(positions)
        cell = np.diag([nx * a_fe, ny * a_fe, nz * layer_spacing])

    # Shift slab so bottom is at z=0
    positions[:, 2] -= positions[:, 2].min()

    # Detect unique layers
    unique_z = _detect_layers(positions[:, 2])

    return {
        'positions': positions,
        'cell': cell,
        'n_atoms': len(positions),
        'unique_z': unique_z,
    }


def _detect_layers(z_coords, tol=0.3):
    """Detect unique z-layers with tolerance."""
    unique_z = []
    for z in np.sort(z_coords):
        if not unique_z or abs(z - unique_z[-1]) > tol:
            unique_z.append(z)
    return unique_z


# ═══════════════════════════════════════════════════════════════
# 2. Region Computation
# ═══════════════════════════════════════════════════════════════

def compute_regions(slab_data, state):
    """
    Compute 4-zone region boundaries from slab geometry.

    Zones (bottom to top):
        Fixed    : z < z_fixed_top          (setforce 0)
        Lower NVT: z_fixed_top..z_lower_nvt_top (thermostat)
        NVE      : z_lower_nvt_top..z_nve_top   (reaction zone)
        Upper NVT: z > z_wall_lower         (O2 gas thermostat)

    Returns dict with boundary z-coordinates and atom counts per zone.
    """
    fe_positions = slab_data['positions']
    unique_z = slab_data['unique_z']
    n_layers = len(unique_z)
    z_coords = fe_positions[:, 2]

    n_fix = state.n_fixed_layers
    n_nvt = state.n_thermostat_layers
    # Shared across force fields on purpose — using this force field's own rc
    # would make the O2 layer and the box height force-field dependent, and the
    # comparison assumes identical coordinates. See state.WALL_CUTOFF.
    rc = state.wall_cutoff

    if any(not isinstance(n, (int, np.integer)) or isinstance(n, bool) or n < 1
           for n in (n_fix, n_nvt)):
        print(C.err('  Error: fixed and NVT layer counts must be positive integers '
                    '(zero layers are not supported)'))
        return None
    if n_fix + n_nvt >= n_layers:
        print(C.err(f"  Error: fixed({n_fix}) + NVT({n_nvt}) >= total layers({n_layers})"))
        return None

    n_nve_layers = n_layers - n_fix - n_nvt

    # Boundaries at midpoints between adjacent layers
    z_fixed_top = (unique_z[n_fix - 1] + unique_z[n_fix]) / 2
    z_lower_nvt_top = (unique_z[n_fix + n_nvt - 1] + unique_z[n_fix + n_nvt]) / 2
    z_nve_top = unique_z[-1] + 0.5
    z_wall_lower = z_nve_top + rc + 0.9

    # Atom counts per zone
    n_fixed = int(np.sum(z_coords < z_fixed_top))
    n_lower_nvt = int(np.sum((z_coords >= z_fixed_top) & (z_coords < z_lower_nvt_top)))
    n_nve = int(np.sum(z_coords >= z_lower_nvt_top))

    return {
        'z_fixed_top': z_fixed_top,
        'z_lower_nvt_top': z_lower_nvt_top,
        'z_nve_top': z_nve_top,
        'z_wall_lower': z_wall_lower,
        'n_fixed': n_fixed,
        'n_lower_nvt': n_lower_nvt,
        'n_nve': n_nve,
        'n_layers': n_layers,
        'n_fixed_layers': n_fix,
        'n_thermostat_layers': n_nvt,
        'n_nve_layers': n_nve_layers,
        'surface_z': unique_z[-1],
    }


# ═══════════════════════════════════════════════════════════════
# 3. O2 Placement
# ═══════════════════════════════════════════════════════════════

def place_o2(slab_data, regions, state):
    """
    Place O2 molecules with random orientations in the gas region.

    O2 molecules are placed between z_wall_lower+1.0 and
    z_wall_lower+vacuum-2.0, with PBC-aware minimum separation.
    """
    n_mol = state.n_o2
    if not isinstance(n_mol, (int, np.integer)) or isinstance(n_mol, bool) or n_mol < 0:
        raise ValueError('O2 count must be a nonnegative integer')
    if not np.isfinite(state.vacuum) or state.vacuum <= 0:
        raise ValueError('vacuum must be finite and positive')
    if n_mol == 0:
        return np.zeros((0, 3))

    cell = slab_data['cell']
    Lx, Ly = cell[0][0], cell[1][1]
    z_lo = regions['z_wall_lower'] + 1.0
    z_hi = regions['z_wall_lower'] + state.vacuum - 2.0

    if z_hi <= z_lo:
        raise ValueError('vacuum too small for O2 placement')

    rng = np.random.default_rng(state.seed)
    bond = state.o2_bond
    min_sep = state.o2_separation
    if not np.isfinite(bond) or bond <= 0 or not np.isfinite(min_sep) or min_sep <= 0:
        raise ValueError('O2 bond length and separation must be finite and positive')

    centers = []
    max_trials = n_mol * 1000
    for _ in range(max_trials):
        if len(centers) >= n_mol:
            break
        c = np.array([rng.uniform(0, Lx), rng.uniform(0, Ly),
                       rng.uniform(z_lo, z_hi)])
        ok = True
        for e in centers:
            dx = c - e
            dx[0] -= Lx * round(dx[0] / Lx)
            dx[1] -= Ly * round(dx[1] / Ly)
            if np.linalg.norm(dx) < min_sep:
                ok = False
                break
        if ok:
            centers.append(c)

    if len(centers) < n_mol:
        raise ValueError(f'could only place {len(centers)}/{n_mol} O2 molecules; '
                         'increase vacuum or reduce count/separation')

    o_positions = []
    for c in centers:
        # Uniform solid angle: cos(theta), not theta, must be uniform.
        cos_theta = rng.uniform(-1.0, 1.0)
        phi = rng.uniform(0, 2 * np.pi)
        sin_theta = np.sqrt(max(0.0, 1.0 - cos_theta * cos_theta))
        d = np.array([sin_theta * np.cos(phi),
                       sin_theta * np.sin(phi), cos_theta])
        half = d * bond / 2
        o_positions.extend([c + half, c - half])

    return np.array(o_positions) if o_positions else np.zeros((0, 3))


# ═══════════════════════════════════════════════════════════════
# 4. Build All
# ═══════════════════════════════════════════════════════════════

def build_all(state):
    """
    Full build pipeline: slab -> regions -> O2 -> BuildResult.
    """
    # Never leave a previously successful build usable after a failed rebuild.
    state.build_result = None
    # 1. Fe slab
    progress_msg(f"Building Fe({state.surface}) slab: "
                 f"{state.nx}x{state.ny}x{state.nz} (a={state.a_fe} A)...")
    slab = build_fe_slab(state)
    if slab is None:
        return None

    n_fe = slab['n_atoms']
    cell = slab['cell']
    progress_msg(f"Slab: {n_fe} Fe atoms, box: "
                 f"{cell[0][0]:.1f} x {cell[1][1]:.1f} x "
                 f"{slab['positions'][:, 2].max():.1f} A")

    # 2. Regions
    progress_msg(f"Computing regions ({state.n_fixed_layers} fixed, "
                 f"{state.n_thermostat_layers} NVT layers)...")
    regions = compute_regions(slab, state)
    if regions is None:
        return None

    # 3. O2
    progress_msg(f"Placing {state.n_o2} O2 molecules "
                 f"({state.n_o2 * 2} O atoms)...")
    try:
        o2_pos = place_o2(slab, regions, state)
    except ValueError as exc:
        print(C.err(f'  Error: {exc}'))
        return None

    # 4. Box dimensions
    xhi, yhi = cell[0][0], cell[1][1]
    n_o = len(o2_pos)
    if n_o > 0:
        zhi = o2_pos[:, 2].max() + 5.0
    else:
        zhi = regions['z_wall_lower'] + state.vacuum

    n_total = n_fe + n_o
    progress_msg(f"Total: {C.ok(str(n_total))} atoms ({n_fe} Fe + {n_o} O)")
    progress_msg(f"Box: {xhi:.1f} x {yhi:.1f} x {zhi:.1f} A")

    result = BuildResult(
        fe_positions=slab['positions'],
        o2_positions=o2_pos,
        cell=cell,
        regions=regions,
        box=(0.0, xhi, 0.0, yhi, 0.0, zhi),
        n_atoms=n_total,
        unique_z=slab['unique_z'],
        geometry_signature=state.geometry_signature(),
    )

    state.build_result = result
    return result
