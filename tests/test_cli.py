"""Exercise the installed CLI from outside the source directory."""

from importlib.metadata import version
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest


@pytest.mark.parametrize("entrypoint", ["console", "module"])
@pytest.mark.parametrize(
    ("arguments", "exit_code", "message"),
    [
        ([], 0, "Campaign execution is not implemented."),
        (["--help"], 0, "validate campaign, target, and template configuration"),
        (["--version"], 0, f"watchkeeper {version('watchkeeper')}"),
        (["tick"], 2, "invalid choice: 'tick'"),
    ],
)
def test_cli(entrypoint, arguments, exit_code, message, tmp_path):
    executable = "watchkeeper.exe" if sys.platform == "win32" else "watchkeeper"
    command = (
        [str(Path(sysconfig.get_path("scripts")) / executable)]
        if entrypoint == "console"
        else [sys.executable, "-m", "watchkeeper"]
    )
    result = subprocess.run(
        [*command, *arguments],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == exit_code
    assert message in (result.stderr if exit_code else result.stdout)
    assert not (result.stdout if exit_code else result.stderr)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("explicit_directory", [False, True])
def test_validate_cli(campaign_directory, explicit_directory):
    campaign_file = campaign_directory / "campaign.toml"
    original = campaign_file.read_bytes()
    before = sorted(campaign_directory.rglob("*"))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "watchkeeper",
            "validate",
            *(["--campaign", str(campaign_file.parent)] if explicit_directory else []),
        ],
        cwd=campaign_file.parent,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0 and not result.stderr
    assert "Configuration validation only" in result.stdout
    assert "execution readiness are not checked" in result.stdout
    assert campaign_file.read_bytes() == original
    assert sorted(campaign_directory.rglob("*")) == before


@pytest.mark.parametrize(
    "content,expected",
    [
        (None, "cannot read"),
        ("[bad", "invalid TOML"),
        ('goal = "PRIVATE_INPUT"', "budget: Field required"),
        ('goal = "x"\n[backend]\nkind = "PRIVATE_INPUT"', "backend.kind:"),
    ],
)
def test_validate_cli_failure(tmp_path, content, expected):
    if content is not None:
        (tmp_path / "campaign.toml").write_text(content)
    result = subprocess.run(
        [sys.executable, "-m", "watchkeeper", "validate"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2 and not result.stdout
    assert expected in result.stderr
    assert "PRIVATE_INPUT" not in result.stderr and "Traceback" not in result.stderr


@pytest.mark.parametrize("entrypoint", ["console", "module"])
@pytest.mark.parametrize("explicit_directory", [False, True])
def test_init_then_validate(entrypoint, explicit_directory, tmp_path):
    command = ([str(Path(sysconfig.get_path("scripts")) / "watchkeeper")]
               if entrypoint == "console" else [sys.executable, "-m", "watchkeeper"])
    destination = tmp_path / "new campaign" if explicit_directory else tmp_path
    arguments = ["--campaign", str(destination)] if explicit_directory else []
    for operation in ("init", "validate"):
        result = subprocess.run([*command, operation, *arguments], cwd=tmp_path,
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert not result.stderr
    before = {p.relative_to(destination): p.read_bytes()
              for p in destination.rglob("*") if p.is_file()}
    assert set(map(str, before)) == {"campaign.toml", "templates/example/template.toml"}
    result = subprocess.run([*command, "init", *arguments], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and "destination must be empty" in result.stderr
    assert not result.stdout and "Traceback" not in result.stderr
    assert before == {p.relative_to(destination): p.read_bytes()
                      for p in destination.rglob("*") if p.is_file()}
