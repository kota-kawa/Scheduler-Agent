import logging
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.responses import Response
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Mount

from app import app as flask_app
from mcp_server import mcp_server

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler_asgi")

app = FastAPI()

# Global transport for single-client scenario
# Note: The MCP app is mounted at "/mcp", so the message endpoint should be
# relative to that root. Using "/messages" prevents double-prefix paths such
# as "/mcp/sse/mcp/messages" when the SSE root_path already includes "/mcp/sse".
_transport = SseServerTransport("/messages")

async def _sse_app(scope, receive, send):
    """ASGI app that bridges SSE transport to MCP server."""
    if scope["type"] != "http" or scope.get("method") != "GET":
        response = Response(status_code=405, content="Method not allowed")
        await response(scope, receive, send)
        return

    # Starlette mounts the child app with a root_path that includes the mount
    # point (e.g., "/mcp/sse"). Strip the "/sse" suffix so the generated
    # message endpoint resolves to "/mcp/messages" instead of
    # "/mcp/sse/messages".
    root_path = scope.get("root_path", "")
    trimmed_root = str(root_path).removesuffix("/sse/").removesuffix("/sse")
    adjusted_scope = dict(scope)
    adjusted_scope["root_path"] = trimmed_root

    async with _transport.connect_sse(adjusted_scope, receive, send) as streams:
        await mcp_server.run(
            streams[0],
            streams[1],
            mcp_server.create_initialization_options(),
        )


# Sub-application for MCP transport endpoints
mcp_asgi_app = Starlette(
    routes=[
        Mount("/sse", app=_sse_app),
        Mount("/messages", app=_transport.handle_post_message),
    ]
)

# Mount MCP paths before falling back to Flask
app.mount("/mcp", mcp_asgi_app)

# Mount Flask at root for everything else
app.mount("/", WSGIMiddleware(flask_app))
