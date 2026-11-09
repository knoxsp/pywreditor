import builtins
import json
import keyword
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import QProcess, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QKeyEvent,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.dialects.next import python_code as pc
from pywr_editor.style import Color
from pywr_editor.widgets import PushIconButton

if TYPE_CHECKING:
    from pywr_editor.model import ModelConfig

"""
 The code pane of a "Python" parameter in the parameters dialog. It shows the
 function or class the parameter calls, from the Python file next to the model (or
 the file the parameter names), highlights it, checks it as the user types and runs
 it in a separate process with test values.
"""

PYTHON_KEYWORDS = set(keyword.kwlist) | {"self", "cls"}
PYTHON_BUILTINS = {name for name in dir(builtins) if not name.startswith("_")}
CHECK_DELAY_MS = 400
""" The time after the last key press before the code is checked """

TOKENS = re.compile(
    r"""
    (?P<comment>\#.*)
  | (?P<triple>(?:[rRbBuUfF]{0,2})(?:\"\"\"|'''))
  | (?P<string>(?:[rRbBuUfF]{0,2})(?:"(?:[^"\\]|\\.)*(?:"|$)|'(?:[^'\\]|\\.)*(?:'|$)))
  | (?P<definition>\b(?:def|class)\s+)(?P<name>[A-Za-z_]\w*)
  | (?P<decorator>@[A-Za-z_][\w.]*)
  | (?P<number>\b\d[\d_]*\.?\d*(?:[eE][-+]?\d+)?\b)
  | (?P<word>[A-Za-z_]\w*)
    """,
    re.VERBOSE,
)


class PythonHighlighter(QSyntaxHighlighter):
    """Colours Python code. Multi-line strings are tracked with the block state."""

    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self.formats: dict[str, QTextCharFormat] = {}
        self.set_formats()

    def set_formats(self) -> None:
        """
        Sets the colours, which depend on the active theme.
        :return: None
        """

        def make(color: Color, bold: bool = False, italic: bool = False):
            text_format = QTextCharFormat()
            text_format.setForeground(color.qcolor)
            if bold:
                text_format.setFontWeight(QFont.Weight.DemiBold)
            text_format.setFontItalic(italic)
            return text_format

        self.formats = {
            "comment": make(Color("gray", 500), italic=True),
            "string": make(Color("orange", 800)),
            "number": make(Color("rose", 800)),
            "keyword": make(Color("purple", 700), bold=True),
            "builtin": make(Color("sky", 800)),
            "name": make(Color("blue", 800), bold=True),
            "decorator": make(Color("emerald", 800)),
        }

    def refresh(self) -> None:
        """
        Applies the colours of the active theme and highlights the text again.
        :return: None
        """
        self.set_formats()
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        position = 0
        # 0: normal, 1: inside a triple-single-quoted string, 2: inside triple-double
        state = self.previousBlockState()
        if state in (1, 2):
            quote = "'''" if state == 1 else '"""'
            end = text.find(quote)
            if end < 0:
                self.setFormat(0, len(text), self.formats["string"])
                self.setCurrentBlockState(state)
                return
            self.setFormat(0, end + 3, self.formats["string"])
            position = end + 3
        self.setCurrentBlockState(0)

        while True:
            match = TOKENS.search(text, position)
            if match is None:
                break
            kind = match.lastgroup
            start, end = match.span()
            if kind == "comment":
                self.setFormat(start, end - start, self.formats["comment"])
            elif kind == "triple":
                quote = match.group("triple")[-3:]
                close = text.find(quote, end)
                if close < 0:
                    self.setFormat(start, len(text) - start, self.formats["string"])
                    self.setCurrentBlockState(1 if quote == "'''" else 2)
                    return
                end = close + 3
                self.setFormat(start, end - start, self.formats["string"])
            elif kind == "string":
                self.setFormat(start, end - start, self.formats["string"])
            elif kind == "name":
                name_start = match.start("name")
                self.setFormat(
                    start,
                    len(match.group("definition").rstrip()),
                    self.formats["keyword"],
                )
                self.setFormat(name_start, end - name_start, self.formats["name"])
            elif kind == "decorator":
                self.setFormat(start, end - start, self.formats["decorator"])
            elif kind == "number":
                self.setFormat(start, end - start, self.formats["number"])
            elif kind == "word":
                word = match.group()
                if word in PYTHON_KEYWORDS:
                    self.setFormat(start, end - start, self.formats["keyword"])
                elif word in PYTHON_BUILTINS:
                    self.setFormat(start, end - start, self.formats["builtin"])
            position = max(end, start + 1)


