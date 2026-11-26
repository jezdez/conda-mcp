# Refresh tools after plugin changes

Restart `conda mcp serve` after installing, removing, or updating a plugin in the installation it serves. The generated tools and `conda://capabilities` are startup snapshots.

## Check which installation changed

Read `conda://capabilities` and inspect `conda_executable`. Plugin commands must be installed alongside that conda to join its catalogue. Installing a plugin in an environment merely targeted by a tool's `--name` or `--prefix` does not change the server's own parser.

If tools are unexpectedly missing, inspect the resource's `catalog` diagnostics. An unsupported argparse action can make a command raw-only. A parser or plugin import failure may also leave diagnostics. Restarting does not repair an incompatible plugin.

## Respond to a restart request

After a successful write or execution, a tool result may contain:

```json
{"restart_required": true}
```

This is one field of the full execution result. It means the server detected changed conda or plugin metadata, or could not inspect that metadata after the operation. The flag stays set until the server is replaced. Its tool list does not change in place.

1. Stop the server using the client's server controls.
2. Start it with the same executable and intended permission options.
3. List its tools again.
4. Read `conda://capabilities` and check `conda_executable`, `plugins`, and `discovery_fingerprint` against the installation you changed.
5. Make a read-only call such as `conda_info` to confirm the new session works.

A false `restart_required` is not a background health check. Changes made outside the server may not have been inspected. Restart after those changes too. Passing `--no-plugins` to one raw conda command changes that child process, not the startup catalogue.

## Refresh completion hints separately

If `conda_cli_command` reports `not_generated`, generate the cache in the served installation:

```sh
python -I -m conda completion generate
```

This command requires conda-completion with the public manifest API. Use version 0.3 or newer. When metadata is reported as unavailable or stale, follow its `hint` and query the tool again after repairing or regenerating the cache.

Installing conda-completion requires an MCP server restart before its metadata tool appears. Updating an existing cache does not rebuild the generated argparse tool catalogue. See {doc}`../reference/mcp-interface` for the availability states and the limits of the cache's staleness check.
