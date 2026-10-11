FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY requirements_test.txt /tmp/requirements_test.txt
RUN pip install --no-cache-dir -r /tmp/requirements_test.txt
WORKDIR /repo
