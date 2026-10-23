from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.form import FormTitle
from pywr_editor.utils import Settings
from pywr_editor.widgets import PushIconButton


class PythonPathsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None):
        """
        Initialises the dialog to add the folders and virtual environments that are
        added to the Python search path when the model is run.
        :param settings: The editor settings.
        :param parent: The parent widget.
        """
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Python paths")
        self.setMinimumWidth(560)

        description = QLabel(
            "Add the folders containing the Python packages used by custom "
            "parameters, nodes and recorders, or the root folder of a virtual "
            "environment (its site-packages folder is used). The paths are added "
            "to the Python search path when the model is run, so the PYTHONPATH "
            "environment variable is not needed. A search path only makes modules "
            "importable: add below the modules that define custom parameters, nodes "
            'and recorders (for example "parameters") so that they are imported '
            "before the model is loaded."
        )
        description.setWordWrap(True)

        self.list = QListWidget()
        self.list.addItems(settings.python_paths)

        add_button = PushIconButton(icon="msc.add", label="Add folder", small=True)
        # noinspection PyUnresolvedReferences
        add_button.clicked.connect(self.on_add)
        delete_button = PushIconButton(
            icon="msc.remove", label="Remove selected", small=True
        )
        # noinspection PyUnresolvedReferences
        delete_button.clicked.connect(self.on_delete)
        buttons = QHBoxLayout()
        buttons.addWidget(add_button)
        buttons.addWidget(delete_button)
        buttons.addStretch()

        self.modules = QListWidget()
        self.modules.addItems(settings.python_modules)
        add_module = PushIconButton(icon="msc.add", label="Add module", small=True)
        # noinspection PyUnresolvedReferences
        add_module.clicked.connect(self.on_add_module)
        delete_module = PushIconButton(
            icon="msc.remove", label="Remove selected", small=True
        )
        # noinspection PyUnresolvedReferences
        delete_module.clicked.connect(self.on_delete_module)
        module_buttons = QHBoxLayout()
        module_buttons.addWidget(add_module)
        module_buttons.addWidget(delete_module)
        module_buttons.addStretch()

        layout = QVBoxLayout(self)
        layout.addWidget(FormTitle("Python paths"))
        layout.addWidget(description)
        layout.addLayout(buttons)
        layout.addWidget(self.list)
        layout.addWidget(QLabel("Modules to import before loading the model"))
        layout.addLayout(module_buttons)
        layout.addWidget(self.modules)

    def paths(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    @Slot()
    def on_add(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select a folder or virtual environment"
        )
        if folder and folder not in self.paths():
            self.list.addItem(folder)
            self.settings.save_python_paths(self.paths())

    @Slot()
    def on_delete(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self.settings.save_python_paths(self.paths())

    def module_names(self) -> list[str]:
        return [self.modules.item(i).text() for i in range(self.modules.count())]

    @Slot()
    def on_add_module(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Add module", "Module name (for example parameters):"
        )
        name = name.strip().removesuffix(".py")
        if ok and name and name not in self.module_names():
            self.modules.addItem(name)
            self.settings.save_python_modules(self.module_names())

    @Slot()
    def on_delete_module(self) -> None:
        for item in self.modules.selectedItems():
            self.modules.takeItem(self.modules.row(item))
        self.settings.save_python_modules(self.module_names())
