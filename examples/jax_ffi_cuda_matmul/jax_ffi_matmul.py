import ctypes
from pathlib import Path

import jax
import jax.numpy as jnp
import numpy as np


_TARGET = "pytest_gpu_proof_matmul_square_f32"
_LIB_PATH = Path(__file__).with_name("libjax_ffi_cuda_matmul.so")
_REGISTERED = False
_LIB_HANDLE = None


def _register_target():
    global _LIB_HANDLE, _REGISTERED
    if _REGISTERED:
        return
    if not _LIB_PATH.exists():
        raise RuntimeError(
            f"{_LIB_PATH.name} is missing. Run `cmake -S . -B build && cmake --build build` "
            f"in {Path(__file__).parent} first."
        )

    _LIB_HANDLE = ctypes.CDLL(str(_LIB_PATH))
    jax.ffi.register_ffi_target(
        _TARGET,
        jax.ffi.pycapsule(_LIB_HANDLE.MatmulSquareF32),
        platform="CUDA",
    )
    _REGISTERED = True


def matmul_square(a, b):
    """Compute C = A @ B through a CUDA JAX FFI target."""
    _register_target()

    a = jnp.asarray(a, dtype=jnp.float32)
    b = jnp.asarray(b, dtype=jnp.float32)
    if a.ndim != 2 or b.ndim != 2 or a.shape != b.shape or a.shape[0] != a.shape[1]:
        raise ValueError("expected two square matrices with the same shape")

    return jax.ffi.ffi_call(
        _TARGET,
        jax.ShapeDtypeStruct(a.shape, np.dtype("float32")),
        input_layouts=((0, 1), (0, 1)),
        output_layouts=(0, 1),
        vmap_method="broadcast_all",
    )(a, b)
