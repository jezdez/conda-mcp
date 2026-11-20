"""A local FastMCP server with one greeting tool."""

from fastmcp import FastMCP

server = FastMCP("Greeting example")


@server.tool
def greet(name: str) -> str:
    """Return a greeting for the supplied name."""
    return f"Hello, {name}!"


def main() -> None:
    """Serve requests over standard input and output."""
    server.run(transport="stdio", show_banner=False)
