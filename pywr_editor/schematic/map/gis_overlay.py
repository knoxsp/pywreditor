import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pyproj
import shapefile
from PySide6.QtCore import QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsPathItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from pywr_editor.model import GisLayerConfig

from .projection import Projector, is_valid_crs

if TYPE_CHECKING:
    from pywr_editor.schematic import Schematic

BASE_Z_VALUE = -50.0
""" The z-value of the first layer. Layers are above the map tiles (about -100) and
below the nodes, edges and shapes (0 or more). Each layer is slightly above the
previous one, so they stack in the order of the list """
Z_VALUE_STEP = 0.01
""" The z-value difference between two layers """
SUPPORTED_SUFFIXES = {".shp": "shapefile", ".geojson": "geojson", ".json": "geojson"}
""" The supported file extensions and file type """
MAX_FEATURES = 200_000
""" The maximum number of features of a layer. Each feature is a graphics item, and
drawing more makes the schematic too slow """
MAX_VERTICES = 1_000_000
""" The maximum number of vertices of a layer. A layer with more vertices would make
the editor unresponsive """

GeometryKind = Literal["point", "line", "polygon"]


class GisLayerError(Exception):
    """
    Raised when a layer cannot be loaded. The message is shown to the user.
    """


@dataclass
class GisGeometry:
    """
    A feature geometry, in Web Mercator metres.
    """

    kind: GeometryKind
    """ The geometry type. Multi-part geometries are a single geometry """
    parts: list[list[tuple[float, float]]]
    """ The points (one per part), lines or rings. The holes of a polygon are
    rings as well """


@dataclass
class GisLayerData:
    """
    The geometries read from a layer file.
    """

    geometries: list[GisGeometry]
    """ The geometries, reprojected to Web Mercator """
    crs: str
    """ A description of the CRS of the file coordinates """
    crs_source: str
    """ Where the CRS comes from: "layer", "file" or "default" """
    feature_count: int
    """ The number of features read """
    vertex_count: int
    """ The number of vertices drawn """
    warnings: list[str] = field(default_factory=list)
    """ The problems that did not prevent the layer from being loaded """


