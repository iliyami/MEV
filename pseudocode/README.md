# Attack pseudocode, one file per primitive

Algorithm 1 of the paper gives the shape every attack primitive shares. This directory gives each
primitive in full: its arming variables and defaults, its pseudocode, why every message it sends is
one a correct validator could send, how the trees differ, and the file, function and lines that
implement it in each tree.

Every step in these files was written from the source, not from the paper. Steps marked `▷ upstream`
are the unmodified protocol path; steps marked `▷ hook` are what the attack adds. With its arming
variable unset, every hook returns before the default path, and honest validators run with every
hook disarmed.

## Primitives

These are the eight rows of Table I in the paper, in the paper's order.

| # | Primitive | Clause of the legitimate action set | Block role | File |
|---|---|---|---|---|
| 1 | Fissure | (i) references | victim | [01_fissure.md](01_fissure.md) |
| 2 | Speculative | (ii) contents | own | [02_speculative.md](02_speculative.md) |
| 3 | Sluggish | (iii) timing | own | [03_sluggish.md](03_sluggish.md) |
| 4 | Silent-except-leader | (iii) timing | own | [04_silent_except_leader.md](04_silent_except_leader.md) |
| 5 | SLW | (iii) timing | own anchor | [05_slw.md](05_slw.md) |
| 6 | Proposal-timestamp | (ii) contents | own | [06_proposal_timestamp.md](06_proposal_timestamp.md) |
| 7 | LVW | (i) references | leader | [07_lvw.md](07_lvw.md) |
| 8 | Vote-withhold | (iv) signing | victim | [08_vote_withhold.md](08_vote_withhold.md) |

## Coordination, corruption and actions

| Topic | What it covers | File |
|---|---|---|
| Bribery | a validator that would otherwise follow its default behavior runs one primitive for the briber | [09_bribery.md](09_bribery.md) |
| Coalition coordination | several attackers sharing a victim, rival groups, a shared view | [10_coalition.md](10_coalition.md) |
| Back-run | landing immediately after the victim | [11_backrun.md](11_backrun.md) |
| Sandwich | one block before and one after the victim | [12_sandwich.md](12_sandwich.md) |
| Transaction-level front-running | copying a pending victim transaction into the attacker's own block | [13_tx_frontrun.md](13_tx_frontrun.md) |

## Trees

The files name trees as the paper does.

| Paper name | Directory |
|---|---|
| Bullshark (Narwhal-Bullshark, certified) | `code/bullshark-flashboys` |
| Narwhal-Tusk (certified) | `code/narwhal-tusk` |
| Mysticeti in Sui v1.74 | `code/sui` |
| Mysticeti in Sui v1.58 | `code/bullshark` (the Sui v1.58 tree; the directory name predates the paper) |
| Mysticeti in Sui v1.50 | `code/mevsui` |
| Mysticeti (standalone reference implementation) | `code/mysticeti` |
| Mahi-Mahi | `code/mahi-mahi-consensus` |
| AlephBFT | `code/alephbft` |
| Autobahn | `code/autobahn-artifact` |

## Notation shared by all files

`a` is the attacking validator, `r` the round it is about to propose, `n = 3f+1` the committee
size, and `Q` the parent quorum (`2f+1` validators, or the stake threshold where stake is unequal).
`←` is assignment and `▷` starts a comment. Line ranges refer to the commit this directory was
added in.
