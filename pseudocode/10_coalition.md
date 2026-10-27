# Coalition coordination

Several attacking validators can run the same primitive at once. What changes between coalition settings is not the primitive but who each attacker aims it at and what each attacker knows. In the default setting every attacker leaves the same victim out of its parent set, so the refusals add up on one block (colluding). The coordination variables change only that targeting: each attacker gets its own victim (competing), the attackers split into groups that each share one victim (multi-group), attackers prefer each other's blocks when filling their quorum, or attackers condition on what the other attackers have already done (global view). All of this happens out of band among Byzantine nodes; honest validators receive no new message type and validate exactly as upstream.

| | |
|---|---|
| Clause of the legitimate action set (coordinated) | (i) references: which victim's block each attacker omits, and which valid parents fill its quorum. `NUM_ATTACKERS` also sets the coalition for the Sui timing and contents hooks ((iii) silent-except-leader, (ii) proposal-timestamp) |
| Block role | victim |
| Choice | omit the victim's block; the coalition setting decides which victim per attacker |
| Has an effect where | where fissure does: certified and uncertified DAGs |
| Table II rows | A3.2 competing (`INDEPENDENT=1`), A3.3 colluding (default), A3.4 multi-group (`RIVAL_GROUPS`; the paper describes two groups of three, i.e. `RIVAL_GROUPS=2` with six attackers); A6.1 to A6.3 vary the colluding coalition size (A6.3 = A3.3). All on Bullshark |
| Armed by | Bullshark: `INDEPENDENT=1` or `RIVAL_GROUPS=G` (G > 1), `COLLUDE=1`; read only inside the fissure attacker branches. Mysticeti in Sui v1.74: `RIVAL_GROUPS=G`, `GLOBAL_VIEW` (any value except `0`) with `GLOBAL_VIEW_COVER` (default 1), `NUM_ATTACKERS` (default 0). Both Mysticeti trees: `V2_COORDINATOR_URL` (default unset); Sui v1.58 also `V2_BYZ_PEERS` |

## Notation
- `a`: the attacker running the code.
- Bullshark: `K` is the committee in key order (byte order of the public key). `V` is the list of authorities with `attack_type = 0` in key order, `A` the list with `attack_type ≠ 0` in key order, and `pos(a)` the position of `a` in `A`. The benchmark (`code/bullshark-flashboys/benchmark/benchmark/config.py`, `LocalCommittee`) assigns attack types by node index, not by key: for fissure, nodes `0..n−f_a−1` get 0, node `n−f_a` gets 1 (the delegate), and nodes `n−f_a+1..n−1` get 2. The no-attack control (type 10) gives node `n−f_a` type 10 and every other node 0. Keys are generated fresh for each run, so the delegate's position in `A` varies between runs.
- Sui v1.74: authorities are `0..n−1`; attackers are indexes `< ⌊n·ATTACKER_RATIO⌋`; victims are the last `vc = ⌊n·VICTIM_RATIO⌋` indexes, the first of them `fv = n − vc`.
- `G`: the value of `RIVAL_GROUPS`, used only if it parses and is greater than 1.
- `cover`: `GLOBAL_VIEW_COVER`, default 1. `pooled[(round, author)]`: a counter in a process-wide static map.
- `URL`: `V2_COORDINATOR_URL`.

