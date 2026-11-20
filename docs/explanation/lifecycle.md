# Lifecycle and safety

Conda-mcp reads package records from one selected environment. It does not install packages, solve dependencies, create environments, contact remote servers, or launch servers during discovery, inspection, configuration export, registration, or status checks.

`link` records a client configuration entry and receipt. Existing conflicts are reported instead of overwritten. `unlink` removes only a registration it can identify safely, preserving the package and unrelated client configuration. If a write was interrupted, inspect `status` and resolve the reported conflict before retrying.

Conda updates and removals are native lifecycle operations. An update can change a declaration or executable after registration. A removed package can leave a client registration pointing at an unavailable server. Unlink that registration after removal. Registration receipts describe configuration changes, not package ownership or activation trust.

The foreground runner uses conda's native activation wrapper and a fixed host-Python trampoline. Package activation and deactivation hooks execute with the user's privileges. The wrapper receives null stdin and sends both output streams to diagnostic stderr. Saved protocol descriptors or Windows handles are restored only after activation and a fresh manifest/executable check. Literal argv travels in bounded reserved environment data that is removed before server execution.

On POSIX, the wrapper starts in a separate process group. Interrupts are forwarded once. Remaining group members are killed after a bounded grace period and the wrapper is reaped. A process deliberately escaping its group, or an uncatchable parent termination, is outside this cleanup guarantee. On Windows, the wrapper starts suspended and joins a non-inherited kill-on-close Job Object before it resumes. Closing the parent job handle terminates contained descendants. Neither path restarts a server or detaches it as a service.

These controls keep activation output out of the protocol and bound normal process cleanup. They do not sandbox package code. A trusted hook can execute arbitrary code with the user's permissions. The bridge does not parse MCP messages, retain transcripts, add a protocol handshake, or host an HTTP server.
