# Bribery

A bribed validator is one the committee configuration lists as honest. When the bribery variable names it, it runs one primitive's choice on the briber's behalf; in every measured cell that choice is to leave the victim's block out of its own parent set (fissure, clause (i)). It runs the same parent filter the Byzantine fissure attackers run, so the victim's block loses one more reference per bribed validator, exactly as if the coalition had one more member. A bribed validator does not run any other attacker code: it keeps the honest proposer, takes no attacker role, and its own blocks are not scored as attacker blocks. Following the threat model, a bribed validator no longer follows its default behavior, so it counts as part of the coalition and toward the f the protocol tolerates.

| | |
|---|---|
| Clause of the legitimate action set (bought) | (i) references. Also present but not used by a Table II row: (i) through LVW (`MLVW_BRIBED_NODES`), and parent reordering (`prefer_attacker_block`) in the coordinator path. A5.3 buys a (iv) signing refusal, but through `CENSOR`, not through a bribery variable (see 08_vote_withhold.md) |
| Block role | victim (fissure); leader (LVW variant) |
| Choice | omit the victim's block from the bribed validator's own parent set |
| Has an effect where | where the bought primitive does: fissure on certified and uncertified DAGs |
| Table II rows | A5.2 (Bullshark, `BRIBED=3`, one attacker); A5.4 (Sui v1.74, `FISSURE_BRIBED_NODES=1,2,3`, one attacker); T2.1 to T2.3 rescore A5.2. A5.3 (vote-withhold, `CENSOR=5`) has no bribery variable |
| Armed by | Bullshark: `BRIBED=B` (default 0, off), exported to every node; the hook selects the bribed set itself. Mysticeti in Sui v1.74: `FISSURE_BRIBED_NODES=i,j,...` and `MLVW_BRIBED_NODES=i,j,...` (authority indexes, default empty), plus `ATTACK_MODE` containing `fissure` or `lvw`. Both Mysticeti trees: `V2_BRIBED_HONEST=i,j,...` together with `V2_COORDINATOR_URL` (default unset) |

## Notation
- `b`: the node running the code. In Bullshark its committee `attack_type` is 0; in Sui it is outside the attacker prefix (`is_attacker = false`).
- Bullshark: `H` is the list of authorities with `attack_type = 0` in key order (byte order of the public key, `Attacker::victims()`). The victim is `v = H[0]` (`target_victim()`). `B` is the value of `BRIBED`, 0 if unset or unparsable. The bribed set is `H[1..B]`, the B honest keys that sort right after the victim, capped at `|H| − 1`.
- Bullshark: `FISSUREAPPEND(c, v)` is `CertificatesAggregator::fissure_attack_append`, the parent aggregator the fissure attackers call (01_fissure.md). `APPEND(c)` is the upstream `append`.
- Sui v1.74: authorities are numbered `0..n−1`. Attackers are indexes `< ⌊n·ATTACKER_RATIO⌋` (default 0.33). Victims are the last `⌊n·VICTIM_RATIO⌋` indexes (default 0.2 in the fissure hook). `F` is the parsed `FISSURE_BRIBED_NODES` list and `L` the parsed `MLVW_BRIBED_NODES` list.
- Coordinator path: `URL` is `V2_COORDINATOR_URL`; `W` is the parsed `V2_BRIBED_HONEST` list. An offer `o` has `offer_id`, `infraction`, `target_victim_id`, `target_attacker_set` and `payment`.
- `Q`: the parent quorum, 2f+1 stake.

