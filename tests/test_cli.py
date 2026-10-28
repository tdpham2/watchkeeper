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
        (["--help"], 0, "validate campaign configuration only"),
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
def test_validate_cli(campaign_file, explicit_directory):
    original = campaign_file.read_bytes()
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
    assert list(campaign_file.parent.iterdir()) == [campaign_file]


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
