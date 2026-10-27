# LVW (leader-vote withholding)

In Mysticeti a block of round ρ+1 counts as a vote for the leader of round ρ when its history contains the leader's block, and as a blame when none of its ancestors is authored by that leader. The leader is skipped when 2f+1 stake of round-(ρ+1) blocks blame it, and committed directly when 2f+1 stake of decision-round blocks certify it. An LVW attacker waits for the leader's round-ρ block like any proposer, then leaves it out of the parent set of its own round-(ρ+1) block, so that block is a blame instead of a vote. If enough stake does this, a victim's leader slot is skipped or decided later, and the victim's blocks move to a later sub-DAG behind the attacker's.

| | |
|---|---|
| Clause of the legitimate action set | (i) references |
| Block role | leader |
| Choice | omit the leader's block |
| Has an effect where | leader-anchored DAGs (DAG-specific) |
| Table II rows | A2.7 |
| Armed by | `ATTACK_MODE=mysticeti_lvw` (also any mode containing `lvw` or `eclipse`), read by every node; only nodes with index `< ⌊n·ATTACKER_RATIO⌋` act, plus nodes listed in `MLVW_BRIBED_NODES`. Parameters `ATTACKER_RATIO` (hook default 0.308, proposer constructor default 0.33), `VICTIM_RATIO` (default 0.231, rounded), `MLVW_BLAME_ALL_NON_ATTACKER` (default unset), `REP_TARGET` (default unset). The test harness sets `ATTACK_MODE=mysticeti_lvw`, `ATTACKER_RATIO=0.308`, `VICTIM_RATIO=0.231`, n = 13 unless `NO_ATTACK=1`. |

## Notation
- `a`: the attacking validator; `i(a)` its authority index. `r`: the round `a` is about to propose. `ρ = r − 1`: the leader round whose leader `a`'s block votes on or blames.
- `n`: committee size (13). `Q`: quorum threshold of stake (9 at n = 13 with unit stake).
- `n_a = ⌊n·ATTACKER_RATIO⌋`: attackers are indices `0 .. n_a − 1` (4 at n = 13 with 0.308).
- `n_v = round(n·VICTIM_RATIO)`: victims are indices `n − n_v .. n − 1` (3 at n = 13 with 0.231, so indices 10, 11, 12).
- `w = DEFAULT_WAVE_LENGTH = MINIMUM_WAVE_LENGTH = 3`.
- `T`: the authorities whose round-ρ block the hook drops. The hook builds `T` from `(ρ + o) mod n` for `o = 0 .. w − 1`, which is the round-robin test schedule shifted by up to two rounds (see Differences).
- `A`: the ancestor list `a` is about to reference (upstream: its own last block plus, for every other authority, the latest cached block below round `r`, newer than the last one `a` referenced and in Include state).
- `leader(ρ)`: in the test build, `(ρ + offset) mod n` passed through the leader swap table, with one leader per round (`num_leaders_per_round = Some(1)` in `for_testing`).

## Algorithm
```text
Algorithm G. LVW: Mysticeti in Sui v1.74 (runs on attacker a only)
 1: procedure PROPOSE(r, force)                                      ▷ upstream try_new_block
 2:   if not force then
 3:     if the block of leader(r−1) is not in the local DAG then return         ▷ upstream: wait for the leader
 4:     if min_round_delay has not passed since a's last block then return       ▷ upstream
 5:   end if
 6:   A ← ancestor candidates for round r                            ▷ upstream
 7:   A ← FISSUREFILTER(A, r)                                        ▷ separate hook (01_fissure.md); returns A unless armed
 8:   A ← LVWFILTER(A, r)                                            ▷ hook
 9:   if not force and stake of the round-(r−1) blocks in A < Q then return     ▷ upstream: wait for more blocks
10:   add Exclude-state ancestors, best score first, until round r−1 reaches Q   ▷ upstream
11:   build block B(r, A, transactions); sign B; broadcast B          ▷ upstream
12: end procedure
13: procedure LVWFILTER(A, r)
14:   bribed ← (i(a) ∈ MLVW_BRIBED_NODES)                            ▷ hook
15:   if ATTACK_MODE contains neither "lvw" nor "eclipse" then return A          ▷ hook gate
16:   if a is not an attacker and not bribed then return A                     ▷ hook gate
17:   ρ ← r − 1
18:   if ρ = 0 then return A
19:   n_v ← round(n · VICTIM_RATIO); if n_v = 0 then return A
20:   n_a ← ⌊n · ATTACKER_RATIO⌋
21:   T ← ∅
22:   for o ← 0 to w − 1 do
23:     u ← (ρ + o) mod n
24:     if MLVW_BLAME_ALL_NON_ATTACKER then add u to T if u ≥ n_a
25:     else add u to T if u ≥ n − n_v
26:   end for
27:   R ← indices listed in REP_TARGET                               ▷ hook variant, reputation targeting
28:   if T = ∅ and R = ∅ then return A
29:   return A without every b with round(b) = ρ and author(b) ∈ T ∪ R      ▷ (i) omit these blocks
30: end procedure
```
With `V2_COORDINATOR_URL` set, a coordinator can mark the attacker passive for a round, and LVWFILTER returns `A` after line 16. With the variable unset that step is skipped.

