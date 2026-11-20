"""Call the packaged server through a real stdio connection."""

import asyncio
import shutil

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def main() -> None:
    """Verify the installed launcher and greeting tool."""
    command = shutil.which("example-fastmcp")
    assert command is not None
    async with Client(StdioTransport(command=command, args=[]), timeout=15) as client:
        result = await client.call_tool("greet", {"name": "Conda"})
        assert result.content[0].text == "Hello, Conda!"


if __name__ == "__main__":
    asyncio.run(main())
