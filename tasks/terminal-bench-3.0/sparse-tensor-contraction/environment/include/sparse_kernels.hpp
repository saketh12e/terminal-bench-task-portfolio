#pragma once

#include "sparse_types.hpp"

#include <vector>

CooTensor coalesce_coo(const CooTensor& in);
SdmmResult sparse_dense_matmul(const CooTensor& sparse, const std::vector<double>& dense, int dense_cols);
std::vector<double> sparse_dense_matmul_backward(
    const CooTensor& sparse,
    const std::vector<double>& dense,
    int dense_cols,
    const std::vector<double>& grad_out);
