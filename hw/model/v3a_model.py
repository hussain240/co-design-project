"""V3A -- 3D Vector-math Accelerator: bit-accurate golden model.

This model defines the EXACT arithmetic the RTL implements (same fixed-point
format, same truncation, same inverse-square-root algorithm), so RTL outputs
must match it bit-for-bit. It is also used to measure how close the fixed-point
hardware results are to the double-precision Python benchmarks.

Number format: signed Q23.40 in 64 bits (W=64, F=40)
  range  +- 8.4e6, resolution 9.1e-13
"""
import math

W = 64
F = 40
ONE = 1 << F
MASK = (1 << W) - 1
THREE = 3 << F
LUT_BITS = 6
NEWTON_ITERS = 3


# ------------------------------------------------------------------ basics ---
def wrap(x):
    """Two's-complement wrap to W bits (what a W-bit register holds)."""
    x &= MASK
    return x - (1 << W) if x >> (W - 1) else x


def to_fx(v):
    return wrap(int(round(v * ONE)))


def from_fx(x):
    return x / ONE


def fx_mul(a, b):
    """Signed W x W multiply, arithmetic shift right by F (floor), keep W bits.
    RTL: prod = $signed(a) * $signed(b);  res = prod >>> F;  res[W-1:0]"""
    return wrap((a * b) >> F)


def to_hex(x):
    return f"{x & MASK:016x}"


# --------------------------------------------------------- inverse sqrt -----
def lut_entry(idx):
    """Initial guess ROM: idx = top 6 bits of the normalized m in [1,4)."""
    if idx < 16:
        return ONE
    mid = (idx + 0.5) / 16.0
    return to_fx(1.0 / math.sqrt(mid))


LUT = [lut_entry(i) for i in range(1 << LUT_BITS)]


def normalize(x):
    """x > 0  ->  (m, k) with m in [2^F, 2^(F+2)) and x = m * 4^k.
    x <= 0 ->  (ONE, 0) and valid = False (result is don't-care)."""
    if x <= 0:
        return ONE, 0, False
    p = x.bit_length() - 1          # index of the leading one (RTL: priority encoder)
    k = (p - F) >> 1                 # floor((p - F) / 2)
    m = x >> (2 * k) if k >= 0 else x << (-2 * k)
    return m, k, True


def invsqrt(x):
    m, k, ok = normalize(x)
    y = LUT[(m >> (F + 2 - LUT_BITS)) & ((1 << LUT_BITS) - 1)]
    for _ in range(NEWTON_ITERS):
        y2 = fx_mul(y, y)
        t = fx_mul(m, y2)
        y = fx_mul(y, wrap(THREE - t)) >> 1
    return (y >> k) if k >= 0 else wrap(y << (-k))


# ---------------------------------------------------- kernel 1: nbody pair --
def pair_force(xi, yi, zi, xj, yj, zj, mdti, mdtj):
    """Returns (fi, fj): fi = d*b2m (subtract from v_i), fj = d*b1m (add to v_j)."""
    dx, dy, dz = wrap(xi - xj), wrap(yi - yj), wrap(zi - zj)
    d2 = wrap(fx_mul(dx, dx) + fx_mul(dy, dy) + fx_mul(dz, dz))
    y = invsqrt(d2)
    mag = fx_mul(fx_mul(y, y), y)                      # d2^-1.5
    b1m, b2m = fx_mul(mdti, mag), fx_mul(mdtj, mag)
    fi = (fx_mul(dx, b2m), fx_mul(dy, b2m), fx_mul(dz, b2m))
    fj = (fx_mul(dx, b1m), fx_mul(dy, b1m), fx_mul(dz, b1m))
    return fi, fj


def nbody_run(bodies, dt, steps):
    """bodies: list of [x,y,z,vx,vy,vz,mdt] in fixed point (modified in place).
    One step = all pair forces from the SAME positions, accumulated per body,
    then v += acc, then r += dt*v  (what the RTL controller does)."""
    n = len(bodies)
    for _ in range(steps):
        acc = [[0, 0, 0] for _ in range(n)]
        for i in range(n - 1):
            for j in range(i + 1, n):
                bi, bj = bodies[i], bodies[j]
                fi, fj = pair_force(bi[0], bi[1], bi[2], bj[0], bj[1], bj[2], bi[6], bj[6])
                for c in range(3):
                    acc[i][c] = wrap(acc[i][c] - fi[c])
                    acc[j][c] = wrap(acc[j][c] + fj[c])
        for k in range(n):
            for c in range(3):
                bodies[k][3 + c] = wrap(bodies[k][3 + c] + acc[k][c])
        for k in range(n):
            for c in range(3):
                bodies[k][c] = wrap(bodies[k][c] + fx_mul(dt, bodies[k][3 + c]))
    return bodies


# ------------------------------------------------- kernel 2: ray-sphere -----
def ray_sphere(px, py, pz, dx, dy, dz, cx, cy, cz, r2):
    """Returns (disc, t) exactly like Sphere.intersectionTime (hit iff disc >= 0)."""
    ex, ey, ez = wrap(cx - px), wrap(cy - py), wrap(cz - pz)
    v = wrap(fx_mul(ex, dx) + fx_mul(ey, dy) + fx_mul(ez, dz))
    cc = wrap(fx_mul(ex, ex) + fx_mul(ey, ey) + fx_mul(ez, ez))
    disc = wrap(r2 - wrap(cc - fx_mul(v, v)))
    s = fx_mul(disc, invsqrt(disc))                    # sqrt(disc) = disc / sqrt(disc)
    return disc, wrap(v - s)


def ray_batch(rays, spheres, eps, mode):
    """mode 0 = closest hit (t > -eps, smallest t) -> (index or -1, t)
       mode 1 = any hit   (t >  eps)              -> (1 if occluded else 0, 0)"""
    out = []
    for r in rays:
        best_i, best_t = -1, 0
        for s_idx, s in enumerate(spheres):
            disc, t = ray_sphere(*r, *s)
            if disc < 0:
                continue
            if mode == 0:
                if t > -eps and (best_i < 0 or t < best_t):
                    best_i, best_t = s_idx, t
            else:
                if t > eps:
                    best_i, best_t = 1, 0
        if mode == 1 and best_i < 0:
            best_i = 0
        out.append((best_i, best_t))
    return out


# --------------------------------------------------------------- ROM file ---
def write_lut_vh(path):
    with open(path, "w") as f:
        f.write("// GENERATED by hw/model/v3a_model.py -- initial-guess ROM for v3a_invsqrt\n")
        f.write("// entry = 1/sqrt((idx+0.5)/16) in Q23.40, idx = top 6 bits of m in [1,4)\n")
        f.write("function [63:0] lut_rom;\n  input [5:0] idx;\n  begin\n    case (idx)\n")
        for i, v in enumerate(LUT):
            f.write(f"      6'd{i}: lut_rom = 64'h{to_hex(v)};\n")
        f.write("      default: lut_rom = 64'h0;\n    endcase\n  end\nendfunction\n")


if __name__ == "__main__":
    import os, random
    here = os.path.dirname(os.path.abspath(__file__))
    write_lut_vh(os.path.join(here, "..", "rtl", "v3a_invsqrt_lut.vh"))
    # self-test of invsqrt accuracy over a wide range
    worst = 0.0
    rnd = random.Random(1)
    for _ in range(20000):
        x = 10 ** rnd.uniform(-6, 6)
        got = from_fx(invsqrt(to_fx(x)))
        worst = max(worst, abs(got * math.sqrt(x) - 1.0))
    print(f"invsqrt: worst relative error over 1e-6..1e6 = {worst:.2e}")
