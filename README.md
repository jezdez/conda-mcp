# conda-mcp

Discover, run, and configure MCP servers installed in conda environments. Conda installs, updates, and removes the software and its dependencies. `conda mcp` reads package-owned declarations and connects them to native client configuration. `conda mcp serve` exposes the installation that launched it through MCP. The conda package records a `conda-cli` declaration for that server.

This project requires Python 3.11 or newer and conda 26.10 or newer on linux-64, osx-arm64, or win-64. It is unreleased. Install a locally built `conda-mcp` package into the environment that runs conda. Server packages can live in a separate environment. See the [installation guide](docs/how-to/install.md) and [contributor checks](CONTRIBUTING.md).

Watch the [terminal demos](docs/demos.md) for declaration review and project-local client registration, with text equivalents for each recording.

Choose a starting point:

- [Call conda through MCP](docs/tutorials/first-conda-session.md) to discover conda tools and make a read-only call.
- [Connect a packaged server](docs/tutorials/first-server.md) to build the greeting example and call it through the manager.
- [Package a Python server](docs/how-to/package-a-server.md) for a complete recipe, with Node, wrapper, and remote variants.

The [installation guide](docs/how-to/install.md) builds a development package. Existing users can go directly to [server configuration](docs/how-to/configure-serving.md), [registration recovery](docs/how-to/recover-registrations.md), or the [migration guide](docs/how-to/migrate-from-conda-cli-mcp.md). The [MCP interface reference](docs/reference/mcp-interface.md) documents tools, resources, and result fields.

```sh
conda activate servers
conda mcp list
conda mcp register example --client codex
conda mcp registry
```

The source defaults to the active environment. Use `-n NAME` to select another environment, and `--dry-run` to preview registration. For stdio servers, append startup arguments after `--`, for example `conda mcp register conda-cli -n base --client codex -- --allow-write`. Restart the server through your client after changing its registration.

Client configuration defaults to the current project. Use `--global` for user configuration. Claude Code and Copilot share the project `.mcp.json`. Claude Desktop uses user configuration and supports only local stdio entries through this plugin. Kilo JSONC is left untouched. Use `render` to generate a native client snippet when another layer prevents a safe write. It is not a portable environment export.

## Package a declaration

Include `share/conda-mcp/servers/<name>.json` as an installed package file. Its name must match the filename. A stdio declaration names a recorded executable and may specify literal arguments and required environment-variable names. Declare runtime dependencies in the conda recipe. The [remote example](examples/remote/recipe.yaml) installs only metadata and does not contact an endpoint.

Local execution runs conda activation hooks and the server with your privileges. Package ownership does not establish trust. Remote connections and approval remain the client's responsibility. The launcher uses POSIX process groups and Windows Job Objects. Native tests establish platform coverage. A cross-platform lockfile only records dependency resolution.

The maintained examples include a [FastMCP greeting tool](examples/fastmcp/recipe.yaml), a [Node server](examples/node/recipe.yaml), a [manifest-only wrapper](examples/wrapper/recipe.yaml), and a [remote declaration](examples/remote/recipe.yaml). Discovery never infers a server from its executable name or contacts an endpoint.
