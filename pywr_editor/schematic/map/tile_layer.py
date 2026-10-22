import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem

from .geo_transform import INITIAL_RESOLUTION, ORIGIN_SHIFT
from .tile_fetcher import TileFetcher, TileKey
from .tile_source import MAX_ZOOM

if TYPE_CHECKING:
    from pywr_editor.schematic import Schematic

BASE_Z_VALUE = -100.0
""" The z-value of the tiles. Nodes, edges and shapes have a z-value of 0 or more,
the GIS overlay layers are between -50 and 0. The z-value is raised slightly with
the zoom level so that, while a zoom level loads, the detailed tiles are on top of
the coarser ones that are still displayed """
MAX_TILES = 150
""" The maximum number of tiles displayed for a zoom level """
VIEW_MARGIN = 0.15
""" The share of the viewport size, added on each side, in which the tiles are
loaded in advance """


def zoom_for_resolution(metres_per_pixel: float) -> int:
    """
    Returns the tile zoom level that gives the closest match between the tile pixels
    and the screen pixels.
    :param metres_per_pixel: The ground resolution of the screen in metres.
    :return: The zoom level, between 0 and MAX_ZOOM.
    """
    if not math.isfinite(metres_per_pixel) or metres_per_pixel <= 0:
        return MAX_ZOOM
    zoom = round(math.log2(INITIAL_RESOLUTION / metres_per_pixel))
    return max(0, min(MAX_ZOOM, zoom))


def tile_size_metres(zoom: int) -> float:
    """
    Returns the width and height of a tile.
    :param zoom: The zoom level.
    :return: The size in Web Mercator metres.
    """
    return 2 * ORIGIN_SHIFT / 2**zoom


def tile_bounds(zoom: int, x: int, y: int) -> tuple[float, float, float, float]:
    """
    Returns the extent of a tile in Web Mercator metres.
    :param zoom: The zoom level.
    :param x: The tile column.
    :param y: The tile row (0 is the northern edge).
    :return: The (left, top, right, bottom) coordinates, with top > bottom.
    """
    size = tile_size_metres(zoom)
    left = -ORIGIN_SHIFT + x * size
    top = ORIGIN_SHIFT - y * size
    return left, top, left + size, top - size


def tiles_in_bounds(
    zoom: int, left: float, bottom: float, right: float, top: float
) -> list[TileKey]:
    """
    Returns the tiles that intersect a Web Mercator extent. The extent is clipped
    to the world.
    :param zoom: The zoom level.
    :param left: The minimum x coordinate.
    :param bottom: The minimum y coordinate.
    :param right: The maximum x coordinate.
    :param top: The maximum y coordinate.
    :return: The (z, x, y) tiles, ordered by column and row.
    """
    size = tile_size_metres(zoom)
    last = 2**zoom - 1

    def index(value: float, upper: int) -> int:
        return max(0, min(upper, int(math.floor(value))))

    x_min = index((left + ORIGIN_SHIFT) / size, last)
    x_max = index((right + ORIGIN_SHIFT) / size, last)
    # the rows are counted from the north
    y_min = index((ORIGIN_SHIFT - top) / size, last)
    y_max = index((ORIGIN_SHIFT - bottom) / size, last)
    return [
        (zoom, x, y) for x in range(x_min, x_max + 1) for y in range(y_min, y_max + 1)
    ]


class TileItem(QGraphicsPixmapItem):
    """
    A map tile on the schematic. The tile ignores the mouse, so that clicks and drags
    go to the items above it or pan the schematic.
    """

    def __init__(self, key: TileKey, pixmap: QPixmap):
        """
        Initialises the tile.
        :param key: The (z, x, y) tile.
        :param pixmap: The tile image.
        """
        super().__init__(pixmap)
        self.key = key
        self.setZValue(BASE_Z_VALUE + key[0] / 100)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)


