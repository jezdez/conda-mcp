# MCP interface

`conda mcp serve` provides generated command tools, an optional raw argv tool, an optional completion-metadata tool, and the `conda://capabilities` resource. Its server name in the MCP initialisation response is `conda-mcp`.

This page describes the built-in conda server. Servers launched through `conda mcp run` define their own tools and resources.

(generated-tools)=
## Generated command tools

Each representable terminal command in conda's startup parser receives a tool. Names begin with `conda_` and join the canonical command path with underscores, for example `conda_info` and `conda_env_create`. Aliases are metadata on the canonical tool. Names containing unsupported characters, exceeding the MCP length limit, or colliding with another command receive a deterministic hash suffix.

Input schemas describe supported argparse actions: scalar values, booleans, counts, repeated options, arrays, choices, positionals, mutually exclusive groups, and nested commands. Options inherited from parent commands keep their command scope. Repeated property names receive numeric suffixes. The schema returned by `tools/list` is authoritative for the installed parser.

For example, a JSON-formatted conda information request is a call to `conda_info` with:

```json
{"json": true}
```

An omitted property leaves that argument out of argv, allowing conda to apply its defaults. For an option with `nargs="?"`, a supplied `null` emits the flag without a value. Counts emit repeated flags. Append actions accept an array of occurrences, with nested arrays when each occurrence takes multiple values.

Generated string positionals reject values beginning with `-`, except for an opaque remainder. Unsupported parser actions make the affected command raw-only and add a catalogue diagnostic. Raw argv can express these commands when enabled. Greedy plugin parsers may instead expose an explicit passthrough array.

Generated tools include canonical-path and alias metadata. Their annotations describe read-only, destructive, idempotent, and open-world behaviour. Mutation tools remain listed when writes are disabled. Server policy checks each invocation before starting conda, independently of client annotations.

The manager's `list`, `inspect`, `render`, `register`, `unregister`, and `registry` commands can appear as generated tools. The `run` and `serve` commands start stdio servers, so they are excluded from generated tools.

## Raw argv tool

`conda_execute` is listed only with `--allow-exec`.

| Input | Type | Required | Meaning |
| --- | --- | --- | --- |
| `argv` | Array of strings | Yes | Tokens after the conda executable. |
| `cwd` | String | No | Existing working directory for the child. |
| `stdin` | String | No | Noninteractive input, bounded by its UTF-8 byte length. |
| `timeout_seconds` | Positive number | No | Timeout no greater than the server's configured limit. |

Unknown properties are rejected. The executable receives argv directly, without shell expansion, pipes, redirection, or shell functions. A raw read-only request has this shape:

```json
{"argv": ["info", "--json"], "timeout_seconds": 30}
```

Raw argv still passes through permission checks. Enabling this tool does not enable mutations. See {doc}`../how-to/enable-operations` for the combinations.

(capabilities-resource)=
## Capabilities resource

`conda://capabilities` is an immutable JSON snapshot from startup.

| Field | Meaning |
| --- | --- |
| `conda_executable` | Resolved executable belonging to the invoking conda installation. |
| `conda_version` | Version of that conda installation. |
| `catalog` | Command tree, arguments, aliases, and discovery diagnostics. |
| `generated_tools` | Canonical structured tool names. |
| `plugins` | External conda entry-point distributions, versions, values, and detected hooks. |
| `discovery_fingerprint` | Digest of the startup conda version and plugin metadata, including detected hooks. |

The catalogue may contain diagnostics even when the server starts successfully. It does not include credentials, authentication objects, request headers, or complete process environments. Executable paths and installed plugin metadata are visible to the connected client.

`conda-cli-mcp` used `target_executable` for the executable field. Consumers migrating to this server must use `conda_executable`.

(completion-metadata)=
## Completion metadata tool

`conda_cli_command` is listed when the startup plugin inventory contains `conda-completion`. Reading its metadata requires conda-completion 0.3 or newer with the public manifest API. The tool reads the existing `completion.msgpack` and does not generate or update it.

Its optional `command_path` is an array of command tokens without the executable. An empty array selects the root. Tokens must be nonempty, contain no whitespace, and not begin with `-`.

```json
{"command_path": ["env", "list"]}
```

| Result field | Meaning |
| --- | --- |
| `availability` | `available`, `not_installed`, `not_generated`, or `unavailable`. |
| `requested_command_path` | Tokens submitted by the client. |
| `resolved_command_path` | Path after executable-alias resolution, or null. |
| `alias_target` | Expanded alias target, or null. |
| `command` | Options, positionals, direct subcommands, exclusive groups, and summary, or null. |
| `manifest` | Format version, generation time, plugin hashes, staleness, completion version, and runtime-source definitions, or null. |
| `hint` | Suggested recovery action when metadata is unavailable, otherwise null. |

Options and positionals carry conda-completion's completion types and rules. Package-name and package-version caches are not returned. The manifest's `stale` flag compares registered plugin entry-point names. It cannot detect an update that keeps the same names or every conda parser change. A missing cache reports `not_generated` with a hint to run `conda completion generate` in the served installation. Unknown command paths are invalid input.

The tool is read-only and needs neither permission flag. Completion results use their own schema, not the command-execution fields below.

(execution-results)=
## Command execution results

Generated commands and `conda_execute` share this structured result:

| Field | Type | Meaning |
| --- | --- | --- |
| `exit_code` | Integer or null | Child exit status, or null when no completed exit status is reported. |
| `stdout` | String | Retained standard output. |
| `stderr` | String | Retained standard error. |
| `duration_ms` | Integer | Elapsed execution time in milliseconds. |
| `parsed_json` | JSON value or null | Stdout decoded only when it is one complete JSON document and was not truncated. |
| `timed_out` | Boolean | The command exceeded its timeout. |
| `cancelled` | Boolean | Internal cancellation state, normally false for a completed MCP call. |
| `stdout_truncated` | Boolean | Stdout exceeded its retained-byte limit. |
| `stderr_truncated` | Boolean | Stderr exceeded its retained-byte limit. |
| `restart_required` | Boolean | The server has detected a need to refresh its startup catalogue. |

The MCP response carries these fields in `structuredContent`. Text content includes a short summary and a serialised copy for clients without structured-content support. A nonzero exit status, timeout, or cancellation state marks the tool result as an error. `stdout` remains available when `parsed_json` is populated. A JSON `null` result and an unparsed result both have `parsed_json: null`.

Output streams are drained after their retention limits are reached. UTF-8 truncation preserves complete characters. Conda executions are serialised within one server process.

After a successful operation classified as a write or execution, a child Python process checks the installed conda version and plugin hooks against the startup fingerprint. The live MCP server does not import the updated plugin code. A changed fingerprint, or a failed check, sets `restart_required`. Once set, it remains true for subsequent results. Tool lists and the capabilities resource do not refresh in place. See {doc}`../how-to/refresh-plugin-tools`.

## Errors and cancellation

Invalid tool input produces an MCP invalid-parameters error identifying the JSON path without echoing the submitted value. Policy errors name the missing startup option. Invalid execution settings, unknown tools, and unknown resources produce protocol errors rather than successful execution results.

On request cancellation, the server terminates the command tree and propagates cancellation. The cancelled request normally has no tool result. A timeout returns a timed-out result after process cleanup, unless cleanup itself fails. Process cleanup guarantees and platform limitations are described in {doc}`../explanation/lifecycle`.
