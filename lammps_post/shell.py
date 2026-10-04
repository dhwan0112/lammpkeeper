"""
═══════════════════════════════════════════════════════════════
Section 6: Interactive Shell (cmd.Cmd subclass)
═══════════════════════════════════════════════════════════════
The main interactive CLI built on Python's cmd.Cmd framework.
Each 'do_<name>' method implements a user command (e.g., do_load).
Each 'complete_<name>' method provides tab completion for that command.
The shell provides:
  - File I/O commands (load, unload, info)
  - Inspection commands (show thermo/columns/types/frames/box/composition)
  - Settings commands (set output/surface_z/dt/forcefield/types/dpi/...)
  - Analysis commands (analyze charge/rdf/oar/penetration/density/...)
  - Plot commands (plot <type> or plot all)
  - Export commands (export csv/latex/summary)
  - Navigation (pwd, ls, cd, files, find)
  - Interactive prompting when required data is missing
═══════════════════════════════════════════════════════════════
"""

import cmd
import io
import os
import sys
import shlex
import glob as globmod
import importlib.util
import readline  # noqa: F401  (line editing for input())
import threading
import traceback

import numpy as np

from lammps_post import VERSION, CM_PER_INCH, WONG_PALETTE
from lammps_post.display import C, print_table, print_kv, progress_msg, HAS_RICH
from lammpkeeper.common.display import banner
from lammpkeeper.common.hosted import HostedShellMixin

from lammps_post.parsers import (
    parse_log, parse_data_file, detect_forcefield, parse_input,
    DumpReader, LazyFrames, ANALYSIS_COLUMNS, DEFAULT_CACHE_BYTES,
)

from lammpkeeper.common.mapping import element_to_type as ff_element_to_type

from lammps_post.analysis import (
    analyze_charge_evolution, analyze_charge_z, compute_rdf, compute_oar,
    compute_or, analyze_penetration, analyze_penetration_trend,
    compute_density_profile,
    detect_o2_dissociation, analyze_spin_evolution, analyze_msd,
    analyze_stage_performance, analyze_structure,
    analyze_penetration_profile,
)

from lammps_post.plotting import (
    HAS_MPL, _setup_plot_style, _save_fig,
    plot_thermo, plot_thermostat_summary, plot_pressure,
    plot_charge_evolution, plot_charge_z,
    plot_rdf, plot_oar, plot_or,
    plot_penetration, plot_penetration_trend, plot_density,
    plot_dissociation,
    plot_spin, plot_msd, plot_performance,
    plot_structure, plot_snapshot,
    plot_penetration_profile,
)

from lammps_post.state import SessionState

# ── Optional dependency detection (for banner and export commands) ──
# find_spec only locates the package; importing pandas/scipy/MDAnalysis here
# would keep hundreds of MB resident for a banner line. Import at point of use.
def _has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False

HAS_PANDAS = _has_module('pandas')
HAS_SCIPY = _has_module('scipy')
HAS_MDA = _has_module('MDAnalysis')


class _PerThreadStdout:
    """sys.stdout stand-in that sends each thread's writes to its own buffer."""

    def __init__(self, real):
        self._real = real
        self._local = threading.local()

    def redirect(self, buf):
        self._local.buf = buf

    def write(self, s):
        return getattr(self._local, 'buf', self._real).write(s)

    def flush(self):
        getattr(self._local, 'buf', self._real).flush()

    def __getattr__(self, name):
        return getattr(self._real, name)

# Lazy import: only need plt if HAS_MPL is True
if HAS_MPL:
    import matplotlib.pyplot as plt


BANNER = '\n' + banner([
    f"{C.BOLD}LAMMPS-POST:{C.RESET} Post-Processing Interactive CLI  v{VERSION}",
    "Type 'help' for commands, 'quit' to exit",
]) + '\n'

DEPS_INFO = []
for name, flag in [('rich', HAS_RICH), ('pandas', HAS_PANDAS),
                    ('scipy', HAS_SCIPY), ('MDAnalysis', HAS_MDA)]:
    status = C.ok('OK') if flag else C.dim('not found')
    DEPS_INFO.append(f"  {name}: {status}")


