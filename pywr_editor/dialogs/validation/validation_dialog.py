import copy
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHeaderView,
    QAbstractItemView,
)

from pywr_editor.model import (
    Diagnostic,
    PreflightWorker,
    validate_model,
    validate_schema,
)
from pywr_editor.model.validation import schema_info
from pywr_editor.utils import Logging

if TYPE_CHECKING:
    from pywr_editor import MainWindow

"""
 Dialog listing the problems found by the model validation and running the
 preflight check, which loads the model using pywr.
"""

SEVERITY_LABELS = {"error": "Error", "warning": "Warning"}


class SchemaWorker(QObject):
    finished = Signal(list)
    """ Signal emitted with the schema diagnostics """

    def __init__(self, model_dict: dict):
        """
        Initialises the worker. Validating the schema takes a few seconds with a
        large model.
        :param model_dict: A copy of the model dictionary.
        """
        super().__init__()
        self.model_dict = model_dict

    @Slot()
    def run(self) -> None:
        # noinspection PyUnresolvedReferences
        self.finished.emit(validate_schema(self.model_dict))


class ValidationDialog(QDialog):
    component_requested = Signal(str, str)
    """ Signal emitted with the component kind and name when a row is activated """

    def __init__(self, parent: "MainWindow"):
        """
        Initialises the dialog.
        :param parent: The main window.
        """
        super().__init__(parent)
        self.app = parent
        self.model_config = parent.model_config
        self.logger = Logging().logger(self.__class__.__name__)
        self.model_diagnostics: list[Diagnostic] = []
        self.schema_diagnostics: list[Diagnostic] = []
        self.thread: QThread | None = None
        self.worker: PreflightWorker | None = None
        self.schema_thread: QThread | None = None
        self.schema_worker: SchemaWorker | None = None

        self.setWindowTitle("Model validation")
        self.setMinimumSize(760, 480)

        self.summary = QLabel()
        self.summary.setWordWrap(True)

        self.show_warnings = QCheckBox("Show warnings")
        self.show_warnings.setChecked(True)
        self.show_warnings.toggled.connect(self.populate)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Severity", "Message", "Location"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellActivated.connect(self.on_row_activated)
        self.table.cellDoubleClicked.connect(self.on_row_activated)

        info = schema_info()
        note = QLabel(
            "The structure is checked against the pywr-v1-schema "
            f"{info['pywr_v1_schema_version']} (for pywr {info['target_pywr_version']}) "
            "and by the editor. These checks do not guarantee that the model solves "
            "at every time-step. Double-click a row to go to the component."
        )
        note.setWordWrap(True)
        note.setEnabled(False)

        self.preflight_output = QPlainTextEdit()
        self.preflight_output.setReadOnly(True)
        self.preflight_output.setMaximumHeight(160)
        self.preflight_output.hide()

        self.validate_button = QPushButton("Validate again")
        self.validate_button.clicked.connect(self.validate)
        self.preflight_button = QPushButton("Check with Pywr")
        self.preflight_button.setToolTip(
            "Load and set up the model with pywr, using the Python paths, imports\n"
            "and solver of a run, without stepping it"
        )
        self.preflight_button.clicked.connect(self.run_preflight)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.addWidget(self.show_warnings)
        buttons.addStretch()
        buttons.addWidget(self.validate_button)
        buttons.addWidget(self.preflight_button)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.preflight_output)
        layout.addWidget(note)
        layout.addLayout(buttons)

        self.validate()

    @property
    def diagnostics(self) -> list[Diagnostic]:
        """
        The schema and model diagnostics, with the errors first.
        """
        return sorted(
            self.schema_diagnostics + self.model_diagnostics,
            key=lambda d: d.severity != "error",
        )

    @property
    def is_validating(self) -> bool:
        return self.schema_thread is not None

    @Slot()
    def validate(self) -> None:
        """
        Runs the validation and shows the diagnostics. The editor checks are shown
        straight away and the schema ones when the worker is done.
        :return: None
        """
        if self.is_validating:
            return
        self.model_diagnostics = validate_model(self.model_config)
        self.schema_diagnostics = []
        self.populate()

        self.schema_worker = SchemaWorker(copy.deepcopy(self.model_config.clean_json))
        self.schema_thread = QThread(self)
        self.schema_worker.moveToThread(self.schema_thread)
        # noinspection PyUnresolvedReferences
        self.schema_thread.started.connect(self.schema_worker.run)
        self.schema_worker.finished.connect(self.on_schema_validated)
        self.validate_button.setDisabled(True)
        self.summary.setText("Checking the model against the schema...")
        self.schema_thread.start()

    @Slot(list)
    def on_schema_validated(self, diagnostics: list[Diagnostic]) -> None:
        """
        Adds the schema diagnostics.
        :param diagnostics: The schema diagnostics.
        :return: None
        """
        self.schema_thread.quit()
        self.schema_thread.wait()
        self.schema_thread = None
        self.schema_worker = None
        self.schema_diagnostics = diagnostics
        self.validate_button.setDisabled(False)
        self.populate()

    @property
    def error_count(self) -> int:
        return sum(d.severity == "error" for d in self.diagnostics)

    @property
    def warning_count(self) -> int:
        return len(self.diagnostics) - self.error_count

    @Slot()
    def populate(self) -> None:
        """
        Fills the table and the summary.
        :return: None
        """
        if self.is_validating:
            # the summary is updated when the schema diagnostics are available
            pass
        elif not self.diagnostics:
            self.summary.setText("No problems were found.")
        else:
            self.summary.setText(
                f"{self.error_count} error(s) and {self.warning_count} warning(s) "
                "were found."
            )

        shown = [
            d
            for d in self.diagnostics
            if d.severity == "error" or self.show_warnings.isChecked()
        ]
        self.table.setRowCount(len(shown))
        for row, diagnostic in enumerate(shown):
            severity = QTableWidgetItem(SEVERITY_LABELS[diagnostic.severity])
            # keep the diagnostic with the row, which changes with the filter
            severity.setData(Qt.ItemDataRole.UserRole, diagnostic.component)
            self.table.setItem(row, 0, severity)
            self.table.setItem(row, 1, QTableWidgetItem(diagnostic.message))
            self.table.setItem(row, 2, QTableWidgetItem(diagnostic.path_str))
        self.table.resizeRowsToContents()

    @Slot(int, int)
    def on_row_activated(self, row: int, column: int) -> None:
        """
        Asks to show the component of the diagnostic.
        :param row: The row.
        :param column: The column.
        :return: None
        """
        component = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if component:
            # noinspection PyUnresolvedReferences
            self.component_requested.emit(*component)

    @property
    def is_checking(self) -> bool:
        return self.thread is not None

    @Slot()
    def run_preflight(self) -> None:
        """
        Loads and sets up the model with pywr in a thread.
        :return: None
        """
        if self.is_checking:
            return
        settings = self.app.editor_settings
        self.worker = PreflightWorker(
            model_dict=self.model_config.clean_json,
            model_file=self.model_config.json_file,
            python_paths=settings.python_paths,
            python_modules=settings.python_modules,
            solver=settings.solver,
        )
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        # noinspection PyUnresolvedReferences
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_preflight_finished)

        self.preflight_button.setDisabled(True)
        self.close_button.setDisabled(True)
        self.preflight_output.show()
        self.preflight_output.setPlainText("Loading the model with pywr...")
        self.thread.start()

    @Slot(object, float)
    def on_preflight_finished(self, error: str | None, elapsed: float) -> None:
        """
        Shows the result of the check.
        :param error: The traceback or None if the model loaded.
        :param elapsed: The elapsed seconds.
        :return: None
        """
        self.thread.quit()
        self.thread.wait()
        self.thread = None
        self.worker = None
        self.preflight_button.setDisabled(False)
        self.close_button.setDisabled(False)

        if error is None:
            self.preflight_output.setPlainText(
                f"Pywr loaded and set up the model in {elapsed:.1f} s. This does not "
                "guarantee that every time-step solves."
            )
        else:
            self.preflight_output.setPlainText(error)

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Prevents closing while pywr is loading the model.
        :param event: The event.
        :return: None
        """
        if self.is_checking or self.is_validating:
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self) -> None:
        if not (self.is_checking or self.is_validating):
            super().reject()
