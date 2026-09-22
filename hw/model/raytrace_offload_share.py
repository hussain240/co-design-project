"""How much of a raytrace frame could the V3A ray kernel take over?

Records every Sphere.intersectionTime(ray) call of one 100x100 frame, then
times (a) rendering the frame and (b) replaying exactly those calls. The ratio
is the fraction of the frame spent in sphere tests (the Amdahl input used in
report_raytrace.txt, section 5.5).

usage: python3 hw/model/raytrace_offload_share.py
"""
import importlib.util, os, sys, time, types

sys.modules.setdefault("pyperf", types.SimpleNamespace(perf_counter=time.perf_counter))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for v in ("original", "optimized"):
    spec = importlib.util.spec_from_file_location("rt_" + v, os.path.join(ROOT, "benchmarks", "raytrace", v, "run_benchmark.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    calls = []
    orig = m.Sphere.intersectionTime
    def rec(self, ray, orig=orig):
        calls.append((self, ray))
        return orig(self, ray)
    m.Sphere.intersectionTime = rec
    m.bench_raytrace(1, 100, 100, None)
    m.Sphere.intersectionTime = orig
    render = min(m.bench_raytrace(1, 100, 100, None) for _ in range(7))
    def replay():
        t = time.perf_counter()
        for o, r in calls:
            o.intersectionTime(r)
        return time.perf_counter() - t
    tests = min(replay() for _ in range(7))
    share = tests / render
    print(f"{v:9s}: frame {render*1e3:6.1f} ms, {len(calls):,} sphere tests {tests*1e3:5.1f} ms "
          f"-> {share*100:4.1f}% of the frame, Amdahl limit {1/(1-share):.2f}x")
