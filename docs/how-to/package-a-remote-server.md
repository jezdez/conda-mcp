# Package a remote endpoint declaration

Use a metadata-only conda package to distribute an HTTPS MCP endpoint and the names of credentials its client needs. The package need not contain a local server executable or Python runtime.

The repository's remote fixture uses an intentionally unreachable placeholder:

```{literalinclude} ../../examples/remote/example.json
:language: json
:caption: examples/remote/example.json
```

For your own package, choose a distinct server name, rename the file to match it, and supply the actual HTTPS URL. Credentials are references to environment-variable names:

```json
{
  "schema_version": 1,
  "name": "catalog",
  "description": "Hosted catalog tools",
  "http": {
    "url": "https://catalog.example.org/mcp",
    "bearer_token_env": "CATALOG_TOKEN",
    "header_env": {"X-Organization": "CATALOG_ORGANIZATION"}
  }
}
```

This is an illustrative declaration, not a public service. Keep token values out of the package. URLs must use HTTPS and cannot contain user information, query parameters, or fragments. Check the header restrictions in {doc}`../reference/server-format`.

The fixture's recipe copies its manifest at build time:

```{literalinclude} ../../examples/remote/recipe.yaml
:language: yaml
:caption: examples/remote/recipe.yaml
```

The build needs Python for its copy script. The installed metadata-only package does not. Update the install script's source and destination together when renaming the manifest.

Build and inspect the fixture with the environment from {doc}`install`:

::::{tab-set}
:sync-group: builder

:::{tab-item} rattler-build
:sync: rattler-build

```sh
conda workspace run -e build -- rattler-build build -r examples/remote/recipe.yaml --output-dir output/examples-rattler -c conda-forge
conda create -n remote-metadata --override-channels -c ./output/examples-rattler -c conda-forge example-mcp-endpoint
conda mcp inspect example -n remote-metadata
conda mcp render example -n remote-metadata --client codex
```
:::

:::{tab-item} conda-build
:sync: conda-build

```sh
conda workspace run -e build -- conda-build examples/remote --output-folder output/examples-conda -c conda-forge
conda create -n remote-metadata --override-channels -c ./output/examples-conda -c conda-forge example-mcp-endpoint
conda mcp inspect example -n remote-metadata
conda mcp render example -n remote-metadata --client codex
```
:::

::::

These checks do not contact the placeholder endpoint. Remove the disposable environment afterwards. For a real endpoint, verify authentication and a read-only call through a supported client using {doc}`connect-a-remote-server`. Keep that live check separate from package discovery and configuration validation.
