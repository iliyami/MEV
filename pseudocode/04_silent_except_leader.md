# Silent-except-leader

The attacker proposes only in the rounds it leads and sends nothing in every other round. In a leader-anchored DAG a committed leader is linearized together with its causal history, and the other blocks of the leader's round are not in that history, because blocks of one round never reference each other. A block proposed in the attacker's own leader round therefore is committed ahead of every other block of that round, while a block proposed in any other round is one of many inside some later leader's history. By staying silent outside its leader rounds the attacker gives up volume, and every block it does publish sits at a commit anchor.

| | |
|---|---|
| Clause of the legitimate action set | (iii) timing |
| Block role | own |
| Choice | propose only in own leader rounds |
| Has an effect where | leader-anchored DAGs (DAG-specific) |
| Table II rows | A2.4, A3.1, P2.1, P4.1, P4.2, P4.3, T2.4, T3.1, T3.2, T3.3, D1.1, D1.2, D1.3, D2.1, D2.2, D3.1, D3.2, D3.3 (all Mysticeti in Sui v1.74) |
| Armed by | Mysticeti in Sui v1.74: `SILENT_EXCEPT_LEADER` set to any value other than `0`, with `NUM_ATTACKERS=k` (default 0, which disables it); optional `SEL_REAL_SCHEDULE=1`. Mysticeti in Sui v1.58: `SILENT_EXCEPT_LEADER` other than `0`; attackers from `ATTACKER_RATIO` (default 0.33). Bullshark: `SILENT_EXCEPT_LEADER=1` exactly; attackers from `SILENT_NODES` or the committee's `attack_type`; `SILENT_DRYRUN=1` gives the control. All Sui validators of a test share one process, so the variable is process-wide and the index check is what limits the hook to attackers |

## Notation
- `a`: the attacking validator, `idx(a)` its committee index (Sui) or its position in key order (Bullshark).
- `n`: committee size.
- `r`: the round being proposed. Sui: the threshold-clock round `clock_round`. Bullshark: the proposer's round after it has been advanced for the new header.
- `A`: the attacker set.
  - Sui v1.74: `idx(a) < NUM_ATTACKERS` (default 0). `withholding_attack_test.rs` sets `NUM_ATTACKERS = round(n · ATTACKER_RATIO)` (default 0.308, so 4 of 13) and sets `SILENT_EXCEPT_LEADER=1` if unset. It does not read `ATTACK_MODE`.
  - Sui v1.58: `is_attacker`, which for the default front-running layout is `idx(a) < floor(n · ATTACKER_RATIO)` (default 0.33); `REVERSE_LAYOUT` moves the attackers to the top indices; a v2 coordinator, when set, assigns it instead.
  - Bullshark: positions listed in `SILENT_NODES` (comma-separated positions in key order); if `SILENT_NODES` is unset, every node whose committee entry has `attack_type ≠ 0`.
- `force`: Sui only. `true` when the call comes from the leader-timeout task after `τ` without a new round (`τ` = `leader_timeout`, 200 ms default), and at recovery. A forced call skips the upstream leader-wait and `min_round_delay` checks.
- `L(r)`: the leader set the hook checks against.
  - Sui v1.74 default: `{ r mod n }`, a re-derivation of round-robin. It ignores the protocol's leader swap table (reputation), the `STAKE_BASED_LEADER` election and leader offsets above 0.
  - Sui v1.74 with `SEL_REAL_SCHEDULE=1`: the slots returned by `ProposalLeaderWaiter::leader_slots_to_wait_for(r)`, which is the protocol's own schedule (`UniversalCommitter::get_leaders(r)`, or the v3 allowed-leader list when v3 is enabled).
  - Sui v1.58: always the protocol's own schedule, `committer.get_leaders(r)`.
  - Bullshark: `committee.leader(r)`, the key at position `r mod n` in sorted key order. This is the function Bullshark's consensus uses, but consensus elects leaders only in even rounds; the hook applies it to every round.

## Algorithm
```text
Algorithm D. Silent-except-leader (runs on attacker a only)
 1: procedure TRYNEWBLOCK(force)                ▷ Sui: upstream entry after accepting blocks, on leader timeout, at recovery
 2:   if SILENT_EXCEPT_LEADER is set and ≠ "0" and not force and a ∈ A then   ▷ hook: gate
 3:     r ← threshold-clock round                                             ▷ the round a would propose
 4:     if tree = Sui v1.74 and SEL_REAL_SCHEDULE ≠ "1" then
 5:       mine ← (r mod n = idx(a))                                           ▷ hook: round-robin re-derivation
 6:     else
 7:       mine ← a ∈ protocol leaders of round r                              ▷ hook: the protocol's own schedule
 8:     end if
 9:     if not mine then return ⊥                                             ▷ hook: (iii) no block this round
10:   end if
11:   ... sluggish and SLW hooks, if armed                                     ▷ other primitives (Sui v1.74 order)
12:   if not SHOULDPROPOSE() or r ≤ round of a's last block then return ⊥   ▷ upstream
13:   if not force and (leader of r−1 missing or min_round_delay not passed) then return ⊥   ▷ upstream
14:   B ← BUILD(r)                                                            ▷ upstream: parents, payload, timestamp, signature
15:   broadcast B                                                             ▷ upstream
16: end procedure

Bullshark branch (proposer of a; no forced exception)
17: procedure MAKEHEADER()                                                    ▷ upstream; r was already advanced
18:   B ← header(a, r, payload, parents), signed by a                         ▷ upstream; drains payload and parent buffers
19:   if SILENT_EXCEPT_LEADER = "1" and a ∈ A and committee.leader(r) ≠ a then   ▷ hook
20:     log "FairDag SILENT skip round r"                                     ▷ hook (benchmark builds)
21:     if SILENT_DRYRUN ≠ "1" then return                                    ▷ hook: B is dropped, never sent to the core
22:   end if
23:   send B to own core, which stores and broadcasts it                      ▷ upstream
24: end procedure
```
In Sui v1.74, line 2 is the second hook in `try_new_block`, after the `MAX_ATTACKER_PROPOSES` cap (a separate burst-and-hide hook, inert unless that variable is set). In Sui v1.58, the check `r > last proposed round` runs first, then the hook. Because line 2 exempts forced calls, a Sui attacker still proposes in a non-leader round whenever its leader timeout fires before its clock advances; the paper's D1.3 and D3.3 rows attribute their drop to this. In Mysticeti there is no separate vote message, so a silent attacker also gives no support (no reference) to other leaders in its silent rounds.

