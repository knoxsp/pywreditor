from typing import Tuple

import pytest
from PySide6 import QtCore, QtGui
from PySide6.QtCore import QEvent, QMimeData, QObject, QPoint
from PySide6.QtGui import QDragEnterEvent, Qt
from PySide6.QtWidgets import QWidget

from pywr_editor import MainWindow
from pywr_editor.dialogs import NodeDialog
from pywr_editor.form.widgets.parameter_line_edit_widget import ParameterLineEditWidget
from pywr_editor.model import ParameterConfig
from pywr_editor.node_shapes import CustomNode
from pywr_editor.schematic import Schematic, SchematicNode
from pywr_editor.schematic.commands.add_node_command import AddNodeCommand
from pywr_editor.toolbar.node_library.library_item import LibraryItem
from pywr_editor.toolbar.node_library.schematic_items_library import LibraryPanel
from pywr_editor.toolbar.tab_panel import TabPanel
from tests.utils import resolve_model_path


class EventFilter(QObject):
    def eventFilter(self, obj: QWidget, event: QEvent):
        super().eventFilter(obj, event)
        return False


class TestAddNodes:
    model_file = resolve_model_path("model_1.json")

    @pytest.fixture
    def init_window(self) -> Tuple[MainWindow, Schematic, TabPanel]:
        """
        Initialises the window.
        :return: A tuple with the window, schematic and tab panel instances.
        """
        window = MainWindow(self.model_file)
        window.hide()
        schematic = window.schematic
        node_lib_panel = window.toolbar.tabs["Operations"].panels["Nodes Library"]

        return window, schematic, node_lib_panel

    def test_drag_drop_node_to_schematic(self, qtbot, init_window) -> None:
        """
        Tests that when a node is dropped onto the schematic, the node is correctly
        added to the model and the schematic. This only tests the dragEnterEvent and
        dropEvent methods in the Schematic class.
        """
        window, schematic, _ = init_window
        model_config = schematic.model_config
        item_count = len(schematic.node_items)
        panel = schematic.app.toolbar.tabs["Operations"].panels["Undo"]
        undo_button = panel.buttons["Undo"]
        redo_button = panel.buttons["Redo"]

        assert undo_button.isEnabled() is False
        assert redo_button.isEnabled() is False

        # 1. Drop a link node
        mime_data = QMimeData()
        mime_data.setText("Link")

        # start the drop event
        scene_pos = QPoint(100, 50)
        event = QDragEnterEvent(
            scene_pos,
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QtCore.QCoreApplication.sendEvent(schematic.viewport(), event)

        # drop the node
        event = QtGui.QDropEvent(
            scene_pos,
            Qt.DropAction.MoveAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QEvent.Drop,
        )
        QtCore.QCoreApplication.sendEvent(schematic.viewport(), event)

        # 2. Check that the new node is in the schematic
        new_item_count = len(schematic.node_items)
        new_node_name = list(schematic.node_items.keys())[-1]
        assert new_item_count == item_count + 1
        assert "Node " in list(schematic.node_items.keys())[-1]

        assert model_config.has_changes is True
        # the node is in the model configuration
        assert model_config.nodes.find_node_index_by_name(new_node_name) is not None
        # the node dictionary is correct
        node_dict = model_config.nodes.config(new_node_name)
        node_pos = schematic.mapToScene(scene_pos).toTuple()

        assert node_dict["name"] == new_node_name
        assert node_dict["type"] == "link"
        assert node_dict["position"]["schematic"][0] == round(node_pos[0], 4)
        assert node_dict["position"]["schematic"][1] == round(node_pos[1], 4)

        # 3. Change node config
        schematic.node_items[new_node_name].on_edit_node()
        # noinspection PyTypeChecker
        dialog: NodeDialog = window.findChild(NodeDialog)
        dialog_form = dialog.form

        new_new_node_name = "New node name"
        dialog_form.find_field("name").widget.line_edit.setText(new_new_node_name)
        cost_widget: ParameterLineEditWidget = dialog_form.find_field("cost").widget
        cost_widget.component_obj = ParameterConfig({"type": "constant", "value": 9000})
        qtbot.mouseClick(dialog_form.save_button, Qt.MouseButton.LeftButton)
        dialog.close()

        # 4. Check undo action. The change of the node configuration is a step of the
        # undo stack, after the one adding the node
        assert window.undo_stack.count() == 2
        undo_command: AddNodeCommand = window.undo_stack.command(0)
        node_dict["name"] = new_new_node_name
        node_dict["cost"] = 9000

        assert undo_button.isEnabled() is True
        assert redo_button.isEnabled() is False
        assert model_config.nodes.config(new_new_node_name) == node_dict

        # undo the configuration change: the node is as it was added
        qtbot.mouseClick(undo_button, Qt.MouseButton.LeftButton)
        assert undo_button.isEnabled() is True
        assert redo_button.isEnabled() is True
        assert model_config.nodes.find_node_index_by_name(new_new_node_name) is None
        assert model_config.nodes.find_node_index_by_name(new_node_name) is not None
        assert "cost" not in model_config.nodes.config(new_node_name)
        assert new_node_name in schematic.node_items.keys()
        assert new_new_node_name not in schematic.node_items.keys()

        # redo it
        qtbot.mouseClick(redo_button, Qt.MouseButton.LeftButton)
        assert model_config.nodes.config(new_new_node_name) == node_dict
        assert new_new_node_name in schematic.node_items.keys()

        # undo the configuration change and then the node
        qtbot.mouseClick(undo_button, Qt.MouseButton.LeftButton)
        qtbot.mouseClick(undo_button, Qt.MouseButton.LeftButton)
        assert undo_button.isEnabled() is False
        assert redo_button.isEnabled() is True

        # node is removed from model config
        assert model_config.nodes.find_node_index_by_name(new_node_name) is None
        assert model_config.nodes.find_node_index_by_name(new_new_node_name) is None

        # node is removed from schematic
        assert new_node_name not in schematic.node_items.keys()
        assert new_new_node_name not in schematic.node_items.keys()
        node_names = [
            node.name for node in schematic.items() if isinstance(node, SchematicNode)
        ]
        assert new_node_name not in node_names
        assert new_new_node_name not in node_names

        # 5. Check redo action: the node is restored, then its configuration
        qtbot.mouseClick(redo_button, Qt.MouseButton.LeftButton)
        assert new_node_name in schematic.node_items.keys()
        qtbot.mouseClick(redo_button, Qt.MouseButton.LeftButton)
        assert undo_button.isEnabled() is True
        assert redo_button.isEnabled() is False
        assert model_config.nodes.config(new_new_node_name) == node_dict
        assert undo_command.node_config.name in (new_node_name, new_new_node_name)
        assert new_new_node_name in schematic.node_items.keys()

    def test_mime_type_custom_nodes(self, qtbot, init_window):
        """
        Checks that the correct mime type is set for custom nodes.
        """
        window, schematic, _ = init_window
        # noinspection PyTypeChecker
        panel: LibraryPanel = window.findChild(LibraryPanel)

        # check available nodes
        assert "CustomNode" in panel.node_dict
        assert "LeakyPipe" in panel.node_dict

        # check the type set
        custom_nodes: list[LibraryItem] = [
            i
            for i in panel.items()
            if isinstance(i, LibraryItem) and isinstance(i.item, CustomNode)
        ]
        assert custom_nodes[0].node_type == "CustomNode"
        assert custom_nodes[1].node_type == "LeakyPipe"
