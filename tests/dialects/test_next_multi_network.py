import hashlib
import json
from pathlib import Path

import pytest
from PySide6.QtGui import QUndoCommand
from PySide6.QtWidgets import QInputDialog

from pywr_editor import MainWindow
from pywr_editor.model import ModelConfig

MULTI = Path(__file__).parents[1] / "json_models" / "pywr_next" / "multi1"


def copy_model(tmp_path: Path) -> Path:
    for name in ("model.json", "network1.json", "network2.json"):
        (tmp_path / name).write_text((MULTI / name).read_text())
    return tmp_path / "model.json"


def digest(folder: Path) -> dict[str, str]:
    return {
        f.name: hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(folder.iterdir())
    }


class TestLoadingANetwork:
    def test_first_network_is_the_default(self):
        model = ModelConfig(str(MULTI / "model.json"))
        assert model.is_valid()
        assert model.read_only is True
        assert model.network == "network1"
        assert model.network_names == ["network1", "network2"]
        assert model.nodes.names == ["supply1", "link1", "demand1"]
        assert "read-only" in model.read_only_note

    def test_choose_the_network_and_see_its_transfers(self):
        model = ModelConfig(str(MULTI / "model.json"), network="network2")
        assert model.network == "network2"
        assert 'Transfers into this network: "inflow" from "network1"' in (
            model.read_only_note
        )

    def test_the_time_domain_comes_from_the_model(self):
        model = ModelConfig(str(MULTI / "model.json"))
        assert model.json["time"]["start"] == "2015-01-01"

    def test_unknown_network(self):
        model = ModelConfig(str(MULTI / "model.json"), network="nope")
        assert model.is_valid() is False
        assert 'no network "nope"' in model.load_error

    def test_network_in_the_model_file(self, tmp_path):
        data = json.loads((MULTI / "model.json").read_text())
        data["networks"][0]["network"] = json.loads((MULTI / "network1.json").read_text())
        file = tmp_path / "model.json"
        file.write_text(json.dumps(data))
        model = ModelConfig(str(file))
        assert model.is_valid()
        assert model.nodes.names == ["supply1", "link1", "demand1"]
        assert "inline" in model.read_only_note

    def test_missing_network_file(self, tmp_path):
        file = copy_model(tmp_path)
        (tmp_path / "network1.json").unlink()
        model = ModelConfig(str(file))
        assert model.is_valid() is False
        assert "cannot be read" in model.load_error


class TestReadOnly:
    def test_save_refuses_and_the_files_do_not_change(self, tmp_path):
        file = copy_model(tmp_path)
        before = digest(tmp_path)
        model = ModelConfig(str(file))
        assert "read-only" in model.save()
        assert digest(tmp_path) == before

    def test_changing_a_loaded_network_does_not_touch_the_files(self, tmp_path):
        file = copy_model(tmp_path)
        before = digest(tmp_path)
        model = ModelConfig(str(file))
        model.nodes.delete("link1")
        model.save()
        assert digest(tmp_path) == before


@pytest.fixture
def window(qtbot, tmp_path):
    file = copy_model(tmp_path)
    window = MainWindow(str(file), network="network2")
    window.hide()
    yield window
    window.model_config.reset_change_flag()
    window.close()


class TestWindow:
    def test_window_is_locked(self, window):
        assert window.is_read_only and window.editing_locked
        assert "network network2" in window.windowTitle()
        assert window.app_actions.get("save-model").isEnabled() is False
        assert window.app_actions.get("edit-metadata").isEnabled() is False
        assert not window.run_widget.isEnabled()
        # it is not reloaded when the file differs from the view
        assert window.timer.isActive() is False
        assert len(window.schematic.node_items) == 3

    def test_the_nodes_cannot_be_moved(self, window):
        from PySide6.QtWidgets import QGraphicsItem

        for item in window.schematic.node_items.values():
            assert not item.flags() & QGraphicsItem.ItemIsMovable

    def test_commands_are_ignored(self, window):
        done = []

        class Command(QUndoCommand):
            def redo(self):
                done.append(True)

        window.undo_stack.push(Command())
        assert window.undo_stack.count() == 0
        assert done == []

    def test_closing_does_not_ask_to_save(self, window, monkeypatch):
        def fail(*args, **kwargs):
            raise AssertionError("asked to save")

        monkeypatch.setattr(MainWindow, "maybe_save", fail)
        window.model_config.json["metadata"]["title"] = "changed"
        window.model_config.changed_ = True
        assert window.close()


class TestAskingForTheNetwork:
    def test_the_user_chooses(self, qtbot, tmp_path, monkeypatch):
        file = copy_model(tmp_path)
        monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("network2", True))
        window = MainWindow(str(file))
        window.hide()
        try:
            assert window.model_config.network == "network2"
        finally:
            window.close()

    def test_cancel_shows_the_first_network(self, qtbot, tmp_path, monkeypatch):
        file = copy_model(tmp_path)
        monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("", False))
        window = MainWindow(str(file))
        window.hide()
        try:
            assert window.model_config.network == "network1"
        finally:
            window.close()
