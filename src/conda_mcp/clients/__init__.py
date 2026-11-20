"""Shared interface for native MCP client adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ConfigTarget, Connection


@dataclass(frozen=True)
class ClientAdapter(ABC):
    """Render one native client format at its selected destination."""

    @property
    @abstractmethod
    def key(self) -> str:
        """Return the configuration container key."""

    @abstractmethod
    def destination(self, root: Path, *, global_scope: bool) -> Path:
        """Return the client file for the selected scope."""

    @abstractmethod
    def render(
        self, connection: Connection, *, global_scope: bool
    ) -> dict[str, object]:
        """Render a connection into the native entry format."""

    def check_layers(self, target: ConfigTarget, name: str) -> None:
        """Validate effective configuration layers when the client needs it."""
        return None
