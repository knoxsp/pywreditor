import json
import shutil
from pathlib import Path

import pytest

from pywr_editor.dialects.next.validation import validate_all
from pywr_editor.model import ModelConfig
from pywr_editor.model.constants import Constants
from tests.utils import model_path

NEXT_MODELS = model_path() / "pywr_next"
EDITOR_KEY = Constants.EDITOR_CONFIG_KEY.value


def single_network_models() -> list[Path]:
    """
    The pywr-next models with one network that pywr-next loads.
    """
    return sorted(
        f for f in NEXT_MODELS.glob("*.json") if "network" in json.loads(f.read_text())
    )


def without_editor_data(model: dict) -> dict:
    return {key: value for key, value in model.items() if key != EDITOR_KEY}


def has_positions(model: dict) -> bool:
    return any("position" in node.get("meta", {}) for node in model["network"]["nodes"])


@pytest.mark.parametrize("file", single_network_models(), ids=lambda f: f.name)
def test_round_trip(tmp_path, file):
    """
    Loads, saves and reloads each pywr-next test model. The model must not change
    and must still be valid. The editor data goes to a sidecar file, so the saved
    model file is compared only for models without positions, which the editor may
    keep in the sidecar.
    """
    original = json.loads(file.read_text())
    model_file = tmp_path / file.name
    shutil.copy(file, model_file)

    model = ModelConfig(str(model_file))
    assert model.is_valid(), model.load_error
    assert model.dialect.key == "next"
    assert validate_all(model.clean_json) == []
    assert model.save() is True

    if not has_positions(original):
        assert json.loads(model_file.read_text()) == original

    reloaded = ModelConfig(str(model_file))
    assert reloaded.is_valid(), reloaded.load_error
    assert without_editor_data(reloaded.json) == original


def test_round_trip_with_editor_data(tmp_path):
    """
    Tests that the editor data of a pywr-next model survives a save and reload, and
    that the saved model is still valid.
    """
    file = NEXT_MODELS / "reservoir_with_evaporation1.json"
    model_file = tmp_path / file.name
    shutil.copy(file, model_file)

    model = ModelConfig(str(model_file))
    model.nodes.set_position([10, 20], node_name="Reservoir")
    model.nodes.set_node_style("Reservoir", color="red", size=1.5)
    assert model.save() is True

    saved = json.loads(model_file.read_text())
    assert validate_all(saved) == []
    # the position and the appearance are in the model: they travel with it
    saved_node = [
        n for n in saved["network"]["nodes"] if n["meta"]["name"] == "Reservoir"
    ]
    assert saved_node[0]["meta"]["position"] == {"schematic": [10, 20]}
    assert saved_node[0]["meta"]["tags"] == {
        "editor:node_color": "red",
        "editor:node_size": "1.5",
    }
    # and the sidecar is not needed for them
    assert not (model_file.parent / ".pywr-editor").exists()

    reloaded = ModelConfig(str(model_file))
    node = reloaded.nodes.config("Reservoir", as_dict=False)
    assert node.position == [10, 20]
    assert node.node_color == "red"
    assert node.node_size == 1.5


def test_appearance_survives_a_copy(tmp_path):
    """
    Tests that a copy of the model file, without any sidecar, looks the same.
    """
    file = NEXT_MODELS / "reservoir_with_evaporation1.json"
    first = tmp_path / "first" / "model.json"
    first.parent.mkdir()
    shutil.copy(file, first)
    model = ModelConfig(str(first))
    model.nodes.set_node_style("Demand", color="green")
    model.save()

    second = tmp_path / "second" / "model.json"
    second.parent.mkdir()
    shutil.copy(first, second)
    copy = ModelConfig(str(second))
    assert copy.nodes.config("Demand", as_dict=False).node_color == "green"


def test_legacy_appearance_is_moved_to_tags(tmp_path):
    """
    Tests that the appearance an earlier version wrote in the position, or in the
    sidecar, is moved to the tags when the model is loaded.
    """
    from pywr_editor.model.sidecar import write_sidecar

    file = NEXT_MODELS / "reservoir_with_evaporation1.json"
    model_file = tmp_path / "model.json"
    data = json.loads(file.read_text())
    data["network"]["nodes"][0]["meta"]["position"] = {
        "schematic": [1, 2],
        "node_color": "red",
    }
    model_file.write_text(json.dumps(data))
    write_sidecar(
        str(model_file), {"nodes": {"Demand": {"node_size": 2, "edge_color": "blue"}}}
    )

    model = ModelConfig(str(model_file))
    catchment = model.nodes.config("Catchment")["meta"]
    assert catchment["position"] == {"schematic": [1, 2]}
    assert catchment["tags"] == {"editor:node_color": "red"}
    demand = model.nodes.config("Demand", as_dict=False)
    assert demand.node_size == 2
    assert demand.edge_color == "blue"