class GisLayerLoader:
    """
    Reads a GeoJSON or Shapefile and reprojects the coordinates to Web Mercator.
    This is done once when a layer is added or changed. Only the final conversion to
    scene coordinates is repeated when the schematic is drawn again.
    """

    def __init__(self, default_crs: str = "EPSG:4326"):
        """
        Initialises the loader.
        :param default_crs: The CRS to use for the files that do not define one and
        that do not follow a standard that implies it (i.e. Shapefiles). GeoJSON
        files are always in EPSG:4326, as the specification requires.
        """
        self.default_crs = default_crs

    def load(self, layer: GisLayerConfig, file_path: str) -> GisLayerData:
        """
        Loads a layer.
        :param layer: The layer configuration.
        :param file_path: The path of the file. This must be absolute or relative
        to the working directory.
        :return: The layer data.
        :raises GisLayerError: When the file cannot be read.
        """
        path = Path(file_path)
        if not path.is_file():
            raise GisLayerError(f"The file {file_path} does not exist")

        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise GisLayerError(
                f'The file format "{suffix or path.name}" is not supported. Use a '
                "GeoJSON (.geojson) or a Shapefile (.shp). Other formats, such as "
                "GeoPackage, can be converted with QGIS or ogr2ogr"
            )

        warnings: list[str] = []
        if layer.crs is not None and not is_valid_crs(layer.crs):
            warnings.append(f'The CRS "{layer.crs}" is not valid and it was ignored')
        user_crs = layer.crs if layer.crs and is_valid_crs(layer.crs) else None

        if layer.file_type == "shapefile":
            features, file_crs, file_warnings = self._read_shapefile(path)
        else:
            features, file_crs, file_warnings = self._read_geojson(path)
        warnings += file_warnings

        # the CRS provided by the user wins, then the one in the file
        if user_crs is not None:
            crs, crs_source = pyproj.CRS.from_user_input(user_crs), "layer"
        elif file_crs is not None:
            crs, crs_source = file_crs, "file"
        else:
            crs, crs_source = pyproj.CRS.from_user_input(self.default_crs), "default"
            if layer.file_type == "shapefile":
                warnings.append(
                    f"The Shapefile does not define its CRS (the .prj file is "
                    f"missing). The CRS {self.default_crs} of the map is assumed: "
                    "set the CRS of the layer if this is wrong"
                )

        geometries, vertex_count, projection_warnings = self._project(
            features, Projector(crs)
        )
        warnings += projection_warnings
        return GisLayerData(
            geometries=geometries,
            crs=self._describe_crs(crs),
            crs_source=crs_source,
            feature_count=len(features),
            vertex_count=vertex_count,
            warnings=warnings,
        )

    @staticmethod
    def _describe_crs(crs: pyproj.CRS) -> str:
        """
        Returns a short name for a CRS.
        :param crs: The CRS.
        :return: The EPSG code, when it is known, or the CRS name.
        """
        epsg = crs.to_epsg()
        if epsg is not None:
            return f"EPSG:{epsg}"
        return crs.name

    def _read_geojson(
        self, path: Path
    ) -> tuple[list[dict], pyproj.CRS | None, list[str]]:
        """
        Reads a GeoJSON file.
        :param path: The file path.
        :return: The geometries (as GeoJSON dictionaries), the CRS and the warnings.
        The CRS is EPSG:4326, unless the file has the "crs" member of the old
        GeoJSON specification (2008).
        """
        warnings: list[str] = []
        try:
            with open(path, encoding="utf-8-sig") as file:
                data = json.load(file)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GisLayerError(f"The file is not a valid GeoJSON: {error}")
        if not isinstance(data, dict):
            raise GisLayerError("The file is not a valid GeoJSON object")

        crs = pyproj.CRS.from_epsg(4326)
        crs_member = data.get("crs")
        if isinstance(crs_member, dict):
            name = (crs_member.get("properties") or {}).get("name")
            try:
                crs = pyproj.CRS.from_user_input(name)
            except (pyproj.exceptions.CRSError, TypeError):
                warnings.append(
                    f'The CRS "{name}" of the file is not valid: EPSG:4326 is assumed'
                )

        geometries: list[dict] = []
        kind = data.get("type")
        if kind == "FeatureCollection":
            for feature in data.get("features") or []:
                geometry = (
                    feature.get("geometry") if isinstance(feature, dict) else None
                )
                if geometry is not None:
                    geometries.append(geometry)
        elif kind == "Feature":
            if data.get("geometry") is not None:
                geometries.append(data["geometry"])
        elif kind in self.geometry_types or kind == "GeometryCollection":
            geometries.append(data)
        else:
            raise GisLayerError(f'The GeoJSON object type "{kind}" is not supported')

        return geometries, crs, warnings

    def _read_shapefile(
        self, path: Path
    ) -> tuple[list[dict], pyproj.CRS | None, list[str]]:
        """
        Reads a Shapefile.
        :param path: The path of the .shp file.
        :return: The geometries (as GeoJSON dictionaries), the CRS from the .prj file
        or None if this is not available, and the warnings.
        """
        warnings: list[str] = []
        try:
            with shapefile.Reader(str(path)) as reader:
                geometries = [
                    shape.__geo_interface__
                    for shape in reader.shapes()
                    if shape.shapeType != shapefile.NULL
                ]
        except Exception as error:
            # the parser raises many kinds of errors (e.g. struct.error) when
            # the file is truncated or corrupted
            raise GisLayerError(f"The file is not a valid Shapefile: {error}")

        crs = None
        prj_file = next(
            (
                path.with_suffix(suffix)
                for suffix in (".prj", ".PRJ")
                if path.with_suffix(suffix).is_file()
            ),
            None,
        )
        if prj_file is not None:
            try:
                crs = pyproj.CRS.from_wkt(prj_file.read_text(errors="ignore"))
            except (pyproj.exceptions.CRSError, OSError):
                warnings.append("The CRS in the .prj file is not valid: it was ignored")

        return geometries, crs, warnings

    geometry_types = (
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
    )
    """ The GeoJSON geometry types """

    def _flatten(self, geometry: Any) -> list[tuple[GeometryKind, list[list[Any]]]]:
        """
        Converts a GeoJSON geometry to lists of points, lines or rings.
        :param geometry: The GeoJSON geometry dictionary.
        :return: The (kind, parts) pairs. Unsupported geometries return nothing.
        """
        if not isinstance(geometry, dict):
            return []
        kind = geometry.get("type")
        coords = geometry.get("coordinates")

        if kind == "GeometryCollection":
            result = []
            for item in geometry.get("geometries") or []:
                result += self._flatten(item)
            return result
        if not isinstance(coords, (list, tuple)):
            return []

        if kind == "Point":
            return [("point", [[coords]])]
        if kind == "MultiPoint":
            return [("point", [[point] for point in coords])]
        if kind == "LineString":
            return [("line", [list(coords)])]
        if kind == "MultiLineString":
            return [("line", [list(line) for line in coords])]
        if kind == "Polygon":
            return [("polygon", [list(ring) for ring in coords])]
        if kind == "MultiPolygon":
            return [("polygon", [list(ring) for poly in coords for ring in poly])]
        return []

    def _project(
        self, features: list[dict], projector: Projector
    ) -> tuple[list[GisGeometry], int, list[str]]:
        """
        Reprojects the geometries to Web Mercator.
        :param features: The GeoJSON geometries.
        :param projector: The projector from the CRS of the file.
        :return: The geometries, the number of vertices and the warnings.
        """
        if len(features) > MAX_FEATURES:
            raise GisLayerError(
                f"The layer is too large (more than {MAX_FEATURES:,} features). "
                "Simplify it or split it in several layers"
            )

        geometries: list[GisGeometry] = []
        vertex_count = 0
        skipped = 0
        unsupported = 0

        for feature in features:
            flattened = self._flatten(feature)
            if len(flattened) == 0:
                unsupported += 1
                continue

            for kind, parts in flattened:
                projected_parts = []
                for part in parts:
                    # ignore the z and m values
                    xs = [c[0] for c in part if len(c) >= 2]
                    ys = [c[1] for c in part if len(c) >= 2]
                    merc_x, merc_y = projector.lonlat_to_merc_many(xs, ys)
                    # the coordinates that cannot be projected are infinite
                    points = [
                        (x, y)
                        for x, y in zip(merc_x, merc_y)
                        if math.isfinite(x) and math.isfinite(y)
                    ]
                    minimum = {"point": 1, "line": 2, "polygon": 3}[kind]
                    if len(points) < minimum:
                        skipped += 1
                        continue
                    projected_parts.append(points)
                    vertex_count += len(points)

                if vertex_count > MAX_VERTICES:
                    raise GisLayerError(
                        f"The layer is too large (more than {MAX_VERTICES:,} "
                        "vertices). Simplify it or split it in several layers"
                    )
                if len(projected_parts) > 0:
                    geometries.append(GisGeometry(kind=kind, parts=projected_parts))

        warnings = []
        if unsupported > 0:
            warnings.append(f"{unsupported} feature(s) have no supported geometry")
        if skipped > 0:
            warnings.append(
                f"{skipped} geometry part(s) were ignored, as they cannot be "
                "projected or have too few vertices"
            )
        return geometries, vertex_count, warnings


