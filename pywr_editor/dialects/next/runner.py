import shutil
import tempfile
from collections import deque
from datetime import datetime
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal, Slot
from PySide6.QtNetwork import QLocalSocket

from pywr_editor.dialects.next import runner_protocol as protocol
from pywr_editor.model.pywr_worker import PywrProgress
from pywr_editor.model.results import TIMESTAMP_FORMAT
from pywr_editor.utils import Logging

"""
 Runs a pywr-next model, step by step, with the runner service of pywr-next (see
 runner_protocol.py). The service is started in the Python environment of pywr-next,
 in a separate process, and the worker talks to it over a local socket.

 The worker has the signals and methods of the pywr v1 worker (PywrWorker), so the
 run controls work with both: step(), run_to() and full_run() ask for a command,
 and kill() stops the run. It lives in its own thread, like the v1 worker, and
 everything it does is driven by the events of the socket and the process.
"""

CONNECT_INTERVAL_MS = 100
""" How often the worker tries to connect while the service starts """
COMMAND_RETRY_MS = 50
""" The wait before a command that the service rejected (it was still busy) is sent
again """
MAX_COMMAND_RETRIES = 100
STDERR_TAIL = 6000
""" The number of characters of the service output kept, to explain a crash """


class NextRunWorker(QObject):
    progress_update = Signal(PywrProgress)
    """ The progress after a timestep (same as the pywr v1 worker) """
    status_update = Signal(str)
    before_step = Signal()
    step_done = Signal()
    before_run_to = Signal()
    run_to_done = Signal()
    before_run = Signal()
    run_done = Signal()
    finished = Signal()
    """ The worker has finished and is not needed anymore """
    model_error = Signal(str)
    """ The model cannot be loaded or run, with an explanation """
    run_to_date_reached = Signal()
    end_date_reached = Signal()
    results_saved = Signal(str)
    results_error = Signal(str)

    _command = Signal(str)
    """ Sends a command to the worker thread: step, run_to, full_run or kill """

    def __init__(
        self,
        model_dict: dict,
        model_file: str | None,
        python: str | None,
        end_date: pd.Timestamp,
        run_to_date: pd.Timestamp,
        solver: str = protocol.DEFAULT_SOLVER,
        results_dir: str | None = None,
        server_command: list[str] | None = None,
        connect_timeout: float = 90.0,
    ):
        """
        Initialises the worker.
        :param model_dict: The model dictionary, without the editor data.
        :param model_file: The path to the model file. The files of the model are
        relative to its folder.
        :param python: The Python interpreter of the pywr-next environment that runs
        the service.
        :param end_date: The end date of the run.
        :param run_to_date: The date "Run to" runs up to.
        :param solver: The solver of the run.
        :param results_dir: The folder where the outputs of the model are saved, in a
        timestamped folder. They are written to a temporary folder, which is
        removed, if None.
        :param server_command: The command that starts the service, instead of
        running pywr-next. It receives the name of the socket as last argument. An
        empty list starts nothing: the service is started by the caller on the
        socket in socket_name. Optional, used by the tests.
        :param connect_timeout: How long to wait for the service, in seconds.
        """
        super().__init__()
        self.logger = Logging().logger(self.__class__.__name__)
        self.model_dict = model_dict
        self.model_file = model_file
        self.python = python
        self.end_date = end_date
        self.run_to_date = run_to_date
        self.solver = solver
        self.results_dir = results_dir
        self.server_command = server_command
        self.connect_timeout = connect_timeout
        self.pywr_model = None
        """ Not available: the model lives in the service. The run inspector of
        pywr v1 models cannot be used """

        self.socket_name = protocol.socket_name()
        self.state = "new"
        self.progress: protocol.Progress | None = None
        self.session: protocol.ClientSession | None = None
        self.output_dir: Path | None = None
        self._temporary_output = False
        self._pending: deque[str] = deque()
        self._current: str | None = None
        self._last_command: dict | None = None
        self._retries = 0
        self._run_to_target: datetime | None = None
        self._failed = False
        self._finishing = False
        self._end_reached_sent = False
        self._run_to_reached_sent = False
        self._service_output = ""
        self._connect_deadline = 0.0
        self.decoder = protocol.FrameDecoder()
        self.process: QProcess | None = None
        self.socket: QLocalSocket | None = None
        self.connect_timer: QTimer | None = None
        # a signal is used so that the commands of the user run in the worker thread
        self._command.connect(self._on_command)

    # ------------------------------------------------------------------ commands
    def step(self) -> None:
        """
        Runs one timestep.
        :return: None
        """
        self._command.emit("step")

    def run_to(self) -> None:
        """
        Runs the model up to the run-to date.
        :return: None
        """
        self._command.emit("run_to")

    def full_run(self) -> None:
        """
        Runs the model to the end date.
        :return: None
        """
        self._command.emit("full_run")

    def kill(self) -> None:
        """
        Stops the run. The outputs are written when the run reached its end.
        :return: None
        """
        self._command.emit("kill")

    def shutdown(self, timeout_ms: int = 10000) -> None:
        """
        Stops the service at once, without finishing the run, and waits for the
        worker thread to end. Used when the editor is closed, so that no service is
        left running.
        :param timeout_ms: How long to wait for the thread.
        :return: None
        """
        thread = self.thread()
        if thread is None or not thread.isRunning():
            return
        self._command.emit("shutdown")
        thread.wait(timeout_ms)

    @Slot(str)
    def _on_command(self, name: str) -> None:
        if name == "kill":
            self._stop_run()
        elif name == "shutdown":
            self._finish()
        elif not self._finishing:
            self._pending.append(name)
            self._dispatch()

    # ----------------------------------------------------------------- start up
    @Slot()
    def run(self) -> None:
        """
        Starts the service and the run. This is called when the thread starts.
        :return: None
        """
        try:
            self.output_dir = self._prepare_output_dir()
            self.socket = QLocalSocket(self)
            address, abstract = protocol.socket_address(self.socket_name)
            self._address = address
            if abstract:
                self.socket.setSocketOptions(
                    QLocalSocket.SocketOption.AbstractNamespaceOption
                )
            self.socket.connected.connect(self._on_connected)
            self.socket.readyRead.connect(self._on_ready_read)
            self.socket.disconnected.connect(self._on_disconnected)
            self.socket.errorOccurred.connect(self._on_socket_error)

            self.status_update.emit("Starting pywr-next")
            self._start_service()
            self.state = "connecting"
            self._connect_deadline = datetime.now().timestamp() + self.connect_timeout
            self.connect_timer = QTimer(self)
            self.connect_timer.setInterval(CONNECT_INTERVAL_MS)
            self.connect_timer.timeout.connect(self._try_connect)
            self.connect_timer.start()
        except Exception as error:
            self._fail(f"The run could not be started: {error}")

    def _prepare_output_dir(self) -> Path:
        if self.results_dir:
            base = Path(self.results_dir)
            run_dir = base / datetime.now().strftime(TIMESTAMP_FORMAT)
            suffix = 1
            while run_dir.exists():
                run_dir = base / f"{datetime.now().strftime(TIMESTAMP_FORMAT)}_{suffix}"
                suffix += 1
            run_dir.mkdir(parents=True)
            return run_dir
        self._temporary_output = True
        return Path(tempfile.mkdtemp(prefix="pywr-editor-run-"))

    def _start_service(self) -> None:
        if self.server_command == []:
            return
        if self.server_command is not None:
            command = [*self.server_command, self.socket_name]
        else:
            command = [self.python, "-c", protocol.SERVER_SNIPPET, self.socket_name]
        if command[0] is None:
            raise RuntimeError("There is no Python with pywr-next to run the model")
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUNBUFFERED", "1")
        # the logs of the service are sent as events
        self.process.setProcessEnvironment(environment)
        if self.model_file:
            self.process.setWorkingDirectory(str(Path(self.model_file).parent))
        self.process.readyReadStandardOutput.connect(self._on_service_output)
        self.process.finished.connect(self._on_service_finished)
        self.process.errorOccurred.connect(self._on_service_error)
        self.logger.debug(f"Starting the runner service: {command}")
        self.process.start(command[0], command[1:])

    @Slot()
    def _on_service_output(self) -> None:
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode(errors="replace")
        self._service_output = (self._service_output + text)[-STDERR_TAIL:]

    @Slot()
    def _on_service_error(self) -> None:
        if self.state in ("new", "connecting") and not self._finishing:
            self._fail(
                "pywr-next could not be started: "
                + self.process.errorString()
                + f"\n\nCommand: {self.process.program()}"
            )

    @Slot(int, QProcess.ExitStatus)
    def _on_service_finished(self, exit_code: int, status: QProcess.ExitStatus) -> None:
        if self._finishing:
            return
        if self.state == "closing":
            return
        self._on_service_output()
        self._fail(
            "The pywr-next runner service stopped unexpectedly "
            f"(exit code {exit_code}).\n\n{self._service_output.strip()}"
        )

    @Slot()
    def _try_connect(self) -> None:
        if self.state != "connecting" or self._finishing:
            return
        if datetime.now().timestamp() > self._connect_deadline:
            self._fail(
                "The pywr-next runner service did not start in "
                f"{self.connect_timeout:.0f} seconds.\n\n{self._service_output.strip()}"
            )
            return
        if self.socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            self.socket.connectToServer(self._address)

    @Slot()
    def _on_connected(self) -> None:
        self.connect_timer.stop()
        self.state = "handshake"
        self.status_update.emit("Connecting to pywr-next")
        capabilities = [f"solver:{self.solver}"]
        self._send_raw(protocol.encode_frame(protocol.hello(capabilities)))

    @Slot(QLocalSocket.LocalSocketError)
    def _on_socket_error(self, error) -> None:
        if self.state == "connecting" or self._finishing:
            # the service is not listening yet: try again
            return
        if error == QLocalSocket.LocalSocketError.PeerClosedError:
            self._on_disconnected()
            return
        if self.state != "closing":
            self._fail(
                f"The connection to pywr-next failed: {self.socket.errorString()}"
            )

    @Slot()
    def _on_disconnected(self) -> None:
        if self._finishing or self.state in ("closing", "connecting"):
            return
        self._on_service_output()
        self._fail(
            "pywr-next closed the connection unexpectedly.\n\n"
            + self._service_output.strip()
        )

    # -------------------------------------------------------------------- events
    @Slot()
    def _on_ready_read(self) -> None:
        if self._finishing or self.socket is None:
            return
        try:
            messages = self.decoder.push(bytes(self.socket.readAll()))
            for message in messages:
                if self._finishing:
                    break
                self._handle(message)
        except protocol.ProtocolError as error:
            self._fail(f"The runner service sent an invalid message: {error}")

    def _handle(self, message: dict) -> None:
        if self.state == "handshake":
            self._handle_handshake(message)
            return
        event = message.get("payload") or {}
        kind = event.get("type")
        payload = event.get("payload")
        handler = getattr(self, f"_on_event_{kind}", None)
        if handler is None:
            self.logger.debug(f"Ignored the runner event {kind}")
            return
        handler(payload)

    def _handle_handshake(self, message: dict) -> None:
        payload = message.get("payload") or {}
        if message.get("type") == "rejected":
            self._fail(protocol.rejection_text(payload))
            return
        if message.get("type") != "accepted":
            raise protocol.ProtocolError(f"unexpected message {message.get('type')}")
        self.session = protocol.ClientSession(payload["session_id"])
        self.logger.debug(
            f"Connected to the runner service, capabilities: "
            f"{payload.get('capabilities')}"
        )
        self.state = "initialising"
        self.status_update.emit("Loading model")
        self._send(
            protocol.initialise_command(
                run_name=Path(self.model_file).stem if self.model_file else "model",
                model=self.model_dict,
                output_path=str(self.output_dir),
                data_path=(
                    str(Path(self.model_file).parent) if self.model_file else None
                ),
                solver=self.solver,
            )
        )

    def _on_event_initialised(self, payload: dict) -> None:
        self.progress = protocol.Progress.from_message(payload["progress"])
        self.state = "ready"
        self.status_update.emit("Ready to run")
        self._dispatch()

    def _on_event_update(self, payload: dict) -> None:
        self.progress = protocol.Progress.from_message(payload["progress"])
        progress = self.progress
        if progress.completed > 0:
            date = progress.last_date or progress.next_date
            self.progress_update.emit(
                PywrProgress(
                    current_timestamp=pd.Timestamp(date),
                    current_index=progress.completed - 1,
                    last_index=max(progress.total - 1, 1),
                )
            )
        if self._current == "step":
            self._finish_command()
            self.step_done.emit()
            self._after_command()
        elif self._current == "run_to" and self._run_to_reached(progress):
            self._finish_command()
            self.run_to_done.emit()
            self._after_command()

    def _run_to_reached(self, progress: protocol.Progress) -> bool:
        target = self._run_to_target
        return (
            progress.is_finished
            or progress.next_date is None
            or (
                target is not None
                and progress.last_date is not None
                and progress.last_date >= target
            )
        )

    def _after_command(self) -> None:
        """
        Tells the run controls when the run-to date or the end date is reached, and
        sends the next command.
        :return: None
        """
        progress = self.progress
        if (
            progress
            and progress.last_date
            and not self._run_to_reached_sent
            and progress.last_date >= self.run_to_date.to_pydatetime()
        ):
            self._run_to_reached_sent = True
            self.run_to_date_reached.emit()
        if progress and progress.next_date is None and not self._end_reached_sent:
            self._end_reached_sent = True
            self.end_date_reached.emit()
        self._dispatch()

    def _on_event_state_changed(self, payload) -> None:
        self.logger.debug(f"Runner state: {payload}")

    def _on_event_log(self, payload: dict) -> None:
        record = payload.get("record") or {}
        level = {"debug": 10, "info": 20, "warn": 30, "error": 40}.get(
            record.get("level"), 20
        )
        self.logger.log(level, record.get("message", ""))

    def _on_event_command_rejected(self, payload: dict) -> None:
        # the service had not finished the previous command yet: send it again
        self.logger.debug(f"Command rejected: {payload}")
        if self._last_command is None or self._retries >= MAX_COMMAND_RETRIES:
            self._fail(
                f"The runner service rejected the command {payload.get('command')} "
                f"while it was {payload.get('status')}"
            )
            return
        self._retries += 1
        command = self._last_command
        QTimer.singleShot(COMMAND_RETRY_MS, lambda: self._resend(command))

    def _resend(self, command: dict) -> None:
        if not self._finishing and self._last_command is command:
            self._send(command)

    def _on_event_failed(self, payload: dict) -> None:
        self._fail(protocol.error_text(payload["error"]))

    def _on_event_completed(self, payload: dict) -> None:
        if self._current == "full_run":
            self._finish_command()
            self.run_done.emit()
        self._report_results()
        self._finish()

    def _on_event_cancelled(self, payload: dict) -> None:
        self._report_results()
        self._finish()

    def _on_event_goodbye(self, payload: dict) -> None:
        self.logger.debug(f"The runner service said goodbye: {payload}")

    # ------------------------------------------------------------------ commands
    def _dispatch(self) -> None:
        """
        Sends the next command of the user when the service can run it.
        :return: None
        """
        if self.state != "ready" or self._current is not None or not self._pending:
            return
        name = self._pending.popleft()
        progress = self.progress
        if name == "step":
            self._current = "step"
            self.before_step.emit()
            self._send(protocol.step_command())
        elif name == "run_to":
            target = self.run_to_date.to_pydatetime()
            self._run_to_target = target
            self.before_run_to.emit()
            if progress and (
                progress.next_date is None
                or (progress.last_date is not None and progress.last_date >= target)
            ):
                # the model is already at the date: there is nothing to run
                self.run_to_done.emit()
                self._after_command()
                return
            self._current = "run_to"
            self._send(protocol.run_until_command(target))
        elif name == "full_run":
            self._current = "full_run"
            self.before_run.emit()
            self.status_update.emit("Running")
            self._send(protocol.run_to_end_command())

    def _finish_command(self) -> None:
        self._current = None
        self._last_command = None
        self._retries = 0

    def _send(self, command: dict) -> None:
        self._last_command = command
        self._send_raw(self.session.frame(command))

    def _send_raw(self, data: bytes) -> None:
        if self.socket is not None:
            self.socket.write(data)

    # ----------------------------------------------------------------- finishing
    def _stop_run(self) -> None:
        """
        Stops the run requested by the user. A run that reached its end is
        completed, so that the outputs are written; otherwise it is cancelled.
        :return: None
        """
        if self._finishing:
            return
        if self.state == "ready" and self.session is not None:
            self.state = "closing"
            self._pending.clear()
            if self.progress is not None and self.progress.is_finished:
                self._send(protocol.run_to_end_command())
            else:
                self._send(protocol.cancel_command())
            # the service ends the session; do not wait for it forever
            QTimer.singleShot(10000, self._finish)
            return
        if self.state == "initialising" and self.session is not None:
            self.state = "closing"
            self._send(protocol.cancel_command())
            QTimer.singleShot(5000, self._finish)
            return
        # still starting or running a command: the service is stopped
        self._finish()

    def _fail(self, message: str) -> None:
        if self._finishing:
            return
        self._failed = True
        self.logger.debug(f"The run failed: {message}")
        self.model_error.emit(message)
        self._finish()

    def _report_results(self) -> None:
        """
        Tells the user where the outputs of the model were written.
        :return: None
        """
        if self._temporary_output or self.output_dir is None or self._failed:
            return
        try:
            if self.output_dir.exists() and any(self.output_dir.iterdir()):
                self.results_saved.emit(str(self.output_dir))
        except OSError as error:
            self.results_error.emit(str(error))

    def _finish(self) -> None:
        """
        Closes the connection, stops the service and tells the run controls that
        the worker is done.
        :return: None
        """
        if self._finishing:
            return
        self._finishing = True
        self.state = "closing"
        if self.connect_timer is not None:
            self.connect_timer.stop()
        if self.socket is not None:
            self.socket.abort()
        if self.process is not None and self.process.state() != (
            QProcess.ProcessState.NotRunning
        ):
            self.process.terminate()
            if not self.process.waitForFinished(3000):
                self.process.kill()
                self.process.waitForFinished(3000)
        # the socket and the process belong to this thread: they must be deleted
        # here and not later, by the thread that owns the worker
        for child in (self.socket, self.process):
            if child is not None:
                child.deleteLater()
        self.socket = self.process = None
        self._clean_output_dir()
        self.finished.emit()
        # the thread ends without waiting for the run controls, which are not there
        # when the editor is being closed
        thread = self.thread()
        if thread is not None:
            thread.quit()

    def _clean_output_dir(self) -> None:
        if self.output_dir is None:
            return
        try:
            if self._temporary_output:
                shutil.rmtree(self.output_dir, ignore_errors=True)
            elif self.output_dir.exists() and not any(self.output_dir.iterdir()):
                # nothing was written: do not leave an empty folder for the run
                self.output_dir.rmdir()
        except OSError:
            pass
