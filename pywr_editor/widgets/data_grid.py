import csv
import io
from copy import deepcopy
from pathlib import Path
from typing import Any

import PySide6
from PySide6.QtCore import (
    QAbstractTableModel,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import QAbstractItemView, QInputDialog, QMenu, QTableView

"""
 An Excel-style grid to edit tabular data. Cells are stored as text, so the content
 of a file is never reformatted when it is loaded and saved. The view supports
 copy, cut, paste (including from Excel), delete, fill of the selection with a
 single pasted value, row and column insertion and removal, and undo/redo of every
 change.
"""


class _SnapshotCommand(QUndoCommand):
    def __init__(
        self,
        model: "DataGridModel",
        text: str,
        before: tuple[list[str], list[list[str]]],
        after: tuple[list[str], list[list[str]]],
    ):
        """
        Initialises the command. The tables are small, so the whole grid is stored
        before and after the change rather than the individual cells.
        :param model: The DataGridModel instance.
        :param text: The command text.
        :param before: The headers and rows before the change.
        :param after: The headers and rows after the change.
        """
        super().__init__(text)
        self.model = model
        self.before = before
        self.after = after
        self._first = True

    def undo(self) -> None:
        self.model._restore(*self.before)

    def redo(self) -> None:
        # the change has already been applied when the command is pushed
        if self._first:
            self._first = False
            return
        self.model._restore(*self.after)


class DataGridModel(QAbstractTableModel):
    changed = Signal()

    def __init__(
        self,
        headers: list[str] | None = None,
        rows: list[list[str]] | None = None,
    ):
        """
        Initialises the model.
        :param headers: The column names.
        :param rows: The table rows as text. Rows are padded to the number of columns.
        """
        super().__init__()
        self.undo_stack = QUndoStack(self)
        self.headers: list[str] = list(headers) if headers else []
        self.rows: list[list[str]] = [list(r) for r in rows] if rows else []
        self._pad()
        self.undo_stack.cleanChanged.connect(lambda _: self.changed.emit())

    @classmethod
    def blank(cls, columns: int = 5, rows: int = 20) -> "DataGridModel":
        """
        Creates an empty grid to paste data into.
        :param columns: The number of columns.
        :param rows: The number of rows.
        :return: The model.
        """
        return cls(
            [f"Column {i + 1}" for i in range(columns)],
            [[""] * columns for _ in range(rows)],
        )

    def is_blank(self) -> bool:
        """
        :return: Whether the grid contains no data (default column names, no values).
        """
        return all(
            h == f"Column {i + 1}" for i, h in enumerate(self.headers)
        ) and not any(any(r) for r in self.rows)

    def trimmed(self) -> tuple[list[str], list[list[str]]]:
        """
        Gets the headers and rows without the trailing empty rows and the trailing
        columns that still have their default name and no values.
        :return: The headers and rows.
        """
        rows = [list(r) for r in self.rows]
        while rows and not any(rows[-1]):
            rows.pop()
        headers = list(self.headers)
        while (
            headers
            and headers[-1] == f"Column {len(headers)}"
            and not any(r[len(headers) - 1] for r in rows)
        ):
            headers.pop()
        return headers, [r[: len(headers)] for r in rows]

    @classmethod
    def from_csv(cls, path: str | Path, sep: str = ",") -> "DataGridModel":
        """
        Loads a CSV file without parsing the values.
        :param path: The file path.
        :param sep: The separator.
        :return: The model.
        """
        with open(path, newline="", encoding="utf-8-sig") as fid:
            data = list(csv.reader(fid, delimiter=sep))
        if not data:
            return cls()
        return cls(headers=data[0], rows=data[1:])

    def to_csv(self, path: str | Path, sep: str = ",") -> None:
        """
        Saves the table to a CSV file, without the padding of empty rows and columns,
        and marks the undo stack as clean.
        :param path: The file path.
        :param sep: The separator.
        :return: None
        """
        headers, rows = self.trimmed()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as fid:
            writer = csv.writer(fid, delimiter=sep, lineterminator="\n")
            writer.writerow(headers)
            writer.writerows(rows)
        self.undo_stack.setClean()

    def _pad(self) -> None:
        """
        Makes all the rows as long as the headers (or the longest row).
        :return: None
        """
        width = max([len(self.headers)] + [len(r) for r in self.rows])
        while len(self.headers) < width:
            self.headers.append(f"Column {len(self.headers) + 1}")
        for row in self.rows:
            row.extend([""] * (width - len(row)))

    def _snapshot(self) -> tuple[list[str], list[list[str]]]:
        return list(self.headers), deepcopy(self.rows)

    def _restore(self, headers: list[str], rows: list[list[str]]) -> None:
        self.beginResetModel()
        self.headers = list(headers)
        self.rows = deepcopy(rows)
        self.endResetModel()
        self.changed.emit()

    def edit(self, text: str, fun) -> None:
        """
        Applies a change to the grid and records it in the undo stack as a single
        step.
        :param text: The undo command text.
        :param fun: The callable that changes self.headers and self.rows.
        :return: None
        """
        before = self._snapshot()
        self.beginResetModel()
        fun()
        self._pad()
        self.endResetModel()
        self.undo_stack.push(_SnapshotCommand(self, text, before, self._snapshot()))
        self.changed.emit()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self.rows[index.row()][index.column()]
        return None

    def setData(
        self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole
    ) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        value = "" if value is None else str(value)
        if self.rows[index.row()][index.column()] == value:
            return False
        before = self._snapshot()
        self.rows[index.row()][index.column()] = value
        self.dataChanged.emit(index, index)
        self.undo_stack.push(
            _SnapshotCommand(self, "Edit cell", before, self._snapshot())
        )
        self.changed.emit()
        return True

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return section + 1

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        return (
            Qt.ItemFlag.ItemIsEditable
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )

    def rename_column(self, column: int, name: str) -> None:
        """
        Renames a column.
        :param column: The column index.
        :param name: The new name.
        :return: None
        """
        if self.headers[column] == name:
            return
        self.edit("Rename column", lambda: self.headers.__setitem__(column, name))

    def insert_rows(self, row: int, count: int = 1) -> None:
        def fun() -> None:
            for _ in range(count):
                self.rows.insert(row, [""] * len(self.headers))

        self.edit("Insert rows", fun)

    def remove_rows(self, rows: list[int]) -> None:
        def fun() -> None:
            for row in sorted(set(rows), reverse=True):
                del self.rows[row]

        self.edit("Remove rows", fun)

    def insert_column(self, column: int, name: str | None = None) -> None:
        def fun() -> None:
            self.headers.insert(column, name or f"Column {len(self.headers) + 1}")
            for row in self.rows:
                row.insert(column, "")

        self.edit("Insert column", fun)

    def remove_columns(self, columns: list[int]) -> None:
        def fun() -> None:
            for col in sorted(set(columns), reverse=True):
                del self.headers[col]
                for row in self.rows:
                    del row[col]

        self.edit("Remove columns", fun)

    def set_block(
        self,
        top: int,
        left: int,
        block: list[list[str]],
        text: str = "Paste",
        headers: list[str] | None = None,
    ) -> None:
        """
        Writes a block of values starting at the given cell, adding rows and columns
        if the block does not fit. This is a single undo step.
        :param top: The first row.
        :param left: The first column.
        :param block: The values.
        :param text: The undo command text.
        :param headers: The column names for the block, if any.
        :return: None
        """

        def fun() -> None:
            width = max([len(r) for r in block] + [len(headers or [])])
            while len(self.headers) < left + width:
                self.headers.append(f"Column {len(self.headers) + 1}")
            if headers:
                for i, name in enumerate(headers):
                    self.headers[left + i] = name
            while len(self.rows) < top + len(block):
                self.rows.append([""] * len(self.headers))
            for r, values in enumerate(block):
                row = self.rows[top + r]
                row.extend([""] * (len(self.headers) - len(row)))
                for c, value in enumerate(values):
                    row[left + c] = value

        self.edit(text, fun)

    def clear_cells(self, cells: list[tuple[int, int]]) -> None:
        def fun() -> None:
            for row, col in cells:
                self.rows[row][col] = ""

        self.edit("Clear cells", fun)


def parse_clipboard(text: str) -> list[list[str]]:
    """
    Parses the text copied from Excel (tab-separated, with quoted cells when they
    contain tabs or line breaks).
    :param text: The clipboard text.
    :return: The rows.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    if text == "":
        return []
    return [list(r) for r in csv.reader(io.StringIO(text), delimiter="\t")]


class DataGridView(QTableView):
    def __init__(self, model: DataGridModel, parent=None):
        """
        Initialises the view.
        :param model: The DataGridModel instance.
        :param parent: The parent widget.
        """
        super().__init__(parent)
        self.setModel(model)
        self.grid: DataGridModel = model
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.horizontalHeader().sectionDoubleClicked.connect(self._rename_column)

        # every edit rebuilds the model: keep the cursor and selection in place
        self._saved_selection: tuple[tuple[int, int], list[tuple[int, int]]] | None = None
        self.grid.modelAboutToBeReset.connect(self._save_selection)
        self.grid.modelReset.connect(self._restore_selection)

    def _save_selection(self) -> None:
        current = self.currentIndex()
        self._saved_selection = (
            (current.row(), current.column()),
            self._selected_cells(),
        )

    def _restore_selection(self) -> None:
        if self._saved_selection is None:
            return
        (row, col), cells = self._saved_selection
        self._saved_selection = None
        model = self.grid
        rows, cols = model.rowCount(), model.columnCount()

        # one range per run of adjacent cells in a row, as tables can be large
        selection = QItemSelection()
        run: tuple[int, int, int] | None = None  # row, first column, last column
        for r, c in [(r, c) for r, c in cells if r < rows and c < cols]:
            if run and run[0] == r and run[2] == c - 1:
                run = (r, run[1], c)
                continue
            if run:
                selection.select(model.index(run[0], run[1]), model.index(run[0], run[2]))
            run = (r, c, c)
        if run:
            selection.select(model.index(run[0], run[1]), model.index(run[0], run[2]))

        if row < rows and col < cols and row >= 0 and col >= 0:
            self.setCurrentIndex(model.index(row, col))
        self.selectionModel().select(
            selection, QItemSelectionModel.SelectionFlag.ClearAndSelect
        )

    def _selected_cells(self) -> list[tuple[int, int]]:
        return sorted((i.row(), i.column()) for i in self.selectedIndexes())

    def selection_text(self) -> str:
        """
        Gets the selected cells as tab-separated text. Cells outside the selection
        within its bounding box are copied as empty, as in Excel.
        :return: The text.
        """
        cells = self._selected_cells()
        if not cells:
            return ""
        selected = set(cells)
        r0, r1 = cells[0][0], cells[-1][0]
        c0 = min(c for _, c in cells)
        c1 = max(c for _, c in cells)
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
        for r in range(r0, r1 + 1):
            writer.writerow(
                [
                    self.grid.rows[r][c] if (r, c) in selected else ""
                    for c in range(c0, c1 + 1)
                ]
            )
        return buffer.getvalue()

    def copy(self) -> None:
        text = self.selection_text()
        # do not wipe the clipboard when nothing is selected
        if text:
            QGuiApplication.clipboard().setText(text)

    def cut(self) -> None:
        if not self._selected_cells():
            return
        self.copy()
        self.delete_selection()

    def delete_selection(self) -> None:
        cells = self._selected_cells()
        if cells:
            self.grid.clear_cells(cells)

    def paste(self, with_header: bool = False) -> None:
        """
        Pastes the clipboard at the current cell. A single value fills the whole
        selection.
        :param with_header: Whether the first pasted row contains the column names.
        :return: None
        """
        block = parse_clipboard(QGuiApplication.clipboard().text())
        if not block:
            return
        cells = self._selected_cells()
        if cells:
            top, left = cells[0][0], min(c for _, c in cells)
        else:
            top = left = 0

        headers = None
        if with_header:
            headers, block = block[0], block[1:]
        if len(block) == 1 and len(block[0]) == 1 and len(cells) > 1:
            value = block[0][0]
            self.grid.edit(
                "Fill",
                lambda: [self.grid.rows[r].__setitem__(c, value) for r, c in cells],
            )
            return
        self.grid.set_block(top, left, block, headers=headers)

    def keyPressEvent(self, event: PySide6.QtGui.QKeyEvent) -> None:
        if self.state() == QAbstractItemView.State.EditingState:
            return super().keyPressEvent(event)

        if event.matches(QKeySequence.StandardKey.Undo):
            self.grid.undo_stack.undo()
        elif event.matches(QKeySequence.StandardKey.Redo) or (
            event.key() == Qt.Key.Key_Y
            and event.modifiers() == Qt.KeyboardModifier.ControlModifier
        ):
            self.grid.undo_stack.redo()
        elif event.matches(QKeySequence.StandardKey.Copy):
            self.copy()
        elif event.matches(QKeySequence.StandardKey.Cut):
            self.cut()
        elif event.matches(QKeySequence.StandardKey.Paste):
            self.paste()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selection()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # QTableView ignores Return, which would let a dialog default button
            # handle it. Start editing the cell instead
            if self.currentIndex().isValid():
                self.edit(self.currentIndex())
            event.accept()
        else:
            super().keyPressEvent(event)

    def event(self, event) -> bool:
        # stop the shortcuts of parent widgets or dialogs from stealing the keys
        if event.type() == event.Type.ShortcutOverride:
            if (
                event.matches(QKeySequence.StandardKey.Undo)
                or event.matches(QKeySequence.StandardKey.Redo)
                or event.matches(QKeySequence.StandardKey.Paste)
            ) and self.state() != QAbstractItemView.State.EditingState:
                event.accept()
                return True
        return super().event(event)

    def _rename_column(self, column: int) -> None:
        name, ok = QInputDialog.getText(
            self, "Rename column", "Column name", text=self.grid.headers[column]
        )
        if ok and name:
            self.grid.rename_column(column, name)

    def _show_menu(self, pos) -> None:
        self._build_menu().exec(self.viewport().mapToGlobal(pos))

    def _build_menu(self) -> QMenu:
        """
        Builds the context menu.
        :return: The menu.
        """
        menu = QMenu(self)
        actions = [
            ("Undo", self.grid.undo_stack.undo, self.grid.undo_stack.canUndo()),
            ("Redo", self.grid.undo_stack.redo, self.grid.undo_stack.canRedo()),
            None,
            ("Copy", self.copy, True),
            ("Paste", self.paste, True),
            ("Paste with header row", lambda: self.paste(True), True),
            None,
            ("Insert row above", self._insert_row, True),
            ("Insert column left", self._insert_column, True),
            ("Delete selected rows", self._remove_rows, True),
            ("Delete selected columns", self._remove_columns, True),
        ]
        for item in actions:
            if item is None:
                menu.addSeparator()
                continue
            label, fun, enabled = item
            action = QAction(label, menu)
            action.setEnabled(enabled)
            action.triggered.connect(fun)
            menu.addAction(action)
        return menu

    def _insert_row(self) -> None:
        self.grid.insert_rows(max(self.currentIndex().row(), 0))

    def _insert_column(self) -> None:
        self.grid.insert_column(max(self.currentIndex().column(), 0))

    def _remove_rows(self) -> None:
        rows = [i.row() for i in self.selectionModel().selectedRows()] or [
            r for r, _ in self._selected_cells()
        ]
        if rows:
            self.grid.remove_rows(rows)

    def _remove_columns(self) -> None:
        cols = [i.column() for i in self.selectionModel().selectedColumns()] or [
            c for _, c in self._selected_cells()
        ]
        if cols:
            self.grid.remove_columns(cols)