## Algorithm
```text
Algorithm I. Bribery (code present on every node; acts only on a bribed validator b)

Bullshark (BRIBED)
 1: procedure ONCERTIFICATE(c)                             ▷ upstream entry: process_certificate
 2:   process the embedded header if not yet processed     ▷ upstream
 3:   if ancestors of c are missing then suspend           ▷ upstream
 4:   store c                                              ▷ upstream
 5:   if attack_type(b) is fissure, sluggish or speculative then
 6:     run that attacker's aggregator                     ▷ attacker branches; not taken, attack_type(b) = 0
 7:   else
 8:     B ← BRIBED, or 0                                   ▷ hook
 9:     bribed ← B > 0 and b ∈ H[1..B]                      ▷ hook
10:     if bribed and H ≠ ∅ then
11:       P ← FISSUREAPPEND(c, H[0])                       ▷ hook: the victim's certificate is never counted
12:     else
13:       P ← APPEND(c)                                    ▷ upstream
14:     end if
15:     if P ≠ ⊥ then send (P, round(c)) to own proposer    ▷ upstream; proposer builds the header as for any honest node
16:   end if
17:   send c to consensus                                  ▷ upstream
18: end procedure

Mysticeti in Sui v1.74 (FISSURE_BRIBED_NODES, MLVW_BRIBED_NODES)
19: procedure SELECTPARENTS(r)                             ▷ upstream ancestor selection for round r
20:   A ← ancestors chosen by the upstream rules           ▷ upstream
21:   A ← FISSUREHOOK(A, r)                                ▷ hook entry
22:   A ← LVWHOOK(A, r)                                    ▷ hook entry
23:   check the parent-round quorum, add back held-out ancestors, assert stake ≥ Q   ▷ upstream, unchanged
24: end procedure
25: procedure FISSUREHOOK(A, r)
26:   if URL set and b ∉ attackers and b ∈ W then return V2BRIBE(A)   ▷ only if an offer is accepted with omit_reference; else continue
27:   if ATTACK_MODE does not contain "fissure" then return A
28:   if b ∉ attackers and b ∉ F then return A             ▷ gate: an honest, unbribed node leaves here
29:   run the fissure exclusion exactly as an attacker does   ▷ 01_fissure.md: same victims, probability and coin
30: end procedure
31: procedure LVWHOOK(A, r)
32:   if ATTACK_MODE contains neither "lvw" nor "eclipse" then return A
33:   if b ∉ attackers and b ∉ L then return A             ▷ gate
34:   run the LVW exclusion exactly as an attacker does    ▷ see the LVW file
35: end procedure

Both Mysticeti trees (V2_BRIBED_HONEST with a coordinator). v1.74 calls it from line 26;
v1.58 calls it from its fissure hook when ATTACK_MODE is fissure, speculative or sluggish and b is not an attacker.
36: procedure V2BRIBE(A)
37:   o ← POST URL/bribery/pending {node_id: b}            ▷ hook; 404 means no offer
38:   if o = ⊥ then go to line 50
39:   if POST URL/bribery/decide {o, b} returns accept then
40:     POST URL/bribery/accept {o, b}
41:     if o.infraction ∈ {omit_reference, omit_reference_once} then
42:       v1.74: return A without blocks authored by any victim index   ▷ ignores o.target_victim_id
43:       v1.58: return A without blocks authored by o.target_victim_id
44:     else if o.infraction ∈ {select_candidate, prefer_attacker_block} and o.target_attacker_set ≠ ∅ then
45:       v1.58: return A reordered so that authors in o.target_attacker_set come first
46:     else if o.infraction ∈ {delay_broadcast, gas_style_incentive} then
47:       v1.58: log only; A unchanged
48:     end if
49:   end if
50:   return A                                             ▷ v1.58 returns here; v1.74 falls through to line 27
51: end procedure
```

## Bribed versus Byzantine, in code
- **Configuration.** A Byzantine attacker is marked in the committee (`attack_type ≠ 0` in Bullshark) or by its index (`own_index < ⌊n·ATTACKER_RATIO⌋` in Sui), or by a coordinator policy. A bribed validator is marked honest in all of these. It is selected only by the bribery variable.
- **What it runs.** In Bullshark the bribed node calls the same `fissure_attack_append` the attackers call, against `H[0]`, every round. It does not run the attacker branches: it does not forward the victim's header to its proposer, keeps no attack state, and its proposer runs the `HONEST_NODE` branch. In Sui v1.74 the bribed node passes the gate at line 28 or 33 and then runs the attacker's code for that one hook only; the sluggish, speculative and silent hooks still require `is_attacker` or `NUM_ATTACKERS` and stay off.
- **Victim choice.** The Bullshark bribed node always targets `target_victim()`, which is `H[0]`. The attackers target `fissure_target_victim()`, which is also `H[0]` by default but follows `INDEPENDENT` and `RIVAL_GROUPS` when set (10_coalition.md). A bribed node does not follow those variables.
- **Coalition membership seen by other attackers.** Bullshark's `COLLUDE=1` prefers parents with `attack_type ≠ 0`, so it does not treat a bribed node as a colluder. Under `MULTI_VICTIM=K` with K > 1, `H[0..K]` are victims, so bribed nodes `H[1..K−1]` would be victims too; this combination is not used by a Table II row.
- **Scoring.** In Bullshark only the delegate (`attack_type = 1`) logs attack pairs, so the bribed nodes' own blocks are never scored as attacker blocks. In A5.4 the scorer pairs validator 0 (the one attacker) with validator 12 (the victim), so bribed validators 1, 2, 3 are not scored either.
- **What is identical.** The message the bribed node sends is a normally built and signed block whose parent set lacks the victim. That is the same message a Byzantine fissure attacker sends, which is the code-level content of the paper's statement that a bribe is a coalition member.

