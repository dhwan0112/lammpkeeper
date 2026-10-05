#!/usr/bin/env bash
# Build the optional native dump parser and drop it next to parsers.py.
# Without it, lammps_post falls back to np.loadtxt (same results, slower).
set -euo pipefail
cd "$(dirname "$0")"
cargo build --release
cp target/release/lib_dumpparse.so ../lammps_post/_dumpparse.abi3.so
echo "installed lammps_post/_dumpparse.abi3.so"
