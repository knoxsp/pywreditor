import math
import os
import time
from typing import Tuple

import pyproj
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QNetworkRequest

from pywr_editor import MainWindow, __version__
from pywr_editor.schematic import Schematic
from pywr_editor.schematic.map import TileCache, TileFetcher, TileItem
from pywr_editor.schematic.map.tile_layer import (
    BASE_Z_VALUE,
    INITIAL_RESOLUTION,
    MAX_TILES,
    ORIGIN_SHIFT,
    tile_bounds,
    tile_size_metres,
    tiles_in_bounds,
    zoom_for_resolution,
)
from pywr_editor.schematic.map.tile_source import MAX_ZOOM, USER_AGENT, tile_url
from tests.fake_network import FakeNetwork, png_bytes
from tests.utils import close_message_box, resolve_model_path

TO_MERC = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


def slippy_tile(lon: float, lat: float, zoom: int) -> tuple[int, int, int]:
    """
    Reference implementation of the OSM slippy map tile numbering, which does not use
    Web Mercator metres.
    https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames
    """
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return zoom, x, y


class TestTileMath:
    @pytest.mark.parametrize("zoom", [0, 1, 5, 10, 19])
    def test_zoom_for_resolution_round_trip(self, zoom):
        assert zoom_for_resolution(INITIAL_RESOLUTION / 2**zoom) == zoom

    def test_zoom_is_the_closest_level(self):
        # between level 4 (x1) and 5 (x0.5)
        assert zoom_for_resolution(INITIAL_RESOLUTION / 2**4.4) == 4
        assert zoom_for_resolution(INITIAL_RESOLUTION / 2**4.6) == 5

    def test_zoom_is_clamped(self):
        assert zoom_for_resolution(1e9) == 0
        assert zoom_for_resolution(1e-6) == MAX_ZOOM
        for invalid in [0, -1, math.inf, math.nan]:
            assert zoom_for_resolution(invalid) == MAX_ZOOM

    def test_tile_bounds(self):
        assert tile_size_metres(0) == pytest.approx(2 * ORIGIN_SHIFT)
        left, top, right, bottom = tile_bounds(0, 0, 0)
        assert (left, top, right, bottom) == pytest.approx(
            (-ORIGIN_SHIFT, ORIGIN_SHIFT, ORIGIN_SHIFT, -ORIGIN_SHIFT)
        )
        # south east quadrant
        left, top, right, bottom = tile_bounds(1, 1, 1)
        assert (left, top, right, bottom) == pytest.approx(
            (0, 0, ORIGIN_SHIFT, -ORIGIN_SHIFT)
        )

    def test_tile_url(self):
        assert tile_url(3, 4, 5) == "https://tile.openstreetmap.org/3/4/5.png"

    @pytest.mark.parametrize(
        "lonlat",
        [
            (-0.1276, 51.5072),  # London
            (151.2093, -33.8688),  # Sydney
            (-179.99, 0.01),
            (179.99, -0.01),
            (0.0001, 0.0001),
        ],
    )
    @pytest.mark.parametrize("zoom", [0, 3, 10, 17])
    def test_point_tile_matches_reference(self, lonlat, zoom):
        x, y = TO_MERC.transform(*lonlat)
        assert tiles_in_bounds(zoom, x, y, x, y) == [slippy_tile(*lonlat, zoom)]

    def test_known_tile(self):
        # London at zoom 10 is the tile 511/340 (OSM)
        x, y = TO_MERC.transform(-0.1276, 51.5072)
        assert tiles_in_bounds(10, x, y, x, y) == [(10, 511, 340)]

    def test_tile_contains_its_point(self):
        x, y = TO_MERC.transform(-1.5, 52.1)
        (z, tx, ty), *_ = tiles_in_bounds(12, x, y, x, y)
        left, top, right, bottom = tile_bounds(z, tx, ty)
        assert left <= x <= right
        assert bottom <= y <= top

    def test_world_extent(self):
        tiles = tiles_in_bounds(
            2, -ORIGIN_SHIFT, -ORIGIN_SHIFT, ORIGIN_SHIFT, ORIGIN_SHIFT
        )
        assert len(tiles) == 16
        assert len(set(tiles)) == 16

    def test_extent_is_clipped_to_the_world(self):
        """
        An extent beyond the antimeridian or the poles does not give invalid tiles.
        """
        tiles = tiles_in_bounds(3, -3e7, -3e7, 3e7, 3e7)
        assert len(tiles) == 64
        assert all(0 <= x < 8 and 0 <= y < 8 for _, x, y in tiles)

    def test_extent_across_a_tile_edge(self):
        left, top, right, bottom = tile_bounds(5, 10, 12)
        # a thin extent straddling the edge shared by two columns
        tiles = tiles_in_bounds(5, right - 1, bottom + 1, right + 1, bottom + 2)
        assert tiles == [(5, 10, 12), (5, 11, 12)]

    def test_antimeridian_neighbours(self):
        wx, wy = TO_MERC.transform(-179.9, 10)
        ex, ey = TO_MERC.transform(179.9, 10)
        assert tiles_in_bounds(4, wx, wy, wx, wy)[0][1] == 0
        assert tiles_in_bounds(4, ex, ey, ex, ey)[0][1] == 15


