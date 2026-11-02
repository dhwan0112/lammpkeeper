"""
═══════════════════════════════════════════════════════════════
Section 7: Entry Point
═══════════════════════════════════════════════════════════════
Handles command-line argument parsing and launches either:
  - Interactive mode (default): enters the cmd.Cmd event loop
  - Batch mode (--batch): reads commands from a script file
  - One-shot mode (--analyze/--plot): run without entering interactive shell

Files can be pre-loaded via --input, --dump, --log, --data flags to skip
the manual 'load' step. Example:
  python -m lammps_post --dump traj.lammpstrj --log log.lammps
  python -m lammps_post --log log.lammps --plot thermo --theme publication
═══════════════════════════════════════════════════════════════
"""

import argparse
import shlex

from lammps_post import VERSION
from lammps_post.display import C


def main(argv=None):
    """
    Main entry point: parse CLI arguments and start the interactive shell.

    Supports four modes of operation:
    1. Interactive (default): Launches the cmd.Cmd shell with a prompt.
       User types commands interactively with tab completion and history.
    2. Pre-loaded: Use --input/--dump/--log/--data flags to automatically load
       files before entering the interactive prompt.
    3. Batch: Use --batch <file> to execute a series of commands from
       a script file (one command per line, '#' for comments).
    4. One-shot: Use --analyze and/or --plot with file flags to run
        analysis/plotting without entering the interactive shell.

    ``argv=None`` reads process arguments; success returns None. Preload,
    one-shot and batch command failures raise SystemExit(1). The shell counts
    failures independently of cmd.Cmd's truthy stop signal, allowing batch
    scripts to continue after recoverable errors and still exit unsuccessfully.
    """
    parser = argparse.ArgumentParser(
        description='LAMMPS-POST: Post-Processing Interactive CLI')

    # ── File loading ──
    parser.add_argument('--dump', help='Pre-load a dump/trajectory file (.dump or .lammpstrj)')
    parser.add_argument('--log', help='Pre-load a LAMMPS log file')
    parser.add_argument('--data', help='Pre-load a LAMMPS data file (final structure)')
    parser.add_argument('--input', help='Pre-load a LAMMPS input script for explicit run metadata '
                        '(pair_style, units, timestep, boundary); loaded before the other files')
    parser.add_argument('--output', default='./lammps-post_output',
                        help='Output directory for plots and exports (default: ./lammps-post_output)')
    parser.add_argument('--max-frames', type=int, default=None,
                        help='Maximum number of frames to load from dump file')

    # ── One-shot commands (no interactive shell) ──
    parser.add_argument('--analyze', nargs='?', const='all', default=None,
                        help='Run analysis without entering shell (default: all)')
    parser.add_argument('--plot', nargs='?', const='all', default=None,
                        help='Generate plots without entering shell (default: all)')
    parser.add_argument('--find', nargs='?', const='.', default=None,
                        help='Search for LAMMPS files (default: current directory)')

    # ── Style flags ──
    parser.add_argument('--theme', choices=['default', 'publication', 'presentation'],
                        default=None, help='Plot theme preset')
    parser.add_argument('--format', choices=['png', 'pdf', 'svg', 'both'],
                        default=None, dest='save_format', help='Output file format')
    parser.add_argument('--dpi', type=int, default=None, help='Plot resolution (DPI)')

    # ── Batch and meta ──
    parser.add_argument('--batch', help='Execute commands from a script file (non-interactive)')
    parser.add_argument('--version', action='version', version=f'lammps-post {VERSION}')

    args = parser.parse_args(argv)

    if args.batch is not None and (args.analyze is not None or args.plot is not None):
        # One-shot mode would silently skip the script; ambiguous ordering, so refuse.
        parser.error('--batch cannot be combined with --analyze or --plot')

    # Lazy import: only load the heavy shell module when needed
    from lammps_post.shell import LammpsPostShell

    # Create the interactive shell instance
    shell = LammpsPostShell()
    shell.state.output_dir = args.output
    one_shot = args.analyze is not None or args.plot is not None
    # Missing values may use documented defaults in these modes, but must not
    # block on stdin. The shell also treats non-TTY input as noninteractive.
    shell.noninteractive = one_shot or args.batch is not None or args.find is not None

    # Apply style flags before any plotting
    # Routed through onecmd so a bad value is counted and reported, not a traceback.
    if args.theme:
        shell.onecmd(f'set theme {args.theme}')
    if args.save_format:
        shell.onecmd(f'set save_format {args.save_format}')
    if args.dpi is not None:
        # `is not None`: --dpi 0 must reach validation instead of being ignored.
        shell.onecmd(f'set dpi {args.dpi}')
    if shell.command_failures:
        raise SystemExit(1)

    # ── File search mode ──
    if args.find is not None:
        # Search takes precedence over preload/analysis/batch. Through onecmd
        # so failures count; an empty result is a failure for this request.
        shell.require_find_match = True
        shell.onecmd(f'find {shlex.quote(args.find)}')
        if shell.command_failures:
            raise SystemExit(1)
        return

    # ── Pre-load files if specified ──
    max_arg = f' --max {args.max_frames}' if args.max_frames is not None else ''
    # The shell tokenizes command strings again: preserve each filename as one
    # token, including spaces and quotes, rather than interpolating raw paths.
    # The input goes first so explicit metadata is in place when the trajectory
    # loads; the result is identical for the opposite order.
    if args.input:
        shell.onecmd(f'load input {shlex.quote(args.input)}')
    if args.dump:
        shell.onecmd(f'load dump {shlex.quote(args.dump)}{max_arg}')
    if args.log:
        shell.onecmd(f'load log {shlex.quote(args.log)}')
    if args.data:
        shell.onecmd(f'load data {shlex.quote(args.data)}')

    if shell.command_failures:
        # Failed preloads must not start analyses against a partial session.
        raise SystemExit(1)

    # ── One-shot mode: analyze and/or plot, then exit ──
    if args.analyze is not None:
        # A plot may still run after an analysis error; cumulative status below
        # ensures that a later success cannot conceal the earlier failure.
        shell.onecmd(f'analyze {args.analyze}')
    if args.plot is not None:
        shell.onecmd(f'plot {args.plot}')

    if one_shot:
        if shell.command_failures:
            raise SystemExit(1)
        return  # Exit without entering interactive shell

    # ── Batch mode ──
    if args.batch:
        try:
            with open(args.batch) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        print(f"{shell.prompt}{line}")
                        if shell.onecmd(line):
                            # Only an explicit stop command ends the batch;
                            # recoverable failures return False and are counted.
                            break
        except OSError as exc:
            # Opening/reading the script is owned here, not by shell.onecmd.
            print(C.err(f'  {exc}'))
            raise SystemExit(1) from exc
        if shell.command_failures:
            raise SystemExit(1)
        return

    # ── Interactive mode ──
    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        # Interactive interruption is a normal departure, not a batch failure.
        print(f"\n\n  {C.dim('Interrupted. Goodbye!')}\n")


if __name__ == '__main__':
    main()
