# conda-mcp

`conda-mcp` connects MCP clients to conda and to servers installed in conda environments. Its built-in `conda mcp serve` command exposes the invoking installation's conda commands. Its manager discovers package-owned server declarations, writes native client configuration, and launches local servers with their environment activated.

Conda owns installation, updates, and removal. Clients own connection setup and approval. The project is unreleased. Follow {doc}`how-to/install` to build and install the development package alongside conda. Separately packaged servers can live in another environment.

::::{grid} 1 1 3 3
:gutter: 3

:::{grid-item-card} Use conda through MCP
:link: tutorials/first-conda-session
:link-type: doc

Connect a read-only server, inspect its capabilities, and call conda.
:::

:::{grid-item-card} Connect a packaged server
:link: tutorials/first-server
:link-type: doc

Build the greeting example, register it, and make a real MCP call.
:::

:::{grid-item-card} Package a server
:link: how-to/package-a-server
:link-type: doc

Ship a Python server, then adapt the recipe for Node, wrappers, or remote endpoints.
:::

::::

## Work with an existing setup

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Complete a task

- {doc}`how-to/configure-serving`
- {doc}`how-to/recover-registrations`
- {doc}`how-to/connect-a-remote-server`
- {doc}`how-to/provide-credentials`
- {doc}`how-to/maintain-a-server`
:::

:::{grid-item-card} Look up details

- {doc}`reference/commands`
- {doc}`reference/mcp-interface`
- {doc}`reference/server-format`
- {doc}`reference/registrations`
:::

::::

For the reasons behind discovery and permissions, read {doc}`explanation/serving`. {doc}`explanation/packaged-servers` follows a server from source to installation and explains why to package it with conda. {doc}`explanation/lifecycle` covers package ownership, activation, and process cleanup. {doc}`explanation/prior-art` compares conda-mcp with other MCP and conda tools. The {doc}`reference/glossary` defines terms used throughout the guides, and the {ref}`genindex` lists terms and command options alphabetically.

:::{admonition} Moving from conda-cli-mcp
:class: seealso

Follow {doc}`how-to/migrate-from-conda-cli-mcp` to replace the old launcher and update client configuration.
:::

::::{dropdown} Watch a registration walkthrough
:::{figure} ../demos/use-a-server.gif
:alt: Terminal recording of discovering a packaged FastMCP server and creating and removing its project-local Codex registration.

The {ref}`registration recording <demo-registration>` includes the commands in text.
:::
::::

```{toctree}
:hidden:
:caption: Tutorials

tutorials/first-conda-session
tutorials/first-server
demos
```

```{toctree}
:hidden:
:caption: How-to guides

how-to/install
how-to/configure-serving
how-to/enable-operations
how-to/refresh-plugin-tools
how-to/recover-registrations
how-to/connect-a-remote-server
how-to/provide-credentials
how-to/package-a-server
how-to/package-a-node-server
how-to/package-a-wrapper
how-to/package-a-remote-server
how-to/maintain-a-server
how-to/migrate-from-conda-cli-mcp
```

```{toctree}
:hidden:
:caption: Reference

reference/commands
reference/mcp-interface
reference/registrations
reference/server-format
reference/glossary
```

```{toctree}
:hidden:
:caption: Explanation

explanation/serving
explanation/packaged-servers
explanation/lifecycle
explanation/prior-art
```
