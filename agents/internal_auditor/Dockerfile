FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN uv pip install --system .

# HTTP service: POST /audit + GET /healthz. Listens on $PORT (default 8080).
ENV PORT=8080
EXPOSE 8080

CMD ["internal-auditor-server"]
