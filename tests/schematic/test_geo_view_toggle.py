import copy
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
        position by that position, places nodes without one at a default location
        (showing the warning banner), persists the setting, and that toggling back
        restores the schematic view.
        """
        window, schematic, display_panel = init_window
        initial_json = copy.deepcopy(window.model_config.json)
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

        # Link2 has no geographic position: it is shown at a default location
        # (the centre of the view), the banner warns about it and nothing is saved
        assert link2.isVisible() is True
        assert link2.pos().toTuple() == pytest.approx(
            schematic.geo_transform.centre_scene
        )
        assert schematic.geo_view_banner.isHidden() is False
        assert "1 node has no geographic position" in schematic.geo_view_banner.text()
        assert (
            window.model_config.nodes.config("Link2", as_dict=False).geographic_position
            is None
        )
        assert window.model_config.json == initial_json

        # all the edges are visible
        edges = [item for item in schematic.items() if isinstance(item, Edge)]
        assert len(edges) == 2
        assert all(edge.isVisible() for edge in edges)

        # nodes can be moved in the geographic view
        assert bool(reservoir.flags() & QGraphicsItem.ItemIsMovable) is True

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
