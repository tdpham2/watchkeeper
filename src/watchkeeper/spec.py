"""Strict, offline campaign configuration; no approval or execution behavior."""

from decimal import Decimal, DecimalException
from pathlib import Path
import re
import tomllib
from types import MappingProxyType
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


def _number(value: object) -> Decimal:
    if type(value) not in (int, float, Decimal):
        raise ValueError("must be a number, not a string or boolean")
    return Decimal(str(value))


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _environment_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("must be an environment variable name")
    if value.upper().startswith(("ALCF_", "GLOBUS_", "IRI_")):
        raise ValueError("HPC credential namespaces cannot be passed through")
    return value


Text = Annotated[str, AfterValidator(_nonblank)]
PositiveInt = Annotated[int, Field(gt=0)]
Amount = Annotated[Decimal, BeforeValidator(_number), Field(ge=0)]
PositiveAmount = Annotated[Amount, Field(gt=0)]
Fraction = Annotated[Amount, Field(gt=0, lt=1)]
EnvironmentName = Annotated[str, AfterValidator(_environment_name)]
Billing = Literal["api", "subscription", "free"]
IRI_BASE_URL = "https://api.alcf.anl.gov/api/v2"


class SpecModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        allow_inf_nan=False,
        validate_default=True,
        hide_input_in_errors=True,
    )


class AdapterCapabilities(SpecModel):
    model_config = ConfigDict(frozen=True)
    billing_modes: frozenset[Billing]
    reports_cost: bool


# Configuration contracts, not claims about an installed CLI's capabilities.
ADAPTER_CAPABILITIES = MappingProxyType(
    {
        "claude_code": AdapterCapabilities(
            billing_modes=frozenset({"api", "subscription"}),
            reports_cost=True,
        ),
        "chemgraph": AdapterCapabilities(
            billing_modes=frozenset({"api", "free"}),
            reports_cost=False,
        ),
    }
)


class BudgetSpec(SpecModel):
    node_hours: Amount
    llm_usd: Amount | None = None
    deadline: AwareDatetime | None = None
    soft: list[Fraction] = Field(
        default_factory=lambda: [Decimal("0.5"), Decimal("0.8")],
    )

    @field_validator("soft")
    @classmethod
    def ordered_thresholds(cls, value: list[Decimal]) -> list[Decimal]:
        if value != sorted(set(value)):
            raise ValueError("thresholds must be increasing and unique")
        return value


class EnvelopeSpec(SpecModel):
    templates: Annotated[list[Text], Field(min_length=1)]
    queues: Annotated[list[Text], Field(min_length=1)]
    max_nodes: PositiveInt
    max_walltime_s: PositiveInt
    max_concurrent_jobs: PositiveInt
    max_actions_per_wake: PositiveInt


class BackendSpec(SpecModel):
    kind: Literal["simulated", "iri"]
    iri_base_url: str | None = None

    @field_validator("iri_base_url")
    @classmethod
    def https_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            url = urlsplit(value)
            valid = (
                url.scheme == "https"
                and bool(url.hostname)
                and url.username is None
                and url.password is None
                and not any(
                    c.isspace() or ord(c) < 32 or ord(c) == 127 or c in "\\?#"
                    for c in value
                )
                and (url.port is None or url.port > 0)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "must be an absolute HTTPS URL without credentials, query, or fragment"
            )
        return value

    @model_validator(mode="after")
    def backend_settings(self) -> Self:
        if self.kind == "simulated" and self.iri_base_url is not None:
            raise ValueError("iri_base_url requires backend.kind = iri")
        if self.kind == "iri" and self.iri_base_url is None:
            self.iri_base_url = IRI_BASE_URL
        return self


class AgentSpec(SpecModel):
    interactive: bool = True
    adapter: Literal["claude_code", "chemgraph"] | None = None
    billing: Billing | None = None
    model: Text | None = None
    max_wakes: PositiveInt | None = None
    max_turns: PositiveInt | None = None
    timeout_s: PositiveInt | None = None
    max_wakes_per_day: PositiveInt | None = None
    max_usd_per_wake: PositiveAmount | None = None
    env_passthrough: list[EnvironmentName] = Field(default_factory=list)

    @model_validator(mode="after")
    def adapter_settings(self) -> Self:
        if self.adapter is None:
            if self.model_fields_set - {"interactive"}:
                raise ValueError("headless settings require an adapter")
            return self
        if any(
            getattr(self, name) is None
            for name in (
                "billing",
                "max_wakes",
                "max_turns",
                "timeout_s",
            )
        ):
            raise ValueError(
                "adapter requires billing, max_wakes, max_turns, and timeout_s"
            )
        if self.billing not in ADAPTER_CAPABILITIES[self.adapter].billing_modes:
            raise ValueError("billing mode is not supported by this adapter")
        for name in self.env_passthrough:
            name = name.upper()
            api_credential = name.endswith(("_API_KEY", "_AUTH_TOKEN")) or name in {
                "API_KEY",
                "AUTH_TOKEN",
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN",
            }
            if api_credential and self.billing != "api":
                raise ValueError("env_passthrough API credentials require API billing")
            if name == "CLAUDE_CODE_OAUTH_TOKEN" and (
                self.adapter != "claude_code" or self.billing != "subscription"
            ):
                raise ValueError(
                    "env_passthrough subscription credentials require Claude subscription billing"
                )
        return self


class CampaignSpec(SpecModel):
    goal: Text
    budget: BudgetSpec
    envelope: EnvelopeSpec
    backend: BackendSpec
    agent: AgentSpec = Field(default_factory=AgentSpec)

    @model_validator(mode="after")
    def cost_threshold(self) -> Self:
        if self.budget.llm_usd is not None:
            capability = ADAPTER_CAPABILITIES.get(self.agent.adapter)
            if (
                self.agent.billing != "api"
                or not capability
                or not capability.reports_cost
            ):
                raise ValueError(
                    "budget.llm_usd requires an API-billed, cost-reporting adapter"
                )
            if self.agent.max_usd_per_wake is None:
                raise ValueError("budget.llm_usd requires agent.max_usd_per_wake")
        return self


class CampaignConfigError(ValueError):
    """Configuration diagnostics safe to display without input values."""


def load_campaign(path: Path) -> CampaignSpec:
    """Read only this TOML file, preserving decimal amounts and hiding input values."""
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream, parse_float=Decimal)
    except (OSError, UnicodeError):
        raise CampaignConfigError("campaign.toml: cannot read a UTF-8 file") from None
    except (ValueError, DecimalException):
        raise CampaignConfigError("campaign.toml: invalid TOML") from None
    try:
        return CampaignSpec.model_validate(data)
    except ValidationError as exc:
        errors = exc.errors(
            include_input=False, include_context=False, include_url=False
        )
        raise CampaignConfigError(
            "\n".join(
                f"{'.'.join(map(str, error['loc'])) or 'campaign'}: {error['msg']}"
                for error in errors
            )
        ) from None
