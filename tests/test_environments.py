import os
import stat
import sys
import textwrap
from pathlib import Path

import pytest

from pywr_editor.dialogs.environments.install_dialog import InstallEnvironmentDialog
from pywr_editor.environments import (
    ENVS_DIR_VARIABLE,
    PywrEnvironment,
    envs_root,
    find_uv,
    installed_environments,
    pinned_pywr_next_version,
    pywr_next_environment,
)


def test_envs_root(monkeypatch, tmp_path):
    """
    Tests that the environments are in the user data folder, unless overridden.
    """
    monkeypatch.delenv(ENVS_DIR_VARIABLE, raising=False)
    assert envs_root().parts[-2:] == ("pywr-editor", "envs")
    monkeypatch.setenv(ENVS_DIR_VARIABLE, str(tmp_path))
    assert envs_root() == tmp_path


def test_pinned_version_matches_schema():
    """
    Tests that the installed pywr-next version is the one of the bundled schema.
    """
    assert pinned_pywr_next_version().startswith("2.")
    assert pywr_next_environment().pywr_version == pinned_pywr_next_version()


def test_environment(tmp_path):
    environment = PywrEnvironment("2.0.0rc1", tmp_path)
    assert environment.path == tmp_path / "pywr-2.0.0rc1"
    assert environment.is_installed() is False
    commands = environment.install_commands("uv")
    assert commands[0][:2] == ["uv", "venv"]
    assert commands[1][-1] == "pywr[pandas,excel]==2.0.0rc1"

    # installed: the interpreter exists and the marker is written
    environment.python.parent.mkdir(parents=True)
    environment.python.touch()
    assert environment.is_installed() is False
    environment.mark_installed()
    assert environment.is_installed() is True
    assert installed_environments(tmp_path) == [environment]

    environment.remove()
    assert installed_environments(tmp_path) == []


def test_find_uv(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert find_uv() is None or Path(find_uv()).parent != tmp_path
    uv = tmp_path / ("uv.exe" if sys.platform == "win32" else "uv")
    uv.write_text("")
    uv.chmod(uv.stat().st_mode | stat.S_IEXEC)
    assert Path(find_uv()) == uv


def test_dialog_without_uv(qtbot, tmp_path, monkeypatch):
    """
    Tests that the dialog explains that uv is needed and does not install.
    """
    monkeypatch.setattr(
        "pywr_editor.dialogs.environments.install_dialog.find_uv", lambda: None
    )
    dialog = InstallEnvironmentDialog(PywrEnvironment("2.0.0rc1", tmp_path))
    qtbot.addWidget(dialog)
    assert "uv was not found" in dialog.message.text()
    assert dialog.install_button.isEnabled() is False
    assert dialog.location.text() == str(tmp_path / "pywr-2.0.0rc1")


@pytest.mark.skipif(sys.platform == "win32", reason="the fake uv is a script")
def test_install_and_remove(qtbot, tmp_path):
    """
    Tests the installation with a fake uv, which creates the environment folder.
    """
    fake_uv = tmp_path / "uv"
    fake_uv.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import sys
            from pathlib import Path
            if sys.argv[1] == "venv":
                python = Path(sys.argv[-1]) / "bin" / "python"
                python.parent.mkdir(parents=True)
                python.touch()
            print("ran", " ".join(sys.argv[1:]))
            """
        )
    )
    fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IEXEC)
    environment = PywrEnvironment("2.0.0rc1", tmp_path / "envs")
    dialog = InstallEnvironmentDialog(environment, uv=str(fake_uv))
    qtbot.addWidget(dialog)
    assert "Install it now?" in dialog.message.text()

    dialog.install()
    qtbot.waitUntil(environment.is_installed, timeout=20000)
    assert "was installed in" in dialog.output.toPlainText()
    assert "pip install" in dialog.output.toPlainText()
    assert "is installed" in dialog.message.text()

    dialog.remove()
    assert not environment.path.exists()
    assert dialog.install_button.isVisible() or not dialog.isVisible()


@pytest.mark.skipif(sys.platform == "win32", reason="the fake uv is a script")
def test_failed_install(qtbot, tmp_path):
    fake_uv = tmp_path / "uv"
    fake_uv.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(2)\n")
    fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IEXEC)
    environment = PywrEnvironment("2.0.0rc1", tmp_path / "envs")
    dialog = InstallEnvironmentDialog(environment, uv=str(fake_uv))
    qtbot.addWidget(dialog)
    dialog.install()
    qtbot.waitUntil(lambda: dialog.install_button.isEnabled(), timeout=20000)
    assert "failed" in dialog.output.toPlainText()
    assert environment.is_installed() is False
    assert os.path.isdir(tmp_path / "envs")


def test_settings_button(qtbot, monkeypatch, tmp_path):
    """
    Tests that the settings open the dialog of the pywr-next environment.
    """
    from pywr_editor import MainWindow
    from tests.utils import resolve_model_path

    monkeypatch.setenv(ENVS_DIR_VARIABLE, str(tmp_path))
    window = MainWindow(resolve_model_path("model_1.json"))
    window.hide()
    window.app_actions.get("manage-pywr-next").trigger()
    dialogs = [
        d for d in window.findChildren(InstallEnvironmentDialog) if d.isVisible()
    ]
    assert len(dialogs) == 1
    assert dialogs[0].location.text().startswith(str(tmp_path))
    dialogs[0].close()
    window.close()
