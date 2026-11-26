# Recover or replace a registration

Use this guide after changing client configuration, updating a server package, removing an environment, or interrupting a registration write. Keep unrelated entries and client policy settings intact while repairing the selected server.

The examples use `fastmcp-example` in `mcp-servers` and a project-local Codex entry. Substitute your server, source environment, and client. Add `--global` consistently when working on user configuration.

::::{dropdown} Watch an edited entry being replaced
```{figure} ../../demos/recover-registration.gif
:alt: Terminal recording of an edited registration being removed after a preview and replaced with a managed entry.

The {ref}`recovery recording <demo-recover-registration>` includes the commands and shows which custom setting is removed.
```
::::

## Inspect before changing files

Stop the affected server through the client, then inspect the selected scope:

```sh
conda mcp registry --client codex --json
```

Check both the {ref}`entry state <registration-entry-state>` and {ref}`source state <registration-source-state>`. Before manual edits, make a local backup of the configuration and its adjacent receipt. Keep backups private because existing client configuration can contain settings or credentials unrelated to conda-mcp.

## Refresh an unchanged entry after a package update

If the entry is `managed` and the source is `changed`, review the new source before refreshing its receipt:

```sh
conda mcp inspect fastmcp-example -n mcp-servers
conda mcp register fastmcp-example -n mcp-servers --client codex --dry-run
conda mcp register fastmcp-example -n mcp-servers --client codex
```

A source update does not grant trust to new package code. Review the package, declared executable, arguments, and activation behaviour before restarting the client. Even when the launch command stays the same, a receipt refresh can change its recorded package version or manifest digest.

Repeat any custom startup arguments after `--`. Registering without them restores the packaged defaults. See {doc}`enable-operations` for an example that keeps permission options in a managed registration.

## Remove an entry whose source is gone

Unregistration uses the receipt and client configuration. It does not require the original package to remain installed:

```sh
conda mcp unregister fastmcp-example --client codex --dry-run
conda mcp unregister fastmcp-example --client codex
```

Use this for a `managed` entry with a `missing` source. An `absent` entry can also have its leftover receipt removed this way. Discovery never recreates a missing environment.

(recover-edited-registration)=
## Replace an edited or unmanaged entry

Decide whether to keep the custom configuration. If you want to keep it, manage the entry through the client. Conda-mcp will continue to report it as edited or unmanaged.

To replace it with a freshly rendered managed entry, back it up, review the proposed removal, then remove only that entry:

```sh
conda mcp unregister fastmcp-example --client codex --force --dry-run
conda mcp unregister fastmcp-example --client codex --force
```

After reviewing the installed server, register it again with the preview-and-register commands above. `register` has no `--force` option. Custom per-server settings in the removed entry are not carried into the new entry automatically.

Use the same remove-and-register sequence for a `provider-changed` source, after deciding to trust the new provider. The generated command deliberately requires the recorded manifest owner.

## Resolve an interrupted operation

For `pending`, repeat the intended operation with `--dry-run` first. If the actual entry matches the recorded before or after state, conda-mcp can reconcile its receipt. Run the operation without `--dry-run` to persist that recovery.

:::{admonition} Ambiguous recovery
:class: warning

If conda-mcp reports an ambiguous interrupted registration, stop. Neither retrying with `--force` nor deleting the receipt can determine which edit to preserve. Compare your private backups with the current selected entry. Restore a known consistent configuration-and-receipt pair, or resolve the conflict manually before retrying. Do not restore a whole-file backup over unrelated changes made since that backup.
:::

## Handle configuration errors

Malformed JSON or TOML and redirected or unsafe paths must be repaired before mutation. A force removal does not bypass these checks. For an `invalid` source, inspect the installed declaration and package records before trying to replace it.

Kilo may refuse a change because another configuration layer is JSONC or contains the same server name. Preserve those layers and use `render` to obtain a snippet for manual client configuration. Its `registry` output describes the selected strict-JSON file, not Kilo's effective merged configuration.

Finally, run `registry` again and restart the server through the client. A `managed` row confirms configuration ownership. Make a real client call separately to confirm that the server works.
