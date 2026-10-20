import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QAbstractItemDelegate, QInputDialog, QMenu

from pywr_editor.widgets.data_grid import DataGridModel, DataGridView, parse_clipboard

CTRL = Qt.KeyboardModifier.ControlModifier


def make_view(qtbot, headers=None, rows=None, model=None) -> DataGridView:
    view = DataGridView(model or DataGridModel(headers, rows))
    qtbot.addWidget(view)
    view.show()
    return view


def select(view: DataGridView, r0: int, c0: int, r1: int | None = None, c1=None):
    """Selects a rectangle of cells (or just one cell) and makes it current."""
    model = view.model()
    view.setCurrentIndex(model.index(r0, c0))
    r1 = r0 if r1 is None else r1
    c1 = c0 if c1 is None else c1
    view.selectionModel().select(
        QItemSelection(model.index(r0, c0), model.index(r1, c1)),
        QItemSelectionModel.SelectionFlag.ClearAndSelect,
    )


def selected(view: DataGridView) -> set[tuple[int, int]]:
    return {(i.row(), i.column()) for i in view.selectedIndexes()}


def set_clipboard(text: str) -> None:
    QGuiApplication.clipboard().setText(text)


def press(view, key, modifiers=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(view, key, modifiers)


def menu_actions(view: DataGridView) -> dict:
    """Builds the context menu without showing it; returns the actions by label."""
    menu = view._build_menu()
    view._test_menu = menu  # keep the menu (and its actions) alive
    return {a.text(): a for a in menu.actions() if not a.isSeparator()}


def trigger(view: DataGridView, label: str) -> None:
    menu_actions(view)[label].trigger()


class TestParseClipboard:
    def test_excel_text(self):
        text = 'a\tb\r\n1\t"x\ty"\r\n3\t"line1\nline2"\r\n'
        assert parse_clipboard(text) == [
            ["a", "b"],
            ["1", "x\ty"],
            ["3", "line1\nline2"],
        ]

    def test_empty(self):
        assert parse_clipboard("") == []

    def test_only_newline_is_one_empty_cell_row_removed(self):
        assert parse_clipboard("\n") == []

    @pytest.mark.parametrize("eol", ["\n", "\r\n", "\r"])
    def test_line_endings(self, eol):
        assert parse_clipboard(f"1\t2{eol}3\t4{eol}") == [["1", "2"], ["3", "4"]]

    def test_single_value_has_no_tabs(self):
        assert parse_clipboard("42") == [["42"]]

    def test_empty_cells_preserved(self):
        assert parse_clipboard("1\t\t3\n\t5\t\n") == [["1", "", "3"], ["", "5", ""]]

    def test_ragged_rows(self):
        assert parse_clipboard("1\t2\t3\n4\n") == [["1", "2", "3"], ["4"]]

    def test_quotes_are_kept_when_not_wrapping(self):
        assert parse_clipboard('5" pipe\t2') == [['5" pipe', "2"]]

    def test_unicode_and_spaces(self):
        assert parse_clipboard(" é \t£1,000.50") == [[" é ", "£1,000.50"]]


class TestModel:
    def test_pads_short_rows_and_headers(self):
        grid = DataGridModel(["A"], [["1", "2", "3"], ["4"]])
        assert grid.headers == ["A", "Column 2", "Column 3"]
        assert grid.rows == [["1", "2", "3"], ["4", "", ""]]

    def test_does_not_alias_inputs(self):
        headers, rows = ["A"], [["1"]]
        grid = DataGridModel(headers, rows)
        grid.rows[0][0] = "9"
        grid.headers[0] = "Z"
        assert headers == ["A"] and rows == [["1"]]

    def test_empty_model(self):
        grid = DataGridModel()
        assert grid.rowCount() == 0 and grid.columnCount() == 0
        assert grid.is_blank()

    def test_data_roles_and_headers(self):
        grid = DataGridModel(["A", "B"], [["1", "2"]])
        idx = grid.index(0, 1)
        assert grid.data(idx) == "2"
        assert grid.data(idx, Qt.ItemDataRole.EditRole) == "2"
        assert grid.data(idx, Qt.ItemDataRole.ForegroundRole) is None
        assert grid.headerData(1, Qt.Orientation.Horizontal) == "B"
        assert grid.headerData(0, Qt.Orientation.Vertical) == 1
        assert grid.flags(idx) & Qt.ItemFlag.ItemIsEditable

    def test_set_data_same_value_is_not_an_undo_step(self):
        grid = DataGridModel(["A"], [["1"]])
        assert grid.setData(grid.index(0, 0), "1") is False
        assert not grid.undo_stack.canUndo()

    def test_set_data_converts_to_text_and_none(self):
        grid = DataGridModel(["A"], [["1"]])
        grid.setData(grid.index(0, 0), 5.5)
        assert grid.rows == [["5.5"]]
        grid.setData(grid.index(0, 0), None)
        assert grid.rows == [[""]]

    def test_set_data_wrong_role_rejected(self):
        grid = DataGridModel(["A"], [["1"]])
        assert not grid.setData(grid.index(0, 0), "x", Qt.ItemDataRole.DisplayRole)
        assert grid.rows == [["1"]]

    def test_set_data_emits_data_changed_and_changed(self):
        grid = DataGridModel(["A"], [["1"]])
        data_spy = QSignalSpy(grid.dataChanged)
        changed_spy = QSignalSpy(grid.changed)
        grid.setData(grid.index(0, 0), "2")
        assert data_spy.count() == 1 and changed_spy.count() >= 1

    def test_undo_redo_emit_changed(self):
        grid = DataGridModel(["A"], [["1"]])
        grid.setData(grid.index(0, 0), "2")
        spy = QSignalSpy(grid.changed)
        grid.undo_stack.undo()
        grid.undo_stack.redo()
        assert spy.count() >= 2

    def test_redo_after_undo_restores_exact_state(self):
        grid = DataGridModel(["A", "B"], [["1", "2"]])
        grid.set_block(0, 0, [["x", "y", "z"], ["a", "b", "c"]])
        after = (list(grid.headers), [list(r) for r in grid.rows])
        grid.undo_stack.undo()
        grid.undo_stack.redo()
        assert (grid.headers, grid.rows) == after

    def test_undo_does_not_share_state_with_stack(self):
        # editing after an undo must not corrupt the stored snapshots
        grid = DataGridModel(["A"], [["1"]])
        grid.setData(grid.index(0, 0), "2")
        grid.undo_stack.undo()
        grid.setData(grid.index(0, 0), "3")
        grid.undo_stack.undo()
        assert grid.rows == [["1"]]
        grid.undo_stack.redo()
        assert grid.rows == [["3"]]

    def test_many_steps_undo_in_order(self):
        grid = DataGridModel(["A"], [["0"]])
        for i in range(1, 6):
            grid.setData(grid.index(0, 0), str(i))
        for expected in ["4", "3", "2", "1", "0"]:
            grid.undo_stack.undo()
            assert grid.rows == [[expected]]
        # nothing left to undo
        grid.undo_stack.undo()
        assert grid.rows == [["0"]]

    def test_new_edit_clears_redo(self):
        grid = DataGridModel(["A"], [["0"]])
        grid.setData(grid.index(0, 0), "1")
        grid.undo_stack.undo()
        grid.setData(grid.index(0, 0), "2")
        assert not grid.undo_stack.canRedo()

    def test_clean_state_tracking(self, tmp_path):
        grid = DataGridModel(["A"], [["0"]])
        assert grid.undo_stack.isClean()
        grid.setData(grid.index(0, 0), "1")
        assert not grid.undo_stack.isClean()
        grid.to_csv(tmp_path / "t.csv")
        assert grid.undo_stack.isClean()
        grid.undo_stack.undo()
        assert not grid.undo_stack.isClean()  # differs from the saved file
        grid.undo_stack.redo()
        assert grid.undo_stack.isClean()

    def test_changed_signal_on_clean_state_change(self, tmp_path):
        grid = DataGridModel(["A"], [["0"]])
        grid.setData(grid.index(0, 0), "1")
        spy = QSignalSpy(grid.changed)
        grid.to_csv(tmp_path / "t.csv")
        assert spy.count() == 1  # title can drop the "*"

    def test_rename_column(self):
        grid = DataGridModel(["A", "B"], [["1", "2"]])
        grid.rename_column(1, "Flow")
        assert grid.headers == ["A", "Flow"]
        grid.undo_stack.undo()
        assert grid.headers == ["A", "B"]

    def test_rename_column_same_name_is_noop(self):
        grid = DataGridModel(["A"], [["1"]])
        grid.rename_column(0, "A")
        assert not grid.undo_stack.canUndo()

    def test_insert_rows(self):
        grid = DataGridModel(["A", "B"], [["1", "2"], ["3", "4"]])
        grid.insert_rows(1, 2)
        assert grid.rows == [["1", "2"], ["", ""], ["", ""], ["3", "4"]]
        grid.undo_stack.undo()
        assert grid.rows == [["1", "2"], ["3", "4"]]

    def test_insert_row_at_end_and_into_empty(self):
        grid = DataGridModel(["A"], [["1"]])
        grid.insert_rows(1)
        assert grid.rows == [["1"], [""]]
        empty = DataGridModel(["A"], [])
        empty.insert_rows(0)
        assert empty.rows == [[""]]

    def test_remove_rows_unsorted_and_duplicates(self):
        grid = DataGridModel(["A"], [[str(i)] for i in range(5)])
        grid.remove_rows([3, 1, 3])
        assert grid.rows == [["0"], ["2"], ["4"]]
        grid.undo_stack.undo()
        assert len(grid.rows) == 5

    def test_insert_and_remove_columns(self):
        grid = DataGridModel(["A", "B"], [["1", "2"]])
        grid.insert_column(1, "X")
        assert grid.headers == ["A", "X", "B"]
        assert grid.rows == [["1", "", "2"]]
        grid.remove_columns([2, 0])
        assert grid.headers == ["X"] and grid.rows == [[""]]
        grid.undo_stack.undo()
        assert grid.headers == ["A", "X", "B"]

    def test_insert_column_default_name(self):
        grid = DataGridModel(["A", "B"], [["1", "2"]])
        grid.insert_column(0)
        assert grid.headers[0] == "Column 3"

    def test_remove_all_columns(self):
        grid = DataGridModel(["A", "B"], [["1", "2"]])
        grid.remove_columns([0, 1])
        assert grid.columnCount() == 0
        grid.undo_stack.undo()
        assert grid.rows == [["1", "2"]]

    def test_set_block_grows_and_pads(self):
        grid = DataGridModel(["A"], [["1"]])
        grid.set_block(2, 1, [["x", "y"]])
        assert grid.headers == ["A", "Column 2", "Column 3"]
        assert grid.rows == [["1", "", ""], ["", "", ""], ["", "x", "y"]]

    def test_set_block_ragged(self):
        grid = DataGridModel(["A", "B", "C"], [["", "", ""], ["", "", ""]])
        grid.set_block(0, 0, [["1", "2", "3"], ["4"]])
        assert grid.rows == [["1", "2", "3"], ["4", "", ""]]

    def test_set_block_into_empty_model(self):
        grid = DataGridModel()
        grid.set_block(0, 0, [["1", "2"]], headers=["a", "b"])
        assert grid.headers == ["a", "b"] and grid.rows == [["1", "2"]]

    def test_set_block_headers_wider_than_data(self):
        grid = DataGridModel(["A"], [["1"]])
        grid.set_block(0, 0, [["x"]], headers=["h1", "h2", "h3"])
        assert grid.headers == ["h1", "h2", "h3"]
        assert grid.rows == [["x", "", ""]]

    def test_set_block_headers_only(self):
        grid = DataGridModel()
        grid.set_block(0, 0, [], headers=["h1", "h2"])
        assert grid.headers == ["h1", "h2"]

    def test_set_block_headers_at_offset(self):
        grid = DataGridModel(["A", "B", "C"], [["1", "2", "3"]])
        grid.set_block(0, 1, [["x"]], headers=["H"])
        assert grid.headers == ["A", "H", "C"]

    def test_clear_cells(self):
        grid = DataGridModel(["A", "B"], [["1", "2"], ["3", "4"]])
        grid.clear_cells([(0, 0), (1, 1)])
        assert grid.rows == [["", "2"], ["3", ""]]


class TestTrimAndBlank:
    def test_blank_dimensions(self):
        grid = DataGridModel.blank(3, 4)
        assert grid.columnCount() == 3 and grid.rowCount() == 4
        assert grid.is_blank()
        assert grid.undo_stack.isClean() and not grid.undo_stack.canUndo()

    def test_not_blank_when_value_or_name_changes(self):
        grid = DataGridModel.blank(2, 2)
        grid.setData(grid.index(1, 1), "x")
        assert not grid.is_blank()
        grid = DataGridModel.blank(2, 2)
        grid.rename_column(0, "Date")
        assert not grid.is_blank()

    def test_trim_rows_only_at_the_end(self):
        grid = DataGridModel(["A"], [["1"], [""], ["3"], [""], [""]])
        assert grid.trimmed() == (["A"], [["1"], [""], ["3"]])

    def test_trim_default_columns_only_when_empty(self):
        grid = DataGridModel(["A", "Column 2", "Column 3"], [["1", "", ""]])
        assert grid.trimmed() == (["A"], [["1"]])

    def test_does_not_trim_named_or_filled_columns(self):
        grid = DataGridModel(["A", "B", "Column 3"], [["1", "", ""]])
        assert grid.trimmed() == (["A", "B"], [["1", ""]])
        grid = DataGridModel(["A", "Column 2"], [["1", "x"]])
        assert grid.trimmed() == (["A", "Column 2"], [["1", "x"]])

    def test_trim_keeps_default_named_column_followed_by_data(self):
        grid = DataGridModel(["Column 1", "Column 2", "C"], [["", "", "x"]])
        assert grid.trimmed()[0] == ["Column 1", "Column 2", "C"]

    def test_trim_does_not_change_the_grid(self):
        grid = DataGridModel.blank(3, 3)
        grid.setData(grid.index(0, 0), "x")
        grid.trimmed()
        assert grid.columnCount() == 3 and grid.rowCount() == 3

    def test_header_only_table(self):
        grid = DataGridModel(["A", "B"], [["", ""]])
        assert grid.trimmed() == (["A", "B"], [])


class TestCsv:
    def test_round_trip_keeps_text(self, tmp_path):
        file = tmp_path / "t.csv"
        file.write_text("date;v\n01/02/2020;1.50\n03/02/2020;007\n")
        grid = DataGridModel.from_csv(file, sep=";")
        assert grid.rows == [["01/02/2020", "1.50"], ["03/02/2020", "007"]]
        grid.to_csv(file, sep=";")
        assert file.read_text() == "date;v\n01/02/2020;1.50\n03/02/2020;007\n"

    def test_not_dirty_after_load(self, tmp_path):
        file = tmp_path / "t.csv"
        file.write_text("a,b\n1,2\n")
        assert DataGridModel.from_csv(file).undo_stack.isClean()

    def test_empty_file(self, tmp_path):
        file = tmp_path / "t.csv"
        file.write_text("")
        grid = DataGridModel.from_csv(file)
        assert grid.headers == [] and grid.rows == []

    def test_header_only_file(self, tmp_path):
        file = tmp_path / "t.csv"
        file.write_text("a,b\n")
        grid = DataGridModel.from_csv(file)
        assert grid.headers == ["a", "b"] and grid.rows == []

    def test_ragged_file_is_padded(self, tmp_path):
        file = tmp_path / "t.csv"
        file.write_text("a,b,c\n1\n1,2,3,4\n")
        grid = DataGridModel.from_csv(file)
        assert grid.headers == ["a", "b", "c", "Column 4"]
        assert grid.rows == [["1", "", "", ""], ["1", "2", "3", "4"]]

    def test_utf8_bom_is_removed(self, tmp_path):
        file = tmp_path / "t.csv"
        file.write_bytes(b"\xef\xbb\xbfDate,v\n1,2\n")
        assert DataGridModel.from_csv(file).headers == ["Date", "v"]

    def test_crlf_file(self, tmp_path):
        file = tmp_path / "t.csv"
        file.write_bytes(b"a,b\r\n1,2\r\n")
        assert DataGridModel.from_csv(file).rows == [["1", "2"]]

    def test_quoted_fields_round_trip(self, tmp_path):
        file = tmp_path / "t.csv"
        grid = DataGridModel(["a", "b"], [['x,y', 'he said "hi"'], ["l1\nl2", ""]])
        grid.to_csv(file)
        again = DataGridModel.from_csv(file)
        assert again.rows == [['x,y', 'he said "hi"'], ["l1\nl2", ""]]

    def test_non_ascii(self, tmp_path):
        file = tmp_path / "t.csv"
        DataGridModel(["é"], [["£"]]).to_csv(file)
        assert DataGridModel.from_csv(file).rows == [["£"]]

    def test_values_that_contain_the_separator_are_quoted(self, tmp_path):
        file = tmp_path / "t.csv"
        DataGridModel(["a"], [["1;2"]]).to_csv(file, sep=";")
        assert file.read_text() == 'a\n"1;2"\n'

    def test_creates_missing_folders(self, tmp_path):
        file = tmp_path / "a" / "b" / "t.csv"
        DataGridModel(["a"], [["1"]]).to_csv(file)
        assert file.exists()

    def test_trailing_padding_not_written(self, tmp_path):
        grid = DataGridModel.blank()
        grid.set_block(0, 0, [["1", "2"]], headers=["x", "y"])
        grid.to_csv(tmp_path / "t.csv")
        assert (tmp_path / "t.csv").read_text() == "x,y\n1,2\n"

    def test_pandas_can_read_the_result(self, tmp_path):
        import pandas as pd

        grid = DataGridModel.blank()
        grid.set_block(
            0, 0, [["2020-01-01", "1.5"], ["2020-01-02", "2.5"]], headers=["d", "v"]
        )
        grid.to_csv(tmp_path / "t.csv")
        df = pd.read_csv(tmp_path / "t.csv", index_col="d")
        assert list(df.columns) == ["v"] and df["v"].tolist() == [1.5, 2.5]
        assert not df.isna().any().any()

    def test_failed_save_leaves_grid_dirty(self, tmp_path):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        grid = DataGridModel(["a"], [["1"]])
        grid.setData(grid.index(0, 0), "2")
        with pytest.raises(OSError):
            grid.to_csv(blocker / "t.csv")
        assert not grid.undo_stack.isClean()


class TestViewKeys:
    def test_paste_grows_grid_and_one_undo_reverts(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"]])
        set_clipboard("10\t20\t30\n40\t50\t60\n")
        select(view, 0, 1)
        press(view, Qt.Key.Key_V, CTRL)
        grid = view.grid
        assert grid.rows == [["1", "10", "20", "30"], ["", "40", "50", "60"]]
        assert grid.headers == ["A", "B", "Column 3", "Column 4"]
        press(view, Qt.Key.Key_Z, CTRL)
        assert grid.rows == [["1", "2"]] and grid.headers == ["A", "B"]
        press(view, Qt.Key.Key_Y, CTRL)
        assert grid.rows[1] == ["", "40", "50", "60"]

    def test_ctrl_shift_z_redoes(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        view.model().setData(view.model().index(0, 0), "2")
        press(view, Qt.Key.Key_Z, CTRL)
        press(view, Qt.Key.Key_Z, CTRL | Qt.KeyboardModifier.ShiftModifier)
        assert view.grid.rows == [["2"]]

    def test_paste_at_selection_top_left_with_multiple_cells(self, qtbot):
        view = make_view(qtbot, ["A", "B", "C"], [["1", "2", "3"]] * 3)
        set_clipboard("x\ty\n")
        select(view, 1, 1, 2, 2)
        press(view, Qt.Key.Key_V, CTRL)
        assert view.grid.rows[1] == ["1", "x", "y"]
        assert view.grid.rows[2] == ["1", "2", "3"]

    def test_paste_with_no_selection_goes_to_origin(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"]])
        view.clearSelection()
        view.setCurrentIndex(view.model().index(-1, -1))
        set_clipboard("z")
        view.paste()
        assert view.grid.rows[0][0] == "z"

    def test_paste_empty_clipboard_is_noop(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        set_clipboard("")
        select(view, 0, 0)
        press(view, Qt.Key.Key_V, CTRL)
        assert view.grid.rows == [["1"]]
        assert not view.grid.undo_stack.canUndo()

    def test_paste_into_model_without_columns(self, qtbot):
        view = make_view(qtbot)
        set_clipboard("1\t2\n3\t4")
        view.paste()
        assert view.grid.rows == [["1", "2"], ["3", "4"]]
        assert view.grid.headers == ["Column 1", "Column 2"]

    def test_paste_with_header_into_blank_grid(self, qtbot):
        view = make_view(qtbot, model=DataGridModel.blank())
        set_clipboard("Date\tFlow\n2020\t1.5\n")
        select(view, 0, 0)
        view.paste(with_header=True)
        assert view.grid.headers[:2] == ["Date", "Flow"]
        assert view.grid.rows[0][:2] == ["2020", "1.5"]
        assert view.grid.rows[1][:2] == ["", ""]

    def test_paste_with_header_row_only(self, qtbot):
        view = make_view(qtbot, model=DataGridModel.blank(3, 2))
        set_clipboard("a\tb\tc\td\n")
        select(view, 0, 0)
        view.paste(with_header=True)
        assert view.grid.headers == ["a", "b", "c", "d"]

    def test_paste_with_header_wider_than_data(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        set_clipboard("a\tb\tc\n1\n")
        select(view, 0, 0)
        view.paste(with_header=True)
        assert view.grid.headers == ["a", "b", "c"]
        assert view.grid.rows == [["1", "", ""]]

    def test_single_value_fills_selection(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"], ["3", "4"]])
        set_clipboard("0")
        select(view, 0, 0, 1, 1)
        view.paste()
        assert view.grid.rows == [["0", "0"], ["0", "0"]]
        press(view, Qt.Key.Key_Z, CTRL)
        assert view.grid.rows == [["1", "2"], ["3", "4"]]

    def test_single_value_with_one_selected_cell_sets_only_it(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"]])
        set_clipboard("9")
        select(view, 0, 1)
        view.paste()
        assert view.grid.rows == [["1", "9"]]

    def test_single_value_fill_does_not_grow(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"]])
        set_clipboard("7")
        select(view, 0, 0, 0, 1)
        view.paste()
        assert view.grid.rows == [["7", "7"]] and view.grid.columnCount() == 2

    def test_copy_single_and_block(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"], ["3", "4"]])
        select(view, 0, 1)
        assert view.selection_text() == "2\n"
        select(view, 0, 0, 1, 1)
        press(view, Qt.Key.Key_C, CTRL)
        assert QGuiApplication.clipboard().text() == "1\t2\n3\t4\n"

    def test_copy_non_contiguous_selection(self, qtbot):
        view = make_view(qtbot, ["A", "B", "C"], [["1", "2", "3"], ["4", "5", "6"]])
        select(view, 0, 0)
        view.selectionModel().select(
            view.model().index(1, 2), QItemSelectionModel.SelectionFlag.Select
        )
        assert view.selection_text() == "1\t\t\n\t\t6\n"

    def test_copy_with_empty_selection_keeps_clipboard(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        set_clipboard("keep me")
        view.clearSelection()
        view.copy()
        assert QGuiApplication.clipboard().text() == "keep me"

    def test_cut_with_empty_selection_changes_nothing(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        set_clipboard("keep me")
        view.clearSelection()
        press(view, Qt.Key.Key_X, CTRL)
        assert QGuiApplication.clipboard().text() == "keep me"
        assert view.grid.rows == [["1"]]

    def test_cell_with_tab_and_newline_round_trips_via_clipboard(self, qtbot):
        view = make_view(qtbot, ["A"], [["a\tb"], ["c\nd"]])
        select(view, 0, 0, 1, 0)
        view.copy()
        other = make_view(qtbot, model=DataGridModel.blank(1, 2))
        select(other, 0, 0)
        other.paste()
        assert other.grid.rows[:2] == [["a\tb"], ["c\nd"]]

    def test_cut(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"]])
        select(view, 0, 0, 0, 1)
        press(view, Qt.Key.Key_X, CTRL)
        assert QGuiApplication.clipboard().text() == "1\t2\n"
        assert view.grid.rows == [["", ""]]
        press(view, Qt.Key.Key_Z, CTRL)
        assert view.grid.rows == [["1", "2"]]

    @pytest.mark.parametrize("key", [Qt.Key.Key_Delete, Qt.Key.Key_Backspace])
    def test_delete_and_backspace_clear(self, qtbot, key):
        view = make_view(qtbot, ["A", "B"], [["1", "2"], ["3", "4"]])
        select(view, 0, 0, 1, 1)
        press(view, key)
        assert view.grid.rows == [["", ""], ["", ""]]
        press(view, Qt.Key.Key_Z, CTRL)
        assert view.grid.rows == [["1", "2"], ["3", "4"]]

    def test_delete_without_selection_is_noop(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        view.clearSelection()
        press(view, Qt.Key.Key_Delete)
        assert view.grid.rows == [["1"]] and not view.grid.undo_stack.canUndo()

    def test_undo_with_nothing_to_undo(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        press(view, Qt.Key.Key_Z, CTRL)
        press(view, Qt.Key.Key_Y, CTRL)
        assert view.grid.rows == [["1"]]

    @pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter])
    def test_return_starts_editing_the_current_cell(self, qtbot, key):
        view = make_view(qtbot, ["A"], [["1"]])
        select(view, 0, 0)
        press(view, key)
        assert view.state() == view.State.EditingState

    def test_return_without_current_cell_is_safe(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        view.setCurrentIndex(view.model().index(-1, -1))
        press(view, Qt.Key.Key_Return)
        assert view.state() != view.State.EditingState

    def test_arrow_keys_still_navigate(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"], ["3", "4"]])
        select(view, 0, 0)
        press(view, Qt.Key.Key_Down)
        press(view, Qt.Key.Key_Right)
        assert (view.currentIndex().row(), view.currentIndex().column()) == (1, 1)

    def test_shift_click_selection_then_paste_fill(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"], ["2"], ["3"]])
        select(view, 0, 0, 2, 0)
        set_clipboard("5")
        view.paste()
        assert view.grid.rows == [["5"], ["5"], ["5"]]


class TestSelectionSurvivesEdits:
    """Edits rebuild the model: the cursor and selection must stay where they are."""

    def test_selection_kept_after_delete(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"], ["3", "4"]])
        select(view, 0, 0, 1, 1)
        press(view, Qt.Key.Key_Delete)
        assert selected(view) == {(0, 0), (0, 1), (1, 0), (1, 1)}
        assert view.currentIndex().isValid()

    def test_selection_kept_after_undo(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"], ["3", "4"]])
        select(view, 1, 1)
        press(view, Qt.Key.Key_Delete)
        press(view, Qt.Key.Key_Z, CTRL)
        assert selected(view) == {(1, 1)}

    def test_current_cell_kept_after_paste(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"], ["3", "4"]])
        select(view, 1, 0)
        set_clipboard("x")
        view.paste()
        assert (view.currentIndex().row(), view.currentIndex().column()) == (1, 0)

    def test_repeated_delete_keeps_working(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"], ["2"]])
        select(view, 0, 0)
        press(view, Qt.Key.Key_Delete)
        press(view, Qt.Key.Key_Down)
        press(view, Qt.Key.Key_Delete)
        assert view.grid.rows == [[""], [""]]

    def test_selection_dropped_if_cells_no_longer_exist(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"], ["2"], ["3"]])
        select(view, 2, 0)
        view.grid.remove_rows([2])
        assert all(r < view.grid.rowCount() for r, _ in selected(view))


class TestCellEditing:
    def test_edit_cell_is_undoable(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        view.model().setData(view.model().index(0, 0), "9")
        press(view, Qt.Key.Key_Z, CTRL)
        assert view.grid.rows == [["1"]]

    def test_typing_in_the_editor_commits_one_undo_step(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        select(view, 0, 0)
        view.edit(view.currentIndex())
        editor = view.focusWidget()
        editor.selectAll()
        QTest.keyClicks(editor, "123")
        # commit and close as the delegate does on Return (plain Qt ignores a
        # synthetic Return here, and Tab would open the next cell's editor)
        view.commitData(editor)
        view.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
        assert view.grid.rows == [["123"]]
        press(view, Qt.Key.Key_Z, CTRL)
        assert view.grid.rows == [["1"]]

    def test_ctrl_z_inside_editor_does_not_undo_the_grid(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"]])
        view.model().setData(view.model().index(0, 1), "9")
        select(view, 0, 0)
        view.edit(view.currentIndex())
        editor = view.focusWidget()
        press(editor, Qt.Key.Key_Z, CTRL)
        assert view.grid.rows == [["1", "9"]]

    def test_delete_inside_editor_edits_text_not_cells(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["abc", "2"]])
        select(view, 0, 0)
        view.edit(view.currentIndex())
        editor = view.focusWidget()
        editor.setCursorPosition(0)
        press(editor, Qt.Key.Key_Delete)
        assert view.grid.rows == [["abc", "2"]]  # not committed yet
        assert editor.text() == "bc"

    def test_escape_cancels_edit(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        select(view, 0, 0)
        view.edit(view.currentIndex())
        editor = view.focusWidget()
        QTest.keyClicks(editor, "zzz")
        press(editor, Qt.Key.Key_Escape)
        assert view.grid.rows == [["1"]]
        assert not view.grid.undo_stack.canUndo()

    def test_editing_to_the_same_text_adds_no_undo_step(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        select(view, 0, 0)
        view.edit(view.currentIndex())
        press(view.focusWidget(), Qt.Key.Key_Tab)
        assert not view.grid.undo_stack.canUndo()


class TestShortcutOverride:
    def test_parent_shortcut_cannot_steal_keys(self, qtbot):
        from PySide6.QtGui import QAction, QKeySequence
        from PySide6.QtWidgets import QDialog, QVBoxLayout

        dialog = QDialog()
        qtbot.addWidget(dialog)
        stolen = []
        for seq in (
            QKeySequence.StandardKey.Undo,
            QKeySequence.StandardKey.Redo,
            QKeySequence.StandardKey.Paste,
        ):
            action = QAction(dialog)
            action.setShortcut(QKeySequence(seq))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(lambda *_: stolen.append(1))
            dialog.addAction(action)
        view = DataGridView(DataGridModel(["A"], [["1"]]))
        QVBoxLayout(dialog).addWidget(view)
        dialog.show()
        qtbot.waitExposed(dialog)
        view.setFocus()
        view.setCurrentIndex(view.model().index(0, 0))
        view.model().setData(view.model().index(0, 0), "2")
        set_clipboard("5")

        press(view, Qt.Key.Key_Z, CTRL)
        assert view.grid.rows == [["1"]]
        press(view, Qt.Key.Key_V, CTRL)
        assert view.grid.rows == [["5"]]
        assert stolen == []


class TestContextMenuAndHeader:
    def test_menu_entries_and_enabled_state(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        actions = menu_actions(view)
        assert not actions["Undo"].isEnabled()
        assert not actions["Redo"].isEnabled()
        assert {
            "Copy",
            "Paste",
            "Paste with header row",
            "Insert row above",
            "Insert column left",
            "Delete selected rows",
            "Delete selected columns",
        } <= set(actions)

    def test_undo_redo_enabled_after_edit(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        view.model().setData(view.model().index(0, 0), "2")
        assert menu_actions(view)["Undo"].isEnabled()
        view.grid.undo_stack.undo()
        assert menu_actions(view)["Redo"].isEnabled()

    def test_menu_undo_and_redo(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        view.model().setData(view.model().index(0, 0), "2")
        trigger(view, "Undo")
        assert view.grid.rows == [["1"]]
        trigger(view, "Redo")
        assert view.grid.rows == [["2"]]

    def test_menu_copy_and_paste(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"]])
        select(view, 0, 0)
        trigger(view, "Copy")
        select(view, 0, 1)
        trigger(view, "Paste")
        assert view.grid.rows == [["1", "1"]]

    def test_menu_paste_with_header(self, qtbot):
        view = make_view(qtbot, model=DataGridModel.blank(2, 2))
        set_clipboard("H1\tH2\n1\t2")
        select(view, 0, 0)
        trigger(view, "Paste with header row")
        assert view.grid.headers == ["H1", "H2"] and view.grid.rows[0] == ["1", "2"]

    def test_menu_insert_row_above_current(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"], ["2"]])
        select(view, 1, 0)
        trigger(view, "Insert row above")
        assert view.grid.rows == [["1"], [""], ["2"]]

    def test_menu_insert_row_without_current_cell(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        view.setCurrentIndex(view.model().index(-1, -1))
        trigger(view, "Insert row above")
        assert view.grid.rows == [[""], ["1"]]

    def test_menu_insert_column_left(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"]])
        select(view, 0, 1)
        trigger(view, "Insert column left")
        assert view.grid.rows == [["1", "", "2"]] and view.grid.headers[0] == "A"

    def test_menu_delete_selected_rows_from_cell_selection(self, qtbot):
        view = make_view(qtbot, ["A", "B"], [["1", "2"], ["3", "4"], ["5", "6"]])
        select(view, 0, 0, 1, 1)
        trigger(view, "Delete selected rows")
        assert view.grid.rows == [["5", "6"]]

    def test_menu_delete_selected_rows_from_row_header(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"], ["2"], ["3"]])
        view.selectRow(1)
        trigger(view, "Delete selected rows")
        assert view.grid.rows == [["1"], ["3"]]

    def test_menu_delete_selected_columns(self, qtbot):
        view = make_view(qtbot, ["A", "B", "C"], [["1", "2", "3"]])
        view.selectColumn(1)
        trigger(view, "Delete selected columns")
        assert view.grid.headers == ["A", "C"] and view.grid.rows == [["1", "3"]]

    def test_menu_delete_without_selection_is_noop(self, qtbot):
        view = make_view(qtbot, ["A"], [["1"]])
        view.clearSelection()
        trigger(view, "Delete selected rows")
        trigger(view, "Delete selected columns")
        assert view.grid.rows == [["1"]]

    def test_header_double_click_renames(self, qtbot, monkeypatch):
        view = make_view(qtbot, ["A", "B"], [["1", "2"]])
        monkeypatch.setattr(
            QInputDialog, "getText", lambda *a, **k: ("Flow", True)
        )
        view.horizontalHeader().sectionDoubleClicked.emit(1)
        assert view.grid.headers == ["A", "Flow"]
        press(view, Qt.Key.Key_Z, CTRL)
        assert view.grid.headers == ["A", "B"]

    def test_header_rename_cancelled_or_empty(self, qtbot, monkeypatch):
        view = make_view(qtbot, ["A"], [["1"]])
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("X", False))
        view._rename_column(0)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", True))
        view._rename_column(0)
        assert view.grid.headers == ["A"] and not view.grid.undo_stack.canUndo()

    def test_rename_dialog_prefilled_with_current_name(self, qtbot, monkeypatch):
        view = make_view(qtbot, ["A", "Flow"], [["1", "2"]])
        seen = {}

        def fake(*args, **kwargs):
            seen.update(kwargs)
            return ("Flow", False)

        monkeypatch.setattr(QInputDialog, "getText", fake)
        view._rename_column(1)
        assert seen["text"] == "Flow"
