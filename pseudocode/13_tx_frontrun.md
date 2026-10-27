# Transaction-level front-running

The attacker learns of a victim's pending transaction through what the protocol shows it and races its own copy of that transaction so that the copy executes first. On Bullshark it sees the victim's batch, which workers gossip before any header carries it, and puts the copy into its own worker's next batch, which it seals at once. On Mysticeti in Sui v1.74 it sees the victim's transaction in a block it has accepted, or pending 50 ms after submission as a full-node operator would, and puts the copy at the head of the next block it proposes. The copy wins when it lands in an earlier certificate (Bullshark), an earlier position (Sui consensus order), or a higher gas rank inside the same commit (Sui execution order). The attacker can also send its copy to every validator as an ordinary client, and on Bullshark choose which quorum of parents its header references so that its certificate sorts first in the leader's traversal.

| | |
|---|---|
| Clause of the legitimate action set | (ii) contents (the copy in its own block or batch), (iii) timing (`FRONTRUN_WAIT_MS` on Sui; immediate batch seal on Bullshark), (i) references (`FR_GRIND` on Bullshark). Sending the copy to every validator (`FRONTRUN_MODE=broadcast`, `FR_SPRAY`) is a client action outside the four clauses. |
| Block role | own |
| Choice | Not a row of Table I. Add a copy of each victim transaction it has seen to its own payload (first in the block on Sui), optionally wait for the victims' same-round blocks, optionally pay one unit more gas, optionally grind the parent subset. |
| Has an effect where | Not a row of Table I. Measured on Bullshark (certified) and Mysticeti in Sui v1.74 (uncertified), in consensus order and in Sui's execution order. |
| Table II rows | A1.1, A3.5, A4.3, P1.1, P1.2 |
| Armed by | Sui v1.74: `FRONTRUN=1` (the test sets it itself), `FRONTRUN_ATTACKERS` (default 1), `FRONTRUN_VICTIMS` (default 3), `FRONTRUN_WAIT_MS` (default 0), `FRONTRUN_GAS` (default match; `outbid` pays one more), `FRONTRUN_MODE` (unset: the hook; `blind` and `broadcast`: client arms in the test, hook off), `FRONTRUN_VISIBILITY=mempool`, `FRONTRUN_MEMPOOL_DELAY_MS` (default 50), `FRONTRUN_VICTIM_BROADCAST` (victim client), `SUBMIT_INTERVAL_MS` (default 200). Bullshark: `FR_REACT=1` (acts only on nodes with `attack_type` 1 or 10), `FR_SPRAY=1`, `FR_GRIND=1`, `FR_VICTIM_RATE` (above 0 starts the victim client), `FR_VICTIM_SPRAY=1` (victim client). |

## Notation
- `a`: the attacking validator. `r`: the round (Sui) or header round (Bullshark) being proposed. `n`: committee size.
- Sui v1.74: attackers are validators `0, …, k_a−1` with `k_a = FRONTRUN_ATTACKERS`; victims are `n−k_v, …, n−1` with `k_v = FRONTRUN_VICTIMS`. `W = FRONTRUN_WAIT_MS`, `D = FRONTRUN_MEMPOOL_DELAY_MS`.
- Sui transaction layout: byte 0 is the tag (`0xA1` victim, `0xF1` attacker copy), bytes 1 to 8 the id, bytes 16 to 23 the gas price (big-endian). Victim gas is drawn from [1000, 3000).
- `MEMPOOL`: a process-wide list of (id, victim, visible-at time, gas) that the test workload fills and only the attacker's hook reads; it stands in for a full node's view of pending transactions.
- `Reacted`: ids this attacker has already copied.
- Bullshark: victim tag `2`, attacker tag `3`, id = bytes 1 to 8. The attacker is the node whose committee entry has `attack_type` 1 (fissure delegate) or 10 (monitor, no attack); the victim is the honest node with the smallest public key. `Q`: quorum threshold in stake (a count with unit stake). `K = 50` (`SPECULATIVE_MAX_TRIES`).
- Scoring (not run by validators). A victim transaction is won when the attacker's copy of the same id comes first; denominator = committed victim transactions; the first occurrence of each id is used. Sui consensus order: position in the committed transaction sequence. Sui execution order: key (commit index, −gas, position), the stable gas-price re-sort inside each commit. Bullshark: committing height, the index of the copy's certificate in the commit sequence of the longest primary log, strictly lower than the victim's.

