"""Dependency-free test runner: `python tests/run.py`.

Runs every callable `test_*` name in the explicitly registered modules below,
without requiring pytest. New modules must be added to MODULES; this runner
intentionally does not claim automatic filesystem discovery. Pytest can discover
the same files independently when installed. Set LKPR_SLOW=1 to include slower
RDF/MSD regressions and the independent fixture RDF oracle. Tests are ordinary
zero-argument callables: this runner does not implement pytest fixtures, plugins
or parameterization. A passing count certifies only the registered checks that
actually ran, not every optional integration or physical model.
"""
import os
import sys
import importlib
import traceback

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

from _util import Skip  # noqa: E402

MODULES = ['test_mapping', 'test_display', 'test_lkpr_cli', 'test_fair_comparison',
           'test_regression_numeric', 'test_parse_log_merge', 'test_dump_reader',
           'test_engine', 'test_periodicity', 'test_skip_reporting', 'test_history',
           'test_job_script_safety', 'test_msd', 'test_species_selection',
           'test_species_plot_labels', 'test_o2_periodicity', 'test_o2_pairing',
           'test_audit_analysis', 'test_audit_parsers', 'test_audit_workflow',
           'test_audit_prep', 'test_audit_references_plots', 'test_audit_verifier',
           'test_audit_rdf_oracle', 'test_audit_integration', 'test_slab_reference',
           'test_species_map', 'test_species_metadata', 'test_species_session',
           'test_box_model', 'test_box_geometry', 'test_triclinic_io',
           'test_triclinic_analysis', 'test_triclinic_session', 'test_log_integrity',
           'test_cif_occupancy']


def main():
    """Run registered checks deterministically and return nonzero on any failure.

    Skip is a distinct outcome, never a pass. Import failures remain visible
    outside the per-test catch so an unavailable or broken test module cannot
    silently disappear from the suite's reported coverage.
    """
    passed = failed = skipped = 0
    for modname in MODULES:
        mod = importlib.import_module(modname)
        for name in sorted(dir(mod)):
            if not name.startswith('test_'):
                continue
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            # Tests use ordinary zero-argument callables so pytest is optional;
            # traceback evidence is retained rather than aborting after one bug.
            try:
                fn()
                print(f'PASS {modname}.{name}')
                passed += 1
            except Skip as e:
                print(f'SKIP {modname}.{name}: {e}')
                skipped += 1
            except Exception:
                print(f'FAIL {modname}.{name}')
                traceback.print_exc()
                failed += 1
    print(f'\n{passed} passed, {failed} failed, {skipped} skipped')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
