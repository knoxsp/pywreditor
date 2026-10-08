import time
from pathlib import Path

import pytest

from pywr_editor.utils import Settings


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
