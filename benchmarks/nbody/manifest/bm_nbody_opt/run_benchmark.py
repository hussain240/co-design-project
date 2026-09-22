"""
N-body benchmark -- OPTIMIZED version (HWSW co-design project).

Same workload and same physics as pyperformance's bm_nbody
(original: benchmarks/nbody/original/run_benchmark.py).

What changed and why (measurements in report_nbody.txt):

  O1  Precompute m*dt once per body instead of multiplying by dt for every
      pair on every step. Saves one boxed-float multiply per pair per step.

  O2  Data-layout change: body state moves out of nested Python lists
      ([x,y,z], [vx,vy,vz], m) into plain local variables (x0, y0, ..., vz4).
      In CPython every `v1[0] -= ...` costs BINARY_SUBSCR + INPLACE_* +
      STORE_SUBSCR (type dispatch, bounds check, refcounting), and every pair
      iteration costs FOR_ITER + 3x UNPACK_SEQUENCE. Locals are just
      LOAD_FAST/STORE_FAST on the frame's fast-locals array.

  O3  Loop unrolling / specialization: the number of bodies is fixed for the
      whole run, so the 10 pair interactions are emitted as straight-line code
      (no inner `for` over PAIRS). The specialized function is generated ONCE
      at import time for the actual number of bodies (works for any N), so no
      code generation happens inside the timed region.

Run `python3 run_benchmark.py --dump-generated` to print the generated code.
"""

import sys

try:
    import pyperf
except ImportError:          # lets profile_nbody.py run under python3-dbg
    pyperf = None

__contact__ = "collinwinter@google.com (Collin Winter)"
DEFAULT_ITERATIONS = 20000
DEFAULT_REFERENCE = 'sun'


def combinations(l):
    """Pure-Python implementation of itertools.combinations(l, 2)."""
    result = []
    for x in range(len(l) - 1):
        ls = l[x + 1:]
        for y in ls:
            result.append((l[x], y))
    return result


PI = 3.14159265358979323
SOLAR_MASS = 4 * PI * PI
DAYS_PER_YEAR = 365.24

BODIES = {
    'sun': ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0], SOLAR_MASS),

    'jupiter': ([4.84143144246472090e+00,
                 -1.16032004402742839e+00,
                 -1.03622044471123109e-01],
                [1.66007664274403694e-03 * DAYS_PER_YEAR,
                 7.69901118419740425e-03 * DAYS_PER_YEAR,
                 -6.90460016972063023e-05 * DAYS_PER_YEAR],
                9.54791938424326609e-04 * SOLAR_MASS),

    'saturn': ([8.34336671824457987e+00,
                4.12479856412430479e+00,
                -4.03523417114321381e-01],
               [-2.76742510726862411e-03 * DAYS_PER_YEAR,
                4.99852801234917238e-03 * DAYS_PER_YEAR,
                2.30417297573763929e-05 * DAYS_PER_YEAR],
               2.85885980666130812e-04 * SOLAR_MASS),

    'uranus': ([1.28943695621391310e+01,
                -1.51111514016986312e+01,
                -2.23307578892655734e-01],
               [2.96460137564761618e-03 * DAYS_PER_YEAR,
                2.37847173959480950e-03 * DAYS_PER_YEAR,
                -2.96589568540237556e-05 * DAYS_PER_YEAR],
               4.36624404335156298e-05 * SOLAR_MASS),

    'neptune': ([1.53796971148509165e+01,
                 -2.59193146099879641e+01,
                 1.79258772950371181e-01],
                [2.68067772490389322e-03 * DAYS_PER_YEAR,
                 1.62824170038242295e-03 * DAYS_PER_YEAR,
                 -9.51592254519715870e-05 * DAYS_PER_YEAR],
                5.15138902046611451e-05 * SOLAR_MASS)}


SYSTEM = list(BODIES.values())
PAIRS = combinations(SYSTEM)


