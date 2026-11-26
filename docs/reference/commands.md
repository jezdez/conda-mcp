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
| `serve` | Its own installation | No |

`render`, `register`, `unregister`, and `registry` use the current directory by default. `render` generates a native client snippet, not a portable environment export. `--global` selects a user configuration only for supported clients. Claude Code and Copilot share the project `.mcp.json` format. Claude Desktop accepts a global local-stdio registration only. Each client has its own approval and trust policy. Registration does not grant trust or permission to invoke tools.

`--package PACKAGE` on `run` requires exact equality with the normalised name of the package owning the manifest. It is not a MatchSpec and does not identify the executable's dependency package. Put extra literal server arguments after `--`, for example `conda mcp run -n servers example -- --verbose`.

Source selection defaults to the active environment. On `run`, `render`, and `register`, manager options may appear before or after `SERVER`, but must precede `--`. All arguments after that separator belong to the stdio server, including strings matching manager options. Extra server arguments without the separator are rejected.

`render` and `register` append those arguments after the packaged declaration's arguments. A repeated registration replaces the previous additional arguments, and omitting them restores the packaged defaults. The complete generated entry is covered by the registration receipt. HTTP declarations reject startup arguments.

On Windows, `run` requires Windows 10 or Windows Server 2016 or newer and pywin32 >=311. Launch metadata and arguments must fit within `cmd.exe`'s 8,191-character environment limit. Oversized payloads fail before activation starts. The activation wrapper is assigned to its Job Object during process creation. Unsupported containment fails without an uncontained fallback.

`--json` emits one JSON result for administrative commands. It does not wrap protocol streams from `run`.

(serve-options)=
## Serve

`conda mcp serve` exposes the conda installation that launched it over MCP on stdio. It reads that installation's command catalogue and plugin metadata at startup, then serves until the client closes the stream. It is not a client command and it does not write client configuration.

```{program} conda mcp serve
```

```{option} --timeout <seconds>
Upper bound for one conda command. Default: `900` seconds. The value must be finite and greater than zero.
```

```{option} --output-limit-bytes <bytes>
Bytes retained per output stream. Default: `1048576`. Later bytes are drained, not kept. The value must be a positive integer.
```

```{option} --stdin-limit-bytes <bytes>
Accepted UTF-8 input bytes. Default: `1048576`. The value must be a positive integer.
```

```{option} --allow-write
Enables conda operations classified as changes to environments or files. Disabled by default.
```

```{option} --allow-exec
Enables raw `conda_execute` and arbitrary argv execution. Disabled by default. Processes launched with this permission run with the user's privileges.
```

```{option} --version
Prints the conda-mcp version and exits.
```

`serve` does not accept a source-prefix selector, `--conda-exe`, or an administrative JSON envelope. Use {doc}`../how-to/configure-serving` for client configuration and {doc}`mcp-interface` for tools, resources, and result fields.

Read-only conda commands are callable by default. Mutations need `--allow-write`, and raw execution needs `--allow-exec`. Enabling execution does not grant write permission. Server policy is fixed at startup and enforced on each call, independent of the annotations a client displays. The server excludes itself from the generated tool list, so a client cannot start another long-lived server through a generated tool.

`serve` resolves conda from the running interpreter's installation prefix. An inherited `CONDA_EXE` or a different conda on `PATH` does not change which installation it serves. To expose a different installation, use that installation's Python launcher. Use `python -I -m conda_mcp._stdio serve` for an MCP client so plugin startup output cannot enter its protocol stream.

On Windows, command execution through `serve` has the same operating-system and pywin32 requirements as `run`. Commands start suspended, are assigned to a Job Object, then resume. Output draining continues until EOF or the command timeout, including when a descendant holds a pipe open after the root exits. See [Lifecycle and safety](../explanation/lifecycle.md) for cleanup behaviour and the remaining owner-death limitation during suspended creation.

The conda package installs a `conda-cli` declaration at `share/conda-mcp/servers/conda-cli.json`. `list` and `inspect` show it like any package-owned server. `register` writes the same entry shape it writes for every packaged server, and that entry runs the direct Python launcher from the prefix. A wheel install has no conda package record, so discovery does not advertise the declaration.

(native-destinations)=
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

`registry` without `--client` already lists all supported targets in the selected scope. `--all` is optional.

See {doc}`registrations` for every state and the JSON result fields. {doc}`../how-to/recover-registrations` gives the recovery steps for edited entries, missing packages, and interrupted writes.

## Conflicts and recovery

`register --dry-run` validates the source and destination and previews the generated entry without creating a directory, lock, or receipt. `unregister --dry-run` previews removal. Ordinary unregister only removes an unchanged receipted entry. `unregister --force` can remove an edited or unmanaged selected entry, but cannot bypass malformed files, redirected paths, or ambiguous recovery. No command deletes package files.

Receipts are adjacent files named `<config-filename>.conda-mcp.json`. Keep the receipt with its config: a matching entry without a receipt is unmanaged. Interrupted mutations retain an intent containing before/after fingerprints. The next mutation checks the actual current entry before finalising or rolling back receipt state. It never restores a stale whole-config snapshot.

## Credential references

Generated stdio entries inherit the client's environment. Codex also receives name-only `env_vars`. No live value is copied into configuration. HTTP bearer/header names become native references: `${NAME}` for Claude Code and Copilot, `${env:NAME}` for Cursor, `{env:NAME}` for trusted global Kilo, and name-based Codex fields. Kilo project remote credentials and Claude Desktop remote file entries are unsupported.

Use {doc}`../how-to/provide-credentials` to supply those variables, and {doc}`../how-to/connect-a-remote-server` to register an HTTPS declaration.

Client format evidence comes from the [portable MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration), [Claude Code](https://code.claude.com/docs/en/mcp), [Codex](https://developers.openai.com/codex/extend/mcp), [Cursor](https://cursor.com/docs/mcp), and [Claude Desktop's local-server guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers). Kilo compatibility and layer behaviour were checked against [source revision `bd8b98ae`](https://github.com/Kilo-Org/kilocode/tree/bd8b98aeab348c08221a836ba091b855a62814e9). These references establish configuration syntax, not an end-to-end client acceptance test.
