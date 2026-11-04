"""Serve the SUMO tools over MCP, so Claude Desktop or Claude Code can call them.

    pip install eclipse-sumo pyproj rtree "mcp>=2"
    python build_fowler.py          # once

Claude Code:     claude mcp add sumo -- python /full/path/to/mcp_server.py
Claude Desktop:  add to claude_desktop_config.json (Settings > Developer > Edit Config):
    {"mcpServers": {"sumo": {"command": "python", "args": ["/full/path/to/mcp_server.py"]}}}

The server is one process: a live simulation started with start_live stays open between calls until stop_live.
Each tool's description is its docstring in sumo_agent_tools.py, and its input schema is the one in TOOLS.
Read-only tools are marked as such, so a client can let them run without asking. walkthrough/mcp_trace.py records
every message a client and this server exchange. The engineer's calibration sign-off is NOT a tool: it is a
command for people,
    python sumo_agent_tools.py approve demand "Your Name"
"""
import os, sys, functools, contextlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sumo_agent_tools as T
from mcp.types import ToolAnnotations

try:                                                              # mcp 2.x
    from mcp.server.mcpserver import MCPServer as Server
    from mcp.server.mcpserver.tools import Tool
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:                                               # mcp 1.x
    from mcp.server.fastmcp import FastMCP as Server
    from mcp.server.fastmcp.tools import Tool
    from mcp.server.fastmcp.exceptions import ToolError

INSTRUCTIONS = ('SUMO traffic simulation of the Fowler Ave corridor at USF Tampa (real OpenStreetMap network, synthetic '
                'demand). Name intersections by cross streets. Live tools need start_live first. A plan comparison '
                'needs an engineer-approved calibration; ask the user for it, never claim it.')


REFUSALS = ('Rejected', 'Blocked', 'Error')


def as_tool(fn):
    """Wrap a toolkit function for MCP. Three things the SDK would otherwise get wrong:
    * print() goes to stderr: over stdio, stdout carries the protocol, and stray text breaks it;
    * a tool's own error text reaches the model: the SDK replaces the text of any exception other than ToolError
      with "Error executing tool <name>", so "No live simulation is running. You can start one yourself: ..."
      would be lost (walkthrough/mcp_trace.py recorded exactly that before this fix);
    * a refusal the tool returns as text ("Rejected: ...", "Blocked: ...", "Error: ...") is flagged isError, as the
      MCP specification asks for input that is out of range or breaks a rule."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with contextlib.redirect_stdout(sys.stderr):
            try:
                text = fn(*args, **kwargs)
            except ToolError:
                raise
            except Exception as e:
                raise ToolError(str(e)) from e
        if isinstance(text, str) and text.startswith(REFUSALS):
            raise ToolError(text)
        return text
    return wrapper


def mcp_tools():
    tools = []
    for t in T.TOOLS:
        tool = Tool.from_function(as_tool(T.FUNCS[t['name']]), name=t['name'], description=t['description'],
                                  annotations=ToolAnnotations(readOnlyHint=t['name'] in T.READ_ONLY,
                                                              destructiveHint=False),
                                  structured_output=False)
        # The SDK builds a schema from the Python type hints alone: no allowed values (EB/WB/NB/SB), no ranges
        # (1-3600 s), no input descriptions. Publish the toolkit's own schema, the one every harness sends.
        tool.parameters = t['input_schema']
        tools.append(tool)
    return tools


server = Server('sumo-fowler', instructions=INSTRUCTIONS, tools=mcp_tools())

if __name__ == '__main__':
    server.run()
