# Provide credentials through environment variables

Conda-mcp declarations store environment-variable names. They do not store token values or read live values while rendering or registering a server. Use this guide to make the named variables available at the point where the server or client needs them.

## Find the required names

Inspect the installed declaration:

```sh
conda mcp inspect SERVER -n SERVER_ENV
```

Replace `SERVER` and `SERVER_ENV` with your installed server and source environment. A stdio declaration lists environment variables and whether they are required. An HTTP declaration may name a bearer-token variable and variables for individual headers.

Do not paste live values into the manifest, a rendered snippet, a command argument, or a registration receipt. Use your existing secret manager or environment setup to supply them to the relevant process.

## Local stdio servers

The launch inherits the client's environment, then applies activation for the selected source prefix. Required names must be present after activation. An empty value counts as present, so this check does not prove that a credential is usable.

When a client is started from a terminal, export or inject the variable before starting that client. For GUI clients, use their documented environment or secret-management mechanism. Changing a terminal's environment does not update a client that is already running. Restart the client or its server process after changing inherited values.

Codex entries include name-only `env_vars` for the declared variables. The other stdio adapters use inherited values without writing those values to configuration. Review activation hooks too, since they can modify the server environment and run with your privileges.

## Remote servers

For HTTP, the client resolves credential references and creates the request. The source environment is not activated for the connection. Set variables in the client process, even when you installed the declaration in a different environment.

The adapters render these native references:

| Client | Reference form |
| --- | --- |
| Claude Code and Copilot | `${NAME}` in header values. |
| Cursor | `${env:NAME}` in header values. |
| Kilo, global scope | `{env:NAME}` in header values. |
| Codex | `bearer_token_env_var` and `env_http_headers` contain variable names. |

Kilo project entries cannot forward remote credential references through this adapter. Claude Desktop's file adapter supports local stdio only. See {doc}`connect-a-remote-server` for the registration workflow.

## Check a connection without printing secrets

Render the entry and confirm that it contains variable names or placeholders. Inspect the client's diagnostics for missing-variable or authentication errors, then make a read-only call through that client. Do not print the whole environment to diagnose a missing credential.

A successful registration only confirms that the configuration was accepted by conda-mcp. It does not validate a token, make a network request, or grant client approval. Remote authentication errors must be resolved with the client and service.

To rotate a value without changing its variable name, update it at its source and restart the process that inherits it. The reference in client configuration can stay the same. If the variable name changes, update the packaged declaration and review the resulting registration change.