What the omission does on the commit side (upstream, unchanged, `base_committer.rs`): a round-(ρ+1) block is a blame for `leader(ρ)` when none of its ancestors is authored by the leader (`enough_leader_blame`), and the leader is skipped when blames reach `Q`. Commit needs `Q` stake of decision-round blocks that each see `Q` votes (`enough_leader_support`). The hook drops the leader's latest block, and `A` holds at most one block per authority, so the attacker's round-r block has no ancestor by that leader and is a blame. With 4 attackers at n = 13 there are 4 blames against 9 needed, which matches the A2.7 cause "four blames, nine needed".

## Why every message stays in the legitimate action set
A correct validator whose leader timeout fires before the round-ρ leader's block reaches it calls the proposer with `force = true`, skips the leader wait, and proposes a round-r block whose parents do not include that leader. The attacker sends a block of the same form: its own payload, its own signature, and at least `Q` stake of round-ρ parents, because when the drop leaves less than that the upstream path waits for more blocks (line 9). The hook itself has no quorum guard: on the forced path (line 10) the upstream code adds low-score ancestors and then asserts that round r−1 reaches `Q`, so a drop that leaves too little stake there would stop the attacker's node rather than produce an invalid block. Every honest node checks it with the unchanged block verifier, including the parent-quorum check, and runs the unchanged commit rule on it. The only difference from the timeout case is when the block is sent: the attacker already has the leader's block and leaves it out without waiting for the timeout.

## Differences between trees
- **Mysticeti in Sui v1.74**: the only tree with an LVW hook. No LVW hook exists in Bullshark, Narwhal-Tusk, Mysticeti in Sui v1.58 or v1.50, Mysticeti (standalone), Mahi-Mahi, AlephBFT or Autobahn.
- **The dropped set is wider than the leader.** `T` contains up to `w = 3` authorities, `ρ mod n`, `(ρ+1) mod n` and `(ρ+2) mod n`, filtered to victims. In the test build there is one leader per round, so only `ρ mod n` leads round ρ. The other two lead rounds ρ+1 and ρ+2, and their round-ρ blocks are ordinary blocks. At n = 13 with victims 10, 11, 12, the hook drops up to 9 victim blocks per 13 rounds, and 3 of them are leader blocks. The other 6 drops act like fissure on a victim. The code comment explains the offsets as pipelined committers with different leader offsets, but the upstream `UniversalCommitter` builds pipeline stages with a round offset and one leader offset per round.
- **Schedule assumption.** `T` assumes the round-robin test schedule. The upstream test schedule passes the leader through the reputation swap table, and `STAKE_BASED_LEADER=1` or a non-test build uses the stake-weighted schedule; the hook follows neither.
- **Bribed variant.** `MLVW_BRIBED_NODES` (comma-separated indices) makes honest-index nodes run the same filter. It only acts when `ATTACK_MODE` arms the hook. The bribery file covers it.
- **`MLVW_BLAME_ALL_NON_ATTACKER`** widens the target from victims to every non-attacker index among the up to three offsets.
- **`REP_TARGET`** (indices) drops the round-ρ blocks of the listed authorities in every round, to lower their reputation scores. It shares this hook and its gate, but it is not leader omission.
- **Compound modes.** `mysticeti_lvw_fissure` runs both filters. With `VICTIM_RATIO` unset the two filters disagree on the victim set: the fissure filter floors `n · 0.2` (2 victims at n = 13), LVW rounds `n · 0.231` (3 victims). The `eclipse` modes also arm LVW.

## Where it is implemented
| Tree (paper name) | File | Function / anchor | Lines |
|---|---|---|---|
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | constructor: `ATTACK_MODE`, `attack_active`, `is_attacker` | 172-208 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | call in `smart_ancestors_to_propose`, upstream quorum wait and quorum assert | 403-404, 412-429, 540-543 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `preprocess_ancestors_for_mysticeti_lvw_attack` (gate at 984-988) | 965-1095 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | upstream leader wait, min delay, `force` path in `try_new_block` | 1302-1351 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/leader_schedule.rs` | `elect_leader` (test round-robin, swap table) | 161-183 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/universal_committer.rs` | pipeline stages by round offset | 203-209 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/commit.rs` | `DEFAULT_WAVE_LENGTH`, `MINIMUM_WAVE_LENGTH` | 37, 40 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/base_committer.rs` | `enough_leader_blame`, `enough_leader_support` (upstream) | 337-366, 370 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/block_verifier.rs` | upstream parent-quorum check | 136-146 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/config/src/consensus_protocol_config.rs` | `num_leaders_per_round: Some(1)` in `for_testing` | 97 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/mysticeti_lvw_attack_test.rs` | `test_mysticeti_lvw_attack_asr_dynamic`: n, ratios, `ATTACK_MODE`, `NO_ATTACK` | 77-112 |
