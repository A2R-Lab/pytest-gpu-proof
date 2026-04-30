"""
Example 1 — Minimal no-GPU demo.

Runs entirely on CPU. The "candidate" is just a pure-Python function that
happens to live where a CUDA wrapper would normally live. This lets you:

  - install and test the plugin without CUDA hardware
  - validate the full receipt→sign→verify workflow in CI
  - use this as a copy-paste starting point

Run:
    cd examples/minimal_python_only
    pytest test_minimal.py --gpu-proof-enable -v
"""

import math
import pytest


# ---------------------------------------------------------------------------
# Reference implementation (the "ground truth", pure Python)
# ---------------------------------------------------------------------------

def python_relu(values: list) -> list:
    return [max(0.0, v) for v in values]


def python_softmax(values: list) -> list:
    exps = [math.exp(v) for v in values]
    total = sum(exps)
    return [e / total for e in exps]


# ---------------------------------------------------------------------------
# "GPU" candidate (would be a CUDA wrapper in a real project)
# Here we use an equivalent Python implementation so the example runs anywhere.
# ---------------------------------------------------------------------------

def fake_gpu_relu(values: list) -> list:
    """Stand-in for a CUDA relu kernel."""
    return [v if v > 0.0 else 0.0 for v in values]


def fake_gpu_softmax(values: list) -> list:
    """Stand-in for a CUDA softmax kernel."""
    exps = [math.exp(v) for v in values]
    total = sum(exps)
    return [e / total for e in exps]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.gpu_proof
def test_relu(gpu_proof_check):
    inputs = [1.0, -2.0, 3.0, -4.0, 0.0, 5.5]
    gpu_proof_check(
        name="relu",
        reference=python_relu,
        candidate=fake_gpu_relu,
        args=(inputs,),
        metadata={"operation": "relu", "n": len(inputs)},
    )


@pytest.mark.gpu_proof
def test_softmax(gpu_proof_check):
    inputs = [1.0, 2.0, 3.0, 4.0]
    gpu_proof_check(
        name="softmax",
        reference=python_softmax,
        candidate=fake_gpu_softmax,
        args=(inputs,),
        metadata={"operation": "softmax", "n": len(inputs)},
    )


@pytest.mark.gpu_proof
@pytest.mark.parametrize("scale", [1.0, 2.0, -1.0])
def test_relu_parametrized(gpu_proof_check, scale):
    inputs = [scale * v for v in [1.0, -2.0, 3.0, -0.5]]
    gpu_proof_check(
        name=f"relu_scale_{scale}",
        reference=python_relu,
        candidate=fake_gpu_relu,
        args=(inputs,),
        metadata={"scale": scale},
    )
