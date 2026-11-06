from PySide6.QtCore import QProcess, Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.environments import (
    PYTHON_VERSION,
    PywrEnvironment,
    find_uv,
    pywr_next_environment,
)

"""
 The dialog that installs, after the user agrees, the Python environment with the
 pywr-next version the editor needs, and shows where it is.
"""

UV_URL = "https://docs.astral.sh/uv/getting-started/installation/"


class InstallEnvironmentDialog(QDialog):
    def __init__(
        self,
        environment: PywrEnvironment,
        purpose: str = "run pywr-next models",
        parent: QWidget | None = None,
        uv: str | None = None,
    ):
        """
        Initialises the dialog.
        :param environment: The environment to install or show.
        :param purpose: What the environment is needed for, to explain the request.
        :param parent: The parent widget. Optional.
        :param uv: The path to uv. Defaults to the one found by find_uv().
        """
        super().__init__(parent)
        self.environment = environment
        self.uv = uv if uv is not None else find_uv()
        self.process: QProcess | None = None
        self.commands: list[list[str]] = []

        version = environment.pywr_version
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.RichText)
        self.message.setOpenExternalLinks(True)

        location_label = QLabel("Location:")
        self.location = QLineEdit(str(environment.path))
        self.location.setReadOnly(True)
        self.location.setObjectName("environment_location")
        self.open_folder_button = QPushButton("Open folder")
        # noinspection PyUnresolvedReferences
        self.open_folder_button.clicked.connect(self.open_folder)
        location = QHBoxLayout()
        location.addWidget(location_label)
        location.addWidget(self.location, 1)
        location.addWidget(self.open_folder_button)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setObjectName("install_output")
        self.output.hide()

        self.install_button = QPushButton("Install")
        self.install_button.setDefault(True)
        # noinspection PyUnresolvedReferences
        self.install_button.clicked.connect(self.install)
        self.remove_button = QPushButton("Remove")
        # noinspection PyUnresolvedReferences
        self.remove_button.clicked.connect(self.remove)
        self.close_button = QPushButton("Cancel")
        # noinspection PyUnresolvedReferences
        self.close_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.remove_button)
        buttons.addStretch()
        buttons.addWidget(self.install_button)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.message)
        layout.addLayout(location)
        layout.addWidget(self.output, 1)
        layout.addLayout(buttons)

        self.purpose = purpose
        self.setWindowTitle(f"pywr-next {version}")
        self.setMinimumWidth(640)
        self.refresh()

    def refresh(self) -> None:
        """
        Shows whether the environment is installed and what can be done.
        :return: None
        """
        version = self.environment.pywr_version
        installed = self.environment.is_installed()
        self.open_folder_button.setEnabled(self.environment.path.exists())
        self.remove_button.setVisible(installed)
        if installed:
            info = self.environment.info() or {}
            self.message.setText(
                f"<b>pywr-next {version}</b> is installed, with Python "
                f"{info.get('python_version', PYTHON_VERSION)}, since "
                f"{info.get('installed_on', 'an unknown date')}. The editor uses it "
                "for pywr-next models."
            )
            self.install_button.hide()
            self.close_button.setText("Close")
        elif self.uv is None:
            self.message.setText(
                f"To {self.purpose}, the editor needs <b>pywr-next {version}</b>, "
                "which it installs with <i>uv</i>. uv was not found: install it "
                f'(<a href="{UV_URL}">instructions</a>) and try again.'
            )
            self.install_button.setEnabled(False)
        else:
            self.message.setText(
                f"To {self.purpose}, the editor needs <b>pywr-next {version}</b>. "
                "pywr-next cannot be installed with the pywr version the editor "
                "uses, so the editor installs it in a separate folder, with Python "
                f"{PYTHON_VERSION}. This downloads about 100 MB from the Python "
                "package index. Nothing else on your computer is changed, and the "
                "folder can be removed from this dialog at any time.<br><br>"
                "It will be installed in the folder below. Install it now?"
            )

    @Slot()
    def install(self) -> None:
        """
        Runs the installation commands one after the other.
        :return: None
        """
        if self.uv is None:
            return
        self.environment.path.parent.mkdir(parents=True, exist_ok=True)
        self.commands = self.environment.install_commands(self.uv)
        self.install_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.output.show()
        self.output.appendPlainText(f"Installing in {self.environment.path}\n")
        self.run_next_command()

    def run_next_command(self) -> None:
        if not self.commands:
            self.environment.mark_installed()
            self.output.appendPlainText(
                f"\npywr-next {self.environment.pywr_version} was installed in "
                f"{self.environment.path}"
            )
            self.close_button.setEnabled(True)
            self.refresh()
            return

        command = self.commands.pop(0)
        self.output.appendPlainText("$ " + " ".join(command))
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        # noinspection PyUnresolvedReferences
        self.process.readyReadStandardOutput.connect(self.on_output)
        # noinspection PyUnresolvedReferences
        self.process.finished.connect(self.on_finished)
        self.process.start(command[0], command[1:])

    @Slot()
    def on_output(self) -> None:
        text = bytes(self.process.readAllStandardOutput()).decode(errors="replace")
        self.output.appendPlainText(text.rstrip())

    @Slot(int, QProcess.ExitStatus)
    def on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            self.output.appendPlainText(
                f"\nThe installation failed (exit code {exit_code}). Check the "
                "internet connection and try again."
            )
            self.commands = []
            self.install_button.setEnabled(True)
            self.close_button.setEnabled(True)
            return
        self.run_next_command()

    @Slot()
    def open_folder(self) -> None:
        """
        Opens the folder of the environment in the file manager.
        :return: None
        """
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.environment.path)))

    @Slot()
    def remove(self) -> None:
        """
        Deletes the environment.
        :return: None
        """
        self.environment.remove()
        self.output.hide()
        self.install_button.show()
        self.install_button.setEnabled(self.uv is not None)
        self.close_button.setText("Cancel")
        self.refresh()


def ensure_pywr_next(
    purpose: str, parent: QWidget | None = None
) -> PywrEnvironment | None:
    """
    Returns the pywr-next environment, asking to install it when it is missing.
    :param purpose: What the environment is needed for, such as "run this model".
    :param parent: The parent widget. Optional.
    :return: The installed environment, or None if the user did not install it.
    """
    environment = pywr_next_environment()
    if environment.is_installed():
        return environment
    InstallEnvironmentDialog(environment, purpose, parent).exec()
    return environment if environment.is_installed() else None
