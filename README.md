# Transaction Order Manipulation in DAG-Based BFT

This repository contains the code, data, and plotting pipeline for our experimental study of transaction-order manipulation in DAG-based Byzantine fault-tolerant consensus protocols.

The artifact evaluates:
- 6 DAG-based BFT codebases: Narwhal-Tusk, Bullshark, Mysticeti, AlephBFT, Mahi-Mahi, and Autobahn
- 4 attacker actions: frontrunning, backrunning, sandwiching, and censorship
- 7 attacker primitives: fissure, speculative, sluggish, silent-except-leader, SLW, LVW, and proposal-timestamp
- protocol and deployment dimensions: DAG type, ordering rule, tiebreak, leader rule, tuning, committee size, stake and geo-distribution

The repository already includes the evaluated protocol forks under [`code/`](code), the committed datasets at the project root, and the auto-generated figure pipeline under [`plots/`](plots).

## What Is In This Repository

- [`code/`](code): protocol-specific implementations and attack hooks
- [`config/`](config): experiment configurations used by the runners
- [`scripts/`](scripts): campaign runners for baselines, frontrunning sweeps, and post-victim attacks
- [`plots/`](plots): data loader, figure generator, and generated reports
- [`baseline.csv`](baseline.csv): attack-disabled baselines
- [`experiment_results.csv`](experiment_results.csv): main frontrunning campaign results
- [`autobahn_results.csv`](autobahn_results.csv): Autobahn frontrunning campaign results
- [`back_sand_results.csv`](back_sand_results.csv): backrunning and sandwich campaign results

## Quick Start

If you only want to reproduce the figures and reports from the committed paper data, you do not need to rerun the experiments.

### Requirements

- Python 3.9+
- `pip`
- `docker` only if you want to rerun experiments
- `cargo` only if you want to rebuild local protocol binaries
- a TeX distribution only if you want to compile the paper locally

Install the only Python dependency used by the plotting and runner layer:

```bash
python3 -m pip install pyyaml
```

## Running Long Experiments On Your Own Machines

The long campaigns do not provision cloud resources for you. They assume you already have one or more Linux machines with enough CPU, RAM, and disk, and that Docker can run privileged network-emulation commands on those hosts.

The simplest setup is:

1. Provision one or more Ubuntu-class machines.
2. Clone this repository onto each machine that will execute experiments.
3. Install Docker and confirm that your user can run it.
4. Install Python and `pyyaml`.
5. Run the campaign commands from the repository root on each machine.

For the Docker-backed paths, the runner expects:

- `docker build` and `docker run` to work without sudo prompts
- support for `--cap-add=NET_ADMIN`
- enough local disk for Docker images, temporary build artifacts, and logs under [`results/`](results)

The YAML files under [`config/`](config) declare the requested Docker resources for each protocol, for example:

- Narwhal-Tusk: [`config/grand_experiment_narwhal.yaml`](config/grand_experiment_narwhal.yaml)
- Autobahn: [`config/grand_experiment_autobahn.yaml`](config/grand_experiment_autobahn.yaml)

If your machine is smaller than the validated setup, reduce the `docker.cpus` and `docker.memory` values in the relevant config before launching a long run. The runner will cap requests to the Docker daemon limits when possible, but a smaller machine can still change throughput and timing behavior.

Useful preflight checks:

```bash
docker info
docker run --rm --cap-add=NET_ADMIN alpine true
python3 -m pip install pyyaml
```

If Docker build issues appear on some cloud images, try:

```bash
export DOCKER_BUILDKIT=0
```

before running the campaign. The runner already honors that override.

Recommended execution pattern:

- use one machine per large campaign family if you want to parallelize runs
- keep a separate output CSV per machine while the runs are in progress
- copy the finished CSVs back into the repository root before regenerating figures

The validated paper datasets were produced from containerized runs on dedicated cloud machines. Full reruns on smaller hosts are still useful, but the committed CSVs remain the reference data for the artifact.

## Reproduce Figures And Reports From The Committed Data

From the repository root:

```bash
python3 -m plots.generate_all
```

This regenerates:

- TikZ figure sources in [`plots/generated/figures/`](plots/generated/figures)
- coverage and inventory reports in [`plots/generated/reports/`](plots/generated/reports)
- a lightweight preview document in [`plots/generated/preview.tex`](plots/generated/preview.tex)

Optional preview build:

```bash
cd plots/generated
latexmk -pdf preview.tex
```

The most useful generated reports are:

