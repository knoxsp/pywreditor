import copy
import json
import shutil

import pytest

from pywr_editor import MainWindow
from pywr_editor.dialogs.node.next_node_dialog import NextNodeDialog
from pywr_editor.model import ModelConfig
from tests.utils import model_path

NEXT_MODELS = model_path() / "pywr_next"


@pytest.fixture(autouse=True)
def no_error_box(monkeypatch):
    # a form that does not validate shows a modal message box
    monkeypatch.setattr(
        "pywr_editor.form.form.QMessageBox.critical", staticmethod(lambda *args: None)
    )


@pytest.fixture
def model(tmp_path) -> ModelConfig:
    """
    Catchment -> Reservoir -> Demand, with a metric set naming the nodes.
    """
    model_file = tmp_path / "model.json"
    shutil.copy(NEXT_MODELS / "reservoir_with_evaporation1.json", model_file)
    return ModelConfig(str(model_file))


def open_dialog(qtbot, model: ModelConfig, name: str) -> NextNodeDialog:
    dialog = NextNodeDialog(node_name=name, model_config=model)
    qtbot.addWidget(dialog)
    return dialog


def nodes_of_test_models() -> list:
    params = []
    for file in sorted(NEXT_MODELS.glob("*.json")):
        network = json.loads(file.read_text()).get("network")
        if isinstance(network, dict):
            for node in network["nodes"]:
                params.append(
                    pytest.param(
                        file,
                        node["meta"]["name"],
                        id=f"{file.stem}-{node['meta']['name']}",
                    )
                )
    return params


@pytest.mark.parametrize("file, name", nodes_of_test_models())
def test_save_without_changes(qtbot, file, name):
    """
    Tests that saving the dialog of each node of the pywr-next test models leaves
    the node unchanged.
    """
    model = ModelConfig(str(file))
    before = copy.deepcopy(model.nodes.config(name))
    dialog = open_dialog(qtbot, model, name)
    assert dialog.save() == before
    assert model.nodes.config(name) == before


def test_edit_value(qtbot, model):
    """
    Tests that a changed metric is saved.
    """
    dialog = open_dialog(qtbot, model, "Reservoir")
    metric = dialog.form.find_field("max_volume").widget
    metric.editors["value"].widget.setText("2000")
    dialog.save()
    assert model.nodes.config("Reservoir")["max_volume"] == {
        "type": "Literal",
        "value": 2000,
    }
    assert model.has_changes


def test_rename(qtbot, model):
    """
    Tests that renaming a node renames its edges and the references to it.
    """
    dialog = open_dialog(qtbot, model, "Reservoir")
    dialog.form.find_field("name").widget.line_edit.setText("Lake")
    dialog.save()
    assert model.nodes.names == ["Catchment", "Lake", "Demand"]
    assert model.edges.targets("Catchment") == ["Lake"]
    metric_names = [
        m["name"] for m in model.json["network"]["metric_sets"][0]["metrics"]
    ]
    assert metric_names == ["Lake", "Lake", "Demand"]
    assert dialog.node_name == "Lake"


@pytest.mark.parametrize("new_name", ["Demand", "", "  "])
def test_invalid_name(qtbot, model, new_name):
    dialog = open_dialog(qtbot, model, "Reservoir")
    dialog.form.find_field("name").widget.line_edit.setText(new_name)
    assert dialog.save() is False
    assert "Reservoir" in model.nodes.names


def test_comment_and_meta(qtbot, model):
    """
    Tests that the comment is saved in the meta, which keeps the position and tags.
    """
    model.nodes.set_position([1, 2], node_name="Demand")
    model.nodes.config("Demand")["meta"]["tags"] = {"zone": "north"}
    dialog = open_dialog(qtbot, model, "Demand")
    dialog.form.find_field("comment").widget.line_edit.setPlainText("A demand")
    dialog.save()
    assert model.nodes.config("Demand")["meta"] == {
        "name": "Demand",
        "comment": "A demand",
        "position": {"schematic": [1, 2]},
        "tags": {"zone": "north"},
    }

    dialog = open_dialog(qtbot, model, "Demand")
    dialog.form.find_field("comment").widget.line_edit.setPlainText("")
    dialog.save()
    assert "comment" not in model.nodes.config("Demand")["meta"]


def test_window_opens_next_dialog(qtbot, tmp_path):
    model_file = tmp_path / "model.json"
    shutil.copy(NEXT_MODELS / "reservoir_with_evaporation1.json", model_file)
    window = MainWindow(str(model_file))
    window.hide()
    window.open_node_dialog("Reservoir")
    dialogs = [d for d in window.findChildren(NextNodeDialog) if d.isVisible()]
    assert len(dialogs) == 1
    dialogs[0].close()
    # nodes without a position were placed on the schematic: do not ask to save
    window.model_config.reset_change_flag()
    window.close()
