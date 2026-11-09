FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

ENV PYTHONPATH=/app

RUN pip install --no-cache-dir pytest==8.4.1 pytest-json-ctrf==0.3.5

COPY data /app/data
COPY model /app/model
COPY spec /app/spec
COPY lm_router /app/lm_router
COPY bin/lm-router-score /usr/local/bin/lm-router-score

RUN chmod 0755 /usr/local/bin/lm-router-score \
    && mkdir -p /app/output /tmp/router-eval

WORKDIR /app
