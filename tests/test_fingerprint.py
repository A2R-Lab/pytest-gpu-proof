import os
from pathlib import Path

import pytest

from pytest_gpu_proof import fingerprint as fingerprint_module
from pytest_gpu_proof.fingerprint import (
    FingerprintError,
    compute_fingerprint,
    compute_legacy_fingerprint,
    recompute_fingerprint,
)
from pytest_gpu_proof.gitutils import GitError, TrackedEntry


def test_fingerprint_deterministic(tmp_git_repo):
    fp1 = compute_fingerprint(["src", "tests"], root=str(tmp_git_repo))
    fp2 = compute_fingerprint(["src", "tests"], root=str(tmp_git_repo))
    assert fp1["digest"] == fp2["digest"]


def test_fingerprint_changes_on_file_edit(tmp_git_repo):
    import subprocess

    fp_before = compute_fingerprint(["src"], root=str(tmp_git_repo))
    (tmp_git_repo / "src" / "mymodule.py").write_text("def add(a, b): return a + b + 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_git_repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "change"],
        cwd=tmp_git_repo, capture_output=True,
    )
    fp_after = compute_fingerprint(["src"], root=str(tmp_git_repo))
    assert fp_before["digest"] != fp_after["digest"]


def test_fingerprint_structure(tmp_git_repo):
    fp = compute_fingerprint(["src", "tests"], root=str(tmp_git_repo))
    assert fp["algorithm"] == "sha256-manifest-v2"
    assert isinstance(fp["digest"], str)
    assert len(fp["digest"]) == 64
    assert fp["file_count"] > 0
    assert "src" in fp["included_paths"]


def test_fingerprint_empty_paths(tmp_path):
    with pytest.raises(FingerprintError):
        compute_fingerprint(["nonexistent"], root=str(tmp_path))


def test_extra_files_directories_and_symlinks(tmp_git_repo):
    generated = tmp_git_repo / "generated"
    generated.mkdir()
    (generated / "data.bin").write_bytes(b"one")
    (generated / "link").symlink_to("data.bin")
    before = compute_fingerprint([], str(tmp_git_repo), extra_paths=["generated"])
    assert before["file_count"] == 2
    (generated / "data.bin").write_bytes(b"two")
    after = compute_fingerprint([], str(tmp_git_repo), extra_paths=["generated"])
    assert after["digest"] != before["digest"]


def test_tracked_symlink_and_duplicate_scope(tmp_git_repo):
    import subprocess

    (tmp_git_repo / "src" / "alias.py").symlink_to("mymodule.py")
    subprocess.run(["git", "add", "src/alias.py"], cwd=tmp_git_repo, check=True)
    fp = compute_fingerprint(["src", "src", ""], str(tmp_git_repo))
    assert fp["included_paths"] == ["src"]
    assert fp["file_count"] == 2


@pytest.mark.parametrize("path", ["missing.bin", "../escape"])
def test_extra_path_must_exist_inside_repo(tmp_git_repo, path):
    with pytest.raises(FingerprintError):
        compute_fingerprint([], str(tmp_git_repo), extra_paths=[path])


def test_legacy_and_recompute_dispatch(tmp_git_repo):
    legacy = compute_legacy_fingerprint(["src"], str(tmp_git_repo))
    assert legacy["algorithm"] == "sha256"
    assert recompute_fingerprint(legacy, str(tmp_git_repo))["digest"] == legacy["digest"]
    current = compute_fingerprint(["src"], str(tmp_git_repo))
    assert recompute_fingerprint(current, str(tmp_git_repo))["digest"] == current["digest"]


def test_recompute_rejects_invalid_metadata(tmp_git_repo):
    with pytest.raises(FingerprintError, match="included_paths"):
        recompute_fingerprint({"algorithm": "sha256", "included_paths": "src"}, str(tmp_git_repo))
    with pytest.raises(FingerprintError, match="extra_paths"):
        recompute_fingerprint(
            {"algorithm": "sha256-manifest-v2", "included_paths": ["src"], "extra_paths": "x"},
            str(tmp_git_repo),
        )
    with pytest.raises(FingerprintError, match="unsupported"):
        recompute_fingerprint({"algorithm": "md5", "included_paths": ["src"]}, str(tmp_git_repo))


def test_empty_scope_and_overlapping_extra(tmp_git_repo):
    with pytest.raises(FingerprintError, match="scope is empty"):
        compute_fingerprint([], str(tmp_git_repo))
    fp = compute_fingerprint(
        ["src"], str(tmp_git_repo), extra_paths=["src/mymodule.py"]
    )
    assert fp["file_count"] == 1


