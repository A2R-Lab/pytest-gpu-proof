# CUDA nanobind matrix multiplication

This example builds a CUDA-backed Python extension with nanobind and verifies
it with `pytest-gpu-proof`.

The exported operation is:

```python
cuda_nanobind_matmul.matmul_square(a_flat, b_flat, n) -> list[float]
```

where the inputs are row-major `float32` values for `n x n` matrices.

## Prerequisites

- NVIDIA CUDA toolkit with `nvcc`
- CMake
- A CUDA-capable GPU and driver
- Python packages: `pytest`, `numpy`, `pytest-gpu-proof`, `nanobind`

Install the example-only build dependency with:

```bash
python3 -m pip install nanobind
```

## Build

```bash
cd examples/cuda_nanobind_matmul
cmake -S . -B build
cmake --build build
```

The extension module is written into this directory and ignored by git as a
compiled shared library.

## Run

```bash
PYTHONPATH=../../src pytest test_cuda_nanobind_matmul.py --gpu-proof-enable -v
```

On machines without GPU access, the `gpu_required` marker skips the test. If a
GPU is present but the extension has not been built, the test fails with a
message telling you to run the CMake commands above.