- [`plots/generated/reports/experiment_inventory.md`](plots/generated/reports/experiment_inventory.md)
- [`plots/generated/reports/figure_manifest.md`](plots/generated/reports/figure_manifest.md)
- [`plots/generated/reports/data_anomalies.md`](plots/generated/reports/data_anomalies.md)

Important note:

- [`plots/generated/figures/`](plots/generated/figures) contains the auto-generated figure sources driven directly from the CSVs.

## Smoke-Test The Reproduction Entry Points

Before launching a full rerun, you can validate the entry points without writing CSV output:

```bash
python3 scripts/run_protocol_baselines.py --dry-run --out /tmp/baseline_smoke.csv
```

```bash
python3 scripts/experiment_sweeper.py \
  --config config/grand_experiment_narwhal.yaml \
  --experiments scaling,env_latency,offense_fissure,offense_speculative,offense_sluggish,defense_memory,defense_network,defense_gc,defense_header,defense_batching,scaling_workers \
  --type frontrun \
  --out /tmp/experiment_results_smoke.csv \
  --dry-run
```

```bash
python3 scripts/experiment_sweeper.py \
  --config config/grand_experiment_autobahn.yaml \
  --experiments scaling,env_latency,offense_fissure,offense_speculative,offense_sluggish,offense_exclusion,autobahn_k,autobahn_fast_path \
  --type frontrun \
  --out /tmp/autobahn_results_smoke.csv \
  --dry-run
```

```bash
python3 scripts/run_backrun_sandwich_simple_campaign.py \
  --out /tmp/back_sand_results_smoke.csv \
  --dry-run
```

These commands do not execute the full experiments. They verify that the runner scripts, config files, and command wiring resolve correctly on your machine.

## Reproduce The Data

The committed CSV files are the paper datasets. If you want to regenerate them from the experiment runners, use the workflow below.

### 1. Reproduce Baselines

```bash
python3 scripts/run_protocol_baselines.py --out baseline.csv
```

This regenerates the attack-disabled baseline measurements used as the fair-order reference.

### 2. Reproduce Frontrunning Campaigns

The main sweeps are driven by [`scripts/experiment_sweeper.py`](scripts/experiment_sweeper.py):

```bash
python3 scripts/experiment_sweeper.py \
  --config <config-file> \
  --experiments <comma-separated-experiments> \
  --type frontrun \
  --out <output.csv>
```

Common experiment groups:

- `scaling`
- `env_latency`
- `offense_fissure`
- `offense_speculative`
- `offense_sluggish`

Protocol-specific extensions:

- Bullshark / MEVSUI / Narwhal-Tusk:
  - `defense_memory`
  - `defense_network`
  - `defense_gc`
- Narwhal-Tusk:
  - `defense_header`
  - `defense_batching`
  - `scaling_workers`
- Mysticeti:
  - `offense_exclusion`
  - `mysticeti_strategy`
  - `mahimahi_wave`
  - `mahimahi_leaders`
- Mahi-Mahi:
  - `mahimahi_strategy`
  - `mahimahi_wave`
  - `mahimahi_leaders`
- AlephBFT:
  - `offense_exclusion`
  - `aleph_lookahead`
  - `aleph_sync_speed`
  - `aleph_hash_randomization`
- Autobahn:
  - `offense_exclusion`
  - `autobahn_k`
  - `autobahn_fast_path`

Main configuration files:

- [`config/local_verify_unified.yaml`](config/local_verify_unified.yaml): Bullshark
- [`config/grand_experiment.yaml`](config/grand_experiment.yaml): MEVSUI (present in the artifact, not part of the six-protocol evaluation)
- [`config/grand_experiment_narwhal.yaml`](config/grand_experiment_narwhal.yaml): Narwhal-Tusk
- [`config/grand_experiment_mysticeti.yaml`](config/grand_experiment_mysticeti.yaml): Mysticeti
- [`config/grand_experiment_alephbft.yaml`](config/grand_experiment_alephbft.yaml): AlephBFT
- [`config/grand_experiment_mahimahi.yaml`](config/grand_experiment_mahimahi.yaml): Mahi-Mahi
- [`config/grand_experiment_autobahn.yaml`](config/grand_experiment_autobahn.yaml): Autobahn

Examples:

```bash
python3 scripts/experiment_sweeper.py \
  --config config/grand_experiment_narwhal.yaml \
  --experiments scaling,env_latency,offense_fissure,offense_speculative,offense_sluggish,defense_memory,defense_network,defense_gc,defense_header,defense_batching,scaling_workers \
  --type frontrun \
  --out experiment_results.csv
```

