# Package a declaration for a dependency

Use a metadata-only wrapper when an existing conda package already provides the server executable but does not ship a conda-mcp declaration. The wrapper owns the manifest, while the dependency owns the executable.

The maintained fixture declares `node` from its runtime dependency:

```{literalinclude} ../../examples/wrapper/wrapper-example.json
:language: json
:caption: examples/wrapper/wrapper-example.json
```

```{literalinclude} ../../examples/wrapper/recipe.yaml
:language: yaml
:caption: examples/wrapper/recipe.yaml
```

This fixture demonstrates package ownership and dependency lookup. Bare `node` is not an MCP server. For a usable wrapper, name an executable that already implements MCP stdio, include any required literal arguments, and declare the package that provides it as a runtime requirement.

Copy the declaration into `share/conda-mcp/servers/NAME.json` during the wrapper build. A noarch-generic package can contain only that metadata. If the wrapper adds executable code, package its runtime and entry point as in {doc}`package-a-server` or {doc}`package-a-node-server`.

Build the fixture using the setup from {doc}`install`:

::::{tab-set}
:sync-group: builder

:::{tab-item} rattler-build
:sync: rattler-build

```sh
conda workspace run -e build -- rattler-build build -r examples/wrapper/recipe.yaml --output-dir output/examples-rattler -c conda-forge
conda create -n wrapper-server --override-channels -c ./output/examples-rattler -c conda-forge example-mcp-wrapper
conda mcp inspect wrapper-example -n wrapper-server
```
:::

:::{tab-item} conda-build
:sync: conda-build

```sh
conda workspace run -e build -- conda-build examples/wrapper --output-folder output/examples-conda -c conda-forge
conda create -n wrapper-server --override-channels -c ./output/examples-conda -c conda-forge example-mcp-wrapper
conda mcp inspect wrapper-example -n wrapper-server
```
:::

::::

Inspection should identify `example-mcp-wrapper` as the declaration owner and resolve the executable inside that environment. The runner checks recorded ownership of the selected executable and any resolved symlink target. Ambient `PATH` entries cannot supply an unrecorded replacement.

The generated `run --package` argument identifies the wrapper that owns the manifest. The executable can belong to its dependency package.

For your actual server, add a real initialise/list/call check before publishing. Remove the disposable fixture environment after inspection.
