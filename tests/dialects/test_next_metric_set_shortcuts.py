import shutil

import pytest
from PySide6.QtWidgets import QMessageBox

from pywr_editor import MainWindow
from pywr_editor.dialects.next import metric_sets as ms
from pywr_editor.dialogs.next_components.add_to_metric_set_dialog import (
    AddToMetricSetDialog,
    NEW_SET,
)
from pywr_editor.dialogs.node.next_node_dialog import NextNodeDialog
from pywr_editor.model import ModelConfig
from tests.utils import model_path

NEXT_MODELS = model_path() / "pywr_next"


@pytest.fixture
def model_file(tmp_path):
    file = tmp_path / "model.json"
    shutil.copy(NEXT_MODELS / "time-series.json", file)
    return file


@pytest.fixture
def model(model_file) -> ModelConfig:
    return ModelConfig(str(model_file))


class TestLogic:
    def test_default_attribute(self):
        assert ms.default_attribute("Reservoir") == "Volume"
        assert ms.default_attribute("Storage") == "Volume"
        assert ms.default_attribute("Link") == "Outflow"
        assert ms.default_attribute("Input") == "Outflow"
        assert ms.default_attribute(None) == "Outflow"
        assert ms.default_attribute("AnnualVirtualStorage", "VirtualNode") == "Volume"

    def test_metrics(self):
        assert ms.node_metric("a", "Volume") == {
            "type": "Node",
            "name": "a",
            "attribute": "Volume",
        }
        assert ms.node_metric("a", None) == {"type": "Node", "name": "a"}
        assert ms.node_metric("v", "Volume", "VirtualNode")["type"] == "VirtualNode"
        assert ms.parameter_metric("p") == {"type": "Parameter", "name": "p"}

    def test_sets_containing(self, model):
        assert ms.sets_containing(model, "Node", "output1") == [
            ("nodes", [{"type": "Node", "name": "output1"}])
        ]
        assert ms.sets_containing(model, "Node", "link1") == []
        assert ms.sets_containing(model, "Parameter", "output1") == []
        assert ms.describe_sets(ms.sets_containing(model, "Node", "output1")) == "nodes"
        assert (
            ms.describe_sets([("a", [{"attribute": "Volume"}, {"attribute": "Inflow"}])])
            == "a (Volume, Inflow)"
        )

    def test_add_and_remove(self, model):
        metric = ms.node_metric("link1", "Outflow")
        assert ms.add_metrics(model, "nodes", [metric]) == 1
        # no duplicate
        assert ms.add_metrics(model, "nodes", [metric]) == 0
        # another attribute is another metric
        assert ms.add_metrics(model, "nodes", [ms.node_metric("link1", "Inflow")]) == 1
        assert len(ms.sets_containing(model, "Node", "link1")[0][1]) == 2
        assert ms.remove_metrics(model, "nodes", "Node", "link1") == 2
        assert ms.sets_containing(model, "Node", "link1") == []
        assert ms.remove_metrics(model, "nodes", "Node", "link1") == 0
        assert ms.remove_metrics(model, "missing", "Node", "link1") == 0

    def test_create(self, model):
        with pytest.raises(ValueError):
            ms.add_metrics(model, "new set", [ms.parameter_metric("demand")])
        assert ms.add_metrics(
            model, "new set", [ms.parameter_metric("demand")], create=True
        ) == 1
        assert model.metric_sets.config("new set")["metrics"] == [
            {"type": "Parameter", "name": "demand"}
        ]


