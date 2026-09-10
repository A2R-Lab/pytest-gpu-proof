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

extern "C" int matmul_square_f32(const float *a_host, const float *b_host, float *c_host, int n) {
    if (n <= 0) {
        return static_cast<int>(cudaErrorInvalidValue);
    }

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

