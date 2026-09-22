"""Correctness check: original vs optimized must produce the same physics.

Runs both implementations for N steps from the same initial state and compares
final energy and every position/velocity component. Tiny differences (~1e-15)
are expected: O1 computes (m*dt)*mag instead of m*(dt*mag), and IEEE-754
multiplication is not associative.
"""
import importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def simulate(mod, steps):
    mod.offset_momentum(mod.BODIES['sun'])
    e0 = mod.report_energy()
    mod.advance(0.01, steps)
    return e0, mod.report_energy(), [(list(r), list(v)) for r, v, _ in mod.SYSTEM]

if __name__ == "__main__":
    steps = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    orig = load("orig", os.path.join(HERE, "original", "run_benchmark.py"))
    opt = load("opt", os.path.join(HERE, "optimized", "run_benchmark.py"))
    e0a, e1a, sa = simulate(orig, steps)
    e0b, e1b, sb = simulate(opt, steps)
    worst = max(abs(a - b) for (ra, va), (rb, vb) in zip(sa, sb)
                for a, b in zip(ra + va, rb + vb))
    print(f"steps={steps}")
    print(f"energy before : original={e0a!r}  optimized={e0b!r}")
    print(f"energy after  : original={e1a!r}  optimized={e1b!r}")
    print(f"|dE|={abs(e1a - e1b):.3e}   max |state diff|={worst:.3e}")
    ok = abs(e1a - e1b) < 1e-12 and worst < 1e-9
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
