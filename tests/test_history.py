"""OPS-1: readline history files are bounded and can be disabled.

Repro: a 5,000-line history file used to be written back in full, so
~/.lkpr_history, ~/.lammps-pre_history and ~/.lammps-post_history grew
without bound. After the fix, saving keeps at most 2,000 lines (the most
recent), and LKPR_NO_HISTORY=1 reads and writes nothing.
"""
import os
import tempfile

import _util  # noqa: F401  (path bootstrap)
from _util import skip

try:
    import readline
except ImportError:
    readline = None

LIMIT = 2000
N = 5000


def _require_readline():
    """Report unavailable history support as a skip, never as a passing no-op."""
    if readline is None:
        skip('readline not available')


def _fill(path, n=N):
    """Write ordered commands so truncation can be checked against the newest one."""
    with open(path, 'w') as f:
        for i in range(n):
            f.write(f'cmd {i}\n')


def _lines(path):
    """Read persisted commands without newline differences obscuring duplication."""
    with open(path) as f:
        return f.read().splitlines()


class _patched_home:
    """Point HOME (and optionally LKPR_NO_HISTORY) at a temp dir."""

    def __init__(self, no_history=False):
        """Allocate an isolated home and remember the requested history policy."""
        self.tmp = tempfile.mkdtemp(prefix='lkpr_hist_')
        self.no_history = no_history

    def __enter__(self):
        """Save environment values before redirecting all home-based history writes."""
        self._saved = {k: os.environ.get(k) for k in ('HOME', 'LKPR_NO_HISTORY')}
        os.environ['HOME'] = self.tmp
        if self.no_history:
            os.environ['LKPR_NO_HISTORY'] = '1'
        else:
            os.environ.pop('LKPR_NO_HISTORY', None)
        return self.tmp

    def __exit__(self, *exc):
        """Restore both absent and set environment values even after assertion failure."""
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_standalone_shell_history_does_not_accumulate_on_reload():
    """Repeated initialization must not append duplicate in-memory history entries."""
    _require_readline()
    from lammpkeeper.common.hosted import HostedShellMixin

    class Shell(HostedShellMixin):
        """Expose the history mixin without unrelated interactive shell behavior."""
        pass

    with _patched_home() as home:
        path = os.path.join(home, '.test_history')
        _fill(path, n=3)
        saved = [readline.get_history_item(i + 1)
                 # Readline is process-global; restore prior entries after the test.
                 for i in range(readline.get_current_history_length())]
        try:
            for _ in range(3):
                sh = Shell()
                sh._setup_history(path)
                assert readline.get_current_history_length() == 3
                sh._save_history_if_standalone()
                assert _lines(path) == ['cmd 0', 'cmd 1', 'cmd 2']
        finally:
            readline.clear_history()
            for line in saved:
                readline.add_history(line)


def test_pre_shell_history_is_trimmed_to_limit():
    """Preprocessing history stays bounded while retaining the newest command."""
    _require_readline()
    with _patched_home() as home:
        path = os.path.join(home, '.lammps-pre_history')
        _fill(path)
        from lammps_pre.shell import LammpsPreShell
        sh = LammpsPreShell()
        sh._save_history_if_standalone()
        lines = _lines(path)
        assert len(lines) <= LIMIT, f'{len(lines)} lines kept, limit is {LIMIT}'
        assert lines[-1] == f'cmd {N - 1}'


def test_lkpr_shell_history_is_trimmed_to_limit():
    """Unified-shell persistence applies the same bound and newest-command policy."""
    _require_readline()
    with _patched_home() as home:
        path = os.path.join(home, '.lkpr_history')
        _fill(path)
        import lammpkeeper.shell as lk
        saved = lk._HISTFILE
        lk._HISTFILE = path
        try:
            sh = lk.LkprShell()
            sh._save_history(path)
        finally:
            lk._HISTFILE = saved
        lines = _lines(path)
        assert len(lines) <= LIMIT, f'{len(lines)} lines kept, limit is {LIMIT}'
        assert lines[-1] == f'cmd {N - 1}'


