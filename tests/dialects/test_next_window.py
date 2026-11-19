import json
import shutil

import pytest
from PySide6.QtWidgets import QApplication

from pywr_editor import MainWindow
from pywr_editor.schematic.commands.add_node_command import AddNodeCommand
from pywr_editor.schematic.commands.connect_node_command import ConnectNodeCommand
from tests.utils import model_path

NEXT_MODELS = model_path() / "pywr_next"


@pytest.fixture
def window(qtbot, tmp_path) -> MainWindow:
    """
    Opens a copy of a pywr-next model: Catchment -> Reservoir -> Demand.
    """
    model_file = tmp_path / "model.json"
    shutil.copy(NEXT_MODELS / "reservoir_with_evaporation1.json", model_file)
    window = MainWindow(str(model_file))
    window.hide()
    yield window
    window.model_config.reset_change_flag()
    window.close()


def test_open(window):
    """
    Tests that a pywr-next model is shown on the schematic and in the tree.
    """
    assert window.model_config.dialect.key == "next"
    assert set(window.schematic.node_items) == {"Catchment", "Reservoir", "Demand"}
    assert window.model_config.edges.count == 2
    assert "nodes" in window.components_tree.items
    # the v1 components are not shown
    assert "recorders" not in window.components_tree.items


def test_v1_features_are_not_offered(window):
    """
    Tests that the features that only work with pywr v1 models are not offered.
    """
    for key in [
        "edit-imports",
        "edit-python-paths",
        "edit-slots",
        "find-orphaned-parameters",
        "run-inspector",
    ]:
        assert window.app_actions.get(key).isVisible() is False
        assert window.app_actions.get(key).isEnabled() is False

    # the results of a run are converted to what the results viewer reads
    assert window.app_actions.get("run-results").isVisible()

    # the node data panel shows the v1 node form
    assert window.model_config.dialect.supports("node-data-panel") is False


def test_node_library_lists_next_types(window):
    """
    Tests that the node library offers the pywr-next node types.
    """
    node_types = window.model_config.dialect.node_types()
    assert node_types["RiverSplitWithGauge"] == "River split with gauge"
    assert "Placeholder" not in node_types
    assert window.model_config.dialect.supports_custom_nodes is False


def test_add_connect_and_undo(window):
    """
    Tests that nodes and edges are added in the pywr-next format, and undone.
    """
    props = window.model_config.dialect.create_node("New link", "Link", (10.0, 20.0))
    window.undo_stack.push(
        AddNodeCommand(schematic=window.schematic, added_node_dict=props)
    )
    window.undo_stack.push(
        ConnectNodeCommand(
            schematic=window.schematic,
            source_node_name="New link",
            target_node_name="Demand",
        )
    )
    QApplication.processEvents()
    assert window.model_config.nodes.config("New link") == {
        "meta": {"name": "New link", "position": {"schematic": [10.0, 20.0]}},
        "type": "Link",
    }
    edge, _ = window.model_config.edges.find("New link", "Demand")
    assert edge == {"from_node": "New link", "to_node": "Demand"}

    window.undo_stack.undo()
    window.undo_stack.undo()
    assert "New link" not in window.model_config.nodes.names
    window.undo_stack.redo()
    window.undo_stack.redo()
    assert window.model_config.edges.find("New link", "Demand")[0] is not None


def test_save_positions_in_model(window):
    """
    Tests that the position and the appearance of a node are saved in the model, and
    that the data of the drawing (shapes, map) is not.
    """
    window.model_config.nodes.set_position([1.5, 2.5], node_name="Reservoir")
    window.model_config.nodes.set_node_style("Reservoir", color="red")
    assert window.model_config.save() is True

    saved = json.loads(open(window.model_config.json_file).read())
    node = saved["network"]["nodes"][1]
    assert node["meta"] == {
        "name": "Reservoir",
        "position": {"schematic": [1.5, 2.5]},
        "tags": {"editor:node_color": "red"},
    }
    assert "pywr_editor" not in saved


def test_validation_uses_next_schema(window, qtbot):
    """
    Tests that the validation dialog checks the model against the pywr-next schema.
    """
    window.open_validation_dialog()
    dialog = window.validation_dialog
    qtbot.waitUntil(lambda: dialog.schema_worker is None, timeout=20000)
    # the check with pywr loads the model with pywr v1
    assert dialog.preflight_button.isHidden() is True
    assert dialog.model_diagnostics == []
    assert dialog.schema_diagnostics == []
    dialog.close()


@pytest.mark.parametrize(
    "label, key", [("pywr v1 model", "v1"), ("pywr-next model", "next")]
)
def test_new_model_dialect(qtbot, monkeypatch, label, key):
    """
    Tests that a new model is created in the format chosen by the user.
    """
    from pywr_editor.main_window import ask_new_model_dialect

    monkeypatch.setattr(
        "PySide6.QtWidgets.QInputDialog.getItem", staticmethod(lambda *a: (label, True))
    )
    assert ask_new_model_dialect() == key
    window = MainWindow(new_dialect=key)
    window.hide()
    assert window.model_config.dialect.key == key
    assert window.model_config.is_valid()
    assert window.model_config.nodes.names == []
    assert window.model_config.dialect.label in window.windowTitle()
    window.model_config.reset_change_flag()
    window.close()


def test_new_model_cancelled(monkeypatch):
    from pywr_editor.main_window import ask_new_model_dialect

    monkeypatch.setattr(
        "PySide6.QtWidgets.QInputDialog.getItem", staticmethod(lambda *a: ("", False))
    )
    assert ask_new_model_dialect() is None
