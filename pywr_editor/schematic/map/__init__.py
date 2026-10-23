from .projection import (
    Projector,
    WEB_MERCATOR_CRS,
    count_outside_area_of_use,
    crs_name,
    is_valid_crs,
    looks_like_degrees,
)
from .geo_transform import GeoTransform, europe_extent_merc
from .tile_cache import TileCache
from .tile_fetcher import TileFetcher
from .tile_source import ATTRIBUTION, ATTRIBUTION_URL, MAX_ZOOM
from .tile_layer import TileItem, TileLayer
from .node_footprints import FootprintItem, NodeFootprints
from .gis_overlay import (
    GisLayerData,
    GisLayerError,
    GisLayerGroup,
    GisLayerInfo,
    GisLayerLoader,
    GisOverlay,
    GisPathItem,
    GisPointItem,
)


def is_map_item(item) -> bool:
    """
    Checks whether a scene item belongs to the map (a tile or an item of a GIS layer)
    and is not a schematic item.
    :param item: The scene item.
    :return: True if the item is a map item.
    """
    return isinstance(
        item, (TileItem, GisLayerGroup, GisPathItem, GisPointItem, FootprintItem)
    )
