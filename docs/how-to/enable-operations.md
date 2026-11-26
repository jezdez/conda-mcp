# Enable write and execution operations

Use this guide when a client can see a conda tool but its call is rejected because the server requires `--allow-write` or `--allow-exec`. The client must launch the built-in server with those options. Approving a call in the client does not change server policy.

Start from a working connection described in {doc}`configure-serving`. The examples update a managed Codex entry for the built-in server installed in `base`:

```sh
conda activate base
```

## Allow conda mutations

Register the server with {option}`conda mcp serve --allow-write` after `--`:

```sh
conda mcp register conda-cli --client codex -- --allow-write
```

This permits operations classified as changes to environments, packages, configuration, caches, and files. It also permits the manager's registration and unregistration commands. Without the flag, generated mutation tools remain visible but execution is rejected.

For a manually configured direct `serve` entry using a Python executable, the arguments become:

```json
["-I", "-m", "conda_mcp._stdio", "serve", "--allow-write"]
```

Restart the server through the client after updating its registration. Listing tools alone cannot confirm that write permission changed, because mutation tools are listed in both modes. Confirm the startup arguments in the client before attempting a mutation in a disposable environment.

## Allow raw argv or subprocesses

Add {option}`conda mcp serve --allow-exec` when the client needs `conda_execute`, `conda run`, or a generated command accepting opaque passthrough arguments:

```sh
conda mcp register conda-cli --client codex -- --allow-exec
```

After restarting, list tools and confirm that `conda_execute` appears. A read-only raw call can then use:

```json
{"argv": ["info", "--json"]}
```

:::{admonition} Execution runs with your privileges
:class: warning

Programs launched with execution permission can modify files even when `--allow-write` is off. The flags are not an operating-system sandbox.
:::

## Choose the required combination

| Operation | Startup options |
| --- | --- |
| Generated known read-only command | None. |
| Generated mutation | `--allow-write`. |
| Recognised dry-run form | No write flag needed. Any independent execution requirement still applies. |
| Generated `conda run` or `conda mcp run` | `--allow-exec`. |
| Raw known read-only argv | `--allow-exec`. |
| Raw mutation or unknown argv | `--allow-exec` and `--allow-write`. |
| Opaque plugin passthrough classified as a mutation | `--allow-exec` and `--allow-write`. |

For both permissions:

```sh
conda mcp register conda-cli --client codex -- --allow-write --allow-exec
```

An export to stdout and an export to a file can require different permissions. A dry-run spelling is recognised only for supported command forms. Use the error's missing-option names and the discovered tool schema when diagnosing a rejected request.

## Update startup arguments

`register` records the arguments as part of the managed entry. Repeat it with the complete set of startup arguments you want. For example, to permit writes and set a shorter timeout:

```sh
conda mcp register conda-cli --client codex -- --allow-write --timeout 120
```

Omitting startup arguments restores the packaged defaults, including read-only mode. Use `--dry-run` before the separator to preview a change. `render` accepts the same arguments if you need a snippet for manual configuration. HTTP declarations do not accept startup arguments.

If you previously edited the configuration by hand, follow {doc}`recover-registrations` before replacing it. Do not edit an installed package's manifest to change policy. Supply credentials through {doc}`provide-credentials`, never through arguments stored in client configuration.
