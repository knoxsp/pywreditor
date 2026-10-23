import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.model.results import resolve_output_dir
from pywr_editor.utils import Logging
from pywr_editor.widgets import PushIconButton

from .environment_dialog import ConsoleEnvironmentDialog
from .interpreter import resolve_interpreter

if TYPE_CHECKING:
    from pywr_editor import MainWindow

"""
 Dockable IPython console to interact with the model: run it, look at its
 components and read the results.

 The console runs a Jupyter kernel in a separate process, so that a long model run
 does not freeze the editor and can be interrupted. By default the kernel uses the
 Python environment of the editor, but any environment with ipykernel and Pywr can
 be chosen. When the kernel starts, kernel_startup.py loads the model currently
 open in the editor, after adding the Python paths and importing the modules set in
 the editor, and defines the names available in the console. The kernel is started
 the first time the panel is shown.
"""

STARTUP_SCRIPT = Path(__file__).with_name("kernel_startup.py")
CONFIG_ENV_VAR = "PYWR_EDITOR_CONSOLE_CONFIG"


def create_console_widget():
    """
    Creates the console widget. Imported here as qtconsole is optional.
    :return: The widget.
    """
    from qtconsole.rich_jupyter_widget import RichJupyterWidget

    class PywrConsole(RichJupyterWidget):
        kernel_ready = Signal()
        """ Emitted when the kernel has finished starting and the console is
        receiving its output """

        def _handle_kernel_info_reply(self, rep):
            super()._handle_kernel_info_reply(rep)
            self.kernel_ready.emit()

    return PywrConsole()


