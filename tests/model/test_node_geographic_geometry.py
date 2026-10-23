import pytest

from pywr_editor.model import NodeConfig

SQUARE = [
    [0.0, 0.0, 0.0],
    [4.0, 0.0, 0.0],
    [4.0, 2.0, 0.0],
    [0.0, 2.0, 0.0],
    [0.0, 0.0, 0.0],
]


def config(geographic) -> NodeConfig:
    return NodeConfig(
        {"name": "n", "type": "link", "position": {"geographic": geographic}}
    )


class TestGeographicGeometry:
    def test_point_list(self):
        assert config([1.5, 2.5]).geographic_position == [1.5, 2.5]

    def test_geojson_point(self):
        node = config({"type": "Point", "coordinates": [1, 2]})
        assert node.geographic_position == [1, 2]

    def test_polygon_centroid(self):
        node = config({"type": "Polygon", "coordinates": [SQUARE]})
        assert node.geographic_position == pytest.approx([2.0, 1.0])

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "x",
            [1],
            {"type": "LineString", "coordinates": [[0, 0]]},
            {"type": "Polygon", "coordinates": []},
            {"type": "Polygon", "coordinates": [["a"]]},
        ],
    )
    def test_invalid(self, value):
        assert config(value).geographic_position is None
