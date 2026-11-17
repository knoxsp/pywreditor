import copy
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator

"""
 The change log keeps every change applied to the model as a discrete diff.

 The model emits ModelConfig.has_changed() each time it is edited. The log compares the
 model with a copy taken after the previous change (the snapshot) and stores the
 differences as a ChangeSet, which is a list of Change instances, each describing one
 value that was added, removed or changed. Comparing snapshots means that every
 edit is logged without the code that edits the model having to describe it.

 Items of lists that are dictionaries with a unique "name" or "id" (nodes, scenarios,
 shapes, ...) are matched by that value, so that adding a node does not look like all
 the following nodes changed. The change path then reads, for example,
 nodes["Reservoir"].max_flow.
"""

ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"
REORDERED = "reordered"
""" The kind of change """

MAX_CHANGE_SETS = 2000
""" The oldest change sets are dropped when the log grows over this number """
_ITEM_KEYS = ("name", "id")
""" The keys used to match the dictionaries in a list """
_MISSING = object()


class ByKey(str):
    """
    A path item identifying a list item by the value of its "name" or "id" key, as
    opposed to its index. For the items that are not dictionaries (e.g. edges) the
    item is identified by its content as JSON, and the field is None.
    """

    field: str | None = None
    """ The key of the item holding the value """

    def __new__(cls, value: str, field: str | None = None):
        item = super().__new__(cls, value)
        item.field = field
        return item


PathItem = str | int | ByKey


def format_path(path: tuple[PathItem, ...]) -> str:
    """
    Formats a path as a readable string, e.g. nodes["Reservoir"].max_flow
    :param path: The path items.
    :return: The path as string. The root of the model is "model".
    """
    text = ""
    for item in path:
        if isinstance(item, ByKey):
            text += f"[{json.dumps(str(item))}]"
        elif isinstance(item, int):
            text += f"[{item}]"
        else:
            text += f".{item}" if text else str(item)
    return text or "model"


def format_value(value: Any, max_length: int = 60) -> str:
    """
    Formats a value for display.
    :param value: The value.
    :param max_length: The length at which the text is cut.
    :return: The value as JSON, or "-" if the value does not exist.
    """
    if value is _MISSING:
        return "-"
    # noinspection PyBroadException
    try:
        text = json.dumps(value, sort_keys=True)
    except Exception:
        text = repr(value)
    if len(text) > max_length:
        text = text[: max_length - 1] + "…"
    return text


@dataclass(frozen=True)
class Change:
    """A single value that was added, removed or changed."""

    kind: str
    """ ADDED, REMOVED, CHANGED or REORDERED """
    path: tuple[PathItem, ...]
    """ Where the value is in the model """
    old: Any = _MISSING
    """ The value before the change. Missing if it was added """
    new: Any = _MISSING
    """ The value after the change. Missing if it was removed """
    index: int | None = None
    """ The position of an added value in the new dictionary or list, or of a removed
    value in the old one. This allows restoring the order. For a REORDERED change, old
    and new are the order of the items that are in both lists """

    @property
    def section(self) -> str:
        """The top level key of the model that was changed, e.g. "nodes"."""
        return str(self.path[0]) if self.path else "model"

    @property
    def path_text(self) -> str:
        """The path as readable string."""
        return format_path(self.path)

    @property
    def description(self) -> str:
        """A one-line description of the change."""
        path = self.path_text
        if self.kind == ADDED:
            return f"Added {path}: {format_value(self.new)}"
        if self.kind == REMOVED:
            return f"Removed {path}: {format_value(self.old)}"
        if self.kind == REORDERED:
            return f"Reordered {path}"
        return f"Changed {path}: {format_value(self.old)} → {format_value(self.new)}"

    def to_dict(self) -> dict:
        """Returns the change as JSON-serialisable dictionary."""
        out: dict[str, Any] = {"kind": self.kind, "path": self.path_text}
        if self.old is not _MISSING:
            out["old"] = self.old
        if self.new is not _MISSING:
            out["new"] = self.new
        return out


