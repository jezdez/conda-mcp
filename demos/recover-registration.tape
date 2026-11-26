Set Height 800
Source demos/_settings.tape
Output demos/recover-registration.gif

Hide
Type "source demos/setup.sh"
Enter
Wait+Screen /MCP_DEMO_READY/
Type "clear"
Enter
Sleep 500ms
Show

Type "conda mcp register fastmcp-example -p ../servers --client codex"
Enter
Wait /\$/
Type "conda mcp registry --client codex"
Enter
Wait+Screen /managed/
Wait /\$/
Sleep 2s
Type "clear"
Enter
Type "# Back up the entry and receipt before editing"
Enter
Type "cp .codex/config.toml config.backup.toml"
Enter
Type "cp .codex/config.toml.conda-mcp.json receipt.backup.json"
Enter
Type "printf '\nstartup_timeout_sec = 60\n' >> .codex/config.toml"
Enter
Type "conda mcp registry --client codex"
Enter
Wait+Screen /edited/
Wait /\$/
Sleep 3s
Type "clear"
Enter
Type "# Preview removal of the edited entry, then replace it"
Enter
Type "conda mcp unregister fastmcp-example --client codex --force --dry-run"
Enter
Wait /\$/
Sleep 2s
Type "conda mcp unregister fastmcp-example --client codex --force"
Enter
Wait /\$/
Type "conda mcp register fastmcp-example -p ../servers --client codex"
Enter
Wait /\$/
Type "conda mcp registry --client codex"
Enter
Wait+Screen /managed/
Wait /\$/
Sleep 3s

Hide
Type `conda mcp registry --client codex --json | jq -e '.[0].state == "managed" and .[0].source_state == "current"' > /dev/null`
Enter
Wait /\$/
