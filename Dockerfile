# GitHub MCP server (stdio locally, streamable-http in Docker).
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (pyproject.toml) so rebuilds reuse the layer
# cache when only src/ changes.
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# HTTP transport for container deployments; stdio stays the default when
# MCP_TRANSPORT is unset. Port is overridable via MCP_PORT.
ENV MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=3102

EXPOSE 3102

CMD ["github-mcp"]