def test_gitlink_entries_use_checked_out_or_index_commit(tmp_git_repo, monkeypatch):
    sub = tmp_git_repo / "sub"
    sub.mkdir()
    entry = TrackedEntry("sub", "160000", "index-commit")
    monkeypatch.setattr("pytest_gpu_proof.gitutils.get_commit_sha", lambda root: "head-commit")
    # An empty (uninitialized) submodule dir must NOT be rev-parsed: git would
    # walk up and report the parent repo's HEAD. The index commit is truth.
    assert fingerprint_module._regular_entry(entry, tmp_git_repo)["commit"] == "index-commit"
    # An initialized submodule (".git" present) is read from its checkout.
    (sub / ".git").write_text("gitdir: ../.git/modules/sub\n")
    assert fingerprint_module._regular_entry(entry, tmp_git_repo)["commit"] == "head-commit"
    (sub / ".git").unlink()
    sub.rmdir()
    assert fingerprint_module._regular_entry(entry, tmp_git_repo)["commit"] == "index-commit"


def test_fingerprint_wraps_git_and_io_errors(tmp_git_repo, monkeypatch):
    monkeypatch.setattr(
        fingerprint_module,
        "get_tracked_entries",
        lambda *a, **k: (_ for _ in ()).throw(GitError("index broke")),
    )
    with pytest.raises(FingerprintError, match="index broke"):
        compute_fingerprint(["src"], str(tmp_git_repo))

    monkeypatch.undo()
    extra = tmp_git_repo / "generated.bin"
    extra.write_bytes(b"x")
    monkeypatch.setattr(Path, "read_bytes", lambda path: (_ for _ in ()).throw(OSError("read broke")))
    with pytest.raises(FingerprintError, match="cannot read"):
        compute_fingerprint([], str(tmp_git_repo), extra_paths=["generated.bin"])


def test_legacy_skips_non_files_and_wraps_errors(tmp_git_repo, monkeypatch):
    monkeypatch.setattr(fingerprint_module, "get_tracked_files", lambda *a: ["src"])
    fp = compute_legacy_fingerprint(["src"], str(tmp_git_repo))
    assert fp["file_count"] == 0
    monkeypatch.setattr(
        fingerprint_module,
        "get_tracked_files",
        lambda *a: (_ for _ in ()).throw(GitError("legacy index broke")),
    )
    with pytest.raises(FingerprintError, match="legacy index broke"):
        compute_legacy_fingerprint(["src"], str(tmp_git_repo))


def test_tracked_and_legacy_read_errors(tmp_git_repo, monkeypatch):
    missing = TrackedEntry("missing.py", "100644", "object")
    with pytest.raises(FingerprintError, match="cannot read"):
        fingerprint_module._regular_entry(missing, tmp_git_repo)

    monkeypatch.setattr(fingerprint_module, "get_tracked_files", lambda *a: ["src/mymodule.py"])
    monkeypatch.setattr(Path, "read_bytes", lambda path: (_ for _ in ()).throw(OSError("read broke")))
    with pytest.raises(FingerprintError, match="legacy fingerprint"):
        compute_legacy_fingerprint(["src"], str(tmp_git_repo))


def test_tracked_scope_matching_zero_files(tmp_git_repo):
    with pytest.raises(FingerprintError, match="matched zero files"):
        compute_fingerprint(["does-not-exist"], str(tmp_git_repo))


def test_excluded_receipt_is_not_self_referential(tmp_git_repo):
    import subprocess

    receipt = tmp_git_repo / "gpu-proof.json"
    receipt.write_text('{"old": true}\n')
    subprocess.run(["git", "add", "-f", "gpu-proof.json"], cwd=tmp_git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "receipt"], cwd=tmp_git_repo, check=True, capture_output=True)
    before = compute_fingerprint(
        ["."], str(tmp_git_repo), exclude_paths=["gpu-proof.json"]
    )
    receipt.write_text('{"new": true}\n')
    after = compute_fingerprint(
        ["."], str(tmp_git_repo), exclude_paths=["gpu-proof.json"]
    )
    assert after["digest"] == before["digest"]
    assert after["excluded_paths"] == ["gpu-proof.json"]


def test_direct_extra_symlink_binds_link_target(tmp_git_repo):
    (tmp_git_repo / "one").write_text("same")
    (tmp_git_repo / "two").write_text("same")
    link = tmp_git_repo / "generated-link"
    link.symlink_to("one")
    before = compute_fingerprint([], str(tmp_git_repo), extra_paths=["generated-link"])
    link.unlink()
    link.symlink_to("two")
    after = compute_fingerprint([], str(tmp_git_repo), extra_paths=["generated-link"])
    assert after["digest"] != before["digest"]


def test_recompute_rejects_invalid_excluded_paths(tmp_git_repo):
    with pytest.raises(FingerprintError, match="excluded_paths"):
        recompute_fingerprint(
            {
                "algorithm": "sha256-manifest-v2",
                "included_paths": ["src"],
                "extra_paths": [],
                "excluded_paths": "gpu-proof.json",
            },
            str(tmp_git_repo),
        )
