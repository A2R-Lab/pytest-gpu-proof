"""
Simulates a compiled CUDA shared library called via ctypes or cffi.

In a real project this file would NOT exist — you would instead have:

    libmy_cuda.so      (your compiled CUDA library)
    cuda_wrapper.py    (the Python ctypes/cffi/pybind11 wrapper)

This stub lets the example run on any machine without a GPU or CUDA toolkit,
while keeping the wrapper pattern identical to what you would write for a real library.
"""

import ctypes
import math
from typing import List


def matrix_multiply(a_flat: List[float], b_flat: List[float], n: int) -> List[float]:
    """
    Simulates a CUDA SGEMM kernel: C = A @ B for square n×n matrices.
    In production, this would call into libcublas or a custom CUDA kernel.
    """
    result = [0.0] * (n * n)
    for i in range(n):
        for k in range(n):
            for j in range(n):
                result[i * n + j] += a_flat[i * n + k] * b_flat[k * n + j]
    return result


def vector_norm(values: List[float]) -> float:
    """Simulates a CUDA reduction kernel for L2 norm."""
    return math.sqrt(sum(v * v for v in values))
