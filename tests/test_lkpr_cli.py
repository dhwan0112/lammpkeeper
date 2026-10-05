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


def test_unified_session_switches_and_keeps_state():
    import os
    import tempfile
    import lammpkeeper.shell as lk
    tmp = tempfile.mkdtemp(prefix='lkpr_hist_')
    saved = lk._HISTFILE
    lk._HISTFILE = os.path.join(tmp, 'lkpr')
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            sh = lk.LkprShell()
            pre, post = sh._shell('prep'), sh._shell('post')
            pre.histfile = os.path.join(tmp, 'pre')
            post.histfile = os.path.join(tmp, 'post')
            pre.cmdqueue = ['set temperature 500', 'post', 'back']
            post.cmdqueue = ['set dpi 300', 'prep']
            assert sh._run('prep') is False          # back -> menu
            assert pre.state.temperature == 500 and post.state.dpi == 300
            assert sh._shell('post') is post          # same instance, state kept
            sh.onecmd('post set dpi 200')            # one-shot command from the menu
            assert post.state.dpi == 200
            post.cmdqueue = ['prep']
            pre.cmdqueue = ['quit']
            assert sh.onecmd('post') is True          # quit inside a shell ends lkpr
        text = out.getvalue()
        assert 'LAMMPS-PRE' in text and 'LAMMPS-POST' in text
    finally:
        lk._HISTFILE = saved


def test_switch_commands_need_unified_session():
    from lammps_pre.shell import LammpsPreShell
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert not LammpsPreShell().onecmd('post')
    assert 'lkpr' in out.getvalue()
