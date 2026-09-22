# HWSW Co-Design Project — pyperformance Optimization & Hardware Acceleration

Analysis and optimization of pyperformance benchmarks on the course VM (Ubuntu 22.04, Python 3.10), and a hardware accelerator proposal.

## Status

| Part | Status |
|---|---|
| nbody | measured on the VM: 1.69x |
| raytrace | measured on the VM: 2.87x |
| V3A accelerator | RTL simulated, bit-exact |

## Repository structure

```
report_nbody.txt                               nbody report
report_raytrace.txt                            raytrace report
script_nbody.sh                                nbody: setup, baseline, optimized run, comparison, perf, flame graphs
script_raytrace.sh                             raytrace: same pipeline
prompt.txt                                     AI prompts used in the project
benchmarks/nbody/original/run_benchmark.py     unmodified pyperformance bm_nbody
benchmarks/nbody/optimized/run_benchmark.py    optimized nbody (same API, same output)
benchmarks/nbody/manifest/                     pyperformance manifest for the optimized version
benchmarks/nbody/verify_nbody.py               correctness check (energy / state)
benchmarks/nbody/profile_nbody.py              single-process driver for perf
benchmarks/nbody/bytecode_count_nbody.py       executed bytecodes per step
benchmarks/nbody/ablation_nbody.py             each optimization measured separately
benchmarks/nbody/results/                      VM measurements (json, perf stat, perf report)
benchmarks/nbody/flamegraphs/                  flame graphs (original / optimized)
benchmarks/raytrace/original/run_benchmark.py  unmodified pyperformance bm_raytrace
benchmarks/raytrace/optimized/run_benchmark.py optimized raytrace (bit-identical image)
benchmarks/raytrace/manifest/                  pyperformance manifest for the optimized version
benchmarks/raytrace/verify_raytrace.py         image comparison (SHA-256)
benchmarks/raytrace/profile_raytrace.py        single-process driver for perf
benchmarks/raytrace/callcount_raytrace.py      Python calls / allocations per render
benchmarks/raytrace/variants_raytrace.py       builds the cumulative ablation stages
benchmarks/raytrace/ablation_raytrace.py       each optimization measured
benchmarks/raytrace/results/                   VM measurements
benchmarks/raytrace/flamegraphs/               flame graphs (original / optimized)
hw/rtl/                                        V3A accelerator Verilog
hw/model/v3a_model.py                          bit-accurate golden model
hw/tb/tb_v3a.v                                 testbench
hw/run_hw_tests.py                             simulate the RTL and check it against the model
hw/docs/                                       block diagrams
hw/sim/results.txt                             latest hardware simulation results
```

## How to run

On the course VM (Ubuntu 22.04, Python 3.10, perf, python3-dbg):

```bash
./script_nbody.sh                 # first run (installs the tools)
SKIP_SETUP=1 ./script_nbody.sh    # later runs
./script_raytrace.sh              # same options as script_nbody.sh
python3 hw/run_hw_tests.py        # needs: sudo apt install iverilog
```
