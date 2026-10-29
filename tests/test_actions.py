"""Proposal shape and JSON fidelity, independent of campaign authorization."""

from copy import deepcopy
from decimal import Decimal
import json

from pydantic import ValidationError
import pytest

from watchkeeper.actions import ProposalRequest


@pytest.fixture
def proposal():
    return {"request_id": " intent-1 ", "actions": [
        {"kind": "run", "template": "example", "params": {},
         "resources": {"nodes": 1, "walltime_s": 60, "queue": "debug"},
         "rationale": "Explore a candidate."},
        {"kind": "note", "text": " Remember this.\n"},
        {"kind": "ask_human", "question": "Which candidate?"},
        {"kind": "stop", "reason": "Enough evidence."},
    ]}


def test_round_trip_preserves_order_types_and_text(proposal):
    proposal["actions"][0]["params"] = {
        "nested": [1, 1.25, True, False, None, {"literal": "$(touch NEVER); `id`\n"}],
    }
    original = deepcopy(proposal)
    for data in [proposal, *[proposal | {"actions": [a]} for a in proposal["actions"]]]:
        request = ProposalRequest.model_validate(data)
        assert request.model_dump(mode="json") == data
        assert ProposalRequest.model_validate_json(json.dumps(data)) == request
    assert proposal == original


@pytest.mark.parametrize("path,value", [
    (("request_id",), " \n"),
    (("request_id",), 1),
    (("actions",), []),
    (("actions",), ()),
    (("extra",), True),
    (("actions", 0, "kind"), "submit"),
    (("actions", 0, "kind"), 1),
    (("actions", 0, "type"), "run"),
    (("actions", 0, "template"), " "),
    (("actions", 0, "params"), []),
    (("actions", 0, "params"), {1: "not a string key"}),
    (("actions", 0, "rationale"), ""),
    (("actions", 0, "resources", "nodes"), True),
    (("actions", 0, "resources", "nodes"), "1"),
    (("actions", 0, "resources", "nodes"), 1.0),
    (("actions", 0, "resources", "nodes"), 0),
    (("actions", 0, "resources", "walltime_s"), -1),
    (("actions", 0, "resources", "walltime_s"), False),
    (("actions", 0, "resources", "walltime_s"), "60"),
    (("actions", 0, "resources", "queue"), ""),
    (("actions", 0, "resources", "account"), "not allowed"),
    (("actions", 1, "text"), " "),
    (("actions", 1, "extra"), True),
    (("actions", 2, "question"), " "),
    (("actions", 2, "extra"), True),
    (("actions", 3, "reason"), " "),
    (("actions", 3, "extra"), True),
])
def test_invalid_fields(proposal, path, value):
    target = proposal
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        ProposalRequest.model_validate(proposal)


def test_every_documented_field_is_required(proposal):
    paths = [(key,) for key in proposal]
    paths += [("actions", i, key) for i, a in enumerate(proposal["actions"]) for key in a]
    paths += [("actions", 0, "resources", key)
              for key in proposal["actions"][0]["resources"]]
    for path in paths:
        data = deepcopy(proposal)
        target = data
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
        with pytest.raises(ValidationError):
            ProposalRequest.model_validate(data)


@pytest.mark.parametrize("value", [
    float("nan"), float("inf"), float("-inf"), Decimal("1.25"),
    b"bytes", (1, 2), {1, 2}, object(),
])
def test_nested_params_require_finite_json_values(proposal, value):
    proposal["actions"][0]["params"] = {"nested": [{"value": value}]}
    with pytest.raises(ValidationError):
        ProposalRequest.model_validate(proposal)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_input_is_rejected(value):
    raw = ('{"request_id":"r","actions":[{"kind":"run","template":"t",'
           '"params":{"x":' + value + '},"resources":{"nodes":1,'
           '"walltime_s":1,"queue":"q"},"rationale":"r"}]}')
    with pytest.raises(ValidationError):
        ProposalRequest.model_validate_json(raw)


def test_schema_has_required_kind_discriminator():
    schema = ProposalRequest.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"request_id", "actions"}
    items = schema["properties"]["actions"]["items"]
    assert items["discriminator"]["propertyName"] == "kind"
    assert set(items["discriminator"]["mapping"]) == {"run", "note", "ask_human", "stop"}
    for variant in items["oneOf"]:
        action = schema["$defs"][variant["$ref"].rsplit("/", 1)[-1]]
        assert "kind" in action["required"] and action["additionalProperties"] is False
