from enum import Enum


class _Unchanged:
    def __repr__(self) -> str:
        return "UNCHANGED"


UNCHANGED = _Unchanged()
""" Value used to leave a style property as it is, as opposed to None, which removes
it """

MIN_NODE_SIZE = 0.25
MAX_NODE_SIZE = 5.0
""" The limits of the node size scale factor """


class Constants(Enum):
    EDITOR_CONFIG_KEY = "pywr_editor"
    """ key in JSON containing the editor's settings """
    SHAPES_KEY = "shapes"
    """ key in editor's setting dictionary where to locate the shapes  """
    POSITION_KEY = "schematic"
    """ key in the node's "position" dictionary where to store the schematic position
    (in schematic pixels). This is the key defined by the pywr specification """
    LEGACY_POSITION_KEY = "editor_position"
    """ key used by previous versions of the editor to store the schematic position.
    It is migrated to POSITION_KEY when a model is loaded """
    NODE_STYLE_KEY = "node_style"
    """ key defying where to store the style describing the node's style """
    NODE_COLOR_KEY = "node_color"
    """ key defying where to store the colour highlighting the node on the schematic """
    NODE_SIZE_KEY = "node_size"
    """ key defying where to store the scale factor of the node symbol """
    NODE_TYPES_KEY = "node_types"
    """ key in editor's setting dictionary where to store the style of the node types """
    EDGE_COLOR_KEY = "edge_color"
    """ key defying where to store the style describing the edge colour """
    CUSTOM_NODE_GROUP_NAME = "Custom"
    """ the name of the group for custom nodes"""
    DEFAULT_SCHEMATIC_SIZE = [800, 600]
    """ default size of the schematic when this is not provided in the model file """
    SCHEMATIC_SIZE_KEY = "schematic_size"
    """ key where to store the schematic size """
    GEOGRAPHIC_KEY = "geographic"
    """ key in a node's "position" dict containing its [longitude, latitude] """
    MAP_KEY = "map"
    """ key in the editor's setting dictionary where to locate the map settings """
    DEFAULT_GEOGRAPHIC_CRS = "EPSG:4326"
    """ CRS assumed for a node's "geographic" coordinates when the model does not
    override it """
    GIS_LAYERS_KEY = "layers"
    """ key, under the map setting dictionary, holding the list of GIS overlay
    layers """
