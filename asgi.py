import logging

from fastapi import FastAPI
from fastapi.responses import Response
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Mount

from app import app as main_app
from mcp_server import mcp_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler_asgi")

app = FastAPI()

_transport = SseServerTransport("/messages")


async def _sse_app(scope, receive, send):
    if scope["type"] != "http" or scope.get("method") != "GET":
        response = Response(status_code=405, content="Method not allowed")
        await response(scope, receive, send)
        return

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


mcp_asgi_app = Starlette(
    routes=[
        Mount("/sse", app=_sse_app),
        Mount("/messages", app=_transport.handle_post_message),
    ]
)

app.mount("/mcp", mcp_asgi_app)
app.mount("/", main_app)
