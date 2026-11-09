FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254
WORKDIR /tests
RUN pip install --no-cache-dir numpy==2.4.5 scipy==1.17.1 pytest==9.1.1 pytest-json-ctrf==0.5.2
RUN mkdir -p /app /logs/verifier && chmod 700 /logs/verifier
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
COPY . /tests/