class TestTileCache:
    def test_round_trip_and_layout(self, tmp_path):
        cache = TileCache(tmp_path)
        assert cache.read(3, 4, 5) is None
        cache.write(3, 4, 5, b"data")
        assert cache.read(3, 4, 5) == b"data"
        assert cache.path(3, 4, 5) == tmp_path / "3" / "4" / "5.png"
        # no temporary file is left behind
        assert [p.name for p in (tmp_path / "3" / "4").iterdir()] == ["5.png"]

    def test_stale_tile(self, tmp_path):
        cache = TileCache(tmp_path)
        cache.write(1, 0, 0, b"old")
        old = time.time() - cache.max_age - 10
        os.utime(cache.path(1, 0, 0), (old, old))

        assert cache.read(1, 0, 0) is None
        assert cache.read(1, 0, 0, allow_stale=True) == b"old"

    def test_remove(self, tmp_path):
        cache = TileCache(tmp_path)
        cache.write(1, 0, 0, b"x")
        cache.remove(1, 0, 0)
        cache.remove(1, 0, 0)  # missing tile
        assert cache.read(1, 0, 0) is None

    def test_unwritable_cache_is_ignored(self, tmp_path):
        blocker = tmp_path / "file"
        blocker.write_text("")
        cache = TileCache(blocker / "sub")  # a folder cannot be created
        cache.write(1, 0, 0, b"x")
        assert cache.read(1, 0, 0) is None

    def test_default_location_is_not_the_working_directory(self):
        # the fixture in conftest.py redirects the default away from the user's cache
        assert TileCache().root.name == "osm_tiles"


