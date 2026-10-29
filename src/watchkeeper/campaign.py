"""Offline campaign-directory loading and non-overwriting initialization."""

from dataclasses import dataclass
from pathlib import Path
import stat

from watchkeeper.spec import (
    CampaignConfigError,
    CampaignSpec,
    PositiveInt,
    SpecModel,
    Text,
    _load_spec,
    load_campaign,
)
from watchkeeper.templates import TemplateSpec, _filename, load_template


class TargetSpec(SpecModel):
    """IRI format from ChemGraph's target.example.toml at 855e3756 (Apache-2.0)."""

    compute_resource_id: Text
    storage_resource_id: Text
    account: Text
    username: Text
    queue: Text
    filesystems: Text
    node_count: PositiveInt
    duration: PositiveInt
    remote_root: Text
    local_collection_id: Text
    local_globus_root: Text
    remote_collection_id: Text
    remote_globus_root: Text
    environment_setup: Text
    python: Text


def load_target(path: Path) -> TargetSpec:
    return _load_spec(path, TargetSpec, "target.toml")


@dataclass(frozen=True)
class CampaignDefinition:
    campaign: CampaignSpec
    target: TargetSpec | None
    templates: dict[str, TemplateSpec]


def _entry(path: Path, *, directory: bool = False) -> None:
    """Reject links and special files before reading or walking an entry."""
    mode = path.lstat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise CampaignConfigError(
            "campaign files: expected regular files/directories; no symlinks"
        )


def _template_tree(path: Path) -> None:
    _entry(path, directory=True)
    for child in path.iterdir():
        if child.is_symlink():
            raise CampaignConfigError("template files: symlinks are not allowed")
        if child.is_dir():
            _template_tree(child)
        else:
            _entry(child)


def load_campaign_directory(path: Path) -> CampaignDefinition:
    """Inspect local configuration only; this does not approve any bytes."""
    try:
        # Resolve the caller's directory (e.g. macOS /tmp); children cannot be links.
        root = path.resolve(strict=True)
        _entry(root, directory=True)
        _entry(root / "campaign.toml")
        campaign = load_campaign(root / "campaign.toml")
        target_path = root / "target.toml"
        target = None
        if (
            campaign.backend.kind == "iri"
            or target_path.exists()
            or target_path.is_symlink()
        ):
            _entry(target_path)
            target = load_target(target_path)
        _entry(root / "templates", directory=True)
        templates = {}
        for name in campaign.envelope.templates:
            try:
                _filename(name)
            except ValueError:
                raise CampaignConfigError(
                    "envelope.templates: expected single directory names"
                ) from None
            if name in templates:
                raise CampaignConfigError("envelope.templates: duplicate template")
            folder = root / "templates" / name
            _template_tree(folder)
            _entry(folder / "template.toml")
            template = load_template(folder / "template.toml")
            if template.validator is not None:
                _entry(folder / template.validator)
            templates[name] = template
        return CampaignDefinition(campaign, target, templates)
    except (OSError, RuntimeError):
        raise CampaignConfigError(
            "campaign files: cannot read required files/directories"
        ) from None


_CAMPAIGN = """goal = "Explore a small campaign"

[budget]
node_hours = 1.25

[envelope]
templates = ["example"]
queues = ["debug"]
max_nodes = 1
max_walltime_s = 600
max_concurrent_jobs = 1
max_actions_per_wake = 4

[backend]
kind = "simulated"
"""

_TEMPLATE = """# Configuration example; rendering and execution are not implemented.
outputs = ["result.json"]

[exit_codes]
"0" = "ok"
"1" = "failed"

[params.label]
type = "string"
max_length = 80
"""


def init_campaign(path: Path) -> None:
    """Create configuration in an absent/empty directory; never replace files."""
    try:
        if path.is_symlink():
            raise CampaignConfigError("init: destination must not be a symlink")
        path.mkdir(parents=True, exist_ok=True)
        if any(path.iterdir()):
            raise CampaignConfigError("init: destination must be empty")
        # Exclusive creation also refuses a conflicting concurrent initializer.
        folder = path / "templates" / "example"
        folder.mkdir(parents=True)
        with (folder / "template.toml").open("x", encoding="utf-8") as stream:
            stream.write(_TEMPLATE)
        with (path / "campaign.toml").open("x", encoding="utf-8") as stream:
            stream.write(_CAMPAIGN)
    except OSError:
        raise CampaignConfigError(
            "init: cannot create campaign configuration"
        ) from None