@dataclass
class ChangeSet:
    """The changes applied to the model by one edit."""

    number: int
    """ The position of the edit in the log, starting from 1 """
    time: datetime
    changes: list[Change] = field(default_factory=list)
    label: str | None = None
    """ What the user did, if the code that edited the model said so """

    @property
    def sections(self) -> list[str]:
        """The model sections affected by the edit, in the order they changed."""
        return list(dict.fromkeys(change.section for change in self.changes))

    @property
    def summary(self) -> str:
        """A one-line description of the edit."""
        if self.label:
            return self.label
        if len(self.changes) == 1:
            return self.changes[0].description
        counts = {
            kind: sum(1 for c in self.changes if c.kind == kind)
            for kind in (ADDED, REMOVED, CHANGED, REORDERED)
        }
        parts = [f"{count} {kind}" for kind, count in counts.items() if count]
        return f"{len(self.changes)} changes in {', '.join(self.sections)} " + (
            f"({', '.join(parts)})"
        )

    def to_dict(self) -> dict:
        """Returns the edit as JSON-serialisable dictionary."""
        return {
            "number": self.number,
            "time": self.time.isoformat(timespec="seconds"),
            "label": self.label,
            "changes": [change.to_dict() for change in self.changes],
        }


def _is_keyed(items: list, key: str) -> bool:
    """True if all the items are dictionaries with a unique string value for the key."""
    if not all(isinstance(item, dict) for item in items):
        return False
    values = [item.get(key) for item in items]
    return all(isinstance(v, str) for v in values) and len(set(values)) == len(values)


def _item_key(old: list, new: list) -> str | None:
    """
    Finds the key that identifies the items of two lists.
    :return: The key if the items of both lists are dictionaries with a unique value
    for it, None otherwise.
    """
    if not old and not new:
        return None
    for key in _ITEM_KEYS:
        if _is_keyed(old, key) and _is_keyed(new, key):
            return key
    return None


def _canonical(value: Any) -> str:
    """Returns a string identifying a value, to compare values of any type."""
    # noinspection PyBroadException
    try:
        return json.dumps(value, sort_keys=True)
    except Exception:
        return repr(value)


def _diff_lists(old: list, new: list, path: tuple) -> Iterator[Change]:
    """Compares two lists. See diff()."""
    key = _item_key(old, new)
    # match dictionaries by name
    if key is not None:
        old_items = {item[key]: item for item in old}
        new_items = {item[key]: item for item in new}
        for index, (name, item) in enumerate(old_items.items()):
            if name not in new_items:
                yield Change(REMOVED, path + (ByKey(name, key),), old=item, index=index)
        for index, (name, item) in enumerate(new_items.items()):
            if name not in old_items:
                yield Change(ADDED, path + (ByKey(name, key),), new=item, index=index)
            else:
                yield from diff(old_items[name], item, path + (ByKey(name, key),))
        kept_old = [name for name in old_items if name in new_items]
        kept_new = [name for name in new_items if name in old_items]
        if kept_old != kept_new:
            yield Change(REORDERED, path, old=kept_old, new=kept_new)
        return

    # same length: compare item by item
    if len(old) == len(new):
        for index, (old_item, new_item) in enumerate(zip(old, new)):
            yield from diff(old_item, new_item, path + (index,))
        return

    # different length: the items without a match are added or removed, regardless
    # of their position (e.g. edges)
    old_count = Counter(_canonical(item) for item in old)
    new_count = Counter(_canonical(item) for item in new)
    kept_old, kept_new = [], []
    for index, item in enumerate(old):
        text = _canonical(item)
        if new_count[text] < old_count[text]:
            old_count[text] -= 1
            yield Change(REMOVED, path + (ByKey(text),), old=item, index=index)
        else:
            kept_old.append(text)
    for index, item in enumerate(new):
        text = _canonical(item)
        if old_count[text] < new_count[text]:
            new_count[text] -= 1
            yield Change(ADDED, path + (ByKey(text),), new=item, index=index)
        else:
            kept_new.append(text)
    # the items in both lists are not in the same order
    if kept_old != kept_new:
        yield Change(REORDERED, path, old=kept_old, new=kept_new)


