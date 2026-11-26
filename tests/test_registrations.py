from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import FrozenInstanceError

import pytest
from conda import CondaError
from conda.common.compat import on_win

from conda_mcp import registrations
from conda_mcp.clients.manager import config_target
from conda_mcp.registrations import fingerprint, registration
from conda_mcp.servers import discover


@pytest.fixture(autouse=True)
def isolated_client_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    for key in list(os.environ):
        if key.startswith("KILO_"):
            monkeypatch.delenv(key)


@pytest.fixture
def source(install_package):
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "demo",
            "description": "Example",
            "http": {"url": "https://example.org/mcp"},
        }
    )
    document = discover(prefix)[0].to_dict()
    return {
        key: document[key]
        for key in (
            "prefix",
            "package",
            "manifest",
            "manifest_digest",
            "version",
            "build",
            "channel",
        )
    }


@pytest.fixture
def entry():
    return {"type": "http", "url": "https://example.org/mcp"}


def receipt_path(target):
    return target.path.with_name(target.path.name + ".conda-mcp.json")


def test_shared_project_registration_preserves_edits(tmp_path, source):
    target = config_target("claude-code", tmp_path, global_scope=False)
    target.path.write_text('{"other": true, "mcpServers": {"foreign": {}}}')
    entry = {"url": "https://example.org/mcp"}
    assert registration(target, "demo", entry=entry, source=source, dry_run=True)[
        "changed"
    ]
    assert "demo" not in json.loads(target.path.read_text())["mcpServers"]
    assert registration(target, "demo", entry=entry, source=source)["changed"]
    document = json.loads(target.path.read_text())
    document["mcpServers"]["demo"]["custom"] = True
    target.path.write_text(json.dumps(document))
    copilot = config_target("copilot", tmp_path, global_scope=False)
    with pytest.raises(CondaError, match="edited"):
        registration(copilot, "demo")
    assert registration(copilot, "demo", force=True)["removed"]
    assert json.loads(target.path.read_text()) == {
        "other": True,
        "mcpServers": {"foreign": {}},
    }


def test_dry_run_shows_entry_and_shared_effect_without_creating_paths(
    tmp_path, source, entry
):
    root = tmp_path / "missing"
    target = config_target("claude-code", root, global_scope=False)
    result = registration(target, "demo", entry=entry, source=source, dry_run=True)
    assert result["entry"] == entry
    assert result["shared_clients"] == ["claude-code", "copilot"]
    assert result["changed"]
    assert not root.exists()


def test_link_is_idempotent_and_receipt_contains_complete_source(
    tmp_path, source, entry
):
    target = config_target("cursor", tmp_path, global_scope=False)
    assert registration(target, "demo", entry=entry, source=source)["changed"]
    before = target.path.stat().st_mtime_ns
    ledger = json.loads(receipt_path(target).read_bytes())
    assert ledger == {
        "schema_version": 1,
        "entries": {"demo": {"digest": fingerprint(entry), **source}},
    }
    assert not registration(target, "demo", entry=entry, source=source)["changed"]
    assert target.path.stat().st_mtime_ns == before
    [state] = registration(target)
    assert state["state"] == "managed"
    assert state["source_state"] == "current"
    assert "effective_state" not in state


def test_receiptless_matching_entry_is_not_adopted(tmp_path, source, entry):
    target = config_target("claude-code", tmp_path, global_scope=False)
    target.path.write_text(json.dumps({target.key: {"demo": entry}}))
    with pytest.raises(CondaError, match="unmanaged"):
        registration(target, "demo", entry=entry, source=source)
    assert not receipt_path(target).exists()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"mcpServers":{},"secret":NaN}',
        b'{"x":1,"x":2}',
        b"[]",
        b'{"mcpServers":[]}',
        b"\xff",
        b'{"secret":"PRIVATE"]',
    ],
)
def test_invalid_configuration_never_starts_a_receipt(tmp_path, source, entry, raw):
    target = config_target("claude-code", tmp_path, global_scope=False)
    target.path.write_bytes(raw)
    with pytest.raises(CondaError) as caught:
        registration(target, "demo", entry=entry, source=source)
    assert "PRIVATE" not in str(caught.value)
    assert target.path.read_bytes() == raw
    assert not receipt_path(target).exists()
    assert not target.path.with_name(target.path.name + ".conda-mcp.lock").exists()


