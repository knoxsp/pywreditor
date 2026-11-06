import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
)

from pywr_editor.style import Theme

from .json_editor import JsonEditor


class JsonCodeViewer(QDialog):
    def __init__(self, parent: QMainWindow, file_content: str | dict):
        """
        Initialises the JSON code reader.
        :param parent: The parent window.
        :param file_content: The JSON document.
        """
        super().__init__(parent)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        # noinspection PyUnresolvedReferences
        button_box.rejected.connect(self.reject)
        # noinspection PyUnresolvedReferences
        close_button = button_box.findChild(QPushButton)
        close_button.setIcon(qta.icon("msc.close"))
        Theme.on_change(close_button, lambda w: w.setIcon(qta.icon("msc.close")))

        layout = QVBoxLayout()
        layout.addWidget(JsonEditor(file_content))
        layout.addWidget(button_box)
        self.setLayout(layout)
        self.setWindowModality(Qt.WindowModality.WindowModal)