class LammpsPostShell(HostedShellMixin, cmd.Cmd):
    # Wrap ANSI escape codes in \x01..\x02 so readline correctly computes
    # the visible prompt length. Without this, history navigation (up/down)
    # corrupts the displayed line because readline miscounts cursor position.
    prompt = f"\x01{C.BLUE}\x02lammps-post>\x01{C.RESET}\x02 "
    intro = BANNER + '\n'.join(DEPS_INFO) + '\n'
    shell_name = 'post'

    def __init__(self):
        super().__init__()
        self.state = SessionState()
        self._setup_history('~/.lammps-post_history')

    # ─── Interactive prompt helper ───
    def _ask(self, prompt, default=None):
        """Prompt user for input. Returns None if empty and no default."""
        suffix = f" [{default}]" if default else ""
        try:
            ans = input(f"  \x01{C.YELLOW}\x02?\x01{C.RESET}\x02 {prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        return ans if ans else default

    def _ask_yn(self, prompt, default='y'):
        """Ask yes/no question. Returns True for yes."""
        ans = self._ask(f"{prompt} (y/n)", default)
        return ans is not None and ans.lower() in ('y', 'yes')

    # ─── Output directory suggestion after first load ───

    def _apply_input_config(self):
        """
        Apply parsed input file configuration to enhance/override ff_info.
        Called after 'load input' and also after 'load dump' if input is already loaded.
        """
        s = self.state
        config = s.input_config
        if config is None:
            return

        # Override ff_info with authoritative data from input file
        if config['forcefield'] != 'unknown':
            s.ff_info['forcefield'] = config['forcefield']
        if config.get('units'):
            s.ff_info['unit_system'] = config['units']
        if config.get('dt_fs'):
            s.ff_info['dt_fs'] = config['dt_fs']
        if config['element_map']:
            s.ff_info['atom_types'] = dict(config['element_map'])
        if config.get('pair_coeff') and config['pair_coeff'].get('elements'):
            s.ff_info['has_charge'] = config['forcefield'] == 'reaxff'

        progress_msg(f"Applied input config: {config['forcefield'].upper()}, "
                     f"types={config['element_map']}")

    def _suggest_output_dir(self, loaded_path):
        """
        After loading the first file, suggest an output directory based on
        the loaded file's location and ask the user to confirm or change it.
        Only asks once per session (skips if output_dir was already changed
        from the default).
        """
        s = self.state
        # Only suggest if still using the default output directory
        if s.output_dir != './lammps-post_output':
            return
        # Only suggest on the very first load
        n_loaded = sum(1 for x in [s.dump_path, s.log_path, s.data_path] if x is not None)
        if n_loaded != 1:
            return

        file_dir = os.path.dirname(os.path.abspath(loaded_path))
        suggestion = os.path.join(file_dir, 'lammps-post_output')

        print()
        print(f"  {C.bold('Output directory for plots/exports:')}")
        print(f"    1. ./lammps-post_output {C.dim('(current dir)')}")
        print(f"    2. {suggestion} {C.dim('(next to the data)')}")
        print(f"    3. Custom path")
        print()
        # Default to the working directory: data folders may be shared or
        # synced (e.g. Dropbox) and should not collect plots by accident.
        choice = self._ask("Choose output directory (1/2/3)", '1')

        if choice == '1':
            s.output_dir = './lammps-post_output'
        elif choice == '2':
            s.output_dir = suggestion
        elif choice == '3':
            custom = self._ask("Enter output directory path")
            if custom:
                s.output_dir = custom
            else:
                return
        else:
            # Treat any other input as a custom path
            s.output_dir = choice

        progress_msg(f"Output directory: {s.output_dir}")

    # ─── Requirement checks with interactive fallback ───
    def _require_dump(self):
        if self.state.dump_frames is not None:
            return True
        print(C.warn("  No dump file loaded."))
        path = self._ask("Enter dump file path (or empty to cancel)")
        if path and os.path.exists(path):
            self.do_load(f'dump {path}')
            return self.state.dump_frames is not None
        if path:
            print(C.err(f"  File not found: {path}"))
        return False

    def _require_log(self):
        if self.state.log_data is not None:
            return True
        print(C.warn("  No log file loaded."))
        path = self._ask("Enter log file path (or empty to cancel)")
        if path and os.path.exists(path):
            self.do_load(f'log {path}')
            return self.state.log_data is not None
        if path:
            print(C.err(f"  File not found: {path}"))
        return False

    def _require_charge(self):
        if self.state.has_charge:
            return True
        print(C.warn("  Charge data not available (requires ReaxFF dump with q column)."))
        if self.state.dump_frames:
            print(f"  Current FF: {self.state.ff.upper()} — available analyses: "
                  f"rdf, penetration, density, dissociation, msd"
                  + (", spin" if self.state.ff == 'ace' else ""))
        return False

    def _require_surface_z(self):
        """Ensure surface_z is set, ask user if not."""
        if self.state.surface_z is not None:
            return True
        print(C.warn("  Surface z not set."))
        val = self._ask("Enter Fe surface z coordinate (A), or 'auto'")
        if val is None:
            return False
        if val.lower() == 'auto':
            self.state._guess_surface_z()
            if self.state.surface_z:
                progress_msg(f"Auto-detected surface z: {self.state.surface_z:.1f} A")
                return True
            print(C.err("  Could not auto-detect surface z."))
            return False
        try:
            self.state.surface_z = float(val)
            progress_msg(f"Surface z set to: {self.state.surface_z:.1f} A")
            return True
        except ValueError:
            print(C.err(f"  Invalid number: {val}"))
            return False

    def _require_data(self):
        """Ensure data file is loaded, ask user if not."""
        if self.state.data_atoms is not None and len(self.state.data_atoms) > 0:
            return True
        print(C.warn("  No data file loaded."))
        path = self._ask("Enter LAMMPS data file path (or empty to cancel)")
        if path and os.path.exists(path):
            self.do_load(f'data {path}')
            return self.state.data_atoms is not None and len(self.state.data_atoms) > 0
        if path:
            print(C.err(f"  File not found: {path}"))
        return False

    # ─── FILE I/O ───

    def do_load(self, arg):
        """
        Load a file: load dump|log|data|input <filepath> [--max N] [--stride N]
                     dump only: [--lite] [--all-columns] [--cache-mb N]
          Only the columns analyses read (id type element x y z q) are kept.
          --lite         store them as float32 (half the memory, approximate)
          --all-columns  keep every dump column (e.g. vx vy vz)
          --cache-mb N   parsed-frame memory budget (default 128); larger dumps stream
        Multiple files: load dump f1.dump, log f2.log, data f3.data
        Auto-detect:    load <filepath>  (detects type from extension)
        """
        parts = shlex.split(arg) if arg.strip() else []

        # ── Multi-file: split on comma and load each ──
        if ',' in arg:
            segments = [s.strip() for s in arg.split(',') if s.strip()]
            for seg in segments:
                self.do_load(seg)
            return

        # ── Auto-detect type from extension if only a path is given ──
        if len(parts) == 1 and os.path.exists(parts[0]):
            fpath = parts[0]
            lower = fpath.lower()
            if lower.endswith(('.dump', '.lammpstrj')):
                parts = ['dump', fpath]
            elif 'log' in os.path.basename(lower) or lower.endswith('.log'):
                parts = ['log', fpath]
            elif lower.endswith('.data') or os.path.basename(lower).startswith('data.'):
                parts = ['data', fpath]
            elif lower.endswith('.in'):
                parts = ['input', fpath]
            else:
                print(C.warn(f"  Cannot auto-detect type for: {fpath}"))
                print(f"  Use: load dump|log|data {fpath}")
                return

        # Ask for file type if missing
        if len(parts) < 1:
            ftype = self._ask("File type (dump/log/data/input)")
            if not ftype or ftype.lower() not in ('dump', 'log', 'data', 'input'):
                print("  Cancelled. Usage: load dump|log|data <filepath>")
                return
            parts = [ftype]

        # Ask for file path if missing
        if len(parts) < 2:
            fpath = self._ask(f"Enter {parts[0]} file path")
            if not fpath:
                print("  Cancelled.")
                return
            parts.append(fpath)

        ftype = parts[0].lower()
        fpath = parts[1]

        # Parse optional args
        max_frames = None
        stride = 1
        lite = False
        all_columns = False
        cache_mb = DEFAULT_CACHE_BYTES / 1024 ** 2
        i = 2
        while i < len(parts):
            if parts[i] == '--max' and i + 1 < len(parts):
                max_frames = int(parts[i + 1]); i += 2
            elif parts[i] == '--stride' and i + 1 < len(parts):
                stride = int(parts[i + 1]); i += 2
            elif parts[i] == '--cache-mb' and i + 1 < len(parts):
                cache_mb = float(parts[i + 1]); i += 2
            elif parts[i] == '--lite':
                lite = True; i += 1
            elif parts[i] == '--all-columns':
                all_columns = True; i += 1
            else:
                i += 1

        if not os.path.exists(fpath):
            print(C.err(f"  File not found: {fpath}"))
            return

        if ftype == 'dump':
            progress_msg(f"Loading dump: {fpath} ...")
            try:
                reader = DumpReader(fpath,
                                    columns=None if all_columns else ANALYSIS_COLUMNS,
                                    dtype=np.float32 if lite else np.float64)
                frames = LazyFrames(reader, cache_bytes=int(cache_mb * 1024 ** 2),
                                    stride=stride, max_frames=max_frames)
                if frames:
                    frames[-1]   # parse the last frame now so a truncated dump fails at load
            except (ValueError, OSError) as e:
                print(C.err(f"  {e}"))
                return
            if not frames:
                print(C.err("  No frames found in dump file."))
                return
            columns, col_idx = list(reader.columns), dict(reader.col_idx)

            # If the dump has 'element' column but no 'type' column,
            # synthesize a numeric 'type' column from element labels.
            # This ensures all analysis functions can use col_idx['type'].
            if 'type' not in col_idx and frames and frames[0].get('elements') is not None:
                unique_elems = sorted(set(frames[0]['elements']))
                # Prefer the canonical element -> type numbering of whichever force
                # field owns these elements. Numbering them alphabetically instead
                # only works when every element is present in frame 0: a spin-
                # equilibration run that starts fully polarized has no 'Fe' yet, so
                # Mn and O would be numbered 1 and 2, and O (really type 3) would be
                # read as Fe_down by every type-based analysis.
                elem_to_type = None
                lookup = None   # full mapping, so elements absent from frame 0 still resolve
                for ff_name in ('ace', 'reaxff'):
                    canonical = ff_element_to_type(ff_name)
                    if set(unique_elems) <= set(canonical):
                        elem_to_type = {e: canonical[e] for e in unique_elems}
                        lookup = dict(canonical)
                        break
                if elem_to_type is None:
                    elem_to_type = {e: i + 1 for i, e in enumerate(unique_elems)}
                    lookup = elem_to_type
                progress_msg(f"Synthesizing 'type' column from elements: {elem_to_type}")

                def add_type_column(fr, lookup=lookup):
                    elements = fr['elements']
                    type_arr = np.zeros((len(elements), 1), dtype=fr['atoms'].dtype)
                    for e, t in lookup.items():
                        type_arr[elements == e, 0] = t
                    unknown = set(elements[type_arr[:, 0] == 0].tolist())
                    if unknown:
                        raise ValueError(
                            f"step {fr['timestep']}: element(s) {sorted(unknown)} have no "
                            f"type mapping {lookup}")
                    return dict(fr, atoms=np.hstack([fr['atoms'], type_arr]))

                frames.set_transform(add_type_column)
                col_idx['type'] = len(col_idx)
                columns.append('type')

            self.state.dump_path = fpath
            self.state.dump_frames = frames
            self.state.dump_columns = columns
            self.state.dump_col_idx = col_idx
            self.state.clear_cache()

            # Auto-detect force field
            ff_info = detect_forcefield(columns, col_idx, frames)
            ff_info['has_velocity'] = 'vx' in reader.raw_columns
            self.state.ff_info = ff_info

            # Auto-detect surface z
            self.state._guess_surface_z()

            n_atoms = frames[0]['natoms']
            n_frames = len(frames)
            progress_msg(f"Columns: {C.info(', '.join(columns))}")
            skipped = [c for c in reader.raw_columns
                       if c not in columns and c != 'element']
            if skipped:
                progress_msg(f"Not loaded (unused by analyses): {', '.join(skipped)} "
                             f"(--all-columns keeps them)")
            progress_msg(f"Detected: {C.bold(ff_info['forcefield'].upper())} "
                         f"({ff_info['unit_system']} units, dt={ff_info['dt_fs']} fs)")
            progress_msg(f"Loaded {C.ok(str(n_frames))} frames, {n_atoms} atoms")
            est_mb = frames.estimated_bytes / 1024 ** 2
            if frames.fits_in_cache:
                progress_msg(f"Frames cached in memory on first use (~{est_mb:.0f} MB)")
            else:
                progress_msg(
                    f"Streaming from disk: ~{est_mb:.0f} MB of frames exceeds the "
                    f"{cache_mb:.0f} MB cache (--cache-mb N to keep them in memory)")
            progress_msg(f"Types: {ff_info['atom_types']}")
            if self.state.surface_z:
                progress_msg(f"Auto-detected surface z: {self.state.surface_z:.1f} A")

            # If input file was loaded first, apply its config to enhance ff_info
            if self.state.input_config:
                self._apply_input_config()

        elif ftype == 'log':
            progress_msg(f"Loading log: {fpath} ...")
            log_data = parse_log(fpath)
            if log_data is None:
                print(C.err("  No thermo data found in log file."))
                return

            self.state.log_path = fpath
            self.state.log_data = log_data

            n_points = len(log_data.get('step', []))
            headers = log_data.get('headers', [])
            progress_msg(f"Columns: {C.info(', '.join(headers))}")
            progress_msg(f"Extracted {C.ok(str(n_points))} data points")
            if log_data.get('stage_times'):
                stages = ', '.join(f"{k}: {v:.0f}s" for k, v in log_data['stage_times'].items())
                progress_msg(f"Stages: {stages}")

        elif ftype == 'data':
            progress_msg(f"Loading data file: {fpath} ...")
            atoms, box, masses = parse_data_file(fpath)
            if len(atoms) == 0:
                print(C.err("  No atoms found in data file."))
                return

            self.state.data_path = fpath
            self.state.data_atoms = atoms
            self.state.data_box = box
            self.state.data_masses = masses

            # Compute total system mass from type counts and masses
            if masses and len(atoms) > 0:
                types = atoms[:, 1].astype(int)
                total_mass = sum(
                    np.sum(types == t) * m for t, m in masses.items()
                )
                self.state.total_mass_amu = total_mass
                progress_msg(f"Total mass: {total_mass:.2f} amu")

            progress_msg(f"Loaded {C.ok(str(len(atoms)))} atoms")
            if masses:
                mass_str = ', '.join(f"type {k}: {v}" for k, v in masses.items())
                progress_msg(f"Masses: {mass_str}")
        elif ftype == 'input':
            progress_msg(f"Loading input: {fpath} ...")
            config = parse_input(fpath)
            self.state.input_path = fpath
            self.state.input_config = config

            # Report extracted configuration
            progress_msg(f"Units: {C.info(config.get('units') or 'unknown')}")
            if config['boundary']:
                progress_msg(f"Boundary: {C.info(' '.join(config['boundary']))}")
            progress_msg(f"Force field: {C.bold(config['forcefield'].upper())}")
            if config.get('pair_coeff'):
                progress_msg(f"Potential: {C.info(config['pair_coeff']['potential_file'])}")
            if config['element_map']:
                type_str = ', '.join(f"{k}: {v}" for k, v in sorted(config['element_map'].items()))
                progress_msg(f"Type mapping: {C.info(type_str)}")
            if config.get('dt_fs'):
                progress_msg(f"Timestep: {config['dt_fs']} fs")
            if config.get('temperature'):
                progress_msg(f"Temperature: {config['temperature']} K")
            if config['reaction_type'] != 'unknown':
                progress_msg(f"Reaction: {C.info(config['reaction_type'])}")
            if config['stages']:
                progress_msg(f"Stages: {len(config['stages'])} detected")
            if config['dumps']:
                dump_files = [d['file'] for d in config['dumps'] if d['file']]
                progress_msg(f"Dump files: {', '.join(dump_files)}")
            output_files = []
            if config['write_data']:
                output_files.append(f"data: {config['write_data']}")
            if config['write_restart']:
                output_files.append(f"restart: {config['write_restart']}")
            if config['log_file']:
                output_files.append(f"log: {config['log_file']}")
            if output_files:
                progress_msg(f"Output: {', '.join(output_files)}")

            # Apply input config to override/enhance ff_info if dump is loaded
            self._apply_input_config()

        else:
            print(f"  Unknown file type: {ftype}. Use dump|log|data|input.")
            return

        # ── After first load: suggest output directory ──
        self._suggest_output_dir(fpath)

    def complete_load(self, text, line, begidx, endidx):
        tokens = line.split()
        if len(tokens) == 2 and not text:
            return ['dump ', 'log ', 'data ', 'input ']
        if len(tokens) == 2:
            return [t + ' ' for t in ['dump', 'log', 'data', 'input'] if t.startswith(text)]
        if len(tokens) >= 3:
            return self._complete_path(text)
        return []

    def do_unload(self, arg):
        """Unload a file: unload dump|log|data|input|all"""
        ftype = arg.strip().lower()
        if ftype == 'all':
            self.do_unload('dump')
            self.do_unload('log')
            self.do_unload('data')
            self.do_unload('input')
            return
        if ftype == 'dump':
            self.state.dump_path = None
            self.state.dump_frames = None
            self.state.dump_columns = None
            self.state.dump_col_idx = None
            self.state.ff_info = {'forcefield': 'unknown', 'unit_system': 'metal',
                                  'dt_fs': 1.0, 'has_charge': False, 'has_velocity': False,
                                  'has_element': False, 'atom_types': {}}
            self.state.clear_cache()
            progress_msg("Dump data unloaded.")
        elif ftype == 'log':
            self.state.log_path = None
            self.state.log_data = None
            progress_msg("Log data unloaded.")
        elif ftype == 'data':
            self.state.data_path = None
            self.state.data_atoms = None
            progress_msg("Data file unloaded.")
        elif ftype == 'input':
            self.state.input_path = None
            self.state.input_config = None
            progress_msg("Input file unloaded.")
        else:
            print("  Usage: unload dump|log|data|input|all")

    def complete_unload(self, text, line, begidx, endidx):
        return [t for t in ['dump', 'log', 'data', 'input', 'all'] if t.startswith(text)]

    # ─── INFO / SHOW ───

    def do_info(self, arg):
        """Show session summary."""
        s = self.state
        pairs = [
            ('Force Field', f"{s.ff.upper()} ({'auto' if s.dump_frames else 'N/A'})"),
            ('Units', s.ff_info['unit_system']),
            ('Timestep', f"{s.dt_fs} fs"),
        ]

        if s.dump_path:
            pairs.append(('Dump', os.path.basename(s.dump_path)))
            pairs.append(('  Frames', str(len(s.dump_frames))))
            pairs.append(('  Atoms', str(s.dump_frames[0]['natoms'])))
            pairs.append(('  Columns', ', '.join(s.dump_columns)))
            type_str = ', '.join(f"{v}({k})" for k, v in s.atom_types.items())
            pairs.append(('  Types', type_str))
        else:
            pairs.append(('Dump', C.dim('not loaded')))

        if s.log_path:
            pairs.append(('Log', os.path.basename(s.log_path)))
            pairs.append(('  Data points', str(len(s.log_data.get('step', [])))))
        else:
            pairs.append(('Log', C.dim('not loaded')))

        if s.data_path:
            pairs.append(('Data', os.path.basename(s.data_path)))
            pairs.append(('  Atoms', str(len(s.data_atoms))))
        else:
            pairs.append(('Data', C.dim('not loaded')))

        if s.input_path:
            pairs.append(('Input', os.path.basename(s.input_path)))
            ic = s.input_config
            if ic:
                pairs.append(('  Boundary', ' '.join(ic.get('boundary', []))))
                pairs.append(('  Reaction', ic.get('reaction_type', 'unknown')))
                if ic['element_map']:
                    tm = ', '.join(f"{k}:{v}" for k, v in sorted(ic['element_map'].items()))
                    pairs.append(('  Type map', tm))
        else:
            pairs.append(('Input', C.dim('not loaded')))

        pairs.append(('Surface z', f"{s.surface_z:.1f} A" if s.surface_z else C.dim('not set')))
        pairs.append(('Normalize', C.ok('ON') if s.normalize else C.dim('OFF')))
        zf = s.z_focus
        pairs.append(('z_focus', f"[{zf[0]:.1f}, {zf[1]:.1f}] A" if zf else C.dim('full range')))
        pairs.append(('Pressure unit', s.pressure_unit.upper()))
        pairs.append(('Total mass',
                       f"{s.total_mass_amu:.2f} amu" if s.total_mass_amu else C.dim('not set')))
        pairs.append(('Output dir', s.output_dir))
        pairs.append(('DPI', str(s.dpi)))
        pairs.append(('Theme', s.theme))
        pairs.append(('Save format', s.save_format.upper()))
        fig_info = f"lw={s.linewidth}, ms={s.marker_size}, font={s.font_size}, "
        fig_info += f"grid={'ON' if s.grid else 'OFF'}({s.grid_alpha}), "
        if s.figsize_override:
            fig_info += f"fig={s.figsize_override[0]:.2f}x{s.figsize_override[1]:.2f} (override)"
        else:
            fig_info += f"fig={s.fig_width}x{s.fig_height} (per-function)"
        pairs.append(('Plot style', fig_info))

        print_kv(pairs, 'Session Info')

    def do_show(self, arg):
        """Show details: show thermo|columns|types|frames|box|composition|stages"""
        parts = arg.strip().split()
        if not parts:
            print("  Usage: show thermo|columns|types|frames|box|composition|stages")
            return

        what = parts[0].lower()
        s = self.state

        if what == 'thermo':
            if not self._require_log():
                return
            d = s.log_data
            headers = ['Column', 'Min', 'Max', 'Mean', 'Std']
            rows = []
            for key in ['step', 'temp', 'pe', 'ke', 'etotal', 'press', 'vol']:
                if key in d:
                    v = d[key]
                    rows.append([key, f'{v.min():.4g}', f'{v.max():.4g}',
                                 f'{v.mean():.4g}', f'{v.std():.4g}'])
            print_table(headers, rows, 'Thermo Summary')

        elif what == 'columns':
            if not self._require_dump():
                return
            print(f"  Dump columns: {C.info(', '.join(s.dump_columns))}")

        elif what == 'types':
            if not s.atom_types:
                print("  No type information available.")
                return
            headers = ['Type ID', 'Name']
            rows = [[str(k), str(v)] for k, v in s.atom_types.items()]
            print_table(headers, rows, 'Atom Types')

        elif what == 'frames':
            if not self._require_dump():
                return
            first = s.dump_frames[0]
            last = s.dump_frames[-1]
            print_kv([
                ('Total frames', str(len(s.dump_frames))),
                ('First timestep', str(first['timestep'])),
                ('Last timestep', str(last['timestep'])),
                ('Atoms per frame', str(first['natoms'])),
            ], 'Frame Info')

        elif what == 'box':
            if not self._require_dump():
                return
            box = s.dump_frames[0]['box']
            L = box[:, 1] - box[:, 0]
            print_kv([
                ('x', f"{box[0][0]:.4f} to {box[0][1]:.4f}  (L={L[0]:.4f} A)"),
                ('y', f"{box[1][0]:.4f} to {box[1][1]:.4f}  (L={L[1]:.4f} A)"),
                ('z', f"{box[2][0]:.4f} to {box[2][1]:.4f}  (L={L[2]:.4f} A)"),
                ('Volume', f"{L[0]*L[1]*L[2]:.1f} A^3"),
            ], 'Simulation Box')

        elif what == 'composition':
            if not self._require_dump():
                return
            frame_idx = int(parts[1]) if len(parts) > 1 else -1
            fr = s.dump_frames[frame_idx]
            types = fr['atoms'][:, s.dump_col_idx['type']].astype(int)
            unique, counts = np.unique(types, return_counts=True)
            headers = ['Type', 'Name', 'Count', 'Fraction']
            rows = []
            total = len(types)
            for t, c in zip(unique, counts):
                name = s.atom_types.get(int(t), f'Type {t}')
                rows.append([str(int(t)), str(name), str(c), f'{c/total*100:.1f}%'])
            rows.append(['', 'Total', str(total), '100%'])
            label = f'Composition (frame {frame_idx})'
            print_table(headers, rows, label)

        elif what == 'stages':
            if not self._require_log():
                return
            st = s.log_data.get('stage_times', {})
            if not st:
                print("  No stage information detected.")
                return
            headers = ['Stage', 'Wall Time (s)', 'Wall Time (hr)', 'Fraction']
            total = sum(st.values())
            rows = []
            for stage, t in st.items():
                rows.append([stage, f'{t:.1f}', f'{t/3600:.2f}', f'{t/total*100:.1f}%'])
            rows.append(['Total', f'{total:.1f}', f'{total/3600:.2f}', '100%'])
            print_table(headers, rows, 'Stage Performance')
        else:
            print(f"  Unknown: '{what}'. Options: thermo|columns|types|frames|box|composition|stages")

    def complete_show(self, text, line, begidx, endidx):
        opts = ['thermo', 'columns', 'types', 'frames', 'box', 'composition', 'stages']
        return [o for o in opts if o.startswith(text)]

    # ─── SETTINGS ───

    def do_set(self, arg):
        """
        Set a parameter. Configures analysis, output, and plot style settings.

        Usage:
            set output <dir>                    — Output directory for plots/exports
            set surface_z <float>               — Fe surface z-coordinate (Angstroms)
            set dt <float>                      — Override timestep (femtoseconds)
            set forcefield reaxff|ace|hdnnp      — Override auto-detected force field
            set types 1=Fe 2=O 3=Cr             — Override atom type name mapping
            set dpi <int>                       — Plot resolution (dots per inch)
            set normalize on|off                — Show ratios instead of raw counts
            set z_focus auto|off|<zlo> <zhi>    — Focus z-range for plots
            set pressure_unit bar|gpa           — Pressure display unit
            set mass <float>                    — Override total system mass (amu)
            set linewidth <float>               — Plot line width (default: 1.5)
            set markersize <float>              — Scatter plot marker size (default: 3)
            set fontsize <int>                  — Base font size for plots (default: 11)
            set grid on|off                     — Toggle grid lines on plots
            set grid_alpha <float>              — Grid transparency 0-1 (default: 0.3)
            set figsize <W> <H>|single_col|double_col|1.5col|slide16x9|slide4x3  — Figure size or preset
            set theme default|publication|presentation  — Plot theme preset
            set save_format png|pdf|svg|both    — Output file format
        """
        parts = shlex.split(arg)
        if len(parts) < 2:
            print("  Usage: set <key> <value>")
            print("  Keys: output, surface_z, dt, forcefield, types, dpi, normalize,")
            print("        z_focus, linewidth, markersize, fontsize, grid, grid_alpha, figsize")
            return

        key = parts[0].lower()
        val = parts[1]
        s = self.state

        if key == 'output':
            s.output_dir = val
            progress_msg(f"Output directory: {val}")
        elif key == 'surface_z':
            s.surface_z = float(val)
            s.clear_cache()  # Penetration and OAR depend on surface_z
            progress_msg(f"Surface z: {s.surface_z} A")
        elif key == 'dt':
            s.ff_info['dt_fs'] = float(val)
            s.clear_cache()  # Time axes change with timestep
            progress_msg(f"Timestep: {s.dt_fs} fs")
        elif key == 'forcefield':
            valid = ['reaxff', 'ace', 'hdnnp']
            if val.lower() in valid:
                s.ff_info['forcefield'] = val.lower()
                progress_msg(f"Force field: {val.upper()}")
            else:
                print(f"  Invalid. Choose from: {', '.join(valid)}")
        elif key == 'types':
            # Parse "1=Fe 2=O 3=Cr" format from remaining arguments
            type_map = {}
            for pair in parts[1:]:
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    type_map[int(k)] = v
            s.ff_info['atom_types'] = type_map
            s.clear_cache()
            progress_msg(f"Types: {type_map}")
        elif key == 'dpi':
            s.dpi = int(val)
            s.apply_plot_style()
            progress_msg(f"DPI: {s.dpi}")
        elif key == 'normalize':
            if val.lower() in ('on', 'true', '1', 'yes'):
                s.normalize = True
                progress_msg("Normalize: ON (plots show ratios/fractions)")
            elif val.lower() in ('off', 'false', '0', 'no'):
                s.normalize = False
                progress_msg("Normalize: OFF (plots show raw counts)")
            else:
                print("  Usage: set normalize on|off")
        elif key == 'z_focus':
            if val.lower() == 'auto':
                zf = s.compute_z_focus()
                if zf:
                    s.z_focus = zf
                    progress_msg(f"z_focus auto-computed: [{zf[0]:.1f}, {zf[1]:.1f}] A")
                else:
                    print(C.warn("  Cannot auto-compute z_focus. Load dump first."))
            elif val.lower() in ('off', 'none', 'reset'):
                s.z_focus = None
                progress_msg("z_focus: OFF (full z-range)")
            elif len(parts) >= 3:
                s.z_focus = (float(parts[1]), float(parts[2]))
                progress_msg(f"z_focus: [{s.z_focus[0]:.1f}, {s.z_focus[1]:.1f}] A")
            else:
                print("  Usage: set z_focus auto | off | <zlo> <zhi>")
        # ── Plot style settings ──
        elif key == 'linewidth' or key == 'lw':
            s.linewidth = float(val)
            s.apply_plot_style()
            progress_msg(f"Line width: {s.linewidth}")
        elif key == 'markersize' or key == 'ms':
            s.marker_size = float(val)
            s.apply_plot_style()
            progress_msg(f"Marker size: {s.marker_size}")
        elif key == 'fontsize' or key == 'fs':
            s.font_size = int(val)
            s.apply_plot_style()
            progress_msg(f"Font size: {s.font_size}")
        elif key == 'grid':
            if val.lower() in ('on', 'true', '1', 'yes'):
                s.grid = True
                s.apply_plot_style()
                progress_msg("Grid: ON")
            elif val.lower() in ('off', 'false', '0', 'no'):
                s.grid = False
                s.apply_plot_style()
                progress_msg("Grid: OFF")
            else:
                print("  Usage: set grid on|off")
        elif key == 'grid_alpha':
            s.grid_alpha = float(val)
            s.apply_plot_style()
            progress_msg(f"Grid alpha: {s.grid_alpha}")
        elif key == 'figsize':
            # Presets in inches. Journal widths converted from cm via / CM_PER_INCH.
            presets = {
                'slide16x9':  (10, 5.6),
                'slide4x3':   (8, 6),
                'a4':         (11.7, 8.3),
                'single_col': (8.3 / CM_PER_INCH, 6.0 / CM_PER_INCH),   # ~3.27 x 2.36 in
                'double_col': (17.1 / CM_PER_INCH, 8.0 / CM_PER_INCH),  # ~6.73 x 3.15 in
                '1.5col':     (12.0 / CM_PER_INCH, 7.0 / CM_PER_INCH),  # ~4.72 x 2.76 in
                'reset':      None,
                'none':       None,
            }
            if val.lower() in presets:
                s.figsize_override = presets[val.lower()]
                if s.figsize_override:
                    s.fig_width, s.fig_height = s.figsize_override
                    progress_msg(f"Figure size preset '{val}': "
                                 f"{s.fig_width:.2f} x {s.fig_height:.2f} inches "
                                 f"({s.fig_width * CM_PER_INCH:.1f} x {s.fig_height * CM_PER_INCH:.1f} cm)")
                else:
                    s.figsize_override = None
                    progress_msg("Figure size override: OFF (using per-function defaults)")
            elif len(parts) >= 3:
                s.fig_width = float(parts[1])
                s.fig_height = float(parts[2])
                s.figsize_override = (s.fig_width, s.fig_height)
                progress_msg(f"Figure size: {s.fig_width} x {s.fig_height} inches")
            else:
                print("  Usage: set figsize <W> <H> | single_col | double_col | 1.5col |")
                print("                     slide16x9 | slide4x3 | a4 | reset")
        elif key == 'pressure_unit' or key == 'press_unit':
            if val.lower() in ('gpa', 'giga'):
                s.pressure_unit = 'gpa'
                progress_msg("Pressure unit: GPa")
            elif val.lower() in ('bar', 'default'):
                s.pressure_unit = 'bar'
                progress_msg("Pressure unit: bar")
            else:
                print("  Usage: set pressure_unit bar|gpa")
        elif key == 'mass':
            s.total_mass_amu = float(val)
            progress_msg(f"Total mass: {s.total_mass_amu:.2f} amu (manual override)")
        elif key == 'theme':
            valid_themes = ['default', 'publication', 'presentation']
            if val.lower() in valid_themes:
                s.theme = val.lower()
                # Theme changes some settings to sensible defaults
                if s.theme == 'publication':
                    s.grid = False
                    s.font_size = 10
                    s.linewidth = 1.2
                    s.marker_size = 4
                    s.dpi = 300
                    s.save_format = 'pdf'
                elif s.theme == 'presentation':
                    s.grid = True
                    s.font_size = 14
                    s.linewidth = 2.0
                    s.marker_size = 6
                    s.dpi = 200
                else:
                    s.grid = True
                    s.font_size = 11
                    s.linewidth = 1.5
                    s.marker_size = 3
                    s.dpi = 150
                    s.save_format = 'png'
                s.apply_plot_style()
                progress_msg(f"Theme: {s.theme} (grid={'on' if s.grid else 'off'}, "
                             f"dpi={s.dpi}, format={s.save_format})")
            else:
                print(f"  Usage: set theme {' | '.join(valid_themes)}")
        elif key == 'save_format' or key == 'format':
            valid_fmts = ['png', 'pdf', 'svg', 'both']
            if val.lower() in valid_fmts:
                s.save_format = val.lower()
                progress_msg(f"Save format: {s.save_format}" +
                             (" (PNG + PDF + SVG)" if s.save_format == 'both' else ""))
            else:
                print(f"  Usage: set save_format {' | '.join(valid_fmts)}")
        else:
            print(f"  Unknown setting: {key}")
            print("  Available: output, surface_z, dt, forcefield, types, dpi, normalize,")
            print("             z_focus, pressure_unit, mass, linewidth, markersize,")
            print("             fontsize, grid, grid_alpha, figsize, theme, save_format")

    def complete_set(self, text, line, begidx, endidx):
        """Tab completion for the 'set' command — lists all configurable settings."""
        opts = ['output', 'surface_z', 'dt', 'forcefield', 'types', 'dpi',
                'normalize', 'z_focus', 'pressure_unit', 'mass',
                'linewidth', 'markersize', 'fontsize',
                'grid', 'grid_alpha', 'figsize', 'theme', 'save_format']
        return [o for o in opts if o.startswith(text)]

    # ─── ANALYZE ───

    def _get_available_analyses(self):
        """
        Return a list of (name, description) tuples for analyses that are
        applicable to the current session state (loaded data + force field).
        Used by the interactive analyze prompt and tab completion.
        """
        s = self.state
        available = []

        # Dump-dependent analyses
        if s.dump_frames:
            if s.has_charge:
                available.append(('charge',       'Fe charge evolution (ReaxFF)'))
                available.append(('charge_z',     'z-direction charge distribution (ReaxFF)'))
                available.append(('or',           'Fe oxidation rate (ReaxFF)'))
            available.append(('rdf',          'Radial distribution function'))
            available.append(('oar',          'Oxygen absorption rate'))
            available.append(('penetration',  'O penetration depth'))
            available.append(('penetration_trend', 'Smoothed O penetration trends'))
            available.append(('density',      'z-direction density profile'))
            available.append(('dissociation', 'O2 dissociation tracking'))
            if s.ff == 'ace':
                available.append(('spin',     'Magnetic spin evolution (ACE)'))
            available.append(('msd',          'Mean square displacement'))
        else:
            # Even without dump, show all possibilities (will prompt to load)
            available.append(('rdf',          'Radial distribution function'))
            available.append(('penetration',  'O penetration depth'))
            available.append(('density',      'z-direction density profile'))
            available.append(('dissociation', 'O2 dissociation tracking'))
            available.append(('msd',          'Mean square displacement'))

        # Log-dependent analyses
        available.append(('performance',  'Stage-wise wall time'))

        # Data-dependent analyses
        available.append(('structure',    'Final structure z-profile'))

        available.append(('all',          'Run ALL applicable analyses'))
        return available

    def do_analyze(self, arg):
        """
        Run an analysis. If no argument is provided, interactively shows
        available analyses and prompts the user to choose one.

        Usage:
            analyze                              — Interactive selection
            analyze <type> [options]             — Direct invocation
            analyze all                          — Run all applicable

        Types: charge, charge_z, rdf, oar, or, penetration, density,
               dissociation, spin, msd, performance, structure, all
        """
        parts = shlex.split(arg) if arg.strip() else []

        # ── Interactive mode: no arguments provided ──
        if not parts:
            available = self._get_available_analyses()
            print(f"\n  {C.bold('Available analyses:')}")
            for i, (name, desc) in enumerate(available, 1):
                # Mark analyses that are already cached
                cached = ''
                if name in self.state.cache or any(
                        k.startswith(f'{name}_') for k in self.state.cache):
                    cached = f" {C.ok('[cached]')}"
                print(f"  {C.CYAN}{i:>3}.{C.RESET} {name:<15} {C.DIM}{desc}{C.RESET}{cached}")
            print()

            choice = self._ask("Enter analysis name or number (or 'all')")
            if choice is None:
                return

            # Accept number or name
            choice = choice.strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(available):
                    what = available[idx][0]
                    parts = [what]
                else:
                    print(C.err(f"  Invalid number. Choose 1-{len(available)}."))
                    return
            else:
                parts = shlex.split(choice)

        what = parts[0].lower()
        s = self.state

        if what == 'all':
            self._analyze_all()
            return

        analyzers = {
            'charge': self._analyze_charge,
            'charge_z': self._analyze_charge_z,
            'rdf': self._analyze_rdf,
            'oar': self._analyze_oar,
            'or': self._analyze_or,
            'penetration': self._analyze_penetration,
            'density': self._analyze_density,
            'dissociation': self._analyze_dissociation,
            'penetration_trend': self._analyze_penetration_trend,
            'spin': self._analyze_spin,
            'msd': self._analyze_msd,
            'performance': self._analyze_performance,
            'structure': self._analyze_structure,
        }

        if what in analyzers:
            analyzers[what](parts[1:])
        else:
            print(f"  Unknown analysis: '{what}'")

    def _analyze_all(self):
        """
        Run all applicable analyses. If no dump is loaded, prompts
        the user to load one first. If surface_z is not set, offers
        auto-detection before running surface-dependent analyses.
        """
        s = self.state

        # If nothing is loaded at all, prompt the user
        if s.dump_frames is None and s.log_data is None and \
                (s.data_atoms is None or len(s.data_atoms) == 0):
            print(C.warn("  No data loaded. Load at least one file first."))
            if not self._require_dump():
                return

        print(f"\n  {C.bold('Running all applicable analyses...')}\n")

        # A trajectory larger than the frame cache would be re-read from disk
        # by every analysis; run them concurrently over one shared read instead.
        # Needs surface_z up front: the RDF z_pbc default depends on whether it
        # was known before the auto-detect below, so that case stays sequential.
        shared = (bool(s.dump_frames) and not s.dump_frames.fits_in_cache
                  and s.surface_z is not None)

        if s.dump_frames:
            jobs = []
            if s.has_charge:
                jobs.append(lambda: self._analyze_charge([]))
                jobs.append(lambda: self._analyze_charge_z([], _batch=True))
                jobs.append(lambda: self._analyze_or([]))
            jobs.append(lambda: self._analyze_rdf([], _batch=True))
            if shared:
                jobs += self._dump_jobs_after_rdf(split_density=True)
                self._run_jobs_shared(jobs)
            else:
                for job in jobs:
                    job()
                for job in self._dump_jobs_after_rdf(split_density=False):
                    job()

        if s.log_data:
            self._analyze_performance([])

        if s.data_atoms is not None and len(s.data_atoms) > 0:
            self._analyze_structure([])

        print(f"\n  {C.ok('All analyses complete.')}")
        print(f"  Cached results: {', '.join(s.cache.keys())}")
        print(f"  Use 'plot <name>' or 'plot all' to generate figures.")

    def _dump_jobs_after_rdf(self, split_density):
        """
        Remaining dump analyses of 'analyze all', in order, as callables.
        Building the list runs the surface auto-detect, which must happen
        after the RDF job when running sequentially.
        """
        s = self.state
        jobs = []
        if s.surface_z is None:
            s._guess_surface_z()
            if s.surface_z:
                progress_msg(f"Auto-detected surface z: {s.surface_z:.1f} A")
        if s.surface_z:
            jobs.append(lambda: self._analyze_oar([]))
            jobs.append(lambda: self._analyze_penetration([]))
            jobs.append(lambda: self._analyze_penetration_trend([]))
        else:
            jobs.append(lambda: print(C.warn(
                "  Skipping OAR/penetration (surface_z unknown). "
                "Use 'set surface_z <value>' to enable.")))
        if split_density:
            # One job per profile, so each joins the shared read instead of
            # three profiles reading the trajectory one after another.
            jobs.append(lambda: self._density_one(None, 'all'))
            for name, type_id in self._density_species().items():
                jobs.append(lambda n=name, t=type_id: self._density_one(t, n))
        else:
            jobs.append(lambda: self._analyze_density([], _batch=True))
        jobs.append(lambda: self._analyze_dissociation([]))
        if s.ff == 'ace':
            jobs.append(lambda: self._analyze_spin([]))
        jobs.append(lambda: self._analyze_msd([], _batch=True))
        return jobs

    def _run_jobs_shared(self, jobs):
        """Run analysis jobs in threads over one shared trajectory read.

        Each job's output is buffered and printed afterwards in job order, so
        the transcript reads the same as a sequential run.
        """
        frames = self.state.dump_frames
        progress_msg(f"Trajectory exceeds the {frames.cache_bytes / 1024 ** 2:.0f} MB frame "
                     f"cache: running {len(jobs)} analyses over one shared read...")
        outputs = [io.StringIO() for _ in jobs]
        errors = [None] * len(jobs)
        proxy = _PerThreadStdout(sys.stdout)

        def run(i, job):
            proxy.redirect(outputs[i])
            try:
                job()
            except Exception:
                errors[i] = traceback.format_exc()

        saved = sys.stdout
        sys.stdout = proxy
        try:
            with frames.shared_pass() as shared:
                threads = [threading.Thread(target=run, args=(i, job), daemon=True)
                           for i, job in enumerate(jobs)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
        finally:
            sys.stdout = saved
        for out, err in zip(outputs, errors):
            sys.stdout.write(out.getvalue())
            if err:
                print(C.err(f"  Analysis failed: {err.strip().splitlines()[-1]}"))
        progress_msg(f"Shared read parsed {shared.frames_parsed} of {len(frames)} frames once "
                     f"for all analyses")

    def _density_species(self):
        return {str(v): k for k, v in self.state.atom_types.items() if isinstance(k, int)}

    def _density_one(self, species_type, species_name):
        s = self.state
        progress_msg(f"Computing density profile (species: {species_name})...")
        s.cache[f'density_{species_name}'] = compute_density_profile(
            s.dump_frames, s.dump_col_idx,
            species_type=species_type, species_name=species_name)

    def _analyze_charge(self, opts):
        if not self._require_dump() or not self._require_charge():
            return
        s = self.state
        progress_msg("Computing charge evolution...")
        result = analyze_charge_evolution(
            s.dump_frames, s.dump_col_idx,
            dt_fs=s.dt_fs, q_thr=s.q_threshold)
        s.cache['charge'] = result
        if result:
            progress_msg(f"Final avg Fe charge: {result['avg'][-1]:.4f} e")
            progress_msg(f"Oxidized Fe (q>{s.q_threshold}): {result['n_oxidized'][-1]}")
        print(C.ok("  Done. Use 'plot charge' to visualize."))

    def _analyze_charge_z(self, opts, _batch=False):
        """
        Compute z-direction charge distribution for a single frame.
        Interactive: if no frame index is given and _batch=False, asks
        the user to choose. In batch mode, defaults to the last frame.
        """
        if not self._require_dump() or not self._require_charge():
            return
        s = self.state

        if opts:
            frame_idx = int(opts[0])
        elif _batch:
            frame_idx = -1  # Default to last frame in batch mode
        else:
            n = len(s.dump_frames)
            ans = self._ask(
                f"Frame index (0 to {n-1}, or -1 for last)", default='-1')
            if ans is None:
                return
            frame_idx = int(ans)

        progress_msg(f"Computing z-direction charge distribution (frame {frame_idx})...")
        result = analyze_charge_z(s.dump_frames[frame_idx], s.dump_col_idx)
        s.cache['charge_z'] = result
        print(C.ok("  Done. Use 'plot charge_z' to visualize."))

    def _analyze_rdf(self, opts, _batch=False):
        """
        Compute RDF g(r) for a specified atom pair.
        Interactive: if no pair is given and _batch=False, shows available
        species and asks the user to choose. Also prompts for number of frames.
        When _batch=True (called from _analyze_all), uses defaults without prompting.
        """
        if not self._require_dump():
            return
        s = self.state

        # Build species name -> type ID mapping
        at = s.atom_types
        inv_map = {}
        species_names = []
        for t, n in at.items():
            if isinstance(t, int):
                inv_map[str(n)] = t
                species_names.append(str(n))
                for short in [n.split('_')[0], n]:
                    inv_map[short] = t

        # Parse pair from opts, or ask interactively
        pair_str = None
        max_frames = 20
        for i, o in enumerate(opts):
            if o == '--frames' and i + 1 < len(opts):
                max_frames = int(opts[i + 1])
            elif pair_str is None and '-' in o:
                pair_str = o
            elif pair_str is None and not o.startswith('-'):
                pair_str = o

        if pair_str is None and not _batch:
            # Interactive: show available species and common pairs
            print(f"  Available species: {', '.join(species_names)}")
            common_pairs = []
            if len(species_names) >= 2:
                for i, a in enumerate(species_names):
                    for b in species_names[i:]:
                        common_pairs.append(f"{a}-{b}")
            if common_pairs:
                print(f"  Suggested pairs: {', '.join(common_pairs[:6])}")
            pair_str = self._ask("Enter atom pair (e.g., Fe-O)", default='Fe-O')
            if pair_str is None:
                return
        elif pair_str is None:
            pair_str = 'Fe-O'  # Default for batch mode

        # Resolve pair to type numbers
        pair_parts = pair_str.split('-')
        if len(pair_parts) != 2:
            pair_parts = ['Fe', 'O']

        type_a = inv_map.get(pair_parts[0], 1)
        type_b = inv_map.get(pair_parts[1], 2)

        # Optionally ask for number of frames if not specified (skip in batch mode)
        if not _batch and '--frames' not in ' '.join(opts) and not opts:
            n_total = len(s.dump_frames)
            frames_ans = self._ask(
                f"Number of frames to average (total: {n_total})",
                default=str(min(20, n_total)))
            if frames_ans:
                try:
                    max_frames = int(frames_ans)
                except ValueError:
                    pass

        # Auto-detect z_pbc from boundary conditions or surface_z
        z_pbc = False  # Safe default for slab geometries
        if s.input_config and s.input_config.get('boundary'):
            z_pbc = s.input_config['boundary'][2] == 'p'
        elif s.surface_z is None:
            z_pbc = True  # No slab detected, assume fully periodic

        progress_msg(f"Computing RDF {pair_str} (last {max_frames} frames, z_pbc={z_pbc})...")
        result = compute_rdf(s.dump_frames, s.dump_col_idx,
                             type_a=type_a, type_b=type_b,
                             max_frames=max_frames,
                             label_a=pair_parts[0], label_b=pair_parts[1],
                             z_pbc=z_pbc)
        cache_key = f'rdf_{pair_str}'
        s.cache[cache_key] = result

        # Report peak position
        if result['g'].max() > 0:
            peak_idx = np.argmax(result['g'])
            progress_msg(f"Peak at r = {result['r'][peak_idx]:.2f} A "
                         f"(g = {result['g'][peak_idx]:.2f})")
        print(C.ok(f"  Done. Use 'plot rdf {pair_str}' to visualize."))

    def _analyze_oar(self, opts):
        if not self._require_dump() or not self._require_surface_z():
            return
        s = self.state
        z_surf = s.surface_z

        o_type = s._guess_o_type()
        progress_msg(f"Computing OAR (surface z = {z_surf:.1f} A)...")
        result = compute_oar(s.dump_frames, s.dump_col_idx,
                             z_surf=z_surf, dt_fs=s.dt_fs, o_type=o_type)
        s.cache['oar'] = result
        progress_msg(f"Final OAR: {result['oar'][-1]:.4f} ({result['n_absorbed'][-1]} O atoms absorbed)")
        print(C.ok("  Done. Use 'plot oar' to visualize."))

    def _analyze_or(self, opts):
        if not self._require_dump() or not self._require_charge():
            return
        s = self.state
        progress_msg("Computing oxidation rate...")
        result = compute_or(s.dump_frames, s.dump_col_idx,
                            dt_fs=s.dt_fs, q_thr=s.q_threshold)
        s.cache['or'] = result
        if result:
            progress_msg(f"Final OR: {result['or'][-1]:.4f}")
        print(C.ok("  Done. Use 'plot or' to visualize."))

    def _analyze_penetration(self, opts):
        if not self._require_dump() or not self._require_surface_z():
            return
        s = self.state
        sz = s.surface_z

        o_type = s._guess_o_type()
        progress_msg(f"Computing O penetration (surface z = {sz:.1f} A)...")
        result = analyze_penetration(s.dump_frames, s.dump_col_idx,
                                     surface_z=sz, dt_fs=s.dt_fs, o_type=o_type)
        s.cache['penetration'] = result
        if len(result['o_min_z']) > 0:
            depth = sz - result['o_min_z'][-1]
            progress_msg(f"Max penetration depth: {depth:.2f} A")
            progress_msg(f"O atoms below surface: {result['n_adsorbed'][-1]}")
        print(C.ok("  Done. Use 'plot penetration' to visualize."))

    def _analyze_penetration_trend(self, opts):
        if not self._require_dump() or not self._require_surface_z():
            return
        s = self.state
        sz = s.surface_z
        o_type = s._guess_o_type()
        progress_msg(f"Computing penetration trends (surface z = {sz:.1f} A)...")
        result = analyze_penetration_trend(s.dump_frames, s.dump_col_idx,
                                           surface_z=sz, dt_fs=s.dt_fs, o_type=o_type)
        s.cache['penetration_trend'] = result
        if result:
            progress_msg(f"Final adsorption ratio: {result['adsorption_ratio'][-1]*100:.1f}%")
            progress_msg(f"Smoothing window: {result['window']} frames")
        print(C.ok("  Done. Use 'plot penetration_trend' to visualize."))

    def _analyze_density(self, opts, _batch=False):
        """
        Compute z-direction density profile.
        Interactive: if no --species flag is given and _batch=False,
        asks whether to run for all species or a specific one.
        In batch mode, defaults to all species.
        """
        if not self._require_dump():
            return
        s = self.state

        # Parse --species from opts
        species_name = None
        for i, o in enumerate(opts):
            if o == '--species' and i + 1 < len(opts):
                species_name = opts[i + 1]

        at = s.atom_types
        inv = {str(v): k for k, v in at.items() if isinstance(k, int)}
        species_list = list(inv.keys())

        # Interactive: ask whether to run for a specific species or all
        if species_name is None and not opts and not _batch:
            if species_list:
                print(f"  Available species: {', '.join(species_list)}")
            choice = self._ask(
                "Species to analyze (or 'all' for every species)",
                default='all')
            if choice is None:
                return
            if choice.lower() != 'all':
                species_name = choice

        # Treat 'all' as no specific species (run all)
        if species_name is not None and species_name.lower() == 'all':
            species_name = None

        if species_name is not None:
            # Single species requested
            species_type = inv.get(species_name)
            if species_type is None:
                print(C.err(f"  Unknown species: '{species_name}'. "
                            f"Available: {', '.join(species_list)}"))
                return
            progress_msg(f"Computing density profile (species: {species_name})...")
            result = compute_density_profile(s.dump_frames, s.dump_col_idx,
                                             species_type=species_type,
                                             species_name=species_name)
            s.cache[f'density_{species_name}'] = result
        else:
            # Auto-run for each species separately + all combined
            progress_msg("Computing density profiles for each species...")
            result = compute_density_profile(s.dump_frames, s.dump_col_idx,
                                             species_type=None, species_name='all')
            s.cache['density_all'] = result
            for name, type_id in inv.items():
                progress_msg(f"  Species: {name} (type {type_id})...")
                r = compute_density_profile(s.dump_frames, s.dump_col_idx,
                                            species_type=type_id, species_name=name)
                s.cache[f'density_{name}'] = r

        print(C.ok("  Done. Use 'plot density' to visualize."))

    def _analyze_dissociation(self, opts):
        if not self._require_dump():
            return
        s = self.state
        o_type = s._guess_o_type()
        progress_msg("Detecting O2 dissociation events...")
        result = detect_o2_dissociation(s.dump_frames, s.dump_col_idx,
                                        dt_fs=s.dt_fs, o_type=o_type)
        s.cache['dissociation'] = result
        if len(result['n_o2']) > 0:
            progress_msg(f"Initial O2: {result['n_o2'][0]}, Final O2: {result['n_o2'][-1]}")
            progress_msg(f"Dissociated O atoms: {result['n_dissociated'][-1]}")
        print(C.ok("  Done. Use 'plot dissociation' to visualize."))

    def _analyze_spin(self, opts):
        if not self._require_dump():
            return
        s = self.state
        if s.ff != 'ace':
            print(C.warn("  Spin analysis is only applicable to ACE simulations."))
            return
        progress_msg("Computing spin evolution...")
        result = analyze_spin_evolution(s.dump_frames, s.dump_col_idx, dt_fs=s.dt_fs)
        s.cache['spin'] = result
        progress_msg(f"Final Fe_up fraction: {result['up_fraction'][-1]:.3f}")
        print(C.ok("  Done. Use 'plot spin' to visualize."))

    def _analyze_msd(self, opts, _batch=False):
        """
        Compute mean square displacement.
        Interactive: if no --species flag is given and _batch=False,
        shows available species and asks the user to choose.
        In batch mode, defaults to 'Fe'.
        """
        if not self._require_dump():
            return
        s = self.state

        # Parse --species from opts
        species_name = None
        for i, o in enumerate(opts):
            if o == '--species' and i + 1 < len(opts):
                species_name = opts[i + 1]

        at = s.atom_types
        inv = {}
        species_list = []
        for k, v in at.items():
            if isinstance(k, int):
                inv[str(v)] = k
                inv[v.split('_')[0]] = k
                species_list.append(str(v))

        # Interactive: ask for species (skip in batch mode)
        if species_name is None and not opts and not _batch:
            if species_list:
                print(f"  Available species: {', '.join(species_list)}")
            species_name = self._ask("Species to analyze", default='Fe')
            if species_name is None:
                return

        if species_name is None:
            species_name = 'Fe'

        species_type = inv.get(species_name)

        progress_msg(f"Computing MSD for {species_name}...")
        result = analyze_msd(s.dump_frames, s.dump_col_idx,
                             species_type=species_type, dt_fs=s.dt_fs)
        cache_key = f'msd_{species_name}'
        s.cache[cache_key] = result
        if result and len(result['msd']) > 0:
            progress_msg(f"Final MSD: {result['msd'][-1]:.2f} A^2")
        print(C.ok(f"  Done. Use 'plot msd' to visualize."))

    def _analyze_performance(self, opts):
        if not self._require_log():
            return
        s = self.state
        result = analyze_stage_performance(s.log_data)
        s.cache['performance'] = result
        if result:
            total = sum(result.values())
            progress_msg(f"Total wall time: {total:.1f} s ({total/3600:.2f} hr)")
        print(C.ok("  Done. Use 'plot performance' or 'show stages' to view."))

    def _analyze_structure(self, opts):
        s = self.state

        # Prefer data file if loaded; otherwise use last dump frame
        if s.data_atoms is not None and len(s.data_atoms) > 0:
            source = 'data file'
            atoms_array = s.data_atoms
        elif s.dump_frames is not None and len(s.dump_frames) > 0:
            source = 'last dump frame'
            fr = s.dump_frames[-1]
            ti = s.dump_col_idx['type']
            xi, yi, zi = s.dump_col_idx['x'], s.dump_col_idx['y'], s.dump_col_idx['z']
            idi = s.dump_col_idx.get('id', s.dump_col_idx['x'])  # fallback
            atoms = fr['atoms']
            # Build [id, type, x, y, z] array to match data file format
            id_col = atoms[:, s.dump_col_idx['id']] if 'id' in s.dump_col_idx else np.arange(1, len(atoms) + 1)
            atoms_array = np.column_stack([
                id_col, atoms[:, ti], atoms[:, xi], atoms[:, yi], atoms[:, zi]
            ])
        else:
            print(C.warn("  No data file or dump loaded."))
            return

        progress_msg(f"Analyzing structure from {source} (step {s.dump_frames[-1]['timestep'] if source == 'last dump frame' else 'static'})...")
        result = analyze_structure(atoms_array, z_surface=s.surface_z)
        s.cache['structure'] = result
        # Also store for plot_structure
        s._structure_atoms = atoms_array
        if result:
            for t, info in result.items():
                name = s.atom_types.get(int(t), f'Type {t}')
                progress_msg(f"  {name}: {info['count']} atoms, z=[{info['z_min']:.1f}, {info['z_max']:.1f}] A")
        print(C.ok("  Done. Use 'plot structure' to visualize."))

    def complete_analyze(self, text, line, begidx, endidx):
        analyses = ['charge', 'charge_z', 'rdf', 'oar', 'or', 'penetration',
                     'density', 'dissociation', 'spin', 'msd', 'performance',
                     'structure', 'all']
        s = self.state
        if s.ff != 'reaxff':
            analyses = [a for a in analyses if a not in ('charge', 'charge_z', 'or')]
        if s.ff != 'ace':
            analyses = [a for a in analyses if a != 'spin']
        return [a for a in analyses if a.startswith(text)]

    # ─── PLOT ───

    def _get_available_plots(self):
        """
        Return a list of (name, description, ready) tuples for plot types
        applicable to the current session state.
        'ready' is True if the required data is already cached or loaded.
        Used by the interactive plot prompt.
        """
        s = self.state
        available = []

        # Log-dependent plots
        available.append(('thermo', 'Thermodynamic properties (T, P, E, V, density)',
                          bool(s.log_data)))
        available.append(('thermostat', 'Thermostat QC summary (T+P twinx)',
                          bool(s.log_data)))
        available.append(('pressure', 'Pressure analysis (stress tensor, slab correction)',
                          bool(s.log_data)))

        # Dump-dependent plots: charge-related (ReaxFF only)
        if s.dump_frames and s.has_charge:
            available.append(('charge', 'Fe charge evolution (ReaxFF)',
                              'charge' in s.cache))
            available.append(('charge_z', 'z-direction charge distribution (ReaxFF)',
                              'charge_z' in s.cache))
            available.append(('oar', 'Oxygen absorption rate',
                              'oar' in s.cache))
            available.append(('or', 'Fe oxidation rate (ReaxFF)',
                              'or' in s.cache))

        # Dump-dependent plots: general
        if s.dump_frames or any(k.startswith('rdf_') for k in s.cache):
            available.append(('rdf', 'Radial distribution function',
                              any(k.startswith('rdf_') for k in s.cache)))
        if s.dump_frames or 'penetration' in s.cache:
            available.append(('penetration', 'O penetration depth',
                              'penetration' in s.cache))
            available.append(('penetration_profile', 'O penetration profiling (5 plots: trajectories, kymograph, ridge, timeline, 3D)',
                              'penetration_profile' in s.cache))
        if s.dump_frames or any(k.startswith('density_') for k in s.cache):
            available.append(('density', 'z-direction density profile',
                              any(k.startswith('density_') for k in s.cache)))
        if s.dump_frames or 'dissociation' in s.cache:
            available.append(('dissociation', 'O2 dissociation tracking',
                              'dissociation' in s.cache))
        if (s.dump_frames and s.ff == 'ace') or 'spin' in s.cache:
            available.append(('spin', 'Magnetic spin evolution (ACE)',
                              'spin' in s.cache))
        if s.dump_frames or any(k.startswith('msd_') for k in s.cache):
            available.append(('msd', 'Mean square displacement',
                              any(k.startswith('msd_') for k in s.cache)))

        # Log-dependent
        available.append(('performance', 'Stage-wise wall time',
                          'performance' in s.cache))

        # Data-dependent
        if s.data_atoms is not None:
            available.append(('structure', 'Final structure z-profile', True))

        # Dump-dependent: snapshots
        if s.dump_frames:
            available.append(('snapshot', 'z-x plane atomic snapshots', True))

        available.append(('all', 'Generate ALL applicable plots', False))
        return available

    def do_plot(self, arg):
        """
        Generate a plot. If no argument is provided, interactively shows
        available plot types and prompts the user to choose one.

        Usage:
            plot                                 — Interactive selection
            plot <type> [options]                — Direct invocation
            plot all                            — Generate all applicable plots
            plot redo <type>                    — Regenerate using saved settings (no prompts)
            plot edit <type>                    — Show saved settings, modify, regenerate
            plot recipes                        — List all saved plot recipes
            plot save_defaults <type>           — Save recipe as session defaults

        Types: thermo, charge, charge_z, rdf, oar, or, penetration, density,
               dissociation, spin, msd, performance, structure, snapshot, all
        """
        parts = shlex.split(arg) if arg.strip() else []

        # ── plot recipes: show saved recipes ──
        if parts and parts[0] == 'recipes':
            recipes = self.state.plot_recipes
            if not recipes:
                print(C.dim("  No saved plot recipes."))
            else:
                print(f"\n  {C.bold('Saved plot recipes:')}")
                for name, recipe in sorted(recipes.items()):
                    display_items = [f"{k}={v}" for k, v in recipe.items() if not k.startswith('_')]
                    print(f"    {C.CYAN}{name}{C.RESET}: {', '.join(display_items)}")
                print()
                print(f"  {C.DIM}Use 'plot redo <type>' to regenerate, 'plot edit <type>' to modify{C.RESET}")
            return

        # ── plot save_defaults <type>: save recipe as session defaults ──
        if len(parts) >= 2 and parts[0] == 'save_defaults':
            recipe_key = parts[1].lower()
            recipe = self.state.plot_recipes.get(recipe_key)
            if not recipe:
                print(C.warn(f"  No saved recipe for '{recipe_key}'."))
                return
            if 'normalize' in recipe:
                self.state.normalize = recipe['normalize']
            if 'lw' in recipe:
                self.state.linewidth = recipe['lw']
            if 'z_focus' in recipe:
                self.state.z_focus = recipe['z_focus']
            if 'figsize' in recipe:
                self.state.figsize_override = recipe['figsize']
            self.state.apply_plot_style()
            progress_msg(f"Recipe '{recipe_key}' saved as session defaults")
            return

        # ── plot redo <type>: regenerate with saved recipe ──
        if len(parts) >= 2 and parts[0] == 'redo':
            redo_type = parts[1].lower()
            recipe = self.state.plot_recipes.get(redo_type)
            if not recipe:
                print(C.warn(f"  No saved recipe for '{redo_type}'. Run 'plot {redo_type}' first."))
                return
            progress_msg(f"Regenerating '{redo_type}' with saved settings...")
            parts = [redo_type] + parts[2:]
            # Fall through to normal dispatch with _batch=True (uses recipe defaults)

        # ── plot edit <type>: edit saved recipe and regenerate ──
        _edit_mode = False
        if len(parts) >= 2 and parts[0] == 'edit':
            edit_type = parts[1].lower()
            if edit_type not in self.state.plot_recipes:
                print(C.warn(f"  No saved recipe for '{edit_type}'. Run 'plot {edit_type}' first."))
                return
            _edit_mode = True
            parts = [edit_type] + parts[2:]

        # ── Interactive mode: no arguments provided ──
        if not parts:
            available = self._get_available_plots()
            if len(available) <= 1:
                print(C.warn("  No data loaded. Use 'load' first."))
                return
            print(f"\n  {C.bold('Available plot types:')}")
            for i, (name, desc, ready) in enumerate(available, 1):
                status = ''
                if name == 'all':
                    pass
                elif ready:
                    status = f" {C.ok('[ready]')}"
                else:
                    status = f" {C.DIM}[need analyze]{C.RESET}"
                print(f"  {C.CYAN}{i:>3}.{C.RESET} {name:<15} {C.DIM}{desc}{C.RESET}{status}")
            print()
            print(f"  {C.DIM}[ready] = data available, [need analyze] = run 'analyze' first{C.RESET}")
            print()

            choice = self._ask("Enter plot type name or number (or 'all')")
            if choice is None:
                return

            choice = choice.strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(available):
                    what = available[idx][0]
                    parts = [what]
                else:
                    print(C.err(f"  Invalid number. Choose 1-{len(available)}."))
                    return
            else:
                parts = shlex.split(choice)

        what = parts[0].lower()
        s = self.state

        # ── Confirm output directory before plotting ──
        # Shows current path and lets user change it (Enter to keep).
        # Only prompt if stdin is interactive (skip in batch/one-shot mode).
        current = s.output_dir or './lammps-post_output'
        if sys.stdin.isatty():
            new_dir = self._ask(f"Output directory", current)
            if new_dir and new_dir != current:
                s.output_dir = new_dir
                progress_msg(f"Output directory: {s.output_dir}")
            elif new_dir:
                s.output_dir = new_dir
        else:
            s.output_dir = current

        os.makedirs(s.output_dir, exist_ok=True)

        # Apply current plot style settings before generating any plots
        s.apply_plot_style()

        if what == 'all':
            self._plot_all()
            return

        # ── Dispatch to per-type interactive plotters ──
        plot_dispatch = {
            'thermo':       self._iplot_thermo,
            'thermostat':   self._iplot_thermostat,
            'pressure':     self._iplot_pressure,
            'charge':       self._iplot_charge,
            'charge_z':     self._iplot_charge_z,
            'rdf':          self._iplot_rdf,
            'oar':          self._iplot_oar,
            'or':           self._iplot_or,
            'penetration':  self._iplot_penetration,
            'penetration_trend': self._iplot_penetration_trend,
            'penetration_profile': self._iplot_penetration_profile,
            'density':      self._iplot_density,
            'dissociation': self._iplot_dissociation,
            'spin':         self._iplot_spin,
            'msd':          self._iplot_msd,
            'performance':  self._iplot_performance,
            'structure':    self._iplot_structure,
            'snapshot':     self._iplot_snapshot,
        }

        if what in plot_dispatch:
            # Determine mode: redo (silent with saved recipe) or edit (interactive with saved defaults)
            is_redo = (what in s.plot_recipes and
                       len(arg.split()) >= 2 and arg.split()[0] == 'redo')
            plot_dispatch[what](parts[1:], _batch=is_redo, _edit_mode=_edit_mode)
        else:
            print(f"  Unknown plot type: '{what}'")

    # ── Per-type interactive plot methods ──
    # Each method: (1) ensures data exists (auto-analyze if missing),
    # (2) asks user about plot-specific options when called interactively,
    # (3) generates the plot. The _batch parameter suppresses prompts
    # when called from _plot_all.

    def _iplot_common_opts(self, plot_name, edit_mode=False):
        """
        Ask common plot options shared by most plot types.
        Returns dict with: normalize, z_focus, linewidth, figsize.
        Returns None if user cancels.

        If a previous recipe exists for this plot_name, uses those values
        as defaults. In edit_mode, shows the saved settings and only asks
        for changes.
        """
        s = self.state
        recipe_key = plot_name.lower().replace(' ', '_').replace('-', '_')

        # Load previous recipe as defaults if available
        prev = s.plot_recipes.get(recipe_key, {})

        opts = {
            'normalize': prev.get('normalize', s.normalize),
            'z_focus': prev.get('z_focus', s.compute_z_focus()),
            'lw': prev.get('lw', s.linewidth),
            'figsize': prev.get('figsize', s.figsize_override),
        }

        if edit_mode and prev:
            print(f"\n  {C.bold(f'Edit settings for: {plot_name}')}")
            print(f"  {C.DIM}(saved recipe shown as defaults — Enter to keep){C.RESET}\n")
        else:
            print(f"\n  {C.bold(f'Plot options for: {plot_name}')}")
            print(f"  {C.DIM}(press Enter to keep defaults){C.RESET}\n")

        # Normalize
        cur = 'ON' if opts['normalize'] else 'OFF'
        ans = self._ask(f"Normalize mode (ratios/fractions)? [y/n]", cur)
        if ans is None:
            return None
        if ans.lower() in ('y', 'yes', 'on'):
            opts['normalize'] = True
        elif ans.lower() in ('n', 'no', 'off'):
            opts['normalize'] = False

        # z_focus
        zf = opts['z_focus']
        cur_zf = f"{zf[0]:.1f}:{zf[1]:.1f}" if zf else "full range"
        ans = self._ask(f"z-axis focus range in A? (e.g. '0:30', '-10:30', 'full')", cur_zf)
        if ans is None:
            return None
        ans = ans.strip().lower()
        if ans in ('full', 'none', 'all', ''):
            opts['z_focus'] = None
        elif ':' in ans:
            try:
                lo, hi = ans.split(':', 1)
                opts['z_focus'] = (float(lo), float(hi))
            except ValueError:
                pass
        elif ',' in ans:
            try:
                lo, hi = ans.split(',', 1)
                opts['z_focus'] = (float(lo), float(hi))
            except ValueError:
                pass

        # Line width
        ans = self._ask(f"Line width", str(opts['lw']))
        if ans is None:
            return None
        try:
            opts['lw'] = float(ans)
        except ValueError:
            pass

        # Save recipe
        s.plot_recipes[recipe_key] = opts.copy()
        return opts

    def _save_recipe(self, plot_name, extra=None):
        """Save plot-specific parameters to recipe store for redo/edit."""
        s = self.state
        recipe_key = plot_name.lower().replace(' ', '_').replace('-', '_')
        recipe = s.plot_recipes.get(recipe_key, {})
        if extra:
            recipe.update(extra)
        # Always save output_dir and dpi used
        recipe['_output_dir'] = s.output_dir
        recipe['_dpi'] = s.dpi
        s.plot_recipes[recipe_key] = recipe

    def _ensure_cache(self, key, analyzer_name, analyzer_args=None):
        """Auto-run analysis if data is missing from cache. Returns True if data available."""
        s = self.state
        if key in s.cache:
            return True
        # Check prefix-style keys (rdf_, density_, msd_)
        if any(k.startswith(f'{key}_') for k in s.cache):
            return True
        analyzer_method = getattr(self, analyzer_name, None)
        if analyzer_method:
            if self._ask_yn(f"No data for '{key}'. Run analyze {key} now?"):
                # Only pass _batch if the analyzer accepts it
                import inspect
                sig = inspect.signature(analyzer_method)
                if '_batch' in sig.parameters:
                    analyzer_method(analyzer_args or [], _batch=True)
                else:
                    analyzer_method(analyzer_args or [])
                return key in s.cache or any(k.startswith(f'{key}_') for k in s.cache)
        return False

    def _iplot_thermo(self, opts, _batch=False, _edit_mode=False):
        """Interactive thermo plot — passes dt_fs, pressure_unit, total_mass_amu, figsize."""
        s = self.state
        if s.log_data is None:
            print(C.warn("  No log data loaded. Use 'load log' first."))
            return
        plot_thermo(s.log_data, s.output_dir, s.dpi,
                    dt_fs=s.dt_fs, pressure_unit=s.pressure_unit,
                    total_mass_amu=s.total_mass_amu,
                    figsize=s.figsize_override,
                    unit_system=s.ff_info.get('unit_system', 'metal'))
        self._save_recipe('thermo', {'pressure_unit': s.pressure_unit})

    def _iplot_thermostat(self, opts, _batch=False, _edit_mode=False):
        """Interactive thermostat twinx summary plot."""
        s = self.state
        if s.log_data is None:
            print(C.warn("  No log data loaded. Use 'load log' first."))
            return
        plot_thermostat_summary(s.log_data, s.output_dir, s.dpi,
                                dt_fs=s.dt_fs, pressure_unit=s.pressure_unit,
                                figsize=s.figsize_override)
        self._save_recipe('thermostat', {'pressure_unit': s.pressure_unit})

    def _iplot_pressure(self, opts, _batch=False, _edit_mode=False):
        """Interactive pressure analysis plot — shows stress tensor and slab correction."""
        s = self.state
        if s.log_data is None:
            print(C.warn("  No log data loaded. Use 'load log' first."))
            return

        # Check if stress tensor components are available
        d = s.log_data
        has_stress = all(k in d for k in ('pxx', 'pyy', 'pzz'))
        if not has_stress:
            print(C.warn("  Pxx/Pyy/Pzz not found in log data."))
            print(f"  {C.DIM}Add to your LAMMPS input: thermo_style custom step temp pe ke etotal press pxx pyy pzz vol{C.RESET}")
            print(f"  {C.DIM}Generating basic pressure plot from total Press...{C.RESET}")

        # Ask about slab z-range if not in batch mode
        slab_z = None
        if not _batch:
            recipe = s.plot_recipes.get('pressure', {})
            prev_slab = recipe.get('slab_z_range')

            if prev_slab:
                default = f"{prev_slab[0]:.1f}-{prev_slab[1]:.1f}"
            elif s.surface_z:
                # Suggest slab range based on detected surface
                default = f"0-{s.surface_z:.0f}"
            else:
                default = 'none'

            ans = self._ask("Slab z-range for correction (e.g. '0-80', or 'none' for bulk)", default)
            if ans and ans.lower() not in ('none', 'n', 'full', ''):
                try:
                    lo, hi = ans.split('-', 1)
                    slab_z = (float(lo), float(hi))
                except ValueError:
                    pass
        else:
            slab_z = s.plot_recipes.get('pressure', {}).get('slab_z_range')

        plot_pressure(s.log_data, s.output_dir, s.dpi,
                      dt_fs=s.dt_fs, pressure_unit=s.pressure_unit,
                      slab_z_range=slab_z, figsize=s.figsize_override)
        self._save_recipe('pressure', {
            'pressure_unit': s.pressure_unit,
            'slab_z_range': slab_z,
        })

    def _iplot_charge(self, opts, _batch=False, _edit_mode=False):
        """Interactive charge evolution plot."""
        s = self.state
        if not self._ensure_cache('charge', '_analyze_charge'):
            return
        recipe = s.plot_recipes.get('charge_evolution', {})
        if _batch:
            norm = recipe.get('normalize', s.normalize)
            lw = recipe.get('lw', s.linewidth)
            plt.rcParams['lines.linewidth'] = lw
            plot_charge_evolution(s.cache['charge'], s.output_dir, s.dpi,
                                  normalize=norm, figsize=s.figsize_override)
            return

        popts = self._iplot_common_opts('charge_evolution', edit_mode=_edit_mode)
        if popts is None:
            return
        plt.rcParams['lines.linewidth'] = popts['lw']
        plot_charge_evolution(s.cache['charge'], s.output_dir, s.dpi,
                              normalize=popts['normalize'], figsize=s.figsize_override)

    def _iplot_charge_z(self, opts, _batch=False, _edit_mode=False):
        """Interactive charge z-distribution plot."""
        s = self.state
        if not self._ensure_cache('charge_z', '_analyze_charge_z'):
            return
        recipe = s.plot_recipes.get('charge_z_distribution', {})
        if _batch:
            norm = recipe.get('normalize', s.normalize)
            zf = recipe.get('z_focus', s.compute_z_focus())
            lw = recipe.get('lw', s.linewidth)
            plt.rcParams['lines.linewidth'] = lw
            plot_charge_z(s.cache['charge_z'], s.output_dir, s.dpi,
                          normalize=norm, z_focus=zf,
                          figsize=s.figsize_override)
            return

        popts = self._iplot_common_opts('charge_z_distribution', edit_mode=_edit_mode)
        if popts is None:
            return
        plt.rcParams['lines.linewidth'] = popts['lw']
        plot_charge_z(s.cache['charge_z'], s.output_dir, s.dpi,
                      normalize=popts['normalize'], z_focus=popts['z_focus'],
                      figsize=s.figsize_override)

    def _iplot_rdf(self, opts, _batch=False, _edit_mode=False):
        """Interactive RDF plot — asks which pairs to plot, with optional reference overlays."""
        from lammps_post.references import (
            compute_reference_rdf, get_available_phases, get_phases_for_pair, parse_cif
        )

        s = self.state
        rdf_keys = [k for k in s.cache if k.startswith('rdf_')]

        # If a pair is specified via command args, use it directly
        pair_str = opts[0] if opts else None
        if pair_str:
            key = f'rdf_{pair_str}'
            if key not in s.cache:
                if self._ask_yn(f"No cached RDF for '{pair_str}'. Run analyze rdf {pair_str} now?"):
                    self._analyze_rdf([pair_str], _batch=True)
            if f'rdf_{pair_str}' in s.cache:
                plot_rdf(s.cache[f'rdf_{pair_str}'], s.output_dir, s.dpi, figsize=s.figsize_override)
                self._save_recipe('rdf')
            return

        # No cached data at all — run analysis first or skip in batch
        if not rdf_keys:
            if _batch:
                return
            if self._ask_yn("No RDF data. Run analyze rdf now?"):
                self._analyze_rdf([], _batch=True)
                rdf_keys = [k for k in s.cache if k.startswith('rdf_')]
            if not rdf_keys:
                return

        if _batch:
            # Use saved recipe for reference overlays
            recipe = s.plot_recipes.get('rdf', {})
            ref_rdfs = recipe.get('_ref_rdfs')
            for k in rdf_keys:
                plot_rdf(s.cache[k], s.output_dir, s.dpi,
                         figsize=s.figsize_override, ref_rdfs=ref_rdfs)
            self._save_recipe('rdf')
            return

        # Interactive: show available pairs and let user pick
        print(f"\n  {C.bold('Cached RDF pairs:')}")
        for i, k in enumerate(rdf_keys, 1):
            pair = k.replace('rdf_', '').replace('_', '-')
            print(f"  {C.CYAN}{i:>3}.{C.RESET} {pair}")
        print(f"  {C.CYAN}{len(rdf_keys)+1:>3}.{C.RESET} All pairs")
        print()

        choice = self._ask("Which pair to plot? (number or 'all')", 'all')
        if choice is None:
            return
        choice = choice.strip()

        if choice.lower() == 'all' or choice == str(len(rdf_keys) + 1):
            selected = rdf_keys
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(rdf_keys):
                selected = [rdf_keys[idx]]
            else:
                print(C.err(f"  Invalid number."))
                return
        else:
            selected = rdf_keys

        # ── Ask about reference RDF overlays ──
        ref_rdfs = None
        ans = self._ask("Overlay reference crystal g(r)? (y/n)", 'y')
        if ans and ans.lower() in ('y', 'yes'):
            # Determine pair from the first selected RDF
            rdf_pair = selected[0].replace('rdf_', '').split('_')
            if len(rdf_pair) == 2:
                pair_tuple = (rdf_pair[0], rdf_pair[1])
            else:
                pair_tuple = ('Fe', 'O')

            # Show available references
            builtin = get_phases_for_pair(pair_tuple)
            print(f"\n  {C.bold('Available references for ' + '-'.join(pair_tuple) + ':')}")
            for i, phase in enumerate(builtin, 1):
                phases_db = dict(get_available_phases())
                print(f"    {C.CYAN}{i}.{C.RESET} {phases_db.get(phase, phase)}")
            print(f"    {C.CYAN}{len(builtin)+1}.{C.RESET} All built-in phases")
            print(f"    {C.CYAN}{len(builtin)+2}.{C.RESET} Load CIF file or COD ID")
            print()

            ref_choice = self._ask("Select references (numbers, e.g. '1,3' or 'all')", 'all')
            if ref_choice is None:
                ref_choice = ''

            ref_rdfs = []

            # Check for CIF option
            if ref_choice.strip() == str(len(builtin) + 2):
                cif_src = self._ask("CIF file path or COD ID (e.g. 'cod:9009768')")
                if cif_src:
                    progress_msg(f"Loading CIF: {cif_src}")
                    crystal = parse_cif(cif_src)
                    if crystal:
                        ref = compute_reference_rdf(crystal, pair=pair_tuple, r_max=6.0)
                        if ref:
                            ref_rdfs.append(ref)
                            progress_msg(f"Reference loaded: {ref['label']}")
                        else:
                            print(C.warn(f"  Could not compute RDF for this pair from CIF."))
                    else:
                        print(C.warn(f"  Failed to parse CIF."))
            else:
                # Parse selected built-in phases
                if ref_choice.lower() in ('all', str(len(builtin) + 1)):
                    sel_phases = builtin
                else:
                    sel_phases = []
                    for token in ref_choice.replace(',', ' ').split():
                        if token.isdigit():
                            idx = int(token) - 1
                            if 0 <= idx < len(builtin):
                                sel_phases.append(builtin[idx])

                for phase in sel_phases:
                    ref = compute_reference_rdf(phase, pair=pair_tuple, r_max=6.0)
                    if ref:
                        ref_rdfs.append(ref)

            if not ref_rdfs:
                ref_rdfs = None

        # Generate plots
        for k in selected:
            plot_rdf(s.cache[k], s.output_dir, s.dpi,
                     figsize=s.figsize_override, ref_rdfs=ref_rdfs)
        self._save_recipe('rdf', {'_ref_rdfs': ref_rdfs})
        self._save_recipe('rdf')

    def _iplot_oar(self, opts, _batch=False, _edit_mode=False):
        """Interactive OAR plot."""
        s = self.state
        if not self._ensure_cache('oar', '_analyze_oar'):
            return
        if _batch:
            plot_oar(s.cache['oar'], s.output_dir, s.dpi, normalize=s.normalize,
                        figsize=s.figsize_override)
            return

        popts = self._iplot_common_opts('Oxygen Absorption Rate', edit_mode=_edit_mode)
        if popts is None:
            return
        plt.rcParams['lines.linewidth'] = popts['lw']
        plot_oar(s.cache['oar'], s.output_dir, s.dpi, normalize=popts['normalize'],
                figsize=s.figsize_override)

    def _iplot_or(self, opts, _batch=False, _edit_mode=False):
        """Interactive oxidation rate plot."""
        s = self.state
        if not self._ensure_cache('or', '_analyze_or'):
            return
        if _batch:
            plot_or(s.cache['or'], s.output_dir, s.dpi, figsize=s.figsize_override)
            return

        ans = self._ask("Line width", str(s.linewidth))
        if ans is None:
            return
        try:
            lw = float(ans)
        except ValueError:
            lw = s.linewidth
        plt.rcParams['lines.linewidth'] = lw
        plot_or(s.cache['or'], s.output_dir, s.dpi, figsize=s.figsize_override)

    def _iplot_penetration(self, opts, _batch=False, _edit_mode=False):
        """Interactive penetration plot — asks normalize and z_focus."""
        s = self.state
        if not self._ensure_cache('penetration', '_analyze_penetration'):
            return
        if _batch:
            plot_penetration(s.cache['penetration'], s.output_dir, s.dpi,
                             normalize=s.normalize, figsize=s.figsize_override)
            return

        popts = self._iplot_common_opts('O Penetration', edit_mode=_edit_mode)
        if popts is None:
            return
        plt.rcParams['lines.linewidth'] = popts['lw']
        plot_penetration(s.cache['penetration'], s.output_dir, s.dpi,
                         normalize=popts['normalize'], figsize=s.figsize_override)

    def _iplot_penetration_trend(self, opts, _batch=False, _edit_mode=False):
        """Interactive penetration trend plot — smoothed trend lines."""
        s = self.state
        if not self._ensure_cache('penetration_trend', '_analyze_penetration_trend'):
            return
        if _batch:
            plot_penetration_trend(s.cache['penetration_trend'], s.output_dir, s.dpi,
                                   figsize=s.figsize_override)
            return

        popts = self._iplot_common_opts('O Penetration Trend', edit_mode=_edit_mode)
        if popts is None:
            return
        plt.rcParams['lines.linewidth'] = popts['lw']
        plot_penetration_trend(s.cache['penetration_trend'], s.output_dir, s.dpi,
                               figsize=s.figsize_override)
        self._save_recipe('penetration_trend')

    def _iplot_penetration_profile(self, opts, _batch=False, _edit_mode=False):
        """Interactive penetration profiling — generates 5 detailed plots."""
        s = self.state
        if s.dump_frames is None:
            print(C.warn("  No dump file loaded. Use 'load dump' first."))
            return

        # Run analysis if not cached
        if 'penetration_profile' not in s.cache:
            progress_msg("Computing O penetration profile...")
            o_type = s._guess_o_type()
            result = analyze_penetration_profile(
                s.dump_frames, s.dump_col_idx, dt_fs=s.dt_fs, o_type=o_type)
            if result is None:
                print(C.warn("  No O atoms found in trajectory."))
                return
            s.cache['penetration_profile'] = result
            progress_msg(f"Tracked {result['n_o']} O atoms across {len(result['time'])} frames")
            progress_msg(f"Adsorbed: {len(result['cross_times'])}/{result['n_o']} O atoms crossed surface")

        data = s.cache['penetration_profile']
        zf = s.z_focus or s.compute_z_focus()
        plot_penetration_profile(data, s.output_dir, s.dpi,
                                  figsize=s.figsize_override, z_focus=zf)
        self._save_recipe('penetration_profile')

    def _iplot_density(self, opts, _batch=False, _edit_mode=False):
        """Interactive density profile plot — asks species and z_focus."""
        s = self.state
        dens_keys = [k for k in s.cache if k.startswith('density_')]
        if not dens_keys:
            if _batch:
                return  # Skip silently in batch mode
            if self._ask_yn("No density data. Run analyze density now?"):
                self._analyze_density([], _batch=True)
                dens_keys = [k for k in s.cache if k.startswith('density_')]
            if not dens_keys:
                return

        if _batch:
            data_list = [s.cache[k] for k in dens_keys]
            plot_density(data_list, s.output_dir, s.dpi, z_focus=s.compute_z_focus(),
                         figsize=s.figsize_override)
            return

        # Interactive: show cached species, let user pick
        print(f"\n  {C.bold('Cached density profiles:')}")
        for i, k in enumerate(dens_keys, 1):
            sp = k.replace('density_', '')
            print(f"  {C.CYAN}{i:>3}.{C.RESET} {sp}")
        print(f"  {C.CYAN}{len(dens_keys)+1:>3}.{C.RESET} All species (overlay)")
        print()

        choice = self._ask("Which species to plot? (number or 'all')", 'all')
        if choice is None:
            return
        choice = choice.strip()

        if choice.lower() == 'all' or choice == str(len(dens_keys) + 1):
            selected = dens_keys
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(dens_keys):
                selected = [dens_keys[idx]]
            else:
                print(C.err("  Invalid number."))
                return
        else:
            selected = dens_keys

        # z_focus
        zf = s.compute_z_focus()
        cur_zf = f"{zf[0]:.1f}-{zf[1]:.1f}" if zf else "full range"
        ans = self._ask(f"z-axis focus range in A? (e.g. '0-30', 'full')", cur_zf)
        if ans is not None:
            ans = ans.strip().lower()
            if ans in ('full', 'none', 'all'):
                zf = None
            elif '-' in ans:
                try:
                    lo, hi = ans.split('-', 1)
                    zf = (float(lo), float(hi))
                except ValueError:
                    pass

        data_list = [s.cache[k] for k in selected]
        plot_density(data_list, s.output_dir, s.dpi, z_focus=zf,
                     figsize=s.figsize_override)

    def _iplot_dissociation(self, opts, _batch=False, _edit_mode=False):
        """Interactive dissociation plot."""
        s = self.state
        if not self._ensure_cache('dissociation', '_analyze_dissociation'):
            return
        if _batch:
            plot_dissociation(s.cache['dissociation'], s.output_dir, s.dpi,
                              normalize=s.normalize, figsize=s.figsize_override)
            return

        popts = self._iplot_common_opts('O2 Dissociation', edit_mode=_edit_mode)
        if popts is None:
            return
        plt.rcParams['lines.linewidth'] = popts['lw']
        plot_dissociation(s.cache['dissociation'], s.output_dir, s.dpi,
                          normalize=popts['normalize'], figsize=s.figsize_override)

    def _iplot_spin(self, opts, _batch=False, _edit_mode=False):
        """Interactive spin evolution plot."""
        s = self.state
        if not self._ensure_cache('spin', '_analyze_spin'):
            return
        if _batch:
            plot_spin(s.cache['spin'], s.output_dir, s.dpi, normalize=s.normalize,
                      figsize=s.figsize_override)
            return

        popts = self._iplot_common_opts('Spin Evolution', edit_mode=_edit_mode)
        if popts is None:
            return
        plt.rcParams['lines.linewidth'] = popts['lw']
        plot_spin(s.cache['spin'], s.output_dir, s.dpi,
                  normalize=popts['normalize'], figsize=s.figsize_override)

    def _iplot_msd(self, opts, _batch=False, _edit_mode=False):
        """Interactive MSD plot — asks which species."""
        s = self.state
        msd_keys = [k for k in s.cache if k.startswith('msd_')]

        # Explicit species from command args
        sp = opts[0] if opts else None
        if sp:
            key = f'msd_{sp}'
            if key not in s.cache:
                if self._ask_yn(f"No MSD for '{sp}'. Run analyze msd --species {sp} now?"):
                    self._analyze_msd(['--species', sp], _batch=True)
            if f'msd_{sp}' in s.cache:
                plot_msd(s.cache[f'msd_{sp}'], sp, s.output_dir, s.dpi,
                            figsize=s.figsize_override)
            return

        if not msd_keys:
            if _batch:
                return  # Skip silently in batch mode
            if self._ask_yn("No MSD data. Run analyze msd now?"):
                self._analyze_msd([], _batch=True)
                msd_keys = [k for k in s.cache if k.startswith('msd_')]
            if not msd_keys:
                return

        if _batch:
            for k in msd_keys:
                plot_msd(s.cache[k], k.replace('msd_', ''), s.output_dir, s.dpi,
                        figsize=s.figsize_override)
            return

        # Interactive: show cached species
        print(f"\n  {C.bold('Cached MSD species:')}")
        for i, k in enumerate(msd_keys, 1):
            sp_name = k.replace('msd_', '')
            print(f"  {C.CYAN}{i:>3}.{C.RESET} {sp_name}")
        print(f"  {C.CYAN}{len(msd_keys)+1:>3}.{C.RESET} All species")
        print()

        choice = self._ask("Which species to plot? (number or 'all')", 'all')
        if choice is None:
            return
        choice = choice.strip()

        if choice.lower() == 'all' or choice == str(len(msd_keys) + 1):
            selected = msd_keys
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(msd_keys):
                selected = [msd_keys[idx]]
            else:
                print(C.err("  Invalid number."))
                return
        else:
            selected = msd_keys

        for k in selected:
            plot_msd(s.cache[k], k.replace('msd_', ''), s.output_dir, s.dpi,
                        figsize=s.figsize_override)

    def _iplot_performance(self, opts, _batch=False, _edit_mode=False):
        """Interactive performance plot."""
        s = self.state
        if not self._ensure_cache('performance', '_analyze_performance'):
            return
        plot_performance(s.cache['performance'], s.output_dir, s.dpi,
                             figsize=s.figsize_override)

    def _iplot_structure(self, opts, _batch=False, _edit_mode=False):
        """Interactive structure plot — uses data file or last dump frame."""
        s = self.state
        # Prefer _structure_atoms if analyze structure was run; else data_atoms; else last dump
        atoms = getattr(s, '_structure_atoms', None)
        if atoms is None:
            atoms = s.data_atoms if s.data_atoms is not None else np.empty((0, 5))
        if atoms is None or len(atoms) == 0:
            # Try last dump frame
            if s.dump_frames and s.dump_col_idx:
                self._analyze_structure([])
                atoms = getattr(s, '_structure_atoms', np.empty((0, 5)))
        if len(atoms) == 0:
            print(C.warn("  No data file or dump loaded."))
            return

        if _batch:
            zf = s.compute_z_focus()
            plot_structure(atoms, s.atom_types, s.output_dir, s.dpi,
                           z_surface=s.surface_z, z_focus=zf,
                           figsize=s.figsize_override)
            return

        zf = s.compute_z_focus()
        cur_zf = f"{zf[0]:.1f}-{zf[1]:.1f}" if zf else "full range"
        ans = self._ask(f"z-axis focus range in A? (e.g. '0-30', 'full')", cur_zf)
        if ans is not None:
            ans = ans.strip().lower()
            if ans in ('full', 'none', 'all'):
                zf = None
            elif '-' in ans:
                try:
                    lo, hi = ans.split('-', 1)
                    zf = (float(lo), float(hi))
                except ValueError:
                    pass

        plot_structure(atoms, s.atom_types, s.output_dir, s.dpi,
                       z_surface=s.surface_z, z_focus=zf)

    def _iplot_snapshot(self, opts, _batch=False, _edit_mode=False):
        """Interactive snapshot plot — asks frame indices, z_focus, marker size."""
        s = self.state
        if not self._require_dump():
            return

        # Explicit indices from command args
        if opts:
            try:
                indices = [int(x) for x in opts]
            except ValueError:
                print(C.err("  Frame indices must be integers."))
                return
            plot_snapshot(s.dump_frames, s.dump_col_idx, s.atom_types,
                          s.output_dir, indices, s.dpi,
                          z_focus=s.compute_z_focus(), figsize=s.figsize_override)
            return

        if _batch:
            plot_snapshot(s.dump_frames, s.dump_col_idx, s.atom_types,
                          s.output_dir, dpi=s.dpi, z_focus=s.compute_z_focus(),
                          figsize=s.figsize_override)
            return

        n = len(s.dump_frames)
        default_idx = [0, n // 4, n // 2, 3 * n // 4, n - 1]
        default_idx = sorted(set(i for i in default_idx if 0 <= i < n))
        default_str = ' '.join(str(i) for i in default_idx)

        print(f"\n  {C.bold('Snapshot options')}")
        print(f"  Total frames: {n} (indices 0-{n-1})")
        print()

        ans = self._ask(f"Frame indices (space-separated)", default_str)
        if ans is None:
            return
        try:
            indices = [int(x) for x in ans.split()]
            indices = [i for i in indices if 0 <= i < n]
        except ValueError:
            indices = default_idx

        # z_focus
        zf = s.compute_z_focus()
        cur_zf = f"{zf[0]:.1f}-{zf[1]:.1f}" if zf else "full range"
        ans = self._ask(f"z-axis focus range in A? (e.g. '0-30', 'full')", cur_zf)
        if ans is not None:
            ans = ans.strip().lower()
            if ans in ('full', 'none', 'all'):
                zf = None
            elif '-' in ans:
                try:
                    lo, hi = ans.split('-', 1)
                    zf = (float(lo), float(hi))
                except ValueError:
                    pass

        plot_snapshot(s.dump_frames, s.dump_col_idx, s.atom_types,
                      s.output_dir, indices, s.dpi, z_focus=zf,
                      figsize=s.figsize_override)

    def _plot_all(self):
        """Generate all applicable plots using _batch=True (no interactive prompts)."""
        s = self.state
        s.apply_plot_style()
        print(f"\n  {C.bold('Generating all plots...')}")
        if s.normalize:
            progress_msg("Normalize mode: ON (showing ratios/fractions)")
        zf = s.compute_z_focus()
        if zf:
            progress_msg(f"z_focus: [{zf[0]:.1f}, {zf[1]:.1f}] A")
        print()

        # Log-dependent
        self._iplot_thermo([], _batch=True)
        self._iplot_thermostat([], _batch=True)
        self._iplot_pressure([], _batch=True)

        # Cache-dependent: iterate over all cached analysis results
        for key in list(s.cache.keys()):
            if s.cache[key] is None:
                continue
            if key == 'charge':
                self._iplot_charge([], _batch=True)
            elif key == 'charge_z':
                self._iplot_charge_z([], _batch=True)
            elif key == 'oar':
                self._iplot_oar([], _batch=True)
            elif key == 'or':
                self._iplot_or([], _batch=True)
            elif key == 'penetration':
                self._iplot_penetration([], _batch=True)
            elif key == 'penetration_trend':
                self._iplot_penetration_trend([], _batch=True)
            elif key == 'dissociation':
                self._iplot_dissociation([], _batch=True)
            elif key == 'spin':
                self._iplot_spin([], _batch=True)
            elif key == 'performance':
                self._iplot_performance([], _batch=True)

        # Multi-key types: RDF, density, MSD
        self._iplot_rdf([], _batch=True)
        self._iplot_density([], _batch=True)
        self._iplot_msd([], _batch=True)

        # Structure from data file
        self._iplot_structure([], _batch=True)

        # Snapshots
        if s.dump_frames:
            self._iplot_snapshot([], _batch=True)

        print(f"\n  {C.ok('All plots saved to:')} {s.output_dir}/")

    def complete_plot(self, text, line, begidx, endidx):
        plots = ['thermo', 'thermostat', 'charge', 'charge_z', 'rdf', 'oar', 'or',
                 'penetration', 'penetration_trend', 'penetration_profile',
                 'density', 'dissociation', 'spin', 'msd',
                 'performance', 'structure', 'snapshot', 'all']
        return [p for p in plots if p.startswith(text)]

    # ─── EXPORT ───

    def do_export(self, arg):
        """Export data: export csv|latex|summary <analysis> [filename]"""
        parts = shlex.split(arg)
        if len(parts) < 2:
            print("  Usage: export csv|latex|summary <analysis> [filename]")
            return

        fmt = parts[0].lower()
        what = parts[1]  # keep original case for cache key matching
        fname = parts[2] if len(parts) > 2 else None
        s = self.state

        if fmt == 'csv':
            self._export_csv(what, fname)
        elif fmt == 'latex':
            self._export_latex(what, fname)
        elif fmt == 'summary':
            self._export_summary(fname or what)
        else:
            print(f"  Unknown format: {fmt}. Use csv|latex|summary.")

    def _export_csv(self, what, fname):
        s = self.state
        if not HAS_PANDAS:
            print(C.err("  pandas not available. Install with: pip install pandas"))
            return

        # Find data
        data = s.cache.get(what)
        if data is None:
            # Check partial matches
            matches = [k for k in s.cache if k.startswith(what)]
            if matches:
                data = s.cache[matches[0]]
                what = matches[0]
            else:
                print(C.err(f"  No cached data for '{what}'. Run 'analyze {what}' first."))
                return

        os.makedirs(s.output_dir, exist_ok=True)
        if fname is None:
            fname = os.path.join(s.output_dir, f'{what}.csv')

        # Convert to DataFrame
        df_data = {}
        for k, v in data.items():
            if isinstance(v, np.ndarray) and v.ndim == 1:
                df_data[k] = v
        if df_data:
            import pandas as pd
            df = pd.DataFrame(df_data)
            df.to_csv(fname, index=False)
            progress_msg(f"Exported: {C.ok(fname)}")
        else:
            print(C.warn("  No exportable array data found."))

    def _export_latex(self, what, fname):
        s = self.state
        if not HAS_PANDAS:
            print(C.err("  pandas not available. Install with: pip install pandas"))
            return

        data = s.cache.get(what)
        if data is None:
            print(C.err(f"  No cached data for '{what}'."))
            return

        os.makedirs(s.output_dir, exist_ok=True)
        if fname is None:
            fname = os.path.join(s.output_dir, f'{what}.tex')

        df_data = {}
        for k, v in data.items():
            if isinstance(v, np.ndarray) and v.ndim == 1:
                df_data[k] = v
        if df_data:
            import pandas as pd
            df = pd.DataFrame(df_data)
            with open(fname, 'w') as f:
                f.write(df.to_latex(index=False, float_format='%.4f'))
            progress_msg(f"Exported: {C.ok(fname)}")

    def _export_summary(self, fname):
        s = self.state
        os.makedirs(s.output_dir, exist_ok=True)
        if not fname.endswith('.txt'):
            fname = os.path.join(s.output_dir, 'summary.txt')

        lines = []
        lines.append("=" * 60)
        lines.append("LAMMPS-POST Analysis Summary")
        lines.append("=" * 60)
        lines.append(f"Force Field: {s.ff.upper()}")
        lines.append(f"Units: {s.ff_info['unit_system']}")
        lines.append(f"Timestep: {s.dt_fs} fs")

        if s.dump_path:
            lines.append(f"\nDump: {s.dump_path}")
            lines.append(f"  Frames: {len(s.dump_frames)}")
            lines.append(f"  Atoms: {s.dump_frames[0]['natoms']}")

        if s.log_path:
            lines.append(f"\nLog: {s.log_path}")

        lines.append(f"\nCached analyses: {', '.join(s.cache.keys())}")
        lines.append("")

        for key, data in s.cache.items():
            if data is None:
                continue
            lines.append(f"\n--- {key} ---")
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, np.ndarray):
                        lines.append(f"  {k}: min={v.min():.4g}, max={v.max():.4g}, mean={v.mean():.4g}")
                    elif isinstance(v, (int, float)):
                        lines.append(f"  {k}: {v}")
            elif isinstance(data, dict):
                for k, v in data.items():
                    lines.append(f"  {k}: {v}")

        with open(fname, 'w') as f:
            f.write('\n'.join(lines))
        progress_msg(f"Summary exported: {C.ok(fname)}")

    def complete_export(self, text, line, begidx, endidx):
        tokens = line.split()
        if len(tokens) == 2:
            return [t for t in ['csv', 'latex', 'summary'] if t.startswith(text)]
        if len(tokens) == 3:
            return [k for k in self.state.cache if k.startswith(text)]
        return self._complete_path(text)

    # ─── UTILITY ───

    def do_files(self, arg):
        """List files in directory: files [path] [pattern]"""
        parts = shlex.split(arg) if arg else ['.']
        path = parts[0] if parts else '.'
        pattern = parts[1] if len(parts) > 1 else '*'

        if not os.path.isdir(path):
            # Treat as glob pattern
            matches = sorted(globmod.glob(arg or '*'))
        else:
            matches = sorted(globmod.glob(os.path.join(path, pattern)))

        if not matches:
            print("  No files found.")
            return

        for m in matches:
            if os.path.isdir(m):
                print(f"  {C.BLUE}{m}/{C.RESET}")
            else:
                size = os.path.getsize(m)
                if size > 1e9:
                    sz = f"{size/1e9:.1f} GB"
                elif size > 1e6:
                    sz = f"{size/1e6:.1f} MB"
                elif size > 1e3:
                    sz = f"{size/1e3:.1f} KB"
                else:
                    sz = f"{size} B"
                print(f"  {m}  {C.dim(sz)}")

    def do_find(self, arg):
        """
        Search for LAMMPS files recursively.

        Usage:
            find                    — Search for all dump/log/data files from cwd
            find <directory>        — Search in a specific directory
            find dump               — Search for dump/lammpstrj files only
            find log                — Search for log files only
            find data               — Search for data files only
            find <glob_pattern>     — Custom glob pattern (e.g. "*.xyz")
        """
        parts = shlex.split(arg) if arg.strip() else []

        # Predefined patterns for common LAMMPS file types
        presets = {
            'dump':  ['**/*.dump', '**/*.lammpstrj'],
            'log':   ['**/log.*', '**/log.lammps', '**/*.log'],
            'data':  ['**/*.data', '**/data.*'],
        }

        search_dir = '.'
        patterns = []

        for p in parts:
            if p in presets:
                patterns.extend(presets[p])
            elif os.path.isdir(p):
                search_dir = p
            else:
                patterns.append(f'**/{p}' if '/' not in p and '*' not in p else p)

        # Default: search all types
        if not patterns:
            for v in presets.values():
                patterns.extend(v)

        # Collect and deduplicate results
        found = {}
        for pat in patterns:
            for m in globmod.glob(os.path.join(search_dir, pat), recursive=True):
                found[os.path.abspath(m)] = m

        if not found:
            print(C.dim("  No LAMMPS files found."))
            return

        # Group by type
        groups = {'dump': [], 'log': [], 'data': [], 'other': []}
        for abspath, relpath in sorted(found.items()):
            lower = relpath.lower()
            if lower.endswith(('.dump', '.lammpstrj')):
                groups['dump'].append(relpath)
            elif 'log' in os.path.basename(lower):
                groups['log'].append(relpath)
            elif lower.endswith('.data') or os.path.basename(lower).startswith('data.'):
                groups['data'].append(relpath)
            else:
                groups['other'].append(relpath)

        idx = 1
        results = []
        for gname, files in groups.items():
            if not files:
                continue
            label = {'dump': 'Dump/Trajectory', 'log': 'Log',
                     'data': 'Data', 'other': 'Other'}[gname]
            print(f"\n  {C.bold(label)} ({len(files)})")
            for f in sorted(files):
                size = os.path.getsize(f)
                if size > 1e9:
                    sz = f"{size/1e9:.1f} GB"
                elif size > 1e6:
                    sz = f"{size/1e6:.1f} MB"
                elif size > 1e3:
                    sz = f"{size/1e3:.1f} KB"
                else:
                    sz = f"{size} B"
                print(f"    {C.CYAN}{idx:>3}.{C.RESET} {f}  {C.dim(sz)}")
                results.append(f)
                idx += 1

        # ── Check if "load all" is safe ──
        # Count unique parent directories of found files
        parent_dirs = set(os.path.dirname(os.path.abspath(f)) for f in results)
        n_dump = len(groups['dump'])
        n_log = len(groups['log'])
        n_data = len(groups['data'])
        total = len(results) - len(groups['other'])  # exclude 'other'

        can_load_all = (
            total > 0 and total <= 5 and          # not too many files
            n_dump <= 1 and n_log <= 1 and         # at most one of each type
            n_data <= 1 and len(parent_dirs) <= 3   # not scattered across many dirs
        )

        # Offer to load
        print()
        if can_load_all and total > 1:
            load_summary = []
            if n_dump: load_summary.append(f'{n_dump} dump')
            if n_log:  load_summary.append(f'{n_log} log')
            if n_data: load_summary.append(f'{n_data} data')
            print(f"  {C.bold('Quick load:')} 'all' to load {' + '.join(load_summary)}")

        choice = self._ask("Load file(s)? Enter numbers, 'all', or Enter to skip")
        if not choice:
            return

        if choice.strip().lower() == 'all':
            if not can_load_all:
                if total > 5:
                    print(C.warn(f"  Too many files ({total}) to load all at once."))
                elif len(parent_dirs) > 3:
                    print(C.warn(f"  Files spread across {len(parent_dirs)} directories. Select individually."))
                elif n_dump > 1 or n_log > 1:
                    print(C.warn(f"  Multiple dump or log files found. Select individually."))
                print(f"  {C.DIM}Pick specific numbers instead (e.g. '1,3').{C.RESET}")
                return
            # Load all: one of each type (skip 'other')
            for ftype in ['dump', 'log', 'data']:
                if groups[ftype]:
                    self.do_load(sorted(groups[ftype])[0])
            return

        # Parse comma/space-separated numbers
        nums = []
        for token in choice.replace(',', ' ').split():
            token = token.strip()
            if token.isdigit():
                nums.append(int(token))

        for n in nums:
            if 1 <= n <= len(results):
                fpath = results[n - 1]
                self.do_load(fpath)

    def complete_find(self, text, line, begidx, endidx):
        """Tab completion for find — file types and directories."""
        opts = ['dump', 'log', 'data']
        # Also complete directory names
        dirs = [d + '/' for d in globmod.glob(text + '*') if os.path.isdir(d)]
        return [o for o in opts if o.startswith(text)] + dirs

    def do_pwd(self, arg):
        """Print working directory."""
        print(f"  {os.getcwd()}")

    def do_ls(self, arg):
        """List directory contents."""
        self.do_files(arg)

    def do_cd(self, arg):
        """Change directory."""
        path = arg.strip()
        if not path:
            path = os.path.expanduser('~')
        try:
            os.chdir(path)
            print(f"  {os.getcwd()}")
        except FileNotFoundError:
            print(C.err(f"  Directory not found: {path}"))

    def do_clear(self, arg):
        """Clear terminal screen."""
        os.system('clear' if os.name != 'nt' else 'cls')

    def do_quit(self, arg):
        """Exit the tool."""
        print(f"\n  {C.dim('Goodbye!')}\n")
        self._next = 'quit'
        return True

    do_exit = do_quit
    do_q = do_quit

    def do_EOF(self, arg):
        """Handle Ctrl+D."""
        print()
        return self.do_quit(arg)

    # ─── HELP ───

    def do_help(self, arg):
        """Show help for a command or list all commands."""
        if arg:
            super().do_help(arg)
            return

        help_text = f"""
{C.bold('FILE I/O')}
  load dump <path> [--max N] [--stride N]   Load trajectory file
            [--lite] [--all-columns]        float32 columns / keep unused columns
            [--cache-mb N]                  frame cache budget (default 128 MB)
  load log <path>                           Load LAMMPS log file
  load data <path>                          Load LAMMPS data file
  unload dump|log|data                      Unload a file
  info                                      Session summary

{C.bold('INSPECTION')}
  show thermo                               Thermo data statistics
  show columns                              Dump column names
  show types                                Atom type mapping
  show frames                               Frame count & timestep range
  show box                                  Simulation box dimensions
  show composition [frame]                  Atom counts by type
  show stages                               Stage-wise timing

{C.bold('ANALYSIS')} (results are cached)
  analyze charge                            Fe charge evolution (ReaxFF)
  analyze charge_z [frame]                  z-direction charge dist (ReaxFF)
  analyze rdf [pair] [--frames N]           RDF (default: Fe-O)
  analyze oar                               Oxygen Absorption Rate
  analyze or                                Oxidation Rate (ReaxFF)
  analyze penetration                       O penetration depth
  analyze density [--species X]             Density profile rho(z)
  analyze dissociation                      O2 dissociation tracking
  analyze spin                              Spin evolution (ACE)
  analyze msd [--species X]                 Mean Square Displacement
  analyze performance                       Stage wall time
  analyze structure                         Final structure z-profile
  analyze all                               Run all applicable

{C.bold('PLOTTING')}
  plot <analysis_name>                      Generate plot from cached data
  plot snapshot [frame_indices]              z-x plane snapshots
  plot all                                  All plots from cached data

{C.bold('EXPORT')}
  export csv <analysis> [filename]          Export to CSV
  export latex <analysis> [filename]        Export to LaTeX table
  export summary [filename]                 Export text summary

{C.bold('SETTINGS')}
  set output <dir>                          Output directory
  set surface_z <float>                     Fe surface z coordinate (A)
  set dt <float>                            Override timestep (fs)
  set forcefield reaxff|ace|hdnnp           Override force field
  set types 1=Fe 2=O ...                    Override type mapping
  set dpi <int>                             Plot resolution
  set normalize on|off                      Show ratios instead of raw counts
  set z_focus auto|off|<zlo> <zhi>          Focus z-range for plots
  set linewidth <float>                     Plot line width (default: 1.5)
  set markersize <float>                    Scatter marker size (default: 3)
  set fontsize <int>                        Plot font size (default: 11)
  set grid on|off                           Toggle grid lines
  set grid_alpha <float>                    Grid transparency 0-1
  set figsize <W> <H> | single_col | double_col | 1.5col  Figure size
  set theme default|publication|presentation  Plot theme preset
  set save_format png|pdf|svg|both           Output file format
  set pressure_unit bar|gpa                  Pressure display unit
  set mass <float>                           Total system mass (amu)

{C.bold('UTILITY')}
  find [dump|log|data] [dir]                Search for LAMMPS files recursively
  files [path] [pattern]                    List files
  pwd / ls / cd                             Navigation
  clear                                     Clear screen
  quit / exit / q                           Exit
"""
        print(help_text + self._hosted_help())

    # ─── Path completion helper ───

    def _complete_path(self, text):
        """Complete file/directory paths for tab completion."""
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

    def default(self, line):
        """Handle unknown commands."""
        print(f"  Unknown command: '{line}'. Type 'help' for available commands.")

    def emptyline(self):
        """Do nothing on empty input."""
        pass