class GisPointItem(QGraphicsItem):
    """
    A point of a layer. It has a constant size on screen, whatever the zoom is.
    """

    def __init__(self, layer: GisLayerConfig):
        """
        Initialises the point.
        :param layer: The layer configuration with the style.
        """
        super().__init__()
        self.pen = QPen(layer.stroke_color)
        self.pen.setWidthF(1.0)
        self.color = layer.stroke_color
        self.radius = max(3.0, layer.stroke_width * 2)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self) -> QRectF:
        margin = self.radius + 1
        return QRectF(-margin, -margin, margin * 2, margin * 2)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self.pen)
        painter.setBrush(self.color)
        painter.drawEllipse(QPointF(0, 0), self.radius, self.radius)


class GisPathItem(QGraphicsPathItem):
    """
    A line or a polygon of a layer.
    """

    def __init__(self, path: QPainterPath, layer: GisLayerConfig, is_polygon: bool):
        """
        Initialises the item.
        :param path: The path in scene coordinates.
        :param layer: The layer configuration with the style.
        :param is_polygon: Whether the path is filled.
        """
        super().__init__(path)
        pen = QPen(layer.stroke_color)
        pen.setWidthF(layer.stroke_width)
        # the width does not change with the zoom
        pen.setCosmetic(True)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)
        if is_polygon:
            self.setBrush(layer.fill_color)
        else:
            self.setBrush(Qt.BrushStyle.NoBrush)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)


class GisLayerGroup(QGraphicsItemGroup):
    """
    The items of a layer.
    """

    def __init__(self, layer_id: str):
        """
        Initialises the group.
        :param layer_id: The layer ID.
        """
        super().__init__()
        self.layer_id = layer_id
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)


