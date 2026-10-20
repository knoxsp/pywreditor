import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QPushButton

from pywr_editor.dialogs.tables.table_data_dialog import TableDataDialog

CTRL = Qt.KeyboardModifier.ControlModifier
SB = QMessageBox.StandardButton


@pytest.fixture()
def boxes(monkeypatch):
    """Records and answers the message boxes. Set boxes.answer for question()."""

    class Boxes:
        answer = SB.Cancel
        shown: list[tuple[str, str]] = []

    boxes = Boxes()
    boxes.shown = []

    def make(kind):
        def fake(parent, title, text, *args, **kwargs):
            boxes.shown.append((kind, text))
            return boxes.answer if kind == "question" else SB.Ok

        return fake

    for kind in ("question", "warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(make(kind)))
    return boxes


_OPEN: list[TableDataDialog] = []


@pytest.fixture(autouse=True)
def close_dialogs():
    """
    Closes the dialogs at the end of a test without the unsaved-changes prompt, which
    would otherwise block waiting for an answer in a test that left edits behind.
    """
    yield
    while _OPEN:
        dialog = _OPEN.pop()
        dialog.grid.undo_stack.setClean()
        dialog.close()
        dialog.deleteLater()


def make_dialog(qtbot, file, sep=",", name="My table") -> TableDataDialog:
    dialog = TableDataDialog(name, file, sep=sep)
    _OPEN.append(dialog)
    dialog.show()
    return dialog


def button(dialog, name: str) -> QPushButton:
    return dialog.findChild(QPushButton, name)


def set_clipboard(text: str) -> None:
    QGuiApplication.clipboard().setText(text)


class TestLoading:
    def test_new_file_starts_with_blank_grid(self, qtbot, tmp_path):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        assert dialog.grid.columnCount() == 5 and dialog.grid.rowCount() == 20
        assert dialog.grid.is_blank()
        assert dialog.grid.undo_stack.isClean()
        assert not (tmp_path / "t.csv").exists()  # nothing written until Save

    def test_new_file_view_has_cells_to_click(self, qtbot, tmp_path):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        assert dialog.view.model().rowCount() > 0
        assert dialog.view.model().columnCount() > 0
        assert dialog.view.currentIndex().isValid()

    def test_empty_file_starts_with_blank_grid(self, qtbot, tmp_path):
        file = tmp_path / "t.csv"
        file.write_text("")
        assert make_dialog(qtbot, file).grid.is_blank()

    def test_existing_file_is_loaded_as_text(self, qtbot, tmp_path):
        file = tmp_path / "t.csv"
        file.write_text("d,v\n01/02,1.50\n")
        dialog = make_dialog(qtbot, file)
        assert dialog.grid.headers == ["d", "v"]
        assert dialog.grid.rows == [["01/02", "1.50"]]
        assert dialog.grid.undo_stack.isClean()

    def test_header_only_file_is_not_replaced_by_blank_grid(self, qtbot, tmp_path):
        file = tmp_path / "t.csv"
        file.write_text("a,b\n")
        dialog = make_dialog(qtbot, file)
        assert dialog.grid.headers == ["a", "b"] and dialog.grid.rows == []

    def test_separator_is_used(self, qtbot, tmp_path):
        file = tmp_path / "t.csv"
        file.write_text("a;b\n1;2\n")
        assert make_dialog(qtbot, file, sep=";").grid.rows == [["1", "2"]]

    def test_shows_file_path_and_title(self, qtbot, tmp_path):
        dialog = make_dialog(qtbot, tmp_path / "t.csv", name="Flows")
        assert str(tmp_path / "t.csv") in dialog.path_label.text()
        assert dialog.windowTitle() == "Table data: Flows"

    def test_grid_has_focus(self, qtbot, tmp_path):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        qtbot.waitUntil(lambda: dialog.view.hasFocus() or dialog.focusWidget() is dialog.view)


class TestTitle:
    def test_star_appears_on_edit_and_clears_on_save(self, qtbot, tmp_path):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        dialog.grid.setData(dialog.grid.index(0, 0), "x")
        assert dialog.windowTitle().endswith("*")
        dialog.on_save()
        assert not dialog.windowTitle().endswith("*")

    def test_star_clears_when_undone_back_to_saved_state(self, qtbot, tmp_path):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        dialog.grid.setData(dialog.grid.index(0, 0), "x")
        dialog.grid.undo_stack.undo()
        assert not dialog.windowTitle().endswith("*")


class TestSave:
    def test_save_writes_trimmed_csv(self, qtbot, tmp_path):
        file = tmp_path / "sub" / "t.csv"
        dialog = make_dialog(qtbot, file)
        dialog.grid.set_block(0, 0, [["1", "2"]], headers=["a", "b"])
        dialog.on_save()
        assert file.read_text() == "a,b\n1,2\n"
        assert dialog.saved is True

    def test_save_button_click(self, qtbot, tmp_path):
        file = tmp_path / "t.csv"
        dialog = make_dialog(qtbot, file)
        dialog.grid.set_block(0, 0, [["1"]], headers=["a"])
        qtbot.mouseClick(button(dialog, "save_button"), Qt.MouseButton.LeftButton)
        assert file.read_text() == "a\n1\n"

    def test_save_uses_separator(self, qtbot, tmp_path):
        file = tmp_path / "t.csv"
        dialog = make_dialog(qtbot, file, sep=";")
        dialog.grid.set_block(0, 0, [["1", "2"]], headers=["a", "b"])
        dialog.on_save()
        assert file.read_text() == "a;b\n1;2\n"

    def test_saving_blank_grid_warns_and_writes_nothing(self, qtbot, tmp_path, boxes):
        file = tmp_path / "t.csv"
        dialog = make_dialog(qtbot, file)
        dialog.on_save()
        assert not file.exists() and dialog.saved is False
        assert boxes.shown and boxes.shown[0][0] == "warning"

    def test_saving_an_existing_file_blanked_out_does_not_erase_it(
        self, qtbot, tmp_path, boxes
    ):
        file = tmp_path / "t.csv"
        file.write_text("a,b\n1,2\n")
        dialog = make_dialog(qtbot, file)
        dialog.grid.remove_columns([0, 1])
        dialog.on_save()
        # an empty table is refused: the original file must be untouched
        assert dialog.saved is False
        assert file.read_text() == "a,b\n1,2\n"
        assert boxes.shown[0][0] == "warning"

    def test_save_error_is_reported_and_state_stays_dirty(
        self, qtbot, tmp_path, boxes
    ):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        dialog = make_dialog(qtbot, blocker / "t.csv")
        dialog.grid.set_block(0, 0, [["1"]], headers=["a"])
        dialog.on_save()
        assert dialog.saved is False
        assert boxes.shown[0][0] == "critical"
        assert not dialog.grid.undo_stack.isClean()

    def test_saved_flag_stays_true_after_later_failed_save(
        self, qtbot, tmp_path, boxes
    ):
        file = tmp_path / "t.csv"
        dialog = make_dialog(qtbot, file)
        dialog.grid.set_block(0, 0, [["1"]], headers=["a"])
        dialog.on_save()
        assert dialog.saved is True


class TestPasteButtons:
    def test_paste_button(self, qtbot, tmp_path):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        set_clipboard("1\t2\n3\t4")
        dialog.view.setCurrentIndex(dialog.grid.index(0, 0))
        qtbot.mouseClick(button(dialog, "paste_button"), Qt.MouseButton.LeftButton)
        assert dialog.grid.rows[0][:2] == ["1", "2"]
        assert dialog.grid.rows[1][:2] == ["3", "4"]

    def test_paste_with_header_button(self, qtbot, tmp_path):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        set_clipboard("Date\tFlow\n2020\t1.5")
        dialog.view.setCurrentIndex(dialog.grid.index(0, 0))
        qtbot.mouseClick(
            button(dialog, "paste_header_button"), Qt.MouseButton.LeftButton
        )
        assert dialog.grid.headers[:2] == ["Date", "Flow"]
        assert dialog.grid.rows[0][:2] == ["2020", "1.5"]

    def test_paste_button_without_selected_cell(self, qtbot, tmp_path):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        dialog.view.clearSelection()
        dialog.view.setCurrentIndex(dialog.grid.index(-1, -1))
        set_clipboard("9")
        qtbot.mouseClick(button(dialog, "paste_button"), Qt.MouseButton.LeftButton)
        assert dialog.grid.rows[0][0] == "9"

    def test_paste_then_ctrl_z_inside_dialog(self, qtbot, tmp_path):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        dialog.view.setFocus()
        dialog.view.setCurrentIndex(dialog.grid.index(0, 0))
        set_clipboard("1\t2\n3\t4")
        QTest.keyClick(dialog.view, Qt.Key.Key_V, CTRL)
        assert dialog.grid.rows[0][:2] == ["1", "2"]
        QTest.keyClick(dialog.view, Qt.Key.Key_Z, CTRL)
        assert dialog.grid.is_blank()
        assert dialog.isVisible()  # undo did not close or save anything
        assert not (tmp_path / "t.csv").exists()


class TestKeysDoNotTriggerButtons:
    """A dialog default button must never fire from the grid's keys."""

    @pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter])
    def test_return_on_a_cell_does_not_click_a_button(self, qtbot, tmp_path, key):
        file = tmp_path / "t.csv"
        dialog = make_dialog(qtbot, file)
        set_clipboard("clipboard value")
        dialog.view.setFocus()
        dialog.view.setCurrentIndex(dialog.grid.index(0, 0))
        QTest.keyClick(dialog.view, key)
        assert dialog.grid.is_blank()  # "Paste" was not triggered
        assert not file.exists() and dialog.saved is False
        assert dialog.isVisible()

    def test_no_button_is_a_default_button(self, qtbot, tmp_path):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        for b in dialog.findChildren(QPushButton):
            assert not b.autoDefault() and not b.isDefault(), b.text()


