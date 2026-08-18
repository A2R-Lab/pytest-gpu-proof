import builtins

import pytest

np = pytest.importorskip("numpy")

from pytest_gpu_proof.compare import default_compare, run_comparison


def test_default_compare_equal_lists():
    default_compare([1.0, 2.0], [1.0, 2.0])  # should not raise


def test_default_compare_equal_scalars():
    default_compare(42, 42)


def test_default_compare_unequal_scalars():
    with pytest.raises(AssertionError):
        default_compare(1, 2)


def test_default_compare_numpy_integer_arrays():
    default_compare(np.array([1, 2]), np.array([1, 2]))
    with pytest.raises(AssertionError, match="not exactly equal"):
        default_compare(np.array([1, 2]), np.array([1, 3]))


def test_default_compare_numpy_float_arrays_and_nan():
    default_compare(np.array([1.0, np.nan]), np.array([1.0, np.nan]))
    with pytest.raises(AssertionError, match="max diff"):
        default_compare(np.array([1.0, 2.0]), np.array([1.0, 3.0]))


def test_default_compare_numpy_shape_mismatch():
    with pytest.raises(AssertionError, match="Shapes differ"):
        default_compare(np.array([1.0, 2.0]), np.array([[1.0, 2.0]]))


def test_default_compare_falls_back_without_numpy(monkeypatch):
    real_import = builtins.__import__

    def without_numpy(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_numpy)
    default_compare("same", "same")
    with pytest.raises(AssertionError, match="Values not equal"):
        default_compare("left", "right")


def test_default_compare_falls_back_for_non_array_values(monkeypatch):
    def reject(_value):
        raise TypeError("cannot convert")

    monkeypatch.setattr(np, "asarray", reject)
    default_compare("same", "same")


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


def test_run_comparison_custom_compare_error():
    def broken_compare(_reference, _candidate):
        raise ValueError("comparison broke")

    outcome, _, _, error = run_comparison(
        lambda: 1, lambda: 1, (), {}, compare_fn=broken_compare
    )
    assert outcome == "error"
    assert "Comparator raised ValueError" in error


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
