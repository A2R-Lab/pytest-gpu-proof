# CUDA ctypes matrix multiplication

This example builds a small CUDA shared library with a C ABI, loads it with
Python `ctypes`, and verifies it with `pytest-gpu-proof`.

The exported operation is:

```python
matmul_square(a_flat, b_flat, n) -> list[float]
```

where `a_flat` and `b_flat` are row-major `float32` values for `n x n`
matrices.

## Prerequisites

- NVIDIA CUDA toolkit with `nvcc`
- A CUDA-capable GPU and driver
- Python packages: `pytest`, `numpy`, `pytest-gpu-proof`

## Build

```bash
cd examples/cuda_ctypes_matmul
make
```

This writes `libcuda_ctypes_matmul.so` in this directory. The repository
`.gitignore` already ignores compiled shared libraries.

## Run

```bash
PYTHONPATH=../../src pytest test_cuda_ctypes_matmul.py --gpu-proof-enable -v
```

On machines without GPU access, the `gpu_required` marker skips the test. If a
GPU is present but the shared library has not been built, the test fails with a
message telling you to run `make`.

