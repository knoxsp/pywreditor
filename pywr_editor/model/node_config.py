import math
from copy import deepcopy as dp
from typing import Sequence

from pywr_editor.model import ComponentConfig, Constants, PywrNodesData
from pywr_editor.model.constants import MAX_NODE_SIZE, MIN_NODE_SIZE
from pywr_editor.style import Color

"""
 Handles the model node configuration
"""


def valid_node_size(value: object) -> float | None:
    """
    Validates a node size scale factor.
    :param value: The value.
    :return: The factor as float, None if the value is not a number in range.
    """
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and MIN_NODE_SIZE <= value <= MAX_NODE_SIZE
    ):
        return float(value)
    return None


class NodeConfig(ComponentConfig):
    def __init__(self, props: dict = None, deepcopy: bool = False):
        """
        Initialise the class.
        :param props: The node dictionary.
        :param deepcopy: Whether to create a deepcopy of the dictionary. Default to
        False.
        """
        super().__init__(props=props)

        self.custom_node_group_name = Constants.CUSTOM_NODE_GROUP_NAME.value
        if deepcopy is True:
            self.props = dp(self.props)

    @property
    def name(self) -> str | None:
        """
        Return the node name.
        :return: The name of the node
        """
        return self.props["name"]

    @property
    def custom_style(self) -> str | None:
        """
        Return the custom node style.
        :return: The node style or None if this is not set.
        """
        node_style_key = Constants.NODE_STYLE_KEY.value
        if (
            "position" not in self.props
            or node_style_key not in self.props["position"]
            or not isinstance(self.props["position"][node_style_key], str)
        ):
            return None

        return self.props["position"][node_style_key].lower()

    @property
    def edge_color(self) -> str | None:
        """
        Return the color name to use for the edge.
        :return: The edge_color property or None if this is not set.
        """
        edge_color_key = Constants.EDGE_COLOR_KEY.value
        if (
            "position" not in self.props
            or edge_color_key not in self.props["position"]
            or not isinstance(self.props["position"][edge_color_key], str)
        ):
            return None

        return self.props["position"][edge_color_key]

    @property
    def node_color(self) -> str | None:
        """
        Return the name of the colour highlighting the node on the schematic.
        :return: The colour name (a key of Color.colors) or None if not set.
        """
        position = self.props.get("position")
        if not isinstance(position, dict):
            return None
        value = position.get(Constants.NODE_COLOR_KEY.value)
        if isinstance(value, str) and value in Color.colors:
            return value
        return None

    @property
    def node_size(self) -> float | None:
        """
        Return the scale factor of the node symbol stored for this node.
        :return: The factor, None if not set or not valid.
        """
        position = self.props.get("position")
        if not isinstance(position, dict):
            return None
        return valid_node_size(position.get(Constants.NODE_SIZE_KEY.value))

    @property
    def raw_geographic(self) -> list | dict | None:
        """
        Return the stored geographic value as it is in the model: an [x, y] list
        or a GeoJSON geometry dictionary.
        :return: The value, None if the node does not have one.
        """
        position = self.props.get("position")
        if not isinstance(position, dict):
            return None
        return position.get(Constants.GEOGRAPHIC_KEY.value)

    @staticmethod
    def _is_xy(value) -> bool:
        return (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and all(
                isinstance(v, (int, float))
                and not isinstance(v, bool)
                and math.isfinite(v)
                for v in value[:2]
            )
        )

    @property
    def geographic_position(self) -> list[float] | None:
        """
        Return the node's geographic position, as stored in the map CRS (e.g.
        longitude and latitude for EPSG:4326). The position can be stored as an
        [x, y] pair or as a GeoJSON "Point" or "Polygon", in which case the
        centroid of the polygon is returned.
        :return: The [x, y] pair, or None if the node does not have a valid one.
        """
        value = self.raw_geographic
        if self._is_xy(value) and len(value) == 2:
            return value
        if not isinstance(value, dict):
            return None

        coordinates = value.get("coordinates")
        geometry_type = value.get("type")
        if geometry_type == "Point" and self._is_xy(coordinates):
            return [coordinates[0], coordinates[1]]
        if geometry_type == "Polygon":
            ring = (
                coordinates[0]
                if isinstance(coordinates, list) and coordinates
                else None
            )
            if (
                isinstance(ring, list)
                and len(ring) > 0
                and all(self._is_xy(v) for v in ring)
            ):
                return self.polygon_centroid(ring)
        return None

    @property
    def geographic_rings(self) -> list[list[list[float]]]:
        """
        Return the rings of the polygon stored as the node's geographic position,
        in the map CRS. Empty if the position is not a polygon.
        :return: The list of rings. Each ring is a list of [x, y, ...] vertices.
        """
        value = self.raw_geographic
        if not isinstance(value, dict) or value.get("type") != "Polygon":
            return []
        coordinates = value.get("coordinates")
        if not isinstance(coordinates, list):
            return []
        return [
            ring
            for ring in coordinates
            if isinstance(ring, list)
            and len(ring) > 2
            and all(self._is_xy(v) for v in ring)
        ]

    @staticmethod
    def polygon_centroid(ring: list[list[float]]) -> list[float]:
        """
        Computes the (area-weighted) centroid of a polygon ring. A degenerate ring
        falls back to the mean of its vertices.
        :param ring: The list of vertices.
        :return: The [x, y] centroid.
        """
        area = cx = cy = 0.0
        for (x0, y0, *_), (x1, y1, *_) in zip(ring, ring[1:] + ring[:1]):
            cross = x0 * y1 - x1 * y0
            area += cross
            cx += (x0 + x1) * cross
            cy += (y0 + y1) * cross
        if abs(area) < 1e-12:
            return [
                sum(v[0] for v in ring) / len(ring),
                sum(v[1] for v in ring) / len(ring),
            ]
        return [cx / (3 * area), cy / (3 * area)]

    @property
    def position(self) -> list[float | int] | None:
        """
        Return the node position.
        :return: The node position if available, None otherwise.
        """
        position_key = Constants.POSITION_KEY.value
        if (
            "position" in self.props
            and position_key in self.props["position"]
            and isinstance(self.props["position"][position_key], (list, tuple))
            and len(self.props["position"][position_key]) == 2
        ):
            return self.props["position"][position_key]
        return None

    def change_name(self, name: str) -> None:
        """
        Change the node name.
        :param name: The new name.
        :return: None. This only update the internal dictionary.
        """
        self.props["name"] = name

    def change_position(self, position: list[float]) -> None:
        """
        Change the node position.
        :param position: The new position to set.
        :return: None. This only update the internal dictionary.
        """
        position_key = Constants.POSITION_KEY.value
        if "position" in self.props:
            self.props["position"][position_key] = position
        else:
            self.props["position"] = {position_key: position}

    @property
    def is_visible(self) -> bool:
        """
        Return True if the node is visible on the schematic.
        :return: True if the node is visible, False otherwise.
        """
        if "visible" not in self.props or not isinstance(self.props["visible"], bool):
            return True

        return self.props["visible"]

    @property
    def is_virtual(self) -> bool:
        """
        Check if a node is virtual (i.e. the node is not connectable).
        :return: True if the node is virtual, False otherwise
        """
        return self.key in [
            "annualvirtualstorage",
            "virtualstorage",
            "aggregatednode",
            "aggregatedstorage",
            "seasonalvirtualstorage",
        ]

    @property
    def humanised_type(self) -> str:
        """
        Return a user-friendly string identifying the type of node.
        :return The node type.
        """
        pywr_nodes = PywrNodesData()
        if pywr_nodes.exists(self.type):
            return pywr_nodes.name(self.type)
        else:
            return self.custom_node_group_name

    @staticmethod
    def create(name: str, node_type: str, position: Sequence[float]) -> dict:
        """
        Create a new dictionary with the node properties.
        :param name: The node name.
        :param node_type: The node type.
        :param position: The node position.
        :return: A dictionary with the basic node properties.
        """
        return {
            "name": name,
            "type": node_type,
            "position": {
                Constants.POSITION_KEY.value: [
                    round(position[0], 4),
                    round(position[1], 4),
                ]
            },
        }
