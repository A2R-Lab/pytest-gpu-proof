"""
Verifier tests. GitHub key fetching is patched so tests run offline and fast.
"""

import datetime
import json
import os
import sys
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from pytest_gpu_proof.receipt import (
    build_receipt_payload,
    finalize_receipt,
    write_receipt,
)
from pytest_gpu_proof.signers.ed25519 import SSHSigner, _verify_with_key
from pytest_gpu_proof.verify import VerificationError, _load_policy, _verify, verify_receipt


@pytest.fixture
def keypair():
    pk = Ed25519PrivateKey.generate()
    return pk, pk.public_key()


@pytest.fixture
def signer_with_key(tmp_path, keypair):
    private_key, public_key = keypair
    key_path = tmp_path / "id_ed25519"
    key_path.write_bytes(
        private_key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
    )
    return SSHSigner(key_path=str(key_path)), public_key


def _utcstamp(days_ago: int = 0) -> str:
    ts = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days_ago)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_receipt(
    tmp_path,
    tmp_git_repo,
    signer,
    results=None,
    ended_at=None,
    mutate=None,
    sign=True,
):
    """Build a receipt against tmp_git_repo, optionally mutating the payload
    *before* signing (so the signature stays valid)."""
    from pytest_gpu_proof.config import GpuProofConfig

    os.chdir(tmp_git_repo)
    config = GpuProofConfig(enabled=True, fingerprint_paths=["src", "tests"])
    results = results or [
        {
            "node_id": "tests/test_add.py::test_add",
            "outcome": "passed",
            "duration_s": 0.01,
            "checks": [],
        }
    ]
    now = _utcstamp()
    stamp = ended_at or now
    payload = build_receipt_payload(config, results, stamp, stamp)
    if mutate is not None:
        mutate(payload)
    if sign:
        receipt = finalize_receipt(payload, signer)
    else:
        receipt = dict(payload)
        receipt["signature"] = None
    path = tmp_path / "gpu-proof.json"
    write_receipt(receipt, str(path))
    return path


@pytest.fixture
def good_receipt(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer)
    return path, public_key


def _mock_github_keys(public_key):
    """Return a patcher that makes schema-3 verification use our local key."""
    def _fake_verify(data, signature, username):
        return public_key if _verify_with_key(public_key, signature, data) else None

    return patch(
        "pytest_gpu_proof.verify.find_verifying_github_key",
        side_effect=_fake_verify,
    )


def test_verify_passes(good_receipt, tmp_git_repo):
    path, public_key = good_receipt
    with _mock_github_keys(public_key):
        _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_verify_passes_when_receipt_is_committed_after_code(good_receipt, tmp_git_repo):
    path, public_key = good_receipt
    receipt_path = tmp_git_repo / "gpu-proof.json"
    receipt_path.write_text(path.read_text())

    import subprocess

    subprocess.run(["git", "add", "-f", "gpu-proof.json"], cwd=tmp_git_repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add GPU proof receipt"],
        cwd=tmp_git_repo,
        check=True,
        capture_output=True,
    )

    with _mock_github_keys(public_key):
        _verify(str(receipt_path), None, str(tmp_git_repo), "testuser", None)


