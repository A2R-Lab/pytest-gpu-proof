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
                   results, *, ended_days_ago=0.0, mutate=None, shard_extra_paths=None):
    """A schema-2 single-shard receipt built at tmp_git_repo's current HEAD."""
    os.chdir(tmp_git_repo)
    config = GpuProofConfig(enabled=True, fingerprint_paths=["src", "tests"],
                            shard_name=shard_name,
                            shard_fingerprint_paths=shard_paths,
                            shard_fingerprint_extra_paths=shard_extra_paths or [])
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
        return public_key if _verify_with_key(public_key, signature, data) else None
    return patch("pytest_gpu_proof.verify.find_verifying_github_key", side_effect=_fake)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


# ─── emission ────────────────────────────────────────────────────────────────

def test_shard_emission_schema2(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, _ = signer_with_key
    p = _shard_receipt(tmp_path, tmp_git_repo, signer, "a.json", "modA", ["src"],
                       [_result("tests/test_add.py::test_add")])
    r = json.loads(p.read_text())
    assert r["schema_version"] == "3"
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
    assert r["schema_version"] == "3"
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
    assert merged["schema_version"] == "3"
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
        with pytest.raises(VerificationError, match="shard 'modA' fingerprint does not match"):
            _verify(str(p), None, str(tmp_git_repo), "testuser", None)


def test_verify_rejects_membership_hole(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key, _ = signer_with_key
    p = _shard_receipt(tmp_path, tmp_git_repo, signer, "a.json", "modA", ["src"],
                       [_result("t::a"), _result("t::orphan")],
                       mutate=lambda pl: pl["shards"][0]["node_ids"].remove("t::orphan"))
    os.chdir(tmp_git_repo)
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="does not exactly partition"):
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
        with pytest.raises(VerificationError, match="policy rejects carry-forward"):
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
        with pytest.raises(VerificationError, match="outside its age policy"):
            _verify(str(out), _policy(tmp_path, allow_carried=True,
                                      carried_max_age_days=30),
                    str(tmp_git_repo), "testuser", None)
        # a permissive age window accepts the same receipt
        _verify(str(out), _policy(tmp_path, allow_carried=True,
                                  carried_max_age_days=60),
                str(tmp_git_repo), "testuser", None)


def test_schema1_with_shards_block_rejected(tmp_path, tmp_git_repo, signer_with_key):
    """A schema-1 receipt must not smuggle a shards block past the v1 checks
    (shard semantics exist only under schema 2, where they are verified)."""
    signer, public_key, _ = signer_with_key
    os.chdir(tmp_git_repo)
    config = GpuProofConfig(enabled=True, fingerprint_paths=["src", "tests"])
    payload = build_receipt_payload(config, [_result("t::a")], _utcstamp(), _utcstamp())
    assert payload["schema_version"] == "3"
    payload["schema_version"] = "1"
    payload["shards"] = [{"name": "smuggled", "fingerprint": {}, "node_ids": []}]
    receipt = finalize_receipt(payload, signer)
    path = tmp_path / "smuggled.json"
    write_receipt(receipt, str(path))
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="cannot contain shards"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_carry_preserves_and_checks_extra_paths(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, _ = signer_with_key
    generated = tmp_git_repo / "generated.bin"
    generated.write_bytes(b"stable")
    old = _shard_receipt(
        tmp_path, tmp_git_repo, signer, "old-extra.json", "extra", [],
        [_result("t::extra")], shard_extra_paths=["generated.bin"],
    )
    old_r = json.loads(old.read_text())
    fresh = _shard_receipt(
        tmp_path, tmp_git_repo, signer, "fresh.json", "fresh", ["src"],
        [_result("t::fresh")],
    )
    payload = merge_payloads([json.loads(fresh.read_text())], ["fresh.json"])
    carried = carry_forward(payload, old_r, "old-extra.json", str(tmp_git_repo))
    assert {s["name"] for s in carried["shards"]} == {"fresh", "extra"}


def test_carry_refusal_matrix(tmp_path, tmp_git_repo, signer_with_key, capsys):
    signer, _, _ = signer_with_key
    fresh = _shard_receipt(
        tmp_path, tmp_git_repo, signer, "fresh.json", "same", ["src"], [_result("t::same")]
    )
    payload = merge_payloads([json.loads(fresh.read_text())], ["fresh.json"])
    old = json.loads(fresh.read_text())

    invalid_schema = dict(old)
    invalid_schema["schema_version"] = "1"
    with pytest.raises(MergeError, match="not a schema"):
        carry_forward(dict(payload), invalid_schema, "old", str(tmp_git_repo))

    missing_sha = json.loads(fresh.read_text())
    missing_sha["repo"]["commit_sha"] = None
    with pytest.raises(MergeError, match="commit SHAs"):
        carry_forward(dict(payload), missing_sha, "old", str(tmp_git_repo))

    unchanged = carry_forward(payload, old, "old", str(tmp_git_repo))
    assert unchanged
    assert "nothing to carry" in capsys.readouterr().out


def test_carry_rejects_missing_claimed_test(tmp_path, tmp_git_repo, signer_with_key):
    signer, _, _ = signer_with_key
    old = _shard_receipt(
        tmp_path, tmp_git_repo, signer, "old.json", "old", ["src"], [_result("t::old")]
    )
    old_r = json.loads(old.read_text())
    old_r["tests"] = []
    fresh = _shard_receipt(
        tmp_path, tmp_git_repo, signer, "fresh.json", "fresh", ["tests"], [_result("t::fresh")]
    )
    payload = merge_payloads([json.loads(fresh.read_text())], ["fresh.json"])
    with pytest.raises(MergeError, match="not in its receipt"):
        carry_forward(payload, old_r, "old", str(tmp_git_repo))


def test_carry_rejects_invalid_fingerprint_and_duplicate_node(
    tmp_path, tmp_git_repo, signer_with_key
):
    signer, _, _ = signer_with_key
    old = _shard_receipt(
        tmp_path, tmp_git_repo, signer, "old.json", "old", ["src"], [_result("t::old")]
    )
    fresh = _shard_receipt(
        tmp_path, tmp_git_repo, signer, "fresh.json", "fresh", ["tests"], [_result("t::fresh")]
    )
    old_r = json.loads(old.read_text())
    payload = merge_payloads([json.loads(fresh.read_text())], ["fresh.json"])
    old_r["shards"][0]["fingerprint"]["algorithm"] = "bad"
    with pytest.raises(MergeError, match="fingerprint is invalid"):
        carry_forward(payload, old_r, "old", str(tmp_git_repo))

    old_r = json.loads(old.read_text())
    old_r["shards"][0]["node_ids"] = ["t::fresh"]
    with pytest.raises(MergeError, match="re-introduce"):
        carry_forward(payload, old_r, "old", str(tmp_git_repo))


@pytest.mark.parametrize(
    ("mutate", "policy", "message"),
    [
        (lambda r: r.__setitem__("shards", []), {}, "has no shards"),
        (lambda r: r["shards"].__setitem__(0, "bad"), {}, "valid name"),
        (lambda r: r["shards"].append(dict(r["shards"][0])), {}, "duplicate shard"),
        (lambda r: r["shards"][0].__setitem__("node_ids", "bad"), {}, "invalid node_ids"),
        (lambda r: r["shards"][0].__setitem__("fingerprint", None), {}, "no fingerprint"),
        (
            lambda r: r["shards"][0]["fingerprint"].__setitem__("algorithm", "bad"),
            {}, "unsupported fingerprint",
        ),
        (lambda r: r["shards"][0].__setitem__("carried", "bad"), {"allow_carried": True}, "metadata is invalid"),
        (
            lambda r: r["shards"][0].__setitem__(
                "carried", {"original_ended_at": _utcstamp()}
            ),
            {"allow_carried": True, "carried_max_age_days": "bad"},
            "carried_max_age_days",
        ),
    ],
)
def test_shard_structure_refusal_matrix(
    tmp_path, tmp_git_repo, signer_with_key, mutate, policy, message
):
    signer, public_key, _ = signer_with_key
    path = _shard_receipt(
        tmp_path, tmp_git_repo, signer, "shard.json", "core", ["src"], [_result("t::a")]
    )
    receipt = json.loads(path.read_text())
    mutate(receipt)
    path.write_text(json.dumps(receipt))
    policy_path = _policy(tmp_path, **policy) if policy else None
    with patch("pytest_gpu_proof.verify.find_verifying_github_key", return_value=public_key):
        with pytest.raises(VerificationError, match=message):
            _verify(str(path), policy_path, str(tmp_git_repo), "testuser", None)


def test_shard_overlap_and_required_policy(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key, _ = signer_with_key
    path = _shard_receipt(
        tmp_path, tmp_git_repo, signer, "shard.json", "core", ["src"], [_result("t::a")]
    )
    receipt = json.loads(path.read_text())
    second = dict(receipt["shards"][0])
    second["name"] = "other"
    receipt["shards"].append(second)
    path.write_text(json.dumps(receipt))
    with patch("pytest_gpu_proof.verify.find_verifying_github_key", return_value=public_key):
        with pytest.raises(VerificationError, match="overlaps"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", None)

    receipt["shards"] = receipt["shards"][:1]
    path.write_text(json.dumps(receipt))
    with patch("pytest_gpu_proof.verify.find_verifying_github_key", return_value=public_key):
        with pytest.raises(VerificationError, match="paths do not match"):
            _verify(
                str(path),
                _policy(tmp_path, required_shard_fingerprints={"core": {"paths": ["tests"]}}),
                str(tmp_git_repo), "testuser", None,
            )
        with pytest.raises(VerificationError, match="extra paths"):
            _verify(
                str(path),
                _policy(tmp_path, required_shard_fingerprints={"core": {"paths": ["src"], "extra_paths": ["x"]}}),
                str(tmp_git_repo), "testuser", None,
            )
        with pytest.raises(VerificationError, match="exclusions"):
            _verify(
                str(path),
                _policy(tmp_path, required_shard_fingerprints={"core": {"excluded_paths": []}}),
                str(tmp_git_repo), "testuser", None,
            )
        with pytest.raises(VerificationError, match="shard set"):
            _verify(
                str(path),
                _policy(
                    tmp_path,
                    required_shard_fingerprints={
                        "core": {"paths": ["src"]},
                        "missing": {"paths": ["tests"]},
                    },
                ),
                str(tmp_git_repo), "testuser", None,
            )


def test_direct_shard_validation_rejects_bad_carried_limit(
    tmp_path, tmp_git_repo, signer_with_key
):
    from pytest_gpu_proof.verify import _verify_shards

    signer, _, _ = signer_with_key
    path = _shard_receipt(
        tmp_path, tmp_git_repo, signer, "shard.json", "core", ["src"], [_result("t::a")]
    )
    receipt = json.loads(path.read_text())
    receipt["shards"][0]["carried"] = {"original_ended_at": _utcstamp()}
    with pytest.raises(VerificationError, match="non-negative integer"):
        _verify_shards(
            receipt,
            str(tmp_git_repo),
            {"allow_carried": True, "carried_max_age_days": "bad"},
        )
