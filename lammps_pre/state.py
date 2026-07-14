"""
PreState: simulation configuration container for lammps-pre.

All parameters needed to build a structure and generate LAMMPS input files
are stored here. Force-field presets auto-populate unit system, atom style,
timestep, and output fields when the user selects a force field.
"""

from lammps_pre import A_FE_BCC, O2_BOND_LENGTH
from lammpkeeper.common.mapping import type_to_label, element_order

# Element symbols in atom-type order, as LAMMPS wants them in `pair_coeff` and
# `dump_modify ... element`. Sourced from the shared mapping so the convention
# prep writes can never drift from the one post reads back.
ACE_ELEMENTS = ' '.join(element_order('ace'))       # 'Fe Mn O'

# ═══════════════════════════════════════════════════════════════
# Force Field Presets
# ═══════════════════════════════════════════════════════════════

FF_PRESETS = {
    'ace': {
        'label': 'ACE',
        'reference': 'Bienvenu et al., npj Comput. Mater. (2025) 11:81',
        'unit_system': 'metal',
        'atom_style': 'atomic',
        'pair_style': 'pace product',
        'potential_file': 'ACE_Fe-O.yace',
        'pair_coeff': f'* * ACE_Fe-O.yace {ACE_ELEMENTS}',
        'dt': 0.00025,                 # ps (metal units) = 0.25 fs
        'dt_display_fs': 0.25,
        'T_damp': 0.1,                 # ps = 100 fs
        'T_damp_display_fs': 100.0,
        'rc': 7.0,
        'atom_types': type_to_label('ace'),
        'masses': {1: 55.845, 2: 55.845, 3: 15.999},
        'has_spin': True,
        'has_qeq': False,
        'thermo_interval': 50,
        'dump_interval': 2000,
        'thermo_fields': 'step c_temp_mobile pe ke etotal pxx pyy pzz c_o_z_min c_o_z_max',
        # 'element' makes the trajectory self-describing: paired with
        # `dump_modify ... element Fe Mn O` it records the spin convention in the
        # file itself, so post reads the types back deterministically instead of
        # inferring them from atom counts.
        'dump_fields': 'id type element x y z vx vy vz',
        # Simulation time defaults (ps)
        'eq_ps': 100,
        'ox_ps': 500,
        'spin_ps': 20,
        # Minimization
        'min_etol': 1.0e-6,
        'min_ftol': 1.0e-8,
        'min_maxiter': 5000,
        'min_maxeval': 50000,
        # HPC defaults
        'ncpus': 48,
        'memory_gb': 96,
        'walltime_hr': 120,
        'nproc_x': 6,
        'nproc_y': 8,
    },
    'reaxff2010': {
        'label': 'ReaxFF-2010',
        'reference': 'Aryanpour et al., J. Phys. Chem. A 114, 6298 (2010)',
        'unit_system': 'real',
        'atom_style': 'charge',
        'pair_style': 'reaxff NULL safezone 3.0 mincap 200',
        'potential_file': 'ffield.reax.Fe_O_C_H',
        'pair_coeff': '* * ffield.reax.Fe_O_C_H Fe O',
        'dt': 0.25,                     # fs (real units)
        'dt_display_fs': 0.25,
        'T_damp': 25.0,                 # fs (= 100 * dt)
        'T_damp_display_fs': 25.0,
        'rc': 5.0,
        'atom_types': type_to_label('reaxff'),
        'masses': {1: 55.845, 2: 15.999},
        'has_spin': False,
        'has_qeq': True,
        'thermo_interval': 500,
        'dump_interval': 1000,
        'thermo_fields': 'step c_temp_mobile pe ke etotal press pxx pyy pzz c_o_z_min c_o_z_max',
        'dump_fields': 'id type x y z vx vy vz q',
        'eq_ps': 200,
        'ox_ps': 200,
        'spin_ps': 0,
        'min_etol': 1.0e-4,
        'min_ftol': 1.0e-6,
        'min_maxiter': 2000,
        'min_maxeval': 20000,
        'ncpus': 24,
        'memory_gb': 48,
        'walltime_hr': 72,
        'nproc_x': None,
        'nproc_y': None,
    },
    'reaxff2015': {
        'label': 'ReaxFF-2015',
        'reference': 'Shin et al., ACS Catal. 5, 7226 (2015)',
        'unit_system': 'real',
        'atom_style': 'charge',
        'pair_style': 'reaxff NULL safezone 3.0 mincap 200',
        'potential_file': 'ffield.reax.Shin2015',
        'pair_coeff': '* * ffield.reax.Shin2015 Fe O',
        'dt': 0.25,
        'dt_display_fs': 0.25,
        'T_damp': 25.0,
        'T_damp_display_fs': 25.0,
        'rc': 5.0,
        'atom_types': type_to_label('reaxff'),
        'masses': {1: 55.845, 2: 15.999},
        'has_spin': False,
        'has_qeq': True,
        'thermo_interval': 500,
        'dump_interval': 1000,
        'thermo_fields': 'step c_temp_mobile pe ke etotal press pxx pyy pzz c_o_z_min c_o_z_max',
        'dump_fields': 'id type x y z vx vy vz q',
        'eq_ps': 200,
        'ox_ps': 200,
        'spin_ps': 0,
        'min_etol': 1.0e-4,
        'min_ftol': 1.0e-6,
        'min_maxiter': 2000,
        'min_maxeval': 20000,
        'ncpus': 24,
        'memory_gb': 48,
        'walltime_hr': 72,
        'nproc_x': None,
        'nproc_y': None,
    },
}