def diff(old: Any, new: Any, path: tuple[PathItem, ...] = ()) -> Iterator[Change]:
    """
    Compares two values and yields what changed.
    :param old: The value before the change.
    :param new: The value after the change.
    :param path: The path of the values in the model.
    :return: The changes, one for each value that was added, removed or changed.
    """
    if isinstance(old, dict) and isinstance(new, dict):
        for index, (key, value) in enumerate(old.items()):
            if key not in new:
                yield Change(REMOVED, path + (str(key),), old=value, index=index)
        for index, (key, value) in enumerate(new.items()):
            if key not in old:
                yield Change(ADDED, path + (str(key),), new=value, index=index)
            else:
                yield from diff(old[key], value, path + (str(key),))
    elif isinstance(old, list) and isinstance(new, list):
        yield from _diff_lists(old, new, path)
    # compare the type too, as 1 == True and 1 == 1.0 in Python
    elif type(old) is not type(new) or old != new:
        yield Change(CHANGED, path, old=old, new=new)


class ChangeLog:
    """
    Stores the changes applied to the model as a list of discrete diffs. The log is
    kept in memory, for the time the model is open.
    """

    def __init__(self):
        self.change_sets: list[ChangeSet] = []
        self._snapshot: Any = _MISSING
        self._counter = 0
        self._saved_number = 0
        self._opened: Any = _MISSING
        self._saved: Any = _MISSING

    @property
    def is_tracking(self) -> bool:
        """True if the log has a snapshot of the model to compare."""
        return self._snapshot is not _MISSING

    def start(self, model: dict) -> None:
        """
        Sets the state the following changes are compared with. The log is not cleared.
        :param model: The model dictionary.
        """
        self._snapshot = copy.deepcopy(model)
        # the model as it was opened and as it is in the file
        self._opened = copy.deepcopy(model)
        self._saved = copy.deepcopy(model)

    def baseline(self, since_saved: bool = False) -> Any:
        """
        The state the model is compared with in net_changes().
        :param since_saved: True to return the last saved state, False for the state
        when the model was opened.
        :return: The model dictionary, which must not be changed, or None if the log
        is not tracking.
        """
        baseline = self._saved if since_saved else self._opened
        return None if baseline is _MISSING else baseline

    def net_changes(self, model: dict, since_saved: bool = False) -> list[Change]:
        """
        Compares the model with its state when it was opened or last saved. Unlike the
        change sets, which list each edit, this is the overall difference: a value
        edited three times is one change, and an edit that was undone is not listed.
        :param model: The model dictionary.
        :param since_saved: Compare with the last saved state instead of the state
        when the model was opened.
        :return: The changes. Empty if the log is not tracking.
        """
        baseline = self._saved if since_saved else self._opened
        if baseline is _MISSING:
            return []
        return list(diff(baseline, model))

    def record(self, model: dict, label: str | None = None) -> ChangeSet | None:
        """
        Stores what changed in the model since the last time the log was updated.
        :param model: The model dictionary.
        :param label: A description of the edit. Optional.
        :return: The change set, or None if the model is not different from the
        snapshot or the log is not tracking.
        """
        if not self.is_tracking:
            return None
        # the changes refer to the copies of the model, so they are not altered by the
        # following edits
        current = copy.deepcopy(model)
        changes = list(diff(self._snapshot, current))
        if not changes:
            return None

        self._snapshot = current
        self._counter += 1
        change_set = ChangeSet(
            number=self._counter, time=datetime.now(), changes=changes, label=label
        )
        self.change_sets.append(change_set)
        if len(self.change_sets) > MAX_CHANGE_SETS:
            del self.change_sets[: len(self.change_sets) - MAX_CHANGE_SETS]
        return change_set

    def mark_saved(self, model: dict | None = None) -> None:
        """
        Remembers that the model was saved with the changes logged so far.
        :param model: The model dictionary that was saved. Default to the last state
        recorded in the log.
        """
        self._saved_number = self._counter
        if self.is_tracking:
            self._saved = copy.deepcopy(self._snapshot if model is None else model)

    @property
    def unsaved(self) -> list[ChangeSet]:
        """The change sets applied after the model was last saved."""
        return [c for c in self.change_sets if c.number > self._saved_number]

    def is_saved(self, change_set: ChangeSet) -> bool:
        """True if the change set was written to the model file."""
        return change_set.number <= self._saved_number

    def clear(self) -> None:
        """Removes the change sets. The snapshot is kept."""
        self.change_sets.clear()
        self._saved_number = self._counter

    def to_list(self) -> list[dict]:
        """Returns the log as JSON-serialisable list."""
        return [change_set.to_dict() for change_set in self.change_sets]

    def __len__(self) -> int:
        return len(self.change_sets)
