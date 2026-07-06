"""gitutils.is_dirty: submodule-aware dirty detection.

The dirty flag guards receipt honesty (allow_dirty policy), so its semantics
matter: anything that can change the attested code must count as dirty, and
nothing else. Submodules are the subtle case — the parent's gitlink pins their
content, so untracked files INSIDE a submodule (build deps, caches) are noise,
while a moved pin is a real change.
"""

import subprocess

from pytest_gpu_proof.gitutils import is_dirty


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
    (parent / "sub" / "f.txt").write_text("changed")
    _commit_all(parent / "sub", "advance pin")
    assert is_dirty() is True
