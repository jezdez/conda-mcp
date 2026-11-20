# Server declaration format

Declarations are JSON files installed at `share/conda-mcp/servers/NAME.json`. The installed package record must include that file. Unrecorded files are ignored.

```json
{
  "schema_version": 1,
  "name": "example-server",
  "description": "A local example server",
  "stdio": {"command": "example-server"}
}
```

Required fields are `schema_version`, `name`, and `description`. Version 1 accepts exactly one transport: `stdio` or `http`. The name uses lowercase ASCII letters, numbers, underscores, and hyphens, starts with a letter or number, and has at most 64 characters. See `src/conda_mcp/schema/server-v1.json` for the shipped schema.

An HTTP declaration stores its endpoint metadata. Discovery and configuration do not make a network request. Credential fields name environment variables and never contain credential values. Provenance comes from the conda package record that lists the declaration, while trust is a separate user decision.

## Local stdio

```json
{
  "schema_version": 1,
  "name": "catalog",
  "description": "Read-only catalog tools",
  "stdio": {
    "command": "catalog-server",
    "args": ["--stdio", "literal argument"],
    "environment": [{"name": "CATALOG_TOKEN", "required": true}]
  }
}
```

`command` is an executable basename, not a path or shell expression. Arguments are literal strings, including empty arguments. Commands ending in `.cmd` or `.bat` are rejected. An environment reference contains only `name` and a boolean `required`. Duplicate names, including case-insensitive collisions, are rejected. Required variables must be present after activation. An empty value counts as present.

Executable lookup follows conda's native executable-directory order inside the selected prefix. The selected path and any resolved symlink target must have unambiguous recorded package ownership. The executable may belong to a runtime dependency. An unrecorded file, escaping link, special file, or ambiguous owner causes a failure. Lookup never falls back to the ambient `PATH`.

## Remote HTTP

```json
{
  "schema_version": 1,
  "name": "remote-catalog",
  "description": "Hosted catalog tools",
  "http": {
    "url": "https://catalog.example.org/mcp",
    "bearer_token_env": "CATALOG_TOKEN",
    "header_env": {"X-Organization": "CATALOG_ORGANIZATION"}
  }
}
```

The endpoint must use HTTPS without user information, query, or fragment. Header mappings contain environment-variable names, never values. Transport-controlled headers, cookies, duplicate case-insensitive header names, and competing authorization fields are rejected. The client owns authentication, network access, consent, and transport behavior.

## Validation and provenance

Unknown fields, duplicate JSON keys, nonfinite numbers, invalid UTF-8, oversized manifests, and escaping paths are rejected. The description is nonblank and at most 1,024 characters. Windows device names are rejected on every platform. The optional `registry_name` is descriptive metadata. It does not assert that the official MCP Registry accepts conda packages.

Discovery only considers matching paths in installed `PrefixRecord.files`. A package can provide multiple declarations, but each name must have one provider. Output includes the selected prefix, relative manifest path, manifest SHA-256 digest, and record-derived package name, version, build, and channel. A later launch reloads those records. Same-owner updates apply on subsequent launches, while a provider replacement fails the generated exact-owner command.
