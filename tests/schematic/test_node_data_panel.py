from typing import Tuple

import pytest
from PySide6.QtCore import Qt

from pywr_editor import MainWindow
from pywr_editor.dialogs import NodeDataPanel
from pywr_editor.schematic import Schematic
from tests.utils import resolve_model_path


class TestNodeDataPanel:
    model_file = resolve_model_path("model_1.json")

    @pytest.fixture
    def init_window(self) -> Tuple[MainWindow, Schematic]:
        """
        Initialises the window.
        :return: A tuple with the window and schematic instances.
        """
        window = MainWindow(self.model_file)
        window.hide()
        return window, window.schematic

    def test_double_click_shows_panel(self, qtbot, init_window) -> None:
        """
        Tests that double-clicking a node shows its data in the dockable panel,
        and that double-clicking another node replaces the panel's content.
        """
        window, schematic = init_window
        panel = window.node_data_panel
        assert isinstance(panel, NodeDataPanel)
        assert panel.isVisibleTo(window) is False

        node = schematic.node_items["Link"]
        node.mouseDoubleClickEvent(None)

        assert panel.isVisibleTo(window) is True
        assert panel.node_name == "Link"
        assert panel.form.find_field("name").widget.line_edit.text() == "Link"

        other_node = schematic.node_items["Reservoir"]
        other_node.on_show_node_data()

        assert panel.node_name == "Reservoir"
        assert panel.form.find_field("name").widget.line_edit.text() == "Reservoir"

    def test_save_updates_model_and_refreshes_panel(self, qtbot, init_window) -> None:
        """
        Tests that saving the form shown in the panel updates the model
        configuration and refreshes the panel content, including after a node
        is renamed.
        """
        window, schematic = init_window
        panel = window.node_data_panel
        model_config = schematic.model_config

        node = schematic.node_items["Link"]
        node.on_show_node_data()

        new_name = "New link name"
        panel.form.find_field("name").widget.line_edit.setText(new_name)
        qtbot.mouseClick(panel.form.save_button, Qt.MouseButton.LeftButton)

        assert model_config.nodes.find_node_index_by_name(new_name) is not None
        assert panel.node_name == new_name
        assert panel.isVisibleTo(window) is True
        assert panel.form.find_field("name").widget.line_edit.text() == new_name

    def test_hides_when_shown_node_is_deleted(self, qtbot, init_window) -> None:
        """
        Tests that the panel is hidden when the node it is currently showing is
        deleted, so that stale data cannot be saved for a node that no longer
        exists.
        """
        window, schematic = init_window
        panel = window.node_data_panel

        node = schematic.node_items["Link"]
        node.on_show_node_data()
        assert panel.isVisibleTo(window) is True

        node.on_delete_item()

        assert panel.isVisibleTo(window) is False
        assert panel.node_name is None

        # deleting the other, non-displayed node does not affect an already
        # hidden panel
        other_node = schematic.node_items["Reservoir"]
        other_node.on_show_node_data()
        other_node.on_delete_item()
        assert panel.isVisibleTo(window) is False
        assert panel.node_name is None
