import pytest
from PySide6.QtWidgets import QApplication, QDialog


@pytest.fixture(autouse=True)
def hide_leftover_dialogs():
    """
    Hides the dialogs a test shows and does not close. The dialog is a cycle of Python
    objects, which Python deletes later and, when it does, clears the model of the
    dialog while the Qt window can still receive events (e.g. the show event when
    another test processes events): this fails with an "AttributeError" in a test that
    has nothing to do with the dialog.
    """
    yield
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        if isinstance(widget, QDialog) and widget.isVisible():
            widget.hide()
