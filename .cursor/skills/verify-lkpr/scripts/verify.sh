#!/usr/bin/env bash
# verify-lkpr: doctor + tests + one-shot post (+ prep smoke in full mode).
# Usage: verify.sh [quick|full]      Evidence: $LKPR_VERIFY_DIR (default ~/.cache/lkpr-verify)
set -uo pipefail

MODE="${1:-quick}"
case "$MODE" in quick|full) ;; *) echo "usage: $0 [quick|full]" >&2; exit 2 ;; esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT" || exit 2
PY="${PYTHON:-python3}"
# Import from this checkout even when the package is not pip-installed.
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
FIXTURE="$ROOT/tests/fixtures/ace_examples/regular_MD/traj.dump"

SHA="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
EVID="${LKPR_VERIFY_DIR:-$HOME/.cache/lkpr-verify}/$(date +%Y%m%dT%H%M%S)-$SHA-$MODE"
mkdir -p "$EVID" || { echo "cannot create evidence dir $EVID" >&2; exit 2; }
TMPHOME="$(mktemp -d)"; WORK="$(mktemp -d)"
cleanup() { rm -rf "$TMPHOME" "$WORK"; }
trap cleanup EXIT

declare -a RESULTS=()
record() { RESULTS+=("$1 $2${3:+ — $3}"); }   # STATUS STEP NOTE

# ── Doctor ──────────────────────────────────────────────────────────────
{
  echo "mode: $MODE"; echo "root: $ROOT"
  echo "git: $(git rev-parse --abbrev-ref HEAD 2>/dev/null) @ $SHA"
  echo "dirty files: $(git status --porcelain 2>/dev/null | wc -l)"
  "$PY" --version
  for m in numpy scipy ase matplotlib pandas MDAnalysis rich; do
    "$PY" -c "import $m; print('  ok  $m', getattr($m,'__version__',''))" 2>/dev/null \
      || echo "  MISSING $m"
  done
  ls lammps_post/_dumpparse*.so >/dev/null 2>&1 && echo "  native parser: present" \
      || echo "  native parser: absent (NumPy fallback)"
  [ -f "$FIXTURE" ] && echo "  fixture: present" || echo "  fixture: MISSING"
} > "$EVID/doctor.txt" 2>&1
cat "$EVID/doctor.txt"
have() { "$PY" -c "import $1" 2>/dev/null; }

# ── Tests ───────────────────────────────────────────────────────────────
if [ "$MODE" = full ]; then SLOW=1; else SLOW=0; fi
if HOME="$TMPHOME" LKPR_SLOW="$SLOW" "$PY" tests/run.py > "$EVID/tests.log" 2>&1; then
  record PASS tests "$(tail -n 1 "$EVID/tests.log")"
else
  record FAIL tests "$(tail -n 1 "$EVID/tests.log")"
fi
# Surface the runner's own SKIP lines (TEST-1): they name each skipped test
# and its reason. Do not guess from missing dependencies — a missing module
# only matters if a test actually skipped because of it, and the runner
# already says so. No SKIP lines means nothing was skipped.
while IFS= read -r line; do
  record SKIP "${line#SKIP }" ""
done < <(grep '^SKIP ' "$EVID/tests.log" || true)

# ── Drive: post one-shot on the fixture ─────────────────────────────────
if [ -f "$FIXTURE" ]; then
  PLOT=(); [ "$MODE" = full ] && have matplotlib && PLOT=(--plot all)
  if (cd "$WORK" && HOME="$TMPHOME" "$PY" -m lammpkeeper post --dump "$FIXTURE" \
        --analyze all "${PLOT[@]}" --output "$WORK/post_out" < /dev/null) > "$EVID/post.log" 2>&1 \
     && ! grep -qE "Traceback|Error:" "$EVID/post.log"; then
    record PASS post "analyze all${PLOT:+ + plot all}"
  else
    record FAIL post "see post.log"
  fi
  find "$WORK/post_out" -type f 2>/dev/null | sed "s|$WORK/||" | sort > "$EVID/outputs.txt"
else
  record SKIP post "fixture missing"
fi

# ── Drive: prep smoke (full mode, needs ASE) ────────────────────────────
if [ "$MODE" = full ]; then
  if have ase; then
    if (cd "$WORK" && HOME="$TMPHOME" "$PY" -m lammpkeeper prep --ff ace --temp 800 --o2 4 \
          --slab 4x4x8 --write "$WORK/prep_out" < /dev/null) > "$EVID/prep.log" 2>&1; then
      bad=0; n=0
      while IFS= read -r s; do
        n=$((n+1)); bash -n "$s" >> "$EVID/prep.log" 2>&1 || bad=1
      done < <(find "$WORK/prep_out" -type f \( -name '*.sh' -o -name '*.pbs' \) 2>/dev/null)
      find "$WORK/prep_out" -type f 2>/dev/null | sed "s|$WORK/||" | sort >> "$EVID/outputs.txt"
      if [ $bad = 0 ]; then record PASS prep "$n job script(s) pass bash -n"; else record FAIL prep "bash -n failed"; fi
    else
      record FAIL prep "see prep.log"
    fi
  else
    record SKIP prep "ASE not installed"
  fi
fi

# ── Evidence summary ────────────────────────────────────────────────────
printf '%s\n' "${RESULTS[@]}" | tee "$EVID/summary.txt"
echo "evidence: $EVID"
grep -q '^FAIL' "$EVID/summary.txt" && exit 1
exit 0
