import qtawesome as qta
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.style import Theme

from .json_diff import JsonDiffEditor
from .json_editor import JsonEditor


class JsonCodeViewer(QDialog):
    def __init__(
        self,
        parent: QMainWindow,
        file_content: str | dict,
        compare_with: dict[str, dict | str] | None = None,
    ):
        """
        Initialises the JSON code reader.
        :param parent: The parent window.
        :param file_content: The JSON document.
        :param compare_with: The documents the model can be compared with, by name
        (for example the last saved version). When given, the viewer has a "Diff" tab
        showing what is different in file_content. Optional.
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
        editor = JsonEditor(file_content)
        if compare_with:
            layout.addWidget(self._tabs(editor, file_content, compare_with))
        else:
            layout.addWidget(editor)
        layout.addWidget(button_box)
        self.setLayout(layout)
        self.setWindowModality(Qt.WindowModality.WindowModal)

    def _tabs(
        self,
        editor: JsonEditor,
        file_content: str | dict,
        compare_with: dict[str, dict | str],
    ) -> QTabWidget:
        """
        Creates the tabs with the document and its differences from other versions.
        :param editor: The editor showing the document.
        :param file_content: The JSON document.
        :param compare_with: The documents to compare with, by name.
        :return: The tab widget.
        """
        self.compare_with = compare_with
        self.file_content = file_content
        self.diff_editor = JsonDiffEditor()
        self.compare_combo = QComboBox()
        self.compare_combo.addItems(list(compare_with))
        # noinspection PyUnresolvedReferences
        self.compare_combo.currentIndexChanged.connect(self.show_diff)

        header = QHBoxLayout()
        header.addWidget(QLabel("Compare the model with"))
        header.addWidget(self.compare_combo)
        header.addStretch()
        diff_widget = QWidget()
        diff_layout = QVBoxLayout(diff_widget)
        diff_layout.addLayout(header)
        diff_layout.addWidget(self.diff_editor)

        self.tabs = QTabWidget()
        self.tabs.addTab(editor, "JSON")
        self.tabs.addTab(diff_widget, "Diff")
        self.show_diff()
        return self.tabs

    @Slot()
    def show_diff(self) -> None:
        """
        Shows what is different between the document and the selected version.
        :return: None
        """
        name = self.compare_combo.currentText()
        self.diff_editor.show_diff(
            self.compare_with[name], self.file_content, name, "current model"
        )
