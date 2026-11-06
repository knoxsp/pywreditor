import copy
import json
from pathlib import Path

import pytest

from pywr_editor.dialects import detect_dialect
from pywr_editor.dialects.next.validation import (
    component_from_path,
    schema_info,
    validate_all,
    validate_network,
    validate_schema,
)
from tests.utils import model_path

NEXT_MODELS = model_path() / "pywr_next"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def single_network_models() -> list[Path]:
    """
    The pywr-next models with one network that pywr-next loads.
    """
    return sorted(
        f
        for f in NEXT_MODELS.glob("*.json")
        if "network" in load(f) and f.parent == NEXT_MODELS
    )


@pytest.fixture
def model() -> dict:
    return load(NEXT_MODELS / "reservoir_with_evaporation1.json")


def test_schema_info():
    """
    Tests that the version of the bundled schema is recorded.
    """
    assert schema_info()["pywr_version"].startswith("2.")


def test_fixtures_found():
    assert len(single_network_models()) > 50


@pytest.mark.parametrize("file", single_network_models(), ids=lambda f: f.name)
def test_valid_models(file):
    """
    Tests that the pywr-next test models pass the validation.
    """
    assert validate_all(load(file)) == []


@pytest.mark.parametrize(
    "file, message",
    [
        ("duplicate-parameter-name.json", 'The parameter name "demand" is used 2'),
        ("duplicate-virtual-node-name.json", 'The node name "total" is used 2'),
        ("duplicate-node-name-with-composite.json", 'The node name "supply1" is'),
    ],
)
def test_invalid_models(file, message):
    """
    Tests the invalid pywr-next test models that the editor can check without
    loading the model with pywr-next.
    """
    diagnostics = validate_all(load(NEXT_MODELS / "invalid" / file))
    assert any(d.message.startswith(message) for d in diagnostics), diagnostics


def test_schema_error_names_component(model):
    """
    Tests that a schema error identifies the node it is in.
    """
    model["network"]["nodes"][1]["max_volume"] = "not a metric"
    diagnostics = validate_schema(model)
    assert len(diagnostics) > 0
    assert diagnostics[0].component == ("node", "Reservoir")
    assert diagnostics[0].path[:3] == ("network", "nodes", 1)


def test_missing_section(model):
    """
    Tests that a missing required section is reported.
    """
    del model["time"]
    assert any(
        "'time' is a required property" in d.message for d in validate_all(model)
    )


@pytest.mark.parametrize(
    "edge, message",
    [
        ({"from_node": "Missing", "to_node": "Demand"}, 'node "Missing" does not'),
        ({"from_node": "Demand", "to_node": "Demand"}, "connected to itself"),
    ],
)
def test_invalid_edges(model, edge, message):
    """
    Tests that edges to unknown nodes and to the same node are reported.
    """
    model["network"]["edges"].append(edge)
    diagnostics = validate_network(model)
    assert len(diagnostics) == 1
    assert message in diagnostics[0].message
    assert diagnostics[0].path == ("network", "edges", 2)


def test_edge_to_virtual_node(model):
    """
    Tests that edges to virtual nodes are reported.
    """
    model["network"]["virtual_nodes"] = [
        {"meta": {"name": "Total"}, "type": "Aggregated", "nodes": []}
    ]
    model["network"]["edges"].append({"from_node": "Total", "to_node": "Demand"})
    messages = [d.message for d in validate_network(model)]
    assert messages == ['The source node "Total" is a virtual node']


def test_component_from_path(model):
    """
    Tests that paths outside named components have no component.
    """
    assert component_from_path(model, ("network", "nodes", 0)) == (
        "node",
        "Catchment",
    )
    assert component_from_path(model, ("network", "nodes", 99)) is None
    assert component_from_path(model, ("time", "start")) is None
    broken = copy.deepcopy(model)
    del broken["network"]["nodes"][0]["meta"]
    assert component_from_path(broken, ("network", "nodes", 0)) is None


@pytest.mark.parametrize(
    "file",
    sorted(NEXT_MODELS.rglob("*.json")),
    ids=lambda f: str(f.relative_to(NEXT_MODELS)),
)
def test_detect_fixtures(file):
    """
    Tests that the pywr-next models and network files are detected as pywr-next,
    and the v1 models used by pywr-next's conversion tests as v1 (the converted
    models next to them are pywr-next models).
    """
    is_v1 = file.parent.name == "v1" and not file.stem.endswith("-converted")
    expected = "v1" if is_v1 else "next"
    assert detect_dialect(load(file)).key == expected
