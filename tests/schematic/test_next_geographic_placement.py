import json

import pytest

from pywr_editor import MainWindow


def make_model(path) -> str:
    """
    Writes a pywr-next model with: a node with only a geographic position, one with
    a schematic and a geographic position, one with only a schematic position and one
    with neither.
    """
    positions = {
        "West": {"geographic": [-1.5, 51.0]},
        "East": {"geographic": [0.5, 51.0]},
        "North": {"geographic": [-0.5, 52.0]},
        "Both": {"schematic": [11, 22], "geographic": [-0.5, 51.5]},
        "Schematic": {"schematic": [33, 44]},
        "Nowhere": None,
    }
    nodes = []
    for name, position in positions.items():
        meta = {"name": name}
        if position is not None:
            meta["position"] = position
        nodes.append({"meta": meta, "type": "Link"})
    model = {
        "metadata": {"title": "Geographic"},
        "time": {
            "start": "2015-01-01",
            "end": "2015-01-31",
            "timestep": {"type": "Days", "days": 1},
        },
        "network": {"nodes": nodes, "edges": []},
    }
    file = path / "geo.json"
    file.write_text(json.dumps(model))
    return str(file)


@pytest.fixture
def window(qtbot, tmp_path) -> MainWindow:
    window = MainWindow(make_model(tmp_path))
    window.hide()
    yield window
    window.model_config.reset_change_flag()
    window.close()


def stored(window, name: str) -> list[float] | None:
    return window.model_config.nodes.config(name, as_dict=False).position


def test_nodes_are_placed_from_their_geographic_position(window):
    """
    Tests that the nodes with only a geographic position are laid out like the map,
    at the position the geographic view would draw them, instead of in a pile.
    """
    schematic = window.schematic
    west, east, north = (stored(window, n) for n in ("West", "East", "North"))
    assert west != east != north

    # the same layout as the map: west is left of east, north is above (smaller y)
    assert west[0] < east[0]
    assert north[1] < west[1] == east[1]
    # the schematic position is where the geographic view puts the node
    for name in ("West", "East", "North"):
        node = window.model_config.nodes.config(name, as_dict=False)
        geographic = node.geographic_position
        assert stored(window, name) == schematic.geo_to_scene(geographic)
    # and the node is drawn there
    assert list(schematic.node_items["East"].position) == east


def test_existing_positions_are_kept(window):
    """
    Tests that a schematic position is used when the node has one, also if the node
    has a geographic position, and that a node with neither is put in the centre.
    """
    assert stored(window, "Both") == [11, 22]
    assert stored(window, "Schematic") == [33, 44]
    schematic = window.schematic
    assert stored(window, "Nowhere") == [
        schematic.schematic_width / 2,
        schematic.schematic_height / 2,
    ]


def test_placed_nodes_are_saved(window, tmp_path):
    """
    Tests that the placed positions are written to the model when it is saved, and
    that the geographic positions are not changed.
    """
    expected = stored(window, "West")
    window.model_config.save()
    saved = json.loads((tmp_path / "geo.json").read_text())
    west = next(n for n in saved["network"]["nodes"] if n["meta"]["name"] == "West")
    assert west["meta"]["position"]["schematic"] == expected
    assert west["meta"]["position"]["geographic"] == [-1.5, 51.0]
