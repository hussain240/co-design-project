#!/usr/bin/env bash
# =============================================================================
# script_raytrace.sh -- HWSW project, benchmark #2: raytrace
#
#   0. environment setup (perf, python3-dbg, pyperformance, FlameGraph)
#   1. correctness check  (original vs optimized render a bit-identical image)
#   2. baseline run       (pyperformance, original raytrace)
#   3. optimized run      (pyperformance, custom manifest -> bm_raytrace_opt)
#   4. comparison         (pyperf compare_to)
#   5. hardware counters  (perf stat: cycles, instructions, IPC, branches, cache)
#   6. profiling          (course guide: perf record -g python3-dbg -m pyperformance -> perf report + flame graphs)
#   7. ablation study     (contribution of each optimization step)
#   8. hardware sim       (V3A RTL simulation: bit-exact vs golden model, accuracy vs Python)
#   9. call counts        (Python calls / allocations per render)
#
# Usage:   ./script_raytrace.sh            # normal mode
#          MODE=--rigorous ./script_raytrace.sh
#          SKIP_SETUP=1 ./script_raytrace.sh
# Tested on Ubuntu 22.04 (jammy) QEMU image, Python 3.10.
# =============================================================================
set -eu   # no pipefail: `perf report | head` would kill the script via SIGPIPE

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RT="$ROOT/benchmarks/raytrace"
RES="$RT/results"
FG="$RT/flamegraphs"
TOOLS="$ROOT/tools"
MODE="${MODE:-}"                     # "", "--fast" or "--rigorous"
PY="${PY:-python3}"
PYDBG="${PYDBG:-python3-dbg}"
# QEMU usually exposes no hardware PMU -> sample on the software timer event
PERF_EVENT="${PERF_EVENT:-cpu-clock}"
CALLGRAPH="${CALLGRAPH:-dwarf}"      # dwarf unwinding works even without frame pointers
mkdir -p "$RES" "$FG" "$TOOLS"
cd "$ROOT"                           # pyperformance creates ./venv here (git-ignored)

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }


# ---------------------------------------------------------------- 0. setup ---
if [[ -z "${SKIP_SETUP:-}" ]]; then
  log "Installing dependencies"
  sudo apt-get update -y
  sudo apt-get install -y linux-tools-common "linux-tools-$(uname -r)" \
       python3-dbg python3-pip python3-venv git iverilog || \
  sudo apt-get install -y linux-tools-generic python3-dbg python3-pip python3-venv git iverilog
  $PY -m pip install --user -U pyperformance pyperf
  $PYDBG -m pip install --user pyperf || true   # optional; profile script has a fallback
  [[ -d "$TOOLS/FlameGraph" ]] || git clone --depth 1 https://github.com/brendangregg/FlameGraph "$TOOLS/FlameGraph"
  # allow perf for a normal user (VM only!)
  sudo sysctl -w kernel.perf_event_paranoid=-1 || true
  sudo sysctl -w kernel.kptr_restrict=0 || true
fi
export PATH="$HOME/.local/bin:$PATH"

# keep the pyperformance copy of the optimized benchmark in sync
cp "$RT/optimized/run_benchmark.py" "$RT/manifest/bm_raytrace_opt/run_benchmark.py"

# ------------------------------------------------------- 1. correctness -----
log "Correctness check (original vs optimized)"
$PY "$RT/verify_raytrace.py" 100 100 | tee "$RES/verify.txt"

# ---------------------------------------------------------- 2. baseline -----
log "Baseline: pyperformance run -b raytrace $MODE"
rm -f "$RES/baseline.json"            # pyperformance refuses to overwrite
pyperformance run -b raytrace $MODE -o "$RES/baseline.json"

# --------------------------------------------------------- 3. optimized ----
log "Optimized: pyperformance run --manifest (raytrace_opt) $MODE"
rm -f "$RES/optimized.json"
pyperformance run --manifest "$RT/manifest/MANIFEST" -b raytrace_opt $MODE -o "$RES/optimized.json"

# -------------------------------------------------------- 4. comparison -----
log "Comparison"
$PY -m pyperf compare_to "$RES/baseline.json" "$RES/optimized.json" --table \
    | tee "$RES/compare.txt"

# ------------------------------------------------- 5. hardware counters -----
log "perf stat (release python3)"
EVENTS=cycles,instructions,branches,branch-misses,cache-references,cache-misses,task-clock,page-faults
for v in original optimized; do
  perf stat -r 5 -e "$EVENTS" -- $PY "$RT/profile_raytrace.py" "$v" 5 \
      2> "$RES/perf_stat_$v.txt" >/dev/null || \
  echo "perf stat failed (hardware counters may be unavailable in the VM)" >> "$RES/perf_stat_$v.txt"
  cat "$RES/perf_stat_$v.txt"
