"""
Example 2 — Wrapped CUDA library (ctypes-style).

Demonstrates how to test a Python wrapper around a compiled CUDA library.
The pattern is identical whether you use ctypes, cffi, or pybind11:

  1. Your reference is a numpy / pure-Python implementation.
  2. Your candidate is the wrapper that calls into the compiled library.
  3. gpu_proof_check runs both and asserts they agree within tolerance.

Run:
    cd examples/wrapped_cuda_ctypes
    pytest test_cuda_wrapper.py --gpu-proof-enable -v

On a machine with a real CUDA library, replace fake_cuda_lib with your actual
ctypes wrapper module and add @pytest.mark.gpu_required to skip on CPU-only CI.
"""

import math
import sys
import os

import pytest

# Allow importing the fake library from this directory
sys.path.insert(0, os.path.dirname(__file__))
import fake_cuda_lib


# ---------------------------------------------------------------------------
# Reference implementations (numpy / pure Python)
# ---------------------------------------------------------------------------

def numpy_matmul(a_flat, b_flat, n):
    try:
        import numpy as np
        A = np.array(a_flat, dtype=float).reshape(n, n)
        B = np.array(b_flat, dtype=float).reshape(n, n)
        return (A @ B).flatten().tolist()
    except ImportError:
        result = [0.0] * (n * n)
        for i in range(n):
            for k in range(n):
                for j in range(n):
                    result[i * n + j] += a_flat[i * n + k] * b_flat[k * n + j]
        return result


def python_vector_norm(values):
    return math.sqrt(sum(v * v for v in values))


# ---------------------------------------------------------------------------
# "CUDA" candidate wrappers
# ---------------------------------------------------------------------------

def cuda_matmul(a_flat, b_flat, n):
    return fake_cuda_lib.matrix_multiply(a_flat, b_flat, n)


def cuda_vector_norm(values):
    return fake_cuda_lib.vector_norm(values)


# ---------------------------------------------------------------------------
# Custom compare functions
# ---------------------------------------------------------------------------

def compare_floats(ref, cand, rtol=1e-5, atol=1e-6):
    if abs(ref - cand) > atol + rtol * abs(ref):
        raise AssertionError(
            f"Float mismatch: reference={ref:.8f} candidate={cand:.8f} "
            f"delta={abs(ref-cand):.2e}"
        )


def compare_list_allclose(ref, cand, rtol=1e-5, atol=1e-6):
    if len(ref) != len(cand):
        raise AssertionError(f"Length mismatch: {len(ref)} vs {len(cand)}")
    for i, (r, c) in enumerate(zip(ref, cand)):
        if abs(r - c) > atol + rtol * abs(r):
            raise AssertionError(
                f"Element [{i}] mismatch: reference={r:.8f} candidate={c:.8f}"
            )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.gpu_proof
def test_matrix_multiply_2x2(gpu_proof_check):
    n = 2
    a = [1.0, 2.0, 3.0, 4.0]
    b = [5.0, 6.0, 7.0, 8.0]
    gpu_proof_check(
        name="matmul_2x2",
        reference=numpy_matmul,
        candidate=cuda_matmul,
        args=(a, b, n),
        compare=compare_list_allclose,
        metadata={"shape": f"{n}x{n}", "operation": "SGEMM"},
    )


@pytest.mark.gpu_proof
@pytest.mark.parametrize("n", [3, 4, 8])
def test_matrix_multiply_square(gpu_proof_check, n):
    import random
    random.seed(42 + n)
    a = [random.gauss(0, 1) for _ in range(n * n)]
    b = [random.gauss(0, 1) for _ in range(n * n)]
    gpu_proof_check(
        name=f"matmul_{n}x{n}",
        reference=numpy_matmul,
        candidate=cuda_matmul,
        args=(a, b, n),
        compare=compare_list_allclose,
        metadata={"shape": f"{n}x{n}", "operation": "SGEMM"},
    )


@pytest.mark.gpu_proof
def test_vector_norm(gpu_proof_check):
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    gpu_proof_check(
        name="l2_norm",
        reference=python_vector_norm,
        candidate=cuda_vector_norm,
        args=(values,),
        compare=compare_floats,
        metadata={"operation": "L2 norm", "dim": len(values)},
    )