def test_toml_comments_foreign_policy_and_mode_survive(tmp_path, source, entry):
    target = config_target("codex", tmp_path, global_scope=False)
    target.path.parent.mkdir()
    target.path.write_text(
        "# keep this comment\n[mcp_servers.foreign]\n"
        'command="other" # and this\nenabled=false\n'
    )
    target.path.chmod(0o640)
    registration(target, "demo", entry={"url": entry["url"]}, source=source)
    text = target.path.read_text()
    assert "# keep this comment" in text and "# and this" in text
    assert "enabled=false" in text
    if not on_win:
        assert target.path.stat().st_mode & 0o777 == 0o640
    registration(target, "demo")
    assert "[mcp_servers.demo]" not in target.path.read_text()
    assert "enabled=false" in target.path.read_text()


def test_lock_receives_a_binary_file_object(tmp_path, source, entry, monkeypatch):
    native_lock = registrations.lock

    @contextmanager
    def checked_lock(stream):
        assert hasattr(stream, "fileno") and hasattr(stream, "seek")
        assert "b" in stream.mode
        with native_lock(stream):
            yield

    monkeypatch.setattr(registrations, "lock", checked_lock)
    target = config_target("cursor", tmp_path, global_scope=False)
    registration(target, "demo", entry=entry, source=source)
    assert json.loads(target.path.read_bytes())[target.key]["demo"] == entry


@pytest.mark.parametrize("layer", ["kilo.json", "kilo.jsonc", ".kilo/kilo.jsonc"])
def test_kilo_unrelated_jsonc_layer_is_preserved(tmp_path, source, entry, layer):
    target = config_target("kilo", tmp_path, global_scope=False)
    competing = tmp_path / layer
    competing.parent.mkdir(exist_ok=True)
    raw = b'{// literal config\n"mcp":{"foreign":{"enabled":false},},}\n'
    competing.write_bytes(raw)
    with pytest.raises(CondaError, match="conda mcp render"):
        registration(
            target, "demo", entry={"type": "remote", "url": entry["url"]}, source=source
        )
    assert competing.read_bytes() == raw
    assert not target.path.exists()
    assert not receipt_path(target).exists()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"mcp":{"demo":{"enabled":false}}}',
        b'{"mcp":{},"mcp":{}}',
        b'{"mcp":"PRIVATE"}',
    ],
)
def test_kilo_ambiguous_layers_refuse_without_writes(tmp_path, source, entry, raw):
    target = config_target("kilo", tmp_path, global_scope=False)
    (tmp_path / "kilo.jsonc").write_bytes(raw)
    with pytest.raises(CondaError, match="Kilo") as caught:
        registration(target, "demo", entry=entry, source=source)
    assert "PRIVATE" not in str(caught.value)
    assert not target.path.parent.exists()


@pytest.mark.parametrize(
    "setting", ["KILO_CONFIG", "KILO_CONFIG_DIR", "KILO_CONFIG_CONTENT"]
)
def test_kilo_unknown_override_refuses_without_writes(
    tmp_path, source, entry, setting, monkeypatch
):
    monkeypatch.setenv(setting, "private-override")
    target = config_target("kilo", tmp_path, global_scope=False)
    with pytest.raises(CondaError, match="Kilo"):
        registration(target, "demo", entry=entry, source=source)
    assert not target.path.parent.exists()


def test_kilo_jsonc_syntax_in_selected_json_is_left_untouched(tmp_path, source, entry):
    target = config_target("kilo", tmp_path, global_scope=False)
    target.path.parent.mkdir()
    raw = b'{/* keep */"mcp":{}}'
    target.path.write_bytes(raw)
    with pytest.raises(CondaError):
        registration(target, "demo", entry=entry, source=source)
    assert target.path.read_bytes() == raw
    assert not receipt_path(target).exists()


def test_idempotent_kilo_link_rechecks_new_competing_layers(tmp_path, source, entry):
    target = config_target("kilo", tmp_path, global_scope=False)
    rendered = {"type": "remote", "url": entry["url"]}
    registration(target, "demo", entry=rendered, source=source)
    (tmp_path / "kilo.jsonc").write_text('{"mcp":{"demo":{"enabled":false}}}')
    before = target.path.read_bytes(), receipt_path(target).read_bytes()
    with pytest.raises(CondaError, match="another Kilo layer"):
        registration(target, "demo", entry=rendered, source=source)
    assert (target.path.read_bytes(), receipt_path(target).read_bytes()) == before


