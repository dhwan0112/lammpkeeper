"""
Entry point for lammps-pre.

Supports four modes:
  1. Interactive (default): cmd.Cmd shell with tab completion
  2. One-shot: --build/--write/--preview flags
  3. Batch: --batch <script> executes commands from file
  4. Pre-configured: --ff/--temp/--o2 etc. set state before shell
"""

import argparse

from lammps_pre import VERSION
from lammps_pre.display import C


def main():
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

    args = parser.parse_args()

    # Lazy import
    from lammps_pre.shell import LammpsPreShell

    shell = LammpsPreShell()
    s = shell.state

    # ── Apply quick setup flags ──
    if args.ff:
        shell.do_set(f'ff {args.ff}')
    if args.temp:
        shell.do_set(f'temperature {args.temp}')
    if args.o2 is not None:
        shell.do_set(f'o2 {args.o2}')
    if args.slab:
        shell.do_set(f'slab {args.slab.replace("x", " ")}')
    if args.surface:
        shell.do_set(f'surface {args.surface}')
    if args.boundary:
        shell.do_set(f'boundary {args.boundary}')
    if args.seed:
        shell.do_set(f'seed {args.seed}')

    # ── Matrix mode ──
    if args.matrix:
        # Parse: "temps=300,500,800 o2=40,100,200"
        matrix_args = args.matrix
        if args.write is not None:
            matrix_args += f' output={args.write}'
        shell.do_matrix(matrix_args)
        return

    # ── One-shot mode ──
    one_shot = args.build or args.write is not None or args.preview

    if args.build or args.write is not None:
        shell.do_build('')

    if args.write is not None:
        shell.do_set(f'output {args.write}')
        shell.do_write('all')

    if args.preview:
        shell.do_show('')

    if one_shot:
        return

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
