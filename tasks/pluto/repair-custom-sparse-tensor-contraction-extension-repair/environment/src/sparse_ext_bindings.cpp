#include "sparse_kernels.hpp"
#include "sparse_types.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

CooTensor coo_from_lists(const std::vector<int>& row,
                         const std::vector<int>& col,
                         const std::vector<double>& val,
                         int rows,
                         int cols) {
    CooTensor t;
    t.rows = rows;
    t.cols = cols;
    t.row = row;
    t.col = col;
    t.val = val;
    return t;
}

py::dict coo_to_dict(const CooTensor& t) {
    py::dict d;
    d["rows"] = t.rows;
    d["cols"] = t.cols;
    d["row"] = t.row;
    d["col"] = t.col;
    d["val"] = t.val;
    return d;
}

PYBIND11_MODULE(sparse_contract_ext, m) {
    m.doc() = "Sparse COO coalesce and sparse-dense matmul kernels";

    m.def(
        "coalesce_coo",
        [](const std::vector<int>& row,
           const std::vector<int>& col,
           const std::vector<double>& val,
           int rows,
           int cols) { return coo_to_dict(coalesce_coo(coo_from_lists(row, col, val, rows, cols))); },
        py::arg("row"),
        py::arg("col"),
        py::arg("val"),
        py::arg("rows"),
        py::arg("cols"));

    m.def(
        "sparse_dense_matmul",
        [](const std::vector<int>& row,
           const std::vector<int>& col,
           const std::vector<double>& val,
           int rows,
           int cols,
           const std::vector<double>& dense,
           int dense_cols) {
            auto fwd = sparse_dense_matmul(coo_from_lists(row, col, val, rows, cols), dense, dense_cols);
            py::dict out;
            out["out"] = fwd.out;
            out["coalesced"] = coo_to_dict(fwd.coalesced);
            return out;
        },
        py::arg("row"),
        py::arg("col"),
        py::arg("val"),
        py::arg("rows"),
        py::arg("cols"),
        py::arg("dense"),
        py::arg("dense_cols"));

    m.def(
        "sparse_dense_matmul_backward",
        [](const std::vector<int>& row,
           const std::vector<int>& col,
           const std::vector<double>& val,
           int rows,
           int cols,
           const std::vector<double>& dense,
           int dense_cols,
           const std::vector<double>& grad_out) {
            return sparse_dense_matmul_backward(
                coo_from_lists(row, col, val, rows, cols), dense, dense_cols, grad_out);
        },
        py::arg("row"),
        py::arg("col"),
        py::arg("val"),
        py::arg("rows"),
        py::arg("cols"),
        py::arg("dense"),
        py::arg("dense_cols"),
        py::arg("grad_out"));
}
