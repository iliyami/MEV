"""Invariant Auditor — guards the protocol-modification invariant (CLAUDE.md).

Two layers:

1. **Static checker** (`StaticAuditor`). Registry of attacker-hook descriptors;
   each descriptor declares which protocol code paths the hook may invoke.
   The audit asserts that this set is a subset of paths an honest validator
   already invokes. The actual subset check is currently a manifest-based
   declaration (the harness ships a `legitimate_paths.json` per protocol);
   reviewers can audit the manifest and the runtime checker (below) confirms
   the manifest is honored.

2. **Runtime tap** (`RuntimeAuditor`). Streamed per-run check on the protocol's
   message log. Asserts:
     (a) every honest-node-emitted message would pass the protocol's own
         validity predicates (we replay the verifier on the captured message),
     (b) signatures are produced only by their owner (we recompute the
         signer-id from the certificate header),
     (c) committed-block agreement holds across replicas round-by-round.
   Any violation aborts the run and is logged as a framework bug.

For P0 these are scaffolds. P1 wires them to the real Bullshark message log
and validator. The scaffolds are deliberately structured so the wiring is a
single adapter implementation per protocol, never a logic change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional


# ---------------------------------------------------------------------------
# Static auditor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HookDescriptor:
    """Declares an attacker hook's footprint for static auditing.

    name: stable identifier (e.g., "bullshark.fissure.parent_filter").
    protocol: which protocol this hook lives in.
    invoked_paths: protocol code paths (symbol names) the hook may invoke.
    rationale: one-line note explaining why this is within the legitimate
        action set. Reviewers read this verbatim.
    """

    name: str
    protocol: str
    invoked_paths: frozenset[str]
    rationale: str


class StaticAuditError(AssertionError):
    """A hook declares a code path that honest validators never invoke."""


class StaticAuditor:
    """In-process registry of attacker-hook descriptors.

    Real protocols ship a `legitimate_paths` manifest — the set of symbols
    honest validators invoke. The auditor verifies every registered hook's
    `invoked_paths` is a subset.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, HookDescriptor] = {}
        self._legitimate_paths: dict[str, frozenset[str]] = {}

    def register_legitimate_paths(self, protocol: str, paths: Iterable[str]) -> None:
        self._legitimate_paths[protocol] = frozenset(paths)

    def register_hook(self, descriptor: HookDescriptor) -> None:
        if descriptor.name in self._hooks:
            raise ValueError(f"hook {descriptor.name!r} already registered")
        self._hooks[descriptor.name] = descriptor

    def audit(self) -> list[str]:
        """Return a list of human-readable findings. Empty list ⇒ clean."""
        findings: list[str] = []
        for name, hook in self._hooks.items():
            legit = self._legitimate_paths.get(hook.protocol)
            if legit is None:
                findings.append(
                    f"{name}: no legitimate-paths manifest registered for "
                    f"protocol {hook.protocol!r}"
                )
                continue
            extra = hook.invoked_paths - legit
            if extra:
                findings.append(
                    f"{name}: invokes non-legitimate paths {sorted(extra)} "
                    f"(rationale: {hook.rationale})"
                )
        return findings

    def assert_clean(self) -> None:
        findings = self.audit()
        if findings:
            raise StaticAuditError("\n".join(findings))


# ---------------------------------------------------------------------------
# Runtime auditor
# ---------------------------------------------------------------------------


@dataclass
class RuntimeViolation:
    kind: str  # "invalid_message" | "forged_signature" | "agreement_failure"
    round: int
    node: int
    detail: str


@dataclass
class RuntimeAuditor:
    """Stream-oriented runtime checker.

    The protocol-side adapter calls these methods. None of them write to or
    read from the protocol's state — they observe only.
    """

    protocol: str
    # Callables provided by the protocol adapter:
    validity_predicate: Optional[Callable[[dict], bool]] = None
    signer_extractor: Optional[Callable[[dict], int]] = None
    # Collected findings; the run aborts on the first non-empty list at flush.
    violations: list[RuntimeViolation] = field(default_factory=list)
    # Cross-replica commit tracking: round -> { node_id -> committed_digest }.
    _commits: dict[int, dict[int, str]] = field(default_factory=dict)

    def observe_message(self, msg: dict) -> None:
        """Check (a) and (b) for a single observed message."""
        if self.validity_predicate is not None and not self.validity_predicate(msg):
            self.violations.append(
                RuntimeViolation(
                    kind="invalid_message",
                    round=int(msg.get("round", -1)),
                    node=int(msg.get("node", -1)),
                    detail=f"validity_predicate rejected message {msg.get('id')!r}",
                )
            )
        if self.signer_extractor is not None:
            claimed = msg.get("signer")
            actual = self.signer_extractor(msg)
            if claimed is not None and int(claimed) != int(actual):
                self.violations.append(
                    RuntimeViolation(
                        kind="forged_signature",
                        round=int(msg.get("round", -1)),
                        node=int(actual),
                        detail=f"claimed signer {claimed}, actual {actual}",
                    )
                )

    def observe_commit(self, round_: int, node: int, digest: str) -> None:
        """Record a per-replica commit; agreement is checked at flush."""
        self._commits.setdefault(round_, {})[node] = digest

    def flush(self) -> list[RuntimeViolation]:
        """Finalize cross-replica agreement check; return all violations."""
        for round_, by_node in self._commits.items():
            digests = set(by_node.values())
            if len(digests) > 1:
                self.violations.append(
                    RuntimeViolation(
                        kind="agreement_failure",
                        round=round_,
                        node=-1,
                        detail=f"replicas disagree on round {round_}: {by_node!r}",
                    )
                )
        return list(self.violations)


# ---------------------------------------------------------------------------
# Bullshark-specific manifest stub
# ---------------------------------------------------------------------------

# P0 ships an empty manifest; P1 will populate this once we walk the Bullshark
# consensus crate and enumerate the honest-validator code paths. The manifest
# is reviewed by hand and lives in scripts/v2/refs/.
BULLSHARK_LEGITIMATE_PATHS_STUB: frozenset[str] = frozenset()


def make_default_auditor() -> StaticAuditor:
    a = StaticAuditor()
    a.register_legitimate_paths("bullshark", BULLSHARK_LEGITIMATE_PATHS_STUB)
    return a
