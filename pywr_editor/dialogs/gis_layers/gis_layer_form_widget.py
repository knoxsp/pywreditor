from typing import Callable

from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.form.form import FormTitle
from pywr_editor.model import GisLayerConfig, ModelConfig
from pywr_editor.schematic.map import GisLayerInfo, is_valid_crs
from pywr_editor.style import Color
from pywr_editor.widgets import DoubleSpinBox, PushIconButton

FILE_FILTER = (
    "GIS files (*.geojson *.json *.shp);;GeoJSON (*.geojson *.json);;"
    "Shapefile (*.shp)"
)
""" The filter of the file picker """


def color_to_list(color: QColor, alpha: bool) -> list[int]:
    """
    Converts a colour to the list of values stored in the model.
    :param color: The colour.
    :param alpha: Whether to store the opacity.
    :return: The RGB or RGBA values (0-255).
    """
    values = list(color.toTuple())
    return values if alpha else values[:3]


class ColorButton(QPushButton):
    color_changed = Signal(QColor)
    """ Signal emitted when the user selects a colour """

    def __init__(self, title: str, alpha: bool = False, parent: QWidget = None):
        """
        Initialises a button that shows a colour and opens the colour picker.
        :param title: The title of the colour picker.
        :param alpha: Whether the user can change the opacity.
        :param parent: The parent widget.
        """
        super().__init__(parent)
        self.title = title
        self.alpha = alpha
        self.color = QColor("black")
        self.setFixedWidth(90)
        self.clicked.connect(self.pick)

    def set_color(self, color: QColor) -> None:
        """
        Sets the colour shown by the button.
        :param color: The colour.
        :return: None
        """
        self.color = color
        r, g, b, a = color.toTuple()
        self.setStyleSheet(
            f"background: rgba({r}, {g}, {b}, {a}); "
            f"border: 1px solid {Color('gray', 400).hex}; padding: 6px;"
        )
        self.setToolTip(
            color.name(
                QColor.NameFormat.HexArgb if self.alpha else QColor.NameFormat.HexRgb
            )
        )

    @Slot()
    def pick(self) -> None:
        """
        Opens the colour picker.
        :return: None
        """
        options = (
            QColorDialog.ColorDialogOption.ShowAlphaChannel
            if self.alpha
            else QColorDialog.ColorDialogOption()
        )
        color = QColorDialog.getColor(self.color, self, self.title, options)
        if color.isValid():
            self.set_color(color)
            self.color_changed.emit(color)


