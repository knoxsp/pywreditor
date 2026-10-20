from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.utils import Settings
from pywr_editor.widgets import PushIconButton

from .interpreter import check_interpreter, resolve_interpreter


class ConsoleEnvironmentDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None):
        """
        Initialises the dialog to choose the Python interpreter running the console.
        :param settings: The editor settings.
        :param parent: The parent widget.
        """
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Console environment")
        self.setMinimumWidth(560)

        description = QLabel(
            "The console runs in the Python environment of the editor by default. "
            "To use another environment, select its Python interpreter (for "
            "example <i>venv/bin/python</i>). The environment must have the "
            "<i>ipykernel</i>, <i>pywr</i> and <i>pandas</i> packages installed. "
            "The kernel is restarted when the environment is changed."
        )
        description.setWordWrap(True)

        self.path = QLineEdit(settings.console_python)
        self.path.setPlaceholderText("Editor's Python environment")
        browse = PushIconButton(icon="msc.folder-opened", label="Browse", small=True)
        # noinspection PyUnresolvedReferences
        browse.clicked.connect(self.on_browse)
        default = PushIconButton(icon="msc.discard", label="Use default", small=True)
        # noinspection PyUnresolvedReferences
        default.clicked.connect(self.path.clear)
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        row.addWidget(default)

        save = PushIconButton(icon="msc.save", label="Save", accent=True)
        # noinspection PyUnresolvedReferences
        save.clicked.connect(self.on_save)
        cancel = PushIconButton(icon="msc.close", label="Cancel")
        # noinspection PyUnresolvedReferences
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(save)
        buttons.addWidget(cancel)

        layout = QVBoxLayout(self)
        title = QLabel("Console environment")
        title.setStyleSheet("font-size: 18px;")
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(row)
        layout.addLayout(buttons)

    @Slot()
    def on_browse(self) -> None:
        file, _ = QFileDialog.getOpenFileName(
            self, "Select the Python interpreter", self.path.text()
        )
        if file:
            self.path.setText(file)

    @Slot()
    def on_save(self) -> None:
        """
        Checks the interpreter and saves it.
        :return: None
        """
        python = resolve_interpreter(self.path.text())
        error = check_interpreter(python)
        if error:
            answer = QMessageBox.warning(
                self,
                "Unsuitable environment",
                f"{error}\n\nSave it anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.settings.save_console_python(self.path.text())
        self.accept()
