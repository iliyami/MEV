# Speculative

The attacker builds several valid versions of its own block, computes the hash each version would have, and publishes the one whose hash ranks best under the ordering key it targets. The versions differ only in what the attacker puts in its own block: which of its pending transactions or batches it includes, and in what order. Nothing about the parents, the round or the signature path changes. In a protocol that orders blocks, or elects the block that anchors a batch, by a hash of the block, a better-ranked hash moves the attacker's block ahead of other blocks of the same round, including the victim's. The attacker never reads the victim's hash; it only ranks its own candidates, and wins against the victim whenever its chosen hash ranks ahead of the victim's.

| | |
|---|---|
| Clause of the legitimate action set | (ii) contents |
| Block role | own |
| Choice | reorder the payload to grind the hash |
| Has an effect where | any protocol ordering by a block hash (general) |
| Table II rows | A2.2, A4.2, P2.4 (AlephBFT); P5.1 (Mahi-Mahi) |
| Armed by | `ATTACK_MODE=speculative` on every node of the run; the hook acts only on nodes that the attacker layout marks as attackers (below). Parameters: `SPECULATIVE_P_MAX` (default and cap differ per tree, see Notation); AlephBFT also `SPECULATIVE_SEED_AWARE` (default off) and `ALEPH_HASH_SORT_SEED` (default 0); Narwhal-Tusk also `SPECULATIVE_P_MAX_LIMIT` (50), `SPECULATIVE_TIMEOUT_MS` (20), `SPECULATIVE_GRACE_MS` (15), `SPECULATIVE_REQUIRE_VICTIM` (on when n ≥ 25), `SPECULATIVE_REFRESH_PARENTS` (off), `NUM_WORKERS` (4); Mahi-Mahi also `SPECULATIVE_STRATEGY` (default `sophisticated`). Bullshark has no environment variable: the committee file gives the attacker `attack_type` 5 or 6 |

## Notation
- `a`: the attacking validator. `r`: the round of the block being built.
- `P`: the parents `a` references in round `r`. The hook never changes `P`.
- `X`: the payload `a` would put in its round-`r` block on the upstream path. Sui trees: the transaction list returned by `TransactionConsumer::next`. Narwhal-Tusk and Bullshark: the queued worker batch digests. AlephBFT: one data item from the `DataProvider`. Mahi-Mahi: in the default strategy the list that varies is the include (reference) list, not the payload.
- `p_max`: number of candidates. Sui v1.74 and v1.50: `SPECULATIVE_P_MAX`, required (the node panics if it is missing and `ATTACK_MODE=speculative`), capped at 50. Sui v1.58: `SPECULATIVE_P_MAX`, default 2 with a warning, capped at 50. AlephBFT: default 50, capped at 50. Narwhal-Tusk: default 10, capped at `SPECULATIVE_P_MAX_LIMIT` (default 50). Bullshark: the constant `SPECULATIVE_MAX_TRIES = 50`, further capped by the number of queued digests. Mahi-Mahi: default 50, no cap.
- `C_i`: candidate `i` (a payload, or for Mahi-Mahi an include list).
- `DIGEST(C)`: the hash the grinder computes for the block built with `C`.
- `BETTER(d, d*)`: the comparison the grinder uses to keep a candidate. It is `>` (largest wins) or `<` (smallest wins) depending on the tree and the attacker's role, see "Differences between trees".
- `BUILD(r, P, C)`: the upstream block or header constructor, including signing.
- Attacker layout: Sui trees, `own_index < floor(n · ATTACKER_RATIO)` (default ratio 0.33); AlephBFT front-runners, `index < round(n · ATTACKER_RATIO)` (default 0.308); Narwhal-Tusk, the first `floor(n · ATTACKER_RATIO)` public keys in sorted order (default 0.33); Mahi-Mahi, the single node `ATTACKER_ID`; Bullshark, the nodes whose committee entry has `attack_type` 5 or 6.

