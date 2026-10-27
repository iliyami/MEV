# Back-run

The attacker wants one of its own blocks to sit directly after a victim's block in the committed order. A block that references the victim's block is causally after it, so every linearization places it later; the attack makes that following block exist as early as possible, so that few other blocks land in between. On standalone Mysticeti a back attacker proposes the moment a victim's block reaches its DAG, without waiting for the round leader. In the two Mysticeti-in-Sui trees (v1.58 and v1.74) it instead holds each proposal until a victim's block of the previous round is among its parents. Honest blocks that also reference the victim compete for the same next position, which is what the L1 metric measures.

| | |
|---|---|
| Clause of the legitimate action set | (iii) timing |
| Block role | own (the attacker's next proposal, timed by the victim's block) |
| Choice | Not a row of Table I. Mysticeti: propose as soon as a victim block arrives. Sui v1.58 and v1.74: do not propose round r until a round r−1 victim block is a parent. |
| Has an effect where | Not a row of Table I. Measured on Mysticeti (A1.2) and, in the action figure, on Sui v1.58, Mysticeti, AlephBFT and Autobahn. Only Mysticeti and the two Sui trees carry a back-run hook (see Differences between trees). |
| Table II rows | A1.2 (imported from the benchmark paper) |
| Armed by | `ATTACK_TYPE=backrun` together with an attack mode: `ATTACK_MODE` in {`fissure`, `speculative`, `sluggish`, `certification_race`} (Mysticeti), in {`fissure`, `speculative`, `sluggish`} (Sui v1.58), or any value containing `fissure` (Sui v1.74). Parameters `ATTACKER_RATIO` (code default 0.33) and `VICTIM_RATIO` (code default 0.22 in Mysticeti and Sui v1.58, 0.2 in Sui v1.74); the campaign configs set 0.308 and 0.231. All validators of a test share one process and one environment, so the variables are set for every node; the hook acts only on nodes whose index falls in the attacker range. |

## Notation
- `a`: the attacking validator. `r`: the round being proposed (the threshold-clock round). `n`: committee size.
- `f_a = ⌊n · ATTACKER_RATIO⌋`: number of attackers. `f_v = ⌊n · VICTIM_RATIO⌋`: number of victims.
- `V`: victim authorities. `B`: back attackers.
  - Mysticeti and Sui v1.58, `ATTACK_TYPE=backrun`: `V = {0, …, f_v−1}`, `B = {f_v, …, f_v+f_a−1}`. At n = 13 with 0.308 and 0.231: `V = {0,1,2}`, `B = {3,4,5,6}`.
  - Sui v1.74 has no back-run layout: attackers are `{0, …, f_a−1}` and `V = {n−f_v, …, n−1}`, as for front-running.
- `immediate`: Mysticeti flag `force_immediate_proposal` (set in `Core`), copied into the upstream flag `force_new_block` (in `Syncer`).
- `force`: the upstream "propose now" flag, set by the leader timeout.
- `Q`: quorum threshold (2f+1 stake).
- Scoring (not run by validators): for each committed victim block `v`, `gap(v)` is the smallest `pos(b) − pos(v) > 0` over back-attacker blocks `b` with `0 ≤ round(b) − round(v) ≤ g`, where `g = 6` under `ATTACK_MODE=sluggish` and `g = 0` otherwise. L1 = share of victim blocks with `gap = 1`; L2 = share with `gap ≤ 2`; cumulative = share with any gap. Denominator: all committed victim blocks.