## Algorithm
```text
Algorithm C. Transaction-level front-running (runs on attacker a only)

  Branch S: Mysticeti in Sui v1.74 (validator hook)
 1: procedure TRYNEWBLOCK(force)                        ▷ ValidatorProposer::try_new_block
 2:   if r ≤ last proposed round then return ⊥          ▷ upstream
 3:   if fr_enabled and W > 0 and not force then        ▷ hook (iii)
 4:     if some victim v ∈ {n−k_v, …, n−1} has no round r block in a's cache
          and less than W ms have passed since a first tried round r then
 5:       return ⊥                                      ▷ hook: retry later; the leader timeout forces past it
 6:     end if
 7:   end if
 8:   wait for the leader of r−1 and min_round_delay unless force; choose parents   ▷ upstream
 9:   X ← next transactions from the consumer           ▷ upstream
10:   if fr_enabled then X ← PREPEND(r, X)              ▷ hook (ii)
11:   build, sign and broadcast block(a, r, parents, X) ▷ upstream
12: end procedure
13: procedure PREPEND(r, X)
14:   Found ← []
15:   for each entry (id, v, t, gas) in MEMPOOL with t ≤ now do      ▷ hook: pending view
16:     remove the entry from MEMPOOL                   ▷ for every attacker, not only a
17:     if id ∉ Reacted then append (id, gas) to Found
18:   end for
19:   for each authority x ≠ a, each cached block b of x with round ≥ r−5,
          each transaction t in b with t[0] = 0xA1 do   ▷ hook: block view
20:     if id(t) ∉ Reacted and id(t) not in Found then append (id(t), gas(t)) to Found
21:   end for
22:   Front ← []
23:   for each (id, gas) in Found do
24:     c ← [0xF1, id, a], padded to 32 bytes, gas field ← gas + 1 if FRONTRUN_GAS = outbid else gas
25:     if adding c exceeds the block's transaction count or byte limit then
26:       log FRONTRUN_DROPPED; continue                ▷ not added to Reacted
27:     end if
28:     Reacted ← Reacted ∪ {id}; append c to Front
29:   end for
30:   return Front followed by X                        ▷ copies go first in a's block
31: end procedure

  Branch W: Sui v1.74 test workload (client side, not a validator)
32: every SUBMIT_INTERVAL_MS: v ← n − k_v + (seq mod k_v); build victim tx (0xA1, id, gas)
33:   if FRONTRUN_VISIBILITY = mempool and not blind then add (id, v, now + D, gas) to MEMPOOL
34:   send the victim tx to validator v, or to every validator if FRONTRUN_VICTIM_BROADCAST = 1
35:   if FRONTRUN_MODE = blind then send a copy (author byte 0) to validator 0 at the same instant
36:   if FRONTRUN_MODE = broadcast then after D ms send a copy (author byte 0) to every validator
37:   send one background tx to every non-victim validator

  Branch B: Bullshark (attacker's worker and primary)
38: procedure ONWORKERBATCH(batch from another worker) ▷ WorkerReceiverHandler::dispatch
39:   acknowledge                                       ▷ upstream
40:   if FR_REACT = 1 and attack_type(a) ∈ {1, 10} then ▷ hook (gate fixed at spawn)
41:     for each t in batch with t[0] = 2 and |t| > 8 do
42:       if id(t) already seen then continue
43:       mark id(t) seen; log FR_SEEN
44:       c ← t with t[0] set to 3                      ▷ same id and size
45:       if FR_SPRAY = 1 then send c to every other validator's client port   ▷ client action
46:       hand c to a's own BatchMaker                  ▷ hook (ii)
47:     end for
48:   end if
49:   store the batch and pass its digest to a's primary   ▷ upstream
50: end procedure
51: procedure BATCHMAKER.ONTX(t)                        ▷ a's own worker
52:   append t to the current batch                     ▷ upstream
53:   if (fr_flush and t[0] = 3) or batch size ≥ batch_size then seal and broadcast   ▷ hook (iii) for tag 3
54: end procedure
55: procedure MAKEHEADER(r)                             ▷ Proposer::make_header
56:   payload ← drained batch digests; P ← digests of the round r−1 parent certificates   ▷ upstream
57:   if FR_GRIND = 1 and attack_type(a) ∈ {1, 10} and |P| > Q then   ▷ hook (i)
58:     best ← P; d* ← certificate digest of header(a, r, payload, P)
59:     repeat K times
60:       S ← the first k entries of a random permutation of P, k uniform in [Q, |P|]
61:       d ← certificate digest of header(a, r, payload, S)
62:       if d > d* then best ← S; d* ← d               ▷ larger digest is popped first in order_dag
63:     end repeat
64:     P ← best
65:   end if
66:   sign header(a, r, payload, P) and send it to the core   ▷ upstream (silent-except-leader may withhold)
67: end procedure
```

