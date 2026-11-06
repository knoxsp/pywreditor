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


class TreeWidgetComponent(QTreeWidgetItem):
    """A pywr-next component in a list of the network, such as a parameter."""

    def __init__(self, component: dict, kind: str, tag: str = "type"):
        """
        :param component: The component dictionary.
        :param kind: The key of the component kind, such as "parameter".
        :param tag: The key with the component type.
        """
        super().__init__()
        meta = component.get("meta") if isinstance(component, dict) else None
        self.name = meta.get("name") if isinstance(meta, dict) else None
        self.kind = kind
        self.setText(0, str(self.name))
        component_type = component.get(tag)
        self.setText(1, str(component_type) if component_type else "")
        self.setToolTip(0, str(self.name))
        values = {k: v for k, v in component.items() if k not in ("meta", tag)}
        self.addChildren(value_items(values))