def test_no_history_env_leaves_home_untouched():
    """The opt-out must prevent both shell families from creating history files."""
    _require_readline()
    with _patched_home(no_history=True) as home:
        from lammps_pre.shell import LammpsPreShell
        sh = LammpsPreShell()
        sh._save_history_if_standalone()
        import lammpkeeper.shell as lk
        saved = lk._HISTFILE
        lk._HISTFILE = os.path.join(home, '.lkpr_history')
        try:
            lksh = lk.LkprShell()
            lksh._save_history(lk._HISTFILE)
        finally:
            lk._HISTFILE = saved
        assert os.listdir(home) == [], f'history written despite LKPR_NO_HISTORY: {os.listdir(home)}'


def _buffer():
    """Return the process-global readline buffer as a list, oldest first."""
    return [readline.get_history_item(i + 1)
            for i in range(readline.get_current_history_length())]


class _menu_session:
    """Build an LkprShell on an isolated HOME whose menu buffer has unsaved input.

    Yields (lk_module, shell, menu_file, home). The menu file holds only
    'menu_old'; 'menu_unsaved' exists in memory alone, as after typing it at the
    prompt. The prior process-global readline buffer is restored on exit.
    """

    def __enter__(self):
        """Create the isolated home, post history file and unsaved menu buffer."""
        import lammpkeeper.shell as lk
        self.home_ctx = _patched_home()
        home = self.home_ctx.__enter__()
        self.lk = lk
        self.saved_hist = _buffer()
        self.saved_file = lk._HISTFILE
        self.menu_file = os.path.join(home, '.lkpr_history')
        lk._HISTFILE = self.menu_file
        with open(self.menu_file, 'w') as f:
            f.write('menu_old\n')
        with open(os.path.join(home, '.lammps-post_history'), 'w') as f:
            f.write('post_a\npost_b\n')
        self.sh = lk.LkprShell()
        readline.add_history('menu_unsaved')
        return self.lk, self.sh, self.menu_file, home

    def __exit__(self, *exc):
        """Restore module globals, readline buffer and environment."""
        self.lk._HISTFILE = self.saved_file
        readline.clear_history()
        for line in self.saved_hist:
            readline.add_history(line)
        self.home_ctx.__exit__(*exc)


def test_inline_hosted_command_keeps_menu_history():
    """REV-OPS-1: `post info` must not replace the menu buffer with post history."""
    _require_readline()
    with _menu_session() as (lk, sh, menu_file, home):
        assert _buffer() == ['menu_old', 'menu_unsaved']
        assert sh._enter('post', 'info') is False
        assert _buffer() == ['menu_old', 'menu_unsaved'], _buffer()
        sh.postloop()
        assert _lines(menu_file) == ['menu_old', 'menu_unsaved'], _lines(menu_file)


def test_inline_hosted_command_restores_menu_history_when_child_raises():
    """REV-OPS-1: a failing inline child must still leave the menu buffer intact."""
    _require_readline()
    with _menu_session() as (lk, sh, menu_file, home):
        child = sh._shell('post')
        # Constructing the child swapped the buffer; re-establish the menu state.
        readline.clear_history()
        readline.add_history('menu_old')
        readline.add_history('menu_unsaved')

        def boom(line):
            """Simulate a child command that crashes after history was swapped."""
            readline.add_history('child_cmd')
            raise RuntimeError('boom')

        child.onecmd = boom
        try:
            sh._enter('post', 'info')
        except RuntimeError:
            pass
        else:
            raise AssertionError('child exception was swallowed')
        assert _buffer() == ['menu_old', 'menu_unsaved'], _buffer()
        sh.postloop()
        assert _lines(menu_file) == ['menu_old', 'menu_unsaved'], _lines(menu_file)
