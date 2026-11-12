FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# Hosting platforms (Render, Railway, Fly, Cloud Run) inject PORT.
ENV MCP_TRANSPORT=http HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "mlb-stats-mcp"]
