import pytest
from PySide6.QtCore import QPoint

from pywr_editor import MainWindow
from pywr_editor.schematic import Schematic
from tests.utils import resolve_model_path


class TestSchematicZoom:
    model_file = resolve_model_path("model_1.json")

    @pytest.fixture
    def schematic(self) -> Schematic:
        """
        Initialises the window and returns the schematic instance.
        :return: The Schematic instance.
        """
        window = MainWindow(self.model_file)
        window.hide()
        return window.schematic

    @staticmethod
    def off_centre_anchor(schematic: Schematic) -> QPoint:
        """
        Returns a viewport point that is not the viewport centre, so that tests
        can tell apart "zoom anchored at the cursor" from "zoom anchored at the
        viewport centre".
        :param schematic: The Schematic instance.
        :return: A QPoint towards the top-left of the viewport.
        """
        rect = schematic.viewport().rect()
        return QPoint(rect.width() // 4, rect.height() // 4)

    def test_zoom_keeps_scene_point_under_anchor_fixed(self, qtbot, schematic) -> None:
        """
        Tests that, when an anchor point is given to scale_view (as wheelEvent
        does with the mouse cursor position), the scene point under that
        viewport position stays fixed on screen after zooming. This is the
        behaviour a mouse-wheel zoom must have so that the editor zooms into
        whatever is under the cursor, rather than always zooming around the
        same point (a bug caused by Qt's AlignCenter view alignment overriding
        AnchorUnderMouse whenever the scene content fits the viewport).
        """
        anchor = self.off_centre_anchor(schematic)
        scene_pos_before = schematic.mapToScene(anchor)

        schematic.scale_view(1.25, anchor=anchor)

        scene_pos_after = schematic.mapToScene(anchor)
        assert round(scene_pos_after.x(), 4) == round(scene_pos_before.x(), 4)
        assert round(scene_pos_after.y(), 4) == round(scene_pos_before.y(), 4)

    def test_zoom_without_anchor_uses_viewport_centre(self, qtbot, schematic) -> None:
        """
        Tests that, when no anchor is given (as with the toolbar zoom buttons),
        scale_view keeps the viewport-centre scene point fixed, preserving the
        previous button-zoom behaviour.
        """
        centre = schematic.viewport().rect().center()
        scene_pos_before = schematic.mapToScene(centre)

        schematic.scale_view(1.25)

        scene_pos_after = schematic.mapToScene(centre)
        assert round(scene_pos_after.x(), 4) == round(scene_pos_before.x(), 4)
        assert round(scene_pos_after.y(), 4) == round(scene_pos_before.y(), 4)

    def test_zoom_in_moves_anchor_point_towards_view_edges(
        self, qtbot, schematic
    ) -> None:
        """
        Tests that zooming in around an off-centre anchor spreads the scene
        content apart around that anchor (i.e. a point away from the anchor
        moves further from it in viewport coordinates), confirming that nodes
        actually separate on screen rather than the whole panel scaling as a
        flat image.
        """
        anchor = self.off_centre_anchor(schematic)
        far_scene_point = schematic.mapToScene(schematic.viewport().rect().topLeft())

        distance_before = (
            schematic.mapFromScene(far_scene_point) - anchor
        ).manhattanLength()

        schematic.scale_view(1.5, anchor=anchor)

        distance_after = (
            schematic.mapFromScene(far_scene_point) - anchor
        ).manhattanLength()

        assert distance_after > distance_before
