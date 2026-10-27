# Fissure

The attacker builds its own blocks without referencing the victim's block of the previous round, while still referencing a quorum of other blocks. Its blocks are then valid but carry no support for the victim. On a certified DAG the victim's block reaches the committed order only through the blocks that reference it, so each attacker that leaves it out removes one path by which a leader's causal history can pick it up. The victim's block is then committed under a later leader than the blocks of the same round that the attacker did reference, which puts the attacker's blocks ahead of it. On an uncertified DAG the same omission has the same direction but acts only through the references the attacker's own blocks carry.

| | |
|---|---|
| Clause of the legitimate action set | (i) references |
| Block role | victim |
| Choice | omit the victim's block |
| Has an effect where | certified and uncertified DAGs (DAG-specific) |
| Table II rows | A1.1, A2.1, A3.2, A3.3, A3.4, A4.1, A5.1, A5.2, A6.1, A6.2, A6.3, P1.1, T1.1, T1.2, T2.1, T2.2, T2.3 (Bullshark); A5.4, P1.2 (Mysticeti in Sui v1.74); P2.3 (Autobahn, imported). A1.2 and A1.3 are labelled "fissure + react"; see the note on back-run and sandwich below. |
| Armed by | Bullshark: `attack_type` 1 (delegate) or 2 in the attacker's committee entry, written by the benchmark's `LocalCommittee` when the run's attack type is 1. All other trees: `ATTACK_MODE=fissure` in the environment; only nodes in the attacker index range act. Parameters per tree are listed under Notation. |

## Notation
- `a`: the attacking validator. `r`: the round `a` is about to propose. `Q`: the quorum threshold (`2·total_stake/3 + 1`; 9 at n = 13 with unit stake).
- `P` (certified DAG): the certificates of round `r−1` that `a`'s core forwards to its proposer as parents.
- `A` (uncertified DAG): the ancestor blocks `a` is about to reference, at most one per authority, some of round `r−1` and some older.
- `V`: the victim set. How each tree picks it:
  - Bullshark: the authorities whose committee entry has `attack_type = 0`, in byte order of the 32-byte public key (`Committee.authorities` is a `BTreeMap<PublicKey, _>`). The target is `v = V[0]`, the honest node with the smallest key. `INDEPENDENT=1` gives attacker number `j` (in key order among `attack_type ≠ 0`) the target `V[j mod |V|]`; `RIVAL_GROUPS=G` (G > 1) gives it `V[(j mod G) mod |V|]`; `MULTI_VICTIM=k` (k > 1) excludes the first `k` entries of `V`. Defaults: all unset, one target.
  - Narwhal-Tusk: sort the keys; attackers are the first `⌊n·ATTACKER_RATIO⌋`, victims the next `min(VICTIM_COUNT or ⌊n·VICTIM_RATIO⌋, n − attackers)`. Defaults `ATTACKER_RATIO=0.33`, `VICTIM_RATIO=0.22`.
  - Mysticeti in Sui v1.74, v1.58, v1.50 and Mysticeti (standalone), AlephBFT: attackers are the lowest authority indices, victims the highest. Counts and defaults differ per tree (see Differences).
  - Mahi-Mahi: one attacker `ATTACKER_ID`, one victim `VICTIM_ID` (both unset by default, which disables the hook).
  - Autobahn: one attacker at position `FRONT_ATTACKER_ID` (else `ATTACKER_ID`, default 0) and one victim at position `VICTIM_ID` (default 1) in key order.
- `f_a`, `f_v`: number of attackers and victims as the hook computes them.
- `p`: the exclusion probability. In Mysticeti in Sui v1.74, v1.58, v1.50 and in Autobahn the code computes `p = min(0.95, (1/2 + f_a / (2(n − f_v))) · NF)` with `NF = 7.0` if n ≤ 13, else 6.5. The product is at least 3.25 for any inputs, so `p = 0.95` in every configuration.
- `COIN(b)`: a deterministic number in [0, 1) derived from block `b`: the first 8 bytes of its digest as a little-endian integer, plus `31·round(b) + 17·author(b)`, modulo 10000, divided by 10000. Every attacker draws the same value for the same block.