## Why every message stays in the legitimate action set
A correct validator that is partitioned, overloaded or briefly offline sends no block in some rounds; Mysticeti and Bullshark tolerate up to f such validators and need no block from a given non-leader. The blocks the attacker does send are built by the upstream path from blocks it holds and pass the unchanged parent, quorum, timestamp and signature checks at every receiver. In the Bullshark branch the header is built and signed but never leaves the attacker, which is indistinguishable from a validator that lost the message. No honest node's code changes; the hook returns before any upstream step when it is disarmed.

## Differences between trees
- **Mysticeti in Sui v1.74**: gated by `NUM_ATTACKERS`, not by `ATTACK_MODE` or `ATTACKER_RATIO`. The default leader test `r mod n = idx(a)` matches the protocol's leader only when the round-robin test schedule (`elect_leader` under `cfg(test)`, `STAKE_BASED_LEADER` unset) has not been changed by a reputation swap. With `STAKE_BASED_LEADER=1` or after a swap, only `SEL_REAL_SCHEDULE=1` follows the protocol. The paper's P4 and D2 runs record `SEL_REAL_SCHEDULE=1` in PROVENANCE.md.
- **Mysticeti in Sui v1.58**: same position and the same forced exception, but always checks the protocol's schedule (`is_leader_at` calls `committer.get_leaders`), and the attacker set comes from `is_attacker` (ATTACKER_RATIO), not `NUM_ATTACKERS`. Any value of `SILENT_EXCEPT_LEADER` other than `0` arms it.
- **Bullshark**: the check sits in `make_header`, after the round has advanced and the header has been built. There is no forced exception: the attacker never sends a header outside the rounds the hook counts as its own. The hook counts every round with `r mod n = position(a)`, including odd rounds where Bullshark elects no leader. The payload digests and parents drained into a withheld header are not put back. `SILENT_DRYRUN=1` logs the skip and still sends the header, as a control with identical labelling.
- **Mysticeti in Sui v1.50, Mysticeti (standalone), Mahi-Mahi, Narwhal-Tusk, AlephBFT, Autobahn**: no silent-except-leader hook was found.

## Where it is implemented
| Tree (paper name) | File | Function / anchor | Lines |
|---|---|---|---|
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `try_new_block`, `MAX_ATTACKER_PROPOSES` cap (separate hook, runs first) | 1139-1157 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `try_new_block`, silent-except-leader (gate at 1167-1168, attacker check at 1170-1173, schedule at 1178-1185) | 1159-1190 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `try_new_block`, upstream checks and leader wait | 1239-1334 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `ProposalLeaderWaiter::leader_slots_to_wait_for` | 1744-1777 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/universal_committer.rs` | `get_leaders` | 115-121 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/leader_schedule.rs` | `elect_leader`: round-robin under `cfg(test)`, `STAKE_BASED_LEADER`, swap table | 161-183 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/leader_timeout.rs` | `LeaderTimeoutTask::run`: `new_block(round, true)` after `leader_timeout` | 60-121 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/core.rs` | `Core::new_block`, `Core::try_propose` | 532-551, 596-610 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/withholding_attack_test.rs` | `test_withhold_silent_attack_asr_dynamic`: sets `NUM_ATTACKERS`, `SILENT_EXCEPT_LEADER` | 320-353 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `try_new_block`, silent-except-leader (gate at 725-731) | 713-734 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `is_leader_at` | 1616-1622 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `Core::new`: `is_attacker` layout | 242-269 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/withholding_attack_test.rs` | `test_withhold_silent_attack_asr_dynamic` | 304-322 |
| Bullshark | `code/bullshark-flashboys/primary/src/proposer.rs` | `silent_skip_this_round` (gate at 120) | 115-152 |
| Bullshark | `code/bullshark-flashboys/primary/src/proposer.rs` | `make_header`: skip before `tx_core.send` | 209-298 |
| Bullshark | `code/bullshark-flashboys/config/src/lib.rs` | `Committee::leader` | 191-195 |
| Bullshark | `code/bullshark-flashboys/consensus/src/lib.rs` | consensus: leaders only in even rounds; `leader()` | 125-128, 220-237 |
