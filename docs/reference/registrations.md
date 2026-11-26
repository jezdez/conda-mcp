# Registration states

`conda mcp registry` reports entries in selected local client configuration files. It does not contact servers or query a public catalogue. `--client CLIENT` selects one client. With no client, or with `--all`, it reports the supported targets in that scope and reports shared paths once. Claude Desktop is skipped in project scope unless explicitly selected, which produces a scope error.

(registration-entry-state)=
## Entry state

| `state` | Meaning |
| --- | --- |
| `managed` | The entry matches its registration receipt. |
| `edited` | A receipt exists, but the current entry differs from its recorded fingerprint. |
| `unmanaged` | An entry exists without a receipt. |
| `absent` | A receipt exists, but the configuration no longer contains that entry. |
| `pending` | The receipt records an interrupted operation for this entry. |

These states describe configuration ownership, not client approval or server health.

(registration-source-state)=
## Recorded source state

| `source_state` | Meaning |
| --- | --- |
| `current` | The declaration and recorded package provenance match the receipt. |
| `changed` | The same provider still declares the server, but recorded source details have changed. |
| `provider-changed` | Another package now provides that server name. |
| `missing` | The source environment or declaration is absent. |
| `invalid` | Source discovery failed. |
| `unknown` | No receipt is available to identify a source. |

A row can be `managed` and `missing` at the same time: its configuration is unchanged, but its server package is gone. Source checks inspect the receipt's prefix, not every environment on the machine.

## JSON output

`registry --json` returns an array. Every row contains `name`, `client`, `path`, `state`, `source_state`, and `shared_clients`. Claude Code and Copilot share their project configuration and receipt, so both appear in `shared_clients` for that path.

`register --json` and `unregister --json` return an object containing `name`, `client`, `path`, `changed`, `removed`, and `shared_clients`. Registration also includes the proposed `entry`. A dry run returns the proposed result without writing configuration or receipts.

`render --json` returns `path`, `format`, and `snippet`. The snippet is a string containing native JSON or TOML. Without `--json`, `render` prints that native snippet directly.

## Receipts and recovery

The {term}`registration receipt` is adjacent to the client configuration and named `<config-filename>.conda-mcp.json`. It records source provenance and entry fingerprints. An interrupted operation includes before/after entry fingerprints and receipt records. Recovery compares the current selected entry with those states. It never restores an old copy of the whole configuration file.

`registry` reports a pending operation without resolving it. A subsequent mutation checks whether recovery is unambiguous. A dry run can preview recovery, but only an actual mutation persists it. `--force` on unregistration does not override an ambiguous pending operation, malformed files, or unsafe paths.

For the steps to take for each state, see {doc}`../how-to/recover-registrations`.
