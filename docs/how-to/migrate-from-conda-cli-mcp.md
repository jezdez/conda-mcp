# Migrate from conda-cli-mcp

`conda-cli-mcp` provided an MCP server for a conda installation through a `ccm` console script and a bare `conda mcp` launcher. Both now live in `conda-mcp` as `conda mcp serve`. The old package and the new one cannot share an environment, because both register the `mcp` subcommand and conda rejects duplicate names.

## Command mapping

| Old invocation | New invocation |
| --- | --- |
| `ccm --allow-write` | `conda mcp serve --allow-write` |
| `ccm --conda-exe /path/to/conda` | Launch that installation's own `conda mcp serve` |
| `conda mcp --allow-write` (conda-cli-mcp 0.2.0) | `conda mcp serve --allow-write` |

`conda mcp serve` always serves the installation that launched it, so there is no path override. To expose a second installation, run that installation's `conda mcp serve`.

## What stays the same

The MCP surface for conda commands keeps its shape. Generated tool names such as `conda_env_create` are unchanged. The `conda_execute` tool, the optional completion-metadata tool, and the `conda://capabilities` resource remain. Execution results keep the fields clients relied on, including `exit_code`, `stdout`, `stderr`, `duration_ms`, `parsed_json`, `timed_out`, `cancelled`, both truncation flags, and `restart_required`.

Defaults are unchanged. Commands that only read are callable without extra flags. Mutations need `--allow-write`, and raw execution needs `--allow-exec`. Execution does not grant write permission.

## What changed

The initialization response now names the server `conda-mcp`. The capabilities resource still reports the served conda executable in `target_executable`.

The command catalog now includes the manager's own commands, because they are part of the same conda installation. Clients can call `conda_mcp_list`, `conda_mcp_inspect`, `conda_mcp_render`, `conda_mcp_register`, `conda_mcp_unregister`, `conda_mcp_registry`, and `conda_mcp_run`. Registration and unregistration count as writes. Launching a packaged server counts as execution. `conda mcp serve` is never offered as a generated tool, so a client cannot start another long-lived server through the catalog.

## Migration steps

1. Install the released `conda-mcp` package into the environment that runs conda. Do not install it next to `conda-cli-mcp`.
2. Stop any client process using the old server.
3. Remove `conda-cli-mcp` with the installer that owns it. Do not use pip on a conda-owned package.
4. Update the client entry to run `conda mcp serve` with the flags it used before.
5. Verify a read-only call, then a mutation under `--allow-write` if you relied on one.
6. Remove the old environment or configuration once the new entry works.

Removing `conda-mcp` from an environment whose conda is running the removal needs an outside conda, because conda protects its own installation. Run the removal from another environment's conda, for example `conda remove -p /path/to/env conda-mcp`.

The conda recipe declares a constraint that excludes the published `conda-cli-mcp` versions, so a solve cannot install both. Pip has no equivalent, so removal stays manual there.