# ═══════════════════════════════════════════════════════════════
# PreState
# ═══════════════════════════════════════════════════════════════

class PreState:
    """Container for all simulation setup parameters."""

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset all parameters to defaults."""
        # ── Structure ──
        self.surface = '100'
        self.nx = 10
        self.ny = 10
        self.nz = 20
        self.a_fe = A_FE_BCC
        self.n_o2 = 40
        self.o2_bond = O2_BOND_LENGTH
        self.o2_separation = 3.0
        self.vacuum = 35.0
        self.seed = 42

        # ── Regions ──
        self.n_fixed_layers = 3
        self.n_thermostat_layers = 4

        # ── Force field (populated by set_ff) ──
        self.forcefield = None
        self._ff_preset = {}

        # ── Simulation ──
        self.temperature = 300
        self.velocity_seed = 12345
        self.boundary = 'p p f'
        self.eq_ps = None       # None = use FF default
        self.ox_ps = None
        self.spin_ps = None
        self.mc_every = 10
        self.mc_n = 100

        # ── Output ──
        self.thermo_interval = None  # None = use FF default
        self.dump_interval = None
        self.dump_dense_ps = 50      # ACE only
        self.dump_dense_interval = 500

        # ── HPC ──
        self.job_name = None         # None = auto
        self.queue = 'colo-chmlu'
        self.ncpus = None
        self.memory_gb = None
        self.walltime_hr = None
        self.modules = ['gcc/9.2.0', 'openmpi/4.1.2']
        self.lammps_bin = '${HOME}/local/lammps/bin/lmp'
        self.use_scratch = True
        self.nproc_x = None
        self.nproc_y = None

        # ── Output directory ──
        self.output_dir = '.'

        # ── Build result (populated after build) ──
        self.build_result = None

        # Set default ff
        self.set_ff('reaxff2010')

    def set_ff(self, ff_name):
        """Apply a force field preset."""
        ff_name = ff_name.lower()
        if ff_name not in FF_PRESETS:
            return False
        self.forcefield = ff_name
        self._ff_preset = FF_PRESETS[ff_name]
        return True

    # ── Convenience accessors (preset with user override) ──

    @property
    def ff(self):
        return self._ff_preset

    @property
    def unit_system(self):
        return self._ff_preset.get('unit_system', 'metal')

    @property
    def atom_style(self):
        return self._ff_preset.get('atom_style', 'atomic')

    @property
    def rc(self):
        return self._ff_preset.get('rc', 5.0)

    @property
    def dt_display_fs(self):
        return self._ff_preset.get('dt_display_fs', 0.25)

    @property
    def has_spin(self):
        return self._ff_preset.get('has_spin', False)

    @property
    def has_qeq(self):
        return self._ff_preset.get('has_qeq', False)

    def get_eq_ps(self):
        return self.eq_ps if self.eq_ps is not None else self._ff_preset.get('eq_ps', 100)

    def get_ox_ps(self):
        return self.ox_ps if self.ox_ps is not None else self._ff_preset.get('ox_ps', 200)

    def get_spin_ps(self):
        return self.spin_ps if self.spin_ps is not None else self._ff_preset.get('spin_ps', 0)

    def get_thermo_interval(self):
        return self.thermo_interval if self.thermo_interval is not None else self._ff_preset.get('thermo_interval', 100)

    def get_dump_interval(self):
        return self.dump_interval if self.dump_interval is not None else self._ff_preset.get('dump_interval', 1000)

    def get_ncpus(self):
        return self.ncpus if self.ncpus is not None else self._ff_preset.get('ncpus', 24)

    def get_memory_gb(self):
        return self.memory_gb if self.memory_gb is not None else self._ff_preset.get('memory_gb', 48)

    def get_walltime_hr(self):
        return self.walltime_hr if self.walltime_hr is not None else self._ff_preset.get('walltime_hr', 72)

    def get_job_name(self):
        if self.job_name:
            return self.job_name
        ff_short = {'ace': 'ace', 'reaxff2010': 'rx2010', 'reaxff2015': 'rx2015'}
        name = ff_short.get(self.forcefield, self.forcefield)
        return f"{name}_o2_{self.n_o2}_{self.temperature}K"

    def ps_to_steps(self, ps):
        """Convert picoseconds to simulation steps."""
        if self.unit_system == 'metal':
            dt_ps = self._ff_preset['dt']
            return round(ps / dt_ps)
        else:
            dt_fs = self._ff_preset['dt']
            return round(ps * 1000.0 / dt_fs)
