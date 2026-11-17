import difflib
import json

from PySide6 import QtGui
from PySide6.QtGui import QFont, QTextCharFormat
from PySide6.QtWidgets import QPlainTextEdit

from pywr_editor.style import Color, Theme


def json_diff(
    old: dict | str, new: dict | str, old_name: str, new_name: str, context: int = 3
) -> str:
    """
    Compares two JSON documents line by line, after formatting them in the same way,
    so that only the real differences are shown.
    :param old: The original document, as dictionary or JSON string.
    :param new: The new document, as dictionary or JSON string.
    :param old_name: The name of the original document.
    :param new_name: The name of the new document.
    :param context: The number of unchanged lines to show around each difference.
    :return: The diff in the unified format. Empty if there are no differences.
    """
    texts = []
    for document in (old, new):
        if isinstance(document, str):
            document = json.loads(document)
        texts.append(json.dumps(document, indent=2).splitlines())
    return "\n".join(
        difflib.unified_diff(
            texts[0],
            texts[1],
            fromfile=old_name,
            tofile=new_name,
            n=context,
            lineterm="",
        )
    )


class DiffHighlighter(QtGui.QSyntaxHighlighter):
    def __init__(self, parent: QtGui.QTextDocument):
        """
        Initialises the highlighter colouring added and removed lines.
        :param parent: The document.
        """
        super().__init__(parent)
        self.set_formats()

    def set_formats(self) -> None:
        """
        Sets the formats. The colours depend on the active theme.
        :return: None
        """
        self.added = QTextCharFormat()
        self.added.setBackground(Color("green", 200).qcolor)
        self.removed = QTextCharFormat()
        self.removed.setBackground(Color("red", 200).qcolor)
        self.header = QTextCharFormat()
        self.header.setForeground(Color("blue", 800).qcolor)
        self.header.setFontWeight(QFont.DemiBold)

    def refresh(self) -> None:
        """
        Applies the colours of the active theme and highlights the text again.
        :return: None
        """
        self.set_formats()
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        """
        Colours a line of the diff.
        :param text: The line.
        :return: None
        """
        if text.startswith(("+++", "---", "@@")):
            self.setFormat(0, len(text), self.header)
        elif text.startswith("+"):
            self.setFormat(0, len(text), self.added)
        elif text.startswith("-"):
            self.setFormat(0, len(text), self.removed)


class JsonDiffEditor(QPlainTextEdit):
    def __init__(self):
        """
        Initialises the read-only view of the differences between two JSON documents.
        """
        super().__init__()
        self.has_differences = False
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont()
        font.setStyleHint(QFont.Monospace, QFont.PreferAntialias)
        self.setFont(font)
        self.highlighter = DiffHighlighter(self.document())
        Theme.on_change(self, lambda w: w.highlighter.refresh())

    def show_diff(self, old: dict | str, new: dict | str, old_name: str, new_name: str):
        """
        Shows the differences between two documents.
        :param old: The original document.
        :param new: The new document.
        :param old_name: The name of the original document.
        :param new_name: The name of the new document.
        :return: None
        """
        text = json_diff(old, new, old_name, new_name)
        self.setPlainText(text or f"There are no differences from {old_name}.")
        self.has_differences = bool(text)
