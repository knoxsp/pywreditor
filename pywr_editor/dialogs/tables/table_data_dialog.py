from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.widgets import DataGridModel, DataGridView, PushIconButton

"""
 A modal dialog to edit the content of a CSV table in an Excel-style grid. Data can
 be pasted from Excel and every change can be undone with Ctrl+Z. The file is only
 written when the user clicks on the "Save" button.
"""


class TableDataDialog(QDialog):
    def __init__(
        self,
        table_name: str,
        file: Path,
        sep: str = ",",
        parent: QWidget | None = None,
    ):
        """
        Initialises the dialog.
        :param table_name: The table name.
        :param file: The CSV path. If the file does not exist, an empty table is
        shown and the file is created on save.
        :param sep: The CSV separator.
        :param parent: The parent widget.
        """
        super().__init__(parent)
        self.file = Path(file)
        self.sep = sep
        self.saved = False

        self.grid = (
            DataGridModel.from_csv(self.file, sep)
            if self.file.exists()
            else DataGridModel()
        )
        # start from a grid to paste into when there is no data
        if not self.grid.headers:
            self.grid = DataGridModel.blank()
        self.view = DataGridView(self.grid, self)
        self.grid.changed.connect(self.update_title)

        hint = QLabel(
            "Paste data copied from Excel with Ctrl+V (or right-click > Paste with "
            "header row). Double-click a column header to rename it. Ctrl+Z undoes "
            "the last change."
        )
        hint.setWordWrap(True)
        self.path_label = QLabel(f"File: {self.file}")
        # confirms that the file was written (the title only loses its asterisk)
        self.status_label = QLabel("")
        self.status_label.setObjectName("status_label")

        paste_button = PushIconButton(icon="msc.clippy", label="Paste")
        paste_button.setObjectName("paste_button")
        paste_button.clicked.connect(lambda: self.view.paste())
        paste_header_button = PushIconButton(
            icon="msc.clippy", label="Paste with header row"
        )
        paste_header_button.setObjectName("paste_header_button")
        paste_header_button.clicked.connect(lambda: self.view.paste(True))

        save_button = PushIconButton(icon="msc.save", label="Save", accent=True)
        save_button.setObjectName("save_button")
        save_button.clicked.connect(self.on_save)
        close_button = PushIconButton(icon="msc.close", label="Close")
        close_button.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addWidget(paste_button)
        buttons.addWidget(paste_header_button)
        buttons.addStretch()
        buttons.addWidget(save_button)
        buttons.addWidget(close_button)

        # Return in the grid must never trigger a button
        for push_button in (
            paste_button,
            paste_header_button,
            save_button,
            close_button,
        ):
            push_button.setAutoDefault(False)
            push_button.setDefault(False)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.path_label)
        layout.addWidget(self.view)
        layout.addWidget(self.status_label)
        layout.addLayout(buttons)

        self.table_name = table_name
        self.setMinimumSize(900, 600)
        self.update_title()
        self.view.setFocus()
        self.view.setCurrentIndex(self.grid.index(0, 0))

    def update_title(self) -> None:
        mark = "" if self.grid.undo_stack.isClean() else " *"
        self.setWindowTitle(f"Table data: {self.table_name}{mark}")

    @Slot()
    def on_save(self) -> None:
        """
        Writes the CSV file.
        :return: None
        """
        if self.grid.is_blank():
            QMessageBox.warning(self, "Warning", "The table is empty")
            self.status_label.setText("Nothing saved: the table is empty")
            return
        try:
            self.grid.to_csv(self.file, self.sep)
        except OSError as error:
            QMessageBox.critical(self, "Error", f"Cannot save the file: {error}")
            self.status_label.setText(f"Not saved: {error}")
            return
        self.saved = True
        self.update_title()
        headers, rows = self.grid.trimmed()
        self.status_label.setText(
            f"Saved {len(rows)} rows x {len(headers)} columns to {self.file.name} "
            f"at {datetime.now():%H:%M:%S}"
        )

    def reject(self) -> None:
        """
        Closes the dialog (Close button, Esc and the window close button all end
        here, because QDialog.closeEvent calls reject), unless the user cancels the
        prompt about unsaved changes.
        :return: None
        """
        if self.grid.undo_stack.isClean():
            return super().reject()

        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            "The table has unsaved changes. Do you want to save them?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return
        if answer == QMessageBox.StandardButton.Save:
            self.on_save()
            # the save failed or was refused: do not lose the changes
            if not self.grid.undo_stack.isClean():
                return
        super().reject()
