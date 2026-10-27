# SLW (strategic leader withholding)

The attacker proposes in every round except the rounds it leads, and in those rounds it sends no block at all, even when its leader timeout fires. Its leader slot is therefore empty, so that round has no anchor to commit, and the blocks that the anchor would have committed are committed with a later leader. Honest validators, which wait for the previous round's leader before proposing, wait out their leader timeout and then propose on the forced path. The attack moves the boundary between two consecutive commits; it does not drop or reorder any block inside a round, which is why the paper scores it on realized MEV rather than on a positional race.

| | |
|---|---|
| Clause of the legitimate action set | (iii) timing |
| Block role | own anchor |
| Choice | skip own leader rounds |
| Has an effect where | wave-based DAGs (DAG-specific) |
| Table II rows | A2.5 (Mysticeti in Sui v1.74) |
| Armed by | There is no variable named `SLW`. Mysticeti in Sui v1.74: `ATTACK_MODE=mysticeti_slw` (or `mysticeti_slw_fissure`, which also arms fissure); `ATTACK_MODE=slw` alone is not in the recognized set and leaves the hook inert. Mysticeti in Sui v1.58: any `ATTACK_MODE` containing `slw` (the test uses `slw`). Attackers in both: indices `< floor(n · ATTACKER_RATIO)` (default 0.33; the tests set 0.308, so 4 of 13). The v2 Sui launcher translates the campaign label `slw` to `mysticeti_slw` |

## Notation
- `a`: the attacking validator, `idx(a)` its committee index. `n`: committee size.
- `r`: the threshold-clock round, the round `a` would propose.
- `A`: the attacker set. Sui v1.74: `attack_active` (mode in the recognized list) and `idx(a) < floor(n · ATTACKER_RATIO)`, or the v2 coordinator's assignment. Sui v1.58: `attack_active` (mode is `fissure`, `speculative`, `sluggish` or contains `slw`) and `is_attacker` (`idx(a) < floor(n · ATTACKER_RATIO)` in the default layout).
- `τ`: the leader timeout, `leader_timeout` (200 ms default). `force`: the call comes from the leader-timeout task (or recovery) and skips the leader-wait and `min_round_delay` checks.
- `own(r)`: whether the hook treats `r` as `a`'s leader round.
  - Sui v1.74: `r mod n = idx(a)`, a re-derivation of round-robin. It does not read `SEL_REAL_SCHEDULE` and does not consult the protocol's schedule, so it ignores the reputation swap table, `STAKE_BASED_LEADER` and leader offsets above 0.
  - Sui v1.58: `a ∈ committer.get_leaders(r)`, the protocol's own schedule.

## Algorithm
```text
Algorithm E. SLW (runs on attacker a only)
 1: procedure TRYNEWBLOCK(force)          ▷ upstream entry: after accepting blocks, on leader timeout, at recovery
 2:   if attack active and a ∈ A and ATTACK_MODE contains "slw" then        ▷ hook: gate
 3:     r ← threshold-clock round
 4:     if tree = Sui v1.74 then own ← (r mod n = idx(a))                   ▷ hook: round-robin re-derivation
 5:     else own ← a ∈ committer.get_leaders(r)                             ▷ hook: protocol schedule (Sui v1.58)
 6:     if own then return ⊥                                                ▷ hook: (iii) no block for round r, forced or not
 7:   end if
 8:   if r ≤ round of a's last block then return ⊥                          ▷ upstream
 9:   if not force and (leader of r−1 missing or min_round_delay not passed) then return ⊥   ▷ upstream
10:   B ← BUILD(r); broadcast B                                             ▷ upstream
11: end procedure

Effect on an honest validator h (unmodified code)
12: procedure TRYNEWBLOCK_h(force)
13:   r′ ← h's threshold-clock round
14:   if not force and leader slot of r′−1 has no block then return ⊥       ▷ upstream: a's empty slot blocks this
15:   ...                                                                   ▷ upstream
16: LEADERTIMEOUT: after τ without a new round, call TRYNEWBLOCK_h(true)    ▷ upstream: h proposes r′ without a's block
```
In Sui v1.74 the SLW hook is the last of four hooks at the top of `try_new_block` (after `MAX_ATTACKER_PROPOSES`, silent-except-leader and sluggish) and runs before `should_propose` and the round check. In Sui v1.58 it runs after the round check (line 8) and right after the silent-except-leader hook. Because the gate does not test `force`, the attacker produces no block for its leader round at all; once its clock passes `r` it proposes round `r+1` normally.

## Why every message stays in the legitimate action set
The attacker sends no message in its leader rounds and ordinary blocks in every other round. A correct leader that is slow or briefly offline when its turn comes leaves the same empty slot, and Mysticeti's upstream path handles it: honest validators wait at most the leader timeout, propose on the forced path, and the commit rule decides the empty slot with its unchanged skip logic. Every block the attacker does send is built by the upstream path and passes the unchanged parent, quorum, timestamp and signature checks.

## Differences between trees
- **Mysticeti in Sui v1.74**: leader test is `clock_round mod n = own_index`. Under the test builds' default round-robin schedule (`elect_leader` under `cfg(test)` returns `(round + offset) mod n`, then the swap table), this matches the protocol except in rounds where the reputation swap table replaces the leader, and it does not follow `STAKE_BASED_LEADER=1`. The v2 coordinator path recognizes `mysticeti_slw` and `mysticeti_slw_fissure`.
- **Mysticeti in Sui v1.58**: leader test is the protocol's `committer.get_leaders(r)`. The gate matches any mode containing `slw`. On the v2 coordinator path `attack_active` is recomputed as `fissure`, `speculative` or `sluggish` only, so a coordinator-assigned `slw` policy leaves the hook inert.
- **Bullshark, Narwhal-Tusk, Mysticeti in Sui v1.50, Mysticeti (standalone), Mahi-Mahi, AlephBFT, Autobahn**: no SLW hook was found.

## Where it is implemented
| Tree (paper name) | File | Function / anchor | Lines |
|---|---|---|---|
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `ValidatorProposer::new`: `ATTACK_MODE`, recognized modes (`attack_active`), `is_attacker` | 172-208 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | coordinator override, same recognized list | 212-254 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `try_new_block`, SLW hook (gate at 1224-1225, leader test at 1229) | 1217-1237 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `try_new_block`, upstream leader wait skipped only when `force` | 1302-1334 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/leader_timeout.rs` | `LeaderTimeoutTask::run`: forced call after `leader_timeout` | 60-121 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/leader_schedule.rs` | `elect_leader`: round-robin under `cfg(test)`, swap table | 161-183 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/withholding_attack_test.rs` | `test_slw_attack_asr_dynamic`: sets `ATTACK_MODE=mysticeti_slw` | 399-425 |
| Mysticeti in Sui v1.74 | `scripts/v2/launchers/sui.py` | label `slw` translated to `mysticeti_slw` | 56-60 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `Core::new`: `attack_active` (contains `slw`), `is_attacker` | 242-270 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | coordinator override (`attack_active` without `slw`) | 340-343 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `try_new_block`, SLW hook (gate at 737-740) | 735-743 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `is_leader_at`, `leaders` | 1600-1622 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/withholding_attack_test.rs` | `test_slw_attack_asr_dynamic`: sets `ATTACK_MODE=slw` | 324-339 |
