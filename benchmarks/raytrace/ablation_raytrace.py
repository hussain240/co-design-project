"""Ablation study: measure each raytrace optimization cumulatively with pyperf.
See variants_raytrace.py for the stages.

usage: python3 ablation_raytrace.py -o results/ablation.json [--rigorous]
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pyperf
import variants_raytrace as V


def bench(loops, stage):
    mod = V.build(stage)
    mod.pyperf = pyperf
    return mod.bench_raytrace(loops, 100, 100, None)


if __name__ == "__main__":
    runner = pyperf.Runner()
    for stage, _ in V.STAGES:
        runner.bench_time_func(f"raytrace_{stage}", bench, stage)
