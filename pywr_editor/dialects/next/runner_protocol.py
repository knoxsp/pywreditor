import json
import struct
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

"""
 The messages of the pywr-next runner service (pywr_runner_protocol, version 1.0),
 which the editor uses to run a model step by step.

 The service is started with pywr._pywr.run_server(name) and listens on a local
 socket with that name. Messages are JSON documents, each preceded by its length as
 a 4-byte big-endian integer. A session is:
   1. the client sends a "hello" and the service answers "accepted" or "rejected";
   2. the client sends commands in envelopes with the session id, a run id of its
      choice (the same for all the commands of a run), and a sequence number that
      starts at 0; the service answers with events in envelopes numbered from 0;
   3. a run is "initialise"d with the model, then it can "step", "run_until" a date
      or "run_to_end", and it is "cancel"led or completes. The service ends the
      session when the run completes, fails or is cancelled.
 Events are "initialised", "update" (the progress), "state_changed", "log",
 "command_rejected", "failed", "completed" and "cancelled". The state events and
 the updates are not ordered with respect to each other, so a command is finished
 when its update arrives, not when the state changes.
"""

PROTOCOL_VERSION = {"major": 1, "minor": 0}
MAX_FRAME_SIZE = 64 * 1024 * 1024
""" The largest message the service accepts or sends """
SOLVERS = ("clp", "highs", "cbc", "microlp")
""" The solvers of the runner service """
DEFAULT_SOLVER = "clp"

SERVER_SNIPPET = """\
import os
import sys
import threading

# the service ends when the editor does, even if the editor crashes or is killed: it
# keeps listening for a new client after each run, so it would otherwise stay running.
# The editor keeps the standard input of the service open, and the operating system
# closes it when the editor ends: the service stops when it is closed. This works on
# every platform, also while the service is running a model
def stop_with_editor():
    try:
        sys.stdin.buffer.read()
    except Exception:
        return
    os._exit(0)

threading.Thread(target=stop_with_editor, daemon=True).start()
if sys.platform.startswith("linux"):
    # the kernel also ends the service when the editor does
    try:
        import ctypes
        import signal

        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)
    except Exception:
        pass
from pywr._pywr import run_server
run_server(sys.argv[1])
"""
""" The program that starts the service, run by the Python of the pywr-next
environment with the name of the socket as argument """


class ProtocolError(Exception):
    """A message that does not follow the protocol."""


def encode_frame(message: dict) -> bytes:
    """
    Encodes a message to send.
    :param message: The message dictionary.
    :return: The length of the JSON document followed by the document.
    """
    body = json.dumps(message).encode()
    if len(body) > MAX_FRAME_SIZE:
        raise ProtocolError(f"The message is too large ({len(body)} bytes)")
    return struct.pack(">I", len(body)) + body


class FrameDecoder:
    """Splits the bytes received from the service into messages."""

    def __init__(self):
        self.buffer = bytearray()

    def push(self, data: bytes) -> list[dict]:
        """
        Adds the bytes received and returns the messages that are complete.
        :param data: The bytes.
        :return: The decoded messages, in order.
        """
        self.buffer.extend(data)
        messages = []
        while len(self.buffer) >= 4:
            (length,) = struct.unpack(">I", self.buffer[:4])
            if length > MAX_FRAME_SIZE:
                raise ProtocolError(f"The service sent a message of {length} bytes")
            if len(self.buffer) < 4 + length:
                break
            body = bytes(self.buffer[4 : 4 + length])
            del self.buffer[: 4 + length]
            try:
                messages.append(json.loads(body))
            except ValueError as error:
                raise ProtocolError(f"The service sent invalid JSON: {error}")
        return messages


def socket_name(identifier: str | None = None) -> str:
    """
    Returns a name for the socket of a new service.
    :param identifier: A unique string. Defaults to a random one.
    :return: The socket name.
    """
    return f"pywr-editor-{identifier or uuid.uuid4().hex[:12]}"


def socket_address(name: str) -> tuple[str, bool]:
    """
    Returns how to connect to the socket the service creates for a name. The
    service uses the namespace of the platform: the abstract namespace on Linux, a
    named pipe on Windows and a file in /tmp on the other Unix systems.
    :param name: The socket name given to the service.
    :return: The name to connect to, and whether it is in the abstract namespace.
    """
    if sys.platform.startswith("linux"):
        return name, True
    if sys.platform == "win32":
        return name, False
    return str(Path("/tmp") / name), False


def hello(required_capabilities: list[str] | None = None) -> dict:
    """
    Returns the first message of a session.
    :param required_capabilities: The capabilities the service must have, such as
    "solver:clp".
    :return: The message.
    """
    return {
        "type": "hello",
        "payload": {
            "supported_versions": [PROTOCOL_VERSION],
            "required_capabilities": required_capabilities or [],
            "authentication": None,
        },
    }