class TestClosing:
    def test_clean_close_does_not_prompt(self, qtbot, tmp_path, boxes):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        dialog.close()
        assert not dialog.isVisible() and boxes.shown == []

    def test_close_button(self, qtbot, tmp_path, boxes):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        close = [b for b in dialog.findChildren(QPushButton) if "Close" in b.text()][0]
        qtbot.mouseClick(close, Qt.MouseButton.LeftButton)
        assert not dialog.isVisible()

    def test_dirty_close_cancel_keeps_dialog_and_changes(self, qtbot, tmp_path, boxes):
        file = tmp_path / "t.csv"
        dialog = make_dialog(qtbot, file)
        dialog.grid.setData(dialog.grid.index(0, 0), "x")
        boxes.answer = SB.Cancel
        dialog.close()
        assert dialog.isVisible()
        assert dialog.grid.rows[0][0] == "x" and not file.exists()

    def test_dirty_close_discard_writes_nothing(self, qtbot, tmp_path, boxes):
        file = tmp_path / "t.csv"
        dialog = make_dialog(qtbot, file)
        dialog.grid.setData(dialog.grid.index(0, 0), "x")
        boxes.answer = SB.Discard
        dialog.close()
        assert not dialog.isVisible() and not file.exists()
        assert dialog.saved is False

    def test_dirty_close_save_writes_and_closes(self, qtbot, tmp_path, boxes):
        file = tmp_path / "t.csv"
        dialog = make_dialog(qtbot, file)
        dialog.grid.set_block(0, 0, [["1"]], headers=["a"])
        boxes.answer = SB.Save
        dialog.close()
        assert not dialog.isVisible()
        assert file.read_text() == "a\n1\n" and dialog.saved is True

    def test_dirty_close_save_failure_keeps_dialog_open(self, qtbot, tmp_path, boxes):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        dialog = make_dialog(qtbot, blocker / "t.csv")
        dialog.grid.set_block(0, 0, [["1"]], headers=["a"])
        boxes.answer = SB.Save
        dialog.close()
        assert dialog.isVisible()

    def test_dirty_close_save_of_blank_grid_keeps_dialog_open(
        self, qtbot, tmp_path, boxes
    ):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        # dirty but blank again: edit then clear
        dialog.grid.setData(dialog.grid.index(0, 0), "x")
        dialog.grid.setData(dialog.grid.index(0, 0), "")
        boxes.answer = SB.Save
        dialog.close()
        # the save refuses a blank table and the dialog stays open, so the user can
        # keep editing (or choose Discard)
        assert dialog.isVisible() and dialog.saved is False
        assert not (tmp_path / "t.csv").exists()

    def test_escape_asks_before_discarding(self, qtbot, tmp_path, boxes):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        dialog.grid.setData(dialog.grid.index(0, 0), "x")
        boxes.answer = SB.Cancel
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.isVisible()
        assert any(kind == "question" for kind, _ in boxes.shown)

    def test_escape_on_clean_dialog_closes(self, qtbot, tmp_path, boxes):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert not dialog.isVisible()

    def test_save_then_close_does_not_prompt(self, qtbot, tmp_path, boxes):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        dialog.grid.set_block(0, 0, [["1"]], headers=["a"])
        dialog.on_save()
        dialog.close()
        assert boxes.shown == [] and not dialog.isVisible()

    def test_undo_back_to_saved_state_does_not_prompt(self, qtbot, tmp_path, boxes):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        dialog.grid.setData(dialog.grid.index(0, 0), "x")
        dialog.grid.undo_stack.undo()
        dialog.close()
        assert boxes.shown == [] and not dialog.isVisible()


