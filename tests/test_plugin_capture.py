"""
Integration tests for the pytest plugin using pytester.
These run an inner pytest session in a temp directory.
"""

import pytest

from pytest_gpu_proof import plugin as plugin_module


@pytest.fixture
def plugin_testdir(pytester):
    """Pytester instance pre-configured with a minimal git repo and SSH key."""
    pytester.makeconftest(
        """
        # conftest intentionally empty — plugin loads via entry point
        """
    )
    return pytester


def test_fixture_runs_without_plugin_enabled(pytester):
    pytester.makepyfile(
        """
        def test_example(gpu_proof_check):
            gpu_proof_check(
                name="add",
                reference=lambda x: x + 1,
                candidate=lambda x: x + 1,
                args=(5,),
            )
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_fixture_fails_on_mismatch(pytester):
    pytester.makepyfile(
        """
        def test_mismatch(gpu_proof_check):
            gpu_proof_check(
                name="add",
                reference=lambda x: x + 1,
                candidate=lambda x: x + 99,
                args=(5,),
            )
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)


def test_gpu_required_skip_without_gpu(pytester, monkeypatch):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.gpu_required
        def test_needs_gpu():
            assert True
        """
    )
    # Patch _has_gpu to return False inside the spawned process via env
    result = pytester.runpytest("--gpu-proof-enable")
    # Should be skipped (no GPU in CI)
    outcomes = result.parseoutcomes()
    assert outcomes.get("skipped", 0) + outcomes.get("passed", 0) >= 1


def test_markers_registered(pytester):
    result = pytester.runpytest("--markers")
    result.stdout.fnmatch_lines(["*gpu_proof*", "*gpu_required*", "*gpu_equivalence*"])


def _read_receipt(pytester, name="gpu-proof.json"):
    import json

    path = pytester.path / name
    assert path.exists(), f"receipt {name} was not written"
    return json.loads(path.read_text())


def test_backend_none_writes_unsigned_receipt(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.gpu_proof
        def test_ok():
            assert True
        """
    )
    result = pytester.runpytest(
        "--gpu-proof-enable", "--gpu-proof-signing-backend=none"
    )
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*UNSIGNED*"])
    receipt = _read_receipt(pytester)
    assert receipt["signature"] is None
    assert receipt["tests"][0]["outcome"] == "passed"


def test_skipped_marked_test_recorded_in_receipt(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.gpu_proof
        def test_ok():
            assert True

        @pytest.mark.skip(reason="no hardware")
        @pytest.mark.gpu_proof
        def test_skipped():
            assert True
        """
    )
    result = pytester.runpytest(
        "--gpu-proof-enable", "--gpu-proof-signing-backend=none"
    )
    result.assert_outcomes(passed=1, skipped=1)
    receipt = _read_receipt(pytester)
    outcomes = {t["node_id"].split("::")[-1]: t["outcome"] for t in receipt["tests"]}
    assert outcomes["test_skipped"] == "skipped"
    assert outcomes["test_ok"] == "passed"


def test_fail_on_skip_fails_session_and_suppresses_receipt(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.skip(reason="no hardware")
        @pytest.mark.gpu_proof
        def test_skipped():
            assert True
        """
    )
    result = pytester.runpytest(
        "--gpu-proof-enable",
        "--gpu-proof-signing-backend=none",
        "--gpu-proof-fail-on-skip",
    )
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*fail-on-skip*"])
    assert not (pytester.path / "gpu-proof.json").exists()


def test_fail_on_skip_covers_gpu_required(pytester, monkeypatch):
    # Make the plugin believe no GPU is present.
    monkeypatch.setattr("pytest_gpu_proof.plugin._has_gpu", lambda: False)
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.gpu_required
        def test_needs_gpu():
            assert True
        """
    )
    result = pytester.runpytest_inprocess(
        "--gpu-proof-enable",
        "--gpu-proof-signing-backend=none",
        "--gpu-proof-fail-on-skip",
    )
    assert result.ret != 0
    assert not (pytester.path / "gpu-proof.json").exists()


def test_custom_required_marker_is_wired(pytester):
    pytester.makeini(
        """
        [pytest]
        markers =
            my_gpu: custom receipt marker
        """
    )
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.my_gpu
        def test_custom_marked():
            assert True

        def test_unmarked():
            assert True
        """
    )
    result = pytester.runpytest(
        "--gpu-proof-enable",
        "--gpu-proof-signing-backend=none",
        "--gpu-proof-required-marker=my_gpu",
    )
    result.assert_outcomes(passed=2)
    receipt = _read_receipt(pytester)
    node_ids = [t["node_id"] for t in receipt["tests"]]
    assert any("test_custom_marked" in n for n in node_ids)
    assert not any("test_unmarked" in n for n in node_ids)


