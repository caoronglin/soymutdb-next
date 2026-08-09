# SoyMutDB MCP server image (B1 skeleton)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install the package (fastmcp / httpx / uvicorn via pyproject deps).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Streamable HTTP endpoint.
EXPOSE 9000

CMD ["python", "-m", "mcp_server.server", "--host", "0.0.0.0", "--port", "9000"]
