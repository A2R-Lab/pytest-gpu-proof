"""gpu-proof merge: shard-union semantics, refusal matrix, and end-to-end
verification of a merged receipt."""

import datetime
import json
import os
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from pytest_gpu_proof.config import GpuProofConfig
from pytest_gpu_proof.merge import MergeError, load_receipt, merge_payloads, merge_receipts
from pytest_gpu_proof.receipt import build_receipt_payload, finalize_receipt, write_receipt
from pytest_gpu_proof.signers.ed25519 import SSHSigner, _verify_with_key
from pytest_gpu_proof.verify import verify_receipt

@pytest.fixture
def signer_with_key(tmp_path, ed25519_keypair):
    private_key, public_key = ed25519_keypair
    key_path = tmp_path / "id_ed25519"
    key_path.write_bytes(
        private_key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
    )
    return SSHSigner(key_path=str(key_path)), public_key, str(key_path)


def _utcstamp(minutes_ago: int = 0) -> str:
    ts = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=minutes_ago)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _result(node_id, outcome="passed"):
    return {"node_id": node_id, "outcome": outcome, "duration_s": 0.01, "checks": []}


def _shard(tmp_path, tmp_git_repo, signer, name, results, *,
           started_ago=2, ended_ago=1, mutate=None, sign=True):
    os.chdir(tmp_git_repo)
    config = GpuProofConfig(enabled=True, fingerprint_paths=["src", "tests"])
    payload = build_receipt_payload(
        config, results, _utcstamp(started_ago), _utcstamp(ended_ago))
    if mutate is not None:
        mutate(payload)
    if sign:
        receipt = finalize_receipt(payload, signer)
    else:
        receipt = dict(payload)
        receipt["signature"] = None
    path = tmp_path / name
    write_receipt(receipt, str(path))
    return path


def _mock_github_keys(public_key):
    def _fake_verify(data, signature, username):
        return public_key if _verify_with_key(public_key, signature, data) else None
    return patch("pytest_gpu_proof.verify.find_verifying_github_key",
                 side_effect=_fake_verify)


