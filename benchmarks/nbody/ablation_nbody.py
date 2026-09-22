"""Ablation study: measure each optimization step separately with pyperf.

  v0_original      pyperformance code as-is
  v1_sqrt          x**-1.5  ->  1/(d2*sqrt(d2))           (rejected on 3.10)
  v2_mdt           O1: precompute m*dt
  v3_locals        O1+O2+O3: specialized code, state in locals (final version)
  v4_numpy         vectorized numpy version                 (rejected)

usage: python3 ablation_nbody.py -o results/ablation.json [--rigorous]
       python3 -m pyperf compare_to results/ablation.json --table  (not needed; see stats)
"""
import importlib.util, os, sys
from math import sqrt
import pyperf

HERE = os.path.dirname(os.path.abspath(__file__))

def fresh_state():
    spec = importlib.util.spec_from_file_location("orig", os.path.join(HERE, "original", "run_benchmark.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m.offset_momentum(m.BODIES["sun"])
    return m

def v0_original(dt, n, bodies, pairs):
    for i in range(n):
        for (([x1, y1, z1], v1, m1), ([x2, y2, z2], v2, m2)) in pairs:
            dx = x1 - x2; dy = y1 - y2; dz = z1 - z2
            mag = dt * ((dx * dx + dy * dy + dz * dz) ** (-1.5))
            b1m = m1 * mag; b2m = m2 * mag
            v1[0] -= dx * b2m; v1[1] -= dy * b2m; v1[2] -= dz * b2m
            v2[0] += dx * b1m; v2[1] += dy * b1m; v2[2] += dz * b1m
        for (r, [vx, vy, vz], m) in bodies:
            r[0] += dt * vx; r[1] += dt * vy; r[2] += dt * vz

def v1_sqrt(dt, n, bodies, pairs, sqrt=sqrt):
    for i in range(n):
        for (([x1, y1, z1], v1, m1), ([x2, y2, z2], v2, m2)) in pairs:
            dx = x1 - x2; dy = y1 - y2; dz = z1 - z2
            d2 = dx * dx + dy * dy + dz * dz
            mag = dt / (d2 * sqrt(d2))
            b1m = m1 * mag; b2m = m2 * mag
            v1[0] -= dx * b2m; v1[1] -= dy * b2m; v1[2] -= dz * b2m
            v2[0] += dx * b1m; v2[1] += dy * b1m; v2[2] += dz * b1m
        for (r, [vx, vy, vz], m) in bodies:
            r[0] += dt * vx; r[1] += dt * vy; r[2] += dt * vz

def v2_mdt(dt, n, bodies, pairs):
    p2 = [(r1, v1, m1 * dt, r2, v2, m2 * dt) for ((r1, v1, m1), (r2, v2, m2)) in pairs]
    for i in range(n):
        for ([x1, y1, z1], v1, m1, [x2, y2, z2], v2, m2) in p2:
            dx = x1 - x2; dy = y1 - y2; dz = z1 - z2
            mag = (dx * dx + dy * dy + dz * dz) ** (-1.5)
            b1m = m1 * mag; b2m = m2 * mag
            v1[0] -= dx * b2m; v1[1] -= dy * b2m; v1[2] -= dz * b2m
            v2[0] += dx * b1m; v2[1] += dy * b1m; v2[2] += dz * b1m
        for (r, [vx, vy, vz], m) in bodies:
            r[0] += dt * vx; r[1] += dt * vy; r[2] += dt * vz

_spec = importlib.util.spec_from_file_location("opt", os.path.join(HERE, "optimized", "run_benchmark.py"))
_opt = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_opt)
def v3_locals(dt, n, bodies, pairs):
    _opt._advance_specialized(dt, n, bodies)

def v4_numpy(dt, n, bodies, pairs):
    import numpy as np
    r = np.array([b[0] for b in bodies]); v = np.array([b[1] for b in bodies])
    m = np.array([b[2] for b in bodies]); I, J = np.triu_indices(len(bodies), 1)
    mI, mJ = m[I][:, None], m[J][:, None]
    for _ in range(n):
        d = r[I] - r[J]
        mag = (dt * ((d * d).sum(1)) ** -1.5)[:, None]
        np.subtract.at(v, I, d * (mJ * mag))
        np.add.at(v, J, d * (mI * mag))
        r += dt * v
    for k, b in enumerate(bodies):
        b[0][:] = r[k].tolist(); b[1][:] = v[k].tolist()

VARIANTS = [v0_original, v1_sqrt, v2_mdt, v3_locals]
try:
    import numpy  # noqa: F401
    VARIANTS.append(v4_numpy)
except ImportError:
    pass

def bench(loops, fn, iterations):
    st = fresh_state()
    t0 = pyperf.perf_counter()
    for _ in range(loops):
        st.report_energy(); fn(0.01, iterations, st.SYSTEM, st.PAIRS); st.report_energy()
    return pyperf.perf_counter() - t0

if __name__ == "__main__":
    runner = pyperf.Runner()
    for fn in VARIANTS:
        iters = 2000 if fn.__name__ == "v4_numpy" else 20000   # numpy is ~4x slower; keep runtime sane
        runner.bench_time_func(f"nbody_{fn.__name__}_{iters}it", bench, fn, iters)
