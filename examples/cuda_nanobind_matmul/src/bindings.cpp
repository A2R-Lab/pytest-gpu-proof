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

