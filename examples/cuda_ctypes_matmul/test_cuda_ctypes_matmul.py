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
def test_ctypes_cuda_matmul_square(gpu_proof_check):
    from cuda_ctypes_matmul import matmul_square

    n = 4
    a = np.arange(n * n, dtype=np.float32) / 7.0
    b = np.flip(np.arange(n * n, dtype=np.float32)).copy() / 5.0

    gpu_proof_check(
        name="cuda_ctypes_matmul_4x4",
        reference=reference_matmul,
        candidate=matmul_square,
        args=(a, b, n),
        compare=compare_allclose,
        metadata={"binding": "ctypes", "shape": "4x4", "dtype": "float32"},
    )

