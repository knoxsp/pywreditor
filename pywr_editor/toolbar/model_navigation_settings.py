from typing import TYPE_CHECKING

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from pywr_editor.widgets import ComboBox, ToggleSwitchWidget

if TYPE_CHECKING:
    from pywr_editor import MainWindow


class ModelNavigationSettings(QWidget):
    def __init__(self, parent: "MainWindow"):
        """
        Initialises the widget with the model-navigation settings (schematic
        scroll-wheel zoom direction and legend position).
        :param parent: The main window.
        """
        super().__init__(parent)
        self.app = parent
        editor_settings = parent.editor_settings

        main_layout = QGridLayout()
        main_layout.setRowMinimumHeight(0, 40)

        main_layout.addWidget(QLabel("Reverse zoom direction"), 0, 0)
        reverse_zoom = ToggleSwitchWidget()
        reverse_zoom.setToolTip(
            "Reverse the scroll-wheel direction used to zoom in and out "
            "on the schematic"
        )
        reverse_zoom.setChecked(editor_settings.is_zoom_reversed)
        # noinspection PyUnresolvedReferences
        reverse_zoom.toggled.connect(editor_settings.save_reverse_zoom)
        main_layout.addWidget(reverse_zoom, 0, 1)

        main_layout.addWidget(QLabel("Legend position"), 1, 0)
        legend_position = ComboBox()
        legend_position.addItems(["Left", "Right"])
        legend_position.setToolTip(
            "Show the schematic legend on the left or right side of the view"
        )
        legend_position.setCurrentText(
            "Right" if editor_settings.legend_position == "right" else "Left"
        )
        # noinspection PyUnresolvedReferences
        legend_position.currentTextChanged.connect(self.on_legend_position_changed)
        main_layout.addWidget(legend_position, 1, 1)

        self.setLayout(main_layout)

    @Slot(str)
    def on_legend_position_changed(self, text: str) -> None:
        """
        Updates the schematic legend position when the combo box value changes.
        :param text: The new combo box value ("Left" or "Right").
        :return: None
        """
        self.app.schematic.set_legend_position(text.lower())
