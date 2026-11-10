import copy

import pytest

from pywr_editor.dialects.next.validation import validate_all, validate_network


def node(name: str, node_type: str) -> dict:
    return {"meta": {"name": name}, "type": node_type}


@pytest.fixture
def model() -> dict:
    return {
        "metadata": {"title": "Test"},
        "time": {
            "start": "2020-01-01",
            "end": "2020-01-10",
            "timestep": {"type": "Days", "days": 1},
        },
        "network": {
            "nodes": [node("in", "Input"), node("link", "Link"), node("out", "Output")],
            "edges": [
                {"from_node": "in", "to_node": "link"},
                {"from_node": "link", "to_node": "out"},
            ],
        },
    }


def with_edge(model: dict, source: str, target: str) -> dict:
    changed = copy.deepcopy(model)
    changed["network"]["edges"].append({"from_node": source, "to_node": target})
    return changed


def test_a_valid_network_has_no_diagnostics(model):
    assert validate_network(model) == []


@pytest.mark.parametrize(
    "source, target, text",
    [
        ("out", "link", "nothing can flow out of it"),
        ("link", "in", "no node can be connected to it"),
        ("in", "link", '"in" is already connected to "link"'),
    ],
)
def test_edges_pywr_next_refuses_are_errors(model, source, target, text):
    """
    pywr-next refuses these edges when it builds the network, so the model cannot run.
    """
    diagnostics = validate_network(with_edge(model, source, target))
    assert [(d.severity, d.path) for d in diagnostics if text in d.message] == [
        ("error", ("network", "edges", 2))
    ]


def test_the_existing_checks_are_not_repeated(model):
    # a self-loop is reported by the check that already exists, once
    diagnostics = validate_network(with_edge(model, "link", "link"))
    assert [d.message for d in diagnostics] == [
        'The node "link" is connected to itself'
    ]


def test_a_node_on_no_route_is_a_warning_with_its_component(model):
    model["network"]["nodes"].append(node("dead_end", "Link"))
    model["network"]["edges"].append({"from_node": "link", "to_node": "dead_end"})
    [diagnostic] = [d for d in validate_network(model) if d.severity == "warning"]
    assert "dead_end" in diagnostic.message
    assert diagnostic.component == ("node", "dead_end")
    assert diagnostic.path == ("network", "nodes", 3)


def test_the_diagnostics_are_part_of_validate_all(model):
    diagnostics = validate_all(with_edge(model, "out", "link"))
    assert any("nothing can flow out" in d.message for d in diagnostics)


def test_virtual_nodes_and_unknown_types_are_not_restricted(model):
    model["network"]["nodes"].append(node("custom", "SomeFutureNode"))
    model["network"]["edges"].append({"from_node": "link", "to_node": "custom"})
    model["network"]["virtual_nodes"] = [
        {"meta": {"name": "agg"}, "type": "AggregatedNode", "nodes": ["link"]}
    ]
    assert [d.message for d in validate_network(model) if d.severity == "error"] == []
