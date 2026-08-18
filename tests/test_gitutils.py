"""gitutils.is_dirty: submodule-aware dirty detection.

The dirty flag guards receipt honesty (allow_dirty policy), so its semantics
matter: anything that can change the attested code must count as dirty, and
nothing else. Submodules are the subtle case — the parent's gitlink pins their
content, so untracked files INSIDE a submodule (build deps, caches) are noise,
while a moved pin is a real change.
"""

import subprocess

import pytest

from pytest_gpu_proof import gitutils
from pytest_gpu_proof.gitutils import GitError, is_dirty


def _git(*args, cwd):
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path):
    path.mkdir(exist_ok=True)
    _git("init", "-q", cwd=path)
    _git("config", "user.email", "t@t", cwd=path)
    _git("config", "user.name", "t", cwd=path)


def _commit_all(path, msg="c"):
    _git("add", "-A", cwd=path)
    _git("commit", "-q", "-m", msg, cwd=path)


def test_is_dirty_submodule_semantics(tmp_path, monkeypatch):
    child = tmp_path / "child"
    _init_repo(child)
    (child / "f.txt").write_text("x")
    _commit_all(child)

    parent = tmp_path / "parent"
    _init_repo(parent)
    (parent / "code.py").write_text("print('hi')")
    _commit_all(parent)
    _git("submodule", "add", "-q", str(child), "sub", cwd=parent)
    _commit_all(parent, "add submodule")

    monkeypatch.chdir(parent)
    assert is_dirty() is False, "freshly committed tree must be clean"

    # Untracked file INSIDE the submodule: pinned content unchanged -> clean.
    (parent / "sub" / "build_artifact.o").write_text("junk")
    assert is_dirty() is False, "untracked submodule content cannot change the attested code"

    # Untracked file in the PARENT repo: dirty.
    (parent / "stray.txt").write_text("y")
    assert is_dirty() is True
    (parent / "stray.txt").unlink()
    assert is_dirty() is False

    # A moved submodule PIN is a real change: dirty.
    # (the submodule clone needs its own identity — CI runners have no global one)
    _git("config", "user.email", "t@t", cwd=parent / "sub")
    _git("config", "user.name", "t", cwd=parent / "sub")
    (parent / "sub" / "f.txt").write_text("changed")
    _commit_all(parent / "sub", "advance pin")
    assert is_dirty() is True


def test_git_metadata_helpers(tmp_git_repo):
    assert gitutils.get_commit_sha(str(tmp_git_repo))
    assert gitutils.get_branch(str(tmp_git_repo)) == "master"
    assert gitutils.get_remote_url(str(tmp_git_repo)).endswith("testuser/example.git")
    assert gitutils.get_github_username(str(tmp_git_repo)) == "testuser"
    assert gitutils.extract_github_username("https://example.com/nope") is None
    assert gitutils.get_tracked_files(["src"], str(tmp_git_repo)) == ["src/mymodule.py"]
    gitutils.require_repository(str(tmp_git_repo))


def test_git_failures_are_fail_closed(tmp_path, monkeypatch):
    assert gitutils.get_commit_sha(str(tmp_path)) is None
    assert gitutils.is_dirty(str(tmp_path)) is False
    with pytest.raises(GitError, match="not inside"):
        gitutils.require_repository(str(tmp_path))
    with pytest.raises(GitError, match="git rev-parse"):
        gitutils.get_commit_sha(str(tmp_path), required=True)
    with pytest.raises(GitError, match="could not inspect"):
        gitutils.is_dirty(str(tmp_path), required=True)
    with pytest.raises(GitError, match="empty"):
        gitutils.get_tracked_entries([], str(tmp_path))


def test_gh_login_and_signing_key(monkeypatch, tmp_git_repo):
    monkeypatch.setattr(
        gitutils.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="alice\n", stderr=""),
    )
    assert gitutils.get_gh_cli_login() == "alice"

    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(gitutils.subprocess, "run", missing)
    assert gitutils.get_gh_cli_login() is None


def test_unmerged_index_entry_rejected(tmp_git_repo, monkeypatch):
    output = b"100644 deadbeef 1\tconflicted.py\0"
    monkeypatch.setattr(
        gitutils.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=output, stderr=b""),
    )
    with pytest.raises(GitError, match="unmerged"):
        gitutils.get_tracked_entries(["."], str(tmp_git_repo))


def test_git_signing_key(tmp_git_repo):
    _git("config", "user.signingKey", "~/keys/id_ed25519", cwd=tmp_git_repo)
    assert gitutils.get_git_signing_key(str(tmp_git_repo)).endswith("keys/id_ed25519")


def test_dirty_check_can_ignore_only_the_receipt_artifact(tmp_git_repo):
    receipt = tmp_git_repo / "gpu-proof.json"
    receipt.write_text("old\n")
    _git("add", "-f", "gpu-proof.json", cwd=tmp_git_repo)
    _git("commit", "-m", "receipt", cwd=tmp_git_repo)
    receipt.write_text("new\n")
    assert is_dirty(str(tmp_git_repo)) is True
    assert is_dirty(
        str(tmp_git_repo), exclude_paths=["gpu-proof.json"]
    ) is False
    (tmp_git_repo / "src" / "mymodule.py").write_text("changed\n")
    assert is_dirty(
        str(tmp_git_repo), exclude_paths=["gpu-proof.json"]
    ) is True


def test_dirty_rename_parsing(tmp_git_repo):
    _git("mv", "src/mymodule.py", "src/renamed.py", cwd=tmp_git_repo)
    assert is_dirty(
        str(tmp_git_repo), exclude_paths=["src/mymodule.py", "src/renamed.py"]
    ) is False
    assert is_dirty(
        str(tmp_git_repo), exclude_paths=["src/renamed.py"]
    ) is True


def test_dirty_parser_handles_truncated_rename(monkeypatch):
    monkeypatch.setattr(
        gitutils.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=b"R  new.py\0", stderr=b""),
    )
    assert is_dirty(".", exclude_paths=["new.py"]) is False