class TestStatusLine:
    def test_empty_before_saving(self, qtbot, tmp_path):
        assert make_dialog(qtbot, tmp_path / "t.csv").status_label.text() == ""

    def test_save_is_confirmed_on_screen(self, qtbot, tmp_path):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        dialog.grid.set_block(0, 0, [["1", "2"], ["3", "4"]], headers=["a", "b"])
        dialog.on_save()
        text = dialog.status_label.text()
        assert "Saved 2 rows x 2 columns to t.csv" in text

    def test_each_save_updates_the_message(self, qtbot, tmp_path):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        dialog.grid.set_block(0, 0, [["1"]], headers=["a"])
        dialog.on_save()
        dialog.grid.set_block(1, 0, [["2"]])
        dialog.on_save()
        assert "Saved 2 rows x 1 columns" in dialog.status_label.text()

    def test_refused_save_is_shown(self, qtbot, tmp_path, boxes):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        dialog.on_save()
        assert "Nothing saved" in dialog.status_label.text()

    def test_failed_save_is_shown(self, qtbot, tmp_path, boxes):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        dialog = make_dialog(qtbot, blocker / "t.csv")
        dialog.grid.set_block(0, 0, [["1"]], headers=["a"])
        dialog.on_save()
        assert dialog.status_label.text().startswith("Not saved")

    def test_status_label_is_visible(self, qtbot, tmp_path):
        dialog = make_dialog(qtbot, tmp_path / "t.csv")
        dialog.grid.set_block(0, 0, [["1"]], headers=["a"])
        dialog.on_save()
        assert dialog.status_label.isVisible()
