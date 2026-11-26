Set Height 800
Source demos/_settings.tape
Output demos/conda-session.gif

Hide
Type "source demos/setup.sh"
Enter
Wait+Screen /MCP_DEMO_READY/
Type "clear"
Enter
Sleep 500ms
Show

Type "# The tools environment includes the built-in conda server"
Enter
Type "conda mcp list -p ../tools"
Enter
Wait /\$/
Sleep 2s
Type "conda mcp render conda-cli -p ../tools --client claude-code > conda.json"
Enter
Wait /\$/
Sleep 1s
Type "clear"
Enter
Type "# Call conda_info through a real MCP session"
Enter
Type "../servers/bin/fastmcp call conda.json conda_info envs=true json=true --json --timeout 30 > result.json"
Enter
Wait /\$/
Type "# Show the exit status, conda response, and restart flag"
Enter
Type "jq '.structured_content | {exit_code, envs: .parsed_json.envs, restart_required}' result.json"
Enter
Wait+Screen /"exit_code": 0/
Wait /\$/
Sleep 4s

Hide
Type "jq -e '.is_error == false and .structured_content.exit_code == 0 and (.structured_content.parsed_json.envs | length > 0)' result.json > /dev/null"
Enter
Wait /\$/
