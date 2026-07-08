"""Stage 1 dispatcher: top-level lkpr routing + verbatim delegation to sub-CLIs."""
import io
import contextlib

import _util  # noqa: F401  (path bootstrap)

from lammpkeeper.cli import main
from lammpkeeper import VERSION


def _run(argv):
   """Run lkpr main(argv); return (exit_code, stdout, stderr).

   argparse actions (-h/--version, invalid choice) raise SystemExit; capture it.
   """
   out, err = io.StringIO(), io.StringIO()
   with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
      try:
         code = main(argv)
      except SystemExit as e:
         code = e.code
   return code, out.getvalue(), err.getvalue()


def test_no_args_prints_help():
   code, out, _ = _run([])
   assert code == 0
   assert 'lkpr' in out and 'prep' in out and 'post' in out


def test_top_version():
   code, out, _ = _run(['--version'])
   assert code == 0
   assert f'lkpr {VERSION}' in out


def test_unknown_command_exit_2():
   code, _, _ = _run(['bogus'])
   assert code == 2


def test_prep_delegation_preserves_subversion():
   code, out, _ = _run(['prep', '--version'])
   assert code == 0
   assert 'lammps-pre' in out


def test_post_delegation_preserves_subversion():
   code, out, _ = _run(['post', '--version'])
   assert code == 0
   assert 'lammps-post' in out