## Algorithm
```text
Algorithm A. Back-run (runs on attacker a only)

  Branch M: Mysticeti (standalone reference implementation)
 1: procedure ONBLOCKS(S)                              ▷ S: blocks just processed (Core::add_blocks)
 2:   add S to the block store and threshold clock      ▷ upstream
 3:   if ATTACK_TYPE ∈ {backrun, sandwich} and ATTACK_MODE is an attack mode then   ▷ hook (gate)
 4:     if a ∈ B and some b ∈ S has author(b) ∈ V then  ▷ hook: victim block of any round
 5:       immediate ← true                              ▷ hook
 6:     end if
 7:   end if
 8:   TRYPROPOSE()                                      ▷ upstream (Syncer::add_blocks)
 9: end procedure
10: procedure TRYPROPOSE()                              ▷ Syncer::try_new_block
11:   if ATTACK_TYPE ∈ {backrun, sandwich} and a ∈ B and immediate then   ▷ hook
12:     immediate ← false                               ▷ hook (flag is consumed)
13:     force ← true                                    ▷ hook: skip the leader wait
14:   end if
15:   if force or READYNEWBLOCK() then                  ▷ upstream; READYNEWBLOCK waits for the leader block of r−1
16:     if r ≤ last proposed round then return          ▷ upstream (Core::try_new_block)
17:     P ← own previous block ∪ pending includes up to the first one of round ≥ r   ▷ upstream; nothing is dropped for a ∈ B
18:     drop from P every block already referenced by another block in P   ▷ upstream (own previous block kept)
19:     broadcast block(a, r, P, pending payload)       ▷ upstream
20:     force ← false                                   ▷ upstream
21:   end if
22: end procedure

  Branch S: Mysticeti in Sui v1.58 and v1.74
23: procedure TRYNEWBLOCK(force)                        ▷ upstream; called on every accepted block and on leader timeout
24:   if r ≤ last proposed round then return ⊥          ▷ upstream
25:   if not force then
26:     if the leader block(s) of r−1 are missing or min_round_delay has not passed then return ⊥   ▷ upstream
27:   end if
28:   P ← own previous block, then the newest high-score block of every other authority   ▷ upstream (smart_ancestors_to_propose)
29:   if ATTACK_MODE arms the hook and a is an attacker and ATTACK_TYPE ≠ frontrun then  ▷ hook (gate)
30:     if no b ∈ P has round(b) = r−1 and author(b) ∈ V then   ▷ hook
31:       P ← ∅                                         ▷ hook: defer the whole round
32:     end if                                          ▷ otherwise P is returned unchanged
33:   end if
34:   if not force and (P = ∅ or stake of P at round r−1 < Q) then return ⊥   ▷ upstream; retried on the next accepted block
35:   P ← P ∪ low-score blocks needed to reach Q        ▷ upstream
36:   broadcast block(a, r, P, payload)                 ▷ upstream
37: end procedure
```

## Why every message stays in the legitimate action set
On Mysticeti the attacker's block is the block an honest validator sends after its leader timeout fires: same threshold-clock round, the same pending parents, no leader wait. Block validation checks round, parents and signature, not how long the author waited. In the Sui trees the attacker sends the unmodified upstream block, only later; a validator whose link to the victim is fast and whose link to the leader is slow is in exactly this state. No honest node's code path is touched in either tree.

## Differences between trees
- **Mysticeti (standalone)**: the trigger is any victim block of any round in the batch just processed. The back attacker never runs the front-attacker fissure branch (that branch requires the FrontAttacker role), so under `ATTACK_MODE=fissure` back-running is the timing trigger alone. Under `ATTACK_MODE=sluggish` the back attacker also sleeps before each proposal attempt (`Syncer::try_new_block`, up to 200 ms).
- **Mysticeti in Sui v1.58**: roles follow `ATTACK_TYPE` (layout above). The hook does not check `force`: on a forced proposal with no victim parent it still returns ∅, upstream then fills the quorum only from low-score ancestors and reaches the assert `quorum not reached` (`core.rs` 1571). Under `ATTACK_MODE=speculative` a back attacker keeps the candidate with the smallest digest, a front-runner the largest (`core.rs` 951-953).
- **Mysticeti in Sui v1.74**: no back-attacker role; every attacker in `{0, …, f_a−1}` waits for a victim in `{n−f_v, …, n−1}`. Only modes containing `fissure` arm it, and nodes listed in `FISSURE_BRIBED_NODES` run the same rule. The empty set returns before the upstream quorum fill (`proposer.rs` 408-410), so a forced proposal with no victim parent reaches `assert!(!force, …)` (`proposer.rs` 1342-1345). This tree has no back-run scorer.
- **AlephBFT**: no back-run timing hook. With `ATTACK_TYPE=backrun` the fissure filter is off for every node (`node_is_front_attacker` returns false). A back attacker differs from an honest node only under `speculative` (it keeps the candidate with the larger hash) and `sluggish` (unit-processing delay).
- **Autobahn**: no back-run hook under `fissure`; the fissure, tip-exclusion and leader-support code all skip `ATTACK_TYPE=backrun`. Under `sluggish` the back attacker (`BACK_ATTACKER_ID`, default `ATTACKER_ID` or 2) delays its parent-certificate processing and its own certificate send.
- **Bullshark, Narwhal-Tusk, Mahi-Mahi, Mysticeti in Sui v1.50**: no back-run code.

