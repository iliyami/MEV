# Code versions

One row per protocol tree under `code/`. "Paper name" is the label the paper uses. The upstream
base is the commit our tree was taken from; where the tree's own history does not record it, the
row gives the closest upstream commit we found by diffing the tree against upstream history
(protocol crates only). Run `git log --diff-filter=A -- code/<tree>` to see the import commit.

| Directory | Paper name | Upstream project | Upstream version or base | Imported here | Toolchain | Our changes |
|---|---|---|---|---|---|---|
| `code/bullshark-flashboys` | Bullshark (certified DAG) | EtherCS/DAGFrontrunning-artifact, branch `bullshark` (the ACSAC 2025 "Flash Boys" artifact, itself asonnino/narwhal branch `bullshark` plus the artifact's attack framework) | `9f936ed` (2025-09-27) | `c19abbf6`, vendored from our nested commit `58bf896`; `201e3e70` adds `Cargo.lock` and `our_harness/requirements.txt` | rustc 1.92.0, `Cargo.lock` pinned (the lock file the paper's binaries were built with); harness Python venv `our_harness/requirements.txt` | [`patches/bullshark-flashboys.patch`](patches/bullshark-flashboys.patch) |
| `code/sui` | Sui v1.74 (Mysticeti inside Sui) | MystenLabs/sui | workspace version `1.74.0` (`Cargo.toml`). Not a release tag: the import commit message names upstream `main` at `818f8d78` (2026-05-22); our diff against upstream found `main` `de4cbdf6` (2026-05-21) as the closest commit, differing only by the attack hooks | `1e350925`, already modified (see note) | `rust-toolchain.toml`: 1.92. Experiments use the debug test build (`cargo test -p consensus-core --lib`) | none, see note |
| `code/bullshark` | Sui v1.58 (Mysticeti inside Sui; the directory name is historical) | MystenLabs/sui | workspace version `1.58.0` (`Cargo.toml`); upstream commit not recorded | `6c4ea9be`, already modified | `rust-toolchain.toml`: 1.85 | none, see note |
| `code/mysticeti` | Mysticeti (standalone) | MystenLabs/mysticeti | closest upstream commit `3b78b12` (2024-01-09) | `6c4ea9be`, already modified | `rust-toolchain`: 1.72.1 | none, see note |
| `code/narwhal-tusk` | Narwhal-Tusk | asonnino/narwhal | closest upstream commit `9061f41` (2022-05-24); upstream fix `e5cc15d` back-ported in `3a1caea2` | `6c4ea9be`, already modified | not pinned in the tree | none, see note |
| `code/alephbft` | AlephBFT | Cardinal-Cryptography/AlephBFT | crate version `0.45.4`; closest upstream commit `f35c7bb` (2025-04-15) | `6c4ea9be`, already modified | `rust-toolchain.toml`: 1.85.1 | none, see note |
| `code/mahi-mahi-consensus` | Mahi-Mahi | asonnino/mahi-mahi | closest upstream commit `7c928c0` (2025-07-20) | `6c4ea9be`, already modified | `rust-toolchain`: 1.78 | none, see note |
| `code/autobahn-artifact` | Autobahn | neilgiri/autobahn-artifact, branch `autobahn` | closest upstream commit `6d77e03` (2024-08-21) | `6c4ea9be`, already modified | not pinned in the tree; no `Cargo.lock` is tracked | none, see note |
| `code/mevsui` | not used in this paper | MystenLabs/sui | workspace version `1.50.0` (`Cargo.toml`) | `6c4ea9be`, already modified | `rust-toolchain.toml`: 1.85 | none, see note |

## Note: trees imported already modified

Only `code/bullshark-flashboys` has a clean upstream base in its own history, so it is the only
tree with a patch file. Every other tree entered this repository with our attack code already in
it:

- `6c4ea9be` ("convert to monorepo - add all protocol implementations", 2025-12-17) added
  `alephbft`, `autobahn-artifact`, `bullshark`, `mahi-mahi-consensus`, `mevsui`, `mysticeti` and
  `narwhal-tusk` from earlier working copies whose own git histories were removed. Its message
  notes, for example, AlephBFT "with paper-aligned ASR calculation".
- `1e350925` ("Port paper-1 MEV attacks to upstream Sui", 2026-05-23) added `code/sui` together
  with the env-gated hooks in `consensus/core/src/proposer.rs` and the attack tests.

A diff from these import commits would therefore miss the changes made before import, so we do
not ship one. The changes made after import are in this repository's history:

```bash
git log -p 6c4ea9be..HEAD -- code/<tree>   # alephbft, autobahn-artifact, bullshark, mahi-mahi-consensus, mevsui, mysticeti, narwhal-tusk
git log -p 1e350925..HEAD -- code/sui
```

To see every change against upstream, clone the upstream project at the base commit in the table
and diff it against the tree, excluding `target/` and log files.

## The Bullshark patch

The tree was developed as a clone of the artifact repository; that nested git history is not part
of this repository, so the patch was cut from it in our working copy:

```bash
git -C code/bullshark-flashboys diff 9f936ed HEAD -- . ':(exclude)our_harness/__pycache__' \
  > patches/bullshark-flashboys.patch
```

It holds our four commits on top of the artifact (`2015619`, `4e6d25a`, `b535217`, `58bf896`):
the env-gated attacker hooks in `primary/` and `worker/`, the victim client and log lines in
`benchmark/`, `node/` and `consensus/` (logging only, under the `benchmark` feature), and the
scoring harness in `our_harness/`. Applied with `git apply` to a clean checkout of
`9f936ed` from the artifact repository, it reproduces `code/bullshark-flashboys` file for file, except `Cargo.lock` and
`our_harness/requirements.txt`, which are pinned files kept only in this repository. Compiled
Python caches that the nested history carries are left out of the patch.

## Build and run notes

- Bullshark: `cargo build --release --features benchmark` from `code/bullshark-flashboys`. The
  benchmark driver runs the same command before every run, so a warm build is reused.
- Sui v1.74: each experiment is a test in `consensus-core`, run from `code/sui` with
  `cargo test -p consensus-core --lib <test> -- --nocapture`. All validators of a run share one
  process.
- Every `cargo` invocation in our scripts sets `CARGO_BUILD_JOBS`, `RUST_TEST_THREADS=1` and
  `nice`. Keep those caps: an unconstrained build of the Sui workspace can exhaust a laptop.
