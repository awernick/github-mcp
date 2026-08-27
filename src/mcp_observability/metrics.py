from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

mcp_tool_calls_total = Counter(
    "mcp_tool_calls_total",
    "Total MCP tool calls",
    ["tool", "status"],
)

mcp_tool_duration_seconds = Histogram(
    "mcp_tool_duration_seconds",
    "MCP tool call duration in seconds",
    ["tool"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)


def metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST


def metrics_output() -> bytes:
    return generate_latest()
