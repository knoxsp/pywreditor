import math
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsSceneContextMenuEvent,
    QGraphicsSceneMouseEvent,
)

from pywr_editor.style import Color

if TYPE_CHECKING:
    from pywr_editor.schematic import Schematic, SchematicNode

FOOTPRINT_Z_VALUE = -60.0
""" Above the map tiles (about -100), below the GIS layers and the nodes """
MAX_RING_VERTICES = 150
""" The maximum number of vertices drawn for each polygon ring. Footprints are only
illustrations of the area a node represents, so large polygons are thinned out to
keep the map responsive """


class FootprintItem(QGraphicsPathItem):
    """
    The polygon of a node. It is a map item, not a schematic item, but clicking it
    acts on its node: it selects it, opens its context menu and shows its data.
    """

    def __init__(self, path: QPainterPath, node: "SchematicNode"):
        """
        Initialises the item.
        :param path: The polygon path in scene coordinates.
        :param node: The node the polygon belongs to.
        """
        super().__init__(path)
        self.node = node
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

    def contextMenuEvent(self, event: QGraphicsSceneContextMenuEvent) -> None:
        self.node.contextMenuEvent(event)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        self.node.on_show_node_data()
        event.accept()

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        # handled by the schematic, which selects the node
        event.ignore()


class NodeFootprints:
    """
    Draws the polygon stored as the geographic position of a node (a GeoJSON
    "Polygon") on the map, tinted with the colour of the node. The node itself is
    placed at the centroid of the polygon. The footprints are only illustrations:
    they are cosmetic items with a simplified outline and cannot be selected.
    """

    def __init__(self, schematic: "Schematic"):
        """
        Initialises the class.
        :param schematic: The schematic.
        """
        self.schematic = schematic
        self.items: dict[str, FootprintItem] = {}

    @staticmethod
    def thin(ring: list[list[float]]) -> list[list[float]]:
        """
        Reduces the number of vertices of a ring by keeping evenly spaced vertices.
        :param ring: The ring.
        :return: The ring with at most MAX_RING_VERTICES vertices.
        """
        if len(ring) <= MAX_RING_VERTICES:
            return ring
        step = math.ceil(len(ring) / MAX_RING_VERTICES)
        return ring[::step]

    def refresh(self) -> None:
        """
        Draws all the footprints again. Nothing is drawn outside the geographic view.
        :return: None
        """
        self.clear()
        if not self.schematic.editor_settings.is_geo_view_enabled:
            return
        for name in self.schematic.node_items:
            self.update(name)

    def update(self, name: str) -> None:
        """
        Draws, or redraws, the footprint of a node.
        :param name: The node name.
        :return: None
        """
        old = self.items.pop(name, None)
        if old is not None and old.scene() is not None:
            old.scene().removeItem(old)

        node = self.schematic.node_items.get(name)
        if node is None or not self.schematic.editor_settings.is_geo_view_enabled:
            return
        rings = node.model_node.geographic_rings
        if len(rings) == 0:
            return

        projector = self.schematic.geo_projector
        transform = self.schematic.geo_transform
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        for ring in rings:
            ring = self.thin(ring)
            try:
                merc_x, merc_y = projector.lonlat_to_merc_many(
                    [v[0] for v in ring], [v[1] for v in ring]
                )
            except Exception:
                continue
            points = [
                transform.merc_to_scene(x, y)
                for x, y in zip(merc_x, merc_y)
                if math.isfinite(x) and math.isfinite(y)
            ]
            if len(points) < 3:
                continue
            path.moveTo(*points[0])
            for point in points[1:]:
                path.lineTo(*point)
            path.closeSubpath()
        if path.isEmpty():
            return

        color_name = node.style_color or "gray"
        pen = QPen(Color(color_name, 500).qcolor)
        pen.setWidthF(1.5)
        pen.setCosmetic(True)
        fill = QColor(Color(color_name, 300).qcolor)
        fill.setAlpha(80)
        item = FootprintItem(path, node)
        item.setPen(pen)
        item.setBrush(fill)
        item.setZValue(FOOTPRINT_Z_VALUE)
        item.setVisible(node.isVisible())
        self.schematic.scene.addItem(item)
        self.items[name] = item

    def sync_visibility(self) -> None:
        """
        Hides the footprints of the hidden nodes.
        :return: None
        """
        for name, item in self.items.items():
            node = self.schematic.node_items.get(name)
            item.setVisible(node is not None and node.isVisible())

    def clear(self) -> None:
        """
        Removes the footprints from the scene. This must be called before the scene
        is cleared, as the scene deletes its items.
        :return: None
        """
        for item in self.items.values():
            if item.scene() is not None:
                item.scene().removeItem(item)
        self.items = {}