## Algorithm
```text
Algorithm J. Coalition coordination (runs on attackers only; the coordinator lookup runs on every node)

Bullshark: which victim an attacker targets
 1: procedure TARGET()                                     ▷ fissure_target_victim; called only in the fissure branches
 2:   if INDEPENDENT = "1" and V ≠ ∅ and a ∈ A then
 3:     return V[pos(a) mod |V|]                           ▷ hook: competing, one victim per attacker
 4:   end if
 5:   if G is set and V ≠ ∅ and a ∈ A then
 6:     return V[(pos(a) mod G) mod |V|]                   ▷ hook: multi-group, group g targets V[g]
 7:   end if
 8:   return V[0]                                          ▷ default: colluding, every attacker on the same victim
 9: end procedure
10: on header h: if a is a fissure attacker, author(h) ∈ V, author(h) = TARGET() and round(h) mod 7 = 0
11:   then pass h to own proposer                          ▷ victim monitoring for the attack log
12: on certificate c: if a is a fissure attacker then P ← FISSUREAPPEND(c, TARGET())   ▷ 01_fissure.md
13: procedure FISSUREAPPEND quorum step (COLLUDE)          ▷ inside fissure_attack_append, non-rational path
14:   if weight of accumulated certificates ≥ Q then
15:     if COLLUDE = "1" then
16:       R ← accumulated certificates from authors with attack_type ≠ 0   ▷ hook: co-attackers first
17:       add accumulated certificates from attack_type = 0 authors until stake(R) ≥ Q
18:       clear the accumulator; return R
19:     end if
20:     return all accumulated certificates                ▷ upstream
21:   end if

Mysticeti in Sui v1.74: per-ancestor targeting inside the fissure hook
22: for each ancestor x of a's proposal for round r do
23:   isv ← author(x) ≥ fv                                 ▷ default: every attacker targets every victim
24:   if isv and G is set and author(x) ≥ fv then
25:     if (author(x) − fv) mod G ≠ index(a) mod G then isv ← false   ▷ hook: multi-group
26:   end if
27:   if not isv then keep x; continue
28:   if URL set and the coordinator returns profit p for x and a has a profit threshold t and p < t then keep x; continue
29:   if GLOBAL_VIEW is set then
30:     if pooled[(round(x), author(x))] ≥ cover then keep x; continue   ▷ hook: already handled by teammates
31:     pooled[(round(x), author(x))] ← pooled[(round(x), author(x))] + 1
32:   end if
33:   decide exclusion of x with the quorum-aware deterministic coin   ▷ 01_fissure.md
34: end for

Sui v1.74: coalition for other hooks
35: a is in the coalition for silent-except-leader, MAX_ATTACKER_PROPOSES and ATTACK_TIMESTAMP iff index(a) < NUM_ATTACKERS

Both Mysticeti trees: coordinator (only when URL is set)
36: at startup, on every node i:
37:   reply ← POST URL/policy/lookup {node_id: i}
38:   if reply = 200 then attacker ← true; take strategy, family, params, group from the reply
39:   else if reply = 404 then attacker ← false; all attacker hooks off       ▷ honest node
40:   else stop the node (panic)
41: on each proposal of attacker a for round r, before excluding:
42:   d ← POST URL/coordinate/decision {node_id: a, round: r}
43:   if d.role = "passive" then skip exclusion this round   ▷ rr_slot policy: one active attacker per round
44:   v1.58 only: if d.shared_exclusion_seed = s then the exclusion coin uses seed ⊕ s
45:   v1.58 only: if a's role is "amplify" then, after the normal exclusion,
46:     sort the remaining parents so authors in V2_BYZ_PEERS come first
```

## Why every message stays in the legitimate action set
Every hook here changes only the inputs to an attacker's own parent choice: which authority it treats as its victim, which already-valid certificates it lists first, or whether it skips an exclusion. The resulting block is one a correct validator could build from a different but valid view, and the quorum requirement on its own parents is unchanged (Bullshark proposes only from a quorum; Sui still runs its upstream quorum assertion). The coordination channels are outside the consensus network: Bullshark's variants need no messages at all (each attacker reads the committee file and its environment), Sui's global view is shared process memory, and the coordinator is an HTTP sidecar. The only coordinator contact an honest node has is the startup lookup, whose 404 reply turns the attacker hooks off; nodes listed in `V2_BRIBED_HONEST` also poll the bribery endpoints (09_bribery.md). No reply changes how any node validates a header, block, vote or certificate.

