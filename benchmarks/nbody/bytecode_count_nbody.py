"""Count the bytecode instructions CPython actually executes per simulation
step in advance(), original vs optimized. Evidence for *why* O2/O3 help:
arithmetic opcodes stay the same, container/stack-shuffling opcodes vanish.

usage: python3 bytecode_count_nbody.py [steps]
(opcode names are those of the running interpreter, e.g. 3.10)
"""
import collections, dis, importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    spec = importlib.util.spec_from_file_location("bc_" + name, os.path.join(HERE, name, "run_benchmark.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _count(mod, code, steps):
    cnt = collections.Counter()
    def local(frame, event, arg):
        if event == "opcode":
            cnt[dis.opname[frame.f_code.co_code[frame.f_lasti]]] += 1
        return local
    def glob(frame, event, arg):
        if frame.f_code is code:
            frame.f_trace_opcodes = True
            return local
        return None
    sys.settrace(glob)
    try:
        mod.advance(0.01, steps)
    finally:
        sys.settrace(None)
    return {k: v / steps for k, v in cnt.items()}


def count_bytecodes(steps=100):
    """Return (original, optimized): dict opcode -> executions per step."""
    orig, opt = _load("original"), _load("optimized")
    for m in (orig, opt):
        m.offset_momentum(m.BODIES["sun"])
    return (_count(orig, orig.advance.__code__, steps),
            _count(opt, opt._advance_specialized.__code__, steps))


if __name__ == "__main__":
    steps = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    a, b = count_bytecodes(steps)
    print(f"Python {sys.version.split()[0]}, per step (averaged over {steps} steps)")
    print(f"{'opcode':22s}{'original':>10s}{'optimized':>11s}")
    for op in sorted(set(a) | set(b), key=lambda k: -(a.get(k, 0) + b.get(k, 0))):
        print(f"{op:22s}{a.get(op, 0):10.1f}{b.get(op, 0):11.1f}")
    print(f"{'TOTAL':22s}{sum(a.values()):10.1f}{sum(b.values()):11.1f}")
