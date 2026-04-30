from typing import Any, Callable, Optional, Tuple


def default_compare(ref: Any, cand: Any) -> None:
    """numpy.allclose for float arrays, exact equality otherwise. Raises AssertionError on mismatch."""
    try:
        import numpy as np

        ref_arr = np.asarray(ref)
        cand_arr = np.asarray(cand)
        if ref_arr.dtype.kind in ("f", "c"):
            if not np.allclose(ref_arr, cand_arr):
                max_diff = float(np.max(np.abs(ref_arr - cand_arr)))
                raise AssertionError(f"Arrays not close: max difference = {max_diff:.6e}")
            return
    except (ImportError, TypeError, ValueError):
        pass

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