## Algorithm
```text
Algorithm B. Speculative (runs on attacker a only)
 1: procedure PROPOSE(r)
 2:   P ← parents a references in round r                  ▷ upstream choice, unchanged
 3:   X ← payload a would include in its round-r block      ▷ upstream
 4:   if not (ATTACK_MODE = speculative and a is an attacker) then
 5:     return BUILD(r, P, X)                               ▷ upstream path, hook skipped
 6:   end if
 7:   d* ← ⊥ ; X* ← X                                       ▷ hook
 8:   for i ← 0 to p_max − 1 do                             ▷ hook
 9:     C_i ← CANDIDATE(i, X)                               ▷ hook, tree-specific (B.1 to B.4)
10:     d ← DIGEST(C_i)                                     ▷ hook, tree-specific
11:     if d* = ⊥ or BETTER(d, d*) then                     ▷ hook
12:       d* ← d ; X* ← C_i                                 ▷ hook
13:     end if
14:   end for
15:   return BUILD(r, P, X*)                                ▷ upstream build, sign, broadcast
16: end procedure

Algorithm B.1. CANDIDATE in Sui v1.74, v1.58 and v1.50 (cumulative: C carries over between iterations)
17: procedure CANDIDATE_SUI(i, C)                           ▷ C starts as X and is modified in place
18:   if |C| > 0 then rotate C right by (i mod |C|)
19:   if i mod 3 = 0 and |C| > 1 then
20:     C ← first ⌈0.9 · |C|⌉ transactions of C             ▷ drops the tail; dropped ones are not re-queued
21:   end if
22:   return C                                              ▷ DIGEST = digest of the signed, serialized trial block
23: end procedure

Algorithm B.2. CANDIDATE in AlephBFT (draws, does not reorder)
24: procedure CANDIDATE_ALEPH(i)
25:   x_i ← DataProvider.get_data()                         ▷ one new data item per draw; i = 0 is the first draw
26:   return x_i                                            ▷ DIGEST = hash of FullUnit(preunit, x_i, session_id)
27: end procedure

Algorithm B.3. CANDIDATE in Narwhal-Tusk (subsets of queued batches)
28: procedure CANDIDATE_NT(i, D)                            ▷ D: all queued batch digests, drained from the queue once
29:   S ← []
30:   for w ← 0 to NUM_WORKERS − 1 do
31:     D_w ← digests in D from worker w ; R_w ← last min(4, |D_w|) of D_w
32:     s ← SPLITMIX(round, i, w) ; choose by s mod 6:
33:       0: latest of D_w | 1: latest two of R_w | 2: one entry of R_w chosen by s, plus latest
34:       3: all of R_w | 4: two entries of R_w chosen by s | 5: none
35:     append the chosen digests to S
36:   end for
37:   remove duplicates from S ; if S = [] then S ← D
38:   return S                                              ▷ DIGEST = certificate digest H(H(a, r, S, P), r, a)
39: end procedure                                           ▷ the loop stops early once SPECULATIVE_TIMEOUT_MS has passed (checked for i > 0)

Algorithm B.4. CANDIDATE in Bullshark (prefixes of the queue)
40: procedure CANDIDATE_BS(k, D)                            ▷ k ← 0 to min(50, |D|) − 1
41:   return the first k + 1 queued digests of D            ▷ the rest of D stays queued for later headers
42: end procedure                                           ▷ DIGEST = certificate digest H(H(a, r, prefix, P), r, a)
```

Extra gates that run before line 7 in two trees:

