import copy
import json
import shutil

import pytest
from PySide6.QtWidgets import QMessageBox

from pywr_editor import MainWindow
from pywr_editor.dialogs.next_components.components_dialog import (
    NextMetricSetsDialog,
    NextOutputsDialog,
    NextTablesDialog,
    NextTimeSeriesDialog,
)
from pywr_editor.form.schema_form import NamePickerWidget
from pywr_editor.model import ModelConfig
from tests.utils import model_path

NEXT_MODELS = model_path() / "pywr_next"
DIALOG_MODULE = "pywr_editor.dialogs.next_components.components_dialog"
DIALOGS = {
    "tables": NextTablesDialog,
    "time_series": NextTimeSeriesDialog,
    "metric_sets": NextMetricSetsDialog,
    "outputs": NextOutputsDialog,
}


@pytest.fixture(autouse=True)
def no_modal_boxes(monkeypatch):
    monkeypatch.setattr(
        "pywr_editor.form.form.QMessageBox.critical", staticmethod(lambda *args: None)
    )
    monkeypatch.setattr(
        f"{DIALOG_MODULE}.QMessageBox.question",
        staticmethod(lambda *args: QMessageBox.StandardButton.Yes),
    )


def components_of_test_models() -> list:
    params = []
    for file in sorted(NEXT_MODELS.glob("*.json")):
        network = json.loads(file.read_text()).get("network")
        if not isinstance(network, dict):
            continue
        for key in DIALOGS:
            for component in network.get(key) or []:
                name = component["meta"]["name"]
                params.append(
                    pytest.param(file, key, name, id=f"{file.stem}-{key}-{name}")
                )
    return params


@pytest.mark.parametrize("file, key, name", components_of_test_models())
def test_save_without_changes(qtbot, file, key, name):
    """
    Tests that each table, time series, metric set and output of the pywr-next test
    models is unchanged after its form is saved.
    """
    model = ModelConfig(str(file))
    components = DIALOGS[key].components_of(model)
    before = copy.deepcopy(components.config(name))
    dialog = DIALOGS[key](model=model, selected_name=name)
    qtbot.addWidget(dialog)
    assert dialog.save() == before
    assert components.config(name) == before


def test_add_metric_set(qtbot, tmp_path):
    """
    Tests that a metric set, which has no type, is added without asking for one.
    """
    model_file = tmp_path / "model.json"
    shutil.copy(NEXT_MODELS / "reservoir_with_evaporation1.json", model_file)
    model = ModelConfig(str(model_file))
    dialog = NextMetricSetsDialog(model=model)
    qtbot.addWidget(dialog)
    assert dialog.single_type is True
    dialog.on_add()
    assert model.metric_sets.config("New metric set") == {
        "meta": {"name": "New metric set"}
    }


def test_output_picks_metric_set(qtbot, tmp_path):
    """
    Tests that an output offers the metric sets of the model.
    """
    model_file = tmp_path / "model.json"
    shutil.copy(NEXT_MODELS / "agg-storage1.json", model_file)
    model = ModelConfig(str(model_file))
    output = model.outputs.names[0]
    dialog = NextOutputsDialog(model=model, selected_name=output)
    qtbot.addWidget(dialog)
    field = dialog.form.find_field("metric_set")
    if isinstance(field.widget, NamePickerWidget):
        combo = field.widget.combo_box
        assert "nodes" in [combo.itemText(i) for i in range(combo.count())]
    else:
        # a CSV output can have several metric sets, edited as JSON
        assert model.outputs.config(output)["type"] == "CSV"


def test_window(qtbot, tmp_path):
    """
    Tests the ribbon buttons and the tree branches of the pywr-next lists.
    """
    model_file = tmp_path / "model.json"
    shutil.copy(NEXT_MODELS / "time-series.json", model_file)
    window = MainWindow(str(model_file))
    window.hide()
    for key in ["tables", "time-series", "parameters", "metric-sets", "outputs"]:
        assert window.app_actions.get(f"edit-{key}") is not None
    assert {"time_series", "parameters", "metric_sets", "outputs"} <= set(
        window.components_tree.items
    )
    window.app_actions.get("edit-time-series").trigger()
    dialogs = [d for d in window.findChildren(NextTimeSeriesDialog) if d.isVisible()]
    assert dialogs[0].components.names == ["inflow"]
    dialogs[0].close()
    window.model_config.reset_change_flag()
    window.close()
