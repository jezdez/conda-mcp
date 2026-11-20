Set Height 800
Source demos/_settings.tape
Output demos/inspect.gif

Hide
Type "source demos/setup.sh"
Enter
Wait+Screen /MCP_DEMO_READY/
Type "clear"
Enter
Sleep 500ms
Show

Type "conda mcp inspect fastmcp-example -p ../servers"
Enter
Wait /\$/
Sleep 2s
Type "clear"
Enter
Type "# Render a client entry without changing configuration"
Enter
Type "conda mcp render fastmcp-example -p ../servers --client codex"
Enter
Wait /\$/
Sleep 2s
Type "# Inspection and rendering did not register or launch the server"
Enter
Type "conda mcp registry --client codex"
Enter
Wait /\$/
Sleep 1s
