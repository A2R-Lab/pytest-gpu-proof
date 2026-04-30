import pytest

from pytest_gpu_proof.compare import default_compare, run_comparison


def test_default_compare_equal_lists():
    default_compare([1.0, 2.0], [1.0, 2.0])  # should not raise


def test_default_compare_equal_scalars():
    default_compare(42, 42)


def test_default_compare_unequal_scalars():
    with pytest.raises(AssertionError):
        default_compare(1, 2)


def test_run_comparison_passed():
    outcome, ref, cand, err = run_comparison(
        lambda x: x * 2,
        lambda x: x + x,
        (5,),
        {},
    )
    assert outcome == "passed"
    assert err is None


def test_run_comparison_failed():
    outcome, ref, cand, err = run_comparison(
        lambda x: x,
        lambda x: x + 1,
        (5,),
        {},
    )
    assert outcome == "failed"
    assert err is not None


def test_run_comparison_custom_compare():
    def strict(a, b):
        assert a == b, f"{a} != {b}"

    outcome, *_ = run_comparison(lambda: 1, lambda: 1, (), {}, compare_fn=strict)
    assert outcome == "passed"


def test_run_comparison_reference_raises():
    def boom(*args):
        raise RuntimeError("boom")

    outcome, _, _, err = run_comparison(boom, lambda: 1, (), {})
    assert outcome == "error"
    assert "Reference raised" in err


def test_run_comparison_candidate_raises():
    def boom(*args):
        raise RuntimeError("boom")

    outcome, _, _, err = run_comparison(lambda: 1, boom, (), {})
    assert outcome == "error"
    assert "Candidate raised" in err
