#include <stdexcept>
#include <string>
#include <vector>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "matmul_cuda.h"

namespace py = pybind11;

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

PYBIND11_MODULE(cuda_pybind11_matmul, m) {
    m.doc() = "pybind11 CUDA matrix multiplication example for pytest-gpu-proof";
    m.def("matmul_square", &matmul_square, py::arg("a_flat"), py::arg("b_flat"), py::arg("n"));
}

