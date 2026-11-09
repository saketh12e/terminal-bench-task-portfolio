#pragma once

#include <cstddef>
#include <tuple>
#include <vector>

struct CooTensor {
    int rows = 0;
    int cols = 0;
    std::vector<int> row;
    std::vector<int> col;
    std::vector<double> val;
};

struct SdmmResult {
    std::vector<double> out;
    CooTensor coalesced;
};
