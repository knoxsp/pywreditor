from typing import Tuple

import pytest
from PySide6.QtCore import QPoint, Qt

from pywr_editor import MainWindow
from pywr_editor.schematic import Schematic, SchematicNode
from pywr_editor.utils import Settings
from tests.utils import resolve_model_path


class TestSchematicNodeInteraction:
    model_file = resolve_model_path("model_delete_nodes.json")
    node_name = "Link3"

    @pytest.fixture
    def init_window(self) -> Tuple[MainWindow, Schematic]:
        """
        Initialises the window. The editor settings (schematic centre, zoom,
        hidden labels, etc.) are reset first, since they are persisted via
        QSettings across test runs and the tests rely on a known starting state.
        :return: A tuple with the window and schematic instances.
        """
        editor_settings = Settings(self.model_file)
        editor_settings.instance.clear()
        editor_settings.instance.sync()

        window = MainWindow(self.model_file)
        window.hide()
        schematic = window.schematic

        return window, schematic

    @staticmethod
    def symbol_view_point(schematic: Schematic, node: SchematicNode) -> QPoint:
        """
        Returns a point, in viewport coordinates, that lies on the node symbol.
        :return: The point.
        """
        return schematic.mapFromScene(node.scenePos())

    @staticmethod
    def label_view_point(schematic: Schematic, node: SchematicNode) -> QPoint:
        """
        Returns a point, in viewport coordinates, that lies on the node label only
        (and not on the node symbol).
        :return: The point.
        """
        label_centre = node.label.mapRectToParent(node.label.boundingRect()).center()
        return schematic.mapFromScene(node.mapToScene(label_centre))

    def test_label_excluded_from_hit_area(self, qtbot, init_window) -> None:
        """
        Tests that the label never contributes to the node's hit area (shape),
        regardless of whether it is shown, so that it is never clickable itself -
        only the bounding box (used for painting/the selection outline) grows
        while it is visible.
        """
        _, schematic = init_window
        node = schematic.node_items[self.node_name]
        symbol_rect = node.node.mapRectToParent(node.node.boundingRect())

        # label is visible by default: the bounding box includes it, but the shape
        # (hit area) never does
        assert node.label.isVisible() is True
        assert node.boundingRect().height() > symbol_rect.height()
        assert node.shape().boundingRect() == symbol_rect

        label_centre_scene = node.mapToScene(
            node.label.mapRectToParent(node.label.boundingRect()).center()
        )
        assert node.contains(node.mapFromScene(label_centre_scene)) is False

        # hide the label and check that the bounding box shrinks back to the symbol
        schematic.toggle_labels()
        assert node.label.isVisible() is False
        assert node.shape().boundingRect() == symbol_rect

        # restore the label so it does not affect the other tests (settings are
        # persisted via QSettings and shared across tests using this model file)
        schematic.toggle_labels()

    def test_click_on_label_pans_and_does_not_select_node(
        self, qtbot, init_window
    ) -> None:
        """
        Tests that clicking and dragging over a visible label does not select or
        move the node (the label is not interactive - it only pans the schematic).
        """
        window, schematic = init_window
        node = schematic.node_items[self.node_name]
        prev_pos = node.scenePos()

        start = self.label_view_point(schematic, node)
        end = start + QPoint(40, 15)

        qtbot.mousePress(schematic.viewport(), Qt.LeftButton, Qt.NoModifier, start)
        qtbot.mouseMove(schematic.viewport(), end)
        qtbot.mouseRelease(schematic.viewport(), Qt.LeftButton, Qt.NoModifier, end)

        assert node.isSelected() is False
        assert node.scenePos() == prev_pos
        assert window.undo_stack.count() == 0

    def test_quick_click_on_unselected_node_selects_it(
        self, qtbot, init_window
    ) -> None:
        """
        Tests that a quick click (no drag) on an unselected node symbol selects it,
        without moving it.
        """
        window, schematic = init_window
        node = schematic.node_items[self.node_name]
        prev_pos = node.scenePos()
        point = self.symbol_view_point(schematic, node)

        qtbot.mouseClick(schematic.viewport(), Qt.LeftButton, Qt.NoModifier, point)

        assert node.isSelected() is True
        assert node.scenePos() == prev_pos
        assert window.undo_stack.count() == 0

    def test_drag_on_unselected_node_pans_and_does_not_select_or_move_it(
        self, qtbot, init_window
    ) -> None:
        """
        Tests that pressing on an unselected node and dragging pans the schematic
        instead of selecting/moving the node - dragging over dense or overlapping
        nodes should not accidentally select or move one of them.
        """
        window, schematic = init_window
        node = schematic.node_items[self.node_name]
        prev_pos = node.scenePos()

        start = self.symbol_view_point(schematic, node)
        end = start + QPoint(60, 40)

        qtbot.mousePress(schematic.viewport(), Qt.LeftButton, Qt.NoModifier, start)
        qtbot.mouseMove(schematic.viewport(), end)
        qtbot.mouseRelease(schematic.viewport(), Qt.LeftButton, Qt.NoModifier, end)

        assert node.isSelected() is False
        assert node.scenePos() == prev_pos
        assert window.undo_stack.count() == 0

    def test_drag_on_selected_node_moves_it(self, qtbot, init_window) -> None:
        """
        Tests that, once a node is selected, a further press and drag on it moves
        it (handled natively, since a selected node is movable).
        """
        window, schematic = init_window
        node = schematic.node_items[self.node_name]
        prev_pos = node.scenePos()

        point = self.symbol_view_point(schematic, node)
        qtbot.mouseClick(schematic.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        assert node.isSelected() is True

        start = point
        end = start + QPoint(60, 40)
        qtbot.mousePress(schematic.viewport(), Qt.LeftButton, Qt.NoModifier, start)
        qtbot.mouseMove(schematic.viewport(), end)
        qtbot.mouseRelease(schematic.viewport(), Qt.LeftButton, Qt.NoModifier, end)

        assert node.isSelected() is True
        assert node.scenePos() != prev_pos
        assert window.undo_stack.count() == 1
