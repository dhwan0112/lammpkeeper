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
# Timestamp resolution is one second: simultaneous identical-mode runs should
# use distinct LKPR_VERIFY_DIR roots to avoid sharing an evidence directory.
mkdir -p "$EVID" || { echo "cannot create evidence dir $EVID" >&2; exit 2; }
TMPHOME="$(mktemp -d)"; WORK="$(mktemp -d)"
# Own only these disposable paths. Evidence is outside them and must survive
# normal completion and failure so a failed verification can be investigated.
cleanup() { rm -rf "$TMPHOME" "$WORK"; }
trap cleanup EXIT
export HOME="$TMPHOME" LKPR_NO_HISTORY=1
export MPLCONFIGDIR="$TMPHOME/matplotlib"
: > "$EVID/outputs.txt"

declare -a RESULTS=()
# Keep machine-detectable PASS/FAIL/SKIP prefixes; only FAIL controls the exit
# status, while SKIP remains explicit evidence of an unverified optional path.
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
# Probe the selected interpreter, not a different environment's installed
# package list. An import failure disables only the optional drive step.
have() { "$PY" -c "import $1" 2>/dev/null; }

# ── Tests ───────────────────────────────────────────────────────────────
if [ "$MODE" = full ]; then SLOW=1; else SLOW=0; fi
if HOME="$TMPHOME" LKPR_SLOW="$SLOW" "$PY" tests/run.py > "$EVID/tests.log" 2>&1 \
   && grep -qE '^[1-9][0-9]* passed, 0 failed, [0-9]+ skipped$' "$EVID/tests.log"; then
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

# ── Drive: post one-shot + persisted analysis evidence on the fixture ────
if [ -f "$FIXTURE" ]; then
  PLOT=(); [ "$MODE" = full ] && have matplotlib && PLOT=(--plot all)
  post_bad=0
  if ! (cd "$WORK" && HOME="$TMPHOME" "$PY" -m lammpkeeper post --dump "$FIXTURE" \
        --analyze all "${PLOT[@]}" --output "$WORK/post_out" < /dev/null) > "$EVID/post.log" 2>&1; then
    post_bad=1
  fi
  # Quick mode also needs persisted proof that every expected analysis ran.
  printf 'analyze all\nexport summary "%s/post_out/summary.txt"\n' "$WORK" > "$WORK/post.commands"
  if ! (cd "$WORK" && HOME="$TMPHOME" "$PY" -m lammpkeeper post --dump "$FIXTURE" \
        --batch "$WORK/post.commands" --output "$WORK/post_out" < /dev/null) > "$EVID/post-batch.log" 2>&1; then
    post_bad=1
  fi
  # Structure is generated on-demand by plot all, not by dump-only analyze all.
  for required in density_all spin dissociation penetration penetration_trend oar; do
    grep -qFx -- "--- $required ---" "$WORK/post_out/summary.txt" 2>/dev/null || post_bad=1
  done
  for required in msd rdf; do
    grep -qF -- "--- ${required}_" "$WORK/post_out/summary.txt" 2>/dev/null || post_bad=1
  done
  if [ ${#PLOT[@]} -gt 0 ]; then
    # Presence/size is a smoke gate, not image decoding or numerical validation.
    for required in density_profile msd_Fe o2_dissociation oar penetration penetration_trend rdf_Fe_O snapshots spin_evolution structure; do
      [ -s "$WORK/post_out/$required.png" ] || { echo "Missing/empty plot: $required.png" >> "$EVID/post.log"; post_bad=1; }
    done
  fi
  if [ "$post_bad" = 0 ] && ! grep -qiE 'Traceback|Error:|Analysis failed' "$EVID/post.log" "$EVID/post-batch.log"; then
    record PASS post "analyze all${PLOT:+ + plot all}; required analyses persisted"
  else
    record FAIL post "missing analyses/plots or command failure; see post.log and post-batch.log"
  fi
  [ ! -f "$WORK/post_out/summary.txt" ] || cp "$WORK/post_out/summary.txt" "$EVID/post-summary.txt"
  find "$WORK/post_out" -type f 2>/dev/null | sed "s|$WORK/||" | sort > "$EVID/outputs.txt"
  # outputs.txt inventories disposable artifacts; only logs and the copied
  # analysis summary survive cleanup, not the plots or generated preparation.
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
      # An exit status of zero is insufficient: writers used to swallow errors.
      for required in ace_oxidation.in lammps_ace.data regions_ace.inc structure.xyz run.sh; do
        [ -s "$WORK/prep_out/$required" ] || { echo "Missing/empty artifact: $required" >> "$EVID/prep.log"; bad=1; }
      done
      if [ "$bad" = 0 ] && [ "$n" -gt 0 ] \
         && ! grep -qiE 'Traceback|Error:|failed' "$EVID/prep.log"; then
        record PASS prep "$n job script(s) pass bash -n; required artifacts present"
      else
        record FAIL prep "missing artifacts, reported failure or invalid script; see prep.log"
      fi
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
