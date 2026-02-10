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

# 日本語: メイン ASGI アプリ / English: Root ASGI application
app = FastAPI()

# 日本語: SSE トランスポート（MCP用） / English: SSE transport for MCP
_transport = SseServerTransport("/messages")


async def _sse_app(scope, receive, send):
    # 日本語: SSE の HTTP GET 以外を拒否 / English: Reject non-GET for SSE
    if scope["type"] != "http" or scope.get("method") != "GET":
        response = Response(status_code=405, content="Method not allowed")
        await response(scope, receive, send)
        return

    # 日本語: /sse マウントに伴う root_path を調整 / English: Adjust root_path when mounted under /sse
    root_path = scope.get("root_path", "")
    trimmed_root = str(root_path).removesuffix("/sse/").removesuffix("/sse")
    adjusted_scope = dict(scope)
    adjusted_scope["root_path"] = trimmed_root

    # 日本語: MCP サーバーへ SSE ストリームを接続 / English: Connect SSE streams to MCP server
    async with _transport.connect_sse(adjusted_scope, receive, send) as streams:
        await mcp_server.run(
            streams[0],
            streams[1],
            mcp_server.create_initialization_options(),
        )


# 日本語: MCP 通信用 ASGI サブアプリ / English: MCP ASGI sub-application
mcp_asgi_app = Starlette(
    routes=[
        Mount("/sse", app=_sse_app),
        Mount("/messages", app=_transport.handle_post_message),
    ]
)

# 日本語: /mcp に MCP を、/ にメインアプリをマウント / English: Mount MCP and main app
app.mount("/mcp", mcp_asgi_app)
app.mount("/", main_app)
