from typing import Any

from PySide6.QtWidgets import QTreeWidgetItem

"""
 Shows any value of a pywr-next component in the components tree: dictionaries and
 lists become nested items, and a metric is summarised on one line (for example
 "Parameter: demand" or "Literal: 10").
"""

SUMMARY_KEYS = ("name", "value", "table")
""" The keys that identify the target of a metric, in order of preference """


def summary(value: Any) -> str:
    """
    Returns a short description of a value.
    :param value: The value.
    :return: The description.
    """
    if isinstance(value, dict):
        kind = value.get("type")
        for key in SUMMARY_KEYS:
            if key in value and not isinstance(value[key], (dict, list)):
                return f"{kind}: {value[key]}" if kind else str(value[key])
        return str(kind) if kind else ""
    if isinstance(value, list):
        return f"{len(value)} items"
    return str(value)


def value_items(value: Any) -> list[QTreeWidgetItem]:
    """
    Returns the tree items showing the content of a dictionary or a list.
    :param value: The value.
    :return: The items, one per key or list item.
    """
    if isinstance(value, dict):
        entries = [
            (str(key).replace("_", " ").capitalize(), v) for key, v in value.items()
        ]
    elif isinstance(value, list):
        entries = [(f"Item {i + 1}", v) for i, v in enumerate(value)]
    else:
        return []

    items = []
    for label, item_value in entries:
        item = QTreeWidgetItem()
        item.setText(0, label)
        text = summary(item_value)
        item.setText(1, text)
        item.setToolTip(1, text)
        item.addChildren(value_items(item_value))
        items.append(item)
    return items
