# Lifecycle and safety

This page describes the manager's package and registration lifecycle and the process cleanup used by `run` and `serve`. For command discovery and the built-in server's permission model, see {doc}`serving`.

Conda-mcp reads package records from one selected environment. It does not install packages, solve dependencies, create environments, contact remote servers, or launch servers during discovery, inspection, rendering, registration, or registry listing.

`register` records a client configuration entry and receipt. Existing conflicts are reported instead of overwritten. `unregister` removes only a registration it can identify safely, preserving the package and unrelated client configuration. If a write was interrupted, inspect `registry` and resolve the reported conflict before retrying.

Conda updates and removals are native lifecycle operations. An update can change a declaration or executable after registration. A removed package can leave a client registration pointing at an unavailable server. Unregister that registration after removal. Registration receipts describe configuration changes, not package ownership or activation trust.

The foreground runner uses conda's native activation wrapper and a fixed host-Python trampoline. Package activation and deactivation hooks execute with the user's privileges. The wrapper receives null stdin and sends both output streams to diagnostic stderr. Saved protocol descriptors or Windows handles are restored only after activation and a fresh manifest/executable check. Literal argv travels in bounded reserved environment data that is removed before server execution.

On POSIX, the wrapper starts in a separate process group. Interrupts are forwarded once. Remaining group members are killed after a bounded grace period and the wrapper is reaped. A process deliberately escaping its group, or an uncatchable parent termination, is outside this cleanup guarantee. Neither platform restarts a server or detaches it as a service.

Windows process containment requires Windows 10 or Windows Server 2016 or newer and pywin32. The foreground runner creates a non-inheritable kill-on-close Job Object before starting the activation wrapper. Windows assigns the wrapper to that job during process creation through `PROC_THREAD_ATTRIBUTE_JOB_LIST`, so it cannot execute before assignment. The inherited-handle list contains only the saved protocol handles, diagnostic output, and null input. The job handle stays with the runner. An incompatible enclosing job or unsupported creation attribute fails the launch without retrying outside containment or enabling breakaway. Reaping the wrapper closes its job and terminates remaining descendants, including descendants holding protocol pipes open. Owner death also closes the job's owning handle.

On Windows, commands invoked through `serve` keep asyncio's subprocess and stream handling. Each command starts suspended in a new process group, joins its job, then resumes. Owner death after assignment terminates the command tree, but owner death between suspended creation and assignment can leave a suspended child. The executor continues draining output until EOF or the command timeout even when the root process has exited. After forced termination, root reaping and outstanding I/O share a five-second cleanup deadline. Cleanup failures are reported without replacing an original launch error or interruption. These controls do not make interpreter shutdown during asyncio-owned process creation safe.

These controls keep activation output out of the protocol and bound normal process cleanup. They do not sandbox package code. A trusted hook can execute arbitrary code with the user's permissions. The bridge does not parse MCP messages, retain transcripts, add a protocol handshake, or host an HTTP server.

## Relationship to other tools

See {doc}`prior-art` for comparisons with other MCP and conda tools.

[FastMCP](https://gofastmcp.com/docs/cli/install-mcp) generates client configuration and provides commands for live tool discovery and invocation. Conda-mcp renders entries from recorded package declarations instead of importing server code. The live demo uses FastMCP's existing client commands to exercise those entries.

[Docker MCP Toolkit](https://docs.docker.com/ai/mcp-catalog-and-toolkit/cli/) separates packaged servers from client configuration through profiles and a gateway. Conda-mcp registers each server directly with the client and starts local servers in their conda environments. It does not add a gateway or profile store.

Conda owns package installation and environment exports. Clients own MCP sessions, authentication, and approval. Here, `registry` means local client registrations, not a public server catalogue. `render` prints a native snippet with machine-specific paths, so it is not a portable backup and has no corresponding import command.
