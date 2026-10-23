import json
from pathlib import Path

import pytest

from pywr_editor.model import ModelConfig
from pywr_editor.model.sidecar import (
    SIDECAR_FOLDER,
    has_content,
    merge_editor_data,
    sidecar_path,
    split_model,
)

POLYGON = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]],
}


def base_model(**overrides) -> dict:
    model = {
        "metadata": {"title": "Test", "minimum_version": "1.19.0"},
        "timestepper": {"start": "2020-01-01", "end": "2020-01-10", "timestep": 1},
        "nodes": [
            {
                "name": "Input",
                "type": "Input",
                "position": {
                    "schematic": [10, 20],
                    "geographic": [-1.5, 52.0],
                    "node_color": "red",
                    "node_size": 2.0,
                    "node_style": "reservoir",
                    "edge_color": "blue",
                },
            },
            {
                "name": "Area",
                "type": "Output",
                "position": {"schematic": [30, 40], "geographic": POLYGON},
            },
            {"name": "Plain", "type": "Link"},
        ],
        "edges": [["Input", "Plain"], ["Plain", "Area"]],
        "pywr_editor": {
            "shapes": [{"id": "s1", "type": "rectangle", "x": 1, "y": 2}],
            "schematic_size": [900, 700],
            "node_types": {"Input": {"color": "red"}},
            "map": {"layers": [{"id": "l1", "path": "a.geojson"}]},
        },
    }
    model.update(overrides)
    return model


@pytest.fixture
def write_model(tmp_path):
    def _write(model: dict) -> str:
        path = tmp_path / "model.json"
        path.write_text(json.dumps(model, indent=2))
        return str(path)

    return _write


def read(path) -> dict:
    with open(path) as fid:
        return json.load(fid)


class TestSplit:
    def test_the_model_does_not_have_the_editor_data(self):
        model = base_model()
        clean, data = split_model(model)

        assert "pywr_editor" not in clean
        positions = {n["name"]: n.get("position") for n in clean["nodes"]}
        assert positions["Input"] == {"schematic": [10, 20], "geographic": [-1.5, 52.0]}
        # the footprint is replaced with its centroid, a Pywr position
        assert positions["Area"]["geographic"] == [2, 2]
        assert "position" not in clean["nodes"][2]
        assert data["shapes"] == model["pywr_editor"]["shapes"]
        assert data["nodes"]["Input"] == {
            "node_color": "red",
            "node_size": 2.0,
            "node_style": "reservoir",
            "edge_color": "blue",
        }
        assert data["nodes"]["Area"] == {"geographic_geometry": POLYGON}

    def test_the_model_in_the_editor_is_not_changed(self):
        model = base_model()
        before = json.dumps(model)
        split_model(model)
        assert json.dumps(model) == before

    def test_merge_restores_the_model(self):
        model = base_model()
        clean, data = split_model(model)
        merge_editor_data(clean, data)
        assert clean["pywr_editor"] == model["pywr_editor"]
        for original, merged in zip(model["nodes"], clean["nodes"]):
            assert merged.get("position") == original.get("position")

    def test_changed_point_wins_over_the_geometry(self):
        clean, data = split_model(base_model())
        # the position was moved outside of the editor
        clean["nodes"][1]["position"]["geographic"] = [10, 10]
        merge_editor_data(clean, data)
        assert clean["nodes"][1]["position"]["geographic"] == [10, 10]

    def test_entries_of_deleted_nodes_are_ignored(self):
        clean, data = split_model(base_model())
        del clean["nodes"][0]
        merge_editor_data(clean, data)
        assert [n["name"] for n in clean["nodes"]] == ["Area", "Plain"]

    def test_has_content(self):
        assert has_content({"shapes": [{"id": "a"}]})
        assert has_content({"nodes": {"a": {"node_color": "red"}}})
        assert not has_content({"shapes": [], "schematic_size": [800, 600]})


