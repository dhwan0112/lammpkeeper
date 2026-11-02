"""
Commands shared by the prep and post shells for running inside the unified
`lkpr` interactive session (lammpkeeper.shell.LkprShell).

When a shell is hosted, `back` returns to the lkpr menu, `prep` / `post`
switch to the other shell (each keeps its state), and `quit` ends the whole
session. Run standalone (`lkpr prep`, `python -m lammps_post`), the switch
commands only explain that they need the unified session.
"""

import atexit
import os
import sys

from lammpkeeper.common.display import C

try:
    import readline
except ImportError:
    readline = None

# Maximum history lines kept per shell (OPS-1). Without a cap the history
# files grow without bound — they reached tens of millions of lines.
HISTORY_LENGTH = 2000


# Standalone shell that currently owns the process-global readline buffer.
_buffer_owner = None


def _snapshot_buffer():
    """Copy the global readline buffer (oldest first)."""
    return [readline.get_history_item(i + 1)
            for i in range(readline.get_current_history_length())]


def _replace_buffer(entries):
    """Replace the global readline buffer with `entries`."""
    readline.clear_history()
    for line in entries:
        readline.add_history(line)


def load_history_bounded(path, limit=HISTORY_LENGTH):
    """Load `path` into a cleared readline buffer, keeping only the newest `limit`.

    A missing or unreadable file yields an empty buffer. Trimming happens on
    entries after readline has decoded them, so escaped multi-line entries are
    never split. The file is still read once in full by readline; only the
    resident buffer (and thus later writes) is bounded.
    """
    readline.clear_history()
    readline.set_history_length(limit)
    try:
        readline.read_history_file(path)
    except (FileNotFoundError, OSError):
        return
    if readline.get_current_history_length() > limit:
        # Keep the newest entries: old ones are the least useful to recall.
        _replace_buffer(_snapshot_buffer()[-limit:])


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
    _atexit_callback = None  # per-instance exit hook, registered at most once
    _detached_entries = None  # this shell's history after another shell took the buffer

    def _setup_history(self, histfile):
        """Replace the process-global history; standalone shells save it at exit.

        The loaded buffer is bounded to the history limit (newest kept). A host
        takes over buffer swapping after setting ``_host``. The readline buffer
        is process-global, so a previous standalone owner's entries are parked
        on that instance before this shell clears the buffer.
        """
        global _buffer_owner
        self.histfile = os.path.expanduser(histfile)
        if readline is None or not history_enabled():
            return
        readline.set_completer_delims(' \t\n')
        # Start from this file alone, as lkpr's _load_history does. Without the
        # clear, every shell created in one process (the test suite makes many)
        # re-appends the file to the shared readline history, and the exit
        # handler writes the sum back, so the file multiplies on every run.
        prev = _buffer_owner
        if prev is not None and prev is not self:
            prev._detached_entries = _snapshot_buffer()
        _buffer_owner = self
        self._detached_entries = None
        load_history_bounded(self.histfile)
        if self._atexit_callback is None:
            self._atexit_callback = self._run_exit_save
            atexit.register(self._atexit_callback)

    def _run_exit_save(self):
        """Exit hook: save this shell's history; report, never raise, on failure.

        atexit already runs later callbacks after an exception, but it prints a
        traceback per failure; a visible one-line warning keeps other shells'
        saves unaffected and the failure not silent.
        """
        try:
            self._save_history_if_standalone()
        except Exception as exc:  # noqa: BLE001 - must not block other callbacks
            print(f"lkpr: could not save history {self.histfile}: {exc!r}",
                  file=sys.stderr)

    def _save_history_if_standalone(self):
        """Persist this shell's own history for a standalone shell, honoring opt-out.

        Hosted sessions swap the process-global readline buffer themselves;
        writing it from an atexit callback would mix the shells' commands. The
        buffer owner writes the live buffer; any other instance writes the
        entries parked when it lost the buffer, so files never mix commands.
        """
        # Hosted shells share readline with lkpr, which swaps history per shell.
        if self._host is None and readline is not None and history_enabled():
            live = None
            try:
                readline.set_history_length(HISTORY_LENGTH)
                if _buffer_owner is not self:
                    if self._detached_entries is None:
                        return
                    live = _snapshot_buffer()
                    _replace_buffer(self._detached_entries)
                readline.write_history_file(self.histfile)
            except OSError:
                pass
            finally:
                if live is not None:
                    _replace_buffer(live)

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
