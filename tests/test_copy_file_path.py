import os

from PySide6.QtGui import QGuiApplication

from pywr_editor.main_window import MainWindow
from tests.utils import resolve_model_path


def test_title_shows_folder_and_path_is_copied(qtbot):
    model_file = resolve_model_path("model_1.json")
    window = MainWindow(model_file)
    window.hide()

    folder = os.path.basename(os.path.dirname(os.path.abspath(model_file)))
    assert f"model_1.json ({folder})" in window.windowTitle()

    window.app_actions.get("copy-file-path").trigger()
    assert QGuiApplication.clipboard().text() == os.path.abspath(model_file)
