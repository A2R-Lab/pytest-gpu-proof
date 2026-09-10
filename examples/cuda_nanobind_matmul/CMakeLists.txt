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
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
)

