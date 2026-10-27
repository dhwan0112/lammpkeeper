"""
Entry point for lammps-pre.

Supports four modes:
  1. Interactive (default): cmd.Cmd shell with tab completion
  2. One-shot: --build/--write/--preview flags
  3. Batch: --batch <script> executes commands from file
  4. Pre-configured: --ff/--temp/--o2 etc. set state before shell
"""

import argparse
import shlex

from lammps_pre import VERSION
from lammps_pre.display import C


def main(argv=None):
    """Apply CLI settings, then choose matrix, one-shot, batch, or shell mode.

    Matrix takes precedence over one-shot actions, which precede batch input.
    Commands share shell validation; failures raise SystemExit(1), including
    through legacy launchers that ignore return values. Paths and compound
    boundary values are shell-quoted before passing through shlex again.
    Batch quit/EOF stops command consumption rather than executing later lines.
    """
    parser = argparse.ArgumentParser(
        description='LAMMPS-PRE: Pre-Processing Interactive CLI')

    # ── Quick setup flags ──
    parser.add_argument('--ff', choices=['ace', 'reaxff2010', 'reaxff2015'],
                        help='Force field selection')
    parser.add_argument('--temp', type=int, help='Temperature (K)')
    parser.add_argument('--o2', type=int, help='Number of O2 molecules')
    parser.add_argument('--slab', help='Supercell size (e.g., 10x10x20)')
    parser.add_argument('--surface', choices=['100', '110', '111'],
                        help='Miller index')
    parser.add_argument('--boundary', help='Boundary conditions (e.g., "p p f")')
    parser.add_argument('--seed', type=int, help='Structure generation seed')

    # ── Action flags ──
    parser.add_argument('--build', action='store_true',
                        help='Build structure from settings')
    parser.add_argument('--write', nargs='?', const='.', default=None,
                        help='Write output files to directory')
    parser.add_argument('--preview', action='store_true',
                        help='Show configuration summary')

    # ── Batch & Matrix ──
    parser.add_argument('--batch', help='Execute commands from script file')
    parser.add_argument('--matrix', help='Generate temp/O2 matrix '
                        '(e.g., "temps=300,500,800 o2=40,100,200")')

    # ── Meta ──
    parser.add_argument('--version', action='version',
                        version=f'lammps-pre {VERSION}')

    args = parser.parse_args(argv)

    # Lazy import
    from lammps_pre.shell import LammpsPreShell

    shell = LammpsPreShell()
    shell.noninteractive = bool(args.batch or args.matrix or args.build or
                                args.write is not None or args.preview)

    def run(command):
        """Execute one shell command, preserving stop signals and failing fast.

        A truthy result means quit, not failure; the separate failure flag is
        what makes malformed setup and generation fail noninteractive callers.
        """
        stop = shell.onecmd(command)
        if shell.last_command_failed:
            # Legacy entrypoints call main() without sys.exit(main()), so errors
            # must raise rather than merely return an ignored numeric status.
            raise SystemExit(1)
        return stop

    # ── Apply quick setup flags ──
    if args.ff:
        run(f'set ff {args.ff}')
    if args.temp is not None:
        run(f'set temperature {args.temp}')
    if args.o2 is not None:
        run(f'set o2 {args.o2}')
    if args.slab:
        run(f'set slab {shlex.quote(args.slab)}')
    if args.surface:
        run(f'set surface {args.surface}')
    if args.boundary:
        run(f'set boundary {shlex.quote(args.boundary)}')
    if args.seed is not None:
        run(f'set seed {args.seed}')

    # ── Matrix mode ──
    if args.matrix:
        # Parse: "temps=300,500,800 o2=40,100,200"
        matrix_args = args.matrix
        if args.write is not None:
            matrix_args += f' output={shlex.quote(args.write)}'
        run(f'matrix {matrix_args}')
        return

    # ── One-shot mode ──
    one_shot = args.build or args.write is not None or args.preview

    if args.build or args.write is not None:
        run('build')

    if args.write is not None:
        run(f'set output {shlex.quote(args.write)}')
        run('write all')

    if args.preview:
        run('show')

    if one_shot:
        return

    # ── Batch mode ──
    if args.batch:
        try:
            with open(args.batch) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        print(f"{shell.prompt}{line}")
                        if run(line):
                            break
        except OSError as exc:
            print(C.err(f'  Error: {exc}'))
            raise SystemExit(1) from exc
        return

    # ── Interactive mode ──
    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        print(f"\n\n  {C.dim('Interrupted. Goodbye!')}\n")


if __name__ == '__main__':
    main()
