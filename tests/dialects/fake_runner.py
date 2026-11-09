from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from pywr_editor.dialects.next import runner_protocol as protocol

"""
 A runner service that follows the protocol of the pywr-next runner service, for a
 model with a number of daily timesteps. It checks what the client sends (the
 handshake, the session and run ids, the sequence numbers) and records what it
 received, so that the tests can check the worker without installing pywr-next.
"""


class FakeRunner(QObject):
    def __init__(
        self,
        total: int = 6,
        start: datetime = datetime(2015, 1, 1),
        update_every: int = 2,
        reject_first_command: bool = False,
        fail_with: dict | None = None,
        write_file_on_end: bool = True,
        reject_hello: dict | None = None,
    ):
        """
        :param total: The number of timesteps of the run.
        :param start: The date of the first timestep.
        :param update_every: The number of timesteps between two updates of a run.
        :param reject_first_command: Reject each step with "command_rejected" once,
        as the service does while it is still busy.
        :param fail_with: The "error" of a "failed" event sent when the run is
        initialised.
        :param write_file_on_end: Write a file in the output folder when the run
        completes or is cancelled.
        :param reject_hello: The rejection payload sent instead of "accepted".
        """
        super().__init__()
        self.total = total
        self.start = start
        self.update_every = update_every
        self.reject_first_command = reject_first_command
        self.fail_with = fail_with
        self.write_file_on_end = write_file_on_end
        self.reject_hello = reject_hello

        self.server = QLocalServer(self)
        self.socket: QLocalSocket | None = None
        self.decoder = protocol.FrameDecoder()
        self.session_id = "00000000-0000-0000-0000-000000000001"
        self.run_id: str | None = None
        self.client_sequence = 0
        self.server_sequence = 0
        self.completed = 0
        self.rejected_current = False
        self.hello: dict | None = None
        self.initialise: dict | None = None
        self.commands: list[str] = []
        self.errors: list[str] = []
        self.client_disconnected = False

    def listen(self, name: str) -> None:
        """
        Listens on the socket the worker connects to.
        :param name: The socket name of the worker.
        :return: None
        """
        address, abstract = protocol.socket_address(name)
        if abstract:
            self.server.setSocketOptions(
                QLocalServer.SocketOption.AbstractNamespaceOption
            )
        QLocalServer.removeServer(address)
        assert self.server.listen(address), self.server.errorString()
        self.server.newConnection.connect(self.on_connection)

    def on_connection(self) -> None:
        self.socket = self.server.nextPendingConnection()
        self.socket.readyRead.connect(self.on_ready_read)
        self.socket.disconnected.connect(self.on_disconnected)

    def on_disconnected(self) -> None:
        self.client_disconnected = True

    def date(self, index: int) -> datetime:
        return self.start + timedelta(days=index)

    def progress(self) -> dict:
        done = self.completed
        return {
            "completed_timesteps": done,
            "total_timesteps": self.total,
            "last_completed_date": (
                self.date(done - 1).isoformat(timespec="seconds") if done else None
            ),
            "next_date": (
                self.date(done).isoformat(timespec="seconds")
                if done < self.total
                else None
            ),
        }

    def send_raw(self, message: dict) -> None:
        self.socket.write(protocol.encode_frame(message))

    def send(self, kind: str, payload=None) -> None:
        event = {"type": kind}
        if payload is not None:
            event["payload"] = payload
        self.send_raw(
            {
                "session_id": self.session_id,
                "run_id": self.run_id,
                "sequence": self.server_sequence,
                "payload": event,
            }
        )
        self.server_sequence += 1

    def on_ready_read(self) -> None:
        for message in self.decoder.push(bytes(self.socket.readAll())):
            if self.hello is None:
                self.on_hello(message)
            else:
                self.on_envelope(message)

    def on_hello(self, message: dict) -> None:
        self.hello = message.get("payload", {})
        if message.get("type") != "hello":
            self.errors.append(f"expected hello, got {message.get('type')}")
        if self.reject_hello is not None:
            self.send_raw({"type": "rejected", "payload": self.reject_hello})
            return
        self.send_raw(
            {
                "type": "accepted",
                "payload": {
                    "selected_version": protocol.PROTOCOL_VERSION,
                    "session_id": self.session_id,
                    "capabilities": ["solver:clp"],
                },
            }
        )

    def on_envelope(self, envelope: dict) -> None:
        if envelope.get("session_id") != self.session_id:
            self.errors.append("wrong session id")
        if envelope.get("sequence") != self.client_sequence:
            self.errors.append(
                f"sequence {envelope.get('sequence')}, expected {self.client_sequence}"
            )
        self.client_sequence += 1
        if self.run_id is None:
            self.run_id = envelope.get("run_id")
        elif envelope.get("run_id") != self.run_id:
            self.errors.append("the run id changed")

        command = envelope["payload"]
        kind = command["type"]
        self.commands.append(kind)
        getattr(self, f"on_{kind}")(command.get("payload"))

    # the commands
    def on_initialise(self, payload: dict) -> None:
        self.initialise = payload["request"]
        if self.fail_with is not None:
            self.send("failed", {"error": self.fail_with})
            return
        self.send("initialised", {"progress": self.progress(), "arrow_streams": []})

    def advance(self, steps: int) -> None:
        self.completed = min(self.completed + steps, self.total)
        self.send("update", {"progress": self.progress(), "arrow_stream_commits": []})

    def on_step(self, payload) -> None:
        if self.reject_first_command and not self.rejected_current:
            self.rejected_current = True
            self.send("command_rejected", {"command": "Step", "status": "running"})
            return
        self.rejected_current = False
        self.advance(1)

    def on_run_until(self, payload: dict) -> None:
        target = datetime.fromisoformat(payload["datetime"])
        self.send("state_changed", "running")
        count = 0
        while self.completed < self.total and self.date(self.completed) <= target:
            self.completed += 1
            count += 1
            reached = self.completed == self.total or self.date(self.completed) > target
            if count % self.update_every == 0 or reached:
                self.send(
                    "update",
                    {"progress": self.progress(), "arrow_stream_commits": []},
                )
        if count == 0:
            self.advance(0)
        self.send("state_changed", "ready")

    def write_output(self) -> None:
        path = self.initialise.get("output_path") if self.initialise else None
        if path and self.write_file_on_end:
            Path(path, "output.csv").write_text("time,value\n")

    def on_run_to_end(self, payload) -> None:
        self.send("state_changed", "running")
        while self.completed < self.total:
            self.advance(min(self.update_every, self.total - self.completed))
        self.write_output()
        self.send("log", {"record": {"level": "info", "message": "done"}})
        self.send("completed", {"summary": {"outcome": "completed"}})

    def on_cancel(self, payload) -> None:
        self.send("state_changed", "cancelling")
        self.write_output()
        self.send("cancelled", {"summary": {"outcome": "cancelled"}})

    def on_shutdown(self, payload) -> None:
        self.send("goodbye", {"type": "normal"})
