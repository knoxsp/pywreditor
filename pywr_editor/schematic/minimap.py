from typing import TYPE_CHECKING

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QFrame

from pywr_editor.style import Color

from .bbox_utils import SchematicBBoxUtils
from .edge import Edge

if TYPE_CHECKING:
    from .schematic import Schematic


class SchematicMinimap(QFrame):
    size_px = (210, 150)
    """ the width and height of the minimap """
    margin = 10
    """ the distance from the schematic border """

    def __init__(self, schematic: "Schematic"):
        """
        Initialises the minimap: a small overview of the whole schematic, drawn on
        top of the view, with a red rectangle showing the part currently visible.
        Click or drag on it to move the view.
        :param schematic: The Schematic instance the minimap belongs to.
        """
        super().__init__(schematic)
        self.schematic = schematic
        self.setObjectName("schematic-minimap")
        self.setFixedSize(*self.size_px)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Overview of the schematic. Click or drag to move the view")

        self._dirty = True
        self._nodes: list[QPointF] = []
        self._edges: list[QLineF] = []
        self._content = QRectF()
        self._extent = QRectF()
        self._scale = 1.0
        self._offset = QPointF()

        # the cached geometry is rebuilt when the scene changes; the red rectangle
        # follows the view
        schematic.scene.changed.connect(self.mark_dirty)
        schematic.horizontalScrollBar().valueChanged.connect(self.update)
        schematic.verticalScrollBar().valueChanged.connect(self.update)
        schematic.horizontalScrollBar().rangeChanged.connect(self.update)
        schematic.verticalScrollBar().rangeChanged.connect(self.update)
        self.hide()

    def mark_dirty(self, *args) -> None:
        """
        Flags that the schematic items changed, so that the geometry is rebuilt the
        next time the minimap is drawn.
        :return: None
        """
        self._dirty = True
        if self.isVisible():
            self.update()

    def refresh(self) -> None:
        """
        Shows or hides the minimap, depending on the setting and on whether there are
        nodes, and puts it in the bottom-right corner.
        :return: None
        """
        self._dirty = True
        self.setVisible(
            len(self.schematic.node_items) > 0
            and not self.schematic.editor_settings.are_minimap_hidden
        )
        self.reposition()
        self.update()

    def reposition(self) -> None:
        """
        Puts the minimap in the bottom-right corner of the view, above the map
        attribution and the legend, when they are shown on that side.
        :return: None
        """
        viewport = self.schematic.viewport()
        bottom = viewport.height() - self.margin
        attribution = getattr(self.schematic, "attribution", None)
        if attribution is not None and attribution.isVisible():
            bottom -= attribution.height()
        legend = self.schematic.legend
        if legend.isVisible() and self.schematic.editor_settings.legend_position == (
            "right"
        ):
            bottom -= legend.height() + 8
        self.move(
            viewport.width() - self.width() - self.margin,
            max(bottom - self.height(), self.margin),
        )

    # geometry ---------------------------------------------------------------------
    def _rebuild(self) -> None:
        nodes = self.schematic.node_items
        self._nodes = [
            item.sceneBoundingRect().center()
            for item in nodes.values()
            if item.isVisible()
        ]
        self._edges = [
            QLineF(
                edge.source.sceneBoundingRect().center(),
                edge.target.sceneBoundingRect().center(),
            )
            for edge in self.schematic.scene.items()
            if isinstance(edge, Edge) and edge.isVisible()
        ]
        # the scene rect is much larger than the content (to let users pan freely),
        # so the content is measured from the items
        content = QRectF()
        if nodes:
            bbox = SchematicBBoxUtils(list(nodes.values())).min_max_bounding_box_coordinates
            if bbox.min_x.value is not None:
                content = QRectF(
                    bbox.min_x.value,
                    bbox.min_y.value,
                    bbox.max_x.value - bbox.min_x.value,
                    bbox.max_y.value - bbox.min_y.value,
                )
        self._content = content
        self._dirty = False

    def view_rect(self) -> QRectF:
        """
        Returns the part of the scene shown by the view.
        :return: The rectangle, in scene coordinates.
        """
        return self.schematic.mapToScene(
            self.schematic.viewport().rect()
        ).boundingRect()

    def _fit(self, view: QRectF) -> None:
        """
        Computes how the scene is scaled in the minimap. The extent is the content
        and the current view together, so the red rectangle is always inside the
        minimap, also when the user pans away from the nodes.
        """
        extent = self._content.united(view) if not self._content.isNull() else view
        pad = max(extent.width(), extent.height()) * 0.04
        extent = extent.adjusted(-pad, -pad, pad, pad)
        inner_w = self.width() - 8
        inner_h = self.height() - 8
        self._scale = min(
            inner_w / max(extent.width(), 1e-6), inner_h / max(extent.height(), 1e-6)
        )
        self._extent = extent
        self._offset = QPointF(
            (self.width() - extent.width() * self._scale) / 2,
            (self.height() - extent.height() * self._scale) / 2,
        )

    def to_minimap(self, point: QPointF) -> QPointF:
        return QPointF(
            (point.x() - self._extent.left()) * self._scale + self._offset.x(),
            (point.y() - self._extent.top()) * self._scale + self._offset.y(),
        )

    def to_scene(self, point: QPointF) -> QPointF:
        return QPointF(
            (point.x() - self._offset.x()) / self._scale + self._extent.left(),
            (point.y() - self._offset.y()) / self._scale + self._extent.top(),
        )

    # painting -----------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        if self._dirty:
            self._rebuild()
        view = self.view_rect()
        self._fit(view)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(Color("gray", 400).hex), 1))
        painter.setBrush(QColor(255, 255, 255, 225))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)

        painter.setPen(QPen(QColor(Color("gray", 400).hex), 1))
        for line in self._edges:
            painter.drawLine(
                QLineF(self.to_minimap(line.p1()), self.to_minimap(line.p2()))
            )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(Color("teal", 600).hex))
        for point in self._nodes:
            painter.drawEllipse(self.to_minimap(point), 2.2, 2.2)

        # the current view
        top_left = self.to_minimap(view.topLeft())
        bottom_right = self.to_minimap(view.bottomRight())
        rect = QRectF(top_left, bottom_right).normalized()
        painter.setPen(QPen(QColor(220, 38, 38), 2))
        painter.setBrush(QColor(220, 38, 38, 35))
        painter.drawRect(rect)
        painter.end()

    # interaction --------------------------------------------------------------------
    def _move_view(self, event: QMouseEvent) -> None:
        if self._scale > 0:
            self.schematic.centerOn(self.to_scene(event.position()))
            self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._move_view(event)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._move_view(event)
            event.accept()

    def wheelEvent(self, event) -> None:
        # do not zoom the schematic from the minimap
        event.accept()
