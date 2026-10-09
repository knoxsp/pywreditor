import pytest
from PySide6.QtGui import QColor

from pywr_editor.model import GisLayerConfig, GisLayers, ModelConfig
from tests.utils import resolve_model_path


class TestGisLayers:
    @staticmethod
    def gis_layers() -> GisLayers:
        """
        Initialises the GisLayers class.
        :return: The GisLayers instance.
        """
        return GisLayers(ModelConfig(resolve_model_path("model_1.json")))

    @pytest.mark.parametrize(
        "layer_dict, is_valid",
        [
            # empty dict
            ({}, False),
            # invalid type
            ([], False),
            # missing path
            ({"id": "aaa"}, False),
            # empty path
            ({"id": "aaa", "path": ""}, False),
            # missing id
            ({"path": "layer.geojson"}, False),
            # valid
            ({"id": "aaa", "path": "layer.geojson"}, True),
        ],
    )
    def test_gis_layer_config_validation(self, layer_dict, is_valid):
        """
        Tests the GisLayerConfig validation.
        """
        assert GisLayerConfig(layer_dict=layer_dict).is_valid() == is_valid

    @pytest.mark.parametrize(
        "path, expected_type",
        [
            ("layer.geojson", "geojson"),
            ("layer.json", "geojson"),
            ("layer.shp", "shapefile"),
            ("layer.SHP", "shapefile"),
        ],
    )
    def test_gis_layer_file_type(self, path, expected_type):
        """
        Tests that the file_type property infers the format from the extension.
        """
        layer = GisLayerConfig(layer_dict={"id": "aaa", "path": path})
        assert layer.file_type == expected_type

    def test_gis_layer_name_fallback(self):
        """
        Tests that the layer name falls back to the file name when not provided.
        """
        layer = GisLayerConfig(layer_dict={"id": "aaa", "path": "catchment.geojson"})
        assert layer.name == "catchment"

    def test_gis_layer_colors(self):
        """
        Tests the stroke_color and fill_color properties.
        """
        layer = GisLayerConfig(
            layer_dict={
                "id": "aaa",
                "path": "layer.geojson",
                "stroke_color": [10, 20, 30],
                "fill_color": [10, 20, 30, 100],
            }
        )
        assert layer.stroke_color == QColor(10, 20, 30)
        assert layer.fill_color == QColor(10, 20, 30, 100)

    def test_add_and_get_all(self):
        """
        Tests adding a layer and retrieving it via get_all.
        """
        gis_layers = self.gis_layers()
        layer_dict = gis_layers.add("catchment.geojson", name="Catchment")

        assert layer_dict["name"] == "Catchment"
        assert layer_dict["visible"] is True

        all_layers = gis_layers.get_all()
        assert len(all_layers) == 1
        assert all_layers[0].id == layer_dict["id"]
        assert gis_layers.model.has_changes is True

    def test_find(self):
        """
        Tests the find and find_index methods.
        """
        gis_layers = self.gis_layers()
        layer_dict = gis_layers.add("catchment.geojson")

        assert gis_layers.find_index(layer_dict["id"]) == 0
        assert gis_layers.find_index("non-existing") is None
        assert gis_layers.find(layer_dict["id"], as_dict=True) == layer_dict
        assert gis_layers.find(layer_dict["id"]).id == layer_dict["id"]
        assert gis_layers.find("non-existing") is None

    def test_delete(self):
        """
        Tests the delete method.
        """
        gis_layers = self.gis_layers()
        layer_dict = gis_layers.add("catchment.geojson")

        gis_layers.delete(layer_dict["id"])
        assert gis_layers.get_all() == []

        # deleting a non-existing layer does not raise
        gis_layers.delete("non-existing")

    def test_update(self):
        """
        Tests the update method.
        """
        gis_layers = self.gis_layers()
        layer_dict = gis_layers.add("catchment.geojson")

        new_dict = {**layer_dict, "name": "New name"}
        gis_layers.update(layer_dict["id"], new_dict)

        assert gis_layers.find(layer_dict["id"], as_dict=True)["name"] == "New name"

    def test_set_visible(self):
        """
        Tests the set_visible method.
        """
        gis_layers = self.gis_layers()
        layer_dict = gis_layers.add("catchment.geojson")

        gis_layers.set_visible(layer_dict["id"], False)
        assert gis_layers.find(layer_dict["id"]).visible is False

    def test_move(self):
        """
        Tests the move method used to reorder layers.
        """
        gis_layers = self.gis_layers()
        first = gis_layers.add("first.geojson")
        second = gis_layers.add("second.geojson")
        third = gis_layers.add("third.geojson")

        gis_layers.move(third["id"], 0)
        ids = [layer.id for layer in gis_layers.get_all()]
        assert ids == [third["id"], first["id"], second["id"]]
