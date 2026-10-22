from typing import Any

import PySide6
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from pywr_editor.model import GisLayerConfig, ModelConfig


class GisLayersListModel(QAbstractListModel):
    visibility_changed = Signal(str, bool)
    """ Signal emitted when the user shows or hides a layer from the list. The
    arguments are the layer ID and whether the layer is now visible """

    def __init__(self, model_config: ModelConfig):
        """
        Initialises the model. The layers are listed like in a GIS application, with
        the layer that is drawn on top first, while the model lists the layer that
        is drawn at the bottom first.
        :param model_config: The ModelConfig instance.
        """
        super().__init__()
        self.model_config = model_config
        self.layer_ids: list[str] = []
        self.reload()

    def reload(self) -> None:
        """
        Reads the layers again from the model.
        :return: None
        """
        self.beginResetModel()
        self.layer_ids = [
            layer.id for layer in reversed(self.model_config.gis_layers.get_all())
        ]
        self.endResetModel()

    def layer(self, index: QModelIndex | int) -> GisLayerConfig | None:
        """
        Returns the layer in a row.
        :param index: The model index or the row.
        :return: The layer or None if the row does not exist.
        """
        row = index.row() if isinstance(index, QModelIndex) else index
        if not 0 <= row < len(self.layer_ids):
            return None
        return self.model_config.gis_layers.find(self.layer_ids[row])

    def row_of(self, layer_id: str) -> int | None:
        """
        Returns the row of a layer.
        :param layer_id: The layer ID.
        :return: The row or None if the layer is not in the list.
        """
        return self.layer_ids.index(layer_id) if layer_id in self.layer_ids else None

    @staticmethod
    def swatch(layer: GisLayerConfig) -> QIcon:
        """
        Draws a small icon with the colours of the layer.
        :param layer: The layer.
        :return: The icon.
        """
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # the layer fill can be translucent: show it on white
        painter.setBrush(QColor("white"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(1, 1, 14, 14, 3, 3)
        painter.setBrush(layer.fill_color)
        painter.setPen(layer.stroke_color)
        painter.drawRoundedRect(1, 1, 14, 14, 3, 3)
        painter.end()
        return QIcon(pixmap)

    def data(
        self,
        index: PySide6.QtCore.QModelIndex | PySide6.QtCore.QPersistentModelIndex,
        role: int = ...,
    ) -> Any:
        """
        Handles the data.
        :param index: The item index.
        :param role: The item role.
        :return: The item data.
        """
        layer = self.layer(index)
        if layer is None:
            return None

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return layer.name
        if role == Qt.ItemDataRole.CheckStateRole:
            return Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DecorationRole:
            return self.swatch(layer)
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{layer.path} ({layer.file_type})"
        if role == Qt.ItemDataRole.UserRole:
            return layer.id
        return None

    def setData(
        self,
        index: PySide6.QtCore.QModelIndex | PySide6.QtCore.QPersistentModelIndex,
        value: Any,
        role: int = ...,
    ) -> bool:
        """
        Shows or hides a layer when its check box is clicked.
        :param index: The item index.
        :param value: The new value.
        :param role: The item role.
        :return: True if the data was set.
        """
        layer = self.layer(index)
        if layer is None or role != Qt.ItemDataRole.CheckStateRole:
            return False

        visible = Qt.CheckState(value) == Qt.CheckState.Checked
        self.model_config.gis_layers.set_visible(layer.id, visible)
        self.dataChanged.emit(index, index, [role])
        self.visibility_changed.emit(layer.id, visible)
        return True

    def rowCount(
        self,
        parent: PySide6.QtCore.QModelIndex | PySide6.QtCore.QPersistentModelIndex = ...,
    ) -> int:
        """
        Provides the total number of rows.
        :param parent: The parent.
        :return: The row count.
        """
        return 0 if parent is not ... and parent.isValid() else len(self.layer_ids)

    def flags(
        self,
        index: PySide6.QtCore.QModelIndex | PySide6.QtCore.QPersistentModelIndex,
    ) -> PySide6.QtCore.Qt.ItemFlag:
        """
        Handles the item flags.
        :param index: The item index.
        :return: The item flags.
        """
        return (
            Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsUserCheckable
        )
