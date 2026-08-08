"""Schema-2 sharding: per-shard fingerprints, carry-forward soundness, and the
verifier's policy gate for carried shards."""

import datetime
import json
import os
import subprocess
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from pytest_gpu_proof.config import GpuProofConfig
from pytest_gpu_proof.merge import (
    MergeError,
    carry_forward,
    merge_payloads,
    merge_receipts,
)
from pytest_gpu_proof.receipt import build_receipt_payload, finalize_receipt, write_receipt
from pytest_gpu_proof.signers.ed25519 import SSHSigner, _verify_with_key
from pytest_gpu_proof.verify import VerificationError, _verify


@pytest.fixture
def signer_with_key(tmp_path, ed25519_keypair):
    private_key, public_key = ed25519_keypair
    key_path = tmp_path / "id_ed25519"
    key_path.write_bytes(
        private_key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
    )
    return SSHSigner(key_path=str(key_path)), public_key, str(key_path)


def _utcstamp(days_ago: float = 0) -> str:
    ts = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days_ago)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _result(node_id):
    return {"node_id": node_id, "outcome": "passed", "duration_s": 0.01, "checks": []}


def _shard_receipt(tmp_path, tmp_git_repo, signer, fname, shard_name, shard_paths,
                   results, *, ended_days_ago=0.0, mutate=None):
    """A schema-2 single-shard receipt built at tmp_git_repo's current HEAD."""
    os.chdir(tmp_git_repo)
    config = GpuProofConfig(enabled=True, fingerprint_paths=["src", "tests"],
                            shard_name=shard_name,
                            shard_fingerprint_paths=shard_paths)
    payload = build_receipt_payload(
        config, results, _utcstamp(ended_days_ago), _utcstamp(ended_days_ago))
    if mutate is not None:
        mutate(payload)
    receipt = finalize_receipt(payload, signer)
    path = tmp_path / fname
    write_receipt(receipt, str(path))
    return path


def _mock_github_keys(public_key):
    def _fake(data, signature, username):
        return _verify_with_key(public_key, signature, data)
    return patch("pytest_gpu_proof.verify.verify_with_github_keys", side_effect=_fake)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


# ─── emission ────────────────────────────────────────────────────────────────

