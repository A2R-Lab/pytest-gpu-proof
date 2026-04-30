#include <cuda_runtime.h>

#include "xla/ffi/api/c_api.h"
#include "xla/ffi/api/ffi.h"

namespace ffi = xla::ffi;

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

ffi::Error MatmulSquareImpl(cudaStream_t stream,
                            ffi::Buffer<ffi::F32> a,
                            ffi::Buffer<ffi::F32> b,
                            ffi::ResultBuffer<ffi::F32> c) {
    auto a_dims = a.dimensions();
    auto b_dims = b.dimensions();

    if (a_dims.size() != 2 || b_dims.size() != 2) {
        return ffi::Error::InvalidArgument("expected two rank-2 input buffers");
    }
    if (a_dims[0] != a_dims[1] || b_dims[0] != a_dims[0] || b_dims[1] != a_dims[1]) {
        return ffi::Error::InvalidArgument("expected two square matrices with the same shape");
    }

    int n = static_cast<int>(a_dims[0]);
    dim3 block(16, 16);
    dim3 grid((n + block.x - 1) / block.x, (n + block.y - 1) / block.y);
    matmul_square_kernel<<<grid, block, 0, stream>>>(a.typed_data(), b.typed_data(), c->typed_data(), n);

    cudaError_t status = cudaGetLastError();
    if (status != cudaSuccess) {
        return ffi::Error::Internal(cudaGetErrorString(status));
    }
    return ffi::Error::Success();
}

XLA_FFI_DEFINE_HANDLER_SYMBOL(
    MatmulSquareF32,
    MatmulSquareImpl,
    ffi::Ffi::Bind()
        .Ctx<ffi::PlatformStream<cudaStream_t>>()
        .Arg<ffi::Buffer<ffi::F32>>()
        .Arg<ffi::Buffer<ffi::F32>>()
        .Ret<ffi::Buffer<ffi::F32>>());
