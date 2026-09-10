cmake_minimum_required(VERSION 3.18)
project(cuda_pybind11_matmul LANGUAGES CXX CUDA)

if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES 60)
endif()

find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)

execute_process(
  COMMAND "${Python_EXECUTABLE}" -m pybind11 --cmakedir
  OUTPUT_VARIABLE pybind11_DIR
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET
)
find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(cuda_pybind11_matmul
  src/bindings.cpp
  src/matmul_kernel.cu
)

target_compile_features(cuda_pybind11_matmul PRIVATE cxx_std_17)
target_include_directories(cuda_pybind11_matmul PRIVATE src)
set_target_properties(cuda_pybind11_matmul PROPERTIES
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
)

