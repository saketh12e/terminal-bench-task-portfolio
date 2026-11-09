FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends bash ca-certificates git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir numpy==2.4.5 scipy==1.17.1
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
COPY app/ /app/
