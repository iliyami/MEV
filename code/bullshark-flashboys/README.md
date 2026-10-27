# No Fish Is Too Big for Flash Boys! Frontrunning on DAG-based Blockchains - ACSAC 2025 Artifact
This branch implements inter-block frontrunning on Bullshark.

## Install dependencies and build binaries

Install software dependencies, including Python, Rust, Clang, and tmux.

```bash
bash ./install.sh
```

Build binaries:

```bash
cargo build
```

Install Python dependencies for benchmarking

```bash
cd benchmark
pip3 install -r requirements.txt
```

## Benchmark in a local machine

### Quick Start (Recommend running)

If it is your first time running our project, we highly recommend running a simple test by executing the following command (under `./benchmark`). It will compile rust code, making the running time of future evaluations more precise (by not re-compile the code).

```bash
fab local
```

This command may take a long time the first time you run it (compiling rust code in `release` mode may be slow). It will deploy a default simple benchmark to evaluate the speculative attack, with 10 nodes in total, 0 crahsed nodes, 3 frontrunning attackers, and 4 workers for each node. When the benchmark terminates, it creates a file `local-3-3-0-4-10.txt` in `.\results\bullshark` with the below output.

```
-----------------------------------------
 SUMMARY:
-----------------------------------------
 + CONFIG:
 Attacking type: 3 
 Arbitragers: 3 node(s)
 Faults: 0 node(s)
 Committee size: 10 node(s)
 Worker(s) per node: 4 worker(s)
 Collocate primary and workers: True
 Input rate: 30,000 tx/s
 Transaction size: 512 B
 Execution time: 30 s

 Header size: 1,000 B
 Max header delay: 200 ms
 GC depth: 50 round(s)
 Sync retry delay: 10,000 ms
 Sync retry nodes: 3 node(s)
 batch size: 500,000 B
 Max batch delay: 200 ms

 + RESULTS:
 Consensus TPS: 29,308 tx/s
 Consensus BPS: 15,005,584 B/s
 Consensus latency: 503 ms

 End-to-end TPS: 29,129 tx/s
 End-to-end BPS: 14,914,022 B/s
 End-to-end latency: 752 ms

 + ATTACK:
 Speculative front-running rate: 77.78% (7/9) 
-----------------------------------------

Cumulative speculative front-running results: 77.78% (7/9) 
```

You can also customize the parameters in `local` function in `fabfile.py` to evaluate different frontrunning strategies under distinct settings, including the number of nodes *n*, the number of attackers *f_a*, the number of crashed nodes *f_l*, and the number of workers *f_w*.

In the following sections, we provide some commands (with customized parameters) for Artifact Evaluation. The experiment results will be used to validate our claims.

### Evaluate the impact of crashed nodes (Claim 1)

First, we validate **Claim 1**, by showing that the attack success rates (ASRs) increase overall for all attacking strategies with an increasing ratio of crashed nodes (i.e., *f_l/n*).

Under `./benchmark`, run the following command:

```bash
fab articrash
```

It will evaluate the baseline and all three frontrunning strategies under different *f_l/n* (including 0 and 0.2). Each measurement will run 1 minute and repreats 4 times. Thus, the expected total runtime is approximately 32 (=4\*2\*4) minutes. After it terminates, it will output the comparison results:

```bash
...
Baseline (crash node ratio: 0/10): 42.64%
Baseline (crash node ratio: 2/10): 50.77%
Fissure (crash node ratio: 0/10): 72.6%
Fissure (crash node ratio: 2/10): 74.82%
Sluggish (crash node ratio: 0/10): 42.71%
Sluggish (crash node ratio: 2/10): 55.56%
Speculative (crash node ratio: 0/10): 61.54%
Speculative (crash node ratio: 2/10): 63.51%
```

### Evaluate the impact of workers (Claim 2)

For **Claim 2**, we will show that the speculative attack benefits from the number of workers (i.e., *f_w*) mostly.

Under `./benchmark`, run the following command:

```bash
fab artiworker
```

It will evaluate the baseline and all three frontrunning strategies under different *f_w* (i.e., *f_w=1, 4*). Each measurement will run 1 minute and repreats 4 times. Thus, the expected total runtime is approximately 32 (=4\*2\*4) minutes. After it terminates, it will output the comparison results:

```bash
...
Baseline (workers: 2): 47.52%
Baseline (workers: 8): 55.77%
Fissure (workers: 2): 40.62%
Fissure (workers: 8): 60.61%
Sluggish (workers: 2): 46.03%
Sluggish (workers: 8): 40.91%
Speculative (workers: 2): 53.37%
Speculative (workers: 8): 85.56%
```

### Evaluate the impact of frontrunning attackers (Claim 3)

For **Claim 3**, we will show that the fissure attack benefits from the ratio of frontrunning attackers (i.e., *f_a/n*) mostly.

Under `./benchmark`, run the following command:

```bash
fab artifrontrunner
```

It will evaluate the baseline and all three frontrunning strategies under different *f_a/n* (i.e., *f_a/n=0.3, 0.5*). Each measurement will run 1 minute and repreats 4 times. Thus, the expected total runtime is approximately 32 (=4\*2\*4) minutes. After it terminates, it will output the comparison results:

```bash
Baseline (frontrunners: 3): 46.67%
Baseline (frontrunners: 5): 45.35%
Fissure (frontrunners: 3): 41.67%
Fissure (frontrunners: 5): 72.73%
Sluggish (frontrunners: 3): 43.86%
Sluggish (frontrunners: 5): 43.51%
Speculative (frontrunners: 3): 50.35%
Speculative (frontrunners: 5): 62.79%
```

### Repeat Evaluation

In the above experiments, each measurement only contains 0~30 times of attacks. This could save your time in getting a rough comparison (which already show the effectiveness of the attacks), but might have deviations. If you wish to get a more precise result, you could repeat this progress multiple times, and the results are cumulative. In our paper, each measure contains at least 500 times of attacks.

## Evaluation on AWS

To run experiments in AWS, follow the steps:

1. **Set up your AWS account**. Please refer to the tutorial provided by [Narwhal AWS Evaluation](https://github.com/asonnino/narwhal/tree/master/benchmark), which explains how to benchmark the codebase and read benchmarks' results. It also provides a step-by-step tutorial to run benchmarks on [Amazon Web Services (AWS)](https://aws.amazon.com) across multiple data centers (WAN).
2. **Run experiments**. Using `fabfile.py` to run the benchmarks. In particular, the `remote` function of `fabfile.py` is defined similarly to the `local` function. Thus, similar to the evaluation in a local machine, after specifying all customized parameters (such as nodes, crashed nodes, attackers, workers, etc.), execute: ```fab remote```.
3. **Get experiment results**. After the program terminates, the experiment results will be automatically downloaded in `./benchmark/results/bullshark/` with the name format `remote--{attack_type}-{attackers}-{crash}-{workers}-{nodes}.txt`.
