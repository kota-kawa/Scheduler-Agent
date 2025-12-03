"""MCP server for Scheduler Agent."""
import logging
from typing import Any, List, Dict

try:
    import mcp.types as types
    from mcp.server import Server
    from mcp.types import Tool
except ModuleNotFoundError as exc:
    raise RuntimeError('mcp[cli] is required.') from exc

from app import app, process_chat_request

# Initialize MCP Server
mcp_server = Server("scheduler-agent")

@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="manage_schedule",
            description="自然言語でスケジュールの確認・追加・変更・日報の記録を行います。",
            inputSchema={
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "スケジュールに関する指示（例: '明日の10時に会議を入れる', '今日の日報を書く'）"
                    }
                },
                "required": ["instruction"]
            }
        )
    ]

@mcp_server.call_tool()
async def call_tool(name: str, arguments: Any) -> List[types.TextContent]:
    """Handle tool calls."""
    if name == "manage_schedule":
        instruction = ""
        if isinstance(arguments, dict):
            instruction = arguments.get("instruction", "")
        
        if not instruction:
            return [types.TextContent(type="text", text="Error: instruction is required")]

        # Execute logic within Flask app context
        with app.app_context():
            try:
                result = process_chat_request(instruction, save_history=False)
                reply = result.get("reply", "")
                return [types.TextContent(type="text", text=reply)]
            except Exception as e:
                logging.exception("Error processing schedule instruction")
                return [types.TextContent(type="text", text=f"Error: {str(e)}")]

    raise ValueError(f"Unknown tool: {name}")
