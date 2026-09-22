"""Run the benchmark body directly (no pyperf worker processes) so that
`perf stat` / py-spy see one clean process. Works without pyperf installed.

usage: python3 profile_raytrace.py {original|optimized} [loops] [width] [height]
"""
import importlib.util, os, sys, time, types

if "pyperf" not in sys.modules:
    try:
        import pyperf  # noqa: F401
    except ImportError:
        sys.modules["pyperf"] = types.SimpleNamespace(perf_counter=time.perf_counter)

HERE = os.path.dirname(os.path.abspath(__file__))
which = sys.argv[1] if len(sys.argv) > 1 else "original"
loops = int(sys.argv[2]) if len(sys.argv) > 2 else 5
w = int(sys.argv[3]) if len(sys.argv) > 3 else 100
h = int(sys.argv[4]) if len(sys.argv) > 4 else 100

spec = importlib.util.spec_from_file_location("bm", os.path.join(HERE, which, "run_benchmark.py"))
bm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bm)
bm.pyperf = sys.modules["pyperf"]
t = bm.bench_raytrace(loops, w, h, None)
print(f"{which}: {loops} loops of {w}x{h} -> {t:.3f} s")
