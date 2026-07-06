"""
═══════════════════════════════════════════════════════════════
Section 1: Display Utilities
═══════════════════════════════════════════════════════════════
Terminal output helpers for colored text, tables, and key-value
displays. Uses ANSI escape codes for color, with optional 'rich'
library integration for prettier output when available.
═══════════════════════════════════════════════════════════════
"""

# ── Optional rich library ──
# Provides beautiful tables (RichTable), panels, and progress bars.
# Falls back to plain ANSI-colored text output when not available.
try:
    from rich.console import Console
    from rich.table import Table as RichTable
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich import box as rich_box
    _console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class C:
    """
    ANSI escape code constants and convenience methods for colored
    terminal output. These codes work in virtually all modern
    terminals (xterm, gnome-terminal, iTerm2, Windows Terminal, etc.).

    Usage:
        print(f"{C.RED}Error!{C.RESET}")   # Direct escape codes
        print(C.ok("Success"))              # Convenience wrappers
        print(C.err("Failed"))
    """
    BOLD = '\033[1m'       # Bold / bright text
    DIM = '\033[2m'        # Dimmed / faint text (for secondary info)
    RED = '\033[91m'       # Bright red (errors, O atoms in plots)
    GREEN = '\033[92m'     # Bright green (success messages, O2 in plots)
    YELLOW = '\033[93m'    # Bright yellow (warnings, interactive prompts)
    BLUE = '\033[94m'      # Bright blue (CLI prompt, Fe atoms in plots)
    MAGENTA = '\033[95m'   # Bright magenta (accent color)
    CYAN = '\033[96m'      # Bright cyan (info messages, table headers)
    WHITE = '\033[97m'     # Bright white
    RESET = '\033[0m'      # Reset all attributes to terminal default

    @staticmethod
    def ok(msg):    return f"{C.GREEN}{msg}{C.RESET}"    # Success/positive
    @staticmethod
    def warn(msg):  return f"{C.YELLOW}{msg}{C.RESET}"   # Warning/caution
    @staticmethod
    def err(msg):   return f"{C.RED}{msg}{C.RESET}"      # Error/failure
    @staticmethod
    def info(msg):  return f"{C.CYAN}{msg}{C.RESET}"     # Informational
    @staticmethod
    def bold(msg):  return f"{C.BOLD}{msg}{C.RESET}"     # Emphasized text
    @staticmethod
    def dim(msg):   return f"{C.DIM}{msg}{C.RESET}"      # De-emphasized text


def print_table(headers, rows, title=None):
    """
    Print a formatted table to the terminal.

    Uses rich.table.Table when the 'rich' library is available for
    beautiful box-drawn tables with colored headers. Falls back to
    a plain-text table with aligned columns using ANSI formatting.

    Args:
        headers: list[str] — Column header names.
        rows:    list[list] — Each inner list is one row of data.
                 Values are converted to strings automatically.
        title:   str or None — Optional title displayed above the table.
    """
    if HAS_RICH:
        t = RichTable(title=title, box=rich_box.ROUNDED)
        for h in headers:
            t.add_column(h, style="cyan")
        for row in rows:
            t.add_row(*[str(x) for x in row])
        _console.print(t)
    else:
        # Plain-text fallback: compute column widths from headers and data,
        # then format each row with left-aligned, padded columns.
        if title:
            print(f"\n  {C.bold(title)}")
        widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) + 2
                  for i, h in enumerate(headers)]
        hdr = "  ".join(f"{h:<{widths[i]}}" for i, h in enumerate(headers))
        print(f"  {C.BOLD}{hdr}{C.RESET}")
        print(f"  {'─' * len(hdr)}")
        for row in rows:
            line = "  ".join(f"{str(row[i]):<{widths[i]}}" for i in range(len(headers)))
            print(f"  {line}")
        print()


def print_kv(pairs, title=None):
    """
    Print key-value pairs in a visually distinct panel or indented block.

    Uses rich.Panel when available for a bordered display. Falls back
    to simple indented text with a horizontal rule separator.

    Args:
        pairs: list[tuple[str, str]] — Each tuple is (key_name, value).
        title: str or None — Optional panel/section title.
    """
    if HAS_RICH:
        lines = "\n".join(f"[cyan]{k}:[/cyan]  {v}" for k, v in pairs)
        _console.print(Panel(lines, title=title, border_style="blue"))
    else:
        if title:
            print(f"\n  {'─' * 50}")
            print(f"  {C.bold(title)}")
            print(f"  {'─' * 50}")
        for k, v in pairs:
            print(f"  {C.CYAN}{k}:{C.RESET}  {v}")
        print(f"  {'─' * 50}")


def progress_msg(msg):
    """
    Print a single-line progress/status message with a dim '>' prefix.
    Used throughout the tool to show step-by-step progress during
    file loading, analysis computation, and plot generation.
    """
    print(f"  {C.DIM}>{C.RESET} {msg}")
