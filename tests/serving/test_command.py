from __future__ import annotations

import argparse
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING

import pytest
from jsonschema import ValidationError

from conda_mcp.cli.parser import configure
from conda_mcp.serving.command import (
    CommandTool,
    argument_argv,
    argument_input_schema,
    canonical_tool_name,
    command_tools,
)
from conda_mcp.serving.discovery import inspect_parser
from conda_mcp.serving.models import (
    ActionKind,
    Argument,
    Command,
    Diagnostic,
    ExclusiveGroup,
    Program,
)

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.parametrize("name", ["run", "register", "render"])
def test_generated_manager_tools_preserve_server_argument_separator(name):
    parser = argparse.ArgumentParser()
    configure(parser)
    tools = {tool.path: tool for tool in command_tools(inspect_parser(parser))}
    values = {
        "server": "demo",
        "name": "servers",
        "arguments": ["--json", "", "--", "a b"],
    }
    if name != "run":
        values["client"] = "codex"
    argv = tools[(name,)].compile(values)
    assert argv[-5:] == ("--", "--json", "", "--", "a b")
    parsed = parser.parse_args(argv)
    assert parsed.name == "servers"
    assert parsed.arguments == ["--json", "", "--", "a b"]


def make_argument(
    action: ActionKind,
    *,
    argument_id: str = "value",
    flags: tuple[str, ...] = ("-v", "--value"),
    nargs: int | str | None = None,
    value_type: str = "string",
    required: bool = False,
    choices: tuple[str, ...] = (),
    help_text: str | None = None,
) -> Argument:
    return Argument(
        id=argument_id,
        dest=argument_id,
        flags=flags,
        action=action,
        nargs=nargs,
        value_type=value_type,
        required=required,
        choices=choices,
        help=help_text,
    )


def make_tool(
    *arguments: Argument,
    groups: tuple[ExclusiveGroup, ...] = (),
    passthrough: bool = False,
) -> CommandTool:
    return CommandTool(
        (
            Command(name=None),
            Command(
                name="example",
                arguments=tuple(arguments),
                exclusive_groups=groups,
                passthrough=passthrough,
            ),
        )
    )


@pytest.mark.parametrize(
    ("action", "converter", "positional", "value", "argv"),
    [
        ("store", str, False, "numpy", ("--value", "numpy")),
        ("store", str, False, "two words", ("--value", "two words")),
        ("store", int, False, 7, ("--value", "7")),
        ("store", float, False, 1.5, ("--value", "1.5")),
        ("store", str, False, None, ("--value",)),
        ("store", str, True, "numpy", ("numpy",)),
        ("store", str, True, None, ()),
        (
            "append",
            str,
            False,
            ["two words", None, "last"],
            ("--value", "two words", "--value", "--value", "last"),
        ),
        ("append", int, False, [7, 8], ("--value", "7", "--value", "8")),
    ],
)
def test_optional_values_round_trip_through_the_discovered_parser(
    action, converter, positional, value, argv
):
    parser = argparse.ArgumentParser(prog="conda")
    child = parser.add_subparsers(dest="command").add_parser("example")
    child.add_argument(
        "value" if positional else "--value",
        action=action,
        type=converter,
        nargs="?",
    )
    tool = command_tools(inspect_parser(parser, conda_version="test"))[0]

    compiled = tool.compile({"value": value})

    assert compiled == ("example", *argv)
    assert parser.parse_args(compiled).value == value


@pytest.mark.parametrize(
    ("options", "value", "expected", "parsed"),
    [
        ({"type": int}, 2.0, ("--value", "2"), 2),
        ({"action": "append", "type": int}, [2.0], ("--value", "2"), [2]),
        (
            {"action": "extend", "type": int, "nargs": 2},
            [2.0, 3.0],
            ("--value", "2", "3"),
            [2, 3],
        ),
        ({"action": "count"}, 2.0, ("--value", "--value"), 2),
    ],
)
def test_integral_json_numbers_round_trip_through_argparse(
    options, value, expected, parsed
) -> None:
    parser = argparse.ArgumentParser(prog="conda")
    child = parser.add_subparsers(dest="command").add_parser("example")
    child.add_argument("--value", **options)
    tool = command_tools(inspect_parser(parser, conda_version="test"))[0]

    compiled = tool.compile({"value": value})

    assert compiled == ("example", *expected)
    assert parser.parse_args(compiled).value == parsed


