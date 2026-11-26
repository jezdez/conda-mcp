from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from mcp import Client, MCPError
from mcp.types import INVALID_PARAMS, INVALID_REQUEST

from conda_mcp.serving.capabilities import Capabilities, plugin_fingerprint
from conda_mcp.serving.execution import CompletionQueryError
from conda_mcp.serving.models import (
    ActionKind,
    Argument,
    Command,
    ExecutionResult,
    Plugin,
    Program,
)
from conda_mcp.serving.policy import SafetyPolicy
from conda_mcp.serving.server import (
    CAPABILITIES_URI,
    COMPLETION_TOOL_NAME,
    EXECUTE_TOOL_NAME,
    CondaMCPServer,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conda_mcp.serving.execution import CondaExecutor

    ServerFactory = Callable[
        ["RecordingExecutor", tuple[Command, ...], SafetyPolicy], CondaMCPServer
    ]


@dataclass
class RecordingExecutor:
    calls: list[tuple[str, ...]] = field(default_factory=list)
    plugins: tuple[Plugin, ...] = ()
    exit_code: int = 0
    plugin_fingerprint_calls: int = 0
    completion_calls: list[tuple[str, ...]] = field(default_factory=list)
    timeout_seconds: float = 900

    async def execute(
        self,
        argv: list[str] | tuple[str, ...],
        **_options: object,
    ) -> ExecutionResult:
        self.calls.append(tuple(argv))
        return ExecutionResult(
            exit_code=self.exit_code,
            stdout='{"ok": true}\n',
            stderr="",
            duration_ms=1,
            parsed_json={"ok": True},
        )

    async def probe_plugin_fingerprint(self) -> str:
        self.plugin_fingerprint_calls += 1
        return plugin_fingerprint("26.7", self.plugins)

    async def inspect_completion_command(
        self,
        command_path: list[str] | tuple[str, ...],
    ) -> dict[str, object]:
        self.completion_calls.append(tuple(command_path))
        return {
            "availability": "available",
            "requested_command_path": list(command_path),
            "resolved_command_path": list(command_path),
            "alias_target": None,
            "command": {
                "summary": "List environments",
                "options": [],
                "positionals": [],
                "subcommands": [],
                "exclusive_groups": [],
            },
            "manifest": {
                "version": 1,
                "generated_at": "2026-08-22T12:00:00Z",
                "stored_plugin_hash": "hash",
                "current_plugin_hash": "hash",
                "stale": False,
                "conda_completion_version": "0.3.0",
                "runtime_sources": {},
            },
            "hint": None,
        }


@pytest.fixture
def server_factory() -> ServerFactory:
    def build(
        executor: RecordingExecutor,
        children: tuple[Command, ...],
        policy: SafetyPolicy,
    ) -> CondaMCPServer:
        program = Program(
            prog="conda",
            conda_version="26.7",
            root=Command(name=None, terminal=False, children=children),
        )
        return CondaMCPServer(  # type: ignore[arg-type]
            executor,
            Capabilities("conda", program, ()),
            policy,
        )

    return build


@pytest.mark.anyio
async def test_execute_tool_returns_structured_result(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, script = fake_conda
    server = CondaMCPServer(
        executor,
        policy=SafetyPolicy(allow_write=True, allow_exec=True),
    )

    result = await server.execute({"argv": [str(script), "json", "value"]})

    assert not result.is_error
    assert result.structured_content["parsed_json"] == {"argv": ["value"]}
    assert json.loads(result.content[1].text) == result.structured_content
    assert server.execute_tool.name == EXECUTE_TOOL_NAME
    assert (
        server.execute_tool.input_schema["properties"]["timeout_seconds"]["maximum"]
        == 2
    )


@pytest.mark.anyio
@pytest.mark.parametrize("stdout", ['{"value": 1e400}', "[" * 500 + "0" + "]" * 500])
async def test_unrepresentable_parsed_json_keeps_successful_protocol_result(
    fake_conda: tuple[CondaExecutor, Path], stdout: str
) -> None:
    executor, script = fake_conda
    server = CondaMCPServer(
        executor,
        policy=SafetyPolicy(allow_write=True, allow_exec=True),
    )

    async with Client(server.server) as client:
        result = await client.call_tool(
            EXECUTE_TOOL_NAME, {"argv": [str(script), "literal", stdout]}
        )

    assert not result.is_error
    assert result.structured_content["exit_code"] == 0
    assert result.structured_content["stdout"] == stdout
    assert result.structured_content["parsed_json"] is None


@pytest.mark.anyio
async def test_execute_tool_validates_arguments(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, _script = fake_conda
    server = CondaMCPServer(
        executor,
        policy=SafetyPolicy(allow_write=True, allow_exec=True),
    )

    with pytest.raises(MCPError) as caught:
        await server.execute({"argv": "secret-value"})

    assert "secret-value" not in str(caught.value)


@pytest.mark.anyio
async def test_generated_tool_compiles_and_executes_scoped_argv() -> None:
    executor = RecordingExecutor()
    program = Program(
        prog="conda",
        conda_version="26.7",
        root=Command(
            name=None,
            terminal=False,
            arguments=(
                Argument(
                    id="verbose",
                    dest="verbose",
                    flags=("--verbose",),
                    action=ActionKind.COUNT,
                    nargs=0,
                    value_type="string",
                ),
            ),
            children=(Command(name="info"),),
        ),
    )
    capabilities = Capabilities("conda", program, ())
    server = CondaMCPServer(executor, capabilities)  # type: ignore[arg-type]

    async with Client(server.server) as client:
        listed = await client.list_tools()
        resources = await client.list_resources()
        resource = await client.read_resource(CAPABILITIES_URI)
        result = await client.call_tool("conda_info", {"verbose": 2})

    assert [tool.name for tool in listed.tools] == ["conda_info"]
    assert listed.tools[0].output_schema is not None
    assert listed.tools[0].annotations.read_only_hint is True
    assert [str(item.uri) for item in resources.resources] == [CAPABILITIES_URI]
    assert json.loads(resource.contents[0].text)["generated_tools"] == ["conda_info"]
    assert executor.calls == [("--verbose", "--verbose", "info")]
    assert result.structured_content["parsed_json"] == {"ok": True}


@pytest.mark.anyio
async def test_completion_plugin_adds_read_only_command_metadata_tool() -> None:
    executor = RecordingExecutor()
    program = Program(
        prog="conda",
        conda_version="26.7",
        root=Command(
            name=None,
            terminal=False,
            children=(Command(name="info"),),
        ),
    )
    plugin = Plugin(
        distribution="conda-completion",
        version="0.3.0",
        entry_point="conda-completion",
        value="conda_completion.plugin",
        hooks=("conda_subcommands",),
    )
    server = CondaMCPServer(  # type: ignore[arg-type]
        executor,
        Capabilities("conda", program, (plugin,)),
    )

    async with Client(server.server) as client:
        listed = await client.list_tools()
        result = await client.call_tool(
            COMPLETION_TOOL_NAME,
            {"command_path": ["env", "list"]},
        )

    assert [tool.name for tool in listed.tools] == [
        COMPLETION_TOOL_NAME,
        "conda_info",
    ]
    completion_tool = listed.tools[0]
    assert completion_tool.annotations.read_only_hint is True
    assert completion_tool.annotations.destructive_hint is False
    assert result.structured_content["command"]["summary"] == "List environments"
    assert json.loads(result.content[0].text) == result.structured_content
    assert executor.completion_calls == [("env", "list")]


@pytest.mark.anyio
async def test_policy_controls_tool_visibility_and_execution(
    server_factory: ServerFactory,
) -> None:
    executor = RecordingExecutor()
    server = server_factory(
        executor,
        (
            Command(name="info"),
            Command(name="install"),
            Command(name="run"),
            Command(name="fixture-plugin", passthrough=True),
        ),
        SafetyPolicy(),
    )

    async with Client(server.server) as client:
        listed = await client.list_tools()
        info = await client.call_tool("conda_info", {})
        with pytest.raises(MCPError):
            await client.call_tool("conda_install", {})
        with pytest.raises(MCPError):
            await client.call_tool("conda_run", {})
        with pytest.raises(MCPError):
            await client.call_tool("conda_fixture-plugin", {"args": []})
        with pytest.raises(MCPError):
            await client.call_tool(EXECUTE_TOOL_NAME, {"argv": ["info"]})

    assert [tool.name for tool in listed.tools] == [
        "conda_info",
        "conda_install",
        "conda_run",
        "conda_fixture-plugin",
    ]
    annotations = {tool.name: tool.annotations for tool in listed.tools}
    assert annotations["conda_info"].read_only_hint is True
    assert annotations["conda_install"].destructive_hint is True
    assert annotations["conda_run"].open_world_hint is True
    assert annotations["conda_fixture-plugin"].open_world_hint is True
    assert info.structured_content["restart_required"] is False
    assert executor.calls == [("info",)]


@pytest.mark.anyio
async def test_write_and_exec_enablement_remain_separate(
    server_factory: ServerFactory,
) -> None:
    executor = RecordingExecutor()
    children = (Command(name="install"), Command(name="run"))
    write_server = server_factory(
        executor,
        children,
        SafetyPolicy(allow_write=True),
    )
    exec_server = server_factory(
        executor,
        children,
        SafetyPolicy(allow_exec=True),
    )

    async with Client(write_server.server) as client:
        await client.call_tool("conda_install", {})
        with pytest.raises(MCPError):
            await client.call_tool("conda_run", {})
    async with Client(exec_server.server) as client:
        listed = await client.list_tools()
        await client.call_tool("conda_run", {})
        await client.call_tool(EXECUTE_TOOL_NAME, {"argv": ["info"]})
        with pytest.raises(MCPError) as caught:
            await client.call_tool(EXECUTE_TOOL_NAME, {"argv": ["secret-value"]})

    assert listed.tools[0].name == EXECUTE_TOOL_NAME
    assert listed.tools[0].annotations.open_world_hint is True
    assert "secret-value" not in str(caught.value)
    assert executor.calls == [("install",), ("run",), ("info",)]


@pytest.mark.anyio
async def test_successful_mutation_reports_restart_without_changing_tools(
    server_factory: ServerFactory,
) -> None:
    plugin = Plugin(
        distribution="conda-fixture",
        version="1.0",
        entry_point="fixture",
        value="conda_fixture.plugin",
        hooks=("conda_subcommands",),
    )
    executor = RecordingExecutor(plugins=(plugin,))
    server = server_factory(
        executor,
        (Command(name="info"), Command(name="install")),
        SafetyPolicy(allow_write=True),
    )

    async with Client(server.server) as client:
        before = await client.list_tools()
        changed = await client.call_tool("conda_install", {})
        after = await client.list_tools()
        read = await client.call_tool("conda_info", {})

    assert changed.structured_content["restart_required"] is True
    assert "Restart the MCP server" in changed.content[0].text
    assert read.structured_content["restart_required"] is True
    assert [tool.name for tool in before.tools] == [tool.name for tool in after.tools]
    assert executor.plugin_fingerprint_calls == 1


@pytest.mark.anyio
async def test_restart_check_detects_hook_changes_without_metadata_changes() -> None:
    initial = Plugin("example", "1", "plugin", "example.plugin", ("conda_solvers",))
    executor = RecordingExecutor(
        plugins=(Plugin("example", "1", "plugin", "example.plugin"),)
    )
    program = Program(
        prog="conda",
        conda_version="26.7",
        root=Command(name=None, terminal=False, children=(Command(name="install"),)),
    )
    server = CondaMCPServer(  # type: ignore[arg-type]
        executor,
        Capabilities("conda", program, (initial,)),
        SafetyPolicy(allow_write=True),
    )

    async with Client(server.server) as client:
        result = await client.call_tool("conda_install", {})

    assert result.structured_content["restart_required"] is True
    assert executor.plugin_fingerprint_calls == 1


@pytest.mark.anyio
async def test_failed_mutation_does_not_request_restart(
    server_factory: ServerFactory,
) -> None:
    executor = RecordingExecutor(exit_code=1)
    server = server_factory(
        executor,
        (Command(name="install"),),
        SafetyPolicy(allow_write=True),
    )

    async with Client(server.server) as client:
        result = await client.call_tool("conda_install", {})

    assert result.is_error
    assert result.structured_content["restart_required"] is False
    assert executor.plugin_fingerprint_calls == 0


@pytest.mark.anyio
async def test_manager_commands_follow_the_same_policy(
    server_factory: ServerFactory,
) -> None:
    executor = RecordingExecutor()
    manager = Command(
        name="mcp",
        terminal=False,
        children=(
            Command(name="list"),
            Command(name="register"),
            Command(name="run"),
            Command(name="serve"),
        ),
    )
    server = server_factory(executor, (manager,), SafetyPolicy())

    async with Client(server.server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        allowed = await client.call_tool("conda_mcp_list", {})
        with pytest.raises(MCPError):
            await client.call_tool("conda_mcp_register", {})

    assert "conda_mcp_serve" not in names
    assert "conda_mcp_run" not in names
    assert allowed.structured_content["exit_code"] == 0
    assert executor.calls == [("mcp", "list")]


@pytest.mark.parametrize(
    ("allow_write", "allow_exec", "spawned"),
    [
        (False, False, [("info",)]),
        (True, False, [("info",), ("install",)]),
        (False, True, [("info",), ("run",), ("info",)]),
        (True, True, [("info",), ("install",), ("run",), ("info",)]),
    ],
)
@pytest.mark.anyio
async def test_write_and_exec_combinations_bound_spawning(
    server_factory: ServerFactory,
    allow_write: bool,
    allow_exec: bool,
    spawned: list[tuple[str, ...]],
) -> None:
    executor = RecordingExecutor()
    server = server_factory(
        executor,
        (Command(name="info"), Command(name="install"), Command(name="run")),
        SafetyPolicy(allow_write=allow_write, allow_exec=allow_exec),
    )

    async with Client(server.server) as client:
        await client.call_tool("conda_info", {})
        for name, arguments in (
            ("conda_install", {}),
            ("conda_run", {}),
            (EXECUTE_TOOL_NAME, {"argv": ["info"]}),
        ):
            with contextlib.suppress(MCPError):
                await client.call_tool(name, arguments)

    assert executor.calls == spawned


@pytest.mark.anyio
async def test_invalid_generated_input_never_executes(server_factory):
    executor = RecordingExecutor()
    server = server_factory(executor, (Command(name="info"),), SafetyPolicy())
    async with Client(server.server) as client:
        with pytest.raises(MCPError) as caught:
            await client.call_tool("conda_info", {"secret-value": True})
    assert caught.value.code == INVALID_PARAMS
    assert "secret-value" not in str(caught.value)
    assert executor.calls == []


@pytest.mark.anyio
async def test_absent_capabilities_do_not_expose_a_resource():
    server = CondaMCPServer(RecordingExecutor())
    async with Client(server.server) as client:
        assert (await client.list_resources()).resources == []
        with pytest.raises(MCPError) as caught:
            await client.read_resource(CAPABILITIES_URI)
    assert caught.value.code == INVALID_PARAMS


@pytest.mark.anyio
async def test_invalid_execution_directory_returns_a_safe_error(fake_conda, tmp_path):
    executor, script = fake_conda
    server = CondaMCPServer(
        executor, policy=SafetyPolicy(allow_exec=True, allow_write=True)
    )
    with pytest.raises(MCPError) as caught:
        await server.execute(
            {
                "argv": [str(script), "json"],
                "cwd": str(tmp_path / "secret-directory"),
            }
        )
    assert caught.value.code == INVALID_PARAMS
    assert "secret-directory" not in str(caught.value)


@pytest.mark.anyio
async def test_completion_rejects_invalid_input_without_querying():
    executor = RecordingExecutor()
    server = CondaMCPServer(executor)
    with pytest.raises(MCPError) as caught:
        await server.inspect_completion_command({"command_path": "secret-value"})
    assert caught.value.code == INVALID_PARAMS
    assert "secret-value" not in str(caught.value)
    assert executor.completion_calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (
            CompletionQueryError("unknown_command"),
            INVALID_PARAMS,
            "Unknown conda command path",
        ),
        (
            CompletionQueryError("invalid_command_path"),
            INVALID_PARAMS,
            "Invalid conda command path",
        ),
        (CompletionQueryError("invalid_response"), INVALID_REQUEST, "invalid metadata"),
        (CompletionQueryError("unavailable"), INVALID_REQUEST, "unavailable"),
        (OSError("secret-value"), INVALID_REQUEST, "unavailable"),
    ],
)
async def test_completion_errors_have_safe_protocol_codes(
    monkeypatch, error, code, message
):
    executor = RecordingExecutor()

    async def fail(_path):
        raise error

    monkeypatch.setattr(executor, "inspect_completion_command", fail)
    server = CondaMCPServer(executor)
    with pytest.raises(MCPError) as caught:
        await server.inspect_completion_command({})
    assert caught.value.code == code
    assert message in str(caught.value)
    assert "secret-value" not in str(caught.value)


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", [{}, {"secret-value": float("nan")}])
async def test_completion_rejects_invalid_output(monkeypatch, invalid):
    executor = RecordingExecutor()
    payload = await executor.inspect_completion_command(())

    async def malformed(_path):
        return {} if not invalid else {**payload, "command": invalid}

    monkeypatch.setattr(executor, "inspect_completion_command", malformed)
    with pytest.raises(MCPError) as caught:
        await CondaMCPServer(executor).inspect_completion_command({})
    assert caught.value.code == INVALID_REQUEST
    assert "invalid metadata" in str(caught.value)
    assert "secret-value" not in str(caught.value)


@pytest.mark.anyio
async def test_failed_plugin_inspection_after_mutation_keeps_restart_required(
    monkeypatch, server_factory
):
    executor = RecordingExecutor()

    async def fail():
        raise OSError("plugin metadata unavailable")

    monkeypatch.setattr(executor, "probe_plugin_fingerprint", fail)
    server = server_factory(
        executor,
        (Command(name="install"), Command(name="info")),
        SafetyPolicy(allow_write=True),
    )
    async with Client(server.server) as client:
        changed = await client.call_tool("conda_install", {})
        read = await client.call_tool("conda_info", {})
    assert changed.structured_content["restart_required"] is True
    assert read.structured_content["restart_required"] is True
    assert executor.calls == [("install",), ("info",)]
