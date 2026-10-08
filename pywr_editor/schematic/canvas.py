import PySide6
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsItem

from pywr_editor.style import Color


class SchematicCanvas(QGraphicsItem):
    def __init__(self, width: float, height: float):
        """
        Initialises the schematic canvas. This draws an outline, wrapping all the
        shapes, that marks the schematic bounds. The background fill is handled
        separately by the view (see Schematic.add_scene_decorations) so that it
        always fills the viewport instead of zooming/panning with this outline.
        :param width: The schematic width.
        :param height: THe schematic height.
        :return None
        """
        super().__init__()
        # schematic width
        self.width = width
        # schematic height
        self.height = height
        # drop shadow - this slows down painting when zoomed
        # self.setGraphicsEffect(self.shadow)
        # always draw the schematic bounds behind the nodes/edges
        self.setZValue(-1)
        # speed up rendering performance
        self.setCacheMode(QGraphicsItem.ItemCoordinateCache)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)

    def boundingRect(self):
        """
        Set the bounding box for the canvas.
        :return: None
        """
        return QRectF(0, 0, self.width, self.height)

    def paint(
        self,
        painter: PySide6.QtGui.QPainter,
        option: PySide6.QtWidgets.QStyleOptionGraphicsItem,
        widget: PySide6.QtWidgets.QWidget | None = ...,
    ) -> None:
        """
        Draws nothing: the canvas is unbounded, so there is no outline or fill to
        mark the schematic bounds. This item is kept only so that schematic.py's
        size tracking (update_size) and run-mode dimming (set_run_mode) keep
        working against a real item.
        :param painter: The painter instance.
        :param option: The option.
        :param widget: The widget.
        :return: None
        """
        pass

    @property
    def shadow(self) -> QGraphicsDropShadowEffect:
        """
        Returns the shadow effect object.
        :return: The drop shadow effect instance.
        """
        return QGraphicsDropShadowEffect(
            blurRadius=15, xOffset=3, yOffset=3, color=Color("gray", 500).qcolor
        )

    def update_size(self, width: float, height: float) -> None:
        """
        Updates the schematic size.
        :param width: THe schematic width.
        :param height: THe schematic height.
        :return: None
        """
        self.prepareGeometryChange()
        self.width = width
        self.height = height
        self.update()
