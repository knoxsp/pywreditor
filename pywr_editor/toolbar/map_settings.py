import html
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QGridLayout, QLabel, QLineEdit, QPushButton, QWidget

from pywr_editor.schematic.map import crs_name, is_valid_crs
from pywr_editor.style import Color
from pywr_editor.widgets import ToggleSwitchWidget

if TYPE_CHECKING:
    from pywr_editor import MainWindow


class MapSettings(QWidget):
    def __init__(self, parent: "MainWindow"):
        """
        Initialises the widget with the map settings: the geographic view, the
        OpenStreetMap basemap, the CRS of the nodes' geographic positions and the
        GIS layers.
        :param parent: The main window.
        """
        super().__init__(parent)
        self.app = parent
        self.schematic = parent.schematic
        self.model_config = parent.model_config

        main_layout = QGridLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setVerticalSpacing(2)
        main_layout.setHorizontalSpacing(8)

        main_layout.addWidget(QLabel("Geographic view"), 0, 0)
        self.geo_view = ToggleSwitchWidget()
        self.geo_view.setToolTip(
            "Plot the nodes by their geographic position instead of their "
            "schematic position. This is a display setting of the editor"
        )
        self.geo_view.setChecked(parent.editor_settings.is_geo_view_enabled)
        # noinspection PyUnresolvedReferences
        self.geo_view.toggled.connect(self.on_geo_view_toggled)
        main_layout.addWidget(self.geo_view, 0, 1)
        # noinspection PyUnresolvedReferences
        self.schematic.geo_view_changed.connect(self.sync_geo_view)

        main_layout.addWidget(QLabel("Show OSM basemap"), 1, 0)
        self.basemap = ToggleSwitchWidget()
        self.basemap.setToolTip(
            "Show the OpenStreetMap tiles behind the nodes. The map is only shown "
            "in the geographic view. This setting is saved in the model file"
        )
        show_basemap = self.model_config.map_config.get("show_basemap", True)
        self.basemap.setChecked(
            show_basemap if isinstance(show_basemap, bool) else True
        )
        # noinspection PyUnresolvedReferences
        self.basemap.toggled.connect(self.schematic.set_basemap_visible)
        main_layout.addWidget(self.basemap, 1, 1)

        main_layout.addWidget(QLabel("CRS"), 2, 0)
        self.crs_field = QLineEdit()
        self.crs_field.setToolTip(
            "The coordinate reference system of the nodes' geographic positions, "
            "for example EPSG:4326 or EPSG:27700. Positions are [x, y]: "
            "[longitude, latitude] for EPSG:4326 and [easting, northing] for "
            "projected systems such as EPSG:27700"
        )
        self.crs_field.setText(self.saved_crs())
        # noinspection PyUnresolvedReferences
        self.crs_field.editingFinished.connect(self.on_crs_edited)
        main_layout.addWidget(self.crs_field, 2, 1)
        # the message is long: the toolbar is short, so show it on the right and put
        # the full text in the tooltip
        self.crs_message = QLabel()
        self.crs_message.setWordWrap(True)
        self.crs_message.setFixedWidth(280)
        self.crs_message.setMaximumHeight(62)
        self.crs_message.setStyleSheet("font-size: 11px")
        main_layout.addWidget(self.crs_message, 0, 3, 3, 1, Qt.AlignmentFlag.AlignTop)

        self.layers_button = QPushButton("Manage GIS layers...")
        self.layers_button.setToolTip(
            "Add, style and order the GeoJSON and Shapefile layers shown in the "
            "geographic view"
        )
        self.layers_action = parent.app_actions.get("manage-gis-layers")
        # noinspection PyUnresolvedReferences
        self.layers_button.clicked.connect(self.layers_action.trigger)
        # noinspection PyUnresolvedReferences
        self.layers_action.changed.connect(self.on_layers_action_changed)
        main_layout.addWidget(self.layers_button, 0, 2)
        self.layers_label = QLabel()
        main_layout.addWidget(self.layers_label, 1, 2)
        # noinspection PyUnresolvedReferences
        self.schematic.gis_layers_changed.connect(self.update_layers_label)
        self.update_layers_label()
        self.update_crs_message()

        self.setLayout(main_layout)

    def saved_crs(self) -> str:
        """
        Returns the CRS stored in the model, even if it is not valid, so that the
        user can fix it.
        :return: The CRS.
        """
        crs = self.model_config.stored_geographic_crs
        return crs if isinstance(crs, str) else self.model_config.geographic_crs

    @Slot(bool)
    def on_geo_view_toggled(self, checked: bool) -> None:
        """
        Switches the schematic to or from the geographic view.
        :param checked: Whether the geographic view is enabled.
        :return: None
        """
        self.schematic.set_geo_view(checked)
        # the view is not changed if it cannot be drawn or the model is running
        self.sync_geo_view()

    @Slot()
    def sync_geo_view(self, *args) -> None:
        """
        Updates the switch with the current setting, without triggering it.
        :return: None
        """
        self.geo_view.blockSignals(True)
        self.geo_view.setChecked(self.app.editor_settings.is_geo_view_enabled)
        self.geo_view.blockSignals(False)

    @Slot()
    def on_crs_edited(self) -> None:
        """
        Validates the CRS and, if valid, saves it in the model and draws the
        schematic again.
        :return: None
        """
        text = self.crs_field.text().strip()
        if len(text) == 0:
            self.crs_field.setText(self.saved_crs())
            self.update_crs_message()
            return

        if not is_valid_crs(text):
            self.show_crs_message(
                f"'{html.escape(text)}' is not a valid CRS. Use, for example, "
                "EPSG:4326",
                Color("red", 700).hex,
            )
            return

        self.crs_field.setText(text)
        if text != self.model_config.stored_geographic_crs or (
            not self.model_config.has_valid_geographic_crs
        ):
            self.model_config.update_geographic_crs(text)
            self.schematic.on_geographic_crs_changed()
        self.update_crs_message()

    def update_crs_message(self) -> None:
        """
        Shows the name of the CRS and the warnings about the node positions.
        :return: None
        """
        if not self.model_config.has_valid_geographic_crs:
            self.show_crs_message(
                f"'{html.escape(self.saved_crs())}' is not a valid CRS, "
                f"{html.escape(self.model_config.geographic_crs)} is used",
                Color("red", 700).hex,
            )
            return

        crs = self.model_config.geographic_crs
        warnings = self.schematic.crs_warnings()
        lines = [html.escape(crs_name(crs) or crs)] + [
            html.escape(warning) for warning in warnings
        ]
        color = (
            Color("amber", 700).hex if len(warnings) > 0 else Color("neutral", 500).hex
        )
        self.show_crs_message("<br>".join(lines), color)

    def show_crs_message(self, message: str, color: str) -> None:
        """
        Shows a message below the CRS field.
        :param message: The message. This must be escaped.
        :param color: The text colour.
        :return: None
        """
        self.crs_message.setText(f'<span style="color:{color}">{message}</span>')
        self.crs_message.setToolTip(self.crs_message.text())

    @Slot()
    def on_layers_action_changed(self) -> None:
        """
        Enables the button when the action is enabled (the action is disabled while
        the model runs).
        :return: None
        """
        self.layers_button.setEnabled(self.layers_action.isEnabled())

    @Slot()
    def update_layers_label(self) -> None:
        """
        Shows the number of GIS layers and how many are shown on the schematic.
        :return: None
        """
        layers = self.model_config.gis_layers.get_all()
        if len(layers) == 0:
            self.layers_label.setText("No layers")
            return

        shown = sum(layer.visible for layer in layers)
        noun = "layer" if len(layers) == 1 else "layers"
        self.layers_label.setText(f"{len(layers)} {noun} ({shown} shown)")