```bash
python3 scripts/experiment_sweeper.py \
  --config config/grand_experiment_autobahn.yaml \
  --experiments scaling,env_latency,offense_fissure,offense_speculative,offense_sluggish,offense_exclusion,autobahn_k,autobahn_fast_path \
  --type frontrun \
  --out autobahn_results.csv
```

The sweeper writes one row per repetition into the CSV passed with `--out`, and the Docker-backed protocols also write raw logs under [`results/`](results). If a run is interrupted, rerunning the same command resumes from the existing CSV and skips completed rows.

### 3. Reproduce Backrunning And Sandwiching

The post-victim campaign is intentionally narrower and is driven by a dedicated script:

```bash
python3 scripts/run_backrun_sandwich_simple_campaign.py --out back_sand_results.csv
```

By default this runs the simple post-victim campaign for:

- Bullshark
- Mysticeti
- AlephBFT
- Autobahn

You can limit the run to a subset:

```bash
python3 scripts/run_backrun_sandwich_simple_campaign.py \
  --protocol bullshark \
  --protocol mysticeti \
  --out back_sand_results.csv
```

This wrapper builds Docker images only for the protocols that need them and forwards the actual work to [`scripts/experiment_sweeper.py`](scripts/experiment_sweeper.py). In dry-run mode it prints the exact `ATTACK_MODE`, protocol config, and output path for every planned command.

### 4. Outputs

The main data products are:

- [`baseline.csv`](baseline.csv)
- [`experiment_results.csv`](experiment_results.csv)
- [`autobahn_results.csv`](autobahn_results.csv)
- [`back_sand_results.csv`](back_sand_results.csv)

These files are the inputs consumed by the plot generator.

## Attack Hooks

Every attacker behaviour is an environment-gated hook on the proposing path. With the variable
unset the hook returns before the default path, so the compiled binary is byte-identical to
upstream and honest validators always run the disarmed build. No hook alters a validity
predicate, a quorum-intersection check or a signature path: each one only chooses among options
an honest validator could legally take, such as which valid parents to reference, when to
broadcast, or which of its own candidate blocks to publish.

| variable | file | what it does |
|---|---|---|
| `FISSURE_ATTACK` | `sui`, `bullshark-flashboys` | omit the victim from the attacker's parent set |
| `SILENT_EXCEPT_LEADER` | `sui` | propose only in rounds the attacker leads |
| `SLW` | `sui` | propose in every round except the attacker's own leader round |
| `BRIBED` | `bullshark-flashboys` | honest nodes accept an offer to omit the victim |
| `SPECULATIVE_SEED_AWARE` | `alephbft` | aim the grinder at the rank the election rotation selects |
| `ALEPH_HASH_SORT_SEED` | `alephbft` | seed the election's candidate rotation |
| `GLOBAL_VIEW`, `RIVAL_GROUPS` | `sui` | information and multi-group relationship cells |
| `SANDWICH_INTERLEAVE` | `mysticeti` | close both sides of a sandwich around one victim |

Ordering-rule variants used for the defense evaluation live in the same file
(`sui/consensus/core/src/commit.rs`) and are gated the same way:

| variable | ordering rule |
|---|---|
| unset | `(round, author)`, the shipped rule |
| `FIX_TIEBREAK` | `(round, digest)` |
| `ROUND_ONLY` | round only, intra-round order left to graph traversal |
| `SEEDED_TIEBREAK`, `TIEBREAK_SEED` | `(round, H(digest, seed))` |
| `ORDER_FAIR_TIEBREAK` | `(round, proposer timestamp, digest)` |

## Practical Notes

- The repository already contains the evaluated protocol code under [`code/`](code). You do not need to clone external repositories to regenerate the committed plots.
- The experiment runners use Docker by default. Some local paths support `--local`, but the artifact’s validated results were produced with the repository’s protocol-specific runners and containerized deployments.
- The validated paper datasets were produced from the artifact’s containerized campaign setup on CloudLab-style infrastructure. Local reruns are useful for sanity checks, but large campaign timing and throughput behavior should be compared against the committed CSVs.
- Full reruns are much more expensive than figure regeneration. The published datasets are included precisely so that readers can reproduce the analysis without rerunning every campaign.
- The authoritative experiment matrix is encoded in [`scripts/experiment_sweeper.py`](scripts/experiment_sweeper.py) and summarized in [`plots/generated/reports/experiment_inventory.md`](plots/generated/reports/experiment_inventory.md).

## Citation

If you use this repository, please cite the paper and the artifact repository once the public record is finalized.
