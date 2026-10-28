"""
═══════════════════════════════════════════════════════════════
Section 1: Display Utilities
═══════════════════════════════════════════════════════════════
Terminal output helpers for colored text, tables, and key-value
displays. Uses ANSI escape codes for color, with optional 'rich'
library integration for prettier output when available.
═══════════════════════════════════════════════════════════════
"""

import re
import unicodedata

# ── Optional rich library ──
# Provides beautiful tables (RichTable), panels, and progress bars.
# Falls back to plain ANSI-colored text output when not available.
try:
    from rich.console import Console
    from rich.table import Table as RichTable
    from rich.panel import Panel
    from rich.text import Text
    from rich import box as rich_box
    _console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# ANSI SGR sequences plus the \x01/\x02 readline markers used in prompts.
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|[\x01\x02]')


def visible_width(text):
    """Estimate terminal columns: supported ANSI codes count 0, wide glyphs 2.

    This code-point sum is not a grapheme-cluster or terminal cursor emulator;
    joined emoji, tabs and arbitrary control sequences need not match it.
    """
    width = 0
    # Approximate cell widths from code points: a combining mark decorates the
    # preceding character, while a wide/fullwidth glyph contributes two cells.
    for ch in _ANSI_RE.sub('', str(text)):
        if unicodedata.combining(ch) or unicodedata.category(ch) in ('Mn', 'Me', 'Cf'):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
    return width


def pad(text, width):
    """Left-align `text` in `width` terminal columns (ANSI/CJK aware)."""
    return f"{text}{' ' * max(0, width - visible_width(text))}"


def banner(lines, min_width=62, color=None):
    """
    Double-line box around `lines` (which may contain ANSI codes and CJK
    text); the right border always lines up because padding is computed
    from visible width, not len().
    """
    color = C.CYAN if color is None else color
    inner = max(min_width, *(visible_width(l) + 4 for l in lines))
    out = [f"{color}╔{'═' * inner}╗{C.RESET}"]
    for l in lines:
        out.append(f"{color}║{C.RESET}  {pad(l, inner - 2)}{color}║{C.RESET}")
    out.append(f"{color}╚{'═' * inner}╝{C.RESET}")
    return '\n'.join(out)


def _rich_text(value):
    """Preserve our ANSI styles without interpreting user values as Rich markup."""
    # Text.from_ansi turns our own C.* colour codes into styles, so rich
    # measures the visible text; raw escapes would be counted as columns and
    # push the right border out of line. It also stops '[...]' in values
    # from being parsed as rich markup.
    return Text.from_ansi(str(value))


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
    def ok(msg):
        """Mark a successful status, resetting styling so later output is unaffected."""
        return f"{C.GREEN}{msg}{C.RESET}"

    @staticmethod
    def warn(msg):
        """Highlight a caution without making a decision about process exit status."""
        return f"{C.YELLOW}{msg}{C.RESET}"

    @staticmethod
    def err(msg):
        """Color an error message; callers remain responsible for propagating failure."""
        return f"{C.RED}{msg}{C.RESET}"

    @staticmethod
    def info(msg):
        """Style informational text without changing the supplied message content."""
        return f"{C.CYAN}{msg}{C.RESET}"

    @staticmethod
    def bold(msg):
        """Emphasize a heading while keeping the style local to this string."""
        return f"{C.BOLD}{msg}{C.RESET}"

    @staticmethod
    def dim(msg):
        """De-emphasize secondary details without hiding them or filtering output."""
        return f"{C.DIM}{msg}{C.RESET}"


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
            t.add_column(_rich_text(h), style="cyan")
        for row in rows:
            t.add_row(*[_rich_text(x) for x in row])
        _console.print(t)
    else:
        # Plain-text fallback: compute column widths from headers and data,
        # then format each row with left-aligned, padded columns.
        if title:
            print(f"\n  {C.bold(title)}")
        widths = [max(visible_width(h), *(visible_width(r[i]) for r in rows)) + 2
                  for i, h in enumerate(headers)]
        hdr = "  ".join(pad(h, widths[i]) for i, h in enumerate(headers))
        print(f"  {C.BOLD}{hdr}{C.RESET}")
        print(f"  {'─' * visible_width(hdr)}")
        for row in rows:
            line = "  ".join(pad(row[i], widths[i]) for i in range(len(headers)))
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
        rows = []
        for k, v in pairs:
            key = _rich_text(f"{k}:")
            key.stylize("cyan")
            rows.append(Text.assemble(key, "  ", _rich_text(v)))
        _console.print(Panel(Text("\n").join(rows), title=title, border_style="blue"))
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
