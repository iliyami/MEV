# Project rules

## Protocol invariant (non-negotiable)

**No protocol-core modification.** We do not change consensus logic, validity rules, quorum-intersection checks, or signature verification on any node. The protocol code paths run unchanged.

This rule applies to every protocol fork under `code/` (Bullshark, Mysticeti, Narwhal-Tusk, MEVSUI, AlephBFT, Mahi-Mahi, Autobahn) and to any new protocol added later (e.g., Sui mainnet for paper 2). It applies to all phases of all papers in this project.

What this rules out:
- Forcing or faking a validator to accept an invalid message
- Modifying signature verification, quorum-intersection checks, or any validity predicate
- Bypassing safety or liveness invariants
- Forging signatures or rewriting committed history
- Altering honest nodes' message-handling logic to accept what they normally would reject

What is allowed (the legitimate action set):
- Choices an honest validator *could* legally make, driven by attacker incentives — e.g., which parent references to include, when to broadcast within protocol-allowed bounds, which of several locally-valid candidates to propose, worker batch composition, header sealing timing.
- Out-of-band coordination *among Byzantine nodes* (Byzantine nodes can do whatever they want internally).
- Out-of-band signaling *to honest nodes* only if the resulting on-protocol action stays within the honest node's legitimate options.

Before adding any attacker hook, coordination channel, bribery mechanism, or new protocol integration, verify it preserves this invariant. If a hook ever requires an honest node to do something it would normally reject, the hook is wrong and must be redesigned.
