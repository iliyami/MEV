# Sandwich

The attacker surrounds a victim's block with one attacker block before it and one after it in the committed order. The trees split the attackers into a front half and a back half: the front half sits at the lowest indices, then come the victims, then the back half. On standalone Mysticeti the front half runs fissure against the victims (it leaves victim blocks, and honest blocks that reference them, out of its parents while the quorum allows), which delays the victims, and the back half runs the back-run trigger, which proposes as soon as a victim block arrives. In the Mysticeti in Sui v1.58 tree there is no exclusion: both halves hold every proposal until a victim's previous-round block is a parent. That tree orders the blocks of one commit by (round, author), and the layout puts front attackers below and back attackers above the victims, so a same-round triplet committed in one sub-DAG is already ordered front, victim, back by the tiebreak.

| | |
|---|---|
| Clause of the legitimate action set | (i) references for the front half (fissure; Mysticeti, AlephBFT, Autobahn) and (iii) timing for the back half (Mysticeti; both halves in Sui v1.58) |
| Block role | victim (front half) and own (back half) |
| Choice | Not a row of Table I. Front half: omit the victim's block (the fissure row of Table I). Back half: propose as soon as a victim block arrives (Mysticeti), or wait until a round r−1 victim block is a parent (Sui v1.58, both halves). |
| Has an effect where | Not a row of Table I. Measured on Sui v1.58 (A1.3) and, in the action figure, on Sui v1.58, Mysticeti, AlephBFT and Autobahn. |
| Table II rows | A1.3 (imported from the benchmark paper) |
| Armed by | `ATTACK_TYPE=sandwich` together with an attack mode: `ATTACK_MODE` in {`fissure`, `speculative`, `sluggish`, `certification_race`} (Mysticeti; the front-half exclusion needs `fissure`), in {`fissure`, `speculative`, `sluggish`} (Sui v1.58), or any value containing `fissure` (Sui v1.74). Parameters `ATTACKER_RATIO` (code default 0.33), `VICTIM_RATIO` (code default 0.22), `EXCLUSION_PROBABILITY` (Mysticeti front half, default 0.8); campaign configs set 0.308 and 0.231. Scorer only: `SANDWICH_METRIC_MODE` (default `strict`; `triplet` for A1.3), `SANDWICH_GAP_K` (default 0), `SANDWICH_INTERLEAVE` (Mysticeti scorer, unset by default). All validators of a test share one environment; each hook acts only on nodes whose index is in its range. |

## Notation
- `a`: the attacking validator. `r`: the round being proposed (threshold-clock round). `n`: committee size. `w`: wave length (Mysticeti, `WAVE_LENGTH`, 3 in the campaign config).
- `f_a = ⌊n · ATTACKER_RATIO⌋`, `f_v = ⌊n · VICTIM_RATIO⌋`; `h = ⌊f_a / 2⌋`.
- Layout (Mysticeti `attack_role`, Sui v1.58 `Core::new` and `is_victim_block`, AlephBFT): front half `F = {0, …, h−1}`, victims `V = {h, …, h+f_v−1}`, back half `B = {h+f_v, …, h+f_v+(f_a−h)−1}`. At n = 13 with 0.308 and 0.231: `F = {0,1}`, `V = {2,3,4}`, `B = {5,6}`.
- `Q`: quorum threshold. `s`: stake already counted at round r−1 in the parent set being built.
- `p_x = EXCLUSION_PROBABILITY` (default 0.8).
- Scoring (not run by validators), with `g = 6` under `ATTACK_MODE=sluggish` and `g = 0` otherwise:
  - `triplet`: over every triple (x ∈ F blocks, v ∈ V blocks, y ∈ B blocks) with `0 ≤ round(v) − round(x) ≤ g` and `0 ≤ round(y) − round(v) ≤ g`, the share with `pos(x) < pos(v) < pos(y)`.
  - `strict` (default): share of victim blocks with an F block within `SANDWICH_GAP_K + 1` positions before and a B block within `SANDWICH_GAP_K + 1` positions after, under the same round bounds.

## Algorithm
```text
Algorithm B. Sandwich (runs on attackers a ∈ F ∪ B only)

  Branch M: Mysticeti (standalone reference implementation)
 1: if a ∈ B then run Algorithm A, Branch M (back-run), with V and B as above   ▷ hook (iii)
 2: procedure PARENTS(r)                                ▷ inside Core::try_new_block, a ∈ F and ATTACK_MODE = fissure
 3:   C ← own previous block ∪ pending includes up to the first one of round ≥ r   ▷ upstream
 4:   T ← victim blocks of rounds r−2w … r that are in the current wave, or in the previous
          wave's decision round, or within one round of r (round ≥ 3), or at a leader or
          decision position (round ≥ 3)                 ▷ hook
 5:   s ← stake(a)                                      ▷ hook
 6:   for each x ∈ C other than own previous block do  ▷ hook: classify
 7:     if round(x) ≤ 2 then x is clean honest
 8:     else if author(x) ∈ F ∪ B then x is attacker
 9:     else if author(x) ∉ V then x is dirty honest if one of its includes is in T, else clean honest
10:     else x is target victim if x ∈ T, else other victim
11:     if x is clean honest or attacker and round(x) = r−1 then s ← s + stake(x)
12:   end for
13:   P ← own previous block ∪ clean honest ∪ attacker  ▷ hook
14:   for each dirty honest x, then each target victim x, while s < Q do   ▷ hook: only to reach Q
15:     P ← P ∪ {x}; if round(x) = r−1 then s ← s + stake(x)
16:   end for
17:   for each other victim x do                        ▷ hook
18:     if round(x) = r−1 and s < Q then P ← P ∪ {x}; s ← s + stake(x)
19:     else with probability p_x drop x, otherwise P ← P ∪ {x} (and add its stake if round(x) = r−1)
20:   end for
21:   return P                                          ▷ then upstream: compress, sign, broadcast
22: end procedure

  Branch S: Mysticeti in Sui v1.58
23: for every a ∈ F ∪ B: run Algorithm A, Branch S      ▷ hook (iii): no proposal for round r
                                                        ▷ until a round r−1 block by some v ∈ V is a parent;
                                                        ▷ no block is excluded
24: if ATTACK_MODE = sluggish and a ∈ B then sleep leader_timeout · SLUGGISH_TIMEOUT_MULTIPLIER before proposing   ▷ hook
25: if ATTACK_MODE = speculative then keep the payload order whose digest is largest (a ∈ F) or smallest (a ∈ B)   ▷ hook (ii)
```

