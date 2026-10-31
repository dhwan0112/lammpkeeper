# REV-IO-4 — '#' is ordinary text in dump atom rows

Status: implemented and fully verified by the parent;
[PR #42](https://github.com/dhwan0112/lammpkeeper/pull/42).

## Defect (measured)
The NumPy fallback in `DumpReader._parse_block` called `np.loadtxt` with its
default `comments='#'`. For `ITEM: ATOMS id type element x y z`:
- `1 1 A 1 2 3#CORRUPTED`: native rejected the token, NumPy stripped
  `#CORRUPTED` and returned `[[1,1,1,2,3]]` with no warning (both readers).
- `1 1 A#site 1 2 3`: native returned element `A#site`; forced NumPy raised
  `invalid column index 3 ...`.

## Fix
`lammps_post/parsers.py`: both `np.loadtxt` calls on atom rows now pass
`comments=None`. Corrupted numeric tokens raise `ValueError` ("malformed atom
block") on both paths; text labels with '#' parse identically.

## Scope check
`grep loadtxt|genfromtxt` over `lammps_post`, `lammpkeeper`, `lammps_pre`: only
these two calls exist. Data-file, log and input parsing use their own line
code and keep '#' comment handling unchanged.

## Tests
`tests/test_dump_comment_tokens.py` (4 tests): corrupted tokens rejected on
NumPy and native; numeric-only projection; `A#site` parity with `np.loadtxt`
patched to raise (no fallback masking); fixture arrays equal on both paths.
Native-dependent tests skip visibly when the module is not built.

## Evidence (measured, before/after)
- Before fix: native 1 passed / 3 failed; `LKPR_NO_NATIVE=1` 0 passed / 3 failed / 1 skipped.
- After fix, 8 requested modules, `LKPR_SLOW=1`: native 79 passed 0 failed 0 skipped;
  `LKPR_NO_NATIVE=1` 70 passed 0 failed 9 skipped (native-only tests).

## Parent integration (2026-11-01, measured)

- Rebased (unpublished, no force-push) onto main `73215fe` (PR #41). Registered
  `test_dump_comment_tokens`; BACKLOG and CHANGELOG updated.
- Failing-first reproduced by the parent against main's `parsers.py`: native
  **1 passed, 3 failed**; `LKPR_NO_NATIVE=1` **0 passed, 3 failed, 1 skipped**.
  With the fix: native **4 passed**; `LKPR_NO_NATIVE=1` **1 passed, 3 skipped**.
  In NumPy-only mode the three tests run their NumPy assertions first and then
  skip visibly because the native half could not be compared; they are not
  silent passes.
- Full verifier on `d8384b6`: native **568 passed, 0 failed, 0 skipped**;
  forced NumPy **559 passed, 0 failed, 9 skipped**. The nine are the six known
  native-only checks plus three new `test_dump_comment_tokens` tests whose native
  comparison cannot run without the native module (their NumPy assertions ran
  first; all nine PASS natively). Post analyses/real plots and prep passed.
  Evidence: `/tmp/opencode/io4-native/20261101T020645-d8384b6-full`,
  `/tmp/opencode/io4-numpy/20261101T020647-d8384b6-full`. Native extension not
  rebuilt; pytest, MDAnalysis and HPC not run.