def test_source_change_is_reported_even_if_rendered_entry_did_not_change(
    tmp_path, source, entry
):
    target = config_target("cursor", tmp_path, global_scope=False)
    registration(target, "demo", entry=entry, source=source)
    manifest = tmp_path / source["manifest"]
    document = json.loads(manifest.read_bytes())
    document["description"] = "Updated description"
    manifest.write_text(json.dumps(document))
    [state] = registration(target)
    assert state["state"] == "managed" and state["source_state"] == "changed"
    current = discover(tmp_path)[0].to_dict()
    updated = {key: current[key] for key in source}
    before = target.path.read_bytes()
    assert registration(target, "demo", entry=entry, source=updated)["changed"]
    assert target.path.read_bytes() == before
    assert registration(target)[0]["source_state"] == "current"


def test_provider_substitution_is_not_silently_refreshed(tmp_path, source, entry):
    target = config_target("cursor", tmp_path, global_scope=False)
    registration(target, "demo", entry=entry, source=source)
    record_path = tmp_path / "conda-meta/provider-1-0.json"
    record = json.loads(record_path.read_bytes())
    record["name"] = "substitute"
    record_path.unlink()
    (record_path.parent / "substitute-1-0.json").write_text(json.dumps(record))
    assert registration(target)[0]["source_state"] == "provider-changed"
    current = discover(tmp_path)[0].to_dict()
    updated = {key: current[key] for key in source}
    with pytest.raises(CondaError, match="different provider"):
        registration(target, "demo", entry=entry, source=updated)


def test_unlink_survives_native_source_removal(tmp_path, source, entry):
    target = config_target("cursor", tmp_path, global_scope=False)
    registration(target, "demo", entry=entry, source=source)
    (tmp_path / "conda-meta/provider-1-0.json").unlink()
    (tmp_path / source["manifest"]).unlink()
    assert registration(target)[0]["source_state"] == "missing"
    assert registration(target, "demo")["removed"]
    assert registration(target) == []


@pytest.fixture
def interrupted(tmp_path, source, entry):
    """Stage a complete interrupted link intent without touching the actual entry."""
    target = config_target("claude-code", tmp_path, global_scope=False)
    record = {"digest": fingerprint(entry), **source}
    pending = {
        "operation": "link",
        "target": str(target.path),
        "container": target.key,
        "key": "demo",
        "before": {"absent": True},
        "after": {"digest": fingerprint(entry)},
        "previous": None,
        "record": record,
    }
    ledger = {"schema_version": 1, "entries": {}, "pending": pending}
    target.path.write_text(
        json.dumps({target.key: {"foreign": {"enabled": False}}, "user-edit": True})
    )
    receipt_path(target).write_text(json.dumps(ledger))
    return target, ledger


@pytest.mark.parametrize("after", [False, True])
def test_recovery_never_replays_old_config_or_loses_unrelated_edits(
    interrupted, entry, after
):
    target, ledger = interrupted
    if after:
        document = json.loads(target.path.read_bytes())
        document[target.key]["demo"] = entry
        target.path.write_text(json.dumps(document))
    before = target.path.read_bytes()
    states = registration(target)
    assert {row["name"] for row in states} == {"demo", "foreign"}
    assert next(row for row in states if row["name"] == "demo")["state"] == "pending"
    assert "pending" in json.loads(receipt_path(target).read_bytes())
    registration(target, "missing")
    assert target.path.read_bytes() == before
    recovered = json.loads(receipt_path(target).read_bytes())
    assert "pending" not in recovered
    assert recovered["entries"] == (
        {"demo": ledger["pending"]["record"]} if after else {}
    )


def test_ambiguous_recovery_refuses_even_force(interrupted):
    target, ledger = interrupted
    target.path.write_text(json.dumps({target.key: {"demo": {"user-edit": True}}}))
    before = target.path.read_bytes(), receipt_path(target).read_bytes()
    with pytest.raises(CondaError, match="Ambiguous"):
        registration(target, "demo", force=True)
    assert (target.path.read_bytes(), receipt_path(target).read_bytes()) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation", "overwrite"),
        ("target", "/other/config"),
        ("container", "other"),
        ("key", 123),
        ("before", None),
        ("after", {"digest": "bad"}),
        ("previous", {}),
        ("record", {"digest": "a" * 64}),
    ],
)
def test_malformed_pending_preserves_both_files(interrupted, field, value):
    target, ledger = interrupted
    ledger["pending"][field] = value
    receipt_path(target).write_text(json.dumps(ledger))
    before = target.path.read_bytes(), receipt_path(target).read_bytes()
    with pytest.raises(CondaError, match="receipt"):
        registration(target, "demo", force=True)
    assert (target.path.read_bytes(), receipt_path(target).read_bytes()) == before


