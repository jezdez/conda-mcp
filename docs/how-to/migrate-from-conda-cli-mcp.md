# Migrate from conda-cli-mcp

`conda-cli-mcp` provided an MCP server for a conda installation through a `ccm` console script and a bare `conda mcp` launcher. Both now live in `conda-mcp` as `conda mcp serve`. The old package and the new one cannot share an environment, because both register the `mcp` subcommand and conda rejects duplicate names.

## Command mapping

| Old invocation | New invocation |
| --- | --- |
| `ccm --allow-write` | Register `conda-cli` with `-- --allow-write`, or use that installation's Python with `-I -m conda_mcp._stdio serve --allow-write` |
| `ccm --conda-exe /path/to/conda` | Use the selected installation's Python launcher |
| `conda mcp --allow-write` (conda-cli-mcp 0.2.0) | Register `conda-cli` with `-- --allow-write` |

The direct `serve` launcher uses the installation that supplies its Python interpreter, so there is no path override. To expose a second installation, configure a separate client entry using its Python interpreter.

## What stays the same

The MCP surface for conda commands keeps its shape. Generated tool names such as `conda_env_create` are unchanged. The `conda_execute` tool, the optional completion-metadata tool, and the `conda://capabilities` resource remain. Execution results keep the fields clients relied on, including `exit_code`, `stdout`, `stderr`, `duration_ms`, `parsed_json`, `timed_out`, `cancelled`, both truncation flags, and `restart_required`.

Defaults are unchanged. Commands that only read are callable without extra flags. Mutations need `--allow-write`, and raw execution needs `--allow-exec`. Execution does not grant write permission.

## What changed

The initialisation response now names the server `conda-mcp`. The capabilities resource renamed `target_executable` to `conda_executable`. Update clients or scripts that read the old field. The complete field definitions are in {doc}`../reference/mcp-interface`.

Discovery now runs in the invoking conda process. The old standalone server could select a different installation and discover it through a helper process. Follow {doc}`configure-serving` to configure one entry per installation using the current launch model.

The command catalogue now includes the manager's own commands, because they are part of the same conda installation. Clients can call `conda_mcp_list`, `conda_mcp_inspect`, `conda_mcp_render`, `conda_mcp_register`, `conda_mcp_unregister`, `conda_mcp_registry`, and `conda_mcp_run`. Registration and unregistration count as writes. Launching a packaged server counts as execution. `conda mcp serve` is never offered as a generated tool, so a client cannot start another long-lived server through the catalogue.

## Migration steps

1. Save a private copy of the old client entry and stop its server through the client.
2. Choose the conda installation to expose. If reusing the old environment, remove `conda-cli-mcp` with the installer that owns it before installing conda-mcp. Do not use pip to remove a conda-owned package. A fresh environment can be prepared without changing the old one.
3. Build and install the development conda-mcp package following {doc}`install`. This project is unreleased, so do not assume a public package is available.
4. Update the client entry to use the intended installation's absolute Python executable with `-I -m conda_mcp._stdio serve`, or register its packaged `conda-cli` declaration. Remove `--conda-exe` and preserve only the permission and limit options you still need. Use {doc}`configure-serving` for JSON and TOML examples.
5. Start the new entry and follow {doc}`../tutorials/first-conda-session` to verify the served installation and a read-only call. If mutations are needed, configure them with {doc}`enable-operations` and test against a disposable target environment.
6. Remove the obsolete client entry and retire the old environment only after the replacement works. Keep any environment still used for other tasks.

Removing `conda-mcp` from an environment whose conda is running the removal needs an outside conda, because conda protects its own installation. Run the removal from another environment's conda, for example `conda remove -p /path/to/env conda-mcp`.

The conda recipe declares a constraint that excludes the published `conda-cli-mcp` versions, so a solve cannot install both. Pip has no equivalent, so removal stays manual there.