class TestSave:
    def test_model_and_sidecar_are_written(self, write_model):
        path = write_model(base_model())
        config = ModelConfig(path)
        assert config.load_error is None
        assert config.save() is True

        model = read(path)
        assert "pywr_editor" not in model
        assert "node_color" not in json.dumps(model)
        assert "Polygon" not in json.dumps(model)

        sidecar = sidecar_path(path)
        assert sidecar.parent.name == SIDECAR_FOLDER
        assert sidecar.parent.parent == Path(path).parent
        data = read(sidecar)
        # the sidecar can be tracked back to the model
        assert data["model"] == "model.json"
        assert data["shapes"][0]["id"] == "s1"
        assert data["nodes"]["Area"]["geographic_geometry"] == POLYGON

    def test_the_saved_model_loads_with_its_editor_data(self, write_model):
        path = write_model(base_model())
        config = ModelConfig(path)
        config.save()

        reloaded = ModelConfig(path)
        assert reloaded.load_error is None
        assert reloaded.json == config.json
        assert reloaded.editor_config["shapes"][0]["id"] == "s1"
        assert reloaded.nodes.node(reloaded.json["nodes"][1]).geographic_rings != []
        assert reloaded.nodes.node(reloaded.json["nodes"][0]).node_color == "red"

    def test_as_string_is_the_model_file(self, write_model):
        path = write_model(base_model())
        config = ModelConfig(path)
        config.save()
        with open(path) as fid:
            assert fid.read() == config.as_string
        assert "pywr_editor" not in config.as_string
        assert "pywr_editor" in config.json

    def test_clean_json_is_what_is_run(self, write_model):
        config = ModelConfig(write_model(base_model()))
        assert "pywr_editor" not in config.clean_json
        assert "node_color" not in json.dumps(config.clean_json)

    def test_loading_does_not_write_files(self, write_model):
        path = write_model(base_model())
        before = read(path)
        ModelConfig(path)
        assert read(path) == before
        assert not sidecar_path(path).exists()

    def test_no_sidecar_without_editor_data(self, write_model):
        model = base_model()
        del model["pywr_editor"]
        model["nodes"][0]["position"] = {"schematic": [1, 2]}
        model["nodes"][1]["position"] = {"schematic": [3, 4]}
        path = write_model(model)
        config = ModelConfig(path)
        config.save()
        assert not sidecar_path(path).exists()
        assert not sidecar_path(path).parent.exists()
        assert "pywr_editor" not in read(path)

    def test_sidecar_is_removed_when_the_data_is_deleted(self, write_model):
        path = write_model(base_model())
        config = ModelConfig(path)
        config.save()
        assert sidecar_path(path).exists()

        config.json["pywr_editor"] = {"shapes": []}
        for node in config.json["nodes"]:
            node["position"] = {"schematic": [1, 2]}
        config.save()
        assert not sidecar_path(path).exists()
        assert not sidecar_path(path).parent.exists()

    def test_sidecar_wins_over_the_data_in_the_model(self, write_model):
        path = write_model(base_model())
        config = ModelConfig(path)
        config.save()
        # models saved by older versions still have the data: the sidecar is used
        legacy = base_model()
        legacy["pywr_editor"]["shapes"] = [{"id": "old"}]
        with open(path, "w") as fid:
            json.dump(legacy, fid)
        assert ModelConfig(path).editor_config["shapes"][0]["id"] == "s1"

    def test_other_files_in_the_folder_are_kept(self, write_model):
        path = write_model(base_model())
        config = ModelConfig(path)
        config.save()
        (sidecar_path(path).parent / "notes.txt").write_text("keep")

        config.json["pywr_editor"] = {"shapes": []}
        for node in config.json["nodes"]:
            node["position"] = {"schematic": [1, 2]}
        config.save()
        assert not sidecar_path(path).exists()
        assert (sidecar_path(path).parent / "notes.txt").exists()

    def test_unreadable_sidecar_is_backed_up(self, write_model):
        path = write_model(base_model())
        sidecar = sidecar_path(path)
        sidecar.parent.mkdir()
        sidecar.write_text("{ not json")

        config = ModelConfig(path)
        assert config.load_error is None
        assert config.sidecar_error is not None
        # the inline data is used
        assert config.editor_config["shapes"][0]["id"] == "s1"

        assert config.save() is True
        assert config.sidecar_error is None
        assert sidecar.with_name(sidecar.name + ".bak").read_text() == "{ not json"
        assert read(sidecar)["shapes"][0]["id"] == "s1"

    def test_save_reports_a_sidecar_that_cannot_be_written(
        self, write_model, monkeypatch
    ):
        path = write_model(base_model())
        config = ModelConfig(path)

        def fail(*args, **kwargs):
            raise PermissionError("read-only folder")

        monkeypatch.setattr("pywr_editor.model.model_config.write_sidecar", fail)
        message = config.save()
        assert message is not True
        assert "read-only folder" in message
        # the model is not written, so the data is not lost
        assert "pywr_editor" in read(path)
