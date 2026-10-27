# Vote-withhold

On a certified DAG a header becomes a block in the DAG only after 2f+1 validators sign it, and the resulting certificate is what other validators reference and what consensus orders. A vote-withholding validator receives the victim's header, runs every validity check on it as usual, stores it, and then does not send its vote. If k validators other than the victim do this, at most n−k votes exist for each victim header. With k ≥ f+1 no victim header can be certified, so the victim's blocks never enter the committed order. With k = f the victim needs every one of the remaining 2f+1 votes in time, so one late vote is enough to lose the round.

| | |
|---|---|
| Clause of the legitimate action set | (iv) signing |
| Block role | victim |
| Choice | withhold the certificate vote |
| Has an effect where | certified DAGs (DAG-specific) |
| Table II rows | A1.4, A2.8 (k = 4 = f); A5.3 (k = 5 = f+1, the fifth withholder counted as bribed) |
| Armed by | `CENSOR=k` in the environment of the benchmark run. Every node process inherits it; the hook acts only on the nodes in the censor set C defined below. Parameter `CENSOR` (default 0, which disables the hook) |

## Notation
- `a`: the node running the code (its public key, `self.name`).
- `h`: a header received from another primary, or a loopback header from the header waiter.
- `K`: the committee in key order. `Committee.authorities` is a `BTreeMap<PublicKey, Authority>` and `PublicKey` is a 32-byte array with a derived `Ord`, so iteration is in byte order of the public key. This is not the order of the benchmark's node indexes, because keys are freshly generated for each run.
- `V`: the authorities whose committee entry has `attack_type = 0`, in key order (`Attacker::victims()`).
- `v = V[0]`: the target. If `V` is empty the hook does nothing.
- `k`: the value of `CENSOR` parsed as an unsigned integer; 0 if unset or not a number.
- `C`: the censor set, the first `k` authorities of `K` after removing `v`. Membership does not depend on `attack_type`. With `k = 4` and four fissure attackers in the committee, `C` contains whichever four non-target keys sort first, which in general mixes `attack_type = 0` and `attack_type ≠ 0` nodes.
- `Q`: the quorum threshold, `2·total_stake/3 + 1` (9 at n = 13 with unit stake).
- `voted[r]`: the set of authors this node has already voted for in round `r` (`last_voted`).

## Algorithm
```text
Algorithm H. Vote-withhold (code present on every node; acts only when a ∈ C)
 1: procedure ONHEADER(h)                                  ▷ upstream; network headers first pass SANITIZE (not GC'd, signature valid)
 2:   mark h as being processed in round(h)                ▷ upstream
 3:   P ← parent certificates of h                         ▷ upstream; if one is missing, suspend and sync
 4:   require round(p) + 1 = round(h) for every p ∈ P      ▷ upstream validity check, unchanged
 5:   require stake(P) ≥ Q                                 ▷ upstream validity check, unchanged
 6:   if the payload of h is missing then suspend          ▷ upstream
 7:   store h                                              ▷ upstream
 8:   if a is a fissure, sluggish, speculative or monitor node and h is its target's header
 9:        and round(h) mod 7 = 0 then pass h to own proposer   ▷ other primitives, unchanged by this hook
10:   k ← CENSOR, or 0 if unset or unparsable               ▷ hook
11:   if k > 0 and V ≠ ∅ then                              ▷ hook
12:     v ← V[0]                                           ▷ hook
13:     if author(h) = v then                              ▷ hook
14:       C ← first k entries of K, skipping v             ▷ hook
15:       if a ∈ C then                                    ▷ hook
16:         log "CENSOR_VOTE_WITHHELD round(h) target v"   ▷ hook (benchmark builds)
17:         return                                         ▷ hook: (iv) no vote is created or sent
18:       end if
19:     end if
20:   end if
21:   if author(h) ∉ voted[round(h)] then                  ▷ upstream: one vote per (round, author)
22:     voted[round(h)] ← voted[round(h)] ∪ {author(h)}     ▷ upstream
23:     σ ← vote on h signed with a's key                  ▷ upstream
24:     if a = author(h) then process σ locally            ▷ upstream
25:     else send σ to author(h)                           ▷ upstream
26:   end if
27: end procedure
```
Lines 2 to 7 run before the hook, so a censor has already checked and stored the header. Because line 2 records the header as processed, a censor that later receives a certificate for it (possible when k ≤ f) does not run ONHEADER again; it handles the certificate on the upstream path and may reference it as a parent. Vote-withholding therefore does not change what a censor accepts, stores, or references. It only removes the censor's signature from the victim's quorum.

## Why every message stays in the legitimate action set
The hook sends no message. A correct validator whose copy of the victim's header arrives late, or after it has moved past that round, produces exactly the same observable behavior: no vote from it reaches the victim. The vote aggregator at the victim, the certificate check `2f+1` signatures, header and parent validity checks, and signature verification are all unchanged on every node. The hook is placed after every validity check in `process_header` and returns before the vote is created; with `CENSOR` unset or 0 it is skipped and the upstream vote path runs.

## Differences between trees
- **Bullshark** (`code/bullshark-flashboys`): the only tree with this hook. The censor set is chosen by key order, not by the `attack_type` field of the committee. The censorship runs also used a fissure layout with `f_a = 4`, so the four fissure attackers and the censors are two independently chosen sets that overlap only when the attackers' keys happen to sort first. Whoever is in `C` deviates from default behavior and so counts toward the coalition; the code does not enforce that `C` equals the attacker set. For A5.3 (`CENSOR=5`) at least one member of `C` must have `attack_type = 0`, since only four nodes have `attack_type ≠ 0`; there is no separate bribery variable for this cell.
- **Narwhal-Tusk** (`code/narwhal-tusk`): certified, with the same Narwhal vote path in `process_header`, but no vote-withholding hook. Every node votes as upstream.
- **Mysticeti in Sui v1.74, Mysticeti in Sui v1.58, Mysticeti (standalone), Mahi-Mahi**: uncertified; a block is accepted without a certificate vote, so there is no vote to withhold. The nearest primitive there is LVW, which withholds a reference to a leader rather than a signature.
- **AlephBFT, Autobahn**: no vote-withholding hook was found.

## Where it is implemented
| Tree (paper name) | File | Function / anchor | Lines |
|---|---|---|---|
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | `fn run`, network header goes through `sanitize_header` then `process_header` | 625-631 |
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | `fn sanitize_header` (upstream) | 572-583 |
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | `fn process_header`, upstream checks and store | 155-195 |
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | `fn process_header`, CENSOR hook (gating check at 266) | 247-287 |
| Bullshark | `code/bullshark-flashboys/primary/src/core.rs` | `fn process_header`, upstream vote | 289-318 |
| Bullshark | `code/bullshark-flashboys/primary/src/attacks.rs` | `fn victims` (`V`, `attack_type = 0` in key order) | 48-56 |
| Bullshark | `code/bullshark-flashboys/config/src/lib.rs` | `struct Committee`, `authorities: BTreeMap<PublicKey, Authority>`; `fn quorum_threshold` | 144-145, 175-180 |
| Bullshark (scorer) | `scripts/score_censorship_bullshark.py` | `score_run`: victim from attack-pair lines, else from `CENSOR_VOTE_WITHHELD ... target`; rate = 1 − median(victim committed blocks) / median(other non-attacker authors) | 52-124 |
| Narwhal-Tusk (no hook) | `code/narwhal-tusk/primary/src/core.rs` | `fn process_header`, upstream vote | 198-287 |
