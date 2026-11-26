# Configure the built-in conda server

Use this guide to connect an MCP client to a specific conda installation, set execution limits, or customise its startup options. Install conda-mcp in that installation first, following {doc}`install`.

## Choose a launch method

A conda package installation includes a `conda-cli` declaration. Activate the installation from {doc}`install`, then preview and register it from your project directory:

```sh
conda activate base
conda mcp register conda-cli --client codex --dry-run
conda mcp register conda-cli --client codex
```

Replace `codex` with the supported client you use. Add `--global` for user scope. Claude Desktop requires global scope. The current directory selects project configuration, independently of the source environment. Use `-n NAME` when the source is in another environment.

Registration records a command that activates the source environment through `conda mcp run`. It does not launch the client, approve the server, or change client trust settings. Restart or reload the server using the client's normal controls after registration.

Append startup arguments after `--` to change permissions or limits, as shown below and in {doc}`enable-operations`. For a wheel installation, use a direct `serve` entry.

## Configure a direct entry

Activate the installation containing conda-mcp and print its Python executable:

```sh
python -c "import sys; print(sys.executable)"
python -I -m conda mcp serve --version
```

Use that absolute path as the client command. Select the example for your platform:

::::{tab-set}
:sync-group: platform

:::{tab-item} Linux and macOS
:sync: posix

For clients accepting an `mcpServers` JSON document:

```json
{
  "mcpServers": {
    "conda": {
      "command": "/absolute/path/to/mcp-tools/bin/python",
      "args": ["-I", "-m", "conda", "mcp", "serve"]
    }
  }
}
```

Codex uses a TOML entry instead:

```toml
[mcp_servers.conda]
command = "/absolute/path/to/mcp-tools/bin/python"
args = ["-I", "-m", "conda", "mcp", "serve"]
```
:::

:::{tab-item} Windows
:sync: windows

Use the environment's `python.exe` and escape backslashes in JSON:

```json
{
  "mcpServers": {
    "conda": {
      "command": "C:\\absolute\\path\\to\\mcp-tools\\python.exe",
      "args": ["-I", "-m", "conda", "mcp", "serve"]
    }
  }
}
```

For Codex, a literal TOML string keeps Windows backslashes unchanged:

```toml
[mcp_servers.conda]
command = 'C:\absolute\path\to\mcp-tools\python.exe'
args = ["-I", "-m", "conda", "mcp", "serve"]
```
:::

::::

Merge the selected entry into the client's existing configuration, preserving other entries and settings. The paths above are placeholders. Direct entries are managed by you or the client and have no conda-mcp registration receipt.

You can also use that installation's absolute conda executable with `mcp serve`. On Windows, select `conda.exe`, not a `.bat` or `.cmd` wrapper. Do not depend on a GUI client's `PATH` or a terminal's shell function to find the intended installation.

## Set command limits

Update a managed registration with the desired limits:

```sh
conda mcp register conda-cli --client codex -- --timeout 120 --output-limit-bytes 2097152 --stdin-limit-bytes 65536
```

Include any permission options you want to keep. Each registration replaces the previous startup arguments. For a direct `serve` entry, the equivalent argument array is:

```json
["-I", "-m", "conda", "mcp", "serve", "--timeout", "120", "--output-limit-bytes", "2097152", "--stdin-limit-bytes", "65536"]
```

The timeout must be finite and positive. Both byte limits must be positive integers. Output limits apply separately to stdout and stderr. Excess output is drained and marked as truncated. The stdin limit counts UTF-8 bytes, not characters.

The raw tool may request a shorter timeout, but cannot raise the server limit. Generated tools use the server timeout. These settings take effect after restarting the server. See the reference for {option}`conda mcp serve --timeout`, {option}`conda mcp serve --output-limit-bytes`, and {option}`conda mcp serve --stdin-limit-bytes`.

## Select another installation

Install conda-mcp alongside the other conda and configure another entry using its absolute interpreter or conda executable. There is no `--conda-exe` option. Neither inherited `CONDA_EXE` nor another executable on `PATH` changes the serving installation.

Command arguments such as `--name` and `--prefix` select an environment for an individual conda operation. They do not change which installed plugins define the server's tools.

## Diagnose startup and request problems

| Symptom | Action |
| --- | --- |
| `mcp` is an invalid conda command | Run `python -I -m conda mcp --help` with the configured interpreter. Check that conda-mcp is installed there and plugins are enabled. |
| `conda-cli` is absent from `list` | Confirm a conda package installation and the selected source prefix. A wheel has no recorded declaration. |
| Client startup waits with no terminal output | `serve` speaks MCP on stdio and waits for a client. Use a real client, as in the tutorial. |
| A visible tool requires a startup flag | Follow {doc}`enable-operations` and restart. Client approval alone does not change server policy. |
| A command waits for input | Use conda's noninteractive options. No interactive terminal is allocated. Only the raw tool accepts bounded stdin. |
| Returned output is incomplete | Inspect `stdout_truncated` and `stderr_truncated`, then raise the appropriate startup limit if needed. |
| New plugin commands are missing | Follow {doc}`refresh-plugin-tools` and inspect catalogue diagnostics. |

Keep protocol stdout available to the client. Do not insert banners, shell prompts, or output-capturing wrappers into the server command. To inspect startup diagnostics, use the client's server log or stderr capture.

Shell interpolation, pipes, and redirection are not supported inside tool argv. An activation command cannot activate an environment in the MCP host's shell. See {doc}`../explanation/serving` for the process model.