class TileLayer(QObject):
    """
    Draws the OSM basemap behind the schematic items. The tiles are scene items,
    placed with the transform fitted to the nodes (Schematic.geo_transform), and
    are loaded for the part of the map in the viewport at the zoom level matching the
    view scale. The layer is only active in the geographic view when the basemap is
    visible.
    """

    active_changed = Signal(bool)
    """ Signal emitted when the layer is shown or hidden """
    refresh_delay: int = 40
    """ Milliseconds to wait, after the view changed, before loading the tiles. This
    groups the many changes of a pan or zoom gesture """

    def __init__(self, schematic: "Schematic", fetcher: TileFetcher | None = None):
        """
        Initialises the layer.
        :param schematic: The schematic.
        :param fetcher: The tile fetcher. Optional.
        """
        super().__init__(schematic)
        self.schematic = schematic
        self.fetcher = fetcher if fetcher is not None else TileFetcher(parent=self)
        self.fetcher.tile_ready.connect(self.on_tile_ready)
        self.items: dict[TileKey, TileItem] = {}
        self.wanted: set[TileKey] = set()
        self.zoom: int | None = None
        self.basemap_visible = True
        self._active = False
        self._signature: tuple | None = None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.refresh_delay)
        self._timer.timeout.connect(self.refresh)

    @property
    def is_active(self) -> bool:
        """
        Whether the tiles must be displayed.
        :return: True in the geographic view when the basemap is visible.
        """
        return (
            self.basemap_visible and self.schematic.editor_settings.is_geo_view_enabled
        )

    def set_basemap_visible(self, visible: bool) -> None:
        """
        Shows or hides the basemap.
        :param visible: Whether to show the tiles.
        :return: None
        """
        self.basemap_visible = visible
        self.refresh()

    def request_refresh(self) -> None:
        """
        Loads the tiles for the visible area shortly, unless the view did not change
        since the last time. This is cheap, so it can be called while painting. The
        tiles are not added straight away, as the scene must not change while it is
        painted.
        :return: None
        """
        if not self.is_active:
            return
        if self._view_signature() != self._signature:
            self._timer.start()

    def refresh(self) -> None:
        """
        Adds the tiles that intersect the viewport and removes the ones that do not
        or that are no longer needed.
        :return: None
        """
        self._timer.stop()
        self._set_active(self.is_active)
        if not self.is_active:
            self.clear()
            self._signature = None
            return

        self._signature = self._view_signature()
        transform = self.schematic.geo_transform
        view_scale = self.schematic.transform().m11()
        zoom = zoom_for_resolution(transform.metres_per_pixel(view_scale))

        # use a coarser level, rather than thousands of tiles, if the view is huge
        view_rect = self.visible_rect()
        keys = self.tiles_for(view_rect, zoom)
        while len(keys) > MAX_TILES and zoom > 0:
            zoom -= 1
            keys = self.tiles_for(view_rect, zoom)

        self.zoom = zoom
        self.wanted = set(keys)
        for key in keys:
            if key in self.items:
                continue
            pixmap = self.fetcher.get(key)
            if pixmap is not None:
                self.add_tile(key, pixmap)
        self.fetcher.retain(self.wanted)
        self.purge()

    def visible_rect(self) -> QRectF:
        """
        Returns the scene area to load the tiles for: the viewport and a margin.
        :return: The rectangle in scene coordinates.
        """
        rect = self.schematic.mapToScene(
            self.schematic.viewport().rect()
        ).boundingRect()
        return rect.adjusted(
            -rect.width() * VIEW_MARGIN,
            -rect.height() * VIEW_MARGIN,
            rect.width() * VIEW_MARGIN,
            rect.height() * VIEW_MARGIN,
        )

    def tiles_for(self, scene_rect: QRectF, zoom: int) -> list[TileKey]:
        """
        Returns the tiles covering a scene area, with the ones closest to the
        centre first, so that they are loaded first.
        :param scene_rect: The area in scene coordinates.
        :param zoom: The zoom level.
        :return: The (z, x, y) tiles.
        """
        transform = self.schematic.geo_transform
        left, top = transform.scene_to_merc(scene_rect.left(), scene_rect.top())
        right, bottom = transform.scene_to_merc(scene_rect.right(), scene_rect.bottom())
        keys = tiles_in_bounds(zoom, left, bottom, right, top)

        centre = transform.scene_to_merc(*scene_rect.center().toTuple())

        def distance(key: TileKey) -> float:
            tile_left, tile_top, tile_right, tile_bottom = tile_bounds(*key)
            return math.hypot(
                (tile_left + tile_right) / 2 - centre[0],
                (tile_top + tile_bottom) / 2 - centre[1],
            )

        return sorted(keys, key=distance)

    def add_tile(self, key: TileKey, pixmap: QPixmap) -> None:
        """
        Places a tile on the scene.
        :param key: The (z, x, y) tile.
        :param pixmap: The tile image.
        :return: None
        """
        transform = self.schematic.geo_transform
        left, top, right, _ = tile_bounds(*key)
        item = TileItem(key, pixmap)
        item.setPos(*transform.merc_to_scene(left, top))
        item.setScale((right - left) / transform.metres_per_unit / pixmap.width())
        self.schematic.scene.addItem(item)
        self.items[key] = item

    def on_tile_ready(self, z: int, x: int, y: int, pixmap: QPixmap) -> None:
        """
        Places a downloaded tile, if it is still needed.
        :param z: The zoom level.
        :param x: The tile column.
        :param y: The tile row.
        :param pixmap: The tile image.
        :return: None
        """
        key = (z, x, y)
        if key not in self.wanted or key in self.items or not self.is_active:
            return
        self.add_tile(key, pixmap)
        self.purge()

    def purge(self) -> None:
        """
        Removes the tiles that are outside the viewport. The tiles of another zoom
        level are kept, under the new ones, until all the tiles of the current zoom
        level are loaded, to avoid showing a blank map while zooming.
        :return: None
        """
        complete = self.wanted.issubset(self.items)
        for key in list(self.items):
            if key in self.wanted:
                continue
            if key[0] == self.zoom or complete:
                self.remove_tile(key)

    def remove_tile(self, key: TileKey) -> None:
        """
        Removes a tile from the scene.
        :param key: The (z, x, y) tile.
        :return: None
        """
        item = self.items.pop(key, None)
        if item is not None:
            if item.scene() is not None:
                item.scene().removeItem(item)

    def clear(self) -> None:
        """
        Removes all the tiles from the scene and cancels the downloads. This must be
        called before the scene is cleared, as the scene deletes its items.
        :return: None
        """
        for key in list(self.items):
            self.remove_tile(key)
        self.wanted = set()
        self.fetcher.retain([])
        self._timer.stop()
        self._signature = None

    def _set_active(self, active: bool) -> None:
        """
        Emits active_changed when the layer is shown or hidden.
        :param active: Whether the layer is active.
        :return: None
        """
        if active != self._active:
            self._active = active
            self.active_changed.emit(active)

    def _view_signature(self) -> tuple:
        """
        Returns a value that changes when the visible area or the zoom changes.
        :return: The signature.
        """
        rect = self.schematic.mapToScene(
            self.schematic.viewport().rect()
        ).boundingRect()
        return (
            round(rect.left(), 2),
            round(rect.top(), 2),
            round(self.schematic.transform().m11(), 6),
            round(rect.width(), 2),
            round(rect.height(), 2),
        )