class GisLayerFormWidget(QWidget):
    changed = Signal(str, str)
    """ Signal emitted when a layer property was changed. The arguments are the layer ID
    and the property name """

    def __init__(
        self,
        model_config: ModelConfig,
        layer_info: Callable[[GisLayerConfig], GisLayerInfo],
        parent: QWidget = None,
    ):
        """
        Initialises the form to edit the selected layer. Changes are stored in the
        model straight away.
        :param model_config: The ModelConfig instance.
        :param layer_info: A function that loads a layer and returns the outcome.
        :param parent: The parent widget.
        """
        super().__init__(parent)
        self.model_config = model_config
        self.layer_info = layer_info
        self.layer_id: str | None = None
        self._loading = False

        self.title = FormTitle("GIS layer")
        self.name_field = QLineEdit()
        self.name_field.setPlaceholderText("Name of the layer")
        self.name_field.editingFinished.connect(self.on_name_changed)

        self.path_field = QLineEdit()
        self.path_field.setReadOnly(True)
        self.browse_button = PushIconButton(icon="msc.folder-opened", label="Browse")
        self.browse_button.clicked.connect(self.on_browse)
        path_layout = QHBoxLayout()
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.addWidget(self.path_field)
        path_layout.addWidget(self.browse_button)

        self.visible_field = QCheckBox("Show the layer on the schematic")
        self.visible_field.toggled.connect(self.on_visible_changed)

        self.stroke_button = ColorButton("Stroke colour")
        self.stroke_button.color_changed.connect(self.on_stroke_color_changed)
        self.fill_button = ColorButton("Fill colour", alpha=True)
        self.fill_button.color_changed.connect(self.on_fill_color_changed)
        self.width_field = DoubleSpinBox(0.1, 20, precision=1)
        self.width_field.setSingleStep(0.5)
        self.width_field.setFixedWidth(90)
        self.width_field.valueChanged.connect(self.on_width_changed)

        self.crs_field = QLineEdit()
        self.crs_field.setPlaceholderText("Automatic (from the file)")
        self.crs_field.editingFinished.connect(self.on_crs_changed)
        self.crs_message = QLabel()
        self.crs_message.setWordWrap(True)
        self.crs_message.hide()

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setOpenExternalLinks(False)

        form = QFormLayout()
        form.setLabelAlignment(form.labelAlignment())
        form.addRow("Name", self.name_field)
        form.addRow("File", path_layout)
        form.addRow("", self.visible_field)
        form.addRow("Outline colour", self.stroke_button)
        form.addRow("Fill colour", self.fill_button)
        form.addRow("Outline width", self.width_field)
        form.addRow("File CRS", self.crs_field)
        form.addRow("", self.crs_message)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addLayout(form)
        layout.addWidget(self.status)
        layout.addStretch()

        self.set_layer(None)

    def set_layer(self, layer_id: str | None) -> None:
        """
        Shows a layer in the form.
        :param layer_id: The layer ID or None to disable the form.
        :return: None
        """
        self.layer_id = layer_id
        layer = (
            self.model_config.gis_layers.find(layer_id)
            if layer_id is not None
            else None
        )
        self.setEnabled(layer is not None)
        self._loading = True
        try:
            if layer is None:
                self.title.setText("GIS layers")
                self.status.setText(
                    "Select a layer on the list or add a GeoJSON or Shapefile. The "
                    "layers are shown on the schematic in the geographic view. The "
                    "layers at the top of the list are drawn on top."
                )
                self.name_field.clear()
                self.path_field.clear()
                self.crs_field.clear()
                self.crs_message.hide()
                return

            self.title.setText(layer.name)
            self.name_field.setText(layer.layer_dict.get("name") or "")
            self.name_field.setPlaceholderText(layer.name)
            self.path_field.setText(layer.path)
            self.visible_field.setChecked(layer.visible)
            self.stroke_button.set_color(layer.stroke_color)
            self.fill_button.set_color(layer.fill_color)
            self.width_field.setValue(float(layer.stroke_width))
            self.crs_field.setText(layer.crs or "")
            self.crs_message.hide()
            self.update_status()
        finally:
            self._loading = False

    def update_status(self) -> None:
        """
        Shows the outcome of reading the layer file: the number of features, the CRS
        and the problems.
        :return: None
        """
        layer = self.model_config.gis_layers.find(self.layer_id)
        if layer is None:
            return

        info = self.layer_info(layer)
        error_color = Color("red", 700).hex
        warning_color = Color("amber", 700).hex
        if info.error is not None:
            self.status.setText(
                f'<span style="color:{error_color}">{info.error}</span>'
            )
            return

        data = info.data
        source = {
            "layer": "set above",
            "file": "from the file",
            "default": "assumed",
        }[data.crs_source]
        lines = [
            f"{data.feature_count:,} feature(s), {data.vertex_count:,} vertices. "
            f"CRS: {data.crs} ({source})."
        ]
        lines += [
            f'<span style="color:{warning_color}">{warning}</span>'
            for warning in data.warnings
        ]
        self.status.setText("<br>".join(lines))

    def set_property(self, key: str, value) -> None:
        """
        Stores a layer property in the model and notifies the change.
        :param key: The property name.
        :param value: The new value. None removes the property.
        :return: None
        """
        if self._loading or self.layer_id is None:
            return
        self.model_config.gis_layers.set_property(self.layer_id, key, value)
        self.changed.emit(self.layer_id, key)

    @Slot()
    def on_name_changed(self) -> None:
        name = self.name_field.text().strip()
        self.set_property("name", name if len(name) > 0 else None)
        layer = self.model_config.gis_layers.find(self.layer_id or "")
        if layer is not None:
            self.title.setText(layer.name)
            self.name_field.setPlaceholderText(layer.name)

    @Slot()
    def on_browse(self) -> None:
        layer = self.model_config.gis_layers.find(self.layer_id or "")
        if layer is None:
            return
        start = self.model_config.normalize_file_path(layer.path) or ""
        file, _ = QFileDialog.getOpenFileName(
            self, "Select a GIS file", start, FILE_FILTER
        )
        if len(file) == 0:
            return

        self.set_property("path", self.model_config.path_to_relative(file))
        self.path_field.setText(self.model_config.path_to_relative(file))
        self.update_status()

    @Slot(bool)
    def on_visible_changed(self, visible: bool) -> None:
        self.set_property("visible", visible)

    @Slot(QColor)
    def on_stroke_color_changed(self, color: QColor) -> None:
        self.set_property("stroke_color", color_to_list(color, alpha=False))

    @Slot(QColor)
    def on_fill_color_changed(self, color: QColor) -> None:
        self.set_property("fill_color", color_to_list(color, alpha=True))

    @Slot(float)
    def on_width_changed(self, width: float) -> None:
        self.set_property("stroke_width", width)

    @Slot()
    def on_crs_changed(self) -> None:
        if self._loading:
            return
        crs = self.crs_field.text().strip()
        if len(crs) > 0 and not is_valid_crs(crs):
            self.crs_message.setText(
                f'<span style="color:{Color("red", 700).hex}">"{crs}" is not a '
                "valid CRS. Use, for example, an EPSG code like EPSG:27700.</span>"
            )
            self.crs_message.show()
            return

        self.crs_message.hide()
        self.set_property("crs", crs if len(crs) > 0 else None)
        self.update_status()
