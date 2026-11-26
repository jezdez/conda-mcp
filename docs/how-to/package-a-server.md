# Package a Python server

Use this guide to ship a Python MCP server and its declaration in one conda package. It follows the maintained FastMCP greeting example from source code to an installed protocol call. You need the conda-mcp checkout and the build environment prepared by {doc}`install`.

For other layouts, use {doc}`package-a-node-server`, {doc}`package-a-wrapper`, or {doc}`package-a-remote-server`.

For the package and registration model, see {doc}`../explanation/packaged-servers`. After the first release, use {doc}`maintain-a-server` to build and test updates.

## Define the server entry point

The example has one tool and a `main()` function that starts stdio transport:

```{literalinclude} ../../examples/fastmcp/example_fastmcp.py
:language: python
:caption: examples/fastmcp/example_fastmcp.py
```

Keep protocol output on stdout and diagnostics on stderr. The Python build metadata includes the module and its runtime dependency:

```{literalinclude} ../../examples/fastmcp/pyproject.toml
:language: toml
:caption: examples/fastmcp/pyproject.toml
```

In this example, the conda recipe creates the `example-fastmcp` console entry point. The wheel metadata alone does not create that entry point or install the declaration. Adapt the entry-point ownership to your package's build system without defining competing launchers.

## Include the declaration as a package file

The declaration names an executable basename and literal arguments. Its server name must match its installed filename:

```{literalinclude} ../../examples/fastmcp/fastmcp-example.json
:language: json
:caption: examples/fastmcp/fastmcp-example.json
```

The build copies it into the package prefix:

```{literalinclude} ../../examples/fastmcp/install.py
:language: python
:caption: examples/fastmcp/install.py
```

Install declarations under `share/conda-mcp/servers/NAME.json` during the package build. Conda records the file in the installed package's inventory. Copying a JSON file into an existing environment by hand does not make it discoverable.

Use environment-variable names for credentials and declare whether each is required. The full field definitions and validation rules are in {doc}`../reference/server-format`.

## Declare build and runtime requirements

The recipe installs the Python code, creates its launcher, copies the declaration, and checks package contents:

```{literalinclude} ../../examples/fastmcp/recipe.yaml
:language: yaml
:caption: examples/fastmcp/recipe.yaml
```

Runtime requirements must provide the executable and every dependency it needs. Launch must not depend on `npx`, `uvx`, or another downloader. The executable may belong to a declared dependency, but it must have unambiguous package ownership inside the source prefix.

## Build and inspect the artifact

From the checkout, select a builder:

::::{tab-set}
:sync-group: builder

:::{tab-item} rattler-build
:sync: rattler-build

```sh
conda workspace run -e build -- rattler-build build -r examples/fastmcp/recipe.yaml --output-dir output/examples-rattler -c conda-forge
conda create -n mcp-servers --override-channels -c ./output/examples-rattler -c conda-forge example-fastmcp-server "fastmcp>=3"
conda mcp inspect fastmcp-example -n mcp-servers --json
```
:::

:::{tab-item} conda-build
:sync: conda-build

The conda-build integration accepts the recipe directory:

```sh
conda workspace run -e build -- conda-build examples/fastmcp --output-folder output/examples-conda -c conda-forge
conda create -n mcp-servers --override-channels -c ./output/examples-conda -c conda-forge example-fastmcp-server "fastmcp>=3"
conda mcp inspect fastmcp-example -n mcp-servers --json
```
:::

::::

Check the manifest path, package owner, executable, and declared arguments. Inspection validates discovery and launch requirements, but does not start a protocol session.

Both commands accept the recipe-v1 source. They exercise different integration paths around the Rattler build engine. Keep their output directories separate when checking the artifacts from each builder.

## Exercise the installed protocol

From a disposable project directory, render and call the installed package:

```sh
conda activate mcp-servers
conda mcp render fastmcp-example --client claude-code > server.json
fastmcp list server.json --timeout 30
fastmcp call server.json greet name=Conda --timeout 30
```

The expected reply is `Hello, Conda!`. This checks that the installed executable starts after activation and answers an MCP request. Keep checks for your own tool's inputs and results alongside the package source.

For this repository, `conda task run test-examples` builds all maintained examples with both builders, installs them into temporary prefixes, and exercises their intended behaviour. The remote and wrapper examples are metadata fixtures, so their checks do not claim a live hosted connection or a wrapper-provided MCP implementation.

Deactivate and remove the disposable server environment when finished, and delete `server.json`. If you also registered the server, unregister it before removing the environment. See {doc}`recover-registrations` for registrations left behind by package removal.