class TestTileFetcher:
    @pytest.fixture
    def fetcher(self, tmp_path, qtbot):
        network = FakeNetwork()
        fetcher = TileFetcher(cache=TileCache(tmp_path), network=network)
        return fetcher, network

    def test_download_and_cache(self, fetcher, qtbot):
        fetcher, network = fetcher
        key = (3, 4, 5)

        assert fetcher.get(key) is None
        assert network.urls == ["https://tile.openstreetmap.org/3/4/5.png"]

        request = network.replies[0].request
        assert request.header(QNetworkRequest.KnownHeaders.UserAgentHeader) == (
            USER_AGENT
        )
        assert "pywr-editor" in USER_AGENT and __version__ in USER_AGENT

        with qtbot.waitSignal(fetcher.tile_ready) as signal:
            network.replies[0].complete(png_bytes())
        assert signal.args[:3] == [3, 4, 5]
        assert signal.args[3].width() == 256

        # served from memory without a new request
        assert fetcher.get(key) is not None
        assert len(network.replies) == 1
        # and from the disk cache by a new fetcher
        other = TileFetcher(cache=fetcher.cache, network=FakeNetwork())
        assert other.get(key) is not None
        assert other.network.replies == []

    def test_request_is_not_repeated_while_pending(self, fetcher):
        fetcher, network = fetcher
        fetcher.get((1, 0, 0))
        fetcher.get((1, 0, 0))
        assert len(network.replies) == 1

    def test_concurrent_connections_are_limited(self, fetcher, qtbot):
        fetcher, network = fetcher
        keys = [(4, x, 0) for x in range(5)]
        for key in keys:
            fetcher.get(key)
        assert len(network.replies) == TileFetcher.max_concurrent == 2

        with qtbot.waitSignal(fetcher.tile_ready):
            network.replies[0].complete(png_bytes())
        assert len(network.replies) == 3
        assert network.urls[2].endswith("/4/2/0.png")

    def test_retain_drops_queued_and_aborts_pending(self, fetcher):
        fetcher, network = fetcher
        for x in range(4):
            fetcher.get((4, x, 0))
        assert len(network.replies) == 2

        fetcher.retain([(4, 0, 0), (4, 3, 0)])
        # the pending tile that is not needed is aborted, the queued one dropped
        assert network.replies[0].aborted is False
        assert network.replies[1].aborted is True
        assert fetcher.queue == [] or fetcher.queue == [(4, 3, 0)]
        assert (4, 2, 0) not in fetcher.queue

    def test_failed_download_is_not_retried_straight_away(self, fetcher, qtbot):
        fetcher, network = fetcher
        key = (2, 1, 1)
        fetcher.get(key)
        network.replies[0].complete(error=True)

        assert fetcher.get(key) is None
        assert len(network.replies) == 1  # backoff

        fetcher.retry_delay = 0
        fetcher.get(key)
        assert len(network.replies) == 2

    def test_invalid_image_is_a_failure(self, fetcher):
        fetcher, network = fetcher
        key = (2, 1, 1)
        fetcher.get(key)
        network.replies[0].complete(b"<html>rate limited</html>")
        assert fetcher.cache.read(*key) is None  # not cached
        assert key in fetcher.failed

    def test_stale_tile_is_used_when_the_download_fails(self, fetcher, qtbot):
        fetcher, network = fetcher
        key = (2, 1, 1)
        fetcher.cache.write(*key, png_bytes("#ff0000"))
        old = time.time() - fetcher.cache.max_age - 10
        os.utime(fetcher.cache.path(*key), (old, old))

        assert fetcher.get(key) is None  # stale: downloaded again
        with qtbot.waitSignal(fetcher.tile_ready):
            network.replies[0].complete(error=True)
        assert fetcher.get(key) is not None

    def test_corrupted_cache_file_is_replaced(self, fetcher):
        fetcher, network = fetcher
        key = (2, 1, 1)
        fetcher.cache.write(*key, b"not a png")
        assert fetcher.get(key) is None
        assert fetcher.cache.read(*key) is None
        assert len(network.replies) == 1

    def test_memory_is_bounded(self, fetcher):
        fetcher, network = fetcher
        fetcher.memory_size = 3
        for x in range(6):
            fetcher.cache.write(5, x, 0, png_bytes(size=8))
            fetcher.get((5, x, 0))
        assert len(fetcher.memory) == 3
        assert list(fetcher.memory) == [(5, 3, 0), (5, 4, 0), (5, 5, 0)]


