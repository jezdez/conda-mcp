"""Render shared command output."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from conda.base.context import context
from rich.console import Console
from rich.table import Table
from rich.text import Text

_CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def literal(value: object) -> str:
    """Render terminal controls visibly without interpreting markup."""
    return _CONTROLS.sub(lambda match: f"\\x{ord(match[0]):02x}", str(value))


def table(columns: tuple[str, ...], rows: Iterable[Iterable[object]]) -> None:
    """Render a labeled table of literal package and client data."""
    rendered = Table(show_edge=False, pad_edge=False)
    for column in columns:
        rendered.add_column(column)
    for row in rows:
        rendered.add_row(*(Text(literal(value)) for value in row))
    Console(markup=False, highlight=False).print(rendered)


def message(value: object) -> None:
    """Print one literal human confirmation or empty state."""
    Console(markup=False, highlight=False).print(Text(literal(value)))


def structured(result: object) -> None:
    """Print a complete JSON document."""
    print(json.dumps(result, indent=None if context.json else 2))
