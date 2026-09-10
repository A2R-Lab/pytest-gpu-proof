cmake_minimum_required(VERSION 3.18)
project(jax_ffi_cuda_matmul LANGUAGES CXX CUDA)

if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES 60)
endif()

find_package(Python COMPONENTS Interpreter REQUIRED)

execute_process(
  COMMAND "${Python_EXECUTABLE}" -c "import pathlib, jaxlib; print(pathlib.Path(jaxlib.__file__).parent / 'include')"
  OUTPUT_VARIABLE JAXLIB_INCLUDE_DIR
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET
)

if(NOT JAXLIB_INCLUDE_DIR OR NOT EXISTS "${JAXLIB_INCLUDE_DIR}")
  message(FATAL_ERROR "Could not find jaxlib headers. Install jax[cuda] >= 0.4.31 for this example.")
endif()

add_library(jax_ffi_cuda_matmul SHARED src/matmul_ffi.cu)
target_compile_features(jax_ffi_cuda_matmul PRIVATE cxx_std_17)
target_include_directories(jax_ffi_cuda_matmul PRIVATE "${JAXLIB_INCLUDE_DIR}")
set_target_properties(jax_ffi_cuda_matmul PROPERTIES
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
)

