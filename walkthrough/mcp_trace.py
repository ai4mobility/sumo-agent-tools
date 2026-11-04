"""Record every MCP message between a client and mcp_server.py: what Claude Code or Claude Desktop sends and gets back.

A tiny relay sits between the client and the server and writes down each line that crosses stdio, so you can
read the protocol itself rather than a summary of it. Over stdio, MCP is one JSON-RPC message per line.

    pip install "mcp>=2"
    python walkthrough/mcp_trace.py          # writes walkthrough/mcp_trace.json
"""
import asyncio, json, os, subprocess, sys, threading, time
HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), 'mcp_server.py')


def relay(log_path, cmd):
    """Pass stdin to the server and its stdout back, logging every line (the client never knows it is there)."""
    child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    t0, lock, log = time.time(), threading.Lock(), open(log_path, 'w')

    def note(direction, line):
        with lock:
            log.write(json.dumps({'t_s': round(time.time() - t0, 3), 'dir': direction,
                                  'msg': json.loads(line)}) + '\n')
            log.flush()

    def client_to_server():
        for line in sys.stdin.buffer:
            note('client -> server', line)
            child.stdin.write(line)
            child.stdin.flush()
        child.stdin.close()

    threading.Thread(target=client_to_server, daemon=True).start()
    for line in child.stdout:
        note('server -> client', line)
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()
    child.wait()


CALLS = [('get_approach_state', {'intersection': 'Fowler & 30th', 'approach': 'WB'}),   # before start_live
         ('start_live', {}),
         ('advance', {'seconds': 4500}),                                                 # out of range
         ('advance', {'seconds': 900}),
         ('get_approach_state', {'intersection': 'Fowler & 30th', 'approach': 'WB'}),
         ('stop_live', {})]


async def client(log_path):
    from mcp.client.client import Client
    from mcp.client.stdio import StdioServerParameters
    params = StdioServerParameters(command=sys.executable,
                                   args=[__file__, '--relay', log_path, '--', sys.executable, SERVER])
    async with Client(params) as c:
        await c.list_tools()
        for name, args in CALLS:
            await c.call_tool(name, args)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--relay':
        relay(sys.argv[2], sys.argv[4:])
    else:
        raw = os.path.join(HERE, 'mcp_trace.jsonl')
        t0 = time.time()
        asyncio.run(client(raw))
        msgs = [json.loads(l) for l in open(raw)]
        json.dump({'mcp_server': 'mcp_server.py', 'messages': msgs, 'total_s': round(time.time() - t0, 1)},
                  open(os.path.join(HERE, 'mcp_trace.json'), 'w'), indent=1)
        for m in msgs:
            print(f"{m['t_s']:7.3f} s  {m['dir']}: {json.dumps(m['msg'])[:160]}")
