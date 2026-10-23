"""
The OpenStreetMap raster tile source. OSM tiles are published in Web Mercator
(EPSG:3857) as a slippy map pyramid: zoom level z is a grid of 2^z x 2^z tiles of
256 x 256 pixels. The usage policy
(https://operations.osmfoundation.org/policies/tiles/) requires a descriptive
User-Agent, caching, a limit on concurrent connections and a visible attribution.
"""

from pywr_editor import __version__

OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
""" The XYZ URL template of the tile server """
TILE_SIZE = 256
""" The tile width and height in pixels """
MAX_ZOOM = 19
""" The highest zoom level published by the tile server """
ATTRIBUTION = "© OpenStreetMap contributors"
""" The attribution text to display while the tiles are visible """
ATTRIBUTION_URL = "https://www.openstreetmap.org/copyright"
""" The page the attribution links to """
USER_AGENT = f"pywr-editor/{__version__} (+https://github.com/pywr-editor/editor)"
""" The User-Agent identifying the application to the tile server """


def tile_url(z: int, x: int, y: int) -> str:
    """
    Returns the URL of a tile.
    :param z: The zoom level.
    :param x: The tile column.
    :param y: The tile row (0 is the northern edge).
    :return: The URL.
    """
    return OSM_TILE_URL.format(z=z, x=x, y=y)
