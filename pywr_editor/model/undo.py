import functools
import time
from typing import Callable

from PySide6.QtGui import QUndoCommand

from pywr_editor.model.change_log import Change
from pywr_editor.model.change_patch import PatchError, apply_changes

"""
 The undo commands that change the model.

 The schematic has its own commands (moving and connecting nodes, ...), that change the
 model and the schematic together. The other edits (parameters, scenarios, the model
 metadata, ...) are undone by ChangeSetCommand, which replays the changes of the change
 log backwards. The window creates one for each edit that is not done by a command.
"""

MERGE_SECONDS = 0.2
""" Edits made within this time are undone together, as one action of the user (e.g.
saving a dialog) can change the model more than once """
CHANGE_SET_COMMAND_ID = 0x4D43

SCHEMATIC_SECTIONS = ("edges", "pywr_editor")
""" The sections of the model the schematic changes by itself, while the user drags
items, and that its commands undo """


def tracked(method: Callable) -> Callable:
    """
    Decorator of the redo() and undo() methods of the commands changing the model. The
    model changes made while a command runs are part of the command and must not be
    added to the undo stack again: ModelUndoCommand.is_running() tells the window.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        ModelUndoCommand.running += 1
        try:
            return method(self, *args, **kwargs)
        finally:
            ModelUndoCommand.running -= 1

    return wrapper


class ModelUndoCommand(QUndoCommand):
    """
    Base class of the undo commands changing the model. Decorate redo() and undo()
    with @tracked.
    """

    running = 0
    """ The number of commands that are being done or undone """

    @staticmethod
    def is_running() -> bool:
        """Returns True if a command is doing or undoing a change."""
        return ModelUndoCommand.running > 0


def is_schematic_change(changes: list[Change]) -> bool:
    """
    Checks whether the changes are made by the schematic while items are dragged, and
    are undone by its own commands: the position and style of the nodes, the edges and
    the editor data.
    :param changes: The changes.
    :return: True if all the changes are of this type.
    """
    for change in changes:
        path = change.path
        if path and path[0] in SCHEMATIC_SECTIONS:
            continue
        if len(path) >= 3 and path[0] == "nodes" and path[2] == "position":
            continue
        return False
    return True


class ChangeSetCommand(ModelUndoCommand):
    def __init__(
        self,
        model_config,
        changes: list[Change],
        refresh: Callable[[set[str]], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ):
        """
        Initialises the command for changes that are already applied to the model.
        :param model_config: The ModelConfig instance.
        :param changes: The changes, as one edit.
        :param refresh: Function called with the changed sections of the model, after
        the changes are undone or done again, to update the widgets.
        :param on_error: Function called with the message when the changes cannot be
        applied, as the model is no longer as it was after the changes.
        """
        super().__init__()
        self.model_config = model_config
        self.groups: list[list[Change]] = [list(changes)]
        self.refresh = refresh
        self.on_error = on_error
        self._is_applied = True
        self._last_time = time.monotonic()
        self._set_text()

    @property
    def sections(self) -> set[str]:
        return {c.section for group in self.groups for c in group}

    def _set_text(self) -> None:
        sections = list(
            dict.fromkeys(s for g in self.groups for c in g for s in [c.section])
        )
        self.setText("change " + ", ".join(sections))

    def id(self) -> int:
        return CHANGE_SET_COMMAND_ID

    def mergeWith(self, other: QUndoCommand) -> bool:
        """
        Merges the edits made within a short time into one.
        :param other: The command that is added to the undo stack.
        :return: True if the command was merged.
        """
        if not isinstance(other, ChangeSetCommand):
            return False
        if other._last_time - self._last_time > MERGE_SECONDS:
            return False
        self.groups.extend(other.groups)
        self._last_time = other._last_time
        self._set_text()
        return True

    @tracked
    def redo(self) -> None:
        # the model already has the changes when the command is added to the stack
        if self._is_applied:
            self._is_applied = False
            return
        self._apply(reverse=False)

    @tracked
    def undo(self) -> None:
        self._apply(reverse=True)

    def _apply(self, reverse: bool) -> None:
        """
        Applies the changes to the model, one edit at a time.
        :param reverse: Whether to undo the changes.
        :return: None
        """
        try:
            for group in reversed(self.groups) if reverse else self.groups:
                apply_changes(self.model_config.json, group, reverse=reverse)
        except PatchError as error:
            if self.on_error is not None:
                self.on_error(
                    f"The change cannot be {'undone' if reverse else 'done again'} "
                    f"because the model is different from when it was made: {error}"
                )
            return

        self.model_config.has_changed(
            label=f"{'Undo' if reverse else 'Redo'}: {self.text()}"
        )
        if self.refresh is not None:
            self.refresh(self.sections)
