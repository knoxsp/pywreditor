from PySide6.QtGui import QBrush
from PySide6.QtWidgets import QTreeWidgetItem

from pywr_editor.model.change_log import ADDED, REMOVED, Change, format_value
from pywr_editor.style import Color


def change_item(change: Change, description_column: int = 2) -> QTreeWidgetItem:
    """
    Creates the tree item for a change. The kind of change is in the second column.
    :param change: The change.
    :param description_column: The column where to show the description.
    :return: The item.
    """
    texts = [""] * (description_column + 1)
    texts[1] = change.kind.capitalize()
    texts[description_column] = change.description
    item = QTreeWidgetItem(texts)
    item.setToolTip(
        description_column,
        f"{change.path_text}\n\nBefore: {format_value(change.old, 2000)}"
        f"\nAfter: {format_value(change.new, 2000)}",
    )
    if change.kind == ADDED:
        item.setForeground(1, QBrush(Color("green", 500).qcolor))
    elif change.kind == REMOVED:
        item.setForeground(1, QBrush(Color("red", 500).qcolor))
    return item
