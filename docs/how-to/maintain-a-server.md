# Maintain a packaged MCP server

Use this guide when an upstream server releases a new version or a packaged server needs a dependency, recipe, or declaration change. The commands use the maintained FastMCP greeting example. Replace its package and server names with yours. Prepare the build environment as in {doc}`install`.

```{mermaid}
:name: server-maintenance
:caption: Test a new package before publishing it, then let operators review their own registrations.
:alt: Maintainer updates, builds, installs, and tests the package before publishing it. Operator updates with conda and reviews the client registration.

flowchart LR
    accTitle: Maintaining a packaged MCP server
    accDescr: A new release or dependency change leads to a recipe update and a review of the MCP declaration. The maintainer builds an artifact, installs it in a fresh prefix, inspects it, and makes a protocol call before publishing it to a channel. Operators update with conda and review or refresh their client registrations.
    subgraph maintainer["Maintainer"]
        direction TB
        change["Release or dependency change"] --> recipe["Update recipe"]
        recipe --> declaration["Review declaration"]
        declaration --> artifact["Build artifact"]
        artifact --> prefix["Install in fresh prefix"]
        prefix --> protocol["Inspect + protocol call"]
        protocol --> channel["Publish to channel"]
    end
    subgraph operator["Operator"]
        direction TB
        update["conda update"] --> registration["Review or refresh registration"]
    end
    maintainer -->|After publication| operator
```

## Update the recipe and declaration

Update the recipe's source, version, and dependencies for the release. If the package uses an upstream archive, update its URL and checksum. For a new source version, set `package.version` and reset `build.number` to `0`. For a new build of the same version, increment `build.number`, which defaults to `0`. These rules follow the [Rattler-Build recipe reference](https://rattler-build.prefix.dev/dev/reference/recipe_file/) and [conda-forge's package maintenance guide](https://conda-forge.org/docs/maintainer/updating_pkgs/).

Review the installed declaration when the executable name, arguments, transport, or required environment-variable names change. Keep credential values out of it. A wrapper's recipe must retain a runtime dependency that supplies its declared executable. See {doc}`package-a-server` for the Python example and {doc}`package-a-wrapper` for the separate declaration owner.

## Build and test a fresh artifact

From this checkout, choose an unused output directory for the candidate build. This example uses `output/maintenance-rattler`:

```sh
conda workspace run -e build -- rattler-build build -r examples/fastmcp/recipe.yaml --output-dir output/maintenance-rattler -c conda-forge
conda create -n mcp-maintenance-check --override-channels -c ./output/maintenance-rattler -c conda-forge example-fastmcp-server "fastmcp>=3"
conda mcp inspect fastmcp-example -n mcp-maintenance-check --json
```

Use a fresh environment name for each candidate. Check the reported declaration owner, executable, and arguments. Inspection checks the installed records and launch requirements. It does not make an MCP call.

Activate the test environment, move to a disposable project directory, and call the installed server:

```sh
conda activate mcp-maintenance-check
conda mcp render fastmcp-example --client claude-code > server.json
fastmcp list server.json --timeout 30
fastmcp call server.json greet name=Conda --timeout 30
```

The example replies `Hello, Conda!`. Test your own server's tools and expected results in the same way. Remove `server.json` and the disposable environment when finished. The {doc}`package-a-server` guide also shows the conda-build command. This repository's `conda task run test-examples` checks all maintained example packages with both builders.

## Publish and hand off the update

Publish the tested artifact and channel metadata through your channel's release process. Tell operators which package version and channel to install, and whether the declaration or required environment variables changed. Conda handles package updates. Existing client entries remain in each operator's configuration until they review them.

For an operator using a managed Codex entry, replace `your-channel`, the environment name, and the server name below. After the conda update, inspect the installed source and the registry state:

Run the registration commands from the project containing the existing entry. For a user-level entry, add `--global` to every `registry` and `register` command below.

```sh
conda update -n mcp-servers --override-channels -c your-channel -c conda-forge example-fastmcp-server
conda mcp inspect fastmcp-example -n mcp-servers
conda mcp registry --client codex --json
```

If the entry is `managed` and its source is `changed`, preview and refresh the registration. Include any custom startup arguments after `--` in both commands. Omitting them restores the packaged defaults:

```sh
conda mcp register fastmcp-example -n mcp-servers --client codex --dry-run
conda mcp register fastmcp-example -n mcp-servers --client codex
```

Restart the server through the client and make a real call. If the entry was edited, the source disappeared, or the source provider changed, follow {doc}`recover-registrations` before changing client configuration.
