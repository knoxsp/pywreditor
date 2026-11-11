import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from PySide6.QtCore import QThread

from pywr_editor.dialects.next import runner_protocol as protocol
from pywr_editor.dialects.next.runner import NextRunWorker
from tests.dialects.fake_runner import FakeRunner

SIGNALS = [
    "status_update",
    "before_step",
    "step_done",
    "before_run_to",
    "run_to_done",
    "before_run",
    "run_done",
    "model_error",
    "run_to_date_reached",
    "end_date_reached",
    "results_saved",
    "results_error",
    "finished",
]


class TestProtocol:
    def test_frames(self):
        """
        Tests that messages are split from the bytes received, in any chunks.
        """
        first = protocol.encode_frame({"a": 1})
        second = protocol.encode_frame({"b": [1, 2]})
        assert first[:4] == b"\x00\x00\x00\x08"
        decoder = protocol.FrameDecoder()
        data = first + second
        messages = []
        for i in range(0, len(data), 3):
            messages += decoder.push(data[i : i + 3])
        assert messages == [{"a": 1}, {"b": [1, 2]}]
        assert decoder.push(b"") == []

    def test_invalid_frames(self):
        decoder = protocol.FrameDecoder()
        with pytest.raises(protocol.ProtocolError):
            decoder.push(b"\xff\xff\xff\xff")
        decoder = protocol.FrameDecoder()
        with pytest.raises(protocol.ProtocolError):
            decoder.push(b"\x00\x00\x00\x03abc")

    def test_session_envelopes(self):
        session = protocol.ClientSession("sid", "rid")
        first = session.envelope(protocol.step_command())
        second = session.envelope(protocol.cancel_command())
        assert first == {
            "session_id": "sid",
            "run_id": "rid",
            "sequence": 0,
            "payload": {"type": "step"},
        }
        assert second["sequence"] == 1
        assert (
            protocol.ClientSession("sid").run_id != protocol.ClientSession("sid").run_id
        )

    def test_commands(self):
        command = protocol.initialise_command(
            "run", {"metadata": {}}, "/out", "/data", solver="highs"
        )
        request = command["payload"]["request"]
        assert command["type"] == "initialise"
        assert request["model"] == {"type": "json", "payload": {"metadata": {}}}
        assert request["solver"] == {"solver": "highs"}
        assert request["output_path"] == "/out" and request["data_path"] == "/data"
        assert request["result_options"]["arrow_streams"] == []
        assert protocol.run_until_command(datetime(2015, 1, 4)) == {
            "type": "run_until",
            "payload": {"datetime": "2015-01-04T00:00:00"},
        }
        hello = protocol.hello(["solver:clp"])["payload"]
        assert hello["required_capabilities"] == ["solver:clp"]
        assert hello["supported_versions"] == [{"major": 1, "minor": 0}]

    def test_progress(self):
        progress = protocol.Progress.from_message(
            {
                "completed_timesteps": 6,
                "total_timesteps": 6,
                "last_completed_date": "2015-01-06T00:00:00",
                "next_date": None,
            }
        )
        assert progress.last_date == datetime(2015, 1, 6)
        assert progress.is_finished is True
        start = protocol.Progress.from_message(
            {
                "completed_timesteps": 0,
                "total_timesteps": 6,
                "last_completed_date": None,
                "next_date": "2015-01-01T00:00:00",
            }
        )
        assert start.last_date is None and start.is_finished is False

    def test_error_texts(self):
        text = protocol.error_text(
            {
                "stage": "model_build",
                "summary": "Failed to build",
                "causes": ["no node", "no parameter"],
                "timestep": "2015-01-02T00:00:00",
            }
        )
        assert text.splitlines()[0] == "Failed to build"
        assert "  caused by: no parameter" in text
        assert "Stage: model build" in text and "Timestep: 2015-01-02" in text
        assert "does not support" in protocol.rejection_text(
            {"reason": "unsupported_version", "supported": []}
        )
        assert "lacks solver:cbc" in protocol.rejection_text(
            {"reason": "missing_capabilities", "capabilities": ["solver:cbc"]}
        )

    @pytest.mark.parametrize(
        "platform, address",
        [
            ("linux", ("name", True)),
            ("win32", ("name", False)),
            ("darwin", ("/tmp/name", False)),
        ],
    )
    def test_socket_address(self, monkeypatch, platform, address):
        monkeypatch.setattr(sys, "platform", platform)
        assert protocol.socket_address("name") == address

    def test_socket_names_are_unique(self):
        assert protocol.socket_name() != protocol.socket_name()


