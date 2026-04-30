import re
import subprocess
from typing import Optional


def _git(*args) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_commit_sha() -> Optional[str]:
    return _git("rev-parse", "HEAD")


def get_branch() -> Optional[str]:
    return _git("rev-parse", "--abbrev-ref", "HEAD")


def is_dirty() -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_remote_url() -> Optional[str]:
    return _git("remote", "get-url", "origin")


def extract_github_username(remote_url: str) -> Optional[str]:
    match = re.search(r"github\.com[:/]([^/]+)/", remote_url)
    return match.group(1) if match else None


def get_github_username() -> Optional[str]:
    url = get_remote_url()
    return extract_github_username(url) if url else None


def get_git_signing_key() -> Optional[str]:
    val = _git("config", "--get", "user.signingKey")
    if not val:
        return None
    import os
    return os.path.expanduser(val)


def get_tracked_files(paths, root="."):
    try:
        result = subprocess.run(
            ["git", "ls-files"] + list(paths),
            capture_output=True,
            text=True,
            check=True,
            cwd=root,
        )
        return sorted(line for line in result.stdout.splitlines() if line)
    except (subprocess.CalledProcessError, FileNotFoundError):
        import os
        files = []
        for path in paths:
            full = os.path.join(root, path)
            if os.path.isfile(full):
                files.append(os.path.relpath(full, root))
            elif os.path.isdir(full):
                for dirpath, _, filenames in os.walk(full):
                    for fn in filenames:
                        fp = os.path.join(dirpath, fn)
                        files.append(os.path.relpath(fp, root))
        return sorted(files)
