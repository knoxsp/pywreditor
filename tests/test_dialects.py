import pytest

from pywr_editor.dialects import detect_dialect, get_dialect
from pywr_editor.dialects.next import NextDialect
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

    def test_next_model_not_opened_yet(self):
        """
        Tests that a pywr-next model is recognised and not read as a v1 model.
        """
        model = ModelConfig(
            resolve_model_path("pywr_next/reservoir_with_evaporation1.json")
        )
        assert model.dialect.key == "next"
        assert model.is_valid() is False
        assert "pywr-next model" in model.load_error
