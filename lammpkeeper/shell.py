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
    prompt = f"\x01{C.MAGENTA}\x02lkpr>\x01{C.RESET}\x02 "
    intro = '\n' + banner([
        f"{C.BOLD}LammpKeeper (lkpr){C.RESET}  v{VERSION}",
        "LAMMPS pre/post-processing for Fe-O MLFF / ReaxFF studies",
    ]) + '\n' + _MENU

    def __init__(self):
        super().__init__()
        self._shells = {}
        self._entered = set()
        self._load_history(_HISTFILE)

    # ── readline history, one file per shell ──

    def _load_history(self, path):
        if readline is None or not history_enabled():
            return
        readline.clear_history()
        readline.set_history_length(HISTORY_LENGTH)
        try:
            readline.read_history_file(path)
        except (FileNotFoundError, OSError):
            pass

    def _save_history(self, path):
        if readline is None or not history_enabled():
            return
        try:
            readline.set_history_length(HISTORY_LENGTH)
            readline.write_history_file(path)
        except OSError:
            pass

    # ── shells ──

    def _shell(self, name):
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
            self._load_history(_HISTFILE)

    def _enter(self, name, arg):
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
        print()
        return self.do_quit(arg)

    def emptyline(self):
        pass

    def default(self, line):
        print(f"  Unknown command: '{line}'. Choose 'prep' or 'post' (or 'quit').")

    def postloop(self):
        self._save_history(_HISTFILE)


def main():
    shell = LkprShell()
    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        print(f"\n\n  {C.dim('Interrupted. Goodbye!')}\n")
    return 0
