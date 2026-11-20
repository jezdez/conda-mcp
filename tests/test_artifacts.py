"""Regression checks for release artifact acceptance scripts."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _script_module(name: str):
    """Load an artifact script without relying on checkout imports."""
    path = ROOT / "scripts" / f"{name}.py"
    spec = spec_from_file_location(name, path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_distribution_validation_rejects_a_wheel_with_a_bad_crc(tmp_path: Path) -> None:
    """A corrupt wheel must fail before metadata is trusted."""
    wheel = tmp_path / "conda_mcp-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("conda_mcp/__init__.py", "artifact")
    with zipfile.ZipFile(wheel) as archive:
        member = archive.getinfo("conda_mcp/__init__.py")
    payload = bytearray(wheel.read_bytes())
    payload[member.header_offset + 30 + len(member.filename) + len(member.extra)] ^= 1
    wheel.write_bytes(payload)

    sdist = tmp_path / "conda_mcp-1.0.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        package_info = tmp_path / "PKG-INFO"
        package_info.write_text("Name: conda-mcp\nVersion: 1.0.0\n", encoding="utf-8")
        archive.add(package_info, arcname="conda_mcp-1.0.0/PKG-INFO")

    check_dist = _script_module("check_dist")
    try:
        check_dist.DistributionArtifacts(wheel, sdist).validate()
    except AssertionError as error:
        assert "CRC" in str(error)
    else:
        raise AssertionError("A wheel with a bad CRC was accepted.")


def test_wheel_script_creates_an_isolated_conda_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wheel acceptance creates an isolated prefix before its no-deps install."""
    test_wheel = _script_module("test_wheel")
    root = tmp_path / "project"
    dist = root / "dist"
    dist.mkdir(parents=True)
    wheel = dist / "conda_mcp-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "conda_mcp-1.2.3.dist-info/METADATA",
            "Name: conda-mcp\nVersion: 1.2.3\n",
        )
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "smoke_plugin.py").write_text("pass\n", encoding="utf-8")
    calls: list[tuple[list[str], dict[str, str], Path | None]] = []

    def record_run(
        arguments: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(
            (
                arguments,
                kwargs["env"],  # type: ignore[arg-type]
                kwargs.get("cwd"),  # type: ignore[arg-type]
            )
        )
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(test_wheel, "__file__", str(scripts / "test_wheel.py"))
    monkeypatch.setattr(test_wheel.subprocess, "run", record_run)

    test_wheel.main()

    create, install, smoke = calls
    assert create[0][:5] == [str(test_wheel.HOST), "-I", "-m", "conda", "create"]
    assert "--override-channels" in create[0]
    assert create[0][-5:] == [
        "conda>=26.10",
        "python>=3.11",
        "rich>=13",
        "tomlkit>=0.13",
        "pip",
    ]
    assert create[1]["CONDARC"].endswith("condarc")
    assert create[1]["CONDA_ENVS_PATH"].endswith("envs")
    assert install[0][2:7] == [
        "pip",
        "install",
        "--no-deps",
        "--no-build-isolation",
        str(wheel.resolve()),
    ]
    assert smoke[0][-2:] == ["--expected-version", "1.2.3"]


def test_example_script_passes_an_isolated_rattler_cache_to_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Example builds must not depend on a Windows profile cache location."""
    test_examples = _script_module("test_examples")
    environments: list[dict[str, str]] = []

    class StopAfterFirstBuild(Exception):
        pass

    def record_version(
        arguments: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(arguments, 0, stdout="1.2.3\n")

    def record_build(
        arguments: list[str], *, environment: dict[str, str], cwd: Path
    ) -> None:
        environments.append(environment)
        raise StopAfterFirstBuild

    monkeypatch.setattr(test_examples.subprocess, "run", record_version)
    monkeypatch.setattr(test_examples, "_build_run", record_build)

    with pytest.raises(StopAfterFirstBuild):
        test_examples.main()

    environment = environments[0]
    cache = Path(environment["RATTLER_CACHE_DIR"])
    assert cache.parent == Path(environment["HOME"]).parent
    assert cache.name == "rattler-cache"


@pytest.mark.skipif(
    shutil.which("node") is None, reason="Node runs in the artifact environment"
)
def test_node_example_initializes_before_listing_and_calling_tools():
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "hello", "arguments": {"name": "Conda"}},
        },
    ]
    result = subprocess.run(
        [sys.executable, "-c", "from example_node_mcp import main; main()"],
        cwd=ROOT / "examples/node",
        input="".join(json.dumps(request) + "\n" for request in requests),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [0, 1, 2]
    assert replies[0]["result"]["capabilities"] == {"tools": {}}
    assert replies[-1]["result"]["content"][0]["text"] == "Hello, Conda!"
