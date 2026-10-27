#!/usr/bin/env bash
# Build the optional native dump parser and drop it next to parsers.py.
# Without it, lammps_post falls back to np.loadtxt (same results, slower).
# Requires an existing Rust/Cargo toolchain and configured Python/PyO3 build
# environment; this helper does not bootstrap or install either toolchain.
# Fail immediately on build/copy errors or unset variables, rather than claiming
# that the extension was installed when only an older shared object exists.
set -euo pipefail
# Resolve build paths from this script, independent of the invoking directory.
cd "$(dirname "$0")"
# Produce the optimized cdylib using Cargo's manifest/PyO3 ABI configuration.
cargo build --release
# Install the Linux shared library alongside parsers.py for the relative import.
# `_dumpparse` must match the Rust module initializer; the abi3 suffix denotes
# the stable Python ABI configured in Cargo, not a rebuild for every Python minor.
cp target/release/lib_dumpparse.so ../lammps_post/_dumpparse.abi3.so
# Report success only after the release artifact has been copied successfully.
echo "installed lammps_post/_dumpparse.abi3.so"
