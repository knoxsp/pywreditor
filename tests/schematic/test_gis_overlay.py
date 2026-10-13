import json
import os
from pathlib import Path
from typing import Tuple

import pyproj
import pytest
from PySide6.QtCore import QPointF, QTimer
from PySide6.QtGui import QColor

from pywr_editor import MainWindow
from pywr_editor.schematic import Schematic
from pywr_editor.schematic.map import (
    GisLayerGroup,
    GisPathItem,
    GisPointItem,
    TileItem,
    is_map_item,
)
from pywr_editor.schematic.map.gis_overlay import BASE_Z_VALUE, Z_VALUE_STEP
from pywr_editor.schematic.map.tile_layer import BASE_Z_VALUE as TILE_Z_VALUE
from tests.fake_network import png_bytes
from tests.utils import close_message_box, resolve_model_path


def write_layer(path: Path, geometry: dict) -> Path:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {}, "geometry": geometry}
                ],
            }
        )
    )
    return path


POINT = {"type": "Point", "coordinates": [-1.5, 52.1]}
LINE = {"type": "LineString", "coordinates": [[-1.5, 52.1], [-0.448083, 51.6217]]}
POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [[-1.6, 52.2], [-0.4, 52.2], [-0.4, 51.5], [-1.6, 51.5], [-1.6, 52.2]],
        [[-1.2, 52.0], [-0.8, 52.0], [-0.8, 51.8], [-1.2, 52.0]],
    ],
}


