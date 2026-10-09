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

    def __init__(self, source_crs: str = "EPSG:4326"):
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

    def merc_to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        """
        Converts a coordinate pair from Web Mercator back to the source CRS.
        :param x: The x coordinate in Web Mercator metres.
        :param y: The y coordinate in Web Mercator metres.
        :return: The (x, y) coordinate pair in the source CRS.
        """
        return self._from_merc.transform(x, y)
