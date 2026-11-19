import json

import pytest

from pywr_editor import MainWindow

NODES = [
    ("in", "Input", [100, 100]),
    ("link", "Link", [250, 100]),
    ("link2", "Link", [250, 250]),
    ("out", "Output", [400, 100]),
]


def v1_model() -> dict:
    return {
        "metadata": {"title": "Test", "minimum_version": "1.19.0"},
        "timestepper": {"start": "2020-01-01", "end": "2020-01-10", "timestep": 1},
        "nodes": [
            {"name": n, "type": t, "position": {"schematic": p}} for n, t, p in NODES
        ],
        "edges": [["in", "link"], ["link", "out"]],
    }


def next_model() -> dict:
    return {
        "metadata": {"title": "Test"},
        "time": {
            "start": "2020-01-01",
            "end": "2020-01-10",
            "timestep": {"type": "Days", "days": 1},
        },
        "network": {
            "nodes": [
                {"meta": {"name": n, "position": {"schematic": p}}, "type": t}
                for n, t, p in NODES
            ],
            "edges": [
                {"from_node": "in", "to_node": "link"},
                {"from_node": "link", "to_node": "out"},
            ],
        },
    }


@pytest.fixture(params=[("v1", v1_model), ("next", next_model)], ids=["v1", "next"])
def window(request, qtbot, tmp_path) -> MainWindow:
    key, make = request.param
    file = tmp_path / "model.json"
    file.write_text(json.dumps(make()))
    window = MainWindow(str(file))
    window.hide()
    assert window.model_config.dialect.key == key
    yield window
    window.model_config.reset_change_flag()
    window.close()


def message(window) -> str:
    return window.statusBar().currentMessage()


def test_nothing_can_be_connected_to_an_input(window):
    """
    Tests that, when connecting from a node, the Input is not offered (nothing can
    flow into it), and that the other nodes are.
    """
    schematic = window.schematic
    link = schematic.node_items["link2"]
    schematic.on_connect_node_start(link)
    assert schematic.connecting_node_props.enabled is True
    assert getattr(schematic.node_items["in"], "connecting_mode_on", False) is False
    assert schematic.node_items["in"].isEnabled() is False
    assert schematic.node_items["out"].connecting_mode_on is True
    assert schematic.node_items["link"].connecting_mode_on is True
    schematic.on_connect_node_end(None)


def test_an_output_cannot_start_a_connection(window):
    """
    Tests that connecting from an Output does not start, and says why.
    """
    schematic = window.schematic
    schematic.on_connect_node_start(schematic.node_items["out"])
    assert schematic.connecting_node_props.enabled is False
    assert "nothing can flow out of it" in message(window)
    assert window.model_config.edges.count == 2


def test_a_node_connected_to_everything_it_can_says_so(window):
    """
    Tests that connecting from a node that is already connected to every node it can be
    connected to does not start, and says so.
    """
    schematic = window.schematic
    for target in ("link2", "out"):
        schematic.on_connect_node_start(schematic.node_items["in"])
        schematic.on_connect_node_end(schematic.node_items[target])
    assert window.model_config.edges.count == 4

    schematic.on_connect_node_start(schematic.node_items["in"])
    assert schematic.connecting_node_props.enabled is False
    assert "already connected to every node it can be connected to" in message(window)


def test_a_refused_target_creates_no_edge(window):
    """
    Tests that an edge that is not allowed is not created even if the slot is called
    with the target, and that the undo stack is untouched.
    """
    schematic = window.schematic
    count = window.model_config.edges.count
    undo_count = window.undo_stack.count()
    schematic.on_connect_node_start(schematic.node_items["link2"])
    schematic.on_connect_node_end(schematic.node_items["in"])
    assert window.model_config.edges.count == count
    assert window.undo_stack.count() == undo_count
    assert '"in" is an Input node' in message(window)


def test_an_allowed_edge_is_still_created(window):
    schematic = window.schematic
    schematic.on_connect_node_start(schematic.node_items["link2"])
    schematic.on_connect_node_end(schematic.node_items["out"])
    assert window.model_config.edges.count == 3
    assert window.model_config.edges.find_record("link2", "out") is not None