@pytest.mark.parametrize(
    ("options", "value", "expected", "parsed"),
    [
        ({}, "--message", ("--value=--message",), "--message"),
        ({"nargs": "?"}, "--message", ("--value=--message",), "--message"),
        (
            {"action": "append"},
            ["--message"],
            ("--value=--message",),
            ["--message"],
        ),
        (
            {"action": "extend"},
            ["--message"],
            ("--value=--message",),
            list("--message"),
        ),
    ],
)
def test_dash_prefixed_scalar_option_values_round_trip_through_argparse(
    options, value, expected, parsed
) -> None:
    parser = argparse.ArgumentParser(prog="conda")
    child = parser.add_subparsers(dest="command").add_parser("example")
    child.add_argument("--value", **options)
    tool = command_tools(inspect_parser(parser, conda_version="test"))[0]

    compiled = tool.compile({"value": value})

    assert compiled == ("example", *expected)
    assert parser.parse_args(compiled).value == parsed


def test_dash_prefixed_multi_value_option_is_rejected_before_argparse() -> None:
    parser = argparse.ArgumentParser(prog="conda")
    child = parser.add_subparsers(dest="command").add_parser("example")
    child.add_argument("--value", nargs=2)
    tool = command_tools(inspect_parser(parser, conda_version="test"))[0]

    with pytest.raises(ValidationError):
        tool.compile({"value": ["plain", "--message"]})


@pytest.mark.parametrize(
    ("options", "value", "invalid", "argv", "parsed"),
    [
        ({"action": "append", "required": True}, ["a"], [], ("--value", "a"), ["a"]),
        (
            {"action": "extend", "required": True},
            ["ab"],
            [],
            ("--value", "ab"),
            ["a", "b"],
        ),
        (
            {"action": "extend", "required": True, "nargs": "?", "const": "c"},
            ["ab", None],
            [],
            ("--value", "ab", "--value"),
            ["a", "b", "c"],
        ),
        ({"action": "store_true", "required": True}, True, False, ("--value",), True),
        ({"type": float, "choices": [1.5, 2.5]}, 1.5, 3.0, ("--value", "1.5"), 1.5),
    ],
)
def test_generated_inputs_enforce_parser_requirements(
    options, value, invalid, argv, parsed
):
    parser = argparse.ArgumentParser(prog="conda")
    child = parser.add_subparsers(dest="command").add_parser("example")
    child.add_argument("--value", **options)
    tool = command_tools(inspect_parser(parser, conda_version="test"))[0]

    compiled = tool.compile({"value": value})

    assert compiled == ("example", *argv)
    assert parser.parse_args(compiled).value == parsed
    with pytest.raises(ValidationError):
        tool.compile({"value": invalid})


@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize(
    ("options", "active", "inactive", "argv"),
    [
        ({"action": "store_false"}, False, True, ("--value",)),
        ({"action": "count"}, 2, 0, ("--value", "--value")),
        ({"action": "append"}, ["a"], [], ("--value", "a")),
        ({"action": "append_const", "const": "a"}, 1, 0, ("--value",)),
        ({"action": "extend"}, ["a"], [], ("--value", "a")),
        ({"action": "extend", "nargs": "?", "const": "a"}, [None], [], ("--value",)),
    ],
)
def test_exclusive_groups_count_only_arguments_that_emit_tokens(
    options, active, inactive, argv, required
):
    parser = argparse.ArgumentParser(prog="conda")
    child = parser.add_subparsers(dest="command").add_parser("example")
    group = child.add_mutually_exclusive_group(required=required)
    group.add_argument("--value", **options)
    group.add_argument("--other", action="store_true")
    tool = command_tools(inspect_parser(parser, conda_version="test"))[0]

    assert tool.compile({"value": active, "other": False}) == ("example", *argv)
    compiled = tool.compile({"value": inactive, "other": True})
    assert compiled == ("example", "--other")
    assert parser.parse_args(compiled).other is True
    with pytest.raises(ValidationError):
        tool.compile({"value": active, "other": True})
    if required:
        with pytest.raises(ValidationError):
            tool.compile({"value": inactive, "other": False})
    else:
        assert tool.compile({"value": inactive, "other": False}) == ("example",)


