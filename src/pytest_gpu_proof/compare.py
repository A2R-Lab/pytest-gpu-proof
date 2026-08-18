from typing import Any, Callable, Optional, Tuple


def default_compare(ref: Any, cand: Any) -> None:
    """Shape-safe allclose for floats and exact equality for other arrays."""
    try:
        import numpy as np

    except ImportError:
        np = None
    if np is not None:
        try:
            ref_arr = np.asarray(ref)
            cand_arr = np.asarray(cand)
        except (TypeError, ValueError):
            ref_arr = cand_arr = None
        if ref_arr is not None and cand_arr is not None:
            if ref_arr.shape != cand_arr.shape:
                raise AssertionError(
                    f"Shapes differ: reference={ref_arr.shape}, candidate={cand_arr.shape}"
                )
            if ref_arr.dtype.kind in ("f", "c") or cand_arr.dtype.kind in ("f", "c"):
                if not np.allclose(ref_arr, cand_arr, equal_nan=True):
                    max_diff = float(np.nanmax(np.abs(ref_arr - cand_arr)))
                    raise AssertionError(f"Arrays not close: max difference = {max_diff:.6e}")
                return
            if not np.array_equal(ref_arr, cand_arr):
                raise AssertionError("Arrays are not exactly equal")
            return

    if ref != cand:
        raise AssertionError(f"Values not equal: {ref!r} != {cand!r}")


def run_comparison(
    reference: Callable,
    candidate: Callable,
    args: tuple,
    kwargs: dict,
    compare_fn: Optional[Callable] = None,
) -> Tuple[str, Any, Any, Optional[str]]:
    """
    Call reference and candidate with the same args, then compare outputs.
    Returns (outcome, ref_result, cand_result, error_message).
    """
    try:
        ref_result = reference(*args, **kwargs)
    except Exception as e:
        return "error", None, None, f"Reference raised: {e}"

    try:
        cand_result = candidate(*args, **kwargs)
    except Exception as e:
        return "error", ref_result, None, f"Candidate raised: {e}"

    compare = compare_fn if compare_fn is not None else default_compare
    try:
        compare(ref_result, cand_result)
        return "passed", ref_result, cand_result, None
    except AssertionError as e:
        return "failed", ref_result, cand_result, str(e)
    except Exception as e:
        return (
            "error",
            ref_result,
            cand_result,
            f"Comparator raised {type(e).__name__}: {e}",
        )
