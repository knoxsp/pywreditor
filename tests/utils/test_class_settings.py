import os

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from pywr_editor import MainWindow
from tests.utils import model_path, resolve_model_path


class TestSettings:
    @staticmethod
    def window(file: str | None = None) -> MainWindow:
        """
        Initialises the window.
        :param file: The model configuration file.
        :return: The window instance.
        """
        if file is None:
            window = MainWindow(None)
        else:
            window = MainWindow(resolve_model_path(file))
        window.hide()

        return window

    @pytest.mark.skipif(
        os.environ.get("QT_QPA_PLATFORM") == "offscreen",
        reason="the offscreen platform does not place windows at the requested "
        "position",
    )
    def test_save_widget_geometry(self, qtbot):
        """
        Tests that the window geometry is saved and restored.
        """
        window = self.window("model_1.json")
        config = window.editor_settings
        assert config.json_file is not None

        # set new geometry, save it and restore it. The window manager may move or
        # resize the window (the screen is small on CI machines), so the geometry
        # that is restored is the one the window had when it was saved
        window.setGeometry(30, 30, 1200, 806)
        QApplication.processEvents()
        saved_geometry = window.geometry()
        config.save_window_attributes(window)
        window.setGeometry(100, 100, 700, 500)
        config.restore_window_attributes(window)

        assert window.geometry() == saved_geometry

    def test_save_data_no_file(self, qtbot):
        """
        Tests that the schematic properties (such as zoom, hide labels, etc.) are not
        saved if the model file is not provided.
        """
        window = self.window()
        config = window.editor_settings
        assert config.json_file is None

        config.save_hide_arrows(True)
        assert config.are_edge_arrows_hidden is False

        config.save_hide_labels(True)
        assert config.are_labels_hidden is False

        config.save_zoom_level(200)
        assert config.zoom_level == 1

        config.save_schematic_lock(True)
        assert config.is_schematic_locked is False

        config.save_schematic_center(QPointF(200, 100))
        assert config.schematic_center is None

    def test_recent_file(self, qtbot):
        """
        Tests the recent file list.
        """
        window = self.window()

        # store original list
        config = window.editor_settings
        or_list = [file_dict["file"] for file_dict in config.get_recent_files()]

        # clear list
        config.clear_recent_files()
        assert config.get_recent_files() == []

        # store first three test files
        all_test_models = sorted(model_path().glob("*.json"))
        files_to_check = []
        for mi in range(1, 4):
            model_file = str(all_test_models[mi])
            config.save_recent_file(model_file)
            files_to_check.append(model_file)

        # check stored files
        file_names = [f["file"] for f in config.get_recent_files()]
        assert file_names == files_to_check

        # try inserting invalid JSON
        config.save_recent_file(str(all_test_models[0]))
        # list did not change
        assert len(config.get_recent_files()) == 3

        # try non-existing file
        config.save_recent_file("wrong_path.json")
        # list did not change
        assert len(config.get_recent_files()) == 3

        # restore
        config.clear_recent_files()
        config.instance.setValue(config.recent_projects_key, or_list)
