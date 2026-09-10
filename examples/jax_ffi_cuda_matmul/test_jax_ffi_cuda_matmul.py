import numpy as np
import pytest


def reference_matmul(a, b):
    return np.asarray(a, dtype=np.float32) @ np.asarray(b, dtype=np.float32)


def compare_allclose(ref, cand):
    np.testing.assert_allclose(
        np.asarray(cand, dtype=np.float32),
        np.asarray(ref, dtype=np.float32),
        rtol=1e-5,
        atol=1e-5,
    )


def jax_candidate(a, b):
    from jax_ffi_matmul import matmul_square

    return np.asarray(matmul_square(a, b).block_until_ready(), dtype=np.float32)


@pytest.mark.gpu_required
@pytest.mark.gpu_proof
def test_jax_ffi_cuda_matmul_square(gpu_proof_check):
    jax = pytest.importorskip("jax")
    pytest.importorskip("jaxlib")

    if not any(device.platform == "gpu" for device in jax.devices()):
        pytest.skip("JAX does not see a GPU backend")

    n = 4
    a = (np.arange(n * n, dtype=np.float32) / 23.0).reshape(n, n)
    b = (np.flip(np.arange(n * n, dtype=np.float32)).copy() / 29.0).reshape(n, n)

    gpu_proof_check(
        name="jax_ffi_cuda_matmul_4x4",
        reference=reference_matmul,
        candidate=jax_candidate,
        args=(a, b),
        compare=compare_allclose,
        metadata={"binding": "jax.ffi", "shape": "4x4", "dtype": "float32"},
    )
