# Connect a packaged remote server

Use this guide when an installed package declares an HTTPS MCP endpoint. The client connects to that endpoint directly. Conda-mcp supplies configuration from the package's recorded declaration and does not run an HTTP proxy.

You need the endpoint package installed in an existing source environment and a client that supports its transport and authentication. The commands below use `example` in `mcp-servers`. Substitute the name and environment of your real endpoint package.

```{mermaid}
:alt: An installed declaration supplies the endpoint URL and credential-variable names to conda mcp register, which writes native client configuration. The client reads that configuration and receives credential values from its own environment, then connects directly to the remote MCP server over HTTPS.
:caption: Registration supplies connection details. The client makes the HTTPS connection.

flowchart TB
    accTitle: Registering and connecting to a remote MCP server
    accDescr: An installed declaration supplies the endpoint URL and credential-variable names to conda mcp register, which writes native client configuration. The client reads that configuration and receives credential values from its own environment, then connects directly to the remote MCP server over HTTPS.
    declaration["Installed declaration<br/>URL and credential-variable names"]
    register["conda mcp register"]
    config["Native client configuration"]
    credentials["Client environment<br/>Credential values"]
    client["MCP client"]
    remote["Remote MCP server"]
    declaration --> register --> config --> client
    credentials --> client
    client <-->|HTTPS MCP| remote
```

## Review the endpoint

```sh
conda mcp list -n mcp-servers
conda mcp inspect example -n mcp-servers
conda mcp render example -n mcp-servers --client codex
```

Check the package owner, endpoint URL, and credential-variable names before granting the client access. None of these commands contacts the endpoint. An HTTP declaration cannot be launched with `conda mcp run`.

The repository's `examples/remote` package points to `https://example.invalid/mcp`. It is a configuration fixture, not a working remote service. To package your own endpoint, use {doc}`package-a-remote-server`.

## Supply credentials to the client

If the declaration names bearer or header variables, make those values available to the client process before connecting. Follow {doc}`provide-credentials` for environment handling. For remote entries, conda-mcp does not activate the source environment to obtain credentials.

| Client target | Remote declaration support in this adapter |
| --- | --- |
| `codex` | URL and named bearer/header references in TOML. |
| `claude-code`, `copilot` | HTTP entries with environment references. |
| `cursor` | URL and headers with environment references. |
| `kilo` | Remote entries. Credential references require explicit global scope. |
| `claude-desktop` | Unsupported through this adapter's local-stdio configuration file. |

Client versions, authentication support, and approval settings still determine whether a connection succeeds. The adapter's configuration support is not a claim that every client accepts every endpoint.

## Register and connect

Preview the project entry, then write it:

```sh
conda mcp register example -n mcp-servers --client codex --dry-run
conda mcp register example -n mcp-servers --client codex
```

Reload the client configuration and approve the endpoint according to the client's controls. Use that client to initialise a session, list tools, and make a suitable read-only call. Registration alone cannot confirm authentication or server availability.

For a user-level entry, add `--global` to preview and registration. For credential-bearing Kilo entries, use `--client kilo --global`. If Kilo layer checks prevent a safe write, render the global snippet and use the client's own configuration process.

## Disconnect

Stop the connection in the client, then remove the selected registration:

```sh
conda mcp unregister example --client codex --dry-run
conda mcp unregister example --client codex
```

This preserves the installed declaration package. Revoke credentials at the remote service separately if they should no longer be usable.
