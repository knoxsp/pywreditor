import pytest

from pywr_editor.main_window import MainWindow
from pywr_editor.style import Theme
from pywr_editor.toolbar import AppearanceSettings
from pywr_editor.utils import Settings
from tests.utils import resolve_model_path


@pytest.fixture
def restore_theme():
    settings = Settings()
    previous = settings.theme
    yield
    settings.save_theme(previous)
    Theme.preference = "light"
    Theme.apply_mode("light")


def test_theme_is_chosen_in_the_settings_tab(qtbot, restore_theme):
    Settings().save_theme("system")
    window = MainWindow(resolve_model_path("model_1.json"))
    window.hide()

    # not in the model tab anymore
    with pytest.raises(KeyError):
        window.app_actions.get("toggle-dark-mode")

    widget = window.toolbar.findChild(AppearanceSettings)
    assert [widget.theme.itemText(i) for i in range(widget.theme.count())] == [
        "System",
        "Light",
        "Dark",
    ]
    assert widget.theme.currentText() == "System"

    widget.theme.setCurrentText("Dark")
    assert Theme.is_dark()
    assert Settings().theme == "dark"

    widget.theme.setCurrentText("Light")
    assert not Theme.is_dark()
    assert Settings().theme == "light"

    widget.theme.setCurrentText("System")
    assert Settings().theme == "system"
    assert Theme.preference == "system"