def test_verify_fails_on_bad_signature(good_receipt, tmp_git_repo):
    path, _ = good_receipt
    other_key = Ed25519PrivateKey.generate().public_key()
    with _mock_github_keys(other_key):
        with pytest.raises(VerificationError, match="signature does not match"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_verify_fails_on_modified_receipt(good_receipt, tmp_git_repo):
    path, public_key = good_receipt
    receipt = json.loads(path.read_text())
    receipt["tests"][0]["outcome"] = "failed"
    path.write_text(json.dumps(receipt))

    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="signature does not match"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_verify_fails_on_stale_receipt(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key
    # Genuinely-signed receipt whose ended_at is far in the past: every check
    # up to freshness must pass, and freshness must be the one that fails.
    path = _make_receipt(
        tmp_path, tmp_git_repo, signer, ended_at="2020-01-01T00:00:00Z"
    )
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match=r"older than the 30-day policy"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", 30)


def test_verify_max_age_zero_is_respected(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer, ended_at=_utcstamp(days_ago=5))
    with _mock_github_keys(public_key):
        # An explicit override of 0 must not silently fall back to 30.
        with pytest.raises(VerificationError, match=r"older than the 0-day policy"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", 0)


def test_verify_rejects_unsigned_receipt(tmp_path, tmp_git_repo, signer_with_key):
    signer, _ = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer, sign=False)
    with pytest.raises(VerificationError, match="unsigned"):
        _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_verify_accepts_unsigned_receipt_with_allow_unsigned(
    tmp_path, tmp_git_repo, signer_with_key
):
    signer, _ = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer, sign=False)
    _verify(str(path), None, str(tmp_git_repo), "testuser", None, allow_unsigned=True)


def test_verify_rejects_skipped_tests(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key
    results = [
        {"node_id": "tests/test_add.py::test_add", "outcome": "passed",
         "duration_s": 0.01, "checks": []},
        {"node_id": "tests/test_add.py::test_skipped", "outcome": "skipped",
         "duration_s": 0.0, "checks": []},
    ]
    path = _make_receipt(tmp_path, tmp_git_repo, signer, results=results)
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="skipped"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", None)
        # Explicit opt-in accepts them.
        _verify(
            str(path), None, str(tmp_git_repo), "testuser", None, allow_skipped=True
        )


def test_verify_missing_digest_raises_clean_error(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key

    def drop_digest(payload):
        del payload["fingerprint"]["digest"]

    path = _make_receipt(tmp_path, tmp_git_repo, signer, mutate=drop_digest)
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="empty or missing"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_yaml_policy_without_pyyaml_raises(tmp_path, monkeypatch):
    from pytest_gpu_proof.verify import _load_policy

    policy = tmp_path / "policy.yaml"
    policy.write_text("max_age_days: 7\n")
    monkeypatch.setitem(sys.modules, "yaml", None)  # force ImportError
    with pytest.raises(VerificationError, match="yaml.*extra|YAML policy"):
        _load_policy(str(policy))


def test_json_policy_works_without_pyyaml(tmp_path, monkeypatch):
    from pytest_gpu_proof.verify import _load_policy

    policy = tmp_path / "policy.json"
    policy.write_text('{"max_age_days": 7}')
    monkeypatch.setitem(sys.modules, "yaml", None)
    assert _load_policy(str(policy)) == {"max_age_days": 7}


def test_require_gpu_rejects_null_gpu_info(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key

    def null_gpu(payload):
        payload["environment"]["gpu_info"] = None

    path = _make_receipt(tmp_path, tmp_git_repo, signer, mutate=null_gpu)
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="GPU information"):
            _verify(
                str(path), None, str(tmp_git_repo), "testuser", None, require_gpu=True
            )
        # Off by default: same receipt verifies fine.
        _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_require_gpu_accepts_present_gpu_info(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key

    def fake_gpu(payload):
        payload["environment"]["gpu_info"] = {
            "name": "NVIDIA Test GPU",
            "driver_version": "555.0",
            "memory": "8192 MiB",
        }

    path = _make_receipt(tmp_path, tmp_git_repo, signer, mutate=fake_gpu)
    with _mock_github_keys(public_key):
        _verify(str(path), None, str(tmp_git_repo), "testuser", None, require_gpu=True)


def test_verify_fails_on_failed_test(tmp_path, tmp_git_repo, signer_with_key):
    from pytest_gpu_proof.config import GpuProofConfig

    os.chdir(tmp_git_repo)
    signer, public_key = signer_with_key
    config = GpuProofConfig(enabled=True, fingerprint_paths=["src", "tests"])
    results = [
        {
            "node_id": "tests/test_add.py::test_add",
            "outcome": "failed",
            "duration_s": 0.01,
            "checks": [],
        }
    ]
    import datetime
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = build_receipt_payload(config, results, now, now)
    receipt = finalize_receipt(payload, signer)
    path = tmp_path / "gpu-proof.json"
    write_receipt(receipt, str(path))

    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="did not pass"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", None)


# ─── expected-skips baseline ────────────────────────────────────────────────

def _mixed_results():
    return [
        {"node_id": "tests/test_add.py::test_add", "outcome": "passed",
         "duration_s": 0.01, "checks": []},
        {"node_id": "tests/test_add.py::test_skipped", "outcome": "skipped",
         "duration_s": 0.0, "checks": []},
    ]


def test_expected_skips_exact_match_passes(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer, results=_mixed_results())
    baseline = tmp_path / "expected_skips.txt"
    baseline.write_text(
        "# known-legitimate skips\n"
        "\n"
        "tests/test_add.py::test_skipped\n"
    )
    with _mock_github_keys(public_key):
        _verify(
            str(path), None, str(tmp_git_repo), "testuser", None,
            expected_skips_path=str(baseline),
        )


def test_expected_skips_rejects_unexpected_skip(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer, results=_mixed_results())
    baseline = tmp_path / "expected_skips.txt"
    baseline.write_text("tests/test_add.py::test_other_skip\n")
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="skip set"):
            _verify(
                str(path), None, str(tmp_git_repo), "testuser", None,
                expected_skips_path=str(baseline),
            )


def test_expected_skips_rejects_stale_baseline(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key
    # all tests pass — the baseline entry no longer skips
    path = _make_receipt(tmp_path, tmp_git_repo, signer)
    baseline = tmp_path / "expected_skips.txt"
    baseline.write_text("tests/test_add.py::test_skipped\n")
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="skip set"):
            _verify(
                str(path), None, str(tmp_git_repo), "testuser", None,
                expected_skips_path=str(baseline),
            )


def test_expected_skips_mutually_exclusive_with_allow_skipped(
    tmp_path, tmp_git_repo, signer_with_key
):
    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer, results=_mixed_results())
    baseline = tmp_path / "expected_skips.txt"
    baseline.write_text("tests/test_add.py::test_skipped\n")
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="mutually exclusive"):
            _verify(
                str(path), None, str(tmp_git_repo), "testuser", None,
                allow_skipped=True, expected_skips_path=str(baseline),
            )


def test_expected_skips_from_toml(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer, results=_mixed_results())
    (tmp_git_repo / "pyproject.toml").write_text(
        "[tool.gpu_proof]\n"
        'expected_skips = ["tests/test_add.py::test_skipped"]\n'
    )
    with _mock_github_keys(public_key):
        _verify(str(path), None, str(tmp_git_repo), "testuser", None)


# ─── strict schema and policy validation ───────────────────────────────────

def _policy(tmp_path, content, suffix=".json"):
    path = tmp_path / f"policy{suffix}"
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return str(path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p.__setitem__("repo", []), "repo.*object"),
        (lambda p: p.__setitem__("environment", []), "environment.*object"),
        (lambda p: p.__setitem__("mode", "unknown"), "mode is missing"),
        (lambda p: p["repo"].__setitem__("commit_sha", ""), "commit_sha"),
        (lambda p: p.__setitem__("tests", []), "no test results"),
        (lambda p: p["tests"].__setitem__(0, "bad"), "valid node_id"),
        (lambda p: p["tests"][0].__setitem__("outcome", "maybe"), "invalid outcome"),
        (lambda p: p["tests"][0].__setitem__("checks", {}), "checks must be a list"),
        (lambda p: p["tests"][0].__setitem__("checks", ["bad"]), r"checks\[0\] is invalid"),
        (lambda p: p["tests"].append(dict(p["tests"][0])), "duplicate test"),
        (lambda p: p["session"].__setitem__("node_ids", []), "does not exactly match"),
        (lambda p: p["session"].__setitem__("started_at", None), "not a UTC timestamp"),
        (lambda p: p["session"].__setitem__("ended_at", "bad"), "not a valid UTC"),
        (
            lambda p: p["session"].update(
                started_at="2026-01-02T00:00:00Z", ended_at="2026-01-01T00:00:00Z"
            ),
            "precedes",
        ),
        (lambda p: p["session"].__setitem__("outcome", "unknown"), "session.outcome"),
    ],
)
def test_structure_validation_errors(
    tmp_path, tmp_git_repo, signer_with_key, mutate, message
):
    signer, _ = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer, mutate=mutate, sign=False)
    with pytest.raises(VerificationError, match=message):
        _verify(str(path), None, str(tmp_git_repo), "testuser", None, allow_unsigned=True)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{bad", "cannot read policy"),
        ("[]", "policy must"),
        ('{"unknown": true}', "unknown policy"),
        ('{"signer_mode": "closed"}', "signer_mode"),
        ('{"signer_mode": "restricted"}', "no allowlist"),
    ],
)
def test_policy_validation_errors(tmp_path, content, message):
    with pytest.raises(VerificationError, match=message):
        _load_policy(_policy(tmp_path, content))


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        ({"allowed_signers": "alice"}, "list of strings"),
        ({"allowed_signers": [""]}, "list of strings"),
        ({"allow_dirty": "yes"}, "boolean"),
        ({"allow_carried": 1}, "boolean"),
        ({"max_age_days": True}, "non-negative integer"),
        ({"carried_max_age_days": -1}, "non-negative integer"),
        ({"require_mode": "remote"}, "local.*ci-gpu"),
        ({"required_test_manifest": []}, "path string"),
        ({"required_shard_fingerprints": []}, "must be an object"),
        ({"required_shard_fingerprints": {"a": []}}, "scope must be an object"),
        ({"required_shard_fingerprints": {"a": {"bad": []}}}, "unknown policy"),
        ({"required_shard_fingerprints": {"a": {"paths": "src"}}}, "list of strings"),
    ],
)
def test_policy_field_types_are_strict(tmp_path, policy, message):
    with pytest.raises(VerificationError, match=message):
        _load_policy(_policy(tmp_path, policy))