done

# --------------------------------------------------------- 6. profiling -----
# Exactly as in the course guide (Project.pdf, "Step 2"):
#   perf record -F 999 -g -- python3-dbg -m pyperformance run --bench <name>
# (plus -e cpu-clock: QEMU has no hardware PMU, so the default "cycles" event
#  records zero samples -> "Stack count is low (0)" / empty flame graph)
#   perf report --stdio > perf_report.txt
# The optimized version runs the same way through the custom manifest.
# If pyperformance cannot build its venv under python3-dbg, we fall back to
# profile_raytrace.py (same benchmark code, single process, no pyperformance).
log "perf record on $PYDBG (course guide method) + flame graphs"
# FlameGraph is a helper tool, not part of the repo: fetch it if missing
if [[ ! -x "$TOOLS/FlameGraph/flamegraph.pl" ]]; then
  echo "fetching FlameGraph into $TOOLS (not tracked by git)"
  rm -rf "$TOOLS/FlameGraph"
  git clone --depth 1 https://github.com/brendangregg/FlameGraph "$TOOLS/FlameGraph" \
    || echo "!! could not fetch FlameGraph -- flame graphs will be skipped"
fi
for v in original optimized; do
  if [[ $v == original ]]; then
    PP_ARGS=(run --bench raytrace)
  else
    PP_ARGS=(run --manifest "$RT/manifest/MANIFEST" --bench raytrace_opt)
  fi
  rm -f "$RES/dbg_$v.json"
  if ! perf record -e "$PERF_EVENT" -F 999 -g -o "$RES/perf_$v.data" -- \
        $PYDBG -m pyperformance "${PP_ARGS[@]}" --fast -o "$RES/dbg_$v.json"; then
    echo "!! pyperformance under $PYDBG failed -> fallback: profile_raytrace.py"
    perf record -e "$PERF_EVENT" -F 999 --call-graph "$CALLGRAPH" -o "$RES/perf_$v.data" \
      -- $PYDBG "$RT/profile_raytrace.py" "$v" 2
  fi
  # full report, as the guide asks
  perf report -i "$RES/perf_$v.data" --stdio > "$RES/perf_report_$v.txt" 2>/dev/null
  # compact view: self overhead per symbol, no call chains (used by the report)
  perf report -i "$RES/perf_$v.data" --stdio --no-children -g none \
      --sort dso,sym --percent-limit 0.2 > "$RES/perf_report_${v}_self.txt" 2>/dev/null
  if [[ -x "$TOOLS/FlameGraph/stackcollapse-perf.pl" ]]; then
    perf script -i "$RES/perf_$v.data" 2>/dev/null \
      | "$TOOLS/FlameGraph/stackcollapse-perf.pl" > "$RES/perf_$v.folded"
  fi
  if [[ -s "$RES/perf_$v.folded" ]]; then
    "$TOOLS/FlameGraph/flamegraph.pl" --title "raytrace ($v) - CPython internals" \
        "$RES/perf_$v.folded" > "$FG/flamegraph_raytrace_$v.svg"
  else
    echo "WARNING: no stacks recorded for $v (try CALLGRAPH=fp or PERF_EVENT=task-clock)"
  fi
done

# ---------------------------------------------------------- 7. ablation -----
log "Ablation study (optimizations added one at a time)"
rm -f "$RES/ablation.json"
$PY "$RT/ablation_raytrace.py" $MODE -o "$RES/ablation.json"
$PY - "$RES/ablation.json" <<'EOF' | tee "$RES/ablation.txt"
import sys, pyperf
suite = pyperf.BenchmarkSuite.load(sys.argv[1])
rows = [(b.get_name(), b.mean()) for b in suite.get_benchmarks()]
base = rows[0][1]
print(f"{'variant (cumulative)':34s} {'time per render':>20s} {'vs original':>12s}")
for name, t in rows:
    print(f"{name:34s} {t*1e3:17.1f} ms {base/t:11.2f}x")
EOF

# ------------------------------------------------------ 8. hardware sim -----
# V3A accelerator RTL (hw/): simulate with Icarus Verilog, check bit-exactness
# against the golden model and accuracy against the Python benchmark.
if command -v iverilog >/dev/null 2>&1; then
  log "Hardware accelerator: RTL simulation (hw/run_hw_tests.py)"
  $PY "$ROOT/hw/run_hw_tests.py" || echo "!! hardware tests failed (see output above)"
else
  echo "iverilog not found -> skipping hardware simulation (sudo apt install iverilog)"
fi

# ---------------------------------------------------- 9. call counts -----
log "Python calls / object allocations per render (original vs optimized)"
$PY "$RT/callcount_raytrace.py" > "$RES/callcount.txt" && cat "$RES/callcount.txt"

log "Done. Results in $RES, flame graphs in $FG"