class Recorder:
    """Records the signals of a worker, which are emitted in its thread."""

    def __init__(self, worker: NextRunWorker):
        self.events: list[tuple] = []
        self.progress: list[dict] = []
        for name in SIGNALS:
            getattr(worker, name).connect(self.make(name))
        worker.progress_update.connect(lambda p: self.progress.append(dict(p)))

    def make(self, name: str):
        return lambda *args: self.events.append((name, *args))

    @property
    def names(self) -> list[str]:
        return [event[0] for event in self.events]

    def count(self, name: str) -> int:
        return self.names.count(name)

    def texts(self, name: str) -> list[str]:
        return [event[1] for event in self.events if event[0] == name]


@pytest.fixture
def start_worker(qtbot, tmp_path):
    """
    Returns a function that starts a worker connected to a fake runner service.
    """
    threads: list[QThread] = []
    runners: list[FakeRunner] = []

    def start(runner: FakeRunner | None = None, listen: bool = True, **kwargs):
        runner = runner or FakeRunner()
        runners.append(runner)
        options = dict(
            model_dict={"metadata": {"title": "t"}},
            model_file=str(tmp_path / "model.json"),
            python=None,
            end_date=pd.Timestamp("2015-01-06"),
            run_to_date=pd.Timestamp("2015-01-04"),
            solver="clp",
            results_dir=str(tmp_path / "outputs"),
            server_command=[],
            connect_timeout=15,
        )
        options.update(kwargs)
        worker = NextRunWorker(**options)
        if listen:
            runner.listen(worker.socket_name)
        recorder = Recorder(worker)
        thread = QThread()
        threads.append(thread)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.start()
        return worker, runner, recorder

    yield start
    for thread in threads:
        thread.quit()
        assert thread.wait(10000)
    for runner in runners:
        runner.server.close()


def wait_ready(qtbot, recorder: Recorder) -> None:
    qtbot.waitUntil(
        lambda: "Ready to run" in recorder.texts("status_update"), timeout=10000
    )


def wait_for(qtbot, recorder: Recorder, name: str, count: int = 1) -> None:
    qtbot.waitUntil(lambda: recorder.count(name) >= count, timeout=10000)


