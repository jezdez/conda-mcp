# Command reference

`conda mcp` has six supported client targets: `claude-code`, `copilot`, `codex`, `kilo`, `claude-desktop`, and `cursor`.

| Command | Source prefix | Writes configuration |
| --- | --- | --- |
| `list` | `-n NAME` or `-p PREFIX` | No |
| `inspect SERVER` | `-n NAME` or `-p PREFIX` | No |
| `render SERVER --client CLIENT` | `-n NAME` or `-p PREFIX` | No |
| `register SERVER --client CLIENT` | `-n NAME` or `-p PREFIX` | Yes |
| `unregister SERVER --client CLIENT` | No | Yes |
| `registry` | No | No |
| `run SERVER` | `-n NAME` or `-p PREFIX` | No |

`render`, `register`, `unregister`, and `registry` use the current directory by default. `render` generates a native client snippet, not a portable environment export. `--global` selects a user configuration only for supported clients. Claude Code and Copilot share the project `.mcp.json` format. Claude Desktop accepts a global local-stdio registration only. Each client has its own approval and trust policy. Registration does not grant trust or permission to invoke tools.

`--package PACKAGE` on `run` requires exact equality with the normalized name of the package owning the manifest. It is not a MatchSpec and does not identify the executable's dependency package. Put extra literal server arguments after `--`, for example `conda mcp run -n servers example -- --verbose`.

On Windows, launch metadata and arguments must fit within `cmd.exe`'s 8,191-character environment limit. Oversized payloads fail before activation starts.

`--json` emits one JSON result for administrative commands. It does not wrap protocol streams from `run`.

## Native destinations

| Client | Current project | Explicit `--global` |
| --- | --- | --- |
| Claude Code | `.mcp.json` | `~/.claude.json` |
| Copilot | `.mcp.json` | `$COPILOT_HOME/mcp-config.json`, or `~/.copilot/mcp-config.json` |
| Codex | `.codex/config.toml` | `$CODEX_HOME/config.toml`, or `~/.codex/config.toml` |
| Kilo | `.kilo/kilo.json` | `$XDG_CONFIG_HOME/kilo/kilo.json`, or `~/.config/kilo/kilo.json` |
| Cursor | `.cursor/mcp.json` | `~/.cursor/mcp.json` |
| Claude Desktop | Unsupported | macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`, Windows: `%APPDATA%/Claude/claude_desktop_config.json`, Linux: `~/.config/Claude/claude_desktop_config.json` |

The project is the explicit current directory. Running from home does not substitute for `--global`. Home override variables must contain absolute paths. Claude Code and Copilot share one project config and receipt, so changing either affects both.

Kilo layers containing comments or trailing commas cannot be safely inspected without a JSONC parser. `register` and `unregister` refuse to change entries when those layers prevent collision checks. Use `conda mcp render` to generate the native snippet instead. `registry` reads the selected strict-JSON target and its receipts, without checking competing layers or reporting Kilo's effective configuration.

`registry --all` lists local client registrations in the selected scope and reports a shared path once. It does not query the official MCP Registry or check client or server health. Each row includes registration `state` and receipt-source `source_state`.

## Conflicts and recovery

`register --dry-run` validates the source and destination and previews the generated entry without creating a directory, lock, or receipt. `unregister --dry-run` previews removal. Ordinary unregister only removes an unchanged receipted entry. `unregister --force` can remove an edited or unmanaged selected entry, but cannot bypass malformed files, redirected paths, or ambiguous recovery. No command deletes package files.

Receipts are adjacent files named `<config-filename>.conda-mcp.json`. Keep the receipt with its config: a matching entry without a receipt is unmanaged. Interrupted mutations retain an intent containing before/after fingerprints. The next mutation checks the actual current entry before finalizing or rolling back receipt state. It never restores a stale whole-config snapshot.

## Credential references

Generated stdio entries inherit the client's environment. Codex also receives name-only `env_vars`. No live value is copied into configuration. HTTP bearer/header names become native references: `${NAME}` for Claude Code and Copilot, `${env:NAME}` for Cursor, `{env:NAME}` for trusted global Kilo, and name-based Codex fields. Kilo project remote credentials and Claude Desktop remote file entries are unsupported.

Client format evidence comes from the [portable MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration), [Claude Code](https://code.claude.com/docs/en/mcp), [Codex](https://developers.openai.com/codex/extend/mcp), [Cursor](https://cursor.com/docs/mcp), and [Claude Desktop's local-server guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers). Kilo compatibility and layer behavior were checked against [source revision `bd8b98ae`](https://github.com/Kilo-Org/kilocode/tree/bd8b98aeab348c08221a836ba091b855a62814e9). These references establish configuration syntax, not an end-to-end client acceptance test.
