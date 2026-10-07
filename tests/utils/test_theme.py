import pytest
import shiboken6

from pywr_editor.style import Color, Theme
from pywr_editor.style.theme import SHADE_MIRROR
from pywr_editor.utils import Settings


@pytest.fixture(autouse=True)
def reset_theme():
    """
    Restores the light theme after each test.
    """
    Theme.apply_mode("light")
    yield
    Theme.apply_mode("light")


class TestTheme:
    def test_light_is_default(self):
        assert not Theme.is_dark()
        assert Color("gray", 100).hex == Color.colors["gray"][100]
        assert Theme.color("base") == "#FFFFFF"
        assert Theme.overlay(5) == "rgba(0, 0, 0, 5)"

    def test_dark_mirrors_shades(self):
        Theme.set_mode("dark")
        assert Theme.is_dark()
        assert Color("gray", 100).hex == Color.colors["gray"][800]
        assert Color("blue", 500).hex == Color.colors["blue"][400]
        assert Color("gray", 80).hex == Color.colors["gray"][800]
        assert Theme.color("base") == "#111827"
        assert Theme.overlay(5) == "rgba(255, 255, 255, 5)"

    def test_unthemed_color_is_unchanged(self):
        Theme.set_mode("dark")
        assert Color("red", 500, themed=False).hex == Color.colors["red"][500]
        assert Color("red", 500, themed=False).change_shade(100).hex == (
            Color.colors["red"][100]
        )

    def test_unknown_mode_falls_back_to_light(self):
        Theme.set_mode("purple")
        assert not Theme.is_dark()

    def test_every_shade_has_a_mirror(self):
        for name, shades in Color.colors.items():
            for shade in shades:
                assert SHADE_MIRROR[shade] in shades, (name, shade)

    @pytest.mark.parametrize("mode", ["light", "dark"])
    def test_palette(self, mode):
        Theme.set_mode(mode)
        window = Theme.palette().color(Theme.palette().ColorRole.Window)
        assert window.name() == Theme.color("window").lower()

    def test_saved_theme(self, tmp_path):
        settings = Settings()
        previous = settings.theme
        try:
            settings.save_theme("dark")
            assert settings.theme == "dark"
            settings.save_theme("nonsense")
            assert settings.theme == "light"
        finally:
            settings.save_theme(previous)


class TestLiveTheme:
    def test_bound_stylesheet_is_rebuilt(self, qtbot):
        from PySide6.QtWidgets import QWidget

        widget = QWidget()
        qtbot.addWidget(widget)
        Theme.bind(widget, lambda w: f"background: {Color('gray', 100).hex};")
        assert Color.colors["gray"][100] in widget.styleSheet()

        Theme.apply_mode("dark")
        assert Color.colors["gray"][800] in widget.styleSheet()
        Theme.apply_mode("light")
        assert Color.colors["gray"][100] in widget.styleSheet()

    def test_on_change_callback_and_signal(self, qtbot):
        from PySide6.QtWidgets import QWidget

        widget = QWidget()
        qtbot.addWidget(widget)
        calls = []
        Theme.on_change(widget, lambda w: calls.append(Theme.mode))

        with qtbot.waitSignal(Theme.signals.changed):
            Theme.apply_mode("dark")
        assert calls == ["dark"]

    def test_destroyed_widget_is_dropped(self, qtbot):
        from PySide6.QtWidgets import QWidget

        widget = QWidget()
        key = id(widget)
        Theme.bind(widget, lambda w: "")
        assert key in Theme._stylesheets
        widget.deleteLater()
        qtbot.waitUntil(lambda: not shiboken6.isValid(widget))
        Theme.prune()
        assert key not in Theme._stylesheets

    def test_icon_is_recoloured_in_dark_theme(self, qtbot, monkeypatch):
        from pywr_editor.style import icons

        # the caret icon is filled with #6b7280
        monkeypatch.setitem(icons.DARK_SVG_COLORS, "*", {"#6b7280": "#ff0000"})

        def dominant_color(icon) -> str:
            image = icon.pixmap(16, 16).toImage()
            return image.pixelColor(8, 8).name()

        light = dominant_color(icons.themed_icon(":form/caret-down"))
        Theme.apply_mode("dark")
        dark = dominant_color(icons.themed_icon(":form/caret-down"))
        assert light != dark
        assert dark == "#ff0000"

    def test_dark_icon_file_is_used(self, monkeypatch):
        from pywr_editor.style import icons

        monkeypatch.setitem(icons.DARK_ICONS, ":toolbar/open", ":toolbar/save")
        light = icons.themed_icon(":toolbar/open").pixmap(16, 16).toImage()
        Theme.apply_mode("dark")
        dark = icons.themed_icon(":toolbar/open").pixmap(16, 16).toImage()
        expected = icons.themed_icon(":toolbar/save").pixmap(16, 16).toImage()
        assert dark == expected
        assert light != dark

    def test_many_callbacks_per_widget(self, qtbot):
        from PySide6.QtWidgets import QWidget

        widget = QWidget()
        qtbot.addWidget(widget)
        calls = []
        Theme.on_change(widget, lambda w: calls.append("a"))
        Theme.on_change(widget, lambda w: calls.append("b"))
        Theme.apply_mode("dark")
        assert calls == ["a", "b"]
