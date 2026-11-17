import copy
import shutil

import pytest
from PySide6.QtWidgets import QMessageBox

from pywr_editor import MainWindow
from pywr_editor.model.undo import ModelUndoCommand
from pywr_editor.widgets import DateEdit
from tests.utils import resolve_model_path


@pytest.fixture
def window(qtbot, tmp_path) -> MainWindow:
    file = tmp_path / "model.json"
    shutil.copy(resolve_model_path("model_1.json"), file)
    window = MainWindow(str(file))
    window.hide()
    # do not prompt to save the model when the window is closed
    window.prompt_unsaved_changes = False
    qtbot.addWidget(window)
    return window


class TestUndoModelChanges:
    def test_edit_is_undone_and_redone(self, window):
        model = window.model_config
        stack = window.undo_stack
        before = copy.deepcopy(model.json)
        count = stack.count()

        model.scenarios.update("new scenario", {"size": 3})
        assert stack.count() == count + 1
        assert stack.undoText() == "change scenarios"
        after = copy.deepcopy(model.json)
        assert after != before

        stack.undo()
        assert model.json == before
        assert not model.scenarios.exists("new scenario")
        stack.redo()
        assert model.json == after
        # undoing does not add entries
        assert stack.count() == count + 1

        # the change log shows what was done
        labels = [c.label for c in model.change_log.change_sets]
        assert labels[-2:] == ["Undo: change scenarios", "Redo: change scenarios"]

    def test_edits_made_together_are_one_step(self, window):
        model = window.model_config
        count = window.undo_stack.count()
        before = copy.deepcopy(model.json)
        model.scenarios.update("a", {"size": 1})
        model.scenarios.update("b", {"size": 2})
        model.json["metadata"]["title"] = "other"
        model.has_changed()
        assert window.undo_stack.count() == count + 1
        window.undo_stack.undo()
        assert model.json == before

    def test_undo_a_node_added_outside_the_schematic(self, window):
        model = window.model_config
        names = len(window.schematic.node_items)
        model.nodes.add(
            {"name": "Added", "type": "input", "position": {"schematic": [100, 100]}}
        )
        window.schematic.reload()
        assert len(window.schematic.node_items) == names + 1

        window.undo_stack.undo()
        assert "Added" not in model.nodes.names
        # the schematic is redrawn
        assert len(window.schematic.node_items) == names
        window.undo_stack.redo()
        assert len(window.schematic.node_items) == names + 1

    def test_timestepper_widgets_follow_the_undo(self, window):
        model = window.model_config
        original = model.start_date
        model.start_date = "2001-02-03"
        window.undo_stack.undo()
        assert model.start_date == original
        widget = window.findChild(DateEdit, "start_date")
        assert widget.date().toString("yyyy-MM-dd") == original
        window.undo_stack.redo()
        assert widget.date().toString("yyyy-MM-dd") == "2001-02-03"
        # showing the dates did not change the model again
        assert model.start_date == "2001-02-03"

    def test_schematic_edits_are_not_added_twice(self, window):
        model = window.model_config
        count = window.undo_stack.count()
        # dragging changes the position of the node before the command is added
        name = model.nodes.names[0]
        model.nodes.set_position(node_name=name, position=[10, 20])
        assert window.undo_stack.count() == count

        # the command of the schematic changes the model, and is one step
        from pywr_editor.schematic.commands.add_node_command import AddNodeCommand

        window.undo_stack.push(
            AddNodeCommand(
                window.schematic,
                {
                    "name": "FromCommand",
                    "type": "input",
                    "position": {"schematic": [50, 50]},
                },
            )
        )
        assert window.undo_stack.count() == count + 1
        window.undo_stack.undo()
        assert "FromCommand" not in model.nodes.names
        assert not ModelUndoCommand.is_running()

    def test_a_change_that_does_not_match_is_not_applied(self, window, monkeypatch):
        model = window.model_config
        warnings = []
        monkeypatch.setattr(
            QMessageBox, "warning", lambda *args: warnings.append(args[2])
        )
        model.scenarios.update("temp", {"size": 1})
        # the scenario is removed without the undo stack knowing
        model.json["scenarios"] = [
            s for s in model.json["scenarios"] if s["name"] != "temp"
        ]
        before = copy.deepcopy(model.json)
        window.undo_stack.undo()
        assert model.json == before
        assert len(warnings) == 1 and "cannot be undone" in warnings[0]


def test_all_commands_track_that_they_run():
    """
    The commands changing the model must be decorated with @tracked, otherwise their
    model changes are added to the undo stack a second time.
    """
    import importlib
    import inspect
    import pkgutil

    import pywr_editor.schematic.commands as package

    found = []
    for module_info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, ModelUndoCommand) and cls is not ModelUndoCommand:
                if cls.__module__ != module.__name__:
                    continue
                found.append(cls)
                for name in ("redo", "undo"):
                    assert hasattr(
                        getattr(cls, name), "__wrapped__"
                    ), f"{cls.__name__}.{name}() must be decorated with @tracked"
    assert len(found) >= 9