class TestGisOverlay:
    model_file = resolve_model_path("model_geographic_positions.json")

    @pytest.fixture
    def init_window(self, qtbot) -> Tuple[MainWindow, Schematic]:
        QTimer.singleShot(100, close_message_box)
        window = MainWindow(self.model_file)
        # loading the model changes it: do not ask to save when the window is closed
        window.prompt_unsaved_changes = False
        window.resize(1000, 800)
        window.show()
        qtbot.addWidget(window)
        schematic = window.schematic
        schematic.editor_settings.save_geo_view(False)
        # the layers added by a test are not kept in the model
        layers = schematic.model_config.map_config["layers"]
        original = list(layers)
        yield window, schematic
        layers[:] = original
        schematic.editor_settings.save_geo_view(False)

    @staticmethod
    def add_layer(schematic: Schematic, path: Path, **properties) -> str:
        layer = schematic.model_config.gis_layers.add(str(path))
        layer.update(properties)
        return layer["id"]

    @staticmethod
    def groups(schematic: Schematic) -> list[GisLayerGroup]:
        return [i for i in schematic.scene.items() if isinstance(i, GisLayerGroup)]

    def test_layers_are_only_drawn_in_the_geographic_view(self, init_window, tmp_path):
        window, schematic = init_window
        self.add_layer(schematic, write_layer(tmp_path / "a.geojson", POINT))

        schematic.refresh_gis_layers()
        assert self.groups(schematic) == []

        schematic.toggle_coordinate_system()
        assert len(self.groups(schematic)) == 1

        schematic.toggle_coordinate_system()
        assert self.groups(schematic) == []

    def test_point_is_drawn_where_the_node_is(self, init_window, tmp_path):
        """
        A point at the location of Link1 is drawn at the node position.
        """
        window, schematic = init_window
        layer_id = self.add_layer(schematic, write_layer(tmp_path / "p.geojson", POINT))
        schematic.toggle_coordinate_system()

        group = schematic.gis_overlay.groups[layer_id]
        (item,) = group.childItems()
        assert isinstance(item, GisPointItem)
        assert item.scenePos().toTuple() == pytest.approx(
            schematic.node_items["Link1"].pos().toTuple(), abs=1e-3
        )

    def test_line_and_polygon_geometry_and_style(self, init_window, tmp_path):
        window, schematic = init_window
        line_id = self.add_layer(
            schematic,
            write_layer(tmp_path / "l.geojson", LINE),
            stroke_color=[10, 20, 30],
            stroke_width=3.5,
        )
        polygon_id = self.add_layer(
            schematic,
            write_layer(tmp_path / "poly.geojson", POLYGON),
            stroke_color=[200, 0, 0],
            fill_color=[0, 200, 0, 90],
            stroke_width=2,
        )
        schematic.toggle_coordinate_system()

        (line,) = schematic.gis_overlay.groups[line_id].childItems()
        assert isinstance(line, GisPathItem)
        assert line.pen().color() == QColor(10, 20, 30)
        assert line.pen().widthF() == 3.5
        # constant width on screen at any zoom
        assert line.pen().isCosmetic()
        assert line.brush().style().name == "NoBrush"
        # the path goes through the two nodes
        points = [line.path().elementAt(i) for i in range(line.path().elementCount())]
        for node in ("Link1", "Reservoir"):
            node_pos = schematic.node_items[node].pos()
            assert any(
                abs(p.x - node_pos.x()) < 1e-3 and abs(p.y - node_pos.y()) < 1e-3
                for p in points
            )

        (polygon,) = schematic.gis_overlay.groups[polygon_id].childItems()
        assert polygon.pen().color() == QColor(200, 0, 0)
        assert polygon.brush().color() == QColor(0, 200, 0, 90)
        # the hole is not filled
        assert polygon.path().fillRule().name == "OddEvenFill"
        assert len(polygon.path().toSubpathPolygons()) == 2
        hole = schematic.to_geo_px([-1.0, 51.95])
        assert polygon.path().contains(QPointF(*hole)) is False
        outside_hole = schematic.to_geo_px([-1.5, 51.7])
        assert polygon.path().contains(QPointF(*outside_hole)) is True

    def test_z_values_are_between_the_tiles_and_the_nodes(self, init_window, tmp_path):
        window, schematic = init_window
        ids = [
            self.add_layer(schematic, write_layer(tmp_path / f"{n}.geojson", POINT))
            for n in "abc"
        ]
        schematic.toggle_coordinate_system()

        groups = [schematic.gis_overlay.groups[layer_id] for layer_id in ids]
        z_values = [g.zValue() for g in groups]
        # the first layer is at the bottom
        assert z_values == sorted(z_values)
        assert z_values[0] == pytest.approx(BASE_Z_VALUE)
        assert z_values[1] - z_values[0] == pytest.approx(Z_VALUE_STEP)
        tile_z = TILE_Z_VALUE + 19 / 100
        assert tile_z < z_values[0]
        assert z_values[-1] < min(n.zValue() for n in schematic.node_items.values())

    def test_stacking_order_follows_the_list(self, init_window, tmp_path):
        window, schematic = init_window
        first = self.add_layer(schematic, write_layer(tmp_path / "1.geojson", POINT))
        second = self.add_layer(schematic, write_layer(tmp_path / "2.geojson", POINT))
        schematic.toggle_coordinate_system()
        groups = schematic.gis_overlay.groups
        assert groups[first].zValue() < groups[second].zValue()

        schematic.model_config.gis_layers.move(first, 1)
        schematic.refresh_gis_layers()
        groups = schematic.gis_overlay.groups
        assert groups[first].zValue() > groups[second].zValue()

    def test_hidden_layer_is_not_drawn(self, init_window, tmp_path):
        window, schematic = init_window
        shown = self.add_layer(schematic, write_layer(tmp_path / "1.geojson", POINT))
        hidden = self.add_layer(
            schematic, write_layer(tmp_path / "2.geojson", POINT), visible=False
        )
        schematic.toggle_coordinate_system()
        assert list(schematic.gis_overlay.groups) == [shown]

        schematic.model_config.gis_layers.set_visible(hidden, True)
        schematic.refresh_gis_layers()
        assert set(schematic.gis_overlay.groups) == {shown, hidden}

    def test_deleted_layer_is_removed(self, init_window, tmp_path):
        window, schematic = init_window
        layer_id = self.add_layer(schematic, write_layer(tmp_path / "1.geojson", POINT))
        schematic.toggle_coordinate_system()
        assert len(self.groups(schematic)) == 1

        schematic.model_config.gis_layers.delete(layer_id)
        schematic.refresh_gis_layers()
        assert self.groups(schematic) == []
        assert layer_id not in schematic.gis_overlay._cache

    def test_layers_survive_a_reload(self, init_window, tmp_path):
        window, schematic = init_window
        self.add_layer(schematic, write_layer(tmp_path / "1.geojson", LINE))
        schematic.toggle_coordinate_system()
        schematic.reload()
        schematic.reload()

        assert len(self.groups(schematic)) == 1
        group = self.groups(schematic)[0]
        assert group.scene() is schematic.scene

    def test_missing_file_is_reported_and_does_not_break_the_schematic(
        self, init_window, tmp_path
    ):
        window, schematic = init_window
        layer_id = self.add_layer(schematic, tmp_path / "missing.geojson")
        good = self.add_layer(schematic, write_layer(tmp_path / "1.geojson", POINT))
        schematic.toggle_coordinate_system()

        assert list(schematic.gis_overlay.groups) == [good]
        layer = schematic.model_config.gis_layers.find(layer_id)
        info = schematic.gis_overlay.inspect(layer)
        assert info.data is None
        assert "does not exist" in info.error

    def test_layer_data_is_cached_until_the_file_or_crs_changes(
        self, init_window, tmp_path
    ):
        window, schematic = init_window
        path = write_layer(tmp_path / "1.geojson", POINT)
        layer_id = self.add_layer(schematic, path)
        overlay = schematic.gis_overlay
        layers = schematic.model_config.gis_layers

        first = overlay.inspect(layers.find(layer_id))
        assert overlay.inspect(layers.find(layer_id)) is first

        # a change to the style does not need the file to be read again
        layers.set_property(layer_id, "stroke_width", 5)
        assert overlay.inspect(layers.find(layer_id)) is first

        # the CRS does
        layers.set_property(layer_id, "crs", "EPSG:3857")
        second = overlay.inspect(layers.find(layer_id))
        assert second is not first
        assert second.data.crs == "EPSG:3857"

        # and so does the file
        write_layer(path, LINE)
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        third = overlay.inspect(layers.find(layer_id))
        assert third is not second
        assert third.data.geometries[0].kind == "line"

    def test_cache_follows_the_shapefile_sidecar_files(self, init_window, tmp_path):
        """
        Changing the .prj file of a Shapefile reloads the layer.
        """
        import os

        import shapefile

        window, schematic = init_window
        base = tmp_path / "points"
        with shapefile.Writer(str(base), shapeType=shapefile.POINT) as writer:
            writer.field("name", "C")
            writer.point(-1, 52)
            writer.record("a")
        prj = base.with_suffix(".prj")
        prj.write_text(pyproj.CRS.from_epsg(4326).to_wkt())
        layer_id = self.add_layer(schematic, base.with_suffix(".shp"))

        overlay = schematic.gis_overlay
        layers = window.model_config.gis_layers
        first = overlay.inspect(layers.find(layer_id))
        assert overlay.inspect(layers.find(layer_id)) is first

        prj.write_text(pyproj.CRS.from_epsg(4326).to_wkt() + " ")
        stat = os.stat(prj)
        os.utime(prj, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))
        assert overlay.inspect(layers.find(layer_id)) is not first

    def test_map_items_are_not_schematic_items(self, init_window, tmp_path, qtbot):
        window, schematic = init_window
        self.add_layer(schematic, write_layer(tmp_path / "1.geojson", POLYGON))
        schematic.toggle_coordinate_system()

        map_items = [i for i in schematic.scene.items() if is_map_item(i)]
        assert any(isinstance(i, GisPathItem) for i in map_items)
        assert not any(is_map_item(n) for n in schematic.node_items.values())

        # they cannot be selected or moved
        schematic.select_all_items()
        assert not any(i.isSelected() for i in map_items)
        assert not any(isinstance(i, TileItem) and i.isSelected() for i in map_items)

    def test_layers_do_not_change_the_fitted_view(self, init_window, tmp_path):
        """
        The view fits the nodes, even when a layer is much larger.
        """
        window, schematic = init_window
        schematic.toggle_coordinate_system()
        before = schematic.transform().m11()
        world = {
            "type": "Polygon",
            "coordinates": [[[-170, -60], [170, -60], [170, 60], [-170, 60]]],
        }
        self.add_layer(schematic, write_layer(tmp_path / "world.geojson", world))
        schematic.reload()
        schematic.fit_view()
        assert schematic.transform().m11() == pytest.approx(before, rel=0.05)

    def test_tiles_and_layers_together(self, init_window, tmp_path, qtbot):
        window, schematic = init_window
        layer_id = self.add_layer(schematic, write_layer(tmp_path / "1.geojson", LINE))
        schematic.toggle_coordinate_system()
        tiles = schematic.tile_layer
        tiles.fetcher.network.replies[0].complete(png_bytes())
        qtbot.waitUntil(lambda: len(tiles.items) > 0)

        tile = next(iter(tiles.items.values()))
        group = schematic.gis_overlay.groups[layer_id]
        assert tile.zValue() < group.zValue()