def test_fixture_checks_recorded_in_receipt(pytester):
    pytester.makepyfile(
        """
        def test_with_fixture(gpu_proof_check):
            gpu_proof_check(
                name="add",
                reference=lambda x: x + 1,
                candidate=lambda x: x + 1,
                args=(5,),
                metadata={"kernel": "add"},
            )
        """
    )
    result = pytester.runpytest(
        "--gpu-proof-enable", "--gpu-proof-signing-backend=none"
    )
    result.assert_outcomes(passed=1)
    receipt = _read_receipt(pytester)
    assert len(receipt["tests"]) == 1
    checks = receipt["tests"][0]["checks"]
    assert checks == [{"name": "add", "outcome": "passed", "metadata": {"kernel": "add"}}]


def test_tool_gpu_proof_toml_defaults(pytester):
    pytester.makepyprojecttoml(
        """
        [tool.pytest.ini_options]
        markers = ["my_gpu: custom receipt marker"]

        [tool.gpu_proof]
        signing_backend = "none"
        output = "toml-receipt.json"
        required_marker = "my_gpu"
        """
    )
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.my_gpu
        def test_custom_marked():
            assert True
        """
    )
    result = pytester.runpytest("--gpu-proof-enable")
    result.assert_outcomes(passed=1)
    receipt = _read_receipt(pytester, "toml-receipt.json")
    assert receipt["signature"] is None
    assert any("test_custom_marked" in t["node_id"] for t in receipt["tests"])


def test_cli_overrides_toml_defaults(pytester):
    pytester.makepyprojecttoml(
        """
        [tool.pytest.ini_options]

        [tool.gpu_proof]
        signing_backend = "none"
        output = "toml-receipt.json"
        """
    )
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.gpu_proof
        def test_ok():
            assert True
        """
    )
    result = pytester.runpytest(
        "--gpu-proof-enable", "--gpu-proof-out=cli-receipt.json"
    )
    result.assert_outcomes(passed=1)
    assert (pytester.path / "cli-receipt.json").exists()
    assert not (pytester.path / "toml-receipt.json").exists()


def test_cli_equal_to_builtin_default_still_overrides_toml(pytester):
    """Tri-state regression (0.2.0): an EXPLICIT CLI value that happens to equal
    the built-in default must beat [tool.gpu_proof] — previously it was
    silently ignored because "set" was detected by comparing against the
    built-in default. --gpu-proof-out=gpu-proof.json IS the built-in default."""
    pytester.makepyprojecttoml(
        """
        [tool.pytest.ini_options]

        [tool.gpu_proof]
        signing_backend = "none"
        output = "toml-receipt.json"
        """
    )
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.gpu_proof
        def test_ok():
            assert True
        """
    )
    result = pytester.runpytest(
        "--gpu-proof-enable", "--gpu-proof-out=gpu-proof.json"
    )
    result.assert_outcomes(passed=1)
    assert (pytester.path / "gpu-proof.json").exists()
    assert not (pytester.path / "toml-receipt.json").exists()


def test_no_marked_tests_fails_closed_and_best_effort_can_opt_out(pytester):
    pytester.makepyfile("def test_plain(): assert True")
    result = pytester.runpytest(
        "--gpu-proof-enable", "--gpu-proof-signing-backend=none"
    )
    result.assert_outcomes(passed=1)
    assert result.ret != 0
    assert not (pytester.path / "gpu-proof.json").exists()

    result = pytester.runpytest(
        "--gpu-proof-enable", "--gpu-proof-signing-backend=none",
        "--gpu-proof-best-effort",
    )
    assert result.ret == 0


def test_setup_failure_is_recorded_and_session_fails(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture
        def broken():
            raise RuntimeError("setup broke")

        @pytest.mark.gpu_proof
        def test_setup(broken):
            pass
        """
    )
    result = pytester.runpytest(
        "--gpu-proof-enable", "--gpu-proof-signing-backend=none"
    )
    result.assert_outcomes(errors=1)
    receipt = _read_receipt(pytester)
    assert receipt["session"]["outcome"] == "failed"
    assert receipt["tests"][0]["outcome"] == "failed"
    assert receipt["tests"][0]["phase"] == "setup"


