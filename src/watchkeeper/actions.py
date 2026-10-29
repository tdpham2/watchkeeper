"""Proposal data contracts; validation does not authorize or execute actions."""

import json
from typing import Annotated, Literal

from pydantic import Field, JsonValue, field_validator

from watchkeeper.spec import PositiveInt, SpecModel, Text


class Resources(SpecModel):
    nodes: PositiveInt
    walltime_s: PositiveInt
    queue: Text


class RunAction(SpecModel):
    kind: Literal["run"]
    template: Text
    params: dict[str, JsonValue]
    resources: Resources
    rationale: Text

    @field_validator("params")
    @classmethod
    def finite_params(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        # JsonValue's JSON-input path does not enforce nested allow_inf_nan.
        json.dumps(value, allow_nan=False)
        return value


class NoteAction(SpecModel):
    kind: Literal["note"]
    text: Text


class AskHumanAction(SpecModel):
    kind: Literal["ask_human"]
    question: Text


class StopAction(SpecModel):
    kind: Literal["stop"]
    reason: Text


Action = Annotated[
    RunAction | NoteAction | AskHumanAction | StopAction,
    Field(discriminator="kind"),
]


class ProposalRequest(SpecModel):
    """An ordered intent, without replay, template, envelope or budget checks."""

    request_id: Text
    actions: Annotated[list[Action], Field(min_length=1)]
