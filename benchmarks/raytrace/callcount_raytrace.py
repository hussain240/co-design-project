"""Count Python-level function calls and object allocations for ONE render of
the benchmark scene (100x100), original vs optimized. Evidence for why the
optimizations help: in CPython 3.10 every Python call is a frame push/pop and
every Vector/Point/Ray is a heap allocation (plus a __dict__ without slots).

usage: python3 callcount_raytrace.py
"""
import collections, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_raytrace as VR
import variants_raytrace as V


def count(mod, w=100, h=100):
    calls = collections.Counter()
    code2name = {}
    def prof(frame, event, arg):
        if event == "call":
            co = frame.f_code
            if co.co_filename.endswith("run_benchmark.py") or co.co_filename.startswith("<"):
                name = code2name.get(co)
                if name is None:
                    self = frame.f_locals.get("self")
                    cls = type(self).__name__ + "." if self is not None else ""
                    name = code2name[co] = cls + co.co_name
                calls[name] += 1
    sys.setprofile(prof)
    try:
        VR.render(mod, w, h)
    finally:
        sys.setprofile(None)
    allocs = {k: calls.get(k + ".__init__", 0) for k in ("Vector", "Point", "Ray")}
    return calls, allocs


def counts_for(stages=("v0_original", "v4_slots")):
    return {s: count(V.build(s)) for s in stages}


if __name__ == "__main__":
    res = counts_for()
    (co, ao), (cp, ap) = res["v0_original"], res["v4_slots"]
    print(f"Python function calls per render (100x100)")
    print(f"{'function':34s}{'original':>12s}{'optimized':>12s}")
    for name in sorted(set(co) | set(cp), key=lambda k: -(co.get(k, 0) + cp.get(k, 0)))[:25]:
        print(f"{name:34s}{co.get(name, 0):12,d}{cp.get(name, 0):12,d}")
    print(f"{'TOTAL calls':34s}{sum(co.values()):12,d}{sum(cp.values()):12,d}")
    print()
    print(f"{'objects allocated':34s}{'original':>12s}{'optimized':>12s}")
    for k in ao:
        print(f"{k:34s}{ao[k]:12,d}{ap[k]:12,d}")
