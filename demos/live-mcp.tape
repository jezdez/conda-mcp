Set Height 800
Source demos/_settings.tape
Output demos/live-mcp.gif

Hide
Type "source demos/setup.sh"
Enter
Wait+Screen /MCP_DEMO_READY/
Type "clear"
Enter
Sleep 500ms
Show

Type "# Live MCP session: launch, list tools, and call greet"
Enter
Type "conda mcp render -p ../servers fastmcp-example --client claude-code > server.json"
Enter
Wait /\$/
Sleep 1s
Type "# FastMCP starts the declared server and initializes an MCP session"
Enter
Type "../servers/bin/fastmcp list server.json --timeout 30"
Enter
Wait /\$/
Sleep 2s
Type "../servers/bin/fastmcp call server.json greet name=Conda --timeout 30"
Enter
Wait+Screen /Hello, Conda!/
Wait /\$/
Sleep 2s
