# Quickstart: local CUDA proof, GitHub verification

This guide creates a separate GitHub repository that builds a tiny CUDA
matrix-multiply extension with nanobind, runs the GPU proof locally, commits the
signed receipt, and lets GitHub Actions verify it on an ordinary CPU runner.

The CI job does not need CUDA, a GPU, or secrets. It only verifies the committed
`gpu-proof.json`.

## What you need

- A Linux machine with a CUDA-capable GPU, NVIDIA driver, CUDA toolkit, `nvcc`,
  CMake, and Python 3.8+.
- A GitHub account with an SSH public key registered at
  `github.com/settings/keys`.
- A new empty GitHub repository. The examples below use
  `git@github.com:YOUR_USER/gpu-proof-nanobind-demo.git`.

## 1. Create the demo repo

```bash
mkdir gpu-proof-nanobind-demo
cd gpu-proof-nanobind-demo
git init
git remote add origin git@github.com:YOUR_USER/gpu-proof-nanobind-demo.git

mkdir -p src tests .github/workflows
```

Create a virtual environment and install the runtime/build tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install pytest-gpu-proof numpy nanobind
```

Add a `.gitignore`:

```gitignore
.venv/
build/
*.so
*.egg-info/
__pycache__/
.pytest_cache/
```

## 2. Add the CUDA nanobind extension

Create `CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.18)
project(cuda_nanobind_matmul LANGUAGES CXX CUDA)

if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES 60)
endif()

find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)

execute_process(
  COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
  OUTPUT_VARIABLE nanobind_ROOT
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET
)
find_package(nanobind CONFIG REQUIRED)

nanobind_add_module(cuda_nanobind_matmul
  src/bindings.cpp
  src/matmul_kernel.cu
)

target_compile_features(cuda_nanobind_matmul PRIVATE cxx_std_17)
target_include_directories(cuda_nanobind_matmul PRIVATE src)
set_target_properties(cuda_nanobind_matmul PROPERTIES
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/src"
)
```

Create `src/matmul_cuda.h`:

```cpp
#pragma once

int cuda_matmul_square_f32(const float *a_host, const float *b_host, float *c_host, int n);
```

Create `src/matmul_kernel.cu`:

```cpp
#include "matmul_cuda.h"

#include <cuda_runtime.h>

__global__ void matmul_square_kernel(const float *a, const float *b, float *c, int n) {
    int row = blockIdx.y * blockDim.y + threadIdx.y;
    int col = blockIdx.x * blockDim.x + threadIdx.x;

    if (row >= n || col >= n) {
        return;
    }

    float acc = 0.0f;
    for (int k = 0; k < n; ++k) {
        acc += a[row * n + k] * b[k * n + col];
    }
    c[row * n + col] = acc;
}

int cuda_matmul_square_f32(const float *a_host, const float *b_host, float *c_host, int n) {
    const size_t bytes = static_cast<size_t>(n) * static_cast<size_t>(n) * sizeof(float);
    float *a_dev = nullptr;
    float *b_dev = nullptr;
    float *c_dev = nullptr;

    cudaError_t status = cudaMalloc(&a_dev, bytes);
    if (status != cudaSuccess) {
        return static_cast<int>(status);
    }
    status = cudaMalloc(&b_dev, bytes);
    if (status != cudaSuccess) {
        cudaFree(a_dev);
        return static_cast<int>(status);
    }
    status = cudaMalloc(&c_dev, bytes);
    if (status != cudaSuccess) {
        cudaFree(a_dev);
        cudaFree(b_dev);
        return static_cast<int>(status);
    }

    status = cudaMemcpy(a_dev, a_host, bytes, cudaMemcpyHostToDevice);
    if (status == cudaSuccess) {
        status = cudaMemcpy(b_dev, b_host, bytes, cudaMemcpyHostToDevice);
    }
    if (status == cudaSuccess) {
        dim3 block(16, 16);
        dim3 grid((n + block.x - 1) / block.x, (n + block.y - 1) / block.y);
        matmul_square_kernel<<<grid, block>>>(a_dev, b_dev, c_dev, n);
        status = cudaGetLastError();
    }
    if (status == cudaSuccess) {
        status = cudaDeviceSynchronize();
    }
    if (status == cudaSuccess) {
        status = cudaMemcpy(c_host, c_dev, bytes, cudaMemcpyDeviceToHost);
    }

    cudaFree(a_dev);
    cudaFree(b_dev);
    cudaFree(c_dev);
    return static_cast<int>(status);
}
```

Create `src/bindings.cpp`:

```cpp
#include <stdexcept>
#include <string>
#include <vector>

#include <nanobind/nanobind.h>
#include <nanobind/stl/vector.h>

#include "matmul_cuda.h"

namespace nb = nanobind;

