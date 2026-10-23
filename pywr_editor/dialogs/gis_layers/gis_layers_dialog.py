from typing import TYPE_CHECKING, Union

from PySide6.QtCore import QModelIndex, Qt, Slot
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QListView,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.model import GisLayerConfig, ModelConfig
from pywr_editor.schematic.map import GisLayerError, GisLayerInfo, GisLayerLoader
from pywr_editor.style import Color
from pywr_editor.widgets import PushIconButton

from .gis_layer_form_widget import FILE_FILTER, GisLayerFormWidget
from .gis_layers_list_model import GisLayersListModel

if TYPE_CHECKING:
    from pywr_editor import MainWindow


class GisLayersDialog(QDialog):
    def __init__(
        self,
        model_config: ModelConfig,
        parent: Union[QWindow, "MainWindow", None] = None,
    ):
        """
        Initialises the dialog to add, change, order and remove the GIS layers drawn
        on the schematic in the geographic view. Changes are applied straight away.
        :param model_config: The ModelConfig instance.
        :param parent: The parent widget. When this is the main window, the schematic
        is updated when the layers change.
        """
        super().__init__(parent)
        self.app = parent
        self.model_config = model_config

        self.list_model = GisLayersListModel(model_config)
        self.list_model.visibility_changed.connect(self.on_visibility_changed)

        self.list = QListView()
        self.list.setModel(self.list_model)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setStyleSheet(
            f"QListView {{ border: 1px solid {Color('gray', 300).hex}; "
            "border-radius: 4px; padding: 3px; }"
        )
        self.list.selectionModel().currentChanged.connect(self.on_selection_changed)

        self.add_button = PushIconButton(icon="msc.add", label="Add", accent=True)
        self.add_button.setToolTip("Add one or more GeoJSON or Shapefile files")
        self.add_button.clicked.connect(self.on_add)
        self.remove_button = PushIconButton(icon="msc.remove", label="Remove")
        self.remove_button.setToolTip("Remove the layer from the model")
        self.remove_button.clicked.connect(self.on_remove)
        self.up_button = PushIconButton(icon="msc.arrow-up", label="")
        self.up_button.setToolTip("Draw the layer above the previous one")
        self.up_button.clicked.connect(lambda: self.move_selected(1))
        self.down_button = PushIconButton(icon="msc.arrow-down", label="")
        self.down_button.setToolTip("Draw the layer below the next one")
        self.down_button.clicked.connect(lambda: self.move_selected(-1))
        self.close_button = PushIconButton(icon="msc.close", label="Close")
        self.close_button.clicked.connect(self.reject)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addStretch()
        button_layout.addWidget(self.up_button)
        button_layout.addWidget(self.down_button)

        left = QWidget()
        left.setMaximumWidth(330)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 5, 10)
        left_layout.addWidget(self.list)
        left_layout.addLayout(button_layout)

        self.form = GisLayerFormWidget(model_config, self.layer_info, self)
        self.form.changed.connect(self.on_form_changed)

        right = QVBoxLayout()
        right.addWidget(self.form)
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_layout.addWidget(self.close_button)
        right.addLayout(close_layout)

        layout = QHBoxLayout(self)
        layout.addWidget(left)
        layout.addLayout(right, 1)

        self.setWindowTitle("GIS layers")
        self.setMinimumSize(900, 560)
        self.update_buttons()
        if self.list_model.rowCount() > 0:
            self.list.setCurrentIndex(self.list_model.index(0))

    @property
    def schematic(self):
        """
        Returns the schematic to update when the layers change.
        :return: The Schematic instance or None if the dialog has no main window.
        """
        return getattr(self.app, "schematic", None)

    def layer_info(self, layer: GisLayerConfig) -> GisLayerInfo:
        """
        Loads a layer.
        :param layer: The layer.
        :return: The outcome. This is the one the schematic uses, when there is one,
        so that the file is not read twice.
        """
        if self.schematic is not None:
            return self.schematic.gis_overlay.inspect(layer)

        path = self.model_config.normalize_file_path(layer.path)
        try:
            loader = GisLayerLoader(self.model_config.geographic_crs)
            return GisLayerInfo(data=loader.load(layer, path))
        except GisLayerError as error:
            return GisLayerInfo(error=str(error))

    def selected_layer_id(self) -> str | None:
        """
        Returns the ID of the selected layer.
        :return: The layer ID or None if no layer is selected.
        """
        index = self.list.currentIndex()
        if not index.isValid():
            return None
        return self.list_model.data(index, Qt.ItemDataRole.UserRole)

    def select_layer(self, layer_id: str) -> None:
        """
        Selects a layer on the list.
        :param layer_id: The layer ID.
        :return: None
        """
        row = self.list_model.row_of(layer_id)
        if row is not None:
            self.list.setCurrentIndex(self.list_model.index(row))

    def update_buttons(self) -> None:
        """
        Enables the buttons that act on the selected layer.
        :return: None
        """
        layer_id = self.selected_layer_id()
        row = self.list_model.row_of(layer_id) if layer_id else None
        self.remove_button.setEnabled(row is not None)
        self.up_button.setEnabled(row is not None and row > 0)
        self.down_button.setEnabled(
            row is not None and row < self.list_model.rowCount() - 1
        )

    def notify_schematic(self) -> None:
        """
        Draws the layers on the schematic again.
        :return: None
        """
        if self.schematic is not None:
            self.schematic.refresh_gis_layers()

    @Slot(QModelIndex, QModelIndex)
    def on_selection_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        """
        Shows the selected layer in the form.
        :param current: The new item.
        :param previous: The previous item.
        :return: None
        """
        layer_id = (
            self.list_model.data(current, Qt.ItemDataRole.UserRole)
            if current.isValid()
            else None
        )
        self.form.set_layer(layer_id)
        self.update_buttons()

    def update_layer_row(self, layer_id: str) -> None:
        """
        Updates a layer on the list and draws the layers on the schematic again.
        :param layer_id: The layer ID.
        :return: None
        """
        row = self.list_model.row_of(layer_id)
        if row is not None:
            index = self.list_model.index(row)
            self.list_model.dataChanged.emit(index, index)
        self.notify_schematic()

    @Slot(str, bool)
    def on_visibility_changed(self, layer_id: str, visible: bool) -> None:
        """
        Updates the form and the schematic after a layer was shown or hidden from
        the list.
        :param layer_id: The layer ID.
        :param visible: Whether the layer is visible.
        :return: None
        """
        if layer_id == self.form.layer_id:
            self.form.set_layer(layer_id)
        self.notify_schematic()

    @Slot(str, str)
    def on_form_changed(self, layer_id: str, property_name: str) -> None:
        """
        Updates the list and the schematic after a layer was changed in the form.
        :param layer_id: The layer ID.
        :param property_name: The name of the changed property.
        :return: None
        """
        self.update_layer_row(layer_id)

    @Slot()
    def on_add(self) -> None:
        """
        Adds the layers selected by the user.
        :return: None
        """
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select the GIS files", "", FILE_FILTER
        )
        if len(files) == 0:
            return
        self.add_files(files)

    def add_files(self, files: list[str]) -> None:
        """
        Adds layers to the model and selects the last one.
        :param files: The paths of the GeoJSON or Shapefile files.
        :return: None
        """
        layer_id = None
        for file in files:
            layer_id = self.model_config.gis_layers.add(file)["id"]

        self.list_model.reload()
        if layer_id is not None:
            self.select_layer(layer_id)
        self.notify_schematic()
        self.update_buttons()
        self.show_message(f"Added {len(files)} GIS layer(s)")

    @Slot()
    def on_remove(self) -> None:
        """
        Removes the selected layer, after the user confirms.
        :return: None
        """
        layer_id = self.selected_layer_id()
        layer = self.model_config.gis_layers.find(layer_id) if layer_id else None
        if layer is None:
            return

        answer = QMessageBox.question(
            self,
            "Remove the layer",
            f'Do you want to remove the layer "{layer.name}" from the model? '
            "The file is not deleted.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        row = self.list_model.row_of(layer_id)
        self.model_config.gis_layers.delete(layer_id)
        self.list_model.reload()
        count = self.list_model.rowCount()
        if count > 0:
            self.list.setCurrentIndex(self.list_model.index(min(row, count - 1)))
        else:
            self.form.set_layer(None)
        self.notify_schematic()
        self.update_buttons()
        self.show_message(f'Removed the GIS layer "{layer.name}"')

    def move_selected(self, direction: int) -> None:
        """
        Moves the selected layer up or down the stack.
        :param direction: 1 to draw the layer above the next one, -1 to draw it below.
        :return: None
        """
        layer_id = self.selected_layer_id()
        if layer_id is None:
            return

        # the model lists the layer at the bottom first
        index = self.model_config.gis_layers.find_index(layer_id)
        self.model_config.gis_layers.move(layer_id, index + direction)
        self.list_model.reload()
        self.select_layer(layer_id)
        self.notify_schematic()
        self.update_buttons()

    def show_message(self, message: str) -> None:
        """
        Shows a message in the status bar of the main window.
        :param message: The message.
        :return: None
        """
        if self.app is not None and hasattr(self.app, "statusBar"):
            self.app.statusBar().showMessage(message)
