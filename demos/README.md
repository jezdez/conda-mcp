# Record the demos

The recordings use VHS with conda-skills' JetBrains Mono font, Dark+ theme, green prompt, and 1200-pixel width. Each command runs against installed packages built from this checkout. The GIFs can be viewed and included in the documentation without recording tools.

## Prerequisites

Recording needs a POSIX Bash shell, [VHS](https://github.com/charmbracelet/vhs), its ttyd and browser dependencies, FFmpeg, bat, jq, and JetBrains Mono. The recordings are made on macOS. Native Windows behaviour is tested separately.

From the repository root, build the plugin and example package:

```sh
conda workspace install --locked -e build
conda task run build-conda
conda workspace run -e build -- rattler-build build -r examples/fastmcp/recipe.yaml --output-dir conda-dist -c conda-forge
vhs demos/use-a-server.tape
vhs demos/inspect.tape
vhs demos/live-mcp.tape
vhs demos/conda-session.tape
vhs demos/recover-registration.tape
```

`setup.sh` creates a temporary home, project, package cache, and two explicit prefixes. The tools prefix contains the built plugin. The servers prefix contains the built FastMCP example and FastMCP 3 or newer for its client commands. Installation downloads dependencies from conda-forge and is hidden from the recording. The installed plugin keeps rendered commands free of paths from the checkout or your home.

The setup removes inherited conda and client path overrides. It does not launch a server or client. The `live-mcp` and `conda-session` recordings launch a server through the FastMCP client. Every recording writes only project-local configuration inside the temporary directory, which is removed when the shell exits. No recording publishes packages or changes your usual configuration. Source the setup only in a disposable shell.

| Tape | What it shows |
| --- | --- |
| `use-a-server.tape` | Discover and review a declaration, preview registration, then create and remove the entry. No server is launched. |
| `inspect.tape` | Inspect package provenance and render a client entry without writes or a server launch. |
| `live-mcp.tape` | Launch the greeting server through FastMCP, list tools, and call `greet`. |
| `conda-session.tape` | Launch the built-in conda server and call `conda_info`. jq selects fields from the real result for display. |
| `recover-registration.tape` | Back up and edit a registration, inspect its state, then preview removal and replace it. No server is launched. |

`_settings.tape` supplies their shared appearance. `conda-session` and `recover-registration` also check their expected JSON results before exiting.

Watch the generated GIFs before keeping them. Check that every command succeeds and its output fits, then run `conda task run docs`. Keep the text equivalents in `docs/demos.md` synchronised with the tapes.
