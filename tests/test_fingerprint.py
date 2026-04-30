import os

import pytest

from pytest_gpu_proof.fingerprint import compute_fingerprint


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
    assert fp["algorithm"] == "sha256"
    assert isinstance(fp["digest"], str)
    assert len(fp["digest"]) == 64
    assert fp["file_count"] > 0
    assert "src" in fp["included_paths"]


def test_fingerprint_empty_paths(tmp_path):
    fp = compute_fingerprint(["nonexistent"], root=str(tmp_path))
    assert fp["file_count"] == 0
    assert isinstance(fp["digest"], str)
