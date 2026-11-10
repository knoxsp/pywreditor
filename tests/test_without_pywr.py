import os
import subprocess
import sys
import textwrap
from pathlib import Path

from tests.utils import ISOLATE_SETTINGS, child_process_env, resolve_model_path

SCRIPT = (
    textwrap.dedent(
    """
    import sys
    from importlib.abc import MetaPathFinder


    class BlockPywr(MetaPathFinder):
        # make "import pywr" fail as if pywr were not installed
        def find_spec(self, name, path=None, target=None):
            if name == "pywr" or name.startswith("pywr."):
                raise ImportError(f"No module named {name!r}")
            return None


    sys.meta_path.insert(0, BlockPywr())

    ISOLATE_SETTINGS

    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    from pywr_editor import MainWindow
    from pywr_editor.dialogs.about_dialog.about_dialog import AboutDialog

    window = MainWindow(sys.argv[1])
    AboutDialog(window)
    assert "pywr" not in sys.modules
    window.close()
    print("ok")
    """
    ).replace("ISOLATE_SETTINGS", ISOLATE_SETTINGS)
)


def test_editor_starts_without_pywr(tmp_path):
    """
    Opens a model with pywr made unimportable. pywr v1 and pywr-next install a package
    with the same name, so the editor must work without either of them.
    """
    env = child_process_env(tmp_path)
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT, resolve_model_path("model_1.json")],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")
    # the settings of the editor were written in the temporary folder
    assert list((tmp_path / "settings").rglob("*.ini"))
