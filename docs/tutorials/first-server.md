(tutorial-packaged-server)=
# Connect a packaged server

In this tutorial, you will build the greeting example, discover its installed declaration, register it for a project, and call its `greet` tool through conda-mcp. The reply will be `Hello, Conda!`.

::::{steps}

:::{step} Prepare the example

Complete the `base` installation in {doc}`../how-to/install` and return to the conda-mcp checkout. That guide also prepares the build environment. This tutorial uses Bash or Zsh on POSIX, or PowerShell 7 on Windows.

Build the maintained example and create its environment:

```sh
conda workspace run -e build -- rattler-build build -r examples/fastmcp/recipe.yaml --output-dir output/examples-rattler -c conda-forge
conda create -n mcp-servers --override-channels -c ./output/examples-rattler -c conda-forge example-fastmcp-server "fastmcp>=3"
conda activate mcp-servers
mkdir packaged-session
cd packaged-session
```

The example package comes from your local build. FastMCP supplies both its server implementation and the client commands used later. Your shell's conda command loads the manager from `base` and selects the active `mcp-servers` environment.
:::

:::{step} Discover and inspect

```sh
conda mcp list
conda mcp inspect fastmcp-example
```

The list should contain `fastmcp-example`. Inspection identifies `example-fastmcp-server` as its package owner and shows the `example-fastmcp` executable. Review the description, arguments, and package provenance before executing it.

These commands read package records and declarations without starting the server. The active environment supplies the {term}`source prefix`.
:::

:::{step} Preview and register

Preview the Codex registration, then create it:

```sh
conda mcp register fastmcp-example --client codex --dry-run
conda mcp register fastmcp-example --client codex
conda mcp registry --client codex
```

The dry run creates no configuration, lock, or receipt. The actual registration creates `.codex/config.toml` and its adjacent receipt in `packaged-session`. The registry should report `managed` with a `current` source. Codex does not need to be installed for this configuration exercise, and registration does not start it or grant approval.
:::

:::{step} Call the greeting tool

```{important}
This step executes activation hooks and server code with your privileges. Review the installed package before making the call.
```

For a live connection, render the JSON form accepted by the [FastMCP client CLI](https://gofastmcp.com/docs/cli/client):

```sh
conda mcp render fastmcp-example --client claude-code > server.json
fastmcp list server.json --timeout 30
fastmcp call server.json greet name=Conda --timeout 30
```

The list should show `greet` with a required `name` string. The call returns `Hello, Conda!`. Each client command launches a fresh session through `conda mcp run`, activates `mcp-servers`, and closes the session when it finishes. The JSON file does not register Claude Code.

Running `conda mcp run` by itself in a terminal waits for protocol input. Use a client for a tool call. The manager preserves protocol streams and does not add its own JSON response around the server's messages.
:::

:::{step} Remove the registration and example

```sh
conda mcp unregister fastmcp-example --client codex --dry-run
conda mcp unregister fastmcp-example --client codex
conda mcp registry --client codex
conda deactivate
conda env remove -n mcp-servers
```

The registry should now contain no registration for `fastmcp-example`. Unregistration preserves the server package until the explicit environment removal. Delete `server.json`, then remove the disposable `packaged-session` directory and any empty configuration or receipt files left inside it.

To package your own tool, follow {doc}`../how-to/package-a-server`. To connect a hosted endpoint, use {doc}`../how-to/connect-a-remote-server`. The recordings in {doc}`../demos` show the same discovery and registration operations.
:::

::::
