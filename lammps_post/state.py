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

import warnings

import numpy as np

from lammps_post import Q_OXIDIZED_E, SURFACE_OFFSET_A

class SessionState:
    """
    Own raw inputs, mutable metadata, display settings and derived results.

    The shell owns atomic load/unload transitions. Raw typed identities are
    retained separately for input, data and consumed dump frames; inferred
    force-field metadata and legacy mutable ``ff_info`` remain compatibility
    views. Log-specific units stay attached to their own thermo source.

    Design philosophy:
    - All loaded data is stored here (not in the shell class)
    - Analysis functions are pure: they read from state but don't modify it
    - Cache is invalidated (cleared) when input data changes
    - Settings have sensible defaults that can be overridden via 'set' commands
    """

    def __init__(self):
        """Start an unloaded session with legacy Fe-O and plotting defaults."""
        # ── Loaded raw data ──
        # These are populated by do_load() and cleared by do_unload().
        self.dump_path = None       # Path to the loaded dump/lammpstrj file
        self.dump_frames = None     # LazyFrames sequence of parsed frame dictionaries
        self.dump_columns = None    # list[str]: numeric column names
        self.dump_col_idx = None    # dict[str, int]: column name -> array index

        self.log_path = None        # Path to the loaded LAMMPS log file
        self.log_data = None        # dict: parsed thermodynamic data

        self.data_path = None       # Path to the loaded LAMMPS data file
        self.data_atoms = None      # np.array (N, 5): [id, type, x, y, z]
        self.data_box = None        # np.array (3, 2): [[xlo, xhi], ...]
        self.data_cell = None       # Immutable physical cell; PBC may be unresolved
        self.data_masses = None     # dict[int, float]: type -> mass

        self.input_path = None      # Path to the loaded LAMMPS input (.in) file
        self.input_config = None    # dict from parse_input(): units, boundary, type_map, etc.
        self.manifest_path = None
        self.run_manifest = None
        # Raw identities remain source-owned, before preset display adaptation.
        self.species_sources = {}
        self._dump_ff_info = None
        self._user_species = {}
        self._species_override = None
        self._species_list_identity = None
        self._dump_type_ids = frozenset()
        self._metadata_transaction = False

        # ── Auto-detected force field properties ──
        # Detection supplies initial values, not authoritative run metadata;
        # loading input or setting values may replace them afterwards.
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
        # Metadata changes may recompute an automatic plane but preserve a
        # manual one; unloading the dump deliberately resets both fields.
        self.q_threshold = Q_OXIDIZED_E  # Charge threshold for "oxidized" Fe (e)
        self.normalize = False      # If True, plots show ratios/fractions instead of raw counts
        self.z_focus = None         # (zlo, zhi) tuple or None for full z-range in plots

        # ── Cached analysis results ──
        # Keys are analysis names (e.g., 'charge', 'rdf_Fe-O', 'density_Fe').
        # Values are the dicts returned by analysis functions.
        # Keys retain requested species labels, which may denote type unions.
        # The shell clears results on load/unload and analysis-relevant edits;
        # presentation-only settings do not invalidate numerical results.
        self.cache = {}

        # ── Derived quantities ──
        self.total_mass_amu = None  # amu; data-file atom counts/masses or a manual override
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
        self.save_format = 'png'    # Output format: 'png', 'pdf', 'svg', 'both' (PNG/PDF/SVG)

        # ── Plot recipes: saved settings per plot type for redo/edit ──
        # Keys are plot type names (e.g., 'rdf', 'density').
        # Values are dicts of the parameters used to generate the plot.
        # Recipes are session-local preferences, not cached scientific data or
        # durable run records; clear_cache() intentionally leaves them intact.
        self.plot_recipes = {}

    # ── Convenience properties for frequently accessed ff_info fields ──

    @property
    def ff(self):
        """Return the current force-field label, including explicit overrides."""
        return self.ff_info['forcefield']

    @property
    def dt_fs(self):
        """Return the session timestep in fs, not the raw native LAMMPS time unit."""
        return self.ff_info['dt_fs']

    @property
    def atom_types(self):
        """Expose type-ID labels; repeated labels and spin channels form groups."""
        return self.ff_info['atom_types']

    @property
    def species_groups(self):
        """Return manifest-owned unions without turning pending IDs into types."""
        return (self.run_manifest or {}).get('species_groups', {})

    def _combined_species(self):
        """Merge raw explicit sources, rejecting disagreements with provenance."""
        combined = {}
        identities = {}
        owners = {}
        for source in ('input', 'data', 'dump'):
            raw = self.species_sources.get(source, {})
            comparable = self._preset_identities(raw)
            for type_id, label in raw.items():
                if type_id in identities and identities[type_id] != comparable[type_id]:
                    message = (f'Conflicting species for type {type_id}: '
                               f'{owners[type_id]}={combined[type_id]!r}, '
                               f'{source}={label!r}')
                    warnings.warn(message, RuntimeWarning, stacklevel=3)
                    raise ValueError(message)
                combined.setdefault(type_id, label)
                identities.setdefault(type_id, comparable[type_id])
                owners.setdefault(type_id, source)
        for type_id, label in self._user_species.items():
            combined.setdefault(type_id, label)
        return combined

    def _preset_identities(self, raw):
        """Compare established matching proxy slots without rewriting raw evidence."""
        from lammpkeeper.common.mapping import FORCE_FIELDS
        for preset in FORCE_FIELDS.values():
            proxies = {value for element, label in preset.values() if element != label
                       for value in (element, label)}
            if (proxies.intersection(raw.values())
                    and all(t in preset and value in preset[t] for t, value in raw.items())):
                return {t: preset[t][0] for t in raw}
        return dict(raw)

    def _analysis_species(self, raw):
        """Adapt only established matching preset slots, preserving raw evidence."""
        from lammpkeeper.common.mapping import element_to_type, type_to_label
        config = self.input_config or {}
        ff = config.get('forcefield')
        if not ff or ff == 'unknown':
            ff = self.ff
        try:
            canonical = {t: element for element, t in element_to_type(ff).items()}
            labels = type_to_label(ff)
        except KeyError:
            return dict(raw)
        explicit_input = self.species_sources.get('input', {})
        complete_input = bool(explicit_input) and explicit_input == canonical
        dump = self.species_sources.get('dump', {})
        proxy_elements = {element for t, element in canonical.items()
                          if labels[t] != element}
        matching_dump = (bool(proxy_elements & set(dump.values()))
                         and all(canonical.get(t) == value for t, value in dump.items()))
        if complete_input or matching_dump:
            return {t: labels[t] if canonical.get(t) == value else value
                    for t, value in raw.items()}
        return dict(raw)

    def _known_species_ids(self, atom_types):
        """Return declared or consumed raw numeric IDs, never inferred preset keys."""
        known = set(self._combined_species())
        reader = getattr(self.dump_frames, 'reader', None)
        if reader is not None:
            known.update(reader.type_ids)
        else:
            known.update(self._dump_type_ids)
            if self._dump_ff_info is None:
                # Programmatic legacy maps without a heuristic reader are user
                # metadata, unlike synthesized element-only trajectory slots.
                known.update(atom_types)
        if self.data_masses:
            known.update(self.data_masses)
        if self.data_atoms is not None:
            known.update(self.data_atoms[:, 1].astype(int))
        if self._species_override is not None:
            known.update(self._species_override)
        return frozenset(known)

    def _validate_species(self, atom_types, allow_pending=False, declared=False):
        """Reject proven group conflicts; retain undetermined references as pending."""
        from lammpkeeper.core import SpeciesMap
        from lammpkeeper.common.mapping import make_species_map
        groups = self.species_groups
        known = self._known_species_ids(atom_types)
        if declared:
            known = known.union(atom_types)
        pending = {name: sorted(set(ids) - known)
                   for name, ids in groups.items() if set(ids) - known}
        baseline = make_species_map(atom_types, ff=self.ff).type_sets()
        if (declared or self._species_override is not None
                or (getattr(self.dump_frames, 'reader', None) is None
                    and self._dump_ff_info is None)):
            authoritative = baseline
        else:
            raw = self._combined_species()
            authoritative = make_species_map(self._analysis_species(raw), ff=self.ff).type_sets()
        for name, ids in groups.items():
            members = frozenset(ids)
            exact = authoritative.get(name)
            # Unknown additions alone do not prove a redefinition. A known
            # excluded member or a differently labelled known extra does.
            other_labels = set().union(*(selection for label, selection in authoritative.items()
                                         if label != name)) if authoritative else set()
            if (exact is not None and
                    ((name not in pending and members != exact)
                     or exact - members or ((members - exact) & other_labels))):
                raise ValueError(f'Conflicting definition for species {name!r} '
                                 f'in manifest {self.manifest_path!r}')
        if pending and not allow_pending:
            raise ValueError(f'Pending species groups in manifest {self.manifest_path!r}: '
                             f'unknown atom type IDs {pending}')
        # The constructor accepts explicit selections whose numeric IDs have
        # already been validated above. No fake chemical labels are needed for
        # raw numeric dump IDs whose species identity remains unspecified.
        baseline.update({name: ids for name, ids in groups.items() if name not in pending})
        return SpeciesMap(baseline)

    def refresh_species(self):
        """Rebuild managed labels from surviving raw sources and validate groups."""
        raw = self._combined_species()
        labels = (dict(self._species_override) if self._species_override is not None
                  else self._analysis_species(raw) if raw else dict(
                      (self._dump_ff_info or {}).get('atom_types', {})))
        self._validate_species(labels, allow_pending=True)
        self.ff_info['atom_types'] = labels

    def _invalidate_species_geometry(self):
        """Drop results and automatic geometry without recursively reading a frame."""
        self.clear_cache()
        self.z_focus = None
        if not self.surface_z_manual:
            self.surface_z = None

    def species_display_name(self, name):
        """Keep preset display names while supporting unions of unlabelled raw IDs."""
        from lammpkeeper.common.mapping import make_species_map, species_display_name
        members = self.species_map.resolve(name)
        baseline = make_species_map(self.atom_types, ff=self.ff).type_sets()
        if baseline.get(name) == members:
            return species_display_name(name, self.atom_types, ff=self.ff)
        if len(members) > 1:
            return f'{name} (types {", ".join(map(str, sorted(members)))})'
        return name

    @property
    def species_map(self):
        """Build a fresh selection snapshot, including mutable legacy metadata."""
        reader = getattr(self.dump_frames, 'reader', None)
        evidence = getattr(reader, 'type_labels', None)
        type_ids = getattr(reader, 'type_ids', frozenset())
        if evidence is not None and (evidence != self.species_sources.get('dump', {})
                                     or type_ids != self._dump_type_ids):
            old_sources = self.species_sources
            old_ids = self._dump_type_ids
            self.species_sources = dict(old_sources, dump=dict(evidence))
            self._dump_type_ids = type_ids
            try:
                self.refresh_species()
            except Exception:
                self.species_sources = old_sources
                self._dump_type_ids = old_ids
                self._invalidate_species_geometry()
                raise
            self._invalidate_species_geometry()
        elif (reader is None and isinstance(self.dump_frames, (list, tuple))
              and self._species_list_identity != (id(self.dump_frames), len(self.dump_frames),
                                                  id(self.dump_col_idx))):
            # List-based legacy callers have no reader ledger. Inspect explicit
            # numeric evidence only; element-only synthetic types stay inferred.
            evidence = {}
            raw_ids = set()
            ti = (self.dump_col_idx or {}).get('type')
            if ti is not None:
                for frame in self.dump_frames:
                    raw_ids.update(frame['atoms'][:, ti].astype(int))
                    if frame.get('elements') is None:
                        continue
                    for tid, label in zip(frame['atoms'][:, ti], frame['elements']):
                        if not np.isfinite(tid) or tid != int(tid) or tid <= 0:
                            raise ValueError(f'Invalid explicit dump atom type ID {tid!r}')
                        tid, label = int(tid), str(label)
                        if tid in evidence and evidence[tid] != label:
                            message = f'Conflicting dump species for type {tid}: '
                            message += f'{evidence[tid]!r}, {label!r}'
                            warnings.warn(message, RuntimeWarning, stacklevel=2)
                            self._invalidate_species_geometry()
                            raise ValueError(message)
                        evidence[tid] = label
            if evidence and evidence != self.species_sources.get('dump'):
                old_sources = self.species_sources
                self.species_sources = dict(self.species_sources, dump=evidence)
                try:
                    self.refresh_species()
                except Exception:
                    self.species_sources = old_sources
                    self._invalidate_species_geometry()
                    raise
                self._invalidate_species_geometry()
            self._dump_type_ids = frozenset(raw_ids)
            self._species_list_identity = (id(self.dump_frames), len(self.dump_frames),
                                           id(self.dump_col_idx))
        return self._validate_species(self.atom_types)

    @property
    def has_charge(self):
        """Whether the dump file contains per-atom charge data."""
        return self.ff_info['has_charge']

    def clear_cache(self):
        """Drop numerical results and structure arrays, retaining plot recipes."""
        self.cache.clear()
        self._structure_atoms = None

    @property
    def input_pbc(self):
        """Resolve only an explicitly parsed input boundary, never LAMMPS defaults."""
        boundary = (getattr(self, 'input_config', None) or {}).get('boundary')
        if not boundary:
            return None
        if not isinstance(boundary, (list, tuple)) or len(boundary) != 3:
            raise ValueError('Input boundary must contain exactly three axis flags')
        if any(not isinstance(flag, str) or len(flag) not in (1, 2)
               or set(flag) - set('pfsm') or ('p' in flag and flag not in ('p', 'pp'))
               for flag in boundary):
            raise ValueError('Input boundary contains invalid axis flags')
        return tuple(flag in ('p', 'pp') for flag in boundary)

    @property
    def pbc(self):
        """Resolve lattice-vector PBC from dump, input, then orthogonal legacy fallback.

        Unknown triclinic flags raise. The orthogonal fallback assumes periodic
        x/y and nonperiodic z only when a surface is known; provenance is exposed
        by shell._periodicity. Input-derived cells never own the source flags.
        """
        from lammps_post.parsers import pbc_from_boundary
        reader = getattr(getattr(self, 'dump_frames', None), 'reader', None)
        flags = pbc_from_boundary(getattr(reader, 'boundary', None))
        if flags is not None:
            return flags
        flags = SessionState.input_pbc.fget(self)
        if flags is not None:
            return flags
        if SessionState.has_triclinic_dump(self):
            raise ValueError('Triclinic PBC is unresolved: supply dump boundary flags '
                             'or load an input with an explicit boundary command')
        return (True, True, getattr(self, 'surface_z', None) is None)

    def has_triclinic_dump(self):
        """Inspect authoritative cells without interpreting physical bounds as AABBs."""
        frames = getattr(self, 'dump_frames', None)
        if not frames:
            return False
        index = getattr(getattr(frames, '_store', None), 'index', None)
        cells = getattr(index, 'cells', None)
        if cells is not None:
            return any(not cells[k].is_orthogonal for k in frames._positions)
        if index is not None and not getattr(frames.reader, 'box_model', False):
            return False  # The legacy reader itself rejects retained tilted cells.
        return any((fr.get('cell') is not None and not fr['cell'].is_orthogonal)
                   or fr.get('triclinic', False)
                   or any(np.any(np.asarray(fr.get(key, 0)) != 0)
                          for key in ('tilt', 'tilt_factors', 'xy', 'xz', 'yz'))
                   for fr in frames)

    def require_orthogonal(self, operation, include_data=False):
        """Reject unsupported slab/geometry interpretation, including manual planes."""
        if (self.has_triclinic_dump() or
                (include_data and self.data_cell is not None
                 and not self.data_cell.is_orthogonal)):
            raise ValueError(f'{operation} is orthogonal-only; triclinic geometry '
                             'is supported only for RDF and constant-cell MSD')

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

        Handles dumps with or without the 'type' column, using the first frame.
        Explicit non-Fe type metadata stops detection rather than reinterpreting
        unrelated species. Element-only legacy dumps may use Fe/Mn slots, then
        the maximum of all atoms as a last fallback. This method does not check
        the manual flag: its caller must decide whether recomputation is allowed.
        """
        if not self.dump_frames or not self.dump_col_idx:
            return
        if self.has_triclinic_dump():
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
        """Return all integer type IDs whose labels contain Fe, including spins.

        This is a legacy domain selector, not a generic element resolver. Missing
        surface labels raise so an unrelated system cannot acquire an Fe plane.
        """
        selections = self.species_map.type_sets()
        if 'Fe' in selections:
            return selections['Fe']
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
        selections = self.species_map.type_sets()
        at = self.atom_types
        matches = selections.get('O', frozenset())
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
        - The current surface plane, or the 95th percentile of Fe z-coordinates

        Adds a margin (default 10 A) on both sides for context.
        Uses the last frame and clamps to its simulation box boundaries. An
        explicit z_focus is returned unchanged; this method otherwise computes
        a suggestion without storing it or altering the surface plane.

        This is used by the 'set z_focus auto' command and by plotting
        functions to automatically crop plots to the interesting region,
        avoiding large empty gas-phase regions above the slab.

        Args:
            margin: float — Extra padding in Angstroms on each side.

        Returns:
            (zlo, zhi) tuple, or None if auto-detection fails.
        """
        self.require_orthogonal('Automatic geometry focus', include_data=True)
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