```text
Algorithm B.5. When Narwhal-Tusk's speculative attacker proposes (proposer loop)
43: on a victim header h stored by a's Core: send round(h) to a's proposer   ▷ hook (Core::process_header)
44: seen ← (a victim header of the current round was reported)
45: ready ← seen and P ≠ ∅ and D ≠ ∅ and (header timer expired or SPECULATIVE_GRACE_MS passed since the report)
46: if SPECULATIVE_REQUIRE_VICTIM then propose iff ready
47: else if ready then propose
48: else propose iff (timer expired or enough digests) and P ≠ ∅            ▷ upstream rule
49: before moving to the next round: if a has not proposed this round, P ≠ ∅, D ≠ ∅
50:        and (not SPECULATIVE_REQUIRE_VICTIM or seen) then propose now
51: if SPECULATIVE_REFRESH_PARENTS and a larger parent set for the current round arrives
52:        before a proposes, replace P with it

Algorithm B.6. When Bullshark's speculative attacker grinds
53: grind (lines 7 to 14 with B.4) only if D ≠ ∅, r mod 7 = 0,
54:        and the target victim's round-r header has already reached a's Core
55: otherwise build the header from all of D and P                         ▷ upstream path
```

## What "best-ranked hash" means in each tree
- **Mysticeti in Sui v1.74, v1.58, v1.50**: the grinder ranks `VerifiedBlock::compute_digest` of the signed, serialized trial block. A front-runner keeps the largest digest. In v1.58 a back-runner, or the back half of a sandwich, keeps the smallest. The shipped linearizer (`sort_sub_dag_blocks`) orders a committed sub-DAG by `(round, author)` and does not read the digest. Only the defense variant `FIX_TIEBREAK=1` (set on every node) orders by `(round, digest)` ascending, under which the largest digest is placed last in its round.
- **AlephBFT**: the grinder ranks the unit hash, the hash of `(preunit, data, session_id)`. For round `r` the election lists the hashes of the round-`r` units a node has, sorts them ascending (with `ALEPH_HASH_SORT_SEED` ≠ 0 it sorts by `(seeded_rank_key(seed, hash), hash)`), and tries them in that order; the first one not eliminated by the vote becomes the head. The head's batch is a BFS over its parents, reversed, so a round-`r` unit that is not the head waits for a later batch. A front-runner keeps the smallest raw hash, or with `SPECULATIVE_SEED_AWARE=1` the smallest seeded key. A back-runner keeps the largest raw hash. The attacker's unit is tried before the victim's exactly when its key is smaller.
- **Narwhal-Tusk** and **Bullshark**: the grinder ranks the certificate digest, `H(header id, round, origin)`, which it recomputes from the candidate header. Consensus walks the committed sub-DAG depth first from the leader with a stack, pushing each certificate's parents in the ascending digest order of the `BTreeSet`, so among one certificate's parents the largest digest is popped and appended first; the result is then stably sorted by round. Both grinders keep the largest digest. In Narwhal-Tusk, `NT_LOP_SORT=1` (off by default) makes the tiebreak explicitly digest descending.
- **Mahi-Mahi** (`SPECULATIVE_STRATEGY=sophisticated`): the grinder ranks a preview digest computed with an empty signature and keeps the smallest. The real block digest also hashes the real signature, so it is not the value that was ranked. Mahi-Mahi orders a committed sub-DAG by round only, keeping the order of a stack-based walk over each block's include list, and elects leaders round-robin (`r mod n`). Neither reads the digest. What the hook changes in the committed order is the include order it chose.

## Why every message stays in the legitimate action set
A correct validator decides which of its own pending transactions or batches to include and in what order, and any choice passes the receivers' checks: Sui's block verifier does not constrain transaction order or count beyond its limits, a Narwhal header may carry any set of locally available batch digests, and an AlephBFT unit carries whatever its data provider returned. A correct validator whose mempool happened to hold exactly the chosen subset, in the chosen order, would send the same block. The parents, round, author and signature are produced by the upstream path, and the receivers run their checks unchanged. With `ATTACK_MODE` unset (or, on Bullshark, `attack_type` not 5 or 6) the condition on line 4 is false and the upstream constructor runs.

