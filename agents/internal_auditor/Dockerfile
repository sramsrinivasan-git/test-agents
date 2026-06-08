FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN uv pip install --system .

ENV PORT=8080
EXPOSE 8080

CMD ["internal-auditor-server"]
