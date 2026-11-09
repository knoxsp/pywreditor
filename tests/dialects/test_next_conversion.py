import json
import os
import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from pywr_editor import MainWindow
from pywr_editor.dialects.next import conversion
from pywr_editor.dialogs.convert.convert_dialog import ConvertDialog
from pywr_editor.model import ModelConfig
from tests.utils import model_path

V1_MODEL = model_path() / "model_1.json"
REAL = pytest.mark.skipif(
    not os.environ.get("PYWR_NEXT_PYTHON"),
    reason="PYWR_NEXT_PYTHON is not set to a Python with pywr-next",
)


def test_humanise_error():
    assert conversion.humanise_error("MissingAttribute") == "Missing attribute"
    assert conversion.humanise_error("UnrecognisedType") == "Unrecognised type"
    assert conversion.humanise_error(None) == "Not converted"


def test_default_file(tmp_path):
    assert conversion.default_file(tmp_path / "model.json") == tmp_path / "model_next.json"
    assert conversion.default_file(None) is None


def test_count_components():
    model = {"network": {"nodes": [1, 2], "edges": [1], "parameters": []}}
    assert conversion.count_components(model) == {
        "nodes": 2,
        "edges": 1,
        "parameters": 0,
        "tables": 0,
    }
    assert conversion.count_components({})["nodes"] == 0


@pytest.fixture
def v1_file(tmp_path) -> Path:
    file = tmp_path / "model.json"
    shutil.copy(V1_MODEL, file)
    return file


@REAL
def test_convert_a_real_model(v1_file):
    model = ModelConfig(str(v1_file))
    v1_nodes = {n["name"]: n for n in model.json["nodes"]}
    result = conversion.convert_model(os.environ["PYWR_NEXT_PYTHON"], model.json)
    network = result.model["network"]
    names = {n["meta"]["name"] for n in network["nodes"]}
    assert names == set(v1_nodes)
    assert len(network["edges"]) == len(model.json["edges"])
    # the schematic positions are kept
    for node in network["nodes"]:
        name = node["meta"]["name"]
        expected = v1_nodes[name]["position"]["schematic"]
        assert node["meta"]["position"]["schematic"] == expected
    # the custom parameters cannot be converted
    problems = {(e.component, e.name) for e in result.errors}
    assert ("parameter", "custom_param") in problems
    assert all(e.error for e in result.errors)


@REAL
def test_save_and_open_the_converted_model(tmp_path, v1_file):
    model = ModelConfig(str(v1_file))
    result = conversion.convert_model(os.environ["PYWR_NEXT_PYTHON"], model.json)
    target = tmp_path / "model_next.json"
    conversion.save_converted_model(result.model, target)

    converted = ModelConfig(str(target))
    assert converted.dialect.key == "next"
    assert converted.load_error is None
    assert set(converted.nodes.names) == set(model.nodes.names)
    # the original model is not touched
    assert json.loads(v1_file.read_text())["nodes"]


def test_the_editor_data_goes_to_the_new_model(tmp_path, v1_file, monkeypatch):
    """
    Tests that the shapes and the style of the nodes of the pywr v1 model are in the
    new model, with the style in the tags.
    """
    model = ModelConfig(str(v1_file))
    name = model.nodes.names[0]
    model.json["pywr_editor"] = {
        "shapes": [{"type": "text", "text": "Hello"}],
    }
    for node in model.json["nodes"]:
        if node["name"] == name:
            node.setdefault("position", {})["node_color"] = "red"

    converted = {
        "metadata": {"title": "t"},
        "time": {"start": "2000-01-01", "end": "2000-01-02", "timestep": {"type": "Days", "days": 1}},
        "network": {
            "nodes": [
                {"type": "Link", "meta": {"name": n, "position": {"schematic": [1, 2]}}}
                for n in model.nodes.names
            ],
            "edges": [],
        },
    }
    reply = {"model": converted, "errors": []}

    class Process:
        returncode = 0
        stdout = "\n" + json.dumps(reply)
        stderr = ""

    monkeypatch.setattr(conversion.subprocess, "run", lambda *a, **k: Process())
    result = conversion.convert_model("python", model.json)
    editor = result.model["pywr_editor"]
    assert editor["shapes"] == [{"type": "text", "text": "Hello"}]
    first = next(n for n in result.model["network"]["nodes"] if n["meta"]["name"] == name)
    assert first["meta"]["tags"]["editor:node_color"] == "red"

    target = tmp_path / "out" / "model_next.json"
    target.parent.mkdir()
    conversion.save_converted_model(result.model, target)
    saved = json.loads(target.read_text())
    assert "pywr_editor" not in saved
    sidecar = json.loads((target.parent / ".pywr-editor" / "model_next.json.json").read_text())
    assert sidecar["shapes"] == [{"type": "text", "text": "Hello"}]
    reloaded = ModelConfig(str(target))
    assert reloaded.dialect.key == "next"
    assert reloaded.json["pywr_editor"]["shapes"] == [{"type": "text", "text": "Hello"}]


