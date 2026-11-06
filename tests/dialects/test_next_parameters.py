import copy
import json
import shutil

import pytest
from PySide6.QtWidgets import QMessageBox

from pywr_editor import MainWindow
from pywr_editor.dialects.next.model import NamedComponents
from pywr_editor.dialects.next.references import find_references
from pywr_editor.dialogs.next_components.components_dialog import (
    NextParametersDialog,
    open_local_parameters,
)
from pywr_editor.dialogs.search.search_model import SearchModel
from pywr_editor.model import ModelConfig
from tests.utils import model_path

NEXT_MODELS = model_path() / "pywr_next"
DIALOG_MODULE = "pywr_editor.dialogs.next_components.components_dialog"


@pytest.fixture(autouse=True)
def no_modal_boxes(monkeypatch):
    # a form that does not validate shows a modal message box
    monkeypatch.setattr(
        "pywr_editor.form.form.QMessageBox.critical", staticmethod(lambda *args: None)
    )
    # discard the unsaved changes when a dialog is closed at the end of a test
    monkeypatch.setattr(
        f"{DIALOG_MODULE}.QMessageBox.question",
        staticmethod(lambda *args: QMessageBox.StandardButton.Yes),
    )


@pytest.fixture
def model(tmp_path) -> ModelConfig:
    """
    A model where the "demand" parameter is used by a node and "factored_flow"
    uses the "inflow" time series.
    """
    model_file = tmp_path / "model.json"
    shutil.copy(NEXT_MODELS / "time-series.json", model_file)
    return ModelConfig(str(model_file))


def make_dialog(qtbot, model, name=None, **kwargs) -> NextParametersDialog:
    dialog = NextParametersDialog(model=model, selected_name=name, **kwargs)
    qtbot.addWidget(dialog)
    return dialog


class TestNamedComponents:
    def test_list(self, model):
        parameters = model.parameters
        assert isinstance(parameters, NamedComponents)
        assert set(parameters.names) == {"demand", "factored_flow"}
        assert parameters.config("demand")["type"] == "Constant"
        assert parameters.config("missing") is None
        with pytest.raises(ValueError):
            parameters.add({"meta": {"name": "demand"}, "type": "Constant"})
        with pytest.raises(ValueError):
            parameters.add({"type": "Constant"})

    def test_rename_updates_references(self, model):
        parameters = model.parameters
        component = copy.deepcopy(parameters.config("demand"))
        component["meta"]["name"] = "new_demand"
        parameters.update("demand", component)
        assert "new_demand" in parameters.names
        assert find_references(model.json, kind="parameter", name="demand") == []
        assert len(parameters.references("new_demand")) == 1

    def test_delete_last_removes_list(self, model):
        for name in list(model.parameters.names):
            model.parameters.delete(name)
        assert "parameters" not in model.json["network"]


def parameters_of_test_models() -> list:
    params = []
    for file in sorted(NEXT_MODELS.glob("*.json")):
        network = json.loads(file.read_text()).get("network")
        if isinstance(network, dict):
            for parameter in network.get("parameters") or []:
                name = parameter["meta"]["name"]
                params.append(pytest.param(file, name, id=f"{file.stem}-{name}"))
    return params


@pytest.mark.parametrize("file, name", parameters_of_test_models())
def test_save_without_changes(qtbot, file, name):
    """
    Tests that each parameter of the pywr-next test models is unchanged after its
    form is saved.
    """
    model = ModelConfig(str(file))
    before = copy.deepcopy(model.parameters.config(name))
    dialog = make_dialog(qtbot, model, name)
    assert dialog.current == name
    assert dialog.save() == before
    assert model.parameters.config(name) == before


class TestDialog:
    def test_rename(self, qtbot, model):
        dialog = make_dialog(qtbot, model, "demand")
        dialog.form.find_field("name").widget.line_edit.setText("base_demand")
        dialog.save()
        assert dialog.current == "base_demand"
        node = model.nodes.config("output1")
        assert node["max_flow"] == {"type": "Parameter", "name": "base_demand"}

    def test_duplicate_name(self, qtbot, model):
        dialog = make_dialog(qtbot, model, "demand")
        dialog.form.find_field("name").widget.line_edit.setText("factored_flow")
        assert dialog.save() is False

    def test_add_and_clone(self, qtbot, model, monkeypatch):
        monkeypatch.setattr(
            f"{DIALOG_MODULE}.QInputDialog.getItem",
            staticmethod(lambda *args: ("Constant", True)),
        )
        dialog = make_dialog(qtbot, model, "demand")
        dialog.on_add()
        assert dialog.current == "New constant"
        assert model.parameters.config("New constant") == {
            "meta": {"name": "New constant"},
            "type": "Constant",
        }
        dialog.select("demand")
        dialog.on_clone()
        assert dialog.current == "demand copy"
        clone = model.parameters.config("demand copy")
        assert {k: v for k, v in clone.items() if k != "meta"} == {
            k: v for k, v in model.parameters.config("demand").items() if k != "meta"
        }

    def test_delete(self, qtbot, model):
        # the question is answered with Yes by the no_modal_boxes fixture
        dialog = make_dialog(qtbot, model, "demand")
        dialog.on_delete()
        assert "demand" not in model.parameters.names
        assert dialog.current == "factored_flow"

    def test_filter(self, qtbot, model):
        dialog = make_dialog(qtbot, model)
        dialog.filter.setText("factor")
        visible = [
            dialog.list.item(i).text()
            for i in range(dialog.list.count())
            if not dialog.list.item(i).isHidden()
        ]
        assert visible == ["factored_flow"]


def test_local_parameters(qtbot, tmp_path):
    """
    Tests that the local parameters of a node are edited in the same dialog.
    """
    model_file = tmp_path / "model.json"
    shutil.copy(NEXT_MODELS / "local-parameter1.json", model_file)
    model = ModelConfig(str(model_file))
    dialog = open_local_parameters(model, "demand1")
    qtbot.addWidget(dialog)
    assert dialog.components.names == ["demand"]
    before = copy.deepcopy(model.nodes.config("demand1"))
    dialog.save()
    assert model.nodes.config("demand1") == before


def test_window(qtbot, tmp_path):
    """
    Tests that the parameters are in the ribbon, the tree and the search.
    """
    model_file = tmp_path / "model.json"
    shutil.copy(NEXT_MODELS / "time-series.json", model_file)
    window = MainWindow(str(model_file))
    window.hide()
    assert "parameters" in window.components_tree.items
    assert window.components_tree.items["parameters"].childCount() == 2
    types = {row["type"] for row in SearchModel(window.model_config).model_data}
    assert "parameter" in types

    window.app_actions.get("edit-parameters").trigger()
    dialogs = [d for d in window.findChildren(NextParametersDialog) if d.isVisible()]
    assert len(dialogs) == 1
    dialogs[0].close()
    window.model_config.reset_change_flag()
    window.close()
