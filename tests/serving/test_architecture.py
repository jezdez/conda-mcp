from __future__ import annotations

import ast
from pathlib import Path


def test_argparse_internals_and_conda_imports_are_isolated() -> None:
    package = Path(__file__).parents[2] / "src" / "conda_mcp" / "serving"
    violations: list[str] = []

    for source_path in package.glob("*.py"):
        if source_path.name == "discovery.py":
            continue
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and (
                node.attr
                in {"_actions", "_mutually_exclusive_groups", "_group_actions"}
                or (
                    isinstance(node.value, ast.Name)
                    and node.value.id == "argparse"
                    and node.attr.startswith("_")
                )
            ):
                violations.append(f"{source_path.name}:{node.lineno}")
            if isinstance(node, ast.ImportFrom) and (
                (node.module or "").startswith("conda")
                and not (
                    node.module == "conda.common.compat"
                    and len(node.names) == 1
                    and node.names[0].name == "on_win"
                    and node.names[0].asname is None
                )
            ):
                violations.append(f"{source_path.name}:{node.lineno}")
            if isinstance(node, ast.Import) and any(
                alias.name.startswith("conda") for alias in node.names
            ):
                violations.append(f"{source_path.name}:{node.lineno}")

    assert violations == []
