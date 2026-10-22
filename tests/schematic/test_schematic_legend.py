from typing import Tuple

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox

from pywr_editor import MainWindow
from pywr_editor.schematic import Edge, Schematic
from pywr_editor.toolbar.tab_panel import TabPanel
from pywr_editor.utils import Settings
from tests.utils import close_message_box, resolve_model_path


class TestSchematicLegend:
    model_file = resolve_model_path("model_delete_nodes.json")

    @pytest.fixture
    def init_window(self) -> Tuple[MainWindow, Schematic, TabPanel]:
        """
        Initialises the window. The editor settings are reset first, since they are
        persisted via QSettings across test runs and the tests rely on a known
        starting state.
        :return: A tuple with the window, schematic and display panel instances.
        """
        editor_settings = Settings(self.model_file)
        editor_settings.instance.clear()
        editor_settings.instance.sync()

        QTimer.singleShot(100, close_message_box)
        window = MainWindow(self.model_file)
        window.hide()
        schematic = window.schematic
        display_panel = window.toolbar.tabs["Schematic"].panels["Display"]

        return window, schematic, display_panel

    def test_node_type_groups(self, qtbot, init_window) -> None:
        """
        Tests that the nodes on the schematic are grouped by pywr type, with the
        correct label and count, for the legend.
        """
        _, schematic, _ = init_window
        groups = {group["type"]: group for group in schematic.node_type_groups()}

        assert set(groups.keys()) == {"link", "storage", "virtualstorage"}
        assert groups["link"]["label"] == "Link"
        assert groups["link"]["count"] == 4
        assert groups["storage"]["label"] == "Storage"
        assert groups["storage"]["count"] == 1
        assert groups["virtualstorage"]["count"] == 1

        # all types are shown by default
        assert all(group["hidden"] is False for group in groups.values())
        # the legend lists one row per group
        assert schematic.legend.rows_layout.count() == len(groups)

    def test_set_node_type_hidden(self, qtbot, init_window) -> None:
        """
        Tests that hiding a node type hides all the nodes of that type and the
        edges connecting them, and that the configuration is stored via QSettings.
        """
        window, schematic, _ = init_window

        schematic.set_node_type_hidden("link", True)
        for node in schematic.node_items.values():
            assert node.isVisible() is (node.model_node.type != "link")
        for item in schematic.items():
            if isinstance(item, Edge):
                # all edges in this model connect at least one "link" node
                assert item.isVisible() is False

        assert window.editor_settings.hidden_node_types == ["link"]

        # show the nodes again
        schematic.set_node_type_hidden("link", False)
        for node in schematic.node_items.values():
            assert node.isVisible() is True
        for item in schematic.items():
            if isinstance(item, Edge):
                assert item.isVisible() is True

        assert window.editor_settings.hidden_node_types == []

    def test_hidden_node_types_restored_on_init(self, qtbot, init_window) -> None:
        """
        Tests that node types hidden in a previous session are hidden again when the
        schematic is redrawn.
        """
        window, schematic, _ = init_window
        schematic.set_node_type_hidden("link", True)

        # reload mimics what happens when any node is added, deleted or edited
        schematic.reload()
        for node in schematic.node_items.values():
            assert node.isVisible() is (node.model_node.type != "link")

    def test_legend_checkbox_hides_node_type(self, qtbot, init_window) -> None:
        """
        Tests that unchecking a legend row's checkbox hides all the nodes of that
        type.
        """
        window, schematic, _ = init_window
        groups = {
            group["type"]: i for i, group in enumerate(schematic.node_type_groups())
        }
        row = schematic.legend.rows_layout.itemAt(groups["link"]).widget()
        checkbox = row.findChild(QCheckBox)
        assert checkbox.isChecked() is True

        qtbot.mouseClick(checkbox, Qt.MouseButton.LeftButton)
        assert checkbox.isChecked() is False
        assert "link" in schematic.hidden_node_types
        for node in schematic.node_items.values():
            if node.model_node.type == "link":
                assert node.isVisible() is False

    def test_toggle_legend_button(self, qtbot, init_window) -> None:
        """
        Tests that the "Hide legend" toolbar button shows and hides the legend
        widget and that the configuration is stored via QSettings.
        """
        window, schematic, display_panel = init_window
        button = display_panel.buttons[window.app_actions.get("toggle-legend").text()]

        assert schematic.legend.isHidden() is False

        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
        assert button.isChecked() is True
        assert schematic.legend.isHidden() is True
        assert window.editor_settings.are_legend_hidden is True

        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
        assert button.isChecked() is False
        assert schematic.legend.isHidden() is False
        assert window.editor_settings.are_legend_hidden is False
