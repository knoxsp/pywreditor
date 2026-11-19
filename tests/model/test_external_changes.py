import json
import os
import shutil

import pytest

from pywr_editor import MainWindow
from pywr_editor.model import ModelConfig
from tests.utils import model_path

V1_MODEL = model_path() / "model_1.json"


def legacy_model() -> dict:
    """
    A model as the previous versions of the editor saved it: with the editor data
    (shapes, node styles) in the model file, and without the empty lists.
    """
    return {
        "metadata": {"title": "Test", "minimum_version": "1.19.0"},
        "timestepper": {"start": "2020-01-01", "end": "2020-01-10", "timestep": 1},
        "nodes": [
            {
                "name": "Input",
                "type": "Input",
                "position": {"schematic": [10, 20], "node_color": "red"},
            },
            {"name": "Output", "type": "Output", "position": {"schematic": [30, 40]}},
        ],
        "edges": [["Input", "Output"]],
        "parameters": {},
        "recorders": {},
        "tables": {},
        "pywr_editor": {"shapes": [{"id": "s1", "type": "rectangle"}]},
    }


@pytest.fixture
def model_file(tmp_path):
    file = tmp_path / "model.json"
    file.write_text(json.dumps(legacy_model(), indent=4))
    return file


class TestFileChangedExternally:
    def test_legacy_model_is_not_a_change(self, model_file):
        """
        Tests that a model that has editor data, or that the editor completes when it
        loads it, is not reported as changed, whatever its formatting is.
        """
        config = ModelConfig(str(model_file))
        assert config.load_error is None
        assert not config.file_changed_externally()
        # the file is touched, but not changed
        os.utime(model_file, ns=(1, 1))
        assert not config.file_changed_externally()
        assert not config.file_changed_externally()

    def test_change_by_another_program(self, model_file):
        config = ModelConfig(str(model_file))
        model = legacy_model()
        model["metadata"]["title"] = "Changed outside"
        model_file.write_text(json.dumps(model))
        assert config.file_changed_externally()
        # it is reported until the model is loaded again
        assert config.file_changed_externally()
        assert not ModelConfig(str(model_file)).file_changed_externally()

    def test_the_file_is_not_changed_by_the_editor_itself(self, model_file):
        config = ModelConfig(str(model_file))
        config.json["metadata"]["title"] = "Saved by the editor"
        assert config.save() is True
        assert not config.file_changed_externally()

    def test_missing_or_partial_file_is_not_a_change(self, model_file):
        config = ModelConfig(str(model_file))
        model_file.unlink()
        assert not config.file_changed_externally()

    def test_model_without_a_file(self):
        assert not ModelConfig().file_changed_externally()


@pytest.fixture
def window(qtbot, model_file, monkeypatch):
    window = MainWindow(str(model_file))
    window.hide()
    window.timer.stop()
    monkeypatch.setattr(window, "window", lambda: window)
    monkeypatch.setattr(window, "isActiveWindow", lambda: True)
    opened = []
    monkeypatch.setattr(
        "pywr_editor.main_window.MainWindow", lambda file: opened.append(file)
    )
    window.reopened = opened
    yield window
    window.model_config.reset_change_flag()
    window.close()


class TestListenForChanges:
    def test_legacy_model_is_not_reloaded(self, window):
        """
        Tests that the editor does not reload a model that contains the editor data
        again and again, when nobody changed it.
        """
        for _ in range(3):
            window.listen_for_changes()
        assert window.reopened == []

    def test_external_change_reloads_the_model(self, window, model_file):
        model = legacy_model()
        model["metadata"]["title"] = "Changed outside"
        model_file.write_text(json.dumps(model))
        window.listen_for_changes()
        assert window.reopened == [str(model_file)]