## Why every message stays in the legitimate action set
On Sui the attacker's block carries a transaction of its own operator first, which is a payload choice every proposer has; it passes the same transaction verifier and block checks, and the wait ends no later than the leader timeout because a forced proposal skips it. On Bullshark the attacker's worker puts a client transaction into its own batch and seals that batch early, which the batch timer also does at any size, and its header references a subset of round r−1 certificates that still holds a quorum, which any valid header may do. Sending the copy to every validator's transaction port is what any client can do, and honest validators include it through their unmodified client path.

## Differences between trees
- **Bullshark**: the attacker sees the victim's transaction only through worker batch gossip (`FR_SEEN`). The "No attack" arm is `attack_type` 10, which still copies; the "Fissure" arm is `attack_type` 1, which also runs fissure in the primary (see the fissure file). `FR_GRIND` grinds the parent subset, not the payload, so it is a clause (i) choice on its own block. `FR_VICTIM_SPRAY=1` makes the victim's client send each transaction to every validator ("both send to all").
- **Mysticeti in Sui v1.74**: the attacker sees transactions in blocks of round ≥ r−5 in its cache, or pending through `MEMPOOL`. The copy goes to the head of its block. Gas matters only in the execution-order score. Combined arms set `ATTACK_MODE` (`fissure`, `speculative`) or `SILENT_EXCEPT_LEADER` with `NUM_ATTACKERS`; under `speculative` the payload reordering runs after PREPEND and rotates and truncates the transaction list, so a copy can leave the head of the block or be cut after it was added to `Reacted` (`proposer.rs` 1492-1550). `MEMPOOL` entries are removed by the first attacker that reads them, so with `FRONTRUN_ATTACKERS=2` (A3.5) each pending victim transaction reaches only one of the two attackers through the pending view; the other can copy it only after seeing it in a block. In `blind` and `broadcast` arms the hook is off (`fr_enabled` is false) and the copy is sent by the test as a client.
- **Other trees**: no transaction-level front-running code.

## Where it is implemented
| Tree (paper name) | File | Function / anchor | Lines |
|---|---|---|---|
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | tags, `frontrun_attacker_gas`, `frontrun_read_gas`, `FRONTRUN_MEMPOOL` | 120-153 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `fr_enabled` gate and parameters in `ValidatorProposer::new` | 256-261 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `frontrun_prepend` | 834-936 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | wait in `try_new_block` (gate 1278) | 1274-1300 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | prepend call in `try_new_block` | 1456, 1489-1491 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/frontrun_attack_test.rs` | `test_frontrun_reactive` (workload 142-243, `FINAL_TX_ORDER` 270-295) | 93-307 |
| Mysticeti in Sui v1.74 | `scripts/frontrun_sui/score_frontrun.py` | `exec_key`, `score` | 35-71 |
| Mysticeti in Sui v1.74 | `scripts/frontrun_sui/score_compete.py` | two-attacker scoring (A3.5) | 13-36 |
| Bullshark | `code/bullshark-flashboys/worker/src/worker.rs` | `FR_REACT` gate in `Worker::spawn` | 77-90 |
| Bullshark | `code/bullshark-flashboys/worker/src/worker.rs` | `FR_SPRAY` setup; tags; `WorkerReceiverHandler::dispatch` | 238-252, 316-318, 320-363 |
| Bullshark | `code/bullshark-flashboys/worker/src/batch_maker.rs` | `fr_flush` seal | 44-47, 84-91 |
| Bullshark | `code/bullshark-flashboys/primary/src/proposer.rs` | `fr_grind_parents`, `make_header` | 154-221 |
| Bullshark | `code/bullshark-flashboys/primary/src/attacks.rs` | `SPECULATIVE_MAX_TRIES`, attack types, `get_header_id`, `get_certificate_digest` | 10-20, 74-111 |
| Bullshark | `code/bullshark-flashboys/consensus/src/lib.rs` | `order_dag` (stack pops the last-pushed parent first) | 279-319 |
| Bullshark | `code/bullshark-flashboys/benchmark/benchmark/local.py` | victim client (`FR_VICTIM_RATE`, `FR_VICTIM_SPRAY`) | 107-131 |
| Bullshark | `code/bullshark-flashboys/node/src/benchmark_client.rs` | `send_victim` | 153-175 |
| Bullshark | `code/bullshark-flashboys/our_harness/frontrun_score.py` | `score` | 22-73 |
