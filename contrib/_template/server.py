"""Serve the toolkit's tools and yours over MCP, from one server and one simulation.

    pip install "mcp>=2"
    python contrib/<you>/server.py           # starts and waits: a client talks to it over stdin/stdout

Your tools and the toolkit's must share one process: a live simulation lives in the process that started it, so a
second server would run a second, separate simulation. That is why this server serves both.

Watch a model use it (contrib/agent_loop.py), or connect Claude:
    python contrib/agent_loop.py contrib/<you>/server.py "your question" --name q1
    claude mcp add sumo-<you> -- python /full/path/to/sumo-agent-tools/contrib/<you>/server.py      # Claude Code
    Claude Desktop: Settings > Developer > Edit Config, then add to claude_desktop_config.json
    {"mcpServers": {"sumo-<you>": {"command": "python",
                                   "args": ["/full/path/to/sumo-agent-tools/contrib/<you>/server.py"]}}}

What you decide here, for your own tools (contrib/check.py checks the first one):
  1. annotations: readOnlyHint for a tool that only reads; destructiveHint for one whose change cannot be undone
  2. the input schema the model sees: the toolkit publishes its own (allowed values, ranges); give yours in
     SCHEMAS in tools.py, or the SDK builds one from the type hints alone
  3. INSTRUCTIONS: what the model must know before it calls any tool. Say what your tools add and when to use them
Errors: base.as_tool passes a tool's own error text to the model and flags refusals ("Rejected", "Blocked",
"Error") as errors, as the MCP specification asks. Nothing may print to stdout: over stdio, stdout carries the
protocol. Use print(..., file=sys.stderr) to debug.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', '..'))
import mcp_server as base       # the toolkit's server: its tools, as_tool(), and the SDK classes it imports
import tools as mine            # your tools.py
from mcp.types import ToolAnnotations

INSTRUCTIONS = (
    base.INSTRUCTIONS + ' '
    # ---- your part: what your tools add, and when to use them
    'For what each lane at a stop line serves and holds, use lane_use: it names lanes by movement, from the '
    'median to the curb.')


def my_tools():
    out = []
    for fn in mine.TOOLS:
        t = base.Tool.from_function(base.as_tool(fn), name=fn.__name__, description=' '.join(fn.__doc__.split()),
                                    annotations=ToolAnnotations(readOnlyHint=fn.__name__ in mine.READ_ONLY,
                                                                destructiveHint=False),
                                    structured_output=False)
        if fn.__name__ in getattr(mine, 'SCHEMAS', {}):
            t.parameters = mine.SCHEMAS[fn.__name__]
        out.append(t)
    return out


server = base.Server('sumo-' + os.path.basename(HERE), instructions=INSTRUCTIONS, tools=base.mcp_tools() + my_tools())

if __name__ == '__main__':
    server.run()
