import importlib.util

import numpy as np
import pytest


def reference_matmul(a_flat, b_flat, n):
    a = np.asarray(a_flat, dtype=np.float32).reshape(n, n)
    b = np.asarray(b_flat, dtype=np.float32).reshape(n, n)
    return (a @ b).reshape(n * n).tolist()


def compare_allclose(ref, cand):
    np.testing.assert_allclose(
        np.asarray(cand, dtype=np.float32),
        np.asarray(ref, dtype=np.float32),
        rtol=1e-5,
        atol=1e-5,
    )


@pytest.mark.gpu_required
@pytest.mark.gpu_proof
def test_pybind11_cuda_matmul_square(gpu_proof_check):
    if importlib.util.find_spec("cuda_pybind11_matmul") is None:
        pytest.fail("cuda_pybind11_matmul is not built. Run `cmake -S . -B build && cmake --build build`.")

    import cuda_pybind11_matmul

    n = 4
    a = (np.arange(n * n, dtype=np.float32) / 11.0).tolist()
    b = (np.flip(np.arange(n * n, dtype=np.float32)).copy() / 13.0).tolist()

    gpu_proof_check(
        name="cuda_pybind11_matmul_4x4",
        reference=reference_matmul,
        candidate=cuda_pybind11_matmul.matmul_square,
        args=(a, b, n),
        compare=compare_allclose,
        metadata={"binding": "pybind11", "shape": "4x4", "dtype": "float32"},
    )