@pytest.mark.parametrize("boundary", [1, 2, 3])
def test_interrupted_write_recovers_without_rewriting_user_edits(
    tmp_path, source, entry, monkeypatch, boundary
):
    target = config_target("claude-code", tmp_path, global_scope=False)
    native_replace = registrations.atomic_write
    calls = 0

    def fail_after_replace(path, text, previous, **kwargs):
        nonlocal calls
        native_replace(path, text, previous, **kwargs)
        calls += 1
        if calls == boundary:
            raise OSError("injected interruption")

    monkeypatch.setattr(registrations, "atomic_write", fail_after_replace)
    with pytest.raises(OSError, match="interruption"):
        registration(target, "demo", entry=entry, source=source)
    monkeypatch.setattr(registrations, "atomic_write", native_replace)
    document = json.loads(target.path.read_bytes()) if target.path.exists() else {}
    document["later-edit"] = {"secret": "never-in-receipt"}
    target.path.write_text(json.dumps(document))
    registration(target, "demo", entry=entry, source=source)
    assert json.loads(target.path.read_bytes())["later-edit"] == {
        "secret": "never-in-receipt"
    }
    assert "never-in-receipt" not in receipt_path(target).read_text()
    assert "pending" not in json.loads(receipt_path(target).read_bytes())


def test_stale_source_refuses_before_any_destination_write(tmp_path, source, entry):
    (tmp_path / source["manifest"]).unlink()
    target = config_target("cursor", tmp_path, global_scope=False)
    with pytest.raises(CondaError, match="source"):
        registration(target, "demo", entry=entry, source=source)
    assert not target.path.parent.exists()


def test_source_change_after_intent_preserves_client_configuration(
    tmp_path, source, entry, monkeypatch
):
    target = config_target("claude-code", tmp_path, global_scope=False)
    original = b'{"mcpServers":{"foreign":{"command":"keep"}}}\n'
    target.path.write_bytes(original)
    native_write = registrations.atomic_write

    def change_source_after_intent(path, data, expected, **kwargs):
        native_write(path, data, expected, **kwargs)
        if path == receipt_path(target) and "pending" in json.loads(data):
            manifest = tmp_path / source["manifest"]
            document = json.loads(manifest.read_bytes())
            document["description"] = "Replaced during registration"
            manifest.write_text(json.dumps(document))

    monkeypatch.setattr(registrations, "atomic_write", change_source_after_intent)
    with pytest.raises(CondaError, match="source changed"):
        registration(target, "demo", entry=entry, source=source)
    assert target.path.read_bytes() == original
    assert "pending" in json.loads(receipt_path(target).read_bytes())


def test_receipt_record_owns_validation_and_is_immutable(source, entry):
    record = registrations.ReceiptRecord.from_dict(
        {**source, "digest": fingerprint(entry)}
    )
    assert record.to_dict() == {**source, "digest": fingerprint(entry)}
    assert record.source_state("demo") == "current"
    with pytest.raises(FrozenInstanceError):
        record.package = "different"


def test_receipt_model_reads_and_serializes_complete_intent(interrupted):
    target, ledger = interrupted
    receipt = registrations.Receipt.load(target)
    assert json.loads(receipt.encode()) == ledger
    assert receipt.pending.name == "demo"
    with pytest.raises(FrozenInstanceError):
        receipt.pending.name = "different"


def test_pending_unlink_recovery_retains_other_receipts(tmp_path, source, entry):
    target = config_target("cursor", tmp_path, global_scope=False)
    registration(target, "demo", entry=entry, source=source)
    ledger = json.loads(receipt_path(target).read_bytes())
    previous = ledger["entries"]["demo"]
    ledger["pending"] = {
        "operation": "unlink",
        "target": str(target.path),
        "container": target.key,
        "key": "demo",
        "before": {"digest": previous["digest"]},
        "after": {"absent": True},
        "previous": previous,
        "record": None,
    }
    receipt_path(target).write_text(json.dumps(ledger))
    target.path.write_text(json.dumps({target.key: {}, "later": True}))
    registration(target, "missing")
    assert json.loads(receipt_path(target).read_bytes())["entries"] == {}
    assert json.loads(target.path.read_bytes())["later"] is True


