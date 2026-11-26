# Demos

These recordings run the installed CLI on macOS in disposable homes, projects, and prefixes. Each has a text equivalent. Open a recording to watch it, or use the commands below it.

(demo-registration)=
## Register a local server

The FastMCP example is already installed in `../servers`. The recording lists its declaration, reads the manifest, previews a Codex registration, then creates and removes that project-local entry. The installed package stays in place and the tape never starts a server.

::::{dropdown} Watch: register a local server
```{figure} ../demos/use-a-server.gif
:alt: Terminal recording of listing and reviewing the FastMCP declaration, previewing and creating a Codex registration, checking the registry, and unregistering it.

Download the {download}`VHS source <../demos/use-a-server.tape>`.
```
::::

From a temporary project with the example installed in a sibling prefix:

```sh
conda mcp list -p ../servers
bat --paging=never --style=plain ../servers/share/conda-mcp/servers/fastmcp-example.json
conda mcp register fastmcp-example -p ../servers --client codex --dry-run
conda mcp register fastmcp-example -p ../servers --client codex
conda mcp registry --client codex
conda mcp unregister fastmcp-example --client codex
```

`-p` selects the installed server's source environment. The current directory selects the configuration destination, `.codex/config.toml`. `--dry-run` creates neither configuration nor a receipt. Registering writes the entry and its ownership receipt, but does not start Codex, activate the environment, or launch the server. Approval and tool permissions remain the client's responsibility. Review and trust the installed package before allowing its execution.

Bat is optional. An editor can display the installed manifest. Follow {doc}`tutorials/first-server` to build and install the example yourself.

(demo-inspect)=
## Inspect and render

Inspection shows the package owner, manifest digest, and declared command. Rendering prints the proposed Codex entry without writing it. The final registry check shows no Codex registration in the temporary project. This tape never starts a server.

::::{dropdown} Watch: inspect and render
```{figure} ../demos/inspect.gif
:alt: Terminal recording of inspecting FastMCP package provenance, rendering a Codex configuration entry, and checking that no registrations exist.

Download the {download}`VHS source <../demos/inspect.tape>`.
```
::::

Text equivalent:

```sh
conda mcp inspect fastmcp-example -p ../servers
conda mcp render fastmcp-example -p ../servers --client codex
conda mcp registry --client codex
```

These commands do not contact or execute the declared server. Package ownership identifies the installed provider and does not establish that its code is safe. The generated command uses `conda mcp run` with the recorded prefix and provider when a client later starts it. See {doc}`reference/commands` for the other supported clients and {doc}`explanation/lifecycle` for activation and process cleanup.

(demo-live-mcp)=
## Live MCP session

This recording uses the existing [FastMCP client CLI](https://gofastmcp.com/docs/cli/client) to launch the packaged server through `conda mcp run`. It reads the rendered configuration, initialises a session, and lists the server's tools. The next command starts a new session and calls `greet`, returning the real reply `Hello, Conda!`.

::::{dropdown} Watch: live MCP session
```{figure} ../demos/live-mcp.gif
:alt: Terminal recording of FastMCP listing the greet tool and receiving Hello, Conda! through the conda-mcp launcher.

Download the {download}`VHS source <../demos/live-mcp.tape>`.
```
::::

Text equivalent:

```sh
# Install the client commands if the example resolved to FastMCP 2
conda install -p ../servers -c conda-forge "fastmcp>=3"
conda mcp render -p ../servers fastmcp-example --client claude-code > server.json
../servers/bin/fastmcp list server.json --timeout 30
../servers/bin/fastmcp call server.json greet name=Conda --timeout 30
```

Run this only after reviewing and trusting the installed package. Unlike discovery, rendering, and registry commands, the FastMCP client runs conda activation hooks and server code with your privileges. Rendering is passive, while the shell redirection explicitly writes `server.json`. These commands do not register a client or grant client approval. FastMCP is a demo dependency, not a dependency of `conda-mcp`.

(demo-conda-session)=
## Call the built-in conda server

The `conda-cli` declaration belongs to conda-mcp in the tools environment. The client starts that server and calls `conda_info` to list environments. The recording shows selected fields from the real response: the exit status, environment paths from `parsed_json`, and restart flag.

::::{dropdown} Watch: call conda through MCP
```{figure} ../demos/conda-session.gif
:alt: Terminal recording of discovering conda-cli, rendering its configuration, and calling conda_info to return an environment list with exit code zero.

Download the {download}`VHS source <../demos/conda-session.tape>`.
```
::::

The tools prefix contains conda-mcp and the servers prefix supplies the FastMCP client. From their sibling project directory:

```sh
conda mcp list -p ../tools
conda mcp render conda-cli -p ../tools --client claude-code > conda.json
../servers/bin/fastmcp call conda.json conda_info envs=true json=true --json --timeout 30 > result.json
jq '.structured_content | {exit_code, envs: .parsed_json.envs, restart_required}' result.json
```

Expect `exit_code: 0`, an `envs` array, and `restart_required: false`. The complete response remains in `result.json`. `jq` only selects fields for display. Follow {doc}`tutorials/first-conda-session` to set up the environments yourself.

(demo-recover-registration)=
## Replace an edited registration

Adding a client-specific setting changes a managed entry from `managed` to `edited`. This recording backs up the configuration and receipt, makes that edit, then previews removal and replaces the entry. The final registry row is `managed` with a `current` source. No server or MCP client is launched.

::::{dropdown} Watch: recover an edited registration
```{figure} ../demos/recover-registration.gif
:alt: Terminal recording of a managed Codex registration becoming edited after a timeout setting is added, followed by a force-removal preview and replacement with a managed entry.

Download the {download}`VHS source <../demos/recover-registration.tape>`.
```
::::

From a disposable project with the greeting example installed in `../servers`:

```sh
conda mcp register fastmcp-example -p ../servers --client codex
conda mcp registry --client codex
cp .codex/config.toml config.backup.toml
cp .codex/config.toml.conda-mcp.json receipt.backup.json
printf '\nstartup_timeout_sec = 60\n' >> .codex/config.toml
conda mcp registry --client codex
conda mcp unregister fastmcp-example --client codex --force --dry-run
conda mcp unregister fastmcp-example --client codex --force
conda mcp register fastmcp-example -p ../servers --client codex
conda mcp registry --client codex
```

The replacement drops the custom timeout setting. Keep the edited entry if you still need that setting. See {ref}`recover-edited-registration` for the recovery steps and how to preserve unrelated configuration.

## Record locally

The tapes and setup script are in the repository's `demos/` directory. Its README lists the build and recording commands. Setup copies the built packages into a temporary channel, then downloads runtime dependencies from conda-forge. It isolates conda and client configuration and deletes its temporary directory when the recording shell exits.

The GIFs demonstrate macOS behaviour. They do not establish native Windows compatibility. VHS and its browser dependencies are needed only to regenerate the recordings, not to build the documentation.
