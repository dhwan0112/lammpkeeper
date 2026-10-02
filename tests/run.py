"""Dependency-free test runner: `python tests/run.py`.

Discovers and runs every `test_*` function in the tests/ modules without
requiring pytest. `pytest tests/` also works when pytest is installed.
Set LKPR_SLOW=1 to include the slower RDF/MSD regression checks.
"""
import os
import sys
import importlib
import traceback

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
   sys.path.insert(0, TESTS_DIR)

MODULES = ['test_mapping', 'test_display', 'test_lkpr_cli', 'test_fair_comparison',
           'test_regression_numeric', 'test_parse_log_merge', 'test_dump_reader']


def main():
   passed = failed = 0
   for modname in MODULES:
      mod = importlib.import_module(modname)
      for name in sorted(dir(mod)):
         if not name.startswith('test_'):
            continue
         fn = getattr(mod, name)
         if not callable(fn):
            continue
         try:
            fn()
            print(f'PASS {modname}.{name}')
            passed += 1
         except Exception:
            print(f'FAIL {modname}.{name}')
            traceback.print_exc()
            failed += 1
   print(f'\n{passed} passed, {failed} failed')
   return 1 if failed else 0


if __name__ == '__main__':
   sys.exit(main())
