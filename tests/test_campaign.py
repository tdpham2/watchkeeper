"""Offline directory validation, IRI compatibility, and safe scaffolding."""

import os
import socket
import subprocess

from pydantic import ValidationError
import pytest

from watchkeeper.campaign import (
    TargetSpec,
    init_campaign,
    load_campaign_directory,
    load_target,
)
from watchkeeper.spec import CampaignConfigError, load_campaign


@pytest.fixture
def target_file(tmp_path):
    path = tmp_path / "target.toml"
    # Same fields/types as iri_configure.py at ChemGraph 855e3756; no discovery.
    path.write_text("""compute_resource_id = "compute-id"
storage_resource_id = "storage-id"
account = "project"
username = "user"
queue = "debug"
filesystems = "home:eagle"
node_count = 1
duration = 300
remote_root = "/eagle/project/user/runs"
local_collection_id = "local-id"
local_globus_root = "/~/runs"
remote_collection_id = "remote-id"
remote_globus_root = "/project/user/runs"
environment_setup = "source /env/bin/activate"
python = "/env/bin/python"
""")
    return path


def snapshot(path):
    return {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def test_directory_offline_and_read_only(campaign_directory, monkeypatch):
    root = campaign_directory
    folder = root / "templates" / "example"
    path = folder / "template.toml"
    path.write_text('validate = "validate.py"\n' + path.read_text())
    (folder / "validate.py").write_text('raise RuntimeError("must not execute")')
    before = snapshot(root)

    def forbidden(*args, **kwargs):
        pytest.fail("configuration must not execute or contact services")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "getenv", forbidden)
    definition = load_campaign_directory(root)
    assert definition.campaign.backend.kind == "simulated"
    assert definition.target is None and set(definition.templates) == {"example"}
    assert snapshot(root) == before
    assert not (root / "watchkeeper.db").exists()


def test_iri_target_and_optional_target(campaign_directory, target_file):
    root = campaign_directory
    target = load_target(target_file)
    assert target.local_globus_root == "/~/runs" and target.node_count == 1
    assert target.environment_setup == "source /env/bin/activate"
    assert load_campaign_directory(root).target == target
    path = root / "campaign.toml"
    path.write_text(path.read_text().replace('"simulated"', '"iri"'))
    assert load_campaign_directory(root).target == target
    target_file.unlink()
    with pytest.raises(CampaignConfigError, match="cannot read"):
        load_campaign_directory(root)
    assert load_campaign(path).backend.kind == "iri"


@pytest.mark.parametrize(
    "field,value",
    [
        ("node_count", True),
        ("node_count", "1"),
        ("duration", 0),
        ("account", " "),
        ("python", 1),
        ("extra", "PRIVATE_INPUT"),
    ],
)
def test_strict_target(target_file, field, value):
    data = load_target(target_file).model_dump() | {field: value}
    with pytest.raises(ValidationError):
        TargetSpec.model_validate(data)


@pytest.mark.parametrize(
    "relative",
    [
        "campaign.toml",
        "templates",
        "templates/example",
        "templates/example/template.toml",
    ],
)
def test_missing_files(campaign_directory, relative):
    path = campaign_directory / relative
    path.rename(path.with_name(path.name + "-moved"))
    with pytest.raises(CampaignConfigError, match="cannot read"):
        load_campaign_directory(campaign_directory)


@pytest.mark.parametrize(
    "relative",
    [
        "campaign.toml",
        "target.toml",
        "templates",
        "templates/example",
        "templates/example/template.toml",
        "templates/example/extra",
    ],
)
def test_symlinks_rejected(campaign_directory, relative, tmp_path_factory):
    external = tmp_path_factory.mktemp("outside")
    path = campaign_directory / relative
    if path.exists():
        saved = external / "original"
        path.rename(saved)
    else:
        saved = external / "absent"
    path.symlink_to(saved)
    with pytest.raises(CampaignConfigError):
        load_campaign_directory(campaign_directory)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a/b", "a\\b", ".", ".."])
def test_template_names_cannot_escape(campaign_directory, name):
    import json

    path = campaign_directory / "campaign.toml"
    path.write_text(path.read_text().replace('["example"]', json.dumps([name])))
    with pytest.raises(CampaignConfigError, match="directory names"):
        load_campaign_directory(campaign_directory)


def test_missing_validator_and_special_file(campaign_directory):
    folder = campaign_directory / "templates" / "example"
    path = folder / "template.toml"
    path.write_text('validate = "validate.py"\n' + path.read_text())
    with pytest.raises(CampaignConfigError, match="cannot read"):
        load_campaign_directory(campaign_directory)
    os.mkfifo(folder / "validate.py")
    with pytest.raises(CampaignConfigError, match="regular files"):
        load_campaign_directory(campaign_directory)


def test_duplicate_names_and_malformed_optional_target(campaign_directory):
    path = campaign_directory / "campaign.toml"
    original = path.read_text()
    path.write_text(original.replace('["example"]', '["example", "example"]'))
    with pytest.raises(CampaignConfigError, match="duplicate template"):
        load_campaign_directory(campaign_directory)
    path.write_text(original)
    (campaign_directory / "target.toml").write_text("[broken")
    with pytest.raises(CampaignConfigError, match="target.toml: invalid TOML"):
        load_campaign_directory(campaign_directory)


def test_initializer_does_not_overwrite_a_concurrent_file(tmp_path, monkeypatch):
    from pathlib import Path

    original_open = Path.open

    def competing_write(path, mode="r", *args, **kwargs):
        if path.name == "campaign.toml" and mode == "x":
            with original_open(path, "w") as stream:
                stream.write("concurrent content")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", competing_write)
    with pytest.raises(CampaignConfigError, match="cannot create"):
        init_campaign(tmp_path)
    assert (tmp_path / "campaign.toml").read_text() == "concurrent content"
    with pytest.raises(CampaignConfigError, match="must be empty"):
        init_campaign(tmp_path)


@pytest.mark.parametrize("content", ["[broken", 'private = "PRIVATE_INPUT"', "\x00"])
def test_bad_template_safe_diagnostics(campaign_directory, content):
    (campaign_directory / "templates/example/template.toml").write_text(content)
    with pytest.raises(CampaignConfigError) as error:
        load_campaign_directory(campaign_directory)
    assert "PRIVATE_INPUT" not in str(error.value)


def test_init_nonempty_and_invalid_destinations(tmp_path):
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("preserve")
    for path in (tmp_path, sentinel):
        with pytest.raises(CampaignConfigError):
            init_campaign(path)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "absent")
    with pytest.raises(CampaignConfigError, match="symlink"):
        init_campaign(link)
    assert sentinel.read_text() == "preserve"
    assert set(tmp_path.iterdir()) == {sentinel, link}