class TestWorker:
    def test_session_setup(self, qtbot, start_worker, tmp_path):
        """
        Tests what the worker sends to start the run.
        """
        worker, runner, recorder = start_worker(solver="highs")
        wait_ready(qtbot, recorder)
        assert runner.hello["required_capabilities"] == ["solver:highs"]
        request = runner.initialise
        assert request["model"] == {
            "type": "json",
            "payload": {"metadata": {"title": "t"}},
        }
        assert request["solver"] == {"solver": "highs"}
        assert request["data_path"] == str(tmp_path)
        assert Path(request["output_path"]).parent == tmp_path / "outputs"
        assert request["run_name"] == "model"
        assert recorder.texts("status_update")[:3] == [
            "Starting pywr-next",
            "Connecting to pywr-next",
            "Loading model",
        ]
        assert runner.errors == []
        worker.kill()
        wait_for(qtbot, recorder, "finished")

    def test_step(self, qtbot, start_worker):
        worker, runner, recorder = start_worker()
        wait_ready(qtbot, recorder)
        worker.step()
        wait_for(qtbot, recorder, "step_done")
        assert recorder.names.index("before_step") < recorder.names.index("step_done")
        assert recorder.progress[-1]["current_index"] == 0
        assert recorder.progress[-1]["last_index"] == 5
        assert recorder.progress[-1]["current_timestamp"] == pd.Timestamp("2015-01-01")

        worker.step()
        wait_for(qtbot, recorder, "step_done", 2)
        assert recorder.progress[-1]["current_timestamp"] == pd.Timestamp("2015-01-02")
        assert runner.commands == ["initialise", "step", "step"]
        assert runner.errors == []
        assert recorder.count("end_date_reached") == 0
        worker.kill()
        wait_for(qtbot, recorder, "finished")

    def test_commands_wait_for_the_model(self, qtbot, start_worker):
        """
        Tests that a command asked for before the model is loaded runs when it is
        ready, as the run controls ask for a step right after starting the worker.
        """
        worker, runner, recorder = start_worker()
        worker.step()
        wait_for(qtbot, recorder, "step_done")
        assert runner.commands == ["initialise", "step"]
        worker.kill()
        wait_for(qtbot, recorder, "finished")

    def test_run_to(self, qtbot, start_worker):
        worker, runner, recorder = start_worker()
        wait_ready(qtbot, recorder)
        worker.run_to()
        wait_for(qtbot, recorder, "run_to_done")
        assert recorder.count("before_run_to") == 1
        wait_for(qtbot, recorder, "run_to_date_reached")
        assert runner.commands == ["initialise", "run_until"]
        assert recorder.progress[-1]["current_timestamp"] == pd.Timestamp("2015-01-04")
        assert recorder.progress[-1]["current_index"] == 3
        # progress was reported before the end of the command
        assert len(recorder.progress) >= 2

        # already at the date: nothing is sent
        worker.run_to()
        wait_for(qtbot, recorder, "run_to_done", 2)
        assert runner.commands == ["initialise", "run_until"]
        worker.kill()
        wait_for(qtbot, recorder, "finished")

    def test_end_date_then_stop_writes_outputs(self, qtbot, start_worker, tmp_path):
        """
        Tests that the run controls are told when the last timestep is reached, and
        that stopping then completes the run, so that the outputs are written.
        """
        worker, runner, recorder = start_worker()
        wait_ready(qtbot, recorder)
        for count in range(1, 7):
            worker.step()
            wait_for(qtbot, recorder, "step_done", count)
        wait_for(qtbot, recorder, "end_date_reached")
        assert recorder.count("end_date_reached") == 1
        assert recorder.names.index("step_done", 5) < recorder.names.index(
            "end_date_reached"
        )
        assert recorder.progress[-1]["current_index"] == 5

        worker.kill()
        wait_for(qtbot, recorder, "finished")
        assert runner.commands[-1] == "run_to_end"
        run_dir = Path(recorder.texts("results_saved")[0])
        assert run_dir.parent == tmp_path / "outputs"
        assert (run_dir / "output.csv").is_file()
        assert recorder.count("run_done") == 0
        assert runner.errors == []

    def test_full_run(self, qtbot, start_worker):
        worker, runner, recorder = start_worker()
        wait_ready(qtbot, recorder)
        worker.full_run()
        wait_for(qtbot, recorder, "finished")
        assert recorder.names.index("before_run") < recorder.names.index("run_done")
        assert recorder.count("results_saved") == 1
        assert runner.commands == ["initialise", "run_to_end"]
        assert recorder.progress[-1]["current_index"] == 5
        assert runner.errors == []

    def test_stop_cancels_a_run_in_progress(self, qtbot, start_worker):
        worker, runner, recorder = start_worker()
        wait_ready(qtbot, recorder)
        worker.step()
        wait_for(qtbot, recorder, "step_done")
        worker.kill()
        wait_for(qtbot, recorder, "finished")
        assert runner.commands == ["initialise", "step", "cancel"]
        assert recorder.count("results_saved") == 1
        assert recorder.count("model_error") == 0

    def test_stop_while_connecting(self, qtbot, start_worker, tmp_path):
        """
        Tests that the worker can be stopped while it waits for the service.
        """
        worker, runner, recorder = start_worker(listen=False)
        qtbot.waitUntil(lambda: recorder.count("status_update") >= 1)
        worker.kill()
        wait_for(qtbot, recorder, "finished")
        assert recorder.count("model_error") == 0
        # the folder of the run is removed when nothing was written
        assert list((tmp_path / "outputs").iterdir()) == []

    def test_shutdown_ends_the_thread(self, qtbot, start_worker):
        """
        Tests that shutdown() stops the run at once and waits for the thread, which
        ends by itself, so that nothing is left running when the editor closes.
        """
        worker, runner, recorder = start_worker()
        wait_ready(qtbot, recorder)
        worker.step()
        wait_for(qtbot, recorder, "step_done")
        thread = worker.thread()
        worker.shutdown()
        assert not thread.isRunning()
        wait_for(qtbot, recorder, "finished")
        assert recorder.count("finished") == 1
        assert recorder.count("model_error") == 0
        # the connection to the service was closed
        qtbot.waitUntil(lambda: runner.client_disconnected, timeout=5000)

    def test_shutdown_while_connecting(self, qtbot, start_worker):
        worker, runner, recorder = start_worker(listen=False)
        qtbot.waitUntil(lambda: recorder.count("status_update") >= 1)
        thread = worker.thread()
        worker.shutdown()
        assert not thread.isRunning()

    def test_shutdown_after_the_run_ended_does_nothing(self, qtbot, start_worker):
        worker, runner, recorder = start_worker()
        wait_ready(qtbot, recorder)
        worker.full_run()
        wait_for(qtbot, recorder, "finished")
        qtbot.waitUntil(lambda: not worker.thread().isRunning(), timeout=5000)
        worker.shutdown()
        assert recorder.count("finished") == 1

    def test_service_not_found(self, qtbot, start_worker):
        worker, runner, recorder = start_worker(listen=False, connect_timeout=0.5)
        wait_for(qtbot, recorder, "finished")
        assert "did not start" in recorder.texts("model_error")[0]

    def test_model_error(self, qtbot, start_worker):
        error = {
            "stage": "model_build",
            "summary": "Failed to build model from builder.",
            "causes": ["Error building node `Demand`."],
            "timestep": None,
        }
        worker, runner, recorder = start_worker(FakeRunner(fail_with=error))
        wait_for(qtbot, recorder, "finished")
        text = recorder.texts("model_error")[0]
        assert "Failed to build model from builder." in text
        assert "caused by: Error building node `Demand`." in text
        assert recorder.count("results_saved") == 0

    def test_rejected_by_the_service(self, qtbot, start_worker):
        rejection = {"reason": "missing_capabilities", "capabilities": ["solver:clp"]}
        worker, runner, recorder = start_worker(FakeRunner(reject_hello=rejection))
        wait_for(qtbot, recorder, "finished")
        assert "lacks solver:clp" in recorder.texts("model_error")[0]

    def test_busy_service_rejects_commands(self, qtbot, start_worker):
        """
        Tests that a command rejected because the service is still busy is sent
        again.
        """
        worker, runner, recorder = start_worker(FakeRunner(reject_first_command=True))
        wait_ready(qtbot, recorder)
        worker.step()
        wait_for(qtbot, recorder, "step_done")
        assert runner.commands == ["initialise", "step", "step"]
        assert recorder.count("model_error") == 0
        assert runner.errors == []
        worker.kill()
        wait_for(qtbot, recorder, "finished")

    def test_connection_lost(self, qtbot, start_worker):
        worker, runner, recorder = start_worker()
        wait_ready(qtbot, recorder)
        runner.socket.disconnectFromServer()
        wait_for(qtbot, recorder, "finished")
        assert "closed the connection" in recorder.texts("model_error")[0]

    def test_outputs_in_a_temporary_folder(self, qtbot, start_worker):
        """
        Tests that the outputs are not kept when the results are not saved.
        """
        worker, runner, recorder = start_worker(results_dir=None)
        wait_ready(qtbot, recorder)
        output = Path(runner.initialise["output_path"])
        assert output.is_dir()
        worker.full_run()
        wait_for(qtbot, recorder, "finished")
        assert recorder.count("results_saved") == 0
        assert not output.exists()

    def test_no_folder_left_without_outputs(self, qtbot, start_worker, tmp_path):
        worker, runner, recorder = start_worker(FakeRunner(write_file_on_end=False))
        wait_ready(qtbot, recorder)
        worker.full_run()
        wait_for(qtbot, recorder, "finished")
        assert recorder.count("results_saved") == 0
        assert list((tmp_path / "outputs").iterdir()) == []

    def test_missing_python(self, qtbot, start_worker, tmp_path):
        worker, runner, recorder = start_worker(
            listen=False, server_command=None, python=str(tmp_path / "no-python")
        )
        wait_for(qtbot, recorder, "finished")
        assert "could not be started" in recorder.texts("model_error")[0]


