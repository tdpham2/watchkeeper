"""Offline template contracts. Parameters are data, never shell substitutions."""

import math
from pathlib import Path
import re
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, field_validator, model_validator

from watchkeeper.spec import (
    CampaignConfigError,
    PositiveInt,
    SpecModel,
    Text,
    _load_spec,
)


def _relative_path(value: str) -> str:
    if (
        not value
        or any(part in ("", ".", "..") for part in value.split("/"))
        or any(ord(c) < 32 or ord(c) == 127 or c in "\\:" for c in value)
    ):
        raise ValueError("must be a relative path without traversal")
    return value


def _filename(value: str) -> str:
    _relative_path(value)
    if "/" in value:
        raise ValueError("must be a single filename")
    return value


RelativePath = Annotated[str, AfterValidator(_relative_path)]
Filename = Annotated[str, AfterValidator(_filename)]
Scalar = str | int | float | bool


class ParameterSpec(SpecModel):
    type: Literal["string", "integer", "number", "boolean"]
    required: bool = True
    enum: Annotated[list[Scalar], Field(min_length=1)] | None = None
    min: int | float | None = None
    max: int | float | None = None
    pattern: str | None = None
    max_length: PositiveInt | None = None

    @field_validator("min", "max", "enum", mode="before")
    @classmethod
    def scalar_literals(cls, value):
        values = value if type(value) is list else [value]
        if value is not None and any(
            type(item) not in (str, int, float, bool) for item in values
        ):
            raise ValueError("constraints must use JSON scalar values")
        return value

    def check(self, value: object) -> None:
        allowed = {
            "string": (str,),
            "integer": (int,),
            "number": (int, float),
            "boolean": (bool,),
        }[self.type]
        if type(value) not in allowed:
            raise ValueError("incorrect scalar type")
        if type(value) is float and not math.isfinite(value):
            raise ValueError("must be finite")
        if self.enum is not None and value not in self.enum:
            raise ValueError("must be a declared enum value")
        if self.min is not None and value < self.min:
            raise ValueError("below minimum")
        if self.max is not None and value > self.max:
            raise ValueError("above maximum")
        if self.max_length is not None and len(value) > self.max_length:
            raise ValueError("exceeds maximum length")
        if self.pattern is not None and re.fullmatch(self.pattern, value) is None:
            raise ValueError("does not match pattern")

    @model_validator(mode="after")
    def constraints(self) -> Self:
        numeric = self.type in ("integer", "number")
        if not numeric and (self.min is not None or self.max is not None):
            raise ValueError("ranges require a numeric parameter")
        if self.type != "string" and (
            self.pattern is not None or self.max_length is not None
        ):
            raise ValueError("pattern and max_length require a string parameter")
        if self.type == "string" and self.max_length is None:
            raise ValueError("string parameters require max_length")
        if numeric and self.enum is None and (self.min is None or self.max is None):
            raise ValueError("numeric parameters require enum or both min and max")
        if self.type == "integer" and any(
            bound is not None and type(bound) is not int
            for bound in (self.min, self.max)
        ):
            raise ValueError("integer bounds must be integers")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not exceed max")
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except (re.error, OverflowError, RecursionError):
                raise ValueError("invalid regular expression") from None
        if self.enum is not None:
            if len(set(self.enum)) != len(self.enum):
                raise ValueError("enum values must be unique")
            for value in self.enum:
                self.check(value)
        return self


class TemplateSpec(SpecModel):
    params: dict[Text, ParameterSpec]
    outputs: list[RelativePath]
    exit_codes: Annotated[dict[str, Text], Field(min_length=1)]
    validator: Filename | None = Field(default=None, alias="validate")

    @field_validator("exit_codes")
    @classmethod
    def valid_exit_codes(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            not re.fullmatch(r"0|[1-9][0-9]{0,2}", key) or int(key) > 255
            for key in value
        ):
            raise ValueError("exit codes must be canonical integers from 0 to 255")
        return value

    @field_validator("outputs")
    @classmethod
    def unique_outputs(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("output paths must be unique")
        return value

    def validate_params(self, params: object) -> dict[str, Scalar]:
        """Check a run's params without coercion, mutation, defaults or effects."""
        if type(params) is not dict or any(type(key) is not str for key in params):
            raise CampaignConfigError("params: must be an object with string keys")
        if params.keys() - self.params.keys():
            raise CampaignConfigError("params: unknown parameters")
        for name, spec in self.params.items():
            if name not in params:
                if spec.required:
                    raise CampaignConfigError(
                        f"params.{name!r}: required parameter missing"
                    )
                continue
            try:
                spec.check(params[name])
            except ValueError as exc:
                raise CampaignConfigError(f"params.{name!r}: {exc}") from None
        return dict(params)


def load_template(path: Path) -> TemplateSpec:
    """Read metadata only; file checks belong to load_campaign_directory."""
    return _load_spec(path, TemplateSpec, "template.toml", parse_float=float)