def test_command_tools_build_canonical_leaves_and_preserve_scope() -> None:
    root = Command(
        name=None,
        arguments=(
            make_argument(
                ActionKind.STORE_TRUE,
                argument_id="json",
                flags=("--json",),
            ),
        ),
        children=(
            Command(
                name="env",
                terminal=False,
                aliases=("environment",),
                arguments=(
                    make_argument(
                        ActionKind.STORE,
                        argument_id="prefix",
                        flags=("-p", "--prefix"),
                    ),
                ),
                children=(
                    Command(
                        name="create",
                        aliases=("new",),
                        summary="Create a conda environment.",
                        arguments=(
                            make_argument(
                                ActionKind.STORE,
                                argument_id="name",
                                flags=("-n", "--name"),
                            ),
                        ),
                    ),
                ),
            ),
            Command(name="build", aliases=("bld",), passthrough=True),
            Command(name="raw", raw_only=True, children=(Command(name="child"),)),
            Command(name="broken"),
            Command(name=None),
        ),
    )
    program = Program(
        prog="conda",
        conda_version="26.7.0",
        root=root,
        diagnostics=(Diagnostic(path=("broken",), reason="unsupported action"),),
    )

    tools = command_tools(program)

    assert [tool.name for tool in tools] == ["conda_env_create", "conda_build"]
    env_tool, build_tool = tools
    assert env_tool.compile(
        {"json": True, "prefix": "/tmp/prefix", "name": "demo"}
    ) == (
        "--json",
        "env",
        "--prefix",
        "/tmp/prefix",
        "create",
        "--name",
        "demo",
    )
    assert build_tool.compile({"args": ["--", "recipe", "--variants", "x"]}) == (
        "build",
        "--",
        "recipe",
        "--variants",
        "x",
    )

    output_schema = {"type": "object"}
    declaration = env_tool.as_mcp_tool(output_schema=output_schema)
    assert declaration.title == "conda env create"
    assert declaration.description == "Create a conda environment."
    assert declaration.output_schema == output_schema
    assert declaration.meta == {
        "conda-cli-mcp/path": ["env", "create"],
        "conda-cli-mcp/aliases": [
            {"command": "env", "aliases": ["environment"]},
            {"command": "create", "aliases": ["new"]},
        ],
    }


