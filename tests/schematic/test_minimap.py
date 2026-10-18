import json

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtTest import QTest

from pywr_editor import MainWindow
from tests.utils import close_message_box, resolve_model_path


def open_window(tmp_path):
    with open(resolve_model_path("model_geographic_positions.json")) as fp:
        model = json.load(fp)
    path = tmp_path / "model.json"
    path.write_text(json.dumps(model))
    QTimer.singleShot(100, close_message_box)
    window = MainWindow(str(path))
    window.resize(1000, 700)
    window.show()
    return window


class TestMinimap:
    def test_shown_in_bottom_right_corner(self, qtbot, tmp_path):
        window = open_window(tmp_path)
        minimap = window.schematic.minimap
        viewport = window.schematic.viewport()
        assert minimap.isVisible()
        assert minimap.geometry().right() < viewport.width()
        assert minimap.geometry().bottom() < viewport.height()
        # nearer the bottom-right than the top-left
        assert minimap.x() > viewport.width() / 2
        assert minimap.y() > viewport.height() / 2

    def test_view_rectangle_is_inside_the_minimap_even_when_panned_away(
        self, qtbot, tmp_path
    ):
        window = open_window(tmp_path)
        schematic = window.schematic
        minimap = schematic.minimap
        schematic.centerOn(QPointF(1e6, 1e6))
        view = minimap.view_rect()
        minimap._fit(view)
        top_left = minimap.to_minimap(view.topLeft())
        bottom_right = minimap.to_minimap(view.bottomRight())
        assert 0 <= top_left.x() <= minimap.width()
        assert 0 <= bottom_right.y() <= minimap.height() + 1

    def test_click_moves_the_view(self, qtbot, tmp_path):
        window = open_window(tmp_path)
        schematic = window.schematic
        minimap = schematic.minimap
        minimap.repaint()
        before = minimap.view_rect().center()
        QTest.mouseClick(minimap, Qt.MouseButton.LeftButton, pos=QPointF(15, 15).toPoint())
        after = minimap.view_rect().center()
        assert (before - after).manhattanLength() > 1

    def test_optional_through_the_settings_tab(self, qtbot, tmp_path):
        from pywr_editor.toolbar import ModelNavigationSettings

        window = open_window(tmp_path)
        toggle = window.findChild(ModelNavigationSettings).minimap
        # shown by default
        assert toggle.isChecked()
        assert window.schematic.minimap.isVisible()

        toggle.setChecked(False)
        assert not window.schematic.minimap.isVisible()
        assert window.editor_settings.are_minimap_hidden

        toggle.setChecked(True)
        assert window.schematic.minimap.isVisible()
        assert not window.editor_settings.are_minimap_hidden
        window.editor_settings.instance.clear()

    def test_setting_is_restored_on_open(self, qtbot, tmp_path):
        window = open_window(tmp_path)
        window.schematic.set_minimap_visible(False)
        window.close()
        window2 = open_window(tmp_path)
        assert not window2.schematic.minimap.isVisible()
        window2.editor_settings.instance.clear()
