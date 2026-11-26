# How conda becomes an MCP server

Conda-mcp is a conda plugin with two roles. Its manager connects packaged MCP servers to clients. Its built-in server exposes conda's own commands as MCP tools. Registration reads installed declarations and writes client configuration and a receipt. The client starts a server later, when it opens a session.

## Two execution paths

For a packaged stdio server, the client starts conda-mcp's direct stdio launcher. The runner activates the selected environment, checks the recorded declaration and executable, and forwards protocol streams to that server. The server defines its own MCP tools. Conda-mcp does not inspect or authorise those individual tool calls.

For the built-in conda server, the client starts the direct stdio launcher with `serve`. This process handles MCP requests, validates tool input, checks its startup permissions, and executes conda commands in child processes. The conda-mcp conda package includes the `conda-cli` declaration, which connects the two paths: its managed entry uses `run` to activate the environment and start the built-in server. A manually configured `serve` entry starts that server directly. Both use a launcher that reserves protocol stdout before loading conda plugins and sends startup output to stderr.

```{mermaid}
:alt: The client uses run to activate a packaged stdio server, including the built-in server through conda-cli, or starts the built-in server through a direct serve entry. The built-in server executes allowed conda commands in child processes.
:caption: The client can start a packaged server with run or the built-in conda server with serve.

flowchart TB
    accTitle: Managed servers and the built-in conda server
    accDescr: The client uses run to activate a packaged stdio server, including the built-in server through conda-cli, or starts the built-in server through a direct serve entry. The built-in server executes allowed conda commands in child processes.
    client["MCP client"] -->|run SERVER entry| runner["Activate environment and recheck server"]
    runner -->|Other stdio declarations| packaged["Packaged MCP server"]
    runner -->|conda-cli declaration| builtin["Built-in conda server: serve"]
    client -->|Manual serve entry| builtin
    builtin -->|Allowed tool call| conda["Conda child process"]
```

The {term}`serving installation` determines the conda command catalogue and installed plugins. An environment selected by a command's `-n` or `-p` can be a target of that command, but does not become a different serving installation.

## Discovery and structured arguments

At startup, conda builds its parser with the installed subcommand plugins. Conda-mcp inspects that parser in process and converts supported actions into immutable command and argument values. It derives JSON Schemas and deterministic tool names from those values. The runtime catalogue retains the converted values, not the argparse parser objects.

This reuses the command definitions that conda and its plugins already maintain. It also requires explicit conversion for argparse actions such as repeated options, optional values, and mutually exclusive groups. JSON Schema validation checks a client's structured request before the adapter converts it into argv. Conda parses the resulting argv again when the child command starts.

```{mermaid}
:name: generated-tool-flow
:alt: Startup discovery builds conda's parser with its installed plugins, converts it into a fixed catalogue, and publishes tool names and schemas. Each generated tool call is validated and converted to argv, checked against startup permissions, and either rejected or executed in a conda child process.
:caption: Generated tools reuse the startup catalogue for every call.

flowchart LR
    accTitle: From installed conda commands to a generated tool call
    accDescr: Startup discovery builds conda's parser with its installed plugins, converts it into a fixed catalogue, and publishes tool names and schemas. Each generated tool call is validated and converted to argv, checked against startup permissions, and either rejected or executed in a conda child process.
    subgraph startup["At startup"]
        direction TB
        plugins["Conda and plugins"] --> parser["Build and inspect parser"]
        parser --> catalog["Fixed catalogue"]
        catalog --> tools["Tools and JSON Schemas"]
    end
    subgraph calls["Each generated tool call"]
        direction TB
        input["Structured arguments"] --> compile["Validate and build argv"]
        compile --> policy{"Allowed by policy?"}
        compile -->|Invalid input| error["MCP error"]
        policy -->|Denied| error
        policy -->|Allowed| child["Run conda child"]
        child --> result["Execution result"]
    end
    startup -.->|Catalogue and schemas| calls
```

The raw argv tool has its own input schema and shares the permission checks and executor.

