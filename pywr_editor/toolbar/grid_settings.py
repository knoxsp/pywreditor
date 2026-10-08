from typing import TYPE_CHECKING

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from pywr_editor.widgets import SpinBox, ToggleSwitchWidget

if TYPE_CHECKING:
    from pywr_editor import MainWindow


class GridSettings(QWidget):
    def __init__(self, parent: "MainWindow"):
        """
        Initialises the widget with the schematic grid settings (grid visibility,
        snap-to-grid and grid size).
        :param parent: The main window.
        """
        super().__init__(parent)
        self.app = parent
        editor_settings = parent.editor_settings

        main_layout = QGridLayout()
        main_layout.setRowMinimumHeight(0, 40)

        main_layout.addWidget(QLabel("Show grid"), 0, 0)
        show_grid = ToggleSwitchWidget()
        show_grid.setToolTip("Show or hide the grid on the schematic background")
        show_grid.setChecked(editor_settings.is_grid_shown)
        # noinspection PyUnresolvedReferences
        show_grid.toggled.connect(self.on_show_grid_changed)
        main_layout.addWidget(show_grid, 0, 1)

        main_layout.addWidget(QLabel("Snap to grid"), 1, 0)
        snap_to_grid = ToggleSwitchWidget()
        snap_to_grid.setToolTip(
            "Snap nodes to the nearest grid point when moving them on the schematic"
        )
        snap_to_grid.setChecked(editor_settings.is_snap_to_grid_enabled)
        # noinspection PyUnresolvedReferences
        snap_to_grid.toggled.connect(editor_settings.save_snap_to_grid)
        main_layout.addWidget(snap_to_grid, 1, 1)

        main_layout.addWidget(QLabel("Grid size"), 2, 0)
        grid_size = SpinBox()
        grid_size.setRange(5, 500)
        grid_size.setSuffix(" px")
        grid_size.setToolTip("The spacing, in pixels, between the grid lines")
        grid_size.setValue(editor_settings.grid_size)
        # noinspection PyUnresolvedReferences
        grid_size.valueChanged.connect(self.on_grid_size_changed)
        main_layout.addWidget(grid_size, 2, 1)

        self.setLayout(main_layout)

    @Slot(bool)
    def on_show_grid_changed(self, checked: bool) -> None:
        """
        Updates the grid visibility on the schematic when the toggle changes.
        :param checked: Whether the grid should be shown.
        :return: None
        """
        self.app.schematic.set_grid_visible(checked)

    @Slot(int)
    def on_grid_size_changed(self, size: int) -> None:
        """
        Updates the schematic grid size when the spin box value changes.
        :param size: The new grid size, in pixels.
        :return: None
        """
        self.app.schematic.set_grid_size(size)
