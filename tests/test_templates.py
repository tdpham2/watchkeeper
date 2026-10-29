"""Strict scalar contracts remain separate from JSON proposal transport."""

from copy import deepcopy
from decimal import Decimal
import json

from pydantic import ValidationError
import pytest

from watchkeeper.actions import ProposalRequest
from watchkeeper.spec import CampaignConfigError
from watchkeeper.templates import ParameterSpec, TemplateSpec, load_template


@pytest.fixture
def template_data():
    return dict(
        params={
            "label": dict(type="string", max_length=12, pattern="[a-z ]+"),
            "count": dict(type="integer", min=1, max=10),
            "scale": dict(type="number", min=-1.5, max=2),
            "enabled": dict(type="boolean", required=False),
        },
        outputs=["result.json"],
        exit_codes={"0": "ok", "2": "nonconverged"},
    )


def test_values_preserved_and_validation_has_no_effects(template_data):
    spec = TemplateSpec.model_validate(template_data)
    params = dict(label=" a b ", count=1, scale=2, enabled=True)
    original = deepcopy(params)
    result = spec.validate_params(params)
    assert result == params == original and result is not params
    assert type(result["scale"]) is int
    assert spec.validate_params(dict(label="a", count=10, scale=-1.5)) == dict(
        label="a", count=10, scale=-1.5
    )
    request = ProposalRequest.model_validate(
        dict(
            request_id="one",
            actions=[
                dict(
                    kind="run",
                    template="example",
                    params=params,
                    resources=dict(nodes=1, walltime_s=60, queue="debug"),
                    rationale="test",
                )
            ],
        )
    )
    assert spec.validate_params(request.actions[0].params) == params


@pytest.mark.parametrize(
    "field,value",
    [
        ("label", "not_match!"),
        ("label", "a" * 13),
        ("label", 1),
        ("count", True),
        ("count", 1.0),
        ("count", "1"),
        ("count", 0),
        ("count", 11),
        ("scale", True),
        ("scale", "1"),
        ("scale", float("inf")),
        ("scale", float("nan")),
        ("scale", Decimal("1")),
        ("scale", -1.6),
        ("scale", 2.1),
        ("scale", {"nested": []}),
        ("enabled", 0),
        ("enabled", "true"),
        ("enabled", None),
        ("extra", "PRIVATE_INPUT"),
    ],
)
def test_invalid_params(template_data, field, value):
    spec = TemplateSpec.model_validate(template_data)
    with pytest.raises(CampaignConfigError) as error:
        spec.validate_params(dict(label="a", count=1, scale=1) | {field: value})
    assert "PRIVATE_INPUT" not in str(error.value)


@pytest.mark.parametrize("params", [None, [], {1: "x"}, {}, {"label": "a"}])
def test_bad_parameter_object_or_missing_required(template_data, params):
    with pytest.raises(CampaignConfigError):
        TemplateSpec.model_validate(template_data).validate_params(params)


@pytest.mark.parametrize(
    "declaration",
    [
        {},
        {"type": "object"},
        {"type": "array"},
        {"type": "boolean", "unknown": 1},
        {"type": "boolean", "required": "true"},
        {"type": "boolean", "min": 0},
        {"type": "boolean", "max_length": 4},
        {"type": "number"},
        {"type": "number", "min": 0},
        {"type": "number", "min": 2, "max": 1},
        {"type": "integer", "min": 0.5, "max": 2},
        {"type": "number", "min": False, "max": 2},
        {"type": "number", "min": 0, "max": float("inf")},
        {"type": "number", "min": Decimal("0.1"), "max": 2},
        {"type": "string"},
        {"type": "string", "max_length": 0},
        {"type": "string", "max_length": 4, "pattern": "[PRIVATE_INPUT"},
        {"type": "string", "max_length": 4, "pattern": "a{9999999999999999999999}"},
        {"type": "string", "max_length": 4, "pattern": "(" * 1000},
        {"type": "boolean", "enum": []},
        {"type": "boolean", "enum": [1]},
        {"type": "integer", "enum": [True]},
        {"type": "integer", "enum": [1.0]},
        {"type": "number", "enum": [1, 1.0]},
        {"type": "number", "enum": [float("nan")]},
        {"type": "number", "enum": [Decimal("1.5")]},
        {"type": "string", "max_length": 4, "enum": [b"text"]},
        {"type": "integer", "enum": [0], "min": 1},
        {"type": "string", "max_length": 2, "enum": ["long"]},
    ],
)
def test_invalid_declarations(declaration):
    with pytest.raises(ValidationError) as error:
        ParameterSpec.model_validate(declaration)
    assert "PRIVATE_INPUT" not in str(error.value)


@pytest.mark.parametrize(
    "declaration,good,bad",
    [
        (dict(type="string", max_length=4, enum=["low", "high"]), "low", "mid"),
        (dict(type="integer", enum=[1, 2]), 1, 3),
        (dict(type="number", enum=[0.5, 1]), 1.0, 2),
        (dict(type="boolean", enum=[False]), False, True),
    ],
)
def test_enum_contracts(declaration, good, bad):
    spec = ParameterSpec.model_validate(declaration)
    spec.check(good)
    with pytest.raises(ValueError):
        spec.check(bad)


@pytest.mark.parametrize(
    "changes",
    [
        {"extra": True},
        {"params": []},
        {"exit_codes": {}},
        {"exit_codes": {"01": "ok"}},
        {"exit_codes": {"-1": "failed"}},
        {"exit_codes": {"256": "failed"}},
        {"exit_codes": {"0": " "}},
        {"exit_codes": {0: "ok"}},
        {"outputs": ["result", "result"]},
        {"outputs": ["/absolute"]},
        {"outputs": ["../escape"]},
        {"outputs": ["x/../escape"]},
        {"outputs": ["./result"]},
        {"outputs": ["x//result"]},
        {"outputs": ["x\\result"]},
        {"outputs": ["x\x00result"]},
        {"outputs": ["C:result"]},
        {"validate": "../validator.py"},
        {"validate": "nested/validator.py"},
    ],
)
def test_invalid_template_metadata(template_data, changes):
    with pytest.raises(ValidationError):
        TemplateSpec.model_validate(template_data | changes)


def test_file_load_and_literal_shell_text(tmp_path):
    path = tmp_path / "template.toml"
    path.write_text("""outputs = ["nested/result.json"]
validate = "validate.py"
[exit_codes]
"0" = "ok"
[params.text]
type = "string"
max_length = 100
[params.scale]
type = "number"
enum = [0.5, 1.5]
required = false
""")
    spec = load_template(path)
    # Single-file API never imports or requires the validator; directory API does.
    value = {"text": "$(touch NEVER); `id`\n"}
    assert spec.validate_params(value) == value
    assert spec.validator == "validate.py" and not (tmp_path / "NEVER").exists()
    for spelling in ("NaN", "Infinity", "-Infinity"):
        raw = json.dumps(dict(type="number", enum=[0])).replace("[0]", f"[{spelling}]")
        with pytest.raises(ValidationError):
            ParameterSpec.model_validate_json(raw)
