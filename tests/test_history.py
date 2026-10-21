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
    if readline is None:
        skip('readline not available')


def _fill(path, n=N):
    with open(path, 'w') as f:
        for i in range(n):
            f.write(f'cmd {i}\n')


def _lines(path):
    with open(path) as f:
        return f.read().splitlines()


class _patched_home:
    """Point HOME (and optionally LKPR_NO_HISTORY) at a temp dir."""

    def __init__(self, no_history=False):
        self.tmp = tempfile.mkdtemp(prefix='lkpr_hist_')
        self.no_history = no_history

    def __enter__(self):
        self._saved = {k: os.environ.get(k) for k in ('HOME', 'LKPR_NO_HISTORY')}
        os.environ['HOME'] = self.tmp
        if self.no_history:
            os.environ['LKPR_NO_HISTORY'] = '1'
        else:
            os.environ.pop('LKPR_NO_HISTORY', None)
        return self.tmp

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_pre_shell_history_is_trimmed_to_limit():
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