def test_policy_empty_and_yaml(tmp_path):
    assert _load_policy(None) == {}
    assert _load_policy(_policy(tmp_path, "null")) == {}
    assert _load_policy(_policy(tmp_path, "max_age_days: 5\n", ".yaml")) == {
        "max_age_days": 5
    }
    with pytest.raises(VerificationError, match="cannot read policy"):
        _load_policy(str(tmp_path / "missing.json"))


def test_open_and_restricted_signer_modes(
    tmp_path, tmp_git_repo, signer_with_key
):
    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer)
    key_fp = json.loads(path.read_text())["signer"]["key_fingerprint"]
    with _mock_github_keys(public_key):
        _verify(
            str(path),
            _policy(tmp_path, {"signer_mode": "restricted", "allowed_signers": ["testuser"]}),
            str(tmp_git_repo), "testuser", None,
        )
        _verify(
            str(path),
            _policy(tmp_path, {"signer_mode": "restricted", "allowed_key_fingerprints": [key_fp]}),
            str(tmp_git_repo), "testuser", None,
        )
        with pytest.raises(VerificationError, match="signer @testuser"):
            _verify(
                str(path),
                _policy(tmp_path, {"signer_mode": "restricted", "allowed_signers": ["other"]}),
                str(tmp_git_repo), "testuser", None,
            )
        with pytest.raises(VerificationError, match="signing key"):
            _verify(
                str(path),
                _policy(tmp_path, {"signer_mode": "restricted", "allowed_key_fingerprints": ["SHA256:no"]}),
                str(tmp_git_repo), "testuser", None,
            )


