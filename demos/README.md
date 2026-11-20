# Record the demos

The recordings use VHS with conda-skills' JetBrains Mono font, Dark+ theme, green prompt, and 1200-pixel width. Each command runs against installed packages built from this checkout. The GIFs can be viewed and included in the documentation without recording tools.

## Prerequisites

Recording needs a POSIX Bash shell, [VHS](https://github.com/charmbracelet/vhs), its ttyd and browser dependencies, FFmpeg, bat, and JetBrains Mono. The recordings are made on macOS. Native Windows behavior is tested separately.

From the repository root, build the plugin and example package:

```sh
conda workspace install --locked -e build
conda task run -e build build-conda
conda workspace run -e build -- rattler-build build -r examples/fastmcp/recipe.yaml --output-dir conda-dist -c conda-forge
vhs demos/use-a-server.tape
vhs demos/inspect.tape
vhs demos/live-mcp.tape
```

`setup.sh` creates a temporary home, project, package cache, and two explicit prefixes. The tools prefix contains the built plugin. The servers prefix contains the built FastMCP example and FastMCP 3 or newer for its client commands. Installation downloads dependencies from conda-forge and is hidden from the recording. The installed plugin keeps rendered commands free of paths from the checkout or your home.

The setup removes inherited conda and client path overrides. It does not launch a server or client. The live recording does both. Every recording writes only project-local configuration inside the temporary directory, which is removed when the shell exits. No recording publishes packages or changes your usual configuration. Source the setup only in a disposable shell.

`use-a-server.tape` covers discovery, declaration review, dry-run, registration, registry inspection, and removal without launching a server. `inspect.tape` shows package provenance and a client entry rendered without writes or launching a server. `live-mcp.tape` uses FastMCP's client CLI with a rendered configuration to launch the packaged server, list tools, and call `greet`. `_settings.tape` supplies their shared appearance.

Watch the generated GIFs before keeping them. Check that every command succeeds and its output fits, then run `conda task run -e docs docs`. Keep the text equivalents in `docs/demos.md` synchronized with the tapes.
