FROM debian:bookworm-slim

ENV APP_DIR=/app
ENV PYTHONPATH=/app/build:/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build \
    python3 python3-pip python3-dev \
    jq \
    && python3 -m pip install --no-cache-dir --break-system-packages \
        pytest==8.3.4 numpy==2.1.3 pybind11==2.13.6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY CMakeLists.txt ./
COPY include/ ./include/
COPY src/ ./src/
COPY sparse_*.py ./
COPY data/ ./data/
COPY work/ ./work/

RUN cmake -S . -B build -GNinja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    && cmake --build build -j \
    && python3 -c "import sys; sys.path.insert(0, 'build'); import sparse_contract_ext; print('ext ok')"

RUN mkdir -p /app/output /logs/verifier