class ConsolePanel(QDockWidget):
    def __init__(self, parent: "MainWindow"):
        """
        Initialises the panel.
        :param parent: The main window.
        """
        super().__init__("Console", parent)
        self.app = parent
        self.logger = Logging().logger(self.__class__.__name__)
        self.setObjectName("console_panel")
        self.setMinimumHeight(120)

        self.console = None
        self.kernel_manager = None
        self.kernel_client = None
        self.has_started = False
        self.work_dir = tempfile.TemporaryDirectory(prefix="pywr_editor_console_")

        self.environment_label = QLabel()
        self.environment_label.setStyleSheet("color: gray;")
        interrupt = self.add_button("msc.debug-stop", "Interrupt", self.interrupt)
        interrupt.setToolTip("Interrupt the running command, e.g. a model run")
        reload = self.add_button("msc.refresh", "Reload model", self.reload_model)
        reload.setToolTip(
            "Load the model as currently open in the editor, including the unsaved "
            "changes, replacing the 'model' variable"
        )
        restart = self.add_button("msc.debug-restart", "Restart", self.restart)
        restart.setToolTip(
            "Restart the kernel, clearing all variables. Use it after changing the "
            "Python paths or modules"
        )
        environment = self.add_button(
            "msc.settings-gear", "Environment", self.choose_environment
        )
        environment.setToolTip("Choose the Python environment of the console")

        header = QHBoxLayout()
        header.setContentsMargins(4, 4, 4, 0)
        for button in (interrupt, reload, restart, environment):
            header.addWidget(button)
        header.addWidget(self.environment_label, 1)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addLayout(header)
        layout.addLayout(self.body, 1)
        self.setWidget(container)
        self.update_environment_label()

    def add_button(self, icon: str, label: str, slot) -> PushIconButton:
        button = PushIconButton(icon=icon, label=label, small=True)
        # noinspection PyUnresolvedReferences
        button.clicked.connect(slot)
        return button

    def update_environment_label(self) -> None:
        python = resolve_interpreter(self.app.editor_settings.console_python)
        default = " (editor)" if not self.app.editor_settings.console_python else ""
        self.environment_label.setText(f"{python}{default}")

    def showEvent(self, event: QShowEvent) -> None:
        """
        Starts the kernel the first time the panel is shown.
        :param event: The event being triggered.
        :return: None
        """
        super().showEvent(event)
        if not self.has_started:
            self.has_started = True
            self.start_kernel()

    def write_files(self) -> Path:
        """
        Writes the copy of the model currently open in the editor and the settings
        read by the startup script.
        :return: The path to the settings file.
        """
        folder = Path(self.work_dir.name)
        model_config = self.app.model_config
        settings = self.app.editor_settings
        with open(folder / "model.json", "w") as fid:
            json.dump(model_config.clean_json, fid, default=str)
        config = {
            "model_json": str(folder / "model.json"),
            "model_file": model_config.json_file,
            "python_paths": settings.python_paths,
            "python_modules": settings.python_modules,
            "solver": settings.solver,
            "output_dir": str(
                resolve_output_dir(settings.output_dir, model_config.json_file)
            ),
        }
        config_file = folder / "config.json"
        with open(config_file, "w") as fid:
            json.dump(config, fid)
        return config_file

    def start_kernel(self) -> None:
        """
        Starts the kernel and shows the console connected to it.
        :return: None
        """
        self.update_environment_label()
        try:
            from jupyter_client.kernelspec import KernelSpec
            from qtconsole.manager import QtKernelManager
        except ImportError:
            self.show_message(
                "The console needs the qtconsole and ipykernel packages. Install "
                "them in the editor's environment with:\n"
                "pip install qtconsole ipykernel"
            )
            return

        python = resolve_interpreter(self.app.editor_settings.console_python)
        config_file = self.write_files()
        model_file = self.app.model_config.json_file

        manager = QtKernelManager()
        # the kernel is started with the chosen interpreter instead of a kernelspec
        manager._kernel_spec = KernelSpec(
            argv=[python, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            display_name="Pywr",
            language="python",
        )
        try:
            manager.start_kernel(
                extra_arguments=[
                    f"--IPKernelApp.exec_files=['{STARTUP_SCRIPT.as_posix()}']"
                ],
                env={**os.environ, CONFIG_ENV_VAR: str(config_file)},
                cwd=str(Path(model_file).parent) if model_file else None,
            )
        except Exception as e:
            self.logger.debug(f"The kernel failed to start: {e}")
            self.show_message(f"The console kernel could not be started:\n{e}")
            return
        client = manager.client()
        client.start_channels()

        console = create_console_widget()
        # the startup script cannot show anything: load the model once connected
        console.kernel_ready.connect(self.reload_model)
        console.kernel_manager = manager
        console.kernel_client = client
        console.exit_requested.connect(self.restart)
        self.kernel_manager, self.kernel_client, self.console = (
            manager,
            client,
            console,
        )
        self.clear_body()
        self.body.addWidget(console)

    def show_message(self, message: str) -> None:
        self.clear_body()
        label = QLabel(message)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignTop)
        label.setMargin(8)
        self.body.addWidget(label)

    def clear_body(self) -> None:
        while self.body.count():
            widget = self.body.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()

    def stop_kernel(self) -> None:
        """
        Stops the kernel process.
        :return: None
        """
        if self.kernel_client is not None:
            self.kernel_client.stop_channels()
        if self.kernel_manager is not None:
            try:
                self.kernel_manager.shutdown_kernel(now=True)
            except Exception as e:
                self.logger.debug(f"The kernel did not shut down cleanly: {e}")
        self.kernel_client = self.kernel_manager = self.console = None

    @Slot()
    def restart(self) -> None:
        self.stop_kernel()
        self.start_kernel()

    @Slot()
    def interrupt(self) -> None:
        if self.kernel_manager is not None:
            self.kernel_manager.interrupt_kernel()

    @Slot()
    def reload_model(self) -> None:
        """
        Loads the current state of the model in the kernel.
        :return: None
        """
        if self.console is None:
            return
        self.write_files()
        self.console.execute("reload_model()")

    @Slot()
    def choose_environment(self) -> None:
        """
        Opens the dialog to choose the Python environment and restarts the kernel
        if it changes.
        :return: None
        """
        previous = self.app.editor_settings.console_python
        dialog = ConsoleEnvironmentDialog(self.app.editor_settings, parent=self)
        if dialog.exec() and self.app.editor_settings.console_python != previous:
            self.restart()

    def shutdown(self) -> None:
        """
        Stops the kernel and deletes the temporary files. Called when the editor
        closes.
        :return: None
        """
        self.stop_kernel()
        self.work_dir.cleanup()
