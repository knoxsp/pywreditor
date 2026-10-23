import shutil
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from pywr_editor.schematic.map import TileCache, TileFetcher
from pywr_editor.utils import Settings
from tests.fake_network import FakeNetwork


@pytest.fixture(scope="session", autouse=True)
def isolated_editor_settings(tmp_path_factory):
    """
    Stores the editor settings in a temporary folder for the whole test session, so
    the tests never add their models to the real "recent files" list or leave
    per-model settings files in the user's configuration folder.
    """
    root = str(tmp_path_factory.mktemp("qsettings"))
    # the native format is the registry on Windows and a property list on macOS, which
    # setPath() does not redirect. Use ini files everywhere
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
            QSettings.setPath(fmt, scope, root)
    yield root
    QSettings.setDefaultFormat(QSettings.Format.NativeFormat)
    # pytest keeps the last few base temporary folders: remove the settings now
    shutil.rmtree(root, ignore_errors=True)


def clean_env(model_file: str) -> None:
    """
    Removes the editor settings.
    :param model_file: The model file.
    :return: None
    """
    editor_settings = Settings(model_file)
    editor_settings.instance.clear()
    editor_settings.instance.sync()


def clean_recent_files() -> None:
    """
    Removes any test model paths that tests have added to the real, global
    "recent files" list (this list is not scoped per model file, unlike the rest
    of the editor settings, so running the test suite would otherwise pollute
    the user's real recent-files list indefinitely).
    :return: None
    """
    editor_settings = Settings()
    tests_dir = str(Path(__file__).parent)
    recent_files = editor_settings._get_recent_files_list()
    kept_files = [f for f in recent_files if not f.startswith(tests_dir)]
    if kept_files != recent_files:
        editor_settings.global_instance.setValue(
            editor_settings.recent_projects_key, kept_files
        )
        editor_settings.global_instance.sync()


@pytest.fixture(autouse=True)
def offline_map_tiles(monkeypatch, tmp_path_factory):
    """
    Prevents the tests from downloading OSM tiles, which must not be requested by
    automated runs, and from writing to the real tile cache.
    """
    monkeypatch.setattr(TileFetcher, "network_factory", FakeNetwork)
    monkeypatch.setattr(
        TileCache, "default_root", tmp_path_factory.getbasetemp() / "osm_tiles"
    )


def pytest_sessionfinish(session):
    """
    Cleans the editor settings after a test.
    """
    for item in session.items:
        cls = item.getparent(pytest.Class)
        if cls is not None and hasattr(cls, "obj") and hasattr(cls.obj, "model_file"):
            clean_env(cls.obj.model_file)

    clean_recent_files()

    # Removed the dynamic table file created by one test. If one test fails the
    # file is not deleted.
    dynamic_file = Path("test/models/files/table_missing.csv")
    if dynamic_file.exists():
        dynamic_file.unlink()

    # remove solved debug files
    [f.unlink() for f in Path(__file__).parent.glob("*/*.lp")]
    [f.unlink() for f in Path(__file__).parent.glob("*/*.mps")]


@pytest.fixture(scope="class")
def delay() -> None:
    """
    Fixture to delay a test.
    :return: None
    """
    time.sleep(1)


@pytest.fixture(autouse=True)
def do_not_save_run_results(monkeypatch):
    """
    Runs do not write an "outputs" folder next to the test models, unless a test
    turns the setting on explicitly.
    """
    monkeypatch.setattr(Settings, "default_save_results", False)
