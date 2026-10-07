from typing import Tuple

import pytest
from PySide6.QtCore import QRectF, QTimer
from PySide6.QtGui import QImage, QPainter

from pywr_editor import MainWindow
from pywr_editor.schematic import Edge, Schematic, SchematicNode
from pywr_editor.style import Color, Theme
from tests.utils import close_message_box, resolve_model_path


class TestSchematicTheme:
    model_file = resolve_model_path("model_1.json")

    @pytest.fixture
    def init_window(self) -> Tuple[MainWindow, Schematic]:
        """
        Initialises the window and restores the light theme afterwards.
        :return: A tuple with the window and schematic instances.
        """
        QTimer.singleShot(100, close_message_box)
        window = MainWindow(self.model_file)
        window.hide()
        yield window, window.schematic
        Theme.apply_mode("light")

    @staticmethod
    def canvas_pixel(schematic: Schematic) -> tuple[int, int, int]:
        """
        Renders the scene and returns the colour of a pixel inside the canvas.
        :param schematic: The schematic.
        :return: The RGB colour.
        """
        image = QImage(4, 4, QImage.Format.Format_RGB32)
        painter = QPainter(image)
        schematic.scene.render(
            painter, target=QRectF(0, 0, 4, 4), source=QRectF(30, 3, 4, 4)
        )
        painter.end()
        return image.pixelColor(2, 2).toTuple()[0:3]

    def test_canvas_and_background(self, qtbot, init_window):
        """
        Checks that the canvas and the scene background follow the theme.
        """
        window, schematic = init_window
        light_background = schematic.scene.backgroundBrush().color().name()
        light_canvas = self.canvas_pixel(schematic)

        Theme.apply_mode("dark")
        assert schematic.scene.backgroundBrush().color().name() != light_background
        assert self.canvas_pixel(schematic) != light_canvas

        Theme.apply_mode("light")
        assert schematic.scene.backgroundBrush().color().name() == light_background
        assert self.canvas_pixel(schematic) == light_canvas

    def test_user_colors_unchanged(self, qtbot, init_window):
        """
        Checks that the colours set in the model are not changed by the theme.
        """
        window, schematic = init_window
        edge = next(i for i in schematic.items() if isinstance(i, Edge))
        edge.custom_edge_color = Color("red", 500, themed=False).qcolor
        shape_items = [i for i in schematic.shape_items.values() if hasattr(i, "pen")]

        Theme.apply_mode("dark")
        assert edge.edge_color.name() == Color("red", 500, themed=False).hex
        for item in shape_items:
            if "border_color" in item.shape_obj.shape_dict:
                assert item.pen.color() == item.shape_obj.border_color

        # the default edge colour is themed
        edge.custom_edge_color = None
        dark_default = edge.edge_color.name()
        Theme.apply_mode("light")
        assert edge.edge_color.name() != dark_default

    def test_node_colors(self, qtbot, init_window):
        """
        Checks that the default node colours follow the theme.
        """
        window, schematic = init_window
        node = next(i for i in schematic.items() if isinstance(i, SchematicNode))
        light_fill = node.node.fill.hex
        label = node.label.toHtml()
        Theme.apply_mode("dark")
        assert node.node.fill.hex != light_fill
        assert node.label.toHtml() != label

    def test_export_is_always_light(self, init_window, tmp_path, monkeypatch):
        window, schematic = init_window
        window.show()
        Theme.apply_mode("dark")
        file = tmp_path / "export.png"
        monkeypatch.setattr(
            "pywr_editor.schematic.schematic.QFileDialog.getSaveFileName",
            lambda *args, **kwargs: (str(file), ""),
        )

        schematic.export_current_view()

        # the theme is restored after the export
        assert Theme.is_dark()
        image = QImage(str(file))
        assert not image.isNull()
        # the canvas is white and not the dark base colour
        colours = {
            image.pixelColor(x, y).name()
            for x in range(0, image.width(), 20)
            for y in range(0, image.height(), 20)
        }
        assert "#ffffff" in colours
        assert Theme.tokens["base"][1].lower() not in colours
