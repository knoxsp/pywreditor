from typing import TYPE_CHECKING, TypedDict

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.node_shapes import get_node_icon, get_pixmap_from_type
from pywr_editor.style import Color, stylesheet_dict_to_str

if TYPE_CHECKING:
    from .schematic import Schematic


class NodeTypeGroup(TypedDict):
    type: str
    """ the node type key (the pywr node "type" property) """
    label: str
    """ the user-friendly name to show next to the icon """
    pixmap: QPixmap
    """ the node icon, rendered as a pixmap """
    count: int
    """ the number of nodes of this type on the schematic """
    hidden: bool
    """ whether the nodes of this type are currently hidden """


class SchematicLegend(QFrame):
    icon_size = QSize(20, 20)
    """ the size of the node icons shown in the legend """
    max_height = 220
    """ the maximum height of the legend before it starts scrolling """

    def __init__(self, schematic: "Schematic"):
        """
        Initialises the legend.
        :param schematic: The Schematic instance the legend belongs to.
        """
        super().__init__(schematic)
        self.schematic = schematic
        self.setObjectName("schematic-legend")

        title = QLabel("Legend")
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)

        self.rows_layout = QVBoxLayout()
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(1)

        rows_container = QWidget()
        rows_container.setLayout(self.rows_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(rows_container)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setMaximumHeight(self.max_height)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setStyleSheet("background: transparent; border: none")
        rows_container.setStyleSheet("background: transparent")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(title)
        layout.addWidget(self.scroll_area)

        self.setStyleSheet(self.stylesheet)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        # hidden until refresh() finds at least one node type to show
        self.hide()

    def refresh(self) -> None:
        """
        Rebuilds the legend rows from the node types currently on the schematic.
        :return: None
        """
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        groups = self.schematic.node_type_groups()
        for group in groups:
            self.rows_layout.addWidget(self._build_row(group))

        self.setVisible(
            len(groups) > 0 and not self.schematic.editor_settings.are_legend_hidden
        )

    def _build_row(self, group: NodeTypeGroup) -> QWidget:
        """
        Builds a single legend row for a node type group.
        :param group: The node type group to build the row for.
        :return: The row widget.
        """
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(2, 2, 2, 2)
        row_layout.setSpacing(6)

        icon_label = QLabel()
        icon_label.setPixmap(group["pixmap"])
        icon_label.setFixedSize(self.icon_size)
        icon_label.setScaledContents(True)

        text_label = QLabel(f"{group['label']} ({group['count']})")

        checkbox = QCheckBox()
        checkbox.setChecked(not group["hidden"])
        checkbox.setToolTip(f"Show or hide all '{group['label']}' nodes")
        # noinspection PyUnresolvedReferences
        checkbox.toggled.connect(
            lambda checked, node_type=group["type"]: (
                self.schematic.set_node_type_hidden(node_type, not checked)
            )
        )

        row_layout.addWidget(icon_label)
        row_layout.addWidget(text_label, 1)
        row_layout.addWidget(checkbox)

        return row

    def toggle(self) -> None:
        """
        Shows or hides the legend.
        :return: None
        """
        hide = not self.schematic.editor_settings.are_legend_hidden
        self.schematic.editor_settings.save_hide_legend(hide)
        self.refresh()

    @staticmethod
    def pixmap_for_node_type(model_node) -> QPixmap:
        """
        Renders the icon for the provided node configuration as a pixmap.
        :param model_node: The NodeConfig instance.
        :return: The pixmap.
        """
        icon_class = get_node_icon(model_node)
        pixmap, _ = get_pixmap_from_type(SchematicLegend.icon_size, icon_class)
        return pixmap

    @property
    def stylesheet(self) -> str:
        """
        Returns the widget stylesheet as string.
        :return: The style sheet.
        """
        background = Color("gray", 50)
        return stylesheet_dict_to_str(
            {
                "#schematic-legend": {
                    "background-color": f"rgba{str(background.rgba(.85))}",
                    "border": f"1px solid {Color('gray', 300).hex}",
                    "border-radius": "4px",
                },
            }
        )
