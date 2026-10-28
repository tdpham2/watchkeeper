"""Keep package metadata and the chemistry-free import boundary explicit."""

import ast
from importlib.metadata import metadata, version
from pathlib import Path
import tomllib

import watchkeeper


ROOT = Path(__file__).resolve().parents[1]


def test_installed_metadata_matches_project():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert watchkeeper.__version__ == version("watchkeeper") == project["version"]
    assert metadata("watchkeeper")["Requires-Python"] == project["requires-python"]
    assert metadata("watchkeeper")["License-Expression"] == "Apache-2.0"


def test_core_has_no_chemistry_or_agent_framework_imports():
    forbidden = {"chemgraph", "langchain", "langchain_core", "ase", "rdkit"}
    for path in (ROOT / "src/watchkeeper").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not forbidden.intersection(name.split(".")[0] for name in names), path
