import copy
from typing import Any

from pywr_editor.model.change_log import (
    _ITEM_KEYS,
    _MISSING,
    ADDED,
    CHANGED,
    REMOVED,
    REORDERED,
    ByKey,
    Change,
    _canonical,
    format_path,
)

"""
 Applies the changes of the change log to a model, forwards (redo) or backwards (undo).

 The changes are applied in phases so that the result does not depend on the order of
 the changes: first the values are deleted, then the lists are reordered, the values
 are changed and finally the values are inserted at their original position, from the
 first to the last.
"""


class PatchError(Exception):
    """Raised when the changes do not match the model, e.g. a node is missing."""


def _find(container: list, key: ByKey) -> int:
    """
    Finds an item of a list.
    :param container: The list.
    :param key: The path item identifying the item.
    :return: The index of the item.
    """
    for index, item in enumerate(container):
        if key.field is not None:
            if isinstance(item, dict) and item.get(key.field) == str(key):
                return index
        elif _canonical(item) == str(key):
            return index
    raise PatchError(f"{key!r} is not in the list")


def _resolve(model: Any, path: tuple) -> Any:
    """
    Returns the value at a path.
    :param model: The model.
    :param path: The path items.
    :return: The value.
    """
    value = model
    for position, item in enumerate(path):
        where = format_path(path[: position + 1])
        try:
            if isinstance(item, ByKey):
                value = value[_find(value, item)]
            else:
                value = value[item]
        except (KeyError, IndexError, TypeError) as error:
            raise PatchError(f"{where} does not exist in the model") from error
    return value


def _delete(model: Any, change: Change) -> None:
    parent = _resolve(model, change.path[:-1])
    key = change.path[-1]
    if isinstance(parent, dict):
        if key not in parent:
            raise PatchError(f"{change.path_text} does not exist in the model")
        del parent[key]
    elif isinstance(parent, list) and isinstance(key, ByKey):
        del parent[_find(parent, key)]
    else:
        raise PatchError(f"{change.path_text} cannot be removed")


def _insert(model: Any, change: Change, value: Any) -> None:
    parent = _resolve(model, change.path[:-1])
    key = change.path[-1]
    value = copy.deepcopy(value)
    if isinstance(parent, dict):
        if key in parent:
            raise PatchError(f"{change.path_text} already exists in the model")
        items = list(parent.items())
        position = len(items) if change.index is None else min(change.index, len(items))
        items.insert(position, (key, value))
        # the dictionary is changed in place, as other objects can refer to it
        parent.clear()
        parent.update(items)
    elif isinstance(parent, list) and isinstance(key, ByKey):
        position = (
            len(parent) if change.index is None else min(change.index, len(parent))
        )
        parent.insert(position, value)
    else:
        raise PatchError(f"{change.path_text} cannot be added")


def _set(model: Any, change: Change, value: Any) -> None:
    if not change.path:
        raise PatchError("The model cannot be replaced")
    parent = _resolve(model, change.path[:-1])
    key = change.path[-1]
    try:
        parent[key] = copy.deepcopy(value)
    except (KeyError, IndexError, TypeError) as error:
        raise PatchError(f"{change.path_text} does not exist in the model") from error


def _reorder(model: Any, change: Change, order: list[str]) -> None:
    target = _resolve(model, change.path)
    if not isinstance(target, list):
        raise PatchError(f"{change.path_text} is not a list")
    # items identified by their name or id
    for field in _ITEM_KEYS:
        if all(isinstance(i, dict) and i.get(field) in order for i in target):
            position = {name: index for index, name in enumerate(order)}
            target.sort(key=lambda item: position[item[field]])
            return

    # items identified by their content. Equal items take the positions in turn
    slots: dict[str, list[int]] = {}
    for index, text in enumerate(order):
        slots.setdefault(text, []).append(index)
    positions = []
    for item in target:
        free = slots.get(_canonical(item))
        if not free:
            raise PatchError(f"The items of {change.path_text} cannot be reordered")
        positions.append(free.pop(0))
    target[:] = [item for _, item in sorted(zip(positions, target), key=lambda x: x[0])]


def apply_changes(model: dict, changes: list[Change], reverse: bool = False) -> None:
    """
    Applies changes to the model, in place. The model is not changed if the changes
    do not match it.
    :param model: The model dictionary.
    :param changes: The changes of the change log.
    :param reverse: Whether to undo the changes.
    :return: None
    """
    # try on a copy first, so that the model is not left half-changed
    apply_to = copy.deepcopy(model)
    for target in (apply_to, model):
        _apply(target, changes, reverse)


def _apply(model: dict, changes: list[Change], reverse: bool) -> None:
    inserts, deletes, reorders, sets = [], [], [], []
    for change in changes:
        kind = change.kind
        if reverse:
            kind = {ADDED: REMOVED, REMOVED: ADDED}.get(kind, kind)
        value = change.old if reverse else change.new
        if kind == REMOVED:
            deletes.append(change)
        elif kind == ADDED:
            # the value that is inserted is the one that the change adds, or removes
            inserts.append((change, change.old if reverse else change.new))
        elif kind == REORDERED:
            reorders.append((change, value))
        elif kind == CHANGED:
            sets.append((change, value))

    for change in deletes:
        _delete(model, change)
    for change, order in reorders:
        _reorder(model, change, order)
    for change, value in sets:
        _set(model, change, value)
    # insert at the original position, from the first to the last
    for change, value in sorted(
        inserts, key=lambda c: -1 if c[0].index is None else c[0].index
    ):
        if value is _MISSING:
            raise PatchError(f"{change.path_text} has no value")
        _insert(model, change, value)
