# Package a Node server

Use a conda-managed launcher and a declared Node runtime to package a JavaScript stdio server. This avoids downloading code when a client starts the server.

The maintained `examples/node` package ships `server.mjs` and a small Python launcher:

```{literalinclude} ../../examples/node/example_node_mcp.py
:language: python
:caption: examples/node/example_node_mcp.py
```

The launcher inherits protocol streams, starts the packaged JavaScript, and returns its exit status. Node is resolved after the source environment is activated.

The recipe declares both runtimes and creates a native Python console entry point on each platform:

```{literalinclude} ../../examples/node/recipe.yaml
:language: yaml
:caption: examples/node/recipe.yaml
```

Its declaration names that entry point:

```{literalinclude} ../../examples/node/node-example.json
:language: json
:caption: examples/node/node-example.json
```

Keep the JavaScript and any required modules in the package, and ensure the Python build includes them. The example's Python build metadata includes both `example_node_mcp.py` and `server.mjs`. Windows `.cmd` and `.bat` launchers are rejected by conda-mcp, so do not point the declaration at an npm batch shim.

With the environment prepared by {doc}`install`, build and inspect from the checkout:

::::{tab-set}
:sync-group: builder

:::{tab-item} rattler-build
:sync: rattler-build

```sh
conda workspace run -e build -- rattler-build build -r examples/node/recipe.yaml --output-dir output/examples-rattler -c conda-forge
conda create -n node-server --override-channels -c ./output/examples-rattler -c conda-forge example-node-mcp-server "fastmcp>=3"
conda mcp inspect node-example -n node-server
```
:::

:::{tab-item} conda-build
:sync: conda-build

```sh
conda workspace run -e build -- conda-build examples/node --output-folder output/examples-conda -c conda-forge
conda create -n node-server --override-channels -c ./output/examples-conda -c conda-forge example-node-mcp-server "fastmcp>=3"
conda mcp inspect node-example -n node-server
```
:::

::::

From a disposable project directory, exercise its `hello` tool:

```sh
conda activate node-server
conda mcp render node-example --client claude-code > node-server.json
fastmcp call node-server.json hello name=Conda --timeout 30
```

Expect `Hello, Conda!`. Deactivate and remove the disposable environment, then delete the JSON file. For the full Python packaging workflow, see {doc}`package-a-server`.
