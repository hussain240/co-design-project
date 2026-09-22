"""Build cumulative variants of the raytracer for the ablation study.

Each stage starts from a fresh copy of the ORIGINAL module and replaces some of
its methods with the exact source of the corresponding methods from the
OPTIMIZED module (compiled inside the original module's namespace, so global
lookups behave the same). This way every stage uses the final code, and each
optimization's contribution is measured in isolation, cumulatively:

  v0_original   pyperformance code as-is
  v1_no_checks  + O2  remove mustBeVector()/isPoint() calls
  v2_hoist      + O3  build the shadow ray once per light (loop-invariant)
  v3_inline     + O4  inline hot vector math on floats
  v4_slots      + O1  __slots__ (= the final optimized file)
"""
import importlib.util, inspect, os, sys, textwrap, time, types

if "pyperf" not in sys.modules:
    try:
        import pyperf  # noqa: F401
    except ImportError:
        sys.modules["pyperf"] = types.SimpleNamespace(perf_counter=time.perf_counter)

HERE = os.path.dirname(os.path.abspath(__file__))
ORIG = os.path.join(HERE, "original", "run_benchmark.py")
OPT = os.path.join(HERE, "optimized", "run_benchmark.py")

# optimization -> list of (class name or None, method name)
PATCHES = {
    "O2": [("Vector", "__add__"), ("Vector", "__sub__"), ("Vector", "dot"),
           ("Vector", "cross"), ("Point", "__add__"), ("Point", "__sub__")],
    "O3": [("Scene", "_lightIsVisible")],
    "O4": [("Vector", "magnitude"), ("Vector", "normalized"), ("Vector", "reflectThrough"),
           ("Sphere", "intersectionTime"), ("Sphere", "normalAt"),
           ("Halfspace", "intersectionTime"), ("Ray", "__init__"), ("Ray", "pointAtTime"),
           ("Scene", "render"), ("Scene", "rayColour"), ("SimpleSurface", "colourAt")],
}
STAGES = [
    ("v0_original", []),
    ("v1_no_checks", ["O2"]),
    ("v2_hoist", ["O2", "O3"]),
    ("v3_inline", ["O2", "O3", "O4"]),
    ("v4_slots", None),            # None -> load the optimized file itself
]

_counter = [0]


def _load(path):
    _counter[0] += 1
    spec = importlib.util.spec_from_file_location(f"rt_variant_{_counter[0]}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build(stage):
    opts = dict(STAGES)[stage]
    if opts is None:
        return _load(OPT)
    mod = _load(ORIG)
    if opts:
        opt = _load(OPT)
        exec("from math import sqrt", mod.__dict__)
        for o in opts:
            for cls, meth in PATCHES[o]:
                src = textwrap.dedent(inspect.getsource(getattr(getattr(opt, cls), meth)))
                ns = {}
                exec(compile(src, f"<{stage}:{cls}.{meth}>", "exec"), mod.__dict__, ns)
                setattr(getattr(mod, cls), meth, ns[meth])
    return mod
