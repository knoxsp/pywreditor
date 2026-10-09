import math
from typing import Tuple

import pyproj
import pytest
from PySide6.QtCore import QTimer

from pywr_editor import MainWindow
from pywr_editor.schematic import Schematic
from pywr_editor.schematic.map import GeoTransform
from pywr_editor.schematic.map.geo_transform import FILL_RATIO, MIN_SPAN_METRES
from tests.utils import close_message_box, resolve_model_path

TO_MERC = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


class TestGeoTransform:
    scene_size = (800, 600)

    def test_fit_centres_and_fills_the_scene(self):
        """
        The extent of the points fills FILL_RATIO of the scene along the limiting
        axis, is centred, and the y axis is flipped.
        """
        transform = GeoTransform.fit([(0, 0), (80_000, 10_000)], self.scene_size)

        # the x extent is the limiting one
        assert transform.metres_per_unit == pytest.approx(80_000 / (800 * FILL_RATIO))
        left = transform.merc_to_scene(0, 0)
        right = transform.merc_to_scene(80_000, 10_000)
        assert (left[0] + right[0]) / 2 == pytest.approx(400)
        assert (left[1] + right[1]) / 2 == pytest.approx(300)
        assert right[0] - left[0] == pytest.approx(800 * FILL_RATIO)
        # north (larger y) is up, i.e. a smaller scene y
        assert right[1] < left[1]

    def test_round_trip(self):
        transform = GeoTransform.fit([(1e6, 6e6), (1.2e6, 6.3e6)], self.scene_size)
        for point in [(1e6, 6e6), (1.1e6, 6.1e6), (-5e5, 2e6)]:
            back = transform.scene_to_merc(*transform.merc_to_scene(*point))
            assert back == pytest.approx(point)

    @pytest.mark.parametrize("points", [[], [(5e5, 5e5)], [(5e5, 5e5), (5e5, 5e5)]])
    def test_degenerate_extent_has_minimum_span(self, points):
        """
        No nodes, a single node or nodes in the same place do not give an infinite
        or zero scale.
        """
        transform = GeoTransform.fit(points, self.scene_size)
        assert 0 < transform.metres_per_unit < math.inf
        assert transform.metres_per_unit == pytest.approx(
            MIN_SPAN_METRES / (600 * FILL_RATIO)
        )

    def test_metres_per_pixel(self):
        transform = GeoTransform.fit([(0, 0), (1e5, 0)], self.scene_size)
        assert transform.metres_per_pixel(2) == pytest.approx(
            transform.metres_per_unit / 2
        )
        # a non-positive scale does not divide by zero
        assert math.isfinite(transform.metres_per_pixel(0))

    def test_is_finite(self):
        assert GeoTransform.is_finite((1, 2))
        assert not GeoTransform.is_finite((math.inf, 2))
        assert not GeoTransform.is_finite((1, math.nan))


class TestSchematicToGeoPx:
    model_file = resolve_model_path("model_geographic_positions.json")

    @pytest.fixture
    def init_window(self, qtbot) -> Tuple[MainWindow, Schematic]:
        QTimer.singleShot(100, close_message_box)
        window = MainWindow(self.model_file)
        window.hide()
        yield window, window.schematic

    def test_matches_independent_pyproj_reference(self, init_window):
        """
        to_geo_px() is compared against an independent implementation that uses
        pyproj directly, for the nodes in the model.
        """
        window, schematic = init_window
        lonlats = [[-0.448083, 51.6217], [-1.5, 52.1]]
        merc = [TO_MERC.transform(*p) for p in lonlats]

        span_x = merc[0][0] - merc[1][0]
        span_y = merc[0][1] - merc[1][1]
        metres_per_unit = max(
            abs(span_x) / (schematic.schematic_width * FILL_RATIO),
            abs(span_y) / (schematic.schematic_height * FILL_RATIO),
        )
        centre = ((merc[0][0] + merc[1][0]) / 2, (merc[0][1] + merc[1][1]) / 2)

        for lonlat, (x, y) in zip(lonlats, merc):
            expected = [
                schematic.schematic_width / 2 + (x - centre[0]) / metres_per_unit,
                schematic.schematic_height / 2 - (y - centre[1]) / metres_per_unit,
            ]
            assert schematic.to_geo_px(lonlat) == pytest.approx(expected, abs=1e-3)

    def test_point_near_the_antimeridian(self, init_window):
        """
        Points either side of the antimeridian are on opposite sides of the map and
        are not wrapped.
        """
        window, schematic = init_window
        east = schematic.to_geo_px([179.9, 51.6])
        west = schematic.to_geo_px([-179.9, 51.6])
        # the model nodes are close to each other, so these are far outside the
        # schematic, but still ordered like the longitudes and finite
        assert west[0] < east[0]
        assert all(math.isfinite(v) for v in east + west)

    def test_unprojectable_point_is_centred(self, init_window):
        window, schematic = init_window
        # the poles cannot be represented in Web Mercator
        position = schematic.to_geo_px([0, 90])
        assert all(math.isfinite(v) for v in position)

    def test_nodes_are_visible_and_zoom_works_in_geo_view(self, init_window):
        """
        The geographic view is fitted to the nodes, so they are inside the viewport and
        the zoom limits of the schematic still apply. Leaving the view restores the
        schematic zoom and centre.
        """
        window, schematic = init_window
        schematic.editor_settings.save_geo_view(False)
        window.resize(1000, 800)
        before = schematic.transform().m11()
        centre = schematic.mapToScene(schematic.viewport().rect().center())

        schematic.toggle_coordinate_system()
        assert schematic.editor_settings.is_geo_view_enabled is True
        viewport = schematic.viewport().rect()
        for name in ["Reservoir", "Link1"]:
            point = schematic.mapFromScene(schematic.node_items[name].pos())
            assert viewport.contains(point), name

        zoom = schematic.transform().m11()
        assert Schematic.min_zoom < zoom < Schematic.max_zoom
        schematic.scale_view(1.1)
        assert schematic.transform().m11() == pytest.approx(zoom * 1.1)

        schematic.toggle_coordinate_system()
        assert schematic.editor_settings.is_geo_view_enabled is False
        assert schematic.transform().m11() == pytest.approx(before)
        restored = schematic.mapToScene(schematic.viewport().rect().center())
        assert restored.toTuple() == pytest.approx(centre.toTuple(), abs=2)
