# Sluggish

The attacker runs slow on purpose: it delays its own proposals, and in some trees also its processing of incoming blocks, so its block for a round leaves later than the other validators' blocks of that round. The code comments state the intent as lagging behind the honest majority, so that the attacker's blocks carry a lower round (or height) than the victim's blocks proposed at the same time. Under a round-first linearization a lower round is ordered earlier. Every block the attacker sends is built by the unmodified proposal path; only the moment it is built changes. How the delay is produced differs a lot between trees: a non-blocking hold (Mysticeti in Sui v1.74), a blocking sleep of the proposing thread (Mysticeti in Sui v1.58 and v1.50, Mysticeti, Mahi-Mahi), a longer header timer (Narwhal-Tusk, Bullshark), or a delay on processing incoming units or certificates (AlephBFT, Autobahn).

| | |
|---|---|
| Clause of the legitimate action set | (iii) timing |
| Block role | own |
| Choice | run slow, delaying its proposals |
| Has an effect where | leader-anchored DAGs, Mysticeti here (general) |
| Table II rows | A2.3 (Mahi-Mahi) |
| Armed by | `ATTACK_MODE=sluggish` in every tree, plus a per-tree attacker selector and delay parameter (see Notation). In the Sui trees, Mysticeti, AlephBFT and Narwhal-Tusk the attacker set is the first validators by index (or by sorted key); in Mahi-Mahi and Autobahn it is one index (`ATTACKER_ID`); in Bullshark it is the committee file's `attack_type` 3 or 4. Parameters: `SLUGGISH_TIMEOUT_MULTIPLIER` (Sui trees, Mysticeti, Narwhal-Tusk, Autobahn), `SLUGGISH_MULTIPLIER` (Mahi-Mahi), `SLUGGISH_PROCESSING_DELAY_MS` (AlephBFT); Bullshark has a hard-coded factor 2 |

## Notation
- `a`: the attacking validator. `A`: the attacker set.
  - Sui v1.74, v1.58, v1.50: indices `< floor(n · ATTACKER_RATIO)` (default `ATTACKER_RATIO` 0.33). In v1.74 and v1.50 `a ∈ A` also requires `ATTACK_MODE` to be an attack mode; in v1.58 the index rule alone sets `is_attacker`, and the hook also checks `attack_active`. v1.58 with `ATTACK_TYPE=sandwich` delays only the back attackers. With `V2_COORDINATOR_URL` set (v1.74, v1.58), the coordinator assigns the mode, the attacker flag and `sluggish_timeout_multiplier` instead.
  - Mysticeti: indices `< floor(n · ATTACKER_RATIO)` (default 0.33) for front-running and back-running layouts; only the back attackers for `ATTACK_TYPE=sandwich`.
  - Mahi-Mahi: the single index `ATTACKER_ID`; if `ATTACKER_ID` is unset no node is an attacker.
  - Narwhal-Tusk: the first `floor(n · ATTACKER_RATIO)` public keys in sorted order (default 0.33).
  - Autobahn: the single key at position `FRONT_ATTACKER_ID` (else `ATTACKER_ID`, default 0) of the key-ordered committee for front-running; `BACK_ATTACKER_ID` (else `ATTACKER_ID`, default 2) for back-running and sandwich.
  - AlephBFT: indices `< round(n · ATTACKER_RATIO)` (default 0.308) for front-running.
  - Bullshark: nodes whose committee entry has `attack_type` 3 (one node) or 4 (the rest); the benchmark assigns them to the last `faults + arbitragers` names.