## Why every message stays in the legitimate action set
Each bribed node only removes a valid block from its own parent set (or, on the coordinator path, reorders its own parent list). A correct validator whose copy of the victim's block arrived late would reference the same parents. In Bullshark the victim's certificate is dropped before it is counted, so the node proposes only when the remaining certificates reach Q, which the upstream proposer requires anyway. In Sui the upstream quorum assertion (line 23) still runs after the hook on the bribed node's own proposal. No hook touches header, block, vote or certificate validation on any node.

## Differences between trees
- **Bullshark** (`code/bullshark-flashboys`): one variable, `BRIBED=B`. The bribed set is derived, not listed: the B honest keys that sort right after the victim. Confirmed in code: bribed validators are `H[1..B]` in key order and the victim is `H[0]`. Strict exclusion: the victim's certificate is never counted unless `FISSURE_RATIONAL` is set.
- **Mysticeti in Sui v1.74** (`code/sui`): explicit index lists `FISSURE_BRIBED_NODES` and `MLVW_BRIBED_NODES`; the bribed node runs the attacker's probabilistic, quorum-aware exclusion. A5.4 uses attacker 0, bribed 1,2,3 and victim 12 (`scripts/frontrun_sui/run_mlaw.sh`). The same tree also has `WITHHOLD_BRIBED_NODES` in `authority_service.rs`, which adds a per-peer delay to blocks a listed node streams to victim peers; it is not one of the eight primitives and no Table II row uses it.
- **Mysticeti in Sui v1.58** (`code/bullshark`): only the coordinator path, `V2_BRIBED_HONEST`. It runs only when `ATTACK_MODE` is fissure, speculative or sluggish (checked at the top of the hook). It implements four infractions; the Sui v1.74 copy implements only `omit_reference`. In both trees the `omit_reference` path removes the victim's blocks without the quorum check the attacker path performs; the upstream assertion that follows still guards the bribed node's own proposal.
- **Narwhal-Tusk, Mysticeti (standalone), Mahi-Mahi, AlephBFT, Autobahn, Mysticeti in Sui v1.50**: no bribery variable.

## Where it is implemented
| Tree (paper name) | File | Function / anchor | Lines |
|---|---|---|---|
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | `fn process_certificate`, upstream prologue | 423-451 |
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | `fn process_certificate`, BRIBED branch (gating at 518-530) | 512-559 |
| Bullshark | `code/bullshark-flashboys/primary/src/attacks.rs` | `fn victims`, `fn target_victim` | 48-56, 66-71 |
| Bullshark | `code/bullshark-flashboys/primary/src/aggregators.rs` | `fn fissure_attack_append` (shared with attackers); `fn append` (upstream) | 95-205, 74-93 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | hook call sites in ancestor selection | 393-404 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `fn preprocess_ancestors_for_fissure_attack`: `FISSURE_BRIBED_NODES` 588-596, `V2_BRIBED_HONEST` 598-621, gate 623 | 571-825 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `fn preprocess_ancestors_for_mysticeti_lvw_attack`: `MLVW_BRIBED_NODES` 974-983, gate 986 | 965-1095 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | upstream quorum assertion | 540-543 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/authority_service.rs` | `WITHHOLD_BRIBED_NODES` (not a Table I primitive) | 384-416 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `fn preprocess_ancestors_for_fissure_attack`: mode gate 1646, honest branch with `V2_BRIBED_HONEST` 1656-1762 | 1639-1762 |
| Both Mysticeti trees | `code/sui/consensus/core/src/v2_coordinator_client.rs`, `code/bullshark/consensus/core/src/v2_coordinator_client.rs` | `query_pending_bribery_offer`, `bribery_decide`, `bribery_accept` | 123-205, 149-233 |
| Coordinator | `scripts/v2/coordinator.py`, `scripts/v2/briber.py` | `/bribery/pending`, `/bribery/decide`, `/bribery/accept`; `HonestResponsePolicy.decide` | 482-590; 101-132 |
