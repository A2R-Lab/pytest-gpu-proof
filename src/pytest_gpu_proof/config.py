import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


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
    require_gpu: bool = False


def load_toml_defaults(root: Union[str, Path]) -> Dict[str, Any]:
    """Read the ``[tool.gpu_proof]`` table from ``<root>/pyproject.toml``.

    Returns an empty dict when the file or table is absent or unparseable.
    """
    pyproject = Path(root) / "pyproject.toml"
    if not pyproject.is_file():
        return {}
    try:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return {}
    table = data.get("tool", {}).get("gpu_proof", {})
    return table if isinstance(table, dict) else {}


def load_config(pytest_config) -> GpuProofConfig:
    toml_cfg = load_toml_defaults(pytest_config.rootpath)

    def opt(name, default=None):
        try:
            return pytest_config.getoption(name)
        except ValueError:
            return default

    def resolve(opt_name, toml_key, default):
        """Precedence: CLI flag (when it differs from its built-in default),
        then [tool.gpu_proof] in pyproject.toml, then the built-in default."""
        cli = opt(opt_name, default)
        if cli != default:
            return cli
        toml_val = toml_cfg.get(toml_key)
        if toml_val is not None:
            return toml_val
        return default

    raw_paths = resolve("--gpu-proof-fingerprint-paths", "fingerprint_paths", "src,tests")
    if isinstance(raw_paths, str):
        paths = [p.strip() for p in raw_paths.split(",") if p.strip()]
    else:
        paths = [str(p) for p in raw_paths]

    max_age = toml_cfg.get("max_age_days")
    max_age_days = int(max_age) if max_age is not None else 30

    return GpuProofConfig(
        enabled=bool(opt("--gpu-proof-enable", False)),
        mode=resolve("--gpu-proof-mode", "mode", "local"),
        output=resolve("--gpu-proof-out", "output", "gpu-proof.json"),
        key_path=resolve("--gpu-proof-key", "key_path", None),
        signing_backend=resolve("--gpu-proof-signing-backend", "signing_backend", "ed25519"),
        policy_path=resolve("--gpu-proof-policy", "policy_path", None),
        required_marker=resolve("--gpu-proof-required-marker", "required_marker", "gpu_proof"),
        fail_on_skip=bool(resolve("--gpu-proof-fail-on-skip", "fail_on_skip", False)),
        fingerprint_paths=paths,
        github_username=resolve("--gpu-proof-github-user", "github_username", None),
        max_age_days=max_age_days,
        require_gpu=bool(toml_cfg.get("require_gpu", False)),
    )
