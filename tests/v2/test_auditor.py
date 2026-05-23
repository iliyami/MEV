"""Invariant Auditor scaffold tests."""

import pytest

from scripts.v2 import auditor


def test_static_auditor_clean_when_hook_paths_subset():
    a = auditor.StaticAuditor()
    a.register_legitimate_paths("bullshark", {"propose_block", "select_parents", "broadcast"})
    a.register_hook(
        auditor.HookDescriptor(
            name="bullshark.fissure.parent_filter",
            protocol="bullshark",
            invoked_paths=frozenset({"select_parents"}),
            rationale="Honest validators legally choose which parents to include.",
        )
    )
    assert a.audit() == []
    a.assert_clean()  # does not raise


def test_static_auditor_flags_non_legitimate_path():
    a = auditor.StaticAuditor()
    a.register_legitimate_paths("bullshark", {"propose_block", "select_parents"})
    a.register_hook(
        auditor.HookDescriptor(
            name="bullshark.cheaty.invalid_vote",
            protocol="bullshark",
            invoked_paths=frozenset({"forge_signature"}),
            rationale="Hypothetical bad hook for unit test.",
        )
    )
    findings = a.audit()
    assert len(findings) == 1
    assert "forge_signature" in findings[0]
    with pytest.raises(auditor.StaticAuditError):
        a.assert_clean()


def test_static_auditor_missing_manifest_flagged():
    a = auditor.StaticAuditor()
    a.register_hook(
        auditor.HookDescriptor(
            name="x.y",
            protocol="bullshark",
            invoked_paths=frozenset({"a"}),
            rationale="r",
        )
    )
    findings = a.audit()
    assert "no legitimate-paths manifest" in findings[0]


def test_runtime_auditor_detects_forged_signature():
    ra = auditor.RuntimeAuditor(
        protocol="bullshark",
        signer_extractor=lambda m: m["true_signer"],
    )
    ra.observe_message({"id": "m1", "round": 5, "node": 7, "signer": 7, "true_signer": 7})
    ra.observe_message({"id": "m2", "round": 5, "node": 7, "signer": 3, "true_signer": 7})
    violations = ra.flush()
    assert any(v.kind == "forged_signature" for v in violations)


def test_runtime_auditor_detects_invalid_message():
    ra = auditor.RuntimeAuditor(
        protocol="bullshark",
        validity_predicate=lambda m: m.get("ok", True),
    )
    ra.observe_message({"id": "m1", "round": 5, "node": 7, "ok": True})
    ra.observe_message({"id": "m2", "round": 5, "node": 7, "ok": False})
    violations = ra.flush()
    assert any(v.kind == "invalid_message" for v in violations)


def test_runtime_auditor_detects_agreement_failure():
    ra = auditor.RuntimeAuditor(protocol="bullshark")
    ra.observe_commit(round_=10, node=0, digest="abc")
    ra.observe_commit(round_=10, node=1, digest="abc")
    ra.observe_commit(round_=10, node=2, digest="xyz")  # disagreement
    violations = ra.flush()
    assert any(v.kind == "agreement_failure" for v in violations)


def test_runtime_auditor_clean_when_consistent():
    ra = auditor.RuntimeAuditor(protocol="bullshark")
    ra.observe_commit(round_=10, node=0, digest="abc")
    ra.observe_commit(round_=10, node=1, digest="abc")
    ra.observe_commit(round_=11, node=0, digest="def")
    ra.observe_commit(round_=11, node=1, digest="def")
    assert ra.flush() == []
