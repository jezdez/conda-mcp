(tutorial-conda-session)=
# Call conda through MCP

In this tutorial, you will connect a command-line MCP client to the built-in conda server and retrieve conda's installation information through its `conda_info` tool.

::::{dropdown} Watch a conda tool call
```{figure} ../../demos/conda-session.gif
:alt: Terminal recording of a successful conda_info call through the built-in server.

The {ref}`conda recording <demo-conda-session>` shows an environment-list request and includes a text equivalent.
```
::::

::::{steps}

:::{step} Prepare the client

Complete the `base` installation in {doc}`../how-to/install`. This tutorial uses its recorded `conda-cli` declaration.

Create a separate environment for the [FastMCP client commands](https://gofastmcp.com/docs/cli/client):

```sh
conda activate base
conda create -n mcp-client --override-channels -c conda-forge "fastmcp>=3"
mkdir conda-session
cd conda-session
```

FastMCP supplies the client for this lesson. Keep `base` active until the server configuration is written.
:::

:::{step} Connect the built-in server

Review the installed declaration and render a client configuration:

```sh
conda mcp inspect conda-cli
conda mcp render conda-cli --client claude-code > conda-server.json
```

Inspection identifies conda-mcp as the declaration owner and shows Python with the arguments `-I -m conda_mcp._stdio serve`. The rendered JSON is also accepted by FastMCP. Creating this file does not register Claude Code or start a server.

The configuration records absolute paths to the server. Activate the client environment and list tools:

```sh
conda activate mcp-client
fastmcp list conda-server.json --timeout 30
```

Find `conda_info` in the list. Other names depend on the installed conda and plugins. `conda_execute` is absent because this server starts without execution permission. Mutation tools may still appear, but their calls are rejected in the default mode.

Each FastMCP command starts a server, completes its request, and closes that session. You do not need to run `conda mcp serve` in a second terminal.
:::

:::{step} Inspect the serving installation

Read the server's {ref}`capabilities resource <capabilities-resource>`:

```sh
fastmcp call conda-server.json conda://capabilities --timeout 30
```

Check that `conda_executable` points inside `base`, where you installed conda-mcp. The `generated_tools` array contains `conda_info`, and `plugins` describes the external conda plugins visible at startup. Paths, versions, and the discovery fingerprint will vary between installations.

This resource is a snapshot. It lets you check which installation the client reached before asking it to perform an operation.
:::

:::{step} Make a read-only call

Request conda's JSON information:

```sh
fastmcp call conda-server.json conda_info json=true --json --timeout 30
```

In the returned `structured_content`, look for `exit_code: 0`, `timed_out: false`, and `restart_required: false`. `parsed_json` contains conda's information object, while `stdout` retains the original JSON text. FastMCP uses `structured_content` for the MCP protocol's `structuredContent` field in its CLI output. A nonzero exit code or a protocol error needs investigation before continuing.

You have now discovered tools, read a resource, and called a generated tool through the packaged `conda-cli` server.
:::

:::{step} Clean up and continue

The client has already closed the server. Delete `conda-server.json`, then leave and remove the empty `conda-session` directory. Remove the disposable client environment if you no longer need it:

```sh
conda deactivate
conda env remove -n mcp-client
```

To connect your usual client, follow {doc}`../how-to/configure-serving`. Use {doc}`../how-to/enable-operations` when a task needs additional permissions. Look up result fields in the {ref}`execution-results` reference.
:::

::::