@pytest.mark.skipif(
    not os.environ.get("PYWR_NEXT_PYTHON"),
    reason="set PYWR_NEXT_PYTHON to a Python with pywr-next (and pandas) installed",
)
def test_real_runner_service(qtbot, tmp_path):
    """
    Runs a model with the real pywr-next runner service: steps, runs to a date and
    to the end, and checks that the outputs of the model are written.
    """
    from tests.utils import model_path

    model_file = model_path() / "pywr_next" / "reservoir_with_evaporation1.json"
    import json

    worker = NextRunWorker(
        model_dict=json.loads(model_file.read_text()),
        model_file=str(model_file),
        python=os.environ["PYWR_NEXT_PYTHON"],
        end_date=pd.Timestamp("2015-01-06"),
        run_to_date=pd.Timestamp("2015-01-04"),
        results_dir=str(tmp_path),
    )
    recorder = Recorder(worker)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    thread.start()
    try:
        worker.step()
        wait_for(qtbot, recorder, "step_done")
        worker.run_to()
        wait_for(qtbot, recorder, "run_to_done")
        assert recorder.progress[-1]["current_timestamp"] == pd.Timestamp("2015-01-04")
        worker.step()
        wait_for(qtbot, recorder, "step_done", 2)
        worker.step()
        wait_for(qtbot, recorder, "step_done", 3)
        wait_for(qtbot, recorder, "end_date_reached")
        worker.kill()
        wait_for(qtbot, recorder, "finished")
        assert recorder.count("model_error") == 0, recorder.texts("model_error")
        run_dir = Path(recorder.texts("results_saved")[0])
        assert (run_dir / "reservoir_with_evaporation1-expected.csv").is_file()
        # the results of all the nodes can be shown by the results viewer
        from pywr_editor.model.results import ResultsRun

        run = ResultsRun(run_dir)
        assert {"Catchment", "Reservoir", "Demand"} <= set(run.recorder_names)
        assert run.metadata["format"] == "pywr-next"
        assert run.has_timeseries("Reservoir")
        assert len(run.timeseries("Reservoir")) >= 4
    finally:
        thread.quit()
        thread.wait(10000)


