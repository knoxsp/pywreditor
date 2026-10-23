import pytest
from PySide6.QtWidgets import QApplication

from pywr_editor.main_window import MainWindow


@pytest.fixture(autouse=True)
def stop_run_threads():
    """
    Stops the threads of the runs started by a test. A thread still running when the
    interpreter exits aborts the process ("QThread: Destroyed while thread is still
    running"), which fails the test run even if all the tests passed.
    """
    yield
    for window in QApplication.topLevelWidgets():
        if not isinstance(window, MainWindow):
            continue
        try:
            run_widget = window.run_widget
            if run_widget.worker is not None:
                run_widget.worker.kill()
            if run_widget.thread is not None:
                run_widget.thread.quit()
                run_widget.thread.wait(10000)
        except RuntimeError:
            # the Qt object was already deleted
            pass
