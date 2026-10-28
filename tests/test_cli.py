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
        (["--help"], 0, "Only help and version are available."),
        (["--version"], 0, f"watchkeeper {version('watchkeeper')}"),
        (["tick"], 2, "unrecognized arguments: tick"),
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