def test_policy_mode_and_fingerprint_scope(
    tmp_path, tmp_git_repo, signer_with_key
):
    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer)
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="required mode"):
            _verify(str(path), _policy(tmp_path, {"require_mode": "ci-gpu"}), str(tmp_git_repo), "testuser", None)
        with pytest.raises(VerificationError, match="fingerprint paths"):
            _verify(str(path), _policy(tmp_path, {"required_fingerprint_paths": ["src"]}), str(tmp_git_repo), "testuser", None)
        with pytest.raises(VerificationError, match="extra paths"):
            _verify(str(path), _policy(tmp_path, {"required_fingerprint_extra_paths": ["generated"]}), str(tmp_git_repo), "testuser", None)
        with pytest.raises(VerificationError, match="exclusions"):
            _verify(str(path), _policy(tmp_path, {"required_fingerprint_excluded_paths": []}), str(tmp_git_repo), "testuser", None)


def test_test_manifest_policy(tmp_path, tmp_git_repo, signer_with_key):
    import subprocess

    manifest = tmp_git_repo / "gpu-tests.txt"
    manifest.write_text("tests/test_add.py::test_add\n")
    subprocess.run(["git", "add", "gpu-tests.txt"], cwd=tmp_git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "manifest"], cwd=tmp_git_repo, check=True, capture_output=True)
    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer)
    with _mock_github_keys(public_key):
        _verify(str(path), _policy(tmp_path, {"required_test_manifest": "gpu-tests.txt"}), str(tmp_git_repo), "testuser", None)
        manifest.write_text("tests/test_add.py::other\n")
        with pytest.raises(VerificationError, match="test manifest"):
            _verify(str(path), _policy(tmp_path, {"required_test_manifest": "gpu-tests.txt", "allow_dirty": True}), str(tmp_git_repo), "testuser", None)


