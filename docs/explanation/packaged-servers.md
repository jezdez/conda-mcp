# Why package an MCP server with conda

Conda solves Python or Node runtimes and native libraries in one environment, using builds for the selected platform from configured channels. A lockfile can pin the complete environment when repeatable installs matter. The maintained local examples launch installed executables, so starting a server does not download dependencies. Package code still runs with the user's privileges.

Conda-mcp discovers server declarations from installed conda package records. For a local stdio server, packaging puts its executable, dependencies, and declaration in the same environment. Conda handles installation, updates, and removal. An operator registers the server to give a client its launch entry.

The executable must already implement MCP. Its declaration tells conda-mcp how to find and start it. The diagram follows this local stdio path.

```{mermaid}
:caption: A package carries the declaration into an installed prefix. Registration configures a client after discovery.
:alt: Server source and declaration become a conda package, reach an installed prefix through a channel, and are discovered before client registration and launch. A runtime dependency can supply the executable.

flowchart TB
    accTitle: From MCP server source to client launch
    accDescr: Server source and an MCP declaration enter a conda recipe. The built package moves through a channel into an installed prefix, which can also contain a runtime dependency. Conda-mcp discovers the recorded declaration. An operator registers it, creating a client entry and receipt. The client then launches the server.
    source["MCP server source"] --> recipe["Conda recipe"]
    declaration["MCP declaration"] --> recipe
    recipe --> artifact["Built package"]
    recipe -.->|requires| dependency["Runtime dependency"]
    artifact --> channel["Conda channel"]
    channel --> prefix["Installed prefix"]
    dependency --> prefix
    prefix --> discovery["Discover installed declaration"]
    discovery -->|register| registration["Client entry + receipt"]
    registration --> client["Client launches server"]
```

## What the package provides

The recipe specifies how to build the server and what must be installed alongside it. The declaration is a JSON file under `share/conda-mcp/servers/`. Conda records that file as belonging to the installed package. Conda-mcp reads only declarations found through those records, so copying JSON into an environment by hand does not add a discoverable server.

The package can provide the executable itself, as the {doc}`../how-to/package-a-server` example does. A metadata-only wrapper can instead provide the declaration and depend on a package that provides the executable. Conda-mcp checks recorded ownership of the selected executable inside the source prefix. The wrapper still needs an executable that speaks MCP. See {doc}`../how-to/package-a-wrapper` for the ownership example.

A package can also carry an HTTPS endpoint declaration. That path has no local executable to launch or activate. See {doc}`../how-to/package-a-remote-server` for the remote layout.

Declarations can name required environment variables, but they do not contain credential values. Client configuration or the operator's environment supplies values at launch. The {doc}`../reference/server-format` describes the declaration fields.

## What registration adds

Discovery and inspection read installed records without starting the server. `register` writes an entry in the chosen native client configuration and an adjacent receipt used to recognise later edits. For local stdio, the client launches the installed server when it needs a session, using the selected conda environment and its activation hooks. Package installation and protocol calls happen separately from registration.

An updated package can change the declaration or executable while the client entry still exists. Operators can review the new installed source and refresh a managed registration. The {doc}`../how-to/maintain-a-server` guide covers the maintainer's release path and the operator handoff. Use {doc}`../how-to/recover-registrations` when an entry was edited or its source disappeared.
