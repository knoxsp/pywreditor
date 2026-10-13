import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from PySide6.QtCore import QUuid
from PySide6.QtGui import QColor

from pywr_editor.model import BaseShape, Constants
from pywr_editor.style import Color

if TYPE_CHECKING:
    from pywr_editor.model import ModelConfig


def parse_layer_color(
    value: Sequence[int] | str | None, default_rgb: Sequence[int]
) -> QColor:
    """
    Parses a layer colour. Like the shape colours, this is a list of RGB or RGBA
    values (0-255). A CSS-like hex string ("#rrggbb" or "#rrggbbaa", where the optional
    last pair is the opacity) is also accepted. Qt reads 8-digit hex strings as
    #aarrggbb, so the string is parsed here.
    :param value: The colour.
    :param default_rgb: The RGB or RGBA colour to use if the colour is not valid.
    :return: The QColor instance.
    """
    if isinstance(value, str):
        match = re.fullmatch(r"#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", value.strip())
        if match is not None:
            rgb = [int(match.group(1)[i : i + 2], 16) for i in (0, 2, 4)]
            if match.group(2) is not None:
                rgb.append(int(match.group(2), 16))
            return QColor.fromRgb(*rgb)
        return QColor.fromRgb(*default_rgb)

    return BaseShape.parse_color(value, default_rgb)


@dataclass
class GisLayerConfig:
    layer_dict: dict
    """ The GIS layer dictionary with the ID, name, path and style keys. """

    default_stroke_color: tuple[int, int, int] = Color(name="blue", shade=700).rgb
    """ The stroke colour to use when it is not provided """
    default_fill_color: tuple[int, int, int, int] = (
        *Color(name="blue", shade=100).rgb,
        100,
    )
    """ The fill colour to use when it is not provided """
    default_stroke_width: float = 1.5
    """ The stroke width to use when it is not provided """

    def __post_init__(self):
        """
        Define the layer properties.
        :return: None
        """
        if isinstance(self.layer_dict, dict):
            self.id = self.layer_dict.get("id", None)

    @staticmethod
    def generate_id() -> str:
        """
        Creates a new layer ID.
        :return: A unique layer ID.
        """
        return QUuid().createUuid().toString()[1:7]

    @property
    def name(self) -> str:
        """
        Returns the layer's name.
        :return: The layer name, or the file name if one is not set.
        """
        return self.layer_dict.get("name") or Path(self.path).stem

    @property
    def path(self) -> str:
        """
        Returns the layer's file path, as stored in the model file (this may be
        relative to the model file).
        :return: The file path.
        """
        return self.layer_dict["path"]

    @property
    def file_type(self) -> str:
        """
        Returns the layer's file type, inferred from the file extension.
        :return: Either "shapefile" or "geojson".
        """
        if Path(self.path).suffix.lower() == ".shp":
            return "shapefile"
        return "geojson"

    @property
    def crs(self) -> str | None:
        """
        Returns the CRS of the file coordinates, when the user provided one. This
        takes priority over the CRS defined in the file and is needed for the files
        that do not define it (e.g. a Shapefile without the .prj file).
        :return: The CRS definition (e.g. an EPSG code) or None to use the file CRS.
        """
        crs = self.layer_dict.get("crs", None)
        if isinstance(crs, str) and len(crs.strip()) > 0:
            return crs.strip()
        return None

    @property
    def visible(self) -> bool:
        """
        Returns whether the layer is visible on the schematic.
        :return: True if the layer is visible, False otherwise.
        """
        visible = self.layer_dict.get("visible", True)
        return visible if isinstance(visible, bool) else True

    @property
    def stroke_color(self) -> QColor:
        """
        Returns the layer's stroke (outline) colour.
        :return: The colour instance.
        """
        return parse_layer_color(
            self.layer_dict.get("stroke_color", None), self.default_stroke_color
        )

    @property
    def fill_color(self) -> QColor:
        """
        Returns the layer's fill colour, used for polygon geometries.
        :return: The colour instance.
        """
        return parse_layer_color(
            self.layer_dict.get("fill_color", None), self.default_fill_color
        )

    @property
    def stroke_width(self) -> float:
        """
        Returns the layer's stroke width.
        :return: The stroke width.
        """
        width = self.layer_dict.get("stroke_width", self.default_stroke_width)
        if (
            isinstance(width, bool)
            or not isinstance(width, (int, float))
            or not math.isfinite(width)
            or width <= 0
        ):
            return self.default_stroke_width
        return width

    def is_valid(self) -> bool:
        """
        Checks the layer configuration dictionary.
        :return: Whether the layer configuration is valid.
        """
        return (
            isinstance(self.layer_dict, dict)
            and "id" in self.layer_dict
            and "path" in self.layer_dict
            and isinstance(self.layer_dict["id"], str)
            and isinstance(self.layer_dict["path"], str)
            and len(self.layer_dict["path"]) > 0
        )


