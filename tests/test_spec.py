"""Offline configuration contracts, including billing and credential exclusions."""

from datetime import datetime, timezone
from decimal import Decimal
import os
import socket
import subprocess
import tomllib

from pydantic import ValidationError
import pytest

from watchkeeper.spec import CampaignConfigError, CampaignSpec, load_campaign


@pytest.fixture
def data(campaign_file):
    return tomllib.loads(campaign_file.read_text(), parse_float=Decimal)


def headless(adapter="claude_code", billing="api"):
    return dict(
        adapter=adapter, billing=billing, max_wakes=3, max_turns=10, timeout_s=60
    )


def test_decimal_precision_defaults_and_read_only_loading(campaign_file):
    original = campaign_file.read_text().replace(
        "1.25", "0.12345678901234567890123456789"
    )
    campaign_file.write_text(original)
    spec = load_campaign(campaign_file)
    assert spec.budget.node_hours == Decimal("0.12345678901234567890123456789")
    assert spec.budget.soft == [Decimal("0.5"), Decimal("0.8")]
    assert spec.agent.interactive and spec.agent.adapter is None
    assert spec.backend.iri_base_url is None
    assert list(campaign_file.parent.iterdir()) == [campaign_file]
    assert campaign_file.read_text() == original


def test_loading_does_not_read_environment_or_contact_services(
    campaign_file, monkeypatch
):
    campaign_file.write_text(
        campaign_file.read_text()
        + """[agent]
adapter = "claude_code"
billing = "api"
max_wakes = 1
max_turns = 2
timeout_s = 30
env_passthrough = ["ANTHROPIC_API_KEY"]
"""
    )

    def forbidden(*args, **kwargs):
        pytest.fail("configuration validation must remain offline")

    with monkeypatch.context() as patch:
        patch.setattr(os, "environ", {})
        patch.setattr(os, "getenv", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        patch.setattr(subprocess, "Popen", forbidden)
        assert load_campaign(campaign_file).agent.env_passthrough == [
            "ANTHROPIC_API_KEY"
        ]


@pytest.mark.parametrize(
    "adapter,billing",
    [
        ("claude_code", "api"),
        ("claude_code", "subscription"),
        ("chemgraph", "api"),
        ("chemgraph", "free"),
    ],
)
def test_supported_adapters(data, adapter, billing):
    data["agent"] = headless(adapter, billing)
    data["agent"].update(
        model="example",
        max_wakes_per_day=2,
        env_passthrough=["ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS"],
    )
    assert CampaignSpec.model_validate(data).agent.billing == billing


def test_api_threshold_and_native_toml_deadline(campaign_file):
    text = campaign_file.read_text().replace(
        "node_hours = 1.25",
        """node_hours = 0
llm_usd = 0.1
deadline = 2000-01-01T00:00:00Z
soft = []""",
    )
    campaign_file.write_text(
        text
        + """[agent]
adapter = "claude_code"
billing = "api"
max_wakes = 1
max_turns = 2
timeout_s = 30
max_usd_per_wake = 0.01
"""
    )
    spec = load_campaign(campaign_file)
    assert spec.budget.llm_usd == Decimal("0.1")
    assert spec.budget.node_hours == 0
    assert spec.budget.soft == []
    assert spec.budget.deadline == datetime(2000, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("url", [None, "https://example.invalid:8443/api/v2/"])
def test_iri_endpoint(data, url):
    data["backend"] = {"kind": "iri"}
    if url is not None:
        data["backend"]["iri_base_url"] = url
    assert CampaignSpec.model_validate(data).backend.iri_base_url == (
        url or "https://api.alcf.anl.gov/api/v2"
    )


@pytest.mark.parametrize(
    "path,value",
    [
        ("goal", "  "),
        ("goal", 3),
        ("unknown", 1),
        ("wake", {}),
        ("stop", {}),
        ("budget.node_hours", -1),
        ("budget.node_hours", True),
        ("budget.node_hours", "1.2"),
        ("budget.node_hours", float("inf")),
        ("budget.node_hours", Decimal("NaN")),
        ("budget.unknown", 1),
        ("budget.soft", [0.8, 0.5]),
        ("budget.soft", [0.5, 0.5]),
        ("budget.soft", [0]),
        ("budget.soft", [1]),
        ("budget.soft", [True]),
        ("budget.deadline", datetime(2030, 1, 1)),
        ("budget.deadline", "2030-01-01T00:00:00Z"),
        ("envelope.templates", []),
        ("envelope.templates", [" "]),
        ("envelope.queues", []),
        ("envelope.queues", [1]),
        ("envelope.max_nodes", 0),
        ("envelope.max_nodes", True),
        ("envelope.max_walltime_s", 1.5),
        ("envelope.max_concurrent_jobs", "1"),
        ("envelope.max_actions_per_wake", -1),
        ("envelope.unknown", True),
        ("backend", {}),
        ("backend.kind", "unknown"),
        ("backend.unknown", 1),
        ("backend.iri_base_url", "https://example.invalid"),
        ("agent", {"interactive": "true"}),
        ("agent", {"adapter": "unknown"}),
        ("agent", {"billing": "api"}),
        ("agent", {"env_passthrough": []}),
    ],
)
def test_invalid_fields(data, path, value):
    target = data
    *parents, name = path.split(".")
    for parent in parents:
        target = target[parent]
    target[name] = value
    with pytest.raises(ValidationError):
        CampaignSpec.model_validate(data)


@pytest.mark.parametrize("field", ["goal", "budget", "envelope", "backend"])
def test_required_sections(data, field):
    del data[field]
    with pytest.raises(ValidationError):
        CampaignSpec.model_validate(data)


@pytest.mark.parametrize("field", ["billing", "max_wakes", "max_turns", "timeout_s"])
def test_required_headless_settings(data, field):
    data["agent"] = headless()
    del data["agent"][field]
    with pytest.raises(ValidationError, match="adapter requires"):
        CampaignSpec.model_validate(data)


@pytest.mark.parametrize(
    "overrides",
    [
        {"billing": "free"},
        {"adapter": "chemgraph", "billing": "subscription"},
        {"max_wakes": 0},
        {"max_turns": True},
        {"timeout_s": "60"},
        {"max_wakes_per_day": -1},
        {"max_usd_per_wake": 0},
        {"model": " "},
        {"unknown": 1},
    ],
)
def test_invalid_headless_settings(data, overrides):
    data["agent"] = headless() | overrides
    with pytest.raises(ValidationError):
        CampaignSpec.model_validate(data)


@pytest.mark.parametrize(
    "agent",
    [
        {},
        headless(),
        headless("chemgraph"),
        headless(billing="subscription"),
        headless("chemgraph", "free"),
    ],
)
def test_llm_threshold_requires_cost_capability_and_per_wake_allowance(data, agent):
    data["budget"]["llm_usd"] = 1
    data["agent"] = agent
    with pytest.raises(ValidationError, match="budget.llm_usd requires"):
        CampaignSpec.model_validate(data)


@pytest.mark.parametrize(
    "name,billing",
    [
        ("ALCF_TOKEN", "api"),
        ("GLOBUS_TOKEN", "api"),
        ("IRI_TOKEN", "api"),
        ("iri_token", "api"),
        ("ALCF_OTHER", "subscription"),
        ("ANTHROPIC_API_KEY", "subscription"),
        ("ANTHROPIC_AUTH_TOKEN", "subscription"),
        ("OPENAI_API_KEY", "subscription"),
        ("AWS_SECRET_ACCESS_KEY", "subscription"),
        ("CLAUDE_CODE_OAUTH_TOKEN", "api"),
        ("BAD=VALUE", "api"),
        ("BAD\n", "api"),
    ],
)
def test_forbidden_environment_names(data, name, billing):
    data["agent"] = headless(billing=billing) | {"env_passthrough": [name]}
    with pytest.raises(ValidationError):
        CampaignSpec.model_validate(data)


@pytest.mark.parametrize(
    "adapter,billing,names",
    [
        ("claude_code", "api", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"]),
        ("claude_code", "subscription", ["CLAUDE_CODE_OAUTH_TOKEN"]),
        ("chemgraph", "api", ["OPENAI_API_KEY"]),
        ("chemgraph", "free", ["ARGO_USER"]),
    ],
)
def test_compatible_environment_names(data, adapter, billing, names):
    data["agent"] = headless(adapter, billing) | {"env_passthrough": names}
    assert CampaignSpec.model_validate(data).agent.env_passthrough == names


@pytest.mark.parametrize(
    "url",
    [
        "http://example.invalid",
        "/api/v2",
        "https:///api/v2",
        "https://user:secret@example.invalid",
        "https://example.invalid?",
        "https://example.invalid#",
        " https://example.invalid",
        "https://example.invalid\\other",
        "https://example.invalid:wrong",
        "https://[broken",
        "https://example.invalid:65536",
        "https://example.invalid:0",
        "https://example.invalid\x00",
        "https://example.invalid\x7f",
    ],
)
def test_invalid_iri_endpoints(data, url):
    data["backend"] = dict(kind="iri", iri_base_url=url)
    with pytest.raises(ValidationError, match="absolute HTTPS URL"):
        CampaignSpec.model_validate(data)


@pytest.mark.parametrize(
    "raw",
    [
        b"[bad",
        b"\xff",
        b'goal = "private-value"\n',
        b"value = 1e999999999999999999999999",
        b"value = " + b"9" * 5000,
    ],
)
def test_loader_errors_omit_values(campaign_file, raw):
    campaign_file.write_bytes(raw)
    with pytest.raises(CampaignConfigError) as error:
        load_campaign(campaign_file)
    assert "private-value" not in str(error.value)


def test_missing_file(tmp_path):
    with pytest.raises(CampaignConfigError, match="cannot read"):
        load_campaign(tmp_path / "missing.toml")
    assert not list(tmp_path.iterdir())
