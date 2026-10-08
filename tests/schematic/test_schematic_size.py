from typing import Literal, Tuple

import pytest
from PySide6.QtCore import Qt

from pywr_editor import MainWindow
from pywr_editor.schematic import Schematic
from pywr_editor.toolbar.base_button import ToolbarBaseButton
from pywr_editor.toolbar.tab_panel import TabPanel
from tests.utils import resolve_model_path


class TestSchematicResize:
    model_file = resolve_model_path("model_1.json")

    @pytest.fixture
    def init_window(self) -> Tuple[MainWindow, Schematic, TabPanel]:
        """
        Initialises the window.
        :return: A tuple with the window, schematic and tab panel instances.
        """
        # QTimer.singleShot(100, close_message_box)
        window = MainWindow(self.model_file)
        window.hide()
        schematic = window.schematic
        size_panel = window.toolbar.tabs["Schematic"].panels["Size"]

        return window, schematic, size_panel

    @pytest.fixture
    def resize(
        self,
        qtbot,
        init_window,
        action: Literal[
            "increase-width",
            "decrease-width",
            "increase-height",
            "decrease-height",
        ],
        n: int,
    ) -> Tuple[float, float, ToolbarBaseButton]:
        """
        Resize the schematic.
        :param qtbot: The QT bot fixture.
        :param init_window: The init_window fixture.
        :param action: The action in the editor.
        :param n: Resize the schematic n times.
        :return: A tuple containing the expected schematic size, its measured size and
        the clicked button .
        """
        window, schematic, size_panel = init_window

        if "width" in action:
            attr = "schematic_width"
        else:
            attr = "schematic_height"
        delta = schematic.max_view_size_delta * n
        if "decrease" in action:
            delta = -delta

        expected = getattr(schematic, attr) + delta
        button = size_panel.buttons[window.app_actions.get(action).text()]
        for _ in range(0, n):
            qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
        measured = getattr(schematic, attr)

        return expected, measured, button

    @pytest.fixture
    def minimise(self, qtbot, init_window) -> ToolbarBaseButton:
        """
        Resize the schematic.
        :param qtbot: The QT bot fixture.
        :param init_window: The init_window fixture.
        :return: The clicked button instance.
        """
        window, schematic, size_panel = init_window
        button = size_panel.buttons[window.app_actions.get("minimise").text()]
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

        return button

    @pytest.mark.parametrize(
        "action, n",
        [
            ("increase-width", 1),
            ("decrease-width", 1),
            ("increase-height", 1),
            ("decrease-height", 1),
        ],
    )
    def test_schematic_resize(self, qtbot, resize, action, n) -> None:
        """
        Tests that the schematic resizes as expected when the resize buttons are
        pressed.
        """
        expected, measured, _ = resize
        assert expected == measured

    @pytest.mark.parametrize(
        "action, n",
        [("decrease-width", 20), ("decrease-height", 25)],
    )
    def test_decrease_button_not_limited_by_items(
        self, qtbot, resize, init_window, action, n
    ) -> None:
        """
        Tests that decreasing the schematic size repeatedly is not limited by
        where nodes/shapes are (the bounds outline is purely cosmetic and does
        not constrain item positions), and that the button stays enabled, as
        there is no hard limit to disable it for.
        """
        _, _, size_panel = init_window
        expected, measured, button = resize

        assert expected == measured
        assert button.isEnabled() is True

    @pytest.mark.parametrize(
        "action, n",
        [("decrease-width", 100), ("decrease-height", 100)],
    )
    def test_decrease_button_floor(
        self, qtbot, resize, init_window, action, n
    ) -> None:
        """
        Tests that decreasing the schematic size repeatedly stops at a minimum
        floor (max_view_size_delta), and that the button stays enabled at that
        floor.
        """
        _, schematic, _ = init_window
        _, measured, button = resize

        assert measured == schematic.max_view_size_delta
        assert button.isEnabled() is True

    def test_minimise_button(self, qtbot, minimise, init_window) -> None:
        """
        Tests that the minimise button shrinks the bounds outline to tightly wrap
        the schematic items, without affecting button enabled state (the outline
        is purely cosmetic and does not constrain item positions).
        """
        window, schematic, tab_panel = init_window
        _ = minimise
        item = schematic.shape_items["466eaX"]

        rect = item.mapRectToScene(item.boundingRect())
        expected_width = rect.x() + rect.width()

        rect = item.mapRectToScene(item.boundingRect())
        expected_height = rect.y() + rect.height()

        assert (
            tab_panel.buttons[
                window.app_actions.get("decrease-width").text()
            ].isEnabled()
            is True
            and tab_panel.buttons[
                window.app_actions.get("decrease-height").text()
            ].isEnabled()
            is True
            and schematic.schematic_width == expected_width
            and schematic.schematic_height == expected_height
        )
