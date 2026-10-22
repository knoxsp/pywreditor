from typing import Tuple

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

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

    def test_single_click_follows_only_if_panel_is_visible(
        self, qtbot, init_window
    ) -> None:
        """
        Tests that selecting a node does not open the panel, but that it shows the
        node when the panel is visible.
        """
        window, schematic = init_window
        panel = window.node_data_panel

        schematic.node_items["Link"].setSelected(True)
        assert panel.isVisibleTo(window) is False
        assert panel.node_name is None

        schematic.node_items["Link"].mouseDoubleClickEvent(None)
        assert panel.isVisibleTo(window) is True
        assert panel.node_name == "Link"

        schematic.de_select_all_items()
        schematic.node_items["Reservoir"].setSelected(True)
        assert panel.node_name == "Reservoir"

        panel.hide()
        schematic.de_select_all_items()
        schematic.node_items["Link"].setSelected(True)
        assert panel.isVisibleTo(window) is False
        assert panel.node_name == "Reservoir"

    def test_panel_shows_configuration_and_saves_all_fields(
        self, qtbot, init_window
    ) -> None:
        """
        Tests that the panel shows only the configuration of the node and that
        saving it preserves the name, type, node style and edge colour.
        """
        window, schematic = init_window
        panel = window.node_data_panel
        model_config = schematic.model_config
        from pywr_editor.node_shapes import get_node_icon_classes

        style = get_node_icon_classes(include_pywr_nodes=False)[0].lower()
        link = model_config.nodes.config("Link")
        model_config.nodes.update({**link, "node_style": style, "edge_color": "red"})
        before = model_config.nodes.config("Link")
        assert before["position"]["node_style"] == style
        node = schematic.node_items["Link"]
        node.on_show_node_data()

        cost_widget = panel.form.find_field("cost").widget
        assert panel.isAncestorOf(cost_widget)
        # the name, type and style are not shown
        assert panel.form.isHidden()
        assert not panel.form.find_field("name").widget.isVisibleTo(panel)

        panel.form.find_field("comment").widget.line_edit.setPlainText("A comment")
        panel.findChild(QPushButton, "save_button").click()
        after = model_config.nodes.config("Link")
        assert after["comment"] == "A comment"
        # the type is saved in lower case
        for key in before:
            if key not in ("comment", "type"):
                assert after[key] == before[key]
        assert after["type"].lower() == before["type"].lower()

    def test_panel_can_be_docked_on_each_side(self, qtbot, init_window) -> None:
        """
        Tests that the components and node data panels take the full height of a side,
        or share it when stacked.
        """
        window, schematic = init_window
        window.resize(1400, 900)
        window.show()
        qtbot.waitExposed(window)
        panel = window.node_data_panel
        panel.show_node("Link")
        components = window.components_dock

        for area in (
            Qt.DockWidgetArea.LeftDockWidgetArea,
            Qt.DockWidgetArea.RightDockWidgetArea,
        ):
            window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, components)
            window.addDockWidget(area, panel)
            qtbot.wait(50)
            full_height = panel.height()
            assert full_height >= window.centralWidget().height()

            window.addDockWidget(area, components)
            window.splitDockWidget(panel, components, Qt.Orientation.Vertical)
            qtbot.wait(50)
            assert panel.geometry().bottom() <= components.geometry().top()
            assert panel.height() < 0.8 * full_height
            assert components.height() < 0.8 * full_height
