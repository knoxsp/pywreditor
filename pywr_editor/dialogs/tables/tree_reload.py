from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication


def reload_tree_later(app: Any) -> None:
    """
    Reloads the components tree of the main window after the pending events have
    been processed, with a busy cursor. Rebuilding the tree takes seconds on a large
    model: doing it later lets the dialog show its new page before the UI blocks.
    :param app: The main window (or None, when the dialog has no parent).
    :return: None
    """
    tree = getattr(app, "components_tree", None)
    if tree is None:
        return

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def reload() -> None:
        try:
            tree.reload()
        finally:
            QApplication.restoreOverrideCursor()

    QTimer.singleShot(0, reload)
