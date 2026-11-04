# REV-PLOT-1: interactive RDF reference overlays use each curve's own pair

Status: fixed and verified (PR #91).
Branch: `rev-plot-1/rdf-reference-pair` from `180f913` (main after PR #90).
Source: BACKLOG REV-PLOT-1 (P2; F-SESSION-1 in `docs/agent/REVIEW-20261028.md`).

## Problem

`lammps_post/shell.py::_iplot_rdf` derived the element pair for the
reference g(r) overlay from the first selected cache key by splitting it on
`_`. `_analyze_rdf` stores curves under hyphenated keys (`rdf_Fe-O`,
`rdf_O-O`), so the split never produced two parts and the code fell back to
`('Fe', 'O')`. The interactive menu then listed the Fe-O phases and computed
Fe-O references for whatever curve was selected, and when several curves were
selected they all shared that single reference list, which was also what
`plot redo rdf` replayed from the recipe's `_ref_rdfs` list. The measured RDF
kernel was never wrong; the overlay was, silently, for every pair other than
Fe-O. Type-id pairs (`rdf_1-2`) and legacy underscore keys (`rdf_X_Y`, used
by the CIF import test) were affected the same way.

## Change

`lammps_post/shell.py`:

- `_rdf_reference_pair(key, data)` (static): the pair of one cached curve,
  read from `display_label` (species names when the user typed type ids),
  then `label`, then the key stem with `_` mapped to `-`. Exactly two
  non-empty parts make a pair; anything else is `None`. There is no default
  pair any more.
- `_rdf_recipe_references(recipe, key)` (static): the saved references for
  one cache key. `_ref_rdfs` is now a dict keyed by cache key; a bare list
  (the pre-fix shape) or any other value names no curve and yields no overlay.
- `_iplot_rdf` interactive path: after curve selection and the existing
  "Overlay reference crystal g(r)?" prompt it reads every selected curve's
  pair, warns per curve when the pair cannot be read, skips the reference
  menu with a warning when no selected curve names a pair, and otherwise
  calls `_rdf_select_references`. Each curve is plotted with its own list and
  the recipe stores `{'_ref_rdfs': {key: refs-or-None}}` (or `None`).
- `_rdf_select_references(pairs, distinct)`: one menu for all selected
  curves. Built-in phases are offered when `get_phases_for_pair` lists them
  for at least one selected pair and, with more than one distinct pair, are
  tagged with the pairs they serve (`α-Fe (BCC)  [Fe-Fe]`); with no matching
  phase the menu says so and still offers the CIF option under the same
  numbering rule (`len(builtin) + 2`). A CIF or COD crystal serves every pair.
  The menu order follows the phase database, not the curve selection order.
  References are computed per curve, per source, only for sources that serve
  that curve's pair, and each (source, pair) once even when several curves
  share a pair; a CIF that cannot produce a pair warns per pair, and a curve
  that ends with no reference after the user asked for an overlay warns
  `<key>: no X-Y reference among the selected sources; plotted without
  overlay.` (empty answer, no matching phase, or a numeric selection that
  serves only the other curves).
- Batch/redo path: `plot_rdf(..., ref_rdfs=self._rdf_recipe_references(recipe, k))`
  per key, so a redo after plotting `O-O` and `Fe-Fe` replays O-O references
  on the O-O curve and Fe-Fe references on the Fe-Fe curve. A cached curve
  that was not part of the saved selection (analysed later, or not selected
  then) is replayed without overlay with a dim note saying so; before the
  fix it silently received the shared list.
- The module-level `references` import inside `_iplot_rdf` moved into
  `_rdf_select_references`, the only place that now uses it.

`tests/test_rdf_reference_pair.py` (new, no matplotlib or numeric reference
computation needed: the calculator and renderer are recorders):

- pair derivation unit cases, including `rdf_1-2` with a `display_label`,
  legacy `rdf_X_Y`, and the non-pairs `rdf_all`, `rdf_Fe-O-up`, `rdf_-O`;
- recipe reader unit cases: per-key dict, missing key, empty list, bare
  list, recipe without the key, `None` recipe;
- `plot rdf` with `rdf_O-O` and `rdf_Fe-Fe` selected together: every
  calculator call uses the curve's own pair, never Fe-O, each curve gets
  exactly the built-in phases that contain its pair, the menu tags α-Fe as
  `[Fe-Fe]`, and the recipe is a per-key dict;
- `plot redo rdf` replays the per-key lists with no calculator call, notes a
  curve outside the saved selection, and a bare-list recipe gives no overlay;
- `rdf_1-2` (no element names) shows "no built-in phase contains these
  pairs", computes nothing, warns and plots without overlay; `rdf_all` warns
  that its pair cannot be read and never reaches the reference prompt; an
  empty selection answer warns the same way;
- a numeric selection (α-Fe, entry 1 in database order) on `rdf_1-2`
  (display label Fe-O), `rdf_Fe-Fe` and `rdf_all`: one calculator call for
  Fe-Fe, no overlay and a warning for the Fe-O curve, the unreadable curve
  warned separately;
- a CIF selected for `Fe-O`, `O-O` and a type-id curve resolving to Fe-O is
  computed once per pair (two calls, three curves);
- the legacy-key CIF failure path (mirror of the matplotlib-gated check in
  `test_cif_occupancy`): the CIF option is still `2` with no built-in phase,
  a `ValueError` from `parse_cif` fails the command before any computation,
  render or recipe write.

`tests/run.py`: the new module is registered in `MODULES` (the runner has
an explicit list; the first full run after writing the tests reported the
unchanged 738/725 totals, which is how the omission was caught).

BACKLOG row set to done; CHANGELOG entry under `[Unreleased]`.

## Decisions

- No default pair. The old `('Fe', 'O')` fallback is what turned a parsing
  bug into a wrong scientific overlay; an unreadable pair now produces a
  visible warning and no overlay instead of a plausible-looking wrong one.
- One menu, per-curve computation. Asking the phase question once per curve
  would multiply prompts for `all`; tagging each phase with the pairs it
  serves keeps a single prompt while making it clear that, for example, α-Fe
  cannot serve an O-O curve. Selecting it only affects the curves it serves.
- `_ref_rdfs` becomes a dict keyed by cache key. The list shape could not say
  which curve a reference belonged to, which is the second half of
  F-SESSION-1. Recipes are in-memory only (`state.py` never serializes them),
  so no stored data changes shape; an old list in a live session simply
  yields no overlay on redo rather than a wrong one.
- `display_label` is read before `label` so that curves analysed by type id
  (`rdf_1-2` with species metadata) compare against the resolved elements;
  without metadata `1-2` is read as a pair, matches no built-in phase, and
  can still be served by a user CIF, which is also the only source that can
  serve it.
- The `plot recipes` listing already hides underscore-prefixed keys, so the
  dict is not printed.

## Verification

| Check | Result |
| --- | --- |
| `run_one.py test_rdf_reference_pair` | 6 PASS |
| `run_one.py test_cif_occupancy` | 7 PASS, 1 SKIP (`matplotlib not installed (interactive CIF shell check)`); the same scenario is covered without matplotlib by `test_failed_cif_import_on_legacy_key_publishes_nothing` |
| `run_one.py test_species_plot_labels` | 4 PASS |
| `HOME=tmp /usr/bin/python3 tests/run.py` (native parser installed) | 746 passed, 0 failed, 26 skipped (738/0/26 on main; the 8 new tests pass) |
| `LKPR_NO_NATIVE=1 HOME=tmp /usr/bin/python3 tests/run.py` | 733 passed, 0 failed, 39 skipped (725/0/39 on main) |
| `('Fe', 'O')` default left in `shell.py` | `grep -n "'Fe', 'O'" lammps_post/shell.py` finds none |

## Review round

Read-only review of the diff before merge; findings and their resolution are
listed below.

| # | Finding | Resolution |
| --- | --- | --- |
| 1 | `_rdf_recipe_references` called `.get` on the recipe unguarded; a non-dict recipe would raise | Returns None unless the recipe is a dict |
| 2 | Behaviour change: redo now overlays only the curves in the saved selection; curves analysed later get nothing, silently | Intentional (a shared list was the bug); the batch path now prints a dim note for a cached curve missing from the saved dict, with a test |
| 3 | After answering `y`, an empty answer, no matching built-in phase, a numeric selection serving only other pairs, or a None from the calculator all dropped the overlay silently | Per-curve warning `no X-Y reference among the selected sources; plotted without overlay`, tested for the empty answer, the type-id pair and the partial numeric selection |
| 4 | Built-in menu order followed the curve selection order, so numbering changed with the selection | Sorted by `get_available_phases()` order; unchanged for a single pair |
| 5 | A CIF was recomputed for every curve sharing a pair and printed "Reference loaded" each time | Each (source, pair) computed once; tested with three curves and two pairs |
| 6 | A grouped species display name that is not two element names is read as a pair and matches no phase, but a CIF is still attempted | Kept: the menu says no built-in phase contains it, the CIF attempt warns if it cannot produce the pair |
| 7 | `_save_recipe` docstring did not state the `_ref_rdfs` shape | Documented |
| 8 | Menu-tag assertions depend on the phase database contents | Kept as documentation of the menu; the regression guard is the per-curve pair assertion and `('Fe','O')` never requested |
| 9 | Missing cases: display_label through the shell, readable+unreadable mix, partial numeric selection, empty answer, batch with no recipe | All added (see the test list above) |
| 10 | The test helper never set `display_label`, so the real cache shape was not exercised | Helper accepts extra fields; two tests use `display_label` |
| 11 | The matplotlib-free CIF failure test duplicates the gated one in `test_cif_occupancy` | Kept: on this host the gated test skips, so this is the only executed cover for that path |
| — | Checked: legacy `rdf_X_Y` still gives the CIF option number `2`; the lazy `references` import keeps the existing patches effective; single-curve menu and empty-answer behaviour unchanged except for the new warning; `pairs[k] is None` never reaches the calculator; no other reader of `plot_recipes['rdf']` or `_ref_rdfs` in `state.py`, `session*.py` or tests | No change |
