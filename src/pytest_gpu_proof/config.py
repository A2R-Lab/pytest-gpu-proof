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
    required_marker: str = "gpu_proof"
    fail_on_skip: bool = False
    fingerprint_paths: List[str] = field(default_factory=lambda: ["."])
    fingerprint_extra_paths: List[str] = field(default_factory=list)
    fingerprint_excluded_paths: List[str] = field(
        default_factory=lambda: ["gpu-proof.json"]
    )
    github_username: Optional[str] = None
    max_age_days: int = 30
    require_gpu: bool = False
    # Sharded emission: a declared shard name + its narrow
    # fingerprint paths (None -> the global fingerprint_paths).
    shard_name: Optional[str] = None
    shard_fingerprint_paths: Optional[List[str]] = None
    shard_fingerprint_extra_paths: Optional[List[str]] = None
    repo_root: str = "."
    invocation_args: List[str] = field(default_factory=list)
    best_effort: bool = False


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
        """Precedence: CLI flag (when explicitly passed), then [tool.gpu_proof]
        in pyproject.toml, then the built-in default. Value-taking options
        register with ``default=None`` so an explicit CLI value that happens to
        equal the built-in default still wins — previously it was silently
        ignored in favor of the toml value."""
        cli = opt(opt_name, None)
        if cli is not None:
            return cli
        toml_val = toml_cfg.get(toml_key)
        if toml_val is not None:
            return toml_val
        return default

    raw_paths = resolve("--gpu-proof-fingerprint-paths", "fingerprint_paths", ".")
    if isinstance(raw_paths, str):
        paths = [p.strip() for p in raw_paths.split(",") if p.strip()]
    else:
        paths = [str(p) for p in raw_paths]

    raw_shard_paths = resolve("--gpu-proof-shard-fingerprint-paths",
                              "shard_fingerprint_paths", None)
    if isinstance(raw_shard_paths, str):
        shard_paths = [p.strip() for p in raw_shard_paths.split(",") if p.strip()]
    elif raw_shard_paths is not None:
        shard_paths = [str(p) for p in raw_shard_paths]
    else:
        shard_paths = None

    def path_list(opt_name, toml_key, default=None):
        raw = resolve(opt_name, toml_key, [] if default is None else default)
        if isinstance(raw, str):
            return [p.strip() for p in raw.split(",") if p.strip()]
        return [str(p) for p in raw]

    max_age = toml_cfg.get("max_age_days")
    max_age_days = int(max_age) if max_age is not None else 30

    return GpuProofConfig(
        enabled=bool(opt("--gpu-proof-enable", False)),
        mode=resolve("--gpu-proof-mode", "mode", "local"),
        output=resolve("--gpu-proof-out", "output", "gpu-proof.json"),
        key_path=resolve("--gpu-proof-key", "key_path", None),
        signing_backend=resolve("--gpu-proof-signing-backend", "signing_backend", "ed25519"),
        required_marker=resolve("--gpu-proof-required-marker", "required_marker", "gpu_proof"),
        # store_true flag: False just means "not passed", so OR with the toml
        # value rather than sentinel-resolving (a CLI flag can only turn it ON).
        fail_on_skip=bool(opt("--gpu-proof-fail-on-skip", False)
                          or toml_cfg.get("fail_on_skip", False)),
        fingerprint_paths=paths,
        fingerprint_extra_paths=path_list(
            "--gpu-proof-fingerprint-extra-paths", "fingerprint_extra_paths"
        ),
        fingerprint_excluded_paths=path_list(
            "--gpu-proof-fingerprint-excluded-paths",
            "fingerprint_excluded_paths",
            ["gpu-proof.json"],
        ),
        github_username=resolve("--gpu-proof-github-user", "github_username", None),
        max_age_days=max_age_days,
        require_gpu=bool(toml_cfg.get("require_gpu", False)),
        shard_name=resolve("--gpu-proof-shard", "shard_name", None),
        shard_fingerprint_paths=shard_paths,
        shard_fingerprint_extra_paths=(
            path_list(
                "--gpu-proof-shard-fingerprint-extra-paths",
                "shard_fingerprint_extra_paths",
            )
            if resolve(
                "--gpu-proof-shard-fingerprint-extra-paths",
                "shard_fingerprint_extra_paths",
                None,
            )
            is not None
            else None
        ),
        repo_root=str(pytest_config.rootpath),
        invocation_args=[str(a) for a in pytest_config.invocation_params.args],
        best_effort=bool(
            opt("--gpu-proof-best-effort", False)
            or toml_cfg.get("best_effort", False)
        ),
    )
