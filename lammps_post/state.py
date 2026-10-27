"""
═══════════════════════════════════════════════════════════════
Section 5: Session State
═══════════════════════════════════════════════════════════════
Central data store for the interactive session. Holds:
  - Loaded file data (dump frames, log data, data file atoms)
  - Auto-detected force field properties
  - User-configurable analysis/plot parameters
  - Cached analysis results (to avoid recomputation)

Design philosophy:
  - All loaded data is stored here (not in the shell class)
  - Analysis functions are pure: they read from state but don't modify it
  - Cache is invalidated (cleared) when input data changes
  - Settings have sensible defaults that can be overridden via 'set' commands
═══════════════════════════════════════════════════════════════
"""

import numpy as np

from lammps_post import Q_OXIDIZED_E, SURFACE_OFFSET_A

class SessionState:
    """
    Central session state container for all loaded data, settings,
    and cached analysis results.

    Design philosophy:
    - All loaded data is stored here (not in the shell class)
    - Analysis functions are pure: they read from state but don't modify it
    - Cache is invalidated (cleared) when input data changes
    - Settings have sensible defaults that can be overridden via 'set' commands
    """

    def __init__(self):
        # ── Loaded raw data ──
        # These are populated by do_load() and cleared by do_unload().
        self.dump_path = None       # Path to the loaded dump/lammpstrj file
        self.dump_frames = None     # list[dict]: parsed trajectory frames
        self.dump_columns = None    # list[str]: numeric column names
        self.dump_col_idx = None    # dict[str, int]: column name -> array index

        self.log_path = None        # Path to the loaded LAMMPS log file
        self.log_data = None        # dict: parsed thermodynamic data

        self.data_path = None       # Path to the loaded LAMMPS data file
        self.data_atoms = None      # np.array (N, 5): [id, type, x, y, z]
        self.data_box = None        # np.array (3, 2): [[xlo, xhi], ...]
        self.data_masses = None     # dict[int, float]: type -> mass

        self.input_path = None      # Path to the loaded LAMMPS input (.in) file
        self.input_config = None    # dict from parse_input(): units, boundary, type_map, etc.

        # ── Auto-detected force field properties ──
        # Populated by detect_forcefield() when a dump file is loaded.
        self.ff_info = {
            'forcefield': 'unknown',    # 'reaxff', 'ace', or 'hdnnp'
            'unit_system': 'metal',     # 'real' (ReaxFF) or 'metal' (ACE/HDNNP)
            'dt_fs': 1.0,              # Timestep in femtoseconds
            'has_charge': False,        # True if 'q' column exists
            'has_velocity': False,      # True if 'vx','vy','vz' columns exist
            'has_element': False,       # True if 'element' column exists
            'atom_types': {},           # Type ID -> name mapping
        }

        # ── User-settable analysis parameters ──
        self.surface_z = None       # Fe surface z-coordinate (A), auto-detected or manual
        self.surface_z_manual = False
        self.q_threshold = Q_OXIDIZED_E  # Charge threshold for "oxidized" Fe (e)
        self.normalize = False      # If True, plots show ratios/fractions instead of raw counts
        self.z_focus = None         # (zlo, zhi) tuple or None for full z-range in plots

        # ── Cached analysis results ──
        # Keys are analysis names (e.g., 'charge', 'rdf_Fe-O', 'density_Fe').
        # Values are the dicts returned by analysis functions.
        # Cache is cleared when input data changes (load/unload dump).
        self.cache = {}

        # ── Derived quantities ──
        self.total_mass_amu = None  # Total system mass in amu (computed from data file masses + dump atom counts)
        self.pressure_unit = 'bar'  # Pressure display unit: 'bar' or 'gpa'

        # ── Output and plot settings ──
        self.output_dir = './lammps-post_output'   # Directory for saved plots and exports
        self.dpi = 150              # Plot resolution (dots per inch)
        self.linewidth = 1.5        # Default line width for plot curves
        self.marker_size = 3        # Default scatter plot marker size
        self.font_size = 11         # Base font size for plot text
        self.grid = True            # Whether to show grid lines on plots
        self.grid_alpha = 0.3       # Grid line transparency (0=invisible, 1=opaque)
        self.fig_width = 12         # Default figure width in inches
        self.fig_height = 6         # Default figure height in inches
        self.figsize_override = None  # (w, h) tuple or None; overrides per-function defaults
        self.theme = 'default'      # Plot theme: 'default', 'publication', 'presentation'
        self.save_format = 'png'    # Output format: 'png', 'pdf', 'svg', 'both' (png+pdf)

        # ── Plot recipes: saved settings per plot type for redo/edit ──
        # Keys are plot type names (e.g., 'rdf', 'density').
        # Values are dicts of the parameters used to generate the plot.
        self.plot_recipes = {}

    # ── Convenience properties for frequently accessed ff_info fields ──

    @property
    def ff(self):
        """Short name of the detected force field (e.g., 'reaxff', 'ace')."""
        return self.ff_info['forcefield']

    @property
    def dt_fs(self):
        """Timestep in femtoseconds (0.25 for ReaxFF, 1.0 for ACE/HDNNP)."""
        return self.ff_info['dt_fs']

    @property
    def atom_types(self):
        """Atom type mapping dict (e.g., {1: 'Fe', 2: 'O'})."""
        return self.ff_info['atom_types']

    @property
    def has_charge(self):
        """Whether the dump file contains per-atom charge data."""
        return self.ff_info['has_charge']

    def clear_cache(self):
        """Clear all cached analysis results. Called when input data changes."""
        self.cache.clear()
        self._structure_atoms = None

    @property
    def pbc(self):
        """Authoritative per-axis flags, preferring trajectory metadata."""
        from lammps_post.parsers import pbc_from_boundary
        reader = getattr(self.dump_frames, 'reader', None)
        flags = pbc_from_boundary(getattr(reader, 'boundary', None))
        if flags is not None:
            return flags
        if self.input_config and self.input_config.get('boundary'):
            return tuple(b == 'p' for b in self.input_config['boundary'][:3])
        return (True, True, self.surface_z is None)

    def apply_plot_style(self):
        """
        Apply the current plot style settings to matplotlib rcParams.
        Called before generating plots so that user-modified settings
        (linewidth, font_size, grid, theme, save_format, etc.) take effect.
        First applies theme defaults, then overlays per-setting overrides.
        Also updates the module-level _SAVE_FORMAT in plotting for _save_fig().
        """
        # Lazy import to avoid circular dependency (state ↔ plotting)
        import lammps_post.plotting as _plotting
        from lammps_post import WONG_PALETTE

        _plotting._SAVE_FORMAT = self.save_format

        if _plotting.HAS_MPL:
            _plotting._setup_plot_style(self.theme)
            # Overlay user-specific overrides on top of theme
            _plotting.plt.rcParams.update({
                'font.size': self.font_size,
                'axes.labelsize': self.font_size + 1,
                'axes.titlesize': self.font_size + 2,
                'legend.fontsize': max(7, self.font_size - 2),
                'lines.linewidth': self.linewidth,
                'lines.markersize': self.marker_size,
                'axes.grid': self.grid,
                'grid.alpha': self.grid_alpha,
                'savefig.dpi': self.dpi,
                'axes.prop_cycle': _plotting.plt.cycler('color', WONG_PALETTE),
            })

    def _guess_surface_z(self):
        """
        Auto-detect the Fe surface z-coordinate from the dump data.
        Uses the maximum Fe z minus SURFACE_OFFSET_A (about half a BCC
        lattice constant, 1.4 Å) as the surface plane. This places the
        surface between the topmost Fe layer and the gas phase, so O atoms
        that enter the top Fe layer are correctly counted as adsorbed.

        Previous: 95th percentile — too conservative, misses O atoms
        interstitially absorbed between the top 2-3 Fe layers.

        Handles dumps with or without the 'type' column.
        """
        if not self.dump_frames or not self.dump_col_idx:
            return
        if 'z' not in self.dump_col_idx:
            return

        zi = self.dump_col_idx['z']
        atoms = self.dump_frames[0]['atoms']
        fr = self.dump_frames[0]

        # Strategy 1: use 'type' column if available
        if 'type' in self.dump_col_idx:
            ti = self.dump_col_idx['type']
            types = atoms[:, ti].astype(int)
            try:
                fe_type_nums = self._guess_fe_types()
            except ValueError:
                # Explicit labels without the domain species cannot define an
                # oxidation surface; do not guess from unrelated atom types.
                return
            fe_mask = np.isin(types, list(fe_type_nums))
            if np.any(fe_mask):
                fe_max = float(np.max(atoms[fe_mask, zi]))
                self.surface_z = fe_max - SURFACE_OFFSET_A
                return

        # Strategy 2: use 'element' column if available
        if fr.get('elements') is not None:
            elements = fr['elements']
            fe_mask = np.array([e in ('Fe', 'Mn') for e in elements])
            if np.any(fe_mask):
                fe_max = float(np.max(atoms[fe_mask, zi]))
                self.surface_z = fe_max - SURFACE_OFFSET_A
                return

        # Strategy 3: fallback — use max z of any atom
        self.surface_z = float(np.max(atoms[:, zi])) - SURFACE_OFFSET_A

    def _guess_fe_types(self):
        """All explicitly labeled surface species channels, including spins."""
        fe_type_nums = frozenset(t for t, n in self.atom_types.items()
                                if isinstance(t, int) and 'Fe' in str(n))
        if not fe_type_nums:
            raise ValueError('No surface species in the explicit atom type mapping')
        return fe_type_nums

    def _guess_o_type(self):
        """
        Return the oxygen type, or a frozen union for repeated labels.
        Explicit labels are authoritative; only a missing map permits a
        visibly reported legacy highest-type guess.
        """
        at = self.atom_types
        matches = frozenset(t for t, n in at.items()
                            if isinstance(t, int) and n == 'O')
        if matches:
            return next(iter(matches)) if len(matches) == 1 else matches
        if at:
            raise ValueError('No oxygen species in the explicit atom type mapping')
        # Default: highest type number from dump data
        if self.dump_frames and self.dump_col_idx and 'type' in self.dump_col_idx:
            types = self.dump_frames[0]['atoms'][:, self.dump_col_idx['type']].astype(int)
            print('  Warning: no species metadata; guessing oxygen from the highest atom type')
            return int(types.max())
        print('  Warning: no species metadata; using the legacy oxygen type default')
        return 2

    def compute_z_focus(self, margin=10.0):
        """
        Auto-compute a z-range of interest that focuses on the oxidation zone.

        Determines the relevant z-range by finding:
        - The deepest O atom penetration (minimum O z-coordinate)
        - The highest O atom position (maximum O z-coordinate)
        - The Fe surface position (95th percentile of Fe z-coords)

        Adds a margin (default 10 A) on both sides for context.
        Clamps the result to the simulation box boundaries.

        This is used by the 'set z_focus auto' command and by plotting
        functions to automatically crop plots to the interesting region,
        avoiding large empty gas-phase regions above the slab.

        Args:
            margin: float — Extra padding in Angstroms on each side.

        Returns:
            (zlo, zhi) tuple, or None if auto-detection fails.
        """
        if self.z_focus is not None:
            return self.z_focus

        if not self.dump_frames or not self.dump_col_idx:
            return None

        if 'z' not in self.dump_col_idx:
            return None

        zi = self.dump_col_idx['z']
        fr = self.dump_frames[-1]
        atoms = fr['atoms']

        # Identify O and Fe atoms (handles both type-based and element-based dumps)
        o_z = np.array([])
        fe_z = np.array([])

        if 'type' in self.dump_col_idx:
            ti = self.dump_col_idx['type']
            types = atoms[:, ti].astype(int)
            try:
                o_type = self._guess_o_type()
            except ValueError:
                return None  # A domain-specific focus is unavailable for this system.
            selection = [o_type] if np.isscalar(o_type) else list(o_type)
            o_z = atoms[np.isin(types, selection), zi]
            try:
                fe_type_nums = self._guess_fe_types()
            except ValueError:
                return None
            fe_mask = np.isin(types, list(fe_type_nums))
            fe_z = atoms[fe_mask, zi]
        elif fr.get('elements') is not None:
            elements = fr['elements']
            o_mask = np.array([e == 'O' for e in elements])
            fe_mask = np.array([e in ('Fe', 'Mn') for e in elements])
            o_z = atoms[o_mask, zi]
            fe_z = atoms[fe_mask, zi]

        if len(o_z) == 0 or len(fe_z) == 0:
            return None

        # Focus range: from deepest O penetration - margin to highest O + margin
        # Also include Fe surface region
        sz = (self.surface_z if self.surface_z is not None
              else float(np.percentile(fe_z, 95)))
        o_min = float(np.min(o_z))
        o_max = float(np.max(o_z))

        zlo = min(o_min, sz) - margin
        zhi = max(o_max, sz) + margin

        # Clamp to box
        box_zlo = self.dump_frames[-1]['box'][2][0]
        box_zhi = self.dump_frames[-1]['box'][2][1]
        zlo = max(zlo, box_zlo)
        zhi = min(zhi, box_zhi)

        return (zlo, zhi)