## Differences between trees
- **Bullshark** (`code/bullshark-flashboys`): coordination is static. The default is already colluding, because every fissure attacker targets `V[0]`. `INDEPENDENT` takes precedence over `RIVAL_GROUPS` when both are set. Positions are taken in key order among `attack_type ≠ 0` nodes, so which victim the delegate (the only node that logs attack pairs, and so the only one scored) gets under `INDEPENDENT` or `RIVAL_GROUPS` depends on where its key sorts. Bribed nodes do not follow these variables; they always target `V[0]`.
- **Mysticeti in Sui v1.74** (`code/sui`): the default is every attacker against every victim index (`VICTIM_RATIO`), not one shared victim. `RIVAL_GROUPS` assigns attacker `a` to group `a mod G` and victim `j` to group `(j − fv) mod G`. `GLOBAL_VIEW` works through a static map in the process. Sui runs host all validators in one process, so the map is the union of all attackers' decisions; in a deployment with one process per validator it would hold only the node's own decisions. The counter is incremented before the exclusion coin, so it counts attackers that reached the coin, not attackers that actually excluded the block. The coordinator path honors only the `passive` role; the shared seed is parsed but not used, and there is no amplify role.
- **Mysticeti in Sui v1.58** (`code/bullshark`): no `RIVAL_GROUPS` or `GLOBAL_VIEW`. Coordination is only through the coordinator: `passive` role, shared exclusion seed, and the `amplify` role with `V2_BYZ_PEERS`. The code comment at the role dispatch says amplify skips exclusion; the code does not skip it, it runs the normal exclusion and then reorders. The launcher sets `V2_BYZ_PEERS` to all policy members only when some policy has `role_action = amplify`.
- **Narwhal-Tusk, Mysticeti (standalone), Mahi-Mahi, AlephBFT, Autobahn, Mysticeti in Sui v1.50**: no coalition variable.
- **Not covered by these variables**: A3.1 (solo) is a single silent-except-leader attacker; A3.5 (competing for one victim) uses the Sui front-running hook with two attackers; A4.2 (global information) is the AlephBFT seed-aware grinder, not `GLOBAL_VIEW`.

## Where it is implemented
| Tree (paper name) | File | Function / anchor | Lines |
|---|---|---|---|
| Bullshark | `code/bullshark-flashboys/benchmark/benchmark/config.py` | `LocalCommittee.__init__`, attack types by node index | 153-183 |
| Bullshark | `code/bullshark-flashboys/benchmark/benchmark/local.py` | fresh keys per run; nodes started under a new tmux server, inheriting the caller's environment | 34-44, 73-80 |
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | `fn fissure_target_victim` (`INDEPENDENT` 362, `RIVAL_GROUPS` 393, default 419) | 355-420 |
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | `fn process_header`, victim monitoring | 198-210 |
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | `fn process_certificate`, fissure branch | 454-474 |
| Bullshark | `code/bullshark-flashboys/primary/src/aggregators.rs` | `fn fissure_attack_append`, `COLLUDE` 195; `fn select_colluder_quorum` | 186-201, 207-239 |
| Bullshark | `code/bullshark-flashboys/primary/src/proposer.rs` | delegate-only attack-pair log | 253-260 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | constructor: attacker prefix 208, coordinator lookup 210-252 | 200-252 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | fissure hook: coordinator role 627-636, `RIVAL_GROUPS` 686-716, profit gate 720-738, `GLOBAL_VIEW` 740-786 | 571-825 |
| Mysticeti in Sui v1.74 | `code/sui/consensus/core/src/proposer.rs` | `NUM_ATTACKERS` in `try_new_block` and the timestamp hook | 1148, 1170, 1423 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | constructor: attacker layout 245-269, coordinator lookup 299-362 | 245-362 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | fissure hook: role dispatch 1767-1825, `amplify` with `V2_BYZ_PEERS` 2011-2047 | 1639-2050 |
| Mysticeti in Sui v1.58 | `code/bullshark/consensus/core/src/core.rs` | `fn should_exclude_victim_block`, shared seed | 2141-2166 |
| Both Mysticeti trees | `code/sui/consensus/core/src/v2_coordinator_client.rs`, `code/bullshark/consensus/core/src/v2_coordinator_client.rs` | `lookup_policy`, `query_coordinate_decision` | 25-88, 30-99 |
| Coordinator | `scripts/v2/coordinator.py` | `decide`, `_compute_decision`; `/policy/lookup` handler | 170-249, 411-425 |
| Launcher | `scripts/v2/launchers/bullshark.py` | `V2_BYZ_PEERS`, `V2_BRIBED_HONEST`, `V2_COORDINATOR_URL` exported to the run | 277-305 |
