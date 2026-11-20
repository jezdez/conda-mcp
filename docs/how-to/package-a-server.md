# Package a server

Put a version-1 declaration at `share/conda-mcp/servers/NAME.json` in the installed package. The manifest filename and `name` must agree. Discovery reads only declarations listed in the installed package record.

The repository has working recipes under `examples/`:

| Recipe | Purpose |
| --- | --- |
| `fastmcp` | A Python FastMCP server with a console entry point. |
| `node` | A Node stdio server with a conda-managed Python console entry point and Node runtime. |
| `remote` | A noarch-generic HTTP declaration with no network activity during installation or discovery. |
| `wrapper` | A noarch-generic declaration that names the `node` executable from a runtime dependency. |

Declare every local executable's runtime dependency in the recipe. Do not rely on `npx`, `uvx`, or another downloader at launch time. A metadata-only wrapper must declare the package that owns the executable.

Build a recipe with the recipe-v1 builder:

```sh
rattler-build build -r examples/node/recipe.yaml -c conda-forge
```

Install the resulting artifact in a disposable environment and use `conda mcp inspect -p PREFIX NAME` to review the recorded declaration before configuring a client. The entry point starts the packaged JavaScript without invoking `npx` or downloading code.

`conda-build examples/node -c conda-forge` accepts the same v1 recipe through conda-build's Rattler integration. Pass the recipe directory to this entry point. The two commands exercise different integration paths around the same build engine.
