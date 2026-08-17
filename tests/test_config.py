from types import SimpleNamespace

from pytest_gpu_proof.config import GpuProofConfig, load_config, load_toml_defaults


class FakeConfig:
    def __init__(self, rootpath, options=None, args=("-q",)):
        self.rootpath = rootpath
        self.options = options or {}
        self.invocation_params = SimpleNamespace(args=args)

    def getoption(self, name):
        if name not in self.options:
            raise ValueError(name)
        return self.options[name]


def test_dataclass_defaults_are_safe():
    first = GpuProofConfig()
    second = GpuProofConfig()
    first.fingerprint_paths.append("x")
    assert second.fingerprint_paths == ["."]
    assert second.best_effort is False


def test_load_toml_defaults_absent_invalid_and_non_table(tmp_path):
    assert load_toml_defaults(tmp_path) == {}
    (tmp_path / "pyproject.toml").write_text("not = [valid")
    assert load_toml_defaults(tmp_path) == {}
    (tmp_path / "pyproject.toml").write_text('[tool]\ngpu_proof = "bad"\n')
    assert load_toml_defaults(tmp_path) == {}


def test_load_config_toml_lists_and_cli_precedence(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.gpu_proof]
mode = "ci"
output = "from-toml.json"
fingerprint_paths = ["src", "tests"]
fingerprint_extra_paths = "generated/a,generated/b"
shard_name = "core"
shard_fingerprint_paths = ["src"]
shard_fingerprint_extra_paths = ["generated/a"]
fail_on_skip = true
best_effort = true
max_age_days = 7
require_gpu = true
"""
    )
    config = load_config(
        FakeConfig(
            tmp_path,
            {
                "--gpu-proof-enable": True,
                "--gpu-proof-mode": "local",
                "--gpu-proof-out": None,
                "--gpu-proof-fingerprint-paths": "src, docs,",
                "--gpu-proof-shard-fingerprint-paths": None,
            },
            args=("tests", "-q"),
        )
    )
    assert config.enabled is True
    assert config.mode == "local"
    assert config.output == "from-toml.json"
    assert config.fingerprint_paths == ["src", "docs"]
    assert config.fingerprint_extra_paths == ["generated/a", "generated/b"]
    assert config.fingerprint_excluded_paths == ["gpu-proof.json"]
    assert config.shard_fingerprint_paths == ["src"]
    assert config.shard_fingerprint_extra_paths == ["generated/a"]
    assert config.fail_on_skip and config.best_effort and config.require_gpu
    assert config.max_age_days == 7
    assert config.invocation_args == ["tests", "-q"]


def test_load_config_defaults_and_string_shard_paths(tmp_path):
    config = load_config(
        FakeConfig(
            tmp_path,
            {
                "--gpu-proof-fingerprint-paths": None,
                "--gpu-proof-shard-fingerprint-paths": "src,tests",
                "--gpu-proof-fail-on-skip": False,
                "--gpu-proof-best-effort": False,
            },
        )
    )
    assert config.fingerprint_paths == ["."]
    assert config.shard_fingerprint_paths == ["src", "tests"]
    assert config.shard_name is None


def test_load_config_list_fingerprint_paths(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.gpu_proof]\nfingerprint_paths = ["src", 7]\n'
    )
    config = load_config(FakeConfig(tmp_path))
    assert config.fingerprint_paths == ["src", "7"]


def test_explicit_empty_fingerprint_exclusions(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.gpu_proof]\nfingerprint_excluded_paths = []\n"
    )
    assert load_config(FakeConfig(tmp_path)).fingerprint_excluded_paths == []
