"""Correctness check: the optimized raytracer must render a BIT-IDENTICAL image.

Renders the benchmark scene with the original and the optimized code and
compares every byte of the RGB canvas (and its SHA-256). Optionally also at a
larger resolution to exercise more rays.

usage: python3 verify_raytrace.py [width height]   (default 100 100)
"""
import hashlib, importlib.util, os, sys, time, types

if "pyperf" not in sys.modules:
    try:
        import pyperf  # noqa: F401
    except ImportError:
        sys.modules["pyperf"] = types.SimpleNamespace(perf_counter=time.perf_counter)

HERE = os.path.dirname(os.path.abspath(__file__))


def load(tag, path):
    spec = importlib.util.spec_from_file_location(tag, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def render(mod, w, h):
    canvas = mod.Canvas(w, h)
    s = mod.Scene()
    s.addLight(mod.Point(30, 30, 10))
    s.addLight(mod.Point(-10, 100, 30))
    s.lookAt(mod.Point(0, 3, 0))
    s.addObject(mod.Sphere(mod.Point(1, 3, -10), 2), mod.SimpleSurface(baseColour=(1, 1, 0)))
    for y in range(6):
        s.addObject(mod.Sphere(mod.Point(-3 - y * 0.4, 2.3, -5), 0.4),
                    mod.SimpleSurface(baseColour=(y / 6.0, 1 - y / 6.0, 0.5)))
    s.addObject(mod.Halfspace(mod.Point(0, 0, 0), mod.Vector.UP), mod.CheckerboardSurface())
    s.render(canvas)
    return canvas.bytes.tobytes()


if __name__ == "__main__":
    w = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    h = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    orig = load("rt_orig", os.path.join(HERE, "original", "run_benchmark.py"))
    opt = load("rt_opt", os.path.join(HERE, "optimized", "run_benchmark.py"))
    a, b = render(orig, w, h), render(opt, w, h)
    diff = sum(1 for x, y in zip(a, b) if x != y)
    print(f"image {w}x{h} ({len(a)} bytes)")
    print(f"sha256 original : {hashlib.sha256(a).hexdigest()}")
    print(f"sha256 optimized: {hashlib.sha256(b).hexdigest()}")
    print(f"differing bytes : {diff}")
    ok = a == b
    # every intermediate ablation stage must also be bit-identical
    sys.path.insert(0, HERE)
    import variants_raytrace as V
    for stage, _ in V.STAGES:
        same = render(V.build(stage), w, h) == a
        ok = ok and same
        print(f"ablation stage {stage:14s}: {'identical' if same else 'DIFFERENT'}")
    print("PASS (bit-identical)" if ok else "FAIL")
    sys.exit(0 if ok else 1)
