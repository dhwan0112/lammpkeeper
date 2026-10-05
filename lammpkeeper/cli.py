"""
Top-level entry point for the `lkpr` command (LammpKeeper).

Stage 1 design: a thin dispatcher. `lkpr prep ...` and `lkpr post ...` forward
their remaining arguments verbatim to the existing `lammps_pre.cli.main` and
`lammps_post.cli.main`, which keep their own argparse definitions and behavior.
This preserves every existing flag, help text, and numeric output; the only
change to those packages is that each sub-`main()` now accepts an optional
`argv` list (defaulting to None -> sys.argv, i.e. unchanged when called bare).

`lkpr` with no arguments (in a terminal) or `lkpr shell` opens the unified
interactive session (lammpkeeper.shell), where prep and post are chosen and
switched from one prompt.

Backwards-compatible entry points remain fully functional and are untouched:
    python -m lammps_pre ...    /  python lammps-pre.py ...
    python -m lammps_post ...   /  python lammps-post.py ...
"""

import argparse
import sys

from lammpkeeper import VERSION


def _build_parser():
    """Parser used only for `lkpr -h`, `lkpr --version`, and error messages.

    Subcommand arguments are intentionally NOT declared here: they are owned by
    each subcommand's own parser and forwarded untouched by main(). The two
    sub-parsers below exist solely so that `lkpr -h` lists the commands.
    """
    parser = argparse.ArgumentParser(
       prog='lkpr',
       description='LammpKeeper — unified LAMMPS pre/post-processing '
                   'for iron-redox MLFF studies.',
       epilog="Run 'lkpr prep -h' or 'lkpr post -h' for subcommand options.",
    )
    parser.add_argument('--version', action='version', version=f'lkpr {VERSION}')
    sub = parser.add_subparsers(dest='command', metavar='<command>')
    sub.add_parser('prep', add_help=False,
                   help='pre-processing: build structures & LAMMPS inputs '
                        '(delegates to lammps-pre)')
    sub.add_parser('post', add_help=False,
                   help='post-processing: analyze & plot trajectories '
                        '(delegates to lammps-post)')
    sub.add_parser('shell', add_help=False,
                   help='interactive session: choose prep or post, switch '
                        'between them (default when run in a terminal)')
    return parser


def main(argv=None):
    """Dispatch to the prep/post sub-CLIs, forwarding remaining args verbatim."""
    argv = list(sys.argv[1:]) if argv is None else list(argv)

    # No subcommand: interactive session in a terminal, help otherwise (exit 0).
    if not argv:
        if sys.stdin.isatty() and sys.stdout.isatty():
            argv = ['shell']
        else:
            _build_parser().print_help()
            return 0

    command, rest = argv[0], argv[1:]

    if command == 'shell':
        from lammpkeeper.shell import main as shell_main
        return shell_main()

    if command == 'prep':
        from lammps_pre.cli import main as prep_main
        return prep_main(rest)

    if command == 'post':
        from lammps_post.cli import main as post_main
        return post_main(rest)

        # Top-level --version / -h / --help, or an unknown command: hand back to
        # argparse for standard usage formatting and exit codes (invalid choice -> 2).
    return _build_parser().parse_args(argv)


if __name__ == '__main__':
    sys.exit(main())