std::vector<float> matmul_square(const std::vector<float> &a,
                                 const std::vector<float> &b,
                                 int n) {
    const size_t expected = static_cast<size_t>(n) * static_cast<size_t>(n);
    if (n <= 0 || a.size() != expected || b.size() != expected) {
        throw std::invalid_argument("expected two flat row-major n x n matrices");
    }

    std::vector<float> out(expected);
    int status = cuda_matmul_square_f32(a.data(), b.data(), out.data(), n);
    if (status != 0) {
        throw std::runtime_error("CUDA matmul failed with cudaError_t=" + std::to_string(status));
    }
    return out;
}

NB_MODULE(cuda_nanobind_matmul, m) {
    m.doc() = "nanobind CUDA matrix multiplication example for pytest-gpu-proof";
    m.def("matmul_square", &matmul_square, nb::arg("a_flat"), nb::arg("b_flat"), nb::arg("n"));
}
```

## 3. Add the GPU proof test

Create `tests/test_cuda_nanobind_matmul.py`:

```python
import importlib.util

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
def test_nanobind_cuda_matmul_square(gpu_proof_check):
    if importlib.util.find_spec("cuda_nanobind_matmul") is None:
        pytest.fail("cuda_nanobind_matmul is not built. Run `cmake -S . -B build && cmake --build build`.")

    import cuda_nanobind_matmul

    n = 4
    a = (np.arange(n * n, dtype=np.float32) / 17.0).tolist()
    b = (np.flip(np.arange(n * n, dtype=np.float32)).copy() / 19.0).tolist()

    gpu_proof_check(
        name="cuda_nanobind_matmul_4x4",
        reference=reference_matmul,
        candidate=cuda_nanobind_matmul.matmul_square,
        args=(a, b, n),
        compare=compare_allclose,
        metadata={"binding": "nanobind", "shape": "4x4", "dtype": "float32"},
    )
```

## 4. Add CPU-only GitHub verification

Create `.github/workflows/verify-gpu-proof.yml`:

```yaml
name: Verify GPU proof

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install verifier
        run: python -m pip install pytest-gpu-proof

      - name: Verify committed GPU receipt
        run: |
          gpu-proof verify \
            --receipt gpu-proof.json \
            --repo . \
            --max-age-days 30
```

This job verifies your signature, the current commit, the fingerprint of `src/`
`tests/`, and `CMakeLists.txt`, receipt freshness, and the recorded test
outcomes.

## 5. Commit the initial repo

Make an initial commit before generating the proof. The receipt records the
current commit SHA, so generate it from the commit you plan to push.

```bash
git add .
git commit -m "add CUDA nanobind GPU proof demo"
git branch -M main
```

## 6. Build and run the proof locally

Build the extension with the same Python environment that has nanobind
installed:

```bash
cmake -S . -B build -DPython_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build build
```

Run the proof test and write `gpu-proof.json`:

```bash
PYTHONPATH=src pytest tests/ \
  --gpu-proof-enable \
  --gpu-proof-fingerprint-paths=src,tests,CMakeLists.txt \
  --gpu-proof-github-user YOUR_USER \
  -v
```

You should see:

```text
PASSED tests/test_cuda_nanobind_matmul.py::test_nanobind_cuda_matmul_square
[gpu-proof] Receipt written to gpu-proof.json
[gpu-proof] Signed with key SHA256:...
```

If your GitHub remote is already configured as `github.com/YOUR_USER/...`, the
plugin can usually infer the username and `--gpu-proof-github-user` is optional.

## 7. Commit and push the receipt

```bash
git add gpu-proof.json
git commit -m "add local GPU proof receipt"
git push -u origin main
```

Open the repository on GitHub and check the Actions tab. The workflow should
pass without a GPU runner because it only verifies the committed receipt.

The receipt records the commit SHA that existed when you ran the GPU test. The
verifier accepts the follow-up commit that adds only `gpu-proof.json`, as long
as the recorded fingerprint still matches the checked-out files.

## Updating the proof after code changes

When you change files under `src/` or `tests/`, generate a new receipt for the
new commit:

```bash
git add src tests CMakeLists.txt
git commit -m "change CUDA matmul demo"

cmake --build build
PYTHONPATH=src pytest tests/ \
  --gpu-proof-enable \
  --gpu-proof-fingerprint-paths=src,tests,CMakeLists.txt \
  --gpu-proof-github-user YOUR_USER \
  -v

git add gpu-proof.json
git commit -m "update GPU proof receipt"
git push
```

## Troubleshooting

- `No SSH private key found`: pass `--gpu-proof-key ~/.ssh/id_ed25519`, or set
  `git config user.signingKey ~/.ssh/id_ed25519`.
- `Cannot determine GitHub username`: pass `--gpu-proof-github-user YOUR_USER`.
- `Fingerprint mismatch`: regenerate `gpu-proof.json` after committing the code
  state you want CI to verify.
- `Commit SHA mismatch`: generate the proof after the commit that will be
  pushed.
- `Signature does not match any SSH key`: make sure the public half of the key
  used locally is registered on your GitHub account.

## Next steps

- [Local mode](local_mode.md) explains the workflow in general terms.
- [CI-GPU mode](ci_gpu_mode.md) shows how to run GPU tests on a GPU runner
  instead of a developer machine.
- [Security model](security_model.md) explains what the receipt proves.
