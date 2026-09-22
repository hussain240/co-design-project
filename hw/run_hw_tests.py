"""Run the V3A hardware tests end to end.

  1. regenerate the invsqrt ROM include from the golden model
  2. build test vectors from the REAL benchmark code:
       nbody   : the 5 Jovian bodies after offset_momentum(), dt = 0.01
       ray0    : primary camera rays of the raytrace scene vs its 7 spheres
       ray1    : shadow rays (hit point -> each light) vs the 7 spheres
  3. compile + simulate the RTL with Icarus Verilog (tb/tb_v3a.v)
  4. check  RTL == golden fixed-point model   (must be bit-exact)
     check  fixed point vs original double-precision benchmark (accuracy)
  5. print cycle counts -> throughput numbers used in the report

usage: python3 hw/run_hw_tests.py [--steps N] [--grid G]
"""
import argparse, importlib.util, math, os, subprocess, sys, time, types

HW = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HW)
SIM = os.path.join(HW, "sim")
sys.path.insert(0, os.path.join(HW, "model"))
import v3a_model as M                                            # noqa: E402

if "pyperf" not in sys.modules:
    sys.modules["pyperf"] = types.SimpleNamespace(perf_counter=time.perf_counter)


def load(tag, rel):
    spec = importlib.util.spec_from_file_location(tag, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_hex(path, words):
    with open(path, "w") as f:
        for w in words:
            f.write(M.to_hex(w) + "\n")


def read_hex(path):
    return [M.wrap(int(x, 16)) for x in open(path).read().split()]


# ------------------------------------------------------------------- nbody ---
def nbody_vectors(steps):
    nb = load("nb_orig", "benchmarks/nbody/original/run_benchmark.py")
    nb.offset_momentum(nb.BODIES["sun"])
    dt = 0.01
    bodies_f = [(list(r), list(v), m) for r, v, m in nb.SYSTEM]
    fx = [[M.to_fx(r[0]), M.to_fx(r[1]), M.to_fx(r[2]),
           M.to_fx(v[0]), M.to_fx(v[1]), M.to_fx(v[2]), M.to_fx(m * dt)] for r, v, m in bodies_f]
    words = [len(fx), steps, M.to_fx(dt)] + [w for b in fx for w in b]
    write_hex(os.path.join(SIM, "nbody_in.hex"), words)
    golden = M.nbody_run([b[:] for b in fx], M.to_fx(dt), steps)
    e0 = nb.report_energy()
    nb.advance(dt, steps)                                        # float reference
    e1 = nb.report_energy()
    return nb, golden, e0, e1


def energy_of(nb, fx_bodies, dt=0.01):
    """Energy of a fixed-point state, using the benchmark's own formula."""
    system = [([M.from_fx(b[0]), M.from_fx(b[1]), M.from_fx(b[2])],
               [M.from_fx(b[3]), M.from_fx(b[4]), M.from_fx(b[5])],
               M.from_fx(b[6]) / dt) for b in fx_bodies]
    return nb.report_energy(system, nb.combinations(system))


# --------------------------------------------------------------------- rays ---
def ray_vectors(grid):
    rt = load("rt_orig", "benchmarks/raytrace/original/run_benchmark.py")
    s = rt.Scene()
    s.addLight(rt.Point(30, 30, 10))
    s.addLight(rt.Point(-10, 100, 30))
    s.lookAt(rt.Point(0, 3, 0))
    s.addObject(rt.Sphere(rt.Point(1, 3, -10), 2), rt.SimpleSurface(baseColour=(1, 1, 0)))
    for y in range(6):
        s.addObject(rt.Sphere(rt.Point(-3 - y * 0.4, 2.3, -5), 0.4),
                    rt.SimpleSurface(baseColour=(y / 6.0, 1 - y / 6.0, 0.5)))
    s.addObject(rt.Halfspace(rt.Point(0, 0, 0), rt.Vector.UP), rt.CheckerboardSurface())
    spheres = [o for o, _ in s.objects if isinstance(o, rt.Sphere)]
    sph_fx = [[M.to_fx(o.centre.x), M.to_fx(o.centre.y), M.to_fx(o.centre.z),
               M.to_fx(o.radius * o.radius)] for o in spheres]
    eps = rt.EPSILON

    # primary rays exactly as Scene.render() builds them (100x100 image, sub-sampled)
    W = H = 100
    fov = math.pi * (s.fieldOfView / 2.0) / 180.0
    hw = math.tan(fov); hh = 0.75 * hw
    pw, ph = hw * 2 / (W - 1), hh * 2 / (H - 1)
    eye = rt.Ray(s.position, s.lookingAt - s.position)
    vr = eye.vector.cross(rt.Vector.UP).normalized()
    vu = vr.cross(eye.vector).normalized()
    prim = []
    step = max(1, W // grid)
    for y in range(0, H, step):
        for x in range(0, W, step):
            prim.append(rt.Ray(eye.point, eye.vector + vr.scale(x * pw - hw) + vu.scale(y * ph - hh)))

    def closest_float(ray):
        best_i, best_t = -1, None
        for i, o in enumerate(spheres):
            t = o.intersectionTime(ray)
            if t is not None and t > -eps and (best_i < 0 or t < best_t):
                best_i, best_t = i, t
        return best_i, best_t

    ref0 = [closest_float(r) for r in prim]

    # shadow rays from every sphere or floor hit point towards both lights
    shadow, ref1 = [], []
    floor = [o for o, _ in s.objects if isinstance(o, rt.Halfspace)][0]
    for r, (i, t) in zip(prim, ref0):
        if i >= 0:
            p = r.pointAtTime(t)
        else:
            tf = floor.intersectionTime(r)
            if tf is None or tf <= eps:
                continue
            p = r.pointAtTime(tf)
        for l in s.lightPoints:
            sr = rt.Ray(p, l - p)
            occ = any((o.intersectionTime(sr) or -1) > eps for o in spheres)
            shadow.append(sr)
            ref1.append(1 if occ else 0)

    def ray_words(rays):
        return [w for r in rays for w in (M.to_fx(r.point.x), M.to_fx(r.point.y), M.to_fx(r.point.z),
                                          M.to_fx(r.vector.x), M.to_fx(r.vector.y), M.to_fx(r.vector.z))]

    write_hex(os.path.join(SIM, "ray0_in.hex"),
              [len(prim), len(sph_fx), M.to_fx(eps)] + [w for sp in sph_fx for w in sp] + ray_words(prim))
    write_hex(os.path.join(SIM, "ray1_in.hex"),
              [len(shadow), len(sph_fx), M.to_fx(eps)] + [w for sp in sph_fx for w in sp] + ray_words(shadow))

    def fx_rays(rays):
        return [[M.to_fx(r.point.x), M.to_fx(r.point.y), M.to_fx(r.point.z),
                 M.to_fx(r.vector.x), M.to_fx(r.vector.y), M.to_fx(r.vector.z)] for r in rays]

    gold0 = M.ray_batch(fx_rays(prim), sph_fx, M.to_fx(eps), 0)
    gold1 = M.ray_batch(fx_rays(shadow), sph_fx, M.to_fx(eps), 1)
    return len(sph_fx), prim, ref0, gold0, shadow, ref1, gold1


# --------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=2000, help="nbody time steps to simulate")
    ap.add_argument("--grid", type=int, default=50, help="primary rays per image side")
    args = ap.parse_args()
    os.makedirs(SIM, exist_ok=True)
    M.write_lut_vh(os.path.join(HW, "rtl", "v3a_invsqrt_lut.vh"))

    print("== generating vectors from the benchmark code")
    nb, gold_nb, e0, e1 = nbody_vectors(args.steps)
    nsph, prim, ref0, gold0, shadow, ref1, gold1 = ray_vectors(args.grid)

    print("== compiling + simulating RTL (Icarus Verilog)")
    rtl = [os.path.join(HW, "rtl", f) for f in
           ("v3a_delay.v", "v3a_invsqrt.v", "v3a_pair_pipe.v", "v3a_raysphere_pipe.v",
            "v3a_nbody_ctrl.v", "v3a_ray_ctrl.v", "v3a_top.v")]
    vvp = os.path.join(SIM, "tb_v3a.vvp")
    subprocess.run(["iverilog", "-g2012", "-I", os.path.join(HW, "rtl"), "-o", vvp,
                    os.path.join(HW, "tb", "tb_v3a.v")] + rtl, check=True)
    t0 = time.time()
    out = subprocess.run(["vvp", "-n", vvp], cwd=HW, check=True, capture_output=True, text=True).stdout
    print(out.strip())
    print(f"   (simulation wall time {time.time() - t0:.1f} s)")

    ok = True
    lines = []
    P = lines.append

    # ---- nbody checks
    rtl_nb = read_hex(os.path.join(SIM, "nbody_out.hex"))
    cyc_nb, rtl_state = rtl_nb[0], [rtl_nb[1 + 7 * k: 8 + 7 * k] for k in range(len(gold_nb))]
    exact_nb = rtl_state == gold_nb
    ok &= exact_nb
    e_fx = energy_of(nb, rtl_state)
    maxpos = max(abs(M.from_fx(rtl_state[k][c]) - nb.SYSTEM[k][0][c])
                 for k in range(len(gold_nb)) for c in range(3))
    npairs = len(gold_nb) * (len(gold_nb) - 1) // 2
    P(f"nbody  : {len(gold_nb)} bodies, {args.steps} steps, {npairs} pairs/step")
    P(f"  RTL vs golden fixed-point model: {'BIT-EXACT' if exact_nb else 'MISMATCH'}")
    P(f"  energy: float benchmark {e1:.12f}, hardware {e_fx:.12f}")
    P(f"          relative difference {abs(e_fx - e1) / abs(e1):.2e}")
    P(f"  max |position diff| vs float benchmark: {maxpos:.2e}")
    P(f"  cycles: {cyc_nb} = {cyc_nb / args.steps:.1f} per step ({npairs} pair feeds +")
    P(f"          19 latency + {len(gold_nb)} position updates + control)")

    # ---- ray checks
    for mode, rays, ref, gold, fname, label in (
            (0, prim, ref0, gold0, "ray0_out.hex", "closest hit, primary rays"),
            (1, shadow, ref1, gold1, "ray1_out.hex", "any hit, shadow rays")):
        rr = read_hex(os.path.join(SIM, fname))
        cyc, res = rr[0], [(rr[1 + 2 * i], rr[2 + 2 * i]) for i in range(len(rays))]
        exact = res == gold
        ok &= exact
        if mode == 0:
            agree = sum(1 for (hi, _), (fi, _) in zip(res, ref) if hi == fi)
            terr = max([abs(M.from_fx(ht) - ft) for (hi, ht), (fi, ft) in zip(res, ref) if hi == fi >= 0] or [0])
            hits = sum(1 for fi, _ in ref if fi >= 0)
            extra = (f"closest sphere == float benchmark: {agree}/{len(rays)} rays\n"
                     f"  ({hits} hits), max |t error| {terr:.2e}")
        else:
            agree = sum(1 for (hi, _), fo in zip(res, ref) if hi == fo)
            occl = sum(ref)
            extra = (f"shadow decision == float benchmark: {agree}/{len(rays)} rays\n"
                     f"  ({occl} occluded)")
        tests = len(rays) * nsph
        P(f"ray    : {label}")
        P(f"  {len(rays)} rays x {nsph} spheres = {tests} tests")
        P(f"  RTL vs golden fixed-point model: {'BIT-EXACT' if exact else 'MISMATCH'}")
        P(f"  {extra}")
        P(f"  cycles: {cyc} = {cyc / tests:.3f} per test (+19 latency, +1 BRAM read)")

    P(f"RESULT: {'PASS' if ok else 'FAIL'}")
    txt = "\n".join(l for x in lines for l in x.split("\n"))
    print("== results\n" + txt)
    with open(os.path.join(HW, "sim", "results.txt"), "w") as f:
        f.write(txt + "\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
