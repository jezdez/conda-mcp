# conda-mcp

`conda-mcp` discovers MCP server declarations installed by conda packages, writes selected client registrations, and runs local stdio servers with the selected environment activated. Conda still owns package installation, updates, and removal.

The project is unreleased. Install it into the environment that runs `conda`, using conda or conda-pypi. Server packages may be installed in another environment.

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} First server
:link: tutorials/first-server
:link-type: doc

Discover a package-owned declaration and preview client configuration.
:::

:::{grid-item-card} Package a server
:link: how-to/package-a-server
:link-type: doc

Build Python, Node, remote, and wrapper declarations.
:::

:::{grid-item-card} Command reference
:link: reference/commands
:link-type: doc

Look up commands, clients, and declaration fields.
:::

:::{grid-item-card} Safety and lifecycle
:link: explanation/lifecycle
:link-type: doc

Understand trust, streams, receipts, and package changes.
:::
::::

```{toctree}
:hidden:

tutorials/first-server
how-to/package-a-server
reference/commands
reference/server-format
explanation/lifecycle
```
