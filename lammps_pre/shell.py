"""
Interactive cmd.Cmd shell for lammps-pre.

Provides set/build/preview/write/show commands with tab completion,
persistent command history, and colored terminal output.
"""

import cmd
import os
import shlex

from lammps_pre import VERSION
from lammps_pre.display import C, progress_msg, print_table, print_kv
from lammpkeeper.common.display import banner
from lammpkeeper.common.hosted import HostedShellMixin
from lammps_pre.state import PreState, FF_PRESETS
from lammps_pre.builders import build_all
from lammps_pre.writers import (write_all, write_data_file, write_regions_inc,
                                write_input_script, write_run_script, write_xyz,
                                get_filenames)

BANNER = '\n' + banner([
    f"{C.BOLD}LAMMPS-PRE:{C.RESET} Pre-Processing Interactive CLI  v{VERSION}",
    "Type 'help' for commands, 'quit' to exit",
]) + '\n'


class LammpsPreShell(HostedShellMixin, cmd.Cmd):
    prompt = f"\x01{C.BLUE}\x02lammps-pre>\x01{C.RESET}\x02 "
    intro = BANNER
    shell_name = 'prep'

    def __init__(self):
        super().__init__()
        self.state = PreState()
        self._setup_history('~/.lammps-pre_history')

    # ── Helper: interactive prompt ──

    def _ask(self, prompt, default=None):
        suffix = f" [{default}]" if default else ""
        try:
            ans = input(f"  \x01{C.YELLOW}\x02?\x01{C.RESET}\x02 {prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        return ans if ans else default

    # ── Path completion helper ──

    def _complete_path(self, text):
        if not text:
            text = './'
        dirname = os.path.dirname(text) or '.'
        basename = os.path.basename(text)
        try:
            entries = os.listdir(dirname)
        except OSError:
            return []
        matches = []
        for e in entries:
            if e.startswith(basename):
                full = os.path.join(dirname, e)
                if os.path.isdir(full):
                    matches.append(full + '/')
                else:
                    matches.append(full)
        return matches

    # ═══════════════════════════════════════════════════════════
    # set
    # ═══════════════════════════════════════════════════════════

    def do_set(self, arg):
        """Set a parameter: set <key> <value>

        Structure:  ff, temperature, slab, surface, o2, vacuum, lattice, seed
        Simulation: boundary, dt, eq_time, ox_time, spin_time
        Regions:    fixed_layers, nvt_layers, wall
        Output:     thermo, dump, output
        HPC:        job_name, queue, ncpus, walltime, memory
        """
        parts = shlex.split(arg) if arg.strip() else []
        if len(parts) < 2 and parts:
            # special case: 'set ff' with no value
            if parts[0] == 'ff':
                print(f"  Available: {', '.join(FF_PRESETS.keys())}")
                return
        if len(parts) < 2:
            print("  Usage: set <key> <value>")
            print("  Keys: ff, temperature, slab, surface, o2, vacuum, lattice,")
            print("        boundary, dt, eq_time, ox_time, seed, fixed_layers,")
            print("        nvt_layers, wall, thermo, dump, output, job_name,")
            print("        queue, ncpus, walltime, memory")
            return

        key = parts[0].lower()
        s = self.state

        try:
            if key == 'ff' or key == 'forcefield':
                val = parts[1].lower()
                if s.set_ff(val):
                    ff = s.ff
                    progress_msg(f"Force field: {C.bold(ff['label'])} "
                                 f"({ff['unit_system']} units, "
                                 f"dt={ff['dt_display_fs']} fs, "
                                 f"atom_style={ff['atom_style']})")
                else:
                    print(f"  Unknown FF. Available: {', '.join(FF_PRESETS.keys())}")

            elif key == 'temperature' or key == 'temp':
                s.temperature = int(parts[1])
                progress_msg(f"Temperature: {s.temperature} K")

            elif key == 'slab':
                if len(parts) == 4:
                    s.nx, s.ny, s.nz = int(parts[1]), int(parts[2]), int(parts[3])
                elif len(parts) == 2 and 'x' in parts[1]:
                    dims = parts[1].split('x')
                    s.nx, s.ny, s.nz = int(dims[0]), int(dims[1]), int(dims[2])
                else:
                    print("  Usage: set slab <nx> <ny> <nz>  or  set slab NxNxN")
                    return
                n_fe = s.nx * s.ny * s.nz
                progress_msg(f"Supercell: {s.nx} x {s.ny} x {s.nz} layers "
                             f"({n_fe} Fe atoms)")

            elif key == 'surface':
                val = parts[1]
                if val in ('100', '110', '111'):
                    s.surface = val
                    progress_msg(f"Surface: Fe({s.surface})")
                else:
                    print("  Valid: 100, 110, 111")

            elif key == 'o2':
                s.n_o2 = int(parts[1])
                progress_msg(f"O2 molecules: {s.n_o2} ({s.n_o2 * 2} O atoms)")

            elif key == 'vacuum':
                s.vacuum = float(parts[1])
                progress_msg(f"Vacuum: {s.vacuum} A")

            elif key == 'lattice' or key == 'a_fe':
                s.a_fe = float(parts[1])
                progress_msg(f"Lattice constant: {s.a_fe} A")

            elif key == 'boundary':
                if len(parts) >= 4:
                    s.boundary = f"{parts[1]} {parts[2]} {parts[3]}"
                else:
                    s.boundary = parts[1]
                progress_msg(f"Boundary: {s.boundary}")

            elif key == 'dt':
                # Store in ff-native units
                progress_msg(f"Note: dt is set per force field preset. "
                             f"Current: {s.dt_display_fs} fs")

            elif key == 'eq_time':
                s.eq_ps = float(parts[1])
                progress_msg(f"Equilibration: {s.eq_ps} ps "
                             f"({s.ps_to_steps(s.eq_ps)} steps)")

            elif key == 'ox_time':
                s.ox_ps = float(parts[1])
                progress_msg(f"Oxidation: {s.ox_ps} ps "
                             f"({s.ps_to_steps(s.ox_ps)} steps)")

            elif key == 'spin_time':
                s.spin_ps = float(parts[1])
                progress_msg(f"Spin equilibration: {s.spin_ps} ps")

            elif key == 'seed':
                s.seed = int(parts[1])
                progress_msg(f"Structure seed: {s.seed}")

            elif key == 'velocity_seed' or key == 'vseed':
                s.velocity_seed = int(parts[1])
                progress_msg(f"Velocity seed: {s.velocity_seed}")

            elif key == 'fixed_layers':
                s.n_fixed_layers = int(parts[1])
                progress_msg(f"Fixed layers: {s.n_fixed_layers}")

            elif key == 'nvt_layers':
                s.n_thermostat_layers = int(parts[1])
                progress_msg(f"NVT thermostat layers: {s.n_thermostat_layers}")

            elif key == 'wall':
                from lammps_pre.state import WALL_CUTOFF
                progress_msg(f"Wall position is auto-computed: slab top + "
                             f"{WALL_CUTOFF} A + 0.9. That cutoff is shared by every "
                             f"force field on purpose, so all of them start from "
                             f"identical coordinates. "
                             f"Use 'set fixed_layers' or 'set nvt_layers' to adjust.")

            elif key == 'thermo':
                s.thermo_interval = int(parts[1])
                progress_msg(f"Thermo interval: {s.thermo_interval} steps")

            elif key == 'dump':
                s.dump_interval = int(parts[1])
                progress_msg(f"Dump interval: {s.dump_interval} steps")

            elif key == 'output':
                s.output_dir = parts[1]
                progress_msg(f"Output directory: {s.output_dir}")

            elif key == 'job_name':
                s.job_name = parts[1]
                progress_msg(f"Job name: {s.job_name}")

            elif key == 'queue':
                s.queue = parts[1]
                progress_msg(f"Queue: {s.queue}")

            elif key == 'ncpus':
                s.ncpus = int(parts[1])
                progress_msg(f"CPUs: {s.ncpus}")

            elif key == 'walltime':
                s.walltime_hr = int(parts[1])
                progress_msg(f"Walltime: {s.walltime_hr} hr")

            elif key == 'memory' or key == 'mem':
                s.memory_gb = int(parts[1])
                progress_msg(f"Memory: {s.memory_gb} GB")

            else:
                print(f"  Unknown setting: {key}")

        except (ValueError, IndexError) as e:
            print(f"  {C.err('Error:')} {e}")

    def complete_set(self, text, line, begidx, endidx):
        keys = ['ff', 'temperature', 'slab', 'surface', 'o2', 'vacuum',
                'lattice', 'boundary', 'dt', 'eq_time', 'ox_time', 'seed',
                'fixed_layers', 'nvt_layers', 'wall', 'thermo', 'dump',
                'output', 'job_name', 'queue', 'ncpus', 'walltime', 'memory']
        tokens = line.split()
        if len(tokens) == 2 and text:
            return [k + ' ' for k in keys if k.startswith(text)]
        if len(tokens) == 2 and not text:
            return [k + ' ' for k in keys]
        # Value completion for specific keys
        if len(tokens) >= 3:
            key = tokens[1].lower()
            if key == 'ff':
                return [f + ' ' for f in FF_PRESETS if f.startswith(text)]
            elif key == 'surface':
                return [s + ' ' for s in ('100', '110', '111') if s.startswith(text)]
            elif key == 'output':
                return self._complete_path(text)
        return []

    # ═══════════════════════════════════════════════════════════
    # load
    # ═══════════════════════════════════════════════════════════

    def do_load(self, arg):
        """Load an existing LAMMPS data file: load <filepath>

        Reads atom count, box size, atom types, and masses from a
        LAMMPS data file. Useful for inspecting or regenerating files
        for an existing structure.
        """
        parts = shlex.split(arg) if arg.strip() else []
        if not parts:
            fpath = self._ask("Data file path")
            if not fpath:
                return
        else:
            fpath = parts[0]

        if not os.path.exists(fpath):
            print(C.err(f"  File not found: {fpath}"))
            return

        progress_msg(f"Loading: {fpath} ...")

        try:
            info = self._parse_data_file(fpath)
        except Exception as e:
            print(C.err(f"  Parse error: {e}"))
            return

        progress_msg(f"Atoms: {info['n_atoms']}, Types: {info['n_types']}")
        progress_msg(f"Box: {info['xhi']-info['xlo']:.1f} x "
                     f"{info['yhi']-info['ylo']:.1f} x "
                     f"{info['zhi']-info['zlo']:.1f} A")
        if info['masses']:
            for tid, mass in sorted(info['masses'].items()):
                progress_msg(f"  Type {tid}: {mass} amu")

        # Auto-detect force field from atom style
        if info.get('atom_style') == 'charge':
            progress_msg(f"Detected: atom_style charge (ReaxFF)")
        elif info.get('atom_style') == 'atomic':
            if info['n_types'] == 3:
                progress_msg(f"Detected: atom_style atomic, 3 types (ACE)")
            else:
                progress_msg(f"Detected: atom_style atomic")

    @staticmethod
    def _parse_data_file(filepath):
        """Parse header info from a LAMMPS data file."""
        info = {'n_atoms': 0, 'n_types': 0, 'masses': {},
                'xlo': 0, 'xhi': 0, 'ylo': 0, 'yhi': 0,
                'zlo': 0, 'zhi': 0, 'atom_style': None}
        in_masses = False
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    if in_masses:
                        in_masses = False
                    continue
                if 'atoms' in line and 'atom' not in line.split()[0]:
                    try:
                        info['n_atoms'] = int(line.split()[0])
                    except ValueError:
                        pass
                elif 'atom types' in line:
                    try:
                        info['n_types'] = int(line.split()[0])
                    except ValueError:
                        pass
                elif 'xlo' in line and 'xhi' in line:
                    parts = line.split()
                    info['xlo'], info['xhi'] = float(parts[0]), float(parts[1])
                elif 'ylo' in line and 'yhi' in line:
                    parts = line.split()
                    info['ylo'], info['yhi'] = float(parts[0]), float(parts[1])
                elif 'zlo' in line and 'zhi' in line:
                    parts = line.split()
                    info['zlo'], info['zhi'] = float(parts[0]), float(parts[1])
                elif line == 'Masses':
                    in_masses = True
                    continue
                elif in_masses:
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            info['masses'][int(parts[0])] = float(parts[1])
                        except ValueError:
                            in_masses = False
                elif line.startswith('Atoms'):
                    # Detect atom_style from comment
                    if '# charge' in line:
                        info['atom_style'] = 'charge'
                    elif '# atomic' in line:
                        info['atom_style'] = 'atomic'
                    break  # Stop reading after Atoms header
        return info

    def complete_load(self, text, line, begidx, endidx):
        return self._complete_path(text)

    # ═══════════════════════════════════════════════════════════
    # build
    # ═══════════════════════════════════════════════════════════

    def do_build(self, arg):
        """Build structure from current settings: build [slab|o2]"""
        s = self.state

        # Validate before building
        n_nve = s.nz - s.n_fixed_layers - s.n_thermostat_layers
        if n_nve < 1:
            print(C.err(f"  Error: fixed({s.n_fixed_layers}) + NVT({s.n_thermostat_layers}) "
                        f">= slab layers({s.nz}). Increase nz or reduce layer counts."))
            return
        if s.forcefield is None:
            print(C.err("  Error: no force field set. Use 'set ff <name>' first."))
            return

        result = build_all(s)
        if result:
            print(f"  {C.ok('Build complete.')}")
        else:
            print(f"  {C.err('Build failed.')}")

    # ═══════════════════════════════════════════════════════════
    # preview / show
    # ═══════════════════════════════════════════════════════════

    def do_preview(self, arg):
        """Show current configuration summary: preview [structure|regions|thermo|dump|files]"""
        self.do_show(arg)

    def do_show(self, arg):
        """Show current settings: show [ff|regions|hpc|output|all]"""
        sub = arg.strip().lower() if arg else ''
        s = self.state
        ff = s.ff

        if sub == 'ff':
            self._show_ff()
        elif sub == 'hpc':
            self._show_hpc()
        elif sub == 'regions':
            self._show_regions()
        elif sub == 'output':
            self._show_output()
        elif sub == 'files':
            self._show_files()
        else:
            self._show_all()

    def _show_all(self):
        s = self.state
        ff = s.ff
        n_fe = s.nx * s.ny * s.nz
        n_o = s.n_o2 * 2
        n_nve = s.nz - s.n_fixed_layers - s.n_thermostat_layers

        pairs = [
            ('Force field', f"{ff['label']} ({ff['unit_system']} units)"),
            ('Temperature', f"{s.temperature} K"),
            ('Surface', f"Fe({s.surface}), a={s.a_fe} A"),
            ('Slab', f"{s.nx}x{s.ny}x{s.nz} ({n_fe} Fe atoms)"),
            ('Layers', f"fixed {s.n_fixed_layers} / NVT {s.n_thermostat_layers} / NVE {n_nve}"),
            ('O2 molecules', f"{s.n_o2} ({n_o} O atoms)"),
            ('Total atoms', f"{n_fe + n_o}"),
            ('Boundary', s.boundary),
            ('Timestep', f"{ff['dt_display_fs']} fs"),
            ('Eq. time', f"{s.get_eq_ps()} ps ({s.ps_to_steps(s.get_eq_ps())} steps)"),
            ('Ox. time', f"{s.get_ox_ps()} ps ({s.ps_to_steps(s.get_ox_ps())} steps)"),
        ]
        if s.has_spin:
            pairs.append(('Spin EQ', f"{s.get_spin_ps()} ps"))
        pairs.append(('Output dir', s.output_dir))

        print_kv(pairs, title='Configuration Summary')

        if s.build_result:
            self._show_regions()

    def _show_ff(self):
        ff = self.state.ff
        pairs = [
            ('Name', ff['label']),
            ('Reference', ff.get('reference', '')),
            ('Unit system', ff['unit_system']),
            ('atom_style', ff['atom_style']),
            ('pair_style', ff['pair_style']),
            ('Potential', ff['potential_file']),
            ('Timestep', f"{ff['dt_display_fs']} fs"),
            ('T damping', f"{ff['T_damp_display_fs']} fs"),
            ('Cutoff (rc)', f"{ff['rc']} A"),
            ('Atom types', str(ff['atom_types'])),
            ('Spin model', 'MC swap (Ising)' if ff['has_spin'] else 'None'),
            ('Charge model', 'QEq (every 10 steps)' if ff['has_qeq'] else 'None'),
            ('Thermo fields', ff['thermo_fields']),
            ('Dump fields', ff['dump_fields']),
        ]
        print_kv(pairs, title=f'Force Field: {ff["label"]}')

    def _show_regions(self):
        s = self.state
        b = s.build_result
        if b is None:
            n_nve = s.nz - s.n_fixed_layers - s.n_thermostat_layers
            print(f"\n  {C.dim('(No build yet — showing layer counts only)')}")
            headers = ['Zone', 'Ensemble', 'Layers']
            rows = [
                ['Fixed', 'frozen (setforce 0)', str(s.n_fixed_layers)],
                ['Lower NVT', 'NVT (Nose-Hoover)', str(s.n_thermostat_layers)],
                ['NVE reaction', 'NVE', str(n_nve)],
                ['Upper NVT', 'NVT (O2 gas)', '—'],
            ]
            print_table(headers, rows, title='Region / Ensemble Layout')
            return

        r = b.regions
        headers = ['Zone', 'Ensemble', 'z range (A)', 'Atoms']
        rows = [
            ['Fixed', 'frozen', f'z < {r["z_fixed_top"]:.2f}', str(r['n_fixed'])],
            ['Lower NVT', 'NVT', f'{r["z_fixed_top"]:.2f} – {r["z_lower_nvt_top"]:.2f}',
             str(r['n_lower_nvt'])],
            ['NVE reaction', 'NVE', f'{r["z_lower_nvt_top"]:.2f} – {r["z_nve_top"]:.2f}',
             str(r['n_nve'])],
            ['Upper NVT', 'NVT', f'{r["z_wall_lower"]:.2f} – {b.box[5]:.1f}',
             str(len(b.o2_positions))],
        ]
        print_table(headers, rows, title='Region / Ensemble Layout')

        print(f"  Walls:")
        print(f"    upper  : wall/reflect zhi EDGE (all atoms)")
        print(f"    lower O: wall/reflect z={r['z_wall_lower']:.2f} A "
              f"{C.dim('(removed in Stage 3)')}")
        print()

    def _show_hpc(self):
        s = self.state
        pairs = [
            ('Job name', s.get_job_name()),
            ('Queue', s.queue),
            ('CPUs', str(s.get_ncpus())),
            ('Memory', f"{s.get_memory_gb()} GB"),
            ('Walltime', f"{s.get_walltime_hr()} hr"),
            ('Modules', ', '.join(s.modules)),
            ('LAMMPS', s.lammps_bin),
            ('Scratch', 'Yes' if s.use_scratch else 'No'),
        ]
        print_kv(pairs, title='HPC Settings')

    def _show_output(self):
        ff = self.state.ff
        s = self.state
        pairs = [
            ('Thermo interval', f"{s.get_thermo_interval()} steps"),
            ('Thermo fields', ff['thermo_fields']),
            ('Dump interval', f"{s.get_dump_interval()} steps"),
            ('Dump fields', ff['dump_fields']),
        ]
        if s.has_spin:
            pairs.append(('Dense dump', f"first {s.dump_dense_ps} ps, "
                                        f"every {s.dump_dense_interval} steps"))
        print_kv(pairs, title='Output Settings')

    def _show_files(self):
        names = get_filenames(self.state)
        d = self.state.output_dir
        print(f"\n  {C.bold('Files to generate:')}")
        for key, fname in names.items():
            status = ''
            fpath = os.path.join(d, fname)
            if os.path.exists(fpath):
                status = f' {C.dim("(exists)")}'
            print(f"    {os.path.join(d, fname)}{status}")
        print()

    def complete_show(self, text, line, begidx, endidx):
        opts = ['ff', 'regions', 'hpc', 'output', 'files', 'all']
        return [o + ' ' for o in opts if o.startswith(text)]

    complete_preview = complete_show

    # ═══════════════════════════════════════════════════════════
    # write
    # ═══════════════════════════════════════════════════════════

    def do_write(self, arg):
        """Write output files: write [all|data|regions|input|runscript] [directory]"""
        s = self.state
        b = s.build_result

        if b is None:
            print(C.warn("  No structure built. Run 'build' first."))
            ans = self._ask("Build now? (y/n)", 'y')
            if ans and ans.lower() in ('y', 'yes'):
                self.do_build('')
                b = s.build_result
                if b is None:
                    return
            else:
                return

        parts = shlex.split(arg) if arg.strip() else []
        what = parts[0].lower() if parts else 'all'
        directory = parts[1] if len(parts) > 1 else s.output_dir

        os.makedirs(directory, exist_ok=True)
        names = get_filenames(s)

        if what == 'all':
            write_all(b, s, directory)
        elif what == 'data':
            write_data_file(b, s, os.path.join(directory, names['data']))
        elif what == 'regions':
            write_regions_inc(b, s, os.path.join(directory, names['regions']))
        elif what == 'input':
            write_input_script(b, s, os.path.join(directory, names['input']))
        elif what == 'runscript':
            write_run_script(b, s, os.path.join(directory, names['runscript']))
        elif what == 'xyz':
            write_xyz(b, os.path.join(directory, names['xyz']))
        else:
            print(f"  Unknown target: {what}")
            print("  Options: all, data, regions, input, runscript, xyz")

    def complete_write(self, text, line, begidx, endidx):
        targets = ['all', 'data', 'regions', 'xyz', 'input', 'runscript']
        tokens = line.split()
        if len(tokens) == 2 and text:
            return [t + ' ' for t in targets if t.startswith(text)]
        if len(tokens) == 2 and not text:
            return [t + ' ' for t in targets]
        if len(tokens) >= 3:
            return self._complete_path(text)
        return []

    # ═══════════════════════════════════════════════════════════
    # matrix
    # ═══════════════════════════════════════════════════════════

    def do_matrix(self, arg):
        """Generate a temperature/O2 matrix of simulations.

        Usage:
          matrix temps=300,500,800 o2=40,100,200
          matrix temps=300,500,800 o2=40,100,200 output=./atlas/ace
          matrix temps=300,800 o2=100     (single O2 count is fine)

        Creates directory structure:
          <output>/o2_40/300K/  (data + input + regions + run.sh + xyz)
          <output>/o2_40/500K/
          ...
        """
        s = self.state

        # Parse key=value pairs
        parts = shlex.split(arg) if arg.strip() else []
        temps = None
        o2s = None
        output_base = None

        for part in parts:
            if '=' not in part:
                print(f"  {C.err('Error:')} expected key=value, got '{part}'")
                return
            key, val = part.split('=', 1)
            key = key.lower()
            if key in ('temps', 'temp', 'temperatures', 't'):
                temps = [int(t) for t in val.split(',')]
            elif key in ('o2', 'o2s', 'n_o2'):
                o2s = [int(n) for n in val.split(',')]
            elif key in ('output', 'dir', 'base'):
                output_base = val

        if temps is None or o2s is None:
            print("  Usage: matrix temps=300,500,800 o2=40,100,200 [output=./dir]")
            return

        if output_base is None:
            output_base = s.output_dir

        n_total = len(temps) * len(o2s)
        ff_label = s.ff['label']
        print(f"\n  {C.bold(f'Matrix generation: {ff_label}')}")
        print(f"  Temperatures: {temps}")
        print(f"  O2 counts:    {o2s}")
        print(f"  Total:        {n_total} simulations")
        print(f"  Output base:  {output_base}")
        print()

        count = 0
        for n_o2 in o2s:
            for temp in temps:
                count += 1
                subdir = os.path.join(output_base, f"o2_{n_o2}", f"{temp}K")
                print(f"  [{count}/{n_total}] {ff_label} / o2_{n_o2} / {temp}K")

                # Update state for this combination
                s.n_o2 = n_o2
                s.temperature = temp
                s.build_result = None

                # Build
                result = build_all(s)
                if result is None:
                    print(f"  {C.err('Build failed, skipping.')}")
                    continue

                # Write
                write_all(result, s, subdir)

        print(f"\n  {C.ok(f'Matrix complete: {count} simulations generated.')}")
        print(f"  Base directory: {os.path.abspath(output_base)}/")
        print()

    # ═══════════════════════════════════════════════════════════
    # reset
    # ═══════════════════════════════════════════════════════════

    def do_reset(self, arg):
        """Reset settings to defaults: reset [ff]"""
        sub = arg.strip().lower()
        if sub == 'ff':
            self.state.set_ff(self.state.forcefield)
            progress_msg("Force field settings reset.")
        else:
            self.state.reset()
            progress_msg("All settings reset to defaults.")

    # ═══════════════════════════════════════════════════════════
    # Exit / misc
    # ═══════════════════════════════════════════════════════════

    def do_quit(self, arg):
        """Exit lammps-pre."""
        print(f"\n  {C.dim('Goodbye!')}\n")
        self._next = 'quit'
        return True

    do_exit = do_quit
    do_q = do_quit

    def do_EOF(self, arg):
        """Handle Ctrl+D."""
        print()
        return self.do_quit(arg)

    def emptyline(self):
        pass

    def default(self, line):
        print(f"  Unknown command: '{line}'. Type 'help' for available commands.")

    def do_help(self, arg):
        """Show help for a command or list all commands."""
        if arg:
            super().do_help(arg)
            return

        help_text = f"""
{C.bold('STRUCTURE')}
  set ff <name>             Force field (ace / reaxff2010 / reaxff2015)
  set slab <nx> <ny> <nz>   Supercell size
  set surface <100|110|111> Miller index
  set o2 <count>            O2 molecule count
  set temperature <K>       Simulation temperature
  build                     Build structure from current settings
  load <data_file>          Inspect existing LAMMPS data file

{C.bold('SETTINGS')}
  set boundary <bx by bz>   Boundary conditions (p/f/s)
  set eq_time <ps>           Equilibration time
  set ox_time <ps>           Oxidation time
  set fixed_layers <N>       Fixed layer count
  set nvt_layers <N>         NVT buffer layer count
  set vacuum <A>             Vacuum thickness
  set thermo <N>             Thermo output interval (steps)
  set dump <N>               Dump output interval (steps)
  set output <dir>           Output directory

{C.bold('VIEW')}
  show [ff|regions|hpc|output|files]
  preview                   Same as show

{C.bold('OUTPUT')}
  write all                 Write all files (data + regions + input + run.sh + xyz)
  write data                Write LAMMPS data file only
  write regions             Write regions.inc only
  write input               Write LAMMPS input script only
  write runscript           Write PBS run.sh only
  write xyz                 Write XYZ visualization file

{C.bold('BATCH')}
  matrix temps=.. o2=..     Generate temperature/O2 combination matrix
  (--batch <file>)          Execute commands from script (CLI flag)

{C.bold('OTHER')}
  reset                     Reset all settings
  help [cmd]                Show help
  quit / exit / q           Exit
"""
        print(help_text + self._hosted_help())
