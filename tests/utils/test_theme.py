import pytest

from pywr_editor.style import Color, Theme
from pywr_editor.style.theme import SHADE_MIRROR
from pywr_editor.utils import Settings


@pytest.fixture(autouse=True)
def reset_theme():
    """
    Restores the light theme after each test.
    """
    Theme.set_mode("light")
    yield
    Theme.set_mode("light")


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
