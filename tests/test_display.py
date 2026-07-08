"""Stage 2 display de-duplication: single source of truth + rendering."""
import _util  # noqa: F401  (path bootstrap)

import lammps_pre.display as pre_d
import lammps_post.display as post_d
import lammpkeeper.common.display as common_d


def test_single_source_identity():
   # All three modules must expose the *same* objects (one implementation).
   assert pre_d.C is post_d.C is common_d.C
   assert pre_d.progress_msg is common_d.progress_msg
   assert post_d.print_table is common_d.print_table


def test_public_api_present():
   for name in ('C', 'HAS_RICH', 'print_table', 'print_kv', 'progress_msg'):
      assert hasattr(pre_d, name), f'lammps_pre.display missing {name}'
      assert hasattr(post_d, name), f'lammps_post.display missing {name}'


def test_render_ansi():
   assert common_d.C.ok('x') == '\x1b[92mx\x1b[0m'
   assert common_d.C.err('x') == '\x1b[91mx\x1b[0m'
   assert common_d.C.RESET == '\x1b[0m'
