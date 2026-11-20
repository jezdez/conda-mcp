"""Conda provenance receipts and recoverable native client registrations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path, PurePosixPath

from conda import CondaError
from conda.gateways.disk.lock import lock

from .clients.config import MAX_CONFIG_BYTES, ClientConfig, ConfigTarget
from .files import atomic_write, load_json, open_lock, read_bytes
from .servers import discover

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def fingerprint(entry: object) -> str:
    """Hash all entry fields, independent of JSON formatting."""
    return hashlib.sha256(
        json.dumps(
            entry,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ReceiptRecord:
    """Complete source provenance and the last complete rendered-entry digest."""

    prefix: str
    package: str
    manifest: str
    manifest_digest: str
    version: str
    build: str
    channel: str
    digest: str

    def __post_init__(self) -> None:
        """Validate provenance without reading the source or storing credentials."""
        if any(
            not isinstance(value, str) or not value for value in asdict(self).values()
        ):
            raise ValueError("Invalid registration source provenance.")
        prefix, manifest = Path(self.prefix), PurePosixPath(self.manifest)
        if (
            not _DIGEST.fullmatch(self.digest)
            or not _DIGEST.fullmatch(self.manifest_digest)
            or not prefix.is_absolute()
            or ".." in prefix.parts
            or manifest.is_absolute()
            or ".." in manifest.parts
            or "\\" in self.manifest
            or manifest.parent != PurePosixPath("share/conda-mcp/servers")
            or manifest.suffix != ".json"
        ):
            raise ValueError("Invalid registration source provenance.")

    @classmethod
    def from_dict(cls, value: object) -> ReceiptRecord:
        """Require exactly the current receipt fields, without coercing values."""
        if not isinstance(value, dict) or set(value) != {
            field.name for field in fields(cls)
        }:
            raise ValueError("Invalid registration source provenance.")
        return cls(**value)

    def to_dict(self) -> dict[str, str]:
        """Serialize the stable receipt schema, never a live server object."""
        return asdict(self)

    def source_state(self, name: str) -> str:
        """Inspect only this recorded source, never an environment registry."""
        prefix = Path(self.prefix)
        if not (prefix / "conda-meta").is_dir():
            return "missing"
        try:
            server = next(
                (server for server in discover(prefix) if server.name == name), None
            )
        except (CondaError, OSError, ValueError):
            return "invalid"
        if server is None:
            return "missing"
        if server.package != self.package:
            return "provider-changed"
        current = server.to_dict()
        return (
            "current"
            if all(
                current[key] == value
                for key, value in self.to_dict().items()
                if key != "digest"
            )
            else "changed"
        )


@dataclass(frozen=True)
class PendingIntent:
    """An interrupted operation containing only states and complete receipt records."""

    operation: str
    name: str
    before: str | None
    after: str | None
    previous: ReceiptRecord | None
    record: ReceiptRecord | None

    @classmethod
    def from_dict(cls, value: object, target: ConfigTarget) -> PendingIntent:
        """Validate both states and bind intent to this exact native destination."""
        if not isinstance(value, dict) or set(value) != {
            "operation",
            "target",
            "container",
            "key",
            "before",
            "after",
            "previous",
            "record",
        }:
            raise ValueError("Invalid pending receipt.")
        if (
            value["operation"] not in ("link", "unlink")
            or value["target"] != str(target.path)
            or value["container"] != target.key
            or not isinstance(value["key"], str)
            or not value["key"]
        ):
            raise ValueError("Invalid pending receipt.")
        states = []
        for key in ("before", "after"):
            state = value[key]
            if (
                isinstance(state, dict)
                and set(state) == {"absent"}
                and state["absent"] is True
            ):
                states.append(None)
            elif (
                isinstance(state, dict)
                and set(state) == {"digest"}
                and isinstance(state["digest"], str)
                and _DIGEST.fullmatch(state["digest"])
            ):
                states.append(state["digest"])
            else:
                raise ValueError("Invalid pending receipt.")
        previous = (
            ReceiptRecord.from_dict(value["previous"])
            if value["previous"] is not None
            else None
        )
        record = (
            ReceiptRecord.from_dict(value["record"])
            if value["record"] is not None
            else None
        )
        if any(
            item is not None and PurePosixPath(item.manifest).stem != value["key"]
            for item in (previous, record)
        ):
            raise ValueError("Invalid pending receipt.")
        if value["operation"] == "link":
            if record is None or states[1] != record.digest:
                raise ValueError("Invalid pending receipt.")
        elif record is not None or states[1] is not None:
            raise ValueError("Invalid pending receipt.")
        return cls(value["operation"], value["key"], *states, previous, record)

    def to_dict(self, target: ConfigTarget) -> dict:
        """Persist complete intent without copying the client configuration."""
        return {
            "operation": self.operation,
            "target": str(target.path),
            "container": target.key,
            "key": self.name,
            "before": {"digest": self.before}
            if self.before is not None
            else {"absent": True},
            "after": {"digest": self.after}
            if self.after is not None
            else {"absent": True},
            "previous": self.previous.to_dict() if self.previous else None,
            "record": self.record.to_dict() if self.record else None,
        }


@dataclass(frozen=True)
class Receipt:
    """An immutable receipt snapshot with validated recoverable operation state."""

    target: ConfigTarget
    raw: bytes | None
    entries: tuple[tuple[str, ReceiptRecord], ...] = ()
    pending: PendingIntent | None = None

    @property
    def path(self) -> Path:
        """Use the same adjacent receipt for clients sharing a native file."""
        return self.target.path.with_name(self.target.path.name + ".conda-mcp.json")

    @classmethod
    def load(cls, target: ConfigTarget) -> Receipt:
        """Read and validate the entire receipt before any mutation or recovery."""
        path = target.path.with_name(target.path.name + ".conda-mcp.json")
        raw = read_bytes(path, limit=MAX_CONFIG_BYTES, missing_ok=True)
        try:
            value = (
                load_json(raw)
                if raw is not None
                else {"schema_version": 1, "entries": {}}
            )
            entries = value.get("entries")
            if (
                set(value) - {"schema_version", "entries", "pending"}
                or type(value.get("schema_version")) is not int
                or value["schema_version"] != 1
                or not isinstance(entries, dict)
                or any(not isinstance(name, str) or not name for name in entries)
            ):
                raise ValueError
            records = tuple(
                (name, ReceiptRecord.from_dict(record))
                for name, record in entries.items()
            )
            if any(
                PurePosixPath(record.manifest).stem != name for name, record in records
            ):
                raise ValueError
            pending = (
                PendingIntent.from_dict(value["pending"], target)
                if "pending" in value
                else None
            )
            if pending and pending.previous != dict(records).get(pending.name):
                raise ValueError
            return cls(target, raw, records, pending)
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            raise CondaError(
                "Invalid registration receipt. Files left unchanged."
            ) from error

    def encode(self) -> bytes:
        """Serialize one complete receipt with no live credentials."""
        value: dict = {
            "schema_version": 1,
            "entries": {name: record.to_dict() for name, record in self.entries},
        }
        if self.pending:
            value["pending"] = self.pending.to_dict(self.target)
        return (
            json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")

    def with_record(self, name: str, record: ReceiptRecord | None) -> Receipt:
        """Return a finalized snapshot after changing one record."""
        entries = dict(self.entries)
        if record is None:
            entries.pop(name, None)
        else:
            entries[name] = record
        return replace(self, entries=tuple(entries.items()), pending=None)

    def recover(self, config: ClientConfig) -> Receipt:
        """Recover receipt state from the current entry without rewriting the config."""
        pending = self.pending
        if pending is None:
            return self
        table = config.entries
        actual = fingerprint(table[pending.name]) if pending.name in table else None
        if actual == pending.after:
            record = pending.record
        elif actual == pending.before:
            record = pending.previous
        else:
            raise CondaError(
                "Ambiguous interrupted registration. Files left unchanged."
            )
        return self.with_record(pending.name, record)


def registration(
    target: ConfigTarget,
    name: str | None = None,
    *,
    entry: dict | None = None,
    source: dict | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> list[dict] | dict:
    """Inspect or mutate an entry without looking up its source when unlinking."""
    try:
        preview = _registration(target, name, entry, source, force, write=False)
        if isinstance(preview, list) or dry_run or not preview["changed"]:
            return preview
        lock_path = target.path.with_name(target.path.name + ".conda-mcp.lock")
        with open_lock(lock_path) as stream, lock(stream):
            return _registration(target, name, entry, source, force, write=True)
    except (ValueError, RecursionError) as error:
        raise CondaError(str(error)) from error


def _registration(
    target: ConfigTarget,
    name: str | None,
    entry: dict | None,
    source: dict | None,
    force: bool,
    *,
    write: bool,
) -> list[dict] | dict:
    """Plan against current files and write only while the caller holds the lock."""
    config = ClientConfig.from_bytes(
        target, read_bytes(target.path, limit=MAX_CONFIG_BYTES, missing_ok=True)
    )
    table = config.entries
    receipt = Receipt.load(target)
    entries = dict(receipt.entries)
    pending = receipt.pending
    if name is None:
        result = []
        for key in sorted(
            table.keys() | entries.keys() | ({pending.name} if pending else set())
        ):
            record = entries.get(key)
            state = (
                "pending"
                if pending and pending.name == key
                else "absent"
                if key not in table
                else "unmanaged"
                if record is None
                else "managed"
                if record.digest == fingerprint(table[key])
                else "edited"
            )
            result.append(
                {
                    "name": key,
                    "client": target.client,
                    "path": str(target.path),
                    "state": state,
                    "source_state": record.source_state(key) if record else "unknown",
                    "effective_state": "unknown",
                    "shared_clients": target.shared_clients,
                }
            )
        return result

    if pending:
        receipt = receipt.recover(config)
        if write:
            encoded = receipt.encode()
            atomic_write(receipt.path, encoded, receipt.raw, limit=MAX_CONFIG_BYTES)
            receipt = replace(receipt, raw=encoded)
    old_record = dict(receipt.entries).get(name)
    present = name in table
    before = fingerprint(table[name]) if present else None
    if present and (old_record is None or old_record.digest != before) and not force:
        raise CondaError(
            "Refusing to replace an unmanaged or edited entry. "
            "Inspect status or use --force."
        )
    record = (
        ReceiptRecord.from_dict({**(source or {}), "digest": fingerprint(entry)})
        if entry is not None
        else None
    )
    if record:
        if (
            old_record
            and (old_record.prefix, old_record.package, old_record.manifest)
            != (record.prefix, record.package, record.manifest)
            and not force
        ):
            raise CondaError(
                "Entry belongs to a different provider. Use --force to replace it."
            )
        if record.source_state(name) != "current":
            raise CondaError("Registration source changed or is unavailable.")
    after = record.digest if record else None
    changed = before != after or old_record != record
    result = {
        "name": name,
        "client": target.client,
        "path": str(target.path),
        "changed": changed or pending is not None,
        "removed": entry is None and present,
        "shared_clients": target.shared_clients,
    }
    if entry is not None:
        result["entry"] = entry
    if changed or entry is not None:
        target.check_layers(name)
    if not changed:
        return result
    rendered = config.render(name, entry)
    if not write:
        return result

    staged = replace(
        receipt,
        pending=PendingIntent(
            "link" if entry is not None else "unlink",
            name,
            before,
            after,
            old_record,
            record,
        ),
    )
    pending_raw = staged.encode()
    atomic_write(receipt.path, pending_raw, receipt.raw, limit=MAX_CONFIG_BYTES)
    if record and record.source_state(name) != "current":
        raise CondaError("Registration source changed during the operation.")
    if before != after:
        atomic_write(target.path, rendered, config.raw, limit=MAX_CONFIG_BYTES)
    elif read_bytes(target.path, limit=MAX_CONFIG_BYTES, missing_ok=True) != config.raw:
        raise CondaError("Client configuration changed during the operation.")
    finalized = staged.with_record(name, record)
    atomic_write(receipt.path, finalized.encode(), pending_raw, limit=MAX_CONFIG_BYTES)
    return result