## Differences between trees
- **Mysticeti in Sui v1.74** (`code/sui`): the candidate list is mutated in place, so each rotation and truncation applies to the previous candidate. At `i = 0` the list is already truncated, so with 11 or more transactions every candidate drops at least one transaction; over 50 iterations the truncation runs 17 times. Dropped transactions are not put back. The transaction acknowledgements still carry the indexes of the original list, so on the attacker's own node a dropped transaction is acknowledged as included. Front-runner keeps the largest digest; there is no back-run branch.
- **Mysticeti in Sui v1.58** (`code/bullshark`): same candidates as v1.74. `SPECULATIVE_P_MAX` defaults to 2. A back-runner, or a sandwich attacker in the back half, keeps the smallest digest. `REVERSE_LAYOUT=1` puts front-runners at the highest indexes. A `V2_COORDINATOR_URL` policy can override `ATTACK_MODE` and `speculative_p_max` per node.
- **Mysticeti in Sui v1.50** (`code/mevsui`): same candidates; largest digest wins; `SPECULATIVE_P_MAX` required.
- **AlephBFT**: no reordering. The attacker draws up to `p_max` data items in succession and keeps one; the other draws are consumed. In the mock `DataProvider` of the tests, each call returns the next counter value. Seed-aware grinding is skipped for back-runners.
- **Narwhal-Tusk**: candidates are subsets of the queued batch digests, not reorderings (a header's payload is a `BTreeMap`, so order carries no information). All queued digests are drained once; digests not in the chosen candidate are not re-queued. The parent set is fixed. The hook also adds the timing gate of B.5, which waits for the victim's header of the current round. When `SPECULATIVE_REQUIRE_VICTIM` is on, a round in which no victim header was seen gets no header from the attacker. On the attacker only, the certificate aggregator keeps returning the growing parent set after a quorum (`aggregators.rs`), which feeds `SPECULATIVE_REFRESH_PARENTS`.
- **Bullshark** (Zhang and Kate's artifact): candidates are prefixes of the queue, so only the length varies; the unchosen tail stays queued. Grinding runs only in rounds `r mod 7 = 0` after the target victim's header of round `r` arrives. The target is the first `attack_type = 0` authority in public-key order. Types 5 and 6 run the same proposer code.
- **Mahi-Mahi**: `ATTACK_MODE=speculative` selects one of nine strategies through `SPECULATIVE_STRATEGY`. Only `sophisticated`, the code default, grinds a hash, and it shuffles the include list (own previous block kept at position 0) rather than the payload. The other strategies (`simple`, `roundrace`, `optimal`, `smart`, `hybrid`, `turbo`, `cascade`, `traversal`) drop the victim's includes with some probability or reorder includes, and compute no hash. `config/grand_experiment_mahimahi.yaml` sets `SPECULATIVE_STRATEGY: "smart"`, and `code/mahi-mahi-consensus/scripts/legacy_automation/automated_speculative_attack.sh` runs `smart`, `simple`, `sophisticated` (with `SPECULATIVE_P_MAX=5`) and `hybrid` in turn.
- **Mysticeti (standalone reference implementation)**: not implemented. `ATTACK_MODE=speculative` only marks the node as an attacker (`is_mev_attack_mode`); `SPECULATIVE_STRATEGY` is read into an unused variable, and no candidate loop exists. The test `test_speculative_attack_asr_13_nodes` does not set `ATTACK_MODE`.
- **Autobahn**: not implemented.

## Where it is implemented
| Tree (paper name) | File | Function / anchor | Lines |
|---|---|---|---|
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `ValidatorProposer::new`: `SPECULATIVE_P_MAX`, attacker layout | 178-188, 201-208 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `try_new_block`: gate (line 1492) and candidate loop | 1483-1550 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/commit.rs` | `sort_sub_dag_blocks` (`FIX_TIEBREAK` 408-415; shipped rule 478-482) | 403-484 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/transaction.rs` | `TransactionConsumer::next` (acknowledgement indexes) | 106-188 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `Core::new`: `SPECULATIVE_P_MAX`, layout, `attack_active` | 231-270 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `try_new_block`: gate (line 890) and candidate loop | 886-975 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/commit.rs` | `sort_sub_dag_blocks` | 404-423 |
| Mysticeti in Sui v1.50 | `code/mevsui/consensus/core/src/core.rs` | `Core::new` (200-213); `try_new_block`: gate (line 736) and loop | 200-213, 733-813 |
| AlephBFT | `code/alephbft/consensus/src/creation/mod.rs` | `run_creator`: attacker layout and gate (line 389) | 356-396 |
| AlephBFT | `code/alephbft/consensus/src/creation/mod.rs` | `speculative_attack_select_best_data` | 88-177 |
| AlephBFT | `code/alephbft/consensus/src/extension/election.rs` | `RoundElection::for_round`: candidate sort, seeded key | 156-196 |
| AlephBFT | `code/alephbft/consensus/src/extension/mod.rs` | `seeded_rank_key` | 8-14 |
| AlephBFT | `code/alephbft/consensus/src/extension/units.rs` | `Units::remove_batch` | 58-80 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/proposer.rs` | `Proposer::spawn`: parameters and layout | 95-116 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/proposer.rs` | `make_header`: gate (line 449) | 433-486 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/proposer.rs` | `run`: timing gate, forced proposal, victim report | 488-678 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/proposer.rs` | `propose_speculative_block`, `sample_worker_batches`, `speculative_worker_seed`, `compute_header_digest`, `digest_wins_over` | 682-943 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/core.rs` | `process_header`: victim header report | 240-254 |
| Narwhal-Tusk | `code/narwhal-tusk/primary/src/aggregators.rs` | `CertificatesAggregator::append`: attacker-only parent updates | 122-134 |
| Narwhal-Tusk | `code/narwhal-tusk/consensus/src/lib.rs` | `order_dag` (upstream walk 413-441; round sort 451-459) | 361-463 |
| Bullshark | `code/bullshark-flashboys/primary/src/attacks.rs` | `SPECULATIVE_MAX_TRIES`, `get_header_id`, `get_certificate_digest` | 10, 73-110 |
| Bullshark | `code/bullshark-flashboys/primary/src/proposer.rs` | `make_minimum_header` | 301-427 |
| Bullshark | `code/bullshark-flashboys/primary/src/proposer.rs` | `run`: speculative branch (gate `is_attacking`) and victim header | 568-606, 639-660 |
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | victim header forwarded to proposer | 224-235 |
| Bullshark | `code/bullshark-flashboys/consensus/src/lib.rs` | `order_dag` | 279-320 |
| Bullshark | `code/bullshark-flashboys/benchmark/benchmark/config.py` | `LocalCommittee`: `attack_type` 3 → nodes typed 5 and 6 | 174-177 |
| Mahi-Mahi | `code/mahi-mahi-consensus/crates/mysticeti-core/src/core.rs` | `try_new_block`: `ATTACKER_ID`, `SPECULATIVE_STRATEGY` | 272-295 |
| Mahi-Mahi | `code/mahi-mahi-consensus/crates/mysticeti-core/src/core.rs` | `sophisticated` strategy: gate (line 842) and loop | 840-898 |
| Mahi-Mahi | `code/mahi-mahi-consensus/crates/mysticeti-core/src/crypto.rs` | `BlockDigest::new` (hashes the signature) | 47-70 |
| Mahi-Mahi | `code/mahi-mahi-consensus/crates/mysticeti-core/src/consensus/linearizer.rs` | `CommittedSubDag::sort`, `collect_sub_dag` | 28-84 |
| Mysticeti (standalone) | `code/mysticeti/mysticeti-core/src/core.rs` | `is_mev_attack_mode`; unused `_speculative_strategy` | 147-149, 451 |
