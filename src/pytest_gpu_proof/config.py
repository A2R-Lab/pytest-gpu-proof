from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class GpuProofConfig:
    enabled: bool = False
    mode: str = "local"
    output: str = "gpu-proof.json"
    key_path: Optional[str] = None
    signing_backend: str = "ed25519"
    policy_path: Optional[str] = None
    required_marker: str = "gpu_proof"
    fail_on_skip: bool = False
    fingerprint_paths: List[str] = field(default_factory=lambda: ["src", "tests"])
    github_username: Optional[str] = None
    max_age_days: int = 30


def load_config(pytest_config) -> GpuProofConfig:
    def opt(name, default=None):
        try:
            return pytest_config.getoption(name)
        except ValueError:
            return default

    def ini(name, default=None):
        val = pytest_config.getini(name)
        return val if val else default

    raw_paths = opt("--gpu-proof-fingerprint-paths", "src,tests")
    paths = [p.strip() for p in raw_paths.split(",") if p.strip()]

    return GpuProofConfig(
        enabled=bool(opt("--gpu-proof-enable", False)),
        mode=opt("--gpu-proof-mode", "local"),
        output=opt("--gpu-proof-out", "gpu-proof.json"),
        key_path=opt("--gpu-proof-key", None),
        signing_backend=opt("--gpu-proof-signing-backend", "ed25519"),
        policy_path=opt("--gpu-proof-policy", None),
        required_marker=opt("--gpu-proof-required-marker", "gpu_proof"),
        fail_on_skip=bool(opt("--gpu-proof-fail-on-skip", False)),
        fingerprint_paths=paths,
        github_username=opt("--gpu-proof-github-user", None),
        max_age_days=30,
    )
