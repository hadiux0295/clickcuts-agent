FROM python:3.12-slim
RUN pip install --no-cache-dir mcp-clickhouse
ENV CLICKHOUSE_MCP_SERVER_TRANSPORT=http
ENV CLICKHOUSE_MCP_BIND_HOST=0.0.0.0
CMD ["sh", "-c", "CLICKHOUSE_MCP_BIND_PORT=${PORT:-8080} mcp-clickhouse"]