Argparse has no public command-tree inspection API. The discovery adapter therefore isolates the inspection logic and reports unsupported actions. A command that cannot be represented safely remains raw-only. The optional raw tool lets a client supply argv for such commands with explicit execution permission.

Discovery imports installed plugin code and runs parser configuration callbacks. A read-only serving policy does not sandbox that startup code. Only install plugins you trust in the serving environment.

## Why the catalogue stays fixed

Clients discover tools and their input schemas before calling them. Keeping that interface fixed for a session avoids changing a tool's meaning while a client is preparing a request.

Conda and plugin changes can still make the snapshot outdated. The server checks a fingerprint after successful operations classified as non-read-only. A child process performs the check, keeping updated plugin code out of the running server. A changed fingerprint or failed check sets `restart_required`, which stays true for the rest of the session. Calls remain available using the same catalogue.

```{mermaid}
:alt: A new server discovers its catalogue and keeps serving that snapshot. A fingerprint change or failed check marks the session as requiring a restart without changing or disabling its tools. The client must restart the server to create a new snapshot, including after external package changes.
:caption: Only a new server process builds a new catalogue.

stateDiagram-v2
    accTitle: Catalogue lifetime and restart requests
    accDescr: A new server discovers its catalogue and keeps serving that snapshot. A fingerprint change or failed check marks the session as requiring a restart without changing or disabling its tools. The client must restart the server to create a new snapshot, including after external package changes.
    state "New server process" as Startup
    state "Serve the startup catalogue" as Serving
    state "Serve the same catalogue, restart_required = true" as RestartNeeded
    [*] --> Startup
    Startup --> Serving: Discover commands and plugins
    Serving --> RestartNeeded: Fingerprint changes or check fails
    RestartNeeded --> Startup: Client restarts the server
    Serving --> Startup: Client restarts after external changes
```

External package changes also call for a restart, even if no subsequent operation has detected them. Follow {doc}`../how-to/refresh-plugin-tools` to start a new session and check its tools.

Conda-completion contributes optional completion hints through its public manifest API. Those hints are read from its existing cache. Generated MCP tools come from the argparse catalogue. Regenerating the completion cache does not rebuild those tools.

## Conda retains command behaviour

Installed conda plugins participate at two points. Their subcommand definitions contribute to the startup catalogue. During each invocation, the serving installation's conda executable runs in a fresh process, where conda loads configuration, selects solvers, authenticates, and runs command and transaction hooks. Hooks that do not define subcommands still participate through this normal lifecycle. They do not become separate MCP tools.

The executor passes literal argv without a shell and bounds command time and retained output. It does not allocate an interactive terminal. Activation commands can return shell code, but a child process cannot change the shell or environment of the MCP client that launched it.

This differs from the old `conda-cli-mcp` design. That project could run a separate server environment against a selected conda installation and used helper processes for discovery. `conda mcp serve` uses the invoking installation and performs discovery in that process. Command execution still uses child processes.

## Permissions describe operations

Read-only mode allows known inspection operations, including network reads such as package searches. It is not an offline mode. Some commands are classified by their arguments: exporting to stdout can be read-only, while exporting to a file requires write permission. Recognised dry-run forms can be allowed without enabling writes.

`--allow-write` and `--allow-exec` are independent. The first permits operations classified as mutations. The second permits arbitrary process execution and exposes raw argv. Unknown commands are treated conservatively as mutations, and opaque passthrough interfaces also need execution permission. The examples in {doc}`../how-to/enable-operations` show these combinations.

An allowed arbitrary process can write files and access the network with the user's privileges. The permission flags classify entry points into conda, not the effects of every instruction a child program might run. Likewise, tool annotations help clients present a decision but do not enforce the server's policy. Client approval and server startup permissions both remain relevant.

Process groups and Windows Job Objects help terminate descendants. They do not restrict filesystem or network access. See {doc}`lifecycle` for activation, cleanup, and owner-death behaviour, and {doc}`../reference/mcp-interface` for the protocol fields clients receive.
