# conda-mcp

Discover, run, and configure MCP servers installed in conda environments. Conda installs, updates, and removes the software and its dependencies. `conda mcp` reads package-owned declarations and connects them to native client configuration.

This project is unreleased. Install a locally built `conda-mcp` package into the environment that runs conda. Do not assume the package is available from a public channel. Server packages can live in a separate environment. See the [first-server tutorial](docs/tutorials/first-server.md) and [contributor checks](CONTRIBUTING.md).

```sh
conda mcp list -n servers
conda mcp inspect example -n servers
conda mcp config example -n servers --client codex
conda mcp link example -n servers --client codex --dry-run
conda mcp link example -n servers --client codex
conda mcp status --client codex
conda mcp unlink example --client codex
```

Client configuration defaults to the current project. Use `--global` for user configuration. Claude Code and Copilot share the project `.mcp.json`. Claude Desktop uses user configuration and supports only local stdio entries through this plugin. Kilo JSONC is left untouched. Use `config` if another layer prevents a safe write.

## Package a declaration

Include `share/conda-mcp/servers/<name>.json` as an installed package file. Its name must match the filename. A stdio declaration names a recorded executable and may specify literal arguments and required environment-variable names. Declare runtime dependencies in the conda recipe. The [remote example](examples/remote/recipe.yaml) installs only metadata and does not contact an endpoint.

Local execution runs conda activation hooks and the server with your privileges. Package ownership does not establish trust. Remote connections and approval remain the client's responsibility. The launcher uses POSIX process groups and Windows Job Objects. Native tests establish platform coverage. A cross-platform lockfile only records dependency resolution.

## Try FastMCP

The [FastMCP recipe](examples/fastmcp/recipe.yaml) packages a local `greet` tool. The example checks build and install it, then send protocol requests through `conda mcp run`. From the checkout, build and install it into a dedicated environment:

```sh
rattler-build build -r examples/fastmcp/recipe.yaml -c conda-forge
conda create -n fastmcp-demo -c "./output" -c conda-forge example-fastmcp-server
conda mcp inspect fastmcp-example -n fastmcp-demo
conda mcp config fastmcp-example -n fastmcp-demo --client codex
```

The [Node example](examples/node/recipe.yaml), [manifest-only wrapper](examples/wrapper/recipe.yaml), and [remote declaration](examples/remote/recipe.yaml) exercise other package layouts. Discovery never infers a server from its executable name or contacts an endpoint.