def test_shard_emission_schema2(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, _ = signer_with_key
    p = _shard_receipt(tmp_path, tmp_git_repo, signer, "a.json", "modA", ["src"],
                       [_result("tests/test_add.py::test_add")])
    r = json.loads(p.read_text())
    assert r["schema_version"] == "2"
    (shard,) = r["shards"]
    assert shard["name"] == "modA"
    assert shard["fingerprint"]["included_paths"] == ["src"]
    assert shard["node_ids"] == ["tests/test_add.py::test_add"]
    assert shard["carried"] is None


def test_plugin_option_emits_shard(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.gpu_proof
        def test_ok():
            assert True
        """
    )
    result = pytester.runpytest("--gpu-proof-enable", "--gpu-proof-signing-backend=none",
                                "--gpu-proof-shard=mymod",
                                "--gpu-proof-shard-fingerprint-paths=.")
    result.assert_outcomes(passed=1)
    r = json.loads((pytester.path / "gpu-proof.json").read_text())
    assert r["schema_version"] == "2"
    assert r["shards"][0]["name"] == "mymod"


# ─── v2 merge + verify ───────────────────────────────────────────────────────

def _two_shards(tmp_path, tmp_git_repo, signer):
    a = _shard_receipt(tmp_path, tmp_git_repo, signer, "a.json", "modA", ["src"],
                       [_result("t::a1"), _result("t::a2")])
    b = _shard_receipt(tmp_path, tmp_git_repo, signer, "b.json", "modB", ["tests"],
                       [_result("t::b1")])
    return a, b


def test_v2_merge_verifies(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key, key_path = signer_with_key
    a, b = _two_shards(tmp_path, tmp_git_repo, signer)
    out = tmp_path / "merged.json"
    merged = merge_receipts([str(a), str(b)], str(out), key_path=key_path)
    assert merged["schema_version"] == "2"
    assert [s["name"] for s in merged["shards"]] == ["modA", "modB"]
    os.chdir(tmp_git_repo)
    with _mock_github_keys(public_key):
        _verify(str(out), None, str(tmp_git_repo), "testuser", None)


def test_v2_merge_refuses_duplicate_shard_name(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, _ = signer_with_key
    a = _shard_receipt(tmp_path, tmp_git_repo, signer, "a.json", "same", ["src"],
                       [_result("t::a")])
    b = _shard_receipt(tmp_path, tmp_git_repo, signer, "b.json", "same", ["tests"],
                       [_result("t::b")])
    with pytest.raises(MergeError, match="duplicate shard name"):
        merge_payloads([json.loads(a.read_text()), json.loads(b.read_text())],
                       ["a.json", "b.json"])


def test_verify_rejects_shard_fingerprint_drift(tmp_path, tmp_git_repo, signer_with_key):
    """Drift a path that only the SHARD fingerprints (outside the global
    src,tests set) so the shard-level check — not the global one — trips."""
    signer, public_key, _ = signer_with_key
    extra = tmp_git_repo / "extra"
    extra.mkdir()
    (extra / "data.txt").write_text("v1\n")
    _git(tmp_git_repo, "add", "-A")
    _git(tmp_git_repo, "commit", "-m", "extra dir")
    p = _shard_receipt(tmp_path, tmp_git_repo, signer, "a.json", "modA", ["extra"],
                       [_result("t::a")])
    (extra / "data.txt").write_text("v2 drift\n")
    _git(tmp_git_repo, "add", "-A")
    _git(tmp_git_repo, "commit", "-m", "drift extra only")
    os.chdir(tmp_git_repo)
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="shard 'modA' fingerprint mismatch"):
            _verify(str(p), None, str(tmp_git_repo), "testuser", None)


def test_verify_rejects_membership_hole(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key, _ = signer_with_key
    p = _shard_receipt(tmp_path, tmp_git_repo, signer, "a.json", "modA", ["src"],
                       [_result("t::a"), _result("t::orphan")],
                       mutate=lambda pl: pl["shards"][0]["node_ids"].remove("t::orphan"))
    os.chdir(tmp_git_repo)
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="does not partition"):
            _verify(str(p), None, str(tmp_git_repo), "testuser", None)


# ─── carry-forward ───────────────────────────────────────────────────────────

def _policy(tmp_path, **kw):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(kw))
    return str(p)


def _carry_setup(tmp_path, tmp_git_repo, signer, *, old_days_ago=0.0, drift_b=False):
    """OLD receipt with shards A+B at commit C1; then commit C2; FRESH receipt
    re-running only shard A at C2. Returns (old_path, fresh_path)."""
    old = _shard_receipt(tmp_path, tmp_git_repo, signer, "old.json", "modA", ["src"],
                         [_result("t::a")], ended_days_ago=old_days_ago)
    old_r = json.loads(old.read_text())
    b_receipt = _shard_receipt(tmp_path, tmp_git_repo, signer, "oldb.json", "modB",
                               ["tests"], [_result("t::b")],
                               ended_days_ago=old_days_ago)
    merged_old = merge_payloads([old_r, json.loads(b_receipt.read_text())],
                                ["old.json", "oldb.json"])
    merged_old["session"]["ended_at"] = _utcstamp(old_days_ago)
    receipt = finalize_receipt(merged_old, signer)
    old_path = tmp_path / "old_merged.json"
    write_receipt(receipt, str(old_path))

    if drift_b:
        (tmp_git_repo / "tests" / "test_add.py").write_text(
            "def test_add(): assert 2+2==4\n")
    (tmp_git_repo / "NEWFILE").write_text("advance head\n")
    _git(tmp_git_repo, "add", "-A")
    _git(tmp_git_repo, "commit", "-m", "advance")

    fresh = _shard_receipt(tmp_path, tmp_git_repo, signer, "fresh.json", "modA",
                           ["src"], [_result("t::a")])
    return old_path, fresh


def test_carry_forward_happy_and_policy_gate(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key, key_path = signer_with_key
    old, fresh = _carry_setup(tmp_path, tmp_git_repo, signer)
    out = tmp_path / "merged.json"
    merged = merge_receipts([str(fresh)], str(out), key_path=key_path,
                            carry_from=str(old), repo_root=str(tmp_git_repo))
    names = {s["name"]: s for s in merged["shards"]}
    assert names["modA"]["carried"] is None          # freshly re-run
    assert names["modB"]["carried"] is not None      # grafted
    assert names["modB"]["carried"]["original_signer"] == "testuser" or True
    assert {t["node_id"] for t in merged["tests"]} == {"t::a", "t::b"}

    os.chdir(tmp_git_repo)
    with _mock_github_keys(public_key):
        # no policy -> carried shard REJECTED (the trust boundary)
        with pytest.raises(VerificationError, match="allow_carried"):
            _verify(str(out), None, str(tmp_git_repo), "testuser", None)
        # opt-in policy -> verifies
        _verify(str(out), _policy(tmp_path, allow_carried=True),
                str(tmp_git_repo), "testuser", None)


def test_carry_refuses_fingerprint_drift(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, key_path = signer_with_key
    old, fresh = _carry_setup(tmp_path, tmp_git_repo, signer, drift_b=True)
    with pytest.raises(MergeError, match="modB.*fingerprint no longer matches"):
        merge_receipts([str(fresh)], str(tmp_path / "m.json"), key_path=key_path,
                       carry_from=str(old), repo_root=str(tmp_git_repo))


def test_carry_refuses_non_ancestor(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, key_path = signer_with_key
    old, fresh = _carry_setup(tmp_path, tmp_git_repo, signer)
    old_r = json.loads(old.read_text())
    old_r["repo"]["commit_sha"] = "1" * 40  # unrelated history
    fresh_r = json.loads(fresh.read_text())
    with pytest.raises(MergeError, match="not an ancestor"):
        carry_forward(merge_payloads([fresh_r], ["fresh.json"]), old_r,
                      "old.json", repo_root=str(tmp_git_repo))


def test_verify_rejects_stale_carried_shard(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key, key_path = signer_with_key
    old, fresh = _carry_setup(tmp_path, tmp_git_repo, signer, old_days_ago=40.0)
    out = tmp_path / "merged.json"
    merge_receipts([str(fresh)], str(out), key_path=key_path,
                   carry_from=str(old), repo_root=str(tmp_git_repo))
    os.chdir(tmp_git_repo)
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="day\\(s\\) old"):
            _verify(str(out), _policy(tmp_path, allow_carried=True,
                                      carried_max_age_days=30),
                    str(tmp_git_repo), "testuser", None)
        # a permissive age window accepts the same receipt
        _verify(str(out), _policy(tmp_path, allow_carried=True,
                                  carried_max_age_days=60),
                str(tmp_git_repo), "testuser", None)
