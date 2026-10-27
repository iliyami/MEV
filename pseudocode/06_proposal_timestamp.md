# Proposal-timestamp

Every Mysticeti block carries a timestamp that its proposer writes from its own clock. The attacker adds a fixed offset to that value in its own blocks and leaves every other field as upstream builds it. Receivers check the block's signature, epoch, author and ancestors, but no rule bounds its timestamp, so the block is accepted as is. A protocol whose ordering trusts proposer time would then place the attacker's block by the stamped time rather than by when it was made. In Sui v1.74 the shipped intra-commit order is `(round, author)` and does not read the timestamp, so the stamp only reaches the commit timestamp and the `ORDER_FAIR_TIEBREAK` defense variant.

| | |
|---|---|
| Clause of the legitimate action set | (ii) contents |
| Block role | own |
| Choice | set the timestamp field ahead |
| Has an effect where | any protocol trusting proposer time (general) |
| Table II rows | A2.6 |
| Armed by | `ATTACK_TIMESTAMP` set to any value other than `0`, together with `NUM_ATTACKERS=k` and `BYZANTINE_TIMESTAMP_OFFSET_MS=δ`; the hook acts only on nodes with index below `k`. Parameters: `NUM_ATTACKERS` (default 0, so no node acts), `BYZANTINE_TIMESTAMP_OFFSET_MS` (no default; unset or not an `i64` means no change). The test `test_timestamp_attack_asr_dynamic` sets `ATTACK_TIMESTAMP=1` and δ = −500 when they are unset, and sets `NUM_ATTACKERS` to round(n · `ATTACKER_RATIO`) (4 at n = 13, ratio 0.308). The driver `scripts/v2/p_sui_timestamp.py` passes δ = 5000 |

## Notation
- `a`: the attacking validator, with committee index `idx(a)`. `r`: the round being proposed (`clock_round`).
- `force`: true when the proposal is forced by a leader timeout.
- `now`: the local clock in UTC milliseconds (`context.clock.timestamp_utc_ms()`).
- `δ`: the offset in milliseconds, a signed 64-bit integer from `BYZANTINE_TIMESTAMP_OFFSET_MS`.
- `k`: the value of `NUM_ATTACKERS` (default 0).
- `ts(B)`: the timestamp field of block `B`.
- `last_ts`: the timestamp of `a`'s last proposed block.
- `min_round_delay`: upstream minimum spacing between own unforced proposals. Default 50 ms; 400 ms under `msim` or with `__TEST_ONLY_CONSENSUS_USE_LONG_MIN_ROUND_DELAY`; 250 ms only when `consensus-config` is itself compiled for its own unit tests (`parameters.rs`). The timestamp test builds `Parameters` with `..Default::default()`, so it gets 50 ms.
- `A`: the ancestors chosen for the block. `L`: a committed leader block, of round `ℓ`.

## Algorithm
```text
Algorithm F. Proposal-timestamp (Sui v1.74; the hook runs on attacker a only)
 1: procedure TRY_NEW_BLOCK(force)                          ▷ on a
 2:   r ← threshold clock round; return if r ≤ round of a's last block    ▷ upstream
 3:   if not force then                                     ▷ upstream
 4:     return if a leader of round r−1 is still missing    ▷ upstream
 5:     return if now − last_ts < min_round_delay           ▷ upstream; last_ts is a's own stamped value
 6:   end if
 7:   A ← ancestors chosen by smart ancestor selection      ▷ upstream; return if none
 8:   t ← now                                               ▷ upstream
 9:   if ATTACK_TIMESTAMP is set and ≠ "0" then             ▷ hook
10:     if idx(a) < k then                                  ▷ hook
11:       if BYZANTINE_TIMESTAMP_OFFSET_MS parses as i64 δ then   ▷ hook
12:         if δ ≥ 0 then t ← t + δ (saturating)            ▷ hook
13:         else t ← t − |δ| (saturating at 0)              ▷ hook
14:         print "V2_TIMESTAMP_ATTACK round authority offset_ms new_ts_ms"   ▷ hook
15:       end if
16:     end if
17:   end if
18:   for each B' ∈ A with ts(B') > t do record a drift metric   ▷ upstream, metric only
19:   X ← transactions; build block B with ts(B) ← t        ▷ upstream (a speculative attacker would grind here)
20:   sign B; accept B into a's own DAG; broadcast B        ▷ upstream
21: end procedure

22: procedure ON_RECEIVE(B)                                 ▷ every receiver, unmodified
23:   verify B: epoch, round ≠ 0, author index, signature,
24:       ancestor positions and rounds, parent quorum, transaction limits   ▷ no timestamp predicate
25:   record max(0, ts(B) − now) as a drift metric         ▷ metric only; no bound is enforced
26:   accept B into the DAG
27: end procedure

28: procedure COMMIT_TIMESTAMP(L)                           ▷ linearizer, every node
29:   T ← stake-weighted median of ts over L's ancestors of round ℓ−1
30:   return max(T, timestamp of the previous commit)
31: end procedure

32: procedure SORT_SUB_DAG(blocks)                          ▷ every node
33:   if ORDER_FAIR_TIEBREAK = 1 then sort by (round, ts, digest)   ▷ defense variant
34:   else sort by (round, author)                          ▷ shipped rule; ts not read
35: end procedure
```

