from typing import TYPE_CHECKING

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from pywr_editor.widgets import ComboBox

if TYPE_CHECKING:
    from pywr_editor import MainWindow

THEMES = {"System": "system", "Light": "light", "Dark": "dark"}


class AppearanceSettings(QWidget):
    def __init__(self, parent: "MainWindow"):
        """
        Initialises the widget to choose the theme: light, dark or the colour
        scheme of the desktop.
        :param parent: The main window.
        """
        super().__init__(parent)
        self.app = parent

        main_layout = QGridLayout()
        main_layout.setRowMinimumHeight(0, 40)
        main_layout.addWidget(QLabel("Theme"), 0, 0)

        self.theme = ComboBox()
        self.theme.addItems(list(THEMES))
        self.theme.setToolTip(
            "Use the light or dark theme, or follow the colour scheme of the desktop"
        )
        saved = parent.editor_settings.theme
        self.theme.setCurrentText(
            next(name for name, value in THEMES.items() if value == saved)
        )
        # noinspection PyUnresolvedReferences
        self.theme.currentTextChanged.connect(self.on_theme_changed)
        main_layout.addWidget(self.theme, 0, 1)

        self.setLayout(main_layout)

    @Slot(str)
    def on_theme_changed(self, text: str) -> None:
        """
        Changes the theme.
        :param text: The combo box value.
        :return: None
        """
        self.app.set_theme(THEMES[text])