class CodeEdit(QPlainTextEdit):
    """A plain text editor for code: monospace, with indentation helpers."""

    INDENT = "    "

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(max(font.pointSize(), 10))
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.highlighter = PythonHighlighter(self.document())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        cursor = self.textCursor()
        if key == Qt.Key.Key_Tab and not event.modifiers():
            if cursor.hasSelection():
                self.change_indent(indent=True)
            else:
                column = cursor.positionInBlock()
                cursor.insertText(" " * (4 - column % 4))
            return
        if key == Qt.Key.Key_Backtab:
            self.change_indent(indent=False)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            before = cursor.block().text()[: cursor.positionInBlock()]
            indent = re.match(r"\s*", before).group()
            if before.rstrip().endswith(":"):
                indent += self.INDENT
            super().keyPressEvent(event)
            self.insertPlainText(indent)
            return
        if key == Qt.Key.Key_Backspace and not cursor.hasSelection():
            before = cursor.block().text()[: cursor.positionInBlock()]
            if before and not before.strip() and len(before) % 4 == 0:
                # delete a whole level of indentation
                cursor.movePosition(
                    QTextCursor.MoveOperation.Left,
                    QTextCursor.MoveMode.KeepAnchor,
                    4,
                )
                cursor.removeSelectedText()
                return
        super().keyPressEvent(event)

    def change_indent(self, indent: bool) -> None:
        """
        Indents or dedents the selected lines, or the current line.
        :param indent: True to indent.
        :return: None
        """
        cursor = self.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        cursor.setPosition(start)
        first = cursor.blockNumber()
        cursor.setPosition(end)
        last = cursor.blockNumber()
        if end > start and cursor.positionInBlock() == 0 and last > first:
            last -= 1
        cursor.beginEditBlock()
        for number in range(first, last + 1):
            block = self.document().findBlockByNumber(number)
            line = QTextCursor(block)
            if indent:
                line.insertText(self.INDENT)
            else:
                removable = len(block.text()) - len(block.text().lstrip(" "))
                line.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor,
                    min(4, removable),
                )
                line.removeSelectedText()
        cursor.endEditBlock()

    def mark_problems(self, diagnostics: list[pc.Diagnostic]) -> None:
        """
        Underlines the lines with problems.
        :param diagnostics: The problems, with line numbers in the editor.
        :return: None
        """
        selections = []
        for diagnostic in diagnostics:
            if diagnostic.line < 1:
                continue
            block = self.document().findBlockByNumber(diagnostic.line - 1)
            if not block.isValid():
                continue
            selection = QTextEdit.ExtraSelection()
            text_format = QTextCharFormat()
            color = QColor("#d13438" if diagnostic.severity == "error" else "#c19c00")
            text_format.setUnderlineColor(color)
            text_format.setUnderlineStyle(
                QTextCharFormat.UnderlineStyle.WaveUnderline
            )
            selection.format = text_format
            cursor = QTextCursor(block)
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            selection.cursor = cursor
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, False)
            selections.append(selection)
        self.setExtraSelections(selections)

    def go_to_line(self, line: int) -> None:
        """
        Moves the cursor to a line.
        :param line: The line number, from 1.
        :return: None
        """
        block = self.document().findBlockByNumber(max(line - 1, 0))
        if block.isValid():
            self.setTextCursor(QTextCursor(block))
            self.setFocus()


