#!/usr/bin/env bash
# Stage synthetic evaluation data in the evaluation working directory only.
set -eu
cp -R "$(dirname "$0")/files/." .