def test_failed_session_and_comparison_check_rejected(
    tmp_path, tmp_git_repo, signer_with_key
):
    signer, public_key = signer_with_key
    path = _make_receipt(
        tmp_path, tmp_git_repo, signer,
        mutate=lambda p: p["session"].__setitem__("outcome", "failed"),
    )
    with _mock_github_keys(public_key), pytest.raises(VerificationError, match="session did not pass"):
        _verify(str(path), None, str(tmp_git_repo), "testuser", None)
    path = _make_receipt(
        tmp_path, tmp_git_repo, signer,
        mutate=lambda p: p["tests"][0].__setitem__(
            "checks", [{"name": "x", "outcome": "failed"}]
        ),
    )
    with _mock_github_keys(public_key), pytest.raises(VerificationError, match="failed comparison"):
        _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_bad_receipt_files_and_schema(tmp_path, tmp_git_repo):
    with pytest.raises(VerificationError, match="cannot read receipt"):
        _verify(str(tmp_path / "missing"), None, str(tmp_git_repo), None, None)
    bad = tmp_path / "bad.json"
    bad.write_text("[]")
    with pytest.raises(VerificationError, match="JSON object"):
        _verify(str(bad), None, str(tmp_git_repo), None, None)
    bad.write_text('{"schema_version": 99}')
    with pytest.raises(VerificationError, match="unknown schema"):
        _verify(str(bad), None, str(tmp_git_repo), None, None)


def test_signature_metadata_and_encoding_errors(
    tmp_path, tmp_git_repo, signer_with_key
):
    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer)
    receipt = json.loads(path.read_text())
    receipt["signature"] = "bad"
    path.write_text(json.dumps(receipt))
    with pytest.raises(VerificationError, match="signature.value"):
        _verify(str(path), None, str(tmp_git_repo), None, None)
    receipt["signature"] = {"value": "%%%"}
    path.write_text(json.dumps(receipt))
    with pytest.raises(VerificationError, match="valid base64"):
        _verify(str(path), None, str(tmp_git_repo), None, None)


def test_verifier_wrapper_reports_failure(tmp_path, tmp_git_repo, capsys):
    assert not verify_receipt(str(tmp_path / "missing"), repo_root=str(tmp_git_repo))
    assert "FAIL" in capsys.readouterr().err


def test_future_and_invalid_age_policy(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key
    future = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = _make_receipt(tmp_path, tmp_git_repo, signer, ended_at=future)
    with _mock_github_keys(public_key), pytest.raises(VerificationError, match="future"):
        _verify(str(path), None, str(tmp_git_repo), "testuser", None)
    path = _make_receipt(tmp_path, tmp_git_repo, signer)
    with _mock_github_keys(public_key), pytest.raises(VerificationError, match="non-negative"):
        _verify(str(path), _policy(tmp_path, {"max_age_days": "bad"}), str(tmp_git_repo), "testuser", None)
    with _mock_github_keys(public_key), pytest.raises(VerificationError, match="non-negative"):
        _verify(str(path), None, str(tmp_git_repo), "testuser", True)


def test_missing_node_manifest_is_reported(tmp_path):
    from pytest_gpu_proof.verify import _load_node_ids

    with pytest.raises(VerificationError, match="cannot read node-id"):
        _load_node_ids(tmp_path / "missing")


def test_signer_metadata_must_match_verifying_key(
    tmp_path, tmp_git_repo, signer_with_key
):
    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer)
    receipt = json.loads(path.read_text())

    receipt["signer"]["github_user"] = ""
    path.write_text(json.dumps(receipt))
    with pytest.raises(VerificationError, match="identity is incomplete"):
        _verify(str(path), None, str(tmp_git_repo), None, None)

    receipt["signer"]["github_user"] = "testuser"
    receipt["signer"]["key_fingerprint"] = "SHA256:wrong"
    path.write_text(json.dumps(receipt))
    with patch("pytest_gpu_proof.verify.find_verifying_github_key", return_value=public_key):
        with pytest.raises(VerificationError, match="key_fingerprint"):
            _verify(str(path), None, str(tmp_git_repo), None, None)

    receipt["signer"]["key_fingerprint"] = signer.key_fingerprint()
    receipt["signer"]["algorithm"] = "rsa-pss-sha256"
    path.write_text(json.dumps(receipt))
    with patch("pytest_gpu_proof.verify.find_verifying_github_key", return_value=public_key):
        with pytest.raises(VerificationError, match="algorithm"):
            _verify(str(path), None, str(tmp_git_repo), None, None)


