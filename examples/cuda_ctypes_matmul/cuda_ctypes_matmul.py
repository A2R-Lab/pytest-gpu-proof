import ctypes
from pathlib import Path

import numpy as np


_LIB_PATH = Path(__file__).with_name("libcuda_ctypes_matmul.so")


def _load_library():
    if not _LIB_PATH.exists():
        raise RuntimeError(
            f"{_LIB_PATH.name} is missing. Run `make` in {Path(__file__).parent} first."
        )

    lib = ctypes.CDLL(str(_LIB_PATH))
    lib.matmul_square_f32.argtypes = [
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_float),
        ctypes.c_int,
    ]
    lib.matmul_square_f32.restype = ctypes.c_int
    return lib


def matmul_square(a_flat, b_flat, n):
    """Compute C = A @ B for row-major n x n float32 matrices."""
    a = np.asarray(a_flat, dtype=np.float32).reshape(n * n)
    b = np.asarray(b_flat, dtype=np.float32).reshape(n * n)
    out = np.empty(n * n, dtype=np.float32)

    status = _load_library().matmul_square_f32(
        a.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        b.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        ctypes.c_int(n),
    )
    if status != 0:
        raise RuntimeError(f"CUDA matmul failed with cudaError_t={status}")

    return out.tolist()

