"""
Commands shared by the prep and post shells for running inside the unified
`lkpr` interactive session (lammpkeeper.shell.LkprShell).

When a shell is hosted, `back` returns to the lkpr menu, `prep` / `post`
switch to the other shell (each keeps its state), and `quit` ends the whole
session. Run standalone (`lkpr prep`, `python -m lammps_post`), the switch
commands only explain that they need the unified session.
"""

import os

from lammpkeeper.common.display import C

try:
    import readline
except ImportError:
    readline = None

# Maximum history lines kept per shell (OPS-1). Without a cap the history
# files grow without bound — they reached tens of millions of lines.
HISTORY_LENGTH = 2000


def history_enabled():
    """False when LKPR_NO_HISTORY=1: no history is read or written."""
    return os.environ.get('LKPR_NO_HISTORY') != '1'


class HostedShellMixin:
    """Share navigation/history policy without owning either shell's data.

    A hosted command exits the child cmdloop via its boolean return, leaving a
    target in ``_next`` for the outer session. Standalone shells have no host to
    consume that target, so navigation is informational rather than destructive.
    """
    shell_name = None       # 'prep' or 'post'
    histfile = None         # readline history file of this shell
    _host = None            # LkprShell when hosted
    _next = None            # what the host should do after cmdloop returns

    def _setup_history(self, histfile):
        """Replace the process-global history; standalone shells save it at exit.

        The configured length bounds file writes, not the number of entries read
        into memory. A host takes over buffer swapping after setting ``_host``.
        """
        self.histfile = os.path.expanduser(histfile)
        if readline is None or not history_enabled():
            return
        readline.set_completer_delims(' \t\n')
        readline.set_history_length(HISTORY_LENGTH)
        # Start from this file alone, as lkpr's _load_history does. Without the
        # clear, every shell created in one process (the test suite makes many)
        # re-appends the file to the shared readline history, and the exit
        # handler writes the sum back, so the file multiplies on every run.
        readline.clear_history()
        try:
            readline.read_history_file(self.histfile)
        except (FileNotFoundError, OSError):
            pass
        import atexit
        atexit.register(self._save_history_if_standalone)

    def _save_history_if_standalone(self):
        """Persist the current buffer for a standalone shell, honoring opt-out.

        Hosted sessions swap the process-global readline buffer themselves;
        writing it from an atexit child callback would mix the shells' commands.
        Multiple standalone instances do not have independent in-memory buffers.
        """
        # Hosted shells share readline with lkpr, which swaps history per shell.
        if self._host is None and readline is not None and history_enabled():
            try:
                readline.set_history_length(HISTORY_LENGTH)
                readline.write_history_file(self.histfile)
            except OSError:
                pass

    def _leave(self, target):
        """Request host navigation without clearing the current shell's state.

        True is cmd.Cmd's stop signal, not an analysis success/error code.
        Unsupported standalone switches and self-switches leave cmdloop running.
        """
        if self._host is None:
            print(f"  '{target}' works inside the unified session; start it with 'lkpr'.")
            return False
        if target == self.shell_name:
            print(f"  Already in {self.shell_name}.")
            return False
        self._next = target
        return True

    def do_back(self, arg):
        """Return to the lkpr menu (unified session only)."""
        return self._leave('menu')

    def do_prep(self, arg):
        """Switch to pre-processing; settings here are kept (unified session only)."""
        return self._leave('prep')

    def do_post(self, arg):
        """Switch to post-processing; loaded files are kept (unified session only)."""
        return self._leave('post')

    def _hosted_help(self):
        """Advertise host-only navigation only when an outer session can honor it."""
        if self._host is None:
            return ''
        return (f"\n{C.bold('SESSION')}\n"
                f"  back                      Return to the lkpr menu\n"
                f"  prep / post               Switch shell (state is kept)\n"
                f"  quit                      Exit lkpr\n")
