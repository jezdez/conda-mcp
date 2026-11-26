from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
NArgs = int | Literal["?", "*", "+", "remainder", "parser"] | None
ValueType = Literal["string", "integer", "number"]


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Structured outcome of one conda child process."""

    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    parsed_json: JsonValue | None = None
    timed_out: bool = False
    cancelled: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    restart_required: bool = False

    @property
    def failed(self) -> bool:
        return self.exit_code not in (0, None) or self.timed_out or self.cancelled

    def as_dict(self) -> dict[str, JsonValue]:
        """Return the stable MCP structured-output representation."""
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "parsed_json": self.parsed_json,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "restart_required": self.restart_required,
        }

    def summary(self) -> str:
        """Return a concise text result for MCP clients without structured output."""
        if self.timed_out:
            return "conda command timed out"
        if self.cancelled:
            return "conda command was cancelled"
        summary = f"conda command exited with {self.exit_code}"
        if self.restart_required:
            return f"{summary}. Restart the MCP server to refresh conda tools"
        return summary


class ActionKind(StrEnum):
    """Portable argparse action semantics used by the CLI catalog."""

    STORE = "store"
    APPEND = "append"
    EXTEND = "extend"
    STORE_TRUE = "store_true"
    STORE_FALSE = "store_false"
    BOOLEAN = "boolean"
    STORE_CONST = "store_const"
    APPEND_CONST = "append_const"
    COUNT = "count"
    EXTEND_CONST = "extend_const"


@dataclass(frozen=True, slots=True)
class Plugin:
    """Installed metadata for one external conda plugin entry point."""

    distribution: str
    version: str
    entry_point: str
    value: str
    hooks: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-compatible representation."""
        return {
            "distribution": self.distribution,
            "version": self.version,
            "entry_point": self.entry_point,
            "value": self.value,
            "hooks": list(self.hooks),
        }


@dataclass(frozen=True, slots=True)
class Argument:
    """One positional or optional argument accepted by a command."""

    id: str
    dest: str
    flags: tuple[str, ...]
    action: ActionKind
    nargs: NArgs
    value_type: ValueType
    required: bool = False
    choices: tuple[str, ...] = ()
    metavar: tuple[str, ...] = ()
    help: str | None = None
    hidden: bool = False

    def as_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-compatible representation."""
        return {
            "id": self.id,
            "dest": self.dest,
            "flags": list(self.flags),
            "action": self.action.value,
            "nargs": self.nargs,
            "value_type": self.value_type,
            "required": self.required,
            "choices": list(self.choices),
            "metavar": list(self.metavar),
            "help": self.help,
            "hidden": self.hidden,
        }


@dataclass(frozen=True, slots=True)
class ExclusiveGroup:
    """Arguments where argparse permits at most one member."""

    members: tuple[str, ...]
    required: bool = False

    def as_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-compatible representation."""
        return {"members": list(self.members), "required": self.required}


@dataclass(frozen=True, slots=True)
class Command:
    """One command node in the discovered conda CLI tree."""

    name: str | None
    aliases: tuple[str, ...] = ()
    summary: str | None = None
    arguments: tuple[Argument, ...] = ()
    exclusive_groups: tuple[ExclusiveGroup, ...] = ()
    children: tuple[Command, ...] = ()
    terminal: bool = True
    passthrough: bool = False
    raw_only: bool = False

    def as_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-compatible representation."""
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "summary": self.summary,
            "arguments": [argument.as_dict() for argument in self.arguments],
            "exclusive_groups": [group.as_dict() for group in self.exclusive_groups],
            "children": [child.as_dict() for child in self.children],
            "terminal": self.terminal,
            "passthrough": self.passthrough,
            "raw_only": self.raw_only,
        }


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A discovery problem that prevents typed exposure of one command."""

    path: tuple[str, ...]
    reason: str
    action_type: str | None = None

    def as_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-compatible representation."""
        return {
            "path": list(self.path),
            "reason": self.reason,
            "action_type": self.action_type,
        }


@dataclass(frozen=True, slots=True)
class Program:
    """The immutable CLI catalog discovered in this conda environment."""

    prog: str
    conda_version: str
    root: Command | None
    diagnostics: tuple[Diagnostic, ...] = ()

    def as_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-compatible representation."""
        return {
            "prog": self.prog,
            "conda_version": self.conda_version,
            "root": self.root.as_dict() if self.root is not None else None,
            "diagnostics": [diagnostic.as_dict() for diagnostic in self.diagnostics],
        }
