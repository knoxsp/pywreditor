import shutil

import pytest
from PySide6.QtCore import Qt

from pywr_editor import MainWindow
from pywr_editor.dialects.next.runner import NextRunWorker
from pywr_editor.toolbar.run_controls.run_widget import RunWidget
from tests.dialects.fake_runner import FakeRunner
from tests.utils import model_path

NEXT_MODELS = model_path() / "pywr_next"


class Environment:
    """What ensure_pywr_next() returns for an installed environment."""

    python = "python"


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    """
    Opens a copy of the reservoir model (6 daily timesteps) whose runs are done by a
    fake runner service, as if pywr-next was installed.
    """
    model_file = tmp_path / "model.json"
    shutil.copy(NEXT_MODELS / "reservoir_with_evaporation1.json", model_file)
    runners: list[FakeRunner] = []

    class FakeBackedWorker(NextRunWorker):
        def __init__(self, *args, **kwargs):
            kwargs.pop("python", None)
            super().__init__(*args, python=None, server_command=[], **kwargs)
            runner = FakeRunner()
            runner.listen(self.socket_name)
            runners.append(runner)

    monkeypatch.setattr(
        "pywr_editor.dialogs.environments.install_dialog.ensure_pywr_next",
        lambda purpose, parent=None: Environment(),
    )
    monkeypatch.setattr(
        "pywr_editor.dialects.next.runner.NextRunWorker", FakeBackedWorker
    )
    window = MainWindow(str(model_file))
    window.hide()
    window.runners = runners
    yield window
    run_widget = window.findChild(RunWidget)
    if run_widget.is_running:
        run_widget.stop()
        qtbot.waitUntil(lambda: not run_widget.is_running, timeout=10000)
    for runner in runners:
        runner.server.close()
    window.model_config.reset_change_flag()
    window.close()


def test_controls_are_enabled(window):
    run_widget = window.findChild(RunWidget)
    assert run_widget.isEnabled()
    for button in [
        run_widget.step_button,
        run_widget.run_button,
        run_widget.run_to_button,
    ]:
        assert button.isEnabled() is True
    assert run_widget.stop_button.isEnabled() is False


def test_step_and_stop(qtbot, window):
    """
    Tests the Step and Stop buttons with the controls of the editor.
    """
    run_widget = window.findChild(RunWidget)
    qtbot.mouseClick(run_widget.step_button, Qt.MouseButton.LeftButton)
    assert run_widget.is_running is True
    qtbot.waitUntil(lambda: run_widget.stop_button.isEnabled(), timeout=10000)
    assert run_widget.progress_status.text() == "01/01/2015"
    assert run_widget.progress_bar.value() == 0
    assert run_widget.step_button.isEnabled() is True

    qtbot.mouseClick(run_widget.step_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: run_widget.progress_status.text() == "02/01/2015", timeout=10000
    )
    assert run_widget.progress_bar.value() == 20

    qtbot.mouseClick(run_widget.stop_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not run_widget.is_running, timeout=10000)
    assert run_widget.step_button.isEnabled() is True
    assert run_widget.stop_button.isEnabled() is False
    assert window.runners[0].commands[-1] == "cancel"


def test_run_to_end_date(qtbot, window):
    """
    Tests that the buttons are disabled when the last timestep is reached and that
    Stop then completes the run.
    """
    run_widget = window.findChild(RunWidget)
    for count in range(6):
        qtbot.mouseClick(run_widget.step_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(
            lambda: run_widget.step_button.isEnabled()
            or run_widget.is_end_date_reached,
            timeout=10000,
        )
        qtbot.waitUntil(lambda: run_widget.stop_button.isEnabled(), timeout=10000)
    qtbot.waitUntil(lambda: run_widget.is_end_date_reached, timeout=10000)
    assert run_widget.step_button.isEnabled() is False
    assert run_widget.run_button.isEnabled() is False
    assert run_widget.progress_bar.value() == 100

    qtbot.mouseClick(run_widget.stop_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not run_widget.is_running, timeout=10000)
    assert window.runners[0].commands[-1] == "run_to_end"
    assert window.runners[0].errors == []


def test_closing_the_window_stops_the_service(qtbot, window):
    """
    Tests that closing the editor during a run stops the worker thread, which
    owns the connection to the service.
    """
    run_widget = window.findChild(RunWidget)
    qtbot.mouseClick(run_widget.step_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: run_widget.stop_button.isEnabled(), timeout=10000)
    thread = run_widget.worker.thread()
    assert thread.isRunning()
    # nodes without a position were placed on the schematic: do not ask to save
    window.model_config.reset_change_flag()
    window.close()
    assert not thread.isRunning()
    qtbot.waitUntil(lambda: window.runners[0].client_disconnected, timeout=5000)


def test_full_run(qtbot, window, monkeypatch):
    run_widget = window.findChild(RunWidget)
    # the dialog telling where the results were saved is not shown
    monkeypatch.setattr(run_widget, "on_results_saved", lambda folder: None)
    qtbot.mouseClick(run_widget.run_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not run_widget.is_running, timeout=10000)
    assert window.runners[0].commands == ["initialise", "run_to_end"]
    assert run_widget.run_button.isEnabled() is True
    assert window.statusBar().currentMessage() == "Run has ended"


def test_declined_installation(qtbot, window, monkeypatch):
    """
    Tests that nothing runs when the user does not install pywr-next.
    """
    monkeypatch.setattr(
        "pywr_editor.dialogs.environments.install_dialog.ensure_pywr_next",
        lambda purpose, parent=None: None,
    )
    run_widget = window.findChild(RunWidget)
    qtbot.mouseClick(run_widget.step_button, Qt.MouseButton.LeftButton)
    assert run_widget.is_running is False
    assert run_widget.worker is None
    assert window.runners == []


def test_model_error_is_shown(qtbot, window, monkeypatch):
    """
    Tests that the error of a model that cannot be built is shown.
    """
    shown = []
    run_widget = window.findChild(RunWidget)
    monkeypatch.setattr(run_widget, "on_model_error", lambda text: shown.append(text))

    original = FakeRunner.on_initialise

    def fail(self, payload):
        self.fail_with = {
            "stage": "model_build",
            "summary": "Failed to build model from builder.",
            "causes": ["Error building node `Demand`."],
        }
        original(self, payload)

    monkeypatch.setattr(FakeRunner, "on_initialise", fail)
    qtbot.mouseClick(run_widget.step_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not run_widget.is_running, timeout=10000)
    assert "Failed to build model from builder." in shown[0]


def test_solver_setting(window):
    """
    Tests that the run settings offer the pywr-next solvers and keep the choice
    apart from the solver of pywr v1 models.
    """
    from pywr_editor.toolbar.run_settings import RunSettings

    settings = window.findChild(RunSettings)
    solvers = [settings.solver.itemText(i) for i in range(settings.solver.count())]
    assert solvers == ["clp", "highs", "cbc", "microlp"]
    assert settings.solver.currentText() == "clp"
    settings.solver.setCurrentText("highs")
    assert window.editor_settings.next_solver == "highs"
    assert window.editor_settings.solver == "glpk-edge"
