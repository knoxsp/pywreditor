from typing import Tuple

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGraphicsItem

from pywr_editor import MainWindow
from pywr_editor.schematic import Edge, Schematic, SchematicNode
from pywr_editor.toolbar.tab_panel import TabPanel
from tests.utils import close_message_box, resolve_model_path


class TestGeoViewToggle:
    model_file = resolve_model_path("model_geographic_positions.json")

    @pytest.fixture
    def init_window(self) -> Tuple[MainWindow, Schematic, TabPanel]:
        """
        Initialises the window.
        :return: A tuple with the window, schematic and display panel instances.
        """
        QTimer.singleShot(100, close_message_box)
        window = MainWindow(self.model_file)
        window.hide()
        schematic = window.schematic
        display_panel = window.toolbar.tabs["Schematic"].panels["Display"]

        return window, schematic, display_panel

    @staticmethod
    def node(schematic: Schematic, name: str) -> SchematicNode:
        """
        Returns the SchematicNode instance by name.
        """
        return schematic.node_items[name]

    def test_toggle_geo_view(self, qtbot, init_window):
        """
        Tests that enabling the geographic view plots the nodes with a geographic
        position by that position, hides nodes without one (showing the warning
        banner), hides edges connected to a hidden node, persists the setting, and
        that toggling back restores the schematic view.
        """
        window, schematic, display_panel = init_window
        button = display_panel.buttons[window.app_actions.get("toggle-geo-view").text()]

        assert window.editor_settings.is_geo_view_enabled is False
        assert schematic.geo_view_banner.isHidden() is True

        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

        assert button.isChecked() is True
        assert window.editor_settings.is_geo_view_enabled is True

        # nodes with a geographic position are visible and plotted by it
        reservoir = self.node(schematic, "Reservoir")
        link1 = self.node(schematic, "Link1")
        link2 = self.node(schematic, "Link2")

        assert reservoir.isVisible() is True
        assert link1.isVisible() is True
        assert reservoir.pos().toTuple() == tuple(
            schematic.to_geo_px([-0.448083, 51.6217])
        )
        assert link1.pos().toTuple() == tuple(schematic.to_geo_px([-1.5, 52.1]))

        # Link2 has no geographic position: it is hidden and the banner is shown
        assert link2.isVisible() is False
        assert schematic.geo_view_banner.isHidden() is False
        assert "1 node hidden" in schematic.geo_view_banner.text()

        # the edge to the hidden node is hidden too, the other edge is visible
        edges = [item for item in schematic.items() if isinstance(item, Edge)]
        for edge in edges:
            if edge.target.name == "Link2" or edge.source.name == "Link2":
                assert edge.isVisible() is False
            else:
                assert edge.isVisible() is True

        # dragging is disabled while the geographic view is active
        assert bool(reservoir.flags() & QGraphicsItem.ItemIsMovable) is False

        # toggle back to the schematic view
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

        assert button.isChecked() is False
        assert window.editor_settings.is_geo_view_enabled is False
        assert schematic.geo_view_banner.isHidden() is True

        reservoir = self.node(schematic, "Reservoir")
        link2 = self.node(schematic, "Link2")
        assert reservoir.isVisible() is True
        assert link2.isVisible() is True
        assert reservoir.pos().toTuple() == (200, 500)
        assert bool(reservoir.flags() & QGraphicsItem.ItemIsMovable) is True