## Algorithm

The trees implement the same choice at two different places. On the certified Bullshark tree the attacker's core never counts the victim's certificate toward the parent quorum (A.1). On the uncertified Sui trees the proposer removes victim blocks from its ancestor list, but only while the rest still reaches the quorum (A.2).

```text
Algorithm A.1. Fissure on a certified DAG: Bullshark (runs on attacker a only)
 1: procedure ONCERTIFICATE(c)                      ▷ upstream; c passed signature and vote-quorum checks
 2:   if the header inside c is not yet processed then process it   ▷ upstream
 3:   if an ancestor of c is missing then suspend and sync           ▷ upstream
 4:   store c                                                        ▷ upstream
 5:   if attack_type(a) ∈ {1, 2} then                                ▷ hook gate; honest nodes go to line 8
 6:     v ← TARGET(a)                                                ▷ hook
 7:     P ← FISSUREAPPEND(c, v)                                      ▷ hook
 8:   else P ← APPEND(c)                                             ▷ upstream aggregator
 9:   if P ≠ ⊥ then send (P, round(c)) to a's proposer               ▷ upstream
10:   send c to a's own consensus                                    ▷ upstream; a still orders the victim
11: end procedure
12: procedure FISSUREAPPEND(c, v)          ▷ per-round state: list C, weight w, set used, flag emitted
13:   x ← (origin(c) = v), or origin(c) ∈ first k of V when MULTI_VICTIM = k > 1   ▷ hook
14:   if x and not RATIONAL then return ⊥                            ▷ hook: the victim's certificate is never counted
15:   if origin(c) ∈ used then return ⊥                              ▷ upstream
16:   used ← used ∪ {origin(c)}; C ← C ∪ {c}; w ← w + stake(origin(c))   ▷ upstream
17:   if RATIONAL and w ≥ Q then                                     ▷ hook, FISSURE_RATIONAL only
18:     K ← C without the certificate of v
19:     if emitted then C ← ∅; return K if K ≠ ∅, else ⊥             ▷ late extras: never re-admit v
20:     emitted ← true
21:     if stake(K) ≥ Q then C ← ∅; return K                         ▷ omit v, the rest is a quorum
22:     return C and set C ← ∅                                        ▷ keep v rather than stop proposing
23:   end if
24:   if w ≥ Q then                                                  ▷ upstream; w is not reset, so later certificates also pass
25:     if COLLUDE then                                              ▷ hook variant
26:       P ← co-attacker certificates in C, then honest ones until stake(P) ≥ Q; C ← ∅; return P
27:     end if
28:     return C and set C ← ∅                                        ▷ upstream
29:   end if
30:   return ⊥
31: end procedure
32: procedure PROPOSERLOOP                  ▷ upstream; the fissure branch is the honest branch verbatim
33:   on (P, ρ) from core: if ρ > r then r ← ρ and parents ← P; if ρ = r then parents ← parents ∪ P
34:   when parents ≠ ∅ and (timer expired or (enough batch digests and the leader rule allows)) do
35:     r ← r + 1; H ← header(a, r, payload, digests of parents); sign H; send H to core for broadcast
36: end procedure
```