@dataclass
class GisLayers:
    model: "ModelConfig"
    """ The ModelConfig instance """

    def get_all(self) -> list[GisLayerConfig]:
        """
        Returns the list of GIS overlay layers, in the order they should be
        stacked on the schematic (the first layer is drawn at the bottom).
        :return: A list of GisLayerConfig instances.
        """
        layers = []
        for layer_dict in self.model.map_config[Constants.GIS_LAYERS_KEY.value]:
            layer = GisLayerConfig(layer_dict=layer_dict)
            if layer.is_valid():
                layers.append(layer)

        return layers

    def find_index(self, layer_id: str) -> int | None:
        """
        Finds the layer index in the list by its ID.
        :param layer_id: The layer ID to look for.
        :return: The layer index if the ID is found. None otherwise.
        """
        return next(
            (
                idx
                for idx, layer_dict in enumerate(
                    self.model.map_config[Constants.GIS_LAYERS_KEY.value]
                )
                if layer_dict.get("id") == layer_id
            ),
            None,
        )

    def find(
        self, layer_id: str, as_dict: bool = False
    ) -> dict | GisLayerConfig | None:
        """
        Find a layer by ID.
        :param layer_id: The layer ID.
        :param as_dict: Whether to return the layer configuration dictionary or
        the layer instance. Default to False.
        :return: The layer dictionary or instance if the ID is found, None
        otherwise.
        """
        idx = self.find_index(layer_id)
        if idx is None:
            return None

        layer_dict = self.model.map_config[Constants.GIS_LAYERS_KEY.value][idx]
        if as_dict:
            return layer_dict

        layer = GisLayerConfig(layer_dict=layer_dict)
        return layer if layer.is_valid() else None

    @staticmethod
    def portable_path(path: str) -> str:
        """
        Converts the Windows path separators to forward slashes, which are valid on
        every platform, so that a model saved on Windows opens on Linux and macOS.
        :param path: The path.
        :return: The path with forward slashes on Windows, unchanged otherwise.
        """
        return path.replace("\\", "/") if os.sep == "\\" else path

    def add(self, path: str, name: str | None = None) -> dict:
        """
        Adds a new GIS overlay layer, stacked on top of the existing ones.
        :param path: The GeoJSON or Shapefile path. This is converted to a path
        relative to the model file, when possible.
        :param name: The layer name. Optional - the file name is used if not
        provided.
        :return: The new layer dictionary.
        """
        layer_dict = {
            "id": GisLayerConfig.generate_id(),
            "name": name or Path(path).stem,
            "path": self.portable_path(self.model.path_to_relative(path)),
            "visible": True,
        }
        self.model.writable_map_config[Constants.GIS_LAYERS_KEY.value].append(
            layer_dict
        )
        self.model.has_changed()

        return layer_dict

    def delete(self, layer_id: str) -> None:
        """
        Deletes a layer by ID.
        :param layer_id: The layer ID.
        :return: None
        """
        idx = self.find_index(layer_id)
        if idx is None:
            return

        del self.model.writable_map_config[Constants.GIS_LAYERS_KEY.value][idx]
        self.model.has_changed()

    def update(self, layer_id: str, layer_dict: dict) -> None:
        """
        Updates an existing layer's configuration.
        :param layer_id: The layer ID to update.
        :param layer_dict: The new layer dictionary.
        :return: None
        """
        idx = self.find_index(layer_id)
        if idx is None:
            return

        self.model.writable_map_config[Constants.GIS_LAYERS_KEY.value][idx] = layer_dict
        self.model.has_changed()

    def move(self, layer_id: str, new_index: int) -> None:
        """
        Moves a layer to a new position in the stacking order.
        :param layer_id: The layer ID to move.
        :param new_index: The new index of the layer in the list.
        :return: None
        """
        idx = self.find_index(layer_id)
        if idx is None:
            return

        layers = self.model.writable_map_config[Constants.GIS_LAYERS_KEY.value]
        new_index = max(0, min(new_index, len(layers) - 1))
        layer_dict = layers.pop(idx)
        layers.insert(new_index, layer_dict)
        self.model.has_changed()

    def set_property(self, layer_id: str, key: str, value: Any) -> None:
        """
        Sets or, when the value is None, removes a layer property.
        :param layer_id: The layer ID.
        :param key: The property name (e.g. "name" or "stroke_width").
        :param value: The new value. None removes the property.
        :return: None
        """
        layer_dict = self.find(layer_id, as_dict=True)
        if layer_dict is None:
            return

        if value is None:
            layer_dict.pop(key, None)
        else:
            layer_dict[key] = value
        self.model.has_changed()

    def set_visible(self, layer_id: str, visible: bool) -> None:
        """
        Sets whether a layer is visible on the schematic.
        :param layer_id: The layer ID.
        :param visible: Whether the layer should be visible.
        :return: None
        """
        idx = self.find_index(layer_id)
        if idx is None:
            return

        self.model.writable_map_config[Constants.GIS_LAYERS_KEY.value][idx][
            "visible"
        ] = visible
        self.model.has_changed()