class DryRunDialog(QDialog):
    """Runs a function or class for a few timesteps with test values."""

    def __init__(
        self,
        python: str,
        request: dict,
        parent: QWidget | None = None,
        timeout_seconds: int = 60,
    ):
        """
        Initialises the dialog.
        :param python: The Python interpreter to run the code with.
        :param request: The request from python_code.dry_run_request(), whose
        "metrics" and "indices" give the names (the values are the test values).
        :param parent: The parent widget. Optional.
        :param timeout_seconds: The seconds after which the code is stopped.
        """
        super().__init__(parent)
        self.python = python
        self.request = request
        self.timeout_seconds = timeout_seconds
        self.process: QProcess | None = None
        self.timed_out = False
        self.setWindowTitle(f"Test run of {request['name']}")
        self.setMinimumSize(560, 520)

        self.inputs = QTableWidget(0, 2)
        self.inputs.setObjectName("dry_run_inputs")
        self.inputs.setHorizontalHeaderLabels(["Metric or index", "Test value"])
        self.inputs.horizontalHeader().setStretchLastSection(True)
        self.inputs.verticalHeader().hide()
        self.inputs.setMaximumHeight(150)
        for kind, values in (("metric", request["metrics"]), ("index", request["indices"])):
            for name, value in values.items():
                row = self.inputs.rowCount()
                self.inputs.insertRow(row)
                label = QTableWidgetItem(name)
                label.setFlags(Qt.ItemFlag.ItemIsEnabled)
                label.setData(Qt.ItemDataRole.UserRole, kind)
                label.setToolTip(f"A {kind} given to the parameter")
                self.inputs.setItem(row, 0, label)
                self.inputs.setItem(row, 1, QTableWidgetItem(str(value)))

        self.steps = QSpinBox()
        self.steps.setObjectName("dry_run_steps")
        self.steps.setRange(1, 366)
        self.steps.setValue(int(request["steps"]))
        self.run_button = PushIconButton(icon="msc.play", label="Run", accent=True)
        self.run_button.setObjectName("dry_run_button")
        # noinspection PyUnresolvedReferences
        self.run_button.clicked.connect(self.run)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Timesteps"))
        controls.addWidget(self.steps)
        controls.addStretch()
        controls.addWidget(self.run_button)

        self.results = QTableWidget(0, 2)
        self.results.setObjectName("dry_run_results")
        self.results.setHorizontalHeaderLabels(["Date", "Value"])
        self.results.horizontalHeader().setStretchLastSection(True)
        self.results.verticalHeader().hide()
        self.results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.output = QPlainTextEdit()
        self.output.setObjectName("dry_run_output")
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("What the code prints and its errors are shown here")
        self.output.setMaximumHeight(160)
        self.status = QLabel(
            "The code runs in a separate process, with the Python of "
            f"{python}. The metrics and indices get the values above."
        )
        self.status.setWordWrap(True)

        layout = QVBoxLayout(self)
        if self.inputs.rowCount():
            layout.addWidget(self.inputs)
        layout.addLayout(controls)
        layout.addWidget(self.results, 1)
        layout.addWidget(self.output)
        layout.addWidget(self.status)

    def test_values(self) -> tuple[dict[str, float], dict[str, int]]:
        """
        Reads the test values.
        :return: The metric values and the index values.
        """
        metrics, indices = {}, {}
        for row in range(self.inputs.rowCount()):
            label = self.inputs.item(row, 0)
            text = self.inputs.item(row, 1).text().strip()
            if label.data(Qt.ItemDataRole.UserRole) == "metric":
                metrics[label.text()] = float(text or 0)
            else:
                indices[label.text()] = int(float(text or 0))
        return metrics, indices

    @Slot()
    def run(self) -> None:
        """
        Starts the process.
        :return: None
        """
        if self.process is not None:
            return
        try:
            metrics, indices = self.test_values()
        except ValueError:
            self.status.setText("The test values must be numbers")
            return
        request = {
            **self.request,
            "metrics": metrics,
            "indices": indices,
            "steps": self.steps.value(),
        }
        self.results.setRowCount(0)
        self.output.clear()
        self.run_button.setEnabled(False)
        self.status.setText("Running…")
        self.timed_out = False
        process = QProcess(self)
        self.process = process
        process.setWorkingDirectory(request["folder"])
        # noinspection PyUnresolvedReferences
        process.finished.connect(self.on_finished)
        # noinspection PyUnresolvedReferences
        process.errorOccurred.connect(self.on_error)
        process.start(self.python, ["-c", pc.DRY_RUN_PROGRAM])
        process.write(json.dumps(request).encode())
        process.closeWriteChannel()
        QTimer.singleShot(self.timeout_seconds * 1000, self.on_timeout)

    @Slot()
    def on_timeout(self) -> None:
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            self.timed_out = True
            self.process.kill()

    @Slot(QProcess.ProcessError)
    def on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.show_result(
                pc.DryRunResult(error=f"Python could not be started: {self.python}")
            )

    @Slot(int, QProcess.ExitStatus)
    def on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        process = self.process
        if process is None:
            return
        stdout = bytes(process.readAllStandardOutput()).decode(errors="replace")
        stderr = bytes(process.readAllStandardError()).decode(errors="replace")
        if self.timed_out:
            result = pc.DryRunResult(
                error=f"The code did not finish in {self.timeout_seconds} seconds"
            )
        else:
            result = pc.read_dry_run_reply(stdout, stderr)
        self.show_result(result)

    def show_result(self, result: "pc.DryRunResult") -> None:
        """
        Shows the values, the output and the error.
        :param result: The result of the run.
        :return: None
        """
        process, self.process = self.process, None
        if process is not None:
            process.deleteLater()
        self.run_button.setEnabled(True)
        self.results.setRowCount(len(result.values))
        for row, (when, value) in enumerate(result.values):
            self.results.setItem(row, 0, QTableWidgetItem(when.replace("T", " ")))
            self.results.setItem(row, 1, QTableWidgetItem(str(value)))
        text = result.printed.rstrip()
        if result.error:
            text = (text + "\n\n" if text else "") + result.error.rstrip()
        self.output.setPlainText(text)
        self.status.setText(
            f"The code failed after {len(result.values)} timesteps"
            if result.error
            else f"Ran {len(result.values)} timesteps"
        )

    def closeEvent(self, event) -> None:
        process, self.process = self.process, None
        if process is not None:
            process.kill()
            process.waitForFinished(2000)
            process.deleteLater()
        super().closeEvent(event)


