import json

import pytest

from pywr_editor.model import ModelConfig, validate_all, validate_model, validate_schema
from pywr_editor.model.validation import component_from_path, schema_info
from tests.utils import resolve_model_path


def base_model(**overrides) -> dict:
    model = {
        "metadata": {"title": "Test", "minimum_version": "1.19.0"},
        "timestepper": {"start": "2020-01-01", "end": "2020-01-10", "timestep": 1},
        "nodes": [
            {"name": "Input", "type": "Input", "max_flow": 5},
            {"name": "Output", "type": "Output", "max_flow": 5, "cost": -10},
        ],
        "edges": [["Input", "Output"]],
    }
    model.update(overrides)
    return model


@pytest.fixture
def make_config(tmp_path):
    def _make(model: dict) -> ModelConfig:
        file = tmp_path / "model.json"
        file.write_text(json.dumps(model))
        config = ModelConfig(str(file))
        assert config.load_error is None
        return config

    return _make


def messages(diagnostics, severity=None, source=None) -> list[str]:
    return [
        d.message
        for d in diagnostics
        if (severity is None or d.severity == severity)
        and (source is None or d.source == source)
    ]


def test_schema_info():
    info = schema_info()
    assert info["target_pywr_version"] == "1.23.0"


def test_valid_model(make_config):
    config = make_config(base_model())
    assert validate_all(config) == []


def test_schema_accepts_editor_keys(make_config):
    # positions, the editor configuration and node styles are not rejected
    model = base_model()
    model["nodes"][0]["position"] = {"schematic": [10, 20], "geographic": [-1, 50]}
    model["pywr_editor"] = {"shapes": [], "map": {"crs": "EPSG:4326"}}
    assert validate_schema(model) == []


def test_schema_errors_have_a_path_and_component():
    model = base_model()
    del model["timestepper"]["end"]
    diagnostics = validate_schema(model)
    errors = [d for d in diagnostics if d.severity == "error"]
    assert len(errors) == 1
    assert "'end' is a required property" in errors[0].message
    assert errors[0].path == ("timestepper",)

    model = base_model()
    model["edges"] = [["Input", 1]]
    errors = validate_schema(model)
    assert errors[0].path == ("edges", 0, 1)


def test_strict_findings_are_warnings():
    # the standard schema reads an invalid core definition as a custom parameter
    model = base_model()
    model["parameters"] = {
        "p": {
            "type": "ControlCurve",
            "storage_node": "Input",
            "control_curve": 12,
            "values": "wrong",
        }
    }
    diagnostics = validate_schema(model)
    assert len(diagnostics) == 1
    assert diagnostics[0].severity == "warning"
    assert diagnostics[0].component == ("parameter", "p")
    assert diagnostics[0].path == ("parameters", "p")


def test_duplicated_nodes_missing_edge_nodes(make_config):
    # the editor refuses to load these, but the model can change after it is loaded
    config = make_config(base_model())
    config.json["edges"].append(["Input", "Missing"])
    config.json["nodes"].append({"name": "Input", "type": "Output"})
    errors = messages(validate_model(config), "error")
    assert any("used by 2 nodes" in m for m in errors)
    assert any('"Missing", which does not exist' in m for m in errors)


def test_missing_references(make_config):
    model = base_model()
    model["nodes"][0]["max_flow"] = "missing_param"
    model["parameters"] = {
        "agg": {"type": "aggregated", "agg_func": "sum", "parameters": ["nope"]},
        "tbl": {"type": "tablesarray", "table": "no_table", "scenario": "no_scen"},
        "node_param": {"type": "flow", "node": "NoNode"},
    }
    diagnostics = validate_model(make_config(model), include_orphans=False)
    errors = messages(diagnostics, "error")
    assert (
        '"max_flow" refers to the parameter "missing_param", which does not exist'
        in errors
    )
    assert 'The parameter "nope" does not exist' in errors
    assert 'The table "no_table" does not exist' in errors
    assert 'The scenario "no_scen" does not exist' in errors
    assert 'The node "NoNode" does not exist' in errors
    node_diagnostic = next(d for d in diagnostics if "missing_param" in d.message)
    assert node_diagnostic.component == ("node", "Input")
    assert node_diagnostic.path == ("nodes", 0, "max_flow")


def test_custom_component_references_are_warnings(make_config):
    model = base_model(
        parameters={"c": {"type": "my_custom_parameter", "table": "whatever"}}
    )
    diagnostics = validate_model(make_config(model), include_orphans=False)
    assert messages(diagnostics, "error") == []
    assert len(messages(diagnostics, "warning")) == 1


def test_existing_references_are_not_reported(make_config):
    model = base_model(
        parameters={
            "p": {"type": "constant", "value": 1},
            "agg": {"type": "aggregated", "agg_func": "sum", "parameters": ["p"]},
        },
        tables={"t": {"url": "t.csv"}},
        scenarios=[{"name": "s", "size": 2}],
    )
    model["nodes"][0]["max_flow"] = "agg"
    diagnostics = validate_model(make_config(model), include_orphans=False)
    assert messages(diagnostics, "error") == []


def test_missing_files_are_warnings(make_config):
    model = base_model(
        tables={"t": {"url": "does_not_exist.csv"}},
        includes=["does_not_exist.py"],
    )
    warnings = messages(validate_model(make_config(model)), "warning")
    assert 'The file "does_not_exist.csv" does not exist' in warnings
    assert 'The imported file "does_not_exist.py" does not exist' in warnings


def test_orphans_are_warnings(make_config):
    model = base_model(parameters={"unused": {"type": "constant", "value": 1}})
    model["nodes"].append({"name": "Lonely", "type": "Output"})
    diagnostics = validate_model(make_config(model))
    warnings = messages(diagnostics, "warning")
    assert 'The node "Lonely" is not connected to any other node' in warnings
    assert 'The parameter "unused" is not used by any component' in warnings
    assert messages(validate_model(make_config(model), include_orphans=False)) == []


def test_validate_all_lists_errors_first(make_config):
    config = make_config(
        base_model(parameters={"unused": {"type": "constant", "value": 1}})
    )
    config.json["edges"].append(["Input", "Missing"])
    severities = [d.severity for d in validate_all(config)]
    assert severities == sorted(severities, key=lambda s: s != "error")
    assert severities[0] == "error"


def test_component_from_path():
    model = base_model(parameters={"p": {"type": "constant", "value": 1}})
    assert component_from_path(model, ("nodes", 1, "cost")) == ("node", "Output")
    assert component_from_path(model, ("parameters", "p", "value")) == (
        "parameter",
        "p",
    )
    assert component_from_path(model, ("timestepper", "end")) is None
    assert component_from_path(model, ("nodes", 9)) is None


def test_real_test_model_has_no_errors():
    config = ModelConfig(resolve_model_path("model_1.json"))
    assert messages(validate_all(config), "error") == []