Which rules read the timestamp, from the code:
- **Ordering inside a commit.** The shipped `sort_sub_dag_blocks` sorts by `(round, author)` and ignores `ts`. Only the env-gated defense variant `ORDER_FAIR_TIEBREAK=1` sorts by `(round, ts, digest)`. Under it, a positive δ moves the attacker's blocks later inside their round and a negative δ moves them earlier.
- **Commit timestamp.** `calculate_commit_timestamp` takes the stake-weighted median of the timestamps of the leader's round `ℓ−1` ancestors, then the maximum with the previous commit's timestamp. The median is the first timestamp, in ascending order, at which the cumulative stake exceeds half the stake of those ancestors. Attacker blocks stamped ahead sort to the top, stamped behind to the bottom. While their stake among those ancestors is at most half, the median is still an honest block's timestamp, though which honest timestamp it is can shift.
- **Receiver bound.** None is enforced. `Parameters::max_forward_time_drift` exists (default 500 ms) but outside a unit test nothing reads it. `handle_send_block`, the synchronizer, the commit syncer and `DagState::accept_block` only record how far `ts(B)` is ahead of the local clock. `verify_block` has no timestamp check, and the block manager accepts blocks without comparing a block's timestamp to its ancestors'.
- **The attacker's own proposer.** Line 5 compares the real clock with `a`'s own last stamped timestamp. With δ > 0, `now − last_ts` saturates to 0 until the real clock passes `last_ts`, so `a` makes no unforced proposal for about δ + `min_round_delay` after each block and proposes only when forced by a leader timeout. With δ ≤ −`min_round_delay` the check always passes, so `a` no longer waits `min_round_delay` between its proposals.

## Why every message stays in the legitimate action set
A correct validator whose local clock runs δ milliseconds ahead of, or behind, the others would build exactly this block. The receivers run their unchanged checks, which accept any timestamp, so no honest node takes an action it would otherwise refuse. The hook changes only the value `a` writes into its own block. Signing, ancestor selection and broadcast are the upstream steps. With `ATTACK_TIMESTAMP` unset or `0`, or `idx(a) ≥ k`, or the offset unset, `t` stays equal to `now` and the upstream path runs.

## Differences between trees
- **Mysticeti in Sui v1.74** (`code/sui`): the only tree with this hook.
- **Mysticeti in Sui v1.58** (`code/bullshark`) and **Mysticeti in Sui v1.50** (`code/mevsui`): not implemented. Their `try_new_block` stamps `now` with no offset.
- **Bullshark, Narwhal-Tusk, Mysticeti (standalone reference implementation), Mahi-Mahi, AlephBFT, Autobahn**: not implemented. A search for `ATTACK_TIMESTAMP`, `BYZANTINE_TIMESTAMP_OFFSET_MS` and similar names in their Rust sources finds nothing.
- The hook is gated by `NUM_ATTACKERS`, not by `ATTACK_MODE` or `ATTACKER_RATIO` as the speculative, fissure and sluggish hooks are. `NUM_ATTACKERS` is the same gate the burst-and-hide hook (`MAX_ATTACKER_PROPOSES`) uses.

## Where it is implemented
| Tree (paper name) | File | Function / anchor | Lines |
|---|---|---|---|
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `try_new_block`: hook, gate on line 1422 | 1416-1440 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `try_new_block`: upstream `min_round_delay` check against `last_proposed_timestamp_ms` | 1308-1334 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `try_new_block`: ancestor drift metric, block built with `now` | 1441-1452, 1552-1576 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/block_verifier.rs` | `SignedBlockVerifier::verify_block` (no timestamp check) | 67-152 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/authority_service.rs` | `handle_send_block`: drift metric only | 213-222 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/synchronizer.rs` | fetched block drift metric only | 705-727 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/dag_state.rs` | `accept_block`: drift metric only | 303-318 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/config/src/parameters.rs` | `max_forward_time_drift` (500 ms), `min_round_delay` | 37-39, 135-151 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/linearizer.rs` | `calculate_commit_timestamp`, `median_timestamp_by_stake` | 125-154, 291-332 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/commit.rs` | `sort_sub_dag_blocks` (`ORDER_FAIR_TIEBREAK` 441-453; shipped rule 478-482) | 403-484 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/timestamp_attack_test.rs` | `run_timestamp_cell`, baseline and attack tests | 82-229, 280-309 |
| Mysticeti in Sui v1.74 | `scripts/v2/p_sui_timestamp.py` | `_BASE_ENV` (δ = 5000) | 51-63 |
