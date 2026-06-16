FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN uv pip install --system .

# No EXPOSE: this container is a Pub/Sub subscriber, not an HTTP service.
# Liveness is detected via the heartbeat file written by common.heartbeat;
# see the exec livenessProbe in deployment/k8s/deployment.yaml.
CMD ["internal-auditor-subscriber"]