def rejection_text(rejection: dict) -> str:
    """
    Describes why the service rejected the hello.
    :param rejection: The "rejected" message payload.
    :return: The explanation.
    """
    reason = rejection.get("reason")
    if reason == "unsupported_version":
        return (
            "This version of pywr-next does not support the runner protocol the "
            f"editor uses (it supports {rejection.get('supported')})"
        )
    if reason == "missing_capabilities":
        return "This version of pywr-next lacks " + ", ".join(
            rejection.get("capabilities", [])
        )
    return f"The runner service refused the connection ({reason})"


class ClientSession:
    """Builds the envelopes of the commands of one run."""

    def __init__(self, session_id: str, run_id: str | None = None):
        """
        :param session_id: The session id from the service's "accepted" message.
        :param run_id: The id of the run. Defaults to a random one.
        """
        self.session_id = session_id
        self.run_id = run_id or str(uuid.uuid4())
        self.sequence = 0

    def envelope(self, command: dict) -> dict:
        """
        Wraps a command in an envelope.
        :param command: The command, such as {"type": "step"}.
        :return: The envelope to send.
        """
        envelope = {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "payload": command,
        }
        self.sequence += 1
        return envelope

    def frame(self, command: dict) -> bytes:
        """
        Encodes a command to send.
        :param command: The command.
        :return: The bytes to send.
        """
        return encode_frame(self.envelope(command))


def initialise_command(
    run_name: str,
    model: dict,
    output_path: str | None,
    data_path: str | None,
    solver: str = DEFAULT_SOLVER,
    log_level: str = "info",
) -> dict:
    """
    Returns the command that prepares a run.
    :param run_name: The name of the run.
    :param model: The model dictionary.
    :param output_path: The folder where the outputs of the model are written.
    :param data_path: The folder the files of the model are relative to.
    :param solver: The solver: "clp", "highs", "cbc" or "microlp".
    :param log_level: The least important level of the messages the service sends.
    :return: The command.
    """
    return {
        "type": "initialise",
        "payload": {
            "request": {
                "run_name": run_name,
                "model": {"type": "json", "payload": model},
                "output_path": output_path,
                "data_path": data_path,
                "log_level": log_level,
                "solver": {"solver": solver},
                "result_options": {
                    "all_nodes_metric_set": None,
                    "all_edges_metric_set": None,
                    "clear_existing_outputs": False,
                    "arrow_streams": [],
                },
            }
        },
    }


def step_command() -> dict:
    return {"type": "step"}


def run_until_command(date: datetime) -> dict:
    """
    Returns the command that runs the model up to, and including, a date.
    :param date: The date.
    :return: The command.
    """
    return {
        "type": "run_until",
        "payload": {"datetime": date.strftime("%Y-%m-%dT%H:%M:%S")},
    }


def run_to_end_command() -> dict:
    return {"type": "run_to_end"}


def cancel_command() -> dict:
    return {"type": "cancel"}


def shutdown_command() -> dict:
    return {"type": "shutdown"}


def parse_date(value: Any) -> datetime | None:
    """
    Reads a date of the service.
    :param value: The date as a string, or None.
    :return: The date, None if there is none.
    """
    return datetime.fromisoformat(value) if value else None


@dataclass(frozen=True)
class Progress:
    completed: int
    """ The number of timesteps run """
    total: int
    """ The number of timesteps of the run """
    last_date: datetime | None
    """ The date of the last timestep run, None before the first one """
    next_date: datetime | None
    """ The date of the next timestep, None when the run reached its end """

    @classmethod
    def from_message(cls, progress: dict) -> "Progress":
        """
        Reads the progress of an "initialised" or "update" event.
        :param progress: The "progress" dictionary.
        :return: The progress.
        """
        return cls(
            completed=int(progress["completed_timesteps"]),
            total=int(progress["total_timesteps"]),
            last_date=parse_date(progress.get("last_completed_date")),
            next_date=parse_date(progress.get("next_date")),
        )

    @property
    def is_finished(self) -> bool:
        """
        Whether all the timesteps were run.
        """
        return self.next_date is None and self.completed >= self.total > 0


def error_text(error: dict) -> str:
    """
    Describes the error of a "failed" event for the user.
    :param error: The "error" dictionary.
    :return: The text, with the stage, the causes and the date of the timestep.
    """
    lines = [error.get("summary") or "The run failed"]
    lines += [f"  caused by: {cause}" for cause in error.get("causes") or []]
    details = [f"Stage: {str(error.get('stage', 'unknown')).replace('_', ' ')}"]
    if error.get("timestep"):
        details.append(f"Timestep: {error['timestep']}")
    return "\n".join(lines + [""] + details)