def test_happy_merge_verifies(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key, key_path = signer_with_key
    a = _shard(tmp_path, tmp_git_repo, signer, "a.json",
               [_result("tests/test_add.py::test_add")], started_ago=10, ended_ago=8)
    b = _shard(tmp_path, tmp_git_repo, signer, "b.json",
               [_result("tests/test_add.py::test_sub")], started_ago=5, ended_ago=3)
    out = tmp_path / "merged.json"
    merged = merge_receipts([str(a), str(b)], str(out), key_path=key_path)

    assert [t["node_id"] for t in merged["tests"]] == [
        "tests/test_add.py::test_add", "tests/test_add.py::test_sub"]
    sess = merged["session"]
    # span = earliest start .. latest end across shards
    assert sess["started_at"] == json.loads(a.read_text())["session"]["started_at"]
    assert sess["ended_at"] == json.loads(b.read_text())["session"]["ended_at"]
    assert [s["source"] for s in sess["shards"]] == ["a.json", "b.json"]
    assert all(s["signer"] for s in sess["shards"])

    # the merged receipt goes through the UNCHANGED verifier
    os.chdir(tmp_git_repo)
    with _mock_github_keys(public_key):
        assert verify_receipt(receipt_path=str(out), policy_path=None,
                              repo_root=str(tmp_git_repo),
                              github_user_override="testuser",
                              max_age_days=None)


def test_refuses_commit_sha_mismatch(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, key_path = signer_with_key
    a = _shard(tmp_path, tmp_git_repo, signer, "a.json",
               [_result("t::a")])
    b = _shard(tmp_path, tmp_git_repo, signer, "b.json",
               [_result("t::b")],
               mutate=lambda p: p["repo"].__setitem__("commit_sha", "deadbeef"))
    with pytest.raises(MergeError, match="commit_sha"):
        merge_payloads([json.loads(a.read_text()), json.loads(b.read_text())],
                       ["a.json", "b.json"])


def test_refuses_fingerprint_mismatch(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, key_path = signer_with_key
    a = _shard(tmp_path, tmp_git_repo, signer, "a.json", [_result("t::a")])
    b = _shard(tmp_path, tmp_git_repo, signer, "b.json", [_result("t::b")],
               mutate=lambda p: p["fingerprint"].__setitem__("digest", "0" * 64))
    with pytest.raises(MergeError, match="fingerprint"):
        merge_payloads([json.loads(a.read_text()), json.loads(b.read_text())],
                       ["a.json", "b.json"])


def test_refuses_duplicate_node_id(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, key_path = signer_with_key
    a = _shard(tmp_path, tmp_git_repo, signer, "a.json", [_result("t::same")])
    b = _shard(tmp_path, tmp_git_repo, signer, "b.json", [_result("t::same")])
    with pytest.raises(MergeError, match="duplicate node_id"):
        merge_payloads([json.loads(a.read_text()), json.loads(b.read_text())],
                       ["a.json", "b.json"])


def test_refuses_environment_mismatch(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, key_path = signer_with_key
    a = _shard(tmp_path, tmp_git_repo, signer, "a.json", [_result("t::a")])
    b = _shard(tmp_path, tmp_git_repo, signer, "b.json", [_result("t::b")],
               mutate=lambda p: p["environment"].__setitem__("pytest_version", "0.0"))
    with pytest.raises(MergeError, match="environment.pytest_version"):
        merge_payloads([json.loads(a.read_text()), json.loads(b.read_text())],
                       ["a.json", "b.json"])


def test_unsigned_shards_merge_and_dirty_ors(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, key_path = signer_with_key
    a = _shard(tmp_path, tmp_git_repo, signer, "a.json", [_result("t::a")], sign=False)
    b = _shard(tmp_path, tmp_git_repo, signer, "b.json", [_result("t::b")], sign=False,
               mutate=lambda p: p["repo"].__setitem__("dirty", True))
    merged = merge_payloads([json.loads(a.read_text()), json.loads(b.read_text())],
                            ["a.json", "b.json"])
    assert merged["repo"]["dirty"] is True
    assert merged["session"]["shards"][0]["signer"] is None


def test_merged_unsigned_flag(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, key_path = signer_with_key
    a = _shard(tmp_path, tmp_git_repo, signer, "a.json", [_result("t::a")])
    out = tmp_path / "merged.json"
    merged = merge_receipts([str(a)], str(out), unsigned=True)
    assert merged["signature"] is None
    assert json.loads(out.read_text())["signature"] is None


def test_gpu_info_survives_cpu_only_shard(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, key_path = signer_with_key
    gpu = {"name": "FakeGPU", "driver_version": "1", "memory": "1 MiB"}
    a = _shard(tmp_path, tmp_git_repo, signer, "a.json", [_result("t::a")],
               mutate=lambda p: p["environment"].__setitem__("gpu_info", None))
    b = _shard(tmp_path, tmp_git_repo, signer, "b.json", [_result("t::b")],
               mutate=lambda p: p["environment"].__setitem__("gpu_info", gpu))
    merged = merge_payloads([json.loads(a.read_text()), json.loads(b.read_text())],
                            ["a.json", "b.json"])
    assert merged["environment"]["gpu_info"] == gpu


def test_load_receipt_rejects_bad_inputs(tmp_path):
    with pytest.raises(MergeError, match="readable"):
        load_receipt(str(tmp_path / "missing.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("[]")
    with pytest.raises(MergeError, match="no 'tests'"):
        load_receipt(str(bad))


def test_merge_rejects_empty_unsupported_and_zero_tests():
    with pytest.raises(MergeError, match="nothing"):
        merge_payloads([], [])
    with pytest.raises(MergeError, match="unsupported"):
        merge_payloads([{"schema_version": "9", "tests": [{}]}], ["x"])
    base = {
        "schema_version": "3",
        "repo": {"commit_sha": "a", "dirty": False},
        "fingerprint": {"digest": "d"},
        "mode": "local",
        "environment": {},
        "session": {"started_at": "a", "ended_at": "b", "outcome": "passed"},
        "tests": [],
    }
    with pytest.raises(MergeError, match="zero tests"):
        merge_payloads([base], ["x"])


def test_merge_schema_and_mode_mismatch(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, _ = signer_with_key
    a = json.loads(_shard(tmp_path, tmp_git_repo, signer, "a.json", [_result("t::a")]).read_text())
    b = json.loads(_shard(tmp_path, tmp_git_repo, signer, "b.json", [_result("t::b")]).read_text())
    b["schema_version"] = "2"
    with pytest.raises(MergeError, match="schema_version"):
        merge_payloads([a, b], ["a", "b"])
    b = dict(a)
    b["tests"] = [_result("t::b")]
    b["mode"] = "ci-gpu"
    with pytest.raises(MergeError, match="mode"):
        merge_payloads([a, b], ["a", "b"])


def test_merge_failed_session_and_github_override(
    tmp_path, tmp_git_repo, signer_with_key
):
    signer, _, key_path = signer_with_key
    a = _shard(tmp_path, tmp_git_repo, signer, "a.json", [_result("t::a")])
    b = _shard(
        tmp_path, tmp_git_repo, signer, "b.json", [_result("t::b")],
        mutate=lambda p: p["session"].__setitem__("outcome", "failed"),
    )
    out = tmp_path / "merged.json"
    merged = merge_receipts(
        [str(a), str(b)], str(out), key_path=key_path, github_user="merger"
    )
    assert merged["session"]["outcome"] == "failed"
    assert merged["signer"]["github_user"] == "merger"


def test_schema1_merge_has_no_schema3_session_fields():
    base = {
        "schema_version": "1",
        "repo": {"commit_sha": "a", "dirty": False},
        "fingerprint": {"digest": "d"},
        "mode": "local",
        "environment": {},
        "session": {"started_at": "a", "ended_at": "b"},
        "tests": [_result("t::a")],
        "signature": None,
    }
    merged = merge_payloads([base], ["one.json"])
    assert "outcome" not in merged["session"]
    assert "shards" not in merged