## Where it is implemented
| Tree (paper name) | File | Function / anchor | Lines |
|---|---|---|---|
| Mysticeti | `code/mysticeti/mysticeti-core/src/core.rs` | `attack_type_from_env`, `attack_counts`, `attack_role` (back-run layout) | 86-145 |
| Mysticeti | `code/mysticeti/mysticeti-core/src/core.rs` | `is_mev_attack_mode` (gate) | 147-149 |
| Mysticeti | `code/mysticeti/mysticeti-core/src/core.rs` | `Core::add_blocks`, back-run trigger (gate at 357) | 355-391 |
| Mysticeti | `code/mysticeti/mysticeti-core/src/core.rs` | `Core::try_new_block` (round check, pending includes) | 416-466, 663-665 |
| Mysticeti | `code/mysticeti/mysticeti-core/src/core.rs` | `ready_new_block` (upstream leader wait) | 961-1008 |
| Mysticeti | `code/mysticeti/mysticeti-core/src/core.rs` | `check_and_reset_immediate_proposal` | 1097-1101 |
| Mysticeti | `code/mysticeti/mysticeti-core/src/syncer.rs` | `Syncer::add_blocks`, `Syncer::try_new_block` (back-run force at 237-245) | 152-173, 190-346 |
| Mysticeti | `code/mysticeti/mysticeti-core/src/attack_tests.rs` | `AttackLayout::new`, `calculate_asr` (L1, L2, cumulative) | 115-151, 382-433 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `Core::new` roles (`"backrun"` arm) | 221-270 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `try_new_block` (leader wait, empty-ancestor check) | 690-787 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `smart_ancestors_to_propose`, hook call | 1375-1580 (call 1451-1455) |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `preprocess_ancestors_for_fissure_attack` (gate 1645-1648; back-run rule 1829-1841) | 1639-1841 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `is_victim_block` | 2065-2095 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/mev_attack_metrics.rs` | `calculate_attack_score`, `AttackType::Backrun` | 148-293 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `ValidatorProposer::new` (`is_attacker`) | 173-208 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `smart_ancestors_to_propose`, hook call and empty return | 392-410 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `preprocess_ancestors_for_fissure_attack` (gate 579-583, 623-625; back-run rule 652-665) | 571-665 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `try_new_block` (leader wait, empty-ancestor assert) | 1302-1351 |
| AlephBFT | `code/alephbft/consensus/src/creation/mod.rs` | `node_is_back_attacker`, speculative criterion | 58-72, 149-162 |
| AlephBFT | `code/alephbft/consensus/src/creation/collector.rs` | `node_is_front_attacker` (false for back-run) | 25-34, 158-160 |
| Autobahn | `code/autobahn-artifact/primary/src/core.rs` | back-run exclusions from fissure (340, 1046, 1129); sluggish actor | 191-197, 874-877 |
| Autobahn | `code/autobahn-artifact/primary/src/proposer.rs` | sluggish parent-processing delay (back attacker for back-run) | 280-310 |
