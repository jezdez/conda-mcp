# conda-mcp

Discover, run, and configure MCP servers installed in conda environments. Conda installs, updates, and removes the software and its dependencies. `conda mcp` reads package-owned declarations and connects them to native client configuration. `conda mcp serve` exposes the installation that launched it through MCP. The conda package records a `conda-cli` declaration for that server.

This project is unreleased. Install a locally built `conda-mcp` package into the environment that runs conda. Do not assume the package is available from a public channel. Server packages can live in a separate environment. See the [first-server tutorial](docs/tutorials/first-server.md) and [contributor checks](CONTRIBUTING.md).

Watch the [terminal demos](docs/demos.md) for declaration review and project-local client registration, with text equivalents for each recording.

```sh
conda mcp list -n servers
conda mcp inspect example -n servers
conda mcp render example -n servers --client codex
conda mcp register example -n servers --client codex --dry-run
conda mcp register example -n servers --client codex
conda mcp serve
conda mcp registry --client codex
conda mcp unregister example --client codex
```

Client configuration defaults to the current project. Use `--global` for user configuration. Claude Code and Copilot share the project `.mcp.json`. Claude Desktop uses user configuration and supports only local stdio entries through this plugin. Kilo JSONC is left untouched. Use `render` to generate a native client snippet when another layer prevents a safe write. It is not a portable environment export.

## Package a declaration

Include `share/conda-mcp/servers/<name>.json` as an installed package file. Its name must match the filename. A stdio declaration names a recorded executable and may specify literal arguments and required environment-variable names. Declare runtime dependencies in the conda recipe. The [remote example](examples/remote/recipe.yaml) installs only metadata and does not contact an endpoint.

Local execution runs conda activation hooks and the server with your privileges. Package ownership does not establish trust. Remote connections and approval remain the client's responsibility. The launcher uses POSIX process groups and Windows Job Objects. Native tests establish platform coverage. A cross-platform lockfile only records dependency resolution.

## Try FastMCP

The [FastMCP recipe](examples/fastmcp/recipe.yaml) packages a local `greet` tool. The example checks build and install it, then send protocol requests through `conda mcp run`. From the checkout, build and install it into a dedicated environment:

```sh
rattler-build build -r examples/fastmcp/recipe.yaml -c conda-forge
conda create -n fastmcp-demo -c "./output" -c conda-forge example-fastmcp-server
conda mcp inspect fastmcp-example -n fastmcp-demo
conda mcp render fastmcp-example -n fastmcp-demo --client codex
```

The [Node example](examples/node/recipe.yaml), [manifest-only wrapper](examples/wrapper/recipe.yaml), and [remote declaration](examples/remote/recipe.yaml) exercise other package layouts. Discovery never infers a server from its executable name or contacts an endpoint.