# the part of the service program that is specific to Linux is removed to test what the
# other platforms use
WATCHDOG_ONLY = protocol.SERVER_SNIPPET.replace('sys.platform.startswith("linux")', "False")

LONG_RUN_MODEL = """
{"metadata": {"title": "long"},
 "time": {"start": "1700-01-01", "end": "2400-12-31",
          "timestep": {"type": "Days", "days": 1}},
 "network": {"nodes": [
   {"meta": {"name": "in"}, "type": "Input", "max_flow": {"type": "Literal", "value": 5}},
   {"meta": {"name": "out"}, "type": "Output", "max_flow": {"type": "Literal", "value": 3},
    "cost": {"type": "Literal", "value": -10}}],
  "edges": [{"from_node": "in", "to_node": "out"}]}}
"""


def is_alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except (FileNotFoundError, ProcessLookupError):
        return False


def wait_until_gone(pid: int, seconds: float = 8) -> bool:
    import time

    deadline = time.time() + seconds
    while is_alive(pid) and time.time() < deadline:
        time.sleep(0.1)
    gone = not is_alive(pid)
    if not gone:
        os.kill(pid, 9)
    return gone


EDITOR = """
import json, os, socket, subprocess, sys, time
from pywr_editor.dialects.next import runner_protocol as P

python, snippet, name, run = sys.argv[1:5]
# the editor keeps the standard input of the service open, as QProcess does
service = subprocess.Popen([python, "-c", snippet, name], stdin=subprocess.PIPE,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(service.pid, flush=True)
if run == "idle":
    time.sleep(120)
sock = None
for _ in range(300):
    sock = socket.socket(socket.AF_UNIX)
    try:
        sock.connect("\\0" + name)
        break
    except OSError:
        sock.close()
        time.sleep(0.1)
decoder = P.FrameDecoder()

def read():
    sock.settimeout(60)
    while True:
        messages = decoder.push(sock.recv(1 << 20))
        if messages:
            return messages

def kinds(messages):
    return [m.get("payload", m).get("type") for m in messages]

sock.sendall(P.encode_frame(P.hello(["solver:clp"])))
accepted = read()[0]
session = P.ClientSession((accepted.get("payload") or accepted)["session_id"])
sock.sendall(session.frame(P.initialise_command(
    "long", json.loads(sys.argv[5]), sys.argv[6], sys.argv[6])))
seen = []
while "initialised" not in seen:
    seen += kinds(read())
sock.sendall(session.frame(P.run_to_end_command()))
updates = 0
while updates < 3:
    updates += kinds(read()).count("update")
print("running", flush=True)
time.sleep(120)
"""


