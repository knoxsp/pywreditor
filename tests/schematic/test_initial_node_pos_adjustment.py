import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pywr_editor import MainWindow
from pywr_editor.schematic import SchematicItemUtils
from tests.utils import resolve_model_path


class TestInitialWrongPosition:
    model_file = resolve_model_path("wrong_initial_pos_model_1.json")
    dialog_text = None

    @pytest.fixture
    def window(self) -> MainWindow:
        """
        Initialises the window.
        :return: The window instance.
        """
        QTimer.singleShot(100, self.get_warning_message)
        window = MainWindow(self.model_file)
        window.hide()

        return window

    def get_warning_message(self) -> None:
        """
        Saves the text in the warning message, if one was shown.
        :return: None
        """
        widget = QApplication.activeModalWidget()
        if widget is not None:
            self.dialog_text = widget.text()
            widget.close()

    def test_node_outside_left_edge(self, qtbot, window):
        """
        Tests that the canvas is unbounded: a node initially positioned outside the
        schematic bounds keeps its stored position (it is not snapped back onto the
        canvas) and no warning is shown to the user.
        """
        schematic = window.schematic

        item = schematic.node_items["Link"]
        item_utils = SchematicItemUtils(
            item=item,
            schematic_size=[
                schematic.schematic_width,
                schematic.schematic_height,
            ],
        )
        assert item_utils.is_outside_left_edge is True

        item = schematic.node_items["Output"]
        item_utils = SchematicItemUtils(
            item=item,
            schematic_size=[
                schematic.schematic_width,
                schematic.schematic_height,
            ],
        )
        assert item_utils.is_outside_bottom_edge is True

        # no warning is shown, since the canvas has no hard bounds to enforce
        assert self.dialog_text is None