## Why every message stays in the legitimate action set
The front half sends blocks whose parents are a subset of what it has received and still carry a round r−1 quorum, which is what a validator with a slow link to the victims would send; Mysticeti checks parents and signature, not which blocks were left out. The back half sends the unmodified upstream block, either early (as after a leader timeout, Mysticeti) or late (as with a slow leader link, Sui v1.58). No honest node's validation, voting or commit logic is touched.

## Differences between trees
- **Mysticeti (standalone)**: front half excludes (Branch M) and back half reacts (Algorithm A). Under `ATTACK_MODE=sluggish` only the back half sleeps (`syncer.rs` 250-253). The front-half rule also leaves out honest blocks that reference a targeted victim block, and drops non-targeted victim blocks at random with `p_x`. `SANDWICH_INTERLEAVE=1` changes only the scorer's role vector (`attack_tests.rs`, front, victim, back repeated: at n = 13 the scorer reads F = {0,3}, V = {1,4,6}, B = {2,5}); the validators' roles in `core.rs` and `syncer.rs` stay contiguous (F = {0,1}, V = {2,3,4}, B = {5,6}), so with the flag set the scorer labels differ from the nodes that run the hooks.
- **Mysticeti in Sui v1.58**: both halves wait for a victim parent; no exclusion under `fissure`. Inside one commit the order is `(round, author)` (`commit.rs` 418-422), which with this layout already orders a same-round F, V, B triple within one sub-DAG. The same forced-proposal caveat as for back-run applies (Algorithm A, `core.rs` 1571).
- **Mysticeti in Sui v1.74**: no front/back split. Every attacker in `{0, …, f_a−1}` waits for a victim in `{n−f_v, …, n−1}` exactly as in back-run; there is no sandwich scorer except the within-sub-DAG count in `mysticeti_lvw_attack_test.rs` (an LVW test, a different metric).
- **AlephBFT**: front half (`node < h`, counts use `round()` instead of floor) runs the fissure parent filter; the back half has no timing hook. Under `speculative` the back half keeps the candidate with the larger hash, the front half the smaller.
- **Autobahn**: one front attacker (`FRONT_ATTACKER_ID`, default `ATTACKER_ID` or 0) runs fissure and tip exclusion against one victim (`VICTIM_ID`, default 1); the back attacker (`BACK_ATTACKER_ID`, default `ATTACKER_ID` or 2) has a hook only under `sluggish`.
- **Bullshark, Narwhal-Tusk, Mahi-Mahi, Mysticeti in Sui v1.50**: no sandwich code.

## Where it is implemented
| Tree (paper name) | File | Function / anchor | Lines |
|---|---|---|---|
| Mysticeti | `code/mysticeti/mysticeti-core/src/core.rs` | `attack_role` (sandwich layout) | 111-145 |
| Mysticeti | `code/mysticeti/mysticeti-core/src/core.rs` | back-half trigger in `Core::add_blocks` (gate 357) | 355-391 |
| Mysticeti | `code/mysticeti/mysticeti-core/src/core.rs` | front-half fissure in `Core::try_new_block` (gate 481) | 481-665 |
| Mysticeti | `code/mysticeti/mysticeti-core/src/syncer.rs` | back-half force (237-245); sluggish role (250-253) | 190-346 |
| Mysticeti | `code/mysticeti/mysticeti-core/src/attack_tests.rs` | `interleaved_sandwich`, `AttackLayout::new` (`SANDWICH_INTERLEAVE` 134-141) | 69-151 |
| Mysticeti | `code/mysticeti/mysticeti-core/src/attack_tests.rs` | `sandwich_gap_k`, `sandwich_metric_mode`, triplet and strict scoring | 189-198, 437-526 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `Core::new` roles (`"sandwich"` arm) | 251-258 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | sluggish delay, back half only (gate 657-662) | 655-671 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | speculative digest preference | 951-953 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `preprocess_ancestors_for_fissure_attack` (wait rule 1829-1841) | 1639-1841 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `is_victim_block` (sandwich arm 2080-2084) | 2065-2095 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/commit.rs` | intra-commit sort `(round, author)` | 418-422 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/mev_attack_metrics.rs` | layout, `sandwich_metric_mode`, `AttackType::Sandwich` scoring | 73-82, 112-122, 295-385 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `preprocess_ancestors_for_fissure_attack` (rule 652-665) | 571-665 |
| AlephBFT | `code/alephbft/consensus/src/creation/collector.rs` | `node_is_front_attacker`, fissure filter gate | 25-34, 116-160 |
| AlephBFT | `code/alephbft/consensus/src/creation/mod.rs` | `node_is_back_attacker`, speculative criterion | 58-72, 149-162 |
| Autobahn | `code/autobahn-artifact/primary/src/core.rs` | `participant_keys`, tip exclusion, fissure | 170-189, 335-345, 1046 |
