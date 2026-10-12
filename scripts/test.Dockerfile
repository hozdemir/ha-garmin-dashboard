FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
ARG HA_SERIES=2026.10
COPY requirements/test-${HA_SERIES}.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /repo
