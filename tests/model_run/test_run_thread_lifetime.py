import subprocess
import sys
from pathlib import Path

import pytest

from tests.utils import ISOLATE_SETTINGS, child_process_env, resolve_model_path

ROOT = Path(__file__).parents[2]

SCRIPT = """
import sys, time
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication
from pywr_editor import MainWindow
from pywr_editor.utils import Settings
ISOLATE_SETTINGS
from pywr_editor.toolbar.run_controls.run_widget import RunWidget

# do not write the results of the run next to the test model
Settings.default_save_results = False
app = QApplication([])
window = MainWindow(sys.argv[1])
window.hide()
run_widget = window.findChild(RunWidget)
run_widget.run_button.click()
worker = run_widget.worker
# the work a worker can still do once it has reported it finished. This slot runs in
# the worker thread, after the run widget has been told that the run is done
worker.finished.connect(lambda: time.sleep(0.5), Qt.ConnectionType.DirectConnection)

deadline = time.time() + 20
while time.time() < deadline and run_widget.is_running:
    QCoreApplication.processEvents()
    time.sleep(0.01)
# keep handling events (this delivers the deferred delete of the thread) until the
# worker thread has really ended
end = time.time() + 2
while time.time() < end:
    QCoreApplication.processEvents()
    # the deferred deletes are delivered here, as processEvents() leaves them if it is
    # not called from the event loop
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    time.sleep(0.01)
window.model_config.reset_change_flag()
print("finished cleanly")
""".replace("ISOLATE_SETTINGS", ISOLATE_SETTINGS)


def test_thread_is_not_deleted_while_the_worker_is_still_running(tmp_path):
    """
    Tests that the run widget does not delete its thread as soon as the worker reports
    it finished: the worker can still be in the thread (Qt aborts the application with
    "QThread: Destroyed while thread is still running"). The thread must be deleted
    when it has really ended. This runs in a separate process as a failure aborts it.
    """
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT, resolve_model_path("model_to_run.json")],
        cwd=ROOT,
        env=child_process_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout + result.stderr
    assert "Destroyed while thread is still running" not in output, output[-2000:]
    assert result.returncode == 0, output[-2000:]
    assert "finished cleanly" in result.stdout
    # the settings of the editor were written in the temporary folder
    assert list((tmp_path / "settings").rglob("*.ini"))