def test_concurrent_config_edit_is_preserved_and_pending_is_not_replayed(
    tmp_path, source, entry, monkeypatch
):
    target = config_target("cursor", tmp_path, global_scope=False)
    native_write = registrations.atomic_write

    def edit_after_intent(path, data, expected, **kwargs):
        native_write(path, data, expected, **kwargs)
        if path == receipt_path(target) and "pending" in json.loads(data):
            target.path.write_text(
                json.dumps({"mcpServers": {"demo": {"command": "USER-EDIT"}}})
            )

    monkeypatch.setattr(registrations, "atomic_write", edit_after_intent)
    with pytest.raises(CondaError, match="changed"):
        registration(target, "demo", entry=entry, source=source)
    assert (
        json.loads(target.path.read_bytes())["mcpServers"]["demo"]["command"]
        == "USER-EDIT"
    )
    assert registration(target)[0]["state"] == "pending"
    with pytest.raises(CondaError, match="Ambiguous"):
        registration(target, "demo", force=True)


def test_receipt_only_refresh_rechecks_the_config_before_finalizing(
    tmp_path, source, entry, monkeypatch
):
    target = config_target("cursor", tmp_path, global_scope=False)
    registration(target, "demo", entry=entry, source=source)
    manifest = tmp_path / source["manifest"]
    document = json.loads(manifest.read_bytes())
    document["description"] = "Updated source only"
    manifest.write_text(json.dumps(document))
    current = discover(tmp_path)[0].to_dict()
    updated = {key: current[key] for key in source}
    native_write = registrations.atomic_write

    def edit_after_intent(path, data, expected, **kwargs):
        native_write(path, data, expected, **kwargs)
        if path == receipt_path(target) and "pending" in json.loads(data):
            target.path.write_text(
                json.dumps({"mcpServers": {"demo": {"disabled": True}}})
            )

    monkeypatch.setattr(registrations, "atomic_write", edit_after_intent)
    with pytest.raises(CondaError, match="changed"):
        registration(target, "demo", entry=entry, source=updated)
    assert "pending" in json.loads(receipt_path(target).read_bytes())
    assert (
        json.loads(target.path.read_bytes())["mcpServers"]["demo"]["disabled"] is True
    )


@pytest.mark.parametrize("mutation", ["removed", "invalid"])
def test_receipt_source_status_never_blocks_unlink(tmp_path, source, entry, mutation):
    target = config_target("cursor", tmp_path, global_scope=False)
    registration(target, "demo", entry=entry, source=source)
    manifest = tmp_path / source["manifest"]
    if mutation == "invalid":
        manifest.write_text("{invalid}")
    else:
        (tmp_path / "conda-meta/provider-1-0.json").unlink()
    [state] = registration(target)
    assert state["source_state"] == ("invalid" if mutation == "invalid" else "missing")
    assert registration(target, "demo")["removed"] is True


def test_pending_intent_rejects_a_record_for_a_different_entry(interrupted):
    target, ledger = interrupted
    ledger["pending"]["record"]["manifest"] = "share/conda-mcp/servers/different.json"
    receipt_path(target).write_text(json.dumps(ledger))
    before = receipt_path(target).read_bytes()
    with pytest.raises(CondaError, match="receipt"):
        registration(target, "missing")
    assert receipt_path(target).read_bytes() == before


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"schema_version": True, "entries": {}},
        {"schema_version": 1, "entries": {}, "extra": None},
    ],
)
def test_invalid_receipt_schema_never_mutates_destination(
    tmp_path, source, entry, value
):
    target = config_target("claude-code", tmp_path, global_scope=False)
    target.path.write_text(json.dumps({"mcpServers": {}}))
    receipt_path(target).write_text(json.dumps(value))
    before = target.path.read_bytes(), receipt_path(target).read_bytes()
    with pytest.raises(CondaError, match="receipt"):
        registration(target, "demo", entry=entry, source=source)
    assert (target.path.read_bytes(), receipt_path(target).read_bytes()) == before
