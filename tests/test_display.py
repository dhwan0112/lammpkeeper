"""Stage 2 display de-duplication: single source of truth + rendering."""
import _util  # noqa: F401  (path bootstrap)

import lammps_pre.display as pre_d
import lammps_post.display as post_d
import lammpkeeper.common.display as common_d


def test_single_source_identity():
    """Legacy import paths must share objects, not divergent display copies."""
    # All three modules must expose the *same* objects (one implementation).
    assert pre_d.C is post_d.C is common_d.C
    assert pre_d.progress_msg is common_d.progress_msg
    assert post_d.print_table is common_d.print_table


def test_public_api_present():
    """Both compatibility modules must retain the established display exports."""
    for name in ('C', 'HAS_RICH', 'print_table', 'print_kv', 'progress_msg'):
        assert hasattr(pre_d, name), f'lammps_pre.display missing {name}'
        assert hasattr(post_d, name), f'lammps_post.display missing {name}'


def test_visible_width_ignores_ansi_and_counts_wide_chars():
    """Terminal width excludes control escapes and counts Korean glyphs twice."""
    C = common_d.C
    assert common_d.visible_width(C.ok('abc')) == 3
    assert common_d.visible_width('\x01\x1b[94m\x02lkpr>\x01\x1b[0m\x02') == 5
    assert common_d.visible_width('전처리 OK') == 9
    assert common_d.visible_width('Å ² ₂ ─') == 7


def _visible_lines(text):
    """Strip styling and blank lines before comparing rendered box geometry."""
    return [l for l in common_d._ANSI_RE.sub('', text).splitlines() if l.strip()]


def test_banner_right_border_aligned():
    """Mixed wide glyphs, styling and long lines must share one border column."""
    C = common_d.C
    out = common_d.banner([f"{C.BOLD}LAMMPS-PRE:{C.RESET} v0.1.0",
                           "한글 설명이 들어간 줄", "x" * 70])
    widths = {common_d.visible_width(l) for l in _visible_lines(out)}
    assert len(widths) == 1, widths


def test_kv_panel_and_table_right_border_aligned():
    """Rich and fallback output preserve literal brackets and aligned panels."""
    import contextlib
    import io
    C = common_d.C
    pairs = [('Log', C.dim('not loaded')), ('Normalize', C.warn('OFF')),
             ('Types', '[1, 2] Fe(1), O(2)'), ('메모', '한글 값'), ('Plain', 'value')]
    rows = [['1', C.ok('Fe')], ['2', '산소 [O]']]
    for has_rich in {common_d.HAS_RICH, False}:
        # Exercise fallback even on Rich-enabled hosts; restore the global on failure.
        saved = common_d.HAS_RICH
        common_d.HAS_RICH = has_rich
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                common_d.print_kv(pairs, 'Session Info')
                common_d.print_table(['Type', 'Name'], rows, 'Atom Types')
        finally:
            common_d.HAS_RICH = saved
        text = buf.getvalue()
        assert '[1, 2]' in text and '[O]' in text
        if has_rich:
            boxed = [l for l in _visible_lines(text) if l[:1] in '╭│├╰']
            panel = [l for l in boxed if common_d.visible_width(l) > 30]
            table = [l for l in boxed if common_d.visible_width(l) <= 30]
            for part in (panel, table):
                assert part and len({common_d.visible_width(l) for l in part}) == 1, part


def test_render_ansi():
    """Color helpers must emit the exact escape/reset pairs used by terminals."""
    assert common_d.C.ok('x') == '\x1b[92mx\x1b[0m'
    assert common_d.C.err('x') == '\x1b[91mx\x1b[0m'
    assert common_d.C.RESET == '\x1b[0m'
