# Demos

These recordings use installed packages built from this checkout and run the real CLI on macOS. They share conda-skills' Dark+ theme, terminal font, and 1200-pixel width. Setup creates disposable homes, projects, and prefixes before the visible commands begin.

## Register a local server

The FastMCP example is already installed in `../servers`. The recording lists its declaration, reads the manifest, previews a Codex registration, then creates and removes that project-local entry. The installed package stays in place and the tape never starts a server.

```{image} ../demos/use-a-server.gif
:alt: Terminal recording of listing and reviewing the FastMCP declaration, previewing and creating a Codex registration, checking the registry, and unregistering it.
```

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

## Inspect and render

Inspection shows the package owner, manifest digest, and declared command. Rendering prints the proposed Codex entry without writing it. The final registry check shows no Codex registration in the temporary project. This tape never starts a server.

```{image} ../demos/inspect.gif
:alt: Terminal recording of inspecting FastMCP package provenance, rendering a Codex configuration entry, and checking that no registrations exist.
```

Text equivalent:

```sh
conda mcp inspect fastmcp-example -p ../servers
conda mcp render fastmcp-example -p ../servers --client codex
conda mcp registry --client codex
```

These commands do not contact or execute the declared server. Package ownership identifies the installed provider and does not establish that its code is safe. The generated command uses `conda mcp run` with the recorded prefix and provider when a client later starts it. See {doc}`reference/commands` for the other supported clients and {doc}`explanation/lifecycle` for activation and process cleanup.

## Live MCP session

This recording uses the existing [FastMCP client CLI](https://gofastmcp.com/docs/cli/client) to launch the packaged server through `conda mcp run`. It reads the rendered configuration, initializes a session, and lists the server's tools. The next command starts a new session and calls `greet`, returning the real reply `Hello, Conda!`.

```{image} ../demos/live-mcp.gif
:alt: Terminal recording of FastMCP listing the greet tool and receiving Hello, Conda! through the conda-mcp launcher.
```

Text equivalent:

```sh
# Install the client commands if the example resolved to FastMCP 2
conda install -p ../servers -c conda-forge "fastmcp>=3"
conda mcp render -p ../servers fastmcp-example --client claude-code > server.json
../servers/bin/fastmcp list server.json --timeout 30
../servers/bin/fastmcp call server.json greet name=Conda --timeout 30
```

Run this only after reviewing and trusting the installed package. Unlike discovery, rendering, and registry commands, the FastMCP client runs conda activation hooks and server code with your privileges. Rendering is passive, while the shell redirection explicitly writes `server.json`. These commands do not register a client or grant client approval. FastMCP is a demo dependency, not a dependency of `conda-mcp`.

## Record locally

The tapes and setup script are in the repository's `demos/` directory. Its README lists the build and recording commands. Setup copies the built packages into a temporary channel, then downloads runtime dependencies from conda-forge. It isolates conda and client configuration and deletes its temporary directory when the recording shell exits.

The GIFs demonstrate macOS behavior. They do not establish native Windows compatibility. VHS and its browser dependencies are needed only to regenerate the recordings, not to build the documentation.
