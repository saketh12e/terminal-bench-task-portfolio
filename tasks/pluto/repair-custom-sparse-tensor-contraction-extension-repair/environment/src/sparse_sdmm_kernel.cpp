#include "sparse_kernels.hpp"
#include "sparse_types.hpp"

#include <cmath>
#include <stdexcept>
#include <vector>

SdmmResult sparse_dense_matmul(const CooTensor& sparse, const std::vector<double>& dense, int dense_cols) {
    if (dense_cols <= 0) {
        throw std::runtime_error("invalid dense_cols");
    }
    if (static_cast<int>(dense.size()) != sparse.cols * dense_cols) {
        throw std::runtime_error("dense shape mismatch");
    }
    SdmmResult result;
    result.coalesced = sparse;
    result.out.assign(static_cast<std::size_t>(sparse.rows) * static_cast<std::size_t>(dense_cols), 0.0);
    for (std::size_t i = 0; i < sparse.row.size(); ++i) {
        const int r = sparse.row[i];
        const int c = sparse.col[i];
        const double v = sparse.val[i];
        if (r < 0 || r >= sparse.rows || c < 0 || c >= sparse.cols) {
            throw std::runtime_error("coo index out of bounds");
        }
        for (int k = 0; k < dense_cols; ++k) {
            result.out[static_cast<std::size_t>(r) * dense_cols + k] +=
                v * dense[static_cast<std::size_t>(c) * dense_cols + k];
        }
    }
    return result;
}

std::vector<double> sparse_dense_matmul_backward(
    const CooTensor& sparse,
    const std::vector<double>& dense,
    int dense_cols,
    const std::vector<double>& grad_out) {
    if (static_cast<int>(grad_out.size()) != sparse.rows * dense_cols) {
        throw std::runtime_error("grad_out shape mismatch");
    }
    std::vector<double> grad_sparse(sparse.row.size(), 0.0);
    for (std::size_t i = 0; i < sparse.row.size(); ++i) {
        const int r = sparse.row[i];
        const int c = sparse.col[i];
        double acc = 0.0;
        for (int k = 0; k < dense_cols; ++k) {
            acc += grad_out[static_cast<std::size_t>(r) * dense_cols + k] *
                   dense[static_cast<std::size_t>(c) * dense_cols + k];
        }
        grad_sparse[i] += acc;
    }
    return grad_sparse;
}
