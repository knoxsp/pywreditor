from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.dialects.next import conversion
from pywr_editor.widgets import PushIconButton

if TYPE_CHECKING:
    from pywr_editor import MainWindow
    from pywr_editor.model import ModelConfig

"""
 The dialog that shows the result of the conversion of a pywr v1 model to pywr-next
 (see dialects/next/conversion.py): what was converted, what was not, and where to save
 the new model.
"""


class ConvertDialog(QDialog):
    def __init__(
        self,
        result: conversion.ConversionResult,
        v1_model: "ModelConfig",
        parent: "MainWindow | QWidget | None" = None,
    ):
        """
        Initialises the dialog.
        :param result: The result of the conversion.
        :param v1_model: The model that was converted.
        :param parent: The parent widget. Optional.
        """
        super().__init__(parent)
        self.app = parent
        self.result = result
        self.v1_model = v1_model
        self.saved_file: Path | None = None
        self.setWindowTitle("Convert to pywr-next")
        self.setMinimumSize(720, 560)

        counts = conversion.count_components(result.model)
        v1 = v1_model.json
        v1_counts = {
            "nodes": len(v1.get("nodes") or []),
            "parameters": len(v1.get("parameters") or {}),
            "tables": len(v1.get("tables") or {}),
        }
        summary = (
            f"The pywr-next model has {counts['nodes']} nodes and {counts['edges']} "
            f"edges, {counts['parameters']} parameters and {counts['tables']} tables "
            f"(the original has {v1_counts['nodes']} nodes, "
            f"{v1_counts['parameters']} parameters and {v1_counts['tables']} tables). "
            "pywr v1 recorders are not converted: pywr-next has metric sets and "
            "outputs instead."
        )
        self.summary = QLabel(summary)
        self.summary.setObjectName("summary")
        self.summary.setWordWrap(True)

        errors = result.errors
        self.errors_label = QLabel(
            f"{len(errors)} component{'s' if len(errors) != 1 else ''} could not be "
            "converted and are not in the new model:"
            if errors
            else "Everything was converted."
        )
        self.errors_label.setObjectName("errors_label")
        self.table = QTableWidget(len(errors), 4)
        self.table.setObjectName("errors_table")
        self.table.setHorizontalHeaderLabels(["Component", "Name", "Attribute", "Problem"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, error in enumerate(errors):
            for column, text in enumerate(
                (error.component, error.name or "", error.attribute or "", error.error)
            ):
                self.table.setItem(row, column, QTableWidgetItem(text))
        self.table.setVisible(bool(errors))

        default = conversion.default_file(v1_model.json_file)
        self.path = QLineEdit(str(default) if default else "")
        self.path.setObjectName("path")
        self.path.setPlaceholderText("Where to save the pywr-next model")
        browse = PushIconButton(icon="msc.folder-opened", label="Browse")
        # noinspection PyUnresolvedReferences
        browse.clicked.connect(self.browse)
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Save as"))
        path_row.addWidget(self.path, 1)
        path_row.addWidget(browse)
        self.note = QLabel(
            "The files that the model reads (tables, time series) are looked for next "
            "to the model file, so save it in the folder of the original model."
        )
        self.note.setWordWrap(True)
        self.message = QLabel()
        self.message.setObjectName("message")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #d13438")

        self.save_button = PushIconButton(icon="msc.save", label="Save")
        self.save_button.setObjectName("save_button")
        self.open_button = PushIconButton(
            icon="msc.go-to-file", label="Save and open", accent=True
        )
        self.open_button.setObjectName("open_button")
        close_button = PushIconButton(icon="msc.close", label="Close")
        # noinspection PyUnresolvedReferences
        self.save_button.clicked.connect(lambda: self.save(False))
        # noinspection PyUnresolvedReferences
        self.open_button.clicked.connect(lambda: self.save(True))
        # noinspection PyUnresolvedReferences
        close_button.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.open_button)
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.errors_label)
        layout.addWidget(self.table, 1)
        layout.addLayout(path_row)
        layout.addWidget(self.note)
        layout.addWidget(self.message)
        layout.addLayout(buttons)

    @Slot()
    def browse(self) -> None:
        start = self.path.text() or str(Path.home())
        file, _ = QFileDialog.getSaveFileName(
            self, "Save the pywr-next model", start, "JSON files (*.json)"
        )
        if file:
            self.path.setText(file)

    def target(self) -> Path | None:
        text = self.path.text().strip()
        return Path(text).expanduser() if text else None

    def save(self, open_model: bool = False) -> bool:
        """
        Saves the converted model and its editor data.
        :param open_model: Whether to open the model in a new window.
        :return: True if the model was saved.
        """
        target = self.target()
        if target is None:
            self.message.setText("Enter where to save the model")
            return False
        if target.resolve() == Path(self.v1_model.json_file or "").resolve():
            self.message.setText("This is the file of the original model")
            return False
        if target.exists():
            answer = QMessageBox.question(
                self,
                "Replace the file",
                f"{target.name} already exists. Replace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            conversion.save_converted_model(self.result.model, target)
        except OSError as error:
            self.message.setText(f"The model could not be saved: {error}")
            return False
        self.saved_file = target
        self.message.setText("")
        app = self.app
        if app is not None and hasattr(app, "statusBar"):
            app.statusBar().showMessage(f"Saved the pywr-next model in {target}")
        if open_model:
            from pywr_editor import MainWindow

            self.opened_window = MainWindow(str(target))
            self.close()
        return True


def convert_to_next(app: "MainWindow") -> ConvertDialog | None:
    """
    Converts the model of a window to pywr-next, installing pywr-next if the user
    agrees, and shows the result.
    :param app: The main window of a pywr v1 model.
    :return: The dialog with the result, None if the model was not converted.
    """
    from pywr_editor.dialogs.environments.install_dialog import ensure_pywr_next

    model = app.model_config
    environment = ensure_pywr_next("convert this model", app)
    if environment is None:
        return None
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        result = conversion.convert_model(str(environment.python), model.json)
    except RuntimeError as error:
        QApplication.restoreOverrideCursor()
        box = QMessageBox(app)
        box.setWindowTitle("Conversion failed")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("The model could not be converted.")
        box.setDetailedText(str(error))
        box.show()
        app.conversion_error_box = box
        return None
    QApplication.restoreOverrideCursor()
    dialog = ConvertDialog(result, model, app)
    dialog.setWindowModality(Qt.WindowModality.NonModal)
    dialog.show()
    return dialog
