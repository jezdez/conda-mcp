# Prior art and design choices

Conda-mcp connects conda and MCP in two directions. It discovers packaged MCP servers and configures clients to launch them. It also exposes an installed conda CLI through `conda mcp serve`. These operations share one distribution and command namespace, while keeping package management, client configuration, and MCP execution separate.

## When to use conda-mcp

Conda-mcp is useful when a server needs native libraries, several language runtimes, platform-specific builds, or packages from an organization's channels. A package supplies the declaration, conda supplies the software and activation, and conda-mcp generates the client entry. Discovery does not import the server, resolve dependencies, or start an MCP session.

The built-in CLI server provides structured access to a selected conda installation, including its plugin commands. Conda still performs the operations in child processes, with its own configuration, solvers, reporters, and transaction hooks. The server adds MCP schemas, permission checks, input/output limits, and cancellation handling.

The advantage is smaller for a single Python server already served well by a framework's installer, and smaller still for an individual remote HTTPS endpoint. A remote declaration can distribute endpoint metadata through a channel, but it does not package, pin, or verify the service behind that URL. A client's native configuration is often sufficient for that case.

## MCP tools

| Prior art | What it provides | Relationship to conda-mcp |
| --- | --- | --- |
| [Docker MCP Toolkit](https://docs.docker.com/ai/mcp-catalog-and-toolkit/cli/) | Catalogs, profiles, client connections, a container gateway, OAuth configuration, and profile import/export or OCI distribution. | Conda-mcp uses conda environments and direct client entries without a gateway. Native environment specifications and locks describe software installation. Conda environments do not provide container isolation. |
| [Claude Code MCP](https://code.claude.com/docs/en/mcp) | Native server registration, scopes, approval, OAuth, policy, and connection status. | Conda-mcp supplies package-derived connections. Claude Code owns approval, authentication, and effective configuration. Writing `.mcp.json` does not establish any of those states. |
| [Codex MCP](https://developers.openai.com/codex/extend/mcp) | Native configuration and OAuth, with server enablement, tool filters, timeouts, and environment settings. | Package-derived connection fields must remain separate from these client-owned settings. Updating a connection must not implicitly enable a disabled server or relax its policy. |
| [MCP Inspector](https://github.com/modelcontextprotocol/inspector) | Live protocol inspection and testing, including initialization, tool listing, and calls. | Conda-mcp's `inspect` reads a declaration. The CLI server's tools execute conda commands. Neither replaces a general-purpose client for testing other MCP servers. |

[FastMCP's installer](https://gofastmcp.com/docs/cli/install-mcp.md) supports native client commands, direct configuration writes, confirmation links, and configuration generation. Its documented local-server workflow uses uv and declared Python dependencies. Conda-mcp works from an installed conda package environment, so the client does not need to resolve dependencies at launch. The live greeting-server demo uses FastMCP's client to exercise the generated connection.

## Conda ecosystem precedents

### conda-cli-mcp and conda-meta-mcp

[Conda-cli-mcp](https://github.com/jezdez/conda-cli-mcp) is the predecessor of the built-in CLI server. Its released 0.2.0 interface provided both `ccm` and a bare `conda mcp` server launcher. The merger described in [#1](https://github.com/jezdez/conda-mcp/issues/1) brought that implementation into conda-mcp and gave the combined package sole ownership of the conda subcommand.

| Operation | Command |
| --- | --- |
| Discover installed server declarations | `conda mcp list` |
| Configure a client entry | `conda mcp register SERVER --client CLIENT` |
| Launch a selected packaged server | `conda mcp run SERVER` |
| Expose a conda installation through MCP | `conda mcp serve` |

Bare `conda mcp` displays help. The merged package does not install `ccm`, and the old bare-server invocation is not an alias for `serve`. Existing clients must use `conda mcp serve`, carrying over target selection, permission flags, limits, and environment references. The predecessor's plugin and the merged plugin must not be installed together in the same tools environment because both register `mcp`.

[Conda-meta-mcp](https://github.com/conda-incubator/conda-meta-mcp) remains an independent server for ecosystem queries such as package search, import/file mappings, PyPI-to-conda mapping, CLI help, and dependency queries. It provides the standalone `cmm run` and `cmm mcp-json` commands, with no conda subcommand registration. Read-only metadata queries can contact services and use caches. They are different from conda-mcp's local installed-declaration scan, and conda-meta-mcp is not a dependency needed to use that scan or the CLI server.

### conda-global and conda-exec

[Conda-global](https://conda-incubator.github.io/conda-global/) manages persistent tool environments, exposes commands through `conda-trampoline`, and records desired tools in a manifest for update and sync. Its [binary exposure](https://conda-incubator.github.io/conda-global/features/) uses conda package ownership metadata. It is a close precedent for keeping reusable server executables separate from project dependencies.

Tool provisioning and client registration remain separate jobs. Exposing a binary on `PATH` does not give a client an MCP entry. Conda-global's documented trampoline sets paths and configured variables without shell activation, so it is not a substitute for the packaged-server runner's activation hooks, source revalidation, stream protection, and child-process cleanup. Conda-mcp does not duplicate conda-global's global environment manager.

[Conda-exec](https://conda-incubator.github.io/conda-exec/) starts from package specifications or script metadata, creates or reuses a cached environment, and runs a command. It supports channels, additional dependencies, PEP 723 scripts, and script locks. Its standalone `ce` launcher avoids the normal conda CLI plugin-loading path.

Conda-exec can solve and install on a cache miss. Conda-mcp's packaged-server runner launches from an existing prefix and does no installation. Conda-exec's [activation mode](https://conda-incubator.github.io/conda-exec/how-to/use-activation/) computes environment variables but does not execute `activate.d` scripts. Its cache lifetime and execution semantics must not be mistaken for a durable registered environment. In particular, passive discovery must not trigger a conda-exec installation.

### Package metadata and menuinst

[Menuinst](https://conda.github.io/menuinst/conda/) ships declarative launch metadata inside packages and translates it into operating-system shortcuts. This is a close precedent for package-owned MCP declarations: package names, declaration names, and external launch artifacts have different lifecycles.

Conda-mcp keeps registration explicit. A package transaction alone does not identify the intended project, client, or configuration scope, and cannot grant approval to call MCP tools. Project receipts can live outside the source prefix. Package removal cannot safely search arbitrary projects and rewrite their client configuration, so unregistering remains possible after the source environment disappears.

### Environments, workspaces, and exports

Recipes declare runtime dependencies, version constraints, and platform requirements. Conda's solver selects compatible builds from configured channels. [Conda export](https://docs.conda.io/projects/conda/en/stable/commands/export.html) distinguishes portable requested dependencies from explicit resolved packages. [Conda-workspaces](https://conda-incubator.github.io/conda-workspaces/features/environments/) adds named environments, features, activation settings, and locked installation.

A reproducible setup uses these tools for both the tools environment and the server environment, then generates local client entries after installation. The declaration describes the server interface and launch requirements. The registration records local configuration. Neither replaces an environment specification or lockfile.

[Conda-pack](https://conda.github.io/conda-pack/) provides environment archives and relocation support within its platform constraints. Relocating a source environment does not rewrite client entries stored outside it or include a separate tools environment automatically. Generate entries again at the destination. Copying a client config alone does not recreate its dependencies.

### Activation and exposed commands

[Conda run](https://docs.conda.io/projects/conda/en/stable/commands/run.html) and [Pixi global tools](https://pixi.sh/latest/global_tools/introduction/) already launch commands in prepared environments. Conda-mcp's packaged-server runner adds package-owned executable resolution, post-activation source checks, protocol stream protection, and process cleanup around native conda activation.

Putting a prefix's `bin` directory on `PATH` loses activation scripts and environment state, particularly on Windows. Normal `conda run --no-capture-output` also does not by itself establish the runner's guarantee that activation cannot consume protocol stdin or write to protocol stdout. These requirements explain why the runner has more machinery than an exposed executable.

The CLI server has a different execution path. It invokes conda commands with an argv list, captures bounded results, and serializes calls. It does not route every conda operation through the packaged-server runner. Discovery of a separately selected conda installation runs under that target's interpreter, without requiring the MCP SDK or this package to be installed there.

## Design limits

### Permissions are separate from package ownership

The CLI server defaults to read-only operations. Mutations require `--allow-write`, and arbitrary execution requires `--allow-exec`. Enabling execution does not imply permission for conda-managed mutations. Client approval and server startup policy are separate controls.

The built-in manager's passive operations remain passive when exposed through MCP. Registration writes require write permission, and launching a packaged server requires execution permission. `serve` is not an automatically callable generated tool that starts another long-lived server. Raw execution is still arbitrary execution, so excluding that generated tool is not a general recursion or sandbox guarantee.

Permission classification must describe the selected target's actual command implementation. An unrelated plugin using a familiar command name does not inherit the built-in manager's read-only classification. Package ownership likewise does not make server code safe to execute.

### Provenance, availability, and protocol health answer different questions

A declaration receipt records the provider and configuration accepted at registration. Installed package records attribute files to packages. Executable checks determine whether a recorded launch target is available. A live client session determines whether a server initializes and responds. None of these signals substitutes for the others.

For example, an unchanged declaration provider does not establish that the package owning its executable is unchanged. It also says nothing about the tools interpreter or every dependency in the source environment. Provenance and availability diagnostics must not be presented as a live health check.

`PrefixData` and `PrefixRecord` provide the installed inventory. [Conda doctor](https://docs.conda.io/projects/conda/en/stable/commands/doctor.html) provides relevant installation checks, and conda's [health-check hook](https://docs.conda.io/projects/conda/en/stable/dev-guide/plugins/health_checks.html) supports additional passive diagnostics. These checks do not establish publisher trust or replace MCP initialization and tool calls.

### Local configuration is not an artifact pin

Generated stdio entries refer to a tools interpreter and an installed source prefix. Those locations can change independently. An environment name resolves through local conda configuration, and copying a project does not rewrite its stored paths.

A receipt or package-name check does not freeze the environment. Exact package selection belongs with native package specifications, explicit exports, and locks. `PrefixRecord.to_match_spec()` and `PrefixData.query()` can describe and find a selected build, but matching that build does not verify all its installed files or lock every dependency. Regenerate local entries after relocation and review them after changing either environment.

### Client policy is not package metadata

A package-derived command or URL does not own a client's disablement, approval, tool filters, or timeout policy. Updating a generated connection must preserve those decisions and refuse ambiguous edits. Removing an entry and registering it again is not a policy-preserving refresh: the replacement cannot infer settings that were deleted.

`render` is the alternative when a client configuration is outside the supported write format. Kilo can use commented or layered configuration that the strict-JSON writer deliberately leaves untouched. A selected file and its receipt do not reveal the client's effective configuration across all layers.

### Installed discovery needs recorded declarations

An MCP-capable package is discoverable only when an installed package records its declaration. The built-in CLI server follows that package-owned declaration model. Other servers need declarations in their own packages or maintained companion packages with the appropriate runtime dependencies. A project comparison is not evidence that its package already ships one.

The [official MCP Registry](https://modelcontextprotocol.io/registry/about) publishes server metadata separately from package registries. Its [documented package types](https://modelcontextprotocol.io/registry/package-types) did not include conda when these sources were reviewed. A `registry_name` is informational, not a verified publisher identity or an automatic conda package lookup. Name similarity must not be used to infer an artifact mapping.

### Native API reuse does not guarantee unlimited compatibility

Conda activation wrappers, Windows executable search, and argparse discovery depend on behavior that can change between conda versions. The host conda running the plugin and a separately selected target conda are also distinct installations. Their supported ranges need separate compatibility evidence.

A lockfile solve does not prove a native launch works. Python-version coverage or Windows-targeted typing does not replace Windows execution. Conda-version and platform tests must cover activation noise and failure, environment state, protocol streams, cancellation, and child-process cleanup. Simplifying the launcher must preserve those behaviors.

## Misconceptions to avoid

| Assumption | What the primitives provide |
| --- | --- |
| An environment is a sandbox. | Conda isolates dependencies. Activation hooks and server code run with the user's OS privileges. Python `-I` is not a security sandbox. |
| A package record proves authentic, unchanged code. | A record attributes paths to a package. A declaration digest covers one file, not every executable, dependency, or activation hook. Artifact verification and channel policy are separate concerns. |
| A registration or receipt is an environment lock. | It describes a local client entry and its source metadata. Native exports and locks describe software installation. |
| `noarch` metadata makes every server portable. | A declaration-only package can depend on platform-specific executables. Dependencies and virtual-package constraints still determine where it can be installed. |
| Declaring an environment variable supplies its value. | A stdio declaration records names and requiredness. Values come from the client process or activation. [Conda environment variables](https://docs.conda.io/projects/conda/en/stable/user-guide/tasks/manage-environments.html#setting-environment-variables) are stored values that can appear in exports, not a secret vault. |
| Switching solvers makes passive discovery faster. | Solvers resolve dependencies during environment operations. Selecting rattler does not disable other installed plugins or remove their import costs. |
| Every file inside a prefix satisfies ownership checks. | Pip-installed or editable projects need a supported recorded packaging route. Installing inside a conda prefix alone is not enough. |
| Serving conda means reimplementing conda. | The MCP server validates and authorizes requests, then invokes conda. Conda owns solving, transactions, configuration, and its normal plugin hooks. |

## Sources and scope

The linked upstream documentation was reviewed on November 23, 2026. The historical CLI-server comparison refers to [conda-cli-mcp 0.2.0](https://github.com/jezdez/conda-cli-mcp/releases/tag/0.2.0). Project descriptions explain the division of responsibilities, not tested interoperability with every version of those projects.

Conda-mcp does not add a gateway, OAuth store, general-purpose MCP client, or another environment manager. Native clients own their sessions and approval. Conda owns software installation, and dedicated ecosystem tools retain their own metadata, provisioning, and execution roles.
