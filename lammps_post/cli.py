"""
═══════════════════════════════════════════════════════════════
Section 7: Entry Point
═══════════════════════════════════════════════════════════════
Handles command-line argument parsing and launches either:
  - Interactive mode (default): enters the cmd.Cmd event loop
  - Batch mode (--batch): reads commands from a script file
  - One-shot mode (--analyze/--plot): run without entering interactive shell

Files can be pre-loaded via --dump, --log, --data flags to skip
the manual 'load' step. Example:
  python -m lammps_post --dump traj.lammpstrj --log log.lammps
  python -m lammps_post --log log.lammps --plot thermo --theme publication
═══════════════════════════════════════════════════════════════
"""

import argparse

from lammps_post import VERSION
from lammps_post.display import C


def main(argv=None):
    """
    Main entry point: parse CLI arguments and start the interactive shell.

    Supports four modes of operation:
    1. Interactive (default): Launches the cmd.Cmd shell with a prompt.
       User types commands interactively with tab completion and history.
    2. Pre-loaded: Use --dump/--log/--data flags to automatically load
       files before entering the interactive prompt.
    3. Batch: Use --batch <file> to execute a series of commands from
       a script file (one command per line, '#' for comments).
    4. One-shot: Use --analyze and/or --plot with file flags to run
       analysis/plotting without entering the interactive shell.
    """
    parser = argparse.ArgumentParser(
        description='LAMMPS-POST: Post-Processing Interactive CLI')

    # ── File loading ──
    parser.add_argument('--dump', help='Pre-load a dump/trajectory file (.dump or .lammpstrj)')
    parser.add_argument('--log', help='Pre-load a LAMMPS log file')
    parser.add_argument('--data', help='Pre-load a LAMMPS data file (final structure)')
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

    # Lazy import: only load the heavy shell module when needed
    from lammps_post.shell import LammpsPostShell

    # Create the interactive shell instance
    shell = LammpsPostShell()
    shell.state.output_dir = args.output

    # Apply style flags before any plotting
    if args.theme:
        shell.do_set(f'theme {args.theme}')
    if args.save_format:
        shell.do_set(f'save_format {args.save_format}')
    if args.dpi:
        shell.do_set(f'dpi {args.dpi}')

    # ── File search mode ──
    if args.find is not None:
        shell.do_find(args.find)
        return

    # ── Pre-load files if specified ──
    max_arg = f' --max {args.max_frames}' if args.max_frames else ''
    if args.dump:
        shell.do_load(f'dump {args.dump}{max_arg}')
    if args.log:
        shell.do_load(f'log {args.log}')
    if args.data:
        shell.do_load(f'data {args.data}')

    # ── One-shot mode: analyze and/or plot, then exit ──
    one_shot = args.analyze is not None or args.plot is not None

    if args.analyze is not None:
        shell.do_analyze(args.analyze)
    if args.plot is not None:
        shell.do_plot(args.plot)

    if one_shot:
        return  # Exit without entering interactive shell

    # ── Batch mode ──
    if args.batch:
        with open(args.batch) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    print(f"{shell.prompt}{line}")
                    shell.onecmd(line)
        return

    # ── Interactive mode ──
    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        print(f"\n\n  {C.dim('Interrupted. Goodbye!')}\n")


if __name__ == '__main__':
    main()
