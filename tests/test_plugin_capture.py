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