def test_signer_key_lookup_error_is_clean(
    tmp_path, tmp_git_repo, signer_with_key
):
    from pytest_gpu_proof.signers.base import VerifierError

    signer, _ = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer)
    with patch(
        "pytest_gpu_proof.verify.find_verifying_github_key",
        side_effect=VerifierError("offline"),
    ), pytest.raises(VerificationError, match="offline"):
        _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_legacy_signature_paths(tmp_path, tmp_git_repo, signer_with_key):
    from pytest_gpu_proof.config import GpuProofConfig
    from pytest_gpu_proof.signers.base import VerifierError

    signer, _ = signer_with_key
    os.chdir(tmp_git_repo)
    config = GpuProofConfig(enabled=True, fingerprint_paths=["src", "tests"])
    payload = build_receipt_payload(
        config,
        [{"node_id": "t::x", "outcome": "passed", "checks": []}],
        _utcstamp(), _utcstamp(),
    )
    payload["schema_version"] = "2"
    receipt = finalize_receipt(payload, signer)
    path = tmp_path / "legacy.json"
    write_receipt(receipt, str(path))
    with patch("pytest_gpu_proof.verify.verify_with_github_keys", return_value=True):
        _verify(str(path), None, str(tmp_git_repo), None, None)
    with patch("pytest_gpu_proof.verify.verify_with_github_keys", return_value=False):
        with pytest.raises(VerificationError, match="signature does not match"):
            _verify(str(path), None, str(tmp_git_repo), None, None)
    with patch(
        "pytest_gpu_proof.verify.verify_with_github_keys",
        side_effect=VerifierError("network"),
    ), pytest.raises(VerificationError, match="network"):
        _verify(str(path), None, str(tmp_git_repo), None, None)
    receipt["signature"].pop("signer")
    receipt["repo"]["github_username"] = None
    path.write_text(json.dumps(receipt))
    with pytest.raises(VerificationError, match="determine legacy"):
        _verify(str(path), None, str(tmp_git_repo), None, None)


def test_tree_and_git_failures_are_rejected(
    tmp_path, tmp_git_repo, signer_with_key, monkeypatch
):
    from pytest_gpu_proof.gitutils import GitError

    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer)
    receipt = json.loads(path.read_text())

    receipt["fingerprint"]["algorithm"] = "unknown"
    receipt["signature"] = None
    path.write_text(json.dumps(receipt))
    with pytest.raises(VerificationError, match="unsupported fingerprint"):
        _verify(str(path), None, str(tmp_git_repo), None, None, allow_unsigned=True)

    path = _make_receipt(tmp_path, tmp_git_repo, signer, sign=False)
    receipt = json.loads(path.read_text())
    receipt["fingerprint"]["digest"] = "0" * 64
    path.write_text(json.dumps(receipt))
    with pytest.raises(VerificationError, match="source fingerprint"):
        _verify(str(path), None, str(tmp_git_repo), None, None, allow_unsigned=True)

    path = _make_receipt(tmp_path, tmp_git_repo, signer, sign=False)
    receipt = json.loads(path.read_text())
    receipt["repo"]["commit_sha"] = "1" * 40
    path.write_text(json.dumps(receipt))
    with pytest.raises(VerificationError, match="not the current commit"):
        _verify(str(path), None, str(tmp_git_repo), None, None, allow_unsigned=True)

    path = _make_receipt(tmp_path, tmp_git_repo, signer, sign=False)
    receipt = json.loads(path.read_text())
    receipt["repo"]["dirty"] = True
    path.write_text(json.dumps(receipt))
    with pytest.raises(VerificationError, match="clean recording"):
        _verify(str(path), None, str(tmp_git_repo), None, None, allow_unsigned=True)

    monkeypatch.setattr("pytest_gpu_proof.verify.require_repository", lambda root: (_ for _ in ()).throw(GitError("git broke")))
    with pytest.raises(VerificationError, match="git broke"):
        _verify(str(path), None, str(tmp_git_repo), None, None, allow_unsigned=True)


def test_dirty_query_error_is_rejected(
    tmp_path, tmp_git_repo, signer_with_key, monkeypatch
):
    from pytest_gpu_proof.gitutils import GitError

    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer)
    monkeypatch.setattr("pytest_gpu_proof.verify.is_dirty", lambda *a, **k: (_ for _ in ()).throw(GitError("status broke")))
    with _mock_github_keys(public_key), pytest.raises(VerificationError, match="status broke"):
        _verify(str(path), None, str(tmp_git_repo), "testuser", None)
