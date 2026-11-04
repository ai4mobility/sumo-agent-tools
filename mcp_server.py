"""Serve the SUMO tools over MCP, so Claude Desktop or Claude Code can call them.

    pip install eclipse-sumo pyproj rtree "mcp>=2"
    python build_fowler.py          # once

Claude Code:     claude mcp add sumo -- python /full/path/to/mcp_server.py
Claude Desktop:  add to claude_desktop_config.json (Settings > Developer > Edit Config):
    {"mcpServers": {"sumo": {"command": "python", "args": ["/full/path/to/mcp_server.py"]}}}

The server is one process: a live simulation started with start_live stays open between calls until stop_live.
Each tool's description is its docstring in sumo_agent_tools.py. Read-only tools are marked as such, so a client
can let them run without asking. The engineer's calibration sign-off is NOT a tool: it is a command for people,
    python sumo_agent_tools.py approve demand "Your Name"
"""
import os, sys, functools, contextlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sumo_agent_tools as T

try:
    from mcp.server.mcpserver import MCPServer as Server      # mcp 2.x
except ImportError:
    from mcp.server.fastmcp import FastMCP as Server          # mcp 1.x
from mcp.types import ToolAnnotations

server = Server('sumo-fowler', instructions=(
    'SUMO traffic simulation of the Fowler Ave corridor at USF Tampa (real OpenStreetMap network, synthetic '
    'demand). Name intersections by cross streets. Live tools need start_live first. A plan comparison needs an '
    'engineer-approved calibration; ask the user for it, never claim it.'))

def quiet(fn):
    """Run a tool with print() sent to stderr: over stdio, stdout carries the protocol and stray text breaks it."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with contextlib.redirect_stdout(sys.stderr):
            return fn(*args, **kwargs)
    return wrapper


for t in T.TOOLS:
    ro = t['name'] in T.READ_ONLY
    server.add_tool(quiet(T.FUNCS[t['name']]), name=t['name'], description=t['description'],
                    annotations=ToolAnnotations(readOnlyHint=ro, destructiveHint=False))

if __name__ == '__main__':
    server.run()
