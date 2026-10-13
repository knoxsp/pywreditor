import math
from typing import Sequence

import pyproj

WEB_MERCATOR_CRS = "EPSG:3857"
""" The CRS used by OSM tiles and, internally, by the geographic schematic view """


def is_valid_crs(crs: str) -> bool:
    """
    Checks whether a string is a valid CRS definition (e.g. an EPSG code, a proj4
    string or a WKT definition).
    :param crs: The CRS definition to validate.
    :return: True if pyproj can parse the CRS, False otherwise.
    """
    try:
        pyproj.CRS.from_user_input(crs)
        return True
    except pyproj.exceptions.CRSError:
        return False


class Projector:
    """
    Converts coordinates between a source CRS (e.g. the CRS used by a node's
    "geographic" position or by a GIS overlay layer) and Web Mercator (EPSG:3857),
    the CRS used internally to place items on the schematic when the geographic
    view is active, since this is also the CRS OSM tiles are published in.
    """

    def __init__(self, source_crs: "str | pyproj.CRS" = "EPSG:4326"):
        """
        Initialise the class.
        :param source_crs: The CRS the input coordinates are provided in (e.g. an
        EPSG code or a WKT definition). Default to "EPSG:4326".
        """
        self.source_crs = source_crs
        self._to_merc = pyproj.Transformer.from_crs(
            source_crs, WEB_MERCATOR_CRS, always_xy=True
        )
        self._from_merc = pyproj.Transformer.from_crs(
            WEB_MERCATOR_CRS, source_crs, always_xy=True
        )

    def lonlat_to_merc(self, x: float, y: float) -> tuple[float, float]:
        """
        Converts a coordinate pair from the source CRS to Web Mercator.
        :param x: The x coordinate (longitude, when the source CRS is EPSG:4326).
        :param y: The y coordinate (latitude, when the source CRS is EPSG:4326).
        :return: The (x, y) coordinate pair in Web Mercator metres.
        """
        return self._to_merc.transform(x, y)

    def lonlat_to_merc_many(
        self, x: Sequence[float], y: Sequence[float]
    ) -> tuple[list[float], list[float]]:
        """
        Converts many coordinate pairs from the source CRS to Web Mercator. The
        coordinates that cannot be projected are returned as infinity.
        :param x: The x coordinates.
        :param y: The y coordinates.
        :return: The x and y coordinates in Web Mercator metres.
        """
        merc_x, merc_y = self._to_merc.transform(list(x), list(y))
        return list(merc_x), list(merc_y)

    def merc_to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        """
        Converts a coordinate pair from Web Mercator back to the source CRS.
        :param x: The x coordinate in Web Mercator metres.
        :param y: The y coordinate in Web Mercator metres.
        :return: The (x, y) coordinate pair in the source CRS.
        """
        return self._from_merc.transform(x, y)


def count_outside_area_of_use(
    crs: str, points: Sequence[Sequence[float]], tolerance: float = 1.0
) -> tuple[int, int] | None:
    """
    Counts the points that are outside the area where a CRS is defined, which
    usually means that the wrong CRS or axis order was used.
    :param crs: The CRS the points are provided in.
    :param points: The (x, y) points.
    :param tolerance: The margin, in degrees, added to the area of use.
    :return: The number of points outside the area and the total number of points.
    None if the CRS does not define an area of use or the check cannot be done.
    """
    try:
        crs_obj = pyproj.CRS.from_user_input(crs)
        area = crs_obj.area_of_use
        if area is None:
            return None
        transformer = pyproj.Transformer.from_crs(crs_obj, "EPSG:4326", always_xy=True)
    except pyproj.exceptions.ProjError:
        return None

    outside = 0
    for x, y in points:
        lon, lat = transformer.transform(x, y)
        is_inside = (
            math.isfinite(lon)
            and math.isfinite(lat)
            and area.south - tolerance <= lat <= area.north + tolerance
            # areas crossing the antimeridian (west > east) are not checked
            and (
                area.west > area.east
                or area.west - tolerance <= lon <= area.east + tolerance
            )
        )
        outside += 0 if is_inside else 1
    return outside, len(points)


def looks_like_degrees(crs: str, points: Sequence[Sequence[float]]) -> bool:
    """
    Checks whether the coordinates look like longitudes and latitudes while the CRS
    uses metres, which means that the CRS was changed without converting the
    coordinates (or the wrong CRS was set): the values are valid but they are a few
    metres from the origin of the CRS.
    :param crs: The CRS the points are provided in.
    :param points: The (x, y) points.
    :return: True if the CRS is projected and all the points are within the range of
    the degrees.
    """
    try:
        is_projected = pyproj.CRS.from_user_input(crs).is_projected
    except pyproj.exceptions.ProjError:
        return False
    return (
        is_projected
        and len(points) > 0
        and all(abs(x) <= 180 and abs(y) <= 90 for x, y in points)
    )