@pytest.mark.parametrize(
    ("argument", "expected"),
    [
        (
            make_argument(
                ActionKind.STORE,
                choices=("main", "test"),
            ),
            {"type": "string", "enum": ["main", "test"]},
        ),
        (
            make_argument(ActionKind.STORE, nargs="+", value_type="integer"),
            {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 1,
            },
        ),
        (
            make_argument(ActionKind.STORE, nargs="parser"),
            {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
        ),
        (
            make_argument(ActionKind.STORE, nargs=2, value_type="number"),
            {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
            },
        ),
        (
            make_argument(ActionKind.STORE, nargs="?"),
            {"anyOf": [{"type": "string"}, {"type": "null"}]},
        ),
        (
            make_argument(ActionKind.STORE, flags=()),
            {"type": "string", "pattern": "^(?!-)"},
        ),
        (
            make_argument(ActionKind.APPEND),
            {"type": "array", "items": {"type": "string"}},
        ),
        (
            make_argument(ActionKind.APPEND, nargs=2),
            {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "string", "pattern": "^(?!-)"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
        ),
        (
            make_argument(ActionKind.EXTEND),
            {"type": "array", "items": {"type": "string"}},
        ),
        (
            make_argument(ActionKind.EXTEND, nargs="+"),
            {
                "type": "array",
                "items": {"type": "string", "pattern": "^(?!-)"},
                "minItems": 1,
            },
        ),
        (make_argument(ActionKind.STORE_TRUE), {"type": "boolean"}),
        (make_argument(ActionKind.STORE_FALSE), {"type": "boolean"}),
        (make_argument(ActionKind.BOOLEAN), {"type": "boolean"}),
        (make_argument(ActionKind.STORE_CONST), {"type": "boolean"}),
        (
            make_argument(ActionKind.APPEND_CONST),
            {"type": "integer", "minimum": 0, "maximum": 128},
        ),
        (
            make_argument(ActionKind.EXTEND_CONST),
            {"type": "array", "items": {"type": "string", "pattern": "^(?!-)"}},
        ),
        (
            make_argument(ActionKind.COUNT),
            {"type": "integer", "minimum": 0, "maximum": 128},
        ),
    ],
)
def test_argument_input_schema_covers_supported_actions(
    argument: Argument,
    expected: dict[str, Any],
) -> None:
    assert argument_input_schema(argument) == expected


def test_argument_input_schema_converts_numeric_choices_and_requirements() -> None:
    integer = make_argument(
        ActionKind.STORE,
        value_type="integer",
        choices=("1", "3"),
        required=True,
        help_text="Number of retries.",
    )
    count = make_argument(ActionKind.COUNT, required=True)
    disabled = make_argument(ActionKind.STORE_FALSE, required=True)

    assert argument_input_schema(integer) == {
        "type": "integer",
        "enum": [1, 3],
        "description": "Number of retries.",
    }
    assert argument_input_schema(count) == {
        "type": "integer",
        "minimum": 1,
        "maximum": 128,
    }
    assert argument_input_schema(disabled) == {
        "type": "boolean",
        "const": False,
    }


@pytest.mark.parametrize("action", [ActionKind.COUNT, ActionKind.APPEND_CONST])
def test_repeated_flags_have_a_small_finite_limit(action: ActionKind) -> None:
    tool = make_tool(make_argument(action))
    maximum = tool.input_schema["properties"]["value"]["maximum"]

    assert 4 < maximum <= 256
    assert tool.compile({"value": maximum}) == (
        "example",
        *("--value",) * maximum,
    )
    with pytest.raises(ValidationError):
        tool.compile({"value": maximum + 1})
    with pytest.raises(ValidationError):
        tool.compile({"value": 2**100})
    with pytest.raises(ValueError, match="repeat count"):
        argument_argv(make_argument(action), maximum + 1)


@pytest.mark.parametrize(
    ("argument", "value", "expected"),
    [
        (make_argument(ActionKind.STORE), "text", ("--value", "text")),
        (
            make_argument(ActionKind.STORE, flags=()),
            "text",
            ("text",),
        ),
        (
            make_argument(ActionKind.STORE, nargs="+"),
            ["a", "b"],
            ("--value", "a", "b"),
        ),
        (
            make_argument(ActionKind.STORE, nargs="?"),
            None,
            ("--value",),
        ),
        (
            make_argument(ActionKind.APPEND),
            ["a", "b"],
            ("--value", "a", "--value", "b"),
        ),
        (
            make_argument(ActionKind.APPEND, nargs=2),
            [["a", "b"], ["c", "d"]],
            ("--value", "a", "b", "--value", "c", "d"),
        ),
        (
            make_argument(ActionKind.EXTEND),
            ["a", "b"],
            ("--value", "a", "--value", "b"),
        ),
        (
            make_argument(ActionKind.EXTEND, nargs="?"),
            ["a", None],
            ("--value", "a", "--value"),
        ),
        (
            make_argument(ActionKind.EXTEND, nargs="+"),
            ["a", "b"],
            ("--value", "a", "b"),
        ),
        (make_argument(ActionKind.STORE_TRUE), True, ("--value",)),
        (make_argument(ActionKind.STORE_TRUE), False, ()),
        (make_argument(ActionKind.STORE_FALSE), False, ("--value",)),
        (make_argument(ActionKind.STORE_FALSE), True, ()),
        (
            make_argument(
                ActionKind.BOOLEAN,
                flags=("-c", "--color", "--no-color"),
            ),
            True,
            ("--color",),
        ),
        (
            make_argument(
                ActionKind.BOOLEAN,
                flags=("-c", "--color", "--no-color"),
            ),
            False,
            ("--no-color",),
        ),
        (make_argument(ActionKind.STORE_CONST), True, ("--value",)),
        (make_argument(ActionKind.STORE_CONST), False, ()),
        (
            make_argument(ActionKind.APPEND_CONST),
            2,
            ("--value", "--value"),
        ),
        (
            make_argument(ActionKind.EXTEND_CONST),
            ["first", "second"],
            ("--value", "first", "second"),
        ),
        (
            make_argument(ActionKind.COUNT),
            3,
            ("--value", "--value", "--value"),
        ),
    ],
)
def test_argument_argv_covers_supported_actions(
    argument: Argument,
    value: Any,
    expected: tuple[str, ...],
) -> None:
    assert argument_argv(argument, value) == expected


def test_command_tool_validates_required_and_exclusive_arguments() -> None:
    first = make_argument(
        ActionKind.STORE_TRUE,
        argument_id="first",
        flags=("--first",),
    )
    second = make_argument(
        ActionKind.STORE_TRUE,
        argument_id="second",
        flags=("--second",),
    )
    tool = make_tool(
        first,
        second,
        groups=(ExclusiveGroup(("first", "second"), required=True),),
    )

    with pytest.raises(ValidationError):
        tool.compile({})
    with pytest.raises(ValidationError):
        tool.compile({"first": True, "second": True})
    with pytest.raises(ValidationError):
        tool.compile({"first": False, "second": False})

    assert tool.compile({"first": True, "second": False}) == (
        "example",
        "--first",
    )


def test_command_tool_validates_shape_and_scopes_duplicate_ids() -> None:
    root = Command(
        name=None,
        arguments=(
            make_argument(
                ActionKind.COUNT,
                argument_id="verbose",
                flags=("-v", "--verbose"),
            ),
        ),
    )
    leaf = Command(
        name="search",
        arguments=(
            make_argument(
                ActionKind.STORE_TRUE,
                argument_id="verbose",
                flags=("--verbose",),
            ),
        ),
    )
    tool = CommandTool((root, leaf))

    assert set(tool.input_schema["properties"]) == {"verbose", "verbose_2"}
    assert tool.compile({"verbose": 2, "verbose_2": True}) == (
        "--verbose",
        "--verbose",
        "search",
        "--verbose",
    )
    with pytest.raises(ValidationError):
        tool.compile({"unknown": True})
    with pytest.raises(ValidationError):
        tool.compile({"verbose": "twice"})


def test_passthrough_id_is_disambiguated_and_tokens_are_unchanged() -> None:
    tool = make_tool(
        make_argument(ActionKind.STORE, argument_id="args"),
        passthrough=True,
    )

    assert tool.passthrough_id == "args_2"
    assert tool.compile({"args": "configured", "args_2": ["--", "$(not-a-shell)"]}) == (
        "example",
        "--value",
        "configured",
        "--",
        "$(not-a-shell)",
    )


def test_typed_positionals_reject_options_but_remainder_preserves_them() -> None:
    positional = make_tool(make_argument(ActionKind.STORE, flags=()))
    remainder = make_tool(make_argument(ActionKind.STORE, flags=(), nargs="remainder"))

    with pytest.raises(ValidationError):
        positional.compile({"value": "--json"})
    assert remainder.compile({"value": ["python", "-V"]}) == (
        "example",
        "python",
        "-V",
    )


def test_extend_const_emits_one_flag_for_an_empty_value_list() -> None:
    argument = make_argument(ActionKind.EXTEND_CONST, nargs="*")
    tool = make_tool(argument)

    assert tool.input_schema["properties"]["value"] == {
        "type": "array",
        "items": {"type": "string", "pattern": "^(?!-)"},
    }
    assert tool.compile({"value": []}) == ("example", "--value")
    assert tool.compile({"value": ["one", "two"]}) == (
        "example",
        "--value",
        "one",
        "two",
    )


def test_unavailable_program_and_name_collisions_remain_local() -> None:
    unavailable = Program(
        prog="conda",
        conda_version="unknown",
        root=None,
    )
    collision = Program(
        prog="conda",
        conda_version="26.7.0",
        root=Command(
            name=None,
            children=(
                Command(
                    name="foo",
                    terminal=False,
                    children=(Command(name="bar"),),
                ),
                Command(name="foo_bar"),
                Command(name="safe"),
            ),
        ),
    )

    assert command_tools(unavailable) == ()
    generated = command_tools(collision)
    assert len(generated) == 3
    assert generated[-1].name == "conda_safe"
    assert generated[0].name != generated[1].name
    assert all(tool.name.startswith("conda_foo_bar_") for tool in generated[:2])


def test_terminal_nonleaf_commands_and_their_children_receive_tools() -> None:
    program = Program(
        prog="conda",
        conda_version="26.7.0",
        root=Command(
            name=None,
            terminal=False,
            children=(
                Command(
                    name="config",
                    children=(Command(name="sources"),),
                ),
            ),
        ),
    )

    generated = command_tools(program)

    assert [tool.name for tool in generated] == [
        "conda_config",
        "conda_config_sources",
    ]
    assert generated[0].compile({}) == ("config",)
    assert generated[1].compile({}) == ("config", "sources")


def test_generated_commands_cannot_take_builtin_tool_names() -> None:
    program = Program(
        prog="conda",
        conda_version="26.10.0",
        root=Command(
            name=None,
            terminal=False,
            children=(Command(name="execute"), Command(name="cli_command")),
        ),
    )

    generated = command_tools(program)

    assert generated[0].name.startswith("conda_execute_")
    assert generated[1].name.startswith("conda_cli_command_")
    assert generated[0].compile({}) == ("execute",)
    assert generated[1].compile({}) == ("cli_command",)


def test_hashed_reserved_name_cannot_hide_another_command() -> None:
    reserved_hash = canonical_tool_name(("execute",), disambiguate=True)
    sibling = reserved_hash.removeprefix("conda_")
    program = Program(
        prog="conda",
        conda_version="26.10.0",
        root=Command(
            name=None,
            terminal=False,
            children=(Command(name="execute"), Command(name=sibling)),
        ),
    )

    generated = command_tools(program)
    names = [tool.name for tool in generated]

    assert names[0] == reserved_hash
    assert len(names) == len(set(names))
    assert generated[1].compile({}) == (sibling,)


def test_command_tool_is_frozen_and_names_are_canonical() -> None:
    tool = make_tool()

    assert canonical_tool_name(("env", "create-from-file")) == (
        "conda_env_create-from-file"
    )
    sanitized = canonical_tool_name(("plugin:name",))
    long_name = canonical_tool_name(("x" * 200,))
    assert sanitized.startswith("conda_plugin_name_")
    assert len(long_name) == 128
    assert long_name == canonical_tool_name(("x" * 200,))
    with pytest.raises(FrozenInstanceError):
        tool.commands = ()


def test_manager_stdio_launchers_are_not_generated_tools() -> None:
    root = Command(
        name=None,
        terminal=False,
        children=(
            Command(
                name="mcp",
                terminal=False,
                children=(
                    Command(name="list"),
                    Command(name="run"),
                    Command(name="serve"),
                ),
            ),
        ),
    )
    program = Program(prog="conda", conda_version="26.10.0", root=root)

    assert [tool.name for tool in command_tools(program)] == ["conda_mcp_list"]
