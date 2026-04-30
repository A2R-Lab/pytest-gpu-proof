# CUDA JAX FFI matrix multiplication

This example registers a CUDA typed FFI target with JAX, calls it through
`jax.ffi.ffi_call`, and verifies it with `pytest-gpu-proof`.

The exported Python operation is:

```python
jax_ffi_matmul.matmul_square(a, b) -> jax.Array
```

where `a` and `b` are square `float32` matrices.

## Prerequisites

- NVIDIA CUDA toolkit with `nvcc`
- CMake
- A CUDA-capable GPU and driver
- Python packages: `pytest`, `numpy`, `pytest-gpu-proof`, `jax[cuda] >= 0.4.31`

Install the example-only JAX dependency using the command recommended for your
CUDA version in the official JAX installation docs.

## Build

```bash
cd examples/jax_ffi_cuda_matmul
cmake -S . -B build
cmake --build build
```

This writes `libjax_ffi_cuda_matmul.so` in this directory. The repository
`.gitignore` already ignores compiled shared libraries.

## Run

```bash
PYTHONPATH=../../src pytest test_jax_ffi_cuda_matmul.py --gpu-proof-enable -v
```

On machines without GPU access, the `gpu_required` marker skips the test. If a
GPU is present but the FFI library has not been built, the test fails with a
message telling you to run the CMake commands above.

JAX FFI APIs are lower-level than pybind11/nanobind and are meant for users who
need the operation to participate in JAX lowering and compilation.

