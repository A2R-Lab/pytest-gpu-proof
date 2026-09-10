NVCC ?= nvcc
CUDA_ARCH ?= sm_60

TARGET := libcuda_ctypes_matmul.so
SRC := matmul_kernel.cu

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(SRC)
	$(NVCC) -O2 -Xcompiler -fPIC -shared -arch=$(CUDA_ARCH) $< -o $@

clean:
	rm -f $(TARGET)

