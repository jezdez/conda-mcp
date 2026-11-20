# First server

Install `conda-mcp` in the environment that provides your `conda` command. This is unreleased software, so use a local build or a development package source rather than a published package name.

With the example recipe checked out and `rattler-build` available, build the local package and create a server environment:

```sh
rattler-build build -r examples/fastmcp/recipe.yaml -c conda-forge
conda create -n servers -c ./output -c conda-forge example-fastmcp-server
```

These commands install a locally built example, not a published server package. From a project directory, use the new environment as the source:

```sh
conda mcp list -n servers
conda mcp inspect fastmcp-example -n servers
conda mcp config fastmcp-example -n servers --client codex
conda mcp link fastmcp-example -n servers --client codex --dry-run
conda mcp link fastmcp-example -n servers --client codex
```

`-n` and `-p` select the source environment that owns the installed declaration. They do not select where client configuration is written. Client configuration is written in the current project by default. Use `--global` only when the client supports a user-level configuration.

Review the package and declaration before linking it. Package ownership records where a declaration came from. It does not make its server trustworthy. A local server runs with your privileges after activation. Client approval and tool permissions remain client policy.

Run a local stdio server in the foreground:

```sh
conda mcp run -n servers fastmcp-example
```

The command forwards protocol bytes between the client and server. An MCP client normally starts it using the generated command. Running it in a terminal waits for protocol input. EOF is delivered to the server, which decides when to exit. The bridge does not force an exit solely because stdin closed.

Inspect and remove the registration independently of the package:

```sh
conda mcp status --client codex
conda mcp unlink fastmcp-example --client codex
```