- `m`: the multiplier. Sui v1.74 and v1.58 panic if `SLUGGISH_TIMEOUT_MULTIPLIER` is unset when `ATTACK_MODE=sluggish`; the v1.74 test sets 2.0 if unset, the v1.58 test sets 1.5 if unset, the v1.50 core also panics and its test does not set it. Mysticeti, Narwhal-Tusk and Autobahn's proposer default to 2.0; Autobahn's core defaults to 5.0 (and its `run_attack_test.sh` passes 5.0). Mahi-Mahi `SLUGGISH_MULTIPLIER` defaults to 2.0.
- `τ`: the leader timeout, `Parameters::default_leader_timeout()` = 200 ms in all three Sui trees.
- `D`: `max_header_delay` (Narwhal-Tusk, Bullshark, Autobahn node parameter; 100 ms config default in all three; 200 ms in the Narwhal-Tusk and Bullshark benchmark fabfiles; 100 ms in Autobahn's `run_attack_test.sh`).
- `r_clock`: the threshold-clock round (the round `a` would propose). `r_last`: the round of `a`'s last proposed block.
- `t_ready`: Sui v1.74 only, the instant before which the held proposal may not go out (`sluggish_ready_at`), initially ⊥.

## Algorithm
```text
Algorithm C. Sluggish, Mysticeti-family trees (Sui v1.74, Sui v1.58, Sui v1.50, Mysticeti, Mahi-Mahi)
 1: procedure TRYPROPOSE(force)            ▷ upstream entry: after accepting blocks, on a leader timeout, at recovery
 2:   if ATTACK_MODE = sluggish and a ∈ A then                     ▷ hook: gate; disarmed nodes go to line 13
 3:     d ← DELAY(r_clock, r_last)                                 ▷ hook, lines 17-22
 4:     if tree = Sui v1.74 then                                   ▷ hook: hold without blocking the thread
 5:       if t_ready = ⊥ then
 6:         t_ready ← now + d; return ⊥                            ▷ hook: start a hold, no block now
 7:       else if now < t_ready then
 8:         return ⊥                                               ▷ hook: still holding
 9:       else t_ready ← ⊥                                         ▷ hook: release and fall through
10:       end if
11:     else sleep(d) on the thread that runs the core             ▷ hook: Sui v1.58, v1.50, Mysticeti, Mahi-Mahi; blocking
12:   end if
13:   if not READY(force) then return ⊥                            ▷ upstream readiness checks, unchanged
14:   B ← BUILD(r_clock)                                           ▷ upstream: parents, payload, timestamp, signature
15:   broadcast B                                                  ▷ upstream
16: end procedure
17: function DELAY(r_clock, r_last)
18:   Sui v1.74, v1.58, v1.50: return ⌊m · τ⌋
19:   Mysticeti: w ← 1.2, 1.0, 1.3 for r_clock mod 3 = 0, 1, 2
20:              return min(200 ms, ⌊3 · m · 25 ms · w⌋)           ▷ 3 is commit_period; fixed to 3 in attack_tests.rs
21:   Mahi-Mahi: if r_clock − r_last > 1 then return 0 else return ⌊10 ms · m⌋
22: end function
```
Line 13 is the tree's own check: in Sui, `should_propose`, then `r_clock > r_last`, then (unless `force`) the leader of round `r_clock − 1` is present and `min_round_delay` has passed; in Mysticeti and Mahi-Mahi, `force_new_block` or `ready_new_block(commit_period, …)`. In Sui v1.74 the hook sits inside `try_new_block` after the silent-except-leader hook and before the SLW hook. A released call (line 9) that then fails line 13 leaves `t_ready = ⊥`, so the next call starts a new full hold. In Sui v1.58 and v1.50 the sleep runs at the top of `Core::try_propose`, before `should_propose`, on every call, whether or not a block results; the core handles no other message while it sleeps.

```text
Algorithm C.2. Sluggish, Narwhal-Tusk (proposer task of attacker a)
 1: at spawn: if ATTACK_MODE = sluggish and a ∈ A then D ← ⌊D · m⌋        ▷ hook: longer header timer
 2: loop                                                                   ▷ upstream proposer loop
 3:   if a ∈ A then propose ← P ≠ ∅ and (v_round > r or timer expired)    ▷ hook: the "header full" trigger is ignored
 4:   else propose ← P ≠ ∅ and (timer expired or header full)             ▷ upstream
 5:   if propose then MAKEHEADER(r, P); reset timer to now + D             ▷ upstream (D from line 1)
 6:   on parents (P′, r′) from own core:                                   ▷ upstream event
 7:     r_h ← max(r_h, r′)                                                 ▷ hook: highest parent round seen
 8:     if r′ < r then continue                                            ▷ upstream
 9:     if a ∈ A and r_h − r < 1 then await sleep(D)                       ▷ hook: async sleep of the proposer task
10:     if a ∈ A and not proposed in r and P ≠ ∅ then MAKEHEADER(r, P)     ▷ hook: send the late round-r header
11:     r ← r′ + 1; P ← P′                                                 ▷ upstream: advance
12:   on victim header round v from own core:                              ▷ hook: own core forwards victims' header rounds
13:     v_round ← v
14:     if v > r and not proposed in r and P ≠ ∅ then
15:       MAKEHEADER(r, P); reset timer to now + D                         ▷ hook: propose at once in the lower round
```

```text
Algorithm C.3. Sluggish, Bullshark (proposer of a node with attack_type 3 or 4)
 1: loop                                                                   ▷ upstream proposer loop
 2:   if (timer expired or (header full and advance)) and P ≠ ∅ then      ▷ upstream trigger, unchanged
 3:     r ← r + 1; MAKEHEADER(r, P)                                        ▷ upstream
 4:     if attacking then reset timer to now + D                           ▷ hook: normal pace while a target is pending
 5:     else reset timer to now + 2 · D                                    ▷ hook: SLUGGISH_DELAY_MULTI_FACTOR = 2
 6:   on header h from own core, with author(h) = V[0] and round(h) mod 7 = 0:   ▷ hook: V = attack_type 0 nodes in key order
 7:     if not attacking and r ≤ round(h) then remember h; attacking ← true
 8:   on certificate c committed (from the garbage collector):
 9:     if round(c) ≥ round(remembered h) then attacking ← false           ▷ hook
```

```text
Algorithm C.4. Sluggish, AlephBFT (unit creator of attacker a)
 1: procedure PROCESSUNIT()                     ▷ upstream: called while waiting the creation delay and until the unit can be built
 2:   if ATTACK_MODE = sluggish and a ∈ A then                              ▷ hook
 3:     δ ← SLUGGISH_PROCESSING_DELAY_MS, default 10 ms (tests and scripts set 11)
 4:     if 0 < δ < 15 ms then await Delay(δ)                                ▷ hook: async, before every incoming unit
 5:   u ← next unit from incoming_parents; add u to the creator's view     ▷ upstream
```

```text
Algorithm C.5. Sluggish, Autobahn (core and proposer of attacker a)
 1: on own car certificate ready (dissemination and consensus ready):      ▷ upstream, in Core::process_vote
 2:   if ATTACK_MODE = sluggish and a is the attacker then
 3:     await sleep(100 ms · m)                                            ▷ hook: m default 5.0; the core task waits
 4:   send the certificate to own proposer                                 ▷ upstream
 5: on own certificate from own core, height ≥ current height:             ▷ upstream, in the proposer
 6:   if ATTACK_MODE = sluggish and a is the attacker then
 7:     await sleep(D · m)                                                 ▷ hook: m default 2.0
 8:   height ← height + 1; last_parent ← certificate                       ▷ upstream
```

## Why every message stays in the legitimate action set
A correct validator with a slow CPU, a slow disk or a slow link proposes late, and processes incoming blocks late, in exactly the way these hooks emulate. Every block the attacker sends is produced by the upstream build path from blocks it really holds, so parent rules, quorum checks, timestamp checks and signatures pass unchanged at every receiver. Honest validators accept a late block of a lower round on their normal path; none of their code is changed. In the Sui trees the hold also applies to forced (leader-timeout) calls, which only makes the attacker later still.

## Differences between trees
- **Mysticeti in Sui v1.74**: delay `m · τ` (400 ms at the test default m = 2.0) measured from the first call after the previous release. It does not block the thread, so the attacker keeps accepting blocks during the hold. This replaced a blocking `std::thread::sleep` in commit 5f7fa05f, whose message says the sleep stalled a tokio worker shared with the co-hosted honest validators in the test harness.
- **Mysticeti in Sui v1.58** and **Mysticeti in Sui v1.50**: still use the blocking `std::thread::sleep(m · τ)` at the top of `Core::try_propose`. It runs on every call (every batch of accepted blocks, every leader timeout, recovery), so the lag per round can be several multiples of `m · τ`, and the core processes no incoming block while sleeping. The core runs as a tokio task (`spawn_logged_monitored_task`), so in the in-process tests the sleep also holds a tokio worker thread.
- **Mysticeti (standalone)**: delay is not tied to the leader timeout. It is `min(200 ms, ⌊75 ms · m · w⌋)` with `w` depending on `r_clock mod 3` (180, 150, 195 ms at m = 2.0), slept on the core thread before every readiness check.
- **Mahi-Mahi**: one attacker (`ATTACKER_ID`), variable `SLUGGISH_MULTIPLIER` (not `SLUGGISH_TIMEOUT_MULTIPLIER`), delay `10 ms · m` (20 ms at the default) and 0 when the attacker is already more than one round behind its own clock. `ATTACK_MODE=hybrid_sluggish` adds a probabilistic victim-exclusion step in `core.rs`; that is a fissure-like variant, not this primitive.
- **Narwhal-Tusk**: the header timer becomes `m · D`, the "header full" trigger is dropped, and on each new parent set the proposer sleeps `m · D` unless it is already one round behind the highest parent round it has seen. It also proposes at once in its lower round when its own core reports a victim header of a higher round. The attacker's own core forwards victim header rounds (`tx_victim_round`); victims are the keys after the attackers in sorted order.
- **Bullshark**: the original Zhang and Kate logic. No multiplier variable; the timer after each header is `2 · D` while no target header is pending and `D` while one is. The upstream trigger still fires as soon as the header is full and `advance` holds, so the slow timer binds only when headers are not full or the leader condition is not met.
- **AlephBFT**: a fixed per-unit processing delay, not a multiple of anything. Values of 15 ms or more, and 0, are silently ignored (no delay). The upstream creation-delay schedule is unchanged.
- **Autobahn**: two async delays, one before the core hands the attacker's own car certificate to its proposer (100 ms · m, default m = 5.0), one before the proposer advances its height on that certificate (`D · m`, default m = 2.0). Both read the same variable but with different defaults. The core's sleep is awaited inside `process_vote`, so the attacker's core handles no other message, including others' headers it would vote on, until it ends.
- `PROPOSAL_JITTER=1` (Mysticeti, Mahi-Mahi) adds a random 0 to 5 ms sleep before every node's proposal, honest or not. It is off by default and is not part of this primitive.

## Where it is implemented
| Tree (paper name) | File | Function / anchor | Lines |
|---|---|---|---|
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `ValidatorProposer::new`: `ATTACK_MODE`, `ATTACKER_RATIO`, `SLUGGISH_TIMEOUT_MULTIPLIER`, `attack_active`, `is_attacker` | 172-208 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | coordinator override of mode and multiplier | 212-254 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `try_new_block`, sluggish hold (gate at 1194) | 1191-1215 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `try_new_block`, upstream checks after the hooks | 1239-1334 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/core.rs` | `Core::try_propose` and its callers (`add_blocks`, `add_certified_commits`, `new_block`, recovery) | 596-610; 279, 422, 465, 547 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/config/src/parameters.rs` | `default_leader_timeout` = 200 ms | 131-133 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/sluggish_attack_test.rs` | test default m = 2.0, sets `ATTACK_MODE=sluggish` | 83-96 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `Core::new`: attacker layout, `attack_active`, multiplier | 220-280 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `Core::try_propose`, blocking sleep (gate at 659-662) | 655-688 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/sluggish_attack_test.rs` | test default m = 1.5 | 117-126 |
| Mysticeti in Sui v1.50 | `code/mevsui/consensus/core/src/core.rs` | `Core::new`: `is_attacker`, multiplier | 209-222 |
| Mysticeti in Sui v1.50 | `code/mevsui/consensus/core/src/core.rs` | `Core::try_propose`, blocking sleep (gate at 545) | 542-569 |
| Mysticeti (standalone) | `code/mysticeti/mysticeti-core/src/syncer.rs` | `attack_counts`, `attack_role` | 84-132 |
| Mysticeti (standalone) | `code/mysticeti/mysticeti-core/src/syncer.rs` | `Syncer::try_new_block`, sluggish sleep (gate at 249-255) | 190-305 |
| Mysticeti (standalone) | `code/mysticeti/mysticeti-core/src/attack_tests.rs` | `NetworkSyncer::start(…, 3, …)`: commit_period = 3 | 271-275 |
| Mahi-Mahi | `code/mahi-mahi-consensus/crates/mysticeti-core/src/syncer.rs` | `Syncer::try_new_block`, sluggish sleep (gate at 94-99) | 86-128 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/proposer.rs` | `Proposer::spawn`: attacker set and `max_header_delay · m` (gate at 120) | 95-124 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/proposer.rs` | `run`: sluggish trigger and header timer | 503-554 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/proposer.rs` | `run`: lag sleep and late header before advancing | 584-627 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/proposer.rs` | `run`: victim round handling | 650-671 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/core.rs` | `process_header`: attacker's core forwards victim header rounds | 241-254 |
| Bullshark | `code/bullshark-flashboys/primary/src/proposer.rs` | `run`: sluggish branch and timer reset | 535-567 |
| Bullshark | `code/bullshark-flashboys/primary/src/proposer.rs` | `run`: target header and committed certificate events | 639-685 |
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | `process_header`: forward target header (round mod 7 = 0) | 211-224 |
| Bullshark | `code/bullshark-flashboys/primary/src/attacks.rs` | `SLUGGISH_DELAY_MULTI_FACTOR = 2`, attack types 3 and 4 | 11, 16-17 |
| Bullshark | `code/bullshark-flashboys/benchmark/benchmark/config.py` | `LocalCommittee`: sluggish layout | 168-171 |
| AlephBFT | `code/alephbft/consensus/src/creation/mod.rs` | `process_unit`, processing delay (gate at 225, bound at 231) | 217-242 |
| AlephBFT | `code/alephbft/consensus/src/creation/mod.rs` | `run_creator`: attacker set | 356-373 |
| Autobahn | `code/autobahn-artifact/primary/src/core.rs` | `process_vote`: delay before own certificate goes to the proposer (gate at 874) | 857-911 |
| Autobahn | `code/autobahn-artifact/primary/src/core.rs` | `front_attacker_id`, `back_attacker_id`, `delay_actor_pk` | 170-197 |
| Autobahn | `code/autobahn-artifact/primary/src/proposer.rs` | `run`: delay before advancing height (gate at 282) | 272-320 |
