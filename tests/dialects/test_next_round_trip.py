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
    model.nodes.set_node_style("Reservoir", color="red")
    assert model.save() is True

    saved = json.loads(model_file.read_text())
    assert validate_all(saved) == []
    # pywr-next ignores unknown keys in the position, so check that the editor data
    # is not written there
    saved_node = [
        n for n in saved["network"]["nodes"] if n["meta"]["name"] == "Reservoir"
    ]
    assert saved_node[0]["meta"]["position"] == {"schematic": [10, 20]}

    reloaded = ModelConfig(str(model_file))
    node = reloaded.nodes.config("Reservoir", as_dict=False)
    assert node.position == [10, 20]
    assert node.node_color == "red"