def test_a_failing_conversion_raises(monkeypatch, v1_file):
    class Process:
        returncode = 1
        stdout = ""
        stderr = "ModuleNotFoundError: No module named 'pywr'"

    monkeypatch.setattr(conversion.subprocess, "run", lambda *a, **k: Process())
    with pytest.raises(RuntimeError, match="No module named"):
        conversion.convert_model("python", ModelConfig(str(v1_file)).json)

    class Garbage:
        returncode = 0
        stdout = "not json"
        stderr = ""

    monkeypatch.setattr(conversion.subprocess, "run", lambda *a, **k: Garbage())
    with pytest.raises(RuntimeError, match="did not return"):
        conversion.convert_model("python", ModelConfig(str(v1_file)).json)

    def missing(*args, **kwargs):
        raise FileNotFoundError("no python")

    monkeypatch.setattr(conversion.subprocess, "run", missing)
    with pytest.raises(RuntimeError, match="could not be started"):
        conversion.convert_model("python", ModelConfig(str(v1_file)).json)


def make_result() -> conversion.ConversionResult:
    return conversion.ConversionResult(
        model={
            "metadata": {"title": "t"},
            "time": {"start": "2000-01-01", "end": "2000-01-02", "timestep": {"type": "Days", "days": 1}},
            "network": {"nodes": [{"type": "Link", "meta": {"name": "a"}}], "edges": []},
        },
        errors=[
            conversion.ConversionError("parameter", "p", "table", "Missing attribute"),
            conversion.ConversionError("node", "n", None, "Unrecognised type"),
        ],
    )


class TestDialog:
    def test_shows_the_problems(self, qtbot, v1_file):
        dialog = ConvertDialog(make_result(), ModelConfig(str(v1_file)))
        qtbot.addWidget(dialog)
        assert dialog.table.rowCount() == 2
        assert dialog.table.item(0, 1).text() == "p"
        assert dialog.table.item(0, 2).text() == "table"
        assert dialog.table.item(1, 3).text() == "Unrecognised type"
        assert "2 components could not be converted" in dialog.errors_label.text()
        assert dialog.path.text().endswith("model_next.json")

    def test_no_problems(self, qtbot, v1_file):
        result = make_result()
        result.errors = []
        dialog = ConvertDialog(result, ModelConfig(str(v1_file)))
        qtbot.addWidget(dialog)
        assert dialog.errors_label.text() == "Everything was converted."
        assert not dialog.table.isVisibleTo(dialog)

    def test_save(self, qtbot, v1_file, tmp_path):
        dialog = ConvertDialog(make_result(), ModelConfig(str(v1_file)))
        qtbot.addWidget(dialog)
        assert dialog.save()
        assert dialog.saved_file == tmp_path / "model_next.json"
        assert json.loads(dialog.saved_file.read_text())["network"]["nodes"]

    def test_refuses_the_original_file_and_an_empty_path(self, qtbot, v1_file):
        original = v1_file.read_text()
        dialog = ConvertDialog(make_result(), ModelConfig(str(v1_file)))
        qtbot.addWidget(dialog)
        dialog.path.setText(str(v1_file))
        assert not dialog.save()
        assert "original" in dialog.message.text()
        assert v1_file.read_text() == original
        dialog.path.setText("")
        assert not dialog.save()
        assert "Enter where" in dialog.message.text()

    def test_asks_before_replacing(self, qtbot, v1_file, tmp_path, monkeypatch):
        target = tmp_path / "model_next.json"
        target.write_text("old")
        dialog = ConvertDialog(make_result(), ModelConfig(str(v1_file)))
        qtbot.addWidget(dialog)
        monkeypatch.setattr(
            "pywr_editor.dialogs.convert.convert_dialog.QMessageBox.question",
            staticmethod(lambda *args: QMessageBox.StandardButton.No),
        )
        assert not dialog.save()
        assert target.read_text() == "old"
        monkeypatch.setattr(
            "pywr_editor.dialogs.convert.convert_dialog.QMessageBox.question",
            staticmethod(lambda *args: QMessageBox.StandardButton.Yes),
        )
        assert dialog.save()
        assert target.read_text() != "old"


def test_the_button_is_for_v1_models_only(qtbot, v1_file, tmp_path):
    window = MainWindow(str(v1_file))
    window.hide()
    assert window.app_actions.get("convert-model").isVisible()
    window.model_config.reset_change_flag()
    window.close()

    next_file = tmp_path / "next.json"
    shutil.copy(model_path() / "pywr_next" / "time-series.json", next_file)
    window = MainWindow(str(next_file))
    window.hide()
    assert not window.app_actions.get("convert-model").isVisible()
    assert not window.app_actions.get("convert-model").isEnabled()
    window.model_config.reset_change_flag()
    window.close()
