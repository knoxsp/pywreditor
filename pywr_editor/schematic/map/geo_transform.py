import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from .tile_source import TILE_SIZE

ORIGIN_SHIFT = 20037508.342789244
""" Half the width of the Web Mercator world in metres. The tile grid starts at the
north west corner (-ORIGIN_SHIFT, ORIGIN_SHIFT) """
INITIAL_RESOLUTION = 2 * ORIGIN_SHIFT / TILE_SIZE
""" The metres covered by one pixel of a tile at zoom level 0 """

MIN_SPAN_METRES = 1000.0
""" Smallest extent, in Web Mercator metres, fitted to the schematic. This stops a
single node (or nodes sharing a location) from zooming the map to an infinite scale """
FILL_RATIO = 0.7
""" The share of the schematic size that the geographic extent of the nodes fills """


EUROPE_LONLAT_EXTENT = (-12.0, 34.0, 32.0, 62.0)
""" The (west, south, east, north) extent, in degrees, shown by the geographic view when
no node has a geographic position: Europe including the UK and Ireland """
EARTH_RADIUS = 6378137.0
""" The radius of the sphere used by Web Mercator, in metres """


def lonlat_to_merc(lon: float, lat: float) -> tuple[float, float]:
    """
    Converts a WGS84 longitude and latitude to Web Mercator without pyproj.
    :param lon: The longitude in degrees.
    :param lat: The latitude in degrees.
    :return: The (x, y) Web Mercator coordinates in metres.
    """
    return (
        EARTH_RADIUS * math.radians(lon),
        EARTH_RADIUS * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)),
    )


def europe_extent_merc() -> tuple[tuple[float, float], tuple[float, float]]:
    """
    Returns the south west and north east corners of the default extent in Web
    Mercator.
    :return: The two (x, y) corners in metres.
    """
    west, south, east, north = EUROPE_LONLAT_EXTENT
    return lonlat_to_merc(west, south), lonlat_to_merc(east, north)


@dataclass(frozen=True)
class GeoTransform:
    """
    Maps Web Mercator coordinates (metres) to scene coordinates (the schematic units)
    and back. Scene units cannot be Web Mercator metres: nodes are a few tens of units
    wide, so they would be invisible on a map spanning kilometres, and the content
    would be thousands of kilometres away from the schematic bounds. Instead, the
    transform is fitted to the nodes, so that the geographic view is displayed at a
    scale comparable to the schematic view. The y axis is flipped to match Qt's y-down
    convention.
    """

    centre_merc: tuple[float, float]
    """ The Web Mercator coordinate placed at the scene centre """
    centre_scene: tuple[float, float]
    """ The scene coordinate of the centre """
    metres_per_unit: float
    """ The number of Web Mercator metres in one scene unit """

    @classmethod
    def fit(
        cls,
        merc_points: Iterable[Sequence[float]],
        scene_size: Sequence[float],
    ) -> "GeoTransform":
        """
        Creates the transform that centres the points in the scene and fits them in
        FILL_RATIO of the scene size.
        :param merc_points: The (x, y) Web Mercator coordinates of the nodes. When
        empty, a transform centred on the origin with a 1 km extent is returned.
        :param scene_size: The (width, height) of the schematic.
        :return: The GeoTransform instance.
        """
        points = list(merc_points)
        if len(points) > 0:
            min_x = min(p[0] for p in points)
            max_x = max(p[0] for p in points)
            min_y = min(p[1] for p in points)
            max_y = max(p[1] for p in points)
        else:
            min_x = max_x = min_y = max_y = 0.0

        # a single scale is used on both axes to avoid distorting the map: the
        # larger extent, compared to the scene, drives it
        width = max(scene_size[0], 1) * FILL_RATIO
        height = max(scene_size[1], 1) * FILL_RATIO
        metres_per_unit = max(
            max(max_x - min_x, MIN_SPAN_METRES) / width,
            max(max_y - min_y, MIN_SPAN_METRES) / height,
        )

        return cls(
            centre_merc=((min_x + max_x) / 2, (min_y + max_y) / 2),
            centre_scene=(scene_size[0] / 2, scene_size[1] / 2),
            metres_per_unit=metres_per_unit,
        )

    def merc_to_scene(self, x: float, y: float) -> tuple[float, float]:
        """
        Converts Web Mercator coordinates to scene coordinates.
        :param x: The Web Mercator x coordinate (metres).
        :param y: The Web Mercator y coordinate (metres).
        :return: The (x, y) scene coordinates.
        """
        return (
            self.centre_scene[0] + (x - self.centre_merc[0]) / self.metres_per_unit,
            self.centre_scene[1] - (y - self.centre_merc[1]) / self.metres_per_unit,
        )

    def scene_to_merc(self, x: float, y: float) -> tuple[float, float]:
        """
        Converts scene coordinates to Web Mercator coordinates.
        :param x: The scene x coordinate.
        :param y: The scene y coordinate.
        :return: The (x, y) Web Mercator coordinates (metres).
        """
        return (
            self.centre_merc[0] + (x - self.centre_scene[0]) * self.metres_per_unit,
            self.centre_merc[1] - (y - self.centre_scene[1]) * self.metres_per_unit,
        )

    def metres_per_pixel(self, view_scale: float) -> float:
        """
        Returns the ground resolution on screen.
        :param view_scale: The view scale (screen pixels per scene unit).
        :return: The Web Mercator metres covered by one screen pixel.
        """
        return self.metres_per_unit / max(view_scale, 1e-12)

    def scale_for_zoom(self, tile_zoom: int) -> float:
        """
        Returns the view scale at which the tiles of a zoom level are displayed
        without being enlarged or reduced (one tile pixel per screen pixel).
        :param tile_zoom: The tile zoom level.
        :return: The view scale.
        """
        return self.metres_per_unit / (INITIAL_RESOLUTION / 2**tile_zoom)

    @staticmethod
    def is_finite(point: Sequence[float]) -> bool:
        """
        Checks that a projected point can be placed on the schematic. pyproj returns
        infinity for the coordinates that cannot be projected, and the points
        beyond the Web Mercator world (the latitudes above about 85.05 degrees)
        are not covered by the map.
        :param point: The coordinates.
        :return: True if all the values are finite and within the Web Mercator world.
        """
        return all(
            math.isfinite(value) and abs(value) <= ORIGIN_SHIFT for value in point
        )