@dataclass
class GisLayerInfo:
    """
    The outcome of loading a layer, for the layer manager.
    """

    error: str | None = None
    """ The reason why the layer cannot be loaded """
    data: GisLayerData | None = None
    """ The data when the layer was loaded """

    @property
    def warnings(self) -> list[str]:
        return [] if self.data is None else self.data.warnings


class GisOverlay(QObject):
    """
    Draws the GIS layers of the model between the map tiles and the nodes. The layers
    are shown in the geographic view only, as their coordinates are geographic, and
    in the order of the model list: the first layer is at the bottom.
    """

    def __init__(self, schematic: "Schematic"):
        """
        Initialises the overlay.
        :param schematic: The schematic.
        """
        super().__init__(schematic)
        self.schematic = schematic
        self.groups: dict[str, GisLayerGroup] = {}
        self._cache: dict[str, tuple[tuple, GisLayerInfo]] = {}

    @property
    def is_active(self) -> bool:
        """
        Whether the layers must be displayed.
        :return: True in the geographic view.
        """
        return self.schematic.editor_settings.is_geo_view_enabled

    def layer_path(self, layer: GisLayerConfig) -> str:
        """
        Returns the absolute path of the layer file.
        :param layer: The layer configuration.
        :return: The path.
        """
        return self.schematic.model_config.normalize_file_path(layer.path)

    def inspect(self, layer: GisLayerConfig) -> GisLayerInfo:
        """
        Loads a layer, or returns the data loaded before when the file and the
        settings did not change. Errors are returned, not raised.
        :param layer: The layer configuration.
        :return: The outcome.
        """
        path = self.layer_path(layer)
        default_crs = self.schematic.model_config.geographic_crs
        # the sidecar files of a Shapefile hold the CRS and the attributes
        modified = []
        for file in [path] + [
            str(Path(path).with_suffix(suffix)) for suffix in (".prj", ".dbf", ".shx")
        ]:
            try:
                modified.append(os.stat(file).st_mtime_ns)
            except OSError:
                modified.append(None)
        signature = (path, tuple(modified), layer.crs, default_crs, layer.file_type)

        cached = self._cache.get(layer.id)
        if cached is not None and cached[0] == signature:
            return cached[1]

        # large files can take a while to read
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            info = GisLayerInfo(
                data=GisLayerLoader(default_crs=default_crs).load(layer, path)
            )
        except GisLayerError as error:
            info = GisLayerInfo(error=str(error))
        finally:
            QGuiApplication.restoreOverrideCursor()
        self._cache[layer.id] = (signature, info)
        return info

    def refresh(self) -> None:
        """
        Draws the visible layers again. The layers are not drawn outside the
        geographic view.
        :return: None
        """
        self.clear()
        if not self.is_active:
            return

        layers = self.schematic.model_config.gis_layers.get_all()
        # forget the layers that were deleted
        for layer_id in set(self._cache) - {layer.id for layer in layers}:
            del self._cache[layer_id]

        for index, layer in enumerate(layers):
            if not layer.visible:
                continue
            info = self.inspect(layer)
            if info.data is None:
                continue
            group = self.build_group(layer, info.data)
            group.setZValue(BASE_Z_VALUE + index * Z_VALUE_STEP)
            self.schematic.scene.addItem(group)
            self.groups[layer.id] = group

    def build_group(self, layer: GisLayerConfig, data: GisLayerData) -> GisLayerGroup:
        """
        Creates the items of a layer.
        :param layer: The layer configuration.
        :param data: The layer data.
        :return: The group.
        """
        transform = self.schematic.geo_transform
        group = GisLayerGroup(layer.id)

        for geometry in data.geometries:
            if geometry.kind == "point":
                for part in geometry.parts:
                    item = GisPointItem(layer)
                    item.setPos(*transform.merc_to_scene(*part[0]))
                    group.addToGroup(item)
                continue

            path = QPainterPath()
            path.setFillRule(Qt.FillRule.OddEvenFill)
            for part in geometry.parts:
                x, y = transform.merc_to_scene(*part[0])
                path.moveTo(x, y)
                for point in part[1:]:
                    path.lineTo(*transform.merc_to_scene(*point))
                if geometry.kind == "polygon":
                    path.closeSubpath()
            group.addToGroup(GisPathItem(path, layer, geometry.kind == "polygon"))

        return group

    def clear(self) -> None:
        """
        Removes the layers from the scene. This must be called before the scene is
        cleared, as the scene deletes its items.
        :return: None
        """
        for group in self.groups.values():
            if group.scene() is not None:
                group.scene().removeItem(group)
        self.groups = {}
