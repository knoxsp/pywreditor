import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from pywr_editor.dialogs import TablesDialog
from pywr_editor.dialogs.tables.tree_reload import reload_tree_later
from pywr_editor.model import ModelConfig
from tests.utils import resolve_model_path


class FakeStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, text):
        self.messages.append(text)


class FakeTree:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def reload(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")


class FakeApp:
    """Stands in for the main window as the dialog parent's API."""

    def __init__(self, tree=None):
        self.components_tree = tree if tree is not None else FakeTree()
        self._bar = FakeStatusBar()

    def statusBar(self):
        return self._bar


def run_pending(qtbot):
    QCoreApplication.processEvents()
    qtbot.wait(20)


@pytest.fixture(autouse=True)
def no_modal_boxes(monkeypatch):
    """A real message box would block the test run waiting for a click."""
    from PySide6.QtWidgets import QMessageBox

    for kind in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(
            QMessageBox,
            kind,
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
        )


@pytest.fixture(autouse=True)
def no_leftover_cursor():
    yield
    while QApplication.overrideCursor() is not None:
        QApplication.restoreOverrideCursor()


class TestReloadTreeLater:
    def test_none_and_app_without_tree_are_noops(self, qtbot):
        reload_tree_later(None)
        reload_tree_later(object())
        assert QApplication.overrideCursor() is None

    def test_reload_is_deferred_with_busy_cursor(self, qtbot):
        app = FakeApp()
        reload_tree_later(app)
        assert app.components_tree.calls == 0  # not blocking the caller
        assert QApplication.overrideCursor() is not None
        run_pending(qtbot)
        assert app.components_tree.calls == 1
        assert QApplication.overrideCursor() is None

    def test_cursor_restored_when_reload_fails(self, qtbot):
        app = FakeApp(FakeTree(fail=True))
        reload_tree_later(app)
        # the exception surfaces in the event loop, as it did before
        with qtbot.captureExceptions() as exceptions:
            run_pending(qtbot)
        assert len(exceptions) == 1
        assert QApplication.overrideCursor() is None

    def test_two_requests_nest_and_restore_cleanly(self, qtbot):
        app = FakeApp()
        reload_tree_later(app)
        reload_tree_later(app)
        run_pending(qtbot)
        assert app.components_tree.calls == 2
        assert QApplication.overrideCursor() is None


class TestDialogUsesDeferredReload:
    def make(self, qtbot, tmp_path):
        import shutil

        file = tmp_path / "m.json"
        shutil.copy(resolve_model_path("model_tables.json"), file)
        app = FakeApp()
        dialog = TablesDialog(ModelConfig(str(file)))
        dialog.app = app  # the real parent is a QWidget: use the fake API
        qtbot.addWidget(dialog)
        return dialog, app

    def test_add_table_shows_page_before_reloading(self, qtbot, tmp_path):
        dialog, app = self.make(qtbot, tmp_path)
        dialog.add_table()
        # page, list entry and status are updated straight away...
        assert dialog.pages.currentWidget().name in dialog.list_model.table_names
        assert app.statusBar().messages[-1].startswith("Added new table")
        # ...the slow tree rebuild happens afterwards
        assert app.components_tree.calls == 0
        run_pending(qtbot)
        assert app.components_tree.calls == 1

    def test_saving_a_table_page_reloads_later(self, qtbot, tmp_path):
        (tmp_path / "t.csv").write_text("a,b\n1,2\n")
        dialog, app = self.make(qtbot, tmp_path)
        dialog.add_table()
        run_pending(qtbot)
        app.components_tree.calls = 0
        page = dialog.pages.currentWidget()
        page.form.load_fields()
        page.form.find_field("url").widget.line_edit.setText("t.csv")
        page.on_save_table()
        assert dialog.model.tables.config(page.name)["url"] == "t.csv"
        assert app.components_tree.calls == 0  # not blocking the Save click
        assert app.statusBar().messages[-1].endswith("updated")
        run_pending(qtbot)
        assert app.components_tree.calls == 1

    def test_delete_table_reloads_later(self, qtbot, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        dialog, app = self.make(qtbot, tmp_path)
        dialog.add_table()
        run_pending(qtbot)
        app.components_tree.calls = 0
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
        )
        page = dialog.pages.currentWidget()
        page.on_delete_table()
        assert app.components_tree.calls == 0
        run_pending(qtbot)
        assert app.components_tree.calls == 1