def generate_advance_source(nbodies):
    """Emit a specialized advance() for a fixed number of bodies (O1+O2+O3)."""
    L = ["def advance_specialized(dt, n, bodies):"]
    # load state into locals + precompute m*dt  (O1, O2)
    for k in range(nbodies):
        L.append(f"    (x{k}, y{k}, z{k}), (vx{k}, vy{k}, vz{k}), m{k} = bodies[{k}]")
        L.append(f"    mdt{k} = m{k} * dt")
    L.append("    for _ in range(n):")
    # unrolled pair interactions  (O3)
    for i in range(nbodies):
        for j in range(i + 1, nbodies):
            L.append(f"        # pair ({i},{j})")
            L.append(f"        dx = x{i} - x{j}")
            L.append(f"        dy = y{i} - y{j}")
            L.append(f"        dz = z{i} - z{j}")
            L.append("        mag = (dx * dx + dy * dy + dz * dz) ** (-1.5)")
            L.append(f"        b1m = mdt{i} * mag")
            L.append(f"        b2m = mdt{j} * mag")
            L.append(f"        vx{i} -= dx * b2m")
            L.append(f"        vy{i} -= dy * b2m")
            L.append(f"        vz{i} -= dz * b2m")
            L.append(f"        vx{j} += dx * b1m")
            L.append(f"        vy{j} += dy * b1m")
            L.append(f"        vz{j} += dz * b1m")
    L.append("        # position update")
    for k in range(nbodies):
        L.append(f"        x{k} += dt * vx{k}")
        L.append(f"        y{k} += dt * vy{k}")
        L.append(f"        z{k} += dt * vz{k}")
    # write state back once, so report_energy() and later calls see it
    for k in range(nbodies):
        L.append(f"    r, v, _ = bodies[{k}]")
        L.append(f"    r[0] = x{k}; r[1] = y{k}; r[2] = z{k}")
        L.append(f"    v[0] = vx{k}; v[1] = vy{k}; v[2] = vz{k}")
    return "\n".join(L) + "\n"


def _compile_specialized(nbodies):
    ns = {}
    exec(compile(generate_advance_source(nbodies), "<advance_specialized>", "exec"), ns)
    return ns["advance_specialized"]


# generated once per body count, at import time for the benchmark's own system,
# so nothing is compiled inside the timed region (and a different number of
# bodies still works: it is compiled once, on the first call with that count)
_SPECIALIZED = {len(SYSTEM): _compile_specialized(len(SYSTEM))}
_advance_specialized = _SPECIALIZED[len(SYSTEM)]


def advance(dt, n, bodies=SYSTEM, pairs=PAIRS):
    fn = _SPECIALIZED.get(len(bodies))
    if fn is None:
        fn = _SPECIALIZED[len(bodies)] = _compile_specialized(len(bodies))
    fn(dt, n, bodies)


def report_energy(bodies=SYSTEM, pairs=PAIRS, e=0.0):
    for (((x1, y1, z1), v1, m1),
         ((x2, y2, z2), v2, m2)) in pairs:
        dx = x1 - x2
        dy = y1 - y2
        dz = z1 - z2
        e -= (m1 * m2) / ((dx * dx + dy * dy + dz * dz) ** 0.5)
    for (r, [vx, vy, vz], m) in bodies:
        e += m * (vx * vx + vy * vy + vz * vz) / 2.
    return e


def offset_momentum(ref, bodies=SYSTEM, px=0.0, py=0.0, pz=0.0):
    for (r, [vx, vy, vz], m) in bodies:
        px -= vx * m
        py -= vy * m
        pz -= vz * m
    (r, v, m) = ref
    v[0] = px / m
    v[1] = py / m
    v[2] = pz / m


def bench_nbody(loops, reference, iterations):
    # Set up global state
    offset_momentum(BODIES[reference])

    range_it = range(loops)
    t0 = pyperf.perf_counter()

    for _ in range_it:
        report_energy()
        advance(0.01, iterations)
        report_energy()

    return pyperf.perf_counter() - t0


def add_cmdline_args(cmd, args):
    cmd.extend(("--iterations", str(args.iterations)))


if __name__ == '__main__':
    if "--dump-generated" in sys.argv:
        print(generate_advance_source(len(SYSTEM)))
        sys.exit(0)
    runner = pyperf.Runner(add_cmdline_args=add_cmdline_args)
    runner.metadata['description'] = "n-body benchmark (optimized)"
    runner.argparser.add_argument("--iterations",
                                  type=int, default=DEFAULT_ITERATIONS,
                                  help="Number of nbody advance() iterations "
                                       "(default: %s)" % DEFAULT_ITERATIONS)
    runner.argparser.add_argument("--reference",
                                  type=str, default=DEFAULT_REFERENCE,
                                  help="nbody reference (default: %s)"
                                       % DEFAULT_REFERENCE)

    args = runner.parse_args()
    runner.bench_time_func('nbody', bench_nbody,
                           args.reference, args.iterations)
