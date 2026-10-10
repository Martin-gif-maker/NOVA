"""A real MCP server built with the official `mcp` package - NOVA's own client is tested against it.
Run:  python mcp_real_server.py            (stdio)
      python mcp_real_server.py http PORT  (streamable HTTP on 127.0.0.1)"""
import sys
from mcp.server.mcpserver import MCPServer

server = MCPServer("nova-test-server")


@server.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@server.tool()
def shout(text: str, times: int = 1) -> str:
    """Upper-case a text, optionally repeated."""
    return " ".join([text.upper()] * times)


@server.tool()
def explode() -> str:
    """Always fails."""
    raise ValueError("this tool always fails")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "http":
        server.run("streamable-http", host="127.0.0.1", port=int(sys.argv[2]),
                   json_response=(len(sys.argv) > 3 and sys.argv[3] == "json"))
    else:
        server.run("stdio")