```text
Algorithm A.2. Fissure on an uncertified DAG: Mysticeti in Sui v1.74 (runs on attacker a only)
 1: procedure PROPOSE(r, force)                                      ▷ upstream try_new_block
 2:   if not force then
 3:     if a leader block of round r−1 is not in the local DAG then return   ▷ upstream
 4:     if min_round_delay has not passed since a's last block then return   ▷ upstream
 5:   end if
 6:   A ← a's last block, and for every other authority its latest cached block below round r,
 7:       if newer than the last block a referenced from it and in Include state  ▷ upstream
 8:   A ← FISSUREFILTER(A, r)                                        ▷ hook
 9:   A ← LVWFILTER(A, r)                                            ▷ separate hook (07_lvw.md); returns A unless armed
10:   if not force and stake of the round-(r−1) blocks in A < Q then return     ▷ upstream: wait for more blocks
11:   add Exclude-state ancestors, best score first, until round r−1 reaches Q   ▷ upstream
12:   build block B(r, A, transactions); sign B; broadcast B          ▷ upstream
13: end procedure
14: procedure FISSUREFILTER(A, r)
15:   if ATTACK_MODE does not contain "fissure" or (a ∉ attackers and a ∉ FISSURE_BRIBED_NODES) then
16:     return A                                                     ▷ hook gate
17:   if ATTACK_TYPE ≠ frontrun then                                 ▷ back-run and sandwich: not fissure
18:     return A if A holds a round-(r−1) victim block, else ∅ (defer this proposal)
19:   S ← stake of the round-(r−1) blocks in A
20:   for each b ∈ A, in order, do
21:     if author(b) ∉ V, or RIVAL_GROUPS = G > 1 and b's victim group ≠ a's group then keep b; continue
22:     if GLOBAL_VIEW then                                          ▷ hook variant, A4 information
23:       if at least GLOBAL_VIEW_COVER attackers already counted (round(b), author(b)) then keep b; continue
24:       count (round(b), author(b)) once more in the pool shared by the attackers
25:     end if
26:     x ← COIN(b)
27:     if round(b) = r−1 then
28:       if S − stake(b) ≥ Q + ⌊Q/5⌋ then q ← p
29:       else if S − stake(b) ≥ Q then q ← p/2
30:       else q ← 0                                                 ▷ never break the parent quorum
31:       if x < q then drop b; S ← S − stake(b) else keep b
32:     else if x < min(p, 0.98) then drop b                         ▷ older victim blocks
33:     else keep b
34:   end for
35:   return the kept blocks
36: end procedure
```

Notes on A.1. Attack types 1 and 2 run the same exclusion; type 1 only adds the benchmark log markers ("FairDag Created a fissure attacking header"). The victim monitor (`ATTACKING_INTERVAL = 7`, `is_attacking`) feeds only those markers, so the exclusion runs in every round. The published Bullshark cells run with `FISSURE_RATIONAL` and `COLLUDE` unset (PROVENANCE.md), so lines 14, 24 and 28 are the measured path: the attacker proposes only once the non-victim certificates alone reach `Q`, and it never falls back to the victim. Under `FISSURE_RATIONAL=1` the filter on line 18 removes only the single target `v`, even when `MULTI_VICTIM` is set. `FR_GRIND=1` adds a separate parent-subset grind in `make_header` that also applies to type-1 nodes; it is not part of fissure.

Notes on A.2. With `V2_COORDINATOR_URL` set, a coordinator can mark an attacker passive for a round (return `A`), and a per-victim profit threshold can keep a victim block; both are skipped when the variable is unset.

## Why every message stays in the legitimate action set
A correct validator whose link to the victim is slow does not have the victim's certificate (or block) when its quorum of round-`r−1` parents is complete, and it proposes with the parents it has. The attacker's header or block is exactly such a proposal. It still references at least `Q` stake of round `r−1`, so it passes the unchanged parent check on every honest node (Bullshark `process_header`, Sui `block_verifier.rs`), and its signature and payload are the attacker's own. Honest nodes keep receiving, voting for and referencing the victim's blocks as usual; only the attacker's own reference set changes.

