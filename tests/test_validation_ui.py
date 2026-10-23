import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from pywr_editor.dialogs import ValidationDialog
from pywr_editor.main_window import MainWindow
from tests.utils import resolve_model_path


@pytest.fixture
def window(qtbot):
    window = MainWindow(resolve_model_path("model_1.json"))
    window.hide()
    return window


def test_validation_dialog_lists_diagnostics(qtbot, window):
    window.app_actions.get("validate-model").trigger()
    dialog = window.validation_dialog
    assert isinstance(dialog, ValidationDialog)
    qtbot.waitUntil(lambda: not dialog.is_validating, timeout=30000)
    assert dialog.table.rowCount() == len(dialog.diagnostics) > 0
    assert dialog.error_count == 0

    dialog.show_warnings.setChecked(False)
    assert dialog.table.rowCount() == 0
    dialog.show_warnings.setChecked(True)
    assert dialog.table.rowCount() == len(dialog.diagnostics)

    # the same dialog is reused
    window.app_actions.get("validate-model").trigger()
    assert window.validation_dialog is dialog
    qtbot.waitUntil(lambda: not dialog.is_validating, timeout=30000)
    dialog.close()


def test_row_selects_node(qtbot, window):
    window.model_config.json["edges"].append(["Reservoir", "Missing"])
    window.app_actions.get("validate-model").trigger()
    dialog = window.validation_dialog
    qtbot.waitUntil(lambda: not dialog.is_validating, timeout=30000)
    row = next(
        r
        for r in range(dialog.table.rowCount())
        if "Missing" in dialog.table.item(r, 1).text()
    )
    assert dialog.table.item(row, 0).text() == "Error"
    # an edge is not a component
    assert dialog.table.item(row, 0).data(Qt.ItemDataRole.UserRole) is None

    window.show_component("node", "Reservoir")
    selected = [i for i in window.schematic.scene.selectedItems()]
    assert [getattr(i, "name", None) for i in selected] == ["Reservoir"]
    dialog.close()


def test_preflight_loads_model(qtbot, window):
    window.app_actions.get("validate-model").trigger()
    dialog = window.validation_dialog
    qtbot.waitUntil(lambda: not dialog.is_validating, timeout=30000)
    dialog.run_preflight()
    assert dialog.is_checking
    qtbot.waitUntil(lambda: not dialog.is_checking, timeout=60000)
    text = dialog.preflight_output.toPlainText()
    assert text  # either loaded or the pywr error, never empty
    dialog.close()


def test_run_is_blocked_by_model_errors(qtbot, window, monkeypatch):
    window.model_config.json["edges"].append(["Reservoir", "Missing"])
    shown = []

    def fake_exec(self):
        shown.append(self.informativeText())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: None)
    assert window.run_widget.confirm_validation() is False
    assert "Missing" in shown[0]


def test_run_is_not_blocked_by_warnings(qtbot, window, monkeypatch):
    # model_1.json has warnings only (missing files, orphans)
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: pytest.fail("No message expected")
    )
    assert window.run_widget.confirm_validation() is True
