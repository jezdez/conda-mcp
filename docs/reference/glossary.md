# Glossary

```{glossary}
:sorted:

declaration
    A JSON file under `share/conda-mcp/servers/` that describes a local executable or a remote endpoint. Discovery requires the file to appear in an installed conda package record. See {doc}`server-format`.

provider
    The conda package that owns a server's declaration. For a wrapper package, the executable may belong to a runtime dependency instead. A generated launch command records the provider in `run --package`.

source prefix
    The existing conda environment from which the manager reads declarations and resolves a local server executable. Administrative commands select it with `-n` or `-p`. It does not determine where client configuration is written.

serving installation
    The conda installation that starts `conda mcp serve`. Its conda version and installed plugins determine the generated tools. An environment targeted by a tool call can be different from this installation.

project scope
    Client configuration selected from the command's current directory. Running in the user's home directory does not turn project scope into user scope.

user scope
    A client's user configuration, selected explicitly with `--global`. Support and destinations depend on the client. See {ref}`native-destinations`.

registration receipt
    The adjacent `<config-filename>.conda-mcp.json` file recording a managed entry's fingerprint and source provenance. It allows later updates and removal to detect manual edits. It does not record client approval or establish execution trust.
```