## Differences between trees
- **Bullshark**: hooked in the certificate aggregator, not the proposer. Deterministic. On the default path the attacker waits for a victim-free quorum and never includes the victim. When too few non-victim certificates exist the attacker cannot advance, which FINDINGS.md records as an attacker stall; `FISSURE_RATIONAL=1` replaces this with "omit only if the rest is a quorum". Arming comes from the committee file, not an environment variable.
- **Narwhal-Tusk**: hooked in `Proposer::make_header`. The victim is dropped when `digest[0]/255 < min(0.85, (1/2 + f_a/(2(n − f_v))) · FISSURE_NETWORK_FACTOR · FISSURE_DECAY_RATE^r)` (defaults 1.0 and 0.99), and at most `|P| − (2f+1)` parents are dropped, with `f = ⌊(n−1)/3⌋`. The aggregator hands the proposer exactly the first set of certificates that reaches `Q` and resets its weight, and with equal stake and n = 3f+1 that set has `2f+1` entries. The `should_exclude_victim` method in `aggregators.rs` is never called.
- **Mysticeti in Sui v1.74**: Algorithm A.2. Defaults `ATTACKER_RATIO=0.33` and `VICTIM_RATIO=0.2`, both floored. `FISSURE_BRIBED_NODES` (indices) makes the listed honest-index nodes run the same filter; `V2_BRIBED_HONEST` with a coordinator offer drops every victim ancestor. Those are the bribery variants (see the bribery file).
- **Mysticeti in Sui v1.58**: same filter, with two differences. A parent-round victim is dropped with probability `p` whenever the rest is at least `Q` (no `Q + ⌊Q/5⌋` tier). The filter runs when `ATTACK_MODE` is `fissure`, `speculative` or `sluggish`, so speculative and sluggish attackers in this tree also omit victims. `REVERSE_LAYOUT=1` moves attackers to the highest indices and victims to the lowest; `V2_VICTIM_NODE_IDS` replaces the victim set with a list. Defaults `ATTACKER_RATIO=0.33`, `VICTIM_RATIO=0.22`, floored.
- **Mysticeti in Sui v1.50**: same filter as v1.74, including the `Q + ⌊Q/5⌋` tier. The hook re-reads its own defaults (`ATTACKER_RATIO=0.3`, `VICTIM_RATIO=0.2`), while the constructor uses 0.33; with the ratio unset, n = 13 gives 3 attackers in the hook and 4 in the constructor.
- **Mysticeti (standalone)**: deterministic, wave-aware. Victim blocks from rounds `r − 2w` to `r` (w = wave length) are targets when they sit in the current wave, in the previous wave's decision round, within one round of `r`, or in a leader or decision round (the last two only from round 3 on). The attacker first references non-victim blocks that do not reference a target, then its co-attackers, and adds blocks that do reference a target, then target blocks, only until round `r−1` reaches `Q`. Other victim blocks are dropped with probability `EXCLUSION_PROBABILITY` (default 0.8, `thread_rng`) unless needed for the quorum. Blocks of rounds ≤ 2 are always kept. This tree also omits honest blocks that reference a target, which goes beyond Table I's "omit the victim's block".
- **Mahi-Mahi**: one attacker, one victim. Each victim include is dropped with probability `EXCLUSION_PROBABILITY` (default 0.85, `thread_rng`). After the loop, if the remaining round-`(r−1)` includes do not reach `Q`, every dropped include is put back (commit 190e9c58).
- **AlephBFT**: hooked in `UnitsCollector::prospective_parents_filtered`. Attackers are the first `round(n·0.308)` indices, victims the last `round(n·0.231)`. Round-`(r−1)` victims are dropped with probability 1.0 when all of them can go and `Q` remains, else 0.99 or 0.96; older victim units with probability 1.0. If the round-`(r−1)` count then falls below the threshold, the full candidate set is used. The paper formula is computed (`NF = 12.0` or 10.0, cap 0.995) but the result is not used.
- **Autobahn**: the attacker acts only as slot leader, when it fills the `proposals` (lane tips) of a `Prepare` in its own header. It removes the victim's tip with probability 0.95 when the rest still covers `Q`, and with probability 0.76 when it does not. A second branch in `process_own_header` ("TIP_EXCLUSION") compares the origin of the attacker's own header with the victim, so it never fires.
- **Back-run and sandwich ("fissure + react", A1.2 and A1.3)**: with `ATTACK_TYPE=backrun` or `sandwich`, the Sui v1.74 and v1.58 hooks drop nothing. They hold the proposal until a victim block of round `r−1` is present (Algorithm A.2, line 17). In Mysticeti (standalone) a back-run run has no front attackers, so the exclusion branch does not run; sandwich front attackers do run it.

