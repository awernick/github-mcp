import time

from fastmcp.server.middleware import Middleware, MiddlewareContext

from .metrics import mcp_tool_calls_total, mcp_tool_duration_seconds


class MetricsMiddleware(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        tool_name = context.message.name
        start = time.monotonic()

        try:
            result = await call_next(context)
            status = "error" if result.is_error else "success"
            mcp_tool_calls_total.labels(tool=tool_name, status=status).inc()
        except Exception:
            mcp_tool_calls_total.labels(tool=tool_name, status="exception").inc()
            raise
        finally:
            duration = time.monotonic() - start
            mcp_tool_duration_seconds.labels(tool=tool_name).observe(duration)

        return result
