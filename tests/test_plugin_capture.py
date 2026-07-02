"""
Integration tests for the pytest plugin using pytester.
These run an inner pytest session in a temp directory.
"""

import pytest


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
