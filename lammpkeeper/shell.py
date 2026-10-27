"""
Unified interactive session for `lkpr`: pick pre- or post-processing from one
prompt and switch between them without losing state.

    lkpr> prep          enter the lammps-pre shell
    lkpr> post          enter the lammps-post shell
    lkpr> post info     run one post command and stay at the lkpr prompt

Inside either shell, `back` returns here, `prep` / `post` switch directly and
`quit` exits. Each shell is created once, so loaded files and settings survive
switching; readline history is kept per shell.
"""

import cmd
import os

from lammpkeeper import VERSION
from lammpkeeper.common.display import C, banner
from lammpkeeper.common.hosted import HISTORY_LENGTH, history_enabled

try:
    import readline
except ImportError:
    readline = None

_HISTFILE = os.path.expanduser('~/.lkpr_history')

_MENU = f"""
  {C.bold('prep')}   Pre-processing: build Fe-O slabs and write LAMMPS inputs
  {C.bold('post')}   Post-processing: load dumps/logs, analyze and plot
  {C.bold('quit')}   Exit

  Inside a shell: {C.info('back')} returns here, {C.info('prep')}/{C.info('post')} switch, {C.info('quit')} exits.
  'post <command>' runs a single command without entering the shell.
"""


class LkprShell(cmd.Cmd):
    """Own persistent prep/post instances and the outer navigation loop.

    Child cmdloops communicate their next destination through ``_next``;
    changing modes is not a reset of loaded trajectories or build settings.
    """
    prompt = f"\x01{C.MAGENTA}\x02lkpr>\x01{C.RESET}\x02 "
    intro = '\n' + banner([
        f"{C.BOLD}LammpKeeper (lkpr){C.RESET}  v{VERSION}",
        "LAMMPS pre/post-processing for Fe-O MLFF / ReaxFF studies",
    ]) + '\n' + _MENU

    def __init__(self):
        """Start with lazy child shells and restore only the menu's own history."""
        super().__init__()
        self._shells = {}
        self._entered = set()
        self._load_history(_HISTFILE)

    # ── readline history, one file per shell ──

    def _load_history(self, path):
        """Replace the global readline buffer when focus changes to another shell.

        Clear before reading to avoid repeated loads multiplying history. Missing
        history files are normal on first use; the environment opt-out prevents
        both reads and writes during automation and isolated tests.
        """
        if readline is None or not history_enabled():
            return
        readline.clear_history()
        readline.set_history_length(HISTORY_LENGTH)
        try:
            readline.read_history_file(path)
        except (FileNotFoundError, OSError):
            pass

    def _save_history(self, path):
        """Write a bounded history snapshot without making persistence mandatory.

        An unwritable HOME must not prevent analysis or shell navigation; this
        optional convenience intentionally tolerates filesystem errors.
        """
        if readline is None or not history_enabled():
            return
        try:
            readline.set_history_length(HISTORY_LENGTH)
            readline.write_history_file(path)
        except OSError:
            pass

    # ── shells ──

    def _shell(self, name):
        """Create each mode once, deferring heavy imports until that mode is used.

        Reusing the instance is what preserves settings and source/cache state
        across switches; assigning the host enables child navigation commands.
        """
        sh = self._shells.get(name)
        if sh is None:
            if name == 'prep':
                from lammps_pre.shell import LammpsPreShell as cls
            else:
                from lammps_post.shell import LammpsPostShell as cls
            sh = cls()
            sh._host = self
            self._shells[name] = sh
        return sh

    def _run(self, name):
        """Run shells starting with `name` until the user goes back or quits.

        Returns True when the whole session should end.
        """
        self._save_history(_HISTFILE)
        try:
            while name in ('prep', 'post'):
                sh = self._shell(name)
                if name in self._entered:
                    intro = C.dim(f"  [{name}] back: menu | "
                                  f"{'post' if name == 'prep' else 'prep'}: switch | quit: exit")
                else:
                    intro = sh.intro + C.dim("  Inside lkpr: 'back' returns to the menu.") + '\n'
                    self._entered.add(name)
                self._load_history(sh.histfile)
                sh._next = None
                try:
                    sh.cmdloop(intro=intro)
                except KeyboardInterrupt:
                    print(f"\n  {C.dim('Interrupted.')}")
                    sh._next = 'menu'
                self._save_history(sh.histfile)
                name = sh._next
            return name == 'quit'
        finally:
            # Restore menu history even if a child raises, so its buffer cannot
            # later be saved under the outer session's history filename.
            self._load_history(_HISTFILE)

    def _enter(self, name, arg):
        """Distinguish a one-command dispatch from entering a persistent cmdloop.

        A child quit request ends the outer session only through _run's explicit
        navigation protocol, not a stray truthy return from an inline command.
        """
        if arg.strip():
            sh = self._shell(name)
            sh.onecmd(arg)
            return False
        if self._run(name):
            return True
        print(_MENU)
        return False

    def do_prep(self, arg):
        """prep [command] — enter the pre-processing shell, or run one command in it."""
        return self._enter('prep', arg)

    def do_post(self, arg):
        """post [command] — enter the post-processing shell, or run one command in it."""
        return self._enter('post', arg)

    def do_menu(self, arg):
        """Show the menu."""
        print(_MENU)

    do_help = do_menu

    def do_quit(self, arg):
        """Exit lkpr."""
        print(f"\n  {C.dim('Goodbye!')}\n")
        return True

    do_exit = do_q = do_quit

    def do_EOF(self, arg):
        """Treat end-of-input like quit instead of repeatedly reopening the prompt."""
        print()
        return self.do_quit(arg)

    def emptyline(self):
        """Ignore blank input; cmd.Cmd's default would repeat the previous command."""
        pass

    def default(self, line):
        """Keep the outer menu recoverable after an unrecognized navigation word."""
        print(f"  Unknown command: '{line}'. Choose 'prep' or 'post' (or 'quit').")

    def postloop(self):
        """Save the currently restored menu buffer after normal cmdloop shutdown."""
        self._save_history(_HISTFILE)


def main():
    """Launch the unified menu; child shells retain ownership of their workflows."""
    shell = LkprShell()
    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        print(f"\n\n  {C.dim('Interrupted. Goodbye!')}\n")
    return 0
