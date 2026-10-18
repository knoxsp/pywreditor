from typing import TYPE_CHECKING

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QWidget,
)

from pywr_editor.model.results import default_output_dir
from pywr_editor.widgets import ToggleSwitchWidget

if TYPE_CHECKING:
    from pywr_editor import MainWindow


class RunSettings(QWidget):
    def __init__(self, parent: "MainWindow"):
        """
        Initialises the widget with the settings used to run the model (the solver).
        :param parent: The main window.
        """
        super().__init__(parent)
        self.editor_settings = parent.editor_settings

        # noinspection PyUnresolvedReferences
        from pywr.solvers import solver_registry

        names = [solver.name for solver in solver_registry if solver.name != "null"]
        current = self.editor_settings.solver

        layout = QGridLayout()
        layout.setRowMinimumHeight(0, 40)
        layout.addWidget(QLabel("Solver"), 0, 0)
        self.solver = QComboBox()
        self.solver.setToolTip(
            "The Pywr solver used to run the model. This is ignored if the model "
            'file sets its own "solver" key'
        )
        self.solver.addItems(names if current in names else [current, *names])
        self.solver.setCurrentText(current)
        # noinspection PyUnresolvedReferences
        self.solver.currentTextChanged.connect(self.on_solver_changed)
        layout.addWidget(self.solver, 0, 1)

        layout.addWidget(QLabel("Save results"), 1, 0)
        self.save_results = ToggleSwitchWidget()
        self.save_results.setToolTip(
            "Save the recorders to a timestamped folder when a run ends or is stopped"
        )
        self.save_results.setChecked(self.editor_settings.are_results_saved)
        # noinspection PyUnresolvedReferences
        self.save_results.toggled.connect(self.editor_settings.save_results_enabled)
        layout.addWidget(self.save_results, 1, 1)

        layout.addWidget(QLabel("Output folder"), 2, 0)
        self.output_dir = QLineEdit(self.editor_settings.output_dir)
        self.output_dir.setPlaceholderText(
            str(default_output_dir(parent.model_config.json_file))
        )
        self.output_dir.setToolTip(
            'The folder where the results are saved, each run in a timestamped '
            'subfolder. Leave it empty to use the "outputs" folder next to the '
            "model. A relative path is relative to the model folder"
        )
        # noinspection PyUnresolvedReferences
        self.output_dir.editingFinished.connect(self.on_output_dir_edited)
        browse = QToolButton()
        browse.setText("...")
        # noinspection PyUnresolvedReferences
        browse.clicked.connect(self.on_browse)
        row = QHBoxLayout()
        row.addWidget(self.output_dir, 1)
        row.addWidget(browse)
        layout.addLayout(row, 2, 1)
        layout.setRowStretch(3, 1)
        self.setLayout(layout)

    @Slot(str)
    def on_solver_changed(self, name: str) -> None:
        self.editor_settings.save_solver(name)

    @Slot()
    def on_output_dir_edited(self) -> None:
        self.editor_settings.save_output_dir(self.output_dir.text().strip())

    @Slot()
    def on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select the output folder", self.output_dir.text()
        )
        if folder:
            self.output_dir.setText(folder)
            self.on_output_dir_edited()