class TestTileLayer:
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
        yield window, schematic
        schematic.editor_settings.save_geo_view(False)

    @staticmethod
    def tile_items(schematic: Schematic) -> list[TileItem]:
        return [i for i in schematic.scene.items() if isinstance(i, TileItem)]

    def test_nothing_is_requested_in_the_schematic_view(self, init_window, qtbot):
        window, schematic = init_window
        schematic.tile_layer.refresh()
        assert schematic.tile_layer.fetcher.network.replies == []
        assert self.tile_items(schematic) == []
        assert schematic.attribution.isHidden() is True

    def test_geo_view_requests_tiles_for_the_visible_area(self, init_window):
        window, schematic = init_window
        schematic.toggle_coordinate_system()
        layer = schematic.tile_layer
        network = layer.fetcher.network

        assert layer.zoom is not None
        assert 0 < len(network.replies) <= TileFetcher.max_concurrent
        assert len(layer.wanted) <= MAX_TILES
        # the nodes are inside the tiles that are requested
        transform = schematic.geo_transform
        zoom = zoom_for_resolution(
            transform.metres_per_pixel(schematic.transform().m11())
        )
        assert layer.zoom == zoom
        for lonlat in ([-0.448083, 51.6217], [-1.5, 52.1]):
            assert slippy_tile(*lonlat, zoom) in layer.wanted
        for url in network.urls:
            assert url.startswith("https://tile.openstreetmap.org/")

    def test_attribution_is_visible_with_the_tiles(self, init_window):
        window, schematic = init_window
        assert schematic.attribution.isHidden() is True

        schematic.toggle_coordinate_system()
        assert schematic.attribution.isHidden() is False
        assert "OpenStreetMap contributors" in schematic.attribution.text()
        assert "openstreetmap.org/copyright" in schematic.attribution.text()
        assert schematic.attribution.openExternalLinks() is True

        schematic.set_basemap_visible(False)
        assert schematic.attribution.isHidden() is True
        schematic.set_basemap_visible(True)
        assert schematic.attribution.isHidden() is False

        schematic.toggle_coordinate_system()
        assert schematic.attribution.isHidden() is True

    def test_downloaded_tile_is_placed_behind_the_nodes(self, init_window, qtbot):
        window, schematic = init_window
        schematic.toggle_coordinate_system()
        layer = schematic.tile_layer
        reply = layer.fetcher.network.replies[0]
        key = layer.fetcher.replies[reply]

        reply.complete(png_bytes())
        qtbot.waitUntil(lambda: key in layer.items)

        item = layer.items[key]
        assert item.scene() is schematic.scene
        # below the nodes and the other schematic items
        assert item.zValue() < -50
        assert item.zValue() >= BASE_Z_VALUE
        assert all(n.zValue() >= 0 for n in schematic.node_items.values())
        assert not item.flags() & item.GraphicsItemFlag.ItemIsSelectable
        assert not item.flags() & item.GraphicsItemFlag.ItemIsMovable

        # the tile covers exactly its extent
        transform = schematic.geo_transform
        left, top, right, bottom = tile_bounds(*key)
        rect = item.sceneBoundingRect()
        expected_left, expected_top = transform.merc_to_scene(left, top)
        expected_right, expected_bottom = transform.merc_to_scene(right, bottom)
        assert rect.left() == pytest.approx(expected_left, abs=1e-6)
        assert rect.top() == pytest.approx(expected_top, abs=1e-6)
        assert rect.right() == pytest.approx(expected_right, abs=1e-6)
        assert rect.bottom() == pytest.approx(expected_bottom, abs=1e-6)

    def test_tile_is_geographically_aligned_with_the_nodes(self, init_window, qtbot):
        """
        The node of a known location is drawn inside the tile that covers this
        location.
        """
        window, schematic = init_window
        schematic.toggle_coordinate_system()
        layer = schematic.tile_layer

        key = slippy_tile(-1.5, 52.1, layer.zoom)
        # load the tile of Link1
        while key not in layer.items:
            pending = [
                (r, k) for r, k in layer.fetcher.replies.items() if not r.aborted
            ]
            assert pending, "the tile was not requested"
            reply, pending_key = pending[0]
            reply.complete(png_bytes())
            qtbot.wait(10)

        link1 = schematic.node_items["Link1"].pos()
        assert layer.items[key].sceneBoundingRect().contains(link1)

    def test_tiles_are_not_schematic_items(self, init_window, qtbot):
        window, schematic = init_window
        schematic.toggle_coordinate_system()
        layer = schematic.tile_layer
        reply = layer.fetcher.network.replies[0]
        reply.complete(png_bytes())
        qtbot.waitUntil(lambda: len(self.tile_items(schematic)) > 0)

        schematic.select_all_items()
        assert not any(i.isSelected() for i in self.tile_items(schematic))

        # tiles are ignored by the bounding box of the schematic items
        assert (
            schematic.sceneRect().contains(schematic.node_items["Link1"].pos()) is True
        )

    def test_reload_and_toggle_remove_the_tiles(self, init_window, qtbot):
        window, schematic = init_window
        schematic.toggle_coordinate_system()
        layer = schematic.tile_layer
        layer.fetcher.network.replies[0].complete(png_bytes())
        qtbot.waitUntil(lambda: len(self.tile_items(schematic)) > 0)

        # the scene deletes its items on reload: this must not leave stale tiles
        schematic.reload()
        assert all(k in layer.wanted for k in layer.items)
        for item in layer.items.values():
            assert item.scene() is schematic.scene

        schematic.toggle_coordinate_system()
        assert layer.items == {}
        assert self.tile_items(schematic) == []
        assert layer.fetcher.queue == []
        assert all(r.aborted for r in layer.fetcher.network.replies if r.aborted)

    def test_basemap_visibility_is_saved_in_the_model(self, init_window):
        window, schematic = init_window
        schematic.toggle_coordinate_system()
        schematic.set_basemap_visible(False)

        assert schematic.model_config.map_config["show_basemap"] is False
        assert schematic.tile_layer.items == {}
        assert schematic.tile_layer.wanted == set()
        schematic.set_basemap_visible(True)
        assert schematic.model_config.map_config["show_basemap"] is True
        assert len(schematic.tile_layer.wanted) > 0

    def test_zoom_requests_new_tiles_and_keeps_the_old_ones_until_loaded(
        self, init_window, qtbot
    ):
        window, schematic = init_window
        schematic.toggle_coordinate_system()
        layer = schematic.tile_layer
        zoom = layer.zoom

        # load every tile of the current zoom level
        for _ in range(MAX_TILES):
            pending = [r for r in layer.fetcher.replies if not r.aborted]
            if not pending:
                break
            pending[0].complete(png_bytes())
            qtbot.wait(5)
        assert layer.wanted.issubset(layer.items)

        # zoom in by 2 levels
        schematic.scale_view(4)
        qtbot.waitUntil(lambda: layer.zoom == zoom + 2, timeout=2000)
        assert all(k[0] == zoom + 2 for k in layer.wanted)
        # the previous level stays displayed while the new one is loading
        assert any(k[0] == zoom for k in layer.items)
        assert not layer.wanted.issubset(layer.items)

        # once the new tiles are loaded, the old ones are dropped
        for _ in range(MAX_TILES * 2):
            pending = [r for r in layer.fetcher.replies if not r.aborted]
            if layer.wanted.issubset(layer.items) or not pending:
                break
            pending[0].complete(png_bytes())
            qtbot.wait(5)
        assert layer.wanted.issubset(layer.items)
        assert all(k[0] == zoom + 2 for k in layer.items)

    def test_panning_requests_the_tiles_of_the_new_area(self, init_window, qtbot):
        window, schematic = init_window
        schematic.toggle_coordinate_system()
        layer = schematic.tile_layer
        before = set(layer.wanted)

        schematic.centerOn(schematic.mapToScene(schematic.viewport().rect().center()))
        # a big pan
        schematic.centerOn(
            schematic.sceneRect().center().x() + 6000,
            schematic.sceneRect().center().y(),
        )
        schematic.viewport().repaint()  # paints the background: requests the refresh
        qtbot.waitUntil(lambda: layer.wanted != before, timeout=2000)
        assert layer.wanted.isdisjoint(before) or layer.wanted != before

    def test_huge_view_uses_a_coarser_zoom(self, init_window):
        window, schematic = init_window
        schematic.toggle_coordinate_system()
        layer = schematic.tile_layer
        # force a tiny scale (the view shows a very large area)
        schematic.setTransform(schematic.transform().scale(1e-3, 1e-3))
        layer.refresh()
        assert len(layer.wanted) <= MAX_TILES
        assert layer.zoom is not None

    def test_initial_visibility_comes_from_the_model(self, qtbot):
        window = MainWindow(self.model_file)
        window.prompt_unsaved_changes = False
        qtbot.addWidget(window)
        assert window.schematic.tile_layer.basemap_visible is True

    def test_zoom_limits_cover_all_the_tile_levels_in_geo_view(self, init_window):
        window, schematic = init_window
        assert schematic.zoom_limits == (Schematic.min_zoom, Schematic.max_zoom)

        schematic.toggle_coordinate_system()
        minimum, maximum = schematic.zoom_limits
        transform = schematic.geo_transform
        assert minimum == pytest.approx(transform.scale_for_zoom(0))
        assert maximum == pytest.approx(transform.scale_for_zoom(MAX_ZOOM))

        # the tiles of the highest level are shown 1:1 at the maximum zoom, whatever
        # the extent of the nodes is
        assert zoom_for_resolution(
            transform.metres_per_pixel(maximum)
        ) == pytest.approx(MAX_ZOOM)
        assert zoom_for_resolution(transform.metres_per_pixel(minimum)) == 0

        # zoom in until the limit
        for _ in range(200):
            before = schematic.transform().m11()
            schematic.scale_view(1.5)
            if schematic.transform().m11() == before:
                break
        assert schematic.transform().m11() <= maximum * (1 + 1e-9)
        assert schematic.transform().m11() > maximum / 1.5
        assert schematic.tile_layer.zoom is not None

        # and out
        for _ in range(200):
            before = schematic.transform().m11()
            schematic.scale_view(1 / 1.5)
            if schematic.transform().m11() == before:
                break
        assert schematic.transform().m11() >= minimum * (1 - 1e-9)
        assert schematic.transform().m11() < minimum * 1.5

        # the schematic limits are restored when leaving the geographic view
        schematic.toggle_coordinate_system()
        assert schematic.zoom_limits == (Schematic.min_zoom, Schematic.max_zoom)
