import json

import pytest

from pywr_editor.model import ModelConfig, validate_all


def make_model(nodes: list[tuple[str, str]], edges: list[list[str]]) -> dict:
    return {
        "metadata": {"title": "Test", "minimum_version": "1.19.0"},
        "timestepper": {"start": "2020-01-01", "end": "2020-01-10", "timestep": 1},
        "nodes": [{"name": n, "type": t} for n, t in nodes],
        "edges": edges,
    }


@pytest.fixture
def diagnostics(tmp_path):
    def _validate(model: dict):
        file = tmp_path / "model.json"
        file.write_text(json.dumps(model))
        config = ModelConfig(str(file))
        assert config.load_error is None
        return [
            (d.severity, d.message)
            for d in validate_all(config)
            if d.source == "model"
        ]

    return _validate


NODES = [("in", "Input"), ("link", "Link"), ("out", "Output")]


def test_a_valid_network_has_no_connection_diagnostics(diagnostics):
    assert diagnostics(make_model(NODES, [["in", "link"], ["link", "out"]])) == []


@pytest.mark.parametrize(
    "edge, text",
    [
        (["out", "link"], 'nothing can flow out of it'),
        (["link", "in"], "no node can be connected to it"),
    ],
)
def test_dead_edges_are_warnings_for_v1(diagnostics, edge, text):
    """
    pywr v1 accepts these edges (they carry no flow), so existing models are not
    rejected: they get a warning. The editor does not let the user add them.
    """
    found = diagnostics(make_model(NODES, [["in", "link"], ["link", "out"], edge]))
    assert [severity for severity, message in found if text in message] == ["warning"]
    assert not [severity for severity, _ in found if severity == "error"]


def test_a_duplicate_edge_is_a_warning(diagnostics):
    found = diagnostics(
        make_model(NODES, [["in", "link"], ["link", "out"], ["in", "link"]])
    )
    assert ("warning", '"in" is already connected to "link"') in found


def test_a_node_on_no_route_is_a_warning(diagnostics):
    nodes = NODES + [("dead_end", "Link")]
    found = diagnostics(
        make_model(nodes, [["in", "link"], ["link", "out"], ["link", "dead_end"]])
    )
    assert [m for _, m in found if "dead_end" in m] == [
        'The node "dead_end" is not on a route from a source (an Input, a Catchment '
        "or a Storage) to a sink (an Output or a Storage)"
    ]


def test_an_isolated_node_is_reported_once(diagnostics):
    # the check for nodes with no edge already exists
    found = diagnostics(
        make_model(NODES + [("alone", "Link")], [["in", "link"], ["link", "out"]])
    )
    assert [m for _, m in found if "alone" in m] == [
        'The node "alone" is not connected to any other node'
    ]