def start_editor(tmp_path, snippet: str, run: str):
    """
    Starts a process that acts as the editor: it starts the service and, when asked,
    a long run. It returns when the service is busy.
    :return: The editor process and the process id of the service.
    """
    import subprocess

    python = os.environ["PYWR_NEXT_PYTHON"]
    editor = subprocess.Popen(
        [
            sys.executable,
            "-c",
            EDITOR,
            python,
            snippet,
            f"pywr-editor-test-{os.getpid()}-{run}",
            run,
            LONG_RUN_MODEL,
            str(tmp_path),
        ],
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[2])},
    )
    service_pid = int(editor.stdout.readline())
    if run == "busy":
        assert editor.stdout.readline().strip() == "running"
    else:
        import time

        time.sleep(2)  # let the service start
    return editor, service_pid


@pytest.mark.skipif(not os.environ.get("PYWR_NEXT_PYTHON"), reason="needs PYWR_NEXT_PYTHON")
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs Linux (/proc)")
@pytest.mark.parametrize(
    "snippet",
    [protocol.SERVER_SNIPPET, WATCHDOG_ONLY],
    ids=["linux", "other_platforms"],
)
@pytest.mark.parametrize("run", ["idle", "busy"])
def test_service_ends_when_the_editor_is_killed(tmp_path, snippet, run):
    """
    Tests that the real service does not stay running when the process that started
    it is killed, which would happen if the editor crashed: the service keeps
    listening for a new client after each run. It must stop both when it waits for a
    client and while it runs a model, with what the service uses on Linux and with
    what is used on the other platforms.
    """
    import signal

    editor, service_pid = start_editor(tmp_path, snippet, run)
    try:
        assert is_alive(service_pid)
        editor.send_signal(signal.SIGKILL)
        editor.wait()
        assert wait_until_gone(service_pid)
    finally:
        if editor.poll() is None:
            editor.kill()
        if is_alive(service_pid):
            os.kill(service_pid, 9)
