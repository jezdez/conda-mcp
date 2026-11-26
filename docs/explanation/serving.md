# How conda becomes an MCP server

Conda-mcp's manager reads declarations installed by packages and connects those servers to clients. Its built-in server exposes conda's own commands. Registration only reads metadata and writes configuration. An MCP tool call can run conda and its plugins.

## Two execution paths

For a packaged stdio server, the client starts conda-mcp's direct stdio launcher. The runner activates the selected environment, checks the recorded declaration and executable, and forwards protocol streams to that server. The server defines its own MCP tools. Conda-mcp does not inspect or authorise those individual tool calls.

For the built-in conda server, the client starts the direct stdio launcher with `serve`. This process handles MCP requests, validates tool input, checks its startup permissions, and executes conda commands in child processes. The conda package's `conda-cli` declaration connects the two paths: registering it makes the manager launch the built-in server as a packaged server. The launcher reserves protocol stdout before loading conda plugins and sends startup output to stderr.

The {term}`serving installation` determines the conda command catalogue and installed plugins. An environment selected by a command's `-n` or `-p` can be a target of that command, but does not become a different serving installation.

## Discovery and structured arguments

At startup, conda builds its parser with the installed subcommand plugins. Conda-mcp inspects that parser in process and converts supported actions into immutable command and argument values. It derives JSON Schemas and deterministic tool names from those values. The runtime catalogue retains the converted values, not the argparse parser objects.

This reuses the command definitions that conda and its plugins already maintain. It also requires explicit conversion for argparse actions such as repeated options, optional values, and mutually exclusive groups. JSON Schema validation checks a client's structured request before the adapter converts it into argv. Conda parses the resulting argv again when the child command starts.

Argparse has no public command-tree inspection API. The discovery adapter therefore isolates the inspection logic and reports unsupported actions. A command that cannot be represented safely remains raw-only. The optional raw tool lets a client supply argv for such commands with explicit execution permission.

Discovery imports installed plugin code and runs parser configuration callbacks. A read-only serving policy does not sandbox that startup code. Only install plugins you trust in the serving environment.

## Why the catalogue stays fixed

Clients discover tools and their input schemas before calling them. Keeping that interface fixed for a session avoids changing a tool's meaning while a client is preparing a request.

Conda and plugin changes can still make the snapshot outdated. The server records a fingerprint and checks it after successful operations that may change installed software. It reports `restart_required` instead of replacing tools during the session. External package changes also call for a restart, even if no subsequent operation has detected them yet.

Conda-completion contributes optional completion hints through its public manifest API. Those hints are read from its existing cache. Generated MCP tools come from the argparse catalogue. Regenerating the completion cache does not rebuild those tools.

## Conda retains command behaviour

Each invocation runs the serving installation's conda executable in a fresh process. Conda loads configuration, selects solvers, authenticates, runs command and transaction hooks, and performs the requested operation. Hooks that do not define subcommands still participate through conda's normal lifecycle. They do not become separate MCP tools.

The executor passes literal argv without a shell and bounds command time and retained output. It does not allocate an interactive terminal. Activation commands can return shell code, but a child process cannot change the shell or environment of the MCP client that launched it.

This differs from the old `conda-cli-mcp` design. That project could run a separate server environment against a selected conda installation and used helper processes for discovery. `conda mcp serve` uses the invoking installation and performs discovery in that process. Command execution still uses child processes.

## Permissions describe operations

Read-only mode allows known inspection operations, including network reads such as package searches. It is not an offline mode. Some commands are classified by their arguments: exporting to stdout can be read-only, while exporting to a file requires write permission. Recognised dry-run forms can be allowed without enabling writes.

`--allow-write` and `--allow-exec` are independent. The first permits operations classified as mutations. The second permits arbitrary process execution and exposes raw argv. Unknown commands are treated conservatively as mutations, and opaque passthrough interfaces also need execution permission. The examples in {doc}`../how-to/enable-operations` show these combinations.

An allowed arbitrary process can write files and access the network with the user's privileges. The permission flags classify entry points into conda, not the effects of every instruction a child program might run. Likewise, tool annotations help clients present a decision but do not enforce the server's policy. Client approval and server startup permissions both remain relevant.

Process groups and Windows Job Objects help terminate descendants. They do not restrict filesystem or network access. See {doc}`lifecycle` for activation, cleanup, and owner-death behaviour, and {doc}`../reference/mcp-interface` for the protocol fields clients receive.