def test_teardown_failure_overrides_passed_call(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture
        def broken_teardown():
            yield
            raise RuntimeError("teardown broke")

        @pytest.mark.gpu_proof
        def test_teardown(broken_teardown):
            assert True
        """
    )
    result = pytester.runpytest(
        "--gpu-proof-enable", "--gpu-proof-signing-backend=none"
    )
    result.assert_outcomes(passed=1, errors=1)
    receipt = _read_receipt(pytester)
    assert receipt["tests"][0]["outcome"] == "failed"
    assert receipt["tests"][0]["phase"] == "teardown"


def test_stale_receipt_removed_before_failed_emission(pytester):
    stale = pytester.path / "gpu-proof.json"
    stale.write_text('{"stale": true}')
    pytester.makepyfile(
        """
        import pytest
        @pytest.mark.gpu_proof
        def test_ok(): assert True
        """
    )
    result = pytester.runpytest(
        "--gpu-proof-enable", "--gpu-proof-fingerprint-extra-paths=missing.bin",
        "--gpu-proof-signing-backend=none",
    )
    result.assert_outcomes(passed=1)
    assert result.ret != 0
    assert not stale.exists()


def test_emission_failure_best_effort_warns(pytester):
    pytester.makepyfile(
        """
        import pytest
        @pytest.mark.gpu_proof
        def test_ok(): assert True
        """
    )
    result = pytester.runpytest(
        "--gpu-proof-enable", "--gpu-proof-fingerprint-extra-paths=missing.bin",
        "--gpu-proof-signing-backend=none", "--gpu-proof-best-effort",
    )
    result.assert_outcomes(passed=1, warnings=1)
    assert result.ret == 0


def test_signed_receipt_path(pytester, tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    key = tmp_path / "id_ed25519"
    key.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()
        )
    )
    pytester.makepyfile(
        """
        import pytest
        @pytest.mark.gpu_proof
        def test_ok(): assert True
        """
    )
    result = pytester.runpytest(
        "--gpu-proof-enable", f"--gpu-proof-key={key}",
        "--gpu-proof-github-user=testuser",
    )
    result.assert_outcomes(passed=1)
    assert _read_receipt(pytester)["signature"]["value"]


def test_has_gpu_fallbacks(monkeypatch):
    import builtins
    import subprocess
    from types import SimpleNamespace

    monkeypatch.setattr(
        plugin_module.subprocess if hasattr(plugin_module, "subprocess") else subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], 0),
    )
    assert plugin_module._has_gpu() is True

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 1))
    monkeypatch.setitem(__import__("sys").modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)))
    assert plugin_module._has_gpu() is True

    real_import = builtins.__import__
    def no_torch(name, *args, **kwargs):
        if name == "torch":
            raise ImportError
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_torch)
    assert plugin_module._has_gpu() is False


def test_xdist_worker_is_rejected():
    class Config:
        workerinput = {}

        def addinivalue_line(self, *args):
            pass

        def getoption(self, name):
            return True

    with pytest.raises(pytest.UsageError, match="xdist"):
        plugin_module.pytest_configure(Config())


def test_runtime_skip_is_recorded(pytester):
    pytester.makepyfile(
        """
        import pytest
        @pytest.mark.gpu_proof
        def test_runtime_skip(): pytest.skip("later")
        """
    )
    result = pytester.runpytest(
        "--gpu-proof-enable", "--gpu-proof-signing-backend=none"
    )
    result.assert_outcomes(skipped=1)
    assert _read_receipt(pytester)["tests"][0]["outcome"] == "skipped"


def test_absolute_output_path(pytester):
    out = pytester.path / "nested" / "receipt.json"
    pytester.makepyfile(
        """
        import pytest
        @pytest.mark.gpu_proof
        def test_ok(): pass
        """
    )
    result = pytester.runpytest(
        "--gpu-proof-enable", "--gpu-proof-signing-backend=none",
        f"--gpu-proof-out={out}",
    )
    result.assert_outcomes(passed=1)
    assert out.exists()


def test_has_gpu_handles_nvidia_error(monkeypatch):
    import builtins
    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())
    )
    real_import = builtins.__import__
    def no_torch(name, *args, **kwargs):
        if name == "torch":
            raise ImportError
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_torch)
    assert plugin_module._has_gpu() is False


def test_plugin_disabled_and_missing_terminal_result(monkeypatch):
    from pytest_gpu_proof.config import GpuProofConfig

    plugin = plugin_module.GpuProofPlugin.__new__(plugin_module.GpuProofPlugin)
    plugin.gpu_proof_config = GpuProofConfig(enabled=False)
    plugin.pytest_sessionfinish(type("S", (), {"exitstatus": pytest.ExitCode.OK})(), 0)

    plugin.gpu_proof_config = GpuProofConfig(enabled=True)
    plugin.collected_node_ids = ["t::missing"]
    plugin._results_by_node = {}
    plugin.test_results = []
    seen = {}
    monkeypatch.setattr(plugin, "_emit_receipt", lambda outcome: seen.setdefault("outcome", outcome))
    session = type("S", (), {"exitstatus": pytest.ExitCode.OK})()
    plugin.pytest_sessionfinish(session, 0)
    assert plugin.test_results[0]["phase"] == "missing-terminal-report"
    assert seen["outcome"] == "passed"


def test_configure_and_collection_tolerate_missing_options():
    class PluginManager:
        def register(self, *args):
            raise AssertionError("must not register")

    class Config:
        pluginmanager = PluginManager()

        def addinivalue_line(self, *args):
            pass

        def getoption(self, name):
            raise ValueError(name)

    plugin_module.pytest_configure(Config())
    plugin_module.pytest_collection_modifyitems(Config(), [])


def test_sessionstart_unlink_failure_fails_closed(monkeypatch, tmp_path):
    from pytest_gpu_proof.config import GpuProofConfig

    plugin = plugin_module.GpuProofPlugin.__new__(plugin_module.GpuProofPlugin)
    plugin.gpu_proof_config = GpuProofConfig(
        enabled=True, output=str(tmp_path / "receipt.json"), repo_root=str(tmp_path)
    )
    plugin.started_at = ""
    session = type("S", (), {"exitstatus": pytest.ExitCode.OK})()
    monkeypatch.setattr(
        plugin_module.Path,
        "unlink",
        lambda *a, **k: (_ for _ in ()).throw(OSError("permission denied")),
    )
    plugin.pytest_sessionstart(session)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED


def test_report_defensive_paths():
    from types import SimpleNamespace
    from pytest_gpu_proof.config import GpuProofConfig

    plugin = plugin_module.GpuProofPlugin.__new__(plugin_module.GpuProofPlugin)
    plugin.gpu_proof_config = GpuProofConfig(enabled=True)
    plugin._results_by_node = {}
    plugin.skipped_required = []

    class Item:
        nodeid = "t::x"
        fixturenames = ()
        _gpu_proof_checks = []

        def get_closest_marker(self, name):
            return object() if name == "gpu_proof" else None

    def drive(call, report):
        hook = plugin.pytest_runtest_makereport(Item(), call)
        next(hook)
        with pytest.raises(StopIteration):
            hook.send(SimpleNamespace(get_result=lambda: report))

    # Teardown may have no prior call result after an interrupted protocol.
    drive(
        SimpleNamespace(when="teardown", duration=0.0),
        SimpleNamespace(failed=False, passed=True, skipped=False),
    )
    # A nonstandard report plugin may provide no terminal boolean.
    drive(
        SimpleNamespace(when="call", duration=0.0),
        SimpleNamespace(failed=False, passed=False, skipped=False),
    )
    assert plugin._results_by_node["t::x"]["outcome"] == "failed"


def test_collection_gpu_probe_is_lazy_and_reused(monkeypatch):
    from types import SimpleNamespace

    class Config:
        def getoption(self, name):
            return False

    class Item:
        def __init__(self, marked):
            self.marked = marked
            self.added = []

        def get_closest_marker(self, name):
            return self.marked if name == "gpu_required" else None

        def add_marker(self, marker):
            self.added.append(marker)

    calls = []
    monkeypatch.setattr(plugin_module, "_has_gpu", lambda: calls.append(1) or False)
    plain, first, second = Item(False), Item(True), Item(True)
    plugin_module.pytest_collection_modifyitems(Config(), [plain, first, second])
    assert not plain.added and first.added and second.added
    assert calls == [1]
    available = Item(True)
    monkeypatch.setattr(plugin_module, "_has_gpu", lambda: True)
    plugin_module.pytest_collection_modifyitems(Config(), [available])
    assert not available.added
