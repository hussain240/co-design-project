"""Run the benchmark body directly (no pyperf worker processes) so that
`perf record` sees one clean process. Works under python3-dbg even if pyperf
is not installed for it.

usage: python3-dbg profile_nbody.py {original|optimized} [loops] [iterations]
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
iters = int(sys.argv[3]) if len(sys.argv) > 3 else 20000

spec = importlib.util.spec_from_file_location("bm", os.path.join(HERE, which, "run_benchmark.py"))
bm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bm)
bm.pyperf = sys.modules["pyperf"]
t = bm.bench_nbody(loops, "sun", iters)
print(f"{which}: {loops} loops x {iters} iterations -> {t:.3f} s")
