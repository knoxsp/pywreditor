from typing import TYPE_CHECKING

import PySide6
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from pywr_editor.style import Color

from ..base_reservoir import BaseReservoir
from ..circle import Circle

if TYPE_CHECKING:
    from pywr_editor.schematic import SchematicNode

"""
 The shapes of the node types that are new in pywr-next and have no pywr v1 equivalent.
"""


class Turbine(Circle):
    is_pywr = True

    def __init__(self, parent: "SchematicNode"):
        """
        Initialises the class for a turbine node, a circle with three blades.
        :param parent: The parent node.
        """
        super().__init__(
            parent=parent,
            fill=Color("amber", 200),
            outline=Color("amber", 600),
            label=Color("amber", 700),
        )

    def paint(
        self,
        painter: PySide6.QtGui.QPainter,
        option: PySide6.QtWidgets.QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        super().paint(painter, option, widget)
        rect = QRectF(
            -self.radius * 0.7, -self.radius * 0.7, self.radius * 1.4, self.radius * 1.4
        )
        painter.setPen(QPen(PySide6.QtCore.Qt.PenStyle.NoPen))
        painter.setBrush(self.outline.qcolor)
        for start in (90, 210, 330):
            painter.drawPie(rect, start * 16, 60 * 16)


class Abstraction(Circle):
    is_pywr = True

    def __init__(self, parent: "SchematicNode"):
        """
        Initialises the class for an abstraction node, a circle with an arrow going
        down, out of the river.
        :param parent: The parent node.
        """
        super().__init__(
            parent=parent,
            fill=Color("cyan", 200),
            outline=Color("cyan", 600),
            label=Color("cyan", 700),
        )

    def paint(
        self,
        painter: PySide6.QtGui.QPainter,
        option: PySide6.QtWidgets.QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        super().paint(painter, option, widget)
        r = self.radius
        arrow = QPainterPath()
        arrow.moveTo(QPointF(-r * 0.25, -r * 0.5))
        arrow.lineTo(QPointF(r * 0.25, -r * 0.5))
        arrow.lineTo(QPointF(r * 0.25, 0))
        arrow.lineTo(QPointF(r * 0.55, 0))
        arrow.lineTo(QPointF(0, r * 0.6))
        arrow.lineTo(QPointF(-r * 0.55, 0))
        arrow.lineTo(QPointF(-r * 0.25, 0))
        arrow.closeSubpath()
        painter.setPen(QPen(PySide6.QtCore.Qt.PenStyle.NoPen))
        painter.setBrush(QColor(self.outline.qcolor))
        painter.drawPath(arrow)


class PiecewiseStorage(BaseReservoir):
    is_pywr = True

    def __init__(self, parent: "SchematicNode"):
        """
        Initialises the class for a piecewise storage node: a storage in a different
        colour, as its volume is split in zones.
        :param parent: The parent node.
        """
        super().__init__(
            parent=parent,
            fill=Color("indigo", 200),
            outline=Color("indigo", 600),
            label=Color("indigo", 500),
        )