class TestDialog:
    def test_add_to_an_existing_set(self, qtbot, model):
        dialog = AddToMetricSetDialog(model, [("Node", "link1", "Link")])
        qtbot.addWidget(dialog)
        dialog.sets.setCurrentText("nodes")
        assert not dialog.new_name.isVisibleTo(dialog)
        assert dialog.apply()
        assert dialog.added == 1
        assert ms.sets_containing(model, "Node", "link1")[0][1] == [
            {"type": "Node", "name": "link1", "attribute": "Outflow"}
        ]

    def test_new_set_with_an_attribute(self, qtbot, model):
        dialog = AddToMetricSetDialog(
            model, [("Node", "link1", "Link"), ("Node", "input1", "Input")]
        )
        qtbot.addWidget(dialog)
        dialog.sets.setCurrentText(NEW_SET)
        assert dialog.new_name.text() == "Metrics"
        dialog.new_name.setText("Flows")
        dialog.attribute.setCurrentIndex(dialog.attribute.findData("Inflow"))
        assert dialog.apply()
        assert model.metric_sets.config("Flows")["metrics"] == [
            {"type": "Node", "name": "link1", "attribute": "Inflow"},
            {"type": "Node", "name": "input1", "attribute": "Inflow"},
        ]

    def test_parameters_have_no_attribute(self, qtbot, model):
        dialog = AddToMetricSetDialog(model, [("Parameter", "demand", None)])
        qtbot.addWidget(dialog)
        assert not dialog.has_nodes
        dialog.sets.setCurrentText("nodes")
        assert dialog.apply()
        assert {"type": "Parameter", "name": "demand"} in model.metric_sets.config(
            "nodes"
        )["metrics"]

    def test_a_name_in_use_is_refused(self, qtbot, model):
        dialog = AddToMetricSetDialog(model, [("Node", "link1", "Link")])
        qtbot.addWidget(dialog)
        dialog.sets.setCurrentText(NEW_SET)
        dialog.new_name.setText("nodes")
        assert not dialog.apply()
        assert "already exists" in dialog.message.text()
        dialog.new_name.setText("")
        assert not dialog.apply()
        assert ms.sets_containing(model, "Node", "link1") == []

    def test_a_model_without_metric_sets(self, qtbot, model):
        model.metric_sets.delete("nodes")
        dialog = AddToMetricSetDialog(model, [("Node", "link1", "Link")])
        qtbot.addWidget(dialog)
        assert dialog.sets.currentText() == NEW_SET
        assert dialog.apply()
        assert model.metric_sets.names == ["Metrics"]


def action_texts(menu) -> list[str]:
    return [a.text() for a in menu.actions()]


def test_window_menus_and_node_dialog(qtbot, model_file):
    window = MainWindow(str(model_file))
    window.hide()
    schematic = window.schematic
    node = schematic.node_items["link1"]
    assert "Add to metric set..." in action_texts(node.create_context_menu())
    both = [schematic.node_items["link1"], schematic.node_items["input1"]]
    assert "Add to metric set..." in action_texts(node.create_context_menu(both))

    # from the node dialog
    dialog = NextNodeDialog("link1", window.model_config, window)
    qtbot.addWidget(dialog)
    assert dialog.metric_sets_label.text().startswith("Not in any metric set")
    ms.add_metrics(window.model_config, "nodes", [ms.node_metric("link1", "Outflow")])
    dialog.update_metric_sets_label()
    assert dialog.metric_sets_label.text() == "Metric sets: nodes (Outflow)"
    dialog.metric_sets_button.click()
    dialogs = window.findChildren(AddToMetricSetDialog)
    assert len(dialogs) == 1
    dialogs[0].sets.setCurrentText(NEW_SET)
    dialogs[0].new_name.setText("More")
    dialogs[0].apply()
    assert "More (Outflow)" in dialog.metric_sets_label.text()
    # from the components tree
    window.components_tree.on_add_to_metric_set("demand")
    parameter_dialogs = [
        d for d in window.findChildren(AddToMetricSetDialog) if d.isVisible()
    ]
    assert parameter_dialogs
    assert "demand" in parameter_dialogs[-1].heading.text()
    for open_dialog in window.findChildren(AddToMetricSetDialog):
        open_dialog.close()
    window.model_config.reset_change_flag()
    window.close()


def test_v1_models_have_no_menu_entry(qtbot):
    from tests.utils import resolve_model_path

    window = MainWindow(str(resolve_model_path("model_1.json")))
    window.hide()
    node = next(iter(window.schematic.node_items.values()))
    assert "Add to metric set..." not in action_texts(node.create_context_menu())
    window.model_config.reset_change_flag()
    window.close()
