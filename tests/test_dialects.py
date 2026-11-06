import pytest

from pywr_editor import MainWindow
from pywr_editor.dialects import detect_dialect, get_dialect
from pywr_editor.dialects.next import NextDialect
from pywr_editor.dialects.v1 import V1Dialect
from pywr_editor.dialogs import (
    ParametersDialog,
    RecordersDialog,
    ScenariosDialog,
    TablesDialog,
)
from pywr_editor.dialogs.search.search_model import SearchModel
from pywr_editor.model import ModelConfig
from tests.utils import resolve_model_path


class TestDetectDialect:
    @pytest.mark.parametrize(
        "model_json, key",
        [
            ({"timestepper": {}, "nodes": [], "edges": []}, "v1"),
            ({"time": {}, "network": {"nodes": [], "edges": []}}, "next"),
            ({"time": {}, "networks": [{"name": "a", "network": {}}]}, "next"),
            # unknown formats are read as v1 models, so that v1 validation reports why
            ({}, "v1"),
            ([], "v1"),
            ("text", "v1"),
            (None, "v1"),
            ({"network": "not an object"}, "v1"),
        ],
    )
    def test_detect(self, model_json, key):
        """
        Tests that the dialect is detected from the model content.
        """
        assert detect_dialect(model_json).key == key

    def test_multi_network(self):
        """
        Tests that multi-network pywr-next models are recognised.
        """
        assert NextDialect.is_multi_network({"networks": []}) is True
        assert NextDialect.is_multi_network({"network": {}}) is False

    def test_get_dialect(self):
        """
        Tests that dialects are found by key.
        """
        assert get_dialect("v1").label == "pywr v1"
        assert get_dialect("next").label == "pywr-next"
        with pytest.raises(KeyError):
            get_dialect("v3")

    @pytest.mark.parametrize("key", ["v1", "next"])
    def test_empty_model_is_detected(self, key):
        """
        Tests that the empty model of each dialect is detected as that dialect.
        """
        assert detect_dialect(get_dialect(key).empty_model()).key == key


class TestModelConfigDialect:
    def test_v1_model(self):
        """
        Tests that a v1 model gets the v1 dialect.
        """
        model = ModelConfig(resolve_model_path("model_1.json"))
        assert model.dialect.key == "v1"
        assert model.is_valid()

    def test_new_model(self):
        """
        Tests that a new model is a v1 model.
        """
        assert ModelConfig().dialect.key == "v1"

    def test_next_model_loads(self):
        """
        Tests that a pywr-next model is loaded with the pywr-next model layer.
        """
        model = ModelConfig(
            resolve_model_path("pywr_next/reservoir_with_evaporation1.json")
        )
        assert model.dialect.key == "next"
        assert model.is_valid(), model.load_error
        assert model.nodes.names == ["Catchment", "Reservoir", "Demand"]


class V1WithoutRecorders(V1Dialect):
    """A dialect like v1 but without recorders, as pywr-next will be."""

    def component_kinds(self) -> list:
        return [k for k in super().component_kinds() if k.key != "recorder"]


class TestDialectUi:
    @pytest.fixture
    def window(self, qtbot, monkeypatch, request):
        """
        Opens a v1 model, optionally with a dialect that has no recorders.
        """
        if getattr(request, "param", None) == "no-recorders":
            monkeypatch.setattr(
                "pywr_editor.model.model_config.detect_dialect",
                lambda _: V1WithoutRecorders(),
            )
        window = MainWindow(resolve_model_path("model_1.json"))
        window.hide()
        yield window
        window.model_config.reset_change_flag()
        window.close()

    def test_v1_component_dialogs(self, qtbot, window):
        """
        Tests that the v1 dialect adds a ribbon button for each component kind and
        that each opens its dialog.
        """
        expected = {
            "scenario": ScenariosDialog,
            "table": TablesDialog,
            "parameter": ParametersDialog,
            "recorder": RecordersDialog,
        }
        for key, dialog_class in expected.items():
            kind = window.model_config.dialect.component_kind(key)
            assert window.app_actions.get(kind.action_key) is not None
            window.app_actions.get(kind.action_key).trigger()
            dialogs = [d for d in window.findChildren(dialog_class) if d.isVisible()]
            assert len(dialogs) == 1, key
            dialogs[0].close()

    def test_show_component_selects_name(self, qtbot, window):
        """
        Tests that a component dialog opens with the component selected.
        """
        window.show_component("recorder", "storage")
        dialog = [d for d in window.findChildren(RecordersDialog) if d.isVisible()][0]
        assert dialog.pages.currentWidget().name == "storage"
        dialog.close()

    @pytest.mark.parametrize("window", ["no-recorders"], indirect=True)
    def test_dialect_without_recorders(self, qtbot, window):
        """
        Tests that the recorders are not shown when the dialect has none.
        """
        assert "edit-recorders" not in window.app_actions.registry
        assert "recorders" not in window.components_tree.items
        assert "parameters" in window.components_tree.items
        search_types = {
            row["type"] for row in SearchModel(window.model_config).model_data
        }
        assert "recorder" not in search_types
        assert "parameter" in search_types
        # does nothing instead of opening the dialog
        window.open_component_dialog("recorder", "storage")
        assert not [d for d in window.findChildren(RecordersDialog) if d.isVisible()]


def test_window_refuses_next_model_for_now(qtbot, monkeypatch):
    """
    Tests that the main window does not open a pywr-next model until the schematic
    and the dialogs support it.
    """
    messages = []
    monkeypatch.setattr(
        "pywr_editor.main_window.QMessageBox.critical",
        staticmethod(lambda parent, title, message: messages.append(message)),
    )
    monkeypatch.setattr("pywr_editor.dialogs.StartScreen", lambda: _NoWindow())
    MainWindow(resolve_model_path("pywr_next/reservoir_with_evaporation1.json"))
    assert messages == [
        "This is a pywr-next model. The editor cannot open pywr-next models yet"
    ]


class _NoWindow:
    def show(self) -> None:
        pass
