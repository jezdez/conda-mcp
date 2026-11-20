Set Height 800
Source demos/_settings.tape
Output demos/use-a-server.gif

Hide
Type "source demos/setup.sh"
Enter
Wait+Screen /MCP_DEMO_READY/
Type "clear"
Enter
Sleep 500ms
Show

Type "# The example package is installed in ../servers"
Enter
Type "conda mcp list -p ../servers"
Enter
Wait /\$/
Sleep 1s
Type "# Review the declaration before registering the server"
Enter
Type "bat ../servers/share/conda-mcp/servers/fastmcp-example.json"
Enter
Wait /\$/
Sleep 2s
Type "clear"
Enter
Type "conda mcp register fastmcp-example -p ../servers --client codex --dry-run"
Enter
Wait /\$/
Sleep 1s
Type "conda mcp register fastmcp-example -p ../servers --client codex"
Enter
Wait /\$/
Sleep 1s
Type "conda mcp registry --client codex"
Enter
Wait /\$/
Sleep 1s
Type "conda mcp unregister fastmcp-example --client codex"
Enter
Wait /\$/
Sleep 1s