## Where it is implemented
| Tree (paper name) | File | Function / anchor | Lines |
|---|---|---|---|
| Bullshark | `code/bullshark-flashboys/config/src/lib.rs` | `Authority.attack_type`, `Committee.authorities: BTreeMap` | 131-146 |
| Bullshark | `code/bullshark-flashboys/benchmark/benchmark/config.py` | `LocalCommittee`, attack type 1 layout | 166-169 |
| Bullshark | `code/bullshark-flashboys/primary/src/attacks.rs` | `FISSURE_ATTACK`, `victims`, `target_victim` | 13-15, 47-71 |
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | gate and call in `process_certificate` | 454-474 |
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | `fissure_target_victim` (`INDEPENDENT`, `RIVAL_GROUPS`) | 361-420 |
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | upstream parent check in `process_header` | 172-184 |
| Bullshark | `code/bullshark-flashboys/primary/src/aggregators.rs` | `fissure_attack_append` (`MULTI_VICTIM`, `FISSURE_RATIONAL`, `COLLUDE`) | 95-205 |
| Bullshark | `code/bullshark-flashboys/primary/src/aggregators.rs` | `select_colluder_quorum` | 210-239 |
| Bullshark | `code/bullshark-flashboys/primary/src/proposer.rs` | fissure branch of `run` (same as honest) | 514-534 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/proposer.rs` | config, attacker and victim sets | 96-116, 167-216 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/proposer.rs` | `preprocess_parents_with_origins`, `calculate_exclusion_probability` | 283-341, 404-431 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/proposer.rs` | gate in `make_header` | 441-446 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/aggregators.rs` | `append` (one quorum per round), unused `should_exclude_victim` | 105-142, 146-190 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | constructor: `ATTACK_MODE`, `is_attacker` | 172-208 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | call in `smart_ancestors_to_propose`, quorum wait | 393-394, 412-429 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `preprocess_ancestors_for_fissure_attack` (gate at 623) | 571-825 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `is_victim_block`, `calculate_exclusion_probability`, `should_exclude_victim_block` | 938-942, 1099-1111, 1116-1134 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | upstream leader wait and min delay in `try_new_block` | 1302-1338 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/block_verifier.rs` | upstream parent-quorum check | 136-146 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | constructor (`REVERSE_LAYOUT`) | 220-270 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | call in `smart_ancestors_to_propose` | 1451-1456 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `preprocess_ancestors_for_fissure_attack` (gate at 1646, 1656) | 1639-2050 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `is_victim_block` (`V2_VICTIM_NODE_IDS`), probability, coin | 2065-2094, 2097-2128, 2141-2168 |
| Mysticeti in Sui v1.50 | `code/mevsui/consensus/core/src/core.rs` | `preprocess_ancestors_for_fissure_attack` (gate at 1430, 1450-1452) | 1423-1561 |
| Mysticeti (standalone) | `code/mysticeti/mysticeti-core/src/core.rs` | `attack_counts`, `attack_role` | 97-145 |
| Mysticeti (standalone) | `code/mysticeti/mysticeti-core/src/core.rs` | wave-aware fissure in `try_new_block` (gate at 481) | 443-446, 481-664 |
| Mahi-Mahi | `code/mahi-mahi-consensus/crates/mysticeti-core/src/core.rs` | config, drop (gate at 313), quorum restore | 272-287, 305-333, 370-382 |
| AlephBFT | `code/alephbft/consensus/src/creation/creator.rs` | `create_unit` switch | 51-60 |
| AlephBFT | `code/alephbft/consensus/src/creation/collector.rs` | `node_is_front_attacker`, `node_is_victim` | 25-45 |
| AlephBFT | `code/alephbft/consensus/src/creation/collector.rs` | `prospective_parents_filtered` (gates at 131-135, 158) | 116-297 |
| Autobahn | `code/autobahn-artifact/primary/src/core.rs` | `participant_keys` (attacker and victim positions) | 170-189 |
| Autobahn | `code/autobahn-artifact/primary/src/core.rs` | fissure in `set_consensus_proposal` (`Prepare` only), called from `process_own_header` and `send_consensus_req` | 386-389, 1015-1019, 1045-1120, 1251-1253 |
| Autobahn | `code/autobahn-artifact/primary/src/core.rs` | unreachable "TIP_EXCLUSION" branch | 335-384 |