class PythonCodePanel(QWidget):
    """
    Edits the code of a Python parameter. The form of the parameter says what the
    parameter calls; the panel shows that function or class from its file.
    """

    changed = Signal()
    """ Emitted when the user edits the code """

    def __init__(
        self,
        model: "ModelConfig",
        parameter_values: Callable[[], dict[str, Any]],
        parent: QWidget | None = None,
    ):
        """
        Initialises the panel.
        :param model: The model configuration.
        :param parameter_values: A function returning the current values of the
        parameter form (source, object, args, kwargs, metrics, indices...).
        :param parent: The parent widget. Optional.
        """
        super().__init__(parent)
        self.model = model
        self.parameter_values = parameter_values
        self.file: Path | None = None
        self.file_text = ""
        self.loaded: tuple[str, str] | None = None
        """ The kind and name of the object whose code is in the editor """
        self.dirty = False
        self.diagnostics: list[pc.Diagnostic] = []
        self.dry_run_dialog: DryRunDialog | None = None

        self.heading = QLabel()
        self.heading.setStyleSheet("font-weight: bold")
        self.file_label = QLabel()
        self.file_label.setObjectName("python_file")
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.reload_button = PushIconButton(icon="msc.refresh", label="Reload", small=True)
        self.reload_button.setToolTip("Read the code again from the file")
        self.open_button = PushIconButton(icon="msc.go-to-file", label="Open file", small=True)
        self.open_button.setToolTip("Open the file in your editor for Python files")
        self.test_button = PushIconButton(icon="msc.play", label="Test run…", small=True)
        self.test_button.setObjectName("python_test_button")
        # noinspection PyUnresolvedReferences
        self.reload_button.clicked.connect(self.reload)
        # noinspection PyUnresolvedReferences
        self.open_button.clicked.connect(self.open_file)
        # noinspection PyUnresolvedReferences
        self.test_button.clicked.connect(self.test_run)
        top = QHBoxLayout()
        top.addWidget(self.heading)
        top.addStretch()
        top.addWidget(self.reload_button)
        top.addWidget(self.open_button)
        top.addWidget(self.test_button)

        self.editor = CodeEdit()
        self.editor.setObjectName("python_code")
        self.editor.setMinimumHeight(160)
        # noinspection PyUnresolvedReferences
        self.editor.textChanged.connect(self.on_text_changed)

        self.problems = QListWidget()
        self.problems.setObjectName("python_problems")
        self.problems.setMaximumHeight(90)
        # noinspection PyUnresolvedReferences
        self.problems.itemActivated.connect(self.on_problem_activated)
        # noinspection PyUnresolvedReferences
        self.problems.itemClicked.connect(self.on_problem_activated)
        self.summary = QLabel()
        self.summary.setObjectName("python_summary")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.file_label)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.summary)
        layout.addWidget(self.problems)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(CHECK_DELAY_MS)
        # noinspection PyUnresolvedReferences
        self.timer.timeout.connect(self.check)
        self.refresh()

    # --- the file and the object ---------------------------------------------

    def target(self) -> pc.PythonTarget | None:
        """
        Returns what the parameter calls, from the form.
        """
        return pc.PythonTarget.from_parameter(self.parameter_values())

    def source_file(self) -> tuple[Path | None, str | None]:
        """
        Returns the file with the code of the parameter, from the form.
        :return: The file path (None if unknown) and a message when the code cannot
        be edited here.
        """
        source = self.parameter_values().get("source")
        folder = Path(self.model.json_file).parent if self.model.json_file else None
        if isinstance(source, dict) and source.get("type") == "Module":
            return None, (
                f'The code is in the module "{source.get("module")}", which the '
                "editor does not edit"
            )
        path = source.get("path") if isinstance(source, dict) else None
        if not path:
            if folder is None:
                return None, "Save the model to give its Python code a file"
            return pc.module_file(self.model.json_file), None
        file = Path(path)
        if not file.is_absolute():
            if folder is None:
                return None, "Save the model to edit the code of this parameter"
            file = folder / file
        return file, None

    def refresh(self) -> None:
        """
        Shows the code of the object the form names, when the user has not changed
        the code. Called when the form changes.
        :return: None
        """
        file, message = self.source_file()
        target = self.target()
        key = None if target is None else (target.kind, target.name)
        file_changed = file != self.file
        self.file = file
        usable = message is None and file is not None
        self.editor.setEnabled(usable)
        self.test_button.setEnabled(usable)
        self.open_button.setEnabled(usable)
        self.reload_button.setEnabled(usable)
        if not usable:
            self.heading.setText("Python code")
            self.file_label.setText(message or "")
            self.show_diagnostics([])
            self.summary.setText("")
            return
        self.file_label.setText(str(file))
        if file_changed or (self.is_untouched() and key != self.loaded):
            self.load(key, file_changed)
        self.timer.start()

    def is_untouched(self) -> bool:
        """
        Whether the code in the editor is what was loaded: the code in the file, or the
        code of a new function or class that the user did not change.
        """
        if not self.dirty:
            return True
        return (
            self.loaded is not None
            and self.editor.toPlainText() == pc.starter_code(*self.loaded)
        )

    def read_file(self) -> str:
        if self.file is not None and self.file.is_file():
            try:
                return self.file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return ""
        return ""

    def load(self, key: tuple[str, str] | None, reread: bool = True) -> None:
        """
        Shows the code of a function or class.
        :param key: The kind and name. None shows the whole file.
        :param reread: Whether to read the file again.
        :return: None
        """
        if reread or not self.file_text:
            self.file_text = self.read_file()
        self.loaded = key
        dirty = False
        if key is None:
            code = self.file_text
            self.heading.setText("Python code (all of the file)")
        else:
            span = pc.find_object(self.file_text, *key)
            if span is None:
                code = pc.starter_code(*key)
                dirty = True
                self.heading.setText(f"Python code (new {key[0].lower()} {key[1]})")
            else:
                lines = self.file_text.splitlines()[span[0] - 1 : span[1]]
                code = "\n".join(lines) + "\n"
                self.heading.setText(f"Python code ({key[0].lower()} {key[1]})")
        self.set_code(code, dirty=dirty)

    def set_code(self, code: str, dirty: bool) -> None:
        self.editor.blockSignals(True)
        self.editor.setPlainText(code)
        self.editor.blockSignals(False)
        self.dirty = dirty
        if dirty:
            self.changed.emit()

    @Slot()
    def reload(self) -> None:
        """
        Reads the code again from the file, discarding the changes in the editor.
        :return: None
        """
        self.load(self.key(), True)
        self.check()

    def key(self) -> tuple[str, str] | None:
        target = self.target()
        return None if target is None else (target.kind, target.name)

    @Slot()
    def open_file(self) -> None:
        if self.file is not None:
            if not self.file.exists():
                self.save()
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.file)))

    # --- editing and checks --------------------------------------------------

    @Slot()
    def on_text_changed(self) -> None:
        self.dirty = True
        self.changed.emit()
        self.timer.start()

    def schedule_check(self) -> None:
        """
        Checks the code soon. Called when the form changes.
        :return: None
        """
        self.refresh()

    def combined_text(self) -> tuple[str, tuple[int, int]]:
        """
        Returns the file as it would be saved, and the lines of the editor in it.
        """
        code = self.editor.toPlainText()
        if self.loaded is None:
            return code, (1, max(len(code.splitlines()), 1))
        span = pc.find_object(self.file_text, *self.loaded)
        return pc.splice(self.file_text, span, code)

    @Slot()
    def check(self) -> list[pc.Diagnostic]:
        """
        Checks the code against the parameter.
        :return: The problems in the editor, with line numbers in the editor.
        """
        if not self.editor.isEnabled():
            return []
        text, (first, last) = self.combined_text()
        found = pc.analyse(text, self.target())
        shown = []
        for item in found:
            if first <= item.line <= last:
                shown.append(item.shifted(1 - first))
            elif item.line == 0:
                shown.append(item)
            elif item.severity == "error":
                shown.append(
                    pc.Diagnostic(
                        0,
                        f"Line {item.line} of the file: {item.message}",
                        item.severity,
                    )
                )
        self.show_diagnostics(shown)
        return shown

    def show_diagnostics(self, diagnostics: list[pc.Diagnostic]) -> None:
        self.diagnostics = diagnostics
        self.problems.clear()
        for item in diagnostics:
            prefix = f"Line {item.line}: " if item.line else ""
            row = QListWidgetItem(f"{prefix}{item.message}")
            row.setData(Qt.ItemDataRole.UserRole, item.line)
            row.setForeground(QColor("#d13438" if item.severity == "error" else "#a37f00"))
            row.setToolTip(item.message)
            self.problems.addItem(row)
        self.problems.setVisible(bool(diagnostics))
        self.editor.mark_problems(diagnostics)
        errors = sum(d.severity == "error" for d in diagnostics)
        warnings = len(diagnostics) - errors
        if not diagnostics:
            self.summary.setText("No problems found")
        else:
            self.summary.setText(
                f"{errors} error{'s' if errors != 1 else ''}, "
                f"{warnings} warning{'s' if warnings != 1 else ''}"
            )

    @Slot(QListWidgetItem)
    def on_problem_activated(self, item: QListWidgetItem) -> None:
        line = item.data(Qt.ItemDataRole.UserRole)
        if line:
            self.editor.go_to_line(line)

    # --- saving ----------------------------------------------------------------

    def has_errors(self) -> bool:
        return any(d.severity == "error" for d in self.diagnostics)

    def save(self) -> bool:
        """
        Writes the code to its file.
        :return: True if the file was written (or there was nothing to write).
        """
        if self.file is None or not self.editor.isEnabled():
            return True
        text, _ = self.combined_text()
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(text, encoding="utf-8")
        except OSError as error:
            self.summary.setText(f"The file could not be written: {error}")
            return False
        self.file_text = text
        self.dirty = False
        if self.loaded is not None:
            code = self.editor.toPlainText()
            self.load(self.loaded, reread=False)
            if self.editor.toPlainText() != code:
                self.set_code(code, dirty=False)
        return True

    # --- test run -------------------------------------------------------------

    def timestep_settings(self) -> tuple[datetime | None, float]:
        """
        Reads the start date and the timestep length from the model.
        """
        time = (self.model.json or {}).get("time") or {}
        start = None
        try:
            start = datetime.fromisoformat(str(time.get("start")))
        except ValueError:
            pass
        timestep = time.get("timestep")
        days = timestep.get("days") if isinstance(timestep, dict) else None
        return start, float(days) if isinstance(days, (int, float)) else 1.0

    @Slot()
    def test_run(self) -> DryRunDialog | None:
        """
        Opens the dialog that runs the code with test values. The code in the editor
        is written to the file first.
        :return: The dialog, None if it cannot be opened.
        """
        target = self.target()
        python = pc.dry_run_python()
        if target is None:
            self.summary.setText("Name the function or class the parameter calls")
            return None
        if python is None:
            self.summary.setText(
                "Install pywr-next (Settings → pywr-next) to run the code"
            )
            return None
        if self.has_errors():
            self.summary.setText("Fix the errors before running the code")
            return None
        if not self.save():
            return None
        values = self.parameter_values()
        start, days = self.timestep_settings()
        return_type = values.get("return_type") or "Float"
        request = pc.dry_run_request(
            self.file,
            target.kind,
            target.name,
            list(target.args),
            target.kwargs,
            {name: 1.0 for name in target.metrics},
            {name: 0 for name in target.indices},
            return_type,
            start,
            5,
            days,
        )
        dialog = DryRunDialog(python, request, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()
        self.dry_run_dialog = dialog
        return dialog
