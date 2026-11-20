"""Build and exercise package-owned MCP server examples through conda-mcp."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = Path(sys.executable).resolve()


def _run(
    arguments: list[str], *, environment: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Run conda through the isolated host interpreter."""
    result = subprocess.run(
        [str(HOST), "-I", "-m", "conda", *arguments],
        cwd=cwd,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"conda command failed: {' '.join(arguments)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _build_run(arguments: list[str], *, environment: dict[str, str], cwd: Path) -> None:
    """Run a declared builder from the build environment without a workspace lookup."""
    executable = shutil.which(arguments[0])
    if executable is None or not Path(executable).resolve().is_relative_to(sys.prefix):
        raise RuntimeError(
            f"Builder is not installed in this environment: {arguments[0]}"
        )
    result = subprocess.run(
        [str(executable), *arguments[1:]],
        cwd=cwd,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"builder failed: {' '.join(arguments)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _artifact(output: Path, package: str) -> Path:
    """Return one exact package archive from one builder output tree."""
    archives = [
        *output.rglob(f"{package}-*.conda"),
        *output.rglob(f"{package}-*.tar.bz2"),
    ]
    if len(archives) != 1:
        raise RuntimeError(
            f"Expected one {package} artifact in {output}, found {archives}."
        )
    return archives[0]


def _build(output: Path, environment: dict[str, str]) -> dict[str, dict[str, Path]]:
    """Build every example with rattler-build and conda-build recipe-v1 paths."""
    version = subprocess.run(
        [str(HOST), "-m", "hatchling", "version"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    builders = {"rattler": ["rattler-build", "build", "-r"], "conda": ["conda-build"]}
    artifacts = {}
    for name, builder in builders.items():
        builder_output = output / name
        for name in ("fastmcp", "node", "remote", "wrapper"):
            recipe = ROOT / "examples" / name / "recipe.yaml"
            arguments = [
                *builder,
                str(recipe),
                "--output-dir",
                str(builder_output),
                "-c",
                "conda-forge",
            ]
            if builder[-1] == "conda-build":
                arguments = [
                    *builder,
                    str(recipe.parent),
                    "--output-folder",
                    str(builder_output),
                    "-c",
                    "conda-forge",
                ]
            _build_run(
                arguments,
                environment={**environment, "CONDA_MCP_VERSION": version},
                cwd=ROOT,
            )
        artifacts[builder_output.name] = {
            package: _artifact(builder_output, package)
            for package in (
                "example-fastmcp-server",
                "example-node-mcp-server",
                "example-mcp-endpoint",
                "example-mcp-wrapper",
            )
        }
    return artifacts


def _request(
    prefix: Path,
    package: str,
    server: str,
    requests: list[dict[str, object]],
    environment: dict[str, str],
) -> list[dict[str, object]]:
    """Send JSON-RPC requests through the foreground manager and return replies."""
    process = subprocess.Popen(
        [
            str(HOST),
            "-I",
            "-m",
            "conda",
            "mcp",
            "run",
            "-p",
            str(prefix),
            "--package",
            package,
            server,
        ],
        cwd=prefix,
        env=environment,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert process.stdin and process.stdout
        replies: queue.Queue[str | None] = queue.Queue(maxsize=len(requests))

        def read_replies() -> None:
            for line in process.stdout:
                replies.put(line)
            replies.put(None)

        reader = threading.Thread(target=read_replies, daemon=True)
        reader.start()
        received = []
        for request in requests:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            if "id" in request:
                line = replies.get(timeout=60)
                assert line is not None, "Server closed before replying."
                received.append(json.loads(line))
        process.stdin.close()
        stderr = process.stderr.read() if process.stderr else ""
        process.wait(timeout=60)
    except BaseException:
        process.kill()
        process.communicate(timeout=10)
        raise
    assert process.returncode == 0, stderr
    return received


def _install(prefix: Path, artifact: Path, environment: dict[str, str]) -> None:
    """Install an artifact with native conda package records in a disposable prefix."""
    _run(
        [
            "create",
            "--yes",
            "-p",
            str(prefix),
            "-c",
            "conda-forge",
            "python>=3.11",
            "fastmcp>=2",
            "nodejs>=20",
        ],
        environment=environment,
        cwd=ROOT,
    )
    _run(
        [
            "install",
            "--yes",
            "-p",
            str(prefix),
            str(artifact),
        ],
        environment=environment,
        cwd=ROOT,
    )


def main() -> None:
    """Verify installed discovery, rendering, and real manager protocol replies."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        home = root / "home"
        home.mkdir()
        condarc = root / "condarc"
        condarc.write_text("channels: [conda-forge]\n", encoding="utf-8")
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("CONDA_", "KILO_", "CODEX_", "COPILOT_"))
            and key
            not in {
                "CONDARC",
                "PYTHONPATH",
                "BASH_ENV",
                "ENV",
                "XDG_CONFIG_HOME",
                "APPDATA",
            }
        }
        environment.update(
            HOME=str(home),
            USERPROFILE=str(home),
            CONDARC=str(condarc),
            CONDA_PKGS_DIRS=str(root / "packages"),
            CONDA_ENVS_PATH=str(root / "envs"),
            RATTLER_CACHE_DIR=str(root / "rattler-cache"),
        )
        output = root / "output"
        artifacts = _build(output, environment)
        updated_output = output / "rattler-update"
        _build_run(
            [
                "rattler-build",
                "build",
                "-r",
                str(ROOT / "examples/remote/recipe.yaml"),
                "--output-dir",
                str(updated_output),
                "-c",
                "conda-forge",
            ],
            environment={**environment, "EXAMPLE_MCP_VERSION": "1.1.0"},
            cwd=ROOT,
        )
        updated_remote = _artifact(updated_output, "example-mcp-endpoint")
        cases = (
            (
                "example-node-mcp-server",
                "node-example",
                [
                    {
                        "jsonrpc": "2.0",
                        "id": 0,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "example-check", "version": "1"},
                        },
                    },
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "hello", "arguments": {"name": "Conda"}},
                    },
                ],
            ),
            (
                "example-fastmcp-server",
                "fastmcp-example",
                [
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "conda-mcp", "version": "1"},
                        },
                    },
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "greet", "arguments": {"name": "Conda"}},
                    },
                ],
            ),
        )
        for builder, packages in artifacts.items():
            for package, server, requests in cases:
                prefix = root / builder / package
                _install(prefix, packages[package], environment)
                listing = _run(
                    ["mcp", "list", "-p", str(prefix), "--json"],
                    environment=environment,
                    cwd=root,
                )
                assert any(
                    item["name"] == server and item["package"] == package
                    for item in json.loads(listing.stdout)
                )
                rendered = _run(
                    [
                        "mcp",
                        "render",
                        "-p",
                        str(prefix),
                        server,
                        "--client",
                        "codex",
                        "--json",
                    ],
                    environment=environment,
                    cwd=prefix,
                )
                assert "conda" in json.loads(rendered.stdout)["snippet"]
                register = _run(
                    [
                        "mcp",
                        "register",
                        "-p",
                        str(prefix),
                        server,
                        "--client",
                        "codex",
                        "--json",
                    ],
                    environment=environment,
                    cwd=prefix,
                )
                assert json.loads(register.stdout)["changed"] is True
                registry = _run(
                    ["mcp", "registry", "--client", "codex", "--json"],
                    environment=environment,
                    cwd=prefix,
                )
                assert json.loads(registry.stdout)[0]["name"] == server
                replies = _request(prefix, package, server, requests, environment)
                assert [reply["id"] for reply in replies] == [
                    request["id"] for request in requests if "id" in request
                ], replies
                assert all("error" not in reply for reply in replies), replies
                assert replies[-1]["result"]["content"][0]["text"] == "Hello, Conda!", (
                    replies
                )
        remote = root / "remote"
        _install(remote, artifacts["rattler"]["example-mcp-endpoint"], environment)
        result = _run(
            ["mcp", "inspect", "-p", str(remote), "example", "--json"],
            environment=environment,
            cwd=remote,
        )
        assert json.loads(result.stdout)["http"]["url"] == "https://example.invalid/mcp"
        _run(
            [
                "mcp",
                "register",
                "-p",
                str(remote),
                "example",
                "--client",
                "codex",
                "--json",
            ],
            environment=environment,
            cwd=remote,
        )
        wrapper = root / "wrapper"
        _install(wrapper, artifacts["rattler"]["example-mcp-wrapper"], environment)
        result = _run(
            [
                "mcp",
                "render",
                "-p",
                str(wrapper),
                "wrapper-example",
                "--client",
                "codex",
                "--json",
            ],
            environment=environment,
            cwd=wrapper,
        )
        assert "command" in json.loads(result.stdout)["snippet"]
        wrapper_result = subprocess.run(
            [
                str(HOST),
                "-I",
                "-m",
                "conda",
                "mcp",
                "run",
                "-p",
                str(wrapper),
                "--package",
                "example-mcp-wrapper",
                "wrapper-example",
                "--version",
            ],
            cwd=wrapper,
            env=environment,
            check=True,
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert wrapper_result.stdout.startswith("v")
        _run(
            ["install", "--yes", "-p", str(remote), str(updated_remote)],
            environment=environment,
            cwd=remote,
        )
        registry = _run(
            ["mcp", "registry", "--client", "codex", "--json"],
            environment=environment,
            cwd=remote,
        )
        remote_status = next(
            item for item in json.loads(registry.stdout) if item["name"] == "example"
        )
        assert remote_status["source_state"] == "changed"
        refresh = _run(
            [
                "mcp",
                "register",
                "example",
                "-p",
                str(remote),
                "--client",
                "codex",
                "--json",
            ],
            environment=environment,
            cwd=remote,
        )
        assert json.loads(refresh.stdout)["changed"] is True
        refreshed = _run(
            ["mcp", "registry", "--client", "codex", "--json"],
            environment=environment,
            cwd=remote,
        )
        assert json.loads(refreshed.stdout)[0]["source_state"] == "current"
        _run(
            ["remove", "--yes", "-p", str(remote), "example-mcp-endpoint"],
            environment=environment,
            cwd=remote,
        )
        registry = _run(
            ["mcp", "registry", "--client", "codex", "--json"],
            environment=environment,
            cwd=remote,
        )
        remote_status = next(
            item for item in json.loads(registry.stdout) if item["name"] == "example"
        )
        assert remote_status["source_state"] == "missing"
        unregister = _run(
            ["mcp", "unregister", "example", "--client", "codex", "--json"],
            environment=environment,
            cwd=remote,
        )
        assert json.loads(unregister.stdout)["removed"] is True
        node = root / "rattler" / "example-node-mcp-server"
        _run(
            ["remove", "--yes", "-p", str(node), "example-node-mcp-server"],
            environment=environment,
            cwd=root,
        )
    print(
        "Installed examples passed discovery, rendering, and manager protocol checks."
    )


if __name__ == "__main__":
    main()
