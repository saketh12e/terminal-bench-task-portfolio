cmake_minimum_required(VERSION 3.18)
project(sparse_contract_ext LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(Python3 REQUIRED COMPONENTS Interpreter Development)
find_package(pybind11 CONFIG QUIET)
if(NOT pybind11_FOUND)
  execute_process(
    COMMAND "${Python3_EXECUTABLE}" -c "import pybind11, pathlib; print(pathlib.Path(pybind11.get_cmake_dir()))"
    OUTPUT_VARIABLE PYBIND11_CMAKE_DIR
    OUTPUT_STRIP_TRAILING_WHITESPACE
    COMMAND_ERROR_IS_FATAL ANY)
  list(APPEND CMAKE_PREFIX_PATH "${PYBIND11_CMAKE_DIR}")
  find_package(pybind11 CONFIG REQUIRED)
endif()

pybind11_add_module(
  sparse_contract_ext
  src/sparse_ext_bindings.cpp
  src/sparse_coalesce_kernel.cpp
  src/sparse_sdmm_kernel.cpp)

target_include_directories(sparse_contract_ext PRIVATE include)
target_compile_options(sparse_contract_ext PRIVATE -Wall -Wextra -O2)
